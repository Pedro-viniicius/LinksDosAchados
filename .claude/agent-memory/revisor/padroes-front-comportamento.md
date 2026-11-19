---
name: padroes-front-comportamento
description: Mudança de comportamento padrão do index.html (ex.: aba desmarcável, "sem aba = todos") quebra páginas de teste antigas que a linha de base do lead não roda
metadata:
  type: feedback
---

Quando a mudança troca um padrão do front (o que abre sem nada guardado, opções novas num select, estado vazio), rode TODAS as páginas do front, não só as da linha de base que o lead mandou. Na r1 de "desmarcar a categoria" (2026-11-07), a linha de base trazia só `desmarcar-aba` e `copiar-imagem` (verdes), mas `abas` (5), `abas-qa` (2) e `genero-qa` (1) caíram: elas fixavam "sem activeCat = primeira aba" e "o `#selCat` só tem as abas". No código base (`git archive HEAD`, servidor na 8767) as três passavam.

**Why:** a mudança era pedida pelo dono, então o certo era atualizar os testes antigos ao contrato novo; sem rodar, a suíte ficaria vermelha para a próxima mudança e pareceria regressão de outra pessoa.
**How to apply:** suba a cópia do banco na 8766 (código novo) e o `git archive HEAD` na 8767 (base) e rode `abas`, `abas-qa`, `abrir-e-adicionar`, `genero`, `genero-qa`, `precos`, `precos-qa`, `mensagens`, `disparo` e `disparo-qa` nas duas. Falha só no novo = teste a atualizar ou regressão; leia o teste para decidir qual. Veja também [[revisao-ambiente]] e [[padroes-ui-designer]].

**Rodada 2 (2026-11-07): APROVADO.** As 12 páginas do front ficaram verdes na 8766, e os mutantes das correções (R3 dona da busca pela ordem das abas, R4 try/catch do público, R6 foco no `#addCat`, R7 nome vazio no "+ nova...") derrubaram cada um o seu teste. Mutante por `str.replace` exato (assert count==1) no `index.html` copiado para `<scratchpad>/mut` com servidor.py/disparo.py/genero.py/api_ofertas.py e `testes/rodar.mjs`, servidor na 8767: rápido e não toca no projeto.
Na r2 não chega o texto dos achados da r1, só os IDs: na r1, anote na memória uma linha por achado (ID, arquivo, causa) para conferir depois.
