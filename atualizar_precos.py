#!/usr/bin/env python3
"""Atualiza em lote os preços dos itens que já estão no achadinhos.db (nunca insere, nunca troca link de afiliado).

Uso:  python3 atualizar_precos.py amazon [--cat "<aba>"] [--produtos N]
      python3 atualizar_precos.py shopee --cat "<aba>"
      python3 atualizar_precos.py ml [--cat "<aba>"] [--vincular N] [--max-chamadas N]

Plano: docs/produto/planos/atualizar-precos.md, etapa 4 (CA2, CA4, CA5, CA10 e CA11); a fonte `ml` vem de
docs/produto/planos/api-oficial-ml-catalogo.md, etapa 3 (CA4, CA5 e CA8).

Ponto de troca (CA10): a seleção dos itens, a gravação e o resumo ficam aqui; cada loja é uma fonte em
`FONTES`. Uma fonte é `fonte(itens, opcoes)`: recebe `{item_id: linha}` e gera `(rotulo, [Observacao, ...])`,
uma vez por página lida. Quando chegar uma API oficial (PA-API, API do ML, consulta da Shopee por itemId),
entra uma fonte nova por id, e o resto não muda.

- Seleção: itens da loja nas abas (`--cat` ou todas as do buscas.json), com id no formato da loja (ASIN ou
  <shopId>.<itemId>) e cujo preço não foi confirmado hoje (preco_em de outro dia, nulo ou malformado).
- Gravação: só observação `ok` de item selecionado, com título e preço legível (servidor.ler_preco), pelo
  `servidor.upsert(..., inserir=False)`, com commit por página (no ml, por item: a releitura abre uma transação
  para cada um). Item sem preço legível não vai ao upsert
  (que apagaria o preço e zeraria o preco_em): conta como "sem preço" e mantém os dados antigos.
  Item que sumiu, ficou indisponível, caiu do piso ou virou usado não é gravado nem apagado: entra no resumo,
  o preço dele envelhece e a trava do disparo o tira de lá (CA5).
- Resumo: só contagens e até 20 ids (ASIN ou números); nada de título nem url.

Amazon (`fonte_amazon_busca`): para cada termo do buscas.json com item pendente, lê a página 1 da busca nas
ordens já marcadas em coleta_amazon_feitos.txt (relevância se não houver), com o mesmo piso (`passa_piso`) e
a mesma recusa de usado (`eh_usado`) da coleta; para o termo quando ele não tem mais item pendente. Com
`--produtos N` (0 a 500, padrão 0), abre depois a página do produto de até N itens não vistos e mais velhos que
a validade (config.preco_validade_horas), com pausa entre um e outro; a url é montada pelo ASIN, nunca lida do
banco. Captcha, 503 ou 429 param com saída 3.

Shopee (`fonte_shopee_api`): pela Open API, com `coletar_shopee.credenciais`/`buscar`/`no_para_item`/
`conferir_dono`. O link do dono é conferido antes da primeira gravação. Limite da API para com saída 3.
  Credenciais só no ambiente deste comando, num terminal só para isso, sem export:
    read -rs S; ACHADINHOS_SHOPEE_SECRET="$S" ACHADINHOS_SHOPEE_APP_ID=<id> python3 atualizar_precos.py shopee --cat ...; unset S
  O Secret é lido com pop e nunca vai para argumento, arquivo, saída ou mensagem de erro.

Mercado Livre (`fonte_ml_catalogo`): pela API oficial (ml_api.py), só pelo catálogo. O anúncio do banco se liga a um
produto de catálogo com prova (ml_api.vincular; cache em ml_catalogo.json, lido antes de qualquer gravação e gravado
a cada 20 vínculos novos); até --vincular itens (padrão 300, máximo 1000) sem vínculo no cache são vinculados por
rodada. O preço vem só da oferta do próprio anúncio (ml_api.ofertas_do_produto); título, nota, vendas, foto, frete e
cupom vêm do banco, relido logo antes de gravar (na mesma transação do upsert: o que o site ou o console mudar no
meio da rodada fica); só preco, preco_antigo e desconto mudam. Condição diferente de new ou título de usado: `usado`;
moeda diferente de BRL ou preço inválido (abaixo de R$ 0,01): `sem_preco`; vinculado mas fora do produto:
`indisponivel`; sem vínculo, com erro passageiro da API ou além do --vincular: não visto. Nenhum deles é gravado.
Teto de --max-chamadas GETs (padrão 3000, máximo 10000) com pausa de 0,3 a 0,8 s entre eles; o vínculo para de ligar
itens novos ao chegar à metade do teto (a outra metade fica para as ofertas); o teto e o 429 param com saída 3.
Tokens do `ml_api.py autorizar`; o Secret só é usado se o token precisar ser renovado:
    read -rs S; ACHADINHOS_ML_SECRET="$S" python3 atualizar_precos.py ml --cat ...; unset S
Premissa: uma máquina e um comando por vez (o arquivo de vínculos não tem trava).

Progresso por dia em atualizar_precos_feitos.txt (ACHADINHOS_FEITOS_ATUALIZAR troca o arquivo), linhas
`<loja>|<AAAA-MM-DD>|<ordem>|<termo>` (na página do produto, `<loja>|<AAAA-MM-DD>|produto|<ASIN>`; no ML,
`ml|<AAAA-MM-DD>|catalogo|<1º produto do lote>`, só registro: o ML retoma pelo preco_em). Rodar de novo
no mesmo dia retoma de onde parou. Não lê nem grava coleta_amazon_feitos.txt além de consultar as ordens.

Saída: 0 ok; 1 erro (dono errado, API recusou, resposta fora do formato, rede); 2 argumento ou configuração
(aba fora do buscas.json, ID de afiliado ou credenciais da Shopee; no ML, tokens ausentes ou recusados, falta do
Secret com o token vencido, renovação recusada, permissão do app ou arquivo de vínculos recusado); 3 bloqueio,
limite ou teto de chamadas (o progresso fica salvo).
"""
import argparse, contextlib, json, os, re, sys, unicodedata, urllib.error
from collections import Counter, namedtuple
from datetime import date, datetime
import servidor as S
import disparo as D

