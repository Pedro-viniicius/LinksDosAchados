---
name: testes-ml-api
description: QA do ml_api.py e da fonte ml do atualizar_precos: arquivos _qa, como rodar, harness de mutantes, concorrência com servidor de verdade, riscos aceitos
metadata:
  type: project
---

**Arquivo (2026-11-05, rodada 1):** `testes/test_ml_api_qa.py` (30 testes). Rodar:
`http_proxy=http://127.0.0.1:9 https_proxy=http://127.0.0.1:9 python3 testes/test_ml_api_qa.py -v` (~4 s).
Importa `test_ml_api as T` (fixa proxies, ACHADINHOS_ML_TOKENS/DB em /tmp/teste-ml-api-*) e reusa
`T.Cli.rodar`, `T.Base.sessao`, `T.OpenerFalso`, `T.api_padrao`, `T.AUXILIAR` (script de subprocesso com
"servidor do ML" em JSON + flock), `T.sem_marcadores`. Meu `tearDownModule` chama `T.tearDownModule`.

**Como testar o difícil:**
- Socket de verdade com `M.OPENER`: `mock.patch.dict(os.environ, {'no_proxy': '127.0.0.1'})` (o ProxyHandler
  lê no_proxy na hora do pedido) + `M._abrir(M.OPENER, Request(local))`. Corpo em chunks tem de ser JSON
  VÁLIDO, senão o mutante do teto sobrevive (recusa por JSON e não pelo tamanho).
- 401 concorrente: estado do AUXILIAR com `acessos: []` e token no arquivo válido pelo relógio.
- argv: `/proc/<pid>/cmdline` enquanto o `autorizar` espera no input().
- Sobra de escrita atômica: subprocesso troca `M.os.replace` por `os.kill(getpid(), SIGKILL)`; o script
  tem de ficar FORA da pasta dos tokens (ele contém o marcador).
- O servidor real da 8765 (do dono) fica no ar: não confundir com o meu (`sys.executable <RAIZ>/servidor.py`).

**Mutantes (espelho no scratchpad com ml_api.py, README, servidor/disparo/genero/api_ofertas/atualizar_precos,
coletar_*.py, coletar_ml.js, buscas.json, index.html, testes/test_ml_api*.py; git e banco real dão skip):**
9/9 mortos (sem releitura no lock, trava presa em exceção, opener que segue redirect, Secret na URL, eco do
endereço, teto frouxo, Bearer no POST, state não conferido, gravar depois do GET). Na M2, mudar só o
`os.close` não prende a trava (o LOCK_UN no finally solta): tire o finally também.

**Achados da rodada 1 (ml_api):** Q1 (sobra `.ml_tokens.json.*.tmp` no .gitignore) CORRIGIDO: o padrão está no
.gitignore e o test_ml_api_qa dá 30 OK (conferido em 2026-11-05).

## sondar --catalogo (plano api-oficial-ml-catalogo, etapa 1) — rodada 1, 2026-11-05
Arquivo `testes/test_ml_api_catalogo_qa.py` (57 testes, ~1,2 s). Importa `test_ml_api_catalogo as C` (que importa o
test_ml_api) e reusa `C.Catalogo` (banco temporário, `self.direto(ml, amostra=…, teto=…, agora=…, buscas=…)`,
`self.rodar_cat(argv, ml, secret=)`), `C.MLFalso` (buscas/produtos/listas/erros por prefixo/outros), `C.prod`,
`C.linha_lista`. Para trocar a resposta de um caminho: `ml.op.responder = T.api_padrao(gets=f)` com `f` chamando
`ml.responder` (cuidado: `ml.erros['/products/MLB11']` casa também `/products/MLB11/items`).
- `sondar` antigo: carrega `git show 34d80cf:ml_api.py` num módulo `ml_api_34d80cf` (importlib) e compara
  (código, out, err, chamadas) com o novo; espelho sem git dá skip na classe.
- Servidor real: `servidor.py` abre conexão por pedido, então parado o banco WAL fica sem -wal/-shm; o `mode=ro`
  da sonda os cria e eles ficam. Q1 virou RISCO ACEITO (CA1 reescrito): o teste agora só aceita `<db>-wal` vazio e
  `<db>-shm` como novos, e o .db igual byte a byte; outro teste confere `git check-ignore` dos dois.
