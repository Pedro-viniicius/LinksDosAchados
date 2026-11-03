# Especificação de UI/UX: gênero nas categorias e melhoria da interface

Pedido do dono: "Coloca uma separação de masculino e feminino também nas categorias que existem coisas para os dois sexos, melhore o UX/UI".

## Decisões do dono (aprovadas) e corte da entrega
Plano: `docs/produto/planos/genero-nas-categorias.md`.
- **Gênero só na aba "Perfumes e Perfumaria"** (hoje: feminino 696, masculino 966, unissex 178, sem gênero 1.211). Valores do dado: `feminino`, `masculino`, `unissex`, `sem` (não há "Infantil"). Campos do item: `genero` e `genero_origem` (`titulo`, `busca`, `manual` ou vazio). O front não guarda lista de abas: a aba tem gênero quando seus itens têm 2 ou mais valores (hoje só Perfumes).
- **Correção à mão entra agora** (A2): "Mais ações" do cartão, `PUT /api/items/<id>/genero` com o valor ou `null` (automático).
- **Regra do disparo:** escolha única na tela, gravada como lista (`generos`; `[]` = todos). Vale só para categorias com gênero; as outras passam inteiras.
- **Entram agora:** Parte A inteira (A1 e A2) + **M1, M3, M5, M6, M7**. **Entrega 2:** M2, M4, M8 (e o renome "Copiar todas da página", que fica como está). Cada item e cada CA-V traz a marca **[AGORA]** ou **[ENTREGA 2]**.

A spec tem duas partes:
- **Parte A (gênero)**: o pedido literal. CA-V1 a CA-V12 (A1) e CA-V23 a CA-V28 (A2, correção à mão). Todos [AGORA].
- **Parte B (melhorias gerais)**: M1 a M8. CA-V13 a CA-V22. Sem feature nova além do gênero: tudo é reorganizar, esclarecer ou dar retorno ao que já existe.

## Objetivo e usuário
O dono, sozinho, no computador (às vezes no celular), monta mensagens de ofertas para grupos de WhatsApp. Ele precisa separar "para ela" de "para ele" sem passar por 3.051 itens de Perfumes, e achar, copiar e colar rápido.

## O que vi (revisão heurística, cópia do banco, 320 e 1280 px, claro)
Capturei a página principal (aba padrão, Black Friday | Eletrônicos, 3.110 itens) em 320 e 1280 px e a tela do disparo em 320 e 1280 px. Não vi: a aba Perfumes (a captura em linha de comando abre sempre a aba padrão), o modo escuro nesta rodada, nem regras e números do disparo (a cópia do banco não tem nenhum; revisei esses estados só pelo código). O que está bom e deve ficar: identidade, uma ação principal por cartão, "Mais ações" recolhido, selo de loja neutro, formulário da regra em 5 blocos com "Avançado" recolhido.

---
# PARTE A: Gênero [AGORA]

## A1. Separação por público

## Fluxo
1. O dono abre uma aba que tem gênero (ex.: Perfumes e Perfumaria, a única hoje). Entre as abas e os filtros aparece o controle **Público**: `Todos · Feminino · Masculino · Unissex`, cada opção com a contagem.
2. Escolhe "Feminino": a lista, o contador de páginas e o "Copiar da página" passam a valer só para o feminino. A escolha fica lembrada para aquela aba.
3. Troca para outra aba sem gênero (ex.: Eletrodomésticos): o controle some e nada filtra por gênero. Volta a Perfumes: a escolha anterior está lá.
4. No disparo, o dono marca em que público a regra envia (padrão "Todos").

