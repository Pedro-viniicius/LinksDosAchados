---
name: decisao-teste-front
description: Estratégia de teste do front sem dependência, com testes/*.test.html rodados por node testes/rodar.mjs (Chrome headless via CDP) e iframe do index.html real
metadata:
  type: project
---
Adotada no commit `fcfcff8` (2026-11-03), a partir da ADR 2 do plano copiar-imagem.
- Os testes do front ficam em `testes/*.test.html`, servidos pelo `servidor.py`. Um iframe carrega `/index.html`, só faz GET na API e monta itens falsos com `win.renderCard`.
- O comando que vale é `node testes/rodar.mjs <nome>`, com Chrome headless via CDP em tempo real. O `--dump-dom` com virtual-time **não** serve: o resultado sai pendente com fotos reais.
- O plano blindar-servidor propõe a variável `PORTA` no runner e testes de servidor em `testes/test_servidor.py` (unittest com subprocesso).

**Why:** o projeto não tem suíte nem dependências. O node não tem canvas nem clipboard. O hook do qa só aceita caminhos com `/testes/` ou `.test.`.
**How to apply:** em features do front, exija lógica testável em `function` global (`let`/`const` não ficam em `window`). Veja [[cdn-imagens-fatos]] e [[decisao-blindar-servidor]].
