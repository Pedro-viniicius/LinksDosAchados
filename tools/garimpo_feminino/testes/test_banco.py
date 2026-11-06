"""Testes do banco.py (etapa 2 do garimpo feminino: CA4 e CA9). Sem rede e sem o achadinhos.db.

Rodar: python3 tools/garimpo_feminino/testes/test_banco.py -v
"""
import atexit
import hashlib
import json
import os
import shutil
import signal
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
import unittest

PASTA = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix='teste-garimpo-banco-')
atexit.register(shutil.rmtree, TMP, True)
for v in ('http_proxy', 'https_proxy', 'ftp_proxy'):
    os.environ[v] = 'http://127.0.0.1:9'
os.environ['no_proxy'] = ''
os.environ['ACHADINHOS_DB'] = os.path.join(TMP, 'achadinhos.db')
os.environ['ACHADINHOS_GARIMPO_DIR'] = os.path.join(TMP, 'garimpo')
for v in ('ACHADINHOS_SHOPEE_APP_ID', 'ACHADINHOS_SHOPEE_SECRET'):
    os.environ.pop(v, None)
sys.path.insert(0, PASTA)

import banco as B  # noqa: E402

# Colunas que o plano ("Esquema e contratos") lista para cada tabela.
COLUNAS_DO_PLANO = {
    'products': {'item_id', 'shop_id', 'nome', 'product_link', 'offer_link', 'image_url', 'price_min', 'price_max',
                 'price_discount_rate', 'sales', 'rating_star', 'commission_rate', 'seller_commission_rate',
                 'shopee_commission_rate', 'commission', 'cat_l1', 'cat_l2', 'cat_l3', 'shop_name', 'shop_type',
                 'period_start', 'period_end', 'raw_json', 'first_seen', 'last_seen', 'foco_score', 'foco'},
    'product_sources': {'item_id', 'consulta_id', 'pagina', 'posicao', 'visto_em'},
    'categories': {'cat_id', 'nivel', 'pai', 'nome', 'nome_origem', 'classe', 'nicho', 'frequencia', 'saturada',
                   'bateu_teto', 'parada'},
    'shops': {'shop_id', 'nome', 'tipo', 'itens_femininos', 'catalogo_feito'},
    'campaigns': {'id', 'nome', 'commission_rate', 'period_start', 'period_end', 'raw_json'},
    'consultas': {'id', 'chave', 'fase', 'estrategia', 'cat_id', 'ultima_pagina', 'status', 'vistos', 'novos'},
    'requisicoes': {'id', 'consulta_id', 'pagina', 'em', 'operacao', 'http', 'codigo', 'ms', 'bytes', 'n_nos',
                    'novos'},
    'medicoes': {'id', 'nome', 'valor_json', 'em'},
    'test_links': {'id', 'item_id', 'short_link', 'sub_ids', 'lote', 'criado_em', 'dono_ok'},
    'conversoes': {'chave', 'relatorio', 'purchase_time', 'item_id', 'shop_id', 'sub_ids', 'comissao', 'status'},
}
VARIAVEIS = {'productCatId': 100017, 'sortType': 2, 'limit': 50}


def no(item_id, **campos):
    """Nó do productOfferV2 como a API devolve (taxas em texto decimal)."""
    base = {'itemId': item_id, 'shopId': 777, 'productName': f'Vestido longo {item_id}',
            'productLink': f'https://shopee.com.br/product/777/{item_id}',
            'offerLink': 'https://s.shopee.com.br/AbC123', 'imageUrl': 'https://down-br.img.susercontent.com/x',
            'priceMin': '49.90', 'priceMax': '59.90', 'priceDiscountRate': 20, 'sales': 1500, 'ratingStar': '4.8',
            'commissionRate': '0.12', 'sellerCommissionRate': '0.05', 'shopeeCommissionRate': '0.07',
            'commission': '5.99', 'productCatIds': [100017, 100104, 100420], 'shopName': 'Loja da Ana',
            'shopType': [1, 2], 'periodStartTime': 1762300800, 'periodEndTime': 1764892800}
    base.update(campos)
    return base


def req(**campos):
    base = {'operacao': 'productOfferV2', 'http': 200, 'codigo': None, 'ms': 640, 'bytes': 48213,
            'em': '2026-11-06T10:00:00'}
    base.update(campos)
    return base


def retrato(con):
    """Todas as linhas de todas as tabelas, para provar que nada mudou."""
    return {t: sorted(con.execute(f'SELECT * FROM {t}').fetchall(), key=repr) for t in B.TABELAS}


