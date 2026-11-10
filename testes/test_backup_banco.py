#!/usr/bin/env python3
"""Testes do backup_banco.py (docs/produto/planos/endurecer-engenharia-e-operacao.md, etapa 4: CA5).

Uso:  python3 testes/test_backup_banco.py -v

Tudo em pasta temporária: cada teste semeia um banco próprio (com a tabela `numeros` e um telefone
falso, para provar que nada do conteúdo sai no stdout/stderr) e roda o script como subprocesso com
ACHADINHOS_DB apontando para ele, ou chama `main()` no próprio processo com `servidor.DB` trocado,
quando precisa injetar falha. Nunca toca o achadinhos.db real nem a pasta backups/ do projeto.
Só biblioteca padrão.
"""
import atexit
import contextlib
import hashlib
import io
import os
import re
import shutil
import signal
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_servidor as TS  # noqa: E402  (ambiente, RAIZ, DB_REAL)

# Antes de importar o servidor: o S.DB deste processo aponta para um temporário, nunca o real.
TMP_AMBIENTE = tempfile.mkdtemp(prefix='achadinhos-backup-env-')
atexit.register(shutil.rmtree, TMP_AMBIENTE, ignore_errors=True)
os.environ['ACHADINHOS_DB'] = os.path.join(TMP_AMBIENTE, 'nunca-usado.db')
sys.path.insert(0, TS.RAIZ)
import servidor as S  # noqa: E402
import backup_banco as B  # noqa: E402

assert os.path.dirname(S.DB) == TMP_AMBIENTE, 'o teste não pode tocar o banco real'

SCRIPT = os.path.join(TS.RAIZ, 'backup_banco.py')
TELEFONE = '5535998761234'          # falso; não pode aparecer em nenhuma saída
GRUPO = '120363041234567890@g.us'   # falso, idem
RE_SAIDA = re.compile(r'backup: (?P<caminho>\S+) ok (?P<n>[0-9]+) itens\n')


def semear(db, itens=3, manter_aberto=False):
    """Banco em WAL, como o real: items + numeros (dado pessoal). Com `manter_aberto`, devolve a
    conexão com escrita ainda só no -wal (sem checkpoint)."""
    con = sqlite3.connect(db)
    con.execute('PRAGMA journal_mode=WAL')
    con.execute('PRAGMA wal_autocheckpoint=0')
    con.execute('CREATE TABLE items (id INTEGER PRIMARY KEY, loja TEXT, titulo TEXT)')
    con.execute('CREATE TABLE numeros (id INTEGER PRIMARY KEY, telefone TEXT, grupo TEXT)')
    con.executemany('INSERT INTO items (loja, titulo) VALUES (?, ?)',
                    [('amazon', f'Produto {i} ' + 'x' * 80) for i in range(itens)])
    con.execute('INSERT INTO numeros (telefone, grupo) VALUES (?, ?)', (TELEFONE, GRUPO))
    con.commit()
    if manter_aberto:
        return con
    con.close()
    return None


def sha(caminho):
    with open(caminho, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


def modo(caminho):
    return stat.S_IMODE(os.lstat(caminho).st_mode)


def criar(caminho, conteudo=b'manual'):
    with open(caminho, 'wb') as f:
        f.write(conteudo)


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix='achadinhos-backup-')
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.db = os.path.join(self.dir, 'achadinhos.db')
        self.pasta = os.path.join(self.dir, 'backups')

    def sem_dado_pessoal(self, *textos):
        for t in textos:
            self.assertNotIn(TELEFONE, t)
            self.assertNotIn(GRUPO, t)
            self.assertNotIn('Produto 0', t)

    def rodar(self, *args, umask=None):
        """Roda o script como subprocesso sobre self.db. Devolve (código, stdout, stderr)."""
        kw = {} if umask is None else {'umask': umask}
        r = subprocess.run([sys.executable, SCRIPT, *args], cwd=self.dir, env=TS.ambiente(self.db),
                           capture_output=True, text=True, timeout=60, **kw)
        self.sem_dado_pessoal(r.stdout, r.stderr)
        return r.returncode, r.stdout, r.stderr

    def rodar_aqui(self, *args):
        """Chama B.main no próprio processo, com S.DB = self.db (para injetar falhas)."""
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(S, 'DB', self.db), contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(err):
            try:
                codigo = B.main(list(args))
            except SystemExit as e:
                codigo = e.code
        self.sem_dado_pessoal(out.getvalue(), err.getvalue())
        return codigo, out.getvalue(), err.getvalue()

    def backups(self):
        return sorted(os.listdir(self.pasta)) if os.path.isdir(self.pasta) else []

    def assert_ok(self, codigo, out, err, itens=3):
        self.assertEqual(codigo, 0, err)
        self.assertEqual(err, '')
        m = RE_SAIDA.fullmatch(out)
        self.assertIsNotNone(m, f'saída fora do formato: {out!r}')
        self.assertEqual(int(m['n']), itens)
        self.assertEqual(os.path.dirname(m['caminho']), self.pasta)
        self.assertTrue(os.path.isfile(m['caminho']))
        return m['caminho']

    def assert_falhou(self, codigo, out, err):
        self.assertEqual(codigo, 1, err)
        self.assertEqual(out, '')
        self.assertRegex(err, r'^ERRO: backup (falhou|interrompido)')
        self.assertEqual([n for n in self.backups() if n.startswith('auto-')], [],
                         'falha não pode deixar backup nem .parcial')


