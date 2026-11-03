#!/usr/bin/env python3
"""Reorganiza as abas (coluna `cat` da tabela `items`) pelo mapa termo -> categoria de buscas.json.

Plano: docs/produto/planos/eletronicos-e-coleta-ml.md (etapa 2).

Uso:
  python3 migrar_categorias.py --dry-run            mostra o que mudaria; não grava nem faz backup
  python3 migrar_categorias.py                       faz backup verificado e migra numa transação só
  python3 migrar_categorias.py --restaurar ARQUIVO   devolve o banco ao estado do backup (servidor parado);
                                                     antes, guarda o estado atual em backups/

No banco real (achadinhos.db ao lado deste arquivo), gravar pede confirmação: digite "sim" quando o
script perguntar ou passe --sim. ACHADINHOS_DB troca o banco e ACHADINHOS_PORTA a porta do servidor.
Código de saída: 0 quando dá certo, 1 quando dá erro ou o pedido é recusado.
"""
import argparse
import json
import os
import pathlib
import shlex
import socket
import sqlite3
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime

import servidor as S

# Abas que deixam de existir. Para a próxima reorganização, basta trocar esta tupla.
ORIGENS = ('Black Friday', 'Casa Nova')
# Termo usado só no ML -> termo de buscas.json de onde ele herda a categoria. Fica fora do
# buscas.json para a Amazon não passar a coletar esse termo.
ALIAS = {'Caixa inteligente assistente virtual': 'Smart speaker Alexa'}
BUSCAS = os.path.join(S.BASE, 'buscas.json')
PORTA_PADRAO = 8765   # a do servidor.py sem ACHADINHOS_PORTA


class Erro(Exception):
    """Falha que encerra o script com código 1 e só a mensagem (sem traceback)."""


def nfc(txt):
    return unicodedata.normalize('NFC', txt)


def seguro(txt):
    """Texto do banco ou do buscas.json pronto para o terminal: caractere não imprimível vira \\xNN.

    Um `cat` ou `busca` com sequência de escape (ex.: ESC[2K) não apaga nem reescreve a saída.
    """
    return ''.join(c if c.isprintable() else f'\\x{ord(c):02x}' for c in str(txt))


def carregar_mapa(caminho=BUSCAS):
    """Lê buscas.json e devolve {termo em NFC: categoria}. Recusa termo repetido entre categorias."""
    try:
        with open(caminho, encoding='utf-8') as f:
            buscas = json.load(f)
    except (OSError, ValueError) as e:
        raise Erro(f'não consegui ler {caminho}: {type(e).__name__}')
    if not isinstance(buscas, dict):
        raise Erro(f'{caminho} tem que ser um objeto {{categoria: [termos]}}')
    mapa = {}
    for cat, termos in buscas.items():
        if not isinstance(termos, list) or not all(isinstance(t, str) for t in termos):
            raise Erro(f'em {caminho}, a categoria "{seguro(cat)}" tem que ter uma lista de termos')
        for termo in termos:
            chave = nfc(termo)
            if chave in mapa and mapa[chave] != cat:
                raise Erro(f'em {caminho}, o termo "{seguro(termo)}" está em "{seguro(mapa[chave])}" '
                           f'e em "{seguro(cat)}"')
            mapa[chave] = cat
    return mapa


def destino_de(busca, mapa):
    """Categoria de destino de um item pela sua `busca` (com o ALIAS do ML), ou None."""
    termo = nfc(busca or '')
    return mapa.get(nfc(ALIAS.get(termo, termo)))


def planejar(linhas, mapa):
    """Separa os itens das origens em (movidos, sem_destino).

    movidos: lista de (id, loja, cat, busca, destino), só dos que mudam de aba.
    sem_destino: lista de (id, loja, cat, busca) cujo termo não está no mapa.
    """
    movidos, sem_destino = [], []
    for r in linhas:
        dest = destino_de(r['busca'], mapa)
        if dest is None:
            sem_destino.append((r['id'], r['loja'], r['cat'], r['busca']))
        elif dest != r['cat']:
            movidos.append((r['id'], r['loja'], r['cat'], r['busca'], dest))
    return movidos, sem_destino


def lojas_txt(contagem):
    return ', '.join(f'{loja} {n}' for loja, n in sorted(contagem.items()))


