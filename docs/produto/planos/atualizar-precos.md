# Plano técnico: preço sempre atualizado
- Brief: não há. O pedido do dono, de 2026-11-04, foi transcrito pelo lead. Spec de tela: `docs/produto/specs/atualizar-precos.md` (designer, em paralelo).
- Data: 2026-11-04

## Objetivo e critérios de aceite
Não mandar preço errado aos grupos. Para isso: atualizar os preços em lote nas três lojas, travar o disparo de preço velho e mostrar no cartão a idade do preço. Tudo funciona agora, sem as APIs oficiais, e já deixa o ponto de troca pronto para elas.

- **CA1 — Data do preço.** Cada item guarda `preco_em`, o momento em que o preço foi confirmado pela última vez.
  - Gravam `preco_em`: a coleta, a atualização em lote, o "Atualizar preço" do cartão e o POST do site, sempre que a escrita traz preço legível (`ler_preco`).
  - Não gravam: reclassificação, correção de público, troca de url e o saneamento do `migrar_categorias.py`.
  - A migração v3 é aditiva. Ela preenche o que já existe com `criado_em`, um limite inferior seguro, e não mexe em `atualizado_em`.
- **CA2 — Amazon em lote.** `python3 atualizar_precos.py amazon [--cat ABA] [--produtos N]`.
  - Lê as páginas de busca dos termos e das ordens já coletados, com o mesmo piso e a mesma recusa de usado.
  - Só atualiza item que já existe: nunca insere e nunca troca link de afiliado.
  - Retoma no mesmo dia. Em captcha, 503 ou 429, para com saída 3 e o progresso salvo.
  - Termina com um resumo de contagens.
- **CA3 — ML em lote.** `ColetaML.atualizar({cat, ordem})`, no console, em `https://lista.mercadolivre.com.br`. Mesmas regras do CA2, gravando pelo `POST /api/items` com `"so_existentes": true`.
- **CA4 — Shopee em lote.** `python3 atualizar_precos.py shopee --cat ABA`, pela Open API, com as credenciais só no ambiente do comando: `pop` do Secret, conferência do dono antes de gravar e saída 3 no limite. O `coletar_shopee.py importar`, que já existe, passa a contar como atualização porque grava `preco_em` pelo `upsert`.
- **CA5 — Item que sumiu ou mudou.** Item que sumiu, ficou indisponível, caiu do piso ou virou usado não é atualizado nem apagado. Ele entra no resumo, o preço dele envelhece e a trava (CA6) o tira do disparo.
- **CA6 — Trava no disparo.** O disparo não envia nem mostra na prévia item com `preco_em` nulo, malformado ou mais velho que `config.preco_validade_horas`. O padrão é 24, de 1 a 168. Valor ausente ou inválido vale 24.
- **CA7 — Aviso.** Quando um horário fica sem mensagem porque todos os itens que casam com os filtros têm preço velho, a regra grava `AVISO_PRECO_VELHO`. A prévia com `"com_info": true` traz `preco_velho` (contagem).
- **CA8 — API v1.** Cada oferta traz `preco_em` (texto ou null). Há um filtro opcional `preco_max_horas`, de 1 a 168. Sem ele, a resposta é igual à de hoje, mais o campo novo. O contrato fica atualizado em `docs/produto/referencias/api-ofertas.md`.
- **CA9 — Site.** O `GET /api/items` traz `preco_em`. O cartão mostra a idade do preço e marca o preço velho, conforme a spec. A validade se configura na tela da spec, gravada por `PUT /api/config/preco_validade_horas`. O "Atualizar preço" do cartão atualiza a idade.
- **CA10 — Ponto de troca.** Três coisas ficam num lugar só, o `atualizar_precos.py`: a seleção dos itens, a gravação e o resumo. Cada loja é uma fonte trocável em `FONTES`. Um teste com uma fonte falsa prova o encaixe sem rede.
- **CA11 — Testes.** Nenhum teste acessa a rede, roda coleta real ou abre o banco real.

