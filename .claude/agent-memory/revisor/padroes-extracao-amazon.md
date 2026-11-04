---
name: padroes-extracao-amazon
description: Regex de extração da página da Amazon (extrair_produto_amazon em servidor.py, também usada por coletar_amazon.py) e como testar mutantes dela
metadata:
  type: project
---

`extrair_produto_amazon` (servidor.py) serve o `/api/fetch` ("Atualizar preço") e o modo `whatsapp` do `coletar_amazon.py`. Em 2026-11-04, a foto passou a sair de `<img(?=[^>]*\sid="landingImage")[^>]*\ssrc="..."` porque a Amazon põe o `src` antes do `id`.

Padrão visto: o teste de "não pega data-src" pôs o `data-src` ANTES do `src`, e aí o mutante sem o `\s` (que pegaria o `data-src`) também passa. Caso que discrimina: `data-src` DEPOIS do `src` na mesma tag. Também `<div id="landingImage" src=...>` mata o mutante sem o `<img`.

**Why:** regex sobre HTML com `[^>]*` guloso pega o ÚLTIMO atributo que casa; a ordem dos atributos no caso de teste decide se o teste prova alguma coisa.
**How to apply:** em mudança de regex de extração, rode os mutantes num script do scratchpad (`python3 -I`) contra os casos do teste e contra a página real salva pelo lead, se houver. Ver [[padroes-disparo]] (mutantes).
