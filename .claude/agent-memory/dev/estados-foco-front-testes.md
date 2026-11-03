---
name: estados-foco-front-testes
description: Armadilhas dos estados da lista (carregando/erro/vazio) e do foco (M3/M5) no index.html e em genero.test.html - srcdoc com fetch trocado, corrida do 2º script, mutantes
metadata:
  type: project
---

Vistas na etapa 9 do plano genero-nas-categorias (2026-11-03):

- **Simular API fora do ar na carga:** o app busca os itens logo no script. Em `genero.test.html`, `abrirAppComApi()` baixa `/index.html`, injeta depois de `<head>` um `<script>` que troca `window.fetch` por `window.parent.FETCH_APP` e carrega por `iframe.srcdoc` (mesma origem, localStorage vale). `srcdoc` ganha de `src`: o `abrirApp()` faz `removeAttribute('srcdoc')`. Erros do iframe vão por `window.parent.ERRO_APP` (o `ouvirErros` chegaria tarde). Esses testes ficam no FIM da página (depois deles `W` é o app simulado).
- **Corrida do 2º script:** erro de rede imediato fazia o IIFE do 1º script chamar `iniciarDisparo()` antes de o 2º `<script>` ser avaliado ("not defined"). Resolvido esperando `DOMContentLoaded` se `readyState==='loading'`.
- `api()` do index.html devolve o corpo de erro como dado (não checa `r.ok`): a carga usa `carregarJson()` (checa `ok`) e `Array.isArray`.
- `render()` sai cedo se `!ofertasProntas`; testes que fazem `items = ...; render()` depois do load continuam valendo.
- Foco: `guardarFoco()`/`devolverFoco()` no `render()` (aba por `data-c`, paginação por `data-a` + topo/rodapé; botão desabilitado cai no vizinho; sem paginação cai na aba ativa), `focus({preventScroll:true})` para não brigar com o `scrollTo` do clique.
- "Sem gênero" + filtro de título zera a contagem e cai em Todos: a lista vazia com público "Sem gênero" não existe pela tela (não teste).
- Mutantes: cópia do projeto em `<scratchpad>/dev-e9/mut` (servidor na 8792) com `mut.py` trocando trechos do `index.html`; 20 de 20 mortos (o `pref_pg` só morreu depois de testar "Anterior" que leva à página 1).
- `abas.test.html`: o esperado do contador sai das lojas presentes na API (nome das lojas escrito no teste, não lido do index.html).

**How to apply:** ao mexer em `render()`, na carga inicial ou no foco da paginação/abas. Relacionado: [[genero-front-testes]], [[chrome-headless-testes]].
