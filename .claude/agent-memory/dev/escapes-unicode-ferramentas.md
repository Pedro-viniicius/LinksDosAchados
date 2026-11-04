---
name: escapes-unicode-ferramentas
description: As ferramentas Write/Edit gravaram escapes \uXXXX de código como os caracteres literais; como escrever e conferir
metadata:
  type: feedback
---

Em 2026-11-03, um `.replace(/[̀-ͯ]/g, '')` escrito com o Write saiu no `coletar_ml.js` com os combinantes literais dentro do regex (o revisor apontou como R7). Funciona, mas fica ilegível e frágil.

**Why:** o texto do parâmetro passa por decodificação de escapes antes de ir para o arquivo.

**How to apply:** quando o código precisar de `\uXXXX` (ou `\xNN`) literal, grave com um `node -e`/`node -` que monte a string com `\\u`, ou confira depois com `grep -nP "[\x{0300}-\x{036f}]" arquivo`. Escapes com barra dupla (`'\\u00'`) passaram intactos. Relacionado: [[coletar-ml-testes]].

Em 2026-11-03 (E7), um `\u0085` (barra simples) num literal Python escrito pelo Write saiu intacto como escape: o comportamento não é constante. Confira sempre com `grep -nP`.

Em 2026-11-04 (etapa 3 de atualizar-precos), um `'٢...'` dentro de um heredoc `<<'EOF'` do **Bash** também saiu como caractere literal: a decodificação vale para o texto do comando, não só para o Write/Edit. Antes de "corrigir", veja se o arquivo já usa o literal (o `test_api_ofertas.py` já tinha `'٢٠٢٦-...'` no HEAD): aí fique com o padrão do arquivo.
