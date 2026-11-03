#!/usr/bin/env python3
"""Testes do servidor.py (docs/produto/planos/blindar-servidor.md).

Uso:  python3 testes/test_servidor.py -v

Cada classe sobe o servidor.py de verdade como subprocesso, com ACHADINHOS_DB num banco novo
dentro de um diretório temporário e ACHADINHOS_PORTA numa porta livre. Nenhum teste toca o
achadinhos.db real, o servidor em 8765, a Amazon ou o Mercado Livre.
Só biblioteca padrão.
"""
import http.client
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from unittest import mock

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_REAL = os.path.realpath(os.path.join(RAIZ, 'achadinhos.db'))


def porta_livre():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


# Qualquer saída acidental para a rede (urllib) bate num proxy morto e falha na hora.
PROXY_MORTO = 'http://127.0.0.1:9'
PROXIES_MORTOS = {'http_proxy': PROXY_MORTO, 'https_proxy': PROXY_MORTO, 'ftp_proxy': PROXY_MORTO,
                  'no_proxy': ''}


def ambiente(db, porta=None):
    """Ambiente do subprocesso: sempre com banco temporário, nunca o real, e sem rede."""
    if os.path.realpath(db) == DB_REAL:
        raise RuntimeError('o teste tentou usar o banco real')
    env = dict(os.environ, ACHADINHOS_DB=db, PYTHONDONTWRITEBYTECODE='1', **PROXIES_MORTOS)
    if porta:
        env['ACHADINHOS_PORTA'] = str(porta)
    return env


