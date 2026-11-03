# Plano técnico: Copiar imagem no card
- Brief: não há; o pedido do lead (2026-11-03) faz o papel dele. Spec de interface: `docs/produto/specs/copiar-imagem.md`
- Data: 2026-11-03

## Objetivo e critérios de aceite
O dono copia a foto do produto direto do card, cola no WhatsApp Web e manda a mensagem como legenda. Hoje a prévia de link sai sem foto, porque a Amazon bloqueia o robô do WhatsApp.

- CA1: todo card com `data.imagem` tem o botão "Copiar imagem". O clique põe a foto na área de transferência como `image/png` (via `ClipboardItem`), pronta para Ctrl+V no WhatsApp Web.
- CA2: funciona com JPEG da Amazon (`m.media-amazon.com`) e WEBP do ML (`http2.mlstatic.com`), sempre convertendo para PNG. Na Amazon, copia em resolução maior (até 1000 px) sem regravar o banco e, se essa versão falhar, volta para a URL gravada.
- CA3: card sem foto (`data` nulo ou `data.imagem` vazio, hoje 55 itens da Amazon) mostra o botão com `aria-disabled` e, ao clicar, explica o motivo sem tentar copiar (opção "desabilitado com explicação", escolhida na spec).
- CA4: há retorno de carregando, sucesso e erro. O erro distingue **rede**, **imagem indisponível**, **área de transferência bloqueada** e **navegador sem suporte**, e diz o que fazer. *Ajuste:* incluí "bloqueada" porque é uma falha real e distinta no Chrome (permissão ou foco), já prevista na spec.
- CA5: não mudam o texto da mensagem (`buildMsg`), os links de afiliado, o banco, a API nem o que as ações atuais fazem. "Copiar" continua sendo a única ação Etiqueta. *Ajuste:* as únicas mudanças fora do botão novo são as de apresentação da spec: o selo "✓ Mensagem copiada", o aviso "cole como legenda" depois de copiar a imagem e "Abrir na loja" em `ghost`.
- CA6: sem dependência nova nem mudança em `servidor.py`.

## Contexto atual
- O card é montado em `renderCard`, em `index.html:233-261`. A miniatura sai de `d.imagem`, com `<img loading="lazy" alt="">` sem `crossorigin` (`index.html:238`). As ações ficam em `index.html:241-253`: `.copy` (CTA), `.open` e o `<details class="more">`.
- O handler de "Copiar" usa `navigator.clipboard.writeText`, marca `.done` e mostra um toast (`index.html:255`). O toast é a função global `toast(m)` (`index.html:192`). O `.status` do card tem `role="status"` (`index.html:240`), e o padrão de erro já existe em `fetchItem` (`index.html:221-231`, com `st.className='status err'`).
- `renderCard` e `buildMsg` são declarações `function` e por isso ficam em `window`. `items`, `templates` e `toast` são `let`/`const` e não ficam (`index.html:192-202`). Isso importa para o teste (etapa 3).
- O `data` vem de `linha_para_item` (`servidor.py:52-55`). É `null` quando `tem_dados=0`, e senão traz `imagem` como string. A Amazon grava `img.s-image` da busca (`coletar_amazon.py:64-70`) ou `#landingImage` pelo `/api/fetch` (`servidor.py:111`).
- O servidor escuta só em `127.0.0.1` (`servidor.py:225`), não manda CSP (`servidor.py:123-129`) e serve qualquer arquivo estático da pasta (`servidor.py:172`).
- Não há `docs/produto/decisoes.md` nem brief. O histórico tem dois commits; o último é o redesenho (`309bb89`).