## Contexto atual
- **`upsert`** (`servidor.py:326-358`):
  - insere ou, com título, atualiza todos os `CAMPOS` e `atualizado_em`, depois de passar por `sanear_precos` (`:335`);
  - preserva o link de afiliado pelo `sql_link_preservado` (`:170-178`, `:355`);
  - não muda `cat`;
  - sem título, não faz nada (`:351`).
- **PATCH com `data`** (`servidor.py:807-812`): mesmo saneamento, também mexe em `atualizado_em`.
- **Leitura dos itens:** `linha_para_item` (`servidor.py:113-125`) monta o item do `GET /api/items` (`:728-734`).
- **Rotas do ML:** `ROTAS_ML` (`servidor.py:51`) libera `POST /api/items` para as origens do ML.
- **Quem regrava `atualizado_em` sem mexer no preço:**
  - `migrar_categorias.py:364` e `:371` (zera `preco_antigo` e `desconto`);
  - `classificar_lista.py:243`;
  - `PUT .../genero` (`servidor.py:856-857`).

  Por isso `atualizado_em` não serve como idade do preço. Ele é também o cursor da v1 (`api_ofertas.py:231-250`).
- **Esquema:** `PRAGMA user_version` 2 em `disparo.migrar` (`disparo.py:29`, `:107-135`), com passos em SQL na tupla `ESQUEMA_V*` (`:30-58`). O `criar_banco` cria `items` e chama `migrar` (`servidor.py:83-106`).
- **Seleção do disparo:** `elegiveis` (`disparo.py:742-781`) conta `info['casam']`. O `processar_slot` escolhe o aviso entre filtros, repetição e link (`:1041-1043`, textos em `:987-990`). A prévia com `com_info` sai em `disparo.py:1263-1270`.
- **Oferta da v1:** `oferta()` (`api_ofertas.py:61-122`). Os parâmetros ficam em `PARAMETROS` (`:29`) e o teto em `MAX_PARES` (`:32`).
- **Coleta da Amazon:**
  - `parse_busca` devolve todos os resultados da página; o corte em 30 é de quem chama (`coletar_amazon.py:214`);
  - `passa_piso` (`:127`), `eh_usado` (`:101`) e `baixar` (`:43-50`, que levanta `Bloqueado` em captcha);
  - progresso em `coleta_amazon_feitos.txt` (`:144-183`);
  - página do produto em `servidor.buscar_produto_amazon` (`servidor.py:397-404`), com redirect conferido.
- **Coleta do ML:** `coletar()` (`coletar_ml.js:790-903`), com piso e usado em `extrairItens` (`:651-673`), captcha em `:834` e progresso no localStorage (`:693-708`).
- **Coleta da Shopee:** `credenciais` com `pop` (`coletar_shopee.py:314-323`), `buscar` (`:376-397`), `no_para_item` com piso e usado (`:219-256`), `conferir_dono` (`:418`), `importar` pelo `upsert` (`:495-527`).
- **Front:** `fetchItem` (`index.html:534-544`) faz `PATCH` com `data`, e só a Amazon tem o botão (`:652`).
- **Banco**, medido em modo ro hoje (ids e contagens, sem dado pessoal):
  - `user_version` 2;
  - Amazon com 5.643 itens, 353 sem preço; ML com 2.705, todos `meli.la`; Shopee com 540;
  - 10 das 17 abas com itens;
  - `criado_em` 03/11 para 5.136 itens da Amazon e para todos os do ML e da Shopee, e 04/11 para 507 da Amazon;
  - 0 regras, 0 números, tabela `config` vazia.
- **Páginas de uma atualização completa.** Amazon: 282 pares (termo, ordem) com itens, tirados de `coleta_amazon_feitos.txt`, com 34,8 itens por termo em média. ML: 99 termos. Shopee: 42 termos. 26 itens da Amazon e 22 do ML têm `busca` fora do `buscas.json`; os do ML são o ALIAS e 1 vazio.

