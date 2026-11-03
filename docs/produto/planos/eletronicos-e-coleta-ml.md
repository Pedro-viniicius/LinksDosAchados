# Plano técnico: reorganizar as abas (Eletrônicos, Eletrodomésticos, Casa e Decoração, Perfumaria) e versionar a coleta do ML
- Brief: não há. Fazem o papel dele o pedido do lead de 2026-11-03 e as respostas do dono, também de 2026-11-03 (revisão 2 deste plano).
- Data: 2026-11-03

## Objetivo e critérios de aceite
**A.** Redistribuir os itens que já estão no banco nas abas finais, sem coletar nada, e criar a categoria nova "Perfumes e Perfumaria" em `buscas.json`. **B.** Versionar a coleta do Mercado Livre em `coletar_ml.js`, seguindo o contrato atual do servidor e gravando já na categoria certa.

Abas finais, com estes nomes exatos: **"Lista WhatsApp"** (não muda), **"Black Friday | Eletrônicos"**, **"Eletrodomésticos"**, **"Casa e Decoração"** e **"Perfumes e Perfumaria"**. As categorias "Black Friday" e "Casa Nova" deixam de existir.

- CA1: depois da migração, as contagens batem com o banco de 2026-11-03, lido em modo `ro`. O total continua 5.329.

  | Aba | Amazon | ML | Total |
  |---|---|---|---|
  | Lista WhatsApp | 74 | 0 | 74 |
  | Black Friday \| Eletrônicos | 1.439 | 1.597 | 3.036 |
  | Eletrodomésticos | 554 | 549 | 1.103 |
  | Casa e Decoração | 558 | 558 | 1.116 |

- CA2: nenhum item fica com `cat` "Black Friday" ou "Casa Nova". Só `cat` e `atualizado_em` dos itens movidos mudam. `url`, `item_id`, `busca`, `posicao` e `data` ficam iguais em todos os itens. "Lista WhatsApp" não é tocada.
- CA3: `--dry-run` mostra as contagens por origem, destino, loja e termo, e não grava nada nem cria backup.
- CA4: a execução real faz backup com a API `backup` do sqlite antes de gravar. O backup passa em `integrity_check` e tem a mesma contagem do banco. Se o backup falhar, nada é migrado. No fim, o script imprime o caminho do backup e o comando para reverter. `--restaurar <arquivo>` recusa rodar com o servidor no ar e, com ele parado, devolve o banco ao estado do backup.
- CA5: o script é idempotente. A segunda execução move 0 itens e não cria backup novo. Se algum item das origens tiver `busca` sem destino no mapa, o script aborta antes de gravar e lista esses itens. Hoje não há nenhum.
- CA6: funciona com o servidor no ar (WAL). Um GET `/api/items` feito logo depois já mostra as abas novas, sem reiniciar o servidor.
- CA7: `buscas.json` é o mapa único termo → categoria. Tem as 4 chaves, nesta ordem: "Black Friday | Eletrônicos" (60), "Eletrodomésticos" (19), "Casa e Decoração" (19) e "Perfumes e Perfumaria" (28). Nenhum termo se repete, nenhum tem `|` e todo texto está em Unicode NFC. Um item novo coletado pelo `coletar_amazon.py` recebe a chave do seu termo. Um item que já existe e é coletado de novo mantém `cat` e `url`.
- CA8: o progresso do `coletar_amazon.py` passa a ser por termo. Mudar o nome de uma chave não faz coletar de novo nenhum termo já feito, e as linhas antigas `busca|<cat>|<termo>` continuam valendo. Uma categoria com `|` no nome não quebra a leitura do progresso. O arquivo de progresso pode ser trocado por `ACHADINHOS_FEITOS`.
- CA9: com `localStorage.activeCat` igual a "Black Friday", o front abre na primeira aba existente, sem erro.
- CA10: o nome "Black Friday | Eletrônicos" funciona de ponta a ponta. A aba aparece com o texto exato, o clique filtra os itens certos, o filtro de buscas e "Mover para" funcionam, e a contagem confere.
- CA11: `coletar_ml.js`, colado no console, só define `ColetaML`. `coletar()` só roda em `https://lista.mercadolivre.com.br` e `afiliar()` só em `https://www.mercadolivre.com.br`. Em outra origem, mostra uma mensagem e não faz nenhum fetch.
- CA12: o parser lê a fixture HTML e devolve itens no formato atual do banco: `item_id` `MLB…`, `url` `https://produto.mercadolivre.com.br/MLB-…`, os 10 `CAMPOS` como texto e os mesmos formatos de hoje ("R$ 124,20", "-5%", "4.8 de 5 estrelas", "Mais de 1000 produtos vendidos", "Frete grátis", imagem `D_Q_NP_2X_<id>-E.webp`). Ignora id repetido e card sem título, e devolve no máximo 30 por termo. Página sem `polycard` ou com captcha para a coleta com mensagem clara, sem enviar nada.
- CA13: cada termo grava `cat` = chave de `buscas.json` e `busca` = o termo. A lista embutida no `coletar_ml.js` é idêntica a `buscas.json`. Se divergir, o teste falha e imprime o bloco certo para colar.
- CA14: todo POST e PATCH leva `Content-Type: application/json`, `loja:'ml'`, campos de texto e `data` como objeto. O arquivo não tem DELETE. O PATCH só manda `url` que casa com `^https://meli\.la/[A-Za-z0-9]+$`; o resto vai para a lista de inelegíveis.
- CA15: contra um servidor de teste (banco temporário, porta livre, `Origin` do ML), o POST da coleta dá 200 e grava com a `cat` certa, inclusive "Black Friday | Eletrônicos". Reenviar não duplica, não troca `cat` e não troca um `meli.la` já gravado.
- CA16: `afiliar()` mapeia a resposta do `createLink` pelo código MLB, não pela ordem. Isso vale também para `origin_url` canônica (`…-_JM`) e para resposta embaralhada. Item com `error_code` vai para a lista de inelegíveis (id, MLB e motivo), sem DELETE. A conferência repete até dar 0 correções e aponta `url` repetida entre itens do ML.
- CA17: o progresso fica por termo e por servidor no `localStorage`, e `ColetaML.parar()` interrompe. Com `enviar:false`, nenhuma chamada vai ao servidor, e o resultado traz os itens montados.
- CA18: o `README.md` explica a migração (dry-run, execução real e como reverter), como carregar e rodar o `coletar_ml.js`, e a primeira coleta de perfumaria.
- CA19: depois da etapa 9 (do dono), a aba "Perfumes e Perfumaria" existe, tem itens da Amazon e do ML, e `GET /api/ml-sem-afiliado` devolve `[]`.

