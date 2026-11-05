# Plano técnico: API oficial do Mercado Livre na coleta e na atualização de preços
- Brief: não há. Origem: pedido do lead de 2026-11-05 (app "Etiqueta" no DevCenter, Client ID `3553760734310605`)
- Data: 2026-11-05

## Objetivo e critérios de aceite
Trocar o console do DevTools pela API oficial do ML (OAuth 2.0 com PKCE, só leitura) na atualização de preços e, se a API permitir, na coleta. O Etiqueta é afiliado: só lê anúncios de terceiros. O `meli.la` continua vindo do `ColetaML.afiliar()`.

- CA1: a página `https://desejodemenina.com/ml/callback` responde 200, com no máximo um 301 para a barra final que preserve a query. Ela não tem JS nem recurso externo e manda `no-store`, `no-referrer` e `noindex`.
- CA2: `ml_api.py autorizar` gera o `state` e o PKCE S256 só em memória e imprime a URL de autorização. Depois lê do stdin o endereço colado e recusa host ou caminho errado, `state` diferente e `error=`. Só então troca o code e grava os tokens. Token, code, verifier e Secret nunca saem na tela, em `argv`, em log ou em mensagem de exceção.
- CA3: os tokens ficam só no arquivo de `ACHADINHOS_ML_TOKENS` (padrão `ml_tokens.json`), que está no `.gitignore`.
  - O arquivo é criado com modo 0600 por escrita atômica.
  - A leitura recusa symlink, arquivo que não é comum, dono diferente do usuário, permissão aberta (`& 0o077`) e arquivo acima de 4 KB.
  - Os tokens nunca vão para a tabela `config` nem para rota, página ou log do `servidor.py`.
- CA4: a renovação acontece quando faltam menos de 5 min para o access_token vencer.
  - Ela roda sob `fcntl.flock` exclusivo e relê o arquivo dentro do lock.
  - O novo refresh_token é gravado antes de qualquer outra chamada.
  - `invalid_grant` dá saída 2 e a mensagem "rode `ml_api.py autorizar`".
  - Um 401 numa chamada provoca uma renovação e uma nova tentativa, só uma vez.
- CA5: o cliente HTTP segue estas regras.
  - Host fixo `api.mercadolibre.com`, só GET, em caminhos montados pelo código.
  - `Authorization: Bearer` sempre no header, nunca na query. O redirect não é seguido e a resposta tem teto de 2 MB.
  - 429 ou `local_rate_limited`: backoff exponencial com jitter e, depois de 3 tentativas, saída 3.
  - 403 `PolicyAgent`: mensagem de permissão funcional e saída 2.
  - Outros erros: saída 1. Só sai o status e o `error`/`code` do ML, filtrado por `[A-Za-z_]{1,64}`.
- CA6: `ml_api.py conferir` chama `GET /users/me` e mostra só "OK" e os escopos, com aviso se aparecer `write`. `ml_api.py sondar` testa cada endpoint candidato (F1 a F6). Para cada um, imprime só o status, o código de erro e os nomes de campo de uma allowlist, nunca valores.
- CA7: `atualizar_precos.py ml [--cat ABA]` atualiza os preços pela API, por id, 20 ids por chamada de `/items/bulk`. A etapa 4 só entra se F2 der 200.
  - Só grava itens que já existem (`inserir=False`) e nunca troca o `meli.la`.
  - Mantém nota, vendas, foto, frete e cupom do banco.
  - Item inativo conta como indisponível. Item usado conta como usado. Nenhum dos dois é gravado.
- CA8: `coletar_ml.py buscas --cat ABA [--ordens relevancia,caros]` grava pela API, com estas regras. A etapa 5 depende do portão G1 e da P1.
  - Tem o mesmo piso e a mesma recusa de usado das outras coletas.
  - O progresso fica em `ACHADINHOS_FEITOS_ML`.
  - O item entra sem link de afiliado, e a saída lembra o dono de rodar o `ColetaML.afiliar()`.
- CA9: nenhum teste sai para a rede. O `py_compile` e as suítes atuais continuam passando, salvo as 3 falhas que já existem no `test_atualizar_precos`.
- CA10: o README traz o passo a passo, as variáveis e o que fazer em cada saída. O CLAUDE.md fica com o lead.
- CA11: `coletar_ml.js`, `mensagens.html` e `amazon.php` não mudam nesta entrega.

