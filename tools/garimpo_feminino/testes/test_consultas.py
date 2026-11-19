#!/usr/bin/env python3
"""Testes do consultas.py (etapa 5 do garimpo feminino: CA7 e CA9). Sem rede.

Rodar: python3 tools/garimpo_feminino/testes/test_consultas.py -v

Cobrem: (1) a forma das consultas (campos do brief, variáveis declaradas e usadas, nada de valor embutido);
(2) nenhuma consulta muda com o valor das variáveis, nem no corpo que o `cliente` monta nem no pedido enviado;
(3) a consulta não recebe dado externo (só constantes, `_montar` só no nível do módulo, nomes recusados);
(4) os leitores de `nodes` e `pageInfo` recusam formato errado com motivo fixo, sem ecoar a resposta.
Os proxies apontam para 127.0.0.1:9 e a rede é trocada por falsos (`comum.isolado`).
"""
import ast
import json
import os
import re
import unittest

import comum  # noqa: F401  (isolamento: tem de vir antes dos módulos do garimpo)
from comum import CS, ApiFalsa, cred, no, resposta

import cliente as K  # noqa: E402
import consultas as C  # noqa: E402

CAMINHO = os.path.join(comum.PASTA, 'consultas.py')
with open(CAMINHO, encoding='utf-8') as _f:
    FONTE = _f.read()

# Campos do `productOfferV2` do brief (seção 1, "Retorno do productOfferV2"), em ordem.
CAMPOS_BRIEF = ['itemId', 'productName', 'productLink', 'offerLink', 'imageUrl', 'priceMin', 'priceMax',
                'priceDiscountRate', 'sales', 'ratingStar', 'commissionRate', 'sellerCommissionRate',
                'shopeeCommissionRate', 'commission', 'productCatIds', 'shopId', 'shopName', 'shopType',
                'periodStartTime', 'periodEndTime']
ARGUMENTOS_BRIEF = ['keyword', 'shopId', 'itemId', 'productCatId', 'listType', 'matchId', 'sortType', 'page',
                    'limit', 'isAMSOffer', 'isKeySeller']
MARCADOR = 'ECO-DA-API-7c3f19'   # texto "vindo da API": nunca pode aparecer em exceção
HOSTIL = ['vestido"} } mutation { x', "a' OR 1=1 --", '$page', '\\u0000', 'linha\nnova', '{ itemId }',
          '${keyword}', 'çãõ 日本語 🙂', '', ' ' * 3, 'x' * 5000]


def corpo_nos(corpo_query):
    """Trecho `nodes { ... }` de uma consulta, só com os nomes dos campos de primeiro nível."""
    m = re.search(r'nodes \{ ([^{}]*?)(?: \{|\s*\})', corpo_query)
    return m.group(1).split() if m else []


