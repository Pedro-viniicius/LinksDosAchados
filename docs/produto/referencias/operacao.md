# Referência: operação (`verificar.py`, `backup_banco.py`, `operacao/`, timers, hook de prompt, `migrar_categorias.py`, `classificar_lista.py` e testes)

Contrato dos módulos, movido do `CLAUDE.md` em 17/11/2026 (plano `docs/produto/planos/endurecer-entrega2.md`, etapa 5). O `CLAUDE.md` guarda o mapa, as armadilhas que cruzam áreas, o resumo da verificação e as regras de segredo, de LGPD e de afiliado, que valem aqui também. Os testes do front estão em `docs/produto/referencias/front.md`.

## `verificar.py`

**Regra de negócio.** Plano `docs/produto/planos/endurecer-engenharia-e-operacao.md`.

- A verificação única e o portão de commit (só biblioteca padrão; não importa o `servidor.py` nem abre o `achadinhos.db`, exceto a cópia do `--front`).
- A 8765 (servidor do dono) só é tocada pelo `--servidor`, que só lê.
- `python3 verificar.py` é a definição de "verde": `py_compile` dos `.py` e todos os testes Python (`testes/` e `tools/garimpo_feminino/testes/`) e Node, um arquivo por subprocesso e com timeout de 900 s, num ambiente isolado (sem Secret nem `ACHADINHOS_*` herdada, proxies em `127.0.0.1:9`, API v1 e agendador desligados, banco, progresso e tokens numa pasta temporária).
- Uma linha por arquivo na tela, a saída inteira em `logs/verificar-<data>/<nome>.txt` (`logs/` no `.gitignore`).
- Opções:
  - `--rapido` (só com `--dados-reais` pula `LENTOS`: `test_api_ofertas_qa` e `test_genero_qa`, lentos só sobre a cópia do banco real; sem ela, não pula nada);
  - `--dados-reais` (exporta `ACHADINHOS_TESTE_DADOS_REAIS=1`; sem ela, os testes que copiam o banco real pulam com motivo);
  - `--hora H` (relógio local às H horas: nenhum teste depende da hora do dia);
  - `--front` (também roda as páginas do front num servidor próprio na 8766, sobre uma cópia do banco em `mode=ro`; `--porta-front P`; recusa a 8765; precisa de Chrome e internet para 2 fotos reais; fora do `--rapido`);
  - `--servidor [P]` (só um GET em `/api/versao`: 0 em dia, 1 reiniciar ou fora do ar; não roda testes).
- Saídas: 0 verde, 1 falhou, 2 uso errado, 130 interrompido.
- Avisa, sem falhar, quando o ambiente difere do `requirements.txt` e quando o portão de commit está desligado.
- **Falha conhecida não é estado normal:** teste vermelho vira fixture, skip com motivo ou bug aberto na mesma rodada; nada é "pronto" com o `verificar.py` vermelho.

### Portão de commit

- `verificar.py --segredos --staged|--tudo` varre nomes proibidos (`api_token*`, `api_cabecalho*`, `ml_tokens.json*`, `*.db*`, `*.sqlite*`, `backups/`, `logs/`...) e padrões de segredo (inclusive AppID numérico; valor com FALSO, MARCADOR, TESTE, EXEMPLO ou o AppID falso `1800012345` é tido como falso de teste), sem nunca imprimir o trecho achado.
- `--pre-commit` (chamado por `.githooks/pre-commit`, que o dono liga com `git config core.hooksPath .githooks`) roda a varredura e, com código staged, o `--rapido`; teste não rastreado de outra frente não bloqueia.
- A linha com o marcador `# verificar: permitir` é liberada e listada no resumo.

## Hook de prompt `.claude/hooks/segredo_no_prompt.py`

**Regra de negócio** (segredos). Plano `docs/produto/planos/endurecer-entrega2.md`, etapa 2 (CA10); testes em `testes/test_hook_prompt.py`.