BASE = S.BASE
BUSCAS = os.path.join(BASE, 'buscas.json')
FEITOS = os.environ.get('ACHADINHOS_FEITOS_ATUALIZAR') or os.path.join(BASE, 'atualizar_precos_feitos.txt')
MAX_PRODUTOS = 500
MAX_IDS_RESUMO = 20
SITUACOES = ('ok', 'fora_do_piso', 'usado', 'indisponivel', 'sumiu', 'sem_preco')
# id do item que a fonte da loja sabe procurar (e que pode sair no resumo)
ID_DA_LOJA = {'amazon': re.compile(r'[A-Z0-9]{10}'), 'shopee': re.compile(r'[0-9]{1,20}\.[0-9]{1,20}'),
              'ml': re.compile(r'MLB[0-9]{6,19}')}
VINCULAR_PADRAO, MAX_VINCULAR = 300, 1000          # itens vinculados pela API por rodada (ml)
CHAMADAS_PADRAO, MAX_CHAMADAS = 3000, 10000        # teto de GETs por rodada (ml)
PRODUTOS_POR_LOTE = 20     # produtos de catálogo por página do ml (rótulo catalogo|<1º produto>)
VINCULOS_POR_GRAVACAO = 20  # vínculos novos entre duas gravações do ml_catalogo.json
PRECO_MIN_ML = 0.01        # abaixo disso o formatar_preco daria "R$ 0,00": sem preço
URL_ML = 'https://produto.mercadolivre.com.br/MLB-{}'   # a mesma forma do coletar_ml.js, montada pelo id
TENTATIVAS_PAGINA = 3   # às vezes a Amazon devolve uma página sem resultados (como no coletar_amazon)

# item_id e situacao (SITUACOES); `it` no formato do servidor.upsert, só quando a situação é 'ok'
Observacao = namedtuple('Observacao', 'item_id situacao it')
# marcador em `it` (fonte ml): o gravar_pagina relê a linha e troca só os CAMPOS_DO_PRECO sobre ela
RELER = 'reler'
CAMPOS_DO_PRECO = ('preco', 'preco_antigo', 'desconto')
TETO = 'teto'   # motivo do Bloqueio quando o teto de chamadas (--max-chamadas) foi atingido


class Bloqueio(Exception):
    """Captcha, 503 ou 429 da Amazon, limite da API da Shopee, ou 429 e teto de chamadas da API do ML: para com
    saída 3 e o progresso salvo. `motivo` é None (a loja bloqueou) ou TETO (o teto posto pelo dono)."""

    def __init__(self, motivo=None):
        super().__init__()
        self.motivo = motivo


class ArgInvalido(ValueError):
    pass


# ---------- progresso ----------
def hoje():
    return date.today().isoformat()


def feitos(loja, dia):
    """Rótulos (`<ordem>|<termo>`) já gravados hoje para a loja."""
    if not os.path.exists(FEITOS):
        return set()
    prefixo = f'{loja}|{dia}|'
    with open(FEITOS, encoding='utf-8') as f:
        return {l[len(prefixo):] for l in f.read().splitlines() if l.startswith(prefixo)}


def marcar(loja, dia, rotulo):
    with open(FEITOS, 'a', encoding='utf-8') as f:
        f.write(f'{loja}|{dia}|{rotulo}\n')