def sha(caminho):
    with open(caminho, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


class Falha(Exception):
    pass


class ConexaoQueFalha:
    """Repassa tudo para a conexão real e dispara `acao` na n-ésima instrução que começa com `gatilho`."""

    def __init__(self, con, gatilho, n, acao):
        self.con, self.gatilho, self.n, self.acao, self.vezes = con, gatilho, n, acao, 0

    @property
    def in_transaction(self):
        return self.con.in_transaction

    def execute(self, sql, *args):
        if sql.lstrip().startswith(self.gatilho):
            self.vezes += 1
            if self.vezes == self.n:
                self.acao()
        return self.con.execute(sql, *args)


class Base(unittest.TestCase):
    def setUp(self):
        self.pasta = tempfile.mkdtemp(dir=TMP)
        self.db = os.path.join(self.pasta, 'garimpo.db')
        self.con = B.abrir(self.db)
        self.addCleanup(self.con.close)

    def consulta(self, variaveis=None, **kw):
        kw.setdefault('fase', 'garimpar')
        return B.obter_consulta(self.con, 'productOfferV2', variaveis or VARIAVEIS, **kw)['id']

    def contar(self, tabela):
        return self.con.execute(f'SELECT COUNT(*) FROM {tabela}').fetchone()[0]

    def produto(self, item_id, *colunas):
        return self.con.execute(f"SELECT {', '.join(colunas)} FROM products WHERE item_id = ?",
                                (item_id,)).fetchone()


def ambiente_sub():
    return dict(os.environ, PYTHONPATH=PASTA, PYTHONDONTWRITEBYTECODE='1')


# ---------------------------------------------------------------- esquema
class Esquema(Base):
    def test_user_version_1(self):
        self.assertEqual(self.con.execute('PRAGMA user_version').fetchone()[0], 1)
        self.assertEqual(B.VERSAO, 1)

    def test_todas_as_tabelas_e_colunas_do_plano(self):
        tabelas = {r[0] for r in self.con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        self.assertEqual(tabelas, set(COLUNAS_DO_PLANO))
        for tabela, colunas in COLUNAS_DO_PLANO.items():
            with self.subTest(tabela=tabela):
                reais = {r[1] for r in self.con.execute(f'PRAGMA table_info({tabela})')}
                self.assertLessEqual(colunas, reais)

    def test_dedupe_e_checkpoint_sao_chaves_do_banco(self):
        pk = {r[1] for r in self.con.execute('PRAGMA table_info(products)') if r[5]}
        self.assertEqual(pk, {'item_id'})
        pk = sorted((r[5], r[1]) for r in self.con.execute('PRAGMA table_info(product_sources)') if r[5])
        self.assertEqual([c for _, c in pk], ['item_id', 'consulta_id'])
        self.con.execute("INSERT INTO consultas (chave, fase, criada_em, atualizada_em) VALUES ('k', 'f', 'a', 'a')")
        with self.assertRaises(sqlite3.IntegrityError):
            self.con.execute("INSERT INTO consultas (chave, fase, criada_em, atualizada_em) "
                             "VALUES ('k', 'g', 'a', 'a')")

    def test_status_fora_da_lista_e_recusado(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.con.execute("INSERT INTO consultas (chave, fase, status, criada_em, atualizada_em) "
                             "VALUES ('k', 'f', 'qualquer', 'a', 'a')")

    def test_reabrir_mantem_dados_e_versao(self):
        cid = self.consulta()
        B.gravar_pagina(self.con, cid, 1, [no(1)], req())
        self.con.close()
        con = B.abrir(self.db)
        self.addCleanup(con.close)
        self.assertEqual(con.execute('PRAGMA user_version').fetchone()[0], 1)
        self.assertEqual(con.execute('SELECT COUNT(*) FROM products').fetchone()[0], 1)

    def test_arquivo_novo_nasce_0600_em_wal_e_com_chaves_estrangeiras(self):
        self.assertEqual(stat.S_IMODE(os.stat(self.db).st_mode), 0o600)
        self.assertEqual(self.con.execute('PRAGMA journal_mode').fetchone()[0], 'wal')
        self.assertEqual(self.con.execute('PRAGMA foreign_keys').fetchone()[0], 1)
        with self.assertRaises(sqlite3.IntegrityError):
            self.con.execute("INSERT INTO product_sources VALUES ('9', 999, 1, 1, 'a')")

    def test_recusa_banco_de_outra_versao_sem_alterar(self):
        outro = os.path.join(self.pasta, 'achadinhos.db')
        c = sqlite3.connect(outro)
        c.execute('CREATE TABLE items (id INTEGER PRIMARY KEY, loja TEXT)')
        c.execute('PRAGMA user_version = 3')
        c.commit()
        c.close()
        antes = sha(outro)
        with self.assertRaises(B.ErroConfig):
            B.abrir(outro)
        self.assertEqual(sha(outro), antes)
        self.assertFalse(os.path.exists(outro + '-wal'))

    def test_recusa_banco_com_tabelas_e_sem_versao(self):
        outro = os.path.join(self.pasta, 'qualquer.db')
        c = sqlite3.connect(outro)
        c.execute('CREATE TABLE products (x)')
        c.commit()
        c.close()
        antes = sha(outro)
        with self.assertRaises(B.ErroConfig):
            B.abrir(outro)
        self.assertEqual(sha(outro), antes)

    def test_recusa_arquivo_que_nao_e_sqlite(self):
        outro = os.path.join(self.pasta, 'texto.db')
        with open(outro, 'w') as f:
            f.write('isto não é um banco\n' * 200)
        with self.assertRaises(B.ErroConfig):
            B.abrir(outro)

    def test_recusa_v1_incompleto(self):
        self.con.execute('DROP TABLE conversoes')
        with self.assertRaises(B.ErroConfig):
            B.abrir(self.db)

    def test_pasta_inexistente_e_erro_de_configuracao(self):
        with self.assertRaises(B.ErroConfig):
            B.abrir(os.path.join(self.pasta, 'nao', 'existe', 'garimpo.db'))

    def test_nao_toca_a_producao(self):
        for nome in ('servidor', 'coletar_shopee', 'disparo', 'genero'):
            self.assertNotIn(nome, sys.modules)
        self.assertFalse(os.path.exists(os.environ['ACHADINHOS_DB']))


# ---------------------------------------------------------------- dedupe
class Dedupe(Base):
    def test_item_repetido_conta_um_novo_e_mantem_first_seen(self):
        cid = self.consulta()
        self.assertEqual(B.gravar_pagina(self.con, cid, 1, [no(1), no(2)], req(em='2026-11-06T10:00:00')), 2)
        self.assertEqual(B.gravar_pagina(self.con, cid, 2, [no(2, priceMin='39.90', productName='Vestido novo'),
                                                          no(3)], req(em='2026-11-06T11:30:00')), 1)
        self.assertEqual(self.contar('products'), 3)
        self.assertEqual(self.produto('2', 'first_seen', 'last_seen', 'price_min', 'nome'),
                         ('2026-11-06T10:00:00', '2026-11-06T11:30:00', 39.9, 'Vestido novo'))
        self.assertEqual(self.produto('1', 'first_seen', 'last_seen'), ('2026-11-06T10:00:00',) * 2)

    def test_numero_e_texto_sao_o_mesmo_item(self):
        cid = self.consulta()
        self.assertEqual(B.gravar_pagina(self.con, cid, 1, [no(123456789012)], req()), 1)
        self.assertEqual(B.gravar_pagina(self.con, cid, 2, [no('123456789012'), no('0123456789012')], req()), 0)
        self.assertEqual(self.con.execute('SELECT item_id FROM products').fetchall(), [('123456789012',)])

    def test_repetido_na_mesma_pagina_conta_uma_vez(self):
        cid = self.consulta()
        self.assertEqual(B.gravar_pagina(self.con, cid, 1, [no(5), no(5), no(6)], req()), 2)
        self.assertEqual(self.contar('products'), 2)
        self.assertEqual(self.con.execute('SELECT vistos, novos FROM consultas').fetchone(), (3, 2))

    def test_campo_ausente_mantem_o_anterior_e_raw_json_e_o_mais_novo(self):
        cid = self.consulta()
        B.gravar_pagina(self.con, cid, 1, [no(7)], req())
        menor = {'itemId': 7, 'productName': 'Vestido 7', 'sales': 1600, 'priceMin': 'abc'}
        B.gravar_pagina(self.con, cid, 2, [menor], req())
        self.assertEqual(self.produto('7', 'sales', 'price_min', 'commission', 'cat_l3', 'shop_name'),
                         (1600, 49.9, 5.99, '100420', 'Loja da Ana'))
        self.assertEqual(json.loads(self.produto('7', 'raw_json')[0]), menor)

    def test_campos_convertidos_com_tipos_conferidos(self):
        cid = self.consulta()
        B.gravar_pagina(self.con, cid, 1, [no('42', shopId='777', productName='Saia\nmidi\x00 plissada',
                                              productCatIds=[100017, '100104'], shopType=[1, 2])], req())
        linha = self.produto('42', 'shop_id', 'nome', 'price_min', 'price_max', 'price_discount_rate', 'sales',
                             'rating_star', 'commission_rate', 'seller_commission_rate', 'shopee_commission_rate',
                             'commission', 'cat_l1', 'cat_l2', 'cat_l3', 'shop_type', 'period_start', 'period_end',
                             'offer_link')
        self.assertEqual(linha, ('777', 'Saia midi plissada', 49.9, 59.9, 20.0, 1500, 4.8, 0.12, 0.05, 0.07, 5.99,
                                 '100017', '100104', None, '[1,2]', 1762300800, 1764892800,
                                 'https://s.shopee.com.br/AbC123'))

    def test_no_com_os_tipos_que_o_r1_mediu_e_gravado_certo(self):
        """Medicoes #72 e #73: com a consulta sem pageInfo, `itemId`, `shopId`, `periodStartTime`, `periodEndTime`,
        `sales` e `priceDiscountRate` voltam como número JSON; preços, taxas e `ratingStar`, como texto decimal;
        `productCatIds` e `shopType`, como lista. Ids de valor realista (mais de 32 bits)."""
        no_r1 = {'commission': '5.99', 'commissionRate': '0.12', 'imageUrl': 'https://down-br.img.susercontent.com/x',
                 'itemId': 23000000001, 'offerLink': 'https://s.shopee.com.br/AbC123', 'periodEndTime': 1767225599,
                 'periodStartTime': 1762300800, 'priceDiscountRate': 0, 'priceMax': '59.90', 'priceMin': '49.90',
                 'productCatIds': [100017, 100104, 100420], 'productLink': 'https://shopee.com.br/product/1/2',
                 'productName': 'Vestido longo', 'ratingStar': '4.8', 'sales': 1500, 'sellerCommissionRate': '0.05',
                 'shopId': 1025679044, 'shopName': 'Loja da Ana', 'shopType': [1], 'shopeeCommissionRate': '0.07'}
        self.assertEqual(len(no_r1), 20)
        cid = self.consulta()
        self.assertEqual(B.gravar_pagina(self.con, cid, 1, [no_r1], req()), 1)
        cols = ('item_id', 'shop_id', 'period_start', 'period_end', 'sales', 'price_discount_rate', 'price_min',
                'price_max', 'rating_star', 'commission_rate', 'seller_commission_rate', 'shopee_commission_rate',
                'commission', 'cat_l1', 'cat_l2', 'cat_l3', 'shop_type', 'nome', 'shop_name')
        self.assertEqual(self.con.execute('SELECT ' + ', '.join(cols) + ' FROM products').fetchall(),
                         [('23000000001', '1025679044', 1762300800, 1767225599, 1500, 0.0, 49.9, 59.9, 4.8, 0.12,
                           0.05, 0.07, 5.99, '100017', '100104', '100420', '[1]', 'Vestido longo', 'Loja da Ana')])
        # tipos que o SQLite guarda: ids em texto, instantes e contagem em inteiro, preços e taxas em real
        self.assertEqual(self.con.execute(
            'SELECT typeof(item_id), typeof(shop_id), typeof(period_start), typeof(period_end), typeof(sales), '
            'typeof(price_min), typeof(rating_star), typeof(commission) FROM products').fetchone(),
            ('text', 'text', 'integer', 'integer', 'integer', 'real', 'real', 'real'))
        self.assertEqual(self.con.execute('SELECT item_id, pagina, posicao FROM product_sources').fetchall(),
                         [('23000000001', 1, 1)])
        self.assertEqual(json.loads(self.produto('23000000001', 'raw_json')[0]), no_r1)
        # o mesmo item vindo com o id em texto (como o datafeed ou o int64 "texto") é o mesmo produto
        self.assertEqual(B.gravar_pagina(self.con, cid, 2, [dict(no_r1, itemId='23000000001', shopId='1025679044')],
                                         req()), 0)
        self.assertEqual(self.contar('products'), 1)

    def test_valores_ilegiveis_viram_nulo(self):
        cid = self.consulta()
        B.gravar_pagina(self.con, cid, 1, [no(8, priceMin=True, ratingStar=float('nan'), sales='muitas',
                                              commission=-3, productCatIds='100017', shopType={'x': 1})], req())
        self.assertEqual(self.produto('8', 'price_min', 'rating_star', 'sales', 'commission', 'cat_l1', 'shop_type'),
                         (None,) * 6)

    def test_foco_nao_e_mexido_pela_gravacao(self):
        cid = self.consulta()
        B.gravar_pagina(self.con, cid, 1, [no(9)], req())
        self.con.execute("UPDATE products SET foco_score = 5, foco = 'alto' WHERE item_id = '9'")
        B.gravar_pagina(self.con, cid, 2, [no(9)], req())
        self.assertEqual(self.produto('9', 'foco_score', 'foco'), (5, 'alto'))

    def test_fontes_uma_por_consulta_com_a_primeira_pagina(self):
        c1 = self.consulta()
        c2 = self.consulta({**VARIAVEIS, 'sortType': 5})
        B.gravar_pagina(self.con, c1, 1, [no(1), no(2)], req(em='2026-11-06T10:00:00'))
        B.gravar_pagina(self.con, c1, 2, [no(3), no(2)], req(em='2026-11-06T10:05:00'))
        self.assertEqual(B.gravar_pagina(self.con, c2, 1, [no(2)], req(em='2026-11-06T10:10:00')), 0)
        fontes = self.con.execute("SELECT consulta_id, pagina, posicao, visto_em FROM product_sources "
                                  "WHERE item_id = '2' ORDER BY consulta_id").fetchall()
        self.assertEqual(fontes, [(c1, 1, 2, '2026-11-06T10:05:00'), (c2, 1, 1, '2026-11-06T10:10:00')])
        self.assertEqual(self.contar('product_sources'), 4)


# ---------------------------------------------------------------- checkpoint
class Checkpoint(Base):
    def test_chave_ignora_page_e_ordem_das_variaveis(self):
        a = B.chave_consulta('productOfferV2', {'page': 1, 'sortType': 2, 'productCatId': 100017, 'limit': 50})
        b = B.chave_consulta('productOfferV2', {'limit': 50, 'productCatId': 100017, 'sortType': 2, 'page': 9})
        self.assertEqual(a, b)
        self.assertNotIn('page', a)
        self.assertNotEqual(a, B.chave_consulta('productOfferV2', {**VARIAVEIS, 'limit': 20}))
        self.assertNotEqual(a, B.chave_consulta('shopOfferV2', VARIAVEIS))

    def test_chave_recusa_formato_errado(self):
        for operacao, variaveis in (('product OfferV2', {}), ('', {}), ('x', []), ('x', {1: 2}),
                                    ('x', {'a': float('nan')}), ('x', {'a': object()})):
            with self.subTest(operacao=operacao, variaveis=variaveis), self.assertRaises(ValueError):
                B.chave_consulta(operacao, variaveis)

    def test_obter_consulta_e_idempotente_e_devolve_o_checkpoint(self):
        primeira = B.obter_consulta(self.con, 'productOfferV2', {**VARIAVEIS, 'page': 1}, fase='mapa',
                                    estrategia='sort2', cat_id='100017')
        self.assertEqual(primeira, {'id': primeira['id'], 'ultima_pagina': 0, 'status': 'pendente', 'vistos': 0,
                                    'novos': 0})
        B.gravar_pagina(self.con, primeira['id'], 1, [no(1), no(2)], req())
        B.gravar_pagina(self.con, primeira['id'], 2, [no(2), no(3), no(4)], req())
        de_novo = B.obter_consulta(self.con, 'productOfferV2', {**VARIAVEIS, 'page': 3}, fase='garimpar')
        self.assertEqual(de_novo, {'id': primeira['id'], 'ultima_pagina': 2, 'status': 'pendente', 'vistos': 5,
                                   'novos': 4})
        self.assertEqual(self.con.execute('SELECT fase, estrategia, cat_id FROM consultas').fetchall(),
                         [('mapa', 'sort2', '100017')])

    def test_requisicao_da_pagina_so_com_os_campos_permitidos(self):
        cid = self.consulta()
        B.gravar_pagina(self.con, cid, 1, [no(1), no(1), no(2)], req(n_nos=99))
        linha = self.con.execute('SELECT consulta_id, pagina, em, operacao, http, codigo, ms, bytes, n_nos, novos '
                                 'FROM requisicoes').fetchone()
        self.assertEqual(linha, (cid, 1, '2026-11-06T10:00:00', 'productOfferV2', 200, None, 640, 48213, 3, 2))

    def test_requisicao_com_campo_proibido_nao_grava_nada(self):
        cid = self.consulta()
        antes = retrato(self.con)
        for extra in ({'authorization': 'SHA256 Credential=1, Signature=abc'}, {'corpo': '{}'},
                      {'cabecalhos': {}}, {'novos': 1}, {'operacao': 'x y'}, {'operacao': None},
                      {'http': '200'}, {'http': True}, {'em': '06/11/2026'}):
            with self.subTest(extra=list(extra)), self.assertRaises(ValueError):
                B.gravar_pagina(self.con, cid, 1, [no(1)], {**req(), **extra})
        with self.assertRaises(ValueError):
            B.gravar_pagina(self.con, cid, 1, [no(1)], [('operacao', 'productOfferV2')])
        self.assertEqual(retrato(self.con), antes)

    def test_data_da_requisicao_em_segundos_vira_texto(self):
        cid = self.consulta()
        quando = time.mktime((2026, 11, 6, 9, 15, 0, 0, 0, -1))
        B.gravar_pagina(self.con, cid, 1, [no(1)], req(em=quando))
        self.assertEqual(self.produto('1', 'first_seen')[0], '2026-11-06T09:15:00')

    def test_pagina_ja_gravada_e_recusada(self):
        cid = self.consulta()
        B.gravar_pagina(self.con, cid, 1, [no(1)], req())
        B.gravar_pagina(self.con, cid, 2, [no(2)], req())
        antes = retrato(self.con)
        for pagina in (1, 2):
            with self.subTest(pagina=pagina), self.assertRaises(ValueError):
                B.gravar_pagina(self.con, cid, pagina, [no(3)], req())
        self.assertEqual(retrato(self.con), antes)

    def test_pagina_e_consulta_invalidas(self):
        cid = self.consulta()
        for consulta_id, pagina, nos in ((cid, 0, []), (cid, True, []), (cid, '1', []), (cid, 1.0, []),
                                         (0, 1, []), (cid + 50, 1, []), (cid, 1, None), (cid, 1, (n for n in []))):
            with self.subTest(consulta_id=consulta_id, pagina=pagina), self.assertRaises(ValueError):
                B.gravar_pagina(self.con, consulta_id, pagina, nos, req())
        self.assertEqual(self.contar('requisicoes'), 0)

    def test_pagina_vazia_avanca_o_checkpoint(self):
        cid = self.consulta()
        self.assertEqual(B.gravar_pagina(self.con, cid, 1, [], req()), 0)
        self.assertEqual(B.obter_consulta(self.con, 'productOfferV2', VARIAVEIS, fase='x')['ultima_pagina'], 1)

    def test_consulta_encerrada_nao_aceita_pagina_e_erro_aceita(self):
        for status in ('esgotada', 'teto', 'saturada'):
            with self.subTest(status=status):
                cid = self.consulta({**VARIAVEIS, 'sortType': status})
                B.fechar_consulta(self.con, cid, status)
                self.assertIsNotNone(self.con.execute('SELECT concluida_em FROM consultas WHERE id = ?',
                                                      (cid,)).fetchone()[0])
                with self.assertRaises(ValueError):
                    B.gravar_pagina(self.con, cid, 1, [no(1)], req())
        cid = self.consulta({**VARIAVEIS, 'sortType': 'erro'})
        B.fechar_consulta(self.con, cid, 'erro')
        B.gravar_pagina(self.con, cid, 1, [no(1)], req())
        self.assertEqual(self.con.execute('SELECT status FROM consultas WHERE id = ?', (cid,)).fetchone()[0],
                         'pendente')

    def test_fechar_consulta_recusa_status_e_id_invalidos(self):
        cid = self.consulta()
        for consulta_id, status in ((cid, 'pendente'), (cid, 'qualquer'), (cid + 9, 'esgotada'), (0, 'teto')):
            with self.subTest(status=status), self.assertRaises(ValueError):
                B.fechar_consulta(self.con, consulta_id, status)

    def test_cat_id_invalido_e_recusado(self):
        with self.assertRaises(ValueError):
            self.consulta(cat_id='abc')
        self.assertEqual(self.contar('consultas'), 0)

    def test_requisicao_sem_pagina_para_o_limite(self):
        cid = self.consulta()
        rid = B.registrar_requisicao(self.con, cid, 3, req(http=200, codigo=10030, bytes=120))
        B.registrar_requisicao(self.con, None, None, req(operacao='conferir', http=429))
        self.assertEqual(self.con.execute('SELECT id, consulta_id, pagina, codigo, n_nos, novos FROM requisicoes '
                                          'ORDER BY id').fetchall(),
                         [(rid, cid, 3, 10030, None, None), (rid + 1, None, None, None, None, None)])
        self.assertEqual(self.con.execute('SELECT ultima_pagina FROM consultas').fetchone()[0], 0)
        with self.assertRaises(ValueError):
            B.registrar_requisicao(self.con, cid, 3, req(cabecalho='x'))


# ---------------------------------------------------------------- surrogate solto (R3)
SOLTO = chr(0xD83D)   # \\ud83d sem o par: json.loads aceita e o sqlite3 recusa (UnicodeEncodeError)


class Surrogates(Base):
    def test_texto_troca_o_surrogate_e_mantem_o_resto(self):
        self.assertEqual(B._texto('a' + SOLTO + 'b', 10), 'a?b')
        self.assertEqual(B._texto(SOLTO, 10), '?')
        self.assertEqual(B._texto('Vestido ' + chr(0x1F600) + ' ação', 50), 'Vestido ' + chr(0x1F600) + ' ação')
        self.assertEqual(B.sem_surrogates('x' + chr(0xDC00) + 'y'), 'x?y')

    def test_pagina_com_surrogate_e_gravada_em_todas_as_colunas_de_texto(self):
        cid = self.consulta()
        n = no(1, productName='Vestido ' + SOLTO, shopName='Loja ' + SOLTO, productLink='https://x/' + SOLTO,
               offerLink='https://y/' + SOLTO, imageUrl='https://z/' + SOLTO, shopType='tipo' + SOLTO,
               campoNovo=SOLTO)
        self.assertEqual(B.gravar_pagina(self.con, cid, 1, [n], req()), 1)
        self.assertEqual(self.produto('1', 'nome', 'shop_name', 'product_link', 'offer_link', 'image_url', 'shop_type'),
                         ('Vestido ?', 'Loja ?', 'https://x/?', 'https://y/?', 'https://z/?', 'tipo?'))
        raw = self.produto('1', 'raw_json')[0]
        self.assertTrue(raw.isascii(), 'raw_json em ASCII: o surrogate vira escape')
        self.assertEqual(json.loads(raw)['campoNovo'], SOLTO)   # nada se perde no raw_json

    def test_raw_json_guarda_emoji_e_acento_sem_perda(self):
        cid = self.consulta()
        nome = 'Maiô ' + chr(0x1F600)
        B.gravar_pagina(self.con, cid, 1, [no(1, productName=nome)], req())
        self.assertEqual(self.produto('1', 'nome')[0], nome)
        self.assertEqual(json.loads(self.produto('1', 'raw_json')[0])['productName'], nome)


# ---------------------------------------------------------------- retomada (CA4)
class Retomada(Base):
    def preparar(self):
        """Consulta com a página 1 gravada; a página 2 é a que cai no meio."""
        cid = self.consulta()
        B.gravar_pagina(self.con, cid, 1, [no(1), no(2)], req(em='2026-11-06T10:00:00'))
        return cid, [no(2, priceMin='9.90'), no(3), no(4), no(5), no(6)]

    def conferir_retomada(self, cid, pagina2, antes):
        self.assertFalse(self.con.in_transaction)
        self.assertEqual(retrato(self.con), antes)
        self.assertEqual(B.obter_consulta(self.con, 'productOfferV2', VARIAVEIS, fase='x')['ultima_pagina'], 1)
        # a retomada refaz só a página em curso
        self.assertEqual(B.gravar_pagina(self.con, cid, 2, pagina2, req(em='2026-11-06T10:01:00')), 4)
        self.assertEqual(self.con.execute('SELECT pagina FROM requisicoes ORDER BY id').fetchall(), [(1,), (2,)])
        self.assertEqual(self.contar('products'), 6)
        self.assertEqual(self.produto('2', 'price_min', 'first_seen'), (9.9, '2026-11-06T10:00:00'))
        self.assertEqual(self.con.execute('SELECT ultima_pagina, vistos, novos FROM consultas').fetchone(),
                         (2, 7, 6))

    def test_excecao_no_meio_da_pagina_nao_deixa_nada(self):
        cid, pagina2 = self.preparar()
        antes = retrato(self.con)

        def cair():
            raise Falha('caiu no 3º produto')
        falha = ConexaoQueFalha(self.con, 'INSERT INTO products', 3, cair)
        with self.assertRaises(Falha):
            B.gravar_pagina(falha, cid, 2, pagina2, req())
        self.assertEqual(falha.vezes, 3)
        self.conferir_retomada(cid, pagina2, antes)

    def test_ctrl_c_no_meio_da_pagina_desfaz_e_continua_ctrl_c(self):
        cid, pagina2 = self.preparar()
        antes = retrato(self.con)

        def ctrl_c():
            raise KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            B.gravar_pagina(ConexaoQueFalha(self.con, 'INSERT INTO product_sources', 4, ctrl_c), cid, 2, pagina2,
                            req())
        self.conferir_retomada(cid, pagina2, antes)

    def test_falha_no_commit_nao_deixa_nada(self):
        cid, pagina2 = self.preparar()
        antes = retrato(self.con)

        def disco():
            raise sqlite3.OperationalError('disk I/O error (simulado)')
        with self.assertRaises(sqlite3.OperationalError):
            B.gravar_pagina(ConexaoQueFalha(self.con, 'COMMIT', 1, disco), cid, 2, pagina2, req())
        self.conferir_retomada(cid, pagina2, antes)

    def test_falha_no_checkpoint_nao_deixa_produtos(self):
        cid, pagina2 = self.preparar()
        antes = retrato(self.con)

        def cair():
            raise Falha('caiu no checkpoint')
        with self.assertRaises(Falha):
            B.gravar_pagina(ConexaoQueFalha(self.con, 'UPDATE consultas', 1, cair), cid, 2, pagina2, req())
        self.conferir_retomada(cid, pagina2, antes)

    def test_no_sem_item_id_e_pulado_e_contado_sem_recusar_a_pagina(self):
        """R3: um nó ruim não derruba a página. Fica de fora de products e de `vistos`; `n_nos` guarda o que a API
        devolveu, então a diferença (n_nos - vistos) conta os pulados e sobrevive à retomada."""
        for i, ruim in enumerate(({'itemId': 'abc'}, {'itemId': None}, {'itemId': 0}, {'itemId': True},
                                  {'itemId': 2 ** 63}, {'productName': 'sem id'}, 'texto', None, 7)):
            with self.subTest(ruim=ruim):
                cid = B.obter_consulta(self.con, 'productOfferV2', {'caso': i}, fase='x')['id']
                base = 1000 * (i + 1)
                pagina = [no(base + 1), ruim, no(base + 2)]
                self.assertEqual(B.nos_sem_id(pagina), 1)
                self.assertEqual(B.gravar_pagina(self.con, cid, 1, pagina, req()), 2)
                self.assertEqual(self.con.execute('SELECT ultima_pagina, vistos, novos, status FROM consultas '
                                                  'WHERE id = ?', (cid,)).fetchone(), (1, 2, 2, 'pendente'))
                self.assertEqual(self.con.execute('SELECT n_nos, novos FROM requisicoes WHERE consulta_id = ?',
                                                  (cid,)).fetchall(), [(3, 2)])
                # a posição é a da página: o buraco do nó pulado continua lá
                self.assertEqual(self.con.execute('SELECT item_id, posicao FROM product_sources WHERE consulta_id = ? '
                                                  'ORDER BY posicao', (cid,)).fetchall(),
                                 [(str(base + 1), 1), (str(base + 2), 3)])
        self.assertEqual(self.contar('products'), 18)

    def test_pagina_so_com_nos_ruins_avanca_o_checkpoint_sem_produto(self):
        cid = self.consulta()
        self.assertEqual(B.gravar_pagina(self.con, cid, 1, [{'itemId': 'x'}, 'y'], req()), 0)
        self.assertEqual(self.contar('products'), 0)
        self.assertEqual(self.con.execute('SELECT ultima_pagina, vistos, novos FROM consultas').fetchone(), (1, 0, 0))
        self.assertEqual(self.con.execute('SELECT n_nos, novos FROM requisicoes').fetchall(), [(2, 0)])

    def test_nos_sem_id_conta_so_os_invalidos(self):
        self.assertEqual(B.nos_sem_id([]), 0)
        self.assertEqual(B.nos_sem_id([no(1), no(2)]), 0)
        self.assertEqual(B.nos_sem_id([no(1), {}, 'x', {'itemId': -1}]), 3)

    def test_linha_produto_sozinha_continua_recusando_no_sem_id(self):
        for ruim in ({'itemId': 'abc'}, 'texto'):
            with self.subTest(ruim=ruim), self.assertRaises(ValueError):
                B._linha_produto(ruim)

    def test_outra_conexao_nao_escreve_nem_ve_a_pagina_pela_metade(self):
        cid, pagina2 = self.preparar()
        vistos = []

        def espiar():
            outra = sqlite3.connect(self.db, timeout=0)
            try:
                vistos.append(outra.execute('SELECT COUNT(*) FROM products').fetchone()[0])
                with self.assertRaises(sqlite3.OperationalError) as ctx:
                    outra.execute("INSERT INTO medicoes (nome, valor_json, em) VALUES ('x', '1', 'a')")
                vistos.append(str(ctx.exception))
            finally:
                outra.close()
        # antes do 1º INSERT da página: só o BEGIN IMMEDIATE já segura a escrita
        B.gravar_pagina(ConexaoQueFalha(self.con, 'INSERT INTO products', 1, espiar), cid, 2, pagina2, req())
        self.assertEqual(vistos, [2, 'database is locked'])
        self.assertEqual(self.contar('products'), 6)

    def test_processo_morto_no_meio_da_pagina(self):
        """kill -9 depois de 3 produtos da página 2: nada dela fica, e a retomada refaz só ela."""
        cid, pagina2 = self.preparar()
        antes = retrato(self.con)
        script = (
            'import json, os, signal, sys\n'
            'import banco as B\n'
            'class Morre:\n'
            '    def __init__(self, con):\n'
            '        self.con, self.vezes = con, 0\n'
            '    in_transaction = property(lambda self: self.con.in_transaction)\n'
            '    def execute(self, sql, *args):\n'
            '        if sql.startswith("INSERT INTO products"):\n'
            '            self.vezes += 1\n'
            '            if self.vezes == 4:\n'
            '                os.kill(os.getpid(), signal.SIGKILL)\n'
            '        return self.con.execute(sql, *args)\n'
            'con = B.abrir(sys.argv[1])\n'
            'B.gravar_pagina(Morre(con), int(sys.argv[2]), 2, json.loads(sys.argv[3]), {"operacao": "productOfferV2"})\n'
            'print("NAO MORREU")\n'
        )
        r = subprocess.run([sys.executable, '-c', script, self.db, str(cid), json.dumps(pagina2)],
                           env=ambiente_sub(), capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, -signal.SIGKILL, r.stderr)
        self.assertNotIn('NAO MORREU', r.stdout)
        self.assertEqual(retrato(self.con), antes)
        self.conferir_retomada(cid, pagina2, antes)


# ---------------------------------------------------------------- trava
SCRIPT_TRAVA = (
    'import sys\n'
    'import banco as B\n'
    'with B.travar(sys.argv[1]):\n'
    '    print("TRAVOU", flush=True)\n'
    '    sys.stdin.read()\n'
)


class Trava(Base):
    def test_segunda_trava_no_mesmo_processo_sai_com_erro_sem_esperar(self):
        with B.travar(self.pasta):
            inicio = time.monotonic()
            with self.assertRaises(B.ErroConfig) as ctx:
                with B.travar(self.pasta):
                    self.fail('entrou com a trava ocupada')
            self.assertLess(time.monotonic() - inicio, 1)
            self.assertIn('outra rodada', str(ctx.exception))

    def test_trava_de_outro_processo_e_kill_nao_deixa_trava_velha(self):
        p = subprocess.Popen([sys.executable, '-c', SCRIPT_TRAVA, self.pasta], env=ambiente_sub(),
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        self.addCleanup(lambda: p.poll() is None and p.kill())
        self.assertEqual(p.stdout.readline().strip(), 'TRAVOU')
        with self.assertRaises(B.ErroConfig):
            with B.travar(self.pasta):
                self.fail('entrou com a trava de outro processo')
        p.kill()
        p.wait(10)
        p.stdin.close()
        p.stdout.close()
        with B.travar(self.pasta):
            pass

    def test_trava_solta_no_fim_do_bloco_mesmo_com_excecao(self):
        with B.travar(self.pasta):
            pass
        with self.assertRaises(Falha):
            with B.travar(self.pasta):
                raise Falha()
        with B.travar(self.pasta):
            pass

    def test_arquivo_da_trava_e_0600(self):
        trava = os.path.join(self.pasta, B.NOME_TRAVA)
        with open(trava, 'w'):
            pass
        os.chmod(trava, 0o644)
        with B.travar(self.pasta):
            self.assertEqual(stat.S_IMODE(os.stat(trava).st_mode), 0o600)

    def test_symlink_na_trava_e_recusado(self):
        alvo = os.path.join(self.pasta, 'alvo.txt')
        with open(alvo, 'w') as f:
            f.write('não mexer')
        os.chmod(alvo, 0o644)
        os.symlink(alvo, os.path.join(self.pasta, B.NOME_TRAVA))
        with self.assertRaises(B.ErroConfig):
            with B.travar(self.pasta):
                self.fail('seguiu o symlink')
        with open(alvo) as f:
            self.assertEqual(f.read(), 'não mexer')
        self.assertEqual(stat.S_IMODE(os.stat(alvo).st_mode), 0o644)

    def test_trava_que_e_pasta_e_recusada(self):
        os.mkdir(os.path.join(self.pasta, B.NOME_TRAVA))
        with self.assertRaises(B.ErroConfig):
            with B.travar(self.pasta):
                pass

    def test_trava_que_e_fifo_e_recusada(self):
        os.mkfifo(os.path.join(self.pasta, B.NOME_TRAVA), 0o600)
        with self.assertRaises(B.ErroConfig):
            with B.travar(self.pasta):
                self.fail('travou numa FIFO')

    def test_pasta_inexistente_e_erro_de_configuracao(self):
        with self.assertRaises(B.ErroConfig):
            with B.travar(os.path.join(self.pasta, 'nao-existe')):
                pass


if __name__ == '__main__':
    unittest.main()