## Contexto atual
- **ML hoje é só console.**
  - `coletar_ml.js:814` `coletar` lê os polycards da listagem.
  - `:599` `polycardParaItem` monta `item_id` `MLB<n>`, url `https://produto.mercadolivre.com.br/MLB-<n>`, nota e "+50 vendidos" do `review_compacted`.
  - `:535` `formatarPreco` dá `R$ 1.234` ou `R$ 1.234,50`, sem ",00". `:622` calcula o desconto em %.
  - `:1033` `atualizar` usa `so_existentes`. `:1479` `afiliar` troca a url por `meli.la` no linkbuilder.
- **Ponto de troca.**
  - `atualizar_precos.py:371` `FONTES = {'amazon', 'shopee'}`.
  - `:56` `ID_DA_LOJA` (sem `ml`) e `:110` `selecionar` (lê só `id, item_id, cat, busca, preco, preco_em`).
  - `:154` `gravar_pagina` chama `upsert(inserir=False)`.
- **Armadilha.** O `upsert` regrava todos os `CAMPOS` com o que veio (`servidor.py:381-386`), então o campo ausente vira `''`. A API por id não traz nota nem vendas, e a fonte do ML precisa completar `data` com os valores do banco.
- **Links.** `sql_link_preservado` (`servidor.py:172`) e o `CASE` (`:385`) preservam o `meli.la`. `/api/ml-sem-afiliado` (`:754`) alimenta o `afiliar()`.
- **Config.** `/api/config/<chave>` (`:766`) expõe a tabela `config`, por isso nenhum token vai para lá.
- **Padrões a copiar.**
  - `coletar_shopee.py:91` `Segredo`.
  - `:314` `credenciais` com `pop`.
  - `:366` `SemRedirecionar`.
  - `:356` `_ler_json` com teto de bytes.
  - Saídas 0/1/2/3 (`:47-50`).
  - `servidor.py:455` `carregar_token_api`, que aceita só arquivo comum, com teto de tamanho e aviso de modo aberto.
- **Banco** (medido em modo ro em 2026-11-05):
  - 3.818 itens do ML, dos quais 3.817 com id `MLB` (3.814 com 13 caracteres) e 1 com a url como id.
  - 2.705 itens com `meli.la` e 1.112 sem afiliado.
  - `config` vazia. `user_version` 3.
  - O lote de preços daria cerca de 191 chamadas de 20 ids.
- **Hostinger.** O `.htaccess` da raiz, no repositório `~/Documentos/lande_pages/Lange_meninas/site/hostinger/.htaccess`, força https sem www. A subpasta não pode ter `RewriteEngine`, senão anula a raiz (a mesma regra do `painel/.htaccess`). A publicação é arquivo a arquivo. Não verifiquei se é igual ao que está em produção.

### O que a doc oficial e os testes sem token mostram (2026-11-05)
- **Auth** (doc "Autenticação e Autorização", atualizada em 29/12/2025):
  - O fluxo e a troca são os do Trello. A resposta traz `expires_in` 21600, `refresh_token` de uso único (só o último vale) e `scope`, por exemplo `offline_access read`.
  - O refresh vence em 6 meses. Cai antes se a app passar 4 meses sem chamar a API, se a senha mudar, se o Secret for renovado ou se a permissão for revogada.
  - O ML não valida o `state`. A doc não diz a validade do code (não verificado).
- **Permissões funcionais** (doc de 21/11/2025):
  - "Busca de items" e "Buscador de produtos" estão sob **Publicação e sincronização**. "Mais vendidos" (`/highlights`) está sob **Métricas do negócio**.
  - Sem a permissão, a API responde `403 {"blocked_by":"PolicyAgent","code":"PA_UNAUTHORIZED_RESULT_FROM_POLICIES"}`.
  - A app só com "Usuários" deve tomar esse 403 nos endpoints de item.
