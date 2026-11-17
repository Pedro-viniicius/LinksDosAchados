---
name: testes-entrega2-hook-timers
description: Entrega 2 do endurecimento (hook de prompt, --sem-chave, automatico.sh, instalar-timers.sh, corte do CLAUDE.md): test_entrega2_qa.py, Q1/Q2 baixos abertos, CA13 sem perda, mutantes e armadilhas
metadata:
  type: project
---

Arquivo do QA: `testes/test_entrega2_qa.py` (20 testes, ~7 s; `python3 testes/test_entrega2_qa.py -v` ou `Classe.metodo`). Importa `test_hook_prompt` (Base, gerar, rodar, URLSAFE) e `test_operacao` (BaseAutomacao: python3/git/notify-send/systemctl falsos no PATH). Classes: HookBordas, HookDesempenhoEFalsosPositivos, AutomaticoBordas (git de verdade em repo temporário, rastreio `bash -x`/SHELLOPTS), InstaladorBordas.

Achados da rodada 1 (17/11/2026), ambos baixos; RODADA 2 (17/11/2026): corrigidos, Q1/Q2 verdes, `verificar.py` VERDE com 54, sonda de regex (2 MB em ~0,02 s, 7 formas) sem falso positivo novo, guarda larga trava `coletar_shopee.py`/módulo novo e não trava `index.html`/`testes/` (teste adaptado preserva a intenção). Descrição original:
- Q1: bloco solto exige espaço/aspas/fim de linha dos dois lados; segredo com `.`/`,`/`;`/`!`/`?`/`)` colado ou entre `(..)`, `[..]`, `**..**`, `“..”` passa. Teste: `HookBordas.test_segredo_solto_com_pontuacao_de_frase_bloqueia`. Correção validada em cópia (28 testes do dev + os meus verdes, `.png` continua passando): `RE_BLOCO = (?<![^\s'"`(\[*<“])[A-Za-z0-9]{32,64}(?![^\s'"`.,;:!?)\]*>”]|[.,;:!?)\]*>”]+[^\s'"`.,;:!?)\]*>”])`.
- Q2: guarda de "código em edição" do `automatico.sh` não lista `coletar_amazon.py`, que `atualizar_precos.py amazon` importa (fonte_amazon_busca, linha ~384). Teste: `AutomaticoBordas.test_cada_arquivo_que_a_rodada_da_amazon_executa_trava_a_guarda`. Correção: pôr `coletar_amazon.py` no `git diff` (e no GIT_GUARDA/README/operacao.md/test_operacao).

Riscos aceitos (sem teste): Secret só hexadecimal (qualquer comprimento) ou com `-`/`_` passa no bloco solto (formato real dos Secrets nunca foi verificado, P4); hook sem tratamento de stdout/stderr fechado (exit 1 = prompt passa; Claude Code usa pipes); arquivo novo não rastreado não trava a guarda do git (só importa se um tracked o importar, e aí o tracked mudou); logs de `automatico-*` e `atualizar-*` sem rotação.

CA13 (corte do CLAUDE.md) conferido sem perda por script descartável (scratchpad): 520 identificadores entre crases do `git show HEAD:CLAUDE.md` todos em CLAUDE.md+referencias+README (também com fronteira de palavra); números e trechos entre aspas idem; "Equipe de agentes" byte a byte igual; "Regra do dono" e "LGPD" com a mesma contagem de palavras; "Segredos" = antigo + 2 frases. `rg "CLAUDE" testes/` só acha `test_servidor.py:309` (caminho proibido). Teste que leia o CLAUDE.md agora é proibido pelo próprio CLAUDE.md: não escreva um para conferir links.

Mutantes mortos (16/16): sem `exec </dev/null` (automatico e --sem-chave), sem `unset` do segredo, aceita shopee, eco do valor, backup antes do conferir, `e_meu` sempre verdadeiro, PassEnvironment na unidade, `--remover` apagando `.service.d` (só o meu teste mata), hook saindo com 1/sem suppressOriginalPrompt/marcador liberando prompt todo/aceitando só hex/limite 33/JSON inválido bloqueando.

Armadilhas:
- Rodar mutantes em background (`&`) num shell não interativo deixa SIGINT ignorado e derruba `test_ctrl_c_*` do `test_operacao` (15 falhas falsas). Faça `signal.signal(SIGINT, default_int_handler)` no runner de mutantes.
- NUNCA rode o `verificar.py` com `nohup` ou em `&` de shell não interativo: SIGHUP/SIGINT ignorados derrubam os testes de sinal do garimpo (`test_cli`, `test_reconhecer`, 3 falhas falsas que passam em primeiro plano). Use `run_in_background` da ferramenta sem `nohup`, ou rode em primeiro plano.
- NUNCA `pkill -f <nome do script>` dentro do Bash da ferramenta: o padrão casa com a própria linha do shell e mata a chamada (exit 144). Use PID.
- O scratchpad é compartilhado entre agentes (há pastas de outras sessões): use nomes próprios e não apague o que não criou.
- Hook: medir 2 MB em bytes (`len(prompt.encode())`), não em caracteres.
- `systemd-analyze --user verify` com XDG_RUNTIME_DIR de caminho longo imprime avisos "File name too long" das unidades do sistema (ruído); só o que cita as nossas unidades importa.

- NUNCA importe o hook por `sys.path.insert` + `import` de uma sonda: o `.pyc` nasce em `.claude/hooks/__pycache__` antes do `sys.dont_write_bytecode` valer e derruba `test_hook_no_repositorio_real_nao_cria_arquivo` no `verificar.py` (falha falsa). Use `python3 -B` ou `importlib` com `sys.dont_write_bytecode=True` antes.
