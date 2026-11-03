#!/usr/bin/env python3
"""Testes do disparo.py (docs/produto/planos/disparo-automatico.md, etapas 1, 2 e 3).

Uso:  python3 testes/test_disparo.py -v

Cada teste usa um banco novo num diretório temporário (o esquema do servidor.py mais o
disparo.migrar). Nenhum teste toca o achadinhos.db real, o servidor em 8765, a rede ou o
WhatsApp: o relógio é injetado e os transportes são o manual, o falso e falsos locais.
Só biblioteca padrão.
"""
import atexit
import contextlib
import json
import logging
import os
import random
import re
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
import tracemalloc
import unittest
from datetime import datetime, timedelta
from unittest import mock

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_REAL = os.path.realpath(os.path.join(RAIZ, 'achadinhos.db'))
TMP = tempfile.mkdtemp(prefix='achadinhos-disparo-')
atexit.register(shutil.rmtree, TMP, ignore_errors=True)

# Antes do import: o servidor lê ACHADINHOS_DB ao carregar, e qualquer saída para a rede bate num proxy morto.
os.environ['ACHADINHOS_DB'] = os.path.join(TMP, 'import.db')
for _v in ('http_proxy', 'https_proxy', 'ftp_proxy'):
    os.environ[_v] = 'http://127.0.0.1:9'
os.environ['no_proxy'] = ''
sys.path.insert(0, RAIZ)
import servidor as S   # noqa: E402
import disparo as D    # noqa: E402

AFILIADO = S.eh_link_afiliado
TELEFONE = '5500000000001'   # fictício: nada parecido com número real no git
GRUPO_ID = '120363012345678901@g.us'
SEGUNDA = datetime(2026, 11, 2)    # weekday() == 0
SABADO = datetime(2026, 11, 7)     # weekday() == 5
with open(os.path.join(RAIZ, 'index.html'), encoding='utf-8') as _f:
    HTML = _f.read()
DEFAULT_TEMPLATES = json.loads(re.search(r'^const DEFAULT_TEMPLATES = (\{.*\});$', HTML, re.M).group(1))


