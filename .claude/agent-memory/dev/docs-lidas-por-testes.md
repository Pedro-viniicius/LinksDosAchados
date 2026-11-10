---
name: docs-lidas-por-testes
description: Quais testes leem README.md e CLAUDE.md e que trechos exigem; o bloco de backup do README é executado por 3 testes
metadata:
  type: project
---

Etapa 11 do endurecer-engenharia-e-operacao (2026-11-09):

- Só `testes/test_shopee_por_item_qa.py` (`TestDocumentacao`) e `testes/test_ml_api_qa.py` (`TestReadme`, seção "API oficial do Mercado Livre") leem as docs. `test_servidor.py` só cita `/CLAUDE.md` numa lista de rotas 404. Antes de reescrever: `rg -n "CLAUDE|README" testes/`.
- O bloco ``` do README na seção Shopee com `python3 backup_banco.py --motivo shopee` é EXECUTADO por 3 testes (cópia íntegra, banco inexistente, restauração de ponta a ponta). O README tem de manter esse bloco com exatamente esse comando. Os testes rodam com `cwd=RAIZ` (onde está o `backup_banco.py`) e `ACHADINHOS_DB` numa pasta temporária; passe SEMPRE o env, senão o comando atinge o `achadinhos.db` real. Os backups caem em `<pasta do banco>/backups`.
- Seção Shopee do README: exatamente 2 blocos com `atualizar_precos.py shopee`; `**Primeira vez:**` e `**Depois, a aba inteira:**` até 400 caracteres antes de cada um. A fatia `### Reverter`..`## Plugin do Chrome` é lida: não ponha seção nova entre elas.
- CLAUDE.md exige: `conferir --por-item`, `shopee --cat ABA [--max-chamadas N]`, `shopee|<dia>|item|<shopId>.<itemId>`, `fonte_shopee_item`, `20 sem o produto pedido`, `shopee|<dia>|tentado|...`; proíbe `fonte_shopee_api` e `ainda não tem a credencial`.
- O `verificar.py --rapido` leva ~2 min; o único vermelho de 09/11 era `garimpo/test_qa_entrega1` (sem `unittest.main()`, outra frente).
