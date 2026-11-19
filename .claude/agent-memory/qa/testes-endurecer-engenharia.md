---
name: testes-endurecer-engenharia
description: Entrega 1 de endurecer-engenharia-e-operacao (verificar.py, trava por loja, backup_banco, operacao/*.sh, /api/versao, portão de commit): como rodar, testes do QA, achados Q1/Q2, armadilhas
metadata:
  type: project
---

Arquivo do QA: `testes/test_endurecer_qa.py` (36 testes, ~20 s; `python3 testes/test_endurecer_qa.py -v` ou `Classe.metodo`). Importa `test_operacao` (Base com python3 falso) e `test_servidor` (porta_livre/ambiente). Classes: PortaoDeCommit (repo git temporário + cópia do verificar.py e do hook), Backup, Trava (dono em processo separado, corrida de 8 processos), OperacaoAbasReais (buscas.json real, 17 abas), VersaoDoServidorNoAr (verificar.py --servidor por subprocesso contra cópia dos 4 .py).

Achados da rodada 1 (09/11/2026), com teste vermelho que os reproduz (Q1, Q2 e o .parcial foram corrigidos na rodada 2 e os testes estão verdes; rodada 2 APROVADA):
- Q1 (baixa): `nome_proibido` só casa o nome exato; `api_token.txt.bak`, `api_token.txt~`, `.old`, `api_cabecalho.txt.bak`, `_chat.txt.bak`, `ml_catalogo.json.bak` passam pelo portão (e o token de 64 hex sozinho na linha não bate em nenhum padrão). Teste: `PortaoDeCommit.test_variantes_de_backup_do_arquivo_do_token_tambem_bloqueiam`.
- Q2 (baixa): `backup_banco.rotacionar` levanta FileNotFoundError se outro processo apagou o arquivo entre o stat e o unlink; vira `AVISO: a rotação ... falhou` e a rotação para no meio. ~25% das vezes com 4 backups simultâneos (atualizar-ml.sh e atualizar-shopee.sh podem rodar juntos). Teste determinístico: `Backup.test_rotacao_que_perde_a_corrida_...` (troca `B.os.unlink` num subprocesso).
- .parcial de SIGKILL: desde a rodada 2 a rotação apaga `auto-*.db.parcial` (+ -wal/-shm/-journal) com MTIME > 6 h (não pela data do nome); teste `test_parcial_de_sigkill_com_mtime_antigo_some...`. Lacuna restante: Regex de segredo não pega `chave secreta: ...`, `api_key=`, `secret => "..."`, senha com símbolos.

Verificado sem bug: `verificar.py --rapido` com `--hora` 0/3/6/7/12/23 só reprova o que é de fora (garimpo/test_qa_entrega1 sem unittest.main(), e o meu vermelho). CA12 end-to-end por CLI contra servidor na porta livre: em dia -> 1 (mexeu em qualquer um dos 4 .py) -> em dia ao desfazer; `touch` não conta como mudança.

Armadilhas:
- NUNCA derrube processo por `ss ... sport = :PORTA | head -1` sem ter certeza de que foi você quem subiu: a 8791 estava ocupada por outro processo e o `kill` o derrubou (avisado ao lead). Escolha porta livre com `socket.bind(('127.0.0.1',0))` e mate pelo PID do `$!`.
- Cópia do repositório para mutantes: não exclua `ml_*` (leva o `ml_api.py` junto e o teste de ML sai com 1 em vez de 2) e não copie `WhatsApp Chat*` (dado pessoal); apague a cópia no fim.
- Outros agentes rodam `verificar.py` (inclusive `--front`, 8766) ao mesmo tempo: confira `pgrep -af verificar.py` antes de rodar a suíte inteira.
- Ler `p.stderr` duas vezes no mesmo Popen devolve '' na segunda: guarde a leitura.
- Mutantes que os testes matam: sem flock no travar_rodada; rotação só do mesmo motivo; sleep depois da última aba; hash sem api_ofertas.py.
- Backups vão para a pasta do BANCO (ACHADINHOS_DB), não para o cwd: em teste de corrida com várias pastas, aponte ACHADINHOS_DB por pasta e confira que os arquivos novos aparecem (senão passa em falso).
- Mutantes da rodada 2 mortos: mtime ignorado, nunca apagar .parcial, sem -wal do velho, sem tolerância a FileNotFoundError, sem api_token*/_chat.txt* em NOMES_PROIBIDOS. Cópia para mutante: *.py + testes/*.py + .githooks (sem .githooks o PortaoDeCommit dá ERROR de import).
- `verificar.py --rapido` rodou 49/50 (só garimpo/test_qa_entrega1, sem unittest.main(), outra frente) com --hora padrão e 3.

- Q3 (15/11/2026, rodada 1 do bug de colisão de nome): `reservar_nome` confere `nome` e só depois `nome.parcial` (O_EXCL); se o outro backup publica no meio (link do nome + unlink do .parcial), o segundo sai com 1 ("o nome final apareceu durante a cópia"). Causa do flaky de `test_rotacao_em_corrida_real_nao_imprime_aviso...`. Teste determinístico: `Backup.test_dois_backups_do_mesmo_segundo_nao_colidem_quando_o_outro_publica_entre_as_conferencias` (embrulha `B.existe` num runner com relógio fixo). Correção candidata validada em cópia: criar o .parcial primeiro e reconferir nome e sidecars depois (apagando o próprio .parcial e seguindo para `-n`).
