#!/usr/bin/env python3
"""Testes de QA da Shopee como terceira loja (docs/produto/planos/perfumaria-tres-lojas.md: CA1, CA2, CA7, CA10).

Uso:  python3 testes/test_shopee_qa.py -v

Complementa test_servidor.py (E1), test_disparo*.py (E2) e test_coletar_shopee.py (E7) sem repetir o que eles
já provam. Quatro frentes:
  - servidor.py de verdade (subprocesso, banco temporário): bordas do POST, da listagem e da concorrência;
  - disparo: seleção por loja, regras antigas, link e foto de outra loja, ordenação e mensagem da Shopee,
    tick de ponta a ponta e as rotas /api/disparo/*;
  - coletar_shopee: assinatura recalculada a partir do que foi de fato enviado, termo hostil, piso nas bordas,
    link e destino hostis, o Secret procurado em toda saída, limite no meio da coleta, respostas malformadas;
  - integração: o que o coletar_shopee grava é aceito e ordenado pelo disparo.
Nada acessa a Shopee, a Amazon, o ML, o achadinhos.db real nem a porta 8765: `OPENER_API.open` e a conferência são
falsos, os bancos são temporários e os proxies estão mortos. Credenciais são marcadores falsos.
Só biblioteca padrão.
"""
import contextlib
import hashlib
import http.client
import io
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_disparo as T            # noqa: E402  (define ACHADINHOS_DB e os proxies mortos antes do import)
import test_disparo_servidor as TD  # noqa: E402
import test_servidor as TS          # noqa: E402

TMP = tempfile.mkdtemp(prefix='teste-shopee-qa-')
os.environ.setdefault('ACHADINHOS_FEITOS_SHOPEE', os.path.join(TMP, 'feitos-shopee.txt'))
for _v in ('ACHADINHOS_SHOPEE_APP_ID', 'ACHADINHOS_SHOPEE_SECRET'):
    os.environ.pop(_v, None)

import coletar_shopee as C  # noqa: E402

D, S = T.D, T.S
assert os.path.realpath(S.DB) != T.DB_REAL, 'o teste não pode tocar o banco real'
assert os.path.realpath(C.FEITOS) != os.path.realpath(os.path.join(T.RAIZ, 'coleta_shopee_feitos.txt'))

SECRET = 'SEGREDO-QA-b81d7e4f'
APP_ID = '1800099'
ID = '18001234567'
CAT = 'Perfumes e Perfumaria'
LINK = 'https://s.shopee.com.br/AbC123xyz'
FOTO = 'https://down-br.img.susercontent.com/file/br-11134207-abc'
DESTINO_BOM = f'https://shopee.com.br/product/1/2?utm_source=an_{ID}&utm_medium=affiliates'
ENV = {'ACHADINHOS_SHOPEE_APP_ID': APP_ID, 'ACHADINHOS_SHOPEE_SECRET': SECRET}
# Links que parecem de afiliado da Shopee e não são, ou são de outra loja
LINKS_RUINS = ['https://s.shopee.com.br/', 'https://s.shopee.com.br/abc?x=1', 'http://s.shopee.com.br/abc',
               'https://shopee.com.br/product/1/2', 'https://s.shopee.com.br.evil.com/abc', 'https://shope.ee/abc',
               'https://s.shopee.com.br:8443/abc', 'https://s.shopee.com.br/ab-c', 'https://evil.com/s.shopee.com.br/abc',
               'https://www.amazon.com.br/dp/B0ABCDEFGH?tag=desejodemen01-20', 'https://meli.la/AbC1234', '', None, 7]


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


