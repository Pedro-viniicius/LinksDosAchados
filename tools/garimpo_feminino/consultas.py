"""Consultas GraphQL da Open API de afiliados da Shopee e leitores das respostas, para o garimpo feminino.

Plano: docs/produto/planos/garimpo-feminino-shopee.md, etapa 5 (CA7 e CA9).

FONTE DOS NOMES: o schema oficial fica no painel logado do dono e nenhum agente o leu. Os nomes de operações,
argumentos e campos vêm do brief (que cita terceiros: Apify `viralanalyzer`, MCP `shopee-br-affiliate-mcp`) e de
uma página não oficial de documentação (affiliateshopee.com.br/documentacao). Tudo é "a confirmar (R1)": o
`reconhecer` (introspecção ou sondas) mede o que existe e a etapa 8 ajusta este arquivo. Uma consulta com campo
ou argumento que a API não conhece volta como erro de validação (`ErroApi`), nunca como dado errado.

Regras deste arquivo:
- As consultas são CONSTANTES de módulo, montadas uma vez no import por `_montar` a partir de nomes escritos
  aqui (tabela `TIPOS` e tuplas de argumentos e de campos). Nada de fora entra na consulta: `_montar` só roda no
  nível do módulo (um teste confere pela árvore do código) e recusa nome fora de `[A-Za-z_][A-Za-z0-9_]*`. A única
  exceção é `consulta_com_campos`, da sonda de campos: escolhe quais pedir, só entre os nomes escritos aqui.
- Os valores (palavra-chave, ids, página, limite, subIds, datas, `scrollId`) vão SÓ em `variables`, no corpo
  que o `cliente.corpo_json` monta. A consulta não tem aspas, número nem valor embutido.
- O tipo GraphQL de cada variável mora na tabela `TIPOS`: trocar `Int64` por `Int` ou `String` (ou `Int` por
  `Int64` em `productCatId`) é mexer numa linha, e todas as consultas que usam o argumento acompanham.
- As variáveis opcionais que não valem na chamada ficam fora do dicionário `variables` (não mande `null`).
- Os leitores conferem o formato da resposta (`nodes` é lista de objetos; quando a consulta pede o `pageInfo`, ele é
  objeto com os tipos certos) e levantam `FormatoInvalido` (uma `CS.RespostaInvalida`) com um motivo fixo: nunca com texto nem valor
  vindo da API. O conteúdo de cada nó é conferido por quem grava (`banco._linha_produto`).
"""
import os
import re
import sys

PASTA = os.path.dirname(os.path.abspath(__file__))
if PASTA not in sys.path:
    sys.path.insert(0, PASTA)

import cliente as K  # noqa: E402

CS = K.CS

RE_IDENT = re.compile(r'[A-Za-z_][A-Za-z0-9_]{0,63}', re.A)
RE_TIPO = re.compile(r'(?:[A-Za-z_][A-Za-z0-9_]{0,63}|\[[A-Za-z_][A-Za-z0-9_]{0,63}!?\])!?', re.A)
RE_SELECAO = re.compile(r'[A-Za-z0-9_{}\s]+', re.A)

MAX_SUBIDS = 5                                # generateShortLink: até 5 subIds (a confirmar (R1))
PREFIXO_ORIGEM = 'https://shopee.com.br/'     # originUrl do link de teste: só a loja (plano, pontos para o seguranca)
MAX_NOS = 5000                                # sanidade: mais nós que isso numa página é resposta fora do padrão
MAX_NUMERO = 10 ** 9                          # page e limit de pageInfo
MAX_SCROLL_ID = 1024                          # caracteres do scrollId

