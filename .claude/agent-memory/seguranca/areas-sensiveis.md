---
name: areas-sensiveis
description: Onde mora dado pessoal, entradas públicas, superfícies de rede e invariantes do projeto achadinhos (servidor local 127.0.0.1:8765)
metadata:
  type: project
---

Mapa de superfície (conferido em 2026-11-03; confira no código antes de usar).

**Dado pessoal**
- `WhatsApp Chat - AmazonLinks/_chat.txt` (e o `.zip`): nome do dono. Fora do git (`.gitignore`), mas DENTRO da pasta servida pelo `servidor.py` (static de BASE inteira) -> responde 200 com `Access-Control-Allow-Origin: *`. Não leia o conteúdo; cheque só status/headers.
- `achadinhos.db`: produtos e links de afiliado, sem dado de cliente. Também servido como arquivo estático.

**Entradas externas**
- POST `/api/items`, PATCH/DELETE `/api/items/<id>`, PUT `/api/config/<chave>`: sem autenticação, sem checagem de Origin/Content-Type (`corpo()` faz json.loads de qualquer corpo). `loja` é livre no upsert.
- `/api/fetch?url=`: `urllib.request.urlopen` de URL arbitrária no servidor (SSRF; aceita esquemas do urllib). Devolve só campos extraídos por regex.
- Coluna `imagem`/`titulo` etc. vêm de scraping (Amazon, ML via Claude in Chrome).

**Saídas no front (`index.html`)**
- Tudo via template string + `innerHTML`; `esc()` escapa `& < > "` (não `'`; atributos usam aspas duplas).
- "Copiar imagem" (2026-11-03): allowlist `HOSTS_FOTO` + https antes do fetch, `credentials:'omit'`, timeout 15 s, canvas -> PNG -> clipboard só no clique.

**Invariantes**
- Todo link gravado é de afiliado (Amazon `tag=desejodemen01-20`, ML `meli.la`). Qualquer escrita não autenticada em `url` ameaça isso.
- Servidor escuta só em 127.0.0.1; não há CSP; headers CORS abertos em `end_headers`.

Ver [[problemas-recorrentes]] e [[riscos-aceitos]].
