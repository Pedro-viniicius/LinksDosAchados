---
name: ml-api-testes
description: Armadilhas do ml_api.py (API oficial do ML: OAuth/PKCE, tokens 0600 com flock) e de testes/test_ml_api.py (openers falsos, processos concorrentes, paridade com o JS, mutantes)
metadata:
  type: project
---

Vistas nas etapas 1 a 3 de api-oficial-ml (2026-11-05):

- `git check-ignore -q a b c` FALHA (exit 128, "--quiet is only valid with a single pathname"). Com vários caminhos, use sem `-q` (exit 0 e lista os 3) ou um `-q` por arquivo. O comando do plano/lead vem com `-q`: relate.
- `HTTPError` falso guarda o corpo num BytesIO: reusar o MESMO objeto em várias respostas faz a 2ª leitura vir vazia (código some). Crie um novo por chamada (no teste do sondar, `erros` guarda `(status, corpo)`).
- Default de argumento é ligado na definição: `entrada=input`, `relogio=time.time` não pegam `mock.patch('builtins.input')`. Use `None` e resolva na chamada (`(entrada or input)(...)`, `self.opener or OPENER`).
- Prova de concorrência com 2 subprocessos: script auxiliar (string no teste, gravado no tmp) troca `M.OPENER` por um falso cujo "servidor" vive num JSON com flock próprio e anota eventos (`pediu-trava`, `post-inicio`, `post-fim`). A condição certa é "o outro pediu a trava ANTES do `post-fim`" (muitas vezes os dois pedem antes do `post-inicio`); exigir `ini <= t <= fim` deu falso negativo em ~50% das rodadas. ATRASO de 1 s no POST basta.
- Reler dentro do lock em processo único: thread + `M.travar` segurado pelo teste + espião em `M.ler_tokens` (Event) e gravar o par novo antes de soltar.
- Paridade do `formatar_preco` com o JS: `node -e <script> coletar_ml.js` (no `-e`, o arquivo é `process.argv[1]`), valores pelo stdin em JSON. vm precisa de `location` da lista, `localStorage`, `fetch`, timers. `round()` do Python ≠ `Math.round` (empate e 0.49999999999999994): use floor + `x - floor(x) >= 0.5`.
- Mutantes: copie `ml_api.py`, `coletar_amazon.py`, `coletar_shopee.py`, `coletar_ml.js`, `servidor.py`, `index.html`, `disparo.py`, `api_ofertas.py`, `genero.py` e o teste (o teste lê esses fontes). O `test_gitignore` pula fora de um repo git. O script de mutantes tem de restaurar o original num `finally`: um `assert` no meio deixou um mutante na cópia e contaminou a rodada seguinte.
- Mutantes equivalentes conhecidos: tirar o `st_size >` do `ler_tokens` (o `len(bruto) >` ainda recusa). Os filtros de código de erro são em dobro (`_codigo_do_corpo` e `ErroApi`/`SemPermissao`): cada um tem teste direto.

Rodada 2 (2026-11-05):
- `getpass.getpass` lê do `/dev/tty` se o processo tiver terminal de controle, MESMO com stdin em pipe: os testes com subprocesso + `stdin=PIPE` travariam no terminal do dono. Por isso `ler_colado` usa getpass só com `sys.stdin.isatty()`; fora disso, `input()`. O `Cli.rodar` troca `M.sys.stdin` por um `TerminalFalso` (isatty True) e mocka `getpass.getpass`; `builtins.input` fica como AssertionError.
- Prova de "sem eco" de verdade: `pty.openpty()` + `Popen(stdin/stdout/stderr=escravo, start_new_session=True)`; sem terminal de controle o getpass cai no termios do stdin (o pty) e desliga o eco. Leia o mestre com `select` até EIO. Com `input()`, o endereço volta na tela.
- Para provar que a suíte não trava num terminal: `script -qec "python3 testes/test_ml_api.py" /dev/null </dev/null`.
- Mutante de laço infinito (401 sempre + renovar sem limite) trava o runner: o mutante certo do S3 é zerar `self._renovou_por_401` no começo do `get`. No script de mutantes, use `timeout=` no subprocess. NUNCA `pkill -f <nome do script>`: casa com o próprio bash da ferramenta e mata o comando (exit 144).
- Exceção nova que precisa passar nos `assertRaises(M.RespostaInvalida)` do qa: subclasse (`RenovacaoInvalida(RespostaInvalida)`, saída 2). Cuidado com quem captura a base: o `_sonda` engolia; tem `except RenovacaoInvalida: raise` antes.
- A tabela de saídas do README é lida pelo qa com `^\| ([0-3]) \|`: linha `| 130 |` não quebra.

