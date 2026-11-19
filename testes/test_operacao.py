#!/usr/bin/env python3
"""Testes dos scripts de operação em operacao/ (docs/produto/planos/endurecer-engenharia-e-operacao.md,
etapa 7: CA5 e CA6; docs/produto/planos/endurecer-entrega2.md, etapa 3: CA11, o --sem-chave do
atualizar-ml.sh; etapa 4: CA11, a rodada automática automatico.sh e o instalador dos timers
instalar-timers.sh).

Uso:  python3 testes/test_operacao.py -v

- Estáticos: `bash -n`, nenhum export, todo `read` de segredo com -rs, nenhum /tmp nem rastreio ligado (o
  comum.sh o desliga com `set +x` antes de qualquer read), log em logs/, segredo só no ambiente do python3.
- Funcionais: cada teste monta numa pasta temporária uma cópia mínima da árvore (operacao/ e um buscas.json
  falso) e roda o script de verdade, com um `python3` e um `sleep` falsos no PATH. O falso registra argv, pasta
  e quais variáveis de segredo recebeu, e devolve os códigos programados no arquivo `saidas` (um por chamada).
  As chamadas `python3 -I -c` (leitura do buscas.json) vão para o Python real.
  Nada roda sobre a raiz real: nem backup_banco.py, nem atualizar_precos.py, nem coletar_shopee.py.
- Rodada automática e instalador: também `git`, `notify-send` e `systemctl` falsos no PATH (cada um com a sua
  fila de saídas) e XDG_CONFIG_HOME numa pasta temporária. Nenhum teste chama o systemctl, o notify-send nem o
  instalador de verdade; o `systemd-analyze --user verify` (se existir) só lê unidades geradas na pasta
  temporária.
Só biblioteca padrão.
"""
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import signal
import tempfile
import time
import unicodedata
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OPERACAO = os.path.join(RAIZ, 'operacao')
RODADAS = ('atualizar-ml.sh', 'atualizar-shopee.sh', 'atualizar-amazon.sh')
AUTOMACAO = ('automatico.sh', 'instalar-timers.sh')   # endurecer-entrega2, etapa 4
SCRIPTS = RODADAS + AUTOMACAO
TODOS = ('comum.sh',) + SCRIPTS
SEGREDOS = ('ACHADINHOS_ML_SECRET', 'ACHADINHOS_SHOPEE_APP_ID', 'ACHADINHOS_SHOPEE_SECRET')

# Ordem do arquivo; "Saúde e Bem-estar" em NFC, como no buscas.json real.
BUSCAS_FALSO = {'Games': ['Console'], 'Saúde e Bem-estar': ['Whey'], 'Perfumes e Perfumaria': ['Perfume']}
ABAS = list(BUSCAS_FALSO)

CHAVE_ML = 'CHAVE-ML-teste-7f3a9'
APP_ID = 'APPID-teste-41c2'
SECRET_SHOPEE = 'SECRET-shopee-teste-b8d0'

FALSO = r'''#!{python}
import json, os, signal, sys, time
pasta = os.environ['FALSO_DIR']
prog = os.path.basename(sys.argv[0])
args = sys.argv[1:]
reg = {{'prog': prog, 'argv': args, 'cwd': os.getcwd(),
        'env': {{k: os.environ[k] for k in {segredos!r} if k in os.environ}}}}
if prog == 'python3' and args[:1] == ['-I']:
    reg['real'] = True
if os.environ.get('FALSO_LER_STDIN') == '1':   # só nos testes do --sem-chave: o que este comando leria
    reg['stdin'] = sys.stdin.read() if sys.stdin is not None else None
if os.environ.get('FALSO_LISTAR'):   # só nos testes do instalador: as unidades que existiam nesta chamada
    try:
        reg['dir'] = sorted(os.listdir(os.environ['FALSO_LISTAR']))
    except FileNotFoundError:
        reg['dir'] = None
with open(os.path.join(pasta, 'chamadas.jsonl'), 'a', encoding='utf-8') as f:
    f.write(json.dumps(reg) + '\n')
if reg.get('real'):
    os.execv(sys.executable, [sys.executable] + args)
if prog == 'sleep':
    if os.environ.get('FALSO_SLEEP_REAL') == '1':   # só no teste do Ctrl+C na pausa
        try:
            time.sleep(min(float(args[0]), 30))
        except KeyboardInterrupt:   # morre pelo sinal, como o sleep de verdade
            signal.signal(signal.SIGINT, signal.SIG_DFL)
            os.kill(os.getpid(), signal.SIGINT)
    sys.exit(0)
# o python3 lê a fila `saidas`; os outros falsos (git, notify-send, systemctl) a sua, `saidas-<prog>`, que pode
# faltar (sai com 0)
fila = os.path.join(pasta, 'saidas' if prog == 'python3' else 'saidas-' + prog)
try:
    with open(fila, encoding='utf-8') as f:
        linhas = f.read().splitlines()
except FileNotFoundError:
    sys.exit(0)
atual = linhas[0] if linhas else '0'
with open(fila, 'w', encoding='utf-8') as f:
    f.write(''.join(l + '\n' for l in linhas[1:]))
codigo, _, tipo = atual.partition(' ')
codigo = int(codigo)
script = args[0] if args else ''
if tipo == 'int':   # espera o Ctrl+C e sai com 130, como o atualizar_precos.py
    print('comecou', flush=True)
    try:
        time.sleep(30)
    except KeyboardInterrupt:
        print('Interrompido (falso).', file=sys.stderr, flush=True)
        sys.exit(130)
if script == 'backup_banco.py':
    if codigo == 0:
        print('backup: backups/auto-falso.db ok 1 itens', flush=True)
    else:
        print('ERRO: backup falhou (falso); nenhum backup novo foi gravado', file=sys.stderr, flush=True)
elif script == 'atualizar_precos.py':
    loja = args[1]
    cat = args[args.index('--cat') + 1] if '--cat' in args else 'todas'
    if codigo in (0, 3):
        print(f'RESUMO {{loja}}: falso {{cat}}', flush=True)
    if codigo == 3 and tipo == 'teto':
        print('PAROU: chegou ao teto de chamadas (--max-chamadas); rode de novo para seguir.', file=sys.stderr)
    elif codigo == 3:
        print('PAROU: a loja bloqueou (captcha, 503, 429 ou limite da API).', file=sys.stderr)
    elif codigo == 4:
        print(f'PAROU: outra rodada de {{loja}} está em andamento (achadinhos.db.rodada-{{loja}}.lock); '
              'espere ela terminar.', file=sys.stderr)
    elif codigo:
        print(f'ERRO: falso {{codigo}}', file=sys.stderr)
elif script == 'ml_api.py':
    print('conferir ml falso', flush=True)
    if codigo:
        print(f'ERRO: falso {{codigo}}', file=sys.stderr)
elif script == 'coletar_shopee.py':
    print('conferir falso', flush=True)
    if codigo:
        print(f'ERRO: falso {{codigo}}', file=sys.stderr)
sys.exit(codigo)
'''.format(python=sys.executable, segredos=SEGREDOS)


def ler(nome):
    with open(os.path.join(OPERACAO, nome), encoding='utf-8') as f:
        return f.read()


def sem_comentarios(texto):
    """Linhas de código (sem as de comentário puro)."""
    return [l for l in texto.splitlines() if not l.lstrip().startswith('#')]


def ml(aba):
    return ['atualizar_precos.py', 'ml', '--cat', aba, '--vincular', '300', '--max-chamadas', '1500']


CONFERIR_ML = ['ml_api.py', 'conferir']
BACKUP_ML = ['backup_banco.py', '--motivo', 'ml']
PAROU_SEM_CHAVE = ('PAROU: o acesso ao Mercado Livre venceu (ou vence em menos de 5 min) e a rodada automática '
                   'não usa a Chave secreta. Rode no terminal: operacao/atualizar-ml.sh')


def shopee(aba, *extra):
    return ['atualizar_precos.py', 'shopee', '--cat', aba, *extra]


