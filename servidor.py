#!/usr/bin/env python3
"""Servidor local do site de mensagens de achadinhos.

Guarda tudo em achadinhos.db (SQLite) e serve o site em http://localhost:8765/
Uso:  python3 servidor.py
Ambiente (opcional): ACHADINHOS_DB troca o caminho do banco e ACHADINHOS_PORTA troca a porta.
Os testes usam as duas para nunca tocar o banco real nem o servidor em 8765.
Disparo automático (disparo.py): ACHADINHOS_DISPARO=0 desliga o agendador, ACHADINHOS_TICK_SEG
troca o intervalo (padrão 30 s) e ACHADINHOS_TRANSPORTE=falso com ACHADINHOS_TRANSPORTE_ARQUIVO
liga o transporte de teste.
API v1 de ofertas (api_ofertas.py, docs/produto/planos/api-achadinho-turbo.md): só liga com o token
Bearer de api_token.txt, ao lado deste arquivo (ACHADINHOS_API_TOKEN_ARQUIVO troca o caminho). Sem o
arquivo, toda rota /api/v1/ responde 503. Para trocar o token, troque o arquivo e reinicie.

O disparo é importado dentro das funções que o usam (criar_banco, rotas e __main__): quem importa
este módulo só pelo conectar/DB (migrar_categorias.py, classificar_lista.py) continua funcionando
mesmo numa cópia sem o disparo.py. O coletar_amazon.py chama criar_banco, então precisa do
disparo.py ao lado e também migra o banco (só aditivo: cria numeros, regras e envios).
"""
import json, re, sqlite3, html, os, sys, stat, hmac, logging, urllib.request, urllib.parse
from datetime import datetime
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get('ACHADINHOS_DB') or os.path.join(BASE, 'achadinhos.db')
PORT = int(os.environ.get('ACHADINHOS_PORTA') or 8765)
TAG_AMAZON = 'desejodemen01-20'
LOJAS = ('amazon', 'ml', 'shopee')
# Link curto de afiliado da Shopee (docs/produto/planos/perfumaria-tres-lojas.md). O host ainda será
# confirmado com um link real do dono. Para aceitar outro host (ex.: shope.ee), acrescente-o nos TRÊS
# lugares: aqui, no HOSTS_AFILIADO_SHOPEE do disparo.py e no HOSTS_LINK.shopee do index.html.
HOSTS_AFILIADO_SHOPEE = ('s.shopee.com.br',)
MAX_CORPO = 5 * 1024 * 1024   # bytes; acima disso a escrita recebe 413 sem ler o corpo
CAMPOS = ['titulo', 'preco', 'preco_antigo', 'desconto', 'avaliacao', 'num_avaliacoes',
          'vendas', 'frete', 'cupom', 'imagem']
# Teto de caracteres de cada campo de data (S2 do disparo): o maior título real tem 223 e os demais
# campos não passam de 73. Texto gigante no banco viraria mensagem gigante na análise do disparo.
MAX_TITULO, MAX_CAMPO = 500, 200
# Quem pode falar com o servidor (docs/produto/planos/blindar-servidor.md). Comparação exata.
HOSTS_LOCAIS = (f'localhost:{PORT}', f'127.0.0.1:{PORT}')          # cabeçalho Host (anti DNS rebinding)
ORIGENS_LOCAIS = tuple('http://' + h for h in HOSTS_LOCAIS)          # o index.html aberto aqui
ORIGENS_ML = ('https://lista.mercadolivre.com.br', 'https://www.mercadolivre.com.br')  # coleta do ML no Chrome
METODOS_ML = ('GET', 'POST', 'PATCH')
ROTAS_ML = re.compile(r'\A/api/(items(/\d+)?|ml-sem-afiliado)\Z')
HOSTS_AMAZON = ('www.amazon.com.br', 'amazon.com.br', 'amzn.to')        # /api/fetch e seus redirects
ESTATICO = ('/', '/index.html')
ESTATICO_TESTES = re.compile(r'\A/testes/[a-z0-9-]+\.test\.html\Z')
# Preenchidos no __main__; importado como módulo, o transporte é o manual e não há agendador.
TRANSPORTE = None
AGENDADOR = None
# API v1 de ofertas (Achadinho Turbo). API_TOKEN é preenchido no __main__ (iniciar_api_v1); importado como
# módulo, fica None e a v1 responde 503. O token nunca vai para log, resposta nem query string.
# O prefixo mora no api_ofertas.PREFIXO, como o do disparo (as rotas não ficam escritas aqui).
SUFIXOS_V1_LOG = ('ofertas', 'categorias')   # só para o log; quem decide a rota é o api_ofertas.rota
API_TOKEN_ARQUIVO = os.environ.get('ACHADINHOS_API_TOKEN_ARQUIVO') or os.path.join(BASE, 'api_token.txt')
API_TOKEN = None
TOKEN_VALIDO = re.compile(r'[A-Za-z0-9_-]{32,}')
MAX_ARQUIVO_TOKEN = 4096   # bytes; um token de verdade tem 43 caracteres
METODOS_HTTP = ('GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS')
UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36'


