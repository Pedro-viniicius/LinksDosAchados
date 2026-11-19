# shellcheck shell=bash
# Funções comuns dos scripts de operação (operacao/atualizar-*.sh). Não rode este arquivo: os scripts o
# carregam com `source`. Plano: docs/produto/planos/endurecer-engenharia-e-operacao.md, etapa 7 (CA5, CA6).
#
# Regras dos segredos (Secret do ML, AppID e Secret da Shopee):
#   - só entram por `read -rs` numa variável do shell (S, A), que não é exportada: nenhum filho a herda;
#   - só vão para o ambiente do comando que precisa deles (VAR="$S" python3 ...), nunca para o argv;
#   - nenhuma linha imprime o valor, e o `read -s` não ecoa: o tee do log não tem como pegá-lo;
#   - o trap EXIT (encerrar) apaga as variáveis;
#   - nada aqui liga o rastreio de comandos do bash (ele imprimiria a linha com o valor já expandido), e o
#     `set +x` abaixo o desliga mesmo quando o script é chamado com ele ligado (opção -x do bash ou xtrace no
#     SHELLOPTS do ambiente). Ele é o primeiro comando: vem antes de qualquer read, e cada script faz o
#     `source` deste arquivo antes de qualquer outro comando.
#
# O log vai para logs/<nome>-AAAAMMDD-HHMMSS.log (a pasta logs/ é ignorada pelo git), com tudo o que aparece
# na tela, inclusive a saída dos comandos.

set +x
set -u
shopt -s lastpipe   # o último comando de um pipeline roda neste shell: `rodar` guarda as linhas RESUMO/PAROU

RAIZ=$(cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd) ||
    { echo 'ERRO: não achei a pasta do projeto.' >&2; exit 1; }
cd -- "$RAIZ" || { echo 'ERRO: não consegui entrar na pasta do projeto.' >&2; exit 1; }

LOG=''
TEE_PID=''
ULTIMO_RESUMO=''   # última linha "RESUMO <loja>: ..." do último comando rodado por `rodar`
ULTIMO_AVISO=''    # última linha "PAROU: ..." ou "ERRO: ..." do último comando rodado por `rodar`

