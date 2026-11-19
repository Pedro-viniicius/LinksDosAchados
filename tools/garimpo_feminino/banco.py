"""Banco próprio do garimpo feminino (garimpo.db): esquema, gravação de página com checkpoint e trava da rodada.

Plano: docs/produto/planos/garimpo-feminino-shopee.md, etapa 2 (CA4 e CA9).

- Nunca abre o achadinhos.db. O `abrir` recusa banco com tabelas e sem `user_version`, ou com versão maior
  que a deste módulo (o achadinhos.db está na v3), e nada muda nele.
- `PRAGMA user_version = 1`, criado de uma vez. Mudança futura só aditiva.
- `gravar_pagina` grava, numa só transação `BEGIN IMMEDIATE`, a requisição, os produtos, as fontes e o
  checkpoint (`consultas.ultima_pagina`). Se a rodada cair no meio, nada da página fica: a retomada refaz
  no máximo a página em curso.
- Dedupe por `item_id`: o `first_seen` fica; o `last_seen`, o `raw_json` e os campos que vieram na resposta
  são atualizados (campo ausente ou ilegível mantém o valor anterior).
- Nó sem itemId válido é pulado, sem recusar a página: `n_nos` da requisição guarda o que a API devolveu e
  `vistos` da consulta só os gravados, então a diferença conta os pulados (`nos_sem_id` conta numa página).
- Texto da API pode trazer surrogate solto (`\\ud83d` sem o par), que o json aceita e o sqlite3 recusa: nas colunas
  ele vira `?` e no `raw_json` fica como escape (JSON em ASCII).
- `travar(pasta)`: flock exclusivo, sem espera, em <pasta>/garimpo.lock. Outra rodada → `ErroConfig` (saída 2).
- Nenhuma mensagem de erro daqui traz conteúdo da API nem valores gravados: só textos fixos.
"""
import contextlib
import errno
import fcntl
import json
import math
import os
import re
import sqlite3
import stat
import time

VERSAO = 1
NOME_TRAVA = 'garimpo.lock'
TIMEOUT_BANCO = 5   # segundos de espera pela trava de escrita do SQLite

STATUS = ('pendente', 'esgotada', 'teto', 'saturada', 'erro')
STATUS_FINAIS = ('esgotada', 'teto', 'saturada')
CAMPOS_REQ = ('em', 'operacao', 'http', 'codigo', 'ms', 'bytes', 'n_nos')

MAX_ID = 2 ** 63 - 1
RE_OPERACAO = re.compile(r'[A-Za-z][A-Za-z0-9_]{0,59}', re.A)
RE_DATA = re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}', re.A)
RE_DECIMAL = re.compile(r'\d{1,15}(\.\d{1,10})?', re.A)

