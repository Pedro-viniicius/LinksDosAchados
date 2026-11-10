#!/usr/bin/env python3
"""Testes dos scripts de operação em operacao/ (docs/produto/planos/endurecer-engenharia-e-operacao.md,
etapa 7: CA5 e CA6).

Uso:  python3 testes/test_operacao.py -v

- Estáticos: `bash -n`, nenhum export, todo `read` de segredo com -rs, nenhum /tmp nem rastreio ligado (o
  comum.sh o desliga com `set +x` antes de qualquer read), log em logs/, segredo só no ambiente do python3.
- Funcionais: cada teste monta numa pasta temporária uma cópia mínima da árvore (operacao/ e um buscas.json
  falso) e roda o script de verdade, com um `python3` e um `sleep` falsos no PATH. O falso registra argv, pasta
  e quais variáveis de segredo recebeu, e devolve os códigos programados no arquivo `saidas` (um por chamada).
  As chamadas `python3 -I -c` (leitura do buscas.json) vão para o Python real.
  Nada roda sobre a raiz real: nem backup_banco.py, nem atualizar_precos.py, nem coletar_shopee.py.
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
SCRIPTS = ('atualizar-ml.sh', 'atualizar-shopee.sh', 'atualizar-amazon.sh')
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
fila = os.path.join(pasta, 'saidas')
with open(fila, encoding='utf-8') as f:
    linhas = f.read().splitlines()
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
        qualquer outro comando (portanto antes de qualquer read)."""
        codigo = [l for l in sem_comentarios(ler('comum.sh')) if l.strip()]
        self.assertEqual(codigo[0], 'set +x')
        for nome in SCRIPTS:
            with self.subTest(nome=nome):
                codigo = [l for l in sem_comentarios(ler(nome)) if l.strip()]
                self.assertEqual(codigo[0], 'source "$(dirname -- "${BASH_SOURCE[0]}")/comum.sh" || exit 1')

    def test_read_de_segredo_com_rs(self):
        esperado = {'atualizar-ml.sh': 2, 'atualizar-shopee.sh': 2, 'atualizar-amazon.sh': 0, 'comum.sh': 0}
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
            texto = ler(nome)
            with self.subTest(nome=nome):
                self.assertNotIn('tee', texto)
                nome_log = nome[:-3]
                self.assertIn(f'\niniciar_log {nome_log}\n', texto)
                self.assertLess(texto.index('\niniciar_log '), texto.index('\nfazer_backup '))

    def test_backup_pelo_backup_banco(self):
        self.assertIn('python3 backup_banco.py --motivo "$1"', ler('comum.sh'))
        for nome, loja in (('atualizar-ml.sh', 'ml'), ('atualizar-shopee.sh', 'shopee'),
                           ('atualizar-amazon.sh', 'amazon')):
            with self.subTest(nome=nome):
                self.assertIn(f'\nfazer_backup {loja}\n', ler(nome))


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


if __name__ == '__main__':
    unittest.main()
