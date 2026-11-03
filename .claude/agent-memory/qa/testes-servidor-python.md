---
name: testes-servidor-python
description: Como rodar/estender os testes do servidor.py (unittest com subprocesso), mutantes sem risco de rede e armadilhas já vistas
metadata:
  type: project
---

Suíte do back: `python3 testes/test_servidor.py -v` (dev, 45 testes) e `python3 testes/test_servidor_qa.py -v` (QA, bordas; importa `test_servidor as T`). Cada classe sobe `servidor.py` real com `ACHADINHOS_DB` temporário e `ACHADINHOS_PORTA` livre. Front contra servidor novo: `PORTA=<p> node testes/rodar.mjs copiar-imagem`.

**Mutantes do servidor.py:** copie servidor.py, coletar_amazon.py, index.html, buscas.json e testes/ para um espelho no scratchpad (RAIZ vem do caminho do teste) e troque trechos por string replace. Mutantes que afrouxam `/api/fetch` (scheme, host, sem conferir URL) FAZEM REDE REAL (evil.com, Amazon, file://): rode sempre com `http_proxy/https_proxy/ftp_proxy=http://127.0.0.1:9` no ambiente (urllib respeita) ou nem rode; em 2026-11-03 rodei sem proxy (incidente, só GET anônimo).

**Armadilhas:** (1) `ServidorTeste.setUpClass` do dev vaza o subprocesso se uma subclasse falhar no seu `setUpClass` (semear dentro dos testes ou limpar). (2) `ThreadingHTTPServer` tem backlog 5: >6 conexões simultâneas dão ConnectionReset que não é bug de banco; conecte antes e dispare com `threading.Barrier` e poucas threads. (3) Q1 e Q2 foram corrigidos na rodada 2; `test_q1_inteiro_gigante_em_data_da_400` segue vermelho (int > 2**63 em data dá OverflowError e derruba a conexão). (4) Mutante que tira o addClassCleanup deixa servidores e diretórios órfãos de propósito: mate pelo pid e apague os dirs pelo nome. Os testes de Q1/Q2 só existem no arquivo QA; a suíte do dev não pega esses mutantes.