# ---------- seleção ----------
def ler_buscas():
    with open(BUSCAS, encoding='utf-8') as f:
        buscas = json.load(f)
    if not isinstance(buscas, dict):
        raise ArgInvalido('buscas.json fora do formato')
    return {k: [t for t in v if isinstance(t, str) and t] for k, v in buscas.items() if isinstance(v, list)}


def abas_escolhidas(cat):
    """{aba: termos} do buscas.json: só a `cat` (em NFC), ou todas sem ela. Aba desconhecida: ArgInvalido."""
    buscas = ler_buscas()
    if cat is None:
        return buscas
    cat = unicodedata.normalize('NFC', cat)
    if cat not in buscas:
        raise ArgInvalido('aba fora do buscas.json')
    return {cat: buscas[cat]}


def selecionar(con, loja, abas, dia):
    """({item_id: linha}, quantos já confirmados no dia) dos itens da loja nessas abas.

    Fica de fora o item cujo preço já foi confirmado no dia `dia` e o de id fora do formato da loja.
    "Confirmado no dia" usa o mesmo parse estrito da trava (disparo.ler_preco_em): preco_em malformado
    é velho e entra na seleção, qualquer que seja o prefixo.
    A linha traz também os S.CAMPOS. Na fonte ml ela só alimenta o vínculo (o título), o eh_usado e a montagem da
    observação: o que é gravado vem da linha relida no banco logo antes (RELER, em _gravar_relendo), com só os
    CAMPOS_DO_PRECO trocados.
    """
    if not abas:
        return {}, 0
    marcas = ','.join('?' * len(abas))
    colunas = ', '.join(['id', 'item_id', 'cat', 'busca', 'preco_em'] + S.CAMPOS)   # o preco vem nos CAMPOS
    linhas = con.execute(f'SELECT {colunas} FROM items '
                         f'WHERE loja=? AND cat IN ({marcas}) ORDER BY id', [loja, *abas]).fetchall()
    formato = ID_DA_LOJA[loja]
    itens, ja = {}, 0
    for r in linhas:
        if not isinstance(r['item_id'], str) or not formato.fullmatch(r['item_id']):
            continue
        quando = D.ler_preco_em(r['preco_em'])
        # R4: preço "do futuro" além da folga é velho para a trava; não conta como já confirmado hoje
        if (quando is not None and quando.date().isoformat() == dia
                and quando <= datetime.now() + D.FOLGA_FUTURO_PRECO):
            ja += 1
            continue
        itens[r['item_id']] = dict(r)
    return itens, ja


def termos_unicos(abas):
    vistos = []
    for termos in abas.values():
        for t in termos:
            if t not in vistos:
                vistos.append(t)
    return vistos


def por_termo(itens):
    grupos = {}
    for iid, linha in itens.items():
        grupos.setdefault(linha['busca'], set()).add(iid)
    return grupos


# ---------- orquestrador: seleção, gravação e resumo (CA10) ----------
def gravar_pagina(con, loja, itens, observacoes, estado):
    """Grava as observações `ok` de itens selecionados. Devolve quantos foram atualizados nesta página."""
    n = 0
    for obs in observacoes:
        iid = obs.item_id
        if iid not in itens or obs.situacao not in SITUACOES or estado.get(iid) == 'atualizado':
            continue
        if obs.situacao != 'ok':
            estado[iid] = obs.situacao
            continue
        it = obs.it
        if not isinstance(it, dict) or it.get('loja') != loja or it.get('item_id') != iid:
            raise ValueError('a fonte devolveu um item de outra loja ou de outro id')
        n += _gravar_relendo(con, it, estado) if it.get(RELER) else _gravar(con, it, estado)
    return n


def _gravar(con, it, estado):
    """Grava um item `ok` pelo upsert(inserir=False) e anota a situação em `estado`. Devolve 1 se atualizou."""
    iid, data = it['item_id'], it.get('data') or {}
    if not data.get('titulo'):
        estado[iid] = 'indisponivel'
        return 0
    if S.ler_preco(data.get('preco')) is None:
        estado[iid] = 'sem_preco'   # não vai ao upsert: o preço antigo e o preco_em ficam
        return 0
    r = S.upsert(con, it, inserir=False)
    estado[iid] = 'atualizado' if r == 'atualizado' else 'sumiu'   # 'ausente': excluído no meio do lote
    return int(estado[iid] == 'atualizado')


