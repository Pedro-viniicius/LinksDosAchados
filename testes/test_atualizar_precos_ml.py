#!/usr/bin/env python3
"""Testes da fonte `ml` do atualizar_precos.py (docs/produto/planos/api-oficial-ml-catalogo.md, etapa 3: CA4, CA5,
CA6 e CA8).

Uso:  python3 testes/test_atualizar_precos_ml.py -v

Nenhum teste fala com o Mercado Livre: o catálogo é o MLFalso do test_ml_api_catalogo.py, atrás do OpenerFalso do
test_ml_api.py, que fixa no import os proxies mortos e ACHADINHOS_ML_TOKENS, ACHADINHOS_DB e ACHADINHOS_ML_CATALOGO
numa pasta temporária. Cada teste tem o seu banco (servidor.criar_banco), o seu arquivo de tokens, o seu arquivo de
vínculos, o seu buscas.json e o seu arquivo de progresso, todos nessa pasta. Títulos, cupom, foto e tokens são
marcadores procurados na saída; o relógio da Sessao e a pausa são falsos.
"""
import contextlib
import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_ml_api as T             # noqa: E402  (proxies, tokens, banco e vínculos temporários)
import test_ml_api_catalogo as TC   # noqa: E402  (MLFalso, prod)

os.environ['ACHADINHOS_FEITOS_ATUALIZAR'] = os.path.join(T.TMP, 'feitos-atualizar.txt')
os.environ['ACHADINHOS_FEITOS'] = os.path.join(T.TMP, 'feitos-coleta-amazon.txt')
os.environ['ACHADINHOS_FEITOS_SHOPEE'] = os.path.join(T.TMP, 'feitos-coleta-shopee.txt')
import atualizar_precos as A        # noqa: E402
import servidor as S                # noqa: E402

M = T.M
RAIZ = T.RAIZ
assert all(os.path.dirname(p) == T.TMP for p in (S.DB, A.FEITOS, M.TOKENS, M.CATALOGO)), \
    'o teste não pode tocar os dados reais'

CEL, CASA = 'Celulares e Informática', 'Casa e Cozinha'
BUSCAS = {CEL: ['iPhone 17'], CASA: ['Air fryer']}
ANTIGO = '2026-01-10T08:00:00'
LINK = 'https://meli.la/AbC123'
OUTRO = 'MLB8999999999'   # anúncio que não está no banco
DADOS = {'preco': 'R$ 50,00', 'preco_antigo': 'R$ 60,00', 'desconto': '-17%', 'avaliacao': '4.8 de 5 estrelas',
         'num_avaliacoes': '(1.234)', 'vendas': '+5mil vendidos', 'frete': 'Frete grátis', 'cupom': 'CUPOM-MARCADOR',
         'imagem': 'https://http2.mlstatic.com/D_Q_NP_2X_FOTO-MARCADOR-E.webp'}
PAUSA = M.PAUSA_MIN + (M.PAUSA_MAX - M.PAUSA_MIN) * 0.5   # aleatorio falso = 0.5
MSG_TETO = 'PAROU: chegou ao teto de chamadas (--max-chamadas); rode de novo para seguir, sem precisar esperar.'
MSG_BLOQUEIO = ('PAROU: a loja bloqueou (captcha, 503, 429 ou limite da API). O progresso foi salvo; '
                'espere de 15 a 30 minutos e rode de novo.')


def tearDownModule():
    T.tearDownModule()


def mlb(n):
    return f'MLB{8100000000 + n}'


def pid(n):
    return f'MLB7{n:05d}'


def titulo(n):
    return f'TITULO-MARCADOR-ML{n:03d} Celular Ação Nº{n} 128GB'


def linha_lista(item_id, preco, original=None, moeda='BRL', condicao='new'):
    d = {'item_id': item_id, 'price': preco, 'original_price': original, 'currency_id': moeda, 'seller_id': 77777}
    if condicao is not None:
        d['condition'] = condicao
    return d


class Base(T.Base):
    def setUp(self):
        super().setUp()   # self.dir, self.caminho (tokens), self.agora, self.dormidas
        self.db = os.path.join(self.dir, 'achadinhos.db')
        self.catalogo = os.path.join(self.dir, 'ml_catalogo.json')
        self.buscas = os.path.join(self.dir, 'buscas.json')
        with open(self.buscas, 'w', encoding='utf-8') as f:
            json.dump(BUSCAS, f, ensure_ascii=False)
        for alvo, nome, novo in ((S, 'DB', self.db), (A, 'FEITOS', os.path.join(self.dir, 'feitos.txt')),
                                 (A, 'BUSCAS', self.buscas), (M, 'CATALOGO', self.catalogo),
                                 (M, 'TOKENS', self.caminho), (M, 'BACKOFF_BASE', 0.0)):
            p = mock.patch.object(alvo, nome, novo)
            p.start()
            self.addCleanup(p.stop)
        S.criar_banco()
        self.gravar()   # tokens válidos por 1 h no relógio falso
        self.ml = TC.MLFalso()
        self.sessoes = []
        self.upserts = []
        upsert = S.upsert

        def espiao(con, it, inserir=True):
            self.upserts.append((it.get('item_id'), inserir))
            return upsert(con, it, inserir=inserir)
        p = mock.patch.object(S, 'upsert', espiao)
        p.start()
        self.addCleanup(p.stop)

    # ---------- banco ----------
    def inserir(self, n, cat=CEL, url=LINK, titulo_=None, item_id=None, loja='ml', preco_em=ANTIGO):
        con = S.conectar()
        try:
            colunas = ['loja', 'item_id', 'cat', 'busca', 'url', 'titulo', *DADOS, 'tem_dados', 'posicao',
                       'criado_em', 'atualizado_em', 'preco_em']
            valores = [loja, item_id or mlb(n), cat, BUSCAS[cat][0] if cat in BUSCAS else 'x', url,
                       titulo(n) if titulo_ is None else titulo_, *DADOS.values(), 1, n, ANTIGO, ANTIGO, preco_em]
            con.execute(f'INSERT INTO items ({",".join(colunas)}) VALUES ({",".join("?" * len(colunas))})', valores)
            con.commit()
        finally:
            con.close()
        return item_id or mlb(n)

    def todas(self):
        con = S.conectar()
        try:
            return {r['item_id']: dict(r) for r in con.execute('SELECT * FROM items')}
        finally:
            con.close()

    def progresso(self):
        if not os.path.exists(A.FEITOS):
            return []
        with open(A.FEITOS, encoding='utf-8') as f:
            return f.read().splitlines()

    # ---------- catálogo falso ----------
    def no_catalogo(self, n, p, linha=None, bbw=None):
        """O título do item n leva ao produto p (busca); a linha dele (se houver) entra na 1ª página da lista de p."""
        self.ml.buscas[M.consulta_do_titulo(titulo(n))] = [{'id': p, 'status': 'active'}]
        self.ml.produtos.setdefault(p, bbw or TC.prod(p, nulo=True))
        if linha is not None:
            self.ml.listas.setdefault(p, [[]])[0].append(linha)

    def no_cache(self, vinculos):
        """vinculos: {item_id: pid|None} gravados como provados (pela lista) ou negativos de hoje."""
        M.gravar_vinculos({i: {'p': p, 'em': A.hoje(), 'via': 'lista' if p else None} for i, p in vinculos.items()},
                          self.catalogo)

    def caminhos(self):
        return [c.caminho for c in self.ml.op.gets()]

    # ---------- comando ----------
    def rodar(self, *argv, secret=None):
        """(código, stdout, stderr) do main com `ml` e os argumentos; o Secret só no os.environ, se dado."""
        real = M.sessao_do_ambiente

        def sessao_do_ambiente():
            s = real()
            s.relogio, s.dormir, s.aleatorio = (lambda: self.agora[0]), self.dormidas.append, (lambda: 0.5)
            self.sessoes.append(s)
            return s
        out, err = io.StringIO(), io.StringIO()
        env = {'ACHADINHOS_ML_SECRET': secret} if secret else {}
        with mock.patch.dict(os.environ, env), mock.patch.object(M, 'OPENER', self.ml.op), \
                mock.patch.object(M, 'sessao_do_ambiente', sessao_do_ambiente), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            if not secret:
                os.environ.pop('ACHADINHOS_ML_SECRET', None)
            try:
                codigo = A.main(['ml', *argv])
            except SystemExit as e:
                codigo = e.code
            self.secret_ficou = 'ACHADINHOS_ML_SECRET' in os.environ
        return codigo, out.getvalue(), err.getvalue()

    def assertSemVazamento(self, *textos):
        for t in textos:
            for proibido in ('MARCADOR', 'Ação', 'R$', 'mlstatic', 'meli.la', 'http', '77777', '55555'):
                self.assertNotIn(proibido, t)
            T.sem_marcadores(self, t)


