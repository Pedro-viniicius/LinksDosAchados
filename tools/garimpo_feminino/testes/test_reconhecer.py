#!/usr/bin/env python3
"""Testes do fase_reconhecer.py (etapa 6 do garimpo feminino: CA1, CA7 e CA9). Sem rede.

Rodar: python3 tools/garimpo_feminino/testes/test_reconhecer.py -v

A API é um falso que responde pela consulta enviada (`ApiRoteada`); os dois pontos de rede do coletar_shopee.py
são trocados (`comum.isolado`), o `urlopen` falha e os proxies apontam para 127.0.0.1:9. Cobrem:
- cada sonda grava a medição certa, e o api_findings.md só traz valor medido (com `#id`) ou "não medido";
- a rajada para no primeiro 10030 (ou 429), sem as esperas do backoff;
- toda requisição fica em `requisicoes` e conta no teto (`--max-req` e `max_total_requests`); retomada;
- os links das sondas de subId passam pelo `conferir_dono` e ficam só no banco (sem export nem test_links);
- a mensagem de erro da API: saneada, até 300 caracteres e só no banco; nem Secret nem `Signature=` em lugar
  nenhum;
- nenhuma consulta vem de dado externo (constantes do módulo; nomes vindos da API só em `variables`).
"""
import ast
import contextlib
import io
import json
import os
import re
import signal
import sqlite3
import subprocess
import sys
import threading
import unittest
import urllib.error
from unittest import mock

import comum  # noqa: F401  (isolamento: tem de vir antes dos módulos do garimpo)
from comum import APP_ID, CS, LINK, S, SECRET, ConferenciaFalsa, erro, http_erro

import banco  # noqa: E402
import cliente as K  # noqa: E402
import consultas as C  # noqa: E402
import fase_reconhecer as R  # noqa: E402
import garimpo as G  # noqa: E402

CAMINHO = os.path.join(comum.PASTA, 'fase_reconhecer.py')
with open(CAMINHO, encoding='utf-8') as _f:
    FONTE = _f.read()

ECO = 'ECO-DA-API-51d0e2'        # texto "vindo da API": só pode aparecer no banco
FEED = 'TEXTO-DO-FEED-77a1c0'    # nome e descrição do feed: só no banco, e nunca uma linha de dados
TETO = 7                         # páginas com itens no falso (limit 20)
CAT = '100420'                   # L3 do comum.no()
CONSTANTES = {C.INTROSPECCAO: 'introspeccao', R.RAIZES: 'raizes', R.TIPO_POR_NOME: 'tipo',
              R.P_PRODUTOS_COM_PAGINA: 'produtos', R.P_CATEGORIAS: 'categorias', R.P_BASE: 'base',
              R.P_CATEGORIA: 'categoria', R.P_LISTTYPE: 'listtype', R.P_AMS: 'ams', R.P_KEYSELLER: 'keyseller',
              R.P_ITEM: 'item', C.GERAR_LINK: 'link', C.LISTAR_FEEDS: 'feeds', C.DADOS_FEED: 'dados_feed',
              R.P_LOJAS_COM_PAGINA: 'lojas', R.P_LOJAS_SEM_PAGINA: 'lojas_sem_pagina', R.P_CAMPANHAS: 'campanhas',
              C.RELATORIO_CONVERSOES: 'conversoes'}
MEDICOES_PADRAO = {
    'schema.introspeccao', 'produtos.consulta', 'limit.20', 'limit.50', 'limit.100', 'limit.500',
    'pagina.1', 'pagina.2', 'pagina.5', 'pagina.10', 'pagina.7', 'pagina.8', 'pagina.teto',
    'sort.1', 'sort.2', 'sort.3', 'sort.4', 'sort.5', 'sort.sobreposicao', 'categoria.produto',
    'listtype.0', 'listtype.1', 'listtype.2', 'listtype.3', 'listtype.4', 'listtype.comparacao',
    'filtro.ams', 'filtro.keyseller', 'filtro.comparacao', 'int64.numero', 'int64.texto', 'taxa',
    'subid.simples', 'subid.hifen', 'subid.sublinhado', 'feeds.full', 'feeds.delta', 'feeds.dados', 'lojas',
    'campanhas', 'conversoes', 'campos.pageInfo', 'campos.combinados', 'campos.combinado.1', 'campos.combinado.10',
    'pagina50.teto'} | {f'campos.{c}' for c in C.CAMPOS_EXTRAS} | {f'pagina50.{p}' for p in R.PAGINAS_50}
RAJADA = 120
# base + limites etc.; depois campos (extras + pageInfo + 2 combinados), limit 50, rajada, subIds, feeds e o resto
REQUISICOES_PADRAO = (1 + 1 + 4 + 6 + 5 + 1 + 5 + 2 + 2 + len(C.CAMPOS_EXTRAS) + 1 + 2 + len(R.PAGINAS_50) + RAJADA
                      + 3 + 3 + 3)
LER_JSON_ORIGINAL = CS._ler_json


def tearDownModule():
    for sufixo in ('', '-wal', '-shm', '-journal'):
        assert not os.path.exists(S.DB + sufixo), 'o garimpo abriu o achadinhos.db'


# ---------- schema falso ----------
def ref(nome, kind='SCALAR'):
    return {'kind': kind, 'name': nome, 'ofType': None}


def nao_nulo(r):
    return {'kind': 'NON_NULL', 'name': None, 'ofType': r}


def lista(r):
    return {'kind': 'LIST', 'name': None, 'ofType': r}


def campo(nome, tipo, args=()):
    return {'name': nome, 'type': tipo, 'args': [{'name': a, 'type': t} for a, t in args]}


def tipos_schema(retorno='ProductOfferConnectionV2'):
    args = [('keyword', ref('String')), ('shopId', ref('Int64')), ('itemId', ref('Int64')),
            ('productCatId', ref('Int')), ('listType', ref('Int')), ('matchId', ref('Int64')),
            ('sortType', ref('Int')), ('page', ref('Int')), ('limit', ref('Int')), ('isAMSOffer', ref('Boolean')),
            ('isKeySeller', ref('Boolean'))]
    return [
        {'kind': 'OBJECT', 'name': 'Query', 'fields': [
            campo('productOfferV2', nao_nulo(ref(retorno, 'OBJECT')), args),
            campo('shopOfferV2', ref('ShopConnection', 'OBJECT')),
            campo('listItemFeeds', lista(ref('Feed', 'OBJECT')))]},
        {'kind': 'OBJECT', 'name': 'Mutation', 'fields': [
            campo('generateShortLink', ref('ShortLinkResult', 'OBJECT'),
                  [('input', nao_nulo(ref('ShortLinkInput', 'INPUT_OBJECT')))])]},
        {'kind': 'OBJECT', 'name': retorno, 'fields': [
            campo('nodes', lista(ref('ProductOfferV2', 'OBJECT'))), campo('pageInfo', nao_nulo(ref('PageInfo', 'OBJECT')))]},
        {'kind': 'OBJECT', 'name': 'ProductOfferV2', 'fields': [campo(c, ref('String')) for c in C.CAMPOS_PRODUTO]},
        {'kind': 'OBJECT', 'name': 'PageInfo', 'fields': [campo('page', ref('Int')), campo('limit', ref('Int')),
                                                          campo('hasNextPage', ref('Boolean'))]},
        {'kind': 'SCALAR', 'name': 'Int64', 'fields': None},
        {'kind': 'INPUT_OBJECT', 'name': 'ShortLinkInput', 'fields': None,
         'inputFields': [{'name': 'originUrl', 'type': ref('String')}, {'name': 'subIds', 'type': lista(ref('String'))}]},
    ]


def schema(tipos=None):
    return {'queryType': {'name': 'Query'}, 'mutationType': {'name': 'Mutation'}, 'types': tipos or tipos_schema()}


def nos(ids, **extra):
    return [{'itemId': i, 'shopId': 777, **extra} for i in ids]


def pagina(operacao, lista_nos, *, tem_proxima=False):
    return {'data': {operacao: {'nodes': lista_nos, 'pageInfo': {'page': 1, 'limit': 20, 'hasNextPage': tem_proxima}}}}


def base(lista_nos):
    return {'data': {'productOfferV2': {'nodes': lista_nos}}}


LIST_TYPES_FALSOS = {0: range(101, 121), 1: range(1, 21), 2: range(1, 11), 3: range(1, 21), 4: range(5, 25)}


class ApiRoteada(comum.ApiFalsa):
    """Falso da API que responde pela consulta enviada. `trocas[nome]` (resposta, exceção ou função(variáveis)
    que devolve um dos dois, ou None para o padrão) troca a resposta de uma consulta. `limite_na_rajada = k`
    responde 10030 (ou `resposta_limite`) no k-ésimo pedido da rajada."""

    def __init__(self, **trocas):
        super().__init__()
        self.trocas = trocas
        self.limite_na_rajada = None
        self.resposta_limite = erro(CS.ERRO_LIMITE, 'limite')
        self.rajada = 0
        self.depois_do_item = False
        self.campos_nulos = set()     # campo que derruba a consulta ("got null for non-null")
        self.pagina_quebra = set()    # idem, para os campos do pageInfo
        self.desconhecidas = []
        self.tipos = {t['name']: t for t in tipos_schema()}

    def __call__(self, req, timeout=None):
        self.pedidos.append(req)
        self.timeouts.append(timeout)
        corpo = json.loads(req.data)
        r = self.responder(corpo['query'], corpo['variables'])
        if isinstance(r, BaseException):
            raise r
        return comum.Resp(r if isinstance(r, bytes) else json.dumps(r).encode())

    def nomes(self):
        return [CONSTANTES.get(c['query'], '?') for c in self.corpos()]

    def responder(self, query, v):
        nome = CONSTANTES.get(query)
        if query.startswith('query SondaCampos('):
            nome = 'campos'
            self.consulta_atual = query
            pedidos = set(re.findall(r'\w+', query.split('nodes {')[1]))
            if pedidos & (self.campos_nulos | self.pagina_quebra):
                return erro(10010, 'graphql: got null for non-null')
        if nome is None:
            self.desconhecidas.append(query)
            return erro(1, 'consulta desconhecida')
        if nome == 'item':
            self.depois_do_item = True
        elif nome == 'base' and self.depois_do_item and v['limit'] == R.LIMITE_SONDA:   # a pagina50 usa 50
            self.rajada += 1
            if self.limite_na_rajada is not None and self.rajada >= self.limite_na_rajada:
                return self.resposta_limite
        troca = self.trocas.get(nome)
        if callable(troca) and not isinstance(troca, BaseException):
            troca = troca(v)
        if troca is not None:
            return troca
        return getattr(self, 'r_' + nome)(v)

    def r_introspeccao(self, v):
        return {'data': {'__schema': schema()}}

    def r_raizes(self, v):
        return {'data': {'__schema': {'queryType': {'name': 'Query'}, 'mutationType': {'name': 'Mutation'}}}}

    def r_tipo(self, v):
        return {'data': {'__type': self.tipos.get(v['name'])}}

    def r_produtos(self, v):
        return {'data': {'productOfferV2': {'nodes': [comum.no(i) for i in range(1, 21)],
                                            'pageInfo': {'page': 1, 'limit': 20, 'hasNextPage': True}}}}

    def r_categorias(self, v):
        return base([comum.no(i) for i in range(1, 21)])

    def r_base(self, v):
        if v['page'] > TETO:
            return base([])
        limite = min(v['limit'], 100)
        inicio = (v['page'] - 1) * limite + 1 + (v['sortType'] - 1) * 5
        return base(nos(range(inicio, inicio + limite)))

    def r_categoria(self, v):
        return base(nos(range(1, 21)))

    def r_listtype(self, v):
        return base(nos(LIST_TYPES_FALSOS[v['listType']]))

    def r_ams(self, v):
        return base(nos(range(1, 11)))

    def r_keyseller(self, v):
        return base(nos(range(3, 13)))

    def r_item(self, v):
        if not isinstance(v['itemId'], str):
            return erro(10010, 'wrong type')   # o relato do brief: Int64 como número dá 10010
        return base(nos([int(v['itemId'])]))

    def r_link(self, v):
        return {'data': {'generateShortLink': {'shortLink': LINK}}}

    def r_campos(self, v):
        b = base(nos(range(1, 51)))
        if 'pageInfo' in self.consulta_atual:
            b['data']['productOfferV2']['pageInfo'] = {'page': 1, 'limit': 50, 'hasNextPage': True}
        return b

    def r_feeds(self, v):
        modo = v['feedMode']
        return {'data': {'listItemFeeds': {'feeds': [
            {'datafeedId': f'{modo}-9|2026', 'referenceId': 'ref', 'datafeedName': 'Nome ' + FEED, 'date': '2026-11-06',
             'description': 'Descricao ' + FEED, 'totalCount': 123456 if modo == 'FULL' else 77, 'feedMode': modo}]}}}

    def r_dados_feed(self, v):
        linha = json.dumps({'itemId': 1, 'itemName': 'Vestido ' + ECO, 'categoryLv1Name': 'Moda', 'price': '9.90'})
        return {'data': {'getItemFeedData': {'rows': [{'columns': linha, 'updateType': None}], 'pageInfo': {
            'offset': 0, 'limit': v['limit'], 'totalCount': 123456, 'hasMore': True}}}}

    def r_lojas_sem_pagina(self, v):
        return {'data': {'shopOfferV2': {'nodes': [{'shopId': 777, 'shopName': 'Loja ' + ECO}]}}}

    def r_lojas(self, v):
        return pagina('shopOfferV2', [{'shopId': 777, 'shopName': 'Loja ' + ECO, 'commissionRate': '0.1'}],
                      tem_proxima=True)

    def r_campanhas(self, v):
        return {'data': {'shopeeOfferV2': {'nodes': []}}}

    def r_conversoes(self, v):
        return {'data': {'conversionReport': {
            'nodes': [{'purchaseTime': 1, 'conversionId': 'c-' + ECO, 'utmContent': 'fem-' + ECO}],
            'pageInfo': {'limit': 20, 'hasNextPage': True, 'scrollId': 'SCROLL-' + ECO}}}}


# ---------- rodada ----------
class Resultado:
    def __init__(self, codigo, out, err, api, conferencia, esperas, pasta):
        self.codigo, self.out, self.err = codigo, out, err
        self.api, self.conferencia, self.esperas, self.pasta = api, conferencia, esperas, pasta

    @property
    def banco(self):
        return os.path.join(self.pasta, 'garimpo.db')

    def linhas(self, sql, *args):
        con = sqlite3.connect(f'file:{self.banco}?mode=ro', uri=True)
        try:
            return con.execute(sql, args).fetchall()
        finally:
            con.close()

    def medicoes(self):
        """{nome: (id, valor)} da última medição de cada nome."""
        return {n: (i, json.loads(v)) for i, n, v in self.linhas('SELECT id, nome, valor_json FROM medicoes '
                                                                 'ORDER BY id')}

    def valor(self, nome):
        return self.medicoes()[nome][1]

    def ler(self, relativo):
        with open(os.path.join(self.pasta, relativo), encoding='utf-8') as f:
            return f.read()

    @property
    def findings(self):
        return self.ler(R.ARQ_FINDINGS)

    @property
    def log(self):
        nomes = sorted(os.listdir(os.path.join(self.pasta, 'logs')))
        return '\n'.join(self.ler(os.path.join('logs', n)) for n in nomes)


