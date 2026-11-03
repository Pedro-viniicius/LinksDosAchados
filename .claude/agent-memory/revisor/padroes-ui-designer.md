---
name: padroes-ui-designer
description: Problemas recorrentes nas mudanças visuais do index.html (contraste de borda de campo, cor fixa fora de token, informação removida sob "sinal-ruído", flex:1 em textarea quebrando resize)
metadata:
  type: feedback
---

Nas mudanças visuais do `designer` no `index.html`, confira estes pontos antes de aceitar que ele diz cumprir o WCAG:
1. Borda de campo precisa de 3:1 ou mais (SC 1.4.11). O `--linha` dá entre 1,2 e 1,3:1; o projeto usa `--linha-campo` (= Mudo) só em campos.
2. Procure cor literal fora de `:root` (`grep -nE '#[0-9a-fA-F]{3,6}'` no `<style>`).
3. Sob o rótulo "sinal-ruído", ele já removeu informação. Trate isso como remoção de feature e leve ao lead. Decisões do dono em 2026-11-03: os totais por loja do `#count` ficam; o card fica sem a URL visível; o Google Fonts foi aceito e consta no "Stack" do `CLAUDE.md`. Não reabra esses três.
4. Um `flex:1` (base 0%) num textarea dentro de flex column ignora a `height` que o `resize` grava, e o arrasto para de funcionar. A forma certa aqui é `.card textarea{flex:1 0 auto}`, só no card. A regra global de `textarea` fica sem `flex`.

**Why:** foi o que apareceu nas três rodadas do redesenho de 2026-11-03. O item 4 nasceu de uma sugestão minha, então confira o efeito colateral das próprias sugestões.
**How to apply:** calcule o contraste com um script Python (luminância relativa do WCAG). Para comportamento de CSS, monte uma página estática no scratchpad com o `<style>` atual e meça com `google-chrome --headless=new --dump-dom` e um `<script>` que escreve `getBoundingClientRect()` no DOM. Ver [[revisao-ambiente]].
