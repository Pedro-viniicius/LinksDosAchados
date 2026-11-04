#!/usr/bin/env python3
"""Tira os itens da aba "Lista WhatsApp" e os põe na aba e no subtema (`cat` e `busca`) de lista_whatsapp.json.

Plano: docs/produto/planos/disparo-automatico.md (etapa 6).

Histórico: já rodou no banco real em 2026-11-03. Depois da reorganização em 17 abas
(docs/produto/planos/abas-nichadas-e-coleta.md, etapa 6), os itens que ele classificou saíram de
"Black Friday | Eletrônicos", e rodar de novo aborta por divergência sem gravar nada (nem o --desfazer
serve mais). Para voltar àquele estado, use o backup do migrar_categorias.py.

Uso:
  python3 classificar_lista.py --dry-run              mostra o que mudaria; não grava nem faz backup
  python3 classificar_lista.py                        faz backup verificado e grava numa transação só
  python3 classificar_lista.py --desfazer [--dry-run] devolve só os itens do mapa a "Lista WhatsApp"

Quando rodar no banco real: logo DEPOIS do `python3 migrar_categorias.py` (é ele que cria a aba
"Black Friday | Eletrônicos" com os outros itens) e ANTES de cadastrar qualquer número no disparo.
Este script funciona fora dessa ordem, mas aí a aba de destino fica só com os itens da Lista WhatsApp
(ele avisa).

Antes de gravar, cada id do mapa é conferido no banco: o `item_id` tem que ser o mesmo e o item tem
que estar em "Lista WhatsApp" (ou já com a `cat` e a `busca` do mapa). Qualquer divergência aborta sem
gravar nada. Rodar de novo resulta em 0 mudanças e nenhum backup. Só mudam `cat`, `busca` e
`atualizado_em`; a `url` (link de afiliado) nunca é tocada.

Para reverter, use --desfazer: ele mexe só nos itens do mapa que ainda estão com a `cat` e a `busca`
do mapa (volta para "Lista WhatsApp" / "WhatsApp"), com as mesmas conferências, backup e confirmação.
O `migrar_categorias.py --restaurar` também reverte, mas devolve o banco INTEIRO ao backup: desfaz
tudo o que foi gravado depois (inclusive números, regras e envios do disparo).

No banco real (achadinhos.db ao lado deste arquivo), gravar pede confirmação: digite "sim" quando o
script perguntar ou passe --sim. ACHADINHOS_DB troca o banco e ACHADINHOS_PORTA a porta do servidor.
Código de saída: 0 quando dá certo, 1 quando dá erro, divergência ou o pedido é recusado.
"""
import argparse
import json
import os
import re
import shlex
import sqlite3
import sys
from collections import Counter, defaultdict, namedtuple

import migrar_categorias as M
import servidor as S
from migrar_categorias import Erro, seguro

ORIGEM = 'Lista WhatsApp'
BUSCA_ORIGEM = 'WhatsApp'   # a busca de todos os itens da Lista WhatsApp antes da classificação
MAPA = os.path.join(S.BASE, 'lista_whatsapp.json')
CAMPOS_MAPA = ('item_id', 'cat', 'busca')
# Abas que o migrar_categorias.py de 2026-11-03 tirava; o aviso de ordem olha estas, não as M.ORIGENS de hoje.
ORIGENS_ANTIGAS = ('Black Friday', 'Casa Nova')
LEMBRETE = ('Rode logo depois do migrar_categorias.py e ANTES de cadastrar qualquer número no disparo '
            '(o --restaurar do migrar_categorias.py devolve o banco inteiro).')

# Um item a mudar: de (de_cat, de_busca) para (cat, busca). `subtema` é a busca do mapa.
Mudanca = namedtuple('Mudanca', 'id loja item_id de_cat de_busca cat busca subtema')


def _sem_chave_repetida(pares):
    vistas = set()
    for chave, _ in pares:
        if chave in vistas:
            raise Erro(f'chave repetida no mapa: "{seguro(chave)}"')
        vistas.add(chave)
    return dict(pares)