# ---------- CA4: só o preço muda, o link fica, nada é inserido ----------
class TestGravacao(Base):
    def test_grava_so_o_preco_mantem_o_meli_la_e_os_dados_do_banco(self):
        a = self.inserir(1)                                                    # com meli.la
        b = self.inserir(2, url='https://www.mercadolivre.com.br/celular/p/MLB123')   # sem afiliado
        self.inserir(3, loja='amazon', item_id='B0AMAZON01', url='https://www.amazon.com.br/dp/B0AMAZON01?tag=x')
        self.no_catalogo(1, pid(1), linha_lista(a, 1234.5, original=1500))
        self.no_catalogo(2, pid(1), linha_lista(b, 99.9))
        self.ml.listas[pid(1)][0].insert(0, linha_lista(OUTRO, 5.0))           # outro anúncio do produto
        antes = self.todas()
        codigo, out, err = self.rodar()
        self.assertEqual(codigo, 0, err)
        depois = self.todas()
        self.assertEqual(set(depois), set(antes), 'nunca insere')
        self.assertEqual(self.upserts, [(a, False), (b, False)])
        mudam = ('preco', 'preco_antigo', 'desconto', 'preco_em', 'atualizado_em', 'url')
        for iid in (a, b):
            for c in set(antes[iid]) - set(mudam):
                self.assertEqual(depois[iid][c], antes[iid][c], (iid, c))   # título, nota, vendas, foto, frete, cupom
            self.assertTrue(depois[iid]['preco_em'].startswith(A.hoje() + 'T'))
        self.assertEqual((depois[a]['preco'], depois[a]['preco_antigo'], depois[a]['desconto']),
                         ('R$ 1.234,50', 'R$ 1.500', '-18%'))
        self.assertEqual((depois[b]['preco'], depois[b]['preco_antigo'], depois[b]['desconto']), ('R$ 99,90', '', ''))
        self.assertEqual(depois[a]['url'], LINK)                                            # o meli.la fica
        self.assertEqual(depois[b]['url'], 'https://produto.mercadolivre.com.br/MLB-8100000002')   # montada pelo id
        self.assertEqual(depois['B0AMAZON01'], antes['B0AMAZON01'])
        self.assertEqual(M.ler_vinculos(self.catalogo), {a: {'p': pid(1), 'em': A.hoje(), 'via': 'lista'},
                                                         b: {'p': pid(1), 'em': A.hoje(), 'via': 'lista'}})
        self.assertEqual(self.progresso(), [f'ml|{A.hoje()}|catalogo|{pid(1)}'])
        self.assertEqual(self.ml.op.posts(), [])   # token válido: o Secret nem é pedido
        self.assertIsNone(self.sessoes[0].opener)  # a vista com teto devolveu o opener original
        self.assertIn('RESUMO ml: 2 selecionados (0 já confirmados hoje ficaram de fora); 2 atualizados, '
                      '0 sem preço legível (dados mantidos), 0 fora do piso, 0 usados, 0 indisponíveis, 0 sumidos, '
                      '0 não vistos.', out)
        self.assertSemVazamento(out, err)

    def test_preco_do_vencedor_que_e_outro_anuncio_nunca_e_gravado(self):
        a, b, c = self.inserir(1), self.inserir(2), self.inserir(3)
        # a: o vencedor é outro anúncio (R$ 10); vale a linha de a na lista (R$ 77)
        self.no_catalogo(1, pid(1), linha_lista(a, 77.0), bbw=TC.prod(pid(1), OUTRO, 10.0))
        # b: já vinculado; o vencedor é outro anúncio e b saiu da lista: indisponível, nada gravado
        self.ml.produtos[pid(2)] = TC.prod(pid(2), OUTRO, 11.0)
        self.ml.listas[pid(2)] = [[linha_lista(OUTRO, 11.0)]]
        self.no_cache({b: pid(2)})
        # c: o vencedor é o próprio c (prova e preço pelo buy_box_winner)
        self.no_catalogo(3, pid(3), bbw=TC.prod(pid(3), c, 55.5))
        antes = self.todas()
        codigo, out, err = self.rodar()
        self.assertEqual(codigo, 0, err)
        depois = self.todas()
        self.assertEqual(depois[a]['preco'], 'R$ 77')
        self.assertEqual(depois[b], antes[b])
        self.assertEqual(depois[c]['preco'], 'R$ 55,50')
        self.assertEqual(M.ler_vinculos(self.catalogo)[c]['via'], 'bbw')
        self.assertEqual({i for i, _ in self.upserts}, {a, c})
        self.assertIn('2 atualizados, 0 sem preço legível (dados mantidos), 0 fora do piso, 0 usados, '
                      '1 indisponíveis', out)

    def test_usado_sem_preco_e_indisponivel_nao_gravam(self):
        casos = {1: ('usado', {'condicao': 'used'}), 2: ('usado', {'condicao': None}),
                 3: ('usado', {'titulo': 'Celular Seminovo 128GB'}),
                 4: ('sem_preco', {'moeda': 'USD'}), 5: ('sem_preco', {'preco': None}),
                 6: ('sem_preco', {'preco': 0}), 7: ('sem_preco', {'preco': 0.004}),
                 8: ('sem_preco', {'preco': 0.0099}), 9: ('sem_preco', {'preco': 10_000_000}),
                 10: ('sem_preco', {'preco': '99.90'}), 11: ('indisponivel', {'fora': True}),
                 12: ('ok', {'preco': 0.01})}
        ids = {}
        self.ml.produtos[pid(1)] = TC.prod(pid(1), nulo=True)
        self.ml.listas[pid(1)] = [[]]
        for n, (_, k) in casos.items():
            ids[n] = self.inserir(n, titulo_=k.get('titulo'))
            if not k.get('fora'):
                self.ml.listas[pid(1)][0].append(linha_lista(ids[n], k.get('preco', 120.0), moeda=k.get('moeda', 'BRL'),
                                                             condicao=k.get('condicao', 'new')))
        self.no_cache({i: pid(1) for i in ids.values()})
        antes = self.todas()
        codigo, out, err = self.rodar()
        self.assertEqual(codigo, 0, err)
        depois = self.todas()
        for n, (situacao, _) in casos.items():
            if situacao != 'ok':
                self.assertEqual(depois[ids[n]], antes[ids[n]], n)
        self.assertEqual(depois[ids[12]]['preco'], 'R$ 0,01')   # 1 centavo ainda é preço
        self.assertEqual(self.upserts, [(ids[12], False)])
        self.assertIn('1 atualizados, 7 sem preço legível (dados mantidos), 0 fora do piso, 3 usados, '
                      '1 indisponíveis, 0 sumidos, 0 não vistos.', out)
        self.assertSemVazamento(out, err)

    def test_sem_vinculo_cai_em_nao_vistos(self):
        a = self.inserir(1)                    # negativo recente no cache: nem vai à API
        b = self.inserir(2)                    # busca sem candidato
        c = self.inserir(3)                    # candidato sem o anúncio (bbw nulo, lista 404)
        d = self.inserir(4, titulo_='')        # sem título utilizável: negativo sem chamada
        self.no_cache({a: None})
        self.ml.buscas[M.consulta_do_titulo(titulo(2))] = []
        self.no_catalogo(3, pid(3))
        antes = self.todas()
        codigo, out, err = self.rodar()
        self.assertEqual(codigo, 0, err)
        self.assertEqual(self.todas(), antes)
        self.assertEqual(self.caminhos(), ['/products/search', '/products/search', f'/products/{pid(3)}',
                                           f'/products/{pid(3)}/items'])
        self.assertIn('0 atualizados', out)
        self.assertIn('4 não vistos', out)
        self.assertIn(f'Não vistos (até 20): {a}, {b}, {c}, {d}', out)
        negativo = {'p': None, 'em': A.hoje(), 'via': None}
        self.assertEqual(M.ler_vinculos(self.catalogo), {i: negativo for i in (a, b, c, d)})
        self.assertEqual(self.upserts, [])

    def test_selecao_so_ids_mlb_das_abas_e_traz_os_campos_do_banco(self):
        bom = self.inserir(1)
        self.inserir(2, item_id='MLB12')                                         # curto demais
        self.inserir(3, item_id='https://produto.mercadolivre.com.br/MLB-1')
        self.inserir(4, cat='Geral')                                             # aba fora do buscas.json
        self.inserir(5, preco_em=A.hoje() + 'T00:00:01')                         # já confirmado hoje
        con = S.conectar()
        try:
            itens, ja = A.selecionar(con, 'ml', [CEL, CASA], A.hoje())
        finally:
            con.close()
        self.assertEqual((list(itens), ja), ([bom], 1))
        self.assertTrue(set(S.CAMPOS) <= set(itens[bom]))
        self.assertNotIn('url', itens[bom])
        self.assertEqual(itens[bom]['cupom'], DADOS['cupom'])
        self.assertEqual(A.ID_DA_LOJA['ml'].pattern, r'MLB[0-9]{6,19}')

    def test_retomada_pelo_preco_em_de_hoje(self):
        a, b = self.inserir(1), self.inserir(2)
        self.no_cache({a: pid(1), b: pid(2)})
        for n, iid in ((1, a), (2, b)):
            self.ml.produtos[pid(n)] = TC.prod(pid(n), nulo=True)
            self.ml.listas[pid(n)] = [[linha_lista(iid, 10.0 * n)]]
        self.assertEqual(self.rodar()[0], 0)
        self.ml.op.chamadas.clear()
        codigo, out, err = self.rodar()
        self.assertEqual(codigo, 0, err)
        self.assertEqual(self.ml.op.chamadas, [])
        self.assertIn('0 selecionados (2 já confirmados hoje ficaram de fora)', out)

    def test_fontes_tem_o_ml(self):
        self.assertIs(A.FONTES['ml'], A.fonte_ml_catalogo)


