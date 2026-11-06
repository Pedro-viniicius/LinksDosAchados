---
name: garimpo-reconhecer-testes
description: Armadilhas do tools/garimpo_feminino/fase_reconhecer.py e do test_reconhecer.py (__schema recusado pelo banco, mensagem da API sem gancho no cliente, parar no 1º 10030, ApiRoteada, mutantes)
metadata:
  type: project
---

Vistas na etapa 6 do plano garimpo-feminino-shopee (2026-11-06):

- `banco.RE_OPERACAO` exige letra no início: o `operacao_de` da introspecção dá `__schema`/`__type` e o `registrar_requisicao` levanta ValueError DENTRO do `finally` do `Cliente._tentar` (mascara a resposta). A fase grava com `lstrip('_')` (`schema`, `type`). Fase nova com introspecção: faça o mesmo.
- O `Cliente.pedir` levanta `ErroApi(codigo, http)` sem a mensagem. Para guardar a mensagem (plano: `CS._texto`, 300, só no banco), a fase troca `CS._ler_json` por um invólucro durante o `rodar` e devolve o original no `finally`; o teste confere a identidade depois de cada rodada.
- O cliente repete o 10030/429 com backoff sozinho. Para parar no 1º 10030 (rajada), o `registrar` próprio levanta uma exceção privada depois de gravar a linha: ela sobe do `finally` do `_tentar` antes de qualquer espera.
- `Cliente.pausa` é atributo comum (validado só no construtor): a rajada põe 1/taxa − JITTER/2 e devolve no `finally`.
- `CS._texto` e `CS.MAX_RESPOSTA` entraram em `NOMES_CS`/`ARIDADE` do test_cli.py. Nome novo do CS numa fase = mexer no test_cli.py (arquivo de outra etapa): avise o lead se houver dev em paralelo.
- `ApiRoteada` (test_reconhecer.py) responde pelo texto da consulta (mapa constante → nome) e anota consulta desconhecida: serve de modelo para as fases seguintes. ~25 rodadas completas (155 pedidos cada) levam 0,4 s; não é sinal de teste pulado.
- Mutantes: script no scratchpad copia `coletar_shopee.py`, `servidor.py`, `disparo.py`, `genero.py` e `tools/`; 21 mutantes, todos mortos. Mutante tem de TROCAR o trecho, não acrescentar um bloco antes dele (um "vivo" falso foi isso).

**How to apply:** ao escrever `fase_mapa`, `fase_links`, `fase_conversoes` ou mexer no reconhecer depois do R1. Relacionado: [[garimpo-cli-testes]], [[garimpo-consultas-testes]], [[garimpo-cliente-testes]], [[garimpo-banco-testes]].

Depois da rodada 1 de correção, a 1ª sonda é a `limit.20` e falha sem resposta não vira medição: [[garimpo-correcoes-rodada1]].