# ---------- (1) forma das consultas ----------
class TestForma(unittest.TestCase):
    def test_a_primeira_operacao_de_cada_consulta_e_a_esperada(self):
        for nome, texto in C.OPERACOES.items():
            with self.subTest(operacao=nome):
                self.assertEqual(K.operacao_de(texto), nome)

    def test_as_nove_operacoes_pedidas_existem(self):
        self.assertEqual(set(C.OPERACOES), {'productOfferV2', 'shopOfferV2', 'shopeeOfferV2', 'generateShortLink',
                                            'conversionReport', 'validatedReport', 'listItemFeeds',
                                            'getItemFeedData', '__schema'})
        self.assertTrue(C.GERAR_LINK.startswith('mutation '))
        for nome, texto in C.OPERACOES.items():
            if nome != 'generateShortLink':
                self.assertTrue(texto.startswith('query '), nome)

    def test_productoffer_traz_todos_os_campos_do_brief_e_nao_pede_o_pageinfo(self):
        texto = C.CONSULTA_PRODUTOS
        self.assertEqual(corpo_nos(texto), CAMPOS_BRIEF)
        self.assertEqual(list(C.CAMPOS_PRODUTO), CAMPOS_BRIEF)
        self.assertNotIn('pageInfo', texto)   # recusada com ele no R1 (#3 e #47), aceita sem ele (#72 a #74)
        for campo in ('hasNextPage', 'page limit', 'scrollId'):
            self.assertNotIn(campo, texto)
        self.assertTrue(texto.rstrip().endswith('}\n  }\n}'), texto[-20:])   # fecha o `nodes { ... }` sem mais nada

    def test_a_consulta_de_lojas_tambem_nao_pede_o_pageinfo(self):
        self.assertNotIn('pageInfo', C.CONSULTA_LOJAS)   # recusada com ele (#85), aceita sem ele (#86)
        self.assertEqual(corpo_nos(C.CONSULTA_LOJAS), list(C.CAMPOS_LOJA))
        self.assertEqual(C.OPERACOES['productOfferV2'], C.CONSULTA_PRODUTOS)
        self.assertEqual(C.OPERACOES['shopOfferV2'], C.CONSULTA_LOJAS)

    def test_a_sonda_do_reconhecer_guarda_o_texto_com_pageinfo_igual_ao_de_antes(self):
        import fase_reconhecer as R
        com_info = ' pageInfo { page limit hasNextPage }'
        for antiga, atual in ((R.P_PRODUTOS_COM_PAGINA, C.CONSULTA_PRODUTOS), (R.P_LOJAS_COM_PAGINA, C.CONSULTA_LOJAS)):
            self.assertIn('pageInfo { page limit hasNextPage }', antiga)
            self.assertEqual(antiga.replace(com_info, ''), atual)   # só o pageInfo as diferencia

    def test_productoffer_declara_todos_os_argumentos_do_brief(self):
        declaradas = re.findall(r'\$(\w+): ', C.CONSULTA_PRODUTOS)
        self.assertEqual(declaradas, ARGUMENTOS_BRIEF)
        usadas = re.findall(r'(\w+): \$', C.CONSULTA_PRODUTOS)
        self.assertEqual(usadas, ARGUMENTOS_BRIEF)

    def test_campanhas_trazem_pageinfo_e_relatorios_o_scrollid(self):
        # produtos e lojas não pedem o pageInfo (testes acima); as campanhas ficam como estavam (#87 é da sonda)
        self.assertIn('pageInfo { page limit hasNextPage }', C.OPERACOES['shopeeOfferV2'])
        for nome in ('conversionReport', 'validatedReport'):
            self.assertIn('pageInfo { limit hasNextPage scrollId }', C.OPERACOES[nome], nome)
            self.assertIn('$scrollId: String', C.OPERACOES[nome], nome)
            self.assertIn('scrollId: $scrollId', C.OPERACOES[nome], nome)

    def test_as_chaves_dos_relatorios_e_dos_feeds(self):
        self.assertIn('utmContent', C.RELATORIO_CONVERSOES)
        self.assertIn('$purchaseTimeStart', C.RELATORIO_CONVERSOES)
        self.assertIn('$datafeedId: String!', C.DADOS_FEED)   # o id do datafeed vai como texto (pode ser composto)
        self.assertIn('$offset: Int', C.DADOS_FEED)
        self.assertIn('$input: ShortLinkInput!', C.GERAR_LINK)

    def test_tipos_corrigidos_pelo_schema_do_r1(self):
        self.assertIn('$shopType: [Int!]', C.CONSULTA_LOJAS)
        self.assertIn('$purchaseTimeStart: Int64', C.RELATORIO_CONVERSOES)
        self.assertIn('$purchaseTimeEnd: Int64', C.RELATORIO_CONVERSOES)
        self.assertIn('$orderStatus: DisplayOrderStatus', C.RELATORIO_CONVERSOES)
        self.assertIn('$feedMode: FeedMode', C.LISTAR_FEEDS)
        self.assertIn('listItemFeeds(feedMode: $feedMode)', C.LISTAR_FEEDS)
        self.assertIn('feeds { datafeedId referenceId datafeedName description totalCount date feedMode }',
                      C.LISTAR_FEEDS)
        self.assertIn('rows { columns updateType }', C.DADOS_FEED)
        self.assertIn('pageInfo { offset limit totalCount hasMore }', C.DADOS_FEED)
        self.assertEqual(C.TIPOS['productCatId'], 'Int')

    def test_toda_variavel_declarada_e_usada_e_vice_versa(self):
        for nome, texto in C.OPERACOES.items():
            with self.subTest(operacao=nome):
                decl = re.findall(r'\$(\w+): ', texto)
                usos = re.findall(r'\b(\w+): \$(\w+)', texto)
                self.assertEqual(decl, [v for _, v in usos])
                self.assertTrue(all(a == v for a, v in usos), 'argumento e variável com nomes diferentes')
                self.assertEqual(len(decl), len(set(decl)))

    def test_o_tipo_de_cada_variavel_vem_so_da_tabela(self):
        for nome, texto in C.OPERACOES.items():
            with self.subTest(operacao=nome):
                for var, tipo in re.findall(r'\$(\w+): ([^,)]+)', texto):
                    self.assertEqual(tipo, C.TIPOS[var], var)

    def test_nenhuma_consulta_tem_valor_embutido(self):
        for nome, texto in C.OPERACOES.items():
            with self.subTest(operacao=nome):
                self.assertNotIn('"', texto)
                self.assertNotIn("'", texto)
                self.assertNotIn('\\', texto)
                # nenhum número fora de identificador, nenhum literal true/false/null
                self.assertIsNone(re.search(r'(?<![A-Za-z0-9_])\d', texto))
                self.assertIsNone(re.search(r'\b(true|false|null)\b', texto))
                # nada entre parênteses além de `nome: $variavel` ou `$variavel: Tipo`
                for dentro in re.findall(r'\(([^()]*)\)', texto.split('{', 1)[0] + texto.split('{', 2)[1]):
                    for parte in dentro.split(','):
                        self.assertRegex(parte.strip(), r'^(\$?\w+: (\$\w+|\[?\w+!?\]?!?))$')
                self.assertEqual(texto.count('{'), texto.count('}'))

    def test_trocar_o_tipo_na_tabela_muda_so_a_declaracao(self):
        outros = dict(C.TIPOS, productCatId='Int64', matchId='String')
        novo = C._montar('query', 'ProdutosPorOferta', 'productOfferV2', tuple(ARGUMENTOS_BRIEF),
                         C._nos(C.CAMPOS_PRODUTO), tipos=outros)
        esperado = (C.CONSULTA_PRODUTOS.replace('$productCatId: Int,', '$productCatId: Int64,')
                    .replace('$matchId: Int64,', '$matchId: String,'))
        self.assertNotEqual(novo, C.CONSULTA_PRODUTOS)
        self.assertEqual(novo, esperado)

    def test_pontos_nao_confirmados_levam_a_marca_a_confirmar(self):
        linhas = FONTE.splitlines()
        for chave in ("'input':", "'datafeedId':"):
            with self.subTest(chave=chave):
                achadas = [l for l in linhas if l.lstrip().startswith(chave)]
                self.assertTrue(achadas, chave)
                self.assertTrue(all('a confirmar (R1)' in l for l in achadas), achadas)

    def test_tipos_medidos_no_r1_citam_a_medicao(self):
        """Etapa 8: o que o R1 mediu deixa de ser "a confirmar" e passa a apontar a linha de `medicoes` (#id)."""
        linhas = FONTE.splitlines()
        for chave in ("'productCatId':", "'listType':", "'matchId':", 'TIPO_ID =', 'TIPO_CATEGORIA ='):
            with self.subTest(chave=chave):
                achadas = [l for l in linhas if l.lstrip().startswith(chave)]
                self.assertTrue(achadas, chave)
                for l in achadas:
                    self.assertIn('medido no R1', l)
                    self.assertRegex(l, r'#\d+')
                    self.assertNotIn('a confirmar', l)
        # e a tabela diz o mesmo que o R1 mediu: productCatId é Int; shopId, itemId e matchId são Int64
        self.assertEqual((C.TIPOS['productCatId'], C.TIPOS['shopId'], C.TIPOS['itemId'], C.TIPOS['matchId']),
                         ('Int', 'Int64', 'Int64', 'Int64'))

    def test_a_introspeccao_pede_o_schema(self):
        t = C.INTROSPECCAO
        self.assertIn('__schema', t)
        self.assertIn('queryType', t)
        self.assertIn('mutationType', t)
        self.assertNotIn('$', t)
        self.assertEqual(t.count('{'), t.count('}'))


