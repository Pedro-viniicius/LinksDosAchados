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
- O `buscas.json` é **aba → lista de termos**; as abas são as chaves.
- Estático de "segredo só no ambiente": cada `$S`/`$A` não escapado tem de ser `-n`/`-z` dentro de `[[ ]]` ou parte de `VAR="$S" ... python3 `. Texto de instrução com `read -rs S` dentro de aspas confunde contagem de `read`: conte só `read` no começo da linha.
- Mutantes: runner copia `operacao/` e o teste para o scratchpad; ~30 mutantes; os do Ctrl+C demoram (timeouts de 20-30 s), rode em segundo plano.

- **Rastreio (S1, rodada 2):** `set +x` é o primeiro comando do `comum.sh`. Teste funcional: `bash -x <script>` e `SHELLOPTS=xtrace` no ambiente, marcador no stdin; prove que o rastreio estava ligado com `^\+ source .*/operacao/comum\.sh$` no stderr (não com a linha do `set +x`, que só existe depois da correção). Sem o `set +x`, o `[[ -z $A || -z $S ]]` e o `VAR="$S" python3` saem expandidos no log. O estático aceita `set +x` e recusa `set -x`, `-o xtrace`, `SHELLOPTS=`, `bash -x` (até em comentário).

- **`--sem-chave` (entrega2, etapa 3, 2026-11-17):** provas que funcionaram: (1) `BASH_ENV` apontando para um arquivo que define a função `read` (sobrepõe o builtin no bash não interativo do script) e registra cada `read -rsp`, com controle no modo manual; (2) `FALSO_LER_STDIN=1` faz o falso gravar o stdin que receberia: sem o `exec </dev/null`, o 1º filho (`python3 -I` do `abas_validas`) já come a chave. `read -p` não mostra o prompt fora de terminal: a ausência do texto do prompt na saída NÃO prova nada.
- Estáticos que travam a forma do script: `fazer_backup ml` e `iniciar_log` precisam estar na coluna 0 (o teste procura `\nfazer_backup ml\n`); o 1º `read -rsp` do arquivo (inclusive em comentário) tem de vir depois do `iniciar_log`; nada de "tee", "/tmp" ou "bash -x" nem nos comentários; `read` fora do começo da linha precisa de aspas antes.

- **Timers (entrega2, etapa 4, 2026-11-17):** `notify-send`, `git` e `systemctl` existem de verdade em `/usr/bin`: o falso tem de vir antes no PATH, e "programa ausente" só se prova com uma pasta de symlinks de `/usr/bin` e `/bin` sem ele (`bin_sem`). O falso lê a fila `saidas` só no `python3`; os outros, `saidas-<prog>` (sem arquivo, sai com 0). `FALSO_LISTAR` registra o `listdir` das unidades em cada chamada do `systemctl` (prova "gravou antes do daemon-reload").
- `systemd-analyze --user verify` (systemd 259) funciona sobre unidades numa pasta temporária, mas exige `XDG_RUNTIME_DIR` (sem ele: "Failed to initialize manager"); com um temporário, imprime avisos de sockets do sistema ("File name too long") e sai com 0. Filtre as linhas com `etiqueta-`. Ele confere se o `ExecStart` existe e é executável.
- Mutantes mostraram redundância: `command -v notify-send` antes do `timeout ... || true` e `command -v git` antes de `! git diff` (127 já dispara a guarda) eram equivalentes; saíram.
- Os estáticos valem para `SCRIPTS = RODADAS + AUTOMACAO`: o 1º comando do `automatico.sh`/`instalar-timers.sh` é `set +x` (não o `source`), e nenhum dos dois pode ter "read" como palavra em linha de código (use `head -n 1` para ler a 1ª linha de arquivo).
- Armadilha de ferramenta: código Python escrito por heredoc bash com `'EOF'` guarda `\\n` literal; só use `\\n` quando o texto passa por uma string Python de substituição.

- **Guarda de código em edição (rodada 1, 2026-11-17):** `git --glob-pathspecs status --porcelain --untracked-files=normal -- '*.py' buscas.json operacao/`, saída vazia ou para. Com `GIT_LITERAL_PATHSPECS=1` no ambiente, a forma `':(glob)*.py'` vira literal e NÃO acha nada (falha calada); com `--glob-pathspecs` o git sai com 128 (fail closed). Em glob, `*` não passa de `/` (só a raiz). O falso de `git` só controla a saída: "saída 0 com linhas" só se prova com git real. Entre subTests com arquivo novo, `git clean`; com pathspec de pasta (`testes/`) ele pode levar a pasta: recrie.

**How to apply:** ao mexer em `operacao/*.sh` ou escrever outro script bash com log por tee e segredo. Relacionado: [[backup-banco-testes]], [[trava-rodada-testes]].
