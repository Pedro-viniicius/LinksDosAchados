#!/usr/bin/env python3
"""Disparo automático de ofertas (docs/produto/planos/disparo-automatico.md).

Regras do dono escolhem itens do banco, montam a mensagem igual à do card e entregam a um
transporte trocável. Esta entrega traz o transporte "manual" (o envio fica pendente na fila da
tela) e o "falso" (só para teste).

Só biblioteca padrão. Não importa `servidor`, para não criar import circular com o __main__ dele:
quem chama passa `conectar` e `eh_afiliado` (o `eh_link_afiliado` do servidor) por parâmetro.

Dado pessoal: telefone e id do grupo ficam só na tabela `numeros`. Nunca entram em mensagem de
exceção, log, `envios.motivo` nem no arquivo do transporte falso.
"""
import json
import logging
import os
import random
import re
import sqlite3
import threading
import unicodedata
import urllib.parse
from datetime import date, datetime, timedelta

log = logging.getLogger('disparo')

VERSAO_ESQUEMA = 1
ESQUEMA_V1 = (
    '''CREATE TABLE IF NOT EXISTS numeros (id INTEGER PRIMARY KEY AUTOINCREMENT,
      nome TEXT NOT NULL, telefone TEXT NOT NULL DEFAULT '', grupo_nome TEXT NOT NULL,
      grupo_id TEXT NOT NULL DEFAULT '', limite_diario INTEGER NOT NULL DEFAULT 40,
      ativo INTEGER NOT NULL DEFAULT 1, criado_em TEXT, atualizado_em TEXT)''',
    '''CREATE TABLE IF NOT EXISTS regras (id INTEGER PRIMARY KEY AUTOINCREMENT,
      nome TEXT NOT NULL, numero_id INTEGER NOT NULL, ativa INTEGER NOT NULL DEFAULT 1,
      cats TEXT NOT NULL, lojas TEXT NOT NULL DEFAULT '["amazon","ml"]', palavras TEXT NOT NULL DEFAULT '[]',
      desconto_min INTEGER NOT NULL DEFAULT 0, ordem TEXT NOT NULL DEFAULT 'relevancia',
      template TEXT NOT NULL, com_foto INTEGER NOT NULL DEFAULT 1,
      dias TEXT NOT NULL DEFAULT '[0,1,2,3,4,5,6]', horarios TEXT NOT NULL,
      por_disparo INTEGER NOT NULL DEFAULT 1, max_por_dia INTEGER NOT NULL DEFAULT 10,
      repetir_apos_dias INTEGER DEFAULT 7, intervalo_seg INTEGER NOT NULL DEFAULT 60,
      aviso TEXT NOT NULL DEFAULT '', criado_em TEXT, atualizado_em TEXT)''',
    '''CREATE TABLE IF NOT EXISTS envios (id INTEGER PRIMARY KEY AUTOINCREMENT,
      regra_id INTEGER NOT NULL, numero_id INTEGER NOT NULL, item_pk INTEGER NOT NULL,
      slot TEXT NOT NULL, status TEXT NOT NULL, mensagem TEXT NOT NULL, imagem TEXT NOT NULL DEFAULT '',
      titulo TEXT NOT NULL DEFAULT '', motivo TEXT NOT NULL DEFAULT '', transporte TEXT NOT NULL,
      criado_em TEXT NOT NULL, enviado_em TEXT, UNIQUE(regra_id, slot, item_pk))''',
    'CREATE INDEX IF NOT EXISTS ix_envios_rep ON envios(numero_id, item_pk, criado_em)',
)

ORDENS = ('relevancia', 'desconto', 'menor_preco', 'maior_preco', 'cupom', 'recentes', 'aleatoria')
LOJAS = ('amazon', 'ml', 'shopee')
STATUS = ('pendente', 'enviando', 'enviado', 'incerto', 'erro', 'pulado', 'expirado')
# Status que contam como "já mandado" para não repetir (CA5) e para os limites do dia (CA6).
STATUS_OCUPA = ('enviado', 'pendente', 'enviando', 'incerto')
TOLERANCIA = timedelta(minutes=10)   # horário perdido há mais que isso é pulado (CA6)
MAX_PREVIA = 20
LIMITE_HISTORICO = 500
# Host do link de afiliado de cada loja (link_da_loja_ok). O formato do link (tag, código) quem confere é o
# eh_afiliado do servidor; aqui se exige só que o host seja o da loja do item.
# Shopee: host do link curto do painel de afiliados, a confirmar com um link real do dono (F3 do plano
# docs/produto/planos/perfumaria-tres-lojas.md). Mesmo valor do HOSTS_AFILIADO_SHOPEE do servidor.py.
HOSTS_AFILIADO_SHOPEE = ('s.shopee.com.br',)
HOSTS_LINK_LOJA = {'amazon': ('www.amazon.com.br',), 'ml': ('meli.la',), 'shopee': HOSTS_AFILIADO_SHOPEE}
# CDN das fotos da Shopee Brasil, a confirmar com o imageUrl da Open API (F4 do mesmo plano).
HOST_FOTO_SHOPEE = 'down-br.img.susercontent.com'
# CDN das fotos de cada loja: no disparo, a foto só segue para o transporte se vier do CDN da loja do
# próprio item (foto de CDN de outra loja faz o item sair sem foto).
HOSTS_FOTO_LOJA = {'amazon': ('m.media-amazon.com',), 'ml': ('http2.mlstatic.com',), 'shopee': (HOST_FOTO_SHOPEE,)}
# A união dos CDNs: mesma allowlist do HOSTS_FOTO do index.html.
HOSTS_FOTO = tuple(h for hosts in HOSTS_FOTO_LOJA.values() for h in hosts)
# Colunas de dados do item (as mesmas de CAMPOS no servidor.py; repetidas para não importar o servidor).
CAMPOS_ITEM = ('titulo', 'preco', 'preco_antigo', 'desconto', 'avaliacao', 'num_avaliacoes',
               'vendas', 'frete', 'cupom', 'imagem')

_LOCK = threading.Lock()   # serializa processar_slot dentro do processo (thread do agendador x rota "agora")


class ErroDisparo(Exception):
    """Pedido recusado (400 inválido, 404 não existe, 409 conflito). A mensagem nunca traz valores enviados."""
    def __init__(self, codigo, msg):
        super().__init__(msg)
        self.codigo, self.msg = codigo, msg


class ErroEnvio(Exception):
    """Falha de um transporte. `motivo` é curto e vai para envios.motivo depois de limpo."""
    def __init__(self, motivo):
        super().__init__(motivo)
        self.motivo = motivo


def _agora_iso(agora=None):
    return (agora or datetime.now()).isoformat(timespec='seconds')


# ---------------------------------------------------------------- esquema (etapa 1)
def migrar(con):
    """Cria numeros, regras e envios se PRAGMA user_version < 1. Aditiva e idempotente.

    Faz commit do que a conexão tiver pendente (como o executescript). Devolve True se migrou.
    O BEGIN IMMEDIATE e a releitura da versão impedem dois processos de migrar ao mesmo tempo.
    """
    if con.execute('PRAGMA user_version').fetchone()[0] >= VERSAO_ESQUEMA:
        return False
    if con.in_transaction:
        con.commit()
    con.execute('BEGIN IMMEDIATE')
    try:
        if con.execute('PRAGMA user_version').fetchone()[0] >= VERSAO_ESQUEMA:
            con.rollback()
            return False
        for sql in ESQUEMA_V1:
            con.execute(sql)
        con.execute(f'PRAGMA user_version = {VERSAO_ESQUEMA}')
        con.commit()
    except BaseException:
        con.rollback()
        raise
    return True