# ---------- (2) a consulta não muda com o valor das variáveis ----------
class TestConsultaConstante(unittest.TestCase):
    def variaveis_de(self, texto, valor):
        return {v: valor for v in re.findall(r'\$(\w+): ', texto)}

    def test_o_corpo_leva_sempre_a_mesma_consulta_e_os_valores_so_em_variables(self):
        for nome, texto in C.OPERACOES.items():
            for valor in HOSTIL + [0, -1, 10 ** 19, 3.5, True, None, [1, 2], {'a': 'b'}]:
                with self.subTest(operacao=nome, valor=repr(valor)[:30]):
                    variaveis = self.variaveis_de(texto, valor)
                    corpo = json.loads(K.corpo_json(texto, variaveis))
                    self.assertEqual(set(corpo), {'query', 'variables'})
                    self.assertEqual(corpo['query'], texto)
                    self.assertEqual(corpo['variables'], variaveis)

    def test_o_texto_enviado_nao_carrega_o_valor_na_consulta(self):
        for nome, texto in C.OPERACOES.items():
            with self.subTest(operacao=nome):
                variaveis = self.variaveis_de(texto, MARCADOR)
                corpo = json.loads(K.corpo_json(texto, variaveis))
                self.assertNotIn(MARCADOR, corpo['query'])
                self.assertEqual(corpo['query'], C.OPERACOES[nome])

    def test_as_constantes_nao_mudam_depois_de_usadas(self):
        antes = dict(C.OPERACOES)
        for texto in antes.values():
            K.corpo_json(texto, self.variaveis_de(texto, MARCADOR))
        self.assertEqual(C.OPERACOES, antes)
        self.assertEqual(C.OPERACOES['productOfferV2'], C.CONSULTA_PRODUTOS)

    def test_pedido_enviado_pelo_cliente_leva_a_consulta_da_constante_e_a_operacao_certa(self):
        with comum.isolado() as (api, _conf, _esperas):
            cli = K.Cliente(cred(), pausa=0.5)
            registros = []
            for nome, texto in C.OPERACOES.items():
                variaveis = self.variaveis_de(texto, MARCADOR)
                cli.pedir(texto, variaveis, registrar=registros.append)
            corpos = api.corpos()
        self.assertEqual(len(corpos), len(C.OPERACOES))
        for (nome, texto), corpo, reg in zip(C.OPERACOES.items(), corpos, registros):
            with self.subTest(operacao=nome):
                self.assertEqual(corpo['query'], texto)
                self.assertNotIn(MARCADOR, corpo['query'])
                self.assertEqual(reg['operacao'], nome)
        for p in api.pedidos:
            self.assertEqual(p.full_url, comum.URL_FIXA)


