#!/usr/bin/env python3
"""Público (gênero) das ofertas (docs/produto/planos/genero-nas-categorias.md).

O gênero é derivado na leitura a partir de `cat`, `busca` e `titulo`; só a correção do dono fica no
banco (tabela `generos_manuais`, criada por `disparo.migrar` na versão 2 do esquema). Uma regra
determinística, na ordem: correção manual, título, linha de produto conhecida no título, termo `busca`.

Só biblioteca padrão. Não importa `servidor` nem `disparo` (os dois, e o `api_ofertas`, importam este).
"""
import re
import sqlite3
import unicodedata

GENEROS = ('feminino', 'masculino', 'unissex', 'sem')
# Só estas abas têm público. Aba nova: acrescente o nome exato aqui (o teste confere com o buscas.json).
ABAS_COM_GENERO = ('Perfumes e Perfumaria',)

# Os padrões rodam sobre o texto já sem acento e em minúsculas (`_norm`), e com `\b` nas pontas.
_U = r'unissex|unisex|unissexo|ambos os sexos'
_M = r'masculin[oa]s?|masc|homem|homens|homme|men|man|uomo|hombres?|male|boys?|menino|for him|pour lui'
_F = (r'feminin[oa]s?|fem|mulher(?:es)?|women|woman|femme|donna|mujer(?:es)?|lady|girls?|menina|'
      r'for her|pour elle')
_RE_U = re.compile(r'\b(?:%s)\b' % _U)
_RE_M = re.compile(r'\b(?:%s)\b' % _M)
_RE_F = re.compile(r'\b(?:%s)\b' % _F)

# Linhas de perfumaria cujo gênero é conhecido. O título com palavra de gênero (passo anterior) vence:
# "Lady Million Paco Rabanne Feminino" sai feminino.
_RE_LINHA_M = re.compile(r'\b(?:invictus|sauvage|malbec|million|pos[- ]?barba|barbear|barber)')
_RE_LINHA_F = re.compile(r'\bla vie est belle\b')
_RE_LINHA_U = re.compile(r'\bck one\b')
# A coleta traz ruído: vinho "Malbec" e "Bota Invictus" aparecem na aba de perfumaria. Título com uma
# destas palavras não é perfume, então a linha de produto não vale (a palavra de gênero, o passo 2,
# continua valendo). Lista curta de propósito: nenhuma delas aparece em título de perfume na base
# de 2026-11-03 (medido), e o que escapar o dono corrige à mão.
_RE_NAO_PERFUME = re.compile(
    r'\b(?:vinhos?|tintos?|bota|botas|botina|botinas|coturno|coturnos|sapato|sapatos|tenis|sandalias?)\b')


def _norm(texto):
    """NFKD, sem acento (marcas combinantes) e em minúsculas, para casar as palavras."""
    if not isinstance(texto, str):
        return ''
    texto = unicodedata.normalize('NFKD', texto)
    return ''.join(c for c in texto if not unicodedata.combining(c)).casefold()


def _por_palavras(texto):
    """Gênero pelas palavras de gênero do texto normalizado, ou '' se não há nenhuma.
    Unissex declarado, ou masculino e feminino juntos, dá unissex."""
    if _RE_U.search(texto):
        return 'unissex'
    m = _RE_M.search(texto)
    f = _RE_F.search(texto)
    if m and f:
        return 'unissex'
    if m:
        return 'masculino'
    if f:
        return 'feminino'
    return ''


def classificar(cat, busca, titulo):
    """(genero, origem). origem: 'titulo' (palavra ou linha de produto no título), 'busca' ou '' (sem).
    Aba fora de `ABAS_COM_GENERO` é sempre ('sem', '')."""
    if cat not in ABAS_COM_GENERO:
        return 'sem', ''
    t = _norm(titulo)
    g = _por_palavras(t)
    if g:
        return g, 'titulo'
    if not _RE_NAO_PERFUME.search(t):
        if _RE_LINHA_M.search(t):
            return 'masculino', 'titulo'
        if _RE_LINHA_F.search(t):
            return 'feminino', 'titulo'
        if _RE_LINHA_U.search(t):
            return 'unissex', 'titulo'
    g = _por_palavras(_norm(busca))
    if g:
        return g, 'busca'
    return 'sem', ''


def manuais(con):
    """{item_pk: genero} das correções do dono. {} se a tabela não existe (banco ainda não migrado)."""
    try:
        linhas = con.execute('SELECT item_pk, genero FROM generos_manuais').fetchall()
    except sqlite3.OperationalError:
        return {}
    return {pk: g for pk, g in linhas if g in GENEROS}


def do_item(item_pk, cat, busca, titulo, manuais):
    """(genero, origem) do item. A correção manual vale só em aba com gênero (origem 'manual'); fora
    dela o item é 'sem' e a correção fica guardada para quando ele voltar."""
    if cat not in ABAS_COM_GENERO:
        return 'sem', ''
    g = (manuais or {}).get(item_pk)
    if g in GENEROS:
        return g, 'manual'
    return classificar(cat, busca, titulo)


def definir_manual(con, item_pk, genero_ou_None, agora_iso):
    """Grava a correção do item, ou apaga com None (volta ao automático). Não faz commit.
    Gravar o mesmo valor que já existe não muda nada (nem `atualizado_em`, nem `con.total_changes`).
    ValueError se o valor não é um de GENEROS (nem None); a mensagem não repete o valor."""
    if genero_ou_None is None:
        con.execute('DELETE FROM generos_manuais WHERE item_pk=?', (item_pk,))
        return
    if genero_ou_None not in GENEROS:
        raise ValueError('genero fora da lista')
    con.execute(
        'INSERT INTO generos_manuais (item_pk, genero, atualizado_em) VALUES (?,?,?) '
        'ON CONFLICT(item_pk) DO UPDATE SET genero=excluded.genero, atualizado_em=excluded.atualizado_em '
        'WHERE generos_manuais.genero IS NOT excluded.genero',
        (item_pk, genero_ou_None, agora_iso))
