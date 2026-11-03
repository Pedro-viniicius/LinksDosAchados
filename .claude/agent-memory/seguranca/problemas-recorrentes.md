---
name: problemas-recorrentes
description: Falhas já vistas no projeto achadinhos que devem ser procuradas em toda revisão (escape no innerHTML, CORS aberto, static servindo a pasta toda, CSRF sem checagem)
metadata:
  type: project
---

Padrões a procurar sempre (origem: revisão "copiar imagem", 2026-11-03). Remova quando o servidor for corrigido.

- **Campo sem `esc()` em template de `innerHTML`** em `index.html`. Já apareceu com `it.loja` no badge (corrigido no front em 2026-11-03). Sempre grep por `${` sem `esc(`.
- **Servidor aceita escrita sem checar Origin/Content-Type e `loja` livre no upsert** (`servidor.py` `corpo()`/`upsert`): CSRF por form `text/plain`. Aberto; fora da feature, levado ao dono.
- **CORS `*` + `Access-Control-Allow-Private-Network: true` em toda resposta** + static servindo BASE inteira (`_chat.txt`, `.db`, `.claude/`, logs). Aberto (S1 de 2026-11-03), levado ao dono.
- **Allowlist de URL só na requisição**: em fetch novo do front, conferir também `r.url` final (o "Copiar imagem" já faz).
- **Sem teto de tamanho/dimensão** ao decodificar imagem externa (INFORMATIVA, não tratada).
- Runner `testes/rodar.mjs` abre CDP em porta efêmera de 127.0.0.1 com perfil temporário; checar que continua com `--remote-debugging-port=0`, perfil descartável e `kill` no `finally`.

Ver [[areas-sensiveis]], [[riscos-aceitos]].
