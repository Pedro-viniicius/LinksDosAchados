#!/usr/bin/env python3
"""Testes do atualizar_precos.py (docs/produto/planos/atualizar-precos.md, etapa 4: CA2, CA4, CA5, CA10 e CA11).

Uso:  python3 testes/test_atualizar_precos.py -v

ACHADINHOS_DB e os três arquivos de progresso (ACHADINHOS_FEITOS da coleta da Amazon,
ACHADINHOS_FEITOS_SHOPEE e ACHADINHOS_FEITOS_ATUALIZAR) apontam para um diretório temporário antes do
import. O buscas.json do teste também é temporário. `coletar_amazon.baixar`,
`servidor.buscar_produto_amazon`, `coletar_shopee.buscar` e `coletar_shopee.destino` são falsos, e os
openers de verdade (urlopen, OPENER_AMAZON, OPENER_API, OPENER_CONFERENCIA) levantam erro: nenhum teste
acessa a Amazon, a Shopee, o achadinhos.db real ou os arquivos de progresso reais. Qualquer saída
acidental para a rede bate num proxy morto. As credenciais são marcadores falsos.
"""
import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from unittest import mock

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix='teste-atualizar-precos-')
PROXIES = {v: 'http://127.0.0.1:9' for v in ('http_proxy', 'https_proxy', 'ftp_proxy')}
os.environ.update(PROXIES)
os.environ['no_proxy'] = ''
os.environ['ACHADINHOS_DB'] = os.path.join(TMP, 'achadinhos.db')
os.environ['ACHADINHOS_FEITOS'] = os.path.join(TMP, 'feitos-coleta-amazon.txt')
os.environ['ACHADINHOS_FEITOS_SHOPEE'] = os.path.join(TMP, 'feitos-coleta-shopee.txt')
os.environ['ACHADINHOS_FEITOS_ATUALIZAR'] = os.path.join(TMP, 'feitos-atualizar.txt')
for v in ('ACHADINHOS_SHOPEE_APP_ID', 'ACHADINHOS_SHOPEE_SECRET'):
    os.environ.pop(v, None)
sys.path.insert(0, RAIZ)

import atualizar_precos as A  # noqa: E402
import coletar_amazon as C  # noqa: E402
import coletar_shopee as CS  # noqa: E402
import servidor as S  # noqa: E402

assert all(os.path.dirname(p) == TMP for p in (S.DB, C.FEITOS, CS.FEITOS, A.FEITOS)), \
    'o teste não pode tocar os dados reais'

FIXTURE = os.path.join(RAIZ, 'testes', 'fixtures', 'amazon-busca.html')
with open(FIXTURE, encoding='utf-8') as _f:
    HTML = _f.read()
BUSCAS = {'Perfumes e Perfumaria': ['Perfume Floral', 'Perfume Amadeirado'], 'Cozinha': ['Panela']}
CAT = 'Perfumes e Perfumaria'
ANTIGO = '2026-01-10T08:00:00'
SECRET = 'SEGREDO-MARCADOR-c41d07'   # procurado em toda saída: nunca pode aparecer
APP_ID = '1800012345'
ID = '18001234567'
LINK_A = 'https://s.shopee.com.br/AbC123'      # link de afiliado já gravado
LINK_B = 'https://s.shopee.com.br/Novo456'     # link que a API devolve agora
DESTINO_BOM = f'https://shopee.com.br/product/1/2?utm_source=an_{ID}&utm_medium=affiliates'
DESTINO_RUIM = 'https://shopee.com.br/product/1/2?utm_source=an_99999999999&utm_medium=affiliates'
FOTO = 'https://down-br.img.susercontent.com/file/br-11134207-abc'
ENV_SHOPEE = {'ACHADINHOS_SHOPEE_APP_ID': APP_ID, 'ACHADINHOS_SHOPEE_SECRET': SECRET}


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


def hoje():
    return A.hoje() + 'T'


def pagina_so(*asins):
    """Página de busca só com os cards da fixture desses ASINs (na ordem da fixture)."""
    cards = re.findall(r'<div data-component-type="s-search-result" data-asin="([A-Z0-9]+)">.*?\n</div>', HTML, re.S)
    blocos = re.findall(r'(<div data-component-type="s-search-result" data-asin="[A-Z0-9]+">.*?\n</div>)', HTML, re.S)
    return ('<html><body><div class="s-main-slot">'
            + ''.join(b for a, b in zip(cards, blocos) if a in asins) + '</div></body></html>')


def http_erro(codigo):
    return urllib.error.HTTPError('https://www.amazon.com.br/x', codigo, 'erro', {}, io.BytesIO())


def rede_proibida(*a, **k):
    raise AssertionError('teste tentou acessar a rede')


