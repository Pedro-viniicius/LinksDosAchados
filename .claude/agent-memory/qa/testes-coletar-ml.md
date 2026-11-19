---
name: testes-coletar-ml
description: Como rodar e estender os testes do coletar_ml.js (node:test + vm), harness de mutantes, equivalentes conhecidos e fatos do banco real sobre o ML
metadata:
  type: project
---

**Rodar:** `export http_proxy=http://127.0.0.1:9 https_proxy=$http_proxy ftp_proxy=$http_proxy no_proxy=; node --test testes/coletar_ml.test.mjs` (dev, 90 em 2026-11-03) e `node --test testes/coletar_ml_qa.test.mjs` (QA, 191). Um arquivo: `node --test testes/<arquivo>`. Integração sobe `servidor.py` com banco temporário e porta livre; fala com ele por `node:http` com `Origin` do ML (o `fetch` do Node não é usado de propósito).

**Estrutura do QA:** helpers duplicados (o arquivo do dev não exporta). `carregar({origem, caminho, extras, aleatorio})` roda o script em `vm` (`caminho` = `location.pathname`, padrão `/afiliados/linkbuilder` no www). `relogio()` troca o `setTimeout` do contexto: registra as pausas e só dispara os prazos de 30 s e 60 s se listados em `estourar` (qualquer atraso >= 30000 é tratado como prazo). `fetchChrome` faz o preflight CORS antes de POST/PATCH como o Chrome. `linkbuilder({dados, via:'fetch'|'xhr', pedido, modoRotulo})` é a página falsa com `Response` real. `servidorMem(itens, gancho)` é o servidor em memória do `afiliar()`.

**Armadilhas:** (1) `carregar({localStorage: undefined})` cai no valor padrão; use `null`. (2) Teste que trava a promessa faz o node:test marcar "cancelled" com `# fail 0`: no harness de mutantes some `fail + cancelled`, senão mutante morto parece sobrevivente. (3) Quando a conferência gera de novo (rodada 2), todo teste que conta chamadas do `gerar` ganha mais uma geração por volta. (4) `servidor.py` real em 8765 é do dono: só GET, com `curl --noproxy '*'`.

**Mutantes:** espelho no scratchpad com `servidor.py`, `buscas.json`, `coletar_ml.js` e `testes/`; troca de trecho por string e roda os dois arquivos. Sobreviventes equivalentes conhecidos: `ALIAS[t] || t` sem hasOwnProperty, alternativa `x([0-9a-f]{2})` do decodificador (inalcançável), `if (execucao.parar) break` logo após `estado.correcoes +=` na conferência (só muda um log).

**Fatos do banco real (2026-11-03, 2.704 itens ML, só leitura):** todo `meli.la` tem 7 caracteres `[A-Za-z0-9]`; todo `item_id` é `MLB\d{6,}`; `num_avaliacoes` e `cupom` são sempre vazios no ML; `desconto` bate com `Math.round` do JS (135 de 200 = -33%, meio ponto sobe). Os formatos estão num teste do QA (`os campos têm os formatos dos 2.704 itens`).

**Só a etapa 9 prova:** estrutura real do polycard, regex de vendas/avaliação em páginas reais, captcha do ML, `createLink` real (ordem, `-_JM`, 50 falha), clique real em "Links curtos"/"Gerar", setter nativo no React, nome real do campo `tag` no pedido, Chrome com Private Network Access/Local Network Access para localhost.

**Busca sem resultado / ofertadodia (rodada 1 em 2026-11-15, reprodução):** fixture sintética `testes/fixtures/ml-busca-sem-resultado.html` (literal `.q("0:{\"optimizedResponse\":...rescue type zrp...}")`); testes novos no fim de `coletar_ml.test.mjs` (describes "ordem 'ofertadodia' removida", "busca sem resultado", "busca sem polycard e sem marcador continua sendo erro"). Campo esperado `estado.semResultado`; log exigido por regex `/"<termo>"[^\n]*não trouxe resultado/` e, fora da relevância, cita a ordem. Armadilha: array vindo do contexto vm precisa de `js()` antes do `deepEqual`; testes de regressão usam `estado.semResultado ?? []` para passarem antes do campo existir.

**Rodada 2 (2026-11-15, Q1 fechado):** `coletar_ml.test.mjs` 253, `coletar_ml_qa.test.mjs` 219. Teste de "parada" que prova de verdade: chamar `ML.parar()` de dentro do `pagina` do `fetchFalso` ao abrir o 2º termo (3 termos, todos sem resultado) e conferir `estado.parado` + nenhum `warn` `nenhum termo trouxe resultado`; com 1 termo o limite de 2 já esconde o mutante. Mutantes do aviso no ramo `parar()` (copiar `coletar_ml.js` e acrescentar `avisarSemResultadoGeral(estado, buscados, ordem);` depois do log "parado." de cada função) morrem só por esses testes R5. Copie `testes/` inteiro para o espelho (fixtures incluídas).
