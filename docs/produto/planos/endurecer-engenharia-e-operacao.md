# Plano técnico: endurecer a engenharia e a operação
- Brief: não há; o pedido do lead de 09/11/2026 às 14:10 (slug `endurecer-engenharia-e-operacao`) faz as vezes dele.
- Data: 2026-11-09

**Corte:** o plano completo passaria de 250 linhas. A **Entrega 1 (proteção)** cobre CA1–CA8, CA12 e a parte barata do CA9 (etapa 0 e o texto da seção "Processo") e vem com as etapas detalhadas. A **Entrega 2 (processo e docs)** cobre CA9, CA10, CA11 e CA13: aqui só ficam a recomendação e o recorte, e ela ganha um plano próprio depois que o dono decidir as perguntas P4–P7.

## Objetivo e critérios de aceite
Reduzir o risco de perder trabalho ou dados, de regressão silenciosa e de vazar segredo, e tirar a operação da dependência de uma sessão do Claude.

- CA1: `python3 verificar.py` roda o `py_compile` e todos os testes Python (`testes/` e `tools/garimpo_feminino/testes/`) e Node num ambiente isolado. Imprime uma linha por arquivo e sai com código diferente de 0 se algo falhar. Opções:
  - `--rapido` pula os lentos;
  - `--front` sobe um servidor próprio na 8766 sobre uma cópia e nunca usa a 8765;
  - `--dados-reais` liga os testes sobre a cópia do banco real;
  - `--hora H` roda com o relógio local na hora H.
- CA2: nenhum teste depende da hora do dia. `verificar.py --rapido --hora 3` e `--hora 23` passam.
- CA3: nenhuma "falha conhecida". Teste de dado real vira fixture sintética ou fica atrás de `--dados-reais`, com skip e motivo impresso.
- CA4: o `atualizar_precos.py`, o `coletar_amazon.py` e o `coletar_shopee.py` (`buscas`/`importar`) têm trava por loja (flock sem espera). A 2ª rodada da mesma loja sai com **4** e mensagem clara, sem abrir o banco, o progresso nem os tokens.
- CA5: `backup_banco.py` faz backup com nome datado (`backups/auto-<motivo>-AAAAMMDD-HHMMSS.db`), confere com `PRAGMA integrity_check`, grava 0600 sem `-wal`/`-shm` e rotaciona só os próprios arquivos (fica com os 14 mais novos). Nunca sobrescreve. Os scripts operacionais usam esse utilitário.
- CA6: os scripts operacionais ficam em `operacao/` (Shopee, ML aba por aba, Amazon):
  - segredo só por `read -rs`, sem `export`, nunca em arquivo;
  - log datado em `logs/` (ignorada pelo git);
  - códigos de saída tratados: 3 espera e segue, 2 e 4 param.
- CA7: há portão de commit em `.githooks/pre-commit` (via `core.hooksPath`). Ele roda a varredura de segredos no que está staged e, se houver código staged, o `verificar.py --rapido`. Bloqueia o commit se algo falhar.
- CA8: `requirements.txt` com versões fixas. O `verificar.py` avisa quando o ambiente difere do manifesto.
- CA9: texto de processo pronto para o lead propor ao dono (seção "Processo"). Na Entrega 1, só a etapa 0 e a regra "falha conhecida não é estado normal".
- CA10, CA11 e CA13: ficam para a Entrega 2 (seção própria).
- CA12: o servidor registra na subida a versão do código. `GET /api/versao` diz se o código em disco mudou, e `verificar.py --servidor` avisa que é preciso reiniciar.

## Contexto atual
- **Linha de base** (`scratchpad/base/RESUMO`, 09/11 ~14:20): `py_compile` OK, 35 arquivos Python e 4 Node. Há 2 vermelhos:
  - `test_api_ofertas_qa` (200 s): `DadosReais.test_ca2_…` falha no título de `amazon:B0GL9FF7Q5`. O oráculo `_RE_PARECE_LINK` (`testes/test_api_ofertas_qa.py:80`, `[a-z0-9-]\.[a-z]{2,}` sem fronteira) acha "link" em `l.eb2gam1`, que o disparo não considera link.
  - `test_shopee_por_item_qa` (falha **nova**): `testes/test_shopee_por_item_qa.py:1469` exige o literal `conferir --por-item` no CLAUDE.md, que a mudança sem commit trocou por `conferir [--por-item]` (`CLAUDE.md:11`). É teste amarrado ao texto do CLAUDE.md. `testes/test_servidor.py` também lê o CLAUDE.md.
  - Lentos: `test_api_ofertas_qa` (200 s) e `test_genero_qa` (109 s); o resto soma cerca de 2 min.
  - Os testes do garimpo não estavam na linha de base: tempo e estado **não verificados**.
