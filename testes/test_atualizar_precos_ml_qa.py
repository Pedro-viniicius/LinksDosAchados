#!/usr/bin/env python3
"""QA da fonte `ml` do atualizar_precos.py (docs/produto/planos/api-oficial-ml-catalogo.md, etapa 3: CA4, CA5, CA6
e CA8).

Uso:  http_proxy=http://127.0.0.1:9 https_proxy=http://127.0.0.1:9 python3 testes/test_atualizar_precos_ml_qa.py -v

Estende o test_atualizar_precos_ml.py sem duplicar: url hostil no banco e link trocado no meio da rodada, colunas
comparadas byte a byte (quote() do SQLite, que separa NULL de ''), item apagado no meio, anúncios da resposta que
não estão no banco, preço do vencedor e de outro anúncio nosso em outro produto, páginas 2 a 4 da lista, linha
repetida ou com id parecido, preços e moedas hostis (NaN, Infinity, bool, lista, subnormal), renovação recusada
pelo 401 do GET (e não pelo relógio) no vínculo e nas ofertas, sem Secret no meio, invalid_grant e renovação fora
do formato no meio, Limite no 2º lote e no vínculo além de 20, rede e Ctrl+C no meio, teto exato, limites dos
argumentos, ordem leitura → GET → gravação do cache, arquivo de vínculos symlink, grande e fora do formato, tabela
config e esquema intactos e toda linha da saída conferida contra uma lista fechada de formatos. Rodada 2: Ctrl+C,
erro e banco travado no meio da página (commit por item), nenhum GET com o banco travado, outra conexão escrevendo em
paralelo, o servidor.py de verdade mexendo no meio da rodada, mensagem do teto no vínculo e metade do teto.

Nenhum teste fala com o Mercado Livre: MLFalso atrás do OpenerFalso, proxies mortos (fixados no import do
test_ml_api) e todos os arquivos (banco, tokens, vínculos, buscas.json e progresso) numa pasta temporária. Só o
QaServidorDeVerdade abre socket, em 127.0.0.1, com o servidor.py sobre o banco temporário do teste. No fim
do módulo, confere que o ml_catalogo.json da raiz e o atualizar_precos_feitos.txt real não mudaram.
"""
import hashlib
import http.client
import json
import os
import re
import socket
import sqlite3
import subprocess
import threading
import time
import unicodedata
import sys
import tempfile
import unittest
import urllib.error
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_atualizar_precos_ml as TM   # noqa: E402  (importa test_ml_api: proxies mortos e pastas temporárias)

T, TC, M, A, S = TM.T, TM.TC, TM.M, TM.A, TM.S
RAIZ = TM.RAIZ
mlb, pid, titulo, linha_lista = TM.mlb, TM.pid, TM.titulo, TM.linha_lista
CEL, CASA, LINK, OUTRO, ANTIGO = TM.CEL, TM.CASA, TM.LINK, TM.OUTRO, TM.ANTIGO
assert all(os.path.dirname(p) == T.TMP for p in (S.DB, A.FEITOS, M.TOKENS, M.CATALOGO)), \
    'o teste não pode tocar os dados reais'

FEITOS_REAL = os.path.join(RAIZ, 'atualizar_precos_feitos.txt')
# só preco, preco_antigo e desconto mudam; preco_em e atualizado_em são o carimbo da gravação
MUDAM = {'preco', 'preco_antigo', 'desconto', 'preco_em', 'atualizado_em'}
PRECO_API = 4321.98                       # aparece na API, nunca na saída
PRECO_API_TEXTOS = ('4321', '4.321', '321,98', '321.98')
CONTROLE = re.compile(r'[\x00-\x09\x0b-\x1f\x7f-\x9f​-‏ -‮⁠-⁯﻿]')
LINHAS_STDOUT = (
    re.compile(r'\[ml\] vínculos: \d+ itens em \d+ produtos de catálogo, \d+ sem produto; \d+ vieram do cache e \d+ '
               r'foram à API \(\d+ com erro passageiro\); \d+ ficam para a próxima rodada \(--vincular \d+\)\.'),
    re.compile(r'\[ml\] catalogo\|MLB\d{1,19}: \d+ dos selecionados vistos, \d+ atualizados'),
    re.compile(r'\[ml\] ofertas: \d+ anúncios ficaram sem leitura por erro passageiro da API \(não vistos\)\.'),
    re.compile(r'\[ml\] parou no teto de \d+ chamadas \(--max-chamadas\); rode de novo para seguir\.'),
    re.compile(r'\[ml\] vínculo parou na metade do teto; \d+ itens ficam para a próxima rodada\.'),
    re.compile(r'RESUMO ml: \d+ selecionados \(\d+ já confirmados hoje ficaram de fora\); \d+ atualizados, \d+ sem '
               r'preço legível \(dados mantidos\), \d+ fora do piso, \d+ usados, \d+ indisponíveis, \d+ sumidos, '
               r'\d+ não vistos\.'),
    re.compile(r'Não vistos \(até 20\): MLB\d{6,19}(, MLB\d{6,19})*'),
)
MENSAGENS_FIXAS = [str(c()) for c in (M.RefazerAutorizacao, M.SemPermissao, M.Limite, M.ErroRede, M.RenovacaoInvalida,
                                      M.SemRefreshToken, M.RespostaInvalida)] + [A.MSG_SECRET_ML]
LINHAS_STDERR = (
    re.compile('(ERRO|PAROU): (' + '|'.join(re.escape(m) for m in MENSAGENS_FIXAS) + ')'),
    re.compile('ERRO: ' + re.escape(M.RenovacaoFalhou.mensagem) + r'( \[HTTP \d{3}\])?'),
    re.compile(r'ERRO: arquivo de vínculos do catálogo recusado \([^()]{1,80}\)\. Corrija ou apague o arquivo '
               r'\(ml_catalogo\.json ou o de ACHADINHOS_ML_CATALOGO\): os vínculos são refeitos pela API'),
    re.compile(r'ERRO: a API do Mercado Livre recusou: HTTP \d{3}( \([A-Za-z_]{1,64}\)| \(sem código\))'),
    re.compile(r'PAROU: a loja bloqueou \(captcha, 503, 429 ou limite da API\)\. O progresso foi salvo; espere de 15 '
               r'a 30 minutos e rode de novo\.'),
    re.compile(r'PAROU: chegou ao teto de chamadas \(--max-chamadas\); rode de novo para seguir, sem precisar '
               r'esperar\.'),
    re.compile(r'Interrompido\. O progresso das páginas já gravadas foi salvo\.'),
)


def _catalogo_no_projeto():
    """(nome, inode, mtime) do ml_catalogo.json e das sobras .ml_catalogo.json.*.tmp na raiz do projeto."""
    achados = []
    for nome in os.listdir(RAIZ):
        if nome == 'ml_catalogo.json' or (nome.startswith('.ml_catalogo.json.') and nome.endswith('.tmp')):
            info = os.lstat(os.path.join(RAIZ, nome))
            achados.append((nome, info.st_ino, info.st_mtime_ns))
    return sorted(achados)


def _feitos_real():
    """(existe, tamanho, sha256, linhas `ml|`) do atualizar_precos_feitos.txt real; o conteúdo não sai daqui."""
    if not os.path.exists(FEITOS_REAL):
        return (False, 0, None, 0)
    with open(FEITOS_REAL, 'rb') as f:
        bruto = f.read()
    return (True, len(bruto), hashlib.sha256(bruto).hexdigest(),
            sum(1 for l in bruto.splitlines() if l.startswith(b'ml|')))


CATALOGO_NO_PROJETO_ANTES = _catalogo_no_projeto()
FEITOS_REAL_ANTES = _feitos_real()


def tearDownModule():
    TM.tearDownModule()
    # CA6/CA8: nenhum teste desta suíte cria ml_catalogo.json na raiz nem escreve no progresso real
    assert _catalogo_no_projeto() == CATALOGO_NO_PROJETO_ANTES, 'um teste mexeu no ml_catalogo.json do projeto'
    assert _feitos_real() == FEITOS_REAL_ANTES, 'um teste escreveu no atualizar_precos_feitos.txt real'


