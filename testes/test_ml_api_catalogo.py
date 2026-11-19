#!/usr/bin/env python3
"""Testes do `ml_api.py sondar --catalogo` (docs/produto/planos/api-oficial-ml-catalogo.md, etapa 1: CA1, CA2, CA6)
e do vínculo anúncio → produto com o arquivo de vínculos e as ofertas por produto (etapa 2: CA3, CA6).

Uso:  python3 testes/test_ml_api_catalogo.py -v

Nenhum teste fala com o Mercado Livre: o catálogo é um ML falso (MLFalso) atrás do OpenerFalso do
test_ml_api.py, e qualquer saída acidental bate no proxy morto que aquele módulo fixa no import. O banco é
temporário (servidor.criar_banco numa pasta própria) e traz títulos e preços-marcador, procurados em toda saída.
O arquivo de vínculos padrão (ACHADINHOS_ML_CATALOGO) também aponta para a pasta temporária.
"""
import collections
import contextlib
import io
import json
import os
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_ml_api as T   # noqa: E402  (fixa proxies, ACHADINHOS_ML_TOKENS e ACHADINHOS_DB temporários)

M = T.M
RAIZ = T.RAIZ
import servidor as S   # noqa: E402  (só para criar o banco temporário e conferir o ler_preco)

assert os.path.dirname(S.DB) == T.TMP, 'o teste não pode tocar o banco real'
# o ml_api já foi importado pelo test_ml_api: o caminho padrão dos vínculos é trocado aqui também
os.environ['ACHADINHOS_ML_CATALOGO'] = os.path.join(T.TMP, 'catalogo-padrao.json')
M.CATALOGO = os.environ['ACHADINHOS_ML_CATALOGO']
assert os.path.dirname(M.CATALOGO) == T.TMP, 'o teste não pode tocar o ml_catalogo.json real'

ABAS = {'Celulares e Informática': ['iPhone 17', 'Notebook', 'Monitor'],
        'Perfumes e Perfumaria': ['Perfume feminino', 'Perfume masculino', 'Body splash'],
        'Casa e Cozinha': ['Air fryer']}
TERMOS = [t for lista in ABAS.values() for t in lista]


def tearDownModule():
    T.tearDownModule()


def preco_br(v):
    """98765.43 → 'R$ 98.765,43' (como o console grava)."""
    return M.formatar_preco(v)


def titulo(n):
    return f'TITULO-MARCADOR-{n:03d} Perfume Ação Nº{n}, 100ml!'


def prod(pid, bbw_item=None, preco=None, moeda='BRL', status='active', filhos=None, categoria=None, nulo=False,
         condicao='new', **extra):
    """Produto de catálogo falso. bbw_item: item_id do buy_box_winner; nulo: buy_box_winner null."""
    p = {'id': pid, 'name': 'NOME-PRODUTO-MARCADOR', 'status': status, 'permalink': f'https://x/p/{pid}',
         'pictures': [{'id': '123456-MLA1234567890_012026', 'url': 'https://http2.mlstatic.com/MARCADOR.jpg'}],
         'children_ids': filhos or []}
    if nulo:
        p['buy_box_winner'] = None
    elif bbw_item is not None:
        p['buy_box_winner'] = {'item_id': bbw_item, 'price': preco, 'original_price': None, 'currency_id': moeda,
                               'condition': condicao, 'shipping': {'free_shipping': True}, 'seller_id': 55555}
    if categoria is not None:
        p['category_id'] = categoria
    p.update(extra)
    return p


class MLFalso:
    """Catálogo falso. buscas: q → lista de resultados; produtos: pid → dict; listas: pid → [páginas de linhas];
    erros: prefixo de caminho → (status, corpo); outros: prefixo → dict. Erro é um HTTPError novo a cada chamada."""

    def __init__(self):
        self.buscas, self.produtos, self.listas, self.erros, self.outros = {}, {}, {}, {}, {}
        self.op = T.OpenerFalso(T.api_padrao(gets=self.responder))

    def responder(self, c):
        for prefixo, erro in self.erros.items():
            if c.caminho.startswith(prefixo):
                return T.erro_http(*erro)
        if c.caminho == '/products/search':
            v = self.buscas.get(c.query.get('q'), [])
            return T.erro_http(*v) if isinstance(v, tuple) else {'results': v, 'paging': {'total': len(v),
                                                                                         'limit': 50}}
        m = re.fullmatch(r'/products/(MLB[0-9]+)/items', c.caminho)
        if m:
            paginas = self.listas.get(m.group(1))
            if paginas is None:
                return T.erro_http(404, {'error': 'not_found'})
            if isinstance(paginas, tuple):
                return T.erro_http(*paginas)
            offset, inicio = int(c.query.get('offset', '0')), 0
            total = sum(len(p) for p in paginas)
            for pagina in paginas:
                if inicio == offset:
                    return {'results': pagina, 'paging': {'total': total, 'offset': offset, 'limit': len(pagina)}}
                inicio += len(pagina)
            return {'results': [], 'paging': {'total': total, 'offset': offset, 'limit': 0}}
        m = re.fullmatch(r'/products/(MLB[0-9]+)', c.caminho)
        if m:
            v = self.produtos.get(m.group(1))
            return T.erro_http(404, {'error': 'not_found'}) if v is None else v
        for prefixo, v in self.outros.items():
            if c.caminho.startswith(prefixo):
                return v
        return T.erro_http(404, {'error': 'not_found'})

    def q(self, n):
        return M.consulta_do_titulo(titulo(n))

    def gets(self, caminho=None, prefixo=None):
        return [c for c in self.op.gets() if (caminho is None or c.caminho == caminho)
                and (prefixo is None or c.caminho.startswith(prefixo))]


def linha_lista(item_id, preco, moeda='BRL'):
    return {'item_id': item_id, 'price': preco, 'original_price': None, 'currency_id': moeda, 'condition': 'new',
            'seller_id': 77777, 'title': 'TITULO-LISTA-MARCADOR'}


class Catalogo(T.Cli):
    def setUp(self):
        super().setUp()
        self.buscas = os.path.join(self.dir, 'buscas.json')
        with open(self.buscas, 'w', encoding='utf-8') as f:
            json.dump(ABAS, f, ensure_ascii=False)
        self.pasta_db = tempfile.mkdtemp(dir=self.dir)
        self.db = os.path.join(self.pasta_db, 'achadinhos.db')
        self.agora_real = time.time()

    def banco(self, itens, modo='wal'):
        """itens: [(n, cat, preco_float|texto|None, preco_em|None)] → item ml MLB<9000000000+n>."""
        with mock.patch.object(S, 'DB', self.db):
            S.criar_banco()
        con = sqlite3.connect(self.db)
        for n, cat, preco, preco_em in itens:
            texto = preco_br(preco) if isinstance(preco, float) else (preco or '')
            con.execute('INSERT INTO items (loja, item_id, cat, busca, url, titulo, preco, tem_dados, preco_em) '
                        "VALUES ('ml', ?, ?, '', 'https://meli.la/x', ?, ?, 1, ?)",
                        (self.mlb(n), cat, titulo(n), texto, preco_em))
        con.execute("INSERT INTO items (loja, item_id, cat, url, titulo, preco) VALUES ('amazon', 'B0AAAAAAAA', "
                    "'Casa e Cozinha', 'https://www.amazon.com.br/dp/B0AAAAAAAA?tag=desejodemen01-20', "
                    "'TITULO-AMAZON-MARCADOR', 'R$ 1,00')")
        con.commit()
        if modo == 'delete':
            con.execute('PRAGMA journal_mode=DELETE')
        con.close()
        return self.db

    @staticmethod
    def mlb(n):
        return f'MLB{9000000000 + n}'

    def recente(self, horas=1):
        return time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(self.agora_real - horas * 3600))

    def rodar_cat(self, argv, ml, secret=None):
        with mock.patch.object(M, 'PAUSA_MIN', 0.0), mock.patch.object(M, 'PAUSA_MAX', 0.0), \
                mock.patch.object(M, 'BUSCAS', self.buscas):
            return self.rodar(argv, ml.op, secret=secret, db=self.db)

    def direto(self, ml, **kw):
        """sondar_catalogo no mesmo processo, com a Sessao do Base (relógio e dormir falsos)."""
        self.gravar()
        sessao = self.sessao(ml.op)
        out = io.StringIO()
        kw.setdefault('buscas', self.buscas)
        kw.setdefault('agora', self.agora_real)
        with contextlib.redirect_stdout(out):
            codigo = M.sondar_catalogo(sessao, self.db, **kw)
        return codigo, out.getvalue()

    def assertSemTituloNemPreco(self, texto, precos=()):
        self.assertNotIn('MARCADOR', texto.upper())
        for nome in ('perfume acao', 'Ação', 'NOME-PRODUTO', 'mlstatic', '55555', '77777'):
            self.assertNotIn(nome, texto)
        for v in precos:
            centavos = f'{v:.2f}'
            inteiro = centavos.split('.')[0]
            for forma in (preco_br(v), centavos, centavos.replace('.', ','), inteiro,
                          f'{int(v):,}'.replace(',', '.')):
                self.assertNotIn(forma, texto, forma)
        T.sem_marcadores(self, texto)


# ---------- funções puras ----------
class TestFuncoes(unittest.TestCase):
    def test_consulta_do_titulo(self):
        self.assertEqual(M.consulta_do_titulo('Perfume Ação Nº5, 100ml! Coração—Pêssego'),
                         'perfume acao no5 100ml coracao pessego')
        doze = ' '.join(f'p{i}' for i in range(20))
        self.assertEqual(M.consulta_do_titulo(doze), ' '.join(f'p{i}' for i in range(12)))
        self.assertEqual(M.consulta_do_titulo('  ...  '), '')
        self.assertEqual(M.consulta_do_titulo('Smart TV 55" 4K (LG) / Wi‑Fi'), 'smart tv 55 4k lg wi fi')
        for ruim in (None, 123, b'x', ['a']):
            self.assertEqual(M.consulta_do_titulo(ruim), '')

    def test_ler_preco_igual_ao_do_servidor(self):
        casos = ['R$ 1.299,90', 'R$ 4.285', 'R$ 69,90', '69.9', '69.90', '1.000', '1.000.000', 'R$ 0', '0,00', '',
                 None, True, 'R$ 10 - R$ 20', 'abc', '12,5', 'R$ 1.234,56', '1.23.4', '٣٤', 12, 12.5]
        for c in casos:
            self.assertEqual(M.ler_preco(c), S.ler_preco(c), repr(c))

    def test_faixa_de_preco(self):
        D = M.decimal.Decimal
        self.assertEqual(M._faixa_de_preco(124.2, D('124.20')), 'igual')
        self.assertEqual(M._faixa_de_preco(2569, D('2569')), 'igual')
        self.assertEqual(M._faixa_de_preco(102.0, D('100')), 'ate2')
        self.assertEqual(M._faixa_de_preco(98.0, D('100')), 'ate2')
        self.assertEqual(M._faixa_de_preco(102.01, D('100')), 'acima')
        self.assertEqual(M._faixa_de_preco(50.0, D('100')), 'acima')


class TestCandidatos(T.Base):
    def test_pai_vai_para_os_filhos(self):
        ml = MLFalso()
        ml.buscas['abc'] = [
            {'id': 'MLB100', 'status': 'inactive', 'children_ids': ['MLB101', '../x', 'MLB102', 'MLB103', 'MLB104']},
            {'id': 'MLB200', 'status': 'active'},
            {'id': 'MLB300', 'status': 'active', 'children_ids': ['MLB301', 'MLB200']},
            {'id': 'MLB400', 'status': 'active'}]   # o 4º passa do k=3
        self.gravar()
        pids = M.candidatos(self.sessao(ml.op), 'abc')
        self.assertEqual(pids, ['MLB101', 'MLB102', 'MLB103', 'MLB200', 'MLB301'])
        self.assertEqual(ml.op.gets()[0].query, {'site_id': 'MLB', 'status': 'active', 'q': 'abc', 'limit': '3'})

    def test_ids_estranhos_nao_viram_candidato(self):
        ml = MLFalso()
        ml.buscas['abc'] = [{'id': '../../users/me', 'status': 'active'}, {'id': 12345, 'status': 'active'},
                            {'id': 'MLB', 'status': 'active'}, 'x']
        self.gravar()
        self.assertEqual(M.candidatos(self.sessao(ml.op), 'abc'), [])
        op = T.OpenerFalso(T.api_padrao(gets=lambda c: {'sem_results': 1}))
        with self.assertRaises(M.RespostaInvalida):
            M.candidatos(self.sessao(op), 'abc')

    def test_produto_valida_o_id_antes_do_caminho(self):
        ml = MLFalso()
        self.gravar()
        for ruim in ('../users/me', 'MLB1/../x', None, 123, 'MLB'):
            with self.assertRaises(ValueError):
                M.produto(self.sessao(ml.op), ruim)
        self.assertEqual(ml.op.gets(), [])


