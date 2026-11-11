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
Versão do código (CA12 de docs/produto/planos/endurecer-engenharia-e-operacao.md): a subida registra no
log o hash de ARQUIVOS_VERSAO e o último commit; GET /api/versao diz se o código em disco mudou desde
então (`python3 verificar.py --servidor` usa isso para avisar que é preciso reiniciar).

O disparo é importado dentro das funções que o usam (criar_banco, rotas e __main__): quem importa
este módulo só pelo conectar/DB (migrar_categorias.py, classificar_lista.py) continua funcionando
mesmo numa cópia sem o disparo.py. O coletar_amazon.py e o coletar_shopee.py chamam criar_banco, então
precisam do disparo.py e do genero.py ao lado (o disparo.py importa o genero no topo) e também migram o
banco (só aditivo: cria numeros, regras, envios, generos_manuais e a coluna items.preco_em). O genero.py
(público de cada item, derivado na leitura) também é importado sob demanda aqui.
"""
import json, re, sqlite3, html, os, sys, stat, hmac, logging, urllib.request, urllib.parse, urllib.error
import contextlib, errno, fcntl, hashlib, http.client, collections, math, threading, time
from datetime import datetime
from decimal import Decimal
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
# Preço antigo de LIMITE_PRECO_ANTIGO vezes o preço ou mais não é desconto: é o seletor pegando outra coisa
# (preço por litro ou por unidade). O upsert descarta o antigo e o desconto desse item (CA4 de
# docs/produto/planos/abas-nichadas-e-coleta.md).
LIMITE_PRECO_ANTIGO = 5
# Quem pode falar com o servidor (docs/produto/planos/blindar-servidor.md). Comparação exata.
HOSTS_LOCAIS = (f'localhost:{PORT}', f'127.0.0.1:{PORT}')          # cabeçalho Host (anti DNS rebinding)
ORIGENS_LOCAIS = tuple('http://' + h for h in HOSTS_LOCAIS)          # o index.html aberto aqui
ORIGENS_ML = ('https://lista.mercadolivre.com.br', 'https://www.mercadolivre.com.br')  # coleta do ML no Chrome
METODOS_ML = ('GET', 'POST', 'PATCH')
ROTAS_ML = re.compile(r'\A/api/(items(/\d+)?|ml-sem-afiliado)\Z')
HOSTS_AMAZON = ('www.amazon.com.br', 'amazon.com.br', 'amzn.to')        # /api/fetch e seus redirects
# Id de item no caminho: até 19 dígitos (o int() de milhares de dígitos levanta ValueError) e, depois
# do int(), até MAX_ID_SQLITE (acima disso o sqlite levanta OverflowError). Fora disso, 404.
ROTA_ITEM = re.compile(r'\A/api/items/([0-9]{1,19})\Z')
# Correção manual do público (genero.py). Fora de ROTAS_ML de propósito: a origem do ML recebe 403.
ROTA_GENERO = re.compile(r'\A/api/items/([0-9]{1,19})/genero\Z')
MAX_ID_SQLITE = 2**63 - 1   # id maior que isso não cabe no INTEGER do sqlite: é item inexistente
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


class RodadaEmAndamento(Exception):
    """A trava da rodada desta loja não pôde ser pega (os CLIs saem com 4).

    `motivo` é None quando outra rodada da mesma loja segura a trava; senão, um texto fixo (nada de caminho
    nem de mensagem do sistema). `nome` é só o nome do arquivo da trava, sem a pasta.
    """

    def __init__(self, loja, nome, motivo=None):
        self.loja, self.nome, self.motivo = loja, nome, motivo
        if motivo is None:
            texto = f'outra rodada de {loja} está em andamento ({nome}); espere ela terminar.'
        else:
            texto = f'não consegui pegar a trava da rodada de {loja} ({nome}): {motivo}.'
        super().__init__(texto)


@contextlib.contextmanager
def travar_rodada(loja):
    """flock exclusivo e sem espera em <DB>.rodada-<loja>.lock enquanto durar o bloco (plano
    docs/produto/planos/endurecer-engenharia-e-operacao.md, etapa 3, CA4).

    Uma rodada por loja contra o mesmo banco: a coleta e a atualização de preços da mesma loja se excluem; lojas
    diferentes rodam juntas. Os CLIs pegam a trava antes de ler credencial, tokens, banco ou progresso, e saem
    com 4 quando ela levanta RodadaEmAndamento. O arquivo tem de ser comum e do próprio usuário (symlink é
    recusado pelo O_NOFOLLOW) e fica em 0600. A trava some com o processo (kill -9 não deixa trava velha); o
    arquivo nunca é apagado por aqui: apagá-lo à mão no meio de uma rodada deixa a seguinte entrar.
    Cópia do `travar` de tools/garimpo_feminino/banco.py, sem importá-lo.
    """
    if loja not in LOJAS:
        raise ValueError('loja desconhecida')
    caminho = DB + '.rodada-' + loja + '.lock'   # DB lido agora: os testes trocam o servidor.DB
    nome = os.path.basename(caminho)
    try:
        # O_NONBLOCK: um FIFO no lugar da trava não prende o open (e o S_ISREG o recusa logo depois)
        fd = os.open(caminho, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, 0o600)
    except OSError:
        raise RodadaEmAndamento(loja, nome,
                                'não deu para abrir o arquivo da trava (symlink, pasta ou permissão)') from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise RodadaEmAndamento(loja, nome, 'o arquivo da trava não é um arquivo comum do seu usuário')
        if stat.S_IMODE(info.st_mode) != 0o600:
            os.fchmod(fd, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            if e.errno in (errno.EWOULDBLOCK, errno.EAGAIN):
                raise RodadaEmAndamento(loja, nome) from None
            raise RodadaEmAndamento(loja, nome, 'o sistema recusou a trava') from None
        try:
            # entre o open e o flock o arquivo pode ter sido trocado (apagado à mão e recriado por outra rodada):
            # a trava só vale se o caminho ainda leva ao mesmo arquivo que está travado
            atual = os.stat(caminho, follow_symlinks=False)
        except OSError:
            atual = None
        if atual is None or (atual.st_dev, atual.st_ino) != (info.st_dev, info.st_ino):
            fcntl.flock(fd, fcntl.LOCK_UN)
            raise RodadaEmAndamento(loja, nome, 'o arquivo da trava foi trocado enquanto eu o abria')
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


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
      preco_em TEXT,                 -- quando o preço foi confirmado (NULL = sem preço legível)
      UNIQUE(loja, item_id)
    );
    CREATE INDEX IF NOT EXISTS ix_items_cat ON items(cat);
    CREATE TABLE IF NOT EXISTS config (chave TEXT PRIMARY KEY, valor TEXT);
    ''')
    con.commit()
    import disparo
    # PRAGMA user_version 3, só aditiva: v1 cria numeros, regras e envios; v2, generos_manuais e regras.generos;
    # v3, items.preco_em (num banco que já tinha items)
    disparo.migrar(con)
    con.close()


def agora():
    return datetime.now().isoformat(timespec='seconds')


# ---------------------------------------------------------------- versão do código (/api/versao)
# Arquivos .py que o servidor carrega. O index.html fica de fora: ele é lido do disco a cada pedido, então
# mudança nele só pede recarregar a página. O genero.py e o api_ofertas.py são importados no primeiro pedido
# que os usa; mudança neles depois da subida também conta como "mudou" (do lado seguro: reinicie).
ARQUIVOS_VERSAO = ('servidor.py', 'disparo.py', 'genero.py', 'api_ofertas.py')
TAMANHO_CODIGO = 12           # caracteres do sha256 no "codigo" e no "em_disco"
TAMANHO_COMMIT = 7            # caracteres do commit, como no git log --oneline
MAX_REF_GIT = 4096            # bytes lidos do .git/HEAD e de um ref solto (o normal é 41)
MAX_PACKED_REFS = 8 * 1024 * 1024
RE_SHA_GIT = re.compile(r'[0-9a-f]{40}|[0-9a-f]{64}')   # sha1 ou sha256
# Nome de ref aceito: só refs/..., componentes sem ponto no início (nem "..") e sem barra dupla. Um HEAD
# que aponte para "../fora", caminho absoluto ou outro formato vira git null, sem abrir nada.
RE_REF_GIT = re.compile(r'refs(?:/[A-Za-z0-9_+@-][A-Za-z0-9_.+@-]*)+')
# Preenchida no __main__ (registrar_versao); importado como módulo, fica None e a rota responde 503.
VERSAO = None


def hash_do_codigo(base=BASE, arquivos=ARQUIVOS_VERSAO):
    """sha256[:12] dos bytes de cada arquivo, na ordem, com nome e tamanho no meio (dois arquivos nunca se
    confundem). Arquivo que não abre entra como ausente: sumir ou voltar também muda o hash."""
    h = hashlib.sha256()
    for nome in arquivos:
        try:
            with open(os.path.join(base, nome), 'rb') as f:
                dados = f.read()
        except OSError:
            h.update(f'{nome}\0ausente\0'.encode())
            continue
        h.update(f'{nome}\0{len(dados)}\0'.encode())
        h.update(dados)
    return h.hexdigest()[:TAMANHO_CODIGO]


def _ler_dentro(pasta_git, relativo, limite=MAX_REF_GIT):
    """Texto de um arquivo dentro da pasta .git (no máximo `limite` bytes), ou None. Recusa o que, depois
    de resolver links, cair fora dela, e o que não for arquivo comum."""
    raiz = os.path.realpath(pasta_git)
    alvo = os.path.realpath(os.path.join(raiz, relativo))
    if not alvo.startswith(raiz + os.sep) or not os.path.isfile(alvo):
        return None
    with open(alvo, 'rb') as f:
        bruto = f.read(limite + 1)
    if len(bruto) > limite:
        return None
    return bruto.decode('ascii')


def _sha_curto(texto):
    texto = (texto or '').strip()
    return texto[:TAMANHO_COMMIT] if RE_SHA_GIT.fullmatch(texto) else None


def commit_git(base=BASE):
    """Commit curto do HEAD, lido direto de <base>/.git (sem subprocess), ou None.

    HEAD com "ref: refs/..." lê o ref solto e, sem ele, o packed-refs; HEAD destacado traz o sha. Fica
    None quando: não há .git (ou ele é um arquivo, como numa worktree), o ref é malformado ou sai da pasta
    .git, o arquivo passa do tamanho esperado ou qualquer leitura falha. Nada além do sha curto sai daqui.
    """
    pasta_git = os.path.join(base, '.git')
    try:
        if os.path.islink(pasta_git) or not os.path.isdir(pasta_git):
            return None
        head = _ler_dentro(pasta_git, 'HEAD')
        if head is None:
            return None
        head = head.strip()
        if not head.startswith('ref:'):
            return _sha_curto(head)
        ref = head[len('ref:'):].strip()
        if not RE_REF_GIT.fullmatch(ref) or '..' in ref or ref.endswith(('.', '/', '.lock')):
            return None
        solto = _ler_dentro(pasta_git, ref)
        if solto is not None:
            return _sha_curto(solto)
        empacotado = _ler_dentro(pasta_git, 'packed-refs', MAX_PACKED_REFS)
        for linha in (empacotado or '').splitlines():
            sha, _, nome = linha.strip().partition(' ')
            if nome == ref:
                return _sha_curto(sha)
        return None
    except (OSError, UnicodeDecodeError, ValueError):
        return None


def registrar_versao(base=BASE, arquivos=ARQUIVOS_VERSAO):
    """Guarda em VERSAO o código e o commit desta subida e devolve a linha do log."""
    global VERSAO
    VERSAO = {'codigo': hash_do_codigo(base, arquivos), 'git': commit_git(base), 'iniciado_em': agora()}
    return f'Código {VERSAO["codigo"]} (último commit {VERSAO["git"] or "?"}; pode haver mudança sem commit)'


def resposta_versao(versao, base=BASE, arquivos=ARQUIVOS_VERSAO):
    """JSON do GET /api/versao: o código da subida, o de agora no disco e se mudou."""
    em_disco = hash_do_codigo(base, arquivos)
    return {'codigo': versao['codigo'], 'em_disco': em_disco, 'mudou': em_disco != versao['codigo'],
            'git': versao['git'], 'iniciado_em': versao['iniciado_em']}


def linha_para_item(r, manuais=None):
    """JSON de um item do /api/items. `manuais` é o genero.manuais(con), lido uma vez por pedido.

    genero e genero_origem vêm do genero.do_item ('manual' quando o dono corrigiu); genero_auto é o
    que a regra automática dá, para a tela mostrar "Automático (...)" num item corrigido.
    """
    import genero
    d = {c: r[c] for c in CAMPOS} if r['tem_dados'] else None
    g, origem = genero.do_item(r['id'], r['cat'], r['busca'], r['titulo'], manuais)
    auto = genero.classificar(r['cat'], r['busca'], r['titulo'])[0] if origem == 'manual' else g
    return {'id': r['id'], 'loja': r['loja'], 'item_id': r['item_id'], 'cat': r['cat'],
            'busca': r['busca'], 'url': r['url'], 'data': d, 'preco_em': r['preco_em'],
            'genero': g, 'genero_origem': origem, 'genero_auto': auto}


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


def so_existentes_do_lote(body):
    """"so_existentes" do POST /api/items: true faz o lote só atualizar itens que já existem.

    Ausente (ou corpo em lista) vale false. Qualquer valor que não seja true/false dá ErroCliente 400.
    """
    if not isinstance(body, dict) or 'so_existentes' not in body:
        return False
    if not isinstance(body['so_existentes'], bool):
        raise ErroCliente(400, 'so_existentes deve ser true ou false')
    return body['so_existentes']


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


_PRECO_MILHAR = re.compile(r'\d{1,3}(?:\.\d{3})+')
_PRECO_BR = re.compile(r'\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:,\d+)?|\d+\.\d{1,2}')


def ler_preco(texto):
    """Valor de um preço em texto ("R$ 1.299,90", "R$ 4.285", "R$ 69,90") como Decimal; None se vazio, ilegível ou <= 0.

    Formato brasileiro: ponto separa milhar e vírgula separa os centavos. Um ponto seguido de 1 ou 2 dígitos
    (sem vírgula) vale como decimal. Faixa ("R$ 10 - R$ 20") e qualquer outra forma dão None.
    """
    if texto is None or isinstance(texto, bool):
        return None
    t = re.sub(r'R\$|\s', '', str(texto))
    if not _PRECO_BR.fullmatch(t):
        return None
    if ',' in t:
        t = t.replace('.', '').replace(',', '.')
    elif _PRECO_MILHAR.fullmatch(t):
        t = t.replace('.', '')
    v = Decimal(t)
    return v if v > 0 else None


def preco_antigo_plausivel(preco, antigo):
    """False só quando os dois preços são legíveis e o antigo é LIMITE_PRECO_ANTIGO vezes o preço ou mais.

    Preço ou antigo vazio ou ilegível, ou antigo menor que o preço: plausível (nada a mexer).
    Só olha os dois valores; quem chama decide o que zerar (sanear_precos zera preco_antigo e desconto).
    """
    p, a = ler_preco(preco), ler_preco(antigo)
    if p is None or a is None:
        return True
    return a < p * LIMITE_PRECO_ANTIGO


def sanear_precos(vals):
    """Zera preco_antigo e desconto de vals (dict com os CAMPOS) quando o antigo é implausível. Devolve o mesmo dict.

    Vale para todo caminho que grava os dados de um item (upsert das coletas e PATCH com data do site).
    Só mexe nesses dois campos: a url e o resto seguem iguais.
    """
    if not preco_antigo_plausivel(vals.get('preco'), vals.get('preco_antigo')):
        vals['preco_antigo'] = vals['desconto'] = ''
    return vals


def preco_em_de(preco, quando):
    """preco_em de uma escrita com os dados do item: `quando` se o preço é legível (ler_preco), senão None.

    Uma regra só para o upsert e o PATCH com data (CA1 de docs/produto/planos/atualizar-precos.md).
    """
    return quando if ler_preco(preco) is not None else None


def upsert(con, it, inserir=True):
    """Insere ou atualiza um item. Mantém a categoria original se já existir.

    Devolve 'inserido', 'atualizado' ou, com inserir=False (lote que só atualiza, "so_existentes"),
    'ausente' quando o item não existe: nada é gravado. Com título, grava preco_em (preco_em_de).
    """
    loja = it.get('loja') or 'amazon'
    if loja not in LOJAS:
        raise ValueError('loja inválida (use amazon, ml ou shopee)')
    if loja == 'shopee' and not eh_link_shopee(it.get('url')):
        raise ValueError('url da Shopee precisa ser link de afiliado')
    item_id = it.get('item_id') or it['url']
    d = it.get('data') or {}
    vals = sanear_precos({c: (d.get(c) or '') for c in CAMPOS})
    tem = 1 if vals['titulo'] else 0
    quando = agora()
    preco_em = preco_em_de(vals['preco'], quando)
    cur = con.execute('SELECT id, tem_dados FROM items WHERE loja=? AND item_id=?', (loja, item_id)).fetchone()
    if not cur:
        if not inserir:
            return 'ausente'
        pos = con.execute('SELECT COALESCE(MAX(posicao),0)+1 FROM items').fetchone()[0]
        try:
            con.execute(f'''INSERT INTO items (loja,item_id,cat,busca,url,{','.join(CAMPOS)},tem_dados,posicao,criado_em,atualizado_em,preco_em)
                            VALUES (?,?,?,?,?,{','.join('?'*len(CAMPOS))},?,?,?,?,?)''',
                        [loja, item_id, it.get('cat') or 'Geral', it.get('busca') or '', it['url']]
                        + [vals[c] for c in CAMPOS] + [tem, pos, quando, quando, preco_em])
            return 'inserido'
        except sqlite3.IntegrityError:
            # outro POST gravou o mesmo loja+item_id entre o SELECT e o INSERT: vira atualização
            cur = con.execute('SELECT id, tem_dados FROM items WHERE loja=? AND item_id=?', (loja, item_id)).fetchone()
            if not cur:
                raise
    if tem:
        sets = ', '.join(f'{c}=?' for c in CAMPOS)
        # atualiza preços/dados, mas nunca troca um link de afiliado já gerado
        con.execute(f'''UPDATE items SET {sets}, tem_dados=1, atualizado_em=?, preco_em=?,
                        url=CASE WHEN {sql_link_preservado()} THEN url ELSE ? END
                        WHERE id=?''',
                    [vals[c] for c in CAMPOS] + [quando, preco_em, it['url'], cur['id']])
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


class LimiteDaLeitura(OSError):
    """Prazo total ou teto de bytes de uma leitura limitada estourado (é OSError: vira `falha_rede`)."""


class RedirecionamentoAmazon(urllib.request.HTTPRedirectHandler):
    """Confere cada redirect antes de segui-lo, não só a URL final.

    Pedido com `prazo_final` (leitura limitada, veja buscar_produto_amazon): o prazo passa ao pedido seguinte,
    redirect depois do prazo levanta LimiteDaLeitura e o salto seguinte espera no máximo o que resta. O urllib
    abre o salto seguinte com o `req.timeout` do pedido atual, por isso ele é encurtado aqui."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        conferir_url_amazon(newurl)
        novo = super().redirect_request(req, fp, code, msg, headers, newurl)
        prazo_final = getattr(req, 'prazo_final', None)
        if novo is not None and prazo_final is not None:
            restante = prazo_final - time.monotonic()
            if restante <= 0:
                raise LimiteDaLeitura('prazo total da leitura esgotado')
            novo.prazo_final = prazo_final
            if isinstance(req.timeout, (int, float)):
                req.timeout = min(req.timeout, restante)
        return novo


