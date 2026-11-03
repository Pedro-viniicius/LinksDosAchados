# Especificação de UI/UX: Disparo automático

## Objetivo e usuário
O dono, sozinho, no computador. Hoje ele copia mensagens à mão. Passa a criar **regras** que enviam sozinhas, de um número de WhatsApp Business para um grupo, no horário e na quantidade que ele definir. O uso é raro (configurar) e de conferência (ver se enviou). O app continua sendo, antes de tudo, o gerador de mensagens: o fluxo "Copiar" não muda.

Referência do dono (Analytics Lead, "Nova regra"): nome + número, loja, ordem, busca por palavra, grade de categorias. Mantemos o **mecanismo** (regra = número + loja + ordem + categorias). Não copiamos: modal rolável longo, emojis coloridos de terceiros, verde como cor de ação, menu lateral. A identidade segue a Etiqueta (tokens de `ux-ui-identidade.md`).

Nomes de campo seguem o pedido (`nome`, `numero_id`, `categorias`, `loja`, `ordem`, `dias`, `janelas`, `intervalo_min`, `max_por_dia`, `nao_repetir_dias`, `filtro_texto`, `so_com_cupom`, `desconto_min`). Se o plano do arquiteto divergir, o plano manda.

## Fluxo
1. Primeiro uso: Disparo automático → "Cadastre um número" → Números → cadastra, pareia e testa o envio.
2. "Nova regra" → preenche → vê a prévia → "Salvar regra" (nasce **pausada**; o dono ativa de propósito).
3. Na lista, "Ativar". A regra envia sozinha; "Enviar agora" dispara um item na hora (com confirmação).
4. Histórico mostra o que saiu e o que falhou, com a causa e o que fazer.

## Navegação (Hick e hierarquia)
- **Uma única entrada nova no cabeçalho:** link-botão discreto (`ghost`, mesmo estilo de "Editar templates") **"Disparo automático"**, depois de "Adicionar links". Sem ícone, sem Etiqueta, sem contador de destaque. Só ganha um ponto de estado (texto + cor, ver Estados) quando há problema: "Disparo automático · atenção".
- Mesma página, por hash: `#disparo` (regras), `#disparo/nova`, `#disparo/regra/<id>`, `#historico`, `#numeros`. O botão Voltar do navegador funciona. Ao entrar, o foco vai ao `<h2>` da tela; ao voltar, ao link do cabeçalho que a abriu. Atualizar a página mantém a tela.
- Dentro de `#disparo`, **navegação secundária** com três abas (padrão de `.tab`, `aria-current="page"`): **Regras · Histórico · Números de WhatsApp**. "Números" fica aqui e não no cabeçalho: é configuração rara, e assim o cabeçalho ganha 1 item, não 2.
- Cada tela traz "← Voltar às ofertas" (link para `#`) no topo. A tela de ofertas (abas de categoria, filtros, grid) fica oculta (`hidden`) enquanto uma tela de disparo está aberta; o estado dela (aba, página) é preservado.
- Formulário é **tela cheia**, não modal: a referência vira modal rolável longo e quebra no celular; página tem Voltar nativo, foco simples e mais espaço. Uma ação principal por tela: "Nova regra" (lista), "Salvar regra" (formulário), "Salvar número" (cadastro).

## Layout
Coluna única centrada, `max-width` ~720 px (linhas de 45 a 75 caracteres), mesmo `padding` do cabeçalho. Em 1280 px a lista de regras segue em coluna única (cartões largos), sem grade.

