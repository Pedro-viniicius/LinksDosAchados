# Plano técnico: blindar o servidor local (achados S1 e S2)
- Brief: não há. O pedido do lead de 2026-11-03 faz o papel dele (achados S1 e S2 do `seguranca`, na revisão "copiar imagem").
- Data: 2026-11-03

## Objetivo e critérios de aceite
Fechar o `servidor.py` para sites de fora sem quebrar o front, a coleta do Mercado Livre no Chrome, o `coletar_amazon.py` e a suíte atual. Não muda dado, esquema nem regra de afiliado.

- CA1: requisição com `Host` diferente de `localhost:<PORTA>` e de `127.0.0.1:<PORTA>` recebe 403 em qualquer rota e método. É a defesa contra DNS rebinding.
- CA2: o estático serve só `/`, `/index.html` e `/testes/<nome>.test.html`. O resto dá 404 em GET e em HEAD, sem listar pasta: `/servidor.py`, `/achadinhos.db`, `/WhatsApp%20Chat%20-%20AmazonLinks/_chat.txt`, `/servidor.log`, `/.claude/…`, `/.git/…`, `/testes/rodar.mjs` e `/testes/`.
- CA3: nenhuma resposta leva `Access-Control-Allow-Origin: *`. O CORS só existe em `/api/`, só para origens do ML na allowlist, e devolve a própria origem com `Vary: Origin`. `Access-Control-Allow-Private-Network: true` só vai no preflight dessas origens, e só quando o Chrome pede.
- CA4: em `/api/`, uma `Origin` fora da allowlist (inclusive `null`) recebe 403 sem efeito. Sem `Origin`, um `Sec-Fetch-Site` igual a `cross-site` ou `same-site` também recebe 403. As origens do ML só podem usar GET, POST e PATCH em `/api/items`, `/api/items/<id>` e `/api/ml-sem-afiliado`. O resto (DELETE, PUT de config, `/api/fetch`) dá 403.
- CA5: POST, PATCH ou PUT sem `Content-Type: application/json` recebe 415, e JSON inválido recebe 400. Nos dois casos nada é gravado.
- CA6: um POST `/api/items` com `loja` fora de `amazon`/`ml` recebe 400 e não grava nenhum item do lote. Sem `loja`, continua valendo `amazon`.
- CA7: um PATCH `/api/items/<id>` com `url` que não é de afiliado (`https://meli.la/…` ou `tag=desejodemen01-20`) recebe 400 e não grava. *Proposta do arquiteto; veja P1.*
- CA8: `/api/fetch` só aceita `https` nos hosts `www.amazon.com.br`, `amazon.com.br` e `amzn.to`, tanto na URL pedida quanto em cada redirect. Fora disso responde 400 com `{"error": …}`, sem acessar a rede.
- CA9: os fluxos atuais continuam funcionando:
  - o `index.html` aberto em `localhost` ou em `127.0.0.1` lê e grava;
  - a coleta do ML faz o preflight e o POST a partir de `https://lista.mercadolivre.com.br`, e faz GET de `ml-sem-afiliado` mais PATCH a partir de `https://www.mercadolivre.com.br`;
  - o `coletar_amazon.py` importa e grava como hoje;
  - `node testes/rodar.mjs copiar-imagem` continua em 72/72.
- CA10: `ACHADINHOS_DB` e `ACHADINHOS_PORTA` definem o banco e a porta, e sem elas o padrão fica igual ao de hoje. Nenhum teste toca o `achadinhos.db` real nem o servidor em 8765.