# ---------------------------------------------------------------- validação (etapa 1)
_RX_TELEFONE = re.compile(r'[0-9]{10,15}')
_RX_GRUPO = re.compile(r'[0-9]{5,25}(-[0-9]{5,25})?@g\.us')
_RX_HORARIO = re.compile(r'([01][0-9]|2[0-3]):[0-5][0-9]')


def _invalido(msg):
    return ErroDisparo(400, msg)


def _utf8_ok(v):
    """Texto que o sqlite consegue gravar: sem surrogate solto (JSON aceita "\\ud800", UTF-8 não)."""
    try:
        v.encode('utf-8')
    except UnicodeEncodeError:
        return False
    return True


def _texto(dados, campo, rotulo, minimo, maximo):
    v = dados.get(campo)
    if not isinstance(v, str) or not _utf8_ok(v):
        raise _invalido(f'{rotulo} deve ser texto')
    v = v.strip()
    if not minimo <= len(v) <= maximo:
        raise _invalido(f'{rotulo} precisa ter de {minimo} a {maximo} caracteres')
    return v


def _inteiro(dados, campo, rotulo, minimo, maximo, nulo=False):
    v = dados.get(campo)
    if v is None and nulo:
        return None
    # bool é subclasse de int no Python: true/false do JSON não vale como número
    if isinstance(v, bool) or not isinstance(v, int):
        raise _invalido(f'{rotulo} deve ser um número inteiro')
    if not minimo <= v <= maximo:
        raise _invalido(f'{rotulo} deve ficar entre {minimo} e {maximo}')
    return v


def _flag(dados, campo, rotulo):
    v = dados.get(campo)
    if isinstance(v, bool) or v not in (0, 1):
        raise _invalido(f'{rotulo} deve ser 0 ou 1')
    return v


def _lista(dados, campo, rotulo, minimo, maximo):
    v = dados.get(campo)
    if not isinstance(v, list):
        raise _invalido(f'{rotulo} deve ser uma lista')
    if not minimo <= len(v) <= maximo:
        raise _invalido(f'{rotulo} precisa ter de {minimo} a {maximo} itens')
    return v


def validar_numero(dados):
    """Confere e normaliza um número (CA1). ErroDisparo 400; a mensagem nunca repete o valor recebido."""
    if not isinstance(dados, dict):
        raise _invalido('envie um objeto JSON')
    tel = dados.get('telefone', '')
    if not isinstance(tel, str) or tel and not _RX_TELEFONE.fullmatch(tel):
        raise _invalido('telefone inválido: use só dígitos, com DDI e DDD (10 a 15), ou deixe vazio')
    grupo = dados.get('grupo_id', '')
    if not isinstance(grupo, str) or grupo and not _RX_GRUPO.fullmatch(grupo):
        raise _invalido('id do grupo inválido: deixe vazio ou use o formato 120363...@g.us')
    return {
        'nome': _texto(dados, 'nome', 'nome', 1, 80),
        'telefone': tel,
        'grupo_nome': _texto(dados, 'grupo_nome', 'nome do grupo', 1, 80),
        'grupo_id': grupo,
        'limite_diario': _inteiro(dados, 'limite_diario', 'limite diário', 1, 200),
        'ativo': _flag(dados, 'ativo', 'ativo'),
    }


def carregar_templates(con):
    """config.templates como dict nome → texto. Vazio se não existe ou está malformado."""
    try:
        r = con.execute("SELECT valor FROM config WHERE chave='templates'").fetchone()
    except sqlite3.OperationalError:   # banco sem a tabela config
        return {}
    try:
        t = json.loads(r[0]) if r and r[0] else None
    except ValueError:
        return {}
    if not isinstance(t, dict):
        return {}
    return {k: v for k, v in t.items() if isinstance(k, str) and isinstance(v, str)}


def _numero_existe(con, numero_id):
    return con.execute('SELECT 1 FROM numeros WHERE id=?', (numero_id,)).fetchone() is not None


def validar_regra(con, dados, conferir_template=True):
    """Confere e normaliza uma regra (CA2), com os limites do plano. ErroDisparo 400.

    `conferir_template=False` (atualização que não mexe no template) deixa pausar ou editar outros
    campos de uma regra cujo template foi apagado; o agendador continua pulando-a com aviso.
    """
    if not isinstance(dados, dict):
        raise _invalido('envie um objeto JSON')
    numero_id = _inteiro(dados, 'numero_id', 'número', 1, 2**63 - 1)
    if not _numero_existe(con, numero_id):
        raise _invalido('número não encontrado: cadastre o número antes da regra')

    cats = _lista(dados, 'cats', 'categorias', 1, 50)
    if not all(isinstance(c, str) and _utf8_ok(c) and 1 <= len(c) <= 100 for c in cats):
        raise _invalido('cada categoria deve ser um texto de 1 a 100 caracteres')
    if len(set(cats)) != len(cats):
        raise _invalido('categorias repetidas')

    lojas = _lista(dados, 'lojas', 'lojas', 1, len(LOJAS))
    if not all(isinstance(l, str) and l in LOJAS for l in lojas) or len(set(lojas)) != len(lojas):
        raise _invalido('lojas deve ter amazon, ml e/ou shopee, sem repetir')

    palavras = _lista(dados, 'palavras', 'palavras', 0, 20)
    if not all(isinstance(p, str) and _utf8_ok(p) and 1 <= len(p.strip()) <= 40 for p in palavras):
        raise _invalido('cada palavra deve ser um texto de 1 a 40 caracteres')
    palavras = [p.strip() for p in palavras]

    ordem = dados.get('ordem')
    if not isinstance(ordem, str) or ordem not in ORDENS:
        raise _invalido('ordem inválida (use ' + ', '.join(ORDENS) + ')')

    template = dados.get('template')
    if not isinstance(template, str) or not _utf8_ok(template):
        raise _invalido('template deve ser texto')
    if conferir_template:
        texto_tpl = carregar_templates(con).get(template)
        if texto_tpl is None:
            raise _invalido('template não encontrado em Editar templates')
        if '{LINK}' not in texto_tpl:
            raise _invalido('o template precisa ter {LINK}, para o link de afiliado ir na mensagem')

    dias = _lista(dados, 'dias', 'dias', 1, 7)
    if not all(isinstance(d, int) and not isinstance(d, bool) and 0 <= d <= 6 for d in dias) \
            or len(set(dias)) != len(dias):
        raise _invalido('dias deve ter valores de 0 (segunda) a 6 (domingo), sem repetir')

    horarios = _lista(dados, 'horarios', 'horários', 1, 48)
    if not all(isinstance(h, str) and _RX_HORARIO.fullmatch(h) for h in horarios):
        raise _invalido('cada horário deve estar no formato HH:MM, de 00:00 a 23:59')
    if len(set(horarios)) != len(horarios):
        raise _invalido('horários repetidos')

    return {
        'nome': _texto(dados, 'nome', 'nome', 1, 80),
        'numero_id': numero_id,
        'ativa': _flag(dados, 'ativa', 'ativa'),
        'cats': cats,
        'lojas': [l for l in LOJAS if l in lojas],
        'palavras': palavras,
        'desconto_min': _inteiro(dados, 'desconto_min', 'desconto mínimo', 0, 95),
        'ordem': ordem,
        'template': template,
        'com_foto': _flag(dados, 'com_foto', 'com foto'),
        'dias': sorted(dias),
        'horarios': sorted(horarios),
        'por_disparo': _inteiro(dados, 'por_disparo', 'itens por disparo', 1, 10),
        'max_por_dia': _inteiro(dados, 'max_por_dia', 'máximo por dia', 1, 200),
        'repetir_apos_dias': _inteiro(dados, 'repetir_apos_dias', 'prazo para repetir', 1, 365, nulo=True),
        'intervalo_seg': _inteiro(dados, 'intervalo_seg', 'intervalo', 30, 3600),
    }