# ---------- (3) sem interpolação de dado externo ----------
class TestConsultaComCampos(unittest.TestCase):
    """A sonda de campos escolhe QUAIS campos pede, mas só entre os nomes escritos em CAMPOS_PRODUTO e INFO_CAMPOS."""

    def test_monta_so_com_os_campos_pedidos(self):
        texto = C.consulta_com_campos(('itemId', 'productLink'))
        self.assertEqual(corpo_nos(texto), ['itemId', 'productLink'])
        self.assertNotIn('pageInfo', texto)
        self.assertEqual(re.findall(r'\$(\w+): ', texto), ['keyword', 'sortType', 'page', 'limit'])
        self.assertEqual(K.operacao_de(texto), 'productOfferV2')

    def test_com_pageinfo(self):
        self.assertIn('pageInfo { page limit hasNextPage }',
                      C.consulta_com_campos(('itemId',), pagina=('page', 'limit', 'hasNextPage')))
        self.assertIn('pageInfo { limit }', C.consulta_com_campos(('itemId',), pagina=('limit',)))

    def test_recusa_nome_fora_das_listas(self):
        for campos, pagina in ((('x',), ()), (('itemId', 'itemId2'), ()), (('itemId } mutation { x',), ()), ((), ()),
                               (('itemId',), ('scrollId',)), (('itemId',), ('page } x',)), ([1], ()), ('itemId', ()),
                               (('itemId',), 'page')):
            with self.subTest(campos=campos, pagina=pagina), self.assertRaises(ValueError):
                C.consulta_com_campos(campos, pagina=pagina)

    def test_os_campos_de_producao_batem_com_o_coletar_shopee(self):
        self.assertEqual(sorted(C.CAMPOS_PRODUCAO), sorted(corpo_nos(CS.CONSULTA)))
        self.assertLessEqual(set(C.CAMPOS_PRODUCAO), set(C.CAMPOS_PRODUTO))
        self.assertEqual(len(C.CAMPOS_EXTRAS), len(C.CAMPOS_PRODUTO) - len(C.CAMPOS_PRODUCAO))
        self.assertFalse(set(C.CAMPOS_EXTRAS) & set(C.CAMPOS_PRODUCAO))


class TestSemInterpolacao(unittest.TestCase):
    def setUp(self):
        self.arvore = ast.parse(FONTE)

    def funcoes(self):
        return [n for n in ast.walk(self.arvore) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]

    def test_montar_e_nos_so_sao_chamadas_no_nivel_do_modulo(self):
        dentro = set()
        for f in self.funcoes():
            for c in ast.walk(f):
                if isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id in ('_montar', '_nos'):
                    dentro.add((f.name, c.func.id))
        # a única exceção: a sonda de campos escolhe entre nomes escritos aqui (TestConsultaComCampos)
        self.assertEqual(dentro, {('consulta_com_campos', '_montar'), ('consulta_com_campos', '_nos')},
                         'chamada dentro de função')
        chamadas = [c for c in ast.walk(self.arvore) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                    and c.func.id == '_montar']
        self.assertGreaterEqual(len(chamadas), 8)

    def test_so_o_montar_e_o_nos_usam_f_string_ou_formatacao(self):
        com_fstring = {f.name for f in self.funcoes() if any(isinstance(n, ast.JoinedStr) for n in ast.walk(f))}
        self.assertEqual(com_fstring, {'_montar', '_nos'})
        nivel_modulo = [n for n in self.arvore.body if not isinstance(n, (ast.FunctionDef, ast.ClassDef))]
        for n in nivel_modulo:
            self.assertFalse(any(isinstance(x, ast.JoinedStr) for x in ast.walk(n)), 'f-string no módulo')
        self.assertNotIn('.format(', FONTE)
        self.assertIsNone(re.search(r"'\s*%\s*[\(\w]", FONTE), '% como formatação de texto')

    def test_nenhum_leitor_nem_o_variaveis_link_toca_na_consulta(self):
        nomes_consulta = {'CONSULTA_PRODUTOS', 'CONSULTA_LOJAS', 'CONSULTA_CAMPANHAS', 'GERAR_LINK',
                          'RELATORIO_CONVERSOES', 'RELATORIO_VALIDADO', 'LISTAR_FEEDS', 'DADOS_FEED', 'INTROSPECCAO',
                          'OPERACOES'}
        for f in self.funcoes():
            if f.name in ('_montar', '_nos'):
                continue
            usados = {n.id for n in ast.walk(f) if isinstance(n, ast.Name)}
            with self.subTest(funcao=f.name):
                self.assertEqual(usados & nomes_consulta, {'OPERACOES'} & usados)
                if usados & nomes_consulta:
                    self.assertEqual(f.name, 'ler_operacao')   # só confere se a operação é conhecida

    def test_o_modulo_nao_le_ambiente_arquivo_nem_rede(self):
        for proibido in ('os.environ', 'getenv', 'open(', 'urlopen', 'input('):
            self.assertNotIn(proibido, FONTE, proibido)

    def test_montar_recusa_nome_tipo_ou_selecao_de_fora(self):
        ok = ('query', 'Nome', 'productOfferV2', ('keyword',), 'itemId')
        self.assertTrue(C._montar(*ok).startswith('query Nome($keyword: String)'))
        ruins = [
            ('subscription', 'Nome', 'productOfferV2', ('keyword',), 'itemId'),
            ('query', 'No me', 'productOfferV2', ('keyword',), 'itemId'),
            ('query', 'Nome', 'op) { x', ('keyword',), 'itemId'),
            ('query', 'Nome', 'op"', ('keyword',), 'itemId'),
            ('query', 'Nome', '1op', ('keyword',), 'itemId'),
            ('query', 'Nome', 'op', ('keyword) { y',), 'itemId'),
            ('query', 'Nome', 'op', ('$keyword',), 'itemId'),
            ('query', 'Nome', 'op', ('desconhecido',), 'itemId'),     # sem tipo na tabela
            ('query', 'Nome', 'op', ('keyword', 'keyword'), 'itemId'),
            ('query', 'Nome', 'op', ('keyword',), 'itemId "x"'),
            ('query', 'Nome', 'op', ('keyword',), 'itemId(a: 1)'),
            ('query', 'Nome', 'op', ('keyword',), 'a { b'),
            ('query', 'Nome', 'op', ('keyword',), 'a } {'.replace('} {', '}}')),
            ('query', 'Nome', 'op', ('keyword',), 'a ...F'),
            ('query', 'Nome', 'op', ('keyword',), ''),
            ('query', 'Nome', 'op', ('keyword',), None),
            ('query', 'Nome', 'op', ('keyword',), 'a\x00b'),
            ('query', None, 'op', ('keyword',), 'a'),
            ('query', 'Nome', 'op', (1,), 'a'),
        ]
        for args in ruins:
            with self.subTest(args=args):
                with self.assertRaises(ValueError):
                    C._montar(*args)
        for tipo_ruim in ('String) { x', 'Int!!!', '', '[Int', 'Int"', 'Int Int'):
            with self.subTest(tipo=tipo_ruim):
                with self.assertRaises(ValueError):
                    C._montar('query', 'N', 'op', ('keyword',), 'a', tipos={'keyword': tipo_ruim})