- **Hora do dia:** `testes/test_atualizar_precos.py:253` (`T07:00:00`) e `:418` (`T06:00:00`) caem no futuro de madrugada. O `selecionar` (`atualizar_precos.py:217-221`) compara com `datetime.now()` e manda o item para a seleção. O teste de `:461-466` já usa um relógio fixo (é o padrão a seguir).
- **Dados reais:** `test_api_ofertas_qa.py:477-506` (`DadosReais`) e `:920`, e `test_atualizar_precos_qa.py:45-117`, `:177` e `:242` copiam o `achadinhos.db` em `mode=ro` e só pulam se o banco não existir.
- **Trava:** existem dois padrões. `tools/garimpo_feminino/banco.py:391-421` (`travar`: `O_NOFOLLOW`, 0600, dono, `LOCK_EX|LOCK_NB`, erro → saída 2) e `ml_api.py:474-490` (com espera, para a renovação). O `atualizar_precos.py` não tem trava; a premissa "um comando por vez" está só na docstring (`atualizar_precos.py:76`). O progresso é `open(FEITOS,'a')` (`:163-165`). Os códigos de saída em uso são 0/1/2/3/130 (`atualizar_precos.py:78-83`, `coletar_shopee.py:715-768`); nenhum CLI usa o 4.
- **Backup:** `migrar_categorias.py:247-301` já tem `caminho_backup` (datado, com sufixo em colisão), `verificar_backup` e `fazer_backup`.
  - `~/atualizar-ml.sh` e `~/atualizar-shopee.sh` gravam em nome fixo (`backups/antes-ml-api.db`, `backups/antes-shopee-item.db`) e ficam fora do repositório. O teste `test_shopee_por_item_qa.py:1475-1477` exige que o README cite `backups/antes-shopee-item.db`.
  - `backups/` tem 90 MB, arquivos 0644 e `-shm`/`-wal` soltos. Eles aparecem porque o backup herda o modo WAL e é aberto depois.
  - O banco tem a tabela `numeros` (telefone: dado pessoal), então todo backup leva dado pessoal.
- **Servidor:** a subida está em `servidor.py:975-986` e só imprime porta e banco. O `do_GET` (`:745`) passa por `bloquear()` antes das rotas. `ROTAS_ML` (`:51`) define o que o ML alcança; rota fora dele é só da origem local.
- **Skill quebrada:** `.claude/skills/rodar_localmente/SKILL.md` aponta para `~/Documentos/mensagensParaEnviar`, pasta que não existe mais (o projeto está em `~/Documentos/saas/etiqueta`).
- **Agendador durável já usado na máquina:** `~/.config/systemd/user/achadinhoturbo-backup.timer` e `atualizar-ofertas-casamento.timer` (`Persistent=true`, gerados por instalador). `Linger=no` (`loginctl`): só rodam com o dono logado. O crontab está vazio.
- **Git:** branch `garimpo-feminino`, 4 commits à frente da `origin`, `main` 5 atrás, 28 arquivos modificados e 7 novos. Não há `core.hooksPath` nem hooks além dos exemplos. Não existe `.claude/settings.json` nem `docs/produto/decisoes.md`.
- **Manifesto:** o "Sem manifesto de dependências" do CLAUDE.md veio no commit `309bb89` como descrição; nenhum plano o registra como decisão (`grep` em `docs/produto/planos`).

