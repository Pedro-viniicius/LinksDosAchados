# API de ofertas v1 (Etiqueta para o Achadinho Turbo)

- Plano: `docs/produto/planos/api-achadinho-turbo.md`. Código: `api_ofertas.py` (regra das ofertas) e `servidor.py` (token, guarda HTTP e log).
- Estado descrito aqui: o código final da etapa 2, conferido em 2026-11-03, mais o público (`genero`) da etapa 5 do plano `docs/produto/planos/genero-nas-categorias.md` (código do público em `genero.py`). Os campos, parâmetros e erros que já existiam não mudaram e a `versao` continua 1.
- Atualizado em 2026-11-04 (plano `docs/produto/planos/abas-nichadas-e-coleta.md`): as abas passam a ser 17 e 3 delas têm público. **Só os nomes de `categoria` e as abas com `generos` mudam; nenhum campo, parâmetro ou erro é novo.** Veja "Abas" e a nota de renomeação.
- Atualizado em 2026-11-04 (plano `docs/produto/planos/atualizar-precos.md`, etapa 3): cada oferta ganha o campo `preco_em` (quando o preço foi confirmado) e há o parâmetro opcional `preco_max_horas`. A `versao` continua 1. Veja "Idade do preço".
- **Mudança de comportamento em 2026-11-08 (decisão do dono):** sem `preco_max_horas`, a API passa a trazer só ofertas com preço dentro da validade configurada no Etiqueta (`config.preco_validade_horas`, padrão 24 h), a mesma trava do disparo. Antes, sem o parâmetro, saía também oferta de preço velho. `/api/v1/categorias` não mudou. Nenhum campo, parâmetro ou erro é novo. Veja "Idade do preço".
- **Mudança em 2026-11-11 (plano "Rodar sozinho · Entrega 1" do Achadinho Turbo, `docs/produto/planos/rodar-sozinho-entrega1.md` no repositório dele): a v1 passa a ter uma rota que grava**, `POST /api/v1/amazon/<ASIN>/confirmar-preco`. Ela relê a página de **uma** oferta da Amazon que já está no banco e grava só o preço. As duas rotas `GET` não mudaram e a `versao` continua 1. Veja "`POST /api/v1/amazon/<ASIN>/confirmar-preco`".
- Resumo: duas rotas só de leitura, `GET /api/v1/ofertas` e `GET /api/v1/categorias`, e uma que relê e grava o preço de uma oferta da Amazon, `POST /api/v1/amazon/<ASIN>/confirmar-preco`, em `http://127.0.0.1:8765` (ou na porta de `ACHADINHOS_PORTA`). Toda oferta sai com **link de afiliado da própria loja**, como está no banco. O consumidor é um processo no mesmo computador (o Achadinho Turbo, em Node), não um navegador.

## Como usar em 1 minuto

```
python3 -c "import secrets; print(secrets.token_urlsafe(32))" > api_token.txt; chmod 600 api_token.txt
# reinicie o servidor.py
{ printf 'Authorization: Bearer '; cat api_token.txt; } > api_cabecalho.txt; chmod 600 api_cabecalho.txt
curl -s -H @api_cabecalho.txt "http://localhost:8765/api/v1/categorias"
```

O `curl` lê o cabeçalho de um arquivo (`-H @arquivo`, curl 7.55 ou mais novo) em vez de receber o token na linha de comando: um `$(cat api_token.txt)` na linha aparece para qualquer usuário no `ps` e no histórico do shell. **O `api_cabecalho.txt` também é segredo** (tem o token): permissão 600, nunca versionar (confira se está no `.gitignore`; se faltar, acrescente) e apague quando não precisar mais. Se trocar o token, gere o arquivo de cabeçalho de novo.

Sem `api_token.txt` (ou com token inválido) a v1 fica desligada e responde 503 (o motivo aparece no terminal do servidor); o resto do Etiqueta funciona normalmente.

## Token

- **Onde:** arquivo `api_token.txt` ao lado do `servidor.py`. `ACHADINHOS_API_TOKEN_ARQUIVO` troca o caminho. O arquivo está no `.gitignore`: nunca vai para o git.
- **Formato:** 32 ou mais caracteres de `A-Z`, `a-z`, `0-9`, `_` e `-`, só ASCII. Os espaços e a quebra de linha das pontas são ignorados. O arquivo precisa ser um arquivo comum (não pasta, nem FIFO) e ter no máximo 4096 bytes.
- **Gerar:** `python3 -c "import secrets; print(secrets.token_urlsafe(32))" > api_token.txt; chmod 600 api_token.txt` (43 caracteres). Qualquer outro gerador serve, desde que respeite o formato.
- **Permissão:** o servidor **não recusa** um arquivo legível por outros usuários, só avisa no terminal ("o arquivo do token pode ser lido por outros usuários"). Use `chmod 600`.
- **Leitura única:** o servidor lê o arquivo uma vez, na subida. Para **trocar** o token, troque o arquivo e **reinicie o `servidor.py`**; depois atualize o valor no consumidor.
- **Para desligar** a API: apague o arquivo e reinicie. A v1 passa a dar 503.
- **Onde vai o token:** só no cabeçalho `Authorization: Bearer <token>` (o esquema `Bearer` vale sem diferenciar maiúsculas). **`?token=` na URL não autentica.** Mais de um cabeçalho `Authorization` dá 401. A comparação é em tempo constante (`hmac.compare_digest`).
- **Nunca** cole o token em conversa de chat, issue, commit, print ou log. O servidor também não o grava: o log de acesso da v1 mostra só o método, a rota e `?(omitida)` no lugar da query, e a mensagem de subida traz só o caminho do arquivo. A rota de confirmação de preço aparece no log sem o ASIN: `POST /api/v1/amazon/(asin)/confirmar-preco`.
- Se o token vazar, gere outro, troque o arquivo, reinicie e atualize o consumidor.

## Guardas, na ordem em que valem

