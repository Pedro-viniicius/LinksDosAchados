---
name: padroes-shopee-tres-lojas
description: O que conferir quando mexerem na Shopee (servidor, disparo, coletar_shopee.py) e nas ordens das coletas: constantes duplicadas, fatos F3/F4/F5 pendentes, urlopen que segue redirect com Authorization
metadata:
  type: feedback
---

Rodada 1 do plano perfumaria-tres-lojas (E1-E3, E5-E7), 2026-11-03. Pontos a reconferir:
1. **Constantes repetidas de propósito**: `LOJAS` e `HOSTS_AFILIADO_SHOPEE` existem no `servidor.py` e no `disparo.py` (o disparo não importa o servidor). Um teste do `test_disparo.py` exige que sejam iguais. O comentário do servidor ("basta acrescentar shope.ee aqui") esquece o disparo e o `index.html`.
2. **Fatos ainda não confirmados** (podem mudar o código): `ID_AFILIADO_SHOPEE` foi preenchido na rodada 2 (não é segredo). Host do link curto (F3), CDN `down-br.img.susercontent.com` (F4), endpoint/assinatura/sortType/`extensions.code` (F5). Se o lead mudar algum, confira os testes que fixam o valor.
3. **`urllib.request.urlopen` segue 301/302/303 de um POST** e repassa todos os cabeçalhos menos Content-*, inclusive `Authorization`, para qualquer host e até para http. No `coletar_shopee.buscar` isso deixou de lado o "host fixo" do plano (só a assinatura vaza, não o Secret). A conferência usa opener sem redirect; a API não. Corrigido na rodada 2 (`OPENER_API` sem redirect, 3xx vira `ErroApi`): confira se continua assim.
4. **PATCH de `url` e lote não casam loja com host**: item amazon/ml aceita link da Shopee e item shopee aceita meli.la pelo PATCH. É um padrão antigo (ML com link da Amazon). O disparo segura na saída (`link_da_loja_ok`), mas o item fica mudo, sem aviso. Corrigido na rodada 2: `URL_DA_LOJA` no lote, `eh_link_afiliado_da_loja` no PATCH e `sql_link_preservado()` amarrado à loja com GLOB. No banco real (consulta `ro`, 2026-11-03) não havia nenhum par loja x host trocado e nenhuma linha que o LIKE antigo preservasse e o GLOB não.
5. **Progresso por ordem**: Amazon `busca|termo` / `ordem|<ordem>|termo` (o `feitos()` reescreve só `busca|`); ML termo puro / `<ordem>|termo`; Shopee `<ordem>|termo` em arquivo próprio. Nunca rode testes que escrevam no `coleta_amazon_feitos.txt` real.

6. **Front (E4, rodada 1)**: o `index.html` tem cópias próprias, `HOSTS_LINK` (detecção da loja ao colar; host desconhecido = toast, nada é enviado) e `HOST_FOTO_SHOPEE`, que desde a rodada 2 são amarradas ao servidor/disparo por `testes/test_front_constantes.py` (lê cada `const` numa linha só e roda o `lojaDoLink` no node contra `eh_url_de_loja`; 3 mutantes de host mortos). Mudou host? Esse teste tem que reprovar. A loja na fila/histórico sai de `items.find(item_pk)` no front (`lojaDoEnvio`), não da API: some se `items` estiver velho ou o item foi excluído. Para rodar a `disparo-integracao`, uma cópia `ro` do banco real serve enquanto ele não tiver número nem regra (confira `numeros`/`regras` = 0).

**Why:** o dev cumpre o CA com valores "a confirmar". O risco está na hora de trocar esses valores e no que ficou fora do teste (redirect, loja x host).
**How to apply:** na rodada 2 e na E4/E9, confira se os valores confirmados chegaram aos dois módulos e ao `index.html`. Ver [[padroes-disparo]] e [[padroes-coleta-ml]].