def _gravar_relendo(con, it, estado):
    """Como _gravar, mas sobre a linha de agora (S1): a rodada do ml dura horas e o upsert regrava todos os CAMPOS,
    então o título, o cupom ou a nota que o site ou o console mudaram depois da seleção voltariam ao valor velho.
    Relê os CAMPOS e grava só os CAMPOS_DO_PRECO de `it` sobre eles, dentro de um BEGIN IMMEDIATE com o upsert
    (nenhuma escrita entra entre a leitura e a gravação) e commit logo depois. Linha apagada: vai ao upsert como veio,
    que devolve 'ausente' sem gravar (conta `sumiu`). O marcador RELER não vai ao upsert."""
    it = {k: v for k, v in it.items() if k != RELER}
    if con.in_transaction:
        con.commit()
    con.execute('BEGIN IMMEDIATE')
    try:
        atual = con.execute(f'SELECT {", ".join(S.CAMPOS)} FROM items WHERE loja=? AND item_id=?',
                            (it['loja'], it['item_id'])).fetchone()
        if atual is not None:
            novo = it.get('data') or {}
            it = dict(it, data={**dict(atual), **{c: novo.get(c) for c in CAMPOS_DO_PRECO}})
        n = _gravar(con, it, estado)
        con.commit()
        return n
    except BaseException:
        con.rollback()
        raise


def atualizar(loja, abas, opcoes):
    """Roda a fonte da loja sobre os itens selecionados e devolve o resumo (dict).

    `opcoes` chega à fonte com `buscas` ({aba: termos}), `feitos` (rótulos de hoje), `agora` e `validade`
    acrescentados aqui. Bloqueio para o laço e marca `parou` no resumo; o que já foi gravado fica.
    """
    fonte = FONTES[loja]
    dia = hoje()
    con = S.conectar()
    try:
        itens, ja = selecionar(con, loja, list(abas), dia)
        opcoes = dict(opcoes, buscas=abas, feitos=feitos(loja, dia), agora=datetime.now(),
                      validade=D.validade_horas(con))
        estado, parou, motivo = {}, False, None
        try:
            for rotulo, observacoes in fonte({k: dict(v) for k, v in itens.items()}, opcoes):
                observacoes = list(observacoes)
                n = gravar_pagina(con, loja, itens, observacoes, estado)
                con.commit()
                if rotulo:
                    marcar(loja, dia, rotulo)
                    vistos = sum(1 for o in observacoes if o.item_id in itens)
                    print(f'[{loja}] {rotulo}: {vistos} dos selecionados vistos, {n} atualizados', flush=True)
        except Bloqueio as e:
            con.rollback()
            parou, motivo = True, e.motivo
    finally:
        con.close()
    contagem = {s: sum(1 for v in estado.values() if v == s)
                for s in ('atualizado', 'sem_preco', 'fora_do_piso', 'usado', 'indisponivel', 'sumiu')}
    nao_vistos = [iid for iid in itens if iid not in estado]
    return {'loja': loja, 'selecionados': len(itens), 'ja_hoje': ja, **contagem,
            'nao_vistos': len(nao_vistos), 'ids_nao_vistos': nao_vistos[:MAX_IDS_RESUMO], 'parou': parou,
            'motivo': motivo}


def texto_resumo(r):
    linhas = [f'RESUMO {r["loja"]}: {r["selecionados"]} selecionados ({r["ja_hoje"]} já confirmados hoje ficaram de fora); '
              f'{r["atualizado"]} atualizados, {r["sem_preco"]} sem preço legível (dados mantidos), '
              f'{r["fora_do_piso"]} fora do piso, {r["usado"]} usados, {r["indisponivel"]} indisponíveis, '
              f'{r["sumiu"]} sumidos, {r["nao_vistos"]} não vistos.']
    if r['ids_nao_vistos']:
        linhas.append(f'Não vistos (até {MAX_IDS_RESUMO}): ' + ', '.join(r['ids_nao_vistos']))
    return '\n'.join(linhas)


# ---------- fonte da Amazon: busca e, com --produtos, página do produto ----------
def _bloqueio_http(e):
    if isinstance(e, urllib.error.HTTPError) and e.code in (429, 503):
        e.close()
        return True
    return False


def _situacao_amazon(C, data):
    if C.eh_usado(data.get('titulo')):
        return 'usado'
    return 'ok' if C.passa_piso(data) else 'fora_do_piso'


def _observacao_amazon(C, asin, linha, data):
    sit = _situacao_amazon(C, data)
    it = {'loja': 'amazon', 'item_id': asin, 'cat': linha['cat'], 'busca': linha['busca'],
          'url': C.link_afiliado(asin), 'data': data} if sit == 'ok' else None
    return Observacao(asin, sit, it)


def ordens_amazon(C, termo, ja_coleta):
    """Ordens em que o termo foi coletado (coleta_amazon_feitos.txt), na ordem de C.ORDENS; relevância se nenhuma."""
    return [o for o in C.ORDENS if C.chave_busca(termo, o) in ja_coleta] or ['relevancia']


