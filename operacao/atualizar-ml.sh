#!/usr/bin/env bash
# Atualiza os preços do Mercado Livre pela API oficial (catálogo), uma aba por vez.
#
# Uso:  operacao/atualizar-ml.sh [aba ...]
#       sem aba: todas as abas do buscas.json, na ordem do arquivo.
#       PAUSA_SEG=N muda a espera depois de uma saída 3 (padrão 300 s).
#
# Por aba: python3 atualizar_precos.py ml --cat "<aba>" --vincular 300 --max-chamadas 1500
# (sem --cat, a API do ML dá 429 logo no início; aba por aba funciona).
#
# Pede a Chave secreta da app "Etiqueta" sem mostrar na tela. Enter vazio = usar o token atual (ele vale umas
# 6 h e só se renova com a chave). A chave só vai para o ambiente do comando, nunca para arquivo, argv ou log.
#
# Saídas do atualizar_precos.py, por aba:
#   0 segue;  3 (teto ou 429) espera PAUSA_SEG e segue para a próxima;
#   2 sem a chave: pede a chave e repete a mesma aba;  2 com a chave, 4 ou 1: para com instrução.
# Este script sai com 0 (tudo ok), 3 (alguma aba parou no teto ou no limite: rode de novo depois) ou com o
# código da aba que parou. No fim, imprime um resumo por aba. Plano: endurecer-engenharia-e-operacao, etapa 7.

source "$(dirname -- "${BASH_SOURCE[0]}")/comum.sh" || exit 1

pausa_seg
iniciar_log atualizar-ml
abas_txt=$(abas_validas "$@") || exit 2
mapfile -t ABAS <<< "$abas_txt"

S=''
read -rsp 'Chave secreta do Mercado Livre (não aparece na tela; Enter vazio = usar o token atual): ' S; echo
fazer_backup ml

ml_sem_chave() { python3 atualizar_precos.py ml --cat "$1" --vincular 300 --max-chamadas 1500; }
ml_com_chave() { ACHADINHOS_ML_SECRET="$S" python3 atualizar_precos.py ml --cat "$1" --vincular 300 --max-chamadas 1500; }
rodar_aba() {
    if [[ -n $S ]]; then rodar ml_com_chave "$1"; else rodar ml_sem_chave "$1"; fi
}

SAIDAS=()    # SAIDAS[i] e RESUMOS[i]: saída e linha RESUMO da aba ABAS[i] (só das que rodaram)
RESUMOS=()
total=${#ABAS[@]}
codigo=0
restantes=()

for i in "${!ABAS[@]}"; do
    aba=${ABAS[i]}
    echo "== [$((i + 1))/$total] $aba ($(date +%H:%M))"
    rodar_aba "$aba"; r=$?
    if [[ $r -eq 2 && -z $S ]]; then
        echo 'O acesso ao Mercado Livre venceu e precisa da Chave secreta para ser renovado.'
        read -rsp 'Chave secreta do Mercado Livre (não aparece na tela): ' S; echo
        if [[ -n $S ]]; then
            echo "Repetindo a aba $aba com a chave..."
            rodar_aba "$aba"; r=$?
        fi
    fi
    SAIDAS[i]=$r
    RESUMOS[i]=$ULTIMO_RESUMO
    case $r in
        0) ;;
        3)
            codigo=3
            if (( i + 1 < total )); then
                echo "Aba $aba parou no teto ou no limite da API; esperando ${PAUSA}s antes da próxima..."
                sleep "$PAUSA"
            fi
            ;;
        *)
            codigo=$r
            if [[ $r -eq 2 && -z $S ]]; then
                echo "PAROU na aba $aba: o acesso venceu e nenhuma chave foi digitada. Rode de novo e digite a" \
                     "Chave secreta da app \"Etiqueta\"."
            elif [[ $r -eq 2 ]]; then
                echo "PAROU na aba $aba: o Mercado Livre recusou o acesso mesmo com a chave, ou falta configuração" \
                     "(veja a linha ERRO acima). Confira com: python3 ml_api.py conferir. Se os tokens sumiram ou" \
                     "foram recusados, autorize de novo: read -rs S; ACHADINHOS_ML_SECRET=\"\$S\" python3" \
                     "ml_api.py autorizar; unset S"
                [[ -n $ULTIMO_AVISO ]] && echo "Mensagem do comando: $ULTIMO_AVISO"
            elif [[ $r -eq 4 ]]; then
                instrucao_saida4 ml
            else
                instrucao_erro "na aba $aba" "$r"
            fi
            restantes=("${ABAS[@]:i}")
            break
            ;;
    esac
done

echo
echo "RESUMO DAS ABAS (log: $LOG)"
for i in "${!ABAS[@]}"; do
    if [[ -n ${SAIDAS[i]+x} ]]; then
        echo "  ${ABAS[i]} | saída ${SAIDAS[i]} | ${RESUMOS[i]:-sem linha RESUMO ml:}"
    else
        echo "  ${ABAS[i]} | não rodou"
    fi
done
if (( ${#restantes[@]} > 0 )); then
    printf 'Para seguir depois de resolver, rode só as abas que faltam:\n  operacao/atualizar-ml.sh'
    printf ' "%s"' "${restantes[@]}"
    printf '\n'
elif [[ $codigo -eq 3 ]]; then
    echo 'Alguma aba parou no teto ou no limite da API: rode de novo mais tarde; o ML retoma pelos preços mais antigos.'
fi
exit "$codigo"
