#!/usr/bin/env python3
"""Testes de QA do ml_api.py (docs/produto/planos/api-oficial-ml.md, etapas 1 a 3: CA2 a CA6, CA9 e CA10).

Uso:  http_proxy=http://127.0.0.1:9 https_proxy=http://127.0.0.1:9 python3 testes/test_ml_api_qa.py -v

Complementam o test_ml_api.py do dev (reaproveitam os helpers dele, sem repetir os casos). Foco:
  - inventário de toda requisição de um ciclo completo (autorizar → conferir com renovação → sondar com 401):
    host fixo, POST só no /oauth/token, Secret só no corpo do POST, Bearer só no header do GET;
  - nada sensível em arquivo (token, trava, sobras) nem em argv (/proc/<pid>/cmdline) durante o autorizar;
  - sobra da escrita atômica depois de um SIGKILL no meio da gravação (fica fora do .gitignore?);
  - concorrência entre 3 processos e entre 2 processos que tomam 401 ao mesmo tempo;
  - a trava é solta em toda falha dentro dela; o par novo fica gravado mesmo se o GET seguinte falhar;
  - o OPENER do módulo de verdade (socket local): nenhum código de redirect é seguido e o teto de 2 MB
    vale para resposta em chunks e para corpo de erro;
  - o servidor.py não serve arquivo do projeto e a config do banco real não tem chave do ML (mode=ro);
  - o README (CA10) e a tabela de saídas batem com as exceções do módulo.

Nenhum teste fala com o Mercado Livre: openers falsos, servidor local em 127.0.0.1 e proxy morto para o resto.
Nunca cria ml_tokens.json no projeto: tudo em pasta temporária.
"""
import hashlib
import http.server
import json
import os
import re
import signal
import socket
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_ml_api as T   # noqa: E402  (fixa proxies, ACHADINHOS_ML_TOKENS e ACHADINHOS_DB temporários)

M = T.M
RAIZ = T.RAIZ
SECRET, ACCESS, REFRESH, CODE, USER = T.SECRET, T.ACCESS, T.REFRESH, T.CODE, T.USER
erro_http, novo, resposta_token = T.erro_http, T.novo, T.resposta_token


def tearDownModule():
    T.tearDownModule()


def lock_livre(caminho):
    """True se ninguém segura o flock de <caminho>.lock."""
    import fcntl
    with open(caminho + '.lock', 'a') as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        fcntl.flock(f, fcntl.LOCK_UN)
        return True


def conteudo_da_pasta(pasta):
    """{nome: bytes} de todo arquivo comum da pasta (inclusive ocultos)."""
    saida = {}
    for nome in os.listdir(pasta):
        p = os.path.join(pasta, nome)
        if os.path.isfile(p) and not os.path.islink(p):
            with open(p, 'rb') as f:
                saida[nome] = f.read()
    return saida


def entrada_do_autorizar(guardar, code=CODE, cauda=''):
    """input() falso: lê o state da URL impressa e devolve o endereço da página de retorno."""
    def entrada(out):
        url = re.search(r'https://auth\.mercadolivre\.com\.br/authorization\?\S+', out.getvalue()).group(0)
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        guardar.update(q)
        return f'https://desejodemenina.com/ml/callback/?code={code}&state={q["state"]}{cauda}'
    return entrada