# ---------------------------------------------------------------- estáticos
class Estatico(unittest.TestCase):
    def test_existem_e_bash_n(self):
        for nome in TODOS:
            with self.subTest(nome=nome):
                p = subprocess.run(['bash', '-n', os.path.join(OPERACAO, nome)], capture_output=True, text=True)
                self.assertEqual(p.returncode, 0, p.stderr)

    def test_scripts_executaveis(self):
        for nome in SCRIPTS:
            with self.subTest(nome=nome):
                self.assertTrue(os.stat(os.path.join(OPERACAO, nome)).st_mode & stat.S_IXUSR)
                self.assertTrue(ler(nome).startswith('#!/usr/bin/env bash\n'))

    def test_nenhum_export(self):
        proibidos = re.compile(r'\bexport\b|\b(declare|typeset|local)\s+-[a-zA-Z]*x|\bset\s+-[a-zA-Z]*a|allexport')
        for nome in TODOS:
            for linha in sem_comentarios(ler(nome)):
                with self.subTest(nome=nome, linha=linha):
                    self.assertIsNone(proibidos.search(linha))

    def test_nenhum_xtrace_nem_tmp(self):
        # `set +x` (desliga) é permitido e exigido no comum.sh; ligar o rastreio, de qualquer jeito, não.
        proibidos = re.compile(r'\bset\s+-[a-zA-Z]*x|-o\s+xtrace|SHELLOPTS=|BASH_XTRACEFD|bash\s+-[a-zA-Z]*x|'
                               r'/tmp\b')
        for nome in TODOS:
            for linha in ler(nome).splitlines():   # inclusive o shebang e os comentários
                with self.subTest(nome=nome, linha=linha):
                    self.assertIsNone(proibidos.search(linha))

    def test_comum_desliga_o_rastreio_antes_de_tudo(self):
        """S1 (rodada 2): o primeiro comando do comum.sh é `set +x`, e cada script faz o `source` dele antes de
        qualquer outro comando (portanto antes de qualquer read). O automatico.sh e o instalador não carregam o
        comum.sh no começo (as guardas vêm antes): o primeiro comando deles é o próprio `set +x`."""
        codigo = [l for l in sem_comentarios(ler('comum.sh')) if l.strip()]
        self.assertEqual(codigo[0], 'set +x')
        for nome in AUTOMACAO:
            with self.subTest(nome=nome):
                codigo = [l for l in sem_comentarios(ler(nome)) if l.strip()]
                self.assertEqual(codigo[0], 'set +x')
        for nome in RODADAS:
            with self.subTest(nome=nome):
                codigo = [l for l in sem_comentarios(ler(nome)) if l.strip()]
                self.assertEqual(codigo[0], 'source "$(dirname -- "${BASH_SOURCE[0]}")/comum.sh" || exit 1')

    def test_read_de_segredo_com_rs(self):
        esperado = {'atualizar-ml.sh': 2, 'atualizar-shopee.sh': 2, 'atualizar-amazon.sh': 0, 'comum.sh': 0,
                    'automatico.sh': 0, 'instalar-timers.sh': 0}
        for nome in TODOS:
            linhas = [l for l in sem_comentarios(ler(nome)) if re.search(r'\bread\b', l)]
            # `read` como comando (fora de texto entre aspas, como o das instruções impressas)
            reads = [l for l in linhas if re.match(r'\s*(?:while IFS= )?read\s', l)]
            for linha in linhas:
                if linha not in reads:
                    self.assertRegex(linha.split('read', 1)[0], r'["\']', linha)
            segredo = [l for l in reads if re.search(r"\s(S|A)\s*;", l)]
            with self.subTest(nome=nome):
                self.assertEqual(len(segredo), esperado[nome], segredo)
                for linha in segredo:
                    self.assertRegex(linha, r"\bread -rsp '[^']*' [SA]; echo$")
                # o único outro read é o da saída do comando, em comum.sh (nunca de segredo)
                for linha in reads:
                    if linha not in segredo:
                        self.assertIn('read -r linha', linha)

    def test_segredo_so_no_ambiente_do_python3(self):
        # Cada uso de $S/$A (fora de texto escapado) é um teste de vazio dentro de [[ ]] ou uma atribuição só
        # para o ambiente do python3 (VAR="$S" ... python3 ...).
        uso = re.compile(r'(?<!\\)\$\{?[SA]\b')
        ambiente = re.compile(r'(?:ACHADINHOS_[A-Z_]+="\$[SA]" )+python3 ')
        vistos = 0
        for nome in TODOS:
            for linha in sem_comentarios(ler(nome)):
                for m in uso.finditer(linha):
                    vistos += 1
                    with self.subTest(nome=nome, linha=linha):
                        self.assertNotRegex(linha, r'\b(echo|printf)\b')
                        teste = '[[' in linha and linha[:m.start()].endswith(('-n ', '-z '))
                        env = any(a.start() < m.start() < a.end() for a in ambiente.finditer(linha))
                        self.assertTrue(teste or env, linha)
        self.assertGreaterEqual(vistos, 4)

    def test_trap_exit_apaga_os_segredos(self):
        comum = ler('comum.sh')
        self.assertIn('trap encerrar EXIT', comum)
        corpo = re.search(r'encerrar\(\) \{\n(.*?)\n\}', comum, re.S).group(1)
        self.assertIn('unset -v S A', corpo)
        for nome in ('atualizar-ml.sh', 'atualizar-shopee.sh'):
            texto = ler(nome)
            with self.subTest(nome=nome):
                # o trap (instalado por iniciar_log) vem antes do primeiro read de segredo
                self.assertLess(texto.index('\niniciar_log '), texto.index('read -rsp'))

    def test_log_em_logs_com_tee_so_no_comum(self):
        comum = ler('comum.sh')
        self.assertIn('base="logs/$1-$(date +%Y%m%d-%H%M%S)"', comum)
        self.assertIn('LOG="$base.log"', comum)
        self.assertIn('exec tee -i -a -- "$LOG"', comum)
        for nome in SCRIPTS:
            with self.subTest(nome=nome):
                self.assertNotIn('tee', ler(nome))
        # o backup da rodada automática usa o iniciar_log do comum.sh, com nome próprio
        self.assertIn('\n            iniciar_log automatico-backup\n', ler('automatico.sh'))
        for nome in RODADAS:
            texto = ler(nome)
            with self.subTest(nome=nome):
                nome_log = nome[:-3]
                self.assertIn(f'\niniciar_log {nome_log}\n', texto)
                self.assertLess(texto.index('\niniciar_log '), texto.index('\nfazer_backup '))

    def test_backup_pelo_backup_banco(self):
        self.assertIn('python3 backup_banco.py --motivo "$1"', ler('comum.sh'))
        for nome, loja in (('atualizar-ml.sh', 'ml'), ('atualizar-shopee.sh', 'shopee'),
                           ('atualizar-amazon.sh', 'amazon')):
            with self.subTest(nome=nome):
                self.assertIn(f'\nfazer_backup {loja}\n', ler(nome))

    # ---- rodada automática e instalador (endurecer-entrega2, etapa 4; CA11)
    def test_automatico_guardas_antes_de_qualquer_rodada(self):
        """Segredo no ambiente, depois código em edição, antes do comum.sh, do backup e dos scripts."""
        codigo = '\n'.join(sem_comentarios(ler('automatico.sh')))
        ordem = ['[[ -v $nome ]]', 'GIT_OPTIONAL_LOCKS=0 git --glob-pathspecs status --porcelain '
                 "--untracked-files=normal -- \\\n       '*.py' buscas.json operacao/) || [[ -n $sujos ]]; then",
                 'source "$RAIZ/operacao/comum.sh"', 'python3 backup_banco.py --motivo diario',
                 '"$RAIZ/operacao/atualizar-amazon.sh"', '"$RAIZ/operacao/atualizar-ml.sh" --sem-chave']
        posicoes = [codigo.index(t) for t in ordem]
        self.assertEqual(posicoes, sorted(posicoes))
        self.assertIn('if ! sujos=$(GIT_OPTIONAL_LOCKS=0 git ', codigo)   # saída vazia, ou para (R1 = S4 = Q2)
        self.assertEqual(codigo.count('source '), 1)

    def test_shopee_sem_caminho_na_automacao(self):
        """A Shopee só aparece na mensagem de recusa: nenhum comando, tarefa ou unidade a chama."""
        for nome in AUTOMACAO:
            for linha in sem_comentarios(ler(nome)):
                if 'shopee' in linha.lower() and 'ACHADINHOS_SHOPEE_' not in linha:
                    with self.subTest(nome=nome, linha=linha):
                        self.assertIn("echo 'ERRO: a Shopee não roda sozinha: precisa do Secret no terminal", linha)
            with self.subTest(nome=nome):
                self.assertNotIn('coletar_shopee', ler(nome))

    def test_automacao_nao_cria_variavel_de_segredo_nem_de_ambiente(self):
        self.assertNotRegex(ler('automatico.sh'), r'ACHADINHOS_\w+=')
        instalador = ler('instalar-timers.sh')
        self.assertNotIn('ACHADINHOS', instalador)
        for linha in sem_comentarios(instalador):
            with self.subTest(linha=linha):
                self.assertNotIn('nvironment', linha)   # Environment=, EnvironmentFile=, import-environment...


# ---------------------------------------------------------------- funcionais
class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='etiqueta-operacao-')
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.raiz = os.path.join(self.tmp, 'arvore')
        os.makedirs(os.path.join(self.raiz, 'operacao'))
        for nome in TODOS:
            shutil.copy2(os.path.join(OPERACAO, nome), os.path.join(self.raiz, 'operacao', nome))
        with open(os.path.join(self.raiz, 'buscas.json'), 'w', encoding='utf-8') as f:
            json.dump(BUSCAS_FALSO, f, ensure_ascii=False)
        self.bin = os.path.join(self.tmp, 'bin')
        self.falso = os.path.join(self.tmp, 'falso')
        os.makedirs(self.bin)
        os.makedirs(self.falso)
        for prog in ('python3', 'sleep'):
            caminho = os.path.join(self.bin, prog)
            with open(caminho, 'w', encoding='utf-8') as f:
                f.write(FALSO)
            os.chmod(caminho, 0o755)
        self.fora = os.path.join(self.tmp, 'outra-pasta')   # roda de fora da raiz: o script faz o cd
        os.makedirs(self.fora)

    def rodar(self, script, *args, entrada='', saidas=(), pausa='0', antes=(), env_extra=None):
        """`antes` vai antes do caminho do script (ex.: ('bash', '-x')); `env_extra` soma ao ambiente."""
        with open(os.path.join(self.falso, 'saidas'), 'w', encoding='utf-8') as f:
            f.write(''.join(f'{s}\n' for s in saidas))
        env = {'PATH': self.bin + os.pathsep + '/usr/bin:/bin', 'HOME': self.tmp, 'LANG': 'C.UTF-8',
               'FALSO_DIR': self.falso, **(env_extra or {})}
        if pausa is not None:
            env['PAUSA_SEG'] = pausa
        p = subprocess.run([*antes, os.path.join(self.raiz, 'operacao', script), *args], input=entrada,
                           capture_output=True, text=True, cwd=self.fora, env=env, timeout=60)
        self.saida = p.stdout + p.stderr
        return p

    def rodar_e_interromper(self, script, *args, entrada='', saidas=(), pausa='0', quando=None, env_extra=None):
        """Roda o script numa sessão própria e manda SIGINT ao grupo (como o Ctrl+C do terminal) quando
        `quando(chamadas)` ficar verdadeiro."""
        with open(os.path.join(self.falso, 'saidas'), 'w', encoding='utf-8') as f:
            f.write(''.join(f'{s}\n' for s in saidas))
        env = {'PATH': self.bin + os.pathsep + '/usr/bin:/bin', 'HOME': self.tmp, 'LANG': 'C.UTF-8',
               'FALSO_DIR': self.falso, 'PAUSA_SEG': pausa, **(env_extra or {})}
        p = subprocess.Popen([os.path.join(self.raiz, 'operacao', script), *args], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=self.fora, env=env,
                             start_new_session=True)
        try:
            p.stdin.write(entrada)
            p.stdin.close()
            limite = time.monotonic() + 20
            while not quando(self.chamadas()):
                self.assertLess(time.monotonic(), limite, 'o comando esperado não começou')
                time.sleep(0.05)
            time.sleep(0.5)   # o falso já está dentro do sleep
            os.killpg(p.pid, signal.SIGINT)
            out, err = p.communicate(timeout=30)
        finally:
            if p.poll() is None:
                os.killpg(p.pid, signal.SIGKILL)
                p.wait()
        self.saida = out + err
        return subprocess.CompletedProcess(p.args, p.returncode, out, err)

    def chamadas(self, reais=False):
        try:
            with open(os.path.join(self.falso, 'chamadas.jsonl'), encoding='utf-8') as f:
                todas = [json.loads(l) for l in f]
        except FileNotFoundError:
            return []
        return [c for c in todas if bool(c.get('real')) == reais]

    def argvs(self, prog='python3'):
        return [c['argv'] for c in self.chamadas() if c['prog'] == prog]

    def log(self):
        pasta = os.path.join(self.raiz, 'logs')
        nomes = os.listdir(pasta)
        self.assertEqual(len(nomes), 1, nomes)
        caminho = os.path.join(pasta, nomes[0])
        with open(caminho, encoding='utf-8') as f:
            return nomes[0], os.stat(caminho).st_mode & 0o777, f.read()

    def assert_segredos_fora(self, p, *segredos):
        """Nenhum segredo na tela, no log, no argv de nenhuma chamada nem nos arquivos da árvore."""
        _, _, log = self.log()
        textos = [p.stdout, p.stderr, log] + [json.dumps(c['argv']) for c in self.chamadas(True) + self.chamadas()]
        for raiz, _, nomes in os.walk(self.raiz):
            for nome in nomes:
                with open(os.path.join(raiz, nome), encoding='utf-8', errors='replace') as f:
                    textos.append(f.read())
        for s in segredos:
            for t in textos:
                self.assertNotIn(s, t)

    def assert_sem_segredo_no_ambiente(self, chamadas):
        for c in chamadas:
            self.assertEqual(c['env'], {}, c['argv'])


