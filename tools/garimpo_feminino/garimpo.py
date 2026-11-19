#!/usr/bin/env python3
"""Garimpo feminino na Open API de afiliados da Shopee: o comando que o dono roda, fase por fase.

Uso (na raiz do projeto, num terminal só para isso; o Secret vale só para este comando, sem export):
    read -rs S; ACHADINHOS_SHOPEE_SECRET="$S" ACHADINHOS_SHOPEE_APP_ID=<id> \\
        python3 tools/garimpo_feminino/garimpo.py <subcomando> [opções]; unset S

Subcomandos: conferir | reconhecer | mapa | piloto | garimpar | links | exportar | conversoes.
Plano: docs/produto/planos/garimpo-feminino-shopee.md, etapa 4 (CA5, CA7, CA8 e CA9).

- `conferir` mora aqui: 1 requisição (a mesma busca do `coletar_shopee.py conferir`) e a conferência do dono
  do primeiro link (`coletar_shopee.conferir_dono`, utm_source=an_<ID>). Não grava produto nenhum: só a linha
  da requisição em `requisicoes`, que conta no orçamento.
- Os outros vivem em `fase_<nome>.py` (o `piloto` e o `garimpar` no `fase_garimpar.py`), carregados só quando
  pedidos. Cada um tem `configurar(parser)` e `rodar(args, ctx) -> int`; `USA_API = False` no módulo dispensa a
  credencial e o cliente (ex.: `exportar`). Nos que usam a API, o `--max-req` (teto desta rodada) é
  acrescentado aqui: a fase não o declara.
- Ordem: argumentos → `coletar_shopee.credenciais()` (tira o Secret do ambiente com pop) → log → ID de afiliado,
  credencial, `achados.json`, `categorias.json` → trava (`garimpo.lock`) → `garimpo.db` → fase. Nenhum banco é
  aberto antes da credencial, e o achadinhos.db nunca é aberto.
- Pasta de dados: `ACHADINHOS_GARIMPO_DIR` (padrão: esta pasta) com `garimpo.db`, `garimpo.lock`, `logs/` e
  `exports/`. O `achados.json` e o `categorias.json` ficam nesta pasta (versionados, sem segredo).
- Log em `logs/<sub>-<AAAAMMDD-HHMMSS>.log` (0600): tudo o que vai para a tela, com data e hora, e a última
  linha `SAIDA=<n>`. Nunca leva o Secret, a assinatura nem texto de exceção de biblioteca (só o tipo).
- Rodada longa: o `prctl(PR_SET_DUMPABLE, 0)` no topo, antes de importar o coletar_shopee e de ler a credencial,
  fecha o /proc/<pid>/environ para outros processos do usuário (o `pop` não apaga o Secret dali); o `tail -f` do log
  e o `kill` continuam funcionando. Se o sistema recusar, a rodada segue com um AVISO.

Saída: 0 ok; 1 erro (dono errado, API recusou, resposta fora do formato, falha inesperada); 2 configuração
(credencial, ID de afiliado, achados.json/categorias.json inválidos, outra rodada em andamento, banco que não é
o garimpo.db, subcomando ainda não implementado); 3 limite da API ou teto de requisições (o checkpoint fica
salvo; rode de novo depois); 130 interrompido (Ctrl+C, `kill` ou terminal fechado; com `nohup`, fechar o terminal
não interrompe).
"""
import argparse
import importlib
import json
import math
import os
import re
import signal
import stat
import sys
import time


def proteger_processo():
    """PR_SET_DUMPABLE = 0: outro processo do mesmo usuário não lê o /proc/<pid>/environ, onde o Secret fica até o
    fim da rodada. True se o sistema aceitou; False em qualquer falha (fora do Linux, por exemplo), sem levantar."""
    try:
        import ctypes
        return ctypes.CDLL(None, use_errno=True).prctl(4, 0, 0, 0, 0) == 0
    except (ImportError, OSError, AttributeError):
        return False


PROCESSO_PROTEGIDO = proteger_processo()   # antes de importar o coletar_shopee e de ler a credencial