| # | Condição | Resposta |
|---|---|---|
| 1 | `Host` diferente de `localhost:<porta>` ou `127.0.0.1:<porta>` | 403 `host não permitido` |
| 2 | Cabeçalho `Origin` (mesmo a do próprio Etiqueta) ou `Sec-Fetch-Site` presente, que é o que um navegador manda | 403 `a API v1 não aceita pedidos de navegador` |
| 3 | Sem token válido carregado (API desligada) | 503 `a API v1 está desligada: veja o motivo no log do servidor` |
| 4 | Sem `Authorization: Bearer <token>` certo | 401 `token ausente ou inválido: envie Authorization: Bearer <token>`, com `WWW-Authenticate: Bearer` |
| 5 | Método diferente de GET (inclui HEAD e OPTIONS); na rota de confirmação de preço, método diferente de POST | 405 `método não permitido: a API só aceita GET`, com `Allow: GET`; na rota de confirmação, 405 `método não permitido: esta rota só aceita POST`, com `Allow: POST` |
| 6 | Rota que não é `ofertas`, `categorias` nem `amazon/<ASIN>/confirmar-preco` (inclui ASIN fora do formato) | 404 `rota não encontrada` |
| 7 | Parâmetro inválido | 400 (veja "Erros") |

- **Sem CORS:** nenhuma resposta da v1 leva `Access-Control-Allow-*` e `OPTIONS` não é liberado (dá 401 ou 405, como qualquer método não aceito). Uma página aberta no navegador não lê a v1, nem com o token.
- A rota de confirmação de preço tem guardas próprias depois destas (corpo, item e freio): veja a seção dela.
- O 405 só aparece depois da autenticação: quem não tem o token vê 401 (ou 503), nunca 405.
- O `fetch` do Node 22 e o `curl` não mandam `Origin` nem `Sec-Fetch-Site`, então passam. Um navegador sempre manda um deles, então é barrado.
- O servidor só escuta em `127.0.0.1`. Esta API **não** foi pensada para a internet (veja "Limites").

## Resposta e formato

- `Content-Type: application/json; charset=utf-8`, com acentos em UTF-8. `Cache-Control: no-store`.
- Toda resposta de sucesso traz `"versao": 1`. Erro é sempre `{"error": "<frase em português>"}`, salvo o 429 do freio da confirmação de preço, que traz `versao`, `resultado`, `motivo` e `tentar_em_s`.
- Mudança incompatível exige `/api/v2/`. **Campo novo pode entrar na v1:** o consumidor deve ignorar campo que não conhece.
- **Texto cru:** `titulo`, `busca`, `categoria` e `cupom` saem como foram coletados, sem escape. O consumidor precisa escapar antes de pôr esses campos em HTML (ou em qualquer formato com caracteres especiais).
- Horários (`criado_em`, `atualizado_em`, `preco_em`) são texto ISO **local do computador, sem fuso**, com precisão de segundo (`2026-11-03T12:24:23`). Trate como texto.
- Medido em 2026-11-03 com 8.380 itens: cada pedido leva cerca de meio segundo e uma página de 200 ofertas tem cerca de 120 KB. A v1 lê o banco inteiro a cada pedido, então **numa varredura completa use `limite=200`** (o máximo: menos pedidos) e **não faça pedidos em paralelo**.
- **No Node 22, leia o corpo de cada `fetch` logo que ele responder (`await r.json()` antes do próximo pedido) e não dispare pedidos em paralelo.** Com respostas acima de cerca de 64 KB (uma página de 200 ofertas passa disso), o undici do Node 22 pode derrubar o processo com `uncaughtException` (`assert(!this.paused)`) quando um corpo fica parado sem leitura enquanto outro pedido corre. Um pedido por vez, com o corpo lido inteiro, evita o problema.

## Abas

São 17 abas. Os valores de `categoria` (e do filtro `cat`) são estes, **exatamente assim**, na ordem do `buscas.json` e da barra do site (a API lista as categorias em ordem alfabética, não nesta):

1. `Celulares e Informática`
2. `Áudio e Acessórios`
3. `TV, Alexa e Casa Conectada`
4. `Games`
5. `Eletroportáteis`
6. `Eletrodomésticos e Climatização`
7. `Cozinha`
8. `Cama, Mesa e Banho`
9. `Casa, Móveis e Ferramentas`
10. `Beleza e Cuidados`
11. `Perfumes e Perfumaria`
12. `Mercado e Limpeza`
13. `Pets`
14. `Bebês e Brinquedos`
15. `Suplementos e Fitness`
16. `Moda e Viagem`
17. `Natal e Papelaria`

**Têm público (`genero`) 3 abas:** `Perfumes e Perfumaria`, `Beleza e Cuidados` e `Moda e Viagem` (`genero.ABAS_COM_GENERO`). Nelas, `generos` em `/categorias` traz a contagem por público; nas outras 14, tudo em `sem`. Aba nova ou renomeada: a lista pode mudar, então leia `/api/v1/categorias` em vez de fixar os nomes no consumidor. Os 17 nomes cabem no limite de 20 `cat` por pedido.

**Nota de renomeação (2026-11-04).** As abas antigas deixaram de existir. Os itens foram redistribuídos pelo termo de busca, com `migrar_categorias.py`, e quem filtrava por um nome antigo passa a receber 0 ofertas (sem erro: o valor é só texto):

| Aba antiga (`categoria`) | Foi para |
|---|---|
| `Black Friday \| Eletrônicos` | `Celulares e Informática`, `Áudio e Acessórios`, `TV, Alexa e Casa Conectada`, `Games` |
| `Eletrodomésticos` | `Eletroportáteis`, `Eletrodomésticos e Climatização` |
| `Casa e Decoração` | `Cozinha`, `Cama, Mesa e Banho`, `Casa, Móveis e Ferramentas` |