# ---------- S1/R5: o que o site ou o console mudam no meio da rodada fica ----------
class TestReleitura(Base):
    NOVOS = {'titulo': 'TITULO-MARCADOR novo', 'cupom': 'CUPOM-MARCADOR-NOVO', 'avaliacao': '4.9 de 5 estrelas',
             'num_avaliacoes': '(9)', 'vendas': '+9mil vendidos', 'frete': 'Frete novo',
             'imagem': 'https://http2.mlstatic.com/D_Q_NP_2X_FOTO-MARCADOR-NOVA-E.webp'}

    def sql(self, comando, params=()):
        con = sqlite3.connect(self.db, timeout=30)
        try:
            con.execute(comando, params)
            con.commit()
        finally:
            con.close()

    def no_produto(self, *ids):
        """Os ids vinculados no cache ao produto 1, com a linha de cada um na lista (preço 100 + posição)."""
        self.ml.produtos[pid(1)] = TC.prod(pid(1), nulo=True)
        self.ml.listas[pid(1)] = [[linha_lista(i, 100.0 + k, original=150.0) for k, i in enumerate(ids)]]
        self.no_cache({i: pid(1) for i in ids})

    def ao_ler_a_lista(self, fazer):
        """fazer() roda uma vez no meio da rodada: depois da seleção e antes da gravação da página."""
        responder, feito = self.ml.responder, []

        def gets(c):
            if c.caminho == f'/products/{pid(1)}/items' and not feito:
                feito.append(1)
                fazer()
            return responder(c)
        self.ml.op.responder = T.api_padrao(gets=gets)

    def item_direto(self, iid, **novo):
        data = {c: 'velho' for c in S.CAMPOS}
        data.update(preco='R$ 77', preco_antigo='R$ 99', desconto='-22%')
        data.update(novo)
        return {'loja': 'ml', 'item_id': iid, 'cat': CEL, 'busca': 'iPhone 17', 'url': 'https://x.invalid/', 'data': data,
                A.RELER: True}

    def test_edicao_no_meio_da_rodada_fica_e_o_preco_novo_e_gravado(self):
        a, b = self.inserir(1), self.inserir(2)
        self.no_produto(a, b)
        sets = ', '.join(f'{c}=?' for c in self.NOVOS)
        self.ao_ler_a_lista(lambda: self.sql(f'UPDATE items SET {sets}, cat=? WHERE item_id=?',
                                             (*self.NOVOS.values(), CASA, a)))
        antes = self.todas()
        codigo, out, err = self.rodar()
        self.assertEqual(codigo, 0, err)
        depois = self.todas()
        for c, valor in self.NOVOS.items():
            self.assertEqual(depois[a][c], valor, c)        # a edição do meio da rodada não volta ao valor velho
        self.assertEqual(depois[a]['cat'], CASA)
        self.assertEqual((depois[a]['preco'], depois[a]['preco_antigo'], depois[a]['desconto']),
                         ('R$ 100', 'R$ 150', '-33%'))      # e o preço novo é gravado
        self.assertTrue(depois[a]['preco_em'].startswith(A.hoje() + 'T'))
        self.assertEqual(depois[a]['url'], LINK)
        self.assertEqual(depois[b]['preco'], 'R$ 101')      # o outro item segue com os dados dele
        self.assertEqual(depois[b]['cupom'], antes[b]['cupom'])
        self.assertIn('2 atualizados', out)
        self.assertSemVazamento(out, err)

    def test_linha_apagada_no_meio_da_rodada_conta_sumiu_e_nao_volta(self):
        a, b = self.inserir(1), self.inserir(2)
        self.no_produto(a, b)
        self.ao_ler_a_lista(lambda: self.sql('DELETE FROM items WHERE item_id=?', (b,)))
        codigo, out, err = self.rodar()
        self.assertEqual(codigo, 0, err)
        depois = self.todas()
        self.assertEqual(set(depois), {a})
        self.assertEqual(depois[a]['preco'], 'R$ 100')
        self.assertIn('1 atualizados', out)
        self.assertIn('1 sumidos', out)
        self.assertEqual(self.upserts, [(a, False), (b, False)])   # só com inserir=False: nunca volta

    def test_o_marcador_nao_chega_ao_upsert_nem_ao_banco(self):
        a, b = self.inserir(1), self.inserir(2)
        self.no_produto(a, b)
        self.ao_ler_a_lista(lambda: self.sql('DELETE FROM items WHERE item_id=?', (b,)))
        vistos, upsert = [], S.upsert

        def espiao(con, it, inserir=True):
            vistos.append(dict(it))
            return upsert(con, it, inserir=inserir)
        fonte, marcados = A.FONTES['ml'], []

        def fonte_espiada(itens, opcoes):   # prova que o marcador sai da fonte (senão o teste não prova nada)
            for rotulo, obs in fonte(itens, opcoes):
                marcados.extend(o.it[A.RELER] for o in obs)
                yield rotulo, obs
        with mock.patch.object(S, 'upsert', espiao), mock.patch.dict(A.FONTES, {'ml': fonte_espiada}):
            self.assertEqual(self.rodar()[0], 0)
        self.assertEqual(marcados, [True, True])
        self.assertEqual([i['item_id'] for i in vistos], [a, b])   # com linha (a) e sem linha (b)
        for it in vistos:
            self.assertEqual(set(it), {'loja', 'item_id', 'cat', 'busca', 'url', 'data'})
            self.assertEqual(set(it['data']), set(S.CAMPOS))
        self.assertNotIn(A.RELER, self.todas()[a])

    def test_nenhuma_escrita_entra_entre_a_leitura_e_a_gravacao(self):
        a = self.inserir(1)
        upsert, tentativas = S.upsert, []

        def espiao(con, it, inserir=True):
            outra = sqlite3.connect(self.db, timeout=0)
            try:
                with self.assertRaises(sqlite3.OperationalError):
                    outra.execute("UPDATE items SET cupom='entrou no meio'")
                tentativas.append(con.in_transaction)
            finally:
                outra.close()
            return upsert(con, it, inserir=inserir)
        con = S.conectar()
        estado = {}
        try:
            with mock.patch.object(S, 'upsert', espiao):
                self.assertEqual(A._gravar_relendo(con, self.item_direto(a), estado), 1)
            self.assertFalse(con.in_transaction)   # commit logo depois: a trava não fica presa
        finally:
            con.close()
        self.assertEqual(tentativas, [True])
        self.assertEqual(estado, {a: 'atualizado'})
        self.assertEqual(self.todas()[a]['preco'], 'R$ 77')

    def test_erro_no_upsert_desfaz_e_solta_a_trava(self):
        a = self.inserir(1)
        upsert = S.upsert

        def quebra(con, it, inserir=True):
            upsert(con, it, inserir=inserir)
            raise RuntimeError('falha no meio')
        antes = self.todas()
        con = S.conectar()
        try:
            with mock.patch.object(S, 'upsert', quebra), self.assertRaises(RuntimeError):
                A._gravar_relendo(con, self.item_direto(a), {})
            self.assertFalse(con.in_transaction)
        finally:
            con.close()
        self.assertEqual(self.todas(), antes)

    def test_transacao_aberta_antes_e_preservada_com_commit(self):
        a, b = self.inserir(1), self.inserir(2)
        con = S.conectar()
        try:
            con.execute("UPDATE items SET cupom='da pagina' WHERE item_id=?", (b,))
            self.assertTrue(con.in_transaction)
            self.assertEqual(A._gravar_relendo(con, self.item_direto(a), {}), 1)
            con.rollback()   # o que veio antes já foi gravado, o BEGIN IMMEDIATE não falha por transação aberta
        finally:
            con.close()
        self.assertEqual(self.todas()[b]['cupom'], 'da pagina')

    def test_linha_relida_sem_titulo_ou_preco_ilegivel_nao_grava(self):
        a, b = self.inserir(1), self.inserir(2)
        self.sql("UPDATE items SET titulo='' WHERE item_id=?", (a,))
        antes = self.todas()
        self.upserts.clear()
        con = S.conectar()
        estado = {}
        try:
            self.assertEqual(A._gravar_relendo(con, self.item_direto(a), estado), 0)   # título apagado no meio
            self.assertEqual(A._gravar_relendo(con, self.item_direto(b, preco='sem preço'), estado), 0)
            self.assertFalse(con.in_transaction)
        finally:
            con.close()
        self.assertEqual(estado, {a: 'indisponivel', b: 'sem_preco'})
        self.assertEqual(self.upserts, [])
        self.assertEqual(self.todas(), antes)

    def test_fonte_sem_marcador_grava_o_que_veio_e_o_commit_e_por_pagina(self):
        """Amazon e Shopee não relêem: o `it` vai ao upsert como veio e o commit continua sendo o da página."""
        iid = self.inserir(1, loja='amazon', item_id='B0AMAZON01', url='https://www.amazon.com.br/dp/B0AMAZON01?tag=x')
        self.sql("UPDATE items SET cupom='mudou no meio' WHERE item_id=?", (iid,))
        data = {**DADOS, 'titulo': 'TITULO-MARCADOR da busca', 'preco': 'R$ 7'}
        it = {'loja': 'amazon', 'item_id': iid, 'cat': CEL, 'busca': 'iPhone 17',
              'url': f'https://www.amazon.com.br/dp/{iid}?tag=desejodemen01-20', 'data': data}
        vistos, upsert = [], S.upsert

        def espiao(con, item, inserir=True):
            vistos.append(item)
            return upsert(con, item, inserir=inserir)
        antes = self.todas()
        con = S.conectar()
        try:
            with mock.patch.object(S, 'upsert', espiao), \
                    mock.patch.object(A, '_gravar_relendo', side_effect=AssertionError('releu')):
                n = A.gravar_pagina(con, 'amazon', {iid: {}}, [A.Observacao(iid, 'ok', it)], {})
                self.assertEqual(n, 1)
                self.assertTrue(con.in_transaction)   # quem fecha é o atualizar, depois da página
                con.rollback()
                self.assertEqual(self.todas(), antes)
                self.assertEqual(A.gravar_pagina(con, 'amazon', {iid: {}}, [A.Observacao(iid, 'ok', it)], {}), 1)
                con.commit()
        finally:
            con.close()
        self.assertIs(vistos[0], it)
        depois = self.todas()[iid]
        self.assertEqual((depois['titulo'], depois['preco'], depois['cupom']),
                         ('TITULO-MARCADOR da busca', 'R$ 7', DADOS['cupom']))