OPENER_AMAZON = urllib.request.build_opener(RedirecionamentoAmazon)
BLOCO_LEITURA = 64 * 1024


def _ler_limitado(r, prazo_final, teto_bytes):
    """Lê o corpo em blocos de até BLOCO_LEITURA com read1 (uma chamada de rede por bloco, então cada bloco espera
    no máximo o timeout da operação), conferindo o prazo antes de cada bloco e o total de bytes depois de cada um.
    Levanta LimiteDaLeitura ao estourar um dos dois.

    Conexão que fecha antes do Content-Length levanta IncompleteRead, como o read() faria: o read1 só devolve b''
    e deixa o que falta em `r.length`. Sem isso, uma página cortada antes do preço viraria `sem_preco` (descarte)
    e uma cortada antes do título, `bloqueado` (pausa), em vez de `falha_rede`. Na resposta em pedaços (chunked),
    o próprio read1 já levanta IncompleteRead."""
    partes, total = [], 0
    while True:
        if prazo_final is not None and time.monotonic() >= prazo_final:
            raise LimiteDaLeitura('prazo total da leitura esgotado')
        bloco = r.read1(BLOCO_LEITURA)
        if not bloco:
            faltam = getattr(r, 'length', None)
            if faltam:
                raise http.client.IncompleteRead(b''.join(partes), faltam)
            return b''.join(partes)
        total += len(bloco)
        if teto_bytes is not None and total > teto_bytes:
            raise LimiteDaLeitura('página maior que o teto')
        partes.append(bloco)