class RastreioLigado(Base):
    """S1 (rodada 2): chamado com `bash -x` ou com SHELLOPTS=xtrace no ambiente, o script não pode mandar o
    segredo (já expandido pelo rastreio) para a tela nem para o log. Os valores daqui são marcadores falsos."""

    MARCA_ML = 'marca-rastreio-ml-4d2e'
    MARCA_APP = 'marca-rastreio-app-91c0'
    MARCA_SHOPEE = 'marca-rastreio-shopee-a7f3'
    MODOS = (('bash -x', ('bash', '-x'), None), ('SHELLOPTS', (), {'SHELLOPTS': 'xtrace'}))

    def casos(self):
        return (
            ('atualizar-ml.sh', f'{self.MARCA_ML}\n', ['0', '0', '0', '0'],
             {'ACHADINHOS_ML_SECRET': self.MARCA_ML}, (self.MARCA_ML,)),
            ('atualizar-shopee.sh', f'{self.MARCA_APP}\n{self.MARCA_SHOPEE}\n', ['0', '0', '0', '0'],
             {'ACHADINHOS_SHOPEE_APP_ID': self.MARCA_APP, 'ACHADINHOS_SHOPEE_SECRET': self.MARCA_SHOPEE},
             (self.MARCA_APP, self.MARCA_SHOPEE)),
            ('atualizar-amazon.sh', f'{self.MARCA_ML}\n', ['0', '0'], None, (self.MARCA_ML,)),
        )

    def test_marcador_fora_da_tela_e_do_log(self):
        for modo, antes, env_extra in self.MODOS:
            for script, entrada, saidas, ambiente, marcas in self.casos():
                with self.subTest(modo=modo, script=script):
                    for nome in ('logs',):
                        shutil.rmtree(os.path.join(self.raiz, nome), ignore_errors=True)
                    with open(os.path.join(self.falso, 'chamadas.jsonl'), 'w'):
                        pass
                    p = self.rodar(script, entrada=entrada, saidas=saidas, antes=antes, env_extra=env_extra)
                    self.assertEqual(p.returncode, 0, self.saida)
                    # o rastreio estava mesmo ligado ao começar (a linha do `source` sai rastreada no stderr)
                    self.assertRegex(p.stderr, r'(?m)^\+ source .*/operacao/comum\.sh$')
                    # e o segredo chegou ao comando que o usa (o teste exercita o caminho com o valor)
                    if ambiente:
                        self.assertIn(ambiente, [c['env'] for c in self.chamadas()])
                    self.assert_segredos_fora(p, *marcas)