## Contexto atual
- `buscas.json` tem "Black Friday" com 59 termos, todos de eletrônicos ou informática, e "Casa Nova" com 39. Nenhum termo se repete entre as chaves.
- No banco, "Black Friday" tem 60 valores de `busca`: os 59 termos mais "Caixa inteligente assistente virtual", que só existe no ML (21 itens). Em compensação, o ML não tem "Smart speaker Alexa". Por que o termo mudou: **não verificado**. Nenhum item está fora da categoria do seu termo, ou seja, não houve "Mover para" manual. Nenhuma `cat` tem `|` hoje.
- `upsert` grava `cat` só no INSERT (`servidor.py:147-150`). No UPDATE, não mexe em `cat` e preserva a `url` de afiliado (`servidor.py:157-163`). Por isso, coletar de novo **não** devolve o item à aba antiga.
- `conectar()` usa WAL com `timeout=30` (`servidor.py:33-37`). `DB` e `PORT` vêm do ambiente (`servidor.py:14-15`). O servidor não valida o conteúdo de `cat`: com `|` passa como texto (`servidor.py:130`, `407-408`).
- **Armadilha do `|` e da renomeação no `coletar_amazon.py`:**
  - A chave de progresso é `busca|{cat}|{termo}` (`coletar_amazon.py:100`) e é comparada inteira com as linhas do arquivo (`:83`, `:101`). Hoje há 59 linhas `busca|Black Friday|…` e 39 `busca|Casa Nova|…`.
  - Com a `cat` nova, a chave vira `busca|Black Friday | Eletrônicos|iPhone 17`. Ela não casa com nenhuma linha antiga, e por isso **os 98 termos seriam coletados de novo na Amazon**.
  - Qualquer leitura que separe a chave por `|` também passa a errar.
  - O caminho `FEITOS` é fixo em `BASE` (`:12`). Uma coleta de teste contra uma cópia do banco marcaria os termos como feitos para a coleta real.