- Hook `UserPromptSubmit` do Claude Code, só biblioteca padrão. Bloqueia o prompt que traz segredo **antes de ele chegar ao Claude**.
- **Entrada:** o JSON do Claude Code no stdin; só o campo `prompt` (texto) importa. JSON inválido, sem `prompt` ou com `prompt` que não é texto: sai com 0, sem nada na saída.
- **Achados:** os `PADROES_SEGREDO` do `verificar.py` (carregado pelo caminho exato `<raiz>/verificar.py` com `importlib.util.spec_from_file_location`, sem mexer no `sys.path`; usados via `verificar.varrer_linhas`; quem muda um padrão lá muda o hook junto) mais o **bloco solto**: um token de 32 a 64 caracteres `[A-Za-z0-9]`, com ao menos uma letra e um dígito, que não seja só hexadecimal, solto numa frase (`RE_BLOCO`). Antes dele: início da linha, espaço, aspas (retas, crase ou curvas), `(`, `[`, `{`, `<`, `*` ou `:` (pega `Chave:X`). Depois: fim da linha ou espaço, com no máximo uma sequência de pontuação de frase no meio (`.`, `,`, `;`, `:`, `!`, `?`, `)`, `]`, `}`, `>`, `*`, aspas). Preso a outra coisa não conta: `<token>.png`, `https://x.com/<token>`, `x=<token>`. Fica de fora (limite documentado) um Secret com `-`/`_`, todo hexadecimal, ou com menos de 32 ou mais de 64 caracteres; com palavra-chave (`secret=`), é pego pelos padrões. O formato real dos Secrets da Shopee e do ML não foi verificado: a regra é genérica (decisão do dono, P4). Passam: hash de commit (40 e 64 hex), ASIN, `MLB...`, `https://s.shopee.com.br/...`, URL longa, `read -rs S; ...="$S"` e o id de arquivo do Telegram. A linha com `# verificar: permitir` é liberada.
- **Bloqueio:** stdout com `{"decision":"block","reason":R,"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","suppressOriginalPrompt":true}}`, o mesmo R no stderr e **saída 2** (bloqueia mesmo se o Claude Code não aceitar o JSON). R é fixo e diz só os tipos achados, nunca o trecho.
- **Falha aberta** (decisão P4): se o `verificar.py` não carregar, a regra do bloco solto roda sozinha (com o marcador como constante local, igual ao `verificar.MARCADOR`) e bloqueia se achar algo; sem achado, sai com 1 e uma mensagem fixa. Se a varredura quebrar, sai com 1 e outra mensagem fixa, e o prompt segue sem a conferência. Para falha fechada, `"onFailure":"block"` no registro.
- **Garantias:** nunca grava (nem `__pycache__`), não usa a rede e nunca põe o prompt ou o trecho na saída.
- **Limite:** o bloqueio impede o envio ao Claude, mas **não tira o segredo do disco**: o texto pode ficar no histórico e no transcript locais do Claude Code. Segredo real colado continua pedindo troca da chave.
- **Registro (etapa 7 do plano, feita pelo lead com o dono; o hook só vale depois dela, e o `.claude/settings.json` não existia na escrita desta referência):**

  ```json
  {"hooks":{"UserPromptSubmit":[{"hooks":[{"type":"command","command":"/usr/bin/python3","args":["-I","${CLAUDE_PROJECT_DIR}/.claude/hooks/segredo_no_prompt.py"],"timeout":10}]}]}}
  ```

  O `settings.json` versionado leva só o hook, sem permissões nem variáveis. Desligar: tirar o bloco.
- **Teste manual:** gere um falso na hora, só com letras e dígitos, cole-o sozinho num prompt e confira o bloqueio sem o texto (isso também confirma o `suppressOriginalPrompt` na versão instalada); um prompt normal passa. `python3 -c "import secrets,string;a=string.ascii_letters+string.digits;print(''.join(secrets.choice(a) for _ in range(40)))"`. Não use `secrets.token_urlsafe`: quase sempre tem `-`/`_` e passa. Para provar o formato do Secret real sem mostrá-lo, o comando do `README.md` ("Prova com o formato do Secret real"): saída 2 significa coberto.

## Testes