- **Multiget.** A doc "Busca de itens" (31/08/2026) diz que `/items?ids=` está em descontinuação ("migre até 25/10/2026") e manda usar `/items/bulk?ids=`, até 20 ids, com `status_code` e atributos com o prefixo `body.`. O `available_quantity` público é uma faixa.
- **Chamadas sem token:**
  - `/sites/MLB/search` responde `403 {"message":"forbidden"}`, um formato diferente do dos outros endpoints.
  - `/items/{id}`, `/products/search` e `/users/me` respondem 403 `PolicyAgent`.
  - `/items?ids=` responde 401 do nginx.
- **Terceiros** (sem confirmação oficial):
  - Há muitos relatos no Reclame Aqui, de 2025 a 2026, de `/sites/MLB/search` com 403 mesmo com token.
  - O PR `Maxwbh/Lista_de_Presentes#8` (19/10/2026), com token `client_credentials` `read`, relata `/items/{id}` de outro vendedor com `403 access_denied` e `/products/search?q=` e `/products/{id}/items` (preço por anúncio) com 200.
  - Não há campo público de vendas: `sold_quantity` de terceiros não foi verificado. A nota vem de `/reviews/item/{id}`, com `rating_average` e `paging.total`.

## Abordagens consideradas
| Tema | Abordagem | Prós | Contras | Risco |
|---|---|---|---|---|
| Callback | **Página estática sem JS que pede para copiar o endereço** | Nada executa. Zero segredo na Hostinger. Dois arquivos | O dono copia a barra de endereço | O code fica no log de acesso da Hostinger, mas é de uso único e exige o verifier e o Secret |
| Callback | Página com JS que mostra o code e tem botão copiar | Mais cômoda | Superfície de XSS e CSP com hash para manter | Baixo, ganho pequeno: descartada |
| Callback | PHP na Hostinger que troca o code | Sem copiar e colar | O Secret iria para a Hostinger | Alto: descartada |
| Callback | Servidor local ou túnel (ngrok) | Automático | O ML recusa `localhost`, e o túnel expõe a porta e traz dependência | Descartada |
| Onde roda o OAuth | **CLI `ml_api.py` no terminal do dono** | O padrão da Shopee. O servidor nunca vê o Secret | Mais um comando | Baixo |
| Onde roda o OAuth | Rota no `servidor.py` | Botão no site | O site passaria a pedir credencial, o que contraria a regra do dono | Descartada |
| Tokens | **Arquivo 0600 fora do git** | stdlib, padrão do `api_token.txt` | Quem tem a conta Linux lê o arquivo | Baixo: o refresh exige o Secret, e o access só lê por 6 h |
| Tokens | Cifrar com chave tirada do Secret | O arquivo roubado não serve | Complexidade sem ganho real, já que o refresh já exige o Secret | Excesso: descartada |

## Decisão
1. **Etapa 0, manual.** O dono publica a página de callback e ativa **Publicação e sincronização** em **somente leitura** no DevCenter. Sem a permissão, todo endpoint de item dá 403 `PolicyAgent`, conforme a doc (a confirmar, F0). Ele não habilita escrita.
2. **`ml_api.py` é o único módulo que fala com a API.** Ele cuida do OAuth, do arquivo de tokens com lock, do cliente HTTP e dos subcomandos `autorizar`, `conferir`, `sondar` e `sair`, e guarda as funções puras de mapeamento: `formatar_preco` (porte do `formatarPreco` do JS), `desconto` e `RE_USADO`/`eh_usado`. Ele não importa `servidor.py`, então nenhum código do servidor toca o arquivo de tokens.
3. **Fluxo sem nada em disco antes da troca.** O `autorizar` faz tudo num processo só. Gera o `state` e o verifier, imprime a URL e espera com `input()` o endereço colado. Confere, troca e grava. O Secret é lido com `pop` no início.
4. **Portão G1.** Depois das etapas 1 e 2, o dono roda `autorizar`, `conferir` e `sondar`, e o lead registra F0 a F6 aqui. A etapa 4 só entra com F2 = 200. A etapa 5 só entra com F1 ou F3 = 200 e com a P1 respondida. Antes dela, o arquiteto fecha o desenho com uma revisão curta deste plano. Se a API estiver fechada, o ML segue no console como hoje, e o que for entregue serve para tentar de novo depois.
5. **Sem migração e sem rota nova.** O `servidor.py`, o `index.html`, o `disparo.py` e o `api_ofertas.py` não mudam.
6. **Fora desta entrega:** aposentar o `ColetaML.coletar` e o `ColetaML.atualizar`. Só depois de duas semanas de API estável, num plano próprio.

