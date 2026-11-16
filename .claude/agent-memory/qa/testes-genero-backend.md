---
name: testes-genero-backend
description: Como rodar e estender testes/test_genero_qa.py (público/gênero: migração v2 na cópia do banco real, paridade items x v1 x disparo, concorrência), mutantes e armadilhas
metadata:
  type: project
---

Arquivo QA: `testes/test_genero_qa.py` (58 testes, ~75 s, criado 2026-11-03, rodada 1, nenhum bug encontrado). Dev: `test_genero.py`, `test_genero_servidor.py` e classes de gênero em `test_disparo.py`/`test_api_ofertas.py`.

**Rodar:** proxies mortos; `python3 testes/test_genero_qa.py -v`; classe isolada com `-k Concorrencia` (ou `ParidadeTresConsumidores`, `MigracaoNaCopiaReal`, `BordasDoPut`, `V1NadaQueExistiaMuda`, `RegraAntigaElegeOMesmoConjunto`, `CodigoAntigoSobreBancoMigrado`).

**Como funciona:** copia o banco real com `sqlite3.backup` (origem `mode=ro`) e, com `rebaixar_para_v1`, deixa a cópia em v1 mesmo que o real já tenha sido migrado (drop da tabela e da coluna, `user_version=1`). Código "antigo" = `git archive 1571135` (commit fixo anterior à feature; SkipTest se o git não tiver o commit). O antigo roda em subprocesso (`python -I -c` com `sys.path` do diretório extraído), nunca no mesmo processo. `ServidorQa` aceita `CODIGO` (antigo) e `preparar_banco`. Token da v1 só em arquivo temporário. Sem `achadinhos.db` as classes de banco real dão SkipTest.

**Fatos (2026-11-03):** real em v1 e sem regra/número/envio/config; Perfumaria 3.051 itens: F 696, M 972, U 178, sem 1.205 (folga de 8% na proporção). `/api/items` com gênero custa ~39 ms por 8.381 itens. PUT no 2^63-1: 404; PATCH no mesmo id responde 200 com `null` e DELETE 200 (contrato antigo, de propósito). Itens `items.id` são AUTOINCREMENT (id nunca reaproveitado: correção órfã é inofensiva). Pedido da v1 com 29 a 32 pares mudou de "parâmetros demais" para "no máximo 20 categorias" (MAX_PARES 28 -> 32): mesma 400, frase diferente.

**Mutantes (19, todos mortos pela união das suítes):** script no scratchpad (`mutar.py`: espelho com `.git` e `achadinhos.db` por symlink, `communicate(timeout=420)`). m13 (migrar só a v1) e outros que quebram o servidor travam por timeout: o espelho deixa servidor órfão (mate por PID, `/tmp/achadinhos-genero-qa-*`). Mutante com aspas dentro de string do SQL: use `\x22`.

**Armadilhas:** (1) `pgrep -f` mata o próprio shell (exit 144): use `ps aux | grep '[t]est_genero_qa'`. (2) teste que falha antes do cleanup vaza correção para os seguintes (a `BordasDoPut` limpa `generos_manuais` no setUp/addCleanup). (3) ordem `atualizacao` da v1 esconde itens gravados há < 60 s: nos testes use `ordem=relevancia` ou `A.rota(..., agora=futuro)` em processo. (4) caminho com dígito unicode não vai pelo http.client (ascii): use `%D9%A3`.

**Corrida PUT x DELETE (2026-11-15, rodada 1):** `testes/test_genero_servidor.py::PutGeneroDeleteNaJanela` (3 testes, em processo, sem thread): `object.__new__(S.Handler)` com `corpo/json/log_message` trocados, `S.DB` e `S.conectar` por `mock.patch.object`, e `sqlite3.connect(factory=ConexaoQueApagaNoCommit)` cujo `commit()` apaga o item por outra conexão. Bug confirmado: o `corrigir_genero` relê o item DEPOIS do `commit` e `linha_para_item(None)` dá TypeError (500). Correção validada por mutante em cópia no scratchpad (ler antes do commit): os 3 passam. A correção órfã não acontece (o DELETE apaga `generos_manuais` junto).
