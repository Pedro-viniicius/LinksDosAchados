# Especificação de UI/UX: 17 abas nichadas e "Público" em três abas

Plano em paralelo (arquiteto): `docs/produto/planos/abas-nichadas-e-coleta.md`. Specs de base: `ux-ui-identidade.md` e `genero-e-ux.md` (esta não repete o que lá já vale: cartão, "Mais ações", controle segmentado, foco, M1 a M7).

## Objetivo e usuário
O dono, sozinho, no computador (às vezes no celular), vai manter um grupo de WhatsApp por nicho, e cada nicho é uma aba. Ele precisa chegar à aba do grupo em um ou dois toques, saber quanto há em cada uma e não se perder entre 17 nomes longos. Volume: ~10.400 itens, de dezenas a ~3.000 por aba.

## Decisões do dono (fora de discussão)
- Abas, nesta ordem: 1 Celulares e Informática · 2 Áudio e Acessórios · 3 TV, Alexa e Casa Conectada · 4 Games · 5 Eletroportáteis · 6 Eletrodomésticos e Climatização · 7 Cozinha · 8 Cama, Mesa e Banho · 9 Casa, Móveis e Ferramentas · 10 Beleza e Cuidados · 11 Perfumes e Perfumaria · 12 Mercado e Limpeza · 13 Pets · 14 Bebês e Brinquedos · 15 Suplementos e Fitness · 16 Moda e Viagem · 17 Natal e Papelaria.
- "Público" vale em "Perfumes e Perfumaria", "Beleza e Cuidados" e "Moda e Viagem".

## Decisão 1: como mostrar 17 abas
**Escolha: abas agrupadas em 4 faixas no desktop e seletor nativo (`select` com `optgroup`) no celular.**

Opções avaliadas (17 nomes de 10 a 31 caracteres, mais contagem):
| Opção | Resultado | Veredito |
|---|---|---|
| Quebra livre como hoje (pílulas) | 5 a 6 linhas desalinhadas no desktop; 9 linhas na grade de 2 colunas a 360 px (~400 px de rolagem antes da primeira oferta) | Rejeitada: é o paredão |
| Rolagem horizontal | Esconde 10 das 17; em 360 px o dono não sabe que existem; aba ativa pode ficar fora da vista; rolagem horizontal pesa em WCAG 1.4.10 | Rejeitada |
| Só seletor, também no desktop | Compacto, mas esconde a visão geral e as contagens que o dono usa para decidir o que coletar | Rejeitada no desktop |
| **Faixas agrupadas (desktop) + select (celular)** | Visão geral completa em ~4 linhas; grupos dão sentido (Miller: 4 blocos de 4 a 5 em vez de 17 itens soltos); celular ocupa 1 linha de 44 px | Escolhida |

### Grupos (constante fixa no front, só apresentação)
Os grupos cortam a ordem do dono em faixas contíguas, sem trocar a ordem:
| Grupo (rótulo) | Abas |
|---|---|
| Tecnologia | 1 a 4 |
| Casa | 5 a 9 |
| Beleza e consumo | 10 a 13 |
| Família e estilo | 14 a 17 |

Os rótulos são sugestão minha; o dono pode trocar sem afetar o resto (ver Perguntas).

### Ordem
Constante fixa no front, `ORDEM_ABAS` (lista na ordem do dono, com o grupo de cada aba), e não a ordem do banco. Motivos: a ordem do banco muda a cada coleta (hoje é a de aparição do primeiro item); o dono memoriza a posição de cada nicho; por volume a lista mudaria de lugar a cada coleta e quebraria a memória muscular.
- **Todas as 17 aparecem sempre, mesmo com 0 itens** (contagem "0"). Assim a estrutura é estável antes da coleta e o dono vê o que falta coletar. Hoje `cats()` deriva dos itens: o `dev` troca por "as 17 da constante, mais qualquer outra categoria que exista no banco ao final, em um grupo "Outras" (ordem alfabética), que só aparece se houver)". Isso cobre legado ("Lista WhatsApp", abas antigas ainda não migradas) sem sumir com item.
- **Aba padrão** quando `activeCat` salvo não existe mais (as 3 abas que somem): a primeira, "Celulares e Informática".
- A mesma lista ordenada alimenta "Mover para" (cartão) e a escolha de categorias da regra do disparo (ver abaixo), para os três lugares nunca divergirem.
- Nomes de aba vêm de `ORDEM_ABAS` e têm de bater com as chaves de `buscas.json` (o `dev` confere com um teste; não é decisão visual).

