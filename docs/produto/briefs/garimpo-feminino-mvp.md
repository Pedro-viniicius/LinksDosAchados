# Requisitos do MVP: garimpo feminino da Shopee

Corte de escopo feito pelo lead em 06/11/2026, a pedido do dono ("o que for melhor, orientado a levantamento de requisito, para o MVP funcionar bem agora; depois vou melhorando"). Deriva de `garimpo-feminino-shopee.md` (a missão completa continua lá) e do plano `docs/produto/planos/garimpo-feminino-shopee.md`.

## Problema
O dono quer saber quais produtos femininos da Shopee vale divulgar. Hoje ele não tem uma lista organizada por nicho nem como medir qual link converte.

## Resultado do MVP
Uma lista de produtos femininos por nicho, com link de afiliado do dono, e um lote de links rastreáveis por subId, pronto para testar nos grupos. Tudo pelo terminal, sem tocar no Etiqueta.

## Requisitos funcionais
| ID | Requisito | Prioridade | Etapa |
|---|---|---|---|
| RF1 | Medir os limites reais da API, sem confundir falha com medição | MVP | 1 a 8, R1 |
| RF2 | Mapear as categorias com nome, classe (`feminina`, `mista`, `fora`) e nicho | MVP | 9, 13, R2 |
| RF3 | Estimar o custo antes de gastar o orçamento e pedir o aval do dono | MVP | 14, R3 |
| RF4 | Garimpar por categoria (estratégias 1 a 4), com a parada documentada em cada uma | MVP | 7, 15 |
| RF5 | Marcar o foco feminino (alto, médio, neutro, descartado) sem apagar nada | MVP | 3 |
| RF6 | Exportar CSV por nicho e categoria, e um relatório curto | MVP | 12 |
| RF7 | Gerar o lote de links de teste com subIds, por nicho, categoria ou item | MVP | 10 |
| RF8 | Relatório de conversões por subId | Depois | 11 |
| RF9 | Lojas (`shopOfferV2` e catálogo) e campanhas (estratégias 5 e 7) | Depois | 15 |
| RF10 | Datafeed FULL como fonte do mapa de categorias (nome e id) | MVP | 9 |

**Por que o RF8 fica para depois:** conversão só existe depois de dias de teste nos grupos, e o painel da Shopee já mostra os relatórios enquanto isso. Entra logo depois do primeiro teste.

**Por que o RF9 fica para depois:** só aumenta a cobertura.

