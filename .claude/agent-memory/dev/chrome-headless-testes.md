---
name: chrome-headless-testes
description: Armadilhas do Chrome headless (156) ao testar o front (canvas, clipboard, rede real) e como rodar em tempo real via CDP com node 22
metadata:
  type: project
---

Testes do front em `testes/*.test.html` rodam no Chrome headless. Armadilhas vistas em 2026-11-03 (Chrome 156, node v22 em ~/.nvm):

- `--virtual-time-budget`: `fetch` real funciona, mas `createImageBitmap` de uma foto real fica pendente e o tempo virtual acaba antes (dump sai no meio). Polling com `setTimeout` consome o orçamento rápido.
- `--timeout=N` (tempo real) com `--dump-dom`: o `fetch` aos CDNs ficou pendente; não confiável.
- O que funcionou: Chrome com `--remote-debugging-port`, navegar por CDP (`Page.navigate`) e consultar o DOM com `Runtime.evaluate` a cada 500 ms, usando o `WebSocket` global do node 22 (sem dependência). O `qa` fez disso o runner do projeto: `node testes/rodar.mjs copiar-imagem` (servidor 8765 no ar; espera `RESULTADO: OK`).
- Stubs do qa montam `new W.Response(...)` com `r.url` vazio quando não passam URL: validação de `r.url` no código precisa aceitar vazio, senão quebra os casos de sucesso.
- Área de transferência real no headless: `Browser.grantPermissions` com `clipboardReadWrite` e `clipboardSanitizedWrite` mais `Emulation.setFocusEmulationEnabled`. Assim `ClipboardItem` com Promise e `clipboard.read()` funcionam, sem gesto.
- Página de teste com iframe: use `window.onload` do pai, não `iframe.onload` (a página pode carregar antes de o handler ser ligado via CDP).
- `pkill -f "http.server 8799"` mata o próprio shell (o padrão aparece na linha de comando). Use `^python3 -m http[.]server`. Servidor auxiliar: suba com `run_in_background`, porque `&`/`setsid` morre com o shell.
- `TXT_IMG` e `items` são `const`/`let`: não ficam em `window`; o teste lê com `win.eval('TXT_IMG')`.

**How to apply:** ao provar algo com canvas, imagem real ou clipboard, prefira o CDP em tempo real; se o `qa` usar `--virtual-time-budget`, avise do risco no relatório. Relacionado: [[copiar-imagem]].
