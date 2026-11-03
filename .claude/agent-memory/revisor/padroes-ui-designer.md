---
name: padroes-ui-designer
description: Problemas recorrentes nas mudanças visuais do index.html (contraste de borda de campo, cor literal, informação removida, flex:1 em textarea, aria-disabled vs hover, regra nova da spec não medida, cor da referência não conferida)
metadata:
  type: feedback
---

Nas mudanças visuais do `designer` no `index.html`, confira estes pontos antes de aceitar que ele diz cumprir o WCAG:
1. Borda de campo precisa de 3:1 ou mais (SC 1.4.11). O `--linha` dá entre 1,2 e 1,3:1; o projeto usa `--linha-campo` (= Mudo) só em campos.
2. Procure cor literal fora de `:root` (`grep -nE '#[0-9a-fA-F]{3,6}'` no `<style>`).
3. Sob o rótulo "sinal-ruído", ele já removeu informação. Trate isso como remoção de feature e leve ao lead. Decisões do dono em 2026-11-03: os totais por loja do `#count` ficam; o card fica sem a URL visível; o Google Fonts foi aceito e consta no "Stack" do `CLAUDE.md`. Não reabra esses três.
4. Um `flex:1` (base 0%) num textarea dentro de flex column ignora a `height` que o `resize` grava, e o arrasto para de funcionar. A forma certa aqui é `.card textarea{flex:1 0 auto}`, só no card. A regra global de `textarea` fica sem `flex`.
5. Botão "desabilitado" por `[aria-disabled="true"]` perde para os hovers globais `button…:hover:not(:disabled)`, que têm especificidade (0,2,1) a (0,3,1): no hover, a opacidade volta a 1. Calcule a especificidade e meça com `:hover` trocado por `.h`. Visto em `.copyimg` (copiar-imagem, 2026-11-03).
6. Regra nova que a spec cria na mesma mudança (ex.: "área de respiro = x-height" do logo, 2026-11-03) precisa valer na tela: meça. Listas exaustivas antigas ("Etiqueta só em: ...") também precisam ganhar o uso novo.
7. Afirmação sobre a referência (ex.: "a prancha negativa usa #FF5B14") pode estar errada: conte as cores da PNG num canvas (Chrome via CDP em tempo real, `--allow-file-access-from-files`; `--virtual-time-budget` com `--dump-dom` não espera o `decode()`). No logo, a prancha negativa usava #FF6A2B, igual ao token.

**Why:** os itens 1 a 4 apareceram nas três rodadas do redesenho de 2026-11-03, e o 5 apareceu na feature copiar-imagem. O item 4 nasceu de uma sugestão minha, então confira o efeito colateral das próprias sugestões.
**How to apply:** calcule o contraste com um script Python (luminância relativa do WCAG). Para comportamento de CSS, siga o método de [[revisao-ambiente]].
