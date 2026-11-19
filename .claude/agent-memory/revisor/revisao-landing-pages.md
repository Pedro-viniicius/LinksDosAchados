---
name: revisao-landing-pages
description: Revisão das landing pages de grupo (Desejo de Menina, Eletrônicos/decisoesquedaolucro, Black) pedida a partir deste projeto: comandos, cópias do contar.php e armadilhas
metadata:
  type: reference
---

Pedidas pelo lead deste projeto, mas o código fica fora daqui: `~/Documentos/lande_pages/` (cópias principais; o lead não edita lá) e worktrees em `~/Documentos/lande_pages_variante-b/` (r1 da variante B em 2026-11-08).

- Checks: Desejo (`Lange_meninas`) `npm run check` na raiz do worktree (474 testes em 08/11), `npm run build -- --estrito`, `bash site/hostinger/testar-contar.sh` (Docker, ~1 min, "TUDO OK"). Eletrônicos (`lange_tech`) `npm run verificar` + `node --check public/js/script.js` (sem suíte). Black (`langeBlack`) só `build.js`, que copia `src/contar.php` para `dist/`. Sem `php` no host.
- `contar.php` tem 4 cópias (Desejo `site/hostinger/`, Eletrônicos `public/`, Black `src/` e `dist/`): compare por md5 ENTRE worktrees, porque as cópias principais podem estar noutra branch sem a mudança.
- Armadilha vista: origem nova (`hero-b`) sem teste amarrando a `ORIGENS`; `contar-hostinger.test.js` só lê os `data-cta` do `index.html`. Página nova precisa entrar nesse teste.
- `consentimento.js` da Desejo tem `ORIGENS` própria para o `content_name` do Contact (origem fora vira "outro"); o script.js da Eletrônicos manda sempre `grupo-whatsapp`.
- Desejo: `docs/equipe/` é a fonte da verdade (o CLAUDE.md de lá manda atualizar); Eletrônicos: `README.md` e `campanha-meta-estado.md`.