## Layout

### Desktop (a partir de 601 px)
- Bloco `#tabs` (mantém o id): quatro **faixas**, uma por grupo. Cada faixa: rótulo do grupo à esquerda em coluna fixa de 144 px (`.lbl`: Legenda, caixa-alta, Mudo) e, à direita, as pílulas existentes (`.tab`) em `flex-wrap`, `gap: var(--s2)`.
- Faixas separadas por `var(--s2)`; sem linha divisória (o rótulo basta). Altura total esperada em 1280 px: 4 a 5 linhas (≤ 230 px). Abaixo de ~900 px o rótulo passa para cima das pílulas (coluna única) para dar largura às pílulas.
- Pílula: igual à atual (alvo `--alvo`, 36 px; 44 px com `pointer:coarse`), com `white-space: nowrap`; só quebra se o nome sozinho passar da largura da faixa (aí `overflow-wrap:anywhere`). Texto: nome + contagem Mono (`.muted`).
- Sem token novo. Etiqueta continua só na aba ativa.

### Celular (até 600 px, testar 320, 360 e 375)
- A grade de 2 colunas de M6 sai para `#tabs`. No lugar, aparece **`<select id="selCat">`** com rótulo visível "Categoria" (`.lbl`), largura total, 44 px de altura, `optgroup` por grupo, `option` com `Nome (contagem)`. Ex.: `Perfumes e Perfumaria (3.051)`.
- O `#tabs` com os botões fica `display:none` no celular e o `select` fica `display:none` no desktop (um só visível por vez; o oculto sai da árvore de acessibilidade). Os dois são gerados no mesmo `render()` a partir de `ORDEM_ABAS`, e `change` do select executa o mesmo código do clique da aba (zera busca e página).
- Nomes longos no select: o `option` pode ser cortado pelo SO, mas o valor escolhido aparece inteiro, em até 2 linhas (`white-space:normal` no select não é confiável; garantir `text-overflow:ellipsis` e `title` com o nome completo). Em 320 px o maior ("Eletrodomésticos e Climatização (1.234)") tem ~40 caracteres: cabe com `font-size` 16 px do select em ~290 px? Não cabe sempre; aceito ellipsis, pois o select aberto mostra a lista inteira em tela cheia do SO.
- Select nativo e não menu próprio: acessível e usável no teclado/leitor de tela, abre o seletor do SO (roda grande, fácil de tocar) e não precisa de JS de posição.
- Ordem das barras na tela: cabeçalho, seletor "Categoria", linha do contador de totais, controle "Público" (se houver), filtros, barra de lista, grid.

## Componentes
| Componente | Existente ou novo | Onde fica |
|---|---|---|
| Faixa de grupo (`.tabs-grupo` com rótulo `.lbl`) | Novo, variante de `.tabs` | `index.html` (CSS e `render()`) |
| Pílula de aba (`.tab`) | Existente, sem mudança visual | `index.html` |
| Seletor de categoria `#selCat` (celular) | Novo, usa o estilo de `select` existente | `index.html` |
| Controle "Público" | Existente (`.seg-filtro`) | `index.html` |
| Dica de público (`.dica-publico`, Legenda Mudo) | Novo, uma linha de texto | `index.html` |
| Tokens | Nenhum novo | `:root` |

## Estados

**Aba (desktop)**
- Padrão, hover (borda `--mudo`), ativa (Etiqueta clara, borda `--etiqueta-escura`, peso 600) e foco (anel `--foco` 2 px) como hoje.
- **Com 0 itens:** pílula normal, contagem "0" em Mudo; não desabilitar (o dono entra para ver a frase de categoria vazia e o caminho de "Adicionar links"). Sem ícone nem cor.
- **Conteúdo longo:** "Eletrodomésticos e Climatização" (31 caracteres) cabe em uma pílula de ~290 px; se a faixa for mais estreita, quebra em 2 linhas dentro da pílula, nunca estoura a faixa.
- **Contagem com 5 dígitos** ("10.400" não ocorre por aba, mas "3.051" sim): Mono tabular.
- **Aba ativa sempre visível:** com quebra em linhas (sem rolagem), a aba ativa nunca fica fora da vista. Ao entrar na página com aba salva, nada a rolar.
- **Carregando e erro:** as faixas e o select só aparecem depois dos itens (como hoje, M3), para a contagem não pular de 0.