## Layout
### Controle "Público" (página principal)
- **Onde:** logo abaixo das abas de categoria, acima da linha de filtros, alinhado à esquerda. Só existe na aba ativa se ela tiver gênero (aba com pelo menos dois valores de `item.genero` entre seus itens; o dev calcula com `abaTemGenero`, sem lista fixa de abas no código).
- **Forma:** `fieldset` com legenda visível "Público" (Rótulo, caixa-alta, Mudo, igual ao `.lbl`) e `input type="radio"` nativos, estilizados como **controle segmentado** (botões encostados, raio `--r`). Reaproveita o padrão `.chips.seg` já usado em "Ordem de envio", com a variante abaixo.
- **Por que segmentado e não mais uma fileira de pílulas:** as abas já são pílulas com Etiqueta clara. Duas fileiras iguais disputam o acento (regra de ~5% de Etiqueta) e o dono não distingue "aba" de "filtro". O público é filtro de segundo nível: neutro.
- **Opção selecionada:** fundo Tinta e texto `--sobre-tinta` (contraste ~16:1), peso 600 e "✓" antes do texto (cor não é o único sinal). Não selecionada: fundo Superfície, borda `--linha-campo`, texto Tinta. Contagem em Mono (`--t-mono-p`), Mudo na opção inativa e herdando a cor na ativa.
- **Contagens:** de cada opção, para a aba ativa **respeitando os filtros de loja e de título** (mas não o próprio público). Assim o número é o que o dono vai ver ao clicar. "Todos" = soma de tudo, incluindo itens sem gênero.
- **Opção com zero:** continua habilitada, com "0" (previsibilidade; o vazio explica, ver Estados).
- **Itens sem gênero** (em Perfumes são 1.211, ~40%): aparecem só em "Todos". Se houver ao menos um na aba (considerando os mesmos filtros; em Perfumes sempre), entra uma quinta opção **"Sem gênero"** no fim, para que nada fique escondido; se não houver nenhum, a opção não existe (sinal-ruído).
- **320 px:** grade de 2 colunas (`repeat(2,1fr)`), cada opção com no mínimo 44 px de altura; o texto e a contagem cabem ("Masculino 1.020" em ~148 px). Sem rolagem horizontal. 375 px e acima: uma linha se couber, senão quebra em linhas completas (`flex-wrap`).
- **Memória por aba:** `localStorage` com chave por aba (ex.: `genero:<aba>`). Se o valor salvo não existir mais na aba (ex.: "Sem gênero" zerou), cai em "Todos". Trocar de aba, de público ou de filtro volta à página 1.
- **Interação com "Todas as buscas":** o select de busca passa a listar só as buscas que têm item no público escolhido (sem isso, "Perfume masculino importado" aparece com o público "Feminino" e dá lista vazia).

### Selo no cartão
- Apenas em **"Todos"**, o cartão mostra o gênero em texto, na linha do topo: `AMAZON · FEMININO · Perfume feminino importado` (mesmo `.badge`, Mudo, caixa-alta, sem cor e sem ícone). Item sem gênero não mostra nada.
- **Corrigido à mão** (`genero_origem` = `manual`): o selo ganha ` · corrigido` (ex.: `FEMININO · CORRIGIDO`), e item corrigido para "sem gênero" mostra só `CORRIGIDO` (`title="Público corrigido à mão"`). Aparece também com um público escolhido, porque aí é o único selo e ajuda o dono a ver o que já mexeu. Itens automáticos não mostram origem (ruído).
- Com um público escolhido, o selo de gênero **não aparece** (todos os cartões teriam o mesmo; seria ruído), salvo o "corrigido" acima.
- Justificativa: em "Todos" a lista mistura os públicos e o dono precisa saber a qual grupo cada mensagem vai antes de copiar. O texto da busca nem sempre diz (ex.: "Dior Sauvage"). Nas abas sem gênero o selo não existe.
- Em 320 px o selo cabe antes da busca, que já trunca com reticências (`.busca`).

### Formulário da regra do disparo
- No bloco "2. O que enviar", entre "Lojas" e "Ordem de envio": campo **"Público"** (escolha única; grava `generos`: `[]` em "Todos", `[valor]` nos demais) com `radio` em chips (mesmo `htmlChip('radio', ...)` e `.chips.seg` de "Ordem de envio"): `Todos · Feminino · Masculino · Unissex`. Padrão **Todos**. Ajuda (Legenda Mudo): "Vale só para categorias que separam por público, como Perfumes e Perfumaria. Nas outras, a regra envia tudo."
- Regra existente abre em "Todos" (não muda o que já envia).
- Contador do formulário (`#f-contador`, "N itens disponíveis") já passa a respeitar o público, só nas categorias com gênero (as outras entram inteiras). Se nenhuma categoria marcada tem gênero, o campo continua visível e a ajuda já diz que não terá efeito (não esconder campo que o dono já viu).
- Cartão da regra: o resumo ganha o público só quando não for "Todos": `Perfumes e Perfumaria · Feminino · Todas as lojas`. "Sem gênero" não é opção da regra.
- Escolha única (rádio) e não caixas de seleção (decisão do dono): rádio mantém 4 opções em vez de 7 combinações (Lei de Hick). Se pedirem "Feminino + Unissex" depois, só a tela muda (o dado já é lista).

