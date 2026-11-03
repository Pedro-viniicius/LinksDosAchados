#!/usr/bin/env python3
"""Testes do disparo ligado ao servidor.py (docs/produto/planos/disparo-automatico.md, etapa 4).

Uso:  python3 testes/test_disparo_servidor.py -v

Sobe o servidor.py de verdade como subprocesso (base ServidorTeste de testes/test_servidor.py),
com banco temporário, porta livre, proxy morto e o transporte falso gravando num JSONL temporário.
Nenhum teste toca o achadinhos.db real, o servidor em 8765, a rede ou o WhatsApp.
Só biblioteca padrão.
"""
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_servidor as TS  # noqa: E402  (ambiente, porta_livre, ServidorTeste, RAIZ, DB_REAL)

TELEFONE = '5500000000001'   # fictício: nada parecido com número real no git
GRUPO_ID = '120363012345678901@g.us'
with open(os.path.join(TS.RAIZ, 'index.html'), encoding='utf-8') as _f:
    HTML = _f.read()
DEFAULT_TEMPLATES = json.loads(re.search(r'^const DEFAULT_TEMPLATES = (\{.*\});$', HTML, re.M).group(1))
ML = ('https://lista.mercadolivre.com.br', 'https://www.mercadolivre.com.br')
VARS_DISPARO = ('ACHADINHOS_DISPARO', 'ACHADINHOS_TICK_SEG', 'ACHADINHOS_TRANSPORTE', 'ACHADINHOS_TRANSPORTE_ARQUIVO')


def esperar(cond, segundos=15, desc='condição'):
    fim = time.monotonic() + segundos
    while True:
        v = cond()
        if v:
            return v
        if time.monotonic() > fim:
            raise AssertionError('tempo esgotado esperando: ' + desc)
        time.sleep(0.1)