class Qa(TM.Base):
    # ---------- banco: retratos byte a byte ----------
    def colunas(self):
        con = sqlite3.connect(self.db)
        try:
            return [r[1] for r in con.execute('PRAGMA table_info(items)')]
        finally:
            con.close()

    def retrato(self):
        """{item_id: {coluna: quote(coluna)}}: quote() separa NULL de '' e texto de número."""
        cols = self.colunas()
        con = sqlite3.connect(self.db)
        try:
            sql = 'SELECT item_id, ' + ', '.join(f'quote({c})' for c in cols) + ' FROM items'
            return {r[0]: dict(zip(cols, r[1:])) for r in con.execute(sql)}
        finally:
            con.close()

    def resto_do_banco(self):
        """Tudo fora de items: config, disparo, gênero, sqlite_sequence, esquema e user_version."""
        con = sqlite3.connect(self.db)
        try:
            tabelas = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name<>'items' "
                                                 'ORDER BY name')]
            dados = {t: sorted(map(repr, con.execute(f'SELECT * FROM "{t}"'))) for t in tabelas}
            dados['__esquema__'] = sorted(map(repr, con.execute('SELECT type, name, sql FROM sqlite_master')))
            dados['__user_version__'] = con.execute('PRAGMA user_version').fetchone()[0]
            return dados
        finally:
            con.close()

    def contagem(self):
        con = sqlite3.connect(self.db)
        try:
            return con.execute('SELECT count(*), max(id) FROM items').fetchone()
        finally:
            con.close()

    def sql(self, comando, params=()):
        con = sqlite3.connect(self.db, timeout=30)
        try:
            con.execute(comando, params)
            con.commit()
        finally:
            con.close()

    def assertSoOPrecoMudou(self, antes, depois, iid, url_muda=False):
        for c, v in antes[iid].items():
            if c in MUDAM or (url_muda and c == 'url'):
                continue
            self.assertEqual(depois[iid][c], v, (iid, c))

    # ---------- catálogo ----------
    def em_um_produto(self, ids, p, precos=None, **linha):
        """Os ids vinculados no cache ao produto p (bbw nulo), cada um com a sua linha na lista."""
        self.ml.produtos[p] = TC.prod(p, nulo=True)
        self.ml.listas[p] = [[linha_lista(i, (precos or {}).get(i, PRECO_API), **linha) for i in ids]]
        self.no_cache({i: p for i in ids})

    def um_por_produto(self, n, preco=PRECO_API):
        """n itens no banco, cada um vinculado no cache ao seu produto, com preço válido na lista."""
        ids = []
        for k in range(1, n + 1):
            iid = self.inserir(k)
            self.ml.produtos[pid(k)] = TC.prod(pid(k), nulo=True)
            self.ml.listas[pid(k)] = [[linha_lista(iid, preco)]]
            ids.append(iid)
        self.no_cache({iid: pid(k) for k, iid in enumerate(ids, 1)})
        return ids

    def responder_com(self, antes_do_get=None, token=None):
        """Troca o responder do opener: antes_do_get(chamada, n_get) pode devolver uma resposta/erro ou None."""
        n = [0]

        def gets(c):
            n[0] += 1
            if antes_do_get:
                r = antes_do_get(c, n[0])
                if r is not None:
                    return r
            return self.ml.responder(c)
        self.ml.op.responder = T.api_padrao(gets=gets, token=token)

    def a_partir_da_vez(self, caminho, vez, resposta):
        """Devolve `resposta` (fábrica) da `vez`-ésima chamada exata a `caminho` em diante (o 429 é tentado 3 vezes)."""
        vistas = [0]

        def f(c, _):
            if c.caminho == caminho:
                vistas[0] += 1
                if vistas[0] >= vez:
                    return resposta()
            return None
        return f

    # ---------- saída ----------
    def conferir_saida(self, out, err):
        """Toda linha bate com um formato fechado; título, preço, link, vendedor e token nunca saem."""
        for linha in out.splitlines():
            self.assertTrue(any(r.fullmatch(linha) for r in LINHAS_STDOUT), f'linha fora do formato: {linha!r}')
        for linha in err.splitlines():
            self.assertTrue(any(r.fullmatch(linha) for r in LINHAS_STDERR), f'linha fora do formato: {linha!r}')
        self.assertSemVazamento(out, err)
        for t in (out, err):
            self.assertIsNone(CONTROLE.search(t))
            for p in PRECO_API_TEXTOS:
                self.assertNotIn(p, t)


# ---------- CA4: o meli.la nunca muda, nada é inserido, só o preço muda ----------
class QaLinkEColunas(Qa):
    def test_meli_la_nunca_e_trocado_e_url_hostil_vira_so_a_url_montada_pelo_id(self):
        urls = {1: LINK, 2: 'https://meli.la/Zz9?utm=1#frag', 3: "https://meli.la/x' OR '1'='1", 4: 'https://meli.la/',
                5: 'https://www.mercadolivre.com.br/celular/p/MLB123', 6: 'javascript:alert(1)',
                7: 'https://meli.la.evil.example/x', 8: 'https://evil.example/https://meli.la/x', 9: ''}
        ids = {n: self.inserir(n, url=u) for n, u in urls.items()}
        self.em_um_produto(ids.values(), pid(1))
        antes = self.retrato()
        codigo, out, err = self.rodar()
        self.assertEqual(codigo, 0, err)
        depois = self.retrato()
        for n, iid in ids.items():
            with self.subTest(n=n):
                self.assertEqual(depois[iid]['preco'], "'R$ 4.321,98'")
                if urls[n].startswith('https://meli.la/'):
                    self.assertEqual(depois[iid]['url'], antes[iid]['url'])            # o meli.la fica, byte a byte
                    self.assertSoOPrecoMudou(antes, depois, iid)
                else:
                    # sem afiliado: só a url montada pelo id validado; nada da API (permalink) nem da url antiga
                    self.assertEqual(depois[iid]['url'], f"'https://produto.mercadolivre.com.br/MLB-{iid[3:]}'")
                    self.assertSoOPrecoMudou(antes, depois, iid, url_muda=True)
        self.assertEqual(sum(1 for r in depois.values() if r['url'].startswith("'https://meli.la/")), 4)
        self.conferir_saida(out, err)

    def test_link_trocado_para_meli_la_durante_a_rodada_nao_volta_atras(self):
        a = self.inserir(1, url='https://www.mercadolivre.com.br/x/p/MLB1')
        self.em_um_produto([a], pid(1))

        def afiliar_no_meio(c, _):   # o ColetaML.afiliar() grava o meli.la enquanto a API responde
            if c.caminho == f'/products/{pid(1)}/items':
                self.sql('UPDATE items SET url=? WHERE item_id=?', ('https://meli.la/Novo1', a))
            return None
        self.responder_com(afiliar_no_meio)
        codigo, out, err = self.rodar()
        self.assertEqual(codigo, 0, err)
        self.assertEqual(self.todas()[a]['url'], 'https://meli.la/Novo1')
        self.assertEqual(self.todas()[a]['preco'], 'R$ 4.321,98')

    def test_todas_as_colunas_fora_do_preco_ficam_iguais_byte_a_byte(self):
        estranho = {'titulo': '  Celular Ação​ 128GB 🚀 "aspas" \'simples\' \\ %_  ', 'avaliacao': '4,9',
                    'num_avaliacoes': '(12)', 'vendas': '+50 vendidos', 'frete': '', 'cupom': "10% OFF 'X' -- ;",
                    'imagem': 'https://http2.mlstatic.com/D_Q_NP_2X_999-E.webp', 'busca': 'termo antigo',
                    'posicao': 77, 'tem_dados': 1, 'criado_em': '2025-01-01T00:00:00'}
        a = self.inserir(1)
        sets = ', '.join(f'{c}=?' for c in estranho)
        self.sql(f'UPDATE items SET {sets} WHERE item_id=?', (*estranho.values(), a))
        self.em_um_produto([a], pid(1), precos={a: 99.9})
        self.ml.listas[pid(1)][0][0]['original_price'] = 129.9
        antes = self.retrato()
        codigo, out, err = self.rodar()
        self.assertEqual(codigo, 0, err)
        depois = self.retrato()
        self.assertSoOPrecoMudou(antes, depois, a)
        self.assertEqual((depois[a]['preco'], depois[a]['preco_antigo'], depois[a]['desconto']),
                         ("'R$ 99,90'", "'R$ 129,90'", "'-23%'"))
        self.assertNotEqual(depois[a]['preco_em'], antes[a]['preco_em'])
        self.conferir_saida(out, err)

    def test_q1_coluna_nula_vira_vazia_risco_aceito(self):
        """CA4: as colunas vêm do banco; só a NULL vira '', pelo `d.get(c) or ''` do servidor.upsert."""
        # Risco aceito em 05/11/2026: o banco real tem 0 NULL nesses campos e o CA8 proíbe mexer no servidor.py.
        a = self.inserir(1)
        self.sql('UPDATE items SET cupom=NULL, frete=NULL, num_avaliacoes=NULL WHERE item_id=?', (a,))
        self.em_um_produto([a], pid(1))
        antes = self.retrato()
        codigo, out, err = self.rodar()
        self.assertEqual(codigo, 0, err)
        depois = self.retrato()
        self.assertEqual(depois[a]['preco'], "'R$ 4.321,98'")
        nulas = {'cupom', 'frete', 'num_avaliacoes'}
        for c in nulas:
            self.assertEqual((antes[a][c], depois[a][c]), ('NULL', "''"), c)
        for c in set(antes[a]) - MUDAM - nulas:
            self.assertEqual(depois[a][c], antes[a][c], c)

    def test_nenhum_insert_com_anuncios_da_resposta_fora_do_banco(self):
        a, b = self.inserir(1), self.inserir(2)
        # a: o produto tem vencedor e 30 linhas de outros anúncios; a não está entre eles
        self.ml.produtos[pid(1)] = TC.prod(pid(1), OUTRO, 10.0)
        self.ml.listas[pid(1)] = [[linha_lista(f'MLB89999999{k:02d}', 5.0 + k) for k in range(30)]]
        # b: está na lista, ao lado de anúncios que não estão no banco
        self.ml.produtos[pid(2)] = TC.prod(pid(2), 'MLB8999999950', 1.0)
        self.ml.listas[pid(2)] = [[linha_lista('MLB8999999951', 2.0), linha_lista(b, 3.0),
                                   linha_lista('MLB8999999952', 4.0)]]
        self.no_cache({a: pid(1), b: pid(2)})
        con = sqlite3.connect(self.db)
        seq_antes = con.execute("SELECT seq FROM sqlite_sequence WHERE name='items'").fetchone()
        con.close()
        n_antes = self.contagem()
        antes = self.retrato()
        codigo, out, err = self.rodar()
        self.assertEqual(codigo, 0, err)
        self.assertEqual(self.contagem(), n_antes)
        con = sqlite3.connect(self.db)
        self.assertEqual(con.execute("SELECT seq FROM sqlite_sequence WHERE name='items'").fetchone(), seq_antes)
        con.close()
        depois = self.retrato()
        self.assertEqual(set(depois), {a, b})
        self.assertEqual(depois[a], antes[a])                    # indisponível: nada gravado
        self.assertEqual(depois[b]['preco'], "'R$ 3'")
        self.assertEqual(self.upserts, [(b, False)])
        self.assertIn('1 atualizados', out)
        self.assertIn('1 indisponíveis', out)
        self.conferir_saida(out, err)

    def test_item_apagado_no_meio_da_rodada_conta_sumiu_e_nao_volta(self):
        a, b = self.inserir(1), self.inserir(2)
        self.em_um_produto([a, b], pid(1))

        def apagar(c, _):
            if c.caminho == f'/products/{pid(1)}/items':
                self.sql('DELETE FROM items WHERE item_id=?', (b,))
            return None
        self.responder_com(apagar)
        n, _ = self.contagem()
        codigo, out, err = self.rodar()
        self.assertEqual(codigo, 0, err)
        self.assertEqual(self.contagem()[0], n - 1)
        self.assertNotIn(b, self.todas())
        self.assertEqual(self.todas()[a]['preco'], 'R$ 4.321,98')
        self.assertEqual(self.upserts, [(a, False), (b, False)])
        self.assertIn('1 atualizados', out)
        self.assertIn('1 sumidos', out)