# ================================================================ servidor.py de verdade
class TestServidorShopee(TS.ServidorTeste):
    """CA1: bordas que o test_servidor.py não cobre."""

    def item(self, item_id, loja='shopee'):
        return next((i for i in self.itens() if i['item_id'] == item_id and i['loja'] == loja), None)

    def test_ca1_shopee_sem_url_nao_grava_nada_e_responde_200(self):
        for url in (None, ''):
            with self.subTest(url=url):
                corpo = {'loja': 'shopee', 'item_id': f'sem.{url!r}', 'cat': CAT}
                if url is not None:
                    corpo['url'] = url
                st, _, dados = self.postar([corpo])
                self.assertEqual(st, 200, dados)
                self.assertEqual(self.json_de(dados)['inserido'], 0)
                self.assertIsNone(self.item(f'sem.{url!r}'))

    def test_ca1_url_que_nao_e_texto_da_400(self):
        for url in (123, ['https://s.shopee.com.br/abc'], {'a': 1}, True):
            with self.subTest(url=url):
                st, _, _ = self.postar([{'loja': 'shopee', 'item_id': '1.1', 'url': url}])
                self.assertEqual(st, 400)

    def test_ca1_sem_item_id_o_id_e_a_url_e_o_segundo_post_atualiza(self):
        url = 'https://s.shopee.com.br/SemId77'
        st, _, dados = self.postar([{'loja': 'shopee', 'cat': CAT, 'url': url, 'data': {'titulo': 'A', 'preco': 'R$ 1,00'}}])
        self.assertEqual((st, self.json_de(dados)['inserido']), (200, 1))
        st, _, dados = self.postar([{'loja': 'shopee', 'cat': CAT, 'url': url, 'data': {'titulo': 'B', 'preco': 'R$ 2,00'}}])
        self.assertEqual((st, self.json_de(dados)['atualizado']), (200, 1))
        it = self.item(url)
        self.assertEqual((it['url'], it['data']['titulo']), (url, 'B'))
        self.assertEqual(len([i for i in self.itens() if i['item_id'] == url]), 1)

    def test_ca1_mesmo_item_id_em_lojas_diferentes_convive(self):
        amz = 'https://www.amazon.com.br/dp/B0MESMOID1?tag=desejodemen01-20'
        st, _, dados = self.postar([{'loja': 'shopee', 'item_id': '55.66', 'url': 'https://s.shopee.com.br/Mesmo1'},
                                    {'loja': 'amazon', 'item_id': '55.66', 'url': amz}])
        self.assertEqual((st, self.json_de(dados)['inserido']), (200, 2), dados)
        self.assertEqual(self.item('55.66', 'shopee')['url'], 'https://s.shopee.com.br/Mesmo1')
        self.assertEqual(self.item('55.66', 'amazon')['url'], amz)

    def test_ca1_lote_misto_com_um_shopee_ruim_nao_grava_nenhum(self):
        amz = 'https://www.amazon.com.br/dp/B0LOTEMIX1?tag=desejodemen01-20'
        for ruim in ('https://www.amazon.com.br/dp/B0LOTEMIX2?tag=desejodemen01-20', 'https://s.shopee.com.br/ok?x=1'):
            with self.subTest(ruim=ruim):
                st, _, _ = self.postar([{'loja': 'amazon', 'item_id': 'MIX.1', 'url': amz},
                                        {'loja': 'ml', 'item_id': 'MLB900000001', 'url': 'https://meli.la/MixOk01'},
                                        {'loja': 'shopee', 'item_id': 'MIX.2', 'url': 'https://s.shopee.com.br/MixOk2'},
                                        {'loja': 'shopee', 'item_id': 'MIX.3', 'url': ruim}])
                self.assertEqual(st, 400)
                for iid in ('MIX.1', 'MLB900000001', 'MIX.2', 'MIX.3'):
                    self.assertFalse([i for i in self.itens() if i['item_id'] == iid], iid)

    def test_ca1_ml_sem_afiliado_ignora_item_shopee(self):
        self.postar([{'loja': 'shopee', 'item_id': 'MLS.1', 'url': 'https://s.shopee.com.br/MlSem1'},
                     {'loja': 'ml', 'item_id': 'MLB900000777', 'url': 'https://produto.mercadolivre.com.br/MLB-900000777'}])
        st, _, dados = self.pedir('GET', '/api/ml-sem-afiliado')
        self.assertEqual(st, 200)
        urls = [i['url'] for i in self.json_de(dados)]
        self.assertIn('https://produto.mercadolivre.com.br/MLB-900000777', urls)
        self.assertNotIn('https://s.shopee.com.br/MlSem1', urls)

    def test_ca1_fetch_nao_aceita_link_da_shopee(self):
        for url in ('https://s.shopee.com.br/abc', 'https://shopee.com.br/product/1/2'):
            with self.subTest(url=url):
                st, _, dados = self.pedir('GET', '/api/fetch?url=' + url, None, self.local())
                self.assertEqual(st, 400, dados)

    def test_ca1_a_loja_do_item_fica_amarrada_ao_host_do_link_no_post(self):
        """Rodada 2 do E1: cada loja só aceita links do próprio host (o link curto da Shopee só em loja shopee)."""
        links = {'amazon': 'https://www.amazon.com.br/dp/B0AMARRA01?tag=desejodemen01-20',
                 'ml': 'https://meli.la/Amarra1', 'shopee': 'https://s.shopee.com.br/Amarra1'}
        for loja, bom in links.items():
            for outra, link in links.items():
                with self.subTest(loja=loja, link_de=outra):
                    iid = f'AM.{loja}.{outra}'
                    st, _, dados = self.postar([{'loja': loja, 'item_id': iid, 'url': link, 'data': {'titulo': 'x'}}])
                    if outra == loja:
                        self.assertEqual(st, 200, dados)
                        self.assertEqual(self.item(iid, loja)['url'], bom)
                    else:
                        self.assertEqual(st, 400, dados)
                        self.assertFalse([i for i in self.itens() if i['item_id'] == iid])
        for loja, url in (('amazon', 'https://amzn.to/AmazOk1'), ('amazon', 'https://amazon.com.br/dp/B0SEMWWW01'),
                          ('ml', 'https://produto.mercadolivre.com.br/MLB-900000123')):
            st, _, dados = self.postar([{'loja': loja, 'item_id': f'AMOK.{url[-6:]}', 'url': url}])
            self.assertEqual(st, 200, (url, dados))

    def test_ca1_patch_so_aceita_link_de_afiliado_da_loja_do_proprio_item(self):
        links = {'amazon': 'https://www.amazon.com.br/dp/B0PATCH001?tag=desejodemen01-20',
                 'ml': 'https://meli.la/Patch01', 'shopee': 'https://s.shopee.com.br/Patch01'}
        ids = {}
        for loja, link in links.items():
            self.postar([{'loja': loja, 'item_id': f'PT.{loja}', 'cat': CAT, 'url': link}])
            ids[loja] = self.item(f'PT.{loja}', loja)['id']
        novos = {'amazon': 'https://www.amazon.com.br/dp/B0PATCH002?tag=desejodemen01-20',
                 'ml': 'https://meli.la/Patch02', 'shopee': 'https://s.shopee.com.br/Patch02'}
        for loja, iid in ids.items():
            for de, link in novos.items():
                with self.subTest(loja=loja, link_de=de):
                    corpo = {'url': link} if de == loja else {'url': link, 'cat': 'Mudou'}
                    st, _, dados = self.pedir('PATCH', f'/api/items/{iid}', corpo, self.local())
                    if de == loja:
                        self.assertEqual(st, 200, dados)
                        self.assertEqual(self.item(f'PT.{loja}', loja)['url'], link)
                    else:
                        self.assertEqual(st, 400, dados)
                        # recusa antes de qualquer UPDATE: nem a cat do mesmo pedido muda
                        self.assertEqual(self.item(f'PT.{loja}', loja)['cat'], CAT)
                        self.assertNotEqual(self.item(f'PT.{loja}', loja)['url'], link)

    def test_ca1_upsert_troca_link_comum_por_afiliado_e_nunca_o_contrario_nas_tres_lojas(self):
        casos = {'amazon': ('https://www.amazon.com.br/dp/B0TROCA001', 'https://www.amazon.com.br/dp/B0TROCA001?tag=desejodemen01-20'),
                 'ml': ('https://produto.mercadolivre.com.br/MLB-900000321', 'https://meli.la/Troca01')}
        for loja, (comum, afiliado) in casos.items():
            with self.subTest(loja=loja):
                self.postar([{'loja': loja, 'item_id': f'TR.{loja}', 'url': comum, 'data': {'titulo': 'a'}}])
                self.assertEqual(self.item(f'TR.{loja}', loja)['url'], comum)
                self.postar([{'loja': loja, 'item_id': f'TR.{loja}', 'url': afiliado, 'data': {'titulo': 'b'}}])
                self.assertEqual(self.item(f'TR.{loja}', loja)['url'], afiliado)
                self.postar([{'loja': loja, 'item_id': f'TR.{loja}', 'url': comum, 'data': {'titulo': 'c'}}])
                it = self.item(f'TR.{loja}', loja)
                self.assertEqual((it['url'], it['data']['titulo']), (afiliado, 'c'), 'dados atualizam, o afiliado fica')

    def test_ca1_concorrencia_do_mesmo_item_shopee_deixa_uma_linha_e_o_primeiro_link(self):
        urls = [f'https://s.shopee.com.br/Conc{i}' for i in range(4)]
        barreira, resultados = threading.Barrier(len(urls)), []

        def postar(url):
            con = http.client.HTTPConnection('127.0.0.1', self.porta, timeout=15)
            con.connect()
            barreira.wait(10)
            corpo = json.dumps({'items': [{'loja': 'shopee', 'item_id': 'CONC.1', 'cat': CAT, 'url': url,
                                           'data': {'titulo': 'Concorrente', 'preco': 'R$ 9,00'}}]})
            con.request('POST', '/api/items', corpo, {**self.local(), 'Host': f'localhost:{self.porta}',
                                                       'Content-Type': 'application/json'})
            r = con.getresponse()
            resultados.append((r.status, json.loads(r.read())))
            con.close()

        ts = [threading.Thread(target=postar, args=(u,)) for u in urls]
        [t.start() for t in ts]
        [t.join(30) for t in ts]
        self.assertEqual([s for s, _ in resultados], [200] * 4, resultados)
        self.assertEqual(sum(j['inserido'] for _, j in resultados), 1)
        linhas = [i for i in self.itens() if i['item_id'] == 'CONC.1']
        self.assertEqual(len(linhas), 1)
        primeiro = linhas[0]['url']
        self.assertIn(primeiro, urls)
        self.postar([{'loja': 'shopee', 'item_id': 'CONC.1', 'url': 'https://s.shopee.com.br/Depois', 'data': {'titulo': 'Novo'}}])
        self.assertEqual(self.item('CONC.1')['url'], primeiro, 'o upsert nunca troca o link da Shopee')

    def test_ca1_origem_do_ml_com_loja_shopee_segue_a_mesma_regra(self):
        h = {'Host': f'localhost:{self.porta}', 'Origin': TS.ML_LISTA, 'Sec-Fetch-Site': 'cross-site'}
        st, _, _ = self.pedir('POST', '/api/items', {'items': [{'loja': 'shopee', 'item_id': 'ORI.1', 'url': 'https://s.shopee.com.br/x?y=1'}]}, h)
        self.assertEqual(st, 400)
        self.assertIsNone(self.item('ORI.1'))

    def test_ca1_listagem_devolve_a_loja_shopee_e_o_link_intactos(self):
        url = 'https://s.shopee.com.br/List0Ab'
        self.postar([{'loja': 'shopee', 'item_id': 'LST.1', 'cat': CAT, 'busca': 'Colônia feminina', 'url': url,
                      'data': {'titulo': 'Colônia', 'preco': 'R$ 10,00', 'vendas': '1.234 vendidos'}}])
        it = self.item('LST.1')
        self.assertEqual((it['loja'], it['url'], it['busca'], it['data']['vendas']), ('shopee', url, 'Colônia feminina', '1.234 vendidos'))


