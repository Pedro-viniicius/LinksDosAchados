---
name: foto-grande-testes
description: foto_grande/urlFotoParaCopiar - tabela espelhada Python x front, mutantes e teto de 2048
metadata:
  type: project
---

- `TABELA_FOTO_GRANDE` (test_disparo.py) e `TABELA_FOTO` (copiar-imagem.test.html, entre marcadores) são comparadas por ordem: inserir linha nas duas, na mesma posição (script que acha a âncora pelo nome).
- Caso de guarda "query/fragmento volta igual" só prova a guarda se a URL TERMINAR no padrão da loja (`?x=._b_.jpg`, `#b-E.webp`, `?x_tn`); `.jpg?x=1` passa mesmo sem a guarda.
- Teto `TETO_URL_FOTO = 2048` (disparo.py) e `s.length > 2048` (index.html): regex da Amazon é quadrática (0,8 s com 20.000 chars). Teste de borda: 2048 converte, 2049 volta igual.
- Mutante: faça backup do arquivo no scratchpad, mexa no real, rode, restaure e confira com `cmp` (os testes importam o real).