# Tipo GraphQL de cada variável. É aqui que se troca o tipo dos ids quando o `reconhecer` medir (etapa 8).
TIPO_ID = 'Int64'        # medido no R1: shopId, itemId e matchId são Int64 no schema (#2); como número a API recusa
#                          (10010, #37) e como texto aceita (#38): o achados.json manda `int64: "texto"`
TIPO_CATEGORIA = 'Int'   # medido no R1: o argumento productCatId é Int, vai como número (#2, #27)
TIPOS = {
    'keyword': 'String',
    'shopId': TIPO_ID,
    'itemId': TIPO_ID,
    'productCatId': TIPO_CATEGORIA,   # medido no R1 (#2, #27)
    'listType': 'Int',                # medido no R1: o 4 devolve o mesmo que o productCatId (#33); o garimpo não o usa
    'matchId': TIPO_ID,               # medido no R1: Int64, como texto (#38)
    'sortType': 'Int',
    'page': 'Int',
    'limit': 'Int',
    'isAMSOffer': 'Boolean',
    'isKeySeller': 'Boolean',
    'shopType': '[Int!]',             # schema do R1: shopOfferV2 (1 Mall, 2 Star, 4 Star+)
    'sellerCommCoveRatio': 'String',  # a confirmar (R1): só a página não oficial cita
    'input': 'ShortLinkInput!',       # a confirmar (R1): nome do tipo de entrada do generateShortLink
    'purchaseTimeStart': 'Int64',     # schema do R1: segundos desde 1970
    'purchaseTimeEnd': 'Int64',       # schema do R1
    'orderStatus': 'DisplayOrderStatus',   # schema do R1
    'scrollId': 'String',
    'validationId': TIPO_ID + '!',    # a confirmar (R1): só a página não oficial cita; de onde vem o id não se sabe
    'datafeedId': 'String!',          # a confirmar (R1): o brief diz que pode ser composto: não normalizar
    'offset': 'Int',                  # schema do R1
    'feedMode': 'FeedMode',           # schema do R1: FULL ou DELTA
}


def _montar(tipo, nome, operacao, argumentos, selecao, tipos=TIPOS):
    """Texto da consulta: `<tipo> <nome>($a: T, ...) { <operacao>(a: $a, ...) { <selecao> } }`.

    Só pode ser chamada no nível do módulo, com nomes escritos neste arquivo. Os valores nunca passam por aqui.
    """
    if tipo not in ('query', 'mutation'):
        raise ValueError('tipo de operação inválido')
    for ident in (nome, operacao, *argumentos):
        if not isinstance(ident, str) or not RE_IDENT.fullmatch(ident):
            raise ValueError('nome fora do padrão')
    if len(set(argumentos)) != len(argumentos):
        raise ValueError('argumento repetido')
    if not isinstance(selecao, str) or not RE_SELECAO.fullmatch(selecao) or selecao.count('{') != selecao.count('}'):
        raise ValueError('seleção fora do padrão')
    for a in argumentos:
        if a not in tipos or not RE_TIPO.fullmatch(tipos[a]):
            raise ValueError('argumento sem tipo na tabela')
    cabecalho = f'{tipo} {nome}'
    chamada = operacao
    if argumentos:
        cabecalho += '(' + ', '.join(f'${a}: {tipos[a]}' for a in argumentos) + ')'
        chamada += '(' + ', '.join(f'{a}: ${a}' for a in argumentos) + ')'
    return f'{cabecalho} {{\n  {chamada} {{\n    {" ".join(selecao.split())}\n  }}\n}}'


# ---------- campos ----------
INFO_PAGINA = 'pageInfo { page limit hasNextPage }'
INFO_RELATORIO = 'pageInfo { limit hasNextPage scrollId }'   # a confirmar (R1): o validatedReport pode não ter `limit`

# ESTA é a lista de campos do productOfferV2 no garimpo: para tirar um campo depois da medição (etapa 8, parte B),
# basta tirá-lo daqui; a CONSULTA_PRODUTOS e a sonda de campos acompanham, e o motor e o banco não exigem nenhum dos
# campos além do itemId.
# Todos os campos do brief (seção 1, "Retorno do productOfferV2"); o `productCatIds` é [L1, L2, L3].
CAMPOS_PRODUTO = ('itemId', 'productName', 'productLink', 'offerLink', 'imageUrl', 'priceMin', 'priceMax',
                  'priceDiscountRate', 'sales', 'ratingStar', 'commissionRate', 'sellerCommissionRate',
                  'shopeeCommissionRate', 'commission', 'productCatIds', 'shopId', 'shopName', 'shopType',
                  'periodStartTime', 'periodEndTime')

# Os 9 campos que funcionam em produção (coletar_shopee.py, CONSULTA): a base da sonda de campos.
CAMPOS_PRODUCAO = ('itemId', 'shopId', 'productName', 'priceMin', 'priceDiscountRate', 'ratingStar', 'sales',
                   'imageUrl', 'offerLink')
CAMPOS_EXTRAS = tuple(c for c in CAMPOS_PRODUTO if c not in CAMPOS_PRODUCAO)
INFO_CAMPOS = ('page', 'limit', 'hasNextPage')

