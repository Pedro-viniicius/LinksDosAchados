#!/usr/bin/env python3
"""Testes da API v1 ligada ao servidor.py (docs/produto/planos/api-achadinho-turbo.md, etapa 2).

Uso:  python3 testes/test_api_ofertas_servidor.py -v

As classes HTTP sobem o servidor.py de verdade como subprocesso (no molde do ServidorDisparo de
testes/test_disparo_servidor.py), com banco temporário, porta livre, proxy morto, agendador do
disparo desligado e ACHADINHOS_API_TOKEN_ARQUIVO apontando para um arquivo dentro do diretório
temporário. O token é gerado aqui e nunca é impresso: as asserções que o envolvem usam
assertTrue/assertFalse com mensagem fixa. Nenhum teste cria o api_token.txt do projeto, toca o
achadinhos.db real, o servidor em 8765 ou a rede. Só biblioteca padrão.
"""
import hmac
import http.client
import io
import json
import os
import re
import secrets
import shutil
import socket
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime
from http.server import ThreadingHTTPServer
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_servidor as TS  # noqa: E402  (ambiente, porta_livre, ServidorTeste, RAIZ, DB_REAL)

TMP = tempfile.mkdtemp(prefix='achadinhos-api-v1-')
# Antes do import: o servidor lê ACHADINHOS_DB ao carregar; a rede bate num proxy morto.
os.environ['ACHADINHOS_DB'] = os.path.join(TMP, 'import.db')
os.environ.update(TS.PROXIES_MORTOS)
os.environ.pop('ACHADINHOS_API_TOKEN_ARQUIVO', None)
sys.path.insert(0, TS.RAIZ)
import servidor as S     # noqa: E402
import api_ofertas as A  # noqa: E402

VAR_TOKEN = 'ACHADINHOS_API_TOKEN_ARQUIVO'
TOKEN_REAL = os.path.join(TS.RAIZ, 'api_token.txt')
ANTIGO = '2026-11-03T12:24:23'   # bem antes da folga de 60 s da ordem "atualizacao"
PRECO_EM_VELHO = '2020-01-01T00:00:00'   # mais velho que o teto de 168 h do preco_max_horas
PERFUMES = 'Perfumes e Perfumaria'
CASA = 'Casa e Decoração'
LINK_AMAZON = 'https://www.amazon.com.br/dp/B0TESTE001?tag=desejodemen01-20'
LINK_ML = 'https://meli.la/1AbCdEf'
METODOS_NAO_GET = ('POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS')
ROTAS = ('/api/v1/ofertas', '/api/v1/categorias', '/api/v1/nada', '/api/v1')
SEGREDO = 'VALORQUEOCLIENTEMANDOU'


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


def gravar_token(caminho, conteudo, modo=0o600):
    """Grava o arquivo do token já com o modo pedido (o umask não abre mais que isso)."""
    if os.path.lexists(caminho):
        os.remove(caminho)   # o anterior pode estar sem permissão de escrita (0o400)
    fd = os.open(caminho, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'wb') as f:
        f.write(conteudo)
    os.chmod(caminho, modo)


def inserir(con, **campos):
    """Item direto no banco temporário, com horários antigos (passa da folga de 60 s)."""
    base = {'loja': 'amazon', 'item_id': 'B0TESTE001', 'cat': PERFUMES, 'busca': 'perfume', 'url': LINK_AMAZON,
            'titulo': 'Perfume Teste 100ml', 'preco': 'R$ 100,00', 'preco_antigo': 'R$ 150,00', 'desconto': '',
            'avaliacao': '4,5 de 5 estrelas', 'num_avaliacoes': '1.234', 'vendas': 'Mais de 50 compras',
            'frete': 'Frete GRÁTIS', 'cupom': '', 'imagem': 'https://m.media-amazon.com/images/I/71teste.jpg',
            'tem_dados': 1, 'posicao': 1, 'criado_em': ANTIGO, 'atualizado_em': ANTIGO}
    base.update(campos)
    con.execute(f"INSERT INTO items ({','.join(base)}) VALUES ({','.join('?' * len(base))})", list(base.values()))


