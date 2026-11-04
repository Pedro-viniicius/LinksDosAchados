#!/usr/bin/env python3
"""Testes do público (gênero) no servidor.py (docs/produto/planos/genero-nas-categorias.md, etapa 3).

Uso:  python3 testes/test_genero_servidor.py -v

Sobe o servidor.py de verdade como subprocesso (base ServidorTeste de testes/test_servidor.py),
com banco temporário, porta livre, proxy morto e a API v1 desligada. Nenhum teste toca o
achadinhos.db real, o servidor em 8765, a rede ou o Mercado Livre.
Cobre o CA2 (item novo já sai classificado) e o CA4 (correção manual por PUT /api/items/<id>/genero).
Só biblioteca padrão.
"""
import json
import os
import sqlite3
import subprocess
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_servidor as TS  # noqa: E402  (ambiente, ServidorTeste, ml, RAIZ)

PERF = 'Perfumes e Perfumaria'
CASA = 'Casa e Decoração'
BF = 'Black Friday | Eletrônicos'
GENEROS = ('feminino', 'masculino', 'unissex', 'sem')
ORIGENS = ('titulo', 'busca', 'manual', '')
CHAVES_ITEM = {'id', 'loja', 'item_id', 'cat', 'busca', 'url', 'data', 'genero', 'genero_origem', 'genero_auto', 'preco_em'}
# valor de teste que nunca pode aparecer na resposta nem no log (as mensagens não ecoam o valor)
MARCA = 'ValorMarcaGenero7Q'
VELHO = '2000-01-01T00:00:00'


def amazon(asin, titulo, cat=PERF, busca=''):
    return {'loja': 'amazon', 'item_id': asin, 'cat': cat, 'busca': busca,
            'url': f'https://www.amazon.com.br/dp/{asin}?tag=desejodemen01-20', 'data': {'titulo': titulo}}


# (item_id, título, cat, busca, gênero esperado, origem esperada): casos reais do plano
CASOS = [
    ('GEN0000001', 'Lady Million Paco Rabanne Feminino', PERF, 'Paco Rabanne One Million', 'feminino', 'titulo'),
    ('GEN0000002', '212 Men NYC Carolina Herrera EDT', PERF, '', 'masculino', 'titulo'),
    ('GEN0000003', 'Kit Perfumes Feminino e Masculino', PERF, '', 'unissex', 'titulo'),
    ('GEN0000004', 'Olympea EDP', PERF, 'Perfume feminino importado', 'feminino', 'busca'),
    ('GEN0000005', 'Hidratante Corporal Pera', PERF, '', 'sem', ''),
    ('GEN0000006', 'Smartwatch Masculino Feminino', BF, 'smartwatch masculino', 'sem', ''),
    ('GEN0000007', 'Toalha Lady Banho', CASA, '', 'sem', ''),
]