- **Front:**
  - `cats()` deriva as abas dos itens, na ordem de `posicao` (`index.html:220`).
  - `esc` escapa `& < > "` (`index.html:211`). A aba usa `data-c="${esc(c)}"` e `t.dataset.c` (`:387-388`), e por isso `|`, espaço e acento chegam intactos.
  - "Mover para" usa `<option>` sem `value` (`:361`). O valor de um option assim é o texto, com espaços aparados e espaços seguidos reduzidos a um. "Black Friday | Eletrônicos" tem espaços simples e nada nas pontas, então chega igual. Mesmo assim, o CA10 cobre esse caso.
  - `render()` já troca um `activeCat` inexistente pela primeira aba (`:385-386`).
  - Ordem das abas depois da migração, pela menor `posicao` de cada uma: Lista WhatsApp (1), Black Friday | Eletrônicos (69), Eletrodomésticos (2503), Casa e Decoração (2799). Perfumes entra no fim, quando for coletada.
- **Risco de normalização:** "Eletrônicos" e "Decoração" têm acento. Se um arquivo trouxer o acento decomposto (NFD) e outro composto (NFC), surgem duas abas visualmente iguais. Por isso o CA7 exige NFC.
- **Servidor:** só serve `/`, `/index.html` e `/testes/*.test.html` (`servidor.py:28-29`). O script antigo do ML lia `http://localhost:8765/buscas.json`, que hoje dá 404. As origens do ML podem usar GET, POST e PATCH em `/api/items`, `/api/items/<id>` e `/api/ml-sem-afiliado` (`servidor.py:24-26`, `278-284`). DELETE dá 403. O PATCH de `url` exige link de afiliado (`servidor.py:413-415`).
- **O script antigo do ML existe numa transcrição de sessão anterior.** Ela tem dado pessoal do dono: não abra nem copie. O que importa está resumido aqui:
  - **Coleta.** O slug é o termo sem acento, em minúsculas, com cada trecho não alfanumérico trocado por `-`. A página vem de `fetch('/'+slug,{credentials:'include'})`, e há captcha quando `r.url` casa com `/captcha|account-verification|gz\//`. Os dados ficam num `<script>` que contém `.q("` e `polycard`. O literal JS depois de `.q(` passa por duas trocas (`\'` vira `'` e `\xNN` vira `\u00NN`) e por `JSON.parse`, que devolve uma string. Dentro dela, cada `"polycard"` é seguido de um objeto `{…}`, extraído com balanceamento de chaves que respeita aspas e depois lido com `JSON.parse`.
  - **Campos do polycard.**
    - `metadata.id` traz o MLB. `metadata.url` às vezes é `click1…` (anúncio) e não serve.
    - `pictures.pictures[0].id` dá o id da foto.
    - `components[]` vem indexado por `type`:
      - `title.text`;
      - `price.current_price.value`, e o primeiro objeto dentro de `price` com `previous:true` e `value`;
      - `review_compacted.alt_text`, no formato "Classificação 4.2 de 5 estrelas. Mais de 25 produtos vendidos.";
      - "grátis" dentro de `shipping_v2` ou `shipping`.
  - **Envio.**
    - Preço: "R$ " + `toLocaleString('pt-BR')`, com 2 decimais só quando o valor não é inteiro.
    - Desconto: `-round(100-atual*100/anterior)%`.
    - `url`: `https://produto.mercadolivre.com.br/MLB-<n>`.
    - Lote: 30 por termo, com pausa de 2,5 a 5 s.
  - **Linkbuilder.**
    - Passos na interface: clica no label /Links curtos/, preenche o `textarea[0]` com o setter nativo mais o evento `input` e clica no botão "Gerar".
    - Captura: um hook em `fetch` e em XHR guarda a resposta das URLs com `createLink`, no formato `{urls:[{origin_url, short_url, error_code, message, created}]}`.
    - Tamanho do lote: 25, porque 50 falha. Na repescagem foram usados 10.
    - Mapeamento: por `/MLB-?(\d{6,})/` em `origin_url`.
  - **O que mudou desde então:** antes, o item inelegível era apagado com DELETE. Hoje isso dá 403.