# ---------- CA4: o preço é só o do próprio anúncio ----------
class QaPrecoDoProprioAnuncio(Qa):
    def test_vencedor_e_outro_anuncio_e_o_nosso_esta_na_pagina_3_ou_4(self):
        a, b, c = self.inserir(1), self.inserir(2), self.inserir(3)
        outros = [[linha_lista(f'MLB88{p}{k:08d}', 1.0) for k in range(50)] for p in range(4)]
        outros[1].append(linha_lista(c, 22.22))   # c é nosso, mas está vinculado a outro produto
        outros[2].append(linha_lista(a, 33.33))   # página 3: ainda é lida
        outros[3].append(linha_lista(b, 44.44))   # página 4: além do limite, b fica indisponível
        self.ml.produtos[pid(1)] = TC.prod(pid(1), OUTRO, 11.11)
        self.ml.listas[pid(1)] = outros
        self.ml.produtos[pid(2)] = TC.prod(pid(2), OUTRO, 11.11)
        self.ml.listas[pid(2)] = [[linha_lista(OUTRO, 11.11)]]
        self.no_cache({a: pid(1), b: pid(1), c: pid(2)})
        antes = self.retrato()
        codigo, out, err = self.rodar()
        self.assertEqual(codigo, 0, err)
        depois = self.retrato()
        self.assertEqual(depois[a]['preco'], "'R$ 33,33'")
        self.assertEqual(depois[b], antes[b])   # nem o 11,11 do vencedor nem o 44,44 da 4ª página
        self.assertEqual(depois[c], antes[c])   # nem o 22,22 da lista do produto de outro anúncio nosso
        self.assertEqual(len(self.ml.gets(prefixo=f'/products/{pid(1)}/items')), 3)
        self.assertIn('1 atualizados', out)
        self.assertIn('2 indisponíveis', out)
        self.conferir_saida(out, err)

    def test_dois_nossos_no_mesmo_produto_cada_um_com_o_seu_preco(self):
        a, b = self.inserir(1), self.inserir(2)
        self.ml.produtos[pid(1)] = TC.prod(pid(1), a, 55.55)
        self.ml.listas[pid(1)] = [[linha_lista(a, 66.66), linha_lista(b, 77.77)]]
        self.no_cache({a: pid(1), b: pid(1)})
        codigo, out, err = self.rodar()
        self.assertEqual(codigo, 0, err)
        depois = self.todas()
        self.assertEqual((depois[a]['preco'], depois[b]['preco']), ('R$ 55,55', 'R$ 77,77'))

    def test_linha_repetida_vale_a_primeira_e_id_parecido_nao_e_o_nosso(self):
        a, b = self.inserir(1), self.inserir(2)
        self.ml.produtos[pid(1)] = TC.prod(pid(1), b + '0', 1.0)   # vencedor com id parecido com o de b
        self.ml.listas[pid(1)] = [[linha_lista(a, 12.34), linha_lista(a, 99.99),
                                   linha_lista(b.lower(), 2.0), linha_lista(' ' + b, 3.0), linha_lista(b + '\n', 4.0),
                                   linha_lista('MLB' + b[3:] + '0', 5.0), {'item_id': [b], 'price': 6.0}, None, 'x']]
        self.no_cache({a: pid(1), b: pid(1)})
        antes = self.retrato()
        codigo, out, err = self.rodar()
        self.assertEqual(codigo, 0, err)
        depois = self.retrato()
        self.assertEqual(depois[a]['preco'], "'R$ 12,34'")
        self.assertEqual(depois[b], antes[b])
        self.assertIn('1 indisponíveis', out)


# ---------- CA4: usado, sem preço, indisponível e não visto nunca gravam ----------
class QaSituacoes(Qa):
    def test_preco_e_moeda_hostis_sao_sem_preco_e_condicao_estranha_e_usado(self):
        sem_preco = [{'price': -5}, {'price': float('nan')}, {'price': float('inf')}, {'price': float('-inf')},
                     {'price': True}, {'price': '10'}, {'price': [10]}, {'price': {'v': 1}}, {'price': 5e-324},
                     {'price': 0.0099}, {'price': 0}, {'price': 1e308}, {'price': 10_000_000.0},
                     {'currency_id': 'USD'}, {'currency_id': 'brl'}, {'currency_id': 'BRL '}, {'currency_id': None},
                     {'currency_id': 986}]
        usado = [{'condition': 'NEW'}, {'condition': 'used'}, {'condition': 'refurbished'}, {'condition': ''},
                 {'condition': ['new']}]
        casos = [('sem_preco', d) for d in sem_preco] + [('usado', d) for d in usado]
        ids = []
        self.ml.produtos[pid(1)] = TC.prod(pid(1), nulo=True)
        self.ml.listas[pid(1)] = [[]]
        for n, (_, d) in enumerate(casos, 1):
            iid = self.inserir(n)
            linha = linha_lista(iid, 120.0)
            linha.update(d)
            self.ml.listas[pid(1)][0].append(linha)
            ids.append(iid)
        self.no_cache({i: pid(1) for i in ids})
        antes = self.retrato()
        codigo, out, err = self.rodar()
        self.assertEqual(codigo, 0, err)
        depois = self.retrato()
        for iid, (sit, d) in zip(ids, casos):
            with self.subTest(sit=sit, d=repr(d)):
                self.assertEqual(depois[iid], antes[iid])
        self.assertEqual(self.upserts, [])
        self.assertIn(f'0 atualizados, {len(sem_preco)} sem preço legível (dados mantidos), 0 fora do piso, '
                      f'{len(usado)} usados, 0 indisponíveis, 0 sumidos, 0 não vistos.', out)
        self.conferir_saida(out, err)

    def test_preco_antigo_hostil_nao_vira_desconto(self):
        antigos = [float('nan'), -1, '120', 10_000_000, True, None, 100.0, 50.0, 60.0]   # preço 10
        ids = [self.inserir(n) for n in range(1, len(antigos) + 1)]
        self.em_um_produto(ids, pid(1), precos={i: 10.0 for i in ids})
        for linha, antigo in zip(self.ml.listas[pid(1)][0], antigos):
            linha['original_price'] = antigo
        codigo, out, err = self.rodar()
        self.assertEqual(codigo, 0, err)
        depois = self.todas()
        for iid, antigo in zip(ids, antigos):
            with self.subTest(antigo=repr(antigo)):
                self.assertEqual(depois[iid]['preco'], 'R$ 10')
                # menor ou igual ao preço, inválido ou 5× o preço ou mais (sanear_precos): sem desconto
                self.assertEqual((depois[iid]['preco_antigo'], depois[iid]['desconto']), ('', ''))
        self.assertIn(f'{len(ids)} atualizados', out)

    def test_limites_de_preco_validos(self):
        precos = {1: 0.01, 2: 9_999_999.99, 3: 1, 4: 0.014}
        ids = {n: self.inserir(n) for n in precos}
        self.em_um_produto(ids.values(), pid(1), precos={ids[n]: p for n, p in precos.items()})
        codigo, out, err = self.rodar()
        self.assertEqual(codigo, 0, err)
        depois = self.todas()
        self.assertEqual([depois[ids[n]]['preco'] for n in precos], ['R$ 0,01', 'R$ 9.999.999,99', 'R$ 1', 'R$ 0,01'])

    def test_vincular_0_deixa_os_sem_cache_como_nao_vistos_sem_chamar_a_api(self):
        a, b, c = self.inserir(1), self.inserir(2), self.inserir(3)
        for n in (1, 2):
            self.no_catalogo(n, pid(n), linha_lista(mlb(n), 10.0))
        self.em_um_produto([c], pid(3))
        antes = self.retrato()
        codigo, out, err = self.rodar('--vincular', '0')
        self.assertEqual(codigo, 0, err)
        depois = self.retrato()
        self.assertEqual((depois[a], depois[b]), (antes[a], antes[b]))
        self.assertEqual(depois[c]['preco'], "'R$ 4.321,98'")
        self.assertEqual(self.ml.gets(caminho='/products/search'), [])
        self.assertIn('2 não vistos', out)
        self.assertIn(f'Não vistos (até 20): {a}, {b}', out)
        self.conferir_saida(out, err)