## Abordagens consideradas
| Tema | Abordagem | Prós | Contras | Risco |
|---|---|---|---|---|
| Trava | **Uma por loja**, ao lado do banco (`<DB>.rodada-<loja>.lock`) | ML e Amazon rodam juntos (hoje é assim); coleta e atualização da mesma loja se excluem | O progresso compartilhado continua com append concorrente (linhas curtas com `O_APPEND`) | baixo |
| Trava | Uma global por banco | A mais simples | Amazon (40 min) fica bloqueada durante o ML (horas) | médio, operacional |
| Onde fica a trava | **`travar_rodada` no `servidor.py`** | Os CLIs já importam `S` para `criar_banco`/`upsert`; nenhum arquivo novo para as coletas carregarem | `servidor.py` cresce ~30 linhas | baixo |
| Onde fica a trava | Módulo novo `rodada.py` | Isolado | Vira a 4ª dependência obrigatória das coletas (CLAUDE.md, seção coletas) | baixo |
| Versão | **Hash do conteúdo dos `.py` carregados**, mais o commit lido de `.git/` | Pega mudança sem commit (o caso de hoje); sem subprocess | — | baixo |
| Versão | Só `git rev-parse` | Simples | Mente com árvore suja e põe subprocess no servidor | médio |

Para o código de saída da trava, a escolha é o **4**, não o 2 do garimpo. O 2 já quer dizer "acesso do ML venceu, rode com o Secret" no laço aba por aba e no `~/atualizar-ml.sh`, e reusar o código daria a instrução errada ao dono.

## Decisão
- Estender o que existe: copiar o `travar` do garimpo (sem importar `tools/`) e o backup do `migrar_categorias` (sem refatorá-lo agora), além de ampliar o `rodar_base.sh` do lead até virar o `verificar.py`.
- Tudo só com a biblioteca padrão.
- Arquivos novos na raiz: `verificar.py`, `backup_banco.py` e `requirements.txt`.
- Pastas novas: `operacao/` (scripts) e `.githooks/` (portão).

## Esquema e contratos
- `servidor.travar_rodada(loja)`, um context manager:
  - arquivo `S.DB + '.rodada-' + loja + '.lock'`, aberto com `O_RDWR|O_CREAT|O_NOFOLLOW|O_CLOEXEC`, 0600, conferindo arquivo comum e do próprio usuário;
  - `flock(LOCK_EX|LOCK_NB)`;
  - ocupado → `RodadaEmAndamento(loja)`; outro erro → `RodadaEmAndamento` com motivo fixo.
- Saída **4** nos três CLIs, com a mensagem `PAROU: outra rodada de <loja> está em andamento (<nome do .lock>); espere ela terminar.` no stderr. A trava é pega **antes** de `proteger_processo`, `credenciais`, `sessao_do_ambiente`, `criar_banco` e de qualquer `marcar`. `coletar_shopee conferir` não trava, porque não grava.
- `backup_banco.py --motivo <[a-z0-9-]{1,30}> [--manter N]` (N padrão 14, mínimo 3). O fluxo:
  1. Lê o `S.DB` em `mode=ro`.
  2. Confere o espaço livre: precisa de 2× o tamanho do banco, senão sai com 1.
  3. Grava em `<final>.parcial` e roda `integrity_check == 'ok'` e `COUNT(items) > 0`.
  4. Põe `PRAGMA journal_mode=DELETE` (assim a cópia não cria `-wal`/`-shm` ao ser aberta), faz `chmod 0600` e `os.replace` para o nome final.
  5. Garante `backups/` em 0700.
  6. Imprime `backup: <caminho> ok <n> itens` e sai com 0. Em falha, apaga o parcial e sai com 1.
  7. A rotação só roda depois do sucesso: apaga `auto-*.db` (e o `-wal`/`-shm`/`-journal` de cada um) além dos N mais novos pelo nome e nunca toca arquivo sem o prefixo `auto-`.
- `verificar.py`:
  - **Ambiente isolado:** cópia de `os.environ` sem as variáveis `ACHADINHOS_*SECRET*`, `ACHADINHOS_SHOPEE_APP_ID` e `ACHADINHOS_ML_TOKENS`; proxies `http(s)/ftp` (minúsculas e maiúsculas) em `http://127.0.0.1:9`; `ACHADINHOS_API_TOKEN_ARQUIVO=/nao/existe`; `ACHADINHOS_DISPARO=0`; `ACHADINHOS_DB`, `ACHADINHOS_FEITOS*`, `ACHADINHOS_ML_TOKENS` e `ACHADINHOS_ML_CATALOGO` numa pasta temporária. Essa pasta é rede de segurança: teste que quebrar com isso estava tocando dado real, e isso é achado.
  - **Execução:** cada arquivo em subprocesso com `-v` e timeout de 900 s; a saída vai para `logs/verificar-<data>/<nome>.txt`.
  - **Resumo:** uma linha por arquivo `nome saida tempo Ran/OK/FAILED (skipped=n)` e os motivos de skip extraídos da saída `-v`.
  - `LENTOS = ('test_api_ofertas_qa', 'test_genero_qa')`.
  - `--dados-reais` exporta `ACHADINHOS_TESTE_DADOS_REAIS=1`. Esse é o contrato com a etapa 2.
  - `--hora H` põe `TZ` com deslocamento POSIX calculado a partir do UTC atual, para o relógio local cair na hora H (por exemplo, `TZ='XXX+N'` dá local = UTC − N).
  - `--segredos [--staged|--tudo]` e `--pre-commit` estão descritos na etapa 8; `--servidor [porta]`, na etapa 6.
  - Saídas: 0 tudo verde; 1 algo falhou; 2 uso errado.
