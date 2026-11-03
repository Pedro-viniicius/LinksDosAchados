#!/usr/bin/env python3
"""Testes do migrar_categorias.py (docs/produto/planos/eletronicos-e-coleta-ml.md, etapa 2).

Uso:  python3 testes/test_migrar_categorias.py -v

O script roda como subprocesso com ACHADINHOS_DB num banco temporário semeado (nunca o
achadinhos.db real: `ambiente()` de test_servidor.py recusa) e sem rede (proxy morto).
A guarda do banco real é provada numa cópia do projeto dentro de um diretório temporário.
Só biblioteca padrão.
"""
import atexit
import contextlib
import hashlib
import io
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import unicodedata
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_servidor as TS  # noqa: E402  (ambiente, porta_livre, ServidorTeste, RAIZ, DB_REAL)

# Antes de importar o servidor: o S.DB deste processo aponta para um temporário, nunca o real.
TMP_AMBIENTE = tempfile.mkdtemp(prefix='achadinhos-migrar-env-')
atexit.register(shutil.rmtree, TMP_AMBIENTE, ignore_errors=True)
os.environ['ACHADINHOS_DB'] = os.path.join(TMP_AMBIENTE, 'nunca-usado.db')
sys.path.insert(0, TS.RAIZ)
import servidor as S  # noqa: E402
import migrar_categorias as M  # noqa: E402

assert os.path.dirname(S.DB) == TMP_AMBIENTE, 'o teste não pode tocar o banco real'

SCRIPT = os.path.join(TS.RAIZ, 'migrar_categorias.py')
ELETRONICOS = 'Black Friday | Eletrônicos'
ELETRODOMESTICOS = 'Eletrodomésticos'
CASA = 'Casa e Decoração'

# (loja, item_id, cat, busca, cat esperada depois da migração)
SEMENTE = [
    ('amazon', 'W1', 'Lista WhatsApp', '', 'Lista WhatsApp'),
    ('amazon', 'W2', 'Lista WhatsApp', 'Geladeira', 'Lista WhatsApp'),   # termo mapeado, mas fora das origens
    ('amazon', 'B1', 'Black Friday', 'iPhone 17', ELETRONICOS),
    ('ml', 'MLB1', 'Black Friday', 'iPhone 17', ELETRONICOS),
    ('ml', 'MLB2', 'Black Friday', 'Caixa inteligente assistente virtual', ELETRONICOS),   # ALIAS
    ('amazon', 'B2', 'Black Friday', 'Smart speaker Alexa', ELETRONICOS),
    ('amazon', 'C1', 'Casa Nova', 'Smart TV', ELETRONICOS),
    ('ml', 'MLB3', 'Casa Nova', 'Geladeira', ELETRODOMESTICOS),
    ('amazon', 'C2', 'Casa Nova', 'Máquina de lavar', ELETRODOMESTICOS),
    ('amazon', 'C3', 'Casa Nova', 'Sofá', CASA),
    ('ml', 'MLB4', 'Casa Nova', 'Jogo de panelas', CASA),
    ('ml', 'MLB5', 'Casa Nova', unicodedata.normalize('NFD', 'Sofá'), CASA),  # acento decomposto no banco
]
ESPERADO = {s[1]: s[4] for s in SEMENTE}
ANTIGO = '2026-01-01T00:00:00'


def semear(db):
    """Cria o esquema do servidor.py (se faltar) e grava a SEMENTE num banco temporário."""
    if os.path.realpath(db) == TS.DB_REAL:
        raise RuntimeError('o teste tentou semear o banco real')
    with mock.patch.object(S, 'DB', db):
        S.criar_banco()
    con = sqlite3.connect(db)
    for pos, (loja, iid, cat, busca, _) in enumerate(SEMENTE, 1):
        url = (f'https://www.amazon.com.br/dp/{iid}?tag={S.TAG_AMAZON}' if loja == 'amazon'
               else f'https://meli.la/{iid}x')
        dados = {c: f'{c} de {iid}' for c in S.CAMPOS}
        con.execute(f'INSERT INTO items (loja,item_id,cat,busca,url,{",".join(S.CAMPOS)},tem_dados,posicao,'
                    f'criado_em,atualizado_em) VALUES (?,?,?,?,?,{",".join("?" * len(S.CAMPOS))},1,?,?,?)',
                    (loja, iid, cat, busca, url, *dados.values(), pos, ANTIGO, ANTIGO))
    con.commit()
    con.close()