- **Testes:** `testes/test_servidor.py` usa unittest com o servidor em subprocesso, banco e porta temporários (`:45-85`). `testes/rodar.mjs` aceita `PORTA`. O node instalado é o v22.23.0, que tem `node:test` e `node:vm`. Não existe `docs/produto/decisoes.md`.

## Abordagens consideradas
| Tema | Opção | Prós | Contras | Escolha |
|---|---|---|---|---|
| Migração | Script com UPDATE numa transação | Backup, dry-run, atômico, idempotente | Mais um arquivo | **sim** |
| Migração | ~4.200 PATCH `cat` pela API | Usa rota existente | Sem transação nem backup; para no meio | não |
| Mapa termo → categoria | `buscas.json` é a fonte; o script lê o arquivo; o JS tem uma cópia conferida por teste | Uma fonte; o servidor não muda | Cópia no JS (o teste pega divergência) | **sim** |
| Mapa termo → categoria | Rota nova `GET /api/buscas` para o ML | Sem cópia | Muda a allowlist do servidor (sensível) | não |
| Mapa termo → categoria | Gerador que reescreve o bloco do JS | Sem cópia manual | Mais código para 1 bloco | não: o teste já imprime o bloco certo |
| `cat` com `|` | Progresso só por termo, lendo o último segmento das linhas antigas | Imune a qualquer nome de aba | Muda 2 linhas do coletor | **sim** |
| `cat` com `|` | Trocar o separador ou escapar `|` | — | Continua dependendo do nome da aba | não |

## Decisão
1. **Mapa único.** `buscas.json` é o mapa termo → categoria. O script de migração e o `coletar_amazon.py` leem o arquivo. O `coletar_ml.js` traz uma cópia literal, e um teste compara as duas e imprime o bloco certo se divergirem. O alias do ML fica como constante no script, `ALIAS = {'Caixa inteligente assistente virtual': 'Smart speaker Alexa'}`, e herda a categoria do termo a que aponta. Não entra em `buscas.json`, para a Amazon não passar a coletar esse termo.
2. **Termos de cada aba**, conferidos termo a termo contra `buscas.json`:
   - **Black Friday | Eletrônicos (60):** os 59 de "Black Friday", na ordem atual, mais "Smart TV".
   - **Eletrodomésticos (19):** Geladeira, Máquina de lavar, Lava e seca, Fogão, Cooktop, Air fryer, Micro-ondas, Ar-condicionado, Aspirador de pó, Robô aspirador, Cafeteira, Liquidificador, Mixer, Purificador de água, Ventilador, Sanduicheira grill, Lava-louças, Ferro de passar, Vaporizador de roupas.
   - **Casa e Decoração (19):** Jogo de panelas, Cama box, Colchão, Sofá, Guarda-roupa, Armário de cozinha, Mesa de jantar com cadeiras, Aparelho de jantar, Jogo de talheres, Potes herméticos, Jogo de cama, Jogo de toalhas, Travesseiro, Edredom, Cortina, Persiana, Tapete, Organizador de cozinha, Organizador de guarda-roupa.
   - **Perfumes e Perfumaria (28):** Perfume masculino importado, Perfume feminino importado, Perfume masculino nacional, Perfume feminino nacional, Kit perfume, Miniatura de perfume, Body splash, Desodorante colônia, Hidratante corporal perfumado, Perfume árabe, Perfume infantil, Perfume Natura, Natura Kaiak, Natura Essencial, Perfume O Boticário, Malbec O Boticário, Egeo O Boticário, Perfume Eudora, Carolina Herrera 212 VIP, Carolina Herrera Good Girl, Paco Rabanne One Million, Paco Rabanne Invictus, Dior Sauvage, Lancôme La Vie Est Belle, Calvin Klein CK One, Jean Paul Gaultier Le Male, Azzaro Pour Homme, Lattafa.