PASTA = os.path.dirname(os.path.abspath(__file__))
if PASTA not in sys.path:
    sys.path.insert(0, PASTA)

import banco  # noqa: E402
import cliente as K  # noqa: E402
import foco  # noqa: E402

CS = K.CS

ACHADOS = os.path.join(PASTA, 'achados.json')
CATEGORIAS = os.path.join(PASTA, 'categorias.json')
NICHOS = os.path.join(PASTA, 'nichos.json')
NOME_BANCO = 'garimpo.db'
MAX_CONFIG = 1024 * 1024   # bytes de cada arquivo de configuração
MAX_CATEGORIAS = 20_000
SAIDAS = (0, 1, 2, 3, 130)
# Teto da rodada (--max-req) quando o dono não passa nenhum: só o reconhecer tem, porque a rodada dele é curta e de
# tamanho conhecido (a completa cabe nisso, e o --refazer-taxa também; o plano prevê 80 a 250).
MAX_REQ_PADRAO = {'reconhecer': 250}

# subcomando → módulo da fase (None: implementado aqui)
SUBCOMANDOS = {
    'conferir': None,
    'reconhecer': 'fase_reconhecer',
    'mapa': 'fase_mapa',
    'piloto': 'fase_garimpar',
    'garimpar': 'fase_garimpar',
    'links': 'fase_links',
    'exportar': 'fase_exportar',
    'conversoes': 'fase_conversoes',
}
AJUDA = {
    'conferir': 'faz 1 busca e confere que o link gerado é do dono; não grava produto',
    'reconhecer': 'Fase 1: mede os limites reais da API (docs/api_findings.md)',
    'mapa': 'Fase 2: mapa de categorias femininas',
    'piloto': 'Fase 3: piloto em 3 categorias e estimativa de requisições',
    'garimpar': 'Fase 4: garimpo por categoria até saturar',
    'links': 'Fase 5: links de teste com subIds',
    'exportar': 'Fase 6: exports e RELATORIO.md (sem API)',
    'conversoes': 'Fase 7: relatórios de conversão por subId',
}

# Busca do `conferir`: a mesma consulta e o mesmo termo do coletar_shopee.py, valores só em "variables".
VARIAVEIS_CONFERIR = {'keyword': CS.TERMO_CONFERENCIA, 'sortType': 1, 'page': 1, 'limit': CS.POR_BUSCA}

# achados.json: chave → (padrão, validação). O dev grava os valores medidos na etapa 8 (e o orçamento no R3).
RE_ESTRATEGIA = re.compile(r'[a-z][a-z0-9_]{0,39}', re.A)
RE_CAT_ID = re.compile(r'[1-9][0-9]{0,18}', re.A)
RE_SEPARADOR = re.compile(r'[!-/:-@\[-`{-~]', re.A)   # um sinal ASCII visível (nem letra, nem dígito, nem espaço)
PADROES_ACHADOS = {
    'limit': 20,                                 # itens por página (medido no reconhecer)
    'teto_pagina': 100,                          # última página que a API devolve (medido)
    'int64': 'texto',                            # como mandar Int64: 'numero' ou 'texto' (medido)
    'list_types': [],                            # listType úteis com matchId de categoria (medido)
    'separador_subids': None,                    # separador dos subIds no relatório (medido; None = não medido)
    'estrategias': None,                         # ordem das estratégias do motor (None = a ordem do brief)
    'orcamento_aprovado': None,                  # requisições que o dono aprovou para o garimpar (R3)
    'max_total_requests': K.MAX_TOTAL_REQUESTS,  # teto total no garimpo.db (brief: 20.000)
    'pausa': K.PAUSA_PADRAO,                     # segundos entre requisições (piso 0,5)
    'paginas_sem_novo': 3,                       # páginas seguidas sem item novo que encerram uma consulta
}


AUSENTE = object()   # ler_json_estrito: o arquivo não existe (diferente de um arquivo com `null`)


class ErroConfig(banco.ErroConfig):
    """achados.json, categorias.json ou nichos.json inválido (saída 2). Mensagem fixa: nada do conteúdo."""


