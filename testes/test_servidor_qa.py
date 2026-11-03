#!/usr/bin/env python3
"""Testes extras do servidor.py (QA), em cima de testes/test_servidor.py.

Uso:  python3 testes/test_servidor_qa.py -v

Complementam os 45 testes do dev com bordas que os mutantes mostraram sem cobertura:
Content-Length negativo, JSON muito aninhado, alvo absoluto e query enganosa no estático,
caminhos enganosos de quem tem Origin do ML, escritas concorrentes e campos com tipo errado.
Mesma base: servidor.py de verdade como subprocesso, banco temporário e porta livre. Nada de
rede real, do achadinhos.db real nem do servidor em 8765. Só biblioteca padrão.
"""
import http.client
import json
import socket
import threading
import unittest

import test_servidor as T

ML_LISTA = T.ML_LISTA
ML_WWW = T.ML_WWW


class TestBordasHttp(T.ServidorTeste):

    def bruto(self, linha_de_requisicao, cabecalhos=None):
        """Manda a linha de requisição exatamente como veio (alvo absoluto, por exemplo)."""
        hd = {'Host': f'localhost:{self.porta}', 'Connection': 'close'}
        hd.update(cabecalhos or {})
        msg = linha_de_requisicao + '\r\n' + ''.join(f'{k}: {v}\r\n' for k, v in hd.items()) + '\r\n'
        with socket.create_connection(('127.0.0.1', self.porta), timeout=10) as s:
            s.sendall(msg.encode())
            dados = b''
            while True:
                pedaco = s.recv(65536)
                if not pedaco:
                    break
                dados += pedaco
        cabeca, _, corpo = dados.partition(b'\r\n\r\n')
        status = int(cabeca.split(b' ', 2)[1])
        return status, cabeca.decode('latin-1'), corpo

    # ---- CA5: borda do corpo
    def test_ca5_content_length_negativo_da_400(self):
        # Content-Length: -1 faria rfile.read(-1) esperar o fim da conexão
        for valor in ('-1', '-100'):
            with self.subTest(valor=valor):
                st, _, dados = self.pedir('POST', '/api/items', None,
                                          {**self.local(), 'Content-Type': 'application/json', 'Content-Length': valor})
                self.assertEqual(st, 400)
                self.assertIn('error', self.json_de(dados))

    def test_ca5_json_muito_aninhado_da_400_e_o_servidor_continua(self):
        h = {**self.local(), 'Content-Type': 'application/json'}
        fundo = ('[' * 200000).encode()
        for metodo, caminho in (('POST', '/api/items'), ('PATCH', '/api/items/1'), ('PUT', '/api/config/aninhado')):
            with self.subTest(metodo=metodo):
                st, _, _ = self.pedir(metodo, caminho, fundo, h)
                self.assertEqual(st, 400)
        self.assertEqual(self.pedir('GET', '/api/items')[0], 200)

    def test_ca5_corpo_vazio_com_content_type_json_em_post_da_lista_vazia(self):
        # hoje: corpo vazio vira {} e o POST responde com 0 itens; documenta que nada é gravado
        st, _, dados = self.pedir('POST', '/api/items', b'', {**self.local(), 'Content-Type': 'application/json'})
        self.assertEqual(st, 200)
        self.assertEqual(self.json_de(dados)['inserido'], 0)

    # ---- CA2: o caminho cru decide, nada de alvo absoluto nem query enganosa
    def test_ca2_alvo_absoluto_nao_serve_arquivo_nem_dado(self):
        p = self.porta
        for alvo in (f'http://localhost:{p}/servidor.py', f'http://localhost:{p}/achadinhos.db',
                     f'http://localhost:{p}/api/items', 'http://evil.com/servidor.py', 'http://evil.com/api/items',
                     'http://evil.com/index.html'):
            with self.subTest(alvo=alvo):
                st, _, corpo = self.bruto(f'GET {alvo} HTTP/1.1')
                self.assertEqual(st, 404)
                self.assertNotIn(b'class Handler', corpo)
                self.assertNotIn(b'SQLite format', corpo)

    def test_ca2_query_ou_ponto_e_virgula_nao_trocam_o_arquivo(self):
        for caminho in ('/servidor.py?/index.html', '/servidor.py?x=.test.html', '/index.html;/../servidor.py',
                        '/index.html/../servidor.py', '/testes/x.test.html/../../servidor.py'):
            with self.subTest(caminho=caminho):
                for metodo in ('GET', 'HEAD'):
                    st, _, corpo = self.pedir(metodo, caminho)
                    self.assertEqual(st, 404)
                    self.assertNotIn(b'class Handler', corpo)
        st, _, corpo = self.pedir('GET', '/testes/copiar-imagem.test.html?/../../servidor.py')
        self.assertEqual(st, 200)
        self.assertNotIn(b'class Handler', corpo)
        self.assertIn(b'<html', corpo.lower())

    def test_ca2_options_fora_da_api_nao_leva_cors_nem_pna(self):
        for origem in (ML_LISTA, 'https://evil.com'):
            for caminho in ('/', '/servidor.py'):
                with self.subTest(origem=origem, caminho=caminho):
                    st, h, _ = self.pedir('OPTIONS', caminho, headers={
                        'Origin': origem, 'Access-Control-Request-Method': 'GET',
                        'Access-Control-Request-Private-Network': 'true'})
                    self.assertEqual(st, 204)
                    for nome in ('Access-Control-Allow-Origin', 'Access-Control-Allow-Methods',
                                 'Access-Control-Allow-Private-Network'):
                        self.assertIsNone(h.get(nome), nome)

    # ---- CA4: quem tem Origin do ML não chega a outras rotas por caminho enganoso
    def test_ca4_ml_nao_alcanca_outra_rota_por_caminho_enganoso(self):
        enganosos = ['/api/items/../config/templates', '/api/items/../fetch?url=https://www.amazon.com.br/dp/X',
                     '/api/items/1/../../config/currentTpl', '/api/items/%31', '/api//items', '/api/items%2f..%2fconfig',
                     '/api/ml-sem-afiliado/../fetch', '/api/items/1/', '/api/items/-1', '/api/items/1.0',
                     '/api/config/templates', '/api/%66etch']
        for origem in (ML_LISTA, ML_WWW):
            for caminho in enganosos:
                for metodo in ('GET', 'PATCH', 'POST'):
                    with self.subTest(origem=origem, caminho=caminho, metodo=metodo):
                        corpo = {'cat': 'x'} if metodo != 'GET' else None
                        st, h, _ = self.pedir(metodo, caminho, corpo, {'Origin': origem})
                        self.assertEqual(st, 403)
                        self.assertIsNone(h.get('Access-Control-Allow-Origin'))
        st, _, dados = self.pedir('GET', '/api/config/templates')
        self.assertIsNone(self.json_de(dados))

    def test_ca4_origem_repetida_vale_a_primeira_e_a_ruim_primeiro_e_recusada(self):
        # navegador não repete Origin, mas um cliente qualquer pode: a primeira decide e não há CORS
        con = http.client.HTTPConnection('127.0.0.1', self.porta, timeout=10)
        try:
            con.putrequest('GET', '/api/items', skip_host=True)
            con.putheader('Host', f'localhost:{self.porta}')
            con.putheader('Origin', 'https://evil.com')
            con.putheader('Origin', ML_LISTA)
            con.endheaders()
            r = con.getresponse()
            r.read()
        finally:
            con.close()
        self.assertEqual(r.status, 403)
        self.assertIsNone(r.getheader('Access-Control-Allow-Origin'))

    def test_ca3_resposta_403_e_404_nao_leva_cors_nem_para_o_ml(self):
        for caminho, esperado in (('/api/config/x', 403), ('/servidor.py', 404)):
            with self.subTest(caminho=caminho):
                st, h, _ = self.pedir('GET', caminho, headers={'Origin': ML_WWW})
                self.assertEqual(st, esperado)
                self.assertIsNone(h.get('Access-Control-Allow-Origin'))


