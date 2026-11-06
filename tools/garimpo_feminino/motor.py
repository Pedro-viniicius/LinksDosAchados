"""Motor do garimpo: paginação com retomada e as estratégias de uma categoria, até saturar.

Plano: docs/produto/planos/garimpo-feminino-shopee.md, etapa 7 (CA3, CA4 e CA9). Brief: Fase 4.

Só usa o `Cliente` (o único ponto de rede) e o `banco`; não tem rede própria.

`paginar(con, cli, consulta, variaveis, ...)`: percorre as páginas de UMA consulta (as variáveis sem `page`).
- Retoma pelo checkpoint: a próxima página é `ultima_pagina + 1` (o `banco.gravar_pagina` já guarda a página, a
  requisição e o checkpoint numa só transação, então só a página em curso se repete).
- A consulta NÃO pede o `pageInfo` (a completa foi recusada no R1, medicoes #3 e #47), então a parada vem dos nós:
  página vazia ou com menos itens que o `limit` (`esgotada`), página cheia que é a do teto medido (`teto`: leu a
  página `teto_pagina` e pode haver mais) ou `paginas_sem_novo` páginas seguidas sem item novo (`saturada`). Quando
  o último lote vem exatamente cheio, sai um pedido a mais, que volta vazio e encerra. Se a API mandar `pageInfo`
  mesmo assim, ele é ignorado. A contagem das páginas seguidas sem novo é refeita pela tabela `requisicoes`, então
  vale também depois de uma retomada.
  Se a rodada caiu depois de gravar a última página e antes de fechar a consulta, a retomada decide só pelo
  checkpoint (o tamanho da página não é guardado): pode gastar uma requisição a mais, que volta vazia e encerra.
- Fecha a consulta com `banco.fechar_consulta`. Erro da API ou resposta fora do formato fecha com `erro` e
  sobe a exceção. Teto de requisições (`Teto`), limite da API (`LimiteAtingido`) e Ctrl+C deixam a consulta
  `pendente`. Pedido que não gerou página (limite 10030/429, falha) vai para `requisicoes` na mesma página, sem
  `novos`.
- Consulta em `erro`: a retomada olha o último pedido dela em `requisicoes`. Erro permanente (`K.erro_permanente`:
  com código ou HTTP 4xx) não é repetido, e `paginar` devolve o status `erro` sem pedir nada. Transitório (rede,
  5xx, autenticação, limite) ou resposta fora do formato continua da página seguinte à última gravada.
- Nó sem itemId válido é pulado pelo banco e contado em `pulados`.

`garimpar_categoria(con, cli, cat, estrategias, ...)`: roda as estratégias do brief, nesta ordem padrão
(`ORDEM_PADRAO`; o `estrategias` do achados.json troca a ordem ou tira alguma, usando estes nomes):
1. `sort`: `productCatId` x `sortType` 1 a 5.
2. `listtype`: `listType` 4 e 3 com `matchId` = a categoria, só os que o achados.json liberar (`list_types`).
3. `ams_keyseller`: `isAMSOffer` verdadeiro e, em outra consulta, `isKeySeller` verdadeiro, com `productCatId`.
4. `fatiamento`: keyword + `productCatId` (+ `sortType` 1), só se alguma consulta da categoria bateu o teto de
   página. Primeiro as sementes do nicho (`nichos.json`), depois os bigramas mais frequentes (>= 3 títulos)
   dos títulos já guardados da categoria, recalculados a cada consulta (bola de neve: o que uma fatia
   trouxe gera as próximas). Nunca repete uma palavra (comparada em minúsculas, NFC, espaços únicos), nem
   refaz uma fatia já encerrada; no máximo `MAX_FATIAS` por categoria.

Erro permanente numa consulta não trava a categoria: ela fica em `erro`, o motor segue para a próxima, e a
`parada` da categoria cita quantas foram recusadas. Erro transitório sobe (a rodada para e a próxima retoma).

Saturação: as últimas 5 consultas encerradas da categoria (feitas pelas estratégias acima) trouxeram, cada uma,
menos de 2% de itens novos (`novos`/`vistos` no banco inteiro; consulta sem item novo conta como 0%). É
checada ao começar e depois de cada consulta; com menos de 5 consultas não há saturação.

Retorno: 'saturada', 'teto' (acabaram as estratégias sem saturar e alguma consulta bateu o teto) ou 'esgotada'
(acabaram sem saturar nem bater o teto). Também grava em `categories` (`saturada`, `bateu_teto`, `parada`, com
texto fixo). Chamar de novo depois de uma queda ou de um `Teto` retoma sem repetir pedido: consulta encerrada
não pede nada.

Valores do achados.json que entram aqui (o caller os passa; veja `parametros`): `limit`, `teto_pagina`,
`int64` (como mandar os ids Int64), `list_types`, `paginas_sem_novo` e `estrategias`.
"""
import collections
import json
import os
import re
import sys
import unicodedata