# ---------- a sonda ----------
class TestSonda(Catalogo):
    def cenario(self):
        """5 itens: 1 e 2 provados pelo bbw, 3 pela lista (2ª página, depois de um 404 noutro candidato),
        4 com título igual mas sem pertença, 5 sem candidato. Preços-marcador no banco e na API."""
        p = {1: 91234.56, 2: 92345.67, 3: 93456.78, 4: 94567.89, 5: 95678.91}
        self.precos = list(p.values())
        self.banco([(1, 'Celulares e Informática', p[1], self.recente()),
                    (2, 'Perfumes e Perfumaria', p[2], self.recente()),
                    (3, 'Perfumes e Perfumaria', p[3], self.recente(72)),
                    (4, 'CAT-MARCADOR-ESTRANHA', p[4], self.recente()),
                    (5, 'Casa e Cozinha', p[5], None)])
        ml = MLFalso()
        ml.buscas[ml.q(1)] = [{'id': 'MLB11', 'status': 'active'}]
        ml.produtos['MLB11'] = prod('MLB11', self.mlb(1), p[1], categoria='MLB1055')
        ml.buscas[ml.q(2)] = [{'id': 'MLB21', 'status': 'active'}, {'id': 'MLB22', 'status': 'active'}]
        ml.produtos['MLB21'] = prod('MLB21', 'MLB8888888888', 11111.11)
        ml.listas['MLB21'] = [[linha_lista('MLB8888888888', 11111.11)]]
        ml.produtos['MLB22'] = prod('MLB22', self.mlb(2), p[2] * 1.01)        # até 2%
        ml.buscas[ml.q(3)] = [{'id': 'MLB31', 'status': 'active'}, {'id': 'MLB32', 'status': 'active'}]
        ml.produtos['MLB31'] = prod('MLB31', nulo=True)                      # sem /items: 404
        ml.produtos['MLB32'] = prod('MLB32', 'MLB7777777777', 22222.22)
        ml.listas['MLB32'] = [[linha_lista('MLB7777777777', 1.0)], [linha_lista(self.mlb(3), p[3] * 1.5)]]
        ml.buscas[ml.q(4)] = [{'id': 'MLB41', 'status': 'active'}]
        ml.produtos['MLB41'] = prod('MLB41', 'MLB6666666666', p[4], name=titulo(4))   # título igual, outro anúncio
        ml.listas['MLB41'] = [[linha_lista('MLB6666666666', p[4])]]
        ml.outros['/reviews/item/'] = {'rating_average': 4.87, 'paging': {'total': 321}}
        ml.outros['/highlights/'] = {'content': [{'id': 'MLB5555555555', 'type': 'ITEM'}]}
        ml.erros['/sites/'] = (403, {'message': 'forbidden', 'error': 'forbidden'})
        return ml

    def test_conta_provados_por_bbw_e_por_lista(self):
        ml = self.cenario()
        codigo, out = self.direto(ml, amostra=5)
        self.assertEqual(codigo, 0, out)
        self.assertIn('Catálogo: amostra de 5 de 5 itens do ML no banco', out)
        self.assertIn('F7 /products/search (título): 200: 5; itens com candidato: 4 de 5; média de candidatos: 1.5',
                      out)
        self.assertIn('F8 /products/{id}: 200: 6; lidos: 6; buy_box_winner: objeto 5, nulo 1, ausente 0; campos do '
                      'buy_box_winner: condition, currency_id, item_id, original_price, price, seller_id, shipping; '
                      'shipping.free_shipping: 5; pictures[].id: 6; children_ids: 0; status active: 6, outro: 0; '
                      'category_id: 1', out)
        self.assertIn('F9 /products/{id}/items: 200: 4, 404 not_found: 1; 404: 1 (bbw nulo 1, bbw de outro anúncio 0, '
                      'bbw ausente 0, sem produto 0); campos em results[]: condition, currency_id, item_id, '
                      'original_price, price, seller_id; paging: limit, offset, total', out)
        self.assertIn(f'F10 provados: 3 de 5 (60%) (bbw: 2, lista: 1)', out)
        exemplos = re.search(r'F10 exemplos: (.*)', out).group(1).split(', ')
        self.assertEqual(sorted(exemplos), [self.mlb(1), self.mlb(2), self.mlb(3)])
        self.assertIn('F10 aba Celulares e Informática: 1 de 1', out)
        self.assertIn('F10 aba Perfumes e Perfumaria: 2 de 2', out)
        self.assertIn('F10 aba Casa e Cozinha: 0 de 1', out)
        self.assertIn('F10 aba (outra aba): 0 de 1', out)
        self.assertNotIn('CAT-', out)
        self.assertIn('F11 preço do banco até 48 h: igual 1, até 2% 1, acima de 2% 0', out)
        self.assertIn('F11 preço do banco mais antigo ou sem data: igual 0, até 2% 0, acima de 2% 1', out)
        self.assertIn(f'F11 acima de 2%: {self.mlb(3)}', out)
        self.assertIn('F13 /reviews/item/{id}: 200', out)
        self.assertIn('F14 /highlights/MLB/category/{cat}: 200', out)
        self.assertIn('F15 /sites/MLB/search?product_id: 403 forbidden', out)
        self.assertRegex(out, r'chamadas: \d+, 429: 0, tempo: \d+\.\ds\n\Z')
        # F14 usa o category_id do produto; F15 o 1º produto candidato; F13 o 1º item da amostra
        self.assertEqual([c.caminho for c in ml.gets(prefixo='/highlights/')], ['/highlights/MLB/category/MLB1055'])
        f15 = ml.gets('/sites/MLB/search')
        self.assertEqual(len(f15), 1)
        self.assertEqual(f15[0].query['limit'], '1')
        self.assertTrue(M.RE_PRODUTO.fullmatch(f15[0].query['product_id']))
        self.assertEqual(len(ml.gets(prefixo='/reviews/item/MLB')), 1)
        # cada linha F<n> com no máximo 5 ids MLB, e todo id que sai é do banco
        for linha in out.splitlines():
            ids = re.findall(r'MLB[0-9]+', linha)
            self.assertLessEqual(len(ids), 5, linha)
            for i in ids:
                self.assertIn(i, {self.mlb(n) for n in range(1, 6)}, linha)
        self.assertSemTituloNemPreco(out, self.precos + [11111.11, 22222.22])
        # o título vira só a consulta: nenhum título cru vai para a API
        self.assertFalse(any('MARCADOR' in c.query.get('q', '') for c in ml.op.gets()))

    def test_cada_f_numa_linha_propria(self):
        ml = self.cenario()
        codigo, out = self.direto(ml, amostra=5)
        prefixos = {re.match(r'F([0-9]+) ', l).group(1) for l in out.splitlines() if re.match(r'F[0-9]+ ', l)}
        self.assertEqual(prefixos, {str(n) for n in range(7, 16)})

    def test_titulo_igual_sem_pertenca_nao_prova(self):
        self.banco([(4, 'Perfumes e Perfumaria', 100.0, self.recente())])
        ml = MLFalso()
        ml.buscas[ml.q(4)] = [{'id': 'MLB41', 'status': 'active'}]
        ml.produtos['MLB41'] = prod('MLB41', 'MLB6666666666', 100.0, name=titulo(4))
        ml.listas['MLB41'] = [[linha_lista('MLB6666666666', 100.0)]]
        codigo, out = self.direto(ml, amostra=1)
        self.assertIn('F10 provados: 0 de 1 (0%) (bbw: 0, lista: 0)', out)
        self.assertIn('F11 preço do banco até 48 h: igual 0, até 2% 0, acima de 2% 0', out)

    def test_pai_na_busca_vai_para_os_filhos(self):
        self.banco([(1, 'Perfumes e Perfumaria', 100.0, self.recente())])
        ml = MLFalso()
        ml.buscas[ml.q(1)] = [{'id': 'MLB10', 'status': 'inactive', 'children_ids': ['MLB11', 'MLB12']}]
        ml.produtos['MLB11'] = prod('MLB11', 'MLB6666666666', 1.0)
        ml.produtos['MLB12'] = prod('MLB12', self.mlb(1), 100.0)
        codigo, out = self.direto(ml, amostra=1)
        self.assertIn('F10 provados: 1 de 1 (100%) (bbw: 1, lista: 0)', out)
        caminhos = [c.caminho for c in ml.op.gets()]
        self.assertNotIn('/products/MLB10', caminhos)
        self.assertIn('/products/MLB12', caminhos)

    def test_404_no_items_nao_derruba(self):
        self.banco([(1, 'Perfumes e Perfumaria', 100.0, self.recente()),
                    (2, 'Perfumes e Perfumaria', 200.0, self.recente())])
        ml = MLFalso()
        for n in (1, 2):
            ml.buscas[ml.q(n)] = [{'id': f'MLB{n}1', 'status': 'active'}, {'id': f'MLB{n}2', 'status': 'active'}]
            ml.produtos[f'MLB{n}1'] = prod(f'MLB{n}1', 'MLB6666666666', 1.0)   # /items: 404
            ml.produtos[f'MLB{n}2'] = prod(f'MLB{n}2', 'MLB6666666666', 1.0)
            ml.listas[f'MLB{n}2'] = [[linha_lista(self.mlb(n), 100.0 * n)]]
        codigo, out = self.direto(ml, amostra=2)
        self.assertEqual(codigo, 0)
        self.assertIn('F9 /products/{id}/items: 200: 2, 404 not_found: 2; 404: 2 (bbw nulo 0, bbw de outro anúncio 2, '
                      'bbw ausente 0, sem produto 0);', out)
        self.assertIn('F10 provados: 2 de 2 (100%) (bbw: 0, lista: 2)', out)
        self.assertIn('F11 preço do banco até 48 h: igual 2, até 2% 0, acima de 2% 0', out)

    def test_preco_sem_comparacao(self):
        self.banco([(1, 'Perfumes e Perfumaria', 'R$ 10 - R$ 20', self.recente()),
                    (2, 'Perfumes e Perfumaria', 100.0, 'data-ruim'),
                    (3, 'Perfumes e Perfumaria', 100.0, self.recente())])
        ml = MLFalso()
        for n, (preco, moeda) in {1: (100.0, 'BRL'), 2: (100.0, 'BRL'), 3: (100.0, 'USD')}.items():
            ml.buscas[ml.q(n)] = [{'id': f'MLB{n}1', 'status': 'active'}]
            ml.produtos[f'MLB{n}1'] = prod(f'MLB{n}1', self.mlb(n), preco, moeda=moeda)
        codigo, out = self.direto(ml, amostra=3)
        self.assertIn('F10 provados: 3 de 3', out)
        self.assertIn('F11 preço do banco mais antigo ou sem data: igual 1, até 2% 0, acima de 2% 0', out)
        self.assertIn('F11 sem comparação: sem preço legível no banco 1, sem preço BRL na API 1', out)

    def test_limit_50_uma_vez(self):
        self.banco([(1, 'Perfumes e Perfumaria', 100.0, self.recente())])
        ml = MLFalso()
        ml.buscas[ml.q(1)] = [{'id': f'MLB{n}', 'status': 'active'} for n in range(10, 40)]
        codigo, out = self.direto(ml, amostra=1)
        limites = [c.query['limit'] for c in ml.gets('/products/search')]
        self.assertEqual(limites.count('50'), 1)
        self.assertEqual(limites[0], '50')
        self.assertIn('F7 /products/search limit=50: 200; resultados: 30; paging.limit: 50', out)

    def test_ids_por_linha_no_maximo_5(self):
        self.banco([(n, 'Perfumes e Perfumaria', 100.0 + n, self.recente()) for n in range(1, 9)])
        ml = MLFalso()
        for n in range(1, 9):
            ml.buscas[ml.q(n)] = [{'id': f'MLB{n}1', 'status': 'active'}]
            ml.produtos[f'MLB{n}1'] = prod(f'MLB{n}1', self.mlb(n), 300.0 + n)
        codigo, out = self.direto(ml, amostra=8)
        self.assertIn('F10 provados: 8 de 8', out)
        for linha in out.splitlines():
            self.assertLessEqual(len(re.findall(r'MLB[0-9]+', linha)), 5, linha)
        self.assertEqual(len(re.findall(r'MLB[0-9]+', re.search(r'F11 acima de 2%: .*', out).group())), 5)

    def test_para_no_teto_de_500(self):
        """Todo item explode em 3 pais × 3 filhos, nenhum prova e toda lista tem 3 páginas: para em 500."""
        self.banco([(n, 'Perfumes e Perfumaria', 100.0, self.recente()) for n in range(1, 51)])
        ml = MLFalso()
        outro = [[linha_lista('MLB6666666666', 1.0)]] * 3
        for n in range(1, 51):
            pais = []
            for j in range(3):
                filhos = [f'MLB{n}{j}{k}' for k in range(1, 4)]
                pais.append({'id': f'MLB{n}{j}0', 'status': 'inactive', 'children_ids': filhos})
                for f in filhos:
                    ml.produtos[f] = prod(f, 'MLB6666666666', 1.0, categoria='MLB1055')
                    ml.listas[f] = outro
            ml.buscas[ml.q(n)] = pais
        for termo in TERMOS:   # 2 pais × 3 filhos: 6 candidatos, o F12 lê 5
            ml.buscas[termo] = [{'id': f'MLB770{i}000', 'status': 'inactive',
                                 'children_ids': [f'MLB770{i}00{k}' for k in range(1, 4)]} for i in range(2)]
        for i in range(2):
            for k in range(1, 4):
                ml.produtos[f'MLB770{i}00{k}'] = prod(f'MLB770{i}00{k}', 'MLB6666666666', 1.0)
        codigo, out = self.direto(ml, amostra=50)
        self.assertEqual(codigo, 0)
        self.assertEqual(len(ml.op.gets()), 500)
        self.assertIn('Parcial (teto de 500 chamadas', out)
        self.assertIn('chamadas: 500, 429: 0', out)
        # a reserva garante F12 a F15 mesmo com o laço no teto
        self.assertIn('F13 /reviews/item/{id}: 404 not_found', out)
        self.assertIn('F14 /highlights/MLB/category/{cat}: 404 not_found', out)
        self.assertIn('F15 /sites/MLB/search?product_id: 404 not_found', out)
        # com um teto menor, nada passa dele
        ml2 = MLFalso()
        ml2.buscas, ml2.produtos, ml2.listas = ml.buscas, ml.produtos, ml.listas
        codigo, out = self.direto(ml2, amostra=50, teto=40)
        self.assertEqual(len(ml2.op.gets()), 40)
        self.assertIn('chamadas: 40,', out)

    def test_pausa_entre_chamadas(self):
        self.banco([(n, 'Perfumes e Perfumaria', 100.0, self.recente()) for n in range(1, 4)])
        for sorteio, esperado in ((0.0, 0.3), (0.5, 0.55), (0.999999, 0.8)):
            ml = MLFalso()
            dormidas = []
            codigo, out = self.direto(ml, amostra=3, dormir=dormidas.append, aleatorio=lambda: sorteio)
            n = len(ml.op.gets())
            self.assertEqual(len(dormidas), n - 1)
            for d in dormidas:
                self.assertAlmostEqual(d, esperado, places=5)
                self.assertTrue(0.3 <= d <= 0.8)

    def test_amostra_deterministica_com_semente(self):
        self.banco([(n, 'Perfumes e Perfumaria', 100.0, self.recente()) for n in range(1, 31)])

        def consultas(semente):
            ml = MLFalso()
            self.direto(ml, amostra=5, semente=semente)
            return [c.query['q'] for c in ml.gets('/products/search') if c.query['limit'] == '3']
        a, b, c = consultas(7), consultas(7), consultas(8)
        self.assertEqual(len(a), 5 + M.TERMOS_F12)
        self.assertEqual(a, b)
        self.assertNotEqual(a[:5], c[:5])
        self.assertEqual(len(set(a[:5])), 5)

    def test_saida_nunca_traz_titulo_nem_preco(self):
        ml = self.cenario()
        self.gravar_real()
        codigo, out, err = self.rodar_cat(['sondar', '--catalogo', '--amostra', '5'], ml)
        self.assertEqual(codigo, 0, err)
        self.assertEqual(err, '')
        self.assertIn('F10 provados: 3 de 5', out)
        self.assertSemTituloNemPreco(out + err, self.precos + [11111.11, 22222.22])
        self.assertNotIn(T.ACCESS, ''.join(c.url for c in ml.op.chamadas))
        self.assertTrue(all(c.metodo == 'GET' and c.host == 'api.mercadolibre.com' for c in ml.op.chamadas))

    def test_limite_da_3_com_o_parcial(self):
        ml = self.cenario()
        ml.erros['/products/MLB2'] = (429, {})   # o 2º item da amostra estoura
        self.gravar_real()
        with mock.patch.object(M, 'BACKOFF_BASE', 0.0):
            codigo, out, err = self.rodar_cat(['sondar', '--catalogo', '--amostra', '5', '--semente', '1'], ml)
        self.assertEqual(codigo, 3, err)
        self.assertTrue(err.startswith('PAROU: '), err)
        self.assertIn('Parcial (limite de requisições (429))', out)
        self.assertIn('F10 provados:', out)
        self.assertRegex(out, r'chamadas: \d+, 429: 3, tempo: ')
        self.assertNotIn('F12', out)
        self.assertSemTituloNemPreco(out + err, self.precos)

    def test_sem_permissao_na_lista_nao_para_os_outros(self):
        ml = self.cenario()
        policy = (403, {'blocked_by': 'PolicyAgent', 'code': 'PA_UNAUTHORIZED_RESULT_FROM_POLICIES'})
        for pid in list(ml.listas):
            ml.listas[pid] = policy
        ml.erros['/reviews/'] = policy
        codigo, out = self.direto(ml, amostra=5)
        self.assertEqual(codigo, 0)
        # a lista dá 403 uma vez e não é chamada de novo; o bbw continua provando
        self.assertEqual(len([c for c in ml.op.gets() if c.caminho.endswith('/items')]), 1)
        self.assertIn('F9 /products/{id}/items: 403 PA_UNAUTHORIZED_RESULT_FROM_POLICIES: 1', out)
        self.assertIn('(bbw: 2, lista: 0)', out)
        self.assertIn('F12 /products/search', out)
        self.assertIn('F13 /reviews/item/{id}: 403 PA_UNAUTHORIZED_RESULT_FROM_POLICIES (falta permissão', out)
        self.assertIn('F14 /highlights/MLB/category/{cat}: 200', out)
        self.assertIn('F15 /sites/MLB/search?product_id: 403 forbidden', out)

    def test_sem_permissao_na_busca_nao_para_os_outros(self):
        ml = self.cenario()
        ml.erros['/products/search'] = (403, {'blocked_by': 'PolicyAgent', 'code': 'PA_UNAUTHORIZED'})
        codigo, out = self.direto(ml, amostra=5)
        self.assertEqual(codigo, 0)
        self.assertIn('Parcial (403 na busca de produtos)', out)
        # limit=50, o 1º item (para o laço) e os 5 termos do F12
        self.assertEqual(len(ml.gets('/products/search')), 1 + 1 + 1)
        self.assertIn('F12 /products/search (5 termos): 403 PA_UNAUTHORIZED: 1', out)
        self.assertIn('F13 /reviews/item/{id}: 200', out)
        self.assertIn('F14 /highlights/MLB/category/{cat}: pulado (sem category_id)', out)
        self.assertIn('F15 /sites/MLB/search?product_id: pulado (sem id de produto)', out)

    def test_banco_vazio_ou_ausente(self):
        ml = MLFalso()
        codigo, out = self.direto(ml, amostra=5)   # o banco nem existe
        self.assertEqual(codigo, 0)
        self.assertFalse(os.path.exists(self.db))
        self.assertIn('amostra de 0 de 0', out)
        self.assertIn('F7-F11: pulados (sem item do ML no banco)', out)
        self.assertIn('F13 /reviews/item/{id}: pulado', out)
        self.assertIn('F12 /products/search (5 termos): 200: 5', out)
        self.assertEqual(len(ml.op.gets()), 5)

    def test_buscas_ausente_pula_o_f12_e_toda_aba_e_outra(self):
        self.banco([(1, 'Perfumes e Perfumaria', 100.0, self.recente())])
        ml = MLFalso()
        codigo, out = self.direto(ml, amostra=1, buscas=os.path.join(self.dir, 'nao-existe.json'))
        self.assertIn('F12 /products/search (termos): pulado', out)
        self.assertIn('F10 aba (outra aba): 0 de 1', out)
        self.assertNotIn('Perfumes', out)


