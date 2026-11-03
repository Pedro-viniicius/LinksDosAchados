---
name: testes-genero-front
description: Páginas genero-qa e genero-integracao (front do Público/gênero, M1/M3/M5/M6/M7), como rodar, mutantes, bugs abertos e armadilhas
metadata:
  type: project
---

Verificado em 2026-11-03 (rodada 1, plano genero-nas-categorias, etapas 6, 7 e 9).

**Páginas** (nome com hífen; o servidor só serve `/testes/[a-z0-9-]+.test.html`)
- `testes/genero.test.html` (dev, 43): itens falsos, intercepta PUT/PATCH. Roda em qualquer servidor.
- `testes/genero-qa.test.html` (QA, 40): mesma guarda do dev, mais DELETE e `PUT /api/config/*` interceptados e `navigator.clipboard` trocado. Largura do iframe muda por `largura(px)` (media query do iframe vale, sem recarregar). Só GET sai: pode rodar em qualquer servidor.
- `testes/genero-integracao.test.html` (QA, 9): grava de verdade (PUT do público, número e regra). Guarda: recusa 8765 e banco com número/regra; desfaz tudo no fim e compara `/api/items` inteiro com o do início. Nunca rodei na 8765 (a guarda cai antes de gravar).
- Cópia do banco: `sqlite3.connect('file:achadinhos.db?mode=ro', uri=True).backup(...)`; `ACHADINHOS_DB=<c> ACHADINHOS_PORTA=<p> ACHADINHOS_DISPARO=0 ACHADINHOS_API_TOKEN_ARQUIVO=/nao/existe python3 servidor.py`; `PORTA=<p> node testes/rodar.mjs <pagina>`. Com proxies mortos exportados, `curl` precisa de `--noproxy '*'`.

**Armadilhas**
- `</script>` dentro de string JS da página fecha o bloco: a página fica sem saída ("sem saída" no runner). Use `<img ...>` como payload.
- `W.eval('PAGINA')` não enxerga constantes da página de teste; use o literal.
- `styleSheets[i].cssRules` lança SecurityError na folha do Google Fonts: pegue só as legíveis (try/catch).
- Overflow horizontal: `getBoundingClientRect` não mostra texto que vaza de caixa sem overflow; use também `e.scrollWidth > vw` (achou a aba de nome comprido).
- Teclado de verdade (setas do rádio, Tab) só com CDP `Input.dispatchKeyEvent`; evento sintético não troca rádio. Rodei um script avulso no scratchpad: Tab entra na opção marcada, setas trocam e marcam, foco fica, anel `solid 2px`, Shift+Tab volta (CA-V10 ok).
- Spec x tela: o "Para enviar · 3" da spec é "Para enviar (3)" na tela (testes do dev fixam "(3)"); entre 375 e 600 px o controle é 2 colunas (spec dizia uma linha se couber).

**Bugs abertos (rodada 1, baixos)**: render() durante o PUT deixa o cartão novo com o público antigo; "Sem gênero" escolhido e zerado por correção deixa nenhum rádio marcado até o próximo render(); nome de aba de uma palavra só com ~37+ letras faz rolar na horizontal a 320 px (abas em 2 colunas, `overflow-wrap:break-word` não reduz min-content). Testes vermelhos de propósito até o dev corrigir.

**Mutantes** (espelho no scratchpad com `index.html` mutado, servidor próprio 8783, script `mut.py`): 50 mutantes de index.html (contagem sem loja/título, memória sem validar, selo com público/sem corrigido/minúsculo, buscas sem restringir, 404=400, campo sem disabled/aria-busy, foco, cabeçalho sticky 320/desktop, abas sem grade, textarea 200, controle sem grade/36 px, title do copyimg, contador sem omitir loja, cabeçalho do disparo, tokens escuros fracos, sem reduced-motion, 6 esc() removidos, copiar página, Limpar filtros, regra com generos). Todos mortos por genero + genero-qa + genero-integracao; sobrevivente só equivalente (ordem interna do Template na barra). Lição: mutante de loja/título nas contagens só cai com loja E título juntos.