## Esquema e contratos
- **Constantes de `ml_api.py`.** `CLIENT_ID = '3553760734310605'` e `REDIRECT_URI = 'https://desejodemenina.com/ml/callback'`. URL de autorização: `https://auth.mercadolivre.com.br/authorization`. API: `https://api.mercadolibre.com`. Nenhuma variável troca host, client ou redirect.
- **Ambiente.**
  - `ACHADINHOS_ML_SECRET` (lido com `pop`, embrulhado em `Segredo`). É exigido só para a troca e para a renovação. Se faltar quando for preciso, a saída é 2 com a receita `read -rs S; ACHADINHOS_ML_SECRET="$S" python3 ...; unset S`.
  - `ACHADINHOS_ML_TOKENS`.
  - `ACHADINHOS_FEITOS_ML` (padrão `coleta_ml_feitos.txt`).
- **Arquivo de tokens** (JSON, até 4 KB): `{"v":1,"user_id":<int>,"access_token":"…","expira_em":<epoch int>,"refresh_token":"…","scope":"…","renovado_em":"AAAA-MM-DDTHH:MM:SS"}`.
  - A gravação segue esta ordem: `os.open(tmp, O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW, 0o600)` na mesma pasta, `fsync`, `os.replace` e `fsync` da pasta.
  - O lock fica em `<arquivo>.lock`, com modo 0600.
- **PKCE.** `verifier = secrets.token_urlsafe(64)` (86 caracteres). `challenge = base64url(sha256(verifier))`, sem `=`. `state = secrets.token_urlsafe(32)`, comparado com `hmac.compare_digest`.
- **Endereço colado.**
  - Esquema `https`, host `desejodemenina.com`, caminho `/ml/callback` ou `/ml/callback/`.
  - Exatamente um `code` (`[A-Za-z0-9_-]{1,256}`) e um `state`.
  - Com `error=`, a saída é 1 e a mensagem é fixa.
- **API pública do módulo.**
  - `Sessao(caminho=TOKENS, segredo=None, opener=OPENER, relogio=time.time, dormir=time.sleep)`, com o método `.get(caminho, params=None) -> dict|list`.
  - `sessao_do_ambiente()`.
  - Exceções `RefazerAutorizacao`, `SemPermissao`, `CredencialInvalida` e `ConfigFaltando` (saída 2), `Limite` (saída 3), `RespostaInvalida` e `ErroApi(status, codigo)` (saída 1).
  - `formatar_preco(float) -> str`, `desconto(atual, antes) -> (preco_antigo, desconto)`, `eh_usado(titulo)`.
- **Bulk (F6).** `GET /items/bulk?ids=<até 20>&attributes=body.id,body.title,body.price,body.original_price,body.status,body.condition`. Para cada elemento:
  - `status_code` 200 e `status == 'active'`: `ok`.
  - `condition != 'new'` ou `eh_usado(title)`: `usado`.
  - Outro status: `indisponivel`.
  - 404 ou ausente: `sumiu`.
- **`atualizar_precos.py`.** `ID_DA_LOJA['ml'] = re.compile(r'MLB[0-9]{6,19}')`. O `selecionar` passa a ler também os `S.CAMPOS`, o que é inofensivo para as outras fontes. A fonte `fonte_ml_api` monta `data = {c: linha[c] for c in CAMPOS}` e só sobrepõe `titulo`, `preco`, `preco_antigo` e `desconto`. A url sai de `https://produto.mercadolivre.com.br/MLB-<n>` montada pelo id, nunca do banco.