# ---------- generateShortLink: variáveis ----------
class TestVariaveisLink(unittest.TestCase):
    URL = 'https://shopee.com.br/product/777/1'

    def test_monta_o_input_com_ate_cinco_subids(self):
        for n in range(1, 6):
            subs = [f's{i}' for i in range(n)]
            v = C.variaveis_link(self.URL, subs)
            self.assertEqual(v, {'input': {'originUrl': self.URL, 'subIds': subs}})
            self.assertIsNot(v['input']['subIds'], subs)
        self.assertEqual(C.variaveis_link(self.URL, ('a', 'b'))['input']['subIds'], ['a', 'b'])

    def test_recusa_subids_fora_do_limite_ou_do_tipo(self):
        for ruim in ([], ['a'] * 6, [1], [None], [''], ['a', ''], 'abc', None, {'a': 1}, [b'a'], [['a']]):
            with self.subTest(subids=ruim):
                with self.assertRaises(ValueError):
                    C.variaveis_link(self.URL, ruim)

    def test_recusa_origin_url_que_nao_e_da_loja(self):
        for ruim in ('http://shopee.com.br/product/1/2', 'https://shopee.com.br', 'https://s.shopee.com.br/AbC123',
                     'https://shopee.com.br.evil.com/x', 'https://shopee.com.br@evil.com/x', 'https://evil.com/',
                     'https://shopee.com.br/a b', 'https://shopee.com.br/a\nb', 'https://shopee.com.br/ç',
                     'https://shopee.com.br/' + 'a' * 300, '', None, 5, b'https://shopee.com.br/x'):
            with self.subTest(url=repr(ruim)[:40]):
                with self.assertRaises(ValueError):
                    C.variaveis_link(ruim, ['a'])

    def test_o_endereco_e_os_subids_vao_so_em_variables(self):
        v = C.variaveis_link(self.URL, ['fem', 'vestidos', MARCADOR])
        corpo = json.loads(K.corpo_json(C.GERAR_LINK, v))
        self.assertEqual(corpo['query'], C.GERAR_LINK)
        self.assertNotIn(MARCADOR, corpo['query'])
        self.assertNotIn('shopee.com.br', corpo['query'])
        self.assertEqual(corpo['variables'], v)


# ---------- (4) leitores ----------
PADRAO = object()   # "use o valor padrão" (None é um valor a testar)


def dados(nos=PADRAO, info=PADRAO, operacao='productOfferV2', **extra):
    corpo = {'nodes': [no()] if nos is PADRAO else nos}
    corpo['pageInfo'] = {'page': 2, 'limit': 50, 'hasNextPage': True} if info is PADRAO else info
    corpo.update(extra)
    return {operacao: corpo}


def sem(d, *caminho):
    """Cópia de `d` sem a chave do caminho."""
    d = json.loads(json.dumps(d))
    alvo = d
    for c in caminho[:-1]:
        alvo = alvo[c]
    del alvo[caminho[-1]]
    return d


def com(d, valor, *caminho):
    d = json.loads(json.dumps(d))
    alvo = d
    for c in caminho[:-1]:
        alvo = alvo[c]
    alvo[caminho[-1]] = valor
    return d


MOTIVOS = {C.M_DADOS, C.M_OPERACAO, C.M_NOS, C.M_NO, C.M_NOS_DEMAIS, C.M_INFO, C.M_PAGE, C.M_LIMIT, C.M_PROXIMA,
           C.M_SCROLL}


class Leitor:
    """Auxiliar: o leitor recusa com FormatoInvalido, motivo fixo e sem ecoar o valor."""

    def recusa(self, leitor, entrada, motivo=None, **kw):
        with self.assertRaises(C.FormatoInvalido) as ctx:
            leitor(entrada, **kw)
        e = ctx.exception
        self.assertIsInstance(e, CS.RespostaInvalida)
        self.assertIn(e.motivo, MOTIVOS)
        if motivo:
            self.assertEqual(e.motivo, motivo)
        self.assertEqual(str(e), e.motivo)
        self.assertEqual(e.args, (e.motivo,))
        self.assertNotIn(MARCADOR, repr(e) + str(e) + repr(e.args))
        self.assertIsNone(e.__cause__)
        self.assertIsNone(e.__context__)
        return e


