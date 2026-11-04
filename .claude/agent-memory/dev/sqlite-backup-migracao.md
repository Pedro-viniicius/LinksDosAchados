---
name: sqlite-backup-migracao
description: Armadilhas do sqlite3 (Python 3.14) em script de migração com backup (migrar_categorias, classificar_lista): backup trava se a conexão de origem segura escrita; gatilho para provar a conferência antes do COMMIT; como provar na cópia do banco real
metadata:
  type: project
---

Vistas em 2026-11-03, na etapa 2 do plano eletronicos-e-coleta-ml (`migrar_categorias.py`):

- **`con.backup(dst)` trava para sempre** se `con` está dentro de `BEGIN IMMEDIATE` (o step dá SQLITE_LOCKED e o Python repete sem fim). Faça o backup por uma **segunda conexão** ao mesmo banco: com o lock de escrita na primeira, ninguém comita, e a cópia é o mesmo estado. Rode experimentos de sqlite com `timeout 20`.
- Restaurar com `src.backup(dst)` para um destino em WAL funciona (mesmo page size).
- `curl` respeita `http_proxy`: com o proxy morto exportado, o GET dá vazio. Use `curl --noproxy '*'`.
- Prova na cópia do banco real: cópia por `sqlite3.backup` de `file:achadinhos.db?mode=ro`, servidor em porta livre com `ACHADINHOS_DB`/`ACHADINHOS_PORTA` exportados em linha separada, `&` e `kill $PID` no fim do mesmo bash.
- Guarda de "banco real" testável sem risco: copie `servidor.py`, o script e `buscas.json` para um tmp com um `achadinhos.db` semeado, **e** passe `ACHADINHOS_DB` apontando para ele (se o import pegar o servidor errado, ainda cai no tmp).
- O `--restaurar` no banco "real" também testa a 8765, onde o servidor do dono costuma estar no ar: teste em subprocesso numa cópia do projeto tem que trocar `PORTA_PADRAO` na cópia por uma porta livre, senão o resultado depende da máquina.
- Módulo de teste importado por outro (o `qa` importa `test_migrar_categorias`): `tearDownModule` não roda para o importador. Para limpar temporário criado no import, use `atexit`.
- Mutantes "sem nfc" e "dest != cat" sobrevivem por serem equivalentes (o `nfc` externo cobre; origens não são chaves do mapa).

Vistas na etapa 6 do plano disparo-automatico (`classificar_lista.py`, 2026-11-03):

- Backups do mesmo segundo viram `achadinhos-<ts>.db`, `-1.db`, `-2.db`; `ls | tail -1` pega o `.db` sem sufixo (o `-` ordena antes do `.`), ou seja, o MAIS ANTIGO. Restaure sempre pelo caminho impresso em "Para reverter", nunca pelo `ls`.
- Script novo que reaproveita `migrar_categorias` (M): `M.comando('--restaurar', bk)` já imprime o comando do `migrar_categorias.py` (usa o `__file__` de M); `M.fazer_backup(total, 'nada foi gravado')` troca o texto do erro; mock de `M.verificar_backup` e `M.confirmar_banco_real` funciona porque C chama via `M.`.
- A reconferência dentro do `BEGIN IMMEDIATE` (depois do plano lido em `mode=ro`) só é provada trocando `M.confirmar_banco_real` por uma função que muda o banco no meio; sem isso o mutante sobrevive.
- Condição extra no `WHERE` do UPDATE (cat/busca de origem) é mutante quase equivalente dentro do `BEGIN IMMEDIATE`; prova: mock de `planejar` devolvendo um item com `._replace(de_busca='Outra')` (namedtuple) e esperar o erro de `rowcount`.
- `--restaurar` devolve o banco INTEIRO: com o disparo em uso (números, envios), o `seguranca` pede reversão cirúrgica (`--desfazer` por id do mapa) e o comando impresso tem que ser ela.
- Lista de mutantes com `\n` dentro: escreva o arquivo direto (heredoc com aspas), não por `re.sub`, que transforma `\n` em quebra de linha e quebra a string.

**How to apply:** ao escrever qualquer script que mexa no `achadinhos.db`. Relacionado: [[servidor-testes]].

Vistas na etapa 6 do plano abas-nichadas-e-coleta (`migrar_categorias.py`, 2026-11-04):

- Conferência "banco depois do UPDATE = plano" (dentro do `BEGIN IMMEDIATE`) só é provada com **gatilho** no banco de teste: `CREATE TRIGGER ... AFTER UPDATE OF cat ... BEGIN UPDATE/DELETE outro item; END`. O `rowcount` não conta o que o gatilho muda, então só a conferência pega. `recursive_triggers` vem desligado: gatilho que reescreve a própria coluna não entra em laço.
- `executemany(...).rowcount` soma as linhas mudadas; com lista vazia dá 0 (Python 3.14).
- `sorted()` de um dict com chaves `None` e `''` (busca NULL e vazia) dá TypeError: normalize com `busca or ''` antes de agrupar.
- Os 33 preços antigos implausíveis (>= 5x) do banco real são TODOS da "Perfumes e Perfumaria" (amazon): a limpeza muda `preco_antigo`/`desconto`/`atualizado_em` desses 33, mas ids e contagem da perfumaria ficam iguais.
- Abrir a cópia em `mode=ro` cria `-wal`/`-shm` ao lado, mas o sha do `.db` não muda (bom para provar "dry-run não grava").
