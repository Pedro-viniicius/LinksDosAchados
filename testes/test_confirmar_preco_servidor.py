#!/usr/bin/env python3
"""Testes da rota POST /api/v1/amazon/<ASIN>/confirmar-preco e do FreioReleitura (plano "Rodar sozinho ·
Entrega 1" do Achadinho Turbo, etapa A2: CA1.1 e CA1.2).

Uso:  python3 testes/test_confirmar_preco_servidor.py -v

Três camadas, como no test_api_ofertas_servidor.py:
- TestFreio: a classe FreioReleitura com relógio falso (ocupado, intervalo, teto, pausa e rodada).
- TestRotaEmProcesso: o Handler real neste processo, com S.API_TOKEN trocado, o relógio do freio falso e o
  OPENER_AMAZON.open falso (devolve uma página montada aqui ou levanta o erro pedido).
- TestRotaPeloServidor: o servidor.py de verdade como subprocesso, banco temporário, porta livre e proxy morto:
  a leitura da Amazon bate em 127.0.0.1:9 e vira falha_rede (nenhum teste abre a Amazon de verdade).
O token é gerado aqui e nunca é impresso (asserções com mensagem fixa). Nenhum teste cria o api_token.txt do
projeto, toca o achadinhos.db real ou o servidor em 8765. Só biblioteca padrão.
"""
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
from datetime import datetime
from http.server import ThreadingHTTPServer
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_servidor as TS  # noqa: E402  (ambiente, porta_livre, RAIZ, DB_REAL, PROXIES_MORTOS)

TMP = tempfile.mkdtemp(prefix='achadinhos-confirmar-')
# Antes do import: o servidor lê ACHADINHOS_DB ao carregar; a rede bate num proxy morto.
os.environ['ACHADINHOS_DB'] = os.path.join(TMP, 'import.db')
os.environ.update(TS.PROXIES_MORTOS)
os.environ.pop('ACHADINHOS_API_TOKEN_ARQUIVO', None)
sys.path.insert(0, TS.RAIZ)
import servidor as S  # noqa: E402

assert os.path.dirname(S.DB) == TMP, 'o teste não pode tocar o banco real'

VAR_TOKEN = 'ACHADINHOS_API_TOKEN_ARQUIVO'
ASIN = 'B0TESTE001'
ASIN_ML = 'B0TESTE002'   # item_id com cara de ASIN, mas de um item do ML
ROTA = f'/api/v1/amazon/{ASIN}/confirmar-preco'
LINK = f'https://www.amazon.com.br/dp/{ASIN}?tag=desejodemen01-20'
ANTIGO = '2026-11-01T08:00:00'
METODOS_NAO_POST = ('GET', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS')
OUTRAS_ROTAS = ('/api/v1/ofertas', '/api/v1/categorias', '/api/v1/nada', '/api/v1')
SEGREDO = 'VALORQUEOCLIENTEMANDOU'
RE_HORA = r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}'


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