`Perfumes e Perfumaria` não mudou (mesmos itens). **A migração regrava o `atualizado_em`** dos itens que trocaram de aba (e dos que perderam um preço antigo implausível, de 5× o preço ou mais): na ordem `atualizacao` eles reaparecem depois do cursor, e a `chave` evita repetir o envio. Quem guardou um `cursor` não precisa recomeçar do zero.

## `GET /api/v1/ofertas`

Parâmetros (todos opcionais). **A validação é estrita:** parâmetro desconhecido, parâmetro repetido onde não pode, valor vazio onde não pode e valor fora da faixa dão 400. Nenhuma mensagem de erro devolve o valor enviado.

| Parâmetro | Regra |
|---|---|
| `cat` | Nome exato da aba (como em `categorias`). Repetível, até 20; cada um de 1 a 200 caracteres. O mesmo valor duas vezes dá 400. Sem `cat`: todas as abas. Várias: qualquer uma delas. |
| `loja` | `amazon`, `ml` ou `shopee`. Repetível; o mesmo valor duas vezes dá 400. Sem `loja`: as três. |
| `q` | Até 200 caracteres. Vírgula separa até 10 termos; basta **um** aparecer no título, sem diferenciar maiúsculas nem acentos. `q=` vazio ou `a,,b` (termo vazio) dá 400. |
| `desconto_min` | Inteiro de 0 a 99. Filtra pelo `desconto_pct` da própria oferta, que **inclui o desconto calculado pelo preço antigo** (veja a tabela de campos). |
| `ordem` | `atualizacao` (padrão), `relevancia`, `desconto`, `menor_preco`, `maior_preco`, `cupom` ou `recentes`. `aleatoria` (que existe no disparo) dá 400: ela não pagina. |
| `limite` | Inteiro de 1 a 200. Padrão 50. |
| `cursor` | O valor de `proximo` da página anterior, na **mesma ordem**. Opaco: não monte nem altere. Cursor adulterado ou de outra ordem dá 400. |
| `genero` | Público: `feminino`, `masculino`, `unissex` ou `sem`, exatamente assim (minúsculas, sem acento). Repetível, até os 4; o mesmo valor duas vezes dá 400. Sem `genero`: todos. Vários: qualquer um deles. O filtro é **exato** e vale para todas as abas: `genero=feminino` só traz ofertas com `"genero": "feminino"`, e as abas que não separam por público (todas fora das 3 de "Abas") são sempre `sem`. Para "perfumes femininos e toda a Cozinha", faça dois pedidos (um com `cat` e `genero`, outro só com `cat`). |
| `preco_max_horas` | Inteiro de 1 a 168 (uma semana), só dígitos. Só traz ofertas com o preço confirmado há **no máximo** essas horas, pelo relógio do Etiqueta (`preco_em` maior ou igual a agora menos as horas e no máximo 5 minutos à frente de agora). Oferta com `preco_em` `null`, fora do formato `AAAA-MM-DDTHH:MM:SS` (hora de 00 a 23, minuto e segundo de 00 a 59, data que existe) ou mais de 5 minutos no futuro nunca passa. **Sem o parâmetro vale `config.preco_validade_horas`** (padrão 24 h, de 1 a 168; ausente ou inválida vale 24), lida a cada pedido: o dono muda o prazo pelo site e a API acompanha, sem reiniciar. Com o parâmetro, vale o número pedido, mesmo maior que o da config. Repetido dá 400. Veja "Idade do preço". |

Mais de 33 pares `nome=valor` no total também dá 400 (`parâmetros demais`). Em `curl`, use `-G --data-urlencode` para acentos e espaços; `+` na query vira espaço.

### Resposta

```json
{"versao": 1,
 "ofertas": [ { "id": 4211, "chave": "amazon:B0G5NZ82TJ", "...": "..." } ],
 "proximo": "2026-11-03T12:36:48~5520",
 "total": 2764}
```

- `ofertas`: a página, na ordem pedida.
- `proximo`: cursor da próxima chamada ou `null` (as regras mudam conforme a ordem; veja "Paginação").
- `total`: quantas ofertas o filtro tem, **sem paginar** (não diminui com o `cursor`). Na ordem `atualizacao` o `total` **já desconta os itens dentro da folga de 60 s**, então pode diferir do `total` de outra ordem no mesmo instante.

### Campos da oferta