def imprimir_plano(movidos, mapa):
    """Contagens por origem e destino, com loja e termo, e o resumo por destino."""
    por_rota = defaultdict(Counter)                        # (origem, destino) -> loja -> n
    por_termo = defaultdict(lambda: defaultdict(Counter))  # (origem, destino) -> busca -> loja -> n
    por_destino = defaultdict(Counter)
    for _id, loja, cat, busca, dest in movidos:
        por_rota[(cat, dest)][loja] += 1
        por_termo[(cat, dest)][busca][loja] += 1
        por_destino[dest][loja] += 1
    for (cat, dest), lojas in sorted(por_rota.items()):
        print(f'\nDe "{seguro(cat)}" para "{seguro(dest)}": {sum(lojas.values())} itens ({lojas_txt(lojas)})')
        for busca, cont in sorted(por_termo[(cat, dest)].items()):
            alias = f' (alias de "{seguro(ALIAS[nfc(busca)])}")' if nfc(busca) in ALIAS else ''
            print(f'    {seguro(busca)}{alias}: {lojas_txt(cont)}')
    print('\nResumo por destino:')
    for dest in dict.fromkeys(mapa.values()):
        if dest in por_destino:
            c = por_destino[dest]
            print(f'    "{seguro(dest)}": {sum(c.values())} itens ({lojas_txt(c)})')
    print(f'Total a mover: {len(movidos)}')


def imprimir_abas(con):
    print('\nAbas no banco:')
    ordem = 'SELECT cat, MIN(posicao) AS p FROM items GROUP BY cat'
    for r in con.execute(f'SELECT i.cat, i.loja, COUNT(*) AS n FROM items i JOIN ({ordem}) o ON o.cat = i.cat '
                         'GROUP BY i.cat, i.loja ORDER BY MIN(o.p), i.cat, i.loja'):
        print(f'    "{seguro(r["cat"])}" | {seguro(r["loja"])}: {r["n"]}')
    print(f'    total: {con.execute("SELECT COUNT(*) FROM items").fetchone()[0]}')


def conectar_ro(caminho):
    """Conexão só de leitura (nunca cria o arquivo)."""
    con = sqlite3.connect(pathlib.Path(caminho).resolve().as_uri() + '?mode=ro', uri=True, timeout=30)
    con.row_factory = sqlite3.Row
    return con


def exigir_banco():
    if not os.path.isfile(S.DB):
        raise Erro(f'banco não encontrado: {S.DB}')


def eh_banco_real():
    return os.path.realpath(S.DB) == os.path.realpath(os.path.join(S.BASE, 'achadinhos.db'))


def confirmar_banco_real(acao, sim):
    """Gravar no banco real exige --sim ou digitar "sim" num terminal. Sem terminal, recusa."""
    if not eh_banco_real() or sim:
        return
    if not sys.stdin.isatty():
        raise Erro(f'{acao} no banco real ({S.DB}) exige confirmação: rode num terminal ou passe --sim')
    try:
        resp = input(f'Isto vai {acao} no banco REAL {S.DB}. Digite "sim" para continuar: ')
    except (EOFError, KeyboardInterrupt):
        resp = ''
    if resp.strip().lower() != 'sim':
        raise Erro('cancelado: nada foi gravado')


