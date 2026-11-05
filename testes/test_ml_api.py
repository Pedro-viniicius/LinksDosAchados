#!/usr/bin/env python3
"""Testes do ml_api.py (docs/produto/planos/api-oficial-ml.md, etapas 1 e 2: CA2 a CA6 e CA9).

Uso:  python3 testes/test_ml_api.py -v

Nenhum teste fala com o Mercado Livre: a rede passa por openers falsos (OpenerFalso, ou o Opener do
script auxiliar nos subprocessos), o relógio é falso e qualquer saída acidental bate num proxy morto.
ACHADINHOS_ML_TOKENS, ACHADINHOS_DB e ACHADINHOS_ML_CATALOGO apontam para uma pasta temporária antes do
import; o arquivo de tokens de cada teste fica numa subpasta própria. O Secret, os tokens e o code são
marcadores procurados em toda saída, mensagem de exceção e argv.
"""
import ast
import base64
import contextlib
import email.message
import fcntl
import glob
import hashlib
import http.server
import io
import json
import os
import pty
import random
import re
import select
import shutil
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

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix='teste-ml-api-')
for v in ('http_proxy', 'https_proxy', 'ftp_proxy', 'HTTP_PROXY', 'HTTPS_PROXY'):
    os.environ[v] = 'http://127.0.0.1:9'
os.environ['no_proxy'] = ''
os.environ['ACHADINHOS_ML_TOKENS'] = os.path.join(TMP, 'tokens-padrao.json')
os.environ['ACHADINHOS_DB'] = os.path.join(TMP, 'banco-padrao.db')
os.environ['ACHADINHOS_ML_CATALOGO'] = os.path.join(TMP, 'catalogo-padrao.json')
os.environ.pop('ACHADINHOS_ML_SECRET', None)
sys.path.insert(0, RAIZ)

import ml_api as M  # noqa: E402

assert os.path.dirname(M.TOKENS) == TMP and os.path.dirname(M.DB) == TMP and os.path.dirname(M.CATALOGO) == TMP, \
    'o teste não pode tocar os dados reais'

SECRET = 'SEGREDO-MARCADOR-ml-5b1e77'
ACCESS = 'APP_USR-ACESSO-MARCADOR-0001-aaaaaaaaaaaa'
REFRESH = 'TG-RENOVA-MARCADOR-0001-bbbbbbbbbbbbbb'
CODE = 'TG-CODE-MARCADOR-9q8w7e'
USER = 123456789
AGORA = 1_800_000_000
ESCOPO = 'offline_access read'
MARCADORES = (SECRET, ACCESS, REFRESH, CODE, 'ACESSO-NOVO', 'RENOVA-NOVO')


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


# ---------- dados e rede falsos ----------
def tokens(access=ACCESS, refresh=REFRESH, expira_em=AGORA + 3600, user_id=USER, scope=ESCOPO):
    return M.Tokens(user_id, access, expira_em, refresh, scope, '2026-11-05T10:00:00')


def novo(n):
    return f'APP_USR-ACESSO-NOVO-{n:04d}-cccccccccccc', f'TG-RENOVA-NOVO-{n:04d}-dddddddddddd'


def resposta_token(n=1, user_id=USER, scope=ESCOPO, **extra):
    a, r = novo(n)
    d = {'access_token': a, 'token_type': 'Bearer', 'expires_in': 21600, 'scope': scope, 'user_id': user_id,
         'refresh_token': r}
    d.update(extra)
    return d


class Resp:
    def __init__(self, corpo, status=200):
        self.corpo = corpo if isinstance(corpo, bytes) else json.dumps(corpo).encode('utf-8')
        self.status = status
        self._f = io.BytesIO(self.corpo)

    def read(self, n=-1):
        return self._f.read(n)

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def erro_http(status, corpo=None, url='https://api.mercadolibre.com/x', headers=None):
    bruto = corpo if isinstance(corpo, bytes) else json.dumps(corpo if corpo is not None else {}).encode('utf-8')
    h = email.message.Message()
    for k, v in (headers or {}).items():
        h[k] = v
    return urllib.error.HTTPError(url, status, 'x', h, io.BytesIO(bruto))


class Chamada:
    def __init__(self, req):
        self.metodo = req.get_method()
        self.url = req.full_url
        partes = urllib.parse.urlsplit(self.url)
        self.host, self.caminho = partes.netloc, partes.path
        self.query = dict(urllib.parse.parse_qsl(partes.query, keep_blank_values=True))
        self.headers = dict(req.header_items())
        self.auth = req.get_header('Authorization')
        self.corpo = req.data
        self.campos = dict(urllib.parse.parse_qsl(req.data.decode('ascii'))) if req.data else {}


class OpenerFalso:
    """Anota cada requisição e responde com responder(chamada): Resp, exceção (levantada) ou dict (Resp 200)."""
    def __init__(self, responder):
        self.responder = responder
        self.chamadas = []

    def open(self, req, timeout=None):
        c = Chamada(req)
        self.chamadas.append(c)
        r = self.responder(c)
        if isinstance(r, BaseException):
            raise r
        return r if isinstance(r, Resp) else Resp(r)

    def posts(self):
        return [c for c in self.chamadas if c.metodo == 'POST']

    def gets(self):
        return [c for c in self.chamadas if c.metodo == 'GET']


def api_padrao(gets=None, token=None):
    """Responder: POST /oauth/token devolve token() (padrão: novos tokens n=1); GET devolve gets(chamada) ou {}."""
    def responder(c):
        if c.metodo == 'POST':
            return token(c) if token else resposta_token(1)
        return gets(c) if gets else {'id': USER, 'nickname': 'APELIDO-MARCADOR'}
    return responder


def sem_marcadores(teste, *textos):
    for t in textos:
        for m in MARCADORES:
            teste.assertNotIn(m, t)


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(dir=TMP)
        self.caminho = os.path.join(self.dir, 'ml_tokens.json')
        self.agora = [AGORA]
        self.dormidas = []

    def sessao(self, opener, segredo=SECRET):
        return M.Sessao(self.caminho, M.Segredo(segredo) if segredo else None, opener=opener,
                        relogio=lambda: self.agora[0], dormir=self.dormidas.append, aleatorio=lambda: 0.5)

    def gravar(self, **kw):
        M.gravar_tokens(self.caminho, tokens(**kw))

    def lido(self):
        with open(self.caminho, encoding='ascii') as f:
            return json.load(f)


# ---------- funções puras ----------
class TestFuncoesPuras(unittest.TestCase):
    def test_formatar_preco_mesmos_casos_do_js(self):
        # os mesmos de testes/coletar_ml.test.mjs ("formatarPreco: centavos só quando o valor não é inteiro")
        casos = {2569: 'R$ 2.569', 124.2: 'R$ 124,20', 1019.9: 'R$ 1.019,90', 1234567.05: 'R$ 1.234.567,05',
                 99: 'R$ 99', 0.5: 'R$ 0,50'}
        for v, esperado in casos.items():
            self.assertEqual(M.formatar_preco(v), esperado, v)

    def test_formatar_preco_recusa_o_que_nao_e_preco(self):
        for v in (None, '10', True, float('nan'), float('inf'), -1, -0.01):
            with self.assertRaises(ValueError, msg=repr(v)):
                M.formatar_preco(v)

    def test_arredondamento_igual_ao_math_round(self):
        self.assertEqual(M._arredondar_js(0.49999999999999994), 0)   # floor(x + 0.5) daria 1
        self.assertEqual(M._arredondar_js(2.5), 3)
        self.assertEqual(M._arredondar_js(-2.5), -2)

    def test_formatar_preco_paridade_com_o_js(self):
        node = shutil.which('node') or next(iter(sorted(glob.glob(os.path.expanduser(
            '~/.nvm/versions/node/v2*/bin/node')), reverse=True)), None)
        if not node:
            self.skipTest('node não encontrado')
        r = random.Random(20261105)
        valores = [2569, 124.2, 1019.9, 1234567.05, 99, 0.5, 0, 0.005, 0.015, 1.005, 2.675, 10.075, 999.995,
                   1000, 1000000, 123456789.99, 0.1 + 0.2, 0.49999999999999994, 1e-9, 19.999, 7.125]
        valores += [round(r.uniform(0, 20000), 2) for _ in range(300)]
        valores += [r.uniform(0, 5000) for _ in range(200)]
        valores += [r.randint(0, 10 ** 7) for _ in range(50)]
        script = r'''
const fs = require('fs'), vm = require('vm');
const mem = {};
const ctx = { console: { log() {}, warn() {}, error() {} }, setTimeout, clearTimeout, AbortController,
  localStorage: { getItem: (k) => (k in mem ? mem[k] : null), setItem: (k, v) => { mem[k] = String(v); },
                  removeItem: (k) => { delete mem[k]; } },
  fetch: async () => { throw new Error('sem rede'); },
  location: { origin: 'https://lista.mercadolivre.com.br', pathname: '/' } };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), ctx);
const vals = JSON.parse(fs.readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(vals.map((v) => ctx.ColetaML.formatarPreco(v))));
'''
        saida = subprocess.run([node, '-e', script, os.path.join(RAIZ, 'coletar_ml.js')],
                               input=json.dumps(valores), capture_output=True, text=True, timeout=60)
        self.assertEqual(saida.returncode, 0, saida.stderr)
        do_js = json.loads(saida.stdout)
        for v, js in zip(valores, do_js):
            self.assertEqual(M.formatar_preco(v), js, repr(v))

    def test_desconto(self):
        self.assertEqual(M.desconto(100, 200), ('R$ 200', '-50%'))
        self.assertEqual(M.desconto(124.2, 199.9), ('R$ 199,90', '-38%'))
        self.assertEqual(M.desconto(99.5, 100), ('R$ 100', '-1%'))    # 0,5% arredonda para 1 (Math.round)
        self.assertEqual(M.desconto(99.6, 100), ('', ''))             # arredonda para 0%: não é desconto
        for atual, antes in ((100, None), (100, 100), (100, 90), (0, 100), (None, 100), (100, float('nan')),
                             (True, 100), (100, '200')):
            self.assertEqual(M.desconto(atual, antes), ('', ''), (atual, antes))

    def test_eh_usado(self):
        for t in ('iPhone 13 Seminovo', 'Notebook USADO', 'Câmera Recondicionada', 'Fone renovado',
                  'TV de Vitrine', 'Kindle Open  Box', 'Refurbished Mouse', 'Usados em bom estado'):
            self.assertTrue(M.eh_usado(t), t)
        for t in ('Perfume Novo', 'Usadão', 'semi novo', 'Mouse sem uso', '', None, 123):
            self.assertFalse(M.eh_usado(t), t)

    def test_re_usado_igual_ao_das_outras_coletas(self):
        def do_fonte(arquivo, padrao):
            with open(os.path.join(RAIZ, arquivo), encoding='utf-8') as f:
                m = re.search(padrao, f.read(), re.M)
            self.assertIsNotNone(m, arquivo)
            return m.group(1)
        py = r"^RE_USADO = re\.compile\(r'(.+)'\)$"
        self.assertEqual(M.RE_USADO.pattern, do_fonte('coletar_amazon.py', py))
        self.assertEqual(M.RE_USADO.pattern, do_fonte('coletar_shopee.py', py))
        self.assertEqual(M.RE_USADO.pattern, do_fonte('coletar_ml.js', r'^\s*const RX_USADO = /(.+)/;$'))


