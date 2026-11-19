---
name: confirmar-preco-freio-testes
description: Ordem "liberar o freio x resposta" na rota confirmar-preco (Q1, 17/11/2026) e como provar; tail do sistema é o uutils
metadata:
  type: project
---

- Q1 (17/11/2026): `despachar_confirmar_preco` libera o `FREIO_RELEITURA` por `soltar_freio()` (uma vez só,
  erro ao liberar só no log) antes de cada `self.json`; o `finally` só cobre BaseException. Qualquer ramo novo
  na rota precisa chamar `soltar_freio()` antes de responder.
- Prova determinística da ordem: espiar `S.FREIO_RELEITURA.liberar` e `S.Handler.json` (no nível da classe,
  `responder(handler, obj, code, cabecalhos)`) numa lista comum: `[('liberar', r), ('resposta', código)]`.
  Está em `test_confirmar_preco_servidor.py` (`espiar_ordem`). O qa usa outra técnica (Event no liberar).
- Chamar `self.setUp()` dentro de um `subTest` no `TestRotaEmProcesso` funciona: os patches empilham pelo
  `addCleanup` e desfazem em LIFO.
- O "antes" provado numa cópia: `servidor.py` do `git show HEAD:` + `disparo.py`, `genero.py`, `api_ofertas.py`
  e `testes/` no scratchpad (o `RAIZ` vem do local do teste).
- `tail` nesta máquina é o uutils: `tail -3 a b` dá "unexpected argument '-3'"; use `tail -n 3`.

**How to apply:** ao mexer na rota de confirmação de preço ou no freio. Relacionado: [[servidor-testes]].
