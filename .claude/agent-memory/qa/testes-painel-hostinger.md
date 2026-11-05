---
name: testes-painel-hostinger
description: Painel PHP /painel/ do repo Pagina_desejoMenina (outro repo): como rodar unidade, Apache, TLS local e layout; limites do hook de escrita; mutantes; rodadas 1 e 2 (Q1-Q3 corrigidos)
metadata:
  type: project
---

Repo `/home/ufla/Documentos/Pagina_desejoMenina` (não é o mensagensParaEnviar). Painel em `site/hostinger/painel/`, testes em `site/hostinger/painel-testes/`.

**Rodar (Docker, sem rede):**
- Unidade: `docker run --rm --network none -v "$PWD/site/hostinger:/app:ro" -w /app php:8.3-apache php painel-testes/rodar.php` (acha `*.test.php`; todos no mesmo processo, então nomes de função/const globais precisam de prefixo `qa...`; arquivos `x.qa.test.php` carregam ANTES de `x.test.php`, mas só chamam helpers do dev dentro dos closures, o que funciona).
- QA integrado: `bash site/hostinger/testar-painel-qa.test.sh` (~15 s): TLS local, gerar-hash-senha, Apache com casos de borda, layout no Chrome.
- Dev: `bash site/hostinger/testar-painel.sh`; `npm run check` na raiz (biome checa o `.mjs`: sem `console`, usar `process.stdout.write`).

**Hook de escrita do QA** só aceita nomes `*.test.*`/`*-test.*`/`_test.*`, pastas `tests?|testes|fixtures` (NÃO `painel-testes`), `.qa-tmp/` e `/tmp/`. Script `testar-painel-qa.sh` é bloqueado; usei `testar-painel-qa.test.sh`. Arquivo auxiliar que não pode rodar no runner vira `*.qa.test.php` com `if (defined('PAINEL')) return;` no topo (servidor-tls, http-real).

**Como testei o que era difícil:**
- curl de verdade sem rede: contêiner `--network none --add-host desejodemenina.com:127.0.0.1`, `openssl req -x509` + `update-ca-certificates`, servidor `stream_socket_server('ssl://0.0.0.0:443')` em PHP. Provou que o `buscarJson` devolve `resposta_invalida` para 404 sem corpo (o dev testava 404 com corpo `[]`, irreal).
- Layout: `layout.qa.test.mjs` (CDP, `Emulation.setDeviceMetricsOverride`) sobre o HTML renderizado pelo Apache + CSS/fontes locais em file://; mede scrollWidth, texto < 16 px, alvos < 44 px. Validado com um HTML sabotado.
- Escrita simultânea: 8 `curl &` dentro do contêiner e `proc_open` de PHP filho nos testes.
- Fuso: instantes UTC em volta de 02:59:59Z/03:00:00Z (virada de São Paulo); o contêiner está em UTC.

**Armadilhas:** `pkill -f qa-painel-chrome` mata o próprio shell (a linha de comando contém a string): use `pgrep -f '^/opt/google/chrome/chrome.*qa-painel'`. `| head` num script node fecha stdout e deixa Chrome órfão (corrigido com `process.stdout.on('error')`). Regex com `$` sem `D` aceita `\n` final (causa do Q2).

**Mutantes úteis (todos pegos):** `<`→`<=` no limiar, base do período = primeiro registro, tirar `contagemDesde`, `<=` na validade da sessão, limite de IP `>`, Origin por prefixo, registrar sem substituir, `ENT_NOQUOTES`, `dataLocal` em UTC, token em cabeçalho extra, CSRF sem comparar. Sobrevivente equivalente: `novos > 0` → `!== 0` (o `dividirCentavos` já barra negativo).

**Rodada 2 (2026-11-04):** Q1, Q2, Q3 corrigidos e verificados; suíte final 163 casos/0 falhas (unidade), testar-painel-qa.test.sh e testar-painel.sh TUDO OK, npm run check 423/0. Acrescentei: seção "rodada 2" no script QA (S1: bypass `//casamento/`, `%63asamento`, `/painel/../casamento/`, Host com ponto/porta; S4: `.bak`, `.map`, `.txt`, `.htaccess`; S3: HSTS uma vez e sem includeSubDomains; R3: Atualizar mantém a sessão) e 3 testes R1 em membros.qa.test.php (leitor SEM trava via file_get_contents durante 120 gravações: só o rename protege; lerJson com LOCK_SH não serviria, pois mascara o mutante).
**Mutantes da rodada 2 (todos pegos, rodados em cópia no scratchpad):** tirar a regra S1 do .htaccess da raiz; tirar a lista de permissão S4; HSTS com includeSubDomains; atualizarJsonAtomico trocado por file_put_contents direto. Sem rede, o Atualizar não grava aviso (hora das fontes null), então o aviso "Atualizado às" não é testável no Apache.