## A2. Corrigir o público de um item à mão [AGORA]
**Onde:** dentro de "Mais ações" do cartão, só em cartões de aba com gênero (cartões de outras abas não mostram o campo). Fica na linha `.rare`, junto de "Mover para", com o mesmo padrão `.lbl` + `select`:
`PÚBLICO [Automático (Feminino) ▾]`
- **Opções:** `Automático (<resultado atual>)`, Feminino, Masculino, Unissex, Sem gênero. A opção "Automático" mostra entre parênteses o que a classificação automática dá hoje, para o dono ver o que está desfazendo; quando o item está corrigido à mão, o valor selecionado é o corrigido, e "Automático" continua oferecido. (O dev obtém o automático pela mesma regra do servidor: se o servidor não devolver o valor automático de um item corrigido, mostrar só "Automático", sem parênteses.)
- **Por que select e não botões:** é ação rara, dentro de "Mais ações" (Hick); um select nativo é acessível e coerente com "Mover para".
- **Ao escolher:** o select fica desabilitado com `aria-busy="true"` até a resposta do `PUT` (`null` para "Automático"). Sem recriar o cartão (preserva "✓ Mensagem copiada", foco e o painel aberto).
- **Sucesso:** o selo do cartão atualiza ("corrigido" aparece ou some); toast "Público salvo: Masculino." (ou "Público voltou ao automático."); as contagens do controle "Público" da página atualizam. Se o novo valor não bate com o público escolhido na página, **o cartão fica onde está** (não some sob o cursor) e a linha de status do cartão diz: "Agora é Masculino. Sai desta lista quando você trocar de página ou de filtro." O cartão sai da lista no próximo `render()`.
- **Erro:** o select volta ao valor anterior, reabilita, e a linha de status do cartão (`.status.err`, `role="status"`) mostra: sem servidor, "Não consegui falar com o servidor. Verifique se ele está aberto e tente de novo."; 404, "Este item não existe mais. Recarregue a página."; 400 ou outro, "Não consegui salvar o público. Tente de novo." Não usa `alert()` nem perde o foco.
- **Acessibilidade:** `label` visível "Público" associado; o nome acessível inclui o título ("Público de <título>") só se o `aria-label` começar pelo texto visível; resultado anunciado pela linha `role="status"` do cartão; select nativo (setas e Enter); alvo 36/44 px; selo "corrigido" é texto, não cor.
- **Estados:** padrão (Automático), corrigido (valor escolhido), carregando (desabilitado, `aria-busy`), sucesso, erro, item em aba sem gênero (campo ausente).

## Componentes
| Componente | Existente ou novo | Onde fica |
|---|---|---|
| Campo "Público" em "Mais ações" (select) | Existente (`.lbl` + select, como "Mover para") | `index.html`, `renderCard` |
| Controle segmentado "Público" (rádio nativo) | Novo, variante de `.chips.seg` (`.seg-filtro`) | `index.html` (CSS e marcação) |
| Campo "Público" na regra | Existente (`htmlChip('radio')`, `.chips.seg`) | `index.html`, `htmlFormRegra` |
| Selo de gênero no cartão | Existente (`.badge`), sem variante de cor | `index.html`, `renderCard` |
| Tokens | Nenhum novo (Tinta, `--sobre-tinta`, `--linha-campo`, Mono) | `:root` |

## Estados (gênero)
- **Padrão / hover / foco / ativo:** hover em opção inativa: borda `--mudo`; foco: anel `--foco` 2 px no segmento inteiro (`input:focus-visible+span`); ativo (selecionado) como descrito. Sem estado desabilitado.
- **Vazio** (gênero com 0 após filtros): no lugar do grid, o vazio da M3 com a frase "Nenhuma oferta para Feminino com esses filtros." e o botão "Limpar filtros".
- **Carregando:** o controle só aparece depois que os itens chegam (ver M3).
- **Aba sem gênero:** controle ausente; o valor lembrado de outra aba não vaza para ela.
- **Conteúdo longo:** contagens de até 5 dígitos ("10.000") cabem; o rótulo é fixo e curto.
- **Modo escuro:** a opção ativa usa os tokens (`--tinta` claro sobre `--sobre-tinta` escuro): inverte sozinho, contraste ≥ 12:1.

