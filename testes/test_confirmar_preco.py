#!/usr/bin/env python3
"""Testes do confirmar_preco_amazon do servidor.py (plano "Rodar sozinho · Entrega 1" do Achadinho Turbo,
etapa A1: CA1.1 e CA1.2).

Uso:  python3 testes/test_confirmar_preco.py -v

ACHADINHOS_DB aponta para um diretório temporário antes do import e qualquer saída acidental para a rede
bate num proxy morto. A página da Amazon é sempre falsa: o `buscar` é injetado (dict no formato do
buscar_produto_amazon ou a exceção que ele levantaria) e o OPENER_AMAZON.open reprova se for chamado,
salvo nos testes que conferem a URL pedida e os limites da leitura (prazo total e teto de bytes), onde ele
também é falso. Nenhum teste abre a Amazon, o
achadinhos.db real ou o servidor em 8765. Só biblioteca padrão.
"""
import contextlib
import http.client
import io
import itertools
import os
import shutil
import socket
import sqlite3
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
import urllib.response
from unittest import mock

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix='teste-confirmar-preco-')
os.environ.update({v: 'http://127.0.0.1:9' for v in ('http_proxy', 'https_proxy', 'ftp_proxy')})
os.environ['no_proxy'] = ''
os.environ['ACHADINHOS_DB'] = os.path.join(TMP, 'achadinhos.db')
sys.path.insert(0, RAIZ)

import servidor as S  # noqa: E402

assert os.path.dirname(S.DB) == TMP, 'o teste não pode tocar o banco real'

ASIN = 'B0TESTE001'
OUTRO = 'B0TESTE999'
LINK = f'https://www.amazon.com.br/dp/{ASIN}?tag=desejodemen01-20'
ANTIGO = '2026-11-01T08:00:00'
AGORA = '2026-11-11T10:30:00'
FALHAS = ('sem_preco', 'outro_produto', 'bloqueado', 'falha_rede')


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


def rede_proibida(*a, **kw):
    raise AssertionError('teste tentou acessar a rede')


def pagina(asin=ASIN, titulo='Perfume Teste 100ml (novo)', preco='R$ 89,90', preco_antigo='R$ 119,90',
           desconto='-25%', captcha=False, url_final=None, **outros):
    """Retorno do buscar_produto_amazon de uma página lida."""
    d = {'url_final': url_final or f'https://www.amazon.com.br/dp/{asin}' if asin else 'https://www.amazon.com.br/',
         'asin': asin, 'captcha': captcha, 'titulo': titulo, 'preco': preco, 'preco_antigo': preco_antigo,
         'desconto': desconto, 'avaliacao': '4,9 de 5 estrelas', 'num_avaliacoes': '9.999',
         'vendas': 'Mais de 5 mil compras', 'cupom': 'Cupom de 10% da página', 'frete': '',
         'imagem': 'https://m.media-amazon.com/images/I/outra.jpg'}
    d.update(outros)
    return d


def erro_http(codigo):
    return urllib.error.HTTPError(f'https://www.amazon.com.br/dp/{ASIN}', codigo, 'erro', {}, io.BytesIO(b''))


class Buscar:
    """buscar falso: devolve `resultado` (dict) ou o levanta (exceção) e guarda cada chamada."""

    def __init__(self, resultado, antes=None):
        self.resultado, self.antes, self.chamadas = resultado, antes, []

    def __call__(self, url, timeout=None):
        self.chamadas.append((url, timeout))
        if self.antes:
            self.antes()
        if isinstance(self.resultado, BaseException):
            raise self.resultado
        return dict(self.resultado)


# Um byte a cada 20 ms por 3 s: com prazo de 0,3 s, para o servidor é a página que nunca termina. É finito só
# para que um servidor sem o prazo falhe o teste em vez de travá-lo.
def gotejando():
    return itertools.repeat(b'x', 150)


