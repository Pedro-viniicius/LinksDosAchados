---
name: garimpo-correcoes-rodada1
description: Correções R1-R5, R9, S1, S4, S5, S6, S8, S9 do garimpo feminino (portão da sonda-base, erro_permanente, sinais com nohup, prctl, pty, surrogate com chr, mutantes)
metadata:
  type: project
---

Rodada 1 de correção da triagem do MVP (2026-11-06):

- `K.erro_permanente(codigo, http)` recebe campos, não a exceção: classifica `ErroApi`, linha de `medicoes` e linha de `requisicoes`. Linha gravada com 200 + código é permanente; limite (10030/429) nunca é: sem isso, consulta em `erro` que bate 10030 na retomada viraria "recusada de vez" pelo último registro.
- A consulta recusada de vez não tem status próprio (esquema fixo): o motor decide pelo último pedido dela em `requisicoes`.
- Sonda-base = `limit.20`, primeira da rodada. Reordenar não muda a contagem (155 pedidos), mas muda `api.nomes()[:n]`. A falha com código É gravada (guarda a mensagem do Secret errado) e o `_a_refazer` a descarta ao carregar.
- `ApiRoteada.rajada` só conta depois da sonda `item`: numa rodada só de `--refazer-taxa` fica 0. Use `api.nomes()`.
- SIGHUP: respeite `SIG_IGN`, senão o handler desfaz o `nohup` da rodada longa. Com terminal fechado de verdade a tela dá EIO: o `Log` grava no arquivo antes do print e engole `OSError`. O código do processo sai 120 (flush final do Python), mas o log fecha com `SAIDA=130`. Prova com `pty.openpty` + `start_new_session` + `TIOCSCTTY` no `preexec_fn`.
- Subprocesso que morre por sinal padrão (código antigo) não roda o `atexit` do `comum`: sobra `/tmp/teste-garimpo-*`. Apague as suas depois da execução "antes".
- `prctl` no import do `garimpo.py` vale para o processo do teste também (inofensivo). A prova do /proc tem controle: subprocesso sem proteção lê o marcador. Ordem no topo: teste por AST.
- Surrogate em teste: `chr(0xD83D)`, nunca o escape no literal (ver [[escapes-unicode-ferramentas]]).
- `CS.destino`/`CS.dono_ok` entraram em `NOMES_CS`/`ARIDADE` do test_cli.py.
- Mutantes: `<scratch>/m/` com `coletar_shopee.py`, `servidor.py`, `disparo.py`, `genero.py` e `tools/`; lista de (arquivo, trecho, troca, testes), confere `count == 1` do trecho. 92 mutantes, ~6 min. O `TestGitignore` pula na cópia (sem `.git`): o `.gitignore` se prova com a execução antes/depois.
- Secret errado numa retomada: `reconfirmar_base()` reenvia a base sem gravar, chamado no topo do `medir` e da `rajada` (pedido preguiçoso: tudo medido não gasta requisição). Toda retomada tem 1 pedido a mais, e `--max-req 1` numa retomada só gasta a reconfirmação. Resumo sem pedido (`pagina.teto` etc.) pode ser gravado antes dela, sempre de dado já bom. `Resultado.log` junta os logs da pasta e o `-2.log` ordena antes do `.log`: em 2ª rodada no mesmo segundo, `endswith('SAIDA=')` pega o log errado.

**How to apply:** ao escrever `fase_garimpar`/`fase_mapa` ou mexer no reconhecer. Relacionado: [[garimpo-reconhecer-testes]], [[garimpo-motor-testes]], [[garimpo-cli-testes]].

Etapa 8, parte A (depois do R1 real):
- **Dados reais em `tools/garimpo_feminino/`** (`garimpo.db`, `logs/`, `docs/`): nunca grave. Mutantes copiam `tools/` com `ignore_patterns('garimpo.db*', 'logs', 'docs', 'garimpo.lock')`. Para ensaiar sobre o estado real: `cp` do `garimpo.db` para pasta temporária (WAL vazio) e `rodar(pasta=copia, api=...)`.
- Validar todas as consultas contra `docs/schema.json` num script do scratchpad pega erro que a `ApiRoteada` não pega (ela responde a qualquer seleção).
- 10000: o `Cliente` repete 3 vezes; o `medir` grava o que persiste (com 200) e segue, porque pode ser determinístico (`pagina.100`); o `_nao_medida` o descarta ao carregar, menos na `taxa`. A rajada para pelo `registrar` (`_SistemaNaRajada`), antes das tentativas.
- `VERSOES` (sonda cuja consulta mudou): refaz sem `--refazer`, e a medição nova nasce com a versão. Fixture de teste com essas sondas precisa de `versao=`.
- `C.consulta_com_campos` é a única exceção ao "`_montar` só no módulo": aceita só nomes de `CAMPOS_PRODUTO`/`INFO_CAMPOS`.
- A `ApiRoteada` só conta a rajada com `limit` 20 depois da sonda `item` (a `pagina50` vem antes da rajada, com 50).
- "Antes" comportamental quando o teste novo importa nomes novos: copie o código, reverta as edições na cópia e acrescente só os nomes vazios.
