---
name: testes-perfumaria-tres-lojas
description: Suítes do QA para Shopee como 3ª loja, ordens da Amazon e do ML e os 42 termos (plano perfumaria-tres-lojas): arquivos, como rodar, harness de mutantes e armadilhas
metadata:
  type: project
---

**Arquivos do QA (2026-11-03):** `testes/test_shopee_qa.py` (65; servidor em subprocesso + disparo sobre `T.Base` + `coletar_shopee` com API/conferência falsas + deriva de constantes), `testes/test_ordens_qa.py` (27; 42 termos, URL/chave da Amazon, CLI em subprocesso) e o bloco final de `testes/coletar_ml_qa.test.mjs` (218 no total, +20). Rodar: `http_proxy=https_proxy=ftp_proxy=http://127.0.0.1:9 no_proxy= python3 testes/test_shopee_qa.py` (idem `test_ordens_qa.py`).

**Armadilhas:** (1) importe `test_disparo as T` ANTES de `coletar_shopee`: o T fixa `ACHADINHOS_DB`/proxies; não importe `test_coletar_shopee` junto (ele sobrescreve o env e o assert de TMP quebra). Troque `S.DB`, `C.FEITOS`, `C.BUSCAS`, `C.ID_AFILIADO_SHOPEE` com `mock.patch.object`. (2) Depois da rodada 2 o `coletar_shopee` chama a API por `C.OPENER_API.open` (não `urlopen`) e `credenciais()` faz `os.environ.pop` do Secret; use `mock.patch.dict(os.environ, ...)` para restaurar. (3) O laço do coletor é termo por termo e, dentro, ordem por ordem (t1 rel, t1 vendidos, t2 rel...); a Amazon também. (4) Rota de atualizar regra do disparo é `PUT /api/disparo/regras/<id>`, não PATCH. (5) Fake de ASIN com truncamento colide: use hash. (6) `PATCH` no servidor, rodada 2: loja do item amarrada ao host do link (meli.la só em ml, tag só em amazon, s.shopee só em shopee); POST idem via `URL_DA_LOJA`.

**Mutantes:** espelho no scratchpad (servidor, disparo, coletar_*.py, buscas.json, coletar_ml.js, index.html, testes/), troca por string e roda só o arquivo QA. Equivalentes conhecidos: lote do servidor sem `eh_link_shopee` (o `upsert` ainda recusa com 400), `HOSTS_LINK_LOJA.get(loja, <host shopee>)` (loja desconhecida nunca entra em `regra.lojas`), `return 3` antes do print do limite (a mensagem agora é asserida).

**Fatos:** `imagem_permitida` do disparo é allowlist global (não por loja): item Shopee com foto do CDN da Amazon/ML sai com a foto (baixa, CA2 diz "foto do CDN dela"). `imagem_permitida` aceita host em caixa mista (inofensivo). `--ordens relevancia,,caros` do coletor Shopee ignora o vazio.
