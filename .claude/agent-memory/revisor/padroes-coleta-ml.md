---
name: padroes-coleta-ml
description: Riscos a conferir no coletar_ml.js (coleta e afiliação do ML no console): conferência vazia, inelegível persistente por causa de configuração, toggle "Links curtos", e como provar sem acessar o ML
metadata:
  type: feedback
---

Achados da rodada 1 do `coletar_ml.js` (plano eletronicos-e-coleta-ml, 2026-11-03). Confira de novo em cada mudança do arquivo:
1. **Verificação que só relê o que o próprio script acabou de gravar** (GET depois do PATCH) é vazia: com o `servidor.py` síncrono, ela sempre dá 0. A "segunda passada" do plano serve para pegar par `origin_url`↔`short_url` errado do linkbuilder, e isso só aparece gerando de novo (o link já existe, `created:false`, e a resposta é estável).
2. **Falha de configuração classificada como defeito do item.** Um `short_url` que não é `meli.la` (com "Links curtos" desligado) ia para os inelegíveis, que ficam no `localStorage` e aparecem com "Exclua pelo site". Isso pode fazer o dono apagar produtos bons. O mesmo vale para `error_code` transitório.
3. **Toggle clicado às cegas** (`label.control` nulo num switch React) alterna o estado a cada lote.

4. **Efeito colateral da minha correção do item 2 (rodada 2):** "parar o lote se vier algum link não-meli.la" trava o `afiliar()` para sempre se o ML devolver esse link sempre para um item específico, porque nada é persistido e a ordem por id se repete. Ficou como SUGESTÃO: só parar quando o lote inteiro vier assim. Corrigido na rodada 3: só para quando nenhum item do lote vem `meli.la`; a repescagem nunca para; a conferência para.
O dono confirmou em 2026-11-03 que a segunda passada antiga gerava os links de novo, porque a 1ª criação em lote embaralhava os pares.

5. **Pré-filtro por substring esvazia o teste negativo (Q1, 2026-11-15).** `paginaSemResultado` só decodifica literal com `zrp` no texto bruto; o caso "rescue de outro tipo" (`type:'outro'`) nem passa no filtro, então o mutante que aceita rescue de qualquer tipo sobrevive. Teste negativo precisa conter a palavra-chave do pré-filtro em outro lugar. Mesmo padrão vale para `literalQ` (`includes('polycard')`).
6. **"Sem resultado" que não para a rodada esconde filtro removido pelo ML** (o próprio bug do `ofertadodia`). Resolvido na r2 do Q1: `avisarSemResultadoGeral` (2 ou mais buscados, todos zrp, fora do ramo do `parar()`). Os mutantes de limite, de "todos" e de contar pulados morrem; o teste "coleta parada não avisa" é vazio (para depois de 1 termo, abaixo do limite de 2), e o `atualizar()` nem tem esse teste. Para guarda que depende de limiar, monte o teste acima do limiar (parar dentro do fetch falso do 2º termo, determinístico).

**Why:** o dev cumpre o texto do CA ("a conferência repete até 0") sem a proteção que ele pedia, e os testes com servidor falso (`trocarErrado`) parecem provar o contrário.
**How to apply:** pergunte "que falha real isso detecta?" para toda conferência. Para os formatos dos campos, compare com os itens reais do ML por GET em `localhost:8765/api/items`: preço "R$ 9.999"/"R$ 999,99", desconto "-99%", avaliação "4.8 de 5 estrelas", vendas "Mais de N produtos vendidos", `num_avaliacoes` e `cupom` sempre vazios. Para os mutantes, copie para o scratchpad (veja a memória `coletar-ml-testes` do dev). Ver [[revisao-ambiente]].
