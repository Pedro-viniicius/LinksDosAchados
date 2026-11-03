---
name: decisao-eletronicos-coleta-ml
description: Abas finais decididas pelo dono em 2026-11-03 (Black Friday | Eletrônicos, Eletrodomésticos, Casa e Decoração, Perfumes e Perfumaria), migrar_categorias.py, progresso por termo e coletar_ml.js
metadata:
  type: project
---
O plano está em `docs/produto/planos/eletronicos-e-coleta-ml.md` (rev. 2, 2026-11-03).

**Decisão do dono.** As abas finais são "Lista WhatsApp", "Black Friday | Eletrônicos" (com `|`), "Eletrodomésticos", "Casa e Decoração" e "Perfumes e Perfumaria" (nova). Eletrodoméstico tem aba própria. "Black Friday" e "Casa Nova" deixam de existir.

**Fatos do código e do banco:**
- `buscas.json` é o mapa único termo → categoria. O `coletar_ml.js` embute uma cópia, e um teste confere as duas.
- O alias do ML "Caixa inteligente assistente virtual" aponta para "Smart speaker Alexa".
- Uma `cat` por item (UNIQUE loja+item_id). O `upsert` só grava `cat` no INSERT, então coletar de novo não devolve o item à aba antiga.
- **Armadilha:** o progresso antigo do `coletar_amazon.py` é `busca|{cat}|{termo}`. Renomear uma aba, ou usar `|` no nome, faz a Amazon coletar tudo de novo. O plano passa a chave para `busca|{termo}` (lê o último segmento) e cria `ACHADINHOS_FEITOS`.
- O servidor não serve `/buscas.json`, e o script antigo do ML dependia disso.
- O script antigo do ML está numa transcrição de sessão anterior que tem dado pessoal do dono. O resumo do algoritmo está no plano. **Não extraia a transcrição para arquivo.** O lead pediu isso depois que eu gravei um extrato no scratchpad.

**Why:** essas armadilhas não aparecem lendo só o código atual.
**How to apply:** antes de mexer em categorias, `buscas.json` ou coleta, confira se `migrar_categorias.py` e `coletar_ml.js` já existem. Veja [[decisao-blindar-servidor]] e [[decisao-teste-front]].
