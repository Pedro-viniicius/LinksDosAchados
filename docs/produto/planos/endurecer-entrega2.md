# Plano técnico: endurecer a engenharia e a operação, Entrega 2 (hook de prompt, timers, corte do CLAUDE.md)
- Brief: não há. A origem é `docs/produto/planos/endurecer-engenharia-e-operacao.md`, seções "Entrega 2: recomendação e recorte" (linhas 148–173), "Perguntas em aberto" (134–140) e "ADR" (175–186), mais o pedido do lead de 17/11/2026.
- Data: 2026-11-17
- **Nada é implementado antes de o dono responder P4–P9.** As etapas que dependem de uma resposta dizem qual.
- **Decisões do dono (17/11/2026):** plano aprovado com as recomendações. P4 sim (regra genérica de formato, sem o formato real dos Secrets; o teste manual da etapa 8 confirma); P5 não; P6 fora deste plano; P7 sim; P8 ML no timer só como lembrete; P9 não.

## Objetivo e critérios de aceite
Fechar o endurecimento: um segredo colado no prompt não chega ao Claude, as rodadas sem credencial rodam sozinhas num agendador que sobrevive à sessão, e o `CLAUDE.md` volta a ser um mapa curto. Os números vêm do plano de origem.

- **CA10:** o hook `UserPromptSubmit` do projeto bloqueia o prompt que traz segredo, o que inclui o Secret solto do jeito que o dono copia do painel.
  - O prompt bloqueado não chega ao Claude, e a mensagem de bloqueio não repete o texto.
  - O hook nunca grava, nunca imprime o prompt nem o trecho achado e não usa a rede.
  - Os falsos positivos comuns passam: hash de commit, ASIN, id do ML, link `s.shopee.com.br`, URL longa e o `read -rs S; …="$S"` dos comandos.
- **CA11:** timers do systemd `--user` para o backup diário, a Amazon e o ML (este só enquanto o token valer).
  - A Shopee fica fora e não há caminho para ela entrar.
  - Nenhum arquivo de unidade, log ou ambiente da automação leva o Secret da Shopee nem o do ML.
  - Falha vira aviso na área de trabalho (`notify-send`) com texto fixo.
  - O instalador é versionado e reversível.
- **CA13:** o `CLAUDE.md` é cortado e os contratos por módulo passam para `docs/produto/referencias/`.
  - Antes do corte, nenhum teste lê mais o texto do `CLAUDE.md`.
  - O corte não perde informação: todo identificador entre crases do `CLAUDE.md` antigo continua num documento do projeto.
  - As seções "Segredos", "Regra do dono" e "Dado pessoal (LGPD)" ficam no `CLAUDE.md` sem perder nenhuma regra.

## Contexto atual (conferido em 17/11/2026)
- **Linha de base (dada pelo lead):** `python3 verificar.py` VERDE com 52 itens, no branch `endurecer-engenharia`.
  - Esse branch está 21 commits à frente da `main`, e a `main` não tem commit novo.
  - Na árvore há três arquivos modificados de outra frente (`SKILL.md`, `test_backup_banco.py`, `test_genero_servidor.py`) e `docs/produto/specs/black-friday.md` não rastreado. Nenhum deles entra nesta entrega.
- **Hook do Claude Code** (doc oficial `code.claude.com/docs/en/hooks`, lida hoje; versão instalada `2.1.326`):
  - O `UserPromptSubmit` não aceita `matcher` e dispara em todo prompt. O texto chega no campo `prompt` do JSON de entrada, com o colado (`[Pasted text #N]`) já expandido.
  - **Exit 2** "Blocks the prompt, so it never reaches Claude", e o stderr vira o `reason`. Mesmo no exit 2, o Claude Code lê o JSON da saída padrão. Se o JSON for inválido, o hook ainda bloqueia e usa o stderr.
  - Exit 1 ou outro código é erro que não bloqueia: o prompt passa. O mesmo vale para o JSON com `decision: "block"` que falha na validação quando o hook sai com 0.
  - **A doc avisa:** por padrão, a mensagem de bloqueio termina com `Original prompt:` e o texto, e essa mensagem vai para o transcript em disco. Com `hookSpecificOutput.suppressOriginalPrompt: true`, o texto sai da mensagem, mas "can still appear in local files such as the session transcript and your prompt history, so a blocking hook isn't a way to keep a secret off disk".
  - O hook protege contra o envio ao modelo, não contra a cópia local em `~/.claude/history.jsonl` e no transcript. O `~/.claude/paste-cache/` também existe (o que ele guarda: **não verificado**).
  - O tempo-limite padrão do `UserPromptSubmit` é de 30 s. Com tempo-limite estourado, o hook falha aberto, a menos que tenha `onFailure: "block"` (desde a 2.1.295). A forma exec (`command` + `args`, sem shell) aceita `${CLAUDE_PROJECT_DIR}`.
  - A versão mínima do `suppressOriginalPrompt` é **não verificada**, e o teste manual da etapa 8 a confirma.
