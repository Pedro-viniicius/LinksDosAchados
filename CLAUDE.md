## Contexto do projeto

> **A definir** (parcial): dados de teste. Os demais itens foram verificados em 2026-11-03.

- **Produto:** **Etiqueta** (nome que aparece no `<title>` e no `<h1>` do `index.html`; antes "Mensagens Achadinhos"; não confundir com a cor de acento Etiqueta, token `--etiqueta`, nem com a etiqueta de afiliado do ML; ao falar da cor, diga "cor Etiqueta" ou `--etiqueta`), gerador de mensagens de ofertas ("achadinhos") para grupos de WhatsApp. O dono coleta produtos da Amazon e do Mercado Livre, escolhe um template e copia a mensagem pronta, sempre com link de afiliado. Uso local, uma pessoa, no computador. A visão fica em `docs/produto/visao.md` (a escrever na sessão `produto`).
- **Stack:** Python 3.14 só com a biblioteca padrão no servidor (`http.server` + `sqlite3`); `beautifulsoup4` e `lxml` na coleta da Amazon; front em HTML, CSS e JS puros num arquivo só, sem build; fontes Geist e Geist Mono pelo Google Fonts (sem internet, cai na fonte do sistema). Identidade visual em `Identidade visual — links de afiliado.pdf`; decisões de UI em `docs/produto/specs/ux-ui-identidade.md`. Sem manifesto de dependências.
- **Camadas e pastas:**
  - `servidor.py`: API REST (`/api/items`, `/api/config/<chave>`, `/api/fetch`, `/api/ml-sem-afiliado`) em http://localhost:8765/. Estático só de `/`, `/index.html` e `/testes/<nome>.test.html` (o resto dá 404). Só aceita `Host` `localhost`/`127.0.0.1` na porta; na API, só a própria origem e, para a coleta do ML, `https://lista.mercadolivre.com.br` e `https://www.mercadolivre.com.br` (GET, POST e PATCH em `/api/items`, `/api/items/<id>` e `/api/ml-sem-afiliado`). Escritas exigem `Content-Type: application/json` (415), corpo até 5 MB (413), `loja` `amazon`/`ml` e, no PATCH de `url`, link de afiliado (400). `/api/fetch` só busca `https` da Amazon. Banco e porta vêm de `ACHADINHOS_DB` e `ACHADINHOS_PORTA` (padrão: `achadinhos.db` e 8765). Plano: `docs/produto/planos/blindar-servidor.md`. **Regra de negócio.**
  - `coletar_amazon.py` e `buscas.json`: coleta da Amazon pelo terminal (`python3 coletar_amazon.py buscas`). `buscas.json` é o mapa termo → aba (chaves: "Black Friday | Eletrônicos", "Eletrodomésticos", "Casa e Decoração", "Perfumes e Perfumaria"; termos em NFC, sem `|`). Progresso por termo em `coleta_amazon_feitos.txt` (`ACHADINHOS_FEITOS` troca o arquivo). **Regra de negócio.**
  - `migrar_categorias.py`: reorganiza a coluna `cat` dos itens a partir de `buscas.json` + `ALIAS`, com `--dry-run`, backup verificado em `backups/`, `--sim`/prompt "sim" no banco real e `--restaurar` (só com servidor e coleta parados; devolve o banco INTEIRO, inclusive `numeros`/`regras`/`envios` do disparo). Plano: `docs/produto/planos/eletronicos-e-coleta-ml.md`. **Regra de negócio.**
  - `classificar_lista.py` + `lista_whatsapp.json`: movem os 74 itens de "Lista WhatsApp" para "Black Friday | Eletrônicos" com `busca` por subtema (`--dry-run`, `--sim`, `--desfazer` reverte só esses 74). Rodar logo depois do `migrar_categorias.py` e antes de cadastrar qualquer número no disparo. **Regra de negócio.**
  - `disparo.py`: disparo automático (plano `docs/produto/planos/disparo-automatico.md`, spec `docs/produto/specs/disparo-automatico.md`): tabelas `numeros` (telefone e id de grupo: dado pessoal, só no banco local, mascarado na tela, nunca em log/URL/git), `regras` e `envios` (migração por `PRAGMA user_version`, só aditiva, feita em `criar_banco`); `montar_mensagem` é porte fiel do `buildMsg` (paridade em `testes/mensagens.test.html`); só sai link de afiliado (ML sem `meli.la` nunca sai; mensagem com qualquer outra URL não é criada); agendador em thread no `servidor.py` (`ACHADINHOS_DISPARO=0` desliga; `ACHADINHOS_TICK_SEG`, padrão 30); transporte `manual` (fila: o dono copia e cola) ou `falso` (`ACHADINHOS_TRANSPORTE`, `ACHADINHOS_TRANSPORTE_ARQUIVO`, só teste); rotas `/api/disparo/*` só da origem local. Detecção de links na mensagem é conservadora, token a token (NFKC, pontos parecidos, invisíveis, IP): títulos como `i.Phone` ou `55UN85CBPSA.BWZ` são recusados de propósito (14 itens reais). A montagem para em `LIMITE_MONTAGEM` (8.000 caracteres) e a mensagem acima de `MAX_MENSAGEM` (4.000) é pulada. Horário sem nenhuma mensagem grava `aviso` na regra (filtros, repetição ou link recusado); `recusados` (só em memória) sai no `GET regras` e na prévia com `"com_info": true`. Envio automático pelo WhatsApp fica para uma entrega 2 (o dono escolheu ficar no manual). **Regra de negócio.**
  - `achadinhos.db`: banco SQLite (tabela `items`, única por `loja`+`item_id`; tabela `config`). **Dados; nunca editar à mão.**
  - `index.html`: a interface inteira (estilos, marcação e JS que chama a API), incluindo a tela "Disparo automático" (`#telaDisparo`, textos em `TXT_DISPARO`, rotas por hash `#disparo`, `#disparo/nova`, `#disparo/regra/<id>`, `#historico`, `#numeros`; telefone e código do grupo mascarados, inteiros só no campo de edição). O `designer` mexe só em estilo, marcação e textos; chamadas de API e lógica de dados ficam com o `dev`.
  - `mensagens.html` e `amazon.php`: cópia antiga do site na Hostinger. Não alterar.
  - `coletar_ml.js`: coleta e afiliação do Mercado Livre, colado no console do DevTools (`ColetaML.coletar()` em `https://lista.mercadolivre.com.br`, `ColetaML.afiliar()` em `https://www.mercadolivre.com.br/afiliados/linkbuilder`); traz uma cópia de `buscas.json` entre marcadores, conferida por teste. Uso no `README.md`. **Regra de negócio.** Contrato com o servidor: chamar a partir de `https://lista.mercadolivre.com.br` ou `https://www.mercadolivre.com.br`, sempre com `Content-Type: application/json`, `loja:'ml'` e campos de texto (`data` como objeto; `titulo` até 500 caracteres e os demais campos até 200, senão 400); excluir item não é permitido dessas origens (faça pelo site).
  - Pastas de regra de negócio que o `designer` não pode tocar: `servidor.py`, `disparo.py`, `coletar_*.py`, `coletar_ml.js`, `migrar_categorias.py`, `classificar_lista.py`, `buscas.json`, `lista_whatsapp.json`, `*.db`.
