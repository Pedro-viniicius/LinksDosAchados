---
name: docs-lidas-por-testes
description: Quais testes leem README.md (nenhum lê mais o CLAUDE.md desde 17/11) e que trechos exigem; o bloco de backup do README é executado; como conferir um corte de doc sem perda
metadata:
  type: project
---

Atualizado em 2026-11-17 (etapas 1 e 5 do `endurecer-entrega2`):

- **Nenhum teste lê o `CLAUDE.md`** (regra escrita nele). `test_servidor.py:309` só cita `/CLAUDE.md` numa lista de rotas 404. Leem o README: `test_shopee_por_item_qa.py` (`TestDocumentacao`) e `test_ml_api_qa.py` (`TestReadme`, seção "API oficial do Mercado Livre"). Antes de reescrever: `rg -n "CLAUDE|README" testes/`.
- Os contratos por módulo saíram do `CLAUDE.md` para `docs/produto/referencias/{servidor,coletas,atualizar-precos,disparo,front,operacao,api-ofertas}.md`; o `CLAUDE.md` é mapa (~1.950 palavras, teto 2.300).
- O bloco ``` do README na seção Shopee com `python3 backup_banco.py --motivo shopee` é EXECUTADO por 3 testes (cópia íntegra, banco inexistente, restauração de ponta a ponta). O README tem de manter esse bloco com exatamente esse comando. Os testes rodam com `cwd=RAIZ` e `ACHADINHOS_DB` numa pasta temporária; passe SEMPRE o env, senão o comando atinge o `achadinhos.db` real.
- Seção Shopee do README: exatamente 2 blocos com `atualizar_precos.py shopee`; `**Primeira vez:**` e `**Depois, a aba inteira:**` até 400 caracteres antes de cada um. A fatia `### Reverter`..`## Plugin do Chrome` é lida: não ponha seção nova entre elas.
- Conferir corte de doc sem perda: além de "todo `` `…` `` do antigo aparece nos novos", compare trechos de 4 palavras (shingles) do texto antigo contra os docs novos; o que sobra são só fronteiras de reordenação e as mudanças de propósito, fácil de revisar à mão.
- Etapa 6 do entrega2 (2026-11-17): a seção nova do README ("### Rodadas automáticas") entra como `###` dentro de "Operação", antes de "## Reorganizar abas"; nenhum teste lê esse trecho. O CLAUDE.md pode crescer ~110 palavras (2.060 de 2.300). Edição de doc por script Python no scratchpad com `assert t.count(ant) == 1` antes de cada troca evita substituir no lugar errado.
