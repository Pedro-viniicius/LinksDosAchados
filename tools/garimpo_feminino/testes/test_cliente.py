#!/usr/bin/env python3
"""Testes do cliente.py (etapa 1 do garimpo feminino: CA5, CA7 e CA9). Sem rede.

Rodar: python3 tools/garimpo_feminino/testes/test_cliente.py -v

`CS.OPENER_API.open` é trocado por um falso e `urllib.request.urlopen` por um que falha; o único teste com
HTTP de verdade usa um servidor local em 127.0.0.1 (o 3xx não seguido pelo opener real). Os proxies apontam
para 127.0.0.1:9 (porta morta), o ACHADINHOS_DB vai para uma pasta temporária e as credenciais são
marcadores falsos. Relógio, espera e sorteio são injetados: nenhum teste dorme de verdade.
"""
import contextlib
import email.message
import hashlib
import http.server
import io
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import traceback
import unittest
import urllib.error
import urllib.request
from unittest import mock

PASTA = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAIZ = os.path.dirname(os.path.dirname(PASTA))
TMP = tempfile.mkdtemp(prefix='teste-garimpo-cliente-')
for v in ('http_proxy', 'https_proxy', 'ftp_proxy'):
    os.environ[v] = 'http://127.0.0.1:9'
os.environ['no_proxy'] = ''
os.environ['ACHADINHOS_DB'] = os.path.join(TMP, 'achadinhos.db')
os.environ['ACHADINHOS_FEITOS_SHOPEE'] = os.path.join(TMP, 'feitos-shopee.txt')
os.environ['ACHADINHOS_GARIMPO_DIR'] = os.path.join(TMP, 'garimpo')
for v in ('ACHADINHOS_SHOPEE_APP_ID', 'ACHADINHOS_SHOPEE_SECRET'):
    os.environ.pop(v, None)
sys.path.insert(0, PASTA)

import cliente as K  # noqa: E402

CS = K.CS
S = CS.S
assert os.path.dirname(S.DB) == TMP and os.path.dirname(CS.FEITOS) == TMP, 'o teste não pode tocar os dados reais'

SECRET = 'SEGREDO-MARCADOR-c41e07'   # procurado em toda saída: nunca pode aparecer
APP_ID = '1800012345'
TS = 1_700_000_000
URL_FIXA = 'https://open-api.affiliate.shopee.com.br/graphql'
CONSULTA = '''query Busca($keyword: String, $page: Int, $limit: Int) {
  productOfferV2(keyword: $keyword, page: $page, limit: $limit) {
    nodes { itemId productName }
    pageInfo { page limit hasNextPage }
  }
}'''
VARS = {'keyword': 'vestido', 'page': 1, 'limit': 50}
CAMPOS_REGISTRO = {'operacao', 'http', 'codigo', 'ms', 'bytes', 'em'}


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


def cred():
    return (APP_ID, CS.Segredo(SECRET))


def resposta(nos=({'itemId': 1, 'productName': 'Vestido'},)):
    return {'data': {'productOfferV2': {'nodes': list(nos), 'pageInfo': {'page': 1, 'limit': 50, 'hasNextPage': False}}}}


def erro(codigo, mensagem='falhou'):
    return {'errors': [{'message': mensagem, 'extensions': {'code': codigo, 'message': mensagem}}]}


def http_erro(codigo, corpo=b'', location=None, motivo='x'):
    h = email.message.Message()
    if location:
        h['Location'] = location
    if isinstance(corpo, dict):
        corpo = json.dumps(corpo).encode()
    return urllib.error.HTTPError(URL_FIXA, codigo, motivo, h, io.BytesIO(corpo))


class Resp(io.BytesIO):
    """Resposta falsa do opener (context manager com read e status)."""
    status = 200


class ApiFalsa:
    """Troca o CS.OPENER_API.open: devolve as respostas da fila e guarda as requisições e os timeouts."""
    def __init__(self, *respostas):
        self.fila, self.pedidos, self.timeouts = list(respostas), [], []

    def __call__(self, req, timeout=None):
        self.pedidos.append(req)
        self.timeouts.append(timeout)
        r = self.fila.pop(0) if self.fila else resposta()
        if isinstance(r, BaseException):
            raise r
        return Resp(r if isinstance(r, bytes) else json.dumps(r).encode())

    def corpos(self):
        return [json.loads(p.data) for p in self.pedidos]