# a confirmar (R1): campos da loja, da campanha e dos relatórios vêm só da página não oficial de documentação
CAMPOS_LOJA = ('shopId', 'shopName', 'commissionRate', 'ratingStar', 'shopType', 'imageUrl', 'offerLink',
               'remainingBudget', 'sellerCommCoveRatio', 'periodStartTime', 'periodEndTime')
CAMPOS_CAMPANHA = ('commissionRate', 'imageUrl', 'offerLink', 'originalLink', 'offerName', 'offerType',
                   'categoryId', 'collectionId', 'periodStartTime', 'periodEndTime')
# `utmContent` leva os subIds do link (o separador entre eles é medido no R1); `orders.items` traz o produto
CAMPOS_CONVERSAO = ('purchaseTime clickTime conversionId totalCommission sellerCommission shopeeCommissionCapped '
                    'buyerType device utmContent orders { orderId orderStatus items { itemId itemName shopName '
                    'itemPrice qty itemTotalCommission attributionType } }')
CAMPOS_VALIDADO = ('conversionId netCommission totalCommission orders { orderId items { itemName '
                   'itemTotalCommission refundAmount } }')


def _nos(campos, info=''):
    campos = campos if isinstance(campos, str) else ' '.join(campos)
    return f'nodes {{ {campos} }} {info}'


# ---------- consultas (constantes) ----------
# Busca de produtos. Argumentos fora do `variables` são opcionais: o garimpo manda só os que a estratégia usa.
# SEM `pageInfo`: com ele a consulta completa foi recusada duas vezes no R1 (medicoes #3 e #47), e os mesmos campos sem
# ele passaram nas páginas 1 e 10 (#72 a #74). Quem pagina decide a parada pelos nós (`ler_nos`): página com menos
# itens que o `limit`, ou vazia, é a última. A causa exata da recusa não foi isolada (o `pageInfo` passou com 9 campos
# em `limit` 50, #71); a sonda do `reconhecer` guarda o texto com `pageInfo` (`fase_reconhecer.P_PRODUTOS_COM_PAGINA`).
CONSULTA_PRODUTOS = _montar(
    'query', 'ProdutosPorOferta', 'productOfferV2',
    ('keyword', 'shopId', 'itemId', 'productCatId', 'listType', 'matchId', 'sortType', 'page', 'limit',
     'isAMSOffer', 'isKeySeller'),
    _nos(CAMPOS_PRODUTO))

# Lojas com oferta (estratégia de lojas, etapa 15). Também SEM `pageInfo`: com ele foi recusada (medicoes #85) e a
# mesma consulta sem ele passou (#86). A sonda do `reconhecer` guarda o texto com `pageInfo`.
CONSULTA_LOJAS = _montar(
    'query', 'LojasPorOferta', 'shopOfferV2',
    ('keyword', 'shopId', 'shopType', 'isKeySeller', 'sortType', 'sellerCommCoveRatio', 'page', 'limit'),
    _nos(CAMPOS_LOJA))

# Campanhas (11.11, Black Friday, Natal). a confirmar (R1)
CONSULTA_CAMPANHAS = _montar(
    'query', 'CampanhasShopee', 'shopeeOfferV2',
    ('keyword', 'sortType', 'page', 'limit'),
    _nos(CAMPOS_CAMPANHA, INFO_PAGINA))

# Link de teste com subIds. Variáveis: {"input": {"originUrl": ..., "subIds": [...]}} (ver `variaveis_link`).
# a confirmar (R1): nome do tipo de entrada, campos e o formato aceito nos subIds
GERAR_LINK = _montar('mutation', 'GerarLink', 'generateShortLink', ('input',), 'shortLink')

# Relatórios de conversão: 1ª consulta sem `scrollId`; as seguintes com o `scrollId` da página anterior, usado
# em até 30 s e uma vez só (a 1ª consulta de cada relatório pede mais de 30 s de intervalo). a confirmar (R1)
RELATORIO_CONVERSOES = _montar(
    'query', 'RelatorioConversoes', 'conversionReport',
    ('purchaseTimeStart', 'purchaseTimeEnd', 'orderStatus', 'limit', 'scrollId'),
    _nos(CAMPOS_CONVERSAO, INFO_RELATORIO))
RELATORIO_VALIDADO = _montar(
    'query', 'RelatorioValidado', 'validatedReport',
    ('validationId', 'limit', 'scrollId'),
    _nos(CAMPOS_VALIDADO, INFO_RELATORIO))

