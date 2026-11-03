// Testes de QA do coletar_ml.js (CA11 a CA17 de docs/produto/planos/eletronicos-e-coleta-ml.md).
// Complementa testes/coletar_ml.test.mjs (do dev) sem repetir o que ele já prova.
//
// Uso:  node --test testes/coletar_ml_qa.test.mjs
//
// Como no arquivo do dev: o coletar_ml.js é carregado em node:vm, o ML de verdade nunca é acessado
// (a página vem de HTML gerado aqui) e a integração sobe o servidor.py com banco temporário e porta livre,
// com proxies mortos no ambiente. O "navegador" da integração é node:http com a Origin do ML e, para
// POST/PATCH, o preflight CORS que o Chrome faria antes (fetchChrome).
import { describe, test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import http from 'node:http';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const RAIZ = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const FONTE = fs.readFileSync(path.join(RAIZ, 'coletar_ml.js'), 'utf8');
const BUSCAS_JSON = JSON.parse(fs.readFileSync(path.join(RAIZ, 'buscas.json'), 'utf8'));
const LISTA = 'https://lista.mercadolivre.com.br';
const WWW = 'https://www.mercadolivre.com.br';
const SERVIDOR = 'http://localhost:8765';
const BF = 'Black Friday | Eletrônicos';
const TODOS_TERMOS = Object.entries(BUSCAS_JSON).flatMap(([cat, ts]) => ts.map((t) => [t, cat]));

const js = (v) => JSON.parse(JSON.stringify(v));
const produto = (n) => `https://produto.mercadolivre.com.br/MLB-${n}`;
const mlbDe = (url) => { const m = /MLB-?(\d{6,})/.exec(String(url)); return m ? 'MLB' + m[1] : null; };

// ------------------------------------------------------------------ apoio
function memoria(inicial = {}) {
  const m = new Map(Object.entries(inicial));
  return {
    escritas: 0,
    getItem(k) { return m.has(k) ? m.get(k) : null; },
    setItem(k, v) { this.escritas++; m.set(k, String(v)); },
    removeItem(k) { this.escritas++; m.delete(k); },
    lista(k) { return m.has(k) ? JSON.parse(m.get(k)) : null; },
  };
}

/** Carrega o coletar_ml.js num contexto vm (como colar no console). `extras` entra no contexto. */
function carregar({ origem = LISTA, caminho, fetch, localStorage = memoria(), extras = {}, aleatorio } = {}) {
  const mensagens = [];
  const registrar = (tipo) => (...a) => mensagens.push({ tipo, texto: a.map(String).join(' ') });
  const ctx = {
    console: { log: registrar('log'), warn: registrar('warn'), error: registrar('error') },
    setTimeout, clearTimeout, AbortController, localStorage,
    fetch: fetch || (async () => { throw new Error('fetch global não devia ser chamado'); }),
    ...extras,
  };
  // na aba do linkbuilder o pathname existe sempre: a guarda de afiliar() olha origin e pathname
  if (origem !== null) ctx.location = { origin: origem, pathname: caminho === undefined ? (origem === WWW ? '/afiliados/linkbuilder' : '/') : caminho };
  vm.createContext(ctx);
  if (aleatorio !== undefined) {
    ctx.__aleatorio = aleatorio;
    vm.runInContext('Math.random = () => globalThis.__aleatorio;', ctx);
  }
  vm.runInContext(FONTE, ctx, { filename: 'coletar_ml.js' });
  return { ctx, ML: ctx.ColetaML, mensagens, localStorage };
}

function resposta(status, corpo, url) {
  const texto = typeof corpo === 'string' ? corpo : JSON.stringify(corpo);
  return { ok: status >= 200 && status < 300, status, url, text: async () => texto, json: async () => JSON.parse(texto) };
}

/** Relógio que anota os atrasos pedidos. Atrasos de 30000 ou mais (prazos) só disparam se estiverem em `estourar`. */
function relogio({ estourar = [] } = {}) {
  const pedidos = [];
  const st = (fn, ms, ...a) => {
    pedidos.push(ms);
    if (ms >= 30000) return estourar.includes(ms) ? setTimeout(fn, 1, ...a) : { fake: true };
    return setTimeout(fn, 0, ...a);
  };
  const pausas = () => pedidos.filter((ms) => ms < 30000);
  return { st, pedidos, pausas };
}

/** Polycard sintético; `n` dá o MLB (6000000000 + n). */
function polycard(n, { titulo = `Produto ${n}`, valor = 100 + n, anterior } = {}) {
  const preco = { current_price: { value: valor } };
  if (anterior !== undefined) preco.previous_price = { value: anterior, previous: true };
  return { id: 'POLYCARD', polycard: { metadata: { id: 'MLB' + (6000000000 + n) },
    pictures: { pictures: [{ id: `${900000 + n}-MLB1_0${n}` }] },
    components: [{ type: 'title', title: { text: titulo } }, { type: 'price', price: preco }] } };
}

/** Página de busca com o literal .q("...") escapado como o ML faz (\' e \x3C). */
function pagina(cards) {
  const interno = JSON.stringify({ results: cards });
  const literal = JSON.stringify(interno).replace(/'/g, "\\'").replace(/</g, '\\x3C');
  return `<!DOCTYPE html><html><body><script>_n.ctx.s["x"].q(${literal});</script></body></html>`;
}

/** fetch falso: '/slug' é o ML (página de `paginaDe(slug)`), o resto vai para `servidor`. */
function fetchFalso({ paginaDe = () => pagina([polycard(1), polycard(2), polycard(3)]), urlFinal, statusML = 200, servidor } = {}) {
  const chamadas = [];
  const f = async (url, init = {}) => {
    chamadas.push({ url: String(url), init });
    if (String(url).startsWith('/')) return resposta(statusML, paginaDe(String(url).slice(1)), urlFinal || LISTA + url);
    const r = servidor ? await servidor(url, init)
      : { status: 200, corpo: { inserido: JSON.parse(init.body).items.length, atualizado: 0, total: 1 } };
    return resposta(r.status, r.corpo, String(url));
  };
  return { f, chamadas, doML: () => chamadas.filter((c) => c.url.startsWith('/')),
    doServidor: () => chamadas.filter((c) => !c.url.startsWith('/')) };
}

// ------------------------------------------------------------------ servidor.py + "navegador"
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

/** fetch por node:http com Origin do ML e Sec-Fetch-Site cross-site. Só fala com `porta` em localhost. */
function fetchNode(porta, origem = LISTA) {
  return (url, init = {}) => new Promise((resolve, reject) => {
    const u = new URL(url);
    if (!['localhost', '127.0.0.1'].includes(u.hostname) || u.port !== String(porta)) {
      reject(new Error('o adaptador só fala com o servidor de teste: ' + url));
      return;
    }
    const corpo = init.body === undefined ? null : Buffer.from(init.body);
    const headers = { ...(init.headers || {}), Host: u.host, Origin: origem, 'Sec-Fetch-Site': 'cross-site' };
    if (corpo) headers['Content-Length'] = corpo.length;
    const req = http.request({ host: '127.0.0.1', port: porta, path: u.pathname + u.search,
      method: init.method || 'GET', headers, agent: false }, (res) => {
      const partes = [];
      res.on('data', (c) => partes.push(c));
      res.on('end', () => {
        const texto = Buffer.concat(partes).toString('utf8');
        resolve({ ok: res.statusCode >= 200 && res.statusCode < 300, status: res.statusCode, url: String(url),
          headers: res.headers, text: async () => texto, json: async () => JSON.parse(texto) });
      });
    });
    req.setTimeout(10000, () => req.destroy(new Error('o servidor de teste não respondeu')));
    req.on('error', reject);
    if (corpo) req.write(corpo);
    req.end();
  });
}

/**
 * Faz o que o Chrome faria: antes de POST/PATCH (ou de qualquer cabeçalho fora do básico) manda o preflight
 * OPTIONS e só segue se a resposta liberar método e cabeçalhos. Anota cada requisição em `registro`.
 */
function fetchChrome(porta, origem, registro) {
  const cru = fetchNode(porta, origem);
  const seguros = new Set(['accept', 'accept-language', 'content-language']);
  return async (url, init = {}) => {
    const metodo = init.method || 'GET';
    const nomes = Object.keys(init.headers || {}).map((h) => h.toLowerCase());
    const entrada = { metodo, caminho: new URL(url).pathname, cabecalhos: nomes, credentials: init.credentials,
      referrerPolicy: init.referrerPolicy, preflight: null };
    registro.push(entrada);
    const simples = ['GET', 'HEAD'].includes(metodo) && nomes.every((n) => seguros.has(n));
    if (!simples) {
      const pre = await cru(url, { method: 'OPTIONS', headers: {
        'Access-Control-Request-Method': metodo,
        'Access-Control-Request-Headers': nomes.join(','),
        'Access-Control-Request-Private-Network': 'true' } });
      const metodos = String(pre.headers['access-control-allow-methods'] || '').toUpperCase().split(/\s*,\s*/);
      const cabs = String(pre.headers['access-control-allow-headers'] || '').toLowerCase().split(/\s*,\s*/);
      entrada.preflight = pre.status >= 200 && pre.status < 300
        && pre.headers['access-control-allow-origin'] === origem
        && metodos.includes(metodo) && nomes.every((n) => cabs.includes(n))
        && pre.headers['access-control-allow-private-network'] === 'true';
      if (!entrada.preflight) throw new TypeError('Failed to fetch (preflight recusado)');
    }
    const r = await cru(url, init);
    entrada.status = r.status;
    return r;
  };
}

function usarServidor() {
  const s = {};
  before(async () => {
    s.dir = fs.mkdtempSync(path.join(os.tmpdir(), 'achadinhos-mlqa-'));
    const db = path.join(s.dir, 'teste.db');
    if (path.resolve(db) === path.resolve(RAIZ, 'achadinhos.db')) throw new Error('o teste tentou usar o banco real');
    s.porta = await portaLivre();
    s.servidor = `http://localhost:${s.porta}`;
    const morto = 'http://127.0.0.1:9';
    s.proc = spawn('python3', ['-u', 'servidor.py'], {
      cwd: RAIZ, stdio: ['ignore', 'ignore', 'pipe'],
      env: { ...process.env, ACHADINHOS_DB: db, ACHADINHOS_PORTA: String(s.porta), PYTHONDONTWRITEBYTECODE: '1',
        http_proxy: morto, https_proxy: morto, ftp_proxy: morto, no_proxy: '' },
    });
    s.proc.stderr.resume();
    await esperarPorta(s.porta, s.proc);
  });
  after(async () => {
    const proc = s.proc;
    if (proc && proc.exitCode === null) {
      let prazo;
      const saiu = new Promise((r) => proc.once('exit', r));
      proc.kill('SIGTERM');
      await Promise.race([saiu, new Promise((r) => { prazo = setTimeout(r, 5000); })]);
      clearTimeout(prazo);
      if (proc.exitCode === null && proc.signalCode === null) proc.kill('SIGKILL');
    }
    if (s.dir) fs.rmSync(s.dir, { recursive: true, force: true });
  });
  return s;
}

/** Servidor em memória só com as três rotas do afiliar(); `gancho(metodo, caminho, db)` pode responder no lugar. */
function servidorMem(itens, gancho) {
  const db = new Map(itens.map((i) => [i.id, { ...i }]));
  const chamadas = [];
  const f = async (url, init = {}) => {
    const u = new URL(url);
    const metodo = init.method || 'GET';
    chamadas.push({ url: String(url), metodo, init });
    const custom = gancho && gancho(metodo, u.pathname, db, init);
    if (custom) return resposta(custom.status, custom.corpo, String(url));
    if (metodo === 'GET' && u.pathname === '/api/ml-sem-afiliado') {
      return resposta(200, [...db.values()].filter((i) => i.loja === 'ml' && !i.url.startsWith('https://meli.la/'))
        .map(({ id, url: x }) => ({ id, url: x })), String(url));
    }
    if (metodo === 'GET' && u.pathname === '/api/items') return resposta(200, [...db.values()], String(url));
    const m = /^\/api\/items\/(\d+)$/.exec(u.pathname);
    if (metodo === 'PATCH' && m) {
      const it = db.get(Number(m[1]));
      if (!it) return resposta(200, null, String(url));
      it.url = JSON.parse(init.body).url;
      return resposta(200, it, String(url));
    }
    return resposta(404, { error: 'rota não encontrada' }, String(url));
  };
  return { f, db, chamadas, patches: () => chamadas.filter((c) => c.metodo === 'PATCH') };
}

const itensMl = (n, base = 4100000000) => Array.from({ length: n }, (_, i) => ({ id: i + 1, loja: 'ml', url: produto(base + i + 1) }));

/** Linkbuilder falso que devolve link meli.la para todo MLB pedido, em ordem invertida e com a url canônica -_JM. */
function gerarTodos(pedidos = []) {
  return async (urls) => {
    pedidos.push([...urls]);
    return { urls: [...urls].reverse().map((u) => ({ origin_url: `${u}-produto-_JM`, short_url: `https://meli.la/${mlbDe(u)}`, created: true })) };
  };
}

// ================================================================== CA11: arquivo e guarda de origem
describe('QA CA11: o arquivo colado e a guarda de origem', () => {
  test('carregar num contexto vazio (aba em branco, sem location, localStorage, fetch ou document) não lança', () => {
    const ctx = { console: { log() {}, warn() {}, error() {} } };
    vm.createContext(ctx);
    assert.doesNotThrow(() => vm.runInContext(FONTE, ctx));
    assert.deepEqual(['coletar', 'afiliar', 'parar', 'zerar'].map((k) => typeof ctx.ColetaML[k]), ['function', 'function', 'function', 'function']);
  });

  test('a única API de rede e de armazenamento do arquivo é o fetch (e o hook) e o armazenamento das opções', () => {
    for (const proibido of ['sendBeacon', 'WebSocket', 'EventSource', 'importScripts', 'postMessage', 'sessionStorage',
      'indexedDB', 'new Image', 'document.cookie', 'navigator.', 'window.open', 'location.href', 'location.assign']) {
      assert.ok(!FONTE.includes(proibido), `o arquivo não deveria usar ${proibido}`);
    }
    const metodos = new Set([...FONTE.matchAll(/method:\s*'([A-Z]+)'/g)].map((m) => m[1]));
    assert.deepEqual([...metodos].sort(), ['PATCH', 'POST']);
    assert.ok(!/X-HTTP-Method-Override/i.test(FONTE));
  });

  test('os únicos hosts escritos no arquivo são os do ML, o servidor local, meli.la e as fotos do ML', () => {
    const permitidos = new Set(['lista.mercadolivre.com.br', 'www.mercadolivre.com.br', 'produto.mercadolivre.com.br',
      'localhost', '127.0.0.1', 'meli.la', 'http2.mlstatic.com', 'mercadolivre.com.br']);
    const texto = FONTE.replace(/\\([./])/g, '$1');   // regex escrita como https:\/\/meli\.la
    const hosts = new Set([...texto.matchAll(/https?:\/\/([A-Za-z0-9.-]+)/g)].map((m) => m[1]));
    for (const h of hosts) assert.ok(permitidos.has(h), `host inesperado no arquivo: ${h}`);
  });

  const falsas = [
    ['subdomínio parecido', 'https://lista.mercadolivre.com.br.evil.com'],
    ['http sem TLS', 'http://lista.mercadolivre.com.br'],
    ['porta extra', 'https://lista.mercadolivre.com.br:8443'],
    ['domínio raiz', 'https://mercadolivre.com.br'],
    ['outra loja do ML', 'https://www.mercadolivre.com.ar'],
    ['prefixo no host', 'https://xlista.mercadolivre.com.br'],
  ];
  for (const [nome, origem] of falsas) {
    test(`coletar() recusa ${nome} (${origem}) sem fazer fetch`, async () => {
      const ff = fetchFalso();
      const { ML } = carregar({ origem, fetch: ff.f });
      const estado = await ML.coletar({ termos: ['Smart TV'] });
      assert.match(estado.erro, /só roda numa aba de https:\/\/lista\.mercadolivre\.com\.br/);
      assert.equal(ff.chamadas.length, 0);
    });
    test(`afiliar() recusa ${nome} trocado para www (${origem.replace('lista', 'www')}) sem fazer nada`, async () => {
      const sf = servidorMem(itensMl(2));
      const { ML } = carregar({ origem: origem.replace('lista', 'www'), fetch: sf.f });
      const estado = await ML.afiliar({ gerar: gerarTodos() });
      assert.match(estado.erro, /só roda numa aba de https:\/\/www\.mercadolivre\.com\.br/);
      assert.equal(sf.chamadas.length, 0);
    });
  }

  test('o gancho do createLink devolve ao site a resposta intacta e não lê as outras respostas', async () => {
    const dados = { urls: [{ origin_url: produto(4100000001), short_url: 'https://meli.la/A1' }] };
    const lb = linkbuilder({ dados });
    const { ctx, ML } = carregar({ origem: WWW, fetch: lb.fetch, extras: { Response } });
    lb.montar(ctx);
    const estado = await ML.afiliar({ enviar: false, itens: [produto(4100000001)], pausa: [0, 0] });
    assert.equal(estado.erro, null);
    assert.deepEqual(js(estado.trocados).map((t) => t.url), ['https://meli.la/A1']);
    // 1 geração do lote + 1 da conferência: a página lê o corpo intacto das duas
    assert.deepEqual(lb.leituraDaPagina, [dados, dados], 'a página não conseguiu ler o corpo do createLink depois do gancho');
    assert.equal(lb.leiturasDeOutros, 0, 'o gancho leu (clone) uma resposta que não é createLink');
  });

  test('resposta do createLink que não é JSON não trava: 2 tentativas e fica sem resposta', async () => {
    const lb = linkbuilder({ dados: 'isto não é json' });
    const { ctx, ML } = carregar({ origem: WWW, fetch: lb.fetch, extras: { Response } });
    lb.montar(ctx);
    const estado = await ML.afiliar({ enviar: false, itens: [produto(4100000001), produto(4100000002)], pausa: [0, 0] });
    assert.equal(estado.erro, null);
    assert.equal(lb.botao.cliques, 2);
    assert.deepEqual(js(estado.trocados), []);
    assert.deepEqual(js(estado.semResposta).map((s) => s.mlb), ['MLB4100000001', 'MLB4100000002']);
  });

  test('createLink que nunca responde: o prazo de 30 s derruba o lote, avisa e tira o gancho', async () => {
    const rel = relogio({ estourar: [30000] });
    const lb = linkbuilder({ dados: null });
    const { ctx, ML } = carregar({ origem: WWW, fetch: lb.fetch, extras: { Response, setTimeout: rel.st } });
    lb.montar(ctx);
    const estado = await ML.afiliar({ enviar: false, itens: [produto(4100000001)], pausa: [0, 0] });
    assert.match(estado.erro, /o linkbuilder falhou \(o linkbuilder não respondeu ao createLink\)/);
    assert.equal(ctx.fetch, lb.fetch, 'o gancho não foi desfeito depois da falha');
    assert.equal(estado.rodando, false);
  });
});

/**
 * Página falsa do linkbuilder com Response de verdade.
 * dados: corpo do createLink (objeto, string = corpo cru, função(urls) = por lote, null = nunca responde).
 * via: 'fetch' ou 'xhr'. pedido(urls): corpo enviado ao createLink (string).
 * modoRotulo: 'ligado', 'desligado' (o clique liga), 'trava' (o clique não liga), 'sem-controle', 'ausente'.
 */
function linkbuilder({ dados, via = 'fetch', pedido = (urls) => JSON.stringify({ urls, tag: 'achadosmenicas' }), modoRotulo = 'ligado' } = {}) {
  class Elemento {
    constructor(texto) { this.textContent = texto; this.cliques = 0; this.disabled = false; }
    click() { this.cliques++; if (this.aoClicar) this.aoClicar(); }
    dispatchEvent() { return true; }
  }
  class HTMLTextAreaElement extends Elemento {}
  Object.defineProperty(HTMLTextAreaElement.prototype, 'value', {
    get() { return this.v; }, set(v) { this.v = v; }, configurable: true,
  });
  class Event { constructor(type) { this.type = type; } }
  const rotulo = new Elemento('Links curtos');
  if (modoRotulo === 'ligado') rotulo.control = { checked: true };
  if (modoRotulo === 'desligado') { rotulo.control = { checked: false }; rotulo.aoClicar = () => { rotulo.control.checked = true; }; }
  if (modoRotulo === 'trava') rotulo.control = { checked: false };
  const caixa = new HTMLTextAreaElement('');
  const botao = new Elemento('Gerar');
  const estado = { leituraDaPagina: [], leiturasDeOutros: 0, lotes: [], botao, rotulo };
  let ctx;
  const corpoDe = (urls) => (typeof dados === 'function' ? dados(urls) : dados);
  const f = async (url) => {
    if (!String(url).includes('createLink')) {
      return { ok: true, status: 200, clone() { estado.leiturasDeOutros++; return this; }, json: async () => { estado.leiturasDeOutros++; return {}; },
        text: async () => { estado.leiturasDeOutros++; return ''; } };
    }
    const d = corpoDe(estado.lotes[estado.lotes.length - 1]);
    if (d === null) return new Promise(() => {});
    return new Response(typeof d === 'string' ? d : JSON.stringify(d), { status: 200 });
  };
  class XMLHttpRequest {
    constructor() { this.ouvintes = []; this.responseType = ''; }
    addEventListener(tipo, fn) { if (tipo === 'loadend') this.ouvintes.push(fn); }
    open(metodo, url) { this.url = url; }
    send(corpo) {
      this.enviado = corpo;
      const d = corpoDe(estado.lotes[estado.lotes.length - 1]);
      if (d === null) return;
      setTimeout(() => { this.responseText = typeof d === 'string' ? d : JSON.stringify(d); this.ouvintes.forEach((fn) => fn.call(this)); }, 5);
    }
  }
  const abrirOriginal = XMLHttpRequest.prototype.open;
  const enviarOriginal = XMLHttpRequest.prototype.send;
  botao.aoClicar = async () => {
    const urls = String(caixa.v).split('\n');
    estado.lotes.push(urls);
    if (via === 'fetch') {
      const r = await ctx.fetch('/affiliate-program/api/v2/affiliates/createLink', { method: 'POST', body: pedido(urls) });
      try { estado.leituraDaPagina.push(await r.json()); } catch (e) { estado.leituraDaPagina.push('ilegível'); }
    } else {
      const x = new ctx.XMLHttpRequest();
      x.open('POST', '/affiliate-program/api/v2/affiliates/createLink');
      x.send(pedido(urls));
    }
    await ctx.fetch('/afiliados/outra-coisa');
  };
  const document = {
    querySelectorAll(sel) {
      if (sel === 'label') return modoRotulo === 'ausente' ? [] : [rotulo];
      if (sel === 'textarea') return [caixa];
      if (sel === 'button') return [botao];
      return [];
    },
  };
  return { ...estado, get leituraDaPagina() { return estado.leituraDaPagina; }, get leiturasDeOutros() { return estado.leiturasDeOutros; },
    get lotes() { return estado.lotes; }, fetch: f, botao, rotulo, XMLHttpRequest, abrirOriginal, enviarOriginal,
    montar: (c) => { ctx = c; Object.assign(c, { document, HTMLTextAreaElement, Event, XMLHttpRequest }); } };
}

// ================================================================== CA12: parser
describe('QA CA12: parser e limites', () => {
  test('o máximo padrão é 30 itens por termo, na ordem da página', () => {
    const { ML } = carregar();
    const html = pagina(Array.from({ length: 45 }, (_, i) => polycard(i + 1)));
    const itens = js(ML.extrairItens(html, 'Smart TV', BF));
    assert.equal(itens.length, 30);
    assert.equal(itens[0].item_id, 'MLB6000000001');
    assert.equal(itens[29].item_id, 'MLB6000000030');
  });

  test('coletar() manda no máximo 30 itens por POST e porBusca menor reduz', async () => {
    const paginaDe = () => pagina(Array.from({ length: 45 }, (_, i) => polycard(i + 1)));
    const ff = fetchFalso({ paginaDe });
    const { ML } = carregar({ fetch: ff.f });
    await ML.coletar({ termos: ['Smart TV'] });
    assert.equal(JSON.parse(ff.doServidor()[0].init.body).items.length, 30);
    const ff2 = fetchFalso({ paginaDe });
    await carregar({ fetch: ff2.f }).ML.coletar({ termos: ['Smart TV'], porBusca: 7 });
    assert.equal(JSON.parse(ff2.doServidor()[0].init.body).items.length, 7);
  });

  test('card repetido no meio de uma página cheia não ocupa vaga dos 30', () => {
    const { ML } = carregar();
    const cards = [polycard(1), polycard(1), ...Array.from({ length: 40 }, (_, i) => polycard(i + 2))];
    const itens = js(ML.extrairItens(pagina(cards), 'Smart TV', BF));
    assert.equal(itens.length, 30);
    assert.equal(new Set(itens.map((i) => i.item_id)).size, 30);
  });

  const precos = [
    ['desconto arredonda (4,998% vira 5%)', 124.2, 130.74, 'R$ 124,20', 'R$ 130,74', '-5%'],
    ['desconto de meio por cento sobe', 99.5, 100, 'R$ 99,50', 'R$ 100', '-1%'],
    ['metade do preço', 50, 100, 'R$ 50', 'R$ 100', '-50%'],
    ['milhar com centavos', 1019.9, 1499.9, 'R$ 1.019,90', 'R$ 1.499,90', '-32%'],
    ['meio ponto arredonda para cima como o banco real (135 de 200 = -33%)', 135, 200, 'R$ 135', 'R$ 200', '-33%'],
    ['diferença menor que meio por cento não vira "-0%" nem preço antigo', 99.9, 100, 'R$ 99,90', '', ''],
    ['preço anterior igual não é desconto', 100, 100, 'R$ 100', '', ''],
    ['preço anterior menor não é desconto', 100, 90, 'R$ 100', '', ''],
  ];
  for (const [nome, atual, antes, preco, antigo, desc] of precos) {
    test(`preço: ${nome}`, () => {
      const { ML } = carregar();
      const it = js(ML.extrairItens(pagina([polycard(1, { valor: atual, anterior: antes })]), 'Smart TV', BF)[0]);
      assert.deepEqual([it.data.preco, it.data.preco_antigo, it.data.desconto], [preco, antigo, desc]);
    });
  }

  test('os campos têm os formatos dos 2.704 itens do ML que já estão no banco (medidos em 2026-11-03)', () => {
    const { ML } = carregar();
    const formatos = {
      preco: /^R\$ \d{1,3}(\.\d{3})*(,\d{2})?$/, preco_antigo: /^(R\$ \d{1,3}(\.\d{3})*(,\d{2})?)?$/, desconto: /^(-\d+%)?$/,
      avaliacao: /^(\d(\.\d)? de 5 estrelas)?$/, vendas: /^(Mais de [\d.]+ produtos vendidos)?$/, frete: /^(Frete grátis)?$/,
      num_avaliacoes: /^$/, cupom: /^$/, imagem: /^https:\/\/http2\.mlstatic\.com\/D_Q_NP_2X_[A-Za-z0-9_-]+-E\.webp$/,
    };
    const card = (n, valor, anterior, alt, frete) => {
      const c = polycard(n, { valor, anterior });
      c.polycard.components.push({ type: 'review_compacted', review_compacted: { alt_text: alt } },
        { type: 'shipping_v2', shipping_v2: { text: frete } });
      return c;
    };
    const cards = [card(1, 5, 9, 'Classificação 4.8 de 5 estrelas. Mais de 1000 produtos vendidos.', 'Frete grátis'),
      card(2, 99.9, 150, 'Classificação 5 de 5 estrelas. Mais de 25 produtos vendidos.', 'Chegará amanhã'),
      card(3, 1234.56, 2000, 'Classificação 3.7 de 5 estrelas.', 'Frete GRÁTIS'),
      card(4, 1234567, undefined, '', ''), card(5, 0.99, 1.5, 'Classificação 4.5 de 5 estrelas. Mais de 1.000 produtos vendidos.', 'Frete grátis')];
    const itens = js(ML.extrairItens(pagina(cards), 'Smart TV', BF));
    assert.equal(itens.length, 5);
    for (const it of itens) {
      assert.match(it.item_id, /^MLB\d{6,}$/);
      for (const [campo, rx] of Object.entries(formatos)) assert.match(it.data[campo], rx, `${it.item_id}.${campo}`);
    }
    assert.deepEqual(itens.map((i) => i.data.frete), ['Frete grátis', '', 'Frete grátis', '', 'Frete grátis']);
  });

  test('texto hostil do título chega como texto puro, sem virar markup nem script no POST', async () => {
    const hostil = '</script><img src=x onerror=alert(1)> "aspas" \'apóstrofo\' \\x41 \\u0041 {} [] 🔥 ação';
    const ff = fetchFalso({ paginaDe: () => pagina([polycard(1, { titulo: hostil })]) });
    await carregar({ fetch: ff.f }).ML.coletar({ termos: ['Smart TV'] });
    assert.equal(JSON.parse(ff.doServidor()[0].init.body).items[0].data.titulo, hostil);
  });

  test('contrabarra seguida de x41 no título não vira "A" (par de contrabarras não é escape \\x)', () => {
    const { ML } = carregar();
    const it = js(ML.extrairItens(pagina([polycard(1, { titulo: 'C:\\x41 e \\u0041' })]), 'Smart TV', BF)[0]);
    assert.equal(it.data.titulo, 'C:\\x41 e \\u0041');
  });

  test('escape inválido no literal (\\xZZ) não lança: a página vira "sem polycard"', async () => {
    const { ML } = carregar();
    const ruim = '<script>a.q("{\\"polycard\\":\\xZZ}")</script>';
    assert.equal(ML.literalQ(ruim), null);
    const ff = fetchFalso({ paginaDe: () => ruim });
    const estado = await carregar({ fetch: ff.f }).ML.coletar({ termos: ['Smart TV'] });
    assert.match(estado.erro, /sem polycard/);
    assert.equal(ff.doServidor().length, 0);
  });

  test('JSON de polycard com __proto__ e constructor não polui Object', () => {
    const { ctx, ML } = carregar();
    const texto = '{"polycard":{"__proto__":{"poluido":1},"constructor":{"prototype":{"p2":1}},"metadata":{"id":"MLB1234567"},'
      + '"components":[{"type":"__proto__","__proto__":{"x":1}},{"type":"title","title":{"text":"ok"}}]}}';
    const itens = js(ML.extrairItens(`<script>a.q(${JSON.stringify(texto)})</script>`, 'Smart TV', BF));
    assert.equal(itens.length, 1);
    assert.equal(vm.runInContext('({}).poluido === undefined && ({}).p2 === undefined', ctx), true);
  });

  test('JSON aninhado a 30 mil níveis e página de 3 MB não derrubam nem demoram', () => {
    const { ML } = carregar();
    const fundo = '{"a":'.repeat(30000) + '1' + '}'.repeat(30000);
    const texto = `{"polycard":{"metadata":{"id":"MLB1234567"},"components":[{"type":"title","title":{"text":"d"}},`
      + `{"type":"price","price":{"current_price":{"value":5},"x":${fundo}}}]}}`;
    assert.equal(ML.extrairItens(`<script>a.q(${JSON.stringify(texto)})</script>`, 'Smart TV', BF).length, 1);
    const cards = Array.from({ length: 3000 }, (_, i) => polycard(i + 1, { titulo: 'x'.repeat(500) }));
    const html = pagina(cards);
    assert.ok(html.length > 1.5e6);
    const t0 = Date.now();
    assert.equal(ML.extrairItens(html, 'Smart TV', BF).length, 30);
    assert.ok(Date.now() - t0 < 5000, 'parser lento demais numa página grande');
  });

  test('título muito longo (50 mil caracteres) segue inteiro para o servidor', async () => {
    const longo = 'Perfume ' + 'á'.repeat(50000);
    const ff = fetchFalso({ paginaDe: () => pagina([polycard(1, { titulo: longo })]) });
    await carregar({ fetch: ff.f }).ML.coletar({ termos: ['Smart TV'] });
    assert.equal(JSON.parse(ff.doServidor()[0].init.body).items[0].data.titulo, longo);
  });

  for (const urlFinal of ['https://www.mercadolivre.com.br/gz/account-verification?go=x', 'https://www.mercadolivre.com.br/gz/login', 'https://www.mercadolivre.com.br/captcha/abc',
    'https://www.mercadolivre.com.br/account-verification']) {
    test(`redirecionamento para ${urlFinal} é captcha mesmo com página cheia de polycards: nada é enviado`, async () => {
      const ff = fetchFalso({ urlFinal });
      const arm = memoria();
      const r = await carregar({ fetch: ff.f, localStorage: arm }).ML.coletar({ termos: ['Smart TV', 'Body splash'], pausa: [0, 0] });
      assert.match(r.erro, /captcha/);
      assert.equal(ff.doServidor().length, 0);
      assert.equal(arm.escritas, 0);
    });
  }

  test('URL final que só parece (gzip, "captura") não é captcha', async () => {
    const ff = fetchFalso({ urlFinal: 'https://lista.mercadolivre.com.br/gzip-ferramenta_captura' });
    const r = await carregar({ fetch: ff.f }).ML.coletar({ termos: ['Smart TV'] });
    assert.equal(r.erro, null);
    assert.equal(ff.doServidor().length, 1);
  });

  test('o prazo de 60 s da requisição ao ML derruba a busca com "demorou demais" sem enviar nada', async () => {
    const rel = relogio({ estourar: [60000] });
    const f = async (url, init = {}) => new Promise((_, rej) => {
      init.signal.addEventListener('abort', () => rej(Object.assign(new Error('aborted'), { name: 'AbortError' })));
    });
    const { ML } = carregar({ fetch: f, extras: { setTimeout: rel.st } });
    const estado = await ML.coletar({ termos: ['Smart TV'] });
    assert.match(estado.erro, /não consegui abrir a busca "Smart TV" no ML \(demorou demais\)/);
  });

  test('o prazo de 60 s vale também para o servidor e não marca o termo', async () => {
    const rel = relogio({ estourar: [60000] });
    const arm = memoria();
    const f = async (url, init = {}) => {
      if (String(url).startsWith('/')) return resposta(200, pagina([polycard(1)]), LISTA + url);
      return new Promise((_, rej) => init.signal.addEventListener('abort', () => rej(Object.assign(new Error('x'), { name: 'AbortError' }))));
    };
    // o prazo da busca ao ML precisa passar: só estoura quando o timer é o do servidor
    let n = 0;
    const st = (fn, ms, ...a) => { if (ms === 60000 && ++n === 1) { rel.pedidos.push(ms); return { fake: true }; } return rel.st(fn, ms, ...a); };
    const { ML } = carregar({ fetch: f, extras: { setTimeout: st }, localStorage: arm });
    const estado = await ML.coletar({ termos: ['Smart TV'] });
    assert.match(estado.erro, /não consegui falar com o servidor em http:\/\/localhost:8765 \(demorou demais\)/);
    assert.equal(arm.escritas, 0);
  });
});

// ================================================================== CA13: categoria e termos
describe('QA CA13: cada termo grava a sua cat; BUSCAS e ALIAS', () => {
  test('a cópia BUSCAS tem os mesmos termos, a mesma ordem e o mesmo NFC de buscas.json (leitura independente)', () => {
    const { ML } = carregar();
    assert.equal(JSON.stringify(ML.BUSCAS), JSON.stringify(BUSCAS_JSON));
    const todos = Object.values(ML.BUSCAS).flat();
    assert.equal(todos.length, 140);
    assert.equal(new Set(todos).size, 140);
    for (const t of [...todos, ...Object.keys(ML.BUSCAS)]) assert.equal(t, t.normalize('NFC'));
  });

  test('o termo do ALIAS não está em buscas.json (a Amazon não coleta) e aponta para um termo que está', () => {
    const { ML } = carregar();
    const todos = Object.values(BUSCAS_JSON).flat();
    for (const [alias, alvo] of Object.entries(ML.ALIAS)) {
      assert.ok(!todos.includes(alias), `${alias} não pode entrar em buscas.json`);
      assert.ok(todos.includes(alvo));
    }
    assert.deepEqual(js(ML.ALIAS), { 'Caixa inteligente assistente virtual': 'Smart speaker Alexa' });
  });

  test('os 140 slugs são diferentes e só têm [a-z0-9-] (nenhuma busca repetida no ML)', () => {
    const { ML } = carregar();
    const slugs = TODOS_TERMOS.map(([t]) => ML.slug(t));
    assert.equal(new Set(slugs).size, slugs.length);
    for (const s of slugs) assert.match(s, /^[a-z0-9]+(-[a-z0-9]+)*$/);
  });

  test('coletar() sem termos percorre os 140 termos na ordem do arquivo, cada POST com cat e busca certas', async () => {
    const ff = fetchFalso({ paginaDe: (slug) => pagina([polycard(TODOS_TERMOS.findIndex(([t]) => carregarSlug(t) === slug) + 1)]) });
    const { ML } = carregar({ fetch: ff.f });
    const estado = await ML.coletar({ pausa: [0, 0] });
    assert.equal(estado.erro, null);
    assert.equal(ff.doML().length, 140);
    assert.deepEqual(ff.doML().map((c) => c.url), TODOS_TERMOS.map(([t]) => '/' + carregarSlug(t)));
    const posts = ff.doServidor().map((c) => JSON.parse(c.init.body).items);
    assert.equal(posts.length, 140);
    posts.forEach((itens, i) => {
      assert.equal(itens.length, 1);
      assert.equal(itens[0].cat, TODOS_TERMOS[i][1]);
      assert.equal(itens[0].busca, TODOS_TERMOS[i][0]);
      assert.equal(itens[0].loja, 'ml');
    });
    assert.equal(posts.filter((p) => p[0].cat === BF).length, 60);
  });

  test('o termo do ALIAS é buscado com o slug do alias e grava cat de "Black Friday | Eletrônicos" e busca = alias', async () => {
    const ff = fetchFalso();
    await carregar({ fetch: ff.f }).ML.coletar({ termos: ['Caixa inteligente assistente virtual'] });
    assert.deepEqual(ff.doML().map((c) => c.url), ['/caixa-inteligente-assistente-virtual']);
    const it = JSON.parse(ff.doServidor()[0].init.body).items[0];
    assert.deepEqual([it.cat, it.busca], [BF, 'Caixa inteligente assistente virtual']);
  });

  test('termo em NFD ou com espaços nas pontas é normalizado para o termo do arquivo; repetido conta uma vez', async () => {
    const ff = fetchFalso();
    const arm = memoria();
    const estado = await carregar({ fetch: ff.f, localStorage: arm }).ML.coletar({ termos: ['Sofa\u0301', ' Sofá ', 'Sofá'] });
    assert.equal(estado.erro, null);
    assert.equal(ff.doML().length, 1);
    assert.deepEqual(arm.lista('__coletaML:http://localhost:8765'), ['Sofá']);
    assert.equal(JSON.parse(ff.doServidor()[0].init.body).items[0].busca, 'Sofá');
  });
});

function carregarSlug(t) { return carregar().ML.slug(t); }

// ================================================================== opções e servidor inválido
describe('QA: opções inválidas e servidor de teste', () => {
  const servidoresRuins = ['http://localhost:8765@evil.com', 'http://localhost:8765.evil.com', 'http://localhost.evil.com:8765',
    'http://127.0.0.1.evil.com:80', 'http://[::1]:8765', 'http://localhost:8765/api', 'http://localhost:8765?x=1',
    'http://user@localhost:8765', 'ftp://localhost:8765', 'localhost:8765', '', null, 42, {}, 'http://localhost:'];
  for (const s of servidoresRuins) {
    test(`recusa servidor ${JSON.stringify(s)} em coletar() e afiliar() sem fazer nada`, async () => {
      const ff = fetchFalso();
      const sf = servidorMem(itensMl(1));
      const r1 = await carregar({ fetch: ff.f }).ML.coletar({ termos: ['Smart TV'], servidor: s });
      assert.match(r1.erro, /servidor deve ser http:\/\/localhost/);
      assert.equal(ff.chamadas.length, 0);
      const r2 = await carregar({ origem: WWW, fetch: sf.f }).ML.afiliar({ servidor: s, gerar: gerarTodos() });
      assert.match(r2.erro, /servidor deve ser http:\/\/localhost/);
      assert.equal(sf.chamadas.length, 0);
    });
  }

  for (const opcoes of [null, 5, 'Smart TV', ['Smart TV']]) {
    test(`coletar(${JSON.stringify(opcoes)}) pede um objeto de opções e não faz fetch`, async () => {
      const ff = fetchFalso();
      const r = await carregar({ fetch: ff.f }).ML.coletar(opcoes);
      assert.match(r.erro, /use ColetaML\.coletar\(\{\.\.\.\}\)/);
      assert.equal(ff.chamadas.length, 0);
    });
  }

  test('termos com item que não é texto ou fora de buscas.json (inclusive "Smart TV" com caixa diferente) param antes de tudo', async () => {
    for (const termos of [[1], [null], ['Smart TV', 'smart tv'], ['Smart TV', 'Perfume de gato']]) {
      const ff = fetchFalso();
      const arm = memoria();
      const r = await carregar({ fetch: ff.f, localStorage: arm }).ML.coletar({ termos });
      assert.match(r.erro, /termos/);
      assert.equal(ff.chamadas.length + arm.escritas, 0, JSON.stringify(termos));
    }
  });

  test('enviar:true sem localStorage (modo privado) recusa antes de buscar; enviar:false funciona sem ele', async () => {
    const ff = fetchFalso();
    const { ML } = carregar({ fetch: ff.f, localStorage: null });
    let r = await ML.coletar({ termos: ['Smart TV'] });
    assert.match(r.erro, /sem localStorage/);
    assert.equal(ff.chamadas.length, 0);
    r = await ML.coletar({ termos: ['Smart TV'], enviar: false });
    assert.equal(r.erro, null);
    assert.equal(r.itens.length, 3);
  });

  test('localStorage que lança ao gravar (cota cheia) não derruba a coleta', async () => {
    const arm = { getItem: () => null, setItem() { throw new Error('QuotaExceededError'); }, removeItem() {} };
    const ff = fetchFalso();
    const { ML, mensagens } = carregar({ fetch: ff.f, localStorage: arm });
    const r = await ML.coletar({ termos: ['Smart TV', 'Body splash'], pausa: [0, 0] });
    assert.equal(r.erro, null);
    assert.deepEqual(js(r.feitos), ['Smart TV', 'Body splash']);
    assert.ok(mensagens.some((m) => m.tipo === 'warn' && /progresso/.test(m.texto)));
  });
});

// ================================================================== CA12 (pausa) e CA17 (progresso, parar)
describe('QA CA17: pausa entre termos, progresso, retomada e parar()', () => {
  test('a pausa entre termos fica entre 2,5 e 5 s, não há pausa antes do primeiro nem depois do último', async () => {
    for (const [aleatorio, esperado] of [[0, 2500], [0.5, 3750], [0.999, 4997.5]]) {
      const rel = relogio();
      const ff = fetchFalso();
      const { ML } = carregar({ fetch: ff.f, extras: { setTimeout: rel.st }, aleatorio });
      await ML.coletar({ termos: ['Smart TV', 'Body splash', 'Geladeira'] });
      assert.equal(rel.pausas().length, 2);
      for (const p of rel.pausas()) assert.ok(Math.abs(p - esperado) < 0.01, `pausa ${p}, esperado ${esperado}`);
    }
  });

  test('termos já feitos não geram pausa: só a que separa os dois termos novos', async () => {
    const rel = relogio();
    const ff = fetchFalso();
    const arm = memoria({ '__coletaML:http://localhost:8765': JSON.stringify(['Smart TV']) });
    const { ML } = carregar({ fetch: ff.f, extras: { setTimeout: rel.st }, localStorage: arm, aleatorio: 0 });
    const r = await ML.coletar({ termos: ['Smart TV', 'Body splash', 'Geladeira'] });
    assert.deepEqual(js(r.pulados), ['Smart TV']);
    assert.deepEqual(rel.pausas(), [2500]);
  });

  test('enviar:false ignora o progresso gravado e nunca o altera', async () => {
    const guardado = JSON.stringify(['Smart TV']);
    const arm = memoria({ '__coletaML:http://localhost:8765': guardado });
    const ff = fetchFalso();
    const r = await carregar({ fetch: ff.f, localStorage: arm }).ML.coletar({ termos: ['Smart TV'], enviar: false });
    assert.equal(r.erro, null);
    assert.deepEqual(js(r.pulados), []);
    assert.equal(r.itens.length, 3);
    assert.equal(ff.doML().length, 1);
    assert.equal(arm.escritas, 0);
    assert.equal(arm.getItem('__coletaML:http://localhost:8765'), guardado);
  });

  test('o progresso é gravado termo a termo; um captcha no 2º termo mantém o 1º e a retomada continua do 2º', async () => {
    const arm = memoria();
    let captcha = true;
    const ff = fetchFalso({ });
    const f = async (url, init = {}) => {
      if (captcha && url === '/body-splash') return resposta(200, '<html>captcha</html>', 'https://www.mercadolivre.com.br/gz/account-verification');
      return ff.f(url, init);
    };
    const { ML } = carregar({ fetch: f, localStorage: arm });
    let r = await ML.coletar({ termos: ['Smart TV', 'Body splash', 'Geladeira'], pausa: [0, 0] });
    assert.match(r.erro, /captcha/);
    assert.deepEqual(arm.lista('__coletaML:http://localhost:8765'), ['Smart TV']);
    assert.equal(ff.doServidor().length, 1);

    captcha = false;   // o dono resolveu o captcha na aba
    r = await ML.coletar({ termos: ['Smart TV', 'Body splash', 'Geladeira'], pausa: [0, 0] });
    assert.equal(r.erro, null);
    assert.deepEqual(js(r.pulados), ['Smart TV']);
    assert.deepEqual(js(r.feitos), ['Body splash', 'Geladeira']);
    assert.deepEqual(arm.lista('__coletaML:http://localhost:8765'), ['Smart TV', 'Body splash', 'Geladeira']);
  });

  test('parar() e retomar: a segunda rodada faz só o que faltou e o servidor recebe cada termo uma vez', async () => {
    let ML;
    let primeira = true;
    const ff = fetchFalso({ servidor: async (url, init) => {
      if (primeira) { primeira = false; ML.parar(); }
      return { status: 200, corpo: { inserido: JSON.parse(init.body).items.length, atualizado: 0, total: 1 } };
    } });
    ({ ML } = carregar({ fetch: ff.f }));
    const termos = ['Smart TV', 'Body splash', 'Geladeira'];
    let r = await ML.coletar({ termos, pausa: [0, 0] });
    assert.equal(r.parado, true);
    assert.deepEqual(js(r.feitos), ['Smart TV']);
    r = await ML.coletar({ termos, pausa: [0, 0] });
    assert.equal(r.parado, false);
    assert.deepEqual(js(r.pulados), ['Smart TV']);
    assert.deepEqual(ff.doServidor().map((c) => JSON.parse(c.init.body).items[0].busca), ['Smart TV', 'Body splash', 'Geladeira']);
  });

  test('parar() sem nada rodando só avisa; zerar() com servidor inválido devolve false', () => {
    const { ML, mensagens } = carregar();
    assert.doesNotThrow(() => ML.parar());
    assert.ok(mensagens.some((m) => /nenhuma coleta rodando/.test(m.texto)));
    assert.equal(ML.zerar('http://localhost:8765@evil.com', memoria()), false);
  });

  test('o progresso de um servidor não vale para outro e entradas que não são texto são ignoradas', async () => {
    const arm = memoria({ '__coletaML:http://localhost:8765': JSON.stringify(['Smart TV', 7, null, { a: 1 }]) });
    const ff = fetchFalso();
    const r = await carregar({ fetch: ff.f, localStorage: arm }).ML.coletar({ termos: ['Smart TV', 'Body splash'], servidor: 'http://localhost:8766', pausa: [0, 0] });
    assert.deepEqual(js(r.pulados), []);
    const r2 = await carregar({ fetch: ff.f, localStorage: arm }).ML.coletar({ termos: ['Smart TV', 'Body splash'], pausa: [0, 0] });
    assert.deepEqual(js(r2.pulados), ['Smart TV']);
  });
});

// ================================================================== CA14: contrato do envio
describe('QA CA14: nada fora do contrato sai da coleta', () => {
  const erros = [
    [400, { error: 'item 0: cat deve ser texto' }, /recusou "Smart TV" com 400: item 0: cat deve ser texto/],
    [403, { error: 'origem não permitida' }, /recusou "Smart TV" com 403: origem não permitida/],
    [413, { error: 'corpo grande demais (máximo de 5 MB)' }, /com 413: corpo grande demais/],
    [415, { error: 'envie Content-Type: application/json' }, /com 415: envie Content-Type/],
    [500, '<html>Internal Server Error</html>', /recusou "Smart TV" com 500\. A coleta parou/],
  ];
  for (const [status, corpo, erro] of erros) {
    test(`servidor que responde ${status}: para com mensagem clara e não marca o termo nem repete o POST`, async () => {
      const ff = fetchFalso({ servidor: async () => ({ status, corpo }) });
      const arm = memoria();
      const r = await carregar({ fetch: ff.f, localStorage: arm }).ML.coletar({ termos: ['Smart TV', 'Body splash'], pausa: [0, 0] });
      assert.match(r.erro, erro);
      assert.equal(ff.doServidor().length, 1);
      assert.equal(ff.doML().length, 1);
      assert.equal(arm.escritas, 0);
      assert.deepEqual(js(r.feitos), []);
      assert.equal(r.rodando, false);
    });
  }

  test('resposta 200 sem os contadores (inserido/atualizado) é tratada como inesperada e não marca o termo', async () => {
    for (const corpo of [{ ok: true }, [], null, { inserido: '3', atualizado: 0 }]) {
      const ff = fetchFalso({ servidor: async () => ({ status: 200, corpo }) });
      const arm = memoria();
      const r = await carregar({ fetch: ff.f, localStorage: arm }).ML.coletar({ termos: ['Smart TV'] });
      assert.match(r.erro, /resposta inesperada do servidor/, JSON.stringify(corpo));
      assert.equal(arm.escritas, 0);
    }
  });

  test('cada item do POST tem exatamente loja/item_id/cat/busca/url/data e data só traz os 10 campos, todos texto', async () => {
    const ff = fetchFalso({ paginaDe: () => pagina([polycard(1, { valor: 1234.5, anterior: 2000 }), polycard(2)]) });
    await carregar({ fetch: ff.f }).ML.coletar({ termos: ['Perfume Natura'] });
    const corpo = JSON.parse(ff.doServidor()[0].init.body);
    assert.deepEqual(Object.keys(corpo), ['items']);
    for (const it of corpo.items) {
      assert.deepEqual(Object.keys(it), ['loja', 'item_id', 'cat', 'busca', 'url', 'data']);
      assert.deepEqual(Object.keys(it.data), ['titulo', 'preco', 'preco_antigo', 'desconto', 'avaliacao', 'num_avaliacoes',
        'vendas', 'frete', 'cupom', 'imagem']);
      assert.ok(Object.values(it.data).every((v) => typeof v === 'string'));
      assert.ok(it.url.startsWith('https://produto.mercadolivre.com.br/MLB-'), 'a coleta só envia url comum do ML (a afiliação vem depois)');
      assert.ok(!/meli\.la|amazon/.test(it.url));
    }
  });

  test('toda chamada da coleta é uma busca relativa ao ML (credentials include) ou um POST ao servidor (credentials omit)', async () => {
    const ff = fetchFalso();
    await carregar({ fetch: ff.f }).ML.coletar({ termos: ['Smart TV', 'Geladeira'], pausa: [0, 0] });
    for (const c of ff.chamadas) {
      if (c.url.startsWith('/')) assert.deepEqual([c.init.credentials, c.init.method, c.init.body], ['include', undefined, undefined]);
      else assert.deepEqual([c.url, c.init.method, c.init.credentials, Object.keys(c.init.headers)], [`${SERVIDOR}/api/items`, 'POST', 'omit', ['Content-Type']]);
    }
  });
});

// ================================================================== CA16: afiliar()
describe('QA CA16: afiliar() com servidor e linkbuilder falsos', () => {
  const ELEGIVEL = (mlb, url = `https://meli.la/${mlb}`) => ({ origin_url: produto(mlb) + '-x-_JM', short_url: url });
  const ruins = [
    ['http em vez de https', 'http://meli.la/abc123'],
    ['sem código', 'https://meli.la/'],
    ['com caminho extra', 'https://meli.la/abc/def'],
    ['com query', 'https://meli.la/abc?utm=1'],
    ['host que só contém meli.la', 'https://meli.la.evil.com/abc'],
    ['meli.la no caminho de outro host', 'https://evil.com/meli.la/abc'],
    ['host com usuário', 'https://meli.la@evil.com/abc'],
    ['javascript:', 'javascript:alert(1)'],
    ['com espaço', 'https://meli.la/ab c'],
    ['com quebra de linha', 'https://meli.la/abc\n'],
    ['link do ML que não é meli.la', 'https://mercadolivre.com/sec/1xYz9Qw'],
    ['a própria url do produto', produto(4100000001)],
    ['vazio', ''],
    ['nulo', null],
    ['número', 42],
    ['lista', ['https://meli.la/abc']],
    ['objeto', { u: 'https://meli.la/abc' }],
  ];
  for (const [nome, curto] of ruins) {
    test(`short_url ${nome} em lote misto: o item bom é gravado, o ruim fica sem resposta e nada dele é guardado`, async () => {
      const sf = servidorMem(itensMl(2));
      const arm = memoria();
      const gerar = async () => ({ urls: [{ origin_url: produto(4100000001), short_url: curto }, ELEGIVEL(4100000002)] });
      const { ML, mensagens } = carregar({ origem: WWW, fetch: sf.f, localStorage: arm });
      const r = await ML.afiliar({ gerar, pausa: [0, 0] });
      assert.equal(r.erro, null);
      assert.equal(sf.patches().length, 1, 'só o item bom é gravado');
      assert.match(sf.patches()[0].url, /\/api\/items\/2$/);
      assert.equal(sf.db.get(2).url, 'https://meli.la/4100000002');
      assert.equal(sf.db.get(1).url, produto(4100000001), 'o item ruim fica com a url comum');
      assert.deepEqual(js(r.naoMeliLa).map((e) => e.mlb), ['MLB4100000001']);
      assert.deepEqual(js(r.semResposta).map((e) => e.id), [1]);
      assert.deepEqual(js(r.trocados).map((t) => t.id), [2]);
      assert.deepEqual(js(r.inelegiveis), []);
      const guardado = arm.lista('__afiliarML:http://localhost:8765');
      assert.ok(!guardado || guardado.every((e) => e.id !== 1), 'o item sem meli.la não pode ser guardado como inelegível');
      assert.ok(!mensagens.some((m) => /Exclua pelo site/.test(m.texto)));
      assert.ok(mensagens.some((m) => m.tipo === 'warn' && /vieram sem meli\.la/.test(m.texto)));
      assert.equal(r.rodando, false);
    });
  }

  test('lote inteiro sem meli.la (Links curtos desligado): para com erro, 0 PATCH, nada guardado, nenhum item é "Exclua"', async () => {
    const sf = servidorMem(itensMl(3));
    const arm = memoria();
    const gerar = async (urls) => ({ urls: urls.map((u) => ({ origin_url: u, short_url: `https://mercadolivre.com/sec/${mlbDe(u)}` })) });
    const { ML, mensagens } = carregar({ origem: WWW, fetch: sf.f, localStorage: arm });
    const r = await ML.afiliar({ gerar, pausa: [0, 0] });
    assert.match(r.erro, /não é meli\.la/);
    assert.match(r.erro, /Links curtos/);
    assert.equal(r.naoMeliLa.length, 3);
    assert.equal(sf.patches().length, 0);
    assert.equal(arm.escritas, 0);
    assert.ok(!mensagens.some((m) => /Exclua pelo site/.test(m.texto)));
  });

  test('a repescagem não entra na regra de parada: lote repescado sem meli.la termina sem erro e o item fica sem resposta', async () => {
    const sf = servidorMem(itensMl(2));
    let chamada = 0;
    const gerar = async (urls) => {
      chamada++;
      if (chamada === 1) return { urls: [ELEGIVEL(4100000002)] };   // item 1 sem resposta: vai para a repescagem
      return { urls: urls.filter((u) => mlbDe(u) === 'MLB4100000001').map((u) => ({ origin_url: u, short_url: 'https://evil.com/x' })) };
    };
    const r = await carregar({ origem: WWW, fetch: sf.f }).ML.afiliar({ gerar, pausa: [0, 0] });
    assert.equal(r.erro, null);
    assert.equal(sf.patches().length, 1);
    assert.deepEqual(js(r.naoMeliLa).map((e) => e.id), [1]);
    assert.deepEqual(js(r.semResposta).map((e) => e.id), [1]);
    assert.equal(sf.db.get(1).url, produto(4100000001));
  });

  test('a repescagem que volta com meli.la grava o item', async () => {
    const sf = servidorMem(itensMl(2));
    let chamada = 0;
    const gerar = async (urls) => {
      chamada++;
      return { urls: chamada === 1 ? [ELEGIVEL(4100000002)] : urls.map((u) => ELEGIVEL2(u)) };
    };
    const r = await carregar({ origem: WWW, fetch: sf.f }).ML.afiliar({ gerar, pausa: [0, 0] });
    assert.equal(r.erro, null);
    assert.deepEqual(js(r.trocados).map((t) => t.id).sort(), [1, 2]);
    assert.deepEqual(js(r.semResposta), []);
  });

  test('error_code com short_url meli.la válido continua inelegível (o erro vale mais que o link)', async () => {
    const sf = servidorMem(itensMl(1));
    const gerar = async () => ({ urls: [{ ...ELEGIVEL(4100000001), error_code: 'ITEM_NOT_ELIGIBLE', message: 'não elegível' }] });
    const r = await carregar({ origem: WWW, fetch: sf.f }).ML.afiliar({ gerar, pausa: [0, 0] });
    assert.equal(sf.patches().length, 0);
    assert.match(r.inelegiveis[0].motivo, /^ITEM_NOT_ELIGIBLE: não elegível$/);
  });

  test('resposta embaralhada, canônica (-_JM) e com MLB que não foi pedido: cada item recebe o seu link e o intruso é ignorado', async () => {
    const sf = servidorMem(itensMl(5));
    const gerar = async (urls) => ({ urls: [ELEGIVEL(9999999999), ...[...urls].reverse().map((u) => ELEGIVEL(mlbDe(u).slice(3)))] });
    const r = await carregar({ origem: WWW, fetch: sf.f }).ML.afiliar({ gerar, pausa: [0, 0] });
    assert.equal(r.erro, null);
    for (let i = 1; i <= 5; i++) assert.equal(sf.db.get(i).url, `https://meli.la/${4100000000 + i}`);
    assert.equal(sf.patches().length, 5);
    assert.ok(!sf.patches().some((c) => /9999999999/.test(c.init.body)));
  });

  test('dois itens do banco com o mesmo MLB recebem o mesmo link e a repetição é apontada', async () => {
    const sf = servidorMem([{ id: 1, loja: 'ml', url: produto(4100000001) }, { id: 2, loja: 'ml', url: produto(4100000001) + '-copia-_JM' }]);
    const r = await carregar({ origem: WWW, fetch: sf.f }).ML.afiliar({ gerar: gerarTodos(), pausa: [0, 0] });
    assert.equal(sf.db.get(1).url, sf.db.get(2).url);
    assert.deepEqual(js(r.repetidas), [{ url: 'https://meli.la/MLB4100000001', ids: [1, 2] }]);
  });

  test('url do ML sem código MLB vira inelegível sem chamar o linkbuilder, e o resto segue', async () => {
    const sf = servidorMem([{ id: 1, loja: 'ml', url: 'https://click1.mercadolivre.com.br/mclics/xyz' }, { id: 2, loja: 'ml', url: produto(4100000002) }]);
    const pedidos = [];
    const r = await carregar({ origem: WWW, fetch: sf.f }).ML.afiliar({ gerar: gerarTodos(pedidos), pausa: [0, 0] });
    // 1 geração do lote e 1 da conferência (só do item que ganhou link)
    assert.deepEqual(pedidos, [[produto(4100000002)], [produto(4100000002)]]);
    assert.deepEqual(js(r.inelegiveis).map((e) => [e.id, e.motivo]), [[1, 'url sem código MLB']]);
    assert.equal(sf.db.get(1).url, 'https://click1.mercadolivre.com.br/mclics/xyz');
  });

  for (const [nome, gerar] of [['{urls: []}', async () => ({ urls: [] })], ['null', async () => null], ['texto', async () => 'oops'], ['{}', async () => ({})]]) {
    test(`linkbuilder que responde ${nome}: 2 tentativas por item, sem PATCH e sem laço infinito`, async () => {
      const sf = servidorMem(itensMl(3));
      const pedidos = [];
      const g = async (urls) => { pedidos.push(urls.length); return gerar(urls); };
      const r = await carregar({ origem: WWW, fetch: sf.f }).ML.afiliar({ gerar: g, pausa: [0, 0] });
      assert.equal(r.erro, null);
      assert.deepEqual(pedidos, [3, 3]);
      assert.equal(sf.patches().length, 0);
      assert.equal(r.semResposta.length, 3);
    });
  }

  test('a 2ª passada só repesca em lote de 10 quem ficou sem resposta (30 itens, 12 sem resposta)', async () => {
    const sf = servidorMem(itensMl(30));
    const pedidos = [];
    let rodada = 0;
    const gerar = async (urls) => {
      pedidos.push(urls.length);
      const primeira = ++rodada <= 2;   // lotes 25 e 5 da 1ª passada: os 12 últimos da lista não voltam
      const lista = primeira ? urls.filter((u) => Number(mlbDe(u).slice(3)) - 4100000000 <= 18) : urls;
      return { urls: lista.map((u) => ELEGIVEL(mlbDe(u).slice(3))) };
    };
    const r = await carregar({ origem: WWW, fetch: sf.f }).ML.afiliar({ gerar, pausa: [0, 0] });
    assert.equal(r.erro, null);
    // 25+5 (1ª passada), 10+2 (repescagem) e a conferência dos 30 tocados em lotes de 25
    assert.deepEqual(pedidos, [25, 5, 10, 2, 25, 5]);
    assert.equal(r.trocados.length, 30);
    assert.deepEqual(js(r.semResposta), []);
  });

  test('item excluído entre o PATCH e a conferência não é recriado nem recebe novo PATCH', async () => {
    let gets = 0;
    const sf = servidorMem(itensMl(2), (metodo, caminho, db) => {
      if (metodo === 'GET' && caminho === '/api/items' && ++gets === 1) db.delete(2);
    });
    const r = await carregar({ origem: WWW, fetch: sf.f }).ML.afiliar({ gerar: gerarTodos(), pausa: [0, 0] });
    assert.equal(r.erro, null);
    assert.equal(sf.patches().length, 2);
    assert.equal(r.correcoes, 0);
    assert.equal(sf.db.has(2), false);
  });

  test('conferência que nunca converge (servidor ignora o PATCH) para em 3 voltas com aviso, sem laço infinito', async () => {
    const sf = servidorMem(itensMl(2), (metodo, caminho) => (metodo === 'PATCH' ? { status: 200, corpo: { ignorado: true } } : null));
    const { ML, mensagens } = carregar({ origem: WWW, fetch: sf.f });
    const r = await ML.afiliar({ gerar: gerarTodos(), pausa: [0, 0] });
    assert.equal(r.erro, null);
    assert.equal(r.correcoes, 6);
    // 2 PATCH da 1ª passada, 2 da repescagem (o item continua pendente porque o servidor ignora) e 3 voltas x 2 da conferência
    assert.equal(sf.patches().length, 2 + 2 + 6);
    assert.ok(mensagens.some((m) => m.tipo === 'warn' && /não chegou a 0 correções/.test(m.texto)));
  });

  test('erro do servidor na lista de pendentes ou lista que não é lista: para antes de gerar qualquer link', async () => {
    for (const [custom, erro] of [[{ status: 500, corpo: 'x' }, /o servidor respondeu 500/], [{ status: 200, corpo: { a: 1 } }, /resposta inesperada/],
      [{ status: 403, corpo: { error: 'origem não permitida' } }, /o servidor respondeu 403/]]) {
      const sf = servidorMem(itensMl(2), () => custom);
      const pedidos = [];
      const r = await carregar({ origem: WWW, fetch: sf.f }).ML.afiliar({ gerar: gerarTodos(pedidos) });
      assert.match(r.erro, erro);
      assert.equal(pedidos.length, 0);
      assert.equal(r.rodando, false);
    }
  });

  test('PATCH recusado pelo servidor (403/415/400) para na hora e o item fica como estava', async () => {
    for (const status of [400, 403, 415]) {
      const sf = servidorMem(itensMl(3), (metodo) => (metodo === 'PATCH' ? { status, corpo: { error: 'recusado' } } : null));
      const r = await carregar({ origem: WWW, fetch: sf.f }).ML.afiliar({ gerar: gerarTodos(), pausa: [0, 0] });
      assert.match(r.erro, new RegExp(`recusou o link do item \\d+ com ${status}: recusado`));
      assert.equal(sf.patches().length, 1);
      assert.deepEqual([...sf.db.values()].map((i) => i.url), itensMl(3).map((i) => i.url));
    }
  });

  test('afiliar() duas vezes ao mesmo tempo: a segunda é recusada e só uma execução gera links', async () => {
    const sf = servidorMem(itensMl(2));
    let soltar;
    const trava = new Promise((r) => { soltar = r; });
    const pedidos = [];
    const gerar = async (urls) => { await trava; return gerarTodos(pedidos)(urls); };
    const { ML, mensagens } = carregar({ origem: WWW, fetch: sf.f });
    const primeira = ML.afiliar({ gerar, pausa: [0, 0] });
    await new Promise((r) => setTimeout(r, 20));
    const segunda = await ML.afiliar({ gerar: gerarTodos(pedidos), pausa: [0, 0] });
    assert.equal(segunda.rodando, true);
    assert.ok(mensagens.some((m) => m.tipo === 'error' && /já há uma coleta rodando/.test(m.texto)));
    soltar();
    const r = await primeira;
    assert.equal(r.erro, null);
    assert.equal(pedidos.length, 2, 'uma geração do lote e uma da conferência, só da execução que rodou');
    assert.equal(sf.patches().length, 2);
  });

  test('afiliar com enviar:false não grava inelegíveis nem lê o localStorage, mesmo com lista guardada', async () => {
    const guardado = JSON.stringify([{ id: 1, mlb: 'MLB4100000001', motivo: 'x' }]);
    const arm = memoria({ '__afiliarML:http://localhost:8765': guardado });
    const sf = servidorMem(itensMl(2));
    const r = await carregar({ origem: WWW, fetch: sf.f, localStorage: arm }).ML.afiliar({ enviar: false, itens: [produto(4100000001)], gerar: gerarTodos(), pausa: [0, 0] });
    assert.deepEqual(js(r.trocados).map((t) => t.id), [1]);
    assert.equal(sf.chamadas.length, 0);
    assert.equal(arm.escritas, 0);
    assert.equal(arm.getItem('__afiliarML:http://localhost:8765'), guardado);
  });

  test('parar() durante a pausa entre lotes corta a espera e o próximo lote não sai', async () => {
    let ML;
    const sf = servidorMem(itensMl(4));
    const pedidos = [];
    const gerar = async (urls) => { const r = await gerarTodos(pedidos)(urls); setTimeout(() => ML.parar(), 20); return r; };
    ({ ML } = carregar({ origem: WWW, fetch: sf.f }));
    const t0 = Date.now();
    const r = await ML.afiliar({ gerar, lote: 2, pausa: [10000, 10000] });
    assert.ok(Date.now() - t0 < 2000, 'a pausa de 10 s não foi cortada');
    assert.equal(r.parado, true);
    assert.equal(pedidos.length, 1);
    assert.equal(r.trocados.length, 2);
  });
});

// ================================================================== integração: servidor.py de verdade
describe('QA integração: coleta e afiliação de ponta a ponta no servidor.py', () => {
  const srv = usarServidor();
  /** Três cards por termo, com MLB próprio de cada termo (prefixo*1000 + posição do termo na lista). */
  const paginaDoTermo = (prefixo, termos, valor = 50) => {
    const idx = new Map(termos.map((t, i) => [carregarSlug(t), i]));
    return (slug) => {
      const base = prefixo * 1000 + idx.get(slug) * 10;
      return pagina([polycard(base, { valor, anterior: 80 }), polycard(base + 1, { valor }), polycard(base + 2, { valor, titulo: 'Perfume ação 🔥 "x" <b>' })]);
    };
  };
  const misto = (chrome, paginaDe) => async (url, init = {}) => {
    if (String(url).startsWith('/')) return resposta(200, paginaDe(String(url).slice(1)), LISTA + url);
    return chrome(url, init);
  };
  const lerItens = async (origem = LISTA) => (await (await fetchNode(srv.porta, origem)(`${srv.servidor}/api/items`)).json());

  test('fluxo completo como o Chrome: preflight liberado, só Content-Type, só GET/POST/PATCH, só as 3 rotas', async () => {
    const registro = [];
    const lista = fetchChrome(srv.porta, LISTA, registro);
    const termos = ['Smart TV', 'Geladeira', 'Sofá', 'Body splash', 'Caixa inteligente assistente virtual'];
    const { ML } = carregar({ fetch: misto(lista, paginaDoTermo(1, termos)) });
    const c = await ML.coletar({ servidor: srv.servidor, termos, pausa: [0, 0] });
    assert.equal(c.erro, null);
    assert.equal(c.inserido, 15);

    const www = fetchChrome(srv.porta, WWW, registro);
    const pedidos = [];
    const a = await carregar({ origem: WWW, fetch: www }).ML.afiliar({ servidor: srv.servidor, gerar: gerarTodos(pedidos), pausa: [0, 0] });
    assert.equal(a.erro, null);
    assert.equal(a.trocados.length, 15);
    assert.deepEqual(js(a.inelegiveis), []);
    assert.equal(a.correcoes, 0);

    assert.ok(registro.length > 20);
    for (const r of registro) {
      assert.match(r.caminho, /^\/api\/(items|items\/\d+|ml-sem-afiliado)$/);
      assert.ok(['GET', 'POST', 'PATCH'].includes(r.metodo), r.metodo);
      assert.ok(r.cabecalhos.every((h) => h === 'content-type'), `cabeçalho fora do preflight: ${r.cabecalhos}`);
      assert.equal(r.credentials, 'omit');
      assert.equal(r.referrerPolicy, 'no-referrer', 'a chamada ao servidor local leva o Referer do ML');
      assert.equal(r.status, 200, `${r.metodo} ${r.caminho}`);
      if (r.metodo !== 'GET') assert.equal(r.preflight, true, `${r.metodo} ${r.caminho} sem preflight liberado`);
    }
    assert.ok(registro.some((r) => r.metodo === 'POST') && registro.some((r) => r.metodo === 'PATCH'));

    const itens = (await lerItens(WWW)).filter((i) => i.loja === 'ml');
    assert.equal(itens.length, 15);
    const cats = new Map(itens.map((i) => [i.busca, i.cat]));
    assert.deepEqual([...cats].sort(), [['Body splash', 'Perfumes e Perfumaria'], ['Caixa inteligente assistente virtual', BF],
      ['Geladeira', 'Eletrodomésticos'], ['Smart TV', BF], ['Sofá', 'Casa e Decoração']]);
    for (const i of itens) {
      assert.match(i.url, /^https:\/\/meli\.la\/MLB\d+$/);
      assert.equal(i.url, `https://meli.la/${i.item_id}`, 'o link ficou no item de outro MLB');
      assert.ok(i.data.titulo && i.data.preco && i.data.imagem, 'os dados do item sumiram depois do PATCH');
    }
    const pend = await (await fetchNode(srv.porta, WWW)(`${srv.servidor}/api/ml-sem-afiliado`)).json();
    assert.deepEqual(pend, []);
  });

  test('afiliar() de novo depois de tudo afiliado não gera link nem faz PATCH (idempotente)', async () => {
    const registro = [];
    const pedidos = [];
    const r = await carregar({ origem: WWW, fetch: fetchChrome(srv.porta, WWW, registro) }).ML.afiliar({ servidor: srv.servidor, gerar: gerarTodos(pedidos), pausa: [0, 0] });
    assert.equal(r.erro, null);
    assert.deepEqual(pedidos, []);
    assert.deepEqual(registro.filter((x) => x.metodo !== 'GET'), []);
    assert.equal(r.trocados.length, 0);
  });

  test('coletar de novo com preço novo atualiza os dados e preserva o meli.la e a cat; total não cresce', async () => {
    const termos = ['Smart TV', 'Geladeira', 'Sofá', 'Body splash', 'Caixa inteligente assistente virtual'];
    const antes = (await lerItens()).filter((i) => i.loja === 'ml');
    const lista = fetchChrome(srv.porta, LISTA, []);
    const { ML } = carregar({ fetch: misto(lista, paginaDoTermo(1, termos, 7)) });
    const r = await ML.coletar({ servidor: srv.servidor, termos, pausa: [0, 0] });
    assert.equal(r.erro, null);
    assert.equal(r.inserido, 0);
    assert.equal(r.atualizado, 15);
    const depois = (await lerItens()).filter((i) => i.loja === 'ml');
    assert.equal(depois.length, antes.length);
    for (const a of antes) {
      const d = depois.find((i) => i.id === a.id);
      assert.equal(d.url, a.url, 'o meli.la foi trocado pela url comum');
      assert.equal(d.cat, a.cat);
      assert.equal(d.data.preco, 'R$ 7');
    }
  });

  /** Título de exatamente `n` code points (como o len() do Python no servidor), com emoji, aspas e HTML; não termina em espaço. */
  const tituloDe = (n) => [...'Perfume 🔥 "x" <b>&amp;</b> \'ação\' '.repeat(40)].slice(0, n - 1).join('') + 'z';
  /** Card com a foto de `n` caracteres no total (o parser monta https://http2.mlstatic.com/D_Q_NP_2X_<id>-E.webp). */
  const cardComImagem = (num, titulo, tamanhoImagem) => {
    const c = polycard(num, { titulo });
    c.polycard.pictures.pictures[0].id = 'a'.repeat(tamanhoImagem - 'https://http2.mlstatic.com/D_Q_NP_2X_-E.webp'.length);
    return c;
  };

  test('no teto do servidor (título de 500 e foto de 200 caracteres, com emoji, aspas e HTML) volta do banco idêntico', async () => {
    const titulo = tituloDe(500);
    assert.equal([...titulo].length, 500);
    assert.ok(titulo.length > 500, 'o teste precisa de pares substitutos para provar a contagem por code point');
    const mlb = 8100000001;
    const lista = fetchChrome(srv.porta, LISTA, []);
    const { ML } = carregar({ fetch: misto(lista, () => pagina([cardComImagem(mlb - 6000000000, titulo, 200)])) });
    const r = await ML.coletar({ servidor: srv.servidor, termos: ['Lattafa'], pausa: [0, 0] });
    assert.equal(r.erro, null);
    assert.equal(r.itens[0].data.imagem.length, 200);
    const it = (await lerItens()).find((i) => i.item_id === 'MLB' + mlb);
    assert.equal(it.data.titulo, titulo);
    assert.equal(it.data.imagem, r.itens[0].data.imagem);
    assert.equal(it.cat, 'Perfumes e Perfumaria');
  });

  for (const [nome, card, erro] of [
    ['título de 501 caracteres', (n) => cardComImagem(n, tituloDe(501), 100), /data\.titulo passa de 500 caracteres/],
    ['foto de 201 caracteres', (n) => cardComImagem(n, 'Produto normal', 201), /data\.imagem passa de 200 caracteres/],
  ]) {
    test(`${nome}: o servidor recusa com 400, a coleta para com a mensagem inteira e nada do lote é gravado`, async () => {
      const antes = (await lerItens()).filter((i) => i.loja === 'ml').length;
      const base = 2100000000 + (nome.startsWith('título') ? 10 : 20);
      const arm = memoria();
      const registro = [];
      const lista = fetchChrome(srv.porta, LISTA, registro);
      const { ML, mensagens } = carregar({ localStorage: arm,
        fetch: misto(lista, () => pagina([polycard(base), card(base + 1), polycard(base + 2)])) });
      const r = await ML.coletar({ servidor: srv.servidor, termos: ['Lattafa', 'Azzaro Pour Homme'], pausa: [0, 0] });
      assert.match(r.erro, new RegExp(`o servidor recusou "Lattafa" com 400: item 1: ${erro.source}\\. A coleta parou\\.$`));
      assert.ok(mensagens.some((m) => m.tipo === 'error' && m.texto.includes(r.erro)), 'a mensagem não chegou inteira ao console');
      assert.equal(registro.filter((x) => x.metodo === 'POST').length, 1, 'não pode repetir o POST nem seguir para o próximo termo');
      assert.equal(registro.find((x) => x.metodo === 'POST').status, 400);
      assert.equal(arm.escritas, 0, 'o termo recusado não pode entrar no progresso');
      assert.deepEqual(js(r.feitos), []);
      const depois = (await lerItens()).filter((i) => i.loja === 'ml');
      assert.equal(depois.length, antes);
      assert.ok(!depois.some((i) => [base, base + 1, base + 2].map((n) => 'MLB' + (6000000000 + n)).includes(i.item_id)), 'item válido do mesmo lote foi gravado');
    });
  }

  test('servidor recusando por origem (403 de verdade): a coleta e o afiliar() param e nada é gravado', async () => {
    const antes = (await lerItens()).length;
    const mau = fetchNode(srv.porta, 'https://evil.example');
    const c = await carregar({ fetch: misto(mau, paginaDoTermo(2, ['Smart TV'])) }).ML.coletar({ servidor: srv.servidor, termos: ['Smart TV'] });
    assert.match(c.erro, /o servidor recusou "Smart TV" com 403: origem não permitida/);
    const pedidos = [];
    const a = await carregar({ origem: WWW, fetch: mau }).ML.afiliar({ servidor: srv.servidor, gerar: gerarTodos(pedidos) });
    assert.match(a.erro, /o servidor respondeu 403/);
    assert.deepEqual(pedidos, []);
    assert.equal((await lerItens()).length, antes);
  });

  test('servidor fora do ar (porta fechada de verdade): erro claro, termo não marcado, nada enviado ao ML depois', async () => {
    const fechada = await portaLivre();
    const arm = memoria();
    const ff = [];
    const f = async (url, init) => { ff.push(String(url)); return String(url).startsWith('/') ? resposta(200, pagina([polycard(1)]), LISTA + url) : fetchNode(fechada)(url, init); };
    const r = await carregar({ fetch: f, localStorage: arm }).ML.coletar({ servidor: `http://localhost:${fechada}`, termos: ['Smart TV', 'Geladeira'], pausa: [0, 0] });
    assert.match(r.erro, new RegExp(`não consegui falar com o servidor em http://localhost:${fechada} .*Ele está no ar\\?`));
    assert.equal(arm.escritas, 0);
    assert.deepEqual(ff.filter((u) => u.startsWith('/')), ['/smart-tv']);
    const a = await carregar({ origem: WWW, fetch: fetchNode(fechada) }).ML.afiliar({ servidor: `http://localhost:${fechada}`, gerar: gerarTodos() });
    assert.match(a.erro, /não consegui falar com o servidor/);
  });

  test('servidor em 127.0.0.1 (outro Host) também aceita a coleta e o PATCH', async () => {
    const base = `http://127.0.0.1:${srv.porta}`;
    const lista = fetchChrome(srv.porta, LISTA, []);
    const { ML } = carregar({ fetch: misto(lista, paginaDoTermo(3, ['Cooktop'])) });
    const r = await ML.coletar({ servidor: base, termos: ['Cooktop'], pausa: [0, 0] });
    assert.equal(r.erro, null);
    const a = await carregar({ origem: WWW, fetch: fetchChrome(srv.porta, WWW, []) }).ML.afiliar({ servidor: base, gerar: gerarTodos(), pausa: [0, 0] });
    assert.equal(a.erro, null);
    const itens = (await lerItens()).filter((i) => i.busca === 'Cooktop');
    assert.equal(itens.length, 3);
    assert.ok(itens.every((i) => /^https:\/\/meli\.la\/MLB\d+$/.test(i.url)));
  });

  test('duas coletas ao mesmo tempo dos mesmos itens: sem erro, sem duplicar', async () => {
    const mesma = () => pagina([polycard(300), polycard(301), polycard(302)]);
    const uma = () => carregar({ fetch: misto(fetchChrome(srv.porta, LISTA, []), mesma) }).ML.coletar({ servidor: srv.servidor, termos: ['Fogão'], pausa: [0, 0] });
    const [a, b] = await Promise.all([uma(), uma()]);
    assert.equal(a.erro, null);
    assert.equal(b.erro, null);
    assert.equal(a.inserido + b.inserido, 3);
    assert.equal(a.atualizado + b.atualizado, 3);
    const dupl = (await lerItens()).filter((i) => ['MLB6000000300', 'MLB6000000301', 'MLB6000000302'].includes(i.item_id));
    assert.equal(dupl.length, 3);
  });
});


// ================================================================== rodada 2
const ELEGIVEL2 = (u, codigo) => ({ origin_url: `${u}-x-_JM`, short_url: `https://meli.la/${codigo || mlbDe(u)}` });

describe('QA rodada 2, R1: a conferência gera os links de novo e corrige o que a 1ª geração trocou', () => {
  test('1ª geração com pares cruzados: a conferência regera, corrige no banco e repete até 0 correções', async () => {
    const sf = servidorMem(itensMl(3));
    let chamada = 0;
    const gerar = async (urls) => {
      chamada++;
      const mlbs = urls.map(mlbDe);
      return { urls: urls.map((u, i) => ({ origin_url: u, short_url: `https://meli.la/${mlbs[chamada === 1 ? (i + 1) % 3 : i]}` })) };
    };
    const r = await carregar({ origem: WWW, fetch: sf.f }).ML.afiliar({ gerar, pausa: [0, 0] });
    assert.equal(r.erro, null);
    assert.equal(chamada, 3, '1 geração do lote + volta 1 (3 correções) + volta 2 (0 correções)');
    assert.equal(r.correcoes, 3);
    assert.equal(sf.patches().length, 6);
    assert.deepEqual(js(r.divergencias), []);
    for (const i of [1, 2, 3]) assert.equal(sf.db.get(i).url, `https://meli.la/MLB410000000${i}`);
    assert.deepEqual(js(r.trocados).map((t) => t.url), [1, 2, 3].map((i) => `https://meli.la/MLB410000000${i}`));
  });

  test('item excluído entre a conferência e a correção: o PATCH volta null e o item sai dos trocados sem contar como correção', async () => {
    const sf = servidorMem(itensMl(3), (metodo, caminho, db) => {
      if (metodo === 'PATCH' && caminho === '/api/items/2' && db.get(2).url.startsWith('https://meli.la/')) {
        db.delete(2);
        return { status: 200, corpo: null };
      }
      return null;
    });
    let chamada = 0;
    const gerar = async (urls) => {
      chamada++;
      const mlbs = urls.map(mlbDe);
      return { urls: urls.map((u, i) => ({ origin_url: u, short_url: `https://meli.la/${mlbs[chamada === 1 ? (i + 1) % urls.length : i]}` })) };
    };
    const r = await carregar({ origem: WWW, fetch: sf.f }).ML.afiliar({ gerar, pausa: [0, 0] });
    assert.equal(r.erro, null);
    assert.deepEqual(js(r.trocados).map((t) => t.id), [1, 3]);
    assert.equal(r.correcoes, 2);
    assert.equal(sf.db.has(2), false);
    assert.equal(sf.db.get(1).url, 'https://meli.la/MLB4100000001');
  });

  test('links estáveis: a conferência gera uma vez, não faz PATCH e termina na 1ª volta', async () => {
    const sf = servidorMem(itensMl(3));
    const pedidos = [];
    const r = await carregar({ origem: WWW, fetch: sf.f }).ML.afiliar({ gerar: gerarTodos(pedidos), pausa: [0, 0] });
    assert.equal(pedidos.length, 2);
    assert.deepEqual(pedidos[1].sort(), itensMl(3).map((i) => i.url).sort(), 'a conferência pede a url de origem de cada tocado');
    assert.equal(sf.patches().length, 3);
    assert.equal(r.correcoes, 0);
  });

  test('links que mudam a cada geração: para em 3 voltas (4 gerações), avisa e não entra em laço', async () => {
    const sf = servidorMem(itensMl(2));
    let chamada = 0;
    const gerar = async (urls) => { chamada++; return { urls: urls.map((u) => ({ origin_url: u, short_url: `https://meli.la/G${chamada}x${mlbDe(u).slice(-1)}` })) }; };
    const { ML, mensagens } = carregar({ origem: WWW, fetch: sf.f });
    const r = await ML.afiliar({ gerar, pausa: [0, 0] });
    assert.equal(r.erro, null);
    assert.equal(chamada, 4);
    assert.equal(r.correcoes, 6);
    assert.equal(sf.patches().length, 2 + 6);
    assert.ok(mensagens.some((m) => m.tipo === 'warn' && /não chegou a 0 correções em 3 voltas/.test(m.texto)));
  });

  test('conferência em lotes de até 25 (ou do tamanho pedido) e na mesma ordem', async () => {
    for (const [lote, esperado] of [[undefined, [25, 5, 25, 5]], [10, [10, 10, 10, 10, 10, 10]]]) {
      const sf = servidorMem(itensMl(30));
      const pedidos = [];
      const r = await carregar({ origem: WWW, fetch: sf.f }).ML.afiliar({ gerar: gerarTodos(pedidos), pausa: [0, 0], lote });
      assert.equal(r.erro, null);
      assert.deepEqual(pedidos.map((p) => p.length), esperado);
      assert.equal(r.trocados.length, 30);
    }
  });

  test('com enviar:false a conferência também gera de novo e compara com o que foi gerado antes', async () => {
    let chamada = 0;
    const gerar = async (urls) => { chamada++; return { urls: urls.map((u) => ({ origin_url: u, short_url: `https://meli.la/${chamada === 1 ? 'Primeiro' : 'Segundo'}1` })) }; };
    const sf = servidorMem(itensMl(1));
    const r = await carregar({ origem: WWW, fetch: sf.f }).ML.afiliar({ enviar: false, itens: [produto(4100000001)], gerar, pausa: [0, 0] });
    assert.equal(sf.chamadas.length, 0);
    assert.equal(r.correcoes, 1);
    assert.deepEqual(js(r.trocados).map((t) => t.url), ['https://meli.la/Segundo1']);
  });

  test('parar() durante a conferência encerra sem novos PATCH e sem erro', async () => {
    let ML; let chamada = 0;
    const sf = servidorMem(itensMl(2));
    const gerar = async (urls) => { chamada++; const r = await gerarTodos()(urls); if (chamada === 2) ML.parar(); return r; };
    ({ ML } = carregar({ origem: WWW, fetch: sf.f }));
    const r = await ML.afiliar({ gerar, pausa: [0, 0] });
    assert.equal(r.erro, null);
    assert.equal(r.parado, true);
    assert.equal(chamada, 2);
    assert.equal(sf.patches().length, 2);
  });
});

describe('QA rodada 2, S3: a conferência não troca um meli.la que a execução não gravou', () => {
  test('o dono mudou o link no meio: nada é regravado, a divergência vai para o estado e para o console', async () => {
    let gets = 0;
    const sf = servidorMem(itensMl(2), (metodo, caminho, db) => {
      if (metodo === 'GET' && caminho === '/api/items' && ++gets === 1) db.get(1).url = 'https://meli.la/Dono123';
    });
    const { ML, mensagens } = carregar({ origem: WWW, fetch: sf.f });
    const r = await ML.afiliar({ gerar: gerarTodos(), pausa: [0, 0] });
    assert.equal(r.erro, null);
    assert.equal(sf.patches().length, 2, 'só os 2 PATCH da 1ª passada');
    assert.equal(sf.db.get(1).url, 'https://meli.la/Dono123');
    assert.deepEqual(js(r.divergencias), [{ id: 1, mlb: 'MLB4100000001', banco: 'https://meli.la/Dono123', gerado: 'https://meli.la/MLB4100000001' }]);
    assert.equal(r.correcoes, 0);
    assert.ok(mensagens.some((m) => m.tipo === 'warn' && /divergência no item 1/.test(m.texto) && /Não mexi/.test(m.texto)));
    assert.match(mensagens.find((m) => /fim:/.test(m.texto)).texto, /1 divergências/);
  });

  test('o link do banco ainda é o que a execução gravou: é corrigido; o do banco que veio de fora não é', async () => {
    let gets = 0;
    const sf = servidorMem(itensMl(2), (metodo, caminho, db) => {
      if (metodo === 'GET' && caminho === '/api/items' && ++gets === 1) db.get(2).url = 'https://meli.la/DeFora9';
    });
    let chamada = 0;
    const gerar = async (urls) => { chamada++; return { urls: urls.map((u) => ({ origin_url: u, short_url: `https://meli.la/${chamada === 1 ? 'Velho' : 'Novo'}${mlbDe(u).slice(-1)}` })) }; };
    const r = await carregar({ origem: WWW, fetch: sf.f }).ML.afiliar({ gerar, pausa: [0, 0] });
    assert.equal(sf.db.get(1).url, 'https://meli.la/Novo1');
    assert.equal(sf.db.get(2).url, 'https://meli.la/DeFora9');
    assert.deepEqual(js(r.divergencias).map((d) => d.id), [2, 2, 2].slice(0, r.divergencias.length));
    assert.ok(r.divergencias.length >= 1);
  });
});

describe('QA rodada 2, R2: link que não é meli.la para o lote; só erro de elegibilidade fica guardado', () => {
  test('mapearLinks marca naoMeliLa (sem error_code) e codigo (com error_code)', () => {
    const { ML } = carregar();
    const m = js(ML.mapearLinks({ urls: [
      { origin_url: produto(4100000001), short_url: 'https://evil.com/x' },
      { origin_url: produto(4100000002), short_url: null, error_code: 'ITEM_NOT_ELIGIBLE', message: 'não' },
      { origin_url: produto(4100000003), short_url: 'https://meli.la/OK3' }] }, itensMl(3)));
    assert.deepEqual(m.inelegiveis.map((e) => [e.id, e.naoMeliLa === true, e.codigo]), [[1, true, undefined], [2, false, 'ITEM_NOT_ELIGIBLE']]);
    assert.match(m.inelegiveis[0].motivo, /não é meli\.la/);
    assert.deepEqual(m.trocar.map((t) => t.id), [3]);
  });

  test('só ELIGIB/ELEGIB e url sem MLB ficam guardados; o resto volta na próxima execução e não vai para "Exclua"', async () => {
    const itens = [...itensMl(4), { id: 5, loja: 'ml', url: 'https://click1.mercadolivre.com.br/x' }];
    const sf = servidorMem(itens);
    const arm = memoria();
    const codigos = { 1: 'INTERNAL_ERROR', 2: 'ITEM_NOT_ELIGIBLE', 3: 'not_elegible_for_program' };
    const gerar = async (urls) => ({ urls: urls.map((u, i) => {
      const id = Number(mlbDe(u).slice(-1));
      return codigos[id] ? { origin_url: u, short_url: null, error_code: codigos[id], message: 'm' } : ELEGIVEL2(u);
    }) });
    const { ML, mensagens } = carregar({ origem: WWW, fetch: sf.f, localStorage: arm });
    const r = await ML.afiliar({ gerar, pausa: [0, 0] });
    assert.equal(r.erro, null);
    assert.deepEqual(js(r.inelegiveis).map((e) => e.id).sort(), [1, 2, 3, 5]);
    assert.deepEqual(arm.lista('__afiliarML:http://localhost:8765').map((e) => e.id).sort(), [2, 3, 5]);
    const exclua = mensagens.findIndex((m) => /Exclua pelo site/.test(m.texto));
    const tento = mensagens.findIndex((m) => /tento de novo na próxima execução/.test(m.texto));
    assert.ok(exclua !== -1 && tento !== -1);
    const linhas = (de, ate) => mensagens.slice(de + 1, ate).map((m) => m.texto).join('\n');
    assert.match(linhas(exclua, tento), /id 2 /);
    assert.doesNotMatch(linhas(exclua, tento), /id 1 /);
    assert.match(linhas(tento, mensagens.length), /id 1 .*INTERNAL_ERROR/);

    const pedidos = [];
    const g2 = async (urls) => { pedidos.push([...urls]); return gerar(urls); };
    await ML.afiliar({ gerar: g2, pausa: [0, 0] });
    assert.deepEqual(pedidos, [[produto(4100000001)]], 'só o item com erro que não é de elegibilidade volta ao linkbuilder');
  });

  test('link ruim na conferência para com erro "na conferência", mantém os PATCH da 1ª passada e não grava nada novo', async () => {
    const sf = servidorMem(itensMl(2));
    let chamada = 0;
    const gerar = async (urls) => {
      chamada++;
      return { urls: urls.map((u) => ({ origin_url: u, short_url: chamada === 1 ? `https://meli.la/${mlbDe(u)}` : 'https://evil.com/x' })) };
    };
    const arm = memoria();
    const r = await carregar({ origem: WWW, fetch: sf.f, localStorage: arm }).ML.afiliar({ gerar, pausa: [0, 0] });
    assert.match(r.erro, /não é meli\.la.* na conferência/);
    assert.equal(r.naoMeliLa.length, 2);
    assert.equal(sf.patches().length, 2);
    assert.deepEqual(js(r.trocados).map((t) => t.id), [1, 2]);
    assert.ok([...sf.db.values()].every((i) => i.url.startsWith('https://meli.la/MLB')));
  });
});

describe('QA rodada 2, S2: etiqueta do pedido do createLink', () => {
  const dadosOk = (urls) => ({ urls: urls.map((u) => ELEGIVEL2(u)) });
  async function rodar({ via = 'fetch', pedido, n = 2, lote } = {}) {
    const lb = linkbuilder({ dados: dadosOk, via, pedido });
    const { ctx, ML, mensagens } = carregar({ origem: WWW, fetch: lb.fetch, extras: { Response } });
    lb.montar(ctx);
    const sf = servidorMem(itensMl(n));
    const r = await ML.afiliar({ fetch: sf.f, pausa: [0, 0], lote });
    return { lb, ctx, r, sf, mensagens };
  }

  for (const via of ['fetch', 'xhr']) {
    for (const [nome, pedido] of [
      ['tag diferente', (u) => JSON.stringify({ urls: u, tag: 'outraetiqueta' })],
      ['Tag em outro nível e com outra caixa', (u) => JSON.stringify({ params: { dados: { Tag: 'outra' } }, urls: u })],
      ['achadosmenicas com espaço no fim', (u) => JSON.stringify({ urls: u, tag: 'achadosmenicas ' })],
    ]) {
      test(`${via}: ${nome} falha o lote antes do PATCH e tira o gancho`, async () => {
        const { lb, ctx, r, sf } = await rodar({ via, pedido });
        assert.match(r.erro, /o linkbuilder está gerando com a etiqueta ".*", não achadosmenicas/);
        assert.match(r.erro, /nada deste lote foi gravado/i);
        assert.equal(sf.patches().length, 0);
        assert.equal(ctx.fetch, lb.fetch);
        assert.equal(lb.XMLHttpRequest.prototype.send, lb.enviarOriginal);
        assert.equal(lb.XMLHttpRequest.prototype.open, lb.abrirOriginal);
      });
    }

    test(`${via}: tag achadosmenicas passa e o gancho não muda o que a página envia`, async () => {
      const { lb, r, sf } = await rodar({ via, pedido: (u) => JSON.stringify({ urls: u, tag: 'achadosmenicas' }) });
      assert.equal(r.erro, null);
      assert.equal(sf.patches().length, 2);
      assert.ok(lb.lotes.length >= 2);
    });

    for (const [nome, pedido] of [['sem tag', (u) => JSON.stringify({ urls: u })], ['corpo que não é JSON', (u) => u.join(',')],
      ['tag que não é texto', (u) => JSON.stringify({ urls: u, tag: 5 })]]) {
      test(`${via}: ${nome} só avisa, uma vez por execução, e segue`, async () => {
        const { r, sf, mensagens } = await rodar({ via, pedido, n: 2, lote: 1 });
        assert.equal(r.erro, null);
        assert.equal(sf.patches().length, 2);
        assert.equal(mensagens.filter((m) => m.tipo === 'warn' && /não consegui ler a etiqueta no pedido do createLink/.test(m.texto)).length, 1);
      });
    }
  }

  test('etiqueta enorme aparece truncada na mensagem de erro', async () => {
    const { r } = await rodar({ pedido: (u) => JSON.stringify({ urls: u, tag: 'x'.repeat(5000) }) });
    assert.match(r.erro, /etiqueta "x{50}"/);
    assert.ok(r.erro.length < 400);
  });
});

describe('QA rodada 2: rótulo "Links curtos" na página', () => {
  const dadosOk = (urls) => ({ urls: urls.map((u) => ELEGIVEL2(u)) });
  async function rodar(modoRotulo, n = 2, lote) {
    const lb = linkbuilder({ dados: dadosOk, modoRotulo });
    const { ctx, ML, mensagens } = carregar({ origem: WWW, fetch: lb.fetch, extras: { Response } });
    lb.montar(ctx);
    const sf = servidorMem(itensMl(n));
    const r = await ML.afiliar({ fetch: sf.f, pausa: [0, 0], lote });
    return { lb, ctx, r, sf, mensagens };
  }

  test('sem o rótulo: erro claro, nada gerado, nada gravado e o gancho sai', async () => {
    const { lb, ctx, r, sf } = await rodar('ausente');
    assert.match(r.erro, /não achei a opção "Links curtos"/);
    assert.equal(lb.botao.cliques, 0);
    assert.equal(sf.patches().length, 0);
    assert.equal(ctx.fetch, lb.fetch);
  });

  test('controle que não dá para ler: não clica no rótulo (poderia desligar), avisa uma vez e segue', async () => {
    const { lb, r, sf, mensagens } = await rodar('sem-controle', 2, 1);
    assert.equal(r.erro, null);
    assert.equal(lb.rotulo.cliques, 0);
    assert.ok(lb.botao.cliques >= 2);
    assert.equal(sf.patches().length, 2);
    assert.equal(mensagens.filter((m) => /não consegui ver se "Links curtos" está ligado/.test(m.texto)).length, 1);
  });

  test('desligado: clica uma vez, confere que ligou e segue', async () => {
    const { lb, r } = await rodar('desligado', 2, 1);
    assert.equal(r.erro, null);
    assert.equal(lb.rotulo.cliques, 1);
  });

  test('o clique não liga: para antes de gerar com "não consegui ligar"', async () => {
    const { lb, r, sf } = await rodar('trava');
    assert.match(r.erro, /não consegui ligar "Links curtos"/);
    assert.equal(lb.botao.cliques, 0);
    assert.equal(sf.patches().length, 0);
  });

  test('ligado: não clica no rótulo', async () => {
    const { lb, r } = await rodar('ligado');
    assert.equal(r.erro, null);
    assert.equal(lb.rotulo.cliques, 0);
  });
});

describe('QA rodada 2, R4: guarda de origem e de caminho do afiliar()', () => {
  const ruins = ['/', '/afiliados', '/afiliados/', '/afiliados/outra', '/vendas/afiliados/linkbuilder', '/login'];
  for (const caminho of ruins) {
    test(`pathname ${caminho} no www recusa sem fazer nada`, async () => {
      const sf = servidorMem(itensMl(2));
      const pedidos = [];
      const r = await carregar({ origem: WWW, caminho, fetch: sf.f }).ML.afiliar({ gerar: gerarTodos(pedidos) });
      assert.match(r.erro, /só roda numa aba de https:\/\/www\.mercadolivre\.com\.br\/afiliados\/linkbuilder/);
      assert.match(r.erro, /Nada foi feito/);
      assert.equal(sf.chamadas.length + pedidos.length, 0);
    });
  }

  test('guarda estrita: location sem pathname (ou com pathname que não é texto) recusa o afiliar()', async () => {
    for (const caminho of [null, 42, undefined === 0 ? 0 : '']) {
      const sf = servidorMem(itensMl(1));
      const r = await carregar({ origem: WWW, caminho, fetch: sf.f }).ML.afiliar({ gerar: gerarTodos() });
      assert.match(r.erro, /só roda numa aba/, String(caminho));
      assert.equal(sf.chamadas.length, 0);
    }
    const ctx = { console: { log() {}, warn() {}, error() {} }, location: { origin: WWW }, localStorage: memoria() };
    vm.createContext(ctx);
    vm.runInContext(FONTE, ctx);
    const sf = servidorMem(itensMl(1));
    const r = await ctx.ColetaML.afiliar({ fetch: sf.f, gerar: gerarTodos() });
    assert.match(r.erro, /só roda numa aba/);
    assert.equal(sf.chamadas.length, 0);
  });

  for (const caminho of ['/afiliados/linkbuilder', '/afiliados/linkbuilder/']) {
    test(`pathname ${caminho} no www roda`, async () => {
      const sf = servidorMem(itensMl(1));
      const r = await carregar({ origem: WWW, caminho, fetch: sf.f }).ML.afiliar({ gerar: gerarTodos(), pausa: [0, 0] });
      assert.equal(r.erro, null);
      assert.equal(r.trocados.length, 1);
    });
  }

  test('o pathname certo em outra origem continua recusado, e coletar() não olha o pathname', async () => {
    const sf = servidorMem(itensMl(1));
    const r = await carregar({ origem: 'https://example.com', caminho: '/afiliados/linkbuilder', fetch: sf.f }).ML.afiliar({ gerar: gerarTodos() });
    assert.match(r.erro, /só roda numa aba/);
    const ff = fetchFalso();
    const c = await carregar({ caminho: '/smart-tv_NoIndex_True', fetch: ff.f }).ML.coletar({ termos: ['Smart TV'] });
    assert.equal(c.erro, null);
  });
});

describe('QA rodada 2, R6 e S4: gravarLink e chamadas ao servidor sem Referer', () => {
  const chamar = (ML, f, t) => ML._interno.gravarLink(f, 'http://localhost:8765', t);

  test('_interno está congelado e expõe só gravarLink', () => {
    const { ML } = carregar();
    assert.deepEqual(Object.keys(ML._interno), ['gravarLink']);
    assert.ok(Object.isFrozen(ML._interno));
  });

  const urlsRuins = ['https://www.mercadolivre.com.br/MLB-1', produto(4100000001), 'http://meli.la/abc', 'https://meli.la/', 'https://meli.la/a/b',
    'https://meli.la/abc?x=1', 'https://meli.la.evil.com/abc', 'https://www.amazon.com.br/dp/B000?tag=desejodemen01-20', '', null, undefined, 5, ['https://meli.la/abc']];
  for (const u of urlsRuins) {
    test(`gravarLink recusa url ${JSON.stringify(u)} sem chamar o fetch`, async () => {
      const ff = fetchFalso();
      const { ML } = carregar();
      const r = await chamar(ML, ff.f, { id: 1, url: u });
      assert.match(r.erro, /link ou id inválido para o item 1; nada foi enviado/);
      assert.equal(ff.chamadas.length, 0);
    });
  }

  for (const id of [0, -1, 1.5, '1', NaN, null, undefined]) {
    test(`gravarLink recusa id ${String(id)} sem chamar o fetch`, async () => {
      const ff = fetchFalso();
      const r = await chamar(carregar().ML, ff.f, { id, url: 'https://meli.la/abc' });
      assert.match(r.erro, /link ou id inválido/);
      assert.equal(ff.chamadas.length, 0);
    });
  }

  test('gravarLink faz um PATCH só com {url}, JSON, credentials omit e sem Referer', async () => {
    const ff = fetchFalso({ servidor: async () => ({ status: 200, corpo: { id: 7 } }) });
    const r = await chamar(carregar().ML, ff.f, { id: 7, url: 'https://meli.la/AbC123', cat: 'x', data: {} });
    assert.deepEqual(js(r), { ok: true, existe: true });
    assert.equal(ff.chamadas.length, 1);
    const c = ff.chamadas[0];
    assert.equal(c.url, 'http://localhost:8765/api/items/7');
    assert.deepEqual([c.init.method, c.init.credentials, c.init.referrerPolicy], ['PATCH', 'omit', 'no-referrer']);
    assert.deepEqual(js(c.init.headers), { 'Content-Type': 'application/json' });
    assert.equal(c.init.body, '{"url":"https://meli.la/AbC123"}');
  });

  test('gravarLink: resposta null (item excluído) vira existe:false; 400/403/415/500 e rede caída viram erro', async () => {
    const { ML } = carregar();
    let r = await chamar(ML, fetchFalso({ servidor: async () => ({ status: 200, corpo: null }) }).f, { id: 1, url: 'https://meli.la/a' });
    assert.deepEqual(js(r), { ok: true, existe: false });
    for (const status of [400, 403, 415, 500]) {
      r = await chamar(ML, fetchFalso({ servidor: async () => ({ status, corpo: { error: 'não' } }) }).f, { id: 1, url: 'https://meli.la/a' });
      assert.match(r.erro, new RegExp(`recusou o link do item 1 com ${status}: não`));
    }
    r = await chamar(ML, async () => { throw new TypeError('Failed to fetch'); }, { id: 1, url: 'https://meli.la/a' });
    assert.match(r.erro, /não consegui falar com o servidor em http:\/\/localhost:8765/);
  });

  test('toda chamada ao servidor (POST da coleta, GET e PATCH do afiliar) leva credentials omit e referrerPolicy no-referrer', async () => {
    const ff = fetchFalso();
    await carregar({ fetch: ff.f }).ML.coletar({ termos: ['Smart TV'] });
    const sf = servidorMem(itensMl(2));
    await carregar({ origem: WWW, fetch: sf.f }).ML.afiliar({ gerar: gerarTodos(), pausa: [0, 0] });
    const todas = [...ff.doServidor(), ...sf.chamadas];
    assert.ok(todas.length >= 6);
    assert.ok(todas.some((c) => (c.init.method || 'GET') === 'GET') && todas.some((c) => c.init.method === 'PATCH') && todas.some((c) => c.init.method === 'POST'));
    for (const c of todas) assert.deepEqual([c.init.credentials, c.init.referrerPolicy], ['omit', 'no-referrer'], `${c.init.method || 'GET'} ${c.url}`);
  });
});

// ------------------------------------------------------------------ CA4 e CA6 (perfumaria nas três lojas): QA da ordem e dos 42 termos
describe('perfumaria (E3 e E6): ordem "caros", 42 termos e compatibilidade do progresso', () => {
  const CHAVE = '__coletaML:http://localhost:8765';
  const PERFUMES = 'Perfumes e Perfumaria';
  const SUFIXO = '_OrderId_PRICE*DESC';
  // os 28 termos da aba antes da E3, congelados aqui: o progresso gravado no navegador do dono usa o termo puro
  const ANTIGOS_28 = ['Perfume masculino importado', 'Perfume feminino importado', 'Perfume masculino nacional',
    'Perfume feminino nacional', 'Kit perfume', 'Miniatura de perfume', 'Body splash', 'Desodorante colônia',
    'Hidratante corporal perfumado', 'Perfume árabe', 'Perfume infantil', 'Perfume Natura', 'Natura Kaiak',
    'Natura Essencial', 'Perfume O Boticário', 'Malbec O Boticário', 'Egeo O Boticário', 'Perfume Eudora',
    'Carolina Herrera 212 VIP', 'Carolina Herrera Good Girl', 'Paco Rabanne One Million', 'Paco Rabanne Invictus',
    'Dior Sauvage', 'Lancôme La Vie Est Belle', 'Calvin Klein CK One', 'Jean Paul Gaultier Le Male',
    'Azzaro Pour Homme', 'Lattafa'];

  test('o bloco BUSCAS do script tem os 42 termos de perfumaria iguais ao buscas.json, em NFC e sem barra vertical', () => {
    const { ML } = carregar();
    assert.equal(BUSCAS_JSON[PERFUMES].length, 42);
    assert.deepEqual(js(ML.BUSCAS[PERFUMES]), BUSCAS_JSON[PERFUMES]);
    for (const t of ML.BUSCAS[PERFUMES]) {
      assert.equal(t, t.normalize('NFC'));
      assert.ok(!t.includes('|'), t);
    }
    for (const antigo of ANTIGOS_28) assert.ok(ML.BUSCAS[PERFUMES].includes(antigo), antigo);
  });

  test('os 42 termos dão 42 buscas diferentes na relevância e em "caros"; a URL de "caros" é a da relevância mais o sufixo', async () => {
    const termos = BUSCAS_JSON[PERFUMES];
    const rel = fetchFalso(), caros = fetchFalso();
    await carregar({ fetch: rel.f }).ML.coletar({ termos, enviar: false, pausa: [0, 0] });
    await carregar({ fetch: caros.f }).ML.coletar({ termos, enviar: false, pausa: [0, 0], ordem: 'caros' });
    const urlsRel = rel.doML().map((c) => c.url), urlsCaros = caros.doML().map((c) => c.url);
    assert.equal(urlsRel.length, 42);
    assert.equal(new Set(urlsRel).size, 42, 'dois termos com o mesmo slug fariam a mesma busca duas vezes');
    assert.deepEqual(urlsCaros, urlsRel.map((u) => u + SUFIXO));
    assert.ok(urlsRel.every((u) => /^\/[a-z0-9]+(-[a-z0-9]+)*$/.test(u)), 'a relevância não leva sufixo nem caractere estranho');
  });

  test('a URL exata de alguns termos novos: acento, til e hífen viram o slug certo e o sufixo vai no fim', async () => {
    const ff = fetchFalso();
    await carregar({ fetch: ff.f }).ML.coletar({
      termos: ['Óleo corporal perfumado', 'Loção pós-barba', 'Colônia feminina', 'Perfume árabe masculino'], enviar: false, pausa: [0, 0], ordem: 'caros' });
    assert.deepEqual(ff.doML().map((c) => c.url), [
      '/oleo-corporal-perfumado' + SUFIXO, '/locao-pos-barba' + SUFIXO, '/colonia-feminina' + SUFIXO, '/perfume-arabe-masculino' + SUFIXO]);
  });

  test('o progresso antigo (28 termos puros no localStorage) faz a relevância buscar só os 14 novos', async () => {
    const ff = fetchFalso();
    const antigo = memoria({ [CHAVE]: JSON.stringify(ANTIGOS_28) });
    const { ML } = carregar({ fetch: ff.f, localStorage: antigo });
    const r = await ML.coletar({ termos: BUSCAS_JSON[PERFUMES], pausa: [0, 0] });
    assert.equal(r.erro, null);
    assert.equal(js(r.pulados).length, 28);
    assert.equal(js(r.feitos).length, 14);
    assert.equal(ff.doML().length, 14);
    const novos = BUSCAS_JSON[PERFUMES].filter((t) => !ANTIGOS_28.includes(t));
    assert.deepEqual(js(r.feitos), novos);
    assert.deepEqual(antigo.lista(CHAVE), [...ANTIGOS_28, ...novos], 'a relevância só acrescenta o termo puro');
    // e "caros" ainda não foi feito para nenhum
    const caros = await ML.coletar({ termos: BUSCAS_JSON[PERFUMES], pausa: [0, 0], ordem: 'caros' });
    assert.equal(js(caros.feitos).length, 42);
    assert.equal(js(caros.pulados).length, 0);
  });

  test('ordem "caros" sem lista de termos percorre os 140 do arquivo, cada um com o sufixo e a chave caros|termo', async () => {
    const ff = fetchFalso();
    const arm = memoria();
    const { ML } = carregar({ fetch: ff.f, localStorage: arm });
    const r = await ML.coletar({ ordem: 'caros', pausa: [0, 0] });
    assert.equal(r.erro, null);
    assert.equal(ff.doML().length, 140);
    assert.ok(ff.doML().every((c) => c.url.endsWith(SUFIXO)));
    assert.deepEqual(arm.lista(CHAVE), TODOS_TERMOS.map(([t]) => 'caros|' + t));
    const n = ff.chamadas.length;
    const de_novo = await ML.coletar({ ordem: 'caros', pausa: [0, 0] });
    assert.equal(ff.chamadas.length, n, 'segunda volta não busca nada');
    assert.equal(js(de_novo.pulados).length, 140);
  });

  test('cada termo de "caros" vai ao servidor com a cat e a busca do termo, loja ml e no máximo 30 itens', async () => {
    const muitos = pagina(Array.from({ length: 45 }, (_, i) => polycard(i + 1)));
    const ff = fetchFalso({ paginaDe: () => muitos });
    await carregar({ fetch: ff.f }).ML.coletar({ termos: ['Perfume unissex', 'Kit sabonete perfumado'], ordem: 'caros', pausa: [0, 0] });
    const posts = ff.doServidor().map((c) => JSON.parse(c.init.body));
    assert.equal(posts.length, 2);
    for (const [i, termo] of ['Perfume unissex', 'Kit sabonete perfumado'].entries()) {
      assert.equal(posts[i].items.length, 30);
      assert.ok(posts[i].items.every((it) => it.cat === PERFUMES && it.busca === termo && it.loja === 'ml'));
    }
  });

  test('captcha no meio de uma volta "caros" mantém só as chaves caros| já gravadas e a retomada continua dali', async () => {
    const arm = memoria({ [CHAVE]: JSON.stringify(['Smart TV']) });   // relevância antiga de outro termo
    let captcha = true;
    const ff = fetchFalso();
    const f = async (url, init = {}) => {
      if (captcha && url.startsWith('/body-splash')) return resposta(200, '<html>captcha</html>', 'https://www.mercadolivre.com.br/gz/account-verification');
      return ff.f(url, init);
    };
    const { ML } = carregar({ fetch: f, localStorage: arm });
    let r = await ML.coletar({ termos: ['Smart TV', 'Body splash', 'Geladeira'], ordem: 'caros', pausa: [0, 0] });
    assert.match(r.erro, /captcha/);
    assert.deepEqual(arm.lista(CHAVE), ['Smart TV', 'caros|Smart TV']);
    captcha = false;
    r = await ML.coletar({ termos: ['Smart TV', 'Body splash', 'Geladeira'], ordem: 'caros', pausa: [0, 0] });
    assert.equal(r.erro, null);
    assert.deepEqual(js(r.pulados), ['Smart TV']);
    assert.deepEqual(js(r.feitos), ['Body splash', 'Geladeira']);
    assert.deepEqual(arm.lista(CHAVE), ['Smart TV', 'caros|Smart TV', 'caros|Body splash', 'caros|Geladeira']);
  });

  for (const [nome, ordem] of [['array', ['caros']], ['String objeto', new String('caros')], ['com espaço antes', ' caros'],
    ['com espaço depois', 'caros '], ['Relevancia maiúscula', 'Relevancia'], ['relevância com acento', 'relevância'], ['maior_preco', 'maior_preco'],
    ['toString', 'toString'], ['hasOwnProperty', 'hasOwnProperty'], ['função', () => 'caros'], ['true', true], ['NaN', NaN]]) {
    test(`ordem inválida (${nome}) é recusada antes de qualquer fetch, escrita ou estado rodando`, async () => {
      const ff = fetchFalso();
      const { ML, localStorage } = carregar({ fetch: ff.f });
      const r = await ML.coletar({ termos: ['Smart TV'], ordem });
      assert.match(r.erro, /ordem deve ser uma destas: relevancia, caros/);
      assert.equal(ff.chamadas.length, 0);
      assert.equal(localStorage.escritas, 0);
      assert.equal(r.rodando, false);
      // e a coleta seguinte (válida) funciona: nada ficou travado
      const ok = await ML.coletar({ termos: ['Smart TV'], ordem: 'caros', enviar: false });
      assert.equal(ok.erro, null);
    });
  }

  test('a coleta em "caros" só fala com o ML por GET na listagem e com o servidor por POST, sem outras rotas', async () => {
    const ff = fetchFalso();
    await carregar({ fetch: ff.f }).ML.coletar({ termos: ['Perfume para cabelo'], ordem: 'caros', pausa: [0, 0] });
    assert.deepEqual(ff.doML().map((c) => [c.init.method || 'GET', c.url]), [['GET', '/perfume-para-cabelo' + SUFIXO]]);
    assert.deepEqual(ff.doServidor().map((c) => [c.init.method, c.url]), [['POST', 'http://localhost:8765/api/items']]);
  });
});
