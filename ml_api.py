#!/usr/bin/env python3
"""Cliente da API oficial do Mercado Livre (OAuth 2.0 com PKCE, só leitura), pelo terminal do dono.

Uso:  python3 ml_api.py autorizar   (pede o Secret no ambiente do comando)
      python3 ml_api.py conferir
      python3 ml_api.py sondar
      python3 ml_api.py sondar --catalogo [--amostra N] [--semente S]
      python3 ml_api.py sair

Plano: docs/produto/planos/api-oficial-ml.md, etapas 1 e 2 (CA2 a CA6, CA9); o `sondar --catalogo` é a etapa 1 de
docs/produto/planos/api-oficial-ml-catalogo.md (CA1, CA2), e o vínculo anúncio → produto de catálogo com as ofertas
por produto (`vincular`, `ofertas_do_produto`, `ler_vinculos`/`gravar_vinculos`) é a etapa 2 (CA3).

Este é o único módulo que fala com a API do ML. Ele não importa o servidor.py: nenhum código do servidor
toca o arquivo de tokens, e os tokens nunca vão para a tabela config, para rota, página ou log.

Ambiente:
  ACHADINHOS_ML_SECRET  Secret do app "Etiqueta" no DevCenter. Exigido só no `autorizar` e quando o
      access_token precisa ser renovado. Lido com pop (sai do ambiente do processo) e guardado num Segredo;
      vai só no corpo do POST /oauth/token ao host fixo. Num terminal só para isso, sem export:
        read -rs S; ACHADINHOS_ML_SECRET="$S" python3 ml_api.py autorizar; unset S
  ACHADINHOS_ML_TOKENS  arquivo dos tokens (padrão ml_tokens.json ao lado deste arquivo, no .gitignore).
  ACHADINHOS_DB  banco de onde o `sondar` lê 3 ids MLB (e o `sondar --catalogo`, a amostra), em modo só leitura
      (como no servidor.py).
  ACHADINHOS_ML_CATALOGO  arquivo de vínculos anúncio → produto de catálogo (padrão ml_catalogo.json ao lado deste
      arquivo, no .gitignore). Não é segredo.
Nenhuma variável troca o host da API, o Client ID ou o endereço de retorno.

Arquivo de tokens (JSON, até 4 KB, modo 0600, gravado por escrita atômica):
  {"v":1,"user_id":<int>,"access_token":"…","expira_em":<epoch int>,"refresh_token":"…","scope":"…",
   "renovado_em":"AAAA-MM-DDTHH:MM:SS"}
A leitura recusa symlink, arquivo que não é comum, dono diferente do usuário, permissão aberta e arquivo grande.
A renovação roda sob flock exclusivo em <arquivo>.lock, relendo o arquivo dentro do lock: o refresh_token é de
uso único, então dois comandos ao mesmo tempo não podem gastá-lo duas vezes.

Arquivo de vínculos (JSON ASCII, até 2 MB, modo 0600, gravado pela mesma escrita atômica dos tokens):
  {"v":1,"itens":{"MLB<n>":{"p":"MLB<m>"|null,"em":"AAAA-MM-DD","via":"bbw"|"lista"|null}}}
Só entra vínculo com prova (o anúncio é o buy_box_winner do produto ou está em /products/{id}/items); "p": null é o
vínculo negativo, tentado de novo depois de 7 dias. A leitura é tão estrita quanto a dos tokens.

Saída: 0 ok; 1 erro (API recusou, resposta fora do formato, endereço colado errado, autorização negada, rede);
2 configuração (sem tokens ou autorização vencida: rode `ml_api.py autorizar`; renovação fora do formato ou sem
refresh_token; renovação recusada com status sem tratamento próprio, como 5xx (RenovacaoFalhou); Secret ausente ou
recusado; permissão funcional que falta no DevCenter; arquivo de tokens inseguro; arquivo de vínculos recusado
(VinculosRecusados));
3 limite de requisições da API; 130 interrompido (Ctrl+C).
As mensagens são fixas: token, code, verifier e Secret nunca saem na tela nem em mensagem de exceção.
"""
import argparse, base64, collections, contextlib, datetime, decimal, fcntl, getpass, hashlib, hmac, http.client, json
import math, os, pathlib, random, re, secrets, sqlite3, stat, sys, time, unicodedata
import urllib.error, urllib.parse, urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
TOKENS = os.environ.get('ACHADINHOS_ML_TOKENS') or os.path.join(BASE, 'ml_tokens.json')
DB = os.environ.get('ACHADINHOS_DB') or os.path.join(BASE, 'achadinhos.db')
CATALOGO = os.environ.get('ACHADINHOS_ML_CATALOGO') or os.path.join(BASE, 'ml_catalogo.json')

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
                'sido gasto). Os tokens não mudaram: rode `ml_api.py autorizar`')


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


class RenovacaoFalhou(ErroApi):
    """A renovação (POST /oauth/token) foi recusada com um status sem tratamento próprio (5xx, por exemplo); o
    Sessao.renovar a levanta no lugar do ErroApi. O _medir não a captura: ela para qualquer laço (sonda do
    catálogo, vincular, ofertas_do_produto), senão cada chamada tentaria renovar de novo (um POST com o Secret por
    item) e o erro sairia como do catálogo. É subclasse de ErroApi (status e código filtrados), então quem captura
    ErroApi precisa de `except RenovacaoFalhou: raise` antes (o _medir, o _sonda do F0 a F6 e a fonte `ml` do
    atualizar_precos.py têm)."""
    saida = 2
    mensagem = ('a renovação do acesso ao Mercado Livre falhou. Os tokens não mudaram: espere alguns minutos e '
                'rode de novo; se repetir, rode `ml_api.py autorizar`')

    def __init__(self, status=None, codigo=None):
        super().__init__(status, codigo)
        ok = isinstance(status, int) and not isinstance(status, bool) and 100 <= status <= 599
        self.args = (self.mensagem + (f' [HTTP {status}]' if ok else ''),)


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


