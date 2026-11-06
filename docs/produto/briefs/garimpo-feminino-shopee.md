# Brief: garimpo completo de produtos femininos na API de Afiliados da Shopee Brasil

Pedido do dono em 06/11/2026, registrado pelo lead. O texto original da missão está na seção "Missão original", logo abaixo da seção "Ajustes obrigatórios".

## Ajustes obrigatórios (regras do projeto, que valem sobre o texto da missão)

1. **Credenciais.** O AppID e o Secret só existem no ambiente de um comando que o dono roda no terminal dele: `read -rs S; ACHADINHOS_SHOPEE_SECRET="$S" ACHADINHOS_SHOPEE_APP_ID=... python3 ...; unset S`. Ficam proibidos:
   - `.env`;
   - arquivo de credencial;
   - `argv`;
   - log;
   - conversa.

   Os agentes nunca veem nem usam o Secret e nunca rodam a ferramenta contra a API real. Toda fase que chama a API vira um subcomando que o dono roda, retomável, que pode ficar em segundo plano com log em arquivo, sem o Secret no log. Os agentes leem os logs, os bancos e os exports para analisar e seguir para a próxima fase.
2. **Stack.** Só Python 3.14 com a biblioteca padrão. O `httpx` não entra (o projeto não tem manifesto de dependências). A assinatura e o host fixo vêm do `coletar_shopee.py` (`assinar`, `URL_API`, opener sem redirect), reaproveitados sem mudar o comportamento de produção do Etiqueta.
3. **Isolamento.** Tudo fica em `tools/garimpo_feminino/`: banco, logs e exports próprios, no `.gitignore`. O garimpo não grava no `achadinhos.db`.
4. **Links.** O link de afiliado continua sendo da conta do dono (`utm_source=an_18328801339`), conferido antes de qualquer export ou link de teste.
5. **Orçamento.** `MAX_TOTAL_REQUESTS` vale 20.000 por padrão. Se a estimativa da Fase 3 passar disso, o lead pergunta ao dono antes de continuar.
6. **Relação com o plano pendente.** `docs/produto/planos/atualizar-precos-shopee-por-item.md` (a consulta por `shopId`/`itemId`) ainda espera a aprovação do dono e mexe no `coletar_shopee.py`. O garimpo não pode conflitar com esse plano.

## Missão original (texto do dono)

Você está no repositório do projeto **Etiqueta**, que já consome a Open API de Afiliados da Shopee Brasil (consulta `productOfferV2`). Sua missão é construir e executar um **garimpo exaustivo, organizado por categoria, de todos os produtos voltados ao público feminino** que a API consegue entregar. No fim, tudo deve estar pronto para eu testar cada produto, com links de afiliado rastreáveis por categoria e um relatório de conversões.

### 0. Regras inegociáveis
- Somente a API oficial (`POST https://open-api.affiliate.shopee.com.br/graphql`); nada de scraping.
- Reaproveitar o cliente e a assinatura do Etiqueta; módulo separado (`tools/garimpo_feminino/`).
- Nunca imprimir, logar ou commitar o Secret; banco, logs e exports no `.gitignore`.
- Tudo retomável: checkpoint por consulta (parâmetros + página).
- Garimpo longo em segundo plano com log em arquivo.
- Começar em ~1 req/s, backoff exponencial com jitter no erro 10030; registrar o limite real.
- `MAX_TOTAL_REQUESTS` configurável (padrão 20.000); se a estimativa da Fase 3 passar disso, perguntar.

### 1. Fatos sobre a API (a confirmar na Fase 1)
- **Autenticação.** `Authorization: SHA256 Credential={AppId}, Timestamp={ts}, Signature={sig}`, com `sig = sha256_hex(AppId + ts + payload + Secret)`, `ts` em segundos e payload igual aos bytes exatos do body.
- **Argumentos do `productOfferV2`:**
  - `keyword`, `shopId`, `itemId`;
  - `productCatId` (categoria de nível 1, 2 ou 3);
  - `listType`: 0 todos, 1 maior comissão (a confirmar), 2 top performance, 3 landing de categoria, 4 detalhe de categoria, 5 detalhe de loja;
  - `matchId`: categoria nos `listType` 3 e 4, loja no 5;
  - `sortType`: 1 relevância, 2 mais vendidos, 3 maior preço, 4 menor preço, 5 maior comissão;
  - `page`, `limit`, `isAMSOffer`, `isKeySeller`.
