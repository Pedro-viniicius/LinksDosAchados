# Especificação de UI/UX: Copiar imagem no card

## Objetivo e usuário
O dono, sozinho, no Chrome do Linux. A prévia de link do WhatsApp sai sem foto; ele quer colar a foto do produto primeiro (abre a tela de legenda) e depois colar a mensagem como legenda. A ação será usada em quase todo envio. Só apresentação: a lógica (fetch, canvas, Clipboard API) é do `dev`, conforme `docs/produto/planos/copiar-imagem.md`.

## Fluxo
1. Card: **Copiar imagem** (foto vai para a área de transferência). O aviso diz o próximo passo.
2. WhatsApp Web: colar (abre a legenda).
3. Voltar ao site: **Copiar** (mensagem). O aviso diz "cole como legenda".
4. WhatsApp Web: colar na legenda e enviar.

Sem tutorial: a instrução aparece no aviso (`toast`) no momento certo, em cada passo, e some sozinha. Nada fixo na tela.

## Decisão: onde fica a ação
**Botão secundário (contorno) na linha de ações, logo depois de "Copiar".** Visível, porque é usado em quase todo envio e esconder em "Mais ações" custaria um clique extra por envio.

| Opção | Decisão | Motivo |
|---|---|---|
| Botão na linha de ações | Escolhida | Descobrível, alvo de 36/44 px, rótulo explícito, padrão dos outros botões |
| Clique ou botão sobre a miniatura | Rejeitada | Alvo escondido e pequeno (miniatura ~72 px), `alt=""` decorativo, sem rótulo para leitor de tela, e sobreposição ao conteúdo (ruído) |
| Dentro de "Mais ações" | Rejeitada | Frequência alta demais para ficar escondida |

**Hierarquia (CA5):** "Copiar" continua o único botão Etiqueta e o primeiro da linha. "Copiar imagem" usa o estilo `.secondary` existente (contorno). "Abrir na loja" é usado menos; passa a `ghost` (sem borda, texto Tinta), como já existe no cabeçalho, para a linha ter 1 destaque + 1 contorno + 1 discreto. Nenhum token novo de cor.

Ordem visual: [Copiar] [Copiar imagem] [Abrir na loja] [Mais ações]. A ordem de uso é o inverso (imagem antes), mas "Copiar" fica à frente por ser a ação principal; o aviso do passo 1 cobre a ordem (ver Perguntas em aberto).

## Layout (mobile e desktop)
- Card ~340 px: a linha de ações usa `flex-wrap` e `gap: var(--s2)`. Em geral "Copiar" e "Copiar imagem" ficam na 1ª linha e "Abrir na loja" e "Mais ações" quebram para a 2ª. Sem rolagem horizontal em 320 px.
- Altura mínima `--alvo` (36 px); 44 px em `pointer:coarse`, como os demais botões.
- O rótulo não encolhe nem quebra em duas linhas (`white-space: nowrap`); quem quebra de linha é o botão inteiro.
- A largura do botão não pode mudar entre os estados (evita o card "pular"): reservar a largura do texto mais longo ("✓ Imagem copiada") com `min-width` em `ch`.

## Componentes
| Componente | Existente ou novo | Onde fica |
|---|---|---|
| Botão "Copiar imagem" (`.secondary.copyimg`) | Novo, reusa `.secondary` | `renderCard`, `.actions` |
| "Abrir na loja" em `ghost` | Existente, estilo muda | `.actions` (só CSS; a classe `.open` fica) |
| Aviso (`toast`) | Existente | duração proporcional ao texto (`Math.max(1300, len*50)` ms) e cancela o timer do aviso anterior, para as frases de instrução darem tempo de ler |
| `.status` do card | Existente | mostra o erro |
| Selo `.feito` | Existente, texto muda | `.top` do card |

## Estados do botão
| Estado | Aparência e texto |
|---|---|
| Padrão | Contorno, "Copiar imagem" |
| Hover | Igual ao `.secondary:hover` existente |
| Foco | Anel de 2 px em `--foco`, igual aos demais |
| Ativo | Igual ao `.secondary:active` existente |
| Carregando | "Copiando…", `aria-disabled="true"`, `aria-busy="true"`, cursor `progress`, sem novo clique. Sem spinner: o texto basta (sem ícone novo). Sem opacidade reduzida: o texto precisa continuar legível, e o hover não muda nada |
| Sucesso | "✓ Imagem copiada", texto em `--enviado` (5:1 no claro; o ✓ garante que a cor não é o único sinal). Fica até o card ser redesenhado, como o `.done`. Continua clicável para copiar de novo. Aviso: ver Textos |
| Erro | Volta ao texto padrão; o motivo aparece em `.status.err` do card (`role="status"`, texto Falhou + ícone ou prefixo "Erro:" para não depender de cor) |
| Sem imagem (CA3) | Botão presente, com `aria-disabled="true"` (não `disabled`, para continuar focável e anunciável), opacidade .45 e cursor `not-allowed`, igual ao desabilitado existente. Ao clicar, `.status` explica o motivo. `aria-describedby` aponta para o texto "Este produto não tem foto". |
| Conteúdo inesperado | Rótulo curto e fixo; nada vindo do produto entra no botão |

**Por que presente e desabilitado, e não oculto:** a linha mantém o mesmo desenho nos 55 itens da Amazon sem foto e nos demais, a memória muscular não quebra, e o dono vê por que não dá para copiar em vez de achar que a função sumiu. Custo: um botão apagado a mais nesses cards (o apagado é discreto).

