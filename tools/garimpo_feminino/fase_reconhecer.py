"""Fase 1 do garimpo feminino (`garimpo.py reconhecer`): mede os limites reais da Open API de afiliados da Shopee.

Plano: docs/produto/planos/garimpo-feminino-shopee.md, etapa 6 (CA1, CA7 e CA9). O dono roda uma vez:
    read -rs S; ACHADINHOS_SHOPEE_SECRET="$S" ACHADINHOS_SHOPEE_APP_ID=<id> \\
        python3 tools/garimpo_feminino/garimpo.py reconhecer [--max-req N] [--refazer] [--refazer-taxa]; unset S

Ordem das sondas (cada uma grava uma linha em `medicoes`, com o nome entre parênteses):
 0. portão: a consulta de produtos conhecida como boa (`limit.20`, a sonda-base). Qualquer falha nela, inclusive com
    código da API (é assim que um Secret errado aparece), para a rodada com saída 1, sem medir mais nada. Numa
    retomada, com a base já medida, o pedido dela é reenviado antes do 1º pedido da rodada, sem gravar medição: o
    Secret é digitado de novo a cada rodada. Se nada falta medir, não há pedido nenhum;
 1. introspecção completa (`schema.introspeccao`), salva em docs/schema.json. Se falhar ou passar de 2 MB:
    raízes do schema (`schema.raizes`) e consultas `__type(name: ...)` menores (`schema.tipo.<Nome>`) para a raiz,
    o `productOfferV2`, o tipo de retorno, o nó, o pageInfo e os tipos dos argumentos (`schema.parcial`);
 2. a consulta de produtos inteira, COM `pageInfo` (`produtos.consulta`; se falhar, `produtos.categorias`): campos
    que vêm, tipos e a amostra (item, loja e categorias) que as sondas seguintes usam. Desde a etapa 8 o garimpo não
    pede o `pageInfo` (`consultas.CONSULTA_PRODUTOS`); a sonda guarda o texto antigo em `P_PRODUTOS_COM_PAGINA` e
    não é refeita (a medição da versão 2 já existe: recusada com código, que vale como medição);
 3. `limit` 50, 100 e 500 (`limit.<n>`; o 20 é o portão);
 4. profundidade de `page` em saltos e depois por bissecção (`pagina.<n>`, resumo em `pagina.teto`);
 5. sobreposição dos `sortType` 1 a 5 (`sort.<n>`, `sort.sobreposicao`);
 6. `listType` 0 a 4 com `matchId` da categoria × `productCatId` (`categoria.produto`, `listtype.<n>`,
    `listtype.comparacao`);
 7. `isAMSOffer` e `isKeySeller` (`filtro.ams`, `filtro.keyseller`, `filtro.comparacao`);
 8. Int64 como número e como texto (`int64.numero`, `int64.texto`);
 8a. quais campos do productOfferV2 derrubam a consulta com `null`: os 9 de produção + cada campo, `limit` 50
    (`campos.<campo>`), o `pageInfo` (`campos.pageInfo`; se recusado, `campos.pageInfo.<campo>`) e os aceitos juntos em
    2 páginas (`campos.combinado.<página>`, resumo em `campos.combinados`);
 8b. profundidade com `limit` 50, para separar teto de páginas de teto de itens (`pagina50.<n>`, `pagina50.teto`);
 9. rajada de taxa em degraus de 1, 2 e 4 req/s, até 120 requisições, parando no 1º 10030 ou HTTP 429 (`taxa`);
10. subIds com `-` e `_` no generateShortLink (`subid.simples`, `subid.hifen`, `subid.sublinhado`);
11. `listItemFeeds` (`feeds.full`, `feeds.delta`) e 1 página de `getItemFeedData` do FULL, só com nomes de coluna e
    contagens, sem nenhuma linha de dados (`feeds.dados`; recusado ou acima de 2 MB, `feeds.dados_menor`);
12. 1 página de `shopOfferV2` com `pageInfo` (`lojas`; recusada, sem o pageInfo em `lojas.sem_pagina`), `shopeeOfferV2` sem o pageInfo
    (`campanhas`) e `conversionReport` (`conversoes`).
No fim (e também quando a rodada para), gera docs/api_findings.md só com valores medidos ou "não medido"; cada
número aponta a linha de `medicoes` (`#id`).

Regras:
- Cada consulta é uma constante: as de `consultas.py` ou as variantes montadas aqui, no nível do módulo, pelo
  mesmo `consultas._montar`; a sonda de campos usa `C.consulta_com_campos`, que só aceita nomes da lista escrita lá.
  Os valores (inclusive nomes de tipo e o datafeedId que vêm da API) vão só em `variables`.
- Retomada: a sonda que já tem medição é pulada. O `--refazer` mede tudo de novo, menos a rajada de taxa, que só
  se repete com o `--refazer-taxa`, explícito (ela pode travar a cota). Teto, limite da API depois das esperas e
  Ctrl+C saem com 3/3/130; a próxima rodada continua de onde parou.
- Falha de transporte ou de autenticação (`K.erro_permanente` falso: rede, 5xx, 3xx, 401/403) não é medição: sobe
  sem gravar, a rodada sai com 1 e a próxima refaz a sonda. Vale também dentro da rajada. Erro com código ou HTTP
  4xx nas demais sondas continua sendo medição: é o que descobre parâmetro recusado.
- Medição já gravada com falha de transporte ou de autenticação conta como não medida (a retomada a refaz, e o
  api_findings.md não a cita), e leva junto o resumo montado em cima dela (`RESUMOS`).
- System Error (10000): o cliente tenta de novo; se persistir, a sonda fica gravada, a rodada segue e sai com 1. Na
  retomada ela conta como não medida. A exceção é a `taxa`: a rajada não tenta de novo e o 10000 que a encerra vale
  como medição, refeita só com `--refazer-taxa`.
- `VERSOES`: sonda cuja consulta mudou depois de medida. A medição sem a versão atual conta como não medida, sem
  precisar de `--refazer`, e a nova já nasce com a versão, então não se repete.
- Toda requisição é gravada em `requisicoes` e conta no orçamento (`max_total_requests` e `--max-req`).
- A mensagem de erro da API passa pelo `CS._texto` (até 300 caracteres), sem `Signature=`/`Credential=` nem
  sequência hexadecimal longa, e fica só no banco (medição da sonda): nunca no log nem no api_findings.md.
- Link gerado nas sondas de subId: só o link curto da Shopee (`eh_link_shopee`), conferido pelo
  `CS.destino` e `CS.dono_ok` (as duas metades do `conferir_dono`, porque aqui importa saber qual falhou); fica só
  na medição (nunca em `test_links` nem em export). Dono errado → a medição fica sem o link e a rodada sai com 1,
  mesmo numa retomada. Conferência sem resposta (rede, ou o link não redirecionou) não diz nada sobre o dono: o link
  fica só no banco, marcado como não conferido, a rodada sai com 1 e a próxima refaz a sonda.
"""
import contextlib
import json
import os
import re
import sys
import tempfile
import time

PASTA = os.path.dirname(os.path.abspath(__file__))
if PASTA not in sys.path:
    sys.path.insert(0, PASTA)

import banco  # noqa: E402
import cliente as K  # noqa: E402
import consultas as C  # noqa: E402

CS = K.CS

USA_API = True

SONDA_BASE = 'limit.20'               # o portão da rodada: a 1ª consulta de produtos, conhecida como boa
SONDA_TAXA = 'taxa'
TERMO = 'vestido'                     # palavra-chave das sondas de produto
LIMITE_SONDA = 20                     # limit das sondas que não medem o limit
LIMITES = (20, 50, 100, 500)
PAGINAS = (1, 2, 5, 10, 20, 50, 100, 200, 500, 1000)   # saltos de page
PASSOS_BISSECAO = 6                   # depois dos saltos, até 6 páginas entre a última útil e a primeira inútil
PAGINAS_50 = (20, 39, 40, 41, 60, 99)  # com limit 50: 2.000 itens caem na página 40 (o teto é de páginas ou de itens?)
LIMITE_MAXIMO = 50                    # medido no R1 (11001 acima disso)
PAGINAS_COMBINADO = (1, 10)           # páginas em que os campos aceitos são confirmados juntos
SORT_TYPES = (1, 2, 3, 4, 5)
LIST_TYPES = (0, 1, 2, 3, 4)
DEGRAUS = ((1, 40), (2, 40), (4, 40))  # (req/s, requisições): até 120, P4 do plano
SUBIDS = (('simples', ('fem', 'sonda')), ('hifen', ('fem', 'sonda-hifen')), ('sublinhado', ('fem', 'sonda_sub')))
LIMITE_FEED, LIMITE_FEED_MENOR = 500, 100
JANELA_CONVERSOES = 30 * 24 * 3600    # segundos (últimos 30 dias)
MAX_TIPOS = 12                        # consultas __type na queda da introspecção
MAX_MENSAGEM = 300
MAX_NOMES = 300                       # nomes de campo ou coluna guardados por medição
MAX_IDS = 500
MAX_FEEDS = 20                        # feeds guardados por medição (nome, descrição, data e total)
SEPARADORES_FEED = ('\t', '|', ';', ',')
ESCALARES = frozenset({'Int', 'Float', 'String', 'Boolean', 'ID'})
RE_IDENT = C.RE_IDENT
RE_TIPO_TEXTO = re.compile(r'[A-Za-z0-9_\[\]!?]{1,80}', re.A)
RE_SENSIVEL = re.compile(r'(?i)\b(?:signature|credential|authorization|secret|timestamp)\b\s*[=:]\s*[^\s,;]*'
                         r'|[0-9a-fA-F]{32,}')
ARQ_SCHEMA = os.path.join('docs', 'schema.json')
ARQ_FINDINGS = os.path.join('docs', 'api_findings.md')
ARQ_INTERPRETACAO = 'docs/api_interpretacao.md'
# (prefixo da sonda, resumo que é montado em cima dela): sem a sonda, o resumo também não vale.
RESUMOS = (('pagina.', 'pagina.teto'), ('sort.', 'sort.sobreposicao'), ('sort.1', 'filtro.comparacao'),
           ('categoria.', 'listtype.comparacao'), ('listtype.', 'listtype.comparacao'),
           ('filtro.', 'filtro.comparacao'), ('schema.raizes', 'schema.parcial'), ('schema.tipo.', 'schema.parcial'),
           ('campos.', 'campos.combinados'), ('pagina50.', 'pagina50.teto'))