class NomeDatado(Base):
    def test_nome_datado_e_saida_so_com_caminho_e_contagem(self):
        semear(self.db)
        antes = datetime.now().strftime('%Y%m%d-%H%M%S')
        caminho = self.assert_ok(*self.rodar('--motivo', 'ml'))
        depois = datetime.now().strftime('%Y%m%d-%H%M%S')
        nome = os.path.basename(caminho)
        m = re.fullmatch(r'auto-ml-([0-9]{8}-[0-9]{6})\.db', nome)
        self.assertIsNotNone(m, nome)
        self.assertTrue(antes <= m[1] <= depois, (antes, m[1], depois))
        self.assertEqual(self.backups(), [nome])
        # A cópia é o banco inteiro (inclusive numeros).
        con = sqlite3.connect(caminho)
        try:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM items').fetchone()[0], 3)
            self.assertEqual(con.execute('SELECT telefone FROM numeros').fetchall(), [(TELEFONE,)])
        finally:
            con.close()

    def test_motivo_com_digitos_e_hifens_de_30_caracteres(self):
        semear(self.db)
        motivo = 'a-1-' + 'b' * 26
        self.assertEqual(len(motivo), 30)
        caminho = self.assert_ok(*self.rodar('--motivo', motivo))
        self.assertTrue(os.path.basename(caminho).startswith(f'auto-{motivo}-'))
        self.assertIsNotNone(B.RE_AUTO.fullmatch(os.path.basename(caminho)))

    def test_copia_o_que_ainda_esta_no_wal(self):
        con = semear(self.db, manter_aberto=True)
        try:
            con.executemany('INSERT INTO items (loja, titulo) VALUES (?, ?)', [('ml', 'novo')] * 4)
            con.commit()
            self.assertGreater(os.path.getsize(self.db + '-wal'), 0)
            self.assert_ok(*self.rodar('--motivo', 'shopee'), itens=7)
        finally:
            con.close()

    def test_colisao_no_mesmo_segundo_ganha_sufixo_e_nao_sobrescreve(self):
        semear(self.db)
        fixo = datetime(2026, 11, 9, 14, 30, 0)
        base = 'auto-ml-20261109-143000'
        nomes = []
        with mock.patch.object(B, 'agora', return_value=fixo):
            for _ in range(3):
                nomes.append(os.path.basename(self.assert_ok(*self.rodar_aqui('--motivo', 'ml'))))
                if len(nomes) == 1:
                    primeiro = sha(os.path.join(self.pasta, nomes[0]))
        self.assertEqual(nomes, [f'{base}.db', f'{base}-1.db', f'{base}-2.db'])
        self.assertEqual(sha(os.path.join(self.pasta, nomes[0])), primeiro)

    def test_nome_ocupado_por_link_ou_journal_solto_e_pulado(self):
        semear(self.db)
        os.mkdir(self.pasta, 0o700)
        alvo = os.path.join(self.dir, 'alvo-inexistente.db')
        base = 'auto-ml-20261109-143000'
        os.symlink(alvo, os.path.join(self.pasta, f'{base}.db'))          # link quebrado
        criar(os.path.join(self.pasta, f'{base}-1.db-journal'), b'velho')   # journal "quente" solto
        criar(os.path.join(self.pasta, f'{base}-2.db.parcial'), b'outro')  # outro backup em curso
        with mock.patch.object(B, 'agora', return_value=datetime(2026, 11, 9, 14, 30, 0)):
            caminho = self.assert_ok(*self.rodar_aqui('--motivo', 'ml', '--manter', '3'))
        self.assertEqual(os.path.basename(caminho), f'{base}-3.db')
        self.assertFalse(os.path.lexists(alvo), 'não pode escrever pelo link')
        self.assertTrue(os.path.islink(os.path.join(self.pasta, f'{base}.db')))
        with open(os.path.join(self.pasta, f'{base}-1.db-journal'), 'rb') as f:
            self.assertEqual(f.read(), b'velho')
        with open(os.path.join(self.pasta, f'{base}-2.db.parcial'), 'rb') as f:
            self.assertEqual(f.read(), b'outro')

    def test_nome_final_que_aparece_durante_a_copia_nao_e_sobrescrito(self):
        semear(self.db)
        fixo = datetime(2026, 11, 9, 14, 30, 0)
        final = os.path.join(self.pasta, 'auto-ml-20261109-143000.db')
        conferir = B.conferir

        def conferir_e_ocupar(caminho):
            n = conferir(caminho)
            criar(final, b'do dono')
            return n

        with mock.patch.object(B, 'agora', return_value=fixo), \
                mock.patch.object(B, 'conferir', side_effect=conferir_e_ocupar):
            codigo, out, err = self.rodar_aqui('--motivo', 'ml')
        self.assertEqual(codigo, 1)
        self.assertEqual(out, '')
        self.assertIn('nada foi sobrescrito', err)
        with open(final, 'rb') as f:
            self.assertEqual(f.read(), b'do dono')
        self.assertEqual(self.backups(), [os.path.basename(final)], 'sem .parcial')


