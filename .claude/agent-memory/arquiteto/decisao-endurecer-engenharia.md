---
name: decisao-endurecer-engenharia
description: Plano endurecer (09/11) + Entrega 2 (17/11, endurecer-entrega2.md): trava saída 4, backup auto-*, timers systemd via operacao/automatico.sh, hook UserPromptSubmit exit 2+JSON, corte do CLAUDE.md
metadata:
  type: project
---

Entrega 1 em docs/produto/planos/endurecer-engenharia-e-operacao.md (pronta, branch endurecer-engenharia). Entrega 2 em docs/produto/planos/endurecer-entrega2.md (17/11, esperando P4–P9 do dono).

- Trava por loja, saída **4**, não 2. **Why:** o 2 já significa "token do ML venceu, rode com o Secret".
- Backup `backup_banco.py`: só rotaciona `auto-*` (14, contados juntos). Backups antigos em WAL: ler com `immutable=1`, `mode=ro` recria -wal/-shm.
- Versão do servidor = sha256 dos .py (árvore fica dias suja).
- Entrega 2, decisões propostas:
  - Hook de prompt: **exit 2 + JSON** (`suppressOriginalPrompt`), porque exit 0 com JSON inválido deixa passar. Doc oficial: bloqueio NÃO tira o texto do disco (history.jsonl/transcript). Padrões reaproveitam `verificar.PADROES_SEGREDO` + regra de "bloco solto" (Secret colado sem palavra-chave). Teste com segredo falso montado em runtime (o `_NAO_FALSO` ignora FALSO).
  - Timers: `operacao/automatico.sh backup|amazon|ml` + `instalar-timers.sh` (padrão "Gerado por" da máquina). Shopee recusada. **Why ML quase inútil no timer:** access token 6 h e renovação exige client_secret (ml_api.py:682) — virou P8 (timer como lembrete).
  - `atualizar-ml.sh --sem-chave` explícito: detectar `-t 0` quebraria test_operacao (chave via pipe).
  - Só `test_shopee_por_item_qa.py` lê o CLAUDE.md; `test_servidor.py:309` só usa o caminho; CLAUDE.md dizia que test_ml_api_qa lê (errado).
- Fatos da máquina (17/11): Linger=no; relatorio-coletor.timer (outro repo) já lê a Meta; DBUS no ambiente do systemd --user; python3 do sistema tem bs4.
- Hook do designer (agents/designer.md) cobre menos arquivos que a lista de regra de negócio do CLAUDE.md.

**How to apply:** planos novos usam `verificar.py`; confira se a Entrega 2 foi aprovada/feita antes de citar automatico.sh, hook ou referências novas. Relacionado: [[decisao-atualizar-precos]], [[decisao-api-oficial-ml]], [[decisao-teste-front]].