class ML(Base):
    def test_sem_argumento_roda_todas_as_abas_na_ordem_do_buscas(self):
        p = self.rodar('atualizar-ml.sh', entrada='\n', saidas=['0', '0', '0', '0'])
        self.assertEqual(p.returncode, 0, self.saida)
        self.assertEqual(self.argvs(), [['backup_banco.py', '--motivo', 'ml']] + [ml(a) for a in ABAS])
        self.assertEqual(self.argvs('sleep'), [])
        # Enter vazio: nenhuma variável de segredo, nem vazia, em nenhum comando
        self.assert_sem_segredo_no_ambiente(self.chamadas() + self.chamadas(True))
        # todas as chamadas rodaram na raiz da cópia, mesmo com o script chamado de outra pasta
        self.assertEqual({c['cwd'] for c in self.chamadas() + self.chamadas(True)}, {self.raiz})
        for a in ABAS:
            self.assertIn(f'  {a} | saída 0 | RESUMO ml: falso {a}', p.stdout)

    def test_log_datado_em_logs_0600_com_toda_a_saida(self):
        p = self.rodar('atualizar-ml.sh', entrada='\n', saidas=['0', '0', '0', '0'])
        nome, modo, log = self.log()
        self.assertRegex(nome, r'^atualizar-ml-\d{8}-\d{6}\.log$')
        self.assertEqual(modo, 0o600)
        self.assertEqual(p.stderr, '')
        self.assertEqual(log, p.stdout)
        self.assertIn('backup: backups/auto-falso.db ok 1 itens', log)
        self.assertIn('RESUMO DAS ABAS', log)

    def test_abas_pedidas_em_nfc_sem_repeticao(self):
        nfd = unicodedata.normalize('NFD', 'Saúde e Bem-estar')
        self.assertNotEqual(nfd, 'Saúde e Bem-estar')
        p = self.rodar('atualizar-ml.sh', 'Perfumes e Perfumaria', nfd, 'Perfumes e Perfumaria',
                       entrada='\n', saidas=['0', '0', '0'])
        self.assertEqual(p.returncode, 0, self.saida)
        self.assertEqual(self.argvs()[1:], [ml('Perfumes e Perfumaria'), ml('Saúde e Bem-estar')])

    def test_aba_desconhecida_para_antes_do_backup(self):
        p = self.rodar('atualizar-ml.sh', 'Games', 'Aba que não existe', entrada='\n')
        self.assertEqual(p.returncode, 2, self.saida)
        self.assertEqual(self.argvs(), [])
        self.assertIn('aba fora do buscas.json: Aba que não existe', p.stdout)

    def test_chave_vai_so_no_ambiente_do_atualizar(self):
        p = self.rodar('atualizar-ml.sh', entrada=CHAVE_ML + '\n', saidas=['0', '3', '0', '0'])
        self.assertEqual(p.returncode, 3, self.saida)
        chamadas = self.chamadas()
        self.assertEqual([c['argv'] for c in chamadas],
                         [['backup_banco.py', '--motivo', 'ml'], ml(ABAS[0]), ['0'], ml(ABAS[1]),
                          ml(ABAS[2])])
        for c in chamadas:
            if c['argv'][:1] == ['atualizar_precos.py']:
                self.assertEqual(c['env'], {'ACHADINHOS_ML_SECRET': CHAVE_ML})
            else:   # backup e sleep não herdam a chave (sem export)
                self.assertEqual(c['env'], {}, c['argv'])
        self.assert_sem_segredo_no_ambiente(self.chamadas(True))
        self.assert_segredos_fora(p, CHAVE_ML)

    def test_saida2_sem_chave_pede_a_chave_e_repete_a_aba(self):
        p = self.rodar('atualizar-ml.sh', entrada='\n' + CHAVE_ML + '\n', saidas=['0', '0', '2', '0', '0'])
        self.assertEqual(p.returncode, 0, self.saida)
        chamadas = self.chamadas()
        self.assertEqual([c['argv'] for c in chamadas],
                         [['backup_banco.py', '--motivo', 'ml'], ml(ABAS[0]), ml(ABAS[1]), ml(ABAS[1]),
                          ml(ABAS[2])])
        self.assertEqual([c['env'] for c in chamadas[1:]],
                         [{}, {}, {'ACHADINHOS_ML_SECRET': CHAVE_ML}, {'ACHADINHOS_ML_SECRET': CHAVE_ML}])
        self.assertIn(f'Repetindo a aba {ABAS[1]} com a chave', p.stdout)
        self.assertIn(f'  {ABAS[1]} | saída 0 | RESUMO ml: falso {ABAS[1]}', p.stdout)
        self.assert_segredos_fora(p, CHAVE_ML)

    def test_saida2_sem_chave_e_enter_vazio_para(self):
        p = self.rodar('atualizar-ml.sh', entrada='\n\n', saidas=['0', '2'])
        self.assertEqual(p.returncode, 2, self.saida)
        self.assertEqual(self.argvs(), [['backup_banco.py', '--motivo', 'ml'], ml(ABAS[0])])
        self.assertIn('nenhuma chave foi digitada', p.stdout)
        self.assertIn(f'  {ABAS[1]} | não rodou', p.stdout)
        self.assertIn('operacao/atualizar-ml.sh "Games" "Saúde e Bem-estar" "Perfumes e Perfumaria"', p.stdout)

    def test_saida2_com_chave_para_com_instrucao(self):
        p = self.rodar('atualizar-ml.sh', entrada=CHAVE_ML + '\n', saidas=['0', '0', '2'])
        self.assertEqual(p.returncode, 2, self.saida)
        self.assertEqual(self.argvs()[1:], [ml(ABAS[0]), ml(ABAS[1])])
        self.assertIn('recusou o acesso mesmo com a chave', p.stdout)
        self.assertIn('python3 ml_api.py conferir', p.stdout)
        self.assertIn('Mensagem do comando: ERRO: falso 2', p.stdout)
        self.assertIn(f'  {ABAS[2]} | não rodou', p.stdout)
        self.assertIn('operacao/atualizar-ml.sh "Saúde e Bem-estar" "Perfumes e Perfumaria"', p.stdout)
        self.assert_segredos_fora(p, CHAVE_ML)

    def test_saida3_espera_e_segue_sem_esperar_depois_da_ultima(self):
        p = self.rodar('atualizar-ml.sh', entrada='\n', saidas=['0', '3', '0', '3'])
        self.assertEqual(p.returncode, 3, self.saida)
        self.assertEqual(self.argvs()[1:], [ml(a) for a in ABAS])
        self.assertEqual(self.argvs('sleep'), [['0']])
        nomes = [c['argv'][3] if c['prog'] == 'python3' else 'sleep' for c in self.chamadas()[1:]]
        self.assertEqual(nomes, [ABAS[0], 'sleep', ABAS[1], ABAS[2]])
        self.assertIn(f'  {ABAS[2]} | saída 3 | RESUMO ml: falso {ABAS[2]}', p.stdout)

    def test_pausa_padrao_de_300_segundos(self):
        p = self.rodar('atualizar-ml.sh', entrada='\n', saidas=['0', '3', '0', '0'], pausa=None)
        self.assertEqual(p.returncode, 3, self.saida)
        self.assertEqual(self.argvs('sleep'), [['300']])

    def test_pausa_invalida_para_antes_de_tudo(self):
        p = self.rodar('atualizar-ml.sh', entrada='\n', pausa='5; rm -rf x')
        self.assertEqual(p.returncode, 2, self.saida)
        self.assertEqual(self.chamadas() + self.chamadas(True), [])

    def test_saida4_para_e_repassa_a_mensagem(self):
        p = self.rodar('atualizar-ml.sh', entrada='\n', saidas=['0', '0', '4'])
        self.assertEqual(p.returncode, 4, self.saida)
        self.assertEqual(self.argvs()[1:], [ml(ABAS[0]), ml(ABAS[1])])
        self.assertIn('PAROU: outra rodada de ml está em andamento (outro terminal ou um timer)', p.stdout)
        self.assertIn('Mensagem do comando: PAROU: outra rodada de ml está em andamento '
                      '(achadinhos.db.rodada-ml.lock)', p.stdout)
        self.assertIn(f'  {ABAS[1]} | saída 4 | sem linha RESUMO ml:', p.stdout)
        self.assertEqual(self.argvs('sleep'), [])

    def test_saida1_para(self):
        p = self.rodar('atualizar-ml.sh', entrada='\n', saidas=['0', '1'])
        self.assertEqual(p.returncode, 1, self.saida)
        self.assertEqual(self.argvs()[1:], [ml(ABAS[0])])
        self.assertIn(f'PAROU na aba {ABAS[0]} (saída 1)', p.stdout)

    def test_ctrl_c_durante_a_aba_para_com_resumo(self):
        p = self.rodar_e_interromper('atualizar-ml.sh', entrada=CHAVE_ML + '\n', saidas=['0', '0', '130 int'],
                                     quando=lambda cs: len(cs) >= 3)
        self.assertEqual(p.returncode, 130, self.saida)
        self.assertEqual(self.argvs()[1:], [ml(ABAS[0]), ml(ABAS[1])])
        _, _, log = self.log()
        # o tee ignora o Ctrl+C: a mensagem do comando e o resumo final chegam ao log e à tela
        for texto in ('Interrompido (falso).', f'PAROU na aba {ABAS[1]}: interrompido (Ctrl+C)',
                      f'  {ABAS[1]} | saída 130 |', f'  {ABAS[2]} | não rodou'):
            self.assertIn(texto, log)
            self.assertIn(texto, p.stdout)
        self.assert_segredos_fora(p, CHAVE_ML)

    def test_ctrl_c_durante_a_pausa_para_na_hora(self):
        p = self.rodar_e_interromper('atualizar-ml.sh', entrada='\n', saidas=['0', '3'], pausa='30',
                                     env_extra={'FALSO_SLEEP_REAL': '1'},
                                     quando=lambda cs: any(c['prog'] == 'sleep' for c in cs))
        self.assertEqual(p.returncode, 130, self.saida)
        self.assertEqual(self.argvs()[1:], [ml(ABAS[0])])
        self.assertEqual(self.argvs('sleep'), [['30']])
        _, _, log = self.log()
        self.assertIn('Interrompido (Ctrl+C).', log)

    def test_backup_falhou_para_sem_atualizar(self):
        p = self.rodar('atualizar-ml.sh', entrada=CHAVE_ML + '\n', saidas=['1'])
        self.assertEqual(p.returncode, 1, self.saida)
        self.assertEqual(self.argvs(), [['backup_banco.py', '--motivo', 'ml']])
        self.assertIn('PAROU: o backup do banco falhou', p.stdout)
        self.assert_segredos_fora(p, CHAVE_ML)

    # ---- --sem-chave (endurecer-entrega2, etapa 3; CA11): a rodada automática nunca lê nem usa a chave
    def rodar_sem_chave(self, *args, **kw):
        """Roda com --sem-chave e com uma chave na entrada: se algum `read` ou comando lesse a entrada, a chave
        apareceria no registro (`stdin`) do falso."""
        kw.setdefault('entrada', CHAVE_ML + '\n' + CHAVE_ML + '\n')
        kw['env_extra'] = {'FALSO_LER_STDIN': '1', **kw.get('env_extra', {})}
        return self.rodar('atualizar-ml.sh', '--sem-chave', *args, **kw)

    def assert_nada_leu_a_entrada(self):
        todas = self.chamadas() + self.chamadas(True)
        self.assertTrue(todas)
        for c in todas:
            self.assertEqual(c.get('stdin'), '', c['argv'])

    def test_sem_chave_nao_le_a_chave_da_entrada(self):
        p = self.rodar_sem_chave(saidas=['0', '0', '0', '0', '0'])
        self.assertEqual(p.returncode, 0, self.saida)
        self.assertEqual(self.argvs(), [CONFERIR_ML, BACKUP_ML] + [ml(a) for a in ABAS])
        self.assert_nada_leu_a_entrada()
        self.assert_sem_segredo_no_ambiente(self.chamadas() + self.chamadas(True))
        self.assert_segredos_fora(p, CHAVE_ML)
        self.assertEqual({c['cwd'] for c in self.chamadas() + self.chamadas(True)}, {self.raiz})

    def test_sem_chave_nunca_chama_o_read_da_chave(self):
        """Uma função `read` carregada pelo BASH_ENV (vale para o bash não interativo do script) registra cada
        `read -rsp`; o controle, sem a opção, prova que o registro funciona."""
        espiao = os.path.join(self.tmp, 'espiao.sh')
        with open(espiao, 'w', encoding='utf-8') as f:
            f.write('read() { [[ ${1-} == -rsp ]] && printf "%s\\n" "${2-}" >> "$FALSO_DIR/reads"; '
                    'builtin read "$@"; }\n')
        reads = os.path.join(self.falso, 'reads')
        for modo, args, saidas in (('manual', (), ['0', '0', '2', '0', '0']),
                                   ('sem-chave', ('--sem-chave',), ['0', '0', '0', '2', '0'])):
            with self.subTest(modo=modo):
                for caminho in (reads, os.path.join(self.falso, 'chamadas.jsonl')):
                    if os.path.exists(caminho):
                        os.remove(caminho)
                shutil.rmtree(os.path.join(self.raiz, 'logs'), ignore_errors=True)
                p = self.rodar('atualizar-ml.sh', *args, entrada='\n' + CHAVE_ML + '\n', saidas=saidas,
                               env_extra={'BASH_ENV': espiao})
                lidos = []
                if os.path.exists(reads):
                    with open(reads, encoding='utf-8') as f:
                        lidos = f.read().splitlines()
                if modo == 'manual':   # a chave do começo (Enter vazio) e a da saída 2 da 2ª aba
                    self.assertEqual(p.returncode, 0, self.saida)
                    self.assertEqual(len(lidos), 2, lidos)
                    self.assertTrue(all(l.startswith('Chave secreta do Mercado Livre') for l in lidos), lidos)
                else:
                    self.assertEqual(p.returncode, 2, self.saida)
                    self.assertEqual(lidos, [])
                    self.assert_sem_segredo_no_ambiente(self.chamadas() + self.chamadas(True))
                    self.assert_segredos_fora(p, CHAVE_ML)

    def test_sem_chave_apaga_a_chave_herdada_do_ambiente(self):
        p = self.rodar_sem_chave('Games', saidas=['0', '0', '0'], env_extra={'ACHADINHOS_ML_SECRET': CHAVE_ML})
        self.assertEqual(p.returncode, 0, self.saida)
        self.assertEqual(self.argvs(), [CONFERIR_ML, BACKUP_ML, ml('Games')])
        self.assert_sem_segredo_no_ambiente(self.chamadas() + self.chamadas(True))
        self.assert_segredos_fora(p, CHAVE_ML)

    def test_sem_chave_conferir_2_para_sem_backup(self):
        p = self.rodar_sem_chave(saidas=['2'])
        self.assertEqual(p.returncode, 2, self.saida)
        self.assertEqual(self.argvs(), [CONFERIR_ML])   # nem backup nem chamada da API
        self.assertIn(PAROU_SEM_CHAVE, p.stdout)
        self.assertIn('Mensagem do comando: ERRO: falso 2', p.stdout)
        self.assertNotIn('RESUMO DAS ABAS', p.stdout)
        self.assertNotIn('Repetindo', p.stdout)
        _, modo, log = self.log()
        self.assertEqual(modo, 0o600)
        self.assertIn(PAROU_SEM_CHAVE, log)
        self.assert_nada_leu_a_entrada()
        self.assert_segredos_fora(p, CHAVE_ML)

    def test_sem_chave_conferir_com_outro_erro_para_com_ele_sem_backup(self):
        for codigo in (1, 3, 130):
            with self.subTest(codigo=codigo):
                with open(os.path.join(self.falso, 'chamadas.jsonl'), 'w'):
                    pass
                shutil.rmtree(os.path.join(self.raiz, 'logs'), ignore_errors=True)
                p = self.rodar_sem_chave(saidas=[str(codigo)])
                self.assertEqual(p.returncode, codigo, self.saida)
                self.assertEqual(self.argvs(), [CONFERIR_ML])
                self.assertIn('PAROU na conferência do acesso', p.stdout)
                self.assertNotIn(PAROU_SEM_CHAVE, p.stdout)
                self.assert_segredos_fora(p, CHAVE_ML)

    def test_sem_chave_conferir_0_faz_backup_e_roda_as_abas_pedidas(self):
        p = self.rodar_sem_chave('Perfumes e Perfumaria', 'Games', saidas=['0', '0', '3', '0'])
        self.assertEqual(p.returncode, 3, self.saida)
        nomes = [c['argv'] if c['prog'] == 'python3' else 'sleep' for c in self.chamadas()]
        self.assertEqual(nomes, [CONFERIR_ML, BACKUP_ML, ml('Perfumes e Perfumaria'), 'sleep', ml('Games')])
        self.assertIn('  Games | saída 0 | RESUMO ml: falso Games', p.stdout)
        self.assert_nada_leu_a_entrada()

    def test_sem_chave_saida2_na_aba_para_sem_pedir_a_chave(self):
        p = self.rodar_sem_chave(saidas=['0', '0', '0', '2', '0'])
        self.assertEqual(p.returncode, 2, self.saida)
        # sem a opção, a mesma sequência pediria a chave e repetiria a aba (test_saida2_sem_chave_pede_...)
        self.assertEqual(self.argvs(), [CONFERIR_ML, BACKUP_ML, ml(ABAS[0]), ml(ABAS[1])])
        self.assertIn(PAROU_SEM_CHAVE, p.stdout)
        self.assertIn('Mensagem do comando: ERRO: falso 2', p.stdout)
        self.assertNotIn('Repetindo', p.stdout)
        self.assertNotIn('precisa da Chave secreta para ser renovado', p.stdout)
        self.assertIn(f'  {ABAS[1]} | saída 2 | sem linha RESUMO ml:', p.stdout)
        self.assertIn(f'  {ABAS[2]} | não rodou', p.stdout)
        self.assertIn('operacao/atualizar-ml.sh "Saúde e Bem-estar" "Perfumes e Perfumaria"', p.stdout)
        self.assert_nada_leu_a_entrada()
        self.assert_sem_segredo_no_ambiente(self.chamadas() + self.chamadas(True))
        self.assert_segredos_fora(p, CHAVE_ML)

    def test_sem_chave_fora_da_primeira_posicao_ou_repetida_sai_com_2(self):
        for args in (('Games', '--sem-chave'), ('--sem-chave', '--sem-chave'),
                     ('--sem-chave', 'Games', '--sem-chave'), ('--sem-chave',)):
            with self.subTest(args=args):
                with open(os.path.join(self.falso, 'chamadas.jsonl'), 'w'):
                    pass
                shutil.rmtree(os.path.join(self.raiz, 'logs'), ignore_errors=True)
                p = self.rodar('atualizar-ml.sh', *args, entrada=CHAVE_ML + '\n', saidas=['0', '0', '0', '0', '0'])
                if args == ('--sem-chave',):   # controle: a opção sozinha, em 1º lugar, vale
                    self.assertEqual(p.returncode, 0, self.saida)
                    self.assertEqual(self.argvs()[0], CONFERIR_ML)
                    continue
                self.assertEqual(p.returncode, 2, self.saida)
                self.assertEqual(self.chamadas() + self.chamadas(True), [])
                self.assertIn('a opção --sem-chave só vale como primeiro argumento', p.stderr)
                self.assertFalse(os.path.exists(os.path.join(self.raiz, 'logs')))