## Etapas
| # | Etapa | Arquivos | Verificação | Responsável | Grupo | Sensível | CAs |
|---|---|---|---|---|---|---|---|
| 0 | O dono publica `public_html/ml/callback/index.html` e `.htaccess` (conteúdo abaixo) e ativa "Publicação e sincronização" em somente leitura | Hostinger (fora do repo) | `curl -sI 'https://desejodemenina.com/ml/callback?code=T&state=T'` dá 301 para `/ml/callback/?code=T&state=T`. `curl -sI` nessa URL dá 200 com `Cache-Control: no-store`, `Referrer-Policy: no-referrer`, `X-Robots-Tag` e CSP | dono (o lead roda o curl) | — | sim (entrada pública) | CA1 |
| 1 | Núcleo do `ml_api.py`: `Segredo`, PKCE e `state`, parse do endereço colado, arquivo de tokens (leitura estrita, gravação atômica 0600, flock, renovação com margem de 5 min), `Sessao.get` (host fixo, Bearer, sem redirect, teto de 2 MB, 401 → uma renovação, 429 → backoff de 3 tentativas, mapeamento de erros) e as funções puras de mapeamento. Testes com opener e relógio falsos, em pasta temporária: modo 0600, symlink e modo 0644 recusados, dois processos renovando ao mesmo tempo (o segundo usa o token novo sem gastar o refresh), `invalid_grant`, `PolicyAgent`, `formatar_preco` igual aos casos do JS e saída e exceções sem token falso nem Secret. Mais `ml_tokens.json`, `ml_tokens.json.lock` e `coleta_ml_feitos.txt` no `.gitignore` | `ml_api.py`, `testes/test_ml_api.py`, `.gitignore` | `python3 -m py_compile ml_api.py`, `python3 testes/test_ml_api.py -v`, `git check-ignore ml_tokens.json ml_tokens.json.lock coleta_ml_feitos.txt .ml_tokens.json.0123456789abcdef.tmp` (lista os 4; `-q` só aceita um nome) | dev (opus) | A | sim (segredo, autenticação, concorrência) | CA2-CA5, CA9 |
| 2 | Subcomandos `autorizar`, `conferir`, `sondar` e `sair` (`sair` apaga o arquivo local e explica como revogar em "Segurança > Aplicativos" da conta, não verificado). O `sondar` usa 3 ids `MLB` lidos do banco em modo `ro` e o termo fixo "perfume". Ele chama `/users/me`, `/sites/MLB/search?q=&limit=1`, `/products/search?status=active&site_id=MLB&q=&limit=1`, `/products/{id}/items` (com o primeiro id do passo anterior), `/items/bulk`, `/items/{id}` e `/reviews/item/{id}`, e imprime o status, o código e os campos da allowlist (`price`, `original_price`, `sold_quantity`, `condition`, `status`, `rating_average`, `catalog_product_id`, `thumbnail`). Saídas 0/1/2/3. Testes de CLI com stdin e opener falsos | `ml_api.py`, `testes/test_ml_api.py` | `python3 testes/test_ml_api.py -v`, e `ACHADINHOS_ML_TOKENS=/nao/existe python3 ml_api.py conferir; echo $?` deve dar 2 | dev (opus) | B | sim (segredo, entrada colada) | CA2, CA6 |
| 3 | README: seção "API oficial do Mercado Livre" (etapa 0, autorizar, conferir, sondar, sair, as variáveis, o que fazer em cada saída e a renovação a cada 6 meses ou depois de 4 meses parado) | `README.md` | leitura do revisor | dev | B | não | CA10 |
| G1 | Portão: o dono roda `autorizar`, `conferir` e `sondar`. O lead grava os resultados de F0 a F6 neste plano e decide 4 e 5 | — | saída do `sondar` | dono + lead | — | — | — |
| 4 | Fonte `ml` no `atualizar_precos.py`: `ID_DA_LOJA['ml']`, `selecionar` com `CAMPOS`, `fonte_ml_api` (lotes de 20, pausa de 0,5 a 1,5 s, um rótulo `api\|<primeiro id>` por lote, só para log; a retomada vem do `preco_em` de hoje), subcomando `ml [--cat]`, `_rodar_ml` com as saídas do `ml_api`. Testes: a nota e as vendas do banco ficam, o `meli.la` fica, nada é inserido, inativo e usado não gravam, `Limite` dá 3 com o que já foi gravado mantido e falta de Secret com token vencido dá 2 | `atualizar_precos.py`, `testes/test_atualizar_precos_ml.py` | `python3 testes/test_atualizar_precos_ml.py -v`, `python3 testes/test_atualizar_precos.py` (só as 3 falhas de antes), `python3 testes/test_atualizar_precos_qa.py` | dev (opus) | C | sim (segredo, rede) | CA7, CA9 |
| 5 | `coletar_ml.py buscas --cat ABA [--ordens relevancia,caros]`, só depois de G1 e da P1, com o desenho fechado pelo arquiteto. Progresso `<ordem>\|<termo>`. Piso conforme a P1. `eh_usado` e `condition`. `item_id` `MLB<n>`, url de produto, foto só de `http2.mlstatic.com` (`D.imagem_permitida`). No fim: "N itens sem link de afiliado: rode ColetaML.afiliar()". Teste que amarra o `RE_USADO` ao da Amazon e ao do JS | `coletar_ml.py`, `testes/test_coletar_ml.py` | `python3 testes/test_coletar_ml.py -v`, `node --test testes/coletar_ml.test.mjs` (sem mudança) | dev (opus) | C | sim (rede, segredo) | CA8, CA9, CA11 |
| 6 | README: `atualizar_precos.py ml` e, se houver, `coletar_ml.py`, com tempos e a lembrança do `afiliar()` | `README.md` | leitura do revisor | dev | D | não | CA10 |