- Para um arquivo só: `python3 testes/<nome>.py -v` (rode com os proxies em `127.0.0.1:9`: `export http_proxy=http://127.0.0.1:9 https_proxy=http://127.0.0.1:9 ftp_proxy=http://127.0.0.1:9`; o `/api/fetch` acessa a rede de verdade, também ao testar mutantes ou código antigo).
- Node: `node --test testes/coletar_ml.test.mjs`, `coletar_ml_qa.test.mjs`, `api_ofertas.test.mjs` e `api_ofertas_qa.test.mjs` (sobem o `servidor.py` como subprocesso, com banco temporário e porta livre; o `ambiente()` aponta os proxies para `127.0.0.1:9`).
- Teste não lê o `CLAUDE.md`. Os que leem o `README.md` (`test_shopee_por_item_qa`, `test_ml_api_qa`): antes de reescrever um trecho, `rg -n "CLAUDE|README" testes/` e mantenha os literais exigidos.

### Arquivos de teste por área

- Servidor e operação: `test_servidor`, `test_servidor_qa`, `test_versao_servidor`, `test_trava_rodada`, `test_backup_banco`, `test_verificar`, `test_operacao`, `test_migrar_categorias(_qa)`, `test_classificar_lista(_qa)`.
- Coletas: `test_coletar_amazon(_qa)`, `test_coletar_shopee`, `test_shopee_qa`, `test_ordens_qa`.
- Disparo e público: `test_disparo`, `test_disparo_servidor`, `test_disparo_qa`, `test_front_constantes` (amarra hosts e lojas do `index.html` ao servidor e ao disparo), `test_genero`, `test_genero_qa`, `test_genero_servidor` (token temporário via `ACHADINHOS_API_TOKEN_ARQUIVO`; nunca crie `api_token.txt` real em teste).
- API v1: `test_api_ofertas`, `test_api_ofertas_servidor`, `test_api_ofertas_qa` (lenta só com `--dados-reais`), `test_api_ofertas_validade_qa` (trava de preço velho da v1), `test_confirmar_preco` (releitura e gravação do preço de uma oferta da Amazon, página falsa), `test_confirmar_preco_servidor` (rota, freio com relógio falso e log; um servidor em subprocesso cuja leitura bate no proxy morto e vira `falha_rede`).
- Atualização de preços: `test_atualizar_precos`, `test_atualizar_precos_qa` (as classes de dados reais copiam o `achadinhos.db` para uma pasta temporária, com backup em `mode=ro`, sem gravar nele, e só rodam com `--dados-reais`), `test_atualizar_precos_ml(_qa)`, `test_shopee_por_item_qa`, `test_ml_api`, `test_ml_api_qa`, `test_ml_api_catalogo(_qa)` (openers e relógio falsos, pasta temporária, proxies em `127.0.0.1:9`; `git check-ignore -q` aceita um nome só: para vários, use sem `-q`).

## `backup_banco.py`

**Regra de negócio.**

- `backup_banco.py --motivo M [--manter N]`: backup datado `backups/auto-<motivo>-AAAAMMDD-HHMMSS.db` (motivo `[a-z0-9-]{1,30}`; nunca sobrescreve; lê o banco em `mode=ro`, exige 2x o tamanho em disco livre, `integrity_check` ok e itens > 0; 0600 em pasta 0700, sem `-wal`/`-shm`, porque o banco tem telefones).
- A rotação guarda os 14 `auto-*` mais novos, contados juntos para todos os motivos (`--manter`, mínimo 3), e nunca apaga o que não começa por `auto-`.
- Saídas 0/1/2.
- O `--restaurar` do `migrar_categorias.py` devolve esse arquivo.

## `operacao/`

**Regra de negócio.** O uso está no `README.md`, seção "Operação".

- `operacao/` (`comum.sh`, `atualizar-ml.sh [abas...]`, `atualizar-shopee.sh [aba]`, `atualizar-amazon.sh [--produtos N]`): as rodadas de atualização de preço do dono, no terminal dele (agentes não as rodam: pedem a chave).
- Cada uma faz `backup_banco.py --motivo <loja>` (falhou: para com 1), grava o log em `logs/<nome>-AAAAMMDD-HHMMSS.log` e pede o Secret (e o AppID da Shopee) só por `read -rs`, sem `export`, apagado ao sair.
- No ML, aba por aba (padrão: todas do `buscas.json`; `--vincular 300 --max-chamadas 1500`), Enter vazio usa o token atual, saída 2 sem chave pede a chave e repete a aba, 3 espera `PAUSA_SEG` (padrão 300 s) e segue, 4 e 1 param.
- A Shopee faz `conferir --por-item`, teste de 10 itens e a aba.
- A Amazon roda `atualizar_precos.py amazon`.
- Testes: `test_operacao.py` (estático e com `python3` falso no `PATH`; `automatico.sh` e `instalar-timers.sh` entram nas regras estáticas, e os testes de comportamento usam `python3`, `notify-send`, `systemctl` e `git` falsos no `PATH` e um `XDG_CONFIG_HOME` temporário).

