#!/usr/bin/env python3
"""Cliente da API oficial do Mercado Livre (OAuth 2.0 com PKCE, só leitura), pelo terminal do dono.

Uso:  python3 ml_api.py autorizar   (pede o Secret no ambiente do comando)
      python3 ml_api.py conferir
      python3 ml_api.py sondar
      python3 ml_api.py sair

Plano: docs/produto/planos/api-oficial-ml.md, etapas 1 e 2 (CA2 a CA6, CA9).

Este é o único módulo que fala com a API do ML. Ele não importa o servidor.py: nenhum código do servidor
toca o arquivo de tokens, e os tokens nunca vão para a tabela config, para rota, página ou log.

Ambiente:
  ACHADINHOS_ML_SECRET  Secret do app "Etiqueta" no DevCenter. Exigido só no `autorizar` e quando o
      access_token precisa ser renovado. Lido com pop (sai do ambiente do processo) e guardado num Segredo;
      vai só no corpo do POST /oauth/token ao host fixo. Num terminal só para isso, sem export:
        read -rs S; ACHADINHOS_ML_SECRET="$S" python3 ml_api.py autorizar; unset S
  ACHADINHOS_ML_TOKENS  arquivo dos tokens (padrão ml_tokens.json ao lado deste arquivo, no .gitignore).
  ACHADINHOS_DB  banco de onde o `sondar` lê 3 ids MLB, em modo só leitura (como no servidor.py).
Nenhuma variável troca o host da API, o Client ID ou o endereço de retorno.

Arquivo de tokens (JSON, até 4 KB, modo 0600, gravado por escrita atômica):
  {"v":1,"user_id":<int>,"access_token":"…","expira_em":<epoch int>,"refresh_token":"…","scope":"…",
   "renovado_em":"AAAA-MM-DDTHH:MM:SS"}
A leitura recusa symlink, arquivo que não é comum, dono diferente do usuário, permissão aberta e arquivo grande.
A renovação roda sob flock exclusivo em <arquivo>.lock, relendo o arquivo dentro do lock: o refresh_token é de
uso único, então dois comandos ao mesmo tempo não podem gastá-lo duas vezes.

Saída: 0 ok; 1 erro (API recusou, resposta fora do formato, endereço colado errado, autorização negada, rede);
2 configuração (sem tokens ou autorização vencida: rode `ml_api.py autorizar`; renovação fora do formato ou sem
refresh_token; Secret ausente ou recusado; permissão funcional que falta no DevCenter; arquivo de tokens inseguro);
3 limite de requisições da API; 130 interrompido (Ctrl+C).
As mensagens são fixas: token, code, verifier e Secret nunca saem na tela nem em mensagem de exceção.
"""
import argparse, base64, contextlib, fcntl, getpass, hashlib, hmac, http.client, json, math, os, pathlib, random, re
import secrets, sqlite3, stat, sys, time, unicodedata, urllib.error, urllib.parse, urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
TOKENS = os.environ.get('ACHADINHOS_ML_TOKENS') or os.path.join(BASE, 'ml_tokens.json')
DB = os.environ.get('ACHADINHOS_DB') or os.path.join(BASE, 'achadinhos.db')

# ---------- constantes fixas do app "Etiqueta" no DevCenter (não são segredo) ----------
CLIENT_ID = '3553760734310605'
REDIRECT_URI = 'https://desejodemenina.com/ml/callback'
URL_AUTORIZACAO = 'https://auth.mercadolivre.com.br/authorization'
HOST_API = 'api.mercadolibre.com'
URL_API = 'https://' + HOST_API
URL_TOKEN = URL_API + '/oauth/token'
# endereço colado: o que a página de retorno mostra na barra (com ou sem a barra final do 301 da Hostinger)
HOST_RETORNO = 'desejodemenina.com'
CAMINHOS_RETORNO = ('/ml/callback', '/ml/callback/')

MARGEM_RENOVACAO = 300            # s: renova quando faltam menos de 5 min para o access_token vencer
MAX_ARQUIVO_TOKENS = 4096         # bytes
MAX_RESPOSTA = 2 * 1024 * 1024    # bytes; resposta maior é recusada (dado não confiável)
MAX_ENDERECO = 4096               # caracteres do endereço colado
TENTATIVAS_LIMITE = 3             # 429 ou local_rate_limited: depois da 3ª, saída 3
BACKOFF_BASE = 2.0                # s; espera = base * 2^(n-1) * (1 + jitter de 0 a 1)
TIMEOUT = 30
UA = 'Etiqueta/1 (ml_api.py)'

RE_TOKEN = re.compile(r'[A-Za-z0-9._~+/=-]{16,1024}', re.A)
RE_CODE = re.compile(r'[A-Za-z0-9_-]{1,256}', re.A)
RE_STATE = re.compile(r'[A-Za-z0-9_-]{1,128}', re.A)
RE_ESCOPO = re.compile(r'[\x20-\x7e]{0,2048}', re.A)   # o ML manda a lista inteira de permissões (339+ chars, com / e ,); só ASCII imprimível, sem controle
RE_DATA_HORA = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}', re.A)
RE_CODIGO_ERRO = re.compile(r'[A-Za-z_]{1,64}', re.A)   # único texto da resposta de erro que pode sair na tela
RE_CAMINHO = re.compile(r'(?:/[A-Za-z0-9_.-]+)+', re.A)
RE_MLB = re.compile(r'MLB[0-9]{6,19}', re.A)
RE_PRODUTO = re.compile(r'MLB[0-9]{1,19}', re.A)
CHAVES_TOKENS = {'v', 'user_id', 'access_token', 'expira_em', 'refresh_token', 'scope', 'renovado_em'}

