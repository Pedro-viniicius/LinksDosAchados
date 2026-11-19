# Referência: servidor (`servidor.py` e `achadinhos.db`)

Contrato do módulo, movido do `CLAUDE.md` em 17/11/2026 (plano `docs/produto/planos/endurecer-entrega2.md`, etapa 5). O `CLAUDE.md` guarda o mapa, as armadilhas que cruzam áreas e as regras de segredo, de LGPD e de afiliado, que valem aqui também. A API v1 (`/api/v1/*`) está em `docs/produto/referencias/api-ofertas.md`.

## `servidor.py`

**Regra de negócio.** Plano: `docs/produto/planos/blindar-servidor.md`.

- API REST (`/api/items`, `/api/config/<chave>`, `/api/fetch`, `/api/ml-sem-afiliado`) em http://localhost:8765/.
- Estático só de `/`, `/index.html` e `/testes/<nome>.test.html` (o resto dá 404).
- Só aceita `Host` `localhost`/`127.0.0.1` na porta; na API, só a própria origem e, para a coleta do ML, `https://lista.mercadolivre.com.br` e `https://www.mercadolivre.com.br` (GET, POST e PATCH em `/api/items`, `/api/items/<id>` e `/api/ml-sem-afiliado`).
- Escritas exigem `Content-Type: application/json` (415), corpo até 5 MB (413), `loja` `amazon`/`ml`/`shopee` e url da própria loja do item (mapa `URL_DA_LOJA`; item `shopee` só com `https://s.shopee.com.br/<código alfanumérico>`, via `eh_link_shopee`); no PATCH de `url`, link de afiliado da loja do item (400).
- O `CASE` do `upsert` preserva o link de afiliado já gravado, amarrado à loja (`GLOB`).
- `sanear_precos` limpa preço antigo implausível (≥ 5×) no `upsert` e no PATCH com `data`.
- `preco_em` (idade do preço) só é gravado por `agora()` quando a escrita traz preço legível (`preco_em_de`/`ler_preco`): no `upsert`, no PATCH com `data` e na confirmação de preço da v1 (`confirmar_preco_amazon`, veja `api-ofertas.md`); troca de `url`, `cat` ou público não mexe nele.
- O POST aceita `so_existentes: true` (só `bool`, senão 400): não insere, conta `ausente`.
- Um host novo da Shopee entra em três lugares: `servidor.py` e `disparo.py` (`HOSTS_AFILIADO_SHOPEE`) e `index.html` (`HOSTS_LINK.shopee`); `testes/test_front_constantes.py` reprova se algum ficar para trás.
- `/api/fetch` só busca `https` da Amazon.
- Banco e porta vêm de `ACHADINHOS_DB` e `ACHADINHOS_PORTA` (padrão: `achadinhos.db` e 8765).
- `GET /api/versao` (só da origem local, fora de `ROTAS_ML`): `codigo` (hash dos bytes de `servidor.py`, `disparo.py`, `genero.py` e `api_ofertas.py` na subida), `em_disco`, `mudou`, `git` (commit curto ou `null`) e `iniciado_em`; na subida o servidor imprime `Código <x> (último commit ...)`; `verificar.py --servidor` o consulta.
- `travar_rodada(loja)` (context manager; `RodadaEmAndamento` se ocupada): `flock` sem espera em `<banco>.rodada-<loja>.lock`, um por loja, usado pelos CLIs de coleta e de atualização (saída 4) e conferido (pega e solta) pelo freio da confirmação de preço da v1; só é seguro apagar o `.lock` com as rodadas dessa loja paradas (o sistema solta a trava quando o processo morre).
- `PUT /api/items/<id>/genero` (público corrigido à mão) está em `docs/produto/referencias/disparo.md`, seção `genero.py`.

## `achadinhos.db`

- Banco SQLite (tabela `items`, única por `loja`+`item_id`; tabela `config`). **Dados; nunca editar à mão.**
- O esquema migra em `criar_banco` (veja `disparo.md`): reiniciar o servidor ou rodar uma coleta migra, então faça backup antes.
