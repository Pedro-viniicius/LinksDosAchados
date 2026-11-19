#!/usr/bin/env python3
"""Testes da trava por loja (docs/produto/planos/endurecer-engenharia-e-operacao.md, etapa 3, CA4).

Uso:  python3 testes/test_trava_rodada.py -v

`servidor.travar_rodada(loja)` e o uso dela no `main` do atualizar_precos.py, do coletar_amazon.py e do
coletar_shopee.py (`buscas` e `importar`; o `conferir` não trava). A 2ª rodada da mesma loja sai com 4 sem abrir o
banco, o progresso nem os tokens.

Tudo em pasta temporária: ACHADINHOS_DB, os três arquivos de progresso, ACHADINHOS_ML_TOKENS e
ACHADINHOS_ML_CATALOGO apontam para ela antes do import e no ambiente de cada subprocesso. Os proxies vão para
127.0.0.1:9 (proxy morto). Nenhum teste deixa uma rodada passar da trava rumo à rede: quando a trava não está
segura pelo teste, os argumentos param o comando antes (credencial ausente, tokens ausentes, arquivo inexistente,
aba inexistente). A trava do teste é outro `os.open` + `flock` no mesmo arquivo: no Linux, duas aberturas do mesmo
arquivo se excluem mesmo dentro de um processo só.
"""
import contextlib
import fcntl
import io
import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix='teste-trava-rodada-')
PROXIES = {v: 'http://127.0.0.1:9' for v in ('http_proxy', 'https_proxy', 'ftp_proxy',
                                              'HTTP_PROXY', 'HTTPS_PROXY', 'FTP_PROXY')}
AMBIENTE_DO_IMPORT = {
    'ACHADINHOS_DB': os.path.join(TMP, 'achadinhos.db'),
    'ACHADINHOS_FEITOS': os.path.join(TMP, 'feitos-coleta-amazon.txt'),
    'ACHADINHOS_FEITOS_SHOPEE': os.path.join(TMP, 'feitos-coleta-shopee.txt'),
    'ACHADINHOS_FEITOS_ATUALIZAR': os.path.join(TMP, 'feitos-atualizar.txt'),
    'ACHADINHOS_ML_TOKENS': os.path.join(TMP, 'ml_tokens.json'),
    'ACHADINHOS_ML_CATALOGO': os.path.join(TMP, 'ml_catalogo.json'),
    'ACHADINHOS_API_TOKEN_ARQUIVO': '/nao/existe',
}
os.environ.update(PROXIES)
os.environ['no_proxy'] = ''
os.environ.update(AMBIENTE_DO_IMPORT)
for v in ('ACHADINHOS_SHOPEE_APP_ID', 'ACHADINHOS_SHOPEE_SECRET', 'ACHADINHOS_ML_SECRET'):
    os.environ.pop(v, None)
sys.path.insert(0, RAIZ)

import atualizar_precos as A  # noqa: E402
import coletar_amazon as C  # noqa: E402
import coletar_shopee as CS  # noqa: E402
import ml_api as M  # noqa: E402
import servidor as S  # noqa: E402

assert all(os.path.dirname(p) == TMP for p in (S.DB, A.FEITOS, C.FEITOS, CS.FEITOS, M.TOKENS, M.CATALOGO)), \
    'o teste não pode tocar os dados reais'

ABA = 'Perfumes e Perfumaria'   # existe no buscas.json real (lido só para validar o argumento)
ABA_INEXISTENTE = 'Aba que não existe no buscas'
APP_ID = 'app-id-falso-123'
SECRET = 'SEGREDO-FALSO-DA-TRAVA-0001'


def mensagem(loja):
    return (f'PAROU: outra rodada de {loja} está em andamento (achadinhos.db.rodada-{loja}.lock); '
            'espere ela terminar.')