| Campo | Tipo | Significado |
|---|---|---|
| `id` | inteiro | Id do item no banco do Etiqueta. Para identificar a oferta, use a `chave`. |
| `chave` | texto | `<loja>:<item_id>`, por exemplo `amazon:B0G5NZ82TJ`. **Use para deduplicar**: é única por oferta e estável. |
| `loja` | texto | `amazon`, `ml` ou `shopee`. |
| `item_id` | texto | Código do produto na loja (ASIN, MLB..., `<shopId>.<itemId>`). |
| `categoria` | texto | Nome da aba do Etiqueta, uma das 17 de "Abas" (por exemplo `Perfumes e Perfumaria`). |
| `busca` | texto | Termo de busca que trouxe o item. Pode ser vazio. |
| `titulo` | texto | Título, não vazio. |
| `link` | texto | **Link de afiliado da própria loja**, pronto para usar: Amazon `https://www.amazon.com.br/...?tag=desejodemen01-20`, ML `https://meli.la/...`, Shopee `https://s.shopee.com.br/...`. |
| `imagem` | texto ou `null` | URL da foto, só se for do CDN da loja do item (Amazon `m.media-amazon.com`, ML `http2.mlstatic.com`, Shopee `down-br.img.susercontent.com`); senão `null`. A URL já é a da versão grande no mesmo CDN (`disparo.foto_grande`; o banco guarda a miniatura): Amazon `._<mods>_.<ext>` vira `._AC_SL1000_.<ext>`; ML `-<letra maiúscula>.<webp\|jpg\|jpeg\|png>` vira `-F.jpg`; Shopee perde o `_tn` do fim. URL com query ou fragmento, ou sem esse padrão, sai como está gravada. |
| `preco` | número | Preço em reais, maior que 0 (`"R$ 4.285,90"` vira `4285.9`). |
| `preco_antigo` | número ou `null` | Preço cheio. `null` se vazio ou se não for maior que `preco`. A Shopee não tem. |
| `desconto_pct` | inteiro | Desconto em %. Se o texto de desconto da coleta der 0 e houver `preco_antigo`, é `round((1 - preco / preco_antigo) * 100)`. `0` quando não há desconto. |
| `vendas` | inteiro | Vendas da coleta ("Mais de 1 mil compras" vale 1000). `0` quando não há. |
| `avaliacao` | número ou `null` | Nota (por exemplo `4.5`). `null` se não houver. |
| `num_avaliacoes` | inteiro | Quantidade de avaliações. `0` quando não há. |
| `frete_gratis` | booleano | `true` se o texto de frete da coleta contiver "grátis" (sem diferenciar maiúsculas e acentos). |
| `cupom` | texto | Texto do cupom, `""` quando não há. |
| `criado_em` | texto | Quando o item entrou no banco. |
| `atualizado_em` | texto | Última gravação do item (nova coleta, reclassificação, correção do público pelo site). |
| `genero` | texto | Público da oferta: `feminino`, `masculino`, `unissex` ou `sem`. Só as 3 abas com público (`Perfumes e Perfumaria`, `Beleza e Cuidados` e `Moda e Viagem`) separam por público; nas outras 14 é sempre `sem`. Vem da correção que o dono fez no site ou, sem ela, do título e do termo de busca (`genero.py`). Nas abas com público, `sem` é item sem público definido (hidratante, sabonete, infantil...). Vem depois dos outros campos; consumidor antigo pode ignorá-lo. |
| `preco_em` | texto ou `null` | Quando o preço foi confirmado pela última vez (coleta, atualização em lote ou "Atualizar preço" do site), no mesmo formato de `atualizado_em`. `null` quando não há data confiável: a última gravação não trouxe preço legível, o item foi gravado por uma versão do Etiqueta anterior a esse campo, ou o valor guardado está fora do formato `AAAA-MM-DDTHH:MM:SS`. Trate `null` como preço velho. É o último campo; consumidor antigo pode ignorá-lo. Veja "Idade do preço". |

### Quando uma oferta NÃO sai

Item que falhar em **qualquer** condição fica fora da lista e do `total` (das ofertas):

- `tem_dados` diferente de 1, loja desconhecida, título vazio, ou preço que não seja um número maior que 0 (por exemplo "consulte"). Hoje há centenas de itens da Amazon sem preço.
- Horário `criado_em` ou `atualizado_em` fora do formato `AAAA-MM-DDTHH:MM:SS`.
- `link` que não seja de afiliado **e** da própria loja (ML sem `meli.la`, Amazon com tag de terceiro, link de outra loja).
- Título, cupom, categoria, busca (ou `item_id`, quando não for o próprio link) com algo que se pareça com um endereço de site. A detecção é a mesma e conservadora do disparo: títulos como `i.Phone` ou `55UN85CBPSA.BWZ` ficam de fora de propósito (algumas dezenas de itens no banco de hoje; 27 na contagem de 03/11/2026).

- Preço velho: `preco_em` além da validade (`preco_max_horas` do pedido ou, sem ele, `config.preco_validade_horas`), `null`, fora do formato ou mais de 5 minutos no futuro. É a regra do `disparo.preco_recente`. Só a rota `ofertas` aplica essa condição: `/categorias` continua contando as ofertas de preço velho.

Não entram na v1: a mensagem pronta (o consumidor monta com o template dele), números de telefone, grupos, regras e histórico de envios do disparo.

## Idade do preço

- **`preco_em` não é `atualizado_em`.** O `atualizado_em` muda também quando o item troca de aba ou tem o público corrigido, sem que ninguém tenha olhado o preço. Para saber se o preço está fresco, use só o `preco_em`.
- **Quem grava:** a coleta, a atualização de preços em lote (`atualizar_precos.py` e `ColetaML.atualizar`, etapas 4 e 5 do plano) e o "Atualizar preço" do cartão no site, sempre que trazem um preço legível. Reclassificação de aba, correção de público e troca de link não mexem nele.
- **Itens de antes de 2026-11-04:** a migração do banco (v3) preencheu `preco_em` com o `criado_em`, um limite inferior seguro (o preço pode ser mais novo, nunca mais velho do que diz). Por isso, com a validade de 24 h, um item coletado há mais de um dia só volta a passar depois de uma nova coleta ou atualização do preço.
- **Padrão sem `preco_max_horas` (desde 2026-11-08):** a lista só traz oferta com preço confirmado há no máximo `config.preco_validade_horas` horas (a mesma trava do disparo; padrão 24, de 1 a 168; chave ausente ou valor inválido vale 24). O prazo é lido da config a cada pedido. O consumidor que nunca manda o parâmetro (o Achadinho Turbo) já fica protegido de preço velho. Com banco de antes da migração v3 (sem `preco_em`), a lista vem vazia: na dúvida, o preço é velho.
- **`preco_max_horas`:** a conta é feita no Etiqueta, com o relógio dele; o consumidor não precisa interpretar a data. A regra de idade é a mesma da trava do disparo. Com o parâmetro, vale o número pedido (1 a 168), **mesmo maior que a validade da config**, para quem quer ver ofertas mais antigas de propósito. Um `preco_em` mais de 5 minutos à frente do relógio do Etiqueta conta como velho (relógio adiantado ou gravação errada não deixam um preço "fresco para sempre").
- **Com o cursor:** o filtro vale no instante de cada pedido. Uma oferta cujo preço envelhece entre duas páginas some do filtro sem aviso; quando o preço é atualizado, o `atualizado_em` também muda e ela volta a aparecer depois do cursor (deduplique pela `chave`). O `total` também é o do instante.
- **Sem preço legível na atualização** (item que sumiu da loja, ficou indisponível ou caiu do piso): o item não é regravado, o preço antigo fica e o `preco_em` envelhece. É por isso que a API não apaga nada: o item só deixa de sair na lista quando passa da validade (a da config ou a de `preco_max_horas`).