def buscar_produto_amazon(url, timeout=30, prazo_total=None, teto_bytes=None):
    """Lê uma página da Amazon; `timeout` vale para cada operação de rede. Sem `prazo_total` nem `teto_bytes` (o
    /api/fetch), lê a página inteira de uma vez, como sempre. Com eles (a releitura), a leitura inteira, redirects
    incluídos, tem prazo total, conferido a cada redirect e antes de cada bloco, e teto de bytes: estourado um dos
    dois, a resposta é fechada e sai LimiteDaLeitura (um OSError)."""
    conferir_url_amazon(url)
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept-Language': 'pt-BR,pt;q=0.9',
                                               'Accept': 'text/html,application/xhtml+xml'})
    prazo_final = None
    if prazo_total is not None:
        prazo_final = req.prazo_final = time.monotonic() + prazo_total
        timeout = min(timeout, prazo_total)
    with OPENER_AMAZON.open(req, timeout=timeout) as r:
        final = r.geturl()
        if prazo_total is None and teto_bytes is None:
            corpo = r.read()
        else:
            corpo = _ler_limitado(r, prazo_final, teto_bytes)
        h = corpo.decode('utf-8', 'ignore')
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
        # a tag <img> que tem id="landingImage", com o src antes ou depois do id (a Amazon põe antes)
        'imagem': _grab(r'<img(?=[^>]*\sid="landingImage")[^>]*\ssrc="([^"]*)"', h),
    }