class Permissoes(Base):
    def test_backup_0600_e_pasta_0700_mesmo_com_umask_zero(self):
        semear(self.db)
        caminho = self.assert_ok(*self.rodar('--motivo', 'ml', umask=0))
        self.assertEqual(modo(caminho), 0o600)
        self.assertEqual(modo(self.pasta), 0o700)

    def test_pasta_existente_aberta_e_fechada_sem_mexer_no_resto(self):
        semear(self.db)
        os.mkdir(self.pasta)
        os.chmod(self.pasta, 0o755)
        manual = os.path.join(self.pasta, 'achadinhos-20261101-120000.db')
        criar(manual)
        os.chmod(manual, 0o644)
        self.assert_ok(*self.rodar('--motivo', 'ml'))
        self.assertEqual(modo(self.pasta), 0o700)
        self.assertEqual(modo(manual), 0o644, 'o backup manual não é deste script')

    def test_parcial_nasce_0600(self):
        semear(self.db)
        vistos = []
        copiar = B.copiar

        def espiar(db, destino):
            vistos.append((os.path.basename(destino), modo(destino)))
            return copiar(db, destino)

        anterior = os.umask(0)
        try:
            with mock.patch.object(B, 'copiar', side_effect=espiar):
                self.assert_ok(*self.rodar_aqui('--motivo', 'ml'))
        finally:
            os.umask(anterior)
        self.assertEqual(len(vistos), 1)
        self.assertTrue(vistos[0][0].endswith('.db.parcial'), vistos)
        self.assertEqual(vistos[0][1], 0o600)

    def test_pasta_backups_que_e_link_simbolico_e_recusada(self):
        semear(self.db)
        fora = os.path.join(self.dir, 'fora')
        os.mkdir(fora, 0o755)
        os.symlink(fora, self.pasta)
        codigo, out, err = self.rodar('--motivo', 'ml')
        self.assertEqual(codigo, 1)
        self.assertEqual(out, '')
        self.assertIn('backups/', err)
        self.assertEqual(os.listdir(fora), [])
        self.assertEqual(modo(fora), 0o755, 'não pode mudar o modo pelo link')

    def test_pasta_backups_que_e_arquivo_e_recusada(self):
        semear(self.db)
        criar(self.pasta, b'arquivo')
        codigo, out, err = self.rodar('--motivo', 'ml')
        self.assertEqual(codigo, 1)
        self.assertEqual(out, '')


