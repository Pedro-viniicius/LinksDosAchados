#!/usr/bin/env python3
"""Verificação única do projeto: o que este comando disser é a definição de "verde".

Plano: docs/produto/planos/endurecer-engenharia-e-operacao.md (etapa 5: CA1, CA2, CA3 e CA8; etapa 6: CA12;
etapa 8: CA7).

Uso:
  python3 verificar.py                  py_compile + todos os testes Python e Node
  python3 verificar.py --rapido         com --dados-reais, pula os lentos (LENTOS); sem ele, roda tudo (os
                                        LENTOS só são lentos sobre a cópia do banco real)
  python3 verificar.py --dados-reais    liga os testes sobre a cópia do banco real (ACHADINHOS_TESTE_DADOS_REAIS=1)
  python3 verificar.py --hora 3         roda com o relógio local às 03h (TZ calculado a partir do UTC)
  python3 verificar.py --front          também roda as páginas do front num servidor próprio na 8766,
                                        sobre uma cópia do banco (precisa de internet para 2 fotos reais)
  python3 verificar.py --servidor [P]   só confere se o servidor no ar (padrão 8765) roda o código em disco:
                                        um GET em /api/versao, nada mais (não roda testes)
  python3 verificar.py --segredos [--staged|--tudo]
                                        só procura segredo: nomes proibidos (NOMES_PROIBIDOS, PASTAS_PROIBIDAS)
                                        e padrões (PADROES_SEGREDO) nas linhas adicionadas do que está staged
                                        (padrão) ou em todo arquivo do repositório (--tudo, no disco); mostra
                                        arquivo, linha e tipo, nunca o trecho achado
  python3 verificar.py --pre-commit     portão do commit (.githooks/pre-commit, ligado por
                                        `git config core.hooksPath .githooks`): --segredos --staged e, se houver
                                        .py/.mjs/.html/.json/.sh staged, a suíte --rapido sem os testes fora do
                                        índice (não rastreados). `git commit --no-verify` passa por cima: o portão
                                        protege contra acidente, não contra má-fé

Escape: a linha com "# verificar: permitir" não bloqueia e aparece no resumo como "liberado pelo marcador",
para revisão. Fora do --servidor, avisa quando o core.hooksPath não aponta para .githooks.

Cada arquivo roda em subprocesso, num ambiente isolado (sem Secret, proxies mortos, banco, progresso e
tokens numa pasta temporária), com timeout de 900 s. A saída inteira de cada um fica em
logs/verificar-<data>/<nome>.txt; na tela sai uma linha por arquivo e os motivos de skip.

Saídas: 0 tudo verde; 1 algo falhou (inclusive a porta do --front ocupada durante a suíte: linha "front"
vermelha); 2 uso errado (opção inválida, porta 8765 ou porta do --front já ocupada na largada); 130 interrompido. Com --segredos e --pre-commit: 0 limpo, 1 achado de segredo, teste vermelho ou git
indisponível. Com --servidor: 0 em dia; 1 precisa reiniciar, está fora do ar ou respondeu algo inesperado;
2 uso errado.

A 8765 (servidor do dono) nunca é usada, com uma exceção: o --servidor, que só lê (um GET em /api/versao, sem
corpo e sem gravar nada).

Só biblioteca padrão. Não importa o servidor.py nem nenhum módulo do projeto: nada aqui abre o achadinhos.db,
exceto a cópia do --front, feita em `mode=ro`.
"""
import argparse
import datetime
import fnmatch
import glob
import http.client
import importlib.metadata
import json
import os
import pathlib
import py_compile
import re
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import zoneinfo
from collections import Counter

RAIZ = os.path.dirname(os.path.abspath(__file__))
PASTA_LOGS = os.path.join(RAIZ, 'logs')
BANCO_REAL = os.path.join(RAIZ, 'achadinhos.db')

# (pasta relativa à raiz, prefixo do nome no resumo e no log)
PASTAS_PY = (('testes', ''), (os.path.join('tools', 'garimpo_feminino', 'testes'), 'garimpo/'))
PASTA_NODE = 'testes'
# Arquivos de código conferidos pelo py_compile (relativos à raiz; os testes são conferidos ao rodar).
COMPILAR = ('*.py', os.path.join('tools', 'garimpo_feminino', '*.py'))
# Lentos só com os dados reais ligados (cópias do banco real): em 09/11/2026, ~190 s e ~110 s. Sem o --dados-reais,
# os testes deles que leem o banco real pulam e os dois levam ~4 s e ~2 s: aí o --rapido não pula nada.
LENTOS = ('test_api_ofertas_qa', 'test_genero_qa')
TIMEOUT_SEG = 900

PROXY_MORTO = 'http://127.0.0.1:9'
VARS_PROXY = ('http_proxy', 'https_proxy', 'ftp_proxy', 'all_proxy',
              'HTTP_PROXY', 'HTTPS_PROXY', 'FTP_PROXY', 'ALL_PROXY')
# Padrão da suíte: no_proxy vazio (até o localhost passa pelo proxy morto; os testes que falam com
# servidor local usam opener sem proxy ou http.client).
VARS_SEM_PROXY = ('no_proxy', 'NO_PROXY')
VAR_DADOS_REAIS = 'ACHADINHOS_TESTE_DADOS_REAIS'
# Variáveis apontadas para a pasta temporária de cada arquivo (rede de segurança: teste que quebrar por
# causa disso estava tocando dado real, e isso é achado, não motivo para afrouxar o isolamento).
ARQUIVOS_TEMPORARIOS = {
    'ACHADINHOS_DB': 'achadinhos.db',
    'ACHADINHOS_FEITOS': 'coleta_amazon_feitos.txt',
    'ACHADINHOS_FEITOS_SHOPEE': 'coleta_shopee_feitos.txt',
    'ACHADINHOS_FEITOS_ATUALIZAR': 'atualizar_precos_feitos.txt',
    'ACHADINHOS_ML_TOKENS': 'ml_tokens.json',
    'ACHADINHOS_ML_CATALOGO': 'ml_catalogo.json',
    'ACHADINHOS_GARIMPO_DIR': 'garimpo',
}

