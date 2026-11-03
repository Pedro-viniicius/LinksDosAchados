---
name: cdn-imagens-fatos
description: Fatos verificados (2026-11-03) dos CDNs de imagem da Amazon e do ML, como CORS, padrões de URL, resolução e resposta para foto inexistente
metadata:
  type: project
---
Verificado com curl em 2026-11-03, no plano `docs/produto/planos/copiar-imagem.md`:
- `m.media-amazon.com` e `http2.mlstatic.com` mandam `access-control-allow-origin: *` com e sem `Origin`, sem `Vary`. Por isso o fetch CORS no front funciona, mesmo com a imagem em cache vinda do `<img>`.
- Amazon: 100% `…/images/I/<id>._AC_UL320_.jpg`. Trocar por `._AC_SL1000_` dá até 1000 px e não amplia. Foto inexistente devolve 400 text/plain.
- ML: 100% `D_Q_NP_2X_<id>-E.webp`, 560x560. Foto inexistente faz 302 para `/img-not-available/…gif` com 200, que precisa de detecção explícita.
- 55 itens da Amazon têm `imagem` vazia.

**Why:** a decisão de não usar proxy no `servidor.py` depende desses fatos.
**How to apply:** se aparecer erro de CORS ou de imagem, verifique de novo com curl antes de propor proxy. Veja [[decisao-teste-front]].