class TestLerPagina(Leitor, unittest.TestCase):
    def ler(self, d, op='productOfferV2', **kw):
        return C.ler_pagina(d, op, **kw)

    def test_resposta_valida(self):
        nos, info = self.ler(dados([no(1), no(2)]))
        self.assertEqual([n['itemId'] for n in nos], [1, 2])
        self.assertEqual(info, {'page': 2, 'limit': 50, 'tem_proxima': True})

    def test_resposta_do_cliente_com_o_formato_da_api(self):
        with comum.isolado(ApiFalsa(resposta([no(7)], tem_proxima=False, pagina=3))) as (api, _c, _e):
            d = K.Cliente(cred(), pausa=0.5).pedir(C.CONSULTA_PRODUTOS, {'keyword': 'vestido'}, registrar=lambda r: None)
        nos, info = self.ler(d)
        self.assertEqual(nos[0]['itemId'], 7)
        self.assertEqual(info, {'page': 3, 'limit': 20, 'tem_proxima': False})

    def test_lista_vazia_e_campos_extras_sao_aceitos(self):
        nos, info = self.ler(dados([], {'page': 1, 'limit': 20, 'hasNextPage': False, 'extra': MARCADOR}, extra=1))
        self.assertEqual((nos, info['tem_proxima']), ([], False))

    def test_zero_e_o_maior_numero_sao_aceitos(self):
        _, info = self.ler(dados(info={'page': 0, 'limit': C.MAX_NUMERO, 'hasNextPage': False}))
        self.assertEqual((info['page'], info['limit']), (0, C.MAX_NUMERO))

    def test_outras_operacoes_paginadas(self):
        for op in ('shopOfferV2', 'shopeeOfferV2'):
            nos, info = self.ler(dados([{'shopId': 1}], operacao=op), op)
            self.assertEqual(len(nos), 1)

    def test_operacao_desconhecida_e_erro_de_programacao(self):
        for ruim in ('productOfferV3', '', None, 'x" { y'):
            with self.assertRaises(ValueError):
                self.ler(dados(), ruim)

    def test_dados_que_nao_e_objeto(self):
        for ruim in (None, [], 'texto', 3, True, [dados()], MARCADOR):
            with self.subTest(dados=repr(ruim)[:20]):
                self.recusa(self.ler, ruim, C.M_DADOS)

    def test_operacao_ausente_ou_que_nao_e_objeto(self):
        self.recusa(self.ler, {}, C.M_OPERACAO)
        self.recusa(self.ler, {'shopOfferV2': dados()['productOfferV2']}, C.M_OPERACAO)   # outra operação não serve
        self.recusa(self.ler, {'productOfferV2': {}}, C.M_NOS)   # objeto vazio: sem nodes
        self.recusa(self.ler, {'outra': dados()['productOfferV2']}, C.M_OPERACAO)
        for ruim in (None, [], 'texto', 3, False, [dados()['productOfferV2']], MARCADOR):
            with self.subTest(op=repr(ruim)[:20]):
                self.recusa(self.ler, {'productOfferV2': ruim}, C.M_OPERACAO)

    def test_nodes_que_nao_e_lista(self):
        self.recusa(self.ler, sem(dados(), 'productOfferV2', 'nodes'), C.M_NOS)
        for ruim in (None, {}, {'itemId': 1}, 'texto', MARCADOR, 3, True, 0):
            with self.subTest(nodes=repr(ruim)[:20]):
                self.recusa(self.ler, com(dados(), ruim, 'productOfferV2', 'nodes'), C.M_NOS)

    def test_nodes_com_item_que_nao_e_objeto(self):
        for ruim in (None, 1, 'texto', MARCADOR, [no()], True, 1.5):
            with self.subTest(item=repr(ruim)[:20]):
                self.recusa(self.ler, dados([no(1), ruim]), C.M_NO)

    def test_nodes_acima_do_maximo(self):
        self.recusa(self.ler, dados([no(i) for i in range(3)]), C.M_NOS_DEMAIS, maximo=2)
        self.assertEqual(len(self.ler(dados([no(i) for i in range(2)]), maximo=2)[0]), 2)
        self.recusa(self.ler, dados([{}] * (C.MAX_NOS + 1)), C.M_NOS_DEMAIS)

    def test_pageinfo_ausente_ou_com_tipo_errado(self):
        self.recusa(self.ler, sem(dados(), 'productOfferV2', 'pageInfo'), C.M_INFO)
        for ruim in (None, [], 'texto', MARCADOR, 3, True, [{'page': 1, 'limit': 1, 'hasNextPage': True}]):
            with self.subTest(info=repr(ruim)[:20]):
                self.recusa(self.ler, dados(info=ruim), C.M_INFO)

    def test_page_e_limit_so_aceitam_inteiro(self):
        for campo, motivo in (('page', C.M_PAGE), ('limit', C.M_LIMIT)):
            base = {'page': 1, 'limit': 20, 'hasNextPage': False}
            for ruim in ('1', '20', MARCADOR, 1.0, 2.5, True, False, [1], {'n': 1}, -1, C.MAX_NUMERO + 1,
                         10 ** 30, float('inf'), float('nan')):
                with self.subTest(campo=campo, valor=repr(ruim)[:20]):
                    self.recusa(self.ler, dados(info=dict(base, **{campo: ruim})), motivo)
        # limit é obrigatório no schema (Int!)
        self.recusa(self.ler, dados(info={'page': 1, 'hasNextPage': False}), C.M_LIMIT)
        self.recusa(self.ler, dados(info={'page': 1, 'limit': None, 'hasNextPage': False}), C.M_LIMIT)

    def test_page_pode_faltar_ou_vir_nulo(self):
        # o schema medido no R1 diz page: Int (sem !); o motor só usa o hasNextPage
        for info in ({'limit': 20, 'hasNextPage': True}, {'page': None, 'limit': 20, 'hasNextPage': True}):
            with self.subTest(info=info):
                _, lido = self.ler(dados(info=info))
                self.assertEqual(lido, {'page': None, 'limit': 20, 'tem_proxima': True})

    def test_hasnextpage_so_aceita_bool(self):
        base = {'page': 1, 'limit': 20}
        self.recusa(self.ler, dados(info=base), C.M_PROXIMA)
        for ruim in (None, 'true', 'false', 'True', MARCADOR, 1, 0, 1.0, [], [True], {}, ''):
            with self.subTest(valor=repr(ruim)[:20]):
                self.recusa(self.ler, dados(info=dict(base, hasNextPage=ruim)), C.M_PROXIMA)
        for ok in (True, False):
            self.assertIs(self.ler(dados(info=dict(base, hasNextPage=ok)))[1]['tem_proxima'], ok)

    def test_a_ordem_das_conferencias_e_nodes_antes_do_pageinfo(self):
        d = dados([1], info=None)
        self.recusa(self.ler, d, C.M_NO)

    def test_o_valor_recusado_nunca_aparece_na_excecao(self):
        casos = [dados(nos=MARCADOR), dados([MARCADOR]), dados(info=MARCADOR),
                 dados(info={'page': MARCADOR, 'limit': 1, 'hasNextPage': True}),
                 dados(info={'page': 1, 'limit': MARCADOR, 'hasNextPage': True}),
                 dados(info={'page': 1, 'limit': 1, 'hasNextPage': MARCADOR}), {'productOfferV2': MARCADOR}, MARCADOR]
        for d in casos:
            with self.subTest(d=repr(d)[:40]):
                self.recusa(self.ler, d)