# ---------- confirmação do preço de UMA oferta da Amazon (POST /api/v1/amazon/<ASIN>/confirmar-preco) ----------
# Plano "Rodar sozinho · Entrega 1" do Achadinho Turbo (docs/produto/planos/rodar-sozinho-entrega1.md, lá). O Turbo
# pede, logo antes de enviar, a releitura da página de um produto que já está no banco. A URL é montada aqui a partir
# do ASIN validado (nunca vem do cliente) e vai sem tag, para não parecer clique de afiliado.
RE_ASIN = re.compile(r'[A-Z0-9]{10}')
# Limites da releitura. O Turbo desiste em 15 s; normalmente a resposta sai em até uns 12 s: o prazo total mais uma
# operação que começou antes de ele vencer (8 + 4). Ficam de fora do prazo total, limitados só pelos 4 s de cada
# operação: a espera pelo cabeçalho de cada resposta, o descarte do corpo de um redirect (o urllib faz fp.read()) e
# a linha de tamanho de uma resposta em pedaços (chunked). A página da Amazon tem 1 a 2 MB. O /api/fetch segue sem
# prazo total nem teto, com 30 s por operação.
PRAZO_RELEITURA_S = 8                       # prazo total da leitura, redirects incluídos
PRAZO_OPERACAO_RELEITURA_S = 4              # timeout de cada operação de rede (conexão, cabeçalho, cada bloco)
TETO_RELEITURA_BYTES = 4 * 1024 * 1024      # acima disso a página é abandonada (falha_rede)
CAMPOS_DO_PRECO = ('preco', 'preco_antigo', 'desconto')   # os únicos CAMPOS que a releitura grava
ERRO_SEM_OFERTA = 'oferta da Amazon não encontrada'