class RespostaEmBlocos:
    """Resposta do OPENER_AMAZON.open falsa que só se lê em blocos (read1): devolve os `blocos` (lista ou
    iterador), esperando `pausa` s antes de cada um, e b'' quando acabam. read() reprova: a releitura nunca lê a
    página de uma vez. Guarda quantos blocos foram lidos, o tamanho pedido e se a resposta foi fechada."""

    def __init__(self, blocos, pausa=0.0, url=f'https://www.amazon.com.br/dp/{ASIN}'):
        self.blocos, self.pausa, self.url = iter(blocos), pausa, url
        self.lidos, self.pedidos, self.fechada = 0, [], False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.fechada = True

    def geturl(self):
        return self.url

    def read1(self, n=-1):
        self.pedidos.append(n)
        if self.pausa:
            time.sleep(self.pausa)
        bloco = next(self.blocos, b'')
        if bloco:
            self.lidos += 1
        return bloco

    def read(self, *a):
        raise AssertionError('a releitura leu a página de uma vez')


class Base(unittest.TestCase):
    def setUp(self):
        for p in (S.DB, S.DB + '-wal', S.DB + '-shm'):
            if os.path.exists(p):
                os.remove(p)
        p = mock.patch.object(S.OPENER_AMAZON, 'open', rede_proibida)
        p.start()
        self.addCleanup(p.stop)
        S.criar_banco()
        self.inserir()

    def inserir(self, loja='amazon', item_id=ASIN, url=LINK, preco='R$ 100,00', preco_antigo='R$ 150,00',
                desconto='-33%', preco_em=ANTIGO, **outros):
        base = {'loja': loja, 'item_id': item_id, 'cat': 'Perfumes e Perfumaria', 'busca': 'perfume', 'url': url,
                'titulo': 'Perfume Teste 100ml', 'preco': preco, 'preco_antigo': preco_antigo, 'desconto': desconto,
                'avaliacao': '4,5 de 5 estrelas', 'num_avaliacoes': '1.234', 'vendas': 'Mais de 50 compras',
                'frete': 'Frete GRÁTIS', 'cupom': 'Cupom de 5%', 'imagem': 'https://m.media-amazon.com/images/I/71t.jpg',
                'tem_dados': 1, 'posicao': 1, 'criado_em': ANTIGO, 'atualizado_em': ANTIGO, 'preco_em': preco_em}
        base.update(outros)
        con = sqlite3.connect(S.DB)
        try:
            con.execute(f"INSERT INTO items ({','.join(base)}) VALUES ({','.join('?' * len(base))})",
                        list(base.values()))
            con.commit()
        finally:
            con.close()

    def linha(self, loja='amazon', item_id=ASIN):
        con = sqlite3.connect(S.DB)
        con.row_factory = sqlite3.Row
        try:
            r = con.execute('SELECT * FROM items WHERE loja=? AND item_id=?', (loja, item_id)).fetchone()
            return dict(r) if r else None
        finally:
            con.close()

    def todas(self):
        con = sqlite3.connect(S.DB)
        try:
            return con.execute('SELECT * FROM items ORDER BY id').fetchall()
        finally:
            con.close()

    def confirmar(self, buscar, asin=ASIN):
        con = S.conectar()
        try:
            return S.confirmar_preco_amazon(con, asin, buscar=buscar, agora=lambda: AGORA)
        finally:
            con.close()