# Valores padrão do esquema, usados quando o campo não vem na criação.
PADRAO_NUMERO = {'telefone': '', 'grupo_id': '', 'limite_diario': 40, 'ativo': 1}
PADRAO_REGRA = {'ativa': 1, 'lojas': ['amazon', 'ml'], 'palavras': [], 'desconto_min': 0,
                'ordem': 'relevancia', 'com_foto': 1, 'dias': [0, 1, 2, 3, 4, 5, 6], 'por_disparo': 1,
                'max_por_dia': 10, 'repetir_apos_dias': 7, 'intervalo_seg': 60}
CAMPOS_NUMERO = ('nome', 'telefone', 'grupo_nome', 'grupo_id', 'limite_diario', 'ativo')
CAMPOS_REGRA = ('nome', 'numero_id', 'ativa', 'cats', 'lojas', 'palavras', 'desconto_min', 'ordem',
                'template', 'com_foto', 'dias', 'horarios', 'por_disparo', 'max_por_dia',
                'repetir_apos_dias', 'intervalo_seg')
LISTAS_REGRA = ('cats', 'lojas', 'palavras', 'dias', 'horarios')


def _so_campos(dados, campos):
    """Só os campos conhecidos; os demais (id, criado_em, proximo...) são ignorados."""
    if not isinstance(dados, dict):
        raise _invalido('envie um objeto JSON')
    return {c: dados[c] for c in campos if c in dados}


# ---------------------------------------------------------------- CRUD (etapa 1)
def _numero(r):
    return {k: r[k] for k in r.keys()}


def _regra(r):
    d = {k: r[k] for k in r.keys()}
    for c in LISTAS_REGRA:
        d[c] = json.loads(d[c])
    return d


def listar_numeros(con):
    return [_numero(r) for r in con.execute('SELECT * FROM numeros ORDER BY id')]


def obter_numero(con, numero_id):
    r = con.execute('SELECT * FROM numeros WHERE id=?', (numero_id,)).fetchone()
    if not r:
        raise ErroDisparo(404, 'número não encontrado')
    return _numero(r)


def criar_numero(con, dados, agora=None):
    v = validar_numero({**PADRAO_NUMERO, **_so_campos(dados, CAMPOS_NUMERO)})
    quando = _agora_iso(agora)
    with con:
        cur = con.execute(f'INSERT INTO numeros ({",".join(CAMPOS_NUMERO)}, criado_em, atualizado_em) '
                          f'VALUES ({",".join("?" * len(CAMPOS_NUMERO))}, ?, ?)',
                          [v[c] for c in CAMPOS_NUMERO] + [quando, quando])
    return obter_numero(con, cur.lastrowid)


def atualizar_numero(con, numero_id, dados, agora=None):
    """Atualização parcial: os campos ausentes mantêm o valor atual, e o resultado é validado inteiro."""
    atual = obter_numero(con, numero_id)
    v = validar_numero({**{c: atual[c] for c in CAMPOS_NUMERO}, **_so_campos(dados, CAMPOS_NUMERO)})
    with con:
        con.execute(f'UPDATE numeros SET {", ".join(c + "=?" for c in CAMPOS_NUMERO)}, atualizado_em=? WHERE id=?',
                    [v[c] for c in CAMPOS_NUMERO] + [_agora_iso(agora), numero_id])
    return obter_numero(con, numero_id)


def excluir_numero(con, numero_id):
    """409 se alguma regra (ativa ou não) usa o número."""
    obter_numero(con, numero_id)
    with con:
        if con.execute('SELECT 1 FROM regras WHERE numero_id=? LIMIT 1', (numero_id,)).fetchone():
            raise ErroDisparo(409, 'este número é usado por uma regra: mude ou exclua a regra primeiro')
        con.execute('DELETE FROM numeros WHERE id=?', (numero_id,))


def listar_regras(con):
    return [_regra(r) for r in con.execute('SELECT * FROM regras ORDER BY id')]


def obter_regra(con, regra_id):
    r = con.execute('SELECT * FROM regras WHERE id=?', (regra_id,)).fetchone()
    if not r:
        raise ErroDisparo(404, 'regra não encontrada')
    return _regra(r)


def _valores_regra(v):
    return [json.dumps(v[c], ensure_ascii=False) if c in LISTAS_REGRA else v[c] for c in CAMPOS_REGRA]


def criar_regra(con, dados, agora=None):
    v = validar_regra(con, {**PADRAO_REGRA, **_so_campos(dados, CAMPOS_REGRA)})
    quando = _agora_iso(agora)
    with con:
        cur = con.execute(f'INSERT INTO regras ({",".join(CAMPOS_REGRA)}, criado_em, atualizado_em) '
                          f'VALUES ({",".join("?" * len(CAMPOS_REGRA))}, ?, ?)',
                          _valores_regra(v) + [quando, quando])
    return obter_regra(con, cur.lastrowid)


def atualizar_regra(con, regra_id, dados, agora=None):
    """Atualização parcial (ex.: só {"ativa": 0}). Salvar a regra limpa o aviso."""
    atual = obter_regra(con, regra_id)
    novos = _so_campos(dados, CAMPOS_REGRA)
    v = validar_regra(con, {**{c: atual[c] for c in CAMPOS_REGRA}, **novos}, conferir_template='template' in novos)
    with con:
        con.execute(f'UPDATE regras SET {", ".join(c + "=?" for c in CAMPOS_REGRA)}, aviso=\'\', atualizado_em=? '
                    'WHERE id=?', _valores_regra(v) + [_agora_iso(agora), regra_id])
    return obter_regra(con, regra_id)


def excluir_regra(con, regra_id):
    """Os envios da regra ficam no histórico."""
    obter_regra(con, regra_id)
    with con:
        con.execute('DELETE FROM regras WHERE id=?', (regra_id,))
    RECUSADOS.pop(regra_id, None)


# ---------------------------------------------------------------- mensagem (etapa 2)
# O LOJA do index.html (lá a Shopee entra no E4 do plano perfumaria-tres-lojas, com o caso de paridade).
NOMES_LOJA = {'amazon': 'Amazon', 'ml': 'Mercado Livre', 'shopee': 'Shopee'}
# String.prototype.trim do JS: WhiteSpace + LineTerminator. Inclui U+FEFF (o str.strip() não tira)
# e não inclui U+200B nem U+0085 e U+001C..U+001F (o str.strip() tira).
_ESPACOS_JS = ('\t\n\v\f\r \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008'
               '\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff')


def _js_verdadeiro(v):
    """Truthiness do JS para os valores que chegam do banco ou do JSON."""
    if v is None or v is False:
        return False
    if isinstance(v, (int, float)):
        return v == v and v != 0
    if isinstance(v, str):
        return v != ''
    return True


def _js_texto(v):
    """String(v) do JS para os tipos simples."""
    if isinstance(v, str):
        return v
    if v is None:
        return 'null'
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


class MensagemGrande(Exception):
    """A montagem passou do limite: a mensagem seria recusada de qualquer jeito (S2)."""


class _Conta:
    """Soma o tamanho do que a montagem produz e aborta assim que passa do limite (None = sem limite)."""
    def __init__(self, limite):
        self.limite, self.total = limite, 0

    def soma(self, n):
        self.total += n
        if self.limite is not None and self.total > self.limite:
            raise MensagemGrande()