class Base(unittest.TestCase):
    def setUp(self):
        for p in (S.DB, S.DB + '-wal', S.DB + '-shm', C.FEITOS, CS.FEITOS, A.FEITOS):
            if os.path.exists(p):
                os.remove(p)
        self.buscas = os.path.join(TMP, 'buscas.json')
        with open(self.buscas, 'w', encoding='utf-8') as f:
            json.dump(BUSCAS, f, ensure_ascii=False)
        self.pausas = []
        for alvo, nome, novo in (
                (A, 'BUSCAS', self.buscas),
                (urllib.request, 'urlopen', rede_proibida),
                (S.OPENER_AMAZON, 'open', rede_proibida),
                (CS.OPENER_API, 'open', rede_proibida),
                (CS.OPENER_CONFERENCIA, 'open', rede_proibida),
                (C, 'pausa', lambda a=4, b=8: self.pausas.append(('amazon', a, b))),
                (CS, 'pausa', lambda a=1, b=3: self.pausas.append(('shopee', a, b))),
                (CS, 'ID_AFILIADO_SHOPEE', ID)):
            p = mock.patch.object(alvo, nome, novo)
            p.start()
            self.addCleanup(p.stop)
        S.criar_banco()

    def inserir(self, loja, iid, busca, cat=CAT, preco='R$ 50,00', preco_em=ANTIGO, url=None, titulo='Item antigo'):
        url = url or (C.link_afiliado(iid) if loja == 'amazon' else LINK_A)
        con = S.conectar()
        try:
            con.execute('INSERT INTO items (loja,item_id,cat,busca,url,titulo,preco,tem_dados,posicao,'
                        'criado_em,atualizado_em,preco_em) VALUES (?,?,?,?,?,?,?,1,0,?,?,?)',
                        (loja, iid, cat, busca, url, titulo, preco, ANTIGO, ANTIGO, preco_em))
            con.commit()
        finally:
            con.close()

    def linha(self, iid):
        con = S.conectar()
        try:
            r = con.execute('SELECT * FROM items WHERE item_id=?', (iid,)).fetchone()
            return dict(r) if r else None
        finally:
            con.close()

    def todas(self):
        con = S.conectar()
        try:
            return {r['item_id']: dict(r) for r in con.execute('SELECT * FROM items')}
        finally:
            con.close()

    def progresso(self):
        if not os.path.exists(A.FEITOS):
            return []
        with open(A.FEITOS, encoding='utf-8') as f:
            return f.read().splitlines()

    def rodar(self, argv, env=None):
        """(código de saída, stdout, stderr) do main, com `env` só durante a chamada."""
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, env or {}), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                codigo = A.main(argv)
            except SystemExit as e:
                codigo = e.code
            self.secret_no_ambiente = os.environ.get('ACHADINHOS_SHOPEE_SECRET')
        return codigo, out.getvalue(), err.getvalue()


