#!/usr/bin/env python3
"""Hook UserPromptSubmit do Claude Code: bloqueia o prompt que traz segredo.

Plano: docs/produto/planos/endurecer-entrega2.md, etapa 2 (CA10). Registro (etapa 7, do dono) em
.claude/settings.json, na forma exec:
`/usr/bin/python3 -I ${CLAUDE_PROJECT_DIR}/.claude/hooks/segredo_no_prompt.py`.

- Entrada: o JSON do Claude Code no stdin; só o campo `prompt` (str) importa. JSON inválido, sem `prompt` ou com
  `prompt` que não é texto: sai com 0, sem nada na saída (o prompt passa).
- Achados: os PADROES_SEGREDO do verificar.py (mesma fonte do portão de commit; a linha com o MARCADOR é
  liberada) e o "bloco solto": um token de 32 a 64 letras e dígitos, com ao menos uma letra e um dígito, que não
  seja só hexadecimal (hash de commit e sha256 passam), solto numa frase. Antes dele: início da linha, espaço,
  aspas (retas, crase ou curvas), `(`, `[`, `{`, `<`, `*` ou `:` (pega `Chave:X`). Depois: fim da linha ou
  espaço, com no máximo uma sequência de pontuação de frase no meio (`.`, `,`, `;`, `:`, `!`, `?`, `)`, `]`, `}`,
  `>`, `*`, aspas). Pedaço de URL, de caminho, de nome de arquivo (`<token>.png`), de `x=<token>` ou de id com
  "-"/"_" (como o file_id do Telegram) não é solto. É a forma de um Secret colado do painel, que os padrões do
  verificar.py não pegam por exigirem palavra-chave. Limite: um Secret com "-" ou "_" no meio não é pego sem a
  palavra-chave. O formato real dos Secrets da Shopee e do ML não foi verificado: a regra é genérica (decisão
  do dono, P4).
- Bloqueio: JSON com `decision: block` e `suppressOriginalPrompt` no stdout, o mesmo texto no stderr e saída 2
  (bloqueia mesmo se o Claude Code não aceitar o JSON). O texto é fixo: diz só os tipos, nunca o trecho.
- O verificar.py é carregado pelo caminho exato (<raiz>/verificar.py), sem mexer no sys.path: um arquivo da
  raiz com nome de módulo da biblioteca padrão (socket.py, por exemplo) nunca é importado no lugar dela.
- Falha aberta (decisão P4): se o verificar.py não carregar, a regra do bloco solto roda sozinha (com o
  marcador local) e bloqueia se achar algo; sem achado, sai com 1 e uma mensagem fixa. Se a varredura quebrar,
  sai com 1 e outra mensagem fixa. O Claude Code trata a saída 1 como erro que não bloqueia.
- Nunca grava nada (nem __pycache__), não usa a rede e nunca põe o prompt ou o trecho achado na saída.
  O bloqueio impede o envio ao Claude, mas não tira o texto do histórico local do Claude Code.
Só biblioteca padrão.
"""
import importlib.util
import json
import os
import re
import sys

sys.dont_write_bytecode = True   # importar o verificar.py não pode criar __pycache__ na raiz

# .claude/hooks/<este arquivo> -> raiz do projeto. O verificar.py é carregado só deste caminho (carregar_verificar),
# e com `python3 -I` nem o diretório atual nem o PYTHONPATH entram no sys.path.
RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VERIFICAR = os.path.join(RAIZ, 'verificar.py')

# O mesmo do verificar.MARCADOR (o teste confere), para o bloco solto valer mesmo sem o verificar.py. Montado em
# duas partes, como lá, para este arquivo não conter o marcador.
MARCADOR = '# verificar: ' + 'permitir'
TIPO_BLOCO = 'bloco solto com cara de chave'
# O token solto numa frase. Antes: nada (início da linha), espaço, aspas, ( [ { < * ou ":" (o `Chave:X`). Depois:
# uma sequência (talvez vazia) de pontuação de frase e então espaço ou o fim da linha. Assim `<token>.png`,
# `https://x.com/<token>`, `x=<token>` e um id com "-"/"_" (como o file_id do Telegram) não são soltos. Sem
# retrocesso quadrático: só começa depois de um delimitador, tenta no máximo 33 tamanhos e só o tamanho que
# termina a sequência de letras e dígitos chega a percorrer a pontuação seguinte.
RE_BLOCO = re.compile(r'''(?<![^\s'"`(\[{<*“‘:])[A-Za-z0-9]{32,64}(?=[.,;:!?)\]}>'"`*”’]*(?:\s|$))''')
RE_LETRA = re.compile(r'[A-Za-z]')
RE_DIGITO = re.compile(r'[0-9]')
RE_SO_HEX = re.compile(r'[0-9A-Fa-f]+')