@contextlib.contextmanager
def segurando(caminho):
    """A trava de uma rodada que já está no ar: outro open + flock exclusivo no mesmo arquivo."""
    fd = os.open(caminho, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


class Pasta(unittest.TestCase):
    """Uma pasta nova por teste, com o banco e os arquivos da rodada nela (o servidor.DB do processo aponta para lá)."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix=self._testMethodName[:40] + '-', dir=TMP)
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.db = os.path.join(self.dir, 'achadinhos.db')
        p = mock.patch.object(S, 'DB', self.db)
        p.start()
        self.addCleanup(p.stop)

    def trava(self, loja):
        return self.db + '.rodada-' + loja + '.lock'

    def env(self, **extra):
        env = {k: v for k, v in os.environ.items() if not k.startswith('ACHADINHOS_')}
        env.update(PROXIES, no_proxy='', PYTHONPATH=RAIZ, ACHADINHOS_DB=self.db,
                   ACHADINHOS_FEITOS=os.path.join(self.dir, 'feitos-coleta-amazon.txt'),
                   ACHADINHOS_FEITOS_SHOPEE=os.path.join(self.dir, 'feitos-coleta-shopee.txt'),
                   ACHADINHOS_FEITOS_ATUALIZAR=os.path.join(self.dir, 'feitos-atualizar.txt'),
                   ACHADINHOS_ML_TOKENS=os.path.join(self.dir, 'ml_tokens.json'),
                   ACHADINHOS_ML_CATALOGO=os.path.join(self.dir, 'ml_catalogo.json'),
                   ACHADINHOS_API_TOKEN_ARQUIVO='/nao/existe', ACHADINHOS_DISPARO='0')
        env.update(extra)
        return env

    def cli(self, script, *argv, **extra):
        """(saída, stdout, stderr) do script de verdade, num subprocesso com o ambiente da pasta."""
        r = subprocess.run([sys.executable, os.path.join(RAIZ, script), *argv], cwd=self.dir, env=self.env(**extra),
                           stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
        self.assertNotIn(SECRET, r.stdout + r.stderr)
        self.assertNotIn('Traceback', r.stderr)
        return r.returncode, r.stdout, r.stderr

    def so_a_trava(self, *lojas):
        """Na pasta só sobrou o arquivo da trava: nem banco (nem -wal/-shm), nem progresso, nem tokens, nem vínculos."""
        self.assertEqual(sorted(os.listdir(self.dir)), sorted(os.path.basename(self.trava(l)) for l in lojas))


class TravarRodada(Pasta):
    """servidor.travar_rodada e RodadaEmAndamento."""

    def test_arquivo_ao_lado_do_banco_comum_e_0600_mesmo_com_umask_aberta(self):
        antiga = os.umask(0)
        self.addCleanup(os.umask, antiga)
        with S.travar_rodada('ml'):
            info = os.lstat(self.trava('ml'))
            self.assertTrue(stat.S_ISREG(info.st_mode))
            self.assertEqual(stat.S_IMODE(info.st_mode), 0o600)
            self.assertEqual(info.st_uid, os.getuid())
        self.assertTrue(os.path.exists(self.trava('ml')), 'o arquivo da trava fica: só a trava some')
        self.assertFalse(os.path.exists(self.db), 'pegar a trava não cria o banco')

    def test_modo_aberto_volta_para_0600(self):
        with open(self.trava('amazon'), 'w'):
            pass
        os.chmod(self.trava('amazon'), 0o644)
        with S.travar_rodada('amazon'):
            self.assertEqual(stat.S_IMODE(os.lstat(self.trava('amazon')).st_mode), 0o600)

    def test_segunda_trava_da_mesma_loja_e_recusada_sem_espera_e_com_motivo_none(self):
        for loja in S.LOJAS:
            with self.subTest(loja), S.travar_rodada(loja):
                with self.assertRaises(S.RodadaEmAndamento) as c:
                    with S.travar_rodada(loja):
                        self.fail('entrou com a trava ocupada')
                e = c.exception
                self.assertEqual((e.loja, e.nome, e.motivo), (loja, f'achadinhos.db.rodada-{loja}.lock', None))
                self.assertEqual(f'PAROU: {e}', mensagem(loja))

    def test_trava_segura_por_outro_open_e_recusada(self):
        with segurando(self.trava('shopee')):
            with self.assertRaises(S.RodadaEmAndamento) as c:
                with S.travar_rodada('shopee'):
                    self.fail('entrou com a trava ocupada')
        self.assertIsNone(c.exception.motivo)

    def test_lojas_diferentes_nao_se_bloqueiam(self):
        with S.travar_rodada('ml'), S.travar_rodada('amazon'), S.travar_rodada('shopee'):
            for loja in S.LOJAS:
                self.assertTrue(os.path.exists(self.trava(loja)))

    def test_solta_no_fim_do_bloco_e_na_excecao(self):
        with S.travar_rodada('ml'):
            pass
        with segurando(self.trava('ml')):   # livre: o flock do teste passa
            pass
        with self.assertRaises(ZeroDivisionError):
            with S.travar_rodada('ml'):
                1 / 0
        with S.travar_rodada('ml'):
            pass

    def test_symlink_no_lugar_da_trava_e_recusado_e_o_alvo_fica_intacto(self):
        alvo = os.path.join(self.dir, 'alvo.txt')
        with open(alvo, 'w') as f:
            f.write('não mexa')
        os.chmod(alvo, 0o644)
        os.symlink(alvo, self.trava('ml'))
        with self.assertRaises(S.RodadaEmAndamento) as c:
            with S.travar_rodada('ml'):
                self.fail('entrou por um symlink')
        self.assertIsNotNone(c.exception.motivo)
        self.assertNotIn(self.dir, str(c.exception), 'só o nome do arquivo, sem a pasta')
        self.assertEqual(stat.S_IMODE(os.stat(alvo).st_mode), 0o644)
        with open(alvo) as f:
            self.assertEqual(f.read(), 'não mexa')

    def test_symlink_quebrado_e_recusado_e_nao_cria_o_alvo(self):
        alvo = os.path.join(self.dir, 'nao-existe.txt')
        os.symlink(alvo, self.trava('shopee'))
        with self.assertRaises(S.RodadaEmAndamento):
            with S.travar_rodada('shopee'):
                self.fail('entrou por um symlink')
        self.assertFalse(os.path.lexists(alvo))

    def test_pasta_e_fifo_no_lugar_da_trava_sao_recusados_sem_prender(self):
        os.mkdir(self.trava('ml'))
        os.mkfifo(self.trava('amazon'))   # sem O_NONBLOCK/S_ISREG, um FIFO poderia prender o open ou passar
        for loja in ('ml', 'amazon'):
            with self.subTest(loja), self.assertRaises(S.RodadaEmAndamento) as c:
                with S.travar_rodada(loja):
                    self.fail('entrou numa trava que não é arquivo comum')
            self.assertIsNotNone(c.exception.motivo)

    def test_arquivo_de_outro_usuario_e_recusado(self):
        with open(self.trava('ml'), 'w'):
            pass
        with mock.patch.object(os, 'getuid', return_value=os.getuid() + 1):
            with self.assertRaises(S.RodadaEmAndamento) as c:
                with S.travar_rodada('ml'):
                    self.fail('entrou numa trava de outro usuário')
        self.assertIsNotNone(c.exception.motivo)

    def test_arquivo_trocado_entre_o_open_e_o_flock_e_recusado(self):
        caminho = self.trava('shopee')
        flock = fcntl.flock
        trocas = []

        def flock_com_troca(fd, op):
            if op & fcntl.LOCK_EX and not trocas:   # outra rodada apagou e recriou o arquivo neste meio-tempo
                trocas.append(1)
                os.remove(caminho)
                with open(caminho, 'w'):
                    pass
            return flock(fd, op)

        with mock.patch.object(fcntl, 'flock', flock_com_troca):
            with self.assertRaises(S.RodadaEmAndamento) as c:
                with S.travar_rodada('shopee'):
                    self.fail('travou um arquivo que já não está no caminho')
        self.assertEqual(trocas, [1])
        self.assertIsNotNone(c.exception.motivo)
        with S.travar_rodada('shopee'):   # o arquivo novo trava normalmente
            pass

    def test_flock_recusado_pelo_sistema_vira_motivo_fixo(self):
        with mock.patch.object(fcntl, 'flock', side_effect=OSError(5, 'Input/output error /pasta/secreta')):
            with self.assertRaises(S.RodadaEmAndamento) as c:
                with S.travar_rodada('ml'):
                    self.fail('entrou sem trava')
        self.assertIsNotNone(c.exception.motivo)
        self.assertNotIn('secreta', str(c.exception))

    def test_loja_desconhecida_e_erro_de_programa(self):
        for loja in ('', 'ML', '../x', 'amazon/../ml'):
            with self.subTest(loja), self.assertRaises(ValueError):
                with S.travar_rodada(loja):
                    self.fail('travou loja inválida')
        self.assertEqual(os.listdir(self.dir), [])


class OrdemNoProcesso(Pasta):
    """No processo: com a trava ocupada, o main sai com 4 antes de proteger_processo, credenciais, tokens,
    vínculos, criar_banco e marcar. Sem a trava ocupada, os mesmos falsos são chamados (o teste não é vazio)."""

    def setUp(self):
        super().setUp()
        self.falsos = {}
        alvos = [(S, 'criar_banco'), (A, 'marcar'), (C, 'marcar'), (CS, 'marcar'),
                 (CS, 'proteger_processo'), (CS, 'credenciais'), (M, 'proteger_processo'),
                 (M, 'sessao_do_ambiente'), (M, 'ler_vinculos'), (CS, 'ler_arquivo')]
        for modulo, nome in alvos:
            p = mock.patch.object(modulo, nome)
            self.falsos[f'{modulo.__name__}.{nome}'] = p.start()
            self.addCleanup(p.stop)
        self.falsos['servidor.criar_banco'].side_effect = RuntimeError('parou no banco')
        self.falsos['coletar_shopee.credenciais'].return_value = None
        sessao = mock.Mock()
        sessao.token.side_effect = M.RefazerAutorizacao()
        self.falsos['ml_api.sessao_do_ambiente'].return_value = sessao
        self.falsos['coletar_shopee.ler_arquivo'].side_effect = CS.ArquivoAusente()

    def rodar(self, main, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                codigo = main(argv)
            except SystemExit as e:
                codigo = e.code
            except RuntimeError:   # o criar_banco falso: o coletar_amazon não o trata
                codigo = 'parou no banco'
        return codigo, out.getvalue(), err.getvalue()

    def chamados(self):
        return sorted(k for k, f in self.falsos.items() if f.called)

    CASOS = [
        ('atualizar_precos amazon', 'amazon', lambda: A.main, ['amazon', '--cat', ABA],
         ['servidor.criar_banco'], 1),
        ('atualizar_precos shopee', 'shopee', lambda: A.main, ['shopee', '--cat', ABA],
         ['coletar_shopee.credenciais', 'coletar_shopee.proteger_processo'], 2),
        ('atualizar_precos ml', 'ml', lambda: A.main, ['ml', '--cat', ABA],
         ['ml_api.proteger_processo', 'ml_api.sessao_do_ambiente'], 2),
        ('coletar_amazon buscas', 'amazon', lambda: C.main, ['buscas', '--cat', ABA],
         ['servidor.criar_banco'], 'parou no banco'),
        ('coletar_shopee buscas', 'shopee', lambda: CS.main, ['buscas', '--cat', ABA],
         ['coletar_shopee.credenciais', 'coletar_shopee.proteger_processo'], 2),
        ('coletar_shopee importar', 'shopee', lambda: CS.main, ['importar', 'arquivo.json'],
         ['coletar_shopee.ler_arquivo'], 2),
    ]

    def test_trava_ocupada_sai_com_4_antes_de_tudo(self):
        for rotulo, loja, main, argv, _, _ in self.CASOS:
            with self.subTest(rotulo), segurando(self.trava(loja)):
                for f in self.falsos.values():
                    f.reset_mock()
                codigo, out, err = self.rodar(main(), argv)
                self.assertEqual(codigo, 4)
                self.assertEqual(err.strip(), mensagem(loja))
                self.assertEqual(out, '')
                self.assertEqual(self.chamados(), [], 'nada roda antes da trava')

    def test_trava_livre_segue_para_o_resto(self):
        for rotulo, loja, main, argv, esperados, saida in self.CASOS:
            with self.subTest(rotulo):
                for f in self.falsos.values():
                    f.reset_mock()
                codigo, _, err = self.rodar(main(), argv)
                self.assertEqual(codigo, saida, err)
                self.assertEqual(self.chamados(), sorted(esperados))
                with S.travar_rodada(loja):   # e soltou a trava na saída
                    pass

    def test_coletar_amazon_solta_a_trava_tambem_no_sys_exit(self):
        self.falsos['servidor.criar_banco'].side_effect = None
        with mock.patch.object(C, 'coletar_buscas', side_effect=C.ArgInvalido('x')), \
                mock.patch.object(S, 'conectar'):
            codigo, _, _ = self.rodar(C.main, ['buscas', '--cat', ABA])
        self.assertEqual(codigo, 2)
        with S.travar_rodada('amazon'):
            pass

    def test_conferir_da_shopee_nao_trava(self):
        with segurando(self.trava('shopee')):
            for argv in (['conferir'], ['conferir', '--por-item']):
                with self.subTest(argv):
                    codigo, _, err = self.rodar(CS.main, argv)
                    self.assertEqual(codigo, 2, err)   # passou da trava e parou na credencial ausente
                    self.assertNotIn('PAROU', err)


class CLIs(Pasta):
    """Os scripts de verdade, em subprocesso: saída 4, mensagem no stderr e nada criado além da trava."""

    def test_segunda_rodada_da_mesma_loja_sai_com_4_sem_criar_banco_progresso_nem_tokens(self):
        casos = [
            ('atualizar_precos.py', 'amazon', ['amazon', '--cat', ABA], {}),
            ('atualizar_precos.py', 'shopee', ['shopee', '--cat', ABA],
             {'ACHADINHOS_SHOPEE_APP_ID': APP_ID, 'ACHADINHOS_SHOPEE_SECRET': SECRET}),
            ('atualizar_precos.py', 'ml', ['ml', '--cat', ABA], {'ACHADINHOS_ML_SECRET': SECRET}),
            ('coletar_amazon.py', 'amazon', ['buscas', '--cat', ABA_INEXISTENTE], {}),
            ('coletar_shopee.py', 'shopee', ['buscas', '--cat', ABA],
             {'ACHADINHOS_SHOPEE_APP_ID': APP_ID, 'ACHADINHOS_SHOPEE_SECRET': SECRET}),
            ('coletar_shopee.py', 'shopee', ['importar', os.path.join(TMP, 'nao-existe.json')], {}),
        ]
        for script, loja, argv, extra in casos:
            with self.subTest(script=script, argv=argv[0]), segurando(self.trava(loja)):
                codigo, out, err = self.cli(script, *argv, **extra)
                self.assertEqual(codigo, 4, err)
                self.assertEqual(err.strip(), mensagem(loja))
                self.assertEqual(out, '')
                self.so_a_trava(loja)
            os.remove(self.trava(loja))

    def test_coleta_e_atualizacao_da_mesma_loja_usam_o_mesmo_arquivo(self):
        with segurando(self.trava('shopee')):
            r1 = self.cli('coletar_shopee.py', 'buscas', '--cat', ABA)
            r2 = self.cli('atualizar_precos.py', 'shopee', '--cat', ABA)
        with segurando(self.trava('amazon')):
            r3 = self.cli('coletar_amazon.py', 'buscas', '--cat', ABA_INEXISTENTE)
            r4 = self.cli('atualizar_precos.py', 'amazon')
        self.assertEqual([r[0] for r in (r1, r2, r3, r4)], [4, 4, 4, 4])
        self.assertEqual(r1[2], r2[2])
        self.assertEqual(r3[2], r4[2])

    def test_lojas_diferentes_nao_se_bloqueiam(self):
        with segurando(self.trava('ml')), segurando(self.trava('amazon')):
            # passam da trava e param antes da rede: credencial, tokens e arquivo ausentes
            self.assertEqual(self.cli('atualizar_precos.py', 'shopee', '--cat', ABA)[0], 2)
            self.assertEqual(self.cli('coletar_shopee.py', 'importar', os.path.join(TMP, 'nao-existe.json'))[0], 2)
        with segurando(self.trava('shopee')):
            codigo, _, err = self.cli('atualizar_precos.py', 'ml', '--cat', ABA)
            self.assertEqual(codigo, 2, err)
            codigo, _, err = self.cli('coletar_amazon.py', 'buscas', '--cat', ABA_INEXISTENTE)
            self.assertEqual(codigo, 2, err)   # aba recusada depois do criar_banco: a trava da Amazon passou
            self.assertIn('aba desconhecida', err)
        self.assertTrue(os.path.exists(self.db), 'o coletar_amazon passou da trava e chegou ao banco')

    def test_trava_livre_nao_sai_com_4(self):
        # controle do teste de cima: sem ninguém segurando, os mesmos comandos param no motivo deles
        self.assertEqual(self.cli('coletar_shopee.py', 'importar', os.path.join(TMP, 'nao-existe.json'))[0], 2)
        self.assertEqual(self.cli('atualizar_precos.py', 'ml', '--cat', ABA)[0], 2)
        self.assertEqual(self.cli('coletar_amazon.py', 'buscas', '--cat', ABA_INEXISTENTE)[0], 2)

    def test_symlink_no_lugar_da_trava_para_o_cli_com_4(self):
        alvo = os.path.join(self.dir, 'alvo.txt')
        with open(alvo, 'w') as f:
            f.write('x')
        os.symlink(alvo, self.trava('shopee'))
        codigo, out, err = self.cli('coletar_shopee.py', 'importar', os.path.join(TMP, 'nao-existe.json'))
        self.assertEqual(codigo, 4, err)
        self.assertTrue(err.startswith('PAROU: não consegui pegar a trava da rodada de shopee '
                                       '(achadinhos.db.rodada-shopee.lock): '), err)
        self.assertNotIn(self.dir, err)
        self.assertEqual(sorted(os.listdir(self.dir)), sorted(['alvo.txt', os.path.basename(self.trava('shopee'))]))
        with open(alvo) as f:
            self.assertEqual(f.read(), 'x')

    def test_conferir_da_shopee_nao_trava_nem_cria_o_arquivo(self):
        codigo, _, err = self.cli('coletar_shopee.py', 'conferir')
        self.assertEqual(codigo, 2, err)   # parou na credencial ausente
        self.assertEqual(os.listdir(self.dir), [])
        with segurando(self.trava('shopee')):
            for argv in (['conferir'], ['conferir', '--por-item']):
                with self.subTest(argv):
                    codigo, _, err = self.cli('coletar_shopee.py', *argv)
                    self.assertEqual(codigo, 2, err)
                    self.assertNotIn('PAROU', err)


# O dono da trava: o main de verdade do atualizar_precos, com a rodada do ML trocada por uma pausa longa.
DONO = '''
import sys, time
import atualizar_precos as A
def rodada(args):
    print('rodando', flush=True)
    time.sleep(120)
    return 0
A._rodar_ml = rodada
sys.exit(A.main(['ml']))
'''


class KillMenos9(Pasta):

    def test_a_trava_some_com_kill_9_do_dono(self):
        p = subprocess.Popen([sys.executable, '-c', DONO], cwd=self.dir, env=self.env(), stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: (p.poll() is None and p.kill(), p.wait(), p.stdout.close(), p.stderr.close()))
        self.assertEqual(p.stdout.readline().strip(), 'rodando')
        # com o dono no ar: a 2ª rodada do ML sai com 4, no processo e pelo CLI; a da Amazon passa
        with self.assertRaises(S.RodadaEmAndamento):
            with S.travar_rodada('ml'):
                self.fail('entrou com o dono no ar')
        codigo, _, err = self.cli('atualizar_precos.py', 'ml', '--cat', ABA)
        self.assertEqual((codigo, err.strip()), (4, mensagem('ml')))
        with S.travar_rodada('amazon'):
            pass
        os.kill(p.pid, signal.SIGKILL)
        self.assertEqual(p.wait(timeout=30), -signal.SIGKILL)
        self.assertTrue(os.path.exists(self.trava('ml')), 'o arquivo fica; só a trava some')
        with S.travar_rodada('ml'):
            pass
        codigo, _, err = self.cli('atualizar_precos.py', 'ml', '--cat', ABA)
        self.assertEqual(codigo, 2, err)   # passou da trava e parou nos tokens ausentes


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
