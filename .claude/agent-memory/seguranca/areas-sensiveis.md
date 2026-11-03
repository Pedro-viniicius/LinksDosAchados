---
name: areas-sensiveis
description: Onde mora dado pessoal, entradas, guardas do servidor (Host/Origin/Sec-Fetch-Site, estático fechado) e invariantes do projeto achadinhos
metadata:
  type: project
---

Mapa de superfície (conferido em 2026-11-03, depois do plano blindar-servidor; confira no código antes de usar).

**Dado pessoal**
- `WhatsApp Chat - AmazonLinks/_chat.txt` (e o `.zip`): nome do dono. Fora do git. Desde o blindar-servidor NÃO é servido (estático só `/`, `/index.html`, `/testes/<nome>.test.html`). Não leia o conteúdo; cheque só status.
- `achadinhos.db`: produtos e links de afiliado, sem dado de cliente. Testes usam `ACHADINHOS_DB`/`ACHADINHOS_PORTA` com banco temporário.

**Guardas do `servidor.py` (`bloquear()`)**
- Host exato `localhost:<PORTA>`/`127.0.0.1:<PORTA>` (anti rebinding), em todo método.
- `/api/`: Origin local passa; Origin do ML (`lista.` e `www.mercadolivre.com.br`) só GET/POST/PATCH em `ROTAS_ML`; sem Origin, `Sec-Fetch-Site` cross/same-site = 403.
- Caminho cru (sem decodificar) para roteamento; HTTP/1.0 (uma requisição por conexão).
- Corpo: 415 sem `application/json`, 400 JSON inválido; `loja` em `LOJAS`; PATCH `url` só afiliado (`eh_link_afiliado`).
- `/api/fetch`: allowlist https `www.amazon.com.br`, `amazon.com.br`, `amzn.to`, conferida em cada redirect (`RedirecionamentoAmazon`).

**Saídas no front (`index.html`)**
- `innerHTML` com template string; `esc()` escapa `& < > "`. "Copiar imagem": `HOSTS_FOTO` na URL pedida e no `r.url` final.

**Invariantes**
- Todo link gravado é de afiliado (Amazon `tag=desejodemen01-20`, ML `meli.la`).
- Servidor só em 127.0.0.1; toda resposta leva `X-Frame-Options: SAMEORIGIN` e `frame-ancestors 'self'` (o teste embute o index.html); sem outra CSP.
- O servidor em 8765 é o REAL: só GET nele.

Ver [[problemas-recorrentes]] e [[riscos-aceitos]].