# ---------- rodada 2 (achados R1, R2, R3, R5, R6, R8, S1/R4, S3) ----------
class TestRodada2(Catalogo):
    def tres_por_bbw(self):
        """3 itens provados pelo bbw: cada um custa 2 chamadas (busca + produto), mais o limit=50 no início."""
        self.banco([(n, 'Perfumes e Perfumaria', 100.0 + n, self.recente()) for n in range(1, 4)])
        ml = MLFalso()
        for n in range(1, 4):
            ml.buscas[ml.q(n)] = [{'id': f'MLB60{n}', 'status': 'active'}]
            ml.produtos[f'MLB60{n}'] = prod(f'MLB60{n}', self.mlb(n), 100.0 + n)
        return ml

    def test_r1_item_cortado_pelo_teto_nao_entra_nas_contagens(self):
        ml = self.tres_por_bbw()
        # laço com 6 chamadas: limit=50, 2 itens inteiros e a busca do 3º (o produto dele não cabe)
        codigo, out = self.direto(ml, amostra=3, teto=6 + M.RESERVA_FINAIS)
        self.assertEqual(codigo, 0)
        self.assertEqual(len([c for c in ml.op.gets()[:6] if c.caminho == '/products/search']), 4)
        self.assertIn('Parcial (teto de 39 chamadas, com 33 guardadas para F12 a F15): itens vistos 2 de 3', out)
        self.assertIn('itens com candidato: 2 de 2;', out)
        self.assertIn('F10 provados: 2 de 2 (100%) (bbw: 2, lista: 0)', out)
        self.assertIn('F10 aba Perfumes e Perfumaria: 2 de 2', out)
        self.assertIn('F11 preço do banco até 48 h: igual 2,', out)

    def test_r1_item_cortado_pelo_limite_nao_entra_nas_contagens(self):
        ml = self.tres_por_bbw()
        lidos = []
        responder = ml.responder

        def gets(c):
            if re.fullmatch(r'/products/MLB60[0-9]', c.caminho):
                if c.caminho not in lidos:
                    lidos.append(c.caminho)
                if len(lidos) >= 3 and c.caminho == lidos[2]:
                    return T.erro_http(429, {})
            return responder(c)
        ml.op.responder = T.api_padrao(gets=gets)
        self.gravar_real()
        codigo, out, err = self.rodar_cat(['sondar', '--catalogo', '--amostra', '3'], ml)
        self.assertEqual(codigo, 3, err)
        self.assertIn('Parcial (limite de requisições (429)): itens vistos 2 de 3', out)
        self.assertIn('itens com candidato: 2 de 2;', out)
        self.assertIn('F10 provados: 2 de 2 (100%)', out)
        self.assertIn('F10 aba Perfumes e Perfumaria: 2 de 2', out)

    def test_r2_404_da_lista_separado_pelo_estado_do_produto(self):
        self.banco([(n, 'Perfumes e Perfumaria', 100.0, self.recente()) for n in range(1, 5)])
        ml = MLFalso()
        for n in range(1, 5):
            ml.buscas[ml.q(n)] = [{'id': f'MLB61{n}', 'status': 'active'}]
        ml.produtos['MLB611'] = prod('MLB611', nulo=True)                     # bbw nulo
        ml.produtos['MLB612'] = prod('MLB612', 'MLB6666666666', 1.0)          # bbw de outro anúncio
        # MLB613: sem produto (404 no /products/{id})
        ml.produtos['MLB614'] = prod('MLB614')                                # sem a chave buy_box_winner
        codigo, out = self.direto(ml, amostra=4)
        self.assertEqual(codigo, 0)
        self.assertIn('F9 /products/{id}/items: 404 not_found: 4; 404: 4 (bbw nulo 1, bbw de outro anúncio 1, '
                      'bbw ausente 1, sem produto 1); campos', out)

    def test_r2_404_com_produto_bloqueado_conta_como_sem_produto(self):
        self.banco([(n, 'Perfumes e Perfumaria', 100.0, self.recente()) for n in range(1, 3)])
        ml = MLFalso()
        for n in range(1, 3):
            ml.buscas[ml.q(n)] = [{'id': f'MLB62{n}', 'status': 'active'}]
        # a ordem dos prefixos importa: os /items vêm antes do /products/MLB62 (403 PolicyAgent no produto)
        ml.erros = {'/products/MLB621/items': (404, {'error': 'not_found'}),
                    '/products/MLB622/items': (404, {'error': 'not_found'}),
                    '/products/MLB62': (403, {'blocked_by': 'PolicyAgent', 'code': 'PA_UNAUTHORIZED'})}
        codigo, out = self.direto(ml, amostra=2)
        self.assertIn('; 404: 2 (bbw nulo 0, bbw de outro anúncio 0, bbw ausente 0, sem produto 2);', out)

    def renovacao_500(self, gets=None, falta=10, n_itens=10):
        self.banco([(n, 'Perfumes e Perfumaria', 100.0, self.recente()) for n in range(1, n_itens + 1)])
        self.gravar_real(falta=falta)
        ml = MLFalso()
        ml.op = T.OpenerFalso(T.api_padrao(gets=gets or ml.responder,
                                           token=lambda c: T.erro_http(500, {'error': 'internal_error'})))
        codigo, out, err = self.rodar_cat(['sondar', '--catalogo', '--amostra', str(n_itens)], ml, secret=T.SECRET)
        return ml, codigo, out, err

    def test_s1_token_vencido_e_renovacao_500_para_no_primeiro_post(self):
        ml, codigo, out, err = self.renovacao_500()
        self.assertEqual(codigo, 2, err)
        self.assertEqual((len(ml.op.posts()), len(ml.op.gets())), (1, 0))
        self.assertEqual(err, f'ERRO: {M.RenovacaoFalhou(500)}\n')
        self.assertIn('renovação do acesso', err)
        self.assertIn('HTTP 500', err)
        self.assertEqual(out, '')
        T.sem_marcadores(self, out, err)

    def test_s1_401_e_renovacao_500_no_meio_para_sem_contar_no_catalogo(self):
        def gets(c):
            return T.erro_http(401, {'error': 'invalid_token'})
        ml, codigo, out, err = self.renovacao_500(gets=gets, falta=3600)
        self.assertEqual(codigo, 2, err)
        self.assertEqual((len(ml.op.posts()), len(ml.op.gets())), (1, 1))
        self.assertIn('renovação do acesso', err)
        self.assertNotRegex(out, r'F[0-9]+ [^\n]*500')   # a falha do POST não vira status de endpoint do catálogo
        self.assertIn('Parcial (erro)', out)
        self.assertRegex(out, r'chamadas: 1, 429: 0, tempo: ')

    def test_s1_token_vence_no_meio_e_renovacao_500_para_e_nao_conta_chamada(self):
        ml = self.tres_por_bbw()
        responder = ml.responder

        def gets(c):
            if len(ml.op.gets()) == 3:            # limit=50 e o 1º item inteiro: o token passa da validade
                self.agora[0] = T.AGORA + 7200
            return responder(c)
        ml.op.responder = T.api_padrao(gets=gets, token=lambda c: T.erro_http(503, {}))
        self.gravar()
        sessao = self.sessao(ml.op)
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(M.RenovacaoFalhou) as cm:
            M.sondar_catalogo(sessao, self.db, amostra=3, buscas=self.buscas, agora=self.agora_real)
        out = out.getvalue()
        self.assertEqual(cm.exception.saida, 2)
        self.assertIn('[HTTP 503]', str(cm.exception))
        self.assertEqual((len(ml.op.posts()), len(ml.op.gets())), (1, 3))
        self.assertIn('Parcial (erro): itens vistos 1 de 3', out)
        self.assertIn('chamadas: 3, 429: 0', out)   # o POST que falhou não é chamada do catálogo
        self.assertNotRegex(out, r'F[0-9]+ [^\n]*503')
        self.assertIs(sessao.opener, ml.op)

    def test_s1_401_persistente_sai_2_e_renova_uma_vez(self):
        self.banco([(n, 'Perfumes e Perfumaria', 100.0, self.recente()) for n in range(1, 11)])
        self.gravar_real()
        ml = MLFalso()
        ml.op = T.OpenerFalso(T.api_padrao(gets=lambda c: T.erro_http(401, {'error': 'invalid_token'})))
        codigo, out, err = self.rodar_cat(['sondar', '--catalogo', '--amostra', '10'], ml, secret=T.SECRET)
        self.assertEqual(codigo, 2, err)
        self.assertEqual((len(ml.op.posts()), len(ml.op.gets())), (1, 2))
        self.assertIn('rode `ml_api.py autorizar`', err)
        self.assertNotIn('401', out)
        self.assertIn('Parcial (erro)', out)
        T.sem_marcadores(self, out, err)

    def test_s1_401_persistente_no_f13_tambem_para(self):
        ml = self.tres_por_bbw()
        ml.erros['/reviews/'] = (401, {'error': 'invalid_token'})
        self.gravar_real()
        codigo, out, err = self.rodar_cat(['sondar', '--catalogo', '--amostra', '3'], ml, secret=T.SECRET)
        self.assertEqual(codigo, 2, err)
        self.assertEqual(len(ml.op.posts()), 1)
        self.assertNotIn('F13', out)
        self.assertNotIn('F14', out)

    def test_r5_sem_tokens_nada_sai_no_stdout(self):
        self.banco([(1, 'Perfumes e Perfumaria', 100.0, self.recente())])
        ml = MLFalso()
        codigo, out, err = self.rodar_cat(['sondar', '--catalogo'], ml)
        self.assertEqual(codigo, 2)
        self.assertEqual(out, '')
        self.assertEqual(ml.op.chamadas, [])

    def test_q2_receita_do_secret_com_as_flags_usadas(self):
        self.banco([(1, 'Perfumes e Perfumaria', 100.0, self.recente())])
        self.gravar_real(falta=10)
        for argv, comando in ((['sondar', '--catalogo'], 'sondar --catalogo'),
                              (['sondar', '--catalogo', '--amostra', '7', '--semente', '-3'],
                               'sondar --catalogo --amostra 7 --semente -3'),
                              (['sondar', '--catalogo', '--semente', '9'], 'sondar --catalogo --semente 9')):
            ml = MLFalso()
            codigo, out, err = self.rodar_cat(argv, ml)
            self.assertEqual(codigo, 2, err)
            self.assertIn(f'ACHADINHOS_ML_SECRET="$S" python3 ml_api.py {comando}; unset S', err)
            self.assertEqual(ml.op.chamadas, [])
        # o sondar sem flag continua com a receita de antes
        codigo, out, err = self.rodar(['sondar'], T.OpenerFalso(T.api_padrao()))
        self.assertIn('python3 ml_api.py sondar; unset S', err)

    def test_r3_resultado_sem_status_vira_candidato_e_descartados_sao_contados(self):
        self.banco([(1, 'Perfumes e Perfumaria', 100.0, self.recente())])
        ml = MLFalso()
        ml.buscas[ml.q(1)] = [{'id': 'MLB631'},                                    # sem status: candidato
                              {'id': 'MLB632', 'status': 'inactive'},              # inativo sem filhos: descartado
                              'nao-e-dict']                                       # descartado
        ml.produtos['MLB631'] = prod('MLB631', self.mlb(1), 100.0)
        codigo, out = self.direto(ml, amostra=1)
        self.assertIn('itens com candidato: 1 de 1; média de candidatos: 1.0; sem título utilizável: 0; '
                      'descartados: 2', out)
        self.assertIn('F10 provados: 1 de 1', out)
        self.assertNotIn('/products/MLB632', [c.caminho for c in ml.op.gets()])

    def test_r3_candidatos_conta_descartados(self):
        ml = MLFalso()
        ml.buscas['abc'] = [{'id': 'MLB100', 'children_ids': ['MLB101']},     # pai sem status: filhos
                            {'id': 'MLB200'},                                  # sem status: candidato
                            {'id': 'MLB300', 'status': 'closed', 'children_ids': []},
                            {'id': 'MLB400', 'status': 'active'}]              # o 4º passa do k=3
        self.gravar()
        sessao = self.sessao(ml.op)
        self.assertEqual(M._candidatos(sessao, 'abc'), (['MLB101', 'MLB200'], 1))
        self.assertEqual(M.candidatos(sessao, 'abc'), ['MLB101', 'MLB200'])
        ml.buscas['xyz'] = [{'id': '../x', 'status': 'active'}, {'id': 'MLB1', 'children_ids': ['../y']}, 7]
        self.assertEqual(M._candidatos(sessao, 'xyz'), ([], 3))

    def test_r6_opener_volta_ao_original_depois_da_sonda(self):
        ml = self.tres_por_bbw()
        self.gravar()
        sessao = self.sessao(ml.op)
        with contextlib.redirect_stdout(io.StringIO()):
            M.sondar_catalogo(sessao, self.db, amostra=3, buscas=self.buscas, agora=self.agora_real)
        self.assertIs(sessao.opener, ml.op)
        # também quando a sonda para com erro
        ml.erros['/products/search'] = (429, {})
        sessao = self.sessao(ml.op)
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(M.Limite):
            M.sondar_catalogo(sessao, self.db, amostra=3, buscas=self.buscas, agora=self.agora_real)
        self.assertIs(sessao.opener, ml.op)

    def test_r4_a_sonda_usa_o_com_teto_e_devolve_o_opener_em_qualquer_erro(self):
        ml = self.tres_por_bbw()
        dormir, aleatorio = (lambda s: None), (lambda: 0.0)
        espiao = mock.Mock(wraps=M.com_teto)
        with mock.patch.object(M, 'com_teto', espiao):
            self.assertEqual(self.direto(ml, amostra=3, teto=77, dormir=dormir, aleatorio=aleatorio)[0], 0)
        espiao.assert_called_once()
        self.assertEqual(espiao.call_args.args[1:], (77, dormir, aleatorio))
        # erro que não é da API (o `except ErroML` não pega): a última linha sai e o opener volta
        self.gravar()
        sessao = self.sessao(ml.op)
        out = io.StringIO()
        with mock.patch.object(M, '_laco_da_amostra', side_effect=BrokenPipeError), \
                contextlib.redirect_stdout(out), self.assertRaises(BrokenPipeError):
            M.sondar_catalogo(sessao, self.db, amostra=3, buscas=self.buscas, agora=self.agora_real)
        self.assertIs(sessao.opener, ml.op)
        self.assertRegex(out.getvalue().splitlines()[-1], r'^chamadas: 0, 429: 0, tempo: \d+\.\ds$')

    def test_r6_preco_em_10_min_no_futuro_e_mais_antigo(self):
        futuro = time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(self.agora_real + 600))
        quase = time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(self.agora_real + 240))
        self.banco([(1, 'Perfumes e Perfumaria', 100.0, futuro), (2, 'Perfumes e Perfumaria', 100.0, quase)])
        ml = MLFalso()
        for n in (1, 2):
            ml.buscas[ml.q(n)] = [{'id': f'MLB64{n}', 'status': 'active'}]
            ml.produtos[f'MLB64{n}'] = prod(f'MLB64{n}', self.mlb(n), 100.0)
        codigo, out = self.direto(ml, amostra=2)
        self.assertIn('F11 preço do banco até 48 h: igual 1,', out)
        self.assertIn('F11 preço do banco mais antigo ou sem data: igual 1,', out)

    def test_r8_reserva_vem_do_numero_de_termos(self):
        self.assertEqual(M._reserva(M.TERMOS_F12), M.RESERVA_FINAIS)
        self.assertEqual(M._reserva(1), 1 * (1 + M.PRODUTOS_F12) + 3)
        self.assertEqual(M._reserva(0), 3)
        self.banco([(n, 'Perfumes e Perfumaria', 100.0, self.recente()) for n in range(1, 21)])
        ml = MLFalso()   # nada prova: cada item custa 1 busca (sem candidato)
        codigo, out = self.direto(ml, amostra=20, termos=1, teto=15)
        self.assertIn('Parcial (teto de 15 chamadas, com 9 guardadas para F12 a F15): itens vistos 5 de 20', out)
        self.assertEqual(len(ml.op.gets()), 6 + 1 + 1)   # laço (limit=50 + 5 itens), F12 de 1 termo, F13
        # sem buscas.json, a reserva é só a de F13 a F15
        ml = MLFalso()
        codigo, out = self.direto(ml, amostra=20, teto=15, buscas=os.path.join(self.dir, 'nao-existe.json'))
        self.assertIn('Parcial (teto de 15 chamadas, com 3 guardadas para F12 a F15): itens vistos 11 de 20', out)

    def test_s3_consulta_cortada_em_200_caracteres(self):
        palavra = 'a' * 30
        q = M.consulta_do_titulo(' '.join([palavra] * 12))
        self.assertLessEqual(len(q), M.MAX_CONSULTA)
        self.assertEqual(M.MAX_CONSULTA, 200)
        self.assertRegex(q, r'\A[0-9a-z]+(?: [0-9a-z]+)*\Z')   # sem espaço no fim depois do corte
        self.assertEqual(M.consulta_do_titulo('b' * 500), 'b' * 200)
        self.assertEqual(M.consulta_do_titulo('d' * 199 + ' ' + 'e' * 10), 'd' * 199)   # corte no espaço
        self.assertEqual(M.consulta_do_titulo(' '.join([palavra] * 6) + ' ' + 'c' * 40),
                         ' '.join([palavra] * 6) + ' ' + 'c' * 14)


