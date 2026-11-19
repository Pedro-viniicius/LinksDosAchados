---
name: garimpo-cliente-testes
description: Armadilhas do tools/garimpo_feminino/cliente.py e do test_cliente.py (capture_locals e eco da API, opener real com no_proxy, mutantes numa cópia, palavras proibidas no fonte)
metadata:
  type: project
---

Vistas na etapa 1 do plano garimpo-feminino-shopee (2026-11-06):

- O `Cliente` guarda credencial, ritmo e orçamento (o contrato do plano dizia `pedir(cred, ...)` solto; virou método, com `cred` no construtor). `ja_feitas` vem do garimpo.db (quem conta é o banco/CLI, não o cliente).
- Prova do Secret com `traceback.TracebackException(..., capture_locals=True)`: texto que a API devolve (eco) aparece no repr das variáveis locais (`resposta` no `_tentar`, `bruto` no `CS._ler_json`). Não é vazamento do Secret (ele nunca vai no pedido); nos cenários de eco, confira só str, repr e o traceback comum.
- O mutante "sem `from None` no HTTPError" só morre se o MOTIVO do HTTPError (reason phrase) trouxer o marcador: o corpo e o Location não aparecem no str do HTTPError.
- 3xx com o `CS.OPENER_API` real: servidor em 127.0.0.1, `mock.patch.object(CS, 'URL_API', 'http://127.0.0.1:<porta>/graphql')` e `mock.patch.dict(os.environ, {'no_proxy': '127.0.0.1'})` (o ProxyHandler foi montado com o proxy morto, mas o bypass lê o `no_proxy` na hora).
- O teste estático da etapa 4 reprova as palavras `http.client` e `socket` em `tools/garimpo_feminino/*.py`, inclusive em comentário: por isso o cliente captura só `OSError` (IncompleteRead passa sem virar ErroApi, mas é registrado pelo `finally`).
- Mutantes: copie `coletar_shopee.py`, `servidor.py`, `disparo.py`, `genero.py` para `<scratch>/m/` e o teste para `<scratch>/m/tools/garimpo_feminino/testes/`; o cliente acha a raiz por 3 `dirname`. "Incrementar `feitas` dentro do try" é equivalente.

**How to apply:** ao mexer no `cliente.py` ou nos testes que usam a rede do garimpo. Relacionado: [[coletar-shopee-testes]], [[servidor-testes]].