class Relogio:
    """Relógio monotônico falso: a espera só avança o tempo e fica anotada."""
    def __init__(self):
        self.t, self.esperas = 1000.0, []

    def mono(self):
        return self.t

    def dormir(self, s):
        self.esperas.append(s)
        self.t += s


class Base(unittest.TestCase):
    def setUp(self):
        self.rel = Relogio()
        self.registros, self.sorteios = [], []
        self.fator = lambda a, b: (a + b) / 2   # sorteio padrão: o meio da faixa
        p = mock.patch.object(K.time, 'sleep', side_effect=AssertionError('sleep de verdade'))
        p.start(); self.addCleanup(p.stop)

    def sortear(self, a, b):
        self.sorteios.append((a, b))
        return self.fator(a, b)

    def novo(self, **k):
        k.setdefault('parede', lambda: TS)
        k.setdefault('monotonico', self.rel.mono)
        k.setdefault('dormir', self.rel.dormir)
        k.setdefault('aleatorio', self.sortear)
        return K.Cliente(k.pop('cred', None) or cred(), **k)

    def pedir(self, cli, api, consulta=CONSULTA, variaveis=VARS):
        with mock.patch.object(CS.OPENER_API, 'open', api), \
                mock.patch.object(urllib.request, 'urlopen', side_effect=AssertionError('urlopen direto')):
            return cli.pedir(consulta, variaveis, registrar=self.registros.append)


class TestAssinatura(Base):
    def test_assinatura_calculada_sobre_o_corpo_exato_enviado(self):
        variaveis = {'keyword': 'sutiã "x" ", sortType: 5) { __typename }', 'page': 2, 'limit': 50,
                     'productCatId': '100017'}
        api = ApiFalsa()
        self.pedir(self.novo(), api, variaveis=variaveis)
        req = api.pedidos[0]
        corpo = req.data.decode('utf-8')
        sig = hashlib.sha256(f'{APP_ID}{TS}{corpo}{SECRET}'.encode('utf-8')).hexdigest()
        self.assertEqual(req.get_header('Authorization'),
                         f'SHA256 Credential={APP_ID}, Timestamp={TS}, Signature={sig}')
        self.assertTrue(corpo.isascii(), 'texto assinado e bytes enviados têm de ser os mesmos')

    def test_valores_so_em_variables(self):
        for termo in ('", sortType: 5) { __typename }', '\n', '{ itemId }', '‮', 'a' * 5000, "'; DROP"):
            with self.subTest(termo=termo[:20]):
                api = ApiFalsa()
                self.pedir(self.novo(), api, variaveis={'keyword': termo, 'page': 1})
                corpo = api.corpos()[0]
                self.assertEqual(set(corpo), {'query', 'variables'})
                self.assertEqual(corpo['query'], CONSULTA)
                self.assertEqual(corpo['variables'], {'keyword': termo, 'page': 1})

    def test_corpo_canonico_nao_depende_da_ordem_das_chaves(self):
        a, b = ApiFalsa(), ApiFalsa()
        self.pedir(self.novo(), a, variaveis={'page': 1, 'keyword': 'saia', 'limit': 20})
        self.pedir(self.novo(), b, variaveis={'limit': 20, 'keyword': 'saia', 'page': 1})
        self.assertEqual(a.pedidos[0].data, b.pedidos[0].data)

    def test_metodo_cabecalhos_e_timeout(self):
        api = ApiFalsa()
        self.pedir(self.novo(), api)
        req = api.pedidos[0]
        self.assertEqual(req.get_method(), 'POST')
        self.assertEqual(req.get_header('Content-type'), 'application/json')
        self.assertEqual(api.timeouts, [CS.TIMEOUT])
        for nome, valor in req.header_items():
            self.assertNotIn(SECRET, valor, nome)

    def test_timestamp_em_segundos_do_relogio_de_parede(self):
        api = ApiFalsa()
        self.pedir(self.novo(parede=lambda: TS + 0.9), api)
        self.assertIn(f'Timestamp={TS},', api.pedidos[0].get_header('Authorization'))

    def test_credencial_so_do_coletar_shopee(self):
        for ruim in ((APP_ID, SECRET), [APP_ID, CS.Segredo(SECRET)], (1, CS.Segredo(SECRET)), None, (APP_ID,)):
            with self.subTest(tipo=type(ruim).__name__):
                with self.assertRaises(TypeError) as cm:
                    K.Cliente(ruim)
                self.assertNotIn(SECRET, str(cm.exception))

    def test_credenciais_do_ambiente_tiram_o_secret_e_assinam(self):
        with mock.patch.dict(os.environ, {'ACHADINHOS_SHOPEE_APP_ID': APP_ID, 'ACHADINHOS_SHOPEE_SECRET': SECRET}):
            c = CS.credenciais()
            self.assertNotIn('ACHADINHOS_SHOPEE_SECRET', os.environ)
        api = ApiFalsa()
        self.pedir(self.novo(cred=c), api)
        corpo = api.pedidos[0].data.decode()
        self.assertIn(hashlib.sha256(f'{APP_ID}{TS}{corpo}{SECRET}'.encode()).hexdigest(),
                      api.pedidos[0].get_header('Authorization'))

    def test_consulta_e_variaveis_invalidas_nao_mandam_nada(self):
        casos = [('', VARS, TypeError), (None, VARS, TypeError), (CONSULTA, None, TypeError),
                 (CONSULTA, [('page', 1)], TypeError), (CONSULTA, {1: 'x'}, TypeError),
                 (CONSULTA, {'preco': float('nan')}, ValueError), (CONSULTA, {'x': object()}, TypeError)]
        for consulta, variaveis, erro_esperado in casos:
            with self.subTest(consulta=str(consulta)[:10], variaveis=repr(variaveis)[:30]):
                api, cli = ApiFalsa(), self.novo()
                with self.assertRaises(erro_esperado):
                    self.pedir(cli, api, consulta=consulta, variaveis=variaveis)
                self.assertEqual((api.pedidos, cli.feitas), ([], 0))
        with self.assertRaises(TypeError):
            self.novo().pedir(CONSULTA, VARS, registrar=None)


