---
name: riscos-aceitos
description: Riscos que o dono do projeto achadinhos aceitou explicitamente, com a mitigação declarada (sem token na API; origens do ML podem POST/PATCH)
metadata:
  type: project
---

**R1 — API sem token; script em página do ML (ou extensão) pode POST/PATCH** (dono decidiu "sem token", P3 do plano `docs/produto/planos/blindar-servidor.md`, comunicado pelo lead em 2026-11-03).
- Mitigação declarada: só `https://lista.mercadolivre.com.br` e `https://www.mercadolivre.com.br`, só GET/POST/PATCH em `/api/items`, `/api/items/<id>` e `/api/ml-sem-afiliado`; CA6 (`loja` validada); CA7 (PATCH de `url` só com link de afiliado); prompt de Local Network Access do Chrome; servidor só em 127.0.0.1.
- Volta também se o POST voltar a aceitar `url` fora de `eh_url_de_loja` ou o front abrir url sem checar `https:` (furo S1, fechado em 2026-11-03).
- Conferido em 2026-11-03 (revisão do disparo): `/api/disparo/*` fora de `ROTAS_ML`, R1 continua valendo. Impacto novo de R1: texto livre de item (título) agora alimenta mensagem enviada ao grupo e regex do agendador (ver S1/S2 em [[problemas-recorrentes]]).
- Conferido em 2026-11-03 (Shopee, E1): `s.shopee.com.br/<código>` não prova o dono, como `meli.la`; uma origem do ML pode criar item `shopee` com link de outro afiliado e ele sai no disparo. Mesma classe já coberta por R1; allowlist de origens e `ROTAS_ML` não mudaram.
- Conferido em 2026-11-03 (API v1, E1/E2): gatilhos não dispararam (origens, `ROTAS_ML`, `METODOS_ML` e bind em 127.0.0.1 iguais). O token da v1 não protege mais que hoje contra processo local (`GET /api/items` sem Origin segue aberto). Impacto novo: item plantado por origem do ML (com `meli.la`/`s.shopee` de terceiro) sai pela v1 para o Turbo, que pode enviar sem o dono olhar; recomendei ao lead reconfirmar R1 com o dono (sem resposta até a rodada 2). O contrato manda o Turbo regerar o link do ML ou revisar; o da Shopee (`s.shopee`, também sem prova do dono) segue "como veio".
- Conferido em 2026-11-03 (gênero, E2/E3/E5): gatilhos não dispararam; a rota de correção do público ficou fora de `ROTAS_ML`. Impacto novo: título/busca plantados mudam o gênero automático, e o item entra em regra/filtro por público.
- Volta como achado se: a allowlist de origens crescer, `ROTAS_ML`/`METODOS_ML` ganharem DELETE/PUT/config/fetch, CA7 deixar de valer, ou o servidor escutar fora de 127.0.0.1.

Ver [[problemas-recorrentes]], [[areas-sensiveis]].
