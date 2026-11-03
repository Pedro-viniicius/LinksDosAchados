---
name: problemas-recorrentes
description: Falhas já vistas no projeto achadinhos que devem ser procuradas em toda revisão (escape no innerHTML, guardas de origem do servidor, allowlist de URL, validação de tipo do corpo)
metadata:
  type: project
---

Padrões a procurar sempre (origem: revisões de 2026-11-03).

- **Campo sem `esc()` em template de `innerHTML`** em `index.html` (já houve com `it.loja`). Grep por `${` sem `esc(`.
- **Guardas do servidor**: toda rota/método novo tem que chamar `bloquear()` primeiro; nenhum caminho pode mandar `Access-Control-Allow-Origin: *`; estático continua por allowlist (antes servia a pasta toda, com `_chat.txt`).
- **Allowlist de URL**: conferir URL pedida E destino final/redirect (front `r.url`; servidor `RedirecionamentoAmazon`).
- **Checagem de afiliado por parâmetro**: exigir exatamente um `tag` (corrigido em 2026-11-03 com `== [TAG_AMAZON]`); `meli.la/<qualquer>` não prova a etiqueta (inerente, coberto por R1).
- **Tipo inesperado no corpo**: `conferir_tipos()` barra dict/list, mas int fora de 64 bits em `data` passa e vira `OverflowError` no sqlite (não é `ValueError`), derrubando a conexão sem gravar (BAIXA aberta). Confira em rota nova.
- **Corpo**: `MAX_CORPO` 5 MB (413), `Handler.timeout=15` (408). Imagem no front ainda sem teto (INFORMATIVA).
- Runner `testes/rodar.mjs`: CDP em porta efêmera de 127.0.0.1, perfil temporário, `kill` no `finally` e em SIGINT/SIGTERM.

Ver [[areas-sensiveis]], [[riscos-aceitos]].
