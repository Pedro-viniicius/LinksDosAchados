---
name: coletar-shopee-testes
description: Armadilhas do coletar_shopee.py e de testes/test_coletar_shopee.py (Secret, mocks da rede, mutantes, ID vazio) e da suíte rodando com outros dev em paralelo
metadata:
  type: project
---

Vistas na E7 de perfumaria-tres-lojas (2026-11-03):

- A rede do `coletar_shopee.py` tem dois pontos, ambos openers sem redirect (S2: a API não pode reenviar o Authorization para um Location): `OPENER_API.open` e `OPENER_CONFERENCIA.open`. Os testes trocam os dois com `mock.patch.object(C.OPENER_..., 'open', ...)` e põem um `urlopen` que falha. 3xx não seguido chega como `HTTPError` com `headers['Location']`.
- `credenciais()` faz `os.environ.pop` do Secret (S3): no subprocesso de teste, guarde o Secret numa variável ANTES de chamar `main`, senão `os.environ[...]` dá KeyError.
- `ID_AFILIADO_SHOPEE` foi preenchido em 2026-11-03 com o ID do dono (não é segredo). O `setUp` do teste faz patch dele com um ID falso; o valor do arquivo fica em `ID_DO_ARQUIVO`, guardado ANTES de qualquer mock. O caso "ID vazio sai com 2" como script roda uma CÓPIA do arquivo com a linha trocada, num tmp, com `PYTHONPATH=RAIZ` para achar servidor.py e disparo.py.
- Prova de que o Secret não vaza no subprocesso sem tocar a rede: `python3 -c` que importa o módulo e troca `urlopen`/`OPENER_CONFERENCIA.open` por função que levanta `OSError(<Secret>)`; procure o marcador e "Traceback" na saída.
- Mutante de "teto de tamanho" só morre se a resposta grande for JSON VÁLIDO e no formato (o `read(MAX+1)` já trunca e quebra o JSON); mutante "termo concatenado" só morre se o teste conferir `set(corpo) == {'query','variables'}`.
- Com outros `dev` editando `servidor.py`/`index.html` ao mesmo tempo, `test_servidor.py` deu 1 erro em 38 s; isolado, passou 2 vezes em 2 s. Rode de novo antes de concluir que quebrou.
- Mutantes: copie `coletar_shopee.py`, `servidor.py`, `disparo.py` e `testes/test_coletar_shopee.py` para o scratchpad (o teste acha o módulo pelo `RAIZ` do próprio arquivo).

**How to apply:** ao mexer no `coletar_shopee.py` ou no teste dele. Relacionado: [[servidor-testes]], [[escapes-unicode-ferramentas]].