PORTA_REAL = 8765    # servidor do dono: o --front nunca usa (o --servidor só lê, e é o padrão dele)
PORTA_FRONT = 8766
SEGUNDOS_PAGINA = 300   # espera máxima do testes/rodar.mjs por página
# Páginas do front que rodam sobre a cópia do banco real (já migrada às 17 abas e na v3; o servidor da
# cópia migra de novo se precisar, só na cópia). Todas só fazem GET na API real; escrita é interceptada.
FRONT = (
    'copiar-imagem',        # 2 fotos reais dos CDNs: sem internet, essas falham
    'abrir-e-adicionar',
    'mensagens',
    'abas',                 # pede banco já migrado às 17 abas (o real está)
    'abas-qa',              # idem
    'desmarcar-aba',        # idem
    'precos',
    'precos-qa',
    'genero',
    'genero-qa',
    'disparo',              # servidor com ACHADINHOS_DISPARO=0; rotas do disparo atendidas por servidor falso
    'disparo-qa',
)
FORA_DO_FRONT = {
    'disparo-integracao': 'grava no banco de verdade; só roda num banco temporário novo, sem número nem regra',
    'genero-integracao': 'grava no banco de verdade (público, número e regra); só roda numa cópia descartável',
}


class ErroUso(Exception):
    """Uso errado: sai com 2 e só a mensagem."""


class Resultado:
    """Uma linha do resumo."""

    def __init__(self, nome, ok, saida=None, tempo=0.0, resumo='', skips=None, log=None):
        self.nome, self.ok, self.saida, self.tempo = nome, ok, saida, tempo
        self.resumo, self.skips, self.log = resumo, skips or Counter(), log

    def linha(self):
        saida = 'TIMEOUT' if self.saida is None else str(self.saida)
        return f'{self.nome:<36} saida={saida:<3} {self.tempo:6.1f}s  {self.resumo}'


# ---------------------------------------------------------------- ambiente

def ambiente_isolado(pasta, base=None, dados_reais=False, tz=None):
    """Ambiente do filho: cópia de `base` (padrão os.environ) sem nenhuma ACHADINHOS_* herdada, variável
    com SECRET no nome ou GIT_* (dentro do hook, GIT_DIR e GIT_INDEX_FILE apontam para o repositório real: um
    teste que cria repositório temporário mexeria no índice do commit), proxies mortos, API v1 e agendador
    desligados, e banco, progresso, tokens e catálogo dentro de `pasta`. O próprio verificar.py nunca imprime
    nada disto."""
    base = os.environ if base is None else base
    env = {k: v for k, v in base.items()
           if not k.startswith(('ACHADINHOS_', 'GIT_')) and 'SECRET' not in k.upper()}
    for k in VARS_PROXY:
        env[k] = PROXY_MORTO
    for k in VARS_SEM_PROXY:
        env[k] = ''
    env['ACHADINHOS_API_TOKEN_ARQUIVO'] = '/nao/existe'
    env['ACHADINHOS_DISPARO'] = '0'
    for var, nome in ARQUIVOS_TEMPORARIOS.items():
        env[var] = os.path.join(pasta, nome)
    if dados_reais:
        env[VAR_DADOS_REAIS] = '1'
    if tz is not None:
        env['TZ'] = tz
    return env


def tz_para_hora(hora, agora=None):
    """TZ que põe o relógio local na hora `hora` agora (os minutos seguem os do relógio).

    Deslocamento em horas cheias calculado do UTC atual, no fuso `Etc/GMT±N`, que tem o sinal do POSIX
    (`Etc/GMT+3` = UTC − 3). Não serve o TZ POSIX puro (`XXX+09:35`): o Python (glibc) entende, mas o Node e
    o Chrome (ICU) o ignoram e caem no fuso do sistema. O deslocamento fica entre −12 e +11.
    """
    agora = agora or datetime.datetime.now(datetime.timezone.utc)
    n = (agora.hour - hora + 12) % 24 - 12    # local = UTC − n
    return 'Etc/GMT' if n == 0 else f'Etc/GMT{n:+d}'


def conferir_requirements(caminho=None):
    """Avisos (texto) das diferenças entre o ambiente e o requirements.txt. Nunca falha a verificação."""
    caminho = caminho or os.path.join(RAIZ, 'requirements.txt')
    if not os.path.exists(caminho):
        return ['sem requirements.txt: as versões das dependências não foram conferidas']
    avisos = []
    with open(caminho, encoding='utf-8') as f:
        for n, linha in enumerate(f, 1):
            linha = linha.split('#', 1)[0].strip()
            if not linha:
                continue
            m = re.fullmatch(r'([A-Za-z0-9][A-Za-z0-9._-]*)\s*==\s*([A-Za-z0-9._+!-]+)', linha)
            if not m:
                avisos.append(f'requirements.txt:{n}: linha sem versão fixa (pacote==versão), não conferida')
                continue
            nome, pedida = m.groups()
            try:
                instalada = importlib.metadata.version(nome)
            except importlib.metadata.PackageNotFoundError:
                avisos.append(f'requirements.txt: {nome} {pedida} pedido, mas não está instalado')
                continue
            if instalada != pedida:
                avisos.append(f'requirements.txt: {nome} {pedida} pedido, {instalada} instalado')
    return avisos


def versao_node():
    """(maior, texto) da versão do node no PATH, ou (None, motivo)."""
    if not shutil.which('node'):
        return None, 'node não encontrado no PATH'
    try:
        texto = subprocess.run(['node', '--version'], capture_output=True, text=True, timeout=30).stdout.strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, f'node --version falhou ({type(e).__name__})'
    m = re.match(r'v(\d+)\.', texto)
    return (int(m.group(1)), texto) if m else (None, 'versão do node ilegível')


# ---------------------------------------------------------------- leitura das saídas

RE_SKIP_PY = re.compile(r"\.\.\. skipped (['\"])(.*)\1\s*$", re.M)


