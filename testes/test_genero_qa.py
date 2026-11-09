#!/usr/bin/env python3
"""Testes de QA do público (gênero) no backend (docs/produto/planos/genero-nas-categorias.md, etapas 1 a 5).

Uso:  python3 testes/test_genero_qa.py -v          (leva 1 a 2 minutos: usa uma cópia do banco real)
      python3 testes/test_genero_qa.py -k Concorrencia

Complementa test_genero.py, test_genero_servidor.py, test_disparo.py e test_api_ofertas*.py, sem repetir:
  - CA7: migração v1 -> v2 numa CÓPIA do achadinhos.db real (contagens, integrity_check, linhas de
    `items` idênticas), migração repetida, 6 processos migrando ao mesmo tempo e o código antigo
    (commit 1571135) rodando sobre o banco migrado e rodando enquanto a migração acontece. Desde a v3
    (docs/produto/planos/atualizar-precos.md) a mesma migração vai até a versão 3, que só acrescenta
    `items.preco_em` (as demais colunas de `items` seguem idênticas);
  - CA1: distribuição real da Perfumaria (com folga: a base cresce) e um oráculo independente;
  - CA4, CA5, CA6: o mesmo item tem o mesmo gênero em /api/items, na API v1 e no `elegiveis` do disparo,
    antes e depois de uma correção manual; a correção entra no cursor da v1;
  - CA5: regra gravada antes (sem `generos`) elege exatamente os mesmos itens;
  - concorrência: PUT de gênero, POST de coleta, DELETE e leituras da v1 ao mesmo tempo.

Segurança do teste: nunca toca o servidor da porta 8765 nem o achadinhos.db real (só leitura, em
`mode=ro`, para fazer a cópia com sqlite3.backup); servidores de teste usam banco temporário, porta
livre, proxy morto, ACHADINHOS_DISPARO=0 e um arquivo de token temporário (o api_token.txt do projeto
nunca é lido). Os testes que dependem do banco real dão SkipTest se o achadinhos.db não existir (clone
limpo): sem ele só restam os de banco sintético. Só biblioteca padrão.
"""
import collections
import hashlib
import http.client
import io
import json
import os
import re
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import unicodedata
import unittest
import urllib.parse
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_servidor as TS  # noqa: E402  (ambiente, porta_livre, RAIZ, DB_REAL, PROXIES_MORTOS)

TMP = tempfile.mkdtemp(prefix='achadinhos-genero-qa-')
# Antes do import: o servidor lê ACHADINHOS_DB ao carregar; a rede bate num proxy morto.
os.environ['ACHADINHOS_DB'] = os.path.join(TMP, 'import.db')
os.environ.update(TS.PROXIES_MORTOS)
os.environ.pop('ACHADINHOS_API_TOKEN_ARQUIVO', None)
sys.path.insert(0, TS.RAIZ)
import servidor as S     # noqa: E402
import disparo as D      # noqa: E402
import api_ofertas as A  # noqa: E402
import genero as G       # noqa: E402

PERF = 'Perfumes e Perfumaria'
# uma aba SEM gênero e com itens no banco real (a antiga 'Casa e Decoração' virou 'Casa, Móveis e Ferramentas')
CASA = 'Casa, Móveis e Ferramentas'
BF = 'Black Friday | Eletrônicos'
LOJAS = ('amazon', 'ml', 'shopee')
GENEROS = G.GENEROS
AGORA = datetime(2026, 11, 3, 15, 0, 0)
# Commit anterior à feature: a referência do "código antigo continua rodando sobre o banco migrado".
COMMIT_ANTIGO = '1571135'
# Distribuição da Perfumaria em 2026-11-03 (F 696, M 972, U 178, sem 1.205); a base cresce, então há folga.
DISTRIBUICAO_2026_11_03 = {'feminino': 696, 'masculino': 972, 'unissex': 178, 'sem': 1205}
FOLGA = 0.08


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


# ================================================================ apoio
def banco_real_existe():
    return os.path.exists(TS.DB_REAL)


def exigir_banco_real():
    if not banco_real_existe():
        raise unittest.SkipTest('achadinhos.db não existe neste clone: sem a cópia do banco real')


def copiar_banco_real(destino):
    """Cópia consistente (sqlite3.backup) do banco real, aberto só para leitura. Nunca escreve nele."""
    exigir_banco_real()
    origem = sqlite3.connect(f'file:{TS.DB_REAL}?mode=ro', uri=True, timeout=30)
    try:
        alvo = sqlite3.connect(destino)
        try:
            origem.backup(alvo)
        finally:
            alvo.close()
    finally:
        origem.close()


def rebaixar_para_v1(caminho):
    """Deixa a cópia como o banco real estava antes da v2: user_version 1, sem generos_manuais, regras.generos
    nem items.preco_em (v3)."""
    con = sqlite3.connect(caminho)
    try:
        if con.execute('PRAGMA user_version').fetchone()[0] >= 2:
            con.execute('DROP TABLE IF EXISTS generos_manuais')
            if 'generos' in [c[1] for c in con.execute('PRAGMA table_info(regras)')]:
                con.execute('ALTER TABLE regras DROP COLUMN generos')
            if 'preco_em' in [c[1] for c in con.execute('PRAGMA table_info(items)')]:
                con.execute('ALTER TABLE items DROP COLUMN preco_em')
            con.execute('PRAGMA user_version = 1')
            con.commit()
    finally:
        con.close()


def copia_v1(nome):
    """Cópia do banco real no estado v1, em arquivo próprio dentro de TMP."""
    caminho = os.path.join(TMP, nome + '.db')
    copiar_banco_real(caminho)
    rebaixar_para_v1(caminho)
    return caminho


