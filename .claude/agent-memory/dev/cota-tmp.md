---
name: cota-tmp
description: O /tmp (tmpfs) tem cota por usuário quase cheia; sqlite dá "disk I/O error" (SQLITE_IOERR_WRITE) e o dd dá "Disk quota exceeded" mesmo com o df mostrando GB livres
metadata:
  type: project
---

Vista em 2026-11-04 (etapa 1 de atualizar-precos):

- O `df -h /tmp` mostrava 1,5 GB livres, mas a cota do usuário deixava só ~28 MB (o `/tmp/claude-1000` das sessões ocupava ~4 GB). O scratchpad fica no mesmo `/tmp`.
- Sintoma: `sqlite3.OperationalError: disk I/O error` (`sqlite_errorname` `SQLITE_IOERR_WRITE`) na migração, `pwd: erro de escrita` e "Exception ignored while flushing sys.stdout". Parece bug do código e não é.
- Meça a folga de verdade escrevendo 1 MB por vez num arquivo do scratchpad até o `OSError` (o `df` não serve).
- `git archive HEAD` leva o PDF da identidade visual e o retrato do banco tem ~5 MB: duas árvores de cópia já comem a folga. Apague as cópias logo depois de usar.
- `testes/test_genero_qa.py` inteiro guarda várias cópias do banco real no mesmo TMP até o fim do módulo; com a v3 cada migração ainda escreve um WAL do tamanho do banco. Com a cota apertada, rode em grupos de classes (cada processo limpa o TMP ao sair). Dê os nomes das classes na linha de comando: assim elas rodam na ordem dada; sem nomes, o unittest roda em ordem alfabética.

**How to apply:** antes de culpar o código por erro de E/S em teste, meça a cota. Relacionado: [[servidor-testes]], [[atualizar-precos-testes]].
