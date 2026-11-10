#!/usr/bin/env python3
"""Testes da versão do código no ar (docs/produto/planos/endurecer-engenharia-e-operacao.md, etapa 6, CA12).

Uso:  python3 testes/test_versao_servidor.py -v

Provam:
- a linha `Código <codigo> (último commit <git|?>; ...)` na subida e o GET /api/versao;
- as guardas de Host e de Origem na rota nova, que fica fora de ROTAS_ML;
- que `mudou` vira true quando um dos .py muda (sempre numa CÓPIA dos .py numa pasta temporária; os arquivos
  reais nunca são alterados) e que o index.html fica de fora;
- a leitura do commit direto do .git (refs soltos, packed-refs, HEAD destacado, .git ausente) sem sair da
  pasta .git;
- o `verificar.py --servidor` contra servidores falsos numa porta livre (nunca a 8765) e contra uma cópia
  do servidor de verdade.

Nenhum teste toca o achadinhos.db real, o servidor em 8765 ou a rede. Só biblioteca padrão.
"""
import http.client
import io
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_servidor as TS   # noqa: E402  (ambiente, porta_livre, ServidorTeste, ServidorEmProcesso, RAIZ)

sys.path.insert(0, TS.RAIZ)
import verificar as V   # noqa: E402  (não importa o servidor.py nem abre banco)

ARQUIVOS = ('servidor.py', 'disparo.py', 'genero.py', 'api_ofertas.py')
CHAVES = {'codigo', 'em_disco', 'mudou', 'git', 'iniciado_em'}
RE_CODIGO = re.compile(r'[0-9a-f]{12}')
RE_COMMIT = re.compile(r'[0-9a-f]{7}')
RE_INICIADO = re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}')
RE_LINHA = re.compile(r'Código ([0-9a-f]{12}) \(último commit ([0-9a-f]{7}|\?); pode haver mudança sem commit\)')
SHA_A = 'a1b2c3d4e5f60718293a4b5c6d7e8f9012345678'
SHA_B = 'b' * 40
SHA_FORA = 'f0f0f0f' + '0' * 33   # está num arquivo FORA do .git: se aparecer, a leitura escapou da pasta


def ler_json(dados):
    return json.loads(dados.decode())


def sem_suite(*_a, **_k):
    raise AssertionError('o --servidor rodou a suíte inteira')


def proxima_linha(proc, limite=15):
    """Próxima linha do stdout do servidor, ou '' se não vier em `limite` s (sem a linha de log, o teste
    falha em vez de ficar preso no readline). A thread acaba sozinha quando o servidor é encerrado."""
    linha = []
    t = threading.Thread(target=lambda: linha.append(proc.stdout.readline().decode()), daemon=True)
    t.start()
    t.join(limite)
    return linha[0] if linha else ''


# ================================================================ HTTP, servidor rodando do projeto

