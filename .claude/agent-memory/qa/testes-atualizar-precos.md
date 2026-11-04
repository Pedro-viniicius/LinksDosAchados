---
name: testes-atualizar-precos
description: Feature "preço sempre atualizado" (preco_em, trava do disparo, v1, atualizar_precos.py, quadro no front): como rodar os testes do QA, bugs baixos abertos, mutantes e armadilhas
metadata:
  type: project
---

Verificado em 2026-11-04 (rodada 1). Arquivos do QA: `testes/test_atualizar_precos_qa.py` (30 testes, ~12 s) e `testes/precos-qa.test.html` (7). Ajustes em testes antigos: `test_api_ofertas_qa.py` (gravar com preco_em; DadosReais migra a cópia e marca preco_em uniforme), `test_genero_qa.py` (CASA agora é 'Casa, Móveis e Ferramentas'; `ABAS_COM_GENERO` em vez de só a perfumaria; `sem_o_novo` ignora `preco_em`), `abas.test.html` (totais não fixos: `semAba()` e `alvo`), `api_ofertas_qa.test.mjs` (4 pedidos simultâneos leem o corpo na hora).

**Rodar**
- Python: proxies mortos (`http_proxy=https_proxy=ftp_proxy=http://127.0.0.1:9`). `python3 testes/test_atualizar_precos_qa.py` importa `test_atualizar_precos as T` (cria banco/mocks temporários) e `test_servidor as TS` (ServidorTeste). Três testes vermelhos de propósito (`test_q1_`, `test_q2_`, `test_q3_`); a página `precos-qa` tem o `Q4` vermelho. Quem roda mutantes tem que renomear `def test_q` para `def xtest_q` no espelho.
- Páginas: copie o banco real com `sqlite3.connect('file:...?mode=ro',uri=True).backup(...)`, suba `ACHADINHOS_DB=<cópia> ACHADINHOS_PORTA=<livre> ACHADINHOS_DISPARO=0 ACHADINHOS_API_TOKEN_ARQUIVO=/nao/existe python3 servidor.py` (o servidor migra a cópia para v3 sozinho) e `PORTA=<p> node testes/rodar.mjs precos-qa` (também precos, abas, abas-qa, genero, disparo, disparo-qa...).
- Testes de dados reais (`CopiaMigrada`) partem de `copiar_real` + `como_v2` (derruba a coluna se o real já for v3) + `migrar_com_o_servidor` (subprocesso `servidor.criar_banco()`): valem com o real em v2 ou v3. Cada teste que grava usa a própria cópia (backup por teste).

**Fatos**
- O banco real (2026-11-04 ~07:30): 17 abas, ~15,2 mil itens (Amazon 10,3 mil, ML 3,8 mil, Shopee 540); todo `item_id` Amazon/Shopee bate com `ID_DA_LOJA`. O backfill dá `preco_em` = `criado_em`, e 04/11 tem muitos itens criados: `ja_hoje` do lote conta quem nasceu hoje.
- Node 22.23 (undici): fetch concorrente que lê o corpo depois, com resposta > ~64 KB e `Connection: close`, dispara `assert(!this.paused)` como uncaughtException (reproduz contra `http.createServer` puro, não é do servidor.py). A resposta da v1 passou de 64 KB (limite=200, 130 itens) ao ganhar `preco_em`: o Turbo deve ler o corpo de cada fetch na hora. Lição geral: teste flaky que "piorou" depois de aumentar o corpo pode ser tamanho cruzando 64 KB.
- Python 3.14: `datetime.fromisoformat('...T24:00:00')` é aceito (meia-noite do dia seguinte).
- `sqlite3.connect` usado de outra thread (Timer) precisa de `check_same_thread=False`, senão o commit falha em silêncio na thread e o teste espera 30 s de busy timeout.

**Rodada 1 fechada (2026-11-04): Q1-Q4 corrigidos pelo dev, suítes todas verdes.** Depois das correções, regras novas de relógio: preço mais de 5 min à frente do `agora` é velho (S2, inclusivo); `preco_em` é lido de forma estrita (`disparo.ler_preco_em`); R1 (sem preço legível, o "Atualizar preço" não envia PATCH) e S4 (asin diferente não envia PATCH); D1 (contador do disparo só conta enviáveis). Lição: teste com relógio fixo anterior aos dados quebra com S2; use `relogio_dos_dados(con)` (max preco_em) mais `prazo_largo` (config 168) em testes sobre a cópia real, e `UPDATE items SET preco_em=<relógio injetado>` quando o upsert grava com o relógio real. Texto antigo dos bugs, para histórico: Q1 prazo `48.0`/`1e2` (front lê 48, servidor 24); Q2 `preco_em` com hora 24:00:00 é "recente" no servidor e velho no front; Q3 `selecionar` do lote usa `startswith(dia+'T')` e trata preco_em malformado do dia como confirmado hoje; Q4 quadro oferece `--cat` de categoria fora das 17 abas e o script recusa com saída 2. Risco não-bug: mensagem já na fila (pendente) não revalida o preço até expirar no dia seguinte.

**Mutantes** (espelho em scratchpad, `mut.py` com `{nome,arq,de,para,cmds}`; 17, todos mortos): preco_em sempre carimbado, upsert insere em so_existentes, `>` no limite, trava removida, backfill por atualizado_em ou sem filtro de preço, aviso sempre de filtros, lote com insert, sem commit por página, SQL da v1 `>`, bool aceito na validade, front `<=`, aspasShell sem `$`, PATCH carimba sempre, observação de item não selecionado, sem `ja_hoje`, so_existentes sem checar bool. Só o QA mata: front `<=` e aspas sem `$` (paridade node e shell real).