def rodar(argv=None, *, pasta=None, api=None, conferencia=None, achados=None):
    pasta = pasta or comum.nova_pasta()
    arq_achados = os.path.join(pasta, 'achados-teste.json')
    if achados is not None:
        with open(arq_achados, 'w', encoding='utf-8') as f:
            json.dump(achados, f)
    elif os.path.exists(arq_achados):
        os.remove(arq_achados)
    env = {'ACHADINHOS_GARIMPO_DIR': pasta, 'ACHADINHOS_SHOPEE_APP_ID': APP_ID, 'ACHADINHOS_SHOPEE_SECRET': SECRET}
    api = api if api is not None else ApiRoteada()
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.dict(os.environ, env), mock.patch.object(G, 'ACHADOS', arq_achados), \
            mock.patch.object(G, 'CATEGORIAS', os.path.join(pasta, 'nao-existe.json')), \
            comum.isolado(api, conferencia) as (api, conf, esperas), \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        codigo = G.main(['reconhecer'] + list(argv or []))
    return Resultado(codigo, out.getvalue(), err.getvalue(), api, conf, esperas, pasta)


class Base(unittest.TestCase):
    def sem_vazamento(self, r):
        """CA5: nem o Secret nem a assinatura em stdout, stderr, log, banco ou docs; o eco da API nunca fora do
        banco."""
        tudo = comum.conteudo_da_pasta(r.pasta)
        self.assertNotIn(SECRET.encode(), tudo)
        self.assertNotIn(b'Signature=', tudo)
        for texto in (r.out, r.err, r.log):
            self.assertNotIn(SECRET, texto)
            self.assertNotIn('Signature=', texto)
            self.assertNotIn(ECO, texto)
            self.assertNotIn('Traceback', texto)
        if os.path.exists(os.path.join(r.pasta, R.ARQ_FINDINGS)):
            self.assertNotIn(ECO, r.findings)
        self.assertIs(CS._ler_json, LER_JSON_ORIGINAL)   # o leitor original voltou
        self.assertEqual(r.api.desconhecidas, [])

    def findings_honesto(self, r):
        """CA1: toda linha de dado do findings aponta uma medição que existe, ou diz "não medido"."""
        ids = {i for (i,) in r.linhas('SELECT id FROM medicoes')}
        for linha in r.findings.splitlines():
            if not linha.startswith(('- ', '| ')) or re.fullmatch(r'\|[-| ]+\|', linha) \
                    or linha.startswith(('| limit pedido', '| page (', '| sortType |', '| listType |', '| campo |')):
                continue
            with self.subTest(linha=linha):
                self.assertTrue('(medicoes #' in linha or R.NAO_MEDIDO in linha)
                for n in re.findall(r'medicoes #(\d+)', linha):
                    self.assertIn(int(n), ids)


# ---------- CA1: cada sonda grava a medição certa ----------
class TestRodadaCompleta(Base):
    @classmethod
    def setUpClass(cls):
        cls.r = rodar()

    def test_o_findings_termina_com_o_ponteiro_para_a_interpretacao(self):
        """A interpretação (docs/api_interpretacao.md) é escrita à mão; o findings é gerado e sobrescrito, então só
        leva o ponteiro, no fim, a cada geração (com medições ou sem nenhuma)."""
        ultima = self.r.findings.rstrip('\n').split('\n')[-1]
        self.assertEqual(R.ARQ_INTERPRETACAO, 'docs/api_interpretacao.md')
        self.assertIn('`docs/api_interpretacao.md`', ultima)
        self.assertTrue(R.gerar_findings({}).rstrip('\n').endswith(ultima))

    def test_saida_0_e_uma_medicao_por_sonda(self):
        r = self.r
        self.assertEqual(r.codigo, 0, r.err)
        self.assertEqual(set(r.medicoes()), MEDICOES_PADRAO)
        self.assertEqual(r.linhas('SELECT COUNT(*) FROM medicoes'), [(len(MEDICOES_PADRAO),)])
        self.assertTrue(r.log.rstrip().endswith('SAIDA=0'))
        self.sem_vazamento(r)

    def test_schema(self):
        v = self.r.valor('schema.introspeccao')
        self.assertTrue(v['ok'])
        self.assertEqual(v['n_tipos'], len(tipos_schema()))
        po = v['resumo']['productOfferV2']
        self.assertEqual(po['argumentos']['productCatId'], 'Int')
        self.assertEqual(po['argumentos']['matchId'], 'Int64')
        self.assertEqual(po['retorno'], 'ProductOfferConnectionV2!')
        self.assertEqual(po['campos_do_no'], sorted(C.CAMPOS_PRODUTO))
        self.assertEqual(po['campos_do_pageinfo'], ['hasNextPage', 'limit', 'page'])
        self.assertEqual(po['tipos_dos_argumentos'], {'Int64': 'SCALAR'})   # os escalares padrão não vêm na lista
        self.assertEqual(v['resumo']['generateShortLink'], {'argumentos': {'input': 'ShortLinkInput!'}})
        self.assertTrue(v['resumo']['operacoes']['listItemFeeds'])
        self.assertFalse(v['resumo']['operacoes']['conversionReport'])
        salvo = json.loads(self.r.ler(R.ARQ_SCHEMA))
        self.assertEqual(salvo['origem'], '__schema')
        self.assertEqual(salvo['__schema'], schema())

    def test_produtos_limit_e_paginas(self):
        r = self.r
        v = r.valor('produtos.consulta')
        self.assertEqual((v['n_nos'], v['page_info']), (20, {'page': 1, 'limit': 20, 'tem_proxima': True}))
        self.assertIn('productCatIds', v['campos'])
        self.assertIn('periodEndTime', v['ausentes'])
        self.assertEqual(v['tipos']['itemId'], 'numero')
        self.assertEqual(v['amostra'], {'item_id': '1', 'shop_id': '777', 'cat_ids': ['100017', '100104', CAT]})
        self.assertEqual({n: r.valor(f'limit.{n}')['n_nos'] for n in R.LIMITES}, {20: 20, 50: 50, 100: 100, 500: 100})
        teto = r.valor('pagina.teto')
        self.assertEqual((teto['ultima_util'], teto['primeira_inutil'], teto['exata']), (TETO, TETO + 1, True))
        self.assertEqual(teto['paginas_medidas'], [1, 2, 5, 7, 8, 10])
        self.assertEqual(r.valor('pagina.10')['n_nos'], 0)
        pedidas = [c['variables']['page'] for c in r.api.corpos() if c['query'] == R.P_BASE][4:10]
        self.assertEqual(pedidas, [1, 2, 5, 10, 7, 8])   # saltos e depois bissecção

    def test_ordens_list_types_e_filtros(self):
        r = self.r
        self.assertEqual(r.valor('sort.sobreposicao')['comuns'],
                         {'1x2': 15, '1x3': 10, '1x4': 5, '1x5': 0, '2x3': 15, '2x4': 10, '2x5': 5, '3x4': 15,
                          '3x5': 10, '4x5': 15})
        comp = r.valor('listtype.comparacao')
        self.assertEqual(comp['cat_id'], CAT)
        self.assertEqual({k: x['comuns_com_categoria'] for k, x in comp['list_types'].items()},
                         {'0': 0, '1': 20, '2': 10, '3': 20, '4': 16})
        corpos = r.api.corpos()
        cat = [c['variables'] for c in corpos if c['query'] == R.P_CATEGORIA]
        self.assertEqual(cat, [{'productCatId': int(CAT), 'page': 1, 'limit': 20}])
        lts = [c['variables'] for c in corpos if c['query'] == R.P_LISTTYPE]
        self.assertEqual([x['listType'] for x in lts], [0, 1, 2, 3, 4])
        self.assertTrue(all(x['matchId'] == CAT for x in lts))   # Int64 como texto (padrão do achados.json)
        filtros = r.valor('filtro.comparacao')
        self.assertEqual(filtros['ams'], {'n_nos': 10, 'comuns_com_sort1': 10})
        self.assertEqual(filtros['keyseller'], {'n_nos': 10, 'comuns_com_sort1': 10})
        ams = [c['variables'] for c in corpos if c['query'] == R.P_AMS]
        self.assertEqual(ams, [{'keyword': R.TERMO, 'sortType': 1, 'isAMSOffer': True, 'page': 1, 'limit': 20}])

    def test_int64_como_numero_e_como_texto(self):
        r = self.r
        enviados = [c['variables'] for c in r.api.corpos() if c['query'] == R.P_ITEM]
        self.assertEqual(enviados, [{'shopId': 777, 'itemId': 1, 'page': 1, 'limit': 20},
                                    {'shopId': '777', 'itemId': '1', 'page': 1, 'limit': 20}])
        numero, texto = r.valor('int64.numero'), r.valor('int64.texto')
        self.assertEqual((numero['ok'], numero['codigo']), (False, 10010))
        self.assertEqual((texto['ok'], texto['ids']), (True, ['1']))
        self.assertIn('Como número: não medido (a sonda falhou: código 10010)', r.findings)

    def test_rajada_sem_limite_vai_ate_120_em_tres_degraus(self):
        v = self.r.valor('taxa')
        self.assertEqual((v['enviadas'], v['maximo'], v['parou_por'], v['primeiro_limite_na']),
                         (120, 120, 'fim', None))
        self.assertEqual([(d['taxa_alvo'], d['enviadas'], d['pausa']) for d in v['degraus']],
                         [(1, 40, 0.875), (2, 40, 0.375), (4, 40, 0.125)])
        self.assertEqual(self.r.api.rajada, 120)

    def test_feeds_e_outras_consultas_so_com_nomes_e_contagens(self):
        r = self.r
        feeds = r.valor('feeds.full')
        self.assertEqual((feeds['n_feeds'], feeds['total']), (1, 123456))
        self.assertEqual(feeds['escolhido'], {'datafeed_id': 'FULL-9|2026', 'feed_mode': 'FULL'})
        self.assertEqual(feeds['feeds'][0]['nome'], 'Nome ' + FEED)              # só no banco
        self.assertEqual(r.valor('feeds.delta')['total'], 77)
        self.assertEqual([c['variables'] for c in r.api.corpos() if c['query'] == C.LISTAR_FEEDS],
                         [{'feedMode': 'FULL'}, {'feedMode': 'DELTA'}])
        dados = r.valor('feeds.dados')
        self.assertEqual((dados['total'], dados['n_linhas'], dados['tem_mais'], dados['colunas_de_categoria']),
                         (123456, 1, True, ['categoryLv1Name']))
        self.assertEqual(dados['colunas'], ['categoryLv1Name', 'itemId', 'itemName', 'price'])
        enviado = [c['variables'] for c in r.api.corpos() if c['query'] == C.DADOS_FEED]
        self.assertEqual(enviado, [{'datafeedId': 'FULL-9|2026', 'offset': 0, 'limit': 500}])
        self.assertNotIn(FEED, r.findings)
        self.assertEqual(r.valor('lojas')['campos'], ['commissionRate', 'shopId', 'shopName'])
        self.assertEqual(r.valor('campanhas')['n_nos'], 0)
        conv = r.valor('conversoes')
        self.assertEqual((conv['n_nos'], conv['tem_scroll_id'], conv['campos']),
                         (1, True, ['conversionId', 'purchaseTime', 'utmContent']))
        janela = [c['variables'] for c in r.api.corpos() if c['query'] == C.RELATORIO_CONVERSOES][0]
        self.assertTrue(janela['purchaseTimeStart'].isdigit() and janela['purchaseTimeEnd'].isdigit())   # Int64: texto
        # nenhum valor de linha do feed, de loja ou de conversão foi guardado
        self.assertNotIn(ECO.encode(), comum.conteudo_da_pasta(r.pasta))

    def test_toda_requisicao_fica_em_requisicoes(self):
        r = self.r
        self.assertEqual(len(r.api.pedidos), REQUISICOES_PADRAO)
        self.assertEqual(r.linhas('SELECT COUNT(*) FROM requisicoes'), [(REQUISICOES_PADRAO,)])
        operacoes = dict(r.linhas('SELECT operacao, COUNT(*) FROM requisicoes GROUP BY operacao'))
        self.assertEqual(operacoes['schema'], 1)   # __schema vira "schema" (o banco só aceita nome com letra)
        self.assertEqual(operacoes['generateShortLink'], 3)
        self.assertIn(f'requisições nesta rodada: {REQUISICOES_PADRAO}.', r.log)
        self.assertEqual(r.linhas('SELECT COUNT(*) FROM products'), [(0,)])

    def test_findings_aponta_as_medicoes(self):
        r = self.r
        self.findings_honesto(r)
        f = r.findings
        m = r.medicoes()
        self.assertIn(f'| 500 | 100 | (medicoes #{m["limit.500"][0]}) |', f)
        self.assertIn('Argumento `productCatId` existe: sim', f)
        self.assertIn('última página com itens novos: 7; primeira sem itens ou repetida: 8; exata: sim', f)
        self.assertIn('| 4 | 20 | 16 |', f)
        self.assertIn('Requisições: 120 de 120; parou por: fim; primeiro 10030/429 na requisição: nenhum', f)
        self.assertIn('colunas de categoria: `categoryLv1Name`', f)
        self.assertIn('Separador dos subIds no relatório de conversões: não medido', f)
        self.assertNotIn('s.shopee.com.br', f)

    def test_links_das_sondas_conferidos_e_so_no_banco(self):
        r = self.r
        for nome, sub_ids in R.SUBIDS:
            v = r.valor(f'subid.{nome}')
            self.assertEqual((v['ok'], v['link_valido'], v['dono_ok'], v['link'], v['sub_ids']),
                             (True, True, True, LINK, list(sub_ids)))
        self.assertEqual(r.conferencia.links, [LINK] * 3)
        enviados = [c['variables'] for c in r.api.corpos() if c['query'] == C.GERAR_LINK]
        self.assertEqual([e['input']['subIds'] for e in enviados], [list(s) for _, s in R.SUBIDS])
        self.assertTrue(all(e['input']['originUrl'] == 'https://shopee.com.br/product/777/1' for e in enviados))
        self.assertIn('-', R.SUBIDS[1][1][1])
        self.assertIn('_', R.SUBIDS[2][1][1])
        self.assertEqual(r.linhas('SELECT COUNT(*) FROM test_links'), [(0,)])
        self.assertFalse(os.path.exists(os.path.join(r.pasta, 'exports')))
        self.assertNotIn(LINK, r.log + r.out + r.err)


