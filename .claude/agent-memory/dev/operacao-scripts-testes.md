---
name: operacao-scripts-testes
description: Scripts bash de operacao/ e testes/test_operacao.py: tee com Ctrl+C, lastpipe, python3/sleep falsos no PATH, buscas.json é aba→termos, mutantes
metadata:
  type: project
---

Vistas na etapa 7 do endurecer-engenharia-e-operacao (2026-11-09):

- **Ctrl+C com `exec > >(tee ...)`:** o tee está no mesmo grupo de processos e morre no SIGINT; `trap '' INT; exec tee` dentro da substituição de processo NÃO bastou (o script morreu com SIGPIPE). O que funciona: `tee -i` + `trap ao_interromper INT` no shell principal (com o laço `while read` do `rodar` rodando no shell principal por `lastpipe`; sem o trap, o bash morre no SIGINT durante o `read` builtin e perde o resumo). O handler retorna quando há comando no ar (o filho trata e devolve 130) e sai com 130 fora dele (leitura da chave, pausa).
- `read -rsp` interrompido por trap que faz `exit`: o bash restaura o eco do terminal (provado com `pty.fork` e `termios.tcgetattr` no master).
- Teste do Ctrl+C: `Popen(start_new_session=True)` e `os.killpg(p.pid, SIGINT)` imita o terminal. O `sleep` falso só dorme de verdade com `FALSO_SLEEP_REAL=1` (senão o teste da pausa padrão de 300 s dorme).
- `python3` falso no PATH (shebang com o `sys.executable`): registra argv, cwd e as variáveis de segredo presentes; `python3 -I ...` é repassado ao Python real por `os.execv` (é a leitura do `buscas.json`).
- O `buscas.json` é **aba → lista de termos** (o CLAUDE.md diz "termo → aba"); as abas são as chaves.
- Estático de "segredo só no ambiente": cada `$S`/`$A` não escapado tem de ser `-n`/`-z` dentro de `[[ ]]` ou parte de `VAR="$S" ... python3 `. Texto de instrução com `read -rs S` dentro de aspas confunde contagem de `read`: conte só `read` no começo da linha.
- Mutantes: runner copia `operacao/` e o teste para o scratchpad; ~30 mutantes; os do Ctrl+C demoram (timeouts de 20-30 s), rode em segundo plano.

- **Rastreio (S1, rodada 2):** `set +x` é o primeiro comando do `comum.sh`. Teste funcional: `bash -x <script>` e `SHELLOPTS=xtrace` no ambiente, marcador no stdin; prove que o rastreio estava ligado com `^\+ source .*/operacao/comum\.sh$` no stderr (não com a linha do `set +x`, que só existe depois da correção). Sem o `set +x`, o `[[ -z $A || -z $S ]]` e o `VAR="$S" python3` saem expandidos no log. O estático aceita `set +x` e recusa `set -x`, `-o xtrace`, `SHELLOPTS=`, `bash -x` (até em comentário).

**How to apply:** ao mexer em `operacao/*.sh` ou escrever outro script bash com log por tee e segredo. Relacionado: [[backup-banco-testes]], [[trava-rodada-testes]].