class TestHost(Base):
    def test_full_url_fixa_mesmo_com_variavel_de_ambiente(self):
        self.assertEqual(CS.URL_API, URL_FIXA)
        for var in ('ACHADINHOS_SHOPEE_URL', 'ACHADINHOS_SHOPEE_API', 'SHOPEE_URL', 'ACHADINHOS_URL_API',
                    'ACHADINHOS_GARIMPO_URL', 'URL_API'):
            with self.subTest(var=var):
                api = ApiFalsa()
                with mock.patch.dict(os.environ, {var: 'https://evil.com/graphql'}):
                    self.pedir(self.novo(), api)
                self.assertEqual(api.pedidos[0].full_url, URL_FIXA)

    def test_fonte_com_um_so_ponto_de_rede_e_sem_ambiente(self):
        with open(os.path.join(PASTA, 'cliente.py'), encoding='utf-8') as f:
            fonte = f.read()
        self.assertEqual(len(re.findall(r'OPENER_API\.open\(', fonte)), 1)
        for proibido in ('urlopen(', 'build_opener(', 'http.client', 'socket', 'os.environ', 'getenv'):
            self.assertNotIn(proibido, fonte)


class TestRedirecionamento(Base):
    def test_3xx_do_opener_vira_erro_sem_segundo_pedido(self):
        api = ApiFalsa(http_erro(302, location='https://evil.com/graphql'))
        cli = self.novo()
        with self.assertRaises(CS.ErroApi) as cm:
            self.pedir(cli, api)
        self.assertEqual((cm.exception.http, len(api.pedidos), cli.feitas), (302, 1, 1))
        self.assertEqual(self.registros[0]['http'], 302)

    def test_opener_real_nao_segue_3xx_nem_reenvia_a_assinatura(self):
        visitas = []

        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers.get('Content-Length') or 0))
                visitas.append((self.path, self.headers.get('Authorization') is not None))
                self.send_response(302)
                self.send_header('Location', '/outro')
                self.send_header('Content-Length', '0')
                self.end_headers()

            def do_GET(self):
                visitas.append((self.path, self.headers.get('Authorization') is not None))
                corpo = json.dumps(resposta()).encode()
                self.send_response(200)
                self.send_header('Content-Length', str(len(corpo)))
                self.end_headers()
                self.wfile.write(corpo)

            def log_message(self, *a):
                pass

        srv = http.server.HTTPServer(('127.0.0.1', 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        cli = self.novo()
        with mock.patch.object(CS, 'URL_API', f'http://127.0.0.1:{srv.server_port}/graphql'), \
                mock.patch.dict(os.environ, {'no_proxy': '127.0.0.1'}), \
                mock.patch.object(urllib.request, 'urlopen', side_effect=AssertionError('urlopen direto')):
            with self.assertRaises(CS.ErroApi) as cm:
                cli.pedir(CONSULTA, VARS, registrar=self.registros.append)
        self.assertEqual(cm.exception.http, 302)
        self.assertEqual(visitas, [('/graphql', True)])


class TestResposta(Base):
    def test_devolve_o_data(self):
        self.assertEqual(self.pedir(self.novo(), ApiFalsa(resposta())), resposta()['data'])

    def test_resposta_no_teto_entra_e_acima_de_2_mb_e_recusada(self):
        self.assertEqual(CS.MAX_RESPOSTA, 2 * 1024 * 1024)
        base = json.dumps(resposta()).encode()
        no_teto = base + b' ' * (CS.MAX_RESPOSTA - len(base))
        self.assertEqual(self.pedir(self.novo(), ApiFalsa(no_teto)), resposta()['data'])
        self.assertEqual(self.registros[-1]['bytes'], CS.MAX_RESPOSTA)
        with self.assertRaises(CS.RespostaInvalida):
            self.pedir(self.novo(), ApiFalsa(no_teto + b' '))
        self.assertEqual(self.registros[-1]['http'], 200)

    def test_resposta_fora_do_formato(self):
        for ruim in (b'nao e json', b'[]', b'"x"', {'data': None}, {'data': []}, {'outro': 1}, b'[' * 100000):
            with self.subTest(ruim=repr(ruim)[:30]):
                with self.assertRaises(CS.RespostaInvalida):
                    self.pedir(self.novo(), ApiFalsa(ruim))

    def test_erro_da_api_nao_e_repetido(self):
        for corpo, codigo in ((erro(10010), 10010), (erro('10020'), 10020), (erro(None), 0)):
            with self.subTest(codigo=codigo):
                api = ApiFalsa(corpo)
                with self.assertRaises(CS.ErroApi) as cm:
                    self.pedir(self.novo(), api)
                self.assertEqual((cm.exception.codigo, len(api.pedidos)), (codigo, 1))
                self.assertEqual(self.registros[-1]['codigo'], codigo)

    def test_http_fora_do_2xx(self):
        api = ApiFalsa(http_erro(500, erro(123)))
        with self.assertRaises(CS.ErroApi) as cm:
            self.pedir(self.novo(), api)
        self.assertEqual((cm.exception.codigo, cm.exception.http), (123, 500))
        api = ApiFalsa(http_erro(403, b'<html>'))
        with self.assertRaises(CS.ErroApi) as cm:
            self.pedir(self.novo(), api)
        self.assertEqual((cm.exception.codigo, cm.exception.http), (None, 403))

    def test_falha_de_rede_vira_erro_api_e_e_registrada(self):
        for falha in (urllib.error.URLError('recusada'), TimeoutError('timed out'), ConnectionResetError()):
            with self.subTest(falha=type(falha).__name__):
                self.registros.clear()
                cli = self.novo()
                with self.assertRaises(CS.ErroApi) as cm:
                    self.pedir(cli, ApiFalsa(falha))
                self.assertEqual((cm.exception.codigo, cm.exception.http), (None, None))
                self.assertEqual(len(self.registros), 1)
                self.assertEqual(cli.feitas, 1)


class TestCodigoForaDaFaixa(Base):
    """R3: código fora do int64 não pode derrubar o `registrar` real (o pedido sumiria de `requisicoes`)."""

    def test_vira_none_no_registro_e_o_erro_mantem_o_codigo(self):
        import banco
        for codigo in (2 ** 63, 2 ** 80, -(2 ** 63), -(2 ** 70)):
            with self.subTest(codigo=codigo):
                con = banco.abrir(os.path.join(tempfile.mkdtemp(dir=TMP), 'garimpo.db'))
                self.addCleanup(con.close)
                registrados = []

                def registrar(req):
                    registrados.append(req)
                    banco.registrar_requisicao(con, None, None, req)   # o mesmo que a fase e o motor fazem

                with mock.patch.object(CS.OPENER_API, 'open', ApiFalsa(erro(codigo))):
                    with self.assertRaises(CS.ErroApi) as ctx:
                        K.Cliente(cred(), dormir=lambda s: None).pedir(CONSULTA, VARS, registrar=registrar)
                self.assertEqual(ctx.exception.codigo, codigo)   # a API respondeu com erro: continua sendo "com código"
                self.assertIsNone(registrados[0]['codigo'])
                self.assertEqual(con.execute('SELECT operacao, codigo FROM requisicoes').fetchall(),
                                 [('productOfferV2', None)])

    def test_borda_do_int64_fica_como_veio(self):
        registrados = []
        for codigo in (2 ** 63 - 1, -(2 ** 63 - 1), 10010, 0):
            with mock.patch.object(CS.OPENER_API, 'open', ApiFalsa(erro(codigo))):
                with self.assertRaises(CS.ErroApi):
                    K.Cliente(cred(), dormir=lambda s: None).pedir(CONSULTA, VARS, registrar=registrados.append)
        self.assertEqual([r['codigo'] for r in registrados], [2 ** 63 - 1, -(2 ** 63 - 1), 10010, 0])


class TestErroDeSistema(Base):
    """10000 (System Error) é intermitente: poucas tentativas curtas, cada uma registrada e contada."""

    def cliente(self, **kw):
        self.esperas = []
        return K.Cliente(cred(), dormir=self.esperas.append, aleatorio=lambda a, b: a, **kw)

    def test_repete_e_devolve_a_resposta_boa(self):
        for falhas in (1, K.TENTATIVAS_SISTEMA):
            with self.subTest(falhas=falhas):
                registros = []
                api = ApiFalsa(*[erro(K.ERRO_SISTEMA)] * falhas, resposta())
                cli = self.cliente()
                with mock.patch.object(CS.OPENER_API, 'open', api):
                    dados = cli.pedir(CONSULTA, VARS, registrar=registros.append)
                self.assertIn('productOfferV2', dados)
                self.assertEqual(len(api.pedidos), falhas + 1)
                self.assertEqual(cli.feitas, falhas + 1)                       # conta no orçamento
                self.assertEqual([r['codigo'] for r in registros], [K.ERRO_SISTEMA] * falhas + [None])

    def test_desiste_depois_do_teto_com_erro_api(self):
        registros = []
        api = ApiFalsa(*[erro(K.ERRO_SISTEMA)] * 20)
        cli = self.cliente()
        with mock.patch.object(CS.OPENER_API, 'open', api):
            with self.assertRaises(CS.ErroApi) as ctx:
                cli.pedir(CONSULTA, VARS, registrar=registros.append)
        self.assertEqual((ctx.exception.codigo, ctx.exception.http), (K.ERRO_SISTEMA, None))
        self.assertEqual(K.TENTATIVAS_SISTEMA, 3)
        self.assertEqual(len(api.pedidos), K.TENTATIVAS_SISTEMA + 1)
        self.assertEqual(len(registros), K.TENTATIVAS_SISTEMA + 1)

    def test_espera_de_segundos_nada_do_backoff_do_limite(self):
        api = ApiFalsa(*[erro(K.ERRO_SISTEMA)] * 20)
        cli = self.cliente()
        with mock.patch.object(CS.OPENER_API, 'open', api), self.assertRaises(CS.ErroApi):
            cli.pedir(CONSULTA, VARS, registrar=lambda r: None)
        longas = [e for e in self.esperas if e >= K.ESPERA_SISTEMA]
        self.assertEqual(longas, [K.ESPERA_SISTEMA * 2 ** k for k in range(K.TENTATIVAS_SISTEMA)])
        self.assertLess(max(self.esperas), K.BACKOFF_BASE * K.BACKOFF_FATOR[0])

    def test_em_http_de_erro_tambem_repete_e_sobe_com_o_http(self):
        api = ApiFalsa(*[http_erro(500, corpo=erro(K.ERRO_SISTEMA)) for _ in range(20)])
        cli = self.cliente()
        with mock.patch.object(CS.OPENER_API, 'open', api):
            with self.assertRaises(CS.ErroApi) as ctx:
                cli.pedir(CONSULTA, VARS, registrar=lambda r: None)
        self.assertEqual((ctx.exception.codigo, ctx.exception.http), (K.ERRO_SISTEMA, 500))
        self.assertEqual(len(api.pedidos), K.TENTATIVAS_SISTEMA + 1)

    def test_o_http_e_o_da_ultima_tentativa(self):
        api = ApiFalsa(*[http_erro(500, corpo=erro(K.ERRO_SISTEMA)) for _ in range(K.TENTATIVAS_SISTEMA)],
                       erro(K.ERRO_SISTEMA))
        with mock.patch.object(CS.OPENER_API, 'open', api), self.assertRaises(CS.ErroApi) as ctx:
            self.cliente().pedir(CONSULTA, VARS, registrar=lambda r: None)
        self.assertEqual((ctx.exception.codigo, ctx.exception.http), (K.ERRO_SISTEMA, None))

    def test_o_teto_da_rodada_para_as_tentativas(self):
        api = ApiFalsa(*[erro(K.ERRO_SISTEMA)] * 20)
        cli = self.cliente(max_rodada=2)
        with mock.patch.object(CS.OPENER_API, 'open', api), self.assertRaises(K.Teto):
            cli.pedir(CONSULTA, VARS, registrar=lambda r: None)
        self.assertEqual(len(api.pedidos), 2)
        self.assertLess(sum(1 for e in self.esperas if e >= K.ESPERA_SISTEMA), 2, 'sem orçamento, não espera à toa')

    def test_outros_codigos_nao_repetem(self):
        for codigo in (10010, 10020, 11001, 0):
            with self.subTest(codigo=codigo):
                api = ApiFalsa(*[erro(codigo)] * 5)
                with mock.patch.object(CS.OPENER_API, 'open', api), self.assertRaises(CS.ErroApi):
                    self.cliente().pedir(CONSULTA, VARS, registrar=lambda r: None)
                self.assertEqual(len(api.pedidos), 1)

    def test_contadores_de_limite_e_de_sistema_sao_separados(self):
        api = ApiFalsa(erro(K.ERRO_SISTEMA), erro(CS.ERRO_LIMITE), erro(K.ERRO_SISTEMA), erro(CS.ERRO_LIMITE),
                       erro(K.ERRO_SISTEMA), resposta())
        cli = self.cliente()
        with mock.patch.object(CS.OPENER_API, 'open', api):
            self.assertIn('productOfferV2', cli.pedir(CONSULTA, VARS, registrar=lambda r: None))
        self.assertEqual(len(api.pedidos), 6)


class TestClassificaErro(unittest.TestCase):
    """erro_permanente: a API julgou o pedido (com código ou HTTP 4xx). O resto é falha de transporte ou de
    autenticação: não é medição nem consulta recusada."""

    def test_tabela(self):
        for codigo, http, esperado in (
                (10010, None, True), (0, None, True), (10020, 200, True), (10010, 400, True), (None, 400, True),
                (None, 404, True), (None, 422, True),
                (None, None, False), (None, 500, False), (None, 503, False), (10020, 500, False), (10020, 599, False),
                (None, 401, False), (None, 403, False), (10020, 401, False), (10020, 403, False),
                (None, 302, False), (None, 200, False), (None, 399, False), (None, 499, True), (None, 600, False),
                (CS.ERRO_LIMITE, None, False), (CS.ERRO_LIMITE, 200, False), (None, 429, False), (10010, 429, False),
                (K.ERRO_SISTEMA, None, False), (K.ERRO_SISTEMA, 200, False), (K.ERRO_SISTEMA, 400, False),
                (10001, None, True), (9999, None, True)):
            with self.subTest(codigo=codigo, http=http):
                self.assertIs(K.erro_permanente(codigo, http), esperado)


class TestBackoff(Base):
    def test_cinco_esperas_e_depois_limite_atingido(self):
        api = ApiFalsa(*[erro(10030)] * 10)
        cli = self.novo()
        with self.assertRaises(CS.LimiteAtingido):
            self.pedir(cli, api)
        self.assertEqual(len(api.pedidos), 6)
        self.assertEqual(self.rel.esperas, [30, 60, 120, 240, 480])
        self.assertEqual([r['codigo'] for r in self.registros], [10030] * 6)
        self.assertEqual(cli.feitas, 6)
        self.assertIn((0.8, 1.2), self.sorteios)

    def test_http_429_e_codigo_em_texto_tambem_esperam(self):
        api = ApiFalsa(http_erro(429), http_erro(400, erro('10030')), erro('10030'), http_erro(429, b'x'), resposta())
        self.assertEqual(self.pedir(self.novo(), api), resposta()['data'])
        self.assertEqual(len(api.pedidos), 5)
        self.assertEqual(self.rel.esperas, [30, 60, 120, 240])
        self.assertEqual([r['http'] for r in self.registros], [429, 400, 200, 429, 200])

    def test_jitter_do_backoff_nas_bordas(self):
        for fator, esperado in ((0.8, [24, 48, 96, 192, 384]), (1.2, [36, 72, 144, 288, 576])):
            with self.subTest(fator=fator):
                self.rel.esperas.clear()
                self.fator = lambda a, b, f=fator: f if (a, b) == (0.8, 1.2) else 0
                with self.assertRaises(CS.LimiteAtingido):
                    self.pedir(self.novo(), ApiFalsa(*[erro(10030)] * 6))
                self.assertEqual([round(x, 6) for x in self.rel.esperas], esperado)

    def test_formula_com_teto_de_900(self):
        um = lambda a, b: 1.0  # noqa: E731
        self.assertEqual([K.espera_backoff(k, um) for k in range(7)], [30, 60, 120, 240, 480, 900, 900])
        self.assertEqual(K.espera_backoff(9, lambda a, b: b), 900 * 1.2)


class TestRitmo(Base):
    def test_segundo_pedido_espera_pausa_mais_jitter(self):
        self.fator = lambda a, b: b
        api, cli = ApiFalsa(), self.novo()
        self.pedir(cli, api)
        self.assertEqual(self.rel.esperas, [])
        self.pedir(cli, api)
        self.assertEqual(self.rel.esperas, [1.25])
        self.assertIn((0, 0.25), self.sorteios)

    def test_tempo_ja_passado_nao_espera(self):
        api, cli = ApiFalsa(), self.novo()
        self.pedir(cli, api)
        self.rel.t += 1.3
        self.pedir(cli, api)
        self.assertEqual(self.rel.esperas, [])

    def test_pausa_ajustavel_com_piso(self):
        self.fator = lambda a, b: a
        api, cli = ApiFalsa(), self.novo(pausa=0.5)
        self.pedir(cli, api)
        self.pedir(cli, api)
        self.assertEqual(self.rel.esperas, [0.5])
        for ruim in (0.49, 0, -1, float('nan'), float('inf'), 61, True, '1', None):
            with self.subTest(pausa=ruim):
                with self.assertRaises(ValueError):
                    self.novo(pausa=ruim)


class TestTeto(Base):
    def test_padrao_e_tipo(self):
        self.assertEqual(K.MAX_TOTAL_REQUESTS, 20_000)
        self.assertTrue(issubclass(K.Teto, CS.ErroColeta))

    def test_teto_total_conta_o_que_ja_esta_no_banco(self):
        api, cli = ApiFalsa(), self.novo(ja_feitas=19_999)
        self.pedir(cli, api)
        with self.assertRaises(K.Teto) as cm:
            self.pedir(cli, api)
        self.assertEqual(cm.exception.qual, 'total')
        self.assertEqual((len(api.pedidos), len(self.registros), self.rel.esperas), (1, 1, []))

    def test_teto_total_ja_esgotado_nao_manda_nada(self):
        api = ApiFalsa()
        with self.assertRaises(K.Teto):
            self.pedir(self.novo(ja_feitas=10, max_total=10), api)
        self.assertEqual((api.pedidos, self.registros), ([], []))

    def test_teto_por_rodada(self):
        api, cli = ApiFalsa(), self.novo(max_rodada=2)
        self.pedir(cli, api)
        self.pedir(cli, api)
        with self.assertRaises(K.Teto) as cm:
            self.pedir(cli, api)
        self.assertEqual((cm.exception.qual, len(api.pedidos), cli.feitas), ('rodada', 2, 2))

    def test_tentativas_do_limite_contam_no_teto_sem_espera_inutil(self):
        api, cli = ApiFalsa(*[erro(10030)] * 10), self.novo(max_rodada=3)
        with self.assertRaises(K.Teto) as cm:
            self.pedir(cli, api)
        self.assertEqual((cm.exception.qual, len(api.pedidos)), ('rodada', 3))
        self.assertEqual(self.rel.esperas, [30, 60])

    def test_parametros_invalidos(self):
        for k in ({'max_total': 0}, {'max_total': True}, {'max_total': '10'}, {'max_total': 1.5},
                  {'max_rodada': 0}, {'max_rodada': -1}, {'ja_feitas': -1}, {'ja_feitas': None}):
            with self.subTest(**k):
                with self.assertRaises(ValueError):
                    self.novo(**k)


class TestSegredo(Base):
    def textos_da_excecao(self, e, locais):
        """str, repr e traceback. Com `locais`, o traceback leva o repr das variáveis de cada frame."""
        return [str(e), repr(e), ''.join(traceback.format_exception(e)),
                ''.join(traceback.TracebackException.from_exception(e, capture_locals=locais).format())]

    def test_marcador_ausente_em_repr_excecoes_e_registrar(self):
        excecoes, cli = [], self.novo()
        out, err = io.StringIO(), io.StringIO()
        # (resposta falsa, conferir também o repr das variáveis locais). Texto que a própria API devolve (eco)
        # pode ficar numa variável local (a resposta já lida): ali só str, repr e o traceback comum.
        cenarios = [
            (ApiFalsa(resposta()), True),
            (ApiFalsa(*[erro(10030)] * 6), True),
            (ApiFalsa(http_erro(500, erro(1, mensagem=f'eco {SECRET}'), motivo=f'eco {SECRET}')), True),
            (ApiFalsa(http_erro(302, location=f'https://evil.com/?s={SECRET}')), True),
            (ApiFalsa(OSError(f'falhou com {SECRET}')), True),
            (ApiFalsa(urllib.error.URLError(SECRET)), True),
            (ApiFalsa(b'{"x": '), True),
            (ApiFalsa(erro(10010, mensagem=f'eco {SECRET}')), False),
        ]
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            for api, locais in cenarios:
                try:
                    self.pedir(cli, api)
                except CS.ErroColeta as e:
                    excecoes.append((e, locais))
            try:
                self.pedir(self.novo(max_rodada=1, ja_feitas=0), ApiFalsa(*[erro(10030)] * 3))
            except K.Teto as e:
                excecoes.append((e, True))
        self.assertEqual([type(e).__name__ for e, _ in excecoes],
                         ['LimiteAtingido', 'ErroApi', 'ErroApi', 'ErroApi', 'ErroApi', 'RespostaInvalida', 'ErroApi',
                          'Teto'])
        textos = [x for e, locais in excecoes for x in self.textos_da_excecao(e, locais)]
        textos += [repr(cli), str(cli), repr(vars(cli)), repr(cred()), json.dumps(self.registros),
                   out.getvalue(), err.getvalue()]
        tudo = '\n'.join(textos)
        self.assertNotIn(SECRET, tudo)
        self.assertNotIn('Signature=', tudo)
        self.assertNotIn('Authorization', json.dumps(self.registros))
        self.assertEqual((out.getvalue(), err.getvalue()), ('', ''))

    def test_registro_so_com_os_campos_permitidos(self):
        api = ApiFalsa(erro(10030), resposta())
        self.pedir(self.novo(), api)
        self.assertEqual(len(self.registros), 2)
        corpo_ok = len(json.dumps(resposta()).encode())
        for r in self.registros:
            self.assertEqual(set(r), CAMPOS_REGISTRO)
            self.assertEqual(r['operacao'], 'productOfferV2')
            self.assertRegex(r['em'], r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$')
            self.assertIsInstance(r['ms'], int)
        self.assertEqual(self.registros[1]['bytes'], corpo_ok)
        self.assertEqual((self.registros[1]['http'], self.registros[1]['codigo']), (200, None))
        assinatura = api.pedidos[1].get_header('Authorization').rsplit('=', 1)[1]
        self.assertNotIn(assinatura, json.dumps(self.registros))

    def test_operacao_vem_da_consulta(self):
        self.assertEqual(K.operacao_de('mutation { generateShortLink(input: $i) { shortLink } }'),
                         'generateShortLink')
        self.assertEqual(K.operacao_de('query { __schema { types { name } } }'), '__schema')
        self.assertEqual(K.operacao_de('sem chave'), '?')


class TestIsolamento(Base):
    def test_nao_abre_nem_cria_o_achadinhos_db(self):
        self.pedir(self.novo(), ApiFalsa())
        self.assertEqual(os.path.dirname(S.DB), TMP)
        self.assertFalse(os.path.exists(os.environ['ACHADINHOS_DB']))
        self.assertFalse(os.path.exists(os.path.join(RAIZ, 'tools', 'garimpo_feminino', 'achadinhos.db')))


if __name__ == '__main__':
    unittest.main()
