## Contexto do projeto

> **A definir** (parcial): dados de teste. Os demais itens foram verificados em 2026-11-03.

- **Produto:** **Etiqueta** (nome que aparece no `<title>` e no `<h1>` do `index.html`; antes "Mensagens Achadinhos"; não confundir com a cor de acento Etiqueta, token `--etiqueta`, nem com a etiqueta de afiliado do ML; ao falar da cor, diga "cor Etiqueta" ou `--etiqueta`), gerador de mensagens de ofertas ("achadinhos") para grupos de WhatsApp. O dono coleta produtos da Amazon, do Mercado Livre e da Shopee, escolhe um template e copia a mensagem pronta, sempre com link de afiliado. Uso local, uma pessoa, no computador. A visão fica em `docs/produto/visao.md` (a escrever na sessão `produto`).
- **Stack:** Python 3.14 só com a biblioteca padrão no servidor (`http.server` + `sqlite3`); `beautifulsoup4` e `lxml` na coleta da Amazon; front em HTML, CSS e JS puros num arquivo só, sem build; fontes Geist e Geist Mono pelo Google Fonts (sem internet, cai na fonte do sistema). Identidade visual em `Identidade visual — links de afiliado.pdf`; decisões de UI em `docs/produto/specs/ux-ui-identidade.md`. Dependências em `requirements.txt` (`beautifulsoup4==4.14.3`, `lxml==6.0.2`, versões fixas; o `verificar.py` avisa quando o ambiente difere dele).
- **Mapa** (uma linha por arquivo). O contrato de cada um, com comandos, saídas, limites e histórico, está na referência da área em `docs/produto/referencias/`: leia a da área antes de mexer nela.
  - `servidor.py`: API REST e estático em http://localhost:8765/, guardas de `Host` e origem, `upsert`, `GET /api/versao`, `travar_rodada(loja)` (saída 4 dos CLIs). **Regra de negócio.** [servidor.md](docs/produto/referencias/servidor.md)
  - `achadinhos.db`: banco SQLite (tabela `items`, única por `loja`+`item_id`; tabela `config`). **Dados; nunca editar à mão.** [servidor.md](docs/produto/referencias/servidor.md)
  - `coletar_amazon.py` + `buscas.json` (17 abas), `coletar_shopee.py` (Open API) e `coletar_ml.js` (console do DevTools): as coletas. **Regra de negócio.** [coletas.md](docs/produto/referencias/coletas.md)
  - `atualizar_precos.py` (`amazon`, `shopee`, `ml`): preço dos itens que já existem, sem inserir e sem trocar link de afiliado. **Regra de negócio.** [atualizar-precos.md](docs/produto/referencias/atualizar-precos.md)
  - `ml_api.py`: API oficial do ML, só leitura, OAuth e vínculo com o catálogo (`ml_catalogo.json`: agentes não o leem nem o criam no projeto). **Regra de negócio.** [atualizar-precos.md](docs/produto/referencias/atualizar-precos.md)
  - `disparo.py`: disparo automático, migração do esquema em `criar_banco` (rodar o servidor ou uma coleta migra: faça backup antes), trava de preço velho e `foto_grande`; a tabela `numeros` guarda telefone e id de grupo (dado pessoal: só no banco local, mascarado na tela, nunca em log/URL/git). **Regra de negócio.** [disparo.md](docs/produto/referencias/disparo.md)
  - `genero.py`: público (gênero) calculado na leitura. **Regra de negócio.** [disparo.md](docs/produto/referencias/disparo.md)
  - `api_ofertas.py`: API v1 para o Achadinho Turbo (outro projeto, não editar daqui); a única rota que grava, `POST /api/v1/amazon/<ASIN>/confirmar-preco`, fica no `servidor.py`. **Regra de negócio.** [api-ofertas.md](docs/produto/referencias/api-ofertas.md)
  - `index.html`: a interface inteira, inclusive a tela do disparo e os testes do front. [front.md](docs/produto/referencias/front.md)
  - `mensagens.html` e `amazon.php`: cópia antiga do site na Hostinger. Não alterar.
  - `verificar.py` (verificação e portão de commit), `backup_banco.py` (backup datado), `operacao/` (rodadas de preço do dono; `automatico.sh` e `instalar-timers.sh` geram os timers `etiqueta-<tarefa>` do `systemd --user` para backup, Amazon e ML, nunca a Shopee) e `.claude/hooks/segredo_no_prompt.py` (hook que bloqueia segredo no prompt). **Regra de negócio.** [operacao.md](docs/produto/referencias/operacao.md)
  - `migrar_categorias.py` e `classificar_lista.py` + `lista_whatsapp.json`: reorganização das abas. **Regra de negócio.** [operacao.md](docs/produto/referencias/operacao.md)
  - Pastas de regra de negócio que o `designer` não pode tocar: `servidor.py`, `disparo.py`, `coletar_*.py` (inclui `coletar_shopee.py`), `genero.py`, `api_ofertas.py`, `atualizar_precos.py`, `ml_api.py`, `coletar_ml.js`, `migrar_categorias.py`, `classificar_lista.py`, `buscas.json`, `lista_whatsapp.json`, `*.db`, `verificar.py`, `backup_banco.py`, `operacao/`, `.claude/hooks/`, `.claude/settings*.json`, `.claude/agents/`, `.githooks/`.
