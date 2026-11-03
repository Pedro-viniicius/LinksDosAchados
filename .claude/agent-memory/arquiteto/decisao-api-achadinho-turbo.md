---
name: decisao-api-achadinho-turbo
description: Plano api-achadinho-turbo (2026-11-03): /api/v1 só leitura, pull pelo Turbo, Bearer em api_token.txt, api_ofertas.py, cursor (atualizado_em,id) com folga; fatos do Achadinho Turbo
metadata:
  type: project
---
O plano está em `docs/produto/planos/api-achadinho-turbo.md` (2026-11-03). Aguarda as respostas do dono de P1 a P7. Até agora não há brief nem `docs/produto/decisoes.md`.

**Decisões e por quê:**
- **O Turbo puxa (pull).** O Etiqueta fica sem estado, e o Turbo já tem `candidatesFor` por tipo de fonte, com deduplicação por `key` em `sent_offers`.
- **Push só se o Turbo for para uma VPS** (o dono adiou). O formato da oferta foi pensado para servir aos dois.
- **Token Bearer em `api_token.txt`.** Ele fica fora do git, a API fica desligada sem ele (503) e é comparado com `compare_digest`.
- **Na tabela `config`, não.** O `GET /api/config/<chave>` vazaria o token.
- **O token não protege mais que hoje contra processo local,** porque o `/api/items` continua aberto (R1). O valor dele é o contrato estável para a VPS. A proteção real na máquina local é barrar Origin e Sec-Fetch-Site na v1.
- **A mensagem pronta fica fora da v1.** O Turbo tem templates próprios e precisa de números: preço como float, vendas como int, frete como bool.
- **`desconto_pct` cai no cálculo pelos preços quando o texto não traz o desconto.** O Turbo usa `discountPct ?? …`, e mandar 0 apagaria o desconto.
- **O cursor é `(atualizado_em, id)` com 60 s de folga.** 5.329 itens têm o mesmo `atualizado_em`, com precisão de segundo e hora local.

**Fatos do Achadinho Turbo** (`/home/ufla/Documentos/achadinhoturbo`, só leitura, outra sessão edita):
- Node e Express na porta 3737, como serviço systemd de usuário.
- A oferta de uma regra é `{key,url,title,price,oldPrice,coupon,discountPct,sold,freeShipping,image}`.
- O agendador exige a etiqueta do ML, sempre gera o link de novo pela extensão e só aceita foto `mlstatic`.
- Os segredos de loja ficam em `conexoes.segredos`.
- No Turbo, "etiqueta" quer dizer a etiqueta de afiliado do ML. Nomeie a fonte nova como `catalogo`.

**Why:** isso não aparece no código do Etiqueta.
**How to apply:** se o dono responder P1 a P7, ajuste só o plano. Se for pedido o lado do Turbo, faça um plano no repositório dele, seguindo o guia de encaixe do contrato. Veja [[decisao-disparo-automatico]] e [[decisao-blindar-servidor]].
