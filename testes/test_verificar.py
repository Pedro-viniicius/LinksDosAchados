#!/usr/bin/env python3
"""Testes do verificar.py (docs/produto/planos/endurecer-engenharia-e-operacao.md, etapas 5 e 8).

Uso:  python3 testes/test_verificar.py -v

Provam o ambiente isolado do filho (sem Secret, proxies mortos, dados numa pasta temporária), o TZ do
--hora, a recusa da 8765 e da porta ocupada no --front, a leitura do resumo (com os motivos de skip) e o
aviso do requirements.txt, e o portão de commit (etapa 8, CA7): varredura de segredos e .githooks/pre-commit
em repositórios git temporários (nunca no repositório real). Nenhum teste roda a suíte de verdade, abre o
achadinhos.db, sobe servidor ou sai para a rede: a suíte de mentira mora numa pasta temporária, e o hook dos
repositórios temporários só vê a suíte de mentira deles (sem este arquivo: nada de recursão). Os "segredos" daqui são falsos e os
testes nunca imprimem valor de variável de ambiente, só se ela existe. Só biblioteca padrão.
"""
import atexit
import datetime
import glob
import io
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import textwrap
import unittest
from contextlib import redirect_stdout
from unittest import mock

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Rodando dentro de um hook, GIT_DIR/GIT_INDEX_FILE apontariam para o repositório real: fora com eles.
for _k in [k for k in os.environ if k.startswith('GIT_')]:
    del os.environ[_k]
TMP = tempfile.mkdtemp(prefix='achadinhos-verificar-')
atexit.register(shutil.rmtree, TMP, ignore_errors=True)
sys.path.insert(0, RAIZ)
import verificar as V   # noqa: E402

FALSO = 'falso-' + 'x' * 26   # 32 caracteres, nunca um segredo de verdade
SEGREDOS = {
    'ACHADINHOS_SHOPEE_SECRET': FALSO,
    'ACHADINHOS_ML_SECRET': FALSO,
    'ACHADINHOS_SHOPEE_APP_ID': '123',
    'ACHADINHOS_ML_TOKENS': os.path.join(RAIZ, 'ml_tokens.json'),
    'ACHADINHOS_DB': os.path.join(RAIZ, 'achadinhos.db'),
    'ACHADINHOS_FEITOS_ATUALIZAR': os.path.join(RAIZ, 'atualizar_precos_feitos.txt'),
    'ACHADINHOS_TESTE_DADOS_REAIS': '1',
    'OUTRO_SECRET_QUALQUER': FALSO,
    'http_proxy': 'http://proxy.de.verdade:3128',
    'HTTPS_PROXY': 'http://proxy.de.verdade:3128',
    'no_proxy': '*',
}


def nova_pasta():
    return tempfile.mkdtemp(dir=TMP)


class AmbienteIsolado(unittest.TestCase):
    def setUp(self):
        self.pasta = nova_pasta()
        self.base = dict(SEGREDOS, HOME='/home/alguem', PATH='/usr/bin')
        self.env = V.ambiente_isolado(self.pasta, base=self.base)

    def test_sem_secret_app_id_nem_achadinhos_herdada(self):
        for k in ('ACHADINHOS_SHOPEE_SECRET', 'ACHADINHOS_ML_SECRET', 'ACHADINHOS_SHOPEE_APP_ID',
                  'OUTRO_SECRET_QUALQUER', 'ACHADINHOS_TESTE_DADOS_REAIS'):
            self.assertNotIn(k, self.env)
        self.assertFalse([k for k in self.env if 'SECRET' in k.upper()])
        self.assertNotIn(FALSO, self.env.values())

    def test_proxies_mortos_em_minusculas_e_maiusculas(self):
        for k in ('http_proxy', 'https_proxy', 'ftp_proxy', 'HTTP_PROXY', 'HTTPS_PROXY', 'FTP_PROXY'):
            self.assertEqual(self.env[k], 'http://127.0.0.1:9', k)
        self.assertEqual(self.env['no_proxy'], '')
        self.assertEqual(self.env['NO_PROXY'], '')

    def test_api_v1_e_agendador_desligados(self):
        self.assertEqual(self.env['ACHADINHOS_API_TOKEN_ARQUIVO'], '/nao/existe')
        self.assertEqual(self.env['ACHADINHOS_DISPARO'], '0')

    def test_banco_progresso_tokens_e_catalogo_na_pasta_temporaria(self):
        for k in ('ACHADINHOS_DB', 'ACHADINHOS_FEITOS', 'ACHADINHOS_FEITOS_SHOPEE', 'ACHADINHOS_FEITOS_ATUALIZAR',
                  'ACHADINHOS_ML_TOKENS', 'ACHADINHOS_ML_CATALOGO', 'ACHADINHOS_GARIMPO_DIR'):
            self.assertEqual(os.path.dirname(self.env[k]), self.pasta, k)

    def test_sem_variaveis_do_git(self):
        """Dentro do hook, GIT_DIR e GIT_INDEX_FILE apontam para o repositório real: o filho não as herda."""
        base = dict(self.base, GIT_DIR='/repo/.git', GIT_INDEX_FILE='/repo/.git/index', GIT_WORK_TREE='/repo')
        env = V.ambiente_isolado(self.pasta, base=base)
        self.assertEqual([k for k in env if k.startswith('GIT_')], [])

    def test_resto_do_ambiente_fica(self):
        self.assertEqual(self.env['HOME'], '/home/alguem')
        self.assertEqual(self.env['PATH'], '/usr/bin')

    def test_dados_reais_so_com_a_opcao(self):
        env = V.ambiente_isolado(self.pasta, base=self.base, dados_reais=True)
        self.assertEqual(env['ACHADINHOS_TESTE_DADOS_REAIS'], '1')

    def test_tz_so_com_a_hora(self):
        self.assertNotIn('TZ', V.ambiente_isolado(self.pasta, base={}))
        self.assertEqual(V.ambiente_isolado(self.pasta, base={'TZ': 'UTC'}, tz='Etc/GMT+1')['TZ'], 'Etc/GMT+1')
        self.assertEqual(V.ambiente_isolado(self.pasta, base={'TZ': 'UTC'})['TZ'], 'UTC')

    def test_o_filho_de_verdade_nao_ve_secret_e_bate_no_proxy_morto(self):
        """Ponta a ponta: um teste de mentira roda pelo rodar_arquivo com os.environ cheio de segredos falsos."""
        suite = nova_pasta()
        caminho = os.path.join(suite, 'test_filho.py')
        with open(caminho, 'w', encoding='utf-8') as f:
            f.write(textwrap.dedent('''\
                import os, unittest, urllib.error, urllib.request
                class Filho(unittest.TestCase):
                    def test_sem_secret(self):
                        self.assertEqual([k for k in os.environ if 'SECRET' in k.upper()], [])
                        self.assertNotIn('ACHADINHOS_SHOPEE_APP_ID', os.environ)
                    def test_proxy_morto(self):
                        self.assertEqual(urllib.request.getproxies().get('https'), 'http://127.0.0.1:9')
                        with self.assertRaises(urllib.error.URLError) as c:
                            urllib.request.urlopen('https://www.amazon.com.br/', timeout=5)
                        self.assertIsInstance(c.exception.reason, ConnectionRefusedError)
                    def test_banco_fora_da_raiz(self):
                        self.assertFalse(os.environ['ACHADINHOS_DB'].startswith(os.environ['RAIZ_REAL']))
                if __name__ == '__main__':
                    unittest.main()
            '''))
        with mock.patch.dict(os.environ, dict(SEGREDOS, RAIZ_REAL=RAIZ)):
            env = V.ambiente_isolado(nova_pasta())
        log = os.path.join(suite, 'log.txt')
        r = V.rodar_arquivo('test_filho', [sys.executable, caminho, '-v'], V.ler_resumo_unittest, env, log)
        self.assertTrue(r.ok, V.ler_log(log))
        self.assertEqual(r.resumo, 'Ran 3  OK')
        self.assertNotIn(FALSO, V.ler_log(log))


