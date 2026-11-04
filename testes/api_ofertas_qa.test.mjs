// QA da API v1 com o cliente real do Achadinho Turbo: fetch do Node 22 (undici), seguindo `proximo`
// (docs/produto/planos/api-achadinho-turbo.md, CA1, CA4, CA8). Complementa testes/api_ofertas.test.mjs.
//
// Uso:  node --test testes/api_ofertas_qa.test.mjs
//
// O banco temporário é preparado por um script Python (esquema do servidor.criar_banco, itens com
// horário antigo e muitos empates de atualizado_em, para passarem da folga de 60 s); depois sobe o
// servidor.py como subprocesso, em porta livre, com o agendador desligado, proxies mortos e
// ACHADINHOS_API_TOKEN_ARQUIVO num diretório temporário. O token é gerado aqui e nunca é impresso. Só
// fala com 127.0.0.1 na porta de teste: não toca o achadinhos.db real, o servidor em 8765, o Achadinho
// Turbo nem a rede.
import { describe, test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { spawn, spawnSync } from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const RAIZ = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const TOTAL_BONS = 130;      // itens que passam no CA2
const TOTAL_RUINS = 20;      // itens que ficam de fora (ML sem meli.la, título com cara de link)

const SEMEAR = `
import os, sys
from datetime import datetime, timedelta
sys.path.insert(0, ${JSON.stringify(RAIZ)})
import servidor as S
S.criar_banco()
con = S.conectar()
velho = (datetime.now() - timedelta(hours=3)).isoformat(timespec='seconds')
mais_velho = (datetime.now() - timedelta(hours=5)).isoformat(timespec='seconds')
for n in range(${TOTAL_BONS}):
    loja = ('amazon', 'ml', 'shopee')[n % 3]
    url = {'amazon': 'https://www.amazon.com.br/dp/B0QA%05d?tag=desejodemen01-20' % n,
           'ml': 'https://meli.la/QA%dx' % n, 'shopee': 'https://s.shopee.com.br/QA%dx' % n}[loja]
    foto = {'amazon': 'https://m.media-amazon.com/images/I/qa%d.jpg' % n, 'ml': 'https://http2.mlstatic.com/D_qa%d.jpg' % n,
            'shopee': 'https://evil.example/qa%d.jpg' % n}[loja]
    quando = velho if n % 4 else mais_velho   # empates em dois horários
    con.execute("INSERT INTO items (loja,item_id,cat,busca,url,titulo,preco,preco_antigo,desconto,vendas,frete,imagem,"
                "tem_dados,posicao,criado_em,atualizado_em) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1,?,?,?)",
                (loja, 'QA%d' % n, 'Perfumes e Perfumaria' if n % 2 else 'Casa e Decoração', 'perfume', url,
                 'Produto QA %d' % n, 'R$ 100,00', 'R$ 150,00' if n % 5 else '', '-33%' if n % 5 else '',
                 'Mais de 1 mil compras', 'Frete grátis' if n % 2 else '', foto, n, quando, quando))
for n in range(${TOTAL_RUINS}):
    con.execute("INSERT INTO items (loja,item_id,cat,busca,url,titulo,preco,tem_dados,posicao,criado_em,atualizado_em) "
                "VALUES (?,?,?,?,?,?,?,1,?,?,?)",
                ('ml', 'RU%d' % n, 'Casa e Decoração', 'x',
                 'https://produto.mercadolivre.com.br/MLB-%d' % n if n % 2 else 'https://meli.la/RU%d' % n,
                 'Capinha i.Phone %d' % n if n % 2 == 0 else 'Produto comum %d' % n, 'R$ 10,00', n, velho, velho))
con.commit()
con.close()
`;

function portaLivre() {
  return new Promise((resolve, reject) => {
    const s = net.createServer();
    s.once('error', reject);
    s.listen(0, '127.0.0.1', () => { const { port } = s.address(); s.close(() => resolve(port)); });
  });
}

async function esperarPorta(porta, proc) {
  for (let i = 0; i < 100; i++) {
    if (proc.exitCode !== null) throw new Error('o servidor de teste saiu com código ' + proc.exitCode);
    const ok = await new Promise((resolve) => {
      const s = net.connect(porta, '127.0.0.1', () => { s.destroy(); resolve(true); });
      s.on('error', () => resolve(false));
    });
    if (ok) return;
    await new Promise((r) => setTimeout(r, 50));
  }
  throw new Error('o servidor de teste não subiu');
}

const srv = {};

before(async () => {
  srv.dir = fs.mkdtempSync(path.join(os.tmpdir(), 'achadinhos-api-qa-'));
  const db = path.join(srv.dir, 'teste.db');
  if (path.resolve(db) === path.resolve(RAIZ, 'achadinhos.db')) throw new Error('o teste tentou usar o banco real');
  srv.arquivoToken = path.join(srv.dir, 'api_token.txt');
  srv.token = crypto.randomBytes(32).toString('base64url');
  fs.writeFileSync(srv.arquivoToken, srv.token + '\n', { mode: 0o600 });
  srv.porta = await portaLivre();
  srv.base = `http://127.0.0.1:${srv.porta}`;
  srv.stderr = '';
  const morto = 'http://127.0.0.1:9';
  const env = { ...process.env, ACHADINHOS_DB: db, ACHADINHOS_PORTA: String(srv.porta), PYTHONDONTWRITEBYTECODE: '1',
    ACHADINHOS_API_TOKEN_ARQUIVO: srv.arquivoToken, ACHADINHOS_DISPARO: '0',
    http_proxy: morto, https_proxy: morto, ftp_proxy: morto, no_proxy: '' };
  const semeou = spawnSync('python3', ['-c', SEMEAR], { cwd: RAIZ, env, encoding: 'utf8' });
  assert.equal(semeou.status, 0, 'não consegui preparar o banco temporário: ' + semeou.stderr.slice(-300));
  srv.proc = spawn('python3', ['-u', 'servidor.py'], { cwd: RAIZ, stdio: ['ignore', 'ignore', 'pipe'], env });
  srv.proc.stderr.setEncoding('utf8');
  srv.proc.stderr.on('data', (t) => { srv.stderr += t; });
  await esperarPorta(srv.porta, srv.proc);
});

after(async () => {
  const proc = srv.proc;
  if (proc && proc.exitCode === null) {
    let prazo;
    const saiu = new Promise((r) => proc.once('exit', r));
    proc.kill('SIGTERM');
    await Promise.race([saiu, new Promise((r) => { prazo = setTimeout(r, 5000); })]);
    clearTimeout(prazo);
    if (proc.exitCode === null && proc.signalCode === null) proc.kill('SIGKILL');
  }
  if (srv.dir) fs.rmSync(srv.dir, { recursive: true, force: true });
});

/** fetch real, só para o servidor de teste, como o Turbo faria. */
function pedir(caminho, init = {}) {
  const url = new URL(caminho, srv.base);
  if (url.origin !== srv.base) throw new Error('o teste só fala com o servidor de teste');
  return fetch(url, { signal: AbortSignal.timeout(15000), ...init });
}

const auth = () => ({ headers: { authorization: `Bearer ${srv.token}` } });

async function json(caminho) {
  const r = await pedir(caminho, auth());
  assert.equal(r.status, 200, caminho);
  return r.json();
}

/** Segue `proximo` até a página vazia, como o consumidor do Turbo. `codificar` testa o cursor cru e o codificado. */
async function seguir(query, codificar = true) {
  const ofertas = [];
  const totais = new Set();
  let cursor = null;
  let paginas = 0;
  for (; paginas < 100;) {
    const extra = cursor === null ? '' : '&cursor=' + (codificar ? encodeURIComponent(cursor) : cursor);
    const j = await json(`/api/v1/ofertas?${query}${extra}`);
    paginas += 1;
    totais.add(j.total);
    if (j.ofertas.length === 0) {
      assert.equal(j.proximo, null, 'página vazia tem proximo null');
      break;
    }
    ofertas.push(...j.ofertas);
    cursor = j.proximo;
    assert.equal(typeof cursor, 'string');
  }
  return { ofertas, totais, paginas };
}

describe('seguir o proximo com o fetch do Node 22 (CA4, CA8)', () => {
  test('percorre as ofertas do filtro uma vez só, com cursor codificado e com cursor cru', async () => {
    for (const codificar of [true, false]) {
      const { ofertas, totais, paginas } = await seguir('limite=50', codificar);
      assert.equal(ofertas.length, TOTAL_BONS, `codificar=${codificar}`);
      assert.equal(new Set(ofertas.map((o) => o.id)).size, TOTAL_BONS, 'oferta repetida');
      assert.deepEqual([...totais], [TOTAL_BONS]);
      assert.equal(paginas, Math.ceil(TOTAL_BONS / 50) + 1);
      const chaves = ofertas.map((o) => [o.atualizado_em, o.id]);
      const ordenadas = [...chaves].sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : a[1] - b[1]));
      assert.deepEqual(chaves, ordenadas, 'ordem (atualizado_em, id)');
    }
  });

  test('com limite 1 e muitos empates não pula nem repete ninguém', async () => {
    const { ofertas } = await seguir('limite=1&cat=' + encodeURIComponent('Perfumes e Perfumaria'));
    assert.equal(ofertas.length, TOTAL_BONS / 2);
    assert.equal(new Set(ofertas.map((o) => o.id)).size, TOTAL_BONS / 2);
  });

  test('os itens barrados pelo CA2 não aparecem nem na contagem', async () => {
    const todas = (await seguir('limite=200')).ofertas;
    assert.ok(todas.every((o) => !o.item_id.startsWith('RU')), 'item que deveria ficar fora saiu');
    const cats = await json('/api/v1/categorias');
    assert.equal(cats.total, TOTAL_BONS);
    assert.equal(cats.categorias.reduce((s, c) => s + c.total, 0), TOTAL_BONS);
    assert.ok(cats.categorias.every((c) => c.total === c.lojas.amazon + c.lojas.ml + c.lojas.shopee));
  });

  test('ordem por deslocamento: as páginas juntas dão a lista inteira e a foto fora do CDN vira null', async () => {
    const vistos = [];
    let cursor = null;
    for (let i = 0; i < 10; i++) {
      const j = await json('/api/v1/ofertas?ordem=menor_preco&limite=60' + (cursor ? '&cursor=' + cursor : ''));
      vistos.push(...j.ofertas);
      cursor = j.proximo;
      if (cursor === null) break;
    }
    assert.equal(vistos.length, TOTAL_BONS);
    assert.equal(new Set(vistos.map((o) => o.id)).size, TOTAL_BONS);
    for (const o of vistos.filter((x) => x.loja === 'shopee')) assert.equal(o.imagem, null);
    for (const o of vistos.filter((x) => x.loja !== 'shopee')) assert.equal(typeof o.imagem, 'string');
  });
});

