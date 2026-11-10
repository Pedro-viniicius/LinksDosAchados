#!/usr/bin/env python3
"""Testes de QA da Entrega 1 de docs/produto/planos/endurecer-engenharia-e-operacao.md (CA4, CA5, CA6, CA7, CA12):
casos de borda e concorrência que os testes dos devs não cobrem.

Uso:  python3 testes/test_endurecer_qa.py -v

- PortaoDeCommit: `git commit` de verdade, num repositório temporário com a CÓPIA do verificar.py e do hook (nunca
  o repositório real, nunca o `git config` dele): primeiro commit sem HEAD, subpasta, nome com acento e espaço,
  renomeado, latin-1/CRLF, linha apagada, --amend, --no-verify, variantes de backup do token e linha enorme.
- Backup: rotação com motivos misturados, .parcial de SIGKILL, vários backups ao mesmo tempo e com o banco sendo
  escrito.
- Trava: dono num processo separado (kill -9 inclusive), as quatro formas de rodar a Amazon se excluem de verdade
  numa corrida de 8 processos; ML e Amazon rodam juntas.
- Operação: as 17 abas do buscas.json real (vírgula e acento), pausa só ENTRE as abas, segredo com caracteres
  especiais intacto e só no ambiente do comando.
- CA12: `verificar.py --servidor` de verdade (subprocesso) contra uma cópia do servidor, antes e depois de mexer
  em cada um dos quatro .py.

Nenhum teste roda a suíte de verdade (o hook dos repositórios temporários só vê a suíte de mentira deles), abre o
achadinhos.db, usa a 8765, grava em backups/ do projeto ou sai para a rede. Só biblioteca padrão.
"""
import atexit
import json
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unicodedata
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _k in [k for k in os.environ if k.startswith('GIT_')]:   # rodando dentro de um hook: não herdar o repositório real
    del os.environ[_k]
TMP = tempfile.mkdtemp(prefix='achadinhos-endurecer-qa-')
atexit.register(shutil.rmtree, TMP, ignore_errors=True)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

import test_operacao as TO   # noqa: E402  (Base dos scripts de operação, com o python3 falso)
import test_servidor as TS   # noqa: E402  (ambiente, porta_livre)
import verificar as V        # noqa: E402

PROXIES = {v: 'http://127.0.0.1:9' for v in ('http_proxy', 'https_proxy', 'ftp_proxy',
                                              'HTTP_PROXY', 'HTTPS_PROXY', 'FTP_PROXY')}
# Valores falsos montados na hora: a fonte deste arquivo não tem nenhum (o --tudo varre este arquivo).
FALSO32 = 'f4lso' + 'Q7z' * 9
TOKEN_HEX = 'a1b2c3d4' * 8   # 64 hex sozinhos numa linha, como o conteúdo de um api_token.txt


def nova_pasta():
    return tempfile.mkdtemp(dir=TMP)


def python_fixo():
    """Pasta com um `python3` que é este interpretador: o hook faz `exec python3 verificar.py`."""
    pasta = nova_pasta()
    os.symlink(sys.executable, os.path.join(pasta, 'python3'))
    return pasta


def env_git(**extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1', GIT_TERMINAL_PROMPT='0',
               PATH=python_fixo() + os.pathsep + os.environ.get('PATH', ''), **extra)
    return env


# ================================================================ CA7: portão de commit

class Repo:
    """Repositório git temporário com a cópia do verificar.py e do .githooks/pre-commit reais e uma suíte de
    mentira de um teste verde. `base=False` deixa o repositório sem nenhum commit."""

    def __init__(self, base=True):
        self.dir = nova_pasta()
        self.env = env_git()
        self.git('init', '-q')
        self.git('config', 'user.name', 'Teste')
        self.git('config', 'user.email', 'teste@exemplo.invalid')
        self.git('config', 'commit.gpgsign', 'false')
        self.git('config', 'core.hooksPath', '.githooks')
        os.mkdir(os.path.join(self.dir, '.githooks'))
        shutil.copy2(os.path.join(RAIZ, '.githooks', 'pre-commit'), os.path.join(self.dir, '.githooks'))
        shutil.copy2(os.path.join(RAIZ, 'verificar.py'), self.dir)
        self.escrever('testes/test_verde.py', 'import unittest\nclass T(unittest.TestCase):\n'
                      '    def test_um(self):\n        self.assertTrue(True)\n'
                      'if __name__ == "__main__":\n    unittest.main()\n')
        if base:
            self.git('add', 'verificar.py', '.githooks/pre-commit', 'testes/test_verde.py')
            self.git('commit', '-q', '--no-verify', '-m', 'base')

    def git(self, *args, check=True, cwd=None):
        p = subprocess.run(['git', *args], cwd=cwd or self.dir, env=self.env, capture_output=True, text=True,
                           timeout=180)
        if check and p.returncode != 0:
            raise AssertionError(f'git {args[0]} saiu com {p.returncode}: {p.stderr}')
        return p

    def escrever(self, rel, conteudo):
        caminho = os.path.join(self.dir, rel)
        os.makedirs(os.path.dirname(caminho), exist_ok=True)
        modo = 'wb' if isinstance(conteudo, bytes) else 'w'
        with open(caminho, modo, **({} if modo == 'wb' else {'encoding': 'utf-8'})) as f:
            f.write(conteudo)

    def commit(self, *argv, cwd=None):
        p = self.git('commit', '-m', 'teste', *argv, check=False, cwd=cwd)
        return p.returncode, p.stdout + p.stderr

    def commits(self):
        p = self.git('rev-list', '--count', 'HEAD', check=False)
        return int(p.stdout) if p.returncode == 0 else 0