# ---------- CA5: renovação recusada no começo e no meio, sem Secret, invalid_grant ----------
class QaRenovacao(Qa):
    def test_45_itens_token_vencido_e_post_500_um_post_zero_get(self):
        ids = self.um_por_produto(45)
        self.gravar(expira_em=T.AGORA - 1)
        with open(self.caminho, 'rb') as f:
            tokens_antes = f.read()
        with open(self.catalogo, 'rb') as f:
            cache_antes = f.read()
        antes = self.retrato()
        self.responder_com(token=lambda c: T.erro_http(500, {'error': 'internal_error'}))
        codigo, out, err = self.rodar(secret=T.SECRET)
        self.assertEqual(codigo, 2, err)
        self.assertEqual((len(self.ml.op.posts()), len(self.ml.op.gets())), (1, 0))
        self.assertEqual(self.retrato(), antes)
        with open(self.caminho, 'rb') as f:
            self.assertEqual(f.read(), tokens_antes)
        with open(self.catalogo, 'rb') as f:
            self.assertEqual(f.read(), cache_antes)
        self.assertEqual(self.progresso(), [])
        self.assertEqual(len(ids), 45)
        self.conferir_saida(out, err)
        T.sem_marcadores(self, out, err)

    def test_401_no_meio_do_vinculo_e_post_500_para_com_um_post(self):
        for n in range(1, 31):
            self.inserir(n)
            self.ml.buscas[M.consulta_do_titulo(titulo(n))] = []
        self.responder_com(lambda c, k: T.erro_http(401, {'error': 'unauthorized'}) if k == 4 else None,
                           token=lambda c: T.erro_http(500, {}))
        antes = self.retrato()
        codigo, out, err = self.rodar(secret=T.SECRET)
        self.assertEqual(codigo, 2, err)
        self.assertEqual((len(self.ml.op.posts()), len(self.ml.op.gets())), (1, 4))
        self.assertIn('[HTTP 500]', err)
        self.assertEqual(self.retrato(), antes)
        self.assertEqual(len(M.ler_vinculos(self.catalogo)), 3)   # os 3 negativos de antes do erro ficam
        self.assertIsNone(self.sessoes[0].opener)
        self.conferir_saida(out, err)

    def test_401_no_meio_das_ofertas_e_post_500_para_com_um_post_e_o_1o_lote_fica(self):
        ids = self.um_por_produto(25)
        # 20 produtos (40 GETs) no 1º lote; o 401 vem no produto do 2º lote
        self.responder_com(lambda c, k: T.erro_http(401, {}) if k == 43 else None, token=lambda c: T.erro_http(500, {}))
        antes = self.retrato()
        codigo, out, err = self.rodar(secret=T.SECRET)
        self.assertEqual(codigo, 2, err)
        self.assertEqual((len(self.ml.op.posts()), len(self.ml.op.gets())), (1, 43))
        depois = self.retrato()
        self.assertEqual([i for i in ids if depois[i] != antes[i]], ids[:20])
        for i in ids[20:]:
            self.assertEqual(depois[i], antes[i])
        self.assertEqual(self.progresso(), [f'ml|{A.hoje()}|catalogo|{pid(1)}'])
        self.conferir_saida(out, err)

    def test_token_vence_no_meio_sem_secret_da_2_sem_post(self):
        for n in range(1, 11):
            self.inserir(n)
            self.ml.buscas[M.consulta_do_titulo(titulo(n))] = []

        def vencer(c, k):
            if k == 3:
                self.agora[0] = T.AGORA + 7200   # o próximo GET pede renovação
            return None
        self.responder_com(vencer)
        codigo, out, err = self.rodar()
        self.assertEqual(codigo, 2, err)
        self.assertEqual((len(self.ml.op.posts()), len(self.ml.op.gets())), (0, 3))
        self.assertEqual(err, f'ERRO: {A.MSG_SECRET_ML}\n')
        self.assertEqual(len(M.ler_vinculos(self.catalogo)), 3)
        self.conferir_saida(out, err)

    def renovacao_recusada_no_meio(self, token, trecho):
        self.um_por_produto(3)
        self.responder_com(lambda c, k: T.erro_http(401, {}) if k == 2 else None, token=token)
        antes = self.retrato()
        codigo, out, err = self.rodar(secret=T.SECRET)
        self.assertEqual(codigo, 2, err)
        self.assertEqual((len(self.ml.op.posts()), len(self.ml.op.gets())), (1, 2))
        self.assertIn(trecho, err)
        self.assertEqual(self.retrato(), antes)
        self.assertSemVazamento(out, err)
        T.sem_marcadores(self, out, err)

    def test_invalid_grant_no_meio_para_com_um_post(self):
        self.renovacao_recusada_no_meio(lambda c: T.erro_http(400, {'error': 'invalid_grant'}),
                                        'rode `ml_api.py autorizar`')

    def test_renovacao_fora_do_formato_no_meio_para_com_um_post(self):
        self.renovacao_recusada_no_meio(lambda c: {'refresh_token': 'TG-RENOVA-NOVO-0001-x', 'access_token': 5},
                                        'fora do formato esperado')

    def test_invalid_client_no_meio_para_com_um_post(self):
        self.renovacao_recusada_no_meio(lambda c: T.erro_http(401, {'error': 'invalid_client'}), 'recusou o app')

    def test_renovacao_fora_do_formato_no_meio_do_vinculo_para_com_um_post(self):
        """RenovacaoInvalida é subclasse de RespostaInvalida: não pode virar "erro passageiro" de um item."""
        ids = [self.inserir(n) for n in range(1, 11)]
        for n in range(1, 11):
            self.ml.buscas[M.consulta_do_titulo(titulo(n))] = []
        self.responder_com(lambda c, k: T.erro_http(401, {}) if k == 3 else None,
                           token=lambda c: {'refresh_token': 'TG-RENOVA-NOVO-0001-x', 'access_token': 5})
        antes = self.retrato()
        codigo, out, err = self.rodar(secret=T.SECRET)
        self.assertEqual(codigo, 2, err)
        self.assertEqual((len(self.ml.op.posts()), len(self.ml.op.gets())), (1, 3))
        self.assertEqual(err, f'ERRO: {M.RenovacaoInvalida()}\n')
        self.assertEqual(set(M.ler_vinculos(self.catalogo)), set(ids[:2]))
        self.assertEqual(self.retrato(), antes)
        self.conferir_saida(out, err)


