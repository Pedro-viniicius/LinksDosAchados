#!/usr/bin/env python3
"""QA da confirmação de preço da Amazon pela API v1 (plano "Rodar sozinho · Entrega 1" do Achadinho Turbo,
Parte A, etapas A1 a A3: CA1.1 e CA1.2). Complementa test_confirmar_preco.py e test_confirmar_preco_servidor.py
(do dev) com o que eles não cobrem: o HTML de verdade passando pelo extrator, o OPENER_AMAZON de verdade
seguindo (ou recusando) redirects, a ordem completa das guardas, o freio sob concorrência real e entre
processos (a trava da rodada), e a coerência entre a resposta da rota e o que a GET /api/v1/ofertas passa a
mostrar.

Uso:  python3 testes/test_confirmar_preco_qa.py -v

A Amazon nunca é aberta: o OPENER_AMAZON.open é falso, ou o opener é um OpenerDirector montado aqui com um
`https_open` falso no lugar do HTTPSHandler (o RedirecionamentoAmazon é o de verdade). O banco é temporário,
o token é gerado aqui (nunca impresso, nunca o api_token.txt do projeto) e a rede bate num proxy morto. Só
biblioteca padrão.
"""
import fcntl
import http.client
import io
import json
import os
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import urllib.response
from http.server import ThreadingHTTPServer
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_servidor as TS  # noqa: E402  (ambiente, porta_livre, RAIZ, DB_REAL, PROXIES_MORTOS)

TMP = tempfile.mkdtemp(prefix='achadinhos-confirmar-qa-')
os.environ['ACHADINHOS_DB'] = os.path.join(TMP, 'import.db')
os.environ.update(TS.PROXIES_MORTOS)
os.environ.pop('ACHADINHOS_API_TOKEN_ARQUIVO', None)
sys.path.insert(0, TS.RAIZ)
import servidor as S  # noqa: E402

assert os.path.dirname(S.DB) == TMP, 'o teste não pode tocar o banco real'

ASIN = 'B0TESTE001'
ASIN_2 = 'B0TESTE004'
ASIN_ML = 'B0TESTE002'
OUTRO = 'B0OUTRO999'
LINK = f'https://www.amazon.com.br/dp/{ASIN}?tag=desejodemen01-20'
ANTIGO = '2026-11-01T08:00:00'
AGORA_1 = '2026-11-11T10:30:00'
AGORA_2 = '2026-11-11T10:45:00'
ROTA = f'/api/v1/amazon/{ASIN}/confirmar-preco'
RE_HORA = r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}'
CINCO = {'confirmado', 'sem_preco', 'outro_produto', 'bloqueado', 'falha_rede'}


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


def html(titulo='Perfume Teste 100ml', preco='R$ 89,90', antigo='R$ 119,90', desconto='-25%'):
    """Trecho de página da Amazon com os ids que o extrator procura. Campo None/'' some da página."""
    h = f'<html><body><span id="productTitle"> {titulo} </span>' if titulo else '<html><body>'
    if preco:
        h += f'<div id="corePrice_feature_div"><span class="a-offscreen">{preco}</span></div>'
    if antigo:
        h += f'<span class="basisPrice"><span class="a-offscreen">{antigo}</span></span>'
    if desconto:
        h += f'<span class="a-size-large savingsPercentage">{desconto}</span>'
    return h + '</body></html>'


def inserir(db, loja='amazon', item_id=ASIN, url=LINK, **campos):
    base = {'loja': loja, 'item_id': item_id, 'cat': 'Perfumes e Perfumaria', 'busca': 'perfume', 'url': url,
            'titulo': 'Perfume Teste 100ml', 'preco': 'R$ 100,00', 'preco_antigo': 'R$ 150,00', 'desconto': '-33%',
            'avaliacao': '4,5 de 5 estrelas', 'num_avaliacoes': '1.234', 'vendas': 'Mais de 50 compras',
            'frete': 'Frete GRÁTIS', 'cupom': 'Cupom de 5%', 'imagem': 'https://m.media-amazon.com/images/I/71t.jpg',
            'tem_dados': 1, 'posicao': 1, 'criado_em': ANTIGO, 'atualizado_em': ANTIGO, 'preco_em': ANTIGO}
    base.update(campos)
    con = sqlite3.connect(db, timeout=30)
    try:
        con.execute(f"INSERT INTO items ({','.join(base)}) VALUES ({','.join('?' * len(base))})", list(base.values()))
        con.commit()
    finally:
        con.close()


def linhas(db):
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
    try:
        return con.execute('SELECT * FROM items ORDER BY id').fetchall()
    finally:
        con.close()


def linha(db, item_id=ASIN, loja='amazon'):
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
    con.row_factory = sqlite3.Row
    try:
        r = con.execute('SELECT * FROM items WHERE loja=? AND item_id=?', (loja, item_id)).fetchone()
        return dict(r) if r else None
    finally:
        con.close()


def banco_novo():
    """Banco do teste sem itens. Não apaga arquivo: uma thread do servidor de teste ainda fechando a conexão
    do pedido anterior apagaria o -wal por baixo (corrida vista em 8 rodadas seguidas)."""
    S.criar_banco()
    con = sqlite3.connect(S.DB, timeout=30)
    try:
        con.execute('DELETE FROM items')
        con.commit()
    finally:
        con.close()


def resposta_falsa(corpo, url, codigo=200):
    """Resposta que o opener devolve: com geturl() e read(), no formato do urllib."""
    r = urllib.response.addinfourl(io.BytesIO(corpo if isinstance(corpo, bytes) else corpo.encode()),
                                   http.client.HTTPMessage(), url, codigo)
    r.msg = 'OK'
    return r


class OpenerQueDevolve:
    """OPENER_AMAZON.open falso que devolve `corpo` como a página da URL pedida (ou de `url_final`)."""

    def __init__(self, corpo, url_final=None):
        self.corpo, self.url_final, self.chamadas = corpo, url_final, []

    def __call__(self, req, timeout=None):
        self.chamadas.append((req.full_url, timeout))
        return resposta_falsa(self.corpo, self.url_final or req.full_url)