# ---------- CA2/CA5: inventário de um ciclo completo ----------
class TestInventarioDoCiclo(T.Cli):
    def test_ciclo_completo_so_fala_com_o_host_fixo_e_o_secret_so_vai_no_post(self):
        """autorizar → conferir (renova) → sondar (401 no 1º GET, renova de novo): toda requisição é conferida."""
        estado = {'n': 0, 'validos': set()}
        chamadas = []

        def responder(c):
            chamadas.append(c)
            if c.metodo == 'POST':
                estado['n'] += 1
                r = resposta_token(estado['n'])
                estado['validos'] = {r['access_token']}
                return r
            if c.auth and c.auth[len('Bearer '):] in estado['validos']:
                if c.caminho == '/users/me' and estado.get('derrubar_uma_vez'):
                    estado['derrubar_uma_vez'] = False
                    estado['validos'] = set()          # o ML derrubou o token: 401 e uma renovação
                    return erro_http(401, {'error': 'invalid_token'})
                return {'id': USER}
            return erro_http(401, {'error': 'invalid_token'})

        q = {}
        codigo, out1, err1 = self.rodar(['autorizar'], T.OpenerFalso(responder), secret=SECRET,
                                        entrada=entrada_do_autorizar(q))
        self.assertEqual(codigo, 0, err1)
        # força a renovação no conferir: o arquivo passa a vencer em 10 s (relógio de verdade)
        d = self.lido()
        M.gravar_tokens(self.caminho, M.Tokens(d['user_id'], d['access_token'], int(time.time()) + 10,
                                               d['refresh_token'], d['scope'], d['renovado_em']))
        codigo, out2, err2 = self.rodar(['conferir'], T.OpenerFalso(responder), secret=SECRET)
        self.assertEqual(codigo, 0, err2)
        estado['derrubar_uma_vez'] = True
        codigo, out3, err3 = self.rodar(['sondar'], T.OpenerFalso(responder), secret=SECRET)
        self.assertEqual(codigo, 0, err3)

        self.assertEqual(estado['n'], 3)   # troca do code + renovação por vencimento + renovação pelo 401
        posts = [c for c in chamadas if c.metodo == 'POST']
        gets = [c for c in chamadas if c.metodo == 'GET']
        self.assertEqual(len(posts) + len(gets), len(chamadas))   # nenhum outro método
        verifier = posts[0].campos['code_verifier']
        for c in chamadas:
            self.assertEqual((c.url.split('/')[0], c.host), ('https:', 'api.mercadolibre.com'), c.url)
            for segredo in (SECRET, CODE, verifier, REFRESH, ACCESS, *novo(1), *novo(2), *novo(3)):
                self.assertNotIn(segredo, c.url)
        for c in posts:
            self.assertEqual(c.caminho, '/oauth/token')
            self.assertEqual(c.query, {})
            self.assertIsNone(c.auth)                       # Bearer nunca vai no pedido de token
            self.assertEqual(c.campos['client_secret'], SECRET)
        for c in gets:
            self.assertIsNone(c.corpo)
            self.assertTrue(c.auth.startswith('Bearer '))
            self.assertNotIn(SECRET, json.dumps(c.headers))
        self.assertEqual([p.campos['grant_type'] for p in posts], ['authorization_code', 'refresh_token',
                                                                  'refresh_token'])
        # cada renovação gastou o refresh mais novo (uso único), nunca um antigo
        self.assertEqual([p.campos.get('refresh_token') for p in posts[1:]], [novo(1)[1], novo(2)[1]])
        # nada sensível na tela, em nenhum dos três comandos
        tudo = out1 + err1 + out2 + err2 + out3 + err3
        T.sem_marcadores(self, tudo)
        for segredo in (verifier, *novo(2), *novo(3)):
            self.assertNotIn(segredo, tudo)
        # o arquivo final tem o par da 3ª troca e nenhum segredo que não seja dele
        d = self.lido()
        self.assertEqual((d['access_token'], d['refresh_token']), novo(3))
        bruto = json.dumps(conteudo_da_pasta(self.dir), default=lambda b: b.decode('latin-1'))
        for segredo in (SECRET, CODE, verifier, q['state'], q['code_challenge']):
            self.assertNotIn(segredo, bruto)