Etapa 1 de api-oficial-ml-catalogo (`sondar --catalogo`, testes/test_ml_api_catalogo.py, 2026-11-05):
- `sqlite3.connect('file:...?mode=ro', uri=True)` num banco WAL SEM -wal/-shm (servidor parado) CRIA os dois (shm 32 KB, wal vazio) e eles ficam. O `ids_do_banco` já fazia isso. Teste "nenhum arquivo criado" só fecha byte a byte com o banco em uso (conexão aberta pelo teste, como o servidor no ar) ou em journal DELETE; o -shm muda de conteúdo com leitor (compare só o nome).
- `ml_api` não pode importar `servidor` (TestFronteiras): o parse de preço é porte (`M.ler_preco`) SEM re.A, amarrado ao `S.ler_preco` por teste (dígito árabe pega o re.A).
- MLFalso: ids de produto montados por f-string (`MLB{n}{j}{k}`) colidem entre cenários (item 9 x termo do F12): use prefixos distintos (`MLB770...`).
- O teste importa `test_ml_api as T` e subclassa `T.Cli`; `servidor` importado depois usa S.DB = TMP/banco-padrao.db, patch de `S.DB` + `S.criar_banco()` por teste.
- Pausa da sonda: `PAUSA_MIN/MAX` patcháveis (CLI) ou `dormir`/`aleatorio` no `sondar_catalogo` (direto).
- Script de mutantes: scratchpad `cat1/mutar.py` (copia ml_api, servidor, disparo, genero, api_ofertas, coletas, index.html, buscas.json e os 2 testes); 24 mutantes, todos mortos.
- `test_atualizar_precos_qa` falha 7 em `V1PrecoMaxHorasNosDadosReais` (lê o banco real; depende dos dados do dia), sem relação com o ml_api.

Rodada 2 da etapa 1 do catálogo (R1, R2, S1/R4, Q2, R3, R5, R6, R8, S3; 2026-11-05):
- Erro da renovação x erro do catálogo: o `_OpenerContado` guarda `ultimo` (método do último pedido) e `gets`. ErroApi saindo do `sessao.get` com `ultimo == 'POST'` veio do POST /oauth/token (vira `RenovacaoFalhou`, saída 2); com 'GET', veio do catálogo. `feitas` só sobe se `contado.gets` subiu (o mutante "sempre conta" só morre com o token vencendo NO MEIO: avance `self.agora[0]` dentro do responder).
- `sessao.token()` antes do cabeçalho tem de vir ANTES de trocar `sessao.opener`: senão um erro ali deixa o opener trocado (fora do try/finally).
- `_medir`: o `raise RefazerAutorizacao()` dentro do `except ErroApi` não é pego pelos outros `except` do mesmo try.
- Mutante equivalente: `p = None` antes do `for pid` no `_provar` (o bloqueio do produto sempre vem de uma leitura que já devolve None).
- R7 (fallback MLB1055 no F14) NÃO feito: o qa tem `test_categoria_e_produto_hostis...` exigindo "pulado (sem category_id)". R2 opcional (`/items` do 1º pai) também não: quebra `RESERVA_FINAIS == 33` e `gets[-3:]` do qa.
- Script de mutantes da rodada: scratchpad `mutar_r2.py` + cópia `cat1r2/` (20 mutantes; roda as duas suítes do catálogo).

Etapa 2 do catálogo (vínculo, ml_catalogo.json, ofertas; 2026-11-05):
- `_ler_privado(caminho, teto, recusar)` é a leitura estrita comum (tokens e vínculos) e `gravar_atomico` a escrita; o `test_gravacao_atomica...` do test_ml_api pega o 1º `os.open` que não é a pasta como o tmp: não abra nada antes dele.
- O teste do catálogo troca `M.CATALOGO` no import (o ml_api já veio importado pelo test_ml_api); o `Catalogo.direto` grava tokens, então espião "a sonda não grava" vai em `gravar_vinculos`, não em `gravar_atomico`.
- `_provar` devolve trinca `(via, oferta, pid)`; `_Medidas.negado`/`falha` separam 403 e erro passageiro (404 é resposta). `MLFalso.responder` trata `/products/search` antes de `outros`: para estragar a busca, troque `ml.op.responder` por um wrapper.
- Mutante equivalente: tirar o `RE_MLB.fullmatch(i)` do `_linhas_na_lista` (os ids já vêm validados). Script: scratchpad `e2mutar.py` (23 mutantes, 22 mortos).

Rodada 2 da etapa 2 (R1/S1, Q1, R2-R5; 2026-11-05):
- `RenovacaoFalhou` virou subclasse de `ErroApi` e sai do `Sessao.renovar` (o `test_ml_api_qa` exige `ErroApi` na renovação 500 e não é arquivo do dev). Quem captura `ErroApi` precisa de `except RenovacaoFalhou: raise` antes (o `_medir` tem); o `_sonda` do F0-F6 de propósito não tem (saída visível igual). O `_OpenerContado.ultimo` saiu (código morto).
- `vincular`/`_vincular`: inconclusivo sem prova sobe o erro (`raise erro` na busca, `raise m.falha` no fim); os testes do qa que esperavam `(None, None)` nesses casos passaram a `assertRaises`. `_linhas_na_lista`: página sem `paging.total` inteiro é `m.falha` (Q1); página vazia continua fim.
- Prova "antes falha" sem mexer no projeto: cópia em scratchpad `r2e2/copia/` com o trecho revertido por script.