# ================================================================ as constantes repetidas em três lugares
class TestConstantesSemDeriva(unittest.TestCase):
    """O host do link curto e o do CDN da Shopee existem no servidor.py, no disparo.py e no index.html."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(T.RAIZ, 'index.html'), encoding='utf-8') as f:
            cls.html = f.read()

    def test_ca1_ca2_host_do_link_curto_igual_no_servidor_no_disparo_e_no_front(self):
        self.assertEqual(S.HOSTS_AFILIADO_SHOPEE, D.HOSTS_AFILIADO_SHOPEE)
        m = re.search(r"^const HOSTS_LINK = \{.*shopee:\[([^\]]*)\]\};$", self.html, re.M)
        self.assertIsNotNone(m, 'HOSTS_LINK com shopee não encontrado no index.html')
        self.assertEqual(tuple(re.findall(r"'([^']+)'", m.group(1))), S.HOSTS_AFILIADO_SHOPEE)

    def test_ca2_host_da_foto_igual_no_disparo_no_front_e_no_coletor(self):
        m = re.search(r"^const HOST_FOTO_SHOPEE = '([^']+)';", self.html, re.M)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), D.HOST_FOTO_SHOPEE)
        self.assertIn(D.HOST_FOTO_SHOPEE, D.HOSTS_FOTO)
        self.assertTrue(C.imagem_da_shopee(f'https://{D.HOST_FOTO_SHOPEE}/file/x'))

    def test_ca2_lojas_iguais_no_servidor_e_no_disparo_e_nomes_no_front(self):
        self.assertEqual(S.LOJAS, D.LOJAS)
        self.assertEqual(set(D.NOMES_LOJA), set(D.LOJAS))
        m = re.search(r"^const LOJA = \{(.*)\};$", self.html, re.M)
        self.assertEqual(dict(re.findall(r"(\w+):'([^']+)'", m.group(1))), D.NOMES_LOJA)

    def test_ca1_o_link_do_exemplo_de_cada_loja_passa_nas_tres_validacoes(self):
        for loja, url in (('amazon', 'https://www.amazon.com.br/dp/B0ABCDEFGH?tag=desejodemen01-20'),
                          ('ml', 'https://meli.la/AbC1234'), ('shopee', LINK)):
            self.assertTrue(S.eh_link_afiliado(url), loja)
            self.assertTrue(D.link_da_loja_ok(loja, url, S.eh_link_afiliado), loja)
            for outra in ('amazon', 'ml', 'shopee'):
                if outra != loja:
                    self.assertFalse(D.link_da_loja_ok(outra, url, S.eh_link_afiliado), (loja, outra))


# ================================================================ disparo (banco temporário, relógio injetado)
URL_SHOPEE_N = 'https://s.shopee.com.br/Cod{n}'
FOTO_SHOPEE_N = 'https://down-br.img.susercontent.com/file/f{n}'


class DisparoShopee(T.Base):
    def shopee(self, **campos):
        n = self.seq + 1
        campos.setdefault('imagem', FOTO_SHOPEE_N.format(n=n))
        url = campos.pop('url', URL_SHOPEE_N.format(n=n))
        return self.item(loja='shopee', url=url, **campos)

    def lojas(self, **kw):
        return [p['loja'] for p in D.previa(self.con, self.dados_regra(self.nid, **kw), 20, T.SEGUNDA, T.AFILIADO)]

    def setUp(self):
        super().setUp()
        self.nid = self.numero()['id']

    # ---- CA2: validação e padrão
    def test_ca2_lojas_da_regra_validas_e_invalidas(self):
        for lojas, esperado in ((['shopee'], ['shopee']), (['shopee', 'amazon'], ['amazon', 'shopee']),
                                (['ml', 'shopee', 'amazon'], ['amazon', 'ml', 'shopee'])):
            with self.subTest(lojas=lojas):
                self.assertEqual(self.regra(self.nid, lojas=lojas)['lojas'], esperado)
        for ruim in ([], ['Shopee'], ['shopee', 'shopee'], ['amazon', 'ml', 'shopee', 'outra'], ['outra'], 'shopee', None,
                     [None], [1], [['shopee']], ['shopee '], ['SHOPEE']):
            with self.subTest(ruim=ruim), self.assertRaises(D.ErroDisparo) as cm:
                self.regra(self.nid, lojas=ruim)
            self.assertEqual(cm.exception.codigo, 400)
        with self.assertRaises(D.ErroDisparo) as cm:
            self.regra(self.nid, lojas=['outra'])
        self.assertIn('amazon, ml e/ou shopee', str(cm.exception.args))

    def test_ca2_regra_sem_lojas_continua_amazon_e_ml_e_nao_pega_shopee(self):
        self.item(loja='amazon'); self.item(loja='ml'); self.shopee()
        dados = self.dados_regra(self.nid)
        dados.pop('lojas', None)
        r = D.criar_regra(self.con, dados)
        self.assertEqual(r['lojas'], ['amazon', 'ml'])
        self.assertEqual(sorted(self.lojas()), ['amazon', 'ml'])
        self.assertEqual(sorted(p['loja'] for p in D.previa(self.con, dados, 20, T.SEGUNDA, T.AFILIADO)), ['amazon', 'ml'])

    def test_ca2_regra_gravada_antes_com_amazon_e_ml_nao_muda_e_aceita_shopee_depois(self):
        with self.con:   # linha como a migração antiga deixou: coluna lojas pelo valor padrão
            cur = self.con.execute("INSERT INTO regras (nome, numero_id, cats, palavras, template, dias, horarios) "
                                   "VALUES ('antiga', ?, '[\"Eletrônicos\"]', '[]', 'Template 2', '[0,1,2,3,4]', '[\"09:00\"]')",
                                   (self.nid,))
        rid = cur.lastrowid
        self.assertEqual(D.obter_regra(self.con, rid)['lojas'], ['amazon', 'ml'])
        D.atualizar_regra(self.con, rid, {'nome': 'só o nome'})
        self.assertEqual(D.obter_regra(self.con, rid)['lojas'], ['amazon', 'ml'], 'atualizar outro campo não toca as lojas')
        self.assertEqual(D.atualizar_regra(self.con, rid, {'lojas': ['amazon', 'ml', 'shopee']})['lojas'],
                         ['amazon', 'ml', 'shopee'])
        with self.assertRaises(D.ErroDisparo):
            D.atualizar_regra(self.con, rid, {'lojas': ['shopee', 'shopee']})
        self.assertEqual(D.obter_regra(self.con, rid)['lojas'], ['amazon', 'ml', 'shopee'])

    # ---- CA2: seleção e previa com loja
    def test_ca2_previa_devolve_a_loja_de_cada_item_e_o_filtro_respeita_lojas(self):
        a, m, s = self.item(loja='amazon'), self.item(loja='ml'), self.shopee()
        p = D.previa(self.con, self.dados_regra(self.nid, lojas=['amazon', 'ml', 'shopee']), 20, T.SEGUNDA, T.AFILIADO)
        self.assertEqual({x['item_pk']: x['loja'] for x in p}, {a: 'amazon', m: 'ml', s: 'shopee'})
        self.assertEqual([x['item_pk'] for x in D.previa(self.con, self.dados_regra(self.nid, lojas=['shopee']), 20,
                                                         T.SEGUNDA, T.AFILIADO)], [s])
        self.assertEqual(sorted(self.lojas(lojas=['amazon', 'shopee'])), ['amazon', 'shopee'])

    def test_ca2_item_shopee_so_sai_com_o_link_curto_de_afiliado_da_shopee(self):
        n_ok = self.shopee()
        for ruim in LINKS_RUINS:
            if isinstance(ruim, str) and ruim:
                self.shopee(url=ruim)
        escolhidos = D.previa(self.con, self.dados_regra(self.nid, lojas=['shopee']), 20, T.SEGUNDA, T.AFILIADO)
        self.assertEqual([p['item_pk'] for p in escolhidos], [n_ok])
        self.assertEqual(escolhidos[0]['mensagem'].count('https://'), 1, 'um só link na mensagem')
        self.assertIn(URL_SHOPEE_N.format(n=1), escolhidos[0]['mensagem'])

    def test_ca2_link_de_afiliado_de_outra_loja_nao_sai_em_item_shopee_nem_o_link_da_shopee_em_outras(self):
        self.shopee(url='https://www.amazon.com.br/dp/B0CRUZADO1?tag=desejodemen01-20')
        self.shopee(url='https://meli.la/Cruzado')
        self.item(loja='amazon', url='https://s.shopee.com.br/CruzAmz1')
        self.item(loja='ml', url='https://s.shopee.com.br/CruzMl01')
        self.assertEqual(self.lojas(lojas=['amazon', 'ml', 'shopee']), [])

    def test_ca2_item_shopee_sem_titulo_ou_preco_nao_sai(self):
        self.shopee(titulo='')
        self.shopee(preco='')
        self.shopee(tem_dados=0)
        self.assertEqual(self.lojas(lojas=['shopee']), [])

    def test_ca2_foto_so_do_cdn_e_so_com_com_foto(self):
        boas = self.shopee()
        fotos = {'https://down-br.img.susercontent.com.evil.com/f': '', 'http://down-br.img.susercontent.com/f': '',
                 'https://evil.com/down-br.img.susercontent.com/f': '', 'https://u@down-br.img.susercontent.com/f': '',
                 'https://down-br.img.susercontent.com:444/f': '',
                 'javascript:alert(1)': '', '': ''}
        fotos['https://m.media-amazon.com/images/I/x.jpg'] = ''    # CDN de outra loja: o item sai sem foto
        fotos['https://http2.mlstatic.com/D_NQ_NP_1-F.jpg'] = ''
        pks = {self.shopee(imagem=f): f for f in fotos}
        por_pk = {p['item_pk']: p['imagem'] for p in D.previa(self.con, self.dados_regra(self.nid, lojas=['shopee']), 20,
                                                              T.SEGUNDA, T.AFILIADO)}
        self.assertTrue(por_pk[boas].startswith('https://down-br.img.susercontent.com/'))
        for pk, f in pks.items():
            self.assertEqual(por_pk[pk], '', f)
        sem = D.previa(self.con, self.dados_regra(self.nid, lojas=['shopee'], com_foto=0), 20, T.SEGUNDA, T.AFILIADO)
        self.assertEqual({p['imagem'] for p in sem}, {''})

    # ---- CA2: mensagem
    def test_ca2_loja_vira_shopee_na_mensagem_e_o_link_e_o_do_item(self):
        self.gravar_templates({'T': 'Na {LOJA}: {TITULO_PRODUTO} por {PRECO_PRODUTO}\n{LINK}'})
        pk = self.shopee(titulo='Colônia Floral')
        outros = [self.item(loja='amazon'), self.item(loja='ml')]
        p = {x['item_pk']: x['mensagem'] for x in D.previa(
            self.con, self.dados_regra(self.nid, lojas=['amazon', 'ml', 'shopee'], template='T'), 20, T.SEGUNDA, T.AFILIADO)}
        self.assertEqual(p[pk], f'Na Shopee: Colônia Floral por R$ 100,00\n{URL_SHOPEE_N.format(n=pk)}')
        self.assertTrue(p[outros[0]].startswith('Na Amazon: '))
        self.assertTrue(p[outros[1]].startswith('Na Mercado Livre: '))
        for pk_, m in p.items():
            self.assertEqual(len(re.findall(r'https://', m)), 1, m)

    def test_ca2_titulo_com_link_em_item_shopee_e_recusado_e_contado(self):
        for titulo in ('Perfume https://evil.com/x grátis', 'Veja https://s.shopee.com.br/Outro123', 'perfume.com.br oferta',
                       'Ligue www.golpe.com'):
            with self.subTest(titulo=titulo):
                self.shopee(titulo=titulo)
        info = {}
        p = D.previa(self.con, self.dados_regra(self.nid, lojas=['shopee']), 20, T.SEGUNDA, T.AFILIADO, info=info)
        self.assertEqual(p, [])
        self.assertEqual(info['recusados'], 4)

    def test_ca2_ordenacao_pelos_textos_que_o_coletor_grava(self):
        """O que o coletar_shopee escreve em `vendas`, `avaliacao`, `preco` e `desconto` é lido pelo disparo."""
        nos = [(50, 4.9, 'a'), (12345, 4.6, 'b'), (999, 5.0, 'c'), (1000, 4.5, 'd')]
        pks = {}
        for i, (vendas, nota, nome) in enumerate(nos, 1):
            it = C.no_para_item({'itemId': i, 'shopId': 7, 'productName': f'Perfume {nome}', 'priceMin': 1000 * i + 0.5,
                                 'priceDiscountRate': 10 * i, 'ratingStar': nota, 'sales': vendas, 'imageUrl': FOTO,
                                 'offerLink': f'https://s.shopee.com.br/Ord{i}'}, 'Perfume', 'Eletrônicos')
            self.assertEqual(S.upsert(self.con, it), 'inserido')
            pks[nome] = self.con.execute("SELECT id FROM items WHERE item_id=?", (f'7.{i}',)).fetchone()[0]
        self.con.commit()

        def ordem(**kw):
            r = D.previa(self.con, self.dados_regra(self.nid, lojas=['shopee'], **kw), 20, T.SEGUNDA, T.AFILIADO)
            return [p['titulo'][-1] for p in r]
        self.assertEqual(ordem(ordem='relevancia'), ['b', 'd', 'c', 'a'])      # vendas 12.345, 1.000, 999, 50
        self.assertEqual(ordem(ordem='desconto'), ['d', 'c', 'b', 'a'])        # -40%, -30%, -20%, -10%
        self.assertEqual(ordem(ordem='maior_preco'), ['d', 'c', 'b', 'a'])     # R$ 4.000,50 ... R$ 1.000,50
        self.assertEqual(ordem(ordem='menor_preco'), ['a', 'b', 'c', 'd'])
        self.assertEqual(sorted(ordem(desconto_min=30, ordem='desconto')), ['c', 'd'])

    # ---- CA2: ponta a ponta com o relógio injetado
    def test_ca2_tick_enfileira_item_shopee_com_link_e_foto_e_nao_repete(self):
        self.gravar_templates({'T': '{LOJA}|{TITULO_PRODUTO}|{LINK}'})
        pk = self.shopee(titulo='Body splash')
        r = self.regra(self.nid, lojas=['shopee'], template='T', horarios=['09:00'], dias=[0])
        self.assertEqual(self.tick(T.SEGUNDA.replace(hour=9, second=3))['criados'], 1)
        e = self.envios()
        self.assertEqual(len(e), 1)
        self.assertEqual((e[0]['item_pk'], e[0]['status'], e[0]['regra_id']), (pk, 'pendente', r['id']))
        self.assertEqual(e[0]['mensagem'], f'Shopee|Body splash|{URL_SHOPEE_N.format(n=pk)}')
        self.assertEqual(e[0]['imagem'], FOTO_SHOPEE_N.format(n=pk))
        self.assertEqual(self.tick(T.SEGUNDA.replace(hour=9, second=40))['criados'], 0, 'mesmo horário não repete')
        self.assertEqual(len(self.envios()), 1)

    def test_ca2_tick_nao_envia_item_shopee_com_link_trocado_depois_de_gravado(self):
        """Mesmo que o link seja trocado no banco por um de outra loja, nada sai."""
        pk = self.shopee()
        self.regra(self.nid, lojas=['shopee'], horarios=['09:00'], dias=[0])
        with self.con:
            self.con.execute('UPDATE items SET url=? WHERE id=?', ('https://meli.la/Trocado', pk))
        self.assertEqual(self.tick(T.SEGUNDA.replace(hour=9, second=3))['criados'], 0)
        self.assertEqual(self.envios(), [])
        self.assertTrue(D.obter_regra(self.con, 1)['aviso'], 'a regra avisa que nada saiu')


# ================================================================ rotas /api/disparo/* com loja shopee
class TestRotasShopee(TD.ServidorDisparo):
    DISPARO = '0'

    def setUp(self):
        import sqlite3
        with sqlite3.connect(self.db) as con:
            con.executescript('DELETE FROM envios; DELETE FROM regras; DELETE FROM numeros; DELETE FROM items;')
        con.close()
        self.preparar()
        st, _, d = self.postar([
            {'loja': 'shopee', 'item_id': '1.1', 'cat': 'Eletrônicos', 'url': 'https://s.shopee.com.br/RotaOk1',
             'data': {'titulo': 'Item Shopee', 'preco': 'R$ 20,00', 'desconto': '-30%',
                      'imagem': 'https://down-br.img.susercontent.com/file/x'}}])
        self.assertEqual(st, 200, d)

    def corpo(self, nid, **kw):
        return {'nome': 'R', 'numero_id': nid, 'cats': ['Eletrônicos'], 'template': 'Template 2', 'horarios': ['09:00'], **kw}

    def test_ca2_regra_com_shopee_grava_e_a_previa_traz_a_loja_de_cada_item(self):
        nid = self.numero()['id']
        r = self.ok('POST', 'regras', self.corpo(nid, lojas=['shopee', 'amazon']))
        self.assertEqual(r['lojas'], ['amazon', 'shopee'])
        self.assertEqual([x['lojas'] for x in self.ok('GET', 'regras')], [['amazon', 'shopee']])
        p = self.ok('POST', 'previa', {**self.corpo(nid, lojas=['amazon', 'ml', 'shopee']), 'n': 20})
        self.assertEqual(sorted(x['loja'] for x in p), ['amazon', 'amazon', 'amazon', 'shopee'])
        so = self.ok('POST', 'previa', {**self.corpo(nid, lojas=['shopee']), 'n': 20})
        self.assertEqual([(x['loja'], x['titulo']) for x in so], [('shopee', 'Item Shopee')])
        self.assertIn('https://s.shopee.com.br/RotaOk1', so[0]['mensagem'])

    def test_ca2_regra_sem_lojas_nasce_amazon_e_ml(self):
        nid = self.numero()['id']
        r = self.ok('POST', 'regras', self.corpo(nid))
        self.assertEqual(r['lojas'], ['amazon', 'ml'])
        p = self.ok('POST', 'previa', {**self.corpo(nid), 'n': 20})
        self.assertNotIn('shopee', [x['loja'] for x in p])

    def test_ca2_lojas_invalidas_dao_400_com_a_mensagem_nova_e_nao_gravam(self):
        nid = self.numero()['id']
        for ruim in (['Shopee'], [], ['amazon', 'amazon'], ['shopee', 'outra'], 'shopee'):
            with self.subTest(ruim=ruim):
                st, j = self.api('POST', 'regras', self.corpo(nid, lojas=ruim))
                self.assertEqual(st, 400, j)
                self.assertIn('lojas', j['error'])
        self.assertEqual(self.ok('GET', 'regras'), [])
        st, j = self.api('POST', 'regras', self.corpo(nid, lojas=['outra']))
        self.assertIn('amazon, ml e/ou shopee', j['error'])

    def test_ca2_atualizar_lojas_da_regra_para_shopee(self):
        nid = self.numero()['id']
        rid = self.ok('POST', 'regras', self.corpo(nid))['id']
        r = self.ok('PUT', f'regras/{rid}', {'lojas': ['shopee']})
        self.assertEqual(r['lojas'], ['shopee'])
        self.assertEqual(self.ok('GET', 'regras')[0]['lojas'], ['shopee'])
        self.assertEqual(self.api('PUT', f'regras/{rid}', {'lojas': ['x']})[0], 400)
        self.assertEqual(self.ok('GET', 'regras')[0]['lojas'], ['shopee'])


# ================================================================ coletar_shopee
def no(**k):
    base = {'itemId': 22334455667, 'shopId': 112233, 'productName': 'Perfume Floral 100ml', 'priceMin': '1234.5',
            'priceDiscountRate': 20, 'ratingStar': '4.8', 'sales': 1234, 'imageUrl': FOTO, 'offerLink': LINK}
    base.update(k)
    return base


def resposta(nos):
    return {'data': {'productOfferV2': {'nodes': nos}}}


def erro(codigo, mensagem='falhou'):
    return {'errors': [{'message': mensagem, 'extensions': {'code': codigo, 'message': mensagem}}]}


class Resp(io.BytesIO):
    pass


class ApiFalsa:
    """urlopen falso: devolve as respostas da fila (dict, bytes ou exceção) e guarda as requisições."""
    def __init__(self, *fila):
        self.fila, self.pedidos = list(fila), []

    def __call__(self, req, timeout=None):
        self.pedidos.append(req)
        r = self.fila.pop(0) if self.fila else resposta([])
        if isinstance(r, BaseException):
            raise r
        return Resp(r if isinstance(r, bytes) else json.dumps(r).encode())


class ConferenciaFalsa:
    def __init__(self, location=DESTINO_BOM, codigo=302):
        self.location, self.codigo, self.links = location, codigo, []

    def __call__(self, req, timeout=None):
        self.links.append(req.full_url)
        h = http.client.HTTPMessage()
        if self.location is not None:
            h['Location'] = self.location
        raise urllib.error.HTTPError(req.full_url, self.codigo, 'x', h, io.BytesIO(b''))


class ColetaBase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(dir=TMP)
        self.db = os.path.join(self.dir, 'banco.db')
        self.feitos_arq = os.path.join(self.dir, 'feitos.txt')
        self.buscas = os.path.join(self.dir, 'buscas.json')
        with open(self.buscas, 'w', encoding='utf-8') as f:
            json.dump({CAT: ['Perfume feminino importado', 'Body splash', 'Kit perfume'], 'Outra': ['x']}, f)
        for alvo, nome, v in ((C, 'BUSCAS', self.buscas), (C, 'ID_AFILIADO_SHOPEE', ID), (C, 'FEITOS', self.feitos_arq),
                              (C, 'pausa', lambda *a, **k: None), (S, 'DB', self.db)):
            p = mock.patch.object(alvo, nome, v); p.start(); self.addCleanup(p.stop)

    def rodar(self, argv, api=None, conf=None, env=ENV):
        api = api if api is not None else ApiFalsa()
        conf = conf or ConferenciaFalsa()
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, env), mock.patch.object(C.OPENER_API, 'open', api), \
                mock.patch.object(C.OPENER_CONFERENCIA, 'open', conf), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                codigo = C.main(argv)
            except SystemExit as e:
                codigo = e.code
        self.api, self.conf = api, conf
        saida = out.getvalue() + err.getvalue()
        self.assertNotIn(SECRET, saida, 'o Secret apareceu na saída')
        self.assertNotIn('Traceback', saida)
        return codigo, out.getvalue(), err.getvalue()

    def itens(self):
        if not os.path.exists(self.db):
            return []
        con = S.conectar()
        try:
            return [dict(r) for r in con.execute('SELECT * FROM items ORDER BY id')]
        except Exception:
            return []
        finally:
            con.close()

    def feitos(self):
        if not os.path.exists(self.feitos_arq):
            return []
        with open(self.feitos_arq, encoding='utf-8') as f:
            return f.read().splitlines()

    def nada_gravado(self):
        self.assertEqual(self.itens(), [])
        self.assertEqual(self.feitos(), [])


class TestAssinaturaEConsulta(ColetaBase):
    def test_ca7_a_assinatura_confere_com_o_corpo_e_o_timestamp_que_foram_enviados(self):
        for termo in ('Colônia feminina', 'Perfume "árabe" \\ {x}', 'Kit perfume com hidratante 🌸'):
            with self.subTest(termo=termo):
                api = ApiFalsa(resposta([]))
                mock_cred = (APP_ID, C.Segredo(SECRET))
                with mock.patch.object(C.OPENER_API, 'open', api):
                    C.buscar(mock_cred, termo, 'vendidos')
                req = api.pedidos[0]
                m = re.fullmatch(r'SHA256 Credential=([^,]+), Timestamp=(\d+), Signature=([0-9a-f]{64})',
                                 req.get_header('Authorization'))
                self.assertIsNotNone(m, req.get_header('Authorization'))
                app, ts, assinatura = m.groups()
                self.assertEqual(app, APP_ID)
                esperado = hashlib.sha256((APP_ID + ts).encode() + req.data + SECRET.encode()).hexdigest()
                self.assertEqual(assinatura, esperado, 'a assinatura tem de cobrir os bytes exatos do corpo enviado')
                corpo = json.loads(req.data)
                self.assertEqual(corpo['variables']['keyword'], termo)
                self.assertEqual(corpo['variables']['sortType'], 2)
                self.assertEqual(corpo['query'], C.CONSULTA)
                self.assertNotIn(termo, corpo['query'])
                self.assertEqual((req.get_method(), req.full_url), ('POST', C.URL_API))
                for parte in (req.full_url, req.data.decode(), *[str(v) for v in req.header_items()]):
                    self.assertNotIn(SECRET, parte)
                req.data.decode('ascii')   # sem bytes fora do ASCII: a assinatura não depende de codificação

    def test_ca7_ordens_usam_o_sort_type_do_plano(self):
        for ordem, st in (('relevancia', 1), ('vendidos', 2), ('caros', 3)):
            api = ApiFalsa(resposta([]))
            with mock.patch.object(C.OPENER_API, 'open', api):
                C.buscar((APP_ID, C.Segredo(SECRET)), 'x', ordem)
            self.assertEqual(json.loads(api.pedidos[0].data)['variables']['sortType'], st, ordem)
        self.assertEqual(set(C.ORDENS), {'relevancia', 'vendidos', 'caros'}, 'sem ordem por comissão (decisão do dono)')

    def test_ca7_a_url_da_api_nao_depende_do_ambiente(self):
        for var in ('ACHADINHOS_SHOPEE_URL', 'ACHADINHOS_SHOPEE_API', 'SHOPEE_URL', 'ACHADINHOS_URL_API'):
            api = ApiFalsa(resposta([]))
            with mock.patch.dict(os.environ, {var: 'https://evil.com/graphql'}), \
                    mock.patch.object(C.OPENER_API, 'open', api):
                C.buscar((APP_ID, C.Segredo(SECRET)), 'x', 'relevancia')
            self.assertEqual(api.pedidos[0].full_url, 'https://open-api.affiliate.shopee.com.br/graphql')
        with open(os.path.join(T.RAIZ, 'coletar_shopee.py'), encoding='utf-8') as f:
            fonte = f.read()
        self.assertEqual(len(re.findall(r'OPENER_API\.open\(', fonte)), 1, 'um único ponto que fala com a API, com host fixo')
        self.assertNotIn('urlopen(', fonte)

    def test_ca7_termos_da_aba_vao_sempre_como_variavel(self):
        con_base = json.dumps({'query': C.CONSULTA})
        for termo in ('", sortType: 5) { __typename }', '\n', '{ itemId }', '‮', 'a' * 5000, "'; DROP"):
            with self.subTest(termo=termo[:20]):
                corpo = json.loads(C.corpo_consulta(termo, 1))
                self.assertEqual(corpo['query'], json.loads(con_base)['query'])
                self.assertEqual(corpo['variables']['keyword'], termo)
                self.assertEqual(set(corpo), {'query', 'variables'})


class TestPisoEMapeamento(ColetaBase):
    def test_ca7_piso_de_qualidade_nas_bordas(self):
        # P1 de 2026-11-04 (abas-nichadas-e-coleta.md): nota >= 4,5 e >= 50 vendas
        casos = [((4.5, 50), True), ((4.5, '50'), True), ((5, 50), True), ((4.49, 100), False), ((4.4999, 50), False),
                 ((4.5, 49), False), ((4.5, '49'), False), ((5, 49.99), False), ((5, 1), False),
                 ((4.5, 0), False), ((4.5, '0'), False), ((5, -1), False), (('x', 5), False), ((None, 5), False),
                 ((4.8, None), False), ((4.8, 'abc'), False), ((True, 1), False), ((4.8, True), False),
                 ((float('nan'), 1), False), ((4.8, float('inf')), False), ((-4.8, 5), False), (('4,8', 5), False)]
        for (nota, vendas), passa in casos:
            with self.subTest(nota=nota, vendas=vendas):
                it = C.no_para_item(no(ratingStar=nota, sales=vendas), 't', CAT)
                self.assertEqual(it is not None, passa)

    def test_ca7_so_o_link_curto_de_afiliado_da_shopee_vira_item(self):
        for ruim in LINKS_RUINS:
            with self.subTest(link=ruim):
                self.assertIsNone(C.no_para_item(no(offerLink=ruim), 't', CAT))
        self.assertIsNone(C.no_para_item({k: v for k, v in no().items() if k != 'offerLink'}, 't', CAT))
        self.assertIsNotNone(C.no_para_item(no(), 't', CAT))

    def test_ca7_campos_malformados_descartam_o_no_sem_levantar(self):
        for nome, k in (('shopId ausente', {'shopId': None}), ('itemId texto', {'itemId': 'abc'}), ('itemId negativo', {'itemId': -1}),
                        ('itemId float', {'itemId': 1.5}), ('título vazio', {'productName': ''}),
                        ('título só espaços', {'productName': ' \t\n'}), ('título número', {'productName': 5}),
                        ('título lista', {'productName': ['a']})):
            with self.subTest(nome):
                self.assertIsNone(C.no_para_item(no(**k), 't', CAT))
        for lixo in (None, 5, 'x', [], [no()], b'x'):
            self.assertIsNone(C.no_para_item(lixo, 't', CAT))

    def test_ca7_texto_hostil_e_so_texto_e_cortado(self):
        it = C.no_para_item(no(productName='A\x00B\r\n\x1b[31mC\u0085D ' + 'x' * 5000), 't', CAT)
        self.assertLessEqual(len(it['data']['titulo']), S.MAX_TITULO)
        self.assertNotRegex(it['data']['titulo'], r'[\x00-\x1f\x7f-\x9f]')
        self.assertEqual(it['item_id'], '112233.22334455667')
        self.assertEqual(it['loja'], 'shopee')
        self.assertEqual(it['busca'], 't')
        self.assertEqual(it['cat'], CAT)
        self.assertEqual(it['url'], LINK)
        S.conferir_tipos(it, ('url', 'item_id', 'cat', 'busca'))

    def test_ca7_numeros_e_textos_do_item(self):
        d = C.no_para_item(no(priceMin=1234567.891, priceDiscountRate=99, ratingStar=4.55, sales=50), 't', CAT)['data']
        self.assertEqual(d['preco'], 'R$ 1.234.567,89')
        self.assertEqual(d['desconto'], '-99%')
        self.assertEqual(d['vendas'], '50 vendidos')
        self.assertEqual(D.nota(d['avaliacao']), 4.5 if d['avaliacao'].startswith('4.5') else 4.6)
        for preco in (0, -5, 'abc', '1e3', None, 10**12, float('nan'), True):
            self.assertEqual(C.no_para_item(no(priceMin=preco), 't', CAT)['data']['preco'], '', preco)
        for taxa, esperado in ((0, ''), (100, ''), (150, ''), (-10, ''), ('15', '-15%'), (20.9, '-20%'), (None, ''), ('x', '')):
            self.assertEqual(C.no_para_item(no(priceDiscountRate=taxa), 't', CAT)['data']['desconto'], esperado, taxa)
        self.assertEqual(C.no_para_item(no(sales=1000), 't', CAT)['data']['vendas'], '1.000 vendidos')
        self.assertEqual(C.no_para_item(no(ratingStar=9), 't', CAT)['data']['avaliacao'], '5.0 de 5 estrelas')
        self.assertEqual(C.no_para_item(no(), 't', CAT)['data']['preco_antigo'], '', 'sem preço inventado')

    def test_ca7_foto_so_do_cdn_da_shopee(self):
        for foto in (FOTO, 'https://down-br.img.susercontent.com/a/b.jpg'):
            self.assertEqual(C.no_para_item(no(imageUrl=foto), 't', CAT)['data']['imagem'], foto)
        for foto in ('http://down-br.img.susercontent.com/a', 'https://m.media-amazon.com/a.jpg', 'https://evil.com/a',
                     'https://down-br.img.susercontent.com.evil.com/a', None, 5, '', 'https://down-br.img.susercontent.com/' + 'a' * 300):
            self.assertEqual(C.no_para_item(no(imageUrl=foto), 't', CAT)['data']['imagem'], '', foto)

    def test_ca7_destino_do_dono_hostil(self):
        bons = [DESTINO_BOM, f'https://www.shopee.com.br/x?utm_source=an_{ID}', f'https://shopee.com.br:443/x?utm_source=an_{ID}',
                f'https://SHOPEE.COM.BR/x?a=1&utm_source=an_{ID}&b=2']
        ruins = [f'https://shopee.com.br.evil.com/p?utm_source=an_{ID}', f'https://evilshopee.com.br/p?utm_source=an_{ID}',
                 f'http://shopee.com.br/p?utm_source=an_{ID}', f'https://shopee.com.br/p?utm_source=an_{ID}9',
                 f'https://shopee.com.br/p?utm_source=an_{ID[:-1]}', f'https://shopee.com.br/p?utm_source=an_{ID}&utm_source=an_999',
                 f'https://shopee.com.br/p?x=utm_source=an_{ID}', f'https://shopee.com.br/p#utm_source=an_{ID}',
                 f'https://shopee.com.br:8443/p?utm_source=an_{ID}', f'https://u@shopee.com.br/p?utm_source=an_{ID}',
                 f'https://shopee.com.br\\@evil.com/p?utm_source=an_{ID}', f'//shopee.com.br/p?utm_source=an_{ID}',
                 f'/product/1?utm_source=an_{ID}', f'https://shopee.com.br/p?utm_source=AN_{ID}',
                 f'https://shopee.com.br/p?UTM_SOURCE=an_{ID}', f'https://shopee.com.br/p?utm_source=an_{ID} ',
                 f' https://shopee.com.br/p?utm_source=an_{ID}', f'https://shopee.com.br/p?utm_source=an_{ID}\n',
                 'https://shopee.com.br/p', 'https://shopee.com.br/p?utm_source=an_', 'https://shopee.com.br/p?utm_source=',
                 f'https://s.shopee.com.br.evil.com/p?utm_source=an_{ID}', f'https://shopee.com.br/?utm_source=an_999&u=an_{ID}',
                 '', None, 5, b'https://shopee.com.br/p', 'a' * 100000]
        for loc in bons:
            with self.subTest(bom=loc):
                self.assertTrue(C.dono_ok(loc))
        for loc in ruins:
            with self.subTest(ruim=loc[:80] if isinstance(loc, str) else loc):
                self.assertFalse(C.dono_ok(loc))
        for vazio in ('', 'abc', '0x1', '-1', ' 1', '1 ', '١٢٣', ID + 'x'):
            with self.subTest(id_afiliado=vazio), mock.patch.object(C, 'ID_AFILIADO_SHOPEE', vazio):
                self.assertFalse(C.dono_ok(DESTINO_BOM.replace(ID, vazio)))


class TestColetaDeVerdade(ColetaBase):
    def test_ca7_piso_na_coleta_so_grava_quem_passa(self):
        nos = [no(itemId=1, ratingStar=4.5, sales=50), no(itemId=2, ratingStar=4.49, sales=500),
               no(itemId=3, ratingStar=5, sales=49), no(itemId=4, ratingStar=4.9, sales=70, offerLink='https://s.shopee.com.br/x?y=1'),
               no(itemId=5, ratingStar=4.7, sales=51, offerLink='https://s.shopee.com.br/Cinco5')]
        cod, saida, _ = self.rodar(['buscas', '--cat', CAT], ApiFalsa(resposta(nos), resposta([]), resposta([])))
        self.assertEqual(cod, 0)
        self.assertEqual(sorted(i['item_id'] for i in self.itens()), ['112233.1', '112233.5'])
        for i in self.itens():
            self.assertTrue(S.eh_link_afiliado(i['url']))
            self.assertEqual((i['loja'], i['cat'], i['busca']), ('shopee', CAT, 'Perfume feminino importado'))
        self.assertEqual(self.feitos(), ['relevancia|Perfume feminino importado'])

    def test_ca7_mais_de_30_nos_ficam_em_30(self):
        nos = [no(itemId=i, offerLink=f'https://s.shopee.com.br/N{i}') for i in range(1, 80)]
        self.rodar(['buscas', '--cat', CAT], ApiFalsa(resposta(nos), resposta([]), resposta([])))
        self.assertEqual(len(self.itens()), C.POR_BUSCA)

    def test_ca7_o_mesmo_item_em_duas_ordens_vira_uma_linha_com_o_primeiro_link(self):
        a = no(offerLink='https://s.shopee.com.br/Primeiro1')
        b = no(offerLink='https://s.shopee.com.br/Segundo2', productName='Título novo')
        cod, _, _ = self.rodar(['buscas', '--cat', CAT, '--ordens', 'relevancia,vendidos'],
                               ApiFalsa(resposta([a]), resposta([b]), *[resposta([])] * 4))
        self.assertEqual(cod, 0)
        linhas = [i for i in self.itens() if i['item_id'] == '112233.22334455667']
        self.assertEqual(len(linhas), 1)
        self.assertEqual(linhas[0]['url'], 'https://s.shopee.com.br/Primeiro1')
        self.assertEqual(linhas[0]['titulo'], 'Título novo', 'os dados são atualizados, o link não')

    def test_ca7_segunda_rodada_nao_chama_a_api_para_termo_feito(self):
        cheia = lambda: ApiFalsa(*[resposta([no(itemId=i, offerLink=f'https://s.shopee.com.br/R{i}')]) for i in range(1, 4)])
        self.assertEqual(self.rodar(['buscas', '--cat', CAT], cheia())[0], 0)
        self.assertEqual(len(self.feitos()), 3)
        api = ApiFalsa()
        self.assertEqual(self.rodar(['buscas', '--cat', CAT], api)[0], 0)
        self.assertEqual(api.pedidos, [])

    def test_ca7_termo_sem_item_no_piso_nao_marca_progresso(self):
        cod, saida, _ = self.rodar(['buscas', '--cat', CAT], ApiFalsa(*[resposta([no(sales=0)])] * 3))
        self.assertEqual(cod, 0)
        self.assertEqual(self.itens(), [])
        self.assertEqual(self.feitos(), [])
        self.assertEqual(self.conf.links, [], 'sem item válido não há o que conferir')

    def test_ca7_conferencia_so_do_primeiro_termo_e_ruim_aborta_sem_gravar(self):
        for loc in (DESTINO_BOM.replace(ID, '999'), None, 'https://evil.com/?utm_source=an_' + ID):
            with self.subTest(loc=loc):
                self.setUp()
                cod, _, err = self.rodar(['buscas', '--cat', CAT, '--ordens', 'relevancia,vendidos,caros'],
                                         ApiFalsa(resposta([no()])), ConferenciaFalsa(loc))
                self.assertEqual(cod, 1)
                self.assertIn('Nada foi gravado', err)
                self.nada_gravado()
                self.assertEqual(len(self.api.pedidos), 1, 'para na primeira resposta')

    def test_ca7_conferencia_boa_confere_uma_vez_so_e_o_link_do_primeiro_item(self):
        nos = [no(itemId=1, offerLink='https://s.shopee.com.br/Um1'), no(itemId=2, offerLink='https://s.shopee.com.br/Dois2')]
        self.rodar(['buscas', '--cat', CAT, '--ordens', 'relevancia,caros'], ApiFalsa(resposta(nos), resposta(nos), *[resposta([])] * 4))
        self.assertEqual(self.conf.links, ['https://s.shopee.com.br/Um1'])

    def test_ca7_conferencia_nao_segue_redirect_de_verdade_e_so_abre_link_curto(self):
        self.assertIsNone(C.destino('https://evil.com/x'))
        self.assertIsNone(C.destino('https://s.shopee.com.br/x?y=1'))
        self.assertIsNone(C.destino('http://s.shopee.com.br/x'))
        for codigo in (200, 404, 500):
            conf = ConferenciaFalsa('https://shopee.com.br/?utm_source=an_' + ID, codigo)
            with mock.patch.object(C.OPENER_CONFERENCIA, 'open', conf):
                self.assertIsNone(C.destino(LINK), codigo)
        for codigo in (301, 302, 303, 307, 308):
            with mock.patch.object(C.OPENER_CONFERENCIA, 'open', ConferenciaFalsa(DESTINO_BOM, codigo)):
                self.assertEqual(C.destino(LINK), DESTINO_BOM)

    def test_ca7_limite_no_meio_da_segunda_ordem_preserva_exatamente_o_que_foi_gravado(self):
        un = lambda i: resposta([no(itemId=i, offerLink=f'https://s.shopee.com.br/L{i}')])
        # a ordem do laço é termo por termo: (t1 rel) (t1 vendidos) (t2 rel) e o limite vem no (t2 vendidos)
        api = ApiFalsa(un(1), un(2), un(3), erro(10030, SECRET))
        cod, _, err = self.rodar(['buscas', '--cat', CAT, '--ordens', 'relevancia,vendidos'], api)
        self.assertEqual(cod, 3)
        self.assertIn('limite de requisições', err)
        self.assertIn('progresso foi salvo', err)
        self.assertEqual(self.feitos(), ['relevancia|Perfume feminino importado', 'vendidos|Perfume feminino importado',
                                         'relevancia|Body splash'])
        self.assertEqual(len(self.itens()), 3)
        api2 = ApiFalsa(*[resposta([])] * 10)
        self.assertEqual(self.rodar(['buscas', '--cat', CAT, '--ordens', 'relevancia,vendidos'], api2)[0], 0)
        self.assertEqual([json.loads(p.data)['variables']['keyword'] + '|' + str(json.loads(p.data)['variables']['sortType'])
                          for p in api2.pedidos],
                         ['Body splash|2', 'Kit perfume|1', 'Kit perfume|2'], 'retoma só do que faltou')

    def test_ca7_limite_por_http_429_e_4xx_com_codigo_no_corpo(self):
        def http_erro(codigo, corpo):
            return urllib.error.HTTPError(C.URL_API, codigo, 'x', http.client.HTTPMessage(), io.BytesIO(json.dumps(corpo).encode()))
        for exc in (http_erro(429, {}), http_erro(200, erro(10030)), http_erro(403, erro(10030, SECRET)),
                    http_erro(500, erro(10030)), http_erro(400, erro('10030'))):
            with self.subTest(status=exc.code):
                self.setUp()
                cod, _, err = self.rodar(['buscas', '--cat', CAT], ApiFalsa(exc))
                self.assertEqual(cod, 3, err)
                self.nada_gravado()

    def test_ca7_erros_da_api_so_mostram_codigo_ou_status(self):
        def http_erro(codigo, corpo):
            return urllib.error.HTTPError(C.URL_API, codigo, 'x', http.client.HTTPMessage(), io.BytesIO(corpo))
        for resp in (erro(10020, SECRET), erro('10020', SECRET), erro(True, SECRET), {'errors': [SECRET]}, {'errors': SECRET},
                     {'errors': [{'message': SECRET}]}, http_erro(401, json.dumps(erro(10020, SECRET)).encode()),
                     http_erro(500, SECRET.encode()), http_erro(502, b'<html>' + SECRET.encode()), urllib.error.URLError(SECRET),
                     OSError(SECRET), ValueError(SECRET), RuntimeError(f'Authorization: {SECRET}'),
                     ConnectionResetError(SECRET), TimeoutError(SECRET)):
            with self.subTest(tipo=type(resp).__name__):
                self.setUp()
                cod, out, err = self.rodar(['buscas', '--cat', CAT], ApiFalsa(resp))
                self.assertEqual(cod, 1)
                self.assertNotIn('Traceback', out + err)
                self.nada_gravado()

    def test_ca7_resposta_malformada_sai_com_1_sem_gravar(self):
        for resp in (b'', b'nao e json', b'[1,2]', b'null', b'{}', b'{"data": null}', b'{"data": {"productOfferV2": null}}',
                     b'{"data": {"productOfferV2": {"nodes": null}}}', b'{"data": {"productOfferV2": {"nodes": {"a": 1}}}}',
                     b'[' * 100000, b'{"data":' * 5000, b'x' * (C.MAX_RESPOSTA + 10)):
            with self.subTest(resp=resp[:20]):
                self.setUp()
                cod, _, err = self.rodar(['buscas', '--cat', CAT], ApiFalsa(resp))
                self.assertEqual(cod, 1, err)
                self.assertIn('resposta da API', err)
                self.nada_gravado()

    def test_ca7_nos_de_tipos_estranhos_nao_derrubam_a_coleta(self):
        lixo = [None, 5, 'x', [], {}, [no()], {'offerLink': LINK}, no(itemId=[1]), no(offerLink={'a': 1})]
        cod, out, _ = self.rodar(['buscas', '--cat', CAT], ApiFalsa(resposta(lixo), resposta([]), resposta([])))
        self.assertEqual(cod, 0)
        self.assertEqual(self.itens(), [])

    def test_ca7_argumentos_invalidos_saem_com_2_sem_chamar_a_api(self):
        for argv in (['buscas'], ['buscas', '--cat', CAT, '--ordens', 'menor'], ['buscas', '--cat', CAT, '--ordens', 'caros,caros'],
                     ['buscas', '--cat', CAT, '--ordens', ''], ['buscas', '--cat', CAT, '--ordens', 'RELEVANCIA'],
                     ['buscas', '--cat', CAT, '--ordens', 'comissao'],
                     ['conferir', '--cat', CAT], [], ['coletar'], ['buscas', '--cat']):
            with self.subTest(argv=argv):
                api = ApiFalsa()
                cod, _, _ = self.rodar(argv, api)
                self.assertEqual(cod, 2)
                self.assertEqual(api.pedidos, [])
        self.nada_gravado()

    def test_ca7_aba_inexistente_ou_sem_termos_sai_com_2_sem_chamar_a_api(self):
        with open(self.buscas, 'w', encoding='utf-8') as f:
            json.dump({'Vazia': [], 'Outra': 'x'}, f)
        for aba in ('Nao existe', 'Vazia', 'Outra', CAT.lower()):
            api = ApiFalsa()
            cod, _, _ = self.rodar(['buscas', '--cat', aba], api)
            self.assertEqual((cod, api.pedidos), (2, []), aba)

    def test_ca7_sem_credencial_ou_com_app_id_estranho_sai_com_2_sem_api_e_sem_ecoar_o_secret(self):
        for env in ({}, {'ACHADINHOS_SHOPEE_APP_ID': APP_ID}, {'ACHADINHOS_SHOPEE_SECRET': SECRET},
                    {'ACHADINHOS_SHOPEE_APP_ID': 'a b', 'ACHADINHOS_SHOPEE_SECRET': SECRET},
                    {'ACHADINHOS_SHOPEE_APP_ID': '', 'ACHADINHOS_SHOPEE_SECRET': SECRET},
                    {'ACHADINHOS_SHOPEE_APP_ID': APP_ID, 'ACHADINHOS_SHOPEE_SECRET': ''}):
            with self.subTest(env=sorted(env)):
                api = ApiFalsa()
                with mock.patch.dict(os.environ, {}, clear=False):
                    for v in ('ACHADINHOS_SHOPEE_APP_ID', 'ACHADINHOS_SHOPEE_SECRET'):
                        os.environ.pop(v, None)
                    cod, _, _ = self.rodar(['buscas', '--cat', CAT], api, env=env)
                self.assertEqual((cod, api.pedidos), (2, []))
        self.nada_gravado()

    def test_ca7_o_secret_nao_vai_para_banco_progresso_nem_saida_de_uma_coleta_boa(self):
        un = lambda i: resposta([no(itemId=i, offerLink=f'https://s.shopee.com.br/Seg{i}')])
        cod, out, err = self.rodar(['buscas', '--cat', CAT, '--ordens', 'relevancia,caros'],
                                   ApiFalsa(*[un(i) for i in range(1, 7)]))
        self.assertEqual(cod, 0)
        for caminho in (self.db, self.db + '-wal', self.feitos_arq):
            if os.path.exists(caminho):
                with open(caminho, 'rb') as f:
                    self.assertNotIn(SECRET.encode(), f.read(), caminho)
        self.assertIn('TOTAL da Shopee no banco', out)

    def test_ca7_o_secret_nao_aparece_em_repr_str_format_json_nem_traceback_com_locals(self):
        seg = C.Segredo(SECRET)
        for texto in (repr(seg), str(seg), f'{seg}', f'{seg!r}', '%s %r' % (seg, seg), format(seg, '>40'), repr((seg,)),
                      repr({'s': seg}), repr(C.credenciais.__defaults__), repr(vars(C).get('Segredo'))):
            self.assertNotIn(SECRET, texto)
        with self.assertRaises(TypeError):
            json.dumps({'s': seg})
        try:
            C.buscar((APP_ID, seg), 'x', 'relevancia')   # dá erro de rede (proxy morto) sem urlopen falso
        except BaseException as e:   # noqa: BLE001
            import traceback
            self.assertNotIn(SECRET, ''.join(traceback.format_exception(e)))
            self.assertNotIn(SECRET, repr(e) + str(e))

    def test_ca7_conferir_nao_grava_nada_e_responde_pelo_codigo_de_saida(self):
        cod, out, _ = self.rodar(['conferir'], ApiFalsa(resposta([no()])))
        self.assertEqual(cod, 0)
        self.assertIn(ID, out)
        self.nada_gravado()
        for resp, conf in ((resposta([]), None), (resposta([no(sales=0)]), None), (resposta([no()]), ConferenciaFalsa(None)),
                           (resposta([no()]), ConferenciaFalsa(DESTINO_BOM.replace(ID, '9')))):
            cod, _, _ = self.rodar(['conferir'], ApiFalsa(resp), conf)
            self.assertEqual(cod, 1)
        self.nada_gravado()


class TestIntegracaoColetorDisparo(ColetaBase):
    """O que o coletor grava no banco é aceito pelo disparo (mesmo esquema, mesmos textos)."""

    def test_ca2_ca7_item_coletado_sai_na_mensagem_com_o_link_do_coletor_e_a_loja_shopee(self):
        nos = [no(itemId=1, productName='Perfume Floral', offerLink='https://s.shopee.com.br/Int1', sales=500, priceDiscountRate=25)]
        self.assertEqual(self.rodar(['buscas', '--cat', CAT], ApiFalsa(resposta(nos), resposta([]), resposta([])))[0], 0)
        con = T.abrir(self.db)
        try:
            D.migrar(con)
            with con:
                con.execute("INSERT OR REPLACE INTO config VALUES ('templates', ?)",
                            (json.dumps({'T': '{LOJA}: {TITULO_PRODUTO} {PRECO_PRODUTO} {DESCONTO_PRODUTO} ({NUMERO_VENDAS})\n{LINK}'}),))
            nid = D.criar_numero(con, {'nome': 'N', 'telefone': T.TELEFONE, 'grupo_nome': 'G', 'grupo_id': T.GRUPO_ID})['id']
            regra = {'nome': 'R', 'numero_id': nid, 'cats': [CAT], 'lojas': ['shopee'], 'template': 'T', 'horarios': ['09:00']}
            p = D.previa(con, regra, 5, T.SEGUNDA, T.AFILIADO)
        finally:
            con.close()
        self.assertEqual(len(p), 1)
        self.assertEqual(p[0]['loja'], 'shopee')
        self.assertTrue(p[0]['mensagem'].startswith('Shopee: Perfume Floral R$ 1.234,50 '))
        self.assertTrue(p[0]['mensagem'].endswith('\nhttps://s.shopee.com.br/Int1'))
        self.assertEqual(p[0]['imagem'], FOTO)


if __name__ == '__main__':
    unittest.main()