- Q2 CORRIGIDO na rodada 2 (receita repete `sondar --catalogo [--amostra N] [--semente S]`).
- Mutantes: harness em scratchpad (espelho com *.py, buscas.json e os 3 testes); 30 mutantes, todos mortos pela
  soma das duas suítes (4 só pela do dev: teto de ids por linha, moeda, pausa, dedup). `int` `True` passa no
  `isinstance(amostra, int)` (inofensivo, a CLI só dá int).
- Armadilha: 99.995 em float arredonda para 99,99 (use 99.996); ao apagar o banco entre iterações, apague também
  -wal/-shm (o mode=ro os deixa).

## Rodada 2 (2026-11-05): APROVADO, 67 testes no _qa
Classe `TestRodada2Qa`: corte do teto exatamente na última chamada do item (conta) e antes da 2ª página do /items
(não conta), 429 no /items do 2º item, 404 com/sem código + produto 403 comum/fora do formato (F9 "404: N (...)"),
q com 199/200/201 depois do NFKD (`'ﬃ'*67` vira 201), RenovacaoFalhou no meio do F12 (relógio falso e 401+500 pela
CLI; o bloco F12 não sai, só o da amostra uma vez), só é pai quem tem children_ids lista não vazia, stdout vazio
com tokens vencidos/invalid_grant/ilegíveis. Contas: as 3 tentativas do 429 contam 1 chamada; erro HTTP criado e não
usado gera ResourceWarning (crie só quando for devolver). Rode com `TMPDIR=<scratchpad>/tmpqa` para as pastas
temporárias do test_ml_api caírem no scratchpad. Mutantes (espelho no scratchpad): 6/6 mortos pelo _qa, 5 deles
vivos só com a suíte do dev (404 só not_found, corte antes do NFKD, F12 engole RenovacaoFalhou, [] é pai, 403
comum bloqueia o produto). `ml_tokens.json` real existe na raiz: nunca ler.

## Etapa 2 (vínculo com prova, ml_catalogo.json, ofertas_do_produto) — rodada 1, 2026-11-05
`test_ml_api_catalogo_qa.py` foi a 119 testes (52 novos, ~7,5 s; 3 s são o teste que roda as outras 3 suítes em
subprocesso sem ACHADINHOS_ML_CATALOGO e compara a raiz). Classe base `QaVinculo(T.Base)`: MLFalso com
`self.trocas[(caminho, offset_texto)]` → dict/list/tupla de erro/callable (troca uma resposta num ponto exato:
busca, produto, página 1/2/3 da lista). `tres_paginas(pid, pagina_do_item, linhas=50, paginas=N)`.
Arquivo: herde `C.Vinculos` (self.arq, escrever, recusado). Guarda no `tearDownModule`: snapshot (nome, inode,
mtime) do ml_catalogo.json/.ml_catalogo.json.*.tmp da raiz no import x no fim.
- Difícil: symlink trocado entre lstat e open = patch de `M.os.lstat` devolvendo o stat de um arquivo bom (O_NOFOLLOW
  recusa); arquivo que cresce = patch de `M.os.fstat` com `os.stat_result` de st_size 100; dono diferente de verdade
  = `/etc/passwd` (o uid é conferido antes do modo); SIGKILL no os.replace por subprocesso `-I`, script fora da pasta.
- `test_ml_api.py` sozinho deixa `M.CATALOGO` na raiz (só o test_ml_api_catalogo troca): risco de higiene anotado.
- Q1 (baixa, aberto): lista sem `paging.total` inteiro para na 1ª página e conta "não" conclusivo (negativo de
  7 dias no vincular; None/indisponível nas ofertas). 2 testes `test_q1_*` ficam vermelhos (7 falhas com subtests).
- Mutantes (espelho precisa também de index.html, coletar_ml.js e README.md, senão o test_ml_api quebra): 16/16
  mortos pelo _qa; 8 vivos só com a suíte do dev (PAGINAS 4, sem O_NOFOLLOW, lê st_size, except Exception, um write
  só, sem fchmod com umask 0o277, contexto do JSONDecodeError, os.open dentro do try apagando symlink alheio).
  Compare NOMES de teste com a base (o _qa tem as falhas do Q1), não contagens.
- Armadilha: 2028 é bissexto (23/02 → 01/03 = 7 dias).

