---
name: ml-api-testes
description: Armadilhas do ml_api.py (API oficial do ML: OAuth/PKCE, tokens 0600 com flock) e de testes/test_ml_api.py (openers falsos, processos concorrentes, paridade com o JS, mutantes)
metadata:
  type: project
---

Vistas nas etapas 1 a 3 de api-oficial-ml (2026-11-05):

- `git check-ignore -q a b c` FALHA (exit 128, "--quiet is only valid with a single pathname"). Com vários caminhos, use sem `-q` (exit 0 e lista os 3) ou um `-q` por arquivo. O comando do plano/lead vem com `-q`: relate.
- `HTTPError` falso guarda o corpo num BytesIO: reusar o MESMO objeto em várias respostas faz a 2ª leitura vir vazia (código some). Crie um novo por chamada (no teste do sondar, `erros` guarda `(status, corpo)`).
- Default de argumento é ligado na definição: `entrada=input`, `relogio=time.time` não pegam `mock.patch('builtins.input')`. Use `None` e resolva na chamada (`(entrada or input)(...)`, `self.opener or OPENER`).
- Prova de concorrência com 2 subprocessos: script auxiliar (string no teste, gravado no tmp) troca `M.OPENER` por um falso cujo "servidor" vive num JSON com flock próprio e anota eventos (`pediu-trava`, `post-inicio`, `post-fim`). A condição certa é "o outro pediu a trava ANTES do `post-fim`" (muitas vezes os dois pedem antes do `post-inicio`); exigir `ini <= t <= fim` deu falso negativo em ~50% das rodadas. ATRASO de 1 s no POST basta.
- Reler dentro do lock em processo único: thread + `M.travar` segurado pelo teste + espião em `M.ler_tokens` (Event) e gravar o par novo antes de soltar.
- Paridade do `formatar_preco` com o JS: `node -e <script> coletar_ml.js` (no `-e`, o arquivo é `process.argv[1]`), valores pelo stdin em JSON. vm precisa de `location` da lista, `localStorage`, `fetch`, timers. `round()` do Python ≠ `Math.round` (empate e 0.49999999999999994): use floor + `x - floor(x) >= 0.5`.
- Mutantes: copie `ml_api.py`, `coletar_amazon.py`, `coletar_shopee.py`, `coletar_ml.js`, `servidor.py`, `index.html`, `disparo.py`, `api_ofertas.py`, `genero.py` e o teste (o teste lê esses fontes). O `test_gitignore` pula fora de um repo git. O script de mutantes tem de restaurar o original num `finally`: um `assert` no meio deixou um mutante na cópia e contaminou a rodada seguinte.
- Mutantes equivalentes conhecidos: tirar o `st_size >` do `ler_tokens` (o `len(bruto) >` ainda recusa). Os filtros de código de erro são em dobro (`_codigo_do_corpo` e `ErroApi`/`SemPermissao`): cada um tem teste direto.

Rodada 2 (2026-11-05):
- `getpass.getpass` lê do `/dev/tty` se o processo tiver terminal de controle, MESMO com stdin em pipe: os testes com subprocesso + `stdin=PIPE` travariam no terminal do dono. Por isso `ler_colado` usa getpass só com `sys.stdin.isatty()`; fora disso, `input()`. O `Cli.rodar` troca `M.sys.stdin` por um `TerminalFalso` (isatty True) e mocka `getpass.getpass`; `builtins.input` fica como AssertionError.
- Prova de "sem eco" de verdade: `pty.openpty()` + `Popen(stdin/stdout/stderr=escravo, start_new_session=True)`; sem terminal de controle o getpass cai no termios do stdin (o pty) e desliga o eco. Leia o mestre com `select` até EIO. Com `input()`, o endereço volta na tela.
- Para provar que a suíte não trava num terminal: `script -qec "python3 testes/test_ml_api.py" /dev/null </dev/null`.
- Mutante de laço infinito (401 sempre + renovar sem limite) trava o runner: o mutante certo do S3 é zerar `self._renovou_por_401` no começo do `get`. No script de mutantes, use `timeout=` no subprocess. NUNCA `pkill -f <nome do script>`: casa com o próprio bash da ferramenta e mata o comando (exit 144).
- Exceção nova que precisa passar nos `assertRaises(M.RespostaInvalida)` do qa: subclasse (`RenovacaoInvalida(RespostaInvalida)`, saída 2). Cuidado com quem captura a base: o `_sonda` engolia; tem `except RenovacaoInvalida: raise` antes.
- A tabela de saídas do README é lida pelo qa com `^\| ([0-3]) \|`: linha `| 130 |` não quebra.

**How to apply:** nas etapas 4 e 5 (fonte `ml` do `atualizar_precos.py`, `coletar_ml.py`), que usam `Sessao`/exceções do `ml_api`. Relacionado: [[coletar-shopee-testes]], [[servidor-testes]].