class VersaoHttp(TS.ServidorTeste):
    """GET /api/versao e a linha de log da subida, com o servidor.py do projeto (sem alterar nada nele)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.segunda_linha = proxima_linha(cls.proc)

    def versao(self, headers=None):
        st, hd, dados = self.pedir('GET', '/api/versao', headers=headers)
        return st, hd, dados

    def test_resposta_tem_o_contrato(self):
        st, hd, dados = self.versao()
        self.assertEqual(st, 200)
        self.assertEqual(hd.get('Content-Type'), 'application/json; charset=utf-8')
        j = ler_json(dados)
        self.assertEqual(set(j), CHAVES)
        self.assertRegex(j['codigo'], RE_CODIGO)
        self.assertEqual(j['em_disco'], j['codigo'])
        self.assertIs(j['mudou'], False)
        self.assertRegex(j['iniciado_em'], RE_INICIADO)
        if j['git'] is not None:
            self.assertRegex(j['git'], RE_COMMIT)

    def test_codigo_e_o_sha256_dos_quatro_arquivos(self):
        with mock.patch.dict(os.environ, {'ACHADINHOS_DB': os.path.join(self.dir, 'nao-usado.db')}):
            import servidor as S
        j = ler_json(self.versao()[2])
        self.assertEqual(S.ARQUIVOS_VERSAO, ARQUIVOS)
        self.assertEqual(j['codigo'], S.hash_do_codigo(TS.RAIZ))
        self.assertEqual(j['git'], S.commit_git(TS.RAIZ))

    def test_nao_expoe_caminho_nem_nome_do_ramo(self):
        _, _, dados = self.versao()
        texto = dados.decode()
        self.assertNotIn(TS.RAIZ, texto)
        self.assertNotIn(self.dir, texto)
        self.assertNotIn('refs/', texto)
        for chave, valor in ler_json(dados).items():
            if isinstance(valor, str):
                self.assertNotIn('/', valor, chave)

    def test_linha_de_log_na_subida(self):
        self.assertTrue(self.primeira_linha.startswith('Site em '), self.primeira_linha)
        m = RE_LINHA.fullmatch(self.segunda_linha.rstrip('\n'))
        self.assertIsNotNone(m, self.segunda_linha)
        j = ler_json(self.versao()[2])
        self.assertEqual(m.group(1), j['codigo'])
        self.assertEqual(m.group(2), j['git'] or '?')
        self.assertNotIn(TS.RAIZ, self.segunda_linha)

    def test_host_estranho_ou_ausente_da_403(self):
        ruins = [h.format(p=self.porta, p1=self.porta + 1) for h in TS.TestHost.HOSTS_RUINS]
        for host in ruins:
            with self.subTest(host=host):
                st, _, dados = self.versao({'Host': host})
                self.assertEqual(st, 403)
                self.assertNotIn(b'codigo', dados)
        st, _, _ = self.pedir('GET', '/api/versao', sem_host=True)
        self.assertEqual(st, 403)

    def test_hosts_locais_passam(self):
        for host in (f'localhost:{self.porta}', f'127.0.0.1:{self.porta}', f'LocalHost:{self.porta}'):
            with self.subTest(host=host):
                self.assertEqual(self.versao({'Host': host})[0], 200)

    def test_origem_de_fora_da_403_sem_cors(self):
        for origem in [o.format(p=self.porta) for o in TS.ORIGENS_RUINS]:
            with self.subTest(origem=origem):
                st, hd, dados = self.versao({'Origin': origem})
                self.assertEqual(st, 403)
                self.assertIsNone(hd.get('Access-Control-Allow-Origin'))
                self.assertNotIn(b'codigo', dados)

    def test_origem_do_ml_da_403_porque_a_rota_esta_fora_de_rotas_ml(self):
        for origem in (TS.ML_LISTA, TS.ML_WWW):
            with self.subTest(origem=origem):
                st, hd, dados = self.versao(TS.ml(origem))
                self.assertEqual(st, 403)
                self.assertIsNone(hd.get('Access-Control-Allow-Origin'))
                self.assertNotIn(b'codigo', dados)
                st, hd, _ = self.pedir('OPTIONS', '/api/versao', headers={
                    **TS.ml(origem), 'Access-Control-Request-Method': 'GET',
                    'Access-Control-Request-Private-Network': 'true'})
                self.assertEqual(st, 403)
                self.assertIsNone(hd.get('Access-Control-Allow-Origin'))
                self.assertIsNone(hd.get('Access-Control-Allow-Private-Network'))

    def test_sec_fetch_site_cruzado_da_403(self):
        for site in ('cross-site', 'same-site', 'Cross-Site'):
            with self.subTest(site=site):
                self.assertEqual(self.versao({'Sec-Fetch-Site': site})[0], 403)

    def test_origem_local_e_pedido_sem_navegador_passam_sem_cors(self):
        for h in ({}, self.local(), self.local('127.0.0.1'), {'Sec-Fetch-Site': 'same-origin'},
                  {'Sec-Fetch-Site': 'none'}):
            with self.subTest(h=h):
                st, hd, _ = self.versao(h)
                self.assertEqual(st, 200)
                self.assertIsNone(hd.get('Access-Control-Allow-Origin'))

    def test_so_get_responde_a_versao(self):
        for metodo in ('POST', 'PUT', 'PATCH', 'DELETE', 'HEAD'):
            with self.subTest(metodo=metodo):
                corpo = {} if metodo in ('POST', 'PUT', 'PATCH') else None
                st, _, dados = self.pedir(metodo, '/api/versao', corpo, self.local())
                self.assertNotEqual(st, 200)
                self.assertNotIn(b'codigo', dados)


# ================================================================ HTTP, servidor rodando de uma cópia

class ServidorDaCopia(unittest.TestCase):
    """Sobe o servidor.py de uma CÓPIA dos quatro .py, numa pasta temporária sem .git (o BASE do servidor é a
    pasta do próprio arquivo). Os testes mexem só na cópia."""

    COM_GIT = False

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix='achadinhos-versao-')
        cls.addClassCleanup(shutil.rmtree, cls.dir, ignore_errors=True)
        cls.copia = os.path.join(cls.dir, 'codigo')
        os.mkdir(cls.copia)
        for nome in ARQUIVOS:
            shutil.copy2(os.path.join(TS.RAIZ, nome), cls.copia)
        if cls.COM_GIT:
            git = os.path.join(cls.copia, '.git')
            os.makedirs(os.path.join(git, 'refs', 'heads'))
            with open(os.path.join(git, 'HEAD'), 'w') as f:
                f.write('ref: refs/heads/ramo\n')
            with open(os.path.join(git, 'refs', 'heads', 'ramo'), 'w') as f:
                f.write(SHA_A + '\n')
        cls.db = os.path.join(cls.dir, 'teste.db')
        cls.porta = TS.porta_livre()
        cls.log_err = open(os.path.join(cls.dir, 'stderr.log'), 'wb')
        cls.addClassCleanup(cls.log_err.close)
        cls.proc = subprocess.Popen([sys.executable, '-u', 'servidor.py'], cwd=cls.copia,
                                    env=TS.ambiente(cls.db, cls.porta), stdout=subprocess.PIPE,
                                    stderr=cls.log_err)
        cls.addClassCleanup(cls.parar)
        cls.linhas = [proxima_linha(cls.proc), proxima_linha(cls.proc)]
        for _ in range(100):
            try:
                socket.create_connection(('127.0.0.1', cls.porta), timeout=0.2).close()
                break
            except OSError:
                if cls.proc.poll() is not None:
                    break
                time.sleep(0.05)
        if cls.proc.poll() is not None:
            raise RuntimeError('o servidor da cópia saiu: ' + ''.join(cls.linhas))

    @classmethod
    def parar(cls):
        if cls.proc.poll() is None:
            cls.proc.terminate()
            try:
                cls.proc.wait(5)
            except subprocess.TimeoutExpired:
                cls.proc.kill()
                cls.proc.wait()
        cls.proc.stdout.close()

    def versao(self):
        con = http.client.HTTPConnection('127.0.0.1', self.porta, timeout=10)
        try:
            con.request('GET', '/api/versao', headers={'Host': f'localhost:{self.porta}'})
            r = con.getresponse()
            self.assertEqual(r.status, 200)
            return ler_json(r.read())
        finally:
            con.close()

    def caminho(self, nome):
        return os.path.join(self.copia, nome)

    def ler(self, nome):
        with open(self.caminho(nome), 'rb') as f:
            return f.read()

    def gravar(self, nome, dados):
        with open(self.caminho(nome), 'wb') as f:
            f.write(dados)

    def verificar(self):
        """(saída, texto) do verificar.py --servidor contra a cópia."""
        buf = io.StringIO()
        with redirect_stdout(buf), mock.patch.object(V, 'verificar', side_effect=sem_suite):
            saida = V.main(['--servidor', str(self.porta)])
        return saida, buf.getvalue()


class MudouNaCopia(ServidorDaCopia):

    def test_sem_git_o_commit_e_null_e_o_log_diz_interrogacao(self):
        self.assertFalse(os.path.exists(self.caminho('.git')))
        j = self.versao()
        self.assertIsNone(j['git'])
        self.assertIs(j['mudou'], False)
        m = RE_LINHA.fullmatch(self.linhas[1].rstrip('\n'))
        self.assertIsNotNone(m, self.linhas)
        self.assertEqual((m.group(1), m.group(2)), (j['codigo'], '?'))
        self.assertNotIn(self.dir, self.linhas[1])

    def test_mudou_vira_true_quando_qualquer_um_dos_quatro_muda_e_volta_quando_desfaz(self):
        inicio = self.versao()
        for nome in ARQUIVOS:
            with self.subTest(arquivo=nome):
                original = self.ler(nome)
                try:
                    self.gravar(nome, original + b'\n# mudanca do teste\n')
                    j = self.versao()
                    self.assertIs(j['mudou'], True)
                    self.assertEqual(j['codigo'], inicio['codigo'])
                    self.assertNotEqual(j['em_disco'], inicio['codigo'])
                    self.assertEqual(j['iniciado_em'], inicio['iniciado_em'])
                finally:
                    self.gravar(nome, original)
                j = self.versao()
                self.assertIs(j['mudou'], False)
                self.assertEqual(j['em_disco'], inicio['codigo'])

    def test_arquivo_apagado_tambem_conta_como_mudanca(self):
        # o servidor.py, que já está carregado: sem o api_ofertas.py, o servidor nem atende o /api/ (importa
        # o prefixo da v1 sob demanda)
        original = self.ler('servidor.py')
        try:
            os.remove(self.caminho('servidor.py'))
            self.assertIs(self.versao()['mudou'], True)
        finally:
            self.gravar('servidor.py', original)
        self.assertIs(self.versao()['mudou'], False)

    def test_index_html_fica_fora_do_hash(self):
        try:
            self.gravar('index.html', b'<!doctype html><title>1</title>')
            antes = self.versao()
            self.gravar('index.html', b'<!doctype html><title>2</title>')
            depois = self.versao()
        finally:
            os.remove(self.caminho('index.html'))
        self.assertIs(antes['mudou'], False)
        self.assertIs(depois['mudou'], False)
        self.assertEqual(antes['em_disco'], depois['em_disco'])

    def test_verificar_servidor_contra_a_copia_de_verdade(self):
        saida, texto = self.verificar()
        self.assertEqual(saida, 0, texto)
        self.assertIn('em dia', texto)
        original = self.ler('genero.py')
        try:
            self.gravar('genero.py', original + b'\n# mudanca do teste\n')
            saida, texto = self.verificar()
        finally:
            self.gravar('genero.py', original)
        self.assertEqual(saida, 1, texto)
        self.assertIn('reinicie', texto)


class GitNaCopia(ServidorDaCopia):
    """Com um .git falso na cópia, o commit sai na rota e no log."""

    COM_GIT = True

    def test_commit_na_rota_e_no_log(self):
        j = self.versao()
        self.assertEqual(j['git'], SHA_A[:7])
        m = RE_LINHA.fullmatch(self.linhas[1].rstrip('\n'))
        self.assertIsNotNone(m, self.linhas)
        self.assertEqual(m.group(2), SHA_A[:7])

    def test_commit_e_lido_na_subida_e_nao_a_cada_pedido(self):
        ref = os.path.join(self.copia, '.git', 'refs', 'heads', 'ramo')
        with open(ref, 'w') as f:
            f.write(SHA_B + '\n')
        try:
            self.assertEqual(self.versao()['git'], SHA_A[:7])
        finally:
            with open(ref, 'w') as f:
                f.write(SHA_A + '\n')


# ================================================================ unidade (servidor importado aqui)

class Unidade(TS.ServidorEmProcesso):

    def setUp(self):
        self.pasta = tempfile.mkdtemp(dir=self.dir)

    def escrever(self, relativo, conteudo, modo='w'):
        caminho = os.path.join(self.pasta, relativo)
        os.makedirs(os.path.dirname(caminho), exist_ok=True)
        with open(caminho, modo) as f:
            f.write(conteudo)
        return caminho


class HashDoCodigo(Unidade):

    def criar(self, conteudos):
        for nome, dados in zip(ARQUIVOS, conteudos):
            self.escrever(nome, dados, 'wb')

    def test_doze_hex_e_estavel(self):
        self.criar([b'a', b'b', b'c', b'd'])
        h = self.S.hash_do_codigo(self.pasta)
        self.assertRegex(h, RE_CODIGO)
        self.assertEqual(self.S.hash_do_codigo(self.pasta), h)

    def test_um_byte_a_mais_em_qualquer_arquivo_muda(self):
        self.criar([b'a', b'b', b'c', b'd'])
        base = self.S.hash_do_codigo(self.pasta)
        for i, nome in enumerate(ARQUIVOS):
            with self.subTest(arquivo=nome):
                self.escrever(nome, b'abcd'[i:i + 1] + b' ', 'wb')
                self.assertNotEqual(self.S.hash_do_codigo(self.pasta), base)
                self.escrever(nome, b'abcd'[i:i + 1], 'wb')
                self.assertEqual(self.S.hash_do_codigo(self.pasta), base)

    def test_bytes_que_passam_de_um_arquivo_para_outro_mudam_o_hash(self):
        self.criar([b'xy', b'', b'c', b'd'])
        um = self.S.hash_do_codigo(self.pasta)
        self.criar([b'x', b'y', b'c', b'd'])
        self.assertNotEqual(self.S.hash_do_codigo(self.pasta), um)

    def test_arquivo_ausente_nao_quebra_e_difere_do_vazio(self):
        self.criar([b'a', b'b', b'c', b''])
        vazio = self.S.hash_do_codigo(self.pasta)
        os.remove(os.path.join(self.pasta, 'api_ofertas.py'))
        ausente = self.S.hash_do_codigo(self.pasta)
        self.assertRegex(ausente, RE_CODIGO)
        self.assertNotEqual(ausente, vazio)

    def test_lista_de_arquivos_injetavel(self):
        self.escrever('outro.py', b'1', 'wb')
        a = self.S.hash_do_codigo(self.pasta, ('outro.py',))
        self.escrever('outro.py', b'2', 'wb')
        self.assertNotEqual(self.S.hash_do_codigo(self.pasta, ('outro.py',)), a)

    def test_resposta_versao_compara_com_a_subida(self):
        self.criar([b'a', b'b', b'c', b'd'])
        subida = {'codigo': self.S.hash_do_codigo(self.pasta), 'git': None, 'iniciado_em': '2026-11-09T10:00:00'}
        j = self.S.resposta_versao(subida, self.pasta)
        self.assertEqual(set(j), CHAVES)
        self.assertIs(j['mudou'], False)
        self.escrever('disparo.py', b'B', 'wb')
        j = self.S.resposta_versao(subida, self.pasta)
        self.assertIs(j['mudou'], True)
        self.assertEqual(j['codigo'], subida['codigo'])

    def test_registrar_versao_monta_a_linha(self):
        self.criar([b'a', b'b', b'c', b'd'])
        antes = self.S.VERSAO
        self.addCleanup(setattr, self.S, 'VERSAO', antes)
        linha = self.S.registrar_versao(self.pasta)
        self.assertEqual(linha, f'Código {self.S.hash_do_codigo(self.pasta)} (último commit ?; '
                                'pode haver mudança sem commit)')
        self.assertEqual(set(self.S.VERSAO), {'codigo', 'git', 'iniciado_em'})
        self.assertRegex(self.S.VERSAO['iniciado_em'], RE_INICIADO)


class CommitGit(Unidade):

    def git(self, relativo, conteudo, modo='w'):
        return self.escrever(os.path.join('.git', relativo), conteudo, modo)

    def commit(self):
        return self.S.commit_git(self.pasta)

    def fora(self):
        """Arquivo FORA do .git com um sha válido: se a leitura escapar da pasta, o teste vê SHA_FORA."""
        caminho = os.path.join(self.dir, f'fora-{id(self)}')
        with open(caminho, 'w') as f:
            f.write(SHA_FORA + '\n')
        self.addCleanup(os.remove, caminho)
        return caminho

    def test_sem_git_e_none(self):
        self.assertIsNone(self.commit())

    def test_git_como_arquivo_de_worktree_e_none(self):
        self.escrever('.git', f'gitdir: {TS.RAIZ}/.git\n')
        self.assertIsNone(self.commit())

    def test_git_como_link_e_none(self):
        real = os.path.join(self.dir, f'git-real-{id(self)}')
        os.makedirs(os.path.join(real, 'refs', 'heads'))
        self.addCleanup(shutil.rmtree, real, ignore_errors=True)
        with open(os.path.join(real, 'HEAD'), 'w') as f:
            f.write(SHA_A + '\n')
        os.symlink(real, os.path.join(self.pasta, '.git'))
        self.assertIsNone(self.commit())

    def test_ref_solto(self):
        self.git('HEAD', 'ref: refs/heads/garimpo-feminino\n')
        self.git('refs/heads/garimpo-feminino', SHA_A + '\n')
        self.assertEqual(self.commit(), SHA_A[:7])

    def test_ref_com_barra_no_nome_do_ramo(self):
        self.git('HEAD', 'ref: refs/heads/dev/etapa-6\n')
        self.git('refs/heads/dev/etapa-6', SHA_A + '\n')
        self.assertEqual(self.commit(), SHA_A[:7])

    def test_packed_refs_com_comentario_e_linha_descascada(self):
        self.git('HEAD', 'ref: refs/heads/main\n')
        os.makedirs(os.path.join(self.pasta, '.git', 'refs', 'heads'))
        self.git('packed-refs', '# pack-refs with: peeled fully-sorted sorted\n'
                                f'{SHA_B} refs/heads/mainx\n'
                                f'{SHA_B} refs/heads/outro\n'
                                f'{SHA_A} refs/heads/main\n'
                                f'^{SHA_B}\n'
                                f'{SHA_B} refs/tags/v1\n')
        self.assertEqual(self.commit(), SHA_A[:7])

    def test_ref_solto_vale_mais_que_o_packed_refs(self):
        self.git('HEAD', 'ref: refs/heads/main\n')
        self.git('refs/heads/main', SHA_A + '\n')
        self.git('packed-refs', f'{SHA_B} refs/heads/main\n')
        self.assertEqual(self.commit(), SHA_A[:7])

    def test_ramo_sem_commit_e_none(self):
        self.git('HEAD', 'ref: refs/heads/novo\n')
        self.git('packed-refs', f'{SHA_B} refs/heads/main\n')
        self.assertIsNone(self.commit())

    def test_head_destacado_sha1_e_sha256(self):
        self.git('HEAD', SHA_A + '\n')
        self.assertEqual(self.commit(), SHA_A[:7])
        self.git('HEAD', 'c' * 64 + '\n')
        self.assertEqual(self.commit(), 'c' * 7)

    def test_conteudo_malformado_e_none(self):
        for head, ref in (('ref: refs/heads/x\n', 'nao e sha\n'), ('ref: refs/heads/x\n', SHA_A[:39] + '\n'),
                          ('ref: refs/heads/x\n', 'ref: refs/heads/y\n'), ('xyz\n', None), ('', None),
                          ('ref:\n', None), ('ref: \n', None), (SHA_A.upper() + '\n', None)):
            with self.subTest(head=head, ref=ref):
                shutil.rmtree(os.path.join(self.pasta, '.git'), ignore_errors=True)
                self.git('HEAD', head)
                if ref is not None:
                    self.git('refs/heads/x', ref)
                self.assertIsNone(self.commit())

    def test_bytes_que_nao_sao_ascii_e_none(self):
        self.git('HEAD', b'ref: refs/heads/\xc3\xa7\xff\n', 'wb')
        self.assertIsNone(self.commit())

    def test_arquivo_grande_demais_e_none(self):
        self.git('HEAD', 'ref: refs/heads/x\n')
        self.git('refs/heads/x', SHA_A + '\n' + ' ' * 5000)
        self.assertIsNone(self.commit())

    def test_ref_que_sai_do_git_nao_e_seguido(self):
        fora = self.fora()
        relativo = os.path.relpath(fora, os.path.join(self.pasta, '.git'))   # ../../fora-...
        for alvo in (relativo, fora, 'refs/../../' + os.path.basename(fora), 'refs/heads/../../../' + relativo,
                     'refs//heads/x', 'refs/heads/.oculto', 'refs/heads/x.lock', 'refs/heads/x/', 'HEAD',
                     'config', 'refs/heads/x y'):
            with self.subTest(alvo=alvo):
                shutil.rmtree(os.path.join(self.pasta, '.git'), ignore_errors=True)
                self.git('HEAD', f'ref: {alvo}\n')
                self.git('config', SHA_FORA + '\n')
                self.git('refs/heads/x.lock', SHA_FORA + '\n')
                self.git('refs/heads/.oculto', SHA_FORA + '\n')
                self.assertIsNone(self.commit())

    def test_ref_solto_que_e_link_para_fora_nao_e_seguido(self):
        fora = self.fora()
        self.git('HEAD', 'ref: refs/heads/x\n')
        os.makedirs(os.path.join(self.pasta, '.git', 'refs', 'heads'))
        os.symlink(fora, os.path.join(self.pasta, '.git', 'refs', 'heads', 'x'))
        self.assertIsNone(self.commit())

    def test_pasta_refs_que_e_link_para_fora_nao_e_seguida(self):
        fora = self.fora()
        pasta_fora = os.path.join(self.dir, f'refs-fora-{id(self)}')
        os.makedirs(os.path.join(pasta_fora, 'heads'))
        self.addCleanup(shutil.rmtree, pasta_fora, ignore_errors=True)
        shutil.copy(fora, os.path.join(pasta_fora, 'heads', 'x'))
        self.git('HEAD', 'ref: refs/heads/x\n')
        os.symlink(pasta_fora, os.path.join(self.pasta, '.git', 'refs'))
        self.assertIsNone(self.commit())

    def test_head_que_e_link_para_fora_nao_e_seguido(self):
        fora = self.fora()
        os.makedirs(os.path.join(self.pasta, '.git'))
        os.symlink(fora, os.path.join(self.pasta, '.git', 'HEAD'))
        self.assertIsNone(self.commit())

    def test_packed_refs_que_e_link_para_fora_nao_e_seguido(self):
        caminho = os.path.join(self.dir, f'packed-fora-{id(self)}')
        with open(caminho, 'w') as f:
            f.write(f'{SHA_FORA} refs/heads/main\n')
        self.addCleanup(os.remove, caminho)
        self.git('HEAD', 'ref: refs/heads/main\n')
        os.symlink(caminho, os.path.join(self.pasta, '.git', 'packed-refs'))
        self.assertIsNone(self.commit())

    def test_link_dentro_do_git_e_aceito(self):
        self.git('HEAD', 'ref: refs/heads/x\n')
        self.git('refs/heads/y', SHA_A + '\n')
        os.symlink('y', os.path.join(self.pasta, '.git', 'refs', 'heads', 'x'))
        self.assertEqual(self.commit(), SHA_A[:7])

    def test_repositorio_real_bate_com_o_git(self):
        if not shutil.which('git') or not os.path.isdir(os.path.join(TS.RAIZ, '.git')):
            self.skipTest('sem git ou sem .git no projeto')
        r = subprocess.run(['git', 'rev-parse', '--short=7', 'HEAD'], cwd=TS.RAIZ, capture_output=True,
                           text=True, timeout=30)
        if r.returncode != 0:
            self.skipTest('git rev-parse falhou')
        self.assertEqual(self.S.commit_git(TS.RAIZ), r.stdout.strip())

    def test_o_servidor_nao_usa_subprocess(self):
        with open(os.path.join(TS.RAIZ, 'servidor.py'), encoding='utf-8') as f:
            fonte = f.read()
        self.assertNotRegex(fonte, r'(?m)^\s*(import|from)\s+subprocess\b|\bsubprocess\.')
        self.assertNotRegex(fonte, r'\bos\.(system|popen|exec\w*|spawn\w*)\b')


class RotaUnidade(Unidade):

    def test_rota_fora_de_rotas_ml(self):
        self.assertIsNone(self.S.ROTAS_ML.match('/api/versao'))
        self.assertFalse(self.S.eh_rota_v1('/api/versao'))

    def test_sem_registro_na_subida_responde_503(self):
        """Importado como módulo (sem o __main__), não há versão da subida: 503, nunca um "em dia" falso."""
        self.assertIsNone(self.S.VERSAO)

        class Quieto(self.S.Handler):
            def log_message(self, *a):
                pass
        srv = ThreadingHTTPServer(('127.0.0.1', self.S.PORT), Quieto)
        self.addCleanup(srv.server_close)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        con = http.client.HTTPConnection('127.0.0.1', self.S.PORT, timeout=10)
        try:
            con.request('GET', '/api/versao', headers={'Host': f'localhost:{self.S.PORT}'})
            r = con.getresponse()
            self.assertEqual(r.status, 503)
            self.assertNotIn('codigo', ler_json(r.read()))
        finally:
            con.close()


# ================================================================ verificar.py --servidor

class Falso(BaseHTTPRequestHandler):
    """Servidor falso: responde ao GET com o (status, corpo) da classe e anota cada pedido."""
    resposta = (404, b'{"error": "rota n\\u00e3o encontrada"}')
    pedidos = None

    def do_GET(self):
        self.pedidos.append(('GET', self.path, self.headers.get('Host'), self.headers.get('Content-Length')))
        status, corpo = self.resposta
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def do_POST(self):
        self.pedidos.append(('POST', self.path, None, None))
        self.send_response(405)
        self.end_headers()

    def log_message(self, *a):
        pass


def corpo_versao(mudou, codigo='abcdef012345', em_disco=None, git='c49e672'):
    return json.dumps({'codigo': codigo, 'em_disco': em_disco or (codigo if not mudou else '999999999999'),
                       'mudou': mudou, 'git': git, 'iniciado_em': '2026-11-09T15:00:00'}).encode()


class VerificarServidor(unittest.TestCase):

    def subir(self, status, corpo):
        pedidos = []
        handler = type('F', (Falso,), {'resposta': (status, corpo), 'pedidos': pedidos})
        srv = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        self.addCleanup(srv.server_close)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        return srv.server_address[1], pedidos

    def rodar(self, argv):
        # a suíte trocada por um falso que falha: se o --servidor deixasse de desviar, este teste rodaria
        # a suíte inteira (que roda este arquivo de novo)
        buf = io.StringIO()
        with redirect_stdout(buf), mock.patch.object(V, 'verificar', side_effect=sem_suite):
            saida = V.main(argv)
        return saida, buf.getvalue()

    def caso(self, status, corpo):
        porta, pedidos = self.subir(status, corpo)
        self.assertNotEqual(porta, V.PORTA_REAL)
        saida, texto = self.rodar(['--servidor', str(porta)])
        self.assertEqual(pedidos, [('GET', '/api/versao', f'localhost:{porta}', None)],
                         'o --servidor faz um GET só, sem corpo, com o Host local')
        return saida, texto

    def test_em_dia_sai_com_0(self):
        saida, texto = self.caso(200, corpo_versao(False))
        self.assertEqual(saida, 0, texto)
        self.assertIn('em dia', texto)
        self.assertIn('abcdef012345', texto)
        self.assertIn('c49e672', texto)
        self.assertNotIn('reinicie', texto)

    def test_mudou_sai_com_1_e_manda_reiniciar(self):
        saida, texto = self.caso(200, corpo_versao(True))
        self.assertEqual(saida, 1, texto)
        self.assertIn('reinicie', texto)
        self.assertIn('mudou', texto)

    def test_sem_a_rota_e_servidor_anterior(self):
        saida, texto = self.caso(404, b'{"error": "rota n\\u00e3o encontrada"}')
        self.assertEqual(saida, 1, texto)
        self.assertIn('servidor anterior a esta versão: reinicie', texto)

    def test_fora_do_ar_sai_com_1(self):
        porta = TS.porta_livre()   # ninguém escuta nela
        saida, texto = self.rodar(['--servidor', str(porta)])
        self.assertEqual(saida, 1, texto)
        self.assertIn('fora do ar', texto)
        self.assertIn(str(porta), texto)

    def test_git_null_vira_interrogacao(self):
        saida, texto = self.caso(200, corpo_versao(False, git=None))
        self.assertEqual(saida, 0, texto)
        self.assertIn('último commit ?', texto)

    def test_resposta_estranha_sai_com_1(self):
        casos = [(200, b'nao e json'), (200, b'[]'), (200, b'{}'),
                 (200, json.dumps({'codigo': 'a', 'em_disco': 'a', 'mudou': 'false'}).encode()),
                 (200, json.dumps({'codigo': 'a', 'em_disco': 'a', 'mudou': None}).encode()),
                 (200, b'{"mudou": false, "codigo": "a", "em_disco": "a", "x": "' + b'y' * 70000 + b'"}'),
                 # JSON válido nos primeiros 64 KB, mas a resposta passa do teto: não vale como "em dia"
                 (200, corpo_versao(False) + b' ' * 70000),
                 (403, b'{"error": "host n\\u00e3o permitido"}'), (500, b'{}'), (503, b'{}')]
        for status, corpo in casos:
            with self.subTest(status=status, corpo=corpo[:40]):
                saida, texto = self.caso(status, corpo)
                self.assertEqual(saida, 1, texto)
                self.assertNotIn('em dia', texto)
                self.assertIn('reinicie', texto)
                if status != 200:
                    self.assertIn(f'HTTP {status}', texto)

    def test_pela_linha_de_comando_de_verdade(self):
        """Num processo à parte, o código de saída chega ao sistema (o sys.exit(main()) do verificar.py). A
        suíte fica trocada por uma saída 99: se o --servidor a rodasse, este teste a rodaria de novo."""
        codigo = ('import sys; sys.path.insert(0, sys.argv[1]); import verificar as V; '
                  'V.verificar = lambda a: sys.exit(99); sys.exit(V.main(sys.argv[2:]))')
        for status, corpo, esperado in ((200, corpo_versao(False), 0), (200, corpo_versao(True), 1),
                                        (404, b'{}', 1)):
            with self.subTest(status=status, esperado=esperado):
                porta, pedidos = self.subir(status, corpo)
                r = subprocess.run([sys.executable, '-c', codigo, TS.RAIZ, '--servidor', str(porta)],
                                   capture_output=True, text=True, timeout=60, env=TS.ambiente(
                                       os.path.join(tempfile.gettempdir(), 'nao-usado.db')))
                self.assertEqual(r.returncode, esperado, r.stdout + r.stderr)
                self.assertNotIn('logs em', r.stdout)
                self.assertEqual(len(pedidos), 1)

    def test_porta_padrao_e_a_8765_sem_conectar(self):
        self.assertEqual(V.ler_argumentos(['--servidor']).servidor, 8765)
        self.assertEqual(V.ler_argumentos(['--servidor', '8766']).servidor, 8766)
        self.assertIsNone(V.ler_argumentos([]).servidor)

    def test_sem_servidor_a_suite_nao_passa_pela_versao(self):
        with mock.patch.object(V, 'conferir_servidor') as conferir, \
                mock.patch.object(V, 'verificar', return_value=0) as suite:
            self.assertEqual(V.main(['--rapido']), 0)
        conferir.assert_not_called()
        suite.assert_called_once()

    def test_com_servidor_nao_roda_a_suite(self):
        with mock.patch.object(V, 'conferir_servidor', return_value=0) as conferir, \
                mock.patch.object(V, 'verificar') as suite:
            self.assertEqual(V.main(['--servidor', '9']), 0)
        conferir.assert_called_once_with(9)
        suite.assert_not_called()

    def test_uso_errado_sai_com_2(self):
        for argv in (['--servidor', '0'], ['--servidor', '70000'], ['--servidor', 'abc'], ['--servidor', '-1'],
                     ['--servidor', '--rapido'], ['--servidor', '8766', '--front'],
                     ['--servidor', '8766', '--hora', '3'], ['--dados-reais', '--servidor'],
                     ['--servidor', '8766', '--porta-front', '8767']):
            with self.subTest(argv=argv):
                with mock.patch.object(V, 'conferir_servidor') as conferir, \
                        mock.patch.object(V, 'verificar', side_effect=sem_suite), \
                        mock.patch('sys.stderr', io.StringIO()):
                    with self.assertRaises(SystemExit) as cm:
                        V.main(argv)
                self.assertEqual(cm.exception.code, 2)
                conferir.assert_not_called()

    def test_ajuda_diz_que_e_a_unica_excecao_da_8765_e_so_le(self):
        buf = io.StringIO()
        with redirect_stdout(buf), self.assertRaises(SystemExit):
            V.ler_argumentos(['--help'])
        ajuda = ' '.join(buf.getvalue().split())
        self.assertIn('--servidor', ajuda)
        self.assertIn('Única exceção à regra de nunca usar a 8765: só lê', ajuda)
        self.assertIn('com uma exceção: o --servidor, que só lê', ' '.join(V.__doc__.split()))


if __name__ == '__main__':
    unittest.main()
