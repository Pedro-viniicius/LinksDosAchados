---
name: testes-disparo
description: Como rodar e estender os testes do disparo (disparo.py + rotas /api/disparo), harness de mutantes, armadilhas e fatos do banco real
metadata:
  type: project
---

Suítes: `python3 testes/test_disparo.py` (dev, núcleo, relógio injetado), `test_disparo_servidor.py` (dev, subprocesso com transporte `falso`, `TICK_SEG=1`), `test_disparo_qa.py` (QA, 78 testes; importa os dois como módulos `T` e `TD` e subclassa `T.Base` / `TD.ServidorDisparo`). Rodar com proxy morto no ambiente. Paridade com buildMsg: o QA roda o `buildMsg` do index.html no node (vm, `process.argv.slice(1)` com `node -e`) + fuzz de semente fixa; a página `node testes/rodar.mjs mensagens` roda contra servidor próprio (`PORTA=`).

**Armadilhas**
- curl/urllib respeitam proxy morto: use `curl --noproxy '*'` e `ProxyHandler({})` para falar com o servidor próprio.
- A ferramenta Write converte `\uXXXX` digitado em caractere real (BOM, U+200B...) no arquivo; depois de escrever teste com invisíveis, converta de volta para escape.
- `pendente` de dias anteriores vira `expirado` no tick e NÃO bloqueia repetição: para testar prazo/virada de dia use `enviado` (transporte automático `T.Gravador`) ou datas de hoje.
- `assertSemDadoPessoal` do dev despeja o log inteiro na falha; o QA sobrescreve em `QaRotas`.
- `pkill -f` por trecho do próprio comando mata o shell: use pid.
- `index.html` muda sob os pés (outro dev): não fixar número de linha.

**Mutantes** (harness em scratchpad `qa/mut.py`: espelho do projeto, troca string, roda as 3 suítes; 4 em paralelo, ~6 min para 40). 2026-11-03: todos mortos por alguma suíte; os que o QA sozinho não pega (tolerância 9/10/11 min, so_ativa) o dev pega. Mutante que deixa `if` sem corpo é inválido (SyntaxError).

**Fatos do banco real (cópia, 2026-11-03):** só 3 cats (Black Friday, Casa Nova, Lista WhatsApp), 5.329 itens, tudo criado hoje (`recentes` ≈ posição), 54 itens da Lista sem foto, todos os links de afiliado, campos curtos (título máx 223). Detecção de link rejeita ~14 de 5.242 itens por falso positivo ("Le.Roux", "D.face", "Nx.kzwal.003").
