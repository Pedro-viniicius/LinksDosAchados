---
name: testes-ml-api
description: QA do ml_api.py (API oficial do ML, OAuth PKCE, tokens 0600, flock): arquivo test_ml_api_qa.py, como rodar, harness de mutantes, Q1 aberto
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