def url_releitura_amazon(asin):
    return f'https://www.amazon.com.br/dp/{asin}'


def buscar_releitura_amazon(url, timeout):
    """O buscar_produto_amazon com o prazo total e o teto da releitura (lidos a cada chamada)."""
    return buscar_produto_amazon(url, timeout=timeout, prazo_total=PRAZO_RELEITURA_S,
                                 teto_bytes=TETO_RELEITURA_BYTES)


def _classificar_releitura(asin, buscar):
    """Lê a página e devolve (resultado, página ou None). Mesma classificação do atualizar_precos.py, com uma
    diferença: página não reconhecida (sem título ou sem ASIN) é `bloqueado`, nunca motivo de descarte.
    Prazo total ou teto de bytes estourado (LimiteDaLeitura, um OSError) é `falha_rede`."""
    try:
        r = buscar(url_releitura_amazon(asin), timeout=PRAZO_OPERACAO_RELEITURA_S)
    except URLRecusada:   # redirect para fora da Amazon
        return 'outro_produto', None
    except urllib.error.HTTPError as e:   # antes do URLError, que é a classe mãe
        e.close()
        if e.code in (429, 503):
            return 'bloqueado', None
        if e.code in (404, 410):
            return 'sem_preco', None
        return 'falha_rede', None
    except (OSError, http.client.HTTPException):   # URLError, timeout, conexão recusada ou cortada
        return 'falha_rede', None
    if r.get('captcha'):
        return 'bloqueado', None
    if not r.get('asin'):
        return 'bloqueado', None
    if r['asin'] != asin:
        return 'outro_produto', None
    if not r.get('titulo'):
        return 'bloqueado', None
    if ler_preco(r.get('preco')) is None:
        return 'sem_preco', None
    return 'confirmado', r


def _numero_do_preco(texto):
    v = ler_preco(texto)
    return float(v) if v is not None else None


def _resposta_confirmada(vals, quando):
    """Corpo do `confirmado` a partir do que foi gravado (já saneado): preço, antigo só se maior e desconto em %."""
    preco = _numero_do_preco(vals['preco'])
    antigo = _numero_do_preco(vals['preco_antigo'])
    if antigo is not None and antigo <= preco:
        antigo = None
    digitos = re.sub(r'\D', '', str(vals['desconto'] or ''), flags=re.A)[:3]
    pct = int(digitos) if digitos else None
    if not pct and antigo:
        pct = round((1 - preco / antigo) * 100)
    return {'resultado': 'confirmado', 'preco': preco, 'preco_antigo': antigo,
            'desconto_pct': pct if pct and 0 < pct < 100 else None, 'preco_em': quando}


