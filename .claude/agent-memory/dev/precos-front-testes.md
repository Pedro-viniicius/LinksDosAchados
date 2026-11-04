---
name: precos-front-testes
description: Front da idade do preço (index.html, testes/precos.test.html) - [hidden] com display, details fechado, toast fixo, proxies no curl, itens falsos sem preco_em, recortes do index.html nos testes do qa, mutantes em projeto-cópia
metadata:
  type: project
---

Etapa 6 do plano atualizar-precos (2026-11-04):

- **`[hidden]` perde para `display:flex/grid` de classe:** `.cmd-linha` e `.qp-dl` precisaram de `.x[hidden]{display:none}`. Teste com `checkVisibility()` (pega também o `<details>` fechado, que o `getClientRects` não pega: content-visibility).
- **Testes velhos com item falso sem `preco_em`:** `copiar-imagem.test.html` (`itemFalso`) cria cartão sem `preco_em`, que agora é "velho" e muda o toast de "Mensagem copiada!". Conserto de 1 linha no `itemFalso`: `preco_em` de agora (ISO local, `new Date()` formatado). Provado em cópia: 72 de 72. `abrir-e-adicionar` e os outros não notaram.
- **`abas` CA-D11 e CA-D14 falham por dado** na cópia atual do banco (a coleta cresce a base: esperado 10.400, obtido 12.772). Provado com o `index.html` do HEAD num projeto-cópia na 8767: as mesmas 2 falhas.
- **`curl` com `http_proxy` exportado devolve vazio para localhost:** use `--noproxy '*'`. Os proxies só entram no ambiente do servidor (`http_proxy=... python3 servidor.py` na mesma linha), nunca na shell que roda o runner.
- **Espião do fetch instalado no `iframe.onload` perde a carga inicial** (o `carregarOfertas` já saiu). Para provar que o app lê `config/preco_validade_horas` na carga, chame `carregarOfertas()` de novo e olhe o REG.
- **`#toast` nasce com "Copiado!" no HTML:** teste que lê o toast logo depois do clique lê o texto fixo. Limpe o toast e espere a classe `show` (`clicarEEsperarToast`).
- **Placeholder `{ARG}` com chaves:** `replace('{ARG}', ...)` leva as chaves junto; o ML precisa de `{}`/`{cat: "X"}` completos no ARG. Use função no replace (`()=>arg`): nome de categoria com `$&` vira lixo no replace de string.
- **Hash no `precos.test.html`:** uma só mudança (`#precos`); o "sair do disparo" chama `rotear()` à mão com o hash já em `#precos`; abrir a página já em `#precos` é carga, não navegação. Sem FALSO para `/api/disparo/regras|fila` o `atualizarAtencao()` da saída do disparo pega o guarda: GET de `/api/disparo/*` vai ao servidor real.
- Mutantes: projeto-cópia em `<scratchpad>/e6/projvelho` (servidor na 8767, banco `copia2.db`), `mut.py` troca trechos do `index.html` e roda `precos`; ~17 s por mutante.

Rodada 1 de correções (2026-11-04):

- **Testes do qa que recortam o `index.html` por marcador** (`trecho_do_front` em `test_atualizar_precos_qa.py`): `ParidadeDoFront` pega de `const PRECO_VALIDADE` até a linha de `const validadeValida`; `ComandoCopiavel` de `function aspasShell` até `  return bloco.cmd.replace`. Constante nova usada dentro dessas funções mas declarada fora do trecho dá `ReferenceError` no node: deixe o regex inline ou dentro do trecho.
- O qa reescreve esses testes em paralelo (o do Q1 passou a chamar `validadeDoTexto`, o da categoria passou a aceitar a recusa de Cc/Cf): antes de relatar conflito, rode de novo no fim.
- D1 (contador e cartão da regra sem os itens velhos) quebra testes antigos cujos itens falsos não têm `preco_em`: `genero.test.html` CA5 (2), `disparo.test.html` CA2 (conta esperada sem `itemComPrecoVelho`) e `disparo-qa` contador.
- Mutantes: um `mut.py` com dicionário trecho→troca num projeto-cópia (servidor.py, disparo.py, genero.py, api_ofertas.py, index.html, testes/rodar.mjs e a página), ~25 s cada. A saída do python fica presa no buffer quando vai para arquivo (use `python3 -u`). `pkill -f "<script>"` mata o próprio shell: pare pelo pid do `ss -ltnp`.

**How to apply:** ao mexer na idade do preço, no quadro ou em testes que montam cartão com item falso. Relacionado: [[atualizar-precos-testes]], [[abas-nichadas-front-testes]], [[estados-foco-front-testes]].
