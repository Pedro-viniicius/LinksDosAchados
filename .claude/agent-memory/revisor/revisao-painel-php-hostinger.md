---
name: revisao-painel-php-hostinger
description: Revisões do repositório irmão Pagina_desejoMenina (painel PHP na Hostinger, ADR 0011) delegadas a partir daqui; como rodar, imagens Docker, armadilhas e padrões vistos
metadata:
  type: project
---

O lead deste projeto às vezes delega revisão de `/home/ufla/Documentos/Pagina_desejoMenina` (outro repo, CLAUDE.md próprio, docs em `docs/equipe/`). Primeira vez: painel `/painel/` em PHP (rodada 1 em 2026-11-04; rodada 2 no mesmo dia, R1–R5 e P1 corrigidos, APROVADO COM RESSALVAS). Os arquivos do painel são untracked: `git diff` não mostra o que a correção mexeu; na rodada 1, guarde em scratchpad uma cópia ou o hash dos arquivos para comparar na 2.

**Why:** o contexto daqui (Etiqueta/achadinhos) não vale lá; lá o plano manda nas "Decisões do PO" e "Decisões do lead", que valem sobre a spec.

**How to apply:**
- Testes: unidade `docker run --rm --network none -v "$PWD/site/hostinger:/app:ro" -w /app php:8.3-apache php painel-testes/rodar.php`; integração `bash site/hostinger/testar-painel.sh`; `npm run check`. Imagens locais: `php:8.3-apache`, `php:8.2-cli`, `php:7.4-cli` (guarda de versão), e `php:8.3-cli` (baixei sem querer em 2026-11-04: use sempre `php:8.3-apache` para não puxar imagem nova).
- Rodar a unidade também no `php:8.2-cli` pega recurso de 8.3 escondido (mínimo declarado é 8.1).
- Nunca ler `~/.config/contador-hostinger/*.token`.
- Padrões que vi: JSON gravado com `ftruncate` + `fwrite` (padrão herdado do `contar.php`) não é atômico (no `membros.json` virou `atualizarJsonAtomico`: trava `.trava` + temporário + fsync + rename; cache, sessão e tentativas seguem no padrão antigo de propósito); arquivo vazio vira "corrompido" na leitura mas "novo" na gravação. Âncora `#id` que só existe na versão celular (escondida no desktop com `display:none`) não rola a página. Métrica calculada no `$tela` e nunca mostrada (taxa de entrada).
