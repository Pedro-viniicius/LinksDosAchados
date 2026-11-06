---
name: riscos-aceitos
description: Riscos que o dono do projeto achadinhos aceitou explicitamente, com a mitigação declarada (sem token na API; origens do ML podem POST/PATCH)
metadata:
  type: project
---

**R1 — API sem token; script em página do ML (ou extensão) pode POST/PATCH** (dono decidiu "sem token", P3 do plano `docs/produto/planos/blindar-servidor.md`, comunicado pelo lead em 2026-11-03).
- Mitigação declarada: só `https://lista.mercadolivre.com.br` e `https://www.mercadolivre.com.br`, só GET/POST/PATCH em `/api/items`, `/api/items/<id>` e `/api/ml-sem-afiliado`; CA6 (`loja` validada); CA7 (PATCH de `url` só com link de afiliado); prompt de Local Network Access do Chrome; servidor só em 127.0.0.1.
- Volta também se o POST voltar a aceitar `url` fora de `eh_url_de_loja` ou o front abrir url sem checar `https:` (furo S1, fechado em 2026-11-03).
- Conferido em 2026-11-03 (revisão do disparo): `/api/disparo/*` fora de `ROTAS_ML`, R1 continua valendo. Impacto novo de R1: texto livre de item (título) agora alimenta mensagem enviada ao grupo e regex do agendador (ver S1/S2 em [[problemas-recorrentes]]).
- Conferido em 2026-11-03 (Shopee, E1): `s.shopee.com.br/<código>` não prova o dono, como `meli.la`; uma origem do ML pode criar item `shopee` com link de outro afiliado e ele sai no disparo. Mesma classe já coberta por R1; allowlist de origens e `ROTAS_ML` não mudaram.
- Conferido em 2026-11-03 (API v1, E1/E2): gatilhos não dispararam (origens, `ROTAS_ML`, `METODOS_ML` e bind em 127.0.0.1 iguais). O token da v1 não protege mais que hoje contra processo local (`GET /api/items` sem Origin segue aberto). Impacto novo: item plantado por origem do ML (com `meli.la`/`s.shopee` de terceiro) sai pela v1 para o Turbo, que pode enviar sem o dono olhar; recomendei ao lead reconfirmar R1 com o dono (sem resposta até a rodada 2). O contrato manda o Turbo regerar o link do ML ou revisar; o da Shopee (`s.shopee`, também sem prova do dono) segue "como veio".
- Conferido em 2026-11-03 (gênero, E2/E3/E5): gatilhos não dispararam; a rota de correção do público ficou fora de `ROTAS_ML`. Impacto novo: título/busca plantados mudam o gênero automático, e o item entra em regra/filtro por público.
- Conferido em 2026-11-04 (17 abas, etapas 1-10): `servidor.py` só ganhou `preco_antigo_plausivel` no `upsert`; origens, `ROTAS_ML`, `METODOS_ML` e bind iguais. R1 vale. Rodada 2 (2026-11-04): `sanear_precos` no PATCH `data` só zera preço antigo/desconto; nada de origem/rota mudou.
- Conferido em 2026-11-04 (atualizar-precos, E1-E6, rodada 1): gatilhos não dispararam (`so_existentes` só estreita o POST; origens, `ROTAS_ML`, `METODOS_ML`, bind iguais; config fora de `ROTAS_ML`). Impacto novo: a origem do ML carimba `preco_em` (POST/PATCH `data`) e fura a trava de preço velho com preço falso, ou zera o `preco_em` (tira item do disparo); `cat` plantada chegava a comando de terminal copiado (S1 BAIXA, fechado na rodada 2). Lead levaria os dois impactos ao dono no resumo final.
- Volta como achado se: a allowlist de origens crescer, `ROTAS_ML`/`METODOS_ML` ganharem DELETE/PUT/config/fetch, CA7 deixar de valer, ou o servidor escutar fora de 127.0.0.1.

**R2 (ACEITO pelo dono em 2026-11-05; registrado em `docs/produto/planos/api-oficial-ml.md`, "Risco aceito pelo dono") — `code` do OAuth do ML no log de acesso da Hostinger e no histórico do navegador** (plano api-oficial-ml, "Pontos para o seguranca").
- Mitigação declarada: code de uso único e curto, exige o verifier PKCE (só em memória do `autorizar`) e o Secret (só no env do dono); página sem JS, CSP `default-src 'none'`, `no-store`, `no-referrer`, `noindex`, `frame-ancestors 'none'`.
- Volta como achado se: o PKCE não for obrigatório no app do DevCenter E o Secret ficar em algum lugar além do env do comando; a página ganhar JS/recurso externo; o verifier for para disco.

