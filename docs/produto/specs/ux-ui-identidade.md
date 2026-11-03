# Especificação de UI/UX: identidade visual e usabilidade do `index.html`

## Objetivo e usuário
O dono, sozinho, no computador. Ação frequente: **Copiar** a mensagem de um card. Ações raras: templates, adicionar links, mover, excluir, atualizar preço. Sem feature nova nem removida; só apresentação (CSS, marcação e strings de marcação no JS).

## Decisões e princípio
| Mudança | Princípio |
|---|---|
| Tokens em `:root` (Papel, Superfície, Linha, Mudo, Tinta, Etiqueta, estados), escala tipográfica, espaçamento (4–48) e raio; modo escuro por `prefers-color-scheme` | Consistência; espaço em branco |
| Geist e Geist Mono (Google Fonts, fallback de sistema); preços, desconto e contagens das abas em Mono com `tabular-nums` | Sinal-ruído |
| Card: "Copiar" é o único botão em Etiqueta; "Abrir na loja" fica em contorno | Hick |
| Recarregar, Mover, Excluir e Atualizar preço dentro de `<details>` "Mais ações" (sem JS) | Hick; carga cognitiva |
| Cabeçalho: Editar templates e Adicionar links viram botões discretos (ghost); "Copiar todas" em contorno; nenhum botão de destaque | Hick |
| Card: loja vira rótulo neutro (sem laranja Amazon / amarelo ML); URL crua removida; ordem título → preço/desconto → avaliação → mensagem → ação; título limitado a 2 linhas | Sinal-ruído; hierarquia |
| Contador do cabeçalho mantém o texto original (totais por loja, única visão deles), em Legenda Mudo; contagem das abas sem parênteses e em Mono | Sinal-ruído |
| Espaçamento em tokens, grid `minmax(min(100%,340px),1fr)` (sem rolagem horizontal em 320 px), painéis com campos empilhados | Espaço em branco |
| Etiqueta só em: Copiar, aba ativa (Etiqueta clara + borda + negrito), foco e o desconto (`.off`, Etiqueta escura) | ~5% de acento |

## Acessibilidade (WCAG 2.2 AA)
- Texto sobre Etiqueta usa Tinta (`#111110`, ~6,4:1). Mudo sobre Papel ~5:1.
- Foco: anel de 2px em `--foco` (Etiqueta escura no claro, 4,8:1; Etiqueta no escuro). A Etiqueta pura sobre Papel dá ~2,9:1, abaixo de 3:1, por isso o anel usa a variante escura no modo claro.
- Todos os campos têm rótulo (`label` ou `aria-label`), inclusive os 3 selects e a busca; textarea do card tem `aria-label`.
- "Copiado" não depende de cor: aparece "✓ Copiado" no card (`.feito`, visível com `.done`) além da borda verde; toast com `role="status"`.
- Abas são `<button>` com `aria-pressed`; alvo mínimo 36 px (44 px com `pointer:coarse`), paginação 32 px.
- `prefers-reduced-motion` desliga transições. Preço antigo tem texto "Preço antigo" para leitor de tela.

## Tokens extras (rodada 2)
`--sobre-etiqueta`, `--fundo-imagem`, `--linha-campo` (= Mudo, 5:1 claro e escuro; só em campos, SC 1.4.11; `--linha` fica em cards e divisórias). `--t-valor` agora é Mono 28/32·500·-0,02em. `.old` e `.off` usam tokens Mono 13 e 14. Cards: `.card textarea{flex:1 0 auto}` alinha as ações na linha sem travar o redimensionamento manual (o `flex` fica só no card, não na regra global de `textarea`). O chevron de "Mais ações" tem texto alternativo vazio.

## Textos alterados
"Templates" → "Editar templates"; "+ Adicionar links" → "Adicionar links"; "Excluir" do painel → "Excluir template"; contador sem mudança de texto; novo "Mais ações", "Mover para", "✓ Copiado".

## Estados
Padrão, hover, foco, desabilitado (opacidade .45 e cursor not-allowed), erro (`.status.err` em Falhou), vazio (`.status:empty` some), sucesso (`.done`), título longo (clamp 2 linhas) e card sem dados (só mensagem).

## Arquivos de apresentação afetados
`index.html` apenas. Seletores do JS preservados; `.open` do botão não conflita com `.box.open` (estilos separados).

## Pendências / observações para o dev
- Card re-renderiza no "Atualizar preço", o que apaga `.done` (comportamento já existente).
- Excluir não pede confirmação (regra existente); agora fica dentro de "Mais ações", o que já reduz clique acidental.
