---
name: padroes-docs
description: Ao revisar README/protocolos, simule cada passo com o estado que ele cria (arquivo de progresso novo, cópia do banco, porta); a doc copia o protocolo do plano e herda os erros dele
metadata:
  type: feedback
---

Uma doc que resume um protocolo do plano herda os erros do plano. Simule cada passo com o estado que ele cria, sem confiar no texto. Caso de 2026-11-03 (README da etapa 6 de eletronicos-e-coleta-ml): o passo "Amazon numa cópia" usava um `ACHADINHOS_FEITOS` novo e prometia "só faltam os 28 de perfumaria". Com o progresso vazio, porém, o `coletar_amazon.py` começa pela primeira chave do `buscas.json` (eletrônicos), e o teste não prova nada sobre perfumaria.

**Why:** o plano e a doc diziam a mesma coisa, e por isso o erro parecia confirmado.
**How to apply:** para cada comando da doc, pergunte o que existe antes dele (arquivo de progresso, `localStorage`, cópia migrada ou não, porta) e qual é a ordem de iteração do código. Rode os one-liners numa cópia no scratchpad. Ver [[revisao-ambiente]].