class Base(unittest.TestCase):
    def setUp(self):
        banco_novo()
        inserir(S.DB)
        p = mock.patch.object(S.OPENER_AMAZON, 'open', side_effect=AssertionError('teste tentou abrir a rede'))
        p.start()
        self.addCleanup(p.stop)

    def confirmar(self, asin=ASIN, agora=AGORA_1, **kw):
        con = S.conectar()
        try:
            return S.confirmar_preco_amazon(con, asin, agora=lambda: agora, **kw)
        finally:
            con.close()

    def com_pagina(self, corpo, url_final=None, **kw):
        opener = OpenerQueDevolve(corpo, url_final)
        with mock.patch.object(S.OPENER_AMAZON, 'open', opener):
            return self.confirmar(**kw), opener


# ------------------------------------------------------------------ HTML de verdade pelo extrator
class TestPaginaDeVerdade(Base):
    """O dev testa a classificação com dicts; aqui o HTML passa por buscar_produto_amazon + extrair_produto_amazon."""

    def test_pagina_completa_confirma_e_grava(self):
        r, opener = self.com_pagina(html())
        self.assertEqual(r, {'resultado': 'confirmado', 'preco': 89.9, 'preco_antigo': 119.9, 'desconto_pct': 25,
                             'preco_em': AGORA_1})
        self.assertEqual(opener.chamadas, [(f'https://www.amazon.com.br/dp/{ASIN}', 4)])   # S1: 4 s por operação
        l = linha(S.DB)
        self.assertEqual((l['preco'], l['preco_antigo'], l['desconto'], l['preco_em']),
                         ('R$ 89,90', 'R$ 119,90', '-25%', AGORA_1))

    def test_preco_com_espaco_inseparavel_e_milhar(self):
        for texto, esperado in (('R$&nbsp;1.299,90', 1299.9), ('R$\xa01.299,90', 1299.9), ('R$1.299,90', 1299.9),
                                ('R$ 4.285', 4285.0), ('R$ 69,9', 69.9)):
            with self.subTest(texto=texto):
                banco_novo()
                inserir(S.DB)
                r, _ = self.com_pagina(html(preco=texto, antigo='', desconto=''))
                self.assertEqual((r['resultado'], r['preco']), ('confirmado', esperado))

    def test_produto_indisponivel_sem_bloco_de_preco_e_sem_preco(self):
        antes = linhas(S.DB)
        r, _ = self.com_pagina(html(preco='', antigo='', desconto=''))
        self.assertEqual(r, {'resultado': 'sem_preco'})
        self.assertEqual(linhas(S.DB), antes)

    def test_faixa_de_preco_e_preco_ilegivel_nao_gravam(self):
        antes = linhas(S.DB)
        for preco in ('R$ 10,00 - R$ 20,00', 'Indisponível', 'R$ 0,00', 'R$ -5,00', 'R$ 1,2,3', 'R$ 12,34,'):
            with self.subTest(preco=preco):
                r, _ = self.com_pagina(html(preco=preco, antigo='', desconto=''))
                self.assertEqual(r, {'resultado': 'sem_preco'})
                self.assertEqual(linhas(S.DB), antes)

    def test_paginas_estranhas_nunca_levantam_nem_gravam(self):
        """Corpo vazio, binário, só captcha, HTML quebrado: sempre um dos cinco resultados e o banco igual."""
        antes = linhas(S.DB)
        casos = {
            'vazia': b'',
            'binaria': b'\x00\xff\xfe\x80\x81' * 200,
            'só um <': b'<',
            'captcha': b'<html><form action="/errors/validateCaptcha">Digite os caracteres: captcha</form></html>',
            'sem título e com preço': html(titulo='').encode(),
            'tags sem fechar': b'<span id="productTitle"><div id="corePrice_feature_div"><span class="a-offscreen">',
            'grande': b'<div>' * 60000,
            'só texto': 'Tudo em ordem, nada a ver aqui'.encode(),
        }
        for nome, corpo in casos.items():
            with self.subTest(nome):
                r, _ = self.com_pagina(corpo)
                self.assertIn(r['resultado'], CINCO)
                self.assertNotEqual(r['resultado'], 'confirmado')
                self.assertEqual(linhas(S.DB), antes)

    def test_pagina_de_captcha_e_bloqueado_nao_descarte(self):
        antes = linhas(S.DB)
        r, _ = self.com_pagina('<html>captcha <input name="amzn"></html>')
        self.assertEqual(r, {'resultado': 'bloqueado'})
        self.assertEqual(linhas(S.DB), antes)

    def test_titulo_e_html_da_pagina_nao_chegam_a_resposta_nem_ao_banco(self):
        r, _ = self.com_pagina(html(titulo='<script>alert(1)</script> Perfume'))
        self.assertEqual(set(r), {'resultado', 'preco', 'preco_antigo', 'desconto_pct', 'preco_em'})
        l = linha(S.DB)
        self.assertEqual(l['titulo'], 'Perfume Teste 100ml')
        self.assertNotIn('script', json.dumps(l))


# ------------------------------------------------------------------ opener de verdade, redirects reais
class HTTPSFalso(urllib.request.BaseHandler):
    """Fica no lugar do HTTPSHandler: `rotas` mapeia URL -> (código, Location ou corpo). Nunca abre socket."""

    def __init__(self, rotas):
        self.rotas, self.vistas = rotas, []

    def https_open(self, req):
        self.vistas.append(req.full_url)
        codigo, alvo = self.rotas[req.full_url]
        if codigo in (301, 302, 303, 307, 308):
            h = http.client.HTTPMessage()
            h['Location'] = alvo
            r = urllib.response.addinfourl(io.BytesIO(b''), h, req.full_url, codigo)
            r.msg = 'Found'
            return r
        return resposta_falsa(alvo, req.full_url, codigo)


def opener_com(rotas):
    """OpenerDirector com o RedirecionamentoAmazon de verdade e o HTTPS falso. Devolve (opener, https_falso)."""
    falso = HTTPSFalso(rotas)
    op = urllib.request.OpenerDirector()
    for h in (S.RedirecionamentoAmazon(), urllib.request.HTTPErrorProcessor(),
              urllib.request.HTTPDefaultErrorHandler(), falso):
        op.add_handler(h)
    return op, falso