def ler_resumo_unittest(texto):
    """(ok, resumo, skips) da saída `-v` do unittest. `skips` conta os motivos."""
    ran = re.findall(r'^Ran (\d+) tests? in ', texto, re.M)
    fim = re.findall(r'^(OK(?: \(.*\))?|FAILED \(.*\)|NO TESTS RAN(?: \(.*\))?)\s*$', texto, re.M)
    skips = Counter(m.group(2) for m in RE_SKIP_PY.finditer(texto))
    if not texto.strip():
        return False, 'sem saída: nenhum teste rodou (falta o unittest.main() no arquivo?)', skips
    if not ran or not fim:
        return False, 'sem o resumo do unittest (veja o log)', skips
    final = fim[-1]
    return final.startswith('OK') and int(ran[-1]) > 0, f'Ran {ran[-1]}  {final}', skips


def ler_resumo_node(texto):
    """(ok, resumo, skips) da saída TAP do `node --test`."""
    def conta(nome):
        m = re.findall(rf'^# {nome} (\d+)\s*$', texto, re.M)
        return int(m[-1]) if m else None
    tests, passou, falhou = conta('tests'), conta('pass'), conta('fail')
    cancelados, pulados = conta('cancelled') or 0, conta('skipped') or 0
    skips = Counter(m.strip() for m in re.findall(r'^\s*ok \d+ .*# SKIP\b ?(.*)$', texto, re.M))
    if tests is None or passou is None or falhou is None:
        return False, 'sem o resumo do node --test (veja o log)', skips
    resumo = f'tests {tests} pass {passou} fail {falhou}'
    if cancelados:
        resumo += f' cancelled {cancelados}'
    if pulados:
        resumo += f' (skipped={pulados})'
    return tests > 0 and falhou == 0 and cancelados == 0, resumo, skips


def ler_resumo_front(texto):
    """(ok, resumo, skips) da saída do testes/rodar.mjs."""
    linhas = re.findall(r'^\s*(RESULTADO: .*?)\s*$', texto, re.M)
    if not linhas:
        return False, 'sem a linha de resultado (o servidor estava no ar?)', Counter()
    return linhas[-1] == 'RESULTADO: OK', linhas[-1], Counter()


# ---------------------------------------------------------------- execução

def matar_grupo(pgid, espera=5):
    """SIGTERM e, se preciso, SIGKILL no grupo de processos. True se havia alguém vivo."""
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return False
    fim = time.monotonic() + espera
    while time.monotonic() < fim:
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.1)
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    return True


def rodar(cmd, env, log, timeout=TIMEOUT_SEG):
    """Roda `cmd` na raiz, num grupo de processos próprio, com a saída (stdout e stderr) em `log`.
    Devolve (código de saída ou None no timeout, segundos, sobrou_processo)."""
    t0 = time.monotonic()
    with open(log, 'wb') as f:
        p = subprocess.Popen(cmd, cwd=RAIZ, env=env, stdin=subprocess.DEVNULL, stdout=f,
                             stderr=subprocess.STDOUT, start_new_session=True)
        try:
            saida = p.wait(timeout)
        except subprocess.TimeoutExpired:
            matar_grupo(p.pid)
            p.wait()
            return None, time.monotonic() - t0, False
        except BaseException:
            matar_grupo(p.pid)
            p.wait()
            raise
    # Processo deixado vivo pelo teste (servidor de teste, por exemplo) morre aqui, junto com o grupo.
    sobrou = matar_grupo(p.pid, espera=2)
    return saida, time.monotonic() - t0, sobrou


def ler_log(log):
    with open(log, 'rb') as f:
        return f.read().decode('utf-8', 'replace')


def rodar_arquivo(nome, cmd, leitor, env, log, timeout=TIMEOUT_SEG):
    saida, tempo, sobrou = rodar(cmd, env, log, timeout)
    if saida is None:
        return Resultado(nome, False, None, tempo, f'passou de {timeout} s e foi encerrado', log=log)
    ok, resumo, skips = leitor(ler_log(log))
    ok = ok and saida == 0
    if sobrou:
        resumo += '  [deixou processo vivo; encerrado]'
    return Resultado(nome, ok, saida, tempo, resumo, skips, log)


def arquivos_python():
    """[(nome no resumo, nome do log, caminho relativo)] de todos os testes Python, em ordem."""
    lista = []
    for pasta, prefixo in PASTAS_PY:
        for caminho in sorted(glob.glob(os.path.join(RAIZ, pasta, 'test_*.py'))):
            base = os.path.basename(caminho)[:-3]
            lista.append((prefixo + base, prefixo.replace('/', '-') + base, os.path.relpath(caminho, RAIZ)))
    return lista


def arquivos_node():
    lista = []
    for caminho in sorted(glob.glob(os.path.join(RAIZ, PASTA_NODE, '*.test.mjs'))):
        base = os.path.basename(caminho)[:-len('.test.mjs')]
        lista.append(('node/' + base, 'node-' + base, os.path.relpath(caminho, RAIZ)))
    return lista


def compilar(pasta_tmp):
    """py_compile de COMPILAR, com o .pyc na pasta temporária (não suja __pycache__)."""
    t0 = time.monotonic()
    arquivos = sorted({c for padrao in COMPILAR for c in glob.glob(os.path.join(RAIZ, padrao))})
    erros = []
    for i, caminho in enumerate(arquivos):
        try:
            py_compile.compile(caminho, cfile=os.path.join(pasta_tmp, f'{i}.pyc'), doraise=True)
        except py_compile.PyCompileError as e:
            erros.append(f'{os.path.relpath(caminho, RAIZ)}: {e.exc_type_name}')
    resumo = f'{len(arquivos)} arquivos ' + ('OK' if not erros else 'FALHOU: ' + '; '.join(erros))
    return Resultado('py_compile', not erros and bool(arquivos), 0 if not erros else 1,
                     time.monotonic() - t0, resumo)