def confirmar_preco_amazon(con, asin, buscar=buscar_releitura_amazon, agora=agora):
    """Relê a página do produto da Amazon `asin` e, com preço legível, grava só o preço (CA1.1 e CA1.2).

    Devolve o corpo da resposta (sem a versão): {"resultado": "confirmado", "preco", "preco_antigo",
    "desconto_pct", "preco_em"} ou {"resultado": "sem_preco" | "outro_produto" | "bloqueado" | "falha_rede"}.
    ASIN fora de RE_ASIN levanta ValueError; item da Amazon inexistente (antes da leitura ou apagado durante ela)
    levanta ErroCliente 404. Nos dois casos nada é lido nem gravado.

    A leitura de rede acontece fora de transação. Depois, em BEGIN IMMEDIATE, relê os CAMPOS da linha, aplica o
    sanear_precos sobre eles com o preço, o antigo e o desconto da página e grava só esses três mais preco_em e
    atualizado_em. Nunca insere, nunca mexe em url, título, cupom ou foto. Falha não grava nada (o preço velho
    e o preco_em ficam como estavam).
    """
    if not isinstance(asin, str) or not RE_ASIN.fullmatch(asin):
        raise ValueError('ASIN inválido')
    sql_linha = f"SELECT id, {', '.join(CAMPOS)} FROM items WHERE loja='amazon' AND item_id=?"
    if con.in_transaction:
        con.commit()
    if con.execute(sql_linha, (asin,)).fetchone() is None:
        raise ErroCliente(404, ERRO_SEM_OFERTA)
    resultado, pagina = _classificar_releitura(asin, buscar)
    if resultado != 'confirmado':
        return {'resultado': resultado}
    con.execute('BEGIN IMMEDIATE')
    try:
        atual = con.execute(sql_linha, (asin,)).fetchone()
        if atual is None:   # apagado entre a leitura e a gravação
            raise ErroCliente(404, ERRO_SEM_OFERTA)
        vals = sanear_precos({**{c: atual[c] for c in CAMPOS},
                              **{c: pagina.get(c) or '' for c in CAMPOS_DO_PRECO}})
        quando = agora()
        con.execute('UPDATE items SET preco=?, preco_antigo=?, desconto=?, preco_em=?, atualizado_em=? WHERE id=?',
                    [vals[c] for c in CAMPOS_DO_PRECO] + [quando, quando, atual['id']])
        con.commit()
    except BaseException:
        con.rollback()
        raise
    return _resposta_confirmada(vals, quando)


# Freio da releitura (P5 do plano): uma leitura por vez, FREIO_INTERVALO_S entre o início de duas, no máximo
# FREIO_TETO_POR_HORA numa janela deslizante de uma hora, FREIO_PAUSA_BLOQUEIO_S sem ler depois de um `bloqueado`
# e nenhuma leitura enquanto uma rodada da Amazon (coleta ou atualizar_precos.py) segura a trava.
FREIO_INTERVALO_S = 3
FREIO_TETO_POR_HORA = 60
FREIO_JANELA_S = 3600
FREIO_PAUSA_BLOQUEIO_S = 15 * 60
FREIO_ESPERA_RODADA_S = 60   # o Retry-After quando a rodada da Amazon está no ar (ela dura muito mais)


def rodada_amazon_livre():
    """True se nenhuma rodada da Amazon segura a trava agora. Pega a trava e a solta na hora: a releitura nunca
    a segura durante a leitura, então uma rodada pode começar no meio dela (a rodada tem prioridade). Na rara
    coincidência de a rodada tentar a trava nesses microssegundos, ela sai com 4 ("outra rodada de amazon está em
    andamento") e basta repeti-la. Trava que não abre (symlink, permissão) conta como ocupada: na dúvida, não lê."""
    try:
        with travar_rodada('amazon'):
            return True
    except RodadaEmAndamento:
        return False


class FreioReleitura:
    """Freio da rota de confirmação de preço, em memória (zera quando o servidor reinicia).

    `reservar()` devolve None e marca a leitura como em curso, ou (motivo, segundos) quando recusa: motivo
    'ocupado', 'pausa', 'intervalo', 'teto' ou 'rodada', e segundos inteiros >= 1 para o Retry-After. Recusa não
    conta como leitura. `liberar(resultado)` encerra a leitura reservada; `bloqueado` abre a pausa, contada a
    partir do fim da leitura. `relogio` (monotônico) e `rodada_livre` são injetáveis nos testes.
    """

    def __init__(self, relogio=time.monotonic, rodada_livre=rodada_amazon_livre):
        self._relogio, self._rodada_livre = relogio, rodada_livre
        self._lock = threading.Lock()
        self._ocupado = False
        self._inicios = collections.deque()
        self._pausa_ate = None

    @staticmethod
    def _segundos(s):
        return max(1, math.ceil(s))

    def reservar(self):
        with self._lock:
            t = self._relogio()
            if self._ocupado:
                return 'ocupado', FREIO_INTERVALO_S
            if self._pausa_ate is not None and t < self._pausa_ate:
                return 'pausa', self._segundos(self._pausa_ate - t)
            while self._inicios and self._inicios[0] <= t - FREIO_JANELA_S:
                self._inicios.popleft()
            if self._inicios and t - self._inicios[-1] < FREIO_INTERVALO_S:
                return 'intervalo', self._segundos(self._inicios[-1] + FREIO_INTERVALO_S - t)
            if len(self._inicios) >= FREIO_TETO_POR_HORA:
                return 'teto', self._segundos(self._inicios[0] + FREIO_JANELA_S - t)
            if not self._rodada_livre():
                return 'rodada', FREIO_ESPERA_RODADA_S
            self._ocupado = True
            self._inicios.append(t)
            return None

    def liberar(self, resultado=None):
        with self._lock:
            self._ocupado = False
            if resultado == 'bloqueado':
                self._pausa_ate = self._relogio() + FREIO_PAUSA_BLOQUEIO_S