def linhas(db):
    """{item_id: linha inteira} lida só para leitura."""
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
    con.row_factory = sqlite3.Row
    try:
        return {r['item_id']: dict(r) for r in con.execute('SELECT * FROM items')}
    finally:
        con.close()


def sha(caminho):
    with open(caminho, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


def rodar(db, *args, porta=None, env=None, script=SCRIPT, cwd=TS.RAIZ):
    """Roda o script num subprocesso, sem terminal (stdin vazio), e devolve o CompletedProcess."""
    env = env or TS.ambiente(db, porta or TS.porta_livre())
    return subprocess.run([sys.executable, script, *args], cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, timeout=60)


def backups(pasta):
    d = os.path.join(pasta, 'backups')
    return sorted(os.path.join(d, f) for f in os.listdir(d) if f.endswith('.db')) if os.path.isdir(d) else []


class BancoTemporario(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix='achadinhos-migrar-')
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.db = os.path.join(self.dir, 'teste.db')
        semear(self.db)
        self.antes = linhas(self.db)

    def rodar(self, *args, **kw):
        return rodar(self.db, *args, **kw)

    def assertOk(self, r):
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def assertMigrado(self, depois):
        """CA2: cada item na aba certa e, fora `cat` e `atualizado_em` dos movidos, tudo igual."""
        self.assertEqual(set(depois), set(self.antes))
        for iid, antes in self.antes.items():
            d = depois[iid]
            self.assertEqual(d['cat'], ESPERADO[iid], iid)
            movido = antes['cat'] != ESPERADO[iid]
            for col, valor in antes.items():
                if col == 'cat' or (col == 'atualizado_em' and movido):
                    continue
                self.assertEqual(d[col], valor, f'{iid}.{col} mudou')
            if movido:
                self.assertNotEqual(d['atualizado_em'], ANTIGO, iid)
        self.assertFalse({d['cat'] for d in depois.values()} & set(M.ORIGENS))


class TestMigracao(BancoTemporario):

    def test_dry_run_mostra_contagens_e_nao_grava(self):
        h = sha(self.db)
        r = self.rodar('--dry-run')
        self.assertOk(r)
        out = r.stdout
        self.assertIn(f'De "Black Friday" para "{ELETRONICOS}": 4 itens (amazon 2, ml 2)', out)
        self.assertIn(f'De "Casa Nova" para "{ELETRONICOS}": 1 itens (amazon 1)', out)
        self.assertIn(f'De "Casa Nova" para "{ELETRODOMESTICOS}": 2 itens (amazon 1, ml 1)', out)
        self.assertIn(f'De "Casa Nova" para "{CASA}": 3 itens (amazon 1, ml 2)', out)
        self.assertIn('    iPhone 17: amazon 1, ml 1', out)
        self.assertIn('    Caixa inteligente assistente virtual (alias de "Smart speaker Alexa"): ml 1', out)
        self.assertIn(f'    "{ELETRONICOS}": 5 itens (amazon 3, ml 2)', out)
        self.assertIn('Total a mover: 10', out)
        self.assertIn('Não muda: "Lista WhatsApp" (2 itens)', out)
        self.assertIn('nada foi gravado', out)
        self.assertEqual(linhas(self.db), self.antes)
        self.assertEqual(sha(self.db), h)
        self.assertFalse(os.path.exists(os.path.join(self.dir, 'backups')))

    def test_migra_para_os_tres_destinos_e_mantem_o_resto(self):
        r = self.rodar()
        self.assertOk(r)
        self.assertIn('Migração concluída: 10 itens movidos.', r.stdout)
        self.assertMigrado(linhas(self.db))
        # "Lista WhatsApp" intocada, inclusive o item com termo mapeado
        self.assertEqual(linhas(self.db)['W2'], self.antes['W2'])

    def test_item_sem_destino_aborta_sem_gravar(self):
        con = sqlite3.connect(self.db)
        cur = con.execute("INSERT INTO items (loja,item_id,cat,busca,url,posicao) VALUES "
                          "('ml','MLB9','Casa Nova','Termo que não existe','https://meli.la/z',99)")
        novo_id = cur.lastrowid
        con.commit()
        con.close()
        antes = linhas(self.db)
        for args in ((), ('--dry-run',)):
            r = self.rodar(*args)
            self.assertEqual(r.returncode, 1, args)
            self.assertIn(f'id={novo_id} loja=ml cat="Casa Nova" busca="Termo que não existe"', r.stderr)
            self.assertIn('Nada foi gravado', r.stderr)
            self.assertEqual(linhas(self.db), antes)
            self.assertFalse(os.path.exists(os.path.join(self.dir, 'backups')))

    def test_backup_integro_antes_de_gravar(self):
        porta = TS.porta_livre()
        r = self.rodar(porta=porta)
        self.assertOk(r)
        bks = backups(self.dir)
        self.assertEqual(len(bks), 1)
        self.assertRegex(os.path.basename(bks[0]), r'\Aachadinhos-\d{8}-\d{6}\.db\Z')
        con = sqlite3.connect(bks[0])
        self.assertEqual(con.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        self.assertEqual(con.execute('SELECT COUNT(*) FROM items').fetchone()[0], len(self.antes))
        con.close()
        self.assertEqual(linhas(bks[0]), self.antes)   # o backup é o estado de antes da migração
        self.assertIn(f'Backup: {bks[0]}', r.stdout)
        cmd = f'ACHADINHOS_DB={self.db} ACHADINHOS_PORTA={porta} python3 {SCRIPT} --restaurar {bks[0]}'
        self.assertIn(f'Para reverter (com o servidor parado): {cmd}\n', r.stdout)

    def test_comando_de_reverter_impresso_funciona_de_outra_pasta(self):
        """R1: o comando leva ACHADINHOS_DB, ACHADINHOS_PORTA e o caminho absoluto do script."""
        r = self.rodar()
        self.assertOk(r)
        cmd = re.search(r'^Para reverter \(com o servidor parado\): (.+)$', r.stdout, re.M).group(1)
        # Sem o prefixo do comando, o script cairia neste banco isca (e o teste veria).
        isca = os.path.join(self.dir, 'isca.db')
        outra = os.path.join(self.dir, 'outra-pasta')
        os.mkdir(outra)
        r = subprocess.run(cmd, shell=True, cwd=outra, env=TS.ambiente(isca), stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, timeout=60)
        self.assertOk(r)
        self.assertEqual(linhas(self.db), self.antes)
        self.assertFalse(os.path.exists(isca))

    def test_segunda_execucao_move_zero_e_nao_cria_backup(self):
        self.assertOk(self.rodar())
        depois = linhas(self.db)
        r = self.rodar()
        self.assertOk(r)
        self.assertIn('Nada a migrar: 0 itens movidos. Nenhum backup foi criado.', r.stdout)
        self.assertEqual(len(backups(self.dir)), 1)
        self.assertEqual(linhas(self.db), depois)

    def test_falha_ao_criar_backup_nao_migra(self):
        with open(os.path.join(self.dir, 'backups'), 'w'):   # arquivo no lugar da pasta: makedirs falha
            pass
        r = self.rodar()
        self.assertEqual(r.returncode, 1)
        self.assertIn('backup falhou', r.stderr)
        self.assertEqual(linhas(self.db), self.antes)

    def test_backup_reprovado_na_verificacao_nao_migra(self):
        self.assertNotEqual(os.path.realpath(self.db), TS.DB_REAL)
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(S, 'DB', self.db), \
                mock.patch.object(M, 'verificar_backup', return_value='integrity_check deu "corrompido"'), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(M.main([]), 1)
        self.assertIn('backup falhou (integrity_check deu "corrompido"); nada foi migrado', err.getvalue())
        self.assertEqual(linhas(self.db), self.antes)
        self.assertEqual(backups(self.dir), [])   # o backup reprovado é apagado

    def test_restaurar_com_servidor_parado_volta_ao_backup(self):
        self.assertOk(self.rodar())
        bk = backups(self.dir)[0]
        migrado = linhas(self.db)
        r = self.rodar('--restaurar', bk)   # porta livre: nenhum servidor no ar
        self.assertOk(r)
        self.assertIn('restaurado', r.stdout)
        self.assertEqual(linhas(self.db), self.antes)
        # R3: antes de sobrescrever, o estado de agora (já migrado) foi guardado e verificado
        novos = [b for b in backups(self.dir) if b != bk]
        self.assertEqual(len(novos), 1)
        self.assertIn(f'Backup do estado atual (antes de restaurar): {novos[0]}', r.stdout)
        self.assertEqual(linhas(novos[0]), migrado)

    def test_restaurar_sem_conseguir_guardar_o_estado_atual_nao_restaura(self):
        self.assertOk(self.rodar())
        bk = shutil.move(backups(self.dir)[0], os.path.join(self.dir, 'bk.db'))
        shutil.rmtree(os.path.join(self.dir, 'backups'))
        with open(os.path.join(self.dir, 'backups'), 'w'):   # arquivo no lugar da pasta
            pass
        migrado = linhas(self.db)
        r = self.rodar('--restaurar', bk)
        self.assertEqual(r.returncode, 1)
        self.assertIn('backup falhou', r.stderr)
        self.assertIn('nada foi restaurado', r.stderr)
        self.assertEqual(linhas(self.db), migrado)

    def test_restaurar_recusa_arquivo_invalido_ou_inexistente(self):
        self.assertOk(self.rodar())
        depois = linhas(self.db)
        lixo = os.path.join(self.dir, 'lixo.db')
        with open(lixo, 'wb') as f:
            f.write(b'isto nao e um banco sqlite' * 100)
        for arquivo in (lixo, os.path.join(self.dir, 'nao-existe.db'), self.db):
            r = self.rodar('--restaurar', arquivo)
            self.assertEqual(r.returncode, 1, arquivo)
            self.assertIn('ERRO', r.stderr)
            self.assertEqual(linhas(self.db), depois)
        self.assertEqual(len(backups(self.dir)), 1)   # recusa antes do backup do estado atual

    def test_texto_do_banco_sai_sem_caracteres_de_controle(self):
        """S1: `cat` e `busca` com sequência de escape do terminal saem como \\xNN."""
        self.assertEqual(M.seguro('a\x1b[2K\n\tÁ'), 'a\\x1b[2K\\x0a\\x09Á')
        con = sqlite3.connect(self.db)
        con.execute("INSERT INTO items (loja,item_id,cat,busca,url,posicao) VALUES "
                    "('ml','ESC1','Aba\x1b[2K','','https://meli.la/e',98)")
        con.commit()
        r = self.rodar('--dry-run')
        self.assertOk(r)
        self.assertIn('Não muda: "Aba\\x1b[2K" (1 itens)', r.stdout)
        r = self.rodar()
        self.assertOk(r)
        self.assertIn('"Aba\\x1b[2K" | ml: 1', r.stdout)
        self.assertNotIn('\x1b', r.stdout + r.stderr)
        cur = con.execute("INSERT INTO items (loja,item_id,cat,busca,url,posicao) VALUES "
                          "('ml','ESC2','Casa Nova','x\x1b[2Ky','https://meli.la/f',99)")
        con.commit()
        con.close()
        r = self.rodar()
        self.assertEqual(r.returncode, 1)
        self.assertIn(f'id={cur.lastrowid} loja=ml cat="Casa Nova" busca="x\\x1b[2Ky"', r.stderr)
        self.assertNotIn('\x1b', r.stdout + r.stderr)

    def test_banco_inexistente_nao_e_criado(self):
        db = os.path.join(self.dir, 'nao-existe.db')
        r = rodar(db, '--dry-run')
        self.assertEqual(r.returncode, 1)
        self.assertIn('banco não encontrado', r.stderr)
        self.assertFalse(os.path.exists(db))


class TestComServidorNoAr(TS.ServidorTeste):
    """CA6 e a recusa do --restaurar: servidor.py de verdade sobre o banco temporário."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        semear(cls.db)

    def cats(self):
        return {i['item_id']: i['cat'] for i in self.itens()}

    def test_1_migra_com_servidor_no_ar_e_get_mostra_abas_novas(self):
        self.assertEqual(set(self.cats().values()), {'Lista WhatsApp', 'Black Friday', 'Casa Nova'})
        r = rodar(self.db, porta=self.porta)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.cats(), ESPERADO)   # logo depois, sem reiniciar o servidor
        self.assertIsNone(self.proc.poll())

    def test_2_restaurar_recusa_com_servidor_no_ar(self):
        bk = os.path.join(self.dir, 'copia.db')
        src, dst = sqlite3.connect(self.db), sqlite3.connect(bk)
        src.backup(dst)
        dst.close()
        src.close()
        con = sqlite3.connect(self.db)
        con.execute("UPDATE items SET busca='mudou depois do backup' WHERE item_id='W1'")
        con.commit()
        con.close()
        antes = linhas(self.db)
        r = rodar(self.db, '--restaurar', bk, porta=self.porta)
        self.assertEqual(r.returncode, 1)
        self.assertIn(f'o servidor está no ar na porta {self.porta}', r.stderr)
        self.assertEqual(linhas(self.db), antes)


class TestGuardaBancoReal(unittest.TestCase):
    """Gravar no banco "real" (achadinhos.db ao lado do script) exige --sim ou "sim" no terminal.

    Prova numa cópia do projeto: servidor.py, migrar_categorias.py e buscas.json num diretório
    temporário, com um achadinhos.db semeado. ACHADINHOS_DB aponta para esse arquivo, então mesmo
    um erro no teste nunca alcança o banco real.
    """

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix='achadinhos-guarda-')
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        for f in ('servidor.py', 'migrar_categorias.py', 'buscas.json'):
            shutil.copy(os.path.join(TS.RAIZ, f), self.dir)
        # No banco "real", o --restaurar também testa a 8765, onde o servidor do dono pode estar no
        # ar. Na cópia, a porta padrão vira uma porta livre: o resultado não depende da máquina.
        copia = os.path.join(self.dir, 'migrar_categorias.py')
        with open(copia, encoding='utf-8') as f:
            codigo = f.read()
        self.assertIn('\nPORTA_PADRAO = 8765 ', codigo)
        with open(copia, 'w', encoding='utf-8') as f:
            f.write(codigo.replace('\nPORTA_PADRAO = 8765 ', f'\nPORTA_PADRAO = {TS.porta_livre()} ', 1))
        self.db = os.path.join(self.dir, 'achadinhos.db')
        semear(self.db)
        self.antes = linhas(self.db)
        self.env = TS.ambiente(self.db, TS.porta_livre())
        self.env.pop('PYTHONPATH', None)

    def rodar(self, *args):
        r = rodar(self.db, *args, env=self.env, script=os.path.join(self.dir, 'migrar_categorias.py'),
                  cwd=self.dir)
        self.assertIn(f'{self.dir}', r.stdout + r.stderr)   # rodou a cópia, sobre o banco da cópia
        return r

    def test_sem_confirmacao_recusa_e_nao_grava(self):
        r = self.rodar()
        self.assertEqual(r.returncode, 1)
        self.assertIn('exige confirmação', r.stderr)
        self.assertEqual(linhas(self.db), self.antes)
        self.assertEqual(backups(self.dir), [])

    def test_dry_run_nao_pede_confirmacao(self):
        r = self.rodar('--dry-run')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(linhas(self.db), self.antes)

    def test_sim_migra_e_restaurar_tambem_exige_confirmacao(self):
        r = self.rodar('--sim')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual({k: v['cat'] for k, v in linhas(self.db).items()}, ESPERADO)
        bk = backups(self.dir)[0]
        self.assertNotIn('ACHADINHOS_DB=', r.stdout)   # no banco real, o comando não troca o banco
        porta = self.env['ACHADINHOS_PORTA']
        self.assertIn(f'ACHADINHOS_PORTA={porta} python3 {self.dir}/migrar_categorias.py --restaurar {bk}\n',
                      r.stdout)
        depois = linhas(self.db)
        r = self.rodar('--restaurar', bk)
        self.assertEqual(r.returncode, 1)
        self.assertIn('exige confirmação', r.stderr)
        self.assertEqual(linhas(self.db), depois)
        r = self.rodar('--restaurar', bk, '--sim')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(linhas(self.db), self.antes)

    def test_restaurar_no_banco_real_recusa_com_servidor_na_porta_padrao(self):
        """S2: com ACHADINHOS_PORTA noutra porta, o servidor do dia a dia (8765) ainda bloqueia.

        A 8765 de verdade pode ou não estar no ar: o teste troca a PORTA_PADRAO por uma porta
        onde ele mesmo escuta.
        """
        self.assertNotEqual(os.path.realpath(self.db), TS.DB_REAL)
        bk = os.path.join(self.dir, 'bk.db')
        src, dst = sqlite3.connect(self.db), sqlite3.connect(bk)
        src.backup(dst)
        dst.close()
        src.close()
        with socket.socket() as escuta:
            escuta.bind(('127.0.0.1', 0))
            escuta.listen()
            padrao = escuta.getsockname()[1]
            outra = TS.porta_livre()
            err = io.StringIO()
            with mock.patch.object(S, 'BASE', self.dir), mock.patch.object(S, 'DB', self.db), \
                    mock.patch.object(S, 'PORT', outra), mock.patch.object(M, 'PORTA_PADRAO', padrao), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
                self.assertEqual(M.portas_a_testar(), sorted({outra, padrao}))
                self.assertEqual(M.main(['--restaurar', bk, '--sim']), 1)
                with mock.patch.object(S, 'DB', bk):   # banco que não é o real: só a S.PORT
                    self.assertEqual(M.portas_a_testar(), [outra])
        self.assertIn(f'o servidor está no ar na porta {padrao}', err.getvalue())
        self.assertIn('coletar_amazon.py', err.getvalue())
        self.assertEqual(linhas(self.db), self.antes)
        self.assertEqual(backups(self.dir), [])

    def test_prompt_no_terminal(self):
        """No terminal, só "sim" grava; qualquer outra resposta cancela."""
        self.assertNotEqual(os.path.realpath(self.db), TS.DB_REAL)
        terminal = mock.Mock(isatty=mock.Mock(return_value=True))
        with mock.patch.object(S, 'BASE', self.dir), mock.patch.object(S, 'DB', self.db), \
                mock.patch.object(M.sys, 'stdin', terminal), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as err:
            with mock.patch('builtins.input', return_value='não') as perguntou:
                self.assertEqual(M.main([]), 1)
            perguntou.assert_called_once()
            self.assertIn('cancelado', err.getvalue())
            self.assertEqual(linhas(self.db), self.antes)
            with mock.patch('builtins.input', return_value='sim'):
                self.assertEqual(M.main([]), 0)
        self.assertEqual({k: v['cat'] for k, v in linhas(self.db).items()}, ESPERADO)


if __name__ == '__main__':
    unittest.main()
