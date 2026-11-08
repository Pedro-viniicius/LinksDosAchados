#!/usr/bin/env python3
"""API de ofertas v1 para o Achadinho Turbo (docs/produto/planos/api-achadinho-turbo.md, etapa 1).

Só leitura: monta as ofertas (sempre com link de afiliado da própria loja) e as categorias a partir
da tabela `items`. Não fala HTTP: o servidor.py confere Host, token e método e chama `rota`, que
devolve o objeto da resposta ou levanta `ErroApi` (código HTTP e frase em português).

Só biblioteca padrão. Não importa `servidor` (mesmo padrão do disparo.py): quem chama passa a
conexão e o `eh_afiliado` (o eh_link_afiliado do servidor). Nada é gravado e não há migração.
O público (`genero`) vem do genero.py (docs/produto/planos/genero-nas-categorias.md, etapa 5): a
correção manual é só lida (tabela `generos_manuais`; banco sem ela dá tudo automático).
A idade do preço (`preco_em` e o filtro `preco_max_horas`) é da etapa 3 de
docs/produto/planos/atualizar-precos.md: a coluna items.preco_em vem da migração v3 do disparo.py.
"""
import math
import re
from datetime import datetime, timedelta

import disparo as D
import genero as G

PREFIXO = '/api/v1/'
VERSAO = 1
# Na ordem "atualizacao", item gravado há menos que isso fica para a próxima leitura: as coletas
# fazem commit por lote, em segundos, e o cursor não pode passar por um lote ainda aberto.
FOLGA = timedelta(seconds=60)
LIMITE_PADRAO, LIMITE_MAX = 50, 200
MAX_CATS, MAX_CAT = 20, 200
MAX_Q, MAX_TERMOS = 200, 10
ORDENS = ('atualizacao', 'relevancia', 'desconto', 'menor_preco', 'maior_preco', 'cupom', 'recentes')
PARAMETROS = ('cat', 'loja', 'q', 'desconto_min', 'ordem', 'limite', 'cursor', 'genero', 'preco_max_horas')
REPETIVEIS = ('cat', 'loja', 'genero')
# Pedido válido tem no máximo 20 cat + 3 loja + 4 genero + 6 parâmetros; acima disso nem vale olhar.
MAX_PARES = MAX_CATS + len(D.LOJAS) + len(G.GENEROS) + len(PARAMETROS) - len(REPETIVEIS)
# Horário como o servidor grava (datetime.isoformat(timespec='seconds')): ISO local, sem fuso.
_HORA = '[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}'
_RE_HORA = re.compile(_HORA)
# Cursores (opacos para o cliente, conferidos aqui com fullmatch): "<atualizado_em>~<id>" na ordem
# "atualizacao" e "<deslocamento>" nas demais. Só dígitos ASCII; o id cabe no INTEGER do sqlite.
_RE_CURSOR_ATUALIZACAO = re.compile(f'({_HORA})~([1-9][0-9]{{0,17}})')
_RE_CURSOR_DESLOCAMENTO = re.compile('[1-9][0-9]{0,8}')
_RE_INTEIRO = re.compile('[0-9]{1,3}')
# Colunas de texto da linha que entram na oferta (as de dados vêm do disparo.CAMPOS_ITEM).
_TEXTOS = ('loja', 'item_id', 'cat', 'busca', 'url', 'criado_em', 'atualizado_em') + D.CAMPOS_ITEM
_SQL_BASE = "SELECT * FROM items WHERE tem_dados=1 AND titulo!='' AND preco!=''"


class ErroApi(Exception):
    """Pedido recusado (400, 404, 405). A mensagem nunca traz o valor enviado pelo cliente."""
    def __init__(self, codigo, msg):
        super().__init__(msg)
        self.codigo, self.msg = codigo, msg


def _invalido(msg):
    return ErroApi(400, msg)


def _numero_ok(v):
    return math.isfinite(v) and v > 0