class PortaoDeCommit(unittest.TestCase):

    def assert_bloqueado(self, r, saida, texto, onde, antes):
        self.assertNotEqual(saida, 0, texto)
        self.assertIn(onde, texto)
        self.assertIn('commit bloqueado pelo portão (segredos)', texto)
        self.assertNotIn(FALSO32, texto)
        self.assertNotIn(FALSO32[:10], texto)
        self.assertEqual(r.commits(), antes)

    def test_primeiro_commit_sem_head_bloqueia_o_segredo(self):
        r = Repo(base=False)
        r.escrever('config.py', 'x = 1\nsecret = "' + FALSO32 + '"\n')
        r.git('add', '.')
        saida, texto = r.commit()
        self.assert_bloqueado(r, saida, texto, 'SEGREDO? config.py:2: atribuição de segredo', 0)

    def test_primeiro_commit_limpo_passa_e_roda_a_suite_de_mentira(self):
        r = Repo(base=False)
        r.git('add', '.')
        saida, texto = r.commit()
        self.assertEqual(saida, 0, texto)
        self.assertRegex(texto, r'test_verde\s+saida=0')
        self.assertEqual(r.commits(), 1)

    def test_commit_feito_de_dentro_de_uma_subpasta_bloqueia_do_mesmo_jeito(self):
        r = Repo()
        r.escrever('sub/dentro/notas.md', 'token = "' + FALSO32 + '"\n')
        r.git('add', '.')
        saida, texto = r.commit(cwd=os.path.join(r.dir, 'sub', 'dentro'))
        self.assert_bloqueado(r, saida, texto, 'SEGREDO? sub/dentro/notas.md:1: atribuição de segredo', 1)

    def test_nome_com_acento_e_espaco_bloqueia_sem_mostrar_o_valor(self):
        r = Repo()
        r.escrever('pasta com espaço/configuração final.py', 'senha = "' + FALSO32 + '"\n')
        r.git('add', '.')
        saida, texto = r.commit()
        self.assert_bloqueado(r, saida, texto, 'configuração final.py:1: atribuição de segredo', 1)

    def test_pasta_proibida_em_qualquer_nivel_bloqueia(self):
        for pasta in ('backups', 'a/b/backups', 'x/logs'):
            with self.subTest(pasta=pasta):
                r = Repo()
                r.escrever(pasta + '/qualquer.txt', 'nada\n')
                r.git('add', '-f', '.')
                saida, texto = r.commit()
                self.assertNotEqual(saida, 0, texto)
                self.assertIn(f'SEGREDO? {pasta}/qualquer.txt: pasta proibida', texto)

    def test_arquivo_renomeado_com_linha_nova_e_pego_na_linha_da_versao_nova(self):
        r = Repo()
        r.escrever('antes.txt', ''.join(f'linha {n}\n' for n in range(1, 11)))
        r.git('add', 'antes.txt')
        r.git('commit', '-q', '--no-verify', '-m', 'texto')
        r.git('mv', 'antes.txt', 'depois.txt')
        r.escrever('depois.txt', ''.join(f'linha {n}\n' for n in range(1, 11)) + 'secret: ' + FALSO32 + '\n')
        r.git('add', 'depois.txt')
        saida, texto = r.commit()
        self.assert_bloqueado(r, saida, texto, 'SEGREDO? depois.txt:11: atribuição de segredo', 2)

    def test_arquivo_latin1_com_crlf_e_bytes_invalidos_ainda_e_varrido(self):
        r = Repo()
        r.escrever('legado.txt', b'a = 1\r\ncoment\xe1rio \xe9\xe7\r\nsecret = "' + FALSO32.encode() + b'"\r\n')
        r.git('add', 'legado.txt')
        saida, texto = r.commit()
        self.assert_bloqueado(r, saida, texto, 'SEGREDO? legado.txt:3: atribuição de segredo', 1)

    def test_apagar_a_linha_com_o_segredo_nao_bloqueia(self):
        r = Repo()
        r.escrever('notas.txt', 'a\nsecret = "' + FALSO32 + '"\nb\n')
        r.git('add', 'notas.txt')
        r.git('commit', '-q', '--no-verify', '-m', 'entrou por engano')
        r.escrever('notas.txt', 'a\nb\n')
        r.git('add', 'notas.txt')
        saida, texto = r.commit()
        self.assertEqual(saida, 0, texto)
        self.assertNotIn(FALSO32, texto)

    def test_amend_com_segredo_staged_tambem_passa_pelo_portao(self):
        r = Repo()
        r.escrever('notas.txt', 'a\n')
        r.git('add', 'notas.txt')
        self.assertEqual(r.commit()[0], 0)
        r.escrever('notas.txt', 'a\nsecret = "' + FALSO32 + '"\n')
        r.git('add', 'notas.txt')
        saida, texto = r.commit('--amend', '--no-edit')
        self.assert_bloqueado(r, saida, texto, 'SEGREDO? notas.txt:2: atribuição de segredo', 2)

    def test_no_verify_passa_por_cima_como_o_plano_documenta(self):
        r = Repo()
        r.escrever('notas.txt', 'secret = "' + FALSO32 + '"\n')
        r.git('add', 'notas.txt')
        saida, texto = r.commit('--no-verify')
        self.assertEqual(saida, 0, texto)
        self.assertEqual(r.commits(), 2)

    def test_variantes_de_backup_do_arquivo_do_token_tambem_bloqueiam(self):
        """Q1: `api_token.txt.bak`, `api_token.txt~` e afins levam o mesmo token (64 hex sozinhos numa linha, que a
        varredura de linhas não reconhece) e passam pelo portão porque o nome não bate com o padrão exato."""
        nomes = ['api_token.txt.bak', 'api_token.txt~', 'api_token.txt.old', 'api_cabecalho.txt.bak',
                 '_chat.txt.bak', 'ml_catalogo.json.bak']
        for nome in nomes:
            with self.subTest(nome=nome):
                r = Repo()
                r.escrever(nome, TOKEN_HEX + '\n')
                r.git('add', '-f', nome)
                saida, texto = r.commit()
                self.assertNotEqual(saida, 0, f'{nome} entrou no commit: {texto}')
                self.assertNotIn(TOKEN_HEX, texto)

    def test_linha_enorme_nao_trava_a_varredura(self):
        """Linhas patológicas de 5 MB (sem ReDoS nos cinco padrões): cada uma varre em bem menos de 5 s."""
        linhas = ['secret' + ' ' * 5_000_000, 'secret ' * 700_000, 'Bearer ' + 'a' * 5_000_000,
                  'TG-' * 1_500_000, 'APP_USR-1' + '-' * 5_000_000, 'token="' * 700_000]
        for linha in linhas:
            with self.subTest(inicio=linha[:12]):
                t0 = time.monotonic()
                V.varrer_linhas('x', [(1, linha)])
                self.assertLess(time.monotonic() - t0, 5)