## Textos da interface (gênero)
| Onde | Texto |
|---|---|
| Legenda do controle | Público |
| Opções | Todos · Feminino · Masculino · Unissex · Sem gênero |
| Anúncio ao trocar (`role="status"`) | Mostrando 812 ofertas: Feminino |
| Vazio | Nenhuma oferta para Feminino com esses filtros. |
| Selo no cartão | FEMININO · MASCULINO · UNISSEX (caixa-alta via CSS; o texto no DOM é "Feminino") |
| Campo da regra (legenda) | Público |
| Ajuda do campo | Vale só para categorias que separam por público, como Perfumes e Perfumaria. Nas outras, a regra envia tudo. |
| Resumo da regra | `... · Feminino · ...` (omitido em "Todos") |
| Campo no cartão (Mais ações) | Público: Automático (Feminino) · Feminino · Masculino · Unissex · Sem gênero |
| Selo corrigido | FEMININO · CORRIGIDO (`title`: Público corrigido à mão) |
| Toast de sucesso | Público salvo: Masculino. / Público voltou ao automático. |
| Status ao sair do filtro | Agora é Masculino. Sai desta lista quando você trocar de página ou de filtro. |
| Erros do cartão | Não consegui falar com o servidor. Verifique se ele está aberto e tente de novo. · Este item não existe mais. Recarregue a página. · Não consegui salvar o público. Tente de novo. |

## Acessibilidade (gênero)
- `fieldset`/`legend` e `radio` nativos: setas movem a seleção, Tab entra e sai do grupo; sem ARIA extra.
- Alvos: 36 px no desktop (padrão `--alvo`), 44 px com `pointer:coarse`.
- Contraste: ativo Tinta/`--sobre-tinta`; inativo Tinta sobre Superfície; contagem Mudo ≥ 4,5:1; borda do segmento `--linha-campo` (3:1, SC 1.4.11).
- Selecionado não depende de cor: inversão de fundo, peso e "✓".
- O resumo "Mostrando N ofertas: Feminino" fica numa região `aria-live="polite"` única (a mesma da M2), para o leitor de tela saber o efeito.
- Foco não se perde ao escolher (o controle não é recriado, só atualiza `checked` e contagens; ver M5).

## Critérios de aceite visuais (Parte A)
- **CA-V1** Na aba Perfumes aparece "Público" com Todos, Feminino, Masculino, Unissex e a contagem em cada; em abas sem gênero o controle não existe no DOM.
- **CA-V2** Escolher "Feminino" mostra só itens femininos, a paginação e o "Copiar da página" refletem a lista filtrada, e a página volta à 1.
- **CA-V3** A escolha por aba é lembrada ao trocar de aba e ao recarregar a página; valor que deixou de existir cai em "Todos".
- **CA-V4** As contagens respeitam loja e título (não o próprio público); "Todos" = soma incluindo sem gênero.
- **CA-V5** Item sem gênero só aparece em "Todos" e em "Sem gênero"; essa opção só existe se houver ao menos um.
- **CA-V6** O select de buscas só lista buscas com item no público escolhido.
- **CA-V7** O selo de gênero aparece no cartão somente em "Todos", em texto Mudo sem cor, e some com um público escolhido.
- **CA-V8** Em 320 px o controle ocupa 2 colunas, alvos ≥ 44 px, sem rolagem horizontal; em 1280 px fica em uma linha.
- **CA-V9** Opção selecionada tem contraste ≥ 4,5:1 (texto) e é distinguível sem cor (✓ e peso), em claro e escuro.
- **CA-V10** Só por teclado: Tab chega ao grupo, setas trocam a opção, o foco permanece no controle e é visível.
- **CA-V11** Na regra do disparo, "Público" é rádio com "Todos" marcado por padrão; regra antiga abre em "Todos"; o resumo da regra só cita o público quando não é "Todos".
- **CA-V12** Etiqueta (laranja) continua só na aba ativa, no desconto, no "Copiar" e no foco: o controle de público não usa o acento.