class TestResultados(Base):
    """CA1.1: os cinco resultados, classificados como no atualizar_precos.py, e o preco_em só com preço legível."""

    def test_ca1_1_confirmado_grava_e_carimba_preco_em(self):
        r = self.confirmar(Buscar(pagina()))
        self.assertEqual(r, {'resultado': 'confirmado', 'preco': 89.9, 'preco_antigo': 119.9, 'desconto_pct': 25,
                             'preco_em': AGORA})
        linha = self.linha()
        self.assertEqual((linha['preco'], linha['preco_antigo'], linha['desconto']), ('R$ 89,90', 'R$ 119,90', '-25%'))
        self.assertEqual((linha['preco_em'], linha['atualizado_em']), (AGORA, AGORA))

    def test_confirmado_sem_preco_antigo_limpa_o_antigo_e_devolve_null(self):
        r = self.confirmar(Buscar(pagina(preco_antigo='', desconto='')))
        self.assertEqual(r, {'resultado': 'confirmado', 'preco': 89.9, 'preco_antigo': None, 'desconto_pct': None,
                             'preco_em': AGORA})
        linha = self.linha()
        self.assertEqual((linha['preco'], linha['preco_antigo'], linha['desconto']), ('R$ 89,90', '', ''))

    def test_confirmado_desconto_calculado_quando_a_pagina_nao_traz(self):
        r = self.confirmar(Buscar(pagina(preco='R$ 75,00', preco_antigo='R$ 100,00', desconto='')))
        self.assertEqual((r['preco'], r['preco_antigo'], r['desconto_pct']), (75.0, 100.0, 25))

    def test_confirmado_aplica_sanear_precos(self):
        # antigo de 5x o preço ou mais é o seletor pegando outra coisa: preco_antigo e desconto zerados
        r = self.confirmar(Buscar(pagina(preco='R$ 10,00', preco_antigo='R$ 50,00', desconto='-80%')))
        self.assertEqual((r['preco'], r['preco_antigo'], r['desconto_pct']), (10.0, None, None))
        linha = self.linha()
        self.assertEqual((linha['preco'], linha['preco_antigo'], linha['desconto']), ('R$ 10,00', '', ''))
        self.assertEqual(linha['preco_em'], AGORA)

    def test_confirmado_antigo_menor_ou_igual_ao_preco_sai_null(self):
        """Como na oferta da v1: preco_antigo só sai quando é maior que o preço."""
        for antigo in ('R$ 50,00', 'R$ 89,90'):
            with self.subTest(antigo=antigo):
                r = self.confirmar(Buscar(pagina(preco_antigo=antigo, desconto='')))
                self.assertEqual((r['preco'], r['preco_antigo'], r['desconto_pct']), (89.9, None, None))

    def test_confirmado_preco_com_milhar(self):
        r = self.confirmar(Buscar(pagina(preco='R$ 1.299,90', preco_antigo='R$ 1.599,00', desconto='-19%')))
        self.assertEqual((r['preco'], r['preco_antigo'], r['desconto_pct']), (1299.9, 1599.0, 19))

    def test_ca1_1_sem_preco(self):
        casos = {'preço vazio': Buscar(pagina(preco='')),
                 'preço ilegível': Buscar(pagina(preco='R$ 10 - R$ 20')),
                 'preço zero': Buscar(pagina(preco='R$ 0,00')),
                 'HTTP 404': Buscar(erro_http(404)),
                 'HTTP 410': Buscar(erro_http(410))}
        for nome, buscar in casos.items():
            with self.subTest(nome):
                self.assertEqual(self.confirmar(buscar), {'resultado': 'sem_preco'})

    def test_ca1_1_outro_asin_e_redirect_fora_dao_outro_produto(self):
        casos = {'outro ASIN': Buscar(pagina(asin=OUTRO)),
                 'outro ASIN sem título': Buscar(pagina(asin=OUTRO, titulo='')),
                 'redirect para fora': Buscar(S.URLRecusada('só links https da Amazon'))}
        for nome, buscar in casos.items():
            with self.subTest(nome):
                self.assertEqual(self.confirmar(buscar), {'resultado': 'outro_produto'})

    def test_ca1_1_captcha_429_503_sem_titulo_dao_bloqueado(self):
        casos = {'captcha': Buscar(pagina(captcha=True, titulo='', preco='')),
                 'captcha com outro ASIN': Buscar(pagina(asin=OUTRO, captcha=True)),
                 'HTTP 429': Buscar(erro_http(429)),
                 'HTTP 503': Buscar(erro_http(503)),
                 'sem título': Buscar(pagina(titulo='')),
                 'sem ASIN': Buscar(pagina(asin='')),
                 'página vazia': Buscar({})}
        for nome, buscar in casos.items():
            with self.subTest(nome):
                self.assertEqual(self.confirmar(buscar), {'resultado': 'bloqueado'})

    def test_ca1_1_erro_de_rede_da_falha_rede(self):
        casos = {'URLError': urllib.error.URLError('recusada'),
                 'URLError de timeout': urllib.error.URLError(TimeoutError('timed out')),
                 'TimeoutError': TimeoutError('timed out'),
                 'socket.timeout': socket.timeout('timed out'),
                 'ConnectionResetError': ConnectionResetError(),
                 'OSError': OSError('rede'),
                 'resposta HTTP quebrada': http.client.IncompleteRead(b''),
                 'HTTP 500': erro_http(500),
                 'HTTP 403': erro_http(403),
                 'HTTP 502': erro_http(502)}
        for nome, erro in casos.items():
            with self.subTest(nome):
                self.assertEqual(self.confirmar(Buscar(erro)), {'resultado': 'falha_rede'})

    def test_erro_http_e_fechado(self):
        for codigo in (404, 429, 500):
            with self.subTest(codigo=codigo):
                e = erro_http(codigo)
                self.confirmar(Buscar(e))
                self.assertTrue(e.fp is None or e.fp.closed)

    def test_ca1_1_le_dp_sem_tag(self):
        buscar = Buscar(pagina())
        self.confirmar(buscar)
        self.assertEqual(buscar.chamadas, [(f'https://www.amazon.com.br/dp/{ASIN}', S.PRAZO_OPERACAO_RELEITURA_S)])
        # S1: 8 s para a leitura inteira + uma operação de 4 s que começou antes do prazo = 12 s < 15 s do Turbo
        self.assertEqual((S.PRAZO_RELEITURA_S, S.PRAZO_OPERACAO_RELEITURA_S, S.TETO_RELEITURA_BYTES),
                         (8, 4, 4 * 1024 * 1024))
        self.assertLess(S.PRAZO_RELEITURA_S + S.PRAZO_OPERACAO_RELEITURA_S, 15)

    def test_ca1_1_le_dp_sem_tag_pelo_opener_de_verdade(self):
        """O padrão do `buscar` é o buscar_releitura_amazon: a URL sem tag e os 4 s por operação chegam ao opener,
        e a página é lida em blocos (read1), nunca de uma vez."""
        resposta = RespostaEmBlocos([('<span id="productTitle"> Perfume </span><div id="corePrice_feature_div">'
                                      '<span class="a-offscreen">R$ 89,90</span></div>').encode()])
        with mock.patch.object(S.OPENER_AMAZON, 'open', return_value=resposta) as aberto:
            con = S.conectar()
            try:
                r = S.confirmar_preco_amazon(con, ASIN, agora=lambda: AGORA)
            finally:
                con.close()
        self.assertEqual(r['resultado'], 'confirmado')
        aberto.assert_called_once()
        req = aberto.call_args.args[0]
        self.assertEqual(req.full_url, f'https://www.amazon.com.br/dp/{ASIN}')
        self.assertNotIn('tag=', req.full_url)
        self.assertEqual(aberto.call_args.kwargs.get('timeout'), 4)
        self.assertTrue(resposta.fechada)

    def test_buscar_produto_amazon_mantem_prazo_de_30_s_por_padrao(self):
        """O /api/fetch não muda: 30 s por operação, read() de uma vez, sem prazo total nem teto."""
        resposta = mock.MagicMock()
        resposta.__enter__.return_value = resposta
        resposta.geturl.return_value = f'https://www.amazon.com.br/dp/{ASIN}'
        resposta.read.return_value = b''
        with mock.patch.object(S.OPENER_AMAZON, 'open', return_value=resposta) as aberto:
            S.buscar_produto_amazon(f'https://www.amazon.com.br/dp/{ASIN}')
            S.buscar_produto_amazon(f'https://www.amazon.com.br/dp/{ASIN}', timeout=7)
        self.assertEqual([c.kwargs.get('timeout') for c in aberto.call_args_list], [30, 7])
        resposta.read1.assert_not_called()
        self.assertFalse(any(hasattr(c.args[0], 'prazo_final') for c in aberto.call_args_list))