# ---------- CA2: o autorizar em casos de borda ----------
class TestAutorizarBorda(T.Cli):
    def test_ctrl_c_no_prompt_sai_130_sem_trocar_nem_gravar(self):
        def interromper(out):
            raise KeyboardInterrupt()
        op = T.OpenerFalso(T.api_padrao())
        codigo, out, err = self.rodar(['autorizar'], op, secret=SECRET, entrada=interromper)
        self.assertEqual(codigo, 130)
        self.assertEqual(op.chamadas, [])
        self.assertEqual(os.listdir(self.dir), [])
        self.assertFalse(self.secret_ficou)

    def test_autorizar_que_falha_nao_mexe_no_arquivo_que_ja_existia(self):
        self.gravar_real()
        os.chmod(self.caminho, 0o400)
        antes = (self.lido(), os.stat(self.caminho).st_ino)
        casos = [  # (entrada, resposta do POST, saída esperada)
            (entrada_do_autorizar({}, cauda='&error=access_denied'), None, 1),
            (lambda out: 'https://desejodemenina.com/ml/callback/?code=X&state=outro', None, 1),
            (entrada_do_autorizar({}), erro_http(400, {'error': 'invalid_grant'}), 2),
            (entrada_do_autorizar({}), resposta_token(1, refresh_token=None), 1),   # app sem offline_access
            (entrada_do_autorizar({}), erro_http(500, {'error': 'internal_error'}), 1),
        ]
        for entrada, resposta, saida in casos:
            op = T.OpenerFalso(T.api_padrao(token=lambda c, r=resposta: r))
            codigo, out, err = self.rodar(['autorizar'], op, secret=SECRET, entrada=entrada)
            self.assertEqual(codigo, saida, err)
            self.assertEqual((self.lido(), os.stat(self.caminho).st_ino), antes)
            self.assertEqual(stat.S_IMODE(os.stat(self.caminho).st_mode), 0o400)
            T.sem_marcadores(self, out, err)
            self.assertNotIn('Traceback', err)
            self.assertLessEqual(set(os.listdir(self.dir)), {'ml_tokens.json', 'ml_tokens.json.lock'})   # sem sobra

    def test_endereco_recusado_nunca_e_ecoado(self):
        """Code fora do formato, host parecido e query estranha: a mensagem não repete nada do que foi colado."""
        marcas = ('MARCA-COLADA-7f3', 'evil-desejodemenina')
        entradas = [
            entrada_do_autorizar({}, code=f'{CODE}!{marcas[0]}'),
            lambda out: f'https://{marcas[1]}.com/ml/callback/?code={CODE}&state={marcas[0]}',
            lambda out: f'https://desejodemenina.com/ml/callback/{marcas[0]}?code={CODE}&state=x',
            lambda out: f'https://desejodemenina.com/ml/callback/?code={CODE}&state=x&{marcas[0]}',
            lambda out: f'https://desejodemenina.com/ml/callback/?code={CODE}&state=x#{marcas[0]}',
            lambda out: f'https://{marcas[0]}@desejodemenina.com/ml/callback/?code={CODE}&state=x',
            lambda out: f'https://desejodemenina.com:443/ml/callback/?code={CODE}&state=x',
            lambda out: f'https://desejodemenina.com/ml/callback/?code={CODE}&state=x\x1b]0;{marcas[0]}\x07',
        ]
        for entrada in entradas:
            op = T.OpenerFalso(T.api_padrao())
            codigo, out, err = self.rodar(['autorizar'], op, secret=SECRET, entrada=entrada)
            self.assertEqual(codigo, 1, err)
            self.assertEqual(op.chamadas, [])
            for m in marcas:
                self.assertNotIn(m, out + err)
            T.sem_marcadores(self, out, err)
            self.assertFalse(os.path.exists(self.caminho))

    def test_state_e_verifier_novos_a_cada_execucao(self):
        vistos = []
        for _ in range(3):
            q = {}
            op = T.OpenerFalso(T.api_padrao())
            codigo, out, err = self.rodar(['autorizar'], op, secret=SECRET, entrada=entrada_do_autorizar(q))
            self.assertEqual(codigo, 0, err)
            vistos.append((q['state'], q['code_challenge'], op.posts()[0].campos['code_verifier']))
        for i in range(3):
            self.assertEqual(len({v[i] for v in vistos}), 3)

    def test_code_de_outra_execucao_e_recusado_pelo_state(self):
        """Colar o endereço de uma tentativa anterior (state velho) não troca o code."""
        q1 = {}
        codigo, out, err = self.rodar(['autorizar'], T.OpenerFalso(T.api_padrao()), secret=SECRET,
                                      entrada=entrada_do_autorizar(q1))
        self.assertEqual(codigo, 0, err)
        os.unlink(self.caminho)
        op = T.OpenerFalso(T.api_padrao())
        codigo, out, err = self.rodar(
            ['autorizar'], op, secret=SECRET,
            entrada=lambda out: f'https://desejodemenina.com/ml/callback/?code={CODE}&state={q1["state"]}')
        self.assertEqual(codigo, 1)
        self.assertIn('state diferente', err)
        self.assertEqual(op.chamadas, [])
        self.assertFalse(os.path.exists(self.caminho))


# ---------- CA3: arquivo de tokens ----------
GRAVAR_E_MORRER = r'''
import os, signal, sys
sys.path.insert(0, os.environ['RAIZ_ML'])
import ml_api as M
real = os.replace
def morrer(*a, **k):
    os.kill(os.getpid(), signal.SIGKILL)   # queda de energia, kill -9 ou terminal fechado no meio da gravação
M.os.replace = morrer
M.gravar_tokens(os.environ['ACHADINHOS_ML_TOKENS'],
                M.Tokens(123456789, 'APP_USR-ACESSO-MARCADOR-0001-aaaaaaaaaaaa', 1800000000,
                         'TG-RENOVA-MARCADOR-0001-bbbbbbbbbbbbbb', 'offline_access read', '2026-11-05T10:00:00'))
'''


