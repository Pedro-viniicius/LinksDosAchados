---
name: API oficial do ML (ml_api.py)
description: Revisão r1/r2 das etapas 1-3 do plano api-oficial-ml (OAuth PKCE, tokens 0600, flock, sondar); o que conferir e como rodar mutantes
type: project
---
- Etapas 1-3 aprovadas na r2 (2026-11-05). Resolvidos na r2: .tmp no .gitignore + limpeza sob lock, getpass só com isatty, uma renovação por 401 por Sessao, RenovacaoInvalida/SemRefreshToken (saída 2), safe=',' no urlencode, trava antes da troca do code.
- Borda que sobrou (sugestão): `.lock` já existente + pasta sem escrita → `travar` abre, o code é gasto e `gravar_tokens` dá PermissionError genérico (saída 1). Só falha "antes da rede" quando o .lock ainda não existe.
- Pendência declarada: troca do code sem refresh_token sai 1 "fora do formato" (sem dica do offline_access); o qa fixa saída 1.
- `git check-ignore -q a b c` sai com 128. Use sem `-q` e compare o stdout.
- Frases do tipo "nenhuma dessas" no README: confira contra a lista inteira.
- Mutantes: copie ml_api.py e os .py/.js/.html da raiz + buscas.json e lista_whatsapp.json PELO NOME (nunca `cp *.json`: leva o ml_tokens.json real; aconteceu em 2026-11-05, apagado sem ler) + testes/test_ml_api*.py para o scratchpad. Copie também o README.md, senão o TestReadme do test_ml_api_qa dá erro em todo mutante. Mutante "401 sem limite" vira laço: timeout por arquivo (120 s). Na r2, 9/9 mutantes das correções morreram no test_ml_api.py.
- Mutantes em laço no mesmo segundo: rode com `python3 -B` e PYTHONDONTWRITEBYTECODE=1. O .pyc guarda mtime em segundos + tamanho; dois mutantes do mesmo tamanho seguidos usam o bytecode velho e "sobrevivem" falsamente.
- Catálogo etapa 1 (sondar --catalogo), r1 2026-11-05: 10/12 mutantes mortos (sobram restauração do sessao.opener e tolerância de futuro do preco_em). Achados: item cortado pelo teto conta em vistos/buscados (viés no F10, reproduzido); F9 não diz o que o 404 significa; resultado da busca sem `status` é tratado como pai e some.
- Catálogo etapa 1, r2 2026-11-05: aprovado com ressalvas. 16 de 17 mutantes das correções mortos no test_ml_api_catalogo.py (+1 equivalente: total do 404 pela soma do n404) (script em scratchpad: lista (nome, trecho, troca), roda dev+qa com timeout 120). Sobrou: resultado ativo com `children_ids: []` (o `len>0` do `_eh_pai` sem teste). No scratchpad o test_ml_api_catalogo_qa dá sempre failures=1 skipped=1 (Q1 + teste com servidor), então só discrimina pelo dev. RenovacaoFalhou (saída 2) vale só no --catalogo; docstring de saídas do módulo não a cita. Q1 (-wal/-shm do mode=ro) é risco aceito no CA1.