# ---------- PKCE, state e endereço colado ----------
class TestPkce(unittest.TestCase):
    def test_desafio_do_rfc_7636(self):
        self.assertEqual(M.desafio('dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk'),
                         'E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM')

    def test_verifier_e_state(self):
        v1, c1 = M.novo_pkce()
        v2, _ = M.novo_pkce()
        self.assertEqual(len(v1), 86)
        self.assertRegex(v1, r'\A[A-Za-z0-9_-]{86}\Z')
        self.assertNotEqual(v1, v2)
        esperado = base64.urlsafe_b64encode(hashlib.sha256(v1.encode()).digest()).decode().rstrip('=')
        self.assertEqual(c1, esperado)
        self.assertNotIn('=', c1)
        s = M.novo_state()
        self.assertRegex(s, r'\A[A-Za-z0-9_-]{43}\Z')
        self.assertNotEqual(s, M.novo_state())

    def test_url_de_autorizacao(self):
        self.assertEqual(M.CLIENT_ID, '3553760734310605')
        self.assertEqual(M.REDIRECT_URI, 'https://desejodemenina.com/ml/callback')
        verifier, challenge = M.novo_pkce()
        url = M.url_autorizacao('ESTADO_x', challenge)
        p = urllib.parse.urlsplit(url)
        self.assertEqual((p.scheme, p.netloc, p.path), ('https', 'auth.mercadolivre.com.br', '/authorization'))
        q = urllib.parse.parse_qs(p.query, strict_parsing=True)
        self.assertEqual(q, {'response_type': ['code'], 'client_id': [M.CLIENT_ID], 'redirect_uri': [M.REDIRECT_URI],
                             'state': ['ESTADO_x'], 'code_challenge': [challenge], 'code_challenge_method': ['S256']})
        self.assertNotIn(verifier, url)


class TestEnderecoColado(unittest.TestCase):
    STATE = 'Est4do_do-teste_abcdefghijklmnopqrstuvwxyz0'

    def url(self, cauda='', code=CODE, state=None, caminho='/ml/callback', host='desejodemenina.com', esquema='https'):
        return f'{esquema}://{host}{caminho}?code={code}&state={state or self.STATE}{cauda}'

    def test_aceita_com_e_sem_barra_e_com_espacos_nas_pontas(self):
        for texto in (self.url(), self.url(caminho='/ml/callback/'), '  ' + self.url() + '\n',
                      f'https://desejodemenina.com/ml/callback/?state={self.STATE}&code={CODE}',
                      self.url('&outro=1')):
            self.assertEqual(M.ler_endereco_colado(texto, self.STATE), CODE, texto)

    def recusa(self, texto, tipo=M.EnderecoInvalido):
        with self.assertRaises(tipo) as cm:
            M.ler_endereco_colado(texto, self.STATE)
        self.assertNotIn(CODE, str(cm.exception))
        self.assertNotIn(self.STATE, str(cm.exception))
        self.assertTrue(cm.exception.__suppress_context__ or cm.exception.__context__ is None)
        return cm.exception

    def test_recusa_host_esquema_e_caminho_errados(self):
        for texto in (self.url(esquema='http'), self.url(host='www.desejodemenina.com'),
                      self.url(host='desejodemenina.com.evil.com'), self.url(host='evil.com'),
                      self.url(host='evil.com@desejodemenina.com'), self.url(host='desejodemenina.com@evil.com'),
                      self.url(host='desejodemenina.com:443'), self.url(host='desejodemenina.com:8443'),
                      self.url(host='DESEJODEMENINA.COM'), self.url(caminho='/ml/callbackx'),
                      self.url(caminho='/ml/callback/x'), self.url(caminho='/ML/callback'), self.url(caminho='/'),
                      self.url(caminho='/ml/callback//'), self.url('#frag'), self.url('#'),
                      f'//desejodemenina.com/ml/callback?code={CODE}&state={self.STATE}',
                      f'desejodemenina.com/ml/callback?code={CODE}&state={self.STATE}',
                      f'https://evil.com/?u=https://desejodemenina.com/ml/callback?code={CODE}&state={self.STATE}'):
            self.recusa(texto)

    def test_recusa_state_errado_ausente_ou_repetido(self):
        e = self.recusa(self.url(state='outro_state'))
        self.assertIn('state diferente', str(e))
        self.recusa(f'https://desejodemenina.com/ml/callback?code={CODE}')
        self.recusa(self.url(f'&state={self.STATE}'))
        self.recusa(self.url(state=self.STATE + 'x'))
        self.recusa(self.url(state=self.STATE[:-1]))
        self.recusa(self.url(state='%C3%A9' + self.STATE))

    def test_compara_o_state_em_tempo_constante(self):
        with mock.patch.object(M.hmac, 'compare_digest', wraps=M.hmac.compare_digest) as espiao:
            M.ler_endereco_colado(self.url(), self.STATE)
        espiao.assert_called_once()

    def test_recusa_code_ausente_repetido_ou_fora_do_formato(self):
        self.recusa(f'https://desejodemenina.com/ml/callback?state={self.STATE}')
        self.recusa(self.url('&code=outro'))
        for ruim in ('', 'a.b', 'a%2Fb', 'a%0Ab', '<x>', 'x' * 257):
            self.recusa(self.url(code=ruim))

    def test_error_na_volta_e_autorizacao_negada(self):
        e = self.recusa(f'https://desejodemenina.com/ml/callback?error=access_denied&state={self.STATE}',
                        M.AutorizacaoNegada)
        self.assertEqual(e.saida, 1)
        self.recusa(self.url('&error=x'), M.AutorizacaoNegada)

    def test_recusa_texto_estranho(self):
        for texto in ('', '   ', None, self.url() + 'x' * 5000, self.url(' a'), self.url('\x00'),
                      'https://desejodemenina.com/ml/callback?code=é&state=' + self.STATE, self.url('&&'),
                      'https://desejodemenina.com:abc/ml/callback?code=a&state=b', 'https://[::1/ml/callback'):
            self.recusa(texto)