- **Configuração do harness:** não existem `.claude/settings.json` nem `.claude/hooks/`. O `.gitignore:55` ignora só o `settings.local.json`. O `~/.claude/settings.json` não tem `hooks`.
  - Os agentes já usam hooks no próprio arquivo, por exemplo `.claude/agents/designer.md:9-15`.
  - `testes/test_servidor.py:307` já prova que `/.claude/settings.json` dá 404 no servidor.
- **Padrões de segredo já existentes:** `verificar.py:595-604` (`PADROES_SEGREDO`, com a exceção de falso de teste `_NAO_FALSO`), `verificar.varrer_linhas` (`:673-680`, que libera a linha com `# verificar: permitir`) e o resultado `Achado` (`:612`).
  - Os padrões exigem palavra-chave (`secret=`, `Bearer`, `APP_USR-`, `TG-`) e **não pegam um Secret colado sozinho**.
  - O `verificar.py` só usa a biblioteca padrão e tem a guarda `__main__` (`:960`), então importá-lo não roda nada.
- **Testes que leem o `CLAUDE.md`** (saída do `rg -n "CLAUDE" testes/`): só um.
  - `testes/test_shopee_por_item_qa.py:1400` abre o arquivo, e as afirmações sobre ele estão em `:1466`, `:1469-1473` e `:1608-1612`. Cada uma já tem uma gêmea sobre o README (`self.secao`) no mesmo teste, menos a `:1472` (`fonte_shopee_item`), que é fato de código.
  - `testes/test_servidor.py:309` só usa `/CLAUDE.md` como caminho proibido no estático e não lê o texto.
  - O `test_ml_api_qa.py:684` lê só o README. Ele aparece no `CLAUDE.md:27` como leitor do `CLAUDE.md`, o que está **desatualizado**.
- **Tamanho do `CLAUDE.md`:** 92 linhas, 5.296 palavras e 38.326 bytes. A seção "Equipe de agentes" (`:34` em diante) tem 816 palavras, e o "Contexto do projeto" tem cerca de 4.480. Linhas de até 4 KB (`:10`, `:12`, `:16`, `:27`). Hoje há uma referência só: `docs/produto/referencias/api-ofertas.md` (400 linhas).
- **Timers e linger** (`systemctl --user list-timers --all`, `loginctl show-user`):
  - Já existem `achadinhoturbo-backup.timer` (03:00, `Persistent=true`), `atualizar-ofertas-casamento.timer` e `relatorio-coletor.timer` (a cada 15 min, lê Turbo, contador e **Meta**: `~/.config/systemd/user/relatorio-coletor.service:2`).
  - Os outros projetos usam o padrão de unidade gerada por instalador, com o cabeçalho "Gerado por … Para mudar, rode o instalador de novo" (`achadinhoturbo-backup.service:1`), `UMask=0077`, `Nice=10` e `TimeoutStartSec`.
  - `Linger=no`: os timers só rodam com o dono logado, e o `Persistent=true` recupera na entrada o horário perdido. O backup do Turbo de hoje rodou às 07:48, no login.
  - O ambiente do gerenciador `--user` tem `DBUS_SESSION_BUS_ADDRESS` e nenhuma `ACHADINHOS_*` (conferido só pelos nomes). O `notify-send` está em `/usr/bin`. O `python3` é `/usr/bin/python3` 3.14.4, com `bs4` de `/usr/lib/python3/dist-packages`, então a Amazon roda sem venv.
- **Token do ML:** o access token vale 6 h, e a renovação manda `client_secret` (`ml_api.py:682`, `README.md:382`). Sem o Secret, sai com 2 (`ConfigFaltando`, `ml_api.py:651`). Assim, **"ML enquanto o token valer" quer dizer até 6 h depois de uma rodada manual com a chave**. Esse fato pesa na P8.
- **Operação:** `operacao/atualizar-ml.sh:25` sempre faz o `read -rsp` da chave e, na saída 2 sem chave, pede de novo (`:46-52`). Num timer, o stdin é `/dev/null`: o `read` devolve EOF e a rodada para com 2, mas o backup já foi feito (`:26`).
  - `operacao/atualizar-amazon.sh` não lê nada do teclado.
  - `testes/test_operacao.py:31-32` lista os scripts numa tupla fixa (`SCRIPTS`, `TODOS`) e alimenta a chave pelo stdin em pipe (`:264`), então detectar terminal com `-t 0` quebraria os testes.
  - `core.hooksPath` = `.githooks`. `~/atualizar-ml.sh` e `~/atualizar-shopee.sh` só fazem `exec` de `operacao/`.
- **Backups:** `backup_banco.py` lê só o banco vivo (`mode=ro`, `:162`) e a cópia nova, já em `journal_mode=DELETE` (`:164-178`). A rotação só apaga. Nenhuma etapa deste plano abre backup antigo. Se uma precisar, abre com `file:<caminho>?immutable=1`, porque os backups antigos estão em WAL e o `mode=ro` recria `-wal`/`-shm`.
- **Não existe `docs/produto/decisoes.md`.**