def caminho_backup():
    pasta = os.path.join(os.path.dirname(os.path.abspath(S.DB)), 'backups')
    os.makedirs(pasta, exist_ok=True)
    base = os.path.join(pasta, 'achadinhos-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
    caminho, n = base + '.db', 1
    while os.path.exists(caminho):
        caminho, n = f'{base}-{n}.db', n + 1
    return caminho


def verificar_backup(caminho, total):
    """Devolve None se o backup está íntegro e tem `total` itens; senão, o motivo."""
    con = sqlite3.connect(caminho)
    try:
        ok = con.execute('PRAGMA integrity_check').fetchone()[0]
        if ok != 'ok':
            return f'integrity_check deu "{ok}"'
        n = con.execute('SELECT COUNT(*) FROM items').fetchone()[0]
        if n != total:
            return f'o backup tem {n} itens e o banco {total}'
        return None
    finally:
        con.close()


def fazer_backup(total, efeito='nada foi migrado'):
    """Copia o banco com a API backup do sqlite e verifica a cópia. Erro se algo falhar.

    Chamado com a transação de escrita já aberta noutra conexão: ninguém grava até o
    COMMIT, e por isso a cópia lida aqui é exatamente o estado que a migração vai mudar.
    (A API backup não lê pela conexão que segura a escrita: fica em SQLITE_LOCKED.)
    """
    caminho = None
    try:
        caminho = caminho_backup()
        origem = S.conectar()
        try:
            destino = sqlite3.connect(caminho)
            try:
                origem.backup(destino)
            finally:
                destino.close()
        finally:
            origem.close()
        motivo = verificar_backup(caminho, total)
    except (OSError, sqlite3.Error) as e:
        motivo = f'{type(e).__name__} ao gravar o backup'
    if motivo:
        if caminho:
            for sufixo in ('', '-wal', '-shm', '-journal'):
                try:
                    os.remove(caminho + sufixo)
                except OSError:
                    pass
        raise Erro(f'backup falhou ({motivo}); {efeito}')
    return caminho


def comando(*args):
    """Linha de comando que roda este script sobre o mesmo banco e a mesma porta, de qualquer pasta."""
    env = [] if eh_banco_real() else [f'ACHADINHOS_DB={shlex.quote(os.path.abspath(S.DB))}']
    if os.environ.get('ACHADINHOS_PORTA'):
        env.append(f'ACHADINHOS_PORTA={S.PORT}')
    return ' '.join([*env, 'python3', shlex.quote(os.path.abspath(__file__)), *map(shlex.quote, args)])


def migrar(dry_run, sim):
    exigir_banco()
    mapa = carregar_mapa()
    marcas = ','.join('?' * len(ORIGENS))
    print(f'Banco: {S.DB}')
    print('Origens: ' + ', '.join(f'"{o}"' for o in ORIGENS))

    if dry_run:
        con = conectar_ro(S.DB)
    else:
        confirmar_banco_real('migrar as abas', sim)
        con = S.conectar()
        con.isolation_level = None           # BEGIN/COMMIT/ROLLBACK explícitos
    try:
        if not dry_run:
            con.execute('BEGIN IMMEDIATE')   # trava a escrita até o COMMIT; o servidor espera (timeout 30 s)
        linhas = con.execute(f'SELECT id, loja, cat, busca FROM items WHERE cat IN ({marcas}) ORDER BY id',
                             ORIGENS).fetchall()
        movidos, sem_destino = planejar(linhas, mapa)
        if sem_destino:
            print(f'\nERRO: {len(sem_destino)} itens das origens têm busca sem destino em buscas.json '
                  '(nem no ALIAS). Nada foi gravado.', file=sys.stderr)
            for _id, loja, cat, busca in sem_destino:
                print(f'    id={_id} loja={seguro(loja)} cat="{seguro(cat)}" busca="{seguro(busca)}"',
                      file=sys.stderr)
            raise Erro('migração abortada: ponha esses termos em buscas.json (ou no ALIAS) ou mova os itens')
        if not movidos:
            print('\nNada a migrar: 0 itens movidos. Nenhum backup foi criado.')
            imprimir_abas(con)
            return
        imprimir_plano(movidos, mapa)
        for r in con.execute(f'SELECT cat, COUNT(*) AS n FROM items WHERE cat NOT IN ({marcas}) '
                             'GROUP BY cat ORDER BY MIN(posicao)', ORIGENS):
            print(f'Não muda: "{seguro(r["cat"])}" ({r["n"]} itens)')
        if dry_run:
            print('\n--dry-run: nada foi gravado e nenhum backup foi criado.')
            return

        total = con.execute('SELECT COUNT(*) FROM items').fetchone()[0]
        backup = fazer_backup(total)
        print(f'\nBackup verificado: {backup}')

        # Um UPDATE por destino, só com parâmetros. Os valores de busca vão crus (como estão no
        # banco), para casar mesmo se o banco tiver o termo noutra forma Unicode.
        buscas_por_destino = defaultdict(set)
        for _id, _loja, _cat, busca, dest in movidos:
            buscas_por_destino[dest].add(busca)
        quando, movidos_n = S.agora(), 0
        for dest, buscas in buscas_por_destino.items():
            buscas = sorted(buscas)
            cur = con.execute(
                f'UPDATE items SET cat=?, atualizado_em=? WHERE cat IN ({marcas}) '
                f'AND busca IN ({",".join("?" * len(buscas))}) AND cat<>?',
                (dest, quando, *ORIGENS, *buscas, dest))
            movidos_n += cur.rowcount
        if movidos_n != len(movidos):
            raise Erro(f'o UPDATE mudou {movidos_n} itens e o plano previa {len(movidos)}; nada foi gravado')
        con.execute('COMMIT')
        print(f'Migração concluída: {movidos_n} itens movidos.')
        imprimir_abas(con)
        print(f'\nBackup: {backup}')
        print(f'Para reverter (com o servidor parado): {comando("--restaurar", backup)}')
    finally:
        if con.in_transaction:
            con.execute('ROLLBACK')
        con.close()


def portas_a_testar():
    """S.PORT e, no banco real, sempre a 8765: o servidor do dia a dia pode estar noutra porta."""
    return sorted({S.PORT, PORTA_PADRAO} if eh_banco_real() else {S.PORT})


def servidor_no_ar():
    """Primeira porta de portas_a_testar() que aceita conexão em 127.0.0.1, ou None."""
    for porta in portas_a_testar():
        try:
            socket.create_connection(('127.0.0.1', porta), timeout=0.5).close()
            return porta
        except OSError:
            pass
    return None


def restaurar(arquivo, sim):
    if not os.path.isfile(arquivo):
        raise Erro(f'backup não encontrado: {arquivo}')
    if os.path.exists(S.DB) and os.path.samefile(arquivo, S.DB):
        raise Erro('o backup é o próprio banco')
    porta = servidor_no_ar()
    if porta:
        raise Erro(f'o servidor está no ar na porta {porta}: pare o servidor.py (e o coletar_amazon.py, se '
                   'estiver rodando) e rode de novo. Nada foi restaurado')
    try:
        src = conectar_ro(arquivo)
    except sqlite3.Error as e:
        raise Erro(f'não consegui abrir o backup: {type(e).__name__}')
    try:
        try:
            ok = src.execute('PRAGMA integrity_check').fetchone()[0]
            total = src.execute('SELECT COUNT(*) FROM items').fetchone()[0]
        except sqlite3.Error as e:
            raise Erro(f'o arquivo não é um backup válido ({type(e).__name__}). Nada foi restaurado')
        if ok != 'ok':
            raise Erro(f'o backup falhou no integrity_check ("{ok}"). Nada foi restaurado')
        confirmar_banco_real('restaurar o backup', sim)
        if os.path.isfile(S.DB):
            # Volta possível: o estado de agora, antes de ser sobrescrito pelo backup.
            atual = conectar_ro(S.DB)
            try:
                n_atual = atual.execute('SELECT COUNT(*) FROM items').fetchone()[0]
            except sqlite3.Error as e:
                raise Erro(f'não consegui ler o banco atual ({type(e).__name__}). Nada foi restaurado')
            finally:
                atual.close()
            antes = fazer_backup(n_atual, 'nada foi restaurado')
            print(f'Backup do estado atual (antes de restaurar): {antes}')
        dst = S.conectar()
        try:
            src.backup(dst)
            n = dst.execute('SELECT COUNT(*) FROM items').fetchone()[0]
        finally:
            dst.close()
    finally:
        src.close()
    if n != total:
        raise Erro(f'depois de restaurar, o banco tem {n} itens e o backup {total}')
    print(f'Banco {S.DB} restaurado de {arquivo}: {n} itens.')


def main(argv=None):
    p = argparse.ArgumentParser(description='Reorganiza as abas pelo mapa de buscas.json.')
    g = p.add_mutually_exclusive_group()
    g.add_argument('--dry-run', action='store_true', help='só mostra as contagens; não grava nada')
    g.add_argument('--restaurar', metavar='ARQUIVO', help='devolve o banco ao estado do backup')
    p.add_argument('--sim', action='store_true', help='confirma a gravação no banco real sem perguntar')
    a = p.parse_args(argv)
    try:
        if a.restaurar:
            restaurar(a.restaurar, a.sim)
        else:
            migrar(a.dry_run, a.sim)
    except Erro as e:
        print(f'ERRO: {e}', file=sys.stderr)
        return 1
    except sqlite3.Error as e:   # sem str(e): a mensagem da biblioteca pode trazer parâmetros
        print(f'ERRO: falha no banco ({type(e).__name__}); nada foi gravado', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