class Shopee(Base):
    ENTRADA = f'{APP_ID}\n{SECRET_SHOPEE}\n'
    AMBIENTE = {'ACHADINHOS_SHOPEE_APP_ID': APP_ID, 'ACHADINHOS_SHOPEE_SECRET': SECRET_SHOPEE}

    def test_ordem_e_credenciais_so_no_ambiente(self):
        p = self.rodar('atualizar-shopee.sh', entrada=self.ENTRADA, saidas=['0', '0', '3 teto', '0'])
        self.assertEqual(p.returncode, 0, self.saida)
        chamadas = self.chamadas()
        perf = 'Perfumes e Perfumaria'
        self.assertEqual([c['argv'] for c in chamadas],
                         [['backup_banco.py', '--motivo', 'shopee'], ['coletar_shopee.py', 'conferir', '--por-item'],
                          shopee(perf, '--max-chamadas', '10'), shopee(perf)])
        self.assertEqual(chamadas[0]['env'], {})
        for c in chamadas[1:]:
            self.assertEqual(c['env'], self.AMBIENTE)
        self.assert_sem_segredo_no_ambiente(self.chamadas(True))
        self.assertEqual(self.argvs('sleep'), [])   # 3 pelo teto de 10 chamadas: segue na hora
        self.assertIn(f'  aba {perf} | saída 0 | RESUMO shopee: falso {perf}', p.stdout)
        nome, modo, log = self.log()
        self.assertRegex(nome, r'^atualizar-shopee-\d{8}-\d{6}\.log$')
        self.assertEqual(modo, 0o600)
        self.assertEqual(log, p.stdout)
        self.assert_segredos_fora(p, APP_ID, SECRET_SHOPEE)

    def test_aba_pedida(self):
        p = self.rodar('atualizar-shopee.sh', 'Games', entrada=self.ENTRADA, saidas=['0', '0', '0', '0'])
        self.assertEqual(p.returncode, 0, self.saida)
        self.assertEqual(self.argvs()[2:], [shopee('Games', '--max-chamadas', '10'), shopee('Games')])

    def test_aba_desconhecida_ou_argumentos_demais(self):
        for args in (('Aba que não existe',), ('Games', 'Perfumes e Perfumaria')):
            with self.subTest(args=args):
                with open(os.path.join(self.falso, 'chamadas.jsonl'), 'w'):
                    pass
                p = self.rodar('atualizar-shopee.sh', *args, entrada=self.ENTRADA)
                self.assertEqual(p.returncode, 2, self.saida)
                self.assertEqual(self.argvs(), [])

    def test_limite_da_api_no_teste_pequeno_espera_e_segue(self):
        p = self.rodar('atualizar-shopee.sh', entrada=self.ENTRADA, saidas=['0', '0', '3', '0'])
        self.assertEqual(p.returncode, 0, self.saida)
        nomes = [c['argv'][-1] if c['prog'] == 'python3' else 'sleep' for c in self.chamadas()]
        self.assertEqual(nomes, ['shopee', '--por-item', '10', 'sleep', 'Perfumes e Perfumaria'])
        self.assertEqual(self.argvs('sleep'), [['0']])
        self.assertEqual([c['env'] for c in self.chamadas() if c['prog'] == 'sleep'], [{}])

    def test_conferir_falhou_para(self):
        for codigo in (1, 2, 3):
            with self.subTest(codigo=codigo):
                with open(os.path.join(self.falso, 'chamadas.jsonl'), 'w'):
                    pass
                p = self.rodar('atualizar-shopee.sh', entrada=self.ENTRADA, saidas=['0', str(codigo)])
                self.assertEqual(p.returncode, codigo, self.saida)
                self.assertEqual(self.argvs()[1:], [['coletar_shopee.py', 'conferir', '--por-item']])
                self.assertIn('PAROU no passo 1/3', p.stdout)
                shutil.rmtree(os.path.join(self.raiz, 'logs'))

    def test_saida2_ou_4_no_teste_pequeno_para(self):
        for codigo, texto in ((2, 'credencial recusada'), (4, 'outra rodada de shopee está em andamento')):
            with self.subTest(codigo=codigo):
                with open(os.path.join(self.falso, 'chamadas.jsonl'), 'w'):
                    pass
                p = self.rodar('atualizar-shopee.sh', entrada=self.ENTRADA, saidas=['0', '0', str(codigo)])
                self.assertEqual(p.returncode, codigo, self.saida)
                self.assertEqual(len(self.argvs()), 3)
                self.assertIn(texto, p.stdout)
                shutil.rmtree(os.path.join(self.raiz, 'logs'))

    def test_saida4_na_aba_para_e_repassa(self):
        p = self.rodar('atualizar-shopee.sh', entrada=self.ENTRADA, saidas=['0', '0', '0', '4'])
        self.assertEqual(p.returncode, 4, self.saida)
        self.assertIn('Mensagem do comando: PAROU: outra rodada de shopee está em andamento', p.stdout)
        self.assert_segredos_fora(p, APP_ID, SECRET_SHOPEE)

    def test_saida3_na_aba_pede_para_rodar_depois(self):
        p = self.rodar('atualizar-shopee.sh', entrada=self.ENTRADA, saidas=['0', '0', '0', '3'])
        self.assertEqual(p.returncode, 3, self.saida)
        self.assertIn('PAROU no passo 3/3', p.stdout)
        self.assertEqual(self.argvs('sleep'), [])

    def test_sem_appid_ou_secret_para_antes_do_backup(self):
        for entrada in (f'\n{SECRET_SHOPEE}\n', f'{APP_ID}\n\n', ''):
            with self.subTest(entrada=entrada):
                with open(os.path.join(self.falso, 'chamadas.jsonl'), 'w'):
                    pass
                p = self.rodar('atualizar-shopee.sh', entrada=entrada)
                self.assertEqual(p.returncode, 2, self.saida)
                self.assertEqual(self.argvs(), [])
                self.assertIn('o AppID e o Secret da Open API são obrigatórios', p.stdout)
                self.assert_segredos_fora(p, APP_ID, SECRET_SHOPEE)
                shutil.rmtree(os.path.join(self.raiz, 'logs'))

    def test_backup_falhou_para(self):
        p = self.rodar('atualizar-shopee.sh', entrada=self.ENTRADA, saidas=['1'])
        self.assertEqual(p.returncode, 1, self.saida)
        self.assertEqual(self.argvs(), [['backup_banco.py', '--motivo', 'shopee']])
        self.assert_segredos_fora(p, APP_ID, SECRET_SHOPEE)


class Amazon(Base):
    def test_sem_argumento(self):
        p = self.rodar('atualizar-amazon.sh', saidas=['0', '0'])
        self.assertEqual(p.returncode, 0, self.saida)
        self.assertEqual(self.argvs(), [['backup_banco.py', '--motivo', 'amazon'], ['atualizar_precos.py', 'amazon']])
        self.assert_sem_segredo_no_ambiente(self.chamadas())
        self.assertEqual({c['cwd'] for c in self.chamadas()}, {self.raiz})
        nome, modo, log = self.log()
        self.assertRegex(nome, r'^atualizar-amazon-\d{8}-\d{6}\.log$')
        self.assertEqual(modo, 0o600)
        self.assertEqual(log, p.stdout)
        self.assertIn('  amazon | saída 0 | RESUMO amazon: falso todas', p.stdout)

    def test_produtos(self):
        p = self.rodar('atualizar-amazon.sh', '--produtos', '20', saidas=['0', '0'])
        self.assertEqual(p.returncode, 0, self.saida)
        self.assertEqual(self.argvs()[1:], [['atualizar_precos.py', 'amazon', '--produtos', '20']])

    def test_argumento_invalido_nao_roda_nada(self):
        for args in (('--cat', 'Games'), ('--produtos',), ('--produtos', 'x'), ('--produtos', '1000'),
                     ('--produtos', '1', 'extra')):
            with self.subTest(args=args):
                p = self.rodar('atualizar-amazon.sh', *args)
                self.assertEqual(p.returncode, 2, self.saida)
                self.assertEqual(self.chamadas(), [])

    def test_saida3_captcha_espera_horas(self):
        p = self.rodar('atualizar-amazon.sh', saidas=['0', '3'])
        self.assertEqual(p.returncode, 3, self.saida)
        self.assertIn('Espere algumas horas', p.stdout)
        self.assertEqual(self.argvs('sleep'), [])

    def test_saida4_para(self):
        p = self.rodar('atualizar-amazon.sh', saidas=['0', '4'])
        self.assertEqual(p.returncode, 4, self.saida)
        self.assertIn('Mensagem do comando: PAROU: outra rodada de amazon está em andamento', p.stdout)

    def test_backup_falhou_para(self):
        p = self.rodar('atualizar-amazon.sh', saidas=['1'])
        self.assertEqual(p.returncode, 1, self.saida)
        self.assertEqual(self.argvs(), [['backup_banco.py', '--motivo', 'amazon']])