PASTA = os.path.dirname(os.path.abspath(__file__))
if PASTA not in sys.path:
    sys.path.insert(0, PASTA)

import banco  # noqa: E402
import cliente as K  # noqa: E402
import consultas as C  # noqa: E402

CS = K.CS

OPERACAO = 'productOfferV2'
FASE_PADRAO = 'garimpar'
NICHOS = os.path.join(PASTA, 'nichos.json')

SORT_TYPES = (1, 2, 3, 4, 5)
LIST_TYPES = (4, 3)            # ordem do brief; só entram os que o achados.json liberar
ESTRATEGIAS = ('sort', 'listtype', 'ams_keyseller', 'fatiamento')
ORDEM_PADRAO = ESTRATEGIAS     # a ordem do brief
JANELA_SATURACAO = 5           # consultas encerradas que decidem a saturação
LIMITE_NOVOS_PCT = 2           # cada uma delas com menos de 2% de itens novos
MAX_FATIAS = 200               # fatiamentos por categoria (rede de segurança contra bola de neve sem fim)
MIN_FREQ_BIGRAMA = 3           # títulos da categoria em que o bigrama aparece
MAX_TITULOS = 20_000           # títulos lidos do banco por cálculo de bigramas
MAX_KEYWORD = 100
RE_CAT_ID = re.compile(r'[1-9][0-9]{0,18}', re.A)
RE_PALAVRA = re.compile(r'[^\W_]+')
PALAVRAS_VAZIAS = frozenset('de da do das dos para com sem e a o as os em no na nos nas um uma por ou kit '
                             'pcs un und'.split())

PARADA = {
    'saturada': 'saturada: as últimas 5 consultas trouxeram menos de 2% de itens novos',
    'teto': 'bateu o teto de páginas e as estratégias acabaram sem saturar',
    'esgotada': 'as estratégias acabaram sem saturar e sem bater o teto de páginas',
    'recusadas': 'consultas recusadas pela API (ficaram em erro e não são repetidas): {n}',
}


# ---------- validações ----------
def _inteiro(v, nome, minimo=1, maximo=10 ** 9):
    if isinstance(v, bool) or not isinstance(v, int) or not minimo <= v <= maximo:
        raise ValueError(f'{nome} tem de ser um inteiro entre {minimo} e {maximo}')
    return v


def _cat_id(cat):
    """Id da categoria (inteiro positivo ou texto de dígitos) → int."""
    if isinstance(cat, bool):
        raise ValueError('cat_id inválido')
    if isinstance(cat, str) and RE_CAT_ID.fullmatch(cat):
        cat = int(cat)
    if not isinstance(cat, int) or not 0 < cat <= banco.MAX_ID:
        raise ValueError('cat_id inválido')
    return cat


def _ordem(estrategias):
    """Lista de estratégias a rodar. None = a ordem do brief; nome desconhecido → ErroConfig (saída 2)."""
    if estrategias is None:
        return ORDEM_PADRAO
    if (not isinstance(estrategias, (list, tuple)) or not estrategias
            or not all(isinstance(e, str) and e in ESTRATEGIAS for e in estrategias)
            or len(set(estrategias)) != len(estrategias)):
        raise banco.ErroConfig('estrategias: lista não vazia, sem repetição, só com ' + ', '.join(ESTRATEGIAS))
    return tuple(estrategias)