- `GET /api/versao` (só da origem local, fora de `ROTAS_ML`) devolve `{"codigo": <sha256[:12] dos bytes de servidor.py, disparo.py, genero.py e api_ofertas.py na subida>, "em_disco": <o mesmo recalculado agora>, "mudou": bool, "git": <commit curto lido de .git/HEAD → refs ou packed-refs, ou null>, "iniciado_em": "AAAA-MM-DDTHH:MM:SS"}`. Na subida, o log ganha a linha `Código <codigo> (último commit <git|?>; pode haver mudança sem commit)`. O `index.html` fica de fora do hash, porque é servido do disco a cada pedido.

## Etapas (Entrega 1)
| # | Etapa | Arquivos | Verificação | Responsável | Grupo | Sensível | CAs |
|---|---|---|---|---|---|---|---|
| 0 | Antes de qualquer código: o lead propõe ao dono a divisão em commits temáticos do trabalho sem commit (Shopee por item + G1; trava de preço velho na v1; `proteger_processo`; memórias dos agentes; `black-friday.md` e `test_qa_entrega1.py` ficam fora, cada um na sua frente) e pergunta "pode commitar?". Onde um arquivo mistura frentes (`coletar_shopee.py`), vai no commit da frente maior. Depois de commitar, reinicia o servidor | git (lead) | `git status` limpo, exceto as frentes deixadas de fora; `curl` na 8765 dá 200 | lead + dono | 0 | não | CA9 |
| 1 | Tirar a hora do dia dos testes: `:253` e `:418` passam a gravar `A.hoje()+'T00:00:00'` (sempre no passado, salvo na virada da meia-noite) e procurar outros `hoje() + 'T` nos testes | `testes/test_atualizar_precos.py` | `TZ` com relógio às 03h: `python3 testes/test_atualizar_precos.py` (o dev calcula o `TZ`; depois da etapa 5, `verificar.py --hora 3`) | dev | A | não | CA2 |
| 2 | Acabar com as falhas conhecidas:<br>(a) `DadosReais` e a classe de `:920` do `test_api_ofertas_qa.py`, e as classes de dados reais do `test_atualizar_precos_qa.py`, pulam com `skipUnless(os.environ.get('ACHADINHOS_TESTE_DADOS_REAIS')=='1', 'dados reais: rode verificar.py --dados-reais')`;<br>(b) caso sintético com o título `… l.eb2gam1 …` provando que a v1 o deixa sair e que `D.urls_da_mensagem` devolve `[]`; o oráculo da linha 80 passa a exigir fronteira depois do TLD (`[a-z]{2,}\b`), com comentário;<br>(c) `:1469` passa a aceitar o texto atual do CLAUDE.md (`'--por-item'`) | `testes/test_api_ofertas_qa.py`, `testes/test_atualizar_precos_qa.py`, `testes/test_shopee_por_item_qa.py` | os três arquivos verdes; com `ACHADINHOS_TESTE_DADOS_REAIS=1` e proxies bloqueados, os dois `_qa` de dados reais também verdes | dev | A | não | CA3 |
| 3 | Trava por loja, conforme o contrato: `travar_rodada` e `RodadaEmAndamento` no `servidor.py`; uso no `main` dos três CLIs com saída 4 e docstrings atualizadas (lista de saídas); `.gitignore` ganha `*.db.rodada-*.lock`. Testes: 2ª rodada da mesma loja sai com 4 e não cria `ACHADINHOS_DB` temporário, `FEITOS` nem tokens (trava segurada pelo teste com outro `open`+`flock`); lojas diferentes não se bloqueiam; symlink no lugar do `.lock` é recusado; a trava some com `kill -9` (subprocesso) | `servidor.py`, `atualizar_precos.py`, `coletar_amazon.py`, `coletar_shopee.py`, `.gitignore`, `testes/test_trava_rodada.py` | `python3 testes/test_trava_rodada.py -v`; `python3 testes/test_atualizar_precos.py`, `test_coletar_shopee.py`, `test_coletar_amazon.py` e `test_servidor.py` verdes | dev | A | **sim** (concorrência) | CA4 |
| 4 | `backup_banco.py`, conforme o contrato. Testes em pasta temporária (`ACHADINHOS_DB` temporário): nome datado e colisão, 0600/0700, sem `-wal`/`-shm` depois de abrir a cópia, rotação que poupa arquivo sem `auto-`, parcial apagado em falha, banco corrompido sai com 1, motivo inválido sai com 2 | `backup_banco.py`, `testes/test_backup_banco.py` | `python3 testes/test_backup_banco.py -v` | dev | A | **sim** (backup com dado pessoal) | CA5 |
| 5 | `verificar.py` (py_compile, Python, Node, `--rapido`, `--dados-reais`, `--hora`, `--front`, aviso do manifesto), conforme o contrato. O `--front`:<br>(1) copia o banco real com `sqlite3 backup` em `mode=ro` para uma pasta temporária;<br>(2) sobe `servidor.py` com `ACHADINHOS_PORTA=8766` e o ambiente isolado;<br>(3) se a 8766 estiver ocupada ou alguém pedir a 8765, sai com 2;<br>(4) roda as páginas da lista `FRONT` (o dev classifica cada uma contra a cópia; `disparo-integracao` e `genero-integracao` ficam fora com motivo impresso);<br>(5) derruba o servidor no `finally`.<br>Testes do próprio verificador: ambiente sem Secret e com proxies, `--hora`, recusa da 8765 e parse do resumo | `verificar.py`, `testes/test_verificar.py` | `python3 testes/test_verificar.py -v`; `python3 verificar.py` sai com 0; `--rapido --hora 3` e `--hora 23` saem com 0; `--front` sai com 0 com internet | dev | A | **sim** (copia o banco real, sobe servidor) | CA1, CA2, CA3, CA8 |
| 6 | Versão do código: na subida, hash e linha de log; rota `/api/versao`; `verificar.py --servidor [porta]` (sem a rota → "servidor anterior a esta versão: reinicie"; `mudou` → "reinicie"). Testes: a rota só responde à origem local e com Host válido, `mudou` vira `true` quando o arquivo muda, `.git` ausente dá `git: null` | `servidor.py`, `verificar.py`, `testes/test_versao_servidor.py` | `python3 testes/test_versao_servidor.py -v`; `python3 testes/test_servidor.py` verde | dev | B | **sim** (rota nova) | CA12 |
| 7 | Scripts operacionais versionados em `operacao/`:<br>- `comum.sh`: `cd` para a raiz a partir do próprio caminho, log `logs/<nome>-AAAAMMDD-HHMMSS.log` com `tee`, `backup_banco.py --motivo <loja>` (para se falhar);<br>- `atualizar-ml.sh [abas…]`: abas do `buscas.json` por padrão; Secret pedido com Enter vazio = usar o token; na saída 2 sem Secret, pede e repete a aba; 3 → `sleep ${PAUSA_SEG:-300}` e segue; 2 com Secret, 4 ou 1 → para com instrução;<br>- `atualizar-shopee.sh [aba]`: `conferir --por-item`, 10 itens, depois a aba;<br>- `atualizar-amazon.sh [--produtos N]`.<br>Teste: estático (sem `export`, todo `read` com `-rs`, nenhum `/tmp`, log em `logs/`) e funcional com `python3` falso no `PATH` e `PAUSA_SEG=0`, conferindo a ordem das chamadas e a reação a 0/2/3/4. `.gitignore` ganha `logs/` | `operacao/comum.sh`, `operacao/atualizar-ml.sh`, `operacao/atualizar-shopee.sh`, `operacao/atualizar-amazon.sh`, `testes/test_operacao.py`, `.gitignore` | `bash -n operacao/*.sh`; `python3 testes/test_operacao.py -v` | dev | B | **sim** (segredo) | CA5, CA6 |
| 8 | Portão de commit:<br>- `verificar.py --segredos --staged|--tudo` e `--pre-commit`;<br>- **nomes proibidos:** `api_token.txt`, `api_cabecalho.txt`, `ml_tokens.json*`, `.ml_tokens.json.*.tmp`, `ml_catalogo.json`, `.ml_catalogo.json.*.tmp`, `.env*` (menos `.env.example`), `*.db*`, `*.lock`, `_chat.txt`, `WhatsApp Chat*`, `backups/`, `logs/`;<br>- **padrões nas linhas adicionadas** (`git diff --cached -U0`): chave privada PEM, `Bearer <32+>`, atribuição `(secret|senha|password|token|app_id)\s*[:=]\s*['"]?<24+ alfanuméricos>`, `APP_USR-…`/`TG-…` do ML (formato **não verificado**: o dev confirma na doc pública, sem ler o `ml_tokens.json`);<br>- **escape:** a linha com `# verificar: permitir` é aceita;<br>- **testes:** só se houver `.py`, `.mjs`, `.html` ou `.json` staged;<br>- **saída:** só o arquivo, a linha e o tipo, **nunca o trecho achado**;<br>- **hook:** `.githooks/pre-commit` é `exec python3 verificar.py --pre-commit`; o `verificar.py` avisa quando o `core.hooksPath` não aponta para `.githooks`.<br>Calibrar com `--tudo` sobre o HEAD até zerar, com o mínimo de marcadores | `verificar.py`, `testes/test_verificar.py`, `.githooks/pre-commit` | `python3 testes/test_verificar.py -v`; `python3 verificar.py --segredos --tudo` sai com 0; num repositório temporário, commit com `api_token.txt` ou com `secret = "<falso de 32>"` é bloqueado | dev | C | **sim** (hook, segredo) | CA7 |
| 9 | Manifesto: `requirements.txt` com `beautifulsoup4==4.14.3` e `lxml==6.0.2` e um comentário com Python ≥ 3.14 e Node ≥ 22. Só depois da resposta à P1 | `requirements.txt` | `python3 -m pip install --dry-run -r requirements.txt` (sem instalar) **pelo dono**; `verificar.py` não avisa divergência | dev | B | não | CA8 |
| 10 | Corrigir a skill `rodar_localmente`: caminho `~/Documentos/saas/etiqueta`, backup pelo `backup_banco.py --motivo reiniciar`, conferência final por `verificar.py --servidor` | `.claude/skills/rodar_localmente/SKILL.md` | leitura pelo revisor; `rg mensagensParaEnviar .claude` vazio | dev | C | não | CA5, CA12 |
| 11 | Docs:<br>- **README:** seções "Verificar", "Operação" (os scripts, saída 4, logs, backups) e reversão com o backup datado;<br>- **CLAUDE.md:** "Verificação" vira `python3 verificar.py`, mais a saída 4, `operacao/`, `backup_banco.py` e `/api/versao`;<br>- **`test_shopee_por_item_qa.py`:** `:1475-1477` passa a procurar `backups/auto-` em vez do nome fixo | `README.md`, `CLAUDE.md`, `testes/test_shopee_por_item_qa.py` | `python3 testes/test_shopee_por_item_qa.py`; `python3 verificar.py` verde | dev | D | não | CA1, CA5, CA6 |
| 12 | Ações do dono, com o lead guiando:<br>- `git config core.hooksPath .githooks`;<br>- `chmod 700 backups && chmod 600 backups/*`;<br>- decidir as sobras `-wal`/`-shm` antigas (0 bytes, P2);<br>- trocar `~/atualizar-*.sh` por chamadas a `operacao/`;<br>- gerar um Secret novo da Shopee | — | `git config --get core.hooksPath` dá `.githooks`; `ls -l backups` | dono | E | **sim** | CA5, CA7 |