As etapas 4 e 5 não dividem arquivo e podem rodar em paralelo. A 5 é opcional. O CLAUDE.md fica com o lead depois da aprovação: camadas, segredos, verificação e as pastas proibidas ao `designer` (`ml_api.py` e `coletar_ml.py`).

### Conteúdo exato da etapa 0
`public_html/ml/callback/index.html`:
```html
<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer">
<meta name="robots" content="noindex, nofollow">
<title>Etiqueta: autorização do Mercado Livre</title>
<style>body{font-family:system-ui,sans-serif;max-width:36rem;margin:3rem auto;padding:0 1rem;line-height:1.5;color:#1a1a1a;background:#fff}code{background:#f2f2f2;padding:0 .3rem;border-radius:4px}</style>
</head>
<body>
<h1>Autorização recebida</h1>
<p>Copie o endereço <strong>inteiro</strong> desta página na barra do navegador (Ctrl+L e depois Ctrl+C) e cole no terminal onde o <code>python3 ml_api.py autorizar</code> está esperando.</p>
<p>O código vale uma vez só e por pouco tempo. Não mande este endereço para ninguém.</p>
<p>Se o endereço não tiver <code>code=</code>, a autorização não foi concluída. Rode o comando de novo.</p>
</body>
</html>
```
`public_html/ml/callback/.htaccess`:
```apache
# Retorno do OAuth do Mercado Livre (Etiqueta). Sem RewriteEngine aqui: anularia as regras da raiz.
Options -Indexes
DirectoryIndex index.html
<IfModule mod_headers.c>
  Header always set Cache-Control "no-store"
  Header always set Referrer-Policy "no-referrer"
  Header always set X-Robots-Tag "noindex, nofollow"
  Header always set Content-Security-Policy "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
</IfModule>
```
Sugestão: versionar os dois arquivos em `Lange_meninas/site/hostinger/ml/callback/`. Fica com o lead, fora deste repositório.

## Pontos para o seguranca
- **Secret:** é lido com `pop` uma vez, fica no `Segredo` e vai só no corpo `x-www-form-urlencoded` do `POST /oauth/token` ao host fixo. Nunca entra em URL, `argv`, saída ou mensagem. O `except Exception` imprime só o tipo.
- **Tokens:** confira a lista abaixo.
  - O modo é 0600 e a gravação usa `O_EXCL|O_NOFOLLOW`, `os.replace` e conferência de uid.
  - A leitura recusa modo aberto, em vez de só avisar como o `api_token.txt`.
  - O `repr` dos tokens é mascarado.
  - Verificação: `rg -n "ml_tokens|access_token|refresh_token" servidor.py index.html disparo.py api_ofertas.py genero.py` não acha nada, `git check-ignore`, `SELECT chave FROM config` sem chave do ML e um teste que procura um token falso no stdout, no stderr e em `str(exc)`.