# ---------- Amazon pela busca (CA2, CA5) ----------
class TestAmazonBusca(Base):
    def setUp(self):
        super().setUp()
        for iid in ('B0ATUAL001', 'B0USADO002', 'B0PISO0003', 'B0SEMPR004'):
            self.inserir('amazon', iid, 'Perfume Floral')
        self.inserir('amazon', 'B0OUTRA006', 'Perfume Amadeirado')
        self.inserir('amazon', 'B0COZIN007', 'Panela', cat='Cozinha')
        self.baixados = []
        self.paginas = {}   # url -> html (o resto devolve a fixture inteira)

        def baixar(url):
            self.baixados.append(url)
            h = self.paginas.get(url, HTML)
            if isinstance(h, Exception):
                raise h
            return url, h
        p = mock.patch.object(C, 'baixar', baixar)
        p.start()
        self.addCleanup(p.stop)

    def test_atualiza_so_itens_existentes_que_passam_no_piso(self):
        antes = self.todas()
        codigo, out, err = self.rodar(['amazon', '--cat', CAT])
        self.assertEqual(codigo, 0, err)
        # uma página só: o B0OUTRA006 apareceu na busca do Floral, e o Amadeirado ficou sem pendente
        self.assertEqual(self.baixados, [C.url_busca('Perfume Floral')])
        depois = self.todas()
        a = depois['B0ATUAL001']
        self.assertEqual((a['preco'], a['preco_antigo'], a['desconto']), ('R$ 89,90', 'R$ 129,90', '-31%'))
        self.assertEqual(a['titulo'], 'Perfume Floral Feminino 100ml Eau de Parfum')
        self.assertTrue(a['preco_em'].startswith(hoje()))
        self.assertEqual(a['url'], antes['B0ATUAL001']['url'])
        self.assertEqual((a['cat'], a['busca']), (CAT, 'Perfume Floral'))
        self.assertEqual(depois['B0OUTRA006']['preco'], 'R$ 1.299,90')
        self.assertEqual(depois['B0OUTRA006']['busca'], 'Perfume Amadeirado')   # a busca não muda
        # usado, fora do piso e sem preço: a linha inteira fica igual (preço antigo e preco_em antigo)
        for iid in ('B0USADO002', 'B0PISO0003', 'B0SEMPR004', 'B0COZIN007'):
            self.assertEqual(depois[iid], antes[iid], iid)
        self.assertNotIn('B0NOVO0005', depois)   # nunca insere
        self.assertEqual(len(depois), len(antes))
        self.assertEqual(self.progresso(), [f'amazon|{A.hoje()}|relevancia|Perfume Floral'])
        self.assertFalse(os.path.exists(C.FEITOS), 'o lote não grava o progresso da coleta')
        self.assertIn('2 atualizados, 1 sem preço legível (dados mantidos), 1 fora do piso, 1 usados, '
                      '0 indisponíveis, 0 sumidos, 0 não vistos', out)
        for proibido in ('Feminino', 'Usado', 'http', 'amazon.com.br'):
            self.assertNotIn(proibido, out + err)

    def test_url_de_afiliado_gravada_nao_muda(self):
        url = f'https://www.amazon.com.br/dp/B0ATUAL001?tag={S.TAG_AMAZON}&th=1'
        con = S.conectar()
        con.execute("UPDATE items SET url=? WHERE item_id='B0ATUAL001'", (url,))
        con.commit()
        con.close()
        self.assertEqual(self.rodar(['amazon', '--cat', CAT])[0], 0)
        a = self.linha('B0ATUAL001')
        self.assertEqual(a['preco'], 'R$ 89,90')
        self.assertEqual(a['url'], url)

    def test_sem_cat_percorre_as_abas_e_pula_termo_sem_pendente(self):
        self.assertEqual(self.rodar(['amazon'])[0], 0)
        self.assertEqual(self.baixados, [C.url_busca('Perfume Floral'), C.url_busca('Panela')])
        self.assertEqual(self.pausas, [('amazon', 4, 8)])   # pausa entre as duas, não antes da primeira

    def test_usa_as_ordens_da_coleta_e_para_sem_pendente(self):
        with open(C.FEITOS, 'w', encoding='utf-8') as f:
            f.write('busca|Perfume Floral\nordem|caros|Perfume Floral\nordem|vendidos|Perfume Floral\n')
        self.paginas[C.url_busca('Perfume Floral')] = pagina_so('B0ATUAL001', 'B0NOVO0005')
        codigo, out, err = self.rodar(['amazon', '--cat', CAT])
        self.assertEqual(codigo, 0, err)
        # relevância deixou pendentes; vendidos viu todos (a fixture inteira); caros não é lido
        self.assertEqual(self.baixados, [C.url_busca('Perfume Floral'), C.url_busca('Perfume Floral', 'vendidos')])
        self.assertEqual(self.progresso(), [f'amazon|{A.hoje()}|relevancia|Perfume Floral',
                                            f'amazon|{A.hoje()}|vendidos|Perfume Floral'])

    def test_termo_coletado_so_em_outra_ordem_usa_essa_ordem(self):
        with open(C.FEITOS, 'w', encoding='utf-8') as f:
            f.write('ordem|avaliados|Perfume Floral\n')
        self.assertEqual(self.rodar(['amazon', '--cat', CAT])[0], 0)
        self.assertEqual(self.baixados, [C.url_busca('Perfume Floral', 'avaliados')])

    def test_item_confirmado_hoje_nao_e_selecionado(self):
        con = S.conectar()
        con.execute('UPDATE items SET preco_em=?', (A.hoje() + 'T07:00:00',))
        con.commit()
        con.close()
        codigo, out, _ = self.rodar(['amazon'])
        self.assertEqual(codigo, 0)
        self.assertEqual(self.baixados, [])
        self.assertIn('0 selecionados (6 já confirmados hoje ficaram de fora)', out)

    def test_captcha_para_com_3_salva_o_progresso_e_retoma(self):
        self.paginas[C.url_busca('Panela')] = C.Bloqueado(C.url_busca('Panela'))
        codigo, out, err = self.rodar(['amazon'])
        self.assertEqual(codigo, 3)
        self.assertIn('PAROU', err)
        self.assertNotIn('Panela', err)   # a mensagem não traz a url
        self.assertEqual(self.linha('B0ATUAL001')['preco'], 'R$ 89,90')   # a página anterior ficou gravada
        self.assertEqual(self.progresso(), [f'amazon|{A.hoje()}|relevancia|Perfume Floral'])
        self.assertIn('RESUMO amazon', out)
        # mesma data: retoma só o que faltou
        del self.paginas[C.url_busca('Panela')]
        self.baixados.clear()
        self.assertEqual(self.rodar(['amazon'])[0], 0)
        self.assertEqual(self.baixados, [C.url_busca('Panela')])

    def test_503_e_429_param_com_3(self):
        for codigo_http in (503, 429):
            with self.subTest(codigo_http):
                self.paginas[C.url_busca('Perfume Floral')] = http_erro(codigo_http)
                codigo, _, err = self.rodar(['amazon', '--cat', CAT])
                self.assertEqual(codigo, 3)
                self.assertIn('PAROU', err)
                self.assertEqual(self.progresso(), [])

    def test_outro_erro_http_sai_com_1_so_com_o_tipo(self):
        self.paginas[C.url_busca('Perfume Floral')] = http_erro(500)
        codigo, out, err = self.rodar(['amazon', '--cat', CAT])
        self.assertEqual(codigo, 1)
        self.assertEqual(err.strip(), 'ERRO: HTTPError')

    def test_pagina_vazia_tenta_tres_vezes_e_nao_marca(self):
        self.paginas[C.url_busca('Perfume Floral')] = pagina_so()
        codigo, out, _ = self.rodar(['amazon', '--cat', CAT])
        self.assertEqual(codigo, 0)
        self.assertEqual(self.baixados[:3], [C.url_busca('Perfume Floral')] * 3)
        self.assertEqual(self.pausas[:2], [('amazon', 8, 15)] * 2)
        self.assertNotIn(f'amazon|{A.hoje()}|relevancia|Perfume Floral', self.progresso())