- **Armadilhas que cruzam áreas:**
  - Um host novo da Shopee entra em três lugares: `servidor.py` e `disparo.py` (`HOSTS_AFILIADO_SHOPEE`) e `index.html` (`HOSTS_LINK.shopee`); `testes/test_front_constantes.py` reprova se algum ficar para trás.
  - Constantes do `index.html` lidas por regex nos testes Python ficam numa linha só (`LOJA`, `HOSTS_LINK`, `HOST_FOTO_SHOPEE`, `HOSTS_FOTO`, `ABAS_COM_GENERO`, `GENEROS`, `NOME_GENERO`, `OPCOES_PUBLICO`).
  - `testes/disparo.test.html` está perto do limite de navegações por hash do Chrome no runner: evite acrescentar navegações.
  - Nunca crie `api_token.txt` real em teste: token temporário via `ACHADINHOS_API_TOKEN_ARQUIVO`.
  - As rodadas de `operacao/` são do dono, no terminal dele: agentes não as rodam (pedem a chave). Os timers só rodam com o código commitado (a rodada automática para com saída 1 se algum `.py` da raiz, inclusive novo não rastreado, o `buscas.json` ou `operacao/` tiverem mudança sem commit).
  - O `designer` mexe só em estilo, marcação e textos; chamadas de API e lógica de dados ficam com o `dev`.
  - **Teste não lê o `CLAUDE.md`.** Fato que um teste precisa conferir fica no código ou no `README.md`. Leem o `README.md` o `test_shopee_por_item_qa` e o `test_ml_api_qa` (este só o README): antes de reescrever um trecho, `rg -n "CLAUDE|README" testes/` e mantenha os literais exigidos.
- **Verificação:** `python3 verificar.py` é a definição de "verde": todos os testes Python e Node, um arquivo por subprocesso, num ambiente isolado (sem Secret, proxies em `127.0.0.1:9`, banco temporário). Opções (`--rapido`, `--dados-reais`, `--front`, `--servidor`), portão de commit e testes por área em [operacao.md](docs/produto/referencias/operacao.md).
  - **Falha conhecida não é estado normal:** teste vermelho vira fixture, skip com motivo ou bug aberto na mesma rodada; nada é "pronto" com o `verificar.py` vermelho.
  - Para um arquivo só: `python3 testes/<nome>.py -v` (rode com os proxies em `127.0.0.1:9`: `export http_proxy=http://127.0.0.1:9 https_proxy=http://127.0.0.1:9 ftp_proxy=http://127.0.0.1:9`; o `/api/fetch` acessa a rede de verdade, também ao testar mutantes ou código antigo).
  - Node: `node --test testes/<nome>.test.mjs`.
  - Front: `node testes/rodar.mjs <página>` deve imprimir `RESULTADO: OK`; para código novo, sem tocar no servidor real, use servidor próprio na 8766 sobre uma cópia do banco (receita e páginas em [front.md](docs/produto/referencias/front.md)).