def abrir(caminho):
    """Igual ao conectar() do servidor, mas com caminho explícito e guarda contra o banco real."""
    if os.path.realpath(caminho) == DB_REAL:
        raise RuntimeError('o teste tentou usar o banco real')
    con = sqlite3.connect(caminho, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA journal_mode=WAL')
    return con


def url_amz(n):
    return f'https://www.amazon.com.br/dp/B0TESTE{n:03d}?tag=desejodemen01-20'


class Base(unittest.TestCase):
    """Banco temporário com o esquema do servidor, a migração do disparo e os templates padrão."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(dir=TMP)
        self.caminho = os.path.join(self.dir, 'teste.db')
        with mock.patch.object(S, 'DB', self.caminho):
            S.criar_banco()
        self.con = abrir(self.caminho)
        self.addCleanup(self.con.close)
        D.migrar(self.con)
        self.gravar_templates(DEFAULT_TEMPLATES)
        self.seq = 0

    def conectar(self):
        return abrir(self.caminho)

    def gravar_templates(self, t):
        with self.con:
            self.con.execute("INSERT OR REPLACE INTO config VALUES ('templates', ?)", (json.dumps(t, ensure_ascii=False),))

    def item(self, loja='amazon', cat='Eletrônicos', url=None, **campos):
        """Insere um item com dados e devolve o id (pk)."""
        self.seq += 1
        n = self.seq
        dados = {'titulo': f'Produto {n}', 'preco': 'R$ 100,00', 'preco_antigo': '', 'desconto': '-10%',
                 'avaliacao': '', 'num_avaliacoes': '', 'vendas': '', 'frete': '', 'cupom': '',
                 'imagem': f'https://m.media-amazon.com/images/I/{n}.jpg', 'tem_dados': 1,
                 'posicao': n, 'criado_em': f'2026-11-01T00:00:{n % 60:02d}'}
        dados.update(campos)
        if url is None:
            url = url_amz(n) if loja == 'amazon' else f'https://meli.la/T{n}'
        cols = ['loja', 'item_id', 'cat', 'busca', 'url', *dados]
        with self.con:
            cur = self.con.execute(f'INSERT INTO items ({",".join(cols)}) VALUES ({",".join("?" * len(cols))})',
                                   [loja, f'ID{n}', cat, '', url, *dados.values()])
        return cur.lastrowid

    def numero(self, **kw):
        return D.criar_numero(self.con, {'nome': 'Loja 1', 'telefone': TELEFONE, 'grupo_nome': 'Achadinhos',
                                         'grupo_id': GRUPO_ID, **kw})

    def dados_regra(self, numero_id, **kw):
        return {'nome': 'Eletrônicos de manhã', 'numero_id': numero_id, 'cats': ['Eletrônicos'],
                'template': 'Template 2', 'horarios': ['09:00', '18:00'], 'dias': [0, 1, 2, 3, 4],
                'max_por_dia': 10, **kw}

    def regra(self, numero_id=None, **kw):
        if numero_id is None:
            numero_id = self.numero()['id']
        return D.criar_regra(self.con, self.dados_regra(numero_id, **kw))

    def envios(self, **filtro):
        sql = 'SELECT * FROM envios' + (' WHERE ' + ' AND '.join(f'{k}=?' for k in filtro) if filtro else '')
        return [dict(r) for r in self.con.execute(sql + ' ORDER BY id', list(filtro.values()))]

    def envio_antigo(self, regra, item_pk, status, criado_em, slot=None):
        with self.con:
            self.con.execute('INSERT INTO envios (regra_id, numero_id, item_pk, slot, status, mensagem, transporte, '
                             'criado_em) VALUES (?,?,?,?,?,?,?,?)',
                             (regra['id'], regra['numero_id'], item_pk, slot or f'antigo-{item_pk}-{status}', status,
                              'msg', 'manual', criado_em.isoformat(timespec='seconds')))

    def tick(self, agora, transporte=None, rng=None):
        return D.tick(self.conectar, agora, transporte or D.TransporteManual(), AFILIADO, rng)

    def assertSemDadoPessoal(self, texto, onde=''):
        for v in (TELEFONE, GRUPO_ID, TELEFONE[-8:], GRUPO_ID.split('@')[0]):
            self.assertNotIn(v, str(texto), onde)


# ================================================================ etapa 1: esquema
class Migracao(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(dir=TMP)

    def esquema(self, con):
        return sorted(tuple(r) for r in con.execute('SELECT type, name, sql FROM sqlite_master'))

    def test_banco_novo(self):
        con = abrir(os.path.join(self.dir, 'novo.db'))
        self.addCleanup(con.close)
        self.assertTrue(D.migrar(con))
        self.assertEqual(con.execute('PRAGMA user_version').fetchone()[0], 1)
        nomes = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type IN ('table','index')")}
        self.assertTrue({'numeros', 'regras', 'envios', 'ix_envios_rep'} <= nomes)
        cols = {r[1]: r for r in con.execute('PRAGMA table_info(regras)')}
        self.assertEqual(cols['repetir_apos_dias'][4], '7')
        self.assertEqual(cols['repetir_apos_dias'][3], 0)   # aceita NULL
        self.assertFalse(con.in_transaction)

    def test_banco_antigo_mantem_os_dados(self):
        caminho = os.path.join(self.dir, 'antigo.db')
        # o criar_banco de antes da etapa 4: o mesmo esquema de items/config, sem o disparo
        with mock.patch.object(S, 'DB', caminho), mock.patch.object(D, 'migrar'):
            S.criar_banco()
        con = abrir(caminho)
        self.addCleanup(con.close)
        S.upsert(con, {'loja': 'ml', 'url': 'https://meli.la/abc', 'cat': 'Casa', 'data': {'titulo': 'X'}})
        con.execute("INSERT INTO config VALUES ('templates', '{}')")
        con.commit()
        antes = [tuple(r) for r in con.execute('SELECT * FROM items')]
        self.assertEqual(con.execute('PRAGMA user_version').fetchone()[0], 0)
        self.assertTrue(D.migrar(con))
        self.assertEqual([tuple(r) for r in con.execute('SELECT * FROM items')], antes)
        self.assertEqual(con.execute("SELECT valor FROM config").fetchone()[0], '{}')
        self.assertEqual(con.execute('PRAGMA user_version').fetchone()[0], 1)

    def test_criar_banco_do_servidor_migra(self):
        caminho = os.path.join(self.dir, 'servidor.db')
        with mock.patch.object(S, 'DB', caminho):
            S.criar_banco()
            S.criar_banco()   # de novo, como a cada início do servidor
        con = abrir(caminho)
        self.addCleanup(con.close)
        self.assertEqual(con.execute('PRAGMA user_version').fetchone()[0], 1)
        self.assertIsNotNone(con.execute("SELECT 1 FROM sqlite_master WHERE name='envios'").fetchone())

    def test_repetida_sem_efeito(self):
        con = abrir(os.path.join(self.dir, 'rep.db'))
        self.addCleanup(con.close)
        D.migrar(con)
        D.criar_numero(con, {'nome': 'A', 'grupo_nome': 'G'})
        esquema, mudancas = self.esquema(con), con.total_changes
        self.assertFalse(D.migrar(con))
        outra = abrir(os.path.join(self.dir, 'rep.db'))
        self.addCleanup(outra.close)
        self.assertFalse(D.migrar(outra))
        self.assertEqual(self.esquema(con), esquema)
        self.assertEqual(con.total_changes, mudancas)
        self.assertEqual(len(D.listar_numeros(con)), 1)

    def test_tabelas_ja_existentes_com_versao_zero(self):
        con = abrir(os.path.join(self.dir, 'meio.db'))
        self.addCleanup(con.close)
        con.execute(D.ESQUEMA_V1[0]); con.commit()
        self.assertTrue(D.migrar(con))
        self.assertEqual(con.execute('PRAGMA user_version').fetchone()[0], 1)

    def test_versao_maior_nao_e_tocada(self):
        con = abrir(os.path.join(self.dir, 'futuro.db'))
        self.addCleanup(con.close)
        con.execute('PRAGMA user_version = 2')
        self.assertFalse(D.migrar(con))
        self.assertIsNone(con.execute("SELECT 1 FROM sqlite_master WHERE name='numeros'").fetchone())

    def test_falha_no_meio_desfaz_tudo(self):
        con = abrir(os.path.join(self.dir, 'falha.db'))
        self.addCleanup(con.close)
        with mock.patch.object(D, 'ESQUEMA_V1', D.ESQUEMA_V1[:2] + ('CREATE TABLE quebrada (',)):
            with self.assertRaises(sqlite3.OperationalError):
                D.migrar(con)
        self.assertEqual(con.execute('PRAGMA user_version').fetchone()[0], 0)
        self.assertIsNone(con.execute("SELECT 1 FROM sqlite_master WHERE name='numeros'").fetchone())
        self.assertTrue(D.migrar(con))


# ================================================================ etapa 1: validação e CRUD
class ValidarNumero(Base):
    BASE = {'nome': 'Loja 1', 'telefone': TELEFONE, 'grupo_nome': 'Achadinhos', 'grupo_id': GRUPO_ID,
            'limite_diario': 40, 'ativo': 1}

    def recusa(self, **kw):
        with self.assertRaises(D.ErroDisparo) as cm:
            D.validar_numero({**self.BASE, **kw})
        self.assertEqual(cm.exception.codigo, 400)
        self.assertSemDadoPessoal(str(cm.exception) + repr(cm.exception) + cm.exception.msg)
        for v in kw.values():   # nenhum valor recebido volta na mensagem
            if isinstance(v, str) and len(v) >= 4:
                self.assertNotIn(v, cm.exception.msg)
        return cm.exception

    def test_limites_aceitos(self):
        for kw in ({'telefone': ''}, {'telefone': '0000000001'}, {'telefone': '123456789012345'},
                   {'grupo_id': ''}, {'grupo_id': '12345@g.us'}, {'grupo_id': '5500000000001-1600000000@g.us'},
                   {'nome': 'x' * 80}, {'grupo_nome': 'g' * 80}, {'limite_diario': 1}, {'limite_diario': 200},
                   {'ativo': 0}):
            with self.subTest(kw=kw):
                D.validar_numero({**self.BASE, **kw})

    def test_telefone_recusado(self):
        for tel in ('000000001', '1234567890123456', '+5500000000001', '00 00000-0001', '(00)000000001',
                    '٥٥٠٠٠٠٠٠٠٠٠٠١', TELEFONE + '\n', 5500000000001, None, ['5500000000001']):
            with self.subTest(tel=tel):
                self.recusa(telefone=tel)

    def test_grupo_id_recusado(self):
        for g in ('1234@g.us', '120363012345678901@g.us.evil.com', 'abc@g.us', '120363012345678901',
                  '12345-12@g.us', '1' * 26 + '@g.us', '12345@s.whatsapp.net', 12345, GRUPO_ID + '\n'):
            with self.subTest(g=g):
                self.recusa(grupo_id=g)

    def test_textos_e_inteiros_recusados(self):
        for kw in ({'nome': ''}, {'nome': '   '}, {'nome': 'x' * 81}, {'nome': 3}, {'nome': None},
                   {'grupo_nome': ''}, {'grupo_nome': 'g' * 81},
                   {'limite_diario': 0}, {'limite_diario': 201}, {'limite_diario': True}, {'limite_diario': '40'},
                   {'limite_diario': 4.0}, {'ativo': 2}, {'ativo': True}, {'ativo': '1'}):
            with self.subTest(kw=kw):
                self.recusa(**kw)

    def test_objeto_invalido(self):
        for v in ([], 'x', None):
            with self.assertRaises(D.ErroDisparo):
                D.validar_numero(v)


class ValidarRegra(Base):
    def setUp(self):
        super().setUp()
        self.nid = self.numero()['id']
        self.base = {**D.PADRAO_REGRA, **self.dados_regra(self.nid)}

    def recusa(self, **kw):
        with self.assertRaises(D.ErroDisparo) as cm:
            D.validar_regra(self.con, {**self.base, **kw})
        self.assertEqual(cm.exception.codigo, 400)
        return cm.exception

    def test_limites_aceitos(self):
        for kw in ({'desconto_min': 0}, {'desconto_min': 95}, {'por_disparo': 1}, {'por_disparo': 10},
                   {'max_por_dia': 1}, {'max_por_dia': 200}, {'repetir_apos_dias': None},
                   {'repetir_apos_dias': 1}, {'repetir_apos_dias': 365}, {'intervalo_seg': 30},
                   {'intervalo_seg': 3600}, {'cats': [f'c{i}' for i in range(50)]}, {'cats': ['c' * 100]},
                   {'palavras': ['p' * 40] * 20}, {'lojas': ['ml']}, {'dias': [6]},
                   {'horarios': [f'{h:02d}:{m:02d}' for h in range(24) for m in (0, 30)]},
                   {'horarios': ['00:00', '23:59']}, *({'ordem': o} for o in D.ORDENS)):
            with self.subTest(kw=list(kw)):
                D.validar_regra(self.con, {**self.base, **kw})

    def test_cada_limite_recusado(self):
        casos = [
            {'nome': ''}, {'nome': 'n' * 81}, {'nome': 1},
            {'numero_id': 999}, {'numero_id': True}, {'numero_id': str(self.nid)}, {'numero_id': None},
            {'ativa': 2}, {'ativa': False},
            {'cats': []}, {'cats': [f'c{i}' for i in range(51)]}, {'cats': [1]}, {'cats': ['']},
            {'cats': ['c' * 101]}, {'cats': ['a', 'a']}, {'cats': 'Eletrônicos'},
            {'lojas': []}, {'lojas': ['shopee']}, {'lojas': ['amazon', 'amazon']}, {'lojas': 'amazon'},
            {'palavras': ['p'] * 21}, {'palavras': ['p' * 41]}, {'palavras': ['']}, {'palavras': ['  ']},
            {'palavras': [3]}, {'palavras': None},
            {'desconto_min': -1}, {'desconto_min': 96}, {'desconto_min': True}, {'desconto_min': 10.5},
            {'ordem': 'mais_vendidos'}, {'ordem': None},
            {'template': 'Não existe'}, {'template': 3}, {'template': None},
            {'com_foto': 2}, {'com_foto': True},
            {'dias': []}, {'dias': [7]}, {'dias': [-1]}, {'dias': [True]}, {'dias': [0, 0]}, {'dias': ['0']},
            {'dias': [0, 1, 2, 3, 4, 5, 6, 6]},
            {'horarios': []}, {'horarios': [f'{h:02d}:{m:02d}' for h in range(24) for m in (0, 20, 40)][:49]},
            {'horarios': ['24:00']}, {'horarios': ['9:00']}, {'horarios': ['09:60']}, {'horarios': ['09:00:00']},
            {'horarios': ['09:00', '09:00']}, {'horarios': ['09:00\n']}, {'horarios': [900]},
            {'por_disparo': 0}, {'por_disparo': 11}, {'por_disparo': True},
            {'max_por_dia': 0}, {'max_por_dia': 201},
            {'repetir_apos_dias': 0}, {'repetir_apos_dias': 366}, {'repetir_apos_dias': True},
            {'intervalo_seg': 29}, {'intervalo_seg': 3601},
        ]
        for kw in casos:
            with self.subTest(kw=kw):
                self.recusa(**kw)

    def test_template_sem_link_e_recusado(self):
        self.gravar_templates({**DEFAULT_TEMPLATES, 'Sem link': '*{TITULO_PRODUTO}*'})
        e = self.recusa(template='Sem link')
        self.assertIn('{LINK}', e.msg)

    def test_sem_templates_no_config(self):
        with self.con:
            self.con.execute("DELETE FROM config")
        self.recusa()
        with self.con:
            self.con.execute("INSERT INTO config VALUES ('templates', 'não é json')")
        self.recusa()

    def test_s3_surrogate_solto_e_recusado(self):
        for kw in ({'nome': 'a\ud800'}, {'cats': ['x\udfff']}, {'palavras': ['\ud83d']}, {'template': '\ud800'}):
            with self.subTest(kw=list(kw)):
                self.recusa(**kw)
        with self.assertRaises(D.ErroDisparo):
            D.validar_numero({**ValidarNumero.BASE, 'grupo_nome': 'g\ud800'})

    def test_normaliza(self):
        v = D.validar_regra(self.con, {**self.base, 'lojas': ['ml', 'amazon'], 'dias': [4, 0],
                                       'horarios': ['18:00', '09:00'], 'palavras': [' fone ']})
        self.assertEqual((v['lojas'], v['dias'], v['horarios'], v['palavras']),
                         (['amazon', 'ml'], [0, 4], ['09:00', '18:00'], ['fone']))


class CrudNumeros(Base):
    def test_criar_listar_atualizar_excluir(self):
        n = self.numero(limite_diario=5)
        self.assertEqual((n['nome'], n['telefone'], n['grupo_id'], n['limite_diario'], n['ativo']),
                         ('Loja 1', TELEFONE, GRUPO_ID, 5, 1))
        self.assertTrue(n['criado_em'])
        self.assertEqual(D.listar_numeros(self.con), [n])
        n2 = D.atualizar_numero(self.con, n['id'], {'nome': 'Loja 2', 'id': 99, 'proximo': 'x'})
        self.assertEqual((n2['id'], n2['nome'], n2['telefone'], n2['limite_diario']), (n['id'], 'Loja 2', TELEFONE, 5))
        D.excluir_numero(self.con, n['id'])
        self.assertEqual(D.listar_numeros(self.con), [])

    def test_padroes(self):
        n = D.criar_numero(self.con, {'nome': 'A', 'grupo_nome': 'G'})
        self.assertEqual((n['telefone'], n['grupo_id'], n['limite_diario'], n['ativo']), ('', '', 40, 1))

    def test_atualizacao_invalida_nao_grava(self):
        n = self.numero()
        with self.assertRaises(D.ErroDisparo) as cm:
            D.atualizar_numero(self.con, n['id'], {'telefone': '12'})
        self.assertSemDadoPessoal(cm.exception.msg)
        self.assertEqual(D.obter_numero(self.con, n['id']), n)

    def test_404_e_409(self):
        for f in (lambda: D.atualizar_numero(self.con, 99, {'nome': 'x'}), lambda: D.excluir_numero(self.con, 99),
                  lambda: D.obter_numero(self.con, 99)):
            with self.assertRaises(D.ErroDisparo) as cm:
                f()
            self.assertEqual(cm.exception.codigo, 404)
        r = self.regra(ativa=0)
        with self.assertRaises(D.ErroDisparo) as cm:
            D.excluir_numero(self.con, r['numero_id'])
        self.assertEqual(cm.exception.codigo, 409)
        self.assertEqual(len(D.listar_numeros(self.con)), 1)

    def test_criacao_invalida_sem_telefone_na_excecao(self):
        for kw in ({'nome': ''}, {'limite_diario': 0}, {'grupo_id': 'x'}, {'telefone': TELEFONE + '9' * 5}):
            with self.subTest(kw=kw), self.assertRaises(D.ErroDisparo) as cm:
                self.numero(**kw)
            self.assertSemDadoPessoal(repr(cm.exception))
        self.assertEqual(D.listar_numeros(self.con), [])


class CrudRegras(Base):
    def test_criar_com_padroes_e_listas_em_json(self):
        nid = self.numero()['id']
        r = D.criar_regra(self.con, {'nome': 'R', 'numero_id': nid, 'cats': ['Casa'], 'template': 'Template 1',
                                     'horarios': ['10:00']})
        self.assertEqual({k: r[k] for k in D.PADRAO_REGRA}, D.PADRAO_REGRA)
        self.assertEqual((r['cats'], r['horarios'], r['aviso']), (['Casa'], ['10:00'], ''))
        cru = self.con.execute('SELECT cats, lojas, dias FROM regras WHERE id=?', (r['id'],)).fetchone()
        self.assertEqual(json.loads(cru['cats']), ['Casa'])
        self.assertEqual(json.loads(cru['dias']), [0, 1, 2, 3, 4, 5, 6])
        self.assertEqual(D.listar_regras(self.con), [r])

    def test_repetir_nulo_e_gravado(self):
        r = self.regra(repetir_apos_dias=None)
        self.assertIsNone(D.obter_regra(self.con, r['id'])['repetir_apos_dias'])

    def test_atualizar_parcial_limpa_aviso(self):
        r = self.regra()
        with self.con:
            self.con.execute("UPDATE regras SET aviso='x' WHERE id=?", (r['id'],))
        r2 = D.atualizar_regra(self.con, r['id'], {'ativa': 0})
        self.assertEqual((r2['ativa'], r2['aviso'], r2['cats'], r2['horarios']), (0, '', r['cats'], r['horarios']))

    def test_r1_template_apagado_ainda_deixa_pausar(self):
        r = self.regra()
        self.gravar_templates({'Template 1': DEFAULT_TEMPLATES['Template 1']})   # o Template 2 da regra sumiu
        self.assertEqual(D.atualizar_regra(self.con, r['id'], {'ativa': 0})['ativa'], 0)
        self.assertEqual(D.atualizar_regra(self.con, r['id'], {'nome': 'Outra', 'ativa': 1})['nome'], 'Outra')
        for t in ('Template 2', 'x'):
            with self.subTest(t=t), self.assertRaises(D.ErroDisparo) as cm:
                D.atualizar_regra(self.con, r['id'], {'template': t})
            self.assertEqual(cm.exception.codigo, 400)
        self.assertEqual(D.atualizar_regra(self.con, r['id'], {'template': 'Template 1'})['template'], 'Template 1')
        with self.assertRaises(D.ErroDisparo):   # na criação continua exigido
            self.regra(numero_id=r['numero_id'], template='Template 2')

    def test_atualizar_invalido_nao_grava(self):
        r = self.regra()
        with self.assertRaises(D.ErroDisparo):
            D.atualizar_regra(self.con, r['id'], {'horarios': []})
        self.assertEqual(D.obter_regra(self.con, r['id']), r)

    def test_excluir_mantem_envios(self):
        r = self.regra()
        self.envio_antigo(r, self.item(), 'enviado', SEGUNDA)
        D.excluir_regra(self.con, r['id'])
        self.assertEqual(D.listar_regras(self.con), [])
        self.assertEqual(len(self.envios()), 1)
        with self.assertRaises(D.ErroDisparo) as cm:
            D.excluir_regra(self.con, r['id'])
        self.assertEqual(cm.exception.codigo, 404)


# ================================================================ etapa 2: mensagem
def casos_de_paridade():
    with open(os.path.join(RAIZ, 'testes', 'mensagens.test.html'), encoding='utf-8') as f:
        html = f.read()
    # ancorado no começo da linha: o comentário do topo da página cita a mesma tag
    m = re.search(r'^<script type="application/json" id="casos">\n(.*?)^</script>', html, re.S | re.M)
    return json.loads(m.group(1))


class Mensagem(unittest.TestCase):
    def test_paridade_com_buildMsg(self):
        """Os mesmos casos que testes/mensagens.test.html roda no buildMsg real (CA8)."""
        casos = casos_de_paridade()
        self.assertGreaterEqual(len(casos), 16)
        for c in casos:
            with self.subTest(c['nome']):
                self.assertEqual(D.montar_mensagem(c['item'], c['template']), c['esperado'])

    def test_casos_usam_os_templates_padrao_atuais(self):
        casos = casos_de_paridade()
        padrao = {c['padrao']: c['template'] for c in casos if 'padrao' in c}
        self.assertEqual(padrao, DEFAULT_TEMPLATES)

    def test_casos_exigidos_pelo_plano_existem(self):
        casos = casos_de_paridade()
        dados = [c['item']['data'] or {} for c in casos]
        self.assertTrue(any(not d for d in dados), 'item sem data')
        self.assertTrue(any('\u200b' in d.get('titulo', '') for d in dados), 'U+200B no título')
        self.assertTrue(any(d.get('desconto') and not d['desconto'].startswith('-') for d in dados), 'desconto sem -')
        self.assertTrue(any(not d.get('vendas') and d.get('num_avaliacoes') for d in dados), 'fallback avaliações')
        self.assertTrue(any(not d.get('vendas') and not d.get('num_avaliacoes') and d.get('avaliacao')
                            for d in dados), 'fallback nota')

    def test_s2_limite_na_montagem(self):
        it = {'url': url_amz(1), 'loja': 'amazon', 'data': {'titulo': '$`' * 250, 'cupom': '$`' * 100}}
        tpl = 'Oferta do dia: {TITULO_PRODUTO} {LINK}\n{CUPOM}'   # $` copia o que vem antes do campo
        self.assertGreater(len(D.montar_mensagem(it, tpl)), D.LIMITE_MONTAGEM, 'sem limite, o porte expande')
        with self.assertRaises(D.MensagemGrande):
            D.montar_mensagem(it, tpl, limite=D.LIMITE_MONTAGEM)
        with self.assertRaises(D.MensagemGrande):
            D.montar_mensagem({'url': url_amz(1), 'data': {}}, 'x' * (D.LIMITE_MONTAGEM + 1), limite=D.LIMITE_MONTAGEM)
        # abaixo do limite, o resultado é o mesmo do porte puro (a paridade não muda)
        for c in casos_de_paridade():
            with self.subTest(c['nome']):
                self.assertEqual(D.montar_mensagem(c['item'], c['template'], limite=D.LIMITE_MONTAGEM), c['esperado'])

    def test_trim_do_js(self):
        it = {'url': url_amz(1), 'loja': 'amazon', 'data': {'titulo': '\ufeff\u200bA\u0085\u00a0\ufeff'}}
        self.assertEqual(D.montar_mensagem(it, '{TITULO_PRODUTO}'), '\u200bA\u0085')

    def test_urls_da_mensagem(self):
        self.assertEqual(D.urls_da_mensagem('Compre: *https://meli.la/abc*. Veja (https://meli.la/x).'),
                         ['https://meli.la/abc', 'https://meli.la/x'])
        self.assertEqual(D.urls_da_mensagem('R$ 1.899,00 R$ 1.249,90 4.8 de 5 Wi-Fi 6 1.5m (43% OFF) 2.0'), [])
        # falso positivo aceito (S1): parece domínio, então a mensagem não sai
        self.assertEqual(D.urls_da_mensagem('Node.js i.phone'), ['Node.js', 'i.phone'])
        for t in ('www.google.com', 'amzn.to/abc', 'meli.la/x', 'veja exemplo.com', 'ftp://x', 'HTTPS://evil.com',
                  'mercadolivre.com.br?x=1'):
            with self.subTest(t=t):
                self.assertEqual(len(D.urls_da_mensagem(t)), 1)

    def test_s1_dominios_soltos_idn_italico_e_email_sao_recusados(self):
        url = 'https://meli.la/1AbCdEf'
        ok = f'*Fone JBL*\n🔥 R$ 1.249,90 (43% OFF)\n⭐ 4.8 de 5 · Wi-Fi 6\n🛒 Compre aqui: {url}'
        self.assertTrue(D.mensagem_so_com_afiliado(ok, AFILIADO, url))
        for extra in ('promo.pt', 'cupons.vip', 'andro.id', 'promoção.com', '_golpe.com/p_', '*promo.pt*',
                      '~golpe.com~', 'golpe\u3002com', 'golpe\uff0ecom', 'golpe\uff61com/x', 'x@golpe.com',
                      'contato@promo.pt.', '(golpe.com)', 'aqui:https://evil.com', 'www.evil.com',
                      'golpe.com\u200b/x', 'a..golpe.com', 'https://meli.la/OUTRO', '#_golpe.com',
                      'golpe.com_#', '-golpe.com-', 'x_golpe.com', '#golpe.com', 'GOLPE.COM',
                      # rodada 3: NFKC, marcas Mn/Mc, IP sem esquema, ZWJ e ponto médio
                      'golpe\u2488com', '\uff47\uff4f\uff4c\uff50\uff45\uff0e\uff43\uff4f\uff4d',
                      'golpe.\u0915\u0949\u092e', '10.0.0.1/x', '10.0.0.1', '192.168.0.1:8080',
                      'golpe\u200d.com', 'golpe.\u200dcom', 'golpe\u00b7com', 'golpe\u2027com',
                      'golpe\u30fbcom', 'golpe\u200b.com', 'golpe\u2060.com',
                      url_amz(7), f'{url}?x=1', f'{url}/a', 'xhttps://meli.la/1AbCdEf'):
            with self.subTest(extra=extra):
                self.assertFalse(D.mensagem_so_com_afiliado(ok + '\nVeja ' + extra, AFILIADO, url))
        for passa in ('Fone \u00b7 JBL', 'Bluetooth 5.3', 'v1.2.3', 'R$ 1.249.999,90', 'Wi\u2011Fi 6',
                      '\U0001f468\u200d\U0001f469\u200d\U0001f467 família', 'Nota 4,8 \u00b7 4.8 de 5',
                      '\uff12\uff10\uff12\uff16', 'IP67 1.2.3 cabo 2.0'):
            with self.subTest(passa=passa):
                self.assertTrue(D.mensagem_so_com_afiliado(ok + '\n' + passa, AFILIADO, url), passa)
        for borda in (f'*{url}*', f'_{url}_', f'({url}).', f'Link:{url}', f'{url}!!'):
            with self.subTest(borda=borda):
                self.assertTrue(D.mensagem_so_com_afiliado('Oferta ' + borda, AFILIADO, url))

    def test_s1_templates_padrao_passam_nas_duas_lojas(self):
        cheio = {'titulo': 'Fone Bluetooth Wi-Fi 6', 'preco': 'R$ 1.249,90', 'preco_antigo': 'R$ 1.999,00',
                 'desconto': '-37%', 'avaliacao': '4.8 de 5 estrelas', 'num_avaliacoes': '27,6 mil',
                 'vendas': '', 'frete': 'Frete GRÁTIS', 'cupom': 'FONE10', 'imagem': ''}
        for loja, url in (('amazon', url_amz(1)), ('ml', 'https://meli.la/1AbCdEf')):
            for nome, tpl in DEFAULT_TEMPLATES.items():
                with self.subTest(loja=loja, template=nome):
                    msg = D.montar_mensagem({'loja': loja, 'url': url, 'data': cheio}, tpl)
                    self.assertTrue(D.mensagem_so_com_afiliado(msg, AFILIADO, url), msg)

    def test_s2_analise_linear_em_texto_hostil(self):
        for hostil in ('a' * 40000, 'a.' * 20000, 'a-' * 20000, '1.' * 20000, 'a_' * 20000, 'x://' * 10000,
                       ('a.' * 100 + ' ') * 200, '_' * 40000 + 'golpe.com'):
            with self.subTest(hostil=hostil[:12]):
                inicio = time.monotonic()
                D.urls_da_mensagem(hostil)
                self.assertLess(time.monotonic() - inicio, 0.5)
        self.assertFalse(D.mensagem_so_com_afiliado('https://meli.la/x ' + 'a' * D.MAX_MENSAGEM, AFILIADO))

    def test_so_afiliado(self):
        ok = 'Oferta https://meli.la/abc'
        self.assertTrue(D.mensagem_so_com_afiliado(ok, AFILIADO))
        self.assertTrue(D.mensagem_so_com_afiliado(f'*{url_amz(1)}*', AFILIADO))
        for extra in ('https://evil.com', 'http://meli.la/abc', 'www.amazon.com.br/dp/X', 'amzn.to/x',
                      'https://www.amazon.com.br/dp/X', 'https://www.amazon.com.br/dp/X?tag=outra-20',
                      'https://meli.la/abc\u200b.evil.com', 'https://meli.la/abc\ufeffwww.evil.com',
                      'https://meli.la/abc\u00a0evil.com', 'xhttps://meli.la/abc'):
            with self.subTest(extra=extra):
                self.assertFalse(D.mensagem_so_com_afiliado(ok + '\n' + extra, AFILIADO))
        self.assertFalse(D.mensagem_so_com_afiliado('Sem link nenhum', AFILIADO))


# ================================================================ etapa 2: seleção e ordem
class Elegiveis(Base):
    def setUp(self):
        super().setUp()
        self.r = self.regra(lojas=['amazon', 'ml'])

    def ids(self, regra=None, agora=SEGUNDA):
        return sorted(it['id'] for it in D.elegiveis(self.con, regra or D.obter_regra(self.con, self.r['id']),
                                                    agora, AFILIADO))

    def test_ca4_so_item_completo_e_de_afiliado(self):
        bons = [self.item(), self.item(loja='ml')]
        self.item(tem_dados=0)
        self.item(titulo='')
        self.item(preco='')
        self.item(loja='ml', url='https://produto.mercadolivre.com.br/MLB-123')   # ML sem meli.la
        self.item(loja='ml', url=url_amz(90))                                     # ML com link da Amazon
        self.item(loja='amazon', url='https://meli.la/abc')                       # Amazon com link do ML
        self.item(url='https://www.amazon.com.br/dp/B0X')                         # sem tag
        self.item(url='https://www.amazon.com.br/dp/B0X?tag=outra-20')
        self.item(url='https://amzn.to/abc')
        self.item(cat='Outra')
        self.assertEqual(self.ids(), bons)

    def test_lojas_desconto_e_palavras(self):
        a = self.item(desconto='-30%', titulo='Fone Bluetooth JBL')
        b = self.item(loja='ml', desconto='-50%', titulo='Câmera de segurança')
        self.item(desconto='-5%', titulo='Fone barato')
        self.item(desconto='', titulo='Fone sem desconto')
        r = D.atualizar_regra(self.con, self.r['id'], {'desconto_min': 30})
        self.assertEqual(self.ids(r), [a, b])
        r = D.atualizar_regra(self.con, self.r['id'], {'lojas': ['ml']})
        self.assertEqual(self.ids(r), [b])
        r = D.atualizar_regra(self.con, self.r['id'], {'lojas': ['amazon', 'ml'], 'palavras': ['CAMERA', 'xyz']})
        self.assertEqual(self.ids(r), [b])

    def test_ca5_status_que_bloqueiam(self):
        itens = {st: self.item() for st in D.STATUS}
        for st, pk in itens.items():
            self.envio_antigo(self.r, pk, st, SEGUNDA - timedelta(days=1))
        livres = sorted(itens[st] for st in ('pulado', 'erro', 'expirado'))
        self.assertEqual(self.ids(), livres)

    def test_ca5_prazo_em_dias_de_calendario(self):
        pk = self.item()   # prazo padrão: 7 dias
        self.envio_antigo(self.r, pk, 'enviado', SEGUNDA.replace(hour=9) - timedelta(days=7))
        self.assertEqual(self.ids(agora=SEGUNDA - timedelta(seconds=1)), [], 'domingo: ainda no prazo')
        self.assertEqual(self.ids(agora=SEGUNDA), [pk], 'segunda seguinte, mesmo antes das 9h')
        r = D.atualizar_regra(self.con, self.r['id'], {'repetir_apos_dias': 1})
        self.envio_antigo(r, pk, 'enviado', SEGUNDA.replace(hour=23, minute=59), slot='2026-11-02T23:59')
        self.assertEqual(self.ids(r, agora=SEGUNDA.replace(hour=23, minute=59, second=30)), [])
        self.assertEqual(self.ids(r, agora=SEGUNDA + timedelta(days=1)), [pk], 'N=1: só o mesmo dia bloqueia')

    def test_ca5_nulo_nunca_repete(self):
        r = D.atualizar_regra(self.con, self.r['id'], {'repetir_apos_dias': None})
        pk = self.item()
        self.envio_antigo(r, pk, 'enviado', SEGUNDA - timedelta(days=400))
        self.assertEqual(self.ids(r), [])

    def test_ca5_conta_por_numero_juntando_regras(self):
        pk = self.item()
        outra = self.regra(numero_id=self.r['numero_id'], nome='Outra')
        self.envio_antigo(outra, pk, 'enviado', SEGUNDA)
        self.assertEqual(self.ids(), [])
        de_outro_numero = self.regra(nome='Outro número')
        self.assertEqual(self.ids(de_outro_numero), [pk])


class Ordenar(unittest.TestCase):
    @staticmethod
    def it(pk, **d):
        dados = {c: '' for c in D.CAMPOS_ITEM}
        dados.update(d)
        return {'id': pk, 'posicao': d.pop('posicao', pk), 'criado_em': d.pop('criado_em', ''),
                'data': dados}

    def ordem(self, itens, ordem, rng=None):
        return [x['id'] for x in D.ordenar(itens, ordem, rng)]

    def test_conversoes(self):
        self.assertEqual(D.contagem('Mais de 1 mil compras no mês passado'), 1000)
        self.assertEqual(D.contagem('Mais de 1000 produtos vendidos'), 1000)
        self.assertEqual(D.contagem('Mais de 300 compras'), 300)
        self.assertEqual(D.contagem('27,6 mil'), 27600)
        self.assertEqual(D.contagem('(135)'), 135)
        self.assertEqual(D.contagem('1.234'), 1234)
        self.assertEqual(D.contagem(''), 0)
        self.assertEqual(D.contagem('1.2.3 mil'), 123000)
        self.assertEqual(D.contagem('1.5 mil'), 1500)
        self.assertEqual(D.nota('4,7 de 5 estrelas'), 4.7)
        self.assertEqual(D.nota('4.1 de 5 estrelas'), 4.1)
        self.assertEqual(D.preco_num('R$ 1.899,00'), 1899.0)
        self.assertEqual(D.preco_num('R$45,03'), 45.03)
        self.assertEqual(D.preco_num(''), 0)
        self.assertEqual(D.pct('-34%'), 34)

    def test_relevancia(self):
        itens = [self.it(1, vendas='Mais de 500 produtos vendidos'),
                 self.it(2, vendas='Mais de 1 mil compras', num_avaliacoes='(135)'),
                 self.it(3, vendas='Mais de 1000 produtos vendidos', num_avaliacoes='27,6 mil'),
                 self.it(4, num_avaliacoes='27,6 mil', avaliacao='4,1 de 5'),
                 self.it(5, num_avaliacoes='27,6 mil', avaliacao='4,8 de 5'),
                 self.it(6), self.it(0)]
        self.assertEqual(self.ordem(itens, 'relevancia'), [3, 2, 1, 5, 4, 0, 6])

    def test_desconto_e_desempate_por_posicao(self):
        itens = [self.it(1, desconto='-10%'), self.it(2, desconto='-40%', posicao=9),
                 self.it(3, desconto='-40%', posicao=1), self.it(4)]
        self.assertEqual(self.ordem(itens, 'desconto'), [3, 2, 1, 4])

    def test_precos_com_vazio_no_fim(self):
        itens = [self.it(1, preco='R$ 50,00'), self.it(2, preco=''), self.it(3, preco='R$ 1.200'),
                 self.it(4, preco='R$ 9,90'), self.it(5, preco='consulte')]
        self.assertEqual(self.ordem(itens, 'menor_preco'), [4, 1, 3, 2, 5])
        self.assertEqual(self.ordem(itens, 'maior_preco'), [3, 1, 4, 2, 5])

    def test_cupom(self):
        itens = [self.it(1, desconto='-90%'), self.it(2, cupom='X', desconto='-5%'),
                 self.it(3, cupom='Y', desconto='-20%'), self.it(4, desconto='-50%')]
        self.assertEqual(self.ordem(itens, 'cupom'), [3, 2, 1, 4])

    def test_recentes_por_criado_em_e_id(self):
        itens = [self.it(1, criado_em='2026-11-01T10:00:00'), self.it(2, criado_em='2026-11-03T10:00:00'),
                 self.it(3, criado_em='2026-11-01T10:00:00', posicao=0), self.it(4)]
        self.assertEqual(self.ordem(itens, 'recentes'), [2, 3, 1, 4])   # empate: id maior primeiro

    def test_recentes_ignora_atualizado_em(self):
        """R4: item antigo reclassificado (atualizado_em de hoje) não passa à frente do novo."""
        velho = self.it(1, criado_em='2026-10-01T10:00:00')
        velho['atualizado_em'] = '2026-11-03T12:00:00'
        novo = self.it(2, criado_em='2026-11-02T10:00:00')
        novo['atualizado_em'] = '2026-11-02T10:00:00'
        self.assertEqual(self.ordem([velho, novo], 'recentes'), [2, 1])

    def test_aleatoria_com_rng_injetado(self):
        itens = [self.it(i) for i in range(1, 30)]
        a = self.ordem(itens, 'aleatoria', random.Random(5))
        self.assertEqual(a, self.ordem(list(reversed(itens)), 'aleatoria', random.Random(5)))
        self.assertEqual(sorted(a), list(range(1, 30)))
        self.assertNotEqual(a, list(range(1, 30)))

    def test_ordem_desconhecida(self):
        with self.assertRaises(ValueError):
            D.ordenar([], 'x')


class Previa(Base):
    def setUp(self):
        super().setUp()
        self.nid = self.numero()['id']

    def contagens(self):
        return {t: self.con.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
                for t in ('items', 'numeros', 'regras', 'envios', 'config')}

    def test_previa_sem_gravar(self):
        for d in ('-10%', '-50%', '-30%'):
            self.item(desconto=d)
        antes, mudancas = self.contagens(), self.con.total_changes
        p = D.previa(self.con, self.dados_regra(self.nid, ordem='desconto'), 2, SEGUNDA, AFILIADO)
        self.assertEqual([x['titulo'] for x in p], ['Produto 2', 'Produto 3'])
        self.assertEqual(set(p[0]), {'item_pk', 'titulo', 'mensagem', 'imagem'})
        self.assertIn(url_amz(2), p[0]['mensagem'])
        self.assertTrue(p[0]['imagem'].startswith('https://m.media-amazon.com/'))
        self.assertEqual((self.contagens(), self.con.total_changes), (antes, mudancas))

    def test_foto_so_com_com_foto_e_host_permitido(self):
        self.item()
        self.item(imagem='https://evil.com/x.jpg')
        self.item(imagem='')
        p = D.previa(self.con, self.dados_regra(self.nid), 5, SEGUNDA, AFILIADO)
        self.assertEqual([x['imagem'][:8] for x in p], ['https://', '', ''])
        p = D.previa(self.con, self.dados_regra(self.nid, com_foto=0), 5, SEGUNDA, AFILIADO)
        self.assertEqual([x['imagem'] for x in p], ['', '', ''])

    def test_n_e_regra_invalidos(self):
        for n in (0, 21, True, '5', None):
            with self.subTest(n=n), self.assertRaises(D.ErroDisparo):
                D.previa(self.con, self.dados_regra(self.nid), n, SEGUNDA, AFILIADO)
        with self.assertRaises(D.ErroDisparo):
            D.previa(self.con, self.dados_regra(self.nid, horarios=[]), 5, SEGUNDA, AFILIADO)

    def test_ca4_template_com_url_comum_nao_gera_mensagem(self):
        self.item()
        self.gravar_templates({**DEFAULT_TEMPLATES, 'Com site': '{TITULO_PRODUTO}\n{LINK}\nSiga: www.meusite.com'})
        self.assertEqual(D.previa(self.con, self.dados_regra(self.nid, template='Com site'), 5, SEGUNDA, AFILIADO), [])

    def test_s2_titulo_gigante_gravado_direto_e_pulado_rapido(self):
        grande = self.item()
        with self.con:   # direto no banco, como o upsert do coletor: não passa pelo 400 do servidor
            self.con.execute('UPDATE items SET titulo=? WHERE id=?', ('a.' * 20000, grande))
        ok = self.item()
        inicio = time.monotonic()
        p = D.previa(self.con, self.dados_regra(self.nid), 5, SEGUNDA, AFILIADO)
        self.assertLess(time.monotonic() - inicio, 0.5)
        self.assertEqual([x['item_pk'] for x in p], [ok])

    def test_ca4_titulo_com_url_comum_e_pulado(self):
        self.item(titulo='Promo em https://evil.com')
        ok = self.item()
        p = D.previa(self.con, self.dados_regra(self.nid), 5, SEGUNDA, AFILIADO)
        self.assertEqual([x['item_pk'] for x in p], [ok])


# ================================================================ etapa 3: transportes falsos de teste
class Gravador:
    """Transporte automático que só anota as chamadas."""
    nome, automatico = 'gravador', True

    def __init__(self, erro=None):
        self.chamadas, self.erro = [], erro

    def enviar(self, destino, texto, imagem_url):
        self.chamadas.append((dict(destino), texto, imagem_url))
        if self.erro:
            raise self.erro


class Agendamento(Base):
    def setUp(self):
        super().setUp()
        self.n = self.numero(limite_diario=40)
        self.r = self.regra(numero_id=self.n['id'])
        for _ in range(8):
            self.item()

    def test_dia_e_horario(self):
        self.assertEqual(self.tick(SABADO.replace(hour=9, minute=5))['criados'], 0)
        for hora in ((8, 59), (10, 30), (9, 10, 1)):
            with self.subTest(hora=hora):
                self.assertEqual(self.tick(SEGUNDA.replace(hour=hora[0], minute=hora[1],
                                                           second=hora[2] if len(hora) > 2 else 0))['criados'], 0)
        self.assertEqual(self.tick(SEGUNDA.replace(hour=9))['criados'], 1)
        self.assertEqual([e['slot'] for e in self.envios()], ['2026-11-02T09:00'])

    def test_tolerancia_de_10_min_sem_rajada(self):
        self.assertEqual(self.tick(SEGUNDA.replace(hour=9, minute=10))['criados'], 1)   # limite exato
        # servidor desligado das 17:00 às 18:11: o 18:00 é pulado, sem compensar depois
        self.assertEqual(self.tick(SEGUNDA.replace(hour=18, minute=11))['criados'], 0)
        self.assertEqual(self.tick(SEGUNDA.replace(hour=18, minute=30))['criados'], 0)
        self.assertEqual(len(self.envios()), 1)

    def test_por_disparo(self):
        D.atualizar_regra(self.con, self.r['id'], {'por_disparo': 3})
        self.assertEqual(self.tick(SEGUNDA.replace(hour=9, minute=1))['criados'], 3)
        self.assertEqual(len({e['item_pk'] for e in self.envios()}), 3)

    def test_max_por_dia_por_regra(self):
        D.atualizar_regra(self.con, self.r['id'], {'max_por_dia': 3, 'por_disparo': 2,
                                                   'horarios': ['09:00', '12:00', '18:00']})
        criados = [self.tick(SEGUNDA.replace(hour=h, minute=2))['criados'] for h in (9, 12, 18)]
        self.assertEqual(criados, [2, 1, 0])
        self.assertEqual(self.tick((SEGUNDA + timedelta(days=1)).replace(hour=9, minute=2))['criados'], 2)

    def test_limite_diario_por_numero(self):
        with self.con:
            self.con.execute('UPDATE numeros SET limite_diario=3 WHERE id=?', (self.n['id'],))
        self.regra(numero_id=self.n['id'], nome='Outra', por_disparo=2)
        D.atualizar_regra(self.con, self.r['id'], {'por_disparo': 2})
        self.assertEqual(self.tick(SEGUNDA.replace(hour=9, minute=1))['criados'], 3)
        self.assertEqual(self.tick(SEGUNDA.replace(hour=18, minute=1))['criados'], 0)

    def test_pulado_e_erro_nao_contam_no_limite(self):
        D.atualizar_regra(self.con, self.r['id'], {'max_por_dia': 1})
        self.envio_antigo(self.r, 1, 'pulado', SEGUNDA.replace(hour=8))
        self.envio_antigo(self.r, 2, 'erro', SEGUNDA.replace(hour=8))
        self.assertEqual(self.tick(SEGUNDA.replace(hour=9, minute=1))['criados'], 1)

    # Transporte automático nestes dois: no manual, o pendente não marcado expira no dia seguinte e,
    # como manda o plano, expirado não bloqueia (ver test_pendente_expirado_volta_a_ser_elegivel).
    def test_nao_repetir_com_prazo(self):
        D.atualizar_regra(self.con, self.r['id'], {'repetir_apos_dias': 2, 'ordem': 'desconto'})
        with self.con:   # o item 1 é o melhor em desconto
            self.con.execute("UPDATE items SET desconto='-90%' WHERE id=1")
        for d in (0, 1, 2):
            self.tick((SEGUNDA + timedelta(days=d)).replace(hour=9), Gravador())
        self.assertEqual([e['item_pk'] for e in self.envios()], [1, 2, 1])

    def test_nao_repetir_nulo(self):
        D.atualizar_regra(self.con, self.r['id'], {'repetir_apos_dias': None, 'por_disparo': 5})
        for d in (0, 1, 2, 3):
            self.tick((SEGUNDA + timedelta(days=d)).replace(hour=9), Gravador())
        pks = [e['item_pk'] for e in self.envios()]
        self.assertEqual(sorted(pks), list(range(1, 9)))   # 8 itens, nenhum repetido; depois acaba

    def test_pendente_expirado_volta_a_ser_elegivel(self):
        D.atualizar_regra(self.con, self.r['id'], {'ordem': 'desconto'})
        with self.con:
            self.con.execute("UPDATE items SET desconto='-90%' WHERE id=1")
        self.tick(SEGUNDA.replace(hour=9))
        self.tick(SEGUNDA.replace(hour=18))   # no mesmo dia, o pendente ainda bloqueia
        self.tick((SEGUNDA + timedelta(days=1)).replace(hour=9))
        self.assertEqual([(e['item_pk'], e['status']) for e in self.envios()],
                         [(1, 'expirado'), (2, 'expirado'), (1, 'pendente')])

    def test_pulado_nao_bloqueia_repeticao(self):
        D.atualizar_regra(self.con, self.r['id'], {'ordem': 'desconto'})
        with self.con:
            self.con.execute("UPDATE items SET desconto='-90%' WHERE id=1")
        self.tick(SEGUNDA.replace(hour=9))
        e = self.envios()[0]
        D.marcar_envio(self.con, e['id'], 'pulado')
        self.tick(SEGUNDA.replace(hour=18))
        self.assertEqual([x['item_pk'] for x in self.envios()], [1, 1])

    def test_ca7_slot_processado_nao_repete_nem_apos_reinicio(self):
        self.assertEqual(self.tick(SEGUNDA.replace(hour=9, minute=1))['criados'], 1)
        self.assertEqual(self.tick(SEGUNDA.replace(hour=9, minute=2))['criados'], 0)
        self.con.close()
        self.con = self.conectar()   # "reinício": conexão e agendador novos
        self.addCleanup(self.con.close)
        ag = D.Agendador(self.conectar, AFILIADO, D.TransporteManual(), intervalo=60,
                         relogio=lambda: SEGUNDA.replace(hour=9, minute=5))
        ag.start()
        esperar(lambda: ag.ticks >= 1)
        ag.parar(); ag.join(5)
        self.assertEqual(len(self.envios()), 1)

    def test_manual_fica_pendente_e_vai_para_a_fila(self):
        self.tick(SEGUNDA.replace(hour=9))
        e = self.envios()[0]
        self.assertEqual((e['status'], e['transporte'], e['numero_id'], e['enviado_em']),
                         ('pendente', 'manual', self.n['id'], None))
        self.assertIn('https://www.amazon.com.br/', e['mensagem'])
        self.assertEqual(e['titulo'], 'Produto 1')
        self.assertEqual([f['id'] for f in D.listar_fila(self.con)], [e['id']])
        self.assertSemDadoPessoal(json.dumps(D.listar_fila(self.con)))

    def test_automatico_envia_com_foto_e_marca_enviado(self):
        t = Gravador()
        D.atualizar_regra(self.con, self.r['id'], {'por_disparo': 2})
        with self.con:
            self.con.execute("UPDATE items SET imagem='' WHERE id=2")
        res = self.tick(SEGUNDA.replace(hour=9), t)
        self.assertEqual(res['criados'], 2)
        self.assertEqual([c[2] for c in t.chamadas], ['https://m.media-amazon.com/images/I/1.jpg', None])
        self.assertEqual(t.chamadas[0][0], {'telefone': TELEFONE, 'grupo_id': GRUPO_ID, 'grupo_nome': 'Achadinhos'})
        self.assertEqual([(e['status'], e['transporte'], bool(e['enviado_em'])) for e in self.envios()],
                         [('enviado', 'gravador', True)] * 2)
        self.assertEqual(t.chamadas[0][1], self.envios()[0]['mensagem'])

    def test_sem_foto_quando_com_foto_zero(self):
        t = Gravador()
        D.atualizar_regra(self.con, self.r['id'], {'com_foto': 0})
        self.tick(SEGUNDA.replace(hour=9), t)
        self.assertIsNone(t.chamadas[0][2])
        self.assertEqual(self.envios()[0]['imagem'], '')

    def test_falha_do_transporte_grava_erro_sem_dado_pessoal(self):
        casos = [(D.ErroEnvio(f'número {TELEFONE} fora do grupo {GRUPO_ID}'), None),
                 (D.ErroEnvio('falhou para +55 (00) 00000-0001'), None),
                 (RuntimeError(f'conexão caiu ao enviar para {TELEFONE}'), 'RuntimeError')]
        for i, (erro, esperado) in enumerate(casos):
            with self.subTest(erro=type(erro).__name__, i=i):
                hora = SEGUNDA.replace(hour=9) + timedelta(days=i)
                self.assertEqual(self.tick(hora, Gravador(erro))['criados'], 1)
                e = self.envios()[-1]
                self.assertEqual(e['status'], 'erro')
                self.assertSemDadoPessoal(e['motivo'])
                self.assertNotIn('00000-0001', e['motivo'])
                if esperado:
                    self.assertEqual(e['motivo'], esperado)
                else:
                    self.assertTrue(e['motivo'])
        self.assertSemDadoPessoal(json.dumps(self.envios()))

    def test_erro_nao_bloqueia_repeticao(self):
        D.atualizar_regra(self.con, self.r['id'], {'ordem': 'desconto'})
        with self.con:
            self.con.execute("UPDATE items SET desconto='-90%' WHERE id=1")
        self.tick(SEGUNDA.replace(hour=9), Gravador(D.ErroEnvio('x')))
        self.tick(SEGUNDA.replace(hour=18), Gravador())
        self.assertEqual([(e['item_pk'], e['status']) for e in self.envios()], [(1, 'erro'), (1, 'enviado')])

    def test_template_apagado_grava_aviso(self):
        self.gravar_templates({'Template 1': DEFAULT_TEMPLATES['Template 1']})
        self.assertEqual(self.tick(SEGUNDA.replace(hour=9))['criados'], 0)
        r = D.obter_regra(self.con, self.r['id'])
        self.assertIn('Template 2', r['aviso'])
        self.gravar_templates({'Template 2': '*{TITULO_PRODUTO}*'})   # volta, mas sem {LINK}
        self.assertEqual(self.tick(SEGUNDA.replace(hour=9, minute=1))['criados'], 0)
        self.gravar_templates(DEFAULT_TEMPLATES)
        self.assertEqual(self.tick(SEGUNDA.replace(hour=9, minute=2))['criados'], 1)
        self.assertEqual(D.obter_regra(self.con, self.r['id'])['aviso'], '')

    def test_regra_pausada_e_numero_desativado_nao_disparam(self):
        D.atualizar_regra(self.con, self.r['id'], {'ativa': 0})
        self.assertEqual(self.tick(SEGUNDA.replace(hour=9))['criados'], 0)
        D.atualizar_regra(self.con, self.r['id'], {'ativa': 1})
        D.atualizar_numero(self.con, self.n['id'], {'ativo': 0})
        self.assertEqual(self.tick(SEGUNDA.replace(hour=9, minute=1))['criados'], 0)
        self.assertEqual(self.envios(), [])

    def test_regra_pausada_depois_da_listagem_do_tick(self):
        regra = D.obter_regra(self.con, self.r['id'])   # o tick listou a regra ativa...
        D.atualizar_regra(self.con, self.r['id'], {'ativa': 0})   # ...e o dono pausou antes do processamento
        self.assertEqual(D.processar_slot(self.con, regra, '2026-11-02T09:00', SEGUNDA.replace(hour=9),
                                          D.TransporteManual(), AFILIADO, so_ativa=True), [])
        self.assertEqual(self.envios(), [])

    def test_s1_template_com_link_comum_grava_aviso_e_loga_contagem(self):
        self.gravar_templates({**DEFAULT_TEMPLATES, 'Template 2': '{TITULO_PRODUTO}\n{LINK}\nSiga promo.pt'})
        with self.assertLogs('disparo', level='INFO') as logs:
            self.assertEqual(self.tick(SEGUNDA.replace(hour=9))['criados'], 0)
        self.assertIn('link que não é', D.obter_regra(self.con, self.r['id'])['aviso'])
        self.assertTrue(any('recusada(s)' in l for l in logs.output))
        self.assertSemDadoPessoal('\n'.join(logs.output))
        self.gravar_templates(DEFAULT_TEMPLATES)
        self.assertEqual(self.tick(SEGUNDA.replace(hour=9, minute=1))['criados'], 1)
        self.assertEqual(D.obter_regra(self.con, self.r['id'])['aviso'], '')

    def test_s2_campos_no_teto_cheios_de_cifrao_crase_nao_estouram(self):
        """S2 parcial: $` expande o texto a cada campo; o tick e a prévia têm de abortar a montagem cedo."""
        teto = {'titulo': 500, 'preco': 200, 'preco_antigo': 200, 'desconto': 200, 'vendas': 200, 'frete': 200,
                'cupom': 200}
        with self.con:
            self.con.execute('DELETE FROM items')
        hostil = self.item(**{c: ('$`' * n)[:n] for c, n in teto.items()})
        bom = self.item()
        tpl = ('{TITULO_PRODUTO} {PRECO_PRODUTO}\n{PRECO_ANTIGO} {DESCONTO_PRODUTO}\n'
               '{NUMERO_VENDAS} {FRETE}\n{CUPOM}\n{LINK}')
        self.gravar_templates({**DEFAULT_TEMPLATES, 'Template 2': tpl})
        D.atualizar_regra(self.con, self.r['id'], {'por_disparo': 2})
        # a prévia antes: depois do tick, o item bom fica bloqueado como repetido (CA5)
        for nome, rodar in (('previa', lambda: D.previa(self.con, self.dados_regra(self.n['id']), 5, SEGUNDA,
                                                        AFILIADO)),
                            ('tick', lambda: self.tick(SEGUNDA.replace(hour=9)))):
            with self.subTest(nome):
                tracemalloc.start()
                try:
                    inicio = time.monotonic()
                    res = rodar()
                    demora = time.monotonic() - inicio
                    pico = tracemalloc.get_traced_memory()[1]
                finally:
                    tracemalloc.stop()
                self.assertLess(demora, 0.5)
                self.assertLess(pico, 20 * 1024 * 1024, f'pico de {pico // 1024} kB')
                if nome == 'previa':
                    self.assertEqual([x['item_pk'] for x in res], [bom])
        self.assertEqual([e['item_pk'] for e in self.envios()], [bom])

    # ---- rodada 4 (Q1): por que a regra não mandou nada
    def aviso(self):
        return D.obter_regra(self.con, self.r['id'])['aviso']

    def test_q1_aviso_quando_nada_casa_com_os_filtros(self):
        for i, mudanca in enumerate(({'cats': ['Aba renomeada']}, {'lojas': ['ml']}, {'palavras': ['inexistente']},
                                     {'desconto_min': 95})):
            with self.subTest(mudanca=mudanca):
                D.atualizar_regra(self.con, self.r['id'], {'cats': ['Eletrônicos'], 'lojas': ['amazon', 'ml'],
                                                           'palavras': [], 'desconto_min': 0, **mudanca})
                self.assertEqual(D.disparar_agora(self.con, self.r['id'], SABADO + timedelta(minutes=i),
                                                  D.TransporteManual(), AFILIADO), [])
                self.assertEqual(self.aviso(), D.AVISO_FILTROS)
        D.atualizar_regra(self.con, self.r['id'], {'cats': ['Aba renomeada']})
        self.assertEqual(self.tick(SEGUNDA.replace(hour=9))['criados'], 0)   # o tick também avisa
        self.assertEqual(self.aviso(), D.AVISO_FILTROS)

    def test_q1_aviso_quando_tudo_ja_foi_enviado_no_prazo(self):
        D.atualizar_regra(self.con, self.r['id'], {'por_disparo': 10, 'max_por_dia': 200})
        self.assertEqual(self.tick(SEGUNDA.replace(hour=9), Gravador())['criados'], 8)
        self.assertEqual(self.aviso(), '')
        self.assertEqual(self.tick(SEGUNDA.replace(hour=18), Gravador())['criados'], 0)
        self.assertEqual(self.aviso(), D.AVISO_REPETICAO)

    def test_q1_aviso_de_link_recusado_tem_prioridade_certa(self):
        with self.con:   # os 8 itens casam e estão livres, mas todo título tem um "domínio"
            self.con.execute("UPDATE items SET titulo = titulo || ' i.Phone'")
        self.assertEqual(self.tick(SEGUNDA.replace(hour=9))['criados'], 0)
        self.assertEqual(self.aviso(), D.AVISO_LINK)

    def test_q1_limite_do_dia_atingido_nao_gera_aviso(self):
        D.atualizar_regra(self.con, self.r['id'], {'max_por_dia': 1})
        self.assertEqual(self.tick(SEGUNDA.replace(hour=9))['criados'], 1)
        self.assertEqual(self.tick(SEGUNDA.replace(hour=18))['criados'], 0)
        self.assertEqual(self.aviso(), '')

    def test_q1_aviso_some_quando_o_slot_seguinte_manda(self):
        D.atualizar_regra(self.con, self.r['id'], {'cats': ['Aba nova']})
        self.tick(SEGUNDA.replace(hour=9))
        self.assertEqual(self.aviso(), D.AVISO_FILTROS)
        self.item(cat='Aba nova')   # sem mexer na regra (salvar a regra também limparia o aviso)
        self.assertEqual(self.tick(SEGUNDA.replace(hour=18))['criados'], 1)
        self.assertEqual(self.aviso(), '')

    def test_q1_recusados_do_ultimo_processamento(self):
        D.atualizar_regra(self.con, self.r['id'], {'por_disparo': 3})
        with self.con:
            self.con.execute("UPDATE items SET titulo = titulo || ' 55UN85CBPSA.BWZ' WHERE id IN (1, 2)")
        self.assertEqual(self.tick(SEGUNDA.replace(hour=9))['criados'], 3)
        self.assertEqual(self.aviso(), '', 'só parte recusada: sem aviso, só a contagem')
        self.assertEqual(D.RECUSADOS[self.r['id']], 2)
        D.excluir_regra(self.con, self.r['id'])
        self.assertNotIn(self.r['id'], D.RECUSADOS)

    def test_ca4_no_disparo(self):
        with self.con:
            self.con.execute("UPDATE items SET url='https://www.amazon.com.br/dp/B0X' WHERE id<8")
        self.gravar_templates({**DEFAULT_TEMPLATES, 'Template 2': DEFAULT_TEMPLATES['Template 2']})
        D.atualizar_regra(self.con, self.r['id'], {'por_disparo': 5})
        self.tick(SEGUNDA.replace(hour=9))
        self.assertEqual([e['item_pk'] for e in self.envios()], [8])

    def test_expira_pendentes_de_dias_anteriores(self):
        self.tick(SEGUNDA.replace(hour=9))
        self.tick(SEGUNDA.replace(hour=18))
        res = self.tick((SEGUNDA + timedelta(days=1)).replace(hour=8))
        self.assertEqual(res['expirados'], 2)
        self.assertEqual([e['status'] for e in self.envios()], ['expirado', 'expirado'])
        self.tick((SEGUNDA + timedelta(days=1)).replace(hour=9))
        self.assertEqual([e['status'] for e in self.envios()], ['expirado', 'expirado', 'pendente'])
        self.assertEqual(self.tick((SEGUNDA + timedelta(days=1)).replace(hour=10))['expirados'], 0)

    def test_duas_threads_no_mesmo_slot(self):
        D.atualizar_regra(self.con, self.r['id'], {'por_disparo': 2})
        self.duas_threads()
        self.assertEqual(len(self.envios()), 2)

    def test_duas_threads_sem_o_lock_do_modulo(self):
        """Outro processo não divide o _LOCK: o BEGIN IMMEDIATE e a checagem do slot bastam."""
        D.atualizar_regra(self.con, self.r['id'], {'por_disparo': 2})
        with mock.patch.object(D, '_LOCK', contextlib.nullcontext()):
            self.duas_threads()
        self.assertEqual(len(self.envios()), 2)

    def duas_threads(self):
        regra = D.obter_regra(self.con, self.r['id'])
        barreira, resultados, erros = threading.Barrier(2), [], []

        def rodar():
            con = self.conectar()
            try:
                barreira.wait()
                resultados.append(len(D.processar_slot(con, regra, '2026-11-02T09:00', SEGUNDA.replace(hour=9),
                                                       D.TransporteManual(), AFILIADO)))
            except Exception as e:   # noqa: BLE001
                erros.append(e)
            finally:
                con.close()
        ts = [threading.Thread(target=rodar) for _ in range(2)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(30)
        self.assertEqual(erros, [])
        self.assertEqual(sorted(resultados), [0, 2])

    def test_trocar_transporte_nao_mexe_na_regra(self):
        antes = D.obter_regra(self.con, self.r['id'])
        self.tick(SEGUNDA.replace(hour=9), D.TransporteManual())
        self.tick(SEGUNDA.replace(hour=18), Gravador())
        self.assertEqual(D.obter_regra(self.con, self.r['id']), antes)
        self.assertEqual([e['transporte'] for e in self.envios()], ['manual', 'gravador'])


class DispararAgora(Base):
    def setUp(self):
        super().setUp()
        self.n = self.numero(limite_diario=3)
        self.r = self.regra(numero_id=self.n['id'], por_disparo=2, max_por_dia=10)
        for _ in range(6):
            self.item()

    def test_fora_do_horario_e_com_regra_pausada(self):
        D.atualizar_regra(self.con, self.r['id'], {'ativa': 0})
        envios = D.disparar_agora(self.con, self.r['id'], SABADO.replace(hour=3), D.TransporteManual(), AFILIADO)
        self.assertEqual([e['status'] for e in envios], ['pendente', 'pendente'])
        self.assertTrue(envios[0]['slot'].startswith('agora '))

    def test_respeita_limites_e_repeticao(self):
        agora = SABADO.replace(hour=3)
        a = D.disparar_agora(self.con, self.r['id'], agora, D.TransporteManual(), AFILIADO)
        self.assertEqual(D.disparar_agora(self.con, self.r['id'], agora, D.TransporteManual(), AFILIADO), [],
                         'clique duplo no mesmo segundo')
        b = D.disparar_agora(self.con, self.r['id'], agora + timedelta(seconds=1), D.TransporteManual(), AFILIADO)
        c = D.disparar_agora(self.con, self.r['id'], agora + timedelta(seconds=2), D.TransporteManual(), AFILIADO)
        self.assertEqual((len(a), len(b), len(c)), (2, 1, 0))   # limite_diario 3
        pks = [e['item_pk'] for e in a + b]
        self.assertEqual(len(set(pks)), 3)

    def test_regra_inexistente(self):
        with self.assertRaises(D.ErroDisparo) as cm:
            D.disparar_agora(self.con, 99, SABADO, D.TransporteManual(), AFILIADO)
        self.assertEqual(cm.exception.codigo, 404)


class FilaEHistorico(Base):
    def setUp(self):
        super().setUp()
        self.r = self.regra()
        self.pks = [self.item() for _ in range(6)]

    def criar(self, status, quando=SEGUNDA):
        pk = self.pks.pop(0)
        self.envio_antigo(self.r, pk, status, quando)
        return self.con.execute('SELECT id FROM envios WHERE item_pk=?', (pk,)).fetchone()[0]

    def test_transicoes(self):
        pend, inc, err, err2, env = (self.criar(s) for s in ('pendente', 'incerto', 'erro', 'erro', 'enviado'))
        e = D.marcar_envio(self.con, pend, 'enviado', SEGUNDA.replace(hour=10))
        self.assertEqual((e['status'], e['enviado_em']), ('enviado', '2026-11-02T10:00:00'))
        self.assertEqual(D.marcar_envio(self.con, inc, 'pulado')['status'], 'pulado')
        self.assertEqual(D.marcar_envio(self.con, err, 'pulado')['status'], 'pulado')
        for eid, st in ((env, 'pulado'), (env, 'enviado'), (pend, 'pulado'), (err2, 'enviado')):
            with self.subTest(eid=eid, st=st), self.assertRaises(D.ErroDisparo) as cm:
                D.marcar_envio(self.con, eid, st)
            self.assertEqual(cm.exception.codigo, 409)
        for st in ('erro', 'pendente', 'expirado', None):
            with self.subTest(st=st), self.assertRaises(D.ErroDisparo) as cm:
                D.marcar_envio(self.con, pend, st)
            self.assertEqual(cm.exception.codigo, 400)
        with self.assertRaises(D.ErroDisparo) as cm:
            D.marcar_envio(self.con, 999, 'enviado')
        self.assertEqual(cm.exception.codigo, 404)

    def test_fila_do_mais_antigo_ao_mais_novo(self):
        b = self.criar('pendente', SEGUNDA.replace(hour=10))
        a = self.criar('incerto', SEGUNDA.replace(hour=9))
        self.criar('enviado')
        self.criar('erro')
        self.assertEqual([e['id'] for e in D.listar_fila(self.con)], [a, b])

    def test_historico_por_periodo_e_status(self):
        velho = self.criar('enviado', SEGUNDA - timedelta(days=3))
        novo = self.criar('erro', SEGUNDA)
        meio = self.criar('enviado', SEGUNDA - timedelta(days=1))
        self.assertEqual([e['id'] for e in D.listar_envios(self.con)], [novo, meio, velho])
        self.assertEqual([e['id'] for e in D.listar_envios(self.con, desde='2026-11-01')], [novo, meio])
        self.assertEqual([e['id'] for e in D.listar_envios(self.con, status='enviado')], [meio, velho])
        self.assertEqual(len(D.listar_envios(self.con, limite=1)), 1)
        for kw in ({'desde': '2026-13-01'}, {'desde': '01/11/2026'}, {'desde': '2026-11-01T00'},
                   {'status': 'x'}, {'desde': 20261101}):
            with self.subTest(kw=kw), self.assertRaises(D.ErroDisparo):
                D.listar_envios(self.con, **kw)


class Transportes(unittest.TestCase):
    def test_manual(self):
        t = D.TransporteManual()
        self.assertEqual((t.nome, t.automatico, t.enviar({}, 'x', None)), ('manual', False, None))

    def test_falso_grava_jsonl_sem_dado_pessoal(self):
        arq = os.path.join(tempfile.mkdtemp(dir=TMP), 'envios.jsonl')
        t = D.TransporteFalso(arq)
        self.assertEqual((t.nome, t.automatico), ('falso', True))
        destino = {'telefone': TELEFONE, 'grupo_id': GRUPO_ID, 'grupo_nome': 'Achadinhos'}
        t.enviar(destino, 'oi https://meli.la/x', 'https://http2.mlstatic.com/a.webp')
        t.enviar(destino, 'sem foto', None)
        with open(arq, encoding='utf-8') as f:
            conteudo = f.read()
        self.assertEqual([json.loads(l) for l in conteudo.splitlines()],
                         [{'grupo_nome': 'Achadinhos', 'texto': 'oi https://meli.la/x',
                           'imagem_url': 'https://http2.mlstatic.com/a.webp'},
                          {'grupo_nome': 'Achadinhos', 'texto': 'sem foto', 'imagem_url': None}])
        self.assertNotIn(TELEFONE, conteudo)
        self.assertNotIn(GRUPO_ID, conteudo)
        with self.assertRaises(D.ErroEnvio):
            D.TransporteFalso(arq, falhar=True).enviar(destino, 'x', None)

    def test_escolha_pelo_ambiente(self):
        self.assertIsInstance(D.transporte_do_ambiente({}), D.TransporteManual)
        self.assertIsInstance(D.transporte_do_ambiente({'ACHADINHOS_TRANSPORTE': 'manual'}), D.TransporteManual)
        t = D.transporte_do_ambiente({'ACHADINHOS_TRANSPORTE': 'falso', 'ACHADINHOS_TRANSPORTE_ARQUIVO': '/tmp/x'})
        self.assertEqual((type(t), t.arquivo), (D.TransporteFalso, '/tmp/x'))
        for env in ({'ACHADINHOS_TRANSPORTE': 'falso'}, {'ACHADINHOS_TRANSPORTE': 'baileys'}):
            with self.subTest(env=env), self.assertRaises(ValueError):
                D.transporte_do_ambiente(env)

    def test_motivo_seguro(self):
        destino = {'telefone': TELEFONE, 'grupo_id': GRUPO_ID}
        self.assertEqual(D.motivo_seguro(D.ErroEnvio('número desconectado'), destino), 'número desconectado')
        self.assertEqual(D.motivo_seguro(ValueError(TELEFONE), destino), 'ValueError')
        for m in (f'tel {TELEFONE}', f'grupo {GRUPO_ID}', 'outro 999999999999-123456@g.us', '+55 00 00000-0001'):
            with self.subTest(m=m):
                r = D.motivo_seguro(D.ErroEnvio(m), destino)
                self.assertNotRegex(r, r'\d{5}')
        self.assertEqual(len(D.motivo_seguro(D.ErroEnvio('x' * 500), destino)), 200)


def esperar(cond, segundos=10):
    fim = time.monotonic() + segundos
    while not cond():
        if time.monotonic() > fim:
            raise AssertionError('tempo esgotado')
        time.sleep(0.01)


class AgendadorThread(Base):
    def setUp(self):
        super().setUp()
        self.n = self.numero()
        self.r = self.regra(numero_id=self.n['id'])
        self.pk = self.item()

    def agendador(self, transporte, relogio, intervalo=60, conectar=None):
        ag = D.Agendador(conectar or self.conectar, AFILIADO, transporte, intervalo=intervalo, relogio=relogio)
        self.addCleanup(lambda: (ag.parar(), ag.join(5)))
        return ag

    def test_enviando_vira_incerto_no_inicio_e_nao_e_reenviado(self):
        self.envio_antigo(self.r, self.pk, 'enviando', SEGUNDA.replace(hour=9), slot='2026-11-02T09:00')
        t = Gravador()
        ag = self.agendador(t, lambda: SEGUNDA.replace(hour=9, minute=3))
        with self.assertLogs('disparo', level='WARNING') as logs:
            ag.start()
            esperar(lambda: ag.ticks >= 1)
        self.assertEqual(logs.output, ['WARNING:disparo:disparo: 1 envio(s) interrompido(s) marcado(s) como incerto'])
        self.assertEqual([e['status'] for e in self.envios()], ['incerto'])
        self.assertEqual(t.chamadas, [])
        self.assertEqual([e['status'] for e in D.listar_fila(self.con)], ['incerto'])

    def test_loop_estado_e_log_so_com_contagens(self):
        arq = os.path.join(self.dir, 'envios.jsonl')
        relogio = iter([SEGUNDA.replace(hour=9, minute=1)] + [SEGUNDA.replace(hour=9, minute=2)] * 1000)
        ag = self.agendador(D.TransporteFalso(arq), lambda: next(relogio), intervalo=0.01)
        self.assertEqual(ag.estado()['agendador'], 'desligado')
        with self.assertLogs('disparo', level='INFO') as logs:
            ag.start()
            esperar(lambda: ag.ticks >= 3)
        est = ag.estado()
        self.assertEqual((est['agendador'], est['transporte']), ('ligado', 'falso'))
        self.assertEqual(est['ultimo_tick'], '2026-11-02T09:02:00')
        with open(arq, encoding='utf-8') as f:
            self.assertEqual(len(f.read().splitlines()), 1)
        self.assertEqual([e['status'] for e in self.envios()], ['enviado'])
        self.assertIn('1 envio(s) criado(s)', '\n'.join(logs.output))
        self.assertSemDadoPessoal('\n'.join(logs.output))
        ag.parar(); ag.join(5)
        self.assertFalse(ag.is_alive())
        self.assertEqual(ag.estado()['agendador'], 'desligado')

    def test_erro_no_tick_loga_so_o_tipo(self):
        def conectar_quebrado():
            raise sqlite3.OperationalError(f'falhou com {TELEFONE} e {GRUPO_ID}')
        ag = self.agendador(D.TransporteManual(), lambda: SEGUNDA.replace(hour=9), intervalo=0.01,
                            conectar=conectar_quebrado)
        with self.assertLogs('disparo', level='WARNING') as logs:
            ag.start()
            esperar(lambda: ag.ticks >= 2)
        saida = '\n'.join(logs.output)
        self.assertIn('OperationalError', saida)
        self.assertSemDadoPessoal(saida)
        self.assertTrue(ag.is_alive(), 'o agendador continua vivo depois do erro')

    def test_erro_numa_regra_nao_para_as_outras(self):
        outra = self.regra(numero_id=self.n['id'], nome='Outra')
        self.item()
        original = D.processar_slot

        def quebra_a_primeira(con, regra, *a, **kw):
            if regra['id'] == self.r['id']:
                raise sqlite3.OperationalError(TELEFONE)
            return original(con, regra, *a, **kw)
        with mock.patch.object(D, 'processar_slot', quebra_a_primeira):
            res = self.tick(SEGUNDA.replace(hour=9))
        self.assertEqual((res['criados'], res['erros']), (1, ['OperationalError']))
        self.assertEqual([e['regra_id'] for e in self.envios()], [outra['id']])


class Slots(unittest.TestCase):
    def test_slots_devidos(self):
        r = {'dias': [0], 'horarios': ['09:00', '09:05', '09:20', '23:59']}
        self.assertEqual(D.slots_devidos(r, SEGUNDA.replace(hour=9, minute=10)), ['2026-11-02T09:00', '2026-11-02T09:05'])
        self.assertEqual(D.slots_devidos(r, SEGUNDA.replace(hour=9, minute=10, second=1)), ['2026-11-02T09:05'])
        self.assertEqual(D.slots_devidos(r, SEGUNDA.replace(hour=8, minute=59)), [])
        self.assertEqual(D.slots_devidos(r, SEGUNDA.replace(hour=23, minute=59, second=59)), ['2026-11-02T23:59'])
        self.assertEqual(D.slots_devidos(r, (SEGUNDA + timedelta(days=1)).replace(hour=9, minute=1)), [])



# ================================================================ etapa 4: rota e ambiente
class Rotas(Base):
    """disparo.rota sem HTTP: cada caminho do plano, 404, 405 e ids."""

    def rota(self, metodo, resto, corpo=None, query=None, transporte=None, agendador=None, agora=SEGUNDA):
        return D.rota(self.con, metodo, D.PREFIXO + resto, query or {}, corpo, AFILIADO,
                      transporte or D.TransporteManual(), agendador, agora=agora)

    def erro(self, codigo, *a, **kw):
        with self.assertRaises(D.ErroDisparo) as cm:
            self.rota(*a, **kw)
        self.assertEqual(cm.exception.codigo, codigo, cm.exception.msg)
        return cm.exception

    def test_numeros(self):
        n = self.rota('POST', 'numeros', {'nome': 'Loja 1', 'telefone': TELEFONE, 'grupo_nome': 'G'})
        self.assertEqual(n['telefone'], TELEFONE)   # inteiro para o formulário; a tela mascara
        self.assertEqual(self.rota('GET', 'numeros'), [n])
        self.assertEqual(self.rota('PUT', f'numeros/{n["id"]}', {'nome': 'Loja 2'})['nome'], 'Loja 2')
        self.assertEqual(self.rota('DELETE', f'numeros/{n["id"]}'), {'ok': True})
        self.erro(404, 'DELETE', f'numeros/{n["id"]}')

    def test_regras_com_proximo(self):
        nid = self.numero()['id']
        r = self.rota('POST', 'regras', self.dados_regra(nid), agora=SEGUNDA.replace(hour=10))
        self.assertEqual(r['proximo'], '2026-11-02T18:00')
        self.assertEqual([x['proximo'] for x in self.rota('GET', 'regras', agora=SEGUNDA.replace(hour=19))],
                         ['2026-11-03T09:00'])
        self.assertEqual(self.rota('GET', 'regras', agora=SABADO)[0]['proximo'], '2026-11-09T09:00')
        p = self.rota('PUT', f'regras/{r["id"]}', {'ativa': 0})
        self.assertIsNone(p['proximo'])
        self.assertEqual(self.rota('DELETE', f'regras/{r["id"]}'), {'ok': True})
        self.assertEqual(self.rota('GET', 'regras'), [])

    def test_agora_previa_fila_envios_status(self):
        nid = self.numero()['id']
        r = self.rota('POST', 'regras', self.dados_regra(nid, por_disparo=2))
        for _ in range(3):
            self.item()
        p = self.rota('POST', 'previa', {**self.dados_regra(nid), 'n': 3})
        self.assertEqual(len(p), 3)
        self.assertEqual(self.envios(), [])
        res = self.rota('POST', f'regras/{r["id"]}/agora', agora=SABADO)
        self.assertEqual((res['criados'], [e['status'] for e in res['envios']]), (2, ['pendente', 'pendente']))
        fila = self.rota('GET', 'fila')
        self.assertEqual([e['id'] for e in fila], [e['id'] for e in res['envios']])
        e = self.rota('PATCH', f'envios/{fila[0]["id"]}', {'status': 'enviado'}, agora=SABADO)
        self.assertEqual(e['status'], 'enviado')
        self.erro(409, 'PATCH', f'envios/{fila[0]["id"]}', {'status': 'pulado'})
        for corpo in (None, [], {'status': []}, {'status': 'erro'}):
            with self.subTest(corpo=corpo):
                self.erro(400, 'PATCH', f'envios/{fila[1]["id"]}', corpo)
        self.assertEqual([x['status'] for x in self.rota('GET', 'envios', query={'status': 'enviado'})], ['enviado'])
        self.assertEqual(len(self.rota('GET', 'envios', query={'desde': '2026-11-07'})), 2)
        self.erro(400, 'GET', 'envios', query={'desde': 'ontem'})
        self.assertEqual(self.rota('GET', 'status'),
                         {'agendador': 'desligado', 'transporte': 'manual', 'ultimo_tick': None})

    def test_previa_padrao_e_corpo_invalido(self):
        nid = self.numero()['id']
        for _ in range(7):
            self.item()
        self.assertEqual(len(self.rota('POST', 'previa', self.dados_regra(nid))), D.PREVIA_PADRAO)
        for corpo in (None, [], 'x'):
            with self.subTest(corpo=corpo):
                self.erro(400, 'POST', 'previa', corpo)
        self.erro(400, 'POST', 'previa', {**self.dados_regra(nid), 'n': 21})

    def test_status_com_agendador(self):
        ag = D.Agendador(self.conectar, AFILIADO, D.TransporteFalso(os.path.join(self.dir, 'x.jsonl')))
        self.assertEqual(self.rota('GET', 'status', agendador=ag)['transporte'], 'falso')

    def test_404_e_405(self):
        for resto in ('', 'x', 'numeros/0', 'numeros/01', 'numeros/abc', 'numeros/1/', 'regras/1/agora/x',
                      'numeros/' + '9' * 19, 'envios/-1', 'numeros%2F1', 'regras/1/previa'):
            with self.subTest(resto=resto):
                self.erro(404, 'GET', resto)
        for metodo, resto in (('DELETE', 'numeros'), ('PATCH', 'regras'), ('GET', 'regras/1/agora'),
                              ('GET', 'previa'), ('POST', 'fila'), ('GET', 'envios/1'), ('POST', 'status'),
                              ('GET', 'numeros/1')):
            with self.subTest(metodo=metodo, resto=resto):
                self.erro(405, metodo, resto)
        with self.assertRaises(D.ErroDisparo):
            D.rota(self.con, 'GET', '/api/items', {}, None, AFILIADO, D.TransporteManual())

    def test_r5_proximo_nulo_com_numero_desativado(self):
        n = self.numero()
        r = self.rota('POST', 'regras', self.dados_regra(n['id']), agora=SEGUNDA)
        self.assertEqual(r['proximo'], '2026-11-02T09:00')
        self.rota('PUT', f'numeros/{n["id"]}', {'ativo': 0})
        self.assertIsNone(self.rota('GET', 'regras')[0]['proximo'])
        self.assertIsNone(self.rota('PUT', f'regras/{r["id"]}', {'nome': 'X'})['proximo'])
        self.rota('PUT', f'numeros/{n["id"]}', {'ativo': 1})
        self.assertEqual(self.rota('GET', 'regras')[0]['proximo'], '2026-11-02T09:00')

    def test_q1_recusados_na_listagem_e_na_previa(self):
        D.RECUSADOS.clear()
        n = self.numero()
        r = self.rota('POST', 'regras', self.dados_regra(n['id'], por_disparo=3))
        self.assertEqual(r['recusados'], 0)
        self.item(), self.item()
        self.item(titulo='Capa i.Phone 15')
        res = self.rota('POST', f'regras/{r["id"]}/agora', {}, agora=SABADO)
        self.assertEqual(res['criados'], 2)
        self.assertEqual(self.rota('GET', 'regras')[0]['recusados'], 1)
        self.assertEqual(self.rota('PUT', f'regras/{r["id"]}', {'nome': 'X'})['recusados'], 1)
        corpo = {**self.dados_regra(n['id']), 'n': 5}
        lista = self.rota('POST', 'previa', corpo, agora=SABADO)   # a tela atual: lista, como antes
        self.assertIsInstance(lista, list)
        com = self.rota('POST', 'previa', {**corpo, 'com_info': True}, agora=SABADO)
        self.assertEqual(com['recusados'], 1)
        self.assertEqual(com['itens'], lista)
        self.assertEqual(self.rota('POST', 'previa', {**corpo, 'com_info': 1}, agora=SABADO), lista)
        info = {}
        D.previa(self.con, self.dados_regra(n['id']), 5, SEGUNDA, AFILIADO, info=info)
        self.assertEqual(info, {'recusados': 1})

    def test_404_de_id_inexistente(self):
        for metodo, resto, corpo in (('PUT', 'numeros/5', {}), ('PUT', 'regras/5', {}), ('DELETE', 'regras/5', None),
                                     ('POST', 'regras/5/agora', None), ('PATCH', 'envios/5', {'status': 'pulado'})):
            with self.subTest(resto=resto):
                self.erro(404, metodo, resto, corpo)


class Ambiente(unittest.TestCase):
    def test_agendador_ligado(self):
        self.assertTrue(D.agendador_ligado({}))
        self.assertTrue(D.agendador_ligado({'ACHADINHOS_DISPARO': '1'}))
        self.assertFalse(D.agendador_ligado({'ACHADINHOS_DISPARO': '0'}))
        self.assertFalse(D.agendador_ligado({'ACHADINHOS_DISPARO': ' 0 '}))

    def test_intervalo(self):
        self.assertEqual(D.intervalo_do_ambiente({}), 30)
        self.assertEqual(D.intervalo_do_ambiente({'ACHADINHOS_TICK_SEG': '1'}), 1)
        for v in ('0', '-1', 'abc', '3601', 'nan'):
            with self.subTest(v=v), self.assertRaises(ValueError):
                D.intervalo_do_ambiente({'ACHADINHOS_TICK_SEG': v})

    def test_proximo_horario(self):
        r = {'ativa': 1, 'dias': [2], 'horarios': ['18:00', '09:00']}   # só quarta
        self.assertEqual(D.proximo_horario(r, SEGUNDA), '2026-11-04T09:00')
        self.assertEqual(D.proximo_horario(r, datetime(2026, 11, 4, 9, 0)), '2026-11-04T09:00')
        self.assertEqual(D.proximo_horario(r, datetime(2026, 11, 4, 18, 0, 1)), '2026-11-11T09:00')
        self.assertIsNone(D.proximo_horario({**r, 'ativa': 0}, SEGUNDA))

if __name__ == '__main__':
    logging.getLogger('disparo').setLevel(logging.INFO)
    unittest.main()