# Datafeeds (FULL e DELTA), pelo schema do R1. Cada linha do feed vem como um texto só, em `rows.columns`.
LISTAR_FEEDS = _montar('query', 'ListarFeeds', 'listItemFeeds', ('feedMode',),
                       'feeds { datafeedId referenceId datafeedName description totalCount date feedMode }')
DADOS_FEED = _montar('query', 'DadosFeed', 'getItemFeedData', ('datafeedId', 'offset', 'limit'),
                     'rows { columns updateType } pageInfo { offset limit totalCount hasMore }')

# Introspecção padrão do GraphQL (`__schema`). A resposta pode passar dos 2 MB do `cliente`: nesse caso o
# `reconhecer` cai nas sondas fixas (plano, riscos).
INTROSPECCAO = '''query Introspeccao {
  __schema {
    queryType { name }
    mutationType { name }
    types { ...Tipo }
  }
}
fragment Tipo on __Type {
  kind
  name
  fields { name args { ...Entrada } type { ...Ref } }
  inputFields { ...Entrada }
  enumValues { name }
}
fragment Entrada on __InputValue { name type { ...Ref } }
fragment Ref on __Type {
  kind
  name
  ofType { kind name ofType { kind name ofType { kind name ofType { kind name } } } }
}'''

# operação (primeiro campo da consulta, o `operacao` de `requisicoes`) → texto da consulta
OPERACOES = {
    'productOfferV2': CONSULTA_PRODUTOS,
    'shopOfferV2': CONSULTA_LOJAS,
    'shopeeOfferV2': CONSULTA_CAMPANHAS,
    'generateShortLink': GERAR_LINK,
    'conversionReport': RELATORIO_CONVERSOES,
    'validatedReport': RELATORIO_VALIDADO,
    'listItemFeeds': LISTAR_FEEDS,
    'getItemFeedData': DADOS_FEED,
    '__schema': INTROSPECCAO,
}


# ---------- sonda de campos ----------
def consulta_com_campos(campos, *, pagina=()):
    """Consulta de produtos da sonda de campos: só os campos pedidos e, se vier, os do `pageInfo`.

    Os nomes têm de estar em CAMPOS_PRODUTO e INFO_CAMPOS (ValueError se não): escolhe entre o que está escrito aqui,
    e nada de fora entra no texto. Os valores continuam só em `variables`.
    """
    if not campos or not set(campos) <= set(CAMPOS_PRODUTO) or not set(pagina) <= set(INFO_CAMPOS):
        raise ValueError('campo fora da lista')
    info = 'pageInfo { ' + ' '.join(pagina) + ' }' if pagina else ''
    return _montar('query', 'SondaCampos', 'productOfferV2', ('keyword', 'sortType', 'page', 'limit'),
                   _nos(campos, info))


# ---------- variáveis do generateShortLink ----------
def variaveis_link(origin_url, sub_ids):
    """`variables` do GERAR_LINK: o `originUrl` (só https://shopee.com.br/...) e de 1 a 5 subIds em texto.

    O formato de cada subId (letras, dígitos, `-`, `_`) é medido no R1 e conferido por quem monta o lote.
    """
    if not isinstance(origin_url, str) or not origin_url.startswith(PREFIXO_ORIGEM) or len(origin_url) > CS.MAX_URL \
            or not origin_url.isascii() or any(c.isspace() or ord(c) < 32 for c in origin_url):
        raise ValueError('o originUrl tem de ser um endereço da loja, https://shopee.com.br/...')
    if not isinstance(sub_ids, (list, tuple)) or not 1 <= len(sub_ids) <= MAX_SUBIDS \
            or not all(isinstance(s, str) and s for s in sub_ids):
        raise ValueError('subIds: de 1 a 5 textos não vazios')
    return {'input': {'originUrl': origin_url, 'subIds': list(sub_ids)}}


# ---------- leitores ----------
class FormatoInvalido(CS.RespostaInvalida):
    """Resposta fora do formato esperado. `motivo` é uma das constantes `M_*`: texto fixo, nunca da API."""
    def __init__(self, motivo):
        super().__init__(motivo)
        self.motivo = motivo


