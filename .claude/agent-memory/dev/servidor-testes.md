---
name: servidor-testes
description: Armadilhas ao testar o servidor.py (http.server do 3.14, /api/fetch e rede, proxy morto, mutantes em cópia, órfãos) e o comando que provou o front na 8766
metadata:
  type: project
---

Vistas em 2026-11-03, na etapa blindar-servidor:

- **Nunca rode teste de recusa do `/api/fetch` contra o código antigo** (fase "falha antes"): o código antigo faz `urlopen` de qualquer URL e o servidor de teste acessou a rede de verdade (evil.com, amazon). Para provar o "antes", use só os testes unitários com `mock.patch.object(S.OPENER_AMAZON, 'open', ...)`.
- `unshare -rn` não é permitido nesta máquina (uid_map): não dá para isolar a rede do teste assim.
- O `http.server` do Python 3.14 junta barras no início do caminho (`//x` vira `/x`) antes de chegar ao `do_GET`. Por isso `//` serve o `index.html` e `//testes/a.test.html` serve a página: não é vazamento.
- `send_error` chama `log_message` com um `HTTPStatus` em `args[0]`; filtro com `in` sobre `args[0]` precisa de `str()`.
- Suíte do front contra código novo, sem tocar o real: cópia por `sqlite3 backup` (fonte `file:achadinhos.db?mode=ro`) no scratchpad, `ACHADINHOS_DB=<cópia> ACHADINHOS_PORTA=8766 python3 -u servidor.py &` e `PORTA=8766 node testes/rodar.mjs copiar-imagem` no mesmo comando bash, matando o `$!` no fim. O node vem do `~/.nvm` (pôr no PATH).
- `ambiente()` de `testes/test_servidor.py` põe `http(s)_proxy`/`ftp_proxy` em `http://127.0.0.1:9` (proxy morto); `test_r2_*` confere que o `OPENER_AMAZON` do subprocesso pegou. Servidor avulso fora da suíte: exporte os mesmos proxies.
- Mutantes sem tocar os arquivos reais: copie `servidor.py`, `coletar_amazon.py`, `index.html` e `testes/` para o scratchpad, mute a cópia e rode os testes de lá (o `RAIZ` vem do local do arquivo de teste). Mutante que tira a limpeza da base deixa ~10 `python3 -u servidor.py` órfãos: liste com `readlink /proc/<pid>/cwd` e mate só os do scratchpad (o real tem cwd no projeto e cmdline `python3 servidor.py`).
- `unittest`: `addClassCleanup` roda mesmo quando o `setUpClass` falha; a lista `_class_cleanups` é compartilhada entre classes (funciona porque as classes rodam em sequência).
- Num bash, `X=... && cmd &` põe a atribuição dentro do subshell em background: declare variáveis em linha separada.

**How to apply:** ao mexer em `servidor.py` ou `testes/test_servidor.py`. Relacionado: [[chrome-headless-testes]].