# ---------- CA1: "não medido" quando a sonda falha ----------
class TestFalhas(Base):
    def test_sonda_que_falha_vira_nao_medido_e_a_rodada_segue(self):
        api = ApiRoteada(base=lambda v: erro(10010, ECO) if v['limit'] == 500 else None,
                         feeds=http_erro(400, corpo=erro(10020, ECO)),
                         lojas=b'nao e json')
        r = rodar(api=api)
        self.assertEqual(r.codigo, 0, r.err)
        v = r.valor('limit.500')
        self.assertEqual((v['ok'], v['falha'], v['codigo']), (False, 'erro_api', 10010))
        self.assertEqual(v['mensagem'], ECO)
        feeds = r.valor('feeds.full')
        self.assertEqual((feeds['ok'], feeds['codigo'], feeds['http'], feeds['mensagem']), (False, 10020, 400, ECO))
        self.assertNotIn('feeds.dados', r.medicoes())   # sem lista, a página do feed não é pedida
        self.assertEqual(r.valor('lojas')['falha'], 'resposta_invalida')
        f = r.findings
        self.assertRegex(f, r'\| 500 \| não medido \(a sonda falhou: código 10010\) \(medicoes #\d+\) \| \|')
        self.assertIn('`listItemFeeds` FULL: não medido (a sonda falhou: código 10020, HTTP 400)', f)
        self.assertIn(f'`getItemFeedData` (1 página, limit {R.LIMITE_FEED}): não medido\n', f)
        self.assertIn('`shopOfferV2`: não medido (a sonda falhou: resposta fora do formato)', f)
        self.findings_honesto(r)
        self.sem_vazamento(r)

    def test_formato_errado_guarda_o_motivo_fixo(self):
        api = ApiRoteada(produtos={'data': {'productOfferV2': {'nodes': [], 'pageInfo': {'page': 'x'}}}})
        r = rodar(api=api)
        v = r.valor('produtos.consulta')
        self.assertEqual((v['falha'], v['motivo']), ('resposta_invalida', C.M_PAGE))
        self.assertIn(f'resposta fora do formato: {C.M_PAGE}', r.findings)
        self.assertTrue(r.valor('produtos.categorias')['ok'])   # a variante só com ids e categorias entra
        self.assertEqual(r.valor('categoria.produto')['cat_id'], CAT)

    def test_sem_amostra_as_sondas_que_dependem_dela_ficam_nao_medidas(self):
        vazio = base([])
        api = ApiRoteada(produtos=pagina('productOfferV2', []), categorias=vazio, base=vazio)
        r = rodar(api=api)
        self.assertEqual(r.codigo, 0, r.err)
        nomes = set(r.medicoes())
        for nome in ('categoria.produto', 'listtype.0', 'int64.numero', 'subid.simples'):
            self.assertNotIn(nome, nomes)
        self.assertNotIn('link', api.nomes())
        self.assertEqual(r.valor('pagina.teto')['ultima_util'], 0)
        f = r.findings
        self.assertIn('`productCatId` (referência): não medido\n', f)
        self.assertIn('Como texto: não medido\n', f)
        self.assertIn('`sonda_sub`: não medido\n', f)
        self.findings_honesto(r)
        self.sem_vazamento(r)

    def test_introspeccao_acima_de_2mb_cai_nas_consultas_type(self):
        grande = b'{"data": {"__schema": "' + b'x' * (2 * 1024 * 1024) + b'"}}'
        api = ApiRoteada(introspeccao=grande)
        r = rodar(api=api)
        self.assertEqual(r.codigo, 0, r.err)
        v = r.valor('schema.introspeccao')
        self.assertEqual((v['ok'], v['falha'], v['bytes']), (False, 'acima_de_2mb', 2 * 1024 * 1024 + 1))
        self.assertEqual(api.nomes()[:3], ['base', 'introspeccao', 'raizes'])   # o portão vem antes de tudo
        nomes_pedidos = [c['variables']['name'] for c in api.corpos() if c['query'] == R.TIPO_POR_NOME]
        self.assertEqual(nomes_pedidos, ['Query', 'Mutation', 'ProductOfferConnectionV2', 'Int64',
                                         'ProductOfferV2', 'PageInfo', 'ShortLinkInput'])
        parcial = r.valor('schema.parcial')
        self.assertEqual(parcial['tipos_lidos'], nomes_pedidos)
        self.assertEqual(parcial['resumo']['productOfferV2']['argumentos']['productCatId'], 'Int')
        self.assertEqual(parcial['resumo']['productOfferV2']['campos_do_no'], sorted(C.CAMPOS_PRODUTO))
        salvo = json.loads(r.ler(R.ARQ_SCHEMA))
        self.assertEqual((salvo['origem'], salvo['parcial'], len(salvo['tipos'])), ('__type', True, 7))
        self.assertIn('Introspecção completa: não medido (a sonda falhou: resposta acima de 2 MB)', r.findings)
        self.assertIn('Argumento `productCatId` existe: sim', r.findings)
        self.findings_honesto(r)
        self.sem_vazamento(r)

    def test_introspeccao_recusada_e_type_recusado_seguem_para_as_sondas_fixas(self):
        api = ApiRoteada(introspeccao=erro(10010, ECO), raizes=erro(10010, ECO), tipo=erro(10010, ECO))
        r = rodar(api=api)
        self.assertEqual(r.codigo, 0, r.err)
        self.assertEqual([c['variables']['name'] for c in api.corpos() if c['query'] == R.TIPO_POR_NOME],
                         ['Query'])   # sem raiz lida, tenta só o nome padrão
        self.assertFalse(r.valor('schema.parcial')['ok'])
        self.assertFalse(os.path.exists(os.path.join(r.pasta, R.ARQ_SCHEMA)))
        self.assertTrue(r.valor('limit.20')['ok'])
        self.assertIn('Consultas `__type`: não medido (a sonda falhou: sem código)', r.findings)
        self.sem_vazamento(r)

    def test_nomes_de_tipo_hostis_nao_viram_consulta_nem_vao_ao_findings(self):
        hostil = 'X") { __schema { types { name } } } #'
        tipos = tipos_schema(retorno=hostil)
        api = ApiRoteada(introspeccao=erro(1, 'off'))
        api.tipos = {t['name']: t for t in tipos}
        r = rodar(api=api)
        nomes_pedidos = [c['variables']['name'] for c in api.corpos() if c['query'] == R.TIPO_POR_NOME]
        self.assertNotIn(hostil, nomes_pedidos)
        self.assertTrue(all(C.RE_IDENT.fullmatch(n) for n in nomes_pedidos))
        self.assertEqual(r.valor('schema.parcial')['resumo']['productOfferV2']['retorno'], '?!')
        self.assertNotIn('__schema { types', r.findings)
        self.assertEqual(api.desconhecidas, [])


# ---------- a rajada para no primeiro 10030 ----------
class TestRajada(Base):
    def rajada_com_limite(self, k, resposta=None):
        api = ApiRoteada()
        api.limite_na_rajada = k
        if resposta is not None:
            api.resposta_limite = resposta
        return rodar(api=api)

    def test_para_no_primeiro_10030_sem_esperar_nem_repetir(self):
        r = self.rajada_com_limite(57)
        self.assertEqual(r.codigo, 0, r.err)
        v = r.valor('taxa')
        self.assertEqual((v['enviadas'], v['parou_por'], v['primeiro_limite_na']), (57, 'limite', 57))
        self.assertEqual([(d['taxa_alvo'], d['enviadas']) for d in v['degraus']], [(1, 40), (2, 17)])
        self.assertEqual(r.api.rajada, 57)            # nenhuma nova tentativa depois do 10030
        self.assertTrue(all(e < 2 for e in r.esperas), r.esperas)   # nada do backoff de 30 s ou mais
        codigos = r.linhas('SELECT codigo FROM requisicoes WHERE codigo IS NOT NULL')
        self.assertIn((CS.ERRO_LIMITE,), codigos)
        self.assertIn('subid.simples', r.medicoes())  # as sondas seguintes rodaram
        self.assertIn('primeiro 10030/429 na requisição: 57', r.findings)
        self.assertGreater(r.esperas[-1], 0.9)        # a pausa da rodada voltou (1 s + jitter)
        self.sem_vazamento(r)

    def test_http_429_tambem_para(self):
        r = self.rajada_com_limite(3, http_erro(429))
        v = r.valor('taxa')
        self.assertEqual((v['enviadas'], v['parou_por'], v['primeiro_limite_na']), (3, 'limite', 3))
        self.assertEqual(r.api.rajada, 3)

    def test_outro_erro_para_a_rajada_e_fica_so_no_banco(self):
        r = self.rajada_com_limite(5, erro(10020, ECO))
        v = r.valor('taxa')
        self.assertEqual((v['enviadas'], v['parou_por'], v['codigo'], v['mensagem']), (5, 'erro_api', 10020, ECO))
        self.sem_vazamento(r)

    def test_pausas_dos_degraus(self):
        r = self.rajada_com_limite(None)
        pausas = r.esperas
        # 155 pedidos; o 1º não espera. Dentro da rajada, a espera fica entre a pausa do degrau e +0,25 s
        self.assertEqual(len(pausas), REQUISICOES_PADRAO - 1)
        ini = REQUISICOES_PADRAO - 1 - 9 - 120   # esperas antes da rajada (as 9 do fim vêm depois dela)
        for k, (alvo, n) in enumerate(R.DEGRAUS):
            pausa = 1 / alvo - 0.125
            trecho = pausas[ini + 40 * k + 1:ini + 40 * (k + 1)]
            self.assertTrue(all(pausa - 0.05 < e <= pausa + 0.25 for e in trecho), (alvo, trecho))


# ---------- R1: falha de rede ou de credencial não vira medição ----------
def gravar_antigas(pasta, medicoes):
    """Medições como a versão antiga gravava (para provar o que acontece ao carregar). Devolve {nome: id}."""
    con = sqlite3.connect(os.path.join(pasta, 'garimpo.db'))
    try:
        ids = {nome: R.gravar_medicao(con, nome, valor) for nome, valor in medicoes.items()}
        con.commit()
        return ids
    finally:
        con.close()


def falha_antiga(codigo=None, http=None, **extra):
    return {'ok': False, 'falha': 'erro_api', 'codigo': codigo, 'http': http, 'mensagem': None, **extra}


FALHAS_SEM_RESPOSTA = (
    ('rede', lambda: urllib.error.URLError('rede caiu')),
    ('timeout', lambda: TimeoutError('tempo')),
    ('http_500', lambda: http_erro(500)),
    ('http_503', lambda: http_erro(503)),
    ('http_500_com_codigo', lambda: http_erro(500, corpo=erro(10020, ECO))),
    ('http_401', lambda: http_erro(401)),
    ('http_403', lambda: http_erro(403)),
    ('http_401_com_codigo', lambda: http_erro(401, corpo=erro(10020, ECO))),
    ('http_302', lambda: http_erro(302)),
)


class TestPortaoDaSondaBase(Base):
    def test_e_a_primeira_consulta_da_rodada(self):
        r = rodar()
        self.assertEqual(r.api.nomes()[0], 'base')
        self.assertEqual(r.api.corpos()[0]['variables'], {'keyword': R.TERMO, 'sortType': 1, 'page': 1, 'limit': 20})
        self.assertEqual(r.linhas('SELECT nome FROM medicoes ORDER BY id LIMIT 1'), [(R.SONDA_BASE,)])
        self.assertEqual(r.api.nomes().count('base'), 4 + 6 + 5 + len(R.PAGINAS_50) + RAJADA)   # limit.20: uma vez
        self.assertNotIn(f'{R.SONDA_BASE}: já medido', r.out)                # nem aparece como já medido

    def test_a_amostra_da_base_serve_quando_a_consulta_inteira_falha(self):
        r = rodar(api=ApiRoteada(produtos=erro(10010, ECO), categorias=erro(10010, ECO),
                                 base=lambda v: erro(10010, ECO) if v['limit'] != 20 else None))
        self.assertEqual(r.codigo, 0, r.err)
        self.assertEqual(r.valor(R.SONDA_BASE)['amostra']['item_id'], '1')
        self.assertIn('int64.texto', r.medicoes())                           # item e loja vieram da base
        self.assertNotIn('categoria.produto', r.medicoes())                  # categoria, não

    def test_secret_errado_com_codigo_sai_com_1_sem_medir_mais_nada(self):
        """Um Secret errado responde com código (os reais não estão confirmados): tem de parar aqui."""
        for caso, resposta in (('200', erro(10020, ECO)), ('400', http_erro(400, corpo=erro(10020, ECO))),
                               ('10010', erro(10010, ECO))):
            with self.subTest(caso=caso):
                r = rodar(api=ApiRoteada(base=resposta))
                self.assertEqual(r.codigo, 1, r.err)
                self.assertEqual(len(r.api.pedidos), 1)
                self.assertEqual(set(r.medicoes()), {R.SONDA_BASE})
                self.assertEqual(r.valor(R.SONDA_BASE)['mensagem'], ECO)   # a mensagem fica no banco para o diagnóstico
                self.assertIn('sonda-base', r.err)
                self.assertTrue(r.log.rstrip().endswith('SAIDA=1'))
                self.assertIn('Rajada: não medido', r.findings)
                self.findings_honesto(r)
                self.sem_vazamento(r)

    def test_formato_errado_tambem_para(self):
        r = rodar(api=ApiRoteada(base=b'<html>nao e json</html>'))
        self.assertEqual((r.codigo, len(r.api.pedidos)), (1, 1))
        self.assertEqual(set(r.medicoes()), {R.SONDA_BASE})

    def test_sem_resposta_sai_com_1_sem_gravar_nada(self):
        for caso, falha in FALHAS_SEM_RESPOSTA:
            with self.subTest(caso=caso):
                r = rodar(api=ApiRoteada(base=falha()))
                self.assertEqual((r.codigo, len(r.api.pedidos)), (1, 1), r.err)
                self.assertEqual(r.medicoes(), {})
                self.assertEqual(r.linhas('SELECT COUNT(*) FROM requisicoes'), [(1,)])   # o pedido conta
                self.assertTrue(r.log.rstrip().endswith('SAIDA=1'))
                self.sem_vazamento(r)

    def test_a_proxima_rodada_refaz_a_base_que_falhou(self):
        for caso, resposta in (('codigo', erro(10020, ECO)), ('rede', urllib.error.URLError('x'))):
            with self.subTest(caso=caso):
                r1 = rodar(api=ApiRoteada(base=resposta))
                self.assertEqual(r1.codigo, 1)
                r2 = rodar(pasta=r1.pasta)
                self.assertEqual(r2.codigo, 0, r2.err)
                self.assertEqual(len(r2.api.pedidos), REQUISICOES_PADRAO)
                self.assertTrue(r2.valor(R.SONDA_BASE)['ok'])
                self.assertEqual(set(r2.medicoes()), MEDICOES_PADRAO)

    def test_base_antiga_que_falhou_nao_deixa_sair_com_0(self):
        r1 = rodar()
        gravar_antigas(r1.pasta, {R.SONDA_BASE: falha_antiga(10020)})
        r2 = rodar(api=ApiRoteada(base=erro(10020, ECO)), pasta=r1.pasta)
        self.assertEqual((r2.codigo, len(r2.api.pedidos)), (1, 1), r2.err)   # refaz a base e para nela

    def test_fim_do_rodar_sai_com_1_sem_base_ok(self):
        ctx = mock.Mock(con=sqlite3.connect(':memory:'), achados={'int64': 'texto'})
        ctx.con.execute('CREATE TABLE medicoes (id INTEGER, nome TEXT, valor_json TEXT, em TEXT)')
        self.addCleanup(ctx.con.close)
        r = R.Reconhecer(ctx)
        self.assertIn('sonda-base', ' '.join(r.problemas()))   # nem medida
        r.medidas[R.SONDA_BASE] = (1, {'ok': False})
        self.assertIn('sonda-base', ' '.join(r.problemas()))
        r.medidas[R.SONDA_BASE] = (1, {'ok': True})
        self.assertEqual(r.problemas(), [])


class SecretErrado(ApiRoteada):
    """Toda consulta responde com o código de um Secret errado (a prova da retomada)."""

    def responder(self, query, v):
        return self.falha() if callable(self.falha) else self.falha

    falha = staticmethod(lambda: erro(10020, ECO))


