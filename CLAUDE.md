## Contexto do projeto

> **A definir** (parcial): dados de teste. Os demais itens foram verificados em 2026-11-03.

- **Produto:** **Etiqueta** (nome que aparece no `<title>` e no `<h1>` do `index.html`; antes "Mensagens Achadinhos"; não confundir com a cor de acento Etiqueta, token `--etiqueta`, nem com a etiqueta de afiliado do ML; ao falar da cor, diga "cor Etiqueta" ou `--etiqueta`), gerador de mensagens de ofertas ("achadinhos") para grupos de WhatsApp. O dono coleta produtos da Amazon e do Mercado Livre, escolhe um template e copia a mensagem pronta, sempre com link de afiliado. Uso local, uma pessoa, no computador. A visão fica em `docs/produto/visao.md` (a escrever na sessão `produto`).
- **Stack:** Python 3.14 só com a biblioteca padrão no servidor (`http.server` + `sqlite3`); `beautifulsoup4` e `lxml` na coleta da Amazon; front em HTML, CSS e JS puros num arquivo só, sem build; fontes Geist e Geist Mono pelo Google Fonts (sem internet, cai na fonte do sistema). Identidade visual em `Identidade visual — links de afiliado.pdf`; decisões de UI em `docs/produto/specs/ux-ui-identidade.md`. Sem manifesto de dependências.
- **Camadas e pastas:**
  - `servidor.py`: API REST (`/api/items`, `/api/config/<chave>`, `/api/fetch`, `/api/ml-sem-afiliado`) em http://localhost:8765/. Estático só de `/`, `/index.html` e `/testes/<nome>.test.html` (o resto dá 404). Só aceita `Host` `localhost`/`127.0.0.1` na porta; na API, só a própria origem e, para a coleta do ML, `https://lista.mercadolivre.com.br` e `https://www.mercadolivre.com.br` (GET, POST e PATCH em `/api/items`, `/api/items/<id>` e `/api/ml-sem-afiliado`). Escritas exigem `Content-Type: application/json` (415), corpo até 5 MB (413), `loja` `amazon`/`ml` e, no PATCH de `url`, link de afiliado (400). `/api/fetch` só busca `https` da Amazon. Banco e porta vêm de `ACHADINHOS_DB` e `ACHADINHOS_PORTA` (padrão: `achadinhos.db` e 8765). Plano: `docs/produto/planos/blindar-servidor.md`. **Regra de negócio.**
  - `coletar_amazon.py` e `buscas.json`: coleta da Amazon pelo terminal. **Regra de negócio.**
  - `achadinhos.db`: banco SQLite (tabela `items`, única por `loja`+`item_id`; tabela `config`). **Dados; nunca editar à mão.**
  - `index.html`: a interface inteira (estilos, marcação e JS que chama a API). O `designer` mexe só em estilo, marcação e textos; chamadas de API e lógica de dados ficam com o `dev`.
  - `mensagens.html` e `amazon.php`: cópia antiga do site na Hostinger. Não alterar.
  - A coleta do Mercado Livre roda no Chrome (Claude in Chrome), por causa do captcha; não há arquivo para ela no projeto. Contrato com o servidor: chamar a partir de `https://lista.mercadolivre.com.br` ou `https://www.mercadolivre.com.br`, sempre com `Content-Type: application/json`, `loja:'ml'` e campos de texto (`data` como objeto); excluir item não é permitido dessas origens (faça pelo site).
  - Pastas de regra de negócio que o `designer` não pode tocar: `servidor.py`, `coletar_*.py`, `buscas.json`, `*.db`.
- **Verificação:** `python3 -m py_compile servidor.py coletar_amazon.py` (passa); com o servidor no ar (`python3 servidor.py`), `curl -s -o /dev/null -w "%{http_code}" localhost:8765/api/items` deve dar 200. Testes do front: com o servidor no ar, `node testes/rodar.mjs copiar-imagem` deve imprimir `RESULTADO: OK` (exit 0). Requer Node 22+ (`WebSocket` nativo) e Chrome em `/usr/bin/google-chrome`; o runner abre o Chrome headless via CDP em tempo real (não use `--virtual-time-budget --dump-dom`, que sai antes do fim). Cada página fica em `testes/<nome>.test.html`, só faz GET na API real, usa itens falsos montados com `renderCard` e lê duas fotos reais dos CDNs (sem internet, esses 2 testes falham). Funções do front que precisam de teste ficam declaradas com `function`, para o iframe alcançar. Testes do servidor: `python3 testes/test_servidor.py -v` e `python3 testes/test_servidor_qa.py -v` (sobem o `servidor.py` como subprocesso, com banco temporário e porta livre; o `ambiente()` aponta os proxies para `127.0.0.1:9`, então nenhum teste sai para a rede). Para rodar a suíte do front contra código novo sem tocar no servidor real: copie o banco com `sqlite3 backup` (não `cp`, o banco está em WAL), suba `ACHADINHOS_DB=<cópia> ACHADINHOS_PORTA=8766 python3 servidor.py` e rode `PORTA=8766 node testes/rodar.mjs copiar-imagem`. Ao testar mutantes ou código antigo, exporte `http_proxy`/`https_proxy`/`ftp_proxy=http://127.0.0.1:9`: o `/api/fetch` acessa a rede de verdade.
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