class ServidorApi(TS.ServidorTeste):
    """servidor.py com o arquivo do token num diretório temporário. CONTEUDO(token) dá os bytes do
    arquivo (None: o arquivo não existe); MODO é a permissão dele."""
    MODO = 0o600

    @staticmethod
    def CONTEUDO(token):
        return token.encode() + b'\n'

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix='achadinhos-api-srv-')
        cls.addClassCleanup(shutil.rmtree, cls.dir, ignore_errors=True)
        cls.db = os.path.join(cls.dir, 'teste.db')
        cls.arquivo_token = os.path.join(cls.dir, 'api_token.txt')
        cls.token = secrets.token_urlsafe(32)
        conteudo = cls.CONTEUDO(cls.token)
        if conteudo is not None:
            gravar_token(cls.arquivo_token, conteudo, cls.MODO)
        cls.porta = TS.porta_livre()
        cls.log_err = open(os.path.join(cls.dir, 'stderr.log'), 'wb')
        cls.addClassCleanup(cls.log_err.close)
        env = TS.ambiente(cls.db, cls.porta)
        env.update({VAR_TOKEN: cls.arquivo_token, 'ACHADINHOS_DISPARO': '0'})
        cls.proc = subprocess.Popen([sys.executable, '-u', 'servidor.py'], cwd=TS.RAIZ, env=env,
                                    stdout=subprocess.PIPE, stderr=cls.log_err)
        cls.addClassCleanup(cls.parar_servidor)
        cls.primeira_linha = cls.proc.stdout.readline().decode()
        for _ in range(100):
            try:
                socket.create_connection(('127.0.0.1', cls.porta), timeout=0.2).close()
                break
            except OSError:
                if cls.proc.poll() is not None:
                    break
                time.sleep(0.05)
        if cls.proc.poll() is not None:
            raise RuntimeError('o servidor de teste saiu: ' + cls.primeira_linha)
        con = sqlite3.connect(cls.db)
        # preço da Amazon confirmado agora (relógio do servidor), o do ML há anos (atualizar-precos, CA8)
        cls.preco_em_amazon = datetime.now().isoformat(timespec='seconds')
        inserir(con, preco_em=cls.preco_em_amazon)
        inserir(con, loja='ml', item_id='MLB4100000001', cat=CASA, url=LINK_ML, titulo='Luminária de mesa',
                preco='R$ 59,90', preco_antigo='', imagem='https://http2.mlstatic.com/D_teste.jpg', posicao=2,
                preco_em=PRECO_EM_VELHO)
        # fora da API: ML sem link de afiliado e título com cara de link
        inserir(con, loja='ml', item_id='MLB4100000002', cat=CASA,
                url='https://produto.mercadolivre.com.br/MLB-4100000002',
                posicao=3)
        inserir(con, item_id='B0TESTE003', url='https://www.amazon.com.br/dp/B0TESTE003?tag=desejodemen01-20',
                titulo='Capinha i.Phone 15', posicao=4)
        con.commit()
        con.close()

    # ------------------------------------------------------------ apoio
    def auth(self, token=None, **extra):
        return {'Authorization': f'Bearer {self.token if token is None else token}', **extra}

    def v1(self, caminho, headers=None, metodo='GET', host=None):
        h = dict(headers or {})
        if host is not None:
            h['Host'] = host
        st, hd, dados = self.pedir(metodo, caminho, headers=h)
        self.assertFalse([k for k in hd.keys() if k.lower().startswith('access-control-')],
                         f'{metodo} {caminho} respondeu com cabeçalho de CORS')
        corpo = json.loads(dados) if dados else None
        return st, hd, corpo

    def cru(self, dados):
        """Manda bytes crus (linha malformada, cabeçalho repetido) e devolve a resposta inteira."""
        with socket.create_connection(('127.0.0.1', self.porta), timeout=10) as s:
            s.sendall(dados)
            partes = []
            while True:
                b = s.recv(65536)
                if not b:
                    break
                partes.append(b)
        return b''.join(partes)

    def saida(self):
        """stdout (primeira linha) + stderr inteiro do servidor até agora."""
        self.log_err.flush()
        time.sleep(0.05)   # o log de acesso sai antes do corpo, mas dá folga ao processo
        with open(os.path.join(self.dir, 'stderr.log'), encoding='utf-8', errors='replace') as f:
            return self.primeira_linha + f.read()

    def dump(self):
        con = sqlite3.connect(f'file:{self.db}?mode=ro', uri=True)
        try:
            return list(con.iterdump()), con.execute('PRAGMA user_version').fetchone()[0]
        finally:
            con.close()


