---
name: decisao-abas-nichadas
description: Plano abas-nichadas-e-coleta (2026-11-04), com 17 abas do dono, migração pelo migrar_categorias, piso de qualidade nas 3 coletas, preço antigo saneado no upsert, Shopee por "importar" do painel e fatos medidos no banco
metadata:
  type: project
---
O plano está em `docs/produto/planos/abas-nichadas-e-coleta.md` (2026-11-04). Ele aguarda as respostas do dono de P1 a P8 e a spec `docs/produto/specs/abas-nichadas.md` do designer.

**Decisões e por quê:**
- **A migração reaproveita o `migrar_categorias.py`.** As mudanças são `ORIGENS` nova, `SUBTEMAS_LISTA` separado do `ALIAS` e `DESTINO_SEM_BUSCA`. O `ALIAS` não muda porque é espelho do `coletar_ml.js` e tem teste deepEqual.
- **O `classificar_lista.py` vira histórico**, com `ORIGENS_ANTIGAS` próprias.
- **Os termos atuais mudam de aba sem mudar o texto.** Assim, o progresso da Amazon e do ML continua valendo.
- **Testes que congelam o `buscas.json` histórico** passam a ler `testes/fixtures/buscas-2026-11-04.json`.
- **O piso fica em cada coleta, em Python e em JS.** O preço antigo é saneado num só lugar, o `upsert`, com o limite de 5× ou mais. O piso não vai para o `upsert` porque recusaria o que o dono acrescenta pelo site.
- **Shopee:** o subcomando `coletar_shopee.py importar ARQUIVO` (sem credencial) recebe o que o plugin captura do painel. O progresso é `vendidos|<termo>`, o mesmo da Open API.
- **Front:** `ORDEM_ABAS` numa linha, igual às chaves do `buscas.json`. `cats()` hoje segue a ordem de aparição.

**Fatos medidos em modo ro (2026-11-04):**
- O banco tem 8.888 itens, não os 8.381 do lead. Os 507 a mais são da coleta da lista de presentes.
- Os subtemas da Lista WhatsApp sem destino são 4 (26 itens). O id 8524 é um item do ML sem busca nem dados.
- Há 19 títulos "Seminovo" ou recondicionados.
- Há 33 itens da Amazon com o preço antigo 5× ou mais acima do preço. O 5× ou 10× exato sugere preço por litro: o seletor de fallback em `coletar_amazon.py:66` é a hipótese.
- Os "mais vendidos" da Amazon e do ML dão 503 e 403 no WebFetch. O Promobit funciona.

**Why:** nada disso aparece no código. As contagens explicam as decisões.

**How to apply:** antes de outra reorganização, meça de novo os termos sem destino em modo ro. Não restaure o backup depois de uma coleta: os itens novos se perdem. Veja [[decisao-eletronicos-coleta-ml]], [[decisao-genero-categorias]] e [[decisao-shopee-perfumaria]].