def parametros(achados):
    """Os parâmetros do garimpo que vêm do achados.json (o dict de `garimpo.ler_achados`), prontos para
    `paginar(..., **p)` e `garimpar_categoria(..., **p)` (menos `estrategias`, que é o 4º argumento)."""
    return {'limit': achados['limit'], 'teto_pagina': achados['teto_pagina'], 'int64': achados['int64'],
            'list_types': achados['list_types'], 'paginas_sem_novo': achados['paginas_sem_novo']}


# ---------- paginação ----------
def _sem_novo_seguidas(con, consulta_id):
    """Páginas seguidas, no fim da consulta, que não trouxeram item novo (pela tabela requisicoes)."""
    n = 0
    for (novos,) in con.execute('SELECT novos FROM requisicoes WHERE consulta_id = ? AND pagina IS NOT NULL '
                                'AND novos IS NOT NULL ORDER BY pagina DESC', (consulta_id,)):
        if novos:
            break
        n += 1
    return n


def _parada(pagina, cheia, sem_novo, teto_pagina, paginas_sem_novo):
    """Status que encerra a consulta depois de gravar `pagina`, ou None para pedir a seguinte.

    `cheia`: a página veio com `limit` itens ou mais (a vazia e a incompleta são a última: `esgotada`)."""
    if not cheia:
        return 'esgotada'
    if pagina >= teto_pagina:
        return 'teto'
    if sem_novo >= paginas_sem_novo:
        return 'saturada'
    return None


def _anotar(con, consulta_id, pagina, registros):
    """Grava, sozinhas, as requisições que não geraram página. Não pode mascarar o erro que está subindo."""
    for r in registros:
        try:
            banco.registrar_requisicao(con, consulta_id, pagina, r)
        except Exception:
            pass


def _pedir_pagina(con, cli, consulta, consulta_id, variaveis, pagina):
    """Pede e grava uma página. Devolve (nós, novos). Cada pedido mandado fica em `requisicoes`."""
    registros = []
    try:
        dados = cli.pedir(consulta, variaveis, registrar=registros.append)
        nos = C.ler_nos(dados, OPERACAO)
    except BaseException:
        _anotar(con, consulta_id, pagina, registros)
        raise
    *antes, ultimo = registros   # o último é o pedido que deu certo: vai junto com a página
    _anotar(con, consulta_id, pagina, antes)
    try:
        novos = banco.gravar_pagina(con, consulta_id, pagina, nos, ultimo)
    except BaseException:
        _anotar(con, consulta_id, pagina, [ultimo])
        raise
    return nos, novos


def _erro_definitivo(con, consulta_id):
    """True se o último pedido da consulta foi recusado de vez pela API (o status `erro` também cobre o resto)."""
    ultimo = con.execute('SELECT codigo, http FROM requisicoes WHERE consulta_id = ? ORDER BY id DESC LIMIT 1',
                         (consulta_id,)).fetchone()
    return ultimo is not None and K.erro_permanente(*ultimo)


def _fechar_com_erro(con, consulta_id):
    try:
        banco.fechar_consulta(con, consulta_id, 'erro')
    except Exception:
        pass