## Contexto atual
- CORS aberto em toda resposta, inclusive no estático: `servidor.py:123-129`. O preflight responde 204 a qualquer origem em `servidor.py:142-143`.
- O estático serve a pasta `BASE` inteira (`servidor.py:117` com `directory=BASE`, e o fallback em `servidor.py:172`). O `do_HEAD` herdado também serve tudo, porque não foi sobrescrito.
- `corpo()` faz `json.loads` sem olhar o `Content-Type` (`servidor.py:138-140`). `loja` é livre em `servidor.py:61`. O PATCH grava `url` sem validar (`servidor.py:193-195`).
- `/api/fetch` faz `urlopen` de qualquer URL (`servidor.py:90-96`, `165-169`). Só o front usa essa rota, e só em itens da Amazon (`index.html:244`, botão em `index.html:356`). Hoje as 2.625 `url` da Amazon são `https://www.amazon.com.br` e as 2.704 do ML são `https://meli.la` (consulta só de leitura no banco).
- Constantes `DB` e `PORT` em `servidor.py:12-13`; o bind é só em `127.0.0.1` (`servidor.py:225`).
- **`coletar_amazon.py` não usa HTTP**: faz `import servidor as S` (`coletar_amazon.py:9`) e grava com `S.conectar()` e `S.upsert()` (`coletar_amazon.py:75-77`). O guard não o afeta; a validação de `loja` só o afetaria se ele mandasse `loja` inválida, e ele não manda `loja` nenhuma.
- O front chama a API sempre na mesma origem e com `Content-Type: application/json`, até no DELETE (`index.html:212`). Não precisa mudar.
- O fluxo do ML a partir do `servidor.log`: 702 PATCH `/api/items/<id>`, cada um com OPTIONS antes (ou seja, cross-origin), e GET `/api/ml-sem-afiliado`. O log não grava `Origin`. Pela memória do lead, os links de afiliado saem de `https://www.mercadolivre.com.br/afiliados/linkbuilder` e a coleta roda em `https://lista.mercadolivre.com.br`. **Não verificado:** a origem exata do PATCH e o `Content-Type` do POST que o script da coleta usa.
- O Chrome instalado é o 156. A Local Network Access já pede permissão do usuário quando um site público acessa o loopback, e o header PNA (`Access-Control-Allow-Private-Network`) está obsoleto ([guia LNA](https://developer.chrome.com/docs/modern-web-guidance/guides/security/local-network-access)). Isso reduz o risco, mas não substitui a checagem no servidor.
- Testes: `testes/copiar-imagem.test.html:748-753` lê `/servidor.py` pelo estático (CA6 do plano copiar-imagem: "sem rota de proxy"). O runner fixa a porta 8765 em `testes/rodar.mjs:13`. A página só faz GET na API (é ela que bloqueia as escritas, em `testes/copiar-imagem.test.html:100-103`).
- Não existem `docs/produto/decisoes.md` nem teste de Python.

## Abordagens consideradas
| Abordagem | Prós | Contras | Risco |
|---|---|---|---|
| A. Allowlist no handler: Host, Origin/Sec-Fetch-Site, CORS por origem, estático por lista | Uma mudança num arquivo só; não move nada; o front não muda | A lista de origens do ML fica no código | Origem do ML esquecida quebra a coleta (fácil de ver: 403) |
| B. A + token secreto no header das escritas | Barra também um script malicioso numa página do ML | O script da coleta precisa obter o token; mais peças | Alto custo para um uso local de uma pessoa |
| C. Mover o estático para `publico/` | Estático seguro por construção | Move `index.html` e `testes/`, muda URLs, runner, CLAUDE.md e histórico | Quebra a suíte e os hábitos do dono |

**Decisão: A.** B é excesso para o caso (fica como pergunta P3). C resolve só o CA2 e custa mais que uma regex.

## Decisão
Tudo em `servidor.py`, com a biblioteca padrão:
1. **Config por ambiente:** `DB = os.environ.get('ACHADINHOS_DB') or os.path.join(BASE,'achadinhos.db')` e `PORT = int(os.environ.get('ACHADINHOS_PORTA') or 8765)`. Isso vale também para o `coletar_amazon.py`, que lê `S.DB`.
2. **Constantes novas:** `ORIGENS_ML = ('https://lista.mercadolivre.com.br', 'https://www.mercadolivre.com.br')`, `HOSTS_AMAZON = ('www.amazon.com.br', 'amazon.com.br', 'amzn.to')` e `LOJAS = ('amazon', 'ml')`. As origens locais e os hosts aceitos derivam de `PORT`: `localhost:<PORT>` e `127.0.0.1:<PORT>`, com `http://` na frente para Origin.
3. **Guarda única** `bloquear()`, chamada no início de todo `do_GET/HEAD/POST/PATCH/PUT/DELETE/OPTIONS`. Ela responde e devolve `True` quando recusa:
   - Host (em minúsculas) fora da lista → 403;
   - em `/api/`, Origin local → passa;
   - Origin ∈ `ORIGENS_ML` → passa só se o método (no OPTIONS, o `Access-Control-Request-Method`) estiver em GET/POST/PATCH e o caminho casar com `^/api/(items(/\d+)?|ml-sem-afiliado)$`;
   - qualquer outra Origin → 403;
   - sem Origin, `Sec-Fetch-Site` em `cross-site`/`same-site` → 403.
   - A comparação é exata, sem `startswith` nem `endswith`.
4. **CORS:** o `end_headers` manda sempre `Cache-Control: no-store`. As linhas de CORS só entram quando a guarda aprovou uma origem do ML: `Access-Control-Allow-Origin: <origem>` e `Vary: Origin`. No OPTIONS entram também `…-Allow-Methods: GET, POST, PATCH` e `…-Allow-Headers: Content-Type`, mais `…-Allow-Private-Network: true` só se veio `Access-Control-Request-Private-Network`. Origem local não recebe CORS, porque não precisa.
5. **Estático por lista**, conferida no caminho cru (`urlparse(self.path).path`) antes do `translate_path`: `/`, `/index.html` e `^/testes/[a-z0-9-]+\.test\.html$`. O resto vira `self.json({'error':'não encontrado'},404)`. O `do_HEAD` usa a mesma regra; em `/api/` responde 405.
6. **Escrita:** `corpo()` exige `self.headers.get_content_type() == 'application/json'` (senão 415) e troca `JSONDecodeError` por 400. POST, PATCH e PUT passam por ele. O DELETE não tem corpo e fica protegido pela guarda, já que nenhum formulário consegue mandar DELETE.
7. **`loja`:** o `upsert` lança `ValueError` se a `loja` vier informada e não estiver em `LOJAS`. O POST valida o lote inteiro antes do primeiro `upsert` (400 com o índice do item) ou dá rollback. A regra de nunca trocar link de afiliado (`servidor.py:70-72`) não muda.
8. **PATCH `url`** (CA7, se P1 for aprovada): aceita só `https://meli.la/…`, ou `https://www.amazon.com.br/…` contendo `tag=desejodemen01-20`. Senão, 400.
9. **`/api/fetch`:** `buscar_produto_amazon` confere o esquema `https` e o host em `HOSTS_AMAZON`, e usa um `HTTPRedirectHandler` próprio cujo `redirect_request` recusa destino fora da lista. Erro de validação: 400 com `{"error": …}`, que o front já mostra (`index.html:245`).
10. **Testes do servidor:** `testes/test_servidor.py` em `unittest`. Cada classe sobe `python3 -u servidor.py` como subprocesso, com `ACHADINHOS_DB` num diretório temporário (banco novo e vazio, criado por `criar_banco()`) e `ACHADINHOS_PORTA` livre. Os dados entram por POST da origem local, e `http.client` monta Host, Origin e Sec-Fetch-Site à mão. Nenhum teste acessa Amazon ou ML.

## Esquema e contratos
- Sem migração nem mudança de tabela.
- Variáveis novas: `ACHADINHOS_DB` (caminho do banco) e `ACHADINHOS_PORTA` (porta). No runner, `PORTA` (padrão 8765).
- Códigos novos da API: 403 para Host ou origem recusados, 404 para estático fora da lista, 405 para HEAD em `/api/`, 415 para Content-Type errado, 400 para JSON inválido, `loja` inválida, `url` sem afiliado ou URL do `/api/fetch` fora da lista. Todos com corpo `{"error": "..."}`.
- **Contrato para o script da coleta do ML** (o lead atualiza a memória dele): POST/PATCH com `Content-Type: application/json`, a partir de `lista.` ou de `www.mercadolivre.com.br`.

## Etapas
| # | Etapa | Arquivos | Verificação | Responsável | Grupo | Sensível | CAs |
|---|---|---|---|---|---|---|---|
| 1 | `DB` e `PORT` por ambiente. Esqueleto de `test_servidor.py` (subprocesso, banco temporário, porta livre). Testes da linha de base: GET `/api/items` 200; POST local insere; `coletar_amazon` importa com `S.DB` apontando para o temporário; a primeira linha do stdout mostra o banco temporário. Mais a checagem do CA6 antigo, portada do `.test.html`: as rotas `/api/…` do fonte e "sem proxy de imagem" | `servidor.py`, `testes/test_servidor.py` | `python3 -m py_compile servidor.py coletar_amazon.py && python3 testes/test_servidor.py -v` | dev | A | sim | CA10, CA9 |
| 2 | Guarda de Host e Origin/Sec-Fetch-Site, CORS por allowlist, estático por lista e `do_HEAD`. Testes de cada caso do CA1 a CA4: Host `evil.com:<p>`; Origin `https://evil.com`, `null` e `https://lista.mercadolivre.com.br.evil.com`; preflight do ML com e sem PNA; DELETE vindo do ML; os 404 do CA2 em GET e HEAD; nenhum `*` em resposta nenhuma | `servidor.py`, `testes/test_servidor.py` | idem etapa 1 | dev | B | sim | CA1, CA2, CA3, CA4, CA9 |
| 3 | Página de teste: o teste do CA6 em `copiar-imagem.test.html:748-753` passa a afirmar que `/servidor.py`, `/achadinhos.db` e `/servidor.log` dão 404 (só o status, sem ler o corpo). O total continua em 72. O runner aceita `PORTA` no ambiente (`testes/rodar.mjs:13`) | `testes/copiar-imagem.test.html`, `testes/rodar.mjs` | depois da etapa 2: servidor de teste em 8766 (veja "Como provar") e `PORTA=8766 node testes/rodar.mjs copiar-imagem` → 72/72 | dev | B | não | CA2, CA9 |
| 4 | Escrita: `corpo()` com 415/400, `loja` validada no lote, PATCH `url` só de afiliado. Testes: `text/plain` no POST, PATCH e PUT; JSON quebrado; `loja:"x"` em lote misto sem gravar nada (conferido com GET); PATCH com `https://www.mercadolivre.com.br/x` → 400 e com `https://meli.la/abc` → 200; upsert continua sem trocar link de afiliado | `servidor.py`, `testes/test_servidor.py` | idem etapa 1 | dev | C | sim | CA5, CA6, CA7, CA9 |
| 5 | `/api/fetch` com allowlist e handler de redirect. Testes só de recusa, sem rede: `file:///etc/passwd`, `http://www.amazon.com.br/dp/X`, `https://127.0.0.1:<p>/`, `https://evil.com` → 400. Teste unitário do handler de redirect, com o subprocesso importando `servidor` e chamando `redirect_request` com um destino fora da lista | `servidor.py`, `testes/test_servidor.py` | idem etapa 1 | dev | D | sim | CA8 |
| 6 | Docs: em "Verificação" do `CLAUDE.md`, entram `python3 testes/test_servidor.py -v`, as duas variáveis e o contrato da coleta do ML; atualizar a memória do lead ("localhost aceita CORS" → allowlist e JSON) | `CLAUDE.md` | leitura | lead | E | não | CA9, CA10 |

As etapas 2 e 3 ficam no mesmo grupo porque não têm arquivo em comum, mas a verificação da 3 só vale depois da 2. Até o dono reiniciar o servidor real, a suíte rodada contra a porta 8765 (código antigo) falha no teste do CA6; isso é esperado. As etapas 1, 2, 4 e 5 mexem no mesmo par de arquivos e por isso vão em sequência.

### Como provar sem tocar no banco real (qa)
- **Automático:** `python3 testes/test_servidor.py -v` usa banco novo em diretório temporário e porta livre. O servidor real em 8765 não é tocado.
- **Suíte do front com o código novo:**
  ```
  python3 -c "import sqlite3; s=sqlite3.connect('file:achadinhos.db?mode=ro',uri=True); s.backup(sqlite3.connect('<scratchpad>/copia.db'))"
  ACHADINHOS_DB=<scratchpad>/copia.db ACHADINHOS_PORTA=8766 python3 servidor.py &   # guarde o $!
  PORTA=8766 node testes/rodar.mjs copiar-imagem
  ```
  Não use 8799, que já está em uso no scratchpad, e mate só o próprio PID. Use `backup` em vez de `cp`, porque o banco está em WAL e o servidor real está no ar.
- **Fluxo do ML, manual pelo dono, no Chrome de sempre, sem coletar:**
  1. Suba o servidor de teste em 8766 com a cópia, como acima.
  2. Numa aba qualquer de `https://lista.mercadolivre.com.br`, no console do DevTools: `fetch('http://localhost:8766/api/items',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({items:[{loja:'ml',item_id:'MLBTESTE1',url:'https://meli.la/teste',cat:'Teste'}]})}).then(r=>r.json())` → `{inserido:1,…}`.
  3. Em `https://www.mercadolivre.com.br/afiliados/linkbuilder`: `fetch('http://localhost:8766/api/ml-sem-afiliado').then(r=>r.json())` responde, e um PATCH em `/api/items/<id do teste>` com `{url:'https://meli.la/teste2'}` dá 200.
  4. Em `https://example.com`, o mesmo POST falha com erro de CORS e aparece 403 no terminal do servidor. Se o Chrome mostrar o pedido de "rede local", permita, para testar o servidor e não só o navegador.
  5. Ctrl+C e apague a cópia (`copia.db*`).
- **Depois da aprovação**, o dono reinicia o servidor real (`python3 servidor.py`) para carregar o código novo.

## Pontos para o seguranca
- A comparação de Host e de Origin é exata e em minúsculas. `https://lista.mercadolivre.com.br.evil.com` e `http://localhost:8765.evil.com` não podem passar.
- O estático é decidido pelo caminho cru, antes de qualquer decodificação. `%2e`, `..` e `//` não podem escapar da regex. O HEAD segue a mesma regra, e não sobra listagem de pasta.
- Nenhum caminho de código manda `*`. A PNA só aparece no preflight aprovado. `Vary: Origin` está presente.
- `Sec-Fetch-Site` sem `Origin` em `/api/` fecha o GET cego (`<img src=…/api/fetch?url=…>`).
- Risco que sobra: um script malicioso numa página do ML, ou uma extensão, ainda consegue POST e PATCH. Isso fica limitado por CA6, CA7 e pela permissão de rede local do Chrome. O token (P3) fecharia, mas foi descartado por custo.
- `/api/fetch`: o redirect é conferido antes de ser seguido, não só no `geturl()` final.
- O harness de teste não pode cair no `achadinhos.db` real (o teste da etapa 1 confere o caminho impresso) e nunca acessa Amazon nem ML.
- O `_chat.txt` deixa de ser servido. O teste checa só o status, sem ler o conteúdo.

## Riscos e como reverter
| Risco | Sinal | Como reverter ou corrigir |
|---|---|---|
| A coleta do ML usa outra origem (ex.: `produto.mercadolivre.com.br`) | 403 no terminal e erro de CORS no console | Acrescentar a origem em `ORIGENS_ML` (uma linha) |
| O script do ML manda `text/plain` | 415 | Mandar `Content-Type: application/json` (contrato acima) |
| Um item com link que não é de afiliado precisa de PATCH legítimo | 400 no PATCH | Gerar o link de afiliado antes; se P1 for recusada, tirar a parte de PATCH `url` da etapa 4 |
| O dono abre o site por outro host (ex.: IP da LAN) | 403 | Não se aplica hoje: o bind é só em `127.0.0.1` |
| Regressão geral | qualquer fluxo quebrado | `git checkout fcfcff8 -- servidor.py testes/` e reiniciar o servidor. Sem migração, sem dado alterado |

## Perguntas em aberto e premissas adotadas
- **P1 (dono):** o PATCH deve recusar `url` que não é de afiliado (CA7)? Recomendo sim, porque fecha o impacto citado no S1. *Premissa:* sim. Se for não, a etapa 4 perde essa parte.
- **P2 (lead):** confirmar as origens reais do script do ML. *Premissa:* `lista.` e `www.mercadolivre.com.br`, pelo log e pela memória do lead; não verificado.
- **P3 (dono):** token nas escritas (abordagem B)? *Premissa:* não.
- **Premissa:** `amzn.to` fica no `/api/fetch` porque o `saveLinks` aceita qualquer link (`index.html:415-416`), embora hoje não haja nenhum no banco.
- **Fora de escopo, para registro:** o `saveLinks` grava link comum sem afiliado (`index.html:416`). É regra de produto, não deste plano.

## ADR
**ADR 1: a API local aceita só a própria origem e uma allowlist do ML.** Contexto: S1 e S2. Decisão: guarda de Host, Origin e Sec-Fetch-Site, mais estático por lista, no próprio `servidor.py`. Consequência: toda origem nova de automação precisa entrar em `ORIGENS_ML`. Os scripts mandam JSON.

**ADR 2: testes do servidor em `unittest` com subprocesso.** `testes/test_servidor.py` sobe o `servidor.py` real com `ACHADINHOS_DB` e `ACHADINHOS_PORTA`, num banco temporário e numa porta livre. Por quê: só biblioteca padrão; testa o processo de verdade; nunca toca dado real. Isso complementa os `testes/*.test.html` do front.