## Paginação

**Ordem `atualizacao` (padrão):** por `(atualizado_em, id)` crescente. Há muitos itens com o mesmo `atualizado_em`, por isso o cursor tem os dois: `"<atualizado_em>~<id>"`.

- Só entram itens com `atualizado_em` de pelo menos 60 s atrás (**folga**): as coletas gravam em lotes e o cursor não pode passar por um lote ainda aberto. Item recém-gravado aparece na próxima leitura.
- `proximo` é o cursor da **última oferta da página** e só vem `null` quando a página sai **vazia**. Seguir `proximo` percorre todas as ofertas do filtro uma vez só, sem pular nenhuma; a última chamada, vazia, é a que confirma o fim.
- Item atualizado depois (nova coleta, mudança de aba, correção do público pelo site) volta a aparecer depois do cursor. Deduplique pela `chave`.
- **Público e `atualizado_em`:** o `genero` é calculado a cada leitura. **Mudança de regra do classificador (`genero.py`) não mexe em `atualizado_em`**: quem já passou do cursor não vê o gênero novo dos itens antigos. **Correção manual (pelo site) mexe**: o item volta a aparecer depois do cursor com o `genero` corrigido. Se você filtra por `genero` e a regra mudou, faça uma varredura do zero.
- Para pegar **só as novidades**: guarde o último `proximo` **não nulo**; uma resposta vazia com `proximo: null` não apaga o cursor. Na próxima execução, chame com `cursor=<guardado>`; se vier vazia, não há novidade e o cursor guardado continua valendo.
- **Varredura do zero:** um item que passa a ser válido **sem mudar o `atualizado_em`** (por exemplo, mudança na regra de link, mudança na regra do classificador de público, `migrar_categorias.py --restaurar` ou aumento da validade do preço no Etiqueta, que faz ofertas antigas voltarem a valer) não aparece para quem já passou do cursor. Nesses casos, o consumidor faz uma varredura do zero (sem `cursor`) e deduplica pela `chave`.

**Demais ordens:** o resultado é o mesmo de `disparo.ordenar` (as ordens do disparo, com desempate pela ordem de coleta) e o cursor é um **deslocamento** (`"50"`, `"100"`...). `proximo` vem `null` quando não há mais ofertas depois da página.

| Ordem | O que faz |
|---|---|
| `atualizacao` | Mais antigas primeiro por `atualizado_em`, depois `id`. Serve para "novidades desde a última vez". |
| `relevancia` | Mais vendas, depois mais avaliações, depois a nota. |
| `desconto` | Maior desconto em % do texto da coleta primeiro (não usa o desconto calculado pelo preço antigo). |
| `menor_preco` / `maior_preco` | Preço crescente / decrescente. |
| `cupom` | Itens com cupom primeiro, depois o maior desconto. |
| `recentes` | Coletados há menos tempo primeiro (`criado_em`, depois `id`). |

Nas ordens por deslocamento, uma coleta entre duas páginas pode deslocar itens; deduplique pela `chave`.

## `GET /api/v1/categorias`

Não aceita parâmetros (qualquer um dá 400). Conta só as ofertas que passam nas condições acima, **menos a do preço velho** (as categorias contam também as ofertas cujo preço passou da validade; por isso a soma pode ser maior que o `total` de `/api/v1/ofertas`), em ordem alfabética (sem diferenciar acentos). Cada categoria traz o `total`, a contagem por loja (`lojas`, as 3 chaves sempre) e a contagem por público (`generos`, as 4 chaves sempre, na ordem `feminino`, `masculino`, `unissex`, `sem`). As abas que não separam por público têm tudo em `sem`. A soma de `generos` é o `total` da categoria. Cada número é um teto do `total` de `/api/v1/ofertas?cat=<nome>&genero=<valor>`: os dois só são iguais quando todos os preços da aba estão dentro da validade (as categorias contam também o preço velho) e **numa ordem diferente de `atualizacao`** (por exemplo, `ordem=relevancia`). Na ordem padrão `atualizacao`, o `total` desconta os itens alterados nos últimos 60 s (a folga do cursor), então logo depois de uma coleta ou de uma correção pelo site os dois números podem diferir por alguns itens.

Exemplo (valores ilustrativos; mostra uma aba sem público e as três com público, em ordem alfabética):

```json
{"versao": 1,
 "categorias": [{"nome": "Beleza e Cuidados", "total": 120,
                 "lojas": {"amazon": 80, "ml": 30, "shopee": 10},
                 "generos": {"feminino": 40, "masculino": 20, "unissex": 5, "sem": 55}},
                {"nome": "Cozinha", "total": 604,
                 "lojas": {"amazon": 300, "ml": 304, "shopee": 0},
                 "generos": {"feminino": 0, "masculino": 0, "unissex": 0, "sem": 604}},
                {"nome": "Moda e Viagem", "total": 90,
                 "lojas": {"amazon": 60, "ml": 20, "shopee": 10},
                 "generos": {"feminino": 30, "masculino": 35, "unissex": 5, "sem": 20}},
                {"nome": "Perfumes e Perfumaria", "total": 2764,
                 "lojas": {"amazon": 2228, "ml": 0, "shopee": 536},
                 "generos": {"feminino": 629, "masculino": 865, "unissex": 160, "sem": 1110}}],
 "total": 3578}
```

## Erros

Sempre `{"error": "<frase>"}` (a exceção é o 429 do freio, na tabela). A frase nunca traz o valor que o cliente mandou. **Decida pelo código HTTP, não pelo texto:** a frase é para gente ler e pode mudar quando a API ganha parâmetros (por exemplo, com `genero` o limite de pares passou de 28 para 32, e com `preco_max_horas` para 33, e alguns pedidos com 29 a 32 pares trocaram "parâmetros demais" pela mensagem do parâmetro específico).