**R3 (ACEITO pelo dono em 2026-11-05; registrado em `docs/produto/planos/api-oficial-ml-catalogo.md`, "Risco aceito pelo dono") — termos de uso do ML para afiliado que usa dados de catálogo (`/products/*`) para atualizar preço** (plano api-oficial-ml-catalogo, "Pontos para o seguranca"; ninguém leu os termos; levado ao lead em 2026-11-05, E1 rodada 1).
- Mitigação declarada: só leitura, teto de chamadas por rodada, pausa 0,3-0,8 s, nada de scraping; nenhum dado de terceiro (seller_id) sai ou é gravado.
- Pior caso: app suspensa/bloqueada no DevCenter; o console continua como fallback.

**Q1 / pendência INFORMATIVA — aceita pelo lead em 2026-11-05 (catálogo E1, rodada 2; não precisa do dono por ser INFORMATIVA):** abrir o banco WAL em `mode=ro` com servidor parado (`itens_do_banco`, `ids_do_banco`, `test_ml_api_qa` sobre o banco real) deixa `achadinhos.db-wal` (0 B) e `-shm` (32 KB, sem dado de linha; medido) 0644 na raiz, cobertos por `*.db-wal`/`*.db-shm` no `.gitignore`; `/home/ufla` é 0750.
- Volta como achado se: os arquivos saírem do `.gitignore`, o servidor passar a servir a pasta, ou o `-wal` passar a ter conteúdo gravado por esses leitores (abrir com escrita).

**Q1 da etapa 3 do catálogo — aceito pelo lead em 2026-11-05 (registrado no plano api-oficial-ml-catalogo):** coluna NULL em `CAMPOS` vira `''` pelo `d.get(c) or ''` do `servidor.upsert` (banco real com 0 NULL nesses campos; o front trata igual).
- Volta como achado se: `''` e NULL passarem a ter sentido diferente na leitura.

**S2/S3 do catálogo (INFORMATIVAS, aceitas pelo lead em 2026-11-05, etapa 3 rodada 2; registradas no plano; o aviso "uma máquina, um comando por vez" no README é da etapa 4, confira lá):** `ml_catalogo.json` sem `flock` (premissa "uma máquina, um comando por vez", escrita no docstring do `atualizar_precos.py`) e sem limpeza de `.ml_catalogo.json.*.tmp`.
- Mitigação declarada: `os.replace` atômico + leitor estrito (nunca corrompe nem segue symlink); pior caso de 2 rodadas juntas = vínculos perdidos refeitos pela API (custo de chamadas, R3); o vínculo forjado/velho não injeta preço (pertença reconferida em `ofertas_do_produto`); `.tmp` só sobra em SIGKILL/queda (Ctrl+C limpa, medido), tem só ids, 0600, no `.gitignore`.
- Volta como achado se: o arquivo passar a ter segredo ou dado pessoal; o preço passar a vir só do cache sem reconferir a pertença; aparecer agendamento automático (cron/servidor) que rode duas fontes `ml` ao mesmo tempo; o padrão `.ml_catalogo.json.*.tmp` sair do `.gitignore`.

**S1 do garimpo: NÃO é mais risco aceito (corrigido em 2026-11-06) — Secret em `/proc/<pid>/environ` na rodada em segundo plano.** O `garimpo.py` chama `prctl(PR_SET_DUMPABLE, 0)` antes de importar `coletar_shopee`; teste em subprocesso prova o `PermissionError`. Resta a janela de milissegundos até o `prctl`, e o root continua lendo. Volta como achado se a chamada sair do topo, ou se uma rodada seguir depois de um AVISO de falha do `prctl`: nesse caso, agentes não leem `/proc/*/environ` nem rodam `ps e`/`ps eww`. Os outros achados abertos do garimpo estão no plano `garimpo-feminino-shopee`, "Risco aceito pelo dono".

**P4 do plano garimpo (lido como aceito na frase geral do dono em 2026-11-06, "estou disposto ao risco"; não houve resposta específica) — rajada de medição até o 10030 no mesmo AppID da produção.** Mitigação: teto de 120, para no 1º 10030/429, fora do horário de coleta. Ninguém leu os termos da Open API (doc no painel logado).

Ver [[problemas-recorrentes]], [[areas-sensiveis]].
