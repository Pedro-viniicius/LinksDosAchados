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
- Mutantes: copie `coletar_shopee.py`, `servidor.py`, `disparo.py`, `genero.py` e `testes/test_coletar_shopee.py` para o scratchpad (o teste acha o módulo pelo `RAIZ` do próprio arquivo). Sem `coletar_amazon.py`/`coletar_ml.js` na cópia, `TestUsado.test_mesma_lista_da_amazon_e_do_ml` dá `errors=1` em toda rodada: é da cópia, não do mutante (confira a cópia sem mutação).

Etapa 1 de atualizar-precos-shopee-por-item (2026-11-08):

- O único `OPENER_API.open(` agora fica em `_pedir(cred, corpo)`; `buscar` e `buscar_item` só montam o corpo. O `test_shopee_qa.py` conta as ocorrências no fonte.
- Ordem "API → dono → pausa → API" do `conferir --por-item` provada com um objeto que anota numa lista só os três falsos (`Ordem` no teste); o mutante "sem pausa" só morre por esse teste.
- Subprocesso com falha só na 2ª chamada: no `-c`, uma fila com a 1ª resposta e depois `raise OSError(SEG)`; a conferência levanta `HTTPError` 302 com o Location bom.

Vistas na etapa 7 de abas-nichadas-e-coleta (`importar`, 2026-11-04):

- Para provar "não lê o ambiente", troque `os.environ` (no módulo `os`) por uma subclasse de `dict` que anota as chaves lidas em get/pop/[]/in (`AmbienteEspiao` no teste). O `mock.patch.dict(os.environ, ...)` do `rodar()` passa a agir sobre o espião sem problema. Rode também um caso que LÊ (modo `buscas`) para provar que o espião enxerga.
- Mutante "tirar o `os.path.isfile`" só morre com FIFO (o `open` trava): teste com `os.mkfifo` + thread com `join(5)` e destrave com `os.open(fifo, O_WRONLY|O_NONBLOCK)`. O mutante "ler sem o `MAX+1`" é equivalente (o `len > MAX` ainda recusa).
- Teto exato do arquivo: JSON válido + espaços no fim até `MAX_RESPOSTA` bytes (entra) e `MAX+1` (recusa).
- Piso subiu para 50 vendas (P1): o ramo "1 vendido" (singular) ficou morto; os testes usam 50.

Rodada 1 de abas-nichadas (2026-11-04):

- `importar` confere o dono de CADA link distinto (antes só o 1º), com `pausa()` entre eles; `buscas` segue conferindo só o 1º (link gerado pela API com a credencial do dono). `ConferenciaPorLink` no teste dá Location por link e anota a ordem junto com a pausa.
- `RE_USADO` é cópia local (Amazon, ML, Shopee); `TestUsado.test_mesma_lista_da_amazon_e_do_ml` lê as duas outras regex do fonte por regex: mudar a lista num lugar só reprova.
 ao mexer no `coletar_shopee.py` ou no teste dele. Relacionado: [[servidor-testes]], [[escapes-unicode-ferramentas]].