def _ler_privado(caminho, teto, recusar):
    """Bytes de um arquivo comum do próprio usuário, sem permissão para grupo e outros, com até `teto` bytes; None se
    o arquivo não existe. Symlink, FIFO e outros tipos, dono diferente, permissão aberta, arquivo grande e erro de
    leitura levantam recusar(motivo), com motivo de texto fixo. Usada pelos tokens e pelos vínculos do catálogo."""
    try:
        info = os.lstat(caminho)
    except FileNotFoundError:
        return None
    except OSError:
        raise recusar('não consegui ler o arquivo') from None
    if stat.S_ISLNK(info.st_mode):
        raise recusar('é um link simbólico')
    try:
        # O_NOFOLLOW fecha a janela entre o lstat e o open; O_NONBLOCK: um FIFO não trava
        fd = os.open(caminho, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except FileNotFoundError:
        return None
    except OSError:
        raise recusar('não consegui abrir o arquivo') from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise recusar('não é um arquivo comum')
        if info.st_uid != os.getuid():
            raise recusar('o dono do arquivo não é o seu usuário')
        if info.st_mode & 0o077:
            raise recusar('permissão aberta para grupo ou outros; use chmod 600')
        if info.st_size > teto:
            raise recusar(f'passa de {teto} bytes')
        partes, lidos = [], 0
        while lidos <= teto:
            parte = os.read(fd, teto + 1 - lidos)
            if not parte:
                break
            partes.append(parte)
            lidos += len(parte)
    except OSError:
        raise recusar('não consegui ler o arquivo') from None
    finally:
        os.close(fd)
    if lidos > teto:
        raise recusar(f'passa de {teto} bytes')
    return b''.join(partes)


def ler_tokens(caminho):
    """Tokens do arquivo, com leitura estrita. Sem arquivo: RefazerAutorizacao. Inseguro ou estranho: TokensRecusados."""
    bruto = _ler_privado(caminho, MAX_ARQUIVO_TOKENS, TokensRecusados)
    if bruto is None:
        raise RefazerAutorizacao()
    try:
        tokens = _tokens_validos(json.loads(bruto.decode('ascii')))
    except (ValueError, RecursionError):
        tokens = None
    if tokens is None:
        raise TokensRecusados('conteúdo fora do formato')
    return tokens


def gravar_tokens(caminho, tokens):
    """Grava os tokens por escrita atômica (gravar_atomico). Quem chama segura o lock (travar)."""
    dados = tokens.como_json().encode('ascii')
    if len(dados) > MAX_ARQUIVO_TOKENS:
        raise RespostaInvalida()
    gravar_atomico(caminho, dados, MAX_ARQUIVO_TOKENS)


def gravar_atomico(caminho, dados, teto):
    """Grava `dados` (bytes, até `teto`) por escrita atômica: arquivo temporário .<nome>.<16 hex>.tmp 0600
    (O_EXCL|O_NOFOLLOW) na mesma pasta, fsync, os.replace e fsync da pasta. Um symlink no caminho é trocado pelo
    arquivo, nunca seguido. Se algo falha antes do replace, o temporário é apagado e o arquivo antigo fica."""
    if not isinstance(dados, bytes) or len(dados) > teto:
        raise ValueError('dados fora do teto da gravação')
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
        qualquer outra chamada. Recusa sem tratamento próprio (5xx, por exemplo) sai como RenovacaoFalhou."""
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
            except ErroApi as e:
                # status sem tratamento próprio (invalid_grant e invalid_client já saíram como RefazerAutorizacao e
                # CredencialInvalida): para quem chama, não é um status do recurso pedido
                raise RenovacaoFalhou(e.status, e.codigo) from None
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
    except RenovacaoFalhou:
        raise   # a renovação foi recusada: seguir mandaria um POST com o Secret por endpoint; sai 2
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


# ---------- sondar --catalogo (docs/produto/planos/api-oficial-ml-catalogo.md, etapa 1: F7 a F15) ----------
AMOSTRA_PADRAO = 50
AMOSTRA_MAX = 100
SEMENTE_PADRAO = 20261105
TETO_CHAMADAS = 500
PAUSA_MIN, PAUSA_MAX = 0.3, 0.8       # s entre duas chamadas da sonda
CANDIDATOS_K = 3                      # primeiros resultados da busca por título
FILHOS_POR_PAI = 3                    # filhos de um produto pai que viram candidatos
PAGINAS_LISTA = 3                     # páginas de /products/{id}/items procurando o item
PALAVRAS_CONSULTA = 12
MAX_CONSULTA = 200                    # caracteres do q depois da normalização
LIMIT_F7 = 50                         # teste único do teto do `limit` da busca
TERMOS_F12 = 5
PRODUTOS_F12 = 5                      # produtos lidos por termo no F12
JANELA_F11 = 48 * 3600                # s: preço do banco "recente" no F11
FUTURO_TOLERADO = 300                 # s: preco_em até 5 min no futuro ainda conta como recente
MAX_IDS_LINHA = 5
MAX_BUSCAS = 1024 * 1024              # bytes do buscas.json


def _reserva(termos):
    """Chamadas guardadas para o fim (F12: termos e produtos; F13, F14 e F15: uma cada): o laço da amostra para
    antes delas."""
    return termos * (1 + PRODUTOS_F12) + 3


RESERVA_FINAIS = _reserva(TERMOS_F12)
BUSCAS = os.path.join(BASE, 'buscas.json')
MSG_AMOSTRA = f'--amostra vai de 1 a {AMOSTRA_MAX}'
MSG_SO_CATALOGO = '--amostra e --semente só valem com --catalogo'
# nomes de campo que a sonda pode mostrar (só o nome, nunca o valor)
CAMPOS_BBW = ('item_id', 'price', 'original_price', 'currency_id', 'condition', 'shipping', 'seller_id',
              'listing_type_id', 'category_id')
CAMPOS_LISTA = ('item_id', 'price', 'original_price', 'currency_id', 'condition', 'shipping', 'seller_id',
                'listing_type_id', 'official_store_id', 'category_id')
CAMPOS_PAGING = ('total', 'offset', 'limit')
_CENTAVO = decimal.Decimal('0.01')

# sem re.A, como no servidor.py (porte fiel)
_PRECO_MILHAR = re.compile(r'\d{1,3}(?:\.\d{3})+')
_PRECO_BR = re.compile(r'\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:,\d+)?|\d+\.\d{1,2}')


def ler_preco(texto):
    """Porte fiel do servidor.ler_preco (este módulo não importa o servidor; o teste amarra os dois):
    "R$ 1.299,90" → Decimal('1299.90'); None se vazio, ilegível ou <= 0."""
    if texto is None or isinstance(texto, bool):
        return None
    t = re.sub(r'R\$|\s', '', str(texto))
    if not _PRECO_BR.fullmatch(t):
        return None
    if ',' in t:
        t = t.replace('.', '').replace(',', '.')
    elif _PRECO_MILHAR.fullmatch(t):
        t = t.replace('.', '')
    v = decimal.Decimal(t)
    return v if v > 0 else None


def consulta_do_titulo(titulo):
    """q da busca de produtos a partir do título: sem acento (NFKD), sem pontuação, minúsculas, até 12 palavras e
    até MAX_CONSULTA caracteres."""
    if not isinstance(titulo, str):
        return ''
    q = ' '.join(re.sub(r'[^0-9a-z]+', ' ', sem_acento(titulo)).split()[:PALAVRAS_CONSULTA])
    return q[:MAX_CONSULTA].rstrip()


def _pid(v):
    """id de produto (ou de categoria) da resposta, só se casar com RE_PRODUTO; senão None."""
    return v if isinstance(v, str) and RE_PRODUTO.fullmatch(v) else None


def _eh_pai(p):
    filhos = p.get('children_ids')
    return isinstance(filhos, list) and len(filhos) > 0


def _candidatos(sessao, q, k=CANDIDATOS_K):
    """(pids, descartados). Um resultado com children_ids não vazio é pai e vira até FILHOS_POR_PAI filhos; sem
    filhos, vale o próprio id se o status for active ou faltar (a busca já pede status=active). Descartado: o
    resultado entre os k primeiros que não rende id válido (não é objeto, status de inativo, id fora do formato)."""
    resposta = sessao.get('/products/search', {'site_id': 'MLB', 'status': 'active', 'q': q, 'limit': k})
    resultados = resposta.get('results') if isinstance(resposta, dict) else None
    if not isinstance(resultados, list):
        raise RespostaInvalida()
    pids, descartados = [], 0
    for r in resultados[:k]:
        if not isinstance(r, dict):
            novos = []
        elif _eh_pai(r):
            novos = [p for p in (_pid(f) for f in r['children_ids']) if p][:FILHOS_POR_PAI]
        elif r.get('status', 'active') == 'active':
            novos = [p for p in (_pid(r.get('id')),) if p]
        else:
            novos = []
        if not novos:
            descartados += 1
        pids.extend(p for p in novos if p not in pids)
    return pids, descartados


def candidatos(sessao, q, k=CANDIDATOS_K):
    """ids de produto candidatos para a consulta: os k primeiros resultados da busca de produtos (pai vira até
    FILHOS_POR_PAI filhos; ver _candidatos). Só ids que casam com RE_PRODUTO, sem repetição. Candidato não é
    vínculo: a prova é o item no produto."""
    return _candidatos(sessao, q, k)[0]


def _get_dict(sessao, caminho, params=None):
    resposta = sessao.get(caminho, params)
    if not isinstance(resposta, dict):
        raise RespostaInvalida()
    return resposta


def produto(sessao, pid):
    """GET /products/{pid}. O pid passa por RE_PRODUTO antes de entrar no caminho."""
    if not _pid(pid):
        raise ValueError('id de produto inválido')
    return _get_dict(sessao, f'/products/{pid}')


def itens_do_banco(db=None):
    """Itens do ML com id MLB (item_id, titulo, cat, preco, preco_em), em ordem de id, com o banco em modo só
    leitura (mode=ro e query_only). Banco ausente, ilegível ou sem as colunas: lista vazia."""
    db = db or DB
    try:
        uri = pathlib.Path(db).absolute().as_uri() + '?mode=ro'
        con = sqlite3.connect(uri, uri=True)
    except (sqlite3.Error, ValueError, OSError):
        return []
    try:
        con.execute('PRAGMA query_only = ON')
        linhas = con.execute("SELECT item_id, titulo, cat, preco, preco_em FROM items WHERE loja = 'ml' "
                             "AND item_id GLOB 'MLB[0-9]*' ORDER BY id").fetchall()
    except sqlite3.Error:
        return []
    finally:
        con.close()
    def texto(v):
        return v if isinstance(v, str) else ''
    return [{'item_id': i, 'titulo': texto(t), 'cat': texto(c), 'preco': texto(p), 'preco_em': texto(e)}
            for (i, t, c, p, e) in linhas if isinstance(i, str) and RE_MLB.fullmatch(i)]


def _abas_e_termos(caminho=None):
    """(abas, termos) do buscas.json ({aba: [termos]}). Arquivo ausente ou fora do formato: (set(), [])."""
    try:
        with open(caminho or BUSCAS, 'rb') as f:
            bruto = f.read(MAX_BUSCAS + 1)
        dados = json.loads(bruto) if len(bruto) <= MAX_BUSCAS else None
    except (OSError, ValueError, RecursionError):
        return set(), []
    if not isinstance(dados, dict):
        return set(), []
    abas, termos = set(), []
    for aba, lista in dados.items():
        if isinstance(aba, str) and isinstance(lista, list):
            abas.add(aba)
            termos.extend(t for t in lista if isinstance(t, str) and t.strip() and t not in termos)
    return abas, termos


class _TetoAtingido(Exception):
    """A sonda chegou ao teto de chamadas (uso interno)."""


class _Chamadas:
    """A Sessao vista pela sonda: conta as chamadas, para no teto e faz a pausa de PAUSA_MIN a PAUSA_MAX s entre
    duas delas. `limite` começa abaixo do teto (reserva para F12 a F15) e sobe para o teto no fim.

    `contado` é o _OpenerContado posto na Sessao: diz se a chamada chegou a sair como GET (só então conta em
    `feitas`). A renovação recusada já sai da Sessao como RenovacaoFalhou, nunca como status do catálogo."""

    def __init__(self, sessao, teto, dormir, aleatorio, contado):
        self.sessao, self.teto, self.dormir, self.aleatorio = sessao, teto, dormir, aleatorio
        self.contado = contado
        self.limite = teto   # nunca passa do teto
        self.feitas = 0

    def get(self, caminho, params=None):
        if self.feitas >= self.limite:
            raise _TetoAtingido()
        if self.feitas:
            self.dormir(PAUSA_MIN + (PAUSA_MAX - PAUSA_MIN) * self.aleatorio())
        antes = self.contado.gets
        try:
            return self.sessao.get(caminho, params)
        finally:
            if self.contado.gets > antes:
                self.feitas += 1


class _OpenerContado:
    """Envolve o opener da Sessao para contar os GETs e as respostas 429 (o backoff fica na Sessao)."""

    def __init__(self, interno):
        self.interno = interno
        self.n429 = self.gets = 0

    def open(self, req, timeout=None):
        if req.get_method() == 'GET':
            self.gets += 1
        try:
            return self.interno.open(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                self.n429 += 1
            raise


TetoAtingido = _TetoAtingido   # nome público para quem usa a vista com teto fora da sonda (atualizar_precos.py ml)


@contextlib.contextmanager
def com_teto(sessao, teto, dormir=None, aleatorio=None):
    """A Sessao vista com teto e pausa, a mesma _Chamadas da sonda: até `teto` GETs que chegaram a sair (o próximo
    levanta TetoAtingido) e pausa de PAUSA_MIN a PAUSA_MAX s entre dois deles. A vista vai para vincular e
    ofertas_do_produto no lugar da Sessao. O opener da Sessao volta ao original na saída, com ou sem erro."""
    original = sessao.opener
    contado = _OpenerContado(sessao._opener())
    chamadas = _Chamadas(sessao, teto, dormir or sessao.dormir, aleatorio or sessao.aleatorio, contado)
    sessao.opener = contado
    try:
        yield chamadas
    finally:
        sessao.opener = original


def _medir(contagem, fazer):
    """(resposta, erro) de fazer(). Conta o resultado em `contagem` ('200', '<status> <código>', '403 <código>'
    ou 'fora do formato'). Limite, rede, teto e erros de autorização sobem e param a sonda: o 401 que sobra
    depois da única renovação da Sessao vira RefazerAutorizacao (saída 2), não um status do catálogo, e a
    renovação recusada (RenovacaoFalhou, subclasse de ErroApi) sobe como está."""
    try:
        resposta = fazer()
    except SemPermissao as e:
        contagem[f'403 {e.codigo or "PolicyAgent"}'] += 1
        return None, e
    except RenovacaoFalhou:
        raise
    except ErroApi as e:
        if e.status == 401:
            raise RefazerAutorizacao() from None
        contagem[f'{e.status} {e.codigo}' if e.codigo else str(e.status)] += 1
        return None, e
    except RenovacaoInvalida:
        raise
    except RespostaInvalida as e:
        contagem['fora do formato'] += 1
        return None, e
    contagem['200'] += 1
    return resposta, None


def _status(contagem):
    if not contagem:
        return 'nenhuma chamada'
    return ', '.join(f'{k}: {n}' for k, n in sorted(contagem.items()))


def _so_status(contagem):
    """Uma chamada só: o status (e o código filtrado) dela."""
    if not contagem:
        return 'nenhuma chamada'
    chave = next(iter(contagem))
    return chave + (' (falta permissão funcional no DevCenter)' if chave.startswith(('403 PA_', '403 PolicyAgent'))
                    else '')


def _ids(lista):
    return ', '.join(lista[:MAX_IDS_LINHA]) or '(nenhum)'


def _nomes(conjunto):
    return ', '.join(sorted(conjunto)) or '(nenhum da lista)'


def _faixa_de_preco(preco_api, preco_banco):
    """'igual', 'ate2' ou 'acima' comparando em centavos (o banco guarda o preço já arredondado como no console)."""
    api = _arredondar_js(preco_api * 100)
    banco = int((preco_banco * 100).to_integral_value(rounding=decimal.ROUND_HALF_UP))
    if api == banco:
        return 'igual'
    return 'ate2' if abs(api - banco) * 100 <= 2 * banco else 'acima'


def _recente(preco_em, agora):
    if not isinstance(preco_em, str) or not RE_DATA_HORA.fullmatch(preco_em):
        return False
    try:
        quando = time.mktime(time.strptime(preco_em, '%Y-%m-%dT%H:%M:%S'))
    except (ValueError, OverflowError):
        return False
    return -FUTURO_TOLERADO <= agora - quando <= JANELA_F11


class _Medidas:
    """Contagens da sonda. Só números, nomes de campo, status filtrados, nomes de aba e ids MLB do banco."""

    def __init__(self):
        self.busca, self.produto, self.itens = (collections.Counter() for _ in range(3))
        self.limit50 = None                   # (contagem, resultados, paging.limit)
        self.buscados = self.sem_consulta = self.com_candidato = self.n_candidatos = self.descartados = 0
        self.n404 = collections.Counter()     # 404 do /items pelo estado do produto já lido (R2)
        self.lidos = self.bbw_objeto = self.bbw_nulo = self.bbw_ausente = self.frete = 0
        self.foto_id = self.com_filhos = self.ativos = self.outros = self.com_categoria = 0
        self.campos_bbw, self.campos_lista, self.campos_paging = set(), set(), set()
        self.provados = {'bbw': 0, 'lista': 0}
        self.exemplos, self.acima_ids = [], []
        self.por_aba = {}                     # aba → [provados, na amostra]
        self.faixas = {True: collections.Counter(), False: collections.Counter()}   # recente? → faixa → n
        self.sem_preco_banco = self.sem_preco_api = 0
        self.categoria = self.pid_exemplo = None
        self.bloqueado = set()                # 'produto', 'itens': 403 PolicyAgent, não chama mais no laço
        self.negado = None                    # o SemPermissao visto no produto ou na lista (vincular: para)
        self.falha = None                     # 1º erro que não é 404 nem 403 no produto ou na lista: prova inconclusiva
        self.parou = None
        self.vistos = 0

    def ler_produto(self, p):
        self.lidos += 1
        if 'buy_box_winner' not in p:
            self.bbw_ausente += 1
        bbw = p.get('buy_box_winner')
        if isinstance(bbw, dict):
            self.bbw_objeto += 1
            self.campos_bbw.update(k for k in bbw if k in CAMPOS_BBW)
            if isinstance(bbw.get('shipping'), dict) and 'free_shipping' in bbw['shipping']:
                self.frete += 1
        elif bbw is None and 'buy_box_winner' in p:
            self.bbw_nulo += 1
        fotos = p.get('pictures')
        if isinstance(fotos, list) and any(isinstance(f, dict) and isinstance(f.get('id'), str) for f in fotos):
            self.foto_id += 1
        if isinstance(p.get('children_ids'), list) and p['children_ids']:
            self.com_filhos += 1
        if p.get('status') == 'active':
            self.ativos += 1
        else:
            self.outros += 1
        cat = _categoria_do_produto(p)
        if cat:
            self.com_categoria += 1
            self.categoria = self.categoria or cat


def _categoria_do_produto(p):
    bbw = p.get('buy_box_winner')
    return _pid(p.get('category_id')) or (_pid(bbw.get('category_id')) if isinstance(bbw, dict) else None)


def _estado_do_produto(p):
    """Faixa do 404 do /items pelo produto já lido: p é o dict de /products/{pid} ou None (não lido)."""
    if not isinstance(p, dict):
        return 'sem produto'
    if 'buy_box_winner' not in p:
        return 'bbw ausente'
    return 'bbw de outro anúncio' if isinstance(p['buy_box_winner'], dict) else 'bbw nulo'


def _anotar_erro(m, erro):
    """Guarda em `m` o erro de uma leitura de produto ou de lista: 404 é resposta (sem produto, sem oferta) e não
    entra; 403 PolicyAgent vai para `negado`; o resto (5xx, 4xx, fora do formato) torna a prova inconclusiva."""
    if isinstance(erro, SemPermissao):
        m.negado = erro
    elif erro is not None and not (isinstance(erro, ErroApi) and erro.status == 404):
        m.falha = m.falha or erro


def _linhas_na_lista(chamadas, m, pid, ids, p=None, paginas=PAGINAS_LISTA):
    """{item_id: linha} dos `ids` achados em /products/{pid}/items (até `paginas` páginas; para quando acha todos).
    Só vale o item_id da linha que casa com RE_MLB e está em `ids`; repetido, vale a 1ª linha. 404 só conta,
    separado pelo estado do produto `p` já lido (None: não lido). Página vazia é o fim da lista; `results` que não é
    lista e página sem `paging.total` inteiro são resposta fora do formato (m.falha)."""
    achadas, offset = {}, 0
    if not ids:
        return achadas
    for _ in range(paginas):
        params = {'offset': offset} if offset else None
        r, erro = _medir(m.itens, lambda: _get_dict(chamadas, f'/products/{pid}/items', params))
        _anotar_erro(m, erro)
        if isinstance(erro, SemPermissao):
            m.bloqueado.add('itens')
        elif isinstance(erro, ErroApi) and erro.status == 404:
            m.n404[_estado_do_produto(p)] += 1
        if r is None:
            return achadas
        resultados = r.get('results')
        paging = r.get('paging')
        if isinstance(paging, dict):
            m.campos_paging.update(k for k in paging if k in CAMPOS_PAGING)
        if not isinstance(resultados, list):
            m.falha = m.falha or RespostaInvalida()
            return achadas
        for linha in resultados:
            if not isinstance(linha, dict):
                continue
            m.campos_lista.update(k for k in linha if k in CAMPOS_LISTA)
            i = linha.get('item_id')
            if isinstance(i, str) and RE_MLB.fullmatch(i) and i in ids and i not in achadas:
                achadas[i] = linha
                if len(achadas) == len(ids):
                    return achadas
        if not resultados:
            return achadas
        total = paging.get('total') if isinstance(paging, dict) else None
        if not _inteiro(total):
            # sem paging.total inteiro não dá para saber se há outra página: fora do formato, não fim da lista
            m.falha = m.falha or RespostaInvalida()
            return achadas
        if offset + len(resultados) >= total:   # total menor que o já lido também é fim
            return achadas
        offset += len(resultados)
    return achadas


def _oferta_na_lista(chamadas, m, pid, item_id, p=None):
    """Linha do item_id em /products/{pid}/items (até PAGINAS_LISTA páginas), ou None (ver _linhas_na_lista)."""
    return _linhas_na_lista(chamadas, m, pid, {item_id}, p).get(item_id)


def _provar(chamadas, m, item_id, pids):
    """('bbw'|'lista', oferta, pid) se o item_id está num dos candidatos (é o buy_box_winner do produto ou está na
    lista dele), senão (None, None, None). O buy_box_winner de outro anúncio nunca prova nada."""
    for pid in pids:
        p = None
        if 'produto' not in m.bloqueado:
            p, erro = _medir(m.produto, lambda: produto(chamadas, pid))
            _anotar_erro(m, erro)
            if isinstance(erro, SemPermissao):
                m.bloqueado.add('produto')
            if p is not None:
                m.ler_produto(p)
                bbw = p.get('buy_box_winner')
                if isinstance(bbw, dict) and bbw.get('item_id') == item_id:
                    return 'bbw', bbw, pid
        if 'itens' not in m.bloqueado:
            linha = _oferta_na_lista(chamadas, m, pid, item_id, p)
            if linha is not None:
                return 'lista', linha, pid
    return None, None, None


def _comparar_preco(m, item, oferta, agora):
    banco = ler_preco(item['preco'])
    if banco is None:
        m.sem_preco_banco += 1
        return
    o = _oferta(item['item_id'], oferta, None)
    if not oferta_valida(o):
        m.sem_preco_api += 1
        return
    faixa = _faixa_de_preco(o.preco, banco)
    m.faixas[_recente(item['preco_em'], agora)][faixa] += 1
    if faixa == 'acima':
        m.acima_ids.append(item['item_id'])


def _somar_item(m, item, aba, q, pids, descartados, via, oferta, agora):
    """Soma em `m` um item que terminou a prova. Item cortado no meio (teto, Limite, erro) nunca chega aqui:
    assim F7, F10 e F11 só contam itens inteiros."""
    conta = m.por_aba.setdefault(aba, [0, 0])
    conta[1] += 1
    m.vistos += 1
    if not q:
        m.sem_consulta += 1
        return
    m.buscados += 1
    m.descartados += descartados
    if not pids:
        return
    m.com_candidato += 1
    m.n_candidatos += len(pids)
    if via:
        m.provados[via] += 1
        conta[0] += 1
        m.exemplos.append(item['item_id'])
        _comparar_preco(m, item, oferta, agora)


def _laco_da_amostra(chamadas, m, amostra, abas, agora):
    """F7 a F11 para cada item da amostra. Para no teto (com a reserva) ou no 403 da busca. As contagens por
    endpoint (F8, F9) valem por chamada; as do item (F7, F10, F11) só entram quando ele termina."""
    if amostra:
        q = consulta_do_titulo(amostra[0]['titulo']) or 'celular'
        contagem = collections.Counter()
        r, _ = _medir(contagem, lambda: _get_dict(chamadas, '/products/search', {
            'site_id': 'MLB', 'status': 'active', 'q': q, 'limit': LIMIT_F7}))
        resultados = r.get('results') if r else None
        paging = r.get('paging') if r else None
        m.limit50 = (contagem, len(resultados) if isinstance(resultados, list) else None,
                     paging.get('limit') if isinstance(paging, dict) and _inteiro(paging.get('limit')) else None)
    for item in amostra:
        aba = item['cat'] if item['cat'] in abas else '(outra aba)'
        q = consulta_do_titulo(item['titulo'])
        pids, descartados, via, oferta = [], 0, None, None
        if q:
            r, erro = _medir(m.busca, lambda: _candidatos(chamadas, q))
            if isinstance(erro, SemPermissao):
                m.parou = '403 na busca de produtos'
                return
            pids, descartados = r if r is not None else ([], 0)
            if pids:
                m.pid_exemplo = m.pid_exemplo or pids[0]   # id para o F15, não é contagem
                via, oferta, _ = _provar(chamadas, m, item['item_id'], pids)
        _somar_item(m, item, aba, q, pids, descartados, via, oferta, agora)


def _imprimir_amostra(m, n, parcial):
    if parcial:
        print(f'Parcial ({m.parou or "parou"}): itens vistos {m.vistos} de {n}', flush=True)
    if m.limit50:
        contagem, resultados, limite = m.limit50
        extra = '' if resultados is None else f'; resultados: {resultados}'
        extra += '' if limite is None else f'; paging.limit: {limite}'
        print(f'F7 /products/search limit={LIMIT_F7}: {_so_status(contagem)}{extra}', flush=True)
    media = f'{m.n_candidatos / m.com_candidato:.1f}' if m.com_candidato else '0'
    print(f'F7 /products/search (título): {_status(m.busca)}; itens com candidato: {m.com_candidato} de '
          f'{m.buscados}; média de candidatos: {media}; sem título utilizável: {m.sem_consulta}; '
          f'descartados: {m.descartados}', flush=True)
    print(f'F8 /products/{{id}}: {_status(m.produto)}; lidos: {m.lidos}; buy_box_winner: objeto {m.bbw_objeto}, '
          f'nulo {m.bbw_nulo}, ausente {m.bbw_ausente}; campos do buy_box_winner: {_nomes(m.campos_bbw)}; '
          f'shipping.free_shipping: {m.frete}; pictures[].id: {m.foto_id}; children_ids: {m.com_filhos}; '
          f'status active: {m.ativos}, outro: {m.outros}; category_id: {m.com_categoria}', flush=True)
    n404 = sum(v for k, v in m.itens.items() if k.split(' ')[0] == '404')
    faixas = ', '.join(f'{k} {m.n404[k]}' for k in ('bbw nulo', 'bbw de outro anúncio', 'bbw ausente',
                                                     'sem produto'))
    print(f'F9 /products/{{id}}/items: {_status(m.itens)}; 404: {n404} ({faixas}); campos em results[]: '
          f'{_nomes(m.campos_lista)}; paging: {_nomes(m.campos_paging)}', flush=True)
    total = m.provados['bbw'] + m.provados['lista']
    pct = f' ({100 * total / m.vistos:.0f}%)' if m.vistos else ''
    print(f'F10 provados: {total} de {m.vistos}{pct} (bbw: {m.provados["bbw"]}, lista: {m.provados["lista"]})',
          flush=True)
    print(f'F10 exemplos: {_ids(m.exemplos)}', flush=True)
    for aba in sorted(m.por_aba):
        provados, vistos = m.por_aba[aba]
        print(f'F10 aba {aba}: {provados} de {vistos}', flush=True)
    for recente, rotulo in ((True, 'até 48 h'), (False, 'mais antigo ou sem data')):
        f = m.faixas[recente]
        print(f'F11 preço do banco {rotulo}: igual {f["igual"]}, até 2% {f["ate2"]}, acima de 2% {f["acima"]}',
              flush=True)
    print(f'F11 sem comparação: sem preço legível no banco {m.sem_preco_banco}, sem preço BRL na API '
          f'{m.sem_preco_api}', flush=True)
    print(f'F11 acima de 2%: {_ids(m.acima_ids)}', flush=True)


def _f12(chamadas, m, termos):
    """Busca por termos do buscas.json: produtos ativos, com buy_box_winner e condition new (só contagens)."""
    if not termos:
        print('F12 /products/search (termos): pulado (buscas.json ausente ou fora do formato)', flush=True)
        return
    busca, prod = collections.Counter(), collections.Counter()
    lidos = ativos = com_bbw = novos = 0
    parcial = ''
    try:
        for termo in termos:
            pids, erro = _medir(busca, lambda: candidatos(chamadas, termo))
            if isinstance(erro, SemPermissao):
                break
            for pid in (pids or [])[:PRODUTOS_F12]:
                p, erro = _medir(prod, lambda: produto(chamadas, pid))
                if p is None:
                    continue
                lidos += 1
                ativos += p.get('status') == 'active'
                bbw = p.get('buy_box_winner')
                if isinstance(bbw, dict):
                    com_bbw += 1
                    novos += bbw.get('condition') == 'new'
                m.categoria = m.categoria or _categoria_do_produto(p)
                m.pid_exemplo = m.pid_exemplo or pid
    except _TetoAtingido:
        parcial = ' (parcial: teto de chamadas)'
    print(f'F12 /products/search ({len(termos)} termos): {_status(busca)}{parcial}', flush=True)
    print(f'F12 /products/{{id}}: {_status(prod)}; lidos: {lidos}; active: {ativos}; com buy_box_winner: '
          f'{com_bbw}; buy_box_winner new: {novos}', flush=True)


def _uma(chamadas, rotulo, caminho, params=None):
    contagem = collections.Counter()
    try:
        _medir(contagem, lambda: _get_dict(chamadas, caminho, params))
    except _TetoAtingido:
        print(f'{rotulo}: pulado (teto de chamadas)', flush=True)
        return
    print(f'{rotulo}: {_so_status(contagem)}', flush=True)


def sondar_catalogo(sessao, db=None, amostra=AMOSTRA_PADRAO, semente=SEMENTE_PADRAO, termos=TERMOS_F12,
                    teto=TETO_CHAMADAS, dormir=None, aleatorio=None, agora=None, buscas=None):
    """Mede F7 a F15 do plano api-oficial-ml-catalogo com uma amostra do banco (só leitura; nenhum arquivo é
    gravado pela sonda). Imprime só status, códigos filtrados, nomes de campo, contagens, nomes de aba (do
    buscas.json) e até 5 ids MLB do banco por linha: título, preço e token nunca saem.

    Para em `teto` chamadas (o laço da amostra guarda _reserva(termos sorteados) para F12 a F15). Limite (429),
    rede e erros de autorização (inclusive o 401 que sobra e a renovação recusada) imprimem o parcial e sobem
    (saídas 3, 1 e 2 no main). Os tokens são conferidos antes do cabeçalho."""
    if not isinstance(amostra, int) or not 1 <= amostra <= AMOSTRA_MAX:
        raise ValueError(MSG_AMOSTRA)
    # tokens antes de tudo: sem arquivo, sem Secret ou com a renovação recusada, a sonda para aqui, sem cabeçalho
    # nem parcial vazio (R5); um 5xx da renovação sai da Sessao como RenovacaoFalhou e não se repete (S1)
    sessao.token()
    inicio = time.monotonic()
    agora = time.time() if agora is None else agora
    abas, todos_termos = _abas_e_termos(buscas)
    itens = itens_do_banco(db)
    escolhidos = random.Random(semente).sample(itens, min(amostra, len(itens)))
    termos_f12 = random.Random(semente).sample(todos_termos, min(termos, len(todos_termos)))
    reserva = _reserva(len(termos_f12))
    m = _Medidas()
    impresso = False
    # a vista com teto e pausa (a mesma do atualizar_precos.py ml); o opener original volta na saída do with
    with com_teto(sessao, teto, dormir, aleatorio) as chamadas:
        print(f'Catálogo: amostra de {len(escolhidos)} de {len(itens)} itens do ML no banco (semente {semente}); '
              f'teto de {teto} chamadas.', flush=True)
        try:
            if not escolhidos:
                print('F7-F11: pulados (sem item do ML no banco)', flush=True)
            else:
                chamadas.limite = max(teto - reserva, 0)
                try:
                    _laco_da_amostra(chamadas, m, escolhidos, abas, agora)
                except _TetoAtingido:
                    m.parou = f'teto de {teto} chamadas, com {reserva} guardadas para F12 a F15'
                chamadas.limite = teto
                _imprimir_amostra(m, len(escolhidos), parcial=m.parou is not None)
                impresso = True
            _f12(chamadas, m, termos_f12)
            if escolhidos:
                _uma(chamadas, 'F13 /reviews/item/{id}', f'/reviews/item/{escolhidos[0]["item_id"]}')
            else:
                print('F13 /reviews/item/{id}: pulado (sem item do ML no banco)', flush=True)
            if m.categoria:
                _uma(chamadas, 'F14 /highlights/MLB/category/{cat}', f'/highlights/MLB/category/{m.categoria}')
            else:
                print('F14 /highlights/MLB/category/{cat}: pulado (sem category_id)', flush=True)
            if m.pid_exemplo:
                _uma(chamadas, 'F15 /sites/MLB/search?product_id', '/sites/MLB/search',
                     {'product_id': m.pid_exemplo, 'limit': 1})
            else:
                print('F15 /sites/MLB/search?product_id: pulado (sem id de produto)', flush=True)
        except ErroML as e:
            if escolhidos and not impresso:
                m.parou = m.parou or ('limite de requisições (429)' if isinstance(e, Limite) else 'erro')
                _imprimir_amostra(m, len(escolhidos), parcial=True)
            raise
        finally:
            print(f'chamadas: {chamadas.feitas}, 429: {chamadas.contado.n429}, tempo: {time.monotonic() - inicio:.1f}s',
                  flush=True)
    return 0


# ---------- vínculo anúncio → produto e ofertas (plano api-oficial-ml-catalogo, etapa 2: CA3) ----------
MAX_ARQUIVO_VINCULOS = 2 * 1024 * 1024   # bytes
DIAS_NEGATIVO = 7                        # vínculo negativo é tentado de novo depois disto
PRECO_MAX = 10_000_000                   # oferta válida: 0 < preço < 10⁷
CHAVES_VINCULOS = {'v', 'itens'}
CHAVES_VINCULO = {'p', 'em', 'via'}
VIAS = ('bbw', 'lista')
RE_DATA = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', re.A)

Oferta = collections.namedtuple('Oferta', 'item_id preco preco_antigo moeda condicao via')


class VinculosRecusados(ErroML):
    """Arquivo de vínculos inseguro ou fora do formato. O motivo é texto fixo: nada do arquivo vai para a mensagem."""
    saida = 2

    def __init__(self, motivo):
        super().__init__(f'arquivo de vínculos do catálogo recusado ({motivo}). Corrija ou apague o arquivo '
                         '(ml_catalogo.json ou o de ACHADINHOS_ML_CATALOGO): os vínculos são refeitos pela API')
        self.motivo = motivo


def _data(v):
    """A data 'AAAA-MM-DD' como datetime.date, ou None se não for uma data válida nesse formato."""
    if not isinstance(v, str) or not RE_DATA.fullmatch(v):
        return None
    try:
        return datetime.date.fromisoformat(v)
    except ValueError:
        return None


def _vinculo_valido(e):
    if not isinstance(e, dict) or set(e) != CHAVES_VINCULO or _data(e['em']) is None:
        return False
    if e['p'] is None:
        return e['via'] is None
    return _pid(e['p']) is not None and e['via'] in VIAS


def _vinculos_validos(d):
    """{item_id: {'p', 'em', 'via'}} do JSON do arquivo, ou None se algo estiver fora do formato."""
    if not isinstance(d, dict) or set(d) != CHAVES_VINCULOS or not _inteiro(d['v']) or d['v'] != 1:
        return None
    if not isinstance(d['itens'], dict):
        return None
    itens = {}
    for item_id, e in d['itens'].items():
        if not (isinstance(item_id, str) and RE_MLB.fullmatch(item_id)) or not _vinculo_valido(e):
            return None
        itens[item_id] = {'p': e['p'], 'em': e['em'], 'via': e['via']}
    return itens


def ler_vinculos(caminho=None):
    """{item_id: {'p': pid|None, 'em': 'AAAA-MM-DD', 'via': 'bbw'|'lista'|None}} do arquivo de vínculos (padrão:
    CATALOGO). Sem arquivo: {}. Leitura estrita, como a dos tokens: symlink, arquivo que não é comum, dono diferente,
    permissão aberta, mais de 2 MB, JSON fora do formato ou id que não casa com RE_MLB/RE_PRODUTO levantam
    VinculosRecusados (saída 2)."""
    bruto = _ler_privado(caminho or CATALOGO, MAX_ARQUIVO_VINCULOS, VinculosRecusados)
    if bruto is None:
        return {}
    try:
        itens = _vinculos_validos(json.loads(bruto.decode('ascii')))
    except (ValueError, RecursionError):
        itens = None
    if itens is None:
        raise VinculosRecusados('conteúdo fora do formato')
    return itens


def gravar_vinculos(itens, caminho=None):
    """Grava os vínculos (padrão: CATALOGO) por escrita atômica, 0600. Vínculo fora do formato é erro de programação
    (ValueError, nada é gravado); acima de 2 MB levanta VinculosRecusados e o arquivo antigo fica."""
    dados = {'v': 1, 'itens': itens}
    if _vinculos_validos(dados) is None:
        raise ValueError('vínculo fora do formato')
    bruto = json.dumps(dados, ensure_ascii=True, separators=(',', ':'), sort_keys=True).encode('ascii')
    if len(bruto) > MAX_ARQUIVO_VINCULOS:
        raise VinculosRecusados(f'passaria de {MAX_ARQUIVO_VINCULOS} bytes')
    gravar_atomico(caminho or CATALOGO, bruto, MAX_ARQUIVO_VINCULOS)


def hoje_local():
    return time.strftime('%Y-%m-%d')


def vinculo_do_cache(vinculos, item_id, hoje):
    """O que o cache já sabe do item: (pid, via) do vínculo provado; (None, None) do negativo com menos de
    DIAS_NEGATIVO dias; None quando é preciso vincular pela API (sem entrada, negativo vencido ou datado no futuro).
    O vínculo provado não vence: se o anúncio sai do produto, as ofertas dão None (para refazer, apague o arquivo)."""
    if _data(hoje) is None:
        raise ValueError('data inválida')
    e = vinculos.get(item_id)
    if not _vinculo_valido(e):
        return None
    if e['p'] is not None:
        return e['p'], e['via']
    dias = (_data(hoje) - _data(e['em'])).days
    return (None, None) if 0 <= dias < DIAS_NEGATIVO else None


def _vincular(sessao, item_id, titulo):
    """(pid, via) pela API, ou (None, None) no "não" conclusivo. Candidatos pelo título (_candidatos) e prova por
    pertença (_provar). Só é conclusivo o "não" em que toda leitura respondeu (200 ou 404): sem prova, o erro de
    servidor ou a resposta fora do formato da busca, de um produto ou de uma lista sobe (ErroApi ou
    RespostaInvalida). A prova achada em outro candidato vale mesmo com erro num anterior. O 403 PolicyAgent sobe
    como SemPermissao."""
    q = consulta_do_titulo(titulo)
    if not q:
        return None, None
    m = _Medidas()
    r, erro = _medir(m.busca, lambda: _candidatos(sessao, q))
    if erro is not None:
        raise erro
    pids, _ = r
    via, _, pid = _provar(sessao, m, item_id, pids)
    if m.negado is not None:
        raise m.negado
    if via:
        return pid, via
    if m.falha is not None:
        raise m.falha
    return None, None


def vincular(sessao, item_id, titulo, vinculos=None, hoje=None):
    """(pid, 'bbw'|'lista') se o anúncio item_id está provado num produto de catálogo, senão (None, None).

    A prova é por pertença: o item_id é o buy_box_winner.item_id do produto ou aparece em /products/{pid}/items. O
    título só gera candidatos: título idêntico sem pertença não vincula. `sessao` é a Sessao ou a vista com teto e
    pausa da sonda (_Chamadas). Com `vinculos` (o dict de ler_vinculos), consulta o cache antes (vinculo_do_cache) e
    anota nele o provado e o negativo conclusivo com a data `hoje` ('AAAA-MM-DD', padrão: hoje local); quem chama
    grava com gravar_vinculos. Sem prova e com uma leitura inconclusiva, sobe o erro dela (ErroApi de 5xx ou 4xx
    que não é 404, RespostaInvalida), para quem chama decidir por item entre contar e seguir ou parar. Limite, rede,
    SemPermissao, autorização (o 401 que sobra vira RefazerAutorizacao), a renovação recusada (RenovacaoFalhou) e o
    teto também sobem. Nada é anotado quando algo sobe."""
    if not (isinstance(item_id, str) and RE_MLB.fullmatch(item_id)):
        raise ValueError('id de anúncio inválido')
    hoje = hoje or hoje_local()
    if _data(hoje) is None:
        raise ValueError('data inválida')
    if vinculos is not None:
        guardado = vinculo_do_cache(vinculos, item_id, hoje)
        if guardado is not None:
            return guardado
    pid, via = _vincular(sessao, item_id, titulo)
    if vinculos is not None:
        vinculos[item_id] = {'p': pid, 'em': hoje, 'via': via}
    return pid, via


def _oferta(item_id, d, via):
    """Oferta a partir do buy_box_winner ou da linha da lista. Preço só se for número finito; preço antigo só se
    0 < v < PRECO_MAX; moeda e condição só se forem texto. Quem usa confere com oferta_valida."""
    antigo = d.get('original_price')
    return Oferta(item_id, d.get('price') if _numero(d.get('price')) else None,
                  antigo if _numero(antigo) and 0 < antigo < PRECO_MAX else None,
                  d.get('currency_id') if isinstance(d.get('currency_id'), str) else None,
                  d.get('condition') if isinstance(d.get('condition'), str) else None, via)


def oferta_valida(o):
    """Preço finito com 0 < preço < 10⁷ e moeda BRL."""
    return isinstance(o, Oferta) and _numero(o.preco) and 0 < o.preco < PRECO_MAX and o.moeda == 'BRL'


def ofertas_do_produto(sessao, pid, ids, paginas=PAGINAS_LISTA):
    """{item_id: Oferta|None} dos anúncios `ids` vinculados ao produto pid: primeiro pelo buy_box_winner (só se o
    item_id dele é um dos nossos), depois pela linha de cada um em /products/{pid}/items (até `paginas` páginas).
    None: o anúncio não está no produto. A oferta é sempre a do próprio anúncio, nunca a do vencedor.

    O pid passa por RE_PRODUTO e os ids por RE_MLB antes de qualquer chamada (ValueError). 404 no produto ou na lista
    é resposta (sem oferta); 403 PolicyAgent, outros status, resposta fora do formato (inclusive página da lista sem
    `paging.total` inteiro) e a renovação recusada (RenovacaoFalhou) sobem, para quem chama não contar o anúncio
    como indisponível por um erro passageiro."""
    if not _pid(pid):
        raise ValueError('id de produto inválido')
    ids = list(ids)
    if not all(isinstance(i, str) and RE_MLB.fullmatch(i) for i in ids):
        raise ValueError('id de anúncio inválido')
    ofertas = dict.fromkeys(ids)
    if not ofertas:
        return ofertas
    m = _Medidas()
    p, erro = _medir(m.produto, lambda: produto(sessao, pid))
    _anotar_erro(m, erro)
    bbw = p.get('buy_box_winner') if p is not None else None
    vencedor = bbw.get('item_id') if isinstance(bbw, dict) else None
    if isinstance(vencedor, str) and vencedor in ofertas:
        ofertas[vencedor] = _oferta(vencedor, bbw, 'bbw')
    faltam = {i for i, o in ofertas.items() if o is None}
    if faltam and m.negado is None and m.falha is None:
        for i, linha in _linhas_na_lista(sessao, m, pid, faltam, p, paginas).items():
            ofertas[i] = _oferta(i, linha, 'lista')
    if m.negado is not None:
        raise m.negado
    if m.falha is not None:
        raise m.falha
    return ofertas


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
    s = sub.add_parser('sondar', help='testa os endpoints candidatos (F0 a F6) e mostra só status e nomes de campo')
    s.add_argument('--catalogo', action='store_true',
                   help='mede o catálogo (F7 a F15) com uma amostra do banco, só leitura')
    s.add_argument('--amostra', type=int, default=None,
                   help=f'itens da amostra no --catalogo (padrão {AMOSTRA_PADRAO}, máximo {AMOSTRA_MAX})')
    s.add_argument('--semente', type=int, default=None,
                   help=f'semente da amostra no --catalogo (padrão {SEMENTE_PADRAO}; a mesma dá a mesma amostra)')
    sub.add_parser('sair', help='apaga os tokens locais')
    return p.parse_args(argv)


def main(argv=None):
    args = ler_argumentos(argv)
    if args.comando == 'sondar' and not args.catalogo and (args.amostra is not None or args.semente is not None):
        print(f'ERRO: {MSG_SO_CATALOGO}', file=sys.stderr, flush=True)
        return 2
    if args.comando == 'sondar' and args.catalogo:
        amostra = AMOSTRA_PADRAO if args.amostra is None else args.amostra
        if not 1 <= amostra <= AMOSTRA_MAX:
            print(f'ERRO: {MSG_AMOSTRA}', file=sys.stderr, flush=True)
            return 2
        semente = SEMENTE_PADRAO if args.semente is None else args.semente
    try:
        if args.comando == 'sair':
            return sair(TOKENS)
        if args.comando == 'autorizar':
            return autorizar(TOKENS, ler_segredo())
        sessao = sessao_do_ambiente()
        if args.comando == 'conferir':
            return conferir(sessao)
        if args.catalogo:
            return sondar_catalogo(sessao, DB, amostra, semente)
        return sondar(sessao)
    except ConfigFaltando as e:
        comando = args.comando
        if args.comando == 'sondar' and args.catalogo:   # a receita repete a sonda que o dono rodou (Q2)
            comando += ' --catalogo' + ''.join(f' --{nome} {v}' for nome, v in
                                               (('amostra', args.amostra), ('semente', args.semente)) if v is not None)
        msg = str(e).replace('<comando>', comando)
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