### Lista de regras (`#disparo`)
- `<h2>` "Disparo automático"; texto de apoio em Mudo: "Regras que enviam ofertas sozinhas para o seu grupo." À direita (desktop) ou abaixo (320 px): botão **"Nova regra"** (Tinta, não Etiqueta; ver Etiqueta abaixo).
- Cada regra é um cartão (Superfície, `--linha`, `--r`), com:
  - Linha 1: **nome** (Subtítulo) + selo de estado em texto: "Ativa" / "Pausada" / "Atenção" (cor + texto, nunca só cor).
  - Linha 2 (Legenda, Mudo): categorias (até 3, depois "+2"), loja, ordem. Ex.: "Eletrodomésticos, Casa e Decoração · Amazon e ML · Maiores descontos".
  - Linha 3: número rotulado mascarado ("Loja 1 · (00) ·····-0001"), grupo ("Grupo: Achadinhos"), agenda em resumo ("seg a sex, 09:00–12:00 e 18:00–21:00 · 1 a cada 30 min · máx. 20/dia").
  - Linha 4 (Mono, `tabular-nums`): "Último envio: hoje 10:32" e "Próximo: hoje 11:02". Pausada: "Próximo: —". Sem histórico: "Nunca enviou".
  - Ações: **Ativar/Pausar** (secundário), **Enviar agora** (secundário) e `<details>` "Mais ações" com **Editar**, **Duplicar**, **Excluir regra** (`danger`), igual ao padrão do card.
- Ordem da lista: com atenção primeiro, depois ativas, depois pausadas.

### Formulário (`#disparo/nova` e `#disparo/regra/<id>`)
Seções empilhadas com `<fieldset><legend>`, cada uma com título e uma linha de ajuda. Barra de ações fixa no rodapé em 320 px (Salvar + Cancelar), com `padding` para não cobrir campos.
1. **Identificação.** `nome` (texto, obrigatório; ajuda: "Ex.: Eletrodomésticos de manhã"); `numero_id` (select dos números cadastrados; mostra rótulo e estado: "Loja 1 · conectado"; número desconectado aparece com "· desconectado", selecionável, com aviso).
2. **O que enviar.**
   - `categorias`: grade de chips (`<label>` com `<input type="checkbox">` visualmente oculto, mas focável). As opções vêm das abas reais; as novas abas entram sozinhas. Chip: texto + contagem de itens em Mono. Selecionado: borda Etiqueta, fundo `--etiqueta-clara`, **com "✓" no texto** (não só cor). Links "Marcar todas" e "Limpar". Grade `repeat(auto-fill,minmax(160px,1fr))`; alvo 44 px no celular. **Sem ícones** (decisão: nome da categoria basta; emoji de terceiros destoa da marca).
   - `loja`: grupo de rádio segmentado: **Amazon · Mercado Livre · Ambas**.
   - `ordem`: grupo de rádio segmentado, quebra em linhas em telas estreitas: **Mais relevantes · Maiores descontos · Mais baratos · Mais caros · Com cupom primeiro**.
   - Filtros opcionais, em `<details>` "Filtros (opcional)": `filtro_texto` (palavra no título), `so_com_cupom` (caixa "Só itens com cupom"), `desconto_min` (número 0–90, sufixo "%"; ajuda: "Vazio = qualquer desconto").
   - Contador ao vivo (`aria-live="polite"`): "12 itens disponíveis com esses filtros". Zero: aviso "Nenhum item combina; a regra não enviará nada até entrarem itens."
3. **Quando enviar.**
   - `dias`: sete caixas "seg … dom" (chips como categorias; atalhos "Todos os dias", "Seg a sex").
   - `janelas`: lista de faixas "das [09:00] às [12:00]" (`<input type="time">` com rótulos), botão "Adicionar horário" e "Remover" por faixa; mínimo 1. Início maior que fim: erro inline.
   - `intervalo_min`: número, "Intervalo entre mensagens" (minutos, mínimo definido pelo plano, sugerido 10).
   - `max_por_dia`: número, "Máximo de mensagens por dia".
   - Resumo em frase, `aria-live`: "Envia 1 mensagem a cada 30 min, entre 09:00 e 12:00 e 18:00 e 21:00, de seg a sex, até 20 por dia." Se as janelas não comportam o máximo: "Pelas janelas e pelo intervalo, cabem no máximo 14 por dia."
