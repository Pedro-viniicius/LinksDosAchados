---
name: garimpo-banco-testes
description: Armadilhas do tools/garimpo_feminino/banco.py e do test_banco.py (falha no meio da transação, flock, mutantes S_ISREG e BEGIN deferred, ErroConfig mora no banco.py)
metadata:
  type: project
---

Vistas na etapa 2 do plano garimpo-feminino-shopee (2026-11-06):

- `sqlite3.Connection.execute` não aceita `mock.patch` (tipo em C). Para cair "no meio da página", o teste passa ao `gravar_pagina` um proxy (`ConexaoQueFalha`) com `execute` e `in_transaction`, que dispara na n-ésima instrução que começa com um prefixo (`INSERT INTO products`, `COMMIT`, `UPDATE consultas`). Por isso o `banco.py` só usa `con.execute` e `con.in_transaction` dentro das funções de gravação: se usar `executemany`/`commit()`, o proxy quebra.
- kill -9 no meio: subprocesso com proxy próprio inline que faz `os.kill(getpid(), SIGKILL)`. Não importe o `test_banco` no subprocesso: o topo dele cria TMP com `atexit`, que o SIGKILL não roda (sobra pasta).
- Mutante `BEGIN` (deferred) no lugar de `BEGIN IMMEDIATE` só morre se o espião (outra conexão com `timeout=0` tentando escrever) rodar ANTES do 1º INSERT da página; depois dele o deferred já segura a escrita.
- flock em dois `os.open` do mesmo arquivo no MESMO processo já conflita (descrições diferentes): dá para testar a 2ª trava sem subprocesso. O subprocesso serve para provar que `kill` não deixa trava velha.
- Mutante "tirar o `S_ISREG`" é equivalente com pasta (`O_RDWR` em pasta dá EISDIR); só morre com FIFO (`os.mkfifo`; `O_RDWR|O_NONBLOCK` abre FIFO no Linux).
- `PRAGMA journal_mode = WAL` muda o cabeçalho do arquivo: a guarda "não é garimpo.db" (versão > 1 ou tabelas sem versão) tem de rodar ANTES dele; o teste compara o sha do banco alheio.
- `ErroConfig` (saída 2) foi definida no `banco.py` (o `coletar_shopee.py` não tem): o `garimpo.py` da etapa 4 precisa tratá-la.

**How to apply:** ao mexer no banco do garimpo ou nos testes de motor/fases que gravam por ele. Relacionado: [[sqlite-backup-migracao]], [[coletar-shopee-testes]].
