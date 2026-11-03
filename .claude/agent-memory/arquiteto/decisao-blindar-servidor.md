---
name: decisao-blindar-servidor
description: Proposta (2026-11-03) para fechar o servidor.py, com allowlist de Host/Origin, origens do ML, estático por lista, env ACHADINHOS_DB/PORTA e testes unittest em subprocesso
metadata:
  type: project
---
Plano `docs/produto/planos/blindar-servidor.md` (2026-11-03), **aguardando aprovação do dono**. Corrige S1 e S2 do `seguranca`.
- A coleta do ML é cross-origin. O `servidor.log` mostrou 702 PATCH `/api/items/<id>`, cada um com OPTIONS antes, e GET `/api/ml-sem-afiliado`, além do POST vindo de `lista.mercadolivre.com.br`. Origens assumidas: `https://lista.` e `https://www.mercadolivre.com.br`; a do PATCH não foi verificada (o log não grava Origin).
- O `coletar_amazon.py` não usa HTTP: importa `servidor` e chama `upsert` direto. Variável de ambiente no `servidor.py` vale também para ele.
- O Chrome é o 156, com Local Network Access (prompt de permissão). O header PNA está obsoleto; o plano manda ele só no preflight aprovado do ML.
- A suíte do front passa a aceitar `PORTA` no `rodar.mjs`, para o qa rodar contra um servidor de teste com cópia do banco (`sqlite3 backup`, porque o banco está em WAL).

**Why:** tirar o CORS `*` quebraria a coleta do ML se a allowlist não cobrisse essas origens.
**How to apply:** em qualquer mudança no `servidor.py`, confira se o plano foi aprovado e implementado (procure `ORIGENS_ML`) antes de assumir CORS aberto ou fechado. Veja [[decisao-teste-front]].
