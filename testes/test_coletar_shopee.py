#!/usr/bin/env python3
"""Testes do coletar_shopee.py (docs/produto/planos/perfumaria-tres-lojas.md, etapa E7, CA7).

Uso:  python3 testes/test_coletar_shopee.py -v

ACHADINHOS_DB e ACHADINHOS_FEITOS_SHOPEE apontam para um diretório temporário antes do import (o
coletar_shopee importa o servidor, que lê o banco ao carregar). `OPENER_API.open` (API) e
`OPENER_CONFERENCIA.open` (conferência do dono) são trocados por falsos, e `urllib.request.urlopen` por um
que falha: nenhum teste fala com a Shopee.
Qualquer saída acidental para a rede bate num proxy morto. As credenciais são marcadores falsos.
"""
import contextlib
import hashlib
import http.client
import http.server
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unicodedata
import unittest
import urllib.error
import urllib.request
from unittest import mock

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix='teste-coletar-shopee-')
for v in ('http_proxy', 'https_proxy', 'ftp_proxy'):
    os.environ[v] = 'http://127.0.0.1:9'
os.environ['no_proxy'] = ''
os.environ['ACHADINHOS_DB'] = os.path.join(TMP, 'achadinhos.db')
os.environ['ACHADINHOS_FEITOS_SHOPEE'] = os.path.join(TMP, 'feitos-shopee.txt')
for v in ('ACHADINHOS_SHOPEE_APP_ID', 'ACHADINHOS_SHOPEE_SECRET'):
    os.environ.pop(v, None)
sys.path.insert(0, RAIZ)

import coletar_shopee as C  # noqa: E402
import servidor as S  # noqa: E402

ID_DO_ARQUIVO = C.ID_AFILIADO_SHOPEE   # valor no repositório, antes de qualquer mock
assert os.path.dirname(S.DB) == TMP and os.path.dirname(C.FEITOS) == TMP, 'o teste não pode tocar os dados reais'

SECRET = 'SEGREDO-MARCADOR-7f3a9c'   # procurado em toda saída: nunca pode aparecer
APP_ID = '1800012345'
ID = '18001234567'
CAT = 'Perfumes e Perfumaria'
LINK = 'https://s.shopee.com.br/AbC123xyz'
DESTINO_BOM = f'https://shopee.com.br/product/1/2?utm_source=an_{ID}&utm_medium=affiliates'
DESTINO_RUIM = 'https://shopee.com.br/product/1/2?utm_source=an_99999999999&utm_medium=affiliates'
FOTO = 'https://down-br.img.susercontent.com/file/br-11134207-abc'
ENV = {'ACHADINHOS_SHOPEE_APP_ID': APP_ID, 'ACHADINHOS_SHOPEE_SECRET': SECRET}


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


def no(**k):
    base = {'itemId': 22334455667, 'shopId': 112233, 'productName': 'Perfume Floral 100ml',
            'priceMin': '1234.5', 'priceDiscountRate': 20, 'ratingStar': '4.8', 'sales': 1234,
            'imageUrl': FOTO, 'offerLink': LINK}
    base.update(k)
    return base


def resposta(nos):
    return {'data': {'productOfferV2': {'nodes': nos}}}


def erro(codigo):
    return {'errors': [{'message': 'falhou', 'extensions': {'code': codigo, 'message': 'x'}}]}


class Resp(io.BytesIO):
    """Resposta falsa do opener (context manager com read)."""


class ApiFalsa:
    """Troca o OPENER_API.open: devolve as respostas da fila e guarda as requisições."""
    def __init__(self, *respostas):
        self.fila, self.pedidos = list(respostas), []

    def __call__(self, req, timeout=None):
        self.pedidos.append(req)
        r = self.fila.pop(0) if self.fila else resposta([])
        if isinstance(r, BaseException):
            raise r
        return Resp(r if isinstance(r, bytes) else json.dumps(r).encode())

    def variaveis(self):
        return [json.loads(p.data)['variables'] for p in self.pedidos]


class ConferenciaFalsa:
    """Troca o OPENER_CONFERENCIA.open: 3xx com Location (como o urllib sem seguir redirect) ou 200."""
    def __init__(self, location=DESTINO_BOM, codigo=302):
        self.location, self.codigo, self.links = location, codigo, []

    def __call__(self, req, timeout=None):
        self.links.append(req.full_url)
        if self.codigo == 200:
            return Resp(b'ok')
        h = http.client.HTTPMessage()
        if self.location is not None:
            h['Location'] = self.location
        raise urllib.error.HTTPError(req.full_url, self.codigo, 'x', h, io.BytesIO(b''))


class Base(unittest.TestCase):
    def setUp(self):
        for p in (S.DB, S.DB + '-wal', S.DB + '-shm', C.FEITOS):
            if os.path.exists(p):
                os.remove(p)
        self.buscas = os.path.join(TMP, 'buscas.json')
        with open(self.buscas, 'w', encoding='utf-8') as f:
            json.dump({CAT: ['Perfume feminino importado', 'Body splash', 'Kit perfume'], 'Outra': ['x']}, f)
        for alvo, valor in ((C, {'BUSCAS': self.buscas, 'ID_AFILIADO_SHOPEE': ID}),):
            for nome, v in valor.items():
                p = mock.patch.object(alvo, nome, v); p.start(); self.addCleanup(p.stop)
        p = mock.patch.object(C, 'pausa', lambda *a, **k: None); p.start(); self.addCleanup(p.stop)

    def rodar(self, argv, api=None, conf=None, env=ENV):
        """main(argv) com rede falsa; devolve (código, stdout, stderr). Confere que o Secret não saiu."""
        api = api or ApiFalsa()
        conf = conf or ConferenciaFalsa()
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, env), \
                mock.patch.object(C.OPENER_API, 'open', api), \
                mock.patch.object(C.urllib.request, 'urlopen', side_effect=AssertionError('urlopen direto')), \
                mock.patch.object(C.OPENER_CONFERENCIA, 'open', conf), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                codigo = C.main(argv)
            except SystemExit as e:
                codigo = e.code
        self.api, self.conf = api, conf
        saida = out.getvalue() + err.getvalue()
        self.assertNotIn(SECRET, saida)
        self.assertNotIn('Traceback', saida)
        return codigo, out.getvalue(), err.getvalue()

    def itens(self):
        if not os.path.exists(S.DB):
            return []
        con = S.conectar()
        try:
            return [dict(r) for r in con.execute('SELECT * FROM items ORDER BY id')]
        except Exception:
            return []
        finally:
            con.close()

    def feitos(self):
        if not os.path.exists(C.FEITOS):
            return []
        with open(C.FEITOS, encoding='utf-8') as f:
            return f.read().splitlines()


# ---------- funções puras ----------
class TestAssinatura(unittest.TestCase):
    def test_valor_conhecido(self):
        self.assertEqual(C.assinar('123456', 1700000000, '{"query":"q"}', 'segredo-de-teste'),
                         'b46778ee17f40be331e0f6a19b489045a862837221b8e70fcf1e38c712c24477')

    def test_formula_appid_ts_corpo_secret(self):
        esperado = hashlib.sha256('a19corpo çs'.encode('utf-8')).hexdigest()
        self.assertEqual(C.assinar('a1', 9, 'corpo ç', 's'), esperado)

    def test_cabecalho_nao_leva_o_secret(self):
        cab = C.autorizacao(APP_ID, 1700000000, C.assinar(APP_ID, 1700000000, '{}', SECRET))
        self.assertTrue(cab.startswith(f'SHA256 Credential={APP_ID}, Timestamp=1700000000, Signature='))
        self.assertNotIn(SECRET, cab)


class TestCorpoConsulta(unittest.TestCase):
    def test_termo_e_ordem_vao_como_variaveis(self):
        termo = 'perfume") { x } mutation { apagar } #'
        bruto = C.corpo_consulta(termo, 2)
        corpo = json.loads(bruto)
        self.assertEqual(set(corpo), {'query', 'variables'})
        self.assertEqual(corpo['query'], C.CONSULTA)
        self.assertEqual(bruto.count('apagar'), 1, 'o termo aparece uma vez só, nas variáveis')
        self.assertEqual(corpo['variables'], {'keyword': termo, 'sortType': 2, 'page': 1, 'limit': C.POR_BUSCA})
        self.assertNotIn('apagar', corpo['query'])

    def test_query_igual_para_qualquer_termo(self):
        a, b = json.loads(C.corpo_consulta('a', 1)), json.loads(C.corpo_consulta('Perfume árabe', 3))
        self.assertEqual(a['query'], b['query'])
        self.assertIn('$keyword', a['query'])
        self.assertIn('$sortType', a['query'])

    def test_ordens_do_plano(self):
        self.assertEqual(C.ORDENS, {'relevancia': 1, 'vendidos': 2, 'caros': 3})