RECEITA_SECRET = ('read -rs S; ACHADINHOS_ML_SECRET="$S" python3 ml_api.py {comando}; unset S')

# Título de produto usado (Decisão 4 do plano abas-nichadas-e-coleta), sem acento e em minúsculas (ver `eh_usado`).
# Cópia do RE_USADO do coletar_amazon.py e do coletar_shopee.py (e do RX_USADO do coletar_ml.js): mudar a lista
# exige mexer em todos (o teste amarra).
RE_USADO = re.compile(r'\b(?:usad[oa]s?|recondicionad[oa]s?|renovad[oa]s?|seminov[oa]s?|vitrine|open\s+box|refurbished)\b')


class Segredo:
    """Guarda um valor sensível sem deixá-lo aparecer em repr, str, f-string ou traceback com variáveis locais."""
    __slots__ = ('_valor',)

    def __init__(self, valor):
        self._valor = valor

    def valor(self):
        return self._valor

    def __repr__(self):
        return 'Segredo(***)'

    __str__ = __repr__

    def __format__(self, spec):
        return repr(self)


# ---------- erros: mensagem fixa, nada vindo de fora além de status e código filtrado ----------
class ErroML(Exception):
    saida = 1
    mensagem = 'erro na API do Mercado Livre'

    def __init__(self, mensagem=None):
        super().__init__(mensagem or self.mensagem)


class ConfigFaltando(ErroML):
    saida = 2
    mensagem = ('falta o Secret do app (ACHADINHOS_ML_SECRET). Num terminal só para isso, sem export: '
                + RECEITA_SECRET.format(comando='<comando>'))


class TokensRecusados(ConfigFaltando):
    """Arquivo de tokens inseguro ou fora do formato. O motivo é texto fixo."""
    def __init__(self, motivo):
        super().__init__(f'arquivo de tokens recusado ({motivo}). Corrija ou apague o arquivo e rode '
                         '`ml_api.py autorizar`')
        self.motivo = motivo


class RefazerAutorizacao(ErroML):
    saida = 2
    mensagem = 'a autorização do Mercado Livre não vale mais (ou não existe): rode `ml_api.py autorizar`'


class CredencialInvalida(ErroML):
    saida = 2
    mensagem = ('o Mercado Livre recusou o app (Secret errado ou renovado no DevCenter?). Confira o Secret e '
                'rode `ml_api.py autorizar`')

    def __init__(self, codigo=None):
        """`codigo` é o `error` do ML já filtrado por RE_CODIGO_ERRO (só [A-Za-z_]); nunca o corpo inteiro."""
        extra = f' [ML: {codigo}]' if codigo and RE_CODIGO_ERRO.fullmatch(codigo) else ''
        super().__init__(self.mensagem + extra)
        self.codigo = codigo


class SemPermissao(ErroML):
    saida = 2
    mensagem = ('o app Etiqueta não tem a permissão funcional para este recurso (403 PolicyAgent). No DevCenter, '
                'ative "Publicação e sincronização" em somente leitura')

    def __init__(self, codigo=None):
        super().__init__()
        self.status = 403
        self.codigo = codigo if isinstance(codigo, str) and RE_CODIGO_ERRO.fullmatch(codigo) else None


class Limite(ErroML):
    saida = 3
    mensagem = 'limite de requisições da API do Mercado Livre (429). Espere de 15 a 30 min e rode de novo'


class RespostaInvalida(ErroML):
    mensagem = 'resposta da API do Mercado Livre fora do formato esperado'


class RenovacaoInvalida(RespostaInvalida):
    """Resposta 200 da renovação fora do formato: o refresh_token pode ter sido gasto, então pede o autorizar já."""
    saida = 2
    mensagem = ('a renovação do acesso ao Mercado Livre voltou fora do formato esperado (o refresh_token pode ter '
                'sido gasto). Nada foi gravado: rode `ml_api.py autorizar`')


class SemRefreshToken(RenovacaoInvalida):
    mensagem = ('o Mercado Livre renovou o acesso sem mandar refresh_token. No DevCenter, confira se o app Etiqueta '
                'tem o fluxo "Refresh Token" (offline_access) ativo e rode `ml_api.py autorizar`')


class ErroRede(ErroML):
    mensagem = 'falha de rede ao falar com o Mercado Livre'


class EnderecoInvalido(ErroML):
    """Endereço colado fora do esperado. O motivo é texto fixo: o endereço nunca é ecoado."""
    def __init__(self, motivo):
        super().__init__(f'endereço colado recusado ({motivo}). Rode `ml_api.py autorizar` de novo e cole o '
                         'endereço inteiro da página de retorno')
        self.motivo = motivo


class AutorizacaoNegada(ErroML):
    mensagem = ('o Mercado Livre devolveu erro na autorização (error= no endereço): nada foi gravado. '
                'Rode `ml_api.py autorizar` de novo e aceite o acesso')


class ErroApi(ErroML):
    def __init__(self, status, codigo=None):
        self.status = status if isinstance(status, int) and not isinstance(status, bool) and 100 <= status <= 599 else 0
        self.codigo = codigo if isinstance(codigo, str) and RE_CODIGO_ERRO.fullmatch(codigo) else None
        super().__init__(f'a API do Mercado Livre recusou: HTTP {self.status}'
                         + (f' ({self.codigo})' if self.codigo else ' (sem código)'))