## Abordagens consideradas
| Tema | Abordagem | Prós | Contras | Risco |
|---|---|---|---|---|
| Como o hook bloqueia | **Exit 2 com JSON** (`decision: block` e `suppressOriginalPrompt`) **e** stderr fixo | Se o JSON falhar, o exit 2 ainda bloqueia | — | baixo |
| Como o hook bloqueia | Exit 0 com JSON | O caminho "normal" da doc | Se o JSON for inválido ou de versão velha, **o prompt passa** | alto |
| Padrões do hook | **Importar `verificar.PADROES_SEGREDO`** e somar só a regra do "bloco solto" no próprio hook | Uma fonte só para os padrões; o portão de commit não muda | O hook depende do `verificar.py` importar sem erro (se falhar, o hook falha aberto) | baixo |
| Padrões do hook | Copiar os padrões | Isolado | Duas listas que divergem | médio |
| Agendador | **systemd `--user`** com instalador versionado | Já é o padrão da máquina; `Persistent`; journal | Só com o dono logado (`Linger=no`) | baixo |
| Agendador | cron, cron da sessão ou rotina na nuvem | — | O cron não roda a hora perdida; o da sessão morre com ela; a nuvem não vê o banco (plano de origem `:154-156`) | — |
| Rodada automática | **`operacao/automatico.sh <tarefa>`**, um ponto de entrada que chama os scripts existentes e avisa | Os scripts de hoje mudam pouco; o aviso e as guardas ficam num lugar só | Um script a mais | baixo |
| Rodada automática | `ExecStart` direto nos scripts, com `OnFailure=` numa unidade de aviso | Nativo do systemd | O texto por código de saída depende de `$MONITOR_EXIT_STATUS` e é difícil de testar | médio |
| ML sem teclado | **Opção `--sem-chave` explícita** no `atualizar-ml.sh` | Testável; os testes de hoje não mudam | — | baixo |
| ML sem teclado | Detectar terminal (`-t 0`) | Sem opção nova | Quebra o `test_operacao.py` (chave no pipe) e muda o manual | médio |
| Corte do `CLAUDE.md` | **Seis referências por área** (abaixo) e mapa de uma linha por arquivo | Cada agente lê só a área que toca | Muito texto movido de uma vez | médio, só de docs |
| Corte do `CLAUDE.md` | Uma referência por arquivo `.py` | Granular | Uns 15 arquivos, vários de 3 linhas | baixo, mas é excesso |

## Decisão
- **CA10:**
  - script `.claude/hooks/segredo_no_prompt.py`, só com a biblioteca padrão, registrado em `.claude/settings.json` (versionado, porque é regra do projeto) na forma exec;
  - bloqueio por exit 2 com JSON e stderr;
  - falha aberta (sem `onFailure: "block"`), porque o hook protege contra acidente e um Python quebrado não pode travar o Claude no projeto inteiro (P4).
- **CA11:**
  - `operacao/automatico.sh backup|amazon|ml` e `operacao/instalar-timers.sh`, que gera `etiqueta-<tarefa>.{service,timer}` no padrão "Gerado por";
  - `--sem-chave` no `atualizar-ml.sh`;
  - `shopee` é recusada nos dois scripts.
- **CA13:**
  - primeiro, tirar o `CLAUDE.md` do teste;
  - depois, mover o detalhe para `docs/produto/referencias/`: `servidor.md`, `coletas.md`, `atualizar-precos.md` (inclui o `ml_api.py`), `disparo.md` (inclui o `genero.py`), `front.md` e `operacao.md` (`verificar.py`, `backup_banco.py`, `operacao/`, timers, hook, testes por área, `migrar_categorias.py` e `classificar_lista.py`), além do `api-ofertas.md`, que já existe.
- **Branch:** `endurecer-entrega2`, a partir do `endurecer-engenharia`. A Entrega 2 usa código que não está na `main`.

## Esquema e contratos
Não há esquema de banco nem migração.

**`.claude/hooks/segredo_no_prompt.py`** (etapa 2):
- **Entrada:** lê o stdin inteiro, faz o parse do JSON e pega `prompt` (str). JSON inválido, sem `prompt` ou com `prompt` que não é str: sai com 0, sem nada na saída.
- **Achados:**
  - `verificar.varrer_linhas('prompt', enumerate(prompt.splitlines(), 1))`, com o `verificar.py` carregado pelo caminho exato (`importlib.util.spec_from_file_location('verificar', <raiz derivada de __file__>/verificar.py)`), sem mexer no `sys.path` (rodada 1, S2); o achado com `liberado` não conta;
  - mais o **bloco solto**: um token de 32 a 64 caracteres `[A-Za-z0-9]`, com ao menos uma letra e um dígito, que não seja só hexadecimal (pula commit e sha256), solto numa frase, e cuja linha não tenha o marcador. Antes dele: início da linha, espaço, aspas (retas, crase ou curvas), `(`, `[`, `{`, `<`, `*` ou `:`; depois: fim da linha ou espaço, com no máximo uma sequência de pontuação de frase no meio (`.`, `,`, `;`, `:`, `!`, `?`, `)`, `]`, `}`, `>`, `*`, aspas). Preso a outra coisa (`<token>.png`, `https://x.com/<token>`, `x=<token>`, id com `-`/`_`) não conta (rodada 1, R3 = S1 = Q1); token com `-`/`_` fica como limite documentado;
  - se o `verificar.py` não carregar, o bloco solto roda sozinho, com o marcador como constante local, e bloqueia se achar algo; sem achado, falha aberta (saída 1) (rodada 1, S3);
  - o formato do Secret da Shopee e do ML (tamanho e classes) é **não verificado**: o dono confirma na P4 sem mostrar o valor, e a regra se ajusta.