class TestArquivoTokensQa(T.Base):
    def test_sobra_de_gravacao_interrompida_fica_no_gitignore(self):
        """SIGKILL entre o O_EXCL e o os.replace: a sobra com os tokens tem de ficar fora do git, como o arquivo.

        O padrão é ml_tokens.json na raiz do projeto, então a sobra (.ml_tokens.json.<hex>.tmp) nasce lá.
        """
        if not os.path.exists(os.path.join(RAIZ, '.git')):
            self.skipTest('cópia fora do repositório')
        script = os.path.join(tempfile.mkdtemp(dir=T.TMP), 'gravar_e_morrer.py')   # fora da pasta dos tokens
        with open(script, 'w') as f:
            f.write(GRAVAR_E_MORRER)
        env = {k: v for k, v in os.environ.items() if not k.startswith('ACHADINHOS_')}
        env.update(RAIZ_ML=RAIZ, ACHADINHOS_ML_TOKENS=self.caminho, ACHADINHOS_DB=os.path.join(self.dir, 'x.db'),
                   PYTHONDONTWRITEBYTECODE='1')
        r = subprocess.run([sys.executable, script], env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, -signal.SIGKILL, r.stderr)
        sobras = [n for n, b in conteudo_da_pasta(self.dir).items() if ACCESS.encode() in b]
        self.assertEqual(len(sobras), 1, sobras)
        sobra = sobras[0]
        self.assertRegex(sobra, r'\A\.ml_tokens\.json\.[0-9a-f]{16}\.tmp\Z')
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.dir, sobra)).st_mode), 0o600)
        # o mesmo nome na raiz do projeto (onde fica o padrão) tem de ser ignorado pelo git
        r = subprocess.run(['git', '-C', RAIZ, 'check-ignore', '--no-index', sobra], capture_output=True, text=True,
                           timeout=30)
        self.assertEqual(r.returncode, 0, f'{sobra} (com os tokens) não está no .gitignore: git add -A o levaria')

    def test_trava_e_solta_em_toda_falha_dentro_dela(self):
        falhas = [
            ('invalid_grant', lambda c: erro_http(400, {'error': 'invalid_grant'}), M.RefazerAutorizacao),
            ('invalid_client', lambda c: erro_http(401, {'error': 'invalid_client'}), M.CredencialInvalida),
            ('rede', lambda c: urllib.error.URLError('x'), M.ErroRede),
            ('429', lambda c: erro_http(429, {}), M.Limite),
            ('500', lambda c: erro_http(500, {}), M.ErroApi),
            ('resposta ruim', lambda c: resposta_token(1, user_id=USER + 1), M.RespostaInvalida),
            ('inesperado', lambda c: RuntimeError('x'), RuntimeError),
        ]
        for nome, token, excecao in falhas:
            self.gravar(expira_em=T.AGORA - 1)
            antes = self.lido()
            op = T.OpenerFalso(T.api_padrao(token=token))
            with self.assertRaises(excecao, msg=nome):
                self.sessao(op).get('/users/me')
            self.assertTrue(lock_livre(self.caminho), nome)
            self.assertEqual(self.lido(), antes, nome)
            self.assertEqual(op.gets(), [], nome)
        self.gravar(expira_em=T.AGORA - 1)
        with self.assertRaises(M.ConfigFaltando):
            self.sessao(T.OpenerFalso(T.api_padrao()), segredo=None).renovar()
        self.assertTrue(lock_livre(self.caminho))

    def test_par_novo_fica_gravado_mesmo_se_o_get_seguinte_falhar(self):
        """CA4: o refresh novo é de uso único; se o GET depois da renovação falhar, ele não pode se perder."""
        for falha, excecao in ((urllib.error.URLError('x'), M.ErroRede), (erro_http(500, {}), M.ErroApi),
                               (erro_http(429, {}), M.Limite), (T.Resp(b'nao json'), M.RespostaInvalida),
                               (erro_http(403, {'blocked_by': 'PolicyAgent'}), M.SemPermissao)):
            self.gravar(expira_em=T.AGORA + 10)
            op = T.OpenerFalso(T.api_padrao(gets=lambda c, f=falha: f))
            with self.assertRaises(excecao):
                self.sessao(op).get('/users/me')
            self.assertEqual(len(op.posts()), 1)
            d = self.lido()
            self.assertEqual((d['access_token'], d['refresh_token']), novo(1))
            self.assertEqual(stat.S_IMODE(os.stat(self.caminho).st_mode), 0o600)

    def test_429_no_pedido_de_token_sai_3_e_nao_mexe_no_arquivo(self):
        self.gravar(expira_em=T.AGORA - 1)
        antes = self.lido()
        op = T.OpenerFalso(T.api_padrao(token=lambda c: erro_http(429, {'message': 'too many'})))
        with self.assertRaises(M.Limite) as cm:
            self.sessao(op).get('/users/me')
        self.assertEqual(cm.exception.saida, 3)
        self.assertEqual(len(op.posts()), 3)
        self.assertEqual(self.lido(), antes)

    def test_leitura_recusa_pasta_do_arquivo_trocada_por_link_para_arquivo_de_outro(self):
        """O arquivo apontado por um symlink no lugar do ml_tokens.json nunca é lido, nem se for 0600 e válido."""
        outro = os.path.join(self.dir, 'outro.json')
        M.gravar_tokens(outro, T.tokens(access=novo(5)[0]))
        os.symlink(outro, self.caminho)
        with self.assertRaises(M.TokensRecusados):
            self.sessao(T.OpenerFalso(T.api_padrao())).get('/users/me')

    def test_hardlink_de_arquivo_aberto_continua_recusado(self):
        alvo = os.path.join(self.dir, 'alvo.json')
        M.gravar_tokens(alvo, T.tokens())
        os.link(alvo, self.caminho)
        os.chmod(alvo, 0o640)   # o modo é do inode: vale para os dois nomes
        with self.assertRaises(M.TokensRecusados):
            M.ler_tokens(self.caminho)