class TestApiLigada(ServidorApi):

    def test_ca9_primeira_linha_do_stdout_continua_igual(self):
        self.assertEqual(self.primeira_linha, f'Site em http://localhost:{self.porta}/  (banco: {self.db})\n')

    def test_ca6_stderr_diz_ligada_com_o_caminho_e_sem_aviso(self):
        saida = self.saida()
        self.assertIn(f'API v1 ligada (token em {self.arquivo_token})', saida)
        self.assertNotIn('aviso', saida)
        self.assertFalse(self.token in saida, 'o token apareceu no log')

    def test_ca1_ofertas_com_token_da_200_no_formato(self):
        st, hd, j = self.v1('/api/v1/ofertas', self.auth())
        self.assertEqual(st, 200, j)
        self.assertEqual(hd.get('Content-Type'), 'application/json; charset=utf-8')
        self.assertEqual(sorted(j), ['ofertas', 'proximo', 'total', 'versao'])
        self.assertEqual(j['versao'], 1)
        self.assertEqual(j['total'], 2)
        self.assertEqual(j['proximo'], f'{ANTIGO}~2')   # ordem atualizacao: cursor da última da página
        self.assertEqual([o['chave'] for o in j['ofertas']], ['amazon:B0TESTE001', 'ml:MLB4100000001'])
        amazon = j['ofertas'][0]
        self.assertEqual(amazon['link'], LINK_AMAZON)
        self.assertEqual(amazon['preco'], 100.0)
        self.assertEqual(amazon['preco_antigo'], 150.0)
        self.assertEqual(amazon['desconto_pct'], 33)
        self.assertIs(amazon['frete_gratis'], True)
        self.assertEqual(list(amazon), ['id', 'chave', 'loja', 'item_id', 'categoria', 'busca', 'titulo', 'link',
                                        'imagem', 'preco', 'preco_antigo', 'desconto_pct', 'vendas', 'avaliacao',
                                        'num_avaliacoes', 'frete_gratis', 'cupom', 'criado_em', 'atualizado_em',
                                        'genero', 'preco_em'])

    def test_ca8_preco_em_e_preco_max_horas_pelo_http(self):
        st, _, j = self.v1('/api/v1/ofertas', self.auth())   # sem o filtro: as duas, cada uma com a sua data
        self.assertEqual((st, j['total']), (200, 2), j)
        self.assertEqual({o['chave']: o['preco_em'] for o in j['ofertas']},
                         {'amazon:B0TESTE001': self.preco_em_amazon, 'ml:MLB4100000001': PRECO_EM_VELHO})
        for query in ('preco_max_horas=1', 'preco_max_horas=168&ordem=menor_preco', 'preco_max_horas=24&loja=amazon'):
            with self.subTest(query=query):
                st, _, j = self.v1('/api/v1/ofertas?' + query, self.auth())
                self.assertEqual((st, j['total'], [o['chave'] for o in j['ofertas']]),
                                 (200, 1, ['amazon:B0TESTE001']), j)
        st, _, j = self.v1('/api/v1/ofertas?preco_max_horas=24&loja=ml', self.auth())
        self.assertEqual((st, j['total'], j['ofertas'], j['proximo']), (200, 0, [], None), j)
        for query in ('preco_max_horas=0', 'preco_max_horas=169', 'preco_max_horas=', f'preco_max_horas={SEGREDO}',
                      'preco_max_horas=1&preco_max_horas=1'):
            with self.subTest(query=query):
                st, _, j = self.v1('/api/v1/ofertas?' + query, self.auth())
                self.assertEqual((st, list(j)), (400, ['error']), j)
                self.assertIn('preco_max_horas', j['error'])
                self.assertNotIn(SEGREDO, j['error'])
        st, _, j = self.v1('/api/v1/categorias?preco_max_horas=24', self.auth())
        self.assertEqual(st, 400, j)

    def test_ca1_paginacao_e_filtros_pelo_http(self):
        st, _, j = self.v1('/api/v1/ofertas?limite=1', self.auth())
        self.assertEqual((st, len(j['ofertas'])), (200, 1))
        st, _, j2 = self.v1('/api/v1/ofertas?limite=1&cursor=' + j['proximo'].replace(':', '%3A'), self.auth())
        self.assertEqual(st, 200, j2)
        self.assertEqual(j2['ofertas'][0]['chave'], 'ml:MLB4100000001')
        st, _, j = self.v1('/api/v1/ofertas?cat=Casa+e+Decora%C3%A7%C3%A3o&loja=ml&ordem=menor_preco', self.auth())
        self.assertEqual((st, j['total'], j['ofertas'][0]['categoria']), (200, 1, CASA))
        st, _, j = self.v1('/api/v1/ofertas?q=PERFUME&loja=amazon&loja=ml', self.auth())
        self.assertEqual((st, j['total']), (200, 1))

    def test_ca3_parametro_invalido_da_400_em_portugues(self):
        for query in ('limite=0', 'limite=201', f'limite={SEGREDO}', f'{SEGREDO}=1', 'q=', 'cat=', 'q',
                      'ordem=aleatoria', 'ordem=x', 'desconto_min=100', 'loja=ebay', 'limite=1&limite=2',
                      'cursor=lixo', 'loja=ml&loja=ml'):
            with self.subTest(query=query):
                st, _, j = self.v1('/api/v1/ofertas?' + query, self.auth())
                self.assertEqual(st, 400, j)
                self.assertEqual(list(j), ['error'])
                self.assertRegex(j['error'], r'[a-zà-ú]{3,}')
                self.assertNotIn(SEGREDO, j['error'])

    def test_ca5_categorias_no_formato_do_plano(self):
        st, _, j = self.v1('/api/v1/categorias', self.auth())
        self.assertEqual(st, 200, j)
        self.assertEqual(j, {'versao': 1, 'total': 2, 'categorias': [
            {'nome': CASA, 'total': 1, 'lojas': {'amazon': 0, 'ml': 1, 'shopee': 0},
             'generos': {'feminino': 0, 'masculino': 0, 'unissex': 0, 'sem': 1}},
            {'nome': PERFUMES, 'total': 1, 'lojas': {'amazon': 1, 'ml': 0, 'shopee': 0},
             'generos': {'feminino': 0, 'masculino': 0, 'unissex': 0, 'sem': 1}}]})
        st, _, j = self.v1('/api/v1/categorias?limite=1', self.auth())
        self.assertEqual(st, 400, j)

    def test_rota_v1_desconhecida_com_token_da_404(self):
        for caminho in ('/api/v1/nada', '/api/v1', '/api/v1/', '/api/v1/ofertas/', '/api/v1/ofertas/1',
                        '/api/v1/OFERTAS', '/api/v1/../items'):
            with self.subTest(caminho=caminho):
                st, _, j = self.v1(caminho, self.auth())
                self.assertEqual(st, 404, j)

    def test_ca6_sem_authorization_da_401_com_www_authenticate(self):
        for caminho in ROTAS:
            with self.subTest(caminho=caminho):
                st, hd, j = self.v1(caminho)
                self.assertEqual(st, 401, j)
                self.assertEqual(hd.get('WWW-Authenticate'), 'Bearer')
                self.assertIn('error', j)

    def test_ca6_token_errado_ou_mal_formado_da_401(self):
        errado = secrets.token_urlsafe(32)
        ruins = {'outro token': f'Bearer {errado}', 'sem a última letra': f'Bearer {self.token[:-1]}',
                 'com letra a mais': f'Bearer {self.token}x', 'só o token': self.token,
                 'Basic': f'Basic {self.token}', 'Token': f'Token {self.token}', 'Bearer vazio': 'Bearer',
                 'Bearer e espaço': 'Bearer ', 'com sufixo': f'Bearer {self.token} extra',
                 'tab no lugar do espaço': f'Bearer\t{self.token}', 'não ASCII': f'Bearer {self.token}é'}
        for nome, valor in ruins.items():
            with self.subTest(caso=nome):
                st, hd, j = self.v1('/api/v1/categorias', {'Authorization': valor})
                self.assertEqual(st, 401, j)
                self.assertEqual(hd.get('WWW-Authenticate'), 'Bearer')

    def test_ca6_esquema_bearer_nao_diferencia_caixa_e_aceita_varios_espacos(self):
        # RFC 7235: o esquema não diferencia caixa e vem seguido de 1*SP
        for valor in (f'bearer {self.token}', f'BEARER {self.token}', f'Bearer {self.token}',
                      f'Bearer   {self.token}', f'  Bearer {self.token}  '):
            with self.subTest(caso=valor.replace(self.token, '<token>')):
                st, _, j = self.v1('/api/v1/categorias', {'Authorization': valor})
                self.assertEqual(st, 200, j)

    def test_ca6_dois_cabecalhos_authorization_da_401(self):
        r = self.cru((f'GET /api/v1/categorias HTTP/1.1\r\nHost: localhost:{self.porta}\r\n'
                      f'Authorization: Bearer {self.token}\r\nAuthorization: Bearer {self.token}\r\n'
                      'Connection: close\r\n\r\n').encode())
        self.assertTrue(r.startswith(b'HTTP/1.0 401'), r[:40])

    def test_ca6_token_na_query_nao_autentica_nem_volta_na_resposta(self):
        st, hd, j = self.v1(f'/api/v1/ofertas?token={self.token}')
        self.assertEqual(st, 401, j)
        self.assertFalse(self.token in json.dumps(j) + str(hd), 'o token voltou na resposta')
        st, hd, j = self.v1(f'/api/v1/ofertas?token={self.token}', self.auth())
        self.assertEqual(st, 400, j)   # parâmetro desconhecido
        self.assertFalse(self.token in json.dumps(j) + str(hd), 'o token voltou na resposta')

    def test_ca6_token_nunca_aparece_no_log(self):
        self.v1(f'/api/v1/ofertas?token={self.token}')
        self.v1(f'/api/v1/ofertas?cat=x&token={self.token}', self.auth())
        self.v1(f'/api/v1/{self.token}', self.auth())
        self.v1('/api/v1/categorias', self.auth())
        respostas = [
            self.cru(f'GET /api/v1/ofertas?t={self.token} HTTP/1.1 {self.token}\r\n\r\n'.encode()),
            self.cru(f'GET /api/v1/ofertas {self.token}\r\n\r\n'.encode()),
            self.cru(f'{self.token} /api/v1/ofertas HTTP/1.1\r\n\r\n'.encode()),
            self.cru(f'GET /api/v1/ofertas HTTP/1.1\r\nHost: localhost:{self.porta}\r\n'
                     f'Authorization: Bearer {self.token}\r\nConnection: close\r\n\r\n'.encode())]
        saida = self.saida()
        self.assertFalse(self.token in saida, 'o token apareceu no log do servidor')
        # S1: nem a página de erro do http.server (linha malformada, método sem do_X) repete o token
        self.assertFalse(any(self.token.encode() in r for r in respostas), 'o token voltou na resposta')
        # o log segue útil: rota conhecida aparece, a query vira "?(omitida)" e o resto vira "(outra rota)"
        self.assertIn('"GET /api/v1/ofertas?(omitida) HTTP/1.1" 401', saida)
        self.assertIn('"GET /api/v1/categorias HTTP/1.1" 200', saida)
        self.assertIn('"GET /api/v1/(outra rota) HTTP/1.1" 404', saida)

    def test_s1_erro_do_http_server_nao_repete_o_que_o_cliente_mandou(self):
        casos = {'TRACE /api/v1/ofertas HTTP/1.1': b'501', 'CONNECT /api/v1/ofertas HTTP/1.1': b'501',
                 f'METODOX{SEGREDO} /api/v1/ofertas HTTP/1.1': b'501',
                 f'GET /api/v1/ofertas?x={SEGREDO} HTTP/1.1 sobra': b'400',
                 f'GET /api/v1/ofertas?x={SEGREDO} HTTP/9': b'400',
                 f'TRACE /api/items?x={SEGREDO} HTTP/1.1': b'501', f'TRACE /{SEGREDO} HTTP/1.1': b'501'}
        for linha, codigo in casos.items():
            with self.subTest(linha=linha):
                r = self.cru(f'{linha}\r\nHost: localhost:{self.porta}\r\n\r\n'.encode())
                # linha malformada recebe resposta no estilo HTTP/0.9 (só o corpo), como no http.server
                self.assertIn(b'Error code: ' + codigo, r)
                for pedaco in (b'TRACE', b'CONNECT', b'METODOX', b'/api/', SEGREDO.encode(), b'sobra', b'HTTP/9'):
                    self.assertNotIn(pedaco, r)
                self.assertNotIn(b'access-control-', r.lower())

    def test_ca7_origin_ate_a_local_da_403(self):
        for origem in (f'http://localhost:{self.porta}', f'http://127.0.0.1:{self.porta}',
                       'https://lista.mercadolivre.com.br', 'https://www.mercadolivre.com.br', 'null',
                       'https://evil.example', ''):
            for caminho in ('/api/v1/ofertas', '/api/v1/categorias'):
                with self.subTest(origem=origem, caminho=caminho):
                    st, _, j = self.v1(caminho, self.auth(Origin=origem))
                    self.assertEqual(st, 403, j)

    def test_ca7_sec_fetch_site_qualquer_da_403(self):
        for valor in ('none', 'same-origin', 'same-site', 'cross-site', ''):
            with self.subTest(sec_fetch_site=valor):
                st, _, j = self.v1('/api/v1/ofertas', self.auth(**{'Sec-Fetch-Site': valor}))
                self.assertEqual(st, 403, j)

    def test_ca7_403_vem_antes_do_401(self):
        st, hd, _ = self.v1('/api/v1/ofertas', {'Origin': f'http://localhost:{self.porta}'})
        self.assertEqual(st, 403)
        self.assertIsNone(hd.get('WWW-Authenticate'))

    def test_ca7_metodo_diferente_de_get_da_405_so_depois_da_autenticacao(self):
        for metodo in METODOS_NAO_GET:
            for caminho in ROTAS:
                with self.subTest(metodo=metodo, caminho=caminho):
                    st, hd, _ = self.v1(caminho, metodo=metodo)
                    self.assertEqual(st, 401)
                    self.assertEqual(hd.get('WWW-Authenticate'), 'Bearer')
                    st, hd, _ = self.v1(caminho, self.auth(), metodo=metodo)
                    self.assertEqual(st, 405)
                    self.assertEqual(hd.get('Allow'), 'GET')

    def test_ca7_preflight_do_ml_nao_ganha_cors(self):
        st, _, _ = self.v1('/api/v1/ofertas', {'Origin': 'https://lista.mercadolivre.com.br',
                                               'Access-Control-Request-Method': 'GET',
                                               'Access-Control-Request-Headers': 'authorization'}, metodo='OPTIONS')
        self.assertEqual(st, 403)

    def test_ca7_host_continua_obrigatorio(self):
        for host in ('evil.example', f'evil.example:{self.porta}', 'localhost', f'localhost:{self.porta + 1}',
                     f'0.0.0.0:{self.porta}'):
            with self.subTest(host=host):
                st, _, j = self.v1('/api/v1/categorias', self.auth(), host=host)
                self.assertEqual(st, 403, j)
                self.assertEqual(j, {'error': 'host não permitido'})
        st, _, _ = self.pedir('GET', '/api/v1/categorias', headers=self.auth(), sem_host=True)
        self.assertEqual(st, 403)
        st, _, j = self.v1('/api/v1/categorias', self.auth(), host=f'127.0.0.1:{self.porta}')
        self.assertEqual(st, 200, j)

    def test_ca9_v1_nao_grava_no_banco(self):
        antes = self.dump()
        for caminho in ('/api/v1/ofertas', '/api/v1/ofertas?ordem=relevancia', '/api/v1/categorias',
                        '/api/v1/ofertas?limite=0'):
            self.v1(caminho, self.auth())
        for metodo in METODOS_NAO_GET:
            self.v1('/api/v1/ofertas', self.auth(), metodo=metodo)
        self.assertEqual(self.dump(), antes)

    def test_ca9_rotas_antigas_seguem_iguais(self):
        st, hd, j = self.v1('/api/items')   # sem Origin: continua aberto (risco aceito R1)
        self.assertEqual((st, len(j)), (200, 4))
        st, _, _ = self.pedir('GET', '/api/items', headers=self.local())
        self.assertEqual(st, 200)
        st, _, _ = self.pedir('GET', '/api/items', headers={'Origin': 'https://evil.example'})
        self.assertEqual(st, 403)
        st, _, _ = self.pedir('GET', '/api/disparo/regras', headers=self.local())
        self.assertEqual(st, 200)
        st, _, _ = self.pedir('GET', '/api/v2/ofertas', headers=self.auth())
        self.assertEqual(st, 404)