**Correção à mão (A2), todos [AGORA]:**
- **CA-V23** Em cartão de Perfumes, "Mais ações" mostra o campo "Público" com Automático (<resultado>), Feminino, Masculino, Unissex e Sem gênero; em cartão de outra aba o campo não existe.
- **CA-V24** Escolher um valor desabilita o campo com `aria-busy` até a resposta e, no sucesso, atualiza o selo, as contagens e mostra o toast, sem recriar o cartão (o foco permanece no campo e "Mais ações" continua aberto).
- **CA-V25** Escolher "Automático" envia `null`, remove o selo "corrigido" e volta ao valor automático.
- **CA-V26** Item corrigido mostra "CORRIGIDO" no selo (em "Todos" junto do gênero; com público escolhido, sozinho); itens automáticos não mostram origem.
- **CA-V27** Se o novo valor tira o cartão do público filtrado, o cartão permanece e a linha de status explica que sai da lista ao trocar de página ou filtro.
- **CA-V28** Em falha (sem servidor, 404, 400), o campo volta ao valor anterior e a linha de status mostra a mensagem em pt-BR; sem rolagem horizontal em 320 px e contraste ≥ 4,5:1 nos textos novos.

---
# PARTE B: Melhorias gerais

**Agora:** M1, M3, M5, M6, M7. **Entrega 2:** M2, M4, M8.

Prioridade: **P1** alto impacto, **P2** médio, **P3** sugestão. Todos só de apresentação; o que exige JS de estado está marcado e vai para o `dev`.

## M1 (P1) [AGORA] Cabeçalho que não come a tela
**Problema:** o cabeçalho é `sticky`. Em 320 px ocupa ~320 de 700 px de altura (logo, contador em 2 linhas, Template, 4 botões em coluna), nada além dele cabe ao rolar; em 1280 px são ~100 px fixos. Quatro botões de peso igual (3 ghost + 1 contorno) sem hierarquia (Hick), e "Copiar todas da página" no cabeçalho não diz de qual página fala.
**Proposta:**
- Linha única do cabeçalho: logo à esquerda; à direita, "Adicionar links" e "Disparo automático" (navegação e ação frequente). Altura ≤ 64 px, sticky só a partir de 601 px; **abaixo de 600 px o cabeçalho não é sticky** (rola junto).
- **Template, "Editar templates" e "Copiar todas da página"** (nome mantido, o renome é da entrega 2) saem do cabeçalho e vão para uma **barra de lista simples** logo acima do grid (uma linha que quebra no celular, 44 px), porque só afetam a mensagem dos cartões. Na entrega 2 (M2) essa barra ganha o resumo e a paginação. No celular, "Adicionar links" e "Disparo automático" viram dois botões lado a lado abaixo do logo (uma linha, 44 px).
- O **contador de totais** (`#count`) sai do cabeçalho e vira uma linha Legenda Mudo abaixo das abas ("8.381 itens no total · ..."), mantendo o texto e a regra de omitir loja zerada.
- Os painéis "Adicionar links" e "Editar templates" continuam abrindo abaixo do cabeçalho; não mudam.

## M2 (P1) [ENTREGA 2] Barra de lista: resultado, escopo e paginação
**Problema:** a paginação repete 4 botões no topo e no rodapé (no topo, "Primeira" e "Anterior" ficam desabilitados na página 1) e é a única forma de andar entre até 130 páginas; não há salto. Não há resumo do que está na tela.
**Proposta:** uma barra logo acima do grid, uma linha (quebra no celular):
- Resumo à esquerda, `aria-live="polite"`: "Mostrando 1 a 24 de 3.110 ofertas" (com filtro: "... de 812 ofertas, filtradas").
- À direita: "Copiar as 24 da página" (contorno; o número muda com a página, e é o que o botão copia). Renomeia "Copiar todas da página" (renome só nesta entrega).
- **Paginação** só no rodapé, mais curta: `‹ Anterior · Página [ 3 ] de 130 · Próxima ›`, onde o número é um campo `input type="number"` (rótulo "Ir para a página", Enter vai) em vez de "Primeira"/"Última" (o salto os substitui). No topo fica só o resumo. Com uma página só, nenhuma paginação.
- Ao trocar de página: rola até o topo da barra de lista (não da página, para o dono não reaprender as abas a cada vez), e o foco vai ao resumo (`tabindex="-1"`).