- **Bloqueio:**
  - stdout: `{"decision":"block","reason":R,"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","suppressOriginalPrompt":true}}`;
  - stderr: R;
  - sai com 2.
- **Texto R (fixo):** "Bloqueado: o prompt parece ter um segredo (<tipos, sem trecho>). Ele não foi enviado ao Claude, mas pode ter ficado no histórico local do Claude Code. Se a chave for real, gere outra no painel. Para enviar mesmo assim (falso positivo), ponha `# verificar: permitir` na linha."
- **Garantias:** nenhum `open` para escrita, nenhuma rede, nenhum log; o prompt e o trecho achado nunca vão para a saída.
- **Registro em `.claude/settings.json`:** `{"hooks":{"UserPromptSubmit":[{"hooks":[{"type":"command","command":"/usr/bin/python3","args":["-I","${CLAUDE_PROJECT_DIR}/.claude/hooks/segredo_no_prompt.py"],"timeout":10}]}]}}`.

**`operacao/atualizar-ml.sh --sem-chave [aba …]`** (etapa 3):
- `--sem-chave` só vale como primeiro argumento e só pode aparecer uma vez.
- Com ele:
  1. nunca chama `read`;
  2. antes do backup, roda `rodar python3 ml_api.py conferir`. Se der 2, imprime `PAROU: o acesso ao Mercado Livre venceu (ou vence em menos de 5 min) e a rodada automática não usa a Chave secreta. Rode no terminal: operacao/atualizar-ml.sh` e sai com 2, **sem backup**. Com outro código diferente de 0, sai com ele, também sem backup;
  3. na saída 2 de uma aba, para com a mesma mensagem, sem pedir a chave.
- Sem a opção, o comportamento não muda (os testes atuais do `ML` passam sem edição).

**`operacao/automatico.sh <tarefa>`** (etapa 4):
- **Tarefa:** `backup`, `amazon` ou `ml`. Qualquer outra, inclusive `shopee`, sai com 2 e a mensagem "a Shopee não roda sozinha: precisa do Secret no terminal".
- **Guardas, nesta ordem e antes de tudo:**
  1. `ACHADINHOS_ML_SECRET`, `ACHADINHOS_SHOPEE_SECRET` ou `ACHADINHOS_SHOPEE_APP_ID` definida (`[[ -v ]]`): sai com 2, sem imprimir valor;
  2. **código em edição** (guarda larga, decisão do lead na rodada 1, R1 = S4 = Q2): `GIT_OPTIONAL_LOCKS=0 git --glob-pathspecs status --porcelain --untracked-files=normal -- '*.py' buscas.json operacao/` com qualquer linha na saída (todo `.py` da raiz, rastreado ou não, inclusive o `coletar_amazon.py` que o `atualizar_precos.py amazon` importa; o `buscas.json`; o `operacao/`; `testes/` e `index.html` ficam fora), ou o git com erro ou indisponível: sai com 1 e a mensagem "código com mudança sem commit: a rodada automática não roda código em edição" (premissa, veja os Riscos).
- **Tarefas:**
  - `backup`: `source comum.sh`, `iniciar_log automatico-backup` e `python3 backup_banco.py --motivo diario`;
  - `amazon`: `operacao/atualizar-amazon.sh`;
  - `ml`: `operacao/atualizar-ml.sh --sem-chave`.
- **Aviso:** com saída `r` diferente de 0 e `notify-send` no `PATH`, roda `notify-send -a Etiqueta "Etiqueta: <tarefa> parou (saída r)" "<texto fixo por código>; detalhes em logs/"`.
  - Textos: 2 no ML, "acesso vencido: rode operacao/atualizar-ml.sh no terminal"; 3, "bloqueio ou limite da loja: a próxima rodada retoma"; 4, "outra rodada da mesma loja estava no ar"; os demais, "erro: veja o log".
  - Nunca leva saída de comando. Falha do `notify-send` é ignorada. O script sai com `r`.

**`operacao/instalar-timers.sh [--remover] [tarefa …]`** (etapa 4):
- **Tarefas:** sem tarefa, vale `backup amazon ml`. `shopee` ou tarefa desconhecida saem com 2.
- **Destino:** `${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/etiqueta-<tarefa>.{service,timer}`.
- **Recusas:**
  - raiz do projeto com caractere fora de `[A-Za-z0-9/._-]`: sai com 2;
  - arquivo existente sem o cabeçalho na 1ª linha: sai com 1 e não sobrescreve.