class TestRedirectsReais(Base):
    URL = f'https://www.amazon.com.br/dp/{ASIN}'

    def rodar(self, rotas):
        op, falso = opener_com(rotas)
        antes = linhas(S.DB)
        with mock.patch.object(S, 'OPENER_AMAZON', op):
            r = self.confirmar()
        return r, falso, antes

    def test_redirect_para_fora_da_amazon_e_outro_produto_e_nao_e_seguido(self):
        r, falso, antes = self.rodar({self.URL: (302, f'https://evil.example/dp/{ASIN}')})
        self.assertEqual(r, {'resultado': 'outro_produto'})
        self.assertEqual(falso.vistas, [self.URL])   # o desvio nunca foi pedido
        self.assertEqual(linhas(S.DB), antes)

    def test_redirect_para_http_puro_e_recusado(self):
        r, falso, antes = self.rodar({self.URL: (301, f'http://www.amazon.com.br/dp/{ASIN}')})
        self.assertEqual((r, falso.vistas), ({'resultado': 'outro_produto'}, [self.URL]))
        self.assertEqual(linhas(S.DB), antes)

    def test_redirect_com_usuario_ou_porta_estranha_e_recusado(self):
        for alvo in (f'https://user@www.amazon.com.br/dp/{ASIN}', f'https://www.amazon.com.br:8443/dp/{ASIN}',
                     f'https://www.amazon.com.br.evil.example/dp/{ASIN}'):
            with self.subTest(alvo=alvo):
                r, falso, antes = self.rodar({self.URL: (302, alvo)})
                self.assertEqual((r, falso.vistas), ({'resultado': 'outro_produto'}, [self.URL]))
                self.assertEqual(linhas(S.DB), antes)

    def test_redirect_dentro_da_amazon_para_o_mesmo_asin_e_seguido_e_confirma(self):
        slug = f'https://www.amazon.com.br/Perfume-Teste/dp/{ASIN}/ref=sr_1_1'
        r, falso, _ = self.rodar({self.URL: (301, slug), slug: (200, html())})
        self.assertEqual((r['resultado'], r['preco']), ('confirmado', 89.9))
        self.assertEqual(falso.vistas, [self.URL, slug])
        self.assertEqual(linha(S.DB)['url'], LINK)

    def test_redirect_dentro_da_amazon_para_outro_asin_e_outro_produto(self):
        outro = f'https://www.amazon.com.br/dp/{OUTRO}'
        r, falso, antes = self.rodar({self.URL: (302, outro), outro: (200, html())})
        self.assertEqual(r, {'resultado': 'outro_produto'})
        self.assertEqual(linhas(S.DB), antes)

    def test_redirect_para_a_home_sem_asin_e_bloqueado(self):
        home = 'https://www.amazon.com.br/'
        r, _, antes = self.rodar({self.URL: (302, home), home: (200, '<html>home</html>')})
        self.assertEqual(r, {'resultado': 'bloqueado'})
        self.assertEqual(linhas(S.DB), antes)

    def test_laco_de_redirects_vira_falha_de_rede(self):
        r, falso, antes = self.rodar({self.URL: (302, self.URL)})
        self.assertEqual(r, {'resultado': 'falha_rede'})
        self.assertLessEqual(len(falso.vistas), 11)
        self.assertEqual(linhas(S.DB), antes)

    def test_http_do_opener_de_verdade(self):
        casos = {404: 'sem_preco', 410: 'sem_preco', 429: 'bloqueado', 503: 'bloqueado', 500: 'falha_rede',
                 403: 'falha_rede', 502: 'falha_rede'}
        for codigo, esperado in casos.items():
            with self.subTest(codigo=codigo):
                r, _, antes = self.rodar({self.URL: (codigo, 'corpo qualquer')})
                self.assertEqual(r, {'resultado': esperado})
                self.assertEqual(linhas(S.DB), antes)