# ---------------------------------------------------------------- rodada automática (entrega2, etapa 4)
# Guarda larga (rodada 1, R1 = S4 = Q2): todo .py da raiz (inclusive não rastreado), o buscas.json e operacao/.
GIT_GUARDA = ['--glob-pathspecs', 'status', '--porcelain', '--untracked-files=normal', '--', '*.py', 'buscas.json',
              'operacao/']
BACKUP_DIARIO = ['backup_banco.py', '--motivo', 'diario']
MSG_SHOPEE = 'ERRO: a Shopee não roda sozinha: precisa do Secret no terminal'


def aviso(tarefa, codigo, texto):
    """argv esperado do notify-send."""
    return ['-a', 'Etiqueta', f'Etiqueta: {tarefa} parou (saída {codigo})', texto]


class BaseAutomacao(Base):
    def setUp(self):
        super().setUp()
        self.criar_falsos('git', 'notify-send', 'systemctl')

    def criar_falsos(self, *progs):
        for prog in progs:
            caminho = os.path.join(self.bin, prog)
            with open(caminho, 'w', encoding='utf-8') as f:
                f.write(FALSO)
            os.chmod(caminho, 0o755)

    def fila(self, prog, *codigos):
        with open(os.path.join(self.falso, 'saidas-' + prog), 'w', encoding='utf-8') as f:
            f.write(''.join(f'{c}\n' for c in codigos))

    def limpar(self):
        """Entre os subTests: zera o registro de chamadas, as filas dos outros falsos e os logs."""
        for nome in os.listdir(self.falso):
            os.remove(os.path.join(self.falso, nome))
        shutil.rmtree(os.path.join(self.raiz, 'logs'), ignore_errors=True)

    def bin_sem(self, *faltando):
        """Pasta para o PATH com todos os programas do sistema, menos `faltando` (o falso em self.bin some se for
        apagado à parte): prova o caminho de "programa ausente" numa máquina que o tem em /usr/bin."""
        pasta = os.path.join(self.tmp, 'bin-sistema')
        os.makedirs(pasta)
        for origem in ('/usr/bin', '/bin'):
            if not os.path.isdir(origem):
                continue
            for nome in os.listdir(origem):
                destino = os.path.join(pasta, nome)
                if nome in faltando or os.path.lexists(destino):
                    continue
                os.symlink(os.path.join(origem, nome), destino)
        return pasta

    def rodar_com_path(self, path, script, *args, saidas=(), env_extra=None):
        with open(os.path.join(self.falso, 'saidas'), 'w', encoding='utf-8') as f:
            f.write(''.join(f'{s}\n' for s in saidas))
        env = {'PATH': path, 'HOME': self.tmp, 'LANG': 'C.UTF-8', 'FALSO_DIR': self.falso, 'PAUSA_SEG': '0',
               **(env_extra or {})}
        p = subprocess.run([os.path.join(self.raiz, 'operacao', script), *args], input='', capture_output=True,
                           text=True, cwd=self.fora, env=env, timeout=60)
        self.saida = p.stdout + p.stderr
        return p