- **Verificação:** `python3 -m py_compile servidor.py coletar_amazon.py disparo.py migrar_categorias.py classificar_lista.py` (passa); com o servidor no ar (`python3 servidor.py`), `curl -s -o /dev/null -w "%{http_code}" localhost:8765/api/items` deve dar 200. Testes do front: com o servidor no ar, `node testes/rodar.mjs copiar-imagem` deve imprimir `RESULTADO: OK` (exit 0). Requer Node 22+ (`WebSocket` nativo) e Chrome em `/usr/bin/google-chrome`; o runner abre o Chrome headless via CDP em tempo real (não use `--virtual-time-budget --dump-dom`, que sai antes do fim). Cada página fica em `testes/<nome>.test.html`, só faz GET na API real, usa itens falsos montados com `renderCard` e lê duas fotos reais dos CDNs (sem internet, esses 2 testes falham). Funções do front que precisam de teste ficam declaradas com `function`, para o iframe alcançar. Outras páginas do front: `node testes/rodar.mjs abrir-e-adicionar` e, sobre uma cópia já migrada, `PORTA=8766 node testes/rodar.mjs abas`. Testes Python: `python3 testes/test_servidor.py -v`, `test_servidor_qa.py`, `test_migrar_categorias.py`, `test_migrar_categorias_qa.py`, `test_coletar_amazon.py`, `test_coletar_amazon_qa.py`, `test_classificar_lista.py`, `test_classificar_lista_qa.py`, `test_disparo.py`, `test_disparo_servidor.py`, `test_disparo_qa.py`; páginas do front `mensagens` (contra o 8765), `disparo` e `disparo-qa` (só sobre servidor próprio com `ACHADINHOS_DISPARO=0`) e `disparo-integracao` (grava de verdade: só sobre banco temporário novo, migrado e sem número nem regra; recusa a 8765); Node: `node --test testes/coletar_ml.test.mjs` e `node --test testes/coletar_ml_qa.test.mjs` (sobem o `servidor.py` como subprocesso, com banco temporário e porta livre; o `ambiente()` aponta os proxies para `127.0.0.1:9`, então nenhum teste sai para a rede). Para rodar a suíte do front contra código novo sem tocar no servidor real: copie o banco com `sqlite3 backup` (não `cp`, o banco está em WAL), suba `ACHADINHOS_DB=<cópia> ACHADINHOS_PORTA=8766 python3 servidor.py` e rode `PORTA=8766 node testes/rodar.mjs copiar-imagem`. Ao testar mutantes ou código antigo, exporte `http_proxy`/`https_proxy`/`ftp_proxy=http://127.0.0.1:9`: o `/api/fetch` acessa a rede de verdade.
- **Dados de teste:** a definir. Para não mexer nos dados reais, rode contra uma cópia do `achadinhos.db` (o caminho está na constante `DB` em `servidor.py`). Coletas acessam Amazon e Mercado Livre de verdade: nunca rode em teste.
- **Regra do dono:** todo link gravado tem que ser de afiliado (Amazon `?tag=desejodemen01-20`; Mercado Livre `https://meli.la/...` da etiqueta `achadosmenicas`). Nunca troque um link de afiliado por um link comum.
- **Dado pessoal (LGPD):** não há dado de cliente. O `_chat.txt` em `WhatsApp Chat - AmazonLinks/` tem o nome do dono; não copie para logs.
- **Segredos:** nunca leia nem imprima `.env*` (exceto `.env.example`) nem arquivos de senha.
- **Docs que acompanham a mudança:** `README.md` (hoje só o título do repositório, `LinksDosAchados`) e `CLAUDE.md`.

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
