---
name: index-html-ui
description: Onde ficam tokens/componentes do index.html e armadilhas de UI recorrentes (feedback longe do controle, painéis no cabeçalho)
metadata:
  type: project
---

- Tudo em `index.html` (CSS no topo, tokens em `:root`, textos em constantes `TXT_*`). Gênero: `ABAS_COM_GENERO`, `.seg-filtro`, `select.gen` em "Mais ações". Spec: `docs/produto/specs/genero-e-ux.md`.
- Para ver a Perfumes em captura: CDP com Chrome headless (modelo em scratchpad `rg/shot.mjs`); `--screenshot` direto só mostra a aba padrão. Evaluate com `const` repetido falha em silêncio: usar IIFE.
- Armadilha recorrente: `.status` do cartão fica entre a mensagem e os botões, longe de controles em "Mais ações"; erro ali some da tela no celular.
- Painéis `#tplBox`/`#addBox` moram no cabeçalho; com cabeçalho não sticky (≤600 px) abrir pelo botão que está mais abaixo não mostra nada.
