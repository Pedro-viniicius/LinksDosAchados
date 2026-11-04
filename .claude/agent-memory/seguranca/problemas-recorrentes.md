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
- **Texto do banco impresso cru no terminal** (`cat`/`busca` podem vir de origem do ML, R1): procure `print` de campos do banco sem `seguro()` (resolvido em `migrar_categorias.py` e `classificar_lista.py`; confira em script novo).
- **"Servidor no ar" checado só por uma porta**: guardas que dependem de `S.PORT` falham se o ambiente tiver outra `ACHADINHOS_PORTA` (no `--restaurar` resolvido para o banco real: testa também 8765).
- **Restaurar o banco inteiro desfaz exclusão de dado pessoal**: `migrar_categorias.py --restaurar` (reversão oficial dos scripts de reclassificação) recria `numeros` excluídos e apaga `envios` posteriores. No `classificar_lista.py` resolvido com `--desfazer` cirúrgico (2026-11-03); exija o mesmo em script novo de reclassificação. Backups 0664 aceitáveis: grupo `ufla` só tem o dono e `/home/ufla` é 0750.
- **Sink de url no front** (`href`, `window.open`, `location`): já houve `javascript:` vindo do POST até `window.open` (S1, corrigido em 2026-11-03 com `eh_url_de_loja` no lote e checagem `https:` no front). Toda rota/script novo que grava `url` deve passar por validação equivalente; `upsert()` direto não valida.
- **`meli.la` não prova a etiqueta**: o formato não diz qual conta gerou. No `afiliar()` a defesa é ler `tag` no corpo do pedido `createLink` (corrigido em 2026-11-03); se o ML mudar o nome da chave, cai só no aviso. Confira em todo fluxo novo de link de afiliado.
- **Regravar link de afiliado**: só por cima de link comum ou do que a própria execução gravou (conferência do `afiliar()`, corrigido em 2026-11-03). O PATCH do servidor não tem pré-condição: a janela GET→PATCH continua.
- **Detecção de URL em texto livre**: `disparo.urls_da_mensagem` usava allowlist de TLD (S1, 2026-11-03); corrigido na rodada 2 com análise por token, sem lista de TLD, e exigindo que toda candidata seja exatamente o link do item. Em detector novo, cobrir: TLD fora de lista (`andro.id`), IDN, `_dominio.com/x_`, pontos parecidos, crases/colchetes, esquema colado.
- **Expansão de `$\`` / `$'` no replaceAll do template** (`montar_mensagem` e `buildMsg`): campos com `$\`` multiplicam a mensagem campo a campo. No servidor, resolvido na rodada 3 (2026-11-03): `_Conta` soma antes de fatiar e para em `LIMITE_MONTAGEM` (8000); só `_escolher` (tick, agora, prévia) chama `montar_mensagem`, sempre com limite. O `buildMsg` do front continua sem limite (aba pode travar com item hostil, R1). Em caminho novo que monte mensagem com dado de item, exija o limite.
- **Regex sobre texto sem teto, dentro de lock/transação** (S2, 2026-11-03): tetos `MAX_TITULO`/`MAX_CAMPO` no `conferir_tipos` + detecção linear. Confira teto em campo novo que chega a regex.
- **Host do link não amarrado à loja do item** (S1 Shopee, 2026-11-03, corrigido na rodada 2 com `URL_DA_LOJA`/`eh_link_afiliado_da_loja`/`GLOB`): validação de url por allowlist global (`eh_url_de_loja`, PATCH `eh_link_afiliado`, `sql_link_preservado`) deixa `loja:'ml'` com link da Shopee etc. Em loja nova, exija host por loja na gravação, não só no disparo.
- **Cliente HTTP autenticado que segue redirect**: `urllib` repassa `Authorization` em 301/302/303 para qualquer host, inclusive `http` (S2 Shopee, corrigido em 2026-11-03 com `OPENER_API` sem redirect). Chamada com credencial deve usar opener sem redirect.
- **Segredo exportado no shell**: instrução `export SECRET` deixa o valor no ambiente de tudo que o terminal abrir depois (inclusive sessões de agente, onde `env` vazaria para a conversa). Prefira variável só no comando + `unset`, ou `getpass` (S3 Shopee, corrigido em 2026-11-03: `os.environ.pop` + README).
- **Log de acesso com a query**: `log_message` grava a linha da requisição crua. Rota que pode receber segredo (token, `?token=` por engano) precisa redigir pela linha crua (feito na v1 com `linha_v1_para_log`, 2026-11-03). O `send_error` passa o código em `args[0]`, então a mensagem dele (que pode citar a linha) não é logada.
- **Método sem `do_X` (TRACE, CONNECT, FOO)**: o `http.server` responde 501 antes do `bloquear()` (sem checar Host). Desde 2026-11-03 o `Handler.send_error` só repassa o código (a página não ecoa nada); confira que continua assim.
- **Token sem entropia mínima**: `TOKEN_VALIDO` aceita qualquer texto de 32+ caracteres (INFORMATIVA local, docs mandam `token_urlsafe(32)`; vira requisito com VPS).
- **Valor numérico gigante em campo de item** (`coletar_amazon.py` grava sem teto): `contagem`/`pct` podem levantar `OverflowError`/`ValueError`; caminho novo que converte campo do item deve isolar por linha (feito em `api_ofertas.oferta`).
- **Id do caminho sem teto de dígitos** (S1 BAIXA, 2026-11-03, corrigido na rodada 2): `int()` de `[0-9]+` com mais de 4300 dígitos dá `ValueError` e acima de 2^63-1 o sqlite dá `OverflowError`; a conexão caía sem resposta. Hoje `ROTA_ITEM`/`ROTA_GENERO` usam `[0-9]{1,19}` + `MAX_ID_SQLITE` → 404. Em rota nova com id no caminho, exija o mesmo.
- **Conferência do dono só por amostra de 1 link** (S1 BAIXA, 2026-11-04, `coletar_shopee.py importar`, corrigido na rodada 2 conferindo cada link distinto antes de gravar): vale amostra para a Open API (mesma credencial), não para arquivo externo. Em fluxo novo que grava link vindo de arquivo/captura, exija conferência de cada link distinto.
- **Regra aplicada só num caminho de gravação** (S3, 2026-11-04: `preco_antigo_plausivel` só no `upsert`, corrigido com `sanear_precos` também no PATCH `data`): regra nova de saneamento tem que valer em upsert e PATCH.
- **Regex de volume `\d[\d.,]*...` com `search`** (INFORMATIVA, 2026-11-04, `coletar_amazon.RE_COMPRAS`): quadrática em sequência longa de dígitos (20 mil dígitos ~7,6 s); `numero_de` com 300+ dígitos e "mil" dá `OverflowError`. Fonte é a Amazon, títulos curtos; confira em parser novo de texto de terceiro.
- **Doc diz "não acessa a rede" e o código acessa** (README do `importar`, 2026-11-04, corrigido na rodada 2): confira afirmação de rede/credencial na doc contra o código.
- Runner `testes/rodar.mjs`: CDP em porta efêmera de 127.0.0.1, perfil temporário, `kill` no `finally` e em SIGINT/SIGTERM.

Ver [[areas-sensiveis]], [[riscos-aceitos]].
