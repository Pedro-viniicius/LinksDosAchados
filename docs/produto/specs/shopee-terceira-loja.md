# Especificação de UI/UX: Shopee como terceira loja

## Objetivo e usuário
O dono, sozinho, no computador, passa a coletar perfumaria também na Shopee. A interface acomoda a terceira loja **sem peso visual novo**: nenhuma cor, ícone, logo ou fonte de marca; a loja continua sendo um rótulo neutro, como a spec `ux-ui-identidade.md` já decidiu ("loja vira rótulo neutro, sem laranja Amazon / amarelo ML"). Isso vale em especial para a Shopee, cujo laranja de marca colidiria com `--etiqueta`. Só apresentação: o formato do link, a coleta e as ordenações estão no plano do arquiteto (`docs/produto/planos/perfumaria-tres-lojas.md`).

Chave interna da loja: `shopee` (a confirmar no plano). Nome exibido: **Shopee**.

## Princípios aplicados
- **Hick:** não entra controle novo na página principal; só uma opção a mais no filtro que já existe.
- **Sinal-ruído:** loja sem item não ocupa espaço no contador.
- **Consistência:** a Shopee usa exatamente o mesmo rótulo (`.badge`), o mesmo select e o mesmo mecanismo de chips que as outras lojas.

## Fluxo
Sem fluxo novo. Colar links da Shopee em "Adicionar links" → cartões na aba da categoria → Copiar. Regra de disparo ganha a Shopee entre as lojas selecionáveis.

## Layout (mobile e desktop)
Nada muda de posição. Pontos tocados:

### 1. Selo da loja no cartão (`.badge`, `index.html` ~linha 468)
- Texto "Shopee" no mesmo `.badge` (Rótulo, caixa-alta, Mudo, sem fundo). Não criar `.badge.shopee` com cor. Não haverá regra CSS por loja.
- Em 320 px cabe ao lado da busca (`.busca`, que já trunca); `.badge` mantém `white-space:nowrap`. O nome mais longo continua sendo "Mercado Livre".

### 2. "Abrir na loja"
- Rótulo visível **não muda** ("Abrir na loja"). Nome acessível: `aria-label="Abrir na loja Shopee"` (idem "Amazon" e "Mercado Livre"). O texto visível está contido no nome acessível (WCAG 2.5.3).
- "Atualizar preço" segue só para Amazon, a menos que o plano preveja atualização na Shopee; sem previsão, o botão não aparece (nada de botão desabilitado).

### 3. Filtro por loja (`#fLoja`) e contador (`#count`)
- `#fLoja`: "Todas as lojas · Amazon · Mercado Livre · Shopee" (mesma ordem em todo o app). Continua `<select>` com `aria-label="Filtrar por loja"`. Sem chips nem abas por loja.
- Contador do cabeçalho, mesma Legenda Mudo: `N itens no total · A Amazon · M Mercado Livre · S Shopee`. **Loja com zero item é omitida** do contador (hoje o dono, antes de coletar na Shopee, não vê "0 Shopee"). Em 320 px o texto quebra em até 2 linhas, sem rolagem horizontal; separador "·" fica no fim da primeira linha, nunca sozinho no começo (usar espaço comum, deixar o navegador quebrar).
- O contador por aba (número em Mono) não muda: continua somando todas as lojas.

### 4. Adicionar links
- Placeholder do `#addLinks`: "Cole links de afiliado aqui, um por linha (Amazon, Mercado Livre ou Shopee)".
- Toast e mensagens existentes não mudam. Link de domínio não reconhecido: ver Pendências (hoje cai em "amazon" por padrão, o que rotularia errado).

### 5. Disparo automático
- **Campo de lojas da regra** (`#f-lojas`, `~linha 1158`): sai o rádio segmentado "Amazon · Mercado Livre · Ambas" e entra um **grupo de chips de caixa de seleção** (mesmo `.chip` e `htmlChip('checkbox', ...)` das categorias e dos dias), dentro do `fieldset` com legenda **"Lojas"**:
  `[✓ Amazon] [✓ Mercado Livre] [✓ Shopee]`
  - Motivo: com 3 lojas há 7 combinações; rádio exigiria "Amazon e ML", "ML e Shopee" etc. (Lei de Hick). Caixas dão todas as combinações com 3 controles.
  - Padrão de regra nova: **as três marcadas**. Regra existente abre com as lojas que já tinha (as antigas "Ambas" abrem com Amazon e Mercado Livre marcadas e Shopee desmarcada, para não mudar o que já envia).
  - Mínimo de 1: desmarcar a última não é impedido, mas na gravação mostra o erro inline "Escolha ao menos uma loja." (`aria-invalid`, `aria-describedby`, resumo no topo como os demais erros).
  - Ajuda (linha Mudo sob a legenda): "A regra só envia itens das lojas marcadas."
