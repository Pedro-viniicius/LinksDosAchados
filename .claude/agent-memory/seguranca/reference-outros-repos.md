---
name: reference-outros-repos
description: Onde fica a memória do seguranca quando o lead pede revisão nas landing pages do dono (Desejo de Menina, Decisões que Dão Lucro, Black Friday; contar.php e painel PHP na Hostinger)
metadata:
  type: reference
---

O antigo `/home/ufla/Documentos/Pagina_desejoMenina` não existe mais (conferido em 2026-11-08). As landing pages ficam em `~/Documentos/lande_pages/` (`Lange_meninas` = desejodemenina.com, `lange_tech` = decisoesquedaolucro.com, `langeBlack` = radardablackfriday.store) e às vezes num worktree em `~/Documentos/lande_pages_variante-b/` (branch `feat/variante-b-so-hero`).

A memória do seguranca desses sites está em `~/Documentos/lande_pages/Lange_meninas/.claude/agent-memory/seguranca/` (áreas sensíveis, riscos aceitos, problemas recorrentes): leia lá antes de revisar. Não escreva lá desta sessão: `~/Documentos/lande_pages/` é de outro agente (regra do dono) e a escrita fora desta pasta é bloqueada. O que precisar entrar naquela memória vai no relatório para o lead repassar. Não misture os riscos aceitos dos dois projetos.

Fatos conferidos em 2026-11-08 (revisão da variante B), para repassar àquela memória: `contar.php` idêntico nas 4 cópias (Desejo `site/hostinger/`, Decisões `public/`, Black `src/` e `dist/`), com `hero-b` no `ORIGENS`; o `consentimento.js` da Desejo NÃO tem `hero-b` (o Contact da B sai com `content_name: "outro"`); nenhuma das duas landings tem CSP no `.htaccess` da Hostinger, e as páginas B têm script inline (a Decisões não tinha inline antes).
