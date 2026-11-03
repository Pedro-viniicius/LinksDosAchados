---
name: ui-index-html
description: Onde ficam estilos/tokens do index.html e armadilhas de teste e captura (cabeçalho, barra de lista, disparo)
metadata:
  type: project
---

- Tudo em `index.html` (CSS no topo, tokens em `:root`). Cabeçalho só tem logo + Adicionar links + Disparo (+ `#btnVoltarCab` em `body.em-disparo`); Template, Editar templates e Copiar todas ficam em `.barra-lista` dentro de `#telaOfertas`; `#count` abaixo das abas.
- `#tplBox`/`#addBox` continuam no cabeçalho; "editar-templates" do formulário do disparo clica `#btnTpl` por JS (funciona com o botão oculto).
- Capturas com aba Perfumes e modo escuro: CDP (Emulation.setEmulatedMedia + localStorage `activeCat`), script ad hoc; `--screenshot` do Chrome abre sempre a aba padrão.
- `disparo-integracao` precisa de banco COM itens (cópia do real sem número/regra); banco vazio dá "FALHOU (preparação)".
- Teste D5 de `testes/disparo.test.html` reflete M7 (cabeçalho sem Template no disparo).
