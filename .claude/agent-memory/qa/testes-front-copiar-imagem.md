---
name: testes-front-copiar-imagem
description: Como rodar e depurar a página de teste testes/copiar-imagem.test.html (Chrome headless, iframe no index.html real) e armadilhas já encontradas
metadata:
  type: project
---

Suíte do front = páginas `testes/*.test.html` (sem dependência), servidas pelo `servidor.py` real em :8765.
Comando que funciona: `node testes/rodar.mjs copiar-imagem` (Chrome headless em tempo real via CDP, ~3 s, exit 0 só com `RESULTADO: OK`). O comando do plano (`--virtual-time-budget=30000 --dump-dom | grep`) NÃO serve: com fotos reais o dump sai com `RESULTADO: PENDENTE`. Chrome 156, node 22.

Mutantes (cópia do index.html em servidor falso próprio, nunca no real) verificados em 2026-11-03: sem filtro de host, sem fundo branco, sem `/img-not-available/`, sem fallback, write após o download, credentials include, sem guarda de clique duplo, sem SL1000, sem checar https. Todos derrubam teste. Lição: o gif do `img-not-available` precisa ser imagem decodificável no stub, senão o mutante sobrevive pela falha de decodificação.

**Armadilhas**
- `--dump-dom` imprime também o código-fonte e comentários da página: o `grep` casaria com o próprio script. Por isso as palavras de resultado ficam montadas por concatenação (`'RESULT'+'ADO: '`, `'FALH'+'OU: '`) e nunca literais no arquivo. Não escreva as duas palavras inteiras nem em comentário.
- `items`, `templates`, `TXT_IMG`, `HOSTS_FOTO` são `const`/`let` do index.html: acessar pelo iframe com `W.eval('TXT_IMG')`. Funções declaradas com `function` ficam em `W.<nome>`.
- Erros que o stub gera têm que ser do realm do iframe (`new W.TypeError`, `new W.DOMException`), senão `instanceof` no código do produto falha.
- O teste guarda `W.fetch` do iframe: POST/PATCH/PUT/DELETE em /api/ nunca saem (viram `VIOL`), e `W.open` é trocado. Ao fim compara o texto de `/api/items` com o do início.
- Validar o teste sem tocar nos dados reais: servidor falso em porta própria (scratchpad, `srv.py` com `/api/items` e `/api/config/*` fixos) servindo cópia do `index.html` e do `servidor.py`.
- O scratchpad da sessão é compartilhado com dev/designer: eles sobem `python3 -m http.server 8799` ali. Não use 8799 e nunca `pkill -f` por padrão; guarde o `$!` do próprio processo (matei o servidor do dev por engano em 2026-11-03 e tive de reiniciar).

**Why:** primeira suíte do projeto (ADR 2 do plano copiar-imagem). **How to apply:** novas features do front estendem esse padrão em outro `testes/<nome>.test.html`.

**Rodada 2 (2026-11-03):** o stub de `write` precisa rejeitar com atraso (como o Chrome real) e há um modo `ignorarPromises`; sem isso o mutante "sem `png.catch`" sobrevive. Ouvintes `unhandledrejection`/`error` têm de estar também na janela do iframe (`ouvirErros(W)`). Payload de XSS em atributo: `ml" data-x="1` (a tag `<b>` não pega falta de `esc` em `class="..."`). Mutantes extras mortos: sem clearTimeout, toast fixo, sem esc na loja, sem validar host final, aria-label fixo.