class TestApiDesligadaSemArquivo(ServidorApi):
    """CA6: sem arquivo de token, toda rota /api/v1/ dá 503 e o servidor sobe normalmente."""

    @staticmethod
    def CONTEUDO(token):
        return None

    def test_ca6_toda_rota_v1_da_503_com_ou_sem_bearer(self):
        for metodo in ('GET',) + METODOS_NAO_GET:
            for caminho in ROTAS + ('/api/v1/ofertas?limite=0',):
                for headers in ({}, self.auth()):
                    with self.subTest(metodo=metodo, caminho=caminho, bearer=bool(headers)):
                        st, hd, j = self.v1(caminho, headers, metodo=metodo)
                        self.assertEqual(st, 503)
                        self.assertIsNone(hd.get('WWW-Authenticate'))
                        if metodo != 'HEAD':
                            # R3: o motivo certo (ausente, inválido, outro caminho) está no log, não aqui
                            self.assertEqual(j, {'error': 'a API v1 está desligada: veja o motivo no log do servidor'})

    def test_ca7_403_vem_antes_do_503(self):
        st, _, _ = self.v1('/api/v1/ofertas', {'Sec-Fetch-Site': 'same-origin'})
        self.assertEqual(st, 403)

    def test_ca6_servidor_sobe_normalmente(self):
        self.assertEqual(self.primeira_linha, f'Site em http://localhost:{self.porta}/  (banco: {self.db})\n')
        st, _, j = self.v1('/api/items')
        self.assertEqual((st, len(j)), (200, 4))
        self.assertIn(f'API v1 desligada: arquivo do token não encontrado ({self.arquivo_token})', self.saida())


