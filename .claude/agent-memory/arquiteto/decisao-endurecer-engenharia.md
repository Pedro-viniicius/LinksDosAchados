---
name: decisao-endurecer-engenharia
description: Plano endurecer-engenharia-e-operacao (09/11/2026): verificar.py, trava por loja com saída 4, backup_banco.py auto-*, operacao/, .githooks, /api/versao; Entrega 2 = timers systemd, hook de prompt, corte do CLAUDE.md
metadata:
  type: project
---

Plano em docs/produto/planos/endurecer-engenharia-e-operacao.md (sem brief; pedido do lead). Corte em 2 entregas.

- Trava por loja (`<DB>.rodada-<loja>.lock`, em servidor.py), saída **4**, não 2. **Why:** o 2 já significa "token do ML venceu, rode com o Secret" no laço aba por aba; ML e Amazon rodam juntos de propósito.
- Backup `backup_banco.py`: só rotaciona `auto-*` (14 mais novos), 0600/0700, `journal_mode=DELETE` na cópia. **Why:** as sobras -wal/-shm em backups/ vêm de abrir cópia que herdou WAL; o banco tem `numeros` (dado pessoal).
- Versão do servidor = sha256 dos .py carregados (não só git). **Why:** a árvore fica dias suja; o git hash mentiria.
- Automação durável: timer systemd --user já é padrão da máquina (achadinhoturbo-backup.timer, Linger=no). Shopee nunca é automática sem reabrir "segredo nunca em arquivo".
- Armadilhas achadas: test_shopee_por_item_qa.py:1469/1475 e test_servidor.py leem o texto do CLAUDE.md/README (mudar doc quebra teste); skill rodar_localmente apontava para ~/Documentos/mensagensParaEnviar (inexistente); oráculo `_RE_PARECE_LINK` sem `\b` acusa `l.eb2gam1`.
- Lentos na linha de base: test_api_ofertas_qa (200 s), test_genero_qa (109 s); resto ~2 min.
- Não existe docs/produto/decisoes.md (conferido em 09/11).

**How to apply:** em planos novos, use `verificar.py` como verificação e a saída 4/trava se tocar CLI que grava; confira se a Entrega 1 já foi feita antes de citar esses arquivos. Relacionado: [[decisao-atualizar-precos]], [[decisao-garimpo-feminino]], [[decisao-teste-front]].