def inserir(db, loja='amazon', item_id=ASIN, url=LINK, **campos):
    base = {'loja': loja, 'item_id': item_id, 'cat': 'Perfumes e Perfumaria', 'busca': 'perfume', 'url': url,
            'titulo': 'Perfume Teste 100ml', 'preco': 'R$ 100,00', 'preco_antigo': 'R$ 150,00', 'desconto': '-33%',
            'avaliacao': '4,5 de 5 estrelas', 'num_avaliacoes': '1.234', 'vendas': 'Mais de 50 compras',
            'frete': 'Frete GRÁTIS', 'cupom': '', 'imagem': 'https://m.media-amazon.com/images/I/71t.jpg',
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


class Relogio:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


# ------------------------------------------------------------------ unidade: o freio
class TestFreio(unittest.TestCase):
    """FreioReleitura: 1 leitura por vez, 3 s entre inícios, 60 por hora (janela deslizante), 15 min de pausa
    depois de um `bloqueado` e nada enquanto a rodada da Amazon estiver no ar."""

    def setUp(self):
        self.relogio = Relogio()
        self.rodada_livre = True
        self.freio = S.FreioReleitura(relogio=self.relogio, rodada_livre=lambda: self.rodada_livre)

    def ler(self, resultado='confirmado', depois=0):
        """Uma leitura inteira: reserva, avança `depois` s e libera. Devolve o que o reservar deu."""
        r = self.freio.reservar()
        if r is None:
            self.relogio.t += depois
            self.freio.liberar(resultado)
        return r

    def test_numeros_do_plano(self):
        self.assertEqual((S.FREIO_INTERVALO_S, S.FREIO_TETO_POR_HORA, S.FREIO_PAUSA_BLOQUEIO_S), (3, 60, 15 * 60))

    def test_ocupado_uma_leitura_por_vez(self):
        self.assertIsNone(self.freio.reservar())
        self.relogio.t += 30
        self.assertEqual(self.freio.reservar(), ('ocupado', 3))
        self.freio.liberar('confirmado')
        self.assertIsNone(self.freio.reservar())

    def test_intervalo_de_3_s_entre_inicios(self):
        self.assertIsNone(self.ler())
        self.assertEqual(self.freio.reservar(), ('intervalo', 3))
        self.relogio.t += 2.5
        self.assertEqual(self.freio.reservar(), ('intervalo', 1))
        self.relogio.t += 0.5
        self.assertIsNone(self.freio.reservar())

    def test_intervalo_conta_do_inicio_da_leitura(self):
        self.assertIsNone(self.ler(depois=5))   # leitura de 5 s: a próxima já pode
        self.assertIsNone(self.freio.reservar())

    def test_teto_de_60_por_hora_em_janela_deslizante(self):
        inicio = self.relogio.t
        self.assertIsNone(self.ler())   # a primeira, sozinha; as outras 59, 1000 s depois
        self.relogio.t = inicio + 1000
        for i in range(59):
            self.assertIsNone(self.ler(), i)
            self.relogio.t += 3
        r = self.freio.reservar()
        self.assertEqual(r, ('teto', int(inicio + 3600 - self.relogio.t)))
        self.relogio.t = inicio + 3600 - 0.5
        self.assertEqual(self.freio.reservar(), ('teto', 1))
        self.relogio.t = inicio + 3600   # a primeira saiu da janela: abre uma vaga
        self.assertIsNone(self.ler())
        self.relogio.t += 3
        r = self.freio.reservar()   # as 59 de inicio+1000 ainda estão na janela
        self.assertEqual(r, ('teto', 997))   # a mais velha (inicio+1000) sai em inicio+4600

    def test_pausa_de_15_min_depois_de_bloqueado(self):
        self.assertIsNone(self.ler('bloqueado', depois=2))
        fim = self.relogio.t + 900
        self.relogio.t += 3
        self.assertEqual(self.freio.reservar(), ('pausa', 897))
        self.relogio.t = fim - 0.2
        self.assertEqual(self.freio.reservar(), ('pausa', 1))
        self.relogio.t = fim
        self.assertIsNone(self.freio.reservar())

    def test_outros_resultados_nao_pausam(self):
        for resultado in ('confirmado', 'sem_preco', 'outro_produto', 'falha_rede', None):
            with self.subTest(resultado=resultado):
                self.assertIsNone(self.ler(resultado))
                self.relogio.t += 3

    def test_rodada_em_andamento_recusa_sem_gastar_vaga(self):
        self.rodada_livre = False
        self.assertEqual(self.freio.reservar(), ('rodada', S.FREIO_ESPERA_RODADA_S))
        self.rodada_livre = True
        self.assertIsNone(self.freio.reservar())   # sem "intervalo": a recusa não contou como leitura

    def test_recusa_nao_conta_como_leitura(self):
        self.assertIsNone(self.ler())
        for _ in range(100):
            self.freio.reservar()   # intervalo: recusado
        self.relogio.t += 3
        self.assertIsNone(self.freio.reservar())

    def test_rodada_padrao_usa_a_trava_da_amazon_e_a_solta(self):
        freio = S.FreioReleitura(relogio=self.relogio)
        with S.travar_rodada('amazon'):
            self.assertEqual(freio.reservar(), ('rodada', S.FREIO_ESPERA_RODADA_S))
        self.assertIsNone(freio.reservar())
        # a reserva não segura a trava: a rodada da Amazon consegue entrar durante a leitura
        with S.travar_rodada('amazon'):
            pass
        freio.liberar('confirmado')

    def test_rodada_de_outra_loja_nao_freia(self):
        freio = S.FreioReleitura(relogio=self.relogio)
        with S.travar_rodada('ml'), S.travar_rodada('shopee'):
            self.assertIsNone(freio.reservar())

    def test_reservas_simultaneas_so_uma_passa(self):
        freio = S.FreioReleitura(rodada_livre=lambda: True)
        barreira = threading.Barrier(8)
        saidas = []

        def tenta():
            barreira.wait()
            saidas.append(freio.reservar())
        fios = [threading.Thread(target=tenta) for _ in range(8)]
        for f in fios:
            f.start()
        for f in fios:
            f.join()
        self.assertEqual(saidas.count(None), 1)


# ------------------------------------------------------------------ Handler neste processo
def pagina_html(titulo='Perfume Teste 100ml', preco='R$ 89,90', antigo='R$ 119,90', desconto='-25%'):
    return (f'<span id="productTitle"> {titulo} </span>'
            f'<div id="corePrice_feature_div"><span class="a-offscreen">{preco}</span></div>'
            f'<span class="basisPrice"><span class="a-offscreen">{antigo}</span></span>'
            f'<span class="a-size-large savingsPercentage">{desconto}</span>')


class OpenerFalso:
    """OPENER_AMAZON.open falso: `modo` decide a página ou o erro. Guarda (url, timeout) de cada chamada."""

    def __init__(self):
        self.modo = 'confirmado'
        self.chamadas = []
        self.durante = None   # chamado no meio da leitura (para conferir trava e concorrência)

    def __call__(self, req, timeout=None):
        self.chamadas.append((req.full_url, timeout))
        if self.durante:
            self.durante()
        url, h = req.full_url, pagina_html()
        if self.modo == 'sem_preco':
            h = pagina_html(preco='')
        elif self.modo == 'outro_produto':
            url = url.replace(ASIN, 'B0OUTRO999')
        elif self.modo == 'bloqueado':
            h = '<html><form action="/errors/validateCaptcha">Digite os caracteres (captcha)</form></html>'
        elif self.modo == 'falha_rede':
            raise urllib.error.URLError(ConnectionRefusedError(SEGREDO))
        elif self.modo == 'http_503':
            raise urllib.error.HTTPError(url, 503, SEGREDO, {}, io.BytesIO(SEGREDO.encode()))
        resposta = mock.MagicMock()
        resposta.__enter__.return_value = resposta
        resposta.geturl.return_value = url
        resposta.read.return_value = h.encode()
        return resposta


class TestRotaEmProcesso(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if os.path.realpath(S.DB) == TS.DB_REAL:
            raise RuntimeError('o teste tentou usar o banco real')
        cls.token = secrets.token_urlsafe(32)
        porta = TS.porta_livre()
        for alvo, nome, valor in ((S, 'API_TOKEN', cls.token), (S, 'HOSTS_LOCAIS', (f'localhost:{porta}',))):
            p = mock.patch.object(alvo, nome, valor)
            p.start()
            cls.addClassCleanup(p.stop)
        cls.srv = ThreadingHTTPServer(('127.0.0.1', porta), S.Handler)
        cls.porta = porta
        cls.addClassCleanup(cls.srv.server_close)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.addClassCleanup(cls.srv.shutdown)

    def setUp(self):
        for p in (S.DB, S.DB + '-wal', S.DB + '-shm'):
            if os.path.exists(p):
                os.remove(p)
        S.criar_banco()
        inserir(S.DB)
        inserir(S.DB, loja='ml', item_id=ASIN_ML, url='https://meli.la/1AbC', posicao=2)
        self.relogio = Relogio()
        self.opener = OpenerFalso()
        for alvo, nome, valor in ((S, 'FREIO_RELEITURA', S.FreioReleitura(relogio=self.relogio)),
                                  (S.OPENER_AMAZON, 'open', self.opener)):
            p = mock.patch.object(alvo, nome, valor)
            p.start()
            self.addCleanup(p.stop)

    def pedir(self, caminho=ROTA, metodo='POST', headers=None, corpo=None, token=True):
        """Devolve (status, cabeçalhos, corpo JSON ou None, log do servidor durante o pedido)."""
        h = {'Host': f'localhost:{self.porta}'}
        if token:
            h['Authorization'] = f'Bearer {self.token}'
        h.update(headers or {})
        log = io.StringIO()
        with mock.patch('sys.stderr', log):
            con = http.client.HTTPConnection('127.0.0.1', self.porta, timeout=10)
            try:
                con.request(metodo, caminho, body=corpo, headers=h)
                r = con.getresponse()
                dados = r.read()
            finally:
                con.close()
            time.sleep(0.05)
        return r.status, r.headers, (json.loads(dados) if dados else None), log.getvalue()

    def proxima(self, segundos=3600):
        """Avança o relógio do freio além de intervalo, teto e pausa."""
        self.relogio.t += segundos

    def test_ca1_1_cinco_resultados_pelo_http(self):
        esperados = {'sem_preco': 'sem_preco', 'outro_produto': 'outro_produto', 'bloqueado': 'bloqueado',
                     'http_503': 'bloqueado', 'falha_rede': 'falha_rede'}
        antes = linhas(S.DB)
        for modo, resultado in esperados.items():
            with self.subTest(modo=modo):
                self.opener.modo = modo
                st, _, j, _ = self.pedir()
                self.assertEqual((st, j), (200, {'versao': 1, 'resultado': resultado}))
                self.assertEqual(linhas(S.DB), antes)   # CA1.2: falha não grava nada
                self.proxima()
        self.opener.modo = 'confirmado'
        st, _, j, _ = self.pedir()
        self.assertEqual(st, 200, j)
        self.assertRegex(j.pop('preco_em'), RE_HORA)
        self.assertEqual(j, {'versao': 1, 'resultado': 'confirmado', 'preco': 89.9, 'preco_antigo': 119.9,
                             'desconto_pct': 25})
        con = sqlite3.connect(S.DB)
        try:
            preco, preco_em, url = con.execute("SELECT preco, preco_em, url FROM items WHERE item_id=?",
                                               (ASIN,)).fetchone()
        finally:
            con.close()
        self.assertEqual((preco, url), ('R$ 89,90', LINK))
        self.assertNotEqual(preco_em, ANTIGO)
        self.assertEqual([c for c in self.opener.chamadas],
                         [(f'https://www.amazon.com.br/dp/{ASIN}', 10)] * (len(esperados) + 1))

    def test_resposta_nunca_traz_html_nem_mensagem_do_erro(self):
        for modo in ('falha_rede', 'http_503', 'bloqueado'):
            with self.subTest(modo=modo):
                self.opener.modo = modo
                st, hd, j, log = self.pedir()
                self.assertEqual(st, 200)
                self.assertNotIn(SEGREDO, json.dumps(j) + str(hd) + log)
                self.assertNotIn('captcha', json.dumps(j))
                self.proxima()

    def test_ca1_1_freio_429_com_retry_after(self):
        st, _, j, _ = self.pedir()
        self.assertEqual(st, 200, j)
        st, hd, j, _ = self.pedir()
        self.assertEqual((st, j), (429, {'versao': 1, 'resultado': 'freio', 'motivo': 'intervalo', 'tentar_em_s': 3}))
        self.assertEqual(hd.get('Retry-After'), '3')
        self.assertEqual(len(self.opener.chamadas), 1)
        self.relogio.t += 3
        # ocupado: uma leitura em curso segura a segunda
        segunda = {}

        def durante():
            self.opener.durante = None
            segunda['r'] = self.pedir()
        self.opener.durante = durante
        st, _, j, _ = self.pedir()
        self.assertEqual(st, 200, j)
        st, hd, j, _ = segunda['r']
        self.assertEqual((st, j['motivo'], hd.get('Retry-After')), (429, 'ocupado', '3'))
        self.assertEqual(len(self.opener.chamadas), 2)

    def test_freio_teto_pelo_http(self):
        for _ in range(S.FREIO_TETO_POR_HORA):
            st, _, j, _ = self.pedir()
            self.assertEqual(st, 200, j)
            self.relogio.t += 3
        st, hd, j, _ = self.pedir()
        self.assertEqual((st, j['motivo']), (429, 'teto'))
        self.assertEqual(hd.get('Retry-After'), str(j['tentar_em_s']))
        self.assertEqual(len(self.opener.chamadas), S.FREIO_TETO_POR_HORA)

    def test_freio_pausa_15_min_depois_de_bloqueado(self):
        self.opener.modo = 'bloqueado'
        st, _, j, _ = self.pedir()
        self.assertEqual(j['resultado'], 'bloqueado')
        self.opener.modo = 'confirmado'
        self.relogio.t += 899
        st, hd, j, _ = self.pedir()
        self.assertEqual((st, j['motivo'], j['tentar_em_s'], hd.get('Retry-After')), (429, 'pausa', 1, '1'))
        self.assertEqual(len(self.opener.chamadas), 1)
        self.relogio.t += 1
        st, _, j, _ = self.pedir()
        self.assertEqual((st, j['resultado']), (200, 'confirmado'))
        # 429/503 da Amazon também é bloqueio e pausa
        self.relogio.t += 3
        self.opener.modo = 'http_503'
        self.assertEqual(self.pedir()[2]['resultado'], 'bloqueado')
        self.relogio.t += 60
        self.assertEqual(self.pedir()[2]['motivo'], 'pausa')

    def test_freio_rodada_amazon_em_andamento(self):
        with S.travar_rodada('amazon'):
            st, hd, j, _ = self.pedir()
        self.assertEqual((st, j['motivo'], hd.get('Retry-After')),
                         (429, 'rodada', str(S.FREIO_ESPERA_RODADA_S)))
        self.assertEqual(self.opener.chamadas, [])
        # a rota não segura a trava durante a leitura: a rodada pode entrar no meio
        entrou = []

        def rodada_entra():
            with S.travar_rodada('amazon'):
                entrou.append(True)
        self.opener.durante = rodada_entra
        st, _, j, _ = self.pedir()
        self.assertEqual((st, j['resultado'], entrou), (200, 'confirmado', [True]))

    def test_recusas_antes_do_freio_nao_gastam_leitura(self):
        casos = [dict(token=False), dict(headers={'Origin': f'http://localhost:{self.porta}'}),
                 dict(metodo='GET'), dict(corpo=b'{}', headers={'Content-Type': 'application/json'}),
                 dict(caminho='/api/v1/amazon/B0TESTE999/confirmar-preco'),
                 dict(caminho=f'/api/v1/amazon/{ASIN_ML}/confirmar-preco'),
                 dict(caminho='/api/v1/amazon/b0teste001/confirmar-preco')]
        for caso in casos:
            with self.subTest(caso=caso):
                st, _, j, _ = self.pedir(**caso)
                self.assertIn(st, (400, 401, 403, 404, 405), j)
        self.assertEqual(self.opener.chamadas, [])
        st, _, j, _ = self.pedir()   # nenhuma das recusas acima ocupou o freio
        self.assertEqual(st, 200, j)

    def test_api_desligada_da_503_antes_do_401(self):
        with mock.patch.object(S, 'API_TOKEN', None):
            for token in (True, False):
                st, hd, j, _ = self.pedir(token=token)
                self.assertEqual(st, 503, j)
                self.assertIsNone(hd.get('WWW-Authenticate'))
        self.assertEqual(self.opener.chamadas, [])

    def test_erro_interno_vira_500_so_com_o_tipo_e_libera_o_freio(self):
        with mock.patch.object(S, 'confirmar_preco_amazon', side_effect=RuntimeError(SEGREDO)):
            st, _, j, log = self.pedir()
        self.assertEqual((st, j), (500, {'error': 'erro interno na API v1'}))
        self.assertIn('"POST /api/v1/amazon/(asin)/confirmar-preco HTTP/1.1" confirmar preço falhou: RuntimeError', log)
        self.assertNotIn(SEGREDO, log)
        self.assertNotIn(ASIN, log)
        self.relogio.t += 3
        st, _, j, _ = self.pedir()   # não ficou "ocupado"
        self.assertEqual(st, 200, j)

    def test_conexao_da_rota_grava_e_a_das_outras_continua_so_de_leitura(self):
        st, _, j, _ = self.pedir()
        self.assertEqual(j['resultado'], 'confirmado')
        st, _, j, _ = self.pedir('/api/v1/categorias', metodo='GET')
        self.assertEqual(st, 200, j)
        visto = {}

        def espia(con, *a, **kw):
            visto['query_only'] = con.execute('PRAGMA query_only').fetchone()[0]
            return {}
        import api_ofertas
        with mock.patch.object(api_ofertas, 'rota', espia):
            self.pedir('/api/v1/ofertas', metodo='GET')
        self.assertEqual(visto, {'query_only': 1})


# ------------------------------------------------------------------ servidor.py de verdade
class TestRotaPeloServidor(unittest.TestCase):
    """servidor.py como subprocesso, com o token num arquivo temporário e a rede num proxy morto."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix='achadinhos-confirmar-srv-')
        cls.addClassCleanup(shutil.rmtree, cls.dir, ignore_errors=True)
        cls.db = os.path.join(cls.dir, 'teste.db')
        cls.arquivo_token = os.path.join(cls.dir, 'api_token.txt')
        cls.token = secrets.token_urlsafe(32)
        fd = os.open(cls.arquivo_token, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'wb') as f:
            f.write(cls.token.encode() + b'\n')
        cls.porta = TS.porta_livre()
        cls.log_err = open(os.path.join(cls.dir, 'stderr.log'), 'wb')
        cls.addClassCleanup(cls.log_err.close)
        env = TS.ambiente(cls.db, cls.porta)
        env.update({VAR_TOKEN: cls.arquivo_token, 'ACHADINHOS_DISPARO': '0'})
        cls.proc = subprocess.Popen([sys.executable, '-u', 'servidor.py'], cwd=TS.RAIZ, env=env,
                                    stdout=subprocess.PIPE, stderr=cls.log_err)
        cls.addClassCleanup(cls.parar)
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
        inserir(cls.db)
        inserir(cls.db, loja='ml', item_id=ASIN_ML, url='https://meli.la/1AbC', posicao=2)

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

    def auth(self, **extra):
        return {'Authorization': f'Bearer {self.token}', **extra}

    def pedir(self, caminho=ROTA, metodo='POST', headers=None, corpo=None, host=None):
        h = {'Host': host or f'localhost:{self.porta}'}
        h.update(headers or {})
        con = http.client.HTTPConnection('127.0.0.1', self.porta, timeout=30)
        try:
            con.request(metodo, caminho, body=corpo, headers=h)
            r = con.getresponse()
            dados = r.read()
        finally:
            con.close()
        self.assertFalse([k for k in r.headers.keys() if k.lower().startswith('access-control-')],
                         f'{metodo} {caminho} respondeu com cabeçalho de CORS')
        return r.status, r.headers, (json.loads(dados) if dados else None)

    def saida(self):
        self.log_err.flush()
        time.sleep(0.1)
        with open(os.path.join(self.dir, 'stderr.log'), encoding='utf-8', errors='replace') as f:
            return f.read()

    def test_ca1_1_sem_token_401_navegador_403_get_405_outra_rota_post_405(self):
        antes = linhas(self.db)
        st, hd, j = self.pedir()
        self.assertEqual((st, hd.get('WWW-Authenticate')), (401, 'Bearer'), j)
        st, _, j = self.pedir(headers={'Authorization': 'Bearer ' + 'x' * 43})
        self.assertEqual(st, 401, j)
        for extra in ({'Origin': f'http://localhost:{self.porta}'}, {'Origin': 'https://evil.example'},
                      {'Sec-Fetch-Site': 'same-origin'}, {'Sec-Fetch-Site': 'cross-site'}):
            with self.subTest(navegador=extra):
                st, hd, j = self.pedir(headers=self.auth(**extra))
                self.assertEqual(st, 403, j)
                self.assertIsNone(hd.get('WWW-Authenticate'))
        st, _, j = self.pedir(headers=self.auth(), host='evil.example')
        self.assertEqual((st, j), (403, {'error': 'host não permitido'}))
        for metodo in METODOS_NAO_POST:
            with self.subTest(metodo=metodo):
                st, hd, _ = self.pedir(metodo=metodo)
                self.assertEqual(st, 401)
                st, hd, _ = self.pedir(metodo=metodo, headers=self.auth())
                self.assertEqual((st, hd.get('Allow')), (405, 'POST'))
        for caminho in OUTRAS_ROTAS:
            with self.subTest(caminho=caminho):
                st, hd, _ = self.pedir(caminho, headers=self.auth())
                self.assertEqual((st, hd.get('Allow')), (405, 'GET'))
        self.assertEqual(linhas(self.db), antes)

    def test_ca1_1_item_inexistente_ou_de_outra_loja_404(self):
        antes = linhas(self.db)
        for asin in ('B0TESTE999', ASIN_ML):
            with self.subTest(asin=asin):
                st, _, j = self.pedir(f'/api/v1/amazon/{asin}/confirmar-preco', headers=self.auth())
                self.assertEqual((st, j), (404, {'error': 'oferta da Amazon não encontrada'}))
        # ASIN fora do formato (minúsculas, curto, longo, codificado, vazio): rota da v1 que não existe
        for ruim in ('b0teste001', 'B0TESTE00', 'B0TESTE0011', 'B0TESTE00%31', '', 'B0TESTE00 1'.replace(' ', '%20')):
            with self.subTest(ruim=ruim):
                st, _, j = self.pedir(f'/api/v1/amazon/{ruim}/confirmar-preco', headers=self.auth())
                self.assertEqual((st, j), (404, {'error': 'rota não encontrada'}))
        # outro formato de caminho é outra rota da v1: o POST continua 405
        for caminho in (f'/api/v1/amazon/{ASIN}/x/confirmar-preco', f'/api/v1/amazon/{ASIN}',
                        f'/api/v1/amazon/{ASIN}/confirmar-preco/', f'/api/v1/amazon/{ASIN}/confirmar-preco2'):
            with self.subTest(caminho=caminho):
                st, hd, j = self.pedir(caminho, headers=self.auth())
                self.assertEqual((st, hd.get('Allow')), (405, 'GET'), j)
        self.assertEqual(linhas(self.db), antes)

    def test_ca1_1_corpo_400(self):
        antes = linhas(self.db)
        casos = [({'Content-Type': 'application/json'}, b'{}'), ({}, b'x'),
                 ({'Content-Type': 'application/json', 'Transfer-Encoding': 'chunked'}, None)]
        for extra, corpo in casos:
            with self.subTest(extra=extra, corpo=corpo):
                st, _, j = self.pedir(headers=self.auth(**extra), corpo=corpo)
                self.assertEqual((st, j), (400, {'error': 'esta rota não aceita corpo'}))
        # Content-Length: 0 é corpo vazio: passa da guarda (aqui, até o 404 do item que não existe)
        st, _, j = self.pedir('/api/v1/amazon/B0TESTE999/confirmar-preco',
                              headers=self.auth(**{'Content-Length': '0'}))
        self.assertEqual(st, 404, j)
        self.assertEqual(linhas(self.db), antes)

    def test_ca1_1_falha_de_rede_pelo_http(self):
        """A leitura bate no proxy morto: falha_rede, e nada muda no item (CA1.2)."""
        antes = linhas(self.db)
        st, hd, j = self.pedir(headers=self.auth())
        if st == 429:   # outro teste desta classe leu há menos de 3 s
            time.sleep(int(hd.get('Retry-After')))
            st, hd, j = self.pedir(headers=self.auth())
        self.assertEqual((st, j), (200, {'versao': 1, 'resultado': 'falha_rede'}))
        self.assertEqual(linhas(self.db), antes)

    def test_log_sem_token_nem_asin(self):
        self.pedir(headers=self.auth())
        self.pedir(f'{ROTA}?token={self.token}', headers=self.auth())
        self.pedir('/api/v1/amazon/B0TESTE999/confirmar-preco', headers=self.auth())
        self.pedir(f'/api/v1/amazon/{self.token[:10]}/confirmar-preco', headers=self.auth())
        self.pedir(f'/api/v1/amazon/{self.token}/confirmar-preco', headers=self.auth())
        self.pedir(metodo='GET', headers=self.auth())
        saida = self.saida()
        self.assertFalse(self.token in saida, 'o token apareceu no log do servidor')
        self.assertFalse(self.token[:10] in saida, 'o pedaço do token no lugar do ASIN apareceu no log')
        for asin in (ASIN, 'B0TESTE999'):
            self.assertNotIn(asin, saida)
        self.assertRegex(saida, r'"POST /api/v1/amazon/\(asin\)/confirmar-preco HTTP/1\.1" (200|429)')
        self.assertIn('"POST /api/v1/amazon/(asin)/confirmar-preco?(omitida) HTTP/1.1"', saida)
        self.assertIn('"POST /api/v1/amazon/(asin)/confirmar-preco HTTP/1.1" 404', saida)
        self.assertIn('"GET /api/v1/amazon/(asin)/confirmar-preco HTTP/1.1" 405', saida)


class TestLinhaParaLog(unittest.TestCase):

    def test_rota_de_confirmacao_sai_sem_o_asin(self):
        casos = {
            f'POST {ROTA} HTTP/1.1': 'POST /api/v1/amazon/(asin)/confirmar-preco HTTP/1.1',
            f'POST {ROTA}?x=segredo HTTP/1.1': 'POST /api/v1/amazon/(asin)/confirmar-preco?(omitida) HTTP/1.1',
            'POST /api/v1/amazon/segredo/confirmar-preco HTTP/1.1':
                'POST /api/v1/amazon/(asin)/confirmar-preco HTTP/1.1',
            'POST /api/v1/amazon/segredo HTTP/1.1': 'POST /api/v1/(outra rota) HTTP/1.1',
            'POST /api/v1/amazon/a/b/confirmar-preco HTTP/1.1': 'POST /api/v1/(outra rota) HTTP/1.1',
        }
        for linha, esperado in casos.items():
            with self.subTest(linha=linha):
                self.assertEqual(S.linha_v1_para_log(linha), esperado)


if __name__ == '__main__':
    unittest.main()
