# Especificação de UI/UX: preço sempre atualizado

Plano: `docs/produto/planos/atualizar-precos.md` (CA1 a CA11, Decisão 8, etapas 6 e 7, "Decisões do dono"). Bases que valem sem repetir: `ux-ui-identidade.md` (tokens, cartão, foco), `abas-nichadas.md` (faixas de abas, `ORDEM_ABAS`) e `disparo-automatico.md` (tela do disparo, `confirmar()`).

## Objetivo e usuário
O dono, sozinho, no computador (às vezes no celular), manda ofertas a grupos de WhatsApp. O pior erro dele é mandar um preço que já mudou. A interface precisa (1) mostrar a idade do preço onde ele decide copiar, (2) dizer, sem ele ter de lembrar, como atualizar cada loja e quantos itens estão velhos, e (3) deixar claro por que o disparo pulou itens. **O site não roda lote**: Amazon e Shopee rodam no terminal e o ML no console do Chrome. O site só informa, ensina e mede.

## Fluxo
1. Na lista, a **faixa de preços** da aba diz "120 de 812 preços passam de 24 h" e os cartões mostram a idade do preço.
2. O dono clica "Como atualizar os preços" (na faixa) e abre o **quadro** logo abaixo dela.
3. Copia o comando da loja, roda no terminal (ou no console, no caso do ML) e volta.
4. Clica "Conferir de novo": as contagens são recarregadas e ele vê o que mudou.
5. Se quiser mais ou menos tolerância, muda "Quanto tempo o preço vale" no mesmo quadro (um número para tudo).
6. No disparo, o cabeçalho mostra o prazo em vigor com um atalho para o quadro; quando um horário fica sem mensagem por preço velho, o aviso da regra explica.

## Layout (mobile e desktop)

### Faixa `#faixaPrecos` e quadro `#quadroPrecos`
- **Faixa:** entre o contador `#count` e `#publicoBox`. Uma linha Legenda Mudo + botão `.linklike` "Como atualizar os preços". Oculta só se a aba não tem itens ou os itens ainda não carregaram. Em 320 px o botão desce para a linha de baixo.
- **Quadro:** `<details id="quadroPrecos">` logo abaixo da faixa, **fechado** por padrão, com `<summary>` "Como atualizar os preços". O botão da faixa abre o quadro e põe o foco no `summary` (sem rolagem brusca: `scrollIntoView({block:'nearest'})`). Escolhido em vez de tela ou diálogo porque não há mais job nem progresso: é consulta e cópia, e deve ficar ao lado dos cartões velhos. Largura do conteúdo da lista; texto corrido até ~70 caracteres.
- Atalho de rota `#precos`: mostra a lista com o quadro aberto (usado pelo cabeçalho do disparo). Só abre o `details`; não é tela.

Ordem vertical dentro do quadro:
1. **Apoio** (parágrafo): "O site não busca preços sozinho. Cada loja se atualiza fora dele, com o comando abaixo. Depois, clique em Conferir de novo."
2. **Quanto tempo o preço vale** (`fieldset`): `input type=number` "Horas" (`min=1 max=168 step=1 inputmode=numeric`, padrão 24), botão `secondary` "Salvar prazo", ajuda `.ajuda` (`aria-describedby`) e `role=status` para o resultado. Fica aqui, e não na regra, porque o número vale para o disparo, o cartão, o filtro e a API v1.
3. **Categoria dos comandos** (`select`, mesma lista e `optgroup` do filtro de aba; primeira opção "Todas as categorias"; padrão = aba ativa). Define o `--cat` dos comandos e as contagens do bloco.
4. **Três cartões de loja** (`.dcard`) em grade `repeat(auto-fit,minmax(min(100%,300px),1fr))`: 1 coluna de 320 a 600 px, 3 colunas a 1280. Ordem fixa de `LOJA`.
5. Rodapé: botão `secondary` "Conferir de novo" e `role=status` "Conferido às 14:32. Amazon: 40 com preço velho. Mercado Livre: 0. Shopee: 12."