# ---------- Amazon pela página do produto (--produtos, P4) ----------
class TestAmazonProdutos(Base):
    def setUp(self):
        super().setUp()
        self.inserir('amazon', 'B0PRODA001', 'Perfume Floral', preco_em=None,
                     url=f'https://www.amazon.com.br/dp/B0PRODA001?tag={S.TAG_AMAZON}&ref=banco')
        self.inserir('amazon', 'B0PRODB002', 'Perfume Floral', preco_em='2026-01-01T00:00:00')
        self.inserir('amazon', 'B0PRODC003', 'Perfume Floral', preco_em=ANTIGO)
        self.baixados, self.abertos, self.produtos = [], [], {}
        # a busca não traz nenhum dos itens: todos ficam não vistos
        p = mock.patch.object(C, 'baixar', lambda url: (self.baixados.append(url), (url, pagina_so('B0NOVO0005')))[1])
        p.start()
        self.addCleanup(p.stop)

        def buscar_produto(url):
            self.abertos.append(url)
            asin = re.search(r'/dp/([A-Z0-9]{10})', url).group(1)
            r = self.produtos.get(asin)
            if isinstance(r, Exception):
                raise r
            return r or self.produto(asin)
        p = mock.patch.object(S, 'buscar_produto_amazon', buscar_produto)
        p.start()
        self.addCleanup(p.stop)

    @staticmethod
    def produto(pedido, **k):
        base = {'url_final': f'https://www.amazon.com.br/dp/{pedido}', 'asin': pedido, 'captcha': False,
                'titulo': f'Produto {pedido}', 'preco': 'R$ 77,70', 'preco_antigo': '', 'desconto': '',
                'avaliacao': '4,7 de 5 estrelas', 'num_avaliacoes': '1.234 avaliações', 'vendas': '',
                'cupom': '', 'frete': '', 'imagem': ''}
        base.update(k)
        return base

    def test_produtos_0_e_o_padrao_e_nao_abre_pagina(self):
        for argv in (['amazon', '--cat', CAT], ['amazon', '--cat', CAT, '--produtos', '0']):
            with self.subTest(argv):
                codigo, out, _ = self.rodar(argv)
                self.assertEqual(codigo, 0)
                self.assertEqual(self.abertos, [])
                self.assertIn('3 não vistos', out)
                self.assertIn('Não vistos (até 20): B0PRODA001, B0PRODB002, B0PRODC003', out)

    def test_abre_os_mais_velhos_primeiro_com_url_montada_pelo_asin(self):
        codigo, out, err = self.rodar(['amazon', '--cat', CAT, '--produtos', '2'])
        self.assertEqual(codigo, 0, err)
        # NULL é o mais velho; a url é a do link_afiliado, não a gravada no banco (que tem &ref=banco)
        self.assertEqual(self.abertos, [C.link_afiliado('B0PRODA001'), C.link_afiliado('B0PRODB002')])
        for iid in ('B0PRODA001', 'B0PRODB002'):
            l = self.linha(iid)
            self.assertEqual(l['preco'], 'R$ 77,70')
            self.assertTrue(l['preco_em'].startswith(hoje()))
        self.assertEqual(self.linha('B0PRODA001')['url'], f'https://www.amazon.com.br/dp/B0PRODA001?tag={S.TAG_AMAZON}&ref=banco')
        self.assertEqual(self.linha('B0PRODC003')['preco_em'], ANTIGO)
        self.assertEqual(self.pausas, [('amazon', 4, 8)] * 2)   # busca -> produto -> produto
        self.assertEqual(self.progresso()[-2:], [f'amazon|{A.hoje()}|produto|B0PRODA001',
                                                 f'amazon|{A.hoje()}|produto|B0PRODB002'])
        self.assertIn('1 não vistos', out)

    def test_nao_abre_item_dentro_da_validade(self):
        con = S.conectar()
        con.execute("INSERT INTO config VALUES ('preco_validade_horas', '168')")
        recente = (datetime.now() - timedelta(days=3)).isoformat(timespec='seconds')
        con.execute("UPDATE items SET preco_em=? WHERE item_id='B0PRODA001'", (recente,))
        con.commit()
        con.close()
        self.assertEqual(self.rodar(['amazon', '--cat', CAT, '--produtos', '5'])[0], 0)
        self.assertEqual(self.abertos, [C.link_afiliado('B0PRODB002'), C.link_afiliado('B0PRODC003')])

    def test_captcha_e_503_no_produto_param_com_3(self):
        for erro in ({'captcha': True}, http_erro(503), http_erro(429)):
            with self.subTest(erro):
                if os.path.exists(A.FEITOS):
                    os.remove(A.FEITOS)
                con = S.conectar()   # o subteste anterior atualizou o B0PRODA001 hoje
                con.execute("UPDATE items SET preco_em=NULL WHERE item_id='B0PRODA001'")
                con.commit()
                con.close()
                self.abertos.clear()
                self.produtos = {'B0PRODB002': erro if isinstance(erro, Exception) else self.produto('B0PRODB002', **erro)}
                codigo, _, err = self.rodar(['amazon', '--cat', CAT, '--produtos', '3'])
                self.assertEqual(codigo, 3)
                self.assertIn('PAROU', err)
                self.assertEqual(len(self.abertos), 2)   # o terceiro não é aberto
                self.assertIn(f'amazon|{A.hoje()}|produto|B0PRODA001', self.progresso())
                self.assertNotIn(f'amazon|{A.hoje()}|produto|B0PRODB002', self.progresso())
                self.assertEqual(self.linha('B0PRODB002')['preco_em'], '2026-01-01T00:00:00')

    def test_sumiu_usado_e_fora_do_piso_nao_gravam(self):
        self.produtos = {'B0PRODA001': http_erro(404),
                         'B0PRODB002': self.produto('B0PRODB002', asin='B0OUTRO999'),   # redirecionou para outro
                         'B0PRODC003': self.produto('B0PRODC003', titulo='Perfume Recondicionado')}
        antes = self.todas()
        codigo, out, _ = self.rodar(['amazon', '--cat', CAT, '--produtos', '3'])
        self.assertEqual(codigo, 0)
        self.assertEqual(self.todas(), antes)
        self.assertIn('0 atualizados', out)
        self.assertIn('1 usados, 0 indisponíveis, 2 sumidos, 0 não vistos', out)
        self.produtos = {'B0PRODA001': self.produto('B0PRODA001', avaliacao='4,4 de 5 estrelas')}
        os.remove(A.FEITOS)
        codigo, out, _ = self.rodar(['amazon', '--cat', CAT, '--produtos', '1'])
        self.assertIn('1 fora do piso', out)
        self.assertEqual(self.todas(), antes)

    def test_produto_sem_preco_mantem_os_dados(self):
        self.produtos = {'B0PRODA001': self.produto('B0PRODA001', preco='')}
        antes = self.linha('B0PRODA001')
        self.assertEqual(self.rodar(['amazon', '--cat', CAT, '--produtos', '1'])[0], 0)
        self.assertEqual(self.linha('B0PRODA001'), antes)