## M3 (P1) [AGORA] Estados de carregamento, vazio e erro
**Problema (confirmado no código):** ao abrir, a página fica em branco até as ~8 mil ofertas chegarem; se a API falhar a página fica em branco para sempre (a rotina de início não trata erro); filtro sem resultado deixa o grid vazio, sem mensagem.
**Proposta:**
- **Carregando:** em lugar do grid, texto "Carregando as ofertas…" em `role="status"`, com `aria-busy` no `main`; abas e filtros só aparecem depois.
- **Erro:** bloco `.vazio` com "Não consegui carregar as ofertas. Verifique se o servidor está aberto e tente de novo." e botão "Tentar de novo" (mesmo padrão do disparo, `TXT_DISPARO.erroCarga`).
- **Sem resultado:** bloco `.vazio`: "Nenhuma oferta com esses filtros." + botão "Limpar filtros" (volta loja, busca, ordem, título e público ao padrão, sem trocar de aba).
- **Aba sem itens:** "Esta categoria ainda não tem ofertas. Use Adicionar links para incluir."

## M4 (P2) [ENTREGA 2] Filtros com hierarquia e retorno
**Problema:** quatro controles com o mesmo peso; a busca por título (a mais usada) é a última; "Ordem de coleta" não diz que é ordenação; o select de 65 buscas não mostra quantos itens cada uma tem; não há como saber que um filtro está ativo.
**Proposta:**
- Ordem: **busca por título** (cresce, ocupa a linha inteira no celular), depois Loja, Busca, Ordenar. Rótulos visíveis curtos (`.lbl`): "Loja", "Busca", "Ordenar". Opção padrão da ordem: "Ordem de coleta".
- Contagem nas opções: "Amazon (2.511)", "Dior Sauvage (46)" (respeitando os demais filtros, como no gênero). Buscas em ordem alfabética.
- **Filtro ativo** (valor ≠ padrão): borda 2 px em Tinta (o valor escolhido já está escrito no select, então a cor não é o único sinal) e o botão **"Limpar filtros"** (ghost, só aparece quando há filtro) ao fim da linha. Sem cor nova.
- A busca por título passa a ignorar acentos e maiúsculas (já existe `semAcento` no disparo) e espera 200 ms depois de digitar (`dev`: hoje cada tecla refaz abas e cartões).

## M5 (P1, acessibilidade) [AGORA] Não destruir o foco ao navegar
**Problema (confirmado no código):** `render()` recria todos os botões das abas e da paginação a cada clique. Quem navega por teclado ativa uma aba e o foco vai para o `body`: precisa tabular desde o topo. O mesmo na paginação (WCAG 2.4.3, 3.2.x).
**Proposta (`dev`):** atualizar `class` e `aria-pressed` das abas e o texto da paginação **no lugar**, sem recriar os botões; se recriar, devolver o foco ao botão equivalente (aba ativa ou "Próxima"). Vale também para o controle de público (Parte A).

## M6 (P2) [AGORA] Abas no celular e cartão mais compacto
- **Abas a 320 px:** hoje quebram em 4 linhas de largura variável (~180 px). Passam a uma **grade de 2 colunas** (texto pode quebrar em 2 linhas, contagem à direita, 44 px de altura mínima). A partir de 601 px, como hoje.
- **Altura do cartão:** a caixa de mensagem tem `min-height:200px` e é o maior bloco do cartão (~45% da altura), embora o dono raramente edite. Reduzir para `min-height:132px` (≈ 6 linhas, continua redimensionável e rolável). Efeito: ~70 px a menos por cartão, mais ofertas por tela, sem esconder nada. O "Copiar" fica a menos rolagem.
- **"Copiar imagem" sem foto:** hoje fica um botão esmaecido sem motivo visível (o motivo está só para leitor de tela). Sugestão: manter o botão (alinhamento da grade) e acrescentar `title` com o texto de `TXT_IMG.semFoto`.