class ServidorTeste(unittest.TestCase):
    """Base: sobe um servidor.py por classe, com banco e porta próprios."""

    @classmethod
    def setUpClass(cls):
        # addClassCleanup roda mesmo quando o setUpClass (este ou o de uma subclasse) falha,
        # ao contrário do tearDownClass: servidor e diretório temporário nunca vazam.
        cls.dir = tempfile.mkdtemp(prefix='achadinhos-teste-')
        cls.addClassCleanup(shutil.rmtree, cls.dir, ignore_errors=True)
        cls.db = os.path.join(cls.dir, 'teste.db')
        cls.porta = porta_livre()
        cls.log_err = open(os.path.join(cls.dir, 'stderr.log'), 'wb')
        cls.addClassCleanup(cls.log_err.close)
        cls.proc = subprocess.Popen([sys.executable, '-u', 'servidor.py'], cwd=RAIZ,
                                    env=ambiente(cls.db, cls.porta),
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
        else:
            raise RuntimeError('o servidor de teste não subiu')
        if cls.proc.poll() is not None:
            raise RuntimeError('o servidor de teste saiu: ' + cls.primeira_linha)

    @classmethod
    def parar_servidor(cls):
        if cls.proc.poll() is None:
            cls.proc.terminate()
            try:
                cls.proc.wait(5)
            except subprocess.TimeoutExpired:
                cls.proc.kill()
                cls.proc.wait()
        cls.proc.stdout.close()

    # ------------------------------------------------------------ requisições
    def local(self, host='localhost'):
        """Cabeçalhos de uma escrita feita pelo index.html aberto em http://<host>:<porta>/."""
        return {'Host': f'{host}:{self.porta}', 'Origin': f'http://{host}:{self.porta}',
                'Sec-Fetch-Site': 'same-origin'}

    def pedir(self, metodo, caminho, corpo=None, headers=None, sem_host=False):
        """Faz a requisição e devolve (status, cabeçalhos, corpo em bytes).

        Host padrão: localhost:<porta>. Corpo que não é bytes/str vira JSON com
        Content-Type application/json (a não ser que o teste mande outro).
        """
        h = {'Host': f'localhost:{self.porta}'}
        h.update(headers or {})
        if corpo is not None and not isinstance(corpo, (bytes, str)):
            corpo = json.dumps(corpo)
            h.setdefault('Content-Type', 'application/json')
        con = http.client.HTTPConnection('127.0.0.1', self.porta, timeout=10)
        try:
            if sem_host:
                con.putrequest(metodo, caminho, skip_host=True, skip_accept_encoding=True)
                for k, v in h.items():
                    if k.lower() != 'host':
                        con.putheader(k, v)
                con.endheaders()
            else:
                con.request(metodo, caminho, body=corpo, headers=h)
            r = con.getresponse()
            dados = r.read()
        finally:
            con.close()
        # CA3: nenhuma resposta, de nenhum teste, leva CORS curinga
        self.assertNotIn('*', r.headers.get_all('Access-Control-Allow-Origin') or [],
                         f'{metodo} {caminho} respondeu com Access-Control-Allow-Origin: *')
        return r.status, r.headers, dados

    def json_de(self, dados):
        return json.loads(dados.decode())

    def itens(self):
        st, _, dados = self.pedir('GET', '/api/items')
        self.assertEqual(st, 200)
        return self.json_de(dados)

    def postar(self, itens, headers=None):
        return self.pedir('POST', '/api/items', {'items': itens}, headers or self.local())


class TestLimpezaDaBase(unittest.TestCase):
    """Q3: se o setUpClass de uma subclasse falha depois do super(), servidor e diretório não vazam."""

    def test_q3_setupclass_que_falha_depois_do_super_para_o_servidor_e_apaga_o_diretorio(self):
        visto = {}

        class Quebra(ServidorTeste):
            @classmethod
            def setUpClass(cls):
                super().setUpClass()
                visto.update(proc=cls.proc, dir=cls.dir)
                raise RuntimeError('falha de propósito no setUpClass')

            def test_nada(self):
                pass

        resultado = unittest.TestResult()
        unittest.TestSuite([Quebra('test_nada')]).run(resultado)
        self.assertEqual(len(resultado.errors), 1, resultado.errors)
        self.assertIn('falha de propósito', resultado.errors[0][1])
        self.assertIsNotNone(visto['proc'].poll(), 'o servidor de teste ficou no ar')
        self.assertFalse(os.path.exists(visto['dir']), 'o diretório temporário ficou no disco')


# ================================================================ etapa 1: CA10 e CA9
class TestLinhaDeBase(ServidorTeste):

    def test_ca10_primeira_linha_mostra_o_banco_temporario_e_a_porta(self):
        self.assertIn(f'(banco: {self.db})', self.primeira_linha)
        self.assertIn(f':{self.porta}/', self.primeira_linha)
        self.assertNotIn(DB_REAL, self.primeira_linha)
        self.assertTrue(os.path.exists(self.db), 'criar_banco() não criou o banco temporário')

    def test_ca10_sem_variaveis_o_padrao_e_o_de_hoje(self):
        env = {k: v for k, v in os.environ.items() if k not in ('ACHADINHOS_DB', 'ACHADINHOS_PORTA')}
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        # só importa e imprime as constantes: não cria banco nem sobe servidor
        saida = subprocess.run([sys.executable, '-c', 'import servidor as S; print(S.DB); print(S.PORT)'],
                               cwd=RAIZ, env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(saida.returncode, 0, saida.stderr)
        db, porta = saida.stdout.split()
        self.assertEqual(os.path.realpath(db), DB_REAL)
        self.assertEqual(porta, '8765')

    def test_ca9_get_items_responde_200_com_lista(self):
        self.assertIsInstance(self.itens(), list)

    def test_ca9_post_local_insere(self):
        st, _, dados = self.postar([{'loja': 'amazon', 'item_id': 'BASE00001', 'cat': 'Teste',
                                     'url': 'https://www.amazon.com.br/dp/BASE00001?tag=desejodemen01-20'}])
        self.assertEqual(st, 200, dados)
        self.assertEqual(self.json_de(dados)['inserido'], 1)
        self.assertIn('BASE00001', [i['item_id'] for i in self.itens()])

    def test_ca9_coletar_amazon_importa_e_grava_no_banco_temporario(self):
        db = os.path.join(self.dir, 'coleta.db')
        codigo = ('import servidor as S, coletar_amazon as C\n'
                  'S.criar_banco()\n'
                  'print(S.DB)\n'
                  "print(C.gravar([{'loja': 'amazon', 'item_id': 'COLETA001', 'cat': 'Teste',"
                  " 'url': C.link_afiliado('COLETA001'), 'data': {'titulo': 'x'}}]))\n")
        saida = subprocess.run([sys.executable, '-c', codigo], cwd=RAIZ, env=ambiente(db),
                               capture_output=True, text=True, timeout=30)
        self.assertEqual(saida.returncode, 0, saida.stderr)
        linhas = saida.stdout.splitlines()
        self.assertEqual(linhas[0], db)
        self.assertIn("'inserido': 1", linhas[1])
        con = sqlite3.connect(db)
        try:
            url = con.execute("SELECT url FROM items WHERE item_id='COLETA001'").fetchone()[0]
        finally:
            con.close()
        self.assertEqual(url, 'https://www.amazon.com.br/dp/COLETA001?tag=desejodemen01-20')

    def test_ca6_antigo_rotas_do_fonte_sem_proxy_de_imagem(self):
        # portado de testes/copiar-imagem.test.html (CA6 do plano copiar-imagem): o .test.html
        # não consegue mais ler o servidor.py pelo estático, então a checagem do fonte mora aqui.
        with open(os.path.join(RAIZ, 'servidor.py'), encoding='utf-8') as f:
            src = f.read()
        rotas = sorted(set(re.findall(r"""['"](/api/[^'"]*)['"]""", src)))
        self.assertEqual(rotas, ['/api/', '/api/config/', '/api/fetch', '/api/items', '/api/ml-sem-afiliado'])
        self.assertIsNone(re.search(r'/api/(imagem|img|foto|proxy|copiar)', src, re.I),
                          'rota de proxy de imagem não faz parte do plano')
        # as rotas /api/disparo/* moram no disparo.py, como sufixos do disparo.PREFIXO (R4 da revisão)
        with open(os.path.join(RAIZ, 'disparo.py'), encoding='utf-8') as f:
            src_disparo = f.read()
        self.assertIn("PREFIXO = '/api/disparo/'", src_disparo)
        self.assertIsNone(re.search(r'/api/(imagem|img|foto|proxy|copiar)', src_disparo, re.I),
                          'rota de proxy de imagem não faz parte do plano')
        sufixos = set(re.findall(r"resto == '([^']*)'", src_disparo))
        sufixos |= set(re.findall(r"re\.fullmatch\('([a-z]+)/' \+ _ID", src_disparo))
        self.assertEqual(sufixos, {'numeros', 'regras', 'previa', 'fila', 'envios', 'status'})
        self.assertFalse([x for x in sufixos if re.search(r'imagem|img|foto|proxy|copiar', x, re.I)])


# ================================================================ etapa 2: CA1 a CA4
ML_LISTA = 'https://lista.mercadolivre.com.br'
ML_WWW = 'https://www.mercadolivre.com.br'


def ml(origem):
    """Cabeçalhos que o Chrome manda no fetch da coleta, a partir de uma página do ML."""
    return {'Origin': origem, 'Sec-Fetch-Site': 'cross-site', 'Sec-Fetch-Mode': 'cors'}

ORIGENS_RUINS = ['https://evil.com', 'null', '', 'https://lista.mercadolivre.com.br.evil.com',
                 'http://lista.mercadolivre.com.br', 'https://mercadolivre.com.br',
                 'https://produto.mercadolivre.com.br', 'http://localhost:1', 'https://localhost:{p}',
                 'http://localhost:{p}.evil.com']


class TestHost(ServidorTeste):
    """CA1: Host fora de localhost:<porta> e 127.0.0.1:<porta> recebe 403 (DNS rebinding)."""

    HOSTS_RUINS = ['evil.com:{p}', 'evil.com', 'localhost', 'localhost:{p}.evil.com',
                   'localhost:{p1}', '127.0.0.1:{p1}', '0.0.0.0:{p}', '[::1]:{p}', 'localhost.:{p}']

    def ruins(self):
        return [h.format(p=self.porta, p1=self.porta + 1) for h in self.HOSTS_RUINS]

    def test_ca1_host_estranho_da_403_em_toda_rota_e_metodo(self):
        rotas = [('GET', '/'), ('GET', '/index.html'), ('GET', '/testes/copiar-imagem.test.html'),
                 ('HEAD', '/'), ('GET', '/api/items'), ('GET', '/api/ml-sem-afiliado'),
                 ('GET', '/api/config/templates'), ('GET', '/api/fetch?url=https://www.amazon.com.br/dp/X'),
                 ('OPTIONS', '/api/items'), ('POST', '/api/items'), ('PATCH', '/api/items/1'),
                 ('PUT', '/api/config/x'), ('DELETE', '/api/items/1'), ('GET', '/servidor.py')]
        for host in self.ruins():
            for metodo, caminho in rotas:
                with self.subTest(host=host, metodo=metodo, caminho=caminho):
                    corpo = {'items': []} if metodo in ('POST', 'PATCH', 'PUT') else None
                    st, _, _ = self.pedir(metodo, caminho, corpo, {'Host': host})
                    self.assertEqual(st, 403)

    def test_ca1_sem_host_da_403(self):
        st, _, _ = self.pedir('GET', '/api/items', sem_host=True)
        self.assertEqual(st, 403)

    def test_ca1_host_estranho_nao_grava(self):
        st, _, _ = self.postar([{'loja': 'ml', 'item_id': 'MLBHOST1', 'url': 'https://meli.la/h'}],
                               {'Host': f'evil.com:{self.porta}', 'Origin': f'http://evil.com:{self.porta}'})
        self.assertEqual(st, 403)
        self.assertNotIn('MLBHOST1', [i['item_id'] for i in self.itens()])

    def test_ca1_hosts_locais_passam_inclusive_em_maiusculas(self):
        for host in (f'localhost:{self.porta}', f'127.0.0.1:{self.porta}', f'LocalHost:{self.porta}'):
            with self.subTest(host=host):
                st, _, _ = self.pedir('GET', '/api/items', headers={'Host': host})
                self.assertEqual(st, 200)
                st, _, _ = self.pedir('GET', '/', headers={'Host': host})
                self.assertEqual(st, 200)


class TestEstatico(ServidorTeste):
    """CA2: o estático serve só /, /index.html e /testes/<nome>.test.html."""

    PROIBIDOS = ['/servidor.py', '/achadinhos.db', '/WhatsApp%20Chat%20-%20AmazonLinks/_chat.txt',
                 '/WhatsApp%20Chat%20-%20AmazonLinks/', '/servidor.log', '/.claude/', '/.claude/settings.json',
                 '/.git/', '/.git/config', '/testes/rodar.mjs', '/testes/', '/testes/test_servidor.py',
                 '/testes', '/CLAUDE.md', '/coletar_amazon.py', '/buscas.json', '/mensagens.html',
                 '/docs/', '/__pycache__/', '/favicon.ico', '/index.html/', '//servidor.py',
                 '/./servidor.py', '/%2e/servidor.py', '/testes/../servidor.py',
                 '/testes/%2e%2e/servidor.py', '/testes/..%2fservidor.py', '/testes/copiar-imagem.test.html/',
                 '/testes/Copiar-Imagem.test.html', '/testes/copiar-imagem.test.html%00',
                 '/testes/a/../copiar-imagem.test.html',
                 '/x/../index.html', '/%69ndex.html', '/index.htm', '///servidor.py']

    def test_ca2_fora_da_lista_da_404_em_get_e_head_sem_conteudo_do_arquivo(self):
        for metodo in ('GET', 'HEAD'):
            for caminho in self.PROIBIDOS:
                with self.subTest(metodo=metodo, caminho=caminho):
                    st, h, dados = self.pedir(metodo, caminho)
                    self.assertEqual(st, 404)
                    self.assertTrue(h.get('Content-Type', '').startswith('application/json'))
                    if metodo == 'HEAD':
                        self.assertEqual(dados, b'')
                    else:
                        self.assertEqual(self.json_de(dados), {'error': 'não encontrado'})

    def test_ca2_permitidos_respondem_200_em_get_e_head(self):
        for caminho in ('/', '/index.html', '/?x=1', '/index.html?v=2', '/testes/copiar-imagem.test.html'):
            with self.subTest(caminho=caminho):
                st, h, dados = self.pedir('GET', caminho)
                self.assertEqual(st, 200)
                self.assertTrue(h['Content-Type'].startswith('text/html'))
                self.assertGreater(len(dados), 500)
                st, h, dados = self.pedir('HEAD', caminho)
                self.assertEqual(st, 200)
                self.assertEqual(dados, b'')
                self.assertEqual(h['Cache-Control'], 'no-store')

    def test_ca2_test_html_inexistente_da_404(self):
        st, _, _ = self.pedir('GET', '/testes/nao-existe.test.html')
        self.assertEqual(st, 404)

    def test_s6_estatico_nao_pode_ser_embutido_por_outro_site(self):
        for metodo, caminho in (('GET', '/'), ('GET', '/index.html'), ('HEAD', '/'),
                                ('GET', '/testes/copiar-imagem.test.html'), ('GET', '/servidor.py')):
            with self.subTest(metodo=metodo, caminho=caminho):
                _, h, _ = self.pedir(metodo, caminho)
                self.assertEqual(h['X-Frame-Options'], 'SAMEORIGIN')
                self.assertEqual(h['Content-Security-Policy'], "frame-ancestors 'self'")

    def test_ca2_head_na_api_da_405(self):
        st, _, dados = self.pedir('HEAD', '/api/items')
        self.assertEqual(st, 405)
        self.assertEqual(dados, b'')


class TestOrigem(ServidorTeste):
    """CA3 e CA4: CORS só para a allowlist do ML, e só nas rotas e métodos da coleta."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        con = http.client.HTTPConnection('127.0.0.1', cls.porta, timeout=10)
        con.request('POST', '/api/items', json.dumps({'items': [
            {'loja': 'ml', 'item_id': 'MLBORIG1', 'cat': 'Teste', 'url': 'https://www.mercadolivre.com.br/p/MLBORIG1'},
            {'loja': 'amazon', 'item_id': 'ORIGEM001', 'cat': 'Teste',
             'url': 'https://www.amazon.com.br/dp/ORIGEM001?tag=desejodemen01-20'}]}),
            {'Host': f'localhost:{cls.porta}', 'Origin': f'http://localhost:{cls.porta}',
             'Content-Type': 'application/json'})
        assert con.getresponse().status == 200
        con.close()

    def id_de(self, item_id):
        return next(i['id'] for i in self.itens() if i['item_id'] == item_id)

    def origens_ruins(self):
        return [o.format(p=self.porta) for o in ORIGENS_RUINS]

    # ---- CA4: origem fora da allowlist
    def test_ca4_origem_ruim_da_403_e_nao_grava(self):
        alvo = self.id_de('ORIGEM001')
        for origem in self.origens_ruins():
            with self.subTest(origem=origem):
                h = {'Origin': origem}
                st, hd, _ = self.postar([{'loja': 'ml', 'item_id': 'MLBRUIM', 'url': 'https://meli.la/r'}], h)
                self.assertEqual(st, 403)
                self.assertIsNone(hd.get('Access-Control-Allow-Origin'))
                self.assertEqual(self.pedir('GET', '/api/items', headers=h)[0], 403)
                self.assertEqual(self.pedir('PATCH', f'/api/items/{alvo}', {'cat': 'Invadida'}, h)[0], 403)
                self.assertEqual(self.pedir('DELETE', f'/api/items/{alvo}', headers=h)[0], 403)
                self.assertEqual(self.pedir('PUT', '/api/config/templates', ['x'], h)[0], 403)
                st, hd, _ = self.pedir('OPTIONS', '/api/items', headers={
                    **h, 'Access-Control-Request-Method': 'POST', 'Access-Control-Request-Private-Network': 'true'})
                self.assertEqual(st, 403)
                self.assertIsNone(hd.get('Access-Control-Allow-Origin'))
                self.assertIsNone(hd.get('Access-Control-Allow-Private-Network'))
        itens = self.itens()
        self.assertNotIn('MLBRUIM', [i['item_id'] for i in itens])
        alvo_depois = next(i for i in itens if i['id'] == alvo)
        self.assertEqual(alvo_depois['cat'], 'Teste')
        st, _, dados = self.pedir('GET', '/api/config/templates')
        self.assertEqual(self.json_de(dados), None)

    def test_ca4_sem_origin_e_sec_fetch_site_cruzado_da_403(self):
        for site in ('cross-site', 'same-site', 'Cross-Site'):
            for caminho in ('/api/items', '/api/fetch?url=https://www.amazon.com.br/dp/X',
                            '/api/ml-sem-afiliado', '/api/config/templates'):
                with self.subTest(site=site, caminho=caminho):
                    st, _, _ = self.pedir('GET', caminho, headers={'Sec-Fetch-Site': site})
                    self.assertEqual(st, 403)

    def test_ca4_sem_origin_e_sec_fetch_site_local_ou_ausente_passa(self):
        for h in ({}, {'Sec-Fetch-Site': 'same-origin'}, {'Sec-Fetch-Site': 'none'}):
            with self.subTest(h=h):
                self.assertEqual(self.pedir('GET', '/api/items', headers=h)[0], 200)

    def test_ca4_ml_nao_usa_delete_put_fetch_nem_config(self):
        alvo = self.id_de('ORIGEM001')
        for origem in (ML_LISTA, ML_WWW):
            h = ml(origem)
            casos = [('DELETE', f'/api/items/{alvo}', None), ('PUT', '/api/config/templates', ['x']),
                     ('GET', '/api/fetch?url=https://www.amazon.com.br/dp/X', None),
                     ('GET', '/api/config/templates', None), ('GET', '/api/items/', None),
                     ('GET', '/api/ml-sem-afiliado/', None), ('GET', '/api/itemsX', None)]
            for metodo, caminho, corpo in casos:
                with self.subTest(origem=origem, metodo=metodo, caminho=caminho):
                    st, hd, _ = self.pedir(metodo, caminho, corpo, h)
                    self.assertEqual(st, 403)
                    self.assertIsNone(hd.get('Access-Control-Allow-Origin'))
            for metodo in ('DELETE', 'PUT', 'HEAD', ''):
                with self.subTest(origem=origem, preflight=metodo):
                    st, hd, _ = self.pedir('OPTIONS', f'/api/items/{alvo}',
                                           headers={**h, 'Access-Control-Request-Method': metodo})
                    self.assertEqual(st, 403)
                    self.assertIsNone(hd.get('Access-Control-Allow-Origin'))
        self.assertIn(alvo, [i['id'] for i in self.itens()])

    def test_ca4_ml_em_rota_da_coleta_com_metodo_sem_handler_da_404_sem_efeito(self):
        # a guarda libera o par (método da coleta, rota da coleta); a combinação que não existe cai no 404
        antes = self.itens()
        for metodo, caminho, corpo in (('POST', '/api/items/1', {'items': [{'url': 'https://meli.la/x'}]}),
                                       ('PATCH', '/api/items', {'cat': 'x'}),
                                       ('POST', '/api/ml-sem-afiliado', {'items': []})):
            with self.subTest(metodo=metodo, caminho=caminho):
                st, _, _ = self.pedir(metodo, caminho, corpo, ml(ML_LISTA))
                self.assertEqual(st, 404)
        self.assertEqual(self.itens(), antes)

    # ---- CA3 e CA9: fluxo da coleta do ML
    def test_ca3_preflight_do_ml_sem_pna(self):
        st, h, _ = self.pedir('OPTIONS', '/api/items', headers={
            **ml(ML_LISTA), 'Access-Control-Request-Method': 'POST',
            'Access-Control-Request-Headers': 'content-type'})
        self.assertEqual(st, 204)
        self.assertEqual(h.get_all('Access-Control-Allow-Origin'), [ML_LISTA])
        self.assertIn('Origin', h.get('Vary', ''))
        self.assertEqual(h['Access-Control-Allow-Methods'], 'GET, POST, PATCH')
        self.assertEqual(h['Access-Control-Allow-Headers'], 'Content-Type')
        self.assertIsNone(h.get('Access-Control-Allow-Private-Network'))

    def test_ca3_preflight_do_ml_com_pna(self):
        alvo = self.id_de('MLBORIG1')
        st, h, _ = self.pedir('OPTIONS', f'/api/items/{alvo}', headers={
            **ml(ML_WWW), 'Access-Control-Request-Method': 'PATCH',
            'Access-Control-Request-Headers': 'content-type', 'Access-Control-Request-Private-Network': 'true'})
        self.assertEqual(st, 204)
        self.assertEqual(h.get_all('Access-Control-Allow-Origin'), [ML_WWW])
        self.assertEqual(h['Access-Control-Allow-Private-Network'], 'true')

    def test_ca9_ml_lista_faz_post_com_cors(self):
        st, h, dados = self.postar([{'loja': 'ml', 'item_id': 'MLBORIG2', 'cat': 'Teste',
                                     'url': 'https://www.mercadolivre.com.br/p/MLBORIG2'}], ml(ML_LISTA))
        self.assertEqual(st, 200, dados)
        self.assertEqual(h.get_all('Access-Control-Allow-Origin'), [ML_LISTA])
        self.assertIn('Origin', h.get('Vary', ''))
        self.assertIsNone(h.get('Access-Control-Allow-Private-Network'))
        self.assertIn('MLBORIG2', [i['item_id'] for i in self.itens()])

    def test_ca9_ml_www_le_pendentes_e_faz_patch(self):
        st, h, dados = self.pedir('GET', '/api/ml-sem-afiliado', headers=ml(ML_WWW))
        self.assertEqual(st, 200)
        self.assertEqual(h['Access-Control-Allow-Origin'], ML_WWW)
        pend = self.json_de(dados)
        alvo = self.id_de('MLBORIG1')
        self.assertIn(alvo, [p['id'] for p in pend])
        st, h, dados = self.pedir('PATCH', f'/api/items/{alvo}', {'url': 'https://meli.la/orig1'}, ml(ML_WWW))
        self.assertEqual(st, 200, dados)
        self.assertEqual(h['Access-Control-Allow-Origin'], ML_WWW)
        self.assertEqual(self.json_de(dados)['url'], 'https://meli.la/orig1')
        st, _, dados = self.pedir('GET', '/api/ml-sem-afiliado', headers=ml(ML_LISTA))
        self.assertEqual(st, 200)
        self.assertNotIn(alvo, [p['id'] for p in self.json_de(dados)])
        st, h, _ = self.pedir('GET', '/api/items', headers=ml(ML_LISTA))
        self.assertEqual(st, 200)
        self.assertEqual(h['Access-Control-Allow-Origin'], ML_LISTA)

    def test_ca3_origem_local_nao_recebe_cors_e_le_e_grava(self):
        for host in ('localhost', '127.0.0.1'):
            with self.subTest(host=host):
                h = self.local(host)
                st, hd, _ = self.pedir('GET', '/api/items', headers=h)
                self.assertEqual(st, 200)
                self.assertIsNone(hd.get('Access-Control-Allow-Origin'))
                st, hd, _ = self.postar([{'loja': 'amazon', 'item_id': f'LOCAL{host[:3]}', 'cat': 'Teste',
                                          'url': 'https://www.amazon.com.br/dp/X?tag=desejodemen01-20'}], h)
                self.assertEqual(st, 200)
                self.assertIsNone(hd.get('Access-Control-Allow-Origin'))
                st, _, _ = self.pedir('PUT', '/api/config/currentTpl', '"padrao"',
                                      {**h, 'Content-Type': 'application/json'})
                self.assertEqual(st, 200)

    def test_ca3_estatico_nunca_leva_cors(self):
        for origem in (ML_LISTA, 'https://evil.com', None):
            for caminho in ('/', '/index.html', '/servidor.py'):
                with self.subTest(origem=origem, caminho=caminho):
                    _, h, _ = self.pedir('GET', caminho, headers=ml(origem) if origem else {})
                    self.assertIsNone(h.get('Access-Control-Allow-Origin'))
                    self.assertIsNone(h.get('Access-Control-Allow-Methods'))
                    self.assertIsNone(h.get('Access-Control-Allow-Private-Network'))

    def test_ca3_resposta_de_erro_da_api_nao_leva_cors_curinga(self):
        for h in ({}, ml(ML_LISTA), self.local()):
            with self.subTest(h=h):
                st, hd, _ = self.pedir('GET', '/api/nao-existe', headers=h)
                self.assertIn(st, (403, 404))
                self.assertNotEqual(hd.get('Access-Control-Allow-Origin'), '*')


# ================================================================ etapa 4: CA5, CA6 e CA7
class TestEscrita(ServidorTeste):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        con = http.client.HTTPConnection('127.0.0.1', cls.porta, timeout=10)
        con.request('POST', '/api/items', json.dumps({'items': [
            {'loja': 'ml', 'item_id': 'MLBESC1', 'cat': 'Teste', 'url': 'https://www.mercadolivre.com.br/p/MLBESC1'},
            {'loja': 'ml', 'item_id': 'MLBESC2', 'cat': 'Teste', 'url': 'https://meli.la/esc2'}]}),
            {'Host': f'localhost:{cls.porta}', 'Origin': f'http://localhost:{cls.porta}',
             'Content-Type': 'application/json'})
        assert con.getresponse().status == 200
        con.close()

    def item(self, item_id):
        return next((i for i in self.itens() if i['item_id'] == item_id), None)

    def config(self, chave):
        return self.json_de(self.pedir('GET', f'/api/config/{chave}')[2])

    # ---- CA5
    def test_ca5_sem_content_type_json_da_415_e_nao_grava(self):
        alvo = self.item('MLBESC1')['id']
        corpo_item = json.dumps({'items': [{'loja': 'ml', 'item_id': 'MLB415', 'url': 'https://meli.la/415'}]})
        for tipo in ('text/plain', 'text/plain;charset=UTF-8', 'application/x-www-form-urlencoded',
                     'multipart/form-data; boundary=x', 'application/jsonx', None):
            with self.subTest(tipo=tipo):
                h = dict(self.local())
                if tipo:
                    h['Content-Type'] = tipo
                st, _, dados = self.pedir('POST', '/api/items', corpo_item, h)
                self.assertEqual(st, 415)
                self.assertIn('error', self.json_de(dados))
                st, _, _ = self.pedir('PATCH', f'/api/items/{alvo}', json.dumps({'cat': 'Mudou415'}), h)
                self.assertEqual(st, 415)
                st, _, _ = self.pedir('PUT', '/api/config/chave415', json.dumps({'x': 1}), h)
                self.assertEqual(st, 415)
        self.assertIsNone(self.item('MLB415'))
        self.assertEqual(self.item('MLBESC1')['cat'], 'Teste')
        self.assertIsNone(self.config('chave415'))

    def test_ca5_content_type_json_com_charset_passa(self):
        h = {**self.local(), 'Content-Type': 'application/json; charset=utf-8'}
        st, _, _ = self.pedir('PUT', '/api/config/chaveCharset', json.dumps('ok'), h)
        self.assertEqual(st, 200)
        self.assertEqual(self.config('chaveCharset'), 'ok')

    def test_ca5_json_invalido_da_400_e_nao_grava(self):
        alvo = self.item('MLBESC1')['id']
        h = {**self.local(), 'Content-Type': 'application/json'}
        for quebrado in ('{"items": [', '{items: []}', "{'cat': 'x'}", '\xff\xfe', 'NaN]'):
            with self.subTest(corpo=quebrado):
                st, _, dados = self.pedir('POST', '/api/items', quebrado.encode('latin-1'), h)
                self.assertEqual(st, 400)
                self.assertIn('error', self.json_de(dados))
                self.assertEqual(self.pedir('PATCH', f'/api/items/{alvo}', quebrado.encode('latin-1'), h)[0], 400)
                self.assertEqual(self.pedir('PUT', '/api/config/chave400', quebrado.encode('latin-1'), h)[0], 400)
        self.assertEqual(self.item('MLBESC1')['cat'], 'Teste')
        self.assertIsNone(self.config('chave400'))

    def test_ca5_json_com_formato_errado_da_400(self):
        alvo = self.item('MLBESC1')['id']
        for corpo in ('"x"', '5', 'null', '{"items": "x"}', '{"items": [1]}', '[["a"]]'):
            with self.subTest(post=corpo):
                st, _, _ = self.pedir('POST', '/api/items', corpo, {**self.local(), 'Content-Type': 'application/json'})
                self.assertEqual(st, 400)
        for corpo in ('[]', '"x"', '{"data": "x"}', '{"cat": {"a": 1}}', '{"url": 5}'):
            with self.subTest(patch=corpo):
                st, _, _ = self.pedir('PATCH', f'/api/items/{alvo}', corpo,
                                      {**self.local(), 'Content-Type': 'application/json'})
                self.assertEqual(st, 400)
        self.assertEqual(self.item('MLBESC1')['cat'], 'Teste')

    def test_s8_content_length_acima_de_5mb_da_413_sem_ler_o_corpo(self):
        alvo = self.item('MLBESC1')['id']
        h = {**self.local(), 'Content-Type': 'application/json', 'Content-Length': str(5 * 1024 * 1024 + 1)}
        for metodo, caminho in (('POST', '/api/items'), ('PATCH', f'/api/items/{alvo}'), ('PUT', '/api/config/grande')):
            with self.subTest(metodo=metodo):
                inicio = time.monotonic()
                st, _, dados = self.pedir(metodo, caminho, None, h)   # nenhum byte de corpo é enviado
                self.assertEqual(st, 413)
                self.assertIn('error', self.json_de(dados))
                self.assertLess(time.monotonic() - inicio, 5, 'o servidor esperou o corpo antes de recusar')

    def test_s8_corpo_que_acaba_antes_do_content_length_da_400(self):
        cabeca = (f'POST /api/items HTTP/1.1\r\nHost: localhost:{self.porta}\r\nOrigin: http://localhost:{self.porta}\r\n'
                  'Content-Type: application/json\r\nContent-Length: 100\r\n\r\n')
        with socket.create_connection(('127.0.0.1', self.porta), timeout=10) as s:
            s.sendall(cabeca.encode() + b'{"items": [')
            s.shutdown(socket.SHUT_WR)
            dados = b''
            while pedaco := s.recv(65536):
                dados += pedaco
        self.assertTrue(dados.startswith(b'HTTP/1.0 400'), dados[:80])
        self.assertIn(b'"error"', dados)

    def test_ca5_content_length_invalido_da_400(self):
        st, _, _ = self.pedir('POST', '/api/items', None, {**self.local(), 'Content-Type': 'application/json',
                                                            'Content-Length': 'abc'})
        self.assertEqual(st, 400)

    def test_ca5_post_em_lista_crua_continua_aceito(self):
        st, _, dados = self.pedir('POST', '/api/items', [{'loja': 'ml', 'item_id': 'MLBCRUA', 'url': 'https://meli.la/crua'}],
                                  self.local())
        self.assertEqual(st, 200, dados)
        self.assertIsNotNone(self.item('MLBCRUA'))

    # ---- CA6
    def test_ca6_loja_invalida_no_lote_da_400_e_nao_grava_nada(self):
        for loja in ('x', 'AMAZON', 'Ml', 5, ['ml']):
            with self.subTest(loja=loja):
                lote = [{'loja': 'ml', 'item_id': 'MLBLOTE1', 'url': 'https://meli.la/l1'},
                        {'loja': 'amazon', 'item_id': 'LOTE00002', 'url': 'https://www.amazon.com.br/dp/LOTE00002?tag=desejodemen01-20'},
                        {'loja': loja, 'item_id': 'LOTE00003', 'url': 'https://www.amazon.com.br/dp/LOTE00003'}]
                st, _, dados = self.postar(lote)
                self.assertEqual(st, 400)
                self.assertIn('2', self.json_de(dados)['error'])
        ids = [i['item_id'] for i in self.itens()]
        for item_id in ('MLBLOTE1', 'LOTE00002', 'LOTE00003'):
            self.assertNotIn(item_id, ids)

    def test_ca6_sem_loja_continua_amazon(self):
        for it in ({'item_id': 'SEMLOJA01', 'url': 'https://www.amazon.com.br/dp/SEMLOJA01?tag=desejodemen01-20'},
                   {'loja': '', 'item_id': 'SEMLOJA02', 'url': 'https://www.amazon.com.br/dp/SEMLOJA02?tag=desejodemen01-20'},
                   {'loja': None, 'item_id': 'SEMLOJA03', 'url': 'https://www.amazon.com.br/dp/SEMLOJA03?tag=desejodemen01-20'}):
            with self.subTest(it=it):
                st, _, dados = self.postar([it])
                self.assertEqual(st, 200, dados)
                self.assertEqual(self.item(it['item_id'])['loja'], 'amazon')

    def test_ca6_upsert_direto_recusa_loja_invalida(self):
        # o coletar_amazon.py grava por S.upsert(), sem HTTP: a regra vale lá também
        db = os.path.join(self.dir, 'upsert.db')
        codigo = ('import servidor as S\n'
                  'S.criar_banco(); con = S.conectar()\n'
                  'try:\n'
                  "    S.upsert(con, {'loja': 'x', 'item_id': 'U1', 'url': 'https://meli.la/u'}); print('gravou')\n"
                  'except ValueError:\n'
                  "    print('recusou')\n"
                  "print(S.upsert(con, {'item_id': 'U2', 'url': 'https://www.amazon.com.br/dp/U2?tag=desejodemen01-20'}))\n"
                  "con.commit(); print(con.execute('SELECT COUNT(*) FROM items').fetchone()[0])\n")
        saida = subprocess.run([sys.executable, '-c', codigo], cwd=RAIZ, env=ambiente(db),
                               capture_output=True, text=True, timeout=30)
        self.assertEqual(saida.returncode, 0, saida.stderr)
        self.assertEqual(saida.stdout.split(), ['recusou', 'inserido', '1'])

    def test_ca6_upsert_continua_sem_trocar_link_de_afiliado(self):
        st, _, dados = self.postar([{'loja': 'ml', 'item_id': 'MLBESC2', 'url': 'https://www.mercadolivre.com.br/p/MLBESC2',
                                     'data': {'titulo': 'Produto', 'preco': 'R$ 10'}}])
        self.assertEqual(st, 200, dados)
        self.assertEqual(self.json_de(dados)['atualizado'], 1)
        it = self.item('MLBESC2')
        self.assertEqual(it['url'], 'https://meli.la/esc2')
        self.assertEqual(it['data']['preco'], 'R$ 10')

    # ---- CA7
    def test_ca7_patch_url_sem_afiliado_da_400_e_nao_grava(self):
        alvo = self.item('MLBESC1')
        ruins = ['https://www.mercadolivre.com.br/x', 'http://meli.la/abc', 'https://meli.la/', 'https://meli.la',
                 'https://meli.la@evil.com/abc', 'https://meli.la.evil.com/abc', 'https://evil.com/?u=https://meli.la/x',
                 ' https://meli.la/abc', 'https://meli.la/abc\n', 'https://meli.la:8443/abc', 'javascript:alert(1)',
                 'https://www.amazon.com.br/dp/X', 'https://www.amazon.com.br/dp/X?tag=outra-20',
                 'https://www.amazon.com.br/dp/X?x=tag=desejodemen01-20', 'http://www.amazon.com.br/dp/X?tag=desejodemen01-20',
                 'https://www.amazon.com.br.evil.com/dp/X?tag=desejodemen01-20', 'https://evil.com/?tag=desejodemen01-20',
                 'https://www.amazon.com.br/dp/X?tag=desejodemen01-20&tag=outro-20',
                 'https://www.amazon.com.br/dp/X?tag=outro-20&tag=desejodemen01-20']
        for url in ruins:
            for origem in (self.local(), ml(ML_WWW)):
                with self.subTest(url=url, origem=origem.get('Origin')):
                    st, _, dados = self.pedir('PATCH', f'/api/items/{alvo["id"]}', {'url': url, 'cat': 'Mudou'}, origem)
                    self.assertEqual(st, 400)
                    self.assertIn('error', self.json_de(dados))
        depois = self.item('MLBESC1')
        self.assertEqual(depois['url'], alvo['url'])
        self.assertEqual(depois['cat'], 'Teste')

    def test_ca7_patch_url_de_afiliado_da_200(self):
        alvo = self.item('MLBESC1')['id']
        for url in ('https://meli.la/abc', 'https://www.amazon.com.br/dp/B0X?tag=desejodemen01-20',
                    'https://www.amazon.com.br/dp/B0X?th=1&tag=desejodemen01-20', 'https://meli.la/2Xyz9'):
            with self.subTest(url=url):
                st, _, dados = self.pedir('PATCH', f'/api/items/{alvo}', {'url': url}, ml(ML_WWW))
                self.assertEqual(st, 200, dados)
                self.assertEqual(self.json_de(dados)['url'], url)

    def test_ca9_patch_de_cat_e_data_e_delete_locais_continuam(self):
        st, _, _ = self.postar([{'loja': 'amazon', 'item_id': 'PATCH0001', 'cat': 'A',
                                 'url': 'https://www.amazon.com.br/dp/PATCH0001?tag=desejodemen01-20'}])
        self.assertEqual(st, 200)
        alvo = self.item('PATCH0001')['id']
        st, _, dados = self.pedir('PATCH', f'/api/items/{alvo}', {'cat': 'B', 'data': {'titulo': 'T'}}, self.local())
        self.assertEqual(st, 200, dados)
        self.assertEqual(self.json_de(dados)['cat'], 'B')
        self.assertEqual(self.json_de(dados)['data']['titulo'], 'T')
        # o front manda Content-Type: application/json até no DELETE (index.html:212), sem corpo
        st, _, _ = self.pedir('DELETE', f'/api/items/{alvo}', headers={**self.local(), 'Content-Type': 'application/json'})
        self.assertEqual(st, 200)
        self.assertIsNone(self.item('PATCH0001'))


# ================================================================ S1 (revisão do coletar_ml.js): url do lote
class TestUrlDoLote(ServidorTeste):
    """POST /api/items só grava url https das lojas: o front abre essa url em "Abrir na loja"."""

    RUINS = ['javascript:alert(1)', 'JavaScript:alert(1)', 'data:text/html,<script>alert(1)</script>',
             'vbscript:msgbox(1)', 'http://www.amazon.com.br/dp/X', 'http://meli.la/x',
             'https://evil.com/x', 'https://www.amazon.com/dp/X', 'https://meli.la.evil.com/x',
             'https://mercadolivre.com.br.evil.com/x', 'https://evilmercadolivre.com.br/x',
             'https://evil.com\\.mercadolivre.com.br/', 'https://www.amazon.com.br./dp/X',
             'https://meli.la@evil.com/x', 'https://user@www.amazon.com.br/dp/X', 'https://a:b@amzn.to/x',
             'https://www.amazon.com.br:443/dp/X', 'https://meli.la:8443/x', 'https://meli.la:/x',
             'https://127.0.0.1/x', 'https://[::1]/x', 'https://localhost/x',
             ' https://meli.la/x', 'https://meli.la/x y', 'https://meli.la/x\n', 'https://meli.la/\tx',
             '//meli.la/x', 'meli.la/x', 'https:meli.la/x', 'https:///x']

    BONS = ['https://produto.mercadolivre.com.br/MLB-4100000001-tv-_JM',   # coletar_ml.js
            'https://www.mercadolivre.com.br/p/MLB1', 'https://lista.mercadolivre.com.br/tv',
            'https://meli.la/abc',                                          # saveLinks do front
            'https://www.amazon.com.br/dp/B0ABCDEFGH?tag=desejodemen01-20',   # coletar_amazon.py
            'https://amazon.com.br/dp/B0X', 'https://amzn.to/abc']

    def test_s1_url_que_nao_e_https_de_loja_da_400_e_nao_grava_o_lote(self):
        for url in self.RUINS:
            for nome, h in (('local', self.local()), ('ml', ml(ML_LISTA))):
                with self.subTest(url=url, origem=nome):
                    lote = [{'loja': 'ml', 'item_id': 'MLBURLBOA', 'url': 'https://meli.la/boa'},
                            {'loja': 'ml', 'item_id': 'MLBURLRUIM', 'url': url}]
                    st, _, dados = self.postar(lote, h)
                    self.assertEqual(st, 400)
                    self.assertIn('item 1', self.json_de(dados)['error'])
        ids = [i['item_id'] for i in self.itens()]
        self.assertNotIn('MLBURLBOA', ids)
        self.assertNotIn('MLBURLRUIM', ids)

    def test_s1_url_ruim_tambem_nao_troca_a_url_de_item_existente(self):
        st, _, _ = self.postar([{'loja': 'ml', 'item_id': 'MLBEXISTE', 'url': 'https://produto.mercadolivre.com.br/MLB-1'}])
        self.assertEqual(st, 200)
        st, _, _ = self.postar([{'loja': 'ml', 'item_id': 'MLBEXISTE', 'url': 'javascript:alert(1)',
                                 'data': {'titulo': 'T'}}], ml(ML_LISTA))
        self.assertEqual(st, 400)
        it = next(i for i in self.itens() if i['item_id'] == 'MLBEXISTE')
        self.assertEqual(it['url'], 'https://produto.mercadolivre.com.br/MLB-1')

    def test_s1_urls_das_duas_lojas_continuam_aceitas(self):
        for n, url in enumerate(self.BONS):
            for nome, h in (('local', self.local()), ('ml', ml(ML_LISTA))):
                with self.subTest(url=url, origem=nome):
                    item_id = f'BOA{n}{nome}'
                    st, _, dados = self.postar([{'loja': 'ml' if 'amazon' not in url and 'amzn' not in url else 'amazon',
                                                 'item_id': item_id, 'url': url}], h)
                    self.assertEqual(st, 200, dados)
                    self.assertEqual(next(i for i in self.itens() if i['item_id'] == item_id)['url'], url)

    def test_s1_item_sem_url_continua_ignorado_sem_erro(self):
        st, _, dados = self.postar([{'loja': 'ml', 'item_id': 'MLBSEMURL'}, {'loja': 'ml', 'item_id': 'MLBURLVAZIA', 'url': ''}])
        self.assertEqual(st, 200, dados)
        self.assertEqual(self.json_de(dados)['inserido'], 0)


# ================================================================ etapa 5: CA8
MSG_FETCH_RECUSADO = 'só links https da Amazon (amazon.com.br ou amzn.to)'


class TestFetchHttp(ServidorTeste):
    """CA8 pela API: só recusas, nenhuma acessa a rede (a mensagem é a da validação)."""

    def test_ca8_url_fora_da_allowlist_da_400_sem_rede(self):
        p = self.porta
        ruins = ['file:///etc/passwd', 'http://www.amazon.com.br/dp/X', f'https://127.0.0.1:{p}/',
                 'https://evil.com', '', 'ftp://amazon.com.br/x', f'https://localhost:{p}/api/items',
                 'https://www.amazon.com.br.evil.com/dp/X', 'https://evilamazon.com.br/dp/X',
                 'https://amzn.to@evil.com/x', 'https://user:senha@www.amazon.com.br/dp/X',
                 'https://www.amazon.com.br:8443/dp/X', 'https://www.amazon.com/dp/X', 'https:///dp/X',
                 'javascript:alert(1)', 'https://[::1]/x', 'https://www.amazon.com.br:abc/']
        for url in ruins:
            with self.subTest(url=url):
                st, _, dados = self.pedir('GET', '/api/fetch?url=' + urllib.parse.quote(url, safe=''))
                self.assertEqual(st, 400)
                self.assertEqual(self.json_de(dados), {'error': MSG_FETCH_RECUSADO})
        st, _, dados = self.pedir('GET', '/api/fetch')
        self.assertEqual((st, self.json_de(dados)), (400, {'error': MSG_FETCH_RECUSADO}))

    def conferir_proxy_morto(self):
        codigo = ('import urllib.request, servidor as S\n'
                  'p = [h.proxies for h in S.OPENER_AMAZON.handlers if isinstance(h, urllib.request.ProxyHandler)]\n'
                  "print(p[0].get('http'), p[0].get('https'))\n")
        saida = subprocess.run([sys.executable, '-c', codigo], cwd=RAIZ, env=ambiente(self.db),
                               capture_output=True, text=True, timeout=30)
        self.assertEqual(saida.returncode, 0, saida.stderr)
        self.assertEqual(saida.stdout.split(), [PROXY_MORTO, PROXY_MORTO])

    def test_r2_servidor_de_teste_sai_para_a_rede_so_pelo_proxy_morto(self):
        self.conferir_proxy_morto()

    def test_s9_falha_ao_abrir_a_amazon_da_502_com_mensagem_generica(self):
        self.conferir_proxy_morto()   # garante que a URL aceita bate no proxy morto, nunca na Amazon
        st, _, dados = self.pedir('GET', '/api/fetch?url=' + urllib.parse.quote('https://www.amazon.com.br/dp/B0TESTE000', safe=''))
        self.assertEqual(st, 502)
        self.assertEqual(self.json_de(dados), {'error': 'Não consegui abrir a página da Amazon.'})


class ServidorEmProcesso(unittest.TestCase):
    """Base: importa o servidor.py neste processo, com banco temporário, porta livre e proxy morto.

    O módulo fica em cache depois do primeiro import: DB, PORT e OPENER_AMAZON vêm dele.
    """

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix='achadinhos-teste-')
        cls.addClassCleanup(shutil.rmtree, cls.dir, ignore_errors=True)
        # nada aqui abre o banco; mesmo assim, nunca o real
        env = mock.patch.dict(os.environ, {'ACHADINHOS_DB': os.path.join(cls.dir, 'nao-usado.db'),
                                           'ACHADINHOS_PORTA': str(porta_livre()), **PROXIES_MORTOS})
        env.start()
        cls.addClassCleanup(env.stop)
        sys.path.insert(0, RAIZ)
        cls.addClassCleanup(sys.path.remove, RAIZ)
        import servidor
        cls.S = servidor


class TestHandlerUnidade(ServidorEmProcesso):
    """S8: Content-Length maior que o corpo não prende a thread do servidor."""

    def test_s8_handler_tem_timeout_de_leitura(self):
        self.assertEqual(self.S.Handler.timeout, 15)

    def test_s8_corpo_que_nao_chega_vira_408_depois_do_timeout(self):
        class Rapido(self.S.Handler):
            timeout = 0.5   # o real é 15 s; aqui só encurta a espera

            def log_message(self, *a):
                pass
        srv = ThreadingHTTPServer(('127.0.0.1', self.S.PORT), Rapido)
        self.addCleanup(srv.server_close)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        cabeca = (f'POST /api/items HTTP/1.1\r\nHost: localhost:{self.S.PORT}\r\n'
                  'Content-Type: application/json\r\nContent-Length: 100\r\n\r\n')
        with socket.create_connection(('127.0.0.1', self.S.PORT), timeout=10) as s:
            inicio = time.monotonic()
            s.sendall(cabeca.encode() + b'{"items": [')   # e a conexão fica aberta, sem o resto
            dados = s.recv(65536)
            demora = time.monotonic() - inicio
        self.assertTrue(dados.startswith(b'HTTP/1.0 408'), dados[:80])
        self.assertLess(demora, 5)


class TestFetchUnidade(ServidorEmProcesso):
    """CA8 no código: URL pedida e cada redirect conferidos antes da rede."""

    def pedido(self, url='https://www.amazon.com.br/dp/X'):
        return urllib.request.Request(url, headers={'User-Agent': 'teste'})

    def test_ca8_redirect_para_fora_da_lista_e_recusado(self):
        h = self.S.RedirecionamentoAmazon()
        for destino in ('https://evil.com/x', 'http://www.amazon.com.br/dp/X', 'https://127.0.0.1:8765/api/items',
                        'file:///etc/passwd', 'https://www.amazon.com.br.evil.com/', 'https://amzn.to@evil.com/'):
            with self.subTest(destino=destino):
                with self.assertRaises(self.S.URLRecusada):
                    h.redirect_request(self.pedido(), None, 302, 'Found', {}, destino)

    def test_ca8_redirect_dentro_da_lista_e_seguido(self):
        h = self.S.RedirecionamentoAmazon()
        for destino in ('https://www.amazon.com.br/dp/B0X?tag=desejodemen01-20', 'https://amazon.com.br/dp/B0X'):
            with self.subTest(destino=destino):
                novo = h.redirect_request(self.pedido('https://amzn.to/abc'), None, 301, 'Moved', {}, destino)
                self.assertEqual(novo.full_url, destino)

    def test_ca8_opener_usa_so_o_redirect_conferido(self):
        redirs = [h for h in self.S.OPENER_AMAZON.handlers if isinstance(h, urllib.request.HTTPRedirectHandler)]
        self.assertEqual([type(h) for h in redirs], [self.S.RedirecionamentoAmazon])

    def test_ca8_buscar_produto_recusa_antes_de_abrir_conexao(self):
        with mock.patch.object(self.S.OPENER_AMAZON, 'open', side_effect=AssertionError('acessou a rede')) as aberto:
            for url in ('https://evil.com/', 'http://amzn.to/x', 'file:///etc/passwd', None):
                with self.subTest(url=url):
                    with self.assertRaises(self.S.URLRecusada):
                        self.S.buscar_produto_amazon(url)
            aberto.assert_not_called()

    def test_ca8_buscar_produto_aceito_usa_o_opener_conferido(self):
        resposta = mock.MagicMock()
        resposta.__enter__.return_value = resposta
        resposta.geturl.return_value = 'https://www.amazon.com.br/dp/B0ABCDEFGH?tag=desejodemen01-20'
        resposta.read.return_value = b'<span id="productTitle"> Produto </span>'
        with mock.patch.object(self.S.OPENER_AMAZON, 'open', return_value=resposta) as aberto:
            d = self.S.buscar_produto_amazon('https://amzn.to/abc')
        aberto.assert_called_once()
        self.assertEqual(aberto.call_args.args[0].full_url, 'https://amzn.to/abc')
        self.assertEqual((d['asin'], d['titulo']), ('B0ABCDEFGH', 'Produto'))


if __name__ == '__main__':
    unittest.main()