# ---------- leitura estrita dos arquivos de configuração ----------
def _sem_duplicadas(pares):
    d = {}
    for k, v in pares:
        if k in d:
            raise ValueError('chave repetida')
        d[k] = v
    return d


def _constante_proibida(_):
    raise ValueError('NaN e Infinity não são JSON válido')


def ler_json_estrito(caminho, nome):
    """JSON do arquivo, ou AUSENTE se ele não existir. Recusa (ErroConfig) symlink, o que não é arquivo comum,
    mais de MAX_CONFIG bytes, UTF-8 inválido, chave repetida, NaN e Infinity."""
    try:
        fd = os.open(caminho, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except FileNotFoundError:
        return AUSENTE
    except OSError:
        raise ErroConfig(f'não consegui abrir o {nome} (symlink ou sem permissão)') from None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ErroConfig(f'o {nome} não é um arquivo comum')
        with os.fdopen(fd, 'rb', closefd=False) as f:
            bruto = f.read(MAX_CONFIG + 1)
    except OSError:
        raise ErroConfig(f'não consegui ler o {nome}') from None
    finally:
        os.close(fd)
    if len(bruto) > MAX_CONFIG:
        raise ErroConfig(f'o {nome} passa de {MAX_CONFIG} bytes')
    try:
        return json.loads(bruto.decode('utf-8'), object_pairs_hook=_sem_duplicadas,
                          parse_constant=_constante_proibida)
    except (ValueError, RecursionError):
        raise ErroConfig(f'o {nome} não é JSON válido em UTF-8 (ou tem chave repetida)') from None


def _eh_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _int_na_faixa(v, minimo, maximo):
    return _eh_int(v) and minimo <= v <= maximo


def _validar_achado(chave, v):
    """True se o valor da chave do achados.json está no tipo e na faixa."""
    if chave == 'limit':
        return _int_na_faixa(v, 1, 500)
    if chave == 'teto_pagina':
        return _int_na_faixa(v, 1, 10_000)
    if chave == 'int64':
        return v in ('numero', 'texto') and isinstance(v, str)
    if chave == 'list_types':
        return (isinstance(v, list) and all(_int_na_faixa(x, 0, 5) for x in v)
                and len(set(v)) == len(v))
    if chave == 'separador_subids':
        return v is None or isinstance(v, str) and RE_SEPARADOR.fullmatch(v) is not None
    if chave == 'estrategias':
        return v is None or (isinstance(v, list) and 0 < len(v) <= 30 and len(set(map(str, v))) == len(v)
                             and all(isinstance(x, str) and RE_ESTRATEGIA.fullmatch(x) for x in v))
    if chave == 'orcamento_aprovado':
        return v is None or _int_na_faixa(v, 1, 1_000_000)
    if chave == 'max_total_requests':
        return _int_na_faixa(v, 1, 1_000_000)
    if chave == 'pausa':
        return ((_eh_int(v) or isinstance(v, float)) and math.isfinite(v)
                and K.PAUSA_MINIMA <= v <= K.PAUSA_MAXIMA)
    if chave == 'paginas_sem_novo':
        return _int_na_faixa(v, 1, 100)
    return False


def ler_achados(caminho=None):
    """Configuração medida (achados.json) com os padrões no que faltar. Arquivo ausente = só padrões.

    Recusa (ErroConfig, saída 2): o que não é objeto, chave fora de PADROES_ACHADOS, tipo ou faixa errados.
    """
    dados = ler_json_estrito(caminho or ACHADOS, 'achados.json')
    achados = json.loads(json.dumps(PADROES_ACHADOS))   # cópia funda: o padrão nunca é alterado
    if dados is AUSENTE:
        return achados
    if not isinstance(dados, dict):
        raise ErroConfig('o achados.json tem de ser um objeto')
    fora = [k for k in dados if k not in PADROES_ACHADOS]
    if fora:
        raise ErroConfig('o achados.json tem chave fora da lista: ' + ', '.join(PADROES_ACHADOS))
    for chave, v in dados.items():
        if not _validar_achado(chave, v):
            raise ErroConfig(f'valor inválido no achados.json: {chave}')
        achados[chave] = float(v) if chave == 'pausa' else v
    return achados


def ler_nichos(caminho=None):
    """Slugs dos nichos do nichos.json (lista de {slug, nome, sementes})."""
    dados = ler_json_estrito(caminho or NICHOS, 'nichos.json')
    if (not isinstance(dados, list) or not dados
            or not all(isinstance(n, dict) and isinstance(n.get('slug'), str) for n in dados)):
        raise ErroConfig('o nichos.json está ausente ou fora do formato')
    slugs = [n['slug'] for n in dados]
    if len(set(slugs)) != len(slugs) or any(foco.slug(s) != s or not s for s in slugs):
        raise ErroConfig('o nichos.json tem slug repetido ou fora de [a-z0-9]')
    return frozenset(slugs)


def ler_categorias(caminho=None, nichos=None):
    """Classe e nicho finais por cat_id (categorias.json). Arquivo ausente = nenhuma categoria revisada ({}).

    Formato: {"<cat_id>": {"classe": "feminina"|"mista"|"fora", "nicho": "<slug do nichos.json>"|null,
    "nome": "<texto>" (opcional)}}. Devolve {cat_id: {"classe", "nicho", "nome"}}.
    """
    dados = ler_json_estrito(caminho or CATEGORIAS, 'categorias.json')
    if dados is AUSENTE:
        return {}
    if not isinstance(dados, dict):
        raise ErroConfig('o categorias.json tem de ser um objeto {cat_id: {classe, nicho, nome}}')
    if len(dados) > MAX_CATEGORIAS:
        raise ErroConfig(f'o categorias.json passa de {MAX_CATEGORIAS} categorias')
    nichos = ler_nichos() if nichos is None else nichos
    saida = {}
    for cat_id, v in dados.items():
        if not RE_CAT_ID.fullmatch(cat_id) or int(cat_id) > banco.MAX_ID:
            raise ErroConfig('o categorias.json tem cat_id que não é um id numérico')
        if not isinstance(v, dict) or not set(v) <= {'classe', 'nicho', 'nome'} or 'classe' not in v:
            raise ErroConfig(f'categoria {cat_id} do categorias.json: só classe (obrigatória), nicho e nome')
        if v['classe'] not in foco.CLASSES or not isinstance(v['classe'], str):
            raise ErroConfig(f'categoria {cat_id} do categorias.json: classe fora de {", ".join(foco.CLASSES)}')
        nicho = v.get('nicho')
        if nicho is not None and (not isinstance(nicho, str) or nicho not in nichos):
            raise ErroConfig(f'categoria {cat_id} do categorias.json: nicho fora do nichos.json')
        nome = v.get('nome')
        if nome is not None and (not isinstance(nome, str) or not 0 < len(nome) <= 200
                                 or any(ord(c) < 32 or 0x7f <= ord(c) <= 0x9f for c in nome)):
            raise ErroConfig(f'categoria {cat_id} do categorias.json: nome tem de ser texto de 1 a 200 caracteres')
        saida[cat_id] = {'classe': v['classe'], 'nicho': nicho, 'nome': nome}
    return saida


# ---------- pasta de dados e log ----------
def pasta_dados():
    """Pasta do garimpo.db, da trava, dos logs e dos exports (ACHADINHOS_GARIMPO_DIR, lida a cada rodada)."""
    return os.path.abspath(os.environ.get('ACHADINHOS_GARIMPO_DIR') or PASTA)


def _limpo(texto):
    """Uma linha só: caractere de controle vira espaço (nada de \\r ou escape de terminal no log)."""
    return ''.join(' ' if ord(c) < 32 or 0x7f <= ord(c) <= 0x9f else c for c in str(texto))


class Log:
    """Escreve cada mensagem na tela e em logs/<sub>-<AAAAMMDD-HHMMSS>.log, linha a linha (dá para acompanhar
    com tail -f). `fechar(n)` grava a última linha, `SAIDA=<n>`."""

    def __init__(self, arquivo, caminho):
        self._f, self.caminho = arquivo, caminho

    @classmethod
    def abrir(cls, pasta, sub, instante=None):
        logs = os.path.join(pasta, 'logs')
        try:
            os.makedirs(logs, mode=0o700, exist_ok=True)
        except OSError:
            raise banco.ErroConfig('não consegui criar a pasta logs/ do garimpo') from None
        base = f'{sub}-{time.strftime("%Y%m%d-%H%M%S", time.localtime(instante))}'
        for n in range(1, 100):   # duas rodadas no mesmo segundo: <sub>-<data>-2.log
            caminho = os.path.join(logs, base + ('' if n == 1 else f'-{n}') + '.log')
            try:
                fd = os.open(caminho, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
            except FileExistsError:
                continue
            except OSError:
                break
            return cls(os.fdopen(fd, 'w', encoding='utf-8', buffering=1), caminho)
        raise banco.ErroConfig('não consegui criar o arquivo de log em logs/')

    def __call__(self, mensagem, *, erro=False):
        linha = _limpo(mensagem)
        self._f.write(f'{time.strftime("%Y-%m-%dT%H:%M:%S")} {linha}\n')
        try:
            print(linha, file=sys.stderr if erro else sys.stdout, flush=True)
        except OSError:   # terminal fechado: o log em arquivo é o que vale
            pass

    def fechar(self, codigo):
        try:
            self._f.write(f'SAIDA={codigo}\n')
        finally:
            self._f.close()


# ---------- contexto que a fase recebe ----------
class Contexto:
    """O que a fase recebe em `rodar(args, ctx)`: nunca a credencial (ela fica dentro do cliente)."""

    def __init__(self, *, pasta, con, cliente, achados, categorias, log):
        self.pasta, self.con, self.cliente = pasta, con, cliente
        self.achados, self.categorias, self.log = achados, categorias, log
        self.exports = os.path.join(pasta, 'exports')

    def registrar(self, req):
        """Grava, sozinha, uma requisição que não trouxe página (o `registrar` padrão do cliente)."""
        banco.registrar_requisicao(self.con, None, None, req)

    def __repr__(self):
        return f'Contexto(pasta={self.pasta!r}, cliente={self.cliente!r})'


# ---------- argumentos e despacho sob demanda ----------
def _positivo(texto):
    try:
        n = int(texto, 10)
    except ValueError:
        raise argparse.ArgumentTypeError('tem de ser um inteiro') from None
    if not 1 <= n <= 1_000_000:
        raise argparse.ArgumentTypeError('tem de ficar entre 1 e 1000000')
    return n


def carregar_fase(nome_modulo):
    """Importa fase_<nome>.py, ou None se ele ainda não existir (outro erro de import sobe)."""
    try:
        modulo = importlib.import_module(nome_modulo)
    except ModuleNotFoundError as e:
        if e.name == nome_modulo:
            return None
        raise
    if not callable(getattr(modulo, 'configurar', None)) or not callable(getattr(modulo, 'rodar', None)):
        raise TypeError(f'{nome_modulo}.py precisa de configurar(parser) e rodar(args, ctx)')
    return modulo


def usa_api(modulo):
    return modulo is None or getattr(modulo, 'USA_API', True) is not False


def ler_argumentos(argv):
    """(args, módulo da fase ou None). Só o módulo do subcomando pedido é importado."""
    argv = list(sys.argv[1:] if argv is None else argv)
    p = argparse.ArgumentParser(prog='garimpo.py', description='Garimpo feminino na Open API de afiliados da '
                                'Shopee. Credenciais só no ambiente do comando (veja o topo do garimpo.py).')
    sub = p.add_subparsers(dest='sub', required=True, metavar='SUBCOMANDO')
    parsers = {nome: sub.add_parser(nome, help=AJUDA[nome], description=AJUDA[nome]) for nome in SUBCOMANDOS}
    nome = next((a for a in argv if not a.startswith('-')), None)
    modulo = None
    if SUBCOMANDOS.get(nome):
        modulo = carregar_fase(SUBCOMANDOS[nome])
        if modulo is not None:
            modulo.configurar(parsers[nome])
            if usa_api(modulo):
                padrao = MAX_REQ_PADRAO.get(nome)
                parsers[nome].add_argument('--max-req', type=_positivo, default=padrao, metavar='N',
                                           help='teto de requisições desta rodada (sai com 3 ao chegar nele)'
                                                + (f'; padrão: {padrao}' if padrao else ''))
    args = p.parse_args(argv)
    args.implementado = SUBCOMANDOS[args.sub] is None or modulo is not None
    return args, modulo


# ---------- conferir ----------
def links_da_resposta(dados):
    """offerLink dos nós de data.productOfferV2.nodes que são link curto de afiliado da Shopee."""
    oferta = dados.get('productOfferV2') if isinstance(dados, dict) else None
    nos = oferta.get('nodes') if isinstance(oferta, dict) else None
    if not isinstance(nos, list):
        raise CS.RespostaInvalida()
    links = [n.get('offerLink') for n in nos if isinstance(n, dict)]
    return len(nos), [x for x in links if isinstance(x, str) and len(x) <= CS.MAX_URL and CS.S.eh_link_shopee(x)]


def rodar_conferir(args, ctx):
    dados = ctx.cliente.pedir(CS.CONSULTA, dict(VARIAVEIS_CONFERIR), registrar=ctx.registrar)
    total, links = links_da_resposta(dados)
    ctx.log(f'conferir: a busca devolveu {total} nós, {len(links)} com link curto de afiliado.')
    if not links:
        ctx.log('A busca não trouxe link para conferir. Tente de novo mais tarde.', erro=True)
        return 1
    CS.conferir_dono(links[0])
    ctx.log(f'OK: o link gerado pela API é do afiliado {CS.ID_AFILIADO_SHOPEE}.')
    return 0


# ---------- rodada ----------
def _rodar_fase(args, modulo, cred, pasta, log):
    """Confere a configuração, trava, abre o garimpo.db e roda a fase. Devolve o código de saída."""
    if not CS.id_afiliado_ok():
        log('ERRO: preencha ID_AFILIADO_SHOPEE no coletar_shopee.py (só números).', erro=True)
        return 2
    if usa_api(modulo) and cred is None:
        log('ERRO: defina ACHADINHOS_SHOPEE_APP_ID e ACHADINHOS_SHOPEE_SECRET só para este comando, sem export, '
            'num terminal só para isso: read -rs S; ACHADINHOS_SHOPEE_SECRET="$S" '
            'ACHADINHOS_SHOPEE_APP_ID=<id> python3 tools/garimpo_feminino/garimpo.py ...; unset S', erro=True)
        return 2
    if not args.implementado:
        log(f'ERRO: o subcomando {args.sub} ainda não foi implementado ({SUBCOMANDOS[args.sub]}.py).', erro=True)
        return 2
    achados = ler_achados()
    categorias = ler_categorias()
    with banco.travar(pasta):
        con = banco.abrir(os.path.join(pasta, NOME_BANCO))
        try:
            cli = None
            if usa_api(modulo):
                ja_feitas = con.execute('SELECT COUNT(*) FROM requisicoes').fetchone()[0]
                cli = K.Cliente(cred, ja_feitas=ja_feitas, max_total=achados['max_total_requests'],
                                max_rodada=getattr(args, 'max_req', None), pausa=achados['pausa'])
                log(f'orçamento: {ja_feitas} requisições já feitas de {achados["max_total_requests"]}'
                    + (f'; teto desta rodada: {args.max_req}' if getattr(args, 'max_req', None) else '') + '.')
            ctx = Contexto(pasta=pasta, con=con, cliente=cli, achados=achados, categorias=categorias, log=log)
            codigo = rodar_conferir(args, ctx) if modulo is None else modulo.rodar(args, ctx)
            if cli is not None:
                log(f'requisições nesta rodada: {cli.feitas}.')
        finally:
            con.close()
    if not _eh_int(codigo) or codigo not in SAIDAS:
        log('ERRO: a fase devolveu um código de saída inválido.', erro=True)
        return 1
    return codigo


def executar(args, modulo, cred, pasta, log):
    """_rodar_fase com as saídas 0/1/2/3/130 (como o main do coletar_shopee.py). Mensagens fixas: nada do
    texto das exceções de biblioteca, que pode trazer dados da requisição."""
    try:
        return _rodar_fase(args, modulo, cred, pasta, log)
    except K.Teto as e:
        qual = 'desta rodada (--max-req)' if e.qual == 'rodada' else 'total (max_total_requests do achados.json)'
        log(f'PAROU: chegou ao teto de requisições {qual}. O checkpoint foi salvo; rode de novo para continuar.',
            erro=True)
        return 3
    except CS.LimiteAtingido:
        log(f'PAROU: limite de requisições da API da Shopee (código {CS.ERRO_LIMITE} ou HTTP 429, depois de '
            f'{K.TENTATIVAS_LIMITE} esperas). O checkpoint foi salvo; espere e rode de novo.', erro=True)
        return 3
    except CS.DonoErrado:
        log(f'PAROU: o link gerado não leva a utm_source=an_{CS.ID_AFILIADO_SHOPEE}. Nada foi gravado nem exportado. '
            'Confira as credenciais e o ID_AFILIADO_SHOPEE.', erro=True)
        return 1
    except CS.ErroApi as e:
        detalhe = ', '.join(x for x in (f'código {e.codigo}' if e.codigo is not None else '',
                                        f'HTTP {e.http}' if e.http is not None else '') if x)
        log(f'ERRO: a API da Shopee recusou ou não respondeu ({detalhe or "sem código"}).', erro=True)
        return 1
    except CS.RespostaInvalida:
        log('ERRO: resposta da API da Shopee fora do formato esperado.', erro=True)
        return 1
    except banco.ErroConfig as e:   # textos fixos do banco.py e deste arquivo
        log(f'ERRO: {e}', erro=True)
        return 2
    except KeyboardInterrupt:
        log('Interrompido. O checkpoint da última página gravada foi salvo; rode de novo para retomar.', erro=True)
        return 130
    except Exception as e:   # só o tipo: a mensagem de biblioteca pode trazer dados da requisição
        log(f'ERRO: {type(e).__name__}', erro=True)
        return 1


def instalar_sinais():
    """`kill` e terminal fechado viram KeyboardInterrupt, como o Ctrl+C: a rodada desfaz a página em curso, solta a
    trava e o log fecha com SAIDA=130. Sinal já ignorado continua ignorado: é assim que o `nohup` funciona."""
    for sinal in (signal.SIGTERM, signal.SIGHUP):
        if signal.getsignal(sinal) != signal.SIG_IGN:
            signal.signal(sinal, signal.default_int_handler)


def main(argv=None):
    instalar_sinais()
    args, modulo = ler_argumentos(argv)
    # O Secret sai do ambiente antes de qualquer outra coisa (pop); nenhum banco foi aberto até aqui.
    cred = CS.credenciais() if usa_api(modulo) else None
    pasta = pasta_dados()
    try:
        log = Log.abrir(pasta, args.sub)
    except banco.ErroConfig as e:
        print(f'ERRO: {e}', file=sys.stderr, flush=True)
        return 2
    codigo = 1
    try:
        log(f'garimpo {args.sub}: início (log em {os.path.relpath(log.caminho, pasta)}).')
        if not PROCESSO_PROTEGIDO:
            log('AVISO: o sistema não deixou fechar o /proc/<pid>/environ deste processo; outro processo do seu '
                'usuário pode ler o ambiente enquanto a rodada durar.', erro=True)
        codigo = executar(args, modulo, cred, pasta, log)
    except KeyboardInterrupt:   # o sinal chegou fora do executar (ou outro, durante a saída dele)
        codigo = 130
    finally:
        log.fechar(codigo)
    return codigo


if __name__ == '__main__':
    sys.exit(main())