class TestCliArquivoQa(T.Cli):
    def test_tokens_e_trava_sem_secret_code_nem_verifier_depois_do_autorizar_e_da_renovacao(self):
        q = {}
        op = T.OpenerFalso(T.api_padrao())
        codigo, out, err = self.rodar(['autorizar'], op, secret=SECRET, entrada=entrada_do_autorizar(q))
        self.assertEqual(codigo, 0, err)
        verifier = op.posts()[0].campos['code_verifier']
        self.assertEqual(sorted(os.listdir(self.dir)), ['ml_tokens.json', 'ml_tokens.json.lock'])
        self.assertEqual(stat.S_IMODE(os.stat(self.caminho + '.lock').st_mode), 0o600)
        self.assertEqual(os.path.getsize(self.caminho + '.lock'), 0)
        for nome, bruto in conteudo_da_pasta(self.dir).items():
            for segredo in (SECRET, CODE, verifier, q['state']):
                self.assertNotIn(segredo.encode(), bruto, nome)
        self.assertEqual(set(self.lido()), M.CHAVES_TOKENS)

    def test_conferir_com_401_e_invalid_grant_na_renovacao_sai_2(self):
        self.gravar_real()
        op = T.OpenerFalso(T.api_padrao(gets=lambda c: erro_http(401, {'error': 'invalid_token'}),
                                        token=lambda c: erro_http(400, {'error': 'invalid_grant'})))
        codigo, out, err = self.rodar(['conferir'], op, secret=SECRET)
        self.assertEqual(codigo, 2)
        self.assertIn('rode `ml_api.py autorizar`', err)
        self.assertEqual((len(op.gets()), len(op.posts())), (1, 1))
        T.sem_marcadores(self, out, err)

    def test_conferir_com_401_sem_secret_mostra_a_receita(self):
        self.gravar_real()
        op = T.OpenerFalso(T.api_padrao(gets=lambda c: erro_http(401, {'error': 'invalid_token'})))
        codigo, out, err = self.rodar(['conferir'], op)
        self.assertEqual(codigo, 2)
        self.assertIn('ACHADINHOS_ML_SECRET="$S" python3 ml_api.py conferir; unset S', err)
        self.assertEqual(op.posts(), [])


# ---------- CA4: processos de verdade ----------
class TestConcorrenciaQa(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(dir=T.TMP)
        self.caminho = os.path.join(self.dir, 'ml_tokens.json')
        self.estado = os.path.join(self.dir, 'estado.json')
        self.auxiliar = os.path.join(self.dir, 'auxiliar.py')
        with open(self.auxiliar, 'w') as f:
            f.write(T.AUXILIAR)

    def iniciar(self, acessos):
        with open(self.estado, 'w') as f:
            json.dump({'refresh_valido': REFRESH, 'acessos': acessos, 'n': 0, 'posts': [], 'eventos': [],
                       'code': CODE}, f)

    def env(self, **extra):
        env = {k: v for k, v in os.environ.items() if not k.startswith('ACHADINHOS_')}
        env.update(RAIZ_ML=RAIZ, ESTADO_FALSO=self.estado, ACHADINHOS_ML_TOKENS=self.caminho,
                   ACHADINHOS_DB=os.path.join(self.dir, 'sem.db'), PYTHONDONTWRITEBYTECODE='1')
        env.update(extra)
        return env

    def rodar_juntos(self, n, **extra):
        env = self.env(ACHADINHOS_ML_SECRET=SECRET, **extra)
        procs = [subprocess.Popen([sys.executable, self.auxiliar, 'conferir'], env=env, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True) for _ in range(n)]
        saidas = [p.communicate(timeout=60) for p in procs]
        for p, (out, err) in zip(procs, saidas):
            self.assertEqual(p.returncode, 0, err)
            self.assertIn('OK. Escopos: offline_access read', out)
            T.sem_marcadores(self, out, err)
        with open(self.estado) as f:
            return json.load(f)

    def test_tres_processos_com_token_vencido_gastam_o_refresh_uma_vez(self):
        self.iniciar([ACCESS])
        M.gravar_tokens(self.caminho, T.tokens(expira_em=int(time.time()) + 10))
        e = self.rodar_juntos(3, ATRASO_FALSO='0.8')
        self.assertEqual((len(e['posts']), e['n']), (1, 1))
        pedidos = [nome for nome, pid, t in e['eventos'] if nome == 'pediu-trava']
        self.assertEqual(len(pedidos), 3)   # os três chegaram à trava (leram o arquivo vencido)
        with open(self.caminho) as f:
            self.assertEqual(json.load(f)['refresh_token'], novo(1)[1])

    def test_dois_processos_com_401_ao_mesmo_tempo_renovam_uma_vez(self):
        """O token do arquivo ainda vale pelo relógio, mas o ML já o derrubou: os dois tomam 401 juntos."""
        self.iniciar([])   # o access do arquivo não vale mais do lado do "ML"
        M.gravar_tokens(self.caminho, T.tokens(expira_em=int(time.time()) + 3600))
        e = self.rodar_juntos(2, ATRASO_FALSO='0.8')
        self.assertEqual((len(e['posts']), e['n']), (1, 1))
        self.assertEqual(e['posts'][0]['grant_type'], 'refresh_token')
        with open(self.caminho) as f:
            self.assertEqual(json.load(f)['access_token'], novo(1)[0])

    def test_argv_do_autorizar_esperando_o_endereco_nao_tem_segredo(self):
        """/proc/<pid>/cmdline enquanto o autorizar espera no input(): nada além do script e do subcomando."""
        if not os.path.exists('/proc/self/cmdline'):
            self.skipTest('sem /proc')
        self.iniciar([ACCESS])
        p = subprocess.Popen([sys.executable, self.auxiliar, 'autorizar'], env=self.env(ACHADINHOS_ML_SECRET=SECRET),
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            url = None
            while url is None:
                linha = p.stdout.readline()
                self.assertTrue(linha, 'o autorizar terminou sem imprimir a URL')
                m = re.match(r'https://auth\.mercadolivre\.com\.br/authorization\?\S+$', linha.strip())
                url = m and m.group(0)
            with open(f'/proc/{p.pid}/cmdline', 'rb') as f:
                argv = f.read().split(b'\0')
            state = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))['state']
            out, err = p.communicate(f'https://desejodemenina.com/ml/callback?code={CODE}&state={state}\n', timeout=30)
        finally:
            if p.poll() is None:
                p.kill()
                p.wait()
        self.assertEqual(p.returncode, 0, err)
        self.assertEqual([a for a in argv if a], [sys.executable.encode(), self.auxiliar.encode(), b'autorizar'])
        with open(self.estado) as f:
            verifier = json.load(f)['posts'][0]['code_verifier']
        for segredo in (SECRET, CODE, verifier, state):
            self.assertNotIn(segredo.encode(), b' '.join(argv))


