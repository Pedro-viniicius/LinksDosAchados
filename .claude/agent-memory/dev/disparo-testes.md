---
name: disparo-testes
description: Armadilhas ao testar o disparo.py (paridade buildMsg x montar_mensagem, expiração do manual, mutantes equivalentes) e o scratchpad compartilhado entre agentes
metadata:
  type: project
---

Vistas em 2026-11-03, nas etapas 1 a 3 do plano disparo-automatico:

- **Paridade da mensagem:** o "esperado" dos casos em `testes/mensagens.test.html` foi gerado rodando no node o `buildMsg` extraído do `index.html` (regex `function buildMsg\(it\)\{[\s\S]*?\n\}\n` + `eval`, com `templates`/`current` locais), e não pelo porte Python. Um fuzz de 3.000 casos (placeholders, `$&`, `$'`, `$$`, U+FEFF, U+0085, `\n` em série) deu 0 diferenças. Se o `buildMsg` mudar, gere de novo assim.
- O `replaceAll` do JS interpreta `$$`, `$&`, `` $` `` e `$'` no valor (cupom "R$100" fica literal porque `$1` sem grupo não troca). O `\s` do JS é o mesmo conjunto do `trim`: um mutante `trim` → `replace(/^\s+|\s+$/g,'')` é equivalente.
- O comentário do topo da página cita `<script type="application/json" id="casos">`: o regex que lê o bloco precisa de âncora no começo da linha (`re.M`).
- **Transporte manual:** o `pendente` de ontem vira `expirado` no tick e deixa de bloquear a repetição (decisão do plano). Teste de "não repetir" entre dias tem que usar transporte automático (o `Gravador` do teste), senão o item volta.
- Mutantes equivalentes conhecidos: tirar a 1ª checagem de `user_version` no `migrar` (a releitura dentro do BEGIN IMMEDIATE cobre) e tirar o "vazio no fim" do `maior_preco` (preço 0 já cai no fim).
- O scratchpad da sessão é dividido com outros agentes (havia `mutantes6.py`, `srv.log` etc. de outros). Use nomes com prefixo da tarefa e confira com `ls` antes de gravar.

Vistas na etapa 4 (ligar ao servidor.py):

- `test_servidor.py::test_ca6_antigo_rotas_do_fonte_sem_proxy_de_imagem` lista todo literal `'/api/...'` do `servidor.py` (inclusive em docstring que comece com aspas seguidas de `/api/`) e exige a lista exata. O prefixo `/api/disparo/` mora no `disparo.PREFIXO`.
- `test_migrar_categorias.py` e `test_classificar_lista*.py` copiam o `servidor.py` para um tmp **sem** o `disparo.py`: `import disparo` no topo do servidor quebra essas suítes. Por isso o import é local (`criar_banco`, `despachar_disparo`, `iniciar_disparo`).
- O `corpo()` do servidor exige `Content-Type: application/json` até em POST sem corpo (o front sempre manda). Teste de `POST regras/<id>/agora` precisa mandar `{}`.
- O slot do "agora" tem resolução de segundo: dois POST no mesmo segundo criam só uma vez (teste precisa de `sleep(1.1)`).
- Prova do servidor novo com dados reais: cópia por `backup` de `file:achadinhos.db?mode=ro` no scratchpad, servidor em porta livre, `rodar.mjs` com `PORTA`; a cópia sai com `user_version 1` e o real fica em 0.

Vistas na rodada 2 (S1/S2 do seguranca):

- Regex com classe repetida e sem âncora (`[a-z][a-z0-9+.-]*://`, `(?:[\w-]*\.)+`) é **quadrático** num token longo sem casamento: 40 kB levaram 6 s. Na detecção de links, use `find('://')` + recuo e varredura de rótulos à mão; um teste de tempo (< 0,5 s com `'a'*40000`, `'a.'*20000`) pega a regressão.
- Na detecção de domínio, `_` precisa separar segmentos (rótulo de domínio não tem `_`), senão `#_golpe.com` e `golpe.com_#` escapam. Na cópia do banco, a regra "qualquer rotulo.tld de 2+ letras" deixa 14 de 5.329 itens de fora (modelos de TV com ponto, `i.Phone`, `Andro.id`).
- `$\`` e `$'` no porte do `replaceAll` multiplicam o texto a cada campo (1,5 GB em 0,2 s com campos no teto): a montagem soma o tamanho **antes** de fatiar e aborta com `MensagemGrande`. Teste de bug com risco de OOM: rode o "antes" com `ulimit -v 1500000` num subshell.
- Telefone em teste: use `5500000000001` (fictício); o seguranca recusa número com DDD real no git.

Vistas no E2 do plano perfumaria-tres-lojas (Shopee no disparo, 2026-11-03):

- Os testes da Shopee em `test_disparo.py` usam o `S.eh_link_afiliado` real e conferem `D.HOSTS_AFILIADO_SHOPEE == S.HOSTS_AFILIADO_SHOPEE`: dependem do E1 (servidor). Para provar que a checagem de host do `link_da_loja_ok` segura sozinha, passe um `eh_afiliado` permissivo (`lambda u: True`); `http://` e `user@host` só caem no `eh_afiliado` do servidor.
- Linha com placeholder vazio some inteira no `montar_mensagem`: `'{LOJA}|{LINK}'` com loja desconhecida dá `''`, não `'|link'`. Teste o `{LOJA}` vazio em linha separada.
- Cópia para mutantes do `test_disparo.py` precisa também de `testes/mensagens.test.html`, senão dá 4 ERROR fixos (FileNotFoundError) em toda execução.

**How to apply:** ao mexer em `disparo.py`, `buildMsg` ou nos testes deles. Relacionado: [[escapes-unicode-ferramentas]], [[chrome-headless-testes]], [[servidor-testes]].