# ------------------------------------------------------------------ gravação: estado, repetição, concorrência
class TestGravacaoQA(Base):

    def test_repetir_a_confirmacao_so_renova_o_preco_em(self):
        r1, _ = self.com_pagina(html(), agora=AGORA_1)
        depois_1 = linha(S.DB)
        r2, _ = self.com_pagina(html(), agora=AGORA_2)
        depois_2 = linha(S.DB)
        self.assertEqual((r1['preco'], r2['preco']), (89.9, 89.9))
        self.assertEqual((r1['preco_em'], r2['preco_em']), (AGORA_1, AGORA_2))
        self.assertEqual({c for c in depois_1 if depois_1[c] != depois_2[c]}, {'preco_em', 'atualizado_em'})
        self.assertEqual(len(linhas(S.DB)), 1)

    def test_preco_em_nulo_continua_nulo_na_falha_e_e_carimbado_no_confirmado(self):
        banco_novo()
        inserir(S.DB, preco_em=None)
        for corpo in (html(preco=''), '<html>captcha</html>', html(titulo='')):
            self.com_pagina(corpo)
            self.assertIsNone(linha(S.DB)['preco_em'])
        self.com_pagina(html())
        self.assertEqual(linha(S.DB)['preco_em'], AGORA_1)

    def test_preco_gravado_ilegivel_antes_e_legivel_agora_carimba(self):
        for antigo in ('', 'Consulte', 'R$ 10 - R$ 20'):
            with self.subTest(antigo=antigo):
                banco_novo()
                inserir(S.DB, preco=antigo, preco_antigo='', desconto='', preco_em=None)
                r, _ = self.com_pagina(html())
                self.assertEqual(r['resultado'], 'confirmado')
                self.assertEqual(linha(S.DB)['preco_em'], AGORA_1)

    def test_falha_nao_mexe_nos_outros_itens(self):
        inserir(S.DB, item_id=ASIN_2, url=f'https://www.amazon.com.br/dp/{ASIN_2}?tag=desejodemen01-20')
        inserir(S.DB, loja='ml', item_id=ASIN_ML, url='https://meli.la/1AbC', posicao=3)
        antes = linhas(S.DB)
        self.com_pagina(html())
        depois = linhas(S.DB)
        self.assertEqual(depois[1:], antes[1:])   # só a linha do ASIN muda
        self.assertNotEqual(depois[0], antes[0])

    def test_transacao_de_outra_conexao_so_atrasa_a_gravacao(self):
        """Quem escreve ao mesmo tempo (uma coleta, o site) segura o BEGIN IMMEDIATE por um instante: espera, não falha."""
        outra = sqlite3.connect(S.DB, timeout=30, isolation_level=None, check_same_thread=False)
        outra.execute('BEGIN IMMEDIATE')
        soltou = []

        def solta():
            time.sleep(0.4)
            soltou.append(time.monotonic())   # antes do COMMIT: depois dele a confirmação já pode ter acabado
            outra.execute('COMMIT')
        fio = threading.Thread(target=solta)
        fio.start()
        try:
            r, _ = self.com_pagina(html())
            fim = time.monotonic()
        finally:
            fio.join()
            outra.close()
        self.assertEqual(r['resultado'], 'confirmado')
        self.assertGreaterEqual(fim, soltou[0])   # esperou a outra terminar
        self.assertEqual(linha(S.DB)['preco'], 'R$ 89,90')

    def test_entre_reler_a_linha_e_gravar_ninguem_mais_escreve(self):
        """O BEGIN IMMEDIATE segura o banco do relê até o UPDATE: um DELETE de outra conexão, na hora do UPDATE,
        não passa (sem a transação, o item apagado no intervalo viraria um `confirmado` que não gravou nada)."""
        tentativas = []

        def espia(instrucao):
            if instrucao.startswith('UPDATE items SET preco'):
                outra = sqlite3.connect(S.DB, timeout=0)
                try:
                    outra.execute('DELETE FROM items')
                    outra.commit()
                    tentativas.append('apagou')
                except sqlite3.OperationalError:
                    tentativas.append('bloqueado')
                finally:
                    outra.close()
        con = S.conectar()
        con.set_trace_callback(espia)
        try:
            r = S.confirmar_preco_amazon(con, ASIN, buscar=lambda url, timeout=None: _pagina_dict(html()),
                                         agora=lambda: AGORA_1)
        finally:
            con.set_trace_callback(None)
            con.close()
        self.assertEqual(tentativas, ['bloqueado'])
        self.assertEqual(r['resultado'], 'confirmado')
        self.assertEqual(linha(S.DB)['preco'], 'R$ 89,90')

    def test_duas_confirmacoes_ao_mesmo_tempo_nao_misturam_paginas(self):
        """Preço, antigo e desconto gravados são da mesma página (a última a gravar), nunca um pedaço de cada."""
        paginas = [html(preco='R$ 89,90', antigo='R$ 119,90', desconto='-25%'),
                   html(preco='R$ 79,90', antigo='R$ 109,90', desconto='-27%')]
        barreira = threading.Barrier(2)
        saidas, erros = [], []

        def uma(i):
            def buscar(url, timeout=None):
                barreira.wait(10)
                return S.buscar_produto_amazon.__wrapped__(url, timeout) if False else _pagina_dict(paginas[i])
            con = S.conectar()
            try:
                saidas.append(S.confirmar_preco_amazon(con, ASIN, buscar=buscar, agora=lambda: AGORA_1))
            except Exception as e:   # noqa: BLE001
                erros.append(repr(e))
            finally:
                con.close()
        fios = [threading.Thread(target=uma, args=(i,)) for i in range(2)]
        for f in fios:
            f.start()
        for f in fios:
            f.join()
        self.assertEqual(erros, [])
        self.assertEqual([s['resultado'] for s in saidas], ['confirmado', 'confirmado'])
        l = linha(S.DB)
        self.assertIn((l['preco'], l['preco_antigo'], l['desconto']),
                      [('R$ 89,90', 'R$ 119,90', '-25%'), ('R$ 79,90', 'R$ 109,90', '-27%')])


def _pagina_dict(corpo):
    """O que o buscar_produto_amazon devolveria para `corpo`, sem passar pela rede."""
    return {'url_final': f'https://www.amazon.com.br/dp/{ASIN}', 'asin': ASIN, 'captcha': False,
            **S.extrair_produto_amazon(corpo)}


# ------------------------------------------------------------------ o freio, mais a fundo
class Relogio:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


class TestFreioQA(unittest.TestCase):

    def setUp(self):
        self.relogio = Relogio()
        self.rodada = True
        self.freio = S.FreioReleitura(relogio=self.relogio, rodada_livre=lambda: self.rodada)

    def test_ordem_dos_motivos_ocupado_pausa_intervalo_teto_rodada(self):
        # ocupado ganha de tudo
        self.freio.reservar()
        self.rodada = False
        self.assertEqual(self.freio.reservar()[0], 'ocupado')
        self.freio.liberar('bloqueado')
        # pausa ganha de intervalo (acabou de ler) e de rodada
        self.relogio.t += 1
        self.assertEqual(self.freio.reservar()[0], 'pausa')
        # passada a pausa, rodada vale (intervalo e teto não se aplicam)
        self.relogio.t += S.FREIO_PAUSA_BLOQUEIO_S
        self.assertEqual(self.freio.reservar()[0], 'rodada')
        self.rodada = True

    def test_intervalo_ganha_de_rodada_e_teto_ganha_de_rodada(self):
        self.assertIsNone(self.freio.reservar())
        self.freio.liberar('confirmado')
        self.rodada = False
        self.assertEqual(self.freio.reservar()[0], 'intervalo')
        self.rodada = True
        for _ in range(S.FREIO_TETO_POR_HORA - 1):
            self.relogio.t += S.FREIO_INTERVALO_S
            self.assertIsNone(self.freio.reservar())
            self.freio.liberar('confirmado')
        self.relogio.t += S.FREIO_INTERVALO_S
        self.rodada = False
        self.assertEqual(self.freio.reservar()[0], 'teto')

    def test_retry_after_sempre_inteiro_e_pelo_menos_1(self):
        self.freio.reservar()
        self.freio.liberar('bloqueado')
        for t in (0.0, 0.0001, 3.3, 450.5, 899.9999):
            self.relogio.t = 1000.0 + t
            motivo, seg = self.freio.reservar()
            self.assertIsInstance(seg, int)
            self.assertGreaterEqual(seg, 1)

    def test_janela_desliza_sem_falso_teto(self):
        """Uma leitura a cada 61 s (59 por hora) nunca bate no teto, por mais tempo que passe."""
        for i in range(500):
            self.assertIsNone(self.freio.reservar(), i)
            self.freio.liberar('confirmado')
            self.relogio.t += 61

    def test_liberar_duas_vezes_e_inofensivo(self):
        self.assertIsNone(self.freio.reservar())
        self.freio.liberar('confirmado')
        self.freio.liberar('confirmado')
        self.relogio.t += 3
        self.assertIsNone(self.freio.reservar())

    def test_relogio_real_e_monotonico(self):
        freio = S.FreioReleitura(rodada_livre=lambda: True)
        self.assertIsNone(freio.reservar())
        freio.liberar('confirmado')
        motivo, seg = freio.reservar()
        self.assertEqual(motivo, 'intervalo')
        self.assertIn(seg, (1, 2, 3))

    def test_freio_da_rota_e_unico_do_processo(self):
        self.assertIsInstance(S.FREIO_RELEITURA, S.FreioReleitura)

    def test_trava_que_nao_abre_conta_como_rodada_em_andamento(self):
        with mock.patch.object(S, 'travar_rodada', side_effect=S.RodadaEmAndamento('amazon', 'x.lock', 'permissão')):
            self.assertFalse(S.rodada_amazon_livre())