### Cartão de loja (dentro do quadro)
Cabeçalho: `.badge` da loja e, à direita, onde roda: "No terminal" (Amazon, Shopee) ou "No console do Chrome" (ML), em texto.
Corpo, em `dl` Legenda/Mono: **Itens** · **Com preço velho** (e, se houver, "inclui 12 sem data") · **Preço mais antigo** (data). Depois:
- **Passo a passo** em `<ol>` curta (2 a 3 passos).
- **Comando** em `<code>` dentro de um bloco `.cmd` (fundo `--superficie`, borda 1 px `--linha-campo`, Mono, `white-space:pre-wrap; overflow-wrap:anywhere`, sem rolagem horizontal) e botão `secondary` "Copiar comando" ao lado (embaixo no celular, largura total, 44 px).
- **Tempo estimado** e **Se der captcha** em parágrafos curtos (Legenda). Textos na seção Textos; o que é estimativa diz "não medido".
- Mesma estrutura nas três lojas, para o dono achar tudo no mesmo lugar.

**Amazon:** comando `python3 atualizar_precos.py amazon --cat "ABA"` (sem `--cat` quando "Todas as categorias"). Tempo: cerca de 40 min para tudo pela página de busca (Perfumes e Perfumaria, cerca de 25 min), estimativa pelas pausas do código. Captcha ou bloqueio: o comando para com o progresso do dia salvo (saída 3); esperar de 15 a 30 min e rodar o mesmo comando de novo; se repetir, parar por hoje e dividir por categoria.

**Mercado Livre:** passos: abrir `https://lista.mercadolivre.com.br` no Chrome, colar o `coletar_ml.js` no console, rodar `ColetaML.atualizar({cat: "ABA"})`. Com "Todas as categorias" o bloco não mostra comando e diz "Escolha uma categoria acima: o Mercado Livre atualiza uma categoria por vez.". Tempo: depende dos termos da categoria (99 no total); não medido. Captcha: resolver na aba e chamar `atualizar` de novo; o progresso do dia fica no navegador. Nota: o Chrome precisa do "Acesso à rede local" liberado para o ML (já descrito no README).

**Shopee:** dois blocos, porque o dono ainda não tem a credencial da Open API.
- "Por enquanto": o `importar` do painel (`python3 coletar_shopee.py importar`; **argumentos exatos a confirmar com o dev, do README**), cerca de 1 a 2 min por termo, não verificado.
- "Quando a credencial chegar": `read -rs S; ACHADINHOS_SHOPEE_SECRET="$S" ACHADINHOS_SHOPEE_APP_ID=<id> python3 atualizar_precos.py shopee --cat "ABA"; unset S` (o Secret só no ambiente do comando; nunca no site). Categoria fora das 17 abas fica sem comando: "Essa categoria está fora das abas da coleta." Com "Todas as categorias", o bloco diz "Escolha uma categoria acima: a Shopee atualiza uma categoria por vez." e não mostra comando. Limite da API: o comando para com saída 3; esperar e rodar de novo.
- Frase fixa: "As credenciais ficam só no seu terminal. Este site nunca pede o Secret."

### Contagens (de onde saem)
Saem do `items` **já carregado no front** (`GET /api/items` traz `preco_em`): sem endpoint novo. Contagem por loja e categoria escolhida com `precoVelho(preco_em, horas, agora)`. "Preço mais antigo" é o menor `preco_em` válido do escopo. Itens sem preço (`preco` vazio, 353 na Amazon hoje) **não entram** nas contagens nem ganham linha de idade: nunca teriam data e travariam o "velho" para sempre. O relógio é o do navegador; `agora` entra como parâmetro para teste.

### Cartão de oferta: idade do preço
- Nova linha `.idade-preco` logo abaixo de `.price`, antes de `.meta`: `<time datetime title="03/11/2026 às 14:20">` em Legenda Mudo, `flex-wrap` com `gap: var(--s1) var(--s2)`. Sempre visível, também em dia.
- **Formato** (`textoIdadePreco(preco_em, agora)`; relativo pelo relógio do navegador, absoluto no `title` e no `datetime`):
  | Idade | Texto |
  |---|---|
  | < 1 h | Preço de agora há pouco |
  | mesmo dia | Preço de hoje, 14:20 |
  | dia anterior | Preço de ontem, 18:05 |
  | 2 a 29 dias | Preço de 03/11 (há 2 dias) |
  | 30 dias ou mais | Preço de 03/10 (há mais de 1 mês) |
  | nulo ou malformado | Idade do preço desconhecida |
