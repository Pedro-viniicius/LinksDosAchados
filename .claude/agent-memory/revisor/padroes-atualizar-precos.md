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
