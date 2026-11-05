---
name: decisao-api-oficial-ml
description: Plano api-oficial-ml (2026-11-05), com OAuth PKCE por CLI ml_api.py, callback estático na Hostinger, tokens 0600 com flock, portão G1 (sondar) antes da fonte ml e da coleta, e fatos da API do ML medidos
metadata:
  type: project
---
O plano está em `docs/produto/planos/api-oficial-ml.md` (2026-11-05). Não tem brief: veio de um pedido do lead. A app "Etiqueta" no DevCenter tem o client `3553760734310605` e o redirect `https://desejodemenina.com/ml/callback`.

**Decisões e por quê:**
- **O `ml_api.py` é o único módulo que fala com a API.** O `autorizar` roda num processo só: gera o PKCE e o `state` em memória e lê com `input()` o endereço colado da barra. Assim nada fica em disco antes da troca.
- **Callback é página estática sem JS** em `public_html/ml/callback/`, com um `.htaccess` sem `RewriteEngine`. Ficaram descartados: o PHP que troca o code (levaria o Secret para a Hostinger), o JS (traz superfície de ataque) e o túnel.
- **Tokens num arquivo 0600 com flock.** Cifrar seria excesso: o refresh já exige o Secret.
- **Portão G1:** o dono roda o `sondar` antes da fonte `ml` do `atualizar_precos` (etapa 4) e da coleta (etapa 5, que depende ainda da P1).
- **Armadilha:** o `upsert` zera os CAMPOS ausentes. Por isso a fonte por id completa `data` com o que está no banco.

**Fatos medidos em 2026-11-05:**
- Sem token, `/sites/MLB/search` dá `403 forbidden`, num formato diferente do resto. Os outros endpoints dão 403 PolicyAgent.
- A doc diz que é preciso a permissão "Publicação e sincronização" para itens e produtos, e "Métricas do negócio" para `/highlights`.
- O `/items?ids=` está em descontinuação: o substituto é o `/items/bulk` (`status_code`, prefixo `body.`, até 20 ids).
- Um PR de terceiro, de out/2026, relata `/items/{id}` de terceiros com 403 e `/products/search` e `/products/{id}/items` com 200.
- O WebFetch dá 403 no developers.mercadolivre: use `curl -A "Mozilla/5.0 ..."`.
- O banco tem 3.818 itens do ML: 2.705 com `meli.la` e 1.112 sem afiliado.
- O repositório do site da Hostinger mudou para `~/Documentos/lande_pages/Lange_meninas/site/hostinger/`.

**Why:** a viabilidade da API não está provada. Se o G1 der 403, o ML segue no console.

**How to apply:** quando o lead trouxer o resultado do `sondar`, revise só as etapas 4 e 5 e a P1. Veja [[decisao-atualizar-precos]] e [[decisao-shopee-perfumaria]].