class Hora(unittest.TestCase):
    def utc(self, h, m, s=30):
        return datetime.datetime(2026, 11, 9, h, m, s, tzinfo=datetime.timezone.utc)

    def test_casos_calculados(self):
        casos = [  # (UTC, hora pedida, TZ esperado): Etc/GMT+N quer dizer local = UTC − N
            ((17, 25), 3, 'Etc/GMT-10'),   # 17:25 + 10 h = 03:25 do dia seguinte
            ((17, 25), 23, 'Etc/GMT-6'),   # 17:25 + 6 h = 23:25
            ((17, 25), 17, 'Etc/GMT'),     # sem deslocamento
            ((17, 25), 14, 'Etc/GMT+3'),   # 17:25 − 3 h = 14:25
            ((0, 10), 23, 'Etc/GMT+1'),    # 00:10 − 1 h = 23:10 do dia anterior
            ((23, 59), 0, 'Etc/GMT-1'),    # 23:59 + 1 h = 00:59
            ((12, 0), 0, 'Etc/GMT-12'),    # 12:00 + 12 h = 00:00 (o intervalo é de −12 a +11)
            ((11, 0), 0, 'Etc/GMT+11'),    # 11:00 − 11 h = 00:00
        ]
        for (h, m), hora, esperado in casos:
            with self.subTest(utc=f'{h}:{m}', hora=hora):
                self.assertEqual(V.tz_para_hora(hora, self.utc(h, m)), esperado)

    def test_relogio_local_de_cada_hora_pelo_zoneinfo(self):
        import zoneinfo
        for h_utc in range(24):
            for hora in range(24):
                with self.subTest(utc=h_utc, hora=hora):
                    agora = self.utc(h_utc, 59)
                    tz = V.tz_para_hora(hora, agora)
                    self.assertEqual(agora.astimezone(zoneinfo.ZoneInfo(tz)).hour, hora)

    def hora_no_filho(self, cmd, hora):
        """Hora local que o filho vê; repete uma vez se a hora UTC virou no meio."""
        for _ in range(2):
            antes = datetime.datetime.now(datetime.timezone.utc).hour
            env = V.ambiente_isolado(nova_pasta(), tz=V.tz_para_hora(hora))
            saida = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=30).stdout.strip()
            if datetime.datetime.now(datetime.timezone.utc).hour == antes:
                return saida
        return saida

    def test_python_do_filho_ve_a_hora(self):
        for hora in (3, 23):
            with self.subTest(hora=hora):
                cmd = [sys.executable, '-c', 'import time; print(time.localtime().tm_hour)']
                self.assertEqual(self.hora_no_filho(cmd, hora), str(hora))

    @unittest.skipUnless(shutil.which('node'), 'node não está no PATH')
    def test_node_do_filho_ve_a_hora(self):
        """O Node (ICU) ignora TZ POSIX puro e cai no fuso do sistema: por isso o Etc/GMT±N."""
        for hora in (3, 23):
            with self.subTest(hora=hora):
                cmd = ['node', '-e', 'console.log(new Date().getHours())']
                self.assertEqual(self.hora_no_filho(cmd, hora), str(hora))

    def test_hora_invalida_e_uso_errado(self):
        for valor in ('24', '-1', 'x', '3.5', ''):
            with self.subTest(valor=valor):
                p = subprocess.run([sys.executable, os.path.join(RAIZ, 'verificar.py'), '--hora', valor],
                                   capture_output=True, text=True, timeout=30)
                self.assertEqual(p.returncode, 2)


def logs_existentes():
    return set(glob.glob(os.path.join(RAIZ, 'logs', 'verificar-*')))


