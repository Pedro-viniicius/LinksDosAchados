/*
 * coletar_ml.js: coleta do Mercado Livre para o site de achadinhos (servidor.py).
 *
 * Como usar no Chrome:
 *   1. Abra uma aba em https://lista.mercadolivre.com.br e abra o Console do DevTools (F12).
 *   2. Cole este arquivo inteiro e aperte Enter. Colar só define ColetaML; nada roda sozinho.
 *      Cole só o coletar_ml.js deste projeto: código de outra fonte no console da sua conta é perigoso.
 *   3. Rode, por exemplo (passe sempre os termos: sem `termos`, a coleta busca todos os de buscas.json):
 *        await ColetaML.coletar({termos: ['Body splash'], enviar: false})  // só monta os itens, não grava nada
 *        await ColetaML.coletar({termos: ['Body splash'], servidor: 'http://localhost:8766'})  // servidor de teste
 *        await ColetaML.coletar({termos: ColetaML.BUSCAS['Perfumes e Perfumaria']})
 *        await ColetaML.coletar({termos: ColetaML.BUSCAS['Perfumes e Perfumaria'], ordem: 'caros'})  // maior preço
 *        ColetaML.parar()                                                  // para depois do termo (ou lote) atual
 *   4. Depois, numa aba em https://www.mercadolivre.com.br/afiliados/linkbuilder, cole o arquivo e rode:
 *        await ColetaML.afiliar({enviar: false, itens: ['https://produto.mercadolivre.com.br/MLB-…']})
 *        await ColetaML.afiliar({servidor: 'http://localhost:8766'})       // troca as urls por meli.la
 *      Antes, confira na página que a etiqueta é achadosmenicas e que "Links curtos" está ligado. O script
 *      recusa se o pedido do createLink mostrar outra etiqueta e para se vier link que não é meli.la.
 *      Os inelegíveis aparecem no console: exclua pelo site (o script nunca apaga nada).
 *   5. ColetaML.zerar('http://localhost:8765') esquece o que está guardado no localStorage da aba em que roda:
 *      o progresso da coleta fica na aba lista. e os inelegíveis na aba www., então rode nas duas.
 *
 * Cada termo vira um POST em <servidor>/api/items com cat = chave de buscas.json e busca = termo.
 * O progresso fica no localStorage da aba, por servidor: termo já enviado não é coletado de novo.
 * ordem: 'relevancia' (padrão, a listagem de sempre) ou 'caros' (a mesma listagem por maior preço). O progresso da
 * relevância é o termo puro; o das outras ordens é "<ordem>|<termo>", então cada ordem coleta uma vez por termo.
 * afiliar() só manda PATCH com url https://meli.la/<código>, casando a resposta pelo código MLB.
 * Plano: docs/produto/planos/eletronicos-e-coleta-ml.md. Testes: node --test testes/coletar_ml.test.mjs
 *
 * O conteúdo do ML é dado não confiável: só JSON.parse, sem eval, sem HTML, e tudo vai como texto.
 */
