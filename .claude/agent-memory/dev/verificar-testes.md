---
name: verificar-testes
description: verificar.py (etapas 5 e 8 de endurecer-engenharia-e-operacao) - TZ do --hora no Node/Chrome, arquivo de teste sem unittest.main, front sobre cópia direta, tempos; portão de commit: GIT_* do hook, repositório temporário, falsos do ml_api
metadata:
  type: project
---

Vistas em 2026-11-09, na etapa 5 (verificar.py e testes/test_verificar.py):

- **TZ POSIX puro não vale no Node nem no Chrome** (ICU): `VRF-09:35`, `GMT-09:35`, `<-0935>+09:35` são ignorados e caem no fuso do sistema (America/Sao_Paulo), enquanto o Python (glibc) obedece. Só `Etc/GMT±N` funciona nos dois (sinal POSIX: `Etc/GMT+3` = UTC − 3; hora cheia, de −14 a +12). O `--hora` usa isso, calculado a cada arquivo.
- Arquivo de teste sem `if __name__ == '__main__': unittest.main()` sai com 0 e sem saída nenhuma (era o caso do `tools/garimpo_feminino/testes/test_qa_entrega1.py`, não rastreado): o verificar trata como falha ("nenhum teste rodou").
- O banco real já está nas 17 abas e na v3: as 12 páginas do `FRONT` (inclusive `abas`, `abas-qa`, `desmarcar-aba`) passam sobre uma cópia direta por `sqlite3.backup` em `mode=ro`, sem migrar nada. Só `disparo-integracao` e `genero-integracao` ficam fora (gravam).
- O runner do front (Chrome) roda SEM os proxies mortos (precisa das 2 fotos reais); o servidor da cópia fica com eles.
- `python3 servidor.py` sem `-u` morto por SIGTERM perde o "Site em ..." do stdout no log: suba com `-u`.
- Tempos (09/11): `--rapido` ~1,7 min; completo + `--front` ~5,6 min (front ~2 min; `test_genero_qa` ~107 s é o lento que sobrou, o `test_api_ofertas_qa` caiu para ~4 s com a etapa 2).
- Para testar o `main()` sem rodar a suíte real: `mock.patch.object` em `RAIZ`, `PASTA_LOGS`, `PASTAS_PY`, `PASTA_NODE`, `COMPILAR` com uma suíte de mentira num tmp (o `conferir_requirements` lê o `RAIZ` na hora, não no default).

Vistas na etapa 8 (portão de commit, `--segredos`/`--pre-commit`):

- **Dentro do hook o git exporta `GIT_DIR`/`GIT_INDEX_FILE`** (no `commit -a`, um índice temporário): os git do próprio portão devem herdar (varrem o índice certo), mas os filhos da suíte não (um teste que faz `git init` em pasta temporária mexeria no índice do commit real). Por isso o `ambiente_isolado` tira `GIT_*`, e o `test_verificar.py` apaga `GIT_*` do próprio `os.environ` no import.
- Repositório temporário nos testes: `GIT_CONFIG_GLOBAL=/dev/null`, `GIT_CONFIG_NOSYSTEM=1` (hooksPath, gpgsign e templates do usuário não valem) e um `python3` fixo no PATH (symlink para o `sys.executable`), porque o hook chama `python3` pelo PATH. A suíte de mentira do repositório não contém o `test_verificar.py`: sem recursão.
- `test_ml_api.py` e `test_ml_api_qa.py` têm tokens falsos `APP_USR-ACESSO-MARCADOR-...`: o padrão do ML exige dígito logo depois de `APP_USR-` (formato real `APP_USR-<id da app>-<6 dígitos>-<32 hex>-<user_id>`). A doc do ML dá 403 no WebFetch; o formato veio da busca (doc oficial e exemplo da Chilkat).
- Valores falsos nos testes do portão são montados por concatenação: o `--tudo` varre também os não rastreados fora do `.gitignore`, inclusive o próprio teste. O `MARCADOR` é montado em duas partes no `verificar.py`.
- Mutantes: copiar `verificar.py`, `.githooks/pre-commit` e o teste para uma pasta `raiz/` do scratchpad; a linha de base da cópia tem 3 falhas esperadas (sem `.test.html` e sem git: `test_repositorio_real_calibrado`), compare por diferença.

Rodada 2 (09/11, R2/R4/S2/Q1):

- Os `LENTOS` só são lentos com `--dados-reais` (medido: `test_api_ofertas_qa` ~190 s e `test_genero_qa` ~107 s com a variável; ~4 s e ~1,6 s sem). O `--rapido` só os pula com `--dados-reais`. `--rapido` inteiro: ~2,5 min.
- Padrões de segredo: valor com `falso|marcador|teste|exemplo|12345` (lookahead negativo) não é achado; é o que deixa os falsos dos testes (`SEGREDO-MARCADOR-...`, `SEGREDO-FALSO-DA-TRAVA-0001`, `APP_ID = '1800012345'` em 4 arquivos, inclusive do garimpo) passarem sem marcador. Caso negativo "sem dígito" não pode conter essas palavras, senão o mutante que tira o lookahead de dígito sobrevive.
- Teste de `main()` com `--front`: `mock.patch.object(V, 'porta_ocupada', side_effect=[False, True])` (largada livre, ocupada no `rodar_front`). Não faça mock de `V.subprocess.Popen`: a suíte de mentira usa o Popen de verdade.
- Prova de "falha antes": `verificar.py` não é rastreado; monte a versão antiga revertendo as trocas numa cópia `velho/` do scratchpad (com `.githooks/pre-commit` e o teste) e compare a lista de FAIL com a cópia `novo/` (3 falhas esperadas nas duas: sem `.test.html` e sem git).

**How to apply:** ao mexer no `verificar.py` (etapas 6 e 8 acrescentam `--servidor`, `--segredos`, `--pre-commit`) ou em teste que dependa de hora. Relacionado: [[chrome-headless-testes]], [[servidor-testes]].