# ---------- funções puras de mapeamento ----------
def _numero(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _arredondar_js(x):
    """Math.round do JS: o inteiro mais próximo; no empate, o de cima (floor(x + 0.5) erra em 0.49999999999999994)."""
    r = math.floor(x)
    return r + 1 if x - r >= 0.5 else r


def formatar_preco(v):
    """Porte fiel do formatarPreco do coletar_ml.js: 2569 → "R$ 2.569"; 124.2 → "R$ 124,20"."""
    if not _numero(v) or v < 0:
        raise ValueError('preço inválido')
    centavos = _arredondar_js(v * 100)
    inteiro = f'{centavos // 100:,}'.replace(',', '.')
    resto = centavos % 100
    return 'R$ ' + inteiro + (f',{resto:02d}' if resto else '')


def desconto(atual, antes):
    """(preco_antigo, desconto) como no polycardParaItem do coletar_ml.js, ou ('', '') sem desconto de verdade.

    Diferença que arredonda para 0% não é desconto ("-0%").
    """
    if not _numero(atual) or atual <= 0 or not _numero(antes) or antes <= atual:
        return '', ''
    pct = _arredondar_js(100 - (atual * 100) / antes)
    if pct <= 0:
        return '', ''
    return formatar_preco(antes), f'-{pct}%'


def sem_acento(texto):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(texto or '')) if not unicodedata.combining(c)).lower()


def eh_usado(titulo):
    """Título de usado, recondicionado, seminovo, renovado, de vitrine ou open box, sem acento e com `\\b`."""
    return isinstance(titulo, str) and bool(RE_USADO.search(sem_acento(titulo)))


# ---------- PKCE, state e endereço colado ----------
def novo_pkce():
    """(verifier, challenge): verifier de 86 caracteres, challenge = base64url(sha256(verifier)) sem '='."""
    verifier = secrets.token_urlsafe(64)
    return verifier, desafio(verifier)


def desafio(verifier):
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode('ascii')).digest()).rstrip(b'=').decode('ascii')


def novo_state():
    return secrets.token_urlsafe(32)


def url_autorizacao(state, challenge):
    return URL_AUTORIZACAO + '?' + urllib.parse.urlencode({
        'response_type': 'code', 'client_id': CLIENT_ID, 'redirect_uri': REDIRECT_URI, 'state': state,
        'code_challenge': challenge, 'code_challenge_method': 'S256'})


def ler_endereco_colado(texto, state):
    """code do endereço colado, conferido contra o state. Levanta EnderecoInvalido ou AutorizacaoNegada.

    Ordem: formato, host e caminho; error=; state (em tempo constante); code. Nada do endereço vai para a mensagem.
    """
    if not isinstance(texto, str):
        raise EnderecoInvalido('vazio')
    texto = texto.strip()
    if not texto:
        raise EnderecoInvalido('vazio')
    if len(texto) > MAX_ENDERECO or not texto.isascii() or any(c.isspace() or ord(c) < 32 or ord(c) == 127
                                                              for c in texto):
        raise EnderecoInvalido('caracteres inesperados')
    try:
        partes = urllib.parse.urlsplit(texto)
        porta = partes.port
    except ValueError:
        raise EnderecoInvalido('formato') from None
    if partes.scheme != 'https' or partes.netloc != HOST_RETORNO or porta is not None:
        raise EnderecoInvalido('o endereço não é da página de retorno')
    if partes.path not in CAMINHOS_RETORNO or partes.fragment or texto.endswith('#'):
        raise EnderecoInvalido('o endereço não é da página de retorno')
    try:
        campos = urllib.parse.parse_qs(partes.query, keep_blank_values=True, strict_parsing=True, max_num_fields=20)
    except ValueError:
        raise EnderecoInvalido('formato') from None
    if 'error' in campos:
        raise AutorizacaoNegada()
    estados, codigos = campos.get('state', []), campos.get('code', [])
    if len(estados) != 1 or not RE_STATE.fullmatch(estados[0]):
        raise EnderecoInvalido('state ausente ou repetido')
    if not hmac.compare_digest(estados[0].encode('ascii'), state.encode('ascii')):
        raise EnderecoInvalido('state diferente: o endereço não é desta autorização')
    if len(codigos) != 1 or not RE_CODE.fullmatch(codigos[0]):
        raise EnderecoInvalido('code ausente, repetido ou fora do formato')
    return codigos[0]


# ---------- arquivo de tokens ----------
class Tokens:
    """Conteúdo do arquivo de tokens. access e refresh ficam em Segredo; o repr não mostra nenhum dos dois."""
    __slots__ = ('user_id', 'access', 'expira_em', 'refresh', 'scope', 'renovado_em')

    def __init__(self, user_id, access, expira_em, refresh, scope, renovado_em):
        self.user_id, self.expira_em, self.scope, self.renovado_em = user_id, expira_em, scope, renovado_em
        self.access, self.refresh = Segredo(access), Segredo(refresh)

    def __repr__(self):
        return f'Tokens(user_id={self.user_id}, expira_em={self.expira_em}, scope={self.scope!r}, ***)'

    __str__ = __repr__

    def como_json(self):
        return json.dumps({'v': 1, 'user_id': self.user_id, 'access_token': self.access.valor(),
                           'expira_em': self.expira_em, 'refresh_token': self.refresh.valor(),
                           'scope': self.scope, 'renovado_em': self.renovado_em}, ensure_ascii=True)