### `atualizar-ml.sh --sem-chave [aba ...]`

Plano `docs/produto/planos/endurecer-entrega2.md`, etapa 3 (CA11). É o modo da rodada automática; sem a opção, o comportamento não muda.

- Só vale como **primeiro** argumento e uma vez só; fora disso sai com 2.
- Nunca chama `read` e nunca usa a Chave secreta: `exec </dev/null` (nenhum comando, nem o `abas_validas`, come o que vier na entrada) e `unset ACHADINHOS_ML_SECRET` antes do primeiro comando.
- Antes do backup, roda `python3 ml_api.py conferir`. Saída 2 (token vencido, vencendo em menos de 5 min ou sem autorização): imprime `PAROU: o acesso ao Mercado Livre venceu (ou vence em menos de 5 min) e a rodada automática não usa a Chave secreta. Rode no terminal: operacao/atualizar-ml.sh` e sai com 2, **sem backup** e sem gastar chamada. Outro código diferente de 0: sai com ele, também sem backup.
- Saída 2 numa aba: para com a mesma mensagem, sem pedir a chave.
- O token do ML vale umas 6 h e só se renova com o Secret: a rodada automática do ML só trabalha até umas 6 h depois de uma rodada manual com a chave; fora disso é um lembrete.

### `automatico.sh backup|amazon|ml`

Plano `docs/produto/planos/endurecer-entrega2.md`, etapa 4 (CA11). O ponto de entrada dos timers; também roda à mão, para testar. Outra tarefa, inclusive `shopee`, sai com 2 e a mensagem "a Shopee não roda sozinha: precisa do Secret no terminal".

- **Guardas, nesta ordem e antes de qualquer log, backup ou rodada:**
  1. `ACHADINHOS_ML_SECRET`, `ACHADINHOS_SHOPEE_SECRET` ou `ACHADINHOS_SHOPEE_APP_ID` definida (`[[ -v ]]`, mesmo vazia): sai com 2, mostra só o nome da variável e a apaga antes do aviso;
  2. código em edição (guarda larga): `git --glob-pathspecs status --porcelain --untracked-files=normal -- '*.py' buscas.json operacao/` com qualquer linha na saída (mudança no índice ou fora dele, arquivo apagado ou novo não rastreado), ou o git com erro ou indisponível: sai com 1. Entram todos os `.py` da raiz (inclusive o `coletar_amazon.py`, que o `atualizar_precos.py amazon` importa, e um módulo novo ainda sem commit), o `buscas.json` e o `operacao/`; `testes/` e `index.html` ficam fora. O `--glob-pathspecs` faz o `*` não passar de uma pasta e faz o git recusar (128) um `GIT_LITERAL_PATHSPECS`/`GIT_NOGLOB_PATHSPECS` herdado, em vez de não achar nada. **É preciso commitar antes de instalar os timers**, senão todas as rodadas (inclusive o backup) param nesta guarda. O git roda com `GIT_OPTIONAL_LOCKS=0`.
- **Tarefas:** `backup` = `python3 backup_banco.py --motivo diario`, log em `logs/automatico-backup-*`; `amazon` = `operacao/atualizar-amazon.sh`; `ml` = `operacao/atualizar-ml.sh --sem-chave`. A entrada padrão é `/dev/null`.
- **Aviso:** com saída diferente de 0, `notify-send -a Etiqueta "Etiqueta: <tarefa> parou (saída N)" "<texto fixo>; detalhes em ..."`, com `timeout 15`; falha do `notify-send` ou ausência dele é ignorada. Textos: guarda 1, "segredo no ambiente: nada rodou" (em qualquer tarefa, inclusive o ML); guarda 2, "código com mudança sem commit: nada rodou"; 2 no ML, "acesso vencido: rode operacao/atualizar-ml.sh no terminal"; 3, "bloqueio ou limite da loja: a próxima rodada retoma"; 4, "outra rodada da mesma loja estava no ar"; os demais (e o 2 fora do ML), "erro: veja o log". **Nunca leva saída de comando** (pode ter título de produto ou mensagem da loja). O script sai com o código da tarefa.

