// Testes do coletar_ml.js (docs/produto/planos/eletronicos-e-coleta-ml.md, etapa 4).
//
// Uso:  node --test testes/coletar_ml.test.mjs
//
// O arquivo é carregado com node:vm, como se fosse colado no console de uma aba do ML (location falso).
// O ML de verdade nunca é acessado: a página vem de testes/fixtures/ml-busca.html.
// A integração sobe o servidor.py com ACHADINHOS_DB num diretório temporário e ACHADINHOS_PORTA livre,
// com proxies mortos no ambiente, e fala com ele por node:http mandando a Origin do ML.
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
const FIXTURE = fs.readFileSync(path.join(RAIZ, 'testes', 'fixtures', 'ml-busca.html'), 'utf8');
const BUSCAS_JSON = JSON.parse(fs.readFileSync(path.join(RAIZ, 'buscas.json'), 'utf8'));
// Estado de 2026-11-04 (4 abas) congelado: o que vale só para o histórico aponta para cá.
const ABAS_17 = ['Celulares e Informática', 'Áudio e Acessórios', 'TV, Alexa e Casa Conectada', 'Games',
  'Eletroportáteis', 'Eletrodomésticos e Climatização', 'Cozinha', 'Cama, Mesa e Banho',
  'Casa, Móveis e Ferramentas', 'Beleza e Cuidados', 'Perfumes e Perfumaria', 'Mercado e Limpeza', 'Pets',
  'Bebês e Brinquedos', 'Suplementos e Fitness', 'Moda e Viagem', 'Natal e Papelaria'];
const CREATELINK = JSON.parse(fs.readFileSync(path.join(RAIZ, 'testes', 'fixtures', 'ml-createlink.json'), 'utf8'));
const LISTA = 'https://lista.mercadolivre.com.br';
const WWW = 'https://www.mercadolivre.com.br';
const SERVIDOR = 'http://localhost:8765';
const CAMPOS = ['titulo', 'preco', 'preco_antigo', 'desconto', 'avaliacao', 'num_avaliacoes',
  'vendas', 'frete', 'cupom', 'imagem'];
const ABA_TV = 'TV, Alexa e Casa Conectada';   // aba do termo 'Smart TV'

// objetos do contexto vm têm outros protótipos: compara pelo JSON
const js = (v) => JSON.parse(JSON.stringify(v));

/** O bloco que deve estar entre os marcadores do coletar_ml.js, gerado de buscas.json. */
function blocoBuscas(b) {
  const corpo = JSON.stringify(b, null, 2).split('\n').map((l, i) => (i ? '  ' + l : l)).join('\n');
  return `  // BUSCAS:inicio\n  const BUSCAS = ${corpo};\n  // BUSCAS:fim`;
}

/** localStorage em memória que conta as escritas. */
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

/**
 * Carrega o coletar_ml.js num contexto vm. origem null = sem location. caminho = location.pathname
 * (padrão: o linkbuilder no www e "/" nas outras origens; null = location sem pathname).
 */
function carregar({ origem = LISTA, caminho, fetch, localStorage = memoria() } = {}) {
  const mensagens = [];
  const registrar = (tipo) => (...a) => mensagens.push({ tipo, texto: a.map(String).join(' ') });
  const ctx = {
    console: { log: registrar('log'), warn: registrar('warn'), error: registrar('error') },
    setTimeout, clearTimeout, AbortController, localStorage,
    fetch: fetch || (async () => { throw new Error('fetch global não devia ser chamado'); }),
  };
  if (origem !== null) {
    const pathname = caminho === undefined ? (origem === WWW ? '/afiliados/linkbuilder' : '/') : caminho;
    ctx.location = pathname === null ? { origin: origem } : { origin: origem, pathname };
  }
  vm.createContext(ctx);
  vm.runInContext(FONTE, ctx, { filename: 'coletar_ml.js' });
  return { ctx, ML: ctx.ColetaML, mensagens, localStorage };
}

function resposta(status, corpo, url) {
  const texto = typeof corpo === 'string' ? corpo : JSON.stringify(corpo);
  return { ok: status >= 200 && status < 300, status, url, text: async () => texto, json: async () => JSON.parse(texto) };
}

/** Página da fixture com os MLB trocados por termo, para termos diferentes darem itens diferentes. */
function paginaPorSlug(url) {
  return url === '/body-splash' ? FIXTURE.replaceAll('MLB41', 'MLB42') : FIXTURE;
}

/**
 * fetch falso: caminho relativo é a página do ML (fixture); o resto é o servidor.
 * servidor(url, init) devolve {status, corpo}; o padrão aceita tudo como inserido.
 */
function fetchFalso({ pagina = paginaPorSlug, urlFinal, statusML = 200, servidor, aoBuscar } = {}) {
  const chamadas = [];
  const f = async (url, init = {}) => {
    chamadas.push({ url: String(url), init });
    if (String(url).startsWith('/')) {
      if (aoBuscar) await aoBuscar(url);
      return resposta(statusML, pagina(url), urlFinal || LISTA + url);
    }
    const r = servidor ? await servidor(url, init)
      : { status: 200, corpo: { inserido: JSON.parse(init.body).items.length, atualizado: 0, total: 99 } };
    return resposta(r.status, r.corpo, String(url));
  };
  return { f, chamadas, doML: () => chamadas.filter((c) => c.url.startsWith('/')),
    doServidor: () => chamadas.filter((c) => !c.url.startsWith('/')) };
}

const ALT_NO_PISO = 'Classificação 4.8 de 5 estrelas. Mais de 100 produtos vendidos.';
const ITEM_TV = {
  loja: 'ml', item_id: 'MLB4100000001', cat: ABA_TV, busca: 'Smart TV',
  url: 'https://produto.mercadolivre.com.br/MLB-4100000001',
  data: {
    titulo: 'Smart TV Samsung 50" Crystal UHD 4K {2025}', preco: 'R$ 2.569', preco_antigo: 'R$ 2.999',
    desconto: '-14%', avaliacao: '4.8 de 5 estrelas', num_avaliacoes: '', vendas: 'Mais de 1000 produtos vendidos',
    frete: 'Frete grátis', cupom: '', imagem: 'https://http2.mlstatic.com/D_Q_NP_2X_703732-MLB117693747961_092026-E.webp',
  },
};
const ITEM_BOX = {
  loja: 'ml', item_id: 'MLB4100000002', cat: ABA_TV, busca: 'Smart TV',
  url: 'https://produto.mercadolivre.com.br/MLB-4100000002',
  data: {
    titulo: "TV Box D'Ouro <Ultra> 4K", preco: 'R$ 124,20', preco_antigo: 'R$ 130,74', desconto: '-5%',
    avaliacao: '4.6 de 5 estrelas', num_avaliacoes: '', vendas: 'Mais de 120 produtos vendidos', frete: '',
    cupom: '', imagem: 'https://http2.mlstatic.com/D_Q_NP_2X_611234-MLA100016350069_122025-E.webp',
  },
};
const ITEM_SUPORTE = {
  loja: 'ml', item_id: 'MLB4100000003', cat: ABA_TV, busca: 'Smart TV',
  url: 'https://produto.mercadolivre.com.br/MLB-4100000003',
  data: {
    titulo: 'Suporte de parede para TV', preco: 'R$ 1.877', preco_antigo: '', desconto: '',
    avaliacao: '4.5 de 5 estrelas', num_avaliacoes: '', vendas: 'Mais de 50 produtos vendidos', frete: 'Frete grátis', cupom: '',
    imagem: 'https://http2.mlstatic.com/D_Q_NP_2X_978870-MLM89623083412_082025-E.webp',
  },
};

