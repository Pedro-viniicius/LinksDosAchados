---
name: desmarcar-aba-testes
description: Categoria desmarcável no index.html (activeCat vazio) - testes antigos que fixavam "abre na primeira aba", painel Adicionar fechado impede foco, curl e proxy, mutantes em cópia do index
metadata:
  type: project
---

Rodada 1 de correção de "desmarcar a categoria" (2026-11-07):

- `activeCat === ''` é válido e é o padrão sem nada guardado: testes que dependiam de "abre na primeira aba" (`abas`, `abas-qa`) precisam de `abrirApp(PRIMEIRA)` quando conferem pílula ativa; o `#selCat` ganhou a 1ª opção `''` ("Todas as categorias", conta `items.length`), então comparações de opções esperam `['', ...ORDEM]`.
- Foco em `#addCat` só funciona com o painel aberto (`#addBox.open`); o teste abre o painel antes de clicar em Salvar.
- Stub de `localStorage` indisponível precisa cobrir `getItem`, `setItem` E `removeItem` (o `guardarGenero` usa o último; o mutante sem try/catch sobreviveu até isso).
- `curl` com `http_proxy` exportado para `127.0.0.1:9` falha com código 7: use `--noproxy '*'`. `rodar.mjs` com proxies exportados: `NO_PROXY=127.0.0.1`.
- Mutantes: trocar trecho do `index.html` real com cópia de segurança no scratchpad e restaurar com `cp` + `cmp` (o servidor real lê o arquivo a cada GET).
- `precos` + `precos-qa` + `mensagens` somam >2 min: rode em background.

**How to apply:** ao mexer em `escolherAba`, `render()` ou nos testes de abas. Relacionado: [[abas-nichadas-front-testes]], [[estados-foco-front-testes]].