def paginar(con, cli, consulta, variaveis, *, teto_pagina, limit, paginas_sem_novo=3, fase=FASE_PADRAO,
            estrategia=None, cat_id=None):
    """Percorre as páginas de uma consulta do productOfferV2 e a encerra. Devolve um dicionário:
    `consulta_id`, `status` ('esgotada', 'teto' ou 'saturada'; 'erro' se ela já foi recusada de vez e nada foi
    pedido), `paginas`, `vistos`, `novos` e `pulados` (só desta chamada, não do total) e `ultima_pagina`.

    `consulta` é o texto GraphQL constante (`consultas.CONSULTA_PRODUTOS`); `variaveis` são os valores da
    busca SEM `page` e SEM `limit` (o motor os põe: `limit` entra na chave do checkpoint, porque trocar o
    tamanho da página muda a numeração). Consulta já encerrada não pede nada e devolve o status que tinha.
    """
    if not isinstance(consulta, str) or K.operacao_de(consulta) != OPERACAO:
        raise ValueError(f'só a consulta {OPERACAO} pode ser paginada')
    _inteiro(teto_pagina, 'teto_pagina')
    _inteiro(limit, 'limit', maximo=500)
    _inteiro(paginas_sem_novo, 'paginas_sem_novo')
    if not isinstance(variaveis, dict) or 'page' in variaveis or 'limit' in variaveis:
        raise ValueError('as variáveis são um dicionário sem page nem limit: o motor os coloca')
    base = {**variaveis, 'limit': limit}
    ck = banco.obter_consulta(con, OPERACAO, base, fase=fase, estrategia=estrategia, cat_id=cat_id)
    cid = ck['id']
    res = {'consulta_id': cid, 'status': ck['status'], 'paginas': 0, 'vistos': 0, 'novos': 0, 'pulados': 0,
           'ultima_pagina': ck['ultima_pagina']}
    if ck['status'] in banco.STATUS_FINAIS or ck['status'] == 'erro' and _erro_definitivo(con, cid):
        return res
    sem_novo = _sem_novo_seguidas(con, cid)
    status = None
    if ck['ultima_pagina'] > 0:   # caiu depois da última página e antes de fechar
        status = _parada(ck['ultima_pagina'], True, sem_novo, teto_pagina, paginas_sem_novo)
    pagina = ck['ultima_pagina'] + 1
    while status is None:
        try:
            nos, novos = _pedir_pagina(con, cli, consulta, cid, {**base, 'page': pagina}, pagina)
        except (CS.ErroApi, CS.RespostaInvalida, ValueError):
            _fechar_com_erro(con, cid)
            raise
        pulados = banco.nos_sem_id(nos)
        res['paginas'] += 1
        res['vistos'] += len(nos) - pulados
        res['novos'] += novos
        res['pulados'] += pulados
        res['ultima_pagina'] = pagina
        sem_novo = 0 if novos else sem_novo + 1
        status = _parada(pagina, len(nos) >= limit, sem_novo, teto_pagina, paginas_sem_novo)
        pagina += 1
    banco.fechar_consulta(con, cid, status)
    res['status'] = status
    return res


# ---------- saturação e teto da categoria ----------
def _consultas_da_categoria(con, cat_id):
    """Consultas encerradas da categoria feitas pelas estratégias do motor, da mais recente à mais antiga."""
    marcas = ', '.join('?' * len(ESTRATEGIAS))
    finais = ', '.join('?' * len(banco.STATUS_FINAIS))
    return con.execute(
        f'SELECT vistos, novos FROM consultas WHERE cat_id = ? AND estrategia IN ({marcas}) '
        f'AND status IN ({finais}) ORDER BY concluida_em DESC, id DESC LIMIT ?',
        (str(cat_id), *ESTRATEGIAS, *banco.STATUS_FINAIS, JANELA_SATURACAO)).fetchall()


def saturada(con, cat_id):
    """True se as últimas 5 consultas encerradas da categoria trouxeram, cada uma, menos de 2% de itens novos
    (2% exato não satura). Com menos de 5 consultas, False."""
    ultimas = _consultas_da_categoria(con, _cat_id(cat_id))
    return len(ultimas) == JANELA_SATURACAO and all(
        novos == 0 or novos * 100 < LIMITE_NOVOS_PCT * vistos for vistos, novos in ultimas)


def bateu_teto(con, cat_id):
    """True se alguma consulta da categoria terminou no teto de páginas."""
    return con.execute("SELECT 1 FROM consultas WHERE cat_id = ? AND status = 'teto' LIMIT 1",
                       (str(_cat_id(cat_id)),)).fetchone() is not None


def _recusadas(con, cat_id):
    """Quantas consultas da categoria, das estratégias do motor, a API recusou de vez."""
    marcas = ', '.join('?' * len(ESTRATEGIAS))
    ids = con.execute(f"SELECT id FROM consultas WHERE cat_id = ? AND estrategia IN ({marcas}) AND status = 'erro'",
                      (str(cat_id), *ESTRATEGIAS)).fetchall()
    return sum(1 for (cid,) in ids if _erro_definitivo(con, cid))


def _encerrar(con, cat_id, status):
    """Grava a parada da categoria (só textos fixos e a contagem de recusadas) e devolve o status."""
    teto = 1 if bateu_teto(con, cat_id) else 0
    recusadas = _recusadas(con, cat_id)
    parada = PARADA[status] + ('; ' + PARADA['recusadas'].format(n=recusadas) if recusadas else '')
    con.execute('INSERT INTO categories (cat_id, saturada, bateu_teto, parada) VALUES (?, ?, ?, ?) '
                'ON CONFLICT (cat_id) DO UPDATE SET saturada = excluded.saturada, '
                'bateu_teto = excluded.bateu_teto, parada = excluded.parada',
                (str(cat_id), 1 if status == 'saturada' else 0, teto, parada))
    return status