class TestBancoSoLeitura(Catalogo):
    def conteudo(self, pasta):
        """{nome: bytes} dos arquivos comuns da pasta (o -shm do SQLite fica só pelo nome: leitor mexe nele)."""
        saida = {}
        for nome in sorted(os.listdir(pasta)):
            if not os.path.isfile(os.path.join(pasta, nome)):
                continue
            if nome.endswith('-shm'):
                saida[nome] = None
                continue
            with open(os.path.join(pasta, nome), 'rb') as f:
                saida[nome] = f.read()
        return saida

    def rodar_e_comparar(self):
        ml = MLFalso()
        ml.buscas[ml.q(1)] = [{'id': 'MLB11', 'status': 'active'}]
        ml.produtos['MLB11'] = prod('MLB11', self.mlb(1), 100.0)
        self.gravar_real()
        antes, tokens_antes = self.conteudo(self.pasta_db), self.conteudo(self.dir)
        codigo, out, err = self.rodar_cat(['sondar', '--catalogo', '--amostra', '3'], ml)
        self.assertEqual(codigo, 0, err)
        self.assertIn('F10 provados: 1 de 2', out)
        return antes, self.conteudo(self.pasta_db), tokens_antes, self.conteudo(self.dir)

    def test_nenhum_arquivo_criado_com_o_banco_em_uso(self):
        """Como no uso real (o servidor no ar segura o banco em WAL): a pasta do banco fica igual, byte a byte."""
        self.banco([(1, 'Perfumes e Perfumaria', 100.0, self.recente()), (2, 'Casa e Cozinha', 50.0, None)])
        servidor = sqlite3.connect(self.db)
        servidor.execute('SELECT count(*) FROM items').fetchall()
        try:
            antes, depois, t_antes, t_depois = self.rodar_e_comparar()
        finally:
            servidor.close()
        self.assertEqual(antes, depois)
        self.assertEqual(t_antes, t_depois)   # nem cache, nem progresso ao lado dos tokens

    def test_nenhum_arquivo_criado_com_banco_sem_wal(self):
        self.banco([(1, 'Perfumes e Perfumaria', 100.0, self.recente()), (2, 'Casa e Cozinha', 50.0, None)],
                   modo='delete')
        antes, depois, t_antes, t_depois = self.rodar_e_comparar()
        self.assertEqual(antes, depois)
        self.assertEqual(t_antes, t_depois)

    def test_banco_em_wal_parado_so_ganha_os_arquivos_do_sqlite(self):
        """Limite conhecido do SQLite: abrir em mode=ro um banco WAL sem -wal/-shm (servidor parado) cria os dois
        (vazios); o ids_do_banco do `sondar` já fazia o mesmo. O banco em si não muda."""
        self.banco([(1, 'Perfumes e Perfumaria', 100.0, self.recente()), (2, 'Casa e Cozinha', 50.0, None)])
        antes, depois, _, _ = self.rodar_e_comparar()
        self.assertEqual(antes[os.path.basename(self.db)], depois[os.path.basename(self.db)])
        self.assertLessEqual(set(depois) - set(antes), {'achadinhos.db-wal', 'achadinhos.db-shm'})

    def test_abre_em_mode_ro_com_query_only(self):
        self.banco([(1, 'Perfumes e Perfumaria', 100.0, self.recente())])
        abertos, comandos = [], []
        conectar = sqlite3.connect

        class Espiao:
            def __init__(self, con):
                self.con = con

            def execute(self, sql, *a):
                comandos.append(sql)
                return self.con.execute(sql, *a)

            def close(self):
                self.con.close()

        def espiar(alvo, *a, **kw):
            abertos.append((alvo, kw))
            return Espiao(conectar(alvo, *a, **kw))
        with mock.patch.object(M.sqlite3, 'connect', espiar):
            itens = M.itens_do_banco(self.db)
        self.assertEqual([i['item_id'] for i in itens], [self.mlb(1)])
        self.assertEqual(len(abertos), 1)
        self.assertTrue(abertos[0][0].endswith('?mode=ro') and abertos[0][1] == {'uri': True}, abertos)
        self.assertEqual(comandos[0], 'PRAGMA query_only = ON')
        self.assertTrue(comandos[1].startswith('SELECT item_id, titulo, cat, preco, preco_em FROM items'))
        # escrita é recusada mesmo com a permissão do arquivo
        os.chmod(self.db, 0o400)
        self.assertEqual(len(M.itens_do_banco(self.db)), 1)

    def test_banco_ilegivel_da_lista_vazia(self):
        with open(self.db, 'w') as f:
            f.write('nao e banco')
        self.assertEqual(M.itens_do_banco(self.db), [])
        self.assertEqual(M.itens_do_banco(os.path.join(self.dir, 'nao', 'existe.db')), [])
        self.assertFalse(os.path.exists(os.path.join(self.dir, 'nao')))


