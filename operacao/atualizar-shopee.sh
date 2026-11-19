#!/usr/bin/env bash
# Atualiza os preços da Shopee pela Open API de afiliados, item a item.
#
# Uso:  operacao/atualizar-shopee.sh [aba]      (padrão: "Perfumes e Perfumaria")
#       PAUSA_SEG=N muda a espera depois de um limite da API no teste pequeno (padrão 300 s).
#
# Passos (como no antigo ~/atualizar-shopee.sh):
#   1. python3 coletar_shopee.py conferir --por-item   (1 chamada, não grava nada; qualquer erro para aqui)
#   2. python3 atualizar_precos.py shopee --cat "<aba>" --max-chamadas 10   (teste pequeno)
#      0 segue; 3 pelo teto de 10 chamadas (o normal) segue na hora; 3 pelo limite da API espera PAUSA_SEG e segue
#   3. python3 atualizar_precos.py shopee --cat "<aba>"   (a aba inteira)
#   Saída 2, 4 ou 1 em qualquer passo para com instrução; 3 no passo 3 para e pede para rodar de novo depois.
#
# Pede o AppID e o Secret da Open API sem mostrar na tela. Eles só vão para o ambiente de cada comando,
# nunca para arquivo, argv ou log. Plano: endurecer-engenharia-e-operacao, etapa 7.

source "$(dirname -- "${BASH_SOURCE[0]}")/comum.sh" || exit 1

if (( $# > 1 )); then
    echo 'Uso: operacao/atualizar-shopee.sh [aba]   (padrão: "Perfumes e Perfumaria")' >&2
    exit 2
fi
pausa_seg
iniciar_log atualizar-shopee
ABA=$(abas_validas "${1:-Perfumes e Perfumaria}") || exit 2

A=''
S=''
read -rsp 'AppID da Open API (não aparece na tela): ' A; echo
read -rsp 'Secret da Open API (não aparece na tela): ' S; echo
if [[ -z $A || -z $S ]]; then
    echo 'PAROU: o AppID e o Secret da Open API são obrigatórios. Rode de novo e digite os dois.'
    exit 2
fi
fazer_backup shopee

shp() { ACHADINHOS_SHOPEE_APP_ID="$A" ACHADINHOS_SHOPEE_SECRET="$S" python3 "$@"; }

parar() {   # parar <passo> <saída>
    if [[ $2 -eq 2 ]]; then
        echo "PAROU no $1 (saída 2): credencial recusada ou configuração faltando (veja a linha ERRO acima)." \
             "Confira o AppID, o Secret e o ID_AFILIADO_SHOPEE e rode de novo."
        [[ -n $ULTIMO_AVISO ]] && echo "Mensagem do comando: $ULTIMO_AVISO"
    elif [[ $2 -eq 4 ]]; then
        instrucao_saida4 shopee
    else
        instrucao_erro "no $1" "$2"
    fi
    exit "$2"
}

echo '1/3 Conferindo a credencial e a consulta por produto (1 chamada, não grava nada)...'
rodar shp coletar_shopee.py conferir --por-item; r=$?
if [[ $r -eq 3 ]]; then
    echo 'PAROU no passo 1/3: a API da Shopee está no limite. Espere de 15 a 30 minutos e rode de novo.'
    exit 3
fi
[[ $r -eq 0 ]] || parar 'passo 1/3' "$r"

echo "2/3 Teste pequeno: 10 produtos da aba $ABA..."
rodar shp atualizar_precos.py shopee --cat "$ABA" --max-chamadas 10; r=$?
resumo_teste=$ULTIMO_RESUMO
if [[ $r -eq 3 ]]; then
    if [[ $ULTIMO_AVISO != *'teto de chamadas'* ]]; then
        echo "A API da Shopee pediu uma pausa; esperando ${PAUSA}s antes da aba inteira..."
        sleep "$PAUSA"
    fi
elif [[ $r -ne 0 ]]; then
    parar 'passo 2/3' "$r"
fi

echo "3/3 Atualização completa da aba $ABA (na Perfumaria, de 20 a 30 minutos)..."
rodar shp atualizar_precos.py shopee --cat "$ABA"; r=$?
echo
echo "RESUMO DA RODADA (log: $LOG)"
echo "  teste pequeno | ${resumo_teste:-sem linha RESUMO shopee:}"
echo "  aba $ABA | saída $r | ${ULTIMO_RESUMO:-sem linha RESUMO shopee:}"
if [[ $r -eq 3 ]]; then
    echo 'PAROU no passo 3/3: teto de chamadas ou limite da API. O progresso foi salvo; rode de novo mais tarde' \
         '(o que já foi confirmado hoje fica de fora).'
    exit 3
fi
[[ $r -eq 0 ]] || parar 'passo 3/3' "$r"
echo 'Terminou. Avise o Claude, que ele confere no banco.'
exit 0