class TestApiDesligadaTokenCurto(ServidorApi):
    """CA6: token com 31 caracteres válidos deixa a API desligada, inclusive para quem manda esse token."""

    @staticmethod
    def CONTEUDO(token):
        return token[:31].encode()

    def test_ca6_token_curto_da_503(self):
        st, _, j = self.v1('/api/v1/categorias', self.auth(self.token[:31]))
        self.assertEqual(st, 503, j)
        saida = self.saida()
        self.assertIn('API v1 desligada: token inválido', saida)
        self.assertFalse(self.token[:31] in saida, 'o token apareceu no log')


class TestApiDesligadaTokenComCaractereInvalido(ServidorApi):
    """CA6: token longo com caractere fora de [A-Za-z0-9_-] deixa a API desligada."""

    @staticmethod
    def CONTEUDO(token):
        return (token[:20] + '.' + token[20:]).encode()

    def test_ca6_token_com_ponto_da_503(self):
        invalido = self.token[:20] + '.' + self.token[20:]
        st, _, j = self.v1('/api/v1/categorias', self.auth(invalido))
        self.assertEqual(st, 503, j)
        saida = self.saida()
        self.assertIn('API v1 desligada: token inválido', saida)
        self.assertFalse(self.token[:20] in saida or self.token[20:] in saida, 'o token apareceu no log')


class TestApiPermissaoAberta(ServidorApi):
    """Arquivo legível por grupo e outros: a API liga, mas o servidor avisa (sem o token)."""
    MODO = 0o644

    def test_aviso_de_permissao_e_api_ligada(self):
        st, _, j = self.v1('/api/v1/categorias', self.auth())
        self.assertEqual(st, 200, j)
        saida = self.saida()
        self.assertIn('API v1 ligada', saida)
        self.assertIn('API v1: aviso: o arquivo do token pode ser lido por outros usuários '
                      f'(use chmod 600 {self.arquivo_token})', saida)
        self.assertFalse(self.token in saida, 'o token apareceu no log')