# ---------- arquivo de tokens ----------
class TestArquivoTokens(Base):
    def test_gravacao_cria_0600_mesmo_com_umask_aberto(self):
        antigo = os.umask(0)
        try:
            self.gravar()
        finally:
            os.umask(antigo)
        self.assertEqual(stat.S_IMODE(os.stat(self.caminho).st_mode), 0o600)
        self.assertEqual(self.lido(), {'v': 1, 'user_id': USER, 'access_token': ACCESS, 'expira_em': AGORA + 3600,
                                       'refresh_token': REFRESH, 'scope': ESCOPO,
                                       'renovado_em': '2026-11-05T10:00:00'})
        t = M.ler_tokens(self.caminho)
        self.assertEqual((t.user_id, t.access.valor(), t.refresh.valor(), t.expira_em, t.scope),
                         (USER, ACCESS, REFRESH, AGORA + 3600, ESCOPO))
        self.assertEqual(os.listdir(self.dir), ['ml_tokens.json'])

    def test_gravacao_atomica_com_o_excl_nofollow_replace_e_fsync(self):
        with open(self.caminho, 'w') as f:
            f.write('antigo')
        os.chmod(self.caminho, 0o644)
        abertos, sincronizados = [], []
        abrir, sincronizar = os.open, os.fsync
        with mock.patch.object(M.os, 'open', side_effect=lambda *a, **k: abertos.append(a) or abrir(*a, **k)), \
                mock.patch.object(M.os, 'fsync', side_effect=lambda fd: sincronizados.append(fd) or sincronizar(fd)), \
                mock.patch.object(M.os, 'replace', wraps=os.replace) as trocar:
            self.gravar()
        tmp = [a for a in abertos if a[0] != self.dir][0]
        self.assertEqual(os.path.dirname(tmp[0]), self.dir)
        for flag in (os.O_CREAT, os.O_EXCL, os.O_NOFOLLOW, os.O_WRONLY):
            self.assertTrue(tmp[1] & flag, flag)
        self.assertEqual(tmp[2], 0o600)
        trocar.assert_called_once_with(tmp[0], self.caminho)
        self.assertEqual(len(sincronizados), 2)   # o arquivo e a pasta
        self.assertTrue(any(a[0] == self.dir for a in abertos))
        self.assertEqual(stat.S_IMODE(os.stat(self.caminho).st_mode), 0o600)
        self.assertEqual(self.lido()['access_token'], ACCESS)

    def test_falha_no_meio_nao_deixa_temporario_e_mantem_o_antigo(self):
        self.gravar()
        with mock.patch.object(M.os, 'replace', side_effect=OSError('falhou')):
            with self.assertRaises(OSError):
                M.gravar_tokens(self.caminho, tokens(access=novo(1)[0]))
        self.assertEqual(os.listdir(self.dir), ['ml_tokens.json'])
        self.assertEqual(self.lido()['access_token'], ACCESS)

    def test_gravar_sobre_symlink_troca_o_link_e_nao_o_alvo(self):
        alvo = os.path.join(self.dir, 'alvo.txt')
        with open(alvo, 'w') as f:
            f.write('nao mexer')
        os.symlink(alvo, self.caminho)
        self.gravar()
        self.assertFalse(os.path.islink(self.caminho))
        with open(alvo) as f:
            self.assertEqual(f.read(), 'nao mexer')

    def recusado(self, motivo=None):
        with self.assertRaises(M.TokensRecusados) as cm:
            M.ler_tokens(self.caminho)
        self.assertEqual(cm.exception.saida, 2)
        sem_marcadores(self, str(cm.exception), repr(cm.exception))
        if motivo:
            self.assertIn(motivo, str(cm.exception))
        return cm.exception

    def test_sem_arquivo_pede_autorizar(self):
        with self.assertRaises(M.RefazerAutorizacao) as cm:
            M.ler_tokens(self.caminho)
        self.assertEqual(cm.exception.saida, 2)
        self.assertIn('rode `ml_api.py autorizar`', str(cm.exception))

    def test_recusa_symlink_mesmo_para_arquivo_bom(self):
        bom = os.path.join(self.dir, 'bom.json')
        M.gravar_tokens(bom, tokens())
        os.symlink(bom, self.caminho)
        self.recusado('link simbólico')

    def test_recusa_o_que_nao_e_arquivo_comum(self):
        os.mkdir(self.caminho)
        self.recusado('arquivo comum')
        os.rmdir(self.caminho)
        os.mkfifo(self.caminho, 0o600)
        inicio = time.monotonic()
        self.recusado('arquivo comum')   # FIFO: não trava
        self.assertLess(time.monotonic() - inicio, 5)

    def test_recusa_permissao_aberta(self):
        self.gravar()
        for modo in (0o644, 0o640, 0o604, 0o660, 0o601, 0o610):
            os.chmod(self.caminho, modo)
            self.recusado('chmod 600')
        os.chmod(self.caminho, 0o400)
        self.assertEqual(M.ler_tokens(self.caminho).access.valor(), ACCESS)

    def test_recusa_dono_diferente(self):
        self.gravar()
        with mock.patch.object(M.os, 'getuid', return_value=os.getuid() + 1):
            self.recusado('dono')

    def test_teto_de_4_kb(self):
        corpo = tokens().como_json()
        for tamanho, aceita in ((M.MAX_ARQUIVO_TOKENS, True), (M.MAX_ARQUIVO_TOKENS + 1, False)):
            with open(self.caminho, 'w') as f:
                f.write(corpo + ' ' * (tamanho - len(corpo)))
            os.chmod(self.caminho, 0o600)
            self.assertEqual(os.path.getsize(self.caminho), tamanho)
            if aceita:
                self.assertEqual(M.ler_tokens(self.caminho).refresh.valor(), REFRESH)
            else:
                self.recusado('4096')

    def test_recusa_conteudo_fora_do_formato(self):
        base = json.loads(tokens().como_json())
        ruins = ['nada', '[]', '{}', json.dumps(dict(base, extra=1)), json.dumps({k: v for k, v in base.items()
                                                                                   if k != 'scope'}),
                 json.dumps(dict(base, v=2)), json.dumps(dict(base, v=True)), json.dumps(dict(base, user_id=True)),
                 json.dumps(dict(base, user_id=0)), json.dumps(dict(base, user_id='1')),
                 json.dumps(dict(base, expira_em=1.5)), json.dumps(dict(base, access_token=ACCESS + '\r\nX: y')),
                 json.dumps(dict(base, access_token='curto')), json.dumps(dict(base, refresh_token=None)),
                 json.dumps(dict(base, scope='read\nwrite')), json.dumps(dict(base, renovado_em='ontem')),
                 json.dumps(dict(base, access_token='ACESSO-ÇÇÇ-' + 'a' * 20), ensure_ascii=False),
                 '[' * 3000]
        for conteudo in ruins:
            with open(self.caminho, 'w', encoding='utf-8') as f:
                f.write(conteudo)
            os.chmod(self.caminho, 0o600)
            self.recusado('fora do formato')

    def test_repr_mascarado(self):
        t = tokens()
        sem_marcadores(self, repr(t), str(t), f'{t}', repr(M.Segredo(SECRET)), str(M.Segredo(SECRET)),
                       f'{M.Segredo(SECRET)}', f'{M.Segredo(SECRET):>40}', repr(self.sessao(None)))

    def test_trava_0600_e_recusa_link(self):
        antigo = os.umask(0)
        try:
            with M.travar(self.caminho):
                pass
        finally:
            os.umask(antigo)
        trava = self.caminho + '.lock'
        self.assertEqual(stat.S_IMODE(os.stat(trava).st_mode), 0o600)
        os.chmod(trava, 0o644)
        with M.travar(self.caminho):
            pass
        self.assertEqual(stat.S_IMODE(os.stat(trava).st_mode), 0o600)
        os.unlink(trava)
        os.symlink(os.path.join(self.dir, 'outro'), trava)
        with self.assertRaises(M.TokensRecusados):
            with M.travar(self.caminho):
                pass
        self.assertFalse(os.path.exists(os.path.join(self.dir, 'outro')))

    def test_trava_e_exclusiva(self):
        with M.travar(self.caminho):
            with open(self.caminho + '.lock', 'a') as f:
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with open(self.caminho + '.lock', 'a') as f:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)


# ---------- renovação ----------
class TestRenovacao(Base):
    def test_token_valido_nao_renova(self):
        self.gravar(expira_em=AGORA + 301)
        op = OpenerFalso(api_padrao())
        self.assertEqual(self.sessao(op).get('/users/me')['id'], USER)
        self.assertEqual(op.posts(), [])
        self.assertEqual(op.gets()[0].auth, 'Bearer ' + ACCESS)

    def test_margem_de_5_minutos(self):
        for falta, renova in ((300, False), (299, True), (0, True), (-100, True)):
            self.gravar(expira_em=AGORA + falta)
            op = OpenerFalso(api_padrao())
            self.sessao(op).get('/users/me')
            self.assertEqual(len(op.posts()), int(renova), falta)

    def test_renovacao_grava_antes_de_qualquer_outra_chamada(self):
        self.gravar(expira_em=AGORA + 100)
        vistos = []

        def responder(c):
            if c.metodo == 'POST':
                with open(self.caminho + '.lock', 'a') as f:   # a renovação acontece sob o flock
                    with self.assertRaises(BlockingIOError):
                        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return resposta_token(1)
            vistos.append(self.lido())   # no momento do GET, o arquivo já tem o par novo
            return {'id': USER}
        op = OpenerFalso(responder)
        self.agora[0] = AGORA + 5
        self.sessao(op).get('/users/me')
        post = op.posts()[0]
        self.assertEqual(post.url, 'https://api.mercadolibre.com/oauth/token')
        self.assertEqual(post.headers['Content-type'], 'application/x-www-form-urlencoded')
        self.assertEqual(post.campos, {'grant_type': 'refresh_token', 'client_id': M.CLIENT_ID,
                                       'client_secret': SECRET, 'refresh_token': REFRESH})
        self.assertNotIn(SECRET, post.url)
        self.assertIsNone(post.auth)
        a, r = novo(1)
        self.assertEqual(vistos[0]['refresh_token'], r)
        self.assertEqual(op.gets()[0].auth, 'Bearer ' + a)
        d = self.lido()
        self.assertEqual((d['access_token'], d['refresh_token'], d['expira_em'], d['user_id'], d['scope']),
                         (a, r, AGORA + 5 + 21600, USER, ESCOPO))
        self.assertEqual(d['renovado_em'], time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(AGORA + 5)))
        self.assertEqual(stat.S_IMODE(os.stat(self.caminho).st_mode), 0o600)

    def test_invalid_grant_pede_autorizar_e_nao_mexe_no_arquivo(self):
        self.gravar(expira_em=AGORA - 1)
        antes = self.lido()
        op = OpenerFalso(api_padrao(token=lambda c: erro_http(400, {'error': 'invalid_grant',
                                                                    'message': 'refresh ' + REFRESH})))
        with self.assertRaises(M.RefazerAutorizacao) as cm:
            self.sessao(op).get('/users/me')
        self.assertEqual(cm.exception.saida, 2)
        self.assertIn('rode `ml_api.py autorizar`', str(cm.exception))
        sem_marcadores(self, str(cm.exception))
        self.assertIsNone(cm.exception.__context__ if not cm.exception.__suppress_context__ else None)
        self.assertEqual(self.lido(), antes)
        self.assertEqual(op.gets(), [])

    def test_invalid_client_e_credencial_invalida(self):
        self.gravar(expira_em=AGORA - 1)
        for corpo in ({'error': 'invalid_client'}, {'error': 'unauthorized_client'}):
            op = OpenerFalso(api_padrao(token=lambda c, corpo=corpo: erro_http(401, corpo)))
            with self.assertRaises(M.CredencialInvalida) as cm:
                self.sessao(op).get('/users/me')
            self.assertEqual(cm.exception.saida, 2)

    def test_sem_secret_com_token_vencido_e_config_faltando_sem_rede(self):
        self.gravar(expira_em=AGORA + 10)
        op = OpenerFalso(api_padrao())
        with self.assertRaises(M.ConfigFaltando) as cm:
            self.sessao(op, segredo=None).get('/users/me')
        self.assertEqual(cm.exception.saida, 2)
        self.assertIn('read -rs S; ACHADINHOS_ML_SECRET="$S"', str(cm.exception))
        self.assertEqual(op.chamadas, [])

    def test_sem_secret_com_token_valido_funciona(self):
        self.gravar()
        op = OpenerFalso(api_padrao())
        self.assertEqual(self.sessao(op, segredo=None).get('/users/me')['id'], USER)

    def test_resposta_de_renovacao_ruim_nao_grava(self):
        self.gravar(expira_em=AGORA - 1)
        antes = self.lido()
        ruins = [resposta_token(refresh_token=None), resposta_token(user_id=USER + 1), resposta_token(expires_in=0),
                 resposta_token(expires_in='21600'), resposta_token(access_token='a b c d e f g h i j k l'),
                 resposta_token(scope='read\nwrite'), [], 'texto']
        for corpo in ruins:
            op = OpenerFalso(api_padrao(token=lambda c, corpo=corpo: corpo))
            with self.assertRaises(M.RespostaInvalida, msg=repr(corpo)) as cm:
                self.sessao(op).get('/users/me')
            # R5: o refresh pode ter sido gasto; pede o autorizar já (saída 2), sem esperar o invalid_grant
            self.assertIsInstance(cm.exception, M.RenovacaoInvalida, repr(corpo))
            self.assertEqual(cm.exception.saida, 2)
            self.assertIn('rode `ml_api.py autorizar`', str(cm.exception))
            self.assertEqual(type(cm.exception) is M.SemRefreshToken, corpo is ruins[0], repr(corpo))
            self.assertEqual(self.lido(), antes)
            self.assertEqual(op.gets(), [])
        self.assertIn('offline_access', str(M.SemRefreshToken()))
        # 200 que nem é JSON também
        op = OpenerFalso(api_padrao(token=lambda c: Resp(b'nao e json')))
        with self.assertRaises(M.RenovacaoInvalida):
            self.sessao(op).get('/users/me')
        self.assertEqual(self.lido(), antes)

    def test_401_renova_uma_vez_e_tenta_de_novo(self):
        self.gravar()

        def gets(c):
            return erro_http(401, {'error': 'invalid_token'}) if c.auth == 'Bearer ' + ACCESS else {'id': USER}
        op = OpenerFalso(api_padrao(gets=gets))
        self.assertEqual(self.sessao(op).get('/users/me'), {'id': USER})
        self.assertEqual(len(op.posts()), 1)
        self.assertEqual([c.auth for c in op.gets()], ['Bearer ' + ACCESS, 'Bearer ' + novo(1)[0]])

    def test_401_de_novo_nao_entra_em_laco(self):
        self.gravar()
        op = OpenerFalso(api_padrao(gets=lambda c: erro_http(401, {'error': 'invalid_token'})))
        with self.assertRaises(M.ErroApi) as cm:
            self.sessao(op).get('/users/me')
        self.assertEqual((cm.exception.status, cm.exception.codigo, cm.exception.saida), (401, 'invalid_token', 1))
        self.assertEqual((len(op.posts()), len(op.gets())), (1, 2))

    def test_401_seguido_renova_uma_vez_por_sessao(self):
        """S3: 10 GETs com 401 na mesma sessão gastam o refresh (rotacionam o par) uma vez só."""
        self.gravar()
        n = [0]

        def token(c):
            n[0] += 1
            return resposta_token(n[0])
        op = OpenerFalso(api_padrao(gets=lambda c: erro_http(401, {'error': 'invalid_token'}), token=token))
        sessao = self.sessao(op)
        for _ in range(10):
            with self.assertRaises(M.ErroApi) as cm:
                sessao.get('/users/me')
            self.assertEqual(cm.exception.status, 401)
        self.assertEqual(len(op.posts()), 1)
        self.assertEqual(len(op.gets()), 11)   # 1º get: 401, renova, 401; os outros 9: 401 direto
        self.assertEqual(self.lido()['refresh_token'], novo(1)[1])
        # outra sessão (outro comando) pode renovar de novo
        op2 = OpenerFalso(api_padrao(gets=lambda c: erro_http(401, {'error': 'invalid_token'}),
                                     token=lambda c: resposta_token(2)))
        with self.assertRaises(M.ErroApi):
            self.sessao(op2).get('/users/me')
        self.assertEqual(len(op2.posts()), 1)

    def test_401_quando_outro_processo_ja_renovou_nao_gasta_o_refresh(self):
        self.gravar()
        a2, r2 = novo(7)

        def gets(c):
            if c.auth == 'Bearer ' + ACCESS:   # outro comando renovou no meio: o arquivo já tem o par novo
                M.gravar_tokens(self.caminho, tokens(access=a2, refresh=r2, expira_em=AGORA + 21600))
                return erro_http(401, {'error': 'invalid_token'})
            return {'id': USER}
        op = OpenerFalso(api_padrao(gets=gets))
        self.sessao(op).get('/users/me')
        self.assertEqual(op.posts(), [])
        self.assertEqual(op.gets()[-1].auth, 'Bearer ' + a2)

    def test_rele_o_arquivo_dentro_do_lock(self):
        """Lê vencido, espera o lock; outro comando renova enquanto isso: usa o token dele, sem POST."""
        self.gravar(expira_em=AGORA - 1)
        a2, r2 = novo(9)
        op = OpenerFalso(api_padrao())
        resultado = {}
        lido = threading.Event()
        ler = M.ler_tokens

        def ler_e_avisar(caminho):
            t = ler(caminho)
            lido.set()
            return t

        def rodar():
            try:
                resultado['r'] = self.sessao(op).get('/users/me')
            except Exception as e:   # pragma: no cover - aparece na asserção
                resultado['e'] = e
        with mock.patch.object(M, 'ler_tokens', side_effect=ler_e_avisar):
            with M.travar(self.caminho):
                t = threading.Thread(target=rodar)
                t.start()
                self.assertTrue(lido.wait(5))
                time.sleep(0.2)   # a outra thread já leu o vencido e está presa no flock
                M.gravar_tokens(self.caminho, tokens(access=a2, refresh=r2, expira_em=AGORA + 21600))
            t.join(10)
        self.assertNotIn('e', resultado)
        self.assertEqual(op.posts(), [])
        self.assertEqual(op.gets()[0].auth, 'Bearer ' + a2)