def _js_substituicao(s, pos, alvo, novo, conta):
    """GetSubstitution do JS para padrão em texto (sem grupos): trata $$, $&, $` e $'."""
    saida, i = [], 0
    while i < len(novo):
        c = novo[i]
        if c == '$' and i + 1 < len(novo):
            p = novo[i + 1]
            pedaco = {'$': '$', '&': alvo, '`': None, "'": None}.get(p, False)
            if pedaco is not False:
                # o tamanho é somado antes de fatiar: "$`" repetido não chega a alocar a cópia
                n = (pos if p == '`' else len(s) - pos - len(alvo)) if pedaco is None else len(pedaco)
                conta.soma(n)
                saida.append(pedaco if pedaco is not None else (s[:pos] if p == '`' else s[pos + len(alvo):]))
                i += 2
                continue
        conta.soma(1)
        saida.append(c)
        i += 1
    return ''.join(saida)


def _js_replace_all(s, alvo, novo, limite=None):
    """String.prototype.replaceAll(alvo, novo) com alvo em texto não vazio. MensagemGrande acima do limite."""
    partes, i, conta = [], 0, _Conta(limite)
    while True:
        p = s.find(alvo, i)
        if p < 0:
            break
        conta.soma(p - i)
        partes.append(s[i:p])
        partes.append(_js_substituicao(s, p, alvo, novo, conta))
        i = p + len(alvo)
    conta.soma(len(s) - i)
    partes.append(s[i:])
    return ''.join(partes)


def montar_mensagem(item, template, limite=None):
    """Porte fiel do buildMsg do index.html (CA8). `item` no formato do /api/items: url, loja, data.

    Mesma ordem de troca dos placeholders, mesma remoção das linhas com campo vazio, mesmo
    replaceAll do JS (com $$, $& etc.) e mesmo trim. Quem mudar um dos dois muda o caso em
    testes/mensagens.test.html.

    Com `limite`, levanta MensagemGrande assim que o texto em montagem passar dele (S2): "$`" e
    "$'" nos campos multiplicam o texto a cada troca. Sem limite, é o porte puro (paridade).
    """
    d = item.get('data')
    if not isinstance(d, dict):
        d = {}
    desconto = d.get('desconto')
    vendas = d.get('vendas')
    if not _js_verdadeiro(vendas):
        nav = d.get('num_avaliacoes')
        vendas = _js_texto(nav) + ' avaliações' if _js_verdadeiro(nav) else ''
    if not _js_verdadeiro(vendas):
        vendas = d.get('avaliacao')
    if not _js_verdadeiro(vendas):
        vendas = ''
    mapa = [
        ('{LINK}', item.get('url')),
        ('{LOJA}', NOMES_LOJA.get(item.get('loja'), '')),
        ('{TITULO_PRODUTO}', d.get('titulo') if _js_verdadeiro(d.get('titulo')) else ''),
        ('{PRECO_PRODUTO}', d.get('preco') if _js_verdadeiro(d.get('preco')) else ''),
        ('{PRECO_ANTIGO}', d.get('preco_antigo') if _js_verdadeiro(d.get('preco_antigo')) else ''),
        ('{DESCONTO_PRODUTO}', _js_texto(desconto).replace('-', '', 1) if _js_verdadeiro(desconto) else ''),
        ('{NUMERO_VENDAS}', vendas),
        ('{FRETE}', d.get('frete') if _js_verdadeiro(d.get('frete')) else ''),
        ('{CUPOM}', d.get('cupom') if _js_verdadeiro(d.get('cupom')) else ''),
    ]
    # linhas cujo campo está vazio somem da mensagem
    linhas = [l for l in template.split('\n') if not any(k in l and not _js_verdadeiro(v) for k, v in mapa)]
    s = re.sub(r'\n{3,}', '\n\n', '\n'.join(linhas))
    for k, v in mapa:
        s = _js_replace_all(s, k, _js_texto(v), limite)
    return s.strip(_ESPACOS_JS)


# Detecção de links (CA4, S1): conservadora de propósito. Na dúvida, a mensagem não sai.
# Tudo é feito por token, em tempo linear (S2): nada de regex com retrocesso sobre o texto todo.
# Depois do NFKC: pontos parecidos e o ponto médio (U+00B7, U+2027, U+30FB, U+FF65) viram ".".
_PONTOS = str.maketrans({'\u3002': '.', '\uff0e': '.', '\uff61': '.', '\u2024': '.', '\ufe52': '.',
                         '\u00b7': '.', '\u2027': '.', '\u30fb': '.', '\uff65': '.'})
_BORDA = '_*~.,;:!?()[]{}<>"\'`\u00ab\u00bb\u201c\u201d\u2018\u2019'
_CHARS_ESQUEMA = frozenset('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789+.-')
MAX_MENSAGEM = 4000   # mensagem maior que isso nem é analisada: é pulada (S2)
# Folga na montagem: um texto intermediário acima disso não volta a caber em MAX_MENSAGEM na prática.
LIMITE_MONTAGEM = 2 * MAX_MENSAGEM


def _tem_dominio(token):
    """True se o token tem algo como rotulo.tld: rótulos Unicode e TLD de 2+ letras, sem lista de TLDs.

    Pega "promo.pt", "andro.id", "promoção.com", "x@golpe.com" e "golpe.com/p". Também pega "Node.js"
    e "i.phone" (falso positivo aceito). Não pega "R$ 1.249,90", "4.8 de 5" nem "Wi-Fi 6".
    """
    trecho = []
    for c in token + ' ':
        # "_" separa: rótulo de domínio não tem "_" ("#_golpe.com_#"); marcas (Mn/Mc) fazem parte ("कॉम")
        if c.isalnum() or c in '-.' or unicodedata.category(c) in ('Mn', 'Mc'):
            trecho.append(c)
            continue
        if trecho:
            rotulos = ''.join(trecho).split('.')
            seguidos = 0   # rótulos só de dígitos em sequência: 4 é um IP sem esquema ("10.0.0.1/x")
            for j, rotulo in enumerate(rotulos):
                seguidos = seguidos + 1 if rotulo.isdigit() else 0
                if seguidos >= 4:
                    return True
                if j == 0:
                    continue
                tld, antes = rotulo.rstrip('-'), rotulos[j - 1].lstrip('-')
                if len(tld) >= 2 and tld[0].isalpha() and antes and \
                        all(ch.isalpha() or unicodedata.category(ch) in ('Mn', 'Mc') for ch in tld):
                    return True
            trecho = []
    return False


def _inicio_do_esquema(token):
    """Posição onde começa o primeiro "xx://" do token, ou -1. Linear: find + recuo, sem regex."""
    p = token.find('://')
    if p < 0:
        return -1
    i = p
    while i > 0 and token[i - 1] in _CHARS_ESQUEMA:
        i -= 1
    return i


def urls_da_mensagem(texto):
    """Candidatas a link num texto: cada token com esquema (xx://), com www. ou com domínio.

    O texto passa por NFKC; pontos parecidos (U+3002, U+FF0E, ponto médio...) viram "."; espaços
    Unicode separam tokens; invisíveis (Cf) são lidos das duas formas, como corte e como nada; e a
    pontuação e as marcas do WhatsApp (_ * ~) saem das bordas. Num token com esquema no
    meio ("aqui:https://..."), a candidata começa no esquema, e o que vem antes é conferido à parte.
    """
    texto = unicodedata.normalize('NFKC', texto).translate(_PONTOS)   # "golpe⒈com", letras largas...
    separado = ''.join(' ' if unicodedata.category(c) in ('Cf', 'Cc', 'Zs', 'Zl', 'Zp') else c for c in texto)
    achadas = _candidatas(separado)
    if separado != texto:
        # invisíveis (U+200B, ZWJ U+200D...): o WhatsApp pode tratá-los como corte ou como nada, então as
        # duas leituras são conferidas; na segunda, os Cf somem e os demais continuam separando
        juntado = ''.join('' if unicodedata.category(c) == 'Cf' else
                          ' ' if unicodedata.category(c) in ('Cc', 'Zs', 'Zl', 'Zp') else c for c in texto)
        vistas = set(achadas)
        achadas += [u for u in _candidatas(juntado) if u not in vistas]
    return achadas


