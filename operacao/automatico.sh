#!/usr/bin/env bash
# Rodada automática: o ponto de entrada dos timers do systemd --user (etiqueta-<tarefa>.timer), gerados por
# operacao/instalar-timers.sh. Também pode ser chamado à mão, para testar.
#
# Uso:  operacao/automatico.sh backup|amazon|ml
#   backup   backup diário do banco: python3 backup_banco.py --motivo diario (log em logs/automatico-backup-*);
#   amazon   operacao/atualizar-amazon.sh (preços da Amazon pela busca, sem credencial);
#   ml       operacao/atualizar-ml.sh --sem-chave (só funciona enquanto o token do ML vale, umas 6 h depois de
#            uma rodada manual com a chave; vencido, para antes do backup e vira um lembrete).
# A Shopee não tem tarefa e não roda sozinha: ela precisa do AppID e do Secret digitados no terminal pelo dono
# (operacao/atualizar-shopee.sh). Qualquer outra tarefa, inclusive shopee, sai com 2.
#
# Guardas, nesta ordem, antes de qualquer outro comando (nada de log, backup ou rodada antes delas):
#   1. uma variável de segredo (ACHADINHOS_ML_SECRET, ACHADINHOS_SHOPEE_SECRET, ACHADINHOS_SHOPEE_APP_ID) no
#      ambiente, mesmo vazia: sai com 2 sem mostrar o valor (só o nome) e sem passá-la a nenhum comando;
#   2. código em edição: o `git status` acusa qualquer mudança sem commit (no índice ou fora dele, inclusive
#      arquivo novo não rastreado ou apagado) num .py da raiz do projeto, no buscas.json ou em operacao/, ou o git
#      não responde: sai com 1. Guarda larga: entram os módulos que as rodadas importam (o coletar_amazon.py, pelo
#      atualizar_precos.py amazon) e um módulo novo que ainda não foi commitado; testes/ e index.html ficam fora.
#      --glob-pathspecs: o "*" não passa de uma pasta (só a raiz), e um GIT_LITERAL_PATHSPECS ou
#      GIT_NOGLOB_PATHSPECS no ambiente faz o git recusar (saída 128, a guarda para) em vez de não achar nada.
#      O git roda com GIT_OPTIONAL_LOCKS=0, para não disputar o índice com quem está trabalhando no projeto.
#
# Aviso: com saída diferente de 0, um aviso de área de trabalho (notify-send, se existir) com título
# "Etiqueta: <tarefa> parou (saída N)" e um texto fixo por código, nunca a saída de um comando (ela pode trazer
# título de produto ou mensagem da loja). O detalhe fica no log em logs/ e no journal:
#   journalctl --user -u etiqueta-<tarefa>
# Falha do notify-send é ignorada. O script sai com o código da tarefa (0 ok; 1 erro; 2 ML vencido ou uso
# errado; 3 bloqueio ou limite da loja; 4 outra rodada da mesma loja no ar).
# Plano: docs/produto/planos/endurecer-entrega2.md, etapa 4 (CA11).

set +x
set -u
umask 077

TAREFA=${1-}
if (( $# != 1 )) || [[ $TAREFA != backup && $TAREFA != amazon && $TAREFA != ml ]]; then
    echo 'Uso: operacao/automatico.sh backup|amazon|ml' >&2
    echo 'ERRO: a Shopee não roda sozinha: precisa do Secret no terminal (operacao/atualizar-shopee.sh).' >&2
    exit 2
fi
exec < /dev/null    # nenhum comando da rodada automática lê o teclado nem o que vier na entrada

# avisar <saída> <texto fixo>: aviso de área de trabalho; nunca recebe saída de comando. Sem notify-send (ou
# sem sessão gráfica), o timeout sai com erro e nada muda.
avisar() {
    timeout 15 notify-send -a Etiqueta "Etiqueta: $TAREFA parou (saída $1)" "$2" > /dev/null 2>&1 || true
    return 0
}
JOURNAL="detalhes em journalctl --user -u etiqueta-$TAREFA"

# Guarda 1: segredo no ambiente.
achados=()
for nome in ACHADINHOS_ML_SECRET ACHADINHOS_SHOPEE_SECRET ACHADINHOS_SHOPEE_APP_ID; do
    if [[ -v $nome ]]; then
        achados+=("$nome")
    fi
done
if (( ${#achados[@]} > 0 )); then
    unset -v ACHADINHOS_ML_SECRET ACHADINHOS_SHOPEE_SECRET ACHADINHOS_SHOPEE_APP_ID   # nem o aviso as herda
    echo "PAROU: variável de segredo no ambiente da rodada automática (${achados[*]}). A rodada automática" \
         'nunca roda com segredo: tire a variável do ambiente (por exemplo, systemctl --user' \
         'unset-environment <nome>) e rode de novo. Nada rodou.'
    avisar 2 "segredo no ambiente: nada rodou; $JOURNAL"
    exit 2
fi

# Guarda 2: código em edição.
RAIZ=$(cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd) ||
    { echo 'ERRO: não achei a pasta do projeto.'; avisar 1 "erro: pasta do projeto; $JOURNAL"; exit 1; }
cd -- "$RAIZ" || { echo 'ERRO: não consegui entrar na pasta do projeto.'; avisar 1 "erro: pasta do projeto; $JOURNAL"; exit 1; }
# A saída tem de vir vazia: qualquer linha é mudança sem commit. Sem o git, o comando sai com 127 e a guarda
# também para.
if ! sujos=$(GIT_OPTIONAL_LOCKS=0 git --glob-pathspecs status --porcelain --untracked-files=normal -- \
       '*.py' buscas.json operacao/) || [[ -n $sujos ]]; then
    echo 'PAROU: código com mudança sem commit: a rodada automática não roda código em edição (ou o git não' \
         'respondeu). Faça o commit, ou descarte a mudança, e espere o próximo horário; ou rode à mão no terminal.' \
         'Nada rodou.'
    avisar 1 "código com mudança sem commit: nada rodou; $JOURNAL"
    exit 1
fi

echo "Rodada automática: $TAREFA ($(date '+%d/%m/%Y %H:%M'))"
case $TAREFA in
    backup)
        # Num subshell: o log (iniciar_log) e um `exit` do comum.sh ficam nele, e o aviso abaixo sempre roda.
        (
            source "$RAIZ/operacao/comum.sh" || exit 1
            iniciar_log automatico-backup
            echo 'Backup diário do banco (motivo diario)...'
            python3 backup_banco.py --motivo diario; r=$?
            if [[ $r -ne 0 ]]; then
                echo "PAROU: o backup diário falhou (saída $r, mensagem acima). Confira o espaço em disco e a" \
                     'pasta backups/.'
            fi
            exit "$r"
        ); r=$?
        ;;
    amazon) "$RAIZ/operacao/atualizar-amazon.sh"; r=$? ;;
    ml) "$RAIZ/operacao/atualizar-ml.sh" --sem-chave; r=$? ;;
esac

if [[ $r -ne 0 ]]; then
    case $r in
        2) if [[ $TAREFA == ml ]]; then texto='acesso vencido: rode operacao/atualizar-ml.sh no terminal'
           else texto='erro: veja o log'; fi ;;
        3) texto='bloqueio ou limite da loja: a próxima rodada retoma' ;;
        4) texto='outra rodada da mesma loja estava no ar' ;;
        *) texto='erro: veja o log' ;;
    esac
    avisar "$r" "$texto; detalhes em logs/"
fi
exit "$r"