3. **Script `migrar_categorias.py`** (o nome antigo não cabe mais: são 3 destinos).
   - Usa `DB`, `conectar()` e `agora()` do `servidor`.
   - As origens são `('Black Friday','Casa Nova')`. O destino de cada item é `mapa[ALIAS.get(busca, busca)]`.
   - Faz um `UPDATE … SET cat=?` por destino, todos dentro de um só `BEGIN IMMEDIATE`, com parâmetros. Aborta se algum item das origens ficar sem destino.
   - O backup vai para `<pasta do DB>/backups/achadinhos-AAAAMMDD-HHMMSS.db`, que o `.gitignore` já cobre com `*.db`.
   - O `--restaurar` é pequeno, mas é o único caminho de volta testado.
   - É genérico o bastante para a próxima reorganização: basta trocar as origens.
4. **Progresso do `coletar_amazon.py` por termo.**
   - A chave nova é `busca|{termo}`. `feitos()` reescreve cada linha `busca|…` como `busca|` + o último segmento depois do último `|`, o que funciona para as linhas antigas, para as novas e para qualquer nome de aba. Os termos não têm `|`, e o CA7 garante isso.
   - As linhas `whatsapp|…` ficam como estão.
   - `FEITOS` passa a aceitar `ACHADINHOS_FEITOS`, para a coleta de teste não marcar termos da coleta real.
   - Efeito: depois da migração, `coletar_amazon.py buscas` só coleta os 28 termos de perfumaria.
5. **`coletar_ml.js`:** um arquivo só, com `globalThis.ColetaML` e duas entradas, `coletar()` e `afiliar()`. As funções que não dependem da página são testadas no node com `vm`. O `fetch` real do ML e a operação da interface do linkbuilder só são provados na etapa 9. O dono carrega o arquivo copiando e colando no console do DevTools; na primeira vez, o Chrome pede "allow pasting". Outra opção é Sources > Snippets.

## Esquema e contratos
Sem mudança de esquema, de servidor ou de front.

- `python3 migrar_categorias.py [--dry-run | --restaurar ARQUIVO]` → código de saída 0 quando dá certo, 1 quando dá erro. O banco vem de `ACHADINHOS_DB`.
- `coletar_amazon.py`: mesma linha de comando de hoje. `ACHADINHOS_FEITOS` é opcional.
- API do `coletar_ml.js`, sem nenhum efeito ao carregar:
```
ColetaML.BUSCAS                                   // cópia literal de buscas.json, entre os marcadores // BUSCAS:inicio e // BUSCAS:fim
ColetaML.coletar({termos?, servidor='http://localhost:8765', enviar=true, porBusca=30, fetch?, armazenamento?}) → Promise<estado>
ColetaML.afiliar({servidor, lote=25, enviar=true, fetch?, armazenamento?}) → Promise<estado>
ColetaML.parar(); ColetaML.estado; ColetaML.zerar(servidor)
// puras: slug(termo), categoriaDe(termo), literalQ(html), extrairItens(html, termo, cat, max), polycardParaItem(pc),
//        idMLB(url), mapearLinks(resp, itens) → {trocar, inelegiveis, semResposta}, urlsRepetidas(itensML), ehLinkMeliLa(url)
```
- **Chamadas ao servidor:** sempre com `credentials:'omit'` e `Content-Type: application/json`.
- **Progresso:** `localStorage['__coletaML:'+servidor]`, que guarda um array de termos.
- **`afiliar()`:**
  1. Repete enquanto houver pendentes: GET `ml-sem-afiliado`, gera links em lotes, aplica `mapearLinks` e faz PATCH.
  2. Confere os ids tocados na sessão até dar 0 correções.
  3. Faz GET `/api/items` e roda `urlsRepetidas`.
  4. Imprime os inelegíveis para o dono excluir pelo site.