def _preco_em(v):
    """items.preco_em como sai na oferta: o texto, se o disparo.ler_preco_em o aceita (a mesma regra da
    trava: formato AAAA-MM-DDTHH:MM:SS estrito, hora de 00 a 23, data que existe); senão None (nulo, BLOB,
    "03/11/2026", 2026-02-30, T24:00:00). Data no futuro sai como texto: o campo só mostra a data, quem
    decide se o preço é velho é o filtro preco_max_horas. Nunca tira a oferta da lista: sem o filtro, a
    resposta é a de antes mais este campo (P2 do plano atualizar-precos)."""
    return v if D.ler_preco_em(v) is not None else None


def _tem_preco_em(con):
    """True se items já tem a coluna preco_em (migração v3). O servidor migra na subida, mas um banco
    anterior lido direto (um retrato de antes da v3) não tem: lá nenhuma oferta tem data de preço."""
    return any(r[1] == 'preco_em' for r in con.execute('PRAGMA table_info(items)'))


def oferta(row, eh_afiliado, manuais=None):
    """A linha de `items` no formato da oferta v1, ou None se ela não pode sair (CA2).

    Sai só com: tem_dados=1, loja conhecida, título, preço numérico finito > 0, horários no
    formato do servidor, link de afiliado da própria loja (disparo.link_da_loja_ok) e nenhuma
    candidata a link (disparo.urls_da_mensagem) no título, no cupom, na categoria, na busca ou no
    item_id (que pode ser o próprio link). A imagem fora do CDN da loja vira None. `preco_em` (_preco_em)
    não entra nessas condições: fora do formato, vira None.

    `genero` (genero.do_item) só é calculado depois de todas essas condições: o filtro por público
    nunca traz uma linha que não sairia sem ele. `manuais` é o genero.manuais(con), lido uma vez por
    pedido; None (quem chama com 2 argumentos) vale como nenhuma correção.
    """
    if row['tem_dados'] != 1:
        return None
    t = {}
    for c in _TEXTOS:
        v = '' if row[c] is None else row[c]
        if not isinstance(v, str):   # o sqlite aceita qualquer tipo numa coluna TEXT
            return None
        t[c] = v
    if t['loja'] not in D.LOJAS or not t['titulo'].strip():
        return None
    if not D.link_da_loja_ok(t['loja'], t['url'], eh_afiliado):
        return None
    if not (_RE_HORA.fullmatch(t['criado_em']) and _RE_HORA.fullmatch(t['atualizado_em'])):
        return None   # o cursor da ordem "atualizacao" precisa do horário no formato conhecido
    if any(D.urls_da_mensagem(t[c]) for c in ('titulo', 'cupom', 'cat', 'busca')):
        return None
    if t['item_id'] != t['url'] and D.urls_da_mensagem(t['item_id']):
        return None

    # R1: texto numérico gigante (o coletar_amazon.py não aplica o teto de 200 caracteres) faz as
    # conversões levantarem OverflowError (inf * 1000 no "mil") ou ValueError (int com mais de ~4.300
    # dígitos). A linha fica fora, e não derruba o pedido inteiro. São as mesmas funções e campos que
    # o disparo.ordenar recalcula, então item que passa aqui também passa lá.
    try:
        preco = D.preco_num(t['preco'])
        if not _numero_ok(preco):   # "consulte", vazio, zero ou dígitos demais (inf)
            return None
        antigo = D.preco_num(t['preco_antigo'])
        preco_antigo = antigo if _numero_ok(antigo) and antigo > preco else None
        desconto = D.pct(t['desconto'])
        if desconto == 0 and preco_antigo:
            # o Turbo usa discountPct ?? (cálculo próprio): mandar 0 apagaria o desconto
            desconto = round((1 - preco / preco_antigo) * 100)
        avaliacao = D.nota(t['avaliacao'])
        vendas, num_avaliacoes = D.contagem(t['vendas']), D.contagem(t['num_avaliacoes'])
    except (ValueError, OverflowError):
        return None
    publico, _origem = G.do_item(row['id'], t['cat'], t['busca'], t['titulo'], manuais)
    try:
        preco_em = _preco_em(row['preco_em'])
    except IndexError:   # banco de antes da v3 (_tem_preco_em)
        preco_em = None
    return {
        'id': row['id'], 'chave': f"{t['loja']}:{t['item_id']}", 'loja': t['loja'], 'item_id': t['item_id'],
        'categoria': t['cat'], 'busca': t['busca'], 'titulo': t['titulo'], 'link': t['url'],
        'imagem': D.foto_grande(t['imagem'], t['loja']) if D.imagem_permitida(t['imagem'], t['loja']) else None,
        'preco': preco, 'preco_antigo': preco_antigo, 'desconto_pct': desconto,
        'vendas': vendas,
        'avaliacao': avaliacao if _numero_ok(avaliacao) else None,
        'num_avaliacoes': num_avaliacoes,
        'frete_gratis': 'gratis' in D._sem_acento(t['frete']),
        'cupom': t['cupom'], 'criado_em': t['criado_em'], 'atualizado_em': t['atualizado_em'],
        'genero': publico, 'preco_em': preco_em,
    }


