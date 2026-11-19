#!/usr/bin/env bash
# Instala (ou remove) os timers do systemd --user da rodada automática: etiqueta-<tarefa>.service e .timer, que
# chamam operacao/automatico.sh <tarefa>.
#
# Uso:  operacao/instalar-timers.sh [tarefa ...]             instala; sem tarefa: backup amazon ml
#       operacao/instalar-timers.sh --remover [tarefa ...]   desliga e apaga; sem tarefa: as três
# Tarefas: backup, amazon, ml. A Shopee não tem timer (precisa do Secret no terminal): shopee, ou qualquer outra
# tarefa, sai com 2 sem mexer em nada.
#
# Destino: ${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/. Cada arquivo gerado começa pela linha CABECALHO
# abaixo; arquivo com o mesmo nome e sem ela (feito à mão, ou link simbólico) não é sobrescrito nem apagado:
# o instalador sai com 1 antes de gravar qualquer arquivo. Reinstalar regrava os arquivos dele.
# As unidades não levam variável de ambiente nenhuma (nem segredo): a rodada automática nunca usa credencial.
# Instalar: grava os arquivos, systemctl --user daemon-reload e, por tarefa, enable --now etiqueta-<t>.timer.
# Remover: por tarefa, disable --now etiqueta-<t>.timer e apaga só os arquivos com o cabeçalho; no fim,
# daemon-reload. Uma rodada em andamento não é interrompida.
# Sem linger, os timers só rodam com o dono logado; Persistent=true roda na entrada o horário perdido.
# Saídas: 0 ok; 1 erro (arquivo de outro, falha do systemctl); 2 uso errado ou pasta do projeto com caractere
# fora de [A-Za-z0-9/._-] (o caminho vai sem aspas para o ExecStart e o WorkingDirectory).
# Plano: docs/produto/planos/endurecer-entrega2.md, etapa 4 (CA11).

set +x
set -u
shopt -s globasciiranges   # as faixas A-Z e a-z do teste da pasta valem só para ASCII, em qualquer locale

CABECALHO='# Gerado por operacao/instalar-timers.sh. Para mudar, rode o instalador de novo em vez de editar.'
TAREFAS=(backup amazon ml)
# Horários (premissa do plano; para mudar, edite aqui e rode o instalador de novo).
declare -A HORARIO=([backup]='*-*-* 03:30' [amazon]='*-*-* 06:00' [ml]='*-*-* 06:45')
declare -A LIMITE=([backup]='15min' [amazon]='2h' [ml]='8h')
declare -A DESCRICAO=(
    [backup]='backup diário do banco (backup_banco.py --motivo diario)'
    [amazon]='preços da Amazon pela busca (operacao/atualizar-amazon.sh)'
    [ml]='preços do Mercado Livre sem a chave, ou lembrete de token vencido (operacao/atualizar-ml.sh --sem-chave)'
)

uso() {
    echo 'Uso: operacao/instalar-timers.sh [--remover] [backup|amazon|ml ...]' >&2
    echo 'ERRO: a Shopee não roda sozinha: precisa do Secret no terminal (operacao/atualizar-shopee.sh).' >&2
    exit 2
}

REMOVER=0
if [[ ${1-} == --remover ]]; then
    REMOVER=1
    shift
fi
PEDIDAS=()
for t in "$@"; do
    [[ $t == backup || $t == amazon || $t == ml ]] || uso
    [[ " ${PEDIDAS[*]-} " == *" $t "* ]] || PEDIDAS+=("$t")