**Relação com "✓ Copiado":** o selo do topo (`.feito`) continua sendo só da mensagem e passa a dizer "✓ Mensagem copiada", para não ficar ambíguo com duas cópias. A borda verde do card (`.done`) também segue só a mensagem (último passo do envio). O estado da imagem fica no próprio botão, sem um segundo selo, para o card não ganhar mais um elemento. O botão "Copiar" do passo 3 não muda de texto.

Observação: a área de transferência guarda um item só. Ao copiar a mensagem, a imagem sai dela, mas "✓ Imagem copiada" continua no botão como registro do passo feito (texto no passado).

## Textos da interface
Sugestão: ficar numa constante de textos junto das outras strings da interface (o projeto não tem arquivo de traduções).

| Onde | Texto |
|---|---|
| Botão | "Copiar imagem" |
| Carregando | "Copiando…" |
| Sucesso (botão) | "✓ Imagem copiada" |
| Aviso, sucesso da imagem | "Imagem copiada! Cole no WhatsApp e volte para copiar a mensagem." |
| Aviso, mensagem copiada depois da imagem (card com imagem copiada) | "Mensagem copiada! Cole como legenda da imagem." |
| Aviso, mensagem copiada sem imagem copiada | "Mensagem copiada!" (como hoje) |
| Selo do topo | "✓ Mensagem copiada" |
| Sem imagem (descrição e erro ao clicar) | "Este produto não tem foto. Abra na loja e copie a imagem de lá, se quiser enviar com foto." |
| Erro, rede (`rede`) | "Não consegui baixar a foto. Confira a internet e tente de novo; se repetir, abra na loja e copie a imagem de lá." |
| Erro, foto indisponível (`indisponivel`) | "Esta foto não está mais disponível na loja. Abra na loja e copie a imagem de lá." |
| Erro, Chrome bloqueou a área de transferência (`bloqueado`) | "O Chrome não deixou copiar a imagem. Clique na página e tente de novo; se repetir, clique no cadeado ao lado do endereço e permita a área de transferência." |
| Erro, navegador sem suporte | "Este navegador não copia imagens. Use o Chrome." |

Os textos finais estão em `TXT_IMG` (`index.html`), com as chaves `rede`, `indisponivel`, `bloqueado`, `semSuporte` e `semFoto`. Falha desconhecida usa `rede`. O `dev` coloca o prefixo "Erro: " no `.status.err`.

## Acessibilidade (WCAG 2.2 AA)
- `<button type="button">` nativo, alcançável por Tab na ordem: Copiar, Copiar imagem, Abrir na loja, Mais ações. Enter e Espaço funcionam.
- Nome acessível: "Copiar imagem" não basta quando há 24 cards iguais; acrescentar `aria-label="Copiar imagem de <título>"` só se o título existir. O rótulo acompanha o estado e sempre começa pelo texto visível (SC 2.5.3): "Copiando…: <título>", "✓ Imagem copiada: <título>" e, ao voltar, "Copiar imagem de <título>".
- Resultado anunciado: aviso (`toast`) e `.status` já têm `role="status"`; a troca de texto do botão não é anunciada sozinha, então o aviso é a fonte de verdade.
- Carregando e sem imagem usam `aria-disabled`, mantendo o foco no botão (nada de foco perdido).
- Cor nunca é o único sinal: ✓ no sucesso, prefixo "Erro:" na falha, texto explicativo na ausência de foto.
- Contraste: texto do botão 4,5:1 (Tinta sobre Superfície); `--enviado` 5:1; anel de foco 3:1 (`--foco`). Estado desabilitado é isento, mas a explicação é texto legível em Mudo.
- Alvos de 36 px (44 px com `pointer:coarse`), acima do mínimo de 24 px do WCAG 2.2.
- `prefers-reduced-motion`: sem animação nova; a troca de texto é instantânea.
- Modo escuro: só tokens existentes.

## O que o dev precisa implementar
1. Em `renderCard`, o botão `.secondary.copyimg` após `.copy`; `aria-disabled` e `aria-describedby` quando não há `d.imagem` (ou `d` nulo).
2. Os estados carregando, sucesso e erro com os textos acima. Marcar o card com uma classe (ex.: `img-done`) para escolher o aviso do passo 3.
3. Clique em botão `aria-disabled` não chama a cópia: mostra o motivo no `.status`.
4. Trocar o texto do selo `.feito` e o do aviso de "Copiar".
5. Estilo `ghost` para `.open` e `min-width` do botão novo (CSS).
6. Conferir em 320, 375 e 1280 px, claro e escuro, com card com e sem foto e com título longo.

## Arquivos de apresentação afetados
`index.html` apenas (marcação em `renderCard`, CSS de `.actions`, `.open` e `.copyimg`, strings). Sem token novo. O estilo de "Abrir na loja" muda em todos os cards.

## Perguntas em aberto
- **Ordem:** deixar "Copiar" à frente (escolhido, pela hierarquia) ou "Copiar imagem" à frente (acompanha a ordem do uso, mas tira a ação principal do primeiro lugar)? Se o dono enviar quase sempre com foto, vale reavaliar.
- A foto copiada deve ser sempre PNG, na resolução do `data.imagem`? Fica com o `arquiteto`; não muda a interface.
