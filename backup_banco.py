#!/usr/bin/env python3
"""Backup datado do banco (achadinhos.db), conferido, fechado e com rotação.

Plano: docs/produto/planos/endurecer-engenharia-e-operacao.md, etapa 4 (CA5).

Uso:
  python3 backup_banco.py --motivo <motivo> [--manter N]

  --motivo   de 1 a 30 caracteres entre a-z, 0-9 e "-" (ex.: ml, shopee, diario, reiniciar)
  --manter   quantos backups automáticos (auto-*.db) ficam depois da rotação; padrão 14, mínimo 3

O banco vem de servidor.DB (ACHADINHOS_DB troca o caminho) e o backup vai para backups/, ao lado
dele, com o nome auto-<motivo>-AAAAMMDD-HHMMSS.db (no mesmo segundo: -1, -2...). Nunca sobrescreve
um arquivo que já exista.

O fluxo:
  1. lê o banco em mode=ro, pela API backup do sqlite (pega também o que ainda está no -wal);
  2. exige espaço livre de 2x o tamanho do banco;
  3. grava em <nome>.parcial (0600 desde a criação), põe journal_mode=DELETE (a cópia não cria
     -wal/-shm quando é aberta) e confere integrity_check == "ok" e itens > 0;
  4. publica com link sem sobrescrever (o nome final só aparece completo) e apaga o .parcial;
  5. a pasta backups/ fica em 0700 e cada backup em 0600: o banco tem telefones (tabela numeros);
  6. imprime só "backup: <caminho> ok <n> itens" (nada do conteúdo do banco);
  7. só depois do sucesso, a rotação apaga os auto-*.db além dos N mais novos (pela data do nome)
     e o -wal/-shm/-journal de cada um. Nunca toca arquivo sem o prefixo auto-, nunca segue link
     simbólico e confere o padrão do nome antes de apagar. Backups manuais (achadinhos-*.db,
     antes-*.db) ficam. Apaga também o auto-*.db.parcial (e o -wal/-shm/-journal dele) parado há mais
     de 6 h: é a sobra de um backup morto no meio (kill -9, queda de energia), uma cópia completa do
     banco, com telefones. O de um backup em andamento é recente e fica.

Saídas: 0 backup gravado; 1 falha (o .parcial é apagado); 2 motivo ou uso inválido. Interrompido por
SIGTERM, SIGHUP ou Ctrl+C, sai com 1 e manda conferir backups/: se o sinal chegou depois da publicação, o
backup ficou gravado (sem a rotação).
Só biblioteca padrão.
"""
import argparse
import os
import pathlib
import re
import signal
import sqlite3
import stat
import sys
import time
from datetime import datetime

import servidor as S

MANTER_PADRAO = 14
MANTER_MINIMO = 3
RE_MOTIVO = re.compile(r'[a-z0-9-]{1,30}')
# Nome de um backup automático. O sufixo de colisão tem até 3 dígitos: assim a data é sempre o
# último AAAAMMDD-HHMMSS do nome, mesmo que o motivo também tenha dígitos e hífens.
RE_AUTO = re.compile(r'auto-(?P<motivo>[a-z0-9-]{1,30})-(?P<ts>[0-9]{8}-[0-9]{6})(?:-(?P<n>[0-9]{1,3}))?\.db')
MAX_COLISOES = 1000
SUFIXOS_SQLITE = ('-wal', '-shm', '-journal')
PARCIAL = '.parcial'
# Um .parcial sem mudança há mais que isto é sobra de backup morto (o backup leva segundos).
PARCIAL_VELHO_SEG = 6 * 3600


class Falha(Exception):
    """Falha do backup, com motivo fixo (nunca traz conteúdo do banco)."""


class Interrompido(BaseException):
    """SIGTERM/SIGHUP no meio do backup: vira exceção para o .parcial ser apagado."""


def agora():
    return datetime.now()


def espaco_livre(pasta):
    st = os.statvfs(pasta)
    return st.f_bavail * st.f_frsize


def tamanho_do_banco(db):
    """Tamanho do banco somado ao do -wal (o backup também copia o que ainda está nele)."""
    total = os.path.getsize(db)
    try:
        total += os.path.getsize(db + '-wal')
    except OSError:
        pass
    return total


def uri_somente_leitura(caminho):
    return pathlib.Path(caminho).as_uri() + '?mode=ro'