**Verificado por mim nos CDNs** (2026-11-03, `curl` pontual, sem coleta):
| Fato | Resultado |
|---|---|
| Hosts em `/api/items` | 2.704 `http2.mlstatic.com`, 2.570 `m.media-amazon.com` e 55 vazios. Nenhum outro host. |
| Padrão da Amazon | 100% `…/images/I/<id>._AC_UL320_.jpg` (por exemplo, 320x208) |
| Amazon `._AC_SL1000_.jpg` | 200, JPEG de até 1000 px no lado maior e sem ampliar (uma original pequena veio em 651x785), de 20 a 45 KB |
| Padrão do ML | 100% `D_Q_NP_2X_<id>-E.webp`, 560x560, cerca de 10 KB. Já é suficiente; não reescrever. |
| CORS | `access-control-allow-origin: *` **com e sem** o header `Origin`, nos dois CDNs, sem `Vary: Origin`. Por isso a cópia em cache vinda do `<img>` não quebra o `fetch` CORS. |
| Foto inexistente na Amazon | HTTP 400 `text/plain` |
| Foto inexistente no ML | 302 para `…/img-not-available/…/E@2x.gif`, que responde 200 `image/gif`. **Precisa de detecção explícita**, senão o gif "indisponível" vai para a área de transferência. |

Conclusão: `fetch` + canvas no front funciona sem proxy. Não há caso que peça fallback no servidor. O único fallback é o da Amazon: se `SL1000` falhar, tentar a URL gravada.

## Abordagens consideradas
| Abordagem | Prós | Contras | Risco |
|---|---|---|---|
| A. `fetch` CORS + `createImageBitmap` + `<canvas>` → PNG no front | Não toca `servidor.py`; CORS já confirmado; só código no `index.html` | Depende de o CDN manter `ACAO: *` | Baixo |
| B. Proxy `/api/imagem?url=` no `servidor.py` | Imune a mudança de CORS | Mexe em regra de negócio, abre SSRF no servidor e duplica o que o navegador já faz | Médio |
| C. Copiar o `<img>` já carregado | Sem nova requisição | A miniatura é de 320 px, e um `<img>` sem `crossorigin` suja o canvas | Alto |

**Decisão: A.** B fica como contingência e só entra com uma decisão nova do dono, se um CDN tirar o CORS.

## Decisão
- A lógica fica no `index.html`, logo depois de `fetchItem`, em três funções globais (`function`, não `const`, para o teste alcançar).
- O clique chama `navigator.clipboard.write` **de forma síncrona**, passando uma `Promise<Blob>` ao `ClipboardItem`. Assim o gesto do usuário não expira durante o download. Se a promise falhar, o motivo vem do erro **da nossa promise**, e não do erro genérico que o `write` devolve.
- O canvas é pintado de branco antes de desenhar a foto (`--fundo-imagem`). Sem isso, um WEBP ou PNG transparente vira fundo preto quando o WhatsApp converte para JPEG.
- O PNG sai sempre: o Chrome só aceita `image/png` como imagem no `ClipboardItem`.

## Esquema e contratos
Não há mudança de banco nem de API. Contratos novos no `<script>` do `index.html`:

```js
const HOSTS_FOTO = ['m.media-amazon.com', 'http2.mlstatic.com'];
// TXT_IMG: textos da spec (etapa 1). Chaves: botao, carregando, ok, toastOk, toastLegenda,
//          semFoto, rede, indisponivel, bloqueado, semSuporte

function urlFotoParaCopiar(url)   // string → string
//  Amazon: troca o sufixo `._<mods>_.<ext>` por `._AC_SL1000_.<ext>` (regex /\._[^/]*_\.(jpe?g|png|webp)$/i).
//  Qualquer outro host ou formato: devolve a url como está.

async function fotoComoPng(url)   // → Promise<Blob image/png>; erro com e.motivo ∈ {'rede','indisponivel'}
//  1. Se não for https ou o host não estiver em HOSTS_FOTO: motivo 'indisponivel'.
//  2. fetch(u, {mode:'cors', credentials:'omit', signal: AbortSignal.timeout(15000)}).
//     TypeError ou AbortError/TimeoutError → 'rede'.
//  3. !r.ok, ou r.url contendo '/img-not-available/', ou content-type fora de image/* → 'indisponivel'.
//  4. createImageBitmap(blob); se rejeitar → 'indisponivel'.
//  5. Canvas no tamanho natural, fillRect branco, drawImage, toBlob('image/png'); blob nulo → 'indisponivel'.
//  Tenta primeiro urlFotoParaCopiar(url). Se falhar com 'indisponivel' e a URL for diferente, tenta a url original.

function copiarImagem(it, card, btn)   // sem retorno; cuida dos estados
//  - sem it.data?.imagem: mostra TXT_IMG.semFoto em .status.err e não chama nada
//  - btn em carregando (aria-busy="true"): ignora o clique (evita clique duplo)
//  - sem navigator.clipboard?.write ou ClipboardItem: motivo 'semSuporte', sem fetch
//  - carregando: aria-busy e aria-disabled = "true", texto TXT_IMG.carregando, .status limpo
//  - const png = fotoComoPng(it.data.imagem);
//    await navigator.clipboard.write([new ClipboardItem({'image/png': png})])
//  - sucesso: data-estado="copiada", texto TXT_IMG.ok, card.classList.add('img-done'), toast(TXT_IMG.toastOk)
//  - falha: motivo = (await png.then(()=>null, e=>e.motivo||'rede')) ?? (NotAllowedError → 'bloqueado', senão 'rede');
//           o texto volta a TXT_IMG.botao e .status.err recebe 'Erro: ' + TXT_IMG[motivo]
```

Contrato de marcação entre o designer (etapa 1) e o dev (etapa 2):
- Botão `<button type="button" class="secondary copyimg">`, logo depois de `.copy`.
- Sem foto: `aria-disabled="true"` e `aria-describedby="semfoto-<it.id>"`, apontando para um `<span class="sr" id="semfoto-<it.id>">`.
- O CSS se apoia só em `.copyimg[aria-disabled="true"]`, `.copyimg[aria-busy="true"]` e `.copyimg[data-estado="copiada"]`. O dev não cria outras classes de estado.
- Handler de "Copiar" (`index.html:255`): o texto do toast vira `card.classList.contains('img-done') ? TXT_IMG.toastLegenda : 'Mensagem copiada!'`. O resto da linha fica igual.

Mapa de motivo para texto. A spec tem um texto só para "não baixou"; o CA4 pede rede e indisponível separados.
| Motivo | Texto |
|---|---|
| `rede` | o "Erro, não baixou a foto" da spec |
| `indisponivel` | **proposta, o designer confirma:** "Esta foto não está mais disponível na loja. Abra na loja e copie a imagem de lá." |
| `bloqueado` | o "Chrome bloqueou a área de transferência" da spec |
| `semSuporte` | o "navegador sem suporte" da spec |
| `semFoto` | o "Sem imagem" da spec |