class SemWalShm(Base):
    def test_copia_aberta_nao_cria_wal_nem_shm(self):
        semear(self.db)
        caminho = self.assert_ok(*self.rodar('--motivo', 'ml'))
        with open(caminho, 'rb') as f:
            cabecalho = f.read(20)
        self.assertEqual(cabecalho[18:20], b'\x01\x01', 'cabeçalho fora do modo WAL')
        con = sqlite3.connect(caminho)
        try:
            self.assertEqual(con.execute('PRAGMA journal_mode').fetchone()[0], 'delete')
            self.assertEqual(con.execute('SELECT COUNT(*) FROM items').fetchone()[0], 3)
            self.assertFalse(os.path.exists(caminho + '-wal'))
            self.assertFalse(os.path.exists(caminho + '-shm'))
        finally:
            con.close()
        self.assertEqual(self.backups(), [os.path.basename(caminho)])

    def test_banco_de_origem_continua_em_wal_e_sem_mudanca(self):
        semear(self.db)
        con = sqlite3.connect(self.db)
        con.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        con.close()
        antes = sha(self.db)
        self.assert_ok(*self.rodar('--motivo', 'ml'))
        self.assertEqual(sha(self.db), antes)
        con = sqlite3.connect(self.db)
        try:
            self.assertEqual(con.execute('PRAGMA journal_mode').fetchone()[0], 'wal')
        finally:
            con.close()