## M7 (P2) [AGORA, aprovado pelo dono] Tela do disparo: menos navegação duplicada
**Problema:** na tela do disparo há três navegações: cabeçalho (Template, Editar templates e o próprio botão "Disparo automático", que leva à tela em que já se está), "← Voltar às ofertas" e as abas Regras/Histórico/Números. Em 320 px o cabeçalho ocupa ~190 px antes do título.
**Proposta:**
- Em `body.em-disparo`, o cabeçalho mostra só o logo e **"← Voltar às ofertas"** (o link do corpo sai, ou fica só ele no celular). Esconder também Template, Editar templates e o botão "Disparo automático". O formulário da regra já tem seu próprio Template e o link "Editar templates" (aprovado: isto reverte o que o `CLAUDE.md` registra, que Template e "Editar templates" ficam no cabeçalho; o `dev` atualiza o `CLAUDE.md`).
- Fila e regras: o título "Para enviar" ganha a contagem ("Para enviar · 3") e, quando vazio, a frase "Nada na fila." continua. Nenhuma mudança no formulário além do campo de público.
- O foco programático no `h2` ao entrar na tela mostra um retângulo grande; manter só para teclado (`:focus-visible`), como está, e não aplicar com mouse (conferir no teste manual).

## M8 (P3) [ENTREGA 2] Sugestões
- **S1** Lembrar a aba, o público e a página em `sessionStorage` (hoje só a aba é lembrada): ao voltar de "Abrir na loja" ou do disparo, o dono retoma onde estava.
- **S2** Marcas "✓ Mensagem copiada" sobrevivem à troca de página e de filtro na mesma sessão (guardar os ids copiados em memória). Hoje voltar à página 1 apaga todas as marcas e o dono não sabe o que já enviou. (`dev`, estado em memória; não persiste no banco.)
- **S3** `title` no selo da busca truncada (já existe) e no nome do cartão: manter.

## Componentes (Parte B)
| Componente | Existente ou novo | Onde fica |
|---|---|---|
| Cabeçalho compacto, `.barra-lista` | Novo (CSS e marcação) | `index.html` |
| Paginação com salto | Existente `.pager`, simplificada | `index.html` |
| `.vazio` para carregando/erro/sem resultado | Existente (disparo) | `index.html` |
| Grade de abas 2 colunas (≤ 600 px) | Variante de `.tabs` | `index.html` |
| "Limpar filtros" | Botão `ghost` existente | `index.html` |

## Estados (Parte B)
Resumo: carregando, erro com "Tentar de novo", vazio por filtro com "Limpar filtros", categoria sem itens, uma só página (sem paginação), filtro ativo (rótulo e botão), foco preservado, conteúdo longo (título de 2 linhas, busca truncada com `title`, "Mercado Livre" em 320 px), reduced-motion (sem animação nova).

## Textos da interface (Parte B)
| Onde | Texto |
|---|---|
| Resumo | Mostrando 1 a 24 de 3.110 ofertas |
| Cópia da página | Copiar as 24 da página (toast: "24 mensagens copiadas!") |
| Paginação | ‹ Anterior · Página [n] de 130 · Próxima › · rótulo do campo: Ir para a página |
| Carregando | Carregando as ofertas… |
| Erro | Não consegui carregar as ofertas. Verifique se o servidor está aberto e tente de novo. / Tentar de novo |
| Sem resultado | Nenhuma oferta com esses filtros. / Limpar filtros |
| Categoria sem itens | Esta categoria ainda não tem ofertas. Use Adicionar links para incluir. |
| Rótulos dos filtros | Loja · Busca · Ordenar |
| Disparo | ← Voltar às ofertas · Para enviar · 3 |

## Acessibilidade (Parte B, resumo)
- Foco preservado em abas e paginação (M5); resumo e anúncios em uma única região `aria-live="polite"` (evita leitura dupla).
- Campo "Ir para a página": `label` visível ou `aria-label`, `min`/`max`, Enter confirma, erro some com valor fora do intervalo (volta ao limite).
- Alvos 24 px mínimo (44 px no celular); paginação sobe de 32 para 36 px (44 em `pointer:coarse`).
- Cabeçalho não sticky no celular remove a perda de área útil (WCAG 1.4.10 reflow a 320 px).
- Cor nunca sozinha: filtro ativo mostra valor, não só borda.