class TestReconfirmacaoDaBase(Base):
    """Toda rodada que vai mandar pedido reconfere a sonda-base primeiro, mesmo com a medição dela já gravada."""

    def retomada(self, falha=None, argv=(), primeira=('--max-req', '1')):
        """1ª rodada boa e parada pelo teto; 2ª com a API toda falhando."""
        r1 = rodar(list(primeira))
        api = SecretErrado()
        if falha is not None:
            api.falha = falha
        return r1, rodar(list(argv), pasta=r1.pasta, api=api)

    def test_secret_errado_na_retomada_sai_com_1_sem_medicao_nova(self):
        r1, r2 = self.retomada()
        antes = r1.medicoes().keys()
        self.assertEqual(r2.codigo, 1, r2.err)
        self.assertEqual(len(r2.api.pedidos), 1)
        self.assertEqual(r2.medicoes().keys(), antes)
        self.assertEqual(r2.linhas('SELECT COUNT(*) FROM medicoes'), [(1,)])     # nenhuma nova
        self.assertTrue(r2.valor(R.SONDA_BASE)['ok'])                            # a boa continua a boa
        self.assertEqual(r2.linhas('SELECT COUNT(*) FROM requisicoes'), [(2,)])  # o pedido fica registrado
        self.assertEqual(r2.linhas('SELECT codigo FROM requisicoes ORDER BY id DESC LIMIT 1'), [(10020,)])
        self.assertIn('reconfirmação', r2.err)
        self.assertNotIn('não foi gravada', r2.err)
        self.assertIn('SAIDA=1', r2.log)                                         # r2.log junta os logs da pasta
        self.sem_vazamento(r2)

    def test_qualquer_falha_sai_com_1_sem_medicao_nova(self):
        casos = [(n, f) for n, f in FALHAS_SEM_RESPOSTA] + [
            ('codigo', lambda: erro(10010, ECO)), ('sem_codigo', lambda: erro('x', ECO)),
            ('http_400', lambda: http_erro(400, corpo=erro(10020, ECO))), ('http_404', lambda: http_erro(404)),
            ('nao_json', lambda: b'<html>'), ('sem_data', lambda: {'x': 1}), ('sem_operacao', lambda: {'data': {}}),
            ('nos_ruins', lambda: {'data': {'productOfferV2': {'nodes': 'x'}}})]
        for caso, falha in casos:
            with self.subTest(caso=caso):
                _, r2 = self.retomada(falha)
                self.assertEqual((r2.codigo, len(r2.api.pedidos)), (1, 1), r2.err)
                self.assertIn('reconfirmação', r2.err)
                self.assertEqual(r2.linhas('SELECT COUNT(*) FROM medicoes'), [(1,)])
                self.assertTrue(r2.valor(R.SONDA_BASE)['ok'])
                self.sem_vazamento(r2)

    def test_a_retomada_seguinte_com_o_secret_certo_continua_de_onde_parou(self):
        r1, r2 = self.retomada()
        r3 = rodar(pasta=r1.pasta)
        self.assertEqual(r3.codigo, 0, r3.err)
        self.assertEqual(r3.api.nomes()[:2], ['base', 'introspeccao'])
        self.assertEqual(len(r3.api.pedidos), REQUISICOES_PADRAO)     # a base de novo e todas as que faltavam
        self.assertEqual(set(r3.medicoes()), MEDICOES_PADRAO)
        self.assertEqual(r3.linhas("SELECT COUNT(*) FROM medicoes WHERE nome = ?", R.SONDA_BASE), [(1,)])

    def test_retomada_normal_repete_so_a_base(self):
        r1 = rodar(['--max-req', '10'])
        nomes1 = r1.api.nomes()
        r2 = rodar(pasta=r1.pasta)
        self.assertEqual(r2.codigo, 0, r2.err)
        self.assertEqual(len(nomes1) + len(r2.api.nomes()), REQUISICOES_PADRAO + 1)
        self.assertEqual(r2.api.corpos()[0]['variables'], {'keyword': R.TERMO, 'sortType': 1, 'page': 1, 'limit': 20})
        self.assertEqual(r2.api.nomes()[0], 'base')
        self.assertEqual(r2.api.corpos()[0]['query'], R.P_BASE)
        self.assertNotIn('introspeccao', r2.api.nomes())
        self.assertEqual(r2.linhas('SELECT COUNT(*) FROM medicoes'), [(len(MEDICOES_PADRAO),)])
        self.assertEqual(r2.linhas("SELECT COUNT(*) FROM medicoes WHERE nome = ?", R.SONDA_BASE), [(1,)])

    def test_a_reconfirmacao_vem_uma_vez_so(self):
        r1 = rodar()
        gravar_antigas(r1.pasta, {'lojas': falha_antiga(), 'conversoes': falha_antiga()})
        r2 = rodar(pasta=r1.pasta)
        self.assertEqual(r2.api.nomes(), ['base', 'lojas', 'conversoes'])

    def test_tudo_medido_nao_faz_pedido_e_a_saida_segue_os_problemas(self):
        r1 = rodar()
        r2 = rodar(pasta=r1.pasta, api=SecretErrado())
        self.assertEqual((r2.codigo, r2.api.pedidos), (0, []), r2.err)
        r1 = rodar(conferencia=ConferenciaFalsa(id_afiliado='999'))
        rodar(pasta=r1.pasta)                                         # mede o resto
        r3 = rodar(pasta=r1.pasta, api=SecretErrado())
        self.assertEqual((r3.codigo, r3.api.pedidos), (1, []), r3.err)
        self.assertIn('outro afiliado', r3.err)

    def test_so_a_rajada_pendente_tambem_reconfirma(self):
        r1 = rodar()
        taxa = r1.medicoes()['taxa'][0]
        r2 = rodar(['--refazer-taxa'], pasta=r1.pasta, api=SecretErrado())
        self.assertEqual((r2.codigo, len(r2.api.pedidos)), (1, 1), r2.err)
        self.assertEqual(r2.medicoes()['taxa'][0], taxa)              # a boa não foi trocada por uma rajada de erro
        self.assertEqual(r2.linhas('SELECT COUNT(*) FROM medicoes'), [(len(MEDICOES_PADRAO),)])

    def test_so_uma_sonda_de_subid_pendente_tambem_reconfirma(self):
        r1 = rodar()
        gravar_antigas(r1.pasta, {'subid.hifen': falha_antiga()})
        r2 = rodar(pasta=r1.pasta, api=SecretErrado())
        self.assertEqual((r2.codigo, len(r2.api.pedidos)), (1, 1), r2.err)
        self.assertEqual(r2.conferencia.links, [])
        self.assertEqual(r2.linhas('SELECT COUNT(*) FROM medicoes'), [(len(MEDICOES_PADRAO) + 1,)])   # só a injetada

    def test_conta_no_max_req(self):
        r1 = rodar(['--max-req', '1'])
        r2 = rodar(['--max-req', '1'], pasta=r1.pasta)
        self.assertEqual((r2.codigo, r2.api.nomes()), (3, ['base']))
        self.assertEqual(r2.linhas('SELECT COUNT(*) FROM medicoes'), [(1,)])
        self.assertEqual(r2.linhas('SELECT COUNT(*) FROM requisicoes'), [(2,)])
        self.assertIn('--max-req', r2.err)

    def test_conta_no_teto_total(self):
        r1 = rodar(['--max-req', '1'])
        r2 = rodar(pasta=r1.pasta, achados={'max_total_requests': 1}, api=SecretErrado())
        self.assertEqual((r2.codigo, r2.api.pedidos), (3, []))        # o teto vem antes de mandar

    def test_limite_da_api_na_reconfirmacao_sai_com_3(self):
        _, r2 = self.retomada(lambda: erro(CS.ERRO_LIMITE, ECO))
        self.assertEqual((r2.codigo, len(r2.api.pedidos)), (3, 6))    # as 5 esperas do cliente
        self.assertEqual(r2.linhas('SELECT COUNT(*) FROM medicoes'), [(1,)])

    def test_refazer_e_refazer_taxa_cabem_no_teto_padrao(self):
        r1 = rodar()
        for argv, esperado in ((['--refazer'], REQUISICOES_PADRAO - RAJADA),   # a base é medida: sem reconfirmação
                               (['--refazer-taxa'], RAJADA + 1),               # a base reconfirmada + a rajada
                               (['--refazer', '--refazer-taxa'], REQUISICOES_PADRAO)):
            with self.subTest(argv=argv):
                r = rodar(argv, pasta=r1.pasta)
                self.assertEqual((r.codigo, len(r.api.pedidos)), (0, esperado), r.err)
                self.assertLessEqual(esperado, 250)
                self.assertIn('teto desta rodada: 250', r.out)


class TestSemRespostaNoMeio(Base):
    def test_sobe_sem_gravar_e_a_retomada_mede_so_o_que_falta(self):
        for caso, falha in FALHAS_SEM_RESPOSTA:
            with self.subTest(caso=caso):
                r = rodar(api=ApiRoteada(lojas=falha()))
                self.assertEqual(r.codigo, 1, r.err)
                self.assertNotIn('lojas', r.medicoes())
                self.assertIn('feeds.dados', r.medicoes())           # o que veio antes ficou
                self.assertNotIn('campanhas', r.api.nomes())         # e a rodada parou ali
                self.assertIn('não foi gravada', r.err)
                self.assertTrue(r.log.rstrip().endswith('SAIDA=1'))
                self.assertIn('`shopOfferV2`: não medido\n', r.findings)
                self.findings_honesto(r)
                self.sem_vazamento(r)
                r2 = rodar(pasta=r.pasta)
                self.assertEqual(r2.codigo, 0, r2.err)
                self.assertEqual(r2.api.nomes(), ['base', 'lojas', 'campanhas', 'conversoes'])
                self.assertEqual(set(r2.medicoes()), MEDICOES_PADRAO)

    def test_na_introspeccao_e_nos_resumos_tambem(self):
        r = rodar(api=ApiRoteada(introspeccao=urllib.error.URLError('x')))
        self.assertEqual((r.codigo, r.api.nomes()), (1, ['base', 'introspeccao']))   # não cai nas consultas __type
        self.assertEqual(set(r.medicoes()), {R.SONDA_BASE})
        r = rodar(api=ApiRoteada(base=lambda v: http_erro(503) if v['page'] == 5 else None))
        self.assertEqual(r.codigo, 1)
        self.assertNotIn('pagina.5', r.medicoes())
        self.assertNotIn('pagina.teto', r.medicoes())                # resumo sobre sonda que não veio
        r2 = rodar(pasta=r.pasta)
        self.assertEqual(r2.codigo, 0, r2.err)
        self.assertEqual(r2.valor('pagina.teto')['ultima_util'], TETO)

    def test_mesmo_codigo_em_varias_sondas_continua_sendo_medicao(self):
        """Não há regra de "3 sondas seguidas": 10010 em cada listType é o que a sonda quer descobrir."""
        r = rodar(api=ApiRoteada(listtype=erro(10010, ECO), ams=erro(10010, ECO), keyseller=erro(10010, ECO)))
        self.assertEqual(r.codigo, 0, r.err)
        for lt in R.LIST_TYPES:
            v = r.valor(f'listtype.{lt}')
            self.assertEqual((v['ok'], v['codigo']), (False, 10010))
        self.assertIn('lojas', r.medicoes())

    def test_codigo_e_http_4xx_sem_codigo_continuam_sendo_medicao(self):
        for caso, resposta, codigo, http in (('200', erro(11001, ECO), 11001, None),
                                             ('400', http_erro(400, corpo=erro(10010, ECO)), 10010, 400),
                                             ('404', http_erro(404), None, 404), ('sem_codigo', erro('x', ECO), 0, None)):
            with self.subTest(caso=caso):
                r = rodar(api=ApiRoteada(lojas=resposta))
                self.assertEqual(r.codigo, 0, r.err)
                v = r.valor('lojas')
                self.assertEqual((v['ok'], v['codigo'], v['http']), (False, codigo, http))

    def test_resposta_fora_do_formato_nas_demais_continua_sendo_medicao(self):
        r = rodar(api=ApiRoteada(lojas=b'nao e json'))
        self.assertEqual(r.codigo, 0, r.err)
        self.assertEqual(r.valor('lojas')['falha'], 'resposta_invalida')


class TestSemRespostaNaRajada(Base):
    def rajada(self, k, falha):
        api = ApiRoteada()
        api.limite_na_rajada, api.resposta_limite = k, falha
        return rodar(api=api)

    def test_sobe_sem_gravar_a_taxa_e_a_retomada_refaz(self):
        for caso, falha in FALHAS_SEM_RESPOSTA:
            with self.subTest(caso=caso):
                r = self.rajada(5, falha())
                self.assertEqual(r.codigo, 1, r.err)
                self.assertNotIn('taxa', r.medicoes())
                self.assertEqual(r.api.rajada, 5)
                self.assertNotIn('link', r.api.nomes())
                self.assertIn('Rajada: não medido', r.findings)
                self.assertTrue(r.log.rstrip().endswith('SAIDA=1'))
                r2 = rodar(pasta=r.pasta)
                self.assertEqual(r2.codigo, 0, r2.err)
                self.assertEqual(r2.valor('taxa')['enviadas'], RAJADA)

    def test_codigo_dentro_da_rajada_continua_sendo_medicao(self):
        r = self.rajada(5, erro(10020, ECO))
        v = r.valor('taxa')
        self.assertEqual((r.codigo, v['parou_por'], v['codigo']), (0, 'erro_api', 10020))