# ---------- vínculo pela API: limite por rodada, cache lido antes de gravar (S3) ----------
class TestVinculos(Base):
    def test_vincular_respeita_o_maximo_e_grava_o_cache_a_cada_20(self):
        ids = [self.inserir(n) for n in range(1, 46)]
        for n in range(1, 46):
            self.ml.buscas[M.consulta_do_titulo(titulo(n))] = []
        eventos = []
        ler, gravar = M.ler_vinculos, M.gravar_vinculos
        with mock.patch.object(M, 'ler_vinculos', lambda *a, **k: eventos.append('ler') or ler(*a, **k)), \
                mock.patch.object(M, 'gravar_vinculos',
                                  lambda itens, *a, **k: eventos.append(len(itens)) or gravar(itens, *a, **k)):
            codigo, out, err = self.rodar('--vincular', '25')
            self.assertEqual(codigo, 0, err)
            self.assertEqual(eventos, ['ler', 20, 25])   # S3: lido antes; gravado a cada 20 e no fim
            self.assertEqual(len(self.ml.op.gets()), 25)
            self.assertEqual(set(M.ler_vinculos(self.catalogo)), set(ids[:25]))   # na ordem da seleção
            self.assertIn('45 não vistos', out)
            self.assertIn('20 ficam para a próxima rodada (--vincular 25)', out)
            # a próxima rodada usa o cache e vincula só os que faltam
            eventos.clear()
            self.ml.op.chamadas.clear()
            self.assertEqual(self.rodar()[0], 0)
            self.assertEqual(eventos, ['ler', 45])   # 25 do cache + 20 novos: grava ao chegar a 20 novos
            self.assertEqual(len(self.ml.op.gets()), 20)
            self.ml.op.chamadas.clear()
            self.assertEqual(self.rodar('--vincular', '0')[0], 0)
            self.assertEqual(self.ml.op.gets(), [])

    def test_arquivo_de_vinculos_recusado_para_com_2_sem_gravar_nada(self):
        a = self.inserir(1)
        self.no_catalogo(1, pid(1), linha_lista(a, 10.0))
        self.no_cache({a: None})
        os.chmod(self.catalogo, 0o644)
        with open(self.catalogo, 'rb') as f:
            bruto = f.read()
        antes = self.todas()
        with mock.patch.object(M, 'gravar_vinculos', side_effect=AssertionError('gravou sem ter lido')):
            codigo, out, err = self.rodar()
        self.assertEqual(codigo, 2)
        self.assertTrue(err.startswith('ERRO: arquivo de vínculos do catálogo recusado'), err)
        self.assertEqual(self.ml.op.chamadas, [])
        with open(self.catalogo, 'rb') as f:
            self.assertEqual(f.read(), bruto)
        self.assertEqual(self.todas(), antes)

    def test_arquivo_de_vinculos_recusado_nem_abre_nem_cria_o_banco(self):
        self.no_cache({mlb(1): None})
        os.chmod(self.catalogo, 0o644)
        novo = os.path.join(self.dir, 'banco-novo.db')
        ordem, ler, conectar = [], M.ler_vinculos, S.conectar
        with mock.patch.object(S, 'DB', novo), \
                mock.patch.object(S, 'conectar', lambda: ordem.append('banco') or conectar()), \
                mock.patch.object(M, 'ler_vinculos', lambda *a, **k: ordem.append('vinculos') or ler(*a, **k)):
            codigo, out, err = self.rodar()
        self.assertEqual(codigo, 2)
        self.assertTrue(err.startswith('ERRO: arquivo de vínculos do catálogo recusado'), err)
        self.assertEqual(ordem, ['vinculos'])
        self.assertEqual([n for n in os.listdir(self.dir) if n.startswith('banco-novo')], [])
        self.assertEqual(self.ml.op.chamadas, [])
        self.assertEqual(out, '')

    def test_vinculos_lidos_uma_vez_antes_do_banco_e_entregues_a_fonte(self):
        a = self.inserir(1)
        self.no_catalogo(1, pid(1), linha_lista(a, 10.0))
        ordem, ler, conectar = [], M.ler_vinculos, S.conectar
        with mock.patch.object(S, 'conectar', lambda: ordem.append('banco') or conectar()), \
                mock.patch.object(M, 'ler_vinculos', lambda *a, **k: ordem.append('vinculos') or ler(*a, **k)):
            self.assertEqual(self.rodar()[0], 0)
        self.assertEqual(ordem[0], 'vinculos')
        self.assertEqual(ordem.count('vinculos'), 1)
        self.assertIn('banco', ordem)

    def test_erro_passageiro_por_item_conta_e_segue(self):
        a, b, c, d, e = (self.inserir(n) for n in range(1, 6))
        self.ml.buscas[M.consulta_do_titulo(titulo(1))] = (500, {'error': 'internal_error'})   # ErroApi
        self.ml.buscas[M.consulta_do_titulo(titulo(2))] = 'x'          # results que não é lista: RespostaInvalida
        self.no_catalogo(3, pid(3), linha_lista(c, 30.0))
        self.no_cache({d: pid(4), e: pid(5)})
        self.ml.erros[f'/products/{pid(4)}'] = (503, {})                # erro passageiro nas ofertas
        self.ml.produtos[pid(5)] = TC.prod(pid(5), nulo=True)
        self.ml.listas[pid(5)] = [[linha_lista(e, 50.0)]]
        antes = self.todas()
        codigo, out, err = self.rodar()
        self.assertEqual(codigo, 0, err)
        depois = self.todas()
        self.assertEqual((depois[c]['preco'], depois[e]['preco']), ('R$ 30', 'R$ 50'))
        for iid in (a, b, d):
            self.assertEqual(depois[iid], antes[iid])
        self.assertIn('2 atualizados', out)
        self.assertIn('3 não vistos', out)
        self.assertIn('(2 com erro passageiro)', out)
        self.assertIn('[ml] ofertas: 1 anúncios ficaram sem leitura por erro passageiro da API', out)
        self.assertEqual(set(M.ler_vinculos(self.catalogo)), {c, d, e})   # o erro não vira negativo
        self.assertSemVazamento(out, err)