# ---------- CA5: o OPENER do módulo num socket de verdade ----------
class ServidorLocal:
    """HTTP em 127.0.0.1 com respostas programadas por caminho; anota os caminhos pedidos."""

    def __init__(self, rotas):
        acessos = self.acessos = []

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def do_GET(self):
                acessos.append((self.path, self.headers.get('Authorization')))
                rotas[self.path.split('?')[0]](self)

            def log_message(self, *a):
                pass
        self.srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.url = f'http://127.0.0.1:{self.srv.server_address[1]}'
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def fechar(self):
        self.srv.shutdown()
        self.srv.server_close()


def redirecionar(codigo):
    def rota(h):
        h.send_response(codigo)
        h.send_header('Location', '/destino')
        h.send_header('Content-Length', '0')
        h.end_headers()
    return rota


def em_chunks(status, total, inicio=b'{"error":"not_found","x":"'):
    def rota(h):
        h.send_response(status)
        h.send_header('Content-Type', 'application/json')
        h.send_header('Transfer-Encoding', 'chunked')
        h.end_headers()
        enviado = 0
        pedaco = inicio + b'a' * (65536 - len(inicio))
        try:
            while enviado < total:
                h.wfile.write(b'%x\r\n%s\r\n' % (len(pedaco), pedaco))
                enviado += len(pedaco)
                pedaco = b'a' * 65536
            fim = b'"}'   # JSON válido: só o teto pode recusar
            h.wfile.write(b'%x\r\n%s\r\n0\r\n\r\n' % (len(fim), fim))
        except (BrokenPipeError, ConnectionResetError):
            pass
    return rota


class TestOpenerDeVerdade(unittest.TestCase):
    def setUp(self):
        self.srv = None
        p = mock.patch.dict(os.environ, {'no_proxy': '127.0.0.1', 'NO_PROXY': '127.0.0.1'})
        p.start()
        self.addCleanup(p.stop)

    def tearDown(self):
        if self.srv:
            self.srv.fechar()

    def abrir(self, caminho, auth=None):
        headers = {'Authorization': 'Bearer ' + auth} if auth else {}
        return M._abrir(M.OPENER, urllib.request.Request(self.srv.url + caminho, headers=headers))

    def test_nenhum_codigo_de_redirect_e_seguido(self):
        rotas = {f'/r{c}': redirecionar(c) for c in (301, 302, 303, 307, 308)}
        rotas['/destino'] = lambda h: (h.send_response(200), h.send_header('Content-Length', '2'), h.end_headers(),
                                       h.wfile.write(b'{}'))
        self.srv = ServidorLocal(rotas)
        for c in (301, 302, 303, 307, 308):
            with self.assertRaises(M._Recusa) as cm:
                self.abrir(f'/r{c}', auth=ACCESS)
            self.assertEqual(cm.exception.status, c)
        self.assertEqual([a[0] for a in self.srv.acessos], [f'/r{c}' for c in (301, 302, 303, 307, 308)])

    def test_resposta_em_chunks_acima_de_2_mb_e_recusada(self):
        self.srv = ServidorLocal({'/grande': em_chunks(200, 3 * 1024 * 1024, b'{"x":"'),
                                  '/pequeno': em_chunks(200, 1024 * 1024, b'{"x":"')})
        self.assertEqual(len(self.abrir('/pequeno')['x']), 1024 * 1024 - 6)   # controle: o mesmo formato passa
        with self.assertRaises(M.RespostaInvalida):
            self.abrir('/grande')

    def test_corpo_de_erro_em_chunks_acima_de_2_mb_nao_vira_codigo(self):
        self.srv = ServidorLocal({'/erro': em_chunks(404, 3 * 1024 * 1024)})
        with self.assertRaises(M._Recusa) as cm:
            self.abrir('/erro')
        self.assertEqual((cm.exception.status, cm.exception.codigo), (404, None))

    def test_resposta_de_ate_2_mb_por_socket_passa(self):
        corpo = b'{"id": 1}' + b' ' * (M.MAX_RESPOSTA - 9)

        def rota(h):
            h.send_response(200)
            h.send_header('Content-Length', str(len(corpo)))
            h.end_headers()
            h.wfile.write(corpo)
        self.srv = ServidorLocal({'/ok': rota})
        self.assertEqual(self.abrir('/ok'), {'id': 1})