- **Dados de teste:** a definir. Para não mexer nos dados reais, rode contra uma cópia do `achadinhos.db` (o caminho está na constante `DB` em `servidor.py`). Coletas acessam Amazon e Mercado Livre de verdade: nunca rode em teste.
- **Regra do dono:** todo link gravado tem que ser de afiliado (Amazon `?tag=desejodemen01-20`; Mercado Livre `https://meli.la/...` da etiqueta `achadosmenicas`; Shopee `https://s.shopee.com.br/...` gerado pela Open API com as credenciais do dono, ID de afiliado `18328801339`). Nunca troque um link de afiliado por um link comum.
- **Dado pessoal (LGPD):** não há dado de cliente. O `_chat.txt` em `WhatsApp Chat - AmazonLinks/` tem o nome do dono; não copie para logs. A tabela `numeros` e todo backup ou cópia do banco têm telefone: ficam em 0600 dentro de pasta 0700 e nunca vão para log ou git.
- **Segredos:** nunca leia nem imprima `.env*` (exceto `.env.example`) nem arquivos de senha. Primeiro segredo do projeto: `ACHADINHOS_SHOPEE_SECRET` (e o AppID). Ele só existe no ambiente de um comando do dono (`read -rs S; ACHADINHOS_SHOPEE_SECRET="$S" ... python3 coletar_shopee.py ...; unset S`, sem `export`); nunca em arquivo, git, `argv`, log ou conversa. Agentes nunca rodam `env`, `printenv`, `set` ou `declare -p` nem imprimem essa variável, e nunca usam o plugin do Chrome na aba do painel da Shopee que mostra o Secret. Segundo segredo: `api_token.txt` (token da API v1, no `.gitignore`); agentes nunca o leem, imprimem nem criam no projeto (em teste, só arquivo temporário no scratchpad). Terceiro: `ACHADINHOS_ML_SECRET` (Client Secret da app "Etiqueta" no DevCenter do ML), com a mesma regra da Shopee (`read -rs S; ACHADINHOS_ML_SECRET="$S" python3 ml_api.py autorizar; unset S`); nunca use o plugin do Chrome para revelar a "Chave secreta" na página da app. Quarto: `ml_tokens.json` (access e refresh token do ML), com o `.lock` e as sobras `.ml_tokens.json.*.tmp`: agentes nunca os leem, imprimem nem criam no projeto; em teste, `ACHADINHOS_ML_TOKENS` aponta para pasta temporária. O hook de prompt `.claude/hooks/segredo_no_prompt.py` (vale depois de registrado em `.claude/settings.json`) bloqueia o prompt com segredo, mas **não tira o texto do disco**: ele pode ficar no histórico e no transcript locais; segredo real colado pede troca da chave. As rodadas automáticas (timers) nunca recebem segredo: recusam variável de segredo no ambiente e a Shopee. Toda entrada nova que lê Secret chama `proteger_processo()` antes, e cliente HTTP com credencial não segue redirect.
- **Docs que acompanham a mudança:** `README.md` (visão de uso do dono: servidor, verificar, backup, operação, coletas), `CLAUDE.md` (mapa e regras que cruzam áreas) e a referência da área em `docs/produto/referencias/` (contratos e histórico).

## Equipe de agentes

Na sessão principal, atue como tech lead: delegue, coordene e consolide. Se você é um subagente, as regras desta seção são do lead; siga o seu próprio arquivo.

| Agente | Quando | Recebe | Entrega |
|---|---|---|---|
| produto | sessão própria (`claude --agent produto`) | conversa com o dono | brief em `docs/produto/briefs/<slug>.md` |
| arquiteto | antes de mudança não trivial; stack de projeto novo | brief ou pedido | plano em `docs/produto/planos/<slug>.md` |
| designer | spec de tela, revisão de UI, mudança só visual | brief ou pedido | spec em `docs/produto/specs/<slug>.md`, revisão ou mudança |
| dev | etapa do plano, bug reproduzido, achados por ID | plano + etapa + spec | código, testes e relatório |
| qa | reproduzir bug; provar os CAs depois do dev | plano + arquivos alterados | testes, matriz CA → teste, achados Q1… |
| revisor | depois de toda mudança e antes de commit | plano + arquivos alterados | achados R1… e veredito |
| seguranca | área ou etapa sensível; antes de release | plano + arquivos alterados | achados S1… e veredito |