ESQUEMA = (
    """CREATE TABLE products (
        item_id TEXT PRIMARY KEY,
        shop_id TEXT,
        nome TEXT,
        product_link TEXT,
        offer_link TEXT,
        image_url TEXT,
        price_min REAL,
        price_max REAL,
        price_discount_rate REAL,
        sales INTEGER,
        rating_star REAL,
        commission_rate REAL,
        seller_commission_rate REAL,
        shopee_commission_rate REAL,
        commission REAL,
        cat_l1 TEXT,
        cat_l2 TEXT,
        cat_l3 TEXT,
        shop_name TEXT,
        shop_type TEXT,
        period_start INTEGER,
        period_end INTEGER,
        raw_json TEXT NOT NULL,
        first_seen TEXT NOT NULL,
        last_seen TEXT NOT NULL,
        foco_score INTEGER,
        foco TEXT CHECK (foco IN ('alto', 'medio', 'neutro', 'descartado'))
    )""",
    'CREATE INDEX products_cat_l3 ON products (cat_l3)',
    'CREATE INDEX products_shop ON products (shop_id)',
    """CREATE TABLE consultas (
        id INTEGER PRIMARY KEY,
        chave TEXT NOT NULL UNIQUE,
        fase TEXT NOT NULL,
        estrategia TEXT,
        cat_id TEXT,
        ultima_pagina INTEGER NOT NULL DEFAULT 0 CHECK (ultima_pagina >= 0),
        status TEXT NOT NULL DEFAULT 'pendente'
            CHECK (status IN ('pendente', 'esgotada', 'teto', 'saturada', 'erro')),
        vistos INTEGER NOT NULL DEFAULT 0,
        novos INTEGER NOT NULL DEFAULT 0,
        criada_em TEXT NOT NULL,
        atualizada_em TEXT NOT NULL,
        concluida_em TEXT
    )""",
    'CREATE INDEX consultas_cat ON consultas (cat_id, status)',
    """CREATE TABLE product_sources (
        item_id TEXT NOT NULL REFERENCES products (item_id),
        consulta_id INTEGER NOT NULL REFERENCES consultas (id),
        pagina INTEGER NOT NULL,
        posicao INTEGER NOT NULL,
        visto_em TEXT NOT NULL,
        PRIMARY KEY (item_id, consulta_id)
    )""",
    'CREATE INDEX product_sources_consulta ON product_sources (consulta_id)',
    """CREATE TABLE categories (
        cat_id TEXT PRIMARY KEY,
        nivel INTEGER CHECK (nivel IN (1, 2, 3)),
        pai TEXT,
        nome TEXT,
        nome_origem TEXT CHECK (nome_origem IN ('datafeed', 'titulos', 'manual')),
        classe TEXT CHECK (classe IN ('feminina', 'mista', 'fora')),
        nicho TEXT,
        frequencia INTEGER NOT NULL DEFAULT 0,
        saturada INTEGER NOT NULL DEFAULT 0 CHECK (saturada IN (0, 1)),
        bateu_teto INTEGER NOT NULL DEFAULT 0 CHECK (bateu_teto IN (0, 1)),
        parada TEXT
    )""",
    """CREATE TABLE shops (
        shop_id TEXT PRIMARY KEY,
        nome TEXT,
        tipo TEXT,
        itens_femininos INTEGER NOT NULL DEFAULT 0,
        catalogo_feito INTEGER NOT NULL DEFAULT 0 CHECK (catalogo_feito IN (0, 1))
    )""",
    """CREATE TABLE campaigns (
        id TEXT PRIMARY KEY,
        nome TEXT,
        commission_rate REAL,
        period_start INTEGER,
        period_end INTEGER,
        raw_json TEXT
    )""",
    """CREATE TABLE requisicoes (
        id INTEGER PRIMARY KEY,
        consulta_id INTEGER REFERENCES consultas (id),
        pagina INTEGER,
        em TEXT NOT NULL,
        operacao TEXT NOT NULL,
        http INTEGER,
        codigo INTEGER,
        ms INTEGER,
        bytes INTEGER,
        n_nos INTEGER,
        novos INTEGER
    )""",
    'CREATE INDEX requisicoes_consulta ON requisicoes (consulta_id, pagina)',
    """CREATE TABLE medicoes (
        id INTEGER PRIMARY KEY,
        nome TEXT NOT NULL,
        valor_json TEXT NOT NULL,
        em TEXT NOT NULL
    )""",
    """CREATE TABLE test_links (
        id INTEGER PRIMARY KEY,
        item_id TEXT NOT NULL,
        short_link TEXT NOT NULL,
        sub_ids TEXT NOT NULL,
        lote TEXT,
        criado_em TEXT NOT NULL,
        dono_ok INTEGER NOT NULL DEFAULT 0 CHECK (dono_ok IN (0, 1))
    )""",
    """CREATE TABLE conversoes (
        chave TEXT PRIMARY KEY,
        relatorio TEXT NOT NULL,
        purchase_time INTEGER,
        item_id TEXT,
        shop_id TEXT,
        sub_ids TEXT,
        comissao REAL,
        status TEXT
    )""",
)
TABELAS = ('products', 'product_sources', 'categories', 'shops', 'campaigns', 'consultas', 'requisicoes',
           'medicoes', 'test_links', 'conversoes')