class ServidorDisparo(TS.ServidorTeste):
    """Servidor com o transporte falso. Guarda toda a saída (stdout e stderr) para conferir o CA1."""
    DISPARO = '1'

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix='achadinhos-disparo-srv-')
        cls.addClassCleanup(shutil.rmtree, cls.dir, ignore_errors=True)
        cls.db = os.path.join(cls.dir, 'teste.db')
        cls.jsonl = os.path.join(cls.dir, 'envios.jsonl')
        cls.porta = TS.porta_livre()
        cls.log_err = open(os.path.join(cls.dir, 'stderr.log'), 'ab')
        cls.addClassCleanup(cls.log_err.close)
        cls.stdout = []
        cls.proc = None
        cls.addClassCleanup(cls.parar_servidor)
        cls.subir()

    @classmethod
    def env(cls):
        env = TS.ambiente(cls.db, cls.porta)
        for k in VARS_DISPARO:   # nada do ambiente de quem roda o teste vaza para o subprocesso
            env.pop(k, None)
        env.update(ACHADINHOS_DISPARO=cls.DISPARO, ACHADINHOS_TICK_SEG='1', ACHADINHOS_TRANSPORTE='falso',
                   ACHADINHOS_TRANSPORTE_ARQUIVO=cls.jsonl)
        return env

    @classmethod
    def subir(cls):
        cls.proc = subprocess.Popen([sys.executable, '-u', 'servidor.py'], cwd=TS.RAIZ, env=cls.env(),
                                    stdout=subprocess.PIPE, stderr=cls.log_err)
        cls.primeira_linha = cls.proc.stdout.readline().decode()
        cls.stdout.append(cls.primeira_linha)
        for _ in range(100):
            try:
                socket.create_connection(('127.0.0.1', cls.porta), timeout=0.2).close()
                return
            except OSError:
                if cls.proc.poll() is not None:
                    break
                time.sleep(0.05)
        raise RuntimeError('o servidor de teste não subiu: ' + cls.primeira_linha + cls.saida())

    @classmethod
    def parar_servidor(cls):
        if cls.proc is None:
            return
        if cls.proc.poll() is None:
            cls.proc.terminate()
            try:
                cls.proc.wait(5)
            except subprocess.TimeoutExpired:
                cls.proc.kill()
                cls.proc.wait()
        cls.stdout.append(cls.proc.stdout.read().decode())
        cls.proc.stdout.close()
        cls.proc = None

    @classmethod
    def saida(cls):
        """stdout + stderr de todos os processos desta classe até agora."""
        cls.log_err.flush()
        with open(os.path.join(cls.dir, 'stderr.log'), encoding='utf-8', errors='replace') as f:
            return ''.join(cls.stdout) + f.read()

    # ------------------------------------------------------------ apoio
    def api(self, metodo, resto, corpo=None, headers=None):
        st, _, dados = self.pedir(metodo, '/api/disparo/' + resto, corpo, headers or self.local())
        return st, (json.loads(dados) if dados else None)

    def ok(self, metodo, resto, corpo=None):
        st, j = self.api(metodo, resto, corpo)
        self.assertEqual(st, 200, j)
        return j

    def preparar(self):
        """Templates padrão no config (como a tela fará) e três itens de afiliado."""
        st, _, d = self.pedir('PUT', '/api/config/templates', DEFAULT_TEMPLATES, self.local())
        self.assertEqual(st, 200, d)
        itens = [{'loja': 'amazon', 'item_id': f'B0SRV{i:05d}', 'cat': 'Eletrônicos',
                  'url': f'https://www.amazon.com.br/dp/B0SRV{i:05d}?tag=desejodemen01-20',
                  'data': {'titulo': f'Produto {i}', 'preco': 'R$ 10,00', 'desconto': f'-{10 + i}%',
                           'imagem': f'https://m.media-amazon.com/images/I/{i}.jpg'}} for i in range(3)]
        st, _, d = self.postar(itens)
        self.assertEqual(st, 200, d)

    def numero(self):
        return self.ok('POST', 'numeros', {'nome': 'Loja 1', 'telefone': TELEFONE, 'grupo_nome': 'Achadinhos',
                                           'grupo_id': GRUPO_ID})

    def regra(self, numero_id, **kw):
        return self.ok('POST', 'regras', {'nome': 'R', 'numero_id': numero_id, 'cats': ['Eletrônicos'],
                                          'template': 'Template 2', 'horarios': ['03:33'], **kw})

    def linhas_jsonl(self):
        if not os.path.exists(self.jsonl):
            return []
        with open(self.jsonl, encoding='utf-8') as f:
            return [json.loads(l) for l in f.read().splitlines()]

    def assertSemDadoPessoal(self, texto):
        for v in (TELEFONE, GRUPO_ID, TELEFONE[-8:], GRUPO_ID.split('@')[0]):
            self.assertNotIn(v, texto)