4. **Repetição.** `nao_repetir_dias`: número, "Não repetir o mesmo item por [7] dias" (0 = pode repetir; ajuda: "O mesmo item não é enviado de novo para este grupo dentro desse prazo.") Obs.: vale entre regras do mesmo grupo (decisão do plano).
5. **Prévia.** Cartão com a foto (ou "Sem foto" neutro) e a mensagem renderizada com o template atual de um item real que combina com a regra, mais "Ver outro item" (secundário). Texto: "Assim a mensagem chega no grupo. Usa o template escolhido em Editar templates." Link "Editar templates" abre o painel já existente. Link de afiliado sempre presente na prévia; nada de editar o link aqui.
- Ações: **Salvar regra** (principal, Tinta), "Cancelar". Edição de regra com mudança não salva + Cancelar/Voltar: confirma "Descartar alterações?".

### Números de WhatsApp (`#numeros`)
- Lista de números em cartões: rótulo, telefone **mascarado** ("(00) ·····-0001"), **grupo hospedeiro** (nome; id mascarado "120···@g.us" só em Mono pequeno, opcional), estado da conexão, regras que o usam ("2 regras"). Ações: **Testar envio**, **Parear de novo** (se desconectado), "Mais ações" → **Editar**, **Excluir número** (bloqueado com explicação se há regra ativa).
- **Cadastro** (botão "Adicionar número", abre `#numeros/novo` ou `<details>` na própria tela): `rotulo` ("Como você chama este número"), `telefone` (com DDD, `inputmode="tel"`, `autocomplete="off"`), `grupo` (nome ou id do grupo hospedeiro; ajuda: "O grupo onde as ofertas serão publicadas. O número precisa ser membro."). Salvar.
- **Pareamento** (se o transporte exigir QR; o plano define): após salvar, painel "Conectar o número": passos numerados curtos ("1. Abra o WhatsApp Business no celular. 2. Aparelhos conectados. 3. Aponte para o código") e o QR em área branca fixa (também no escuro, para ser lido), com `alt` "Código QR para conectar o número Loja 1" e contagem "O código expira em 0:45; gerando outro...". Estado muda por `aria-live`. Sem QR no transporte escolhido: o painel vira só o botão "Verificar conexão".
- **Testar envio:** confirma antes ("Enviar uma mensagem de teste para o grupo Achadinhos?"); mensagem de teste neutra e identificada; resultado no toast e no histórico.

### Histórico (`#historico`)
Tabela semântica no desktop (`<table>`, Data/hora, Item, Regra, Status), vira lista de cartões em 320 px (`<th>` ocultos por classe acessível, não por `display:none` do cabeçalho todo). Data em Mono. Filtro "Todos · Só erros" (grupo de botões `aria-pressed`). Status em texto + ícone de texto: "✓ Enviado", "✕ Falhou", "– Ignorado (repetido)". Falha mostra a causa em uma linha e a ação: "Número desconectado. Parear de novo." (link). Paginação igual à do grid. Mostra os últimos 50 envios; "Carregar mais".

## Componentes
| Componente | Existente ou novo | Onde fica |
|---|---|---|
| Botões `cta`, `secondary`, `ghost`, `danger`; `.tab`; `<details>` "Mais ações"; toast `role="status"`; painéis/campos | Existente (reusar) | `index.html` |
| Cartão de regra / de número / de envio | Novo, sobre tokens do `.card` | `index.html` |
| Chip de seleção (checkbox/rádio estilizado) | Novo (`.chip`) | `index.html` |
| Controle segmentado (rádio) | Novo (`.seg`) | `index.html` |
| Selo de estado (`.estado`) | Novo | `index.html` |
| Diálogo de confirmação | Novo: `<dialog>` nativo, `showModal()` | `index.html` |
| QR / painel de pareamento | Novo (condicional ao transporte) | `index.html` |
| Tokens | Existentes; **nenhum novo**. Estados: `--enviado`, `--falhou`; "Pausada"/"Desconectado" usam `--mudo` + texto; "Atenção" usa `--falhou` + texto | `:root` |

