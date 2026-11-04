---
name: abas-nichadas-front-testes
description: Front das 17 abas (index.html, abas.test.html) - cópia migrada só na cópia, abas fixas mudam testes antigos, mutantes, iframe com largura variável
metadata:
  type: project
---

Etapa 8 do plano abas-nichadas-e-coleta (2026-11-04):

- **Banco migrado sem o `migrar_categorias.py`:** `sqlite3.backup` de `file:achadinhos.db?mode=ro` para a cópia + UPDATE de `cat` por `buscas.json` (NFC) + alias `Caixa inteligente assistente virtual` → TV + subtemas da lista (Teclado e mouse, Placa de vídeo, Carregador rápido, Microfone) + sem `busca` → Casa, Móveis e Ferramentas. Dá 8.888 itens e as contagens do plano (Celulares 1.426, Perfumes 3.051...); 7 abas nascem vazias (úteis para CA-D5). Script em `<scratchpad>/dev-e8-front/copia.py`.
- **17 abas fixas mudam testes velhos:** itens falsos com `cat` inventado agora caem em "Outras" e NÃO viram a aba ativa (antes `cats()` só tinha elas). `abrir-e-adicionar.test.html` precisou de `activeCat = items[0].cat` no `trocarItens`. `genero-qa.test.html` (do qa) tem 2 testes do desenho antigo (M3 "excluir o único item troca de aba", M6 grade de 2 colunas a 320 px).
- **abas.test.html:** o iframe muda de largura (`style.width`) e as media queries respondem (1280, 700, 600/601, 375, 360, 320). Itens falsos: `W.eval('items = '+JSON+'; page=1; render()')`. Aba salva e vazia: não espere por cartões, espere `ofertasProntas`. Contar chamadas: troque `W.contarAbas` por wrapper (função global é gravável).
- **Render em lugar:** as pílulas e o `#selCat` só são refeitos quando a estrutura (grupos + nomes) muda (`dataset.estrutura`); trocar de aba só mexe em `active`, `aria-pressed` e contagens, então o foco fica. `renderCard(card, it, abas)` recebe a lista do render (24 cartões × 10k itens).
- `nao_zera_busca` sobrevive se o teste só troca para OUTRA aba (o render já zera o `#fBusca` porque a busca não existe lá): teste o clique na MESMA aba.
- Mutantes: cópia em `<scratchpad>/dev-e8-front/mut` (servidor 8773, banco `m.db`), `mut.py` troca trechos do `index.html` (25, todos mortos após o ajuste acima; rode `python3 mut.py <nome>` para um só).

**How to apply:** ao mexer em abas, `cats()`, `desenharAbas`, `htmlFormRegra` (categorias em grupos) ou nos testes `abas`/`disparo`/`genero`. Relacionado: [[estados-foco-front-testes]], [[genero-front-testes]], [[disparo-tela-testes]].