# ---------- variáveis de cada estratégia ----------
def _valor_id(nome, valor, int64):
    """Id como a API pede: o tipo da variável vem da tabela `consultas.TIPOS`; Int64 segue o achados (`int64`),
    o resto vai como número."""
    return str(valor) if int64 == 'texto' and C.TIPOS[nome].startswith('Int64') else int(valor)


def _normalizar(texto):
    return ' '.join(unicodedata.normalize('NFC', texto).casefold().split())


def _bigramas_do_titulo(titulo):
    """Pares de palavras vizinhas (minúsculas); preposição e artigo quebram a vizinhança."""
    palavras = []
    for p in RE_PALAVRA.findall(_normalizar(titulo)):
        if p in PALAVRAS_VAZIAS or len(p) < 2 or p.isdigit():
            palavras.append(None)
        else:
            palavras.append(p)
    return [f'{a} {b}' for a, b in zip(palavras, palavras[1:]) if a and b and a != b]


def bigramas_da_categoria(con, cat_id):
    """Bigramas dos títulos dos produtos da categoria (em qualquer nível), com pelo menos `MIN_FREQ_BIGRAMA`
    títulos, do mais frequente ao menos (empate: ordem alfabética)."""
    cat = str(_cat_id(cat_id))
    contagem = collections.Counter()
    for (nome,) in con.execute('SELECT nome FROM products WHERE cat_l1 = ? OR cat_l2 = ? OR cat_l3 = ? LIMIT ?',
                               (cat, cat, cat, MAX_TITULOS)):
        if isinstance(nome, str):
            contagem.update(set(_bigramas_do_titulo(nome)))
    return [b for b, n in sorted(contagem.items(), key=lambda x: (-x[1], x[0])) if n >= MIN_FREQ_BIGRAMA]


def sementes_do_nicho(slug, caminho=None):
    """Sementes (keywords) do nicho no nichos.json, na ordem do arquivo. Slug ausente ou None → []."""
    try:
        with open(caminho or NICHOS, encoding='utf-8') as f:
            dados = json.load(f)
    except (OSError, ValueError):
        raise banco.ErroConfig('o nichos.json está ausente ou ilegível') from None
    if not isinstance(dados, list) or not all(isinstance(n, dict) for n in dados):
        raise banco.ErroConfig('o nichos.json está fora do formato')
    for n in dados:
        if n.get('slug') == slug and isinstance(slug, str):
            sementes = n.get('sementes')
            if not isinstance(sementes, list) or not all(isinstance(s, str) for s in sementes):
                raise banco.ErroConfig('o nichos.json está fora do formato')
            return list(sementes)
    return []


def _encerrada(con, variaveis, limit):
    """True se a consulta (variáveis sem page, mais o limit) já foi encerrada no banco."""
    linha = con.execute('SELECT status FROM consultas WHERE chave = ?',
                        (banco.chave_consulta(OPERACAO, {**variaveis, 'limit': limit}),)).fetchone()
    return linha is not None and linha[0] in banco.STATUS_FINAIS


def _fatias(con, cat_id, *, limit, int64, sementes):
    """Variáveis dos fatiamentos, uma de cada vez (o gerador é retomado depois de cada consulta, então os
    bigramas já contam o que a fatia anterior trouxe). Sementes primeiro, depois os bigramas; nenhuma
    palavra se repete e fatia já encerrada é pulada sem contar."""
    if not bateu_teto(con, cat_id):
        return
    fila = []
    for s in sementes:
        if isinstance(s, str):
            s = _normalizar(s)
            if s and len(s) <= MAX_KEYWORD and s not in fila:
                fila.append(s)
    usadas = set()
    feitas = con.execute("SELECT COUNT(*) FROM consultas WHERE cat_id = ? AND estrategia = 'fatiamento' "
                         "AND status IN ('esgotada', 'teto', 'saturada')", (str(cat_id),)).fetchone()[0]
    while feitas < MAX_FATIAS:
        candidatas = fila + bigramas_da_categoria(con, cat_id)
        palavra = next((p for p in candidatas if p not in usadas), None)
        if palavra is None:
            return
        usadas.add(palavra)
        variaveis = {'keyword': palavra, 'productCatId': _valor_id('productCatId', cat_id, int64), 'sortType': 1}
        if _encerrada(con, variaveis, limit):
            continue
        feitas += 1
        yield variaveis