## Etapas
| # | Etapa | Arquivos | Verificação | Responsável | Grupo | Sensível | CAs |
|---|---|---|---|---|---|---|---|
| 1 | Reescrever `buscas.json` com as 4 chaves e os termos da Decisão 2, em UTF-8 e NFC | `buscas.json` | `python3 -c "import json,unicodedata as u;b=json.load(open('buscas.json'));assert list(b)==['Black Friday \| Eletrônicos','Eletrodomésticos','Casa e Decoração','Perfumes e Perfumaria'];assert [len(v) for v in b.values()]==[60,19,19,28];t=[x for v in b.values() for x in v];assert len(t)==len(set(t)) and not any('\|' in x for x in t);assert all(u.is_normalized('NFC',x) for x in t+list(b))"` (no shell, `\|` é só o `|` da tabela) | dev | A | não | CA7 |
| 2 | `migrar_categorias.py` com mapa vindo de `buscas.json` mais `ALIAS`, `--dry-run`, backup verificado, transação única, aborto quando falta destino, idempotência e `--restaurar` (recusa se a porta `S.PORT` responde). Testes em subprocesso com banco temporário semeado e guarda contra o banco real, cobrindo: dry-run sem efeito; os 3 destinos exatos, com as outras colunas intactas e "Lista WhatsApp" sem mudança; item sem destino aborta sem gravar; backup íntegro; segunda execução com 0 e sem backup; migração com o `servidor.py` no ar e GET logo depois; `--restaurar` recusado com o servidor no ar e funcionando com ele parado | `migrar_categorias.py`, `testes/test_migrar_categorias.py` | `python3 -m py_compile migrar_categorias.py && python3 testes/test_migrar_categorias.py -v` | dev (opus) | B | **sim** | CA1–CA6 |
| 3 | `coletar_amazon.py`: chave `busca|{termo}`, `feitos()` normalizando pelo último segmento e `ACHADINHOS_FEITOS`. Testes: as linhas antigas `busca|Black Friday|X` e `busca|Casa Nova|Y` contam como feitas; uma linha com `|` na `cat` também conta; `coletar_buscas()` com `baixar`, `parse_busca` e `pausa` falsos, `ACHADINHOS_DB` e `ACHADINHOS_FEITOS` temporários, grava cada termo (inclusive de perfumaria) com a chave exata do JSON e só coleta os termos que faltam; item existente mantém `cat` e `url` | `coletar_amazon.py`, `testes/test_coletar_amazon.py` | `python3 testes/test_coletar_amazon.py -v && python3 testes/test_servidor.py -v` (continua 53 OK) | dev | B | não | CA7, CA8 |
| 4 | `coletar_ml.js`: guarda de origem, `BUSCAS` entre marcadores, funções puras da coleta, `coletar()` com `enviar:false`, progresso e `parar()`. Fixture com 3 polycards válidos, 1 repetido, 1 sem título, um com `click1`, os escapes `\'` e `\x3C`, preço inteiro e decimal e frete em `shipping_v2`. `node:test`: parser; `BUSCAS` igual a `buscas.json`, imprimindo o bloco certo quando falha; contrato do envio com fetch falso; integração subindo o `servidor.py` com banco temporário e porta livre. O `fetch` do servidor é feito por um adaptador `node:http` que manda `Origin: https://lista.mercadolivre.com.br`, e um termo de "Black Friday \| Eletrônicos" tem que gravar com essa `cat` exata | `coletar_ml.js`, `testes/coletar_ml.test.mjs`, `testes/fixtures/ml-busca.html` | `node --test testes/coletar_ml.test.mjs` | dev (opus) | B | **sim** | CA11–CA15, CA17 |
| 5 | `afiliar()` em `coletar_ml.js`: hook do `createLink`, operação da interface isolada em `gerarNaPagina(urls)`, `mapearLinks`, `ehLinkMeliLa`, segunda passada, `urlsRepetidas` e lista de inelegíveis. Testes com a resposta embaralhada, uma `origin_url` `-_JM`, um `error_code` e um `short_url` que não é `meli.la`. Integração: PATCH aceito com a `Origin` do www e `url` comum nunca enviada | `coletar_ml.js`, `testes/coletar_ml.test.mjs`, `testes/fixtures/ml-createlink.json` | `node --test testes/coletar_ml.test.mjs` | dev (opus) | C | **sim** | CA11, CA14, CA16, CA17 |
| 6 | README com três seções e um one-liner de backup com `sqlite3.backup`: "Reorganizar abas" (dry-run, execução real e reverter), "Coleta do ML" (carregar o arquivo, as duas abas, inelegíveis, "cole só o arquivo do projeto") e "Primeira coleta de perfumaria" | `README.md` | Leitura pelo `revisor`; os comandos citados existem | dev | D | não | CA18 |
| 7 | Provar o CA9 e o CA10 numa página de teste. Ela grava `activeCat='Black Friday'` e carrega `/index.html` num iframe sobre a cópia migrada. Verifica que a aba ativa é a primeira de `cats()`; que existe um botão com o texto exato "Black Friday \| Eletrônicos" e que o clique nele lista só itens com essa `cat`, com a contagem certa; que o `<option>` de "Mover para" tem `value` igual ao nome. A página só faz GET | `testes/abas.test.html` | `PORTA=8766 node testes/rodar.mjs abas` | qa | verificação | não | CA9, CA10 |
| 8 | Migração real: rodar `python3 migrar_categorias.py --dry-run`, comparar com o CA1, rodar sem flag com o servidor no ar e recarregar a página | `achadinhos.db` (dado) | Abas e contagens do CA1 | dono (ou o lead com aprovação explícita) | depois de tudo aprovado | **sim** | CA1–CA6 |
| 9 | Primeira coleta de perfumaria, seguindo o protocolo abaixo | `achadinhos.db` (dado) | CA19 | dono | depois da 8 | **sim** | CA12, CA15, CA16, CA19 |

