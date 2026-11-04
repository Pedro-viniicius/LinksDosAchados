---
name: testes-abas-nichadas
description: Entrega "17 abas por nicho e coleta" (etapas 1-10): como rodar a página abas-qa, testes do QA no servidor/gênero, harness de mutantes, bugs abertos e fatos medidos na cópia do banco
metadata:
  type: project
---

Verificado em 2026-11-04 (rodada 1; etapas 11-15 são operação do lead e ficam fora).

**Rodar**
- Front: cópia com `sqlite3.connect('file:achadinhos.db?mode=ro',uri=True).backup(...)`, depois `ACHADINHOS_DB=<cópia> python3 migrar_categorias.py` (sem `--sim`, caminho não é o real), servidor próprio (`ACHADINHOS_PORTA`, `ACHADINHOS_DISPARO=0`, `ACHADINHOS_API_TOKEN_ARQUIVO=/nao/existe`) e `PORTA=<p> node testes/rodar.mjs abas-qa` (também `abas`, `genero`, `disparo`, `mensagens`, etc. passam na cópia migrada).
- `abas-qa.test.html` (QA, 15): nomes hostis em "Outras" de 320 a 1280 px, activeCat salvo hostil (`__proto__`, caixa errada, espaço), "Outras" some e o seletor acompanha, formulário da regra em tela estreita, "Marcar o grupo" de Outras. O harness é copiado de `abas.test.html`; o formulário da regra é montado solto em `#telaDisparo` (sem navegar) e medido.
- `test_servidor_qa.py::TestPrecoAntigoQa` (7) e `test_genero_qa.py::BelezaEModaNosTresConsumidores` (4, banco novo com itens sintéticos; reaproveita `ServidorQa`, `amazon()` e `D.elegiveis`).
- `migrar_categorias.py --restaurar` com a cópia: o guarda de porta olha a 8765 mesmo com `ACHADINHOS_DB` apontando para cópia; passe `ACHADINHOS_PORTA=<livre>` para restaurar numa cópia enquanto o servidor real roda.

**Fatos medidos na cópia de 8.888 itens (2026-11-04)**: dry-run = plano (Celulares 1426, Áudio 512, TV 767, Games 405, Eletroportáteis 584, Eletrodomésticos 632, Cozinha 604, Cama 266, Casa 641, Perfumaria 3051); 5.837 movidos, 33 preços antigos limpos (todos Amazon, perfumaria), url idêntica, 2ª rodada "Nada a migrar", `--restaurar` devolve `select * from items` idêntico. Perfumaria F/M/U/sem idêntica antes/depois (696/972/178/1205). 161 termos novos batem com o texto do plano. Dos itens Amazon já no banco, 2.435 passam no piso e 19 são "usado". `num_avaliacoes` real vem como "6,6 mil", "827", "1".

**Armadilhas**
- O banco real não tem `sqlite3` CLI neste ambiente: use python.
- Chrome real: palavra única de ~31+ letras num chip do formulário da regra estoura a 320 px (Q1 abaixo); na barra/seletor o `overflow-wrap:anywhere` segura.

**Atualização 2026-11-04 tarde:** `abas-qa` passa 15/15 (Q1 do chip parece corrigido); o banco real já tem as 17 abas e não existe mais "Casa e Decoração" (virou "Casa, Móveis e Ferramentas").

**Bugs abertos (rodada 1, baixos)**
- Q1: chip de categoria legada de uma palavra só (≥ ~31 letras) estoura a tela a 320 px no formulário da regra (`abas-qa::Q1`, vermelho de propósito).
- Q2: `PATCH /api/items/<id>` com `data` grava `preco_antigo` implausível (só o `upsert` aplica `preco_antigo_plausivel`); `test_servidor_qa::test_q2_patch_de_data_tambem_nao_grava_antigo_implausivel`.

**Mutantes** (espelho em scratchpad `mut/` com `mut.py`/`mutfront.py`, JSON de `{nome,arq,de,para,cmds}`): 28 em servidor/amazon/shopee/genero, 20 em migrar/classificar/coletar_ml.js: todos mortos. Front (19 em index.html, servidor 8777 sobre cópia, páginas abas,abas-qa,genero): todos mortos; 4 só caíam no `abas-qa` (marcar grupo, aria-label do botão após alternar, esc de data-c e do nome). Lição: com uma página QA vermelha de propósito (Q1), o harness precisa ignorar a falha conhecida ao julgar o mutante, senão tudo parece "morto".
- Suíte final da rodada 1: Python todo OK (test_servidor_qa 26/27 por causa do Q2; test_genero_qa 62, ~80 s), Node 153/219/7/8, páginas OK exceto abas-qa (Q1). `disparo-integracao` e `genero-integracao` pedem cópia migrada (precisam de itens), não banco vazio.
- Sobras fora do meu controle: `/tmp/achadinhos-api-*` (de testes da API v1, de qualquer agente).
- Lacunas não-bug (regex literal do plano): `Open-Box`, `Openbox`, `Semi-novo`, `Renewed`, `Reembalado` não são recusados como usado; busca "Aparador de barba" não gera masculino sem a palavra no título (busca só vale com palavra de gênero).