class TestLerNos(Leitor, unittest.TestCase):
    """O leitor das consultas sem `pageInfo` (produtos do garimpo e lojas): só os nós."""

    def ler(self, d, op='productOfferV2', **kw):
        return C.ler_nos(d, op, **kw)

    def test_resposta_sem_pageinfo(self):
        d = {'productOfferV2': {'nodes': [no(1), no(2)]}}
        self.assertEqual([n['itemId'] for n in self.ler(d)], [1, 2])
        self.assertEqual(self.ler({'productOfferV2': {'nodes': []}}), [])

    def test_o_pageinfo_se_vier_e_ignorado_inclusive_quando_estranho(self):
        for info in (PADRAO, None, 'texto', [], 3, {'page': 'x'}, {'hasNextPage': 'talvez'}):
            with self.subTest(info=repr(info)[:20]):
                self.assertEqual(len(self.ler(dados([no(1), no(2)], info=info))), 2)

    def test_outras_operacoes_sem_pageinfo(self):
        for op in ('shopOfferV2', 'shopeeOfferV2'):
            self.assertEqual(len(self.ler({op: {'nodes': [{'shopId': 1}]}}, op)), 1)

    def test_operacao_desconhecida_e_erro_de_programacao(self):
        for ruim in ('productOfferV3', '', None, 'x" { y'):
            with self.assertRaises(ValueError):
                self.ler(dados(), ruim)

    def test_formato_errado_tem_motivo_fixo(self):
        for ruim in (None, [], 'texto', MARCADOR):
            self.recusa(self.ler, ruim, C.M_DADOS)
        self.recusa(self.ler, {}, C.M_OPERACAO)
        self.recusa(self.ler, {'productOfferV2': MARCADOR}, C.M_OPERACAO)
        self.recusa(self.ler, {'productOfferV2': {}}, C.M_NOS)
        for ruim in (None, {}, 'texto', MARCADOR, 3, True):
            self.recusa(self.ler, {'productOfferV2': {'nodes': ruim}}, C.M_NOS)
        for ruim in (None, 1, 'texto', MARCADOR, [no()], True):
            self.recusa(self.ler, {'productOfferV2': {'nodes': [no(1), ruim]}}, C.M_NO)
        self.recusa(self.ler, {'productOfferV2': {'nodes': [no(i) for i in range(3)]}}, C.M_NOS_DEMAIS, maximo=2)
        self.assertEqual(len(self.ler({'productOfferV2': {'nodes': [no(i) for i in range(2)]}}, maximo=2)), 2)
        self.recusa(self.ler, {'productOfferV2': {'nodes': [{}] * (C.MAX_NOS + 1)}}, C.M_NOS_DEMAIS)

    def test_resposta_do_cliente_sem_pageinfo(self):
        with comum.isolado(ApiFalsa(resposta([no(7), no(8)]))) as (api, _c, _e):
            d = K.Cliente(cred(), pausa=0.5).pedir(C.CONSULTA_PRODUTOS, {'keyword': 'vestido'}, registrar=lambda r: None)
        self.assertEqual([n['itemId'] for n in self.ler(d)], [7, 8])