O lead atualiza o `CLAUDE.md` depois da aprovação. Em "Camadas e pastas", entram `coletar_ml.js` e `migrar_categorias.py` e sai "não há arquivo para ela". Em "Verificação", entram os três comandos novos.

**Como o `qa` prova sem tocar no banco real.** Faça a cópia com `python3 -c "import sqlite3;s=sqlite3.connect('file:achadinhos.db?mode=ro',uri=True);d=sqlite3.connect('<scratchpad>/copia.db');s.backup(d);d.close()"`. Depois:
1. Rode `ACHADINHOS_DB=<copia> python3 migrar_categorias.py --dry-run` e confira o CA1.
2. Suba `ACHADINHOS_DB=<copia> ACHADINHOS_PORTA=8766 python3 servidor.py`.
3. Rode a migração real na cópia com esse servidor no ar, que prova o CA6, e confira por GET em `localhost:8766`.
4. Rode de novo para o CA5, faça a etapa 7 e use `--restaurar` com o servidor parado.

Do CA11 ao CA17, as provas são as das etapas 4 e 5.

**Protocolo da etapa 9.** Faça um backup com o one-liner do README antes de começar.
1. **Amazon, primeiro numa cópia.** Copie o progresso real antes (`cp coleta_amazon_feitos.txt <scratch>/feitos-teste.txt`), senão a coleta começa pelos termos de eletrônicos, que já estão feitos. Depois rode `ACHADINHOS_DB=<copia> ACHADINHOS_FEITOS=<scratch>/feitos-teste.txt python3 coletar_amazon.py buscas`. Depois da migração, só os 28 termos de perfumaria faltam. Interrompa com Ctrl+C depois de 2 ou 3 termos: cada termo é gravado e marcado assim que termina. Confira a aba em `localhost:8766`.
2. **Amazon no banco real.** Rode `python3 coletar_amazon.py buscas`. Use `buscas`, e não `tudo`, para não passar pelo WhatsApp. Faça a mesma parada depois dos primeiros termos, confira e rode de novo para continuar.
3. **ML.**
   1. Na aba `lista.mercadolivre.com.br`, cole o arquivo e rode `await ColetaML.coletar({termos:['Perfume Natura','Body splash'], enviar:false})`. Compare 3 itens com a página: título, preço e foto.
   2. Repita com `servidor:'http://localhost:8766'`.
   3. Na aba do linkbuilder, rode `await ColetaML.afiliar({servidor:'http://localhost:8766'})` e abra 2 links `meli.la` para conferir o MLB.
   4. Só depois rode contra 8765: primeiro com esses 2 termos, depois com todos os da chave. Termine com `afiliar()` e confira o CA19.

Gerar links de verdade também os adiciona a "Minhas recomendações" da conta, e isso é aceitável.

## Pontos para o seguranca
- **Etapa 2:**
  - A guarda contra o banco real nos testes, como em `testes/test_servidor.py:45-52`.
  - O SQL só com parâmetros.
  - O backup é verificado antes do UPDATE, e uma falha aborta a migração.
  - O `--restaurar` recusa rodar com o servidor no ar.
  - O backup contém o banco inteiro, que só tem produtos, e fica fora do git.