# ---------- CA5: Limite, rede e Ctrl+C no meio; retomada só com o que falta ----------
class QaLimiteERetomada(Qa):
    def test_limite_no_2o_lote_das_ofertas_guarda_vinculos_e_1o_lote_e_retoma_so_o_resto(self):
        ids = [self.inserir(n) for n in range(1, 26)]
        for n, iid in enumerate(ids, 1):
            self.no_catalogo(n, pid(n), linha_lista(iid, 10.0 + n))
        # /products/pid(22) é lido na prova (1ª vez) e nas ofertas (2ª): o 429 só na 2ª
        self.responder_com(self.a_partir_da_vez(f'/products/{pid(22)}', 2, lambda: T.erro_http(429, {})))
        antes = self.retrato()
        codigo, out, err = self.rodar()
        self.assertEqual(codigo, 3, err)
        self.assertTrue(err.startswith('PAROU'), err)
        depois = self.retrato()
        self.assertEqual([i for i in ids if depois[i] != antes[i]], ids[:20])
        self.assertEqual(set(M.ler_vinculos(self.catalogo)), set(ids))   # todos provados e guardados
        self.assertEqual(self.progresso(), [f'ml|{A.hoje()}|catalogo|{pid(1)}'])
        self.assertIn('20 atualizados', out)
        self.assertIn('5 não vistos', out)
        self.conferir_saida(out, err)
        # rodada seguinte: nenhuma busca; só produto e lista dos 5 que faltam
        self.ml.op.chamadas.clear()
        self.responder_com()
        codigo, out, err = self.rodar()
        self.assertEqual(codigo, 0, err)
        caminhos = self.caminhos()
        self.assertEqual(sorted(caminhos), sorted([f'/products/{pid(n)}' for n in range(21, 26)]
                                                  + [f'/products/{pid(n)}/items' for n in range(21, 26)]))
        self.assertIn('RESUMO ml: 5 selecionados (20 já confirmados hoje ficaram de fora); 5 atualizados', out)

    def test_limite_no_vinculo_depois_de_23_novos_guarda_os_23_e_retoma_do_24(self):
        ids = [self.inserir(n) for n in range(1, 31)]
        for n in range(1, 31):
            self.ml.buscas[M.consulta_do_titulo(titulo(n))] = [] if n != 24 else (429, {})
        eventos = []
        gravar = M.gravar_vinculos
        with mock.patch.object(M, 'gravar_vinculos', lambda itens, *a, **k: eventos.append(len(itens))
                               or gravar(itens, *a, **k)):
            antes = self.retrato()
            codigo, out, err = self.rodar()
        self.assertEqual(codigo, 3, err)
        self.assertEqual(eventos, [20, 23])
        self.assertEqual(set(M.ler_vinculos(self.catalogo)), set(ids[:23]))
        self.assertEqual(self.retrato(), antes)
        self.assertEqual(self.progresso(), [])
        self.conferir_saida(out, err)
        self.ml.buscas[M.consulta_do_titulo(titulo(24))] = []
        self.ml.op.chamadas.clear()
        self.assertEqual(self.rodar()[0], 0)
        buscados = [c.query['q'] for c in self.ml.gets(caminho='/products/search')]
        self.assertEqual(buscados, [M.consulta_do_titulo(titulo(n)) for n in range(24, 31)])

    def test_falha_ao_guardar_os_vinculos_no_limite_nao_troca_a_saida_3(self):
        for n in range(1, 4):
            self.inserir(n)
            self.ml.buscas[M.consulta_do_titulo(titulo(n))] = [] if n != 3 else (429, {})
        with mock.patch.object(M, 'gravar_vinculos', side_effect=PermissionError('disco-MARCADOR')):
            codigo, out, err = self.rodar()
        self.assertEqual(codigo, 3, err)
        self.assertTrue(err.startswith('PAROU'), err)
        self.conferir_saida(out, err)

    def test_rede_no_meio_das_ofertas_da_1_e_o_1o_lote_fica(self):
        ids = self.um_por_produto(22)
        self.responder_com(lambda c, k: urllib.error.URLError('rede-MARCADOR') if k == 41 else None)
        antes = self.retrato()
        codigo, out, err = self.rodar()
        self.assertEqual(codigo, 1, err)
        self.assertEqual(err, f'ERRO: {M.ErroRede()}\n')
        depois = self.retrato()
        self.assertEqual([i for i in ids if depois[i] != antes[i]], ids[:20])
        self.assertIsNone(self.sessoes[0].opener)
        self.conferir_saida(out, err)

    def test_ctrl_c_no_meio_do_vinculo_da_130_e_guarda_os_vinculos(self):
        ids = [self.inserir(n) for n in range(1, 6)]
        for n in range(1, 6):
            self.ml.buscas[M.consulta_do_titulo(titulo(n))] = []
        self.responder_com(lambda c, k: KeyboardInterrupt() if k == 3 else None)
        antes = self.retrato()
        codigo, out, err = self.rodar()
        self.assertEqual(codigo, 130, err)
        self.assertEqual(set(M.ler_vinculos(self.catalogo)), set(ids[:2]))
        self.assertEqual(self.retrato(), antes)
        self.assertIsNone(self.sessoes[0].opener)
        self.conferir_saida(out, err)

    def test_sem_permissao_no_2o_lote_da_2_e_o_1o_lote_fica(self):
        ids = self.um_por_produto(21)
        self.ml.erros[f'/products/{pid(21)}/items'] = (403, {'blocked_by': 'PolicyAgent', 'code': 'PA_UNAUTHORIZED'})
        antes = self.retrato()
        codigo, out, err = self.rodar()
        self.assertEqual(codigo, 2, err)
        depois = self.retrato()
        self.assertEqual([i for i in ids if depois[i] != antes[i]], ids[:20])
        self.conferir_saida(out, err)


# ---------- CA5: teto de chamadas ----------
class QaTeto(Qa):
    def test_teto_igual_ao_necessario_termina_com_0(self):
        ids = self.um_por_produto(2)
        codigo, out, err = self.rodar('--max-chamadas', '4')
        self.assertEqual(codigo, 0, err)
        self.assertEqual(len(self.ml.op.gets()), 4)
        self.assertTrue(all(r['preco'] == 'R$ 4.321,98' for i, r in self.todas().items() if i in ids))

    def test_teto_na_virada_do_vinculo_para_as_ofertas(self):
        a = self.inserir(1)
        self.no_catalogo(1, pid(1), linha_lista(a, 10.0))
        antes = self.retrato()
        codigo, out, err = self.rodar('--max-chamadas', '3')   # busca, produto e lista: vínculo provado, sem ofertas
        self.assertEqual(codigo, 3, err)
        self.assertEqual(len(self.ml.op.gets()), 3)
        self.assertEqual(self.retrato(), antes)
        self.assertEqual(M.ler_vinculos(self.catalogo)[a]['p'], pid(1))
        self.assertIn('[ml] parou no teto de 3 chamadas (--max-chamadas)', out)
        self.conferir_saida(out, err)
        self.ml.op.chamadas.clear()
        self.assertEqual(self.rodar('--max-chamadas', '2')[0], 0)
        self.assertEqual(self.caminhos(), [f'/products/{pid(1)}', f'/products/{pid(1)}/items'])
        self.assertEqual(self.todas()[a]['preco'], 'R$ 10')

    def test_teto_1_para_depois_de_um_get(self):
        self.um_por_produto(3)
        antes = self.retrato()
        codigo, out, err = self.rodar('--max-chamadas', '1')
        self.assertEqual(codigo, 3, err)
        self.assertEqual(len(self.ml.op.gets()), 1)
        self.assertEqual(self.retrato(), antes)


# ---------- CA5: argumentos ----------
class QaArgumentos(Qa):
    def test_limites_do_vincular_e_do_max_chamadas(self):
        self.assertEqual(A.ler_argumentos(['ml', '--vincular', '0']).vincular, 0)
        self.assertEqual(A.ler_argumentos(['ml', '--vincular', '1000']).vincular, 1000)
        self.assertEqual(A.ler_argumentos(['ml', '--max-chamadas', '10000']).max_chamadas, 10000)
        self.assertEqual(A.ler_argumentos(['ml', '--max-chamadas', '1']).max_chamadas, 1)
        a = self.inserir(1)
        self.no_catalogo(1, pid(1), linha_lista(a, 10.0))
        antes, resto = self.retrato(), self.resto_do_banco()
        for argv in (('--vincular', '1001'), ('--vincular', '99999'), ('--vincular', '1e3'), ('--vincular', '+5'),
                     ('--vincular', ' 5'), ('--vincular', ''), ('--max-chamadas', '0'), ('--max-chamadas', '10001'),
                     ('--max-chamadas', '00000'), ('--max-chamadas', '-1'), ('--max-chamadas', '０')):
            with self.subTest(argv):
                codigo, out, err = self.rodar(*argv)
                self.assertEqual(codigo, 2)
        self.assertEqual(self.ml.op.chamadas, [])
        self.assertEqual((self.retrato(), self.resto_do_banco()), (antes, resto))
        self.assertFalse(os.path.exists(self.catalogo))
        self.assertEqual(self.progresso(), [])

    def test_vincular_1000_e_max_chamadas_10000_rodam(self):
        a = self.inserir(1)
        self.no_catalogo(1, pid(1), linha_lista(a, 10.0))
        codigo, out, err = self.rodar('--vincular', '1000', '--max-chamadas', '10000')
        self.assertEqual(codigo, 0, err)
        self.assertIn('(--vincular 1000)', out)
        self.assertEqual(self.todas()[a]['preco'], 'R$ 10')

    def test_cat_invalida_da_2_sem_rede_e_cat_em_nfd_vale(self):
        a = self.inserir(1, cat=CASA)
        b = self.inserir(2)   # Celulares e Informática: tem acento, então o NFD é outro texto
        self.em_um_produto([a, b], pid(1))
        antes = self.retrato()
        for cat in ('Geral', '', 'celulares e informática', CEL + ' ', '../buscas.json', 'Celulares e Informática\x00'):
            with self.subTest(cat=cat):
                codigo, out, err = self.rodar('--cat', cat)
                self.assertEqual(codigo, 2)
                self.assertNotIn('Traceback', err)
        self.assertEqual(self.ml.op.chamadas, [])
        self.assertEqual(self.retrato(), antes)

        self.assertNotEqual(unicodedata.normalize('NFD', CEL), CEL)
        codigo, out, err = self.rodar('--cat', unicodedata.normalize('NFD', CEL))
        self.assertEqual(codigo, 0, err)
        depois = self.retrato()
        self.assertEqual(depois[a], antes[a])                    # outra aba: não entra
        self.assertEqual(depois[b]['preco'], "'R$ 4.321,98'")
        self.assertIn('RESUMO ml: 1 selecionados', out)