class TestGeneroServidor(TS.ServidorTeste):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # o item ALVO e os demais que os testes de correção usam; cada teste mexe só nos seus
        corpo = json.dumps({'items': [amazon(c[0], c[1], c[2], c[3]) for c in CASOS]
                            + [amazon(f'ALVO{n:06d}', 'Perfume La Vie Est Belle Feminino EDP') for n in range(1, 13)]
                            + [amazon('CASA000001', 'Jogo de Panelas', CASA)]})
        import http.client
        con = http.client.HTTPConnection('127.0.0.1', cls.porta, timeout=10)
        con.request('POST', '/api/items', corpo, {'Host': f'localhost:{cls.porta}', 'Content-Type': 'application/json',
                                                   'Origin': f'http://localhost:{cls.porta}'})
        assert con.getresponse().status == 200
        con.close()

    # ------------------------------------------------------------ apoio
    def item(self, item_id):
        return next((i for i in self.itens() if i['item_id'] == item_id), None)

    def iid(self, item_id):
        return self.item(item_id)['id']

    def banco(self):
        con = sqlite3.connect(self.db, timeout=30)
        con.row_factory = sqlite3.Row
        return con

    def linha(self, iid):
        con = self.banco()
        try:
            return dict(con.execute('SELECT * FROM items WHERE id=?', (iid,)).fetchone())
        finally:
            con.close()

    def manual(self, iid):
        con = self.banco()
        try:
            r = con.execute('SELECT genero FROM generos_manuais WHERE item_pk=?', (iid,)).fetchone()
        finally:
            con.close()
        return r[0] if r else None

    def envelhecer(self, iid):
        """Põe um atualizado_em antigo no item, para ver se a correção mexe nele."""
        con = self.banco()
        try:
            con.execute('UPDATE items SET atualizado_em=? WHERE id=?', (VELHO, iid))
            con.commit()
        finally:
            con.close()

    def corrigir(self, iid, corpo, headers=None):
        """PUT da correção. Sem headers: os da página local, com Content-Type JSON mesmo em corpo cru."""
        if headers is None:
            headers = {**self.local(), 'Content-Type': 'application/json'}
        st, _, dados = self.pedir('PUT', f'/api/items/{iid}/genero', corpo, headers)
        return st, dados

    # ------------------------------------------------------------ CA2: item novo já sai classificado
    def test_ca2_post_novo_sai_classificado_no_get(self):
        for item_id, titulo, cat, busca, genero, origem in CASOS:
            with self.subTest(titulo=titulo):
                it = self.item(item_id)
                self.assertEqual((it['genero'], it['genero_origem']), (genero, origem))
                self.assertEqual(it['genero_auto'], genero)

    def test_ca2_todo_item_do_get_tem_as_chaves_de_genero(self):
        itens = self.itens()
        self.assertTrue(itens)
        for it in itens:
            with self.subTest(item=it['item_id']):
                self.assertEqual(set(it), CHAVES_ITEM)
                self.assertIn(it['genero'], GENEROS)
                self.assertIn(it['genero_origem'], ORIGENS)
                self.assertIn(it['genero_auto'], GENEROS)

    def test_ca2_post_da_coleta_do_ml_sai_classificado(self):
        st, _, dados = self.postar([{'loja': 'ml', 'item_id': 'MLBGEN1', 'cat': PERF, 'busca': 'Natura Kaiak',
                                     'url': 'https://produto.mercadolivre.com.br/MLB-1', 'data': {'titulo': 'Natura Kaiak Feminino'}}],
                                   TS.ml(TS.ML_LISTA))
        self.assertEqual(st, 200, dados)
        it = self.item('MLBGEN1')
        self.assertEqual((it['genero'], it['genero_origem']), ('feminino', 'titulo'))

    def test_ca2_upsert_da_coleta_no_terminal_sai_classificado(self):
        # coletar_amazon.gravar e coletar_shopee gravam pelo servidor.upsert, em outro processo
        codigo = ('import servidor as S\n'
                  'con = S.conectar()\n'
                  "S.upsert(con, {'loja': 'amazon', 'item_id': 'COLGEN0001', 'cat': 'Perfumes e Perfumaria',"
                  " 'busca': 'perfume masculino', 'url': 'https://www.amazon.com.br/dp/COLGEN0001?tag=desejodemen01-20',"
                  " 'data': {'titulo': 'Sauvage Dior EDT'}})\n"
                  'con.commit(); con.close()\n')
        saida = subprocess.run([sys.executable, '-c', codigo], cwd=TS.RAIZ, env=TS.ambiente(self.db),
                               capture_output=True, text=True, timeout=30)
        self.assertEqual(saida.returncode, 0, saida.stderr)
        it = self.item('COLGEN0001')
        self.assertEqual((it['genero'], it['genero_origem']), ('masculino', 'titulo'))

    def test_ca2_patch_de_data_reclassifica_e_a_resposta_traz_o_genero(self):
        self.postar([amazon('PATGEN0001', 'Perfume Azul 100ml')])
        it = self.item('PATGEN0001')
        self.assertEqual(it['genero'], 'sem')
        st, _, dados = self.pedir('PATCH', f'/api/items/{it["id"]}', {'data': {'titulo': 'Perfume Azul Masculino 100ml'}},
                                  self.local())
        self.assertEqual(st, 200, dados)
        resp = self.json_de(dados)
        self.assertEqual((resp['genero'], resp['genero_origem'], resp['genero_auto']), ('masculino', 'titulo', 'masculino'))
        self.assertEqual(self.item('PATGEN0001')['genero'], 'masculino')

    def test_ca2_cat_mudada_direto_no_banco_vale_na_proxima_leitura(self):
        # migrar_categorias.py e classificar_lista.py regravam cat e busca sem passar pelo servidor
        self.postar([amazon('MIGGEN0001', 'Perfume Ônix Feminino', CASA)])
        self.assertEqual(self.item('MIGGEN0001')['genero'], 'sem')
        con = self.banco()
        try:
            con.execute("UPDATE items SET cat=? WHERE item_id='MIGGEN0001'", (PERF,))
            con.commit()
        finally:
            con.close()
        self.assertEqual(self.item('MIGGEN0001')['genero'], 'feminino')

    # ------------------------------------------------------------ CA4: correção manual
    def test_ca4_correcao_persiste_e_volta_ao_automatico_com_null(self):
        iid = self.iid('ALVO000001')
        st, dados = self.corrigir(iid, {'genero': 'masculino'})
        self.assertEqual(st, 200, dados)
        resp = self.json_de(dados)
        self.assertEqual(set(resp), CHAVES_ITEM)
        self.assertEqual((resp['id'], resp['genero'], resp['genero_origem'], resp['genero_auto']),
                         (iid, 'masculino', 'manual', 'feminino'))
        self.assertEqual(self.manual(iid), 'masculino')   # gravado no banco, lido por outra conexão
        it = self.item('ALVO000001')
        self.assertEqual((it['genero'], it['genero_origem'], it['genero_auto']), ('masculino', 'manual', 'feminino'))

        self.envelhecer(iid)
        st, dados = self.corrigir(iid, {'genero': None})
        self.assertEqual(st, 200, dados)
        resp = self.json_de(dados)
        self.assertEqual((resp['genero'], resp['genero_origem'], resp['genero_auto']), ('feminino', 'titulo', 'feminino'))
        self.assertIsNone(self.manual(iid))
        self.assertNotEqual(self.linha(iid)['atualizado_em'], VELHO, 'apagar a correção é mudança real')
        self.assertEqual(self.item('ALVO000001')['genero_origem'], 'titulo')

    def test_ca4_aceita_os_quatro_valores(self):
        iid = self.iid('ALVO000002')
        for valor in GENEROS:
            with self.subTest(valor=valor):
                st, dados = self.corrigir(iid, {'genero': valor})
                self.assertEqual(st, 200, dados)
                self.assertEqual(self.json_de(dados)['genero'], valor)
                self.assertEqual(self.manual(iid), valor)
                self.assertEqual(self.item('ALVO000002')['genero'], valor)

    def test_ca4_null_em_item_sem_correcao_responde_200(self):
        iid = self.iid('ALVO000003')
        self.envelhecer(iid)
        antes = self.linha(iid)
        st, dados = self.corrigir(iid, {'genero': None})
        self.assertEqual(st, 200, dados)
        self.assertEqual(self.json_de(dados)['genero_origem'], 'titulo')
        self.assertIsNone(self.manual(iid))
        self.assertEqual(self.linha(iid), antes, 'sem correção para apagar, o item não muda (R3)')

    def test_ca4_atualizado_em_muda_e_nenhum_outro_campo_muda(self):
        iid = self.iid('ALVO000004')
        con = self.banco()
        try:
            con.execute("UPDATE items SET atualizado_em='2000-01-01T00:00:00' WHERE id=?", (iid,))
            con.commit()
        finally:
            con.close()
        antes = self.linha(iid)
        inicio = time.strftime('%Y-%m-%dT%H:%M:%S')
        st, dados = self.corrigir(iid, {'genero': 'unissex'})
        self.assertEqual(st, 200, dados)
        depois = self.linha(iid)
        self.assertGreaterEqual(depois['atualizado_em'], inicio)   # o cursor da API v1 vê a mudança
        self.assertEqual({k: v for k, v in depois.items() if k != 'atualizado_em'},
                         {k: v for k, v in antes.items() if k != 'atualizado_em'})
        self.assertEqual(self.json_de(dados)['url'], antes['url'])

    def test_ca4_aba_sem_genero_da_400_e_nao_grava(self):
        iid = self.iid('CASA000001')
        antes = self.linha(iid)
        st, dados = self.corrigir(iid, {'genero': 'feminino'})
        self.assertEqual(st, 400)
        self.assertEqual(self.json_de(dados), {'error': 'esta categoria não separa por público'})
        self.assertIsNone(self.manual(iid))
        self.assertEqual(self.linha(iid), antes)

    def test_ca4_item_inexistente_da_404(self):
        # até 19 dígitos o caminho é a rota (item não existe); com mais, nem casa com a rota (S1)
        for iid, erro in ((987654, 'item não encontrado'), (2**63 - 1, 'item não encontrado'),
                          (2**63, 'item não encontrado'), (10**19 - 1, 'item não encontrado'),
                          (10**19, 'rota não encontrada'), (10**30, 'rota não encontrada')):
            with self.subTest(iid=iid):
                st, dados = self.corrigir(iid, {'genero': 'feminino'})
                self.assertEqual(st, 404)
                self.assertEqual(self.json_de(dados), {'error': erro})

    def test_ca4_caminho_fora_do_formato_da_404(self):
        iid = self.iid('ALVO000005')
        for caminho in ('/api/items/abc/genero', '/api/items/-1/genero', f'/api/items/{iid}.0/genero',
                        f'/api/items/{iid}/genero/', f'/api/items/%3{str(iid)[0]}{str(iid)[1:]}/genero',
                        f'/api/items/{iid}/Genero', f'/api/items//{iid}/genero', '/api/items/genero'):
            with self.subTest(caminho=caminho):
                st, _, _ = self.pedir('PUT', caminho, {'genero': 'feminino'}, self.local())
                self.assertEqual(st, 404)
        self.assertIsNone(self.manual(iid))

    def test_ca4_valor_fora_da_lista_da_400_sem_ecoar_o_valor(self):
        iid = self.iid('ALVO000006')
        antes = self.linha(iid)
        for valor in (MARCA, 'Feminino', 'FEMININO', ' feminino', 'feminino ', '', 'f', 1, 0, True, False,
                      [], ['feminino'], {}, {'v': 'feminino'}, 1.5):
            with self.subTest(valor=valor):
                st, dados = self.corrigir(iid, {'genero': valor})
                self.assertEqual(st, 400)
                self.assertEqual(self.json_de(dados),
                                 {'error': 'genero deve ser feminino, masculino, unissex, sem ou null'})
        self.assertIsNone(self.manual(iid))
        self.assertEqual(self.linha(iid), antes)
        with open(os.path.join(self.dir, 'stderr.log'), encoding='utf-8', errors='replace') as f:
            self.assertNotIn(MARCA, f.read())

    def test_ca4_corpo_que_nao_e_so_genero_da_400(self):
        iid = self.iid('ALVO000007')
        antes = self.linha(iid)
        for corpo in ('[]', '"feminino"', 'null', '1', '{}', '["genero", "feminino"]',
                      json.dumps({'genero': 'feminino', 'url': 'https://www.amazon.com.br/dp/OUTRO?tag=desejodemen01-20'}),
                      json.dumps({'genero': 'feminino', 'cat': CASA}),
                      json.dumps({'Genero': 'feminino'}), json.dumps({MARCA: 'feminino'})):
            with self.subTest(corpo=corpo):
                st, dados = self.corrigir(iid, corpo)
                self.assertEqual(st, 400)
                erro = self.json_de(dados)['error']
                self.assertNotIn(MARCA, erro)
        self.assertIsNone(self.manual(iid))
        self.assertEqual(self.linha(iid), antes)

    def test_ca4_json_invalido_da_400(self):
        iid = self.iid('ALVO000008')
        for quebrado in ('{"genero": ', "{'genero': 'feminino'}", 'NaN]', '\xff\xfe'):
            with self.subTest(corpo=quebrado):
                st, dados = self.corrigir(iid, quebrado.encode('latin-1'))
                self.assertEqual(st, 400)
                self.assertEqual(self.json_de(dados), {'error': 'JSON inválido'})
        self.assertIsNone(self.manual(iid))

    def test_ca4_sem_content_type_json_da_415(self):
        iid = self.iid('ALVO000009')
        for tipo in ('text/plain', 'text/plain;charset=UTF-8', 'application/x-www-form-urlencoded',
                     'multipart/form-data; boundary=x', 'application/jsonx', None):
            with self.subTest(tipo=tipo):
                h = dict(self.local())
                if tipo:
                    h['Content-Type'] = tipo
                st, dados = self.corrigir(iid, json.dumps({'genero': 'feminino'}), h)
                self.assertEqual(st, 415)
                self.assertIn('error', self.json_de(dados))
        self.assertIsNone(self.manual(iid))

    def test_ca4_corpo_acima_de_5mb_da_413_sem_ler_o_corpo(self):
        iid = self.iid('ALVO000009')
        h = {**self.local(), 'Content-Type': 'application/json', 'Content-Length': str(5 * 1024 * 1024 + 1)}
        inicio = time.monotonic()
        st, _, dados = self.pedir('PUT', f'/api/items/{iid}/genero', None, h)   # nenhum byte de corpo é enviado
        self.assertEqual(st, 413)
        self.assertIn('error', self.json_de(dados))
        self.assertLess(time.monotonic() - inicio, 5, 'o servidor esperou o corpo antes de recusar')
        self.assertIsNone(self.manual(iid))

    def test_ca4_origem_do_ml_e_de_fora_dao_403_e_nao_gravam(self):
        iid = self.iid('ALVO000010')
        antes = self.linha(iid)
        for origem in (TS.ML_LISTA, TS.ML_WWW, 'https://evil.com', 'null'):
            with self.subTest(origem=origem):
                st, hd, dados = self.pedir('PUT', f'/api/items/{iid}/genero', {'genero': 'masculino'}, TS.ml(origem))
                self.assertEqual(st, 403)
                self.assertEqual(self.json_de(dados), {'error': 'origem não permitida'})
                self.assertIsNone(hd.get('Access-Control-Allow-Origin'))
                # nem o preflight passa: a rota está fora de ROTAS_ML
                for metodo in ('PUT', 'PATCH'):
                    st, hd, _ = self.pedir('OPTIONS', f'/api/items/{iid}/genero', None,
                                           {**TS.ml(origem), 'Access-Control-Request-Method': metodo})
                    self.assertEqual(st, 403)
                    self.assertIsNone(hd.get('Access-Control-Allow-Origin'))
        self.assertIsNone(self.manual(iid))
        self.assertEqual(self.linha(iid), antes)

    def test_ca4_sec_fetch_site_de_outro_site_da_403_e_nao_grava(self):
        iid = self.iid('ALVO000011')
        antes = self.linha(iid)
        for valor in ('cross-site', 'same-site', 'Cross-Site'):
            with self.subTest(sec_fetch_site=valor):
                st, _, dados = self.pedir('PUT', f'/api/items/{iid}/genero', {'genero': 'masculino'},
                                          {'Sec-Fetch-Site': valor})
                self.assertEqual(st, 403)
                self.assertEqual(self.json_de(dados), {'error': 'origem não permitida'})
        self.assertIsNone(self.manual(iid))
        self.assertEqual(self.linha(iid), antes)

    def test_ca4_origem_local_pelo_127_e_sem_navegador_gravam(self):
        iid = self.iid('ALVO000012')
        st, dados = self.corrigir(iid, {'genero': 'unissex'}, {**self.local('127.0.0.1'),
                                                                'Host': f'127.0.0.1:{self.porta}'})
        self.assertEqual(st, 200, dados)
        self.assertEqual(self.manual(iid), 'unissex')
        st, dados = self.corrigir(iid, {'genero': None}, {})   # curl local: sem Origin nem Sec-Fetch-Site
        self.assertEqual(st, 200, dados)
        self.assertIsNone(self.manual(iid))

    def test_ca4_item_que_sai_da_aba_fica_sem_e_a_correcao_volta_com_ele(self):
        self.postar([amazon('SAIGEN0001', 'Perfume Gotas Feminino')])
        iid = self.iid('SAIGEN0001')
        self.assertEqual(self.corrigir(iid, {'genero': 'masculino'})[0], 200)
        st, _, dados = self.pedir('PATCH', f'/api/items/{iid}', {'cat': CASA}, self.local())
        self.assertEqual(st, 200, dados)
        self.assertEqual((self.json_de(dados)['genero'], self.json_de(dados)['genero_origem']), ('sem', ''))
        self.assertEqual(self.manual(iid), 'masculino')   # guardada
        self.assertEqual(self.corrigir(iid, {'genero': 'feminino'})[0], 400)   # fora da aba não corrige
        self.assertEqual(self.manual(iid), 'masculino')
        st, _, dados = self.pedir('PATCH', f'/api/items/{iid}', {'cat': PERF}, self.local())
        self.assertEqual(st, 200, dados)
        resp = self.json_de(dados)   # a resposta do PATCH já leva a correção
        self.assertEqual((resp['genero'], resp['genero_origem'], resp['genero_auto']), ('masculino', 'manual', 'feminino'))
        it = self.item('SAIGEN0001')
        self.assertEqual((it['genero'], it['genero_origem'], it['genero_auto']), ('masculino', 'manual', 'feminino'))

    def test_ca4_delete_do_item_apaga_a_correcao(self):
        self.postar([amazon('DELGEN0001', 'Perfume Brisa Feminino')])
        iid = self.iid('DELGEN0001')
        self.assertEqual(self.corrigir(iid, {'genero': 'sem'})[0], 200)
        self.assertEqual(self.manual(iid), 'sem')
        st, _, dados = self.pedir('DELETE', f'/api/items/{iid}', None, self.local())
        self.assertEqual(st, 200, dados)
        self.assertIsNone(self.item('DELGEN0001'))
        self.assertIsNone(self.manual(iid))

    def test_ca4_null_fora_da_aba_apaga_a_correcao_guardada(self):
        # decisão do lead na rodada 2: null vale em qualquer aba; valor fora da aba com gênero segue 400
        self.postar([amazon('NULGEN0001', 'Perfume Vento Feminino')])
        iid = self.iid('NULGEN0001')
        self.assertEqual(self.corrigir(iid, {'genero': 'unissex'})[0], 200)
        self.assertEqual(self.pedir('PATCH', f'/api/items/{iid}', {'cat': CASA}, self.local())[0], 200)
        self.assertEqual(self.manual(iid), 'unissex')
        self.envelhecer(iid)
        st, dados = self.corrigir(iid, {'genero': None})
        self.assertEqual(st, 200, dados)
        resp = self.json_de(dados)
        self.assertEqual((resp['cat'], resp['genero'], resp['genero_origem']), (CASA, 'sem', ''))
        self.assertIsNone(self.manual(iid))
        self.assertNotEqual(self.linha(iid)['atualizado_em'], VELHO, 'apagar a correção é mudança real')
        for valor in ('feminino', 'sem'):
            with self.subTest(valor=valor):
                st, dados = self.corrigir(iid, {'genero': valor})
                self.assertEqual(st, 400)
                self.assertEqual(self.json_de(dados), {'error': 'esta categoria não separa por público'})
        self.assertIsNone(self.manual(iid))
        # de volta à Perfumaria, sai pela regra automática (a correção apagada não volta)
        self.pedir('PATCH', f'/api/items/{iid}', {'cat': PERF}, self.local())
        self.assertEqual(self.item('NULGEN0001')['genero_origem'], 'titulo')

    def test_ca4_null_em_item_de_aba_sem_genero_e_sem_correcao_responde_200(self):
        iid = self.iid('CASA000001')
        self.envelhecer(iid)
        antes = self.linha(iid)
        st, dados = self.corrigir(iid, {'genero': None})
        self.assertEqual(st, 200, dados)
        self.assertEqual(self.json_de(dados)['genero'], 'sem')
        self.assertIsNone(self.manual(iid))
        # nada a apagar: atualizado_em não muda, senão o item reaparece no cursor da API v1 (R3)
        self.assertEqual(self.linha(iid), antes)

    # ------------------------------------------------------------ S1: id grande no caminho
    def test_s1_id_gigante_nas_tres_rotas_da_404_e_o_servidor_segue_no_ar(self):
        log = os.path.join(self.dir, 'stderr.log')
        inicio = os.path.getsize(log)
        iid = self.iid('ALVO000012')
        antes = self.linha(iid)
        for nome, numero in (('5000 dígitos', '9' * 5000), ('2^63', str(2**63)), ('20 dígitos', '1' + '0' * 19)):
            for metodo, caminho, corpo in (('PUT', f'/api/items/{numero}/genero', {'genero': 'feminino'}),
                                           ('PATCH', f'/api/items/{numero}', {'cat': PERF}),
                                           ('DELETE', f'/api/items/{numero}', None)):
                with self.subTest(id=nome, metodo=metodo):
                    h = {**self.local(), 'Content-Type': 'application/json'}
                    st, _, dados = self.pedir(metodo, caminho, corpo, h)
                    self.assertEqual(st, 404)
                    self.assertIn('error', self.json_de(dados))
                    self.assertIsNone(self.proc.poll(), 'o servidor caiu')
        self.assertEqual(self.pedir('GET', '/api/items')[0], 200)
        self.assertEqual(self.linha(iid), antes)
        with open(log, encoding='utf-8', errors='replace') as f:
            f.seek(inicio)
            novo = f.read()
        self.assertNotIn('Traceback', novo)
        self.assertNotIn('Error', novo)
        for linha in novo.splitlines():   # só o registro normal de acesso, com o código da resposta
            with self.subTest(linha=linha[:120]):
                self.assertRegex(linha, r'" (200|404) -$')

    def test_s1_maior_id_que_cabe_no_sqlite_segue_o_contrato_de_hoje(self):
        # 2^63-1 cabe no INTEGER: item inexistente, com as respostas de sempre (PATCH 200 null, DELETE ok)
        numero = str(2**63 - 1)
        h = {**self.local(), 'Content-Type': 'application/json'}
        self.assertEqual(self.pedir('PUT', f'/api/items/{numero}/genero', {'genero': 'feminino'}, h)[0], 404)
        st, _, dados = self.pedir('PATCH', f'/api/items/{numero}', {'cat': PERF}, h)
        self.assertEqual((st, self.json_de(dados)), (200, None))
        st, _, dados = self.pedir('DELETE', f'/api/items/{numero}', None, h)
        self.assertEqual((st, self.json_de(dados)), (200, {'ok': True}))

    def test_primeira_linha_do_stdout_nao_mudou(self):
        self.assertEqual(self.primeira_linha,
                         f'Site em http://localhost:{self.porta}/  (banco: {self.db})\n')


if __name__ == '__main__':
    unittest.main()
