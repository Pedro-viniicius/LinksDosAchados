// Roda uma página testes/*.test.html no Chrome headless em tempo real e imprime a saída (#saida).
// Uso (com o servidor no ar):  node testes/rodar.mjs copiar-imagem [segundos]
// PORTA no ambiente troca a porta do servidor (padrão 8765), ex.: PORTA=8766 node testes/rodar.mjs copiar-imagem
// Sai com código 0 só se a saída trouxer a linha de resultado "OK". Sem dependência (node 22+).
// Por quê: com --virtual-time-budget o createImageBitmap/fetch de foto real não termina antes do dump.
import { spawn } from 'node:child_process';
import { mkdtempSync, rmSync, readFileSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const nome = process.argv[2];
if (!nome) { console.error('uso: node testes/rodar.mjs <nome> [segundos]'); process.exit(2); }
const maxSeg = +(process.argv[3] || 90);
const portaServidor = process.env.PORTA || '8765';
if (!/^\d{1,5}$/.test(portaServidor)) { console.error('PORTA inválida: ' + portaServidor); process.exit(2); }
const url = `http://localhost:${portaServidor}/testes/${nome}.test.html`;
const perfil = mkdtempSync(join(tmpdir(), 'qa-chrome-'));
const chrome = spawn('google-chrome', ['--headless=new', '--disable-gpu', '--remote-debugging-port=0', `--user-data-dir=${perfil}`, 'about:blank'], { stdio: 'ignore' });
const espera = ms => new Promise(r => setTimeout(r, ms));
// Fecha o Chrome e apaga o perfil uma vez só, no fim normal ou em Ctrl+C/kill (sem deixar Chrome órfão).
let limpo = false;
async function limpar() {
  if (limpo) return;
  limpo = true;
  chrome.kill(); await espera(300); rmSync(perfil, { recursive: true, force: true });
}
for (const [sinal, cod] of [['SIGINT', 130], ['SIGTERM', 143]]) {
  process.on(sinal, () => { limpar().finally(() => process.exit(cod)); });
}
let codigo = 1;
try {
  let porta;
  for (let i = 0; i < 100 && !porta; i++) {
    await espera(100);
    const f = join(perfil, 'DevToolsActivePort');
    if (existsSync(f)) porta = readFileSync(f, 'utf8').split('\n')[0];
  }
  if (!porta) throw new Error('Chrome não abriu a porta de depuração');
  let alvo;
  for (let i = 0; i < 50 && !alvo; i++) {
    await espera(100);
    try { alvo = (await (await fetch(`http://127.0.0.1:${porta}/json/list`)).json()).find(t => t.type === 'page'); } catch { /* tenta de novo */ }
  }
  const ws = new WebSocket(alvo.webSocketDebuggerUrl);
  await new Promise(r => { ws.onopen = r; });
  let id = 0; const pend = {};
  ws.onmessage = m => { const d = JSON.parse(m.data); if (pend[d.id]) { pend[d.id](d); delete pend[d.id]; } };
  const cmd = (method, params = {}) => new Promise(r => { const i = ++id; pend[i] = r; ws.send(JSON.stringify({ id: i, method, params })); });
  await cmd('Page.navigate', { url });
  let txt = '';
  for (let i = 0; i < maxSeg * 2; i++) {
    await espera(500);
    txt = (await cmd('Runtime.evaluate', { expression: "(document.getElementById('saida')||{}).textContent||''", returnByValue: true })).result?.result?.value || '';
    if (/RESULTADO: (OK|FALHOU)/.test(txt)) break;
  }
  console.log(txt || `(sem saída: o servidor está no ar em :${portaServidor}?)`);
  codigo = /RESULTADO: OK/.test(txt) ? 0 : 1;
  ws.close();
} finally {
  await limpar();
}
process.exit(codigo);
