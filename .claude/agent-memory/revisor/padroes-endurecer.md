---
name: padroes-endurecer
description: Revisão do endurecer-engenharia-e-operacao (verificar.py, trava por loja, backup_banco, operacao/, /api/versao): como verificar, o que escapou na r1 e o que a r2 mostrou
metadata:
  type: project
---

Entrega 1: r1 em 2026-11-09 (MUDANÇAS NECESSÁRIAS: R1 ATENÇÃO, R2-R6 SUGESTÃO); r2 no mesmo dia, todos corrigidos.

**Como verificar (só leitura):** `python3 verificar.py --hora 3` (completo) e `--rapido` levam ~2,5 min; logs em `logs/verificar-*` (ignorados). `--segredos --tudo` e `--servidor` (um GET na 8765) são seguros. Testes de dados reais: rode o arquivo com `ACHADINHOS_TESTE_DADOS_REAIS=1`, proxies mortos (leem o banco em `mode=ro`). Único vermelho conhecido: `garimpo/test_qa_entrega1` (outra frente, sem `unittest.main()`). Outros agentes rodam o `verificar.py` (até `--pre-commit`) em paralelo: `pgrep -af verificar.py` antes de achar estranho.

**Mutante dos scripts de operacao/ sem tocar no repo:** o `test_operacao.py` acha os scripts por `RAIZ` do `__file__` e copia para uma árvore temporária; copie `testes/test_operacao.py` + `operacao/` para o scratchpad, mude o script lá e rode `python3 -I testes/test_operacao.py <Classe>`. Para ver o que a isenção de "falso" (FALSO/MARCADOR/TESTE/EXEMPLO/12345) esconde, rode a regex sem `_NAO_FALSO` sobre `git ls-files --others --cached --exclude-standard` (em 09/11: 9 linhas, todas falsos de teste).

**O que escapou dos devs:**
- r1: portão `ACHADINHOS_TESTE_DADOS_REAIS` só nos arquivos citados no plano (o `test_genero.py` lia o banco real direto). **How to apply:** `grep -rln achadinhos.db testes tools/*/testes` e abra cada um.
- r1: mudança que corta tempo invalida a lista de LENTOS e os tempos da doc: meça de novo.
- r2: texto de instrução escrito pensando no caso de uma aba só ("Nenhum preço foi atualizado por este comando" na saída 4) fica falso no ML aba por aba, quando abas anteriores já gravaram. **How to apply:** em mensagem de script com laço, simule a falha na 2ª iteração.
- r2: edição de comentário deixou `real =os.path...` (espaço comido) em `test_ml_api_qa.py`: olhe o diff das linhas vizinhas do que mudou.

Ver [[padroes-docs]] e [[revisao-ambiente]].