- **Refresh de uso único:** o flock e a releitura dentro do lock valem para dois comandos ao mesmo tempo. O token novo é gravado antes de qualquer uso. Se o processo morrer entre a resposta e a gravação, o refresh se perde e é preciso refazer o `autorizar`, o que é aceitável.
- **Callback:** a página não tem JS, a CSP é `default-src 'none'` e o referrer não sai. O code fica no log da Hostinger e no histórico do navegador. Ele é de uso único e exige o verifier (só em memória) e o Secret: risco aceito, a levar ao dono. O `state` é conferido em tempo constante.
- **Endereço colado:** é entrada não confiável. O parse é estrito, nada vai para a URL da API além do `code` validado por regex, e o endereço não é ecoado.
- **Escopo mínimo:** a app fica só com leitura. O `conferir` avisa se aparecer `write`. Não usar `client_credentials`.
- **Saídas do `sondar`, do lote e da coleta:** só status, códigos, contagens, ids `MLB` e nomes de campo. Nada de corpo de resposta, título ou token.

## Riscos e como reverter
- **API fechada para afiliado (F1, F2 ou F3 com 403):** nada muda no fluxo atual. As etapas 4 e 5 não entram, e o ML continua no `ColetaML`. Para reverter, remova `ml_api.py` e o teste, e saem as linhas do `.gitignore`.
- **Preço da API diferente da vitrine (F4):** antes do primeiro lote, o lead faz `sqlite3 achadinhos.db ".backup backups/antes-ml-api.db"` e o dono compara 5 itens com a página. Para reverter, restaure o backup, sabendo que as atualizações feitas desde então se perdem. O link de afiliado nunca muda.
- **Refresh perdido, 4 meses parado, senha trocada, Secret renovado ou `invalid_grant` por dado pendente na conta:** refaça o `autorizar`, cerca de 2 min.
- **Secret vazado:** renove no DevCenter, o que invalida os tokens, e refaça o `autorizar`.
- **429 ou app bloqueada por volume:** pausas, lotes de 20, cerca de 191 chamadas por rodada completa e saída 3 com o progresso salvo.
- **Termos de uso do ML para uso de dados por afiliado:** não verifiquei.

## Perguntas em aberto e premissas adotadas
- **F0 a F6, a confirmar no G1:**
  - F0: a permissão "Publicação e sincronização" em leitura libera os endpoints de item com token de usuário.
  - F1: `/sites/MLB/search` com token. Provável 403.
  - F2: `/items/bulk` de terceiros. Há um relato de 403.
  - F3: `/products/search` e `/products/{id}/items`. Há um relato de 200, só para itens de catálogo.
  - F4: `price` e `original_price` batem com a vitrine.
  - F5: existe `sold_quantity` de terceiros e `/reviews/item` responde.
  - F6: formato do `/items/bulk` (`status_code`, `body.`).
- **P1.** A API não deve trazer "+50 vendidos". Que piso vale na coleta pela API?
  - (a) Nota ≥ 4,5 por `/reviews/item` e pelo menos N avaliações no lugar das vendas.
  - (b) Só itens do `/highlights` (top 20 por categoria, exige "Métricas do negócio").
  - (c) A coleta continua no console.
  - Premissa: (c) até a resposta. A atualização de preços não depende disso: herda o piso da coleta.
- **P2.** O dono aceita ativar "Publicação e sincronização" em somente leitura? Premissa: sim, porque sem ela a doc indica 403 em tudo.
- **P3.** Onde versionar a página de callback? Premissa: no `Lange_meninas`, pelo lead.
- **Premissas:**
  - Uma máquina e um usuário Linux.
  - Progresso por dia local.
  - Item inativo ou usado não é gravado nem apagado e envelhece, como hoje.
  - O título da API substitui o do banco. O polycard e o anúncio têm o mesmo título (não verificado).

## Decisões do dono (2026-11-05, registradas pelo lead)
- Plano aprovado; etapas 1 a 3 liberadas. As etapas 4 e 5 esperam o G1.
- P1: **(a)** nota ≥ 4,5 por `/reviews/item` e mínimo de avaliações (N a fixar na revisão da etapa 5; sugestão 50).
- P2: sim, "Publicação e sincronização" em somente leitura.
- P3: fica com o lead, no `Lange_meninas`.
- **Risco aceito pelo dono (05/11, depois do G1):** o `code` do OAuth passa pelo log de acesso da Hostinger e pelo histórico do navegador. Mitigações: uso único e curto, exige o verifier PKCE (só na memória do `autorizar`) e o Secret (só no ambiente do comando); página sem JS, CSP `default-src 'none'`, `no-store`, `no-referrer`. Volta como achado se a página ganhar JS ou se o verifier for para o disco.
- **Depois do G1 (05/11):** o dono pediu "a API funcionando" e autorizou o arquiteto a desenhar a rota do catálogo (F3) como revisão deste plano.