def _inteiro(valor, nome, minimo, maximo):
    if not _RE_INTEIRO.fullmatch(valor) or not minimo <= int(valor) <= maximo:
        raise _invalido(f'{nome} deve ser um número inteiro de {minimo} a {maximo}')
    return int(valor)


def filtros(pares):
    """Confere os parâmetros da query (a lista do parse_qsl, para enxergar repetição). ErroApi 400.

    Devolve {'cats', 'lojas', 'generos', 'termos', 'desconto_min', 'ordem', 'limite', 'cursor',
    'preco_max_horas'}; `termos` já vem sem acento e sem caixa; `cursor` é None, (atualizado_em, id) ou
    o deslocamento (int); `preco_max_horas` é None (sem filtro, o padrão) ou o int de 1 a 168.
    """
    pares = list(pares or ())
    if len(pares) > MAX_PARES:
        raise _invalido('parâmetros demais')
    vistos = {}
    for par in pares:
        if not (isinstance(par, tuple) and len(par) == 2 and all(isinstance(x, str) for x in par)):
            raise _invalido('parâmetros malformados')
        nome, valor = par
        if nome not in PARAMETROS:
            raise _invalido('parâmetro desconhecido (use ' + ', '.join(PARAMETROS) + ')')
        if nome in vistos and nome not in REPETIVEIS:
            raise _invalido(f'o parâmetro {nome} só pode aparecer uma vez')
        vistos.setdefault(nome, []).append(valor)

    cats = vistos.get('cat', [])
    if len(cats) > MAX_CATS:
        raise _invalido(f'no máximo {MAX_CATS} categorias')
    if not all(1 <= len(c) <= MAX_CAT for c in cats):
        raise _invalido(f'cada categoria deve ter de 1 a {MAX_CAT} caracteres')
    if len(set(cats)) != len(cats):
        raise _invalido('categorias repetidas')

    lojas = vistos.get('loja', [])
    if not all(l in D.LOJAS for l in lojas) or len(set(lojas)) != len(lojas):
        raise _invalido('loja deve ser ' + ', '.join(D.LOJAS) + ', sem repetir')

    generos = vistos.get('genero', [])
    if not all(g in G.GENEROS for g in generos) or len(set(generos)) != len(generos):
        raise _invalido('genero deve ser ' + ', '.join(G.GENEROS) + ', sem repetir')

    termos = []
    if 'q' in vistos:
        q = vistos['q'][0]
        if len(q) > MAX_Q:
            raise _invalido(f'q deve ter até {MAX_Q} caracteres')
        termos = [p.strip() for p in q.split(',')]
        if len(termos) > MAX_TERMOS:
            raise _invalido(f'q aceita até {MAX_TERMOS} termos separados por vírgula')
        if not all(termos):
            raise _invalido('cada termo de q (separados por vírgula) precisa ter texto')
        termos = [D._sem_acento(p) for p in termos]

    desconto_min = _inteiro(vistos['desconto_min'][0], 'desconto_min', 0, 99) if 'desconto_min' in vistos else 0
    limite = _inteiro(vistos['limite'][0], 'limite', 1, LIMITE_MAX) if 'limite' in vistos else LIMITE_PADRAO
    # mesma faixa da validade do disparo (config.preco_validade_horas), mas aqui só vale se pedirem
    preco_max_horas = (_inteiro(vistos['preco_max_horas'][0], 'preco_max_horas', D.VALIDADE_MIN_HORAS,
                                D.VALIDADE_MAX_HORAS) if 'preco_max_horas' in vistos else None)

    ordem = vistos.get('ordem', ['atualizacao'])[0]
    if ordem == 'aleatoria':
        raise _invalido('a ordem aleatoria não existe na API: ela não pagina (use outra ordem)')
    if ordem not in ORDENS:
        raise _invalido('ordem inválida (use ' + ', '.join(ORDENS) + ')')

    cursor = None
    if 'cursor' in vistos:
        bruto = vistos['cursor'][0]
        if ordem == 'atualizacao':
            m = _RE_CURSOR_ATUALIZACAO.fullmatch(bruto)
            cursor = (m.group(1), int(m.group(2))) if m else None
        else:
            cursor = int(bruto) if _RE_CURSOR_DESLOCAMENTO.fullmatch(bruto) else None
        if cursor is None:
            raise _invalido('cursor inválido: use o valor de "proximo" da página anterior, com a mesma ordem')

    return {'cats': cats, 'lojas': lojas, 'generos': generos, 'termos': termos, 'desconto_min': desconto_min,
            'ordem': ordem, 'limite': limite, 'cursor': cursor, 'preco_max_horas': preco_max_horas}