describe('a oferta no formato que o Turbo consome (guia de encaixe do plano)', () => {
  test('cada campo tem o tipo que o renderTemplate espera', async () => {
    const { ofertas } = await seguir('limite=200');
    for (const o of ofertas) {
      // mapeamento do plano: title←titulo, price←preco, oldPrice←preco_antigo, discountPct←desconto_pct,
      // sold←vendas, freeShipping←frete_gratis, coupon←cupom, image←imagem, key←chave
      const turbo = { key: o.chave, url: o.link, title: o.titulo, price: o.preco, oldPrice: o.preco_antigo,
        coupon: o.cupom, discountPct: o.desconto_pct, sold: o.vendas, freeShipping: o.frete_gratis, image: o.imagem };
      assert.match(turbo.key, /^(amazon|ml|shopee):\S+$/);
      assert.match(turbo.url, /^https:\/\/(www\.amazon\.com\.br\/dp\/|meli\.la\/|s\.shopee\.com\.br\/)/);
      assert.equal(typeof turbo.title, 'string');
      assert.ok(Number.isFinite(turbo.price) && turbo.price > 0);
      assert.ok(turbo.oldPrice === null || (Number.isFinite(turbo.oldPrice) && turbo.oldPrice > turbo.price));
      assert.ok(Number.isInteger(turbo.discountPct) && turbo.discountPct >= 0 && turbo.discountPct <= 99);
      assert.ok(Number.isInteger(turbo.sold) && turbo.sold >= 0);
      assert.equal(typeof turbo.freeShipping, 'boolean');
      assert.equal(typeof turbo.coupon, 'string');
      // desconto_pct 0 apagaria o desconto no template do Turbo (discountPct ?? ...): com preco_antigo ele tem de vir > 0
      if (turbo.oldPrice !== null) assert.ok(turbo.discountPct > 0, o.chave);
      assert.ok(turbo.image === null || typeof turbo.image === 'string');
    }
  });
});