Ordem e grupos:
- O grupo A (1–5) não compartilha arquivos e pode ir em paralelo.
- O grupo B (6, 7 e 9) depende do A: a 6 mexe em `servidor.py` e `verificar.py`; a 7 usa a saída 4 e o `backup_banco.py`.
- C (8 e 10) vem depois de B, porque a 8 também mexe em `verificar.py`, então depende da 6.
- D (11) vem depois de tudo, e E (12) por último.
- A etapa 2 e a 11 tocam o mesmo `test_shopee_por_item_qa.py` em grupos diferentes, e por isso nunca juntas.
- **Nada do grupo A roda enquanto houver rodada do ML no ar contra o banco real.** Os testes usam banco temporário, mas o dev deve conferir antes com `pgrep -af atualizar_precos`.

## Pontos para o seguranca
- **Etapa 3:** `O_NOFOLLOW`, dono e modo do `.lock`; a trava vem antes do `pop` do Secret e de qualquer escrita; nenhuma corrida entre `open` e `flock` deixa a 2ª rodada gravar o progresso.
- **Etapa 4:** backup com dado pessoal (`numeros`) fica 0600 em pasta 0700, sem `.parcial` deixado para trás. A rotação nunca apaga arquivo sem `auto-` nem segue symlink, e confere o padrão do nome antes de `remove`.
- **Etapa 5:** o ambiente do filho nunca herda Secret; o `--front` nunca usa a 8765; a cópia do banco vai para pasta temporária 0700 e é apagada; os logs em `logs/verificar-*` não trazem dado do banco real (os testes de dados reais imprimem só chaves).
- **Etapa 6:** `/api/versao` passa pelas guardas de Host e Origem e fica fora de `ROTAS_ML`; não expõe caminho absoluto nem conteúdo de `.git` além do hash curto.
- **Etapa 7:** sem `export`; `unset` em `trap EXIT`; o `tee` não pega o Secret (o `read -s` não ecoa); nenhum `set -x`; o Secret nunca vai para o `argv` de nada (só para o ambiente do comando).
- **Etapa 8:** a varredura nunca imprime o segredo achado. O escape `verificar: permitir` aparece no resumo para revisão. `--no-verify` continua possível: o portão protege contra acidente, não contra má-fé.