# ---------- S3/CA3: o cache é lido antes e gravado a cada 20; arquivo recusado para tudo ----------
class QaCache(Qa):
    def test_lido_antes_de_qualquer_get_e_gravado_a_cada_20_e_no_fim(self):
        for n in range(1, 46):
            self.inserir(n)
            self.ml.buscas[M.consulta_do_titulo(titulo(n))] = []
        eventos = []
        ler, gravar = M.ler_vinculos, M.gravar_vinculos
        self.responder_com(lambda c, k: eventos.append('GET') or None)
        with mock.patch.object(M, 'ler_vinculos', lambda *a, **k: eventos.append('ler') or ler(*a, **k)), \
                mock.patch.object(M, 'gravar_vinculos',
                                  lambda itens, *a, **k: eventos.append(len(itens)) or gravar(itens, *a, **k)):
            codigo, out, err = self.rodar('--vincular', '1000')
        self.assertEqual(codigo, 0, err)
        self.assertEqual(eventos, ['ler'] + ['GET'] * 20 + [20] + ['GET'] * 20 + [40] + ['GET'] * 5 + [45])

    def test_sem_vinculo_novo_o_arquivo_nao_e_regravado_nem_criado(self):
        a = self.inserir(1)
        self.em_um_produto([a], pid(1))
        info = os.stat(self.catalogo)
        with mock.patch.object(M, 'gravar_vinculos', side_effect=AssertionError('regravou sem vínculo novo')):
            codigo, out, err = self.rodar()
        self.assertEqual(codigo, 0, err)
        self.assertEqual((os.stat(self.catalogo).st_ino, os.stat(self.catalogo).st_mtime_ns),
                         (info.st_ino, info.st_mtime_ns))
        os.unlink(self.catalogo)
        self.inserir(2)
        self.assertEqual(self.rodar('--vincular', '0')[0], 0)
        self.assertFalse(os.path.exists(self.catalogo))

    def recusado(self, preparar):
        a = self.inserir(1)
        self.no_catalogo(1, pid(1), linha_lista(a, 10.0))
        preparar()
        antes, resto = self.retrato(), self.resto_do_banco()
        codigo, out, err = self.rodar()
        self.assertEqual(codigo, 2, err)
        self.assertTrue(err.startswith('ERRO: arquivo de vínculos do catálogo recusado'), err)
        self.assertEqual(self.ml.op.chamadas, [])
        self.assertEqual((self.retrato(), self.resto_do_banco()), (antes, resto))
        self.assertEqual(self.progresso(), [])
        self.conferir_saida(out, err)

    def test_symlink_e_recusado_e_nada_e_gravado_nem_no_alvo(self):
        alvo = os.path.join(self.dir, 'outro.json')
        M.gravar_vinculos({}, alvo)
        with open(alvo, 'rb') as f:
            bruto = f.read()
        self.recusado(lambda: os.symlink(alvo, self.catalogo))
        self.assertTrue(os.path.islink(self.catalogo))
        with open(alvo, 'rb') as f:
            self.assertEqual(f.read(), bruto)

    def test_arquivo_grande_ou_fora_do_formato_e_recusado(self):
        def grande():
            with open(self.catalogo, 'wb') as f:
                f.write(b' ' * (M.MAX_ARQUIVO_VINCULOS + 1))
            os.chmod(self.catalogo, 0o600)
        self.recusado(grande)

    def test_pasta_no_lugar_do_arquivo_e_recusada(self):
        self.recusado(lambda: os.mkdir(self.catalogo))
        self.assertTrue(os.path.isdir(self.catalogo))

    def test_vinculo_com_pid_hostil_e_recusado(self):
        def hostil():
            with open(self.catalogo, 'w', encoding='ascii') as f:
                json.dump({'v': 1, 'itens': {mlb(1): {'p': 'MLB1/../../users/me', 'em': A.hoje(), 'via': 'lista'}}}, f)
            os.chmod(self.catalogo, 0o600)
        self.recusado(hostil)


# ---------- CA8 e saída: config intacta, só formatos fechados na tela ----------
class QaSaidaEConfig(Qa):
    def cenario_completo(self):
        """ok, usado, sem preço, indisponível, sem vínculo, erro passageiro no vínculo e nas ofertas."""
        ok, usado, sem, fora, novo, erro_v, erro_o = (self.inserir(n) for n in range(1, 8))
        self.ml.produtos[pid(1)] = TC.prod(pid(1), OUTRO, PRECO_API + 1)
        self.ml.listas[pid(1)] = [[linha_lista(ok, PRECO_API, original=PRECO_API * 2),
                                   linha_lista(usado, PRECO_API, condicao='used'),
                                   linha_lista(sem, PRECO_API, moeda='USD')]]
        self.ml.produtos[pid(2)] = TC.prod(pid(2), nulo=True)
        self.ml.listas[pid(2)] = [[linha_lista(OUTRO, PRECO_API)]]
        self.ml.erros[f'/products/{pid(3)}'] = (500, {'error': 'TITULO MARCADOR R$ 4321', 'message': titulo(7)})
        self.no_cache({ok: pid(1), usado: pid(1), sem: pid(1), fora: pid(2), erro_o: pid(3)})
        self.ml.buscas[M.consulta_do_titulo(titulo(5))] = []
        self.ml.buscas[M.consulta_do_titulo(titulo(6))] = (503, {'error': 'x', 'message': T.ACCESS})
        return ok

    def test_tabela_config_esquema_e_outras_tabelas_nao_mudam(self):
        self.sql("INSERT INTO config VALUES ('preco_validade_horas', '48')")
        self.sql("INSERT INTO config VALUES ('qualquer', '{\"a\": 1}')")
        self.cenario_completo()
        resto = self.resto_do_banco()
        codigo, out, err = self.rodar()
        self.assertEqual(codigo, 0, err)
        self.assertEqual(self.resto_do_banco(), resto)
        self.assertIn('1 atualizados', out)

    def test_resumo_e_avisos_so_trazem_contagens_e_ids(self):
        ok = self.cenario_completo()
        codigo, out, err = self.rodar()
        self.assertEqual(codigo, 0, err)
        self.conferir_saida(out, err)
        self.assertIn('1 atualizados, 1 sem preço legível (dados mantidos), 0 fora do piso, 1 usados, '
                      '1 indisponíveis, 0 sumidos, 3 não vistos.', out)
        self.assertIn('(1 com erro passageiro)', out)
        self.assertIn('[ml] ofertas: 1 anúncios ficaram sem leitura por erro passageiro da API', out)
        self.assertEqual(self.todas()[ok]['preco'], 'R$ 4.321,98')

    def test_saida_com_limite_e_com_teto_tambem_so_tem_formatos_fechados(self):
        self.cenario_completo()
        self.ml.erros[f'/products/{pid(1)}/items'] = (429, {'error': 'TITULO-MARCADOR'})
        codigo, out, err = self.rodar()
        self.assertEqual(codigo, 3, err)
        self.conferir_saida(out, err)
        self.ml.op.chamadas.clear()
        del self.ml.erros[f'/products/{pid(1)}/items']
        codigo, out, err = self.rodar('--max-chamadas', '2')
        self.assertEqual(codigo, 3, err)
        self.assertIn('chegou ao teto de chamadas', err)
        self.conferir_saida(out, err)
        # a linha da metade do teto também é um formato fechado: só a contagem
        self.ml.op.chamadas.clear()
        for n in (8, 9):
            self.inserir(n)
            self.ml.buscas[M.consulta_do_titulo(titulo(n))] = []
        codigo, out, err = self.rodar('--max-chamadas', '2')
        self.assertEqual(codigo, 3, err)
        self.assertIn('vínculo parou na metade do teto', out)
        self.conferir_saida(out, err)