# ================================================================ CA5: backup

def criar_banco(caminho, itens=5, wal=True):
    con = sqlite3.connect(caminho)
    if wal:
        con.execute('PRAGMA journal_mode=WAL')
    con.execute('CREATE TABLE items (id INTEGER PRIMARY KEY, loja TEXT, item_id TEXT)')
    con.executemany('INSERT INTO items (loja, item_id) VALUES (?, ?)', [('ml', f'I{n}') for n in range(itens)])
    con.commit()
    con.close()


def integridade(caminho):
    con = sqlite3.connect(f'file:{caminho}?mode=ro', uri=True)
    try:
        return con.execute('PRAGMA integrity_check').fetchone()[0], con.execute('SELECT COUNT(*) FROM items').fetchone()[0]
    finally:
        con.close()


RODA_COM_RELOGIO_FIXO = '''
import datetime, os, signal, sys
sys.path.insert(0, %(raiz)r)
import backup_banco as B
B.agora = lambda: datetime.datetime(2026, 11, 9, 12, 0, 0)
if os.environ.get('MATAR_DEPOIS_DA_COPIA') == '1':
    copiar = B.copiar
    def copiar_e_morrer(db, destino):
        copiar(db, destino)                    # a cópia completa já está no .parcial...
        os.kill(os.getpid(), signal.SIGKILL)   # ...e o processo morre antes de publicar
    B.copiar = copiar_e_morrer
sys.exit(B.main(['--motivo', sys.argv[1]]))
''' % {'raiz': RAIZ}