# ================================================================ rotas (agendador desligado)
class TestRotas(ServidorDisparo):
    """ACHADINHOS_DISPARO=0: as rotas funcionam e nenhuma thread dispara sozinha."""
    DISPARO = '0'

    def setUp(self):
        with sqlite3.connect(self.db) as con:   # cada teste começa sem dados do disparo
            con.executescript('DELETE FROM envios; DELETE FROM regras; DELETE FROM numeros; DELETE FROM items;')
        con.close()
        if os.path.exists(self.jsonl):
            os.remove(self.jsonl)
        self.preparar()

    def test_ca9_numeros_crud(self):
        n = self.numero()
        self.assertEqual((n['telefone'], n['grupo_id']), (TELEFONE, GRUPO_ID))   # inteiro no corpo; a tela mascara
        self.assertEqual(self.ok('GET', 'numeros'), [n])
        self.assertEqual(self.ok('PUT', f'numeros/{n["id"]}', {'nome': 'Loja 2'})['nome'], 'Loja 2')
        st, j = self.api('PUT', f'numeros/{n["id"]}', {'telefone': TELEFONE + '00000'})
        self.assertEqual(st, 400)
        self.assertSemDadoPessoal(json.dumps(j))
        r = self.regra(n['id'])
        st, j = self.api('DELETE', f'numeros/{n["id"]}')
        self.assertEqual(st, 409, j)
        self.ok('DELETE', f'regras/{r["id"]}')
        self.assertEqual(self.ok('DELETE', f'numeros/{n["id"]}'), {'ok': True})
        self.assertEqual(self.api('DELETE', f'numeros/{n["id"]}')[0], 404)

    def test_ca2_regras_crud_com_proximo(self):
        n = self.numero()
        r = self.regra(n['id'])
        self.assertRegex(r['proximo'], r'^\d{4}-\d{2}-\d{2}T03:33$')
        self.assertEqual(r['cats'], ['Eletrônicos'])
        lista = self.ok('GET', 'regras')
        self.assertEqual([x['id'] for x in lista], [r['id']])
        self.assertIn('proximo', lista[0])
        self.assertIsNone(self.ok('PUT', f'regras/{r["id"]}', {'ativa': 0})['proximo'])
        st, j = self.api('POST', 'regras', {'nome': 'X', 'numero_id': n['id'], 'cats': [], 'template': 'Template 1',
                                            'horarios': ['09:00']})
        self.assertEqual(st, 400, j)
        self.assertEqual(self.ok('DELETE', f'regras/{r["id"]}'), {'ok': True})

    def test_ca10_previa_nao_grava(self):
        n = self.numero()
        p = self.ok('POST', 'previa', {'nome': 'P', 'numero_id': n['id'], 'cats': ['Eletrônicos'],
                                       'template': 'Template 2', 'horarios': ['09:00'], 'ordem': 'desconto', 'n': 2})
        self.assertEqual([x['titulo'] for x in p], ['Produto 2', 'Produto 1'])
        self.assertIn('?tag=desejodemen01-20', p[0]['mensagem'])
        self.assertEqual(self.ok('GET', 'regras'), [])
        self.assertEqual(self.ok('GET', 'envios'), [])
        self.assertEqual(self.api('POST', 'previa', {'n': 21})[0], 400)

    def test_ca11_agora_com_transporte_falso(self):
        n = self.numero()
        r = self.regra(n['id'], por_disparo=2)
        res = self.ok('POST', f'regras/{r["id"]}/agora', {})
        self.assertEqual(res['criados'], 2)
        self.assertEqual([e['status'] for e in res['envios']], ['enviado', 'enviado'])
        linhas = self.linhas_jsonl()
        self.assertEqual(len(linhas), 2)
        self.assertEqual(linhas[0]['grupo_nome'], 'Achadinhos')
        self.assertTrue(linhas[0]['imagem_url'].startswith('https://m.media-amazon.com/'))
        with open(self.jsonl, encoding='utf-8') as f:
            self.assertSemDadoPessoal(f.read())
        time.sleep(1.1)   # o slot do "agora" tem resolução de segundo (clique duplo não cria nada)
        self.assertEqual(self.ok('POST', f'regras/{r["id"]}/agora', {})['criados'], 1, 'só sobrou um item')
        self.assertEqual(self.api('POST', 'regras/999/agora', {})[0], 404)

    def test_ca9_fila_e_marcacao(self):
        n = self.numero()
        r = self.regra(n['id'])
        with sqlite3.connect(self.db) as con:   # dois envios do transporte manual, direto no banco de teste
            for pk, st in ((1, 'pendente'), (2, 'incerto')):
                con.execute("INSERT INTO envios (regra_id, numero_id, item_pk, slot, status, mensagem, transporte,"
                            " criado_em) VALUES (?,?,?,?,?,'msg','manual',?)",
                            (r['id'], n['id'], pk, f's{pk}', st, f'2026-11-03T0{pk}:00:00'))
        con.close()
        fila = self.ok('GET', 'fila')
        self.assertEqual([e['status'] for e in fila], ['pendente', 'incerto'])
        e = self.ok('PATCH', f'envios/{fila[0]["id"]}', {'status': 'enviado'})
        self.assertEqual(e['status'], 'enviado')
        self.assertTrue(e['enviado_em'])
        self.assertEqual(self.api('PATCH', f'envios/{fila[0]["id"]}', {'status': 'pulado'})[0], 409)
        self.assertEqual(self.api('PATCH', f'envios/{fila[1]["id"]}', {'status': 'erro'})[0], 400)
        self.assertEqual(self.ok('PATCH', f'envios/{fila[1]["id"]}', {'status': 'pulado'})['status'], 'pulado')
        self.assertEqual(self.ok('GET', 'fila'), [])
        self.assertEqual(self.api('PATCH', 'envios/999', {'status': 'pulado'})[0], 404)

    def test_ca10_historico_por_periodo_e_status(self):
        n = self.numero()
        r = self.regra(n['id'])
        self.ok('POST', f'regras/{r["id"]}/agora', {})
        hoje = datetime.now().date().isoformat()
        self.assertEqual(len(self.ok('GET', f'envios?desde={hoje}&status=enviado')), 1)
        self.assertEqual(self.ok('GET', 'envios?status=erro'), [])
        self.assertEqual(self.ok('GET', 'envios?desde=2999-01-01'), [])
        self.assertEqual(self.api('GET', 'envios?desde=ontem')[0], 400)
        self.assertEqual(self.api('GET', 'envios?status=qualquer')[0], 400)

    def test_status_e_disparo_0_nao_inicia_a_thread(self):
        n = self.numero()
        agora = datetime.now()
        self.regra(n['id'], horarios=[agora.strftime('%H:%M')])   # horário do minuto atual
        time.sleep(3)   # com TICK_SEG=1, um agendador ligado já teria disparado
        self.assertEqual(self.ok('GET', 'status'), {'agendador': 'desligado', 'transporte': 'falso', 'ultimo_tick': None})
        self.assertEqual(self.ok('GET', 'envios'), [])
        self.assertEqual(self.linhas_jsonl(), [])
        self.assertIn('agendador desligado, transporte falso', self.saida())

    def test_404_405_e_ids(self):
        for caminho in ('x', 'numeros/0', 'numeros/abc', 'numeros/1/', 'regras/1/previa', '', 'numeros/' + '9' * 19):
            with self.subTest(caminho=caminho):
                self.assertEqual(self.api('GET', caminho)[0], 404)
        self.assertEqual(self.api('DELETE', 'numeros')[0], 405)
        self.assertEqual(self.api('GET', 'previa')[0], 405)
        self.assertEqual(self.api('POST', 'status', {})[0], 405)

    def test_corpo_415_400_413(self):
        h = self.local()
        st, _, _ = self.pedir('POST', '/api/disparo/numeros', b'{"nome": "x"}', h)   # sem Content-Type
        self.assertEqual(st, 415)
        st, _, _ = self.pedir('POST', '/api/disparo/numeros', b'{nao json', {**h, 'Content-Type': 'application/json'})
        self.assertEqual(st, 400)
        for corpo in ([], 'texto', 3):
            with self.subTest(corpo=corpo):
                self.assertEqual(self.api('POST', 'numeros', json.dumps(corpo).encode(),
                                          {**h, 'Content-Type': 'application/json'})[0], 400)
        st, _, _ = self.pedir('POST', '/api/disparo/numeros', b'',
                              {**h, 'Content-Type': 'application/json', 'Content-Length': str(6 * 1024 * 1024)})
        self.assertEqual(st, 413)
        self.assertEqual(self.ok('GET', 'numeros'), [])

    def test_ca13_origens_do_ml_e_de_fora_recebem_403(self):
        n = self.numero()
        alvos = [('GET', 'numeros', None), ('GET', 'fila', None), ('GET', 'status', None),
                 ('POST', 'numeros', {'nome': 'x', 'grupo_nome': 'g'}), ('PUT', f'numeros/{n["id"]}', {'nome': 'y'}),
                 ('PATCH', 'envios/1', {'status': 'pulado'}), ('DELETE', f'numeros/{n["id"]}', None),
                 ('POST', 'previa', {}), ('OPTIONS', 'numeros', None)]
        origens = [{'Origin': o, 'Sec-Fetch-Site': 'cross-site'} for o in ML]
        origens += [{'Origin': 'https://evil.com'}, {'Sec-Fetch-Site': 'cross-site'}, {'Origin': 'null'}]
        for metodo, resto, corpo in alvos:
            for h in origens:
                cab = dict(h)
                if metodo == 'OPTIONS':
                    cab['Access-Control-Request-Method'] = 'GET'
                with self.subTest(metodo=metodo, resto=resto, h=h):
                    st, cabecalhos, _ = self.pedir(metodo, '/api/disparo/' + resto, corpo, cab)
                    self.assertEqual(st, 403)
                    self.assertIsNone(cabecalhos.get('Access-Control-Allow-Origin'))
        self.assertEqual([x['nome'] for x in self.ok('GET', 'numeros')], ['Loja 1'], 'nada mudou')
        self.assertEqual(self.pedir('GET', '/api/disparo/numeros')[0], 200, 'sem Origin (curl local) passa')

    def test_s2_teto_dos_campos_de_data(self):
        base = {'loja': 'amazon', 'item_id': 'B0TETO0001', 'cat': 'Teto',
                'url': 'https://www.amazon.com.br/dp/B0TETO0001?tag=desejodemen01-20'}
        st, _, d = self.postar([{**base, 'data': {'titulo': 't' * 500, 'preco': 'p' * 200}}])
        self.assertEqual(st, 200, d)
        for data in ({'titulo': 't' * 501}, {'titulo': 'x', 'preco': 'p' * 201}, {'titulo': 'x', 'cupom': 'c' * 201},
                     {'titulo': 'x', 'imagem': 'https://m.media-amazon.com/' + 'i' * 200}):
            with self.subTest(campo=[k for k, v in data.items() if len(v) > 1]):
                st, _, d = self.postar([{**base, 'data': data}])
                self.assertEqual(st, 400, d)
                self.assertIn('passa de', json.loads(d)['error'])
        pk = next(i['id'] for i in json.loads(self.pedir('GET', '/api/items')[2]) if i['item_id'] == 'B0TETO0001')
        st, _, d = self.pedir('PATCH', f'/api/items/{pk}', {'data': {'titulo': 't' * 501}}, self.local())
        self.assertEqual(st, 400, d)
        titulo = next(i['data']['titulo'] for i in json.loads(self.pedir('GET', '/api/items')[2]) if i['id'] == pk)
        self.assertEqual(len(titulo), 500, 'o 400 não gravou nada')

    def test_r1_pausar_regra_com_template_apagado(self):
        n = self.numero()
        r = self.regra(n['id'])
        tpls = {k: v for k, v in DEFAULT_TEMPLATES.items() if k != 'Template 2'}
        self.assertEqual(self.pedir('PUT', '/api/config/templates', tpls, self.local())[0], 200)
        self.assertEqual(self.ok('PUT', f'regras/{r["id"]}', {'ativa': 0})['ativa'], 0)
        self.assertEqual(self.api('PUT', f'regras/{r["id"]}', {'template': 'x'})[0], 400)
        self.assertEqual(self.api('PUT', f'regras/{r["id"]}', {'template': 'Template 2'})[0], 400)

    def test_r5_proximo_nulo_com_numero_desativado(self):
        n = self.numero()
        r = self.regra(n['id'])
        self.assertIsNotNone(r['proximo'])
        self.ok('PUT', f'numeros/{n["id"]}', {'ativo': 0})
        self.assertIsNone(self.ok('GET', 'regras')[0]['proximo'])

    def test_ca1_telefone_fora_da_saida_do_servidor(self):
        n = self.numero()
        self.ok('PUT', f'numeros/{n["id"]}', {'telefone': TELEFONE, 'grupo_id': GRUPO_ID})
        self.api('PUT', f'numeros/{n["id"]}', {'telefone': 'x' + TELEFONE})
        self.ok('GET', 'numeros')
        saida = self.saida()
        self.assertIn('/api/disparo/numeros', saida, 'o log de acesso registra as rotas')
        self.assertSemDadoPessoal(saida)