class Automatico(BaseAutomacao):
    def todas(self):
        return self.chamadas() + self.chamadas(True)

    def avisos(self):
        return self.argvs('notify-send')

    def assert_nada_leu_a_entrada(self):
        self.assertTrue(self.todas())
        for c in self.todas():
            self.assertEqual(c.get('stdin'), '', c['argv'])

    def test_backup_roda_o_backup_diario_com_log_e_sem_aviso(self):
        p = self.rodar('automatico.sh', 'backup', entrada=CHAVE_ML + '\n', saidas=['0'],
                       env_extra={'FALSO_LER_STDIN': '1'})
        self.assertEqual(p.returncode, 0, self.saida)
        self.assertEqual(self.argvs('git'), [GIT_GUARDA])
        self.assertEqual(self.argvs(), [BACKUP_DIARIO])
        self.assertEqual([c['prog'] for c in self.chamadas()], ['git', 'python3'])   # a guarda antes do backup
        self.assertEqual({c['cwd'] for c in self.chamadas()}, {self.raiz})
        self.assertEqual(self.avisos(), [])
        nome, modo, log = self.log()
        self.assertRegex(nome, r'^automatico-backup-\d{8}-\d{6}\.log$')
        self.assertEqual(modo, 0o600)
        self.assertIn('backup: backups/auto-falso.db ok 1 itens', log)
        self.assertIn(log, p.stdout)
        self.assert_sem_segredo_no_ambiente(self.chamadas())
        self.assert_nada_leu_a_entrada()   # exec < /dev/null antes de qualquer comando

    def test_amazon_chama_o_atualizar_amazon(self):
        p = self.rodar('automatico.sh', 'amazon', entrada=CHAVE_ML + '\n', saidas=['0', '0'],
                       env_extra={'FALSO_LER_STDIN': '1'})
        self.assertEqual(p.returncode, 0, self.saida)
        self.assertEqual(self.argvs('git'), [GIT_GUARDA])
        self.assertEqual(self.argvs(), [['backup_banco.py', '--motivo', 'amazon'], ['atualizar_precos.py', 'amazon']])
        self.assertEqual(self.avisos(), [])
        nome, _, _ = self.log()
        self.assertRegex(nome, r'^atualizar-amazon-\d{8}-\d{6}\.log$')
        self.assert_sem_segredo_no_ambiente(self.chamadas())
        self.assert_nada_leu_a_entrada()

    def test_ml_chama_o_atualizar_ml_sem_chave_e_nada_le_a_entrada(self):
        p = self.rodar('automatico.sh', 'ml', entrada=CHAVE_ML + '\n', saidas=['0', '0', '0', '0', '0'],
                       env_extra={'FALSO_LER_STDIN': '1'})
        self.assertEqual(p.returncode, 0, self.saida)
        self.assertEqual(self.argvs(), [CONFERIR_ML, BACKUP_ML] + [ml(a) for a in ABAS])
        self.assertEqual(self.avisos(), [])
        self.assert_nada_leu_a_entrada()
        self.assert_sem_segredo_no_ambiente(self.todas())
        self.assert_segredos_fora(p, CHAVE_ML)

    def test_shopee_ou_tarefa_invalida_sai_com_2_sem_rodar_nada(self):
        for args in (('shopee',), ('Shopee',), ('atualizar-shopee',), ('',), (), ('backup', 'amazon'),
                     ('outra',), ('--sem-chave',), ('ml', '--sem-chave')):
            with self.subTest(args=args):
                self.limpar()
                p = self.rodar('automatico.sh', *args, saidas=['0', '0', '0'])
                self.assertEqual(p.returncode, 2, self.saida)
                self.assertIn(MSG_SHOPEE, p.stderr)
                self.assertEqual(self.todas(), [])   # nem git, nem aviso, nem python3
                self.assertFalse(os.path.exists(os.path.join(self.raiz, 'logs')))

    def test_segredo_no_ambiente_sai_com_2_sem_o_valor(self):
        valores = {'ACHADINHOS_ML_SECRET': CHAVE_ML, 'ACHADINHOS_SHOPEE_APP_ID': APP_ID,
                   'ACHADINHOS_SHOPEE_SECRET': SECRET_SHOPEE}
        casos = [{k: v} for k, v in valores.items()] + [{'ACHADINHOS_ML_SECRET': ''}, dict(valores)]
        for tarefa in ('backup', 'amazon', 'ml'):
            for ambiente in casos:
                with self.subTest(tarefa=tarefa, ambiente=sorted(ambiente)):
                    self.limpar()
                    p = self.rodar('automatico.sh', tarefa, saidas=['0', '0', '0'], env_extra=ambiente)
                    self.assertEqual(p.returncode, 2, self.saida)
                    for nome in ambiente:
                        self.assertIn(nome, p.stdout)
                    self.assertIn('PAROU: variável de segredo no ambiente', p.stdout)
                    # só o aviso rodou: nem a guarda do git, nem backup, nem rodada
                    self.assertEqual([c['prog'] for c in self.todas()], ['notify-send'])
                    self.assertEqual(self.avisos(), [aviso(tarefa, 2, 'segredo no ambiente: nada rodou; detalhes '
                                                           f'em journalctl --user -u etiqueta-{tarefa}')])
                    self.assert_sem_segredo_no_ambiente(self.todas())   # nem o notify-send herda
                    self.assertFalse(os.path.exists(os.path.join(self.raiz, 'logs')))
                    for v in ambiente.values():
                        if v:
                            self.assertNotIn(v, self.saida)
                            self.assertNotIn(v, json.dumps(self.todas()))

    def test_codigo_em_edicao_ou_git_com_erro_sai_com_1(self):
        for codigo in (1, 128):
            for tarefa in ('backup', 'amazon', 'ml'):
                with self.subTest(codigo=codigo, tarefa=tarefa):
                    self.limpar()
                    self.fila('git', codigo)
                    p = self.rodar('automatico.sh', tarefa, saidas=['0', '0', '0'])
                    self.assertEqual(p.returncode, 1, self.saida)
                    self.assertIn('PAROU: código com mudança sem commit: a rodada automática não roda código em '
                                  'edição', p.stdout)
                    self.assertEqual(self.argvs(), [])
                    self.assertEqual([c['prog'] for c in self.todas()], ['git', 'notify-send'])
                    self.assertEqual(self.avisos(), [aviso(tarefa, 1, 'código com mudança sem commit: nada rodou; '
                                                           f'detalhes em journalctl --user -u etiqueta-{tarefa}')])

    def test_git_ausente_sai_com_1(self):
        os.remove(os.path.join(self.bin, 'git'))
        sistema = self.bin_sem('git')
        p = self.rodar_com_path(self.bin + os.pathsep + sistema, 'automatico.sh', 'backup', saidas=['0'])
        self.assertEqual(p.returncode, 1, self.saida)
        self.assertIn('PAROU: código com mudança sem commit', p.stdout)
        self.assertEqual(self.argvs(), [])
        self.assertEqual(len(self.avisos()), 1)

    def test_guarda_com_o_git_de_verdade(self):
        """O comando da guarda, rodado pelo git real num repositório temporário: mudança (até só no índice), arquivo
        apagado ou novo não rastreado num .py da raiz, no buscas.json ou em operacao/ para; testes/, index.html,
        .py fora da raiz e repositório limpo não."""
        if shutil.which('git') is None:
            self.skipTest('git não instalado')
        os.remove(os.path.join(self.bin, 'git'))
        git_env = {'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_CONFIG_NOSYSTEM': '1',
                   'GIT_CEILING_DIRECTORIES': self.tmp}
        os.makedirs(os.path.join(self.raiz, 'testes'))
        os.makedirs(os.path.join(self.raiz, 'tools', 'outro'))
        for nome in ('servidor.py', 'ml_api.py', 'coletar_amazon.py', 'index.html', 'buscas.json',
                     'testes/test_x.py', 'tools/outro/modulo.py'):
            with open(os.path.join(self.raiz, nome), 'w', encoding='utf-8') as f:
                f.write('# falso\n')

        def git(*args):
            subprocess.run(['git', '-c', 'user.name=Teste', '-c', 'user.email=teste@exemplo.invalid',
                            '-c', 'commit.gpgsign=false', *args], cwd=self.raiz, check=True, capture_output=True,
                           env={'PATH': '/usr/bin:/bin', 'HOME': self.tmp, **git_env})

        # fora de um repositório: o git falha (128) e a guarda para
        p = self.rodar('automatico.sh', 'backup', saidas=['0'], env_extra=git_env)
        self.assertEqual(p.returncode, 1, self.saida)
        self.assertEqual(self.argvs(), [])
        git('init', '-q')
        git('add', '-A')
        git('commit', '-q', '-m', 'base')
        casos = (('limpo', None, 0), ('index.html mudou', 'index.html', 0), ('servidor.py mudou', 'servidor.py', 1),
                 ('operacao/ mudou', 'operacao/comum.sh', 1), ('ml_api.py só no índice', 'ml_api.py+add', 1),
                 ('coletar_amazon.py mudou', 'coletar_amazon.py', 1), ('buscas.json mudou', 'buscas.json', 1),
                 ('.py novo não rastreado na raiz', 'novo_modulo.py', 1),
                 ('arquivo novo em operacao/', 'operacao/novo.sh', 1), ('servidor.py apagado', '-servidor.py', 1),
                 ('teste mudou', 'testes/test_x.py', 0), ('teste novo', 'testes/test_novo.py', 0),
                 ('.py fora da raiz', 'tools/outro/modulo.py', 0))
        for nome, arquivo, esperado in casos:
            with self.subTest(caso=nome):
                self.limpar()
                git('checkout', '-q', '--', '.')
                git('reset', '-q')
                git('checkout', '-q', '--', '.')
                git('clean', '-qfd')   # o arquivo novo do caso anterior
                if arquivo and arquivo.startswith('-'):
                    os.remove(os.path.join(self.raiz, arquivo[1:]))
                elif arquivo:
                    caminho = arquivo.removesuffix('+add')
                    with open(os.path.join(self.raiz, caminho), 'a', encoding='utf-8') as f:
                        f.write('# mudança\n')
                    if arquivo.endswith('+add'):
                        git('add', caminho)
                p = self.rodar('automatico.sh', 'backup', saidas=['0'], env_extra=git_env)
                self.assertEqual(p.returncode, esperado, self.saida)
                self.assertEqual(self.argvs(), [BACKUP_DIARIO] if esperado == 0 else [])
        # pathspec literal no ambiente: o "*.py" não acharia nada; com --glob-pathspecs o git recusa e a guarda para
        git('clean', '-qfd')
        git('checkout', '-q', '--', '.')
        for variavel in ('GIT_LITERAL_PATHSPECS', 'GIT_NOGLOB_PATHSPECS'):
            with self.subTest(variavel=variavel):
                self.limpar()
                p = self.rodar('automatico.sh', 'backup', saidas=['0'], env_extra={**git_env, variavel: '1'})
                self.assertEqual(p.returncode, 1, self.saida)
                self.assertEqual(self.argvs(), [])

    def test_aviso_so_com_saida_diferente_de_0_e_texto_fixo_por_codigo(self):
        casos = (
            ('backup', ['1'], 1, 'erro: veja o log'),
            ('backup', ['2'], 2, 'erro: veja o log'),
            ('amazon', ['0', '3'], 3, 'bloqueio ou limite da loja: a próxima rodada retoma'),
            ('amazon', ['0', '4'], 4, 'outra rodada da mesma loja estava no ar'),
            ('amazon', ['0', '2'], 2, 'erro: veja o log'),
            ('amazon', ['1'], 1, 'erro: veja o log'),
            ('ml', ['2'], 2, 'acesso vencido: rode operacao/atualizar-ml.sh no terminal'),
            ('ml', ['0', '0', '0', '2'], 2, 'acesso vencido: rode operacao/atualizar-ml.sh no terminal'),
            ('ml', ['0', '0', '0', '0', '3'], 3, 'bloqueio ou limite da loja: a próxima rodada retoma'),
            ('ml', ['0', '0', '4'], 4, 'outra rodada da mesma loja estava no ar'),
            ('ml', ['1'], 1, 'erro: veja o log'),
        )
        for tarefa, saidas, codigo, texto in casos:
            with self.subTest(tarefa=tarefa, saidas=saidas):
                self.limpar()
                p = self.rodar('automatico.sh', tarefa, saidas=saidas)
                self.assertEqual(p.returncode, codigo, self.saida)
                # o texto é fixo: nada da saída do comando (ERRO: falso N, RESUMO, PAROU...) vai para o aviso
                self.assertEqual(self.avisos(), [aviso(tarefa, codigo, f'{texto}; detalhes em logs/')])
                self.assertEqual(self.chamadas()[-1]['prog'], 'notify-send')   # o aviso é o último comando
                self.assert_sem_segredo_no_ambiente(self.todas())

    def test_notify_send_ausente_ou_com_erro_nao_muda_a_saida(self):
        self.fila('notify-send', 1)
        p = self.rodar('automatico.sh', 'amazon', saidas=['0', '3'])
        self.assertEqual(p.returncode, 3, self.saida)
        self.assertEqual(len(self.avisos()), 1)
        self.limpar()
        os.remove(os.path.join(self.bin, 'notify-send'))
        sistema = self.bin_sem('notify-send')
        for tarefa, saidas, codigo in (('amazon', ['0', '3'], 3), ('ml', ['2'], 2), ('backup', ['0'], 0)):
            with self.subTest(tarefa=tarefa):
                self.limpar()
                p = self.rodar_com_path(self.bin + os.pathsep + sistema, 'automatico.sh', tarefa, saidas=saidas)
                self.assertEqual(p.returncode, codigo, self.saida)
                self.assertEqual(self.avisos(), [])
                self.assertNotIn('notify-send', self.saida)