# ---------- ponto de troca (CA10) ----------
class TestFonteFalsa(Base):
    def setUp(self):
        super().setUp()
        self.inserir('amazon', 'B0FALSA001', 'Perfume Floral')
        self.inserir('amazon', 'B0FALSA002', 'Perfume Floral')
        self.inserir('amazon', 'B0FALSA003', 'Perfume Floral')
        self.inserir('amazon', 'B0HOJE0004', 'Perfume Floral', preco_em=A.hoje() + 'T06:00:00')
        self.inserir('amazon', 'B0GERAL005', 'x', cat='Geral')               # aba fora do buscas.json
        self.inserir('amazon', 'https://amzn.to/abc', 'x')                    # id fora do formato
        self.inserir('ml', 'MLB123', 'Perfume Floral', url='https://meli.la/abc')
        self.recebido = {}

    def com_fonte(self, *paginas, efeito=None):
        def falsa(itens, opcoes):
            self.recebido = {'itens': itens, 'opcoes': opcoes}
            for rotulo, obs in paginas:
                if efeito:
                    efeito()
                yield rotulo, obs
        p = mock.patch.dict(A.FONTES, {'amazon': falsa})
        p.start()
        self.addCleanup(p.stop)

    @staticmethod
    def ok(iid, preco='R$ 12,34', loja='amazon'):
        return A.Observacao(iid, 'ok', {'loja': loja, 'item_id': iid, 'cat': CAT, 'busca': 'Perfume Floral',
                                        'url': C.link_afiliado(iid) if loja == 'amazon' else 'https://meli.la/x',
                                        'data': {'titulo': 'Novo título', 'preco': preco}})

    def test_encaixe_sem_rede(self):
        self.com_fonte(('teste|um', [self.ok('B0FALSA001'), self.ok('B0NAOEXIS9'),
                                     A.Observacao('B0FALSA002', 'sumiu', None),
                                     A.Observacao('B0FALSA003', 'indisponivel', None)]))
        codigo, out, err = self.rodar(['amazon', '--produtos', '7'])
        self.assertEqual(codigo, 0, err)
        self.assertEqual(set(self.recebido['itens']), {'B0FALSA001', 'B0FALSA002', 'B0FALSA003'})
        # a fonte não recebe a url do banco: a página do produto sai do link montado pelo ASIN
        self.assertTrue(all('url' not in l for l in self.recebido['itens'].values()))
        o = self.recebido['opcoes']
        self.assertEqual((o['produtos'], o['validade'], o['feitos'], o['buscas']), (7, 24, set(), BUSCAS))
        self.assertEqual(self.linha('B0FALSA001')['preco'], 'R$ 12,34')
        self.assertIsNone(self.linha('B0NAOEXIS9'))
        self.assertEqual(self.linha('B0FALSA002')['preco_em'], ANTIGO)
        self.assertEqual(self.progresso(), [f'amazon|{A.hoje()}|teste|um'])
        self.assertIn('RESUMO amazon: 3 selecionados (1 já confirmados hoje ficaram de fora); 1 atualizados, '
                      '0 sem preço legível (dados mantidos), 0 fora do piso, 0 usados, 1 indisponíveis, '
                      '1 sumidos, 0 não vistos.', out)

    def test_q3_ja_confirmado_hoje_usa_o_parse_estrito_da_trava(self):
        ontem = (datetime.fromisoformat(A.hoje()) - timedelta(days=1)).date().isoformat()
        # relógio fixo ao meio-dia de hoje: a folga de 5 min no futuro (R4) não pode depender da hora do teste
        meio_dia = datetime.fromisoformat(A.hoje() + 'T12:00:00')
        relogio = type('Relogio', (datetime,), {'now': classmethod(lambda cls, tz=None: meio_dia)})
        casos = {A.hoje() + 'T06:00:00': False, A.hoje() + 'T00:00:00': False,
                 A.hoje() + 'T12:05:00': False,   # 5 min à frente: dentro da folga
                 A.hoje() + 'T12:05:01': True, A.hoje() + 'T23:59:59': True,   # futuro além da folga é velho (R4)
                 A.hoje() + 'Tlixo': True, A.hoje() + 'T99:99:99': True, A.hoje() + 'T07:00:00Z': True,
                 A.hoje() + 'T07:00:00.5': True, A.hoje() + 'T24:00:00': True,
                 ontem + 'T24:00:00': True,   # o fromisoformat leria como hoje à meia-noite
                 ontem + 'T23:59:59': True, A.hoje(): True, '': True, None: True}
        for valor, selecionado in casos.items():
            with self.subTest(preco_em=valor):
                con = S.conectar()
                try:
                    con.execute("UPDATE items SET preco_em=? WHERE item_id='B0HOJE0004'", (valor,))
                    con.commit()
                    with mock.patch.object(A, 'datetime', relogio):
                        itens, ja = A.selecionar(con, 'amazon', [CAT], A.hoje())
                finally:
                    con.close()
                self.assertEqual('B0HOJE0004' in itens, selecionado)
                self.assertEqual(ja, 0 if selecionado else 1)

    def test_item_excluido_no_meio_do_lote_nao_e_reinserido(self):
        def excluir():
            con = S.conectar()
            con.execute("DELETE FROM items WHERE item_id='B0FALSA001'")
            con.commit()
            con.close()
        self.com_fonte(('teste|um', [self.ok('B0FALSA001')]), efeito=excluir)
        codigo, out, _ = self.rodar(['amazon'])
        self.assertEqual(codigo, 0)
        self.assertIsNone(self.linha('B0FALSA001'))
        self.assertIn('1 sumidos', out)

    def test_ok_sem_preco_legivel_nao_vai_ao_upsert(self):
        for preco in ('', 'R$ 10 - R$ 20', 'Indisponível'):
            with self.subTest(preco):
                antes = self.linha('B0FALSA001')
                self.com_fonte(('teste|um', [self.ok('B0FALSA001', preco=preco)]))
                with mock.patch.object(S, 'upsert', side_effect=AssertionError('não podia gravar')):
                    codigo, out, _ = self.rodar(['amazon'])
                self.assertEqual(codigo, 0)
                self.assertEqual(self.linha('B0FALSA001'), antes)
                self.assertIn('1 sem preço legível', out)
                os.remove(A.FEITOS)

    def test_ok_sem_titulo_conta_como_indisponivel(self):
        obs = self.ok('B0FALSA001')
        obs.it['data']['titulo'] = ''
        antes = self.linha('B0FALSA001')
        self.com_fonte(('teste|um', [obs]))
        codigo, out, _ = self.rodar(['amazon'])
        self.assertEqual(codigo, 0)
        self.assertEqual(self.linha('B0FALSA001'), antes)
        self.assertIn('0 atualizados', out)
        self.assertIn('1 indisponíveis', out)

    def test_primeira_observacao_atualizada_nao_e_sobrescrita(self):
        self.com_fonte(('a|1', [self.ok('B0FALSA001', 'R$ 1,00')]),
                       ('a|2', [self.ok('B0FALSA001', 'R$ 2,00'), A.Observacao('B0FALSA001', 'usado', None)]))
        codigo, out, _ = self.rodar(['amazon'])
        self.assertEqual(self.linha('B0FALSA001')['preco'], 'R$ 1,00')
        self.assertIn('1 atualizados', out)
        self.assertIn('0 usados', out)

    def test_item_de_outra_loja_e_recusado(self):
        self.com_fonte(('teste|um', [self.ok('B0FALSA002'), self.ok('B0FALSA001', loja='ml')]))
        antes = self.todas()
        codigo, _, err = self.rodar(['amazon'])
        self.assertEqual(codigo, 1)
        self.assertEqual(err.strip(), 'ERRO: ValueError')
        self.assertEqual(self.todas(), antes)   # a página inteira volta (sem commit)
        self.assertEqual(self.progresso(), [])

    def test_resumo_lista_ate_20_ids_e_nenhum_titulo(self):
        for n in range(25):
            self.inserir('amazon', f'B0MUITO{n:03d}', 'Perfume Floral', titulo=f'Titulo secreto {n}')
        self.com_fonte()
        codigo, out, _ = self.rodar(['amazon'])
        linha = [l for l in out.splitlines() if l.startswith('Não vistos')][0]
        self.assertEqual(len(linha.split(': ', 1)[1].split(', ')), 20)
        self.assertIn('28 não vistos', out)
        self.assertNotIn('Titulo secreto', out)
        self.assertNotIn('http', out)

    def test_fontes_tem_as_duas_lojas(self):
        self.assertEqual(A.FONTES, {'amazon': A.fonte_amazon_busca, 'shopee': A.fonte_shopee_api})