class Rotacao(Base):
    def setUp(self):
        super().setUp()
        semear(self.db)
        os.mkdir(self.pasta, 0o700)
        self.fora = os.path.join(self.dir, 'fora')
        os.mkdir(self.fora)

    def auto(self, nome, conteudo=b'antigo'):
        criar(os.path.join(self.pasta, nome), conteudo)
        return nome

    def test_fica_com_os_n_mais_novos_e_poupa_o_que_nao_e_dele(self):
        # 15 automáticos de motivos variados; a ordem é pela data do nome, não pelo motivo.
        velhos = [self.auto(f'auto-{"zzz" if d % 2 else "aaa"}-202601{d:02d}-120000.db')
                  for d in range(1, 16)]
        # Mesma data, sufixo de colisão: o -2 é mais novo que o -1, que é mais novo que o sem sufixo.
        colisao = [self.auto('auto-ml-20260120-080000.db'), self.auto('auto-ml-20260120-080000-1.db'),
                   self.auto('auto-ml-20260120-080000-2.db')]
        # Motivo que parece data: a data que vale é a última do nome (2020, a mais velha de todas).
        enganoso = self.auto('auto-a-20990101-000000-20200101-000000.db')
        # Companheiros do mais velho de todos (apagados com ele) e de um que fica (ficam).
        for s in ('-wal', '-shm', '-journal'):
            self.auto(enganoso + s)
            self.auto(colisao[2] + s)
        alvo = os.path.join(self.fora, 'alvo.db')
        criar(alvo, b'alvo')
        intocaveis = {
            'achadinhos-20200101-000000.db': 'manual do migrar_categorias',
            'antes-ml-api.db': 'manual dos scripts antigos',
            'auto-ML-20200101-000000.db': 'maiúscula: fora do padrão',
            'auto-ml-2020.db': 'data incompleta',
            'auto-ml-20200101-000000.db.parcial': 'parcial de outro processo',
            'auto-ml-20200101-000000-1000.db': 'sufixo fora do padrão',
            'xauto-ml-20200101-000000.db': 'prefixo diferente',
            'auto-ml-20200101-000000.dbx': 'extensão diferente',
            f'{velhos[0]}.bak': 'cópia do dono',
        }
        for nome in intocaveis:
            self.auto(nome, b'manual')
        os.symlink(alvo, os.path.join(self.pasta, 'auto-link-20200101-000000.db'))
        os.symlink(alvo, os.path.join(self.pasta, velhos[0] + '-wal'))   # companheiro que é link
        os.mkdir(os.path.join(self.pasta, 'auto-pasta-20200101-000000.db'))

        caminho = self.assert_ok(*self.rodar('--motivo', 'diario', '--manter', '3'))
        novo = os.path.basename(caminho)
        restantes = set(self.backups())
        autos = sorted(n for n in restantes if B.RE_AUTO.fullmatch(n)
                       and os.path.isfile(os.path.join(self.pasta, n))
                       and not os.path.islink(os.path.join(self.pasta, n)))
        self.assertEqual(set(autos), {novo, colisao[2], colisao[1]})
        for n in velhos + [colisao[0], enganoso]:
            self.assertNotIn(n, restantes)
        for s in ('-wal', '-shm', '-journal'):
            self.assertNotIn(enganoso + s, restantes)
            self.assertIn(colisao[2] + s, restantes, 'companheiro de backup que fica não sai')
        for nome, motivo in intocaveis.items():
            self.assertIn(nome, restantes, motivo)
            with open(os.path.join(self.pasta, nome), 'rb') as f:
                self.assertEqual(f.read(), b'manual', motivo)
        self.assertTrue(os.path.islink(os.path.join(self.pasta, 'auto-link-20200101-000000.db')))
        self.assertTrue(os.path.islink(os.path.join(self.pasta, velhos[0] + '-wal')))
        self.assertTrue(os.path.isdir(os.path.join(self.pasta, 'auto-pasta-20200101-000000.db')))
        with open(alvo, 'rb') as f:
            self.assertEqual(f.read(), b'alvo', 'nunca segue link simbólico')

    def test_parcial_parado_ha_mais_de_6_h_e_apagado_e_o_recente_fica(self):
        """Sobra de um backup morto por kill -9 (rodada 2, pedido do lead): cópia completa com telefones. A
        rotação apaga o auto-*.db.parcial sem mudança há mais de 6 h, com o -wal/-shm/-journal dele; o recente
        (backup em andamento), o de outro nome, o link simbólico e a pasta ficam."""
        agora = time.time()

        def envelhecer(nome, horas):
            os.utime(os.path.join(self.pasta, nome), (agora - horas * 3600,) * 2, follow_symlinks=False)

        velho = self.auto('auto-ml-20261001-000000.db.parcial')
        for s in ('-wal', '-shm', '-journal'):
            envelhecer(self.auto(velho + s), 10)
        envelhecer(velho, 6.1)
        recente = self.auto('auto-ml-20261002-000000.db.parcial')
        envelhecer(recente, 5.9)
        self.auto(recente + '-journal')
        outros = ['achadinhos-20261001-000000.db.parcial', 'auto-ML-20261001-000000.db.parcial',
                  'auto-ml-20261001-000000.db.parcial.bak']
        for nome in outros:
            envelhecer(self.auto(nome), 100)
        alvo = os.path.join(self.fora, 'alvo.db')
        criar(alvo, b'alvo')
        os.symlink(alvo, os.path.join(self.pasta, 'auto-ml-20261003-000000.db.parcial'))
        envelhecer('auto-ml-20261003-000000.db.parcial', 100)
        os.mkdir(os.path.join(self.pasta, 'auto-ml-20261004-000000.db.parcial'))
        envelhecer('auto-ml-20261004-000000.db.parcial', 100)

        self.assert_ok(*self.rodar('--motivo', 'ml'))
        restantes = set(self.backups())
        for s in ('', '-wal', '-shm', '-journal'):
            self.assertNotIn(velho + s, restantes)
        for nome in [recente, recente + '-journal', *outros, 'auto-ml-20261003-000000.db.parcial',
                     'auto-ml-20261004-000000.db.parcial']:
            self.assertIn(nome, restantes)
        with open(alvo, 'rb') as f:
            self.assertEqual(f.read(), b'alvo')

    def test_rotacao_segue_quando_outro_processo_apaga_antes(self):
        """Q2 (rodada 2): dois backups rotacionando juntos. O arquivo que some entre o stat e o unlink é
        ignorado, e a rotação vai até o fim, sem AVISO."""
        nomes = [self.auto(f'auto-ml-202601{d:02d}-120000.db') for d in range(1, 21)]
        unlink = os.unlink
        sumidos = []

        def outro_apagou_antes(nome, *a, **kw):
            if nome in nomes and nome not in sumidos:
                sumidos.append(nome)
                unlink(nome, *a, **kw)         # o outro processo apaga primeiro...
            return unlink(nome, *a, **kw)      # ...e o nosso acha o arquivo sumido

        with mock.patch.object(B.os, 'unlink', side_effect=outro_apagou_antes):
            codigo, out, err = self.rodar_aqui('--motivo', 'ml')
        self.assertEqual(codigo, 0, err)
        self.assertEqual(err, '')
        self.assertEqual(len([n for n in self.backups() if B.RE_AUTO.fullmatch(n)]), 14, self.backups())
        self.assertEqual(len(sumidos), 7)   # 20 + o novo = 21; ficam 14

    def test_padrao_fica_com_14(self):
        for d in range(1, 21):
            self.auto(f'auto-ml-202601{d:02d}-120000.db')
        novo = os.path.basename(self.assert_ok(*self.rodar('--motivo', 'ml')))
        autos = [n for n in self.backups() if n.startswith('auto-')]
        self.assertEqual(len(autos), 14)
        self.assertIn(novo, autos)
        self.assertEqual(sorted(set(autos) - {novo}),
                         [f'auto-ml-202601{d:02d}-120000.db' for d in range(8, 21)])

    def test_nunca_apaga_o_backup_novo_mesmo_com_datas_no_futuro(self):
        futuros = [self.auto(f'auto-ml-209901{d:02d}-120000.db') for d in range(1, 6)]
        novo = os.path.basename(self.assert_ok(*self.rodar('--motivo', 'ml', '--manter', '3')))
        autos = set(n for n in self.backups() if n.startswith('auto-'))
        self.assertEqual(autos, {novo, *futuros[2:]})

    def test_link_simbolico_com_data_nova_nao_ocupa_vaga(self):
        # Se o link contasse como backup, tomaria uma das 3 vagas e um backup de verdade sairia.
        reais = [self.auto(f'auto-ml-202601{d:02d}-120000.db') for d in range(1, 4)]
        alvo = os.path.join(self.fora, 'alvo.db')
        criar(alvo, b'alvo')
        link = os.path.join(self.pasta, 'auto-ml-20990101-000000.db')
        os.symlink(alvo, link)
        novo = os.path.basename(self.assert_ok(*self.rodar('--motivo', 'ml', '--manter', '3')))
        restantes = set(self.backups())
        self.assertEqual({n for n in restantes if not os.path.islink(os.path.join(self.pasta, n))},
                         {novo, reais[2], reais[1]})
        self.assertTrue(os.path.islink(link))
        with open(alvo, 'rb') as f:
            self.assertEqual(f.read(), b'alvo')

    def test_rotacao_nao_roda_quando_o_backup_falha(self):
        velhos = [self.auto(f'auto-ml-202601{d:02d}-120000.db') for d in range(1, 21)]
        con = sqlite3.connect(self.db)
        con.execute('DELETE FROM items')
        con.commit()
        con.close()
        codigo, out, err = self.rodar('--motivo', 'ml', '--manter', '3')
        self.assertEqual(codigo, 1)
        self.assertEqual(out, '')
        self.assertEqual(self.backups(), sorted(velhos))

    def test_falha_na_rotacao_avisa_e_mantem_o_backup(self):
        for d in range(1, 6):
            self.auto(f'auto-ml-202601{d:02d}-120000.db')
        with mock.patch.object(B, 'rotacionar', side_effect=PermissionError(13, 'negado')):
            codigo, out, err = self.rodar_aqui('--motivo', 'ml', '--manter', '3')
        self.assertEqual(codigo, 0)
        self.assertIsNotNone(RE_SAIDA.fullmatch(out))
        self.assertIn('AVISO: a rotação', err)
        self.assertEqual(len([n for n in self.backups() if n.startswith('auto-')]), 6)