class TestMapeamento(unittest.TestCase):
    def test_no_completo(self):
        it = C.no_para_item(no(), 'Kit perfume', CAT)
        self.assertEqual(it, {
            'loja': 'shopee', 'item_id': '112233.22334455667', 'cat': CAT, 'busca': 'Kit perfume', 'url': LINK,
            'data': {'titulo': 'Perfume Floral 100ml', 'preco': 'R$ 1.234,50', 'preco_antigo': '',
                     'desconto': '-20%', 'avaliacao': '4.8 de 5 estrelas', 'num_avaliacoes': '',
                     'vendas': '1.234 vendidos', 'frete': '', 'cupom': '', 'imagem': FOTO}})

    def test_numeros_como_texto_ou_numero(self):
        it = C.no_para_item(no(itemId='9', shopId='8', priceMin=12, ratingStar=5, sales='50', priceDiscountRate=0), 't', CAT)
        self.assertEqual(it['item_id'], '8.9')
        self.assertEqual(it['data']['preco'], 'R$ 12,00')
        self.assertEqual(it['data']['desconto'], '')
        self.assertEqual(it['data']['avaliacao'], '5.0 de 5 estrelas')
        self.assertEqual(it['data']['vendas'], '50 vendidos')

    def test_preco_invalido_fica_vazio(self):
        for p in (None, '', 'abc', -3, 0, float('nan'), True, '1e9'):
            with self.subTest(p=p):
                self.assertEqual(C.no_para_item(no(priceMin=p), 't', CAT)['data']['preco'], '')

    def test_imagem_so_do_cdn_da_shopee(self):
        for img in ('https://m.media-amazon.com/images/x.jpg', 'http://down-br.img.susercontent.com/f',
                    'https://down-br.img.susercontent.com.evil.com/f', 'https://down-br.img.susercontent.com:8443/f',
                    'javascript:alert(1)', 123, None, 'https://down-br.img.susercontent.com/' + 'a' * 300):
            with self.subTest(img=img):
                self.assertEqual(C.no_para_item(no(imageUrl=img), 't', CAT)['data']['imagem'], '')

    def test_titulo_so_texto_e_cortado(self):
        it = C.no_para_item(no(productName='Perfume\n\x00\x1b[31m  azul\u0085 ' + 'x' * 900), 't', CAT)
        self.assertTrue(it['data']['titulo'].startswith('Perfume [31m azul '))
        self.assertEqual(len(it['data']['titulo']), S.MAX_TITULO)
        for nome in (None, '', '   ', 123, ['a'], {'a': 1}):
            with self.subTest(nome=nome):
                self.assertIsNone(C.no_para_item(no(productName=nome), 't', CAT))

    def test_ids_invalidos_descartam(self):
        for campo, v in (('itemId', None), ('itemId', '1.2'), ('itemId', -1), ('itemId', True),
                         ('shopId', 'abc'), ('shopId', 10**25), ('shopId', '')):
            with self.subTest(campo=campo, v=v):
                self.assertIsNone(C.no_para_item(no(**{campo: v}), 't', CAT))

    def test_no_que_nao_e_objeto(self):
        for n in (None, [], 'x', 3):
            self.assertIsNone(C.no_para_item(n, 't', CAT))

    def test_item_passa_no_upsert_do_servidor(self):
        it = C.no_para_item(no(), 't', CAT)
        S.conferir_tipos(it, ('url', 'item_id', 'cat', 'busca'))
        self.assertTrue(S.eh_link_shopee(it['url']))


class TestPiso(unittest.TestCase):
    def test_nota_minima_e_vendas(self):
        casos = [(4.5, 50, True), ('4.5', '50', True), (4.5, 49, False), (5, '49', False), (4.5, 49.9, False),
                 (4.49, 999, False), (5, 0, False), (5, 1, False),
                 (None, 10, False), (4.9, None, False), ('', 10, False), (True, 10, False), (4.9, True, False),
                 (float('nan'), 10, False), ('4,8', 10, False)]
        for nota, vendas, entra in casos:
            with self.subTest(nota=nota, vendas=vendas):
                it = C.no_para_item(no(ratingStar=nota, sales=vendas), 't', CAT)
                self.assertEqual(it is not None, entra)

    def test_valores_do_dono(self):
        """P1 de 2026-11-04 (abas-nichadas-e-coleta.md): o piso de vendas subiu de 1 para 50."""
        self.assertEqual((C.NOTA_MINIMA, C.VENDAS_MINIMAS), (4.5, 50))


USADOS = ('Perfume Usado', 'iPhone 13 128GB Seminovo', 'Dell Latitude Recondicionado', 'Galaxy S21 Renovado',
          'Fritadeira Vitrine', 'Fone Open Box', 'Echo Dot REFURBISHED', 'Câmeras usadas', 'Kit SEMINOVA',
          'Notebook (Seminovo)', 'open  box', unicodedata.normalize('NFD', 'Perfume Usáda'))


class TestUsado(unittest.TestCase):
    """Decisão 4 / ADR do plano abas-nichadas-e-coleta: a recusa de usado fica no no_para_item, como na Amazon e no ML."""

    def test_titulo_de_usado_com_nota_e_vendas_otimas_e_descartado(self):
        for t in USADOS:
            with self.subTest(t=t):
                self.assertTrue(C.eh_usado(t))
                self.assertIsNone(C.no_para_item(no(productName=t, ratingStar=5, sales=99999), 't', CAT))

    def test_titulos_normais_passam(self):
        for t in ('Perfume Floral 100ml', 'Kit Renovador de Couro', 'Fone abusado resistente', 'Desusado',
                  'Panela Usadora', 'Perfume Vitrines', 'Body splash renovação'):
            with self.subTest(t=t):
                self.assertFalse(C.eh_usado(t))
                self.assertIsNotNone(C.no_para_item(no(productName=t), 't', CAT))

    def test_mesma_lista_da_amazon_e_do_ml(self):
        """A regex é cópia local: confere que as três coletas recusam exatamente os mesmos títulos."""
        with open(os.path.join(RAIZ, 'coletar_amazon.py'), encoding='utf-8') as f:
            amazon = re.search(r"^RE_USADO = re\.compile\(r'(.+)'\)$", f.read(), re.M).group(1)
        with open(os.path.join(RAIZ, 'coletar_ml.js'), encoding='utf-8') as f:
            ml = re.search(r'const RX_USADO = /(.+)/;$', f.read(), re.M).group(1)
        self.assertEqual(C.RE_USADO.pattern, amazon)
        self.assertEqual(C.RE_USADO.pattern, ml)


class TestLinkForaDoPadrao(unittest.TestCase):
    def test_so_link_curto_de_afiliado_da_shopee(self):
        ruins = ['https://www.amazon.com.br/dp/B0TESTE123?tag=desejodemen01-20', 'https://meli.la/1AbCd',
                 'http://s.shopee.com.br/AbC1', 'https://s.shopee.com.br/AbC1?x=1', 'https://s.shopee.com.br/',
                 'https://s.shopee.com.br:443/AbC1', 'https://S.SHOPEE.COM.BR/AbC1', 'https://shope.ee/AbC1',
                 'https://shopee.com.br/product/1/2', 'https://s.shopee.com.br.evil.com/AbC1',
                 'https://s.shopee.com.br/AbC1#x', 'https://s.shopee.com.br/' + 'a' * 300, None, 12, '']
        for link in ruins:
            with self.subTest(link=link):
                self.assertIsNone(C.no_para_item(no(offerLink=link), 't', CAT))