**Seletor (celular)**
- Padrão (mostra aba ativa e sua contagem), foco (anel `--foco`), aberto (UI do SO), 0 itens (opção normal "(0)"), desabilitado: não existe.

**Troca de aba (todos)**
- Zera a busca por título e a página, restaura o público lembrado para aquela aba, anuncia na região `aria-live` existente: "Celulares e Informática: 812 ofertas". Foco permanece no botão ou no select (M5: atualizar no lugar, sem recriar; se recriar, devolver o foco ao botão da mesma `data-c`).
- Aba com 0: bloco `.vazio` de M3 ("Esta categoria ainda não tem ofertas. Use Adicionar links para incluir.").
- Aba grande (~3.000 itens, 125 páginas de 24): ver Perguntas (salto de página).

## Decisão 2: "Público" em Beleza e Moda

### Quando aparece
Igual à Parte A de `genero-e-ux.md`: só nas abas de `ABAS_COM_GENERO` (agora as três), cada opção com contagem, escolha lembrada por aba (`genero:<aba>`), selo no cartão só em "Todos".

### Textos por aba
Os rótulos de opção ficam iguais nas três abas (consistência; o dono usa o mesmo controle em todas). O que muda é a ajuda e a dica de "Sem gênero":
- **Moda e Viagem:** Feminino, Masculino e Unissex funcionam como estão. "Viagem" (malas, mochilas, travesseiros) tende a cair em "Sem gênero" ou "Unissex": a dica abaixo cobre isso.
- **Beleza e Cuidados:** a maioria do catálogo (shampoo, creme, escova) não tem público. Isso é esperado e não é erro.

### "Sem gênero" quando é a maioria
- A opção "Sem gênero" continua no fim, com contagem (regra da Parte A: só existe se houver ao menos um item).
- Quando "Sem gênero" for **50% ou mais** dos itens da aba (com os mesmos filtros de loja e título), aparece uma linha de dica sob o controle, Legenda Mudo: `A maior parte desta categoria não separa por público (1.812 de 2.900). Veja em "Sem gênero".`
- Abaixo de 50%, sem dica (sinal-ruído). A dica é texto, não alerta: sem cor, sem ícone, sem `role`. Fica ligada ao controle por `aria-describedby` no `fieldset`.
- A ordem das opções não muda ("Sem gênero" não vira a opção padrão: o padrão continua "Todos", para o dono não esconder itens sem querer).

### Disparo (regra)
- A ajuda do campo "Público" muda de "...como Perfumes e Perfumaria" para: `Vale só para categorias que separam por público: Perfumes e Perfumaria, Beleza e Cuidados e Moda e Viagem. Nas outras, a regra envia tudo.` (o `dev` monta a lista de nomes a partir de `ABAS_COM_GENERO`, para não ficar desatualizada).
- **Escolha de categorias da regra** (`htmlFormRegra`, campo hoje com 4 chips): com 17 categorias passa a usar os mesmos 4 grupos, cada um num `fieldset` com `legend` (grupo) e os chips de checkbox em `flex-wrap`; no celular, chips em coluna única de 44 px. Em cada grupo, botão ghost "Marcar o grupo" / "Desmarcar o grupo" (texto alterna; é opcional marcar uma por uma). Mantém "Marcar todas" se já existir. Resumo no cartão da regra: até 2 nomes e "+N" ("Cozinha, Pets +3"), com `title` com a lista inteira, para não crescer a 17 nomes.

## Textos da interface
| Onde | Texto |
|---|---|
| Rótulo do seletor (celular) | Categoria |
| Opção do seletor | `Perfumes e Perfumaria (3.051)` |
| Rótulos dos grupos | Tecnologia · Casa · Beleza e consumo · Família e estilo · Outras |
| Anúncio ao trocar de aba (`aria-live`) | `Pets: 214 ofertas` (singular: `1 oferta`; zero: `Pets: nenhuma oferta`) |
| Aba vazia | Esta categoria ainda não tem ofertas. Use Adicionar links para incluir. (já existe em M3) |
| Dica de "Sem gênero" majoritário | A maior parte desta categoria não separa por público (1.812 de 2.900). Veja em "Sem gênero". |
| Ajuda do público na regra | Vale só para categorias que separam por público: Perfumes e Perfumaria, Beleza e Cuidados e Moda e Viagem. Nas outras, a regra envia tudo. |
| Marcar grupo (regra) | Marcar o grupo · Desmarcar o grupo |
| Resumo da regra | Cozinha, Pets +3 |