# ---------- Shopee pela Open API (CA4, CA5) ----------
def no(item, **k):
    base = {'itemId': item, 'shopId': 112233, 'productName': 'Perfume Floral 100ml', 'priceMin': '1234.5',
            'priceDiscountRate': 20, 'ratingStar': '4.8', 'sales': 1234, 'imageUrl': FOTO, 'offerLink': LINK_B}
    base.update(k)
    return base


class TestShopee(Base):
    def setUp(self):
        super().setUp()
        for n in (1001, 1002, 1003, 1004, 1005):
            self.inserir('shopee', f'112233.{n}', 'Perfume Floral')
        self.nos = [no(1001), no(1002, productName='Perfume Floral Seminovo'), no(1003, ratingStar='4.2'),
                    no(1004, priceMin=None), no(1005, offerLink='https://shopee.com.br/produto-1005'), no(9999)]
        self.chamadas, self.destinos = [], []
        self.destino = DESTINO_BOM

        def buscar(cred, termo, ordem):
            self.chamadas.append((termo, ordem))
            self.assertEqual(cred[1].valor(), SECRET)
            if isinstance(self.nos, Exception):
                raise self.nos
            return self.nos

        def destino(link):
            self.destinos.append((link, self.linha('112233.1001')['preco']))
            return self.destino
        for nome, novo in (('buscar', buscar), ('destino', destino)):
            p = mock.patch.object(CS, nome, novo)
            p.start()
            self.addCleanup(p.stop)

    def test_atualiza_com_o_dono_conferido_antes_e_tira_o_secret_do_ambiente(self):
        antes = self.todas()
        codigo, out, err = self.rodar(['shopee', '--cat', CAT], ENV_SHOPEE)
        self.assertEqual(codigo, 0, err)
        self.assertIsNone(self.secret_no_ambiente)   # pop
        self.assertEqual(self.chamadas, [('Perfume Floral', 'relevancia')])
        self.assertEqual(self.destinos, [(LINK_B, 'R$ 50,00')])   # conferido antes de gravar
        a = self.linha('112233.1001')
        self.assertEqual((a['preco'], a['desconto']), ('R$ 1.234,50', '-20%'))
        self.assertTrue(a['preco_em'].startswith(hoje()))
        self.assertEqual(a['url'], LINK_A)   # o link de afiliado gravado não muda
        depois = self.todas()
        for iid in ('112233.1002', '112233.1003', '112233.1004', '112233.1005'):
            self.assertEqual(depois[iid], antes[iid], iid)
        self.assertNotIn('112233.9999', depois)
        self.assertEqual(self.progresso(), [f'shopee|{A.hoje()}|relevancia|Perfume Floral'])
        self.assertIn('1 atualizados, 1 sem preço legível (dados mantidos), 1 fora do piso, 1 usados, '
                      '1 indisponíveis, 0 sumidos, 0 não vistos', out)
        self.assertNotIn(SECRET, out + err)
        self.assertNotIn('http', out + err)

    def test_secret_ausente_sai_com_2_sem_chamar_a_api(self):
        for env in ({'ACHADINHOS_SHOPEE_APP_ID': APP_ID}, {'ACHADINHOS_SHOPEE_SECRET': SECRET},
                    {'ACHADINHOS_SHOPEE_APP_ID': 'id com espaço', 'ACHADINHOS_SHOPEE_SECRET': SECRET}):
            with self.subTest(sorted(env)):
                antes = self.todas()
                codigo, out, err = self.rodar(['shopee', '--cat', CAT], env)
                self.assertEqual(codigo, 2)
                self.assertIn('ACHADINHOS_SHOPEE_SECRET', err)
                self.assertNotIn(SECRET, out + err)
                self.assertEqual(self.chamadas, [])
                self.assertEqual(self.todas(), antes)

    def test_sem_id_de_afiliado_sai_com_2(self):
        with mock.patch.object(CS, 'ID_AFILIADO_SHOPEE', ''):
            codigo, _, err = self.rodar(['shopee', '--cat', CAT], ENV_SHOPEE)
        self.assertEqual(codigo, 2)
        self.assertEqual(self.chamadas, [])

    def test_dono_errado_nada_e_gravado(self):
        self.destino = DESTINO_RUIM
        antes = self.todas()
        codigo, out, err = self.rodar(['shopee', '--cat', CAT], ENV_SHOPEE)
        self.assertEqual(codigo, 1)
        self.assertIn('Nada foi gravado', err)
        self.assertEqual(self.todas(), antes)
        self.assertEqual(self.progresso(), [])

    def test_limite_da_api_sai_com_3(self):
        self.nos = CS.LimiteAtingido()
        codigo, out, err = self.rodar(['shopee', '--cat', CAT], ENV_SHOPEE)
        self.assertEqual(codigo, 3)
        self.assertIn('PAROU', err)
        self.assertIn('RESUMO shopee', out)

    def test_erro_da_api_e_resposta_invalida_saem_com_1(self):
        for erro, texto in ((CS.ErroApi(10020, 400), 'código 10020, HTTP 400'), (CS.RespostaInvalida(), 'fora do formato')):
            with self.subTest(texto):
                self.nos = erro
                codigo, _, err = self.rodar(['shopee', '--cat', CAT], ENV_SHOPEE)
                self.assertEqual(codigo, 1)
                self.assertIn(texto, err)

    def test_secret_nunca_sai_nem_em_excecao(self):
        self.nos = RuntimeError(f'falhou com {SECRET}')
        codigo, out, err = self.rodar(['shopee', '--cat', CAT], ENV_SHOPEE)
        self.assertEqual(codigo, 1)
        self.assertEqual(err.strip(), 'ERRO: RuntimeError')
        self.assertNotIn(SECRET, out + err)

    def test_usa_as_ordens_da_coleta_da_shopee(self):
        with open(CS.FEITOS, 'w', encoding='utf-8') as f:
            f.write('vendidos|Perfume Floral\ncaros|Perfume Floral\n')
        self.nos = [no(1001)]
        self.assertEqual(self.rodar(['shopee', '--cat', CAT], ENV_SHOPEE)[0], 0)
        # vendidos deixou pendentes; caros também é lido; o termo seguinte não tem item
        self.assertEqual(self.chamadas, [('Perfume Floral', 'vendidos'), ('Perfume Floral', 'caros')])
        self.assertEqual(self.destinos, [(LINK_B, 'R$ 50,00')])   # uma conferência só
        self.assertEqual(self.pausas, [('shopee', 1, 3)])

    def test_amazon_nao_le_o_secret(self):
        with mock.patch.object(C, 'baixar', side_effect=AssertionError('sem item da Amazon, sem busca')):
            codigo, _, _ = self.rodar(['amazon'], ENV_SHOPEE)
        self.assertEqual(codigo, 0)
        self.assertEqual(self.secret_no_ambiente, SECRET)   # ninguém fez pop