# ---------- cliente HTTP ----------
class TestCliente(Base):
    def setUp(self):
        super().setUp()
        self.gravar()

    def test_host_fixo_get_e_bearer_no_header(self):
        op = OpenerFalso(api_padrao(gets=lambda c: [1, 2]))
        self.assertEqual(self.sessao(op).get('/items/bulk', {'ids': 'MLB1,MLB2', 'attributes': 'body.price'}), [1, 2])
        c = op.chamadas[0]
        self.assertEqual(c.metodo, 'GET')
        self.assertEqual(c.url, 'https://api.mercadolibre.com/items/bulk?ids=MLB1,MLB2&attributes=body.price')
        self.assertEqual(c.auth, 'Bearer ' + ACCESS)
        self.assertNotIn(ACCESS, c.url)
        self.assertIsNone(c.corpo)

    def test_parametro_nao_muda_o_host(self):
        op = OpenerFalso(api_padrao())
        self.sessao(op).get('/sites/MLB/search', {'q': '@evil.com/#?x=1&y=2', 'limit': 1})
        c = op.chamadas[0]
        self.assertEqual((c.host, c.caminho), ('api.mercadolibre.com', '/sites/MLB/search'))
        self.assertEqual(c.query, {'q': '@evil.com/#?x=1&y=2', 'limit': '1'})

    def test_caminho_montado_pelo_codigo(self):
        op = OpenerFalso(api_padrao())
        for ruim in ('', 'users/me', '//evil.com/x', '/a/../b', '/a/..', '/a/./b', '/a?x=1', '/a#b', '/a b', '/@evil',
                     'https://evil.com/x', '/a\\b', '/a/', None, '/a%2Fb', '/é'):
            with self.assertRaises(ValueError, msg=repr(ruim)):
                self.sessao(op).get(ruim)
        self.assertEqual(op.chamadas, [])

    def test_redirect_nao_e_seguido(self):
        self.assertTrue(any(isinstance(h, M.SemRedirecionar) for h in M.OPENER.handlers))
        self.assertIsNone(M.SemRedirecionar().redirect_request(None, None, 302, 'x', {}, 'https://evil.com/'))
        acessos = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                acessos.append(self.path)
                self.send_response(302)
                self.send_header('Location', '/destino')
                self.send_header('Content-Length', '0')
                self.end_headers()

            def log_message(self, *a):
                pass
        srv = http.server.HTTPServer(('127.0.0.1', 0), Handler)
        th = threading.Thread(target=srv.serve_forever, daemon=True)
        th.start()
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), M.SemRedirecionar)
            with self.assertRaises(urllib.error.HTTPError) as cm:
                opener.open(f'http://127.0.0.1:{srv.server_address[1]}/origem', timeout=5)
            self.assertEqual(cm.exception.code, 302)
            cm.exception.close()
        finally:
            srv.shutdown()
            srv.server_close()
        self.assertEqual(acessos, ['/origem'])

    def test_3xx_vira_erro(self):
        op = OpenerFalso(api_padrao(gets=lambda c: erro_http(302, b'', headers={'Location': 'https://evil.com/'})))
        with self.assertRaises(M.ErroApi) as cm:
            self.sessao(op).get('/users/me')
        self.assertEqual((cm.exception.status, cm.exception.saida), (302, 1))
        self.assertEqual(len(op.chamadas), 1)

    def test_teto_de_2_mb(self):
        base = json.dumps({'id': USER}).encode()
        for tamanho, aceita in ((M.MAX_RESPOSTA, True), (M.MAX_RESPOSTA + 1, False)):
            corpo = base + b' ' * (tamanho - len(base))
            op = OpenerFalso(api_padrao(gets=lambda c, corpo=corpo: Resp(corpo)))
            if aceita:
                self.assertEqual(self.sessao(op).get('/users/me'), {'id': USER})
            else:
                with self.assertRaises(M.RespostaInvalida):
                    self.sessao(op).get('/users/me')

    def test_corpo_de_erro_grande_nao_e_lido(self):
        corpo = json.dumps({'error': 'not_found'}).encode() + b' ' * M.MAX_RESPOSTA
        op = OpenerFalso(api_padrao(gets=lambda c: erro_http(404, corpo)))
        with self.assertRaises(M.ErroApi) as cm:
            self.sessao(op).get('/users/me')
        self.assertEqual((cm.exception.status, cm.exception.codigo), (404, None))

    def test_429_backoff_exponencial_com_jitter_e_limite_na_terceira(self):
        op = OpenerFalso(api_padrao(gets=lambda c: erro_http(429, {'message': 'too many'})))
        with self.assertRaises(M.Limite) as cm:
            self.sessao(op).get('/users/me')
        self.assertEqual(cm.exception.saida, 3)
        self.assertEqual(len(op.gets()), 3)
        self.assertEqual(self.dormidas, [3.0, 6.0])   # base 2 s, dobra, jitter 0,5 (fixo no teste)
        jitter = iter([0.0, 0.999])
        s = M.Sessao(self.caminho, None, opener=op, relogio=lambda: AGORA, dormir=self.dormidas.append,
                     aleatorio=lambda: next(jitter))
        self.dormidas.clear()
        with self.assertRaises(M.Limite):
            s.get('/users/me')
        self.assertEqual(self.dormidas[0], 2.0)
        self.assertAlmostEqual(self.dormidas[1], 4 * 1.999)

    def test_429_que_passa_continua(self):
        respostas = iter([erro_http(429, {}), erro_http(400, {'code': 'local_rate_limited'}), {'ok': 1}])
        op = OpenerFalso(api_padrao(gets=lambda c: next(respostas)))
        self.assertEqual(self.sessao(op).get('/users/me'), {'ok': 1})
        self.assertEqual(len(self.dormidas), 2)

    def test_local_rate_limited_conta_como_limite(self):
        for corpo in ({'code': 'local_rate_limited'}, {'error': 'local_rate_limited'},
                      {'error': 'outro', 'code': 'local_rate_limited'}):
            op = OpenerFalso(api_padrao(gets=lambda c, corpo=corpo: erro_http(400, corpo)))
            with self.assertRaises(M.Limite):
                self.sessao(op).get('/users/me')
            self.assertEqual(len(op.gets()), 3)

    def test_403_policy_agent(self):
        corpo = {'blocked_by': 'PolicyAgent', 'code': 'PA_UNAUTHORIZED_RESULT_FROM_POLICIES', 'message': ACCESS}
        op = OpenerFalso(api_padrao(gets=lambda c: erro_http(403, corpo)))
        with self.assertRaises(M.SemPermissao) as cm:
            self.sessao(op).get('/items/MLB123456')
        e = cm.exception
        self.assertEqual((e.saida, e.status, e.codigo), (2, 403, 'PA_UNAUTHORIZED_RESULT_FROM_POLICIES'))
        self.assertIn('Publicação e sincronização', str(e))
        sem_marcadores(self, str(e))
        self.assertEqual(len(op.chamadas), 1)
        for corpo in ({'blocked_by': 'PolicyAgent', 'code': ACCESS}, {'blocked_by': 'PolicyAgent', 'error': ACCESS},
                      {'blocked_by': 'PolicyAgent', 'code': 'PA_' + 'X' * 70}):
            op = OpenerFalso(api_padrao(gets=lambda c, corpo=corpo: erro_http(403, corpo)))
            with self.assertRaises(M.SemPermissao) as cm:
                self.sessao(op).get('/items/MLB123456')
            self.assertIsNone(cm.exception.codigo, corpo)
            sem_marcadores(self, str(cm.exception))

    def test_403_sem_policy_agent_e_outros_erros(self):
        casos = [(403, {'message': 'forbidden'}, None), (404, {'error': 'not_found', 'message': 'x'}, 'not_found'),
                 (500, b'<html>', None), (400, {'error': ACCESS}, None), (400, {'error': 'x' * 65}, None),
                 (400, {'error': 'a-b'}, None), (400, {'error': 12}, None), (400, {'code': 'bad_request'}, 'bad_request'),
                 (400, [1], None), (418, b'', None)]
        for status, corpo, codigo in casos:
            op = OpenerFalso(api_padrao(gets=lambda c, s=status, b=corpo: erro_http(s, b)))
            with self.assertRaises(M.ErroApi) as cm:
                self.sessao(op).get('/users/me')
            e = cm.exception
            self.assertEqual((e.status, e.codigo, e.saida), (status, codigo, 1), (status, corpo))
            self.assertIn(f'HTTP {status}', str(e))
            sem_marcadores(self, str(e), repr(e))
            self.assertTrue(e.__suppress_context__)

    def test_erro_api_filtra_status_e_codigo(self):
        e = M.ErroApi('500\r\n', 'abc<script>')
        self.assertEqual((e.status, e.codigo), (0, None))
        self.assertEqual(M.ErroApi(True, 'a').status, 0)
        self.assertIsNone(M.SemPermissao(ACCESS).codigo)
        self.assertEqual(M.SemPermissao('PA_X').codigo, 'PA_X')

    def test_codigo_do_corpo_so_com_texto_filtrado(self):
        casos = [({'error': 'not_found'}, ('not_found', False)), ({'error': ACCESS}, (None, False)),
                 ({'error': 12, 'code': 'bad_request'}, ('bad_request', False)), ({'code': 'a' * 65}, (None, False)),
                 ({'blocked_by': 'PolicyAgent', 'code': 'PA_UNAUTHORIZED_RESULT_FROM_POLICIES'},
                  ('PA_UNAUTHORIZED_RESULT_FROM_POLICIES', True)),
                 ({'blocked_by': 'PolicyAgent', 'error': ACCESS, 'code': ACCESS}, (None, True)),
                 ({'error': 'x', 'code': 'local_rate_limited'}, ('local_rate_limited', False)),
                 ([], (None, False)), ('texto', (None, False))]
        for corpo, esperado in casos:
            self.assertEqual(M._codigo_do_corpo(corpo), esperado, corpo)

    def test_resposta_200_fora_do_formato(self):
        for corpo in (b'nao e json', b'"texto"', b'12', b'null', b'[' * 100000):
            op = OpenerFalso(api_padrao(gets=lambda c, corpo=corpo: Resp(corpo)))
            with self.assertRaises(M.RespostaInvalida, msg=corpo[:10]):
                self.sessao(op).get('/users/me')

    def test_falha_de_rede_sem_detalhe(self):
        for exc in (urllib.error.URLError(f'falhou {ACCESS}'), TimeoutError(SECRET), ConnectionResetError(ACCESS),
                    __import__('http.client').client.IncompleteRead(ACCESS.encode())):
            op = OpenerFalso(api_padrao(gets=lambda c, exc=exc: exc))
            with self.assertRaises(M.ErroRede) as cm:
                self.sessao(op).get('/users/me')
            sem_marcadores(self, str(cm.exception), repr(cm.exception))
            self.assertTrue(cm.exception.__suppress_context__)
            self.assertIsNone(cm.exception.__cause__)