Os textos devem entrar numa constante (`TXT_ABAS`), junto das demais `TXT_*`.

## Acessibilidade (WCAG 2.2 AA)
- **Padrão de abas:** as abas hoje são botões com `aria-pressed` num `role="group"` e não filtram um painel separado; o padrão `tablist` exige painéis ligados por `aria-controls` e muda a lista a cada seta (o que refaria 3.000 cartões). Mantém-se o padrão de botões alternados: semântica nativa, sem ARIA novo (princípio "nativo antes de ARIA"). Cada faixa é um `role="group"` com `aria-labelledby` apontando ao rótulo visível do grupo; `#tabs` mantém `aria-label="Categorias"`.
- **Teclado:** Tab percorre as 17 pílulas na ordem visual (a do DOM é a da constante); Enter e Espaço ativam. 17 paradas é aceitável porque o dono tem a alternativa do select e porque são botões comuns; roving tabindex com setas fica fora desta entrega (ver Perguntas). Foco visível (anel 2 px, ≥ 3:1) e preservado ao trocar de aba (M5).
- **Alvo:** 36 px no desktop (≥ 24 px, SC 2.5.8), 44 px com `pointer:coarse` e no select.
- **Aba ativa:** não depende de cor (peso 600, `aria-pressed="true"`, borda de 1 px da variante escura); no select, o valor escolhido é texto.
- **Contraste:** inalterado (pílula Tinta sobre Superfície; ativa Tinta sobre Etiqueta clara; Mudo do rótulo de grupo ≥ 4,5:1 sobre Papel; dica Mudo idem).
- **Sem rolagem horizontal** de 320 a 1280 px (SC 1.4.10); linhas de texto curtas.
- **Select:** `label` visível "Categoria" associado por `for`; opções com nome e contagem lidas pelo leitor.
- **Anúncio:** a troca de aba usa a região `aria-live="polite"` única (a mesma de M2/Parte A) para evitar leitura dupla.
- **Movimento:** nenhuma animação nova; `prefers-reduced-motion` já desliga as transições existentes.
- **Modo escuro:** só tokens; nada novo.

## Critérios de aceite visuais
- **CA-D1** Há 17 abas na ordem do dono, nenhuma com nome cortado ou fora do bloco; as abas "Black Friday | Eletrônicos", "Eletrodomésticos" e "Casa e Decoração" não aparecem (a menos que ainda existam itens nelas: aí vão em "Outras", ao final).
- **CA-D2** Em 1280 px as abas formam 4 faixas rotuladas (Tecnologia, Casa, Beleza e consumo, Família e estilo), ocupam no máximo 230 px de altura e não há rolagem horizontal.
- **CA-D3** Em 320, 360 e 375 px, `#tabs` está oculto e aparece o select "Categoria" (44 px, rótulo visível, `optgroup` por grupo, contagem em cada opção); em 601 px ou mais acontece o contrário. Nunca há os dois visíveis, nem rolagem horizontal.
- **CA-D4** Escolher uma aba pelo select ou pelo botão faz a mesma coisa: aba ativa trocada, busca e página zeradas, anúncio no `aria-live`, e os dois controles ficam em sincronia (o select mostra a aba ativa ao voltar ao desktop e vice-versa).
- **CA-D5** Aba sem itens aparece com contagem "0", pode ser aberta e mostra a frase de categoria vazia; não está desabilitada.
- **CA-D6** Se o `activeCat` salvo não existe mais (as 3 abas removidas), a página abre em "Celulares e Informática".
- **CA-D7** Só por teclado: Tab chega às pílulas na ordem visual, Enter ativa, o foco permanece na pílula ativada e é visível; no select, setas trocam a categoria.
- **CA-D8** Categoria do banco que não está nas 17 aparece em "Outras" ao final, com o item ainda acessível; sem item órfão, o grupo "Outras" não existe.
- **CA-D9** "Mover para" do cartão e a escolha de categorias da regra listam as mesmas 17 (mais "Outras" se houver) e na mesma ordem das abas.
- **CA-D10** "Público" aparece em Perfumes e Perfumaria, Beleza e Cuidados e Moda e Viagem e em mais nenhuma; os cartões das outras 14 abas não mostram o campo "Público" em "Mais ações".
- **CA-D11** Em Beleza e Cuidados, se "Sem gênero" for 50% ou mais dos itens, aparece a dica com os números certos; abaixo disso, não aparece. A escolha padrão continua "Todos".
- **CA-D12** Na regra do disparo, a ajuda do público cita as três categorias e as categorias da regra aparecem em 4 grupos com "Marcar o grupo"; o resumo no cartão mostra até 2 nomes e "+N", com `title` completo.
- **CA-D13** Contraste ≥ 4,5:1 nos textos novos e ≥ 3:1 nas bordas e no foco, em claro e escuro; a Etiqueta continua só na aba ativa, no desconto, no "Copiar" e no foco.
- **CA-D14** Com 10.400 itens, trocar de aba e de público leva menos de 200 ms percebidos (sem recriar as 17 pílulas nem recalcular contagem por aba mais de uma vez por `render()`).