## Etapas
| # | Etapa | Arquivos | Verificação | Responsável | Grupo | Sensível | CAs |
|---|---|---|---|---|---|---|---|
| 1 | Marcação e estilo conforme a spec: o botão `.secondary.copyimg` em `renderCard`, ainda sem handler; o `span.sr` "sem foto" com `aria-describedby` e o `aria-label="Copiar imagem de <esc(titulo)>"`; o CSS de `.copyimg` (nowrap, `min-width` em `ch`, estados pelos atributos do contrato); `.open` em `ghost`; o selo `.feito` com "✓ Mensagem copiada"; a constante `TXT_IMG` com as 10 chaves | `index.html` (CSS em `<style>`, `renderCard` em 236-253, constante junto de `LOJA` em 189) | `python3 -m py_compile servidor.py coletar_amazon.py`; `curl … /api/items` dá 200; abrir em 320, 375 e 1280 px, claro e escuro, com card com e sem foto; `buildMsg` sem diff (`git diff index.html`) | designer | A | não | CA3, CA4 (textos), CA5 |
| 2 | Lógica: `HOSTS_FOTO`, `urlFotoParaCopiar`, `fotoComoPng` e `copiarImagem`, como no contrato, entre `fetchItem` e `renderCard`; ligar `card.querySelector('.copyimg').onclick` em `renderCard`; trocar o toast de "Copiar" pela condição de `img-done`; nada de `innerHTML` com URL e nada de `console.log` de URL | `index.html` (`<script>` só, de 221 a 261) | os dois comandos da linha de base; no Chrome do dono, copiar a foto de um card da Amazon e de um do ML e colar no WhatsApp Web; `git diff index.html` sem mexer em `buildMsg`, `api`, `fetchItem`, `.del` e `.mv` | dev (opus) | B | **sim** (rede, entrada externa) | CA1, CA2, CA3, CA4, CA5, CA6 |
| 3 | Página de teste sem dependência, com o roteiro abaixo | `testes/copiar-imagem.test.html` (novo) | `node testes/rodar.mjs copiar-imagem` dá `RESULTADO: OK` (o `--virtual-time-budget --dump-dom` previsto antes não termina; trocado na rodada 1) | qa | B (escreve em paralelo; roda depois da 2) | não | CA1 a CA6 |
| 4 | Prova manual que só um humano faz: colar no WhatsApp Web (uma foto da Amazon, uma do ML e uma de card sem foto) e conferir a qualidade da imagem | nenhum | o dono confirma: a foto abre a tela de legenda, e a mensagem colada na legenda sai igual à de "Copiar" | lead com o dono | C | não | CA1, CA2 |
| 5 | Registrar o comando de teste em "Verificação" no `CLAUDE.md` (texto no fim deste plano) | `CLAUDE.md` | leitura | lead | C | não | — |

As etapas 1 e 2 mexem no mesmo arquivo e **não podem rodar ao mesmo tempo**. A etapa 3 não compartilha arquivo com a 2.

**Roteiro do teste (etapa 3).** Um `iframe` carrega `/index.html` do servidor real, que só recebe GETs. Os itens falsos são montados com `win.renderCard(div, itemFalso)` dentro do iframe. O teste stuba `win.navigator.clipboard.write` para capturar o `ClipboardItem`, e `win.fetch` nos casos de erro. **Nunca clica** em `.del`, `.mv`, `.fetch`, `#saveLinks` nem `#saveTpl`.
1. CA1 e CA2 (rede real, duas leituras pontuais): no item Amazon `…/41p2HTchUrL._AC_UL320_.jpg` e no item ML `…D_Q_NP_2X_624792-MLU75859080805_042024-E.webp`, o clique em `.copyimg` faz o `write` receber um item com `types` igual a `['image/png']`. O `getType` dá um PNG que decodifica com largura > 0, e na Amazon a largura passa de 320. O botão fica com `data-estado="copiada"` e o card, com `img-done`.
2. CA2: `win.urlFotoParaCopiar` em uma tabela de entradas: Amazon com `UL320`, Amazon com `SX300_SY300_QL70`, o id com `+`, o ML sem mudança e uma string vazia.
3. CA3: item com `data:null` e item com `imagem:''`. O botão tem `aria-disabled="true"`; o clique põe o texto `semFoto` em `.status.err`; o `write` e o `fetch` não são chamados.
4. CA4: o `fetch` stubado com TypeError leva ao texto `rede`; status 400 e `r.url` com `/img-not-available/` levam a `indisponivel`; o `write` rejeitado com `NotAllowedError` leva a `bloqueado`; `delete win.ClipboardItem` leva a `semSuporte`, sem chamar o `fetch`; durante o carregando aparece `aria-busy="true"`, e um segundo clique não chama um segundo `fetch`.
5. CA5: o `sha256sum` de `curl -s localhost:8765/api/items` é igual antes e depois da execução. O `.copy` de um item falso grava o mesmo texto de `win.buildMsg(item)`. O link de afiliado aparece intacto nesse texto.
6. CA6: `git diff --stat` mostra só `index.html` e `testes/`; `servidor.py` fica sem diff.