# Colunas de `products` que vêm do nó do productOfferV2, na ordem de `_linha_produto`.
COLUNAS_NO = ('item_id', 'shop_id', 'nome', 'product_link', 'offer_link', 'image_url', 'price_min', 'price_max',
              'price_discount_rate', 'sales', 'rating_star', 'commission_rate', 'seller_commission_rate',
              'shopee_commission_rate', 'commission', 'cat_l1', 'cat_l2', 'cat_l3', 'shop_name', 'shop_type',
              'period_start', 'period_end')
SQL_PRODUTO = (
    f"INSERT INTO products ({', '.join(COLUNAS_NO)}, raw_json, first_seen, last_seen) "
    f"VALUES ({', '.join('?' * (len(COLUNAS_NO) + 3))}) "
    'ON CONFLICT (item_id) DO UPDATE SET '
    + ', '.join(f'{c} = COALESCE(excluded.{c}, {c})' for c in COLUNAS_NO[1:])
    + ', raw_json = excluded.raw_json, last_seen = excluded.last_seen'
)
SQL_FONTE = (
    'INSERT INTO product_sources (item_id, consulta_id, pagina, posicao, visto_em) VALUES (?, ?, ?, ?, ?) '
    'ON CONFLICT (item_id, consulta_id) DO UPDATE SET visto_em = excluded.visto_em'
)
SQL_REQUISICAO = (
    'INSERT INTO requisicoes (consulta_id, pagina, em, operacao, http, codigo, ms, bytes, n_nos, novos) '
    'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)'
)


class ErroConfig(Exception):
    """Configuração ou estado local que impede a rodada (saída 2). A mensagem é sempre texto fixo."""


def agora():
    return time.strftime('%Y-%m-%dT%H:%M:%S')


# ---------- conversões dos campos do nó (tipos conferidos; o resto vira None) ----------
def _eh_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _id(v):
    """Int64 da API (número ou texto só de dígitos) → texto canônico, sem zeros à esquerda; o resto → None."""
    if _eh_int(v):
        n = v
    elif isinstance(v, str) and re.fullmatch(r'\d{1,19}', v, re.A):
        n = int(v)
    else:
        return None
    return str(n) if 0 < n <= MAX_ID else None


def _real(v):
    """Preço ou taxa (número, ou texto decimal como "0.12") → float finito e não negativo; o resto → None."""
    if isinstance(v, str) and RE_DECIMAL.fullmatch(v.strip()):
        return float(v)
    if _eh_int(v) and 0 <= v < 10 ** 15 or isinstance(v, float) and math.isfinite(v) and v >= 0:
        return float(v)
    return None


def _inteiro(v):
    """Contagem ou instante (número ou texto de dígitos) → int; o resto → None."""
    if _eh_int(v) and 0 <= v <= MAX_ID:
        return v
    if isinstance(v, str) and re.fullmatch(r'\d{1,18}', v, re.A):
        return int(v)
    return None


def sem_surrogates(v):
    """Texto que o sqlite3 e o UTF-8 aceitam: surrogate solto vira `?`."""
    return v.encode('utf-8', 'replace').decode('utf-8')


def _texto(v, teto):
    """Só texto: surrogate solto vira `?`, caracteres de controle viram espaço, os espaços se juntam e o texto é
    cortado no teto."""
    if not isinstance(v, str):
        return None
    v = sem_surrogates(v)
    v = ' '.join(''.join(' ' if ord(c) < 32 or 0x7f <= ord(c) <= 0x9f else c for c in v).split())[:teto]
    return v or None


def _tipo_loja(v):
    """shopType: lista de inteiros (JSON compacto), inteiro ou texto curto; o resto → None."""
    if isinstance(v, list) and v and all(_eh_int(x) and 0 <= x <= MAX_ID for x in v):
        return json.dumps(v, separators=(',', ':'))
    if _eh_int(v) and 0 <= v <= MAX_ID:
        return str(v)
    return _texto(v, 60)


def _categorias(v):
    """productCatIds [L1, L2, L3] → três ids (None onde faltar ou for ilegível)."""
    ids = [_id(x) for x in v[:3]] if isinstance(v, list) else []
    return tuple(ids + [None] * (3 - len(ids)))


def _no_valido(no):
    return isinstance(no, dict) and _id(no.get('itemId')) is not None