class Front(unittest.TestCase):
    def rodar_verificar(self, *args):
        return subprocess.run([sys.executable, os.path.join(RAIZ, 'verificar.py'), *args],
                              capture_output=True, text=True, timeout=60)

    def test_porta_padrao_e_8766(self):
        self.assertEqual(V.PORTA_FRONT, 8766)
        self.assertEqual(V.PORTA_REAL, 8765)

    def test_recusa_a_8765_antes_de_qualquer_coisa(self):
        antes = logs_existentes()
        with mock.patch.object(V, 'copiar_banco') as copiar, mock.patch.object(V, 'rodar') as rodar:
            with redirect_stdout(io.StringIO()), mock.patch('sys.stderr', io.StringIO()) as err:
                self.assertEqual(V.main(['--front', '--porta-front', '8765']), 2)
        self.assertIn('8765', err.getvalue())
        copiar.assert_not_called()
        rodar.assert_not_called()
        self.assertEqual(logs_existentes(), antes)

    def test_recusa_a_8765_pela_linha_de_comando(self):
        p = self.rodar_verificar('--front', '--porta-front', '8765')
        self.assertEqual(p.returncode, 2)
        self.assertIn('8765', p.stderr)
        self.assertEqual(p.stdout, '')

    def test_recusa_porta_ocupada(self):
        s = socket.socket()
        s.bind(('127.0.0.1', 0))
        s.listen()
        self.addCleanup(s.close)
        porta = s.getsockname()[1]
        p = self.rodar_verificar('--front', '--porta-front', str(porta))
        self.assertEqual(p.returncode, 2)
        self.assertIn('ocupada', p.stderr)

    def test_recusa_porta_invalida(self):
        for porta in ('0', '80', '70000', 'abc'):
            with self.subTest(porta=porta):
                self.assertEqual(self.rodar_verificar('--front', '--porta-front', porta).returncode, 2)

    def test_porta_do_ambiente_nunca_vale(self):
        """PORTA/ACHADINHOS_PORTA=8765 herdados não chegam ao servidor nem ao runner do --front."""
        base = V.ambiente_isolado(nova_pasta(), base={'PORTA': '8765', 'ACHADINHOS_PORTA': '8765', 'PATH': '/usr/bin'})
        servidor, runner = V.ambiente_front(base, V.PORTA_FRONT, '/tmp/copia.db')
        self.assertEqual(servidor['ACHADINHOS_PORTA'], '8766')
        self.assertNotIn('PORTA', servidor)
        self.assertEqual(runner['PORTA'], '8766')
        self.assertEqual(servidor['ACHADINHOS_DB'], '/tmp/copia.db')
        self.assertEqual(servidor['ACHADINHOS_DISPARO'], '0')
        self.assertEqual(servidor['ACHADINHOS_API_TOKEN_ARQUIVO'], '/nao/existe')
        self.assertEqual(servidor['https_proxy'], 'http://127.0.0.1:9')   # o /api/fetch não sai
        self.assertNotIn('https_proxy', runner)                          # o Chrome baixa as 2 fotos reais

    def test_rodar_front_com_porta_ocupada_devolve_resultado_vermelho(self):
        impressos = []
        with mock.patch.object(V, 'porta_ocupada', return_value=True), \
                mock.patch.object(V, 'copiar_banco') as copiar:
            resultados = V.rodar_front({}, V.PORTA_FRONT, nova_pasta(), impressos.append)
        self.assertEqual(len(resultados), 1)
        r = resultados[0]
        self.assertEqual((r.nome, r.ok, r.saida), ('front', False, 1))
        self.assertIn('ocupada', r.resumo)
        self.assertEqual(impressos, [r])
        copiar.assert_not_called()

    def test_toda_pagina_tem_classificacao(self):
        paginas, problemas = V.paginas_do_front()
        self.assertEqual(problemas, [])
        self.assertNotIn('disparo-integracao', paginas)
        self.assertNotIn('genero-integracao', paginas)
        self.assertEqual(set(V.FORA_DO_FRONT), {'disparo-integracao', 'genero-integracao'})

    def test_pagina_nova_sem_classificacao_e_falha(self):
        with mock.patch.object(V, 'FRONT', V.FRONT[1:]):
            _, problemas = V.paginas_do_front()
        self.assertEqual(len(problemas), 1)
        self.assertIn(V.FRONT[0], problemas[0])

    def test_servidor_estranho_na_porta_nunca_vale(self):
        """Se outro processo atende na porta, o --front só segue quando o log do NOSSO servidor diz que subiu
        sobre a cópia."""
        import http.server
        import threading

        class Ok(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()

            def log_message(self, *a):
                pass
        estranho = http.server.HTTPServer(('127.0.0.1', 0), Ok)
        threading.Thread(target=estranho.serve_forever, daemon=True).start()
        self.addCleanup(estranho.server_close)
        self.addCleanup(estranho.shutdown)
        porta = estranho.server_address[1]
        proc = mock.Mock()
        proc.poll.return_value = None   # o nosso ainda "subindo"
        log = os.path.join(nova_pasta(), 'front-servidor.txt')
        with open(log, 'w') as f:
            f.write('API v1 desligada\n')
        with self.assertRaises(RuntimeError):
            V.esperar_servidor(proc, porta, log, '/tmp/x/copia.db', limite=1)
        with open(log, 'a') as f:
            f.write(f'Site em http://localhost:{porta}/  (banco: /tmp/x/copia.db)\n')
        V.esperar_servidor(proc, porta, log, '/tmp/x/copia.db', limite=5)
        proc.poll.return_value = 1      # o nosso morreu: nunca segue
        with self.assertRaises(RuntimeError):
            V.esperar_servidor(proc, porta, log, '/tmp/x/copia.db', limite=5)

    def test_copia_do_banco_em_modo_leitura_e_0600(self):
        import sqlite3
        pasta = nova_pasta()
        origem = os.path.join(pasta, 'origem.db')
        con = sqlite3.connect(origem)
        con.execute('CREATE TABLE items (id INTEGER)')
        con.execute('INSERT INTO items VALUES (1)')
        con.commit()
        con.close()
        os.chmod(origem, 0o444)   # gravar na origem daria erro
        destino = os.path.join(pasta, 'copia.db')
        V.copiar_banco(origem, destino)
        self.assertEqual(os.stat(destino).st_mode & 0o777, 0o600)
        con = sqlite3.connect(destino)
        self.addCleanup(con.close)
        self.assertEqual(con.execute('SELECT COUNT(*) FROM items').fetchone(), (1,))
        with self.assertRaises(RuntimeError):
            V.copiar_banco(os.path.join(pasta, 'nao-existe.db'), os.path.join(pasta, 'x.db'))


SAIDA_PY = '''\
test_a (test_x.A.test_a) ... ok
test_b (test_x.A.test_b)
Docstring do teste. ... skipped 'dados reais: rode verificar.py --dados-reais'
test_c (test_x.A.test_c) ... skipped 'dados reais: rode verificar.py --dados-reais'
test_d (test_x.B.test_d) ... skipped "sem o banco d'água"
setUpClass (test_x.C) ... skipped 'classe inteira'

----------------------------------------------------------------------
Ran 4 tests in 0.010s

OK (skipped=4)
'''


class Resumo(unittest.TestCase):
    def test_python_ok_com_motivos_de_skip(self):
        ok, resumo, skips = V.ler_resumo_unittest(SAIDA_PY)
        self.assertTrue(ok)
        self.assertEqual(resumo, 'Ran 4  OK (skipped=4)')
        self.assertEqual(skips, {'dados reais: rode verificar.py --dados-reais': 2,
                                 "sem o banco d'água": 1, 'classe inteira': 1})

    def test_python_falhou(self):
        texto = 'test_a (m.A.test_a) ... FAIL\n\nRan 39 tests in 199.888s\n\nFAILED (failures=1, errors=2, skipped=1)\n'
        self.assertEqual(V.ler_resumo_unittest(texto)[:2], (False, 'Ran 39  FAILED (failures=1, errors=2, skipped=1)'))

    def test_python_sem_resumo_ou_sem_teste(self):
        self.assertFalse(V.ler_resumo_unittest('Traceback (most recent call last):\nImportError: x\n')[0])
        self.assertFalse(V.ler_resumo_unittest('\nRan 0 tests in 0.000s\n\nNO TESTS RAN\n')[0])
        self.assertFalse(V.ler_resumo_unittest('\nRan 0 tests in 0.000s\n\nOK\n')[0])
        ok, resumo, _ = V.ler_resumo_unittest('')   # arquivo sem unittest.main(): sai com 0 e não roda nada
        self.assertFalse(ok)
        self.assertIn('nenhum teste rodou', resumo)

    def test_python_saida_impressa_por_um_teste_nao_engana(self):
        """Um "OK" impresso no meio não vale: conta a última linha de fechamento."""
        texto = 'OK\nRan 3 tests in 0.1s\n\nFAILED (failures=1)\n'
        self.assertFalse(V.ler_resumo_unittest(texto)[0])

    def test_node(self):
        texto = ('TAP version 13\nok 1 - a\nok 2 - b # SKIP sem chrome\nnot ok 3 - c\n'
                 '1..3\n# tests 3\n# suites 0\n# pass 1\n# fail 1\n# cancelled 0\n# skipped 1\n# todo 0\n')
        ok, resumo, skips = V.ler_resumo_node(texto)
        self.assertFalse(ok)
        self.assertEqual(resumo, 'tests 3 pass 1 fail 1 (skipped=1)')
        self.assertEqual(skips, {'sem chrome': 1})
        verde = texto.replace('# pass 1\n# fail 1', '# pass 2\n# fail 0')
        self.assertTrue(V.ler_resumo_node(verde)[0])
        self.assertFalse(V.ler_resumo_node('Error: Cannot find module\n')[0])
        self.assertFalse(V.ler_resumo_node(verde.replace('# cancelled 0', '# cancelled 1'))[0])

    def test_front(self):
        self.assertEqual(V.ler_resumo_front('RESULTADO: OK\nok  a\nok  b\n')[:2], (True, 'RESULTADO: OK'))
        self.assertFalse(V.ler_resumo_front('RESULTADO: FALHOU (2 de 40)\nFALHOU: a\n')[0])
        self.assertFalse(V.ler_resumo_front('RESULTADO: PENDENTE\n')[0])
        self.assertFalse(V.ler_resumo_front('(sem saída: o servidor está no ar em :8766?)\n')[0])

    def test_linha_do_resumo(self):
        r = V.Resultado('test_x', True, 0, 1.25, 'Ran 4  OK (skipped=4)')
        self.assertEqual(r.linha().split(), ['test_x', 'saida=0', '1.2s', 'Ran', '4', 'OK', '(skipped=4)'])
        self.assertIn('saida=TIMEOUT', V.Resultado('t', False, None).linha())


class Requirements(unittest.TestCase):
    def escrever(self, texto):
        caminho = os.path.join(nova_pasta(), 'requirements.txt')
        with open(caminho, 'w', encoding='utf-8') as f:
            f.write(texto)
        return caminho

    def test_sem_arquivo_avisa_sem_falhar(self):
        avisos = V.conferir_requirements(os.path.join(nova_pasta(), 'requirements.txt'))
        self.assertEqual(len(avisos), 1)
        self.assertIn('sem requirements.txt', avisos[0])

    def test_diferencas(self):
        versoes = {'beautifulsoup4': '4.14.3', 'lxml': '5.0.0'}

        def versao(nome):
            if nome not in versoes:
                raise V.importlib.metadata.PackageNotFoundError(nome)
            return versoes[nome]
        caminho = self.escrever('# Python >= 3.14, Node >= 22\nbeautifulsoup4==4.14.3\nlxml==6.0.2  # parser\n'
                                'falta==1.0\nsolto>=2\n\n')
        with mock.patch.object(V.importlib.metadata, 'version', versao):
            avisos = V.conferir_requirements(caminho)
        self.assertEqual(len(avisos), 3, avisos)
        self.assertIn('lxml 6.0.2 pedido, 5.0.0 instalado', avisos[0])
        self.assertIn('falta 1.0 pedido, mas não está instalado', avisos[1])
        self.assertIn(':5:', avisos[2])

    def test_igual_nao_avisa(self):
        caminho = self.escrever('beautifulsoup4==4.14.3\n')
        with mock.patch.object(V.importlib.metadata, 'version', return_value='4.14.3'):
            self.assertEqual(V.conferir_requirements(caminho), [])


class SuiteDeMentira(unittest.TestCase):
    """main() inteiro sobre uma suíte de mentira: saída 0/1, --rapido, linha por arquivo e logs."""

    def setUp(self):
        self.raiz = nova_pasta()
        os.mkdir(os.path.join(self.raiz, 'testes'))
        self.escrever('test_verde.py', 'self.assertTrue(True)')
        self.escrever('test_genero_qa.py', 'self.assertTrue(True)')   # nome de um LENTO
        self.escrever('test_pula.py', 'self.skipTest("dados reais: rode verificar.py --dados-reais")')
        with open(os.path.join(self.raiz, 'codigo.py'), 'w') as f:
            f.write('x = 1\n')
        self.logs = os.path.join(self.raiz, 'logs')
        for alvo, valor in (('RAIZ', self.raiz), ('PASTA_LOGS', self.logs),
                            ('PASTAS_PY', (('testes', ''),)), ('PASTA_NODE', 'sem-node'),
                            ('COMPILAR', ('*.py',))):
            p = mock.patch.object(V, alvo, valor)
            p.start()
            self.addCleanup(p.stop)

    def escrever(self, nome, corpo):
        with open(os.path.join(self.raiz, 'testes', nome), 'w', encoding='utf-8') as f:
            f.write('import unittest\nclass T(unittest.TestCase):\n    def test_um(self):\n'
                    f'        {corpo}\nunittest.main()\n')

    def main(self, *args):
        out = io.StringIO()
        with redirect_stdout(out):
            saida = V.main(list(args))
        return saida, out.getvalue()

    def test_verde_e_rapido(self):
        saida, texto = self.main('--rapido')
        self.assertEqual(saida, 0, texto)
        # R2 (rodada 2): sem --dados-reais o LENTO leva segundos e o --rapido não o pula
        self.assertRegex(texto, r'test_genero_qa\s+saida=0')
        self.assertNotIn('pulado', texto)
        self.assertRegex(texto, r'test_verde\s+saida=0 .* Ran 1  OK\n')
        self.assertIn('skip (1): dados reais: rode verificar.py --dados-reais', texto)
        self.assertIn('aviso: sem requirements.txt', texto)
        pastas = glob.glob(os.path.join(self.logs, 'verificar-*'))
        self.assertEqual(len(pastas), 1)
        self.assertEqual(os.stat(pastas[0]).st_mode & 0o777, 0o700)
        self.assertEqual(sorted(os.listdir(pastas[0])), ['test_genero_qa.txt', 'test_pula.txt', 'test_verde.txt'])

    def test_rapido_com_dados_reais_pula_os_lentos(self):
        saida, texto = self.main('--rapido', '--dados-reais')
        self.assertEqual(saida, 0, texto)
        self.assertRegex(texto, r'test_genero_qa\s+pulado \(--rapido: lento com --dados-reais\)')
        self.assertRegex(texto, r'test_verde\s+saida=0')
        pastas = glob.glob(os.path.join(self.logs, 'verificar-*'))
        self.assertEqual(sorted(os.listdir(pastas[0])), ['test_pula.txt', 'test_verde.txt'])

    def test_porta_do_front_ocupada_durante_a_suite_e_falha_no_resumo(self):
        """R4 (rodada 2): livre na largada e ocupada quando o front vai começar: linha vermelha e FALHOU (saída
        1), nunca a saída 2 de uso errado sem resumo. Nada é copiado nem sobe servidor."""
        with mock.patch.object(V, 'porta_ocupada', side_effect=[False, True]) as ocupada, \
                mock.patch.object(V, 'copiar_banco') as copiar, mock.patch.object(V, 'esperar_servidor') as esperar:
            saida, texto = self.main('--rapido', '--front')
        self.assertEqual(saida, 1, texto)
        self.assertEqual(ocupada.call_count, 2)
        self.assertRegex(texto, r'\nfront\s+saida=1 .*a porta 8766 está ocupada')
        self.assertRegex(texto, r'FALHOU: 1 de \d+ em .*: front\n')
        self.assertRegex(texto, r'test_verde\s+saida=0')
        copiar.assert_not_called()
        esperar.assert_not_called()

    def test_lento_roda_sem_rapido(self):
        saida, texto = self.main()
        self.assertEqual(saida, 0, texto)
        self.assertRegex(texto, r'test_genero_qa\s+saida=0')

    def test_falha_sai_com_1(self):
        self.escrever('test_vermelho.py', 'self.assertEqual(1, 2)')
        saida, texto = self.main('--rapido')
        self.assertEqual(saida, 1)
        self.assertRegex(texto, r'test_vermelho\s+saida=1 .*FAILED \(failures=1\)')
        self.assertIn('FALHOU: 1 de', texto)

    def test_erro_de_compilacao_sai_com_1(self):
        with open(os.path.join(self.raiz, 'quebrado.py'), 'w') as f:
            f.write('def (:\n')
        saida, texto = self.main('--rapido')
        self.assertEqual(saida, 1)
        self.assertRegex(texto, r'py_compile .*FALHOU: quebrado\.py')

    def test_dados_reais_chega_ao_filho(self):
        self.escrever('test_pula.py',
                      'self.assertEqual(__import__("os").environ.get("ACHADINHOS_TESTE_DADOS_REAIS"), "1")')
        self.assertEqual(self.main('--rapido')[0], 1)
        self.assertEqual(self.main('--rapido', '--dados-reais')[0], 0)

    def test_timeout_derruba_o_grupo_inteiro(self):
        script = os.path.join(self.raiz, 'dorme.py')
        with open(script, 'w') as f:
            f.write('import subprocess, sys, time\n'
                    'p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])\n'
                    'print(p.pid, flush=True)\ntime.sleep(60)\n')
        log = os.path.join(self.raiz, 'dorme.txt')
        r = V.rodar_arquivo('dorme', [sys.executable, script], V.ler_resumo_unittest, dict(os.environ), log,
                            timeout=2)
        self.assertFalse(r.ok)
        self.assertIsNone(r.saida)
        neto = int(V.ler_log(log).split()[0])
        self.assertFalse(vivo(neto))

    def test_rastreados_deixa_fora_o_teste_que_nao_esta_no_indice(self):
        """Só no --pre-commit: o teste fora do índice não roda e aparece como "fora do commit"."""
        self.escrever('test_vermelho.py', 'self.assertEqual(1, 2)')
        out = io.StringIO()
        with redirect_stdout(out):
            saida = V.verificar(V.ler_argumentos(['--rapido']),
                                rastreados={'testes/test_verde.py', 'testes/test_pula.py'})
        texto = out.getvalue()
        self.assertEqual(saida, 0, texto)
        self.assertRegex(texto, r'test_vermelho\s+fora do commit \(não rastreado\)')
        self.assertRegex(texto, r'test_verde\s+saida=0')
        self.assertEqual(self.main('--rapido')[0], 1)   # fora do --pre-commit, todos rodam


# ---------------------------------------------------------------- portão de commit (etapa 8, CA7)

# Valores falsos montados na hora: a fonte deste arquivo não tem nenhum (o --tudo varre este arquivo).
FALSO32 = 'f4lso' + 'Q7z' * 9                     # 32 alfanuméricos
FALSO_BEARER = 'abc.DEF-ghi_' + 'x9' * 15        # 42 caracteres de token
# Formatos dos exemplos públicos da doc do ML (resposta do /oauth/token), com dígitos trocados.
ML_ACCESS = 'APP_' + 'USR-' + '8133606632685744-060115-' + '9' * 32 + '-577628017'
ML_REFRESH = 'T' + 'G-' + '5ad522a286f1200006ac4ed1' + '-577625007'
ML_CODE = 'T' + 'G-' + '61828b7fffcc9a001b4bc890' + '-314029626'
PEM = '-----BEGIN ' + 'RSA PRIVATE KEY-----'
# Formato do secrets.token_urlsafe (43 de [A-Za-z0-9_-]) e um AppID numérico da Shopee, inventados.
FALSO_URLSAFE = 'q9_Z' + '-k3V_w' * 6 + 'Lm'
APPID_NUM = '18' + '407' * 3
PEM_SIMPLES = '-----BEGIN ' + 'PRIVATE KEY-----'


class Padroes(unittest.TestCase):
    def tipos(self, linha):
        return [a.tipo for a in V.varrer_linhas('x.py', [(1, linha)])]

    def test_achados(self):
        casos = [
            (PEM, 'chave privada PEM'),
            (PEM_SIMPLES, 'chave privada PEM'),
            ('-----BEGIN ' + 'OPENSSH PRIVATE KEY-----', 'chave privada PEM'),
            ('Authorization: Bearer ' + FALSO_BEARER, 'Bearer com valor longo'),
            ("h = {'Authorization': 'bearer " + FALSO32 + "'}", 'Bearer com valor longo'),
            ('secret = "' + FALSO32 + '"', 'atribuição de segredo'),
            ("ACHADINHOS_SHOPEE_SECRET='" + FALSO32 + "'", 'atribuição de segredo'),
            ('"password": "' + FALSO32[:24] + '"', 'atribuição de segredo'),
            ('senha:' + FALSO32, 'atribuição de segredo'),
            ("{'token': '" + FALSO32 + "'}", 'atribuição de segredo'),
            ('APP_ID = ' + FALSO32, 'atribuição de segredo'),
            ('access_token=' + FALSO32, 'atribuição de segredo'),
            # S2 (rodada 2): hífen e sublinhado no valor (token_urlsafe), com dígito e letra
            ("API_TOKEN = '" + FALSO_URLSAFE + "'", 'atribuição de segredo'),
            ('{"token": "' + FALSO_URLSAFE + '"}', 'atribuição de segredo'),
            ('secret=' + FALSO_URLSAFE[:24], 'atribuição de segredo'),
            ('ACHADINHOS_SHOPEE_SECRET="' + '_-' * 6 + 'a1' * 6 + '"', 'atribuição de segredo'),
            # S2: AppID numérico (8 dígitos ou mais), com ou sem sublinhado, aspas ou dois-pontos
            ('ACHADINHOS_SHOPEE_APP_ID=' + APPID_NUM, 'AppID numérico'),
            ("APP_ID = '" + APPID_NUM + "'", 'AppID numérico'),
            ('{"appId": ' + APPID_NUM + '}', 'AppID numérico'),
            ("{'app_id': '" + APPID_NUM[:8] + "'}", 'AppID numérico'),
            ('appid:' + APPID_NUM, 'AppID numérico'),
            ('"access_token": "' + ML_ACCESS + '"', 'access token do Mercado Livre (APP_USR-)'),
            ('"refresh_token": "' + ML_REFRESH + '"', 'refresh token ou código do Mercado Livre (TG-)'),
            ('https://localhost/cb?code=' + ML_CODE + '&state=x', 'refresh token ou código do Mercado Livre (TG-)'),
        ]
        for linha, tipo in casos:
            with self.subTest(tipo=tipo, n=casos.index((linha, tipo))):
                self.assertIn(tipo, self.tipos(linha))

    def test_nao_achados(self):
        casos = [
            "token = os.environ.get('ACHADINHOS_API_TOKEN_ARQUIVO')",
            'secret = "' + FALSO32[:23] + '"',              # 23: curto
            'Bearer ' + 'x' * 31,                              # 31: curto
            'Bearer {token}',
            "SECRET = 'SEGREDO-MARCADOR-ml-5b1e77'",           # falso dos testes do ml_api: palavra MARCADOR
            "SECRET = 'SEGREDO-FALSO-DA-TRAVA-0001'",          # falso do test_trava_rodada: palavra FALSO
            "APP_ID = '18000" + "12345'",                      # AppID falso exato dos testes da Shopee (1800012345)
            "APP_ID = 'EXEMPLO-" + "1" * 20 + "'",             # palavra EXEMPLO
            "token = 'valor_de_teste-" + "1a" * 6 + "'",       # palavra teste
            'APP_ID = ' + APPID_NUM[:7],                       # 7 dígitos: curto
            "ACHADINHOS_SHOPEE_APP_ID=''",
            'token = ACHADINHOS_API_TOKEN_ARQUIVO_PADRAO',    # nome de variável: sem dígito
            'secret = "' + '9' * 30 + '"',                     # só dígitos, sem letra (e não é app_id)
            'senha = "' + '_-' * 15 + '"',                     # sem dígito nem letra
            'secret = "' + FALSO_URLSAFE[:23] + '"',           # 23: curto
            "ACCESS = 'APP_" + "USR-ACESSO-MARCADOR-0001-aaaaaaaaaaaa'",   # falso do test_ml_api
            "REFRESH = 'T" + "G-RENOVA-MARCADOR-0001-bbbbbbbbbbbbbb'",
            'sha = "' + 'a' * 40 + '"',                        # hash solto não é atribuição de segredo
            '-----BEGIN ' + 'PUBLIC KEY-----',
            '-----BEGIN ' + 'CERTIFICATE-----',
        ]
        for linha in casos:
            with self.subTest(n=casos.index(linha)):
                self.assertEqual(self.tipos(linha), [])

    def test_marcador_libera_e_fica_no_resultado(self):
        achados = V.varrer_linhas('x.py', [(7, 'secret = "' + FALSO32 + '"  ' + V.MARCADOR)])
        self.assertEqual([(a.onde(), a.liberado) for a in achados], [('x.py:7', True)])

    def test_o_proprio_verificar_nao_tem_o_marcador_no_codigo(self):
        """O MARCADOR é montado em duas partes; a única menção literal é a da docstring (sem achado)."""
        with open(os.path.join(RAIZ, 'verificar.py'), encoding='utf-8') as f:
            linhas = [(n, t) for n, t in enumerate(f.read().splitlines(), 1) if V.MARCADOR in t]
        self.assertEqual(len(linhas), 1)
        self.assertEqual(V.varrer_linhas('verificar.py', linhas), [])

    def test_relatorio_nunca_traz_o_trecho(self):
        linhas = [(1, 'secret = "' + FALSO32 + '"'), (2, 'Authorization: Bearer ' + FALSO_BEARER),
                  (3, 'x = "' + ML_ACCESS + '"  ' + V.MARCADOR)]
        achados = V.varrer_linhas('a.py', linhas)
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(V.relatar_segredos(achados, 1, 'staged'), 1)
        texto = out.getvalue()
        for valor in (FALSO32, FALSO_BEARER, ML_ACCESS, 'secret =', 'Authorization'):
            self.assertNotIn(valor, texto)
        self.assertIn('SEGREDO? a.py:1: atribuição de segredo', texto)
        self.assertIn('SEGREDO? a.py:2: Bearer com valor longo', texto)
        self.assertIn('liberado pelo marcador: a.py:3: access token do Mercado Livre (APP_USR-)', texto)

    def test_so_liberados_sai_com_0_e_mostra_para_revisar(self):
        out = io.StringIO()
        with redirect_stdout(out):
            saida = V.relatar_segredos([V.Achado('b.md', 3, 'atribuição de segredo', True)], 1, 'staged')
        self.assertEqual(saida, 0)
        self.assertIn('liberado pelo marcador: b.md:3: atribuição de segredo', out.getvalue())


class Nomes(unittest.TestCase):
    def test_proibidos(self):
        for caminho in ('api_token.txt', 'sub/api_token.txt', 'api_cabecalho.txt', 'ml_tokens.json',
                        'ml_tokens.json.lock', '.ml_tokens.json.ab12.tmp', 'ml_catalogo.json',
                        '.ml_catalogo.json.x.tmp', '.env', '.env.local', 'pasta/.env.producao',
                        'achadinhos.db', 'achadinhos.db-wal', 'x.db-shm', 'velho.db.bak', 'a.db.rodada-ml.lock',
                        'qualquer.lock', '_chat.txt', 'WhatsApp Chat - AmazonLinks/foto.jpg',
                        'WhatsApp Chat com alguém.txt', 'backups/auto-1.db', 'backups/nota.txt',
                        'logs/verificar-1/a.txt', 'tools/x/logs/a.txt', 'a/backups/b.sql',
                        # S2 (rodada 2): variações dos nomes do token da API v1 e banco .sqlite
                        'api_token', 'api_token.txt.bak', 'api_token_novo.txt', 'sub/api_cabecalho.bak',
                        'api_cabecalho', 'banco.sqlite', 'x.sqlite3', 'x.sqlite-wal', 'a/b.sqlite-journal',
                        # Q1 (rodada 2): cópias dos arquivos proibidos
                        'api_token.txt~', 'api_cabecalho.txt.bak', '_chat.txt.bak', 'sub/_chat.txt~',
                        'ml_catalogo.json.bak', 'ml_catalogo.json~', 'ml_tokens.json.old', '.env.bak',
                        '.env~'):
            with self.subTest(caminho=caminho):
                self.assertIsNotNone(V.nome_proibido(caminho))

    def test_liberados(self):
        for caminho in ('.env.example', 'pasta/.env.example', 'servidor.py', 'lista_whatsapp.json',
                        'docs/logs.md', 'backup_banco.py', 'testes/test_backup_banco.py', 'package-lock.json',
                        'api_ofertas.py', 'ml_api.py', '.gitignore', 'dbx.txt', 'logs.txt',
                        'testes/test_api_tokens.py', 'sqlite.md', 'chat.txt', 'ml_catalogo.py'):
            with self.subTest(caminho=caminho):
                self.assertIsNone(V.nome_proibido(caminho))


DIFF = (b'diff --git a/x.py b/x.py\nindex 1..2 100644\n--- a/x.py\n+++ b/x.py\n'
        b'@@ -2 +2 @@\n-velha\n+nova linha 2\n'
        b'@@ -9,0 +10,2 @@\n+++ conteudo que comeca com dois mais\n+linha 11\n'
        b'\\ No newline at end of file\n'
        b'@@ -20,3 +21,0 @@\n-a\n-b\n-c\n')


class LinhasAdicionadas(unittest.TestCase):
    def test_numeros_da_versao_nova(self):
        self.assertEqual(V.linhas_adicionadas(DIFF), [(2, 'nova linha 2'),
                                                       (10, '++ conteudo que comeca com dois mais'),
                                                       (11, 'linha 11')])

    def test_vazio(self):
        self.assertEqual(V.linhas_adicionadas(b''), [])


class Argumentos(unittest.TestCase):
    def test_uso_errado_sai_com_2(self):
        for args in (['--staged'], ['--tudo'], ['--segredos', '--staged', '--tudo'], ['--segredos', '--rapido'],
                     ['--pre-commit', '--rapido'], ['--pre-commit', '--segredos'], ['--segredos', '--servidor'],
                     ['--pre-commit', '--front'], ['--pre-commit', '--hora', '3']):
            with self.subTest(args=args):
                with mock.patch('sys.stderr', io.StringIO()), self.assertRaises(SystemExit) as c:
                    V.ler_argumentos(args)
                self.assertEqual(c.exception.code, 2)

    def test_segredos_sem_alvo_e_staged(self):
        args = V.ler_argumentos(['--segredos'])
        self.assertTrue(args.segredos)
        self.assertFalse(args.tudo)


def python_fixo():
    """Pasta de PATH com um `python3` que é este Python: o hook chama `python3` pelo PATH."""
    pasta = os.path.join(TMP, 'bin')
    if not os.path.isdir(pasta):
        os.mkdir(pasta)
        os.symlink(sys.executable, os.path.join(pasta, 'python3'))
    return pasta


def env_git(**extra):
    """Ambiente dos repositórios temporários: sem GIT_* herdado, sem a configuração global e de sistema
    (hooksPath, gpgsign, templates do usuário não valem) e com o `python3` deste teste."""
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1', GIT_TERMINAL_PROMPT='0',
               PATH=python_fixo() + os.pathsep + os.environ.get('PATH', ''), **extra)
    return env