# ================================================================ agendador no servidor
class TestAgendador(ServidorDisparo):
    """ACHADINHOS_DISPARO=1 e TICK_SEG=1: horário do minuto atual vira envio; reinício não repete (CA7)."""

    def status(self):
        return self.ok('GET', 'status')

    def test_ca7_ca9_envia_no_horario_e_reinicio_nao_repete(self):
        agora = datetime.now()
        if (agora.hour, agora.minute) == (23, 59) and agora.second > 45:
            time.sleep(20)   # o slot tem que ser "de hoje" quando o tick rodar
            agora = datetime.now()
        self.preparar()
        n = self.numero()
        r = self.regra(n['id'], horarios=[agora.strftime('%H:%M')])
        linhas = esperar(self.linhas_jsonl, desc='o envio do agendador no JSONL')
        self.assertEqual(len(linhas), 1)
        self.assertEqual(linhas[0]['grupo_nome'], 'Achadinhos')
        self.assertIn('?tag=desejodemen01-20', linhas[0]['texto'])
        st = self.status()
        self.assertEqual((st['agendador'], st['transporte']), ('ligado', 'falso'))
        self.assertTrue(st['ultimo_tick'])
        envios = self.ok('GET', 'envios')
        self.assertEqual([(e['regra_id'], e['status']) for e in envios], [(r['id'], 'enviado')])

        # um envio que ficou "enviando" (servidor caiu no meio do envio)
        with sqlite3.connect(self.db) as con:
            con.execute("INSERT INTO envios (regra_id, numero_id, item_pk, slot, status, mensagem, transporte,"
                        " criado_em) VALUES (?,?,2,'caiu','enviando','msg','falso',?)",
                        (r['id'], n['id'], agora.isoformat(timespec='seconds')))
        con.close()

        self.parar_servidor()
        self.subir()
        inicio = time.monotonic()
        primeiro = esperar(lambda: self.status()['ultimo_tick'], desc='o primeiro tick depois do reinício')
        esperar(lambda: self.status()['ultimo_tick'] != primeiro or None, desc='um segundo tick')
        self.assertLess(time.monotonic() - inicio, 15)
        self.assertEqual(len(self.linhas_jsonl()), 1, 'o reinício não reenviou o horário já processado')
        envios = {e['slot']: e['status'] for e in self.ok('GET', 'envios')}
        self.assertEqual(envios['caiu'], 'incerto', 'enviando vira incerto no início')
        self.assertEqual(len(envios), 2)
        self.assertEqual([e['slot'] for e in self.ok('GET', 'fila')], ['caiu'])

        saida = self.saida()
        self.assertIn('agendador ligado, transporte falso', saida)
        self.assertIn('1 envio(s) criado(s)', saida)
        self.assertIn('marcado(s) como incerto', saida)
        self.assertSemDadoPessoal(saida)


class TestTransportePorAmbiente(unittest.TestCase):
    """Configuração errada do transporte impede o servidor de subir, sem dado pessoal na mensagem."""

    def test_transporte_desconhecido_ou_sem_arquivo(self):
        d = tempfile.mkdtemp(prefix='achadinhos-disparo-env-')
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        for extra in ({'ACHADINHOS_TRANSPORTE': 'baileys'}, {'ACHADINHOS_TRANSPORTE': 'falso'},
                      {'ACHADINHOS_TICK_SEG': 'zero'}):
            with self.subTest(extra=extra):
                env = TS.ambiente(os.path.join(d, 'x.db'), TS.porta_livre())
                for k in VARS_DISPARO:
                    env.pop(k, None)
                env.update(extra)
                r = subprocess.run([sys.executable, '-u', 'servidor.py'], cwd=TS.RAIZ, env=env,
                                   capture_output=True, text=True, timeout=30)
                self.assertNotEqual(r.returncode, 0)
                self.assertIn('ACHADINHOS_', r.stderr)


if __name__ == '__main__':
    unittest.main()
