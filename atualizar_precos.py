#!/usr/bin/env python3
"""Atualiza em lote os preços dos itens que já estão no achadinhos.db (nunca insere, nunca troca link de afiliado).

Uso:  python3 atualizar_precos.py amazon [--cat "<aba>"] [--produtos N]
      python3 atualizar_precos.py shopee --cat "<aba>"

Plano: docs/produto/planos/atualizar-precos.md, etapa 4 (CA2, CA4, CA5, CA10 e CA11).

Ponto de troca (CA10): a seleção dos itens, a gravação e o resumo ficam aqui; cada loja é uma fonte em
`FONTES`. Uma fonte é `fonte(itens, opcoes)`: recebe `{item_id: linha}` e gera `(rotulo, [Observacao, ...])`,
uma vez por página lida. Quando chegar uma API oficial (PA-API, API do ML, consulta da Shopee por itemId),
entra uma fonte nova por id, e o resto não muda.

- Seleção: itens da loja nas abas (`--cat` ou todas as do buscas.json), com id no formato da loja (ASIN ou
  <shopId>.<itemId>) e cujo preço não foi confirmado hoje (preco_em de outro dia, nulo ou malformado).
- Gravação: só observação `ok` de item selecionado, com título e preço legível (servidor.ler_preco), pelo
  `servidor.upsert(..., inserir=False)`, com commit por página. Item sem preço legível não vai ao upsert
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

Progresso por dia em atualizar_precos_feitos.txt (ACHADINHOS_FEITOS_ATUALIZAR troca o arquivo), linhas
`<loja>|<AAAA-MM-DD>|<ordem>|<termo>` (na página do produto, `<loja>|<AAAA-MM-DD>|produto|<ASIN>`). Rodar de novo
no mesmo dia retoma de onde parou. Não lê nem grava coleta_amazon_feitos.txt além de consultar as ordens.

Saída: 0 ok; 1 erro (dono errado, API recusou, resposta fora do formato); 2 argumento ou configuração
(aba fora do buscas.json, ID de afiliado ou credenciais da Shopee); 3 bloqueio ou limite (o progresso fica salvo).
"""
import argparse, json, os, re, sys, unicodedata, urllib.error
from collections import namedtuple
from datetime import date, datetime
import servidor as S
import disparo as D

BASE = S.BASE
BUSCAS = os.path.join(BASE, 'buscas.json')
FEITOS = os.environ.get('ACHADINHOS_FEITOS_ATUALIZAR') or os.path.join(BASE, 'atualizar_precos_feitos.txt')
MAX_PRODUTOS = 500
MAX_IDS_RESUMO = 20
SITUACOES = ('ok', 'fora_do_piso', 'usado', 'indisponivel', 'sumiu')
# id do item que a fonte da loja sabe procurar (e que pode sair no resumo)
ID_DA_LOJA = {'amazon': re.compile(r'[A-Z0-9]{10}'), 'shopee': re.compile(r'[0-9]{1,20}\.[0-9]{1,20}')}
TENTATIVAS_PAGINA = 3   # às vezes a Amazon devolve uma página sem resultados (como no coletar_amazon)

# item_id e situacao (SITUACOES); `it` no formato do servidor.upsert, só quando a situação é 'ok'
Observacao = namedtuple('Observacao', 'item_id situacao it')


class Bloqueio(Exception):
    """Captcha, 503 ou 429 da Amazon, ou limite da API da Shopee: para com saída 3 e o progresso salvo."""


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
    """
    if not abas:
        return {}, 0
    marcas = ','.join('?' * len(abas))
    linhas = con.execute(f'SELECT id, item_id, cat, busca, preco, preco_em FROM items '
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
        data = it.get('data') or {}
        if not data.get('titulo'):
            estado[iid] = 'indisponivel'
            continue
        if S.ler_preco(data.get('preco')) is None:
            estado[iid] = 'sem_preco'   # não vai ao upsert: o preço antigo e o preco_em ficam
            continue
        r = S.upsert(con, it, inserir=False)
        estado[iid] = 'atualizado' if r == 'atualizado' else 'sumiu'   # 'ausente': excluído no meio do lote
        n += estado[iid] == 'atualizado'
    return n


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
        estado, parou = {}, False
        try:
            for rotulo, observacoes in fonte({k: dict(v) for k, v in itens.items()}, opcoes):
                observacoes = list(observacoes)
                n = gravar_pagina(con, loja, itens, observacoes, estado)
                con.commit()
                if rotulo:
                    marcar(loja, dia, rotulo)
                    vistos = sum(1 for o in observacoes if o.item_id in itens)
                    print(f'[{loja}] {rotulo}: {vistos} dos selecionados vistos, {n} atualizados', flush=True)
        except Bloqueio:
            con.rollback()
            parou = True
    finally:
        con.close()
    contagem = {s: sum(1 for v in estado.values() if v == s)
                for s in ('atualizado', 'sem_preco', 'fora_do_piso', 'usado', 'indisponivel', 'sumiu')}
    nao_vistos = [iid for iid in itens if iid not in estado]
    return {'loja': loja, 'selecionados': len(itens), 'ja_hoje': ja, **contagem,
            'nao_vistos': len(nao_vistos), 'ids_nao_vistos': nao_vistos[:MAX_IDS_RESUMO], 'parou': parou}


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


FONTES = {'amazon': fonte_amazon_busca, 'shopee': fonte_shopee_api}


# ---------- linha de comando ----------
def _produtos(texto):
    if not re.fullmatch(r'[0-9]{1,3}', texto, re.A) or int(texto) > MAX_PRODUTOS:
        raise argparse.ArgumentTypeError(f'use um número de 0 a {MAX_PRODUTOS}')
    return int(texto)


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
    args = p.parse_args(argv)
    try:
        args.abas = abas_escolhidas(args.cat)
    except ArgInvalido as e:
        p.error(str(e))
    return args


def _resultado(resumo):
    print(texto_resumo(resumo), flush=True)
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


def main(argv=None):
    args = ler_argumentos(sys.argv[1:] if argv is None else argv)
    try:
        return _rodar_shopee(args) if args.loja == 'shopee' else _rodar_amazon(args)
    except KeyboardInterrupt:
        print('Interrompido. O progresso das páginas já gravadas foi salvo.', file=sys.stderr, flush=True)
        return 130
    except Exception as e:   # só o tipo: a mensagem de biblioteca pode trazer a requisição ou a query
        print(f'ERRO: {type(e).__name__}', file=sys.stderr, flush=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())