class TestMedicaoAntigaAoCarregar(Base):
    """Banco gravado antes da correção: falha de transporte ou de autenticação conta como não medida."""

    def test_e_refeita_e_o_findings_nao_a_cita(self):
        r1 = rodar()
        ids = gravar_antigas(r1.pasta, {
            'lojas': falha_antiga(), 'campanhas': falha_antiga(http=503), 'conversoes': falha_antiga(10020, 401),
            'feeds.full': falha_antiga(http=403)})
        r2 = rodar(['--max-req', '1'], pasta=r1.pasta)
        self.assertEqual(r2.codigo, 3)
        for mid in ids.values():
            self.assertNotIn(f'medicoes #{mid})', r2.findings)
        self.assertIn('`shopOfferV2`: não medido\n', r2.findings)
        r3 = rodar(pasta=r1.pasta)
        self.assertEqual(r3.codigo, 0, r3.err)
        self.assertEqual(r2.api.nomes(), ['base'])                    # a reconfirmação gastou o --max-req 1
        self.assertEqual(r3.api.nomes(), ['base', 'feeds', 'lojas', 'campanhas', 'conversoes'])
        self.findings_honesto(r3)
        self.assertNotIn('a sonda falhou', r3.findings.split('## Outras consultas')[1])

    def test_falha_com_codigo_continua_medida(self):
        r1 = rodar()
        v = R.VERSOES
        ids = gravar_antigas(r1.pasta, {'lojas': falha_antiga(10010, versao=v['lojas']),
                                        'campanhas': falha_antiga(http=400, versao=v['campanhas'])})
        r2 = rodar(pasta=r1.pasta)
        # a falha com código continua medida; a queda sem pageInfo, que ainda não existia, é o único pedido novo
        self.assertEqual((r2.codigo, r2.api.nomes()), (0, ['base', 'lojas_sem_pagina']))
        self.assertIn(f'(medicoes #{ids["lojas"]})', r2.findings)
        self.assertIn('código 10010', r2.findings)

    def test_consulta_de_produtos_do_garimpo_sem_pageinfo_nao_refaz_a_sonda_com_pageinfo(self):
        """Etapa 8: a `CONSULTA_PRODUTOS` do garimpo deixou de pedir o pageInfo, mas a sonda `produtos.consulta` segue
        medindo o texto antigo (o recusado no R1, #47). A medição de hoje (versão 2, recusada com código) continua
        valendo: a próxima rodada não a repete e, com tudo medido, não gasta nenhum pedido."""
        self.assertEqual(R.VERSOES['produtos.consulta'], 2)   # a #47 do R1 é da versão 2: subir a versão a refaria
        r1 = rodar()
        pedida = [json.loads(p.data)['query'] for p in r1.api.pedidos
                  if CONSTANTES.get(json.loads(p.data)['query']) == 'produtos']
        self.assertEqual(pedida, [R.P_PRODUTOS_COM_PAGINA])
        self.assertIn('pageInfo', R.P_PRODUTOS_COM_PAGINA)
        self.assertNotIn('pageInfo', C.CONSULTA_PRODUTOS)
        self.assertNotIn(C.CONSULTA_PRODUTOS, {json.loads(p.data)['query'] for p in r1.api.pedidos})
        # o estado real do R1: a sonda recusada com código 10010 na versão atual
        categorias = {'ok': True, 'n_nos': 20, 'n_unicos': 20, 'ids': ['1'],
                      'amostra': {'item_id': '1', 'shop_id': '777', 'cat_ids': [CAT]}}   # a #4 do R1
        ids = gravar_antigas(r1.pasta, {'produtos.consulta': falha_antiga(10010, versao=R.VERSOES['produtos.consulta']),
                                        'produtos.categorias': categorias})
        r2 = rodar(pasta=r1.pasta)
        self.assertEqual((r2.codigo, r2.api.nomes()), (0, []))   # nada falta medir: nenhum pedido, nem a reconfirmação
        self.assertIn(f'(medicoes #{ids["produtos.consulta"]})', r2.findings)

    def test_ultima_medicao_e_a_que_vale(self):
        r1 = rodar()
        antiga = r1.medicoes()['lojas'][0]
        gravar_antigas(r1.pasta, {'lojas': falha_antiga()})      # a boa ficou para trás
        r2 = rodar(['--max-req', '2'], pasta=r1.pasta)
        self.assertNotIn(f'medicoes #{antiga})', r2.findings.split('## Outras consultas')[1])
        self.assertEqual(r2.api.nomes(), ['base', 'lojas'])
        # depois da falha, uma boa: vale a boa
        valor = {'ok': True, 'n_nos': 1, 'versao': R.VERSOES['lojas']}
        boa = gravar_antigas(r1.pasta, {'lojas': valor})['lojas']
        con = sqlite3.connect(r1.banco)
        self.addCleanup(con.close)
        self.assertEqual(R.ler_medicoes(con)['lojas'], (boa, valor))

    def test_rajada_antiga_interrompida_por_rede_e_refeita(self):
        r1 = rodar()
        gravar_antigas(r1.pasta, {'taxa': {'ok': True, 'enviadas': 5, 'maximo': RAJADA, 'parou_por': 'erro_api',
                                           'primeiro_limite_na': None, 'degraus': [], 'codigo': None, 'http': None,
                                           'mensagem': None}})
        r2 = rodar(pasta=r1.pasta)
        self.assertEqual(r2.codigo, 0, r2.err)
        self.assertEqual((len(r2.api.pedidos), r2.valor('taxa')['enviadas']), (RAJADA + 1, RAJADA))

    def test_rajada_antiga_parada_por_codigo_continua_medida(self):
        r1 = rodar()
        gravar_antigas(r1.pasta, {'taxa': {'ok': True, 'enviadas': 5, 'maximo': RAJADA, 'parou_por': 'erro_api',
                                           'degraus': [], 'codigo': 10020, 'http': None, 'mensagem': None}})
        self.assertEqual(rodar(pasta=r1.pasta).api.nomes(), [])

    def test_resumo_montado_sobre_falha_antiga_e_refeito(self):
        casos = (('pagina.5', 'pagina.teto', ['base']), ('sort.2', 'sort.sobreposicao', ['base']),
                 ('listtype.3', 'listtype.comparacao', ['listtype']), ('categoria.produto', 'listtype.comparacao',
                                                                       ['categoria']),
                 ('filtro.ams', 'filtro.comparacao', ['ams']), ('sort.1', 'filtro.comparacao', ['base']))
        for sonda, resumo, nomes in casos:
            with self.subTest(sonda=sonda):
                r1 = rodar()
                antes = r1.medicoes()[resumo][0]
                gravar_antigas(r1.pasta, {sonda: falha_antiga()})
                r2 = rodar(pasta=r1.pasta)
                self.assertEqual((r2.codigo, r2.api.nomes()), (0, ['base'] + nomes), r2.err)
                self.assertGreater(r2.medicoes()[resumo][0], antes)   # o resumo foi refeito
                self.assertTrue(r2.valor(sonda)['ok'])
                # refeita a sonda, a falha antiga não derruba mais o resumo
                n = r2.linhas('SELECT COUNT(*) FROM medicoes')
                r3 = rodar(pasta=r1.pasta)
                self.assertEqual((r3.api.nomes(), r3.linhas('SELECT COUNT(*) FROM medicoes')), ([], n))

    def test_o_schema_parcial_tambem(self):
        r1 = rodar(api=ApiRoteada(introspeccao=erro(10010, ECO)))
        self.assertEqual(r1.codigo, 0)
        gravar_antigas(r1.pasta, {'schema.tipo.Query': falha_antiga()})
        r2 = rodar(pasta=r1.pasta, api=ApiRoteada(introspeccao=erro(10010, ECO)))
        self.assertEqual((r2.codigo, r2.api.nomes()), (0, ['base', 'tipo']), r2.err)


class TestRefazerETeto(Base):
    def test_refazer_nao_repete_a_rajada(self):
        r1 = rodar()
        taxa = r1.medicoes()['taxa'][0]
        r2 = rodar(['--refazer'], pasta=r1.pasta)
        self.assertEqual(r2.codigo, 0, r2.err)
        self.assertEqual(r2.api.rajada, 0)
        self.assertEqual(r2.medicoes()['taxa'][0], taxa)
        self.assertEqual(len(r2.api.pedidos), REQUISICOES_PADRAO - RAJADA)
        self.assertIn('--refazer-taxa', r2.out)

    def test_refazer_mede_a_taxa_se_ela_ainda_nao_existe(self):
        r1 = rodar(['--max-req', '5'])
        r2 = rodar(['--refazer'], pasta=r1.pasta)
        self.assertEqual(r2.codigo, 0, r2.err)
        self.assertEqual(r2.api.rajada, RAJADA)

    def test_refazer_taxa_repete_so_a_rajada_e_cabe_no_padrao(self):
        r1 = rodar()
        taxa = r1.medicoes()['taxa'][0]
        r2 = rodar(['--refazer-taxa'], pasta=r1.pasta)
        self.assertEqual(r2.codigo, 0, r2.err)
        self.assertEqual(r2.api.nomes(), ['base'] * (RAJADA + 1))     # a reconfirmação e a rajada
        self.assertGreater(r2.medicoes()['taxa'][0], taxa)
        self.assertLess(RAJADA, 250)
        self.assertIn('teto desta rodada: 250', r2.out)

    def test_os_dois_juntos_medem_tudo(self):
        r1 = rodar()
        r2 = rodar(['--refazer', '--refazer-taxa'], pasta=r1.pasta)
        self.assertEqual((r2.codigo, len(r2.api.pedidos)), (0, REQUISICOES_PADRAO))

    def test_rodada_completa_cabe_no_teto_padrao(self):
        r = rodar()
        self.assertEqual(r.codigo, 0, r.err)
        self.assertIn('teto desta rodada: 250', r.log)
        self.assertLessEqual(len(r.api.pedidos), 250)

    def test_pior_caso_da_rodada_cabe_no_teto_padrao(self):
        """Introspecção recusada (12 consultas __type), bissecção inteira da profundidade, feed menor."""
        def pagina_longa(v):
            if v['page'] <= 700:
                inicio = (v['page'] - 1) * 20 + 1 + (v['sortType'] - 1) * 5
                return base(nos(range(inicio, inicio + 20)))
            return base([])

        def tipo_inesgotavel(v):
            return {'data': {'__type': {'kind': 'OBJECT', 'name': v['name'], 'fields': [
                campo('productOfferV2', ref('R' + v['name'], 'OBJECT'),
                      [(f'a{i}', ref(f'T{v["name"]}{i}', 'OBJECT')) for i in range(30)])]}}}

        grande = b'{"data": {"getItemFeedData": "' + b'x' * (2 * 1024 * 1024) + b'"}}'
        api = ApiRoteada(introspeccao=erro(10010, ECO), base=pagina_longa, tipo=tipo_inesgotavel,
                         dados_feed=lambda v: grande if v['limit'] == R.LIMITE_FEED else None,
                         lojas=erro(10010, ECO))
        api.pagina_quebra = {'hasNextPage'}
        r = rodar(api=api)
        self.assertEqual(r.codigo, 0, r.err)
        self.assertEqual(r.api.nomes().count('tipo'), R.MAX_TIPOS)
        self.assertIn('feeds.dados_menor', r.medicoes())
        self.assertGreater(len(r.api.pedidos), REQUISICOES_PADRAO)
        self.assertLessEqual(len(r.api.pedidos), 250)


# ---------- R3: surrogate solto da API ----------
SOLTO = chr(0xDC00)


class TestSurrogates(Base):
    def test_mensagem_de_erro_com_surrogate(self):
        self.assertEqual(R.mensagem_de_erro({'errors': [{'message': 'a' + SOLTO + 'b'}]}), 'a?b')
        r = rodar(api=ApiRoteada(lojas=erro(10010, 'recusado ' + SOLTO)))
        self.assertEqual(r.codigo, 0, r.err)
        self.assertEqual(r.valor('lojas')['mensagem'], 'recusado ?')

    def test_medicao_com_surrogate_em_outro_campo_e_gravada_em_ascii(self):
        r = rodar(api=ApiRoteada(feeds={'data': {'listItemFeeds': {'feeds': [{'datafeedId': 'F' + SOLTO,
                                                                              'feedMode': 'FULL'}]}}}))
        self.assertEqual(r.codigo, 0, r.err)
        self.assertEqual(r.valor('feeds.full')['escolhido']['datafeed_id'], 'F' + SOLTO)
        (texto,) = r.linhas("SELECT valor_json FROM medicoes WHERE nome = 'feeds.full'")[0]
        self.assertTrue(texto.isascii())

    def test_gravar_medicao_em_ascii_guarda_acento_e_emoji(self):
        con = sqlite3.connect(':memory:')
        self.addCleanup(con.close)
        con.execute('CREATE TABLE medicoes (id INTEGER PRIMARY KEY, nome TEXT, valor_json TEXT, em TEXT)')
        valor = {'mensagem': 'ação ' + chr(0x1F600)}
        R.gravar_medicao(con, 'x', valor)
        self.assertEqual(R.ler_medicoes(con)['x'][1], valor)

    def test_schema_com_surrogate_e_salvo(self):
        esquema = schema()
        esquema['description'] = 'descricao ' + SOLTO
        r = rodar(api=ApiRoteada(introspeccao={'data': {'__schema': esquema}}))
        self.assertEqual(r.codigo, 0, r.err)
        self.assertTrue(r.valor('schema.introspeccao')['ok'])
        self.assertEqual(json.loads(r.ler(R.ARQ_SCHEMA))['__schema']['description'], esquema['description'])

    def test_codigo_fora_do_int64_fica_em_requisicoes(self):
        r = rodar(api=ApiRoteada(lojas=erro(2 ** 70, ECO)))
        self.assertEqual(r.codigo, 0, r.err)
        self.assertEqual(r.valor('lojas')['codigo'], 2 ** 70)
        self.assertEqual(r.linhas('SELECT COUNT(*) FROM requisicoes'), [(len(r.api.pedidos),)])
        self.assertIn((None,), r.linhas("SELECT codigo FROM requisicoes WHERE operacao = 'shopOfferV2'"))


# ---------- etapa 8 A: o que o R1 real mediu ----------
SISTEMA = erro(K.ERRO_SISTEMA, 'error [10000]: System Error')


def r1_real():
    """As medições que o R1 do dono deixou no banco, resumidas (nomes e falhas iguais; valores só os necessários)."""
    bom = {'ok': True, 'n_nos': 20, 'n_unicos': 20, 'ids': ['1'], 'amostra': {'item_id': '1', 'shop_id': '777',
                                                                               'cat_ids': []}}
    def outros(n):
        return {**bom, 'ids': [str(n)]}
    m = {'limit.20': bom, 'schema.introspeccao': {'ok': True, 'n_tipos': 78, 'bytes': 59783, 'arquivo': R.ARQ_SCHEMA},
         'produtos.consulta': falha_antiga(10010, mensagem='graphql: got null for non-null'),
         'produtos.categorias': {**bom, 'amostra': {'item_id': '1', 'shop_id': '777', 'cat_ids': ['100017', '100104']}},
         'limit.50': bom, 'limit.100': falha_antiga(11001), 'limit.500': falha_antiga(11001)}
    for p in (1, 2, 5, 10, 20, 50):
        m[f'pagina.{p}'] = outros(p)
    m['pagina.100'] = falha_antiga(K.ERRO_SISTEMA)
    for p in (75, 87, 93, 96, 98):
        m[f'pagina.{p}'] = outros(p)
    m['pagina.teto'] = {'ok': True, 'limit': 20, 'ultima_util': 98, 'primeira_inutil': 100, 'exata': False,
                        'paginas_medidas': [1, 2, 5, 10, 20, 50, 75, 87, 93, 96, 98, 100], 'repetidas': []}
    m['sort.1'] = falha_antiga(K.ERRO_SISTEMA)
    for s in (2, 3, 4, 5):
        m[f'sort.{s}'] = outros(1000 + s)
    m['sort.sobreposicao'] = {'ok': True, 'limit': 20, 'tamanhos': {}, 'comuns': {}}
    m['categoria.produto'] = {**bom, 'cat_id': '100104', 'nivel': 2}
    for lt in R.LIST_TYPES:
        m[f'listtype.{lt}'] = {**bom, 'cat_id': '100104', 'match_id_como': 'texto'}
    m['listtype.comparacao'] = {'ok': True, 'cat_id': '100104', 'categoria_n_nos': 20, 'list_types': {}}
    m['filtro.ams'] = bom
    m['filtro.keyseller'] = bom
    m['filtro.comparacao'] = {'ok': True, 'sort1_n_nos': None, 'ams': None, 'keyseller': None}
    m['int64.numero'] = falha_antiga(10010, item_id='1')
    m['int64.texto'] = {**bom, 'item_id': '1'}
    m['taxa'] = {'ok': True, 'enviadas': 96, 'maximo': 120, 'parou_por': 'erro_api', 'primeiro_limite_na': None,
                 'degraus': [], 'codigo': K.ERRO_SISTEMA, 'http': None, 'mensagem': 'System Error'}
    m['subid.simples'] = {'ok': True, 'link_valido': True, 'dono_ok': True, 'link': LINK, 'sub_ids': ['fem', 'sonda']}
    m['subid.hifen'] = falha_antiga(11001, sub_ids=['fem', 'sonda-hifen'])
    m['subid.sublinhado'] = falha_antiga(11001, sub_ids=['fem', 'sonda_sub'])
    m['feeds.lista'] = falha_antiga(10010)
    m['lojas'] = falha_antiga(10010)
    m['campanhas'] = falha_antiga(10010)
    m['conversoes'] = falha_antiga(10010, janela_dias=30)
    return m


def ate_a_pagina_99(v):
    if v['page'] >= 100:
        return base([])
    inicio = (v['page'] - 1) * v['limit'] + 1 + (v['sortType'] - 1) * 5
    return base(nos(range(inicio, inicio + v['limit'])))


def banco_do_r1():
    pasta = comum.nova_pasta()
    banco.abrir(os.path.join(pasta, 'garimpo.db')).close()
    gravar_antigas(pasta, r1_real())
    return pasta