class TestCli(Catalogo):
    def test_amostra_acima_de_100_e_recusada(self):
        self.gravar_real()
        for valor in ('101', '1000', '0', '-5'):
            ml = MLFalso()
            codigo, out, err = self.rodar_cat(['sondar', '--catalogo', '--amostra', valor], ml)
            self.assertEqual(codigo, 2, valor)
            self.assertEqual(err, f'ERRO: --amostra vai de 1 a 100\n')
            self.assertEqual(out, '')
            self.assertEqual(ml.op.chamadas, [])

    def test_amostra_e_semente_so_com_catalogo(self):
        self.gravar_real()
        for argv in (['sondar', '--amostra', '5'], ['sondar', '--semente', '3']):
            ml = MLFalso()
            codigo, out, err = self.rodar_cat(argv, ml)
            self.assertEqual(codigo, 2)
            self.assertEqual(err, 'ERRO: --amostra e --semente só valem com --catalogo\n')
            self.assertEqual(ml.op.chamadas, [])

    def test_padrao_50_e_semente_fixa(self):
        self.banco([(n, 'Perfumes e Perfumaria', 100.0, self.recente()) for n in range(1, 61)])
        self.gravar_real()
        rodadas = []
        for _ in range(2):
            ml = MLFalso()
            codigo, out, err = self.rodar_cat(['sondar', '--catalogo'], ml)
            self.assertEqual(codigo, 0, err)
            self.assertIn(f'amostra de 50 de 60 itens do ML no banco (semente {M.SEMENTE_PADRAO})', out)
            rodadas.append([c.query['q'] for c in ml.gets('/products/search')])
        self.assertEqual(rodadas[0], rodadas[1])
        self.assertEqual(len(rodadas[0]), 1 + 50 + M.TERMOS_F12)

    def test_amostra_100_aceita(self):
        self.banco([(n, 'Perfumes e Perfumaria', 100.0, self.recente()) for n in range(1, 121)])
        self.gravar_real()
        ml = MLFalso()
        codigo, out, err = self.rodar_cat(['sondar', '--catalogo', '--amostra', '100'], ml)
        self.assertEqual(codigo, 0, err)
        self.assertIn('amostra de 100 de 120', out)

    def test_sem_tokens_da_2(self):
        self.banco([(1, 'Perfumes e Perfumaria', 100.0, self.recente())])
        ml = MLFalso()
        codigo, out, err = self.rodar_cat(['sondar', '--catalogo'], ml)
        self.assertEqual(codigo, 2)
        self.assertIn('rode `ml_api.py autorizar`', err)
        self.assertEqual(ml.op.chamadas, [])
        self.assertEqual(out, '')   # R5: nem cabeçalho nem parcial vazio

    def test_renovacao_fora_do_formato_da_2(self):
        self.banco([(1, 'Perfumes e Perfumaria', 100.0, self.recente())])
        self.gravar_real(falta=10)
        op = T.OpenerFalso(T.api_padrao(token=lambda c: T.resposta_token(1, refresh_token=None)))
        ml = MLFalso()
        ml.op = op
        codigo, out, err = self.rodar_cat(['sondar', '--catalogo'], ml, secret=T.SECRET)
        self.assertEqual(codigo, 2, err)
        self.assertEqual((len(op.posts()), len(op.gets())), (1, 0))
        T.sem_marcadores(self, out, err)

    def test_sondar_sem_flag_nao_le_a_amostra(self):
        """O `sondar` sem --catalogo segue igual: não chama a sonda do catálogo."""
        self.gravar_real()
        with mock.patch.object(M, 'sondar_catalogo', side_effect=AssertionError('não devia')):
            codigo, out, err = self.rodar(['sondar'], T.OpenerFalso(T.api_padrao()))
        self.assertEqual(codigo, 0, err)
        self.assertIn('F0 /users/me: 200', out)
        self.assertNotIn('Catálogo', out)


# ---------- etapa 2: vínculo com prova, arquivo de vínculos e ofertas por produto (CA3, CA6) ----------
HOJE = '2026-11-05'
ITEM = 'MLB9100000001'
OUTRO = 'MLB9100000002'
TERCEIRO = 'MLB9100000003'
TITULO_ITEM = 'TITULO-MARCADOR Fone Bluetooth Ação XYZ 500'


def vinculo(p=None, em=HOJE, via=None):
    return {'p': p, 'em': em, 'via': via}


class Vinculos(T.Base):
    def setUp(self):
        super().setUp()
        self.arq = os.path.join(self.dir, 'ml_catalogo.json')

    def escrever(self, conteudo, modo=0o600):
        with open(self.arq, 'wb') as f:
            f.write(conteudo if isinstance(conteudo, bytes) else conteudo.encode('utf-8'))
        os.chmod(self.arq, modo)

    def recusado(self, motivo):
        with self.assertRaises(M.VinculosRecusados) as cm:
            M.ler_vinculos(self.arq)
        self.assertEqual(cm.exception.saida, 2)
        self.assertIn(motivo, str(cm.exception))
        self.assertNotIn('MARCADOR', str(cm.exception) + repr(cm.exception))
        return cm.exception


class TestGravarAtomico(Vinculos):
    def test_grava_0600_troca_o_antigo_e_nao_deixa_sobra(self):
        self.escrever('antigo', 0o644)
        M.gravar_atomico(self.arq, b'{"novo":1}', 100)
        with open(self.arq, 'rb') as f:
            self.assertEqual(f.read(), b'{"novo":1}')
        self.assertEqual(stat.S_IMODE(os.stat(self.arq).st_mode), 0o600)
        self.assertEqual(os.listdir(self.dir), ['ml_catalogo.json'])

    def test_recusa_acima_do_teto_e_o_que_nao_e_bytes(self):
        for dados, teto in ((b'x' * 11, 10), ('texto', 100), (bytearray(b'x'), 100), (None, 100)):
            with self.assertRaises(ValueError):
                M.gravar_atomico(self.arq, dados, teto)
        self.assertEqual(os.listdir(self.dir), [])
        M.gravar_atomico(self.arq, b'x' * 10, 10)   # no teto exato
        self.assertEqual(os.path.getsize(self.arq), 10)

    def test_tokens_e_vinculos_usam_a_mesma_gravacao(self):
        anotadas, real = [], M.gravar_atomico
        with mock.patch.object(M, 'gravar_atomico', side_effect=lambda *a: anotadas.append(a) or real(*a)):
            self.gravar()
            M.gravar_vinculos({ITEM: vinculo()}, self.arq)
        self.assertEqual([(a[0], a[2]) for a in anotadas],
                         [(self.caminho, M.MAX_ARQUIVO_TOKENS), (self.arq, M.MAX_ARQUIVO_VINCULOS)])
        self.assertEqual(M.ler_tokens(self.caminho).access.valor(), T.ACCESS)
        self.assertEqual(sorted(os.listdir(self.dir)), ['ml_catalogo.json', 'ml_tokens.json'])

    def test_falha_no_meio_nao_deixa_temporario_e_mantem_o_antigo(self):
        antes = {ITEM: vinculo('MLB11', via='lista')}
        M.gravar_vinculos(antes, self.arq)
        with mock.patch.object(M.os, 'replace', side_effect=OSError('falhou')):
            with self.assertRaises(OSError):
                M.gravar_vinculos({OUTRO: vinculo()}, self.arq)
        self.assertEqual(os.listdir(self.dir), ['ml_catalogo.json'])
        self.assertEqual(M.ler_vinculos(self.arq), antes)


