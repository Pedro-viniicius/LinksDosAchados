---
name: shopee-front-testes
description: Armadilhas do E4 (Shopee no index.html e nas páginas de teste do front): LOJA em uma linha, esperado da paridade, chips de loja, itens falsos injetados
metadata:
  type: project
---

Vistas em 2026-11-03, E4 do plano perfumaria-tres-lojas:

- `test_disparo_qa.py` extrai o `LOJA` do `index.html` com `/^const LOJA = \{.*\};$/m`: mantenha `const LOJA = {...};` numa linha só, no começo da linha. Esse teste (fuzz e ADVERSARIAIS) não usa loja `shopee`; a paridade com shopee foi provada à parte (script no scratchpad importando `Q.JS_PARIDADE` e trocando a loja do fuzz) e só fica coberta no repositório pelos 2 casos em `mensagens.test.html`.
- Esperado novo da paridade em `mensagens.test.html`: gere com node extraindo `const LOJA` e `buildMsg` do `index.html` (ver [[disparo-testes]]). Caso com `"padrao"` repetido quebra o teste "os casos cobrem os 4 templates padrão": no caso novo, não ponha `padrao`. O `test_disparo.py` lê o mesmo bloco, então o caso novo já exercita o `montar_mensagem` com `shopee`.
- Regra nova abre com as 3 lojas marcadas: testes que antes marcavam o rádio "Amazon"/"ml" precisam desmarcar as outras (`marcarChip(grupo, valor, false)`).
- `abas.test.html` compara o `textContent` do `#count`: o contador novo usa `<span class="nb">` por trecho (o " ·" fica dentro do trecho anterior), com o mesmo texto de antes.
- Teste do front que precisa de loja ausente do banco real: injete item falso (`W.eval('items.push(...)')` ou `W.__lista` + `items = window.__lista; render()`), e restaure em `finally`. Item falso da fila/histórico: `item_pk` do `envioFalso` aponta o `items[0]` real, então a loja do cartão depende do banco; use `W.eval('LOJA[items[0].loja]')`.
- `copiar-imagem.test.html` também lista `HOSTS_FOTO` exato (3 CDNs agora): mexer em `HOSTS_FOTO` quebra lá.
- `mutante com loja desconhecida → 'amazon'` deixa o `abrir-e-adicionar` em PENDENTE (esperas de 15 s estouram); trate PENDENTE como falha.

**How to apply:** ao mexer em lojas, `buildMsg` ou nas páginas de teste do front. Relacionado: [[disparo-tela-testes]].
- R1 (rodada 2): `testes/test_front_constantes.py` lê as linhas `const LOJA/HOSTS_LINK/SUFIXO_ML/HOST_FOTO_SHOPEE/HOSTS_FOTO` do `index.html` por regex (uma linha só, começo da linha, comentário no fim ok) e as compara com `servidor`/`disparo`; `lojaDoLink` é checado no node contra `S.eh_url_de_loja` e `S.URL_DA_LOJA`. O ML do servidor é `meli.la` + sufixo `.mercadolivre.com.br` (domínio nu recusado).
