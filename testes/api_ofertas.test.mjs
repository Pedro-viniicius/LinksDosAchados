// Teste da API v1 com o cliente real do Achadinho Turbo: fetch do Node 22 (undici)
// (docs/produto/planos/api-achadinho-turbo.md, etapa 2, CA8).
//
// Uso:  node --test testes/api_ofertas.test.mjs
//
// Sobe o servidor.py como subprocesso com banco temporário, porta livre, agendador do disparo desligado,
// proxies mortos e ACHADINHOS_API_TOKEN_ARQUIVO num diretório temporário. O token é gerado aqui e nunca é
// impresso (as asserções que o envolvem usam mensagem fixa). Só fala com 127.0.0.1 na porta de teste: não
// toca o achadinhos.db real, o servidor em 8765, o Achadinho Turbo nem a rede.
import { describe, test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import http from 'node:http';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const RAIZ = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const LINK = 'https://www.amazon.com.br/dp/B0TESTE001?tag=desejodemen01-20';
const CAT = 'Perfumes e Perfumaria';

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

/** POST /api/items como o index.html faria (Origin local), por node:http: só para preparar o banco. */
function postarItem(porta, item) {
  return new Promise((resolve, reject) => {
    const corpo = Buffer.from(JSON.stringify({ items: [item] }));
    const req = http.request({ host: '127.0.0.1', port: porta, path: '/api/items', method: 'POST', agent: false,
      headers: { Host: `localhost:${porta}`, Origin: `http://localhost:${porta}`, 'Content-Type': 'application/json',
        'Content-Length': corpo.length } }, (res) => {
      res.resume();
      res.on('end', () => resolve(res.statusCode));
    });
    req.on('error', reject);
    req.end(corpo);
  });
}

const srv = {};

before(async () => {
  srv.dir = fs.mkdtempSync(path.join(os.tmpdir(), 'achadinhos-api-v1-'));
  const db = path.join(srv.dir, 'teste.db');
  if (path.resolve(db) === path.resolve(RAIZ, 'achadinhos.db')) throw new Error('o teste tentou usar o banco real');
  srv.arquivoToken = path.join(srv.dir, 'api_token.txt');
  srv.token = crypto.randomBytes(32).toString('base64url');   // 43 caracteres de [A-Za-z0-9_-]
  fs.writeFileSync(srv.arquivoToken, srv.token + '\n', { mode: 0o600 });
  srv.porta = await portaLivre();
  srv.base = `http://127.0.0.1:${srv.porta}`;
  srv.stderr = '';
  const morto = 'http://127.0.0.1:9';
  const env = { ...process.env, ACHADINHOS_DB: db, ACHADINHOS_PORTA: String(srv.porta), PYTHONDONTWRITEBYTECODE: '1',
    ACHADINHOS_API_TOKEN_ARQUIVO: srv.arquivoToken, ACHADINHOS_DISPARO: '0',
    http_proxy: morto, https_proxy: morto, ftp_proxy: morto, no_proxy: '' };
  srv.proc = spawn('python3', ['-u', 'servidor.py'], { cwd: RAIZ, stdio: ['ignore', 'ignore', 'pipe'], env });
  srv.proc.stderr.setEncoding('utf8');
  srv.proc.stderr.on('data', (t) => { srv.stderr += t; });
  await esperarPorta(srv.porta, srv.proc);
  const st = await postarItem(srv.porta, {
    loja: 'amazon', item_id: 'B0TESTE001', cat: CAT, busca: 'perfume', url: LINK,
    data: { titulo: 'Perfume Teste 100ml', preco: 'R$ 100,00', preco_antigo: 'R$ 150,00', frete: 'Frete GRÁTIS',
      imagem: 'https://m.media-amazon.com/images/I/71teste.jpg' },
  });
  assert.equal(st, 200, 'não consegui preparar o banco temporário');
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

/** fetch real, só para o servidor de teste. */
function pedir(caminho, init = {}) {
  const url = new URL(caminho, srv.base);
  if (url.origin !== srv.base) throw new Error('o teste só fala com o servidor de teste');
  return fetch(url, init);
}

const comToken = () => ({ headers: { Authorization: `Bearer ${srv.token}` } });

function semCors(r) {
  const cors = [...r.headers.keys()].filter((k) => k.startsWith('access-control-'));
  assert.deepEqual(cors, [], 'resposta da v1 com cabeçalho de CORS');
}

describe('API v1 com o fetch do Node 22 (CA8)', () => {
  test('a versão do Node é 22 ou maior e o fetch é o nativo', () => {
    assert.ok(Number(process.versions.node.split('.')[0]) >= 22, 'precisa do Node 22+');
    assert.equal(typeof globalThis.fetch, 'function');
  });

  test('GET /api/v1/categorias com Bearer em 127.0.0.1 responde 200 no formato do plano', async () => {
    const r = await pedir('/api/v1/categorias', comToken());
    assert.equal(r.status, 200);
    assert.equal(r.headers.get('content-type'), 'application/json; charset=utf-8');
    semCors(r);
    assert.deepEqual(await r.json(), {
      versao: 1, total: 1,
      categorias: [{ nome: CAT, total: 1, lojas: { amazon: 1, ml: 0, shopee: 0 } }],
    });
  });

  test('GET /api/v1/ofertas com Bearer traz a oferta com o link de afiliado', async () => {
    // o item acabou de ser gravado: na ordem padrão (atualizacao) fica na folga de 60 s
    const r = await pedir('/api/v1/ofertas?ordem=relevancia&cat=' + encodeURIComponent(CAT), comToken());
    assert.equal(r.status, 200);
    semCors(r);
    const j = await r.json();
    assert.equal(j.versao, 1);
    assert.equal(j.total, 1);
    assert.equal(j.proximo, null);
    assert.equal(j.ofertas[0].chave, 'amazon:B0TESTE001');
    assert.equal(j.ofertas[0].link, LINK);
    assert.equal(j.ofertas[0].preco, 100);
    assert.equal(j.ofertas[0].frete_gratis, true);
  });

  test('parâmetro inválido dá 400 com mensagem em português', async () => {
    const r = await pedir('/api/v1/ofertas?limite=0', comToken());
    assert.equal(r.status, 400);
    assert.match((await r.json()).error, /limite deve ser um número inteiro/);
  });

  test('sem token, com token errado ou com ?token= dá 401 com WWW-Authenticate: Bearer', async () => {
    const outro = crypto.randomBytes(32).toString('base64url');
    for (const [caminho, init] of [
      ['/api/v1/categorias', {}],
      ['/api/v1/categorias', { headers: { Authorization: `Bearer ${outro}` } }],
      [`/api/v1/categorias?token=${srv.token}`, {}],
    ]) {
      const r = await pedir(caminho, init);
      assert.equal(r.status, 401, caminho.split('?')[0]);
      assert.equal(r.headers.get('www-authenticate'), 'Bearer');
      semCors(r);
      assert.ok(!(await r.text()).includes(srv.token), 'o token voltou na resposta');
    }
  });

  test('POST com token dá 405; a mesma chamada sem token dá 401', async () => {
    let r = await pedir('/api/v1/ofertas', { method: 'POST', body: '{}',
      headers: { Authorization: `Bearer ${srv.token}` } });
    assert.equal(r.status, 405);
    await r.arrayBuffer();
    r = await pedir('/api/v1/ofertas', { method: 'POST', body: '{}' });
    assert.equal(r.status, 401);
    await r.arrayBuffer();
  });

  test('o token não aparece no log do servidor', async () => {
    await new Promise((r) => setTimeout(r, 100));
    assert.match(srv.stderr, /API v1 ligada/);
    assert.match(srv.stderr, /"GET \/api\/v1\/categorias HTTP\/1\.1" 200/);
    assert.ok(!srv.stderr.includes(srv.token), 'o token apareceu no log do servidor');
  });
});