class TestConcorrencia(T.ServidorTeste):
    """Escritas simultâneas. Conecta todo mundo antes e dispara junto (Barrier), com poucas
    threads, para o resultado não depender da fila de conexões do servidor (backlog de 5)."""

    N = 6

    def disparar(self, n, requisicao):
        """requisicao(i) -> (metodo, caminho, corpo, headers). Devolve o status de cada uma."""
        barreira = threading.Barrier(n)
        resultados = [None] * n

        def roda(i):
            con = http.client.HTTPConnection('127.0.0.1', self.porta, timeout=30)
            try:
                con.connect()
                metodo, caminho, corpo, headers = requisicao(i)
                h = {'Host': f'localhost:{self.porta}', 'Content-Type': 'application/json', **headers}
                barreira.wait(30)
                con.request(metodo, caminho, body=json.dumps(corpo), headers=h)
                r = con.getresponse()
                r.read()
                resultados[i] = r.status
            except Exception as e:   # sem resposta também é resultado
                resultados[i] = type(e).__name__
            finally:
                con.close()
        ts = [threading.Thread(target=roda, args=(i,)) for i in range(n)]
        [t.start() for t in ts]
        [t.join(60) for t in ts]
        return resultados

    def test_q2_posts_simultaneos_do_mesmo_item_dao_uma_linha_e_nenhum_erro(self):
        item = {'loja': 'ml', 'item_id': 'MLBCORRIDA', 'cat': 'Teste', 'url': 'https://meli.la/corrida'}
        for rodada in range(5):
            item = dict(item, item_id=f'MLBCORRIDA{rodada}')
            res = self.disparar(self.N, lambda i: ('POST', '/api/items', {'items': [item]}, self.local()))
            self.assertEqual(res, [200] * self.N, f'rodada {rodada}')
            self.assertEqual([i['item_id'] for i in self.itens()].count(item['item_id']), 1)

    def test_posts_simultaneos_de_itens_diferentes_gravam_todos(self):
        res = self.disparar(self.N, lambda i: ('POST', '/api/items', {'items': [
            {'loja': 'ml', 'item_id': f'MLBPAR{i:02d}', 'cat': 'Teste', 'url': f'https://meli.la/par{i}'}]}, self.local()))
        self.assertEqual(res, [200] * self.N)
        ids = {i['item_id'] for i in self.itens()}
        self.assertTrue({f'MLBPAR{i:02d}' for i in range(self.N)} <= ids)

    def test_patches_simultaneos_do_mesmo_item_terminam_ok_com_um_valor_valido(self):
        self.assertEqual(self.postar([{'loja': 'ml', 'item_id': 'MLBPATCHPAR', 'url': 'https://www.mercadolivre.com.br/p/x'}])[0], 200)
        alvo = next(i['id'] for i in self.itens() if i['item_id'] == 'MLBPATCHPAR')
        links = [f'https://meli.la/p{i}' for i in range(self.N)]
        res = self.disparar(self.N, lambda i: ('PATCH', f'/api/items/{alvo}', {'url': links[i]}, {'Origin': ML_WWW}))
        self.assertEqual(res, [200] * self.N)
        final = next(i['url'] for i in self.itens() if i['id'] == alvo)
        self.assertIn(final, links)

    def test_post_recusado_nao_atrapalha_os_aceitos_ao_mesmo_tempo(self):
        def requisicao(i):
            loja = 'x' if i % 2 else 'ml'
            return 'POST', '/api/items', {'items': [{'loja': loja, 'item_id': f'MLBMIX{i}', 'url': f'https://meli.la/m{i}'}]}, self.local()
        res = self.disparar(self.N, requisicao)
        self.assertEqual(res, [200 if i % 2 == 0 else 400 for i in range(self.N)])
        ids = {i['item_id'] for i in self.itens()}
        for i in range(self.N):
            self.assertEqual(f'MLBMIX{i}' in ids, i % 2 == 0, i)