- **Cabeçalho:** `# Gerado por operacao/instalar-timers.sh. Para mudar, rode o instalador de novo em vez de editar.`
- **`.service`:** `Type=oneshot`, `After=network-online.target`, `WorkingDirectory=<raiz>`, `ExecStart=<raiz>/operacao/automatico.sh <tarefa>`, `StandardInput=null`, `UMask=0077`, `Nice=10`, `IOSchedulingClass=idle`, `NoNewPrivileges=yes`, `TimeoutStartSec` (backup 15min, amazon 2h, ml 8h). **Nenhum `Environment=` com `ACHADINHOS_*`** e nenhum `import-environment`.
- **`.timer`:** `OnCalendar` de constantes no topo do script (premissa: backup `*-*-* 03:30`, amazon `06:00`, ml `06:45`), `RandomizedDelaySec=10min`, `Persistent=true` e `WantedBy=timers.target`.
- **Ativação:** `systemctl --user daemon-reload` e depois `enable --now etiqueta-<t>.timer`.
- **`--remover`:** `disable --now`, apaga só os arquivos com o cabeçalho e roda `daemon-reload`.

## Etapas
| # | Etapa | Arquivos | Verificação | Responsável | Grupo | Sensível | CAs |
|---|---|---|---|---|---|---|---|
| 1 | Tirar o `CLAUDE.md` do teste: apagar a leitura `:1400-1401` e as afirmações sobre `self.claude` em `:1466`, `:1469-1473` e `:1608-1612`, mantendo as gêmeas sobre o README (`self.secao`). A `:1472` vira fato de código: `A.FONTES['shopee'].__name__ == 'fonte_shopee_item'`. A `:1473` fica sobre `self.secao + self.atualizar`. Atualizar o comentário de `:1391` | `testes/test_shopee_por_item_qa.py` | `python3 testes/test_shopee_por_item_qa.py -v` (com os proxies em `127.0.0.1:9`); `rg -n "CLAUDE" testes/` mostra só `test_servidor.py:309` | dev | A | não | CA13 |
| 2 | Hook de prompt, conforme o contrato. Testes com subprocesso (`python3 -I` no script, JSON no stdin), cobrindo:<br>(a) prompt limpo e JSON inválido saem com 0 e sem saída;<br>(b) Secret solto, `secret = …`, `Bearer …`, `APP_USR-…` e AppID saem com 2, JSON válido com `suppressOriginalPrompt` e stderr com o tipo;<br>(c) **o valor nunca aparece** no stdout nem no stderr;<br>(d) passam: hash de 40 e de 64 hex, ASIN, `MLB…`, `https://s.shopee.com.br/…`, URL da Amazon de 300 caracteres, `read -rs S; ACHADINHOS_SHOPEE_SECRET="$S" …` e o id de arquivo do Telegram (com `-`/`_`);<br>(e) a linha com o marcador passa;<br>(f) prompt de 2 MB termina em menos de 2 s;<br>(g) o script não grava nada: rodado com `HOME` e diretório atual temporários vazios, os dois continuam vazios.<br>Os segredos falsos são **montados em tempo de execução** (por exemplo, `secrets.token_urlsafe`), nunca literais no arquivo: o `_NAO_FALSO` deixaria passar um valor com FALSO, e o portão acusaria um literal real | `.claude/hooks/segredo_no_prompt.py`, `testes/test_hook_prompt.py` | `python3 testes/test_hook_prompt.py -v`; `printf '{"prompt":"oi"}' \| python3 -I .claude/hooks/segredo_no_prompt.py; echo $?` dá 0 e nada mais; `python3 verificar.py --segredos --tudo` sai com 0 | dev | A | **sim** (segredo) | CA10 |
| 3 | `--sem-chave` no `atualizar-ml.sh`, conforme o contrato; docstring do topo atualizada. Testes novos na classe `ML`: com `entrada` que traz uma chave, ela **não é lida** (o `python3` falso registra o ambiente sem `ACHADINHOS_ML_SECRET`); `conferir` com 2 para sem backup; `conferir` com 0 faz backup e roda as abas; saída 2 numa aba para sem pedir; `--sem-chave` fora da 1ª posição sai com 2. Os testes existentes passam sem mudar | `operacao/atualizar-ml.sh`, `testes/test_operacao.py` | `bash -n operacao/atualizar-ml.sh`; `python3 testes/test_operacao.py -v` | dev | A | **sim** (segredo) | CA11 |
| 4 | `automatico.sh` e `instalar-timers.sh`, conforme os contratos. No `test_operacao.py`, os dois entram em `SCRIPTS`/`TODOS`, para valerem as regras estáticas. Classes novas com `python3`, `notify-send`, `systemctl` e `git` falsos no `PATH` e `XDG_CONFIG_HOME` temporário:<br>- automático: as tarefas chamam o que devem; `shopee` sai com 2; segredo no ambiente sai com 2 sem o valor na saída; código em edição sai com 1; aviso só com saída diferente de 0 e com o texto do código; `notify-send` ausente não quebra;<br>- instalador: gera as 6 unidades com o cabeçalho, `UMask=0077`, `StandardInput=null`, sem `ACHADINHOS_` e sem `Environment=`; recusa sobrescrever arquivo sem cabeçalho; `--remover` apaga só os seus; a ordem das chamadas ao `systemctl` está certa; `shopee` sai com 2 | `operacao/automatico.sh`, `operacao/instalar-timers.sh`, `testes/test_operacao.py` | `bash -n operacao/*.sh`; `python3 testes/test_operacao.py -v`; num `XDG_CONFIG_HOME` temporário, com `systemctl` falso, `systemd-analyze --user verify <unidades geradas>` sem erro (disponibilidade **não verificada**; se faltar, o revisor lê as unidades) | dev | B (depois da 3) | **sim** (automação, segredo e concorrência) | CA11 |
| 5 | Corte do `CLAUDE.md` (depois da 1 e da resposta à P7):<br>(a) criar `docs/produto/referencias/{servidor,coletas,atualizar-precos,disparo,front,operacao}.md` com o texto **movido**, não reescrito, de cada item de "Camadas e pastas" e de "Verificação". O histórico ("535 de 540", "liberada em 06/11", "decisão do lead em 08/11") vai para uma seção "Histórico" da referência da área. O que falta do item `api_ofertas.py` entra no `api-ofertas.md`;<br>(b) o `CLAUDE.md` fica com: produto e stack; mapa de uma linha por arquivo, com a marca **Regra de negócio** e o link da referência; as armadilhas que cruzam áreas (host da Shopee em 3 lugares, constantes numa linha, limite de navegações do `disparo.test.html`, `api_token.txt` nunca em teste, agentes não rodam `operacao/`, testes que leem o README); "Verificação" com `verificar.py`, o comando de um arquivo com proxies e o runner do front em 5 linhas; "Dados de teste"; e, **sem perder nenhuma regra**, "Regra do dono", "Dado pessoal (LGPD)", "Segredos" e a lista de arquivos do `designer`. A "Equipe de agentes" não muda;<br>(c) corrigir o `CLAUDE.md:27` (o `test_ml_api_qa` lê só o README) e escrever a regra "teste não lê o `CLAUDE.md`" | `CLAUDE.md`, `docs/produto/referencias/servidor.md`, `coletas.md`, `atualizar-precos.md`, `disparo.md`, `front.md`, `operacao.md`, `api-ofertas.md` | `wc -w CLAUDE.md` ≤ 2.300 (hoje 5.296); conferência sem perda, por script descartável no scratchpad (não versionado): cada `` `…` `` de `git show HEAD:CLAUDE.md` aparece em `CLAUDE.md` + `docs/produto/referencias/*.md` + `README.md` (a lista dos que faltam sai vazia ou cada item vem justificado no relatório); `python3 verificar.py` verde | dev | B | **sim** (regras de segredo e LGPD) | CA13 |
| 6 | Docs do hook e dos timers: no README, uma seção "Rodadas automáticas" dentro de "Operação" (instalar, remover, horários, ver o log e o journal, o que cada aviso quer dizer, por que a Shopee não entra) e uma nota do hook em "Portão de commit"; no `operacao.md`, os contratos das etapas 2–4; no `CLAUDE.md`, as linhas do mapa e uma frase em "Segredos" (o hook não tira o segredo do disco). Não mexer nos títulos lidos pelos testes (`## Atualizar os preços`, `### Shopee`, `### O que acontece`, `### Reverter`, `## Plugin do Chrome`, `## API oficial do Mercado Livre`) | `README.md`, `CLAUDE.md`, `docs/produto/referencias/operacao.md` | `python3 testes/test_shopee_por_item_qa.py`, `python3 testes/test_ml_api_qa.py` e `python3 verificar.py` verdes | dev | C | não | CA10, CA11, CA13 |
| 7 | Registrar o hook (depois da 2 e do "sim" do dono na P4): criar `.claude/settings.json` com o bloco do contrato. Ninguém mexe em configuração do harness sem o dono pedir: o lead mostra o JSON e o dono aplica ou autoriza | `.claude/settings.json` | `python3 -m json.tool .claude/settings.json`; teste manual na etapa 8 | lead + dono | C | **sim** (harness) | CA10 |
| 8 | Ações do dono, com o lead guiando:<br>(a) gerar um falso na hora, só com letras e dígitos, pelo comando do `README.md` (`python3 -c "import secrets,string;a=string.ascii_letters+string.digits;print(''.join(secrets.choice(a) for _ in range(40)))"`; o `secrets.token_urlsafe` quase sempre tem `-`/`_` e passa de propósito), colá-lo sozinho num prompt e conferir que vem o bloqueio **sem** o texto (isso confirma o `suppressOriginalPrompt` na 2.1.326) e que um prompt normal passa; depois, provar o formato do Secret real sem mostrá-lo: `read -rs S; printf '%s' "$S" \| python3 -I -c 'import json,sys;sys.stdout.write(json.dumps({"prompt":sys.stdin.read()}))' \| python3 -I .claude/hooks/segredo_no_prompt.py >/dev/null 2>&1; echo "saída $?"; unset S` (saída 2: o Secret real está coberto);<br>(b) `operacao/instalar-timers.sh` (ou só as tarefas aprovadas na P8);<br>(c) `systemctl --user start etiqueta-backup.service` e depois `ls -l backups/auto-diario-*` (0600) e `journalctl --user -u etiqueta-backup -n 20`;<br>(d) ver um aviso de verdade, por exemplo com `etiqueta-ml` e o token vencido;<br>(e) decidir o linger (P9) | — | `systemctl --user list-timers 'etiqueta-*'` lista os aprovados; o backup novo existe | dono | D | **sim** | CA10, CA11 |