### Sobre `testes/abas.test.html`
Serve para CA-D1, D5, D6, D8 e D9 (contam `#tabs .tab`, ordem e itens falsos). Ajustes que o `dev` precisa fazer: o teste lê `.tab` dentro de `#tabs` (ids mantidos, então os seletores seguem valendo), mas qualquer asserção de "número de abas igual ao de categorias com itens" muda para 17 mais "Outras". CA-D3 (largura de 360 px) e CA-D2 (altura) exigem janela redimensionada e ficam como verificação visual por captura, não no teste automático, salvo se o runner já fixa a largura da janela.

## O que o dev precisa implementar
1. `ORDEM_ABAS` (17 nomes + grupo de cada), numa linha só se for lida por regex em teste (o `test_front_constantes.py` hoje lê só as constantes listadas no `CLAUDE.md`; se o arquiteto quiser amarrar `ORDEM_ABAS` a `buscas.json`, o teste novo é dele).
2. `cats()` devolve as 17 mais "Outras" ordenadas por `ORDEM_ABAS`; contagens por aba em uma só passada; o `render()` gera as faixas e o select a partir da mesma lista.
3. Marcação e CSS: faixas agrupadas (≥ 601 px), `#selCat` (≤ 600 px), remoção da grade de 2 colunas de M6 para `#tabs`. Eu (designer) posso fazer essa parte quando o `dev` liberar o arquivo.
4. Tratar `activeCat` removido (cai na primeira) e o `change` do select, com foco e anúncio.
5. `ABAS_COM_GENERO` com as 3 abas no `index.html` **e** em `genero.py` (regra de negócio, só `dev`; `test_front_constantes.py` confere). Calcular a proporção de "Sem gênero" para a dica.
6. `htmlFormRegra`: categorias em grupos, "Marcar o grupo", resumo curto; ajuda do público a partir de `ABAS_COM_GENERO`. "Mover para" com a lista ordenada.
7. `TXT_ABAS` com os textos desta spec.
8. Atualizar `testes/abas.test.html` e outros testes que contem abas; atualizar o `CLAUDE.md` (lista das abas, `ABAS_COM_GENERO`, aviso de que `cats()` agora tem ordem fixa).

## Arquivos de apresentação afetados
`index.html` (CSS, marcação, `render()`, `htmlFormRegra`, `TXT_ABAS`) e `testes/abas.test.html`. Nenhum token novo. Mudança em componente compartilhado: `.tabs`/`.tab` são usados só na barra de categorias e no `@media (max-width:600px)` (linhas ~77 a 82 e ~168 a 169); "Mover para" e a regra do disparo usam `cats()`.

## Perguntas em aberto
1. **Rótulos dos 4 grupos** (Tecnologia, Casa, Beleza e consumo, Família e estilo): o dono confirma ou troca? Não muda nenhuma aba.
2. **Salto de página (M2 da spec anterior, hoje "entrega 2"):** com abas de ~3.000 itens (125 páginas de 24), só "Primeira/Anterior/Próxima/Última" é lento. Recomendo trazer o campo "Ir para a página" de M2 junto desta entrega. Decisão do lead.
3. **Setas entre abas (roving tabindex):** com 17 paradas de Tab, vale? Recomendo deixar para depois, porque o select e a quebra por grupos já resolvem o uso real (dono usa mouse no desktop).
4. **"Sem gênero" → "Sem público":** em Beleza o rótulo "Sem gênero" soa estranho para shampoo. Recomendo renomear em todo o app (controle, cartão, select de correção), mas muda texto e testes existentes; só com aprovação.
5. Abas antigas que ainda tenham itens depois da migração caem em "Outras" (CA-D8). O plano do arquiteto garante a migração antes da troca de interface?
