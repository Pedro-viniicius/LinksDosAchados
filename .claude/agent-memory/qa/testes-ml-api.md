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

**Achados abertos:** Q1 baixa: `.ml_tokens.json.<hex>.tmp` (sobra de SIGKILL entre O_EXCL e replace, 0600, com
os tokens) não está no .gitignore. Teste `test_sobra_de_gravacao_interrompida_fica_no_gitignore` falha até
o dev pôr o padrão no .gitignore.
