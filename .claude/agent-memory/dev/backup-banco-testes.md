---
name: backup-banco-testes
description: Armadilhas do backup_banco.py e do test_backup_banco.py (etapa 4 do endurecer-engenharia): corrupção que só o integrity_check pega, tratador de sinal sentinela, mutantes redundantes, link sem sobrescrever
metadata:
  type: project
---

Vistas em 2026-11-09 (etapa 4 do plano endurecer-engenharia-e-operacao):

- **Banco que só o `integrity_check` reprova:** criar tabela `lixo` com ~100 linhas, `PRAGMA writable_schema=ON` e `DELETE FROM sqlite_schema WHERE name='lixo'` (o Python 3.14 deixa). As páginas ficam órfãs ("Page N: never used") e o `COUNT(items)` segue funcionando. Sobrescrever páginas com lixo não serve para isso: o `COUNT` também quebra e o mutante "sem integrity" sobrevive.
- **Teste de "o tratador antigo volta"** precisa instalar um tratador sentinela antes do `main()`: senão o `getsignal` de antes já é o `_interromper` deixado por outro teste (num mutante que não restaura) e a asserção passa à toa.
- `os.link(..., src_dir_fd=, dst_dir_fd=, follow_symlinks=False)` é o "nunca sobrescreve" atômico (EEXIST); o `os.replace` do contrato sobrescreveria um nome que aparecesse durante a cópia.
- O backup pela API do sqlite herda o modo WAL no cabeçalho (bytes 18-19 = 2); `PRAGMA journal_mode=DELETE` na conexão de destino logo depois do `backup()` deixa 1/1 e nenhum `-wal`/`-shm` sobra.
- `semear()` sem conexão aberta: ao fechar, o sqlite faz checkpoint e apaga o `-wal`; para ter `-wal` com dados, mantenha a conexão aberta com `wal_autocheckpoint=0`.
- Mutantes "parcial nasce 0644" e "sem fchmod 0600 no parcial" sobrevivem sozinhos por serem redundantes entre si; juntos morrem (`test_parcial_nasce_0600`, com `os.umask(0)`).
- Mutantes rodam numa cópia com só `servidor.py`, `backup_banco.py`, `testes/test_backup_banco.py` e `testes/test_servidor.py` (~3 s cada).

- Rodada 2: a rotação apaga `auto-*.db.parcial` parado há mais de 6 h **pelo mtime** (não pela data do nome): os testes do `qa` (`test_endurecer_qa`) criam `.parcial` com data antiga no nome e mtime de agora e exigem que fique. `apagar_se_comum` ignora `FileNotFoundError` no unlink (dois backups rotacionando juntos). SIGTERM depois do `os.link`: a mensagem é "backup interrompido; confira backups/".

**How to apply:** ao mexer no `backup_banco.py` ou ao escrever outro script que copie o banco. Relacionado: [[sqlite-backup-migracao]], [[cota-tmp]].