| Código | Quando | Exemplo de frase |
|---|---|---|
| 400 | Corpo na rota de confirmação de preço | `esta rota não aceita corpo` |
| 400 | Parâmetro inválido | `parâmetro desconhecido (use cat, loja, q, desconto_min, ordem, limite, cursor, genero, preco_max_horas)`; `o parâmetro limite só pode aparecer uma vez`; `loja deve ser amazon, ml, shopee, sem repetir`; `genero deve ser feminino, masculino, unissex, sem, sem repetir`; `categorias repetidas`; `cada termo de q (separados por vírgula) precisa ter texto`; `desconto_min deve ser um número inteiro de 0 a 99`; `limite deve ser um número inteiro de 1 a 200`; `preco_max_horas deve ser um número inteiro de 1 a 168`; `a ordem aleatoria não existe na API: ela não pagina (use outra ordem)`; `cursor inválido: use o valor de "proximo" da página anterior, com a mesma ordem`; `parâmetros demais`; `a rota categorias não aceita parâmetros` |
| 401 | Token ausente ou errado (`WWW-Authenticate: Bearer`) | `token ausente ou inválido: envie Authorization: Bearer <token>` |
| 403 | `Host` não local; pedido de navegador (`Origin` ou `Sec-Fetch-Site`) | `host não permitido`; `a API v1 não aceita pedidos de navegador` |
| 404 | Rota v1 desconhecida (só depois da autenticação); ASIN fora do formato na rota de confirmação | `rota não encontrada` |
| 404 | Confirmação de preço de um ASIN que não é oferta da Amazon no banco | `oferta da Amazon não encontrada` |
| 405 | Método diferente de GET, depois da autenticação (`Allow: GET`); na rota de confirmação, diferente de POST (`Allow: POST`) | `método não permitido: a API só aceita GET`; `método não permitido: esta rota só aceita POST` |
| 429 | Freio da confirmação de preço (`Retry-After`) | não é `{"error"}`: `{"versao": 1, "resultado": "freio", "motivo": ..., "tentar_em_s": N}` |
| 500 | Falha inesperada | `erro interno na API v1` (o log do servidor traz só o tipo do erro, nunca a mensagem, que pode trazer dados) |
| 503 | API desligada (sem `api_token.txt` válido) | `a API v1 está desligada: veja o motivo no log do servidor` |

## Exemplos

`curl` (a segunda chamada pagina com o `proximo` da primeira; `-G --data-urlencode` cuida de espaços e acentos):

```
curl -s -H @api_cabecalho.txt "http://localhost:8765/api/v1/categorias"

curl -s -G -H @api_cabecalho.txt \
  --data-urlencode "cat=Perfumes e Perfumaria" -d limite=2 \
  "http://localhost:8765/api/v1/ofertas"

curl -s -G -H @api_cabecalho.txt \
  --data-urlencode "cat=Perfumes e Perfumaria" -d limite=2 \
  --data-urlencode "cursor=2026-11-03T12:36:48~5520" \
  "http://localhost:8765/api/v1/ofertas"

curl -s -G -H @api_cabecalho.txt \
  -d loja=shopee -d ordem=desconto -d desconto_min=30 -d limite=10 \
  "http://localhost:8765/api/v1/ofertas"

curl -s -G -H @api_cabecalho.txt \
  --data-urlencode "cat=Perfumes e Perfumaria" -d genero=feminino -d genero=unissex -d limite=2 \
  "http://localhost:8765/api/v1/ofertas"

curl -s -G -H @api_cabecalho.txt \
  -d preco_max_horas=24 -d ordem=desconto -d limite=10 \
  "http://localhost:8765/api/v1/ofertas"
```

Node 22 (`fetch` nativo; sem dependência):

```js
const token = (await readFile('api_token.txt', 'utf8')).trim();   // import { readFile } from 'node:fs/promises'
const url = new URL('http://127.0.0.1:8765/api/v1/ofertas');
url.searchParams.append('cat', 'Perfumes e Perfumaria');
url.searchParams.set('limite', '50');
const r = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
const { ofertas, proximo, total } = await r.json();
```

## Limites

- **Sem limite de taxa nas rotas `GET`.** Um consumidor local, com token. Se um dia a API sair do computador do dono (VPS), isso e o HTTPS passam a ser requisito. A rota de confirmação de preço é a exceção: tem freio próprio, porque cada pedido abre a página da Amazon.
- **O token não protege mais que hoje contra outro processo no mesmo computador:** `GET /api/items` (a API da interface) continua aberto a quem não manda `Origin`. O que a v1 ganha é barrar o navegador e ter o contrato pronto para o dia em que o consumidor estiver em outra máquina.
- **Item apagado some sem aviso:** a API só lista o que existe agora. O consumidor relê a lista a cada execução.
- **Reclassificar abas** (`migrar_categorias.py`, `classificar_lista.py`) regrava `atualizado_em` de muitos itens; eles reaparecem na ordem `atualizacao`. É esperado: a `chave` evita repetir o envio. Foi o que a migração para as 17 abas fez em 2026-11-04 (veja "Abas").
- Não existe `GET /api/v1/ofertas/<id>` (rota desconhecida dá 404).

## `POST /api/v1/amazon/<ASIN>/confirmar-preco`

Relê agora a página de **uma** oferta da Amazon que já está no banco e, com preço legível, grava o preço. O Achadinho Turbo chama logo antes de enviar a oferta. É a mesma leitura do botão "Atualizar preço" do site (`buscar_produto_amazon`) e a mesma classificação do `atualizar_precos.py`. **É a única rota da v1 que grava.** Código: `confirmar_preco_amazon`, `FreioReleitura` e `Handler.despachar_confirmar_preco` em `servidor.py`.