class Instalador(BaseAutomacao):
    CABECALHO = '# Gerado por operacao/instalar-timers.sh. Para mudar, rode o instalador de novo em vez de editar.'
    TAREFAS = ('backup', 'amazon', 'ml')
    HORARIO = {'backup': '*-*-* 03:30', 'amazon': '*-*-* 06:00', 'ml': '*-*-* 06:45'}
    LIMITE = {'backup': '15min', 'amazon': '2h', 'ml': '8h'}

    def setUp(self):
        super().setUp()
        self.config = os.path.join(self.tmp, 'config')
        self.destino = os.path.join(self.config, 'systemd', 'user')

    def instalar(self, *args, env_extra=None):
        env = {'XDG_CONFIG_HOME': self.config, 'FALSO_LISTAR': self.destino, **(env_extra or {})}
        return self.rodar('instalar-timers.sh', *args, env_extra=env)

    def unidades(self):
        return sorted(os.listdir(self.destino)) if os.path.isdir(self.destino) else []

    def ler_unidade(self, nome):
        with open(os.path.join(self.destino, nome), encoding='utf-8') as f:
            return f.read()

    def systemctl(self):
        return self.argvs('systemctl')

    def todos_os_nomes(self, tarefas):
        return sorted(f'etiqueta-{t}.{tipo}' for t in tarefas for tipo in ('service', 'timer'))

    def test_gera_as_seis_unidades_e_liga_na_ordem(self):
        p = self.instalar()
        self.assertEqual(p.returncode, 0, self.saida)
        self.assertEqual(self.unidades(), self.todos_os_nomes(self.TAREFAS))
        for t in self.TAREFAS:
            with self.subTest(tarefa=t):
                service = self.ler_unidade(f'etiqueta-{t}.service')
                timer = self.ler_unidade(f'etiqueta-{t}.timer')
                for texto in (service, timer):
                    self.assertEqual(texto.splitlines()[0], self.CABECALHO)
                    self.assertNotIn('ACHADINHOS', texto)
                    self.assertNotIn('nvironment', texto)   # Environment=, EnvironmentFile=, PassEnvironment=
                    self.assertNotIn('shopee', texto.lower())
                linhas = service.splitlines()
                for linha in ('[Service]', 'Type=oneshot', 'After=network-online.target',
                              f'WorkingDirectory={self.raiz}', f'ExecStart={self.raiz}/operacao/automatico.sh {t}',
                              'StandardInput=null', 'UMask=0077', 'Nice=10', 'IOSchedulingClass=idle',
                              'NoNewPrivileges=yes', f'TimeoutStartSec={self.LIMITE[t]}'):
                    self.assertIn(linha, linhas)
                self.assertEqual(len([l for l in linhas if l.startswith('ExecStart')]), 1)
                linhas = timer.splitlines()
                for linha in ('[Timer]', f'OnCalendar={self.HORARIO[t]}', 'RandomizedDelaySec=10min',
                              'Persistent=true', '[Install]', 'WantedBy=timers.target'):
                    self.assertIn(linha, linhas)
                self.assertFalse([l for l in linhas if l.startswith(('Unit=', 'OnActiveSec', 'OnBootSec'))])
        # daemon-reload com as 6 unidades já gravadas, depois um enable --now por timer
        self.assertEqual(self.systemctl(), [['--user', 'daemon-reload']] +
                         [['--user', 'enable', '--now', f'etiqueta-{t}.timer'] for t in self.TAREFAS])
        self.assertEqual(self.chamadas()[0]['dir'], self.todos_os_nomes(self.TAREFAS))
        self.assertEqual(self.argvs(), [])        # o instalador não roda nenhuma tarefa
        self.assertEqual(self.argvs('git'), [])
        self.assert_sem_segredo_no_ambiente(self.chamadas())

    def test_tarefas_pedidas_sem_repeticao(self):
        p = self.instalar('ml', 'backup', 'ml')
        self.assertEqual(p.returncode, 0, self.saida)
        self.assertEqual(self.unidades(), self.todos_os_nomes(('ml', 'backup')))
        self.assertEqual(self.systemctl(), [['--user', 'daemon-reload'], ['--user', 'enable', '--now', 'etiqueta-ml.timer'],
                                            ['--user', 'enable', '--now', 'etiqueta-backup.timer']])

    def test_sem_xdg_usa_home_config(self):
        p = self.rodar('instalar-timers.sh', 'backup')   # HOME = self.tmp, sem XDG_CONFIG_HOME
        self.assertEqual(p.returncode, 0, self.saida)
        self.assertEqual(sorted(os.listdir(os.path.join(self.tmp, '.config', 'systemd', 'user'))),
                         self.todos_os_nomes(('backup',)))

    def test_shopee_ou_tarefa_desconhecida_sai_com_2_sem_mexer_em_nada(self):
        for args in (('shopee',), ('backup', 'shopee'), ('Backup',), ('--remover', 'shopee'), ('backup', '--remover'),
                     ('--remover', '--remover'), ('',)):
            with self.subTest(args=args):
                self.limpar()
                p = self.instalar(*args)
                self.assertEqual(p.returncode, 2, self.saida)
                self.assertIn(MSG_SHOPEE, p.stderr)
                self.assertEqual(self.chamadas(), [])
                self.assertFalse(os.path.exists(self.config))

    def test_xdg_relativo_sai_com_2(self):
        p = self.instalar(env_extra={'XDG_CONFIG_HOME': 'config-relativo'})
        self.assertEqual(p.returncode, 2, self.saida)
        self.assertEqual(self.chamadas(), [])
        self.assertFalse(os.path.exists(os.path.join(self.fora, 'config-relativo')))

    def test_recusa_sobrescrever_arquivo_sem_cabecalho_e_nao_grava_nada(self):
        os.makedirs(self.destino)
        alheio = os.path.join(self.destino, 'etiqueta-ml.timer')
        with open(alheio, 'w', encoding='utf-8') as f:
            f.write('# feito à mão\n[Timer]\nOnCalendar=daily\n')
        p = self.instalar()
        self.assertEqual(p.returncode, 1, self.saida)
        self.assertIn('não foi gerado por este instalador', p.stderr)
        self.assertEqual(self.unidades(), ['etiqueta-ml.timer'])   # nem as unidades de backup e amazon
        with open(alheio, encoding='utf-8') as f:
            self.assertEqual(f.read(), '# feito à mão\n[Timer]\nOnCalendar=daily\n')
        self.assertEqual(self.chamadas(), [])

    def test_recusa_link_simbolico_mesmo_com_cabecalho(self):
        os.makedirs(self.destino)
        alvo = os.path.join(self.tmp, 'alvo.service')
        with open(alvo, 'w', encoding='utf-8') as f:
            f.write(self.CABECALHO + '\nconteúdo do alvo\n')
        os.symlink(alvo, os.path.join(self.destino, 'etiqueta-backup.service'))
        for args in ((), ('--remover',)):
            with self.subTest(args=args):
                self.limpar()
                p = self.instalar(*args)
                self.assertEqual(p.returncode, 1, self.saida)
                self.assertTrue(os.path.islink(os.path.join(self.destino, 'etiqueta-backup.service')))
                with open(alvo, encoding='utf-8') as f:
                    self.assertEqual(f.read(), self.CABECALHO + '\nconteúdo do alvo\n')

    def test_reinstalar_regrava_os_seus(self):
        p = self.instalar('amazon')
        self.assertEqual(p.returncode, 0, self.saida)
        original = self.ler_unidade('etiqueta-amazon.timer')
        with open(os.path.join(self.destino, 'etiqueta-amazon.timer'), 'w', encoding='utf-8') as f:
            f.write(self.CABECALHO + '\n[Timer]\nOnCalendar=velho\n')
        self.limpar()
        p = self.instalar('amazon')
        self.assertEqual(p.returncode, 0, self.saida)
        self.assertEqual(self.ler_unidade('etiqueta-amazon.timer'), original)
        self.assertEqual(self.unidades(), self.todos_os_nomes(('amazon',)))   # sem temporário sobrando
        for nome in self.unidades():
            self.assertEqual(os.stat(os.path.join(self.destino, nome)).st_mode & 0o777, 0o644)

    def test_remover_desliga_e_apaga_so_os_seus(self):
        self.assertEqual(self.instalar().returncode, 0, self.saida)
        alheios = {'outra.timer': '[Timer]\n', 'etiqueta-amazon.service': '# feito à mão\n'}
        for nome, texto in alheios.items():
            with open(os.path.join(self.destino, nome), 'w', encoding='utf-8') as f:
                f.write(texto)
        self.limpar()
        p = self.instalar('--remover')
        self.assertEqual(p.returncode, 1, self.saida)   # avisa do arquivo que ficou
        self.assertIn('etiqueta-amazon.service não foi gerado por este instalador', p.stderr)
        self.assertEqual(self.unidades(), sorted(alheios))
        for nome, texto in alheios.items():
            self.assertEqual(self.ler_unidade(nome), texto)
        self.assertEqual(self.systemctl(), [['--user', 'disable', '--now', f'etiqueta-{t}.timer'] for t in self.TAREFAS]
                         + [['--user', 'daemon-reload']])
        # o disable de cada timer vem antes de apagar os arquivos dele; o daemon-reload, depois de tudo apagado
        dirs = [c['dir'] for c in self.chamadas()]
        self.assertIn('etiqueta-backup.timer', dirs[0])
        self.assertIn('etiqueta-ml.timer', dirs[2])
        self.assertNotIn('etiqueta-backup.timer', dirs[1])
        self.assertEqual(dirs[3], sorted(alheios))
        self.assertEqual(self.argvs(), [])

    def test_remover_tarefa_pedida_e_sem_nada_instalado(self):
        self.assertEqual(self.instalar().returncode, 0, self.saida)
        self.limpar()
        p = self.instalar('--remover', 'ml')
        self.assertEqual(p.returncode, 0, self.saida)
        self.assertEqual(self.unidades(), self.todos_os_nomes(('backup', 'amazon')))
        self.assertEqual(self.systemctl(), [['--user', 'disable', '--now', 'etiqueta-ml.timer'],
                                            ['--user', 'daemon-reload']])
        self.limpar()
        p = self.instalar('--remover', 'ml')   # já removido: não chama disable, só o daemon-reload
        self.assertEqual(p.returncode, 0, self.saida)
        self.assertEqual(self.systemctl(), [['--user', 'daemon-reload']])

    def test_remover_com_disable_falhando_mantem_os_arquivos(self):
        self.assertEqual(self.instalar('backup', 'ml').returncode, 0, self.saida)
        self.limpar()
        self.fila('systemctl', 1, 0, 0)
        p = self.instalar('--remover', 'backup', 'ml')
        self.assertEqual(p.returncode, 1, self.saida)
        self.assertEqual(self.unidades(), self.todos_os_nomes(('backup',)))
        self.assertIn('o systemctl não desligou etiqueta-backup.timer', p.stderr)

    def test_falha_do_systemctl_para_com_1(self):
        for fila, chamadas in (((1,), [['--user', 'daemon-reload']]),
                               ((0, 0, 1), [['--user', 'daemon-reload'],
                                            ['--user', 'enable', '--now', 'etiqueta-backup.timer'],
                                            ['--user', 'enable', '--now', 'etiqueta-amazon.timer']])):
            with self.subTest(fila=fila):
                self.limpar()
                self.fila('systemctl', *fila)
                p = self.instalar()
                self.assertEqual(p.returncode, 1, self.saida)
                self.assertEqual(self.systemctl(), chamadas)
                self.assertIn('operacao/instalar-timers.sh --remover', p.stderr)

    def test_pasta_do_projeto_com_caractere_proibido_sai_com_2(self):
        for pasta in ('arvore com espaço', 'árvore', 'arvore%h', "arvore'x"):
            with self.subTest(pasta=pasta):
                self.limpar()
                outra = os.path.join(self.tmp, pasta)
                shutil.copytree(self.raiz, outra, symlinks=True)
                self.addCleanup(shutil.rmtree, outra, ignore_errors=True)
                env = {'PATH': self.bin + os.pathsep + '/usr/bin:/bin', 'HOME': self.tmp, 'LANG': 'C.UTF-8',
                       'FALSO_DIR': self.falso, 'XDG_CONFIG_HOME': self.config}
                p = subprocess.run([os.path.join(outra, 'operacao', 'instalar-timers.sh')], capture_output=True,
                                   text=True, cwd=self.fora, env=env, timeout=60)
                self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
                self.assertIn('caractere fora de A-Z', p.stderr)
                self.assertEqual(self.chamadas(), [])
                self.assertFalse(os.path.exists(self.config))

    @unittest.skipUnless(shutil.which('systemd-analyze'), 'systemd-analyze não instalado')
    def test_unidades_geradas_passam_no_systemd_analyze_verify(self):
        """Só lê as unidades da pasta temporária (XDG_CONFIG_HOME e XDG_RUNTIME_DIR temporários); não fala com o
        systemd do usuário. As outras unidades do sistema podem gerar avisos; os nossos não."""
        self.assertEqual(self.instalar().returncode, 0, self.saida)
        runtime = os.path.join(self.tmp, 'run')
        os.makedirs(runtime, mode=0o700)
        caminhos = [os.path.join(self.destino, n) for n in self.unidades()]
        p = subprocess.run(['systemd-analyze', '--user', 'verify', *caminhos], capture_output=True, text=True,
                           cwd=self.tmp, timeout=120,
                           env={'PATH': '/usr/bin:/bin', 'HOME': self.tmp, 'LANG': 'C.UTF-8',
                                'XDG_CONFIG_HOME': self.config, 'XDG_RUNTIME_DIR': runtime})
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual([l for l in (p.stdout + p.stderr).splitlines() if 'etiqueta-' in l], [])


if __name__ == '__main__':
    unittest.main()