def _casa(o, f, agora):
    """Filtros que dependem da oferta pronta: genero (exato: qualquer um dos pedidos), preco_max_horas
    (disparo.preco_recente, a mesma regra da trava do disparo: preco_em nulo ou malformado não passa),
    q (basta um termo no título) e desconto_min."""
    if f['generos'] and o['genero'] not in f['generos']:
        return False
    if f['preco_max_horas'] is not None and not D.preco_recente(o['preco_em'], agora, f['preco_max_horas']):
        return False
    if o['desconto_pct'] < f['desconto_min']:
        return False
    if f['termos']:
        titulo = D._sem_acento(o['titulo'])
        return any(p in titulo for p in f['termos'])
    return True


def listar(con, f, eh_afiliado, agora):
    """GET /api/v1/ofertas com os filtros já conferidos por `filtros` (CA1 a CA4).

    `total` conta as ofertas do filtro sem paginar (na ordem "atualizacao", já sem as da folga).
    Ordem "atualizacao": por (atualizado_em, id), só itens gravados até agora - FOLGA; `proximo` é o
    cursor da última oferta da página e vem null só quando a página sai vazia, para quem guarda o
    último `proximo` e volta depois buscar só as novidades. Demais ordens: disparo.ordenar e
    deslocamento; `proximo` vem null quando não há mais ofertas.

    Com `preco_max_horas`, só ofertas com preço confirmado há no máximo essas horas, contadas de `agora`.
    O SQL só estreita a leitura (comparação de texto, que deixaria passar BLOB ou texto fora do
    formato); quem decide é o _casa. Num banco de antes da v3 o SQL fica sem a coluna e nada passa.
    """
    sql, args = _SQL_BASE, []
    for coluna, valores in (('cat', f['cats']), ('loja', f['lojas'])):
        if valores:
            sql += f" AND {coluna} IN ({','.join('?' * len(valores))})"
            args += valores
    if f['preco_max_horas'] is not None and _tem_preco_em(con):
        sql += ' AND preco_em >= ?'
        args.append((agora - timedelta(hours=f['preco_max_horas'])).isoformat(timespec='seconds'))
    por_atualizacao = f['ordem'] == 'atualizacao'
    if por_atualizacao:
        sql += ' AND atualizado_em <= ? ORDER BY atualizado_em, id'
        args.append((agora - FOLGA).isoformat(timespec='seconds'))
    else:
        sql += ' ORDER BY id'   # entrada estável para o desempate por posicao do disparo.ordenar

    manuais = G.manuais(con)
    validas = []
    for r in con.execute(sql, args):
        o = oferta(r, eh_afiliado, manuais)
        if o is not None and _casa(o, f, agora):
            validas.append((r, o))

    limite = f['limite']
    if por_atualizacao:
        ofertas = [o for _, o in validas]
        if f['cursor'] is not None:
            ofertas = [o for o in ofertas if (o['atualizado_em'], o['id']) > f['cursor']]
        pagina = ofertas[:limite]
        proximo = f"{pagina[-1]['atualizado_em']}~{pagina[-1]['id']}" if pagina else None
    else:
        por_id = {o['id']: o for _, o in validas}
        # só linhas que passaram em oferta(): as conversões do ordenar já deram certo nelas
        ordenadas = [por_id[it['id']] for it in D.ordenar([D._item(r) for r, _ in validas], f['ordem'])]
        inicio = f['cursor'] or 0
        pagina = ordenadas[inicio:inicio + limite]
        proximo = str(inicio + limite) if inicio + limite < len(ordenadas) else None
    return {'versao': VERSAO, 'ofertas': pagina, 'proximo': proximo, 'total': len(validas)}