def carregar_mapa(caminho=MAPA):
    """Lê o mapa {"<id>": {"item_id", "cat", "busca"}} e devolve {id (int): {item_id, cat, busca}}."""
    try:
        with open(caminho, encoding='utf-8') as f:
            bruto = json.load(f, object_pairs_hook=_sem_chave_repetida)
    except (OSError, ValueError) as e:
        raise Erro(f'não consegui ler {caminho}: {type(e).__name__}')
    if not isinstance(bruto, dict) or not bruto:
        raise Erro(f'{caminho} tem que ser um objeto {{"<id>": {{"item_id", "cat", "busca"}}}} não vazio')
    mapa, donos = {}, {}
    for chave, v in bruto.items():
        if not re.fullmatch(r'[1-9][0-9]{0,17}', chave):
            raise Erro(f'em {caminho}, a chave "{seguro(chave)}" não é um id')
        if (not isinstance(v, dict) or set(v) != set(CAMPOS_MAPA)
                or not all(isinstance(v[c], str) and v[c].strip() for c in CAMPOS_MAPA)):
            raise Erro(f'em {caminho}, o id {chave} tem que ter só item_id, cat e busca, todos texto não vazio')
        if v['cat'] == ORIGEM:
            raise Erro(f'em {caminho}, o id {chave} tem "{ORIGEM}" como destino')
        if v['item_id'] in donos:
            raise Erro(f'em {caminho}, o item_id "{seguro(v["item_id"])}" está nos ids {donos[v["item_id"]]} e {chave}')
        donos[v['item_id']] = chave
        mapa[int(chave)] = {c: v[c] for c in CAMPOS_MAPA}
    return mapa


def planejar(con, mapa, desfazer=False):
    """Confere o mapa contra o banco e devolve (mudar, ja_feitos, divergentes, fora_do_mapa).

    Classificar: o item sai de ORIGEM (qualquer busca) para a `cat` e a `busca` do mapa.
    Desfazer: o item sai exatamente da `cat` e da `busca` do mapa para ORIGEM / BUSCA_ORIGEM.
    mudar: lista de Mudanca.
    ja_feitos: ids que já estão no estado de chegada.
    divergentes: lista de (id, motivo) — se tiver algo, nada pode ser gravado.
    fora_do_mapa: quantos itens de ORIGEM não estão no mapa (ficam onde estão).
    """
    ids = sorted(mapa)
    linhas = {r['id']: r for r in con.execute(
        f'SELECT id, loja, item_id, cat, busca FROM items WHERE cat=? OR id IN ({",".join("?" * len(ids))})',
        (ORIGEM, *ids))}
    mudar, ja_feitos, divergentes = [], [], []
    for _id, m in sorted(mapa.items()):
        r = linhas.get(_id)
        no_mapa = (m['cat'], m['busca'])
        chegada = (ORIGEM, BUSCA_ORIGEM) if desfazer else no_mapa
        if r is None:
            divergentes.append((_id, 'não existe no banco'))
            continue
        atual = (r['cat'], r['busca'])
        if r['item_id'] != m['item_id']:
            divergentes.append((_id, f'item_id no banco é "{seguro(r["item_id"])}" e no mapa '
                                     f'"{seguro(m["item_id"])}"'))
        elif atual == chegada:
            ja_feitos.append(_id)
        elif (atual == no_mapa) if desfazer else (r['cat'] == ORIGEM):
            mudar.append(Mudanca(_id, r['loja'], r['item_id'], *atual, *chegada, m['busca']))
        elif desfazer:
            divergentes.append((_id, f'está em cat="{seguro(r["cat"])}" busca="{seguro(r["busca"])}", '
                                     f'diferente do mapa e de "{ORIGEM}"/"{BUSCA_ORIGEM}"'))
        else:
            divergentes.append((_id, f'está em cat="{seguro(r["cat"])}" busca="{seguro(r["busca"])}", '
                                     f'fora de "{ORIGEM}" e diferente do mapa'))
    fora_do_mapa = sum(1 for _id, r in linhas.items() if r['cat'] == ORIGEM and _id not in mapa)
    return mudar, ja_feitos, divergentes, fora_do_mapa