# ---------- argumentos (saída 2) ----------
class TestArgumentos(Base):
    def test_argumentos_invalidos_saem_com_2(self):
        for argv in (['amazon', '--produtos', '501'], ['amazon', '--produtos', '-1'], ['amazon', '--produtos', 'abc'],
                     ['amazon', '--produtos', '١'], ['amazon', '--cat', 'Aba que não existe'], ['shopee'],
                     ['shopee', '--cat', CAT, '--produtos', '1'], ['ml'], []):
            with self.subTest(argv):
                codigo, out, err = self.rodar(argv)
                self.assertEqual(codigo, 2)

    def test_limites_do_produtos(self):
        self.assertEqual(A.ler_argumentos(['amazon', '--produtos', '500']).produtos, 500)
        self.assertEqual(A.ler_argumentos(['amazon']).produtos, 0)

    def test_cat_em_nfd_vale(self):
        import unicodedata
        a = A.ler_argumentos(['amazon', '--cat', unicodedata.normalize('NFD', 'Cozinha')])
        self.assertEqual(a.abas, {'Cozinha': ['Panela']})


# ---------- como script (CA4, CA11) ----------
class TestScript(unittest.TestCase):
    def env(self, **extra):
        env = {k: v for k, v in os.environ.items() if not k.startswith('ACHADINHOS_')}
        self.db = os.path.join(TMP, f'script-{self._testMethodName}.db')
        env.update(PROXIES, no_proxy='', PYTHONPATH=RAIZ, ACHADINHOS_DB=self.db,
                   ACHADINHOS_FEITOS=os.path.join(TMP, 'script-coleta.txt'),
                   ACHADINHOS_FEITOS_SHOPEE=os.path.join(TMP, 'script-shopee.txt'),
                   ACHADINHOS_FEITOS_ATUALIZAR=os.path.join(TMP, 'script-atualizar.txt'), **extra)
        return env

    def test_sem_secret_sai_com_2(self):
        r = subprocess.run([sys.executable, os.path.join(RAIZ, 'atualizar_precos.py'), 'shopee', '--cat', CAT],
                           env=self.env(ACHADINHOS_SHOPEE_APP_ID=APP_ID), capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertNotIn('Traceback', r.stderr)
        self.assertFalse(os.path.exists(self.db))   # para antes de criar o banco

    def test_secret_nao_vaza_numa_excecao_de_rede(self):
        with open(os.path.join(RAIZ, 'buscas.json'), encoding='utf-8') as f:
            termo = json.load(f)[CAT][0]
        codigo = f'''
import sys, urllib.request
import servidor as S, coletar_shopee as CS, atualizar_precos as A
def falha(*a, **k):
    raise OSError({SECRET!r})
urllib.request.urlopen = CS.OPENER_API.open = CS.OPENER_CONFERENCIA.open = S.OPENER_AMAZON.open = falha
S.criar_banco()
con = S.conectar()
con.execute("INSERT INTO items (loja,item_id,cat,busca,url,titulo,preco,tem_dados) VALUES ('shopee','1.2',?,?,?,'t','R$ 1,00',1)",
            ({CAT!r}, {termo!r}, {LINK_A!r}))
con.commit(); con.close()
sys.exit(A.main(['shopee', '--cat', {CAT!r}]))
'''
        r = subprocess.run([sys.executable, '-c', codigo], cwd=TMP, capture_output=True, text=True, timeout=60,
                           env=self.env(ACHADINHOS_SHOPEE_APP_ID=APP_ID, ACHADINHOS_SHOPEE_SECRET=SECRET))
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertEqual(r.stderr.strip(), 'ERRO: OSError')
        self.assertNotIn(SECRET, r.stdout + r.stderr)
        self.assertNotIn('Traceback', r.stderr)

    def test_progresso_padrao_e_arquivo_proprio(self):
        env = self.env()
        del env['ACHADINHOS_FEITOS_ATUALIZAR']
        r = subprocess.run([sys.executable, '-c', 'import atualizar_precos as A; print(A.FEITOS)'],
                           cwd=TMP, env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.stdout.strip(), os.path.join(RAIZ, 'atualizar_precos_feitos.txt'))


if __name__ == '__main__':
    unittest.main()