def fonte_amazon_busca(itens, opcoes):
    import coletar_amazon as C
    pendentes, grupos, feitos_hoje = set(itens), por_termo(itens), opcoes['feitos']
    ja_coleta = C.feitos()
    primeira = [True]

    def esperar(a=4, b=8):   # pausa entre uma requisição e outra (não antes da primeira)
        if not primeira[0]:
            C.pausa(a, b)
        primeira[0] = False

    def baixar(url):
        try:
            return C.baixar(url)[1]
        except C.Bloqueado:
            raise Bloqueio() from None
        except urllib.error.HTTPError as e:
            if _bloqueio_http(e):
                raise Bloqueio() from None
            e.close()
            raise

    for termo in termos_unicos(opcoes['buscas']):
        for ordem in ordens_amazon(C, termo, ja_coleta):
            if not grupos.get(termo, set()) & pendentes:
                break
            rotulo = f'{ordem}|{termo}'
            if rotulo in feitos_hoje:
                continue
            res = []
            for tentativa in range(TENTATIVAS_PAGINA):
                esperar(*((8, 15) if tentativa else (4, 8)))
                res = C.parse_busca(baixar(C.url_busca(termo, ordem)))   # a página inteira, sem o corte da coleta
                if res:
                    break
            if not res:
                print(f'[amazon] {rotulo}: sem resultados, fica para a próxima rodada', flush=True)
                continue
            obs = [_observacao_amazon(C, r['asin'], itens[r['asin']], r['data']) for r in res if r['asin'] in itens]
            pendentes -= {o.item_id for o in obs}
            yield rotulo, obs

    n = opcoes.get('produtos') or 0
    candidatos = sorted((iid for iid in pendentes
                         if not D.preco_recente(itens[iid]['preco_em'], opcoes['agora'], opcoes['validade'])
                         and f'produto|{iid}' not in feitos_hoje),
                        key=lambda iid: (itens[iid]['preco_em'] or '', iid))
    for asin in candidatos[:n]:
        esperar()
        yield f'produto|{asin}', [_observar_produto(C, asin, itens[asin])]


def _observar_produto(C, asin, linha):
    """Página do produto pelo link montado com o ASIN (nunca a url do banco)."""
    try:
        r = S.buscar_produto_amazon(C.link_afiliado(asin))
    except urllib.error.HTTPError as e:
        if _bloqueio_http(e):
            raise Bloqueio() from None
        e.close()
        if e.code in (404, 410):
            return Observacao(asin, 'sumiu', None)
        raise
    except S.URLRecusada:   # redirect para fora da Amazon
        return Observacao(asin, 'sumiu', None)
    if r.get('captcha'):
        raise Bloqueio()
    if r.get('asin') != asin or not r.get('titulo'):
        return Observacao(asin, 'sumiu', None)
    return _observacao_amazon(C, asin, linha, {c: r.get(c) or '' for c in S.CAMPOS})


# ---------- fonte da Shopee: Open API ----------
def _observacao_shopee(CS, no, termo, cat, itens):
    """Observação de um nó de productOfferV2, ou None se o nó não é de item selecionado."""
    if not isinstance(no, dict):
        return None
    shop, item = CS._inteiro(no.get('shopId')), CS._inteiro(no.get('itemId'))
    iid = f'{shop}.{item}'
    if not shop or not item or iid not in itens:
        return None
    it = CS.no_para_item(no, termo, cat)
    if it is not None and it['item_id'] == iid:
        return Observacao(iid, 'ok', it)
    if CS.eh_usado(CS._texto(no.get('productName'), S.MAX_TITULO)):
        return Observacao(iid, 'usado', None)
    if not CS.passa_piso(CS._numero(no.get('ratingStar')), CS._numero(no.get('sales'))):
        return Observacao(iid, 'fora_do_piso', None)
    return Observacao(iid, 'indisponivel', None)   # sem título ou sem link curto de afiliado


def fonte_shopee_api(itens, opcoes):
    import coletar_shopee as CS
    cred = opcoes['cred']
    (cat, termos), = opcoes['buscas'].items()   # o `shopee` exige --cat: uma aba só
    pendentes, grupos, feitos_hoje = set(itens), por_termo(itens), opcoes['feitos']
    ja_coleta, conferido, primeira = CS.feitos(), False, True
    for termo in termos:
        for ordem in [o for o in CS.ORDENS if CS.chave(o, termo) in ja_coleta] or ['relevancia']:
            if not grupos.get(termo, set()) & pendentes:
                break
            rotulo = f'{ordem}|{termo}'
            if rotulo in feitos_hoje:
                continue
            if not primeira:
                CS.pausa()
            primeira = False
            try:
                nos = CS.buscar(cred, termo, ordem)
            except CS.LimiteAtingido:
                raise Bloqueio() from None
            obs = [o for o in (_observacao_shopee(CS, n, termo, cat, itens) for n in nos) if o]
            oks = [o for o in obs if o.situacao == 'ok']
            if oks and not conferido:   # antes da primeira gravação: o link tem que ser do dono
                CS.conferir_dono(oks[0].it['url'])
                conferido = True
            pendentes -= {o.item_id for o in obs}
            yield rotulo, obs