class TestAmbienteDeTesteIgnoraTokenReal(unittest.TestCase):
    """R4: o ambiente() dos testes deixa a v1 desligada mesmo com um api_token.txt ao lado do servidor.py.

    Prova numa CÓPIA (servidor.py, api_ofertas.py, disparo.py e genero.py num diretório temporário),
    com um api_token.txt falso ao lado; o api_token.txt do projeto nunca é criado.
    """

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix='achadinhos-copia-token-')
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        for f in ('servidor.py', 'api_ofertas.py', 'disparo.py', 'genero.py'):
            shutil.copy(os.path.join(TS.RAIZ, f), self.dir)
        self.token = secrets.token_urlsafe(32)
        gravar_token(os.path.join(self.dir, 'api_token.txt'), self.token.encode())

    def subir_e_pedir(self, env):
        """Sobe a cópia com esse ambiente, faz um GET /api/v1/categorias com o token falso e para."""
        porta = int(env['ACHADINHOS_PORTA'])
        with open(os.path.join(self.dir, 'stderr.log'), 'wb') as err:
            proc = subprocess.Popen([sys.executable, '-u', 'servidor.py'], cwd=self.dir, env=env,
                                    stdout=subprocess.DEVNULL, stderr=err)
            try:
                for _ in range(100):
                    try:
                        socket.create_connection(('127.0.0.1', porta), timeout=0.2).close()
                        break
                    except OSError:
                        self.assertIsNone(proc.poll(), 'a cópia do servidor não subiu')
                        time.sleep(0.05)
                con = http.client.HTTPConnection('127.0.0.1', porta, timeout=10)
                try:
                    con.request('GET', '/api/v1/categorias', headers={'Host': f'localhost:{porta}',
                                                                      'Authorization': f'Bearer {self.token}'})
                    st = con.getresponse().status
                finally:
                    con.close()
            finally:
                proc.terminate()
                proc.wait(5)
        with open(os.path.join(self.dir, 'stderr.log'), encoding='utf-8', errors='replace') as f:
            return st, f.read()

    def test_r4_ambiente_deixa_a_v1_desligada_com_token_ao_lado_do_servidor(self):
        env = TS.ambiente(os.path.join(self.dir, 'teste.db'), TS.porta_livre())
        env['ACHADINHOS_DISPARO'] = '0'
        st, log = self.subir_e_pedir(env)
        self.assertEqual(st, 503, 'o servidor de teste leu o api_token.txt ao lado do servidor.py')
        self.assertFalse(os.path.exists(env[VAR_TOKEN]), 'o caminho sem token existe')
        self.assertIn(f'API v1 desligada: arquivo do token não encontrado ({TS.SEM_TOKEN_API})', log)
        self.assertFalse(self.token in log, 'o token apareceu no log')

    def test_r4_controle_sem_a_variavel_a_copia_le_o_token_falso(self):
        # prova que o api_token.txt falso seria lido: o ambiente() é que o desliga
        env = TS.ambiente(os.path.join(self.dir, 'teste.db'), TS.porta_livre())
        env['ACHADINHOS_DISPARO'] = '0'
        env.pop(VAR_TOKEN, None)
        st, log = self.subir_e_pedir(env)
        self.assertEqual(st, 200)
        self.assertIn(f"API v1 ligada (token em {os.path.join(self.dir, 'api_token.txt')})", log)

    def test_r4_todo_teste_que_sobe_o_servidor_passa_o_arquivo_do_token(self):
        """Guarda estática: quem sobe o servidor.py em testes/ usa o ambiente() ou define a variável."""
        pasta = os.path.join(TS.RAIZ, 'testes')
        vistos = []
        for nome in sorted(os.listdir(pasta)):
            if not nome.endswith(('.py', '.mjs')):
                continue
            with open(os.path.join(pasta, nome), encoding='utf-8') as f:
                fonte = f.read()
            if nome.endswith('.mjs'):
                sobe = re.search(r"spawn\([^)]*'servidor\.py'", fonte)
                ok = VAR_TOKEN in fonte
            else:
                sobe = re.search(r"\[sys\.executable, '-u', 'servidor\.py'\]", fonte)
                ok = 'ambiente(' in fonte or VAR_TOKEN in fonte
            if sobe:
                vistos.append(nome)
                self.assertTrue(ok, f'{nome} sobe o servidor.py sem desligar a API v1')
        self.assertTrue({'test_servidor.py', 'coletar_ml.test.mjs', 'coletar_ml_qa.test.mjs',
                         'api_ofertas.test.mjs'} <= set(vistos), vistos)