# ---------- rodada 2: commit por item, trava só na gravação e outro programa escrevendo de verdade ----------
class QaCommitPorItem(Qa):
    def tres_no_produto(self):
        ids = [self.inserir(n) for n in (1, 2, 3)]
        self.em_um_produto(ids, pid(1))
        return ids

    def quebrando_na_vez(self, vez, excecao):
        """Na `vez`-ésima gravação, o upsert grava de verdade e aí levanta `excecao`."""
        upsert, vistas = S.upsert, [0]

        def quebra(con, it, inserir=True):
            r = upsert(con, it, inserir=inserir)
            vistas[0] += 1
            if vistas[0] == vez:
                raise excecao
            return r
        return mock.patch.object(S, 'upsert', quebra)

    def assertBancoLivre(self):
        """Outra conexão, sem esperar nada, consegue escrever: ninguém ficou com a trava."""
        con = sqlite3.connect(self.db, timeout=0)
        try:
            con.execute("INSERT OR REPLACE INTO config VALUES ('qa-trava', '1')")
            con.rollback()
        finally:
            con.close()

    def assertSoOPrimeiroFicou(self, antes, a, b, c):
        depois = self.retrato()
        self.assertEqual(depois[a]['preco'], "'R$ 4.321,98'")
        self.assertSoOPrecoMudou(antes, depois, a)
        self.assertEqual(depois[b], antes[b])   # o do meio: o upsert dele foi desfeito
        self.assertEqual(depois[c], antes[c])   # o de depois: nem chegou a ser tentado

    def assertRetomaSoOsOutros(self, a, b, c):
        preco_em = self.todas()[a]['preco_em']
        self.ml.op.chamadas.clear()
        codigo, out, err = self.rodar()
        self.assertEqual(codigo, 0, err)
        self.assertIn('RESUMO ml: 2 selecionados (1 já confirmados hoje ficaram de fora); 2 atualizados', out)
        depois = self.todas()
        self.assertEqual((depois[b]['preco'], depois[c]['preco']), ('R$ 4.321,98', 'R$ 4.321,98'))
        self.assertEqual(depois[a]['preco_em'], preco_em)

    def test_ctrl_c_no_meio_da_pagina_guarda_os_anteriores_desfaz_o_atual_e_retoma(self):
        a, b, c = self.tres_no_produto()
        antes = self.retrato()
        with self.quebrando_na_vez(2, KeyboardInterrupt()):
            codigo, out, err = self.rodar()
        self.assertEqual(codigo, 130, err)
        self.assertEqual(err, 'Interrompido. O progresso das páginas já gravadas foi salvo.\n')
        self.assertSoOPrimeiroFicou(antes, a, b, c)
        self.assertBancoLivre()
        self.assertEqual(self.progresso(), [])   # o lote não terminou: o rótulo dele não entra
        self.assertRetomaSoOsOutros(a, b, c)

    def test_erro_no_meio_da_pagina_da_1_so_com_o_tipo_e_guarda_os_anteriores(self):
        a, b, c = self.tres_no_produto()
        antes = self.retrato()
        with self.quebrando_na_vez(2, RuntimeError(f'MARCADOR {titulo(2)} https://meli.la/x')):
            codigo, out, err = self.rodar()
        self.assertEqual(codigo, 1, err)
        self.assertEqual(err, 'ERRO: RuntimeError\n')
        self.assertSemVazamento(out, err)
        self.assertSoOPrimeiroFicou(antes, a, b, c)
        self.assertBancoLivre()
        self.assertEqual(self.progresso(), [])
        self.assertRetomaSoOsOutros(a, b, c)

    def test_ctrl_c_dentro_da_gravacao_solta_a_trava_na_hora(self):
        """Sem esperar o con.close do fim: o rollback precisa valer também para BaseException."""
        a = self.inserir(1)
        it = {'loja': 'ml', 'item_id': a, 'cat': CEL, 'busca': 'x', 'url': LINK, A.RELER: True,
              'data': {'preco': 'R$ 7', 'preco_antigo': '', 'desconto': ''}}
        antes = self.retrato()
        con = S.conectar()
        try:
            with self.quebrando_na_vez(1, KeyboardInterrupt()), self.assertRaises(KeyboardInterrupt):
                A._gravar_relendo(con, it, {})
            self.assertFalse(con.in_transaction)
            self.assertBancoLivre()
            self.assertEqual(self.retrato(), antes)
        finally:
            con.close()

    def test_banco_travado_por_outro_programa_no_2o_item_da_1_e_retoma(self):
        a, b, c = self.tres_no_produto()
        conectar, gravar, vez = S.conectar, A._gravar_relendo, [0]
        outra = sqlite3.connect(self.db, timeout=0)
        self.addCleanup(outra.close)

        def sem_espera():   # o conectar real espera 30 s pela trava
            con = conectar()
            con.execute('PRAGMA busy_timeout=0')
            return con

        def gravar_com_trava(con, it, estado):
            vez[0] += 1
            if vez[0] == 2:
                outra.execute('BEGIN IMMEDIATE')
            return gravar(con, it, estado)
        antes = self.retrato()
        with mock.patch.object(S, 'conectar', sem_espera), mock.patch.object(A, '_gravar_relendo', gravar_com_trava):
            codigo, out, err = self.rodar()
        self.assertEqual(codigo, 1, err)
        self.assertEqual(err, 'ERRO: OperationalError\n')
        self.assertSoOPrimeiroFicou(antes, a, b, c)
        outra.rollback()
        self.assertBancoLivre()
        self.assertRetomaSoOsOutros(a, b, c)

    def test_nenhuma_chamada_a_api_acontece_com_o_banco_travado(self):
        """A cada GET (em 3 lotes), outra conexão sem espera escreve: a gravação não segura a trava durante a rede."""
        ids = self.um_por_produto(45)
        fora = self.inserir(99, cat=CASA)
        escritas = [0]

        def escrever(c, k):
            con = sqlite3.connect(self.db, timeout=0)
            try:
                con.execute('UPDATE items SET cupom=? WHERE item_id=?', (f'get-{k}', fora))
                con.commit()
            finally:
                con.close()
            escritas[0] += 1
            return None
        self.responder_com(escrever)
        codigo, out, err = self.rodar('--cat', CEL)
        self.assertEqual(codigo, 0, err)
        self.assertEqual(escritas[0], 90)
        depois = self.todas()
        self.assertEqual(depois[fora]['cupom'], 'get-90')
        self.assertTrue(all(depois[i]['preco'] == 'R$ 4.321,98' for i in ids))
        self.assertEqual(len(self.progresso()), 3)

    def test_outro_programa_escrevendo_em_paralelo_nunca_perde_a_ultima_escrita(self):
        """Corrida de verdade (S1/R5): cada escrita que outra conexão confirmou fica, e todo preço novo também."""
        ids = self.um_por_produto(60)
        ultimo, erros, parar, comecou = {}, [], threading.Event(), threading.Event()

        def escritor():
            k = 0
            con = sqlite3.connect(self.db, timeout=30)
            try:
                while not parar.is_set():
                    k += 1
                    iid = ids[k % len(ids)]
                    con.execute('UPDATE items SET cupom=? WHERE item_id=?', (f'CUPOM-{k}', iid))
                    con.commit()
                    ultimo[iid] = f'CUPOM-{k}'
                    comecou.set()
            except sqlite3.Error as e:
                erros.append(e)
                comecou.set()
            finally:
                con.close()
        fio = threading.Thread(target=escritor)
        fio.start()
        try:
            self.assertTrue(comecou.wait(30))
            codigo, out, err = self.rodar()
        finally:
            parar.set()
            fio.join(60)
        self.assertEqual(erros, [])
        self.assertEqual(codigo, 0, err)
        self.assertIn('60 atualizados', out)
        depois = self.todas()
        self.assertGreater(len(ultimo), 0)
        for iid in ids:
            self.assertEqual(depois[iid]['preco'], 'R$ 4.321,98', iid)
            self.assertEqual(depois[iid]['cupom'], ultimo.get(iid, TM.DADOS['cupom']), iid)


