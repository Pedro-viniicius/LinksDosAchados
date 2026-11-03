#!/usr/bin/env python3
"""Servidor local do site de mensagens de achadinhos.

Guarda tudo em achadinhos.db (SQLite) e serve o site em http://localhost:8765/
Uso:  python3 servidor.py
"""
import json, re, sqlite3, html, os, urllib.request, urllib.parse
from datetime import datetime
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, 'achadinhos.db')
PORT = 8765
TAG_AMAZON = 'desejodemen01-20'
CAMPOS = ['titulo', 'preco', 'preco_antigo', 'desconto', 'avaliacao', 'num_avaliacoes',
          'vendas', 'frete', 'cupom', 'imagem']
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
      loja TEXT NOT NULL,            -- amazon | ml
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
    con.commit(); con.close()


def agora():
    return datetime.now().isoformat(timespec='seconds')


def linha_para_item(r):
    d = {c: r[c] for c in CAMPOS} if r['tem_dados'] else None
    return {'id': r['id'], 'loja': r['loja'], 'item_id': r['item_id'], 'cat': r['cat'],
            'busca': r['busca'], 'url': r['url'], 'data': d}


def upsert(con, it):
    """Insere ou atualiza um item. Mantém a categoria original se já existir."""
    loja = it.get('loja') or 'amazon'
    item_id = it.get('item_id') or it['url']
    d = it.get('data') or {}
    vals = {c: (d.get(c) or '') for c in CAMPOS}
    tem = 1 if vals['titulo'] else 0
    cur = con.execute('SELECT id, tem_dados FROM items WHERE loja=? AND item_id=?', (loja, item_id)).fetchone()
    if cur:
        if tem:
            sets = ', '.join(f'{c}=?' for c in CAMPOS)
            # atualiza preços/dados, mas nunca troca um link de afiliado já gerado
            con.execute(f'''UPDATE items SET {sets}, tem_dados=1, atualizado_em=?,
                            url=CASE WHEN url LIKE 'https://meli.la/%' OR url LIKE '%tag={TAG_AMAZON}%' THEN url ELSE ? END
                            WHERE id=?''',
                        [vals[c] for c in CAMPOS] + [agora(), it['url'], cur['id']])
        return 'atualizado'
    pos = con.execute('SELECT COALESCE(MAX(posicao),0)+1 FROM items').fetchone()[0]
    con.execute(f'''INSERT INTO items (loja,item_id,cat,busca,url,{','.join(CAMPOS)},tem_dados,posicao,criado_em,atualizado_em)
                    VALUES (?,?,?,?,?,{','.join('?'*len(CAMPOS))},?,?,?,?)''',
                [loja, item_id, it.get('cat') or 'Geral', it.get('busca') or '', it['url']]
                + [vals[c] for c in CAMPOS] + [tem, pos, agora(), agora()])
    return 'inserido'


# ---------- coleta de um produto da Amazon (mesma lógica do amazon.php) ----------
def _grab(rx, txt, i=1):
    m = re.search(rx, txt, re.S)
    return html.unescape(re.sub(r'<[^>]+>', '', m.group(i))).strip() if m else ''


def buscar_produto_amazon(url):
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept-Language': 'pt-BR,pt;q=0.9',
                                               'Accept': 'text/html,application/xhtml+xml'})
    with urllib.request.urlopen(req, timeout=30) as r:
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


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=BASE, **kw)

    def log_message(self, fmt, *args):
        if '/api/' in (args[0] if args else ''):
            super().log_message(fmt, *args)

    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PATCH, PUT, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Access-Control-Allow-Private-Network', 'true')
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()

    def json(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(b)))
        self.end_headers(); self.wfile.write(b)

    def corpo(self):
        n = int(self.headers.get('Content-Length') or 0)
        return json.loads(self.rfile.read(n) or b'{}')

    def do_OPTIONS(self):
        self.send_response(204); self.end_headers()

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = dict(urllib.parse.parse_qsl(u.query))
        if u.path in ('/', '/index.html'):
            self.path = '/index.html'; return super().do_GET()
        if u.path == '/api/ml-sem-afiliado':
            con = conectar()
            rows = con.execute("SELECT id, url FROM items WHERE loja='ml' AND url NOT LIKE 'https://meli.la/%' ORDER BY id").fetchall()
            con.close()
            return self.json([dict(r) for r in rows])
        if u.path == '/api/items':
            con = conectar()
            rows = con.execute('SELECT * FROM items ORDER BY posicao').fetchall()
            con.close()
            return self.json([linha_para_item(r) for r in rows])
        if u.path.startswith('/api/config/'):
            con = conectar()
            r = con.execute('SELECT valor FROM config WHERE chave=?', (u.path.split('/')[-1],)).fetchone()
            con.close()
            return self.json(json.loads(r['valor']) if r else None)
        if u.path == '/api/fetch':
            try:
                return self.json(buscar_produto_amazon(q.get('url', '')))
            except Exception as e:
                return self.json({'error': str(e)})
        if u.path.startswith('/api/'):
            return self.json({'error': 'rota não encontrada'}, 404)
        return super().do_GET()

    def do_POST(self):
        if self.path == '/api/items':
            body = self.corpo()
            lista = body.get('items', body if isinstance(body, list) else [])
            con = conectar(); cont = {'inserido': 0, 'atualizado': 0}
            for it in lista:
                if it.get('url'):
                    cont[upsert(con, it)] += 1
            con.commit()
            total = con.execute('SELECT COUNT(*) FROM items').fetchone()[0]
            con.close()
            return self.json({**cont, 'total': total})
        return self.json({'error': 'rota não encontrada'}, 404)

    def do_PATCH(self):
        m = re.match(r'^/api/items/(\d+)$', self.path)
        if not m:
            return self.json({'error': 'rota não encontrada'}, 404)
        body = self.corpo(); con = conectar(); iid = int(m.group(1))
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
        if self.path.startswith('/api/config/'):
            con = conectar()
            con.execute('INSERT OR REPLACE INTO config VALUES (?,?)',
                        (self.path.split('/')[-1], json.dumps(self.corpo(), ensure_ascii=False)))
            con.commit(); con.close()
            return self.json({'ok': True})
        return self.json({'error': 'rota não encontrada'}, 404)

    def do_DELETE(self):
        m = re.match(r'^/api/items/(\d+)$', self.path)
        if not m:
            return self.json({'error': 'rota não encontrada'}, 404)
        con = conectar(); con.execute('DELETE FROM items WHERE id=?', (int(m.group(1)),)); con.commit(); con.close()
        return self.json({'ok': True})


if __name__ == '__main__':
    criar_banco()
    print(f'Site em http://localhost:{PORT}/  (banco: {DB})')
    ThreadingHTTPServer(('127.0.0.1', PORT), Handler).serve_forever()