# ------------------------------------------------------------------ unidade (sem subprocesso)
class TestCarregarToken(unittest.TestCase):
    """carregar_token_api: só arquivo regular, ASCII, 32+ caracteres de [A-Za-z0-9_-], sem vazar o conteúdo."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(dir=TMP)
        self.caminho = os.path.join(self.dir, 'api_token.txt')

    def carregar(self, conteudo, modo=0o600):
        gravar_token(self.caminho, conteudo, modo)
        return S.carregar_token_api(self.caminho)

    def test_ca6_validos(self):
        token = secrets.token_urlsafe(32)
        for nome, conteudo, esperado in (
                ('token_urlsafe(32)', token.encode(), token),
                ('com quebra de linha', token.encode() + b'\n', token),
                ('com espaços e CRLF nas pontas', b'  \t' + token.encode() + b' \r\n', token),
                ('exatamente 32', b'a' * 31 + b'_', 'a' * 31 + '_'),
                ('hífen e sublinhado', b'-_' * 16, '-_' * 16),
                ('4096 bytes', b'A' * S.MAX_ARQUIVO_TOKEN, 'A' * S.MAX_ARQUIVO_TOKEN)):
            with self.subTest(caso=nome):
                t, motivo = self.carregar(conteudo)
                self.assertTrue(t == esperado, 'token lido diferente do esperado')
                self.assertEqual(motivo, '')

    def test_ca6_invalidos_desligam_sem_mostrar_o_conteudo(self):
        token = secrets.token_urlsafe(32)
        casos = {'vazio': b'', 'só espaços': b' \n\t ', '31 caracteres': token[:31].encode(),
                 'espaço no meio': (token[:20] + ' ' + token[20:]).encode(),
                 'quebra de linha no meio': (token[:20] + '\n' + token[20:]).encode(),
                 'ponto': (token + '.').encode(), 'mais': (token + '+').encode(), 'igual': (token + '=').encode(),
                 'barra': (token + '/').encode(), 'acento': (token + 'é').encode(),
                 'BOM': b'\xef\xbb\xbf' + token.encode(), 'binário': b'\xff' * 40,
                 'NUL': token.encode() + b'\x00', 'grande demais': b'A' * (S.MAX_ARQUIVO_TOKEN + 1),
                 'duas linhas': (token + '\n' + token).encode()}
        for nome, conteudo in casos.items():
            with self.subTest(caso=nome):
                t, motivo = self.carregar(conteudo)
                self.assertIsNone(t)
                self.assertTrue(motivo)
                self.assertFalse(token[:10] in motivo or token[-10:] in motivo, 'o motivo trouxe o token')

    def test_ca6_arquivo_ausente(self):
        self.assertEqual(S.carregar_token_api(self.caminho), (None, 'arquivo do token não encontrado'))

    def test_ca6_diretorio_e_fifo_nao_travam(self):
        os.mkdir(self.caminho)
        t, motivo = S.carregar_token_api(self.caminho)
        self.assertIsNone(t)
        self.assertTrue(motivo)
        fifo = os.path.join(self.dir, 'fifo')
        os.mkfifo(fifo)
        inicio = time.monotonic()
        t, motivo = S.carregar_token_api(fifo)
        self.assertLess(time.monotonic() - inicio, 2)
        self.assertEqual((t, motivo), (None, 'o caminho do token não é um arquivo comum'))

    @unittest.skipIf(hasattr(os, 'geteuid') and os.geteuid() == 0, 'root lê arquivo sem permissão')
    def test_ca6_arquivo_sem_permissao_de_leitura(self):
        t, motivo = self.carregar(secrets.token_urlsafe(32).encode(), modo=0o000)
        self.assertIsNone(t)
        self.assertEqual(motivo, 'não consegui abrir o arquivo do token (PermissionError)')

    def test_aviso_quando_grupo_ou_outros_podem_ler(self):
        token = secrets.token_urlsafe(32).encode()
        for modo, avisa in ((0o600, False), (0o400, False), (0o640, True), (0o604, True), (0o644, True),
                            (0o660, True)):
            with self.subTest(modo=oct(modo)):
                t, motivo = self.carregar(token, modo)
                self.assertTrue(t == token.decode(), 'token não lido')
                self.assertEqual(bool(motivo), avisa)
                if avisa:
                    self.assertIn('chmod 600', motivo)

    def test_padrao_e_api_token_txt_ao_lado_do_servidor_e_a_variavel_troca(self):
        env = {k: v for k, v in os.environ.items() if k != VAR_TOKEN}
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        codigo = 'import servidor as S; print(S.API_TOKEN_ARQUIVO); print(S.API_TOKEN)'
        r = subprocess.run([sys.executable, '-c', codigo], cwd=TS.RAIZ, env=env, capture_output=True, text=True,
                           timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.split(), [TOKEN_REAL, 'None'])   # importado: nunca lê o arquivo
        env[VAR_TOKEN] = self.caminho
        r = subprocess.run([sys.executable, '-c', codigo], cwd=TS.RAIZ, env=env, capture_output=True, text=True,
                           timeout=30)
        self.assertEqual(r.stdout.split(), [self.caminho, 'None'])

    def test_gitignore_cobre_o_arquivo_do_token(self):
        r = subprocess.run(['git', 'check-ignore', '-q', 'api_token.txt'], cwd=TS.RAIZ, timeout=30)
        self.assertEqual(r.returncode, 0, 'api_token.txt não está no .gitignore')

    def test_prefixo_vem_do_api_ofertas_importado_sob_demanda(self):
        self.assertTrue(S.eh_rota_v1('/api/v1/ofertas') and S.eh_rota_v1('/api/v1'))
        self.assertFalse(S.eh_rota_v1('/api/v10/ofertas') or S.eh_rota_v1('/api/items') or S.eh_rota_v1('/'))
        with mock.patch.object(A, 'PREFIXO', '/api/v9/'):
            self.assertTrue(S.eh_rota_v1('/api/v9/ofertas'))
            self.assertFalse(S.eh_rota_v1('/api/v1/ofertas'))
        # quem importa o servidor só pelo conectar/DB não carrega o api_ofertas (nem o disparo)
        codigo = 'import sys, servidor; print(sorted(m for m in ("api_ofertas", "disparo") if m in sys.modules))'
        r = subprocess.run([sys.executable, '-c', codigo], cwd=TS.RAIZ, capture_output=True, text=True, timeout=30,
                           env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
        self.assertEqual((r.returncode, r.stdout.strip()), (0, '[]'), r.stderr)


class TestLinhaParaLog(unittest.TestCase):

    def test_linha_v1_para_log(self):
        casos = {
            'GET /api/v1/ofertas HTTP/1.1': 'GET /api/v1/ofertas HTTP/1.1',
            'GET /api/v1/categorias HTTP/1.0': 'GET /api/v1/categorias HTTP/1.0',
            'GET /api/v1/ofertas?token=abc&cat=x HTTP/1.1': 'GET /api/v1/ofertas?(omitida) HTTP/1.1',
            'POST /api/v1/abc123segredo HTTP/1.1': 'POST /api/v1/(outra rota) HTTP/1.1',
            'GET /api/v1 HTTP/1.1': 'GET /api/v1/(outra rota) HTTP/1.1',
            'GET /api/v1/ofertas segredo': 'GET /api/v1/ofertas',
            'segredo /api/v1/ofertas HTTP/1.1': '? /api/v1/ofertas HTTP/1.1',
            'GET /api/v1/ofertas HTTP/1.1 segredo': 'GET /api/v1/ofertas',
            'GET /api/v1/ofertas segredo HTTP/1.1': 'GET /api/v1/ofertas HTTP/1.1',
            'GET http://segredo/api/v1/ofertas HTTP/1.1': 'GET /api/v1/(outra rota) HTTP/1.1',
            'GET //api/v1/ofertas?segredo HTTP/1.1': 'GET /api/v1/(outra rota)?(omitida) HTTP/1.1',
        }
        for linha, esperado in casos.items():
            with self.subTest(linha=linha):
                self.assertEqual(S.linha_v1_para_log(linha), esperado)
                self.assertNotIn('segredo', S.linha_v1_para_log(linha))


class TestHandlerEmProcesso(unittest.TestCase):
    """Handler real neste processo, com S.API_TOKEN trocado e o api_ofertas.rota substituído quando
    preciso: compare_digest sobre bytes, conexão só de leitura e erro interno sem detalhe."""

    @classmethod
    def setUpClass(cls):
        if os.path.realpath(S.DB) == TS.DB_REAL:
            raise RuntimeError('o teste tentou usar o banco real')
        S.criar_banco()
        cls.token = secrets.token_urlsafe(32)
        p = mock.patch.object(S, 'API_TOKEN', cls.token)
        p.start()
        cls.addClassCleanup(p.stop)
        porta = TS.porta_livre()
        cls.hosts = mock.patch.object(S, 'HOSTS_LOCAIS', (f'localhost:{porta}',))
        cls.hosts.start()
        cls.addClassCleanup(cls.hosts.stop)
        cls.srv = ThreadingHTTPServer(('127.0.0.1', porta), S.Handler)
        cls.porta = porta
        cls.addClassCleanup(cls.srv.server_close)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.addClassCleanup(cls.srv.shutdown)

    def get(self, caminho):
        """GET com o token; devolve (status, corpo, log do servidor durante o pedido)."""
        log = io.StringIO()
        with mock.patch('sys.stderr', log):
            con = http.client.HTTPConnection('127.0.0.1', self.porta, timeout=10)
            try:
                con.request('GET', caminho, headers={'Host': f'localhost:{self.porta}',
                                                     'Authorization': f'Bearer {self.token}'})
                r = con.getresponse()
                dados = r.read()
            finally:
                con.close()
            time.sleep(0.05)
        return r.status, json.loads(dados), log.getvalue()

    def test_ca6_compara_com_hmac_compare_digest_sobre_bytes(self):
        with mock.patch.object(S.hmac, 'compare_digest', wraps=hmac.compare_digest) as cmp:
            st, j, log = self.get('/api/v1/categorias')
        self.assertEqual(st, 200, j)
        self.assertEqual(cmp.call_count, 1)
        a, b = cmp.call_args.args
        self.assertIsInstance(a, bytes)
        self.assertIsInstance(b, bytes)
        self.assertFalse(self.token in log, 'o token apareceu no log')

    def test_ca9_conexao_da_v1_e_so_de_leitura(self):
        def grava(con, *a, **kw):
            con.execute("INSERT INTO config VALUES ('api_v1_teste', '1')")
            con.commit()
            return {}
        with mock.patch.object(A, 'rota', grava):
            st, j, log = self.get('/api/v1/categorias')
        self.assertEqual((st, j), (500, {'error': 'erro interno na API v1'}))
        self.assertIn('api v1 falhou: OperationalError', log)
        self.assertNotIn('readonly', log)
        con = sqlite3.connect(S.DB)
        try:
            self.assertIsNone(con.execute("SELECT 1 FROM config WHERE chave='api_v1_teste'").fetchone())
        finally:
            con.close()

    def test_erro_interno_vira_500_com_so_o_tipo_no_log(self):
        def quebra(*a, **kw):
            raise sqlite3.OperationalError(f'no such table: {SEGREDO}')
        with mock.patch.object(A, 'rota', quebra):
            st, j, log = self.get(f'/api/v1/ofertas?cat={SEGREDO}')
        self.assertEqual((st, j), (500, {'error': 'erro interno na API v1'}))
        self.assertIn('"GET /api/v1/ofertas?(omitida) HTTP/1.1" api v1 falhou: OperationalError', log)
        self.assertNotIn(SEGREDO, log)
        self.assertNotIn(SEGREDO, json.dumps(j))

    def test_erro_api_vira_codigo_e_mensagem(self):
        def recusa(*a, **kw):
            raise A.ErroApi(400, 'mensagem de teste')
        with mock.patch.object(A, 'rota', recusa):
            st, j, _ = self.get('/api/v1/ofertas')
        self.assertEqual((st, j), (400, {'error': 'mensagem de teste'}))

    def test_pares_vao_como_lista_com_valores_vazios(self):
        visto = {}

        def espia(con, metodo, caminho, pares, eh_afiliado, agora=None):
            visto.update(metodo=metodo, caminho=caminho, pares=pares, eh_afiliado=eh_afiliado)
            return {'ok': 1}
        with mock.patch.object(A, 'rota', espia):
            st, j, _ = self.get('/api/v1/ofertas?q=&cat=a+b&cat=c%C3%A9&limite=2')
        self.assertEqual((st, j), (200, {'ok': 1}))
        self.assertEqual(visto, {'metodo': 'GET', 'caminho': '/api/v1/ofertas', 'eh_afiliado': S.eh_link_afiliado,
                                 'pares': [('q', ''), ('cat', 'a b'), ('cat', 'cé'), ('limite', '2')]})


if __name__ == '__main__':
    unittest.main()