## Abordagens consideradas
**Idade do preço**

| Abordagem | Prós | Contras | Risco |
|---|---|---|---|
| A. Usar `atualizado_em` | Zero esquema | Falso: migração e gênero regravam a coluna; ela é o cursor da v1 | Alto: preço velho passa por novo |
| **B. Coluna `items.preco_em` (v3)** | Gravada nos mesmos 2 pontos de escrita (`upsert` e PATCH); `SELECT *` já a traz | Testes que comparam linhas inteiras ou a versão 2 mudam | Baixo |
| C. Tabela `precos(item_pk, preco_em)` | Não altera `items` | JOIN em 4 leituras e escrita em 2 lugares, para um fato da própria linha | Médio: tabela órfã |

**Lote da Amazon** (tempos não verificados: estimativa pelas pausas do código, 4 a 8 s mais 1 a 3 s de rede)

| Abordagem | Tempo para 5.643 itens | Contras | Risco de captcha |
|---|---|---|---|
| Página do produto, item a item | cerca de 5.643 × 9 s ≈ **14 h** | Uma requisição por item | Alto: milhares de acessos seguidos |
| **Página de busca dos termos já coletados** | ≤ 282 páginas × 9 s ≈ **40 min** (Perfumaria ≈ 25 min). Para cedo quando o termo já não tem item pendente | Cobertura parcial: item que saiu da página não é visto | Baixo: o mesmo volume de uma coleta |
| **Busca + página do produto só para o que faltou, até `--produtos N`** | 40 min + N × 9 s | Um parâmetro a mais | Controlado pelo N |

**Prazo da trava:** é um valor global em `config`, um número só para o disparo, o cartão e a v1. Prazo por regra pediria coluna nova e tela, e o dono pediu "um prazo".

## Decisão
1. **B: coluna `preco_em`.** A regra é uma só, no `upsert` e no PATCH: `preco_em = agora()` se `ler_preco(preco)` dá valor, senão `NULL`. O `atualizado_em` continua como está: o item atualizado reaparece no cursor da v1 com o preço novo, o que é desejado.
2. **Lote só atualiza, nunca insere:** `upsert(con, it, inserir=False)` devolve `'ausente'` quando o item não existe. O `CASE` do link segue igual, então a guarda de afiliado é a mesma da coleta.
3. **Novo `atualizar_precos.py`**, script de terminal no padrão das coletas, só com stdlib e import tardio de `coletar_amazon` e `coletar_shopee`. É o ponto de troca. A seleção (itens da loja nas abas), a gravação (`upsert` com `inserir=False`, commit por termo) e o resumo ficam nele. A busca de preços fica em `FONTES = {'amazon': fonte_amazon_busca, 'shopee': fonte_shopee_api}`. Quando chegar a PA-API (até 10 ASINs por `GetItems`), a API do ML (multiget por id) ou a consulta da Shopee por `itemId`, entra uma fonte nova por id, e a seleção, a gravação e o resumo não mudam.
4. **ML fica no console:** `ColetaML.atualizar`, que reaproveita o laço do `coletar()`.
   - Usa outra chave de progresso, `__atualizarML:<servidor>`, com `<AAAA-MM-DD>|<ordem>|<termo>`.
   - Lê a página inteira, sem o corte de 30.
   - Manda `so_existentes: true`.
   - Rota e CORS não mudam.
5. **Item que sumiu, ficou indisponível, caiu do piso ou virou usado:** a fonte o classifica, o orquestrador não grava e conta no resumo. Nada é apagado.
   - Um campo de situação persistente fica para a entrega 2 (P3): a trava pela idade já o tira do disparo e da v1 com filtro.
   - Item sem preço legível na busca ou no produto conta como indisponível e mantém os dados antigos. Não apagamos o preço.