# ---------- CLI (no mesmo processo) ----------
class TerminalFalso(io.StringIO):
    def isatty(self):
        return True


class Cli(Base):
    """main() com o OPENER, o TOKENS e o DB do módulo trocados; o Secret só no os.environ."""

    def rodar(self, argv, opener=None, secret=None, entrada=None, db=None):
        out, err = io.StringIO(), io.StringIO()
        env = {'ACHADINHOS_ML_SECRET': secret} if secret else {}
        pilha = contextlib.ExitStack()
        with pilha:
            pilha.enter_context(mock.patch.dict(os.environ, env))
            if not secret:
                os.environ.pop('ACHADINHOS_ML_SECRET', None)
            pilha.enter_context(mock.patch.object(M, 'OPENER', opener or OpenerFalso(api_padrao())))
            pilha.enter_context(mock.patch.object(M, 'TOKENS', self.caminho))
            pilha.enter_context(mock.patch.object(M, 'DB', db or os.path.join(self.dir, 'sem-banco.db')))
            pilha.enter_context(mock.patch.object(M, 'BACKOFF_BASE', 0.0))
            # S1: no terminal o endereço colado é lido pelo getpass (sem eco); input() nunca é usado
            pilha.enter_context(mock.patch.object(M.sys, 'stdin', TerminalFalso()))
            pilha.enter_context(mock.patch('builtins.input', side_effect=AssertionError('input inesperado')))
            if entrada is not None:
                def ler(prompt=''):
                    self.prompts.append(prompt)
                    return entrada(out)
                self.prompts = []
                pilha.enter_context(mock.patch('getpass.getpass', side_effect=ler))
            else:
                pilha.enter_context(mock.patch('getpass.getpass', side_effect=AssertionError('getpass inesperado')))
            pilha.enter_context(contextlib.redirect_stdout(out))
            pilha.enter_context(contextlib.redirect_stderr(err))
            codigo = M.main(argv)
            self.secret_ficou = 'ACHADINHOS_ML_SECRET' in os.environ
        return codigo, out.getvalue(), err.getvalue()

    def gravar_real(self, falta=3600, **kw):
        self.gravar(expira_em=int(time.time()) + falta, **kw)