class Repo:
    """Repositório git temporário com a cópia do verificar.py e do .githooks/pre-commit reais e uma suíte de
    mentira de um teste verde. Nunca toca o repositório real."""

    def __init__(self, hooks=True, verificar=None):
        self.dir = nova_pasta()
        self.env = env_git()
        self.git('init', '-q')
        self.git('config', 'user.name', 'Teste')
        self.git('config', 'user.email', 'teste@exemplo.invalid')
        self.git('config', 'commit.gpgsign', 'false')
        if hooks:
            self.git('config', 'core.hooksPath', '.githooks')
        os.mkdir(os.path.join(self.dir, '.githooks'))
        shutil.copy2(os.path.join(RAIZ, '.githooks', 'pre-commit'), os.path.join(self.dir, '.githooks'))
        if verificar is None:
            shutil.copy2(os.path.join(RAIZ, 'verificar.py'), self.dir)
        else:
            self.escrever('verificar.py', verificar)
        self.escrever_teste('test_verde.py', 'self.assertTrue(True)')
        self.git('add', 'verificar.py', '.githooks/pre-commit', 'testes/test_verde.py')
        self.git('commit', '-q', '--no-verify', '-m', 'base')

    def git(self, *args, check=True, env=None):
        p = subprocess.run(['git', *args], cwd=self.dir, env=env or self.env, capture_output=True, text=True,
                           timeout=180)
        if check and p.returncode != 0:
            raise AssertionError(f'git {args[0]} saiu com {p.returncode}: {p.stderr}')
        return p

    def escrever(self, rel, texto, modo='w'):
        caminho = os.path.join(self.dir, rel)
        os.makedirs(os.path.dirname(caminho), exist_ok=True)
        with open(caminho, modo, encoding=None if 'b' in modo else 'utf-8') as f:
            f.write(texto)

    def escrever_teste(self, nome, corpo):
        self.escrever(os.path.join('testes', nome),
                      'import unittest\nclass T(unittest.TestCase):\n    def test_um(self):\n'
                      f'        {corpo}\nif __name__ == "__main__":\n    unittest.main()\n')

    def commit(self, *arquivos, env=None):
        """(saída do git commit, texto de stdout+stderr) depois de `git add` dos arquivos."""
        if arquivos:
            self.git('add', '--', *arquivos)
        p = self.git('commit', '-m', 'teste', check=False, env=env)
        return p.returncode, p.stdout + p.stderr

    def commits(self):
        return int(self.git('rev-list', '--count', 'HEAD').stdout)

    def verificar(self, *args):
        p = subprocess.run([sys.executable, 'verificar.py', *args], cwd=self.dir, env=self.env,
                           capture_output=True, text=True, timeout=180)
        return p.returncode, p.stdout + p.stderr