# Versão atual da consulta de cada sonda que mudou depois do R1 (corrigida pelo schema, ou refeita de propósito).
VERSOES = {'produtos.consulta': 2, 'lojas': 2, 'campanhas': 2, 'conversoes': 2}

# ---------- variantes das consultas (constantes, montadas no import pelo mesmo _montar) ----------
# Cada sonda manda só os argumentos e os campos que mede: um argumento ou campo desconhecido derruba a consulta
# inteira (erro de validação), e assim derruba só a sonda dele.
_TIPOS_INTROSPECCAO = dict(C.TIPOS, name='String!')
_REF = 'kind name ofType { kind name ofType { kind name ofType { kind name } } }'
SELECAO_TIPO = ('kind name fields { name args { name type { ' + _REF + ' } } type { ' + _REF + ' } } '
                'inputFields { name type { ' + _REF + ' } } enumValues { name }')
RAIZES = C._montar('query', 'RaizesDoSchema', '__schema', (), 'queryType { name } mutationType { name }')
TIPO_POR_NOME = C._montar('query', 'TipoPorNome', '__type', ('name',), SELECAO_TIPO, tipos=_TIPOS_INTROSPECCAO)
P_BASE = C._montar('query', 'SondaBase', 'productOfferV2', ('keyword', 'sortType', 'page', 'limit'),
                   'nodes { itemId shopId }')
P_CATEGORIAS = C._montar('query', 'SondaCategorias', 'productOfferV2', ('keyword', 'sortType', 'page', 'limit'),
                         'nodes { itemId shopId productCatIds }')
P_CATEGORIA = C._montar('query', 'SondaCategoria', 'productOfferV2', ('productCatId', 'page', 'limit'),
                        'nodes { itemId shopId }')
P_LISTTYPE = C._montar('query', 'SondaListType', 'productOfferV2', ('listType', 'matchId', 'page', 'limit'),
                       'nodes { itemId shopId }')
P_AMS = C._montar('query', 'SondaAms', 'productOfferV2', ('keyword', 'sortType', 'isAMSOffer', 'page', 'limit'),
                  'nodes { itemId shopId }')
P_KEYSELLER = C._montar('query', 'SondaKeySeller', 'productOfferV2',
                        ('keyword', 'sortType', 'isKeySeller', 'page', 'limit'), 'nodes { itemId shopId }')
P_ITEM = C._montar('query', 'SondaItem', 'productOfferV2', ('shopId', 'itemId', 'page', 'limit'),
                   'nodes { itemId shopId }')
# Com pageInfo, como eram as consultas do garimpo antes da etapa 8 (hoje `consultas.CONSULTA_PRODUTOS` e
# `CONSULTA_LOJAS` não o pedem). Existem só para as sondas `produtos.consulta` e `lojas` continuarem medindo a consulta
# recusada no R1 (#3, #47 e #85), com o mesmo texto: se o texto mudasse, a medição existente deixaria de valer.
P_PRODUTOS_COM_PAGINA = C._montar(
    'query', 'ProdutosPorOferta', 'productOfferV2',
    ('keyword', 'shopId', 'itemId', 'productCatId', 'listType', 'matchId', 'sortType', 'page', 'limit',
     'isAMSOffer', 'isKeySeller'),
    C._nos(C.CAMPOS_PRODUTO, C.INFO_PAGINA))
P_LOJAS_COM_PAGINA = C._montar(
    'query', 'LojasPorOferta', 'shopOfferV2',
    ('keyword', 'shopId', 'shopType', 'isKeySeller', 'sortType', 'sellerCommCoveRatio', 'page', 'limit'),
    C._nos(C.CAMPOS_LOJA, C.INFO_PAGINA))
# Sem pageInfo: as duas consultas recusadas com "got null for non-null" no R1 (#3 e #45) são as únicas que o pediam.
P_LOJAS_SEM_PAGINA = C._montar('query', 'SondaLojas', 'shopOfferV2', ('keyword', 'page', 'limit'),
                               'nodes { ' + ' '.join(C.CAMPOS_LOJA) + ' }')
P_CAMPANHAS = C._montar('query', 'SondaCampanhas', 'shopeeOfferV2', ('page', 'limit'),
                        'nodes { ' + ' '.join(C.CAMPOS_CAMPANHA) + ' }')
CONSULTAS_DA_FASE = (RAIZES, TIPO_POR_NOME, P_BASE, P_CATEGORIAS, P_CATEGORIA, P_LISTTYPE, P_AMS, P_KEYSELLER,
                     P_ITEM, P_PRODUTOS_COM_PAGINA, P_LOJAS_COM_PAGINA, P_LOJAS_SEM_PAGINA, P_CAMPANHAS)


class _PrimeiroLimite(Exception):
    """Sinal interno da rajada: a API respondeu 10030 (ou HTTP 429). Sobe do `registrar`, antes das esperas."""


class _SistemaNaRajada(Exception):
    """Sinal interno da rajada: System Error (10000). Sobe do `registrar`, antes das novas tentativas do cliente."""
    def __init__(self, http):
        super().__init__()
        self.http = http


# ---------- funções puras ----------
def _eh_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _id(v):
    """Int64 da API (número ou texto só de dígitos) → texto canônico; o resto → None."""
    if _eh_int(v):
        n = v
    elif isinstance(v, str) and re.fullmatch(r'\d{1,19}', v, re.A):
        n = int(v)
    else:
        return None
    return str(n) if 0 < n <= banco.MAX_ID else None


def _nome(v):
    """Nome de campo, tipo ou coluna vindo da API: só identificador GraphQL; o resto → None."""
    return v if isinstance(v, str) and RE_IDENT.fullmatch(v) else None


def _nomes(valores):
    """Nomes válidos, sem repetição e em ordem, até MAX_NOMES, e quantos foram recusados."""
    vistos, recusados = [], 0
    for v in valores:
        n = _nome(v)
        if n is None:
            recusados += 1
        elif n not in vistos and len(vistos) < MAX_NOMES:
            vistos.append(n)
    return sorted(vistos), recusados


def _tipo_json(v):
    if v is None:
        return 'nulo'
    if isinstance(v, bool):
        return 'booleano'
    if isinstance(v, (int, float)):
        return 'numero'
    if isinstance(v, str):
        return 'texto'
    return 'lista' if isinstance(v, list) else 'objeto'


def mensagem_de_erro(resposta):
    """Mensagem do 1º erro da resposta, saneada: `CS._texto`, sem assinatura, credencial nem hexadecimal longo,
    até MAX_MENSAGEM caracteres. None quando não há mensagem."""
    erros = resposta.get('errors') if isinstance(resposta, dict) else None
    if not isinstance(erros, list) or not erros or not isinstance(erros[0], dict):
        return None
    msg = erros[0].get('message')
    ext = erros[0].get('extensions')
    if not isinstance(msg, str) and isinstance(ext, dict):
        msg = ext.get('message')
    if not isinstance(msg, str):
        return None
    texto = banco.sem_surrogates(CS._texto(RE_SENSIVEL.sub('[removido]', CS._texto(msg, 4000)), MAX_MENSAGEM))
    return texto or None


def _tipo_texto(ref, profundidade=0):
    """Referência de tipo da introspecção → texto como `[Int64!]!`. Nome fora do padrão vira `?`."""
    if not isinstance(ref, dict) or profundidade > 8:
        return '?'
    kind = ref.get('kind')
    if kind == 'NON_NULL':
        return _tipo_texto(ref.get('ofType'), profundidade + 1) + '!'
    if kind == 'LIST':
        return '[' + _tipo_texto(ref.get('ofType'), profundidade + 1) + ']'
    return _nome(ref.get('name')) or '?'


def _nome_base(ref, profundidade=0):
    """Nome do tipo nomeado dentro de NON_NULL/LIST; None se não houver."""
    if not isinstance(ref, dict) or profundidade > 8:
        return None
    if ref.get('kind') in ('NON_NULL', 'LIST'):
        return _nome_base(ref.get('ofType'), profundidade + 1)
    return _nome(ref.get('name'))


def _campos(tipo):
    """{nome: campo} dos `fields` de um tipo da introspecção (só nomes válidos)."""
    campos = tipo.get('fields') if isinstance(tipo, dict) else None
    if not isinstance(campos, list):
        return {}
    return {f['name']: f for f in campos[:5000] if isinstance(f, dict) and _nome(f.get('name'))}


def _argumentos(campo):
    args = campo.get('args') if isinstance(campo, dict) else None
    if not isinstance(args, list):
        return {}
    return {a['name']: a for a in args[:500] if isinstance(a, dict) and _nome(a.get('name'))}


def resumir_schema(por_nome, raiz, mutacao):
    """Resumo medido do schema: operações do garimpo que existem e o `productOfferV2` (argumentos com tipo,
    campos do nó e do pageInfo) e os argumentos do `generateShortLink`. Só nomes válidos."""
    consulta, mut = _campos(por_nome.get(raiz)), _campos(por_nome.get(mutacao))
    resumo = {'raiz': raiz, 'mutacao': mutacao,
              'operacoes': ({op: op in consulta or op in mut for op in sorted(C.OPERACOES) if op != '__schema'}
                            if consulta else None)}
    po = consulta.get('productOfferV2')
    if po:
        args = _argumentos(po)
        retorno = _campos(por_nome.get(_nome_base(po.get('type'))))
        no = por_nome.get(_nome_base(retorno['nodes'].get('type'))) if 'nodes' in retorno else None
        info = por_nome.get(_nome_base(retorno['pageInfo'].get('type'))) if 'pageInfo' in retorno else None
        nomes_tipo = {_nome_base(a.get('type')) for a in args.values()} - {None}
        resumo['productOfferV2'] = {
            'argumentos': {n: _tipo_texto(a.get('type')) for n, a in sorted(args.items())},
            'retorno': _tipo_texto(po.get('type')),
            'campos_do_retorno': sorted(retorno),
            'campos_do_no': sorted(_campos(no)) if no else None,
            'campos_do_pageinfo': sorted(_campos(info)) if info else None,
            'tipos_dos_argumentos': {n: (_nome(por_nome[n].get('kind')) or '?') for n in sorted(nomes_tipo)
                                     if isinstance(por_nome.get(n), dict)},
        }
    gsl = mut.get('generateShortLink')
    if gsl:
        resumo['generateShortLink'] = {'argumentos': {n: _tipo_texto(a.get('type'))
                                                      for n, a in sorted(_argumentos(gsl).items())}}
    return resumo