class TestAutorizar(Cli):
    def colar(self, cauda='', state=None, host='desejodemenina.com'):
        def entrada(out):
            url = re.search(r'https://auth\.mercadolivre\.com\.br/authorization\?\S+', out.getvalue()).group(0)
            q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
            self.challenge = q['code_challenge']
            return f'https://{host}/ml/callback/?code={CODE}&state={state or q["state"]}{cauda}'
        return entrada

    def test_fluxo_completo(self):
        recebido = {}

        def token(c):
            recebido.update(c.campos)
            recebido['url'] = c.url
            return resposta_token(1)
        op = OpenerFalso(api_padrao(token=token))
        codigo, out, err = self.rodar(['autorizar'], op, secret=SECRET, entrada=self.colar())
        self.assertEqual(codigo, 0, err)
        self.assertFalse(self.secret_ficou)   # lido com pop
        self.assertEqual(recebido['url'], 'https://api.mercadolibre.com/oauth/token')
        verifier = recebido.pop('code_verifier')
        self.assertEqual(M.desafio(verifier), self.challenge)
        self.assertEqual(len(verifier), 86)
        recebido.pop('url')
        self.assertEqual(recebido, {'grant_type': 'authorization_code', 'client_id': M.CLIENT_ID,
                                    'client_secret': SECRET, 'code': CODE, 'redirect_uri': M.REDIRECT_URI})
        self.assertEqual(op.gets(), [])
        d = self.lido()
        self.assertEqual((d['access_token'], d['refresh_token'], d['user_id']), (*novo(1), USER))
        self.assertEqual(stat.S_IMODE(os.stat(self.caminho).st_mode), 0o600)
        self.assertIn('OK: autorização gravada. Escopos: offline_access read', out)
        sem_marcadores(self, out, err)
        self.assertNotIn(verifier, out + err)
        self.assertEqual(err, '')

    def test_colagem_pelo_getpass_sem_eco(self):
        """S1: no terminal, o endereço (com o code) é lido sem eco, e o prompt avisa."""
        codigo, out, err = self.rodar(['autorizar'], OpenerFalso(api_padrao()), secret=SECRET, entrada=self.colar())
        self.assertEqual(codigo, 0, err)
        self.assertEqual(self.prompts, ['3. Cole aqui e tecle Enter (o endereço não aparece): '])

    def test_ler_colado_escolhe_getpass_no_terminal_e_stdin_fora_dele(self):
        with mock.patch.object(M.sys, 'stdin', TerminalFalso()), \
                mock.patch('getpass.getpass', return_value='G') as gp, \
                mock.patch('builtins.input', side_effect=AssertionError('input no terminal')):
            self.assertEqual(M.ler_colado('P: '), 'G')
        gp.assert_called_once_with('P: ')
        with mock.patch.object(M.sys, 'stdin', io.StringIO()), \
                mock.patch('getpass.getpass', side_effect=AssertionError('getpass sem terminal')), \
                mock.patch('builtins.input', return_value='I') as inp:
            self.assertEqual(M.ler_colado('P: '), 'I')
        inp.assert_called_once_with('P: ')

    def test_pasta_sem_escrita_para_antes_de_gastar_o_code(self):
        """R4: a trava abre antes da troca; se não abrir, o code não vai ao ML."""
        self.caminho = os.path.join(self.dir, 'nao-existe', 'ml_tokens.json')
        op = OpenerFalso(api_padrao())
        codigo, out, err = self.rodar(['autorizar'], op, secret=SECRET, entrada=self.colar())
        self.assertEqual(codigo, 2, err)
        self.assertIn('trava', err)
        self.assertEqual(op.chamadas, [])
        sem_marcadores(self, out, err)

    def test_apaga_sobra_de_gravacao_interrompida(self):
        sobra = os.path.join(self.dir, '.ml_tokens.json.0123456789abcdef.tmp')
        outros = [os.path.join(self.dir, n) for n in ('.ml_tokens.json.xyz.tmp', '.outro.json.0123456789abcdef.tmp')]
        for p in [sobra] + outros:
            with open(p, 'w') as f:
                f.write(ACCESS)
        codigo, out, err = self.rodar(['autorizar'], OpenerFalso(api_padrao()), secret=SECRET, entrada=self.colar())
        self.assertEqual(codigo, 0, err)
        self.assertFalse(os.path.exists(sobra))
        self.assertTrue(all(os.path.exists(p) for p in outros))

    def test_sem_secret_nao_imprime_url_nem_pede_endereco(self):
        codigo, out, err = self.rodar(['autorizar'])
        self.assertEqual(codigo, 2)
        self.assertNotIn('auth.mercadolivre', out)
        self.assertIn('ACHADINHOS_ML_SECRET="$S" python3 ml_api.py autorizar; unset S', err)
        self.assertFalse(os.path.exists(self.caminho))

    def test_endereco_errado_nao_troca_nem_grava(self):
        for entrada in (self.colar(host='evil.com'), self.colar(state='outro_state_qualquer'),
                        self.colar('&error=access_denied'), lambda out: 'qualquer coisa'):
            op = OpenerFalso(api_padrao())
            codigo, out, err = self.rodar(['autorizar'], op, secret=SECRET, entrada=entrada)
            self.assertEqual(codigo, 1, err)
            self.assertEqual(op.chamadas, [])
            self.assertFalse(os.path.exists(self.caminho))
            self.assertTrue(err.startswith('ERRO: '))
            sem_marcadores(self, out, err)

    def test_sem_entrada(self):
        def eof(out):
            raise EOFError()
        codigo, out, err = self.rodar(['autorizar'], secret=SECRET, entrada=eof)
        self.assertEqual(codigo, 1)
        self.assertIn('nenhum endereço colado', err)

    def test_code_vencido(self):
        op = OpenerFalso(api_padrao(token=lambda c: erro_http(400, {'error': 'invalid_grant', 'message': CODE})))
        codigo, out, err = self.rodar(['autorizar'], op, secret=SECRET, entrada=self.colar())
        self.assertEqual(codigo, 2)
        self.assertIn('rode `ml_api.py autorizar`', err)
        self.assertFalse(os.path.exists(self.caminho))
        sem_marcadores(self, out, err)

    def test_secret_recusado(self):
        op = OpenerFalso(api_padrao(token=lambda c: erro_http(400, {'error': 'invalid_client'})))
        codigo, out, err = self.rodar(['autorizar'], op, secret=SECRET, entrada=self.colar())
        self.assertEqual(codigo, 2)
        sem_marcadores(self, out, err)

    def test_aviso_de_escrita(self):
        op = OpenerFalso(api_padrao(token=lambda c: resposta_token(1, scope='offline_access read write')))
        codigo, out, err = self.rodar(['autorizar'], op, secret=SECRET, entrada=self.colar())
        self.assertEqual(codigo, 0)
        self.assertIn('AVISO', err)
        self.assertIn('write', err)


class TestConferir(Cli):
    def test_ok_mostra_so_ok_e_escopos(self):
        self.gravar_real()
        op = OpenerFalso(api_padrao(gets=lambda c: {'id': USER, 'nickname': 'APELIDO-MARCADOR',
                                                    'email': 'dono@exemplo.com'}))
        codigo, out, err = self.rodar(['conferir'], op)
        self.assertEqual((codigo, out, err), (0, 'OK. Escopos: offline_access read\n', ''))
        self.assertEqual([(c.metodo, c.url) for c in op.chamadas], [('GET', 'https://api.mercadolibre.com/users/me')])

    def test_aviso_de_escrita(self):
        self.gravar_real(scope='offline_access read write')
        codigo, out, err = self.rodar(['conferir'])
        self.assertEqual(codigo, 0)
        self.assertIn('AVISO', err)

    def test_sem_arquivo(self):
        codigo, out, err = self.rodar(['conferir'])
        self.assertEqual((codigo, out), (2, ''))
        self.assertIn('rode `ml_api.py autorizar`', err)

    def test_arquivo_aberto(self):
        self.gravar_real()
        os.chmod(self.caminho, 0o644)
        codigo, out, err = self.rodar(['conferir'])
        self.assertEqual(codigo, 2)
        self.assertIn('chmod 600', err)

    def test_vencido_sem_secret_mostra_a_receita_do_comando(self):
        self.gravar_real(falta=10)
        codigo, out, err = self.rodar(['conferir'])
        self.assertEqual(codigo, 2)
        self.assertIn('ACHADINHOS_ML_SECRET="$S" python3 ml_api.py conferir; unset S', err)

    def test_vencido_com_secret_renova(self):
        self.gravar_real(falta=10)
        op = OpenerFalso(api_padrao())
        codigo, out, err = self.rodar(['conferir'], op, secret=SECRET)
        self.assertEqual(codigo, 0, err)
        self.assertFalse(self.secret_ficou)
        self.assertEqual(self.lido()['refresh_token'], novo(1)[1])
        sem_marcadores(self, out, err)

    def test_renovacao_fora_do_formato_sai_2_pedindo_o_autorizar(self):
        self.gravar_real(falta=10)
        for corpo, trecho in ((resposta_token(1, refresh_token=None), 'offline_access'),
                              (resposta_token(1, user_id=USER + 1), 'fora do formato')):
            op = OpenerFalso(api_padrao(token=lambda c, corpo=corpo: corpo))
            codigo, out, err = self.rodar(['conferir'], op, secret=SECRET)
            self.assertEqual(codigo, 2, err)
            self.assertIn('rode `ml_api.py autorizar`', err)
            self.assertIn(trecho, err)
            sem_marcadores(self, out, err)

    def test_invalid_grant_sai_2(self):
        self.gravar_real(falta=10)
        op = OpenerFalso(api_padrao(token=lambda c: erro_http(400, {'error': 'invalid_grant'})))
        codigo, out, err = self.rodar(['conferir'], op, secret=SECRET)
        self.assertEqual(codigo, 2)
        self.assertIn('rode `ml_api.py autorizar`', err)

    def test_saidas_dos_erros(self):
        self.gravar_real()
        casos = [(erro_http(403, {'blocked_by': 'PolicyAgent', 'code': 'PA_UNAUTHORIZED_RESULT_FROM_POLICIES'}), 2),
                 (erro_http(429, {}), 3), (erro_http(500, {'error': 'internal_error'}), 1),
                 (urllib.error.URLError(ACCESS), 1), (Resp(b'xx'), 1), (RuntimeError(f'{SECRET} {ACCESS}'), 1)]
        for resposta, saida in casos:
            op = OpenerFalso(api_padrao(gets=lambda c, r=resposta: r))
            codigo, out, err = self.rodar(['conferir'], op, secret=SECRET)
            self.assertEqual(codigo, saida, err)
            sem_marcadores(self, out, err)
            self.assertNotIn('Traceback', err)
        self.assertIn('ERRO: RuntimeError', err)