## Pontos para o seguranca
- Entrada externa: `data.imagem` vem de scraping. A defesa é aceitar só `https:` e host em `HOSTS_FOTO` antes do `fetch`, para que uma URL forjada no banco não vire requisição a `localhost:8765/api/...` nem a outro host.
- `credentials:'omit'` e `mode:'cors'`: nenhum cookie vai aos CDNs. Timeout de 15 s.
- A imagem é decodificada pelo navegador (`createImageBitmap`), dentro da sandbox. Não há leitura de bytes em JS nem `innerHTML` com a URL. O `aria-label` usa `esc(titulo)`.
- A área de transferência só é escrita depois de um clique do usuário. Não há leitura dela no código de produção; só o teste usa um stub.
- `servidor.py` não muda: nenhuma rota nova, e o SSRF da abordagem B fica de fora.
- A página `testes/*.test.html` fica servida em `127.0.0.1` (`servidor.py:225`) e não grava nada. Conferir que ela não chama métodos de escrita.

## Riscos e como reverter
| Risco | Mitigação | Reverter |
|---|---|---|
| Um CDN tira o CORS ou muda o padrão de URL | O erro aparece como `rede`/`indisponivel` e diz o que fazer. O fallback da Amazon cobre o `SL1000` | Decisão nova para a abordagem B. A feature some com `git checkout -- index.html` |
| `ClipboardItem` com `Promise` falha no Chrome do dono (**não verificado** nesta versão) | O dev confirma na etapa 2. Se falhar, usar `await fotoComoPng()` e depois `write(blob)`, aceitável no Chrome com a página em foco | Troca de duas linhas em `copiarImagem` |
| O gif "não disponível" do ML vai para a área de transferência | Detecção de `/img-not-available/` em `r.url` (teste 4) | — |
| O redesenho muda o comportamento de "Copiar" | O teste 5 compara com `buildMsg`; o revisor confere o diff de 255 | `git revert` do commit |
| Não há banco nem migração | — | — |

## Perguntas em aberto e premissas adotadas
- **Premissa:** "Copiar imagem" não marca `.done` nem o selo, que continuam sendo só da mensagem, como diz a spec.
- **Para o designer:** confirmar o texto de `indisponivel`. Na spec, o texto de `bloqueado` fala do cadeado; a mesma falha também acontece quando a página perde o foco. Sugiro acrescentar "clique na página e tente de novo".
- **Para o dono (fora deste escopo):** pôr imagem e texto no mesmo `ClipboardItem` (`image/png` + `text/plain`) economizaria um passo, mas **não verifiquei** se o WhatsApp Web usa o texto como legenda. Vale um teste à parte, se o dono quiser.
- **Ordem dos botões** (pergunta da spec): não muda a lógica. Fica com o dono.
- **Resolução:** PNG em até 1000 px na Amazon e 560 px no ML, o que responde à pergunta da spec. Fica abaixo do que o WhatsApp recomprime.

## ADR
**ADR 1: copiar a foto no navegador (fetch CORS + canvas), sem proxy.** Os dois CDNs mandam `ACAO: *` (verificado). Um proxy no `servidor.py` abriria SSRF e mexeria em regra de negócio sem ganho hoje. Revisar se algum CDN mudar o CORS.

**ADR 2: primeira forma de teste do projeto, uma página `testes/*.test.html` rodada no Chrome headless com `--dump-dom`.** Não exige dependência (o Chrome já está em `/usr/bin/google-chrome`) e testa o `index.html` real num iframe, alcançando as funções declaradas com `function`. A alternativa com node exigiria extrair o JS do HTML e não teria canvas nem clipboard. Consequência: a lógica testável do front precisa ficar em `function` global.

**Texto para o lead preencher em "Verificação" no `CLAUDE.md`, depois da aprovação:**
> Testes do front: com o servidor no ar, `node testes/rodar.mjs <nome>` deve imprimir `RESULTADO: OK` (exit 0). As páginas de teste ficam em `testes/`, só fazem GET na API e usam itens falsos montados com `renderCard`. Funções do front que precisam de teste ficam declaradas com `function`, para o iframe alcançar.