6. **Disparo:** o filtro de idade fica no laço do `elegiveis`, depois dos outros filtros e fora do `casam`. Aviso: sem `casam` e com `velhos`, vai `AVISO_PRECO_VELHO`; sem `casam` e sem `velhos`, vai `AVISO_FILTROS`.
7. **v1 informa e filtra só quando pedem** (P2), sem mudar a resposta padrão para o Turbo.
8. **Sem botão de lote no site nesta entrega.** O ML exige o console e a Shopee exige o Secret no terminal. A spec decide como o site mostra os comandos e a idade.

Excesso de engenharia evitado: nada de tabela de situação, nada de job em thread no servidor, nada de prazo por regra.

## Esquema e contratos
```sql
-- v3, em disparo.migrar (BEGIN IMMEDIATE, como v1/v2); VERSAO_ESQUEMA = 3
-- só se items existe e não tem a coluna (o criar_banco novo já cria items com preco_em TEXT)
ALTER TABLE items ADD COLUMN preco_em TEXT;
UPDATE items SET preco_em = criado_em
 WHERE tem_dados = 1 AND preco != ''
   AND criado_em GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]';
```
- `servidor.upsert(con, it, inserir=True) -> 'inserido' | 'atualizado' | 'ausente'`.
- `POST /api/items` aceita `{"items": [...], "so_existentes": true}`. Se `so_existentes` vier e não for `bool`, a resposta é 400. A resposta ganha `ausente`. A forma em lista continua igual.
- `linha_para_item` ganha a chave de topo `preco_em` (str ou null).
- `disparo.preco_recente(preco_em, agora, horas) -> bool`: `fullmatch` do formato ISO e `>= (agora - horas)`.
- `disparo.validade_horas(con) -> int`: lê `config.preco_validade_horas` com `json.loads`; aceita só `int`, sem `bool`, de 1 a 168; senão devolve 24.
- `AVISO_PRECO_VELHO = 'Nenhuma mensagem saiu: os itens que casam com esta regra têm preço de mais de {h} h. Atualize os preços.'`. O texto final vem da spec.
- Prévia com `com_info`: `{"itens", "recusados", "preco_velho"}`.
- Na v1, a oferta ganha `preco_em` no fim. O parâmetro `preco_max_horas` (`[0-9]{1,3}`, de 1 a 168) vira `AND preco_em >= ?` no SQL.
- `atualizar_precos.py` (CLI):
  - `amazon [--cat ABA] [--produtos N]`, com N de 0 a 500 e padrão 0;
  - `shopee --cat ABA`;
  - progresso em `atualizar_precos_feitos.txt` (`ACHADINHOS_FEITOS_ATUALIZAR`), linhas `<loja>|<AAAA-MM-DD>|<ordem>|<termo>`;
  - saídas: 0 ok, 1 erro, 2 argumento ou configuração, 3 bloqueio ou limite (o progresso fica salvo).
- **Fonte:** `fonte(itens, opcoes)` recebe `{item_id: linha}` e gera `(rotulo, [Observacao(item_id, situacao, it)])`. A `situacao` é `ok`, `fora_do_piso`, `usado`, `indisponivel` ou `sumiu`, e `it` vai no formato do `upsert`. O orquestrador só grava `ok` de `item_id` selecionado. Resumo: atualizados, fora do piso, usados, indisponíveis, sumidos e não vistos (com até 20 ids). Sem título nem url na saída.
- **Fonte da Amazon:**
  - para cada termo do `buscas.json` com itens selecionados, lê as ordens marcadas em `coleta_amazon_feitos.txt` (relevância se não houver);
  - para quando o termo não tem mais item pendente;
  - com `--produtos N`, abre a página do produto dos não vistos que estão mais velhos que a validade, com pausa entre um e outro;
  - em `Bloqueado` ou `HTTPError` 503 ou 429, levanta `Bloqueio`.