class TestRodadaDaEtapa8(Base):
    """A rodada normal do dono, sobre o banco que o R1 real deixou: só o que falta, sem rajada."""

    def test_mede_so_o_que_falta_ate_60_pedidos_sem_rajada(self):
        pasta = banco_do_r1()
        api = ApiRoteada(base=ate_a_pagina_99)
        r = rodar(pasta=pasta, api=api)
        self.assertEqual(r.codigo, 0, r.err)
        n = len(r.api.pedidos)
        self.assertLessEqual(n, 60)
        nomes = r.api.nomes()
        # reconfirmação, produtos, 11+1+2 de campos, pagina.100, pagina.99, 6 de limit 50, sort.1, feeds 2+1,
        # lojas, campanhas e conversões
        self.assertEqual(n, 1 + 1 + 14 + 2 + 6 + 1 + 3 + 3)
        self.assertEqual(nomes[0], 'base')
        for ja in ('introspeccao', 'tipo', 'raizes', 'categoria', 'listtype', 'ams', 'keyseller', 'item', 'link'):
            self.assertNotIn(ja, nomes, ja)
        self.assertEqual(r.valor('taxa')['enviadas'], 96)                      # a rajada não foi refeita
        self.assertEqual(r.linhas("SELECT COUNT(*) FROM medicoes WHERE nome = 'taxa'"), [(1,)])
        self.assertEqual(len(r.linhas("SELECT id FROM medicoes WHERE nome = 'limit.100'")), 1)
        self.assertEqual(r.valor('pagina.99')['ok'], True)
        self.findings_honesto(r)
        self.sem_vazamento(r)

    def test_system_error_persistente_conta_e_cabe_em_60(self):
        pasta = banco_do_r1()
        api = ApiRoteada(base=lambda v: SISTEMA if v['page'] in (99, 100) or v['limit'] == 50 and v['page'] > 40
                         or v['sortType'] == 1 and v['page'] == 1 and v['limit'] == 20 and len(api.pedidos) > 2
                         else None, lojas=erro(10010, ECO))
        api.pagina_quebra = {'hasNextPage'}
        r = rodar(pasta=pasta, api=api)
        self.assertEqual(r.codigo, 1, r.err)
        # sort.1, pagina.99, pagina.100 e 3 páginas do limit 50 terminam em System Error, com as tentativas
        self.assertLessEqual(len(r.api.pedidos), 60)
        for nome in ('pagina.100', 'pagina.99', 'sort.1', 'pagina50.41', 'pagina50.60', 'pagina50.99'):
            self.assertIn(nome, r.err)
        self.assertIn('10000', r.err)
        self.assertRegex(r.findings, r'\| 100 \| não medido \(System Error')
        self.assertRegex(r.findings, r'\| 41 \| não medido \(System Error')
        self.findings_honesto(r)

    def test_a_retomada_seguinte_mede_nada_se_tudo_deu_certo(self):
        pasta = banco_do_r1()
        api = ApiRoteada(base=ate_a_pagina_99)
        r = rodar(pasta=pasta, api=api)
        self.assertEqual(r.codigo, 0, r.err)
        r2 = rodar(pasta=pasta, api=api.__class__(base=ate_a_pagina_99))
        self.assertEqual((r2.codigo, r2.api.pedidos), (0, []), r2.err)        # a versão nova não é invalidada de novo

    def test_o_resumo_antigo_com_system_error_e_refeito(self):
        pasta = banco_do_r1()
        antes_teto = rodar(['--max-req', '1'], pasta=pasta)
        self.assertEqual(antes_teto.codigo, 3)
        self.assertNotIn('primeira sem itens ou repetida: 100', antes_teto.findings)
        r = rodar(pasta=pasta, api=ApiRoteada(base=ate_a_pagina_99))
        self.assertEqual(r.codigo, 0, r.err)
        teto = r.valor('pagina.teto')
        self.assertEqual((teto['ultima_util'], teto['exata']), (99, True))
        self.assertEqual(r.valor('sort.sobreposicao')['tamanhos']['1'], 20)

    def test_medicao_de_versao_antiga_nao_aparece_no_findings(self):
        pasta = banco_do_r1()
        r = rodar(['--max-req', '1'], pasta=pasta)
        self.assertNotIn('a sonda falhou: código 10010) (medicoes #', r.findings.split('## Outras consultas')[1])
        self.assertIn('`shopOfferV2`: não medido\n', r.findings)


class TestSystemErrorNoReconhecer(Base):
    def uma_vez(self, n, resposta=SISTEMA):
        vezes = []

        def f(v):
            vezes.append(1)
            return resposta if len(vezes) <= n else None
        return f

    def test_tentativa_que_passa_vira_medicao_boa(self):
        r = rodar(api=ApiRoteada(lojas=self.uma_vez(K.TENTATIVAS_SISTEMA)))
        self.assertEqual(r.codigo, 0, r.err)
        self.assertTrue(r.valor('lojas')['ok'])
        self.assertEqual(r.api.nomes().count('lojas'), K.TENTATIVAS_SISTEMA + 1)
        self.assertEqual(r.linhas("SELECT COUNT(*) FROM requisicoes WHERE codigo = ?", K.ERRO_SISTEMA),
                         [(K.TENTATIVAS_SISTEMA,)])

    def test_ler_system_errors_so_traz_a_ultima_de_cada_nome(self):
        con = sqlite3.connect(':memory:')
        self.addCleanup(con.close)
        con.execute('CREATE TABLE medicoes (id INTEGER PRIMARY KEY, nome TEXT, valor_json TEXT, em TEXT)')
        sistema = falha_antiga(K.ERRO_SISTEMA)
        a = R.gravar_medicao(con, 'a', sistema)
        R.gravar_medicao(con, 'b', sistema)
        R.gravar_medicao(con, 'b', {'ok': True})
        self.assertEqual(R.ler_system_errors(con), {'a': a})

    def test_persistente_grava_segue_a_rodada_e_sai_com_1(self):
        r = rodar(api=ApiRoteada(lojas=SISTEMA))
        self.assertEqual(r.codigo, 1, r.err)
        self.assertNotIn('lojas_sem_pagina', r.api.nomes())           # 10000 não diz nada sobre o pageInfo
        self.assertEqual(r.api.nomes().count('lojas'), K.TENTATIVAS_SISTEMA + 1)
        self.assertEqual(r.valor('lojas')['codigo'], K.ERRO_SISTEMA)
        self.assertIn('conversoes', r.medicoes())                     # a rodada não parou nela
        self.assertIn('lojas', r.err)
        self.assertIn('`shopOfferV2`: não medido (System Error', r.findings)
        self.findings_honesto(r)
        self.sem_vazamento(r)

    def test_a_retomada_refaz_a_medicao_com_system_error(self):
        r = rodar(api=ApiRoteada(lojas=SISTEMA))
        r2 = rodar(pasta=r.pasta)
        self.assertEqual((r2.codigo, r2.api.nomes()), (0, ['base', 'lojas']), r2.err)
        self.assertTrue(r2.valor('lojas')['ok'])
        self.assertNotIn('System Error', r2.findings)

    def test_base_com_system_error_repete_e_o_portao_para(self):
        r = rodar(api=ApiRoteada(base=SISTEMA))
        self.assertEqual((r.codigo, len(r.api.pedidos)), (1, K.TENTATIVAS_SISTEMA + 1), r.err)
        self.assertEqual(set(r.medicoes()), {R.SONDA_BASE})
        r2 = rodar(api=ApiRoteada(base=self.uma_vez(1)))
        self.assertEqual(r2.codigo, 0, r2.err)
        self.assertTrue(r2.valor(R.SONDA_BASE)['ok'])

    def test_reconfirmacao_com_system_error_sai_com_1_sem_medicao_nova(self):
        r1 = rodar(['--max-req', '1'])
        r2 = rodar(pasta=r1.pasta, api=ApiRoteada(base=SISTEMA))
        self.assertEqual((r2.codigo, len(r2.api.pedidos)), (1, K.TENTATIVAS_SISTEMA + 1), r2.err)
        self.assertEqual(r2.linhas('SELECT COUNT(*) FROM medicoes'), [(1,)])
        self.assertIn('reconfirmação', r2.err)

    def test_http_500_com_10000_continua_subindo_sem_gravar(self):
        r = rodar(api=ApiRoteada(lojas=lambda v: http_erro(500, corpo=SISTEMA)))
        self.assertEqual((r.codigo, r.api.nomes().count('lojas')), (1, K.TENTATIVAS_SISTEMA + 1))
        self.assertNotIn('lojas', r.medicoes())
        self.assertNotIn('campanhas', r.api.nomes())

    def test_a_rajada_para_no_10000_sem_tentar_de_novo_e_vale(self):
        api = ApiRoteada()
        api.limite_na_rajada, api.resposta_limite = 96, SISTEMA
        r = rodar(api=api)
        self.assertEqual(r.codigo, 0, r.err)
        v = r.valor('taxa')
        self.assertEqual((v['enviadas'], v['parou_por'], v['codigo'], v['primeiro_limite_na']),
                         (96, 'erro_api', K.ERRO_SISTEMA, None))
        self.assertEqual(api.rajada, 96)                              # nenhuma tentativa a mais
        self.assertEqual(v['mensagem'], 'error [10000]: System Error')
        self.assertIsNone(v['http'])                                  # veio com 200, como a medição do R1
        self.assertFalse([e for e in r.esperas if e >= K.ESPERA_SISTEMA])
        self.assertIn('subid.simples', r.medicoes())                  # a rodada seguiu

    def test_taxa_com_10000_nao_e_refeita_salvo_refazer_taxa(self):
        api = ApiRoteada()
        api.limite_na_rajada, api.resposta_limite = 96, SISTEMA
        r1 = rodar(api=api)
        r2 = rodar(pasta=r1.pasta)
        self.assertEqual((r2.codigo, r2.api.pedidos), (0, []), r2.err)
        self.assertIn('Requisições: 96 de 120', r2.findings)
        r3 = rodar(['--refazer-taxa'], pasta=r1.pasta)
        self.assertEqual((r3.codigo, r3.valor('taxa')['enviadas']), (0, RAJADA), r3.err)

    def test_taxa_antiga_cortada_por_rede_continua_sendo_refeita(self):
        r1 = rodar()
        gravar_antigas(r1.pasta, {'taxa': {'ok': True, 'enviadas': 5, 'parou_por': 'erro_api', 'codigo': None,
                                           'http': None}})
        self.assertEqual(len(rodar(pasta=r1.pasta).api.pedidos), RAJADA + 1)

    def test_system_error_antigo_em_outra_sonda_e_refeito_e_some_do_findings(self):
        r1 = rodar()
        ids = gravar_antigas(r1.pasta, {'campanhas': falha_antiga(K.ERRO_SISTEMA, versao=R.VERSOES['campanhas'])})
        r2 = rodar(pasta=r1.pasta)
        self.assertEqual(r2.api.nomes(), ['base', 'campanhas'])
        self.assertNotIn(f'medicoes #{ids["campanhas"]})', r2.findings)


class TestSondaDeCampos(Base):
    def test_uma_consulta_por_campo_fora_da_producao_e_os_combinados(self):
        api = ApiRoteada()
        api.campos_nulos = {'commission', 'periodEndTime'}
        r = rodar(api=api)
        self.assertEqual(r.codigo, 0, r.err)
        extras = [c for c in r.api.corpos() if c['query'].startswith('query SondaCampos(')]
        self.assertEqual(len(extras), len(C.CAMPOS_EXTRAS) + 1 + 2)
        self.assertTrue(all(c['variables'] == {'keyword': R.TERMO, 'sortType': 1, 'page': c['variables']['page'],
                                               'limit': 50} for c in extras))
        for campo in C.CAMPOS_EXTRAS:
            v = r.valor(f'campos.{campo}')
            if campo in api.campos_nulos:
                self.assertEqual((v['ok'], v['codigo'], v['mensagem']), (False, 10010, 'graphql: got null for non-null'))
            else:
                self.assertTrue(v['ok'], campo)
        comb = r.valor('campos.combinados')
        self.assertEqual(comb['aceitos'], [c for c in C.CAMPOS_EXTRAS if c not in api.campos_nulos])
        self.assertEqual(comb['recusados'], ['commission', 'periodEndTime'])
        self.assertTrue(comb['ok'])
        self.assertEqual(comb['paginas'], {'1': True, '10': True})
        combinadas = extras[-2:]
        self.assertEqual([c['variables']['page'] for c in combinadas], [1, 10])
        for c in combinadas:
            for campo in C.CAMPOS_PRODUCAO + tuple(comb['aceitos']):
                self.assertIn(campo, c['query'])
            self.assertNotIn('commission', re.findall(r'\w+', c['query'].split('nodes {')[1]))
        self.findings_honesto(r)
        self.sem_vazamento(r)

    def test_cada_sonda_pede_a_producao_mais_um_campo(self):
        r = rodar()
        corpos = [c for c in r.api.corpos() if c['query'].startswith('query SondaCampos(')][:len(C.CAMPOS_EXTRAS)]
        self.assertEqual(len(corpos), len(C.CAMPOS_EXTRAS))
        for c, campo in zip(corpos, C.CAMPOS_EXTRAS):
            pedidos = re.findall(r'\w+', c['query'].split('nodes {')[1].split('}')[0])
            self.assertEqual(sorted(pedidos), sorted(C.CAMPOS_PRODUCAO + (campo,)))

    def test_nulos_e_tipo_contados_sem_guardar_valor(self):
        def nos_com_nulo(v):
            return base([{'itemId': i, 'shopId': 7, 'productCatIds': None if i % 2 else [1, 2], 'shopName': ECO}
                         for i in range(1, 5)])
        r = rodar(api=ApiRoteada(campos=nos_com_nulo))
        v = r.valor('campos.productCatIds')
        self.assertEqual((v['n_nos'], v['n_nulos'], v['tipo']), (4, 2, 'lista'))
        self.assertNotIn(ECO, json.dumps(r.valor('campos.shopName')))

    def test_combinado_recusado_vira_ok_falso(self):
        def so_no_combinado(v):
            return erro(10010, 'graphql: got null for non-null') if v['page'] == 10 else None
        r = rodar(api=ApiRoteada(campos=so_no_combinado))
        self.assertEqual(r.codigo, 0, r.err)
        comb = r.valor('campos.combinados')
        self.assertFalse(comb['ok'])
        self.assertEqual(comb['paginas'], {'1': True, '10': False})

    def test_nenhum_aceito_nao_pede_o_combinado(self):
        api = ApiRoteada()
        api.campos_nulos = set(C.CAMPOS_EXTRAS)
        r = rodar(api=api)
        self.assertEqual(r.codigo, 0, r.err)
        self.assertEqual(r.valor('campos.combinados')['aceitos'], [])
        self.assertNotIn('campos.combinado.1', r.medicoes())

    def test_pageinfo_ok_mede_uma_vez_so(self):
        r = rodar()
        self.assertTrue(r.valor('campos.pageInfo')['ok'])
        self.assertNotIn('campos.pageInfo.limit', r.medicoes())

    def test_pageinfo_recusado_separa_por_campo(self):
        """#3 e #45 são as duas consultas com pageInfo: pode ser ele, não um campo do nó, que derruba."""
        api = ApiRoteada()
        api.pagina_quebra = {'hasNextPage'}
        r = rodar(api=api)
        self.assertEqual(r.codigo, 0, r.err)
        self.assertEqual(r.valor('campos.pageInfo')['codigo'], 10010)
        self.assertTrue(r.valor('campos.pageInfo.page')['ok'])
        self.assertTrue(r.valor('campos.pageInfo.limit')['ok'])
        self.assertFalse(r.valor('campos.pageInfo.hasNextPage')['ok'])
        self.assertIn('`hasNextPage`', r.findings)
        self.findings_honesto(r)

    def test_leitor_do_pageinfo(self):
        for ruim in ({'productOfferV2': {'nodes': []}}, {'productOfferV2': {'nodes': [], 'pageInfo': 'x'}}):
            with self.subTest(ruim=ruim), self.assertRaises(C.FormatoInvalido):
                R.ler_info_de_pagina(ruim)
        lido = R.ler_info_de_pagina({'productOfferV2': {'nodes': [{}], 'pageInfo': {
            'page': None, 'limit': 50, 'hasNextPage': True, 'scrollId': ECO}}})
        self.assertEqual(lido, {'n_nos': 1, 'page_info': {'page': None, 'limit': 50, 'hasNextPage': True}})

    def test_rede_na_sonda_de_campo_nao_grava_e_retoma(self):
        r = rodar(api=ApiRoteada(campos=lambda v: urllib.error.URLError('x') if v['limit'] == 50 else None))
        self.assertEqual(r.codigo, 1)
        self.assertNotIn('campos.' + C.CAMPOS_EXTRAS[0], r.medicoes())
        self.assertNotIn('campos.combinados', r.medicoes())
        r2 = rodar(pasta=r.pasta)
        self.assertEqual(r2.codigo, 0, r2.err)
        self.assertIn('campos.combinados', r2.medicoes())

    def test_system_error_num_campo_nao_entra_nos_aceitos_e_o_resumo_e_refeito(self):
        campo = C.CAMPOS_EXTRAS[0]

        def sistema_no_primeiro(v, vezes=[]):
            vezes.append(1)
            return SISTEMA if len(vezes) <= K.TENTATIVAS_SISTEMA + 1 else None
        r = rodar(api=ApiRoteada(campos=sistema_no_primeiro))
        self.assertEqual(r.codigo, 1, r.err)
        self.assertNotIn(campo, r.valor('campos.combinados')['aceitos'])
        r2 = rodar(pasta=r.pasta)
        self.assertEqual(r2.codigo, 0, r2.err)
        self.assertIn(campo, r2.valor('campos.combinados')['aceitos'])

    def test_findings_traz_os_campos(self):
        api = ApiRoteada()
        api.campos_nulos = {'commission'}
        f = rodar(api=api).findings
        self.assertIn('Campos do `productOfferV2`', f)
        self.assertIn('| productLink | aceito', f)
        self.assertRegex(f, r'\| commission \| recusado \(código 10010\) \| \| \(medicoes #\d+\)')
        self.assertIn('aceitos juntos', f)


