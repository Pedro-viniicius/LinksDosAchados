---
name: coletar-ml-testes
description: Armadilhas ao testar o coletar_ml.js com node:test e node:vm (realms, timers pendurados, mutantes, adaptador node:http) e o que não dá para provar sem o ML real
metadata:
  type: project
---

Vistas em 2026-11-03, na etapa 4 do plano eletronicos-e-coleta-ml:

- Objetos criados dentro do contexto `vm` têm outros protótipos: `assert.deepStrictEqual` falha contra literais do teste. Compare com `JSON.parse(JSON.stringify(v))`.
- O script é uma IIFE que só faz `globalThis.ColetaML = ...`; `const` no topo poluiria o escopo léxico do console (colar 2x daria "already declared"). No `vm.createContext`, passe `setTimeout`, `clearTimeout`, `AbortController`, `console`, `location` e `localStorage`: o contexto vem sem eles.
- `Promise.race([saiu, new Promise(r => setTimeout(r, 5000))])` no `after` segura o processo do `node --test` pelos 5 s inteiros: guarde o timer e faça `clearTimeout`. Sintoma: testes somam ~300 ms e a suíte leva 5 s.
- fetch padrão no browser: use `(...a) => globalThis.fetch(...a)`; guardar `globalThis.fetch` como método de objeto dá "Illegal invocation".
- `node:http` não usa `http_proxy`, então o adaptador para o servidor de teste funciona com os proxies mortos no ambiente. Conecte em `127.0.0.1` e mande `Host: localhost:<porta>` (o `servidor.py` só escuta em 127.0.0.1 e confere o Host).
- Mutantes: copie `coletar_ml.js`, `buscas.json`, `servidor.py`, `testes/coletar_ml.test.mjs` e a fixture para o scratchpad (o `RAIZ` vem do local do teste) e troque trechos com um `node -e` que falha se o trecho não existir (um mutante "de X para X" passou despercebido uma vez).
- Teste de `parar()` com `pausa: [0, 0]` não pega a falta da checagem antes da pausa; use pausa longa e meça o tempo.
- `afiliar()`: um PATCH "perdido" no servidor falso não exercita a conferência, porque o item volta no `ml-sem-afiliado` e o laço principal o refaz. Para testar a conferência, grave outro `meli.la` (link errado), que o `ml-sem-afiliado` não enxerga.
- A página do linkbuilder é simulada no `vm` com `document`, `HTMLTextAreaElement` (setter de `value` no protótipo), `Event` e `XMLHttpRequest` falsos; o botão "Gerar" chama `ctx.fetch` (o do gancho) e, antes, uma URL qualquer, para provar que o gancho só pega `createLink`.
- Sem prova real: `fetch` do ML, captcha de verdade e o formato atual do polycard só são provados na etapa 9, pelo dono.

**How to apply:** ao mexer no `coletar_ml.js` (etapa 5, `afiliar()`) ou em testes node com `vm`. Relacionado: [[servidor-testes]].

**Contagem de termos (2026-11-03, E3 perfumaria):** ao mudar o número de termos de `buscas.json`, além do bloco `BUSCAS` do `coletar_ml.js` e de `test_coletar_amazon_qa.py`, o `testes/coletar_ml_qa.test.mjs` tem o total de termos fixo (hoje 140, linhas ~607-637). O bloco se regenera com o mesmo `blocoBuscas` do teste (JSON.stringify indent 2, linhas seguintes com 2 espaços). `buscas.json` não termina com `\n`: preserve.

**Ordem no ML (E6, 2026-11-03):** `coletar({ordem})` valida com `hasOwnProperty` em `ORDENS_ML` (senão `'constructor'` passa). Objetos de `init` do fetch falso vêm do realm do vm: `assert.deepEqual` contra literal falha, compare campo a campo. Mutantes da E6 (sufixo, chave `ordem|termo`, `in` no lugar de `hasOwnProperty`, `feitos.add`/`feitosAntes.has` sem chave) morrem na suíte `coletar_ml.test.mjs`.