## Etapas
| # | Etapa | Arquivos | Verificação | Responsável | Grupo | Sensível | CAs |
|---|---|---|---|---|---|---|---|
| 1 | Migração v3 e `preco_em` nas escritas. **`disparo.py`:** passo v3 condicional, `VERSAO_ESQUEMA = 3` e as funções `preco_recente`/`validade_horas`. **`servidor.py`:** `CREATE TABLE` com `preco_em`, `upsert(inserir=)`, PATCH, `so_existentes` no POST e `linha_para_item`. **Testes:** banco v0, v1 e v2 → v3, backfill = `criado_em`, `atualizado_em` intacto, código antigo sobre banco v3, versão futura 4, PATCH só de url ou cat não muda `preco_em`, `so_existentes` não insere e não troca `meli.la`. Os asserts de versão 2 passam a 3 | `disparo.py`, `servidor.py`, `testes/test_disparo.py`, `testes/test_servidor.py`, `testes/test_genero_qa.py` | `python3 testes/test_disparo.py -v`, `python3 testes/test_servidor.py -v`, `python3 testes/test_genero_qa.py`, `python3 testes/test_genero.py` (`migrar` sobre banco sem `items` não pode falhar), `python3 testes/test_servidor_qa.py`, `python3 testes/test_migrar_categorias.py`, `python3 testes/test_coletar_amazon.py`, `python3 testes/test_coletar_shopee.py` | dev | A | sim (migração, entrada pública) | CA1, CA3 (servidor) |
| 2 | Trava e aviso no disparo: filtro de idade no `elegiveis` (contador `velhos`), aviso no `processar_slot`, `preco_velho` na prévia `com_info`. Testes com relógio injetado: 23 h passa, 25 h não, `NULL` não, `config` inválido vale 24 | `disparo.py`, `testes/test_disparo.py`, `testes/test_disparo_servidor.py` | `python3 testes/test_disparo.py -v`, `python3 testes/test_disparo_servidor.py`, `python3 testes/test_disparo_qa.py` | dev | B | sim (concorrência com o agendador) | CA6, CA7 |
| 3 | v1: `preco_em` na oferta e o filtro `preco_max_horas`, mais as listas fixas de campos nos testes e o contrato (campo, parâmetro, erro 400, guia de encaixe para o Turbo) | `api_ofertas.py`, `testes/test_api_ofertas.py`, `testes/test_api_ofertas_servidor.py`, `docs/produto/referencias/api-ofertas.md` | `python3 testes/test_api_ofertas.py -v`, `python3 testes/test_api_ofertas_servidor.py`, `python3 testes/test_api_ofertas_qa.py`, `node --test testes/api_ofertas.test.mjs` | dev | B | sim (entrada pública) | CA8 |
| 4 | `atualizar_precos.py` com `FONTES`, fonte Amazon (busca e `--produtos`), fonte Shopee (Open API, reaproveitando `credenciais`/`buscar`/`no_para_item`/`conferir_dono`), progresso, resumo e saídas. Testes com `mock` em `C.baixar`, `S.buscar_produto_amazon` e `CS.buscar`/`CS.destino`, mais uma fonte falsa. Casos: captcha → 3 com progresso; não insere; url de afiliado intacta; piso e usado não gravam; Secret ausente → 2 e nunca na saída | `atualizar_precos.py`, `testes/test_atualizar_precos.py`, `testes/fixtures/amazon-busca.html` | `python3 -m py_compile atualizar_precos.py`, `python3 testes/test_atualizar_precos.py -v` | dev | B | sim (segredo, rede) | CA2, CA4, CA5, CA10, CA11 |
| 5 | `ColetaML.atualizar({cat, termos, ordem})`: só em `lista.mercadolivre.com.br`, chave de progresso própria por dia, sem o corte de 30, `so_existentes: true` e resumo com `ausente`, fora do piso e usados. Testes com `fetch` falso | `coletar_ml.js`, `testes/coletar_ml.test.mjs` | `node --test testes/coletar_ml.test.mjs`, `node --test testes/coletar_ml_qa.test.mjs` | dev | B | sim (entrada pública) | CA3, CA5 |
| 6 | Front conforme a spec: funções globais `textoIdadePreco(preco_em, agora)` e `precoVelho(preco_em, horas, agora)`, leitura e gravação de `config/preco_validade_horas` e a idade no `renderCard`. Teste de página novo, sem navegação por hash | `index.html`, `testes/precos.test.html` | servidor de teste na 8766 (receita do CLAUDE.md), `PORTA=8766 node testes/rodar.mjs precos`, `PORTA=8766 node testes/rodar.mjs copiar-imagem`, `PORTA=8766 node testes/rodar.mjs mensagens` | dev (lógica) + designer (revisão) | B | não | CA9 |
| 7 | Uso no README: os comandos das três lojas, os tempos estimados, o que fazer em captcha e a variável `ACHADINHOS_FEITOS_ATUALIZAR` | `README.md` | leitura do revisor | dev | C | não | CA2-CA5 |