def _candidatas(texto):
    achadas = []
    for token in texto.split():
        token = token.strip(_BORDA)
        if not token:
            continue
        i = _inicio_do_esquema(token)
        if i >= 0:
            antes = token[:i].strip(_BORDA)
            if antes and _tem_dominio(antes):
                achadas.append(antes)
            achadas.append(token[i:])
        elif token.lower().startswith('www.') or _tem_dominio(token):
            achadas.append(token)
    return achadas


def mensagem_so_com_afiliado(texto, eh_afiliado, url_item=None):
    """CA4: toda candidata a link tem que ser de afiliado e, com `url_item`, ser o link do próprio item.

    Assim nem um link de afiliado de outro produto, escrito no template ou no título, passa.
    """
    if len(texto) > MAX_MENSAGEM:
        return False
    urls = urls_da_mensagem(texto)
    return bool(urls) and all(eh_afiliado(u) and (url_item is None or u == url_item) for u in urls)


# ---------------------------------------------------------------- seleção (etapa 2)
def _host(url):
    try:
        return urllib.parse.urlsplit(url).hostname or ''
    except ValueError:
        return ''


def link_da_loja_ok(loja, url, eh_afiliado):
    """Afiliado e da loja do item: ML só sai com meli.la, Amazon só com www.amazon.com.br + tag e Shopee
    só com o link curto de afiliado (HOSTS_AFILIADO_SHOPEE). Loja desconhecida nunca sai."""
    if not eh_afiliado(url):
        return False
    return _host(url) in HOSTS_LINK_LOJA.get(loja, ())


def imagem_permitida(url, loja=None):
    """https, sem usuário nem porta, num CDN de foto. Com `loja`, só o CDN dessa loja (loja desconhecida: nenhum);
    sem `loja`, qualquer um do HOSTS_FOTO."""
    if not isinstance(url, str) or not url:
        return False
    try:
        p = urllib.parse.urlsplit(url)
    except ValueError:
        return False
    hosts = HOSTS_FOTO if loja is None else HOSTS_FOTO_LOJA.get(loja, ())
    return p.scheme == 'https' and p.netloc.lower() == (p.hostname or '') and p.hostname in hosts


def _sem_acento(s):
    return ''.join(c for c in unicodedata.normalize('NFKD', s) if not unicodedata.combining(c)).casefold()


def pct(desconto):
    """Desconto em %: só os dígitos, como o pct do index.html ("-34%" vira 34)."""
    so_digitos = re.sub(r'\D', '', str(desconto or ''), flags=re.A)
    return int(so_digitos) if so_digitos else 0


def preco_num(preco):
    """Preço em número, como o num do index.html ("R$ 1.899,00" vira 1899.0). Vazio vira 0."""
    s = re.sub(r'[^\d,]', '', str(preco or ''), flags=re.A).replace(',', '.', 1)
    m = re.match(r'\d+(?:\.\d*)?|\.\d+', s, re.A)   # o prefixo que o parseFloat aceita
    return float(m.group(0)) if m else 0.0


def contagem(texto):
    """'Mais de 1 mil compras' → 1000; 'Mais de 1000 produtos vendidos' → 1000; '27,6 mil' → 27600; '(135)' → 135."""
    m = re.search(r'(\d[\d.,]*)\s*(mil\b)?', str(texto or ''), re.I | re.A)
    if not m:
        return 0
    numero = m.group(1).rstrip('.,')
    if m.group(2):
        decimal = numero.replace('.', '').replace(',', '.') if ',' in numero else numero
        try:
            return int(round(float(decimal) * 1000))
        except ValueError:   # "1.2.3 mil": sem decimal claro, vale só os dígitos
            return int(re.sub(r'\D', '', numero, flags=re.A)) * 1000
    return int(re.sub(r'\D', '', numero, flags=re.A) or 0)


def nota(texto):
    """'4,7 de 5 estrelas' ou '4.7 de 5' → 4.7."""
    m = re.search(r'\d+(?:[.,]\d+)?', str(texto or ''), re.A)
    return float(m.group(0).replace(',', '.')) if m else 0.0


def _item(r):
    """Linha de items no formato do /api/items, mais posicao e criado_em para a ordenação."""
    return {'id': r['id'], 'loja': r['loja'], 'item_id': r['item_id'], 'cat': r['cat'], 'busca': r['busca'],
            'url': r['url'], 'data': {c: r[c] for c in CAMPOS_ITEM},
            'posicao': r['posicao'] or 0, 'criado_em': r['criado_em'] or ''}


def bloqueados(con, numero_id, repetir_apos_dias, agora):
    """item_pk já mandados (ou na fila) para o número no prazo (CA5). NULL = para sempre.

    O prazo conta dias de calendário, sem depender do segundo do tick: com N=7, o item enviado
    numa segunda volta a valer na segunda seguinte; com N=1, só fica bloqueado no mesmo dia.
    """
    sql = f'SELECT DISTINCT item_pk FROM envios WHERE numero_id=? AND status IN ({",".join("?" * len(STATUS_OCUPA))})'
    args = [numero_id, *STATUS_OCUPA]
    if repetir_apos_dias is not None:
        sql += ' AND criado_em >= ?'
        args.append((agora.date() - timedelta(days=repetir_apos_dias - 1)).isoformat())
    return {r[0] for r in con.execute(sql, args)}


def elegiveis(con, regra, agora, eh_afiliado, info=None):
    """Itens que a regra pode mandar agora (CA4 e CA5), ainda sem ordem.

    Com `info` (dict), conta em info['casam'] os itens que passam nos filtros antes da regra de
    repetição: separa "nada casa com os filtros" de "tudo já foi enviado no prazo".
    """
    info = {} if info is None else info
    info['casam'] = 0
    cats, lojas = regra['cats'], regra['lojas']
    if not cats or not lojas:
        return []
    rows = con.execute(
        f"SELECT * FROM items WHERE tem_dados=1 AND titulo!='' AND preco!='' "
        f"AND cat IN ({','.join('?' * len(cats))}) AND loja IN ({','.join('?' * len(lojas))})",
        [*cats, *lojas]).fetchall()
    fora = bloqueados(con, regra['numero_id'], regra['repetir_apos_dias'], agora)
    palavras = [_sem_acento(p) for p in regra.get('palavras') or []]
    saida = []
    for r in rows:
        if not link_da_loja_ok(r['loja'], r['url'], eh_afiliado):
            continue
        if pct(r['desconto']) < regra['desconto_min']:
            continue
        if palavras:   # basta uma das palavras no título, sem diferenciar maiúsculas e acentos
            titulo = _sem_acento(r['titulo'] or '')
            if not any(p in titulo for p in palavras):
                continue
        info['casam'] += 1
        if r['id'] in fora:
            continue
        saida.append(_item(r))
    return saida


def ordenar(itens, ordem, rng=None):
    """As sete ordens do CA3. Desempate por posicao (ordem de coleta)."""
    base = sorted(itens, key=lambda it: it['posicao'])
    d = lambda it: it['data']
    if ordem == 'relevancia':
        return sorted(base, key=lambda it: (-contagem(d(it)['vendas']), -contagem(d(it)['num_avaliacoes']),
                                            -nota(d(it)['avaliacao'])))
    if ordem == 'desconto':
        return sorted(base, key=lambda it: -pct(d(it)['desconto']))
    if ordem == 'menor_preco':
        return sorted(base, key=lambda it: (preco_num(d(it)['preco']) <= 0, preco_num(d(it)['preco'])))
    if ordem == 'maior_preco':
        return sorted(base, key=lambda it: (preco_num(d(it)['preco']) <= 0, -preco_num(d(it)['preco'])))
    if ordem == 'cupom':
        return sorted(base, key=lambda it: (not d(it)['cupom'], -pct(d(it)['desconto'])))
    if ordem == 'recentes':
        # criado_em, e não atualizado_em: migrar_categorias.py e classificar_lista.py regravam o
        # atualizado_em de milhares de itens antigos ao reclassificar (R4)
        return sorted(base, key=lambda it: (it['criado_em'], it['id']), reverse=True)
    if ordem == 'aleatoria':
        (rng or random.Random()).shuffle(base)
        return base
    raise ValueError('ordem desconhecida')