# ------------------------------------------------------------------ a rota, neste processo
class TestRotaQA(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if os.path.realpath(S.DB) == TS.DB_REAL:
            raise RuntimeError('o teste tentou usar o banco real')
        cls.token = secrets.token_urlsafe(32)
        cls.porta = TS.porta_livre()
        for alvo, nome, valor in ((S, 'API_TOKEN', cls.token), (S, 'HOSTS_LOCAIS', (f'localhost:{cls.porta}',)),
                                  (S.Handler, 'log_message', lambda *a, **k: None)):   # sem ruído; o log é do dev
            p = mock.patch.object(alvo, nome, valor)
            p.start()
            cls.addClassCleanup(p.stop)
        cls.srv = ThreadingHTTPServer(('127.0.0.1', cls.porta), S.Handler)
        cls.addClassCleanup(cls.srv.server_close)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.addClassCleanup(cls.srv.shutdown)

    def setUp(self):
        banco_novo()
        inserir(S.DB)
        inserir(S.DB, item_id=ASIN_2, url=f'https://www.amazon.com.br/dp/{ASIN_2}?tag=desejodemen01-20', posicao=2)
        inserir(S.DB, loja='ml', item_id=ASIN_ML, url='https://meli.la/1AbC', posicao=3)
        self.relogio = Relogio()
        self.corpo_pagina = html()
        self.chamadas = []
        self.durante = None
        self.erro = None
        p1 = mock.patch.object(S, 'FREIO_RELEITURA', S.FreioReleitura(relogio=self.relogio,
                                                                       rodada_livre=lambda: True))
        p2 = mock.patch.object(S.OPENER_AMAZON, 'open', self.abrir)
        p1.start()
        p2.start()
        self.addCleanup(p1.stop)
        self.addCleanup(p2.stop)

    def abrir(self, req, timeout=None):
        self.chamadas.append(req.full_url)
        if self.durante:
            self.durante()
        if self.erro:
            raise self.erro
        return resposta_falsa(self.corpo_pagina, req.full_url)

    def pedir(self, caminho=ROTA, metodo='POST', headers=None, corpo=None, token=True, host=True):
        h = {}
        if host:
            h['Host'] = f'localhost:{self.porta}'
        if token:
            h['Authorization'] = f'Bearer {self.token}'
        h.update(headers or {})
        con = http.client.HTTPConnection('127.0.0.1', self.porta, timeout=15)
        try:
            con.putrequest(metodo, caminho, skip_host=True, skip_accept_encoding=True)
            for k, v in h.items():
                con.putheader(k, v)
            if corpo is not None and 'Content-Length' not in h:
                con.putheader('Content-Length', str(len(corpo)))
            con.endheaders(corpo)
            r = con.getresponse()
            dados = r.read()
        finally:
            con.close()
        return r.status, r.headers, (json.loads(dados) if dados else None)

    def get_ofertas(self, extra=''):
        # ordem relevancia: a padrão (atualizacao) esconde por 60 s o que acabou de ser gravado (FOLGA do cursor)
        st, _, j = self.pedir('/api/v1/ofertas?loja=amazon&limite=200&ordem=relevancia' + extra, metodo='GET')
        self.assertEqual(st, 200, j)
        return {o['item_id']: o for o in j['ofertas']}

    # --- ordem completa das guardas
    def test_ordem_das_guardas(self):
        tem_corpo = dict(corpo=b'x')
        with self.subTest('host de fora ganha de tudo'):
            st, _, j = self.pedir(headers={'Host': 'evil.example', 'Origin': 'https://evil.example'}, token=False,
                                  metodo='GET')
            self.assertEqual((st, j), (403, {'error': 'host não permitido'}))
        with self.subTest('navegador ganha de token e de método'):
            st, _, j = self.pedir(headers={'Origin': 'https://evil.example'}, token=False, metodo='GET')
            self.assertEqual(st, 403, j)
            self.assertIn('navegador', j['error'])
        with self.subTest('navegador ganha da API desligada'):
            with mock.patch.object(S, 'API_TOKEN', None):
                st, _, j = self.pedir(headers={'Sec-Fetch-Site': 'same-origin'})
            self.assertEqual(st, 403, j)
        with self.subTest('API desligada ganha de método e de ASIN'):
            with mock.patch.object(S, 'API_TOKEN', None):
                for metodo, caminho in (('GET', ROTA), ('POST', '/api/v1/amazon/zzz/confirmar-preco')):
                    st, _, j = self.pedir(caminho, metodo=metodo, token=False)
                    self.assertEqual(st, 503, j)
        with self.subTest('token ganha de método, ASIN, corpo e item'):
            for metodo, caminho, extra in (('GET', ROTA, {}), ('POST', '/api/v1/amazon/zzz/confirmar-preco', {}),
                                           ('POST', ROTA, tem_corpo),
                                           ('POST', '/api/v1/amazon/B0TESTE999/confirmar-preco', {})):
                st, hd, _ = self.pedir(caminho, metodo=metodo, token=False, **extra)
                self.assertEqual((st, hd.get('WWW-Authenticate')), (401, 'Bearer'))
        with self.subTest('método ganha de ASIN, corpo e item'):
            for caminho in ('/api/v1/amazon/zzz/confirmar-preco', '/api/v1/amazon/B0TESTE999/confirmar-preco'):
                st, hd, _ = self.pedir(caminho, metodo='GET')
                self.assertEqual((st, hd.get('Allow')), (405, 'POST'))
        with self.subTest('ASIN fora do formato ganha do corpo'):
            st, _, j = self.pedir('/api/v1/amazon/zzz/confirmar-preco', **tem_corpo)
            self.assertEqual((st, j), (404, {'error': 'rota não encontrada'}))
        with self.subTest('corpo ganha do item inexistente'):
            st, _, j = self.pedir('/api/v1/amazon/B0TESTE999/confirmar-preco', **tem_corpo)
            self.assertEqual((st, j), (400, {'error': 'esta rota não aceita corpo'}))
        with self.subTest('item inexistente ganha do freio'):
            S.FREIO_RELEITURA._pausa_ate = self.relogio.t + 100
            st, _, j = self.pedir('/api/v1/amazon/B0TESTE999/confirmar-preco')
            self.assertEqual((st, j), (404, {'error': 'oferta da Amazon não encontrada'}))
            st, _, j = self.pedir(ROTA, **tem_corpo)
            self.assertEqual(st, 400, j)
            st, _, j = self.pedir(f'/api/v1/amazon/{ASIN_ML}/confirmar-preco')
            self.assertEqual(st, 404, j)
        with self.subTest('freio ganha da leitura'):
            st, _, j = self.pedir()
            self.assertEqual((st, j['resultado'], j['motivo']), (429, 'freio', 'pausa'))
        self.assertEqual(self.chamadas, [])

    # --- coerência com o que o Turbo lê depois
    def test_confirmar_faz_a_oferta_reaparecer_na_lista_com_o_mesmo_preco(self):
        self.assertNotIn(ASIN, self.get_ofertas())   # preco_em de 01/11: vencido para a validade de 24 h
        st, _, j = self.pedir()
        self.assertEqual(st, 200, j)
        self.assertEqual(j['resultado'], 'confirmado')
        self.assertEqual(linha(S.DB)['preco_em'], j['preco_em'])
        oferta = self.get_ofertas()[ASIN]
        self.assertEqual((oferta['preco'], oferta['preco_antigo'], oferta['desconto_pct'], oferta['preco_em']),
                         (j['preco'], j['preco_antigo'], j['desconto_pct'], j['preco_em']))
        self.assertEqual(oferta['link'], LINK)   # o link de afiliado é o mesmo

    def test_falha_nao_faz_a_oferta_reaparecer(self):
        for modo in ('sem_preco', 'captcha', 'rede'):
            with self.subTest(modo=modo):
                self.relogio.t += 3600
                self.erro = None
                self.corpo_pagina = {'sem_preco': html(preco=''), 'captcha': '<html>captcha</html>',
                                     'rede': html()}[modo]
                if modo == 'rede':
                    self.erro = urllib.error.URLError('x')
                st, _, j = self.pedir()
                self.assertEqual(st, 200, j)
                self.assertNotEqual(j['resultado'], 'confirmado')
                self.assertNotIn(ASIN, self.get_ofertas())
                self.assertEqual(linha(S.DB)['preco_em'], ANTIGO)

    def test_resposta_do_confirmado_bate_com_a_lista_em_varias_paginas(self):
        """preco, preco_antigo e desconto_pct da rota são os mesmos que o GET /ofertas calcula do banco."""
        paginas = {'com desconto': html(),
                   'sem antigo': html(antigo='', desconto=''),
                   'antigo menor': html(antigo='R$ 50,00', desconto=''),
                   'antigo implausível': html(preco='R$ 10,00', antigo='R$ 90,00', desconto='-89%'),
                   'desconto calculado': html(preco='R$ 75,00', antigo='R$ 100,00', desconto=''),
                   'milhar': html(preco='R$ 1.299,90', antigo='R$ 1.599,00', desconto='-19%')}
        for nome, corpo in paginas.items():
            with self.subTest(nome):
                self.corpo_pagina = corpo
                self.relogio.t += 3600
                st, _, j = self.pedir()
                self.assertEqual((st, j['resultado']), (200, 'confirmado'), j)
                o = self.get_ofertas()[ASIN]
                self.assertEqual(o['preco'], j['preco'])
                self.assertEqual(o['preco_antigo'], j['preco_antigo'])
                self.assertEqual(o['desconto_pct'], j['desconto_pct'] or 0)

    # --- cabeçalhos e forma da resposta
    def test_cabecalhos_do_200_e_do_429(self):
        for _ in range(2):
            st, hd, j = self.pedir()
            self.assertEqual(hd.get('Content-Type'), 'application/json; charset=utf-8')
            self.assertEqual(hd.get('Cache-Control'), 'no-store')
            self.assertFalse([k for k in hd.keys() if k.lower().startswith('access-control-')])
        self.assertEqual(st, 429)
        self.assertEqual(set(j), {'versao', 'resultado', 'motivo', 'tentar_em_s'})
        self.assertEqual(hd.get('Retry-After'), str(j['tentar_em_s']))

    def test_forma_exata_de_cada_resultado(self):
        chaves = {'confirmado': {'versao', 'resultado', 'preco', 'preco_antigo', 'desconto_pct', 'preco_em'},
                  'sem_preco': {'versao', 'resultado'}, 'bloqueado': {'versao', 'resultado'}}
        for corpo, resultado in ((html(), 'confirmado'), (html(preco=''), 'sem_preco'), ('<html>captcha</html>',
                                                                                        'bloqueado')):
            self.corpo_pagina = corpo
            self.relogio.t += 3600
            st, _, j = self.pedir()
            self.assertEqual((st, j['resultado'], set(j)), (200, resultado, chaves[resultado]))
            self.assertIsInstance(j['versao'], int)

    # --- pausa, 404 durante a leitura, concorrência
    def test_pausa_depois_de_bloqueado_vale_para_qualquer_asin(self):
        self.corpo_pagina = '<html>captcha</html>'
        self.assertEqual(self.pedir()[2]['resultado'], 'bloqueado')
        self.relogio.t += 60
        st, hd, j = self.pedir(f'/api/v1/amazon/{ASIN_2}/confirmar-preco')
        self.assertEqual((st, j['motivo']), (429, 'pausa'))
        self.assertEqual(int(hd['Retry-After']), 840)
        self.assertEqual(len(self.chamadas), 1)

    def segurar_liberar(self):
        """Faz o `liberar` do freio esperar o cliente (até 1,5 s) e avisa quando terminou.

        Torna determinístico o escalonamento ruim: se o servidor responde ANTES de liberar o freio, o cliente
        recebe a resposta, mexe no relógio e repete o pedido enquanto o `liberar` ainda espera. Se o servidor libera
        ANTES de responder, o `liberar` espera o prazo, termina e só então a resposta sai.
        """
        cliente_recebeu, liberado = threading.Event(), threading.Event()
        original = S.FREIO_RELEITURA.liberar

        def liberar(resultado=None):
            cliente_recebeu.wait(1.5)
            try:
                return original(resultado)
            finally:
                liberado.set()
        p = mock.patch.object(S.FREIO_RELEITURA, 'liberar', liberar)
        p.start()
        self.addCleanup(p.stop)
        return cliente_recebeu, liberado

    def test_pausa_conta_do_instante_do_bloqueio_mesmo_se_o_cliente_demora_a_ler(self):
        # Q1: a pausa era gravada depois de a resposta sair; o relógio que o cliente mexe logo depois entrava na conta
        cliente_recebeu, liberado = self.segurar_liberar()
        self.corpo_pagina = '<html>captcha</html>'
        self.assertEqual(self.pedir()[2]['resultado'], 'bloqueado')
        self.relogio.t += 60
        cliente_recebeu.set()
        self.assertTrue(liberado.wait(5))
        st, hd, j = self.pedir(f'/api/v1/amazon/{ASIN_2}/confirmar-preco')
        self.assertEqual((st, j['motivo']), (429, 'pausa'))
        self.assertEqual(int(hd['Retry-After']), 840)   # 900 - 60: a pausa nasceu no bloqueio
        self.assertEqual(len(self.chamadas), 1)

    def test_pedido_logo_depois_do_bloqueado_recebe_pausa_e_nao_ocupado(self):
        # Q1: com a resposta já na mão, o freio ainda dizia 'ocupado' (Retry-After 3 s) em vez de 'pausa' (15 min)
        cliente_recebeu, liberado = self.segurar_liberar()
        self.corpo_pagina = '<html>captcha</html>'
        self.assertEqual(self.pedir()[2]['resultado'], 'bloqueado')
        st, hd, j = self.pedir(f'/api/v1/amazon/{ASIN_2}/confirmar-preco')   # sem esperar nada
        cliente_recebeu.set()
        self.assertTrue(liberado.wait(5))
        self.assertEqual((st, j['motivo']), (429, 'pausa'), j)
        self.assertEqual(int(hd['Retry-After']), S.FREIO_PAUSA_BLOQUEIO_S)
        self.assertEqual(len(self.chamadas), 1)

    def test_item_apagado_durante_a_leitura_da_404_e_libera_o_freio(self):
        def apaga():
            con = sqlite3.connect(S.DB)
            con.execute('DELETE FROM items WHERE item_id=?', (ASIN,))
            con.commit()
            con.close()
        self.durante = apaga
        st, _, j = self.pedir()
        self.assertEqual((st, j), (404, {'error': 'oferta da Amazon não encontrada'}))
        self.assertIsNone(linha(S.DB))   # não inseriu de volta
        self.durante = None
        self.relogio.t += 3
        st, _, j = self.pedir(f'/api/v1/amazon/{ASIN_2}/confirmar-preco')
        self.assertEqual((st, j['resultado']), (200, 'confirmado'))   # não ficou "ocupado"

    def test_pedidos_simultaneos_so_um_le(self):
        segura = threading.Event()
        entrou = threading.Event()

        def durante():
            entrou.set()
            segura.wait(5)
        self.durante = durante
        resultados = []
        barreira = threading.Barrier(6)

        def um():
            barreira.wait(10)
            resultados.append(self.pedir()[:3:2])

        fios = [threading.Thread(target=um) for _ in range(6)]
        for f in fios:
            f.start()
        entrou.wait(5)
        time.sleep(0.3)   # os outros cinco já bateram no freio
        segura.set()
        for f in fios:
            f.join()
        status = sorted(r[0] for r in resultados)
        self.assertEqual(status, [200] + [429] * 5, resultados)
        self.assertEqual(len(self.chamadas), 1)
        self.assertEqual({r[1]['motivo'] for r in resultados if r[0] == 429} - {'ocupado', 'intervalo'}, set())

    # --- entradas hostis
    def test_query_string_e_ignorada(self):
        st, _, j = self.pedir(ROTA + '?asin=B0OUTRO999&tag=x&token=abc')
        self.assertEqual((st, j['resultado']), (200, 'confirmado'))
        self.assertEqual(self.chamadas, [f'https://www.amazon.com.br/dp/{ASIN}'])   # a URL vem só do caminho

    def test_caminhos_estranhos_nunca_chegam_a_leitura(self):
        antes = linhas(S.DB)
        caminhos = [f'/api/v1/amazon/{ASIN}/../{ASIN}/confirmar-preco', f'/api/v1/amazon/./{ASIN}/confirmar-preco',
                    f'/api/v1/amazon//{ASIN}/confirmar-preco', f'/api/v1//amazon/{ASIN}/confirmar-preco',
                    f'/api/v1/amazon/{ASIN}%2Fconfirmar-preco', f'/api/v1/amazon/{ASIN}/confirmar-preco%00',
                    f'/api/v1/amazon/{ASIN}/CONFIRMAR-PRECO', f'/API/V1/amazon/{ASIN}/confirmar-preco',
                    f'/api/v1/amazon/B0TESTE00%201/confirmar-preco', '/api/v1/amazon/%41%42%43%44%45%46%47%48%49%4A/'
                    'confirmar-preco', f'/api/v1/amazon/{ASIN};x/confirmar-preco',
                    f'/api/v1/amazon/{ASIN} /confirmar-preco'.replace(' ', '%20')]
        for caminho in caminhos:
            with self.subTest(caminho=caminho):
                st, _, j = self.pedir(caminho)
                self.assertIn(st, (404, 405), j)
        self.assertEqual(self.chamadas, [])
        self.assertEqual(linhas(S.DB), antes)

    def test_content_length_estranho_da_400_sem_ler(self):
        for valor in ('5', '1', 'abc', '-1', '99999999999999999999', '0, 5', '0x0', ' 7 '):
            with self.subTest(valor=valor):
                st, _, j = self.pedir(headers={'Content-Length': valor})
                self.assertEqual((st, j), (400, {'error': 'esta rota não aceita corpo'}))
        self.assertEqual(self.chamadas, [])

    def test_content_length_zero_passa(self):
        for valor in ('0', ' 0 '):
            with self.subTest(valor=valor):
                self.relogio.t += 3
                st, _, j = self.pedir(headers={'Content-Length': valor})
                self.assertEqual(st, 200, j)

    def test_aceita_os_cinco_resultados_sem_vazar_texto_da_pagina(self):
        segredo = 'SEGREDOINTERNODAPAGINA'
        casos = {'sem_preco': html(preco='', titulo=segredo), 'bloqueado': f'<html>captcha {segredo}</html>',
                 'confirmado': html(titulo=segredo)}
        for esperado, corpo in casos.items():
            self.corpo_pagina = corpo
            self.relogio.t += 3600
            st, hd, j = self.pedir()
            self.assertEqual((st, j['resultado']), (200, esperado))
            self.assertNotIn(segredo, json.dumps(j) + str(hd))


# ------------------------------------------------------------------ servidor.py de verdade
class TestServidorDeVerdade(unittest.TestCase):
    """Subprocesso com token num arquivo temporário (nunca o api_token.txt do projeto) e rede num proxy morto."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix='achadinhos-confirmar-qa-srv-')
        cls.addClassCleanup(shutil.rmtree, cls.dir, ignore_errors=True)
        cls.db = os.path.join(cls.dir, 'teste.db')
        cls.token = secrets.token_urlsafe(32)
        cls.arquivo_token = os.path.join(cls.dir, 'api_token.txt')
        fd = os.open(cls.arquivo_token, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'wb') as f:
            f.write(cls.token.encode() + b'\n')
        cls.porta = TS.porta_livre()
        cls.log_err = open(os.path.join(cls.dir, 'stderr.log'), 'wb')
        cls.addClassCleanup(cls.log_err.close)
        env = TS.ambiente(cls.db, cls.porta)
        env.update({'ACHADINHOS_API_TOKEN_ARQUIVO': cls.arquivo_token, 'ACHADINHOS_DISPARO': '0'})
        cls.proc = subprocess.Popen([sys.executable, '-u', 'servidor.py'], cwd=TS.RAIZ, env=env,
                                    stdout=subprocess.PIPE, stderr=cls.log_err)
        cls.addClassCleanup(cls.parar)
        cls.proc.stdout.readline()
        for _ in range(100):
            try:
                socket.create_connection(('127.0.0.1', cls.porta), timeout=0.2).close()
                break
            except OSError:
                if cls.proc.poll() is not None:
                    raise RuntimeError('o servidor de teste saiu')
                time.sleep(0.05)
        inserir(cls.db)

    @classmethod
    def parar(cls):
        if cls.proc.poll() is None:
            cls.proc.terminate()
            try:
                cls.proc.wait(5)
            except subprocess.TimeoutExpired:
                cls.proc.kill()
                cls.proc.wait()
        cls.proc.stdout.close()

    ultima_leitura = 0.0

    def esperar_intervalo(self):
        """O freio do servidor guarda 3 s entre leituras: espera o que falta desde o último POST que leu."""
        falta = TestServidorDeVerdade.ultima_leitura + S.FREIO_INTERVALO_S + 0.2 - time.monotonic()
        if falta > 0:
            time.sleep(falta)

    def pedir(self, caminho=ROTA, metodo='POST', token=True):
        TestServidorDeVerdade.ultima_leitura = time.monotonic()
        h = {'Host': f'localhost:{self.porta}'}
        if token:
            h['Authorization'] = f'Bearer {self.token}'
        con = http.client.HTTPConnection('127.0.0.1', self.porta, timeout=30)
        try:
            con.request(metodo, caminho, headers=h)
            r = con.getresponse()
            dados = r.read()
        finally:
            con.close()
        return r.status, r.headers, (json.loads(dados) if dados else None)

    def test_rodada_da_amazon_em_outro_processo_freia_e_ao_soltar_a_leitura_volta(self):
        """A trava é a mesma que o atualizar_precos.py e a coleta pegam (travar_rodada, no banco do servidor)."""
        antes = linhas(self.db)
        self.esperar_intervalo()
        with mock.patch.object(S, 'DB', self.db), S.travar_rodada('amazon'):
            st, hd, j = self.pedir()
        self.assertEqual((st, j['motivo'], hd.get('Retry-After')), (429, 'rodada', str(S.FREIO_ESPERA_RODADA_S)))
        self.assertEqual(linhas(self.db), antes)
        # solta a trava: a recusa por rodada não gastou intervalo nem teto, a leitura acontece (proxy morto)
        st, _, j = self.pedir()   # sem esperar de novo: se a recusa tivesse contado, daria 'intervalo'
        self.assertEqual((st, j), (200, {'versao': 1, 'resultado': 'falha_rede'}))
        self.assertEqual(linhas(self.db), antes)

    def test_rodada_de_outra_loja_nao_freia(self):
        self.esperar_intervalo()
        with mock.patch.object(S, 'DB', self.db), S.travar_rodada('ml'), S.travar_rodada('shopee'):
            st, hd, j = self.pedir()
        self.assertEqual(st, 200, j)

    def test_a_trava_nao_fica_presa_depois_da_requisicao(self):
        """O servidor pega e solta na hora: uma rodada da Amazon entra logo depois de qualquer pedido."""
        self.pedir()
        with mock.patch.object(S, 'DB', self.db), S.travar_rodada('amazon'):
            pass

    def test_sem_token_no_arquivo_a_rota_responde_503(self):
        """API desligada: o POST também dá 503 (e não abre a Amazon): sobe um servidor sem token."""
        d = tempfile.mkdtemp(prefix='achadinhos-confirmar-qa-503-')
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        db = os.path.join(d, 'x.db')
        porta = TS.porta_livre()
        env = TS.ambiente(db, porta)   # o ambiente já aponta o token para um arquivo que não existe
        env['ACHADINHOS_DISPARO'] = '0'
        proc = subprocess.Popen([sys.executable, '-u', 'servidor.py'], cwd=TS.RAIZ, env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.addCleanup(proc.stdout.close)
        self.addCleanup(proc.wait)
        self.addCleanup(proc.terminate)
        proc.stdout.readline()
        for _ in range(100):
            try:
                socket.create_connection(('127.0.0.1', porta), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.05)
        for token in (None, 'x' * 43):
            con = http.client.HTTPConnection('127.0.0.1', porta, timeout=10)
            h = {'Host': f'localhost:{porta}'}
            if token:
                h['Authorization'] = f'Bearer {token}'
            con.request('POST', ROTA, headers=h)
            r = con.getresponse()
            r.read()
            con.close()
            self.assertEqual(r.status, 503)


if __name__ == '__main__':
    unittest.main()