## Critérios de aceite visuais (Parte B)
- **CA-V13** [AGORA] (M1) Em 320 px o cabeçalho não é sticky e tem no máximo 3 linhas antes das abas; em 1280 px é uma linha de ≤ 64 px, sticky.
- **CA-V14** [AGORA] (M1) Template, "Editar templates" e "Copiar todas da página" ficam na barra de lista simples acima do grid e continuam funcionando; o contador de totais aparece abaixo das abas com a mesma regra de loja zerada omitida.
- **CA-V15** [ENTREGA 2] (M2) A barra mostra "Mostrando X a Y de N ofertas" e "Copiar as K da página", com K igual ao número de cartões na tela.
- **CA-V16** [ENTREGA 2] (M2) É possível ir direto à página 57 digitando o número; trocar de página leva a vista ao início da lista e o foco ao resumo.
- **CA-V17** [AGORA] (M3) Há texto de carregando antes dos dados, bloco de erro com "Tentar de novo" se a API falhar, e bloco de "Nenhuma oferta..." com "Limpar filtros" quando o filtro zera a lista.
- **CA-V18** [ENTREGA 2] (M4) A busca por título é o primeiro campo de filtro; Loja, Busca e Ordenar têm rótulo visível e contagem nas opções; "Limpar filtros" só aparece com filtro ativo e restaura o padrão.
- **CA-V19** [AGORA] (M5) Só por teclado: ativar uma aba ou "Próxima" mantém o foco no elemento ativado (ou no equivalente), sem voltar ao início do documento.
- **CA-V20** [AGORA] (M6) Em 320 px as abas formam 2 colunas, sem rolagem horizontal; a caixa de mensagem tem 132 px de altura mínima e continua redimensionável.
- **CA-V21** [AGORA] (M7) Em `#disparo`, o cabeçalho mostra só logo e "← Voltar às ofertas"; nenhuma ação some da tela da regra (o Template continua no formulário).
- **CA-V22** [AGORA] (todos os itens desta entrega) Sem rolagem horizontal de 320 a 1280 px, contraste ≥ 4,5:1 (texto) e ≥ 3:1 (bordas de campos e foco) em claro e escuro, `prefers-reduced-motion` respeitado.

## O que o dev precisa implementar
**Parte A [AGORA]:**
0. Campo "Público" em "Mais ações" (A2): `PUT /api/items/<id>/genero`, estados, selo "corrigido".
1. Ler `item.genero` e `item.genero_origem`; calcular "aba tem gênero"; estado do público por aba em `localStorage`.
2. `filtrada()` passa a filtrar por público; contagens por opção; select de buscas restrito ao público.
3. Controle segmentado (marcação + `.seg-filtro` + atualização no lugar, sem recriar).
4. Selo no `renderCard` só em "Todos".
5. Campo "Público" na regra (`htmlFormRegra`, `lerFormRegra`, resumo `resumoAgenda`/cartão), com a chave do plano na API; contador do formulário (`contarItens`) respeitando o público.
6. Ajustar `testes/*.test.html` que contam botões ou usam o resumo da regra.

**Parte B [AGORA]:** M1 reorganizar cabeçalho e mover `#tplSelect`, `#btnTpl`, `#btnCopyAll`, `#count`; M3 estados; M5 atualizar no lugar; M6 CSS de abas e `min-height`; M7 CSS e marcação de `body.em-disparo`. **[ENTREGA 2]:** M2, M4, M8 (não implementar agora). Os seletores `#tplSelect`, `#btnTpl`, `#count`, `#btnCopyAll`, `#tabs`, `.pager` são usados em testes e no JS: manter os ids ou ajustar os testes junto.

## Arquivos de apresentação afetados
`index.html` (CSS, marcação, `TXT_DISPARO` e novas constantes de texto) e `testes/*.test.html` que dependam dos elementos movidos. Nenhum arquivo de regra de negócio. Mudança em tokens: nenhuma.

## Perguntas em aberto
Resolvidas pelo dono: gênero só em Perfumes; correção à mão agora; regra com escolha única; M7 aprovado; renome do botão fica para a entrega 2.
1. Para mostrar "Automático (Feminino)" no cartão corrigido, o servidor precisa devolver o valor automático junto do manual; se o plano não prevê isso, o campo mostra só "Automático" (já tratado em A2). O `dev` confirma.