**Ordem:**
- O grupo A (1, 2 e 3) não compartilha arquivos e pode rodar em paralelo.
- Depois vem o B: a 4 depende da 3 (`--sem-chave` e `test_operacao.py`), e a 5 depende da 1. A 4 e a 5 não compartilham arquivos.
- O C vem depois do B: a 6 depende da 5 (`CLAUDE.md` e `operacao.md`), e a 7 depende da 2.
- O D vem por último.
- As etapas 2, 3 e 4 esperam a P4 ou a P8. Só a 1 pode começar com a P7 ainda aberta, porque desacoplar o teste vale com ou sem corte.

## Pontos para o seguranca
- **Etapa 2:**
  - o prompt e o trecho achado nunca vão para o stdout, o stderr, um arquivo ou a rede;
  - o exit 2 vale mesmo com JSON inválido;
  - o `verificar.py` é carregado só de `<raiz>/verificar.py` (`spec_from_file_location`), sem tocar no `sys.path` (o `-I` tira o diretório atual);
  - o desempenho com prompt grande é linear, porque os padrões do `verificar.py` não têm retrocesso quadrático (conferir o `Bearer` e a atribuição com 2 MB);
  - a falha aberta é a decisão (P4).
- **Etapa 3:** com `--sem-chave`, nenhum caminho chega a um `read`, e a chave não entra nem quando o stdin traz texto.
- **Etapa 4:**
  - as unidades não carregam ambiente com segredo, e as guardas vêm antes de qualquer `source`/backup;
  - o aviso não leva saída de comando (títulos de produto ou mensagem do ML);
  - o journal recebe a mesma saída dos logs, sem segredo; conferir se algum CLI imprime token ou id do usuário no `conferir`;
  - a guarda de "código em edição" não segue symlink para fora;
  - a trava por loja (saída 4) separa o timer da rodada manual.