- **Selo `.velho`** "Desatualizado" quando `precoVelho(...)` é verdadeiro (passou da validade, nulo ou malformado): Tinta, peso 500, borda 1 px `--linha-campo`, `--r-pill`, padding `0 var(--s2)`, `--t-rotulo`. Sem cor nova, sem ícone: o sinal é a palavra e a borda. Não uso `--falhou`: vermelho já significa erro de operação.
- **Amazon velha:** botão `secondary` pequeno "Atualizar preço" na própria linha (sai de "Mais ações" nesse estado). Resultado e erro em `<span class="idade-msg" role="status">` abaixo da linha. **ML e Shopee velhos:** nenhum botão no cartão; o texto é o mesmo e a faixa leva ao quadro. O "Atualizar preço" faz o PATCH que já existe (`fetchItem`), que grava `preco_em`; após o sucesso o front atualiza `preco_em` do item em memória e redesenha a linha.
- **Copiar** continua funcionando em cartão velho (decisão do dono), mas o toast avisa: "Mensagem copiada. Atenção: o preço é de 01/11; confira na loja." Em "Copiar todas da página": "24 mensagens copiadas. 6 estão com preço desatualizado."
- **Celular (320, 360, 375):** selo "Desatualizado" e, abaixo, "Preço de 01/11 (há 3 dias)" (cabe em 256 px); "Atualizar preço" na linha seguinte, largura total, 44 px. Cresce no máximo ~2 linhas. **Desktop (1280):** selo, texto e botão na mesma linha quando couber.

### Filtro e ordenação
- `select#fPreco` em `.filters`, `aria-label="Filtrar por idade do preço"`: "Todos os preços" · "Desatualizados (120)" · "Em dia (692)". Contagem segue loja, busca e título atuais. Entra no "Limpar filtros" e zera a página ao mudar.
- Em `#fOrdem`, opção "Preço mais antigo primeiro" (sem data primeiro).
- Lista vazia com "Desatualizados": `.vazio` positivo "Tudo em dia: nenhum preço desta categoria passa de 24 h." (o 24 acompanha o prazo), com "Ver todos" como link.

## Disparo (sem campo na regra)
- **Removido** da regra: "Idade máxima do preço", "Sem limite", o resumo "Preço até 24 h" no cartão da regra e o botão "Atualizar preços" no aviso.
- **Cabeçalho do disparo** (`#telaDisparo`, perto do título): uma linha Legenda Mudo "Preços valem 24 h para todas as regras." + `.linklike` "Como atualizar os preços" (vai para `#precos`). O 24 vem de `config.preco_validade_horas`. Não há campo aqui: o número se muda no quadro. Não depende de interpretar o texto do `aviso`.
- **`aviso` do servidor** (`AVISO_PRECO_VELHO`, o card da regra o mostra com "Atenção: " na frente, como hoje): `Nenhuma mensagem saiu: os itens que casam com esta regra têm preço de mais de {h} h. Atualize os preços.` Texto do plano mantido; cabe em duas linhas a 320 px. Some ao salvar a regra, como hoje.
- **Prévia com `com_info`:** quando `preco_velho` > 0, linha em `#dspPrevia`: "3 itens ficaram de fora por preço velho." (singular: "1 item ficou de fora por preço velho."). Mesmo padrão dos `recusados`. Sem `preco_velho`, nada.
- Testes de página do disparo: não acrescentar navegações por hash em `testes/disparo.test.html`; o atalho `#precos` se testa em `testes/precos.test.html`.

## Componentes
| Componente | Existente ou novo | Onde fica |
|---|---|---|
| Faixa `#faixaPrecos` | Novo (texto Legenda + `.linklike`) | `index.html` |
| Quadro `#quadroPrecos` (`details`, prazo, categoria, 3 cartões, "Conferir de novo") | Novo; reaproveita `.dcard`, `.badge`, `fieldset`, `.ajuda`, `.linklike` | `index.html` |
| Bloco `.cmd` + "Copiar comando" | Novo, só CSS com tokens | `index.html` |
| `.idade-preco`, `.velho`, `.idade-msg` | Novos | `renderCard` e CSS |
| `select#fPreco` e opção de ordem | Novos (estilo de `#fLoja`) | `.filters` |
| Linha de prazo no cabeçalho do disparo | Nova | `#telaDisparo` |
| `TXT_PRECOS` | Nova constante de textos | `index.html` |
| Tokens | Nenhum novo | `:root` |