class QaServidorDeVerdade(Qa):
    """O site de verdade (servidor.py em subprocesso, banco temporário, só 127.0.0.1) mexe no meio da rodada."""

    def subir(self):
        with socket.socket() as s:
            s.bind(('127.0.0.1', 0))
            self.porta = s.getsockname()[1]
        env = {k: v for k, v in os.environ.items() if not k.startswith('ACHADINHOS_')}
        env.update({v: 'http://127.0.0.1:9' for v in ('http_proxy', 'https_proxy', 'ftp_proxy')},
                   ACHADINHOS_DB=self.db, ACHADINHOS_PORTA=str(self.porta), ACHADINHOS_DISPARO='0',
                   ACHADINHOS_API_TOKEN_ARQUIVO=os.path.join(self.dir, 'nao-existe'))
        p = subprocess.Popen([sys.executable, os.path.join(RAIZ, 'servidor.py')], cwd=self.dir, env=env,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        def parar():
            p.terminate()
            p.wait(10)
        self.addCleanup(parar)
        limite = time.monotonic() + 15
        while True:
            try:
                self.assertEqual(self.pedir('GET', '/api/items')[0], 200)
                return
            except OSError:
                self.assertLess(time.monotonic(), limite, 'o servidor não subiu')
                time.sleep(0.05)

    def pedir(self, metodo, caminho, corpo=None):
        """http.client ignora os proxies: o pedido vai direto ao servidor local e não espera mais que 5 s."""
        c = http.client.HTTPConnection('127.0.0.1', self.porta, timeout=5)
        try:
            c.request(metodo, caminho, None if corpo is None else json.dumps(corpo),
                      {'Content-Type': 'application/json'} if corpo is not None else {})
            r = c.getresponse()
            return r.status, json.loads(r.read() or b'null')
        finally:
            c.close()

    def test_edicao_afiliacao_e_exclusao_pelo_site_no_meio_da_rodada_ficam(self):
        editado, afiliado, excluido = self.inserir(1), self.inserir(2, url='https://www.mercadolivre.com.br/p/MLB2'), \
            self.inserir(3)
        self.em_um_produto([editado, afiliado, excluido], pid(1))
        self.subir()
        ids = {i: r['id'] for i, r in self.todas().items()}
        novos = {**TM.DADOS, 'titulo': 'TITULO-MARCADOR editado no site', 'preco': 'R$ 1,00', 'preco_antigo': '',
                 'desconto': '', 'cupom': 'CUPOM-MARCADOR-SITE'}
        respostas, feito = [], []

        def no_meio(c, k):
            if c.caminho == f'/products/{pid(1)}/items' and not feito:
                feito.append(1)
                respostas.append(self.pedir('PATCH', f'/api/items/{ids[editado]}', {'data': novos, 'cat': CASA})[0])
                respostas.append(self.pedir('PATCH', f'/api/items/{ids[afiliado]}', {'url': 'https://meli.la/Novo2'})[0])
                respostas.append(self.pedir('DELETE', f'/api/items/{ids[excluido]}')[0])
            return None
        self.responder_com(no_meio)
        codigo, out, err = self.rodar()
        self.assertEqual(codigo, 0, err)
        self.assertEqual(respostas, [200, 200, 200])
        self.assertIn('2 atualizados', out)
        self.assertIn('1 sumidos', out)
        self.conferir_saida(out, err)
        # lido pelo site: o que o site gravou ficou e o preço é o da API
        status, itens = self.pedir('GET', '/api/items')
        self.assertEqual(status, 200)
        por_id = {i['item_id']: i for i in (itens if isinstance(itens, list) else itens['items'])}
        self.assertEqual(set(por_id), {editado, afiliado})
        e = por_id[editado]
        self.assertEqual((e['data']['titulo'], e['data']['cupom'], e['cat'], e['data']['preco']),
                         (novos['titulo'], novos['cupom'], CASA, 'R$ 4.321,98'))
        self.assertEqual((por_id[afiliado]['url'], por_id[afiliado]['data']['preco']),
                         ('https://meli.la/Novo2', 'R$ 4.321,98'))


class QaTetoEMetadeRodada2(Qa):
    def sem_cache(self, n):
        for k in range(1, n + 1):
            self.inserir(k)
            self.ml.buscas[M.consulta_do_titulo(titulo(k))] = []

    def test_teto_atingido_no_vinculo_tambem_usa_a_mensagem_do_teto(self):
        """R1: o teste do dev confere a mensagem só com o teto nas ofertas."""
        a = self.inserir(1)
        self.ml.buscas[M.consulta_do_titulo(titulo(1))] = [{'id': pid(k), 'status': 'active'} for k in (1, 2, 3)]
        for k in (1, 2, 3):
            self.ml.produtos[pid(k)] = TC.prod(pid(k), nulo=True)
        antes = self.retrato()
        codigo, out, err = self.rodar('--max-chamadas', '2')
        self.assertEqual(codigo, 3, err)
        self.assertEqual(err, TM.MSG_TETO + '\n')
        self.assertEqual(len(self.ml.op.gets()), 2)
        self.assertEqual(self.retrato()[a], antes[a])
        self.conferir_saida(out, err)

    def test_429_na_ultima_chamada_do_teto_e_bloqueio_e_nao_teto(self):
        self.um_por_produto(1)
        self.ml.erros[f'/products/{pid(1)}/items'] = (429, {})
        codigo, out, err = self.rodar('--max-chamadas', '2')
        self.assertEqual(codigo, 3, err)
        self.assertEqual(err, TM.MSG_BLOQUEIO + '\n')
        self.assertNotIn('parou no teto', out)

    def test_vincular_acaba_antes_da_metade_conta_adiados_e_nao_avisa_metade(self):
        self.sem_cache(3)
        codigo, out, err = self.rodar('--vincular', '1', '--max-chamadas', '2')
        self.assertEqual(codigo, 0, err)
        self.assertEqual(len(self.ml.op.gets()), 1)
        self.assertIn('1 sem produto; 0 vieram do cache e 1 foram à API (0 com erro passageiro); '
                      '2 ficam para a próxima rodada (--vincular 1).', out)
        self.assertNotIn('metade', out)
        self.assertIn('3 não vistos', out)

    def test_metade_antes_do_vincular_conta_na_linha_da_metade_e_nao_nos_adiados(self):
        self.sem_cache(3)
        codigo, out, err = self.rodar('--vincular', '5', '--max-chamadas', '2')
        self.assertEqual(codigo, 0, err)
        self.assertEqual(len(self.ml.op.gets()), 1)
        self.assertIn('1 foram à API (0 com erro passageiro); 0 ficam para a próxima rodada (--vincular 5).', out)
        self.assertIn('[ml] vínculo parou na metade do teto; 2 itens ficam para a próxima rodada.', out)
        self.assertIn('3 não vistos', out)
        self.conferir_saida(out, err)

    def test_metade_guarda_a_outra_metade_para_as_ofertas(self):
        """Muitos itens sem vínculo não comem o teto: as ofertas dos que têm vínculo ainda são lidas."""
        self.sem_cache(20)
        ok = self.inserir(21)
        self.ml.produtos[pid(21)] = TC.prod(pid(21), nulo=True)
        self.ml.listas[pid(21)] = [[linha_lista(ok, 10.0)]]
        self.no_cache({ok: pid(21)})
        codigo, out, err = self.rodar('--max-chamadas', '10')
        self.assertEqual(codigo, 0, err)
        self.assertEqual(len(self.ml.op.gets()), 7)   # 5 no vínculo + produto e lista
        self.assertEqual(self.todas()[ok]['preco'], 'R$ 10')
        self.assertIn('15 itens ficam para a próxima rodada', out)


# ---------- CA6/CA8: arquivos reais fora de alcance ----------
class QaArquivosReais(unittest.TestCase):
    def test_caminhos_do_teste_apontam_para_a_pasta_temporaria(self):
        for p in (S.DB, A.FEITOS, M.TOKENS, M.CATALOGO):
            self.assertTrue(os.path.realpath(p).startswith(os.path.realpath(T.TMP) + os.sep), p)
            self.assertNotEqual(os.path.dirname(os.path.realpath(p)), os.path.realpath(RAIZ))

    def test_script_com_cwd_na_raiz_nao_cria_nada_na_raiz(self):
        pasta = tempfile.mkdtemp(dir=T.TMP)
        env = {k: v for k, v in os.environ.items() if not k.startswith('ACHADINHOS_')}
        env.update({v: 'http://127.0.0.1:9' for v in ('http_proxy', 'https_proxy', 'ftp_proxy')}, no_proxy='',
                   ACHADINHOS_DB=os.path.join(pasta, 'achadinhos.db'),
                   ACHADINHOS_ML_TOKENS=os.path.join(pasta, 'ml_tokens.json'),
                   ACHADINHOS_ML_CATALOGO=os.path.join(pasta, 'ml_catalogo.json'),
                   ACHADINHOS_FEITOS_ATUALIZAR=os.path.join(pasta, 'feitos.txt'))
        def sensiveis():   # só nomes que este comando poderia criar na raiz (o servidor real mexe no -wal)
            return sorted(n for n in os.listdir(RAIZ) if n.startswith(('ml_', '.ml_', 'feitos', 'atualizar_precos_')))
        raiz_antes = sensiveis()
        r = subprocess.run([sys.executable, os.path.join(RAIZ, 'atualizar_precos.py'), 'ml', '--vincular', '5'],
                           cwd=RAIZ, env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertEqual(sensiveis(), raiz_antes)
        self.assertEqual(_catalogo_no_projeto(), CATALOGO_NO_PROJETO_ANTES)
        self.assertEqual(_feitos_real(), FEITOS_REAL_ANTES)
        self.assertEqual(os.listdir(pasta), [])


if __name__ == '__main__':
    unittest.main()