def conectar():
    con = sqlite3.connect(DB, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA journal_mode=WAL')
    return con


def criar_banco():
    con = conectar()
    con.executescript(f'''
    CREATE TABLE IF NOT EXISTS items (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      loja TEXT NOT NULL,            -- amazon | ml | shopee
      item_id TEXT NOT NULL,         -- ASIN, código MLB ou a própria url
      cat TEXT NOT NULL,             -- aba no site
      busca TEXT DEFAULT '',         -- termo pesquisado / subcategoria
      url TEXT NOT NULL,
      {', '.join(c + " TEXT DEFAULT ''" for c in CAMPOS)},
      tem_dados INTEGER DEFAULT 0,
      posicao INTEGER DEFAULT 0,
      criado_em TEXT, atualizado_em TEXT,
      UNIQUE(loja, item_id)
    );
    CREATE INDEX IF NOT EXISTS ix_items_cat ON items(cat);
    CREATE TABLE IF NOT EXISTS config (chave TEXT PRIMARY KEY, valor TEXT);
    ''')
    con.commit()
    import disparo
    disparo.migrar(con)   # numeros, regras e envios (PRAGMA user_version 1), só aditiva
    con.close()


def agora():
    return datetime.now().isoformat(timespec='seconds')


def linha_para_item(r):
    d = {c: r[c] for c in CAMPOS} if r['tem_dados'] else None
    return {'id': r['id'], 'loja': r['loja'], 'item_id': r['item_id'], 'cat': r['cat'],
            'busca': r['busca'], 'url': r['url'], 'data': d}


def eh_link_afiliado(url):
    """Regra do dono: https://meli.la/<código>, URL https://www.amazon.com.br com tag de afiliado ou
    https://s.shopee.com.br/<código alfanumérico> (link curto da Shopee, sem porta, query nem fragmento)."""
    if not isinstance(url, str) or any(c.isspace() or ord(c) < 32 for c in url):
        return False
    try:
        p = urllib.parse.urlsplit(url)
        porta = p.port
    except ValueError:
        return False
    if p.scheme != 'https' or p.username is not None or p.password is not None or porta not in (None, 443):
        return False
    if p.hostname == 'meli.la':
        return len(p.path) > 1
    if p.hostname == 'www.amazon.com.br':
        return urllib.parse.parse_qs(p.query).get('tag') == [TAG_AMAZON]   # uma tag só, a do dono
    if p.hostname in HOSTS_AFILIADO_SHOPEE:
        return eh_link_shopee(url)
    return False


def eh_link_shopee(url):
    """Link curto de afiliado da Shopee: https://<host de HOSTS_AFILIADO_SHOPEE>/<código alfanumérico>.

    Host exato e em minúsculas, sem usuário, porta, query nem fragmento. Compara o texto inteiro:
    o urlsplit baixa a caixa do host e esconde "?" e ":" vazios. É a regra de um item com loja shopee,
    que não aceita link de afiliado das outras lojas.
    """
    return isinstance(url, str) and any(
        re.fullmatch('https://' + re.escape(h) + '/[A-Za-z0-9]+', url) for h in HOSTS_AFILIADO_SHOPEE)


def eh_link_afiliado_da_loja(url, loja):
    """Link de afiliado que pode substituir a url de um item dessa loja (PATCH).

    A loja fica amarrada ao host: meli.la só em item ml, Amazon com tag só em item amazon e o link
    curto da Shopee só em item shopee. Loja fora de LOJAS não aceita nenhum link.
    """
    hosts = {'amazon': ('www.amazon.com.br',), 'ml': ('meli.la',), 'shopee': HOSTS_AFILIADO_SHOPEE}.get(loja, ())
    return eh_link_afiliado(url) and _host(url) in hosts


def sql_link_preservado():
    """Condição SQL de url que o upsert nunca troca: link de afiliado já gravado, amarrado à loja da linha.

    GLOB diferencia maiúsculas (o LIKE não). Montada a partir de constantes do módulo (nada vem da
    requisição).
    """
    return ' OR '.join(["(loja='ml' AND url GLOB 'https://meli.la/*')",
                        f"(loja='amazon' AND url GLOB '*tag={TAG_AMAZON}*')"]
                       + [f"(loja='shopee' AND url GLOB 'https://{h}/*')" for h in HOSTS_AFILIADO_SHOPEE])


def _host(url):
    """Host da url em minúsculas ('' se não houver). Só para url já conferida como texto."""
    return urllib.parse.urlsplit(url).hostname or ''


HOSTS_LOJAS = ('meli.la', 'www.amazon.com.br', 'amazon.com.br', 'amzn.to')   # mais *.mercadolivre.com.br e a Shopee
HOST_VALIDO = re.compile(r'\A[a-z0-9.-]+\Z')


def eh_url_de_loja(url):
    """url que pode ser gravada num item: https, sem usuário nem porta, num host das lojas.

    O front abre essa url em "Abrir na loja": javascript:, data: ou host de fora não podem entrar.
    """
    if not isinstance(url, str) or any(c.isspace() or ord(c) < 32 for c in url):
        return False
    try:
        p = urllib.parse.urlsplit(url)
    except ValueError:
        return False
    host = p.hostname or ''
    # netloc igual ao host recusa usuário (@), porta (inclusive ":" vazio) e barra invertida
    if p.scheme != 'https' or p.netloc.lower() != host or not HOST_VALIDO.match(host):
        return False
    return host in HOSTS_LOJAS or host in HOSTS_AFILIADO_SHOPEE or host.endswith('.mercadolivre.com.br')


def url_da_amazon(url):
    return _host(url) in HOSTS_AMAZON


def url_do_ml(url):
    host = _host(url)
    return host == 'meli.la' or host.endswith('.mercadolivre.com.br')


# Url que um item de cada loja aceita no POST, depois do eh_url_de_loja: a loja fica amarrada ao host.
# Valor: (validador, mensagem de erro). A Shopee só aceita o link curto de afiliado.
URL_DA_LOJA = {
    'amazon': (url_da_amazon, 'url de item da Amazon precisa ser da Amazon (amazon.com.br ou amzn.to)'),
    'ml': (url_do_ml, 'url de item do Mercado Livre precisa ser do Mercado Livre (meli.la ou mercadolivre.com.br)'),
    'shopee': (eh_link_shopee, 'url da Shopee precisa ser link de afiliado'),
}


class ErroCliente(Exception):
    """Requisição recusada pela validação; vira {"error": msg} com o código HTTP."""
    def __init__(self, codigo, msg):
        super().__init__(msg)
        self.codigo, self.msg = codigo, msg


def conferir_tipos(it, campos, onde=''):
    """Campos de texto só aceitam str ou None, e data só objeto com valores simples. ErroCliente 400.

    Tipo errado (lista, objeto) chegava ao sqlite e derrubava a conexão sem resposta.
    Número em data é aceito: o sqlite grava como texto e não há prova de que a coleta do ML não mande.
    """
    for campo in campos:
        if not isinstance(it.get(campo), (str, type(None))):
            raise ErroCliente(400, f'{onde}{campo} deve ser texto')
    d = it.get('data')
    if d is None:
        return
    if not isinstance(d, dict):
        raise ErroCliente(400, f'{onde}data deve ser um objeto')
    for c in CAMPOS:
        v = d.get(c)
        if isinstance(v, bool) or not isinstance(v, (str, int, float, type(None))):
            raise ErroCliente(400, f'{onde}data.{c} deve ser texto')
        teto = MAX_TITULO if c == 'titulo' else MAX_CAMPO
        if isinstance(v, str) and len(v) > teto:
            raise ErroCliente(400, f'{onde}data.{c} passa de {teto} caracteres')
        # número fora do INTEGER de 64 bits do sqlite (OverflowError) ou NaN/infinito: recusa com 400
        if isinstance(v, int) and not -2**63 <= v < 2**63 or isinstance(v, float) and v != v or v in (float('inf'), float('-inf')):
            raise ErroCliente(400, f'{onde}data.{c} tem número inválido')


def itens_do_lote(body):
    """Lista de itens do POST /api/items, validada inteira antes de gravar qualquer um."""
    lista = body.get('items', []) if isinstance(body, dict) else body
    if not isinstance(lista, list):
        raise ErroCliente(400, 'envie {"items": [...]} ou uma lista de itens')
    for i, it in enumerate(lista):
        if not isinstance(it, dict):
            raise ErroCliente(400, f'item {i}: deve ser um objeto')
        loja = it.get('loja') or 'amazon'
        if loja not in LOJAS:
            raise ErroCliente(400, f'item {i}: loja inválida (use amazon, ml ou shopee)')
        conferir_tipos(it, ('url', 'item_id', 'cat', 'busca'), f'item {i}: ')
        if it.get('url') and not eh_url_de_loja(it['url']):
            raise ErroCliente(400, f'item {i}: url precisa ser https da Amazon, do Mercado Livre ou da Shopee')
        # item sem url é ignorado no POST; com url, ela tem que ser da própria loja do item
        valida, msg = URL_DA_LOJA[loja]
        if it.get('url') and not valida(it['url']):
            raise ErroCliente(400, f'item {i}: {msg}')
    return lista


def upsert(con, it):
    """Insere ou atualiza um item. Mantém a categoria original se já existir."""
    loja = it.get('loja') or 'amazon'
    if loja not in LOJAS:
        raise ValueError('loja inválida (use amazon, ml ou shopee)')
    if loja == 'shopee' and not eh_link_shopee(it.get('url')):
        raise ValueError('url da Shopee precisa ser link de afiliado')
    item_id = it.get('item_id') or it['url']
    d = it.get('data') or {}
    vals = {c: (d.get(c) or '') for c in CAMPOS}
    tem = 1 if vals['titulo'] else 0
    cur = con.execute('SELECT id, tem_dados FROM items WHERE loja=? AND item_id=?', (loja, item_id)).fetchone()
    if not cur:
        pos = con.execute('SELECT COALESCE(MAX(posicao),0)+1 FROM items').fetchone()[0]
        try:
            con.execute(f'''INSERT INTO items (loja,item_id,cat,busca,url,{','.join(CAMPOS)},tem_dados,posicao,criado_em,atualizado_em)
                            VALUES (?,?,?,?,?,{','.join('?'*len(CAMPOS))},?,?,?,?)''',
                        [loja, item_id, it.get('cat') or 'Geral', it.get('busca') or '', it['url']]
                        + [vals[c] for c in CAMPOS] + [tem, pos, agora(), agora()])
            return 'inserido'
        except sqlite3.IntegrityError:
            # outro POST gravou o mesmo loja+item_id entre o SELECT e o INSERT: vira atualização
            cur = con.execute('SELECT id, tem_dados FROM items WHERE loja=? AND item_id=?', (loja, item_id)).fetchone()
            if not cur:
                raise
    if tem:
        sets = ', '.join(f'{c}=?' for c in CAMPOS)
        # atualiza preços/dados, mas nunca troca um link de afiliado já gerado
        con.execute(f'''UPDATE items SET {sets}, tem_dados=1, atualizado_em=?,
                        url=CASE WHEN {sql_link_preservado()} THEN url ELSE ? END
                        WHERE id=?''',
                    [vals[c] for c in CAMPOS] + [agora(), it['url'], cur['id']])
    return 'atualizado'


# ---------- coleta de um produto da Amazon (mesma lógica do amazon.php) ----------
def _grab(rx, txt, i=1):
    m = re.search(rx, txt, re.S)
    return html.unescape(re.sub(r'<[^>]+>', '', m.group(i))).strip() if m else ''


class URLRecusada(ValueError):
    """URL fora da allowlist do /api/fetch."""


def conferir_url_amazon(url):
    """Só https nos HOSTS_AMAZON, sem usuário nem porta estranha. Levanta URLRecusada."""
    recusa = URLRecusada('só links https da Amazon (amazon.com.br ou amzn.to)')
    if not isinstance(url, str) or any(c.isspace() or ord(c) < 32 for c in url):
        raise recusa
    try:
        p = urllib.parse.urlsplit(url)
        porta = p.port
    except ValueError:
        raise recusa
    if (p.scheme != 'https' or p.hostname not in HOSTS_AMAZON or p.username is not None
            or p.password is not None or porta not in (None, 443)):
        raise recusa
    return url


class RedirecionamentoAmazon(urllib.request.HTTPRedirectHandler):
    """Confere cada redirect antes de segui-lo, não só a URL final."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        conferir_url_amazon(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


OPENER_AMAZON = urllib.request.build_opener(RedirecionamentoAmazon)


def buscar_produto_amazon(url):
    conferir_url_amazon(url)
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept-Language': 'pt-BR,pt;q=0.9',
                                               'Accept': 'text/html,application/xhtml+xml'})
    with OPENER_AMAZON.open(req, timeout=30) as r:
        final = r.geturl(); h = r.read().decode('utf-8', 'ignore')
    return {'url_final': final, 'asin': _grab(r'/dp/([A-Z0-9]{10})', final),
            'captcha': 'captcha' in h.lower() and 'productTitle' not in h, **extrair_produto_amazon(h)}


def extrair_produto_amazon(h):
    return {
        'titulo': _grab(r'<span[^>]*id="productTitle"[^>]*>(.*?)</span>', h),
        'preco': _grab(r'id="corePriceDisplay_desktop_feature_div".*?<span class="a-offscreen">(.*?)</span>', h)
                 or _grab(r'id="corePrice_feature_div".*?<span class="a-offscreen">(.*?)</span>', h),
        'preco_antigo': _grab(r'class="basisPrice".*?<span class="a-offscreen">(.*?)</span>', h),
        'desconto': _grab(r'class="[^"]*savingsPercentage[^"]*"[^>]*>\s*(-?\d+%)', h),
        'avaliacao': _grab(r'<span[^>]*id="acrPopover"[^>]*title="([^"]*)"', h),
        'num_avaliacoes': _grab(r'id="acrCustomerReviewText"[^>]*>(.*?)</span>', h),
        'vendas': _grab(r'id="social-proofing-faceout-title-tk_bought"[^>]*>.*?<span[^>]*>(.*?)</span>', h),
        'cupom': _grab(r'id="couponText[^"]*"[^>]*>(.*?)</(?:span|label)>', h),
        'frete': 'Frete GRÁTIS' if 'Frete GRÁTIS' in h else '',
        'imagem': _grab(r'id="landingImage"[^>]*src="([^"]*)"', h),
    }


# ---------- API v1 de ofertas: token, guarda e log ----------
def carregar_token_api(caminho):
    """Lê o token da API v1. Devolve (token, motivo); token None quer dizer API desligada.

    O arquivo tem de ser regular, ASCII e ter no máximo MAX_ARQUIVO_TOKEN bytes; o token, sem os
    espaços das pontas, precisa de 32 caracteres ou mais de [A-Za-z0-9_-]. Com token válido, o motivo
    é '' ou o aviso de permissão aberta (grupo ou outros podem ler). O motivo nunca traz o token nem
    o conteúdo do arquivo, e a mensagem da exceção não entra (só o tipo).
    """
    try:
        # O_NONBLOCK: um FIFO no lugar do arquivo não trava a subida do servidor
        fd = os.open(caminho, os.O_RDONLY | os.O_NONBLOCK)
    except FileNotFoundError:
        return None, 'arquivo do token não encontrado'
    except OSError as e:
        return None, f'não consegui abrir o arquivo do token ({type(e).__name__})'
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            return None, 'o caminho do token não é um arquivo comum'
        bruto = os.read(fd, MAX_ARQUIVO_TOKEN + 1)
    except OSError as e:
        return None, f'não consegui ler o arquivo do token ({type(e).__name__})'
    finally:
        os.close(fd)
    if len(bruto) > MAX_ARQUIVO_TOKEN:
        return None, f'o arquivo do token passa de {MAX_ARQUIVO_TOKEN} bytes'
    try:
        token = bruto.decode('ascii').strip()
    except UnicodeDecodeError:
        token = ''
    if not TOKEN_VALIDO.fullmatch(token):
        return None, 'token inválido: use 32 ou mais caracteres de A-Z, a-z, 0-9, _ e -'
    aviso = ''
    if info.st_mode & 0o077:
        aviso = f'o arquivo do token pode ser lido por outros usuários (use chmod 600 {caminho})'
    return token, aviso


def prefixo_v1():
    """api_ofertas.PREFIXO, importado sob demanda (como o disparo): quem importa este módulo só pelo
    conectar/DB não precisa do api_ofertas.py nem do disparo.py."""
    import api_ofertas
    return api_ofertas.PREFIXO


def eh_rota_v1(caminho):
    """Caminho cru (sem query) da API v1: o prefixo sem a barra final ou qualquer coisa abaixo dele."""
    if not caminho.startswith('/api/'):
        return False
    p = prefixo_v1()
    return caminho == p[:-1] or caminho.startswith(p)


def linha_v1_para_log(linha):
    """Linha da requisição da v1 sem nada que o cliente possa ter mandado de segredo.

    Fica o método (se for um conhecido), a rota (se for ofertas ou categorias; senão "(outra rota)"),
    "?(omitida)" no lugar da query e a versão HTTP (se bem formada). Um ?token= mandado por engano,
    um token no caminho ou numa linha malformada nunca chegam ao log.
    """
    prefixo = prefixo_v1()
    partes = linha.split()
    metodo = partes[0] if partes and partes[0] in METODOS_HTTP else '?'
    alvo = next((p for p in partes if prefixo[:-1] in p), '')
    caminho, tem_query, _ = alvo.partition('?')
    rota = caminho if caminho in [prefixo + suf for suf in SUFIXOS_V1_LOG] else prefixo + '(outra rota)'
    versao = partes[-1] if partes and re.fullmatch(r'HTTP/[0-9]\.[0-9]', partes[-1]) else ''
    return ' '.join(p for p in (metodo, rota + ('?(omitida)' if tem_query else ''), versao) if p)


class Handler(SimpleHTTPRequestHandler):
    timeout = 15   # segundos por leitura no socket: corpo menor que o Content-Length não prende a thread

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=BASE, **kw)

    def log_message(self, fmt, *args):
        # args[0] é a linha da requisição no log de acesso, mas um código (HTTPStatus) no send_error
        primeiro = str(args[0]) if args else ''
        if '/api/' in primeiro:
            if prefixo_v1()[:-1] in primeiro:   # pela linha crua: pega também a linha malformada
                args = (linha_v1_para_log(primeiro),) + args[1:]
            super().log_message(fmt, *args)

    def send_error(self, code, message=None, explain=None):
        """Erro do próprio http.server (linha malformada, método sem do_X, linha longa demais).

        Só a frase padrão do código: a página de erro padrão repetiria ao cliente o método ou a linha
        que ele mandou (um token posto ali por engano, por exemplo). O log de acesso segue passando
        pelo log_message, que tira o que vier na linha da v1.
        """
        super().send_error(code)

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        # contra clickjacking; SAMEORIGIN porque testes/copiar-imagem.test.html embute o /index.html
        self.send_header('X-Frame-Options', 'SAMEORIGIN')
        self.send_header('Content-Security-Policy', "frame-ancestors 'self'")
        # CORS só quando bloquear() aprovou uma origem do ML; a origem local não precisa
        if getattr(self, '_origem_cors', None):
            self.send_header('Access-Control-Allow-Origin', self._origem_cors)
            self.send_header('Vary', 'Origin')
        super().end_headers()

    def json(self, obj, code=200, cabecalhos=()):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        for nome, valor in cabecalhos:
            self.send_header(nome, valor)
        self.send_header('Content-Length', str(len(b)))
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(b)

    def bloquear(self):
        """Guarda única, no início de todo método. Responde 403 e devolve True quando recusa.

        Host tem que ser o deste servidor. Em /api/, a Origin tem que ser a local ou uma do ML
        (essas só com GET/POST/PATCH nas rotas da coleta); sem Origin, Sec-Fetch-Site de outro
        site também é recusado. O caminho é o cru, sem decodificar, e vale para todo o roteamento.
        """
        self._origem_cors = None
        self._caminho = self.path.split('?', 1)[0]
        if (self.headers.get('Host') or '').strip().lower() not in HOSTS_LOCAIS:
            self.json({'error': 'host não permitido'}, 403); return True
        if eh_rota_v1(self._caminho):
            return self.bloquear_v1()
        if not self._caminho.startswith('/api/'):
            return False
        origem = self.headers.get('Origin')
        if origem is not None:
            origem = origem.strip().lower()
            if origem in ORIGENS_LOCAIS:
                return False
            if origem in ORIGENS_ML:
                metodo = (self.headers.get('Access-Control-Request-Method') or '').strip().upper() \
                    if self.command == 'OPTIONS' else self.command
                if metodo in METODOS_ML and ROTAS_ML.match(self._caminho):
                    self._origem_cors = origem
                    return False
            self.json({'error': 'origem não permitida'}, 403); return True
        if (self.headers.get('Sec-Fetch-Site') or '').strip().lower() in ('cross-site', 'same-site'):
            self.json({'error': 'origem não permitida'}, 403); return True
        return False

    def bloquear_v1(self):
        """Guarda da API v1, depois da checagem de Host. Responde e devolve True quando recusa.

        Ordem: navegador (Origin, mesmo a local, ou Sec-Fetch-Site) dá 403; API desligada (sem
        token) dá 503; sem "Authorization: Bearer <token>" certo dá 401 com WWW-Authenticate; método
        diferente de GET dá 405, só depois da autenticação. O token só vale no cabeçalho (?token= não
        autentica) e é comparado em tempo constante. A v1 nunca leva CORS.
        """
        if self.headers.get('Origin') is not None or self.headers.get('Sec-Fetch-Site') is not None:
            self.json({'error': 'a API v1 não aceita pedidos de navegador'}, 403); return True
        if not API_TOKEN:
            # o motivo (arquivo ausente, token inválido, caminho trocado) já foi para o stderr na subida
            self.json({'error': 'a API v1 está desligada: veja o motivo no log do servidor'}, 503); return True
        if not self.token_v1_confere():
            self.json({'error': 'token ausente ou inválido: envie Authorization: Bearer <token>'}, 401,
                      cabecalhos=[('WWW-Authenticate', 'Bearer')])
            return True
        if self.command != 'GET':
            self.json({'error': 'método não permitido: a API só aceita GET'}, 405,
                      cabecalhos=[('Allow', 'GET')])
            return True
        return False

    def token_v1_confere(self):
        """Um único cabeçalho Authorization, no formato "Bearer <token>" (esquema sem diferenciar caixa)."""
        valores = self.headers.get_all('Authorization') or []
        if len(valores) != 1:
            return False
        esquema, _, recebido = valores[0].strip().partition(' ')
        if esquema.lower() != 'bearer':
            return False
        # bytes dos dois lados: compare_digest com str recusa texto fora do ASCII
        return hmac.compare_digest(recebido.strip().encode('utf-8', 'replace'), API_TOKEN.encode('ascii'))

    def estatico_permitido(self):
        """Só /, /index.html e /testes/<nome>.test.html; ajusta self.path para o arquivo."""
        if self._caminho in ESTATICO:
            self.path = '/index.html'; return True
        if ESTATICO_TESTES.match(self._caminho):
            self.path = self._caminho; return True
        return False

    def corpo(self):
        """Corpo JSON da escrita. ErroCliente 415 sem Content-Type application/json, 400 se inválido."""
        try:
            n = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            raise ErroCliente(400, 'Content-Length inválido')
        if n < 0:
            raise ErroCliente(400, 'Content-Length inválido')
        if n > MAX_CORPO:
            raise ErroCliente(413, 'corpo grande demais (máximo de 5 MB)')
        try:
            bruto = self.rfile.read(n) if n else b''
        except OSError:   # inclui o TimeoutError do Handler.timeout
            raise ErroCliente(408, 'o corpo da requisição não chegou inteiro')
        if len(bruto) < n:
            raise ErroCliente(400, 'o corpo da requisição não chegou inteiro')
        if self.headers.get_content_type() != 'application/json':
            raise ErroCliente(415, 'envie Content-Type: application/json')
        try:
            return json.loads(bruto or b'{}')
        except (ValueError, RecursionError):
            raise ErroCliente(400, 'JSON inválido')

    def despachar_disparo(self):
        """Caminho com o prefixo disparo.PREFIXO vai para disparo.rota. True se a rota era do disparo.

        Fora de ROTAS_ML: o bloquear() já recusou as origens do ML com 403. Erro inesperado vira
        500 com só o tipo no log (a mensagem de uma biblioteca pode trazer dados da query).
        """
        import disparo
        if not self._caminho.startswith(disparo.PREFIXO):
            return False
        q = dict(urllib.parse.parse_qsl(self.path.split('?', 1)[1] if '?' in self.path else ''))
        con = None
        try:
            body = self.corpo() if self.command in ('POST', 'PUT', 'PATCH') else None
            con = conectar()
            resposta = disparo.rota(con, self.command, self._caminho, q, body, eh_link_afiliado,
                                    TRANSPORTE or disparo.TransporteManual(), AGENDADOR)
        except ErroCliente as e:
            self.json({'error': e.msg}, e.codigo)
        except disparo.ErroDisparo as e:
            self.json({'error': e.msg}, e.codigo)
        except Exception as e:   # noqa: BLE001
            self.log_message('"%s" disparo falhou: %s', self.requestline, type(e).__name__)
            self.json({'error': 'erro interno no disparo'}, 500)
        else:
            self.json(resposta)
        finally:
            if con is not None:
                con.close()
        return True

    def despachar_v1(self):
        """GET autenticado em /api/v1/ vai para api_ofertas.rota. True se a rota era da v1.

        O bloquear_v1() já conferiu navegador, token e método. A conexão fica só de leitura
        (PRAGMA query_only): a v1 nunca grava. ErroApi vira {"error": msg} com o código; erro
        inesperado vira 500 com só o tipo no log (a mensagem do sqlite pode trazer dados).
        """
        if not eh_rota_v1(self._caminho):
            return False
        import api_ofertas
        pares = urllib.parse.parse_qsl(self.path.split('?', 1)[1] if '?' in self.path else '',
                                       keep_blank_values=True)   # "q=" vazio dá 400 em vez de sumir
        con = None
        try:
            con = conectar()
            con.execute('PRAGMA query_only=1')
            resposta = api_ofertas.rota(con, self.command, self._caminho, pares, eh_link_afiliado)
        except api_ofertas.ErroApi as e:
            self.json({'error': e.msg}, e.codigo)
        except Exception as e:   # noqa: BLE001
            self.log_message('"%s" api v1 falhou: %s', self.requestline, type(e).__name__)
            self.json({'error': 'erro interno na API v1'}, 500)
        else:
            self.json(resposta)
        finally:
            if con is not None:
                con.close()
        return True

    def do_OPTIONS(self):
        if self.bloquear():
            return
        self.send_response(204)
        if self._origem_cors:
            self.send_header('Access-Control-Allow-Methods', ', '.join(METODOS_ML))
            self.send_header('Access-Control-Allow-Headers', 'Content-Type')
            if (self.headers.get('Access-Control-Request-Private-Network') or '').strip().lower() == 'true':
                self.send_header('Access-Control-Allow-Private-Network', 'true')
        self.end_headers()

    def do_HEAD(self):
        if self.bloquear():
            return
        if self._caminho.startswith('/api/'):
            return self.json({'error': 'método não permitido'}, 405)
        if not self.estatico_permitido():
            return self.json({'error': 'não encontrado'}, 404)
        return super().do_HEAD()

    def do_GET(self):
        if self.bloquear() or self.despachar_v1() or self.despachar_disparo():
            return
        caminho = self._caminho
        q = dict(urllib.parse.parse_qsl(self.path.split('?', 1)[1] if '?' in self.path else ''))
        if not caminho.startswith('/api/'):
            if not self.estatico_permitido():
                return self.json({'error': 'não encontrado'}, 404)
            return super().do_GET()
        if caminho == '/api/ml-sem-afiliado':
            con = conectar()
            rows = con.execute("SELECT id, url FROM items WHERE loja='ml' AND url NOT LIKE 'https://meli.la/%' ORDER BY id").fetchall()
            con.close()
            return self.json([dict(r) for r in rows])
        if caminho == '/api/items':
            con = conectar()
            rows = con.execute('SELECT * FROM items ORDER BY posicao').fetchall()
            con.close()
            return self.json([linha_para_item(r) for r in rows])
        if caminho.startswith('/api/config/'):
            con = conectar()
            r = con.execute('SELECT valor FROM config WHERE chave=?', (caminho.split('/')[-1],)).fetchone()
            con.close()
            return self.json(json.loads(r['valor']) if r else None)
        if caminho == '/api/fetch':
            try:
                return self.json(buscar_produto_amazon(q.get('url', '')))
            except URLRecusada as e:
                return self.json({'error': str(e)}, 400)
            except Exception as e:   # sem str(e): a mensagem da biblioteca não vai para o cliente
                self.log_message('"%s" fetch falhou: %s', self.requestline, type(e).__name__)
                return self.json({'error': 'Não consegui abrir a página da Amazon.'}, 502)
        return self.json({'error': 'rota não encontrada'}, 404)

    def do_POST(self):
        if self.bloquear() or self.despachar_disparo():
            return
        if self._caminho == '/api/items':
            try:
                lista = itens_do_lote(self.corpo())
            except ErroCliente as e:
                return self.json({'error': e.msg}, e.codigo)
            con = conectar(); cont = {'inserido': 0, 'atualizado': 0}
            try:
                for it in lista:
                    if it.get('url'):
                        cont[upsert(con, it)] += 1
                con.commit()
                total = con.execute('SELECT COUNT(*) FROM items').fetchone()[0]
            except ValueError as e:
                con.rollback()
                return self.json({'error': str(e)}, 400)
            finally:
                con.close()   # sem commit, nada do lote fica gravado
            return self.json({**cont, 'total': total})
        return self.json({'error': 'rota não encontrada'}, 404)

    def do_PATCH(self):
        if self.bloquear() or self.despachar_disparo():
            return
        m = re.match(r'^/api/items/(\d+)$', self._caminho)
        if not m:
            return self.json({'error': 'rota não encontrada'}, 404)
        try:
            body = self.corpo()
            if not isinstance(body, dict):
                raise ErroCliente(400, 'envie um objeto JSON')
            if body.get('cat') and not isinstance(body['cat'], str):
                raise ErroCliente(400, 'cat deve ser texto')
            if body.get('data') and not isinstance(body['data'], dict):
                raise ErroCliente(400, 'data deve ser um objeto')
            if body.get('data'):
                conferir_tipos(body, ())
            # regra do dono: só link de afiliado substitui a url (nunca um link comum)
            if body.get('url') and not eh_link_afiliado(body['url']):
                raise ErroCliente(400, 'url precisa ser link de afiliado (https://meli.la/..., Amazon com tag ou https://s.shopee.com.br/...)')
        except ErroCliente as e:
            return self.json({'error': e.msg}, e.codigo)
        con = conectar(); iid = int(m.group(1))
        if body.get('url'):
            row = con.execute('SELECT loja FROM items WHERE id=?', (iid,)).fetchone()
            # item que não existe (excluído no meio do afiliar() do ML) segue sem erro e devolve null
            if row and not eh_link_afiliado_da_loja(body['url'], row['loja']):
                con.close()   # antes de qualquer UPDATE: nem a cat do mesmo pedido muda
                return self.json({'error': f'url precisa ser link de afiliado da loja do item ({row["loja"]})'}, 400)
        for campo in ('cat', 'url'):
            if body.get(campo):
                con.execute(f'UPDATE items SET {campo}=?, atualizado_em=? WHERE id=?', (body[campo], agora(), iid))
        if body.get('data'):
            d = body['data']
            sets = ', '.join(f'{c}=?' for c in CAMPOS)
            con.execute(f'UPDATE items SET {sets}, tem_dados=1, atualizado_em=? WHERE id=?',
                        [d.get(c) or '' for c in CAMPOS] + [agora(), iid])
        con.commit()
        r = con.execute('SELECT * FROM items WHERE id=?', (iid,)).fetchone(); con.close()
        return self.json(linha_para_item(r) if r else None)

    def do_PUT(self):
        if self.bloquear() or self.despachar_disparo():
            return
        if self._caminho.startswith('/api/config/'):
            try:
                valor = self.corpo()
            except ErroCliente as e:
                return self.json({'error': e.msg}, e.codigo)
            con = conectar()
            con.execute('INSERT OR REPLACE INTO config VALUES (?,?)',
                        (self._caminho.split('/')[-1], json.dumps(valor, ensure_ascii=False)))
            con.commit(); con.close()
            return self.json({'ok': True})
        return self.json({'error': 'rota não encontrada'}, 404)

    def do_DELETE(self):
        if self.bloquear() or self.despachar_disparo():
            return
        m = re.match(r'^/api/items/(\d+)$', self._caminho)
        if not m:
            return self.json({'error': 'rota não encontrada'}, 404)
        con = conectar(); con.execute('DELETE FROM items WHERE id=?', (int(m.group(1)),)); con.commit(); con.close()
        return self.json({'ok': True})


def iniciar_disparo():
    """Transporte pelo ambiente e, salvo ACHADINHOS_DISPARO=0, o agendador (thread daemon).

    O log do agendador vai para o stderr, junto com o de acesso, e só traz contagens e tipos de erro.
    """
    global TRANSPORTE, AGENDADOR
    import disparo
    TRANSPORTE = disparo.transporte_do_ambiente()
    log = logging.getLogger('disparo')
    if not log.handlers:
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter('%(asctime)s %(message)s', '%Y-%m-%d %H:%M:%S'))
        log.addHandler(h)
    log.setLevel(logging.INFO)
    log.propagate = False
    if disparo.agendador_ligado():
        AGENDADOR = disparo.Agendador(conectar, eh_link_afiliado, TRANSPORTE,
                                      intervalo=disparo.intervalo_do_ambiente())
        AGENDADOR.start()
    log.info('disparo: agendador %s, transporte %s', 'ligado' if AGENDADOR else 'desligado', TRANSPORTE.nome)


def iniciar_api_v1():
    """Lê o token da API v1 (uma vez, na subida) e avisa no stderr se ela ficou ligada ou não.

    Só o caminho e o motivo vão para o log, nunca o token. Sem token válido o servidor sobe do
    mesmo jeito e a v1 responde 503.
    """
    global API_TOKEN
    API_TOKEN, motivo = carregar_token_api(API_TOKEN_ARQUIVO)
    if API_TOKEN:
        print(f'API v1 ligada (token em {API_TOKEN_ARQUIVO})', file=sys.stderr, flush=True)
        if motivo:
            print(f'API v1: aviso: {motivo}', file=sys.stderr, flush=True)
    else:
        print(f'API v1 desligada: {motivo} ({API_TOKEN_ARQUIVO})', file=sys.stderr, flush=True)


if __name__ == '__main__':
    criar_banco()
    # bind antes do agendador: a porta ocupada impede uma segunda instância de disparar em dobro
    servidor = ThreadingHTTPServer(('127.0.0.1', PORT), Handler)
    print(f'Site em http://localhost:{PORT}/  (banco: {DB})')
    iniciar_api_v1()
    iniciar_disparo()
    try:
        servidor.serve_forever()
    finally:
        if AGENDADOR:
            AGENDADOR.parar()