## Estados
**Quadro:** fechado · aberto · carregando itens (contagens "Carregando…", `aria-busy`) · erro ao carregar os itens ("Não consegui ver as contagens. Tentar de novo", que chama `carregarOfertas`) · loja sem itens na categoria ("Nenhum item da Shopee nesta categoria.") · loja em dia ("Tudo em dia.", comando continua visível) · conteúdo longo (nome de categoria quebra em 2 linhas; `.cmd` quebra por `overflow-wrap:anywhere`).
**Prazo:** padrão (24) · digitando · inválido (`campoErro`: "Informe um número inteiro de 1 a 168.", bloqueia o salvar) · salvando (botão `aria-busy`) · salvo (`role=status` "Prazo salvo: 24 h. Contagens atualizadas.") · erro do servidor ("Não consegui salvar o prazo. Tente de novo.") · leitura falhou ou valor inválido na config ("Usando 24 h, o padrão." no `role=status`). Valor acima de 72: aviso suave "Com mais de 3 dias, o grupo pode receber preço que já mudou."
**Copiar comando:** padrão · copiado (`role=status` "Comando copiado.", some em 4 s) · falha ("Não consegui copiar. Selecione o texto e copie.").
**Conferir de novo:** padrão · carregando (`aria-busy`, "Conferindo…") · conferido (resumo com a hora) · erro (mesma mensagem de contagens).
**Faixa:** em dia · com velhos · oculta (sem itens ou carregando) · erro (some; a idade no cartão continua).
**Cartão de oferta:** em dia · velho · sem data · sem preço (sem linha de idade) · atualizando (botão `aria-busy`, "Buscando na Amazon…") · erro ("Não consegui atualizar: a Amazon não respondeu. Tente de novo." ou o texto atual do `fetchItem` para captcha) · sucesso ("Preço atualizado." e a linha vira "Preço de agora há pouco").

## Textos da interface (`TXT_PRECOS`)
| Onde | Texto |
|---|---|
| Faixa, com velhos | 120 de 812 preços desta categoria passam de 24 h. · [Como atualizar os preços] |
| Faixa, em dia | Todos os preços desta categoria têm menos de 24 h. · [Como atualizar os preços] |
| Quadro | Como atualizar os preços · O site não busca preços sozinho. Cada loja se atualiza fora dele, com o comando abaixo. Depois, clique em Conferir de novo. |
| Prazo | Quanto tempo o preço vale · Horas · Salvar prazo · Um número para tudo: disparo, cartões, filtro e API. Padrão: 24 h (de 1 a 168). · Prazo salvo: 24 h. Contagens atualizadas. · Informe um número inteiro de 1 a 168. · Não consegui salvar o prazo. Tente de novo. · Usando 24 h, o padrão. · Com mais de 3 dias, o grupo pode receber preço que já mudou. |
| Categoria dos comandos | Categoria dos comandos · Todas as categorias |
| Dados da loja | Itens · Com preço velho · inclui 12 sem data · Preço mais antigo · Nenhum item da Shopee nesta categoria. · Tudo em dia. |
| Onde roda | No terminal · No console do Chrome |
| Blocos | Passo a passo · Comando · Copiar comando · Comando copiado. · Não consegui copiar. Selecione o texto e copie. · Tempo estimado · Se der captcha |
| Amazon, tempo | Cerca de 40 min para tudo (Perfumes e Perfumaria, cerca de 25 min). Estimativa, não medida. |
| Amazon, captcha | O comando para e guarda o que já fez hoje. Espere de 15 a 30 min e rode o mesmo comando de novo. Se repetir, pare por hoje e divida por categoria. |
| ML, passos | 1. Abra https://lista.mercadolivre.com.br no Chrome. 2. Cole o conteúdo de coletar_ml.js no console. 3. Rode o comando abaixo. |
| ML, tempo e captcha | Depende dos termos da categoria; não medido. · Resolva o captcha na aba e rode o comando de novo; o progresso de hoje fica no navegador. |
| Shopee | Por enquanto · Quando a credencial chegar · Escolha uma categoria acima: a Shopee atualiza uma categoria por vez. · Cerca de 1 a 2 min por termo; não verificado. · No limite da API o comando para: espere e rode de novo. · As credenciais ficam só no seu terminal. Este site nunca pede o Secret. |
| Rodapé do quadro | Conferir de novo · Conferindo… · Conferido às 14:32. Amazon: 40 com preço velho. Mercado Livre: 0. Shopee: 12. · Não consegui ver as contagens. Tentar de novo |
| Cartão: idade | Preço de agora há pouco · Preço de hoje, 14:20 · Preço de ontem, 18:05 · Preço de 03/11 (há 2 dias) · Preço de 03/10 (há mais de 1 mês) · Idade do preço desconhecida · Desatualizado |
| Cartão: ação | Atualizar preço · Buscando na Amazon… · Preço atualizado. · Não consegui atualizar: a Amazon não respondeu. Tente de novo. |
| Toast ao copiar | Mensagem copiada. Atenção: o preço é de 01/11; confira na loja. · 24 mensagens copiadas. 6 estão com preço desatualizado. |
| Filtro | Todos os preços · Desatualizados (120) · Em dia (692) · Preço mais antigo primeiro · Tudo em dia: nenhum preço desta categoria passa de 24 h. · Ver todos |
| Disparo: cabeçalho | Preços valem 24 h para todas as regras. · Como atualizar os preços |
| Disparo: aviso (servidor) | Nenhuma mensagem saiu: os itens que casam com esta regra têm preço de mais de {h} h. Atualize os preços. |
| Disparo: prévia | 3 itens ficaram de fora por preço velho. · 1 item ficou de fora por preço velho. |

