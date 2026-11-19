# Referência: coletas (`coletar_amazon.py`, `buscas.json`, `coletar_shopee.py`, `coletar_ml.js`)

Contrato dos módulos, movido do `CLAUDE.md` em 17/11/2026 (plano `docs/produto/planos/endurecer-entrega2.md`, etapa 5). O `CLAUDE.md` guarda o mapa, as armadilhas que cruzam áreas e as regras de segredo, de LGPD e de afiliado, que valem aqui também. Coletas acessam Amazon e Mercado Livre de verdade: nunca rode em teste.

## Comum às coletas

- As coletas (`coletar_amazon.py`, `coletar_shopee.py`) chamam `criar_banco`, que migra o esquema: precisam de `servidor.py`, `disparo.py` e `genero.py` na mesma pasta.
- Piso de qualidade nas três coletas: nota ≥ 4,5 e Amazon ≥ 100 avaliações ou "compras no mês passado", ML "+50 vendidos", Shopee ≥ 50 vendas; produto usado (`eh_usado`/`RE_USADO`) é recusado.

## `coletar_amazon.py` e `buscas.json`

**Regra de negócio.** Plano `docs/produto/planos/abas-nichadas-e-coleta.md`.

- Coleta da Amazon pelo terminal (`python3 coletar_amazon.py buscas [--cat ABA --ordens vendidos,avaliados,caros]`; relevância é o padrão; `--ordens` exige `--cat`).
- `buscas.json` é `{aba: [termos]}` (chave = aba, valor = lista de termos): 17 abas em 4 grupos (Tecnologia, Casa, Beleza e consumo, Família e estilo; mesma ordem do `ORDEM_ABAS` do `index.html`, conferida por `test_front_constantes.py`), termos em NFC, sem `|`.
- Progresso em `coleta_amazon_feitos.txt` (`ACHADINHOS_FEITOS` troca o arquivo): `busca|<termo>` para a relevância e `ordem|<ordem>|<termo>` para as outras.
- Todos os modos pegam a trava da Amazon (`servidor.travar_rodada`): outra rodada da Amazon no ar sai com 4 e mensagem `PAROU: outra rodada de amazon está em andamento (...)`, antes de abrir banco e progresso.

## `coletar_shopee.py`

**Regra de negócio.** Plano: `docs/produto/planos/perfumaria-tres-lojas.md`.

- Coleta da Shopee pela Open API de afiliados (GraphQL assinado, host fixo, opener sem redirect).
- Subcomandos `conferir` e `conferir --por-item` (o `--por-item` é o portão G1: depois do `conferir`, consulta por `shopId`+`itemId` o primeiro nó válido e sai com 1 se a API não devolver o produto pedido, se o `no_para_item` o recusar ou sem preço legível; com 0, imprime só os ids e o preço lido) e `buscas --cat ABA [--ordens vendidos,relevancia,caros]` (padrão `vendidos`, constante `ORDEM_PADRAO`, também usada pelo `conferir`); piso nota ≥ 4,5 e ≥ 50 vendas.
- Subcomando `importar ARQUIVO` (planilha do painel de afiliados, sem credencial, confere o dono de cada link antes de gravar).
- Só grava `offerLink` `https://s.shopee.com.br/<código>`; confere o dono por `utm_source=an_<ID_AFILIADO_SHOPEE>` antes de gravar.
- Saídas 0/1/2/3/4, 3 = limite da API, 4 = outra rodada da Shopee em andamento em `buscas`/`importar`, o `conferir` não trava.
- Credenciais só no ambiente do comando (`ACHADINHOS_SHOPEE_APP_ID`, `ACHADINHOS_SHOPEE_SECRET`, lido com `pop`; antes, `proteger_processo()` (`prctl(PR_SET_DUMPABLE, 0)`, cópia do garimpo; também no `ml_api.py`) fecha o `/proc/<pid>/environ`, com `AVISO` fixo se o sistema recusar).
- `erro_do_item` separa o erro de um produto (`SemProduto` = `productOfferV2: null`, ou código fora de `ERROS_GERAIS` com HTTP 200) do geral.
- Progresso em `coleta_shopee_feitos.txt` (`ACHADINHOS_FEITOS_SHOPEE`).
- Quem roda é o dono, no terminal dele.
- Formato da API marcado "a confirmar (F5)".

## `coletar_ml.js`

**Regra de negócio.** Uso no `README.md`.

- Coleta e afiliação do Mercado Livre, colado no console do DevTools.
- `ColetaML.coletar({termos, ordem})` em `https://lista.mercadolivre.com.br`, com `ordem` `'relevancia'`, `'caros'` ou `'relampago'` (filtro "Oferta relâmpago"), e progresso `<ordem>|<termo>` fora da relevância.
- Busca sem resultado (literal `.q(...)` com `rescue.type` `zrp` e sem polycard) vai para `estado.semResultado`, fica fora do progresso e a rodada segue, enquanto página sem polycard e sem esse marcador para com "veio sem polycard".
- `ColetaML.afiliar()` em `https://www.mercadolivre.com.br/afiliados/linkbuilder`.
- `ColetaML.atualizar({cat, termos, ordem})` na lista só atualiza preços, exige `cat` ou `termos`, manda `so_existentes: true` depois de conferir com um lote vazio que o servidor o entende, e guarda progresso por dia em `__atualizarML:<servidor>`, que o `zerar()` também apaga.
- Pelo plugin do Chrome, o lead injeta só o `coletar_ml.js` do repositório, e o Chrome precisa de "Acesso à rede local" liberado para os dois endereços do ML, senão as chamadas ao `localhost` ficam presas.
- Traz uma cópia de `buscas.json` entre marcadores, conferida por teste.
- Contrato com o servidor: chamar a partir de `https://lista.mercadolivre.com.br` ou `https://www.mercadolivre.com.br`, sempre com `Content-Type: application/json`, `loja:'ml'` e campos de texto (`data` como objeto; `titulo` até 500 caracteres e os demais campos até 200, senão 400); excluir item não é permitido dessas origens (faça pelo site).

## Histórico

- 18/11/2026: o `conferir` e o `buscas` da Shopee passam a buscar em `vendidos` (sortType 2) em vez de `relevancia`: na relevância a busca "perfume" devolveu 30 nós, todos abaixo do piso (o `conferir` saía com 1); em `vendidos`, 25 de 30 aproveitáveis. O progresso é por ordem: a primeira rodada em `vendidos` refaz os termos já feitos em `relevancia`.
- 15/11/2026: a "Oferta do dia" saiu da busca do ML e a ordem `ofertadodia` foi removida do `coletar_ml.js`.