# ---------- CA3: o servidor e o banco real nunca veem os tokens ----------
def porta_livre():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


class TestServidorNaoExpoe(unittest.TestCase):
    def test_servidor_nao_serve_arquivo_do_projeto(self):
        """O estático é lista fechada: nem ml_api.py, README.md, .gitignore ou ml_tokens.json saem por rota."""
        pasta = tempfile.mkdtemp(dir=T.TMP)
        porta = porta_livre()
        env = {k: v for k, v in os.environ.items() if not k.startswith('ACHADINHOS_')}
        env.update(ACHADINHOS_DB=os.path.join(pasta, 'srv.db'), ACHADINHOS_PORTA=str(porta), ACHADINHOS_DISPARO='0',
                   ACHADINHOS_API_TOKEN_ARQUIVO='/nao/existe', PYTHONDONTWRITEBYTECODE='1')
        p = subprocess.Popen([sys.executable, os.path.join(RAIZ, 'servidor.py')], env=env, stdout=subprocess.DEVNULL,
                             stderr=subprocess.PIPE, text=True)
        try:
            limite = time.monotonic() + 20
            while True:
                try:
                    socket.create_connection(('127.0.0.1', porta), timeout=1).close()
                    break
                except OSError:
                    self.assertIsNone(p.poll(), 'o servidor não subiu')
                    self.assertLess(time.monotonic(), limite)
                    time.sleep(0.1)
            sem_proxy = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            for caminho in ('/ml_api.py', '/README.md', '/.gitignore', '/ml_tokens.json', '/ml_tokens.json.lock',
                            '/testes/test_ml_api.py', '/api/config/ml_tokens', '/api/config/access_token'):
                req = urllib.request.Request(f'http://localhost:{porta}{caminho}')
                try:
                    with sem_proxy.open(req, timeout=10) as r:
                        status, corpo = r.status, r.read()
                except urllib.error.HTTPError as e:
                    status, corpo = e.code, e.read()
                    e.close()
                if caminho.startswith('/api/config/'):
                    self.assertNotIn(b'APP_USR', corpo, caminho)
                    self.assertNotIn(b'TG-', corpo, caminho)
                else:
                    self.assertEqual(status, 404, caminho)
        finally:
            p.terminate()
            p.wait(10)
            if p.stderr:
                p.stderr.close()

    def test_config_do_banco_real_sem_chave_do_ml(self):
        real = os.path.join(RAIZ, 'achadinhos.db')
        if not os.path.exists(real):
            self.skipTest('sem banco real')
        con = sqlite3.connect(f'file:{real}?mode=ro', uri=True)
        try:
            con.execute('PRAGMA query_only = ON')
            chaves = [k for (k,) in con.execute('SELECT chave FROM config')]
            valores = [v for (v,) in con.execute('SELECT valor FROM config')]
        finally:
            con.close()
        for k in chaves:
            self.assertIsNone(re.search(r'ml|token|refresh|secret', k, re.I), k)
        for v in valores:
            self.assertIsNone(re.search(r'APP_USR-|TG-[0-9a-f]', str(v)), 'valor da config parece token do ML')

    def test_nenhum_modulo_do_servidor_ou_do_site_cita_o_ml_api(self):
        for nome in ('servidor.py', 'index.html', 'disparo.py', 'api_ofertas.py', 'genero.py', 'atualizar_precos.py',
                     'coletar_ml.js'):
            with open(os.path.join(RAIZ, nome), encoding='utf-8') as f:
                texto = f.read()
            self.assertIsNone(re.search(r'ml_api|ACHADINHOS_ML_(SECRET|TOKENS)|ml_tokens', texto), nome)


