---
name: padroes-foto-grande
description: Revisão do bug Q1 (foto grande na v1, no disparo e no "Copiar imagem"): guarda de query sem teste, fuzz de paridade Python x front, números do banco copiado
metadata:
  type: feedback
---

R1 da correção Q1 (2026-11-08), `disparo.foto_grande` + `urlFotoParaCopiar`:
- **R1 [ATENÇÃO]**: a guarda "query ou fragmento volta igual" (`disparo.py` ~717, `index.html` ~991) não tinha teste que caísse. Os casos `...jpg?x=1` e `..._tn?x=1` não terminam no padrão, então passam até sem a guarda. Prova: um mutante sem a guarda deixou as suítes verdes e transformou `a._AC_UL320_.jpg?x=._b_.jpg` em `a._AC_SL1000_.jpg`, perdendo a query. Correção pedida: uma linha nas duas tabelas em que a query ou o fragmento terminam no padrão.
- R2 [SUGESTÃO]: a tabela de paridade não tem host nem esquema em maiúsculas.
- R3 [SUGESTÃO]: a fila e a prévia do disparo passaram a carregar a foto grande, e o copiar da fila ficou sem a miniatura de reserva.
- Pré-existente: `imagem_permitida` aceita `\t`, `\n` ou espaço no início, porque o `urlsplit` remove esses caracteres. Todas as 210 divergências do fuzz (60 mil casos) eram desse tipo. O banco real não tem nenhuma.

Números do banco copiado (15.238 itens): 10.878 fotos da Amazon e 3.817 do ML mudam; nenhuma das 511 da Shopee tem `_tn`; nenhuma URL grande passa de 200 caracteres. O Turbo aceita URL de até 4.096 caracteres e qualquer caminho do CDN.

**Rodada 2 (2026-11-08): APROVADO COM RESSALVAS.** R1 e R2 corrigidos. Os mutantes sem a guarda (4 casos caem no Python e 4 no front), sem `toLowerCase` (1 caso) e sem teto derrubam os testes. S1 pôs o teto de 2048 nos dois lados. R3 foi aceito no CLAUDE.md. Achado novo, R5 [SUGESTÃO]: a `-F.jpg` do ML com o cache do CDN frio levou 8 a 13 s (1 de 6 fotos ao acaso; as outras, ~0,1 s). O `baixarComoPng` corta em 15 s e devolve `rede`, que não tem fallback. O teste de rede real "foto do ML em -F.jpg" falhou 1 vez em 3 por isso. No Turbo, o Baileys baixa a URL e cai para texto se falhar.

**Why:** em tabela de paridade, um caso de "não muda" que não depende da guarda testada dá falsa cobertura.
**How to apply:** em toda regra de "volta igual", faça um mutante que tire a guarda. Para comparar Python com o front, extraia a função do `index.html` com `new Function` num `.mjs` do scratchpad (o script `rev/paridade.py` faz isso). Na r2, confira as linhas novas nas duas tabelas. Ver [[padroes-front-comportamento]] e [[padroes-api-v1]].
