---
name: riscos-aceitos
description: Riscos que o dono do projeto achadinhos aceitou explicitamente, com a mitigação declarada (sem token na API; origens do ML podem POST/PATCH)
metadata:
  type: project
---

**R1 — API sem token; script em página do ML (ou extensão) pode POST/PATCH** (dono decidiu "sem token", P3 do plano `docs/produto/planos/blindar-servidor.md`, comunicado pelo lead em 2026-11-03).
- Mitigação declarada: só `https://lista.mercadolivre.com.br` e `https://www.mercadolivre.com.br`, só GET/POST/PATCH em `/api/items`, `/api/items/<id>` e `/api/ml-sem-afiliado`; CA6 (`loja` validada); CA7 (PATCH de `url` só com link de afiliado); prompt de Local Network Access do Chrome; servidor só em 127.0.0.1.
- Volta como achado se: a allowlist de origens crescer, `ROTAS_ML`/`METODOS_ML` ganharem DELETE/PUT/config/fetch, CA7 deixar de valer, ou o servidor escutar fora de 127.0.0.1.

Ver [[problemas-recorrentes]], [[areas-sensiveis]].