class TestSondar(Cli):
    def banco(self, ids):
        db = os.path.join(self.dir, 'banco.db')
        con = sqlite3.connect(db)
        con.execute('CREATE TABLE items (id INTEGER PRIMARY KEY, loja TEXT, item_id TEXT)')
        con.executemany('INSERT INTO items (loja, item_id) VALUES (?, ?)', ids)
        con.commit()
        con.close()
        return db

    def api(self, produto='MLB15149566', erros=None):
        erros = erros or {}
        item = {'id': 'MLB4000000001', 'title': 'TITULO-MARCADOR', 'price': 98765.43, 'original_price': 87654.32,
                'sold_quantity': 4321, 'condition': 'new', 'status': 'active', 'catalog_product_id': 'MLB777',
                'thumbnail': 'http://http2.mlstatic.com/D_MARCADOR.jpg', 'seller_id': 55555}

        def gets(c):
            for prefixo, erro in erros.items():   # erro: (status, corpo), um HTTPError novo a cada chamada
                if c.caminho.startswith(prefixo):
                    return erro_http(*erro)
            if c.caminho == '/users/me':
                return {'id': USER, 'nickname': 'APELIDO-MARCADOR'}
            if c.caminho == '/sites/MLB/search':
                return {'results': [item], 'paging': {'total': 999}}
            if c.caminho == '/products/search':
                return {'results': [{'id': produto, 'name': 'NOME-MARCADOR', 'status': 'active'}]}
            if c.caminho.startswith('/products/'):
                return {'results': [item]}
            if c.caminho == '/items/bulk':
                return [{'code': 200, 'body': item}]
            if c.caminho.startswith('/items/'):
                return item
            if c.caminho.startswith('/reviews/item/'):
                return {'rating_average': 4.87, 'paging': {'total': 321}, 'reviews': [{'content': 'TEXTO-MARCADOR'}]}
            return erro_http(404, {'error': 'not_found'})
        return OpenerFalso(api_padrao(gets=gets))

    def test_chama_os_endpoints_e_mostra_so_nomes_de_campo(self):
        self.gravar_real()
        db = self.banco([('ml', 'MLB1111111111'), ('amazon', 'B0AAAAAAAA'), ('ml', 'MLB2222222222'),
                         ('ml', 'https://produto.mercadolivre.com.br/MLB-1'), ('ml', 'MLB3333333333'),
                         ('ml', 'MLB4444444444'), ('ml', 'MLB12')])
        op = self.api()
        codigo, out, err = self.rodar(['sondar'], op, db=db)
        self.assertEqual(codigo, 0, err)
        ids = 'MLB4444444444,MLB3333333333,MLB2222222222'
        esperado = [('/users/me', {}), ('/sites/MLB/search', {'q': 'perfume', 'limit': '1'}),
                    ('/products/search', {'status': 'active', 'site_id': 'MLB', 'q': 'perfume', 'limit': '1'}),
                    ('/products/MLB15149566/items', {}), ('/items/bulk', {'ids': ids}),
                    ('/items/bulk', {'ids': ids, 'attributes': M.ATRIBUTOS_BULK}),
                    ('/items/MLB4444444444', {}), ('/reviews/item/MLB4444444444', {})]
        self.assertEqual([(c.caminho, c.query) for c in op.chamadas], esperado)
        self.assertTrue(all(c.metodo == 'GET' and c.host == 'api.mercadolibre.com' for c in op.chamadas))
        for valor in ('98765', '87654', '4321', 'TITULO', 'NOME-MARCADOR', 'APELIDO', 'mlstatic', 'D_MARCADOR',
                      '4.87', '4,87', '321', '999', 'MLB777', 'MLB15149566', 'active', 'new', '55555', 'TEXTO'):
            self.assertNotIn(valor, out + err, valor)
        sem_marcadores(self, out, err)
        palavras = set(re.findall(r'[a-z_]+', out))
        self.assertTrue({'price', 'original_price', 'sold_quantity', 'rating_average'} <= palavras)
        self.assertIn('F6 /items/bulk: 200; formato: lista de 1, chaves body, code; campos: catalog_product_id, '
                      'condition, original_price, price, sold_quantity, status, thumbnail', out)
        self.assertIn('F5 /reviews/item/{id}: 200; campos: rating_average', out)
        self.assertIn('ids do banco: MLB4444444444, MLB3333333333, MLB2222222222', out)

    def test_403_e_outros_erros_seguem_para_a_proxima(self):
        self.gravar_real()
        db = self.banco([('ml', 'MLB1111111111')])
        policy = (403, {'blocked_by': 'PolicyAgent', 'code': 'PA_UNAUTHORIZED_RESULT_FROM_POLICIES'})
        op = self.api(erros={'/sites/': (403, {'message': 'forbidden'}), '/products/': policy,
                             '/items/': policy, '/reviews/': (404, {'error': 'not_found'})})
        codigo, out, err = self.rodar(['sondar'], op, db=db)
        self.assertEqual(codigo, 0, err)
        self.assertIn('F1 /sites/MLB/search: 403 (sem código)', out)
        self.assertIn('F3 /products/search: 403 PA_UNAUTHORIZED_RESULT_FROM_POLICIES (falta permissão funcional', out)
        self.assertIn('F3 /products/{id}/items: pulado', out)
        self.assertIn('F6 /items/bulk: 403 PA_UNAUTHORIZED_RESULT_FROM_POLICIES', out)
        self.assertIn('F2 /items/{id}: 403 PA_UNAUTHORIZED_RESULT_FROM_POLICIES', out)
        self.assertIn('F5 /reviews/item/{id}: 404 not_found', out)
        self.assertEqual(len(op.chamadas), 7)

    def test_id_de_produto_estranho_nao_vira_caminho(self):
        self.gravar_real()
        for produto in ('../../users/me', 'MLB1/../x', 12345, 'MLB', None):
            op = self.api(produto=produto)
            codigo, out, err = self.rodar(['sondar'], op)
            self.assertEqual(codigo, 0, err)
            self.assertIn('F3 /products/{id}/items: pulado', out)
            self.assertFalse(any(c.caminho.startswith('/products/') and c.caminho != '/products/search'
                                 for c in op.chamadas))

    def test_sem_banco_pula_os_de_item(self):
        self.gravar_real()
        op = self.api()
        codigo, out, err = self.rodar(['sondar'], op)
        self.assertEqual(codigo, 0, err)
        self.assertIn('pulados (sem id MLB no banco)', out)
        self.assertEqual(len(op.chamadas), 4)

    def test_banco_aberto_so_para_leitura(self):
        db = self.banco([('ml', 'MLB1111111111')])
        os.chmod(db, 0o400)
        self.assertEqual(M.ids_do_banco(db), ['MLB1111111111'])
        self.assertEqual(M.ids_do_banco(os.path.join(self.dir, 'nao', 'existe.db')), [])
        self.assertFalse(os.path.exists(os.path.join(self.dir, 'nao')))
        ruim = os.path.join(self.dir, 'ruim.db')
        with open(ruim, 'w') as f:
            f.write('nao e banco')
        self.assertEqual(M.ids_do_banco(ruim), [])

    def test_limite_e_autorizacao(self):
        self.gravar_real()
        codigo, out, err = self.rodar(['sondar'], self.api(erros={'/sites/': (429, {})}))
        self.assertEqual(codigo, 3)
        self.assertTrue(err.startswith('PAROU: '))
        os.unlink(self.caminho)
        codigo, out, err = self.rodar(['sondar'], self.api())
        self.assertEqual(codigo, 2)

    def test_renovacao_fora_do_formato_para_o_sondar(self):
        """R5: não segue para o próximo endpoint (gastaria o refresh de novo); sai 2 pedindo o autorizar."""
        self.gravar_real(falta=10)
        op = OpenerFalso(api_padrao(token=lambda c: resposta_token(1, refresh_token=None)))
        codigo, out, err = self.rodar(['sondar'], op, secret=SECRET)
        self.assertEqual(codigo, 2, err)
        self.assertIn('rode `ml_api.py autorizar`', err)
        self.assertEqual((len(op.posts()), len(op.gets())), (1, 0))
        sem_marcadores(self, out, err)

    def test_401_em_todo_endpoint_renova_uma_vez(self):
        """S3: o sondar inteiro com o ML devolvendo 401 gasta o refresh uma vez só."""
        self.gravar_real()
        n = [0]

        def token(c):
            n[0] += 1
            return resposta_token(n[0])
        op = OpenerFalso(api_padrao(gets=lambda c: erro_http(401, {'error': 'invalid_token'}), token=token))
        codigo, out, err = self.rodar(['sondar'], op, secret=SECRET)
        self.assertEqual(codigo, 0, err)
        self.assertEqual(len(op.posts()), 1)
        self.assertGreaterEqual(len(op.gets()), 3)
        self.assertIn('F0 /users/me: 401 invalid_token', out)


class TestSair(Cli):
    def test_apaga_o_arquivo(self):
        self.gravar_real()
        codigo, out, err = self.rodar(['sair'])
        self.assertEqual(codigo, 0)
        self.assertFalse(os.path.exists(self.caminho))
        self.assertIn('Segurança > Aplicativos', out)

    def test_sem_arquivo(self):
        codigo, out, err = self.rodar(['sair'])
        self.assertEqual(codigo, 0)
        self.assertIn('Não havia tokens', out)
        self.assertEqual(os.listdir(self.dir), [])   # nem a trava é criada

    def test_apaga_sobras_com_ou_sem_o_arquivo(self):
        for com_arquivo in (True, False):
            if com_arquivo:
                self.gravar_real()
            sobra = os.path.join(self.dir, '.ml_tokens.json.fedcba9876543210.tmp')
            outro = os.path.join(self.dir, 'alvo-de-link.txt')
            with open(sobra, 'w') as f:
                f.write(ACCESS)
            with open(outro, 'w') as f:
                f.write('x')
            link = os.path.join(self.dir, '.ml_tokens.json.0000000000000000.tmp')
            os.symlink(outro, link)
            codigo, out, err = self.rodar(['sair'])
            self.assertEqual(codigo, 0, err)
            self.assertFalse(os.path.exists(sobra))
            self.assertFalse(os.path.exists(self.caminho))
            self.assertTrue(os.path.exists(outro))
            self.assertTrue(os.path.lexists(link))   # link não é sobra nossa: fica
            os.unlink(link)
            self.assertIn('OK: tokens' if com_arquivo else 'Não havia tokens', out)

    def test_symlink_apaga_so_o_link(self):
        alvo = os.path.join(self.dir, 'alvo.txt')
        with open(alvo, 'w') as f:
            f.write('x')
        os.symlink(alvo, self.caminho)
        codigo, out, err = self.rodar(['sair'])
        self.assertEqual(codigo, 0)
        self.assertTrue(os.path.exists(alvo))
        self.assertFalse(os.path.lexists(self.caminho))


# ---------- processos de verdade ----------
AUXILIAR = r'''
"""Roda o ml_api.main com um Opener falso que guarda o estado do "servidor do ML" num arquivo JSON."""
import fcntl, io, json, os, sys, time, urllib.error, urllib.parse
sys.path.insert(0, os.environ['RAIZ_ML'])
import ml_api as M

ESTADO = os.environ['ESTADO_FALSO']


def no_estado(f):
    with open(ESTADO + '.trava', 'a+') as t:
        fcntl.flock(t, fcntl.LOCK_EX)
        with open(ESTADO) as fp:
            e = json.load(fp)
        r = f(e)
        with open(ESTADO, 'w') as fp:
            json.dump(e, fp)
        return r


def evento(nome):
    no_estado(lambda e: e['eventos'].append([nome, os.getpid(), time.time()]))


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def erro(status, corpo):
    return urllib.error.HTTPError('https://api.mercadolibre.com/x', status, 'x', {}, io.BytesIO(json.dumps(corpo).encode()))


class Opener:
    def open(self, req, timeout=None):
        if os.environ.get('REDE_QUEBRADA'):
            raise OSError(os.environ['REDE_QUEBRADA'])
        if req.get_method() == 'POST':
            campos = dict(urllib.parse.parse_qsl(req.data.decode()))
            evento('post-inicio')

            def trocar(e):
                e['posts'].append({k: campos.get(k) for k in ('grant_type', 'code', 'code_verifier')})
                if campos['grant_type'] == 'refresh_token' and campos['refresh_token'] != e['refresh_valido']:
                    return None
                if campos['grant_type'] == 'authorization_code' and campos['code'] != e['code']:
                    return None
                e['n'] += 1
                n = e['n']
                e['refresh_valido'] = f'TG-RENOVA-NOVO-{n:04d}-dddddddddddd'
                e['acessos'].append(f'APP_USR-ACESSO-NOVO-{n:04d}-cccccccccccc')
                return {'access_token': e['acessos'][-1], 'refresh_token': e['refresh_valido'], 'expires_in': 21600,
                        'user_id': 123456789, 'scope': 'offline_access read', 'token_type': 'Bearer'}
            r = no_estado(trocar)
            time.sleep(float(os.environ.get('ATRASO_FALSO', '0')))
            evento('post-fim')
            if r is None:
                raise erro(400, {'error': 'invalid_grant'})
            return Resp(json.dumps(r).encode())
        token = (req.get_header('Authorization') or '')[len('Bearer '):]
        if token in no_estado(lambda e: e['acessos']):
            return Resp(json.dumps({'id': 123456789, 'nickname': 'APELIDO-MARCADOR'}).encode())
        raise erro(401, {'error': 'invalid_token'})


M.OPENER = Opener()
travar = M.travar


def travar_anotando(caminho):
    evento('pediu-trava')
    return travar(caminho)


M.travar = travar_anotando
codigo = M.main(sys.argv[1:])
print('SECRET-NO-AMBIENTE' if 'ACHADINHOS_ML_SECRET' in os.environ else 'SECRET-FORA-DO-AMBIENTE', flush=True)
sys.exit(codigo)
'''