class PortaoDeCommit(unittest.TestCase):
    """CA7 ponta a ponta: `git commit` de verdade num repositório temporário, com o hook real."""

    def test_api_token_txt_bloqueia(self):
        r = Repo()
        r.escrever('api_token.txt', 'qualquer coisa\n')
        saida, texto = r.commit('api_token.txt')
        self.assertNotEqual(saida, 0, texto)
        self.assertIn('SEGREDO? api_token.txt: nome proibido (api_token*)', texto)
        self.assertIn('commit bloqueado pelo portão (segredos)', texto)
        self.assertNotIn('qualquer coisa', texto)
        self.assertEqual(r.commits(), 1)

    def test_secret_falso_bloqueia_sem_mostrar_o_valor(self):
        r = Repo()
        r.escrever('config.py', 'x = 1\nsecret = "' + FALSO32 + '"\n')
        saida, texto = r.commit('config.py')
        self.assertNotEqual(saida, 0, texto)
        self.assertIn('SEGREDO? config.py:2: atribuição de segredo', texto)
        self.assertNotIn(FALSO32, texto)
        self.assertNotIn(FALSO32[:12], texto)
        self.assertNotIn('secret =', texto)
        self.assertNotIn('rodando a suíte', texto)   # bloqueia antes dos testes
        self.assertEqual(r.commits(), 1)

    def test_numero_da_linha_e_da_versao_nova_e_commit_a_tambem_e_varrido(self):
        """`git commit -a` usa outro índice (GIT_INDEX_FILE): o portão varre o que vai no commit."""
        r = Repo()
        r.escrever('notas.txt', ''.join(f'linha {n}\n' for n in range(1, 9)))
        self.assertEqual(r.commit('notas.txt')[0], 0)
        r.escrever('notas.txt', ''.join(f'linha {n}\n' for n in range(1, 9)).replace(
            'linha 6\n', 'linha 6\nAuthorization: Bearer ' + FALSO_BEARER + '\n'))
        p = r.git('commit', '-a', '-m', 'teste', check=False)
        texto = p.stdout + p.stderr
        self.assertNotEqual(p.returncode, 0, texto)
        self.assertIn('SEGREDO? notas.txt:7: Bearer com valor longo', texto)
        self.assertNotIn(FALSO_BEARER, texto)

    def test_marcador_libera_o_commit_e_aparece_no_resumo(self):
        r = Repo()
        r.escrever('notas.txt', 'token = "' + FALSO32 + '"  ' + V.MARCADOR + '\n')
        saida, texto = r.commit('notas.txt')
        self.assertEqual(saida, 0, texto)
        self.assertIn('liberado pelo marcador: notas.txt:1: atribuição de segredo', texto)
        self.assertNotIn(FALSO32, texto)
        self.assertEqual(r.commits(), 2)

    def test_env_example_passa_e_env_nao(self):
        r = Repo()
        r.escrever('.env.example', 'ACHADINHOS_SHOPEE_SECRET=\nACHADINHOS_SHOPEE_APP_ID=\n')
        saida, texto = r.commit('.env.example')
        self.assertEqual(saida, 0, texto)
        r.escrever('.env', 'secret = "' + FALSO32 + '"\n')
        saida, texto = r.commit('.env')
        self.assertNotEqual(saida, 0, texto)
        self.assertIn('SEGREDO? .env: nome proibido (.env*)', texto)
        self.assertNotIn('.env:1', texto)   # o conteúdo de arquivo de nome proibido nem é lido

    def test_commit_so_de_md_nao_roda_testes(self):
        r = Repo()
        r.escrever_teste('test_vermelho.py', 'self.assertEqual(1, 2)')
        r.git('add', 'testes/test_vermelho.py')
        r.git('commit', '-q', '--no-verify', '-m', 'suíte vermelha')
        r.escrever('LEIAME.md', '# nada de código\n')
        saida, texto = r.commit('LEIAME.md')
        self.assertEqual(saida, 0, texto)   # a suíte está vermelha: se rodasse, bloquearia
        self.assertIn('os testes não rodam', texto)
        self.assertFalse(os.path.exists(os.path.join(r.dir, 'logs')))
        self.assertEqual(r.commits(), 3)

    def test_teste_nao_rastreado_vermelho_nao_bloqueia(self):
        r = Repo()
        r.escrever_teste('test_vermelho.py', 'self.assertEqual(1, 2)')   # de outra frente, fora do índice
        r.escrever('codigo.py', 'x = 1\n')
        saida, texto = r.commit('codigo.py')
        self.assertEqual(saida, 0, texto)
        self.assertIn('rodando a suíte --rapido', texto)
        self.assertRegex(texto, r'test_vermelho\s+fora do commit \(não rastreado\)')
        self.assertRegex(texto, r'test_verde\s+saida=0')
        # O mesmo teste vermelho staged entra na suíte e bloqueia: os testes rodam de verdade.
        saida, texto = r.commit('testes/test_vermelho.py')
        self.assertNotEqual(saida, 0, texto)
        self.assertRegex(texto, r'test_vermelho\s+saida=1')
        self.assertIn('commit bloqueado pelo portão (testes)', texto)
        self.assertEqual(r.commits(), 2)

    def test_aviso_do_core_hookspath(self):
        sem = Repo(hooks=False)
        saida, texto = sem.verificar('--segredos')
        self.assertEqual(saida, 0, texto)
        self.assertIn('aviso: portão de commit desligado: core.hooksPath não aponta para .githooks', texto)
        self.assertIn('core.hooksPath', sem.verificar('--pre-commit')[1])
        sem.git('config', 'core.hooksPath', 'outra')
        self.assertIn('core.hooksPath', sem.verificar('--segredos')[1])
        com = Repo()
        saida, texto = com.verificar('--segredos')
        self.assertEqual(saida, 0, texto)
        self.assertNotIn('core.hooksPath', texto)
        com.git('config', 'core.hooksPath', os.path.join(com.dir, '.githooks'))   # caminho absoluto vale
        self.assertNotIn('core.hooksPath', com.verificar('--segredos')[1])

    def test_aviso_na_suite_normal(self):
        """A suíte (verificar.py sem opção) também avisa, junto com os outros avisos."""
        r = Repo(hooks=False)
        with mock.patch.object(V, 'RAIZ', r.dir):
            self.assertIn('core.hooksPath', V.aviso_portao())
            r.git('config', 'core.hooksPath', '.githooks')
            self.assertIsNone(V.aviso_portao())
        with mock.patch.object(V, 'RAIZ', nova_pasta()):   # fora de repositório git: sem aviso
            self.assertIsNone(V.aviso_portao())

    def test_pre_commit_sem_nada_staged_sai_com_0(self):
        r = Repo()
        r.escrever_teste('test_vermelho.py', 'self.assertEqual(1, 2)')
        saida, texto = r.verificar('--pre-commit')
        self.assertEqual(saida, 0, texto)
        self.assertIn('pre-commit: nada staged', texto)
        self.assertFalse(os.path.exists(os.path.join(r.dir, 'logs')))

    def test_apagar_arquivo_proibido_nao_bloqueia(self):
        r = Repo()
        r.escrever('velho.lock', 'x\n')
        r.git('add', 'velho.lock')
        r.git('commit', '-q', '--no-verify', '-m', 'entrou por engano')
        r.git('rm', '-q', '--cached', 'velho.lock')
        saida, texto = r.commit()
        self.assertEqual(saida, 0, texto)

    def test_fora_de_repositorio_git_sai_com_1_sem_a_saida_do_git(self):
        pasta = nova_pasta()
        shutil.copy2(os.path.join(RAIZ, 'verificar.py'), pasta)
        p = subprocess.run([sys.executable, 'verificar.py', '--segredos'], cwd=pasta, env=env_git(),
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn('a raiz é um repositório git?', p.stderr)
        self.assertNotIn('fatal', p.stderr)


class Hook(unittest.TestCase):
    def test_hook_e_executavel_e_chama_o_verificar(self):
        caminho = os.path.join(RAIZ, '.githooks', 'pre-commit')
        self.assertTrue(os.access(caminho, os.X_OK))
        with open(caminho, encoding='utf-8') as f:
            linhas = [l.strip() for l in f if l.strip() and not l.lstrip().startswith('#')]
        self.assertEqual(linhas, ['exec python3 verificar.py --pre-commit'])

    def test_o_git_roda_o_hook_que_roda_o_verificar(self):
        """verificar.py falso no repositório temporário: registra argv e cwd e sai com o código pedido."""
        falso = textwrap.dedent('''\
            import json, os, sys
            with open(os.environ['REGISTRO_FALSO'], 'w') as f:
                json.dump({'argv': sys.argv[1:], 'cwd': os.getcwd()}, f)
            sys.exit(int(os.environ['SAIDA_FALSA']))
        ''')
        r = Repo(verificar=falso)
        registro = os.path.join(nova_pasta(), 'registro.json')
        r.escrever('a.txt', 'a\n')
        saida, texto = r.commit('a.txt', env=env_git(REGISTRO_FALSO=registro, SAIDA_FALSA='1'))
        self.assertNotEqual(saida, 0, texto)
        import json
        with open(registro) as f:
            chamada = json.load(f)
        self.assertEqual(chamada['argv'], ['--pre-commit'])
        self.assertEqual(os.path.realpath(chamada['cwd']), os.path.realpath(r.dir))
        self.assertEqual(r.commits(), 1)
        saida, texto = r.commit(env=env_git(REGISTRO_FALSO=registro, SAIDA_FALSA='0'))
        self.assertEqual(saida, 0, texto)
        self.assertEqual(r.commits(), 2)


class Tudo(unittest.TestCase):
    """--segredos --tudo: rastreados e não rastreados fora do .gitignore, como estão no disco."""

    def test_varre_disco_respeita_gitignore_e_nao_le_nome_proibido(self):
        r = Repo(hooks=False)
        r.escrever('.gitignore', 'ignorado.txt\n')
        r.escrever('ignorado.txt', 'secret = "' + FALSO32 + '"\n')        # ignorado: nem é listado
        r.escrever('rastreado.py', 'x = 1\n')
        r.git('add', '.gitignore', 'rastreado.py')
        r.git('commit', '-q', '--no-verify', '-m', 'mais')
        r.escrever('rastreado.py', 'x = 1\npassword = ' + FALSO32 + '\n')  # mudança no disco, não staged
        r.escrever('novo.md', 'Bearer ' + FALSO_BEARER + '\n')              # não rastreado
        r.escrever('binario.bin', b'\0\0secret = "' + FALSO32.encode() + b'"\n', modo='wb')
        r.escrever('.env', 'secret = "' + FALSO32 + '"\n')                  # nome proibido: só o nome
        saida, texto = r.verificar('--segredos', '--tudo')
        self.assertEqual(saida, 1, texto)
        self.assertIn('SEGREDO? rastreado.py:2: atribuição de segredo', texto)
        self.assertIn('SEGREDO? novo.md:1: Bearer com valor longo', texto)
        self.assertIn('SEGREDO? .env: nome proibido (.env*)', texto)
        self.assertNotIn('.env:1', texto)
        self.assertNotIn('ignorado.txt', texto)
        self.assertNotIn('binario.bin', texto)
        self.assertNotIn(FALSO32, texto)
        self.assertEqual(r.verificar('--segredos', '--staged')[0], 0)   # nada disso está staged

    def test_repositorio_real_calibrado(self):
        """CA7 / calibragem: o repositório real (rastreados e não rastreados fora do .gitignore) sai limpo."""
        out = io.StringIO()
        with redirect_stdout(out):
            saida = V.varrer_segredos('tudo')
        self.assertEqual(saida, 0, out.getvalue())


def vivo(pid):
    """True se o processo existe e não é zumbi (o zumbi espera o init recolher, mas já morreu)."""
    try:
        with open(f'/proc/{pid}/stat') as f:
            return f.read().rsplit(')', 1)[1].split()[0] != 'Z'
    except FileNotFoundError:
        return False


if __name__ == '__main__':
    unittest.main()