- **Retorno do `productOfferV2`:** `itemId`, `productName`, `productLink`, `offerLink`, `imageUrl`, `priceMin`, `priceMax`, `priceDiscountRate`, `sales`, `ratingStar`, `commissionRate`, `sellerCommissionRate`, `shopeeCommissionRate`, `commission`, `productCatIds` ([L1, L2, L3]), `shopId`, `shopName`, `shopType`, `periodStartTime`, `periodEndTime` e `pageInfo { page limit hasNextPage }`. As taxas vêm como string decimal.
- Cada produto já vem com `offerLink`. O `generateShortLink` (até 5 subIds) só é preciso para rastrear testes.
- Há relato de erro 10010 "wrong type" com Int64 enviado como número: testar como string.
- O teto de paginação não é documentado (fala-se em 500). Medir.
- A busca por keyword traz ruído: a categoria é a espinha dorsal do garimpo e a keyword é só semente.
- O Explorer V2 lista `listItemFeeds` e `getItemFeedData`: datafeeds FULL e DELTA paginados por offset, até 500 linhas por página, com schema a descobrir. O `datafeedId` pode ser composto; não normalizar.
- Outras consultas: `shopOfferV2`, `shopeeOfferV2`, `conversionReport` e `validatedReport` (até 500 por página, paginação por `scrollId` válido por ~30 s) e, talvez, `brandOffer`.

### Fase 1: reconhecimento e limites reais. Entregável: `docs/api_findings.md`.
1. Ler o código do Etiqueta: cliente, assinatura, credenciais e campos pedidos.
2. Tentar a introspecção GraphQL. Se funcionar, salvar `docs/schema.json`; se não, descobrir por tentativa controlada.
3. Medir:
   - o maior `limit` por página (20, 50, 100, 500);
   - a profundidade de `page`;
   - a sobreposição entre os `sortType`;
   - os `listType` 0 a 4 com `matchId` de categoria, comparados ao `productCatId`;
   - o efeito de `isAMSOffer` e `isKeySeller`;
   - Int64 como número ou como string;
   - o limite de taxa até o erro 10030;
   - o formato aceito para subIds no `generateShortLink`.
4. Testar `listItemFeeds` (FULL e DELTA) e `getItemFeedData` com 1 página: colunas reais, contagem total e se há colunas com nome de categoria.

### Fase 2: mapa de categorias femininas. Entregável: `docs/mapa_categorias.md` e a tabela `categories`.
1. Sementes da taxonomia: keyword × `sortType` 1, 2 e 5, de 2 a 3 páginas cada.
2. Agregar os trios [L1, L2, L3] com frequência.
3. Dar nome a cada id pelas colunas do datafeed. Se o datafeed não tiver nome de categoria, usar as palavras mais frequentes nos títulos mais a semente.
4. Classificar cada categoria como `feminina`, `mista` ou `fora`.
5. Expandir por `productCatId` até não aparecerem ids novos.
6. Associar cada categoria a um nicho.

### Fase 3: piloto e estimativa. Entregável: a seção "Piloto" do `RELATORIO.md`.
Rodar 3 categorias (uma grande, uma média e uma pequena) com a estratégia completa da Fase 4. Medir as requisições, os únicos, a saturação e a estratégia que mais rende. Estimar o custo total; se passar do orçamento, perguntar.

### Fase 4: garimpo exaustivo por categoria (feminina e mista, das folhas L3 para cima, até saturar: as últimas 5 consultas com menos de 2% de itens novos)
1. `productCatId` × `sortType` 1 a 5 × todas as páginas.
2. `listType` 4 e 3 com `matchId`, se trouxerem conjuntos diferentes.
3. `isAMSOffer: true` e `isKeySeller: true`.
4. No teto de paginação, fatiar com keyword + `productCatId` (sementes + n-gramas dos títulos, em bola de neve).
5. Lojas: `shopOfferV2` com termos femininos e, depois, o catálogo de cada loja (`shopId`, ou `listType` 5 + `matchId`), filtrado pelo mapa.
6. Datafeed FULL inteiro, se confirmado, filtrado e mesclado; o DELTA serve para atualizar.
7. Campanhas ativas e futuras (`shopeeOfferV2`: 11.11, Black Friday, Natal).

Dedupe por `itemId`. Guardar todos os campos, `raw_json`, `first_seen`, `last_seen` e a tabela `product_sources`.

**Score de foco feminino:**
- +3 se a categoria é feminina (mista soma 0);
- +2 se o título tem: feminin*, mulher*, dama, lady, gestante, grávida, maternidade, sutiã, calcinha, biquíni, saia, vestido, lingerie;
- −5 se tem: masculin*, homem, homens, barba, barbear, cueca, men;
- −3 se tem: infantil, bebê, kids, menino (exceto no nicho Gestante & Maternidade).

O foco fica alto, medio, neutro ou descartado. Nada é apagado: só marcado.

