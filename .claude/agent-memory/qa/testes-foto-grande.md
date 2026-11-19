---
name: testes-foto-grande
description: Testes da foto grande (disparo.foto_grande, API v1 imagem, urlFotoParaCopiar): onde estão, tabela compartilhada Python/front e como validei sem a correção
metadata:
  type: project
---

Bug: fotos saíam em miniatura (Amazon `_AC_UL320_`, ML `-E.webp`, Shopee `_tn`). Testes escritos em 2026-11-08 (modo A, antes da correção):
- `testes/test_disparo.py`: `TABELA_FOTO_GRANDE`, classes `FotoGrandeFuncao` (CA1) e `FotoGrandeNoDisparo` (CA3/CA5).
- `testes/test_api_ofertas.py`: classe `FotoGrande` (CA2).
- `testes/copiar-imagem.test.html`: bloco `TABELA_FOTO` entre `// TABELA_FOTO_GRANDE_INICIO/FIM` (JSON puro, mesma ordem da tabela Python; `FotoGrandeFuncao.test_tabela_igual_a_do_front` compara as duas), fallbacks do ML e da Shopee, grade com miniatura no `<img>`.

**Alterei testes antigos do front por mudança de especificação:** o ML deixou de ser "uma tentativa só" (agora `-F.jpg` e depois a URL gravada) e o teste de rede real do ML passou a exigir `-F.jpg` com >= 1000 px; saiu a linha "ML não muda" da `TABELA_URL`.

**Como validei sem a correção:** implementação de referência colada por monkeypatch em `disparo`/`api_ofertas` (scratchpad, apagada) fez as 16+8 Python passarem; para o front, cópia do projeto no scratchpad com `urlFotoParaCopiar` patchada, servidor próprio na 8792 sobre `sqlite3 backup` em `mode=ro` do banco real (banco vazio NÃO serve: o runner espera itens) -> 121/121. Mutantes mortos: sem `imagem_permitida`, ML `.webp` no lugar de `.jpg`, `[A-Za-z]`, sem `re.I`; o mutante "sem checar query" é equivalente (regex ancorada no fim).

Armadilha: o front deduz a loja pelo host (só recebe a URL), então a tabela compartilhada só tem URLs cujo host é o da loja; casos de loja trocada ficam só em Python (`test_so_o_cdn_da_propria_loja_e_mexido`).