## Etapa 2 — rodada 2, 2026-11-05: APROVADO, 122 testes no _qa
Q1 CORRIGIDO (`_linhas_na_lista`: página não vazia sem o item e sem `paging.total` inteiro → m.falha
RespostaInvalida; total inteiro <= lido é fim). R1: `vincular` agora LEVANTA o inconclusivo (ErroApi/RespostaInvalida,
que não são subclasses uma da outra) em vez de (None, None); o dev trocou 4 asserts meus por assertRaises e manteve o
`vinculos` conferido. Classe nova `TestQ1Rodada2Qa` (3 testes): total 0/1/49/50 é fim (1 GET, negativo anotado,
ofertas None), total negativo/enorme sem laço, Q1 na 2ª página sobe e item achado antes do total vale.
- RenovacaoFalhou em vincular com 1 POST e 0 GET já está na suíte do dev (test_ml_api_catalogo.py), não dupliquei.
- Observação (baixa, não aceita na rodada 2): total NEGATIVO conta como "menor que o lido" → fim e negativo de 7 dias.
- Mutantes: 6/6 mortos. ARMADILHA: mutante do mesmo tamanho gravado no mesmo segundo reusa o .pyc velho (mtime+size);
  rode com PYTHONDONTWRITEBYTECODE=1 ou apague __pycache__ a cada mutante.

## Etapa 3 (atualizar_precos.py ml, fonte_ml_catalogo) — rodada 1, 2026-11-05
Arquivo `testes/test_atualizar_precos_ml_qa.py` (43 testes, ~0,3 s). Importa `test_atualizar_precos_ml as TM` e herda
`TM.Base` (banco/tokens/vínculos/buscas/progresso por teste, `inserir`, `no_catalogo`, `no_cache`, `rodar`, espião de
upsert). Meus helpers: `retrato()` = `quote(col)` de todas as colunas (separa NULL de ''), `resto_do_banco()` (config,
outras tabelas, sqlite_sequence, esquema, user_version), `responder_com(antes_do_get(c, n_get), token=)`,
`a_partir_da_vez(caminho, vez, resp)` (o 429 é tentado 3x: use ">= vez", não "== vez"), `conferir_saida` (lista
FECHADA de regex por linha de stdout/stderr). Guarda no tearDownModule: ml_catalogo.json da raiz e sha do
atualizar_precos_feitos.txt real.
- Contas úteis: vínculo novo com bbw nulo = 3 GETs (busca, produto, lista); oferta = 2 GETs por produto; lote = 20
  produtos (o 1º lote são os GETs 1–40). `/products/<pid>` é lido na prova E nas ofertas.
- Q1 (baixa, aberto, test_q1_coluna_nula_do_banco_continua_nula vermelho): coluna NULL em CAMPOS vira ''. A causa é o
  `d.get(c) or ''` do servidor.upsert (mutante que manda None continua falhando), e o CA8 proíbe mexer no servidor.py.
  Banco real: 0 NULL nos CAMPOS do ML (conferido com immutable=1).
- Mutantes: harness `scratchpad/mut/mut.py` (espelho em mkdtemp, PYTHONDONTWRITEBYTECODE=1, roda o _qa e o do dev);
  30/30 mortos pelo _qa; 9 vivos só com a suíte do dev (RenovacaoInvalida no vínculo, 4 páginas, linha repetida,
  NFC do --cat, SemPermissao engolida nas ofertas, falha ao gravar vínculo no erro troca a saída...). Os 2 que
  sobreviveram à 1ª versão do _qa: RenovacaoInvalida só testada nas ofertas, e gravar_vinculos falhando no Limite.

## Etapa 3 — rodada 2, 2026-11-05: APROVADO, 56 testes no test_atualizar_precos_ml_qa (~3 s)
Q1 da rodada 1 virou RISCO ACEITO (`test_q1_coluna_nula_vira_vazia_risco_aceito` caracteriza NULL → ''; fica vermelho de propósito se o upsert mudar).
Classes novas: `QaCommitPorItem` (`quebrando_na_vez(n, exc)`: o upsert grava e depois levanta; `assertBancoLivre`: outra conexão com timeout=0),
`QaServidorDeVerdade` (servidor.py em subprocesso sobre o banco do teste; `pedir` usa http.client, que ignora os proxies mortos; ids vêm de `todas()`),
`QaTetoEMetadeRodada2`. Banco travado de verdade: patch de `S.conectar` com `PRAGMA busy_timeout=0` (o real espera 30 s).
- CA6 por execução: `strace -f -qq -e trace=connect -o <arq> python3 testes/<suite>.py` (só deu AF_UNIX e 127.0.0.1).
- Mutantes: 39/39 mortos; `except Exception` no rollback, metade antes do --vincular e trava durante a rede só morrem pelo _qa.
- O teste antigo do dev pode ser comparado com cópias em scratchpads velhos de `/tmp/claude-1000/*/`, se ainda existirem.