def nos_sem_id(nos):
    """Quantos nós da página o `gravar_pagina` pula por não terem itemId válido."""
    return sum(1 for no in nos if not _no_valido(no))


def _linha_produto(no):
    """Nó do productOfferV2 → valores na ordem de COLUNAS_NO + raw_json. Sem itemId válido → ValueError."""
    if not _no_valido(no):
        raise ValueError('nó de produto sem itemId válido')
    item_id = _id(no.get('itemId'))
    raw = json.dumps(no, ensure_ascii=True, sort_keys=True, separators=(',', ':'))
    return (item_id, _id(no.get('shopId')), _texto(no.get('productName'), 1000),
            _texto(no.get('productLink'), 2000), _texto(no.get('offerLink'), 2000),
            _texto(no.get('imageUrl'), 2000), _real(no.get('priceMin')), _real(no.get('priceMax')),
            _real(no.get('priceDiscountRate')), _inteiro(no.get('sales')), _real(no.get('ratingStar')),
            _real(no.get('commissionRate')), _real(no.get('sellerCommissionRate')),
            _real(no.get('shopeeCommissionRate')), _real(no.get('commission')),
            *_categorias(no.get('productCatIds')), _texto(no.get('shopName'), 300),
            _tipo_loja(no.get('shopType')), _inteiro(no.get('periodStartTime')),
            _inteiro(no.get('periodEndTime')), raw)


def _requisicao(req):
    """Confere o registro da requisição: só as chaves de CAMPOS_REQ (nunca cabeçalho, corpo ou Authorization)."""
    if not isinstance(req, dict) or any(not isinstance(k, str) or k not in CAMPOS_REQ for k in req):
        raise ValueError('registro de requisição com campo não permitido')
    operacao = req.get('operacao')
    if not isinstance(operacao, str) or not RE_OPERACAO.fullmatch(operacao):
        raise ValueError('registro de requisição sem operação válida')
    em = req.get('em')
    if em is None:
        em = agora()
    elif (_eh_int(em) or isinstance(em, float)) and math.isfinite(em) and 0 <= em < 10 ** 11:
        em = time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(em))
    elif not (isinstance(em, str) and RE_DATA.fullmatch(em)):
        raise ValueError('registro de requisição com data inválida')
    numeros = {}
    for campo in ('http', 'codigo', 'ms', 'bytes', 'n_nos'):
        v = req.get(campo)
        if v is not None and not (_eh_int(v) and -MAX_ID <= v <= MAX_ID):
            raise ValueError('registro de requisição com número inválido')
        numeros[campo] = v
    return {'em': em, 'operacao': operacao, **numeros}


def _pagina_ou_id(v, nome):
    if not _eh_int(v) or v < 1:
        raise ValueError(f'{nome} tem de ser inteiro >= 1')
    return v


# ---------- conexão, esquema e transação ----------
@contextlib.contextmanager
def _transacao(con):
    """BEGIN IMMEDIATE … COMMIT. Qualquer exceção (inclusive Ctrl+C) desfaz tudo e segue adiante."""
    if con.in_transaction:
        raise ValueError('já existe uma transação aberta nesta conexão')
    con.execute('BEGIN IMMEDIATE')
    try:
        yield
        con.execute('COMMIT')
    except BaseException:
        if con.in_transaction:
            con.execute('ROLLBACK')
        raise


def _tabelas(con):
    return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def _criar_esquema(con):
    with _transacao(con):
        versao = con.execute('PRAGMA user_version').fetchone()[0]
        if versao == VERSAO:      # outro processo criou entre a leitura e a trava
            return
        if versao != 0 or _tabelas(con):
            raise ErroConfig('o banco indicado não é um garimpo.db (tem outras tabelas); nada foi alterado')
        for comando in ESQUEMA:
            con.execute(comando)
        con.execute(f'PRAGMA user_version = {VERSAO}')


