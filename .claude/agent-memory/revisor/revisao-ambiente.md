---
name: revisao-ambiente
description: Como revisar neste projeto sem git e com o servidor no banco real; ferramentas disponíveis para checar UI (Chrome headless)
metadata:
  type: project
---

O projeto não é repositório git (verificado em 2026-11-03): o lead entrega a versão original do arquivo no scratchpad para `diff`.
O servidor em 8765 roda no `achadinhos.db` REAL: só GET (`curl localhost:8765/api/items`); nunca POST/PATCH/PUT/DELETE nem `/api/fetch`.

**Why:** não há linha de base em git, e gravar ou coletar mexe em dado real ou acessa a Amazon.
**How to apply:** compare o bloco `<script>` original com o atual (`diff <(sed -n '/<script>/,/<\/script>/p' ...)`) para provar que o JS não mudou. Para checar o layout, use `google-chrome --headless=new --window-size=320,1400 --virtual-time-budget=8000 --user-data-dir=<scratchpad>/perfil --screenshot=<scratchpad>/x.png http://localhost:8765/`. Ao carregar, a página só faz GET; `--force-dark-mode --blink-settings=preferredColorScheme=0` dá o modo escuro. Os dados reais têm 3 categorias curtas e alguns itens com `imagem: ''`, então card sem imagem é efeito do dado, não do layout.