# ---------- fonte do Mercado Livre: API oficial pelo catálogo ----------
def _observacao_ml(M, iid, linha, oferta):
    """Observação de um anúncio vinculado pela oferta dele (ofertas_do_produto). Só preco, preco_antigo e desconto
    vêm da API; o resto dos dados é o do banco, relido na gravação (RELER). A url é montada pelo id (o upsert mantém
    o meli.la)."""
    if oferta is None:
        return Observacao(iid, 'indisponivel', None)   # vinculado, mas o anúncio saiu do produto
    if oferta.condicao != 'new' or M.eh_usado(linha.get('titulo')):
        return Observacao(iid, 'usado', None)
    if not M.oferta_valida(oferta) or oferta.preco < PRECO_MIN_ML:
        return Observacao(iid, 'sem_preco', None)
    antigo, desconto = M.desconto(oferta.preco, oferta.preco_antigo)
    data = {c: linha.get(c) or '' for c in S.CAMPOS}
    data.update(preco=M.formatar_preco(oferta.preco), preco_antigo=antigo, desconto=desconto)
    return Observacao(iid, 'ok', {'loja': 'ml', 'item_id': iid, 'cat': linha['cat'], 'busca': linha['busca'],
                                  'url': URL_ML.format(iid[len('MLB'):]), 'data': data, RELER: True})


def _gravar_vinculos_no_erro(M, vinculos):
    """Guarda os vínculos novos quando a rodada para no meio. Uma falha aqui não troca o erro que parou a rodada
    (o vínculo perdido só é refeito pela API)."""
    with contextlib.suppress(M.ErroML, OSError):
        M.gravar_vinculos(vinculos)


def _vincular_ml(M, chamadas, itens, vinculos, dia, maximo, metade):
    """{pid: [item_id]} dos itens com vínculo provado, pelo cache ou pela API (até `maximo` itens sem vínculo no
    cache, na ordem da seleção, e só enquanto `chamadas.feitas` não chega a `metade`, para sobrar teto às ofertas).
    `vinculos` é o dict já lido por ler_vinculos; os novos vão para o arquivo a cada VINCULOS_POR_GRAVACAO e no fim.
    Erro passageiro de um item (ErroApi, RespostaInvalida) conta e segue, sem anotar nada; renovação recusada,
    limite, rede, autorização, permissão e teto param a rodada."""
    por_produto, conta, sujos = {}, Counter(), 0
    try:
        for iid, linha in itens.items():
            vinculo = M.vinculo_do_cache(vinculos, iid, dia)
            if vinculo is not None:
                conta['cache'] += 1
            elif conta['api'] >= maximo:
                conta['adiados'] += 1
                continue
            elif chamadas.feitas >= metade:
                conta['metade'] += 1   # não vistos nesta rodada
                continue
            else:
                conta['api'] += 1
                try:
                    vinculo = M.vincular(chamadas, iid, linha.get('titulo'), vinculos=vinculos, hoje=dia)
                except (M.RenovacaoFalhou, M.RenovacaoInvalida):
                    raise   # subclasses de ErroApi e RespostaInvalida: param a rodada (um POST com o Secret só)
                except (M.ErroApi, M.RespostaInvalida):
                    conta['erro'] += 1
                    continue
                sujos += 1
                if sujos >= VINCULOS_POR_GRAVACAO:
                    M.gravar_vinculos(vinculos)
                    sujos = 0
            pid = vinculo[0]
            if pid:
                por_produto.setdefault(pid, []).append(iid)
            else:
                conta['sem_produto'] += 1
    except BaseException:
        if sujos:
            _gravar_vinculos_no_erro(M, vinculos)
        raise
    if sujos:
        M.gravar_vinculos(vinculos)
    vinculados = sum(len(v) for v in por_produto.values())
    print(f'[ml] vínculos: {vinculados} itens em {len(por_produto)} produtos de catálogo, {conta["sem_produto"]} sem '
          f'produto; {conta["cache"]} vieram do cache e {conta["api"]} foram à API ({conta["erro"]} com erro '
          f'passageiro); {conta["adiados"]} ficam para a próxima rodada (--vincular {maximo}).', flush=True)
    if conta['metade']:
        print(f'[ml] vínculo parou na metade do teto; {conta["metade"]} itens ficam para a próxima rodada.', flush=True)
    return por_produto