Grupo B só começa depois da etapa 1. As etapas 2 a 6 não compartilham arquivo. O `CLAUDE.md` fica com o lead, depois da aprovação.

## Pontos para o seguranca
- **Migração v3:** `BEGIN IMMEDIATE` com releitura da versão; `ALTER` só se a coluna faltar; backfill sem tocar `atualizado_em` nem `url`. O servidor antigo, no ar enquanto uma coleta nova migra, grava sem `preco_em`. É o lado seguro: o item parece velho.
- **`so_existentes`** vem das origens do ML: exige `bool`; não cria rota nem muda CORS; com `inserir=False`, o `upsert` não deixa a origem do ML criar item.
- **Secret da Shopee no `atualizar_precos.py`:** só por `coletar_shopee.credenciais()` (`pop`), nunca em `argv`, log ou mensagem de exceção. A conferência do dono vem antes da primeira gravação. O host é fixo e o redirect não é seguido.
- **Rede:** só URLs montadas pelo código (`url_busca` com `quote_plus` e `buscar_produto_amazon`, com redirect conferido). Nada de url vinda do banco em `--produtos`: a url sai de `link_afiliado(item_id)` com `item_id` `[A-Z0-9]{10}`.
- **`config.preco_validade_horas`:** o `PUT /api/config` aceita qualquer JSON, então a leitura valida e falha para 24. O valor não muda o que sai; só restringe.
- **v1:** parâmetro novo pela regex de `_inteiro`; `MAX_PARES` recalcula sozinho; log sem query.
- **Resumo:** só contagens e ids numéricos ou ASIN; nada de título, url ou cookie.

## Riscos e como reverter
- **Migração v3:** antes de reiniciar o servidor do dono ou rodar qualquer comando novo, o lead faz backup por `sqlite3 achadinhos.db ".backup backups/antes-v3.db"`. O código antigo funciona sobre o banco v3, porque ignora a coluna e o `migrar` não faz nada. Para reverter: volte o código, e a coluna fica sem efeito. Se precisar, restaure o backup, mas perde as atualizações feitas desde então.
- **Trava bloqueia tudo no primeiro dia:** com 24 h, todos os preços de 03/11 e 04/11 ficam velhos. Hoje não há regra, então nada quebra. A tela e o aviso explicam o motivo. Para aliviar: subir a validade ou rodar o lote.
- **Captcha e bloqueio:** na Amazon, para com saída 3; espere de 15 a 30 min e rode de novo (retoma pelo progresso do dia). Use `--cat` para dividir. Se o captcha repetir, pare por hoje: não aumente o `--produtos`. No ML, o `falhar` atual: resolva na aba e chame `atualizar` de novo. Na Shopee, saída 3 no limite da API.
- **Cobertura da busca desconhecida** (não verificado): o primeiro lote real mede os "não vistos". Se passar de cerca de 20%, use `--produtos` aos poucos ou leia a página 2 (P4).
- **Lote grava também título e foto novos**, com a mesma semântica da coleta de hoje. O link de afiliado nunca muda. Para reverter um lote ruim: restaure o backup.
- **Conflito com trabalho não commitado:** a feature abas-nichadas ainda não tem commit e mexe nos mesmos arquivos. Faça o commit dela antes da etapa 1 (premissa).