- **Etapa 5:** comparar as seções "Segredos", "Regra do dono" e "Dado pessoal" antes e depois, regra a regra.
- **Etapa 7:** o `.claude/settings.json` versionado só leva o hook, sem permissões nem variáveis.

## Riscos e como reverter
| Risco | Como reverter |
|---|---|
| O hook bloqueia prompt legítimo (falso positivo) | Marcador `# verificar: permitir` na linha; ajustar a regra do bloco solto; desligar removendo o bloco do `.claude/settings.json` |
| O hook passa a falhar (Python quebrado ou `verificar.py` com erro de sintaxe) e o prompt passa | Falha aberta é a escolha. O `verificar.py` vermelho já trava o commit pelo portão. Se o dono preferir falha fechada, use `"onFailure":"block"` (P4) |
| A versão do Claude Code ignora o `suppressOriginalPrompt` e a mensagem de bloqueio repete o segredo | O teste da etapa 8a pega isso antes do uso. Com o texto repetido, ele fica no transcript local: trocar a chave e atualizar o Claude Code |
| O timer roda código pela metade de uma sessão de dev | Guarda de "código em edição" (sai com 1 e avisa). Desligar: `operacao/instalar-timers.sh --remover` |
| A rodada automática migra o esquema sem ninguém olhar (`criar_banco`) | A Amazon e o ML fazem backup antes. Restaurar com `migrar_categorias.py --restaurar <auto-…>`, com o servidor parado |
| A rotação de 14 cobre poucos dias com 2 ou 3 backups automáticos por dia | Cerca de 5 a 7 dias. Para mais, use `--manter N` no `automatico.sh`, uma linha. Os backups manuais, sem `auto-`, nunca são apagados |
| O aviso diário de "ML vencido" vira ruído | P8 (b): `instalar-timers.sh --remover ml` |
| O corte perde regra ou contrato | Conferência sem perda da etapa 5 e revisão regra a regra. Reverter: `git revert` do commit da etapa 5 (é só doc) |