- **`<ASIN>`:** exatamente 10 caracteres de `A-Z` e `0-9`, conferidos no caminho cru (sem decodificar). Minúsculas, `%xx` ou outro tamanho dão 404 `rota não encontrada`. Outro formato de caminho (`/api/v1/amazon/<ASIN>`, barra a mais) é outra rota da v1: `POST` nela dá 405 com `Allow: GET`.
- **O que é lido:** `https://www.amazon.com.br/dp/<ASIN>`, **sem tag** (a releitura não pode parecer clique de afiliado). A URL é montada pelo Etiqueta a partir do ASIN; nada vem do cliente. Os redirects passam pela mesma conferência do `/api/fetch` (só hosts da Amazon). Prazo de 10 s por operação de rede.
- **Sem corpo:** `POST` sem corpo (`Content-Length` ausente ou `0`). Qualquer corpo, ou `Transfer-Encoding`, dá 400 `esta rota não aceita corpo`. Não há parâmetro.

**Guardas, na ordem** (as 5 primeiras são as de toda a v1):

| # | Condição | Resposta |
|---|---|---|
| 1 | `Host` não local | 403 `host não permitido` |
| 2 | Pedido de navegador (`Origin` ou `Sec-Fetch-Site`) | 403 `a API v1 não aceita pedidos de navegador` |
| 3 | API desligada (sem token) | 503 |
| 4 | Token ausente ou errado | 401, com `WWW-Authenticate: Bearer` |
| 5 | Método diferente de POST (inclui GET, HEAD e OPTIONS) | 405 `método não permitido: esta rota só aceita POST`, com `Allow: POST` |
| 6 | ASIN fora do formato | 404 `rota não encontrada` |
| 7 | Corpo não vazio | 400 `esta rota não aceita corpo` |
| 8 | Não há item com `loja='amazon'` e `item_id=<ASIN>` (inclui item do ML ou da Shopee com o mesmo código) | 404 `oferta da Amazon não encontrada` |
| 9 | Freio | 429 (veja abaixo) |
| 10 | Leitura da página | 200 com o resultado |

Nenhuma recusa das linhas 1 a 8 abre a Amazon nem gasta o freio.

**Respostas 200** (sempre com `"versao": 1`; decida pelo `resultado`):

| `resultado` | Quando | Grava? |
|---|---|---|
| `confirmado` | Página com título, ASIN igual ao pedido e preço legível (`ler_preco`). | Sim, antes de responder. |
| `sem_preco` | Título presente e ASIN igual, mas preço ilegível ou ausente (indisponível); ou HTTP 404/410 da Amazon. | Não. |
| `outro_produto` | A página final é de outro ASIN; ou redirect para fora da Amazon. | Não. |
| `bloqueado` | Captcha; HTTP 429 ou 503 da Amazon; página sem título ou sem ASIN (página que não dá para reconhecer nunca vira descarte). Abre a pausa de 15 min do freio. | Não. |
| `falha_rede` | Erro de rede, tempo esgotado, conexão cortada ou outro código HTTP. | Não. |

```json
{"versao": 1, "resultado": "confirmado", "preco": 89.9, "preco_antigo": 119.9, "desconto_pct": 25,
 "preco_em": "2026-11-11T10:30:00"}
{"versao": 1, "resultado": "sem_preco"}
```

- No `confirmado`, `preco` é o número gravado; `preco_antigo` vem `null` quando a página não traz o preço cheio ou quando ele não é maior que `preco`; `desconto_pct` é o desconto da página ou, sem ele, o calculado pelo preço antigo, e vem `null` sem desconto (diferente das ofertas, onde é `0`); `preco_em` é o carimbo novo, no formato de "Resposta e formato".
- A resposta nunca traz HTML da página nem a mensagem de um erro.

**O que é gravado no `confirmado`:** a leitura de rede acontece fora de transação. Depois, numa transação `BEGIN IMMEDIATE`, o servidor relê a linha, aplica a regra do preço antigo implausível (`sanear_precos`: antigo de 5× o preço ou mais é descartado junto com o desconto) e grava **só** `preco`, `preco_antigo` e `desconto` da página, mais `preco_em` e `atualizado_em` com a hora de agora. Nunca insere item, nunca mexe em `url` (o link de afiliado), título, cupom, foto ou nota. Se o item foi apagado durante a leitura, a resposta é 404 `oferta da Amazon não encontrada` e nada é gravado. Qualquer outro resultado não grava nada: o preço anterior e o `preco_em` ficam como estavam. Como o `atualizado_em` muda, a oferta reaparece depois do cursor na ordem `atualizacao` (deduplique pela `chave`).

**Freio** (em memória; zera quando o servidor reinicia):

- 429 com `Retry-After: N` e `{"versao": 1, "resultado": "freio", "motivo": "<motivo>", "tentar_em_s": N}`, `N` inteiro de 1 ou mais.
- Motivos, na ordem em que são conferidos:
  - `ocupado`: uma leitura por vez; outra está em curso.
  - `pausa`: houve um `bloqueado` há menos de 15 min (contados do fim daquela leitura).
  - `intervalo`: menos de 3 s desde o início da leitura anterior.
  - `teto`: 60 leituras na última hora (janela deslizante).
  - `rodada`: uma rodada da Amazon (coleta ou `atualizar_precos.py amazon`) segura a trava `travar_rodada('amazon')`. A rota só confere a trava (pega e solta na hora) e nunca a segura durante a leitura: a rodada tem prioridade e pode começar no meio.
- Recusa não conta como leitura. Pedido recusado antes do freio (401, 404, 400...) também não.

Exemplo (o dono, no terminal; o arquivo de cabeçalho de "Como usar em 1 minuto"):

```
curl -s -X POST -H @api_cabecalho.txt "http://localhost:8765/api/v1/amazon/<ASIN>/confirmar-preco"
```

Node 22: `fetch(url, { method: 'POST', headers: { Authorization: `Bearer ${token}` }, redirect: 'error' })`, sem corpo; leia o corpo inteiro e trate 429 pelo `tentar_em_s`.