## Acessibilidade (WCAG 2.2 AA)
- **`aria-live`:** as contagens visíveis (faixa, dl dos cartões) não são `aria-live`. Só resultados de ação pontual usam `role="status"` (copiar, salvar prazo, conferir, `.idade-msg`); erro de salvar usa o mesmo, sem `alert`, porque o foco continua no botão. Não há barra de progresso.
- **Foco:** o botão da faixa abre o `details` e leva o foco ao `summary`; "Conferir de novo" e "Copiar comando" mantêm o foco no próprio botão (não somem). Ao redesenhar contagens, o `render()` devolve o foco por `guardarFoco`/`devolverFoco`.
- **Teclado:** `details`, `select`, `input`, botões nativos; ordem: prazo, categoria, cartões (comando, copiar), conferir.
- **Código copiável:** `<code>` selecionável, com `tabindex` desnecessário; o botão é o caminho principal, e o texto selecionável é a alternativa se a área de transferência falhar.
- **Cor nunca é o único sinal:** "Desatualizado" é palavra + borda; "Com preço velho" é rótulo e número.
- **Contraste:** Tinta e Mudo sobre Superfície/Papel ≥ 4,5:1; bordas e foco ≥ 3:1, claro e escuro só por tokens. Etiqueta continua só em Copiar, aba ativa, desconto e foco.
- **Alvos:** 36 px no desktop, 44 px no celular (`--alvo`), inclusive "Atualizar preço", "Copiar comando" e o `summary`.
- **Rótulos:** `label` no campo de horas; `aria-label` no `select#fPreco`; "Copiar comando" com `aria-label="Copiar comando da Amazon"` (por loja); botão do cartão com `aria-label="Atualizar preço de {título}"`; `<time datetime>` com `title` absoluto (a data de 2 a 29 dias já aparece no texto, porque `title` não é confiável no toque).
- **Movimento:** nada animado além do que `prefers-reduced-motion` já desliga.
- **Sem rolagem horizontal** de 320 a 1280 px (SC 1.4.10): `.cmd` quebra linha, grade de cartões em 1 coluna no celular.
- A idade relativa ("há 2 dias") só muda quando o cartão é redesenhado; não é relida pelo leitor.

## Critérios de aceite visuais
- **CA-P1** Cada cartão com preço mostra uma linha de idade com um dos seis textos da tabela; passada a validade, nulo ou malformado, aparece o selo "Desatualizado" em palavra e borda, sem cor nova.
- **CA-P2** Em 320, 360 e 375 px a linha de idade ocupa no máximo 2 linhas mais o botão em largura total, sem rolagem horizontal; em 1280 px cabe em uma linha quando possível.
- **CA-P3** A faixa leva ao quadro "Como atualizar os preços"; o quadro mostra, para Amazon, Mercado Livre e Shopee, o comando com "Copiar comando", o tempo estimado, o que fazer em captcha e a contagem de itens com preço velho. Nenhum botão do site dispara lote.
- **CA-P4** "Quanto tempo o preço vale" lê e grava `config/preco_validade_horas` (padrão 24, de 1 a 168, erro de campo fora da faixa); a regra do disparo não tem campo de idade.
- **CA-P5** "Conferir de novo" recarrega os itens e atualiza as contagens, com resultado em `role=status`.
- **CA-P6** O cabeçalho do disparo mostra o prazo e leva ao quadro; a prévia com `preco_velho` > 0 diz quantos itens ficaram de fora; o `aviso` usa o texto de `AVISO_PRECO_VELHO`.
- **CA-P7** Nenhuma contagem visível é `aria-live`; resultados pontuais usam `role=status`.
- **CA-P8** O filtro "Desatualizados" e a ordem "Preço mais antigo primeiro" funcionam com loja, busca e título, e "Limpar filtros" os zera.
- **CA-P9** Copiar e "Copiar todas da página" avisam quando há preço desatualizado.
- **CA-P10** Sem token novo; contraste ≥ 4,5:1 (texto) e ≥ 3:1 (bordas, foco) em claro e escuro.