# Pausa depois de uma saída 3 (bloqueio ou limite da API), em segundos. Só dígitos.
pausa_seg() {
    local p=${PAUSA_SEG:-300}
    if [[ ! $p =~ ^[0-9]{1,6}$ ]]; then
        echo 'ERRO: PAUSA_SEG tem de ser um número de segundos (ex.: PAUSA_SEG=300).' >&2
        exit 2
    fi
    PAUSA=$((10#$p))
}

# iniciar_log <nome>: daqui em diante, tudo o que sai na tela (stdout e stderr) também vai para o log.
iniciar_log() {
    local base n=0
    mkdir -p logs || { echo 'ERRO: não consegui criar a pasta logs/.' >&2; exit 1; }
    base="logs/$1-$(date +%Y%m%d-%H%M%S)"
    LOG="$base.log"
    while [[ -e $LOG ]]; do n=$((n + 1)); LOG="$base-$n.log"; done
    (umask 077; : > "$LOG") || { echo "ERRO: não consegui criar o log $LOG." >&2; exit 1; }
    # O tee ignora o Ctrl+C (-i): o aviso de interrupção do comando e o resumo final ainda chegam ao log.
    exec > >(exec tee -i -a -- "$LOG") 2>&1
    TEE_PID=$!
    trap encerrar EXIT
    trap ao_interromper INT
    echo "Log desta rodada: $LOG"
}

# Ctrl+C: com um comando no ar (`rodar`), ele recebe o sinal, trata e devolve 130, e o script para com o
# resumo; fora dele (leitura da chave, backup, pausa), o script para na hora.
EM_COMANDO=0
ao_interromper() {
    (( EM_COMANDO )) && return 0
    echo
    echo 'Interrompido (Ctrl+C). O que já foi gravado fica; rode de novo para seguir.'
    exit 130
}

encerrar() {
    unset -v S A
    if [[ -n $TEE_PID ]]; then
        exec >&- 2>&-          # fecha a ponta do tee, que termina de gravar o log
        wait "$TEE_PID" 2>/dev/null
    fi
}

# fazer_backup <loja>: backup datado pelo backup_banco.py; se ele falhar, para aqui (nada foi atualizado).
fazer_backup() {
    echo "Backup do banco antes da rodada (motivo $1)..."
    if ! python3 backup_banco.py --motivo "$1"; then
        echo "PAROU: o backup do banco falhou (mensagem acima). Nada foi atualizado. Confira o espaço em disco" \
             "e a pasta backups/ e rode de novo."
        exit 1
    fi
}

# abas_validas [aba...]: imprime as abas pedidas (em NFC, sem repetição) ou, sem argumento, todas as abas do
# buscas.json na ordem do arquivo, uma por linha. Aba fora do buscas.json: mensagem e saída 2.
abas_validas() {
    python3 -I -c '
import json, sys, unicodedata
try:
    with open("buscas.json", encoding="utf-8") as f:
        buscas = json.load(f)
except (OSError, ValueError):
    print("ERRO: não consegui ler o buscas.json.", file=sys.stderr)
    sys.exit(1)
abas = [k for k, v in buscas.items() if isinstance(v, list)] if isinstance(buscas, dict) else []
if not abas:
    print("ERRO: o buscas.json não tem nenhuma aba.", file=sys.stderr)
    sys.exit(1)
pedidas = [unicodedata.normalize("NFC", a) for a in sys.argv[1:]] or abas
fora = [a for a in pedidas if a not in abas]
if fora:
    print("ERRO: aba fora do buscas.json: " + "; ".join(fora) + ". As abas são: " + "; ".join(abas) + ".",
          file=sys.stderr)
    sys.exit(2)
print("\n".join(dict.fromkeys(pedidas)))
' "$@"
}

# rodar <comando ou função> [args...]: mostra a saída do comando (stdout e stderr), guarda a última linha
# RESUMO e a última PAROU/ERRO e devolve o código de saída do comando. Para passar um segredo, use uma função
# que faça VAR="$S" python3 ... (o segredo nunca vai no argv de `rodar` nem de nada).
rodar() {
    local linha
    ULTIMO_RESUMO=''
    ULTIMO_AVISO=''
    EM_COMANDO=1
    "$@" 2>&1 | while IFS= read -r linha || [[ -n $linha ]]; do
        printf '%s\n' "$linha"
        case $linha in
            'RESUMO '*) ULTIMO_RESUMO=$linha ;;
            'PAROU:'* | 'ERRO:'*) ULTIMO_AVISO=$linha ;;
        esac
    done
    local saida=${PIPESTATUS[0]}
    EM_COMANDO=0
    return "$saida"
}

# Instruções comuns para as saídas que param a rodada.
instrucao_saida4() {
    echo "PAROU: outra rodada de $1 está em andamento (outro terminal ou um timer). Este passo não" \
         "atualizou nenhum preço; o que os passos anteriores gravaram fica, e o backup feito antes da trava" \
         "fica em backups/. Espere a outra terminar e rode de novo."
    [[ -n $ULTIMO_AVISO ]] && echo "Mensagem do comando: $ULTIMO_AVISO"
    return 0
}

instrucao_erro() {   # instrucao_erro <onde: "na aba X", "no passo 1/3"...> <saída>
    if [[ $2 -eq 130 ]]; then
        echo "PAROU $1: interrompido (Ctrl+C). O que já foi gravado fica; rode de novo para seguir."
    else
        echo "PAROU $1 (saída $2). Copie para o Claude só a linha ERRO/PAROU acima (ela não mostra nenhuma" \
             "chave)."
    fi
    [[ -n $ULTIMO_AVISO ]] && echo "Mensagem do comando: $ULTIMO_AVISO"
    return 0
}