class TestLimitesDaLeitura(Base):
    """S1/R2: prazo total e teto de bytes da releitura. Página que goteja, que nunca termina ou grande demais vira
    falha_rede, fecha a resposta e não grava nada. O relógio é o de verdade, com prazos curtos."""

    URL = f'https://www.amazon.com.br/dp/{ASIN}'

    def buscar_limitado(self, resposta, prazo_total=None, teto_bytes=None):
        with mock.patch.object(S.OPENER_AMAZON, 'open', return_value=resposta):
            return S.buscar_produto_amazon(self.URL, timeout=4, prazo_total=prazo_total, teto_bytes=teto_bytes)

    def confirmar_pelo_padrao(self, resposta, prazo=None):
        """confirmar_preco_amazon com o buscar padrão (o da rota), o opener falso e, se pedido, outro prazo total."""
        patches = [mock.patch.object(S.OPENER_AMAZON, 'open', return_value=resposta)]
        if prazo is not None:
            patches.append(mock.patch.object(S, 'PRAZO_RELEITURA_S', prazo))
        with contextlib.ExitStack() as pilha:
            for p in patches:
                pilha.enter_context(p)
            con = S.conectar()
            try:
                return S.confirmar_preco_amazon(con, ASIN, agora=lambda: AGORA)
            finally:
                con.close()

    def test_leitor_que_nunca_termina_estoura_o_prazo_total(self):
        resposta = RespostaEmBlocos(gotejando(), pausa=0.02)
        inicio = time.monotonic()
        with self.assertRaises(S.LimiteDaLeitura):
            self.buscar_limitado(resposta, prazo_total=0.3)
        gasto = time.monotonic() - inicio
        self.assertGreaterEqual(gasto, 0.3)
        self.assertLess(gasto, 1.5)
        self.assertTrue(resposta.fechada)
        self.assertGreater(resposta.lidos, 1)   # leu aos poucos e parou pelo relógio, não pelo fim da página

    def test_pagina_acima_do_teto_e_abandonada_logo_depois_do_teto(self):
        resposta = RespostaEmBlocos(itertools.repeat(b'x' * S.BLOCO_LEITURA, 20))
        with self.assertRaises(S.LimiteDaLeitura):
            self.buscar_limitado(resposta, teto_bytes=10 * S.BLOCO_LEITURA)
        self.assertEqual(resposta.lidos, 11)   # o 11º bloco passa do teto: nenhum bloco a mais
        self.assertTrue(resposta.fechada)

    def test_pagina_exatamente_no_teto_passa(self):
        corpo = b'<span id="productTitle">Perfume</span>'
        self.assertEqual(self.buscar_limitado(RespostaEmBlocos([corpo]), teto_bytes=len(corpo))['titulo'], 'Perfume')
        with self.assertRaises(S.LimiteDaLeitura):
            self.buscar_limitado(RespostaEmBlocos([corpo]), teto_bytes=len(corpo) - 1)

    def test_blocos_pedidos_tem_o_tamanho_do_bloco(self):
        resposta = RespostaEmBlocos([b'a', b'b'])
        self.buscar_limitado(resposta, prazo_total=5, teto_bytes=100)
        self.assertEqual(set(resposta.pedidos), {S.BLOCO_LEITURA})

    def test_prazo_total_menor_que_o_timeout_encurta_o_timeout_da_operacao(self):
        with mock.patch.object(S.OPENER_AMAZON, 'open', return_value=RespostaEmBlocos([])) as aberto:
            S.buscar_produto_amazon(self.URL, timeout=4, prazo_total=2.5, teto_bytes=100)
        self.assertEqual(aberto.call_args.kwargs.get('timeout'), 2.5)

    def test_ca1_2_gotejando_pela_rota_da_falha_rede_e_nao_grava(self):
        antes = self.linha()
        r = self.confirmar_pelo_padrao(RespostaEmBlocos(gotejando(), pausa=0.02), prazo=0.3)
        self.assertEqual(r, {'resultado': 'falha_rede'})
        self.assertEqual(self.linha(), antes)   # preço, url e preco_em como estavam

    def test_ca1_2_pagina_acima_do_teto_pela_rota_da_falha_rede_e_nao_grava(self):
        """Uma página de verdade com preço legível, mas acima dos 4 MB: abandonada, nada gravado."""
        pagina_ok = ('<span id="productTitle"> Perfume </span><div id="corePrice_feature_div">'
                     '<span class="a-offscreen">R$ 89,90</span></div>').encode()
        enchimento = b' ' * S.BLOCO_LEITURA
        blocos = [pagina_ok] + [enchimento] * (S.TETO_RELEITURA_BYTES // S.BLOCO_LEITURA)
        antes = self.linha()
        resposta = RespostaEmBlocos(blocos)
        self.assertEqual(self.confirmar_pelo_padrao(resposta), {'resultado': 'falha_rede'})
        self.assertEqual(self.linha(), antes)
        self.assertTrue(resposta.fechada)
        # a mesma página sem o último bloco cabe no teto e confirma
        self.assertEqual(self.confirmar_pelo_padrao(RespostaEmBlocos(blocos[:-1]))['resultado'], 'confirmado')

    def test_redirects_entram_no_prazo_total(self):
        """Com o RedirecionamentoAmazon de verdade: cada salto demora 0,1 s; com 0,25 s de prazo, o redirect que
        chega depois do prazo levanta LimiteDaLeitura, e cada salto abre com no máximo o que resta do prazo."""
        vistos = []

        class HTTPSQueRedireciona(urllib.request.BaseHandler):
            def https_open(self, req):
                vistos.append(req.timeout)
                time.sleep(0.1)
                h = http.client.HTTPMessage()
                h['Location'] = f'https://www.amazon.com.br/salto-{len(vistos)}/dp/{ASIN}'
                r = urllib.response.addinfourl(io.BytesIO(b''), h, req.full_url, 302)
                r.msg = 'Found'
                return r

        op = urllib.request.OpenerDirector()
        for h in (S.RedirecionamentoAmazon(), urllib.request.HTTPErrorProcessor(),
                  urllib.request.HTTPDefaultErrorHandler(), HTTPSQueRedireciona()):
            op.add_handler(h)
        inicio = time.monotonic()
        with mock.patch.object(S, 'OPENER_AMAZON', op), self.assertRaises(S.LimiteDaLeitura):
            S.buscar_produto_amazon(self.URL, timeout=4, prazo_total=0.25, teto_bytes=100)
        self.assertLess(time.monotonic() - inicio, 1)
        # saltos em 0,0, 0,1 e 0,2 s (o redirect do 3º chega em 0,3 s, depois do prazo); sob carga, um a menos
        self.assertIn(len(vistos), (2, 3), vistos)
        self.assertEqual(vistos[0], 0.25)
        self.assertTrue(all(0 < b < a for a, b in zip(vistos, vistos[1:])), vistos)
        self.assertLessEqual(vistos[-1], 0.25 - 0.1 * (len(vistos) - 1) + 0.001)

    def test_redirects_sem_prazo_seguem_como_antes(self):
        """Pedido sem prazo_final (o /api/fetch): o RedirecionamentoAmazon não mexe no timeout."""
        req = urllib.request.Request(self.URL)
        req.timeout = 30
        novo = S.RedirecionamentoAmazon().redirect_request(req, None, 302, 'Found', {},
                                                           f'https://www.amazon.com.br/x/dp/{ASIN}')
        self.assertEqual(req.timeout, 30)
        self.assertFalse(hasattr(novo, 'prazo_final'))


class TestGravacao(Base):
    """CA1.2: falha não grava; o confirmado grava só os campos de preço, sobre a linha relida."""

    def test_ca1_2_falha_nao_altera_preco_url_nem_preco_em(self):
        casos = {'sem_preco': [pagina(preco=''), erro_http(404)],
                 'outro_produto': [pagina(asin=OUTRO), S.URLRecusada('fora')],
                 'bloqueado': [pagina(captcha=True), erro_http(429), erro_http(503), pagina(titulo='')],
                 'falha_rede': [urllib.error.URLError('x'), TimeoutError(), erro_http(500)]}
        self.assertEqual(set(casos), set(FALHAS))
        antes = self.todas()
        for esperado, resultados in casos.items():
            for resultado in resultados:
                with self.subTest(esperado=esperado, resultado=repr(resultado)[:60]):
                    self.assertEqual(self.confirmar(Buscar(resultado)), {'resultado': esperado})
                    self.assertEqual(self.todas(), antes)

    def test_ca1_2_confirmado_nao_troca_url_titulo_cupom(self):
        antes = self.linha()
        self.confirmar(Buscar(pagina()))
        depois = self.linha()
        mudou = {c for c in antes if antes[c] != depois[c]}
        self.assertEqual(mudou, {'preco', 'preco_antigo', 'desconto', 'preco_em', 'atualizado_em'})
        for c in ('url', 'titulo', 'cupom', 'imagem', 'avaliacao', 'num_avaliacoes', 'vendas', 'frete', 'cat',
                  'busca', 'criado_em', 'posicao', 'tem_dados'):
            self.assertEqual(depois[c], antes[c], c)

    def test_rele_a_linha_depois_da_rede(self):
        """O título e o cupom mudados no site durante a leitura ficam; só o preço vem da página."""
        def site_muda():
            con = sqlite3.connect(S.DB)
            con.execute("UPDATE items SET titulo='Título novo do site', cupom='', preco='R$ 1,00' WHERE item_id=?",
                        (ASIN,))
            con.commit()
            con.close()
        self.confirmar(Buscar(pagina(), antes=site_muda))
        linha = self.linha()
        self.assertEqual((linha['titulo'], linha['cupom'], linha['preco']), ('Título novo do site', '', 'R$ 89,90'))

    def test_sanear_usa_a_linha_relida(self):
        """O sanear_precos olha o preço e o antigo que vão ser gravados (os da página)."""
        self.confirmar(Buscar(pagina(preco='R$ 20,00', preco_antigo='R$ 100,00', desconto='-80%')))
        linha = self.linha()
        self.assertEqual((linha['preco'], linha['preco_antigo'], linha['desconto']), ('R$ 20,00', '', ''))

    def test_linha_apagada_durante_a_leitura_da_404_e_nao_insere(self):
        def apaga():
            con = sqlite3.connect(S.DB)
            con.execute('DELETE FROM items WHERE item_id=?', (ASIN,))
            con.commit()
            con.close()
        with self.assertRaises(S.ErroCliente) as ctx:
            self.confirmar(Buscar(pagina(), antes=apaga))
        self.assertEqual((ctx.exception.codigo, ctx.exception.msg), (404, 'oferta da Amazon não encontrada'))
        self.assertEqual(self.todas(), [])

    def test_item_inexistente_ou_de_outra_loja_da_404_sem_ler(self):
        self.inserir(loja='ml', item_id='B0TESTE002', url='https://meli.la/abc')
        for asin in ('B0TESTE002', 'B0TESTE003'):
            with self.subTest(asin=asin):
                buscar = Buscar(pagina(asin=asin))
                antes = self.todas()
                with self.assertRaises(S.ErroCliente) as ctx:
                    self.confirmar(buscar, asin=asin)
                self.assertEqual(ctx.exception.codigo, 404)
                self.assertEqual(buscar.chamadas, [])
                self.assertEqual(self.todas(), antes)

    def test_asin_fora_do_formato_levanta_sem_ler(self):
        for asin in ('b0teste001', 'B0TESTE00', 'B0TESTE0011', 'B0TESTE00/', '', None, 'B0TESTE00\n'):
            with self.subTest(asin=asin):
                buscar = Buscar(pagina())
                with self.assertRaises(ValueError):
                    self.confirmar(buscar, asin=asin)
                self.assertEqual(buscar.chamadas, [])

    def test_nao_toca_item_do_ml_com_o_mesmo_item_id(self):
        self.inserir(loja='ml', item_id=ASIN, url='https://meli.la/xyz', preco='R$ 5,00')
        antes = self.linha(loja='ml')
        self.confirmar(Buscar(pagina()))
        self.assertEqual(self.linha(loja='ml'), antes)

    def test_erro_inesperado_desfaz_a_transacao(self):
        """Falha no meio da gravação: nada fica gravado e a conexão sai sem transação aberta."""
        con = S.conectar()
        try:
            with mock.patch.object(S, 'sanear_precos', side_effect=RuntimeError('quebrou')):
                with self.assertRaises(RuntimeError):
                    S.confirmar_preco_amazon(con, ASIN, buscar=Buscar(pagina()), agora=lambda: AGORA)
            self.assertFalse(con.in_transaction)
        finally:
            con.close()
        self.assertEqual(self.linha()['preco'], 'R$ 100,00')

    def test_leitura_acontece_fora_de_transacao(self):
        """A rede não segura o banco: durante a leitura, outra conexão grava sem esperar."""
        def outro_grava():
            con = sqlite3.connect(S.DB, timeout=0)
            con.execute("UPDATE items SET busca='mudou' WHERE item_id=?", (ASIN,))
            con.commit()
            con.close()
        self.confirmar(Buscar(pagina(), antes=outro_grava))
        self.assertEqual(self.linha()['busca'], 'mudou')


if __name__ == '__main__':
    unittest.main()