## Registro do G1 (lead, 2026-11-05, em andamento)
- Etapa 0 feita: página de callback no ar (CA1 verificado por curl) e app salva no DevCenter com Refresh Token, PKCE, "Publicação e sincronização" em Leitura ("A aplicação foi alterada corretamente").
- Fluxo OAuth provado até a troca do code: `state` confere, `POST /oauth/token` responde 200 com `access_token, expires_in, refresh_token, scope, token_type, user_id`. **Pendente:** `tokens_da_resposta` recusa a resposta real ("fora do formato"); diagnóstico por campo (`ACHADINHOS_ML_DIAG=1`, só tipo/tamanho/regex, nunca valor) pronto no `ml_api.py` para a próxima rodada do dono. Depois de ajustar a validação, o `dev` revisa o teste do formato e o lead segue para `conferir`/`sondar` (F0–F6).
- **G1 concluído (05/11, ~05:40).** Causa do "fora do formato": o `scope` real tem 339 caracteres com `urn:...:/read-only`; `RE_ESCOPO` passou a aceitar ASCII imprimível até 2048 (sem controle). `autorizar` → "OK: autorização gravada"; `conferir` → 200, escopos `offline_access read ... publish-sync:/read-only ... write` (o `write` vem de "Usuários", que o ML não deixa baixar, e de "Comunicações", a baixar para Leitura).
- **Resultado do `sondar` (F0–F6):**
  - F0 `/users/me`: **200**. A permissão "Publicação e sincronização" em leitura entrou no escopo (`publish-sync:/read-only`).
  - F1 `/sites/MLB/search?q=`: **403 forbidden**. Busca por termo fechada, como previsto.
  - F2 `/items/{id}` de terceiro: **403 access_denied**. Leitura de anúncio alheio por id fechada.
  - F6 `/items/bulk?ids=`: **200**, lista de 3 elementos só com `status_code` (sem `body` com os campos da allowlist): os elementos individuais são recusados, coerente com F2. Formato confirmado: lista com `status_code`/`body` por item.
  - F3 `/products/search?q=`: **200**, com `catalog_product_id` e `status` (só catálogo). `/products/{id}/items`: **404 not_found** para o primeiro id devolvido (não conclusivo: pode ser produto sem anúncio ativo).
  - F5 `/reviews/item/{id}`: **403 PolicyAgent** (exige outra permissão funcional).
- **Decisão pelo portão:** F2 ≠ 200 → **a etapa 4 não entra**; F1 ≠ 200 → **a etapa 5 não entra** como desenhada. O ML continua no console (`ColetaML`) para coleta, afiliação e preço. O que foi entregue (OAuth, tokens, cliente, `sondar`) fica pronto para tentar de novo se o ML abrir os endpoints, e serve de base para um desenho alternativo via catálogo (F3: `/products/search` + `/products/{id}` com `buy_box_winner`), que precisa de revisão do arquiteto porque não mapeia o anúncio do link de afiliado para o produto de catálogo sem o `/items/{id}`.
- Lição de uso: as instruções ao dono devem ter **um comando por bloco**; blocos com texto entre comandos foram colados inteiros no terminal e o `read -rs` engoliu texto como Secret (3 rodadas de `invalid_client` falsas). Secret real tem 32 caracteres.

## ADR
**ADR: API oficial do ML por CLI com tokens em arquivo local.**
- **Contexto:** a coleta pelo console é frágil, e a app "Etiqueta" pede OAuth com PKCE e um redirect público.
- **Decisão:** um módulo `ml_api.py` só com stdlib. O callback estático na Hostinger serve só para o dono copiar o endereço. Os tokens ficam num arquivo 0600 fora do git, com flock na renovação. O Secret fica só no ambiente do comando. O servidor e o site não sabem da API.
- **Consequências:** o dono roda comandos no terminal, como na Shopee, e refaz a autorização a cada 6 meses. O alcance real da API depende do G1, e o console continua como fallback e como único caminho do `meli.la`.