done
(( ${#PEDIDAS[@]} > 0 )) || PEDIDAS=("${TAREFAS[@]}")

if (( EUID == 0 )); then
    echo 'ERRO: rode como o seu usuário, sem sudo: os timers são do systemd --user.' >&2
    exit 2
fi

RAIZ=$(cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd) || { echo 'ERRO: não achei a pasta do projeto.' >&2; exit 1; }
if [[ -z $RAIZ || $RAIZ == *[!A-Za-z0-9/._-]* ]]; then
    echo 'ERRO: a pasta do projeto tem caractere fora de A-Z, a-z, 0-9, /, ., _ e -; os timers não são' \
         'instalados (o caminho vai para o ExecStart).' >&2
    exit 2
fi
CONFIG=${XDG_CONFIG_HOME:-${HOME-}/.config}
if [[ $CONFIG != /* ]]; then
    echo 'ERRO: XDG_CONFIG_HOME (ou HOME) precisa ser um caminho absoluto.' >&2
    exit 2
fi
DESTINO="$CONFIG/systemd/user"

# e_meu <arquivo>: arquivo comum (não link) cuja 1ª linha é o cabeçalho deste instalador.
e_meu() {
    [[ -f $1 && ! -L $1 ]] && [[ $(head -n 1 -- "$1") == "$CABECALHO" ]]
}

unidade_service() {   # unidade_service <tarefa>
    cat <<FIM
$CABECALHO
[Unit]
Description=Etiqueta: ${DESCRICAO[$1]}
After=network-online.target

[Service]
Type=oneshot
WorkingDirectory=$RAIZ
ExecStart=$RAIZ/operacao/automatico.sh $1
StandardInput=null
UMask=0077
Nice=10
IOSchedulingClass=idle
NoNewPrivileges=yes
TimeoutStartSec=${LIMITE[$1]}
FIM
}

unidade_timer() {   # unidade_timer <tarefa>
    cat <<FIM
$CABECALHO
[Unit]
Description=Etiqueta: ${DESCRICAO[$1]}, diário (${HORARIO[$1]#'*-*-* '})

[Timer]
OnCalendar=${HORARIO[$1]}
RandomizedDelaySec=10min
Persistent=true

[Install]
WantedBy=timers.target
FIM
}

# gravar <gerador> <tarefa> <arquivo>: grava num temporário da mesma pasta e troca pelo nome final (mv), sem
# seguir link simbólico.
gravar() {
    local tmp
    tmp=$(mktemp -- "$DESTINO/.etiqueta-XXXXXXXX") || return 1
    if "$1" "$2" > "$tmp" && chmod 644 -- "$tmp" && mv -f -T -- "$tmp" "$3"; then
        return 0
    fi
    rm -f -- "$tmp"
    return 1
}

if (( REMOVER )); then
    codigo=0
    for t in "${PEDIDAS[@]}"; do
        timer="$DESTINO/etiqueta-$t.timer"
        service="$DESTINO/etiqueta-$t.service"
        if e_meu "$timer" && ! systemctl --user disable --now "etiqueta-$t.timer"; then
            echo "ERRO: o systemctl não desligou etiqueta-$t.timer; os arquivos dele ficaram." >&2
            codigo=1
            continue
        fi
        for arq in "$timer" "$service"; do
            if e_meu "$arq"; then
                rm -f -- "$arq" && echo "Apagado: $arq" || { echo "ERRO: não apaguei $arq." >&2; codigo=1; }
            elif [[ -e $arq || -L $arq ]]; then
                echo "ERRO: $arq não foi gerado por este instalador (sem o cabeçalho); ficou como estava." >&2
                codigo=1
            fi
        done
    done
    systemctl --user daemon-reload || { echo 'ERRO: o systemctl --user daemon-reload falhou.' >&2; codigo=1; }
    exit "$codigo"
fi

if [[ ! -x $RAIZ/operacao/automatico.sh ]]; then
    echo "ERRO: $RAIZ/operacao/automatico.sh não existe ou não é executável." >&2
    exit 1
fi
# Confere tudo antes de gravar qualquer arquivo.
for t in "${PEDIDAS[@]}"; do
    for arq in "$DESTINO/etiqueta-$t.service" "$DESTINO/etiqueta-$t.timer"; do
        if [[ -e $arq || -L $arq ]] && ! e_meu "$arq"; then
            echo "ERRO: $arq já existe e não foi gerado por este instalador (sem o cabeçalho na 1ª linha)." \
                 'Nada foi gravado. Apague ou renomeie esse arquivo e rode de novo.' >&2
            exit 1
        fi
    done
done
mkdir -p -- "$DESTINO" || { echo "ERRO: não consegui criar $DESTINO." >&2; exit 1; }
for t in "${PEDIDAS[@]}"; do
    for tipo in service timer; do
        arq="$DESTINO/etiqueta-$t.$tipo"
        gravar "unidade_$tipo" "$t" "$arq" || { echo "ERRO: não consegui gravar $arq." >&2; exit 1; }
        echo "Gravado: $arq"
    done
done
if ! systemctl --user daemon-reload; then
    echo 'ERRO: o systemctl --user daemon-reload falhou; nenhum timer foi ligado. Para desfazer:' \
         'operacao/instalar-timers.sh --remover' >&2
    exit 1
fi
for t in "${PEDIDAS[@]}"; do
    if ! systemctl --user enable --now "etiqueta-$t.timer"; then
        echo "ERRO: o systemctl não ligou etiqueta-$t.timer. Para desfazer: operacao/instalar-timers.sh --remover" >&2
        exit 1
    fi
    echo "Ligado: etiqueta-$t.timer (${HORARIO[$t]#'*-*-* '}, Persistent=true)"
done
echo 'Pronto. Confira com: systemctl --user list-timers "etiqueta-*"'