- **Resumo no cartão da regra** (`textoLojas`): 1 loja → o nome; 2 lojas → "Amazon e Mercado Livre", "Amazon e Shopee" ou "Mercado Livre e Shopee" (ordem fixa Amazon, Mercado Livre, Shopee); 3 lojas → "Todas as lojas". Sem "ML" abreviado.
- **Prévia** (`#dspPrevia`): acima do corpo, uma linha Legenda Mudo `Loja: Shopee` (texto, sem selo colorido). Hoje a prévia não mostra a loja; passa a mostrar porque agora a regra pode misturar três.
- **Fila "Para enviar"** (`criarCardFila`): na linha `.fsub`, antes do grupo: `Shopee · Grupo: Achadinhos`, mesma classe `.busca` (Mudo, trunca). O selo de estado ("Na fila"/"Incerto") continua à direita. Nome acessível dos botões não muda (já leva o título do item).
- **Histórico**: se a linha já mostra o item, acrescentar a loja na mesma célula do item, em Mudo, depois do título ("Título · Shopee"); sem coluna nova.

## Componentes
| Componente | Existente ou novo | Onde fica |
|---|---|---|
| `.badge` (selo de loja) | Existente; sem variante | `index.html` |
| `#fLoja` select | Existente, +1 `<option>` | `index.html` |
| `.chip` checkbox em `#f-lojas` | Existente (já usado em categorias/dias) | `index.html` |
| `.seg` rádio segmentado de loja | **Deixa de ser usado** para loja (continua em "Ordem de envio") | `index.html` |
| Tokens | Nenhum novo | `:root` |

## Estados
- **Padrão:** selo e opções como descrito.
- **Loja sem itens:** omitida do contador; continua no select de filtro (não esconder opção: some a previsibilidade). Filtrar por loja sem itens na aba: usa o vazio existente do grid.
- **Chip de loja:** padrão, hover, foco (`--foco`), marcado (borda Etiqueta + `--etiqueta-clara` + "✓" no texto), desabilitado não se aplica.
- **Erro:** "Escolha ao menos uma loja." inline e no resumo.
- **Conteúdo longo:** "Mercado Livre e Shopee" no cartão da regra cabe na Legenda; a linha já trunca/quebra (categorias + loja + ordem).
- **Carregando e sucesso:** sem mudança.

## Textos da interface (pt-BR)
| Onde | Texto exato |
|---|---|
| Nome da loja (`LOJA.shopee`, também em `{LOJA}` do template) | Shopee |
| Opção do filtro | Shopee |
| Contador | `S Shopee` (ex.: "1.240 itens no total · 600 Amazon · 400 Mercado Livre · 240 Shopee") |
| Placeholder de adicionar links | Cole links de afiliado aqui, um por linha (Amazon, Mercado Livre ou Shopee) |
| Legenda do campo da regra | Lojas |
| Ajuda do campo | A regra só envia itens das lojas marcadas. |
| Chips | Amazon · Mercado Livre · Shopee |
| Resumo, 3 lojas | Todas as lojas |
| Resumo, 2 lojas | Amazon e Shopee · Mercado Livre e Shopee · Amazon e Mercado Livre |
| Erro | Escolha ao menos uma loja. |
| Prévia | Loja: Shopee |
| Fila | Shopee · Grupo: <nome do grupo> |
| `aria-label` de "Abrir na loja" | Abrir na loja Shopee |
| Link inválido (toast, se o dev implementar) | Link não reconhecido: use um link de afiliado da Amazon, do Mercado Livre ou da Shopee. |

Remover do rádio: "Ambas" (substituído por chips e "Todas as lojas").