def tipos_que_faltam(por_nome, raiz, mutacao):
    """Nomes de tipo que o resumo precisa e ainda não foram lidos (para as consultas __type)."""
    nomes = [raiz, mutacao]
    po = _campos(por_nome.get(raiz)).get('productOfferV2')
    if po:
        ret = _nome_base(po.get('type'))
        nomes.append(ret)
        nomes += [_nome_base(a.get('type')) for a in _argumentos(po).values()]
        retorno = _campos(por_nome.get(ret))
        nomes += [_nome_base(retorno[c].get('type')) for c in ('nodes', 'pageInfo') if c in retorno]
    gsl = _campos(por_nome.get(mutacao)).get('generateShortLink')
    if gsl:
        nomes += [_nome_base(a.get('type')) for a in _argumentos(gsl).values()]
    saida = []
    for n in nomes:
        if n and n not in ESCALARES and n not in por_nome and n not in saida:
            saida.append(n)
    return saida


def _nos(dados, operacao):
    """Lista de nós de `data.<operacao>.nodes` (objetos), sem exigir o pageInfo."""
    corpo = C.ler_operacao(dados, operacao)
    nos = corpo.get('nodes')
    if not isinstance(nos, list):
        raise C.FormatoInvalido(C.M_NOS)
    if len(nos) > C.MAX_NOS:
        raise C.FormatoInvalido(C.M_NOS_DEMAIS)
    if not all(isinstance(n, dict) for n in nos):
        raise C.FormatoInvalido(C.M_NO)
    return nos


def _amostra(nos):
    """1º nó com itemId e shopId válidos: {item_id, shop_id, cat_ids} (só ids), ou None."""
    for n in nos:
        item, loja = _id(n.get('itemId')), _id(n.get('shopId'))
        if item and loja:
            cats = n.get('productCatIds')
            cats = [c for c in (_id(x) for x in cats[:3]) if c] if isinstance(cats, list) else []
            return {'item_id': item, 'shop_id': loja, 'cat_ids': cats}
    return None


def _ids(nos):
    ids = []
    for n in nos:
        i = _id(n.get('itemId'))
        if i and len(ids) < MAX_IDS:
            ids.append(i)
    return ids


def ler_base(dados):
    """Sondas de produto sem pageInfo: quantos nós, os ids e a amostra."""
    nos = _nos(dados, 'productOfferV2')
    ids = _ids(nos)
    return {'n_nos': len(nos), 'n_unicos': len(set(ids)), 'ids': ids, 'amostra': _amostra(nos)}


def _campos_dos_nos(nos, esperados):
    presentes, recusados = _nomes(k for n in nos for k in n)
    tipos = {}
    for c in presentes:
        valores = [n.get(c) for n in nos if n.get(c) is not None]
        tipos[c] = _tipo_json(valores[0] if valores else None)
    saida = {'campos': presentes, 'tipos': tipos, 'campos_recusados': recusados}
    if esperados is not None:
        saida['ausentes'] = [c for c in esperados if c not in presentes]
    return saida


def ler_produtos(dados):
    """A consulta de produtos do garimpo, inteira: pageInfo, campos que vieram, tipos e amostra."""
    nos, info = C.ler_pagina(dados, 'productOfferV2')
    return {'n_nos': len(nos), 'page_info': info, **_campos_dos_nos(nos, C.CAMPOS_PRODUTO),
            'amostra': _amostra(nos)}


def _ler_pagina_de(operacao, esperados):
    def ler(dados):
        nos, info = C.ler_pagina(dados, operacao)
        return {'n_nos': len(nos), 'page_info': info, **_campos_dos_nos(nos, esperados)}
    return ler


def _ler_nos_de(operacao, esperados):
    def ler(dados):
        nos = _nos(dados, operacao)
        return {'n_nos': len(nos), **_campos_dos_nos(nos, esperados)}
    return ler


def _ler_campo(campo):
    """Sonda de um campo: quantos nós, quantos com ele nulo e o tipo JSON. Nenhum valor é guardado."""
    def ler(dados):
        nos = _nos(dados, 'productOfferV2')
        valores = [n.get(campo) for n in nos if n.get(campo) is not None]
        return {'n_nos': len(nos), 'n_nulos': len(nos) - len(valores), 'tipo': _tipo_json(valores[0] if valores else None)}
    return ler


def ler_info_de_pagina(dados):
    """Sonda do pageInfo: quantos nós e só os campos do pageInfo com valor inteiro, booleano ou nulo."""
    corpo = C.ler_operacao(dados, 'productOfferV2')
    info = corpo.get('pageInfo')
    if not isinstance(info, dict):
        raise C.FormatoInvalido(C.M_INFO)
    return {'n_nos': len(_nos(dados, 'productOfferV2')),
            'page_info': {c: info[c] for c in C.INFO_CAMPOS if c in info and (info[c] is None or isinstance(info[c], (int, bool)))}}


def ler_conversoes(dados):
    """Relatório de conversões: só contagens e nomes de campo (nada de valor de pedido)."""
    nos, info = C.ler_relatorio(dados, 'conversionReport')
    return {'n_nos': len(nos), 'limit': info['limit'], 'tem_proxima': info['tem_proxima'],
            'tem_scroll_id': info['scroll_id'] is not None, **_campos_dos_nos(nos, None)}


def _id_feed(v):
    """datafeedId como veio (pode ser composto: não normaliza): texto de 1 a 200 sem controle, ou inteiro."""
    if _eh_int(v) and v > 0:
        return str(v)
    if isinstance(v, str) and 0 < len(v) <= 200 and not any(ord(c) < 32 or 0x7f <= ord(c) <= 0x9f for c in v):
        return v
    return None


def _texto_api(v, teto=MAX_MENSAGEM):
    """Texto livre da API, saneado e cortado: fica só no banco, nunca no log nem no api_findings.md."""
    if not isinstance(v, str):
        return None
    return banco.sem_surrogates(CS._texto(RE_SENSIVEL.sub('[removido]', CS._texto(v, 4000)), teto)) or None


def ler_feeds(dados):
    """listItemFeeds: os feeds de um modo (`feeds`), com contagens, nome e descrição, e o 1º com datafeedId usável."""
    corpo = C.ler_operacao(dados, 'listItemFeeds').get('feeds')
    if not isinstance(corpo, list) or len(corpo) > C.MAX_NOS:
        raise C.FormatoInvalido(C.M_NOS)
    if not all(isinstance(f, dict) for f in corpo):
        raise C.FormatoInvalido(C.M_NO)
    escolhido = None
    for f in corpo:
        fid = _id_feed(f.get('datafeedId'))
        if fid and escolhido is None:
            escolhido = {'datafeed_id': fid, 'feed_mode': _nome(f.get('feedMode'))}
    totais = [banco._inteiro(f.get('totalCount')) for f in corpo]
    return {'n_feeds': len(corpo), 'total': sum(t for t in totais if t is not None), 'escolhido': escolhido,
            'feeds': [{'nome': _texto_api(f.get('datafeedName')), 'descricao': _texto_api(f.get('description')),
                       'data': _texto_api(f.get('date'), 40), 'total': t} for f, t in zip(corpo[:MAX_FEEDS], totais)]}


def colunas_da_linha(texto):
    """O que dá para saber das colunas por uma linha do feed (`rows.columns` é um texto só), sem guardar valor.

    JSON de objeto: os nomes das chaves. Lista ou texto com separador: quantos campos e, só se TODOS forem
    identificadores (a linha é um cabeçalho, porque uma linha de dados tem id e preço), os nomes.
    """
    if not isinstance(texto, str) or not texto:
        return {'formato': None, 'n_campos': 0, 'colunas': [], 'colunas_recusadas': 0}
    try:
        valor = json.loads(texto)
    except (ValueError, RecursionError):
        valor = None
    if isinstance(valor, dict):
        nomes, recusados = _nomes(valor)
        return {'formato': 'json_objeto', 'n_campos': len(valor), 'colunas': nomes, 'colunas_recusadas': recusados}
    separador = None
    if isinstance(valor, list):
        formato, partes = 'json_lista', valor
    else:
        separador = max(SEPARADORES_FEED, key=texto.count)
        formato, partes = 'texto', texto.split(separador)
    cabecalho = len(partes) > 1 and all(isinstance(p, str) and _nome(p.strip()) for p in partes)
    saida = {'formato': formato, 'n_campos': len(partes), 'colunas': [p.strip() for p in partes] if cabecalho else [],
             'colunas_recusadas': 0 if cabecalho else len(partes)}
    return {**saida, 'separador': separador} if separador else saida


def ler_dados_feed(dados):
    """getItemFeedData: total, linhas da página e o que a 1ª linha diz das colunas (nenhuma linha é guardada)."""
    corpo = C.ler_operacao(dados, 'getItemFeedData')
    linhas = corpo.get('rows')
    if not isinstance(linhas, list) or not all(isinstance(x, dict) for x in linhas):
        raise C.FormatoInvalido(C.M_NOS)
    info = corpo.get('pageInfo')
    if not isinstance(info, dict):
        raise C.FormatoInvalido(C.M_INFO)
    colunas = colunas_da_linha(linhas[0].get('columns') if linhas else None)
    return {'total': banco._inteiro(info.get('totalCount')), 'limit_devolvido': banco._inteiro(info.get('limit')),
            'tem_mais': info.get('hasMore') if isinstance(info.get('hasMore'), bool) else None,
            'n_linhas': len(linhas), **colunas,
            'colunas_de_categoria': [c for c in colunas['colunas'] if 'cat' in c.lower()]}


def ler_link(dados):
    """generateShortLink: o link só se for o curto da Shopee (eh_link_shopee) e couber no MAX_URL."""
    corpo = C.ler_operacao(dados, 'generateShortLink')
    link = corpo.get('shortLink')
    valido = isinstance(link, str) and len(link) <= CS.MAX_URL and CS.S.eh_link_shopee(link)
    return {'link_valido': valido, '_link': link if valido else None}


def comuns(a, b):
    return len(set(a) & set(b))


# ---------- banco: medicoes ----------
def _sem_resposta(valor):
    """True se a medição é falha de transporte ou de autenticação (a rajada guarda a falha em `parou_por`)."""
    return ('erro_api' in (valor.get('falha'), valor.get('parou_por'))
            and not K.erro_permanente(valor.get('codigo'), valor.get('http')))


def _nao_medida(nome, valor):
    """A medição gravada não vale: consulta de outra versão ou falha sem resposta (o 10000 vale só na rajada)."""
    if nome in VERSOES and valor.get('versao') != VERSOES[nome]:
        return True
    if nome == SONDA_TAXA and valor.get('codigo') == K.ERRO_SISTEMA:
        return False
    return _sem_resposta(valor)


