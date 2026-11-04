---
name: coletar-amazon-piso-testes
description: Piso/usado na coleta da Amazon (etapa 4 abas-nichadas): parses falsos precisam de NO_PISO, HTML de busca montado em teste, mutantes em cópia
metadata:
  type: project
---

Vista em 2026-11-04 (etapa 4 de abas-nichadas-e-coleta):

- Não há fixture de HTML da busca da Amazon no repositório; `testes/test_coletar_amazon.py` monta o card (`card()`/`pagina()`) imitando o markup (preço por litro = `.a-price.a-text-price` SEM `data-a-strike`). Não foi confirmado contra HTML real (sem rede): se a Amazon mudar o markup, o seletor `[data-a-strike]` é o ponto a rever.
- Qualquer `parse_busca` falso nos testes que grava itens precisa devolver `avaliacao`/`num_avaliacoes` que passem o piso (`NO_PISO` em `test_coletar_amazon.py` e em `test_ordens_qa.py`), senão `coletar_buscas` não grava nem marca o termo.
- Termo com achados mas 0 no piso NÃO é marcado como feito (rerodado na próxima rodada, sem loop: uma busca por rodada); termo com ≥ 1 no piso é marcado.
- Mutantes: copie `servidor.py disparo.py genero.py api_ofertas.py buscas.json` + `testes/test_coletar_amazon.py` para o scratchpad e mute só a cópia do `coletar_amazon.py` (os testes importam pelo `RAIZ` do local do arquivo).