def _escolher(con, regra, texto_tpl, agora, eh_afiliado, quantos, rng=None):
    """Os `quantos` primeiros itens elegíveis cuja mensagem só tem o link de afiliado do item.

    Devolve (escolhidos, info). info['recusados'] conta as mensagens descartadas pela conferência
    de links ou pelo tamanho; info['casam'] e info['elegiveis'] vêm da seleção (para o aviso).
    """
    saida, recusados, info = [], 0, {}
    lista = elegiveis(con, regra, agora, eh_afiliado, info)
    info['elegiveis'] = len(lista)
    for it in ordenar(lista, regra['ordem'], rng):
        if len(saida) >= quantos:
            break
        try:
            msg = montar_mensagem(it, texto_tpl, LIMITE_MONTAGEM)
        except MensagemGrande:
            recusados += 1
            continue
        if it['url'] not in msg or not mensagem_so_com_afiliado(msg, eh_afiliado, it['url']):
            recusados += 1
            continue
        img = it['data']['imagem'] if regra['com_foto'] and imagem_permitida(it['data']['imagem'], it['loja']) else ''
        saida.append((it, msg, img))
    info['recusados'] = recusados
    return saida, info


def previa(con, regra, n, agora, eh_afiliado, rng=None, info=None):
    """Próximos itens de uma regra ainda não salva, sem gravar nada (CA10).

    Com `info` (dict), devolve nele 'recusados': mensagens descartadas pela conferência de links.
    """
    if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= MAX_PREVIA:
        raise _invalido(f'n deve ser um número inteiro de 1 a {MAX_PREVIA}')
    v = validar_regra(con, {**PADRAO_REGRA, **_so_campos(regra, CAMPOS_REGRA)})
    texto_tpl = carregar_templates(con)[v['template']]
    escolhidos, dados = _escolher(con, v, texto_tpl, agora, eh_afiliado, n, rng)
    if info is not None:
        info['recusados'] = dados['recusados']
    return [{'item_pk': it['id'], 'loja': it['loja'], 'titulo': it['data']['titulo'], 'mensagem': msg, 'imagem': img}
            for it, msg, img in escolhidos]


# ---------------------------------------------------------------- histórico e fila (CA9, CA10)
def _envio(r):
    return {k: r[k] for k in r.keys()}


def obter_envio(con, envio_id):
    r = con.execute('SELECT * FROM envios WHERE id=?', (envio_id,)).fetchone()
    if not r:
        raise ErroDisparo(404, 'envio não encontrado')
    return _envio(r)


def listar_fila(con):
    """Envios pendente e incerto, do mais antigo para o mais novo (a fila do transporte manual)."""
    return [_envio(r) for r in con.execute(
        "SELECT * FROM envios WHERE status IN ('pendente','incerto') ORDER BY criado_em, id")]