class TestArquivoDeVinculos(Vinculos):
    def test_ida_e_volta_no_formato_do_plano(self):
        itens = {ITEM: vinculo('MLB99', via='lista'), OUTRO: vinculo('MLB1', '2026-11-01', 'bbw'),
                 TERCEIRO: vinculo(em='2026-10-20')}
        M.gravar_vinculos(itens, self.arq)
        with open(self.arq, 'rb') as f:
            bruto = f.read()
        self.assertTrue(bruto.isascii())
        self.assertEqual(json.loads(bruto), {'v': 1, 'itens': itens})
        self.assertEqual(stat.S_IMODE(os.stat(self.arq).st_mode), 0o600)
        self.assertEqual(M.ler_vinculos(self.arq), itens)

    def test_sem_arquivo_e_vazio(self):
        self.assertEqual(M.ler_vinculos(self.arq), {})
        self.assertEqual(os.listdir(self.dir), [])

    def test_caminho_padrao_vem_do_ambiente(self):
        with mock.patch.object(M, 'CATALOGO', self.arq):
            M.gravar_vinculos({ITEM: vinculo()})
            self.assertEqual(M.ler_vinculos(), {ITEM: vinculo()})
        self.assertTrue(os.path.isfile(self.arq))
        codigo = 'import ml_api; print(ml_api.CATALOGO)'
        env = dict(os.environ, ACHADINHOS_ML_CATALOGO=os.path.join(self.dir, 'outro.json'))
        r = subprocess.run([sys.executable, '-c', codigo], cwd=RAIZ, env=env, capture_output=True, text=True,
                           timeout=30)
        self.assertEqual(r.stdout.strip(), os.path.join(self.dir, 'outro.json'), r.stderr)
        env.pop('ACHADINHOS_ML_CATALOGO')
        r = subprocess.run([sys.executable, '-c', codigo], cwd=RAIZ, env=env, capture_output=True, text=True,
                           timeout=30)
        self.assertEqual(r.stdout.strip(), os.path.join(RAIZ, 'ml_catalogo.json'), r.stderr)

    def test_recusa_symlink_mesmo_para_arquivo_bom(self):
        bom = os.path.join(self.dir, 'bom.json')
        M.gravar_vinculos({ITEM: vinculo()}, bom)
        os.symlink(bom, self.arq)
        self.recusado('link simbólico')

    def test_recusa_permissao_aberta(self):
        M.gravar_vinculos({ITEM: vinculo()}, self.arq)
        for modo in (0o644, 0o640, 0o604, 0o660, 0o602):
            os.chmod(self.arq, modo)
            self.recusado('chmod 600')
        os.chmod(self.arq, 0o400)
        self.assertEqual(M.ler_vinculos(self.arq), {ITEM: vinculo()})

    def test_recusa_dono_diferente(self):
        M.gravar_vinculos({ITEM: vinculo()}, self.arq)
        with mock.patch.object(M.os, 'getuid', return_value=os.getuid() + 1):
            self.recusado('dono')

    def test_recusa_o_que_nao_e_arquivo_comum_sem_travar(self):
        os.mkdir(self.arq)
        self.recusado('arquivo comum')
        os.rmdir(self.arq)
        os.mkfifo(self.arq, 0o600)
        inicio = time.monotonic()
        self.recusado('arquivo comum')
        self.assertLess(time.monotonic() - inicio, 5)

    def test_teto_de_2_mb(self):
        corpo = json.dumps({'v': 1, 'itens': {ITEM: vinculo()}})
        for tamanho, aceita in ((M.MAX_ARQUIVO_VINCULOS, True), (M.MAX_ARQUIVO_VINCULOS + 1, False)):
            self.escrever(corpo + ' ' * (tamanho - len(corpo)))
            self.assertEqual(os.path.getsize(self.arq), tamanho)
            if aceita:
                self.assertEqual(M.ler_vinculos(self.arq), {ITEM: vinculo()})
            else:
                self.recusado('passa de 2097152 bytes')
        self.assertEqual(M.MAX_ARQUIVO_VINCULOS, 2 * 1024 * 1024)

    def test_recusa_conteudo_fora_do_formato(self):
        def arq(itens, **extra):
            return json.dumps(dict({'v': 1, 'itens': itens}, **extra))
        bom = vinculo('MLB99', via='lista')
        ruins = [
            'nada', '[]', '{}', 'null', arq({}, x=1), json.dumps({'v': 2, 'itens': {}}),
            json.dumps({'v': True, 'itens': {}}), json.dumps({'v': 1.0, 'itens': {}}), json.dumps({'v': 1}),
            json.dumps({'v': 1, 'itens': []}), json.dumps({'v': 1, 'itens': None}),
            # id do anúncio
            arq({'MLB12345': bom}), arq({'mlb9100000001': bom}), arq({ITEM + ' ': bom}), arq({'../' + ITEM: bom}),
            arq({'TITULO-MARCADOR': bom}), arq({'MLB' + '1' * 20: bom}),
            # id do produto e via
            arq({ITEM: vinculo('../users/me', via='lista')}), arq({ITEM: vinculo('MLB', via='lista')}),
            arq({ITEM: vinculo('MLB1/../x', via='lista')}), arq({ITEM: vinculo(123, via='lista')}),
            arq({ITEM: vinculo('MLB' + '1' * 20, via='lista')}), arq({ITEM: vinculo('MLB99')}),
            arq({ITEM: vinculo(via='bbw')}), arq({ITEM: vinculo('MLB99', via='outra')}),
            # data
            arq({ITEM: vinculo(em='2026-13-01')}), arq({ITEM: vinculo(em='2026-02-30')}),
            arq({ITEM: vinculo(em='2026-11-5')}), arq({ITEM: vinculo(em='05/11/2026')}),
            arq({ITEM: vinculo(em=20261105)}), arq({ITEM: vinculo(em='2026-11-05T10:00:00')}),
            # o date.fromisoformat do 3.14 aceita estes dois: quem barra é o RE_DATA
            arq({ITEM: vinculo(em='20261105')}), arq({ITEM: vinculo(em='2026-W45-4')}),
            # chaves do vínculo
            arq({ITEM: dict(bom, titulo='TITULO-MARCADOR')}), arq({ITEM: {'p': None, 'em': HOJE}}),
            arq({ITEM: [None, HOJE, None]}), arq({ITEM: None}),
            # bytes e JSON hostis
            '{"v":1,"itens":{},"é":1}', '[' * 100000, '{"v":' + '1' * 5000 + ',"itens":{}}', b'\xff\xfe{}',
        ]
        for conteudo in ruins:
            with self.subTest(conteudo=conteudo[:60]):
                self.escrever(conteudo)
                self.recusado('fora do formato')

    def test_gravar_recusa_vinculo_fora_do_formato_sem_tocar_no_arquivo(self):
        antes = {ITEM: vinculo('MLB99', via='lista')}
        M.gravar_vinculos(antes, self.arq)
        for ruim in ({'MLB1': vinculo()}, {ITEM: vinculo('../x', via='lista')}, {ITEM: vinculo('MLB1')},
                     {ITEM: vinculo(em='hoje')}, [], None):
            with self.subTest(ruim=ruim), self.assertRaises(ValueError):
                M.gravar_vinculos(ruim, self.arq)
        self.assertEqual(M.ler_vinculos(self.arq), antes)
        self.assertEqual(os.listdir(self.dir), ['ml_catalogo.json'])

    def test_gravar_acima_do_teto_e_recusado_e_mantem_o_antigo(self):
        antes = {ITEM: vinculo()}
        M.gravar_vinculos(antes, self.arq)
        muitos = {f'MLB{9200000000 + n}': vinculo(f'MLB{n}', via='lista') for n in range(10)}
        with mock.patch.object(M, 'MAX_ARQUIVO_VINCULOS', 200):
            with self.assertRaises(M.VinculosRecusados) as cm:
                M.gravar_vinculos(muitos, self.arq)
        self.assertEqual(cm.exception.saida, 2)
        self.assertEqual(M.ler_vinculos(self.arq), antes)

    def test_gravar_sobre_symlink_troca_o_link_e_nao_o_alvo(self):
        alvo = os.path.join(self.dir, 'alvo.txt')
        with open(alvo, 'w') as f:
            f.write('nao mexer')
        os.symlink(alvo, self.arq)
        M.gravar_vinculos({ITEM: vinculo()}, self.arq)
        self.assertFalse(os.path.islink(self.arq))
        with open(alvo) as f:
            self.assertEqual(f.read(), 'nao mexer')
        self.assertEqual(M.ler_vinculos(self.arq), {ITEM: vinculo()})

    def test_gitignore(self):
        if not shutil.which('git') or not os.path.exists(os.path.join(RAIZ, '.git')):
            self.skipTest('git não encontrado ou cópia fora do repositório')
        nomes = ['ml_catalogo.json', '.ml_catalogo.json.0123456789abcdef.tmp']
        r = subprocess.run(['git', '-C', RAIZ, 'check-ignore', *nomes], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.split(), nomes)