## Decisões a partir do R1 (medições #1 a #88 do `garimpo.db`, 06/11/2026)
- **Página:** `limit` 50, teto de 40 páginas (`pagina50.teto`, #81). O teto real é de 2.000 itens por consulta: a página 100 com `limit` 20 chega ao mesmo total (#56).
- **Sem `pageInfo`:** a consulta completa com `pageInfo` foi recusada duas vezes (#3, #47), e os 20 campos sem ele passaram nas páginas 1 e 10 (#72 a #74). O `pageInfo` passou com 9 campos em `limit` 50 (#71), então a causa exata não foi isolada. O motor não precisa dele: encerra quando a página vem com menos itens que o `limit`, vazia, ou na página 40. Custa no máximo 1 pedido a mais por consulta e não depende de medição nova.
- **`listType`:** sai do motor. O 4 devolve o mesmo que o `productCatId` (#33), o 0 e o 2 não têm item em comum com a categoria e o 1 e o 3 vêm vazios.
- **Filtros:** `isAMSOffer` e `isKeySeller` ficam, porque trazem conjuntos diferentes (3 e 0 em 20 em comum com o sortType 1, #59).
- **Ordenações:** os 5 `sortType` ficam, sem item em comum na página 1 entre eles (#58).
- **Datafeed entra no MVP para o mapa (RF10):** o FULL tem 2 feeds, 110.000 linhas no total, com `global_category1/2` e `global_catid1/2` (#82, #84). O mapa sai em cerca de 220 requisições, contra as 1.400 a 2.400 estimadas por sementes. Limites: não traz comissão, vendas nem `offerLink`, então não substitui o garimpo e nenhuma linha dele vira link de teste. A página de 500 linhas mediu 1,58 MB, perto do teto de 2 MB: se passar, baixar o `limit` do feed, sem subir o teto.
- **Custo:** uma categoria custa até 5 × 40 = 200 pedidos nas ordenações, a cerca de 4,7 s cada (3,7 s de resposta em `limit` 50, mais a pausa): até uns 16 min por categoria. As 20.000 requisições levariam cerca de 26 h, por isso a seleção de categorias e o piloto continuam decidindo o orçamento.
- **Erro 10000:** é transitório. Apareceu 7 vezes em 180 requisições, e a `pagina.100` e o `sort.1` passaram na repetição (#48, #57).
- **subIds:** só letras e números (#41, #42).
- **Limite de taxa:** o 10030 não apareceu em 96 pedidos seguidos (#39), porque a latência já limita o ritmo.

## Requisitos não funcionais (todos MVP)
- **RNF1, confiabilidade:** a saída diz a verdade. `SAIDA=0` só com a medição feita, e falha de rede ou de credencial nunca vira dado.
- **RNF2, retomada:** interrompida (Ctrl+C ou `kill`), a rodada retoma e repete no máximo a página em curso.
- **RNF3, robustez:** uma consulta recusada ou um produto estranho não trava a categoria nem o garimpo.
- **RNF4, segredo:** o Secret nunca vai para log, banco, export ou git, nem fica legível para outro processo durante a rodada longa.
- **RNF5, link do dono:** só sai link que passou na conferência do dono (`utm_source=an_18328801339`).
- **RNF6, cota:** teto de requisições, ritmo e backoff; o gasto fica registrado.
- **RNF7, isolamento:** a produção do Etiqueta não muda.

## Fora do MVP, de propósito
Interface no site, gravar no `achadinhos.db`, paralelismo e cobertura "exaustiva" como critério de pronto. O relatório declara a cobertura alcançada.

## Critério de pronto do MVP
1. `api_findings.md` com limites medidos.
2. Mapa de categorias revisado.
3. Garimpo rodado dentro do orçamento aprovado, com a parada de cada categoria.
4. CSVs por nicho e relatório gerados.
5. Pelo menos um lote de links de teste de um nicho escolhido pelo dono, com o dono conferido.

## Triagem dos achados da revisão (rodada 1, etapas 1 a 7)
| Achados | Decisão | Motivo |
|---|---|---|
| R1 = S2 (falha vira medição, `SAIDA=0`) | Corrigir agora | RNF1; desperdiça a rajada e o R1 |
| R2 (erro permanente trava a categoria) | Corrigir agora | RNF3, RF4 |
| R3 = S6 (nó ruim recusa a página) | Corrigir agora | RNF3 |
| R4 = S4 (`kill` sem `SAIDA=`) | Corrigir agora | RNF2; é o jeito normal de parar a rodada longa |
| R5 (plural `infantis`) | Corrigir agora | RF5; suja o foco |
| R9 = S5 (dono errado termina em saída 0) | Corrigir agora | RNF5 |
| S1 (Secret em `/proc/<pid>/environ`) | Corrigir agora | RNF4; uma linha, e a rodada longa faz parte do MVP |
| S9, só o `--max-req 250` e S8, só o `.gitignore` | Corrigir agora | Custo mínimo; o plano já previa os 250 |
| S3 (`--rajada` explícito) | Não fazer; o `--refazer` não repete a rajada | O dono aceitou a rajada (P4); o risco real era repeti-la |
| R6, R7, R8, S7, resto da S9 | Depois | Falham do lado seguro ou só melhoram texto |
| Pergunta do revisor: colisão da chave do checkpoint com o `mapa` | Resolver na etapa 9 | Ainda não há `fase_mapa` |

A revisão foi encerrada a pedido do dono: o `qa` não concluiu. A verificação das correções é por testes e mutantes do `dev` e pela conferência do lead.