def avisar_fora_do_mapa(fora_do_mapa):
    if fora_do_mapa:
        print(f'AVISO: {fora_do_mapa} itens de "{ORIGEM}" não estão no mapa e ficam nessa aba.')


def imprimir_plano(mudar, ja_feitos, fora_do_mapa, desfazer):
    por_rota = defaultdict(Counter)                        # (de, para) -> loja -> n
    por_busca = defaultdict(lambda: defaultdict(Counter))  # (de, para) -> subtema -> loja -> n
    for x in mudar:
        por_rota[(x.de_cat, x.cat)][x.loja] += 1
        por_busca[(x.de_cat, x.cat)][x.subtema][x.loja] += 1
    for (de, para), lojas in sorted(por_rota.items()):
        print(f'\nDe "{seguro(de)}" para "{seguro(para)}": {sum(lojas.values())} itens ({M.lojas_txt(lojas)})')
        for busca, cont in sorted(por_busca[(de, para)].items()):
            seta = f' -> {BUSCA_ORIGEM}' if desfazer else ''
            print(f'    {seguro(busca)}{seta}: {M.lojas_txt(cont)}')
    print(f'\n{"Já desfeitos" if desfazer else "Já classificados"} (ficam como estão): {len(ja_feitos)}')
    if not desfazer:
        avisar_fora_do_mapa(fora_do_mapa)
    print(f'Total a mudar: {len(mudar)}')


def avisar_ordem(con):
    """O destino é só um texto, mas no banco real a aba nova nasce do migrar_categorias.py."""
    antigas = [r[0] for r in con.execute(
        f'SELECT DISTINCT cat FROM items WHERE cat IN ({",".join("?" * len(ORIGENS_ANTIGAS))}) ORDER BY cat',
        ORIGENS_ANTIGAS)]
    if antigas:
        abas = ', '.join(f'"{seguro(c)}"' for c in antigas)
        print(f'\nAVISO: o banco ainda tem as abas {abas}. Rode antes o migrar_categorias.py; '
              'sem ele, a aba de destino fica só com estes itens.')


def recusar_divergentes(divergentes, caminho_mapa):
    print(f'\nERRO: {len(divergentes)} ids do mapa não batem com o banco. Nada foi gravado.', file=sys.stderr)
    for _id, motivo in divergentes:
        print(f'    id={_id}: {motivo}', file=sys.stderr)
    raise Erro(f'abortado: confira {caminho_mapa} contra o banco')


def nada_a_fazer(ja_feitos, desfazer):
    if desfazer:
        print(f'\nNada a desfazer: 0 itens mudados ({len(ja_feitos)} já em "{ORIGEM}"). Nenhum backup foi criado.')
    else:
        print(f'\nNada a classificar: 0 itens mudados ({len(ja_feitos)} já classificados). '
              'Nenhum backup foi criado.')


def comando(*args):
    """Linha de comando que roda este script sobre o mesmo banco e a mesma porta, de qualquer pasta.

    Cópia do `comando` do migrar_categorias.py, que monta a linha com o caminho dele próprio.
    """
    env = [] if M.eh_banco_real() else [f'ACHADINHOS_DB={shlex.quote(os.path.abspath(S.DB))}']
    if os.environ.get('ACHADINHOS_PORTA'):
        env.append(f'ACHADINHOS_PORTA={S.PORT}')
    return ' '.join([*env, 'python3', shlex.quote(os.path.abspath(__file__)), *map(shlex.quote, args)])


