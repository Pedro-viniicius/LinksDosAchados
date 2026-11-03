---
name: genero-front-testes
description: Armadilhas do front do público (gênero) e de testes/genero.test.html - flooding de navegação, igual() com nó do DOM, foco em campo desabilitado, ++n em predicado
metadata:
  type: project
---

Vistas na etapa 6 do plano genero-nas-categorias (2026-11-03):

- **Flooding protection do Chrome:** `disparo.test.html` anda perto do limite de navegações por janela (hash + replaceState). Dois testes novos com ~14 trocas de hash fizeram o `abrir()` de um teste bem depois dar "tempo esgotado" (o hash não muda, nenhum erro). Prova: `--disable-ipc-flooding-protection` no `rodar.mjs` fazia passar. Solução: poucas navegações por teste novo (a página `genero.test.html` testa o formulário sem navegar, montando `htmlFormRegra()` num `div`). Não mexa no runner.
- **`igual()` com elemento do DOM não prova nada:** `JSON.stringify(el)` dá `{}` ou índices. Para identidade use um `mesmo(a, b)` (`!==`). Achei assertivas vazias no meu próprio teste de foco.
- **Foco em campo desabilitado:** o Chrome tira o foco no próximo quadro. Se a resposta falsa vem na mesma microtask, o mutante "não devolve o foco" fica vivo: `await dormir(150)` antes de resolver. E `.focus()` em campo dentro de `<details>` fechado não faz nada: abra o `details` antes.
- **`PUTS.length === ++n` dentro do predicado do `esperar()`** incrementa a cada polling. Calcule `n++` antes.
- A guarda do teste (`PUTS`, `PATCHES`) acumula entre testes: zere no `montar()`.
- `abas.test.html` falha 1 de 14 no banco atual mesmo com o `index.html` do HEAD (o contador agora cita Shopee: "540 Shopee"); não é regressão.
- Itens falsos: `W.eval('items = ' + JSON.stringify(lista))` + `W.render()` funciona (`let` global alcançado pelo eval); defina o título do item falso à mão quando o gênero do teste for texto malicioso (o título default o contém).
- `fmtNum`, `htmlChip` etc. são do segundo `<script>` do index.html, mas o `render()` só roda depois do fetch: o uso entre scripts funciona.
- Print em 320/1100 px por CDP (`Emulation.setDeviceMetricsOverride`): o `localStorage` precisa ser gravado numa página da mesma origem que não regrave (`/x` dá 404 mas serve); `abas.test.html` restaura `activeCat` no fim e sobrescreve.

**How to apply:** ao mexer no controle "Público", no campo de correção ou no formulário da regra. Relacionado: [[disparo-tela-testes]], [[chrome-headless-testes]], [[genero-testes]].