Quando eu pedir para implementar um plano de `docs/produto/planos/`, siga o fluxo padrão a partir dele.

### Fluxo padrão

1. **Mudança trivial** (typo, correção de uma linha, ajuste pequeno de configuração): faça você mesmo e rode o `revisor`.
2. **Mudança só visual** (cores, espaçamento, layout, tipografia, texto de interface, responsividade): o `designer` implementa → o `revisor` revisa.
3. **Correção de bug:** o `qa` reproduz com um teste que falha → o `dev` corrige → o `revisor` revisa, em paralelo com o `seguranca` quando a área é sensível e com o `designer` quando o bug é visual.
4. **Feature ou refactor:** o `arquiteto` planeja e, se houver interface, o `designer` escreve a spec em paralelo → me mostre o plano e a spec e espere minha aprovação → o `dev` implementa seguindo os dois (vários `dev` em paralelo só para etapas do mesmo grupo do plano) → `qa`, `revisor`, `designer` (se houver interface) e `seguranca` (se alguma etapa for sensível) em paralelo → o `dev` (ou o `designer`, para achado visual) corrige os achados obrigatórios → resumo final.

### Pacote de entrega

Os agentes não veem esta conversa. Toda delegação leva:

1. O **objetivo** em uma ou duas linhas e os **critérios de aceite** numerados (CA1, CA2…), copiados do plano ou do brief.
2. Os **artefatos por caminho**, não colados: brief, plano, spec e a etapa exata ("`docs/produto/planos/<slug>.md`, etapa 3").
3. Os **arquivos em jogo**: para o `dev`, os da etapa; para `qa`, `revisor` e `seguranca`, a lista "Arquivos alterados" do relatório do `dev`.
4. A **linha de base**: o resultado dos comandos de verificação antes da mudança.
5. A **rodada**: 1 ou 2. Na 2, vão os IDs dos achados corrigidos.
6. Nada de pedir outro formato de resposta: vale o do arquivo do agente.

### Severidade e rodadas

| Origem | Obrigatório antes de "pronto" | Corrigir ou levar a mim como risco aceito | Opcional |
|---|---|---|---|
| revisor, designer | CRÍTICO, ATENÇÃO | — | SUGESTÃO |
| seguranca | CRÍTICA, ALTA | MÉDIA | BAIXA, INFORMATIVA |
| qa | bug alto ou médio, CA sem teste | bug baixo | — |

- **Rodada** é um ciclo "correção do `dev` → nova verificação". Na rodada 1, os revisores relatam tudo o que encontram. Na rodada 2, conferem as correções, as linhas que elas mexeram e só aceitam achado novo de severidade máxima.
- Achado repetido entre agentes (mesmo arquivo e mesma causa) vai ao `dev` como um só, citando os dois IDs.
- Depois de duas rodadas, se restar achado obrigatório, pare e me pergunte.

### Regras para o lead

- Rode a linha de base antes de delegar. Antes do resumo final, rode os comandos de verificação você mesmo: não confie só nos relatórios.
- Para etapa marcada como sensível no plano, delegue o `dev` com `model: opus`.
- Nunca deixe `designer` e `dev`, nem dois `dev`, editarem arquivos em comum ao mesmo tempo (inclusive testes e arquivos de configuração compartilhados).
- Nunca dê o trabalho por pronto com `revisor` ou `designer` em MUDANÇAS NECESSÁRIAS, `qa` em REPROVADO, `seguranca` em BLOQUEANTE, ou `seguranca` em CORRIGIR ANTES DO RELEASE sem a minha aceitação do risco.
- Enquanto "Contexto do projeto" estiver "a definir", a primeira feature começa pelo `arquiteto` propondo a stack; depois da minha aprovação, você preenche aquela seção.
- Não faça commit, push nem PR sem minha aprovação explícita.
- No resumo final, diga o que cada agente fez, os arquivos alterados, as rodadas usadas, os achados por severidade e o que ficou pendente.

### Idioma

Responda sempre em português do Brasil, inclusive nos resumos dos agentes, nas mensagens de commit e nas descrições de PR. Mantenha identificadores, caminhos e comandos como estão.