def _plano(con, cat_id, ordem, *, limit, int64, list_types, sementes):
    """(estratégia, variáveis sem page nem limit) de cada consulta, na ordem pedida."""
    cat = _valor_id('productCatId', cat_id, int64)
    for estrategia in ordem:
        if estrategia == 'sort':
            for tipo in SORT_TYPES:
                yield estrategia, {'productCatId': cat, 'sortType': tipo}
        elif estrategia == 'listtype':
            for tipo in LIST_TYPES:
                if tipo in list_types:
                    yield estrategia, {'listType': tipo, 'matchId': _valor_id('matchId', cat_id, int64)}
        elif estrategia == 'ams_keyseller':
            yield estrategia, {'productCatId': cat, 'isAMSOffer': True}
            yield estrategia, {'productCatId': cat, 'isKeySeller': True}
        else:
            for variaveis in _fatias(con, cat_id, limit=limit, int64=int64, sementes=sementes):
                yield estrategia, variaveis


# ---------- uma categoria ----------
def garimpar_categoria(con, cli, cat, estrategias=None, *, limit, teto_pagina, paginas_sem_novo=3,
                       int64='texto', list_types=(), sementes=(), fase=FASE_PADRAO, log=None):
    """Roda as estratégias do brief na categoria `cat` e devolve 'saturada', 'teto' ou 'esgotada'.

    `estrategias`: lista de nomes de `ESTRATEGIAS` (None = a ordem do brief). `list_types`: os `listType`
    que o achados.json liberou (só 4 e 3 são usados). `sementes`: keywords do nicho (`sementes_do_nicho`).
    `log(mensagem)` recebe só ids, nomes de estratégia e contagens (nunca palavra de busca nem texto da API).
    Consulta recusada de vez pela API (`K.erro_permanente`) fica em `erro` e o motor segue para a próxima. Os outros
    erros do `Cliente` (Teto, LimiteAtingido, ErroApi transitório, RespostaInvalida) sobem; o que já foi gravado fica
    e a retomada continua.
    """
    cat_id = _cat_id(cat)
    ordem = _ordem(estrategias)
    if int64 not in ('numero', 'texto'):
        raise ValueError("int64 tem de ser 'numero' ou 'texto'")
    if (not isinstance(list_types, (list, tuple, set, frozenset))
            or not all(isinstance(t, int) and not isinstance(t, bool) for t in list_types)):
        raise ValueError('list_types tem de ser uma lista de inteiros')
    log = log or (lambda mensagem: None)
    if saturada(con, cat_id):
        log(f'categoria {cat_id}: já saturada.')
        return _encerrar(con, cat_id, 'saturada')
    for estrategia, variaveis in _plano(con, cat_id, ordem, limit=limit, int64=int64, list_types=list_types,
                                        sementes=sementes):
        try:
            r = paginar(con, cli, C.CONSULTA_PRODUTOS, variaveis, teto_pagina=teto_pagina, limit=limit,
                        paginas_sem_novo=paginas_sem_novo, fase=fase, estrategia=estrategia, cat_id=cat_id)
        except CS.ErroApi as e:
            if not K.erro_permanente(e.codigo, e.http):
                raise
            detalhe = f'código {e.codigo}' if e.codigo is not None else f'HTTP {e.http}'
            log(f'categoria {cat_id}: {estrategia}: consulta recusada pela API ({detalhe}); segue para a próxima.')
            continue
        log(f'categoria {cat_id}: {estrategia}: {r["paginas"]} páginas pedidas, {r["novos"]} itens novos, '
            f'{r["pulados"]} nós sem id válido pulados, consulta {r["status"]}.')
        if saturada(con, cat_id):
            return _encerrar(con, cat_id, 'saturada')
    return _encerrar(con, cat_id, 'teto' if bateu_teto(con, cat_id) else 'esgotada')