class TestProfundidadeLimit50(Base):
    def test_grava_a_ultima_com_itens_e_a_repeticao(self):
        def f(v):
            if v['limit'] != 50:
                return None
            if v['page'] > 40:
                return base([])
            return base(nos(range(v['page'] * 100, v['page'] * 100 + 50)))
        r = rodar(api=ApiRoteada(base=f))
        self.assertEqual(r.codigo, 0, r.err)
        teto = r.valor('pagina50.teto')
        self.assertEqual((teto['limit'], teto['ultima_com_itens'], teto['primeira_sem_itens'], teto['repetidas'],
                          teto['itens_ate_a_ultima']), (50, 40, 41, [], 2000))
        pedidas = [c['variables']['page'] for c in r.api.corpos()
                   if c['query'] == R.P_BASE and c['variables']['limit'] == 50 and c['variables']['page'] != 1]
        self.assertEqual(pedidas, list(R.PAGINAS_50))
        self.assertEqual(R.PAGINAS_50, (20, 39, 40, 41, 60, 99))
        self.assertRegex(r.findings, r'\| 41 \| 0 \| \(medicoes #\d+\) \|')
        self.assertIn('última página com itens: 40; primeira sem itens: 41', r.findings)
        self.findings_honesto(r)

    def test_repeticao_e_detectada(self):
        def f(v):
            return base(nos(range(1, 51))) if v['limit'] == 50 and v['page'] >= 39 else None
        teto = rodar(api=ApiRoteada(base=f)).valor('pagina50.teto')
        self.assertEqual(teto['repetidas'], [39, 40, 41, 60, 99])

    def test_system_error_nao_conta_como_sem_itens(self):
        def f(v):
            if v['limit'] != 50:
                return None
            if v['page'] == 41:
                return SISTEMA
            return base(nos(range(v['page'] * 100, v['page'] * 100 + 50))) if v['page'] < 41 else base([])
        r = rodar(api=ApiRoteada(base=f))
        self.assertEqual(r.codigo, 1, r.err)
        teto = r.medicoes()['pagina50.teto'][1]
        self.assertEqual(teto['com_erro'], [41])
        self.assertEqual((teto['ultima_com_itens'], teto['primeira_sem_itens']), (40, 60))
        self.assertIn('pagina50.41', r.err)

    def test_pagina_vazia_antes_de_uma_com_itens_nao_e_o_teto(self):
        def f(v):
            if v['limit'] != 50:
                return None
            return base([]) if v['page'] == 39 else base(nos(range(v['page'] * 100, v['page'] * 100 + 50)))
        teto = rodar(api=ApiRoteada(base=f)).valor('pagina50.teto')
        self.assertEqual((teto['ultima_com_itens'], teto['primeira_sem_itens']), (99, None))

    def test_acrescenta_a_pagina_99_quando_o_teto_fica_ambiguo(self):
        self.assertEqual(R.PASSOS_BISSECAO, 6)
        def f(v):
            if v['limit'] != 20:
                return None
            if v['page'] >= 100:
                return base([])
            inicio = (v['page'] - 1) * 20 + 1
            return base(nos(range(inicio, inicio + 20)))
        r = rodar(api=ApiRoteada(base=f))
        teto = r.valor('pagina.teto')
        self.assertEqual((teto['ultima_util'], teto['primeira_inutil'], teto['exata']), (99, 100, True))
        self.assertIn(99, teto['paginas_medidas'])


class TestConsultasCorrigidas(Base):
    def test_lojas_com_tipo_do_schema_e_queda_sem_pageinfo(self):
        r = rodar(api=ApiRoteada(lojas=erro(10010, 'graphql: got null for non-null')))
        self.assertEqual(r.codigo, 0, r.err)
        self.assertEqual(r.valor('lojas')['codigo'], 10010)
        self.assertEqual(r.valor('lojas')['versao'], R.VERSOES['lojas'])
        self.assertTrue(r.valor('lojas.sem_pagina')['ok'])
        self.assertIn('shopOfferV2` sem pageInfo', r.findings)
        for api in (ApiRoteada(), ApiRoteada(lojas=b'nao e json')):   # sem recusa com código, sem queda
            r = rodar(api=api)
            self.assertNotIn('lojas_sem_pagina', r.api.nomes())
            self.assertNotIn('lojas.sem_pagina', r.medicoes())

    def test_campanhas_sem_pageinfo(self):
        r = rodar()
        self.assertNotIn('pageInfo', R.P_CAMPANHAS)
        self.assertEqual(r.valor('campanhas')['n_nos'], 0)
        self.assertEqual(r.valor('campanhas')['versao'], R.VERSOES['campanhas'])

    def test_campanhas_recusada_fica_nao_medida(self):
        r = rodar(api=ApiRoteada(campanhas=erro(10010, ECO)))
        self.assertEqual(r.codigo, 0, r.err)
        self.assertIn('`shopeeOfferV2`: não medido (a sonda falhou: código 10010)', r.findings)

    def test_feeds_um_por_modo_e_o_delta_sem_dados(self):
        def so_delta(v):
            if v['feedMode'] == 'FULL':
                return {'data': {'listItemFeeds': {'feeds': []}}}
            return None
        r = rodar(api=ApiRoteada(feeds=so_delta))
        self.assertEqual(r.valor('feeds.full')['n_feeds'], 0)
        self.assertNotIn('feeds.dados', r.medicoes())                 # só a página do FULL é medida
        self.assertIn('nenhum datafeedId', r.out)

    def test_coluna_em_texto_com_cabecalho_ou_sem(self):
        self.assertEqual(R.colunas_da_linha('itemId,itemName,price'),
                         {'formato': 'texto', 'separador': ',', 'n_campos': 3,
                          'colunas': ['itemId', 'itemName', 'price'], 'colunas_recusadas': 0})
        # linha de dados: conta, mas não guarda nada dela
        linha = R.colunas_da_linha('123|Vestido ' + ECO + '|9.90')
        self.assertEqual((linha['n_campos'], linha['colunas'], linha['formato'], linha['colunas_recusadas']),
                         (3, [], 'texto', 3))
        self.assertEqual(R.colunas_da_linha('Vestido')['colunas'], [])   # uma palavra só pode ser dado
        self.assertNotIn(ECO, json.dumps(linha))
        objeto = R.colunas_da_linha(json.dumps({'itemId': 1, 'nome ruim!': 2}))
        self.assertEqual((objeto['formato'], objeto['colunas'], objeto['colunas_recusadas']),
                         ('json_objeto', ['itemId'], 1))
        lista = R.colunas_da_linha(json.dumps([1, 'Vestido ' + ECO]))
        self.assertEqual((lista['formato'], lista['n_campos'], lista['colunas']), ('json_lista', 2, []))
        self.assertEqual(R.colunas_da_linha(None)['n_campos'], 0)
        self.assertEqual(R.colunas_da_linha('')['n_campos'], 0)

    def test_dados_do_feed_nunca_guardam_linha(self):
        r = rodar()
        (texto,) = r.linhas("SELECT valor_json FROM medicoes WHERE nome = 'feeds.dados'")[0]
        self.assertNotIn(ECO, texto)
        self.assertNotIn('9.90', texto)
        self.assertNotIn('Moda', texto)
        self.assertNotIn(ECO.encode(), comum.conteudo_da_pasta(r.pasta))

    def test_dados_do_feed_fora_do_formato_viram_medicao_de_formato(self):
        for ruim in ({'rows': 'x', 'pageInfo': {}}, {'rows': [1], 'pageInfo': {}}, {'rows': []},
                     {'rows': [], 'pageInfo': 'x'}):
            with self.subTest(ruim=ruim):
                r = rodar(api=ApiRoteada(dados_feed={'data': {'getItemFeedData': ruim}}))
                self.assertEqual(r.codigo, 0, r.err)
                self.assertEqual(r.valor('feeds.dados')['falha'], 'resposta_invalida')

    def test_feed_recusa_o_limite_e_cai_no_menor(self):
        r = rodar(api=ApiRoteada(dados_feed=lambda v: erro(11001, ECO) if v['limit'] == R.LIMITE_FEED else None))
        self.assertEqual(r.codigo, 0, r.err)
        self.assertEqual(r.valor('feeds.dados')['codigo'], 11001)
        self.assertTrue(r.valor('feeds.dados_menor')['ok'])

    def test_feed_fora_do_formato_nao_derruba_a_rodada(self):
        for ruim in ({'data': {'listItemFeeds': []}}, {'data': {'listItemFeeds': {'feeds': 'x'}}},
                     {'data': {'listItemFeeds': {'feeds': [1]}}}):
            with self.subTest(ruim=ruim):
                r = rodar(api=ApiRoteada(feeds=ruim))
                self.assertEqual(r.codigo, 0, r.err)
                self.assertEqual(r.valor('feeds.full')['falha'], 'resposta_invalida')

    def test_versao_nova_nao_e_invalidada_e_a_antiga_e(self):
        con = sqlite3.connect(':memory:')
        self.addCleanup(con.close)
        con.execute('CREATE TABLE medicoes (id INTEGER PRIMARY KEY, nome TEXT, valor_json TEXT, em TEXT)')
        for nome in R.VERSOES:
            R.gravar_medicao(con, nome, {'ok': True})
        self.assertEqual(set(R.ler_medicoes(con)) & set(R.VERSOES), set())
        for nome, versao in R.VERSOES.items():
            R.gravar_medicao(con, nome, {'ok': True, 'versao': versao})
        self.assertEqual(set(R.ler_medicoes(con)) & set(R.VERSOES), set(R.VERSOES))
        self.assertEqual(set(R.VERSOES), {'produtos.consulta', 'lojas', 'campanhas', 'conversoes'})


# ---------- R4: sinal real no meio da rodada ----------
SCRIPT_SINAL = r'''
import os, signal, sys
sys.path.insert(0, sys.argv[1])
import test_reconhecer as T
from test_reconhecer import ApiRoteada, comum, G
pasta, n = sys.argv[2], int(sys.argv[3])
class Para(ApiRoteada):
    def responder(self, q, v):
        if len(self.pedidos) == n:
            print('PRONTO', flush=True)
            signal.pause()
        return super().responder(q, v)
os.environ.update({'ACHADINHOS_GARIMPO_DIR': pasta, 'ACHADINHOS_SHOPEE_APP_ID': comum.APP_ID,
                   'ACHADINHOS_SHOPEE_SECRET': comum.SECRET})
with comum.isolado(Para()):
    sys.exit(G.main(['reconhecer']))
'''