def estado(caminho):
    """Retrato do banco: versão, contagens, integridade, hash das linhas de items e esquema."""
    con = sqlite3.connect(caminho, timeout=30)
    try:
        e = {'versao': con.execute('PRAGMA user_version').fetchone()[0],
             'integridade': con.execute('PRAGMA integrity_check').fetchall(),
             'fk': con.execute('PRAGMA foreign_key_check').fetchall()}
        e['contagens'] = {t: con.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
                          for t in ('items', 'numeros', 'regras', 'envios', 'config')}
        e['colunas_items'] = [(c[1], c[2], c[3], c[4]) for c in con.execute('PRAGMA table_info(items)')]
        # hash das colunas de antes da v3: a v3 só acrescenta preco_em, conferido à parte
        antigas = ','.join(c[0] for c in e['colunas_items'] if c[0] != 'preco_em')
        linhas = con.execute(f'SELECT {antigas} FROM items ORDER BY id').fetchall()
        e['hash_items'] = hashlib.sha256(repr(linhas).encode()).hexdigest()
        e['esquema'] = dict(con.execute("SELECT name, sql FROM sqlite_master WHERE type IN ('table','index')").fetchall())
        e['colunas_regras'] = [(c[1], c[2], c[3], c[4]) for c in con.execute('PRAGMA table_info(regras)')]
        e['tabelas'] = {n for (n,) in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        return e
    finally:
        con.close()


def dump(caminho):
    con = sqlite3.connect(caminho, timeout=30)
    try:
        return list(con.iterdump())
    finally:
        con.close()


def migrar_em_subprocesso(codigo, caminho, pausa_ate=None):
    """Roda o criar_banco do `codigo` sobre `caminho` (como faz o servidor e a coleta ao subir).
    `pausa_ate` (time.time()) alinha a largada de vários processos. Devolve o Popen."""
    script = ('import sys, time\n'
              'sys.path.insert(0, sys.argv[1])\n'
              'import servidor\n'
              'if sys.argv[2] != "0":\n'
              '    time.sleep(max(0, float(sys.argv[2]) - time.time()))\n'
              'servidor.criar_banco()\n')
    return subprocess.Popen([sys.executable, '-I', '-c', script, codigo, str(pausa_ate or 0)],
                            env=TS.ambiente(caminho), stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def migrar(codigo, caminho):
    p = migrar_em_subprocesso(codigo, caminho)
    out, err = p.communicate(timeout=120)
    if p.returncode != 0:
        raise AssertionError(f'a migração saiu com {p.returncode}: {err.decode(errors="replace")[-400:]}')


def relogio_dos_dados(con):
    """O instante em que todo preço do banco é "recente" (disparo.preco_recente): o maior preco_em. A trava de idade
    (atualizar-precos, CA6/S2) deixa fora preço velho e preço à frente do relógio; estes testes comparam gênero e
    elegibilidade, não a idade, então o relógio acompanha os dados (e o prazo é largo: ver prazo_largo)."""
    try:
        maior = con.execute('SELECT MAX(preco_em) FROM items').fetchone()[0]
    except sqlite3.OperationalError:   # banco de antes da v3
        maior = None
    return datetime.fromisoformat(maior) if maior else AGORA


def prazo_largo(caminho):
    """config.preco_validade_horas = 168 no banco (a cópia real passa de 24 h entre o primeiro e o último preço)."""
    con = sqlite3.connect(caminho, timeout=30)
    try:
        con.execute("INSERT OR REPLACE INTO config VALUES ('preco_validade_horas', '168')")
        con.commit()
    finally:
        con.close()


_CODIGO_ANTIGO = {}


def codigo_antigo():
    """Extrai do git (COMMIT_ANTIGO) os .py, o buscas.json e o index.html anteriores à feature."""
    if 'dir' in _CODIGO_ANTIGO:
        return _CODIGO_ANTIGO['dir']
    try:
        subprocess.run(['git', '-C', TS.RAIZ, 'cat-file', '-e', COMMIT_ANTIGO + '^{commit}'], check=True,
                       capture_output=True)
        nomes = subprocess.run(['git', '-C', TS.RAIZ, 'ls-tree', '--name-only', COMMIT_ANTIGO], check=True,
                               capture_output=True, text=True).stdout.split('\n')
        nomes = [n for n in nomes if n.endswith('.py') or n in ('buscas.json', 'index.html')]
        tar = subprocess.run(['git', '-C', TS.RAIZ, 'archive', '--format=tar', COMMIT_ANTIGO, *nomes], check=True,
                             capture_output=True).stdout
    except (OSError, subprocess.CalledProcessError) as e:
        raise unittest.SkipTest(f'sem o commit {COMMIT_ANTIGO} no git deste clone: {type(e).__name__}')
    destino = os.path.join(TMP, 'codigo-antigo')
    os.makedirs(destino)
    with tarfile.open(fileobj=io.BytesIO(tar)) as t:
        t.extractall(destino, filter='data')
    assert not os.path.exists(os.path.join(destino, 'genero.py')), 'o commit de referência já tem a feature'
    _CODIGO_ANTIGO['dir'] = destino
    return destino


def ler_index():
    with open(os.path.join(TS.RAIZ, 'index.html'), encoding='utf-8') as f:
        return f.read()


def abrir_ro(caminho):
    con = sqlite3.connect(f'file:{caminho}?mode=ro', uri=True, timeout=30)
    con.row_factory = sqlite3.Row
    return con


def req(porta, metodo, caminho, corpo=None, headers=None):
    """Requisição com conexão nova. Devolve (status, bytes). Sem asserções: serve a threads."""
    h = {'Host': f'localhost:{porta}', **(headers or {})}
    if corpo is not None and not isinstance(corpo, (bytes, str)):
        corpo = json.dumps(corpo)
        h.setdefault('Content-Type', 'application/json')
    con = http.client.HTTPConnection('127.0.0.1', porta, timeout=30)
    try:
        con.request(metodo, caminho, body=corpo, headers=h)
        r = con.getresponse()
        return r.status, r.read()
    finally:
        con.close()


def local(porta):
    return {'Origin': f'http://localhost:{porta}', 'Sec-Fetch-Site': 'same-origin'}


def amazon(asin, titulo, cat=PERF, busca='', preco='R$ 100,00'):
    return {'loja': 'amazon', 'item_id': asin, 'cat': cat, 'busca': busca,
            'url': f'https://www.amazon.com.br/dp/{asin}?tag=desejodemen01-20',
            'data': {'titulo': titulo, 'preco': preco, 'imagem': 'https://m.media-amazon.com/images/I/71teste.jpg'}}


class ServidorQa(unittest.TestCase):
    """Sobe um servidor.py (código novo ou `CODIGO` antigo) por classe, com banco temporário, porta livre,
    proxy morto, agendador desligado e token da v1 num arquivo temporário (nunca o api_token.txt)."""
    CODIGO = None       # None = código atual do projeto
    COM_TOKEN = True

    @classmethod
    def preparar_banco(cls):
        """Gancho: o banco já está em cls.db (arquivo possivelmente inexistente) e o servidor ainda não subiu."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix='achadinhos-genero-qa-srv-')
        cls.addClassCleanup(shutil.rmtree, cls.dir, ignore_errors=True)
        cls.db = os.path.join(cls.dir, 'teste.db')
        cls.token = secrets.token_urlsafe(32)
        cls.arquivo_token = os.path.join(cls.dir, 'api_token.txt')
        fd = os.open(cls.arquivo_token, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as f:
            f.write(cls.token + '\n')
        cls.porta = TS.porta_livre()
        cls.preparar_banco()
        cls.log_err = open(os.path.join(cls.dir, 'stderr.log'), 'wb')
        cls.addClassCleanup(cls.log_err.close)
        env = TS.ambiente(cls.db, cls.porta)
        env['ACHADINHOS_DISPARO'] = '0'
        if cls.COM_TOKEN:
            env['ACHADINHOS_API_TOKEN_ARQUIVO'] = cls.arquivo_token
        codigo = cls.CODIGO() if callable(cls.CODIGO) else (cls.CODIGO or TS.RAIZ)
        cls.proc = subprocess.Popen([sys.executable, '-u', 'servidor.py'], cwd=codigo, env=env,
                                    stdout=subprocess.PIPE, stderr=cls.log_err)
        cls.addClassCleanup(cls.parar_servidor)
        cls.primeira_linha = cls.proc.stdout.readline().decode()
        for _ in range(200):
            try:
                socket.create_connection(('127.0.0.1', cls.porta), timeout=0.2).close()
                break
            except OSError:
                if cls.proc.poll() is not None:
                    break
                time.sleep(0.05)
        if cls.proc.poll() is not None:
            raise RuntimeError('o servidor de teste saiu: ' + cls.primeira_linha)

    @classmethod
    def parar_servidor(cls):
        if cls.proc.poll() is None:
            cls.proc.terminate()
            try:
                cls.proc.wait(5)
            except subprocess.TimeoutExpired:
                cls.proc.kill()
                cls.proc.wait()
        cls.proc.stdout.close()

    # ------------------------------------------------------------ requisições
    def pedir(self, metodo, caminho, corpo=None, escrita=True, headers=None):
        h = dict(local(self.porta)) if escrita else {}
        h.update(headers or {})
        st, dados = req(self.porta, metodo, caminho, corpo, h)
        return st, (json.loads(dados) if dados else None)

    def itens(self):
        st, d = self.pedir('GET', '/api/items', escrita=False)
        self.assertEqual(st, 200)
        return d

    def v1(self, caminho):
        st, dados = req(self.porta, 'GET', caminho, headers={'Authorization': f'Bearer {self.token}'})
        return st, json.loads(dados)

    def v1_todas(self, qs=''):
        """Todas as ofertas da v1 (ordem relevancia: o cursor é deslocamento e não tem a folga de 60 s)."""
        ofertas = []
        cursor = None
        for _ in range(80):
            q = f'{qs}&ordem=relevancia&limite=200' + (f'&cursor={cursor}' if cursor else '')
            st, corpo = self.v1('/api/v1/ofertas?' + q.lstrip('&'))
            self.assertEqual(st, 200, corpo)
            ofertas += corpo['ofertas']
            cursor = corpo['proximo']
            if cursor is None:
                return ofertas, corpo['total']
        self.fail('a paginação da v1 nunca terminou')

    def corrigir(self, iid, valor):
        return self.pedir('PUT', f'/api/items/{iid}/genero', {'genero': valor})

    def saida(self):
        self.log_err.flush()
        time.sleep(0.05)
        with open(os.path.join(self.dir, 'stderr.log'), encoding='utf-8', errors='replace') as f:
            return self.primeira_linha + f.read()

    def ids_do_banco(self, sql, *args):
        con = sqlite3.connect(self.db, timeout=30)
        try:
            return con.execute(sql, args).fetchall()
        finally:
            con.close()


# ================================================================ CA1: classificador (bordas e dados reais)
class ClassificadorBordas(unittest.TestCase):

    def test_titulo_enorme_nao_trava_nem_muda_o_resultado(self):
        base = 'Perfume Masculino ' + 'x' * 2_000_000
        t0 = time.monotonic()
        self.assertEqual(G.classificar(PERF, '', base), ('masculino', 'titulo'))
        self.assertEqual(G.classificar(PERF, '', 'a ' * 1_000_000), ('sem', ''))
        self.assertLess(time.monotonic() - t0, 10)

    def test_repeticao_patologica_de_palavras_de_genero_e_linear(self):
        t0 = time.monotonic()
        self.assertEqual(G.classificar(PERF, '', 'fem ' * 300_000)[0], 'feminino')
        self.assertEqual(G.classificar(PERF, '', ('masc fem ' * 100_000))[0], 'unissex')
        self.assertLess(time.monotonic() - t0, 10)

    def test_decomposto_composto_e_largura_total_dao_o_mesmo_resultado(self):
        for t in ('PERFUME FEMININO', 'perfume feminino', 'Perfume Ｆｅｍｉｎｉｎｏ',
                  unicodedata.normalize('NFD', 'Perfume Feminino Lancôme')):
            with self.subTest(t=t):
                self.assertEqual(G.classificar(PERF, '', t)[0], 'feminino')
        self.assertEqual(G.classificar(PERF, '', unicodedata.normalize('NFD', 'Colônia Masculina Ação'))[0], 'masculino')

    def test_barra_e_hifen_separam_palavras(self):
        self.assertEqual(G.classificar(PERF, '', 'Eau de Parfum Masculino/Feminino')[0], 'unissex')
        self.assertEqual(G.classificar(PERF, '', 'Kit Feminino-Masculino 100ml')[0], 'unissex')
        self.assertEqual(G.classificar(PERF, '', 'Colônia (Masculina) 100ml')[0], 'masculino')

    def test_palavras_parecidas_nao_casam(self):
        for t in ('Perfume Manhattan Eau de Toilette', 'Máscara Facial Hidratante', 'Mentol Roll-on Cristalino',
                  'Perfume Mandarin 50ml', 'Colônia Mentolada 100ml'):
            with self.subTest(t=t):
                self.assertEqual(G.classificar(PERF, '', t), ('sem', ''))

    def test_resultado_e_deterministico_e_nunca_inventa_valor(self):
        titulos = ['Sauvage', 'Lady Million', 'CK One', 'Perf. Fem. EDP', 'Armani Code Masc', '', 'Hidratante', 'Kit Unissex']
        for t in titulos:
            for busca in ('', 'perfume feminino', 'Natura Kaiak'):
                a, b = G.classificar(PERF, busca, t), G.classificar(PERF, busca, t)
                self.assertEqual(a, b)
                self.assertIn(a[0], GENEROS)
                self.assertEqual(a[1] == '', a[0] == 'sem', (t, busca, a))

    def test_cat_so_vale_exata(self):
        for cat in (PERF + ' ', ' ' + PERF, PERF.lower(), PERF.upper(), 'Perfumes e Perfumaria​',
                    unicodedata.normalize('NFD', 'Perfumes e Perfumaria'.replace('e P', 'é P')), None, 7, ''):
            with self.subTest(cat=cat):
                self.assertEqual(G.classificar(cat, 'perfume feminino', 'Perfume Feminino'), ('sem', ''))
                self.assertEqual(G.do_item(1, cat, '', 'Perfume Feminino', {1: 'masculino'}), ('sem', ''))


@unittest.skipUnless(banco_real_existe(), 'sem achadinhos.db neste clone')
class DistribuicaoReal(unittest.TestCase):
    """Roda o classificador sobre os itens reais (leitura, mode=ro) e compara com um oráculo independente."""

    @classmethod
    def setUpClass(cls):
        con = abrir_ro(TS.DB_REAL)
        try:
            cls.linhas = [(r['id'], r['cat'], r['busca'], r['titulo']) for r in con.execute('SELECT * FROM items')]
        finally:
            con.close()
        t0 = time.monotonic()
        cls.res = {i: G.classificar(cat, busca, tit) for i, cat, busca, tit in cls.linhas}
        cls.segundos = time.monotonic() - t0

    def perfumaria(self):
        return [(i, b, t) for i, c, b, t in self.linhas if c == PERF]

    def test_distribuicao_da_perfumaria_perto_de_2026_11_03(self):
        cont = collections.Counter(self.res[i][0] for i, _, _ in self.perfumaria())
        total = sum(cont.values())
        self.assertGreater(total, 2000)
        for g, esperado in DISTRIBUICAO_2026_11_03.items():
            with self.subTest(genero=g):
                # a base cresce: a proporção precisa ficar perto da de hoje (folga de 8% do valor)
                esperado_prop = esperado / sum(DISTRIBUICAO_2026_11_03.values())
                self.assertAlmostEqual(cont[g] / total, esperado_prop, delta=esperado_prop * FOLGA,
                                       msg=f'{g}: {cont[g]} de {total}')
        self.assertEqual(sum(cont.values()), total)

    def test_outras_abas_sao_todas_sem(self):
        fora = [(i, c) for i, c, _, _ in self.linhas if c not in G.ABAS_COM_GENERO]
        self.assertGreater(len(fora), 1000)
        for i, c in fora:
            self.assertEqual(self.res[i], ('sem', ''), c)

    def test_origem_vazia_so_no_sem(self):
        for i, (g, o) in self.res.items():
            self.assertEqual(o == '', g == 'sem')
            self.assertIn(o, ('titulo', 'busca', ''))

    def test_oraculo_independente_para_titulos_so_masculinos_ou_so_femininos(self):
        def norm(t):
            return ''.join(c for c in unicodedata.normalize('NFKD', t or '') if not unicodedata.combining(c)).lower()
        errados = []
        for i, busca, titulo in self.perfumaria():
            t = norm(titulo)
            tem_m = re.search(r'\bmasculin[oa]s?\b', t)
            tem_f = re.search(r'\bfeminin[oa]s?\b', t)
            tem_u = re.search(r'\b(?:unissex|unisex|unissexo)\b', t)
            esperado = ('unissex' if tem_u or (tem_m and tem_f) else 'masculino' if tem_m
                        else 'feminino' if tem_f else None)
            if esperado and self.res[i] != (esperado, 'titulo'):
                errados.append((i, titulo[:60], self.res[i], esperado))
        self.assertEqual(errados[:5], [])

    def test_classificar_a_base_toda_e_rapido(self):
        self.assertLess(self.segundos, 5, f'{len(self.linhas)} itens em {self.segundos:.2f} s')


# ================================================================ CA7: migração na cópia do banco real
class MigracaoNaCopiaReal(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.caminho = copia_v1('migracao-real')
        cls.antes = estado(cls.caminho)
        migrar(TS.RAIZ, cls.caminho)
        cls.depois = estado(cls.caminho)
        cls.dump1 = dump(cls.caminho)
        migrar(TS.RAIZ, cls.caminho)   # segunda vez: idempotente
        cls.dump2 = dump(cls.caminho)
        cls.depois2 = estado(cls.caminho)

    def test_ponto_de_partida_e_v1_integro(self):
        self.assertEqual(self.antes['versao'], 1)
        self.assertEqual(self.antes['integridade'], [('ok',)])
        self.assertGreater(self.antes['contagens']['items'], 1000)
        self.assertNotIn('generos_manuais', self.antes['tabelas'])
        self.assertNotIn('generos', [c[0] for c in self.antes['colunas_regras']])

    def test_vai_para_a_versao_2_e_continua_integro(self):
        self.assertEqual(self.depois['versao'], 3)   # v2 e, desde o plano atualizar-precos, a v3
        self.assertEqual(self.depois['integridade'], [('ok',)])
        self.assertEqual(self.depois['fk'], [])

    def test_nenhuma_linha_nem_contagem_muda(self):
        self.assertEqual(self.depois['contagens'], self.antes['contagens'])
        self.assertEqual(self.depois['hash_items'], self.antes['hash_items'])

    def test_so_aditiva_uma_tabela_nova_e_uma_coluna_no_fim_de_regras(self):
        self.assertEqual(self.depois['tabelas'] - self.antes['tabelas'], {'generos_manuais'})
        for nome, sql in self.antes['esquema'].items():
            if nome not in ('regras', 'items'):
                self.assertEqual(self.depois['esquema'][nome], sql, nome)
        antes, depois = self.antes['colunas_regras'], self.depois['colunas_regras']
        self.assertEqual(depois[:len(antes)], antes)
        self.assertEqual(depois[len(antes):], [('generos', 'TEXT', 1, "'[]'")])
        # v3: uma coluna no fim de items, TEXT, aceitando NULL e sem padrão
        antes, depois = self.antes['colunas_items'], self.depois['colunas_items']
        self.assertEqual(depois[:len(antes)], antes)
        self.assertEqual(depois[len(antes):], [('preco_em', 'TEXT', 0, None)])

    def test_v3_preenche_preco_em_so_com_criado_em(self):
        con = sqlite3.connect(self.caminho)
        try:
            com, sem, iguais = con.execute(
                "SELECT COUNT(preco_em), COUNT(*) - COUNT(preco_em), SUM(preco_em = criado_em) FROM items").fetchone()
            esperado = con.execute(
                "SELECT COUNT(*) FROM items WHERE tem_dados = 1 AND preco != '' AND criado_em GLOB "
                "'[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]'").fetchone()[0]
        finally:
            con.close()
        self.assertGreater(com, 1000)
        self.assertEqual((com, iguais), (esperado, esperado))
        self.assertEqual(com + sem, self.antes['contagens']['items'])

    def test_tabela_nova_nasce_vazia_e_regra_antiga_nao_existe_no_real(self):
        con = sqlite3.connect(self.caminho)
        try:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM generos_manuais').fetchone()[0], 0)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM regras WHERE generos != '[]'").fetchone()[0], 0)
        finally:
            con.close()

    def test_segunda_migracao_nao_muda_nada(self):
        self.assertEqual(self.dump2, self.dump1)
        self.assertEqual(self.depois2['versao'], 3)

    def test_check_da_tabela_nova_recusa_valor_fora_da_lista(self):
        con = sqlite3.connect(self.caminho)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                con.execute("INSERT INTO generos_manuais VALUES (1, 'infantil', '2026-11-03T10:00:00')")
        finally:
            con.close()


class MigracaoConcorrente(unittest.TestCase):

    def test_seis_processos_migrando_ao_mesmo_tempo(self):
        caminho = copia_v1('migracao-concorrente')
        antes = estado(caminho)
        largada = time.time() + 2.5
        procs = [migrar_em_subprocesso(TS.RAIZ, caminho, largada) for _ in range(6)]
        resultados = [(p.communicate(timeout=120), p.returncode) for p in procs]
        for (out, err), codigo in resultados:
            self.assertEqual(codigo, 0, err.decode(errors='replace')[-300:])
            self.assertEqual(err.decode(), '')
        depois = estado(caminho)
        self.assertEqual(depois['versao'], 3)
        self.assertEqual(depois['integridade'], [('ok',)])
        self.assertEqual(depois['hash_items'], antes['hash_items'])
        self.assertEqual([c[0] for c in depois['colunas_regras']].count('generos'), 1)
        self.assertEqual([c[0] for c in depois['colunas_items']].count('preco_em'), 1)


class CodigoAntigoDuranteAMigracao(ServidorQa):
    """O servidor antigo está no ar sobre o banco v1 quando uma coleta nova (criar_banco) migra para a v2."""
    CODIGO = staticmethod(codigo_antigo)
    COM_TOKEN = False

    @classmethod
    def preparar_banco(cls):
        copiar_banco_real(cls.db)
        rebaixar_para_v1(cls.db)

    def test_servidor_antigo_segue_servindo_antes_durante_e_depois(self):
        st, antes = self.pedir('GET', '/api/items', escrita=False)
        self.assertEqual(st, 200)
        self.assertNotIn('genero', antes[0])
        migrar(TS.RAIZ, self.db)
        self.assertEqual(estado(self.db)['versao'], 3)
        st, depois = self.pedir('GET', '/api/items', escrita=False)
        self.assertEqual((st, len(depois)), (200, len(antes)))
        st, r = self.pedir('POST', '/api/items', {'items': [amazon('QAANT00001', 'Perfume Feminino Teste Antigo')]})
        self.assertEqual(st, 200, r)
        self.assertEqual(len(self.itens()), len(antes) + 1)
        self.assertEqual(estado(self.db)['versao'], 3)
        self.assertEqual(estado(self.db)['integridade'], [('ok',)])
        self.assertNotIn('Traceback', self.saida())


class CodigoAntigoSobreBancoMigrado(ServidorQa):
    """CA7: o código do commit anterior roda sobre o banco já na v2 e não o estraga."""
    CODIGO = staticmethod(codigo_antigo)
    COM_TOKEN = False

    @classmethod
    def preparar_banco(cls):
        copiar_banco_real(cls.db)
        rebaixar_para_v1(cls.db)
        migrar(TS.RAIZ, cls.db)
        cls.antes = estado(cls.db)
        # templates para a regra criada pela API antiga
        html = ler_index()
        padrao = re.search(r'^const DEFAULT_TEMPLATES = (\{.*\});$', html, re.M).group(1)
        con = sqlite3.connect(cls.db)
        con.execute("INSERT OR REPLACE INTO config VALUES ('templates', ?)", (padrao,))
        con.commit()
        con.close()

    def test_get_traz_todos_os_itens_sem_o_campo_novo(self):
        itens = self.itens()
        self.assertEqual(len(itens), self.antes['contagens']['items'])
        self.assertTrue(all('genero' not in i for i in itens))

    def test_versao_do_esquema_nao_baixa_nem_sobe(self):
        self.assertEqual(estado(self.db)['versao'], 3)

    def test_escritas_do_codigo_antigo_funcionam_e_o_banco_segue_integro(self):
        st, r = self.pedir('POST', '/api/items', {'items': [amazon('QAANT00002', 'Perfume Masculino Antigo')]})
        self.assertEqual(st, 200, r)
        novo = next(i for i in self.itens() if i['item_id'] == 'QAANT00002')
        st, r = self.pedir('PATCH', f'/api/items/{novo["id"]}', {'data': {'titulo': 'Perfume Feminino Antigo'}})
        self.assertEqual(st, 200, r)
        st, _ = self.pedir('DELETE', f'/api/items/{novo["id"]}')
        self.assertEqual(st, 200)
        self.assertEqual(estado(self.db)['integridade'], [('ok',)])
        self.assertEqual(estado(self.db)['versao'], 3)

    def test_regra_criada_pelo_codigo_antigo_fica_com_generos_vazio_e_o_novo_le(self):
        st, n = self.pedir('POST', '/api/disparo/numeros', {'nome': 'Loja', 'telefone': '5500000000009',
                                                              'grupo_nome': 'G', 'grupo_id': '120363000000000009@g.us'})
        self.assertEqual(st, 200, n)
        st, r = self.pedir('POST', '/api/disparo/regras', {'nome': 'Antiga', 'numero_id': n['id'], 'cats': [PERF],
                                                             'template': 'Template 2', 'horarios': ['03:33']})
        self.assertEqual(st, 200, r)
        con = sqlite3.connect(self.db)
        con.row_factory = sqlite3.Row
        try:
            self.assertEqual(con.execute('SELECT generos FROM regras WHERE id=?', (r['id'],)).fetchone()[0], '[]')
            self.assertEqual(D.obter_regra(con, r['id'])['generos'], [])
            # a regra com público feita pelo código novo sobrevive a uma edição pelo antigo
            con.execute("UPDATE regras SET generos='[\"feminino\"]' WHERE id=?", (r['id'],))
            con.commit()
        finally:
            con.close()
        st, _ = self.pedir('PUT', f'/api/disparo/regras/{r["id"]}', {'nome': 'Antiga editada'})
        self.assertEqual(st, 200)
        con = sqlite3.connect(self.db)
        try:
            self.assertEqual(con.execute('SELECT generos, nome FROM regras WHERE id=?', (r['id'],)).fetchone(),
                             ('["feminino"]', 'Antiga editada'))
        finally:
            con.close()
        self.assertNotIn('Traceback', self.saida())


# ================================================================ CA5: regra antiga elege o mesmo conjunto
SCRIPT_ELEGIVEIS = r'''
import json, sqlite3, sys
from datetime import datetime
sys.path.insert(0, sys.argv[1])
import disparo as D
import servidor as S
con = sqlite3.connect('file:%s?mode=ro' % sys.argv[2], uri=True)
con.row_factory = sqlite3.Row
saida = {}
for r in D.listar_regras(con):
    info = {}
    try:   # banco migrado: o relógio acompanha os dados (a trava de idade); o código antigo ignora isto
        maior = con.execute('SELECT MAX(preco_em) FROM items').fetchone()[0]
    except sqlite3.OperationalError:
        maior = None
    agora = datetime.fromisoformat(maior) if maior else datetime(2026, 11, 3, 12, 0)
    ids = sorted(i['id'] for i in D.elegiveis(con, r, agora, S.eh_link_afiliado, info))
    saida[r['nome']] = {'ids': ids, 'casam': info['casam'], 'generos': r.get('generos')}
print(json.dumps(saida))
'''
SCRIPT_CRIAR_REGRAS = r'''
import json, sqlite3, sys
sys.path.insert(0, sys.argv[1])
import disparo as D
con = sqlite3.connect(sys.argv[2])
con.row_factory = sqlite3.Row
con.execute("INSERT OR REPLACE INTO config VALUES ('templates', ?)", (sys.argv[3],))
con.commit()
n = D.criar_numero(con, {'nome': 'L', 'telefone': '5500000000008', 'grupo_nome': 'G', 'grupo_id': '120363000000000008@g.us'})
base = {'numero_id': n['id'], 'template': 'Template 2', 'horarios': ['03:33']}
for nome, extra in json.loads(sys.argv[4]).items():
    D.criar_regra(con, {**base, 'nome': nome, **extra})
'''
REGRAS_ANTIGAS = {
    'so-perfumaria': {'cats': [PERF], 'lojas': list(LOJAS)},
    'perfumaria-e-casa': {'cats': [PERF, CASA], 'lojas': list(LOJAS)},
    'perfumaria-ml-feminino': {'cats': [PERF], 'lojas': ['ml'], 'palavras': ['feminino']},
    'eletronicos-20': {'cats': [BF], 'lojas': list(LOJAS), 'desconto_min': 20},
    'tudo-com-palavras': {'cats': [PERF, CASA, BF, 'Eletrodomésticos'], 'lojas': ['amazon', 'ml'],
                          'palavras': ['masculino', 'kit']},
}


class RegraAntigaElegeOMesmoConjunto(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.caminho = copia_v1('regra-antiga')
        antigo = codigo_antigo()
        html = ler_index()
        padrao = re.search(r'^const DEFAULT_TEMPLATES = (\{.*\});$', html, re.M).group(1)
        env = TS.ambiente(cls.caminho)
        subprocess.run([sys.executable, '-I', '-c', SCRIPT_CRIAR_REGRAS, antigo, cls.caminho, padrao,
                        json.dumps(REGRAS_ANTIGAS)], env=env, check=True, capture_output=True, timeout=120)
        cls.antes = cls.elegiveis(antigo)
        migrar(TS.RAIZ, cls.caminho)
        prazo_largo(cls.caminho)
        cls.depois = cls.elegiveis(TS.RAIZ)

    @classmethod
    def elegiveis(cls, codigo):
        r = subprocess.run([sys.executable, '-I', '-c', SCRIPT_ELEGIVEIS, codigo, cls.caminho],
                           env=TS.ambiente(cls.caminho), capture_output=True, timeout=120)
        assert r.returncode == 0, r.stderr.decode(errors='replace')[-500:]
        return json.loads(r.stdout)

    def test_as_cinco_regras_foram_criadas_pelo_codigo_antigo(self):
        self.assertEqual(set(self.antes), set(REGRAS_ANTIGAS))
        for nome in self.antes:
            self.assertIsNone(self.antes[nome]['generos'], 'o código antigo não conhece generos')

    def test_cada_regra_elege_exatamente_os_mesmos_itens_e_a_mesma_contagem(self):
        for nome in REGRAS_ANTIGAS:
            with self.subTest(regra=nome):
                self.assertEqual(self.depois[nome]['ids'], self.antes[nome]['ids'])
                self.assertEqual(self.depois[nome]['casam'], self.antes[nome]['casam'])

    def test_as_regras_de_perfumaria_tem_itens_de_verdade(self):
        for nome in ('so-perfumaria', 'perfumaria-e-casa', 'tudo-com-palavras'):
            self.assertGreater(len(self.antes[nome]['ids']), 100, nome)

    def test_depois_da_migracao_a_regra_le_generos_vazio(self):
        for nome in REGRAS_ANTIGAS:
            self.assertEqual(self.depois[nome]['generos'], [], nome)


# ================================================================ CA4, CA5, CA6: paridade nos três consumidores
class ParidadeTresConsumidores(ServidorQa):
    """O mesmo item tem o mesmo gênero em GET /api/items, na API v1 e no `elegiveis` do disparo."""

    @classmethod
    def preparar_banco(cls):
        copiar_banco_real(cls.db)   # o servidor novo migra para a v3 ao subir
        prazo_largo(cls.db)

    # ------------------------------------------------------------ apoio
    def mundo(self):
        """{id: (genero, origem, auto, cat)} do /api/items."""
        return {i['id']: (i['genero'], i['genero_origem'], i['genero_auto'], i['cat']) for i in self.itens()}

    def disparo_ids(self, cats=(PERF,), generos=()):
        con = abrir_ro(self.db)
        try:
            regra = {'numero_id': 0, 'cats': list(cats), 'lojas': list(LOJAS), 'palavras': [], 'desconto_min': 0,
                     'repetir_apos_dias': None, 'generos': list(generos)}
            return {i['id'] for i in D.elegiveis(con, regra, relogio_dos_dados(con), S.eh_link_afiliado)}
        finally:
            con.close()

    def v1_perfumaria(self):
        ofertas, _ = self.v1_todas('cat=' + urllib.parse.quote(PERF))
        return {o['id']: o for o in ofertas}

    def categorias_perfumaria(self):
        st, corpo = self.v1('/api/v1/categorias')
        self.assertEqual(st, 200)
        return next(c for c in corpo['categorias'] if c['nome'] == PERF)

    def escolher_item(self, auto, mundo, v1, disp):
        """Um item de aba com gênero, no v1 e no disparo, com o gênero automático pedido e sem correção."""
        achados = sorted(i for i, (g, o, a, c) in mundo.items()
                         if c == PERF and g == auto and o != 'manual' and i in v1 and i in disp)
        self.assertTrue(achados, f'nenhum item {auto} elegível na cópia')
        return achados[0]

    def restaurar(self, iid):
        self.corrigir(iid, None)

    # ------------------------------------------------------------ distribuição pela HTTP
    def test_distribuicao_da_perfumaria_pelo_get_items_na_copia_migrada(self):
        mundo = self.mundo()
        cont = collections.Counter(g for g, o, a, c in mundo.values() if c == PERF)
        total = sum(cont.values())
        for g, esperado in DISTRIBUICAO_2026_11_03.items():
            prop = esperado / sum(DISTRIBUICAO_2026_11_03.values())
            self.assertAlmostEqual(cont[g] / total, prop, delta=prop * FOLGA, msg=f'{g}: {cont[g]} de {total}')
        for g, o, a, c in mundo.values():
            if c not in G.ABAS_COM_GENERO:
                self.assertEqual((g, o, a), ('sem', '', 'sem'))
        self.assertEqual(self.ids_do_banco('PRAGMA user_version'), [(3,)])

    # ------------------------------------------------------------ paridade inicial
    def test_paridade_inicial_nos_tres_consumidores(self):
        mundo = self.mundo()
        v1 = self.v1_perfumaria()
        disp_todos = self.disparo_ids()
        self.assertGreater(len(v1), 1000)
        self.assertGreater(len(disp_todos), 1000)
        for i, o in v1.items():
            self.assertEqual(o['genero'], mundo[i][0], f'v1 x items no item {i}')
        for g in GENEROS:
            with self.subTest(genero=g):
                esperado = {i for i in disp_todos if mundo[i][0] == g}
                self.assertEqual(self.disparo_ids(generos=[g]), esperado)
                st, corpo = self.v1('/api/v1/ofertas?cat=' + urllib.parse.quote(PERF) + f'&genero={g}&limite=1&ordem=relevancia')
                self.assertEqual(corpo['total'], sum(1 for o in v1.values() if o['genero'] == g))
        # as quatro fatias do disparo são uma partição do conjunto sem filtro
        fatias = [self.disparo_ids(generos=[g]) for g in GENEROS]
        self.assertEqual(set().union(*fatias), disp_todos)
        self.assertEqual(sum(len(f) for f in fatias), len(disp_todos))

    def test_categorias_da_v1_batem_com_as_ofertas(self):
        v1 = self.v1_perfumaria()
        cont = collections.Counter(o['genero'] for o in v1.values())
        cat = self.categorias_perfumaria()
        self.assertEqual(set(cat['generos']), set(GENEROS))
        self.assertEqual(cat['generos'], {g: cont[g] for g in GENEROS})
        self.assertEqual(sum(cat['generos'].values()), cat['total'])

    def test_a_v1_particiona_o_total_pelos_quatro_valores(self):
        st, geral = self.v1('/api/v1/ofertas?limite=1&ordem=relevancia')
        somas = 0
        for g in GENEROS:
            st, corpo = self.v1(f'/api/v1/ofertas?genero={g}&limite=1&ordem=relevancia')
            self.assertEqual(st, 200)
            somas += corpo['total']
        self.assertEqual(somas, geral['total'])
        st, dois = self.v1('/api/v1/ofertas?genero=feminino&genero=masculino&limite=1&ordem=relevancia')
        st, f = self.v1('/api/v1/ofertas?genero=feminino&limite=1&ordem=relevancia')
        st, m = self.v1('/api/v1/ofertas?genero=masculino&limite=1&ordem=relevancia')
        self.assertEqual(dois['total'], f['total'] + m['total'])

    def test_aba_com_marcacao_mista_leva_a_casa_inteira_no_disparo_mas_a_v1_filtra_exato(self):
        casa_toda = self.disparo_ids(cats=(CASA,))
        self.assertGreater(len(casa_toda), 100)
        mundo = self.mundo()
        for g in GENEROS:
            with self.subTest(genero=g):
                mistas = self.disparo_ids(cats=(PERF, CASA), generos=[g])
                self.assertTrue(casa_toda <= mistas, 'a Casa precisa passar inteira')
                self.assertEqual(mistas - casa_toda, {i for i in self.disparo_ids() if mundo[i][0] == g})
        # na v1 o filtro é exato: 'feminino' não traz nada da Casa
        ofertas, _ = self.v1_todas('genero=feminino&cat=' + urllib.parse.quote(CASA))
        self.assertEqual(ofertas, [])
        ofertas, total = self.v1_todas('genero=sem&cat=' + urllib.parse.quote(CASA))
        self.assertGreater(total, 100)

    # ------------------------------------------------------------ correção manual
    def test_correcao_manual_vale_nos_tres_consumidores_e_volta_ao_automatico(self):
        mundo, v1, disp = self.mundo(), self.v1_perfumaria(), self.disparo_ids()
        iid = self.escolher_item('feminino', mundo, v1, disp)
        self.addCleanup(self.restaurar, iid)
        antes = self.categorias_perfumaria()['generos']
        for alvo in ('masculino', 'unissex', 'sem'):
            with self.subTest(alvo=alvo):
                st, item = self.corrigir(iid, alvo)
                self.assertEqual(st, 200, item)
                self.assertEqual((item['genero'], item['genero_origem'], item['genero_auto']), (alvo, 'manual', 'feminino'))
                self.assertEqual(self.mundo()[iid][:3], (alvo, 'manual', 'feminino'))
                self.assertEqual(self.v1_perfumaria()[iid]['genero'], alvo)
                self.assertIn(iid, self.disparo_ids(generos=[alvo]))
                for outro in GENEROS:
                    if outro != alvo:
                        self.assertNotIn(iid, self.disparo_ids(generos=[outro]), outro)
                cat = self.categorias_perfumaria()['generos']
                self.assertEqual(cat[alvo], antes[alvo] + 1)
                self.assertEqual(cat['feminino'], antes['feminino'] - 1)
        st, item = self.corrigir(iid, None)
        self.assertEqual(st, 200)
        self.assertEqual((item['genero'], item['genero_origem']), ('feminino', mundo[iid][1]))
        self.assertEqual(self.v1_perfumaria()[iid]['genero'], 'feminino')
        self.assertIn(iid, self.disparo_ids(generos=['feminino']))
        self.assertEqual(self.categorias_perfumaria()['generos'], antes)

    def test_correcao_de_item_sem_vira_feminino_nos_tres(self):
        mundo, v1, disp = self.mundo(), self.v1_perfumaria(), self.disparo_ids()
        iid = self.escolher_item('sem', mundo, v1, disp)
        self.addCleanup(self.restaurar, iid)
        st, item = self.corrigir(iid, 'feminino')
        self.assertEqual((st, item['genero'], item['genero_origem'], item['genero_auto']), (200, 'feminino', 'manual', 'sem'))
        self.assertEqual(self.v1_perfumaria()[iid]['genero'], 'feminino')
        self.assertIn(iid, self.disparo_ids(generos=['feminino']))
        self.assertNotIn(iid, self.disparo_ids(generos=['sem']))

    def test_correcao_entra_no_cursor_da_v1_como_a_unica_novidade(self):
        mundo, v1, disp = self.mundo(), self.v1_perfumaria(), self.disparo_ids()
        iid = self.escolher_item('masculino', mundo, v1, disp)
        self.addCleanup(self.restaurar, iid)
        futuro = datetime.now() + timedelta(minutes=10)
        con = abrir_ro(self.db)
        try:
            cursor, pagina = None, None
            for _ in range(80):
                pares = [('cat', PERF), ('limite', '200')] + ([('cursor', cursor)] if cursor else [])
                pagina = A.rota(con, 'GET', '/api/v1/ofertas', pares, S.eh_link_afiliado, futuro)
                if not pagina['ofertas']:
                    break
                cursor = pagina['proximo']
            self.assertIsNotNone(cursor)
        finally:
            con.close()
        st, _ = self.corrigir(iid, 'unissex')
        self.assertEqual(st, 200)
        futuro = datetime.now() + timedelta(minutes=10)
        con = abrir_ro(self.db)
        try:
            novas = A.rota(con, 'GET', '/api/v1/ofertas', [('cat', PERF), ('limite', '200'), ('cursor', cursor)],
                           S.eh_link_afiliado, futuro)
        finally:
            con.close()
        self.assertEqual([(o['id'], o['genero']) for o in novas['ofertas']], [(iid, 'unissex')])

    def test_correcao_guardada_de_outra_aba_nao_filtra_nem_vaza(self):
        """Linha de generos_manuais de um item da Casa (de uma aba que perdeu o gênero) é ignorada."""
        mundo = self.mundo()
        casa = sorted(i for i, (g, o, a, c) in mundo.items() if c == CASA)[0]
        con = sqlite3.connect(self.db, timeout=30)
        con.execute("INSERT OR REPLACE INTO generos_manuais VALUES (?, 'feminino', '2026-11-03T10:00:00')", (casa,))
        con.commit()
        con.close()

        def limpar():
            c = sqlite3.connect(self.db, timeout=30)
            c.execute('DELETE FROM generos_manuais WHERE item_pk=?', (casa,))
            c.commit()
            c.close()
        self.addCleanup(limpar)
        item = next(i for i in self.itens() if i['id'] == casa)
        self.assertEqual((item['genero'], item['genero_origem'], item['genero_auto']), ('sem', '', 'sem'))
        # o disparo com generos=['masculino'] e só a Casa marcada ainda leva o item (aba sem gênero passa inteira)
        self.assertIn(casa, self.disparo_ids(cats=(CASA,), generos=['masculino']))
        ofertas, _ = self.v1_todas('cat=' + urllib.parse.quote(CASA))
        if casa in {o['id'] for o in ofertas}:
            self.assertEqual(next(o for o in ofertas if o['id'] == casa)['genero'], 'sem')
        self.assertNotIn(casa, {o['id'] for o in self.v1_todas('genero=feminino')[0]})
        # e a correção por PUT continua negada nessa aba
        st, e = self.corrigir(casa, 'masculino')
        self.assertEqual(st, 400)
        st, ok = self.corrigir(casa, None)   # null vale em qualquer aba: apaga a guardada
        self.assertEqual(st, 200)
        self.assertEqual(self.ids_do_banco('SELECT COUNT(*) FROM generos_manuais WHERE item_pk=?', casa), [(0,)])


# ================================================================ CA6: nada do que já existia na v1 muda
SCRIPT_V1 = r"""
import json, sqlite3, sys, urllib.parse
from datetime import datetime
sys.path.insert(0, sys.argv[1])
import api_ofertas as A
import servidor as S
con = sqlite3.connect('file:%s?mode=ro' % sys.argv[2], uri=True)
con.row_factory = sqlite3.Row
con.execute('PRAGMA query_only=1')
agora = datetime(2030, 1, 1)
saida = {}
for qs in json.loads(sys.argv[3]):
    pares = urllib.parse.parse_qsl(qs, keep_blank_values=True)
    try:
        saida[qs] = A.rota(con, 'GET', '/api/v1/ofertas', pares, S.eh_link_afiliado, agora)
    except A.ErroApi as e:
        saida[qs] = {'erro': [e.codigo, e.msg]}
saida['__categorias'] = A.rota(con, 'GET', '/api/v1/categorias', [], S.eh_link_afiliado, agora)
print(json.dumps(saida))
"""
CONSULTAS_V1 = [
    '', 'limite=200', 'limite=1', 'ordem=relevancia&limite=200', 'ordem=desconto&limite=200',
    'ordem=menor_preco&limite=200', 'ordem=maior_preco&limite=200', 'ordem=cupom&limite=200',
    'ordem=recentes&limite=200', 'ordem=atualizacao&limite=200', 'cat=' + urllib.parse.quote(PERF) + '&limite=200',
    'cat=' + urllib.parse.quote(CASA) + '&cat=' + urllib.parse.quote(BF) + '&ordem=desconto&limite=100',
    'loja=ml&limite=100', 'loja=amazon&loja=shopee&ordem=relevancia&limite=100', 'q=perfume&limite=100',
    'q=perfume+importado&ordem=desconto&limite=100', 'desconto_min=30&ordem=desconto&limite=100',
    'ordem=relevancia&limite=50&cursor=50', 'ordem=atualizacao&limite=50&cursor=2020-01-01T00:00:00~0',
    # erros que já existiam: o mesmo código e a mesma frase
    'ordem=xx', 'limite=0', 'limite=201', 'limite=abc', 'desconto_min=101', 'cursor=lixo', 'q=', 'loja=xx',
    'loja=ml&loja=ml', 'cat=' + 'a' * 201, 'ordem=desconto&ordem=relevancia', 'limite=1&limite=2',
]


BELEZA = 'Beleza e Cuidados'
MODA = 'Moda e Viagem'
PETS = 'Pets'


class BelezaEModaNosTresConsumidores(ServidorQa):
    """CA5 (plano abas-nichadas-e-coleta): Beleza e Moda têm público e os três consumidores concordam.
    Banco novo só com itens sintéticos; o código de perfume vale só na perfumaria."""

    ITENS = [
        (BELEZA, 'Espuma de Barbear Gillette', 'masculino'), (BELEZA, 'Kit Pós-barba Nivea', 'masculino'),
        (BELEZA, 'Hidratante Corporal Feminino', 'feminino'), (BELEZA, 'Hidratante unissex', 'unissex'),
        (BELEZA, 'Shampoo Elseve Óleo Extraordinário', 'sem'), (BELEZA, 'Dior Sauvage Eau de Toilette', 'sem'),
        (BELEZA, 'Depilador Gillette Venus Barbear', 'sem'),
        (MODA, 'Camisa Masculina Slim', 'masculino'), (MODA, 'Vestido Feminino Longo', 'feminino'),
        (MODA, 'Chinelo unissex', 'unissex'), (MODA, 'Mala de bordo 10 kg', 'sem'),
        (MODA, 'Dior Sauvage Eau de Toilette', 'sem'),
        (PERF, 'Dior Sauvage Eau de Toilette', 'masculino'),
        (PETS, 'Coleira Masculina para Cães', 'sem'), (PETS, 'Perfume Feminino Pet', 'sem'),
    ]

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        lote = [amazon(f'B0BM{n:06d}', t, cat=c) for n, (c, t, _) in enumerate(cls.ITENS)]
        st, corpo = cls.pedir_classe('POST', '/api/items', {'items': lote})
        assert st == 200, corpo

    @classmethod
    def pedir_classe(cls, metodo, caminho, corpo):
        st, dados = req(cls.porta, metodo, caminho, corpo, local(cls.porta))
        return st, (json.loads(dados) if dados else None)

    def por_titulo(self):
        return {(i['cat'], i['data']['titulo']): i for i in self.itens()}

    def disparo_ids(self, cats, generos=()):
        con = abrir_ro(self.db)
        try:
            regra = {'numero_id': 0, 'cats': list(cats), 'lojas': list(LOJAS), 'palavras': [], 'desconto_min': 0,
                     'repetir_apos_dias': None, 'generos': list(generos)}
            return {i['id'] for i in D.elegiveis(con, regra, relogio_dos_dados(con), S.eh_link_afiliado)}
        finally:
            con.close()

    def test_get_items_traz_o_publico_esperado_e_a_linha_de_perfume_so_vale_na_perfumaria(self):
        mundo = self.por_titulo()
        for cat, titulo, esperado in self.ITENS:
            with self.subTest(cat=cat, titulo=titulo):
                self.assertEqual(mundo[(cat, titulo)]['genero'], esperado)
        for cat in (PETS,):
            for (c, t), i in mundo.items():
                if c == cat:
                    self.assertEqual((i['genero'], i['genero_origem']), ('sem', ''))

    def test_v1_ofertas_e_categorias_concordam_com_o_get_items(self):
        mundo = self.por_titulo()
        for cat in (BELEZA, MODA, PERF):
            with self.subTest(cat=cat):
                ofertas, total = self.v1_todas('cat=' + urllib.parse.quote(cat))
                esperado = {i['id']: i['genero'] for (c, t), i in mundo.items() if c == cat}
                self.assertEqual({o['id']: o['genero'] for o in ofertas}, esperado)
                for g in GENEROS:
                    st, corpo = self.v1('/api/v1/ofertas?cat=' + urllib.parse.quote(cat) + f'&genero={g}&limite=1&ordem=relevancia')
                    self.assertEqual(corpo['total'], sum(1 for v in esperado.values() if v == g), g)
        st, corpo = self.v1('/api/v1/categorias')
        cats = {c['nome']: c for c in corpo['categorias']}
        for cat in (BELEZA, MODA):
            cont = collections.Counter(i['genero'] for (c, t), i in mundo.items() if c == cat)
            self.assertEqual(cats[cat]['generos'], {g: cont[g] for g in GENEROS}, cat)
            self.assertEqual(sum(cats[cat]['generos'].values()), cats[cat]['total'])
        self.assertEqual(cats[PETS]['generos'], {'feminino': 0, 'masculino': 0, 'unissex': 0, 'sem': cats[PETS]['total']})

    def test_disparo_filtra_beleza_e_moda_e_deixa_pets_passar_inteira(self):
        mundo = self.por_titulo()
        todos = self.disparo_ids((BELEZA, MODA, PETS))
        pets = {i['id'] for (c, t), i in mundo.items() if c == PETS}
        self.assertEqual(len(pets), 2)
        for g in GENEROS:
            with self.subTest(genero=g):
                esperado = {i['id'] for (c, t), i in mundo.items() if c in (BELEZA, MODA) and i['genero'] == g} | pets
                self.assertEqual(self.disparo_ids((BELEZA, MODA, PETS), [g]), esperado)
        masc_fem = self.disparo_ids((BELEZA, MODA, PETS), ['masculino', 'feminino'])
        self.assertTrue(pets <= masc_fem)
        self.assertEqual(todos, self.disparo_ids((BELEZA, MODA, PETS), list(GENEROS)))

    def test_correcao_manual_na_moda_vale_nos_tres_e_em_pets_e_recusada(self):
        mundo = self.por_titulo()
        mala = mundo[(MODA, 'Mala de bordo 10 kg')]['id']
        self.addCleanup(self.corrigir, mala, None)
        st, item = self.corrigir(mala, 'feminino')
        self.assertEqual(st, 200, item)
        self.assertEqual((item['genero'], item['genero_origem'], item['genero_auto']), ('feminino', 'manual', 'sem'))
        ofertas, _ = self.v1_todas('cat=' + urllib.parse.quote(MODA))
        self.assertEqual(next(o for o in ofertas if o['id'] == mala)['genero'], 'feminino')
        self.assertIn(mala, self.disparo_ids((MODA,), ['feminino']))
        self.assertNotIn(mala, self.disparo_ids((MODA,), ['sem']))
        st, _ = self.corrigir(mundo[(PETS, 'Coleira Masculina para Cães')]['id'], 'masculino')
        self.assertEqual(st, 400)


class V1NadaQueExistiaMuda(unittest.TestCase):
    """O código do commit anterior e o atual respondem igual, menos o campo novo `genero` (e `generos`
    em categorias), sobre o mesmo banco real migrado."""

    @classmethod
    def setUpClass(cls):
        cls.caminho = copia_v1('v1-regressao')
        migrar(TS.RAIZ, cls.caminho)
        # A v1 atual só traz preço dentro da validade (24 h, ou config.preco_validade_horas) e o código antigo
        # não tem essa trava. Aqui se compara tudo o mais, então a cópia (descartável) ganha preço de 1 h antes
        # do relógio do script (2030-01-01) e validade de 168 h: nenhuma oferta some por idade do preço.
        con = sqlite3.connect(cls.caminho)
        try:
            con.execute("UPDATE items SET preco_em='2029-12-31T23:00:00'")
            con.execute("INSERT OR REPLACE INTO config (chave, valor) VALUES ('preco_validade_horas', '168')")
            con.commit()
        finally:
            con.close()
        cls.antigo = cls.rodar(codigo_antigo())
        cls.atual = cls.rodar(TS.RAIZ)

    @classmethod
    def rodar(cls, codigo):
        r = subprocess.run([sys.executable, '-I', '-c', SCRIPT_V1, codigo, cls.caminho, json.dumps(CONSULTAS_V1)],
                           env=TS.ambiente(cls.caminho), capture_output=True, timeout=300)
        assert r.returncode == 0, r.stderr.decode(errors='replace')[-500:]
        return json.loads(r.stdout)

    @staticmethod
    def sem_o_novo(resposta, antigo=False):
        """A resposta sem os campos novos. Com `antigo=True` (resposta do código de antes da foto grande,
        commit 7c6f3e1), `imagem` passa pelo `disparo.foto_grande`: o resto do campo continua comparado."""
        r = json.loads(json.dumps(resposta))
        for o in r.get('ofertas', []):
            o.pop('genero', None)
            o.pop('preco_em', None)   # campo da feature atualizar-precos (testes próprios)
            if antigo:
                o['imagem'] = D.foto_grande(o['imagem'], o['loja'])
        for c in r.get('categorias', []):
            c.pop('generos', None)
        return r

    def test_cada_consulta_responde_igual_menos_o_campo_novo(self):
        for qs in CONSULTAS_V1:
            with self.subTest(qs=qs[:60]):
                self.assertEqual(self.sem_o_novo(self.atual[qs]), self.sem_o_novo(self.antigo[qs], antigo=True))

    def test_a_foto_grande_e_a_unica_diferenca_de_imagem_do_codigo_antigo(self):
        """Garante que a normalização do lado antigo não esconde nada: há foto que muda, e as que não mudam
        são iguais nos dois lados."""
        antigas = {o['id']: o['imagem'] for o in self.antigo['limite=200']['ofertas']}
        novas = {o['id']: o['imagem'] for o in self.atual['limite=200']['ofertas']}
        self.assertEqual(set(antigas), set(novas))
        mudaram = [i for i in antigas if antigas[i] != novas[i]]
        self.assertGreater(len(mudaram), 20)
        for i in antigas:
            self.assertEqual(novas[i], D.foto_grande(antigas[i], next(
                o['loja'] for o in self.atual['limite=200']['ofertas'] if o['id'] == i)))

    def test_as_consultas_comparam_dados_de_verdade(self):
        self.assertGreater(len(self.atual['']['ofertas']), 40)
        self.assertGreater(self.atual['']['total'], 4000)
        self.assertEqual(self.atual['ordem=xx']['erro'][0], 400)

    def test_categorias_iguais_menos_generos(self):
        self.assertEqual(self.sem_o_novo(self.atual['__categorias']), self.sem_o_novo(self.antigo['__categorias']))
        for c in self.atual['__categorias']['categorias']:
            self.assertEqual(list(c['generos']), list(GENEROS))

    def test_oferta_ganha_so_a_chave_genero(self):
        antigas = self.antigo['']['ofertas'][0]
        novas = self.atual['']['ofertas'][0]
        self.assertEqual(set(novas) - set(antigas), {'genero', 'preco_em'})
        self.assertEqual(set(antigas) - set(novas), set())


# ================================================================ concorrência
class Concorrencia(ServidorQa):
    """PUT de gênero ao mesmo tempo que POST de coleta, DELETE e leituras da v1 e do /api/items."""

    @classmethod
    def preparar_banco(cls):
        # o servidor cria o banco; os itens entram pelo POST logo depois (setUpClass abaixo)
        pass

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        corpo = {'items': [amazon(f'CONC{n:06d}', f'Perfume Teste {n} Feminino EDP') for n in range(60)]}
        st, dados = req(cls.porta, 'POST', '/api/items', corpo, local(cls.porta))
        assert st == 200, dados
        con = sqlite3.connect(cls.db, timeout=30)   # horários antigos: a ordem "atualizacao" não esconde por folga
        con.execute("UPDATE items SET criado_em='2026-11-03T10:00:00', atualizado_em='2026-11-03T10:00:00'")
        con.commit()
        con.close()

    def ids_por_chave(self):
        return {i['item_id']: i['id'] for i in self.itens()}

    def test_put_post_delete_e_leituras_ao_mesmo_tempo(self):
        porta = self.porta
        chaves = self.ids_por_chave()
        meus = [chaves[f'CONC{n:06d}'] for n in range(0, 20)]        # termina em masculino
        voltam = [chaves[f'CONC{n:06d}'] for n in range(20, 40)]     # termina em null (automático)
        reescritos = [f'CONC{n:06d}' for n in range(0, 20)]          # a coleta regrava estes pelo POST
        erros, respostas = [], collections.Counter()
        parar = threading.Event()
        largada = threading.Barrier(5)

        def reg(msg):
            erros.append(msg)

        def put_fixos():
            largada.wait()
            for iid in meus:
                for valor in ('masculino', 'unissex', 'sem', 'feminino', 'masculino'):
                    st, d = req(porta, 'PUT', f'/api/items/{iid}/genero', {'genero': valor}, local(porta))
                    respostas[('put', st)] += 1
                    if st != 200:
                        reg(f'PUT {iid} {valor} -> {st} {d[:80]}')
                    else:
                        j = json.loads(d)
                        if (j['genero'], j['genero_origem']) != (valor, 'manual'):
                            reg(f'PUT {iid} {valor} devolveu {j["genero"]}/{j["genero_origem"]}')

        def put_voltam():
            largada.wait()
            for iid in voltam:
                for valor in ('sem', None):
                    st, d = req(porta, 'PUT', f'/api/items/{iid}/genero', {'genero': valor}, local(porta))
                    respostas[('put', st)] += 1
                    if st != 200:
                        reg(f'PUT {iid} {valor} -> {st}')

        def coleta():
            largada.wait()
            for rodada in range(15):
                lote = [amazon(f'NOVO{rodada:03d}{k:03d}', f'Perfume Novo {rodada} {k} Masculino') for k in range(10)]
                lote += [amazon(c, f'Perfume Teste Regravado v{rodada} Feminino') for c in reescritos]
                st, d = req(porta, 'POST', '/api/items', {'items': lote}, local(porta))
                respostas[('post', st)] += 1
                if st != 200:
                    reg(f'POST rodada {rodada} -> {st} {d[:80]}')

        def leitor_v1():
            largada.wait()
            while not parar.is_set():
                st, d = req(porta, 'GET', '/api/v1/ofertas?cat=' + urllib.parse.quote(PERF) + '&limite=200&ordem=relevancia',
                            headers={'Authorization': f'Bearer {self.token}'})
                respostas[('v1', st)] += 1
                if st != 200:
                    reg(f'v1 ofertas -> {st}')
                    continue
                for o in json.loads(d)['ofertas']:
                    if o['genero'] not in GENEROS:
                        reg(f'v1 genero inválido {o["genero"]!r}')
                st, d = req(porta, 'GET', '/api/v1/categorias', headers={'Authorization': f'Bearer {self.token}'})
                if st != 200:
                    reg(f'v1 categorias -> {st}')
                    continue
                for c in json.loads(d)['categorias']:   # no mesmo retrato, as quatro contagens somam o total
                    if sum(c['generos'].values()) != c['total'] or set(c['generos']) != set(GENEROS):
                        reg(f'categorias inconsistente {c["nome"]}: {c["generos"]} total {c["total"]}')

        def leitor_items():
            largada.wait()
            while not parar.is_set():
                st, d = req(porta, 'GET', '/api/items')
                respostas[('items', st)] += 1
                if st != 200:
                    reg(f'items -> {st}')
                    continue
                itens = json.loads(d)
                if len({i['id'] for i in itens}) != len(itens):
                    reg('ids repetidos no /api/items')
                for i in itens:
                    incoerente = (i['genero'] not in GENEROS or i['genero_auto'] not in GENEROS
                                  or i['genero_origem'] not in ('titulo', 'busca', 'manual', '')
                                  or (i['genero_origem'] != 'manual' and i['genero_auto'] != i['genero']))
                    if incoerente:
                        reg(f'item {i["id"]} incoerente: {i["genero"]}/{i["genero_origem"]}/{i["genero_auto"]}')
                        break

        escritores = [threading.Thread(target=f) for f in (put_fixos, put_voltam, coleta)]
        leitores = [threading.Thread(target=f) for f in (leitor_v1, leitor_items)]
        for t in escritores + leitores:
            t.start()
        for t in escritores:
            t.join(180)
        parar.set()
        for t in leitores:
            t.join(60)
        self.assertEqual([t for t in escritores + leitores if t.is_alive()], [])
        self.assertEqual(erros[:5], [])
        self.assertGreater(respostas[('v1', 200)], 0)
        self.assertGreater(respostas[('items', 200)], 0)
        self.assertEqual({k for k in respostas if k[1] != 200}, set())

        final = {i['id']: i for i in self.itens()}
        for iid in meus:
            self.assertEqual((final[iid]['genero'], final[iid]['genero_origem']), ('masculino', 'manual'), iid)
        for iid in voltam:
            self.assertEqual((final[iid]['genero'], final[iid]['genero_origem']), ('feminino', 'titulo'), iid)
        # a regravação pela coleta mantém o id e a correção (a chave do item é loja + item_id)
        self.assertEqual({k: v for k, v in self.ids_por_chave().items() if k in reescritos},
                         {k: chaves[k] for k in reescritos})
        self.assertEqual(sum(1 for i in final.values() if i['item_id'].startswith('NOVO')), 150)
        for i in final.values():
            if i['item_id'].startswith('NOVO'):
                self.assertEqual((i['genero'], i['genero_origem']), ('masculino', 'titulo'))
        # nenhuma correção órfã e só as 20 de `meus` ficaram guardadas
        orfas = self.ids_do_banco('SELECT item_pk FROM generos_manuais WHERE item_pk NOT IN (SELECT id FROM items)')
        self.assertEqual(orfas, [])
        self.assertEqual(self.ids_do_banco('SELECT COUNT(*) FROM generos_manuais'), [(20,)])
        log = self.saida()
        for ruim in ('Traceback', 'locked', 'falhou'):
            self.assertNotIn(ruim, log)

    def test_put_e_delete_do_mesmo_item_ao_mesmo_tempo_nao_deixam_correcao_orfa(self):
        porta = self.porta
        corpo = {'items': [amazon(f'RACE{n:06d}', f'Perfume Corrida {n} Masculino') for n in range(24)]}
        st, d = req(porta, 'POST', '/api/items', corpo, local(porta))
        self.assertEqual(st, 200)
        ids = [i['id'] for i in self.itens() if i['item_id'].startswith('RACE')]
        self.assertEqual(len(ids), 24)
        resultados = []
        erros = []

        def put(iid, b):
            b.wait()
            resultados.append(('put', req(porta, 'PUT', f'/api/items/{iid}/genero', {'genero': 'feminino'}, local(porta))[0]))

        def delete(iid, b):
            b.wait()
            resultados.append(('del', req(porta, 'DELETE', f'/api/items/{iid}', headers=local(porta))[0]))

        for iid in ids:
            b = threading.Barrier(2)
            ts = [threading.Thread(target=put, args=(iid, b)), threading.Thread(target=delete, args=(iid, b))]
            for t in ts:
                t.start()
            for t in ts:
                t.join(60)
        self.assertEqual(erros, [])
        self.assertEqual({st for k, st in resultados if k == 'del'}, {200})
        self.assertLessEqual({st for k, st in resultados if k == 'put'}, {200, 404})
        self.assertEqual(self.ids_do_banco('SELECT COUNT(*) FROM items WHERE item_id LIKE ?', 'RACE%'), [(0,)])
        self.assertEqual(self.ids_do_banco('SELECT item_pk FROM generos_manuais WHERE item_pk NOT IN (SELECT id FROM items)'), [])

    def test_item_recoletado_depois_de_excluido_nasce_sem_a_correcao_antiga(self):
        porta = self.porta
        item = amazon('RECOLETA001', 'Perfume Recoletado EDP')
        self.assertEqual(req(porta, 'POST', '/api/items', {'items': [item]}, local(porta))[0], 200)
        antigo = next(i['id'] for i in self.itens() if i['item_id'] == 'RECOLETA001')
        self.assertEqual(self.corrigir(antigo, 'masculino')[0], 200)
        self.assertEqual(self.pedir('DELETE', f'/api/items/{antigo}')[0], 200)
        self.assertEqual(req(porta, 'POST', '/api/items', {'items': [item]}, local(porta))[0], 200)
        novo = next(i for i in self.itens() if i['item_id'] == 'RECOLETA001')
        self.assertGreater(novo['id'], antigo, 'o id não pode ser reaproveitado (AUTOINCREMENT)')
        self.assertEqual((novo['genero'], novo['genero_origem']), ('sem', ''))


# ================================================================ bordas do PUT que os testes do dev não fixam
class BordasDoPut(ServidorQa):
    COM_TOKEN = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        st, d = req(cls.porta, 'POST', '/api/items', {'items': [amazon('BORDA00001', 'Perfume Qualquer EDP'),
                                                                 amazon('BORDA00002', 'Panela', CASA)]}, local(cls.porta))
        assert st == 200

    def iid(self, item_id):
        return next(i['id'] for i in self.itens() if i['item_id'] == item_id)

    def setUp(self):
        # um teste que falha no meio não pode deixar correção guardada para os seguintes
        self.addCleanup(self.limpar_correcoes)

    def limpar_correcoes(self):
        con = sqlite3.connect(self.db, timeout=30)
        con.execute('DELETE FROM generos_manuais')
        con.commit()
        con.close()

    def test_delete_e_patch_na_rota_de_genero_nao_apagam_nem_alteram_o_item(self):
        iid = self.iid('BORDA00001')
        for metodo in ('GET', 'DELETE', 'PATCH', 'POST'):
            st, _ = self.pedir(metodo, f'/api/items/{iid}/genero', {'genero': 'sem'})
            self.assertIn(st, (404, 405), metodo)
        self.assertIn(iid, {i['id'] for i in self.itens()})
        self.assertEqual(self.ids_do_banco('SELECT COUNT(*) FROM generos_manuais WHERE item_pk=?', iid), [(0,)])

    def test_variacoes_do_caminho_dao_404_e_nao_gravam(self):
        iid = self.iid('BORDA00001')
        for caminho in (f'/api/items/{iid}/genero/', f'/api/items/{iid}/Genero', f'/api/items//genero',
                        f'/api/items/{iid}.0/genero', f'/api/items/-{iid}/genero', f'/api/items/{iid}x/genero',
                        f'/api/items/%{iid}/genero', f'/api/items/{iid}/genero/extra', '/api/items/%D9%A3/genero'):
            with self.subTest(caminho=caminho):
                st, _ = self.pedir('PUT', caminho, {'genero': 'feminino'})
                self.assertIn(st, (400, 404), caminho)
        self.assertEqual(self.ids_do_banco('SELECT COUNT(*) FROM generos_manuais'), [(0,)])

    def test_id_com_zeros_a_esquerda_e_o_mesmo_item(self):
        iid = self.iid('BORDA00001')
        st, item = self.pedir('PUT', f'/api/items/{iid:019d}/genero', {'genero': 'feminino'})
        self.assertEqual((st, item['id'], item['genero']), (200, iid, 'feminino'))
        self.assertEqual(self.corrigir(iid, None)[0], 200)

    def test_limite_dos_ids_19_digitos_e_2_elevado_a_63(self):
        # 2^63-1 ainda cabe no INTEGER do sqlite: o PUT dá 404 (item inexistente) e o PATCH e o DELETE
        # segue o contrato de hoje (200 mesmo sem o item; o PATCH devolve null). Acima disso é 404 nas três rotas, sem 500.
        self.assertEqual(self.pedir('PUT', '/api/items/9223372036854775807/genero', {'genero': 'feminino'})[0], 404)
        self.assertEqual(self.pedir('PATCH', '/api/items/9223372036854775807', {'data': {'titulo': 'x'}}), (200, None))
        self.assertEqual(self.pedir('DELETE', '/api/items/9223372036854775807')[0], 200)
        for id_ in ('9223372036854775808', '9999999999999999999'):
            with self.subTest(id=id_):
                self.assertEqual(self.pedir('PUT', f'/api/items/{id_}/genero', {'genero': 'feminino'})[0], 404)
                self.assertEqual(self.pedir('DELETE', f'/api/items/{id_}')[0], 404)
                self.assertEqual(self.pedir('PATCH', f'/api/items/{id_}', {'data': {'titulo': 'x'}})[0], 404)
        self.assertEqual(self.pedir('PUT', '/api/items/' + '9' * 20 + '/genero', {'genero': 'feminino'})[0], 404)
        self.assertNotIn('Traceback', self.saida())

    def test_valores_quase_validos_dao_400_sem_gravar(self):
        iid = self.iid('BORDA00001')
        for valor in ('Feminino', 'FEMININO', ' feminino', 'feminino ', 'feminino\n', 'feminino\x00', 'ｆeminino',
                      'fem', '', 'infantil', 'automatico', ['feminino'], {'a': 1}, 1, 0, True, False, 1.5):
            with self.subTest(valor=valor):
                st, d = self.corrigir(iid, valor)
                self.assertEqual(st, 400, d)
        self.assertEqual(self.ids_do_banco('SELECT COUNT(*) FROM generos_manuais WHERE item_pk=?', iid), [(0,)])

    def test_corpos_estranhos_dao_400(self):
        iid = self.iid('BORDA00001')
        for corpo in ('[]', '"feminino"', 'null', '1', '{}', '{"genero": "feminino", "url": "https://evil.example/x"}',
                      '{"Genero": "feminino"}', '{"genero": "feminino", "genero_origem": "manual"}', '', '{', 'NaN',
                      '{"genero": NaN}'):
            with self.subTest(corpo=corpo):
                st, _ = req(self.porta, 'PUT', f'/api/items/{iid}/genero', corpo,
                            {**local(self.porta), 'Content-Type': 'application/json'})
                self.assertEqual(st, 400, corpo)
        self.assertEqual(self.ids_do_banco('SELECT COUNT(*) FROM generos_manuais'), [(0,)])
        item = next(i for i in self.itens() if i['id'] == iid)
        self.assertTrue(item['url'].startswith('https://www.amazon.com.br/dp/BORDA00001'))

    def test_chave_repetida_no_json_vale_a_ultima_e_so_aceita_valor_da_lista(self):
        iid = self.iid('BORDA00001')
        st, _ = req(self.porta, 'PUT', f'/api/items/{iid}/genero', '{"genero": "feminino", "genero": "golpe"}',
                    {**local(self.porta), 'Content-Type': 'application/json'})
        self.assertEqual(st, 400)
        self.assertEqual(self.ids_do_banco('SELECT COUNT(*) FROM generos_manuais'), [(0,)])

    def test_charset_e_content_type_com_parametros(self):
        iid = self.iid('BORDA00001')
        st, _ = req(self.porta, 'PUT', f'/api/items/{iid}/genero', '{"genero": "unissex"}',
                    {**local(self.porta), 'Content-Type': 'application/json; charset=utf-8'})
        self.assertEqual(st, 200)
        for ct in ('text/plain', 'application/x-www-form-urlencoded', 'application/jsonx', ''):
            with self.subTest(ct=ct):
                st, _ = req(self.porta, 'PUT', f'/api/items/{iid}/genero', '{"genero": "sem"}',
                            {**local(self.porta), 'Content-Type': ct})
                self.assertEqual(st, 415)
        self.assertEqual(self.ids_do_banco('SELECT genero FROM generos_manuais WHERE item_pk=?', iid), [('unissex',)])
        self.assertEqual(self.corrigir(iid, None)[0], 200)

    def test_preflight_do_ml_e_origens_estranhas_nao_liberam_a_rota(self):
        iid = self.iid('BORDA00001')
        for origem in ('https://lista.mercadolivre.com.br', 'https://www.mercadolivre.com.br', 'null',
                       'https://evil.example', f'http://localhost.evil.example:{self.porta}', f'http://127.0.0.1:{self.porta}.evil'):
            with self.subTest(origem=origem):
                st, dados = req(self.porta, 'PUT', f'/api/items/{iid}/genero', {'genero': 'feminino'},
                                {'Origin': origem, 'Content-Type': 'application/json'})
                self.assertEqual(st, 403)
                self.assertNotIn(b'feminino', dados)
                st, _ = req(self.porta, 'OPTIONS', f'/api/items/{iid}/genero', None,
                            {'Origin': origem, 'Access-Control-Request-Method': 'PUT'})
                self.assertIn(st, (403, 404, 405))
        self.assertEqual(self.ids_do_banco('SELECT COUNT(*) FROM generos_manuais'), [(0,)])

    def test_host_estranho_da_403_ou_nao_grava(self):
        iid = self.iid('BORDA00001')
        st, _ = req(self.porta, 'PUT', f'/api/items/{iid}/genero', {'genero': 'feminino'},
                    {'Host': 'evil.example', **local(self.porta)})
        self.assertIn(st, (400, 403, 421))
        self.assertEqual(self.ids_do_banco('SELECT COUNT(*) FROM generos_manuais'), [(0,)])

    def test_erro_nao_ecoa_o_valor_nem_o_id(self):
        iid = self.iid('BORDA00001')
        st, d = req(self.porta, 'PUT', f'/api/items/{iid}/genero', {'genero': 'SEGREDOQA77'}, local(self.porta))
        self.assertEqual(st, 400)
        self.assertNotIn(b'SEGREDOQA77', d)
        self.assertNotIn('SEGREDOQA77', self.saida())

    def test_put_em_casa_com_null_e_ok_e_valor_da_400(self):
        casa = self.iid('BORDA00002')
        st, e = self.corrigir(casa, 'feminino')
        self.assertEqual(st, 400)
        self.assertNotIn('feminino', e['error'])
        self.assertEqual(self.corrigir(casa, None)[0], 200)

    def test_put_atualiza_so_atualizado_em_do_item(self):
        iid = self.iid('BORDA00001')
        con = sqlite3.connect(self.db, timeout=30)
        con.execute("UPDATE items SET atualizado_em='2026-01-01T00:00:00' WHERE id=?", (iid,))
        con.commit()
        antes = con.execute('SELECT * FROM items WHERE id=?', (iid,)).fetchone()
        cols = [c[1] for c in con.execute('PRAGMA table_info(items)')]
        self.assertEqual(self.corrigir(iid, 'masculino')[0], 200)
        depois = con.execute('SELECT * FROM items WHERE id=?', (iid,)).fetchone()
        con.close()
        mudou = [c for c, a, b in zip(cols, antes, depois) if a != b]
        self.assertEqual(mudou, ['atualizado_em'])
        self.assertEqual(self.corrigir(iid, None)[0], 200)


if __name__ == '__main__':
    unittest.main()
