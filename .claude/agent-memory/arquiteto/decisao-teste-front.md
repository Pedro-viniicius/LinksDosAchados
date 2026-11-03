---
name: decisao-teste-front
description: Estratégia de teste proposta para o front sem dependência, com página testes/*.test.html no Chrome headless via --dump-dom e iframe do index.html
metadata:
  type: project
---
Proposta em 2026-11-03 (plano copiar-imagem, ADR 2), **aguardando aprovação do dono**. Os testes do front ficam em `testes/*.test.html`, servidos pelo `servidor.py` real. Um iframe carrega `/index.html`, e a página roda com `google-chrome --headless=new --virtual-time-budget=30000 --dump-dom URL | grep RESULTADO`. Só GET na API e itens falsos montados com `win.renderCard`.

**Why:** o projeto não tem suíte nem dependências. O Chrome está em `/usr/bin/google-chrome`; o node existe via nvm, mas não tem canvas nem clipboard e exigiria extrair o JS do HTML. O hook do qa só aceita caminhos com `/testes/` ou `.test.`.
**How to apply:** em features do front, exija lógica testável em `function` global (`let`/`const` não ficam em `window`). Antes de reusar, confira se o dono aprovou e se o `CLAUDE.md` já registra o comando. Veja [[cdn-imagens-fatos]].