Etapa 3 do catálogo (fonte `ml` do atualizar_precos.py, testes/test_atualizar_precos_ml.py; 2026-11-05):
- `test_ml_api_qa.py` `test_nenhum_modulo_do_servidor_ou_do_site_cita_o_ml_api`: o lead liberou `ml_api`/`ACHADINHOS_ML_SECRET` no `atualizar_precos.py`; `ml_tokens`/`ACHADINHOS_ML_TOKENS` continuam proibidos no fonte.
- `test_atualizar_precos.py` fixa `FONTES` exato e usava `['ml']` como argumento inválido. Essa suíte NÃO aponta `ACHADINHOS_ML_TOKENS` para tmp: nunca rode o subcomando `ml` nela (troquei por `['ml', '--vincular', '1001']`).
- A suíte nova importa `test_ml_api` e `test_ml_api_catalogo` (MLFalso) e fixa `ACHADINHOS_FEITOS_ATUALIZAR` antes de importar o `atualizar_precos`; por teste, patch de `S.DB`, `A.FEITOS`, `A.BUSCAS`, `M.CATALOGO`, `M.TOKENS` e embrulho do `M.sessao_do_ambiente` (relógio, dormir e aleatório falsos na Sessao real, que faz o pop do Secret).
- `T.Base.sessao()` passa o opener: o `com_teto` devolve o OpenerFalso, não `None` (só a Sessao do `sessao_do_ambiente` volta a `None`).
- Token vencendo no meio: o responder avança `self.agora[0]` quando `len(op.gets()) >= k` (o OpenerFalso anota antes de responder): k GETs e 1 POST.
- Mutantes: scratchpad `e3mutar.py` + cópia `e3mut/` (20 mutantes, todos mortos). Prova do 6a (`_sonda`) pela mesma cópia com o trecho revertido.

Rodada 2 da etapa 3 (reler antes de gravar, metade do teto; 2026-11-05):
- Com a parada na metade do teto, itens de busca vazia nunca chegam ao teto (saída 0). Para bater o teto no vínculo, um item que começa abaixo da metade tem de gastar o resto em candidatos: `buscas[...] = [pid1, pid2]`, 2 GETs por candidato. `--max-chamadas 1` dá metade 0: nada vincula.
- Escrita "no meio da rodada": `self.ml.op.responder = T.api_padrao(gets=...)` e um `UPDATE` por conexão própria ao pedir `/products/<pid>/items`. Prova da trava: no espião do upsert, outra conexão com `timeout=0` tem de levar `OperationalError`.
- `sanear_precos` zera `preco_antigo` quando ele é ≥ 5× o preço: nas fixtures, `original` abaixo disso, senão `preco_antigo` e `desconto` vêm vazios.
- Fonte falsa no `atualizar`: `mock.patch.dict(A.FONTES, ...)` com gerador (`raise e; yield`). O `test_atualizar_precos` precisa de `testes/fixtures/` na cópia de mutantes (FileNotFoundError no import, 0 FAIL no stderr). Script: scratchpad `mutar_r2e3.py` (32 mutantes, todos mortos).

Etapa 4 do catálogo (README, R6/R7; 2026-11-05):
- O `test_ml_api_qa.TestReadme` lê o README INTEIRO: toda linha com `ACHADINHOS_ML_SECRET=` precisa de `"$S"` e `unset S`, e `ml_api.py <palavra> ... secret|SECRET` (minúsculo/maiúsculo, sem crase no meio) na mesma linha reprova. Na prosa cite só `ACHADINHOS_ML_SECRET` sem `=`. A seção "## API oficial do Mercado Livre" vai até o próximo `## ` (um `###` novo dentro dela entra na checagem da tabela `| 0 |`; tabela de saídas do `atualizar_precos.py ml` fica em "Atualizar os preços").
- Conta do tempo: sonda real = 241 chamadas/239 s (~1 s cada), 4,8 chamadas por item (o lead falou 4,4); `ofertas_do_produto` custa 1 a 4 chamadas (produto + até 3 páginas), lote de 20 produtos = 40 a 80 (a razão do "mínimo 40").

**How to apply:** nas etapas 4 e 5 (fonte `ml` do `atualizar_precos.py`, `coletar_ml.py`), que usam `Sessao`/exceções do `ml_api`. Relacionado: [[coletar-shopee-testes]], [[servidor-testes]].
