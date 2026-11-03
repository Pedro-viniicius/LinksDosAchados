---
name: disparo-tela-testes
description: Armadilhas da tela Disparo no index.html e de testes/disparo.test.html (servidor falso no iframe, corridas de hash, dialog, classes que colidem)
metadata:
  type: project
---

Vistas em 2026-11-03, etapa 5 do plano disparo-automatico:

- `testes/disparo.test.html` atende `/api/disparo/*` e `GET/PUT config/templates` com um servidor FALSO em memória, instalado em `W.fetch`; só GET de `/api/items` sai para o servidor real. Por isso roda até num servidor sem as rotas. Integração real: servidor próprio sobre cópia do banco (`sqlite3.backup`), `ACHADINHOS_DISPARO=0` para o agendador não gerar envios sozinho, e script CDP ad hoc para a UI de ponta a ponta.
- Mudar `location.hash` não é síncrono: o helper `abrir()` do teste compara o `#dspTitulo` (recriado a cada rota) e, no mesmo hash, chama `W.eval('rotear()')`. Sem isso o teste lê a tela anterior.
- `.tab`, `.card` e `.more` já têm JS/seletores no resto do app (`render()` põe onclick em todo `.tab`; `#btnCopyAll` lê `.card textarea`). A tela nova usa `.dtab`, `.dcard`; nos testes escope `#telaDisparo .more` porque as ofertas também têm `.more`.
- `<dialog>`: o evento `close` de um diálogo anterior chega depois de o novo abrir e resolvia a Promise errada. `confirmar()` resolve direto no clique e ignora `close` com o diálogo aberto.
- `\p{M}` no regex (flag u) evita `̀-ͯ`, que as ferramentas Write/Edit decodificariam. Ver [[escapes-unicode-ferramentas]].
- `abas.test.html` só passa sobre cópia com `migrar_categorias.py` aplicado (11 de 14 falham no banco não migrado); rodar o migrar cria `backups/` no projeto, então não rodei.
- Telefone no teste: afirmar que nem o texto nem o `innerHTML` nem as URLs do LOG contêm o número inteiro; só o `value` do campo de edição pode.

- Formulário sujo: `rotear()` agora pergunta ao Voltar do navegador (restaura o hash com `history.replaceState`). Teste que deixa o formulário sujo precisa chamar `marcarSujo(false)` ANTES de mudar o hash (o `restaurar()` faz isso), senão trava no diálogo.
- Dois toasts: `#toast` (status) e `#toastErro` (alert); `toast(msg, true)` para erro. O iframe `#app` está no documento do teste, não em `W.document`.
- Mutantes feitos em `index.html` no lugar (cópia em `index.bom.html` no scratchpad, restaurada com `cmp`); com o teste rodando, não edite o arquivo.
- Telefone de teste fictício: `00000000001`; o `grep` de números reais deve voltar vazio.

**How to apply:** ao mexer na tela Disparo ou nas rotas que ela chama (nomes PUT/PATCH, `proximo`, envio.item_pk). Relacionado: [[disparo-testes]], [[chrome-headless-testes]].