(() => {
  'use strict';

  // colar de novo no meio de uma coleta trocaria o ColetaML e o parar() não alcançaria a coleta antiga
  const anterior = globalThis.ColetaML;
  if (anterior && anterior.estado && anterior.estado.rodando) {
    console.error('[ColetaML] há uma coleta rodando. Use ColetaML.parar(), espere terminar e cole de novo.');
    return;
  }

  const ORIGEM_LISTA = 'https://lista.mercadolivre.com.br';
  const SERVIDOR_PADRAO = 'http://localhost:8765';
  // só o servidor local; a porta é obrigatória porque o servidor.py confere o Host com a porta
  const RX_SERVIDOR = /^http:\/\/(localhost|127\.0\.0\.1):\d{1,5}$/;
  const RX_CAPTCHA = /captcha|account-verification|gz\//;
  const PREFIXO_PROGRESSO = '__coletaML:';
  const MAX_POR_BUSCA = 30;
  // sufixo da URL da listagem por ordem; o ML só oferece relevância, menor e maior preço (sem "mais vendidos")
  const ORDENS_ML = { relevancia: '', caros: '_OrderId_PRICE*DESC' };
  const PAUSA_PADRAO = [2500, 5000];   // ms entre um termo e outro, sorteado no intervalo
  const PRAZO_MS = 60000;              // cada requisição desiste depois disso
  const CAMPOS = ['titulo', 'preco', 'preco_antigo', 'desconto', 'avaliacao', 'num_avaliacoes',
    'vendas', 'frete', 'cupom', 'imagem'];

  // Cópia literal de buscas.json (termo → aba). O teste compara com o arquivo e imprime o bloco certo.
  // BUSCAS:inicio
  const BUSCAS = {
    "Black Friday | Eletrônicos": [
      "iPhone 17",
      "iPhone 16",
      "PlayStation 5 Slim",
      "Samsung Galaxy A17",
      "Samsung Galaxy A57",
      "Echo Dot Alexa",
      "Samsung Galaxy Fit3",
      "Smart TV 4K Samsung 50",
      "Smart TV 4K LG 55",
      "Notebook Dell",
      "Notebook Acer",
      "Notebook ASUS",
      "Fone Bluetooth JBL",
      "Fire TV Stick HD",
      "Kindle",
      "Kindle Paperwhite",
      "Tablet Samsung",
      "iPad Apple",
      "Caixa de som Bluetooth JBL",
      "Monitor Samsung",
      "Monitor AOC",
      "Nintendo Switch OLED",
      "Impressora Epson EcoTank L3250",
      "Controle PS5 DualSense",
      "Mouse Logitech M170",
      "Mouse gamer Redragon Predator M612",
      "Filtro de linha iCLAMPER Energia 5",
      "Soundbar Samsung HW-B400F",
      "Celular smartphone",
      "Smart TV 4K",
      "Notebook",
      "Console de videogame",
      "Fone de ouvido Bluetooth",
      "Smart speaker Alexa",
      "Tablet",
      "Relógio inteligente smartwatch",
      "Caixa de som Bluetooth",
      "Notebook gamer",
      "Computador gamer",
      "Monitor",
      "Aparelho de streaming para TV",
      "Leitor de livros digitais",
      "Impressora multifuncional",
      "Soundbar",
      "Home theater",
      "Controle acessório videogame",
      "Headset gamer",
      "SSD",
      "HD externo",
      "Placa de vídeo",
      "Roteador Wi-Fi mesh",
      "Câmera de segurança Wi-Fi",
      "Teclado e mouse",
      "Carregador portátil power bank",
      "Carregador rápido",
      "Webcam",
      "Microfone",
      "Filtro de linha",
      "Nobreak",
      "Smart TV"
    ],
    "Eletrodomésticos": [
      "Geladeira",
      "Máquina de lavar",
      "Lava e seca",
      "Fogão",
      "Cooktop",
      "Air fryer",
      "Micro-ondas",
      "Ar-condicionado",
      "Aspirador de pó",
      "Robô aspirador",
      "Cafeteira",
      "Liquidificador",
      "Mixer",
      "Purificador de água",
      "Ventilador",
      "Sanduicheira grill",
      "Lava-louças",
      "Ferro de passar",
      "Vaporizador de roupas"
    ],
    "Casa e Decoração": [
      "Jogo de panelas",
      "Cama box",
      "Colchão",
      "Sofá",
      "Guarda-roupa",
      "Armário de cozinha",
      "Mesa de jantar com cadeiras",
      "Aparelho de jantar",
      "Jogo de talheres",
      "Potes herméticos",
      "Jogo de cama",
      "Jogo de toalhas",
      "Travesseiro",
      "Edredom",
      "Cortina",
      "Persiana",
      "Tapete",
      "Organizador de cozinha",
      "Organizador de guarda-roupa"
    ],
    "Perfumes e Perfumaria": [
      "Perfume feminino importado",
      "Perfume masculino importado",
      "Perfume feminino nacional",
      "Perfume masculino nacional",
      "Kit perfume com hidratante",
      "Kit perfume com desodorante",
      "Perfume árabe feminino",
      "Perfume árabe masculino",
      "Perfume unissex",
      "Body splash feminino",
      "Body splash masculino",
      "Colônia feminina",
      "Colônia masculina",
      "Hidratante corporal perfumado",
      "Óleo corporal perfumado",
      "Desodorante corporal perfumado",
      "Kit sabonete perfumado",
      "Perfume para cabelo",
      "Miniatura de perfume",
      "Kit perfume",
      "Loção pós-barba",
      "Body splash",
      "Desodorante colônia",
      "Perfume árabe",
      "Perfume infantil",
      "Perfume Natura",
      "Natura Kaiak",
      "Natura Essencial",
      "Perfume O Boticário",
      "Malbec O Boticário",
      "Egeo O Boticário",
      "Perfume Eudora",
      "Carolina Herrera 212 VIP",
      "Carolina Herrera Good Girl",
      "Paco Rabanne One Million",
      "Paco Rabanne Invictus",
      "Dior Sauvage",
      "Lancôme La Vie Est Belle",
      "Calvin Klein CK One",
      "Jean Paul Gaultier Le Male",
      "Azzaro Pour Homme",
      "Lattafa"
    ]
  };
  // BUSCAS:fim

  // Termo que só existe no ML: herda a aba do termo a que aponta (não entra em buscas.json).
  const ALIAS = { 'Caixa inteligente assistente virtual': 'Smart speaker Alexa' };

  function congelar(o) {
    Object.values(o).forEach((v) => { if (v && typeof v === 'object') congelar(v); });
    return Object.freeze(o);
  }
  congelar(BUSCAS);
  congelar(ALIAS);

  const ehObjeto = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
  const ehNumero = (v) => typeof v === 'number' && Number.isFinite(v);

  // ---------------------------------------------------------------- funções puras

  /** "Máquina de lavar" → "maquina-de-lavar": sem acento, minúsculas, não alfanumérico vira "-". */
  function slug(termo) {
    return String(termo).normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase()
      .replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
  }

  /** Aba (chave de BUSCAS) do termo, seguindo o ALIAS. null quando o termo não está no mapa. */
  function categoriaDe(termo) {
    if (typeof termo !== 'string') return null;
    const t = termo.normalize('NFC').trim();
    const alvo = Object.prototype.hasOwnProperty.call(ALIAS, t) ? ALIAS[t] : t;
    for (const cat of Object.keys(BUSCAS)) {
      if (BUSCAS[cat].includes(alvo)) return cat;
    }
    return null;
  }

  /** Índice da aspa que fecha o literal JS que abre em s[ini], ou -1. */
  function fimDoLiteral(s, ini) {
    for (let j = ini + 1; j < s.length; j++) {
      const c = s[j];
      if (c === '\\') j++;
      else if (c === '"') return j;
      else if (c === '\n' || c === '\r') return -1;
    }
    return -1;
  }

  /** Literal JS entre aspas duplas → string, via JSON.parse. \' vira ' e \xNN vira \u00NN. */
  function decodificarLiteral(lit) {
    const json = lit.replace(/\\(?:x([0-9a-fA-F]{2})|(')|[\s\S])/g,
      (m, hex, aspa) => (hex ? '\\u00' + hex : aspa ? "'" : m));
    try {
      const v = JSON.parse(json);
      return typeof v === 'string' ? v : null;
    } catch (e) {
      return null;
    }
  }

  /** Texto do primeiro .q("…") da página que traz "polycard", já decodificado. null se não houver. */
  function literalQ(html) {
    if (typeof html !== 'string') return null;
    let i = html.indexOf('.q("');
    while (i !== -1) {
      const ini = i + 3;
      const fim = fimDoLiteral(html, ini);
      if (fim === -1) {   // literal sem fim: tenta o próximo .q("
        i = html.indexOf('.q("', i + 4);
        continue;
      }
      const bruto = html.slice(ini, fim + 1);
      if (bruto.includes('polycard')) {
        const texto = decodificarLiteral(bruto);
        if (texto !== null && texto.includes('"polycard"')) return texto;
      }
      i = html.indexOf('.q("', fim + 1);
    }
    return null;
  }

  /** Índice da chave que fecha o objeto que abre em s[ini], respeitando strings JSON, ou -1. */
  function fimDoObjeto(s, ini) {
    let nivel = 0;
    let emTexto = false;
    for (let j = ini; j < s.length; j++) {
      const c = s[j];
      if (emTexto) {
        if (c === '\\') j++;
        else if (c === '"') emTexto = false;
      } else if (c === '"') emTexto = true;
      else if (c === '{') nivel++;
      else if (c === '}' && --nivel === 0) return j;
    }
    return -1;
  }

  /** Objetos que vêm depois de cada "polycard": no texto, lidos com JSON.parse. Ilegíveis ficam de fora. */
  function polycards(texto) {
    const lista = [];
    const chave = '"polycard"';
    let i = texto.indexOf(chave);
    while (i !== -1) {
      const m = /^\s*:\s*\{/.exec(texto.slice(i + chave.length, i + chave.length + 64));
      let prox = i + chave.length;
      if (m) {
        const ini = i + chave.length + m[0].length - 1;
        const fim = fimDoObjeto(texto, ini);
        if (fim !== -1) {
          try { lista.push(JSON.parse(texto.slice(ini, fim + 1))); } catch (e) { /* card ilegível */ }
          prox = fim + 1;
        }
      }
      i = texto.indexOf(chave, prox);
    }
    return lista;
  }

  /** 2569 → "R$ 2.569"; 124.2 → "R$ 124,20" (centavos só quando o valor não é inteiro). */
  function formatarPreco(v) {
    const centavos = Math.round(v * 100);
    const inteiro = String(Math.floor(centavos / 100)).replace(/\B(?=(\d{3})+(?!\d))/g, '.');
    const resto = centavos % 100;
    return 'R$ ' + inteiro + (resto ? ',' + String(resto).padStart(2, '0') : '');
  }

  /** Primeiro objeto dentro de price com previous:true e value numérico (busca em profundidade). */
  function precoAnterior(o, profundidade = 0) {
    if (!o || typeof o !== 'object' || profundidade > 4) return null;
    if (o.previous === true && ehNumero(o.value)) return o.value;
    for (const v of Object.values(o)) {
      const achado = precoAnterior(v, profundidade + 1);
      if (achado !== null) return achado;
    }
    return null;
  }

  /** Um polycard → {item_id, url, data} no formato do banco, ou null sem MLB ou sem título. */
  function polycardParaItem(pc) {
    if (!ehObjeto(pc)) return null;
    const meta = ehObjeto(pc.metadata) ? pc.metadata : {};
    const id = typeof meta.id === 'string' ? meta.id.trim() : '';
    const mlb = /^MLB(\d{6,})$/.exec(id);
    if (!mlb) return null;   // metadata.url (às vezes um click1… de anúncio) não é usada
    const comp = new Map();
    for (const c of Array.isArray(pc.components) ? pc.components : []) {
      if (ehObjeto(c) && typeof c.type === 'string' && !comp.has(c.type)) comp.set(c.type, c);
    }
    const parte = (tipo) => (comp.has(tipo) && ehObjeto(comp.get(tipo)[tipo]) ? comp.get(tipo)[tipo] : null);

    const titulo = typeof parte('title')?.text === 'string' ? parte('title').text.trim() : '';
    if (!titulo) return null;

    const data = Object.fromEntries(CAMPOS.map((c) => [c, '']));
    data.titulo = titulo;

    const preco = parte('price');
    const atual = preco && ehObjeto(preco.current_price) ? preco.current_price.value : null;
    if (ehNumero(atual) && atual > 0) {
      data.preco = formatarPreco(atual);
      const antes = precoAnterior(preco);
      const pct = antes !== null && antes > atual ? Math.round(100 - (atual * 100) / antes) : 0;
      if (pct > 0) {   // diferença que arredonda para 0% não é desconto ("-0%")
        data.preco_antigo = formatarPreco(antes);
        data.desconto = '-' + pct + '%';
      }
    }

    const alt = parte('review_compacted')?.alt_text;
    if (typeof alt === 'string') {
      const nota = /(\d+(?:[.,]\d+)?)\s+de\s+5\s+estrelas/i.exec(alt);
      if (nota) data.avaliacao = nota[1].replace(',', '.') + ' de 5 estrelas';
      const vendas = /Mais de\s+[\d.]+(?:\s+mil)?\s+produtos?\s+vendidos?/i.exec(alt);
      if (vendas) data.vendas = vendas[0].replace(/\s+/g, ' ');
    }

    for (const tipo of ['shipping_v2', 'shipping']) {
      if (comp.has(tipo) && /gr[aá]tis/i.test(JSON.stringify(comp.get(tipo)))) {
        data.frete = 'Frete grátis';
        break;
      }
    }

    const foto = ehObjeto(pc.pictures) && Array.isArray(pc.pictures.pictures) ? pc.pictures.pictures[0] : null;
    if (ehObjeto(foto) && typeof foto.id === 'string' && /^[A-Za-z0-9_-]+$/.test(foto.id)) {
      data.imagem = `https://http2.mlstatic.com/D_Q_NP_2X_${foto.id}-E.webp`;
    }

    return { item_id: id, url: `https://produto.mercadolivre.com.br/MLB-${mlb[1]}`, data };
  }

  /** Itens prontos para o POST: sem id repetido nem card sem título, no máximo `max`. */
  function extrairItens(html, termo, cat, max = MAX_POR_BUSCA) {
    const texto = literalQ(html);
    if (texto === null) return [];
    const vistos = new Set();
    const itens = [];
    for (const pc of polycards(texto)) {
      if (itens.length >= max) break;
      const it = polycardParaItem(pc);
      if (!it || vistos.has(it.item_id)) continue;
      vistos.add(it.item_id);
      itens.push({ loja: 'ml', item_id: it.item_id, cat, busca: termo, url: it.url, data: it.data });
    }
    return itens;
  }

  // ---------------------------------------------------------------- coleta

  let ultimoEstado = null;
  let execucao = null;   // {parar, acordar} da coleta em andamento

  const log = (...a) => console.log('[ColetaML]', ...a);

  function falhar(estado, msg) {
    estado.erro = msg;
    console.error('[ColetaML] ' + msg);
    return estado;
  }

  function normalizarServidor(s) {
    const v = typeof s === 'string' ? s.trim().replace(/\/+$/, '') : '';
    return RX_SERVIDOR.test(v) ? v : null;
  }

  function lerProgresso(arm, servidor) {
    try {
      const v = JSON.parse(arm.getItem(PREFIXO_PROGRESSO + servidor) || '[]');
      return new Set(Array.isArray(v) ? v.filter((x) => typeof x === 'string') : []);
    } catch (e) {
      return new Set();   // progresso ilegível: coletar de novo não estraga nada (o upsert preserva cat e url)
    }
  }

  function gravarProgresso(arm, servidor, feitos) {
    try {
      arm.setItem(PREFIXO_PROGRESSO + servidor, JSON.stringify([...feitos]));
    } catch (e) {
      console.warn('[ColetaML] não consegui gravar o progresso no localStorage; a coleta continua.');
    }
  }

  /** fetch com prazo; lê o corpo como 'text' ou 'json' (JSON ilegível vira null). */
  async function pedir(f, url, init, ler) {
    const ctl = typeof AbortController === 'function' ? new AbortController() : null;
    const timer = ctl ? setTimeout(() => ctl.abort(), PRAZO_MS) : null;
    try {
      const r = await f(url, ctl ? { ...init, signal: ctl.signal } : init);
      let corpo = null;
      if (ler === 'text') corpo = await r.text();
      else {
        try { corpo = await r.json(); } catch (e) { corpo = null; }
      }
      return { r, corpo };
    } finally {
      if (timer !== null) clearTimeout(timer);
    }
  }

  const nomeErro = (e) => (e && e.name === 'AbortError' ? 'demorou demais' : (e && e.message) || String(e));

  function pausar(ms) {
    return new Promise((resolve) => {
      const t = setTimeout(resolve, ms);
      execucao.acordar = () => { clearTimeout(t); resolve(); };
    });
  }

  /** Opções de coletar() e afiliar(): servidor, enviar, fetch, pausa e armazenamento (só com enviar). */
  function opcoesComuns(o, funcao) {
    if (!ehObjeto(o)) return { erro: `use ColetaML.${funcao}({...}) com um objeto de opções` };
    const servidor = normalizarServidor(o.servidor === undefined ? SERVIDOR_PADRAO : o.servidor);
    if (!servidor) return { erro: 'servidor deve ser http://localhost:<porta> ou http://127.0.0.1:<porta>' };
    if (o.enviar !== undefined && typeof o.enviar !== 'boolean') return { erro: 'enviar deve ser true ou false' };
    const enviar = o.enviar !== false;
    if (o.fetch !== undefined && typeof o.fetch !== 'function') return { erro: 'fetch deve ser uma função' };
    const pausa = o.pausa === undefined ? PAUSA_PADRAO : o.pausa;
    if (!Array.isArray(pausa) || pausa.length !== 2 || !pausa.every((x) => ehNumero(x) && x >= 0) || pausa[0] > pausa[1]) {
      return { erro: 'pausa deve ser [mínimo, máximo] em milissegundos' };
    }
    let arm = null;
    if (enviar) {
      arm = o.armazenamento === undefined ? globalThis.localStorage : o.armazenamento;
      if (!arm || typeof arm.getItem !== 'function' || typeof arm.setItem !== 'function') {
        return { erro: 'sem localStorage para guardar o progresso' };
      }
    }
    const f = o.fetch || ((...a) => globalThis.fetch(...a));
    return { servidor, enviar, pausa, arm, f };
  }

  /** Confere as opções da coleta. Devolve {erro} ou a configuração pronta. */
  function conferirOpcoes(o) {
    const comuns = opcoesComuns(o, 'coletar');
    if (comuns.erro) return comuns;
    const porBusca = o.porBusca === undefined ? MAX_POR_BUSCA : o.porBusca;
    if (!Number.isInteger(porBusca) || porBusca < 1 || porBusca > MAX_POR_BUSCA) {
      return { erro: `porBusca deve ser um inteiro de 1 a ${MAX_POR_BUSCA}` };
    }
    let termos = o.termos === undefined ? Object.values(BUSCAS).flat() : o.termos;
    if (!Array.isArray(termos) || !termos.length || !termos.every((t) => typeof t === 'string')) {
      return { erro: 'termos deve ser uma lista de textos, por exemplo ["Body splash"]' };
    }
    const ordem = o.ordem === undefined ? 'relevancia' : o.ordem;
    if (typeof ordem !== 'string' || !Object.prototype.hasOwnProperty.call(ORDENS_ML, ordem)) {
      return { erro: 'ordem deve ser uma destas: ' + Object.keys(ORDENS_ML).join(', ') };
    }
    termos = [...new Set(termos.map((t) => t.normalize('NFC').trim()))];
    const desconhecidos = termos.filter((t) => categoriaDe(t) === null);
    if (desconhecidos.length) {
      return { erro: 'termos fora de buscas.json (e do ALIAS): ' + JSON.stringify(desconhecidos) };
    }
    return { ...comuns, porBusca, termos, ordem };
  }

  /**
   * Coleta os termos na própria aba do ML e, com enviar:true, grava cada termo no servidor.
   * Devolve o estado: {rodando, servidor, enviar, ordem, feitos, pulados, itens, inserido, atualizado, parado, erro}.
   * Com enviar:false não fala com o servidor nem usa o progresso: só monta os itens em estado.itens.
   */
  async function coletar(opcoes = {}) {
    if (execucao) {
      console.error('[ColetaML] já há uma coleta rodando. Use ColetaML.parar() e espere ela terminar.');
      return ultimoEstado;
    }
    const estado = {
      rodando: false, servidor: null, enviar: null, ordem: null, termoAtual: null, feitos: [], pulados: [], itens: [],
      inserido: 0, atualizado: 0, parado: false, erro: null,
    };
    ultimoEstado = estado;
    const origem = globalThis.location ? globalThis.location.origin : undefined;
    if (origem !== ORIGEM_LISTA) {
      return falhar(estado, `coletar() só roda numa aba de ${ORIGEM_LISTA} (esta aba é ${origem || 'desconhecida'}). ` +
        'Abra a lista do Mercado Livre, cole o arquivo de novo e rode lá. Nada foi feito.');
    }
    const cfg = conferirOpcoes(opcoes);
    if (cfg.erro) return falhar(estado, cfg.erro + '. Nada foi feito.');
    const { servidor, enviar, porBusca, pausa, termos, ordem, arm, f } = cfg;
    Object.assign(estado, { rodando: true, servidor, enviar, ordem });
    execucao = { parar: false, acordar: null };
    const feitosAntes = enviar ? lerProgresso(arm, servidor) : new Set();
    const feitos = new Set(feitosAntes);
    let buscou = false;
    // chave do progresso: o termo puro na relevância (igual ao que já está no localStorage) e <ordem>|<termo> nas outras
    const chaveDe = (termo) => (ordem === 'relevancia' ? termo : ordem + '|' + termo);
    try {
      for (let n = 0; n < termos.length; n++) {
        const termo = termos[n];
        if (execucao.parar) break;
        if (feitosAntes.has(chaveDe(termo))) { estado.pulados.push(termo); continue; }
        if (buscou) {
          await pausar(pausa[0] + Math.random() * (pausa[1] - pausa[0]));
          if (execucao.parar) break;
        }
        buscou = true;
        estado.termoAtual = termo;
        const cat = categoriaDe(termo);

        let pagina;
        try {
          pagina = await pedir(f, '/' + slug(termo) + ORDENS_ML[ordem], { credentials: 'include' }, 'text');
        } catch (e) {
          return falhar(estado, `não consegui abrir a busca "${termo}" no ML (${nomeErro(e)}). Nada foi enviado deste termo.`);
        }
        if (RX_CAPTCHA.test(String(pagina.r.url || ''))) {
          return falhar(estado, `o ML pediu verificação (captcha) na busca "${termo}". Resolva na aba e rode de novo; ` +
            'os termos já enviados ficam no progresso. Nada foi enviado deste termo.');
        }
        if (!pagina.r.ok) {
          return falhar(estado, `o ML respondeu ${pagina.r.status} na busca "${termo}". Nada foi enviado deste termo.`);
        }
        const itens = extrairItens(pagina.corpo, termo, cat, porBusca);
        if (!itens.length) {
          return falhar(estado, `a busca "${termo}" veio sem polycard: pode ser captcha ou mudança na página do ML. ` +
            'A coleta parou e nada foi enviado deste termo.');
        }
        estado.itens.push(...itens);

        let resumo = '';
        if (enviar) {
          let resp;
          try {
            resp = await pedir(f, servidor + '/api/items', {
              method: 'POST', credentials: 'omit', referrerPolicy: 'no-referrer',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ items: itens }),
            }, 'json');
          } catch (e) {
            return falhar(estado, `não consegui falar com o servidor em ${servidor} (${nomeErro(e)}). Ele está no ar?`);
          }
          const c = resp.corpo;
          if (!resp.r.ok) {
            const motivo = ehObjeto(c) && typeof c.error === 'string' ? ': ' + c.error : '';
            return falhar(estado, `o servidor recusou "${termo}" com ${resp.r.status}${motivo}. A coleta parou.`);
          }
          if (!ehObjeto(c) || !ehNumero(c.inserido) || !ehNumero(c.atualizado)) {
            return falhar(estado, `resposta inesperada do servidor em "${termo}". A coleta parou.`);
          }
          estado.inserido += c.inserido;
          estado.atualizado += c.atualizado;
          feitos.add(chaveDe(termo));
          gravarProgresso(arm, servidor, feitos);
          resumo = ` (inserido ${c.inserido}, atualizado ${c.atualizado})`;
        }
        estado.feitos.push(termo);
        log(`${n + 1}/${termos.length} "${termo}"${ordem === 'relevancia' ? '' : ' (' + ordem + ')'} → ${cat}: ${itens.length} itens${resumo}`);
      }
      if (execucao.parar) {
        estado.parado = true;
        log(`parado. ${estado.feitos.length} termos feitos nesta rodada; rode coletar() de novo para continuar.`);
      } else {
        log(`fim: ${estado.feitos.length} termos coletados, ${estado.pulados.length} pulados (já feitos)` +
          (enviar ? `; inserido ${estado.inserido}, atualizado ${estado.atualizado}.`
            : '. Nada foi enviado: os itens estão em ColetaML.estado.itens.'));
      }
      return estado;
    } finally {
      estado.rodando = false;
      estado.termoAtual = null;
      execucao = null;
    }
  }

  // ---------------------------------------------------------------- links de afiliado (linkbuilder)

  const ORIGEM_AFILIADOS = 'https://www.mercadolivre.com.br';
  const CAMINHO_LINKBUILDER = '/afiliados/linkbuilder';
  const ETIQUETA = 'achadosmenicas';  // etiqueta de afiliado do dono no ML
  const PREFIXO_INELEGIVEIS = '__afiliarML:';
  const MAX_LOTE = 25;              // 50 falha no linkbuilder
  const LOTE_REPESCAGEM = 10;       // segunda tentativa de quem ficou sem resposta
  const MAX_TENTATIVAS = 2;
  const MAX_CONFERENCIAS = 3;
  const PRAZO_LINKBUILDER_MS = 30000;
  const RX_MELI_LA = /^https:\/\/meli\.la\/[A-Za-z0-9]+$/;
  // só error_code de elegibilidade fica guardado como inelegível; os outros são tentados de novo na próxima execução
  const RX_ERRO_ELEGIBILIDADE = /ELIGIB|ELEGIB/i;
  const MOTIVO_NAO_MELI_LA = "link não é meli.la: confira 'Links curtos'";

  /** Só https://meli.la/<código>: é o único link que o PATCH pode levar (regra do dono). */
  function ehLinkMeliLa(url) {
    return typeof url === 'string' && RX_MELI_LA.test(url);
  }

  /** "https://produto.mercadolivre.com.br/MLB-4100000001-tv-_JM" → "MLB4100000001"; null sem código. */
  function idMLB(url) {
    if (typeof url !== 'string') return null;
    const m = /MLB-?(\d{6,})/.exec(url);
    return m ? 'MLB' + m[1] : null;
  }

  /**
   * Casa a resposta do createLink ({urls:[{origin_url, short_url, error_code, message}]}) com os itens
   * ({id, url}) pelo código MLB, nunca pela ordem (a resposta pode vir embaralhada e com a url canônica).
   * trocar: link meli.la único para o MLB.
   * inelegiveis: error_code ({codigo, motivo}) ou link que não é meli.la ({naoMeliLa: true}, sintoma de
   *   "Links curtos" desligado: afiliar() para e não grava nada do lote).
   * semResposta: MLB ausente da resposta ou com dois links diferentes.
   */
  function mapearLinks(resp, itens) {
    const porMLB = new Map();
    for (const e of ehObjeto(resp) && Array.isArray(resp.urls) ? resp.urls : []) {
      const mlb = ehObjeto(e) ? idMLB(e.origin_url) : null;
      if (!mlb) continue;
      if (!porMLB.has(mlb)) porMLB.set(mlb, []);
      porMLB.get(mlb).push(e);
    }
    const trocar = [];
    const inelegiveis = [];
    const semResposta = [];
    for (const it of Array.isArray(itens) ? itens : []) {
      const mlb = idMLB(it.url);
      const respostas = (mlb && porMLB.get(mlb)) || [];
      const links = [...new Set(respostas.filter((e) => !e.error_code && ehLinkMeliLa(e.short_url)).map((e) => e.short_url))];
      const erro = respostas.find((x) => x.error_code);
      if (!respostas.length || links.length > 1) {
        semResposta.push({ id: it.id, mlb, url: it.url });
      } else if (links.length === 1) {
        trocar.push({ id: it.id, mlb, url: links[0], origem: it.url });
      } else if (erro) {
        const codigo = String(erro.error_code).slice(0, 100);
        const motivo = codigo + (typeof erro.message === 'string' && erro.message ? ': ' + erro.message : '');
        inelegiveis.push({ id: it.id, mlb, motivo: motivo.slice(0, 200), codigo });
      } else {
        inelegiveis.push({ id: it.id, mlb, motivo: MOTIVO_NAO_MELI_LA, naoMeliLa: true });
      }
    }
    return { trocar, inelegiveis, semResposta };
  }

  /** Itens do ML que dividem a mesma url: [{url, ids}]. */
  function urlsRepetidas(itens) {
    const porUrl = new Map();
    for (const it of Array.isArray(itens) ? itens : []) {
      if (!ehObjeto(it) || typeof it.url !== 'string' || (it.loja !== undefined && it.loja !== 'ml')) continue;
      if (!porUrl.has(it.url)) porUrl.set(it.url, []);
      porUrl.get(it.url).push(it.id);
    }
    return [...porUrl].filter(([, ids]) => ids.length > 1).map(([url, ids]) => ({ url, ids }));
  }

  /** Valor de uma chave "tag" no corpo do pedido do createLink (texto JSON ou objeto), ou undefined. */
  function etiquetaDoPedido(corpo) {
    let obj = corpo;
    if (typeof corpo === 'string') {
      try { obj = JSON.parse(corpo); } catch (e) { return undefined; }
    }
    const procurar = (o, prof) => {
      if (!o || typeof o !== 'object' || prof > 3) return undefined;
      for (const [k, v] of Object.entries(o)) {
        if (/^tag$/i.test(k) && typeof v === 'string') return v;
      }
      for (const v of Object.values(o)) {
        const achado = procurar(v, prof + 1);
        if (achado !== undefined) return achado;
      }
      return undefined;
    };
    return procurar(obj, 0);
  }

  // Gancho no fetch e no XHR da página: só lê o pedido e a resposta de URLs com createLink e não muda nada nelas.
  let gancho = null;

  function instalarGancho() {
    if (gancho) return gancho;
    const g = globalThis;
    const esperas = [];
    const entregar = (pedido, dados) => { const e = esperas.shift(); if (e) e({ pedido, dados }); };
    const ehCreateLink = (u) => {
      try { return /createLink/.test(typeof u === 'string' ? u : String(u && u.url !== undefined ? u.url : u)); } catch (e) { return false; }
    };
    const fetchOriginal = g.fetch;
    let fetchNosso = null;
    if (typeof fetchOriginal === 'function') {
      fetchNosso = function (...a) {
        const p = fetchOriginal.apply(g, a);
        if (ehCreateLink(a[0])) {
          const pedido = a[1] && typeof a[1].body === 'string' ? a[1].body : undefined;
          p.then((r) => r.clone().json()).then((d) => entregar(pedido, d), () => entregar(pedido, null));
        }
        return p;
      };
      g.fetch = fetchNosso;
    }
    const proto = g.XMLHttpRequest && g.XMLHttpRequest.prototype;
    const abrirOriginal = proto ? proto.open : null;
    const enviarOriginal = proto ? proto.send : null;
    const pedidosXHR = new WeakMap();
    let abrirNosso = null;
    let enviarNosso = null;
    if (typeof abrirOriginal === 'function') {
      abrirNosso = function (metodo, url, ...resto) {
        if (ehCreateLink(url)) {
          pedidosXHR.set(this, { corpo: undefined });
          this.addEventListener('loadend', () => {
            let dados = null;
            try { dados = this.responseType === 'json' ? this.response : JSON.parse(this.responseText); } catch (e) { dados = null; }
            entregar(pedidosXHR.get(this).corpo, dados);
          });
        }
        return abrirOriginal.call(this, metodo, url, ...resto);
      };
      proto.open = abrirNosso;
      if (typeof enviarOriginal === 'function') {
        enviarNosso = function (corpo, ...resto) {
          const reg = pedidosXHR.get(this);
          if (reg && typeof corpo === 'string') reg.corpo = corpo;
          return enviarOriginal.call(this, corpo, ...resto);
        };
        proto.send = enviarNosso;
      }
    }
    gancho = {
      /** Promessa do próximo {pedido, dados} do createLink; rejeita depois de `ms`. */
      esperar(ms) {
        return new Promise((resolve, reject) => {
          const receber = (r) => { clearTimeout(t); resolve(r); };
          const t = setTimeout(() => {
            const i = esperas.indexOf(receber);
            if (i !== -1) esperas.splice(i, 1);
            reject(new Error('o linkbuilder não respondeu ao createLink'));
          }, ms);
          esperas.push(receber);
        });
      },
      desinstalar() {
        if (fetchNosso && g.fetch === fetchNosso) g.fetch = fetchOriginal;
        if (abrirNosso && proto.open === abrirNosso) proto.open = abrirOriginal;
        if (enviarNosso && proto.send === enviarNosso) proto.send = enviarOriginal;
        gancho = null;
      },
    };
    return gancho;
  }

  const dormir = (ms) => new Promise((r) => setTimeout(r, ms));
  let avisos = new Set();   // avisos do linkbuilder já dados nesta execução de afiliar()

  function avisarUmaVez(chave, msg) {
    if (avisos.has(chave)) return;
    avisos.add(chave);
    console.warn('[ColetaML] ' + msg);
  }

  /**
   * Operação da interface do linkbuilder: confere "Links curtos", preenche a primeira caixa de texto com as
   * urls (uma por linha), clica em "Gerar" e devolve a resposta do createLink capturada pelo gancho.
   * Recusa se o pedido mostrar uma etiqueta diferente de achadosmenicas.
   */
  async function gerarNaPagina(urls) {
    const doc = globalThis.document;
    if (!doc) throw new Error('esta aba não tem página');
    const g = instalarGancho();
    const rotulo = [...doc.querySelectorAll('label')].find((l) => /Links curtos/i.test(l.textContent || ''));
    if (!rotulo) throw new Error(`não achei a opção "Links curtos" (abra ${ORIGEM_AFILIADOS}${CAMINHO_LINKBUILDER})`);
    const marcador = rotulo.control || (typeof rotulo.querySelector === 'function' ? rotulo.querySelector('input') : null);
    if (!marcador || typeof marcador.checked !== 'boolean') {
      // não dá para saber se está ligado: não clica (poderia desligar). Se estiver desligado, o lote para.
      avisarUmaVez('rotulo', 'não consegui ver se "Links curtos" está ligado: confira à mão na página.');
    } else if (!marcador.checked) {
      rotulo.click();
      await dormir(300);
      if (!marcador.checked) throw new Error('não consegui ligar "Links curtos": ligue à mão e rode de novo');
    }
    const caixa = doc.querySelectorAll('textarea')[0];
    if (!caixa) throw new Error('não achei a caixa de texto do linkbuilder');
    // setter nativo + evento input: a página (React) só enxerga o valor assim
    const definir = Object.getOwnPropertyDescriptor(globalThis.HTMLTextAreaElement.prototype, 'value').set;
    definir.call(caixa, urls.join('\n'));
    caixa.dispatchEvent(new globalThis.Event('input', { bubbles: true }));
    let botao = null;
    for (let i = 0; i < 50; i++) {
      botao = [...doc.querySelectorAll('button')].find((b) => /^\s*Gerar\b/i.test(b.textContent || ''));
      if (botao && !botao.disabled) break;
      await dormir(100);
    }
    if (!botao || botao.disabled) throw new Error('não achei o botão "Gerar" habilitado no linkbuilder');
    const resposta = g.esperar(PRAZO_LINKBUILDER_MS);
    botao.click();
    const { pedido, dados } = await resposta;
    const etiqueta = etiquetaDoPedido(pedido);
    if (etiqueta === undefined) {
      avisarUmaVez('etiqueta', `não consegui ler a etiqueta no pedido do createLink: confira à mão que é ${ETIQUETA}.`);
    } else if (etiqueta !== ETIQUETA) {
      throw new Error(`o linkbuilder está gerando com a etiqueta "${etiqueta.slice(0, 50)}", não ${ETIQUETA}. ` +
        'Troque a etiqueta na página; nada deste lote foi gravado');
    }
    return dados;
  }

  function lerInelegiveis(arm, servidor) {
    try {
      const v = JSON.parse(arm.getItem(PREFIXO_INELEGIVEIS + servidor) || '[]');
      return new Map((Array.isArray(v) ? v : []).filter((e) => ehObjeto(e) && Number.isInteger(e.id)).map((e) => [e.id, e]));
    } catch (e) {
      return new Map();
    }
  }

  /** Guarda só o que é para o dono excluir: url sem MLB e error_code de elegibilidade. */
  const guardavel = (e) => !e.naoMeliLa && (e.codigo === undefined || RX_ERRO_ELEGIBILIDADE.test(e.codigo));

  function gravarInelegiveis(arm, servidor, mapa) {
    try {
      arm.setItem(PREFIXO_INELEGIVEIS + servidor, JSON.stringify([...mapa.values()].filter(guardavel)));
    } catch (e) {
      console.warn('[ColetaML] não consegui guardar os inelegíveis no localStorage; afiliar() continua.');
    }
  }

  // chamadas ao servidor local: sem credenciais e sem Referer da página do ML
  const SEM_RASTRO = { credentials: 'omit', referrerPolicy: 'no-referrer' };

  /** GET no servidor que devolve uma lista; {lista} ou {erro}. */
  async function lerLista(f, url, servidor) {
    let resp;
    try {
      resp = await pedir(f, url, { ...SEM_RASTRO }, 'json');
    } catch (e) {
      return { erro: `não consegui falar com o servidor em ${servidor} (${nomeErro(e)}). Ele está no ar?` };
    }
    if (!resp.r.ok) return { erro: `o servidor respondeu ${resp.r.status} em ${url}. Parei.` };
    if (!Array.isArray(resp.corpo)) return { erro: `resposta inesperada do servidor em ${url}. Parei.` };
    return { lista: resp.corpo.filter((x) => ehObjeto(x) && Number.isInteger(x.id) && x.id > 0 && typeof x.url === 'string') };
  }

  /** PATCH só com {url: meli.la}. {ok, existe} ou {erro}; url comum nunca sai daqui. */
  async function gravarLink(f, servidor, t) {
    if (!ehLinkMeliLa(t.url) || !Number.isInteger(t.id) || t.id < 1) {
      return { erro: `link ou id inválido para o item ${t.id}; nada foi enviado. Parei.` };
    }
    let resp;
    try {
      resp = await pedir(f, `${servidor}/api/items/${t.id}`, {
        method: 'PATCH', ...SEM_RASTRO,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: t.url }),
      }, 'json');
    } catch (e) {
      return { erro: `não consegui falar com o servidor em ${servidor} (${nomeErro(e)}). Ele está no ar?` };
    }
    if (!resp.r.ok) {
      const motivo = ehObjeto(resp.corpo) && typeof resp.corpo.error === 'string' ? ': ' + resp.corpo.error : '';
      return { erro: `o servidor recusou o link do item ${t.id} com ${resp.r.status}${motivo}. Parei.` };
    }
    return { ok: true, existe: ehObjeto(resp.corpo) };   // null: o item foi excluído no meio do caminho
  }

  function partir(lista, n) {
    const grupos = [];
    for (let i = 0; i < lista.length; i += n) grupos.push(lista.slice(i, i + n));
    return grupos;
  }

  function mensagemNaoMeliLa(ruins, onde) {
    const ex = ruins.slice(0, 3).map((e) => e.mlb).join(', ');
    return `o linkbuilder devolveu link que não é meli.la para ${ruins.length} item(ns)${onde} (${ex}). ` +
      'Confira se "Links curtos" está ligado e rode afiliar() de novo. Nada deste lote foi gravado.';
  }

  /** Confere as opções de afiliar(). Devolve {erro} ou a configuração pronta. */
  function conferirOpcoesAfiliar(o) {
    const comuns = opcoesComuns(o, 'afiliar');
    if (comuns.erro) return comuns;
    const lote = o.lote === undefined ? MAX_LOTE : o.lote;
    if (!Number.isInteger(lote) || lote < 1 || lote > MAX_LOTE) return { erro: `lote deve ser um inteiro de 1 a ${MAX_LOTE}` };
    if (o.gerar !== undefined && typeof o.gerar !== 'function') return { erro: 'gerar deve ser uma função' };
    let itens = null;
    if (comuns.enviar) {
      if (o.itens !== undefined) return { erro: 'itens só vale com enviar:false; com enviar:true a lista vem do servidor' };
    } else {
      if (!Array.isArray(o.itens) || !o.itens.length) {
        return { erro: 'com enviar:false, passe itens: ["https://produto.mercadolivre.com.br/MLB-…", …] ou [{id, url}]' };
      }
      itens = o.itens.map((x, i) => (typeof x === 'string' ? { id: i + 1, url: x } : ehObjeto(x) ? { id: x.id === undefined ? i + 1 : x.id, url: x.url } : null));
      if (!itens.every((x) => x && Number.isInteger(x.id) && x.id > 0 && typeof x.url === 'string')) {
        return { erro: 'itens deve ter urls (texto) ou objetos {id inteiro, url}' };
      }
      if (new Set(itens.map((x) => x.id)).size !== itens.length) return { erro: 'itens tem id repetido' };
    }
    return { ...comuns, lote, itens, gerar: o.gerar || gerarNaPagina };
  }

  /**
   * Troca a url dos itens do ML sem afiliado pelo link meli.la do linkbuilder. Roda na aba
   * https://www.mercadolivre.com.br/afiliados/linkbuilder.
   *   1. Repete enquanto houver pendentes: GET /api/ml-sem-afiliado, gera em lotes, mapeia pelo MLB e faz PATCH.
   *      Quem fica sem resposta tenta de novo em lote de 10; inelegíveis vão para a lista (nunca são apagados).
   *      Link que não é meli.la para tudo: é sinal de "Links curtos" desligado.
   *   2. Conferência: gera de novo os links dos itens tocados (a 1ª criação em lote pode trocar os pares) e
   *      corrige o que mudou, até 0 correções. Um meli.la no banco que não foi gravado nesta execução não é
   *      trocado: a divergência vai para o console.
   *   3. Aponta url repetida entre itens do ML e imprime os inelegíveis para o dono excluir pelo site.
   * Com enviar:false não fala com o servidor: gera os links de `itens` e devolve o que trocaria.
   */
  async function afiliar(opcoes = {}) {
    if (execucao) {
      console.error('[ColetaML] já há uma coleta rodando. Use ColetaML.parar() e espere ela terminar.');
      return ultimoEstado;
    }
    const estado = {
      rodando: false, servidor: null, enviar: null, trocados: [], inelegiveis: [], semResposta: [],
      naoMeliLa: [], correcoes: 0, divergencias: [], repetidas: [], parado: false, erro: null,
    };
    ultimoEstado = estado;
    const loc = globalThis.location;
    const origem = loc ? loc.origin : undefined;
    const caminho = loc && typeof loc.pathname === 'string' ? loc.pathname : '';
    if (origem !== ORIGEM_AFILIADOS || !caminho.startsWith(CAMINHO_LINKBUILDER)) {
      return falhar(estado, `afiliar() só roda numa aba de ${ORIGEM_AFILIADOS}${CAMINHO_LINKBUILDER} ` +
        `(esta aba é ${origem || 'desconhecida'}${caminho.slice(0, 80)}). ` +
        'Abra o linkbuilder, cole o arquivo de novo e rode lá. Nada foi feito.');
    }
    const cfg = conferirOpcoesAfiliar(opcoes);
    if (cfg.erro) return falhar(estado, cfg.erro + '. Nada foi feito.');
    const { servidor, enviar, pausa, arm, f, lote, itens, gerar } = cfg;
    Object.assign(estado, { rodando: true, servidor, enviar });
    execucao = { parar: false, acordar: null };
    avisos = new Set();
    log(`confira no linkbuilder que a etiqueta é ${ETIQUETA}; o script recusa se o pedido mostrar outra.`);
    const inelegiveis = enviar ? lerInelegiveis(arm, servidor) : new Map();
    let conhecidos = 0;
    let primeira = true;
    const tentativas = new Map();
    const tocados = new Map();       // id → {id, mlb, url, origem}: url é o meli.la gravado nesta execução
    const semResposta = new Map();
    let gerou = false;
    let terminou = false;

    /**
     * Um lote no linkbuilder; {m} ou {erro}. Lote sem nenhum meli.la e com link de outro tipo é sinal de
     * "Links curtos" desligado: para sem gravar nada. Em lote misto, quem veio sem meli.la fica sem resposta
     * (tenta de novo, não é guardado nem vai para "Exclua pelo site") e o resto segue. Na repescagem o lote
     * só tem quem já falhou, então ele nunca para por isso.
     */
    const gerarLote = async (lista, onde, repescagem = false) => {
      if (gerou) {
        await pausar(pausa[0] + Math.random() * (pausa[1] - pausa[0]));
        if (execucao.parar) return { parado: true };
      }
      gerou = true;
      let resp;
      try {
        resp = await gerar(lista.map((i) => i.url));
      } catch (e) {
        return { erro: `o linkbuilder falhou${onde} (${nomeErro(e)}). Os links já gravados ficam; rode afiliar() de novo.` };
      }
      const m = mapearLinks(resp, lista);
      const ruins = m.inelegiveis.filter((e) => e.naoMeliLa);
      if (!ruins.length) return { m };
      for (const e of ruins) if (!estado.naoMeliLa.some((x) => x.id === e.id)) estado.naoMeliLa.push(e);
      if (!m.trocar.length && !repescagem) return { erro: mensagemNaoMeliLa(ruins, onde) };
      const porId = new Map(lista.map((i) => [i.id, i]));
      m.inelegiveis = m.inelegiveis.filter((e) => !e.naoMeliLa);
      m.semResposta.push(...ruins.map((e) => ({ id: e.id, mlb: e.mlb, url: porId.get(e.id).url, motivo: e.motivo })));
      console.warn(`[ColetaML] ${ruins.length} item(ns) vieram sem meli.la${onde} (${ruins.slice(0, 3).map((e) => e.mlb).join(', ')}); ` +
        'ficam sem resposta e são tentados de novo.');
      return { m };
    };

    try {
      // 1. pendentes, em lotes, até ninguém mais ter tentativa sobrando
      while (!execucao.parar) {
        let pend;
        if (enviar) {
          const r = await lerLista(f, `${servidor}/api/ml-sem-afiliado`, servidor);
          if (r.erro) return falhar(estado, r.erro);
          pend = r.lista;
          if (primeira) {
            // inelegível guardado que sumiu dos pendentes já foi excluído pelo dono (ou ganhou link)
            const ids = new Set(pend.map((i) => i.id));
            for (const id of [...inelegiveis.keys()]) if (!ids.has(id)) inelegiveis.delete(id);
            conhecidos = inelegiveis.size;
          }
        } else {
          pend = itens.filter((i) => !tocados.has(i.id));
        }
        primeira = false;
        pend = pend.filter((i) => !inelegiveis.has(i.id) && (tentativas.get(i.id) || 0) < MAX_TENTATIVAS);
        for (const it of pend.filter((i) => !idMLB(i.url))) {
          inelegiveis.set(it.id, { id: it.id, mlb: null, motivo: 'url sem código MLB' });
        }
        pend = pend.filter((i) => idMLB(i.url));
        if (!pend.length) break;
        const novos = pend.filter((i) => !tentativas.has(i.id));
        const repescagem = pend.filter((i) => tentativas.has(i.id));
        const grupos = [...partir(novos, lote).map((g) => [g, false]),
          ...partir(repescagem, Math.min(lote, LOTE_REPESCAGEM)).map((g) => [g, true])];
        for (const [grupo, ehRepescagem] of grupos) {
          if (execucao.parar) break;
          const g = await gerarLote(grupo, '', ehRepescagem);
          if (g.parado) break;
          if (g.erro) return falhar(estado, g.erro);
          const { m } = g;
          grupo.forEach((i) => tentativas.set(i.id, (tentativas.get(i.id) || 0) + 1));
          for (const t of m.trocar) {
            if (enviar) {
              const r = await gravarLink(f, servidor, t);
              if (r.erro) return falhar(estado, r.erro);
              if (!r.existe) continue;
            }
            tocados.set(t.id, t);
            semResposta.delete(t.id);
          }
          for (const e of m.inelegiveis) { inelegiveis.set(e.id, e); semResposta.delete(e.id); }
          for (const s of m.semResposta) semResposta.set(s.id, s);
          log(`lote de ${grupo.length}: ${m.trocar.length} links meli.la, ${m.inelegiveis.length} inelegíveis, ` +
            `${m.semResposta.length} sem resposta`);
        }
        if (enviar) gravarInelegiveis(arm, servidor, inelegiveis);
      }

      // 2. conferência: gera de novo os links dos tocados e compara com o banco (ou com a memória, sem enviar)
      let ultimaLista = null;
      if (tocados.size && !execucao.parar) {
        let zerou = false;
        for (let volta = 1; volta <= MAX_CONFERENCIAS && !execucao.parar; volta++) {
          let banco = null;
          if (enviar) {
            const r = await lerLista(f, `${servidor}/api/items`, servidor);
            if (r.erro) return falhar(estado, r.erro);
            ultimaLista = r.lista;
            banco = new Map(r.lista.map((i) => [i.id, i]));
          }
          let correcoes = 0;
          const lista = [...tocados.values()].filter((t) => !banco || banco.has(t.id));   // sem os excluídos
          for (const grupo of partir(lista, lote)) {
            if (execucao.parar) break;
            const g = await gerarLote(grupo.map((t) => ({ id: t.id, url: t.origem })), ' na conferência');
            if (g.parado) break;
            if (g.erro) return falhar(estado, g.erro);
            for (const e of [...g.m.inelegiveis, ...g.m.semResposta]) {
              log(`conferência: item ${e.id} (${e.mlb}) ${e.motivo ? 'veio com ' + e.motivo : 'ficou sem resposta'}; nada mudou.`);
            }
            for (const novo of g.m.trocar) {
              const t = tocados.get(novo.id);
              const atual = banco ? banco.get(novo.id).url : t.url;
              if (atual === novo.url) continue;
              // só regrava se o banco não tem meli.la ou tem o que esta execução gravou (provado errado agora)
              if (ehLinkMeliLa(atual) && atual !== t.url) {
                estado.divergencias.push({ id: t.id, mlb: t.mlb, banco: atual, gerado: novo.url });
                console.warn(`[ColetaML] divergência no item ${t.id} (${t.mlb}): o banco tem ${atual} e o linkbuilder ` +
                  `deu ${novo.url}. Não mexi; confira à mão.`);
                continue;
              }
              if (banco) {
                const r = await gravarLink(f, servidor, { ...t, url: novo.url });
                if (r.erro) return falhar(estado, r.erro);
                if (!r.existe) { tocados.delete(t.id); continue; }
              }
              t.url = novo.url;
              correcoes++;
            }
          }
          estado.correcoes += correcoes;
          if (execucao.parar) break;
          log(`conferência ${volta}: ${correcoes} correções em ${lista.length} itens.`);
          if (!correcoes) { zerou = true; break; }
          ultimaLista = null;
        }
        if (!zerou && !execucao.parar) {
          console.warn(`[ColetaML] a conferência não chegou a 0 correções em ${MAX_CONFERENCIAS} voltas. Rode afiliar() de novo.`);
        }
      }

      // 3. url repetida entre itens do ML
      if (!execucao.parar) {
        if (enviar) {
          if (!ultimaLista) {
            const r = await lerLista(f, `${servidor}/api/items`, servidor);
            if (r.erro) return falhar(estado, r.erro);
            ultimaLista = r.lista;
          }
          estado.repetidas = urlsRepetidas(ultimaLista.filter((i) => i.loja === 'ml'));
        } else {
          estado.repetidas = urlsRepetidas([...tocados.values()]);
        }
        for (const rep of estado.repetidas) {
          console.warn(`[ColetaML] url repetida em ${rep.ids.length} itens do ML (ids ${rep.ids.join(', ')}): ${rep.url}`);
        }
      }
      terminou = true;
      return estado;
    } finally {
      estado.trocados = [...tocados.values()];
      estado.inelegiveis = [...inelegiveis.values()];
      estado.semResposta = [...semResposta.values()].filter((s) => !tocados.has(s.id) && !inelegiveis.has(s.id));
      estado.parado = execucao.parar;
      estado.rodando = false;
      execucao = null;
      if (gancho) gancho.desinstalar();
      const excluir = estado.inelegiveis.filter(guardavel);
      const outros = estado.inelegiveis.filter((e) => !guardavel(e));
      if (excluir.length) {
        log(`${excluir.length} inelegíveis (${conhecidos} de execuções anteriores). Exclua pelo site:`);
        for (const e of excluir) log(`  id ${e.id}  ${e.mlb || '-'}  ${e.motivo}`);
      }
      if (outros.length) {
        log(`${outros.length} itens com erro do linkbuilder (tento de novo na próxima execução):`);
        for (const e of outros) log(`  id ${e.id}  ${e.mlb || '-'}  ${e.motivo}`);
      }
      if (terminou) {
        const acao = enviar ? 'gravados' : 'gerados (nada foi enviado ao servidor)';
        log(`${estado.parado ? 'parado' : 'fim'}: ${estado.trocados.length} links meli.la ${acao}, ` +
          `${estado.semResposta.length} sem resposta, ${estado.correcoes} correções, ` +
          `${estado.divergencias.length} divergências, ${estado.repetidas.length} urls repetidas` +
          (estado.naoMeliLa.length ? `, ${estado.naoMeliLa.length} respostas sem meli.la (confira 'Links curtos').` : '.'));
      }
    }
  }

  /** Interrompe a coleta ou o afiliar() em andamento depois do termo ou lote atual (a pausa é cortada). */
  function parar() {
    if (!execucao) { log('nenhuma coleta rodando.'); return; }
    execucao.parar = true;
    if (execucao.acordar) execucao.acordar();
    log('vou parar depois do termo ou lote atual.');
  }

  /** Esquece o progresso e os inelegíveis guardados de um servidor. */
  function zerar(servidor = SERVIDOR_PADRAO, armazenamento = globalThis.localStorage) {
    const s = normalizarServidor(servidor);
    if (!s) { console.error('[ColetaML] servidor deve ser http://localhost:<porta>'); return false; }
    armazenamento.removeItem(PREFIXO_PROGRESSO + s);
    armazenamento.removeItem(PREFIXO_INELEGIVEIS + s);
    log(`progresso e inelegíveis de ${s} apagados.`);
    return true;
  }

  globalThis.ColetaML = Object.freeze({
    BUSCAS, ALIAS, CAMPOS,
    coletar, afiliar, parar, zerar,
    get estado() { return ultimoEstado; },
    slug, categoriaDe, literalQ, extrairItens, polycardParaItem, formatarPreco,
    idMLB, mapearLinks, urlsRepetidas, ehLinkMeliLa, gerarNaPagina,
    _interno: Object.freeze({ gravarLink }),   // só para os testes
  });
})();