def categorias(con, eh_afiliado):
    """GET /api/v1/categorias (CA5): cada aba com o total e as contagens por loja e por público
    (as 4 chaves de genero.GENEROS, sempre) das ofertas que passam no CA2, em ordem alfabética (sem
    diferenciar acento e caixa)."""
    manuais = G.manuais(con)
    contas = {}
    for r in con.execute(_SQL_BASE):
        o = oferta(r, eh_afiliado, manuais)
        if o is None:
            continue
        lojas, generos = contas.setdefault(o['categoria'],
                                           (dict.fromkeys(D.LOJAS, 0), dict.fromkeys(G.GENEROS, 0)))
        lojas[o['loja']] += 1
        generos[o['genero']] += 1
    lista = [{'nome': nome, 'total': sum(lojas.values()), 'lojas': lojas, 'generos': generos}
             for nome, (lojas, generos) in sorted(contas.items(), key=lambda kv: (D._sem_acento(kv[0]), kv[0]))]
    return {'versao': VERSAO, 'categorias': lista, 'total': sum(c['total'] for c in lista)}


def rota(con, metodo, caminho, pares, eh_afiliado, agora=None):
    """Despacha /api/v1/<resto>. Devolve o objeto da resposta (200) ou levanta ErroApi.

    `caminho` é o cru (sem query); `pares` é a lista do parse_qsl (com keep_blank_values, para
    "q=" vazio dar 400 em vez de sumir). `agora` (datetime local) é injetável nos testes.
    """
    if not isinstance(caminho, str) or not caminho.startswith(PREFIXO):
        raise ErroApi(404, 'rota não encontrada')
    resto = caminho[len(PREFIXO):]
    if resto not in ('ofertas', 'categorias'):
        raise ErroApi(404, 'rota não encontrada')
    if metodo != 'GET':
        raise ErroApi(405, 'método não permitido: a API só aceita GET')
    if resto == 'ofertas':
        return listar(con, filtros(pares), eh_afiliado, agora or datetime.now())
    if pares:
        raise _invalido('a rota categorias não aceita parâmetros')
    return categorias(con, eh_afiliado)