# ---------- CA5: limite, teto, pausa e saídas ----------
class TestLimitesESaidas(Base):
    def produtos_no_cache(self, n):
        ids = []
        for k in range(1, n + 1):
            iid = self.inserir(k)
            self.ml.produtos[pid(k)] = TC.prod(pid(k), nulo=True)
            self.ml.listas[pid(k)] = [[linha_lista(iid, 10.0 + k)]]
            ids.append(iid)
        self.no_cache({iid: pid(k) for k, iid in enumerate(ids, 1)})
        return ids

    def test_limite_da_3_o_que_foi_gravado_fica_e_retoma(self):
        ids = self.produtos_no_cache(25)
        self.ml.erros[f'/products/{pid(22)}'] = (429, {})
        codigo, out, err = self.rodar()
        self.assertEqual(codigo, 3, err)
        self.assertTrue(err.startswith('PAROU'))
        depois = self.todas()
        self.assertEqual([i for i in ids if depois[i]['preco_em'].startswith(A.hoje())], ids[:20])   # o 1º lote
        self.assertEqual(self.progresso(), [f'ml|{A.hoje()}|catalogo|{pid(1)}'])
        self.assertIn('RESUMO ml: 25 selecionados', out)
        self.assertIn('20 atualizados', out)
        # mesma data: só os 5 que faltaram são lidos (produto e lista de cada um)
        del self.ml.erros[f'/products/{pid(22)}']
        self.ml.op.chamadas.clear()
        codigo, out, err = self.rodar()
        self.assertEqual(codigo, 0, err)
        self.assertEqual(len(self.ml.op.gets()), 10)
        self.assertIn('RESUMO ml: 5 selecionados (20 já confirmados hoje ficaram de fora); 5 atualizados', out)
        self.assertTrue(all(r['preco_em'].startswith(A.hoje()) for r in self.todas().values()))

    def test_limite_no_vinculo_guarda_os_vinculos_ja_provados(self):
        a, b, c = self.inserir(1), self.inserir(2), self.inserir(3)
        self.no_catalogo(1, pid(1), linha_lista(a, 10.0))
        self.no_catalogo(2, pid(2), linha_lista(b, 20.0))
        self.ml.buscas[M.consulta_do_titulo(titulo(3))] = (429, {})
        antes = self.todas()
        codigo, out, err = self.rodar()
        self.assertEqual(codigo, 3, err)
        self.assertEqual(self.todas(), antes)
        self.assertEqual(set(M.ler_vinculos(self.catalogo)), {a, b})   # menos de 20, gravados ao parar

    def test_teto_de_chamadas_para_com_3(self):
        """O 2º item começa abaixo da metade do teto e gasta o resto dele nos candidatos: o teto para no vínculo."""
        for n in range(1, 11):
            self.inserir(n)
            self.ml.buscas[M.consulta_do_titulo(titulo(n))] = []
        self.ml.buscas[M.consulta_do_titulo(titulo(2))] = [{'id': pid(1), 'status': 'active'},
                                                           {'id': pid(2), 'status': 'active'}]
        for p in (pid(1), pid(2)):
            self.ml.produtos[p] = TC.prod(p, nulo=True)
        codigo, out, err = self.rodar('--max-chamadas', '4')
        self.assertEqual(codigo, 3, err)
        self.assertEqual(len(self.ml.op.gets()), 4)
        self.assertIn('[ml] parou no teto de 4 chamadas (--max-chamadas)', out)
        self.assertIn('RESUMO ml: 10 selecionados', out)
        self.assertEqual(set(M.ler_vinculos(self.catalogo)), {mlb(1)})   # o negativo de antes do teto fica
        self.assertIsNone(self.sessoes[0].opener)

    def test_mensagem_do_teto_nao_manda_esperar(self):
        """R1: o teto é do dono, não um bloqueio da loja."""
        self.produtos_no_cache(2)
        codigo, out, err = self.rodar('--max-chamadas', '3')
        self.assertEqual(codigo, 3, err)
        self.assertEqual(err, MSG_TETO + '\n')
        self.assertIn('[ml] parou no teto de 3 chamadas (--max-chamadas); rode de novo para seguir.', out)
        self.assertSemVazamento(out, err)

    def test_mensagem_do_limite_da_api_continua_a_do_bloqueio(self):
        self.produtos_no_cache(2)
        self.ml.erros[f'/products/{pid(1)}'] = (429, {})
        codigo, out, err = self.rodar()
        self.assertEqual(codigo, 3, err)
        self.assertEqual(err, MSG_BLOQUEIO + '\n')

    def test_motivo_do_bloqueio_chega_ao_resumo_e_escolhe_a_mensagem(self):
        for excecao, motivo, mensagem in ((A.Bloqueio(), None, MSG_BLOQUEIO), (A.Bloqueio(A.TETO), A.TETO, MSG_TETO)):
            with self.subTest(motivo=motivo):
                def fonte(itens, opcoes, e=excecao):
                    raise e
                    yield
                with mock.patch.dict(A.FONTES, {'amazon': fonte}):
                    resumo = A.atualizar('amazon', {CEL: BUSCAS[CEL]}, {})
                self.assertEqual((resumo['parou'], resumo['motivo']), (True, motivo))
                out, err = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    self.assertEqual(A._resultado(resumo), 3)
                self.assertEqual(err.getvalue(), mensagem + '\n')
        with mock.patch.dict(A.FONTES, {'amazon': lambda itens, opcoes: iter(())}):
            resumo = A.atualizar('amazon', {CEL: BUSCAS[CEL]}, {})
        self.assertEqual((resumo['parou'], resumo['motivo']), (False, None))

    def vinculo_vazio(self, ate):
        """Itens 1 a `ate` sem vínculo no cache, cuja busca não acha candidato (1 GET por item)."""
        for n in range(1, ate + 1):
            self.inserir(n)
            self.ml.buscas[M.consulta_do_titulo(titulo(n))] = []

    def test_vinculo_para_na_metade_do_teto(self):
        """R3: chegou à metade, não vincula mais; os outros ficam em não vistos, sem saída 3 (o teto não chegou)."""
        self.vinculo_vazio(10)
        codigo, out, err = self.rodar('--max-chamadas', '4')
        self.assertEqual(codigo, 0, err)
        self.assertEqual(len(self.ml.op.gets()), 2)
        self.assertIn('[ml] vínculo parou na metade do teto; 8 itens ficam para a próxima rodada.', out)
        self.assertIn('10 não vistos', out)
        self.assertEqual(set(M.ler_vinculos(self.catalogo)), {mlb(1), mlb(2)})
        self.assertEqual(err, '')
        self.assertSemVazamento(out, err)

    def test_metade_de_teto_impar_arredonda_para_baixo(self):
        self.vinculo_vazio(10)
        self.assertEqual(self.rodar('--max-chamadas', '5')[0], 0)
        self.assertEqual(len(self.ml.op.gets()), 2)

    def test_abaixo_da_metade_nao_para_nem_avisa(self):
        self.vinculo_vazio(3)
        codigo, out, err = self.rodar('--max-chamadas', '8')
        self.assertEqual(codigo, 0, err)
        self.assertEqual(len(self.ml.op.gets()), 3)
        self.assertNotIn('metade', out)

    def test_item_com_vinculo_no_cache_passa_da_metade_e_as_ofertas_usam_o_resto(self):
        """A metade só barra quem iria à API: os do cache, mesmo depois dela na seleção, ainda têm preço lido."""
        self.vinculo_vazio(5)
        ids = [self.inserir(n) for n in (6, 7)]
        for n, iid in zip((6, 7), ids):
            self.ml.produtos[pid(n)] = TC.prod(pid(n), nulo=True)
            self.ml.listas[pid(n)] = [[linha_lista(iid, 10.0 + n)]]
        self.no_cache({ids[0]: pid(6), ids[1]: pid(7)})
        codigo, out, err = self.rodar('--max-chamadas', '8')
        self.assertEqual(codigo, 0, err)
        self.assertEqual(len(self.ml.op.gets()), 8)                # 4 no vínculo + 2 × (produto e lista)
        self.assertIn('[ml] vínculo parou na metade do teto; 1 itens ficam para a próxima rodada.', out)
        self.assertIn('2 atualizados', out)
        self.assertIn('5 não vistos', out)
        depois = self.todas()
        self.assertEqual((depois[ids[0]]['preco'], depois[ids[1]]['preco']), ('R$ 16', 'R$ 17'))

    def test_teto_1_nao_vincula_nada(self):
        """Metade de 1 é 0: nenhuma chamada de vínculo; é o limite de baixo do --max-chamadas."""
        self.vinculo_vazio(2)
        codigo, out, err = self.rodar('--max-chamadas', '1')
        self.assertEqual(codigo, 0, err)
        self.assertEqual(self.ml.op.gets(), [])
        self.assertIn('[ml] vínculo parou na metade do teto; 2 itens ficam para a próxima rodada.', out)

    def test_teto_nas_ofertas_nao_grava_o_lote_cortado(self):
        self.produtos_no_cache(2)
        antes = self.todas()
        codigo, out, err = self.rodar('--max-chamadas', '3')
        self.assertEqual(codigo, 3, err)
        self.assertEqual(len(self.ml.op.gets()), 3)
        self.assertEqual(self.todas(), antes)
        self.assertEqual(self.progresso(), [])

    def test_padroes_e_pausa_entre_chamadas(self):
        for n in range(1, 4):
            self.inserir(n)
            self.ml.buscas[M.consulta_do_titulo(titulo(n))] = []
        espiao = mock.Mock(wraps=M.com_teto)
        with mock.patch.object(M, 'com_teto', espiao):
            self.assertEqual(self.rodar()[0], 0)
        self.assertEqual(espiao.call_args.args[1], 3000)
        self.assertEqual(len(self.ml.op.gets()), 3)
        self.assertEqual(len(self.dormidas), 2)   # entre as chamadas, não antes da primeira
        for d in self.dormidas:
            self.assertAlmostEqual(d, PAUSA)
        self.assertTrue(0.3 <= PAUSA <= 0.8)

    def test_sem_secret_com_token_vencido_da_2_sem_rede(self):
        a = self.inserir(1)
        self.no_catalogo(1, pid(1), linha_lista(a, 10.0))
        self.gravar(expira_em=T.AGORA - 1)
        antes = self.todas()
        codigo, out, err = self.rodar()
        self.assertEqual(codigo, 2)
        self.assertEqual(self.ml.op.chamadas, [])
        self.assertEqual(self.todas(), antes)
        self.assertIn('read -rs S; ACHADINHOS_ML_SECRET="$S" python3 atualizar_precos.py ml', err)
        self.assertFalse(os.path.exists(self.catalogo))
        T.sem_marcadores(self, out, err)

    def test_secret_so_e_usado_para_renovar_e_sai_do_ambiente(self):
        a = self.inserir(1)
        self.no_catalogo(1, pid(1), linha_lista(a, 10.0))
        self.gravar(expira_em=T.AGORA + 60)   # vence em menos de 5 min: renova
        codigo, out, err = self.rodar(secret=T.SECRET)
        self.assertEqual(codigo, 0, err)
        self.assertFalse(self.secret_ficou)
        self.assertEqual(len(self.ml.op.posts()), 1)
        self.assertEqual(self.ml.op.posts()[0].campos['client_secret'], T.SECRET)
        self.assertIn('1 atualizados', out)
        T.sem_marcadores(self, out, err)

    def test_renovacao_500_com_token_vencido_faz_1_post_e_0_get(self):
        """Contrato 1: N itens, token vencido e POST /oauth/token 500: exatamente 1 POST e 0 GET, saída 2."""
        for n in range(1, 6):
            iid = self.inserir(n)
            self.no_catalogo(n, pid(n), linha_lista(iid, 10.0))
        self.gravar(expira_em=T.AGORA - 1)
        self.ml.op.responder = T.api_padrao(gets=self.ml.responder,
                                            token=lambda c: T.erro_http(500, {'error': 'internal_error'}))
        antes = self.todas()
        codigo, out, err = self.rodar(secret=T.SECRET)
        self.assertEqual(codigo, 2)
        self.assertEqual((len(self.ml.op.posts()), len(self.ml.op.gets())), (1, 0))
        self.assertEqual(err, f'ERRO: {M.RenovacaoFalhou(500, "internal_error")}\n')
        self.assertEqual(self.todas(), antes)
        self.assertFalse(os.path.exists(self.catalogo))
        T.sem_marcadores(self, out, err)

    def vencer_depois_de(self, k):
        """O token vence depois do k-ésimo GET (o próximo pede renovação)."""
        responder = self.ml.responder

        def gets(c):
            if len(self.ml.op.gets()) >= k:
                self.agora[0] = T.AGORA + 7200
            return responder(c)
        return gets

    def test_renovacao_recusada_no_meio_do_vinculo_para_na_hora(self):
        for n in range(1, 6):
            self.inserir(n)
            self.ml.buscas[M.consulta_do_titulo(titulo(n))] = []
        self.ml.op.responder = T.api_padrao(gets=self.vencer_depois_de(2), token=lambda c: T.erro_http(502, {}))
        codigo, out, err = self.rodar(secret=T.SECRET)
        self.assertEqual(codigo, 2, err)
        self.assertEqual((len(self.ml.op.posts()), len(self.ml.op.gets())), (1, 2))
        self.assertIn('[HTTP 502]', err)
        self.assertEqual(len(M.ler_vinculos(self.catalogo)), 2)   # os 2 negativos de antes do erro ficam

    def test_renovacao_recusada_no_meio_das_ofertas_para_na_hora(self):
        self.produtos_no_cache(3)
        antes = self.todas()
        self.ml.op.responder = T.api_padrao(gets=self.vencer_depois_de(2), token=lambda c: T.erro_http(503, {}))
        codigo, out, err = self.rodar(secret=T.SECRET)
        self.assertEqual(codigo, 2, err)
        self.assertEqual((len(self.ml.op.posts()), len(self.ml.op.gets())), (1, 2))
        self.assertEqual(self.todas(), antes)

    def test_sem_permissao_sem_tokens_e_tokens_recusados_dao_2(self):
        a = self.inserir(1)
        self.ml.erros['/products/search'] = (403, {'blocked_by': 'PolicyAgent', 'code': 'PA_UNAUTHORIZED'})
        codigo, out, err = self.rodar()
        self.assertEqual(codigo, 2)
        self.assertTrue(err.startswith('ERRO: o app Etiqueta não tem a permissão funcional'), err)
        self.assertNotIn(a, M.ler_vinculos(self.catalogo))
        os.chmod(self.caminho, 0o644)
        self.ml.op.chamadas.clear()
        codigo, out, err = self.rodar()
        self.assertEqual(codigo, 2)
        self.assertIn('arquivo de tokens recusado', err)
        os.unlink(self.caminho)
        codigo, out, err = self.rodar()
        self.assertEqual(codigo, 2)
        self.assertIn('rode `ml_api.py autorizar`', err)
        self.assertEqual(self.ml.op.chamadas, [])

    def test_argumentos(self):
        for argv in (('--vincular', '1001'), ('--vincular', '-1'), ('--vincular', 'abc'), ('--vincular', '١'),
                     ('--max-chamadas', '0'), ('--max-chamadas', '10001'), ('--max-chamadas', '3.5'),
                     ('--cat', 'Aba que não existe'), ('--produtos', '1')):
            with self.subTest(argv):
                self.assertEqual(self.rodar(*argv)[0], 2)
        self.assertEqual(self.ml.op.chamadas, [])
        a = A.ler_argumentos(['ml'])
        self.assertEqual((a.vincular, a.max_chamadas, a.abas), (300, 3000, BUSCAS))
        a = A.ler_argumentos(['ml', '--cat', CASA, '--vincular', '1000', '--max-chamadas', '10000'])
        self.assertEqual((a.vincular, a.max_chamadas, a.abas), (1000, 10000, {CASA: BUSCAS[CASA]}))
        self.assertEqual(A.ler_argumentos(['ml', '--vincular', '0', '--max-chamadas', '1']).vincular, 0)