- **Etapa 3:** `ACHADINHOS_FEITOS` só troca o caminho de um arquivo de texto de progresso.
- **Etapas 4 e 5:**
  - O arquivo não tem DELETE.
  - O PATCH só leva `meli.la`, e o servidor também valida (`servidor.py:413-415`).
  - As chamadas ao servidor usam `credentials:'omit'`.
  - O conteúdo do ML é tratado como dado não confiável: só `JSON.parse`, sem `eval`, `innerHTML` nem `Function`, e os valores vão como texto.
  - O hook de `fetch` e XHR só lê respostas com `createLink`.
  - O script não lê cookies nem tokens e não envia nada além dos campos do item.
- **Colar no console de uma conta logada é self-XSS por natureza.** O README tem que dizer "cole só o `coletar_ml.js` do projeto".

## Riscos e como reverter
- **Migração errada:** `python3 migrar_categorias.py --restaurar backups/<arquivo>.db` com o servidor parado. Escritas feitas depois do backup se perdem. Para um ajuste pontual, use "Mover para".
- **`buscas.json` ou `coletar_amazon.py`:** `git revert`. A normalização pelo último segmento lê qualquer formato de linha.
- **Perfumaria com item ruim** (contratipo, réplica, "inspirado em"): exclua pelo site, ou restaure o backup feito antes da etapa 9. Veja P1.
- **O ML mudou a estrutura:** a coleta para sem POST, com "sem polycard". Ajuste o parser e a fixture.
- **O linkbuilder falha no meio:** os itens novos ficam com link comum até o próximo `afiliar()`. Não use a aba enquanto `ml-sem-afiliado` for maior que 0.
- **Front aberto e desatualizado** pode mover um item de volta para uma `cat` antiga por "Mover para". Recarregue a página depois da migração.

## Perguntas em aberto e premissas adotadas
- **P1 (dono): filtrar contratipos na perfumaria?** No ML e na Amazon há muito "contratipo", "inspirado em" e "decant". Divulgar isso pode ser ruim para o grupo e pode ferir a política de afiliados. Recomendo **não filtrar agora**: o dono revê na primeira rodada (etapa 9) e exclui pelo site. Se aparecer muito, o próximo passo é um filtro de título nos dois coletores, numa mudança separada.
- **P2 (dono): os 28 termos de perfumaria servem?** A lista está na Decisão 2. Ela pode ser editada em `buscas.json` antes da etapa 9 sem mexer em código; basta manter o teste do CA13 passando.
- **Premissas mantidas:**
  - O alias do ML vai para "Black Friday | Eletrônicos".
  - Os inelegíveis do linkbuilder são excluídos pelo site.
  - Coleta e linkbuilder ficam num arquivo, com duas funções.
- **Não verificado:** se o `fetch` do Node manda `Origin`. Por isso o teste usa `node:http`.
- **Escopo:** são duas entregas que podem ir separadas. A Parte A (etapas 1–3, 7, 8) pode ir antes da Parte B (4–6, 9). A Parte B só depende da etapa 1.

## ADR
**ADR 1: `buscas.json` é o mapa termo → categoria, e o progresso é por termo.** A migração, a Amazon e o ML usam o mesmo mapa. O JS tem uma cópia conferida por teste. O progresso não depende do nome da aba, para que renomear uma aba (inclusive com `|`) não dispare uma nova coleta. Trade-off: um termo não pode estar em duas abas, e hoje nenhum está.

**ADR 2: mudança de dado por script versionado.** O script tem dry-run, backup com a API `backup` do sqlite, verificação do backup, uma transação, idempotência, aborto quando falta destino e `--restaurar` testado. Fica como padrão para futuras reorganizações, no lugar de edição à mão ou de PATCH em massa.

**ADR 3: script de console versionado.** `coletar_ml.js` expõe `globalThis.ColetaML` e não tem efeito ao carregar. As funções puras são testadas com `node --test` e `node:vm`, sem dependência. O que depende do ML real só é provado na execução do dono, com protocolo de cópia e servidor de teste.