class TestDonoOk(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(C, 'ID_AFILIADO_SHOPEE', ID); p.start(); self.addCleanup(p.stop)

    def test_destino_do_dono(self):
        self.assertTrue(C.dono_ok(DESTINO_BOM))
        self.assertTrue(C.dono_ok(f'https://www.shopee.com.br/x?utm_source=an_{ID}'))

    def test_destino_ruim(self):
        for loc in (DESTINO_RUIM, 'https://shopee.com.br/product/1/2', None, '', 123,
                    f'http://shopee.com.br/x?utm_source=an_{ID}', f'https://shopee.com.br.evil.com/x?utm_source=an_{ID}',
                    f'https://evilshopee.com.br/x?utm_source=an_{ID}', f'https://shopee.com.br:8443/x?utm_source=an_{ID}',
                    f'https://u@shopee.com.br/x?utm_source=an_{ID}', f'/x?utm_source=an_{ID}',
                    f'https://shopee.com.br/x?utm_source=an_{ID}&utm_source=an_1',
                    f'https://shopee.com.br/x?utm_source=an_{ID}1', f'https://shopee.com.br/x#utm_source=an_{ID}',
                    f'https://evil.com/?r=shopee.com.br&utm_source=an_{ID}'):
            with self.subTest(loc=loc):
                self.assertFalse(C.dono_ok(loc))

    def test_id_vazio_nunca_confere(self):
        with mock.patch.object(C, 'ID_AFILIADO_SHOPEE', ''):
            self.assertFalse(C.dono_ok('https://shopee.com.br/x?utm_source=an_'))


# ---------- rede e fluxo ----------
class TestRequisicao(Base):
    def test_post_assinado_para_o_host_fixo(self):
        api = ApiFalsa(resposta([no()]))
        codigo, _, _ = self.rodar(['buscas', '--cat', CAT, '--ordens', 'vendidos'], api=api,
                                  env=dict(ENV, ACHADINHOS_SHOPEE_URL='http://127.0.0.1:1/graphql'))
        self.assertEqual(codigo, 0)
        req = api.pedidos[0]
        self.assertEqual(req.full_url, 'https://open-api.affiliate.shopee.com.br/graphql')
        self.assertEqual(req.get_method(), 'POST')
        self.assertEqual(req.get_header('Content-type'), 'application/json')
        cab = req.get_header('Authorization')
        m = re.fullmatch(rf'SHA256 Credential={APP_ID}, Timestamp=(\d+), Signature=([0-9a-f]{{64}})', cab)
        self.assertIsNotNone(m, cab)
        corpo = req.data.decode('utf-8')
        self.assertEqual(m.group(2), hashlib.sha256((APP_ID + m.group(1) + corpo + SECRET).encode()).hexdigest())
        self.assertEqual(json.loads(corpo)['variables']['keyword'], 'Perfume feminino importado')
        self.assertEqual(json.loads(corpo)['variables']['sortType'], 2)
        for parte in (req.full_url, corpo, repr(req.headers), repr(req)):
            self.assertNotIn(SECRET, parte)

    def test_sem_variavel_de_ambiente_para_a_url(self):
        with open(os.path.join(RAIZ, 'coletar_shopee.py'), encoding='utf-8') as f:
            fonte = f.read()
        nomes = set(re.findall(r"environ(?:\.get|\.pop)?\(?\[?'([A-Z_]+)'", fonte))
        self.assertEqual(nomes, {'ACHADINHOS_FEITOS_SHOPEE', 'ACHADINHOS_SHOPEE_APP_ID', 'ACHADINHOS_SHOPEE_SECRET'})
        self.assertEqual(C.URL_API, 'https://open-api.affiliate.shopee.com.br/graphql')

    def test_resposta_grande_demais_e_recusada(self):
        # JSON válido e no formato, só grande demais: sem o teto ele seria aceito
        api = ApiFalsa(json.dumps(dict(resposta([no()]), x='a' * C.MAX_RESPOSTA)).encode())
        codigo, _, err = self.rodar(['buscas', '--cat', CAT], api=api)
        self.assertEqual(codigo, 1)
        self.assertIn('fora do formato', err)
        self.assertEqual(self.itens(), [])

    def test_resposta_fora_do_formato(self):
        for r in (b'nao e json', b'[]', b'{"data": {"productOfferV2": {"nodes": "x"}}}', b'{"data": null}',
                  b'\xff\xfe', b'[' * 100000):
            with self.subTest(r=r[:20]):
                codigo, _, err = self.rodar(['buscas', '--cat', CAT], api=ApiFalsa(r))
                self.assertEqual(codigo, 1)
                self.assertEqual(self.itens(), [])

    def test_erro_da_api_mostra_so_o_codigo(self):
        api = ApiFalsa({'errors': [{'message': f'segredo {SECRET} invalido', 'extensions': {'code': 10020}}]})
        codigo, _, err = self.rodar(['buscas', '--cat', CAT], api=api)
        self.assertEqual(codigo, 1)
        self.assertIn('código 10020', err)
        self.assertNotIn('invalido', err)

    def test_http_de_erro_mostra_so_o_status(self):
        e = urllib.error.HTTPError(C.URL_API, 403, f'Forbidden {SECRET}', http.client.HTTPMessage(),
                                   io.BytesIO(f'{{"message": "{SECRET}"}}'.encode()))
        codigo, _, err = self.rodar(['buscas', '--cat', CAT], api=ApiFalsa(e))
        self.assertEqual(codigo, 1)
        self.assertIn('HTTP 403', err)


    def test_redirect_da_api_nao_e_seguido(self):
        """S2: um 3xx da API vira erro; o Authorization não vai para o Location e nada é gravado."""
        h = http.client.HTTPMessage()
        h['Location'] = 'https://evil.example/graphql'
        e = urllib.error.HTTPError(C.URL_API, 302, 'Found', h, io.BytesIO(b''))
        api = ApiFalsa(e, resposta([no()]))
        codigo, _, err = self.rodar(['buscas', '--cat', CAT], api=api)
        self.assertEqual(codigo, 1)
        self.assertIn('HTTP 302', err)
        self.assertEqual(len(api.pedidos), 1)
        self.assertEqual(api.pedidos[0].full_url, C.URL_API)
        self.assertEqual(self.itens(), [])
        self.assertEqual(self.feitos(), [])
        self.assertEqual(self.conf.links, [])


class TestColeta(Base):
    def test_grava_itens_do_piso_e_marca_progresso(self):
        api = ApiFalsa(resposta([no(), no(itemId=2, sales=0), no(itemId=3, offerLink='https://shopee.com.br/x'),
                                 no(itemId=4, ratingStar='4.4')]),
                       resposta([no(itemId=5, offerLink='https://s.shopee.com.br/Zz9')]),
                       resposta([]))
        codigo, out, _ = self.rodar(['buscas', '--cat', CAT], api=api)
        self.assertEqual(codigo, 0)
        itens = self.itens()
        self.assertEqual([(i['loja'], i['item_id'], i['busca'], i['cat']) for i in itens],
                         [('shopee', '112233.22334455667', 'Perfume feminino importado', CAT),
                          ('shopee', '112233.5', 'Body splash', CAT)])
        self.assertTrue(all(S.eh_link_afiliado(i['url']) and S.eh_link_shopee(i['url']) for i in itens))
        self.assertEqual(itens[0]['vendas'], '1.234 vendidos')
        # o terceiro termo não trouxe nada: fica para a próxima rodada
        self.assertEqual(self.feitos(), ['relevancia|Perfume feminino importado', 'relevancia|Body splash'])
        self.assertEqual(len(self.conf.links), 1, 'a conferência é feita uma vez por execução')
        self.assertEqual(self.conf.links[0], LINK)
        self.assertIn('TOTAL da Shopee no banco: 2', out)

    def test_ordens_e_progresso_por_ordem(self):
        with open(C.FEITOS, 'w', encoding='utf-8') as f:
            f.write('relevancia|Perfume feminino importado\nvendidos|Body splash\n')
        api = ApiFalsa(*[resposta([no(itemId=i)]) for i in range(1, 20)])
        codigo, _, _ = self.rodar(['buscas', '--cat', CAT, '--ordens', 'relevancia,vendidos,caros'], api=api)
        self.assertEqual(codigo, 0)
        pedidos = [(v['keyword'], v['sortType']) for v in api.variaveis()]
        self.assertEqual(pedidos, [('Perfume feminino importado', 2), ('Perfume feminino importado', 3),
                                   ('Body splash', 1), ('Body splash', 3),
                                   ('Kit perfume', 1), ('Kit perfume', 2), ('Kit perfume', 3)])
        self.assertEqual(len(self.feitos()), 9)
        self.assertEqual(len(set(self.feitos())), 9)

    def test_usado_com_nota_e_vendas_otimas_nao_e_gravado(self):
        api = ApiFalsa(resposta([no(itemId=1, productName='Perfume Importado Seminovo', ratingStar=5, sales=99999,
                                    offerLink='https://s.shopee.com.br/Usado1'),
                                 no(itemId=2, offerLink='https://s.shopee.com.br/Novo2')]),
                       resposta([no(itemId=3, productName='Kit open box', ratingStar=5, sales=99999)]),
                       resposta([]))
        codigo, out, err = self.rodar(['buscas', '--cat', CAT], api=api)
        self.assertEqual(codigo, 0, err)
        self.assertEqual([i['item_id'] for i in self.itens()], ['112233.2'])
        self.assertEqual(self.conf.links, ['https://s.shopee.com.br/Novo2'], 'o link do usado nem é conferido')
        # o termo só com usado não entra no piso: fica para a próxima rodada
        self.assertEqual(self.feitos(), ['relevancia|Perfume feminino importado'])
        self.assertIn('Body splash (relevancia): 1 achados, nenhum no piso', out)

    def test_so_termos_da_aba(self):
        api = ApiFalsa(resposta([no()]))
        self.rodar(['buscas', '--cat', 'Outra'], api=api)
        self.assertEqual([v['keyword'] for v in api.variaveis()], ['x'])

    def test_foto_de_outro_cdn_grava_sem_foto(self):
        """Foto da Amazon ou do ML num item da Shopee: o item entra, a foto não (disparo.imagem_permitida com loja)."""
        outras = ('https://m.media-amazon.com/images/I/71abc.jpg', 'https://http2.mlstatic.com/D_NQ_NP_123-O.webp')
        api = ApiFalsa(resposta([no(itemId=1, imageUrl=outras[0]), no(itemId=2, imageUrl=outras[1]),
                                 no(itemId=3)]))
        codigo, _, err = self.rodar(['buscas', '--cat', CAT], api=api)
        self.assertEqual(codigo, 0, err)
        self.assertEqual([(i['item_id'], i['imagem']) for i in self.itens()],
                         [('112233.1', ''), ('112233.2', ''), ('112233.3', FOTO)])

    def test_link_do_banco_nao_e_trocado(self):
        api = ApiFalsa(resposta([no()]))
        self.rodar(['buscas', '--cat', CAT], api=api)
        os.remove(C.FEITOS)
        api = ApiFalsa(resposta([no(offerLink='https://s.shopee.com.br/Outro1', productName='Novo nome')]))
        self.rodar(['buscas', '--cat', CAT], api=api)
        it = self.itens()[0]
        self.assertEqual((it['url'], it['titulo']), (LINK, 'Novo nome'))


class TestConferencia(Base):
    def test_conferencia_ruim_aborta_sem_gravar(self):
        api = ApiFalsa(resposta([no()]), resposta([no(itemId=2)]))
        codigo, _, err = self.rodar(['buscas', '--cat', CAT], api=api, conf=ConferenciaFalsa(DESTINO_RUIM))
        self.assertEqual(codigo, 1)
        self.assertIn('Nada foi gravado', err)
        self.assertEqual(self.itens(), [])
        self.assertEqual(self.feitos(), [])
        self.assertEqual(len(api.pedidos), 1, 'para no primeiro termo')

    def test_link_que_nao_redireciona_aborta(self):
        for conf in (ConferenciaFalsa(codigo=200), ConferenciaFalsa(location=None), ConferenciaFalsa(codigo=404)):
            with self.subTest(codigo=conf.codigo, location=conf.location):
                codigo, _, _ = self.rodar(['buscas', '--cat', CAT], api=ApiFalsa(resposta([no()])), conf=conf)
                self.assertEqual(codigo, 1)
                self.assertEqual(self.itens(), [])

    def test_conferencia_so_depois_de_um_item_valido(self):
        api = ApiFalsa(resposta([no(sales=0)]), resposta([no()]))
        codigo, _, _ = self.rodar(['buscas', '--cat', CAT], api=api, conf=ConferenciaFalsa(DESTINO_RUIM))
        self.assertEqual(codigo, 1)
        self.assertEqual(self.itens(), [])

    def test_conferir_bom_nao_grava(self):
        api = ApiFalsa(resposta([no(offerLink='https://shopee.com.br/x'), no()]))
        codigo, out, _ = self.rodar(['conferir'], api=api)
        self.assertEqual(codigo, 0)
        self.assertIn(f'afiliado {ID}', out)
        self.assertEqual(self.conf.links, [LINK])
        self.assertFalse(os.path.exists(S.DB))
        self.assertFalse(os.path.exists(C.FEITOS))
        self.assertEqual(api.variaveis()[0]['keyword'], C.TERMO_CONFERENCIA)

    def test_conferir_ruim(self):
        codigo, _, err = self.rodar(['conferir'], api=ApiFalsa(resposta([no()])), conf=ConferenciaFalsa(DESTINO_RUIM))
        self.assertEqual(codigo, 1)
        self.assertIn('PAROU', err)

    def test_conferir_sem_link(self):
        codigo, out, _ = self.rodar(['conferir'], api=ApiFalsa(resposta([])))
        self.assertEqual(codigo, 1)
        self.assertEqual(self.conf.links, [])

    def test_openers_nao_seguem_redirect(self):
        for opener in (C.OPENER_API, C.OPENER_CONFERENCIA):
            redirs = [h for h in opener.handlers if isinstance(h, urllib.request.HTTPRedirectHandler)]
            self.assertEqual([type(h) for h in redirs], [C.SemRedirecionar])

    def test_opener_nao_segue_redirect(self):
        self.assertTrue(any(isinstance(h, C.SemRedirecionar) for h in C.OPENER_CONFERENCIA.handlers))
        self.assertFalse(any(isinstance(h, urllib.request.HTTPRedirectHandler) and not isinstance(h, C.SemRedirecionar)
                             for h in C.OPENER_CONFERENCIA.handlers))
        visitas = []

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                visitas.append(self.path)
                self.send_response(302 if self.path == '/curto' else 200)
                self.send_header('Location', '/destino')
                self.end_headers()

            def log_message(self, *a):
                pass

        srv = http.server.HTTPServer(('127.0.0.1', 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), C.SemRedirecionar)
        with self.assertRaises(urllib.error.HTTPError) as cm:
            opener.open(f'http://127.0.0.1:{srv.server_port}/curto', timeout=5)
        self.assertEqual(cm.exception.headers.get('Location'), '/destino')
        cm.exception.close()
        self.assertEqual(visitas, ['/curto'])

    def test_destino_so_abre_link_curto(self):
        conf = ConferenciaFalsa()
        with mock.patch.object(C.OPENER_CONFERENCIA, 'open', conf):
            self.assertIsNone(C.destino('https://evil.com/x'))
        self.assertEqual(conf.links, [])


class TestLimite(Base):
    def test_10030_para_e_preserva_progresso(self):
        api = ApiFalsa(resposta([no()]), erro(10030), resposta([no(itemId=3)]))
        codigo, _, err = self.rodar(['buscas', '--cat', CAT], api=api)
        self.assertEqual(codigo, 3)
        self.assertIn('10030', err)
        self.assertEqual(self.feitos(), ['relevancia|Perfume feminino importado'])
        self.assertEqual(len(self.itens()), 1)
        self.assertEqual(len(api.pedidos), 2, 'o terceiro termo não é pedido')
        # na rodada seguinte, retoma do termo que bateu no limite
        api = ApiFalsa(resposta([no(itemId=2)]), resposta([no(itemId=3)]))
        codigo, _, _ = self.rodar(['buscas', '--cat', CAT], api=api)
        self.assertEqual(codigo, 0)
        self.assertEqual([v['keyword'] for v in api.variaveis()], ['Body splash', 'Kit perfume'])
        self.assertEqual(len(self.itens()), 3)

    def test_codigo_em_texto(self):
        """R4: extensions.code como texto só com dígitos também é reconhecido."""
        for corpo in (erro('10030'), {'errors': [{'extensions': {'code': '10030'}}], 'data': None}):
            with self.subTest(corpo=corpo):
                api = ApiFalsa(resposta([no()]), corpo)
                codigo, _, err = self.rodar(['buscas', '--cat', CAT], api=api)
                self.assertEqual(codigo, 3, err)
                self.assertEqual(self.feitos(), ['relevancia|Perfume feminino importado'])
                os.remove(C.FEITOS)
        e = urllib.error.HTTPError(C.URL_API, 403, 'x', http.client.HTTPMessage(),
                                   io.BytesIO(json.dumps(erro('10030')).encode()))
        self.assertEqual(self.rodar(['buscas', '--cat', CAT], api=ApiFalsa(e))[0], 3)
        self.assertEqual(C.codigo_de_erro(erro('10020')), 10020)
        for ruim in ('10030x', ' 10030', '', '1' * 20, 1.5, True, None):
            with self.subTest(ruim=ruim):
                self.assertEqual(C.codigo_de_erro(erro(ruim)), 0)

    def test_limite_por_http(self):
        corpo = io.BytesIO(json.dumps(erro(10030)).encode())
        for e in (urllib.error.HTTPError(C.URL_API, 429, 'x', http.client.HTTPMessage(), io.BytesIO(b'')),
                  urllib.error.HTTPError(C.URL_API, 403, 'x', http.client.HTTPMessage(), corpo)):
            with self.subTest(codigo=e.code):
                codigo, _, _ = self.rodar(['buscas', '--cat', CAT], api=ApiFalsa(e))
                self.assertEqual(codigo, 3)


class TestConfiguracao(Base):
    def test_id_vazio_sai_com_2_sem_chamar_a_api(self):
        for id_ in ('', 'abc', ' 123'):
            with self.subTest(id_=id_), mock.patch.object(C, 'ID_AFILIADO_SHOPEE', id_):
                for argv in (['conferir'], ['buscas', '--cat', CAT]):
                    codigo, _, err = self.rodar(argv)
                    self.assertEqual(codigo, 2)
                    self.assertIn('preencha ID_AFILIADO_SHOPEE', err)
                    self.assertEqual(self.api.pedidos, [])

    def test_credencial_ausente_sai_com_2(self):
        for env in ({'ACHADINHOS_SHOPEE_APP_ID': APP_ID, 'ACHADINHOS_SHOPEE_SECRET': ''},
                    {'ACHADINHOS_SHOPEE_APP_ID': '', 'ACHADINHOS_SHOPEE_SECRET': SECRET},
                    {'ACHADINHOS_SHOPEE_APP_ID': '1 2\nX: y', 'ACHADINHOS_SHOPEE_SECRET': SECRET}):
            with self.subTest(app=env['ACHADINHOS_SHOPEE_APP_ID']):
                codigo, _, err = self.rodar(['conferir'], env=env)
                self.assertEqual(codigo, 2)
                self.assertIn('ACHADINHOS_SHOPEE_SECRET', err)
                self.assertEqual(self.api.pedidos, [])
        self.assertFalse(any(v in os.environ for v in ENV))   # o import do teste tirou as duas
        codigo, _, _ = self.rodar(['buscas', '--cat', CAT], env={})
        self.assertEqual(codigo, 2)

    def test_argumentos_invalidos(self):
        for argv in ([], ['buscas'], ['buscas', '--cat', CAT, '--ordens', 'avaliados'],
                     ['buscas', '--cat', CAT, '--ordens', 'vendidos,vendidos'], ['buscas', '--cat', CAT, '--ordens', ','],
                     ['buscas', '--cat', CAT, '--secret', 'x'], ['outro']):
            with self.subTest(argv=argv):
                codigo, _, _ = self.rodar(argv)
                self.assertEqual(codigo, 2)
                self.assertEqual(self.api.pedidos, [])

    def test_aba_em_nfd(self):
        """R5: a aba digitada em NFD acha os termos do buscas.json (NFC) e grava a cat em NFC."""
        aba = 'Casa e Decoração'
        with open(self.buscas, 'w', encoding='utf-8') as f:
            json.dump({aba: ['Luminária']}, f, ensure_ascii=False)
        nfd = unicodedata.normalize('NFD', aba)
        self.assertNotEqual(nfd, aba)
        api = ApiFalsa(resposta([no()]))
        codigo, _, err = self.rodar(['buscas', '--cat', nfd], api=api)
        self.assertEqual(codigo, 0, err)
        self.assertEqual([v['keyword'] for v in api.variaveis()], ['Luminária'])
        self.assertEqual([i['cat'] for i in self.itens()], [aba])
        self.assertEqual(C.termos_da_aba(nfd), ['Luminária'])

    def test_aba_inexistente(self):
        codigo, _, err = self.rodar(['buscas', '--cat', 'Nao existe'])
        self.assertEqual(codigo, 2)
        self.assertEqual(self.api.pedidos, [])


class TestSegredo(Base):
    def test_repr_e_format_escondem(self):
        seg = C.Segredo(SECRET)
        for texto in (repr(seg), str(seg), f'{seg}', f'{seg!r}', repr((APP_ID, seg)), '%s' % seg):
            self.assertNotIn(SECRET, texto)
        with mock.patch.dict(os.environ, ENV):
            self.assertNotIn(SECRET, repr(C.credenciais()))

    def test_credenciais_tira_o_secret_do_ambiente(self):
        """S3: depois de lido, o Secret não fica no os.environ do processo (nem para subprocesso)."""
        with mock.patch.dict(os.environ, ENV):
            app, seg = C.credenciais()
            self.assertEqual((app, seg.valor()), (APP_ID, SECRET))
            self.assertNotIn('ACHADINHOS_SHOPEE_SECRET', os.environ)
            self.assertEqual(os.environ.get('ACHADINHOS_SHOPEE_APP_ID'), APP_ID)
        with mock.patch.dict(os.environ, {'ACHADINHOS_SHOPEE_APP_ID': '', 'ACHADINHOS_SHOPEE_SECRET': SECRET}):
            self.assertIsNone(C.credenciais())
            self.assertNotIn('ACHADINHOS_SHOPEE_SECRET', os.environ)

    def test_main_tira_o_secret_do_ambiente(self):
        visto = []
        api = ApiFalsa(resposta([no()]))
        original = api.__call__

        def espiao(req, timeout=None):
            visto.append('ACHADINHOS_SHOPEE_SECRET' in os.environ)
            return original(req, timeout)
        codigo, _, _ = self.rodar(['buscas', '--cat', CAT], api=espiao)
        self.assertEqual(codigo, 0)
        self.assertTrue(visto)
        self.assertNotIn(True, visto)

    def test_instrucao_sem_export(self):
        with open(os.path.join(RAIZ, 'coletar_shopee.py'), encoding='utf-8') as f:
            fonte = f.read()
        self.assertNotRegex(fonte, r'\bexport\s+[A-Z]')   # "sem export" no texto é a orientação, não o comando
        self.assertIn('unset S', fonte)
        codigo, _, err = self.rodar(['conferir'], env={'ACHADINHOS_SHOPEE_APP_ID': APP_ID, 'ACHADINHOS_SHOPEE_SECRET': ''})
        self.assertEqual(codigo, 2)
        self.assertIn('ACHADINHOS_SHOPEE_SECRET="$S"', err)
        self.assertNotRegex(err, r'\bexport\s+[A-Z]')

    def test_secret_nao_fica_no_modulo(self):
        with mock.patch.dict(os.environ, ENV):
            self.rodar(['buscas', '--cat', CAT], api=ApiFalsa(resposta([no()])))
        for nome, v in vars(C).items():
            self.assertNotIn(SECRET, repr(v), nome)

    def test_excecao_com_o_secret_mostra_so_o_tipo(self):
        for exc in (RuntimeError(f'falhou {SECRET}'), urllib.error.URLError(f'x {SECRET}'),
                    ValueError(SECRET), OSError(SECRET)):
            with self.subTest(tipo=type(exc).__name__):
                codigo, _, err = self.rodar(['buscas', '--cat', CAT], api=ApiFalsa(exc))
                self.assertEqual(codigo, 1)
                self.assertIn(f'ERRO: {type(exc).__name__}', err)
        with mock.patch.object(C.S, 'upsert', side_effect=ValueError(SECRET)):
            codigo, _, _ = self.rodar(['buscas', '--cat', CAT], api=ApiFalsa(resposta([no()])))
            self.assertEqual(codigo, 1)
        codigo, _, _ = self.rodar(['buscas', '--cat', CAT], api=ApiFalsa(resposta([no()])),
                                  conf=lambda *a, **k: (_ for _ in ()).throw(OSError(SECRET)))
        self.assertEqual(codigo, 1)

    def test_subprocesso_nao_imprime_o_secret(self):
        """Roda o script de verdade, sem rede: urlopen e a conferência levantam exceção com o Secret."""
        env = dict(os.environ, **ENV)
        prologo = ('import os, sys, urllib.request; sys.path.insert(0, %r); import coletar_shopee as C\n'
                   'SEG = os.environ["ACHADINHOS_SHOPEE_SECRET"]\n'   # o credenciais() tira do ambiente
                   'def f(*a, **k): raise OSError(SEG)\n'
                   'urllib.request.urlopen = f; C.OPENER_API.open = f; C.OPENER_CONFERENCIA.open = f\n') % RAIZ
        casos = [("C.ID_AFILIADO_SHOPEE = ''", ['conferir'], 2),
                 (f"C.ID_AFILIADO_SHOPEE = '{ID}'", ['conferir'], 1),
                 (f"C.ID_AFILIADO_SHOPEE = '{ID}'", ['buscas', '--cat', CAT], 1)]
        for ajuste, argv, esperado in casos:
            with self.subTest(argv=argv, ajuste=ajuste):
                codigo = prologo + ajuste + f'\nsys.argv[1:] = {argv!r}\nsys.exit(C.main())\n'
                r = subprocess.run([sys.executable, '-c', codigo], env=env, cwd=TMP,
                                   capture_output=True, text=True, timeout=60)
                self.assertEqual(r.returncode, esperado, r.stderr)
                self.assertNotIn(SECRET, r.stdout + r.stderr)
                self.assertNotIn('Traceback', r.stderr)

    def test_copia_do_script_com_id_vazio(self):
        """Cópia do arquivo real só com o ID vazio, rodada como script: sai com 2 antes de qualquer rede.

        A cópia fica num diretório temporário e acha servidor.py e disparo.py pelo PYTHONPATH. Os proxies
        mortos do ambiente seguram qualquer saída acidental.
        """
        with open(os.path.join(RAIZ, 'coletar_shopee.py'), encoding='utf-8') as f:
            fonte = f.read()
        linha = f"ID_AFILIADO_SHOPEE = '{ID_DO_ARQUIVO}'\n"
        self.assertEqual(fonte.count(linha), 1)
        pasta = tempfile.mkdtemp(dir=TMP)
        copia = os.path.join(pasta, 'coletar_shopee.py')
        with open(copia, 'w', encoding='utf-8') as f:
            f.write(fonte.replace(linha, "ID_AFILIADO_SHOPEE = ''\n"))
        env = dict(os.environ, **ENV, PYTHONPATH=RAIZ)
        for argv in (['conferir'], ['buscas', '--cat', CAT]):
            with self.subTest(argv=argv):
                r = subprocess.run([sys.executable, copia] + argv, env=env, cwd=TMP,
                                   capture_output=True, text=True, timeout=60)
                self.assertEqual(r.returncode, 2, r.stderr)
                self.assertIn('preencha ID_AFILIADO_SHOPEE', r.stderr)
                self.assertNotIn(SECRET, r.stdout + r.stderr)
                self.assertNotIn('Traceback', r.stderr)
        self.assertFalse(os.path.exists(C.FEITOS))


MARCA = 'CONTEUDO-DO-ARQUIVO-4e1b'   # vai no arquivo do importar: nunca pode aparecer na saída
TERMO = 'Body splash'


class AmbienteEspiao(dict):
    """Troca o os.environ e anota toda chave lida (get, pop, [] e in)."""
    def __init__(self, base):
        super().__init__(base)
        self.lidas = []

    def __getitem__(self, k):
        self.lidas.append(k)
        return super().__getitem__(k)

    def get(self, k, padrao=None):
        self.lidas.append(k)
        return super().get(k, padrao)

    def pop(self, k, *padrao):
        self.lidas.append(k)
        return super().pop(k, *padrao)

    def __contains__(self, k):
        self.lidas.append(k)
        return super().__contains__(k)


class ConferenciaEspia(ConferenciaFalsa):
    """Anota se o banco já existia no momento da conferência do dono."""
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.banco_existia = []

    def __call__(self, req, timeout=None):
        self.banco_existia.append(os.path.exists(S.DB))
        return super().__call__(req, timeout)


class ConferenciaPorLink(ConferenciaFalsa):
    """Location por link (o que não está no mapa vai para DESTINO_BOM); anota cada link em `eventos`, se dado."""
    def __init__(self, destinos, eventos=None):
        super().__init__()
        self.destinos, self.eventos = destinos, eventos

    def __call__(self, req, timeout=None):
        if self.eventos is not None:
            self.eventos.append(req.full_url)
        self.location = self.destinos.get(req.full_url, DESTINO_BOM)
        return super().__call__(req, timeout)


class TestImportar(Base):
    """CA9 (docs/produto/planos/abas-nichadas-e-coleta.md, etapa 7): `importar ARQUIVO` sem credencial."""

    def lote(self, nos=None, cat=CAT, busca=TERMO):
        return {'cat': cat, 'busca': busca, 'nos': [no()] if nos is None else nos}

    def arquivo(self, dados=None, bruto=None):
        if bruto is None:
            bruto = json.dumps(self.lote() if dados is None else dados, ensure_ascii=False).encode('utf-8')
        pasta = tempfile.mkdtemp(dir=TMP)
        caminho = os.path.join(pasta, 'lote.json')
        with open(caminho, 'wb') as f:
            f.write(bruto)
        return caminho

    def importar(self, dados=None, bruto=None, conf=None, env=None, caminho=None):
        """Roda `importar` sem credencial no ambiente; confere que a API não é chamada e que nada do arquivo sai."""
        caminho = caminho or self.arquivo(dados, bruto)
        api = ApiFalsa()
        codigo, out, err = self.rodar(['importar', caminho], api=api, conf=conf, env={} if env is None else env)
        self.assertEqual(api.pedidos, [], 'o importar nunca chama a Open API')
        for proibido in (MARCA, LINK, CAT, TERMO, 's.shopee.com.br', FOTO):
            self.assertNotIn(proibido, out + err)
        return codigo, out, err

    def nada_gravado(self):
        self.assertFalse(os.path.exists(S.DB), 'o banco nem é criado')
        self.assertEqual(self.feitos(), [])

    def test_grava_so_o_piso_confere_o_dono_antes_e_marca_vendidos(self):
        nos = [no(itemId=1, sales=50, productName=MARCA + ' A', offerLink='https://s.shopee.com.br/Imp1'),
               no(itemId=2, sales=49, productName=MARCA), no(itemId=3, ratingStar='4.49'),
               no(itemId=4, offerLink='https://shopee.com.br/product/1/4'), no(itemId=6, offerLink=f'https://s.shopee.com.br/{MARCA}'),
               no(itemId=5, sales='1234', offerLink='https://s.shopee.com.br/Imp5')]
        conf = ConferenciaEspia()
        codigo, out, err = self.importar(self.lote(nos), conf=conf)
        self.assertEqual(codigo, 0, err)
        self.assertEqual([(i['loja'], i['item_id'], i['cat'], i['busca'], i['url']) for i in self.itens()],
                         [('shopee', '112233.1', CAT, TERMO, 'https://s.shopee.com.br/Imp1'),
                          ('shopee', '112233.5', CAT, TERMO, 'https://s.shopee.com.br/Imp5')])
        self.assertEqual(self.itens()[1]['vendas'], '1.234 vendidos')
        self.assertEqual(conf.links, ['https://s.shopee.com.br/Imp1', 'https://s.shopee.com.br/Imp5'],
                         'S1: confere o dono de cada link que passou no piso, na ordem do arquivo')
        self.assertEqual(conf.banco_existia, [False, False], 'as conferências vêm antes de criar o banco e de gravar')
        self.assertEqual(self.feitos(), [f'vendidos|{TERMO}'])
        self.assertIn('importar: 6 no arquivo, 2 no piso, 2 novos, 0 atualizados.', out)
        self.assertIn('TOTAL da Shopee no banco: 2', out)

    def test_nao_chama_credenciais_nem_le_o_ambiente(self):
        caminho = self.arquivo()
        espiao = AmbienteEspiao(dict(os.environ, **ENV))
        with mock.patch.object(C, 'credenciais', side_effect=AssertionError('credenciais() no importar')), \
                mock.patch.object(os, 'environ', espiao):
            codigo, _, err = self.importar(caminho=caminho, env=ENV)
        self.assertEqual(codigo, 0, err)
        self.assertEqual(len(self.itens()), 1)
        self.assertEqual([k for k in espiao.lidas if k.startswith('ACHADINHOS_SHOPEE')], [])
        # o Secret de um terminal descuidado fica onde estava: o importar não faz o pop do credenciais()
        with mock.patch.dict(os.environ, ENV), contextlib.redirect_stdout(io.StringIO()), \
                mock.patch.object(C.OPENER_CONFERENCIA, 'open', ConferenciaFalsa()):
            self.assertEqual(C.main(['importar', caminho]), 0)
            self.assertEqual(os.environ.get('ACHADINHOS_SHOPEE_SECRET'), SECRET)
        # o espião enxerga a leitura quando ela existe (o modo buscas lê e tira o Secret)
        espiao = AmbienteEspiao(dict(os.environ, **ENV))
        with mock.patch.object(os, 'environ', espiao):
            self.rodar(['buscas', '--cat', CAT], api=ApiFalsa(resposta([])))
        self.assertIn('ACHADINHOS_SHOPEE_SECRET', espiao.lidas)

    def test_conferir_e_buscas_continuam_exigindo_credencial(self):
        self.assertEqual(self.importar()[0], 0)
        for argv in (['conferir'], ['buscas', '--cat', CAT]):
            with self.subTest(argv=argv):
                codigo, _, err = self.rodar(argv, env={})
                self.assertEqual(codigo, 2)
                self.assertIn('ACHADINHOS_SHOPEE_SECRET', err)
                self.assertEqual(self.api.pedidos, [])

    def test_teto_de_bytes(self):
        """JSON válido e no formato: no teto exato entra; um byte a mais é recusado sem gravar nada."""
        base = json.dumps(self.lote()).encode()
        codigo, _, err = self.importar(bruto=base + b' ' * (C.MAX_RESPOSTA - len(base)))
        self.assertEqual(codigo, 0, err)
        self.assertEqual(len(self.itens()), 1)
        self.setUp()
        conf = ConferenciaFalsa()
        codigo, _, err = self.importar(bruto=base + b' ' * (C.MAX_RESPOSTA + 1 - len(base)), conf=conf)
        self.assertEqual(codigo, 1)
        self.assertIn('fora do formato', err)
        self.assertEqual(conf.links, [])
        self.nada_gravado()

    def test_arquivo_fora_do_formato_sai_com_1_sem_gravar(self):
        lote = self.lote()
        brutos = [b'', b'nao e json', b'\xff\xfe{', b'[' * 100000, b'[]', b'null', b'"x"', b'1',
                  ('{"cat": "%s", "busca": "%s", "nos": [%s]}' % (CAT, TERMO, '9' * 5000)).encode()]
        dicts = [{}, {'cat': CAT, 'busca': TERMO}, dict(lote, extra=MARCA), dict(lote, cat=5), dict(lote, cat=None),
                 dict(lote, cat=''), dict(lote, cat=[CAT]), dict(lote, busca=7), dict(lote, busca=''),
                 dict(lote, busca=MARCA * 10), dict(lote, nos={}), dict(lote, nos=MARCA), dict(lote, nos=[]),
                 dict(lote, nos=None), dict(lote, nos=[no(), None]), dict(lote, nos=[no(), [no()]]),
                 dict(lote, nos=[no(), MARCA]), dict(lote, nos=[no()] * (C.MAX_NOS_ARQUIVO + 1))]
        for caso in brutos + dicts:
            with self.subTest(caso=repr(caso)[:60]):
                self.setUp()
                conf = ConferenciaFalsa()
                if isinstance(caso, bytes):
                    codigo, _, err = self.importar(bruto=caso, conf=conf)
                else:
                    codigo, _, err = self.importar(caso, conf=conf)
                self.assertEqual(codigo, 1, err)
                self.assertIn('fora do formato', err)
                self.assertEqual(conf.links, [])
                self.nada_gravado()

    def test_lote_de_100_nos_entra(self):
        nos = [no(itemId=i, offerLink=f'https://s.shopee.com.br/Cem{i}') for i in range(C.MAX_NOS_ARQUIVO)]
        codigo, out, err = self.importar(self.lote(nos))
        self.assertEqual(codigo, 0, err)
        self.assertEqual(len(self.itens()), C.MAX_NOS_ARQUIVO)
        self.assertEqual(C.MAX_NOS_ARQUIVO, 100)

    def test_aba_e_termo_conferidos_no_buscas_json(self):
        with open(self.buscas, 'w', encoding='utf-8') as f:
            json.dump({CAT: [TERMO, 'Kit perfume', 'a|b', 'linha\nnova'], 'Outra': ['x']}, f)
        for cat, busca in ((MARCA, TERMO), ('Outra', TERMO), (CAT, 'x'), (CAT, TERMO.lower()), (CAT.lower(), TERMO),
                           (CAT, TERMO + ' '), (' ' + CAT, TERMO), (CAT, MARCA), (CAT, 'a|b'), (CAT, 'linha\nnova')):
            with self.subTest(cat=cat, busca=busca):
                self.setUp()
                with open(self.buscas, 'w', encoding='utf-8') as f:
                    json.dump({CAT: [TERMO, 'Kit perfume', 'a|b', 'linha\nnova'], 'Outra': ['x']}, f)
                conf = ConferenciaFalsa()
                codigo, _, err = self.importar(self.lote(cat=cat, busca=busca), conf=conf)
                self.assertEqual(codigo, 2)
                self.assertIn('não está no buscas.json', err)
                self.assertEqual(conf.links, [])
                self.nada_gravado()

    def test_aba_e_termo_em_nfd_gravam_em_nfc(self):
        aba, termo = 'Casa e Decoração', 'Luminária'
        with open(self.buscas, 'w', encoding='utf-8') as f:
            json.dump({aba: [termo]}, f, ensure_ascii=False)
        lote = self.lote(cat=unicodedata.normalize('NFD', aba), busca=unicodedata.normalize('NFD', termo))
        self.assertNotEqual(lote['cat'], aba)
        codigo, _, err = self.importar(lote)
        self.assertEqual(codigo, 0, err)
        self.assertEqual([(i['cat'], i['busca']) for i in self.itens()], [(aba, termo)])
        self.assertEqual(self.feitos(), [f'vendidos|{termo}'])

    def test_arquivo_inexistente_ou_que_nao_e_arquivo_sai_com_2(self):
        for caminho in (os.path.join(TMP, 'nao-existe.json'), TMP, os.path.join(TMP, MARCA)):
            with self.subTest(caminho=caminho):
                codigo, _, err = self.importar(caminho=caminho)
                self.assertEqual(codigo, 2)
                self.assertIn('não existe ou não pôde ser lido', err)
                self.nada_gravado()

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'só em sistema com FIFO')
    def test_fifo_e_recusado_sem_travar(self):
        """Um FIFO no lugar do arquivo não é aberto (o open ficaria esperando quem escreve)."""
        fifo = os.path.join(tempfile.mkdtemp(dir=TMP), 'lote.json')
        os.mkfifo(fifo)
        resultado = []

        def ler():
            try:
                C.ler_arquivo(fifo)
            except C.ArquivoAusente:
                resultado.append('ausente')
        t = threading.Thread(target=ler, daemon=True)
        t.start()
        t.join(5)
        if t.is_alive():   # destrava a thread presa no open antes de reprovar
            os.close(os.open(fifo, os.O_WRONLY | os.O_NONBLOCK))
        self.assertEqual(resultado, ['ausente'])

    def test_dono_errado_ou_link_que_nao_redireciona_nao_grava(self):
        for conf in (ConferenciaFalsa(DESTINO_RUIM), ConferenciaFalsa(location=None), ConferenciaFalsa(codigo=200),
                     ConferenciaFalsa(codigo=404), ConferenciaFalsa(f'https://evil.com/?utm_source=an_{ID}')):
            with self.subTest(codigo=conf.codigo, location=conf.location):
                self.setUp()
                codigo, _, err = self.importar(conf=conf)
                self.assertEqual(codigo, 1)
                self.assertIn('Nada foi gravado', err)
                self.assertEqual(conf.links, [LINK])
                self.nada_gravado()

    def test_usado_com_nota_e_vendas_otimas_nao_e_gravado(self):
        nos = [no(itemId=1, productName='Perfume Usado ' + MARCA, ratingStar=5, sales=99999,
                  offerLink='https://s.shopee.com.br/Usado1'),
               no(itemId=2, offerLink='https://s.shopee.com.br/Novo2')]
        conf = ConferenciaFalsa()
        codigo, out, err = self.importar(self.lote(nos), conf=conf)
        self.assertEqual(codigo, 0, err)
        self.assertEqual([i['item_id'] for i in self.itens()], ['112233.2'])
        self.assertEqual(conf.links, ['https://s.shopee.com.br/Novo2'], 'o link do usado nem é conferido')
        self.assertIn('importar: 2 no arquivo, 1 no piso, 1 novos', out)
        # só usado no arquivo: nada no piso, nada gravado e o termo fica para a próxima rodada
        self.setUp()
        conf = ConferenciaFalsa()
        codigo, out, err = self.importar(self.lote([nos[0]]), conf=conf)
        self.assertEqual(codigo, 0, err)
        self.assertIn('1 no arquivo, nenhum no piso', out)
        self.assertEqual(conf.links, [])
        self.nada_gravado()

    def test_segundo_link_de_outro_afiliado_nao_grava_nada(self):
        """S1: o dono é conferido em todos os links distintos do arquivo antes do primeiro gravar."""
        outro = 'https://s.shopee.com.br/Outro2'
        for ruim in (DESTINO_RUIM, None):
            with self.subTest(destino=ruim):
                self.setUp()
                conf = ConferenciaPorLink({outro: ruim})
                nos = [no(itemId=1), no(itemId=2, offerLink=outro), no(itemId=3, offerLink='https://s.shopee.com.br/Bom3')]
                codigo, _, err = self.importar(self.lote(nos), conf=conf)
                self.assertEqual(codigo, 1)
                self.assertIn('Nada foi gravado', err)
                self.assertEqual(conf.links, [LINK, outro], 'para na primeira falha')
                self.nada_gravado()

    def test_confere_cada_link_distinto_uma_vez_com_pausa_entre_eles(self):
        eventos = []
        conf = ConferenciaPorLink({}, eventos)
        nos = [no(itemId=1), no(itemId=2, offerLink='https://s.shopee.com.br/Dois2'), no(itemId=3), no(itemId=4)]
        with mock.patch.object(C, 'pausa', lambda *a, **k: eventos.append('pausa')):
            codigo, out, err = self.importar(self.lote(nos), conf=conf)
        self.assertEqual(codigo, 0, err)
        self.assertEqual(eventos, [LINK, 'pausa', 'https://s.shopee.com.br/Dois2'])
        self.assertEqual(len(self.itens()), 4)
        self.assertIn('4 no piso, 4 novos', out)

    def test_nenhum_no_no_piso_nao_marca_nem_confere(self):
        conf = ConferenciaFalsa()
        nos = [no(itemId=1, sales=49), no(itemId=2, ratingStar=4.4), no(itemId=3, offerLink='https://meli.la/AbC1')]
        codigo, out, err = self.importar(self.lote(nos), conf=conf)
        self.assertEqual(codigo, 0, err)
        self.assertIn('3 no arquivo, nenhum no piso', out)
        self.assertEqual(conf.links, [])
        self.nada_gravado()

    def test_progresso_compartilhado_com_a_open_api_e_sem_linha_repetida(self):
        self.assertEqual(self.importar()[0], 0)
        # de novo, com outro link para o mesmo item: atualiza os dados, preserva o link e não repete a marca
        lote = self.lote([no(offerLink='https://s.shopee.com.br/Outro1', productName='Nome novo')])
        codigo, out, _ = self.importar(lote)
        self.assertEqual(codigo, 0)
        self.assertIn('1 no piso, 0 novos, 1 atualizados', out)
        self.assertEqual([(i['url'], i['titulo']) for i in self.itens()], [(LINK, 'Nome novo')])
        self.assertEqual(self.feitos(), [f'vendidos|{TERMO}'])
        # a Open API na ordem vendidos pula o termo já importado
        api = ApiFalsa(resposta([]), resposta([]), resposta([]))
        codigo, _, _ = self.rodar(['buscas', '--cat', CAT, '--ordens', 'vendidos'], api=api)
        self.assertEqual(codigo, 0)
        self.assertEqual([v['keyword'] for v in api.variaveis()], ['Perfume feminino importado', 'Kit perfume'])

    def test_excecao_mostra_so_o_tipo(self):
        def explode(*a, **k):
            raise OSError(f'{MARCA} {LINK}')
        codigo, _, err = self.importar(conf=explode)
        self.assertEqual(codigo, 1)
        self.assertIn('ERRO: OSError', err)
        self.nada_gravado()
        with mock.patch.object(C.S, 'upsert', side_effect=ValueError(f'{MARCA} {LINK}')):
            codigo, _, err = self.importar()
        self.assertEqual(codigo, 1)
        self.assertIn('ERRO: ValueError', err)
        self.assertEqual(self.feitos(), [])

    def test_id_vazio_sai_com_2_sem_conferir(self):
        conf = ConferenciaFalsa()
        with mock.patch.object(C, 'ID_AFILIADO_SHOPEE', ''):
            codigo, _, err = self.importar(conf=conf)
        self.assertEqual(codigo, 2)
        self.assertIn('preencha ID_AFILIADO_SHOPEE', err)
        self.assertEqual(conf.links, [])
        self.nada_gravado()

    def test_argumentos(self):
        for argv in (['importar'], ['importar', 'a.json', 'b.json'], ['importar', '--cat', CAT]):
            with self.subTest(argv=argv):
                self.assertEqual(self.rodar(argv, env={})[0], 2)
        self.nada_gravado()

    def test_subprocesso_com_o_secret_no_ambiente(self):
        """Script de verdade, sem rede: grava, não imprime o arquivo nem o Secret e deixa o Secret no ambiente."""
        caminho = self.arquivo(self.lote([no(productName=MARCA)]))
        prologo = ('import os, sys, io, http.client, urllib.error, urllib.request; sys.path.insert(0, %r)\n'
                   'import coletar_shopee as C\n'
                   'def morto(*a, **k): raise OSError("rede")\n'
                   'def conf(req, timeout=None):\n'
                   '    h = http.client.HTTPMessage(); h["Location"] = %r\n'
                   '    raise urllib.error.HTTPError(req.full_url, 302, "x", h, io.BytesIO(b""))\n'
                   'urllib.request.urlopen = morto; C.OPENER_API.open = morto; C.OPENER_CONFERENCIA.open = conf\n'
                   'C.ID_AFILIADO_SHOPEE = %r; C.BUSCAS = %r\n'
                   'sys.argv[1:] = ["importar", %r]\n'
                   'r = C.main()\n'
                   'assert os.environ.get("ACHADINHOS_SHOPEE_SECRET"), "o Secret sumiu do ambiente"\n'
                   'sys.exit(r)\n') % (RAIZ, DESTINO_BOM, ID, self.buscas, caminho)
        r = subprocess.run([sys.executable, '-c', prologo], env=dict(os.environ, **ENV), cwd=TMP,
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        for proibido in (SECRET, MARCA, LINK, 'Traceback'):
            self.assertNotIn(proibido, r.stdout + r.stderr)
        self.assertEqual([i['titulo'] for i in self.itens()], [MARCA])
        self.assertEqual(self.feitos(), [f'vendidos|{TERMO}'])


class TestIdDoDono(unittest.TestCase):
    """O ID de afiliado gravado no arquivo (sem mock) confere só o utm_source exato do dono."""
    def test_id_preenchido(self):
        self.assertEqual(ID_DO_ARQUIVO, '18328801339')

    def test_dono_ok_com_o_id_do_arquivo(self):
        with mock.patch.object(C, 'ID_AFILIADO_SHOPEE', ID_DO_ARQUIVO):
            self.assertTrue(C.dono_ok('https://shopee.com.br/Perfume-Floral-i.112233.22334455667'
                                      '?utm_source=an_18328801339&utm_medium=affiliates&utm_campaign=id_x'))
            for outro in ('an_18328801330', 'an_183288013390', 'an_18328801339x'):
                with self.subTest(utm=outro):
                    self.assertFalse(C.dono_ok(f'https://shopee.com.br/Perfume-i.1.2?utm_source={outro}'
                                               '&utm_medium=affiliates'))


if __name__ == '__main__':
    unittest.main()