## Riscos e como reverter
| Risco | Como reverter |
|---|---|
| Trava pega cedo demais e impede rodada legítima (por exemplo, o `.lock` num disco sem `flock`) | Reverter o commit da etapa 3; o `.lock` é inofensivo e pode ser apagado |
| Rotação apaga backup útil | Só apaga `auto-*` além dos 14 mais novos; os backups manuais ficam. Para mudar a política, use `--manter N` nos scripts |
| Ambiente isolado do `verificar.py` revela teste que dependia do banco real | É o objetivo: o teste ganha fixture (fluxo de bug) ou passa para `--dados-reais` |
| Portão bloqueia commit com falso positivo | Usar o marcador na linha e ajustar o padrão; `git config --unset core.hooksPath` desliga o portão |
| `/api/versao` quebra uma guarda existente | Reverter o commit da etapa 6; nenhuma migração de banco neste plano |
| Script novo erra no meio de uma rodada | Os `~/atualizar-*.sh` antigos ficam até a etapa 12; o banco tem o backup datado da própria rodada; restaurar pelo `migrar_categorias.py --restaurar ARQUIVO` com o servidor parado |

## Perguntas em aberto e premissas adotadas
- **P1 (dono):** o "Sem manifesto de dependências" é decisão sua ou só descrição? Premissa: descrição, e o `requirements.txt` entra.
- **P2 (dono):** posso apagar os 14 pares `-wal` (0 bytes) e `-shm` antigos de `backups/`? Eles não têm dado; o `.db` de cada um fica.
- **P3 (dono):** guardar os 14 backups automáticos mais novos (cerca de 115 MB) está bom?
- **Premissa:** a trava é por loja, não global. Se o dono quiser "um comando por vez" de verdade, troque a chave por uma constante (uma linha).
- **Premissa:** o 4 vira "outra rodada em andamento" nos três CLIs.
- **Premissa:** o `--front` precisa de internet para as 2 fotos reais do `copiar-imagem`. Sem rede, essas 2 falham. Por isso o `--front` é opcional e fica fora do `--rapido` e do portão.