# ---------- CA4/CA5 como script ----------
class TestScript(unittest.TestCase):
    def test_sem_tokens_sai_com_2_antes_de_criar_o_banco(self):
        pasta = tempfile.mkdtemp(dir=T.TMP)
        env = {k: v for k, v in os.environ.items() if not k.startswith('ACHADINHOS_')}
        db = os.path.join(pasta, 'achadinhos.db')
        env.update({v: 'http://127.0.0.1:9' for v in ('http_proxy', 'https_proxy', 'ftp_proxy')}, no_proxy='',
                   ACHADINHOS_DB=db, ACHADINHOS_ML_TOKENS=os.path.join(pasta, 'ml_tokens.json'),
                   ACHADINHOS_ML_CATALOGO=os.path.join(pasta, 'ml_catalogo.json'),
                   ACHADINHOS_FEITOS_ATUALIZAR=os.path.join(pasta, 'feitos.txt'))
        r = subprocess.run([sys.executable, os.path.join(RAIZ, 'atualizar_precos.py'), 'ml'], cwd=pasta, env=env,
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertNotIn('Traceback', r.stderr)
        self.assertIn('rode `ml_api.py autorizar`', r.stderr)
        self.assertEqual(os.listdir(pasta), [])   # nem banco, nem vínculos, nem progresso


if __name__ == '__main__':
    unittest.main()