## Perguntas em aberto e premissas adotadas
- **P1.** "A questão das API" é a das APIs oficiais das lojas (Open API da Shopee, API do ML, PA-API)? Se for a API v1 para o Achadinho Turbo, a etapa 3 muda de peso. A premissa é que são as das lojas.
- **P2.** A v1 deve aplicar a validade por padrão? Hoje não aplica, para não esvaziar o Turbo sem aviso. Se o dono quiser, troca-se o padrão e o Turbo é avisado pela doc.
- **P3.** O dono quer marcar ou excluir em massa os itens que sumiram ou caíram do piso? A premissa é que nada é apagado nem marcado, e isso fica para a entrega 2.
- **P4.** Qual o padrão do `--produtos` e da página 2 na Amazon? Premissa: 0 e só a página 1, até medir.
- **P5.** O dono tem as credenciais da Open API da Shopee agora? Se não tiver, a fonte Shopee fica pronta e sem uso, e a Shopee se atualiza pelo `importar` do painel, termo a termo. Isso é manual, cerca de 1 a 2 min por termo, e não foi verificado.
- **P6.** O dono quer o botão "Atualizar preço" item a item no ML e na Shopee? Premissa: não nesta entrega.
- Premissas: a validade vale 24 h, de 1 a 168. O progresso é por dia local. Cada loja roda no seu ambiente atual: Amazon e Shopee no terminal, ML no console.

## ADR
**ADR — Idade do preço em `items.preco_em` e lote por fontes trocáveis (2026-11-04)**
- **Contexto.** Preço velho vai para os grupos. O `atualizado_em` mistura reclassificação e cursor da v1. As APIs oficiais das lojas ainda não chegaram.
- **Decisão.**
  - Uma coluna `preco_em`, gravada só pelas escritas que trazem preço, com migração v3 aditiva e preenchimento conservador com `criado_em`.
  - Um prazo global em `config`, aplicado pelo disparo e, sob pedido, pela v1.
  - Um `atualizar_precos.py` que concentra a seleção, a gravação só de itens existentes e o resumo, com uma fonte por loja em `FONTES`.
- **Alternativas rejeitadas.**
  - Usar `atualizado_em`: dá dado falso.
  - Tabela separada: JOIN para um fato da própria linha.
  - Lote item a item na Amazon: 14 h e captcha.
  - Job no servidor: o ML e a Shopee não rodam lá.
- **Consequências.** Testes que fixam a versão 2 e a lista de campos mudam. Uma API oficial nova entra como fonte por id, sem tocar no disparo, na v1 nem no front.

## Decisões do dono (2026-11-04)
- **Onde roda o lote:** terminal (Amazon e Shopee) e console do Chrome (ML), como na Decisão 8. O site não dispara lote. Ele mostra a idade do preço, o filtro de preço velho e um quadro "Como atualizar" com o comando de cada loja. A spec foi ajustada a isso.
- **Validade:** um número só, `config.preco_validade_horas` (padrão 24, de 1 a 168), como no CA6. Não há prazo por regra.
- **P1:** "a questão das API" são as APIs oficiais das lojas.
- **P5:** o dono ainda não tem a credencial da Open API da Shopee. A fonte Shopee da etapa 4 fica pronta e testada com mock, mas sem uso. Até lá, a Shopee se atualiza pelo `importar` do painel.
- **P2, P3, P4, P6:** valem as premissas do plano. A v1 não filtra por padrão, nada é apagado nem marcado, `--produtos 0` com só a página 1, e não há botão item a item no ML nem na Shopee.