## O que o dev precisa implementar
1. `TXT_PRECOS` (inclui `comandos` por loja, com o `importar` da Shopee tirado do README) e as funções globais, declaradas com `function`: `textoIdadePreco(preco_em, agora)` e `precoVelho(preco_em, horas, agora)`. `precoVelho` espelha `disparo.preco_recente`: `fullmatch` do formato ISO, nulo ou malformado conta como velho. Um helper devolve o texto absoluto do `title`.
2. Leitura de `GET /api/config/preco_validade_horas` (aceitar só inteiro de 1 a 168, senão 24) e gravação por `PUT /api/config/preco_validade_horas`; manter o valor numa variável do front, usada por todas as funções.
3. `renderCard`: linha `.idade-preco` (só com preço), selo, "Atualizar preço" no estado velho da Amazon, `.idade-msg`; `fetchItem` escreve em `.idade-msg` e atualiza `preco_em` do item em memória.
4. Faixa `#faixaPrecos`, quadro `#quadroPrecos` com prazo, categoria, cartões, "Copiar comando" e "Conferir de novo"; contagens calculadas do `items` carregado (sem endpoint novo); atalho `#precos` que abre o quadro.
5. `select#fPreco`, opção de ordem, "Limpar filtros", avisos de cópia em `copiar` e "Copiar todas".
6. Disparo: linha de prazo no cabeçalho; remover qualquer campo de idade da regra; mostrar `preco_velho` da prévia `com_info`; o `aviso` já vem do servidor.
7. Testes: `testes/precos.test.html` sem navegação por hash (idade, `precoVelho` com relógio injetado, filtro, cartão em seus estados, contagens e o quadro com itens falsos); não mexer em `testes/disparo.test.html` além do necessário.
8. Servidor (fora da apresentação, já no plano): `preco_em` no `GET /api/items`, `AVISO_PRECO_VELHO` e `preco_velho` na prévia, `config.preco_validade_horas`.

## Arquivos de apresentação afetados
`index.html` (CSS, marcação, `renderCard`, `fetchItem`, `filtrarItens`/`filtrada`, "Limpar filtros", `#telaDisparo`, `TXT_*`, `rotear`) e `testes/precos.test.html`. Componente compartilhado alterado: `renderCard` (todos os cartões com preço ganham uma linha) e `.filters` (um `select` a mais; em 320 px ficam em coluna, como os outros). `confirmar()` não muda; não há tela nova.

## Perguntas em aberto
1. **Itens sem preço:** a spec assume que não entram nas contagens nem têm linha de idade (353 na Amazon hoje). Dev confirma que o front consegue testar `preco` vazio no item.
2. **`importar` da Shopee:** os argumentos exatos do `coletar_shopee.py importar` (README, etapa 7). A spec não inventa flag.
3. **Tempo do ML:** não há medida; o texto diz "não medido" até o primeiro lote real.
4. **Itens no front:** a spec assume que `GET /api/items` entrega todos os itens ao front (é assim em `carregarOfertas`). Se algum dia houver paginação no servidor, as contagens precisarão de endpoint.

**Fechadas por plano e dono:** Q1 (sem regras com idade), Q2 (prazo único em `config`), Q3 (aviso e `preco_velho` do plano; sem `aviso_tipo`, o atalho fica no cabeçalho), Q4, Q6 e Q8 (não há job), Q5 (nada é marcado nem apagado; selo "Sumiu da loja" retirado), Q7 (passos no quadro, sem pedir o Secret), Q9 (o piso da Amazon vale na coleta; o texto "O que significa" saiu com os contadores).
