---
name: padroes-atualizar-precos
description: Revisão do preço sempre atualizado (preco_em, v3, atualizar_precos.py, ColetaML.atualizar, trava do disparo): o que pegou na rodada 1 e como provar
metadata:
  type: feedback
---

Rodada 1 do plano atualizar-precos (2026-11-04). O que pegou:
1. **Regra "não apagar o preço" posta só no lote.** O `atualizar_precos.py` e o `ColetaML.atualizar` não mandam item sem preço legível. Já o "Atualizar preço" do cartão (`fetchItem` → `PATCH` com `data`) grava `preco: ''` e `preco_em NULL`, e a tela diz "Não consegui atualizar... Tente de novo", como se nada tivesse mudado. Prova: PATCH com `data.preco=''` num item Amazon da cópia. É o mesmo padrão de [[padroes-coletas-piso]] item 1: a regra fica num caminho e o outro escapa.
2. **Campo novo na v1 deixou vermelho o `api_ofertas_qa.test.mjs`** (4 pedidos simultâneos): `assert(!this.paused)` dentro do undici, no Node 22.23. Falha em 100% com `preco_em` e em 0% sem ele (cópia no scratchpad com o campo tirado). Ler os corpos em paralelo não resolve. A causa é o tamanho da resposta somado ao HTTP/1.0 do `http.server`, não a lógica. Campo novo na v1 pode quebrar cliente Node concorrente.
3. Bom no código: `so_existentes` exige bool; o `ColetaML.atualizar` manda antes um lote vazio para detectar servidor antigo; a validade é lida dentro do BEGIN IMMEDIATE; o `preco_recente` é igual no disparo, na v1 e no front (`>=`).

4. **Rodada 2 (2026-11-04): APROVADO COM RESSALVAS.** R1 corrigido (`precoLegivel` porta o `ler_preco` e barra o PATCH; ASIN diferente também barra). R2 corrigido (o teste lê cada corpo na hora; o guia da v1 avisa sobre o undici). R3 corrigido. Ressalva: o `selecionar` não aplica a folga de 5 min no futuro que o `preco_recente` aplica. Para isolar as linhas da rodada 2, guardei cópias dos .py e do index.html da rodada 1 no scratchpad (`cur/`). O `r1/diff.txt` sumiu do scratchpad entre as rodadas, então guarde cópia dos arquivos inteiros, inclusive dos novos sem rastreio.

**Why:** a decisão "mantém os dados antigos" chega ao dev como regra do lote. O caminho item a item, que já existia, não é revisto.
**How to apply:** em toda regra de gravação, rode `grep -n "UPDATE items SET" servidor.py` e confira o PATCH com `data`. Em campo novo da v1, rode `node --test testes/api_ofertas_qa.test.mjs` e compare com a base (`git archive <commit> | tar -x -C <scratchpad>`). Ver [[revisao-ambiente]].

5. **Shopee por item, rodada 1 (2026-11-08): MUDANÇAS NECESSÁRIAS.** (a) Item que a fonte não marca (resposta só com outros produtos, `ErroApi`) e ordem "preço mais velho primeiro" = o mesmo item fica na frente em toda rodada, de todo dia. Com 5 desses, a parada `FiltroIgnorado` dispara logo no começo e a Shopee nunca mais atualiza. Provado sem rede com uma subclasse do `TestShopee` no scratchpad (`prova/prova_divergentes.py`): rodada 1 dá 0, a 2 e a do dia seguinte dão 1. (b) README mandou fazer backup com o CLI `sqlite3`, que não existe na máquina; a seção "Backup" usa o `python3 -c ... backup`.
**How to apply (fonte com retomada):** sempre pergunte "o que acontece com o item que não é marcado na próxima rodada, dada a ordem da seleção?". Em doc nova, confira todo comando de backup contra a seção "Backup" do README.

6. **Shopee por item, rodada 2 (2026-11-08): APROVADO COM RESSALVAS.** O R1 foi corrigido com linhas `tentado|<iid>` de qualquer dia: o item tentado sem sucesso desde o último preço vai para o fim da fila e não conta para a parada. A minha prova da r1 apagava o arquivo de progresso para simular o outro dia, e isso apagava também o histórico. Com `A.hoje` mockado, 5 dias seguidos dão 0. Com o arquivo apagado, a rodada para uma vez e a seguinte, no mesmo dia, se recupera. Os mutantes (sem `novo`, sem fim da fila, erro geral sem marca, `>=`→`>`) morrem no `test_atualizar_precos`. Ressalva: o erro geral (10020) marca um item por rodada, então credencial ruim empurra itens para o fim.
**How to apply:** em prova de vários dias, mocke o relógio (`hoje`) em vez de apagar o arquivo de progresso. Cópia para mutante sem o README faz o `test_shopee_por_item_qa` dar 1 erro de setUpClass: é artefato da cópia.

7. **Ajuste pós-G1 (2026-11-09, r1): MUDANÇAS NECESSÁRIAS.** O G1 deu 10010 e o lead passou os ids para literais na query, sem medir. O próprio repo já tinha a medição real do garimpo (`tools/garimpo_feminino/docs/api_interpretacao.md`, medicoes #37/#38): `$shopId: Int64` com número JSON dá 10010 ("wrong type", não sintaxe); com texto passa e devolve o item pedido. Mutante "sem `int()`" no literal (zero à esquerda vira GraphQL inválido → 10010 geral, para a rodada) sobreviveu às três suítes.
Rodada 2 (mesmo dia): APROVADO COM RESSALVAS. Ids voltaram às variáveis `Int64` como `str(int())`; mutantes sem `int()`, número JSON, sem teto, ids trocados e tipo `String` morrem. Ressalva: a linha da etapa 1 na tabela do plano ainda dizia "inteiros em variables".
**How to apply:** ajuste de formato da Open API da Shopee? Confira antes no `api_interpretacao.md`/`api_findings.md` do garimpo (medições reais) e na linha do portão no plano.