def abrir(caminho):
    """Abre (e cria, na 1ª vez) o garimpo.db. Arquivo novo nasce com modo 0600.

    Recusa com ErroConfig, sem alterar nada: arquivo que não é SQLite, banco com tabelas e sem user_version
    (ex.: um banco qualquer), user_version maior que VERSAO (ex.: o achadinhos.db) e banco v1 incompleto.
    """
    if not os.path.lexists(caminho):
        try:
            os.close(os.open(caminho, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600))
        except FileExistsError:
            pass
        except OSError:
            raise ErroConfig('não consegui criar o garimpo.db na pasta indicada') from None
    try:
        con = sqlite3.connect(caminho, timeout=TIMEOUT_BANCO, isolation_level=None)
    except sqlite3.Error:
        raise ErroConfig('não consegui abrir o garimpo.db') from None
    try:
        try:
            versao = con.execute('PRAGMA user_version').fetchone()[0]
            if versao > VERSAO or versao == 0 and _tabelas(con):
                raise ErroConfig('o banco indicado não é um garimpo.db (versão ou tabelas de outro banco); '
                                 'nada foi alterado')
            con.execute('PRAGMA foreign_keys = ON')
            con.execute('PRAGMA journal_mode = WAL')
            con.execute('PRAGMA synchronous = FULL')
            if versao == 0:
                _criar_esquema(con)
            elif not set(TABELAS) <= _tabelas(con):
                raise ErroConfig('o garimpo.db está incompleto (faltam tabelas da versão 1)')
        except sqlite3.DatabaseError:
            raise ErroConfig('o arquivo indicado não é um banco SQLite legível') from None
        return con
    except BaseException:
        con.close()
        raise