class TestLerRelatorio(Leitor, unittest.TestCase):
    def ler(self, d, op='conversionReport', **kw):
        return C.ler_relatorio(d, op, **kw)

    def relatorio(self, info, nos=PADRAO, op='conversionReport'):
        return dados([{'conversionId': 1}] if nos is PADRAO else nos, info, op)

    def test_resposta_valida_com_scrollid(self):
        nos, info = self.ler(self.relatorio({'limit': 500, 'hasNextPage': True, 'scrollId': 'abc123=='}))
        self.assertEqual(len(nos), 1)
        self.assertEqual(info, {'limit': 500, 'tem_proxima': True, 'scroll_id': 'abc123=='})

    def test_ultima_pagina_sem_scrollid_ou_com_null_ou_vazio(self):
        ausente = object()
        for scroll in (ausente, None, ''):
            pi = {'limit': 10, 'hasNextPage': False}
            if scroll is not ausente:
                pi['scrollId'] = scroll
            with self.subTest(scroll=repr(scroll)[:12]):
                self.assertEqual(self.ler(self.relatorio(pi))[1], {'limit': 10, 'tem_proxima': False, 'scroll_id': None})

    def test_limit_e_opcional_no_relatorio_validado(self):
        _, info = self.ler(self.relatorio({'hasNextPage': True, 'scrollId': 's'}, op='validatedReport'),
                           'validatedReport')
        self.assertEqual(info, {'limit': None, 'tem_proxima': True, 'scroll_id': 's'})
        _, info = self.ler(self.relatorio({'limit': None, 'hasNextPage': False}))
        self.assertIsNone(info['limit'])

    def test_hasnextpage_e_obrigatorio_e_bool(self):
        self.recusa(self.ler, self.relatorio({'limit': 1}), C.M_PROXIMA)
        for ruim in (None, 'true', 1, 0, [], {}):
            with self.subTest(valor=repr(ruim)):
                self.recusa(self.ler, self.relatorio({'limit': 1, 'hasNextPage': ruim}), C.M_PROXIMA)

    def test_limit_presente_tem_de_ser_inteiro(self):
        for ruim in ('1', MARCADOR, 1.5, True, [], -3, C.MAX_NUMERO + 1):
            with self.subTest(valor=repr(ruim)[:20]):
                self.recusa(self.ler, self.relatorio({'limit': ruim, 'hasNextPage': False}), C.M_LIMIT)

    def test_scrollid_presente_tem_de_ser_texto_curto_sem_controle(self):
        for ruim in (5, 1.5, True, [], {}, ['a'], 'x' * (C.MAX_SCROLL_ID + 1), 'a\nb', 'a\x00b', 'a\x7fb'):
            with self.subTest(valor=repr(ruim)[:20]):
                self.recusa(self.ler, self.relatorio({'limit': 1, 'hasNextPage': True, 'scrollId': ruim}), C.M_SCROLL)
        self.assertEqual(self.ler(self.relatorio({'hasNextPage': True, 'scrollId': 'x' * C.MAX_SCROLL_ID}))[1]
                         ['scroll_id'], 'x' * C.MAX_SCROLL_ID)

    def test_mesmas_recusas_de_nodes_e_pageinfo(self):
        self.recusa(self.ler, sem(self.relatorio({'hasNextPage': False}), 'conversionReport', 'nodes'), C.M_NOS)
        self.recusa(self.ler, self.relatorio({'hasNextPage': False}, nos='texto'), C.M_NOS)
        self.recusa(self.ler, self.relatorio({'hasNextPage': False}, nos=[None]), C.M_NO)
        self.recusa(self.ler, sem(self.relatorio({'hasNextPage': False}), 'conversionReport', 'pageInfo'), C.M_INFO)
        self.recusa(self.ler, self.relatorio([]), C.M_INFO)
        self.recusa(self.ler, {}, C.M_OPERACAO)
        self.recusa(self.ler, [], C.M_DADOS)
        with self.assertRaises(ValueError):
            self.ler(self.relatorio({'hasNextPage': False}), 'conversionReports')

    def test_o_scrollid_recusado_nao_aparece_na_excecao(self):
        self.recusa(self.ler, self.relatorio({'hasNextPage': True, 'scrollId': [MARCADOR]}), C.M_SCROLL)
        self.recusa(self.ler, self.relatorio({'hasNextPage': True, 'scrollId': MARCADOR + '\n'}), C.M_SCROLL)


class TestLerOperacao(Leitor, unittest.TestCase):
    def test_devolve_o_objeto_da_operacao(self):
        corpo = C.ler_operacao({'listItemFeeds': {'feeds': []}}, 'listItemFeeds')
        self.assertEqual(corpo, {'feeds': []})

    def test_recusa_formato_errado(self):
        for ruim in (None, [], 'x', {}, {'listItemFeeds': None}, {'listItemFeeds': []}, {'listItemFeeds': 'x'}):
            with self.subTest(d=repr(ruim)):
                self.recusa(lambda d: C.ler_operacao(d, 'listItemFeeds'), ruim)

    def test_formato_invalido_e_tratado_como_resposta_invalida_pelo_garimpo(self):
        self.assertTrue(issubclass(C.FormatoInvalido, CS.RespostaInvalida))
        self.assertTrue(issubclass(C.FormatoInvalido, CS.ErroColeta))


if __name__ == '__main__':
    unittest.main()