def _inteiro(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _tokens_validos(d):
    """Tokens a partir do JSON do arquivo, ou None se algo estiver fora do formato."""
    if not isinstance(d, dict) or set(d) != CHAVES_TOKENS or d['v'] != 1 or not _inteiro(d['v']):
        return None
    if not (_inteiro(d['user_id']) and d['user_id'] > 0 and _inteiro(d['expira_em']) and d['expira_em'] >= 0):
        return None
    for k in ('access_token', 'refresh_token'):
        if not isinstance(d[k], str) or not RE_TOKEN.fullmatch(d[k]):
            return None
    if not isinstance(d['scope'], str) or not RE_ESCOPO.fullmatch(d['scope']):
        return None
    if not isinstance(d['renovado_em'], str) or not RE_DATA_HORA.fullmatch(d['renovado_em']):
        return None
    return Tokens(d['user_id'], d['access_token'], d['expira_em'], d['refresh_token'], d['scope'], d['renovado_em'])


def ler_tokens(caminho):
    """Tokens do arquivo, com leitura estrita. Sem arquivo: RefazerAutorizacao. Inseguro ou estranho: TokensRecusados."""
    try:
        info = os.lstat(caminho)
    except FileNotFoundError:
        raise RefazerAutorizacao() from None
    except OSError:
        raise TokensRecusados('não consegui ler o arquivo') from None
    if stat.S_ISLNK(info.st_mode):
        raise TokensRecusados('é um link simbólico')
    try:
        # O_NOFOLLOW fecha a janela entre o lstat e o open; O_NONBLOCK: um FIFO não trava
        fd = os.open(caminho, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except FileNotFoundError:
        raise RefazerAutorizacao() from None
    except OSError:
        raise TokensRecusados('não consegui abrir o arquivo') from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise TokensRecusados('não é um arquivo comum')
        if info.st_uid != os.getuid():
            raise TokensRecusados('o dono do arquivo não é o seu usuário')
        if info.st_mode & 0o077:
            raise TokensRecusados('permissão aberta para grupo ou outros; use chmod 600')
        if info.st_size > MAX_ARQUIVO_TOKENS:
            raise TokensRecusados(f'passa de {MAX_ARQUIVO_TOKENS} bytes')
        bruto = os.read(fd, MAX_ARQUIVO_TOKENS + 1)
    except OSError:
        raise TokensRecusados('não consegui ler o arquivo') from None
    finally:
        os.close(fd)
    if len(bruto) > MAX_ARQUIVO_TOKENS:
        raise TokensRecusados(f'passa de {MAX_ARQUIVO_TOKENS} bytes')
    try:
        tokens = _tokens_validos(json.loads(bruto.decode('ascii')))
    except (ValueError, RecursionError):
        tokens = None
    if tokens is None:
        raise TokensRecusados('conteúdo fora do formato')
    return tokens


def gravar_tokens(caminho, tokens):
    """Grava por escrita atômica: arquivo temporário 0600 (O_EXCL|O_NOFOLLOW) na mesma pasta, fsync,
    os.replace e fsync da pasta. Quem chama segura o lock (travar)."""
    dados = tokens.como_json().encode('ascii')
    if len(dados) > MAX_ARQUIVO_TOKENS:
        raise RespostaInvalida()
    pasta = os.path.dirname(os.path.abspath(caminho))
    tmp = os.path.join(pasta, f'.{os.path.basename(caminho)}.{secrets.token_hex(8)}.tmp')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        try:
            os.fchmod(fd, 0o600)   # o umask só tira permissão; isto garante 0600 exato
            vista = memoryview(dados)
            while vista:
                vista = vista[os.write(fd, vista):]
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp, caminho)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
    fd_pasta = os.open(pasta, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(fd_pasta)
    finally:
        os.close(fd_pasta)


@contextlib.contextmanager
def travar(caminho):
    """flock exclusivo em <caminho>.lock (arquivo comum, 0600, do próprio usuário)."""
    trava = caminho + '.lock'
    try:
        fd = os.open(trava, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, 0o600)
    except OSError:
        raise TokensRecusados('não consegui abrir o arquivo de trava (.lock)') from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise TokensRecusados('o arquivo de trava (.lock) não é um arquivo comum do seu usuário')
        if stat.S_IMODE(info.st_mode) != 0o600:
            os.fchmod(fd, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def agora_local(epoch):
    return time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(epoch))


def tokens_da_resposta(resposta, agora, user_id=None):
    """Tokens a partir da resposta do POST /oauth/token. user_id: o da conta já gravada (renovação)."""
    if not isinstance(resposta, dict):
        raise RespostaInvalida()
    if os.environ.get('ACHADINHOS_ML_DIAG') == '1':
        # Diagnóstico opcional: só os NOMES dos campos (filtrados), nunca valores.
        nomes = sorted(k for k in resposta if isinstance(k, str) and re.fullmatch(r'[A-Za-z_]{1,32}', k))
        print('Diag: campos da resposta do token: ' + ', '.join(nomes[:20]), file=sys.stderr)
        # Por campo: tipo, tamanho e se passa na regex. Nunca o valor.
        for k, rx in (('access_token', RE_TOKEN), ('refresh_token', RE_TOKEN), ('scope', RE_ESCOPO)):
            v = resposta.get(k)
            ok = isinstance(v, str) and bool(rx.fullmatch(v))
            print(f'Diag: {k}: tipo={type(v).__name__} tam={len(v) if isinstance(v, str) else "-"} regex={ok}',
                  file=sys.stderr)
        for k in ('expires_in', 'user_id'):
            v = resposta.get(k)
            print(f'Diag: {k}: tipo={type(v).__name__} inteiro={_inteiro(v)}', file=sys.stderr)
    access, refresh = resposta.get('access_token'), resposta.get('refresh_token')
    expira, uid, escopo = resposta.get('expires_in'), resposta.get('user_id'), resposta.get('scope', '')
    if not (isinstance(access, str) and RE_TOKEN.fullmatch(access) and isinstance(refresh, str)
            and RE_TOKEN.fullmatch(refresh)):
        raise RespostaInvalida()   # sem refresh_token (app sem offline_access?) também não serve
    if not (_inteiro(expira) and 0 < expira <= 10 * 86400 and _inteiro(uid) and uid > 0):
        raise RespostaInvalida()
    if user_id is not None and uid != user_id:
        raise RespostaInvalida()
    if not isinstance(escopo, str) or not RE_ESCOPO.fullmatch(escopo):
        raise RespostaInvalida()
    agora = int(agora)
    return Tokens(uid, access, agora + expira, refresh, escopo, agora_local(agora))


# ---------- rede ----------
class SemRedirecionar(urllib.request.HTTPRedirectHandler):
    """Nenhum redirect é seguido: o Authorization não vai para outro lugar. O 3xx vira HTTPError."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


OPENER = urllib.request.build_opener(SemRedirecionar)


def _ler_json(r):
    bruto = r.read(MAX_RESPOSTA + 1)
    if len(bruto) > MAX_RESPOSTA:
        raise RespostaInvalida()
    try:
        return json.loads(bruto)
    except (ValueError, RecursionError):
        raise RespostaInvalida() from None


class _Recusa(Exception):
    """Resposta HTTP de erro já lida: status e o código do ML filtrado (uso interno)."""
    def __init__(self, status, codigo, politica):
        super().__init__(status)
        self.status, self.codigo, self.politica = status, codigo, politica


def _codigo_do_corpo(corpo):
    """(código, PolicyAgent?) do corpo de erro do ML: `error` ou `code`, só se casar com [A-Za-z_]{1,64}."""
    if not isinstance(corpo, dict):
        return None, False
    codigo = None
    for k in ('error', 'code'):
        v = corpo.get(k)
        if isinstance(v, str) and RE_CODIGO_ERRO.fullmatch(v):
            codigo = v
            break
    if 'local_rate_limited' in (corpo.get('error'), corpo.get('code')):
        codigo = 'local_rate_limited'
    cod = corpo.get('code')
    politica = corpo.get('blocked_by') == 'PolicyAgent' or (isinstance(cod, str) and cod.startswith('PA_'))
    if politica and isinstance(cod, str) and RE_CODIGO_ERRO.fullmatch(cod):
        codigo = cod
    return codigo, politica


def _abrir(opener, req):
    """JSON da resposta 2xx; _Recusa para status de erro (inclusive 3xx não seguido); ErroRede para falha de rede."""
    try:
        with opener.open(req, timeout=TIMEOUT) as r:
            return _ler_json(r)
    except urllib.error.HTTPError as e:
        try:
            codigo, politica = _codigo_do_corpo(_ler_json(e))
        except Exception:
            codigo, politica = None, False
        finally:
            e.close()
        raise _Recusa(e.code, codigo, politica) from None
    except RespostaInvalida:
        raise
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError):
        raise ErroRede() from None


def _eh_limite(recusa):
    return recusa.status == 429 or recusa.codigo == 'local_rate_limited'


class Sessao:
    """Cliente só de leitura da API do ML, com o access_token do arquivo e renovação automática."""

    def __init__(self, caminho=TOKENS, segredo=None, opener=None, relogio=time.time, dormir=time.sleep,
                 aleatorio=random.random):
        self.caminho, self.segredo = caminho, segredo
        self.opener = opener   # None: o OPENER do módulo, lido na hora (os testes o trocam)
        self.relogio, self.dormir, self.aleatorio = relogio, dormir, aleatorio
        # um 401 renova (e gasta o refresh_token de uso único) no máximo uma vez por sessão: se o ML insistir
        # no 401, o resto vira ErroApi(401), sem rotacionar o refresh a cada chamada
        self._renovou_por_401 = False

    def __repr__(self):
        return 'Sessao(***)'

    def _opener(self):
        return self.opener or OPENER

    def _com_limite(self, fazer):
        """Chama fazer() com backoff exponencial e jitter em 429/local_rate_limited; Limite depois da 3ª vez."""
        tentativa = 0
        while True:
            try:
                return fazer()
            except _Recusa as e:
                if not _eh_limite(e):
                    raise
                tentativa += 1
                if tentativa >= TENTATIVAS_LIMITE:
                    raise Limite() from None
                self.dormir(BACKOFF_BASE * 2 ** (tentativa - 1) * (1 + self.aleatorio()))

    def _post_token(self, campos):
        """POST /oauth/token (form) ao host fixo. O Secret vai só neste corpo."""
        def fazer():
            req = urllib.request.Request(URL_TOKEN, data=urllib.parse.urlencode(campos).encode('ascii'),
                                         method='POST', headers={
                                             'Content-Type': 'application/x-www-form-urlencoded',
                                             'Accept': 'application/json', 'User-Agent': UA})
            return _abrir(self._opener(), req)
        try:
            return self._com_limite(fazer)
        except _Recusa as e:
            if e.codigo == 'invalid_grant':
                raise RefazerAutorizacao() from None
            if e.codigo in ('invalid_client', 'unauthorized_client'):
                raise CredencialInvalida(e.codigo) from None
            raise ErroApi(e.status, e.codigo) from None

    def _segredo(self):
        if self.segredo is None:
            raise ConfigFaltando()
        return self.segredo.valor()

    def trocar_code(self, code, verifier):
        """Troca o code do endereço colado pelos tokens (sem gravar)."""
        resposta = self._post_token({
            'grant_type': 'authorization_code', 'client_id': CLIENT_ID, 'client_secret': self._segredo(),
            'code': code, 'redirect_uri': REDIRECT_URI, 'code_verifier': verifier})
        return tokens_da_resposta(resposta, self.relogio())

    def _vale(self, tokens):
        return tokens.expira_em - self.relogio() >= MARGEM_RENOVACAO

    def token(self):
        """access_token válido por mais de 5 min, renovando se preciso."""
        tokens = ler_tokens(self.caminho)
        if self._vale(tokens):
            return tokens.access.valor()
        return self.renovar()

    def renovar(self, recusado=None):
        """Renova sob flock, relendo o arquivo dentro do lock. Se outro processo já renovou (o token do arquivo
        vale e não é o `recusado`), usa o dele sem gastar o refresh_token. O novo par é gravado antes de
        qualquer outra chamada."""
        with travar(self.caminho):
            tokens = ler_tokens(self.caminho)
            atual = tokens.access.valor()
            if self._vale(tokens) and (recusado is None or not hmac.compare_digest(atual, recusado)):
                return atual
            try:
                resposta = self._post_token({
                    'grant_type': 'refresh_token', 'client_id': CLIENT_ID, 'client_secret': self._segredo(),
                    'refresh_token': tokens.refresh.valor()})
                if isinstance(resposta, dict) and not resposta.get('refresh_token'):
                    raise SemRefreshToken()
                novos = tokens_da_resposta(resposta, self.relogio(), user_id=tokens.user_id)
            except RenovacaoInvalida:
                raise
            except RespostaInvalida:
                raise RenovacaoInvalida() from None
            gravar_tokens(self.caminho, novos)
            return novos.access.valor()

    def get(self, caminho, params=None):
        """GET na API (host fixo, Bearer no header). Devolve dict ou list.

        401: uma renovação e uma nova tentativa, só uma vez por sessão (self._renovou_por_401). 403 PolicyAgent: SemPermissao. 429: Limite depois
        de 3 tentativas. Outros: ErroApi(status, código filtrado)."""
        url = montar_url(caminho, params)
        token = self.token()

        def fazer():
            req = urllib.request.Request(url, method='GET', headers={
                'Authorization': 'Bearer ' + token, 'Accept': 'application/json', 'User-Agent': UA})
            return _abrir(self._opener(), req)
        while True:
            try:
                resposta = self._com_limite(fazer)
            except _Recusa as e:
                if e.status == 401 and not self._renovou_por_401:
                    self._renovou_por_401 = True
                    token = self.renovar(recusado=token)
                    continue
                if e.status == 403 and e.politica:
                    raise SemPermissao(e.codigo) from None
                raise ErroApi(e.status, e.codigo) from None
            if not isinstance(resposta, (dict, list)):
                raise RespostaInvalida()
            return resposta


def montar_url(caminho, params=None):
    """URL da API a partir de um caminho montado pelo código. Caminho estranho é erro de programação."""
    if not isinstance(caminho, str) or not RE_CAMINHO.fullmatch(caminho) or '/../' in caminho + '/' \
            or '/./' in caminho + '/':
        raise ValueError('caminho da API inválido')
    url = URL_API + caminho
    if params:
        url += '?' + urllib.parse.urlencode(params, safe=',')   # a vírgula dos ids do /items/bulk vai crua
    partes = urllib.parse.urlsplit(url)
    if partes.scheme != 'https' or partes.netloc != HOST_API:
        raise ValueError('caminho da API inválido')
    return url


# ---------- ambiente ----------
def ler_segredo():
    """Segredo do ambiente (pop: sai do os.environ do processo), ou None se faltar."""
    valor = os.environ.pop('ACHADINHOS_ML_SECRET', '') or ''
    if valor and os.environ.get('ACHADINHOS_ML_DIAG') == '1':
        # Diagnóstico opcional: só o tamanho e se há espaço nas pontas, nunca o valor.
        aviso = ' (com espaço nas pontas)' if valor != valor.strip() else ''
        print(f'Secret recebido: {len(valor)} caracteres{aviso}.', file=sys.stderr)
    return Segredo(valor) if valor else None


def sessao_do_ambiente():
    return Sessao(TOKENS, ler_segredo())


def ler_colado(prompt):
    """Lê o endereço colado sem eco: no terminal, pelo getpass (o endereço, com o code, não aparece na tela nem
    fica no histórico de rolagem). Sem terminal (stdin redirecionado, como nos testes com processo de verdade),
    lê do stdin, que não ecoa; o getpass ali leria do /dev/tty e ficaria esperando."""
    if sys.stdin is not None and sys.stdin.isatty():
        return getpass.getpass(prompt)
    return input(prompt)


def _sobras(caminho):
    """Temporários da escrita atômica (.<arquivo>.<16 hex>.tmp) que um processo morto deixou: só arquivos comuns
    do próprio usuário."""
    pasta = os.path.dirname(os.path.abspath(caminho))
    padrao = re.compile(r'\.' + re.escape(os.path.basename(caminho)) + r'\.[0-9a-f]{16}\.tmp', re.A)
    try:
        nomes = os.listdir(pasta)
    except OSError:
        return []
    achados = []
    for nome in nomes:
        if not padrao.fullmatch(nome):
            continue
        p = os.path.join(pasta, nome)
        try:
            info = os.lstat(p)
        except OSError:
            continue
        if stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid():
            achados.append(p)
    return achados


def _limpar_sobras(caminho):
    """Apaga as sobras. Quem chama segura o lock (travar): nenhuma gravação está em andamento."""
    for p in _sobras(caminho):
        with contextlib.suppress(OSError):
            os.unlink(p)


# ---------- subcomandos ----------
def autorizar(caminho, segredo, opener=None, entrada=None, relogio=time.time):
    """Fluxo inteiro num processo só: nenhum dado vai para o disco antes da troca do code. A trava (vazia) abre
    antes da troca: pasta sem escrita ou .lock estranho aparecem antes de gastar o code, que vale uma vez."""
    if segredo is None:
        raise ConfigFaltando(ConfigFaltando.mensagem.replace('<comando>', 'autorizar'))
    verifier, challenge = novo_pkce()
    state = novo_state()
    print('1. Abra este endereço no navegador, entre na conta do Mercado Livre e autorize o app Etiqueta:', flush=True)
    print(url_autorizacao(state, challenge), flush=True)
    print('2. Na página "Autorização recebida", copie o endereço inteiro da barra (Ctrl+L e Ctrl+C).', flush=True)
    texto = (entrada or ler_colado)('3. Cole aqui e tecle Enter (o endereço não aparece): ')
    code = ler_endereco_colado(texto, state)
    sessao = Sessao(caminho, segredo, opener=opener, relogio=relogio)
    with travar(caminho):
        tokens = sessao.trocar_code(code, verifier)
        _limpar_sobras(caminho)
        gravar_tokens(caminho, tokens)
    print('OK: autorização gravada. Escopos:', tokens.scope or '(nenhum)', flush=True)
    _avisar_escrita(tokens.scope)
    return 0


def _avisar_escrita(escopo):
    if any('write' in e for e in escopo.split()):
        print('AVISO: o app tem escopo de escrita (write). O Etiqueta só lê: no DevCenter, deixe as permissões '
              'em somente leitura e rode `ml_api.py autorizar` de novo.', file=sys.stderr, flush=True)


def conferir(sessao):
    resposta = sessao.get('/users/me')
    if not isinstance(resposta, dict):
        raise RespostaInvalida()
    escopo = ler_tokens(sessao.caminho).scope
    print('OK. Escopos:', escopo or '(nenhum)', flush=True)
    _avisar_escrita(escopo)
    return 0


# Nomes de campo que o `sondar` pode mostrar (só o nome, nunca o valor).
CAMPOS_SONDAR = ('price', 'original_price', 'sold_quantity', 'condition', 'status', 'rating_average',
                 'catalog_product_id', 'thumbnail')
# Chaves da estrutura de cada elemento do /items/bulk (F6), também só o nome.
FORMATO_BULK = ('code', 'status_code', 'body')
TERMO_SONDAR = 'perfume'
ATRIBUTOS_BULK = 'body.id,body.title,body.price,body.original_price,body.status,body.condition'


def _campos(o, profundidade=0, achados=None):
    achados = set() if achados is None else achados
    if profundidade > 5:
        return achados
    if isinstance(o, dict):
        for k, v in o.items():
            if k in CAMPOS_SONDAR:
                achados.add(k)
            _campos(v, profundidade + 1, achados)
    elif isinstance(o, list):
        for v in o[:50]:
            _campos(v, profundidade + 1, achados)
    return achados


def ids_do_banco(db=None, limite=3):
    """Até `limite` ids MLB do banco, em modo só leitura. Banco ausente ou ilegível: lista vazia."""
    db = db or DB
    try:
        uri = pathlib.Path(db).absolute().as_uri() + '?mode=ro'
        con = sqlite3.connect(uri, uri=True)
    except (sqlite3.Error, ValueError, OSError):
        return []
    try:
        con.execute('PRAGMA query_only = ON')
        linhas = con.execute("SELECT item_id FROM items WHERE loja = 'ml' AND item_id GLOB 'MLB[0-9]*' "
                             'ORDER BY rowid DESC LIMIT 50').fetchall()
    except sqlite3.Error:
        return []
    finally:
        con.close()
    ids = [i for (i,) in linhas if isinstance(i, str) and RE_MLB.fullmatch(i)]
    return ids[:limite]


def _sonda(sessao, rotulo, caminho, params=None, rotulo_caminho=None):
    """Uma chamada do sondar: imprime só status, código e nomes de campo. Devolve a resposta (ou None)."""
    nome = f'{rotulo} {rotulo_caminho or caminho}'
    try:
        resposta = sessao.get(caminho, params)
    except SemPermissao as e:
        print(f'{nome}: 403 {e.codigo or "PolicyAgent"} (falta permissão funcional no DevCenter)', flush=True)
        return None
    except ErroApi as e:
        print(f'{nome}: {e.status} {e.codigo or "(sem código)"}', flush=True)
        return None
    except RenovacaoInvalida:
        raise   # a renovação quebrou: seguir gastaria o refresh de novo; sai pedindo o autorizar
    except RespostaInvalida:
        print(f'{nome}: resposta fora do formato esperado', flush=True)
        return None
    campos = sorted(_campos(resposta))
    extra = ''
    if rotulo_caminho and rotulo_caminho.startswith('/items/bulk') and isinstance(resposta, list):
        chaves = sorted({k for el in resposta if isinstance(el, dict) for k in el if k in FORMATO_BULK})
        extra = f'; formato: lista de {len(resposta)}, chaves {", ".join(chaves) or "(nenhuma conhecida)"}'
    print(f'{nome}: 200{extra}; campos: {", ".join(campos) or "(nenhum da lista)"}', flush=True)
    return resposta


def sondar(sessao, db=None):
    """Testa os endpoints candidatos (F0 a F6 do plano) e imprime só status, códigos e nomes de campo."""
    _sonda(sessao, 'F0', '/users/me')
    _sonda(sessao, 'F1', '/sites/MLB/search', {'q': TERMO_SONDAR, 'limit': 1})
    produtos = _sonda(sessao, 'F3', '/products/search',
                      {'status': 'active', 'site_id': 'MLB', 'q': TERMO_SONDAR, 'limit': 1})
    produto = None
    if isinstance(produtos, dict) and isinstance(produtos.get('results'), list) and produtos['results']:
        primeiro = produtos['results'][0]
        pid = primeiro.get('id') if isinstance(primeiro, dict) else None
        produto = pid if isinstance(pid, str) and RE_PRODUTO.fullmatch(pid) else None
    if produto:
        _sonda(sessao, 'F3', f'/products/{produto}/items', rotulo_caminho='/products/{id}/items')
    else:
        print('F3 /products/{id}/items: pulado (o /products/search não trouxe id de produto)', flush=True)
    ids = ids_do_banco(db)
    if not ids:
        print('F2/F5/F6: pulados (sem id MLB no banco)', flush=True)
        return 0
    print(f'ids do banco: {", ".join(ids)}', flush=True)
    _sonda(sessao, 'F6', '/items/bulk', {'ids': ','.join(ids)}, rotulo_caminho='/items/bulk')
    _sonda(sessao, 'F6', '/items/bulk', {'ids': ','.join(ids), 'attributes': ATRIBUTOS_BULK},
           rotulo_caminho='/items/bulk (attributes)')
    _sonda(sessao, 'F2', f'/items/{ids[0]}', rotulo_caminho='/items/{id}')
    _sonda(sessao, 'F5', f'/reviews/item/{ids[0]}', rotulo_caminho='/reviews/item/{id}')
    return 0


def sair(caminho):
    """Apaga o arquivo local de tokens e as sobras de gravação interrompida (sob o lock, para não cruzar com uma
    renovação)."""
    try:
        os.lstat(caminho)
        existe = True
    except FileNotFoundError:
        existe = False
    if existe or _sobras(caminho):
        with travar(caminho):
            with contextlib.suppress(FileNotFoundError):
                os.unlink(caminho)
            _limpar_sobras(caminho)
    if existe:
        print('OK: tokens do Mercado Livre apagados deste computador.', flush=True)
    else:
        print('Não havia tokens do Mercado Livre neste computador.', flush=True)
    print('Para cortar o acesso também do lado do ML: na conta do Mercado Livre, em Segurança > Aplicativos '
          '(caminho não verificado), remova o app Etiqueta.', flush=True)
    return 0


def ler_argumentos(argv=None):
    p = argparse.ArgumentParser(description='API oficial do Mercado Livre (só leitura).')
    sub = p.add_subparsers(dest='comando', required=True)
    sub.add_parser('autorizar', help='autoriza o app Etiqueta e grava os tokens (pede ACHADINHOS_ML_SECRET)')
    sub.add_parser('conferir', help='confere os tokens com GET /users/me')
    sub.add_parser('sondar', help='testa os endpoints candidatos (F0 a F6) e mostra só status e nomes de campo')
    sub.add_parser('sair', help='apaga os tokens locais')
    return p.parse_args(argv)


def main(argv=None):
    args = ler_argumentos(argv)
    try:
        if args.comando == 'sair':
            return sair(TOKENS)
        if args.comando == 'autorizar':
            return autorizar(TOKENS, ler_segredo())
        sessao = sessao_do_ambiente()
        if args.comando == 'conferir':
            return conferir(sessao)
        return sondar(sessao)
    except ConfigFaltando as e:
        msg = str(e).replace('<comando>', args.comando)
        print(f'ERRO: {msg}', file=sys.stderr, flush=True)
        return e.saida
    except ErroML as e:
        print(f'{"PAROU" if e.saida == 3 else "ERRO"}: {e}', file=sys.stderr, flush=True)
        return e.saida
    except EOFError:
        print('ERRO: nenhum endereço colado. Nada foi gravado.', file=sys.stderr, flush=True)
        return 1
    except KeyboardInterrupt:
        print('Interrompido.', file=sys.stderr, flush=True)
        return 130
    except Exception as e:   # só o tipo: a mensagem de biblioteca pode trazer dados da requisição
        print(f'ERRO: {type(e).__name__}', file=sys.stderr, flush=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())
