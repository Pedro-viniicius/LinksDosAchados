---
name: testes-confirmar-preco-freio
description: Como tornar determinístico o teste de corrida resposta x liberar do FreioReleitura (test_confirmar_preco_qa.py)
metadata:
  type: project
---

Rodar: `python3 testes/test_confirmar_preco_qa.py` (proxies em 127.0.0.1:9), 50 testes, ~8 s.

Corrida de 17/11/2026: `despachar_confirmar_preco` (servidor.py) manda a resposta no `else:` e só libera o freio
no `finally`, então a pausa de 15 min nasce depois da resposta (flaky `900 != 840`; pedido logo depois recebe
'ocupado' 3 s em vez de 'pausa'). Teste determinístico: `segurar_liberar()` no TestRotaQA envolve
`S.FREIO_RELEITURA.liberar` com `Event.wait(1.5)` e um `liberado` Event; testes
`test_pausa_conta_do_instante_do_bloqueio_...` e `test_pedido_logo_depois_do_bloqueado_recebe_pausa_...`.
Mutante validado em cópia no scratchpad: chamar `FREIO_RELEITURA.liberar(resultado)` antes do `self.json` passa tudo.
**Why:** técnica reaproveitável para qualquer corrida "resposta sai antes do estado ser gravado".