## Estados
- **Vazio, sem número:** em `#disparo`, no lugar da lista: "Antes de criar regras, cadastre o número de WhatsApp que vai enviar." + botão principal "Cadastrar número". "Nova regra" fica `aria-disabled` com a mesma explicação ligada por `aria-describedby`.
- **Vazio, com número e sem regra:** "Nenhuma regra ainda. Crie a primeira para enviar ofertas sozinho." + "Nova regra".
- **Carregando:** "Carregando regras…" (`role="status"`), cartões-esqueleto sem animação se `prefers-reduced-motion`. Botões de ação ficam `disabled` + "Enviando…" durante "Enviar agora" e "Testar envio".
- **Regra pausada:** selo "Pausada", cartão com texto Mudo, "Próximo: —", botão "Ativar".
- **Número desconectado:** selo "Desconectado" no cartão do número; regras que o usam ganham selo "Atenção" + "Número desconectado. Parear de novo." (link para `#numeros`); o link do cabeçalho ganha "· atenção". Regras ativas continuam ativas, mas o app avisa que nada será enviado.
- **Erro de envio:** toast `role="alert"` curto ("Não enviou: número desconectado.") + linha no histórico com a causa. Nunca só cor.
- **Sucesso:** "Mensagem enviada para o grupo Achadinhos." (toast) e atualização de "Último envio".
- **Sem itens que combinem:** aviso no formulário e, na lista, "Sem itens para enviar" no lugar de "Próximo".
- **Erro de carga** (servidor fora): "Não foi possível carregar as regras. Verifique se o servidor está aberto e tente de novo." + "Tentar de novo".
- **Erros de campo:** inline, abaixo do campo, `aria-invalid` e `aria-describedby`; no envio inválido, resumo no topo com links e foco nele. Ex.: "Escolha ao menos uma categoria.", "Informe o telefone com DDD.", "O horário final precisa ser depois do inicial.".
- **Conteúdo longo:** nome da regra e do grupo truncam em 2 linhas (clamp); lista de categorias resume com "+N" e expande com `title`/texto completo no formulário.
- **Confirmações (`<dialog>`, foco no botão seguro "Cancelar"):**
  - Excluir regra: "Excluir a regra 'Eletrodomésticos de manhã'? Os envios já feitos continuam no histórico." [Cancelar] [Excluir regra].
  - Excluir número: idem; bloqueado se há regra ativa: "Pause ou mude as regras que usam este número primeiro."
  - Enviar agora: "Enviar 1 mensagem agora para o grupo Achadinhos? Vale como um dos envios de hoje (7 de 20)." [Cancelar] [Enviar agora]. Mostra o item escolhido, com título e foto pequena.
  - Ativar regra pela 1ª vez: sem diálogo; o próximo envio aparece no cartão.

## Textos da interface (pt-BR, para o lugar de strings do `index.html`, como `TXT_IMG`)
Cabeçalho "Disparo automático"; abas "Regras", "Histórico", "Números de WhatsApp"; "Nova regra", "Salvar regra", "Cancelar", "Ativar", "Pausar", "Enviar agora", "Editar", "Duplicar", "Excluir regra", "Excluir número", "Adicionar número", "Salvar número", "Testar envio", "Parear de novo", "Tentar de novo", "← Voltar às ofertas".
Campos: "Nome da regra", "Número que envia", "Categorias", "Loja", "Ordem de envio", "Palavra no título", "Só itens com cupom", "Desconto mínimo (%)", "Dias da semana", "Horários", "Intervalo entre mensagens (min)", "Máximo por dia", "Não repetir o mesmo item por (dias)", "Rótulo", "Telefone com DDD", "Grupo de destino".
Lojas e ordens: "Amazon", "Mercado Livre", "Ambas"; "Mais relevantes", "Maiores descontos", "Mais baratos", "Mais caros", "Com cupom primeiro".
Estados: "Ativa", "Pausada", "Atenção", "Conectado", "Desconectado", "Pareando", "Enviado", "Falhou", "Ignorado (repetido)", "Nunca enviou".