class TestVincular(T.Base):
    def setUp(self):
        super().setUp()
        self.gravar()
        self.ml = MLFalso()
        self.q = M.consulta_do_titulo(TITULO_ITEM)

    def vincular(self, vinculos=None, item_id=ITEM, titulo=TITULO_ITEM, hoje=HOJE, sessao=None):
        return M.vincular(sessao or self.sessao(self.ml.op), item_id, titulo, vinculos=vinculos, hoje=hoje)

    def caminhos(self):
        return [c.caminho + (f'?offset={c.query["offset"]}' if 'offset' in c.query else '')
                for c in self.ml.op.gets()]

    def test_prova_pela_lista_e_anota_o_vinculo(self):
        ml = self.ml
        ml.buscas[self.q] = [{'id': 'MLB51', 'status': 'active'}, {'id': 'MLB52', 'status': 'active'}]
        ml.produtos['MLB51'] = prod('MLB51', nulo=True)                       # sem lista: 404
        ml.produtos['MLB52'] = prod('MLB52', nulo=True)
        ml.listas['MLB52'] = [[linha_lista(OUTRO, 10.0)], [linha_lista(ITEM, 20.0)]]
        vinculos = {}
        self.assertEqual(self.vincular(vinculos), ('MLB52', 'lista'))
        self.assertEqual(vinculos, {ITEM: vinculo('MLB52', via='lista')})
        self.assertEqual(self.caminhos(), ['/products/search', '/products/MLB51', '/products/MLB51/items',
                                           '/products/MLB52', '/products/MLB52/items',
                                           '/products/MLB52/items?offset=1'])
        # o título só vira a consulta: nada dele vai cru para a API
        self.assertFalse(any('MARCADOR' in c.url for c in ml.op.chamadas))

    def test_prova_pelo_bbw_sem_ler_a_lista(self):
        self.ml.buscas[self.q] = [{'id': 'MLB61', 'status': 'active'}]
        self.ml.produtos['MLB61'] = prod('MLB61', ITEM, 30.0)
        vinculos = {}
        self.assertEqual(self.vincular(vinculos), ('MLB61', 'bbw'))
        self.assertEqual(vinculos, {ITEM: vinculo('MLB61', via='bbw')})
        self.assertEqual(self.caminhos(), ['/products/search', '/products/MLB61'])

    def test_titulo_identico_sem_pertenca_da_none(self):
        """O produto tem o nome igual ao título do anúncio, mas o vencedor é outro anúncio e o nosso não está na
        lista: não há vínculo, e o negativo fica anotado."""
        ml = self.ml
        ml.buscas[self.q] = [{'id': 'MLB71', 'status': 'active'}]
        ml.produtos['MLB71'] = prod('MLB71', OUTRO, 40.0, name=TITULO_ITEM)
        ml.listas['MLB71'] = [[linha_lista(OUTRO, 40.0)], [linha_lista(TERCEIRO, 41.0)]]
        vinculos = {}
        self.assertEqual(self.vincular(vinculos), (None, None))
        self.assertEqual(vinculos, {ITEM: vinculo()})
        self.assertEqual(self.caminhos(), ['/products/search', '/products/MLB71', '/products/MLB71/items',
                                           '/products/MLB71/items?offset=1'])

    def test_bbw_de_outro_anuncio_e_lista_404_nao_provam(self):
        self.ml.buscas[self.q] = [{'id': 'MLB72', 'status': 'active'}]
        self.ml.produtos['MLB72'] = prod('MLB72', OUTRO, 40.0)
        vinculos = {}
        self.assertEqual(self.vincular(vinculos), (None, None))
        self.assertEqual(vinculos, {ITEM: vinculo()})       # o 404 da lista é resposta: o negativo é conclusivo
        self.assertEqual(self.vincular(), (None, None))   # sem cache também funciona

    def test_sem_candidato_ou_sem_titulo_da_negativo(self):
        vinculos = {}
        self.assertEqual(self.vincular(vinculos), (None, None))   # a busca não acha nada
        self.assertEqual(vinculos, {ITEM: vinculo()})
        self.assertEqual(self.caminhos(), ['/products/search'])
        vinculos = {}
        self.assertEqual(self.vincular(vinculos, titulo='  ...  '), (None, None))
        self.assertEqual(vinculos, {ITEM: vinculo()})
        self.assertEqual(len(self.ml.op.gets()), 1)   # sem consulta, nenhuma chamada

    def test_negativo_volta_depois_de_7_dias(self):
        self.ml.buscas[self.q] = [{'id': 'MLB81', 'status': 'active'}]
        self.ml.produtos['MLB81'] = prod('MLB81', nulo=True)
        self.ml.listas['MLB81'] = [[linha_lista(ITEM, 10.0)]]
        for em in (HOJE, '2026-10-30'):    # 0 e 6 dias: vale o negativo, sem chamada
            with self.subTest(em=em):
                vinculos = {ITEM: vinculo(em=em)}
                self.assertEqual(self.vincular(vinculos), (None, None))
                self.assertEqual(vinculos, {ITEM: vinculo(em=em)})
                self.assertEqual(self.ml.op.gets(), [])
        for em in ('2026-10-29', '2025-01-01', '2026-11-06'):   # 7 dias, muito velho ou no futuro: tenta de novo
            with self.subTest(em=em):
                vinculos = {ITEM: vinculo(em=em)}
                antes = len(self.ml.op.gets())
                self.assertEqual(self.vincular(vinculos), ('MLB81', 'lista'))
                self.assertEqual(vinculos, {ITEM: vinculo('MLB81', via='lista')})
                self.assertGreater(len(self.ml.op.gets()), antes)
        self.assertEqual(M.vinculo_do_cache({ITEM: vinculo(em='2026-10-30')}, ITEM, HOJE), (None, None))
        self.assertIsNone(M.vinculo_do_cache({ITEM: vinculo(em='2026-10-29')}, ITEM, HOJE))
        self.assertIsNone(M.vinculo_do_cache({}, ITEM, HOJE))

    def test_vinculo_provado_do_cache_nao_chama_a_api(self):
        vinculos = {ITEM: vinculo('MLB91', '2020-01-01', 'bbw')}
        self.assertEqual(self.vincular(vinculos), ('MLB91', 'bbw'))
        self.assertEqual(self.ml.op.chamadas, [])
        self.assertEqual(vinculos, {ITEM: vinculo('MLB91', '2020-01-01', 'bbw')})

    def test_erro_passageiro_nao_anota_negativo(self):
        """Só o "não" em que toda leitura respondeu (200 ou 404) vira negativo; 5xx e resposta fora do formato não:
        sem prova, o erro sobe (R1/S1), para quem chama não confundir o inconclusivo com o negativo."""
        casos = {
            'nenhum erro': (None, None, None),
            'busca 500': ('/products/search', lambda: T.erro_http(500, {'error': 'internal_error'}), M.ErroApi),
            'busca fora do formato': ('/products/search', lambda: {'x': 1}, M.RespostaInvalida),
            'produto 500': ('/products/MLB101', lambda: T.erro_http(500, {}), M.ErroApi),
            'lista 503': ('/products/MLB101/items', lambda: T.erro_http(503, {}), M.ErroApi),
            'lista fora do formato': ('/products/MLB101/items', lambda: {'results': 'x', 'paging': {'total': 1}},
                                      M.RespostaInvalida),
        }
        for nome, (caminho, resposta, esperado) in casos.items():
            with self.subTest(nome):
                ml = MLFalso()
                ml.buscas[self.q] = [{'id': 'MLB101', 'status': 'active'}]
                ml.produtos['MLB101'] = prod('MLB101', nulo=True)
                ml.listas['MLB101'] = [[linha_lista(OUTRO, 10.0)]]

                def responder(c, original=ml.responder, caminho=caminho, resposta=resposta):
                    return resposta() if c.caminho == caminho else original(c)
                ml.op.responder = T.api_padrao(gets=responder)
                vinculos = {}
                if esperado is None:
                    self.assertEqual(M.vincular(self.sessao(ml.op), ITEM, TITULO_ITEM, vinculos=vinculos,
                                                hoje=HOJE), (None, None))
                    self.assertEqual(vinculos, {ITEM: vinculo()})
                    continue
                with self.assertRaises(esperado) as cm:
                    M.vincular(self.sessao(ml.op), ITEM, TITULO_ITEM, vinculos=vinculos, hoje=HOJE)
                if esperado is M.ErroApi:
                    self.assertNotIsInstance(cm.exception, M.RenovacaoFalhou)
                self.assertEqual(vinculos, {})
                self.assertIn(caminho, [c.caminho for c in ml.op.gets()])

    def test_erro_num_candidato_nao_impede_a_prova_por_outro(self):
        ml = self.ml
        ml.buscas[self.q] = [{'id': 'MLB111', 'status': 'active'}, {'id': 'MLB112', 'status': 'active'}]
        ml.erros['/products/MLB111'] = (500, {})
        ml.produtos['MLB112'] = prod('MLB112', nulo=True)
        ml.listas['MLB112'] = [[linha_lista(ITEM, 10.0)]]
        vinculos = {}
        self.assertEqual(self.vincular(vinculos), ('MLB112', 'lista'))
        self.assertEqual(vinculos, {ITEM: vinculo('MLB112', via='lista')})

    def test_sem_permissao_sobe_e_nao_anota(self):
        politica = (403, {'blocked_by': 'PolicyAgent', 'code': 'PA_UNAUTHORIZED_RESULT_FROM_POLICIES'})
        for prefixo in ('/products/search', '/products/MLB121', '/products/MLB121/items'):
            with self.subTest(prefixo):
                ml = MLFalso()
                ml.buscas[self.q] = [{'id': 'MLB121', 'status': 'active'}]
                ml.produtos['MLB121'] = prod('MLB121', nulo=True)
                ml.listas['MLB121'] = [[linha_lista(OUTRO, 10.0)]]
                ml.erros[prefixo] = politica
                vinculos = {}
                with self.assertRaises(M.SemPermissao) as cm:
                    M.vincular(self.sessao(ml.op), ITEM, TITULO_ITEM, vinculos=vinculos, hoje=HOJE)
                self.assertEqual(cm.exception.saida, 2)
                self.assertEqual(vinculos, {})

    def test_limite_sobe_e_nao_anota(self):
        self.ml.erros['/products/search'] = (429, {'error': 'too_many_requests'})
        vinculos = {}
        with self.assertRaises(M.Limite):
            self.vincular(vinculos)
        self.assertEqual(vinculos, {})

    def test_401_que_sobra_vira_refazer_autorizacao(self):
        self.ml.buscas[self.q] = [{'id': 'MLB131', 'status': 'active'}]
        self.ml.erros['/products/MLB131'] = (401, {'error': 'unauthorized'})
        vinculos = {}
        with self.assertRaises(M.RefazerAutorizacao):
            self.vincular(vinculos)
        self.assertEqual(vinculos, {})
        self.assertEqual(len(self.ml.op.posts()), 1)   # uma renovação só

    def test_renovacao_500_levanta_renovacao_falhou_com_1_post_e_0_get(self):
        """R1/S1: com a Sessao crua, token vencido e POST /oauth/token com 500, o vincular para na 1ª chamada
        (1 POST, 0 GET) com RenovacaoFalhou (saída 2), sem virar o "não" nem anotar nada. Antes, cada item gastava
        um POST com o Secret e voltava (None, None)."""
        self.gravar(expira_em=T.AGORA - 1)
        antes = self.lido()
        self.ml.buscas[self.q] = [{'id': 'MLB145', 'status': 'active'}]
        self.ml.op.responder = T.api_padrao(gets=self.ml.responder,
                                            token=lambda c: T.erro_http(500, {'error': 'internal_error'}))
        sessao = self.sessao(self.ml.op)
        vinculos = {ITEM: vinculo(em='2026-10-01')}   # negativo vencido: precisa da API
        with self.assertRaises(M.RenovacaoFalhou) as cm:
            M.vincular(sessao, ITEM, TITULO_ITEM, vinculos=vinculos, hoje=HOJE)
        self.assertEqual((len(self.ml.op.posts()), len(self.ml.op.gets())), (1, 0))
        self.assertEqual(cm.exception.saida, 2)
        self.assertEqual((cm.exception.status, cm.exception.codigo), (500, 'internal_error'))
        self.assertIn('[HTTP 500]', str(cm.exception))
        T.sem_marcadores(self, str(cm.exception))
        self.assertEqual(vinculos, {ITEM: vinculo(em='2026-10-01')})
        self.assertEqual(self.lido(), antes)

    def test_401_no_meio_e_renovacao_503_levanta_renovacao_falhou(self):
        self.ml.buscas[self.q] = [{'id': 'MLB146', 'status': 'active'}]
        self.ml.erros['/products/MLB146'] = (401, {'error': 'invalid_token'})
        self.ml.op.responder = T.api_padrao(gets=self.ml.responder, token=lambda c: T.erro_http(503, {}))
        vinculos = {}
        with self.assertRaises(M.RenovacaoFalhou) as cm:
            self.vincular(vinculos)
        self.assertEqual(cm.exception.status, 503)
        self.assertEqual((len(self.ml.op.posts()), self.caminhos()),
                         (1, ['/products/search', '/products/MLB146']))   # não segue para a lista
        self.assertEqual(vinculos, {})

    def test_teto_da_vista_da_sonda_sobe_sem_anotar(self):
        """Com a vista _Chamadas (teto e pausa), o teto para o vínculo no meio sem anotar nada."""
        self.ml.buscas[self.q] = [{'id': 'MLB141', 'status': 'active'}]
        self.ml.produtos['MLB141'] = prod('MLB141', nulo=True)
        self.ml.listas['MLB141'] = [[linha_lista(ITEM, 10.0)]]
        sessao = self.sessao(self.ml.op)
        contado = M._OpenerContado(self.ml.op)
        sessao.opener = contado
        chamadas = M._Chamadas(sessao, 2, self.dormidas.append, lambda: 0.5, contado)
        vinculos = {}
        with self.assertRaises(M._TetoAtingido):
            self.vincular(vinculos, sessao=chamadas)
        self.assertEqual(vinculos, {})
        self.assertEqual(chamadas.feitas, 2)
        chamadas = M._Chamadas(sessao, 3, self.dormidas.append, lambda: 0.5, contado)
        self.assertEqual(self.vincular(vinculos, sessao=chamadas), ('MLB141', 'lista'))

    def test_id_e_data_validados_antes_da_rede(self):
        for ruim in ('MLB1', '../users/me', None, 123, ITEM + '/../x', 'mlb9100000001'):
            with self.subTest(item_id=ruim), self.assertRaises(ValueError):
                self.vincular({}, item_id=ruim)
        for ruim in ('2026-13-01', '05/11/2026', '2026-11-05T00:00:00', 20261105, '20261105', '2026-W45-4'):
            with self.subTest(hoje=ruim), self.assertRaises(ValueError):
                self.vincular({}, hoje=ruim)
            with self.subTest(hoje=ruim), self.assertRaises(ValueError):
                M.vinculo_do_cache({}, ITEM, ruim)
        self.assertEqual(self.ml.op.chamadas, [])

    def test_item_id_estranho_na_lista_nao_quebra_nem_prova(self):
        self.ml.buscas[self.q] = [{'id': 'MLB151', 'status': 'active'}]
        self.ml.produtos['MLB151'] = prod('MLB151', nulo=True)
        estranhos = [{'item_id': [ITEM]}, {'item_id': {ITEM: 1}}, {'item_id': 9100000001}, {'item_id': ITEM + ' '},
                     {'item_id': None}, 'x', None]
        self.ml.listas['MLB151'] = [estranhos]
        vinculos = {}
        self.assertEqual(self.vincular(vinculos), (None, None))
        self.assertEqual(vinculos, {ITEM: vinculo()})

    def test_hoje_padrao_e_a_data_local(self):
        vinculos = {}
        M.vincular(self.sessao(self.ml.op), ITEM, TITULO_ITEM, vinculos=vinculos)
        self.assertEqual(vinculos[ITEM]['em'], time.strftime('%Y-%m-%d'))

    def lista_crua(self, pid, pagina):
        """/products/{pid}/items devolve `pagina` exatamente como está (sem o paging que o MLFalso monta)."""
        responder = self.ml.responder
        self.ml.op.responder = T.api_padrao(
            gets=lambda c: pagina if c.caminho == f'/products/{pid}/items' else responder(c))

    def test_r6_pagina_vazia_sem_paging_e_fim_da_lista_e_negativo_anotado(self):
        self.ml.buscas[self.q] = [{'id': 'MLB171', 'status': 'active'}]
        self.ml.produtos['MLB171'] = prod('MLB171', nulo=True)
        self.lista_crua('MLB171', {'results': []})
        vinculos = {}
        self.assertEqual(self.vincular(vinculos), (None, None))
        self.assertEqual(vinculos, {ITEM: vinculo()})
        self.assertEqual(self.caminhos(), ['/products/search', '/products/MLB171', '/products/MLB171/items'])

    def test_r6_pagina_vazia_com_total_maior_que_o_lido_faz_1_get(self):
        self.ml.buscas[self.q] = [{'id': 'MLB172', 'status': 'active'}]
        self.ml.produtos['MLB172'] = prod('MLB172', nulo=True)
        self.lista_crua('MLB172', {'results': [], 'paging': {'total': 500, 'offset': 0, 'limit': 50}})
        vinculos = {}
        self.assertEqual(self.vincular(vinculos), (None, None))
        self.assertEqual(vinculos, {ITEM: vinculo()})
        self.assertEqual(self.caminhos().count('/products/MLB172/items'), 1)

    def test_com_teto_e_a_vista_da_sonda_e_devolve_o_opener(self):
        """com_teto (etapa 3): a mesma _Chamadas da sonda, com pausa entre chamadas, TetoAtingido no teto e o
        opener original de volta na saída, mesmo com erro."""
        self.ml.buscas[self.q] = [{'id': 'MLB173', 'status': 'active'}]
        self.ml.produtos['MLB173'] = prod('MLB173', nulo=True)
        self.ml.listas['MLB173'] = [[linha_lista(ITEM, 10.0)]]
        sessao = self.sessao(self.ml.op)
        self.assertIs(M.TetoAtingido, M._TetoAtingido)
        vinculos = {}
        with self.assertRaises(M.TetoAtingido):
            with M.com_teto(sessao, 2) as chamadas:
                self.assertIsInstance(chamadas, M._Chamadas)
                self.assertIsInstance(sessao.opener, M._OpenerContado)
                self.vincular(vinculos, sessao=chamadas)
        self.assertIs(sessao.opener, self.ml.op)
        self.assertEqual((chamadas.feitas, vinculos), (2, {}))
        self.assertEqual(self.dormidas, [M.PAUSA_MIN + (M.PAUSA_MAX - M.PAUSA_MIN) * 0.5])   # entre a 1ª e a 2ª
        with M.com_teto(sessao, 3, dormir=self.dormidas.append, aleatorio=lambda: 1.0) as chamadas:
            self.assertEqual(self.vincular(vinculos, sessao=chamadas), ('MLB173', 'lista'))
        self.assertEqual(self.dormidas[-2:], [M.PAUSA_MAX, M.PAUSA_MAX])
        self.assertIs(sessao.opener, self.ml.op)