def _terminou_em_sistema(valor):
    return valor.get('falha') == 'erro_api' and valor.get('codigo') == K.ERRO_SISTEMA


def ler_system_errors(con):
    """{nome: id} das sondas cuja última medição terminou em System Error (10000): o api_findings.md diz isso."""
    saida = {}
    for mid, nome, texto in con.execute('SELECT id, nome, valor_json FROM medicoes ORDER BY id'):
        try:
            valor = json.loads(texto)
        except ValueError:
            continue
        if isinstance(valor, dict) and _terminou_em_sistema(valor):
            saida[nome] = mid
        else:
            saida.pop(nome, None)
    return saida


def ler_medicoes(con):
    """{nome: (id, valor)} com a última medição de cada nome (JSON ilegível é ignorado). Se a última é falha de
    transporte, de autenticação ou System Error, ou de uma versão antiga da consulta, o nome fica como não medido, e
    o resumo montado em cima dele também."""
    saida, descartadas = {}, set()
    for mid, nome, texto in con.execute('SELECT id, nome, valor_json FROM medicoes ORDER BY id'):
        try:
            valor = json.loads(texto)
        except ValueError:
            continue
        if isinstance(valor, dict):
            if _nao_medida(nome, valor):
                saida.pop(nome, None)
                descartadas.add(nome)
            else:
                saida[nome] = (mid, valor)
    for nome in descartadas - set(saida):
        for prefixo, resumo in RESUMOS:
            if nome.startswith(prefixo):
                saida.pop(resumo, None)
    return saida