### `instalar-timers.sh [--remover] [tarefa ...]`

Plano `docs/produto/planos/endurecer-entrega2.md`, etapa 4 (CA11).

- **Tarefas:** sem tarefa, `backup amazon ml`; `shopee` ou outra sai com 2, sem mexer em nada. Recusa `sudo` (2) e raiz do projeto com caractere fora de `[A-Za-z0-9/._-]` (2, porque o caminho vai sem aspas para o `ExecStart`).
- **Destino:** `${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/etiqueta-<tarefa>.{service,timer}`. A 1ª linha de cada arquivo é `# Gerado por operacao/instalar-timers.sh. Para mudar, rode o instalador de novo em vez de editar.` Arquivo existente sem ela (ou link simbólico): sai com 1 antes de gravar qualquer um e não sobrescreve nem apaga.
- **`.service`:** `Type=oneshot`, `After=network-online.target`, `WorkingDirectory` e `ExecStart=<raiz>/operacao/automatico.sh <tarefa>`, `StandardInput=null`, `UMask=0077`, `Nice=10`, `IOSchedulingClass=idle`, `NoNewPrivileges=yes`, `TimeoutStartSec` (backup 15min, amazon 2h, ml 8h). **Nenhum `Environment=`** e nenhum `import-environment`: a automação nunca leva segredo. O `After=network-online.target` não vale para unidades `--user`: sem rede na entrada da sessão, a rodada para com aviso e a próxima retoma.
- **`.timer`:** `OnCalendar` do `HORARIO` no topo do script (backup `03:30`, amazon `06:00`, ml `06:45`), `RandomizedDelaySec=10min`, `Persistent=true`, `WantedBy=timers.target`.
- **Instalar:** grava as unidades, `systemctl --user daemon-reload` e, por tarefa, `enable --now etiqueta-<t>.timer`. **`--remover`:** por tarefa, `disable --now`, apaga só os arquivos com o cabeçalho e `daemon-reload`; uma rodada em andamento não é interrompida.
- Sem linger (`Linger=no`), os timers só rodam com o dono logado; `Persistent=true` roda na entrada o horário perdido, e o aviso de área de trabalho só chega a quem está na sessão. Decisões do dono de 17/11/2026: Shopee fora, sem Secret no chaveiro, ML como lembrete, linger desligado.
- A trava por loja (saída 4) separa o timer de uma rodada manual da mesma loja. `systemd-analyze --user verify` sobre as unidades (precisa de `XDG_RUNTIME_DIR`) confere se o `ExecStart` existe.

## `migrar_categorias.py`

**Regra de negócio.** Plano: `docs/produto/planos/eletronicos-e-coleta-ml.md`.

- Reorganiza a coluna `cat` dos itens a partir de `buscas.json` + `ALIAS`, com `--dry-run`, backup verificado em `backups/`, `--sim`/prompt "sim" no banco real e `--restaurar` (só com servidor e coleta parados; devolve o banco INTEIRO, inclusive `numeros`/`regras`/`envios` do disparo).

## `classificar_lista.py` + `lista_whatsapp.json`

**Regra de negócio.**

- Movem os 74 itens de "Lista WhatsApp" para "Black Friday | Eletrônicos" com `busca` por subtema (`--dry-run`, `--sim`, `--desfazer` reverte só esses 74).
- Rodar logo depois do `migrar_categorias.py` e antes de cadastrar qualquer número no disparo.

## Histórico

- 17/11/2026: nenhum teste lê mais o `CLAUDE.md` (etapa 1 do plano `docs/produto/planos/endurecer-entrega2.md`); antes, o `test_shopee_por_item_qa` lia os dois arquivos. O `test_ml_api_qa` lê só o `README.md`.
- 17/11/2026: etapas 2 a 4 do mesmo plano (hook de prompt, `--sem-chave`, `automatico.sh` e `instalar-timers.sh`); docs na etapa 6. Decisões do dono: hook com regra genérica e falha aberta (P4), Shopee fora das rodadas automáticas (P5), ML no timer só como lembrete (P8), linger desligado (P9).