ERRO_PADROES = ('hook segredo_no_prompt: não carregou os padrões do verificar.py; '
                'o prompt seguiu conferido só pelo bloco solto.\n')
ERRO_VARREDURA = 'hook segredo_no_prompt: a conferência de segredo falhou; o prompt seguiu sem ela.\n'


def ler_prompt(dados):
    """O texto do campo `prompt`, ou None se a entrada não for o JSON esperado."""
    try:
        entrada = json.loads(dados)
    except (ValueError, RecursionError):   # inclui JSONDecodeError, UnicodeDecodeError e aninhamento sem fim
        return None
    if not isinstance(entrada, dict):
        return None
    prompt = entrada.get('prompt')
    return prompt if isinstance(prompt, str) else None


def tem_bloco_solto(linha):
    for m in RE_BLOCO.finditer(linha):
        token = m.group()
        if RE_LETRA.search(token) and RE_DIGITO.search(token) and not RE_SO_HEX.fullmatch(token):
            return True
    return False


def carregar_verificar():
    """O módulo <raiz>/verificar.py, carregado pelo caminho exato, sem mexer no sys.path (S2). Erro sobe."""
    spec = importlib.util.spec_from_file_location('verificar', VERIFICAR)
    if spec is None or spec.loader is None:
        raise ImportError('verificar.py')
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def tipos_achados(prompt, verificar):
    """Tipos (sem repetição, na ordem em que aparecem) dos segredos do prompt. Nunca o trecho. Com `verificar`
    None (não carregou), só o bloco solto, com o marcador local."""
    linhas = list(enumerate(prompt.splitlines(), 1))
    tipos = []
    marcador = MARCADOR
    if verificar is not None:
        marcador = verificar.MARCADOR
        for achado in verificar.varrer_linhas('prompt', linhas):
            if not achado.liberado and achado.tipo not in tipos:
                tipos.append(achado.tipo)
    if any(marcador not in texto and tem_bloco_solto(texto) for _, texto in linhas):
        tipos.append(TIPO_BLOCO)
    return tipos


def mensagem(tipos, marcador):
    return (f'Bloqueado: o prompt parece ter um segredo ({", ".join(tipos)}). Ele não foi enviado ao Claude, '
            'mas pode ter ficado no histórico local do Claude Code. Se a chave for real, gere outra no painel. '
            f'Para enviar mesmo assim (falso positivo), ponha `{marcador}` na linha.')


def main():
    prompt = ler_prompt(sys.stdin.buffer.read())
    if prompt is None:
        return 0
    try:
        verificar = carregar_verificar()
    except Exception:   # S3: sem os padrões, o bloco solto ainda roda; sem achado, falha aberta (saída 1)
        verificar = None
    try:
        tipos = tipos_achados(prompt, verificar)
    except Exception:   # a mensagem de uma exceção pode citar o texto: só a fixa sai
        sys.stderr.write(ERRO_VARREDURA)
        return 1
    if not tipos:
        if verificar is None:
            sys.stderr.write(ERRO_PADROES)
            return 1
        return 0
    razao = mensagem(tipos, MARCADOR if verificar is None else verificar.MARCADOR)
    sys.stdout.write(json.dumps({
        'decision': 'block',
        'reason': razao,
        'hookSpecificOutput': {'hookEventName': 'UserPromptSubmit', 'suppressOriginalPrompt': True},
    }) + '\n')
    sys.stderr.write(razao + '\n')
    return 2


if __name__ == '__main__':
    sys.exit(main())