### Taxonomia de nichos (sementes)
1. Roupas Femininas: vestido, vestido longo, blusa feminina, cropped, body feminino, regata feminina, camisa feminina, saia, saia midi, short feminino, calça feminina, calça wide leg, pantalona, conjunto feminino, macacão feminino, blazer feminino, jaqueta feminina, casaco feminino, cardigan, tricô feminino, moletom feminino, kimono
2. Moda Íntima, Lingerie & Pijamas: lingerie, sutiã, top sem bojo, calcinha, kit calcinha, conjunto lingerie, body rendado, cinta modeladora, shapewear, pijama feminino, camisola, baby doll, robe, meia-calça
3. Moda Praia: biquíni, maiô, saída de praia, canga
4. Fitness Feminino: legging, top fitness, conjunto fitness, short fitness, macaquinho fitness, bermuda ciclista
5. Plus Size: vestido plus size, blusa plus size, calça plus size, lingerie plus size, biquíni plus size
6. Sapatos Femininos: sandália feminina, rasteirinha, salto alto, scarpin, sandália salto bloco, mule, tamanco, sapatilha, tênis feminino, bota feminina, coturno feminino, chinelo feminino, papete, slide feminino
7. Bolsas & Carteiras: bolsa feminina, bolsa transversal, bolsa tiracolo, bolsa de mão, clutch, bolsa tote, mochila feminina, carteira feminina, necessaire
8. Bijuterias, Joias & Acessórios de Cabelo: brinco, argola, colar, choker, pulseira, tornozeleira, anel, kit bijuteria, prata 925, banhado a ouro, piercing, presilha, piranha de cabelo, scrunchie, tiara, laço de cabelo
9. Relógios, Óculos & Acessórios: relógio feminino, smartwatch feminino, óculos de sol feminino, cinto feminino, lenço, chapéu feminino, boné feminino
10. Maquiagem: base, corretivo, pó facial, blush, bronzer, iluminador, contorno, primer, fixador de maquiagem, batom, batom matte, lip tint, gloss, lip oil, máscara de cílios, delineador, lápis de olho, paleta de sombras, pincéis de maquiagem, esponja de maquiagem, kit maquiagem
11. Skincare: sérum facial, vitamina C, ácido hialurônico, niacinamida, retinol, protetor solar facial, hidratante facial, sabonete facial, tônico facial, máscara facial, patch olheiras, skincare coreano, gua sha, rolo de jade
12. Cabelos: shampoo, máscara capilar, óleo capilar, cronograma capilar, leave-in, finalizador cachos, tinta de cabelo, escova secadora, prancha alisadora, babyliss, modelador de cachos, secador de cabelo, touca de cetim, mega hair, aplique, peruca, lace front
13. Unhas: esmalte, esmalte em gel, cabine led, kit manicure, unha postiça, press on, tips, alongamento de unhas, removedor de cutícula, adesivo de unha
14. Perfumes: perfume feminino, body splash, perfume árabe feminino, colônia feminina, kit perfume
15. Corpo, Banho & Depilação: hidratante corporal, óleo corporal, esfoliante corporal, creme para estrias, autobronzeador, cera depilatória, depilador elétrico, depilador a laser, lâmina depilação feminina
16. Cílios & Sobrancelhas: cílios postiços, cílios magnéticos, extensão de cílios, cola de cílios, curvex, henna sobrancelha, lápis de sobrancelha, gel de sobrancelha
17. Saúde Íntima & Bem-estar: coletor menstrual, calcinha absorvente, absorvente, sabonete íntimo, bolsa térmica cólica, colágeno, vitamina cabelo e unha
18. Gestante & Maternidade: roupa gestante, vestido gestante, sutiã amamentação, cinta gestante, cinta pós-parto, bolsa maternidade, almofada amamentação, travesseiro gestante

### Fase 5: links de teste rastreáveis
- **Lote por categoria:** top N (padrão 30), com 10 pela maior comissão em R$, 10 pelos mais vendidos e 10 pela melhor nota com vendas mínimas, sem repetir loja.
- **Links:** `generateShortLink` com `subId1=fem`, `subId2=<slug do nicho>`, `subId3=<id L3>`, `subId4=t<AAAAMMDD>` e `subId5=<canal>`.
- **Sob demanda:** um comando gera link para um `itemId` ou para uma categoria inteira.

### Fase 6: saídas
```
tools/garimpo_feminino/
  garimpo.db   (products, product_sources, categories, shops, campaigns, queries, test_links)
  exports/produtos_femininos.csv e .json, por_categoria/<nicho>/<categoria>.csv, plano_de_testes.csv
  docs/api_findings.md, schema.json, mapa_categorias.md
  RELATORIO.md
```
O `RELATORIO.md` traz:
- os únicos por nicho e por categoria, com a contagem de foco alto e médio;
- a distribuição de comissão por nicho;
- o top 10 por comissão em R$ de cada nicho;
- as estratégias que mais trouxeram itens novos;
- as categorias que bateram o teto da paginação;
- uma estimativa honesta de cobertura;
- as requisições gastas e o tempo total.

### Fase 7: medir os testes
Comando `conversoes`: `conversionReport` e `validatedReport` paginados por `scrollId`, agrupados por subId, com ranking de nichos, categorias e produtos.

### Critérios de pronto (do dono)
- `api_findings.md` com limites medidos, não suposições.
- Mapa de categorias com nomes, classificação e nicho.
- Garimpo rodado até saturar, ou com a parada documentada.
- Exports e relatório gerados; retomada testada (interromper e retomar uma vez).
- Nenhum segredo em logs, exports ou git.
- Resumo final: total de produtos, total por nicho, onde a API limitou a cobertura e 3 próximos passos.