def abrir_pasta(pasta):
    """Cria (0700) ou confere backups/ e devolve um descritor dela. Recusa link simbólico e pasta de outro."""
    try:
        os.mkdir(pasta, 0o700)
    except FileExistsError:
        pass
    try:
        fd = os.open(pasta, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError:
        raise Falha('backups/ não é uma pasta comum (link simbólico ou outro tipo de arquivo)') from None
    try:
        st = os.fstat(fd)
        if st.st_uid != os.geteuid():
            raise Falha('backups/ é de outro usuário')
        if stat.S_IMODE(st.st_mode) != 0o700:
            os.fchmod(fd, 0o700)
        return fd
    except BaseException:
        os.close(fd)
        raise


def existe(nome, dfd):
    try:
        os.stat(nome, dir_fd=dfd, follow_symlinks=False)
        return True
    except FileNotFoundError:
        return False


def reservar_nome(dfd, motivo):
    """Escolhe o nome final livre e cria o .parcial dele (0600, O_EXCL). Devolve o nome final."""
    base = f'auto-{motivo}-{agora():%Y%m%d-%H%M%S}'
    for n in range(MAX_COLISOES):
        nome = base + (f'-{n}' if n else '') + '.db'
        # Um -journal antigo com o mesmo nome seria lido pelo sqlite como journal "quente" e
        # aplicado sobre a cópia nova: o nome só serve se nada dele existir.
        ocupados = [nome + s for s in ('', *SUFIXOS_SQLITE)]
        ocupados += [nome + PARCIAL + s for s in ('', *SUFIXOS_SQLITE)]
        if any(existe(o, dfd) for o in ocupados):
            continue
        try:
            fd = os.open(nome + PARCIAL, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                         0o600, dir_fd=dfd)
        except FileExistsError:
            continue
        try:
            try:
                os.fchmod(fd, 0o600)
            finally:
                os.close(fd)
        except BaseException:
            limpar_parcial(nome, dfd)
            raise
        return nome
    raise Falha(f'mais de {MAX_COLISOES} backups com o mesmo motivo no mesmo segundo')


def copiar(db, destino):
    """Copia o banco (lido em mode=ro) para `destino` e deixa a cópia em journal_mode=DELETE."""
    origem = sqlite3.connect(uri_somente_leitura(db), uri=True, timeout=30)
    try:
        con = sqlite3.connect(destino)
        try:
            origem.backup(con)
            modo = con.execute('PRAGMA journal_mode=DELETE').fetchone()[0]
        finally:
            con.close()
    finally:
        origem.close()
    if str(modo).lower() != 'delete':
        raise Falha('a cópia não aceitou journal_mode=DELETE')


def conferir(caminho):
    """integrity_check == "ok" e itens > 0 na cópia. Devolve o número de itens."""
    con = sqlite3.connect(uri_somente_leitura(caminho), uri=True)
    try:
        linhas = con.execute('PRAGMA integrity_check').fetchall()
        if [tuple(l) for l in linhas] != [('ok',)]:
            raise Falha('integrity_check não deu "ok"')
        n = con.execute('SELECT COUNT(*) FROM items').fetchone()[0]
    finally:
        con.close()
    if not isinstance(n, int) or n <= 0:
        raise Falha('a cópia não tem itens')
    return n


def apagar_se_comum(nome, dfd):
    """Apaga `nome` da pasta só se for arquivo comum (link simbólico e pasta ficam)."""
    try:
        st = os.stat(nome, dir_fd=dfd, follow_symlinks=False)
    except FileNotFoundError:
        return False
    if not stat.S_ISREG(st.st_mode):
        return False
    try:
        os.unlink(nome, dir_fd=dfd)
    except FileNotFoundError:   # outro backup_banco.py, rotacionando ao mesmo tempo, apagou antes
        return False
    return True


def limpar_parcial(nome, dfd):
    """Apaga o .parcial de `nome` e o -wal/-shm/-journal dele. Nunca lança."""
    for s in ('', *SUFIXOS_SQLITE):
        try:
            apagar_se_comum(nome + PARCIAL + s, dfd)
        except OSError:
            pass


def publicar(nome, dfd):
    """fsync, 0600 e link do .parcial para o nome final, sem sobrescrever; depois apaga o .parcial."""
    parcial = nome + PARCIAL
    if any(existe(parcial + s, dfd) for s in SUFIXOS_SQLITE):
        raise Falha('a cópia deixou -wal/-shm/-journal')
    fd = os.open(parcial, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=dfd)
    try:
        os.fchmod(fd, 0o600)
        os.fsync(fd)
    finally:
        os.close(fd)
    # Um link (e não os.replace) para nunca sobrescrever: se o nome final apareceu durante a cópia,
    # o link falha com EEXIST e o arquivo que lá está fica intacto.
    try:
        os.link(parcial, nome, src_dir_fd=dfd, dst_dir_fd=dfd, follow_symlinks=False)
    except FileExistsError:
        raise Falha('o nome final apareceu durante a cópia; nada foi sobrescrito') from None
    os.unlink(parcial, dir_fd=dfd)
    os.fsync(dfd)


def fazer_backup(motivo):
    """Grava o backup conferido. Devolve (caminho, itens). Falha com motivo fixo; o .parcial nunca fica."""
    db = os.path.abspath(S.DB)
    if not os.path.isfile(db):
        raise Falha('banco não encontrado')
    pasta = os.path.join(os.path.dirname(db), 'backups')
    try:
        dfd = abrir_pasta(pasta)
    except OSError as e:
        raise Falha(f'{type(e).__name__} ao preparar backups/') from None
    try:
        try:
            if espaco_livre(pasta) < 2 * tamanho_do_banco(db):
                raise Falha('espaço livre menor que 2 vezes o tamanho do banco')
            nome = reservar_nome(dfd, motivo)
        except OSError as e:
            raise Falha(f'{type(e).__name__} ao reservar o nome do backup') from None
        try:
            copiar(db, os.path.join(pasta, nome + PARCIAL))
            n = conferir(os.path.join(pasta, nome + PARCIAL))
            publicar(nome, dfd)
        except (OSError, sqlite3.Error) as e:
            raise Falha(f'{type(e).__name__} ao gravar o backup') from None
        finally:
            limpar_parcial(nome, dfd)
        return os.path.join(pasta, nome), n
    finally:
        os.close(dfd)


def rotacionar(pasta, manter, novo):
    """Apaga os auto-*.db além dos `manter` mais novos (pela data do nome). Nunca apaga `novo`.

    Só arquivo comum com nome no padrão RE_AUTO entra na conta; link simbólico, pasta e qualquer
    outro nome ficam como estão. Devolve os nomes apagados (só os auto-*.db). À parte, apaga o
    auto-*.db.parcial (arquivo comum) sem mudança há mais de PARCIAL_VELHO_SEG, com o -wal/-shm/-journal
    dele.
    """
    dfd = os.open(pasta, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        candidatos = []
        parciais_velhos = []
        limite = time.time() - PARCIAL_VELHO_SEG
        with os.scandir(dfd) as it:
            for e in it:
                m = RE_AUTO.fullmatch(e.name)
                if m and e.is_file(follow_symlinks=False):
                    candidatos.append((m['ts'], int(m['n'] or 0), e.name))
                elif (e.name.endswith(PARCIAL) and RE_AUTO.fullmatch(e.name[:-len(PARCIAL)])
                      and e.is_file(follow_symlinks=False)):
                    try:
                        if e.stat(follow_symlinks=False).st_mtime < limite:
                            parciais_velhos.append(e.name)
                    except FileNotFoundError:
                        pass
        for nome in parciais_velhos:
            for s in ('', *SUFIXOS_SQLITE):
                apagar_se_comum(nome + s, dfd)
        candidatos.sort(reverse=True)
        apagados = []
        for _, _, nome in candidatos[manter:]:
            if nome == novo or not RE_AUTO.fullmatch(nome):
                continue
            if apagar_se_comum(nome, dfd):
                apagados.append(nome)
            for s in SUFIXOS_SQLITE:
                apagar_se_comum(nome + s, dfd)
        return apagados
    finally:
        os.close(dfd)


def tipo_motivo(valor):
    if not RE_MOTIVO.fullmatch(valor):
        raise argparse.ArgumentTypeError('use de 1 a 30 caracteres entre a-z, 0-9 e "-"')
    return valor


def tipo_manter(valor):
    if not re.fullmatch(r'[0-9]{1,6}', valor) or int(valor) < MANTER_MINIMO:
        raise argparse.ArgumentTypeError(f'use um número inteiro a partir de {MANTER_MINIMO}')
    return int(valor)


def ler_argumentos(argv):
    p = argparse.ArgumentParser(prog='backup_banco.py', allow_abbrev=False,
                                description='Backup datado, conferido e rotacionado do banco.')
    p.add_argument('--motivo', required=True, type=tipo_motivo,
                   help='de 1 a 30 caracteres entre a-z, 0-9 e "-"')
    p.add_argument('--manter', type=tipo_manter, default=MANTER_PADRAO,
                   help=f'backups automáticos que ficam depois da rotação (padrão {MANTER_PADRAO}, '
                        f'mínimo {MANTER_MINIMO})')
    return p.parse_args(argv)


def _interromper(signum, frame):
    raise Interrompido(signum)


def main(argv=None):
    args = ler_argumentos(argv)   # uso inválido: argparse sai com 2
    anteriores = {sig: signal.signal(sig, _interromper) for sig in (signal.SIGTERM, signal.SIGHUP)}
    try:
        try:
            caminho, n = fazer_backup(args.motivo)
        except Falha as e:
            print(f'ERRO: backup falhou ({e}); nenhum backup novo foi gravado', file=sys.stderr)
            return 1
        except (Interrompido, KeyboardInterrupt):
            # O sinal pode chegar depois do os.link: aí o backup já está publicado (completo e conferido).
            # Por isso a mensagem não diz que nada foi gravado.
            print('ERRO: backup interrompido; confira backups/', file=sys.stderr)
            return 1
        print(f'backup: {caminho} ok {n} itens', flush=True)
    finally:
        for sig, h in anteriores.items():
            signal.signal(sig, h)
    # A rotação só roda depois do sucesso. Se falhar, o backup novo já está gravado: avisa e sai com 0.
    try:
        rotacionar(os.path.dirname(caminho), args.manter, os.path.basename(caminho))
    except OSError as e:
        print(f'AVISO: a rotação de backups/ falhou ({type(e).__name__}); o backup novo ficou gravado',
              file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