@contextlib.contextmanager
def travar(pasta):
    """flock exclusivo e sem espera em <pasta>/garimpo.lock, enquanto durar o bloco.

    Outra rodada com a trava → ErroConfig (saída 2). A trava some com o processo (kill -9 não deixa trava
    velha). O arquivo tem de ser comum, do próprio usuário; symlink é recusado.
    """
    caminho = os.path.join(pasta, NOME_TRAVA)
    try:
        fd = os.open(caminho, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, 0o600)
    except OSError:
        raise ErroConfig('não consegui abrir a trava do garimpo (garimpo.lock)') from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise ErroConfig('a trava do garimpo (garimpo.lock) não é um arquivo comum do seu usuário')
        if stat.S_IMODE(info.st_mode) != 0o600:
            os.fchmod(fd, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            if e.errno in (errno.EWOULDBLOCK, errno.EAGAIN):
                raise ErroConfig('outra rodada do garimpo está em andamento (garimpo.lock); '
                                 'espere ela terminar') from None
            raise ErroConfig('não consegui travar o garimpo (garimpo.lock)') from None
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


# ---------- checkpoint ----------
def chave_consulta(operacao, variaveis):
    """Operação + variáveis canônicas sem `page` (chaves ordenadas, JSON compacto). Mesma busca → mesma chave."""
    if not isinstance(operacao, str) or not RE_OPERACAO.fullmatch(operacao):
        raise ValueError('operação inválida')
    if not isinstance(variaveis, dict) or not all(isinstance(k, str) for k in variaveis):
        raise ValueError('variáveis da consulta fora do formato')
    sem_pagina = {k: v for k, v in variaveis.items() if k != 'page'}
    try:
        texto = json.dumps(sem_pagina, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    except (TypeError, ValueError):
        raise ValueError('variáveis da consulta fora do formato') from None
    return f'{operacao} {texto}'


def obter_consulta(con, operacao, variaveis, *, fase, estrategia=None, cat_id=None):
    """Cria a consulta (se for nova) e devolve o checkpoint: {id, ultima_pagina, status, vistos, novos}.

    A retomada continua de `ultima_pagina + 1`. Consulta que já existe mantém fase, estratégia e categoria
    da 1ª vez.
    """
    chave = chave_consulta(operacao, variaveis)
    if not isinstance(fase, str) or not RE_OPERACAO.fullmatch(fase):
        raise ValueError('fase inválida')
    estrategia = None if estrategia is None else str(estrategia)[:60]
    if cat_id is not None:
        cat_id = _id(cat_id)
        if cat_id is None:
            raise ValueError('cat_id inválido')
    with _transacao(con):
        quando = agora()
        con.execute('INSERT INTO consultas (chave, fase, estrategia, cat_id, criada_em, atualizada_em) '
                    'VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (chave) DO NOTHING',
                    (chave, fase, estrategia, cat_id, quando, quando))
        linha = con.execute('SELECT id, ultima_pagina, status, vistos, novos FROM consultas WHERE chave = ?',
                            (chave,)).fetchone()
    return dict(zip(('id', 'ultima_pagina', 'status', 'vistos', 'novos'), linha))


def fechar_consulta(con, consulta_id, status):
    """Marca a consulta como esgotada, teto, saturada ou erro. Só `erro` aceita página nova depois."""
    _pagina_ou_id(consulta_id, 'consulta_id')
    if status not in STATUS or status == 'pendente':
        raise ValueError('status de encerramento inválido')
    with _transacao(con):
        quando = agora()
        cur = con.execute('UPDATE consultas SET status = ?, atualizada_em = ?, concluida_em = ? WHERE id = ?',
                          (status, quando, quando if status in STATUS_FINAIS else None, consulta_id))
        if cur.rowcount != 1:
            raise ValueError('consulta inexistente')


def registrar_requisicao(con, consulta_id, pagina, req):
    """Grava, sozinha, uma requisição que não trouxe página (limite 10030/429, erro, sonda). Devolve o id."""
    if consulta_id is not None:
        _pagina_ou_id(consulta_id, 'consulta_id')
    if pagina is not None:
        _pagina_ou_id(pagina, 'pagina')
    r = _requisicao(req)
    with _transacao(con):
        cur = con.execute(SQL_REQUISICAO, (consulta_id, pagina, r['em'], r['operacao'], r['http'], r['codigo'],
                                           r['ms'], r['bytes'], r['n_nos'], None))
    return cur.lastrowid


def gravar_pagina(con, consulta_id, pagina, nos, req):
    """Grava uma página numa só transação e devolve quantos produtos eram novos no banco.

    Na mesma transação: a linha de `requisicoes` (com `n_nos` = len(nos) e `novos`), os produtos (dedupe por
    item_id), as fontes (`product_sources`, 1ª página e posição em que o item apareceu na consulta) e o
    checkpoint (`ultima_pagina`, `vistos`, `novos`). Exceção em qualquer ponto → nada da página fica.

    Nó sem itemId válido é pulado: não entra em products nem em `vistos`, mas conta em `n_nos`. A posição na
    fonte é a da página.

    Recusa (ValueError, sem gravar): consulta inexistente ou encerrada, página <= `ultima_pagina` (já gravada)
    e registro de requisição com campo fora de CAMPOS_REQ.
    """
    _pagina_ou_id(consulta_id, 'consulta_id')
    _pagina_ou_id(pagina, 'pagina')
    if not isinstance(nos, (list, tuple)):
        raise ValueError('os nós da página têm de vir numa lista')
    r = _requisicao(req)
    linhas = [(posicao, _linha_produto(no)) for posicao, no in enumerate(nos, 1) if _no_valido(no)]
    em = r['em']
    novos = 0
    with _transacao(con):
        consulta = con.execute('SELECT ultima_pagina, status FROM consultas WHERE id = ?', (consulta_id,)).fetchone()
        if consulta is None:
            raise ValueError('consulta inexistente')
        if consulta[1] in STATUS_FINAIS:
            raise ValueError('consulta já encerrada')
        if pagina <= consulta[0]:
            raise ValueError('página já gravada nesta consulta')
        for posicao, linha in linhas:
            item_id = linha[0]
            if con.execute('SELECT 1 FROM products WHERE item_id = ?', (item_id,)).fetchone() is None:
                novos += 1
            con.execute(SQL_PRODUTO, linha + (em, em))
            con.execute(SQL_FONTE, (item_id, consulta_id, pagina, posicao, em))
        con.execute(SQL_REQUISICAO, (consulta_id, pagina, em, r['operacao'], r['http'], r['codigo'], r['ms'],
                                     r['bytes'], len(nos), novos))
        con.execute("UPDATE consultas SET ultima_pagina = ?, vistos = vistos + ?, novos = novos + ?, "
                    "status = 'pendente', atualizada_em = ? WHERE id = ?",
                    (pagina, len(linhas), novos, em, consulta_id))
    return novos