def _ofertas_ml(M, chamadas, itens, por_produto):
    """Uma página por lote de PRODUTOS_POR_LOTE produtos: ('catalogo|<1º pid>', [Observacao]). Erro passageiro de
    um produto deixa os anúncios dele sem observação (não vistos) e segue; o resto para a rodada."""
    pids, erros = sorted(por_produto), 0
    for inicio in range(0, len(pids), PRODUTOS_POR_LOTE):
        lote, obs = pids[inicio:inicio + PRODUTOS_POR_LOTE], []
        for pid in lote:
            ids = por_produto[pid]
            try:
                ofertas = M.ofertas_do_produto(chamadas, pid, ids)
            except (M.RenovacaoFalhou, M.RenovacaoInvalida):
                raise
            except (M.ErroApi, M.RespostaInvalida):
                erros += len(ids)
                continue
            obs.extend(_observacao_ml(M, iid, itens[iid], ofertas.get(iid)) for iid in ids)
        yield f'catalogo|{lote[0]}', obs
    if erros:
        print(f'[ml] ofertas: {erros} anúncios ficaram sem leitura por erro passageiro da API (não vistos).', flush=True)


def fonte_ml_catalogo(itens, opcoes):
    """Preço pela API oficial do ML, só pelo catálogo (ver a docstring do módulo). `opcoes` traz a `sessao`
    (ml_api.Sessao), `vincular`, `max_chamadas` e `vinculos` (o dict de ml_api.ler_vinculos, lido pelo _rodar_ml antes
    de abrir o banco; sem ele, é lido aqui). Toda chamada passa pela vista com teto e pausa (ml_api.com_teto).
    Retomada pelo preco_em de hoje: o item atualizado sai da seleção; o rótulo do lote é só registro."""
    import ml_api as M
    maximo = opcoes.get('max_chamadas', CHAMADAS_PADRAO)
    # sempre antes de qualquer gravação; arquivo recusado: saída 2, nada gravado
    vinculos = opcoes['vinculos'] if 'vinculos' in opcoes else M.ler_vinculos()
    with M.com_teto(opcoes['sessao'], maximo) as chamadas:
        try:
            por_produto = _vincular_ml(M, chamadas, itens, vinculos, opcoes['agora'].date().isoformat(),
                                       opcoes.get('vincular', VINCULAR_PADRAO), maximo // 2)
            yield from _ofertas_ml(M, chamadas, itens, por_produto)
        except M.Limite:
            raise Bloqueio() from None
        except M.TetoAtingido:
            print(f'[ml] parou no teto de {maximo} chamadas (--max-chamadas); rode de novo para seguir.', flush=True)
            raise Bloqueio(TETO) from None


FONTES = {'amazon': fonte_amazon_busca, 'shopee': fonte_shopee_api, 'ml': fonte_ml_catalogo}


# ---------- linha de comando ----------
def _produtos(texto):
    if not re.fullmatch(r'[0-9]{1,3}', texto, re.A) or int(texto) > MAX_PRODUTOS:
        raise argparse.ArgumentTypeError(f'use um número de 0 a {MAX_PRODUTOS}')
    return int(texto)


def _inteiro_de(minimo, maximo):
    def ler(texto):
        if not re.fullmatch(r'[0-9]{1,5}', texto, re.A) or not minimo <= int(texto) <= maximo:
            raise argparse.ArgumentTypeError(f'use um número de {minimo} a {maximo}')
        return int(texto)
    return ler


def ler_argumentos(argv):
    p = argparse.ArgumentParser(prog='atualizar_precos.py',
                                description='Atualiza os preços dos itens que já estão no banco (não insere).')
    sub = p.add_subparsers(dest='loja', required=True)
    a = sub.add_parser('amazon', help='pela busca da Amazon (e, com --produtos, pela página do produto)')
    a.add_argument('--cat', help='só os itens desta aba do buscas.json')
    a.add_argument('--produtos', type=_produtos, default=0,
                   help=f'abre a página do produto de até N itens não vistos e velhos (0 a {MAX_PRODUTOS}, padrão 0)')
    s = sub.add_parser('shopee', help='pela Open API de afiliados (credenciais só no ambiente do comando)')
    s.add_argument('--cat', required=True, help='aba do buscas.json')
    m = sub.add_parser('ml', help='pela API oficial do Mercado Livre, só pelo catálogo (tokens do ml_api.py autorizar)')
    m.add_argument('--cat', help='só os itens desta aba do buscas.json')
    m.add_argument('--vincular', type=_inteiro_de(0, MAX_VINCULAR), default=VINCULAR_PADRAO,
                   help=f'itens sem vínculo no cache ligados ao catálogo pela API nesta rodada (0 a {MAX_VINCULAR}, '
                        f'padrão {VINCULAR_PADRAO})')
    m.add_argument('--max-chamadas', type=_inteiro_de(1, MAX_CHAMADAS), default=CHAMADAS_PADRAO,
                   help=f'teto de chamadas à API nesta rodada (1 a {MAX_CHAMADAS}, padrão {CHAMADAS_PADRAO}); '
                        'abaixo de 40 pode não fechar nenhum lote de ofertas e a rodada não avança')
    args = p.parse_args(argv)
    try:
        args.abas = abas_escolhidas(args.cat)
    except ArgInvalido as e:
        p.error(str(e))
    return args


def _resultado(resumo):
    print(texto_resumo(resumo), flush=True)
    if resumo['parou'] and resumo.get('motivo') == TETO:
        print('PAROU: chegou ao teto de chamadas (--max-chamadas); rode de novo para seguir, sem precisar esperar.',
              file=sys.stderr, flush=True)
        return 3
    if resumo['parou']:
        print('PAROU: a loja bloqueou (captcha, 503, 429 ou limite da API). O progresso foi salvo; '
              'espere de 15 a 30 minutos e rode de novo.', file=sys.stderr, flush=True)
        return 3
    return 0


def _rodar_amazon(args):
    S.criar_banco()
    return _resultado(atualizar('amazon', args.abas, {'produtos': args.produtos}))


def _rodar_shopee(args):
    import coletar_shopee as CS
    if not CS.id_afiliado_ok():
        print('ERRO: preencha ID_AFILIADO_SHOPEE no coletar_shopee.py.', file=sys.stderr, flush=True)
        return 2
    cred = CS.credenciais()   # pop do Secret: sai do ambiente deste processo
    if cred is None:
        print('ERRO: defina ACHADINHOS_SHOPEE_APP_ID e ACHADINHOS_SHOPEE_SECRET só para este comando, sem export, '
              'num terminal só para isso: read -rs S; ACHADINHOS_SHOPEE_SECRET="$S" '
              'ACHADINHOS_SHOPEE_APP_ID=<id> python3 atualizar_precos.py shopee --cat ...; unset S',
              file=sys.stderr, flush=True)
        return 2
    try:
        S.criar_banco()
        return _resultado(atualizar('shopee', args.abas, {'cred': cred}))
    except CS.DonoErrado:
        print(f'PAROU: o link gerado não leva a utm_source=an_{CS.ID_AFILIADO_SHOPEE}. Nada foi gravado. '
              'Confira as credenciais e o ID_AFILIADO_SHOPEE.', file=sys.stderr, flush=True)
        return 1
    except CS.ErroApi as e:
        detalhe = ', '.join(x for x in (f'código {e.codigo}' if e.codigo is not None else '',
                                        f'HTTP {e.http}' if e.http is not None else '') if x)
        print(f'ERRO: a API da Shopee recusou ({detalhe or "sem código"}).', file=sys.stderr, flush=True)
        return 1
    except CS.RespostaInvalida:
        print('ERRO: resposta da API da Shopee fora do formato esperado.', file=sys.stderr, flush=True)
        return 1


MSG_SECRET_ML = ('o acesso ao Mercado Livre venceu e precisa ser renovado com o Secret do app '
                 '(ACHADINHOS_ML_SECRET). Num terminal só para isso, sem export: read -rs S; ACHADINHOS_ML_SECRET="$S" '
                 'python3 atualizar_precos.py ml [--cat ...]; unset S')


def _rodar_ml(args):
    import ml_api as M
    sessao = M.sessao_do_ambiente()   # pop do Secret: sai do ambiente deste processo
    try:
        # tokens antes do banco: sem arquivo, sem o Secret com o token vencido ou com a renovação recusada, para aqui
        # (o Secret só é usado se o token precisar ser renovado)
        sessao.token()
        # vínculos antes do banco: arquivo recusado sai com 2 sem abrir nem migrar o banco
        vinculos = M.ler_vinculos()
        S.criar_banco()
        return _resultado(atualizar('ml', args.abas, {'sessao': sessao, 'vincular': args.vincular,
                                                      'max_chamadas': args.max_chamadas, 'vinculos': vinculos}))
    except M.ConfigFaltando as e:
        print(f'ERRO: {e if isinstance(e, M.TokensRecusados) else MSG_SECRET_ML}', file=sys.stderr, flush=True)
        return e.saida
    except M.ErroML as e:   # mensagens fixas do ml_api, com status e código filtrados
        print(f'{"PAROU" if e.saida == 3 else "ERRO"}: {e}', file=sys.stderr, flush=True)
        return e.saida


def main(argv=None):
    args = ler_argumentos(sys.argv[1:] if argv is None else argv)
    try:
        if args.loja == 'ml':
            return _rodar_ml(args)
        return _rodar_shopee(args) if args.loja == 'shopee' else _rodar_amazon(args)
    except KeyboardInterrupt:
        print('Interrompido. O progresso das páginas já gravadas foi salvo.', file=sys.stderr, flush=True)
        return 130
    except Exception as e:   # só o tipo: a mensagem de biblioteca pode trazer a requisição ou a query
        print(f'ERRO: {type(e).__name__}', file=sys.stderr, flush=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())