## Guia de encaixe no Achadinho Turbo

Sugestão, sem código, para a sessão que cuida do Turbo. **Este repositório não edita o Turbo.** As linhas citadas são de `/home/ufla/Documentos/achadinhoturbo` em 2026-11-03 e podem mudar (outra sessão edita esses arquivos).

**Nome:** no Turbo, "etiqueta" quer dizer a etiqueta de afiliado do Mercado Livre. Chame a fonte nova de **`catalogo`** ("Catálogo do Etiqueta"), para não colidir.

**Fonte e conexão**
- Novo tipo de fonte `catalogo` em `candidatesFor` (`src/ml.js`, hoje `:298`) e na validação de tipos da regra (`src/server.js`, `tipo()`), ao lado de `afiliados`, `search` e `list`. A fonte chama `GET /api/v1/ofertas` com os filtros da regra (`cat`, `loja`, `q`, `desconto_min`, `ordem`, `limite`) e o `preco_max_horas` (veja o item seguinte).
- **Preço velho:** desde 2026-11-08, sem `preco_max_horas` a v1 só entrega oferta com preço dentro da validade configurada no Etiqueta (`config.preco_validade_horas`, padrão 24 h), então o Turbo já fica protegido sem mandar nada. Mande `preco_max_horas` só se quiser um prazo próprio por regra (de 1 a 168, mesmo maior que o da config). Não há campo equivalente no `renderTemplate`: o `preco_em` serve só para filtrar ou para mostrar na tela do Turbo, se quiser. Na hora do envio, reconfira o `preco_em` com a mesma regra ou busque a oferta de novo; não publique de cache. Se a fonte "secar" com o filtro, é sinal de que os preços do Etiqueta precisam ser atualizados (no Etiqueta, não no Turbo).
- Conexão nova com o endereço `http://127.0.0.1:8765` e o token como **segredo** (campo `segredo` em `PLATAFORMAS`, `src/lojas.js`, e `conexoes.segredos`, que o Turbo nunca devolve ao navegador). Trocar o token: troque o arquivo, reinicie o Etiqueta e atualize em Conexões.
- Só `fetch` em `127.0.0.1` com `Authorization`: sem `Origin`, passa na guarda.

**Mapeamento para o formato do `renderTemplate`** (`src/template.js:36-49`, `src/ml.js:228-238`)

| Turbo | Etiqueta (v1) |
|---|---|
| `key` | `chave` |
| `title` | `titulo` |
| `url` | `link` |
| `price` | `preco` |
| `oldPrice` | `preco_antigo` |
| `discountPct` | `desconto_pct` |
| `sold` | `vendas` |
| `freeShipping` | `frete_gratis` |
| `coupon` | `cupom` |
| `image` | `imagem` |

Mandar `desconto_pct` sempre preenchido evita que o Turbo apague o desconto em `discountPct ?? ...` (`src/template.js:37`).

**Deduplicação:** por `chave` em `sent_offers`, como o Turbo já faz (`src/scheduler.js:58-61,132`). Um candidato que já traz `title` e `price` não é resolvido de novo (`src/ml.js:254-256`).

**Dois modos de consumo**
- **Novidades desde a última execução** (ordem `atualizacao`): guarde o último `proximo` **não nulo** por regra (resposta vazia com `proximo: null` não apaga o cursor) e volte com `cursor`; veja "Paginação". Custa uma chamada extra, vazia, no fim. Depois de `--restaurar` ou de mudança na regra de link, faça uma varredura do zero com `limite=200`.
- **As melhores por execução** (`relevancia`, `desconto`, `menor_preco`, ...): pagine por `proximo` até achar `per_run` ofertas ainda não enviadas dentro do prazo de repetição; sem isso a fonte "seca" depois de 200 envios.

**Os três ajustes do lado do Turbo**
1. `src/scheduler.js:99`: a regra exige etiqueta do ML (`escolha uma etiqueta`). Em regra de catálogo só com Amazon e/ou Shopee, dispense a etiqueta; se a regra incluir o ML, ela continua precisando (veja o ajuste 2).
2. `src/scheduler.js:113`: o link é sempre gerado de novo pela extensão (`links.requestLink({ url: offer.url, tag: etq.name })`). Para a fonte `catalogo`:
   - **Amazon:** use o `link` como veio, **sem `requestLink`**. A tag `desejodemen01-20` é conferida pelo Etiqueta. Trocá-lo por um link comum quebra a regra do dono.
   - **Shopee:** use o `link` como veio, mas **revise antes de enviar** (ou envie só itens que você mesmo coletou). O link curto `https://s.shopee.com.br/<código>` não prova de quem é a conta; o Etiqueta só confere o formato, e um item plantado no banco com link de terceiro passaria.
   - **Mercado Livre: regere o link com a etiqueta do dono** (`requestLink` com a etiqueta `achadosmenicas`) ou revise os links antes de enviar. O Etiqueta só confere o **formato** (`https://meli.la/<código>`), não de quem é a etiqueta: um link de afiliado de terceiro plantado no banco passaria. Não use o `link` do ML às cegas.
3. `src/scheduler.js:121`: a foto só sai se for do CDN do ML (`IMAGEM_PERMITIDA`, `src/ml.js:31`). Libere também os CDNs da Amazon e da Shopee, que são os que a `imagem` da v1 pode trazer (o `src/lojas.js` já tem `IMAGEM_AMAZON` e `IMAGEM_SHOPEE`).

**Shopee:** as regras automáticas do Turbo hoje só enviam ML e Amazon. Os cerca de 540 itens da Shopee saem na API, mas só serão enviados quando o Turbo tiver suporte à Shopee. Até lá, filtre com `loja=amazon&loja=ml` na regra.

**Se o Turbo for para uma VPS:** o pull não alcança o `localhost` do dono. O caminho previsto é um script de saída que empurra o mesmo JSON para um endpoint HTTPS do Turbo, com token. O formato da oferta foi pensado para isso.
