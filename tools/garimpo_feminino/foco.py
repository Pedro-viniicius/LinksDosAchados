"""Foco feminino de um produto e slug de nicho do garimpo (sem rede, só biblioteca padrão).

Regras do brief (seção "Score de foco feminino"), calculadas sem acento e por
palavra inteira:
  +3  a categoria é `feminina` (`mista` e `fora` somam 0);
  +2  o título tem algum termo feminino (uma vez, por mais termos que tenha);
  -5  o título tem algum termo masculino;
  -3  o título tem algum termo infantil, exceto no nicho Gestante & Maternidade.

Faixas (premissa P5 do plano): >= 5 alto, 2 a 4 medio, 0 a 1 neutro, < 0 descartado;
categoria `fora` é sempre descartado. Nada é apagado: o resultado só marca o item.
"""
import re
import unicodedata

CLASSES = ('feminina', 'mista', 'fora')
FAIXAS = ('alto', 'medio', 'neutro', 'descartado')

PONTOS_CLASSE_FEMININA = 3
PONTOS_TERMO_FEMININO = 2
PONTOS_TERMO_MASCULINO = -5
PONTOS_TERMO_INFANTIL = -3

# Gestante & Maternidade: o nicho vende bebê e infantil de propósito, então o -3 não vale.
# Aceita o slug do nichos.json e o slug que `slug()` tira do nome.
NICHOS_SEM_PENALIDADE_INFANTIL = frozenset({'gestante', 'gestantematernidade'})

# Termos já sem acento e em minúsculas. `*` no fim = qualquer terminação (feminin*, mulher*,
# masculin*). Os demais casam a palavra inteira, com `s` opcional para o plural (vestidos,
# calcinhas, mens); "lady" também casa "ladies".
_FEMININOS = ('feminin*', 'mulher*', 'dama', 'lady', 'gestante', 'gravida', 'maternidade',
              'sutia', 'calcinha', 'biquini', 'saia', 'vestido', 'lingerie')
_MASCULINOS = ('masculin*', 'homem', 'homens', 'barba', 'barbear', 'cueca', 'men')
_INFANTIS = ('infantil', 'infantis', 'bebe', 'kids', 'menino')


def _regex(termos):
    partes = []
    for t in termos:
        if t.endswith('*'):
            partes.append(re.escape(t[:-1]) + r'\w*')
        elif t == 'lady':
            partes.append(r'(?:lady|ladies)')
        elif t.endswith('s'):
            partes.append(re.escape(t))
        else:
            partes.append(re.escape(t) + 's?')
    return re.compile(r'\b(?:' + '|'.join(partes) + r')\b')


_RE_FEMININO = _regex(_FEMININOS)
_RE_MASCULINO = _regex(_MASCULINOS)
_RE_INFANTIL = _regex(_INFANTIS)


def _normalizar(texto):
    """Minúsculas, sem acento e só letras e números separados por espaço único."""
    if not isinstance(texto, str):
        return ''
    t = unicodedata.normalize('NFKD', texto)
    t = ''.join(c for c in t if not unicodedata.combining(c)).lower()
    return re.sub(r'[\W_]+', ' ', t).strip()


def slug(texto):
    """Só `[a-z0-9]`, sem acento nem separador, com até 20 caracteres (limite do subId)."""
    return re.sub(r'[^a-z0-9]', '', _normalizar(texto))[:20]


def faixa(pontos, classe=None):
    """Faixa do foco: categoria `fora` é descartado; senão, as faixas da premissa P5."""
    if classe == 'fora' or pontos < 0:
        return 'descartado'
    if pontos >= 5:
        return 'alto'
    if pontos >= 2:
        return 'medio'
    return 'neutro'


def score(titulo, classe, nicho):
    """Devolve `(pontos, faixa)` do título numa categoria de `classe` e `nicho`.

    `classe` é `feminina`, `mista` ou `fora` (`None` conta como `mista`; outro valor é
    ValueError). `nicho` é o slug (ou o nome) do nicho, ou `None`.
    """
    if classe is not None and classe not in CLASSES:
        raise ValueError('classe inválida: %r' % (classe,))
    t = _normalizar(titulo)
    pontos = PONTOS_CLASSE_FEMININA if classe == 'feminina' else 0
    if _RE_FEMININO.search(t):
        pontos += PONTOS_TERMO_FEMININO
    if _RE_MASCULINO.search(t):
        pontos += PONTOS_TERMO_MASCULINO
    if _RE_INFANTIL.search(t) and slug(nicho) not in NICHOS_SEM_PENALIDADE_INFANTIL:
        pontos += PONTOS_TERMO_INFANTIL
    return pontos, faixa(pontos, classe)