class TestTiposErrados(T.ServidorTeste):
    """Campo com tipo errado (lista, objeto) deve virar 400 com {"error": ...}, sem gravar nada.

    Hoje a exceção sobe sem tratamento e o servidor fecha a conexão sem responder (Q1).
    """

    BASE = {'loja': 'ml', 'item_id': 'MLBTIPO0', 'url': 'https://meli.la/tipo0'}

    CASOS = {
        'url lista': {'item_id': 'MLBT1', 'url': ['https://meli.la/x']},
        'cat lista': {'item_id': 'MLBT2', 'url': 'https://meli.la/t2', 'cat': ['x']},
        'item_id lista': {'item_id': ['x'], 'url': 'https://meli.la/t3'},
        'data texto': {'item_id': 'MLBT4', 'url': 'https://meli.la/t4', 'data': 'x'},
        'data lista': {'item_id': 'MLBT5', 'url': 'https://meli.la/t5', 'data': [1]},
        'data com campo objeto': {'item_id': 'MLBT6', 'url': 'https://meli.la/t6', 'data': {'titulo': {'a': 1}}},
    }

    def test_q1_post_com_tipo_errado_da_400_e_nao_grava_o_lote(self):
        for nome, ruim in self.CASOS.items():
            with self.subTest(caso=nome):
                try:
                    st, _, dados = self.postar([dict(self.BASE), ruim])
                except (http.client.HTTPException, OSError) as e:
                    self.fail(f'o servidor fechou a conexão sem responder ({e}); esperado 400')
                self.assertEqual(st, 400)
                self.assertIn('error', self.json_de(dados))
        ids = [i['item_id'] for i in self.itens()]
        self.assertNotIn('MLBTIPO0', ids, 'lote com item inválido não pode gravar o item bom')

    def test_q1_patch_com_campo_de_data_objeto_da_400(self):
        self.assertEqual(self.postar([{'loja': 'ml', 'item_id': 'MLBTP', 'url': 'https://www.mercadolivre.com.br/p/tp'}])[0], 200)
        alvo = next(i['id'] for i in self.itens() if i['item_id'] == 'MLBTP')
        try:
            st, _, _ = self.pedir('PATCH', f'/api/items/{alvo}', {'data': {'titulo': {'a': 1}}}, self.local())
        except (http.client.HTTPException, OSError) as e:
            self.fail(f'o servidor fechou a conexão sem responder ({e}); esperado 400')
        self.assertEqual(st, 400)

    def test_q1_numero_em_data_e_aceito_e_gravado_como_texto(self):
        # desvio deliberado do dev: a coleta do ML pode mandar número em data
        st, _, dados = self.postar([{'loja': 'ml', 'item_id': 'MLBNUM1', 'url': 'https://meli.la/n1',
                                     'data': {'titulo': 5, 'preco': 9.9}}])
        self.assertEqual(st, 200, dados)
        it = next(i for i in self.itens() if i['item_id'] == 'MLBNUM1')
        self.assertEqual((it['data']['titulo'], it['data']['preco']), ('5', '9.9'))

    def test_q1_booleano_em_data_da_400(self):
        st, _, _ = self.postar([{'loja': 'ml', 'item_id': 'MLBBOOL', 'url': 'https://meli.la/b', 'data': {'titulo': True}}])
        self.assertEqual(st, 400)
        self.assertNotIn('MLBBOOL', [i['item_id'] for i in self.itens()])

    def test_q1_data_que_nao_e_objeto_mesmo_vazio_da_400(self):
        for valor in ('', 0, [], 'x'):
            with self.subTest(data=valor):
                st, _, _ = self.postar([{'loja': 'ml', 'item_id': 'MLBDATA', 'url': 'https://meli.la/d', 'data': valor}])
                self.assertEqual(st, 400)

    def test_q1_inteiro_gigante_em_data_da_400(self):
        # int acima de 2**63 não cabe no sqlite (OverflowError): a aceitação de números deixou essa brecha
        try:
            st, _, _ = self.postar([{'loja': 'ml', 'item_id': 'MLBGIGA', 'url': 'https://meli.la/g',
                                     'data': {'titulo': 2 ** 70}}])
        except (http.client.HTTPException, OSError) as e:
            self.fail(f'o servidor fechou a conexão sem responder ({e}); esperado 400')
        self.assertEqual(st, 400)
        self.assertNotIn('MLBGIGA', [i['item_id'] for i in self.itens()])

    def test_servidor_segue_de_pe_depois_de_tipo_errado(self):
        try:
            self.postar([dict(self.BASE, url=['x'])])
        except (http.client.HTTPException, OSError):
            pass
        self.assertEqual(self.pedir('GET', '/api/items')[0], 200)


if __name__ == '__main__':
    unittest.main()