## Processo (CA9: texto para o lead propor ao dono)
1. **Pedido de commit:** o fluxo padrão ganha o passo final "o lead propõe a divisão em commits (um por frente, com mensagem) e pergunta: pode commitar?". Sem o "sim", o lead faz um backup do diff (`git diff > backups/trabalho-<data>.patch`) e registra isso na passagem.
2. **Uma frente por branch:** branch nova a partir da `main` para cada plano. Trabalho de outra frente não entra no commit nem na branch errada.
3. **Passagem de sessão:** `docs/produto/registros/AAAA-MM-DD-passagem-de-sessao.md` é artefato padrão quando a sessão vai acabar com algo rodando, e lista processos, logs (sempre em `logs/`, nunca no `/tmp`), comandos de retomada e pendências.
4. **Falha conhecida não é estado normal:** teste vermelho tem de virar fixture, skip com motivo ou bug aberto na mesma rodada. O lead não dá "pronto" com `verificar.py` vermelho.

## Entrega 2: recomendação e recorte (plano próprio depois)
- **CA10: hook `UserPromptSubmit`.**
  - É viável: script stdlib em `.claude/settings.json` que lê o JSON do prompt e sai com 2 se achar segredo. Pela doc do Claude Code, sair com 2 bloqueia e apaga o prompt (comportamento a conferir na implementação, **não verificado** aqui).
  - Falso positivo provável: hashes de commit (40 hex), ids e URLs longas. Só bloquear `secret`/`app_id`/`senha` seguido de um valor de 16+ caracteres, ou um bloco solto de 32+ caracteres alfanuméricos misturando maiúsculas, minúsculas e dígitos fora de URL.
  - O script nunca grava nem imprime o prompt.
  - Precisa do dono (P4), porque mexe na configuração do harness.