class TestSinalReal(Base):
    def interromper(self, n, sinal):
        pasta = comum.nova_pasta()
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
        p = subprocess.Popen([sys.executable, '-c', SCRIPT_SINAL, os.path.dirname(os.path.abspath(__file__)), pasta,
                              str(n)], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        guarda = threading.Timer(60, p.kill)
        guarda.start()
        try:
            for linha in p.stdout:
                if 'PRONTO' in linha:
                    break
            p.send_signal(sinal)
            _, err = p.communicate(timeout=60)
        finally:
            guarda.cancel()
            if p.poll() is None:
                p.kill()
                p.communicate()
        self.assertEqual(p.returncode, 130, err)
        self.assertNotIn('Traceback', err)
        return Resultado(p.returncode, '', err, None, None, None, pasta)

    def test_kill_no_meio_sai_com_130_com_banco_integro_e_retoma(self):
        for sinal in (signal.SIGTERM, signal.SIGHUP):
            with self.subTest(sinal=sinal.name):
                r = self.interromper(10, sinal)
                self.assertTrue(r.log.rstrip().endswith('SAIDA=130'))
                self.assertIn('Interrompido', r.err)
                self.assertEqual(r.linhas('PRAGMA integrity_check'), [('ok',)])
                with banco.travar(r.pasta):
                    pass
                self.assertIn('Rajada: não medido', r.findings)     # os achados parciais saíram
                self.assertNotIn(SECRET.encode(), comum.conteudo_da_pasta(r.pasta))
                self.assertEqual([n for n in os.listdir(os.path.join(r.pasta, 'docs')) if n.endswith('.tmp')], [])
                r2 = rodar(pasta=r.pasta)
                self.assertEqual(r2.codigo, 0, r2.err)
                # além da rodada normal, só a sonda em curso e a reconfirmação
                self.assertEqual(r2.linhas('SELECT COUNT(*) FROM requisicoes'), [(REQUISICOES_PADRAO + 2,)])
                self.assertEqual(r2.linhas('SELECT COUNT(*) FROM medicoes'), [(len(MEDICOES_PADRAO),)])

    def test_kill_na_rajada_nao_grava_a_taxa(self):
        r = self.interromper(60, signal.SIGTERM)
        self.assertTrue(r.log.rstrip().endswith('SAIDA=130'))
        self.assertNotIn('taxa', r.medicoes())


# ---------- CA7: teto, retomada e saídas ----------
class TestTetoERetomada(Base):
    def test_as_requisicoes_contam_no_teto_da_rodada(self):
        r = rodar(['--max-req', '10'])
        self.assertEqual(r.codigo, 3)
        self.assertEqual(len(r.api.pedidos), 10)
        self.assertEqual(r.linhas('SELECT COUNT(*) FROM requisicoes'), [(10,)])
        self.assertIn('--max-req', r.err)
        self.assertTrue(r.log.rstrip().endswith('SAIDA=3'))
        self.assertIn('pagina.10', r.medicoes())        # o 10º pedido foi medido; o 11º não saiu
        self.assertNotIn('pagina.teto', r.medicoes())
        self.assertIn('Rajada: não medido', r.findings)   # os achados parciais são gerados mesmo assim
        self.findings_honesto(r)
        self.sem_vazamento(r)

    def test_retomada_pula_o_que_ja_foi_medido_e_refazer_mede_de_novo(self):
        r1 = rodar(['--max-req', '10'])
        r2 = rodar(pasta=r1.pasta)
        self.assertEqual(r2.codigo, 0, r2.err)
        self.assertEqual(len(r1.api.pedidos) + len(r2.api.pedidos), REQUISICOES_PADRAO + 1)   # + a reconfirmação
        self.assertNotIn('introspeccao', r2.api.nomes())
        self.assertEqual(set(r2.medicoes()), MEDICOES_PADRAO)
        self.assertEqual(r2.linhas("SELECT COUNT(*) FROM medicoes WHERE nome = 'limit.20'"), [(1,)])
        self.assertEqual(r2.linhas('SELECT COUNT(*) FROM requisicoes'), [(REQUISICOES_PADRAO + 1,)])
        self.assertIn('já medido', r2.out)
        r3 = rodar(['--refazer'], pasta=r1.pasta)
        self.assertEqual((r3.codigo, len(r3.api.pedidos)), (0, REQUISICOES_PADRAO - RAJADA))   # sem a rajada
        self.assertEqual(r3.linhas("SELECT COUNT(*) FROM medicoes WHERE nome = 'limit.20'"), [(2,)])
        self.findings_honesto(r3)
        self.sem_vazamento(r3)

    def test_teto_total_conta_o_que_ja_estava_no_banco(self):
        r1 = rodar(['--max-req', '10'])
        r2 = rodar(pasta=r1.pasta, achados={'max_total_requests': 15})
        self.assertEqual(r2.codigo, 3)
        self.assertEqual(len(r2.api.pedidos), 5)
        self.assertIn('max_total_requests', r2.err)

    def test_teto_no_meio_da_rajada_nao_grava_meia_medicao(self):
        r = rodar(['--max-req', '60'])
        self.assertEqual(r.codigo, 3)
        self.assertGreater(r.api.rajada, 0)
        self.assertNotIn('taxa', r.medicoes())
        self.assertEqual(r.linhas('SELECT COUNT(*) FROM requisicoes'), [(60,)])

    def test_limite_da_api_fora_da_rajada_sai_com_3(self):
        api = ApiRoteada(produtos=erro(CS.ERRO_LIMITE, ECO))
        r = rodar(api=api)
        self.assertEqual(r.codigo, 3)
        self.assertEqual(api.nomes().count('produtos'), 6)   # as 5 esperas do cliente
        self.assertNotIn('produtos.consulta', r.medicoes())
        self.sem_vazamento(r)

    def test_ctrl_c_sai_com_130_e_gera_os_achados_parciais(self):
        r = rodar(api=ApiRoteada(lojas=KeyboardInterrupt()))
        self.assertEqual(r.codigo, 130)
        self.assertIn('feeds.dados', r.medicoes())
        self.assertNotIn('lojas', r.medicoes())
        self.assertIn('`shopOfferV2`: não medido\n', r.findings)
        self.assertIn('`conversionReport`: não medido\n', r.findings)
        self.assertEqual(r.linhas('SELECT COUNT(*) FROM requisicoes'), [(len(r.api.pedidos),)])
        self.sem_vazamento(r)


# ---------- links das sondas de subId ----------
class TestLinks(Base):
    def test_dono_errado_sai_com_1_e_o_link_nao_fica_em_lugar_nenhum(self):
        r = rodar(conferencia=ConferenciaFalsa(id_afiliado='999'))
        self.assertEqual(r.codigo, 1)
        v = r.valor('subid.simples')
        self.assertEqual((v['ok'], v['dono_ok']), (True, False))
        self.assertNotIn('link', v)
        self.assertNotIn('subid.hifen', r.medicoes())
        self.assertNotIn(b's.shopee.com.br', comum.conteudo_da_pasta(r.pasta))
        self.assertIn('NÃO (link de outro afiliado)', r.findings)
        self.sem_vazamento(r)
        # retomada: a medição do dono errado já existe e não trava as sondas seguintes, mas a saída continua 1
        r2 = rodar(pasta=r.pasta)
        self.assertEqual(r2.codigo, 1, r2.err)
        self.assertIn('subid.hifen', r2.medicoes())
        self.assertIn('outro afiliado', r2.err)
        self.assertTrue(r2.log.rstrip().endswith('SAIDA=1'))
        # o --refazer mede de novo; com o dono certo, a saída volta a 0 (e a rajada não se repete)
        r3 = rodar(['--refazer'], pasta=r.pasta)
        self.assertEqual(r3.codigo, 0, r3.err)
        self.assertIs(r3.valor('subid.simples')['dono_ok'], True)
        self.assertNotIn('NÃO (link de outro afiliado)', r3.findings)

    def test_link_que_nao_e_o_curto_da_shopee_nao_e_conferido_nem_guardado(self):
        api = ApiRoteada(link={'data': {'generateShortLink': {'shortLink': 'https://evil.example/' + ECO}}})
        r = rodar(api=api)
        self.assertEqual(r.codigo, 0, r.err)
        v = r.valor('subid.hifen')
        self.assertEqual((v['ok'], v['link_valido']), (True, False))
        self.assertNotIn('dono_ok', v)
        self.assertEqual(r.conferencia.links, [])
        self.assertNotIn(b'evil.example', comum.conteudo_da_pasta(r.pasta))
        self.sem_vazamento(r)

    def test_conferencia_sem_rede_deixa_o_link_so_no_banco(self):
        def sem_rede(req, timeout=None):
            raise urllib.error.URLError('rede caiu')

        r = rodar(conferencia=sem_rede)
        self.assertEqual(r.codigo, 1, r.err)   # sem conferir o dono, a saída não pode ser 0
        v = r.valor('subid.sublinhado')
        self.assertEqual((v['dono_ok'], v['link']), (None, LINK))
        self.assertIn('não deu para conferir', r.findings)
        self.assertFalse(os.path.exists(os.path.join(r.pasta, 'exports')))
        self.assertEqual(r.linhas('SELECT COUNT(*) FROM test_links'), [(0,)])

    def test_subid_recusado_pela_api(self):
        api = ApiRoteada(link=lambda v: erro(11001, ECO) if '-' in ''.join(v['input']['subIds']) else None)
        r = rodar(api=api)
        self.assertEqual(r.valor('subid.hifen')['codigo'], 11001)
        self.assertTrue(r.valor('subid.sublinhado')['ok'])
        self.assertEqual(len(r.conferencia.links), 2)


class TestConferenciaSemResposta(Base):
    """R9: conferência que não chegou a ver um 3xx não diz nada sobre o dono do link."""

    @staticmethod
    def sem_rede(req, timeout=None):
        raise urllib.error.URLError('rede caiu')

    @staticmethod
    def sem_3xx(req, timeout=None):
        return comum.Resp(b'pagina')

    @staticmethod
    def http_503(req, timeout=None):
        raise http_erro(503, url=req.full_url)

    def test_nao_e_link_de_outro_afiliado(self):
        for nome, conf in (('rede', self.sem_rede), ('200', self.sem_3xx), ('503', self.http_503)):
            with self.subTest(caso=nome):
                r = rodar(conferencia=conf)
                self.assertEqual(r.codigo, 1, r.err)
                for sonda, _ in R.SUBIDS:
                    self.assertIsNone(r.valor(f'subid.{sonda}')['dono_ok'])
                self.assertNotIn('outro afiliado', r.findings)
                self.assertNotIn('outro afiliado', r.err + r.out)
                self.assertIn('não deu para conferir', r.findings)
                self.assertIn('não deu para conferir', r.err)
                self.assertIn('a próxima rodada refaz esta sonda', r.out)
                self.assertIn('lojas', r.medicoes())   # o resto da rodada foi medido
                self.sem_vazamento(r)

    def test_a_proxima_rodada_refaz_a_conferencia(self):
        r1 = rodar(conferencia=self.sem_rede)
        r2 = rodar(pasta=r1.pasta)
        self.assertEqual(r2.codigo, 0, r2.err)
        self.assertEqual(r2.api.nomes(), ['base'] + ['link'] * 3)   # a reconfirmação e só as 3 sondas de subId
        self.assertIs(r2.valor('subid.simples')['dono_ok'], True)
        self.assertNotIn('não deu para conferir', r2.findings)

    def test_dono_errado_de_verdade_continua_parando_e_sem_o_link(self):
        r = rodar(conferencia=ConferenciaFalsa(location='https://shopee.com.br/x?utm_source=an_999'))
        self.assertEqual(r.codigo, 1)
        self.assertIs(r.valor('subid.simples')['dono_ok'], False)
        self.assertNotIn('link', r.valor('subid.simples'))
        self.assertIn('PAROU', r.err)
        self.assertNotIn('subid.hifen', r.medicoes())

    def test_location_de_outro_host_e_dono_errado(self):
        r = rodar(conferencia=ConferenciaFalsa(location='https://evil.example/x?utm_source=an_' + CS.ID_AFILIADO_SHOPEE))
        self.assertEqual(r.codigo, 1)
        self.assertIs(r.valor('subid.simples')['dono_ok'], False)

    def test_medicao_antiga_sem_conferencia_conta_como_nao_medida(self):
        r1 = rodar()
        gravar_antigas(r1.pasta, {'subid.hifen': {'ok': True, 'link_valido': True, 'dono_ok': None, 'link': LINK,
                                                  'sub_ids': ['fem', 'sonda-hifen']}})
        r2 = rodar(pasta=r1.pasta)
        self.assertEqual(r2.codigo, 0, r2.err)
        self.assertEqual(r2.api.nomes(), ['base', 'link'])
        self.assertIs(r2.valor('subid.hifen')['dono_ok'], True)


# ---------- mensagem de erro e eco ----------
class TestMensagem(Base):
    SUJA = (ECO + ' Signature=' + 'ab' * 32 + ' Credential=1800012345, Timestamp: 1700000000 '
            + 'f' * 64 + ' \x1b[31m\r\n' + 'y' * 2000)

    def test_saneada_cortada_e_so_no_banco(self):
        for resposta in (erro(10010, self.SUJA), http_erro(400, corpo=erro(10010, self.SUJA))):
            with self.subTest(http=isinstance(resposta, urllib.error.HTTPError)):
                r = rodar(api=ApiRoteada(introspeccao=resposta))
                msg = r.valor('schema.introspeccao')['mensagem']
                self.assertTrue(msg.startswith(ECO), msg)
                self.assertLessEqual(len(msg), R.MAX_MENSAGEM)
                for proibido in ('Signature', 'abab', '1800012345', '1700000000', 'ffff', '\x1b', '\r', '\n'):
                    self.assertNotIn(proibido, msg)
                self.sem_vazamento(r)

    def test_mensagem_em_extensions(self):
        r = rodar(api=ApiRoteada(introspeccao={'errors': [{'extensions': {'code': 10010, 'message': ECO}}]}))
        self.assertEqual(r.valor('schema.introspeccao')['mensagem'], ECO)

    def test_funcao_pura(self):
        self.assertIsNone(R.mensagem_de_erro({'data': {}}))
        self.assertIsNone(R.mensagem_de_erro({'errors': [{'message': 7}]}))
        self.assertIsNone(R.mensagem_de_erro({'errors': 'x'}))
        self.assertEqual(R.mensagem_de_erro({'errors': [{'message': 'secret=abc ok'}]}), '[removido] ok')

    def test_o_leitor_original_volta_mesmo_quando_a_fase_falha(self):
        original = CS._ler_json
        rodar(conferencia=ConferenciaFalsa(id_afiliado='999'))
        self.assertIs(CS._ler_json, original)


# ---------- nenhuma consulta vem de dado externo ----------
class TestConsultasConstantes(unittest.TestCase):
    def setUp(self):
        self.arvore = ast.parse(FONTE)

    def test_montar_so_no_nivel_do_modulo(self):
        for f in ast.walk(self.arvore):
            if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                for c in ast.walk(f):
                    if isinstance(c, ast.Call):
                        alvo = c.func.attr if isinstance(c.func, ast.Attribute) else getattr(c.func, 'id', '')
                        self.assertNotEqual(alvo, '_montar', ast.unparse(c))

    def test_toda_chamada_a_api_usa_uma_constante(self):
        constantes_modulo = {alvo.id for n in self.arvore.body if isinstance(n, ast.Assign)
                             for alvo in n.targets if isinstance(alvo, ast.Name) and alvo.id.isupper()}
        chamadas = [c for c in ast.walk(self.arvore) if isinstance(c, ast.Call)
                    and isinstance(c.func, ast.Attribute) and c.func.attr in ('medir', 'pedir')]
        self.assertGreaterEqual(len(chamadas), 15)
        for c in chamadas:
            with self.subTest(chamada=ast.unparse(c)):
                q = c.args[0]
                if isinstance(q, ast.Name):
                    self.assertIn(q.id, constantes_modulo | {'consulta'})
                    if q.id == 'consulta':   # só o parâmetro do próprio `medir`
                        self.assertIn('self.cli.pedir(consulta', ast.unparse(c))
                elif isinstance(q, ast.Call):    # só a montagem que recusa nome fora de CAMPOS_PRODUTO (test_consultas)
                    self.assertEqual(ast.unparse(q.func), 'C.consulta_com_campos')
                else:
                    self.assertIsInstance(q, ast.Attribute)
                    self.assertEqual((q.value.id, q.attr.isupper()), ('C', True))

    def test_variantes_sem_valor_embutido(self):
        for texto in R.CONSULTAS_DA_FASE:
            with self.subTest(consulta=texto.split('(')[0].split('{')[0]):
                for proibido in ('"', "'", '\\', '...'):
                    self.assertNotIn(proibido, texto)
                self.assertIsNone(re.search(r'(?<![A-Za-z0-9_])\d', texto))
                self.assertIsNone(re.search(r'\b(true|false|null)\b', texto))
                self.assertEqual(texto.count('{'), texto.count('}'))
                for var, tipo in re.findall(r'\$(\w+): ([^,)]+)', texto):
                    self.assertEqual(tipo, R._TIPOS_INTROSPECCAO[var], var)

    def test_variantes_de_produto_declaram_so_o_que_usam(self):
        self.assertEqual(re.findall(r'\$(\w+): ', R.P_BASE), ['keyword', 'sortType', 'page', 'limit'])
        self.assertEqual(re.findall(r'\$(\w+): ', R.P_LISTTYPE), ['listType', 'matchId', 'page', 'limit'])
        self.assertEqual(re.findall(r'\$(\w+): ', R.P_ITEM), ['shopId', 'itemId', 'page', 'limit'])
        self.assertIn('$matchId: ' + C.TIPO_ID, R.P_LISTTYPE)
        self.assertIn('$productCatId: ' + C.TIPO_CATEGORIA, R.P_CATEGORIA)
        self.assertIn('$name: String!', R.TIPO_POR_NOME)
        self.assertTrue(R.TIPO_POR_NOME.startswith('query TipoPorNome($name: String!) {\n  __type(name: $name)'))

    def test_todas_as_consultas_enviadas_sao_constantes(self):
        r = rodar(api=ApiRoteada(introspeccao=erro(1, 'off')))
        enviadas = {c['query'] for c in r.api.corpos() if not c['query'].startswith('query SondaCampos(')}
        self.assertLessEqual(enviadas, set(CONSTANTES))
        self.assertEqual(r.api.desconhecidas, [])

    def test_nao_le_ambiente_nem_abre_rede_crua(self):
        for proibido in ('os.environ', 'getenv', 'urlopen', 'OPENER_API', 'OPENER_CONFERENCIA', 'test_links',
                         'exports'):
            self.assertNotIn(proibido, FONTE.split('"""', 2)[2], proibido)


if __name__ == '__main__':
    unittest.main()