# ---------- CA6: sondar não mexe no banco ----------
class TestSondarQa(T.Cli):
    def test_sondar_nao_altera_o_banco_e_filtra_ids_hostis(self):
        db = os.path.join(self.dir, 'banco.db')
        con = sqlite3.connect(db)
        con.execute('CREATE TABLE items (id INTEGER PRIMARY KEY, loja TEXT, item_id TEXT)')
        con.executemany('INSERT INTO items (loja, item_id) VALUES (?, ?)', [
            ('ml', 'MLB1234567890'), ('ml', 'MLB123456789/../../users/me'), ('ml', 'MLB1234567%2F'),
            ('ml', 'MLB12345678901234567890'), ('ml', 'MLB1234567\n'), ('ml', 'MLB９９９９９９９'),
            ('ml', f'MLB1234567?access_token={ACCESS}')])
        con.commit()
        con.close()
        with open(db, 'rb') as f:
            hash_antes = hashlib.sha256(f.read()).hexdigest()
        arquivos_antes = sorted(os.listdir(self.dir))
        self.gravar_real()
        op = T.OpenerFalso(T.api_padrao(gets=lambda c: {'id': USER}))
        codigo, out, err = self.rodar(['sondar'], op, db=db)
        self.assertEqual(codigo, 0, err)
        self.assertIn('ids do banco: MLB1234567890\n', out)
        caminhos_de_item = [c.caminho for c in op.chamadas if '/items' in c.caminho or '/reviews' in c.caminho]
        self.assertEqual(caminhos_de_item, ['/items/bulk', '/items/bulk', '/items/MLB1234567890',
                                            '/reviews/item/MLB1234567890'])
        self.assertTrue(all(c.query.get('ids', 'MLB1234567890') == 'MLB1234567890' for c in op.chamadas))
        with open(db, 'rb') as f:
            self.assertEqual(hashlib.sha256(f.read()).hexdigest(), hash_antes)
        self.assertEqual(sorted(set(os.listdir(self.dir)) - {'ml_tokens.json', 'ml_tokens.json.lock'}),
                         arquivos_antes)
        T.sem_marcadores(self, out, err)


# ---------- CA10: README ----------
class TestReadme(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(RAIZ, 'README.md'), encoding='utf-8') as f:
            texto = f.read()
        m = re.search(r'^## API oficial do Mercado Livre\n(.*?)(?=^## )', texto, re.S | re.M)
        cls.secao = m.group(1) if m else ''
        cls.readme = texto

    def test_secao_tem_os_comandos_as_variaveis_e_a_receita(self):
        self.assertTrue(self.secao, 'falta a seção "API oficial do Mercado Livre"')
        for termo in ('python3 ml_api.py autorizar', 'python3 ml_api.py conferir', 'ml_api.py sondar',
                      'python3 ml_api.py sair', 'ACHADINHOS_ML_SECRET', 'ACHADINHOS_ML_TOKENS', 'ACHADINHOS_DB',
                      'read -rs S; ACHADINHOS_ML_SECRET="$S" python3 ml_api.py autorizar; unset S',
                      'Publicação e sincronização', 'somente leitura', 'https://desejodemenina.com/ml/callback',
                      '6 meses', '4 meses', 'chmod 600'):
            self.assertIn(termo, self.secao, termo)

    def test_nunca_ensina_export_nem_secret_no_argv(self):
        self.assertIsNone(re.search(r'export\s+ACHADINHOS_ML_SECRET', self.readme))
        self.assertIsNone(re.search(r'ml_api\.py[ \t]+\S+[ \t]+[^\n`]*(secret|SECRET)', self.readme))
        for linha in re.findall(r'ACHADINHOS_ML_SECRET=[^\n]*', self.readme):
            self.assertIn('"$S"', linha)
            self.assertIn('unset S', linha)

    def test_tabela_de_saidas_bate_com_as_excecoes(self):
        linhas = {m.group(1): m.group(2) for m in re.finditer(r'^\| ([0-3]) \| ([^|]*) \|', self.secao, re.M)}
        self.assertEqual(sorted(linhas), ['0', '1', '2', '3'])
        esperado = {
            '1': [(M.ErroApi(500), 'API recusou'), (M.RespostaInvalida(), 'fora do formato'),
                  (M.ErroRede(), 'rede'), (M.EnderecoInvalido('x'), 'endereço colado'),
                  (M.AutorizacaoNegada(), 'error=')],
            '2': [(M.RefazerAutorizacao(), 'autorização vencida'), (M.ConfigFaltando(), 'Secret ausente'),
                  (M.CredencialInvalida(), 'recusado'), (M.SemPermissao(), 'PolicyAgent'),
                  (M.TokensRecusados('x'), 'arquivo de tokens recusado')],
            '3': [(M.Limite(), '429')],
        }
        for saida, casos in esperado.items():
            for excecao, trecho in casos:
                self.assertEqual(excecao.saida, int(saida), type(excecao).__name__)
                self.assertIn(trecho, linhas[saida], (saida, trecho))

    def test_comando_de_teste_do_readme_inclui_a_suite_nova(self):
        self.assertIn('python3 testes/test_ml_api.py -v', self.readme)
        self.assertRegex(self.readme, r'py_compile [^\n]*ml_api\.py')


if __name__ == '__main__':
    unittest.main()