describe('uso repetido e simultâneo, como o agendador do Turbo', () => {
  test('30 pedidos em sequência pela mesma instância do fetch (o servidor fecha a conexão a cada resposta)', async () => {
    for (let i = 0; i < 30; i++) {
      const r = await pedir(i % 2 ? '/api/v1/categorias' : '/api/v1/ofertas?limite=5', auth());
      assert.equal(r.status, 200, `pedido ${i}`);
      await r.arrayBuffer();
    }
  });

  test('4 pedidos simultâneos, várias rodadas, sempre 200 com JSON inteiro', async () => {
    for (let rodada = 0; rodada < 5; rodada++) {
      // Cada pedido lê o corpo assim que chega. Pedir os 4 e ler os corpos depois deixa o socket dos outros com o corpo
      // parado quando o servidor fecha a conexão, e o undici do Node 22 dispara um assert interno (`!this.paused`)
      // com resposta acima de ~64 KB (reproduz contra um http.createServer qualquer: não é defeito do servidor.py).
      await Promise.all([0, 1, 2, 3].map(async (n) => {
        const r = await pedir(['/api/v1/categorias', '/api/v1/ofertas?limite=200', '/api/v1/ofertas?ordem=desconto&limite=50',
          '/api/v1/ofertas?q=produto&limite=10'][n], auth());
        assert.equal(r.status, 200);
        const j = await r.json();
        assert.equal(j.versao, 1);
      }));
    }
  });

  test('o cliente sem token, com token errado ou com Origin nunca recebe oferta, e o log não traz o token', async () => {
    const outro = crypto.randomBytes(32).toString('base64url');
    for (const init of [{}, { headers: { authorization: `Bearer ${outro}` } }]) {
      const r = await pedir('/api/v1/ofertas', init);
      assert.equal(r.status, 401);
      assert.ok(!(await r.text()).includes('"ofertas"'));
    }
    // fetch do Node não deixa forçar Origin; um http.request cru faz o papel do navegador
    const http = await import('node:http');
    const status = await new Promise((resolve, reject) => {
      const req = http.request({ host: '127.0.0.1', port: srv.porta, path: '/api/v1/ofertas', agent: false,
        headers: { Host: `localhost:${srv.porta}`, Origin: `http://localhost:${srv.porta}`,
          authorization: `Bearer ${srv.token}` } }, (res) => { res.resume(); res.on('end', () => resolve(res.statusCode)); });
      req.on('error', reject);
      req.end();
    });
    assert.equal(status, 403);
    await new Promise((r) => setTimeout(r, 100));
    assert.ok(!srv.stderr.includes(srv.token), 'o token apareceu no log do servidor');
    assert.ok(!/Traceback/.test(srv.stderr), 'o servidor imprimiu um erro');
  });
});