## Perguntas em aberto e premissas adotadas
- **P4 (dono): ligar o hook de prompt no projeto?** Recomendo **sim**:
  - em `.claude/settings.json`, versionado;
  - com bloqueio por exit 2 e JSON;
  - com falha aberta;
  - com a regra do bloco solto.

  Fato que muda a expectativa: o hook impede o envio ao Claude, mas **não** tira o texto do disco (`~/.claude/history.jsonl` e o transcript, segundo a doc). Segredo real colado continua pedindo troca da chave.

  Preciso também de dois dados, sem o valor: quantos caracteres e quais classes (maiúsculas, minúsculas, dígitos) têm o Secret da Shopee e o do ML.

  Não verificado: se as mensagens do canal do Telegram passam por esse hook (se passarem, também ficam protegidas).
- **P5 (dono): Shopee automática com o Secret no chaveiro do GNOME (`secret-tool`)?** Recomendo **não**:
  - reabre a regra "nunca em arquivo";
  - o chaveiro aberto no login fica legível por qualquer processo do usuário;
  - a rodada da Shopee tem o portão `conferir --por-item`, que pede olho humano.

  O plano não deixa caminho para ela: os dois scripts recusam `shopee`.
- **P6 (dono): conferência da Meta por `claude -p` disparado por timer?** Recomendo **fora deste plano**:
  - é de outro repositório;
  - já existe `relatorio-coletor.timer`, que lê a Meta a cada 15 min (`relatorio-coletor.service:2`);
  - o `claude -p` sem sessão, com MCP autenticado, é **não verificado**.

  Se ainda faltar alguma conferência, ela vira um plano no repositório do relatório.
- **P7 (dono): aprova o corte do `CLAUDE.md`** (de 5.296 para até 2.300 palavras, com seis referências novas e as regras de segredo, LGPD e afiliado inteiras)? Recomendo **sim**. Hoje, cada agente carrega cerca de 38 KB de contexto antes de começar, e a maior parte é contrato de módulo que ele não vai tocar.
- **P8 (dono, nova): ML no timer.** Fato: o token dura 6 h e só se renova com o Secret (`ml_api.py:682`), então a rodada automática quase sempre vai parar no `conferir` com 2.
  - (a) Timer diário que tenta e, com o token vencido, só avisa "rode `operacao/atualizar-ml.sh`". Funciona como lembrete e não gasta chamada nem backup.
  - (b) Sem timer do ML.

  Recomendo **(a)**, porque cumpre o CA11 e lembra da validade de 24 h dos preços. Se o aviso incomodar, o `--remover ml` desliga.
- **P9 (dono, nova): ligar o linger (`loginctl enable-linger`)?** Recomendo **não**:
  - o `Persistent=true` já roda na entrada o que se perdeu, como acontece hoje com o backup do Turbo;
  - sem sessão, o `notify-send` não teria a quem avisar.
- **Premissas:**
  - **horários:** 03:30 (backup), 06:00 (Amazon) e 06:45 (ML), constantes no instalador;
  - **branch** `endurecer-entrega2` a partir do `endurecer-engenharia`;
  - **guarda de "código em edição"** ligada (se o dono achar rígida, sai com uma linha);
  - **etapas 1 a 6 sem leitura de backup antigo.** Se alguma passar a ler, usa `immutable=1`.
- **Fora do escopo, para o lead registrar:**
  - o hook do `designer` (`.claude/agents/designer.md:15`) bloqueia menos arquivos que a lista de regra de negócio do `CLAUDE.md:26`: faltam `disparo.py`, `genero.py`, `api_ofertas.py`, `atualizar_precos.py`, `ml_api.py`, `coletar_ml.js`, `verificar.py`, `backup_banco.py` e `operacao/`;
  - o CA9 (texto de processo) já está no plano de origem e não tem etapa aqui.

## ADR
**ADR: rodadas automáticas por systemd `--user` e hook de prompt no projeto (2026-11-17).**
- **Contexto:** a operação dependia de o dono ou o Claude lembrarem de rodar. Um segredo colado no prompt iria ao modelo, e o `CLAUDE.md` passou de 38 KB.
- **Decisão:**
  - as tarefas sem credencial rodam por `etiqueta-<tarefa>.timer`, gerado por `operacao/instalar-timers.sh` e entrando por `operacao/automatico.sh`, que recusa segredo no ambiente, código em edição e a Shopee;
  - um hook `UserPromptSubmit` versionado bloqueia segredo com exit 2, reaproveitando os padrões do `verificar.py`;
  - os contratos por módulo vivem em `docs/produto/referencias/`, e o `CLAUDE.md` é o mapa.
- **Alternativas descartadas:**
  - cron, que não recupera o horário perdido;
  - rotina na nuvem, que não vê o banco;
  - Secret no chaveiro;
  - exit 0 com JSON, que deixa passar quando o JSON falha.
- **Consequências:**
  - o dono recebe aviso na área de trabalho quando uma rodada para;
  - os timers só rodam com ele logado;
  - testes não podem mais ler o `CLAUDE.md`;
  - quem muda um padrão de segredo no `verificar.py` muda também o hook.