- **CA11: automação durável.** Recomendo o **timer do systemd `--user`**, que já é o padrão da máquina (`achadinhoturbo-backup.timer`). As alternativas:
  - o cron da sessão morre com ela;
  - a rotina na nuvem não vê o disco nem o banco.

  O que pode ir para o timer:
  - backup diário (`backup_banco.py --motivo diario`);
  - Amazon (`operacao/atualizar-amazon.sh`, sem credencial);
  - ML enquanto o token valer: sai com 2 quando vencer, e o timer avisa por `notify-send`.

  O que não vai:
  - Shopee: o Secret só existe no ambiente de um comando do dono. Automatizar exigiria guardá-lo no chaveiro do GNOME (`secret-tool`), o que reabre a regra "nunca em arquivo" (P5);
  - conferência Meta: depende do MCP autenticado e de arquivos em `~/Documentos/relatorios-campanhas`, fora deste repositório. Fica no cron da sessão, recriado pela passagem, ou num `claude -p` disparado por timer (P6, **não verificado**).

  `Linger=no`: só roda com o dono logado (ativar o linger é decisão dele). Instalador versionado em `operacao/instalar-timers.sh`, no padrão "Gerado por … instalar".
- **CA13: corte do CLAUDE.md** (4.232 palavras):
  - o que fica: regras do dono, segredos, mapa de arquivos de uma linha cada, `verificar.py` e a equipe;
  - o que vai para `docs/produto/referencias/<modulo>.md`: os contratos por módulo;
  - o histórico de rodadas ("535 de 540") vai para os registros.

  Pré-requisito: tirar dos testes as afirmações sobre o texto do CLAUDE.md (`test_shopee_por_item_qa.py`, `test_servidor.py`) e passá-las para o README ou para as referências; senão o corte quebra a suíte. P7 (dono): aprova o corte?

## ADR
**ADR: portão local de qualidade e operação versionada (2026-11-09).**
- **Contexto:** regressões entraram sem ninguém ver (o teste do CLAUDE.md quebrou fora de qualquer revisão), o trabalho ficou sem commit por dias e a operação vivia em scripts no `~` e no `/tmp`.
- **Decisão:**
  - um comando único, `verificar.py` (só stdlib), é a definição de "verde";
  - o portão de commit chama esse comando e a varredura de segredos;
  - as rodadas operacionais ficam em `operacao/`, com trava por loja, backup datado e rotacionado e log em `logs/`.
- **Alternativas descartadas:**
  - pytest/pre-commit, por serem dependência nova;
  - CI remoto, porque os testes precisam do Chrome local e não há segredo para a nuvem;
  - trava global, porque bloqueia Amazon e ML juntos.
- **Consequências:** o commit fica cerca de 2 min mais lento quando há código staged; todo teste novo precisa passar no ambiente isolado; os códigos de saída ganham o 4.