class Backup(unittest.TestCase):

    def setUp(self):
        self.dir = nova_pasta()
        self.db = os.path.join(self.dir, 'achadinhos.db')
        self.backups = os.path.join(self.dir, 'backups')
        criar_banco(self.db)

    def env(self, **extra):
        env = {k: v for k, v in os.environ.items() if not k.startswith('ACHADINHOS_')}
        env.update(PROXIES, ACHADINHOS_DB=self.db, PYTHONDONTWRITEBYTECODE='1', **extra)
        return env

    def cli(self, motivo, **extra):
        p = subprocess.run([sys.executable, os.path.join(RAIZ, 'backup_banco.py'), '--motivo', motivo],
                           cwd=self.dir, env=self.env(**extra), capture_output=True, text=True, timeout=120)
        return p.returncode, p.stdout, p.stderr

    def autos(self):
        return sorted(n for n in os.listdir(self.backups) if n.startswith('auto-') and n.endswith('.db'))

    def test_rotacao_com_motivos_misturados_fica_com_os_14_mais_novos_no_total(self):
        os.makedirs(self.backups, mode=0o700)
        antigos = []
        for dia in range(1, 21):   # 20 backups de 4 motivos, um por dia
            motivo = ('ml', 'shopee', 'amazon', 'reiniciar')[dia % 4]
            antigos.append(f'auto-{motivo}-202610{dia:02d}-120000.db')
        antigos += ['auto-ml-20261015-120000-1.db', 'auto-shopee-20261015-120000-2.db']   # colisões no mesmo segundo
        for nome in antigos:
            with open(os.path.join(self.backups, nome), 'w') as f:
                f.write('x')
        manuais = ['antes-ml-api.db', 'achadinhos-20260101.db', 'auto-ml-20261001-000000.db.parcial', 'leia.txt']
        for nome in manuais:
            with open(os.path.join(self.backups, nome), 'w') as f:
                f.write('x')
        saida, out, err = self.cli('ml')
        self.assertEqual(saida, 0, err)
        restantes = self.autos()
        self.assertEqual(len(restantes), 14, restantes)
        # os mais novos pela data do nome (e, na mesma data, pelo sufixo), contando o backup novo
        esperados = sorted(antigos, key=lambda n: (n.split('-')[2], n.split('-')[3].split('.')[0],
                                                   int(n.rsplit('-', 1)[1][:-3]) if n.count('-') == 4 else 0),
                           reverse=True)[:13]
        novo = [n for n in restantes if n not in antigos]
        self.assertEqual(len(novo), 1, restantes)
        self.assertEqual(sorted(n for n in restantes if n in antigos), sorted(esperados))
        for nome in manuais:
            self.assertTrue(os.path.exists(os.path.join(self.backups, nome)), nome)

    def test_parcial_deixado_por_sigkill_nao_quebra_o_backup_seguinte(self):
        script = os.path.join(self.dir, 'roda.py')
        with open(script, 'w') as f:
            f.write(RODA_COM_RELOGIO_FIXO)
        base = [sys.executable, script, 'ml']
        env = self.env()
        morto = subprocess.run(base, cwd=self.dir, env=dict(env, MATAR_DEPOIS_DA_COPIA='1'),
                               capture_output=True, text=True, timeout=120)
        self.assertEqual(morto.returncode, -signal.SIGKILL)
        sobras = sorted(os.listdir(self.backups))
        self.assertEqual(sobras, ['auto-ml-20261109-120000.db.parcial'])   # a sobra do SIGKILL
        # o relógio fixo faz o backup seguinte querer o MESMO nome: ele pula e fica com o sufixo
        vivo = subprocess.run(base, cwd=self.dir, env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(vivo.returncode, 0, vivo.stderr)
        self.assertEqual(self.autos(), ['auto-ml-20261109-120000-1.db'])
        self.assertEqual(integridade(os.path.join(self.backups, self.autos()[0])), ('ok', 5))
        self.assertEqual(os.stat(os.path.join(self.backups, self.autos()[0])).st_mode & 0o777, 0o600)
        # e o que o SIGKILL deixou segue intacto (nada o apaga sem querer)
        self.assertTrue(os.path.exists(os.path.join(self.backups, 'auto-ml-20261109-120000.db.parcial')))

    def test_seis_backups_ao_mesmo_tempo_geram_seis_arquivos_distintos_e_todos_conferem(self):
        procs = [subprocess.Popen([sys.executable, os.path.join(RAIZ, 'backup_banco.py'), '--motivo', 'ml'],
                                  cwd=self.dir, env=self.env(), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  text=True) for _ in range(6)]
        resultados = [(p.wait(120), p.stdout.read(), p.stderr.read()) for p in procs]
        for saida, out, err in resultados:
            self.assertEqual(saida, 0, err)
            self.assertRegex(out, r'^backup: .*/backups/auto-ml-\d{8}-\d{6}(-\d{1,3})?\.db ok 5 itens\n$')
        self.assertEqual(len({out for _, out, _ in resultados}), 6)
        autos = self.autos()
        self.assertEqual(len(autos), 6)
        for nome in autos:
            self.assertEqual(integridade(os.path.join(self.backups, nome)), ('ok', 5))
        self.assertEqual([n for n in os.listdir(self.backups) if n not in autos], [])   # sem .parcial nem -wal/-shm

    def test_rotacao_que_perde_a_corrida_por_um_arquivo_ja_apagado_nao_vira_aviso_nem_para_no_meio(self):
        """Q2: dois backups ao mesmo tempo (atualizar-ml.sh e atualizar-shopee.sh podem rodar juntos) rotacionam a
        mesma pasta. Se o outro apagou o arquivo entre o stat e o unlink, a rotação aborta com um AVISO falso e
        deixa os demais para trás. Aqui o "outro processo" é simulado de forma determinística."""
        os.makedirs(self.backups, mode=0o700)
        for dia in range(1, 21):
            with open(os.path.join(self.backups, f'auto-ml-202610{dia:02d}-120000.db'), 'w') as f:
                f.write('x')
        runner = textwrap.dedent('''
            import os, sys
            sys.path.insert(0, %r)
            import backup_banco as B
            original = os.unlink
            def unlink_que_perde_a_corrida(nome, dir_fd=None):
                original(nome, dir_fd=dir_fd)      # o outro processo apagou primeiro...
                original(nome, dir_fd=dir_fd)      # ...e o nosso unlink acha o arquivo sumido
            B.os.unlink = unlink_que_perde_a_corrida
            apagados = B.rotacionar(sys.argv[1], 14, 'auto-ml-20261101-120000.db')
            print(len(apagados))
        ''') % RAIZ
        p = subprocess.run([sys.executable, '-c', runner, self.backups], cwd=self.dir, env=self.env(),
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr[-400:])   # não levanta FileNotFoundError
        self.assertEqual(len(self.autos()), 14, self.autos())   # e não para no primeiro arquivo sumido

    def test_rotacao_em_corrida_real_termina_com_exatamente_14(self):
        os.makedirs(self.backups, mode=0o700)
        for dia in range(1, 15):
            with open(os.path.join(self.backups, f'auto-ml-202610{dia:02d}-120000.db'), 'w') as f:
                f.write('x')
        procs = [subprocess.Popen([sys.executable, os.path.join(RAIZ, 'backup_banco.py'), '--motivo', 'shopee'],
                                  cwd=self.dir, env=self.env(), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  text=True) for _ in range(4)]
        for p in procs:
            self.assertEqual(p.wait(120), 0, p.stderr.read())
        self.assertEqual(len(self.autos()), 14, self.autos())
        self.assertEqual([n for n in os.listdir(self.backups) if not n.startswith('auto-')], [])
        self.assertEqual(sum(1 for n in self.autos() if n.startswith('auto-shopee-')), 4)

    def test_parcial_de_sigkill_com_mtime_antigo_some_na_rotacao_seguinte_e_o_recente_fica(self):
        """Lacuna da rodada 1: a sobra de SIGKILL (com -wal/-shm/-journal) some quando passa de 6 h sem mudar;
        a de agora, que pode ser de um backup em curso, fica."""
        os.makedirs(self.backups, mode=0o700)
        antigo = 'auto-ml-20261001-120000.db.parcial'
        recente = 'auto-ml-20261002-120000.db.parcial'
        for nome in (antigo, antigo + '-wal', antigo + '-shm', antigo + '-journal', recente, recente + '-wal'):
            with open(os.path.join(self.backups, nome), 'w') as f:
                f.write('x')
        velho = time.time() - 7 * 3600
        for nome in (antigo, antigo + '-wal', antigo + '-shm', antigo + '-journal'):
            os.utime(os.path.join(self.backups, nome), (velho, velho))
        saida, out, err = self.cli('ml')
        self.assertEqual(saida, 0, err)
        self.assertEqual(sorted(n for n in os.listdir(self.backups) if n not in self.autos()),
                         [recente, recente + '-wal'])

    def test_rotacao_em_corrida_real_nao_imprime_aviso_em_nenhuma_de_20_rodadas(self):
        """Q2 de novo, agora procurando o AVISO falso: 5 rodadas de 4 backups simultâneos sobre 14 antigos."""
        for rodada in range(5):
            pasta = os.path.join(self.dir, f'r{rodada}')
            os.makedirs(os.path.join(pasta, 'backups'), mode=0o700)
            criar_banco(os.path.join(pasta, 'achadinhos.db'))
            for dia in range(1, 15):
                with open(os.path.join(pasta, 'backups', f'auto-ml-202610{dia:02d}-120000.db'), 'w') as f:
                    f.write('x')
            procs = [subprocess.Popen([sys.executable, os.path.join(RAIZ, 'backup_banco.py'), '--motivo', 'shopee'],
                                      cwd=pasta, env=dict(self.env(), ACHADINHOS_DB=os.path.join(pasta, 'achadinhos.db')),
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      text=True) for _ in range(4)]
            for p in procs:
                saida, err, out = p.wait(120), p.stderr.read(), p.stdout.read()
                self.assertEqual(saida, 0, err)
                self.assertNotIn('AVISO', err + out)
            restantes = [n for n in os.listdir(os.path.join(pasta, 'backups'))]
            self.assertEqual(len(restantes), 14, restantes)
            self.assertEqual(sum(1 for n in restantes if n.startswith('auto-shopee-')), 4, restantes)

    def test_banco_sendo_escrito_durante_o_backup_gera_copia_consistente(self):
        escritor = textwrap.dedent('''
            import sqlite3, sys, time
            con = sqlite3.connect(sys.argv[1], timeout=30)
            fim = time.monotonic() + 8
            n = 0
            while time.monotonic() < fim:
                con.execute("INSERT INTO items (loja, item_id) VALUES ('amazon', ?)", (f'W{n}',))
                if n % 5 == 0:
                    con.commit()
                n += 1
            con.commit()
        ''')
        p = subprocess.Popen([sys.executable, '-c', escritor, self.db], cwd=self.dir)
        try:
            time.sleep(0.5)
            for _ in range(6):
                saida, out, err = self.cli('ml')
                self.assertEqual(saida, 0, err)
                declarado = int(out.rsplit(' ok ', 1)[1].split()[0])
                caminho = out.split('backup: ', 1)[1].split(' ok ', 1)[0]
                situacao, itens = integridade(caminho)
                self.assertEqual(situacao, 'ok')
                self.assertEqual(itens, declarado)   # o número impresso é o da cópia
                self.assertGreaterEqual(itens, 5)
        finally:
            p.wait(60)
        self.assertEqual(p.returncode, 0)
        self.assertEqual([n for n in os.listdir(self.backups) if not n.endswith('.db')], [])


# ================================================================ CA4: trava, com processos de verdade

DONO = '''
import sys, time
sys.path.insert(0, %(raiz)r)
import servidor as S
with S.travar_rodada(sys.argv[1]):
    print('segurando', flush=True)
    time.sleep(120)
''' % {'raiz': RAIZ}

# Roda o main de verdade com o miolo da rodada trocado por uma pausa: a trava e o resto do caminho são os reais.
RODADA_LENTA = '''
import os, sys, time
sys.path.insert(0, %(raiz)r)
import atualizar_precos as A
import coletar_amazon as C
def lenta(*a, **k):
    time.sleep(float(os.environ['PAUSA']))
    return 0
quem = sys.argv[1]
if quem == 'atualizar-amazon':
    A._rodar_amazon = lenta
    sys.exit(A.main(['amazon']))
if quem == 'coletar-amazon':
    C.coletar_buscas = lenta
    C.main(['buscas', '--cat', 'Pets'])
    sys.exit(0)
''' % {'raiz': RAIZ}


class Trava(unittest.TestCase):

    def setUp(self):
        self.dir = nova_pasta()
        self.db = os.path.join(self.dir, 'achadinhos.db')
        self.addCleanup(self.encerrar)
        self.filhos = []

    def encerrar(self):
        for p in self.filhos:
            if p.poll() is None:
                p.kill()
            p.wait()
            for f in (p.stdout, p.stderr):
                if f:
                    f.close()

    def env(self, **extra):
        env = {k: v for k, v in os.environ.items() if not k.startswith('ACHADINHOS_')}
        env.update(PROXIES, no_proxy='', PYTHONDONTWRITEBYTECODE='1', ACHADINHOS_DB=self.db,
                   ACHADINHOS_FEITOS=os.path.join(self.dir, 'feitos-amazon.txt'),
                   ACHADINHOS_FEITOS_SHOPEE=os.path.join(self.dir, 'feitos-shopee.txt'),
                   ACHADINHOS_FEITOS_ATUALIZAR=os.path.join(self.dir, 'feitos-atualizar.txt'),
                   ACHADINHOS_ML_TOKENS=os.path.join(self.dir, 'ml_tokens.json'),
                   ACHADINHOS_ML_CATALOGO=os.path.join(self.dir, 'ml_catalogo.json'),
                   ACHADINHOS_API_TOKEN_ARQUIVO='/nao/existe', ACHADINHOS_DISPARO='0')
        env.update(extra)
        return env

    def popen(self, argv, **extra):
        p = subprocess.Popen(argv, cwd=self.dir, env=self.env(**extra), stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.filhos.append(p)
        return p

    def dono(self, loja):
        p = self.popen([sys.executable, '-c', DONO, loja])
        self.assertEqual(p.stdout.readline().strip(), 'segurando')
        return p

    def cli(self, script, *argv, **extra):
        r = subprocess.run([sys.executable, os.path.join(RAIZ, script), *argv], cwd=self.dir, env=self.env(**extra),
                           stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
        self.assertNotIn('Traceback', r.stderr)
        return r.returncode, r.stdout, r.stderr

    def test_dono_em_outro_processo_exclui_as_duas_formas_da_mesma_loja_e_so_ela(self):
        self.dono('amazon')
        self.assertEqual(self.cli('coletar_amazon.py', 'buscas', '--cat', 'Pets')[0], 4)
        self.assertEqual(self.cli('atualizar_precos.py', 'amazon', '--cat', 'Pets')[0], 4)
        # ML e Shopee passam da trava e param nos motivos de sempre (tokens e credencial ausentes)
        self.assertEqual(self.cli('atualizar_precos.py', 'ml', '--cat', 'Pets')[0], 2)
        self.assertEqual(self.cli('atualizar_precos.py', 'shopee', '--cat', 'Pets')[0], 2)
        self.assertFalse(os.path.exists(self.db), 'a rodada recusada nunca abriu o banco')

    def test_ml_e_amazon_seguram_ao_mesmo_tempo_e_kill_9_so_libera_a_sua(self):
        amazon = self.dono('amazon')
        self.dono('ml')   # as duas lojas seguras ao mesmo tempo, por dois processos
        self.assertEqual(self.cli('atualizar_precos.py', 'amazon')[0], 4)
        self.assertEqual(self.cli('atualizar_precos.py', 'ml', '--cat', 'Pets')[0], 4)
        os.kill(amazon.pid, signal.SIGKILL)
        amazon.wait(30)
        saida, _, err = self.cli('coletar_amazon.py', 'buscas', '--cat', 'Aba que nao existe')
        self.assertEqual(saida, 2, err)   # passou da trava e parou na aba inválida
        self.assertEqual(self.cli('atualizar_precos.py', 'ml', '--cat', 'Pets')[0], 4)   # a do ML segue segura

    def test_corrida_de_oito_rodadas_da_amazon_so_uma_entra(self):
        """4 coletas e 4 atualizações da Amazon largam juntas: exatamente uma roda, as outras sete saem com 4."""
        procs = []
        for i in range(8):
            quem = 'coletar-amazon' if i % 2 else 'atualizar-amazon'
            procs.append(self.popen([sys.executable, '-c', RODADA_LENTA, quem], PAUSA='3'))
        codigos = [p.wait(120) for p in procs]
        erros = [p.stderr.read() for p in procs]   # cada pipe é lido uma vez só
        self.assertEqual(sorted(codigos), [0, 4, 4, 4, 4, 4, 4, 4], erros)
        for codigo, err in zip(codigos, erros):
            if codigo == 4:
                self.assertIn('PAROU: outra rodada de amazon está em andamento', err)
        # depois que a dona terminou, a trava está livre
        saida, _, err = self.cli('coletar_amazon.py', 'buscas', '--cat', 'Aba que nao existe')
        self.assertEqual(saida, 2, err)

    def test_banco_numa_pasta_que_nao_existe_sai_com_4_sem_traceback(self):
        saida, _, err = self.cli('atualizar_precos.py', 'amazon', ACHADINHOS_DB=os.path.join(self.dir, 'nao', 'ha.db'))
        self.assertEqual(saida, 4, err)
        self.assertIn('PAROU: não consegui pegar a trava da rodada de amazon', err)
        self.assertNotIn(self.dir, err)


# ================================================================ CA6: scripts de operação com as abas reais

class OperacaoAbasReais(TO.Base):

    def setUp(self):
        super().setUp()
        shutil.copy2(os.path.join(RAIZ, 'buscas.json'), os.path.join(self.raiz, 'buscas.json'))
        with open(os.path.join(RAIZ, 'buscas.json'), encoding='utf-8') as f:
            self.abas = [k for k, v in json.load(f).items() if isinstance(v, list)]

    def test_as_17_abas_reais_chegam_inteiras_e_na_ordem_do_arquivo(self):
        self.assertEqual(len(self.abas), 17)
        self.assertIn('Cama, Mesa e Banho', self.abas)
        p = self.rodar('atualizar-ml.sh', entrada='\n', saidas=['0'] * 18)
        self.assertEqual(p.returncode, 0, self.saida)
        self.assertEqual(self.argvs(), [['backup_banco.py', '--motivo', 'ml']] + [TO.ml(a) for a in self.abas])
        for a in self.abas:
            self.assertIn(f'  {a} | saída 0 | RESUMO ml: falso {a}', p.stdout)

    def test_aba_com_virgula_e_acento_em_nfd_vira_um_argumento_so_em_nfc(self):
        nfd = unicodedata.normalize('NFD', 'Celulares e Informática')
        self.assertNotEqual(nfd, 'Celulares e Informática')
        p = self.rodar('atualizar-ml.sh', 'Cama, Mesa e Banho', nfd, 'TV, Alexa e Casa Conectada', entrada='\n',
                       saidas=['0'] * 4)
        self.assertEqual(p.returncode, 0, self.saida)
        self.assertEqual(self.argvs()[1:], [TO.ml('Cama, Mesa e Banho'), TO.ml('Celulares e Informática'),
                                            TO.ml('TV, Alexa e Casa Conectada')])

    def test_shopee_com_aba_de_virgula(self):
        p = self.rodar('atualizar-shopee.sh', 'Cama, Mesa e Banho', entrada='A\nS\n', saidas=['0'] * 4)
        self.assertEqual(p.returncode, 0, self.saida)
        self.assertEqual(self.argvs()[-2:], [TO.shopee('Cama, Mesa e Banho', '--max-chamadas', '10'),
                                              TO.shopee('Cama, Mesa e Banho')])

    def test_pausa_so_entre_as_abas_16_esperas_para_17_abas_e_nenhuma_depois_da_ultima(self):
        p = self.rodar('atualizar-ml.sh', entrada='\n', saidas=['0'] + ['3'] * 17, pausa='7')
        self.assertEqual(p.returncode, 3, self.saida)
        self.assertEqual(self.argvs('sleep'), [['7']] * 16)
        self.assertEqual(len([a for a in self.argvs() if a[:1] == ['atualizar_precos.py']]), 17)

    def test_saida_3_so_na_ultima_aba_nao_espera_nada(self):
        p = self.rodar('atualizar-ml.sh', entrada='\n', saidas=['0'] * 17 + ['3'], pausa='7')
        self.assertEqual(p.returncode, 3, self.saida)
        self.assertEqual(self.argvs('sleep'), [])

    def test_saida_3_numa_aba_do_meio_espera_uma_vez_e_o_resto_segue(self):
        p = self.rodar('atualizar-ml.sh', 'Games', 'Pets', 'Moda e Viagem', entrada='\n',
                       saidas=['0', '0', '3', '0'], pausa='9')
        self.assertEqual(p.returncode, 3, self.saida)   # "alguma aba parou": o código final lembra
        self.assertEqual(self.argvs('sleep'), [['9']])
        self.assertEqual(len([a for a in self.argvs() if a[:1] == ['atualizar_precos.py']]), 3)

    def test_segredo_com_caracteres_especiais_chega_intacto_so_ao_ambiente_do_comando(self):
        estranho = 'Ab$HOME"x`id`y\\z;&|<>*?(){}#!%'
        p = self.rodar('atualizar-ml.sh', 'Games', entrada=estranho + '\n', saidas=['0', '0'])
        self.assertEqual(p.returncode, 0, self.saida)
        for c in self.chamadas():
            if c['argv'][:1] == ['atualizar_precos.py']:
                self.assertEqual(c['env'], {'ACHADINHOS_ML_SECRET': estranho})
            else:
                self.assertEqual(c['env'], {}, c['argv'])
        self.assert_segredos_fora(p, estranho)

    def test_appid_e_secret_da_shopee_com_caracteres_especiais(self):
        app_id, secret = 'id$x"y', "se'cr\\et`z`$(w)"
        p = self.rodar('atualizar-shopee.sh', entrada=f'{app_id}\n{secret}\n', saidas=['0'] * 4)
        self.assertEqual(p.returncode, 0, self.saida)
        chamadas = [c for c in self.chamadas() if c['argv'][:1] in (['coletar_shopee.py'], ['atualizar_precos.py'])]
        self.assertEqual(len(chamadas), 3)
        for c in chamadas:
            self.assertEqual(c['env'], {'ACHADINHOS_SHOPEE_APP_ID': app_id, 'ACHADINHOS_SHOPEE_SECRET': secret})
        self.assert_segredos_fora(p, secret, app_id)


# ================================================================ CA12: verificar.py --servidor de verdade

ARQUIVOS_VERSAO = ('servidor.py', 'disparo.py', 'genero.py', 'api_ofertas.py')


class VersaoDoServidorNoAr(unittest.TestCase):
    """`python3 verificar.py --servidor <porta>` como o dono roda (subprocesso), contra o servidor de uma CÓPIA
    dos quatro .py: em dia, depois de mexer em cada um, e de novo em dia ao desfazer."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix='achadinhos-qa-versao-')
        cls.addClassCleanup(shutil.rmtree, cls.dir, ignore_errors=True)
        cls.copia = os.path.join(cls.dir, 'codigo')
        os.mkdir(cls.copia)
        for nome in ARQUIVOS_VERSAO:
            shutil.copy2(os.path.join(RAIZ, nome), cls.copia)
        cls.porta = TS.porta_livre()
        cls.log = open(os.path.join(cls.dir, 'servidor.log'), 'wb')
        cls.addClassCleanup(cls.log.close)
        cls.proc = subprocess.Popen([sys.executable, '-u', 'servidor.py'], cwd=cls.copia,
                                    env=TS.ambiente(os.path.join(cls.dir, 'copia.db'), cls.porta),
                                    stdout=cls.log, stderr=subprocess.STDOUT)
        cls.addClassCleanup(cls.parar)
        for _ in range(200):
            if cls.proc.poll() is not None:
                raise RuntimeError('o servidor da cópia saiu')
            try:
                with open(os.path.join(cls.dir, 'servidor.log'), encoding='utf-8') as f:
                    if 'Código ' in f.read():
                        break
            except OSError:
                pass
            time.sleep(0.05)

    @classmethod
    def parar(cls):
        if cls.proc.poll() is None:
            cls.proc.terminate()
            try:
                cls.proc.wait(5)
            except subprocess.TimeoutExpired:
                cls.proc.kill()
                cls.proc.wait()

    def verificar(self):
        p = subprocess.run([sys.executable, os.path.join(RAIZ, 'verificar.py'), '--servidor', str(self.porta)],
                           cwd=self.dir, env={'PATH': os.environ.get('PATH', '')}, capture_output=True, text=True,
                           timeout=60)
        return p.returncode, p.stdout + p.stderr

    def test_cada_um_dos_quatro_arquivos_faz_o_comando_mandar_reiniciar(self):
        saida, texto = self.verificar()
        self.assertEqual(saida, 0, texto)
        self.assertIn('em dia', texto)
        for nome in ARQUIVOS_VERSAO:
            with self.subTest(arquivo=nome):
                caminho = os.path.join(self.copia, nome)
                with open(caminho, 'rb') as f:
                    original = f.read()
                try:
                    with open(caminho, 'wb') as f:
                        f.write(original + b'\n# edicao do QA\n')
                    saida, texto = self.verificar()
                    self.assertEqual(saida, 1, texto)
                    self.assertIn('reinicie', texto)
                    self.assertNotIn(self.dir, texto)   # nenhum caminho absoluto na tela
                finally:
                    with open(caminho, 'wb') as f:
                        f.write(original)
                saida, texto = self.verificar()
                self.assertEqual(saida, 0, texto)

    def test_so_tocar_no_arquivo_sem_mudar_os_bytes_continua_em_dia(self):
        caminho = os.path.join(self.copia, 'genero.py')
        os.utime(caminho, (time.time() + 3600, time.time() + 3600))
        saida, texto = self.verificar()
        self.assertEqual(saida, 0, texto)

    def test_rota_com_query_e_pedido_concorrente_respondem_o_mesmo_contrato(self):
        import http.client

        def pedir(caminho):
            con = http.client.HTTPConnection('127.0.0.1', self.porta, timeout=10)
            try:
                con.request('GET', caminho, headers={'Host': f'localhost:{self.porta}'})
                r = con.getresponse()
                return r.status, r.read()
            finally:
                con.close()

        respostas = []
        fios = [threading.Thread(target=lambda: respostas.append(pedir('/api/versao?x=1'))) for _ in range(20)]
        for t in fios:
            t.start()
        for t in fios:
            t.join(30)
        self.assertEqual(len(respostas), 20)
        self.assertEqual({r[0] for r in respostas}, {200})
        self.assertEqual(len({r[1] for r in respostas}), 1)   # todos veem o mesmo estado


if __name__ == '__main__':
    unittest.main()