class Falhas(Base):
    def test_banco_corrompido_sai_com_1(self):
        con = sqlite3.connect(self.db)
        con.execute('PRAGMA page_size=4096')
        con.execute('CREATE TABLE items (id INTEGER PRIMARY KEY, titulo TEXT)')
        con.execute('CREATE TABLE numeros (id INTEGER PRIMARY KEY, telefone TEXT)')
        con.executemany('INSERT INTO items (titulo) VALUES (?)', [('Produto 0 ' + 'y' * 200,)] * 300)
        con.execute('INSERT INTO numeros (telefone) VALUES (?)', (TELEFONE,))
        con.commit()
        con.close()
        self.assertGreater(os.path.getsize(self.db), 4096 * 6)
        with open(self.db, 'r+b') as f:   # estraga páginas no meio da tabela items
            f.seek(4096 * 3)
            f.write(b'\xa5' * 4096 * 2)
        self.assert_falhou(*self.rodar('--motivo', 'ml'))

    def test_integrity_check_reprova_mesmo_com_items_legivel(self):
        # Páginas órfãs: o COUNT(items) funciona, só o integrity_check acusa.
        semear(self.db)
        con = sqlite3.connect(self.db)
        con.execute('CREATE TABLE lixo (t TEXT)')
        con.executemany('INSERT INTO lixo VALUES (?)', [('z' * 200,)] * 100)
        con.commit()
        con.execute('PRAGMA writable_schema=ON')
        con.execute("DELETE FROM sqlite_schema WHERE name = 'lixo'")
        con.commit()
        con.close()
        con = sqlite3.connect(self.db)
        try:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM items').fetchone()[0], 3)
            self.assertNotEqual(con.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        finally:
            con.close()
        codigo, out, err = self.rodar('--motivo', 'ml')
        self.assert_falhou(codigo, out, err)
        self.assertIn('integrity_check', err)

    def test_copia_que_deixa_wal_solto_e_recusada_e_limpa(self):
        semear(self.db)
        copiar = B.copiar

        def copiar_e_sujar(db, destino):
            copiar(db, destino)
            criar(destino + '-wal', b'')

        with mock.patch.object(B, 'copiar', side_effect=copiar_e_sujar):
            codigo, out, err = self.rodar_aqui('--motivo', 'ml')
        self.assert_falhou(codigo, out, err)
        self.assertIn('-wal', err)
        self.assertEqual(self.backups(), [])

    def test_arquivo_que_nao_e_banco_sai_com_1(self):
        criar(self.db, b'isto nao e um banco sqlite ' * 200)
        self.assert_falhou(*self.rodar('--motivo', 'ml'))

    def test_banco_sem_itens_sai_com_1(self):
        semear(self.db, itens=0)
        self.assert_falhou(*self.rodar('--motivo', 'ml'))

    def test_banco_sem_tabela_items_sai_com_1(self):
        con = sqlite3.connect(self.db)
        con.execute('CREATE TABLE numeros (telefone TEXT)')
        con.execute('INSERT INTO numeros VALUES (?)', (TELEFONE,))
        con.commit()
        con.close()
        self.assert_falhou(*self.rodar('--motivo', 'ml'))

    def test_banco_inexistente_sai_com_1_sem_criar_pasta(self):
        codigo, out, err = self.rodar('--motivo', 'ml')
        self.assertEqual(codigo, 1)
        self.assertEqual(out, '')
        self.assertIn('banco não encontrado', err)
        self.assertFalse(os.path.lexists(self.pasta))
        self.assertFalse(os.path.lexists(self.db))

    def test_parcial_apagado_em_falha(self):
        semear(self.db)
        vistos = []

        def falhar(caminho):
            vistos.append((os.path.basename(caminho), os.path.isfile(caminho)))
            raise sqlite3.DatabaseError('database disk image is malformed')

        with mock.patch.object(B, 'conferir', side_effect=falhar):
            self.assert_falhou(*self.rodar_aqui('--motivo', 'ml'))
        self.assertEqual(len(vistos), 1)
        self.assertTrue(vistos[0][0].endswith('.db.parcial') and vistos[0][1], 'o .parcial existia')
        self.assertEqual(self.backups(), [])

    def test_parcial_apagado_quando_interrompido_por_sigterm(self):
        semear(self.db)
        conferir = B.conferir

        def interromper(caminho):
            n = conferir(caminho)
            os.kill(os.getpid(), signal.SIGTERM)
            return n

        def tratador_do_teste(signum, frame):
            raise AssertionError('o SIGTERM devia ir para o backup_banco')

        self.addCleanup(signal.signal, signal.SIGTERM, signal.getsignal(signal.SIGTERM))
        signal.signal(signal.SIGTERM, tratador_do_teste)
        with mock.patch.object(B, 'conferir', side_effect=interromper):
            self.assert_falhou(*self.rodar_aqui('--motivo', 'ml'))
        self.assertEqual(self.backups(), [])
        self.assertIs(signal.getsignal(signal.SIGTERM), tratador_do_teste, 'o tratador antigo volta')

    def test_sigterm_depois_do_link_nao_diz_que_nada_foi_gravado(self):
        """R5 (rodada 2): o SIGTERM entre o os.link e o retorno deixa o backup publicado. A mensagem não pode
        dizer "nenhum backup novo foi gravado": manda conferir backups/."""
        semear(self.db)
        link = os.link

        def link_e_sigterm(*a, **kw):
            link(*a, **kw)
            os.kill(os.getpid(), signal.SIGTERM)

        def tratador_do_teste(signum, frame):
            raise AssertionError('o SIGTERM devia ir para o backup_banco')

        self.addCleanup(signal.signal, signal.SIGTERM, signal.getsignal(signal.SIGTERM))
        signal.signal(signal.SIGTERM, tratador_do_teste)
        with mock.patch.object(B.os, 'link', side_effect=link_e_sigterm):
            codigo, out, err = self.rodar_aqui('--motivo', 'ml')
        self.assertEqual(codigo, 1)
        self.assertEqual(out, '')
        self.assertEqual(err, 'ERRO: backup interrompido; confira backups/\n')
        # o arquivo publicado ficou (completo e conferido), sem .parcial
        nomes = self.backups()
        self.assertEqual(len(nomes), 1, nomes)
        self.assertIsNotNone(B.RE_AUTO.fullmatch(nomes[0]))
        con = sqlite3.connect(os.path.join(self.pasta, nomes[0]))
        try:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM items').fetchone()[0], 3)
        finally:
            con.close()

    def test_espaco_livre_exige_o_dobro_do_banco(self):
        con = semear(self.db, manter_aberto=True)   # o -wal ainda tem dados e entra na conta
        self.addCleanup(con.close)
        self.assertGreater(os.path.getsize(self.db + '-wal'), 0)
        dobro = 2 * (os.path.getsize(self.db) + os.path.getsize(self.db + '-wal'))
        with mock.patch.object(B, 'espaco_livre', return_value=dobro - 1):
            codigo, out, err = self.rodar_aqui('--motivo', 'ml')
        self.assertEqual(codigo, 1)
        self.assertEqual(out, '')
        self.assertIn('espaço livre', err)
        self.assertEqual(self.backups(), [])
        with mock.patch.object(B, 'espaco_livre', return_value=dobro):
            self.assert_ok(*self.rodar_aqui('--motivo', 'ml'))

    def test_falha_de_escrita_sai_com_1_sem_parcial(self):
        semear(self.db)
        with mock.patch.object(B.os, 'fsync', side_effect=OSError(5, 'E/S')):
            codigo, out, err = self.rodar_aqui('--motivo', 'ml')
        self.assertEqual(codigo, 1)
        self.assertIn('OSError ao gravar o backup', err)
        self.assertEqual(self.backups(), [])


class Uso(Base):
    def assert_uso_invalido(self, *args):
        semear(self.db)
        codigo, out, err = self.rodar(*args)
        self.assertEqual(codigo, 2, (args, err))
        self.assertEqual(out, '')
        self.assertFalse(os.path.lexists(self.pasta), args)

    def test_motivo_invalido_sai_com_2(self):
        for motivo in ('', 'ML', 'a/b', '../x', 'a' * 31, 'á', 'x y', 'a_b', 'a.b', 'a\nb', '٣'):
            with self.subTest(motivo=motivo):
                self.assert_uso_invalido(f'--motivo={motivo}')
                shutil.rmtree(self.dir)
                os.mkdir(self.dir)

    def test_sem_motivo_sai_com_2(self):
        self.assert_uso_invalido()

    def test_abreviacao_e_argumento_solto_saem_com_2(self):
        for args in (('--mot', 'ml'), ('--motivo', 'ml', 'extra')):
            with self.subTest(args=args):
                self.assert_uso_invalido(*args)
                shutil.rmtree(self.dir)
                os.mkdir(self.dir)

    def test_manter_abaixo_de_3_ou_invalido_sai_com_2(self):
        for n in ('2', '0', '-1', 'abc', '3.0', '', '٣', ' 3'):
            with self.subTest(manter=n):
                self.assert_uso_invalido('--motivo', 'ml', f'--manter={n}')
                shutil.rmtree(self.dir)
                os.mkdir(self.dir)

    def test_manter_3_aceito(self):
        semear(self.db)
        self.assert_ok(*self.rodar('--motivo', 'ml', '--manter', '3'))


if __name__ == '__main__':
    unittest.main()
