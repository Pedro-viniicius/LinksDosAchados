---
name: padroes-docs
description: Ao revisar README/protocolos, simule cada passo com o estado que ele cria (arquivo de progresso novo, cópia do banco, porta); a doc copia o protocolo do plano e herda os erros dele
metadata:
  type: feedback
---

Uma doc que resume um protocolo do plano herda os erros do plano. Simule cada passo com o estado que ele cria, sem confiar no texto. Caso de 2026-11-03 (README da etapa 6 de eletronicos-e-coleta-ml): o passo "Amazon numa cópia" usava um `ACHADINHOS_FEITOS` novo e prometia "só faltam os 28 de perfumaria". Com o progresso vazio, porém, o `coletar_amazon.py` começa pela primeira chave do `buscas.json` (eletrônicos), e o teste não prova nada sobre perfumaria.

Caso de 2026-11-03 (README da E8 de perfumaria-tres-lojas): o comando do Secret `read -rs S; VAR="$S" python3 ...; unset S` só limpa `S` se a lista terminar. Se o Python morrer por SIGINT fora do `try` (KeyboardInterrupt não tratado), o bash aborta a lista e `S` fica na shell. Variável não exportada não aparece em `env`/`printenv`, mas aparece em `set`. Para comando com segredo, simule a interrupção em cada ponto.

**Why:** o plano e a doc diziam a mesma coisa, e por isso o erro parecia confirmado.
**How to apply:** para cada comando da doc, pergunte o que existe antes dele (arquivo de progresso, `localStorage`, cópia migrada ou não, porta) e qual é a ordem de iteração do código. Rode os one-liners numa cópia no scratchpad. Ver [[revisao-ambiente]].

Caso de 2026-11-05 (README da etapa 4 de api-oficial-ml-catalogo): a estimativa "X chamadas de vínculo = 5 h em 13 rodadas" somava só uma das fases da rodada; a mesma seção dizia "uma rodada gasta até 50 min", e 13 × 50 min contradiz 5 h. **How to apply:** em estimativa de tempo total, some todas as fases que cada rodada executa (vínculo + ofertas, mesmo dia e dia seguinte) e confira se "rodadas × tempo por rodada" fecha com o total. Confira também a ordem: passo de segurança ("antes do primeiro lote": backup) tem de vir ANTES do bloco de comandos, porque o dono segue de cima para baixo.

Caso de 2026-11-05 (r2 da mesma etapa): as correções de texto trouxeram afirmações novas sem conferir o código. (1) "o `atualizado_em` regravado faz o item subir na ordem 'recentes' do disparo": a `recentes` do `disparo.ordenar` usa `criado_em` justamente para não reagir a regravações. (2) "o atualizado traz 'Preço de hoje, HH:MM'": na primeira hora o cartão mostra "Preço de agora há pouco" (`textoIdadePreco`, < 36e5 ms), e o dono confere logo depois da rodada. (3) Mover um bloco quebrou o "a conferência abaixo" de outro parágrafo. **How to apply:** na r2 de doc, cada consequência nova ("sobe em X", "mostra Y") é afirmação nova: grep no código. Texto de interface citado: leia a função que escolhe o texto e pense em QUANDO o dono vai olhar. Bloco movido: grep por "abaixo"/"acima"/"seção X" no arquivo.