def listar_envios(con, desde=None, status=None, limite=LIMITE_HISTORICO):
    """Histórico do mais novo para o mais antigo. `desde` = AAAA-MM-DD; `status` opcional."""
    sql, args = 'SELECT * FROM envios WHERE 1=1', []
    if desde not in (None, ''):
        if not isinstance(desde, str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', desde):
            raise _invalido('desde deve estar no formato AAAA-MM-DD')
        try:
            date.fromisoformat(desde)
        except ValueError:
            raise _invalido('desde deve ser uma data válida')
        sql += ' AND criado_em >= ?'; args.append(desde)
    if status not in (None, ''):
        if status not in STATUS:
            raise _invalido('status inválido')
        sql += ' AND status = ?'; args.append(status)
    sql += ' ORDER BY criado_em DESC, id DESC LIMIT ?'
    args.append(limite)
    return [_envio(r) for r in con.execute(sql, args)]


# De onde cada marcação manual pode partir (PATCH envios/<id>).
TRANSICOES = {'enviado': ('pendente', 'incerto'), 'pulado': ('pendente', 'incerto', 'erro')}


def marcar_envio(con, envio_id, status, agora=None):
    """Fila manual: "Enviado" ou "Pular". 409 fora de pendente/incerto (erro só vai para pulado)."""
    if not isinstance(status, str) or status not in TRANSICOES:
        raise _invalido('status deve ser enviado ou pulado')
    with con:
        obter_envio(con, envio_id)
        cur = con.execute(
            f'UPDATE envios SET status=?, enviado_em=CASE WHEN ?=\'enviado\' THEN ? ELSE enviado_em END '
            f'WHERE id=? AND status IN ({",".join("?" * len(TRANSICOES[status]))})',
            [status, status, _agora_iso(agora), envio_id, *TRANSICOES[status]])
        if cur.rowcount != 1:
            raise ErroDisparo(409, 'este envio não pode mais ser marcado assim')
    return obter_envio(con, envio_id)


# ---------------------------------------------------------------- transportes (etapa 3)
class TransporteManual:
    """O envio fica `pendente` na fila da tela; o dono copia, cola e marca como enviado."""
    nome = 'manual'
    automatico = False

    def enviar(self, destino, texto, imagem_url):
        return None


class TransporteFalso:
    """Só para teste (ACHADINHOS_TRANSPORTE=falso). Grava uma linha JSON por envio no arquivo indicado.

    Não grava telefone nem id do grupo: só o nome do grupo, o texto e a imagem.
    """
    nome = 'falso'
    automatico = True

    def __init__(self, arquivo_jsonl, falhar=False):
        self.arquivo, self.falhar = arquivo_jsonl, falhar
        self._lock = threading.Lock()

    def enviar(self, destino, texto, imagem_url):
        if self.falhar:
            raise ErroEnvio('falha simulada do transporte falso')
        linha = json.dumps({'grupo_nome': destino.get('grupo_nome', ''), 'texto': texto,
                            'imagem_url': imagem_url}, ensure_ascii=False)
        with self._lock, open(self.arquivo, 'a', encoding='utf-8') as f:
            f.write(linha + '\n')


def transporte_do_ambiente(env=None):
    """Manual, salvo ACHADINHOS_TRANSPORTE=falso com ACHADINHOS_TRANSPORTE_ARQUIVO. Nunca por rota."""
    env = os.environ if env is None else env
    tipo = env.get('ACHADINHOS_TRANSPORTE') or 'manual'
    if tipo == 'manual':
        return TransporteManual()
    if tipo == 'falso':
        arquivo = env.get('ACHADINHOS_TRANSPORTE_ARQUIVO')
        if not arquivo:
            raise ValueError('ACHADINHOS_TRANSPORTE=falso exige ACHADINHOS_TRANSPORTE_ARQUIVO')
        return TransporteFalso(arquivo)
    raise ValueError('ACHADINHOS_TRANSPORTE deve ser manual ou falso')


_RX_DIGITOS_LONGOS = re.compile(r'\+?\d[\d\s().\-]{6,}\d')
_RX_ID_GRUPO = re.compile(r'\S*@g\.us', re.I)


def motivo_seguro(erro, destino):
    """Texto curto para envios.motivo, sem telefone nem id do grupo.

    De ErroEnvio vem o motivo (limpo); de qualquer outra exceção, só o nome do tipo, porque a
    mensagem de uma biblioteca pode trazer o destino.
    """
    if not isinstance(erro, ErroEnvio):
        return type(erro).__name__
    m = str(erro.motivo or '')[:200]
    for v in (destino.get('telefone'), destino.get('grupo_id')):
        if v:
            m = m.replace(v, '…')
    m = _RX_ID_GRUPO.sub('…', m)
    m = _RX_DIGITOS_LONGOS.sub(lambda x: '…' if len(re.sub(r'\D', '', x.group(0))) >= 8 else x.group(0), m)
    return m or 'falha no envio'


# ---------------------------------------------------------------- processamento (etapa 3)
def _hoje(agora):
    return agora.date().isoformat()


def _ocupados_no_dia(con, coluna, valor, agora):
    amanha = (agora.date() + timedelta(days=1)).isoformat()
    return con.execute(
        f'SELECT COUNT(*) FROM envios WHERE {coluna}=? AND criado_em >= ? AND criado_em < ? '
        f'AND status IN ({",".join("?" * len(STATUS_OCUPA))})',
        [valor, _hoje(agora), amanha, *STATUS_OCUPA]).fetchone()[0]


AVISO_FILTROS = 'Nenhum item casa com os filtros desta regra (categorias, loja, palavras, desconto).'
AVISO_REPETICAO = 'Todos os itens elegíveis já foram enviados no prazo de repetição.'
AVISO_LINK = ('Nenhuma mensagem saiu: o template ou os títulos têm link que não é o de afiliado do item. '
              'Confira o template.')
# Mensagens recusadas pela conferência de links no último processamento de cada regra (regra_id → n).
# Só em memória, neste processo (agendador e rotas): é uma dica para a tela; zera ao reiniciar.
RECUSADOS = {}


def _avisar(con, regra_id, aviso):
    con.execute('UPDATE regras SET aviso=? WHERE id=? AND aviso!=?', (aviso, regra_id, aviso))


def processar_slot(con, regra, slot, agora, transporte, eh_afiliado, rng=None, so_ativa=False):
    """Cria os envios de um horário da regra e os entrega ao transporte. Devolve a lista de envios.

    Serializado pelo _LOCK e feito em BEGIN IMMEDIATE: a thread do agendador e a rota "agora"
    (e outro processo) não criam envio duplicado. Slot que já tem envio não é reprocessado (CA7).
    Respeita por_disparo, max_por_dia e limite_diario (CA6), repetição (CA5) e afiliado (CA4).
    `so_ativa` (o tick usa) ignora a regra pausada entre a listagem e o processamento.
    """
    regra_id = regra['id']
    criados = []
    with _LOCK:
        con.execute('BEGIN IMMEDIATE')
        try:
            r = con.execute('SELECT * FROM regras WHERE id=?', (regra_id,)).fetchone()
            if r is None or so_ativa and not r['ativa'] or con.execute('SELECT 1 FROM envios WHERE regra_id=? AND slot=? LIMIT 1',
                                        (regra_id, slot)).fetchone():
                con.rollback()
                return []
            regra = _regra(r)
            numero = con.execute('SELECT * FROM numeros WHERE id=?', (regra['numero_id'],)).fetchone()
            if numero is None or not numero['ativo']:
                _avisar(con, regra_id, 'O número desta regra não existe mais ou está desativado.')
                con.commit()
                return []
            texto_tpl = carregar_templates(con).get(regra['template'])
            if texto_tpl is None or '{LINK}' not in texto_tpl:
                _avisar(con, regra_id, f'O template "{regra["template"][:80]}" não existe mais ou não tem '
                                       '{LINK}. Escolha outro template na regra.')
                con.commit()
                return []
            _avisar(con, regra_id, '')
            vagas = min(regra['por_disparo'],
                        regra['max_por_dia'] - _ocupados_no_dia(con, 'regra_id', regra_id, agora),
                        numero['limite_diario'] - _ocupados_no_dia(con, 'numero_id', numero['id'], agora))
            escolhidos = []
            if vagas > 0:   # limite do dia atingido é o normal: sem aviso
                escolhidos, info = _escolher(con, regra, texto_tpl, agora, eh_afiliado, vagas, rng)
                RECUSADOS[regra_id] = info['recusados']
                if info['recusados']:
                    log.info('disparo: %d mensagem(ns) recusada(s) por link fora do afiliado do item',
                             info['recusados'])
                if not escolhidos:
                    _avisar(con, regra_id, AVISO_FILTROS if not info['casam'] else
                            AVISO_REPETICAO if not info['elegiveis'] else AVISO_LINK)
            status = 'enviando' if transporte.automatico else 'pendente'
            for it, msg, img in escolhidos:
                cur = con.execute(
                    'INSERT INTO envios (regra_id, numero_id, item_pk, slot, status, mensagem, imagem, titulo, '
                    'transporte, criado_em) VALUES (?,?,?,?,?,?,?,?,?,?)',
                    (regra_id, numero['id'], it['id'], slot, status, msg, img, it['data']['titulo'] or '',
                     transporte.nome, _agora_iso(agora)))
                criados.append((cur.lastrowid, msg, img))
            con.commit()
        except BaseException:
            con.rollback()
            raise
        if transporte.automatico:
            destino = {'telefone': numero['telefone'], 'grupo_id': numero['grupo_id'],
                       'grupo_nome': numero['grupo_nome']}
            for envio_id, msg, img in criados:
                try:
                    transporte.enviar(destino, msg, img or None)
                    novo, motivo = 'enviado', ''
                except Exception as e:   # noqa: BLE001 — falha do transporte vira status, nunca derruba o tick
                    novo, motivo = 'erro', motivo_seguro(e, destino)
                with con:
                    con.execute("UPDATE envios SET status=?, motivo=?, enviado_em=? WHERE id=? AND status='enviando'",
                                (novo, motivo, _agora_iso(datetime.now()) if novo == 'enviado' else None, envio_id))
        return [obter_envio(con, envio_id) for envio_id, _, _ in criados]


def slot_agora(agora):
    return 'agora ' + _agora_iso(agora)


def disparar_agora(con, regra_id, agora, transporte, eh_afiliado, rng=None):
    """"Disparar agora" (CA11): processa a regra na hora, fora dos dias e horários dela, mas com os
    mesmos filtros, limites e regra de repetição. Vale também para regra pausada (é um pedido explícito).
    """
    regra = obter_regra(con, regra_id)
    return processar_slot(con, regra, slot_agora(agora), agora, transporte, eh_afiliado, rng)


def slots_devidos(regra, agora):
    """Horários de hoje da regra dentro da janela agora-10min..agora (CA6), como 'AAAA-MM-DDTHH:MM'."""
    if agora.weekday() not in regra['dias']:
        return []
    saida = []
    for h in regra['horarios']:
        quando = datetime.combine(agora.date(), datetime.strptime(h, '%H:%M').time())
        if agora - TOLERANCIA <= quando <= agora:
            saida.append(quando.strftime('%Y-%m-%dT%H:%M'))
    return saida


def expirar_pendentes(con, agora):
    """Pendentes de dias anteriores viram expirado (não bloqueiam repetição). Não apaga nada."""
    with con:
        return con.execute("UPDATE envios SET status='expirado' WHERE status='pendente' AND criado_em < ?",
                           (_hoje(agora),)).rowcount


def marcar_incertos(con):
    """No início do agendador: o que ficou em enviando (servidor caiu no meio) vira incerto e não é reenviado."""
    with con:
        return con.execute("UPDATE envios SET status='incerto' WHERE status='enviando'").rowcount


def tick(conectar, agora, transporte, eh_afiliado, rng=None):
    """Uma passada do agendador. Devolve só contagens: {'criados', 'expirados', 'erros': [tipos]}."""
    con = conectar()
    try:
        res = {'criados': 0, 'expirados': expirar_pendentes(con, agora), 'erros': []}
        regras = [_regra(r) for r in con.execute(
            'SELECT r.* FROM regras r JOIN numeros n ON n.id = r.numero_id WHERE r.ativa=1 AND n.ativo=1 ORDER BY r.id')]
        for regra in regras:
            for slot in slots_devidos(regra, agora):
                try:
                    res['criados'] += len(processar_slot(con, regra, slot, agora, transporte, eh_afiliado, rng,
                                                              so_ativa=True))
                except Exception as e:   # noqa: BLE001 — uma regra com problema não para as outras
                    res['erros'].append(type(e).__name__)
        return res
    finally:
        con.close()


class Agendador(threading.Thread):
    """Thread daemon que chama o tick a cada `intervalo` segundos. Erro é logado só pelo tipo."""

    def __init__(self, conectar, eh_afiliado, transporte, intervalo=30, relogio=datetime.now):
        super().__init__(name='agendador-disparo', daemon=True)
        self.conectar, self.eh_afiliado, self.transporte = conectar, eh_afiliado, transporte
        self.intervalo, self.relogio = intervalo, relogio
        self.ultimo_tick = None
        self.ticks = 0
        self._parar = threading.Event()

    def parar(self):
        self._parar.set()

    def estado(self):
        return {'agendador': 'ligado' if self.is_alive() and not self._parar.is_set() else 'desligado',
                'transporte': self.transporte.nome, 'ultimo_tick': self.ultimo_tick}

    def run(self):
        try:
            con = self.conectar()
            try:
                n = marcar_incertos(con)
            finally:
                con.close()
            if n:
                log.warning('disparo: %d envio(s) interrompido(s) marcado(s) como incerto', n)
        except Exception as e:   # noqa: BLE001
            log.warning('disparo: falha ao marcar incertos (%s)', type(e).__name__)
        while not self._parar.is_set():
            agora = self.relogio()
            try:
                res = tick(self.conectar, agora, self.transporte, self.eh_afiliado)
                if res['criados'] or res['expirados']:
                    log.info('disparo: %d envio(s) criado(s), %d expirado(s)', res['criados'], res['expirados'])
                for tipo in res['erros']:
                    log.warning('disparo: falha numa regra (%s)', tipo)
            except Exception as e:   # noqa: BLE001
                log.warning('disparo: falha no tick (%s)', type(e).__name__)
            self.ultimo_tick = _agora_iso(agora)
            self.ticks += 1
            self._parar.wait(self.intervalo)


# ---------------------------------------------------------------- rotas /api/disparo/* (etapa 4)
PREFIXO = '/api/disparo/'
PREVIA_PADRAO = 5
_ID = r'([1-9][0-9]{0,17})'   # cabe no INTEGER do sqlite; zero à esquerda e não-dígito dão 404


def agendador_ligado(env=None):
    """ACHADINHOS_DISPARO=0 desliga o agendador; qualquer outro valor (ou ausente) liga."""
    env = os.environ if env is None else env
    return (env.get('ACHADINHOS_DISPARO') or '1').strip() != '0'


def intervalo_do_ambiente(env=None):
    """ACHADINHOS_TICK_SEG (segundos entre ticks), de 0,1 a 3600. Padrão 30."""
    env = os.environ if env is None else env
    bruto = env.get('ACHADINHOS_TICK_SEG') or '30'
    try:
        v = float(bruto)
    except ValueError:
        raise ValueError('ACHADINHOS_TICK_SEG deve ser um número de segundos') from None
    if not 0.1 <= v <= 3600:
        raise ValueError('ACHADINHOS_TICK_SEG deve ficar entre 0.1 e 3600')
    return v


def proximo_horario(regra, agora, numero_ativo=True):
    """Próximo horário da regra a partir de agora, como 'AAAA-MM-DDTHH:MM'.

    None se a regra está pausada ou se o número dela está desativado (o tick a ignora).
    """
    if not regra.get('ativa') or not numero_ativo:
        return None
    for d in range(8):
        dia = agora.date() + timedelta(days=d)
        if dia.weekday() not in regra['dias']:
            continue
        for h in sorted(regra['horarios']):
            quando = datetime.combine(dia, datetime.strptime(h, '%H:%M').time())
            if quando >= agora:
                return quando.isoformat(timespec='minutes')
    return None


def _com_proximo(con, regra, agora):
    n = con.execute('SELECT ativo FROM numeros WHERE id=?', (regra['numero_id'],)).fetchone()
    return {**regra, 'proximo': proximo_horario(regra, agora, bool(n and n[0])),
            'recusados': RECUSADOS.get(regra['id'], 0)}


def rota(con, metodo, caminho, query, corpo, eh_afiliado, transporte, agendador=None, agora=None, rng=None):
    """Despacha /api/disparo/<resto>. Devolve o objeto da resposta (200) ou levanta ErroDisparo.

    `caminho` é o cru (sem query); `query` é um dict; `corpo` é o JSON já lido (None em GET e DELETE).
    Os ids vão só no caminho; telefone e grupo_id trafegam só no corpo.
    """
    if not isinstance(caminho, str) or not caminho.startswith(PREFIXO):
        raise ErroDisparo(404, 'rota não encontrada')
    resto = caminho[len(PREFIXO):]
    agora = agora or datetime.now()
    query = query or {}

    def aceita(*metodos):
        if metodo not in metodos:
            raise ErroDisparo(405, 'método não permitido nesta rota')

    if resto == 'numeros':
        aceita('GET', 'POST')
        return listar_numeros(con) if metodo == 'GET' else criar_numero(con, corpo, agora)
    m = re.fullmatch('numeros/' + _ID, resto)
    if m:
        aceita('PUT', 'DELETE')
        if metodo == 'PUT':
            return atualizar_numero(con, int(m.group(1)), corpo, agora)
        excluir_numero(con, int(m.group(1)))
        return {'ok': True}
    if resto == 'regras':
        aceita('GET', 'POST')
        if metodo == 'GET':
            return [_com_proximo(con, r, agora) for r in listar_regras(con)]
        return _com_proximo(con, criar_regra(con, corpo, agora), agora)
    m = re.fullmatch('regras/' + _ID, resto)
    if m:
        aceita('PUT', 'DELETE')
        if metodo == 'PUT':
            return _com_proximo(con, atualizar_regra(con, int(m.group(1)), corpo, agora), agora)
        excluir_regra(con, int(m.group(1)))
        return {'ok': True}
    m = re.fullmatch('regras/' + _ID + '/agora', resto)
    if m:
        aceita('POST')
        envios = disparar_agora(con, int(m.group(1)), agora, transporte, eh_afiliado, rng)
        return {'criados': len(envios), 'envios': envios}
    if resto == 'previa':
        aceita('POST')
        if not isinstance(corpo, dict):
            raise _invalido('envie um objeto JSON')
        info = {}
        itens = previa(con, corpo, corpo.get('n', PREVIA_PADRAO), agora, eh_afiliado, rng, info)
        # a tela atual lê uma lista; com "com_info": true, vem também a contagem de recusados
        return {'itens': itens, 'recusados': info['recusados']} if corpo.get('com_info') is True else itens
    if resto == 'fila':
        aceita('GET')
        return listar_fila(con)
    m = re.fullmatch('envios/' + _ID, resto)
    if m:
        aceita('PATCH')
        if not isinstance(corpo, dict):
            raise _invalido('envie um objeto JSON')
        return marcar_envio(con, int(m.group(1)), corpo.get('status'), agora)
    if resto == 'envios':
        aceita('GET')
        return listar_envios(con, query.get('desde'), query.get('status'))
    if resto == 'status':
        aceita('GET')
        if agendador is not None:
            return agendador.estado()
        return {'agendador': 'desligado', 'transporte': transporte.nome, 'ultimo_tick': None}
    raise ErroDisparo(404, 'rota não encontrada')