## Acessibilidade (WCAG 2.2 AA)
- Telas por hash: `<main>` e `<h2>` por tela, foco movido ao `<h2>` (`tabindex="-1"`), título da página (`document.title`) atualizado. Cabeçalho "Etiqueta" e navegação secundária com `aria-current`.
- Todos os campos com `<label>`; grupos (loja, ordem, dias, categorias) em `<fieldset><legend>`. Chips e segmentados são `input` nativos (setas nos rádios, Espaço nas caixas); foco visível com `--foco` no chip inteiro, via `:focus-visible` no input irmão.
- Selecionado = borda + fundo + "✓"/negrito; estado da regra e conexão = texto. Contraste: texto sobre `--etiqueta-clara` com Tinta (>4,5:1); bordas de campos com `--linha-campo` (3:1).
- Alvos: 36 px (44 px com `pointer:coarse`) via `--alvo`; chips, selos clicáveis e botões "Remover" idem.
- Diálogos com `<dialog>`: foco preso, Esc fecha, foco volta ao botão de origem. Toasts: `status` (sucesso) e `alert` (erro).
- `time` e `number` nativos; mensagens de erro não dependem de cor. Mascaramento: o telefone mascarado é lido pelo leitor como "final 0001" via `aria-label`; o valor inteiro só aparece no campo de edição.
- `prefers-reduced-motion`: sem transições nem esqueleto animado; QR expira sem animação.
- Etiqueta (laranja) só em: foco, chip selecionado, aba ativa. "Nova regra" e "Salvar regra" ficam em Tinta; "Copiar" continua o único botão Etiqueta do app.
- Dado pessoal: telefone e id de grupo mascarados em listas, histórico e toasts; inteiros só no formulário de edição.

## O que o dev precisa implementar
1. Roteamento por hash (`#disparo`, `#disparo/nova`, `#disparo/regra/<id>`, `#historico`, `#numeros`) alternando `hidden` nas seções, com foco e `document.title`.
2. Marcação e CSS das 3 telas + formulário; componentes `.chip`, `.seg`, `.estado`, cartões, `<dialog>`; textos em um objeto de strings (`TXT_DISPARO`).
3. Link do cabeçalho com estado "atenção" a partir do status dos números/regras.
4. Chips de categoria gerados das abas reais; contador "N itens disponíveis" e prévia vindos da API (rotas do plano do arquiteto); resumo da agenda calculado no cliente.
5. Validação de campo inline (a regra valida de novo no servidor).
6. Mascaramento de telefone e id de grupo na apresentação (o servidor idealmente já devolve mascarado).
7. Pareamento/QR conforme o transporte do plano.

## Arquivos de apresentação afetados
`index.html` apenas (CSS, marcação, strings). Nenhum token novo. Sem fonte, ícone ou dependência nova.

## Perguntas em aberto
- Transporte (WhatsApp Business API oficial, WhatsApp Web via QR, outro)? Define pareamento, estados ("Pareando") e o limite mínimo de `intervalo_min`.
- "Mais relevantes": qual dado define (avaliação, vendas)? Hoje os itens têm preço, desconto e avaliação.
- Existe "cupom" nos dados dos itens? Sem ele, "Com cupom primeiro" e `so_com_cupom` saem da v1.
- O prazo `nao_repetir_dias` vale por grupo ou por regra? Proposta: por grupo.
- Regra nasce pausada (proposta); quer que nasça ativa?
- Mais de um grupo por número? Esta spec assume 1 grupo hospedeiro por número.
- Horário do servidor e fuso: mostrar "horário de Brasília" nos horários?
