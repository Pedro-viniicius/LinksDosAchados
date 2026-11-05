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
- Mutantes: copie ml_api.py e os .py/.js/.html/.json da raiz + testes/test_ml_api*.py para o scratchpad. Copie também o README.md, senão o TestReadme do test_ml_api_qa dá erro em todo mutante. Mutante "401 sem limite" vira laço: timeout por arquivo (120 s). Na r2, 9/9 mutantes das correções morreram no test_ml_api.py.