class TestOfertas(T.Base):
    def setUp(self):
        super().setUp()
        self.gravar()
        self.ml = MLFalso()

    def ofertas(self, pid, ids, **kw):
        return M.ofertas_do_produto(self.sessao(self.ml.op), pid, ids, **kw)

    def test_bbw_do_nosso_e_lista_dos_outros(self):
        p = prod('MLB201', ITEM, 100.5)
        p['buy_box_winner']['original_price'] = 120
        self.ml.produtos['MLB201'] = p
        self.ml.listas['MLB201'] = [[linha_lista(ITEM, 999.0), linha_lista(OUTRO, 50)]]
        r = self.ofertas('MLB201', [ITEM, OUTRO, TERCEIRO])
        self.assertEqual(r, {ITEM: M.Oferta(ITEM, 100.5, 120, 'BRL', 'new', 'bbw'),
                             OUTRO: M.Oferta(OUTRO, 50, None, 'BRL', 'new', 'lista'),
                             TERCEIRO: None})

    def test_bbw_de_outro_item_nunca_vira_oferta_do_nosso(self):
        self.ml.produtos['MLB211'] = prod('MLB211', OUTRO, 11111.11)
        self.ml.listas['MLB211'] = [[linha_lista(OUTRO, 11111.11), linha_lista(ITEM, 22.5)]]
        self.assertEqual(self.ofertas('MLB211', [ITEM]), {ITEM: M.Oferta(ITEM, 22.5, None, 'BRL', 'new', 'lista')})
        self.ml.listas['MLB211'] = [[linha_lista(OUTRO, 11111.11)]]
        self.assertEqual(self.ofertas('MLB211', [ITEM]), {ITEM: None})
        self.ml.listas.pop('MLB211')   # lista 404
        self.assertEqual(self.ofertas('MLB211', [ITEM]), {ITEM: None})

    def test_404_na_lista_e_sem_oferta(self):
        self.ml.produtos['MLB221'] = prod('MLB221', nulo=True)
        self.assertEqual(self.ofertas('MLB221', [ITEM, OUTRO]), {ITEM: None, OUTRO: None})

    def test_404_no_produto_ainda_le_a_lista(self):
        self.ml.listas['MLB231'] = [[linha_lista(ITEM, 70.0)]]
        self.assertEqual(self.ofertas('MLB231', [ITEM]), {ITEM: M.Oferta(ITEM, 70.0, None, 'BRL', 'new', 'lista')})
        self.assertEqual(self.ofertas('MLB232', [ITEM]), {ITEM: None})   # os dois 404

    def test_paginas_e_parada_quando_acha_todos(self):
        self.ml.produtos['MLB241'] = prod('MLB241', nulo=True)
        self.ml.listas['MLB241'] = [[linha_lista(OUTRO, 1.0)], [linha_lista(TERCEIRO, 2.0)], [linha_lista(ITEM, 3.0)]]
        self.assertEqual(self.ofertas('MLB241', [ITEM], paginas=2), {ITEM: None})
        self.assertEqual(self.ofertas('MLB241', [ITEM])[ITEM].preco, 3.0)
        antes = len(self.ml.gets(prefixo='/products/MLB241/items'))
        self.assertEqual(self.ofertas('MLB241', [OUTRO])[OUTRO].preco, 1.0)
        self.assertEqual(len(self.ml.gets(prefixo='/products/MLB241/items')) - antes, 1)   # achou na 1ª página

    def test_bbw_do_nosso_dispensa_a_lista(self):
        self.ml.produtos['MLB251'] = prod('MLB251', ITEM, 10.0)
        self.assertEqual(self.ofertas('MLB251', [ITEM])[ITEM].via, 'bbw')
        self.assertEqual(self.ml.gets(prefixo='/products/MLB251/items'), [])

    def test_erro_passageiro_e_sem_permissao_sobem(self):
        politica = (403, {'blocked_by': 'PolicyAgent', 'code': 'PA_UNAUTHORIZED_RESULT_FROM_POLICIES'})
        self.ml.produtos['MLB261'] = prod('MLB261', nulo=True)
        for erros, listas, esperado in (({'/products/MLB261': (500, {})}, None, M.ErroApi),
                                        ({}, (500, {}), M.ErroApi),
                                        ({'/products/MLB261': politica}, None, M.SemPermissao),
                                        ({}, politica, M.SemPermissao)):
            with self.subTest(erros=erros, listas=listas):
                self.ml.erros = dict(erros)
                self.ml.listas = {} if listas is None else {'MLB261': listas}
                antes = len(self.ml.gets(prefixo='/products/MLB261/items'))
                with self.assertRaises(esperado):
                    self.ofertas('MLB261', [ITEM])
                lidas = len(self.ml.gets(prefixo='/products/MLB261/items')) - antes
                self.assertEqual(lidas, 0 if erros else 1)   # erro no produto: a lista nem é pedida
        op = T.OpenerFalso(T.api_padrao(gets=lambda c: {'results': {'x': 1}} if c.caminho.endswith('/items')
                                        else prod('MLB262', nulo=True)))
        with self.assertRaises(M.RespostaInvalida):
            M.ofertas_do_produto(self.sessao(op), 'MLB262', [ITEM])

    def test_renovacao_500_levanta_renovacao_falhou_com_1_post_e_0_get(self):
        """R1/S1: token vencido e POST /oauth/token com 500: RenovacaoFalhou depois de 1 POST e 0 GET, nunca um
        status do produto (o item não pode virar indisponível por isso)."""
        self.gravar(expira_em=T.AGORA - 1)
        antes = self.lido()
        self.ml.produtos['MLB265'] = prod('MLB265', ITEM, 10.0)
        self.ml.op.responder = T.api_padrao(gets=self.ml.responder,
                                            token=lambda c: T.erro_http(500, {'error': 'internal_error'}))
        with self.assertRaises(M.RenovacaoFalhou) as cm:
            self.ofertas('MLB265', [ITEM, OUTRO])
        self.assertEqual((len(self.ml.op.posts()), len(self.ml.op.gets())), (1, 0))
        self.assertEqual((cm.exception.saida, cm.exception.status), (2, 500))
        self.assertEqual(self.lido(), antes)

    def test_401_na_lista_e_renovacao_502_levanta_renovacao_falhou(self):
        self.ml.produtos['MLB266'] = prod('MLB266', nulo=True)
        self.ml.erros['/products/MLB266/items'] = (401, {'error': 'invalid_token'})
        self.ml.op.responder = T.api_padrao(gets=self.ml.responder, token=lambda c: T.erro_http(502, {}))
        with self.assertRaises(M.RenovacaoFalhou) as cm:
            self.ofertas('MLB266', [ITEM])
        self.assertEqual(cm.exception.status, 502)
        self.assertEqual((len(self.ml.op.posts()), len(self.ml.op.gets())), (1, 2))

    def test_pid_e_ids_validados_antes_do_caminho(self):
        for ruim in ('../users/me', 'MLB1/../x', None, 123, 'MLB', 'MLB1?x=1'):
            with self.subTest(pid=ruim), self.assertRaises(ValueError):
                self.ofertas(ruim, [ITEM])
        for ruins in (['MLB1'], [None], [[ITEM]], [ITEM + '/../x'], ITEM, [ITEM, 'TITULO-MARCADOR']):
            with self.subTest(ids=ruins), self.assertRaises(ValueError):
                self.ofertas('MLB271', ruins)
        self.assertEqual(self.ml.op.chamadas, [])
        self.assertEqual(self.ofertas('MLB271', []), {})
        self.assertEqual(self.ml.op.chamadas, [])

    def test_linha_com_item_id_estranho_e_ignorada(self):
        self.ml.produtos['MLB281'] = prod('MLB281', nulo=True)
        self.ml.listas['MLB281'] = [[{'item_id': [ITEM], 'price': 1}, {'item_id': {ITEM: 1}}, {'item_id': 7},
                                     'x', None, linha_lista(OUTRO, 5.0)]]
        self.assertEqual(self.ofertas('MLB281', [ITEM, OUTRO]),
                         {ITEM: None, OUTRO: M.Oferta(OUTRO, 5.0, None, 'BRL', 'new', 'lista')})

    def test_campos_fora_do_formato_viram_none(self):
        self.ml.produtos['MLB291'] = prod('MLB291', nulo=True)
        linhas = [{'item_id': ITEM, 'price': '10', 'original_price': 1e9, 'currency_id': 123, 'condition': ['new']},
                  {'item_id': OUTRO, 'price': 10, 'original_price': True, 'currency_id': 'BRL', 'condition': 'used'},
                  {'item_id': TERCEIRO, 'price': 10, 'original_price': 12.5, 'currency_id': 'USD'}]
        self.ml.listas['MLB291'] = [linhas]
        r = self.ofertas('MLB291', [ITEM, OUTRO, TERCEIRO])
        self.assertEqual(r[ITEM], M.Oferta(ITEM, None, None, None, None, 'lista'))
        self.assertEqual(r[OUTRO], M.Oferta(OUTRO, 10, None, 'BRL', 'used', 'lista'))
        self.assertEqual(r[TERCEIRO], M.Oferta(TERCEIRO, 10, 12.5, 'USD', None, 'lista'))
        self.assertEqual([M.oferta_valida(o) for o in r.values()], [False, True, False])


class TestRenovacaoFalhou(T.Cli):
    """R1/S1: a recusa da renovação sem tratamento próprio sai do Sessao.renovar como RenovacaoFalhou (saída 2),
    que o _medir não captura. invalid_grant e invalid_client continuam com as exceções deles."""

    def test_sessao_converte_o_erro_do_post_e_nao_faz_get(self):
        for status, corpo in ((500, {'error': 'internal_error'}), (503, {}), (400, {'error': 'invalid_request'})):
            with self.subTest(status=status):
                self.gravar(expira_em=T.AGORA - 1)
                antes = self.lido()
                op = T.OpenerFalso(T.api_padrao(token=lambda c, s=status, b=corpo: T.erro_http(s, b)))
                with self.assertRaises(M.RenovacaoFalhou) as cm:
                    self.sessao(op).get('/users/me')
                self.assertIsInstance(cm.exception, M.ErroApi)   # quem já trata ErroApi (sondar F0 a F6) segue igual
                self.assertEqual((cm.exception.saida, cm.exception.status), (2, status))
                self.assertEqual(cm.exception.codigo, corpo.get('error'))
                self.assertTrue(cm.exception.__suppress_context__)
                T.sem_marcadores(self, str(cm.exception))
                self.assertEqual((len(op.posts()), op.gets()), (1, []))
                self.assertEqual(self.lido(), antes)

    def test_r2_mensagens_da_renovacao_falam_dos_tokens(self):
        """R2: na rodada do atualizar_precos.py ml já pode ter havido gravação; o que não mudou são os tokens."""
        for mensagem in (str(M.RenovacaoFalhou(500)), str(M.RenovacaoInvalida()), str(M.SemRefreshToken())):
            with self.subTest(mensagem=mensagem):
                self.assertIn('rode', mensagem)
                self.assertNotIn('Nada foi gravado', mensagem)
        self.assertIn('Os tokens não mudaram', str(M.RenovacaoFalhou(500)))
        self.assertIn('Os tokens não mudaram', str(M.RenovacaoInvalida()))

    def test_invalid_grant_e_invalid_client_nao_mudam(self):
        for corpo, esperado in (({'error': 'invalid_grant'}, M.RefazerAutorizacao),
                                ({'error': 'invalid_client'}, M.CredencialInvalida),
                                ({'error': 'unauthorized_client'}, M.CredencialInvalida)):
            with self.subTest(corpo=corpo):
                self.gravar(expira_em=T.AGORA - 1)
                op = T.OpenerFalso(T.api_padrao(token=lambda c, b=corpo: T.erro_http(400, b)))
                with self.assertRaises(esperado) as cm:
                    self.sessao(op).get('/users/me')
                self.assertNotIsInstance(cm.exception, M.RenovacaoFalhou)

    def test_troca_do_code_continua_erro_api(self):
        """Só a renovação vira RenovacaoFalhou: o 5xx na troca do code (autorizar) segue ErroApi, saída 1."""
        op = T.OpenerFalso(T.api_padrao(token=lambda c: T.erro_http(500, {})))
        with self.assertRaises(M.ErroApi) as cm:
            self.sessao(op).trocar_code('CODE', 'v' * 43)
        self.assertNotIsInstance(cm.exception, M.RenovacaoFalhou)
        self.assertEqual(cm.exception.saida, 1)

    def test_medir_nao_captura(self):
        contagem = collections.Counter()

        def fazer():
            raise M.RenovacaoFalhou(500)
        with self.assertRaises(M.RenovacaoFalhou):
            M._medir(contagem, fazer)
        self.assertEqual(contagem, collections.Counter())

    def test_conferir_sai_2_com_a_mensagem_da_renovacao(self):
        self.gravar_real(falta=10)
        op = T.OpenerFalso(T.api_padrao(token=lambda c: T.erro_http(500, {'error': 'internal_error'})))
        codigo, out, err = self.rodar(['conferir'], op, secret=T.SECRET)
        self.assertEqual(codigo, 2, err)
        self.assertEqual(err, f'ERRO: {M.RenovacaoFalhou(500)}\n')
        self.assertEqual((len(op.posts()), op.gets()), (1, []))
        T.sem_marcadores(self, out, err)


    def test_sondar_simples_com_renovacao_5xx_para_no_primeiro_post(self):
        """Item 6a da etapa 3: o `sondar` de F0 a F6 com o token vencido e a renovação 500 faz 1 POST e sai 2;
        antes, cada endpoint mandava um POST com o Secret e o 500 saía como status do F0, F1 e F3."""
        self.gravar_real(falta=10)
        op = T.OpenerFalso(T.api_padrao(token=lambda c: T.erro_http(500, {'error': 'internal_error'})))
        codigo, out, err = self.rodar(['sondar'], op, secret=T.SECRET)
        self.assertEqual(codigo, 2, err)
        self.assertEqual(err, f'ERRO: {M.RenovacaoFalhou(500)}\n')
        self.assertEqual((len(op.posts()), op.gets()), (1, []))
        self.assertNotIn('500', out)
        T.sem_marcadores(self, out, err)


class TestOfertaValida(unittest.TestCase):
    def test_campos_do_contrato(self):
        self.assertEqual(M.Oferta._fields, ('item_id', 'preco', 'preco_antigo', 'moeda', 'condicao', 'via'))

    def test_preco_finito_na_faixa_e_moeda_brl(self):
        def o(preco, moeda='BRL'):
            return M.Oferta(ITEM, preco, None, moeda, 'new', 'lista')
        for bom in (0.01, 10, 124.2, 9999999.99):
            self.assertTrue(M.oferta_valida(o(bom)), bom)
        for ruim in (0, 0.0, -1, 1e7, 10_000_000, 1e300, float('inf'), float('nan'), True, None, '10'):
            self.assertFalse(M.oferta_valida(o(ruim)), repr(ruim))
        for moeda in ('USD', 'brl', 'BRL ', None, ''):
            self.assertFalse(M.oferta_valida(o(10, moeda)), moeda)
        for nao_oferta in (None, {'preco': 10, 'moeda': 'BRL'}, (ITEM, 10, None, 'BRL', 'new', 'lista')):
            self.assertFalse(M.oferta_valida(nao_oferta))


class TestSondaNaoGravaVinculos(Catalogo):
    def test_sonda_nao_grava_o_arquivo_de_vinculos(self):
        ml = TestSonda.cenario(self)
        with mock.patch.object(M, 'gravar_vinculos', side_effect=AssertionError('a sonda não grava')), \
                mock.patch.object(M, 'ler_vinculos', side_effect=AssertionError('a sonda não lê')):
            codigo, out = self.direto(ml, amostra=5)
        self.assertEqual(codigo, 0, out)
        self.assertIn('F10 provados: 3 de 5 (60%) (bbw: 2, lista: 1)', out)
        self.assertFalse(os.path.exists(M.CATALOGO))


if __name__ == '__main__':
    unittest.main()