def classificar(dry_run, sim, caminho_mapa=MAPA, desfazer=False):
    M.exigir_banco()
    mapa = carregar_mapa(caminho_mapa)
    print(f'Banco: {S.DB}')
    print(f'Mapa: {caminho_mapa} ({len(mapa)} ids)')
    if desfazer:
        print(f'Modo: --desfazer (volta os itens do mapa para "{ORIGEM}" / "{BUSCA_ORIGEM}")')

    # 1) Leitura só: mostra o plano (e os avisos) antes de qualquer pergunta.
    con = M.conectar_ro(S.DB)
    try:
        mudar, ja_feitos, divergentes, fora_do_mapa = planejar(con, mapa, desfazer)
        if divergentes:
            recusar_divergentes(divergentes, caminho_mapa)
        if not mudar:
            nada_a_fazer(ja_feitos, desfazer)
            if not desfazer:
                avisar_fora_do_mapa(fora_do_mapa)
            return
        imprimir_plano(mudar, ja_feitos, fora_do_mapa, desfazer)
        if not desfazer:
            avisar_ordem(con)
            print(f'\n{LEMBRETE}')
    finally:
        con.close()
    if dry_run:
        print('\n--dry-run: nada foi gravado e nenhum backup foi criado.')
        return

    # 2) Escrita: confere de novo dentro da transação, faz o backup e grava.
    M.confirmar_banco_real('desfazer a classificação da Lista WhatsApp' if desfazer
                           else 'classificar a Lista WhatsApp', sim)
    con = S.conectar()
    con.isolation_level = None           # BEGIN/COMMIT/ROLLBACK explícitos
    try:
        con.execute('BEGIN IMMEDIATE')   # trava a escrita até o COMMIT; o servidor espera (timeout 30 s)
        mudar, ja_feitos, divergentes, _ = planejar(con, mapa, desfazer)
        if divergentes:
            recusar_divergentes(divergentes, caminho_mapa)
        if not mudar:
            nada_a_fazer(ja_feitos, desfazer)
            return
        total = con.execute('SELECT COUNT(*) FROM items').fetchone()[0]
        backup = M.fazer_backup(total, 'nada foi gravado')
        print(f'\nBackup verificado: {backup}')

        # Um UPDATE por item, só com parâmetros; o WHERE repete a conferência (id, item_id, cat e busca).
        quando, mudados = S.agora(), 0
        for x in mudar:
            cur = con.execute('UPDATE items SET cat=?, busca=?, atualizado_em=? '
                              'WHERE id=? AND item_id=? AND cat=? AND busca IS ?',   # IS: busca pode ser NULL
                              (x.cat, x.busca, quando, x.id, x.item_id, x.de_cat, x.de_busca))
            mudados += cur.rowcount
        if mudados != len(mudar):
            raise Erro(f'o UPDATE mudou {mudados} itens e o plano previa {len(mudar)}; nada foi gravado')
        con.execute('COMMIT')
        if desfazer:
            print(f'Desfeito: {mudados} itens voltaram para "{ORIGEM}".')
        else:
            print(f'Classificação concluída: {mudados} itens mudados.')
        M.imprimir_abas(con)
        print(f'\nBackup: {backup}')
        if not desfazer:
            print(f'Para desfazer só esta classificação: {comando("--desfazer")}')
        print('Alternativa que devolve o banco INTEIRO a este backup, desfazendo tudo o que foi gravado depois '
              f'(inclusive o disparo), com o servidor parado: {M.comando("--restaurar", backup)}')
    finally:
        if con.in_transaction:
            con.execute('ROLLBACK')
        con.close()


def main(argv=None):
    p = argparse.ArgumentParser(description=f'Classifica os itens de "{ORIGEM}" pelo lista_whatsapp.json.')
    p.add_argument('--dry-run', action='store_true', help='só mostra as contagens; não grava nada')
    p.add_argument('--desfazer', action='store_true',
                   help=f'devolve a "{ORIGEM}" só os itens do mapa que ainda estão como o mapa deixou')
    p.add_argument('--sim', action='store_true', help='confirma a gravação no banco real sem perguntar')
    a = p.parse_args(argv)
    try:
        classificar(a.dry_run, a.sim, desfazer=a.desfazer)
    except Erro as e:
        print(f'ERRO: {e}', file=sys.stderr)
        return 1
    except sqlite3.Error as e:   # sem str(e): a mensagem da biblioteca pode trazer parâmetros
        print(f'ERRO: falha no banco ({type(e).__name__}); nada foi gravado', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
