#!/usr/bin/env bash
# Atualiza os preços da Amazon pela busca (cerca de 40 minutos), sem credencial.
#
# Uso:  operacao/atualizar-amazon.sh [--produtos N]
#       --produtos N abre depois a página do produto de até N itens não vistos (0 a 500; padrão 0).
#
# Roda python3 atualizar_precos.py amazon [--produtos N]. Saídas: 0 ok; 3 a Amazon bloqueou (captcha, 503 ou
# 429): espere algumas horas e rode de novo, que a rodada retoma; 4 outra rodada da Amazon no ar; 2 argumento;
# 1 erro. Este script sai com o mesmo código. Plano: endurecer-engenharia-e-operacao, etapa 7.

source "$(dirname -- "${BASH_SOURCE[0]}")/comum.sh" || exit 1

EXTRA=()
if (( $# == 2 )) && [[ $1 == --produtos && $2 =~ ^[0-9]{1,3}$ ]]; then
    EXTRA=(--produtos "$2")
elif (( $# != 0 )); then
    echo 'Uso: operacao/atualizar-amazon.sh [--produtos N]   (N de 0 a 500)' >&2
    exit 2
fi
iniciar_log atualizar-amazon
fazer_backup amazon

echo 'Atualizando os preços da Amazon pela busca (cerca de 40 minutos)...'
rodar python3 atualizar_precos.py amazon "${EXTRA[@]}"; r=$?
echo
echo "RESUMO DA RODADA (log: $LOG)"
echo "  amazon | saída $r | ${ULTIMO_RESUMO:-sem linha RESUMO amazon:}"
case $r in
    0) echo 'Terminou. Avise o Claude, que ele confere no banco.' ;;
    3) echo 'PAROU: a Amazon bloqueou (captcha, 503 ou 429). O progresso foi salvo. Espere algumas horas antes de' \
            'rodar de novo: a rodada retoma de onde parou.' ;;
    4) instrucao_saida4 amazon ;;
    *) instrucao_erro 'na rodada da Amazon' "$r" ;;
esac
exit "$r"