// ------------------------------------------------------------------ arquivo
describe('arquivo colado no console (CA11)', () => {
  test('carregar só define ColetaML e não chama fetch nem localStorage', () => {
    let fetches = 0;
    const antes = new Set(Object.keys(vm.createContext({})));
    const { ctx, localStorage } = carregar({ fetch: async () => { fetches++; } });
    const novos = Object.keys(ctx).filter((k) => !antes.has(k) &&
      !['console', 'setTimeout', 'clearTimeout', 'AbortController', 'localStorage', 'fetch', 'location'].includes(k));
    assert.deepEqual(novos, ['ColetaML']);
    assert.equal(fetches, 0);
    assert.equal(localStorage.escritas, 0);
    assert.equal(ctx.ColetaML.estado, null);
  });

  test('pode ser colado duas vezes na mesma aba', () => {
    const { ctx } = carregar();
    assert.doesNotThrow(() => vm.runInContext(FONTE, ctx));
    assert.equal(typeof ctx.ColetaML.coletar, 'function');
  });

  test('sem import/export, sem DELETE e sem eval, Function, HTML ou cookie', () => {
    assert.doesNotMatch(FONTE, /^\s*(import|export)\b/m);
    assert.doesNotMatch(FONTE, /DELETE/);
    assert.doesNotMatch(FONTE, /\beval\s*\(|\bFunction\s*\(/);
    assert.doesNotMatch(FONTE, /innerHTML|outerHTML|insertAdjacentHTML|document\.write|DOMParser/);
    assert.doesNotMatch(FONTE, /cookie|token/i);
  });
});

// ------------------------------------------------------------------ BUSCAS
describe('BUSCAS igual a buscas.json (CA13)', () => {
  test('o bloco entre os marcadores é a cópia literal de buscas.json', (t) => {
    const ini = FONTE.indexOf('  // BUSCAS:inicio');
    const fim = FONTE.indexOf('// BUSCAS:fim');
    assert.ok(ini !== -1 && fim > ini, 'faltam os marcadores // BUSCAS:inicio e // BUSCAS:fim');
    assert.equal(FONTE.split('// BUSCAS:inicio').length, 2, 'marcador // BUSCAS:inicio repetido');
    const atual = FONTE.slice(ini, fim + '// BUSCAS:fim'.length);
    const certo = blocoBuscas(BUSCAS_JSON);
    if (atual !== certo) {
      t.diagnostic('buscas.json mudou: troque o bloco do coletar_ml.js por este');
      console.log('\n' + certo + '\n');
    }
    assert.equal(atual, certo, 'o bloco BUSCAS do coletar_ml.js diverge de buscas.json (bloco certo impresso acima)');
  });

  test('ColetaML.BUSCAS tem as mesmas chaves, termos e ordem', (t) => {
    const { ML } = carregar();
    const igual = JSON.stringify(ML.BUSCAS) === JSON.stringify(BUSCAS_JSON);
    if (!igual) console.log('\n' + blocoBuscas(BUSCAS_JSON) + '\n');
    assert.ok(igual, 'ColetaML.BUSCAS diverge de buscas.json (bloco certo impresso acima)');
    assert.ok(Object.isFrozen(ML.BUSCAS) && Object.isFrozen(ML.BUSCAS[ABA_TV]));
  });

  test('buscas.json tem as 17 abas do mapa do dono, com esses nomes e nessa ordem (CA1)', () => {
    assert.deepEqual(Object.keys(BUSCAS_JSON), ABAS_17);
    const { ML } = carregar();
    assert.deepEqual(Object.keys(ML.BUSCAS), ABAS_17);
    for (const aba of ABAS_17) assert.ok(BUSCAS_JSON[aba].length > 0, aba + ' sem termos');
  });

  test('categoriaDe segue buscas.json e o ALIAS', () => {
    const { ML } = carregar();
    assert.equal(ML.categoriaDe('Smart TV'), ABA_TV);
    assert.equal(ML.categoriaDe('Caixa inteligente assistente virtual'), ABA_TV);
    assert.equal(ML.categoriaDe('Smart speaker Alexa'), ABA_TV);
    assert.equal(ML.categoriaDe('Geladeira'), 'Eletrodomésticos e Climatização');
    assert.equal(ML.categoriaDe('Sofa\u0301'), 'Casa, Móveis e Ferramentas');   // NFD vira NFC
    assert.equal(ML.categoriaDe(' Body splash '), 'Perfumes e Perfumaria');
    for (const t of ['Black Friday', 'Casa Nova', 'constructor', '__proto__', '', 'smart tv']) {
      assert.equal(ML.categoriaDe(t), null, t);
    }
    assert.equal(ML.categoriaDe(null), null);
    for (const [cat, termos] of Object.entries(BUSCAS_JSON)) {
      for (const termo of termos) assert.equal(ML.categoriaDe(termo), cat, termo);
    }
  });

  test('slug: sem acento, minúsculas e "-" no lugar do resto', () => {
    const { ML } = carregar();
    assert.equal(ML.slug('Máquina de lavar'), 'maquina-de-lavar');
    assert.equal(ML.slug('Smart TV 4K Samsung 50'), 'smart-tv-4k-samsung-50');
    assert.equal(ML.slug('Lava-louças'), 'lava-loucas');
    assert.equal(ML.slug('Lancôme La Vie Est Belle'), 'lancome-la-vie-est-belle');
    assert.equal(ML.slug('Black Friday | Eletrônicos'), 'black-friday-eletronicos');
    assert.equal(ML.slug('  Perfume árabe!  '), 'perfume-arabe');
  });
});

// ------------------------------------------------------------------ parser
describe('parser da página de busca (CA12)', () => {
  test('literalQ acha o .q("...") com polycard e decodifica \\\' e \\x3C', () => {
    const { ML } = carregar();
    const texto = ML.literalQ(FIXTURE);
    assert.equal(typeof texto, 'string');
    assert.ok(texto.includes('"polycard"'));
    assert.ok(texto.includes("TV Box D'Ouro <Ultra> 4K"));
    assert.ok(!texto.includes('siteId'), 'pegou o .q("...") sem polycard');
  });

  test('extrairItens devolve os 3 válidos no formato do banco', () => {
    const { ML } = carregar();
    const itens = js(ML.extrairItens(FIXTURE, 'Smart TV', ABA_TV, 30));
    assert.deepEqual(itens, [ITEM_TV, ITEM_BOX, ITEM_SUPORTE]);
    for (const it of itens) {
      assert.match(it.item_id, /^MLB\d+$/);
      assert.match(it.url, /^https:\/\/produto\.mercadolivre\.com\.br\/MLB-\d+$/);
      assert.deepEqual(Object.keys(it.data), CAMPOS);
      assert.ok(Object.values(it.data).every((v) => typeof v === 'string'));
    }
  });

  test('ignora id repetido, card sem título e a url click1 do anúncio', () => {
    const { ML } = carregar();
    const itens = js(ML.extrairItens(FIXTURE, 'Smart TV', ABA_TV, 30));
    assert.equal(itens.filter((i) => i.item_id === 'MLB4100000001').length, 1);
    assert.ok(!itens.some((i) => i.data.titulo.includes('repetido')));
    assert.ok(!itens.some((i) => i.item_id === 'MLB4100000005'));
    assert.ok(FIXTURE.includes('click1.mercadolivre'));
    assert.ok(!itens.some((i) => i.url.includes('click1')));
  });

  test('respeita o máximo por termo', () => {
    const { ML } = carregar();
    assert.equal(ML.extrairItens(FIXTURE, 'Smart TV', ABA_TV, 2).length, 2);
    assert.equal(ML.extrairItens(FIXTURE, 'Smart TV', ABA_TV).length, 3);
  });

  test('página sem polycard, captcha ou vazia não gera itens', () => {
    const { ML } = carregar();
    const semPoly = '<script>_n.ctx.s["x"].q("{\\"results\\":[]}")</script>';
    const captcha = '<html><body><form action="/captcha">Confirme que você é humano</form></body></html>';
    for (const h of [semPoly, captcha, '', null, '.q("sem fim']) {
      assert.equal(ML.literalQ(h), null);
      assert.deepEqual(js(ML.extrairItens(h, 'Smart TV', ABA_TV, 30)), []);
    }
  });

  test('literal .q("…") sem fim não esconde o próximo, que tem os polycards', () => {
    const { ML } = carregar();
    const html = '<script>a.q("quebrado\n</script>' + FIXTURE;
    assert.equal(ML.extrairItens(html, 'Smart TV', ABA_TV, 30).length, 3);
  });

  test('chaves e barras dentro de strings não quebram o balanceamento', () => {
    const { ML } = carregar();
    const titulo = 'barra \\ chave } aspa " apóstrofo \' menor <';
    const interno = JSON.stringify({ r: [{ polycard: { metadata: { id: 'MLB1234567' },
      components: [{ type: 'title', title: { text: titulo } }, { type: 'review_compacted', review_compacted: { alt_text: ALT_NO_PISO } }] } },
      { polycard: 'não é objeto' }] });
    const literal = JSON.stringify(interno).replace(/'/g, "\\'").replace(/</g, '\\x3C');
    const itens = js(ML.extrairItens(`<script>a.q(${literal});</script>`, 'Smart TV', ABA_TV, 30));
    assert.equal(itens.length, 1);
    assert.equal(itens[0].data.titulo, titulo);
    assert.equal(itens[0].data.preco, '');
  });

  test('polycardParaItem recusa card sem MLB ou sem título e limpa valores estranhos', () => {
    const { ML } = carregar();
    const tit = { type: 'title', title: { text: 'Produto' } };
    for (const pc of [null, [], 'x', {}, { metadata: { id: 'XYZ1234567' }, components: [tit] },
      { metadata: { id: 'MLB12' }, components: [tit] }, { metadata: { id: 'MLB1234567' } },
      { metadata: { id: 'MLB1234567' }, components: [{ type: 'title', title: { text: '   ' } }] }]) {
      assert.equal(ML.polycardParaItem(pc), null, JSON.stringify(pc));
    }
    const it = js(ML.polycardParaItem({
      metadata: { id: 'MLB1234567' }, pictures: { pictures: [{ id: '"><img src=x>' }] },
      components: [tit, { type: 'price', price: { current_price: { value: '99' }, x: { previous: true, value: 50 } } }],
    }));
    assert.equal(it.url, 'https://produto.mercadolivre.com.br/MLB-1234567');
    assert.equal(it.data.imagem, '');
    assert.equal(it.data.preco, '');
    const barato = js(ML.polycardParaItem({ metadata: { id: 'MLB1234567' },
      components: [tit, { type: 'price', price: { current_price: { value: 100 }, p: { previous: true, value: 90 } } }] }));
    assert.equal(barato.data.preco, 'R$ 100');
    assert.equal(barato.data.preco_antigo, '');
    assert.equal(barato.data.desconto, '');
    // diferença que arredonda para 0% não vira "-0%" (Q1); 0,5% já arredonda para 1%
    const quase = (antes) => js(ML.polycardParaItem({ metadata: { id: 'MLB1234567' },
      components: [tit, { type: 'price', price: { current_price: { value: 99.6 }, p: { previous: true, value: antes } } }] })).data;
    assert.deepEqual([quase(100).preco_antigo, quase(100).desconto], ['', '']);
    assert.deepEqual([quase(100.1).preco_antigo, quase(100.1).desconto], ['', '']);
    assert.deepEqual([quase(100.11).preco_antigo, quase(100.11).desconto], ['R$ 100,11', '-1%']);
  });

  test('formatarPreco: centavos só quando o valor não é inteiro', () => {
    const { ML } = carregar();
    assert.equal(ML.formatarPreco(2569), 'R$ 2.569');
    assert.equal(ML.formatarPreco(124.2), 'R$ 124,20');
    assert.equal(ML.formatarPreco(1019.9), 'R$ 1.019,90');
    assert.equal(ML.formatarPreco(1234567.05), 'R$ 1.234.567,05');
    assert.equal(ML.formatarPreco(99), 'R$ 99');
    assert.equal(ML.formatarPreco(0.5), 'R$ 0,50');
  });
});

// ------------------------------------------------------------------ piso de qualidade e usado (CA8)
describe('piso de qualidade e recusa de usado (CA8)', () => {
  /** Card sintético; `alt` é o texto da avaliação ('' = sem o componente), `extra` entra no polycard. */
  function cardPiso(n, { titulo = `Produto ${n}`, alt = ALT_NO_PISO, extra = {}, meta = {} } = {}) {
    const components = [{ type: 'title', title: { text: titulo } },
      { type: 'price', price: { current_price: { value: 100 + n } } }];
    if (alt) components.push({ type: 'review_compacted', review_compacted: { alt_text: alt } });
    return { id: 'POLYCARD', polycard: { metadata: { id: 'MLB' + (7000000000 + n), ...meta }, components, ...extra } };
  }
  function paginaPiso(cards) {
    const literal = JSON.stringify(JSON.stringify({ results: cards })).replace(/'/g, "\\'").replace(/</g, '\\x3C');
    return `<script>_n.ctx.s["x"].q(${literal});</script>`;
  }
  const alt = (nota, vendas) => `Classificação ${nota} de 5 estrelas.${vendas === undefined ? '' : ' ' + vendas + '.'}`;
  /** Itens que passam e a contagem, para uma lista de cards. */
  function extrair(cards) {
    const { ML } = carregar();
    const contagem = { lidos: 0, foraDoPiso: 0, usados: 0 };
    const itens = js(ML.extrairItens(paginaPiso(cards), 'Smart TV', ABA_TV, 30, contagem));
    return { itens, contagem: js(contagem) };
  }

  const entram = [
    ['limite: nota 4,5 e "Mais de 50"', alt('4.5', 'Mais de 50 produtos vendidos')],
    ['nota 5 e muitas vendas', alt('5', 'Mais de 100 produtos vendidos')],
    ['milhar com ponto', alt('4.7', 'Mais de 1.000 produtos vendidos')],
    ['"Mais de 1 mil"', alt('4.5', 'Mais de 1 mil produtos vendidos')],
    ['"Mais de 2 milhões"', alt('4.9', 'Mais de 2 milhões produtos vendidos')],
    ['rótulo curto "+50 vendidos"', alt('4.6', '+50 vendidos')],
    ['rótulo "+1 mil vendidos"', alt('4.6', '+1 mil vendidos')],
    ['nota com vírgula', alt('4,5', 'Mais de 50 produtos vendidos')],
  ];
  for (const [nome, a] of entram) {
    test(`passa: ${nome}`, () => {
      const { itens, contagem } = extrair([cardPiso(1, { alt: a })]);
      assert.equal(itens.length, 1, a);
      assert.deepEqual(contagem, { lidos: 1, foraDoPiso: 0, usados: 0 });
    });
  }

  const ficamFora = [
    ['nota 4,4 com muitas vendas', alt('4.4', 'Mais de 1000 produtos vendidos')],
    ['nota 4,49', alt('4.49', 'Mais de 1000 produtos vendidos')],
    ['"Mais de 49" vendidos', alt('4.8', 'Mais de 49 produtos vendidos')],
    ['"Mais de 25" vendidos (como o TV Box antigo da fixture)', alt('4.2', 'Mais de 25 produtos vendidos')],
    ['nota boa e sem rótulo de vendas', alt('4.9')],
    ['sem avaliação nenhuma', ''],
    ['só vendas, sem nota', 'Mais de 1000 produtos vendidos.'],
    ['nota fora da escala (45 de 5)', alt('45', 'Mais de 1000 produtos vendidos')],
    ['nota zero', alt('0', 'Mais de 1000 produtos vendidos')],
    ['rótulo de vendas ilegível', alt('4.9', 'Mais de muitos produtos vendidos')],
  ];
  for (const [nome, a] of ficamFora) {
    test(`fica fora: ${nome}`, () => {
      const { itens, contagem } = extrair([cardPiso(1, { alt: a })]);
      assert.equal(itens.length, 0, a);
      assert.deepEqual(contagem, { lidos: 1, foraDoPiso: 1, usados: 0 });
    });
  }

  const usados = ['iPhone 11 128GB Usado', 'Notebook Dell Recondicionado', 'Celular Seminovo Samsung', 'Aspirador Renovado',
    'TV 50 pol Vitrine', 'Smartphone Open Box', 'Galaxy S21 Refurbished', 'Bicicleta USADA aro 29', 'Lote de 3 Usados',
    'Câmera Recondicionádo', 'Console Open-Box'.replace('-', ' '), 'Tablet Seminovos'];
  for (const titulo of usados) {
    test(`usado por título: ${titulo}`, () => {
      const { itens, contagem } = extrair([cardPiso(1, { titulo })]);
      assert.equal(itens.length, 0);
      assert.deepEqual(contagem, { lidos: 1, foraDoPiso: 1, usados: 1 });
    });
  }

  for (const titulo of ['Smart TV Samsung 50 Novo', 'Desusado kit', 'Usadão de plástico', 'Renovação de ar', 'Vitrines Sheila', 'Caixa de som']) {
    test(`não é usado: ${titulo}`, () => {
      const { itens } = extrair([cardPiso(1, { titulo })]);
      assert.equal(itens.length, 1);
    });
  }

  test('condição usada ou recondicionada no polycard recusa o item, mesmo com título limpo', () => {
    const cards = [
      cardPiso(1, { meta: { condition: 'used' } }), cardPiso(2, { extra: { condition: 'Recondicionado' } }),
      cardPiso(3, { meta: { condition: 'new' } }), cardPiso(4, { meta: { condition: 'refurbished' } }), cardPiso(5),
    ];
    const { itens, contagem } = extrair(cards);
    assert.deepEqual(itens.map((i) => i.item_id), ['MLB7000000003', 'MLB7000000005']);
    assert.deepEqual(contagem, { lidos: 5, foraDoPiso: 3, usados: 3 });
  });

  test('o máximo por busca vale para os itens que passam: o que ficou fora não ocupa vaga', () => {
    const ruins = Array.from({ length: 10 }, (_, i) => cardPiso(i + 1, { alt: alt('3.9', 'Mais de 1000 produtos vendidos') }));
    const bons = Array.from({ length: 5 }, (_, i) => cardPiso(i + 11));
    const { ML } = carregar();
    const itens = js(ML.extrairItens(paginaPiso([...ruins, ...bons]), 'Smart TV', ABA_TV, 3));
    assert.deepEqual(itens.map((i) => i.item_id), ['MLB7000000011', 'MLB7000000012', 'MLB7000000013']);
  });

  test('a fixture mista dá os 3 que passam; card repetido não é contado duas vezes', () => {
    const { ML } = carregar();
    const contagem = { lidos: 0, foraDoPiso: 0, usados: 0 };
    const itens = js(ML.extrairItens(FIXTURE, 'Smart TV', ABA_TV, 30, contagem));
    assert.equal(itens.length, 3);
    assert.deepEqual(js(contagem), { lidos: 3, foraDoPiso: 0, usados: 0 });
  });

  test('coletar(): grava só o que passa, soma o que ficou de fora em estado e mostra no resumo', async () => {
    const cards = [cardPiso(1), cardPiso(2, { alt: alt('4.4', 'Mais de 1000 produtos vendidos') }), cardPiso(3, { alt: '' }),
      cardPiso(4, { titulo: 'Fone Usado' }), cardPiso(5, { alt: alt('4.5', 'Mais de 50 produtos vendidos') })];
    const ff = fetchFalso({ pagina: () => paginaPiso(cards) });
    const { ML, mensagens } = carregar({ fetch: ff.f });
    const estado = await ML.coletar({ termos: ['Smart TV'] });
    assert.equal(estado.erro, null);
    assert.deepEqual(JSON.parse(ff.doServidor()[0].init.body).items.map((i) => i.item_id), ['MLB7000000001', 'MLB7000000005']);
    assert.equal(estado.foraDoPiso, 3);
    assert.equal(estado.usados, 1);
    assert.deepEqual(js(estado.semPiso), []);
    assert.deepEqual(js(estado.feitos), ['Smart TV']);
    assert.equal(estado.itens.length, 2);
    const linhas = mensagens.map((m) => m.texto);
    assert.ok(linhas.some((l) => l.includes('2 itens') && l.includes('3 fora do piso (1 usados)')), linhas.join('\n'));
    assert.ok(linhas.some((l) => l.includes('fim:') && l.includes('3 itens fora do piso (1 usados)')), linhas.join('\n'));
  });

  test('com enviar:false o piso vale do mesmo jeito e a contagem aparece', async () => {
    const ff = fetchFalso({ pagina: () => paginaPiso([cardPiso(1), cardPiso(2, { alt: '' })]) });
    const { ML } = carregar({ fetch: ff.f });
    const estado = await ML.coletar({ termos: ['Smart TV'], enviar: false });
    assert.equal(estado.itens.length, 1);
    assert.equal(estado.foraDoPiso, 1);
    assert.equal(ff.doServidor().length, 0);
  });

  test('termo com todos os itens fora do piso não é erro: não envia, não marca como feito e a coleta segue', async () => {
    const ruim = [cardPiso(1, { alt: alt('4.0', 'Mais de 1000 produtos vendidos') }), cardPiso(2, { titulo: 'Tablet Usado' })];
    const ff = fetchFalso({ pagina: (url) => (url === '/smart-tv' ? paginaPiso(ruim) : paginaPiso([cardPiso(30)])) });
    const { ML, localStorage } = carregar({ fetch: ff.f });
    const estado = await ML.coletar({ termos: ['Smart TV', 'Body splash'], pausa: [0, 0] });
    assert.equal(estado.erro, null);
    assert.deepEqual(js(estado.semPiso), ['Smart TV']);
    assert.deepEqual(js(estado.feitos), ['Body splash']);
    assert.equal(estado.foraDoPiso, 2);
    assert.equal(ff.doServidor().length, 1, 'só o termo com itens no piso é enviado');
    assert.deepEqual(localStorage.lista('__coletaML:http://localhost:8765'), ['Body splash']);
    // rodando de novo, o termo que ficou fora do piso é buscado outra vez
    const antes = ff.doML().length;
    await ML.coletar({ termos: ['Smart TV', 'Body splash'], pausa: [0, 0] });
    assert.equal(ff.doML().length, antes + 1);
  });

  test('página sem nenhum polycard continua sendo erro (captcha ou mudança da página), diferente de "todos fora do piso"', async () => {
    const ff = fetchFalso({ pagina: () => '<html><body>nada aqui</body></html>' });
    const { ML } = carregar({ fetch: ff.f });
    const estado = await ML.coletar({ termos: ['Smart TV'] });
    assert.match(estado.erro, /sem polycard/);
    assert.equal(ff.doServidor().length, 0);
  });
});

// ------------------------------------------------------------------ coletar(): guarda e opções
describe('coletar(): guarda de origem e opções (CA11)', () => {
  for (const origem of ['https://www.mercadolivre.com.br', 'https://example.com', 'http://localhost:8765', null]) {
    test(`em ${origem || 'página sem location'} mostra a mensagem e não faz fetch`, async () => {
      const ff = fetchFalso();
      const { ML, mensagens, localStorage } = carregar({ origem, fetch: ff.f });
      const estado = await ML.coletar({ termos: ['Smart TV'], fetch: ff.f });
      assert.match(estado.erro, /só roda numa aba de https:\/\/lista\.mercadolivre\.com\.br/);
      assert.equal(ff.chamadas.length, 0);
      assert.equal(localStorage.escritas, 0);
      assert.ok(mensagens.some((m) => m.tipo === 'error' && m.texto.includes('lista.mercadolivre.com.br')));
      assert.equal(estado.rodando, false);
    });
  }

  const invalidas = [
    ['servidor de fora', { servidor: 'https://evil.example' }, /servidor deve ser/],
    ['servidor sem porta', { servidor: 'http://localhost' }, /servidor deve ser/],
    ['servidor https', { servidor: 'https://localhost:8765' }, /servidor deve ser/],
    ['termo fora de buscas.json', { termos: ['Black Friday'] }, /termos fora de buscas\.json/],
    ['termos vazio', { termos: [] }, /termos deve ser/],
    ['termos texto', { termos: 'Smart TV' }, /termos deve ser/],
    ['porBusca acima de 30', { porBusca: 31 }, /porBusca/],
    ['enviar como texto', { enviar: 'false' }, /enviar deve ser/],
    ['pausa invertida', { pausa: [5, 1] }, /pausa/],
  ];
  for (const [nome, opcoes, erro] of invalidas) {
    test(`recusa ${nome} sem fazer fetch`, async () => {
      const ff = fetchFalso();
      const { ML, localStorage } = carregar({ fetch: ff.f });
      const estado = await ML.coletar({ termos: ['Smart TV'], ...opcoes, fetch: ff.f });
      assert.match(estado.erro, erro);
      assert.match(estado.erro, /Nada foi feito/);
      assert.equal(ff.chamadas.length, 0);
      assert.equal(localStorage.escritas, 0);
    });
  }
});

// ------------------------------------------------------------------ coletar(): envio e progresso
describe('coletar(): envio, progresso e parar (CA13, CA14, CA17)', () => {
  test('contrato do envio: POST JSON com loja ml, cat da chave, busca do termo e textos', async () => {
    const ff = fetchFalso();
    const { ML } = carregar({ fetch: ff.f });
    const estado = await ML.coletar({ termos: ['Smart TV', 'Body splash'], pausa: [0, 0] });
    assert.equal(estado.erro, null);
    assert.deepEqual(js(estado.feitos), ['Smart TV', 'Body splash']);
    assert.equal(estado.inserido, 6);

    assert.deepEqual(ff.doML().map((c) => c.url), ['/smart-tv', '/body-splash']);
    for (const c of ff.doML()) {
      assert.equal(c.init.credentials, 'include');
      assert.equal(c.init.method, undefined);
    }
    const posts = ff.doServidor();
    assert.equal(posts.length, 2);
    const esperado = [['Smart TV', ABA_TV], ['Body splash', 'Perfumes e Perfumaria']];
    posts.forEach((c, i) => {
      assert.equal(c.url, `${SERVIDOR}/api/items`);
      assert.equal(c.init.method, 'POST');
      assert.equal(c.init.credentials, 'omit');
      assert.equal(c.init.referrerPolicy, 'no-referrer');
      assert.deepEqual(js(c.init.headers), { 'Content-Type': 'application/json' });
      assert.equal(typeof c.init.body, 'string');
      const corpo = JSON.parse(c.init.body);
      assert.deepEqual(Object.keys(corpo), ['items']);
      assert.equal(corpo.items.length, 3);
      for (const it of corpo.items) {
        assert.deepEqual(Object.keys(it), ['loja', 'item_id', 'cat', 'busca', 'url', 'data']);
        assert.equal(it.loja, 'ml');
        assert.equal(it.busca, esperado[i][0]);
        assert.equal(it.cat, esperado[i][1]);
        for (const k of ['item_id', 'cat', 'busca', 'url']) assert.equal(typeof it[k], 'string');
        assert.equal(typeof it.data, 'object');
        assert.ok(!Array.isArray(it.data));
        assert.deepEqual(Object.keys(it.data), CAMPOS);
        assert.ok(Object.values(it.data).every((v) => typeof v === 'string'));
      }
    });
    assert.ok(ff.chamadas.every((c) => [undefined, 'GET', 'POST'].includes(c.init.method)));
  });

  test('com enviar:false não chama o servidor nem mexe no progresso e devolve os itens', async () => {
    const ff = fetchFalso();
    const { ML, localStorage, mensagens } = carregar({ fetch: ff.f });
    const estado = await ML.coletar({ termos: ['Smart TV'], enviar: false });
    assert.equal(estado.erro, null);
    assert.equal(ff.doServidor().length, 0);
    assert.equal(ff.doML().length, 1);
    assert.equal(localStorage.escritas, 0);
    assert.deepEqual(js(estado.itens), [ITEM_TV, ITEM_BOX, ITEM_SUPORTE]);
    assert.equal(ML.estado, estado);
    assert.ok(mensagens.some((m) => m.texto.includes('Nada foi enviado')));
  });

  test('progresso por termo e por servidor no localStorage; zerar apaga', async () => {
    const ff = fetchFalso();
    const { ML, localStorage } = carregar({ fetch: ff.f });
    await ML.coletar({ termos: ['Smart TV'] });
    assert.deepEqual(localStorage.lista('__coletaML:http://localhost:8765'), ['Smart TV']);

    const n = ff.chamadas.length;
    const segunda = await ML.coletar({ termos: ['Smart TV'], servidor: 'http://localhost:8765/' });
    assert.equal(ff.chamadas.length, n, 'termo já feito não pode ser buscado de novo');
    assert.deepEqual(js(segunda.pulados), ['Smart TV']);

    await ML.coletar({ termos: ['Smart TV', 'Body splash'], servidor: 'http://127.0.0.1:8766', pausa: [0, 0] });
    assert.deepEqual(localStorage.lista('__coletaML:http://127.0.0.1:8766'), ['Smart TV', 'Body splash']);
    assert.deepEqual(localStorage.lista('__coletaML:http://localhost:8765'), ['Smart TV']);

    const terceira = await ML.coletar({ termos: ['Smart TV', 'Body splash'], pausa: [0, 0] });
    assert.deepEqual(js(terceira.pulados), ['Smart TV']);
    assert.deepEqual(js(terceira.feitos), ['Body splash']);
    assert.deepEqual(localStorage.lista('__coletaML:http://localhost:8765'), ['Smart TV', 'Body splash']);

    assert.equal(ML.zerar('http://localhost:8765', localStorage), true);
    assert.equal(localStorage.lista('__coletaML:http://localhost:8765'), null);
    assert.deepEqual(localStorage.lista('__coletaML:http://127.0.0.1:8766'), ['Smart TV', 'Body splash']);
    assert.equal(ML.zerar('https://evil.example', localStorage), false);
  });

  test('o progresso vem do armazenamento passado nas opções e tolera lixo', async () => {
    const ff = fetchFalso();
    const { ML, localStorage } = carregar({ fetch: ff.f });
    const proprio = memoria({ '__coletaML:http://localhost:8765': '{lixo' });
    const estado = await ML.coletar({ termos: ['Smart TV'], armazenamento: proprio });
    assert.equal(estado.erro, null);
    assert.deepEqual(proprio.lista('__coletaML:http://localhost:8765'), ['Smart TV']);
    assert.equal(localStorage.escritas, 0);
  });

  test('parar() durante a busca termina o termo atual e não começa o próximo', async () => {
    let ML;
    const ff = fetchFalso({ aoBuscar: () => ML.parar() });
    ({ ML } = carregar({ fetch: ff.f }));
    const t0 = Date.now();
    const estado = await ML.coletar({ termos: ['Smart TV', 'Body splash', 'Geladeira'], pausa: [10000, 10000] });
    assert.ok(Date.now() - t0 < 2000, 'esperou a pausa mesmo com parar() pedido');
    assert.equal(estado.parado, true);
    assert.equal(estado.erro, null);
    assert.deepEqual(js(estado.feitos), ['Smart TV']);
    assert.equal(ff.doML().length, 1);
    assert.equal(ff.doServidor().length, 1);
  });

  test('parar() corta a pausa entre termos', async () => {
    let ML;
    const ff = fetchFalso({ servidor: async () => { setTimeout(() => ML.parar(), 20);
      return { status: 200, corpo: { inserido: 3, atualizado: 0, total: 3 } }; } });
    ({ ML } = carregar({ fetch: ff.f }));
    const t0 = Date.now();
    const estado = await ML.coletar({ termos: ['Smart TV', 'Body splash'], pausa: [10000, 10000] });
    assert.ok(Date.now() - t0 < 2000, 'a pausa não foi cortada');
    assert.equal(estado.parado, true);
    assert.equal(ff.doML().length, 1);
    assert.equal(ML.estado.rodando, false);
  });

  test('uma segunda coleta enquanto a primeira roda é recusada', async () => {
    let soltar;
    const trava = new Promise((r) => { soltar = r; });
    const ff = fetchFalso({ aoBuscar: () => trava });
    const { ctx, ML, mensagens } = carregar({ fetch: ff.f });
    const primeira = ML.coletar({ termos: ['Smart TV'] });
    const segunda = await ML.coletar({ termos: ['Body splash'] });
    assert.ok(mensagens.some((m) => m.tipo === 'error' && m.texto.includes('já há uma coleta rodando')));
    assert.equal(segunda.rodando, true);
    vm.runInContext(FONTE, ctx);   // colar de novo no meio da coleta não troca o ColetaML
    assert.equal(ctx.ColetaML, ML);
    assert.ok(mensagens.some((m) => m.tipo === 'error' && m.texto.includes('cole de novo')));
    soltar();
    const estado = await primeira;
    assert.equal(estado.erro, null);
    assert.deepEqual(ff.doML().map((c) => c.url), ['/smart-tv']);
  });

  test('captcha para a coleta sem enviar nada', async () => {
    const ff = fetchFalso({ urlFinal: 'https://www.mercadolivre.com.br/gz/account-verification?go=x' });
    const { ML, localStorage } = carregar({ fetch: ff.f });
    const estado = await ML.coletar({ termos: ['Smart TV', 'Body splash'], pausa: [0, 0] });
    assert.match(estado.erro, /captcha/);
    assert.equal(ff.doServidor().length, 0);
    assert.equal(ff.doML().length, 1);
    assert.equal(localStorage.escritas, 0);
  });

  test('página sem polycard para a coleta sem enviar nada', async () => {
    const ff = fetchFalso({ pagina: () => '<html><body>Não há anúncios</body></html>' });
    const { ML, localStorage } = carregar({ fetch: ff.f });
    const estado = await ML.coletar({ termos: ['Smart TV', 'Body splash'], pausa: [0, 0] });
    assert.match(estado.erro, /sem polycard/);
    assert.equal(ff.doServidor().length, 0);
    assert.equal(ff.doML().length, 1);
    assert.equal(localStorage.escritas, 0);
  });

  test('ML com erro HTTP ou fora do ar para a coleta', async () => {
    const ff = fetchFalso({ statusML: 503 });
    let r = await carregar({ fetch: ff.f }).ML.coletar({ termos: ['Smart TV'] });
    assert.match(r.erro, /o ML respondeu 503/);
    assert.equal(ff.doServidor().length, 0);

    const caiu = async () => { throw new TypeError('Failed to fetch'); };
    r = await carregar({ fetch: caiu }).ML.coletar({ termos: ['Smart TV'] });
    assert.match(r.erro, /não consegui abrir a busca "Smart TV" no ML \(Failed to fetch\)/);
  });

  test('servidor que recusa ou está fora do ar para a coleta e não marca o termo', async () => {
    const ff = fetchFalso({ servidor: async () => ({ status: 403, corpo: { error: 'origem não permitida' } }) });
    const { ML, localStorage } = carregar({ fetch: ff.f });
    let estado = await ML.coletar({ termos: ['Smart TV', 'Body splash'], pausa: [0, 0] });
    assert.match(estado.erro, /recusou "Smart TV" com 403: origem não permitida/);
    assert.equal(ff.doML().length, 1);
    assert.equal(localStorage.escritas, 0);

    const fora = fetchFalso({ servidor: async () => { throw new TypeError('Failed to fetch'); } });
    estado = await carregar({ fetch: fora.f }).ML.coletar({ termos: ['Smart TV'] });
    assert.match(estado.erro, /não consegui falar com o servidor em http:\/\/localhost:8765/);

    const estranho = fetchFalso({ servidor: async () => ({ status: 200, corpo: '<html>' }) });
    estado = await carregar({ fetch: estranho.f }).ML.coletar({ termos: ['Smart TV'] });
    assert.match(estado.erro, /resposta inesperada do servidor/);
  });
});

// ------------------------------------------------------------------ coletar(): ordem da listagem (CA6)
describe('coletar(): ordem da listagem (CA6)', () => {
  const CHAVE = '__coletaML:http://localhost:8765';

  for (const [nome, ordem] of [['desconhecida', 'vendidos'], ['mais vendidos', 'mais_vendidos'], ['maiúscula', 'Caros'],
    ['de protótipo', 'constructor'], ['__proto__', '__proto__'], ['número', 7], ['nula', null], ['vazia', ''],
    ['objeto', { caros: true }]]) {
    test(`ordem ${nome} é recusada antes de qualquer fetch ou escrita`, async () => {
      const ff = fetchFalso();
      const { ML, localStorage } = carregar({ fetch: ff.f });
      const estado = await ML.coletar({ termos: ['Smart TV'], ordem });
      assert.match(estado.erro, /ordem deve ser uma destas: relevancia, caros\. Nada foi feito\./);
      assert.equal(ff.chamadas.length, 0);
      assert.equal(localStorage.escritas, 0);
      assert.equal(estado.rodando, false);
    });
  }

  test('sem ordem (ou "relevancia") a URL é a de sempre e o progresso é o termo puro', async () => {
    for (const opcoes of [{}, { ordem: 'relevancia' }, { ordem: undefined }]) {
      const ff = fetchFalso();
      const { ML, localStorage } = carregar({ fetch: ff.f });
      const estado = await ML.coletar({ termos: ['Máquina de lavar'], ...opcoes });
      assert.equal(estado.erro, null);
      assert.equal(estado.ordem, 'relevancia');
      assert.deepEqual(ff.doML().map((c) => c.url), ['/maquina-de-lavar']);
      assert.deepEqual(localStorage.lista(CHAVE), ['Máquina de lavar']);
    }
  });

  test("ordem 'caros' busca a listagem com o sufixo de maior preço e grava a mesma cat e busca", async () => {
    const ff = fetchFalso();
    const { ML } = carregar({ fetch: ff.f });
    const estado = await ML.coletar({ termos: ['Body splash'], ordem: 'caros' });
    assert.equal(estado.erro, null);
    assert.equal(estado.ordem, 'caros');
    assert.deepEqual(ff.doML().map((c) => c.url), ['/body-splash_OrderId_PRICE*DESC']);
    assert.equal(ff.doML()[0].init.credentials, 'include');
    const corpo = JSON.parse(ff.doServidor()[0].init.body);
    assert.ok(corpo.items.length > 0);
    for (const i of corpo.items) {
      assert.equal(i.cat, 'Perfumes e Perfumaria');
      assert.equal(i.busca, 'Body splash');
      assert.equal(i.loja, 'ml');
    }
  });

  test('o progresso antigo (termo puro) vale para a relevância e não pula a ordem "caros"', async () => {
    const ff = fetchFalso();
    const antigo = memoria({ [CHAVE]: JSON.stringify(['Body splash', 'Smart TV']) });
    const { ML } = carregar({ fetch: ff.f, localStorage: antigo });

    const rel = await ML.coletar({ termos: ['Body splash', 'Smart TV'] });
    assert.deepEqual(js(rel.pulados), ['Body splash', 'Smart TV']);
    assert.deepEqual(js(rel.feitos), []);
    assert.equal(ff.chamadas.length, 0, 'o progresso antigo tem de valer sem recoletar');
    assert.equal(antigo.escritas, 0);

    const caros = await ML.coletar({ termos: ['Body splash', 'Smart TV'], ordem: 'caros', pausa: [0, 0] });
    assert.deepEqual(js(caros.pulados), []);
    assert.deepEqual(js(caros.feitos), ['Body splash', 'Smart TV']);
    assert.deepEqual(ff.doML().map((c) => c.url), ['/body-splash_OrderId_PRICE*DESC', '/smart-tv_OrderId_PRICE*DESC']);
    // os termos puros antigos continuam lá, e as chaves das outras ordens vêm depois
    assert.deepEqual(antigo.lista(CHAVE),
      ['Body splash', 'Smart TV', 'caros|Body splash', 'caros|Smart TV']);
  });

  test('o progresso de cada ordem é separado: caros feito não pula a relevância e vice-versa', async () => {
    const ff = fetchFalso();
    const { ML, localStorage } = carregar({ fetch: ff.f });
    await ML.coletar({ termos: ['Smart TV'], ordem: 'caros' });
    assert.deepEqual(localStorage.lista(CHAVE), ['caros|Smart TV']);

    const n = ff.chamadas.length;
    const denovo = await ML.coletar({ termos: ['Smart TV'], ordem: 'caros' });
    assert.equal(ff.chamadas.length, n, 'termo já feito em "caros" não pode ser buscado de novo');
    assert.deepEqual(js(denovo.pulados), ['Smart TV']);

    const rel = await ML.coletar({ termos: ['Smart TV'] });
    assert.deepEqual(js(rel.feitos), ['Smart TV']);
    assert.deepEqual(js(rel.pulados), []);
    assert.deepEqual(localStorage.lista(CHAVE), ['caros|Smart TV', 'Smart TV']);
    assert.deepEqual(ff.doML().map((c) => c.url).slice(-1), ['/smart-tv']);
  });

  test("com enviar:false e ordem 'caros' busca a listagem ordenada sem tocar no progresso", async () => {
    const ff = fetchFalso();
    const { ML, localStorage } = carregar({ fetch: ff.f });
    const estado = await ML.coletar({ termos: ['Smart TV'], ordem: 'caros', enviar: false });
    assert.equal(estado.erro, null);
    assert.ok(estado.itens.length > 0);
    assert.deepEqual(ff.doML().map((c) => c.url), ['/smart-tv_OrderId_PRICE*DESC']);
    assert.equal(ff.doServidor().length, 0);
    assert.equal(localStorage.escritas, 0);
  });

  test("estado, parar() e zerar() continuam funcionando com ordem 'caros'", async () => {
    let ML;
    const ff = fetchFalso({ aoBuscar: () => ML.parar() });
    let localStorage;
    ({ ML, localStorage } = carregar({ fetch: ff.f }));
    const estado = await ML.coletar({ termos: ['Smart TV', 'Body splash'], ordem: 'caros', pausa: [10000, 10000] });
    assert.equal(estado.parado, true);
    assert.equal(estado.erro, null);
    assert.equal(estado.rodando, false);
    assert.equal(estado.termoAtual, null);
    assert.deepEqual(js(estado.feitos), ['Smart TV']);
    assert.equal(ff.doML().length, 1);
    assert.equal(ML.estado, estado);
    assert.deepEqual(localStorage.lista(CHAVE), ['caros|Smart TV']);

    assert.equal(ML.zerar('http://localhost:8765', localStorage), true);
    assert.equal(localStorage.lista(CHAVE), null);
  });

  test("falha na busca ordenada não marca o termo e a mensagem cita o termo", async () => {
    const ff = fetchFalso({ statusML: 500 });
    const { ML, localStorage } = carregar({ fetch: ff.f });
    const estado = await ML.coletar({ termos: ['Smart TV'], ordem: 'caros' });
    assert.match(estado.erro, /o ML respondeu 500 na busca "Smart TV"/);
    assert.equal(localStorage.escritas, 0);
  });
});

// ------------------------------------------------------------------ integração com o servidor.py
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

/**
 * fetch do servidor por node:http, como o Chrome faria a partir da aba do ML:
 * Origin do ML (lista por padrão) e Sec-Fetch-Site cross-site. Só fala com a porta de teste;
 * node:http não usa as variáveis de proxy, então funciona com os proxies mortos no ambiente.
 */
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

/** Sobe um servidor.py para a suíte atual (before/after), com banco temporário e porta livre. */
function usarServidor() {
  const s = {};
  before(async () => {
    s.dir = fs.mkdtempSync(path.join(os.tmpdir(), 'achadinhos-ml-'));
    const db = path.join(s.dir, 'teste.db');
    if (path.resolve(db) === path.resolve(RAIZ, 'achadinhos.db')) throw new Error('o teste tentou usar o banco real');
    s.porta = await portaLivre();
    s.servidor = `http://localhost:${s.porta}`;
    const morto = 'http://127.0.0.1:9';
    s.proc = spawn('python3', ['-u', 'servidor.py'], {
      cwd: RAIZ, stdio: ['ignore', 'ignore', 'pipe'],
      env: { ...process.env, ACHADINHOS_DB: db, ACHADINHOS_PORTA: String(s.porta), PYTHONDONTWRITEBYTECODE: '1',
        ACHADINHOS_API_TOKEN_ARQUIVO: path.join(s.dir, 'sem-api-token.txt'),   // v1 desligada mesmo com o token real
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

describe('integração com o servidor.py (CA13, CA15)', () => {
  const srv = usarServidor();
  let porta; let servidor; let doServidor;
  before(() => {
    ({ porta, servidor } = srv);
    doServidor = fetchNode(porta);
  });

  const fetchMisto = (chamadas) => async (url, init = {}) => {
    chamadas.push({ url: String(url), init });
    if (String(url).startsWith('/')) return resposta(200, paginaPorSlug(String(url)), LISTA + url);
    return doServidor(url, init);
  };

  async function itens() {
    const r = await doServidor(`${servidor}/api/items`);
    assert.equal(r.status, 200);
    assert.equal(r.headers['access-control-allow-origin'], LISTA);
    return (await r.json()).filter((i) => i.loja === 'ml');
  }

  test('o POST da coleta grava cada termo com a cat da sua chave, inclusive "TV, Alexa e Casa Conectada"', async () => {
    const chamadas = [];
    const { ML } = carregar({ fetch: fetchMisto(chamadas) });
    const estado = await ML.coletar({ servidor, termos: ['Smart TV', 'Body splash'], pausa: [0, 0] });
    assert.equal(estado.erro, null);
    assert.equal(estado.inserido, 6);
    assert.equal(estado.atualizado, 0);

    const gravados = await itens();
    assert.equal(gravados.length, 6);
    const tv = gravados.filter((i) => i.item_id.startsWith('MLB41'));
    const perfume = gravados.filter((i) => i.item_id.startsWith('MLB42'));
    assert.equal(tv.length, 3);
    assert.ok(tv.every((i) => i.cat === ABA_TV && i.busca === 'Smart TV'));
    assert.ok(perfume.every((i) => i.cat === 'Perfumes e Perfumaria' && i.busca === 'Body splash'));
    const box = gravados.find((i) => i.item_id === 'MLB4100000002');
    assert.deepEqual(box.data, ITEM_BOX.data);
    assert.equal(box.url, ITEM_BOX.url);
  });

  test('reenviar não duplica, não troca a cat nem um meli.la já gravado', async () => {
    const antes = await itens();
    const tv = antes.find((i) => i.item_id === 'MLB4100000001');
    const box = antes.find((i) => i.item_id === 'MLB4100000002');
    const json = { 'Content-Type': 'application/json' };
    let r = await doServidor(`${servidor}/api/items/${tv.id}`,
      { method: 'PATCH', headers: json, body: JSON.stringify({ url: 'https://meli.la/1AbC234' }) });
    assert.equal(r.status, 200);
    r = await doServidor(`${servidor}/api/items/${box.id}`,
      { method: 'PATCH', headers: json, body: JSON.stringify({ cat: 'Games' }) });
    assert.equal(r.status, 200);

    const { ML } = carregar({ fetch: fetchMisto([]) });   // localStorage novo: coleta tudo de novo
    const estado = await ML.coletar({ servidor, termos: ['Smart TV', 'Body splash'], pausa: [0, 0] });
    assert.equal(estado.erro, null);
    assert.equal(estado.inserido, 0);
    assert.equal(estado.atualizado, 6);

    const depois = await itens();
    assert.equal(depois.length, 6);
    assert.equal(new Set(depois.map((i) => i.item_id)).size, 6);
    const tv2 = depois.find((i) => i.item_id === 'MLB4100000001');
    const box2 = depois.find((i) => i.item_id === 'MLB4100000002');
    assert.equal(tv2.url, 'https://meli.la/1AbC234');
    assert.equal(tv2.cat, ABA_TV);
    assert.equal(box2.cat, 'Games');
    assert.equal(box2.url, ITEM_BOX.url);
  });

  test('o servidor recusa a mesma coleta vinda de outra origem (a guarda do servidor continua valendo)', async () => {
    const corpo = Buffer.from(JSON.stringify({ items: [ITEM_TV] }));
    const status = await new Promise((resolve, reject) => {
      const req = http.request({ host: '127.0.0.1', port: porta, path: '/api/items', method: 'POST', agent: false,
        headers: { Host: `localhost:${porta}`, Origin: 'https://evil.example', 'Content-Type': 'application/json',
          'Content-Length': corpo.length } }, (res) => { res.resume(); res.on('end', () => resolve(res.statusCode)); });
      req.on('error', reject);
      req.end(corpo);
    });
    assert.equal(status, 403);
  });
});


// ================================================================== afiliar() (etapa 5)
const PRODUTO = (n) => `https://produto.mercadolivre.com.br/MLB-${n}`;
const mlbDe = (url) => { const m = /MLB-?(\d{6,})/.exec(String(url)); return m ? 'MLB' + m[1] : null; };
const RX_MELI = /^https:\/\/meli\.la\/[A-Za-z0-9]+$/;
// a fixture inteira tem um link que não é meli.la ("Links curtos" desligado): afiliar() para.
// SEM_LONGO é a mesma resposta sem ele, para os fluxos que seguem até o fim.
const SEM_LONGO = { urls: CREATELINK.urls.filter((e) => e.error_code || RX_MELI.test(e.short_url)) };
// mesmos itens que a coleta da fixture grava: 3 da TV (MLB41…) e 3 de perfume (MLB42…)
const IDS = { tv1: 1, tv2: 2, tv3: 3, p1: 4, p2: 5, p3: 6 };
const ITENS_ML = [
  [IDS.tv1, 4100000001], [IDS.tv2, 4100000002], [IDS.tv3, 4100000003],
  [IDS.p1, 4200000001], [IDS.p2, 4200000002], [IDS.p3, 4200000003],
].map(([id, n]) => ({ id, loja: 'ml', url: PRODUTO(n) }));
const LINKBUILDER = '/afiliados/linkbuilder';
// "Links curtos" desligado: nenhum item do lote vem meli.la
const TODO_LONGO = { urls: ITENS_ML.map((i) => ({ origin_url: i.url, short_url: `https://mercadolivre.com/sec/L${i.id}` })) };

/**
 * Servidor em memória com as três rotas do afiliar(). `trocarErrado`: o próximo PATCH daquele id grava
 * outro meli.la (como um link de outra origem), que o ml-sem-afiliado não enxerga.
 */
function servidorFalso(itens = ITENS_ML) {
  const db = new Map(itens.map((i) => [i.id, { ...i }]));
  const chamadas = [];
  const trocarErrado = new Set();
  const f = async (url, init = {}) => {
    const u = new URL(url);
    const metodo = init.method || 'GET';
    chamadas.push({ url: String(url), metodo, init });
    if (metodo === 'GET' && u.pathname === '/api/ml-sem-afiliado') {
      return resposta(200, [...db.values()].filter((i) => i.loja === 'ml' && !i.url.startsWith('https://meli.la/'))
        .map(({ id, url: x }) => ({ id, url: x })), String(url));
    }
    if (metodo === 'GET' && u.pathname === '/api/items') return resposta(200, [...db.values()], String(url));
    const m = /^\/api\/items\/(\d+)$/.exec(u.pathname);
    if (metodo === 'PATCH' && m) {
      const it = db.get(Number(m[1]));
      if (!it) return resposta(200, null, String(url));
      if (trocarErrado.has(it.id)) { trocarErrado.delete(it.id); it.url = 'https://meli.la/Errado1'; } else it.url = JSON.parse(init.body).url;
      return resposta(200, it, String(url));
    }
    return resposta(404, { error: 'rota não encontrada' }, String(url));
  };
  return { f, db, chamadas, trocarErrado, patches: () => chamadas.filter((c) => c.metodo === 'PATCH') };
}

/** Linkbuilder falso: devolve as entradas de `resp` cujos MLB foram pedidos, na ordem de `resp` (embaralhada). */
function gerarFalso(resp = SEM_LONGO, aoGerar) {
  const pedidos = [];
  const g = async (urls) => {
    pedidos.push([...urls]);
    if (aoGerar) await aoGerar(urls);
    const pedidosMLB = new Set(urls.map(mlbDe));
    return { urls: resp.urls.filter((e) => pedidosMLB.has(mlbDe(e.origin_url))) };
  };
  return { g, pedidos };
}

/** Linkbuilder falso que devolve `respostas[n]` na n-ésima chamada (a última se repete). */
function gerarEmSequencia(respostas) {
  const pedidos = [];
  const g = async (urls) => {
    pedidos.push([...urls]);
    const r = respostas[Math.min(pedidos.length, respostas.length) - 1];
    return typeof r === 'function' ? r(urls) : r;
  };
  return { g, pedidos };
}

function conferirPatches(patches) {
  for (const c of patches) {
    assert.equal(c.init.method, 'PATCH');
    assert.equal(c.init.credentials, 'omit');
    assert.equal(c.init.referrerPolicy, 'no-referrer');
    assert.deepEqual(js(c.init.headers), { 'Content-Type': 'application/json' });
    const corpo = JSON.parse(c.init.body);
    assert.deepEqual(Object.keys(corpo), ['url']);
    assert.match(corpo.url, RX_MELI);
  }
}

describe('afiliar(): funções puras (CA14, CA16)', () => {
  test('ehLinkMeliLa só aceita https://meli.la/<código>', () => {
    const { ML } = carregar();
    for (const ok of ['https://meli.la/2PfM3kQ', 'https://meli.la/1']) assert.equal(ML.ehLinkMeliLa(ok), true, ok);
    for (const ruim of ['http://meli.la/abc', 'https://meli.la/', 'https://meli.la/abc/def', 'https://meli.la/abc?x=1',
      'https://meli.la.evil.com/abc', 'https://evil.com/meli.la/abc', ' https://meli.la/abc', 'https://meli.la/abc\n',
      'https://meli.la/ab-c', 'https://mercadolivre.com/sec/1xYz9Qw', PRODUTO(4100000001), null, 42]) {
      assert.equal(ML.ehLinkMeliLa(ruim), false, String(ruim));
    }
  });

  test('idMLB lê o código da url comum e da canônica -_JM', () => {
    const { ML } = carregar();
    assert.equal(ML.idMLB(PRODUTO(4100000001)), 'MLB4100000001');
    assert.equal(ML.idMLB(CREATELINK.urls[2].origin_url), 'MLB4100000001');
    assert.equal(ML.idMLB('MLB4100000001'), 'MLB4100000001');
    assert.equal(ML.idMLB('https://produto.mercadolivre.com.br/MLB-123'), null);
    assert.equal(ML.idMLB('https://meli.la/1AbC234'), null);
    assert.equal(ML.idMLB(undefined), null);
  });

  test('mapearLinks casa pelo MLB, não pela ordem, e marca o link que não é meli.la', () => {
    const { ML } = carregar();
    const m = js(ML.mapearLinks(CREATELINK, ITENS_ML));
    assert.deepEqual(m.trocar, [
      { id: IDS.tv1, mlb: 'MLB4100000001', url: 'https://meli.la/1AbC234', origem: PRODUTO(4100000001) },
      { id: IDS.p1, mlb: 'MLB4200000001', url: 'https://meli.la/2PfM3kQ', origem: PRODUTO(4200000001) },
    ]);
    assert.deepEqual(m.inelegiveis, [
      { id: IDS.tv2, mlb: 'MLB4100000002', motivo: 'ITEM_NOT_ELIGIBLE: O produto não participa do programa de afiliados',
        codigo: 'ITEM_NOT_ELIGIBLE' },
      { id: IDS.tv3, mlb: 'MLB4100000003', motivo: "link não é meli.la: confira 'Links curtos'", naoMeliLa: true },
      { id: IDS.p2, mlb: 'MLB4200000002', motivo: 'INTERNAL_SERVER_ERROR: Tente de novo mais tarde', codigo: 'INTERNAL_SERVER_ERROR' },
    ]);
    assert.deepEqual(m.semResposta.map((s) => s.id), [IDS.p3]);
    // pela ordem, o primeiro item levaria o link da primeira resposta, que nem é meli.la
    assert.notEqual(mlbDe(CREATELINK.urls[0].origin_url), mlbDe(ITENS_ML[0].url));
  });

  test('mapearLinks: resposta inválida ou com dois links para o mesmo MLB fica sem resposta', () => {
    const { ML } = carregar();
    for (const resp of [null, {}, { urls: 'x' }, { urls: [null, 1, { origin_url: 5 }] }]) {
      const m = js(ML.mapearLinks(resp, ITENS_ML.slice(0, 2)));
      assert.deepEqual([m.trocar.length, m.inelegiveis.length, m.semResposta.length], [0, 0, 2]);
    }
    const dois = { urls: [{ origin_url: PRODUTO(4100000001), short_url: 'https://meli.la/A1' },
      { origin_url: PRODUTO(4100000001) + '-_JM', short_url: 'https://meli.la/B2' }] };
    assert.deepEqual(js(ML.mapearLinks(dois, ITENS_ML.slice(0, 1))).semResposta.map((s) => s.id), [IDS.tv1]);
    const igual = { urls: [{ origin_url: PRODUTO(4100000001), short_url: 'https://meli.la/A1' },
      { origin_url: PRODUTO(4100000001) + '-_JM', short_url: 'https://meli.la/A1' }] };
    assert.equal(js(ML.mapearLinks(igual, ITENS_ML.slice(0, 1))).trocar[0].url, 'https://meli.la/A1');
  });

  test('urlsRepetidas aponta url igual entre itens do ML', () => {
    const { ML } = carregar();
    const r = js(ML.urlsRepetidas([{ id: 1, loja: 'ml', url: 'https://meli.la/X' }, { id: 2, loja: 'ml', url: 'https://meli.la/X' },
      { id: 3, loja: 'ml', url: 'https://meli.la/Y' }, { id: 4, loja: 'amazon', url: 'https://meli.la/X' }, null]));
    assert.deepEqual(r, [{ url: 'https://meli.la/X', ids: [1, 2] }]);
    assert.deepEqual(js(ML.urlsRepetidas(null)), []);
  });

  test('gravarLink nunca manda url comum nem id inválido (R6)', async () => {
    const sf = servidorFalso();
    const { ML } = carregar({ origem: WWW });
    const { gravarLink } = ML._interno;
    for (const t of [{ id: 1, url: PRODUTO(4100000001) }, { id: 1, url: 'https://mercadolivre.com/sec/1xYz9Qw' },
      { id: 1, url: 'http://meli.la/abc' }, { id: 0, url: 'https://meli.la/abc' }, { id: '1', url: 'https://meli.la/abc' }]) {
      const r = await gravarLink(sf.f, SERVIDOR, t);
      assert.match(r.erro, /link ou id inválido/, JSON.stringify(t));
    }
    assert.equal(sf.chamadas.length, 0);
    const ok = await gravarLink(sf.f, SERVIDOR, { id: 1, url: 'https://meli.la/abc' });
    assert.deepEqual(js(ok), { ok: true, existe: true });
    conferirPatches(sf.patches());
  });
});

describe('afiliar(): guarda de origem e opções (CA11)', () => {
  for (const [origem, caminho] of [[LISTA, undefined], ['https://example.com', undefined], ['http://localhost:8765', undefined],
    [null, undefined], [WWW, null], [WWW, '/'], [WWW, '/afiliados/hub'], [WWW, '/p/MLB4100000001']]) {
    test(`em ${origem || 'página sem location'}${caminho === null ? ' sem pathname' : caminho || ''} mostra a mensagem e não faz nada`, async () => {
      const sf = servidorFalso();
      const gf = gerarFalso();
      const { ML, localStorage, mensagens } = carregar({ origem, caminho, fetch: sf.f });
      const estado = await ML.afiliar({ fetch: sf.f, gerar: gf.g });
      assert.match(estado.erro, /só roda numa aba de https:\/\/www\.mercadolivre\.com\.br\/afiliados\/linkbuilder/);
      assert.equal(sf.chamadas.length, 0);
      assert.equal(gf.pedidos.length, 0);
      assert.equal(localStorage.escritas, 0);
      assert.ok(mensagens.some((m) => m.tipo === 'error'));
    });
  }

  test('roda na página do linkbuilder (com e sem barra no fim)', async () => {
    for (const caminho of [LINKBUILDER, LINKBUILDER + '/']) {
      const sf = servidorFalso();
      const estado = await carregar({ origem: WWW, caminho, fetch: sf.f }).ML.afiliar({ gerar: gerarFalso().g, pausa: [0, 0] });
      assert.equal(estado.erro, null);
      assert.equal(estado.trocados.length, 2);
    }
  });

  test('coletar() não roda na aba do linkbuilder', async () => {
    const sf = servidorFalso();
    const estado = await carregar({ origem: WWW, caminho: LINKBUILDER, fetch: sf.f }).ML.coletar({ termos: ['Smart TV'] });
    assert.match(estado.erro, /só roda numa aba de https:\/\/lista/);
    assert.equal(sf.chamadas.length, 0);
  });

  const invalidas = [
    ['lote acima de 25', { lote: 26 }, /lote/],
    ['lote zero', { lote: 0 }, /lote/],
    ['gerar que não é função', { gerar: 'x' }, /gerar/],
    ['servidor de fora', { servidor: 'https://evil.example' }, /servidor deve ser/],
    ['itens com enviar:true', { itens: [PRODUTO(4100000001)] }, /itens só vale com enviar:false/],
    ['enviar:false sem itens', { enviar: false }, /com enviar:false, passe itens/],
    ['itens com id inválido', { enviar: false, itens: [{ id: -1, url: PRODUTO(4100000001) }] }, /itens deve ter/],
    ['itens com id repetido', { enviar: false, itens: [{ id: 1, url: 'a' }, { id: 1, url: 'b' }] }, /id repetido/],
  ];
  for (const [nome, opcoes, erro] of invalidas) {
    test(`recusa ${nome} sem fazer nada`, async () => {
      const sf = servidorFalso();
      const gf = gerarFalso();
      const { ML, localStorage } = carregar({ origem: WWW, fetch: sf.f });
      const estado = await ML.afiliar({ fetch: sf.f, gerar: gf.g, ...opcoes });
      assert.match(estado.erro, erro);
      assert.match(estado.erro, /Nada foi feito/);
      assert.equal(sf.chamadas.length + gf.pedidos.length + localStorage.escritas, 0);
    });
  }
});

describe('afiliar(): fluxo com servidor falso (CA14, CA16, CA17)', () => {
  test('troca pelo MLB, separa inelegíveis, repesca em lote de 10, confere e nunca envia url comum', async () => {
    const sf = servidorFalso([...ITENS_ML, { id: 7, loja: 'amazon', url: 'https://www.amazon.com.br/dp/B000?tag=x' }]);
    const gf = gerarFalso();
    const { ML, localStorage, mensagens } = carregar({ origem: WWW, fetch: sf.f });
    const estado = await ML.afiliar({ gerar: gf.g, pausa: [0, 0] });
    assert.equal(estado.erro, null);
    assert.deepEqual(js(estado.trocados).map((t) => [t.id, t.url]),
      [[IDS.tv1, 'https://meli.la/1AbC234'], [IDS.p1, 'https://meli.la/2PfM3kQ']]);
    assert.deepEqual(js(estado.inelegiveis).map((e) => e.id), [IDS.tv2, IDS.p2]);
    assert.deepEqual(js(estado.semResposta).map((s) => s.id), [IDS.tv3, IDS.p3]);
    assert.equal(estado.correcoes, 0);
    assert.deepEqual(js(estado.divergencias), []);
    assert.deepEqual(js(estado.repetidas), []);
    // 1º lote com os 6; repescagem só dos 2 sem resposta; conferência gera de novo os 2 trocados
    assert.deepEqual(gf.pedidos, [ITENS_ML.map((i) => i.url), [PRODUTO(4100000003), PRODUTO(4200000003)],
      [PRODUTO(4100000001), PRODUTO(4200000001)]]);

    assert.equal(sf.patches().length, 2);
    conferirPatches(sf.patches());
    assert.ok(sf.chamadas.every((c) => ['GET', 'PATCH'].includes(c.metodo)));
    assert.ok(sf.chamadas.every((c) => c.init.credentials === 'omit' && c.init.referrerPolicy === 'no-referrer'));
    assert.equal(sf.db.get(IDS.tv1).url, 'https://meli.la/1AbC234');
    assert.equal(sf.db.get(IDS.tv3).url, PRODUTO(4100000003));
    assert.equal(sf.db.get(7).url, 'https://www.amazon.com.br/dp/B000?tag=x');
    // só o error_code de elegibilidade fica guardado; o INTERNAL_SERVER_ERROR é tentado de novo na próxima
    assert.deepEqual(localStorage.lista('__afiliarML:http://localhost:8765').map((e) => e.id), [IDS.tv2]);
    const exclua = mensagens.findIndex((m) => m.texto.includes('Exclua pelo site'));
    const erros = mensagens.findIndex((m) => m.texto.includes('tento de novo na próxima'));
    assert.ok(exclua !== -1 && erros > exclua);
    assert.match(mensagens[exclua + 1].texto, /id 2 .*ITEM_NOT_ELIGIBLE/);
    assert.match(mensagens[erros + 1].texto, /id 5 .*INTERNAL_SERVER_ERROR/);
    assert.ok(mensagens.some((m) => m.texto.includes('achadosmenicas')));
  });

  test('lote misto: grava os meli.la e quem veio sem meli.la fica sem resposta, sem guardar nem "Exclua" (R8)', async () => {
    const sf = servidorFalso();
    const gf = gerarFalso(CREATELINK);
    const { ML, localStorage, mensagens } = carregar({ origem: WWW, fetch: sf.f });
    const estado = await ML.afiliar({ gerar: gf.g, pausa: [0, 0] });
    assert.equal(estado.erro, null);
    assert.deepEqual(js(estado.trocados).map((t) => t.id), [IDS.tv1, IDS.p1]);
    assert.equal(sf.patches().length, 2);
    conferirPatches(sf.patches());
    assert.deepEqual(js(estado.semResposta).sort((a, b) => a.id - b.id).map((s) => [s.id, s.motivo]),
      [[IDS.tv3, "link não é meli.la: confira 'Links curtos'"], [IDS.p3, undefined]]);
    assert.deepEqual(js(estado.naoMeliLa).map((e) => e.id), [IDS.tv3]);
    assert.deepEqual(js(estado.inelegiveis).map((e) => e.id), [IDS.tv2, IDS.p2]);
    // a repescagem só com quem falhou (TV3 e P3) não para a execução
    assert.deepEqual(gf.pedidos[1], [PRODUTO(4100000003), PRODUTO(4200000003)]);
    assert.equal(sf.db.get(IDS.tv3).url, PRODUTO(4100000003));
    assert.deepEqual(localStorage.lista('__afiliarML:http://localhost:8765').map((e) => e.id), [IDS.tv2]);
    const exclua = mensagens.findIndex((m) => m.texto.includes('Exclua pelo site'));
    assert.doesNotMatch(mensagens[exclua + 1].texto + mensagens[exclua + 2].texto, /id 3 /);
    assert.ok(mensagens.some((m) => m.tipo === 'warn' && /vieram sem meli\.la \(MLB4100000003\)/.test(m.texto)));
    assert.ok(mensagens.some((m) => /1 respostas sem meli\.la/.test(m.texto)));
  });

  test('lote sem nenhum meli.la ("Links curtos" desligado) para sem gravar nem guardar nada (R8)', async () => {
    const sf = servidorFalso();
    const gf = gerarFalso(TODO_LONGO);
    const { ML, localStorage, mensagens } = carregar({ origem: WWW, fetch: sf.f });
    const estado = await ML.afiliar({ gerar: gf.g, pausa: [0, 0] });
    assert.match(estado.erro, /link que não é meli\.la para 6 item\(ns\) \(MLB4100000001, MLB4100000002, MLB4100000003\).*Links curtos.*Nada deste lote foi gravado/);
    assert.equal(sf.patches().length, 0);
    assert.equal(gf.pedidos.length, 1);
    assert.equal(localStorage.escritas, 0);
    assert.equal(estado.naoMeliLa.length, 6);
    assert.deepEqual(js(estado.inelegiveis), []);
    assert.ok(!mensagens.some((m) => m.texto.includes('Exclua pelo site')));
    assert.equal(estado.rodando, false);
  });

  test('lote só com error_code e link longo, sem nenhum meli.la, também para (R8)', async () => {
    const sf = servidorFalso(ITENS_ML.slice(0, 3));
    const gf = gerarFalso(CREATELINK);   // TV1 vem meli.la, mas no lote de 1 não entra
    const estado = await carregar({ origem: WWW, fetch: sf.f }).ML.afiliar({ gerar: gf.g, pausa: [0, 0], lote: 1 });
    assert.equal(estado.erro.includes('MLB4100000003'), true);
    assert.deepEqual(js(estado.trocados).map((t) => t.id), [IDS.tv1]);
    assert.equal(sf.patches().length, 1);
  });

  test('link que não é meli.la na conferência também para, sem PATCH novo', async () => {
    const sf = servidorFalso(ITENS_ML.slice(0, 1));
    const certo = { urls: [{ origin_url: PRODUTO(4100000001), short_url: 'https://meli.la/A1' }] };
    const longo = { urls: [{ origin_url: PRODUTO(4100000001), short_url: 'https://mercadolivre.com/sec/x' }] };
    const gs = gerarEmSequencia([certo, longo]);
    const estado = await carregar({ origem: WWW, fetch: sf.f }).ML.afiliar({ gerar: gs.g, pausa: [0, 0] });
    assert.match(estado.erro, /não é meli\.la .* na conferência/);
    assert.equal(sf.patches().length, 1);
    assert.equal(sf.db.get(IDS.tv1).url, 'https://meli.la/A1');
  });

  test('lotes de no máximo 25, ou do tamanho pedido, também na conferência', async () => {
    const muitos = Array.from({ length: 30 }, (_, i) => ({ id: i + 1, loja: 'ml', url: PRODUTO(5000000000 + i) }));
    const tudo = { urls: muitos.map((i) => ({ origin_url: i.url + '-_JM', short_url: `https://meli.la/Z${i.id}` })) };
    for (const [lote, tamanhos] of [[undefined, [25, 5, 25, 5]], [10, [10, 10, 10, 10, 10, 10]]]) {
      const sf = servidorFalso(muitos);
      const gf = gerarFalso(tudo);
      const estado = await carregar({ origem: WWW, fetch: sf.f }).ML.afiliar({ gerar: gf.g, pausa: [0, 0], lote });
      assert.equal(estado.erro, null);
      assert.deepEqual(gf.pedidos.map((p) => p.length), tamanhos);
      assert.equal(estado.trocados.length, 30);
      assert.ok([...sf.db.values()].every((i) => i.url === `https://meli.la/Z${i.id}`));
    }
  });

  test('conferência: pares trocados na 1ª criação em lote são corrigidos quando a geração estabiliza (R1)', async () => {
    const sf = servidorFalso([ITENS_ML[0], ITENS_ML[3]]);
    const par = (a, b) => ({ urls: [{ origin_url: PRODUTO(4100000001), short_url: a }, { origin_url: PRODUTO(4200000001), short_url: b }] });
    const gs = gerarEmSequencia([par('https://meli.la/B', 'https://meli.la/A'), par('https://meli.la/A', 'https://meli.la/B')]);
    const { ML, mensagens } = carregar({ origem: WWW, fetch: sf.f });
    const estado = await ML.afiliar({ gerar: gs.g, pausa: [0, 0] });
    assert.equal(estado.erro, null);
    assert.equal(estado.correcoes, 2);
    assert.equal(sf.db.get(IDS.tv1).url, 'https://meli.la/A');
    assert.equal(sf.db.get(IDS.p1).url, 'https://meli.la/B');
    assert.deepEqual(js(estado.trocados).map((t) => t.url), ['https://meli.la/A', 'https://meli.la/B']);
    assert.equal(gs.pedidos.length, 3);   // lote, conferência com 2 correções, conferência com 0
    assert.equal(sf.patches().length, 4);
    conferirPatches(sf.patches());
    assert.ok(!mensagens.some((m) => m.tipo === 'warn' && /não chegou a 0/.test(m.texto)));
  });

  test('conferência que nunca estabiliza para em 3 voltas com aviso', async () => {
    const sf = servidorFalso(ITENS_ML.slice(0, 2));
    let n = 0;
    const sempreNovo = (urls) => ({ urls: urls.map((u) => ({ origin_url: u, short_url: `https://meli.la/N${++n}` })) });
    const gs = gerarEmSequencia([sempreNovo]);
    const { ML, mensagens } = carregar({ origem: WWW, fetch: sf.f });
    const estado = await ML.afiliar({ gerar: gs.g, pausa: [0, 0] });
    assert.equal(estado.erro, null);
    assert.equal(estado.correcoes, 6);
    assert.equal(gs.pedidos.length, 4);
    assert.ok(mensagens.some((m) => m.tipo === 'warn' && /não chegou a 0 correções em 3 voltas/.test(m.texto)));
  });

  test('conferência não troca um meli.la que esta execução não gravou: só avisa a divergência (S3)', async () => {
    const sf = servidorFalso();
    sf.trocarErrado.add(IDS.tv1);   // o banco fica com https://meli.la/Errado1 em vez do que foi enviado
    const { ML, mensagens } = carregar({ origem: WWW, fetch: sf.f });
    const estado = await ML.afiliar({ gerar: gerarFalso().g, pausa: [0, 0] });
    assert.equal(estado.erro, null);
    assert.equal(estado.correcoes, 0);
    assert.deepEqual(js(estado.divergencias), [{ id: IDS.tv1, mlb: 'MLB4100000001', banco: 'https://meli.la/Errado1',
      gerado: 'https://meli.la/1AbC234' }]);
    assert.equal(sf.db.get(IDS.tv1).url, 'https://meli.la/Errado1');
    assert.equal(sf.patches().filter((c) => c.url.endsWith(`/api/items/${IDS.tv1}`)).length, 1);
    assert.ok(mensagens.some((m) => m.tipo === 'warn' && m.texto.includes('divergência no item 1')));
  });

  test('aponta url repetida entre itens do ML', async () => {
    const sf = servidorFalso([...ITENS_ML, { id: 8, loja: 'ml', url: 'https://meli.la/Dup1' },
      { id: 9, loja: 'ml', url: 'https://meli.la/Dup1' }]);
    const { ML, mensagens } = carregar({ origem: WWW, fetch: sf.f });
    const estado = await ML.afiliar({ gerar: gerarFalso().g, pausa: [0, 0] });
    assert.deepEqual(js(estado.repetidas), [{ url: 'https://meli.la/Dup1', ids: [8, 9] }]);
    assert.ok(mensagens.some((m) => m.tipo === 'warn' && m.texto.includes('ids 8, 9')));
  });

  test('inelegíveis guardados não voltam ao linkbuilder e saem da lista quando o dono exclui', async () => {
    const sf = servidorFalso();
    const { ML, localStorage, mensagens } = carregar({ origem: WWW, fetch: sf.f });
    await ML.afiliar({ gerar: gerarFalso().g, pausa: [0, 0] });

    const gf = gerarFalso();
    const segunda = await ML.afiliar({ gerar: gf.g, pausa: [0, 0] });
    const pedidas = gf.pedidos.flat();
    assert.ok(!pedidas.includes(PRODUTO(4100000002)), 'o inelegível guardado voltou ao linkbuilder');
    assert.ok(pedidas.includes(PRODUTO(4200000002)), 'o erro que não é de elegibilidade devia ser tentado de novo');
    assert.deepEqual(js(segunda.inelegiveis).map((e) => e.id), [IDS.tv2, IDS.p2]);
    assert.ok(mensagens.some((m) => m.texto.includes('Exclua pelo site')));

    sf.db.delete(IDS.tv2);   // o dono excluiu pelo site
    const terceira = await ML.afiliar({ gerar: gerarFalso().g, pausa: [0, 0] });
    assert.deepEqual(js(terceira.inelegiveis).map((e) => e.id), [IDS.p2]);
    assert.deepEqual(localStorage.lista('__afiliarML:http://localhost:8765'), []);

    ML.zerar('http://localhost:8765', localStorage);
    assert.equal(localStorage.lista('__afiliarML:http://localhost:8765'), null);
  });

  test('com enviar:false não chama o servidor e devolve o que trocaria', async () => {
    const sf = servidorFalso();
    const gf = gerarFalso();
    const { ML, localStorage } = carregar({ origem: WWW, fetch: sf.f });
    const estado = await ML.afiliar({ enviar: false, gerar: gf.g, pausa: [0, 0],
      itens: [PRODUTO(4100000001), PRODUTO(4100000002), { id: 40, url: PRODUTO(4200000001) }, 'sem codigo'] });
    assert.equal(estado.erro, null);
    assert.equal(sf.chamadas.length, 0);
    assert.equal(localStorage.escritas, 0);
    assert.deepEqual(js(estado.trocados).map((t) => [t.id, t.url]),
      [[1, 'https://meli.la/1AbC234'], [40, 'https://meli.la/2PfM3kQ']]);
    assert.deepEqual(js(estado.inelegiveis).map((e) => [e.id, e.mlb]), [[4, null], [2, 'MLB4100000002']]);
  });

  test('com enviar:false a conferência compara com a memória e corrige os pares trocados', async () => {
    const sf = servidorFalso();
    const par = (a, b) => ({ urls: [{ origin_url: PRODUTO(4100000001), short_url: a }, { origin_url: PRODUTO(4200000001), short_url: b }] });
    const gs = gerarEmSequencia([par('https://meli.la/B', 'https://meli.la/A'), par('https://meli.la/A', 'https://meli.la/B')]);
    const estado = await carregar({ origem: WWW, fetch: sf.f }).ML.afiliar({ enviar: false, gerar: gs.g, pausa: [0, 0],
      itens: [PRODUTO(4100000001), PRODUTO(4200000001)] });
    assert.equal(estado.correcoes, 2);
    assert.deepEqual(js(estado.trocados).map((t) => t.url), ['https://meli.la/A', 'https://meli.la/B']);
    assert.equal(sf.chamadas.length, 0);
  });

  test('parar() entre lotes termina o lote atual e não começa o próximo', async () => {
    let ML;
    const sf = servidorFalso();
    const gf = gerarFalso(SEM_LONGO, () => ML.parar());
    ({ ML } = carregar({ origem: WWW, fetch: sf.f }));
    const t0 = Date.now();
    const estado = await ML.afiliar({ gerar: gf.g, lote: 2, pausa: [10000, 10000] });
    assert.ok(Date.now() - t0 < 2000);
    assert.equal(estado.parado, true);
    assert.equal(estado.erro, null);
    assert.equal(gf.pedidos.length, 1);
    assert.deepEqual(js(estado.trocados).map((t) => t.id), [IDS.tv1]);
    assert.equal(ML.estado.rodando, false);
  });

  test('item excluído no meio não conta como trocado', async () => {
    const sf = servidorFalso();
    const gf = gerarFalso(SEM_LONGO, () => sf.db.delete(IDS.p1));
    const estado = await carregar({ origem: WWW, fetch: sf.f }).ML.afiliar({ gerar: gf.g, pausa: [0, 0] });
    assert.equal(estado.erro, null);
    assert.deepEqual(js(estado.trocados).map((t) => t.id), [IDS.tv1]);
  });

  test('falha do linkbuilder ou do servidor para com mensagem clara', async () => {
    let sf = servidorFalso();
    const quebra = async () => { throw new Error('o linkbuilder não respondeu ao createLink'); };
    let estado = await carregar({ origem: WWW, fetch: sf.f }).ML.afiliar({ gerar: quebra });
    assert.match(estado.erro, /o linkbuilder falhou \(o linkbuilder não respondeu ao createLink\)/);
    assert.equal(sf.patches().length, 0);
    assert.equal(estado.rodando, false);

    sf = servidorFalso();
    const recusa = async (url, init = {}) => (init.method === 'PATCH'
      ? resposta(400, { error: 'url precisa ser link de afiliado' }, url) : sf.f(url, init));
    estado = await carregar({ origem: WWW, fetch: recusa }).ML.afiliar({ gerar: gerarFalso().g, pausa: [0, 0] });
    assert.match(estado.erro, /recusou o link do item 1 com 400: url precisa ser link de afiliado/);

    const fora = async () => { throw new TypeError('Failed to fetch'); };
    estado = await carregar({ origem: WWW, fetch: fora }).ML.afiliar({ gerar: gerarFalso().g });
    assert.match(estado.erro, /não consegui falar com o servidor em http:\/\/localhost:8765/);
  });
});

/**
 * Página falsa do linkbuilder: rótulo "Links curtos", textarea, botão "Gerar" que dispara o createLink.
 * rotulo: 'liga' (controle desmarcado que o clique liga), 'ligado', 'nao-liga' (clique não muda), 'sem-controle', 'ausente'.
 * corpo: o corpo do pedido do createLink (texto); padrão sem etiqueta.
 */
function linkbuilderFalso({ via = 'fetch', resp = SEM_LONGO, semCaixa = false, rotulo: modo = 'liga', corpo = '{}' } = {}) {
  class Elemento {
    constructor(texto) { this.textContent = texto; this.cliques = 0; this.disabled = false; this.eventos = []; }
    click() { this.cliques++; if (this.aoClicar) this.aoClicar(); }
    dispatchEvent(e) { this.eventos.push(e); return true; }
  }
  class HTMLTextAreaElement extends Elemento {}
  const valores = [];
  Object.defineProperty(HTMLTextAreaElement.prototype, 'value', {
    get() { return this.v; }, set(v) { valores.push(v); this.v = v; }, configurable: true,
  });
  class Event { constructor(type, init) { this.type = type; this.bubbles = Boolean(init && init.bubbles); } }
  const rotulo = new Elemento('Links curtos');
  if (modo !== 'sem-controle') rotulo.control = { checked: modo === 'ligado' };
  if (modo === 'liga') rotulo.aoClicar = () => { rotulo.control.checked = !rotulo.control.checked; };
  const caixa = new HTMLTextAreaElement('');
  const outro = new Elemento('Copiar');
  const botao = new Elemento('Gerar');
  const capturas = { outros: 0 };
  const respostaDe = (dados) => ({ ok: true, status: 200, clone: () => ({ json: async () => dados }), json: async () => dados });
  const pedidas = () => { const ped = new Set(String(caixa.v).split('\n').map(mlbDe)); return { urls: resp.urls.filter((e) => ped.has(mlbDe(e.origin_url))) }; };
  const pagina = {
    fetch: async (url) => { if (!String(url).includes('createLink')) capturas.outros++; return respostaDe(String(url).includes('createLink') ? pedidas() : { urls: [] }); },
  };
  class XMLHttpRequest {
    constructor() { this.ouvintes = []; this.responseType = ''; }
    addEventListener(tipo, fn) { if (tipo === 'loadend') this.ouvintes.push(fn); }
    open(metodo, url) { this.url = url; }
    send() { setTimeout(() => { this.responseText = JSON.stringify(pedidas()); this.ouvintes.forEach((fn) => fn.call(this)); }, 5); }
  }
  const abrirOriginal = XMLHttpRequest.prototype.open;
  const enviarOriginal = XMLHttpRequest.prototype.send;
  let ctx;
  botao.aoClicar = () => {
    // a página faz uma chamada qualquer antes: o gancho não pode confundir com o createLink
    ctx.fetch('/afiliados/outra-coisa', { method: 'POST', body: '{"tag":"outra"}' });
    if (via === 'fetch') ctx.fetch(new URL(`${WWW}/affiliate-program/api/v2/affiliates/createLink`), { method: 'POST', body: corpo });
    else { const x = new ctx.XMLHttpRequest(); x.open('POST', '/affiliate-program/api/v2/affiliates/createLink'); x.send(corpo); }
  };
  const document = {
    querySelectorAll(sel) {
      if (sel === 'label') return modo === 'ausente' ? [] : [rotulo];
      if (sel === 'textarea') return semCaixa ? [] : [caixa];
      if (sel === 'button') return [outro, botao];
      return [];
    },
  };
  const montar = (c) => { ctx = c; Object.assign(c, { document, HTMLTextAreaElement, Event, XMLHttpRequest }); };
  return { montar, pagina, rotulo, caixa, botao, valores, capturas, XMLHttpRequest, abrirOriginal, enviarOriginal };
}

/** Carrega na aba do linkbuilder com a página falsa montada. */
function carregarLinkbuilder(lb) {
  const r = carregar({ origem: WWW, caminho: LINKBUILDER, fetch: lb.pagina.fetch });
  lb.montar(r.ctx);
  return r;
}

describe('afiliar(): operação da página e gancho do createLink (CA16, R2, S2)', () => {
  for (const via of ['fetch', 'XMLHttpRequest']) {
    test(`gerarNaPagina preenche, clica em Gerar e captura o createLink via ${via}`, async () => {
      const lb = linkbuilderFalso({ via, corpo: JSON.stringify({ urls: [], tag: 'achadosmenicas' }) });
      const { ctx, ML, mensagens } = carregarLinkbuilder(lb);
      const urls = ITENS_ML.map((i) => i.url);
      const estado = await ML.afiliar({ enviar: false, itens: urls, pausa: [0, 0] });
      assert.equal(estado.erro, null);
      assert.deepEqual(js(estado.trocados).map((t) => [t.id, t.url]),
        [[1, 'https://meli.la/1AbC234'], [4, 'https://meli.la/2PfM3kQ']]);
      assert.deepEqual(js(estado.inelegiveis).map((e) => e.id), [2, 5]);
      assert.equal(lb.rotulo.cliques, 1, '"Links curtos" já ligado não pode ser desligado nos lotes seguintes');
      assert.deepEqual(lb.valores, [urls.join('\n'), [PRODUTO(4100000003), PRODUTO(4200000003)].join('\n'),
        [PRODUTO(4100000001), PRODUTO(4200000001)].join('\n')]);
      assert.ok(lb.caixa.eventos.every((e) => e.type === 'input' && e.bubbles));
      assert.equal(lb.botao.cliques, 3);
      assert.equal(lb.capturas.outros, 3);
      assert.ok(!mensagens.some((m) => m.tipo === 'warn' && /etiqueta/.test(m.texto)), 'a etiqueta certa não devia gerar aviso');
      // no fim o gancho sai: fetch e XHR voltam a ser os da página
      assert.equal(ctx.fetch, lb.pagina.fetch);
      assert.equal(lb.XMLHttpRequest.prototype.open, lb.abrirOriginal);
      assert.equal(lb.XMLHttpRequest.prototype.send, lb.enviarOriginal);
    });
  }

  for (const via of ['fetch', 'XMLHttpRequest']) {
    test(`etiqueta diferente de achadosmenicas no pedido (${via}) para antes de qualquer PATCH (S2)`, async () => {
      const lb = linkbuilderFalso({ via, corpo: JSON.stringify({ data: { urls: [], tag: 'outra-conta' } }) });
      const { ctx, ML } = carregarLinkbuilder(lb);
      const sf = servidorFalso();
      const estado = await ML.afiliar({ fetch: sf.f, pausa: [0, 0] });
      assert.match(estado.erro, /etiqueta "outra-conta", não achadosmenicas/);
      assert.equal(sf.patches().length, 0);
      assert.equal(ctx.fetch, lb.pagina.fetch);
    });
  }

  test('sem etiqueta legível no pedido: avisa uma vez e segue (S2)', async () => {
    const lb = linkbuilderFalso({ corpo: 'urls=a,b' });
    const { ML, mensagens } = carregarLinkbuilder(lb);
    const estado = await ML.afiliar({ enviar: false, itens: ITENS_ML.map((i) => i.url), pausa: [0, 0] });
    assert.equal(estado.erro, null);
    assert.equal(mensagens.filter((m) => m.tipo === 'warn' && /não consegui ler a etiqueta/.test(m.texto)).length, 1);
  });

  test('sem o rótulo "Links curtos" para com mensagem clara (R2)', async () => {
    const lb = linkbuilderFalso({ rotulo: 'ausente' });
    const { ML } = carregarLinkbuilder(lb);
    const estado = await ML.afiliar({ enviar: false, itens: [PRODUTO(4100000001)] });
    assert.match(estado.erro, /não achei a opção "Links curtos"/);
    assert.equal(lb.botao.cliques, 0);
  });

  test('"Links curtos" sem controle detectável: não clica, avisa e o link longo para o lote (R2)', async () => {
    const lb = linkbuilderFalso({ rotulo: 'sem-controle', resp: TODO_LONGO });
    const { ML, mensagens } = carregarLinkbuilder(lb);
    const estado = await ML.afiliar({ enviar: false, itens: ITENS_ML.map((i) => i.url), pausa: [0, 0] });
    assert.equal(lb.rotulo.cliques, 0);
    assert.ok(mensagens.some((m) => m.tipo === 'warn' && /confira à mão/.test(m.texto)));
    assert.match(estado.erro, /não é meli\.la/);
  });

  test('"Links curtos" que não liga com o clique para com mensagem clara (R2)', async () => {
    const lb = linkbuilderFalso({ rotulo: 'nao-liga' });
    const { ML } = carregarLinkbuilder(lb);
    const estado = await ML.afiliar({ enviar: false, itens: [PRODUTO(4100000001)] });
    assert.match(estado.erro, /não consegui ligar "Links curtos"/);
    assert.equal(lb.botao.cliques, 0);
  });

  test('sem a caixa de texto do linkbuilder para com mensagem clara', async () => {
    const lb = linkbuilderFalso({ semCaixa: true });
    const { ctx, ML } = carregarLinkbuilder(lb);
    const estado = await ML.afiliar({ enviar: false, itens: [PRODUTO(4100000001)] });
    assert.match(estado.erro, /não achei a caixa de texto do linkbuilder/);
    assert.equal(ctx.fetch, lb.pagina.fetch);
  });
});

describe('afiliar(): integração com o servidor.py (CA14, CA16)', () => {
  const srv = usarServidor();

  test('"Links curtos" desligado não grava nada; depois, PATCH aceito com a Origin do www e nenhuma url comum enviada', async () => {
    const { porta, servidor } = srv;
    // semeia com a própria coleta (Origin da lista): 3 itens da TV e 3 de perfume
    const lista = fetchNode(porta, LISTA);
    const semear = async (url, init = {}) => (String(url).startsWith('/')
      ? resposta(200, paginaPorSlug(String(url)), LISTA + url) : lista(url, init));
    const coleta = await carregar({ fetch: semear }).ML.coletar({ servidor, termos: ['Smart TV', 'Body splash'], pausa: [0, 0] });
    assert.equal(coleta.erro, null);
    assert.equal(coleta.inserido, 6);

    const www = fetchNode(porta, WWW);
    const chamadas = [];
    const registrar = async (url, init = {}) => {
      const r = await www(url, init);
      chamadas.push({ url: String(url), metodo: init.method || 'GET', init, status: r.status, cors: r.headers['access-control-allow-origin'] });
      return r;
    };
    const pendentes = async () => (await (await www(`${servidor}/api/ml-sem-afiliado`)).json()).map((p) => mlbDe(p.url));

    // 1ª tentativa: "Links curtos" desligado, nenhum link meli.la
    const desligado = await carregar({ origem: WWW, caminho: LINKBUILDER, fetch: registrar })
      .ML.afiliar({ servidor, gerar: gerarFalso(TODO_LONGO).g, pausa: [0, 0] });
    assert.match(desligado.erro, /não é meli\.la/);
    assert.equal(chamadas.filter((c) => c.metodo === 'PATCH').length, 0);
    assert.equal((await pendentes()).length, 6);

    // 2ª: "Links curtos" ligado; a fixture inteira, com um link longo no meio (lote misto)
    const estado = await carregar({ origem: WWW, caminho: LINKBUILDER, fetch: registrar })
      .ML.afiliar({ servidor, gerar: gerarFalso(CREATELINK).g, pausa: [0, 0] });
    assert.equal(estado.erro, null);
    assert.deepEqual(js(estado.trocados).map((t) => t.mlb), ['MLB4100000001', 'MLB4200000001']);
    assert.deepEqual(js(estado.inelegiveis).map((e) => e.mlb), ['MLB4100000002', 'MLB4200000002']);
    assert.deepEqual(js(estado.semResposta).map((s) => s.mlb).sort(), ['MLB4100000003', 'MLB4200000003']);
    assert.equal(estado.correcoes, 0);

    const patches = chamadas.filter((c) => c.metodo === 'PATCH');
    assert.equal(patches.length, 2);
    conferirPatches(patches);
    assert.ok(chamadas.every((c) => ['GET', 'PATCH'].includes(c.metodo)));
    assert.ok(chamadas.every((c) => c.status === 200 && c.cors === WWW), JSON.stringify(chamadas.map((c) => [c.metodo, c.url, c.status])));

    const itens = await (await www(`${servidor}/api/items`)).json();
    const porMLB = new Map(itens.map((i) => [i.item_id, i]));
    assert.equal(porMLB.get('MLB4100000001').url, 'https://meli.la/1AbC234');
    assert.equal(porMLB.get('MLB4200000001').url, 'https://meli.la/2PfM3kQ');
    assert.equal(porMLB.get('MLB4100000003').url, PRODUTO(4100000003));   // o link comum do ML não foi gravado
    assert.equal(porMLB.get('MLB4100000003').cat, ABA_TV);
    assert.deepEqual(await pendentes(), ['MLB4100000002', 'MLB4100000003', 'MLB4200000002', 'MLB4200000003']);
  });
});

// ================================================================== atualizar() (plano atualizar-precos, etapa 5)
// CA3: lote do ML no console, só sobre itens que já existem (so_existentes), sem o corte de 30 e com progresso por dia.
// CA5: card usado, fora do piso ou sem preço não vai no lote; o resumo conta cada um e o ausente do servidor.

const CHAVE_ATUALIZAR = '__atualizarML:http://localhost:8765';
const HOJE = () => new Date(2026, 10, 4, 10, 30);          // 2026-11-04, hora local
const AMANHA = () => new Date(2026, 10, 5, 23, 50);        // 2026-11-05 no fim do dia local (já é dia 6 em UTC no Brasil)

/** Card sintético para o atualizar(); preco null tira o componente de preço, alt '' tira a avaliação. */
function cardAtu(mlb, { titulo = `Produto ${mlb}`, preco = 100, alt = ALT_NO_PISO, meta = {} } = {}) {
  const components = [{ type: 'title', title: { text: titulo } }];
  if (preco !== null) components.push({ type: 'price', price: { current_price: { value: preco } } });
  if (alt) components.push({ type: 'review_compacted', review_compacted: { alt_text: alt } });
  return { id: 'POLYCARD', polycard: { metadata: { id: 'MLB' + mlb, ...meta }, components } };
}
function paginaAtu(cards) {
  const literal = JSON.stringify(JSON.stringify({ results: cards })).replace(/'/g, "\\'").replace(/</g, '\\x3C');
  return `<script>_n.ctx.s["x"].q(${literal});</script>`;
}

/**
 * Servidor falso que já entende so_existentes: os MLB de `existentes` contam como atualizados, os outros como
 * ausentes, e nada é inserido. `pedidos` guarda os corpos recebidos.
 */
function servidorAtu(existentes = null) {
  const pedidos = [];
  const servidor = async (url, init) => {
    const corpo = JSON.parse(init.body);
    pedidos.push(corpo);
    const ids = corpo.items.map((i) => i.item_id);
    const atualizado = existentes ? ids.filter((id) => existentes.includes(id)).length : ids.length;
    return { status: 200, corpo: { inserido: 0, atualizado, ausente: ids.length - atualizado, total: 99 } };
  };
  return { servidor, pedidos, lotes: () => pedidos.filter((p) => p.items.length) };
}

describe('atualizar(): guarda de origem e opções (CA3)', () => {
  for (const origem of [WWW, 'https://example.com', 'http://localhost:8765', null]) {
    test(`em ${origem || 'página sem location'} mostra a mensagem e não faz fetch`, async () => {
      const ff = fetchFalso();
      const { ML, mensagens, localStorage } = carregar({ origem, fetch: ff.f });
      const estado = await ML.atualizar({ cat: ABA_TV, fetch: ff.f, agora: HOJE });
      assert.match(estado.erro, /^atualizar\(\) só roda numa aba de https:\/\/lista\.mercadolivre\.com\.br/);
      assert.equal(ff.chamadas.length, 0);
      assert.equal(localStorage.escritas, 0);
      assert.ok(mensagens.some((m) => m.tipo === 'error' && m.texto.includes('lista.mercadolivre.com.br')));
      assert.equal(estado.rodando, false);
    });
  }

  const invalidas = [
    ['sem cat nem termos', {}, /passe cat .* ou termos/],
    ['cat que não é aba', { cat: 'Black Friday | Eletrônicos' }, /cat deve ser uma das abas/],
    ['cat que não é texto', { cat: 7 }, /cat deve ser uma das abas/],
    ['cat herdada do protótipo', { cat: 'constructor' }, /cat deve ser uma das abas/],
    ['termo de outra aba', { cat: ABA_TV, termos: ['Smart TV', 'Body splash'] }, /não são da aba "TV, Alexa e Casa Conectada": \["Body splash"\]/],
    ['termo fora de buscas.json', { termos: ['Black Friday'] }, /termos fora de buscas\.json/],
    ['termos vazio', { termos: [] }, /termos deve ser/],
    ['termos texto', { termos: 'Smart TV' }, /termos deve ser/],
    ['porBusca (atualizar lê a página inteira)', { cat: ABA_TV, porBusca: 30 }, /não use porBusca/],
    ['ordem inválida', { cat: ABA_TV, ordem: 'vendidos' }, /ordem deve ser/],
    ['ordem herdada do protótipo', { cat: ABA_TV, ordem: 'constructor' }, /ordem deve ser/],
    ['servidor de fora', { cat: ABA_TV, servidor: 'https://evil.example' }, /servidor deve ser/],
    ['enviar como texto', { cat: ABA_TV, enviar: 'false' }, /enviar deve ser/],
    ['agora que não é função', { cat: ABA_TV, agora: '2026-11-04' }, /agora deve ser uma função/],
    ['agora que devolve data inválida', { cat: ABA_TV, agora: () => new Date('x') }, /data válida/],
    ['agora que devolve texto', { cat: ABA_TV, agora: () => '2026-11-04' }, /data válida/],
    ['agora que lança', { cat: ABA_TV, agora: () => { throw new Error('x'); } }, /data válida/],
  ];
  for (const [nome, opcoes, erro] of invalidas) {
    test(`recusa ${nome} sem fazer fetch`, async () => {
      const ff = fetchFalso();
      const { ML, localStorage } = carregar({ fetch: ff.f });
      const estado = await ML.atualizar({ agora: HOJE, ...opcoes });
      assert.match(estado.erro, erro);
      assert.match(estado.erro, /Nada foi feito/);
      assert.equal(ff.chamadas.length, 0);
      assert.equal(localStorage.escritas, 0);
      assert.equal(estado.rodando, false);
    });
  }

  test('com cat e sem termos lê todos os termos da aba, mais o do ALIAS que aponta para ela', async () => {
    const ff = fetchFalso();
    const { ML } = carregar({ fetch: ff.f });
    const estado = await ML.atualizar({ cat: ABA_TV, enviar: false, pausa: [0, 0] });
    assert.equal(estado.erro, null);
    const esperados = [...BUSCAS_JSON[ABA_TV], 'Caixa inteligente assistente virtual'];
    assert.deepEqual(js(estado.feitos), esperados);
    assert.deepEqual(ff.doML().map((c) => c.url), esperados.map((t) => '/' + js(ML.slug(t))));
    assert.equal(estado.cat, ABA_TV);
  });

  test('cat com espaço em volta vale; termos sem cat podem misturar abas', async () => {
    const ff = fetchFalso();
    const { ML } = carregar({ fetch: ff.f });
    let estado = await ML.atualizar({ cat: ` ${ABA_TV} `, termos: ['Smart TV'], enviar: false });
    assert.equal(estado.erro, null);
    assert.equal(estado.cat, ABA_TV);
    estado = await ML.atualizar({ termos: ['Smart TV', 'Body splash'], enviar: false, pausa: [0, 0] });
    assert.equal(estado.erro, null);
    assert.equal(estado.cat, null);
    assert.deepEqual(js(estado.feitos), ['Smart TV', 'Body splash']);
  });
});

describe('atualizar(): envio só de itens existentes (CA3, CA5)', () => {
  test('contrato: confere o servidor com lote vazio e manda cada termo com so_existentes:true', async () => {
    const sa = servidorAtu();
    const ff = fetchFalso({ servidor: sa.servidor });
    const { ML } = carregar({ fetch: ff.f });
    const estado = await ML.atualizar({ termos: ['Smart TV', 'Body splash'], pausa: [0, 0], agora: HOJE });
    assert.equal(estado.erro, null);
    assert.deepEqual(js(estado.feitos), ['Smart TV', 'Body splash']);

    const posts = ff.doServidor();
    assert.equal(posts.length, 3);
    // o primeiro pedido ao servidor vem antes de qualquer busca no ML
    assert.equal(ff.chamadas[0].url, `${SERVIDOR}/api/items`);
    assert.deepEqual(JSON.parse(posts[0].init.body), { items: [], so_existentes: true });
    const esperado = [['Smart TV', ABA_TV], ['Body splash', 'Perfumes e Perfumaria']];
    posts.forEach((c, i) => {
      assert.equal(c.url, `${SERVIDOR}/api/items`);
      assert.equal(c.init.method, 'POST');
      assert.equal(c.init.credentials, 'omit');
      assert.equal(c.init.referrerPolicy, 'no-referrer');
      assert.deepEqual(js(c.init.headers), { 'Content-Type': 'application/json' });
      const corpo = JSON.parse(c.init.body);
      assert.deepEqual(Object.keys(corpo), ['items', 'so_existentes']);
      assert.equal(corpo.so_existentes, true);
      if (!i) return;
      assert.equal(corpo.items.length, 3);
      for (const it of corpo.items) {
        assert.deepEqual(Object.keys(it), ['loja', 'item_id', 'cat', 'busca', 'url', 'data']);
        assert.equal(it.loja, 'ml');
        assert.equal(it.busca, esperado[i - 1][0]);
        assert.equal(it.cat, esperado[i - 1][1]);
        assert.match(it.url, /^https:\/\/produto\.mercadolivre\.com\.br\/MLB-\d+$/);
        assert.deepEqual(Object.keys(it.data), CAMPOS);
        assert.ok(Object.values(it.data).every((v) => typeof v === 'string'));
      }
    });
    assert.deepEqual(JSON.parse(posts[1].init.body).items, [ITEM_TV, ITEM_BOX, ITEM_SUPORTE]);
    assert.equal(estado.atualizado, 6);
    assert.equal(estado.ausente, 0);
    for (const c of ff.doML()) assert.equal(c.init.credentials, 'include');
  });

  test('sem o corte de 30: a página inteira vai num lote só', async () => {
    const cards = Array.from({ length: 47 }, (_, i) => cardAtu(8000000001 + i));
    const sa = servidorAtu();
    const ff = fetchFalso({ pagina: () => paginaAtu(cards), servidor: sa.servidor });
    const { ML } = carregar({ fetch: ff.f });
    const estado = await ML.atualizar({ termos: ['Smart TV'], agora: HOJE });
    assert.equal(estado.erro, null);
    assert.equal(sa.lotes().length, 1);
    assert.equal(sa.lotes()[0].items.length, 47);
    assert.equal(estado.lidos, 47);
    assert.equal(estado.atualizado, 47);
    assert.equal(estado.itens.length, 47);
  });

  test('usado, fora do piso e sem preço ficam fora do lote e entram no resumo; ausente vem do servidor', async () => {
    const cards = [
      cardAtu(8100000001, { preco: 2569 }),                                       // ok, existe
      cardAtu(8100000002, { alt: 'Classificação 4.4 de 5 estrelas. Mais de 1000 produtos vendidos.' }), // fora do piso
      cardAtu(8100000003, { titulo: 'Smart TV 50 Usada' }),                      // usado (título)
      cardAtu(8100000004, { meta: { condition: 'used' } }),                       // usado (condição)
      cardAtu(8100000005, { preco: null }),                                       // sem preço
      cardAtu(8100000006, { preco: 0 }),                                          // preço zero
      cardAtu(8100000007, { preco: 0.004 }),                                      // arredonda para R$ 0
      cardAtu(8100000008, { preco: 124.2 }),                                      // ok, não está no banco
      cardAtu(8100000001, { preco: 1 }),                                          // repetido: não conta de novo
    ];
    const sa = servidorAtu(['MLB8100000001']);
    const ff = fetchFalso({ pagina: () => paginaAtu(cards), servidor: sa.servidor });
    const { ML, mensagens } = carregar({ fetch: ff.f });
    const estado = await ML.atualizar({ termos: ['Smart TV'], agora: HOJE });
    assert.equal(estado.erro, null);
    const lote = sa.lotes()[0].items;
    assert.deepEqual(lote.map((i) => i.item_id), ['MLB8100000001', 'MLB8100000008']);
    assert.deepEqual(lote.map((i) => i.data.preco), ['R$ 2.569', 'R$ 124,20']);
    assert.deepEqual({ lidos: estado.lidos, foraDoPiso: estado.foraDoPiso, usados: estado.usados, semPreco: estado.semPreco,
      atualizado: estado.atualizado, ausente: estado.ausente }, { lidos: 8, foraDoPiso: 3, usados: 2, semPreco: 3, atualizado: 1, ausente: 1 });
    assert.deepEqual(js(estado.itens).map((i) => i.item_id), ['MLB8100000001', 'MLB8100000008']);
    const linhas = mensagens.map((m) => m.texto);
    assert.ok(linhas.some((l) => l.includes('8 lidos, 2 no lote (atualizado 1, ausente 1), 3 fora do piso (2 usados), 3 sem preço')),
      linhas.join('\n'));
    assert.ok(linhas.some((l) => l.includes('fim da atualização de 2026-11-04') && l.includes('3 sem preço') &&
      l.includes('atualizado 1, ausente 1')), linhas.join('\n'));
  });

  test('termo sem nenhum card que sirva não manda POST, mas conta como lido hoje', async () => {
    const ruins = [cardAtu(8200000001, { preco: null }), cardAtu(8200000002, { titulo: 'Tablet Usado' })];
    const sa = servidorAtu();
    const ff = fetchFalso({ pagina: (url) => (url === '/smart-tv' ? paginaAtu(ruins) : FIXTURE), servidor: sa.servidor });
    const { ML, localStorage } = carregar({ fetch: ff.f });
    const estado = await ML.atualizar({ termos: ['Smart TV', 'Body splash'], pausa: [0, 0], agora: HOJE });
    assert.equal(estado.erro, null);
    assert.deepEqual(sa.lotes().map((p) => p.items[0].busca), ['Body splash']);
    assert.deepEqual(js(estado.feitos), ['Smart TV', 'Body splash']);
    assert.deepEqual(localStorage.lista(CHAVE_ATUALIZAR), ['2026-11-04|relevancia|Smart TV', '2026-11-04|relevancia|Body splash']);
    assert.equal(estado.semPreco, 1);
    assert.equal(estado.usados, 1);
  });

  test('servidor antigo (sem so_existentes) é recusado antes de qualquer busca ou item enviado', async () => {
    // o servidor.py de antes da etapa 1 ignora so_existentes e responde sem "ausente"
    const antigo = async (url, init) => ({ status: 200,
      corpo: { inserido: JSON.parse(init.body).items.length, atualizado: 0, total: 9 } });
    const ff = fetchFalso({ servidor: antigo });
    const { ML, localStorage } = carregar({ fetch: ff.f });
    const estado = await ML.atualizar({ termos: ['Smart TV'], agora: HOJE });
    assert.match(estado.erro, /não conhece so_existentes/);
    assert.match(estado.erro, /Nada foi enviado/);
    assert.equal(ff.doML().length, 0);
    assert.equal(ff.doServidor().length, 1);
    assert.deepEqual(JSON.parse(ff.doServidor()[0].init.body).items, []);
    assert.equal(localStorage.escritas, 0);
    assert.equal(estado.rodando, false);
  });

  const respostasRuins = [
    ['que inseriu itens', { status: 200, corpo: { inserido: 1, atualizado: 2, ausente: 0, total: 9 } }, /resposta inesperada/],
    ['sem ausente', { status: 200, corpo: { inserido: 0, atualizado: 3, total: 9 } }, /resposta inesperada/],
    ['com ausente em texto', { status: 200, corpo: { inserido: 0, atualizado: 3, ausente: '0', total: 9 } }, /resposta inesperada/],
    ['que recusa', { status: 400, corpo: { error: 'so_existentes deve ser true ou false' } }, /recusou "Smart TV" com 400: so_existentes/],
    ['fora do ar', null, /não consegui falar com o servidor/],
  ];
  for (const [nome, resp, erro] of respostasRuins) {
    test(`servidor ${nome} no lote para a atualização e não marca o termo`, async () => {
      const servidor = async (url, init) => {
        if (!JSON.parse(init.body).items.length) return { status: 200, corpo: { inserido: 0, atualizado: 0, ausente: 0, total: 9 } };
        if (!resp) throw new TypeError('Failed to fetch');
        return resp;
      };
      const ff = fetchFalso({ servidor });
      const { ML, localStorage } = carregar({ fetch: ff.f });
      const estado = await ML.atualizar({ termos: ['Smart TV', 'Body splash'], pausa: [0, 0], agora: HOJE });
      assert.match(estado.erro, erro);
      assert.deepEqual(js(estado.feitos), []);
      assert.equal(ff.doML().length, 1);
      assert.equal(localStorage.lista(CHAVE_ATUALIZAR), null);
    });
  }

  test('teste do servidor recusado ou fora do ar para sem buscar nada no ML', async () => {
    for (const servidor of [async () => ({ status: 403, corpo: { error: 'origem não permitida' } }),
      async () => { throw new TypeError('Failed to fetch'); }]) {
      const ff = fetchFalso({ servidor });
      const { ML } = carregar({ fetch: ff.f });
      const estado = await ML.atualizar({ termos: ['Smart TV'], agora: HOJE });
      assert.match(estado.erro, /recusou o teste do so_existentes com 403: origem não permitida|não consegui falar com o servidor/);
      assert.equal(ff.doML().length, 0);
    }
  });

  test('captcha, página sem polycard e erro do ML param sem enviar nada do termo', async () => {
    const casos = [
      [{ urlFinal: 'https://www.mercadolivre.com.br/gz/account-verification' }, /captcha/],
      [{ pagina: () => '<html>nada</html>' }, /sem polycard.*A atualização parou/],
      [{ statusML: 503 }, /respondeu 503/],
    ];
    for (const [opcoes, erro] of casos) {
      const sa = servidorAtu();
      const ff = fetchFalso({ ...opcoes, servidor: sa.servidor });
      const { ML, localStorage } = carregar({ fetch: ff.f });
      const estado = await ML.atualizar({ termos: ['Smart TV'], agora: HOJE });
      assert.match(estado.erro, erro);
      assert.equal(sa.lotes().length, 0);
      assert.equal(localStorage.lista(CHAVE_ATUALIZAR), null);
    }
  });

  test('com enviar:false não fala com o servidor, nem para o teste, e não mexe no progresso', async () => {
    const ff = fetchFalso();
    const { ML, localStorage, mensagens } = carregar({ fetch: ff.f });
    const estado = await ML.atualizar({ termos: ['Smart TV'], enviar: false, agora: HOJE });
    assert.equal(estado.erro, null);
    assert.equal(ff.doServidor().length, 0);
    assert.equal(localStorage.escritas, 0);
    assert.deepEqual(js(estado.itens), [ITEM_TV, ITEM_BOX, ITEM_SUPORTE]);
    assert.ok(mensagens.some((m) => m.texto.includes('Nada foi enviado')));
  });
});

describe('atualizar(): progresso por dia, ordem e concorrência (CA3)', () => {
  test('chave própria por servidor e por dia; no mesmo dia pula, no dia seguinte lê de novo e esquece o dia velho', async () => {
    const sa = servidorAtu();
    const ff = fetchFalso({ servidor: sa.servidor });
    const { ML, localStorage } = carregar({ fetch: ff.f });
    let estado = await ML.atualizar({ termos: ['Smart TV'], agora: HOJE });
    assert.deepEqual(localStorage.lista(CHAVE_ATUALIZAR), ['2026-11-04|relevancia|Smart TV']);
    assert.equal(localStorage.lista('__coletaML:http://localhost:8765'), null, 'o progresso da coleta não muda');

    const n = ff.doML().length;
    estado = await ML.atualizar({ termos: ['Smart TV', 'Body splash'], pausa: [0, 0], agora: HOJE });
    assert.deepEqual(js(estado.pulados), ['Smart TV']);
    assert.deepEqual(js(estado.feitos), ['Body splash']);
    assert.equal(ff.doML().length, n + 1);

    estado = await ML.atualizar({ termos: ['Smart TV'], agora: AMANHA });
    assert.equal(estado.dia, '2026-11-05');
    assert.deepEqual(js(estado.pulados), []);
    assert.deepEqual(js(estado.feitos), ['Smart TV']);
    assert.deepEqual(localStorage.lista(CHAVE_ATUALIZAR), ['2026-11-05|relevancia|Smart TV']);

    await ML.atualizar({ termos: ['Smart TV'], servidor: 'http://127.0.0.1:8766', agora: AMANHA });
    assert.deepEqual(localStorage.lista('__atualizarML:http://127.0.0.1:8766'), ['2026-11-05|relevancia|Smart TV']);

    assert.equal(ML.zerar('http://localhost:8765', localStorage), true);
    assert.equal(localStorage.lista(CHAVE_ATUALIZAR), null);
    assert.deepEqual(localStorage.lista('__atualizarML:http://127.0.0.1:8766'), ['2026-11-05|relevancia|Smart TV']);
  });

  test('o progresso da coleta não faz o atualizar() pular termo, e o do atualizar não faz a coleta pular', async () => {
    const arm = memoria({ '__coletaML:http://localhost:8765': JSON.stringify(['Smart TV', 'caros|Smart TV']) });
    const sa = servidorAtu();
    const ff = fetchFalso({ servidor: sa.servidor });
    const { ML } = carregar({ fetch: ff.f, localStorage: arm });
    const estado = await ML.atualizar({ termos: ['Smart TV'], agora: HOJE });
    assert.deepEqual(js(estado.pulados), []);
    assert.deepEqual(js(estado.feitos), ['Smart TV']);
    const coleta = await ML.coletar({ termos: ['Body splash'] });
    assert.equal(coleta.erro, null);
    assert.deepEqual(arm.lista('__coletaML:http://localhost:8765'), ['Smart TV', 'caros|Smart TV', 'Body splash']);
    assert.deepEqual(arm.lista(CHAVE_ATUALIZAR), ['2026-11-04|relevancia|Smart TV']);
  });

  test("ordem 'caros' busca a listagem ordenada e tem progresso separado da relevância", async () => {
    const sa = servidorAtu();
    const ff = fetchFalso({ servidor: sa.servidor });
    const { ML, localStorage } = carregar({ fetch: ff.f });
    await ML.atualizar({ termos: ['Smart TV'], agora: HOJE });
    const estado = await ML.atualizar({ termos: ['Smart TV'], ordem: 'caros', agora: HOJE });
    assert.equal(estado.ordem, 'caros');
    assert.deepEqual(js(estado.pulados), []);
    assert.deepEqual(ff.doML().map((c) => c.url), ['/smart-tv', '/smart-tv_OrderId_PRICE*DESC']);
    assert.deepEqual(localStorage.lista(CHAVE_ATUALIZAR), ['2026-11-04|relevancia|Smart TV', '2026-11-04|caros|Smart TV']);
  });

  test('progresso ilegível ou com lixo é tolerado; entradas de outros dias são descartadas', async () => {
    for (const lixo of ['{lixo', JSON.stringify({ a: 1 }), JSON.stringify(['2026-11-04|relevancia|Smart TV', 7, null, '2026-11-03|relevancia|Body splash'])]) {
      const arm = memoria({ [CHAVE_ATUALIZAR]: lixo });
      const ff = fetchFalso({ servidor: servidorAtu().servidor });
      const estado = await carregar({ fetch: ff.f, localStorage: arm }).ML
        .atualizar({ termos: ['Smart TV', 'Body splash'], pausa: [0, 0], agora: HOJE });
      assert.equal(estado.erro, null);
      const pulouTv = lixo.startsWith('[');
      assert.deepEqual(js(estado.pulados), pulouTv ? ['Smart TV'] : []);
      // a entrada de 03/11 e o lixo somem; a de hoje fica
      assert.deepEqual(arm.lista(CHAVE_ATUALIZAR), ['2026-11-04|relevancia|Smart TV', '2026-11-04|relevancia|Body splash']);
    }
  });

  test('parar() durante a busca termina o termo atual e não começa o próximo', async () => {
    let ML;
    const ff = fetchFalso({ aoBuscar: () => ML.parar(), servidor: servidorAtu().servidor });
    ({ ML } = carregar({ fetch: ff.f }));
    const t0 = Date.now();
    const estado = await ML.atualizar({ termos: ['Smart TV', 'Body splash'], pausa: [10000, 10000], agora: HOJE });
    assert.ok(Date.now() - t0 < 2000, 'esperou a pausa mesmo com parar() pedido');
    assert.equal(estado.parado, true);
    assert.deepEqual(js(estado.feitos), ['Smart TV']);
    assert.equal(ff.doML().length, 1);
    assert.equal(ML.estado.rodando, false);
  });

  test('atualizar() e coletar() não rodam ao mesmo tempo', async () => {
    let soltar;
    const trava = new Promise((r) => { soltar = r; });
    const ff = fetchFalso({ aoBuscar: () => trava, servidor: servidorAtu().servidor });
    const { ML, mensagens } = carregar({ fetch: ff.f });
    const primeira = ML.atualizar({ termos: ['Smart TV'], agora: HOJE });
    await new Promise((r) => setTimeout(r, 10));
    const coleta = await ML.coletar({ termos: ['Body splash'] });
    const outra = await ML.atualizar({ termos: ['Body splash'], agora: HOJE });
    assert.equal(coleta.rodando, true);
    assert.equal(outra, coleta);
    assert.equal(mensagens.filter((m) => m.tipo === 'error' && m.texto.includes('já há uma coleta rodando')).length, 2);
    soltar();
    const estado = await primeira;
    assert.equal(estado.erro, null);
    assert.deepEqual(ff.doML().map((c) => c.url), ['/smart-tv']);
  });
});

describe('atualizar(): integração com o servidor.py (CA3, CA5)', () => {
  const srv = usarServidor();

  test('só atualiza quem existe: não insere, preserva o meli.la, renova o preco_em e não apaga o preço de card sem preço', async () => {
    const { porta, servidor } = srv;
    const lista = fetchNode(porta, LISTA);
    const json = { 'Content-Type': 'application/json' };
    // semeia com a própria coleta: os 3 itens da TV da fixture
    const semear = async (url, init = {}) => (String(url).startsWith('/')
      ? resposta(200, FIXTURE, LISTA + url) : lista(url, init));
    const coleta = await carregar({ fetch: semear }).ML.coletar({ servidor, termos: ['Smart TV'] });
    assert.equal(coleta.inserido, 3);
    const lerItens = async () => new Map((await (await lista(`${servidor}/api/items`)).json()).map((i) => [i.item_id, i]));
    let porMLB = await lerItens();
    const tv = porMLB.get('MLB4100000001');
    let r = await lista(`${servidor}/api/items/${tv.id}`,
      { method: 'PATCH', headers: json, body: JSON.stringify({ url: 'https://meli.la/1AbC234' }) });
    assert.equal(r.status, 200);
    const boxAntes = porMLB.get('MLB4100000002');
    assert.ok(boxAntes.preco_em);
    await new Promise((res) => setTimeout(res, 1100));   // o agora() do servidor tem resolução de segundo

    // a página nova: TV com preço novo, TV Box sem preço, suporte usado e um produto que não está no banco
    const cards = [
      cardAtu(4100000001, { titulo: 'Smart TV Samsung 50" Crystal UHD 4K', preco: 2199 }),
      cardAtu(4100000002, { titulo: 'TV Box 4K', preco: null }),
      cardAtu(4100000003, { titulo: 'Suporte de parede para TV usado' }),
      cardAtu(4100000099, { titulo: 'TV nova que nunca foi coletada', preco: 999 }),
    ];
    const chamadas = [];
    const f = async (url, init = {}) => {
      chamadas.push({ url: String(url), init });
      return String(url).startsWith('/') ? resposta(200, paginaAtu(cards), LISTA + url) : lista(url, init);
    };
    const estado = await carregar({ fetch: f }).ML.atualizar({ servidor, cat: ABA_TV, termos: ['Smart TV'], agora: HOJE });
    assert.equal(estado.erro, null);
    assert.deepEqual({ atualizado: estado.atualizado, ausente: estado.ausente, semPreco: estado.semPreco, usados: estado.usados },
      { atualizado: 1, ausente: 1, semPreco: 1, usados: 1 });

    porMLB = await lerItens();
    assert.equal(porMLB.size, 3, 'o produto novo não pode ser inserido');
    assert.ok(!porMLB.has('MLB4100000099'));
    const tvDepois = porMLB.get('MLB4100000001');
    assert.equal(tvDepois.url, 'https://meli.la/1AbC234');
    assert.equal(tvDepois.data.preco, 'R$ 2.199');
    assert.ok(tvDepois.preco_em > tv.preco_em, `${tvDepois.preco_em} devia ser mais novo que ${tv.preco_em}`);
    assert.equal(tvDepois.cat, ABA_TV);
    // card sem preço e card usado ficaram fora do lote: dados e preco_em antigos
    assert.deepEqual(porMLB.get('MLB4100000002').data, boxAntes.data);
    assert.equal(porMLB.get('MLB4100000002').preco_em, boxAntes.preco_em);
    assert.equal(porMLB.get('MLB4100000003').data.titulo, ITEM_SUPORTE.data.titulo);

    const posts = chamadas.filter((c) => !c.url.startsWith('/'));
    assert.deepEqual(posts.map((c) => JSON.parse(c.init.body).items.map((i) => i.item_id)),
      [[], ['MLB4100000001', 'MLB4100000099']]);
  });
});
