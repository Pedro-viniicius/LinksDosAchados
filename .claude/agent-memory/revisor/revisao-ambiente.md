---
name: revisao-ambiente
description: Como revisar neste projeto (git desde 309bb89, servidor no banco real só com GET), como checar UI no Chrome headless e como rodar as páginas testes/*.test.html de verdade
metadata:
  type: project
---

O projeto virou repositório git no commit `309bb89` (redesenho, 2026-11-03): use `git diff HEAD` e `git status`. `docs/produto/planos/` e `testes/` podem estar sem rastreio; leia-os direto.
O servidor em 8765 roda no `achadinhos.db` REAL: só GET (`curl localhost:8765/api/items`); nunca POST/PATCH/PUT/DELETE nem `/api/fetch`.

**Páginas de teste (`testes/*.test.html`):** o comando do plano com `--virtual-time-budget` (30000 até 3000000) parou em `RESULTADO: PENDENTE` depois de 5 a 8 testes, em cerca de 1,5 s reais (Chrome 156, 2026-11-03). Em tempo real, pelo protocolo de depuração via `--remote-debugging-pipe` (script Python só com a stdlib: fd 3 e 4, JSON terminado em `\0`, `Target.createTarget`, `Target.attachToTarget` com `flatten`, e `Runtime.evaluate` em `#saida` a cada 1 s), a suíte inteira roda em cerca de 2 s. Confira se o comando registrado no `CLAUDE.md` chega mesmo a `RESULTADO: OK`. Desde a rodada 2 de copiar-imagem, o runner do projeto é `node testes/rodar.mjs <nome>` (precisa do Node 22 ou mais novo, por causa do `WebSocket` global; a máquina tem o v22.23.0). Ele sai com código 0 só quando o resultado é OK.

**Servidor próprio para teste dinâmico (desde blindar-servidor, 2026-11-03):** faça a cópia do banco com `sqlite3 ... backup` (o banco está em WAL), a partir de `file:achadinhos.db?mode=ro`. Suba com `ACHADINHOS_DB=<cópia> ACHADINHOS_PORTA=<porta livre> python3 -u servidor.py`, guarde o PID e mate só ele. As suítes do servidor rodam com `python3 testes/test_servidor.py` e `python3 testes/test_servidor_qa.py`. Suba o servidor próprio com `http_proxy` e `https_proxy` apontando para `http://127.0.0.1:9` (proxy morto): o `/api/fetch` dá 502 sem acessar a rede. O servidor agora só serve `/`, `/index.html` e `/testes/*.test.html` (mais a guarda de Host e Origin). Nos testes de origem, confira se eles mandam os cabeçalhos que o Chrome manda de verdade (`Sec-Fetch-Site: cross-site` junto com `Origin`).

**Why:** gravar ou coletar mexe em dado real ou acessa a Amazon. E um comando de teste que nunca termina parece "pendente", não "falhou".
**How to apply:** para medir layout, copie o `index.html` para o scratchpad, troque `const api` por um stub com itens falsos, troque `:hover` por `.h` para medir a cascata e meça com `--dump-dom`. Abaixo de 500 px, o headless não reduz a janela: use uma moldura com `<iframe>` de 320 e 375 px e `--allow-file-access-from-files`. Um `<pre>` de medida com linhas longas gera rolagem horizontal falsa, então meça `scrollWidth` antes de inseri-lo. Ver [[padroes-ui-designer]].