class TestProcessos(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(dir=TMP)
        self.caminho = os.path.join(self.dir, 'ml_tokens.json')
        self.estado = os.path.join(self.dir, 'estado.json')
        self.auxiliar = os.path.join(self.dir, 'auxiliar.py')
        with open(self.auxiliar, 'w') as f:
            f.write(AUXILIAR)
        with open(self.estado, 'w') as f:
            json.dump({'refresh_valido': REFRESH, 'acessos': [ACCESS], 'n': 0, 'posts': [], 'eventos': [],
                       'code': CODE}, f)

    def env(self, **extra):
        env = {k: v for k, v in os.environ.items() if not k.startswith('ACHADINHOS_')}
        env.update(RAIZ_ML=RAIZ, ESTADO_FALSO=self.estado, ACHADINHOS_ML_TOKENS=self.caminho,
                   ACHADINHOS_DB=os.path.join(self.dir, 'sem.db'), PYTHONDONTWRITEBYTECODE='1')
        env.update(extra)
        return env

    def estado_lido(self):
        with open(self.estado) as f:
            return json.load(f)

    def gravar(self, falta):
        M.gravar_tokens(self.caminho, tokens(expira_em=int(time.time()) + falta))

    def test_comando_de_verdade_sem_arquivo_sai_2(self):
        env = self.env(ACHADINHOS_ML_TOKENS='/nao/existe')
        r = subprocess.run([sys.executable, os.path.join(RAIZ, 'ml_api.py'), 'conferir'], env=env,
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn('rode `ml_api.py autorizar`', r.stderr)
        self.assertNotIn('Traceback', r.stderr)

    def test_dois_processos_renovando_ao_mesmo_tempo_gastam_o_refresh_uma_vez(self):
        self.gravar(falta=10)
        env = self.env(ACHADINHOS_ML_SECRET=SECRET, ATRASO_FALSO='1.0')
        procs = [subprocess.Popen([sys.executable, self.auxiliar, 'conferir'], env=env, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True) for _ in range(2)]
        saidas = [p.communicate(timeout=60) for p in procs]
        for p, (out, err) in zip(procs, saidas):
            self.assertEqual(p.returncode, 0, err)
            self.assertIn('OK. Escopos: offline_access read', out)
            self.assertIn('SECRET-FORA-DO-AMBIENTE', out)
            sem_marcadores(self, out, err)
        e = self.estado_lido()
        self.assertEqual(len(e['posts']), 1)   # o segundo usou o token novo, sem gastar o refresh
        self.assertEqual(e['n'], 1)
        # houve concorrência de verdade: o outro pediu a trava (portanto já tinha lido o arquivo vencido)
        # antes de o POST do primeiro terminar, e só então o par novo foi gravado
        fim = [t for nome, pid, t in e['eventos'] if nome == 'post-fim'][0]
        pid_post = [pid for nome, pid, t in e['eventos'] if nome == 'post-inicio'][0]
        outros = [t for nome, pid, t in e['eventos'] if nome == 'pediu-trava' and pid != pid_post]
        self.assertTrue(any(t < fim for t in outros), e['eventos'])
        with open(self.caminho) as f:
            self.assertEqual(json.load(f)['refresh_token'], 'TG-RENOVA-NOVO-0001-dddddddddddd')

    def test_autorizar_com_stdin_de_verdade_nao_vaza_nada(self):
        env = self.env(ACHADINHOS_ML_SECRET=SECRET)
        p = subprocess.Popen([sys.executable, self.auxiliar, 'autorizar'], env=env, stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        lidas = []
        url = None
        while url is None:
            linha = p.stdout.readline()
            self.assertTrue(linha, 'o autorizar terminou sem imprimir a URL')
            lidas.append(linha)
            m = re.match(r'https://auth\.mercadolivre\.com\.br/authorization\?\S+$', linha.strip())
            url = m and m.group(0)
        state = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))['state']
        out, err = p.communicate(f'https://desejodemenina.com/ml/callback?code={CODE}&state={state}\n', timeout=30)
        out = ''.join(lidas) + out
        self.assertEqual(p.returncode, 0, err)
        self.assertIn('SECRET-FORA-DO-AMBIENTE', out)
        verifier = self.estado_lido()['posts'][0]['code_verifier']
        self.assertEqual(len(verifier), 86)
        sem_marcadores(self, out, err)
        self.assertNotIn(verifier, out + err)
        self.assertEqual(stat.S_IMODE(os.stat(self.caminho).st_mode), 0o600)
        with open(self.caminho) as f:
            self.assertEqual(json.load(f)['access_token'], 'APP_USR-ACESSO-NOVO-0001-cccccccccccc')
        self.assertNotIn(SECRET, ' '.join(p.args))   # o Secret vai pelo ambiente, nunca pelo argv

    def test_autorizar_num_terminal_de_verdade_nao_ecoa_o_endereco(self):
        """S1: num pty, o endereço colado (com o code) não volta na tela; com input() ele seria ecoado."""
        env = self.env(ACHADINHOS_ML_SECRET=SECRET)
        mestre, escravo = pty.openpty()
        try:
            p = subprocess.Popen([sys.executable, self.auxiliar, 'autorizar'], env=env, stdin=escravo,
                                 stdout=escravo, stderr=escravo, start_new_session=True)
        finally:
            os.close(escravo)
        lido = b''

        def ler_ate(cond, prazo=20):
            nonlocal lido
            fim = time.time() + prazo
            while not cond() and time.time() < fim:
                pronto, _, _ = select.select([mestre], [], [], 0.2)
                if not pronto:
                    if p.poll() is not None:
                        break
                    continue
                try:
                    bloco = os.read(mestre, 4096)
                except OSError:   # EIO: o processo fechou o terminal
                    break
                if not bloco:
                    break
                lido += bloco
        try:
            ler_ate(lambda: b'(o endere\xc3\xa7o n\xc3\xa3o aparece): ' in lido)
            m = re.search(rb'https://auth\.mercadolivre\.com\.br/authorization\?\S+', lido)
            self.assertIsNotNone(m, lido)
            state = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(m.group(0).decode()).query))['state']
            colado = f'https://desejodemenina.com/ml/callback?code={CODE}&state={state}'
            os.write(mestre, colado.encode() + b'\n')
            ler_ate(lambda: False)   # lê até o processo fechar o terminal (EIO)
            p.wait(timeout=20)
        finally:
            if p.poll() is None:
                p.kill()
                p.wait()
            os.close(mestre)
        tela = lido.decode('utf-8', 'replace')
        self.assertEqual(p.returncode, 0, tela)
        self.assertIn('OK: autorização gravada', tela)
        self.assertNotIn('desejodemenina.com/ml/callback?code', tela)
        self.assertNotIn(state, tela.split('authorization?', 1)[1].split('\n', 1)[1])   # só na URL impressa
        sem_marcadores(self, tela)

    def test_erro_de_rede_no_processo_nao_mostra_secret_nem_token(self):
        self.gravar(falta=10)
        env = self.env(ACHADINHOS_ML_SECRET=SECRET, REDE_QUEBRADA=f'{SECRET} {ACCESS} {REFRESH}')
        r = subprocess.run([sys.executable, self.auxiliar, 'conferir'], env=env, capture_output=True, text=True,
                           timeout=30)
        self.assertEqual(r.returncode, 1)
        self.assertIn('falha de rede', r.stderr)
        sem_marcadores(self, r.stdout, r.stderr)
        self.assertNotIn('Traceback', r.stderr)


# ---------- fronteiras do módulo ----------
class TestFronteiras(unittest.TestCase):
    def test_nao_importa_o_servidor_nem_log_nem_subprocesso(self):
        with open(os.path.join(RAIZ, 'ml_api.py'), encoding='utf-8') as f:
            arvore = ast.parse(f.read())
        modulos = set()
        for no in ast.walk(arvore):
            if isinstance(no, ast.Import):
                modulos.update(a.name.split('.')[0] for a in no.names)
            elif isinstance(no, ast.ImportFrom):
                modulos.add((no.module or '').split('.')[0])
        self.assertFalse(modulos & {'servidor', 'disparo', 'api_ofertas', 'logging', 'subprocess', 'requests'},
                         modulos)

    def test_tokens_nao_aparecem_no_servidor_nem_no_site(self):
        for nome in ('servidor.py', 'index.html', 'disparo.py', 'api_ofertas.py', 'genero.py'):
            with open(os.path.join(RAIZ, nome), encoding='utf-8') as f:
                texto = f.read()
            self.assertIsNone(re.search(r'ml_tokens|access_token|refresh_token', texto), nome)

    def test_gitignore(self):
        if not shutil.which('git') or not os.path.exists(os.path.join(RAIZ, '.git')):
            self.skipTest('git não encontrado ou cópia fora do repositório')
        nomes = ['ml_tokens.json', 'ml_tokens.json.lock', 'coleta_ml_feitos.txt',
                 '.ml_tokens.json.0123456789abcdef.tmp']   # sobra da escrita atômica (S2/Q1/R1)
        # sem -q: o git só aceita --quiet com um caminho
        r = subprocess.run(['git', '-C', RAIZ, 'check-ignore', *nomes], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.split(), nomes)


if __name__ == '__main__':
    unittest.main()
