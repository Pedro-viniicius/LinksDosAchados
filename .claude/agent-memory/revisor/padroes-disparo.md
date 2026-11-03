---
name: padroes-disparo
description: O que conferir no disparo.py (regras/fila/agendador): atualização parcial que revalida tudo, conferência de URL por heurística de TLD, paridade buildMsg x montar_mensagem por fuzz próprio
metadata:
  type: feedback
---

Achados e métodos das etapas 1 a 4 de disparo-automatico (2026-11-03). Os itens 1 e 2 foram corrigidos na rodada 2 e ficam aqui como pontos de regressão:
1. **`atualizar_*` mescla e valida o objeto inteiro.** Um PUT `{"ativa":0}` falha com 400 quando o template da regra foi apagado do `config.templates`, e o agendador manda justamente "escolha outro template". Corrigido com `conferir_template='template' in novos`. Em mudanças futuras, confira se pausar continua sem depender do que não mudou.
2. **Conferência de URL (CA4) com lista fixa de TLDs** (`_TLDS_SOLTOS`). Um domínio solto com TLD fora da lista passa: no banco real aparece "Andro.id". Para medir, troque `_TLDS_SOLTOS` por um objeto com `__contains__` sempre verdadeiro e rode sobre o banco em `mode=ro`. Com isso, 13 de 5.250 itens seriam recusados (nomes ofuscados como "i.Phone"). Na rodada 2, a detecção virou token a token, sem lista de TLDs, e toda candidata tem que ser igual ao `url` do item. Ficaram 14 de 5.250 itens recusados por modelo, e o pior caso do `_escolher` (todas as mensagens recusadas) leva cerca de 0,3 s sob o lock. Para sondar desvios, use um roteiro de casos como golpe。com, U+200B, e-mail, IDN, wa.me e link colado no texto.
3. **Paridade:** extraia o `buildMsg` com `awk '/^function buildMsg/,/^}/'` e o `const LOJA`, troque por `var`, rode no Node e compare com `montar_mensagem`. Funcionou com 4.000 casos aleatórios (`$&`, `$'`, U+FEFF, U+200B, U+2028, `data` nulo) e 0 divergência.
3b. **Montagem com teto (rodada 3):** `montar_mensagem(..., LIMITE_MONTAGEM)` soma o tamanho antes de expandir `` $` ``/`$'`. Para provar paridade, compare a versão com limite e a sem limite no fuzz (0 divergência) e meça o pico com `tracemalloc`. A detecção passou a usar NFKC, ponto médio e duas leituras dos `Cf`; o roteiro `r3.py` do scratchpad tem os casos que devem passar (R$ 1.249.999,90, v1.2.3, `Fone · JBL`, emoji com ZWJ).
4. **Mutantes:** copie `servidor.py`, `disparo.py`, `index.html`, `testes/test_disparo.py` e `testes/mensagens.test.html` para o scratchpad. O teste usa `RAIZ` = pasta pai.

**Why:** quem testou só com regra válida não vê o 400 do item 1. E o item 2 depende de dado real.
**How to apply:** em mudanças futuras do `disparo.py` (entrega 2, transporte automático), repita o fuzz de paridade e a medição de URL. Confira também se o `_LOCK` continua cobrindo o `enviar()` (hoje ele fica preso durante o envio). Ver [[revisao-ambiente]].