## Acessibilidade (WCAG 2.2 AA)
- **Contraste do selo:** o selo da Shopee é texto Mudo sobre Superfície, como os outros: ~5:1 (4,5:1 exigido); nenhuma cor nova, então nenhum contraste novo a validar. Não depende de cor para distinguir lojas: o nome está escrito.
- Grupo de lojas em `<fieldset><legend>Lojas</legend>`; chips são `input type="checkbox"` nativos (Espaço marca), foco visível no chip inteiro via `:focus-visible` do input irmão, alvo 36 px (44 px com `pointer:coarse`).
- Mudança de seleção não precisa de `aria-live`; o contador "N itens disponíveis" e a prévia já usam `aria-live="polite"` e se atualizam com a seleção (a prévia sem item da loja mostra o aviso existente).
- Erro de campo com `aria-invalid` e `aria-describedby`; foco vai ao resumo no envio inválido (padrão atual).
- "Abrir na loja": nome acessível contém o texto visível.
- **320 px:** chips quebram em linha (`flex-wrap`), cada um com largura do texto (≥ 44 px de altura); contador quebra em 2 linhas; selo, `.busca` truncando; nada estoura a largura.
- `prefers-reduced-motion`: sem animação nova.

## Critérios de aceite visuais
- **CA-V1** Cartão da Shopee mostra o selo "SHOPEE" no mesmo estilo (Mudo, Rótulo, caixa-alta) dos outros; nenhuma cor de loja no app.
- **CA-V2** "Abrir na loja" tem `aria-label="Abrir na loja Shopee"` no cartão da Shopee (e o equivalente nas outras).
- **CA-V3** `#fLoja` lista Todas as lojas, Amazon, Mercado Livre, Shopee, e filtra só a Shopee.
- **CA-V4** O contador mostra "S Shopee" quando S > 0 e omite a loja quando S = 0; em 320 px não gera rolagem horizontal.
- **CA-V5** Em "Nova regra", o campo "Lojas" é um grupo de 3 chips de caixa de seleção, todos marcados por padrão; teclado: Tab chega a cada chip e Espaço alterna.
- **CA-V6** Regra salva com 0 lojas é bloqueada com "Escolha ao menos uma loja." inline e no resumo, com foco no resumo.
- **CA-V7** Regra antiga (Amazon + ML) abre na edição com Amazon e Mercado Livre marcadas e Shopee desmarcada.
- **CA-V8** Cartão da regra mostra "Todas as lojas" com 3 lojas e "X e Y" (ordem fixa) com 2.
- **CA-V9** A prévia mostra "Loja: <nome>" e a fila mostra "<loja> · Grupo: <grupo>".
- **CA-V10** Em 320 px e 1280 px, nenhum selo, chip ou texto de loja é cortado sem `title`, e nada força rolagem horizontal.
- **CA-V11** Contraste do texto do selo ≥ 4,5:1 nos modos claro e escuro (token `--mudo`, sem valor novo).
- **CA-V12** Em "Mais ações" de cartão da Shopee não aparece "Atualizar preço" (salvo decisão contrária do plano).

## O que o dev precisa implementar
1. `LOJA = {amazon, ml, shopee:'Shopee'}` e usar `LOJA` também em `textoLojas`, no filtro e no contador (hoje o texto está repetido à mão nas linhas 300, 519 e 659).
2. Opção "Shopee" no `#fLoja`; contador por loja gerado do `LOJA`, omitindo zeros.
3. `aria-label` no "Abrir na loja".
4. `#f-lojas`: trocar rádio por chips de caixa de seleção; leitura do formulário monta `lojas` a partir das marcadas; validação e erro; abrir regra antiga sem marcar a Shopee; `lojasSel` e a linha 1131 (`lojas:['amazon','ml']` por padrão) passam a usar as 3.
5. `textoLojas` para 1, 2 e 3 lojas (ordem fixa).
6. Loja na prévia, na fila e (se existir a linha do item) no histórico.
7. Placeholder de adicionar links.
8. Detecção da loja ao colar link (linha 550): domínio da Shopee e seus encurtadores conforme o plano; link desconhecido não pode cair em "amazon" em silêncio.
9. Testes de front que contam lojas ou usam "Ambas" precisam ser ajustados (`testes/disparo.test.html`, se citar o rádio).

## Arquivos de apresentação afetados
`index.html` apenas (marcação, strings e CSS de `.chip` já existente; nenhum token novo). Possivelmente `testes/*.test.html` que usem o rádio "Ambas".

## Perguntas em aberto
- Chave interna da loja no banco e na API (`shopee`?) e domínios aceitos: definidos pelo plano.
- A Shopee terá "Atualizar preço"? Assumido que não.
- Regras antigas com "Ambas": migrar para `['amazon','ml']` (sem Shopee) é o proposto; confirmar com o dono que não quer que passem a incluir a Shopee.
- O histórico mostra o item hoje? Se não, o item 6 do histórico sai.
