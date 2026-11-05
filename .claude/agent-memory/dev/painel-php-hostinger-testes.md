---
name: painel-php-hostinger-testes
description: Painel PHP do repositório Pagina_desejoMenina (site/hostinger/painel): testes em Docker sem rede, sessão no CLI, error_log, .htaccess (lista de permissão, subdomínios), Chrome abaixo de 500 px
metadata:
  type: project
---

Trabalho delegado no OUTRO repositório `/home/ufla/Documentos/Pagina_desejoMenina` (plano `docs/equipe/planos/painel-hostinger.md`, ADR 0011). Sem `php` no host; imagens já baixadas: `php:8.3-apache`, `php:8.2-*` e `php:7.4-cli` (esta serve para provar a guarda "PHP 8.1 ou mais novo" do `index.php`). Não puxe outra.

- Unidade: `docker run --rm --network none -v "$PWD/site/hostinger:/app:ro" -w /app php:8.3-apache php painel-testes/rodar.php` (montagem `:ro`; testes gravam só em /tmp do contêiner).
- **Sessão no CLI:** qualquer `echo`/`var_dump` no STDOUT antes do `session_start` marca os cabeçalhos como enviados e a sessão falha. O runner escreve com `fwrite(STDOUT)`. Modo estrito recusa também o id passado por `session_id($x)` (gera outro): dá para simular o cookie assim.
- **`error_log()` ignora `log_errors`:** sem `error_log` no ini, vai para o stderr e suja a saída. O runner aponta para `/dev/null` e o `capturarLog()` troca por arquivo.
- **`.htaccess` no `php:8.3-apache`:** a imagem já vem com `AllowOverride All` (em `conf-enabled/docker-php.conf`). Para provar a guarda `defined('PAINEL') || exit` com o `.htaccess` ignorado, troque `All`→`None` em `apache2.conf` E em `conf-enabled/*.conf`.
- `flock` entre dois `fopen` no mesmo processo conflita no Linux: serve para testar "trava ocupada" sem fork.
- `proc_open([PHP_BINARY, '-r', ...])` serve para teste de concorrência (pcntl não vem na imagem).
- Mutantes: copiar `site/hostinger` para o scratchpad e rodar o mesmo `docker run` na cópia.
- `npm run check` não olha `.php` nem `.sh`; o Biome formata os `.json` de `painel-testes/fixtures` (rode `npx biome check` neles).
- Integração: `bash site/hostinger/testar-painel.sh` (contêiner `--network none`, arquivos via `docker cp`, sem bind mount; curl por `docker exec`). Root `.htaccess` entra sem as 3 linhas do https. A imagem precisa de `a2enmod rewrite headers`.
- **OPcache ligado no php:8.3-apache:** um `config.php` regravado não é relido por ~2 s (`revalidate_freq`); por isso `carregarConfig` chama `opcache_invalidate($arquivo, true)`.
- **Set-Cookie duplicado no login:** `session_start` + `session_regenerate_id` mandam dois Set-Cookie, mas o `headers_list()` mostra só o último. `header_remove('Set-Cookie')` limpa os dois (ver `umCookieDoPainel` em `_lib/rotas.php`).
- O Biome lint também o `.css` não monitorado (avisos `noDescendingSpecificity` contam): rode `npx biome check site/hostinger/painel/painel.css`.
- Mutantes da integração: copie `site/hostinger` para `scratchpad/mutantes-painel/mN/h` (um diretório novo por mutante; `rm -rf "$VAR"` é bloqueado pela checagem de segurança).
- Captura de tela: gerar o HTML com `htmlPainel(montarTela(...))` num script PHP em Docker, trocar o link do CSS por relativo e usar `google-chrome --headless=new --screenshot --window-size=375,5200`; PIL serve para recortar.
- **Chrome headless abaixo de 500 px:** com `--window-size=375,…` a captura sai com 375, mas o layout durante o carregamento tem 500 (um script mede 500). Para medir rolagem a 375, use o `painel-testes/layout.qa.test.mjs <pasta com painel.html e painel.css>` (CDP; mede 320 a 1280). `autofocus` rola a janela: capture com janela alta (página inteira) e recorte com PIL.
- **Lista de permissão no `painel/.htaccess`** (`FilesMatch`): `/painel/` chega com nome vazio e `/painel` (sem barra) com o nome `painel`; sem `painel` na lista, o 301 vira 403. Arquivo fora da lista dá 403 mesmo se não existir (o QA esperava 404 em `painel-config.exemplo.php`).
- **Rewrite do `.htaccess` da raiz e subdomínios:** subdomínio com docroot em `public_html/<sub>/` também passa pelo `.htaccess` da raiz, que vê o caminho como `<sub>/...`: regra para esses caminhos tem de ser condicionada ao Host. No teste, Host `casamento.desejodemenina.com` + `/casamento/` simula isso.
- O `testar-painel-qa.test.sh` troca `painel.css?v=1` por `painel.css` com `sed`: subir a versão do CSS quebra o layout do QA (combinar com o QA antes).
- `test/repositorio.test.js` rodado com `node --test` direto falha a "guarda de rede" (falta o `--import`): use `npm run check`.
- Rodada 2 (04/11): os testes do QA `telas.qa.test.php:162` ("Confira a chave no config.php") e `testar-painel-qa.test.sh:214` (404 no modelo de config) ficaram em conflito com D5 e S4; conferir se o QA já atualizou antes de tratar como regressão.
