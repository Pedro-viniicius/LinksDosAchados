---
name: testes-disparo-tela
description: Como rodar e depurar as páginas de teste da tela Disparo (disparo-qa e disparo-integracao), mutantes do index.html e armadilhas já vistas
metadata:
  type: project
---

Verificado em 2026-11-03 (etapa 5 do plano disparo-automatico).

**Páginas** (o servidor só serve `/testes/[a-z0-9-]+.test.html`: nada de underscore no nome)
- `testes/disparo.test.html` (dev, 71): servidor falso em memória para `/api/disparo/*` e `config/templates`; roda contra qualquer servidor, inclusive o real 8765 (só GET).
- `testes/disparo-qa.test.html` (QA, 34): mesma base e mesmo falso. Gerada copiando o cabeçalho/harness do arquivo do dev: quando o dev mudar o harness (ex.: `restaurar`, toasts), copie de novo, senão tudo falha em "voltar às ofertas". Um formulário sujo agora pede confirmação ao mudar de hash: chame `W.eval('marcarSujo(false)')` antes de navegar.
- `testes/disparo-integracao.test.html` (QA, 12): SEM falso, grava de verdade. Guarda: recusa 8765 e banco com número/regra. Cada rodada precisa de banco novo: copiar o migrado, `ACHADINHOS_DB=<c> ACHADINHOS_DISPARO=0 ACHADINHOS_PORTA=8767 python3 servidor.py`, `PORTA=8767 node testes/rodar.mjs disparo-integracao`.

**Armadilhas do produto**: `POST /api/disparo/*` devolve 200 (não 201). O slot de "Disparar agora" é `agora <ISO em segundos>`: dois disparos no mesmo segundo viram um slot só e o segundo cria 0 (espere ≥1,1 s no teste). `pulado` não ocupa vaga de `max_por_dia` nem de `limite_diario`; `enviado`, `pendente`, `enviando` e `incerto` ocupam. `max_por_dia < por_disparo` é aceito (vale o menor).

**Mutantes**: espelho no scratchpad (`servidor.py`, `disparo.py`, `migrar_categorias.py`, `buscas.json`, `index.html` mutado, `rodar.mjs`, páginas) com servidor na porta livre e `ACHADINHOS_DISPARO=0`. Quando o dev está editando, o espelho pega arquivos pela metade (56 falhas no teste mais simples): rode de novo depois que ele liberar. `pkill -f` com o padrão na própria linha de comando mata o shell: use o pid.
Equivalentes conhecidos: horário 25:00 (o campo `time` descarta), `templatesGarantidos` (GET antes do PUT já evita regravar), foco no diálogo (Cancelar vem primeiro no DOM).