def pasta_de_logs():
    """logs/verificar-AAAAMMDD-HHMMSS (sufixo -N se já existir), em 0700."""
    os.makedirs(PASTA_LOGS, mode=0o700, exist_ok=True)
    carimbo = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    for n in range(100):
        caminho = os.path.join(PASTA_LOGS, f'verificar-{carimbo}' + (f'-{n}' if n else ''))
        try:
            os.mkdir(caminho, 0o700)
            return caminho
        except FileExistsError:
            continue
    raise RuntimeError('não consegui criar a pasta de logs')


# ---------------------------------------------------------------- front

def porta_ocupada(porta):
    """True se alguém já escuta na porta (bind em 127.0.0.1 falha ou o localhost atende)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)   # como o ThreadingHTTPServer
        s.bind(('127.0.0.1', porta))
    except OSError:
        return True
    finally:
        s.close()
    try:
        with socket.create_connection(('localhost', porta), timeout=0.5):
            return True
    except OSError:
        return False


def conferir_porta_front(porta):
    if porta == PORTA_REAL:
        raise ErroUso(f'o --front nunca usa a {PORTA_REAL} (servidor do dono); use a {PORTA_FRONT}')
    if not 1024 <= porta <= 65535:
        raise ErroUso(f'porta do --front inválida: {porta}')
    if porta_ocupada(porta):
        raise ErroUso(f'a porta {porta} está ocupada: pare o que está nela ou espere a outra verificação acabar')


def ambiente_front(env_base, porta, banco):
    """(ambiente do servidor, ambiente do runner) do --front. O servidor fica com os proxies mortos (o
    /api/fetch não sai para a rede); o runner (Chrome) fica sem proxy para baixar as 2 fotos reais."""
    servidor = dict(env_base, ACHADINHOS_DB=banco, ACHADINHOS_PORTA=str(porta), ACHADINHOS_DISPARO='0',
                    ACHADINHOS_API_TOKEN_ARQUIVO='/nao/existe')
    servidor.pop('PORTA', None)
    runner = {k: v for k, v in env_base.items() if k not in VARS_PROXY + VARS_SEM_PROXY}
    runner['PORTA'] = str(porta)
    return servidor, runner


def copiar_banco(origem, destino):
    """Cópia por sqlite3.backup, com a origem aberta em `mode=ro` (nunca grava no banco real)."""
    if not os.path.isfile(origem):
        raise RuntimeError('banco real não encontrado para a cópia')
    src = sqlite3.connect(pathlib.Path(origem).resolve().as_uri() + '?mode=ro', uri=True, timeout=30)
    try:
        dst = sqlite3.connect(destino)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    os.chmod(destino, 0o600)


def esperar_servidor(proc, porta, log, banco, limite=30):
    """Espera o servidor do --front atender. Só vale quando o log dele já disse que subiu sobre a cópia
    (o print vem depois do bind): assim, se outro processo tomar a porta no meio, o --front nunca testa
    contra ele."""
    marca = f'(banco: {banco})'
    fim = time.monotonic() + limite
    while time.monotonic() < fim:
        if proc.poll() is not None:
            raise RuntimeError(f'o servidor do --front saiu com {proc.returncode} (veja front-servidor.txt)')
        if marca in ler_log(log):
            try:
                con = http.client.HTTPConnection('127.0.0.1', porta, timeout=5)
                con.request('GET', '/api/items', headers={'Host': f'localhost:{porta}'})
                status = con.getresponse().status
                con.close()
                if status == 200:
                    return
            except OSError:
                pass
        time.sleep(0.3)
    raise RuntimeError(f'o servidor do --front não respondeu em {limite} s')


def paginas_do_front():
    """(nomes em FRONT, problemas de classificação) conferindo FRONT contra testes/*.test.html."""
    no_disco = {os.path.basename(c)[:-len('.test.html')]
                for c in glob.glob(os.path.join(RAIZ, 'testes', '*.test.html'))}
    problemas = [f'{n}: página nova sem classificação (ponha em FRONT ou FORA_DO_FRONT do verificar.py)'
                 for n in sorted(no_disco - set(FRONT) - set(FORA_DO_FRONT))]
    problemas += [f'{n}: está no FRONT, mas testes/{n}.test.html não existe'
                  for n in FRONT if n not in no_disco]
    return [n for n in FRONT if n in no_disco], problemas


def rodar_front(env_base, porta, pasta_logs, imprimir):
    try:
        conferir_porta_front(porta)   # de novo: a suíte pode ter levado minutos
    except ErroUso as e:
        # Ocupada durante a suíte: vira uma linha vermelha do resumo (FALHOU), não uso errado (saída 2).
        r = Resultado('front', False, 1, 0.0, str(e))
        imprimir(r)
        return [r]
    paginas, problemas = paginas_do_front()
    resultados = [Resultado('front/' + p.split(':')[0], False, 1, 0.0, p.split(': ', 1)[1]) for p in problemas]
    for r in resultados:
        imprimir(r)
    for nome, motivo in FORA_DO_FRONT.items():
        print(f'{"front/" + nome:<36} fora do --front: {motivo}', flush=True)
    if not shutil.which('google-chrome') or not shutil.which('node'):
        r = Resultado('front', False, 1, 0.0, 'google-chrome ou node não encontrado no PATH')
        imprimir(r)
        return resultados + [r]
    pasta = tempfile.mkdtemp(prefix='verificar-front-')   # 0700
    servidor = None
    try:
        banco = os.path.join(pasta, 'copia.db')
        copiar_banco(BANCO_REAL, banco)
        env_servidor, env_runner = ambiente_front(env_base, porta, banco)
        log_servidor = os.path.join(pasta_logs, 'front-servidor.txt')
        with open(log_servidor, 'wb') as log:
            servidor = subprocess.Popen([sys.executable, '-u', 'servidor.py'], cwd=RAIZ, env=env_servidor,
                                        stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                        start_new_session=True)
        esperar_servidor(servidor, porta, log_servidor, banco)
        for nome in paginas:
            r = rodar_arquivo('front/' + nome, ['node', os.path.join('testes', 'rodar.mjs'), nome,
                                                 str(SEGUNDOS_PAGINA)],
                              ler_resumo_front, env_runner, os.path.join(pasta_logs, f'front-{nome}.txt'))
            imprimir(r)
            resultados.append(r)
    except (RuntimeError, sqlite3.Error, OSError) as e:
        # Do sqlite e do SO, só o tipo: a mensagem pode trazer caminho ou detalhe do banco.
        motivo = (str(e) if isinstance(e, RuntimeError)
                  else f'falha ao copiar o banco ou subir o servidor ({type(e).__name__})')
        r = Resultado('front', False, 1, 0.0, motivo)
        imprimir(r)
        resultados.append(r)
    finally:
        if servidor is not None:
            matar_grupo(servidor.pid)
            servidor.wait()
        shutil.rmtree(pasta, ignore_errors=True)
    return resultados


# ---------------------------------------------------------------- servidor no ar (--servidor)

ROTA_VERSAO = '/api/versao'
MAX_RESPOSTA_VERSAO = 64 * 1024
TIMEOUT_VERSAO = 10


def pedir_versao(porta, timeout=TIMEOUT_VERSAO):
    """(status, corpo) de um GET em /api/versao no 127.0.0.1:<porta>, como o site pede (Host local).
    http.client não usa proxy. Levanta OSError se nada responder."""
    con = http.client.HTTPConnection('127.0.0.1', porta, timeout=timeout)
    try:
        con.request('GET', ROTA_VERSAO, headers={'Host': f'localhost:{porta}'})
        r = con.getresponse()
        return r.status, r.read(MAX_RESPOSTA_VERSAO + 1)
    finally:
        con.close()


def avaliar_versao(porta, status, corpo):
    """(saída, mensagem) a partir da resposta do /api/versao."""
    if status == 404:
        return 1, (f'servidor na {porta} sem a rota {ROTA_VERSAO}: servidor anterior a esta versão: '
                   'reinicie (skill rodar_localmente)')
    if status != 200:
        return 1, f'resposta inesperada de {ROTA_VERSAO} na {porta} (HTTP {status}): confira o servidor e reinicie'
    try:
        if len(corpo) > MAX_RESPOSTA_VERSAO:
            raise ValueError
        dados = json.loads(corpo)
        codigo, em_disco, mudou = dados['codigo'], dados['em_disco'], dados['mudou']
        if not isinstance(mudou, bool):
            raise ValueError
    except (ValueError, TypeError, KeyError):
        return 1, f'resposta ilegível de {ROTA_VERSAO} na {porta}: confira o servidor e reinicie'
    git = dados.get('git') or '?'
    desde = dados.get('iniciado_em') or '?'
    if mudou:
        return 1, (f'o código em disco mudou desde a subida (no ar: {codigo}, em disco: {em_disco}; '
                   f'no ar desde {desde}): reinicie (skill rodar_localmente)')
    return 0, f'em dia: o servidor na {porta} roda o código em disco ({codigo}, último commit {git}; no ar desde {desde})'


def conferir_servidor(porta):
    """--servidor: só leitura, um GET. Devolve a saída (0 em dia, 1 reiniciar ou fora do ar)."""
    try:
        status, corpo = pedir_versao(porta)
    except (OSError, http.client.HTTPException) as e:
        # Só o tipo: a mensagem do SO não diz mais que isso e não precisa ir para a tela.
        print(f'servidor fora do ar na {porta}: nada respondeu em 127.0.0.1:{porta} ({type(e).__name__}); '
              'suba com a skill rodar_localmente', flush=True)
        return 1
    saida, mensagem = avaliar_versao(porta, status, corpo)
    print(mensagem, flush=True)
    return saida


# ---------------------------------------------------------------- segredos e portão de commit (--segredos, --pre-commit)

# Montado em duas partes para o próprio verificar.py não conter o marcador.
MARCADOR = '# verificar: ' + 'permitir'
PASTA_GANCHOS = '.githooks'
# Código staged que faz o portão rodar a suíte (--rapido).
EXTENSOES_CODIGO = ('.py', '.mjs', '.html', '.json', '.sh')
TIMEOUT_GIT = 60

# Nomes que nunca entram no git (padrão do fnmatch sobre o nome do arquivo). `.env.example` é a exceção. Com `*` no
# fim, as cópias também (`api_token.txt.bak`, `_chat.txt~`, `ml_catalogo.json.old`): levam o mesmo conteúdo.
NOMES_PROIBIDOS = (
    'api_token*', 'api_cabecalho*',
    'ml_tokens.json*', '.ml_tokens.json.*.tmp', 'ml_catalogo.json*', '.ml_catalogo.json.*.tmp',
    '.env*', '*.db*', '*.sqlite*', '*.lock', '_chat.txt*',
)
NOME_LIBERADO = '.env.example'
PASTAS_PROIBIDAS = ('backups', 'logs')   # em qualquer nível do caminho
PREFIXO_PASTA_PROIBIDA = 'WhatsApp Chat'  # pasta (ou arquivo) exportada do WhatsApp, com o nome do dono

# (tipo, padrão). Só o tipo vai para a tela, nunca o trecho achado. A atribuição aceita a chave entre aspas
# ("secret": "...", {'token': '...'}), forma de JSON e de dict.
# Formato do ML conferido na doc pública (exemplos de resposta do /oauth/token, sem ler o ml_tokens.json):
# access token "APP_USR-<dígitos>-<6 dígitos>-<32 hex>-<user_id>"; refresh token e código de autorização
# "TG-<hex>-<user_id>" (23 ou 24 hex nos exemplos). O APP_USR- exige dígito logo depois do prefixo (o id da
# app): os tokens falsos dos testes do ml_api ("APP_USR-ACESSO-MARCADOR-...") não são achado.
# Valor de atribuição: 24 ou mais de [A-Za-z0-9_-] (o formato do secrets.token_urlsafe), com ao menos um dígito e
# uma letra; o AppID da Shopee é numérico (8 ou mais dígitos). Valor com cara de dado falso de teste (FALSO,
# MARCADOR, TESTE, EXEMPLO ou a sequência 12345) não é achado: os testes usam esses nomes de propósito.
_NAO_FALSO = r'(?![A-Za-z0-9_-]*(?:falso|marcador|teste|exemplo|1800012345))'
_VALOR_ATRIBUIDO = _NAO_FALSO + r'(?=[A-Za-z0-9_-]*[0-9])(?=[A-Za-z0-9_-]*[A-Za-z])[A-Za-z0-9_-]{24,}'
PADROES_SEGREDO = (
    ('chave privada PEM', re.compile(r'-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----')),
    ('Bearer com valor longo', re.compile(r'(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{32,}')),
    ('atribuição de segredo', re.compile(
        r'(?i)(?:secret|senha|password|token|app_id)[\'"]?\s*[:=]\s*[\'"]?' + _VALOR_ATRIBUIDO)),
    ('AppID numérico', re.compile(r'(?i)app_?id[\'"]?\s*[:=]\s*[\'"]?' + _NAO_FALSO + r'[0-9]{8,}')),
    ('access token do Mercado Livre (APP_USR-)', re.compile(r'\bAPP_USR-[0-9][0-9A-Za-z-]{19,}')),
    ('refresh token ou código do Mercado Livre (TG-)', re.compile(r'\bTG-[0-9a-fA-F]{16,}-[0-9]+')),
)


class ErroGit(Exception):
    """O git falhou ou a raiz não é um repositório: a mensagem é fixa (nunca a saída do git)."""


class Achado:
    def __init__(self, arquivo, linha, tipo, liberado=False):
        self.arquivo, self.linha, self.tipo, self.liberado = arquivo, linha, tipo, liberado

    def onde(self):
        return self.arquivo if self.linha is None else f'{self.arquivo}:{self.linha}'


def git(*args):
    """stdout (bytes) de `git <args>` na raiz. Herda o ambiente: dentro do hook, o GIT_INDEX_FILE do commit
    vale. Erro vira ErroGit com motivo fixo (o stderr do git pode citar caminho ou conteúdo)."""
    try:
        r = subprocess.run(['git', '--literal-pathspecs', *args], cwd=RAIZ, stdin=subprocess.DEVNULL,
                           capture_output=True, timeout=TIMEOUT_GIT)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ErroGit(f'git indisponível ({type(e).__name__})') from None
    if r.returncode != 0:
        raise ErroGit(f'git {args[0]} falhou (saída {r.returncode}): a raiz é um repositório git?')
    return r.stdout


def caminhos_z(saida):
    return [c for c in saida.decode('utf-8', 'surrogateescape').split('\0') if c]


def aviso_portao():
    """Aviso (texto) se o core.hooksPath não aponta para .githooks; None se aponta ou se a raiz não é git."""
    try:
        dentro = git('rev-parse', '--is-inside-work-tree').strip() == b'true'
    except ErroGit:
        return None
    if not dentro:
        return None
    try:
        valor = git('config', '--get', 'core.hooksPath').decode('utf-8', 'replace').strip()
    except ErroGit:   # sem a chave, o git config sai com 1
        valor = ''
    alvo = os.path.realpath(os.path.join(RAIZ, PASTA_GANCHOS))
    if valor and os.path.realpath(os.path.join(RAIZ, os.path.expanduser(valor))) == alvo:
        return None
    return (f'portão de commit desligado: core.hooksPath não aponta para {PASTA_GANCHOS} '
            f'(ligue com: git config core.hooksPath {PASTA_GANCHOS})')


def nome_proibido(caminho):
    """Tipo do achado se o caminho (relativo, com /) não pode entrar no git; senão None."""
    partes = caminho.split('/')
    for pasta in partes[:-1]:
        if pasta in PASTAS_PROIBIDAS:
            return f'pasta proibida ({pasta}/)'
    if any(p.startswith(PREFIXO_PASTA_PROIBIDA) for p in partes):
        return f'nome proibido ({PREFIXO_PASTA_PROIBIDA}*)'
    nome = partes[-1]
    if nome == NOME_LIBERADO:
        return None
    for padrao in NOMES_PROIBIDOS:
        if fnmatch.fnmatchcase(nome, padrao):
            return f'nome proibido ({padrao})'
    return None


def varrer_linhas(arquivo, linhas):
    """Achados de [(número, texto)]. Linha com o MARCADOR vira achado liberado (aparece no resumo)."""
    achados = []
    for n, texto in linhas:
        tipos = [tipo for tipo, padrao in PADROES_SEGREDO if padrao.search(texto)]
        liberado = MARCADOR in texto
        achados += [Achado(arquivo, n, tipo, liberado) for tipo in tipos]
    return achados


RE_HUNK = re.compile(rb'^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@')


def linhas_adicionadas(diff):
    """[(número na versão nova, texto)] das linhas `+` de um `git diff -U0` de um arquivo só."""
    linhas, n = [], None
    for bruta in diff.split(b'\n'):
        m = RE_HUNK.match(bruta)
        if m:
            n = int(m.group(1))
        elif n is not None and bruta.startswith(b'+'):
            linhas.append((n, bruta[1:].decode('utf-8', 'replace')))
            n += 1
    return linhas


def staged(com_apagados=True):
    """Caminhos staged (relativos à raiz). Sem `com_apagados`, só os que ficam no commit."""
    filtro = [] if com_apagados else ['--diff-filter=d']
    return caminhos_z(git('diff', '--cached', '--name-only', '-z', '--no-renames', *filtro))


def varrer_staged():
    """(achados, arquivos varridos): nomes dos arquivos staged e linhas adicionadas (git diff --cached -U0)."""
    achados = []
    arquivos = staged(com_apagados=False)
    for caminho in arquivos:
        tipo = nome_proibido(caminho)
        if tipo:   # o conteúdo de arquivo de nome proibido nem é lido (pode ser o segredo de verdade)
            achados.append(Achado(caminho, None, tipo))
            continue
        diff = git('diff', '--cached', '-U0', '--no-color', '--no-ext-diff', '--no-textconv', '--no-renames',
                   '--', caminho)
        achados += varrer_linhas(caminho, linhas_adicionadas(diff))
    return achados, len(arquivos)


def varrer_tudo():
    """(achados, arquivos varridos): todo arquivo rastreado e todo não rastreado fora do .gitignore, como está
    no disco. Binário (NUL nos primeiros 8 KB), symlink, arquivo apagado do disco e arquivo de nome proibido só
    têm o nome conferido."""
    arquivos = sorted(set(caminhos_z(git('ls-files', '-z', '--cached', '--others', '--exclude-standard'))))
    achados = []
    for caminho in arquivos:
        tipo = nome_proibido(caminho)
        if tipo:   # o conteúdo de arquivo de nome proibido nem é lido (pode ser o segredo de verdade)
            achados.append(Achado(caminho, None, tipo))
            continue
        disco = os.path.join(RAIZ, caminho)
        if os.path.islink(disco) or not os.path.isfile(disco):
            continue
        with open(disco, 'rb') as f:
            dados = f.read()
        if b'\0' in dados[:8192]:
            continue
        texto = dados.decode('utf-8', 'replace')
        achados += varrer_linhas(caminho, enumerate(texto.splitlines(), 1))
    return achados, len(arquivos)


def relatar_segredos(achados, arquivos, rotulo):
    """Imprime só arquivo, linha e tipo (nunca o trecho). 0 limpo, 1 com achado bloqueante."""
    for a in achados:
        if a.liberado:
            print(f'liberado pelo marcador: {a.onde()}: {a.tipo}  (revise)', flush=True)
    bloqueados = [a for a in achados if not a.liberado]
    for a in bloqueados:
        print(f'SEGREDO? {a.onde()}: {a.tipo}', flush=True)
    if bloqueados:
        print(f'\nFALHOU: {len(bloqueados)} achado(s) de segredo ({rotulo}). Nome proibido: tire o arquivo '
              f'(git rm --cached <arquivo>). Linha: tire o valor; se for falso positivo, ponha '
              f'"{MARCADOR}" no fim da linha.', flush=True)
        return 1
    print(f'segredos ({rotulo}): nada bloqueante em {arquivos} arquivo(s)', flush=True)
    return 0


def varrer_segredos(modo):
    aviso = aviso_portao()
    if aviso:
        print(f'aviso: {aviso}', flush=True)
    achados, arquivos = varrer_tudo() if modo == 'tudo' else varrer_staged()
    return relatar_segredos(achados, arquivos, modo)


def pre_commit():
    """Portão do commit: segredos no que está staged e, se houver código staged, a suíte --rapido (só com os
    testes rastreados: o teste fora do índice não é deste commit)."""
    aviso = aviso_portao()
    if aviso:
        print(f'aviso: {aviso}', flush=True)
    todos = staged()
    if not todos:
        print('pre-commit: nada staged', flush=True)
        return 0
    achados, arquivos = varrer_staged()
    if relatar_segredos(achados, arquivos, 'staged'):
        print('commit bloqueado pelo portão (segredos)', flush=True)
        return 1
    codigo = [c for c in todos if c.endswith(EXTENSOES_CODIGO)]
    if not codigo:
        print(f'pre-commit: nenhum {"/".join(EXTENSOES_CODIGO)} staged: os testes não rodam', flush=True)
        return 0
    print(f'pre-commit: {len(codigo)} arquivo(s) de código staged: rodando a suíte --rapido', flush=True)
    rastreados = set(caminhos_z(git('ls-files', '-z')))
    saida = verificar(ler_argumentos(['--rapido']), rastreados=rastreados, avisar_portao=False)
    if saida:
        print('commit bloqueado pelo portão (testes)', flush=True)
    return saida


# ---------------------------------------------------------------- linha de comando

def ler_argumentos(argv):
    def hora(texto):
        if not re.fullmatch(r'\d{1,2}', texto) or int(texto) > 23:
            raise argparse.ArgumentTypeError('use uma hora de 0 a 23')
        return int(texto)

    def porta(texto):
        if not re.fullmatch(r'\d{1,5}', texto):
            raise argparse.ArgumentTypeError('porta inválida')
        return int(texto)

    def porta_servidor(texto):
        n = porta(texto)
        if not 1 <= n <= 65535:
            raise argparse.ArgumentTypeError('porta inválida')
        return n

    p = argparse.ArgumentParser(prog='verificar.py', description='Verificação única do projeto (o "verde").')
    p.add_argument('--rapido', action='store_true',
                   help='com --dados-reais, pula os lentos (' + ', '.join(LENTOS) + '); sem ele, não pula nada')
    p.add_argument('--front', action='store_true',
                   help=f'também roda as páginas do front num servidor próprio na {PORTA_FRONT}, sobre uma cópia')
    p.add_argument('--porta-front', type=porta, default=PORTA_FRONT, metavar='P',
                   help=f'porta do servidor do --front (padrão {PORTA_FRONT}; a {PORTA_REAL} é recusada)')
    p.add_argument('--dados-reais', action='store_true',
                   help=f'liga os testes sobre a cópia do banco real ({VAR_DADOS_REAIS}=1)')
    p.add_argument('--hora', type=hora, metavar='H', help='roda com o relógio local na hora H (0 a 23)')
    p.add_argument('--servidor', type=porta_servidor, nargs='?', const=PORTA_REAL, metavar='P',
                   help=f'só confere se o servidor no ar na porta P (padrão {PORTA_REAL}) roda o código em disco '
                        f'e diz se é preciso reiniciar; não roda testes. Única exceção à regra de nunca usar a '
                        f'{PORTA_REAL}: só lê (um GET em {ROTA_VERSAO}). Sai com 0 em dia, 1 reinicie ou fora do ar')
    p.add_argument('--segredos', action='store_true',
                   help='só procura segredo (nomes proibidos e padrões); não roda testes. Mostra arquivo, linha e '
                        'tipo, nunca o trecho. Sai com 0 limpo, 1 com achado')
    alvo = p.add_mutually_exclusive_group()
    alvo.add_argument('--staged', action='store_true',
                      help='com --segredos (padrão): nomes staged e linhas adicionadas (git diff --cached -U0)')
    alvo.add_argument('--tudo', action='store_true',
                      help='com --segredos: todo arquivo rastreado e não rastreado fora do .gitignore, no disco')
    p.add_argument('--pre-commit', action='store_true',
                   help=f'portão do commit ({PASTA_GANCHOS}/pre-commit): --segredos --staged e, se houver '
                        f'{"/".join(EXTENSOES_CODIGO)} staged, a suíte --rapido só com os testes rastreados')
    args = p.parse_args(argv)
    suite = (args.rapido or args.front or args.dados_reais or args.hora is not None
             or args.porta_front != PORTA_FRONT)
    if (args.staged or args.tudo) and not args.segredos:
        p.error('--staged e --tudo só valem com --segredos')
    sozinhos = [nome for nome, ligado in (('--servidor', args.servidor is not None), ('--segredos', args.segredos),
                                          ('--pre-commit', args.pre_commit)) if ligado]
    if len(sozinhos) > 1 or (sozinhos and suite):
        p.error(f'{sozinhos[0]} roda sozinho: não junte com as opções da suíte nem com '
                + ', '.join(n for n in ('--servidor', '--segredos', '--pre-commit') if n != sozinhos[0]))
    return args


def imprimir_resultado(r):
    print(r.linha(), flush=True)
    for motivo, n in sorted(r.skips.items()):
        print(f'{"":<6}skip ({n}): {motivo}', flush=True)


def verificar(args, rastreados=None, avisar_portao=True):
    """A suíte. Com `rastreados` (caminhos relativos do `git ls-files`, só no --pre-commit), o teste fora do
    índice não roda: aparece como "fora do commit (não rastreado)"."""
    if args.front:
        conferir_porta_front(args.porta_front)
    pasta_logs = pasta_de_logs()
    tmp = tempfile.mkdtemp(prefix='verificar-')   # 0700
    resultados = []
    t0 = time.monotonic()
    try:
        print(f'verificar: logs em {os.path.relpath(pasta_logs, RAIZ)}/', flush=True)
        avisos = conferir_requirements()
        if sys.version_info < (3, 14):
            avisos.append(f'Python {sys.version.split()[0]}: o projeto pede 3.14 ou mais')
        maior, texto_node = versao_node()
        if maior is None or maior < 22:
            avisos.append(f'node: {texto_node} (o projeto pede 22 ou mais)')
        if avisar_portao:
            avisos.append(aviso_portao())
        for aviso in filter(None, avisos):
            print(f'aviso: {aviso}', flush=True)
        if args.hora is not None:
            tz = tz_para_hora(args.hora)
            try:
                zoneinfo.ZoneInfo(tz)
            except (zoneinfo.ZoneInfoNotFoundError, ValueError):
                print(f'FALHOU: fuso {tz} ausente do sistema (tzdata): o --hora não teria efeito', flush=True)
                return 1
            print(f'relógio local às {args.hora:02d}h (TZ Etc/GMT±N, calculado a cada arquivo)', flush=True)
        if args.dados_reais:
            print(f'dados reais ligados ({VAR_DADOS_REAIS}=1)', flush=True)

        def fora_do_commit(nome, rel):
            if rastreados is None or rel.replace(os.sep, '/') in rastreados:
                return False
            print(f'{nome:<36} fora do commit (não rastreado)', flush=True)
            return True

        def ambiente(nome):
            pasta = tempfile.mkdtemp(prefix=nome.replace('/', '-') + '-', dir=tmp)
            tz = tz_para_hora(args.hora) if args.hora is not None else None
            return ambiente_isolado(pasta, dados_reais=args.dados_reais, tz=tz)

        r = compilar(tmp)
        imprimir_resultado(r)
        resultados.append(r)
        for nome, nome_log, rel in arquivos_python():
            if fora_do_commit(nome, rel):
                continue
            if args.rapido and args.dados_reais and os.path.basename(rel)[:-3] in LENTOS:
                print(f'{nome:<36} pulado (--rapido: lento com --dados-reais)', flush=True)
                continue
            r = rodar_arquivo(nome, [sys.executable, rel, '-v'], ler_resumo_unittest, ambiente(nome),
                              os.path.join(pasta_logs, nome_log + '.txt'))
            imprimir_resultado(r)
            resultados.append(r)
        for nome, nome_log, rel in arquivos_node():
            if fora_do_commit(nome, rel):
                continue
            r = rodar_arquivo(nome, ['node', '--test', '--test-reporter=tap', rel], ler_resumo_node,
                              ambiente(nome), os.path.join(pasta_logs, nome_log + '.txt'))
            imprimir_resultado(r)
            resultados.append(r)
        if args.front:
            resultados += rodar_front(ambiente('front'), args.porta_front, pasta_logs, imprimir_resultado)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    falhas = [r for r in resultados if not r.ok]
    minutos = (time.monotonic() - t0) / 60
    if falhas:
        print(f'\nFALHOU: {len(falhas)} de {len(resultados)} em {minutos:.1f} min: '
              + ', '.join(r.nome for r in falhas), flush=True)
        print(f'logs em {os.path.relpath(pasta_logs, RAIZ)}/', flush=True)
        return 1
    print(f'\nVERDE: {len(resultados)} itens em {minutos:.1f} min', flush=True)
    return 0


def main(argv=None):
    args = ler_argumentos(argv)   # uso errado: o argparse sai com 2
    if args.servidor is not None:
        return conferir_servidor(args.servidor)
    try:
        if args.segredos:
            return varrer_segredos('tudo' if args.tudo else 'staged')
        if args.pre_commit:
            return pre_commit()
        return verificar(args)
    except ErroUso as e:
        print(f'verificar.py: {e}', file=sys.stderr)
        return 2
    except ErroGit as e:
        print(f'verificar.py: {e}', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('\ninterrompido', file=sys.stderr)
        return 130


def _sigterm(_sinal, _quadro):
    raise KeyboardInterrupt


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, _sigterm)   # limpa a cópia, o servidor e os filhos também no kill
    sys.exit(main())