M_DADOS = 'resposta sem o objeto data'
M_OPERACAO = 'operação ausente ou que não é objeto'
M_NOS = 'nodes ausente ou que não é lista'
M_NO = 'nó que não é objeto'
M_NOS_DEMAIS = 'nodes com itens demais'
M_INFO = 'pageInfo ausente ou que não é objeto'
M_PAGE = 'pageInfo.page ausente ou que não é inteiro'
M_LIMIT = 'pageInfo.limit ausente ou que não é inteiro'
M_PROXIMA = 'pageInfo.hasNextPage ausente ou que não é booleano'
M_SCROLL = 'pageInfo.scrollId que não é texto'


def ler_operacao(dados, operacao):
    """`data[operacao]` como dicionário. `dados` é o que o `Cliente.pedir` devolve (o "data" da resposta)."""
    if operacao not in OPERACOES:
        raise ValueError('operação desconhecida')
    if not isinstance(dados, dict):
        raise FormatoInvalido(M_DADOS)
    corpo = dados.get(operacao)
    if not isinstance(corpo, dict):
        raise FormatoInvalido(M_OPERACAO)
    return corpo


def _lista_de_nos(corpo, maximo):
    nos = corpo.get('nodes')
    if not isinstance(nos, list):
        raise FormatoInvalido(M_NOS)
    if len(nos) > maximo:
        raise FormatoInvalido(M_NOS_DEMAIS)
    if not all(isinstance(n, dict) for n in nos):
        raise FormatoInvalido(M_NO)
    return nos


def _info(corpo):
    info = corpo.get('pageInfo')
    if not isinstance(info, dict):
        raise FormatoInvalido(M_INFO)
    return info


def _numero(v, motivo):
    if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= MAX_NUMERO:
        raise FormatoInvalido(motivo)
    return v


def _tem_proxima(info):
    v = info.get('hasNextPage')
    if not isinstance(v, bool):
        raise FormatoInvalido(M_PROXIMA)
    return v


def ler_nos(dados, operacao, *, maximo=MAX_NOS):
    """Lista de nós de uma consulta sem `pageInfo` (a de produtos do garimpo e a de lojas). `nodes` ausente, que não
    é lista, com itens demais ou com item que não é objeto levanta FormatoInvalido. Se a resposta trouxer `pageInfo`,
    ele é ignorado: quem paginar decide pelo tamanho da lista."""
    return _lista_de_nos(ler_operacao(dados, operacao), maximo)


def ler_pagina(dados, operacao, *, maximo=MAX_NOS):
    """(nós, info) de uma consulta paginada por `page` que pede o `pageInfo` (campanhas e a sonda do reconhecer).

    `info` é `{'page': int | None, 'limit': int, 'tem_proxima': bool}`. O `limit` e o `hasNextPage` são obrigatórios
    e o `page` pode faltar ou vir nulo (é o que o schema diz), mas se vier tem de ser `int`; número só `int`, nunca
    texto nem `bool`, e `hasNextPage` só `bool`. Cada nó é um objeto. Qualquer outro formato levanta FormatoInvalido.
    """
    corpo = ler_operacao(dados, operacao)
    nos = _lista_de_nos(corpo, maximo)
    info = _info(corpo)
    pagina = info.get('page')
    return nos, {'page': None if pagina is None else _numero(pagina, M_PAGE), 'limit': _numero(info.get('limit'), M_LIMIT),
                 'tem_proxima': _tem_proxima(info)}


def ler_relatorio(dados, operacao, *, maximo=MAX_NOS):
    """(nós, info) de um relatório paginado por `scrollId` (conversionReport e validatedReport).

    `info` é `{'limit': int | None, 'tem_proxima': bool, 'scroll_id': str | None}`. O `hasNextPage` é
    obrigatório e `bool`; o `limit` e o `scrollId` podem faltar ou vir `null` (o `scrollId` vazio vira `None`),
    mas se vierem têm de ser `int` e texto (até 1024 caracteres, sem caractere de controle).
    """
    corpo = ler_operacao(dados, operacao)
    nos = _lista_de_nos(corpo, maximo)
    info = _info(corpo)
    limite = info.get('limit')
    scroll = info.get('scrollId')
    if scroll is not None and (not isinstance(scroll, str) or len(scroll) > MAX_SCROLL_ID
                               or any(ord(c) < 32 or 0x7f <= ord(c) <= 0x9f for c in scroll)):
        raise FormatoInvalido(M_SCROLL)
    return nos, {'limit': None if limite is None else _numero(limite, M_LIMIT), 'tem_proxima': _tem_proxima(info),
                 'scroll_id': scroll or None}