FREIO_RELEITURA = FreioReleitura()
# Caminho da rota abaixo do prefixo da v1. O grupo é o ASIN cru; só vale se casar RE_ASIN (senão, 404).
RE_ROTA_CONFIRMAR = re.compile(r'amazon/([^/]*)/confirmar-preco')
ROTA_CONFIRMAR_LOG = 'amazon/(asin)/confirmar-preco'


def asin_da_rota_confirmar(caminho):
    """Para o caminho cru: None se não é a rota de confirmação; '' se é, mas o ASIN está fora do formato;
    senão, o ASIN."""
    p = prefixo_v1()
    if not caminho.startswith(p):
        return None
    m = RE_ROTA_CONFIRMAR.fullmatch(caminho[len(p):])
    if not m:
        return None
    return m.group(1) if RE_ASIN.fullmatch(m.group(1)) else ''


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

    Fica o método (se for um conhecido), a rota (se for ofertas ou categorias; a de confirmação de preço sem o
    ASIN, "amazon/(asin)/confirmar-preco"; senão "(outra rota)"), "?(omitida)" no lugar da query e a versão
    HTTP (se bem formada). Um ?token= mandado por engano, um token no caminho ou numa linha malformada nunca
    chegam ao log.
    """
    prefixo = prefixo_v1()
    partes = linha.split()
    metodo = partes[0] if partes and partes[0] in METODOS_HTTP else '?'
    alvo = next((p for p in partes if prefixo[:-1] in p), '')
    caminho, tem_query, _ = alvo.partition('?')
    if caminho in [prefixo + suf for suf in SUFIXOS_V1_LOG]:
        rota = caminho
    elif asin_da_rota_confirmar(caminho) is not None:
        rota = prefixo + ROTA_CONFIRMAR_LOG
    else:
        rota = prefixo + '(outra rota)'
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
        diferente de GET dá 405 (Allow: GET), só depois da autenticação. A exceção é a rota de confirmação
        de preço (asin_da_rota_confirmar), que só aceita POST (405 com Allow: POST). O token só vale no
        cabeçalho (?token= não autentica) e é comparado em tempo constante. A v1 nunca leva CORS.
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
        if asin_da_rota_confirmar(self._caminho) is not None:
            if self.command != 'POST':
                self.json({'error': 'método não permitido: esta rota só aceita POST'}, 405,
                          cabecalhos=[('Allow', 'POST')])
                return True
            return False
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
        (PRAGMA query_only): as rotas GET da v1 nunca gravam (a confirmação de preço tem conexão própria,
        em despachar_confirmar_preco). ErroApi vira {"error": msg} com o código; erro
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

    def despachar_confirmar_preco(self):
        """POST autenticado em /api/v1/amazon/<ASIN>/confirmar-preco. True se a rota era essa.

        O bloquear_v1() já conferiu navegador, token e método. Depois: ASIN fora do formato 404 → corpo não
        vazio 400 → item da Amazon inexistente 404 → freio 429 com Retry-After → leitura (200). É a única rota
        da v1 com conexão que grava (as outras ficam em query_only). Erro inesperado vira 500 com só o tipo no
        log, e a linha do log nunca traz o ASIN nem o token (linha_v1_para_log). A resposta nunca traz HTML nem
        a mensagem de uma exceção.
        """
        asin = asin_da_rota_confirmar(self._caminho)
        if asin is None:
            return False
        if not asin:
            self.json({'error': 'rota não encontrada'}, 404); return True
        # sem ler o corpo: a conexão é HTTP/1.0 e fecha depois da resposta
        tamanhos = self.headers.get_all('Content-Length') or []
        if self.headers.get('Transfer-Encoding') is not None or any(v.strip() != '0' for v in tamanhos):
            self.json({'error': 'esta rota não aceita corpo'}, 400); return True
        import api_ofertas
        con = None
        reservado = resultado = None
        try:
            con = conectar()
            if con.execute("SELECT 1 FROM items WHERE loja='amazon' AND item_id=?", (asin,)).fetchone() is None:
                raise ErroCliente(404, ERRO_SEM_OFERTA)
            freio = FREIO_RELEITURA.reservar()
            if freio is not None:
                motivo, segundos = freio
                self.json({'versao': api_ofertas.VERSAO, 'resultado': 'freio', 'motivo': motivo,
                           'tentar_em_s': segundos}, 429, cabecalhos=[('Retry-After', str(segundos))])
                return True
            reservado = True
            resposta = confirmar_preco_amazon(con, asin)
            resultado = resposta['resultado']
        except ErroCliente as e:
            self.json({'error': e.msg}, e.codigo)
        except Exception as e:   # noqa: BLE001  só o tipo no log: a mensagem do sqlite pode trazer dados
            self.log_message('"%s" confirmar preço falhou: %s', self.requestline, type(e).__name__)
            self.json({'error': 'erro interno na API v1'}, 500)
        else:
            self.json({'versao': api_ofertas.VERSAO, **resposta})
        finally:
            if reservado:
                FREIO_RELEITURA.liberar(resultado)
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
        if caminho == '/api/versao':
            # Fora de ROTAS_ML: o bloquear() já recusou Host estranho e origem que não é a local.
            if VERSAO is None:
                return self.json({'error': 'versão do código não registrada na subida'}, 503)
            return self.json(resposta_versao(VERSAO))
        if caminho == '/api/ml-sem-afiliado':
            con = conectar()
            rows = con.execute("SELECT id, url FROM items WHERE loja='ml' AND url NOT LIKE 'https://meli.la/%' ORDER BY id").fetchall()
            con.close()
            return self.json([dict(r) for r in rows])
        if caminho == '/api/items':
            import genero
            con = conectar()
            rows = con.execute('SELECT * FROM items ORDER BY posicao').fetchall()
            manuais = genero.manuais(con)
            con.close()
            return self.json([linha_para_item(r, manuais) for r in rows])
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
        if self.bloquear() or self.despachar_confirmar_preco() or self.despachar_disparo():
            return
        if self._caminho == '/api/items':
            try:
                body = self.corpo()
                so_existentes = so_existentes_do_lote(body)
                lista = itens_do_lote(body)
            except ErroCliente as e:
                return self.json({'error': e.msg}, e.codigo)
            con = conectar(); cont = {'inserido': 0, 'atualizado': 0, 'ausente': 0}
            try:
                for it in lista:
                    if it.get('url'):
                        cont[upsert(con, it, inserir=not so_existentes)] += 1
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
        m = ROTA_ITEM.match(self._caminho)
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
        iid = int(m.group(1))
        if iid > MAX_ID_SQLITE:
            return self.json({'error': 'item não encontrado'}, 404)
        con = conectar()
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
            vals = sanear_precos({c: (d.get(c) or '') for c in CAMPOS})   # mesma regra do preço antigo do upsert
            sets = ', '.join(f'{c}=?' for c in CAMPOS)
            quando = agora()
            con.execute(f'UPDATE items SET {sets}, tem_dados=1, atualizado_em=?, preco_em=? WHERE id=?',
                        [vals[c] for c in CAMPOS] + [quando, preco_em_de(vals['preco'], quando), iid])
        con.commit()
        import genero
        r = con.execute('SELECT * FROM items WHERE id=?', (iid,)).fetchone()
        manuais = genero.manuais(con); con.close()
        return self.json(linha_para_item(r, manuais) if r else None)

    def corrigir_genero(self, iid):
        """PUT /api/items/<id>/genero com {"genero": um de genero.GENEROS ou null}. null volta ao automático.

        Valor só em item de aba com gênero (senão 400); null apaga a correção em qualquer aba.

        Só grava a correção (generos_manuais) e, se ela mudou alguma linha, o atualizado_em do item, para o
        cursor da API v1 ver a mudança: url e os demais campos não mudam. As mensagens de erro não repetem o valor recebido.
        """
        import genero
        try:
            body = self.corpo()
            if not isinstance(body, dict) or set(body) != {'genero'}:
                raise ErroCliente(400, 'envie só {"genero": ...}: feminino, masculino, unissex, sem ou null')
            valor = body['genero']
            if valor is not None and not (isinstance(valor, str) and valor in genero.GENEROS):
                raise ErroCliente(400, 'genero deve ser feminino, masculino, unissex, sem ou null')
        except ErroCliente as e:
            return self.json({'error': e.msg}, e.codigo)
        if iid > MAX_ID_SQLITE:
            return self.json({'error': 'item não encontrado'}, 404)
        con = conectar()
        try:
            # leitura da aba e escrita na mesma transação: um DELETE no meio não deixa correção órfã
            con.execute('BEGIN IMMEDIATE')
            r = con.execute('SELECT cat FROM items WHERE id=?', (iid,)).fetchone()
            if r is None:
                con.rollback()
                return self.json({'error': 'item não encontrado'}, 404)
            # null (apagar a correção) vale em qualquer aba: a correção guardada de um item que saiu da aba
            # com gênero pode ser apagada; um valor só vale nas abas com gênero
            if valor is not None and r['cat'] not in genero.ABAS_COM_GENERO:
                con.rollback()
                return self.json({'error': 'esta categoria não separa por público'}, 400)
            quando = agora()
            mudancas = con.total_changes
            genero.definir_manual(con, iid, valor, quando)
            # null sem correção para apagar não muda nada: o item não reaparece no cursor da API v1
            if con.total_changes != mudancas:
                con.execute('UPDATE items SET atualizado_em=? WHERE id=?', (quando, iid))
            con.commit()
            r = con.execute('SELECT * FROM items WHERE id=?', (iid,)).fetchone()
            item = linha_para_item(r, genero.manuais(con))
        except Exception as e:   # noqa: BLE001  só o tipo no log: a mensagem do sqlite pode trazer dados
            if con.in_transaction:
                con.rollback()
            self.log_message('"%s" correção de gênero falhou: %s', self.requestline, type(e).__name__)
            return self.json({'error': 'erro interno ao salvar o público'}, 500)
        finally:
            con.close()
        return self.json(item)

    def do_PUT(self):
        if self.bloquear() or self.despachar_disparo():
            return
        m = ROTA_GENERO.match(self._caminho)
        if m:
            return self.corrigir_genero(int(m.group(1)))
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
        m = ROTA_ITEM.match(self._caminho)
        if not m:
            return self.json({'error': 'rota não encontrada'}, 404)
        import genero
        iid = int(m.group(1))
        if iid > MAX_ID_SQLITE:
            return self.json({'error': 'item não encontrado'}, 404)
        con = conectar()
        con.execute('DELETE FROM items WHERE id=?', (iid,))
        genero.definir_manual(con, iid, None, agora())   # apaga a correção do público junto (mesmo commit)
        con.commit(); con.close()
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
    print(registrar_versao(), flush=True)
    iniciar_api_v1()
    iniciar_disparo()
    try:
        servidor.serve_forever()
    finally:
        if AGENDADOR:
            AGENDADOR.parar()
