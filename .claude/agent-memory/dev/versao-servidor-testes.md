---
name: versao-servidor-testes
description: /api/versao e verificar.py --servidor (etapa 6 de endurecer-engenharia-e-operacao) - rota nova quebra lista fechada do test_servidor, servidor numa cópia dos 4 .py, api_ofertas importado em todo /api/, segunda linha do stdout
metadata:
  type: project
---

Vistas em 2026-11-09, na etapa 6 (versão do código no ar):

- **Rota nova quebra `test_ca6_antigo_rotas_do_fonte_sem_proxy_de_imagem`** (`testes/test_servidor.py`): ele lista TODO literal `'/api/...'` do `servidor.py` numa lista fechada. Toda rota nova tem de entrar lá (foi o caso do `/api/versao`).
- **Servidor de verdade numa cópia**: copiar só `servidor.py`, `disparo.py`, `genero.py` e `api_ofertas.py` para uma pasta temporária e subir com `cwd` nela basta (o `BASE` é a pasta do arquivo; sem `.git` ali, `git` dá null). Dá para mexer nos .py da cópia com o servidor no ar.
- **Todo GET em `/api/` importa o `api_ofertas`** (`eh_rota_v1` → `prefixo_v1`), sob demanda. Apagar o `api_ofertas.py` da cópia antes do primeiro pedido derruba a conexão (RemoteDisconnected): para provar "arquivo apagado muda o hash", apague o `servidor.py` da cópia, que já está carregado.
- A linha `Código ...` é a SEGUNDA linha do stdout; vários testes conferem a primeira (`Site em ...`) por igualdade, então nada pode entrar antes dela.
- `assertNotRegex` sobre o fonte inteiro imprime o arquivo todo na falha (60 KB): ao procurar `subprocess`, a docstring já cita a palavra; procure `import subprocess`/`subprocess.`.
- **Recursão do `verificar.py`**: teste que chama `V.main([...])` de verdade roda a SUÍTE INTEIRA se o desvio da opção quebrar, e a suíte roda o próprio teste de novo (centenas de servidores órfãos em `/tmp/achadinhos-*`, filhos em sessão própria que sobrevivem ao kill do pai). Sempre troque `V.verificar` por um falso que falha (`mock.patch.object(V, 'verificar', side_effect=...)`; no subprocesso, `python3 -c` com `V.verificar = lambda a: sys.exit(99)`). Limpar `/tmp` compartilhado é barrado pelo classificador: evite criar a sujeira.
- Mutantes: runner no scratchpad que copia os 5 .py (inclui `verificar.py`) e `testes/test_versao_servidor.py` + `testes/test_servidor.py` (o primeiro importa o segundo como `TS`); ~25 s por mutante.

**How to apply:** ao mexer no `/api/versao`, no `verificar.py --servidor` ou ao criar outra rota no `servidor.py`. Relacionado: [[servidor-testes]], [[verificar-testes]].
