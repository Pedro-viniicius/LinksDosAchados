---
name: hook-prompt-testes
description: Hook UserPromptSubmit (.claude/hooks/segredo_no_prompt.py) e testes/test_hook_prompt.py - prova de "não grava" por audit hook, __pycache__ do import, MARCADOR com '#', token_urlsafe x bloco solto, mutantes
metadata:
  type: project
---

Vistas em 2026-11-17 (etapa 2 de endurecer-entrega2):

- **Importar o verificar.py grava `__pycache__`** na raiz: o hook liga `sys.dont_write_bytecode` antes do import. Na raiz real o `.pyc` já existe e esconde o problema: a prova roda numa cópia (hook + verificar.py) sem `__pycache__` e compara a árvore antes e depois.
- **Prova de "não grava, sem rede, sem processo":** `python3 -I -c <wrapper>` com `sys.addaudithook` + `runpy.run_path(hook, run_name='__main__')`; evento `open` com modo `w/a/x/+` ou flags de escrita, e prefixos `socket.`, `subprocess.`, `os.mkdir`... Abra o arquivo de saída do wrapper ANTES de ligar o gancho e tenha um controle positivo (script que grava é acusado).
- O `MARCADOR` do verificar é `# verificar: permitir` (com `#`): o texto do plano dizia só `verificar: permitir`; a mensagem do hook usa `verificar.MARCADOR`.
- **`secrets.token_urlsafe(32)` tem `-`/`_` em ~75% das vezes**, e o bloco solto é só `[A-Za-z0-9]`: para testar o Secret solto, gere com `secrets.choice(letras+dígitos)`. A etapa 8a do plano manda colar um `token_urlsafe` (avisado ao lead).
- Mutante equivalente: tirar a exigência de letra (só dígitos já é "só hex"). Mutantes no `scratchpad/etapa2-hook/mutantes.py` (cópia por mutante: raiz/.claude/hooks, verificar.py, testes/); ~19 levam ~4 min.
- `test_hook_prompt.py` (28 testes, ~10 s) é achado sozinho pelo `verificar.py` (glob `testes/test_*.py`); o `py_compile` do verificar não cobre `.claude/hooks/`.

Rodada 1 (2026-11-17, R3/S1/Q1, S2, S3):
- `RE_BLOCO` agora aceita pontuação de frase e delimitadores de markdown: lookbehind `[^\s'"`(\[{<*“‘:]` e lookahead `[.,;:!?)\]}>'"`*”’]*(?:\s|$)`. O `:` à esquerda é o `Chave:X`. Custo linear: só o tamanho que fecha a sequência alfanumérica percorre a pontuação seguinte (2 MB de casos adversos < 0,05 s na regex).
- O verificar.py é carregado com `importlib.util.spec_from_file_location` (sem `sys.path`); prova: `socket.py` falso na cópia da raiz (o verificar importa socket e o hook não, antes dele).
- Com o verificar.py quebrado, o bloco solto ainda bloqueia (2); o teste antigo "quebrado sai com 1" mudou de propósito. A mensagem ERRO_PADROES mudou de texto.
- Fail-before: árvore no scratchpad com o hook antigo + verificar.py + o teste novo (o teste calcula RAIZ pelo próprio caminho).

**How to apply:** ao mexer no hook, nos `PADROES_SEGREDO` do verificar.py (o hook importa) ou registrar o hook (etapa 7). Relacionado: [[verificar-testes]].
