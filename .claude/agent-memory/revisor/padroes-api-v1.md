---
name: padroes-api-v1
description: Como revisar a API v1 de ofertas (api_ofertas.py + guarda no servidor.py): medição no banco copiado, custo por pedido, linha ruim derrubando a API inteira, isolamento do token nos testes
metadata:
  type: feedback
---

Revisão da API v1 (plano api-achadinho-turbo, etapas 1 e 2, rodada 1, 2026-11-03):
1. **Medir no banco copiado, não só nos testes.** Script no scratchpad que importa `servidor` e `api_ofertas` com `ACHADINHOS_DB=<cópia>` e chama `A.rota(con, 'GET', ...)` em conexão `mode=ro`. Em 2026-11-03: 8.380 itens, 7.998 ofertas, 27 títulos recusados por `urls_da_mensagem` (o plano ainda cita 14), 54 Amazon com imagem vazia, 5 com desconto -100% (preço antigo mal coletado). Cerca de 0,5 s por pedido; `urls_da_mensagem` é 55% do tempo. Oito pedidos simultâneos levam 7,6 s (GIL). Percorrer tudo com o `limite` padrão (50) dá cerca de 160 pedidos, ou 80 s de CPU.
2. **Toda rota varre a tabela inteira com `oferta()`.** Uma linha que levante exceção derruba todos os pedidos com 500. O `preco`/`avaliacao` têm guarda de `inf`, mas o `contagem` dá OverflowError com mais de 308 dígitos e o `pct` dá ValueError com mais de 4.300. Só alcança quem grava sem o teto de 200 caracteres (o `upsert` do `coletar_amazon.py` não tem teto).
3. **Isolamento:** o `ambiente()` de `test_servidor.py` não define `ACHADINHOS_API_TOKEN_ARQUIVO`. Quando o dono criar o `api_token.txt`, todo servidor de teste vai subir com a v1 ligada pelo token real.
4. **Rotas fora do fonte:** o `test_ca6_antigo_rotas_do_fonte...` lê os literais `/api/...` do `servidor.py`. A v1 monta o caminho a partir de `api_ofertas.PREFIXO` (padrão aceito, igual ao do disparo).

5. **Rodada 2 (2026-11-03):** os itens 2 e 3 foram corrigidos (`oferta()` captura ValueError/OverflowError; o `ambiente()` usa `SEM_TOKEN_API`; os `.mjs` apontam a variável para um arquivo inexistente) e ficam como pontos de regressão. O `Handler.send_error` passou a não ecoar o cliente. Conferi os números do contrato `docs/produto/referencias/api-ofertas.md` contra o banco copiado e a maioria bateu, mas ele ainda diz "14 itens" recusados (são 27). O `curl -H @api_cabecalho.txt` funciona (curl 8.18); crie o cabeçalho e o token só no scratchpad. O `test_api_ofertas_qa.py` leva cerca de 60 s.

6. **Q1, validade padrão (r1, 2026-11-08):** sem `preco_max_horas`, o `listar` usa `D.validade_horas(con)` a cada pedido. No banco copiado: config real = 48 h, 6.398 ofertas no padrão contra 13.506 com 168 (o pedido ficou mais rápido, 0,6 s contra 1,3 s, pelo pré-filtro SQL). Mutantes que valem repetir (cópia do código no scratchpad, troca por `str.replace`): código antigo, 24 fixo, `min(pedido, config)`, cache em módulo, banco sem coluna liberando tudo; todos morreram. Pegadinha de fixture: item "ruim" sem `preco_em` passa a sumir pela validade e a asserção de exclusão vira vazia (o `api_ofertas_qa.test.mjs` só ficou protegido pelo `/categorias`). As 6 falhas de `V1PrecoMaxHorasNosDadosReais` vêm da folga (agora fixo em 04/11, metade dos itens atualizada depois), não do código.

**Why:** os testes usam poucos itens, então custo e dado estranho só aparecem com o banco real.
**How to apply:** na rodada 2 e em mudanças da v1, repita a medição e confira se o `log_message` continua redigindo a linha (`linha_v1_para_log`). Ver [[padroes-disparo]] e [[revisao-ambiente]].
