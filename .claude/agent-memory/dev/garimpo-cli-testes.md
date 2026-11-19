---
name: garimpo-cli-testes
description: Armadilhas do tools/garimpo_feminino/garimpo.py, do testes/comum.py e do test_cli.py (fase falsa via sys.modules, log por rodada, null x ausente, mutantes numa cópia)
metadata:
  type: project
---

Vistas na etapa 4 do plano garimpo-feminino-shopee (2026-11-06):

- Fase falsa para testar o despacho: `types.ModuleType('fase_teste_mapa')` + `mock.patch.dict(sys.modules, {...})` + `mock.patch.dict(G.SUBCOMANDOS, {'mapa': 'fase_teste_mapa'})`. Não use os nomes reais (`fase_mapa`): quando as etapas seguintes criarem o arquivo, o teste "não implementada" quebraria; ele usa `fase_que_nao_existe_ainda`.
- `ler_json_estrito` devolve o sentinela `AUSENTE` (não `None`): um `achados.json` com `null` tem de dar saída 2, não os padrões. Há teste e mutante para isso.
- Pasta reaproveitada entre rodadas: o `Resultado` do teste guarda os logs de antes e lê só o novo (o nome `-2.log` ordena ANTES do `.log` sem sufixo, `-` < `.`). O helper `rodar` reescreve ou apaga o achados de teste a cada chamada (senão o da rodada anterior vale).
- O `S_ISREG` do `ler_json_estrito` é defesa em profundidade: com `O_NONBLOCK`, FIFO sem escritor lê `b''` e pasta dá EISDIR, ambos já viram ErroConfig. Mutante equivalente; não perca tempo.
- O `comum.isolado` troca `time.sleep` pelo `append` de uma lista: o `Cliente` lê `time.sleep` no construtor, então ele tem de nascer dentro do bloco (o `main` cria o cliente, ok).
- Mutantes: um script no scratchpad (some com a sessão; refaça) copia `coletar_shopee.py`, `servidor.py`, `disparo.py`, `genero.py` e a pasta `tools/garimpo_feminino` para `<scratch>/e4/m/` e roda o `test_cli.py` da cópia. 20 mutantes do garimpo.py, todos mortos.
- `--max-req` é acrescentado pelo `garimpo.py` só nas fases com API; a fase não pode declará-lo (argparse daria conflito).

**How to apply:** ao escrever as fases (`fase_*.py`) e os testes delas com o `comum.py`. Relacionado: [[garimpo-cliente-testes]], [[garimpo-banco-testes]], [[coletar-shopee-testes]].
