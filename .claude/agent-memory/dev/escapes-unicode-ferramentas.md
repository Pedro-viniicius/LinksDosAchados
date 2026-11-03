---
name: escapes-unicode-ferramentas
description: As ferramentas Write/Edit gravaram escapes \uXXXX de código como os caracteres literais; como escrever e conferir
metadata:
  type: feedback
---

Em 2026-11-03, um `.replace(/[̀-ͯ]/g, '')` escrito com o Write saiu no `coletar_ml.js` com os combinantes literais dentro do regex (o revisor apontou como R7). Funciona, mas fica ilegível e frágil.

**Why:** o texto do parâmetro passa por decodificação de escapes antes de ir para o arquivo.

**How to apply:** quando o código precisar de `\uXXXX` (ou `\xNN`) literal, grave com um `node -e`/`node -` que monte a string com `\\u`, ou confira depois com `grep -nP "[\x{0300}-\x{036f}]" arquivo`. Escapes com barra dupla (`'\\u00'`) passaram intactos. Relacionado: [[coletar-ml-testes]].