def gravar_medicao(con, nome, valor):
    texto = json.dumps(valor, ensure_ascii=True, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return con.execute('INSERT INTO medicoes (nome, valor_json, em) VALUES (?, ?, ?)',
                       (nome, texto, banco.agora())).lastrowid


def gravar_texto(caminho, texto):
    """Escrita atômica (arquivo temporário na mesma pasta + os.replace)."""
    pasta = os.path.dirname(caminho)
    os.makedirs(pasta, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=pasta, prefix='.' + os.path.basename(caminho) + '.', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(texto)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, caminho)
    except BaseException:
        with contextlib.suppress(OSError):
            os.remove(tmp)
        raise


# ---------- as sondas ----------
class Reconhecer:
    def __init__(self, ctx, *, refazer=False, refazer_taxa=False):
        self.ctx, self.con, self.cli, self.log = ctx, ctx.con, ctx.cliente, ctx.log
        self.refazer = refazer
        self.medidas = {nome: m for nome, m in ler_medicoes(self.con).items()
                        if not self._a_refazer(nome, m[1], refazer, refazer_taxa)}
        self.amostra = None
        self.int64_texto = ctx.achados.get('int64') != 'numero'
        self.da_memoria = False   # a última _sonda veio de uma medição já gravada
        self.a_reconfirmar = False       # a base veio da memória: reconferir antes do 1º pedido da rodada
        self.reconfirmacao_falhou = False
        self._mensagem = None
        self._ultimo = None
        self._marcas = []

    @staticmethod
    def _a_refazer(nome, valor, refazer, refazer_taxa):
        """A medição gravada não vale para esta rodada: pedido do dono, ou não é definitiva (a base que falhou e o
        link sem conferência). As duas continuam no api_findings.md até serem medidas de novo."""
        if nome == SONDA_TAXA:
            return refazer_taxa
        return refazer or nome == SONDA_BASE and not valor.get('ok') or valor.get('dono_ok', True) is None

    # --- registro, mensagem e uma requisição ---
    @contextlib.contextmanager
    def guardando_mensagens(self):
        """Durante a fase, cada resposta lida pelo cliente passa por aqui: só a mensagem do 1º erro, saneada,
        é guardada (para a medição da sonda). O leitor original volta no fim."""
        original = CS._ler_json

        def ler_json(r):
            resposta = original(r)
            self._mensagem = mensagem_de_erro(resposta)
            return resposta

        CS._ler_json = ler_json
        try:
            yield
        finally:
            CS._ler_json = original

    def registrar(self, req):
        req = dict(req)
        req['operacao'] = req.get('operacao', '').lstrip('_') or 'desconhecida'   # __schema → schema
        self._ultimo = req
        banco.registrar_requisicao(self.con, None, None, req)

    def medir(self, consulta, variaveis, ler, *, registrar=None):
        """Uma requisição. {'ok': True, ...ler(dados)} ou {'ok': False, 'falha', ...}. Teto, limite da API
        depois das esperas, falha de transporte ou de autenticação e Ctrl+C sobem (a sonda fica sem medição e é
        refeita na próxima rodada)."""
        self.reconfirmar_base()
        self._mensagem, self._ultimo = None, None
        try:
            dados = self.cli.pedir(consulta, variaveis, registrar=registrar or self.registrar)
            return {'ok': True, **ler(dados)}
        except CS.ErroApi as e:
            sistema = e.codigo == K.ERRO_SISTEMA and e.http is None   # depois das tentativas: fica gravado, e conta
            if not sistema and not K.erro_permanente(e.codigo, e.http):
                raise
            return {'ok': False, 'falha': 'erro_api', 'codigo': e.codigo if _eh_int(e.codigo) else None,
                    'http': e.http if _eh_int(e.http) else None, 'mensagem': self._mensagem}
        except CS.RespostaInvalida as e:
            lidos = (self._ultimo or {}).get('bytes') or 0
            acima = lidos > CS.MAX_RESPOSTA
            return {'ok': False, 'falha': 'acima_de_2mb' if acima else 'resposta_invalida', 'bytes': lidos,
                    'motivo': getattr(e, 'motivo', None)}

    def sonda(self, nome, medir):
        """Mede (ou devolve a medição já gravada) e grava em `medicoes`. `medir()` None = sem pré-requisito."""
        if nome in self.medidas:
            self.da_memoria = True
            self.log(f'{nome}: já medido (medicoes #{self.medidas[nome][0]}), pulado.')
            return self.medidas[nome][1]
        self.da_memoria = False
        valor = medir()
        if valor is None:
            return None
        valor = json.loads(json.dumps(valor), parse_constant=lambda _: None)   # NaN/Infinity da API → null
        if nome in VERSOES:
            valor['versao'] = VERSOES[nome]
        mid = gravar_medicao(self.con, nome, valor)
        self.medidas[nome] = (mid, valor)
        if valor.get('ok', True):
            self.log(f'{nome}: medido (medicoes #{mid}).')
        else:
            detalhe = ', '.join(x for x in (
                f'código {valor["codigo"]}' if _eh_int(valor.get('codigo')) else '',
                f'HTTP {valor["http"]}' if _eh_int(valor.get('http')) else '',
                'acima de 2 MB' if valor.get('falha') == 'acima_de_2mb' else '') if x)
            self.log(f'{nome}: a API recusou ou respondeu fora do formato ({detalhe or "sem código"}; '
                     f'medicoes #{mid}).')
        return valor

    def ja_tem(self, nome):
        if nome in self.medidas:
            self.log(f'{nome}: já medido (medicoes #{self.medidas[nome][0]}); use --refazer para medir de novo.')
            return True
        return False

    def guardar_amostra(self, valor):
        a = valor.get('amostra') if isinstance(valor, dict) and valor.get('ok') else None
        if not isinstance(a, dict) or not _id(a.get('item_id')) or not _id(a.get('shop_id')):
            return
        if self.amostra is None or not self.amostra['cat_ids'] and a.get('cat_ids'):
            self.amostra = {'item_id': a['item_id'], 'shop_id': a['shop_id'],
                            'cat_ids': [c for c in a.get('cat_ids') or [] if _id(c)]}

    def int64(self, valor):
        return valor if self.int64_texto else int(valor)

    def base(self, page=1, limit=LIMITE_SONDA, sort_type=1):
        return {'keyword': TERMO, 'sortType': sort_type, 'page': page, 'limit': limit}

    # --- 0. o portão ---
    def sondar_base(self):
        """True se a consulta conhecida como boa deu certo. Sem isso, nenhuma outra sonda roda: o erro delas seria
        a credencial, não o parâmetro que cada uma mede."""
        v = self.sonda(SONDA_BASE, lambda: self.medir(P_BASE, self.base(), ler_base))
        self.a_reconfirmar = self.da_memoria
        self.guardar_amostra(v)
        return bool(v.get('ok'))

    def reconfirmar_base(self):
        """Retomada: o pedido da base vai antes do 1º pedido da rodada, porque a medição gravada não diz nada sobre
        o Secret digitado agora. Qualquer falha sobe (saída 1; o teto e o limite, 3) antes de gravar a sonda que ia
        ser medida. Só conta em `requisicoes`: a medição boa fica como está."""
        if not self.a_reconfirmar:
            return
        self.a_reconfirmar = False
        try:
            ler_base(self.cli.pedir(P_BASE, self.base(), registrar=self.registrar))
        except (CS.ErroApi, CS.RespostaInvalida):
            self.reconfirmacao_falhou = True
            self.log('ERRO: a reconfirmação da sonda-base falhou: nada foi medido nesta rodada e as medições gravadas '
                     'ficaram como estavam. Confira o AppID e o Secret e rode de novo.', erro=True)
            raise

    # --- 1. schema ---
    def sondar_schema(self):
        intro = self.sonda('schema.introspeccao', lambda: self.medir(C.INTROSPECCAO, {}, self.ler_introspeccao))
        if intro.get('ok'):
            return
        self.sondar_tipos()

    def ler_introspeccao(self, dados):
        schema = C.ler_operacao(dados, '__schema')
        tipos = schema.get('types')
        if not isinstance(tipos, list):
            raise C.FormatoInvalido(C.M_DADOS)
        por_nome = {t['name']: t for t in tipos if isinstance(t, dict) and _nome(t.get('name'))}
        raizes = self.ler_raizes(dados)
        self.gravar_schema({'origem': '__schema', 'parcial': False, '__schema': schema})
        return {'n_tipos': len(tipos), 'bytes': (self._ultimo or {}).get('bytes'), 'arquivo': ARQ_SCHEMA,
                'resumo': resumir_schema(por_nome, raizes['raiz'], raizes['mutacao'])}

    def gravar_schema(self, conteudo):
        gravar_texto(os.path.join(self.ctx.pasta, ARQ_SCHEMA),
                     json.dumps(conteudo, ensure_ascii=True, sort_keys=True, indent=1) + '\n')

    def sondar_tipos(self):
        """Queda da introspecção: raízes e consultas __type(name: $name) menores, até MAX_TIPOS."""
        if self.ja_tem('schema.parcial'):
            return
        raizes = self.sonda('schema.raizes', lambda: self.medir(RAIZES, {}, self.ler_raizes))
        raiz = (_nome(raizes.get('raiz')) if raizes.get('ok') else None) or 'Query'
        mutacao = _nome(raizes.get('mutacao')) if raizes.get('ok') else None
        por_nome, lidos, tentados = {}, [], set()
        while len(tentados) < MAX_TIPOS:
            faltam = [n for n in tipos_que_faltam(por_nome, raiz, mutacao) if n not in tentados]
            if not faltam:
                break
            nome = faltam[0]
            tentados.add(nome)
            v = self.sonda(f'schema.tipo.{nome}',
                           lambda nome=nome: self.medir(TIPO_POR_NOME, {'name': nome}, self.ler_tipo))
            if v.get('ok') and isinstance(v.get('tipo'), dict):
                por_nome[nome] = v['tipo']
                lidos.append(nome)
        resumo = resumir_schema(por_nome, raiz, mutacao)
        if lidos:
            self.gravar_schema({'origem': '__type', 'parcial': True, 'raiz': raiz, 'mutacao': mutacao,
                                'tipos': [por_nome[n] for n in lidos]})
        self.sonda('schema.parcial', lambda: {'ok': bool(lidos), 'tipos_lidos': lidos,
                                              'tipos_tentados': sorted(tentados),
                                              'arquivo': ARQ_SCHEMA if lidos else None, 'resumo': resumo})

    @staticmethod
    def ler_raizes(dados):
        schema = C.ler_operacao(dados, '__schema')
        q, m = schema.get('queryType'), schema.get('mutationType')
        return {'raiz': _nome(q.get('name')) if isinstance(q, dict) else None,
                'mutacao': _nome(m.get('name')) if isinstance(m, dict) else None}

    @staticmethod
    def ler_tipo(dados):
        if not isinstance(dados, dict) or '__type' not in dados:
            raise C.FormatoInvalido(C.M_OPERACAO)
        tipo = dados['__type']
        if tipo is not None and not isinstance(tipo, dict):
            raise C.FormatoInvalido(C.M_OPERACAO)
        return {'existe': tipo is not None, 'tipo': tipo}

    # --- 2. a consulta de produtos inteira e a amostra ---
    def sondar_produtos(self):
        v = self.sonda('produtos.consulta', lambda: self.medir(P_PRODUTOS_COM_PAGINA, self.base(), ler_produtos))
        self.guardar_amostra(v)
        if not v.get('ok'):
            v = self.sonda('produtos.categorias', lambda: self.medir(P_CATEGORIAS, self.base(), ler_base))
            self.guardar_amostra(v)

    # --- 3. limit ---
    def sondar_limites(self):
        for limite in LIMITES:
            if f'limit.{limite}' == SONDA_BASE:
                continue
            v = self.sonda(f'limit.{limite}', lambda limite=limite: self.medir(P_BASE, self.base(limit=limite),
                                                                               ler_base))
            self.guardar_amostra(v)

    # --- 4. profundidade de page ---
    def sondar_paginas(self):
        if self.ja_tem('pagina.teto'):
            return
        medidas = {}

        def util(p):
            v = self.sonda(f'pagina.{p}', lambda: self.medir(P_BASE, self.base(page=p), ler_base))
            medidas[p] = v
            ids = v.get('ids') if v.get('ok') else None
            if not ids:
                return False
            return all(set(ids) != set(o.get('ids') or ()) for q, o in medidas.items() if q != p)

        ultima, primeira = 0, None
        for p in PAGINAS:
            if util(p):
                ultima = p
            else:
                primeira = p
                break
        passos = 0
        while primeira is not None and primeira - ultima > 1 and passos < PASSOS_BISSECAO:
            meio = (ultima + primeira) // 2
            passos += 1
            if util(meio):
                ultima = meio
            else:
                primeira = meio
        repetidas = sorted(p for p, v in medidas.items() if v.get('ids') and any(
            q != p and set(v['ids']) == set(o.get('ids') or ()) for q, o in medidas.items()))
        self.sonda('pagina.teto', lambda: {
            'ok': ultima > 0, 'limit': LIMITE_SONDA, 'ultima_util': ultima, 'primeira_inutil': primeira,
            'exata': primeira is not None and primeira - ultima == 1, 'paginas_medidas': sorted(medidas),
            'repetidas': repetidas})

    # --- 5. sortType ---
    def sondar_ordens(self):
        if self.ja_tem('sort.sobreposicao'):
            return
        ids = {}
        for s in SORT_TYPES:
            v = self.sonda(f'sort.{s}', lambda s=s: self.medir(P_BASE, self.base(sort_type=s), ler_base))
            if v.get('ok'):
                ids[s] = v.get('ids') or []
        pares = {f'{a}x{b}': comuns(ids[a], ids[b]) for a in sorted(ids) for b in sorted(ids) if a < b}
        self.sonda('sort.sobreposicao', lambda: {'ok': bool(ids), 'limit': LIMITE_SONDA,
                                                 'tamanhos': {str(s): len(i) for s, i in ids.items()},
                                                 'comuns': pares})

    # --- 6. listType × productCatId ---
    def sondar_list_types(self):
        if self.ja_tem('listtype.comparacao'):
            return
        cat = self.amostra['cat_ids'][-1] if self.amostra and self.amostra['cat_ids'] else None
        if cat is None:
            self.log('listType × productCatId: não medido (a amostra não trouxe categoria).')
            return
        nivel = len(self.amostra['cat_ids'])
        ref = self.sonda('categoria.produto', lambda: {
            **self.medir(P_CATEGORIA, {'productCatId': int(cat), 'page': 1, 'limit': LIMITE_SONDA}, ler_base),
            'cat_id': cat, 'nivel': nivel})
        tipos = {}
        for lt in LIST_TYPES:
            v = self.sonda(f'listtype.{lt}', lambda lt=lt: {
                **self.medir(P_LISTTYPE, {'listType': lt, 'matchId': self.int64(cat), 'page': 1,
                                          'limit': LIMITE_SONDA}, ler_base),
                'cat_id': cat, 'match_id_como': 'texto' if self.int64_texto else 'numero'})
            tipos[str(lt)] = ({'n_nos': v.get('n_nos'), 'comuns_com_categoria':
                               comuns(v.get('ids') or [], ref.get('ids') or []) if ref.get('ok') else None}
                              if v.get('ok') else None)
        self.sonda('listtype.comparacao', lambda: {
            'ok': bool(ref.get('ok') or any(tipos.values())), 'cat_id': ref.get('cat_id'),
            'categoria_n_nos': ref.get('n_nos') if ref.get('ok') else None, 'list_types': tipos})

    # --- 7. isAMSOffer e isKeySeller ---
    def sondar_filtros(self):
        if self.ja_tem('filtro.comparacao'):
            return
        ams = self.sonda('filtro.ams', lambda: self.medir(P_AMS, {**self.base(), 'isAMSOffer': True}, ler_base))
        key = self.sonda('filtro.keyseller', lambda: self.medir(P_KEYSELLER, {**self.base(), 'isKeySeller': True},
                                                                ler_base))
        ref = self.medidas.get('sort.1', (None, {}))[1]
        ref_ids = ref.get('ids') if ref.get('ok') else None

        def comparar(v):
            if not v.get('ok'):
                return None
            return {'n_nos': v.get('n_nos'),
                    'comuns_com_sort1': comuns(v.get('ids') or [], ref_ids) if ref_ids is not None else None}

        self.sonda('filtro.comparacao', lambda: {'ok': bool(ams.get('ok') or key.get('ok')),
                                                 'sort1_n_nos': len(ref_ids) if ref_ids is not None else None,
                                                 'ams': comparar(ams), 'keyseller': comparar(key)})

    # --- 8. Int64 ---
    def sondar_int64(self):
        if not self.amostra:
            self.log('Int64: não medido (a amostra não trouxe item e loja).')
            return
        item, loja = self.amostra['item_id'], self.amostra['shop_id']
        for como, conv in (('numero', int), ('texto', str)):
            self.sonda(f'int64.{como}', lambda conv=conv: {
                **self.medir(P_ITEM, {'shopId': conv(loja), 'itemId': conv(item), 'page': 1,
                                      'limit': LIMITE_SONDA}, ler_base),
                'item_id': item})

    # --- 8a. campos que podem vir nulos ---
    def sondar_campos(self):
        """Um campo que vem nulo (`got null for non-null`) derruba a página inteira: cada um é medido sozinho, sobre
        os 9 que funcionam em produção, e os aceitos são confirmados juntos."""
        aceitos, recusados = [], []
        for campo in C.CAMPOS_EXTRAS:
            v = self.sonda(f'campos.{campo}', lambda campo=campo: self.medir(
                C.consulta_com_campos(C.CAMPOS_PRODUCAO + (campo,)), self.base(limit=LIMITE_MAXIMO), _ler_campo(campo)))
            (aceitos if v.get('ok') else recusados).append(campo)
        self.sondar_info_de_pagina()
        paginas = {}
        if aceitos:
            for p in PAGINAS_COMBINADO:
                v = self.sonda(f'campos.combinado.{p}', lambda p=p: self.medir(
                    C.consulta_com_campos(C.CAMPOS_PRODUCAO + tuple(aceitos)), self.base(page=p, limit=LIMITE_MAXIMO),
                    _ler_nos_de('productOfferV2', C.CAMPOS_PRODUCAO + tuple(aceitos))))
                paginas[str(p)] = bool(v.get('ok'))
        self.sonda('campos.combinados', lambda: {'ok': all(paginas.values()), 'aceitos': aceitos, 'recusados': recusados,
                                                 'paginas': paginas})

    def sondar_info_de_pagina(self):
        v = self.sonda('campos.pageInfo', lambda: self.medir(
            C.consulta_com_campos(C.CAMPOS_PRODUCAO, pagina=C.INFO_CAMPOS), self.base(limit=LIMITE_MAXIMO),
            ler_info_de_pagina))
        if v.get('falha') != 'erro_api' or v.get('codigo') == K.ERRO_SISTEMA:
            return
        for campo in C.INFO_CAMPOS:
            self.sonda(f'campos.pageInfo.{campo}', lambda campo=campo: self.medir(
                C.consulta_com_campos(C.CAMPOS_PRODUCAO, pagina=(campo,)), self.base(limit=LIMITE_MAXIMO),
                ler_info_de_pagina))

    # --- 8b. profundidade com limit 50 ---
    def sondar_paginas_50(self):
        medidas = {p: self.sonda(f'pagina50.{p}', lambda p=p: self.medir(
            P_BASE, self.base(page=p, limit=LIMITE_MAXIMO), ler_base)) for p in PAGINAS_50}
        com_itens = [p for p, v in medidas.items() if v.get('ok') and v.get('ids')]
        ultima = max(com_itens, default=0)
        vazias = [p for p, v in medidas.items() if v.get('ok') and not v.get('ids') and p > ultima]
        self.sonda('pagina50.teto', lambda: {
            'ok': bool(com_itens), 'limit': LIMITE_MAXIMO, 'ultima_com_itens': ultima,
            'primeira_sem_itens': min(vazias, default=None), 'itens_ate_a_ultima': ultima * LIMITE_MAXIMO,
            'com_erro': [p for p, v in medidas.items() if not v.get('ok')],
            'repetidas': sorted(p for p, v in medidas.items() if v.get('ids') and any(
                q != p and set(v['ids']) == set(o.get('ids') or ()) for q, o in medidas.items()))})

    # --- 9. rajada de taxa ---
    def registrar_rajada(self, req):
        self.registrar(req)
        self._marcas.append(time.monotonic())
        if req.get('codigo') == CS.ERRO_LIMITE or req.get('http') == 429:
            raise _PrimeiroLimite()
        if req.get('codigo') == K.ERRO_SISTEMA:
            raise _SistemaNaRajada(req.get('http'))

    def sondar_taxa(self):
        if self.refazer and SONDA_TAXA in self.medidas:
            self.log('taxa: o --refazer não repete a rajada; use --refazer-taxa para isso.')
        self.sonda(SONDA_TAXA, self.rajada)

    def rajada(self):
        self.reconfirmar_base()
        degraus, enviadas, parou, limite_na, falha = [], 0, 'fim', None, {}
        pausa_original = self.cli.pausa
        try:
            for taxa, n in DEGRAUS:
                self.cli.pausa = max(0.0, 1 / taxa - K.JITTER / 2)   # intervalo médio de 1/taxa s
                self._marcas, feitas, parou_aqui = [], 0, None
                for _ in range(n):
                    feitas += 1
                    try:
                        self.cli.pedir(P_BASE, self.base(), registrar=self.registrar_rajada)
                    except _PrimeiroLimite:
                        parou_aqui, limite_na = 'limite', enviadas + feitas
                    except _SistemaNaRajada as e:   # encerra a rajada e vale como medição, sem nova tentativa
                        parou_aqui = 'erro_api'
                        falha = {'codigo': K.ERRO_SISTEMA, 'http': None if e.http == 200 else e.http,
                                 'mensagem': self._mensagem}
                    except CS.ErroApi as e:
                        if not K.erro_permanente(e.codigo, e.http):
                            raise
                        parou_aqui = 'erro_api'
                        falha = {'codigo': e.codigo if _eh_int(e.codigo) else None,
                                 'http': e.http if _eh_int(e.http) else None, 'mensagem': self._mensagem}
                    except CS.RespostaInvalida:
                        parou_aqui = 'resposta_invalida'
                    if parou_aqui:
                        break
                marcas = self._marcas
                segundos = marcas[-1] - marcas[0] if len(marcas) > 1 else None
                degraus.append({'taxa_alvo': taxa, 'pausa': round(self.cli.pausa, 3), 'enviadas': feitas,
                                'segundos': round(segundos, 3) if segundos is not None else None,
                                'taxa_medida': round((len(marcas) - 1) / segundos, 3) if segundos else None})
                enviadas += feitas
                if parou_aqui:
                    parou = parou_aqui
                    break
        finally:
            self.cli.pausa = pausa_original
        return {'ok': True, 'enviadas': enviadas, 'maximo': sum(n for _, n in DEGRAUS), 'parou_por': parou,
                'primeiro_limite_na': limite_na, 'degraus': degraus, **falha}

    # --- 10. subIds ---
    def sondar_subids(self):
        if not self.amostra:
            self.log('subIds: não medido (a amostra não trouxe item e loja).')
            return
        origem = C.PREFIXO_ORIGEM + 'product/' + self.amostra['shop_id'] + '/' + self.amostra['item_id']
        for nome, sub_ids in SUBIDS:
            v = self.sonda(f'subid.{nome}', lambda sub_ids=sub_ids: self.medir_link(origem, sub_ids))
            if v.get('dono_ok') is False and not self.da_memoria:
                raise CS.DonoErrado()
            if v.get('dono_ok', True) is None:
                self.log(f'subid.{nome}: {SEM_CONFERIR}; a próxima rodada refaz esta sonda.')

    def medir_link(self, origem, sub_ids):
        v = self.medir(C.GERAR_LINK, C.variaveis_link(origem, list(sub_ids)), ler_link)
        v['sub_ids'] = list(sub_ids)
        link = v.pop('_link', None)
        if not link:
            return v
        try:
            destino = CS.destino(link)
        except OSError:
            destino = None
        if destino is None:        # sem 3xx: não deu para conferir; o link fica só no banco
            v['dono_ok'] = None
        elif not CS.dono_ok(destino):
            v['dono_ok'] = False   # link de outro afiliado: não fica nem no banco
            return v
        else:
            v['dono_ok'] = True
        v['link'] = link
        return v

    # --- 11. datafeeds ---
    def sondar_feeds(self):
        modos = {modo: self.sonda(f'feeds.{modo.lower()}', lambda modo=modo: self.medir(
            C.LISTAR_FEEDS, {'feedMode': modo}, ler_feeds)) for modo in ('FULL', 'DELTA')}
        escolhido = modos['FULL'].get('escolhido') if modos['FULL'].get('ok') else None
        if not escolhido or not _id_feed(escolhido.get('datafeed_id')):
            self.log('getItemFeedData: não medido (nenhum datafeedId utilizável na lista).')
            return
        fid = escolhido['datafeed_id']

        def pagina(limite):
            return {**self.medir(C.DADOS_FEED, {'datafeedId': fid, 'offset': 0, 'limit': limite}, ler_dados_feed),
                    'limit': limite, 'feed_mode': escolhido.get('feed_mode')}

        dados = self.sonda('feeds.dados', lambda: pagina(LIMITE_FEED))
        if dados.get('falha') == 'acima_de_2mb' or _eh_int(dados.get('codigo')) and dados['codigo'] != K.ERRO_SISTEMA:
            self.sonda('feeds.dados_menor', lambda: pagina(LIMITE_FEED_MENOR))

    # --- 12. outras consultas ---
    def sondar_outras(self):
        lojas = self.sonda('lojas', lambda: self.medir(P_LOJAS_COM_PAGINA, {'keyword': TERMO, 'page': 1,
                                                                          'limit': LIMITE_SONDA},
                                                       _ler_pagina_de('shopOfferV2', C.CAMPOS_LOJA)))
        if lojas.get('falha') == 'erro_api' and lojas.get('codigo') != K.ERRO_SISTEMA:
            self.sonda('lojas.sem_pagina', lambda: self.medir(P_LOJAS_SEM_PAGINA, {'keyword': TERMO, 'page': 1,
                                                                                   'limit': LIMITE_SONDA},
                                                              _ler_nos_de('shopOfferV2', C.CAMPOS_LOJA)))
        self.sonda('campanhas', lambda: self.medir(P_CAMPANHAS, {'page': 1, 'limit': LIMITE_SONDA},
                                                   _ler_nos_de('shopeeOfferV2', C.CAMPOS_CAMPANHA)))

        def conversoes():
            fim = int(time.time())
            return {**self.medir(C.RELATORIO_CONVERSOES, {'purchaseTimeStart': self.int64(str(fim - JANELA_CONVERSOES)),
                                                          'purchaseTimeEnd': self.int64(str(fim)),
                                                          'limit': LIMITE_SONDA},
                                 ler_conversoes), 'janela_dias': JANELA_CONVERSOES // 86400}

        self.sonda('conversoes', conversoes)

    def tudo(self):
        if not self.sondar_base():
            return
        self.sondar_schema()
        self.sondar_produtos()
        self.sondar_limites()
        self.sondar_paginas()
        self.sondar_ordens()
        self.sondar_list_types()
        self.sondar_filtros()
        self.sondar_int64()
        self.sondar_campos()
        self.sondar_paginas_50()
        self.sondar_taxa()
        self.sondar_subids()
        self.sondar_feeds()
        self.sondar_outras()

    def problemas(self):
        """Por que esta rodada não pode sair com 0, mesmo sem exceção: textos fixos, com o nome da sonda."""
        saida = []
        if not self.medidas.get(SONDA_BASE, (None, {}))[1].get('ok'):
            saida.append('a sonda-base (a consulta de produtos conhecida como boa) falhou, e nada mais foi medido. '
                         'Confira o AppID e o Secret e rode de novo.')
        for nome, _ in SUBIDS:
            dono = self.medidas.get(f'subid.{nome}', (None, {}))[1].get('dono_ok', True)
            if dono is False:
                saida.append(f'subid.{nome}: o link gerado é de outro afiliado (não leva a '
                             f'utm_source=an_{CS.ID_AFILIADO_SHOPEE}). Confira as credenciais; o --refazer mede de novo.')
            elif dono is None:
                saida.append(f'subid.{nome}: {SEM_CONFERIR}.')
        presas = sorted(n for n, (_, v) in self.medidas.items() if _terminou_em_sistema(v))
        if presas:
            saida.append('estas sondas terminaram em System Error (10000) depois das tentativas e contam como não '
                         'medidas; rode de novo para refazê-las: ' + ', '.join(presas) + '.')
        return saida

    def escrever_findings(self):
        caminho = os.path.join(self.ctx.pasta, ARQ_FINDINGS)
        gravar_texto(caminho, gerar_findings(ler_medicoes(self.con), ler_system_errors(self.con)))
        return caminho


# ---------- docs/api_findings.md ----------
NAO_MEDIDO = 'não medido'
SEM_CONFERIR = 'não deu para conferir o dono do link (rede ou link sem redirecionamento)'
MOTIVOS = {getattr(C, n) for n in dir(C) if n.startswith('M_')}


def _seguro(v):
    """Valor para o Markdown: inteiro, real, booleano ou nome válido; o resto vira `?`."""
    if isinstance(v, bool):
        return 'sim' if v else 'não'
    if _eh_int(v) or isinstance(v, float):
        return str(v)
    if isinstance(v, str) and RE_TIPO_TEXTO.fullmatch(v):
        return v
    return '?'


def _lista(nomes):
    nomes = [n for n in (nomes or []) if isinstance(n, str)]
    return ', '.join(f'`{_seguro(n)}`' for n in nomes) if nomes else '(nenhum)'


class _Findings:
    def __init__(self, medidas, sistema=None):
        self.m = medidas
        self.sistema = sistema or {}   # {nome: id}: terminou em System Error (conta como não medida)
        self.linhas = []

    def ref(self, nome):
        return f'(medicoes #{self.m[nome][0]})'

    def valor(self, nome):
        """Valor da medição se ela existe e deu certo; None se não."""
        if nome not in self.m:
            return None
        v = self.m[nome][1]
        return v if v.get('ok', True) else None

    def falhou(self, nome):
        """'não medido' com o motivo (só código, HTTP ou texto fixo) e a referência."""
        if nome in self.sistema:
            return f'{NAO_MEDIDO} (System Error 10000, depois das tentativas) (medicoes #{self.sistema[nome]})'
        if nome not in self.m:
            return NAO_MEDIDO
        v = self.m[nome][1]
        partes = []
        if _eh_int(v.get('codigo')):
            partes.append(f'código {v["codigo"]}')
        if _eh_int(v.get('http')):
            partes.append(f'HTTP {v["http"]}')
        if v.get('falha') == 'acima_de_2mb':
            partes.append('resposta acima de 2 MB')
        elif v.get('falha') == 'resposta_invalida':
            partes.append('resposta fora do formato' + (f': {v["motivo"]}' if v.get('motivo') in MOTIVOS else ''))
        return f'{NAO_MEDIDO} (a sonda falhou: {", ".join(partes) or "sem código"}) {self.ref(nome)}'

    def item(self, texto):
        self.linhas.append(f'- {texto}')

    def titulo(self, texto):
        self.linhas += ['', f'## {texto}', '']

    def campo(self, nome, rotulo, formatar):
        v = self.valor(nome)
        self.item(f'{rotulo}: ' + (f'{formatar(v)} {self.ref(nome)}' if v is not None else self.falhou(nome)))

    def resumo_schema(self, resumo, nome):
        if not isinstance(resumo, dict):
            return
        ref = self.ref(nome)
        self.item(f'Raiz das consultas: `{_seguro(resumo.get("raiz"))}`; das mutações: '
                  f'`{_seguro(resumo.get("mutacao"))}` {ref}')
        ops = resumo.get('operacoes')
        if isinstance(ops, dict):
            self.item('Operações do garimpo no schema: ' + ', '.join(
                f'`{_seguro(op)}` {_seguro(bool(ok))}' for op, ok in sorted(ops.items())) + f' {ref}')
        po = resumo.get('productOfferV2')
        if not isinstance(po, dict):
            self.item(f'productOfferV2: {NAO_MEDIDO} (não apareceu no que foi lido) {ref}')
        else:
            args = po.get('argumentos') if isinstance(po.get('argumentos'), dict) else {}
            self.item('Argumentos do productOfferV2: ' + (', '.join(
                f'`{_seguro(n)}: {_seguro(t)}`' for n, t in sorted(args.items())) or '(nenhum)') + f' {ref}')
            for arg in ('productCatId', 'listType', 'matchId', 'isAMSOffer', 'isKeySeller'):
                self.item(f'Argumento `{arg}` existe: {_seguro(arg in args)} {ref}')
            tipos = po.get('tipos_dos_argumentos')
            if isinstance(tipos, dict) and tipos:
                self.item('Tipos dos argumentos: ' + ', '.join(
                    f'`{_seguro(n)}` ({_seguro(k)})' for n, k in sorted(tipos.items())) + f' {ref}')
            for chave, rotulo in (('campos_do_no', 'Campos do nó'), ('campos_do_pageinfo', 'Campos do pageInfo')):
                valor = po.get(chave)
                self.item(f'{rotulo}: ' + (f'{_lista(valor)} {ref}' if isinstance(valor, list) else NAO_MEDIDO))
        gsl = resumo.get('generateShortLink')
        if isinstance(gsl, dict) and isinstance(gsl.get('argumentos'), dict):
            self.item('Argumentos do generateShortLink: ' + ', '.join(
                f'`{_seguro(n)}: {_seguro(t)}`' for n, t in sorted(gsl['argumentos'].items())) + f' {ref}')

    def gerar_campos(self):
        L = self.linhas
        self.titulo('Campos do `productOfferV2` que podem vir nulos (9 de produção + 1 campo, limit 50)')
        L += ['| campo | resultado | nulos | medição |', '|---|---|---|---|']
        for campo in C.CAMPOS_EXTRAS:
            nome = f'campos.{campo}'
            v = self.valor(nome)
            if v is not None:
                L.append(f'| {campo} | aceito | {_seguro(v.get("n_nulos"))} de {_seguro(v.get("n_nos"))} | {self.ref(nome)} |')
            elif nome in self.m and _eh_int(self.m[nome][1].get('codigo')):
                L.append(f'| {campo} | recusado (código {self.m[nome][1]["codigo"]}) | | {self.ref(nome)} |')
            else:
                L.append(f'| {campo} | {self.falhou(nome)} | | |')
        L.append('')
        self.campo('campos.pageInfo', '`pageInfo { page limit hasNextPage }` junto dos 9 campos', lambda v: 'aceito')
        for campo in C.INFO_CAMPOS:
            nome = f'campos.pageInfo.{campo}'
            if nome in {*self.m, *self.sistema}:
                self.campo(nome, f'Só o `{campo}` do pageInfo', lambda v: 'aceito')
        if 'campos.combinados' in self.m:
            v = self.m['campos.combinados'][1]
            paginas = v.get('paginas') if isinstance(v.get('paginas'), dict) else {}
            self.item(f'Campos aceitos juntos: {_lista(v.get("aceitos"))}; recusados: {_lista(v.get("recusados"))}; '
                      'confirmados nas páginas: ' + (', '.join(f'{_seguro(p)} {_seguro(ok)}' for p, ok in sorted(paginas.items()))
                                                     or 'nenhuma') + f' {self.ref("campos.combinados")}')
        else:
            self.item('Campos aceitos juntos: ' + self.falhou('campos.combinados'))

    def gerar_paginas_50(self):
        L = self.linhas
        self.titulo('Profundidade de `page` com limit 50 (teto de páginas ou de itens)')
        L += ['| page (limit 50) | itens devolvidos | medição |', '|---|---|---|']
        for p in PAGINAS_50:
            nome = f'pagina50.{p}'
            v = self.valor(nome)
            L.append(f'| {p} | {_seguro(v.get("n_nos"))} | {self.ref(nome)} |' if v is not None
                     else f'| {p} | {self.falhou(nome)} | |')
        L.append('')
        self.campo('pagina50.teto', 'Resultado', lambda v: (
            f'última página com itens: {_seguro(v.get("ultima_com_itens"))}; primeira sem itens: '
            f'{_seguro(v.get("primeira_sem_itens")) if v.get("primeira_sem_itens") is not None else "nenhuma das medidas"}; '
            f'itens até a última: {_seguro(v.get("itens_ate_a_ultima"))}; páginas repetidas: '
            f'{", ".join(_seguro(p) for p in v.get("repetidas") or []) or "nenhuma"}; com erro: '
            f'{", ".join(_seguro(p) for p in v.get("com_erro") or []) or "nenhuma"}'))

    def gerar(self):
        L = self.linhas
        L += ['# Achados da Open API de afiliados da Shopee (Fase 1, `reconhecer`)', '',
              f'Gerado pelo `garimpo.py reconhecer` em {banco.agora()}. Só valores medidos: cada número aponta a '
              'linha da tabela `medicoes` do `garimpo.db` (`#id`). "não medido" quer dizer que a sonda não rodou '
              'ou falhou; a mensagem de erro da API fica só no banco. A interpretação fica para a etapa 8.']

        self.titulo('Schema')
        intro = self.valor('schema.introspeccao')
        if intro is not None:
            self.item(f'Introspecção completa: aceita, {_seguro(intro.get("n_tipos"))} tipos, '
                      f'{_seguro(intro.get("bytes"))} bytes, salva em `docs/schema.json` '
                      f'{self.ref("schema.introspeccao")}')
            self.resumo_schema(intro.get('resumo'), 'schema.introspeccao')
        else:
            self.item('Introspecção completa: ' + self.falhou('schema.introspeccao'))
            if 'schema.raizes' in self.m:
                self.campo('schema.raizes', 'Raízes do schema (`__schema` só com os nomes)',
                           lambda v: f'`{_seguro(v.get("raiz"))}` e `{_seguro(v.get("mutacao"))}`')
            parcial = self.valor('schema.parcial')
            if parcial is not None:
                self.item(f'Consultas `__type`: {len(parcial.get("tipos_lidos") or [])} tipos lidos de '
                          f'{len(parcial.get("tipos_tentados") or [])} tentados ({_lista(parcial.get("tipos_lidos"))}), '
                          f'salvos em `docs/schema.json` (parcial) {self.ref("schema.parcial")}')
                self.resumo_schema(parcial.get('resumo'), 'schema.parcial')
            else:
                self.item('Consultas `__type`: ' + self.falhou('schema.parcial'))

        self.titulo('Consulta de produtos do garimpo (`productOfferV2`, todos os campos do brief)')
        self.campo('produtos.consulta', 'Aceita', lambda v: (
            f'sim, {_seguro(v.get("n_nos"))} itens; pageInfo: page {_seguro((v.get("page_info") or {}).get("page"))}, '
            f'limit {_seguro((v.get("page_info") or {}).get("limit"))}, hasNextPage '
            f'{_seguro((v.get("page_info") or {}).get("tem_proxima"))}'))
        v = self.valor('produtos.consulta')
        if v is not None:
            ref = self.ref('produtos.consulta')
            self.item(f'Campos que vieram: {_lista(v.get("campos"))} {ref}')
            self.item(f'Campos do brief que não vieram: {_lista(v.get("ausentes"))} {ref}')
            tipos = v.get('tipos') if isinstance(v.get('tipos'), dict) else {}
            self.item('Tipo JSON de cada campo: ' + (', '.join(
                f'`{_seguro(c)}` {_seguro(t)}' for c, t in sorted(tipos.items())) or '(nenhum)') + f' {ref}')
        elif 'produtos.categorias' in self.m:
            self.campo('produtos.categorias', 'Só `itemId shopId productCatIds`',
                       lambda v: f'aceita, {_seguro(v.get("n_nos"))} itens')

        self.titulo('`limit` por página')
        L += ['| limit pedido | itens devolvidos | medição |', '|---|---|---|']
        for limite in LIMITES:
            nome = f'limit.{limite}'
            v = self.valor(nome)
            L.append(f'| {limite} | {_seguro(v.get("n_nos"))} | {self.ref(nome)} |' if v is not None
                     else f'| {limite} | {self.falhou(nome)} | |')

        self.titulo('Profundidade de `page`')
        paginas = sorted(int(n.split('.')[1]) for n in {*self.m, *self.sistema} if re.fullmatch(r'pagina\.\d+', n))
        if paginas:
            L += [f'| page (limit {LIMITE_SONDA}) | itens devolvidos | medição |', '|---|---|---|']
            for p in paginas:
                v = self.valor(f'pagina.{p}')
                L.append(f'| {p} | {_seguro(v.get("n_nos"))} | {self.ref(f"pagina.{p}")} |' if v is not None
                         else f'| {p} | {self.falhou(f"pagina.{p}")} | |')
            L.append('')
        self.campo('pagina.teto', 'Resultado', lambda v: (
            f'última página com itens novos: {_seguro(v.get("ultima_util"))}; primeira sem itens ou repetida: '
            f'{_seguro(v.get("primeira_inutil")) if v.get("primeira_inutil") is not None else "nenhuma até 1000"}'
            f'; exata: {_seguro(v.get("exata"))}; páginas repetidas: '
            f'{", ".join(_seguro(p) for p in v.get("repetidas") or []) or "nenhuma"}'))

        self.titulo('Sobreposição dos `sortType` (mesma palavra-chave, page 1)')
        L += ['| sortType | itens | medição |', '|---|---|---|']
        for s in SORT_TYPES:
            v = self.valor(f'sort.{s}')
            L.append(f'| {s} | {_seguro(v.get("n_nos"))} | {self.ref(f"sort.{s}")} |' if v is not None
                     else f'| {s} | {self.falhou(f"sort.{s}")} | |')
        L.append('')
        self.campo('sort.sobreposicao', 'Itens em comum por par', lambda v: ', '.join(
            f'{_seguro(p)}: {_seguro(n)}' for p, n in sorted((v.get('comuns') or {}).items())) or 'nenhum par')

        self.titulo('`listType` 0 a 4 com `matchId` da categoria × `productCatId`')
        self.campo('categoria.produto', '`productCatId` (referência)', lambda v: (
            f'categoria `{_seguro(v.get("cat_id"))}` (nível {_seguro(v.get("nivel"))}), '
            f'{_seguro(v.get("n_nos"))} itens'))
        ref_ids = (self.valor('categoria.produto') or {}).get('ids')
        L += ['', '| listType | itens | em comum com o productCatId | medição |', '|---|---|---|---|']
        for lt in LIST_TYPES:
            nome = f'listtype.{lt}'
            v = self.valor(nome)
            if v is None:
                L.append(f'| {lt} | {self.falhou(nome)} | | |')
            else:
                c = comuns(v.get('ids') or [], ref_ids) if ref_ids is not None else NAO_MEDIDO
                L.append(f'| {lt} | {_seguro(v.get("n_nos"))} | {_seguro(c) if c != NAO_MEDIDO else c} | '
                         f'{self.ref(nome)} |')

        self.titulo('`isAMSOffer` e `isKeySeller` (comparados ao sortType 1)')
        for nome, rotulo in (('filtro.ams', '`isAMSOffer: true`'), ('filtro.keyseller', '`isKeySeller: true`')):
            self.campo(nome, rotulo, lambda v: f'{_seguro(v.get("n_nos"))} itens')
        self.campo('filtro.comparacao', 'Em comum com o sortType 1', lambda v: '; '.join(
            f'{rot}: {_seguro((v.get(k) or {}).get("comuns_com_sort1")) if v.get(k) else NAO_MEDIDO}'
            for k, rot in (('ams', 'isAMSOffer'), ('keyseller', 'isKeySeller'))))

        self.titulo('Int64 (`shopId` e `itemId`)')
        for como in ('numero', 'texto'):
            nome = f'int64.{como}'
            self.campo(nome, f'Como {"número" if como == "numero" else "texto"}', lambda v: (
                f'aceito, {_seguro(v.get("n_nos"))} itens; o item pedido voltou: '
                f'{_seguro(v.get("item_id") in (v.get("ids") or []))}'))

        self.gerar_campos()
        self.gerar_paginas_50()

        self.titulo('Taxa (rajada em degraus, para no 1º 10030)')
        v = self.valor('taxa')
        if v is None:
            self.item('Rajada: ' + self.falhou('taxa'))
        else:
            ref = self.ref('taxa')
            limite = v.get('primeiro_limite_na')
            self.item(f'Requisições: {_seguro(v.get("enviadas"))} de {_seguro(v.get("maximo"))}; parou por: '
                      f'{_seguro(v.get("parou_por"))}; primeiro 10030/429 na requisição: '
                      f'{_seguro(limite) if limite is not None else "nenhum"} {ref}')
            for d in v.get('degraus') or []:
                self.item(f'Degrau de {_seguro(d.get("taxa_alvo"))} req/s: {_seguro(d.get("enviadas"))} enviadas, '
                          f'taxa medida {_seguro(d.get("taxa_medida")) if d.get("taxa_medida") else NAO_MEDIDO} '
                          f'req/s em {_seguro(d.get("segundos")) if d.get("segundos") else NAO_MEDIDO} s {ref}')

        self.titulo('subIds no `generateShortLink`')
        for nome, sub_ids in SUBIDS:
            self.campo(f'subid.{nome}', f'subIds {" ".join(f"`{s}`" for s in sub_ids)}', lambda v: (
                f'aceito; link curto da Shopee: {_seguro(v.get("link_valido"))}; dono conferido: '
                + ('sim' if v.get('dono_ok') is True else 'NÃO (link de outro afiliado)' if v.get('dono_ok') is False
                   else SEM_CONFERIR if 'dono_ok' in v else 'não se aplica')))
        self.item('Separador dos subIds no relatório de conversões: não medido (só aparece depois de cliques; Fase 7)')

        self.titulo('Datafeeds')
        for modo in ('FULL', 'DELTA'):
            self.campo(f'feeds.{modo.lower()}', f'`listItemFeeds` {modo}', lambda v: (
                f'{_seguro(v.get("n_feeds"))} feeds; soma de totalCount: {_seguro(v.get("total"))}'))
        for nome in ('feeds.dados', 'feeds.dados_menor'):
            if nome == 'feeds.dados_menor' and nome not in self.m:
                continue
            self.campo(nome, '`getItemFeedData` (1 página' + (f', limit {LIMITE_FEED_MENOR})'
                                                              if nome.endswith('menor') else f', limit {LIMITE_FEED})'),
                       lambda v: (f'feed {_seguro(v.get("feed_mode"))}; total {_seguro(v.get("total"))}; '
                                  f'{_seguro(v.get("n_linhas"))} linhas; tem mais: {_seguro(v.get("tem_mais"))}; '
                                  f'formato da linha: {_seguro(v.get("formato"))}, {_seguro(v.get("n_campos"))} campos; '
                                  f'colunas: {_lista(v.get("colunas"))}; '
                                  f'colunas de categoria: {_lista(v.get("colunas_de_categoria"))}'))

        self.titulo('Outras consultas (1 página cada)')
        self.campo('lojas', '`shopOfferV2`', lambda v: (
            f'{_seguro(v.get("n_nos"))} itens; hasNextPage {_seguro((v.get("page_info") or {}).get("tem_proxima"))}'
            f'; campos: {_lista(v.get("campos"))}; não vieram: {_lista(v.get("ausentes"))}'))
        nos_e_campos = lambda v: (f'{_seguro(v.get("n_nos"))} itens; campos: {_lista(v.get("campos"))}; '   # noqa: E731
                                  f'não vieram: {_lista(v.get("ausentes"))}')
        if 'lojas.sem_pagina' in {*self.m, *self.sistema}:
            self.campo('lojas.sem_pagina', '`shopOfferV2` sem pageInfo', nos_e_campos)
        self.campo('campanhas', '`shopeeOfferV2`', nos_e_campos)
        self.campo('conversoes', '`conversionReport`', lambda v: (
            f'{_seguro(v.get("n_nos"))} conversões em {_seguro(v.get("janela_dias"))} dias; hasNextPage '
            f'{_seguro(v.get("tem_proxima"))}; scrollId: {_seguro(v.get("tem_scroll_id"))}; campos: '
            f'{_lista(v.get("campos"))}'))
        L += ['', f'A interpretação destes números, escrita à mão, fica em `{ARQ_INTERPRETACAO}`. Este arquivo é gerado e '
                  'sobrescrito a cada rodada; aquele não.']
        return '\n'.join(L) + '\n'


def gerar_findings(medidas, sistema=None):
    """Texto do docs/api_findings.md a partir das medições ({nome: (id, valor)}) e das que terminaram em System
    Error ({nome: id})."""
    return _Findings(medidas, sistema).gerar()


# ---------- contrato da fase ----------
def configurar(parser):
    parser.add_argument('--refazer', action='store_true',
                        help='mede tudo de novo, menos a rajada de taxa (sem isso, a sonda que já tem medição é pulada)')
    parser.add_argument('--refazer-taxa', action='store_true',
                        help='repete a rajada de taxa, que pode travar a cota da API por um tempo')


def rodar(args, ctx):
    r = Reconhecer(ctx, refazer=getattr(args, 'refazer', False), refazer_taxa=getattr(args, 'refazer_taxa', False))
    ctx.log('reconhecer: início das sondas (só medições; nenhum produto é gravado).')
    with r.guardando_mensagens():
        try:
            r.tudo()
        except BaseException as e:
            with contextlib.suppress(Exception):   # o motivo da parada é o que importa; os achados vão junto
                r.escrever_findings()
                ctx.log(f'Achados parciais em {ARQ_FINDINGS}.')
            if isinstance(e, CS.ErroApi) and not r.reconfirmacao_falhou:
                ctx.log('Falha de rede ou de autenticação: a sonda em curso não foi gravada; a próxima rodada a refaz.',
                        erro=True)
            raise
    r.escrever_findings()
    ctx.log(f'reconhecer: fim. Achados em {ARQ_FINDINGS}; medições na tabela medicoes do garimpo.db.')
    problemas = r.problemas()
    for texto in problemas:
        ctx.log(f'ERRO: {texto}', erro=True)
    return 1 if problemas else 0
