#!/usr/bin/env python3
"""Testes do classificar_lista.py (docs/produto/planos/disparo-automatico.md, etapa 6, CA12).

Uso:  python3 testes/test_classificar_lista.py -v

O script roda como subprocesso com ACHADINHOS_DB num banco temporário semeado com os 74 itens do
lista_whatsapp.json (nunca o achadinhos.db real: `ambiente()` de test_servidor.py recusa) e sem rede
(proxy morto). A guarda do banco real é provada numa cópia do projeto num diretório temporário.
Só biblioteca padrão.
"""
import contextlib
import io
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# Importa antes do servidor: test_migrar_categorias põe ACHADINHOS_DB num temporário.
import test_migrar_categorias as T  # noqa: E402  (linhas, sha, backups, rodar, TMP_AMBIENTE)
import test_servidor as TS  # noqa: E402
import servidor as S  # noqa: E402
import migrar_categorias as M  # noqa: E402
import classificar_lista as C  # noqa: E402

assert os.path.dirname(S.DB) == T.TMP_AMBIENTE, 'o teste não pode tocar o banco real'

SCRIPT = os.path.join(TS.RAIZ, 'classificar_lista.py')
SCRIPT_MIGRAR = os.path.join(TS.RAIZ, 'migrar_categorias.py')
ORIGEM = 'Lista WhatsApp'
DESTINO = 'Black Friday | Eletrônicos'
ANTIGO = T.ANTIGO

# Mapa da etapa 6 copiado do plano (busca -> ids). O lista_whatsapp.json tem que bater com ele.
MAPA_PLANO = {
    'Console de videogame': [9],
    'Controle acessório videogame': [10, 11, 12, 17, 23, 42],
    'Fone de ouvido Bluetooth': [2, 4],
    'Headset gamer': [16],
    'Teclado e mouse': [13, 15, 37, 38, 39, 40, 41, 44, 48],
    'Monitor': [22, 36],
    'Smart TV': [24],
    'Smart TV 4K': [25, 26, 27],
    'Notebook': [28, 29, 30, 33],
    'Computador gamer': [34],
    'Tablet': [31],
    'Celular smartphone': [18],
    'SSD': [54, 57, 58],
    'HD externo': [53, 62, 63],
    'Roteador Wi-Fi mesh': [52, 65, 66, 67, 68, 129, 130, 131, 133],
    'Carregador portátil power bank': [20],
    'Acessórios de informática': [8, 43, 45, 46, 47, 49, 50, 51, 55, 56, 59, 60, 61, 64, 132],
    'Capas e acessórios': [5, 6, 7, 14, 19],
    'Câmeras': [1, 3, 21],
    'Computador e peças': [32, 35, 134],
}
SUBTEMAS_NOVOS = {'Acessórios de informática', 'Capas e acessórios', 'Câmeras', 'Computador e peças'}

with open(C.MAPA, encoding='utf-8') as _f:
    MAPA = {int(k): v for k, v in json.load(_f).items()}

# Itens fora do mapa: (id, loja, item_id, cat, busca). Nenhum pode mudar.
OUTROS = [
    (1001, 'amazon', 'BFE1', DESTINO, 'Monitor'),
    (1002, 'ml', 'MLB1', 'Casa e Decoração', 'Sofá'),
    (1003, 'amazon', 'BFE2', DESTINO, 'Notebook'),
]


def inserir(con, _id, loja, item_id, cat, busca, pos):
    url = (f'https://www.amazon.com.br/dp/{item_id}?tag={S.TAG_AMAZON}' if loja == 'amazon'
           else f'https://meli.la/{item_id}x')
    dados = {c: f'{c} de {item_id}' for c in S.CAMPOS}
    con.execute(f'INSERT INTO items (id,loja,item_id,cat,busca,url,{",".join(S.CAMPOS)},tem_dados,posicao,'
                f'criado_em,atualizado_em) VALUES (?,?,?,?,?,?,{",".join("?" * len(S.CAMPOS))},1,?,?,?)',
                (_id, loja, item_id, cat, busca, url, *dados.values(), pos, ANTIGO, ANTIGO))


def semear(db, outros=OUTROS):
    """Esquema do servidor.py e os 74 itens do mapa em "Lista WhatsApp" (busca 'WhatsApp'), mais `outros`."""
    if os.path.realpath(db) == TS.DB_REAL:
        raise RuntimeError('o teste tentou semear o banco real')
    with mock.patch.object(S, 'DB', db):
        S.criar_banco()
    con = sqlite3.connect(db)
    for pos, (_id, m) in enumerate(sorted(MAPA.items()), 1):
        inserir(con, _id, 'amazon', m['item_id'], ORIGEM, 'WhatsApp', pos)
    for pos, linha in enumerate(outros, 500):
        inserir(con, *linha, pos)
    con.commit()
    con.close()


def executar(db, sql, *params):
    con = sqlite3.connect(db)
    try:
        con.execute(sql, params)
        con.commit()
    finally:
        con.close()


def rodar(db, *args, **kw):
    kw.setdefault('script', SCRIPT)
    return T.rodar(db, *args, **kw)


class BancoTemporario(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix='achadinhos-classificar-')
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.db = os.path.join(self.dir, 'teste.db')
        semear(self.db)
        self.antes = T.linhas(self.db)
        self.por_id = {v['id']: k for k, v in self.antes.items()}   # id -> item_id

    def rodar(self, *args, **kw):
        return rodar(self.db, *args, **kw)

    def assertOk(self, r):
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def assertNadaMudou(self, antes=None):
        self.assertEqual(T.linhas(self.db), antes or self.antes)

    def assertClassificado(self, depois, antes=None):
        """CA12: cada id do mapa com a cat e a busca do mapa; fora cat, busca e atualizado_em, tudo igual."""
        antes = antes or self.antes
        self.assertEqual(set(depois), set(antes))
        for iid, a in antes.items():
            d = depois[iid]
            m = MAPA.get(a['id'])
            mudou = m is not None and a['cat'] == ORIGEM
            if m:
                self.assertEqual((d['cat'], d['busca']), (m['cat'], m['busca']), a['id'])
            for col, valor in a.items():
                if mudou and col in ('cat', 'busca', 'atualizado_em'):
                    continue
                self.assertEqual(d[col], valor, f'{a["id"]}.{col} mudou')
            if mudou:
                self.assertNotEqual(d['atualizado_em'], ANTIGO, a['id'])
        self.assertNotIn(ORIGEM, {d['cat'] for d in depois.values()})


class TestMapa(unittest.TestCase):

    def test_json_bate_com_o_mapa_do_plano(self):
        esperado = {i: busca for busca, ids in MAPA_PLANO.items() for i in ids}
        self.assertEqual(sum(len(v) for v in MAPA_PLANO.values()), 74)
        self.assertEqual(len(esperado), 74)   # sem id repetido
        self.assertEqual(set(MAPA), set(esperado))
        for _id, m in MAPA.items():
            self.assertEqual(m['cat'], DESTINO, _id)
            self.assertEqual(m['busca'], esperado[_id], _id)
            self.assertRegex(m['item_id'], r'\A[A-Z0-9]{10}\Z', _id)   # ASIN
        self.assertEqual(len({m['item_id'] for m in MAPA.values()}), 74)
        self.assertEqual(C.carregar_mapa(), MAPA)

    def test_subtemas_novos_nao_entram_no_buscas_json(self):
        buscas = M.carregar_mapa()
        for busca in MAPA_PLANO:
            if busca in SUBTEMAS_NOVOS:
                self.assertNotIn(busca, buscas)
            else:
                self.assertEqual(buscas.get(busca), DESTINO, busca)

    def test_mapa_invalido_e_recusado(self):
        d = tempfile.mkdtemp(prefix='achadinhos-mapa-')
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        bom = {'item_id': 'B000000001', 'cat': DESTINO, 'busca': 'Monitor'}
        casos = {
            'nao_json': 'isto não é json',
            'lista': '[]',
            'vazio': '{}',
            'chave_nao_id': json.dumps({'abc': bom}),
            'chave_zero': json.dumps({'0': bom}),
            'chave_com_sinal': json.dumps({'+1': bom}),
            'chave_repetida': '{"1": %s, "1": %s}' % (json.dumps(bom), json.dumps(bom)),
            'campo_faltando': json.dumps({'1': {'item_id': 'B1', 'cat': DESTINO}}),
            'campo_a_mais': json.dumps({'1': {**bom, 'url': 'https://exemplo.com'}}),
            'busca_vazia': json.dumps({'1': {**bom, 'busca': '  '}}),
            'cat_numero': json.dumps({'1': {**bom, 'cat': 5}}),
            'destino_e_a_origem': json.dumps({'1': {**bom, 'cat': ORIGEM}}),
            'item_id_repetido': json.dumps({'1': bom, '2': bom}),
        }
        for nome, conteudo in casos.items():
            caminho = os.path.join(d, nome + '.json')
            with open(caminho, 'w', encoding='utf-8') as f:
                f.write(conteudo)
            with self.assertRaises(C.Erro, msg=nome):
                C.carregar_mapa(caminho)
        with self.assertRaises(C.Erro):
            C.carregar_mapa(os.path.join(d, 'nao-existe.json'))


class TestClassificacao(BancoTemporario):

    def test_dry_run_mostra_contagens_e_nao_grava(self):
        h = T.sha(self.db)
        r = self.rodar('--dry-run')
        self.assertOk(r)
        out = r.stdout
        self.assertIn(f'De "{ORIGEM}" para "{DESTINO}": 74 itens (amazon 74)', out)
        for busca, ids in MAPA_PLANO.items():
            self.assertIn(f'\n    {busca}: amazon {len(ids)}\n', out)
        self.assertIn('Já classificados (ficam como estão): 0', out)
        self.assertIn('Total a mudar: 74', out)
        self.assertIn('--dry-run: nada foi gravado e nenhum backup foi criado.', out)
        self.assertNotIn('AVISO', out)
        self.assertIn('Rode logo depois do migrar_categorias.py e ANTES de cadastrar qualquer número no disparo', out)
        self.assertNadaMudou()
        self.assertEqual(T.sha(self.db), h)
        self.assertFalse(os.path.exists(os.path.join(self.dir, 'backups')))

    def test_classifica_os_74_e_mantem_o_resto(self):
        r = self.rodar()
        self.assertOk(r)
        self.assertIn('Classificação concluída: 74 itens mudados.', r.stdout)
        self.assertIn(f'"{DESTINO}" | amazon: 76', r.stdout)   # 74 + os 2 que já estavam lá
        depois = T.linhas(self.db)
        self.assertClassificado(depois)
        for _id, *_ in OUTROS:
            self.assertEqual(depois[self.por_id[_id]], self.antes[self.por_id[_id]])
        self.assertEqual({d['url'] for d in depois.values()}, {a['url'] for a in self.antes.values()})

    def test_backup_verificado_antes_e_restaurar_do_migrar_categorias_reverte(self):
        porta = TS.porta_livre()
        r = self.rodar(porta=porta)
        self.assertOk(r)
        bks = T.backups(self.dir)
        self.assertEqual(len(bks), 1)
        self.assertRegex(os.path.basename(bks[0]), r'\Aachadinhos-\d{8}-\d{6}\.db\Z')
        con = sqlite3.connect(bks[0])
        self.assertEqual(con.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        con.close()
        self.assertEqual(T.linhas(bks[0]), self.antes)   # o backup é o estado de antes
        self.assertLess(r.stdout.index(f'Backup verificado: {bks[0]}'), r.stdout.index('Classificação concluída'))
        desfazer = f'ACHADINHOS_DB={self.db} ACHADINHOS_PORTA={porta} python3 {SCRIPT} --desfazer'
        self.assertIn(f'Para desfazer só esta classificação: {desfazer}\n', r.stdout)
        cmd = f'ACHADINHOS_DB={self.db} ACHADINHOS_PORTA={porta} python3 {SCRIPT_MIGRAR} --restaurar {bks[0]}'
        self.assertIn(f'devolve o banco INTEIRO a este backup, desfazendo tudo o que foi gravado depois '
                      f'(inclusive o disparo), com o servidor parado: {cmd}\n', r.stdout)
        # O comando do --restaurar impresso, rodado de outra pasta, volta ao estado de antes.
        cmd = re.search(r'com o servidor parado: (.+--restaurar .+)$', r.stdout, re.M).group(1)
        isca = os.path.join(self.dir, 'isca.db')
        outra = os.path.join(self.dir, 'outra-pasta')
        os.mkdir(outra)
        r = subprocess.run(cmd, shell=True, cwd=outra, env=TS.ambiente(isca), stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, timeout=60)
        self.assertOk(r)
        self.assertNadaMudou()
        self.assertFalse(os.path.exists(isca))

    def test_segunda_execucao_muda_zero_e_nao_cria_backup(self):
        self.assertOk(self.rodar())
        depois = T.linhas(self.db)
        for args in (('--dry-run',), ()):
            r = self.rodar(*args)
            self.assertOk(r)
            self.assertIn('Nada a classificar: 0 itens mudados (74 já classificados). Nenhum backup foi criado.',
                          r.stdout)
            self.assertEqual(len(T.backups(self.dir)), 1)
            self.assertNadaMudou(depois)

    def test_execucao_parcial_completa_so_o_que_falta(self):
        for _id in (9, 10, 134):
            executar(self.db, 'UPDATE items SET cat=?, busca=? WHERE id=?', MAPA[_id]['cat'], MAPA[_id]['busca'], _id)
        antes = T.linhas(self.db)
        r = self.rodar()
        self.assertOk(r)
        self.assertIn('Já classificados (ficam como estão): 3', r.stdout)
        self.assertIn('Classificação concluída: 71 itens mudados.', r.stdout)
        depois = T.linhas(self.db)
        self.assertClassificado(depois, antes)
        for _id in (9, 10, 134):
            self.assertEqual(depois[self.por_id[_id]]['atualizado_em'], ANTIGO)   # não foi regravado

    def test_divergencia_aborta_sem_gravar_nem_criar_backup(self):
        casos = [
            ('item_id diferente', 'UPDATE items SET item_id=? WHERE id=?', ('B0OUTROXXX', 9),
             'id=9: item_id no banco é "B0OUTROXXX" e no mapa'),
            ('fora da lista', 'UPDATE items SET cat=? WHERE id=?', ('Casa Nova', 10),
             'id=10: está em cat="Casa Nova" busca="WhatsApp", fora de "Lista WhatsApp"'),
            ('no destino com outra busca', 'UPDATE items SET cat=?, busca=? WHERE id=?', (DESTINO, 'SSD', 11),
             f'id=11: está em cat="{DESTINO}" busca="SSD"'),
            ('id apagado', 'DELETE FROM items WHERE id=?', (12,), 'id=12: não existe no banco'),
        ]
        for nome, sql, params, msg in casos:
            with self.subTest(nome):
                semente = os.path.join(self.dir, 'semente.db')
                shutil.copy(self.db, semente)
                try:   # o próximo caso sempre parte do banco semeado, mesmo se este falhar
                    executar(self.db, sql, *params)
                    antes = T.linhas(self.db)
                    for args in (('--dry-run',), ()):
                        r = self.rodar(*args)
                        self.assertEqual(r.returncode, 1, args)
                        self.assertIn(msg, r.stderr)
                        self.assertIn('Nada foi gravado', r.stderr)
                        self.assertNadaMudou(antes)
                        self.assertFalse(os.path.exists(os.path.join(self.dir, 'backups')))
                finally:
                    shutil.move(semente, self.db)

    def test_item_da_lista_fora_do_mapa_fica_e_e_avisado(self):
        executar(self.db, "INSERT INTO items (id,loja,item_id,cat,busca,url,posicao) VALUES "
                          "(900,'amazon','B0FORAMAPA',?,'WhatsApp','https://www.amazon.com.br/dp/X?tag=t',900)", ORIGEM)
        antes = T.linhas(self.db)
        r = self.rodar()
        self.assertOk(r)
        self.assertIn(f'AVISO: 1 itens de "{ORIGEM}" não estão no mapa e ficam nessa aba.', r.stdout)
        depois = T.linhas(self.db)
        self.assertEqual(depois['B0FORAMAPA'], antes['B0FORAMAPA'])
        self.assertEqual(sum(1 for d in depois.values() if d['cat'] == ORIGEM), 1)

    def test_nada_a_classificar_ainda_avisa_item_fora_do_mapa(self):
        """R1: um link novo do chat recria a aba com 1 item; a repetição avisa em vez de calar."""
        self.assertOk(self.rodar())
        executar(self.db, "INSERT INTO items (id,loja,item_id,cat,busca,url,posicao) VALUES "
                          "(902,'amazon','B0NOVOCHAT',?,'WhatsApp','https://www.amazon.com.br/dp/X?tag=t',902)", ORIGEM)
        depois = T.linhas(self.db)
        for args in (('--dry-run',), ()):
            r = self.rodar(*args)
            self.assertOk(r)
            self.assertIn('Nada a classificar: 0 itens mudados (74 já classificados).', r.stdout)
            self.assertIn(f'AVISO: 1 itens de "{ORIGEM}" não estão no mapa e ficam nessa aba.', r.stdout)
            self.assertNadaMudou(depois)
        self.assertEqual(len(T.backups(self.dir)), 1)

    def test_avisa_quando_migrar_categorias_ainda_nao_rodou(self):
        executar(self.db, "INSERT INTO items (id,loja,item_id,cat,busca,url,posicao) VALUES "
                          "(901,'ml','MLB901','Black Friday','iPhone 17','https://meli.la/z',901)")
        for args in (('--dry-run',), ()):
            r = self.rodar(*args)
            self.assertOk(r)   # avisa, mas não depende disso
            self.assertIn('AVISO: o banco ainda tem as abas "Black Friday". Rode antes o migrar_categorias.py',
                          r.stdout)
        self.assertClassificado(T.linhas(self.db), self.antes | {'MLB901': T.linhas(self.db)['MLB901']})

    def test_falha_ao_criar_backup_nao_grava(self):
        with open(os.path.join(self.dir, 'backups'), 'w'):   # arquivo no lugar da pasta: makedirs falha
            pass
        r = self.rodar()
        self.assertEqual(r.returncode, 1)
        self.assertIn('backup falhou', r.stderr)
        self.assertIn('nada foi gravado', r.stderr)
        self.assertNadaMudou()

    def test_backup_reprovado_na_verificacao_nao_grava(self):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(S, 'DB', self.db), \
                mock.patch.object(M, 'verificar_backup', return_value='integrity_check deu "corrompido"'), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(C.main([]), 1)
        self.assertIn('backup falhou (integrity_check deu "corrompido"); nada foi gravado', err.getvalue())
        self.assertNadaMudou()
        self.assertEqual(T.backups(self.dir), [])   # o backup reprovado é apagado

    def test_rowcount_diferente_do_plano_desfaz_tudo(self):
        """Se um UPDATE não pegar o item previsto, nada é gravado (nem os outros 74)."""
        planejar = C.planejar

        def plano_com_fantasma(con, mapa, desfazer=False):
            mudar, *resto = planejar(con, mapa, desfazer)
            fantasma = C.Mudanca(999, 'amazon', 'B0FANTASMA', ORIGEM, 'WhatsApp', DESTINO, 'SSD', 'SSD')
            return [*mudar, fantasma], *resto

        err = io.StringIO()
        with mock.patch.object(S, 'DB', self.db), mock.patch.object(C, 'planejar', plano_com_fantasma), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            self.assertEqual(C.main([]), 1)
        self.assertIn('o UPDATE mudou 74 itens e o plano previa 75; nada foi gravado', err.getvalue())
        self.assertNadaMudou()

    def test_update_confere_cat_e_busca_de_origem(self):
        """O WHERE do UPDATE é a última barreira: um plano com a cat ou a busca de origem errada não grava."""
        planejar = C.planejar
        for campo in ('de_cat', 'de_busca'):
            with self.subTest(campo):
                def plano_errado(con, mapa, desfazer=False):
                    mudar, *resto = planejar(con, mapa, desfazer)
                    return [mudar[0]._replace(**{campo: 'Outra'}), *mudar[1:]], *resto

                err = io.StringIO()
                with mock.patch.object(S, 'DB', self.db), mock.patch.object(C, 'planejar', plano_errado), \
                        contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
                    self.assertEqual(C.main([]), 1)
                self.assertIn('o UPDATE mudou 73 itens e o plano previa 74; nada foi gravado', err.getvalue())
                self.assertNadaMudou()

    def test_banco_mudou_depois_da_leitura_aborta_dentro_da_transacao(self):
        """Entre o plano (só leitura) e o BEGIN IMMEDIATE, o banco mudou: confere de novo e não grava."""
        def mudar_no_meio(acao, sim):
            executar(self.db, 'UPDATE items SET item_id=? WHERE id=9', 'B0MUDOUXXX')

        err = io.StringIO()
        with mock.patch.object(S, 'DB', self.db), mock.patch.object(M, 'confirmar_banco_real', mudar_no_meio), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            self.assertEqual(C.main([]), 1)
        self.assertIn('id=9: item_id no banco é "B0MUDOUXXX"', err.getvalue())
        depois = T.linhas(self.db)
        self.assertEqual(sum(1 for d in depois.values() if d['cat'] == ORIGEM), 74)
        self.assertEqual(T.backups(self.dir), [])   # aborta antes do backup

    def test_erro_do_sqlite_sai_so_com_o_tipo(self):
        def falha(*a, **kw):
            raise sqlite3.OperationalError('mensagem da biblioteca com B0G5NZ82TJ')

        err = io.StringIO()
        with mock.patch.object(S, 'DB', self.db), mock.patch.object(S, 'conectar', falha), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            self.assertEqual(C.main([]), 1)
        self.assertIn('ERRO: falha no banco (OperationalError); nada foi gravado', err.getvalue())
        self.assertNotIn('mensagem da biblioteca', err.getvalue())
        self.assertNadaMudou()

    def test_texto_do_banco_sai_sem_caracteres_de_controle(self):
        executar(self.db, 'UPDATE items SET cat=? WHERE id=9', 'Aba\x1b[2K')
        executar(self.db, 'UPDATE items SET item_id=? WHERE id=10', 'B0\x1b]0;x\x07')
        r = self.rodar()
        self.assertEqual(r.returncode, 1)
        self.assertIn('id=9: está em cat="Aba\\x1b[2K"', r.stderr)
        self.assertIn('id=10: item_id no banco é "B0\\x1b]0;x\\x07"', r.stderr)
        self.assertNotIn('\x1b', r.stdout + r.stderr)

    def test_banco_inexistente_nao_e_criado(self):
        db = os.path.join(self.dir, 'nao-existe.db')
        r = rodar(db, '--dry-run')
        self.assertEqual(r.returncode, 1)
        self.assertIn('banco não encontrado', r.stderr)
        self.assertFalse(os.path.exists(db))


class TestDesfazer(BancoTemporario):
    """S1: --desfazer devolve só os itens do mapa a "Lista WhatsApp" (o --restaurar devolve o banco inteiro)."""

    def classificar(self):
        self.assertOk(self.rodar())
        return T.linhas(self.db)

    def test_desfazer_volta_os_74_e_so_eles(self):
        porta = TS.porta_livre()
        r = self.rodar(porta=porta)
        self.assertOk(r)
        classificado = T.linhas(self.db)
        # Depois da classificação o banco segue em uso: uma mudança noutro item tem que sobreviver.
        executar(self.db, "UPDATE items SET preco='R$ 1,00' WHERE id=1001")
        executar(self.db, "INSERT INTO config (chave, valor) VALUES ('templates', '[]')")
        em_uso = T.linhas(self.db)
        # Roda o comando --desfazer impresso, de outra pasta, com um banco isca no ambiente.
        cmd = re.search(r'^Para desfazer só esta classificação: (.+)$', r.stdout, re.M).group(1)
        isca = os.path.join(self.dir, 'isca.db')
        outra = os.path.join(self.dir, 'outra-pasta')
        os.mkdir(outra)
        r = subprocess.run(cmd, shell=True, cwd=outra, env=TS.ambiente(isca), stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, timeout=60)
        self.assertOk(r)
        self.assertFalse(os.path.exists(isca))
        self.assertIn('Desfeito: 74 itens voltaram para "Lista WhatsApp".', r.stdout)
        self.assertNotIn('Para desfazer só esta classificação', r.stdout)
        depois = T.linhas(self.db)
        self.assertEqual(set(depois), set(em_uso))
        for iid, a in em_uso.items():
            d = depois[iid]
            if a['id'] in MAPA:
                self.assertEqual((d['cat'], d['busca']), (ORIGEM, 'WhatsApp'), a['id'])
                self.assertNotEqual(d['atualizado_em'], ANTIGO, a['id'])
                for col, valor in self.antes[iid].items():
                    if col != 'atualizado_em':
                        self.assertEqual(d[col], valor, f'{a["id"]}.{col}')
            else:
                self.assertEqual(d, a, iid)   # fora do mapa: nada muda, nem o preço editado depois
        self.assertEqual(depois[self.por_id[1001]]['preco'], 'R$ 1,00')
        con = sqlite3.connect(self.db)
        self.assertEqual(con.execute("SELECT valor FROM config WHERE chave='templates'").fetchone()[0], '[]')
        con.close()
        bks = T.backups(self.dir)
        self.assertEqual(len(bks), 2)   # um da classificação, um do desfazer (verificado antes)
        estados = [T.linhas(b) for b in bks]
        self.assertIn(self.antes, estados)   # backup da classificação
        self.assertIn(em_uso, estados)       # backup do desfazer: o estado logo antes dele
        self.assertNotEqual(em_uso, classificado)

    def test_desfazer_dry_run_nao_grava(self):
        classificado = self.classificar()
        h = T.sha(self.db)
        r = self.rodar('--desfazer', '--dry-run')
        self.assertOk(r)
        self.assertIn(f'De "{DESTINO}" para "{ORIGEM}": 74 itens (amazon 74)', r.stdout)
        self.assertIn('    Acessórios de informática -> WhatsApp: amazon 15', r.stdout)
        self.assertIn('Já desfeitos (ficam como estão): 0', r.stdout)
        self.assertIn('nada foi gravado', r.stdout)
        self.assertNadaMudou(classificado)
        self.assertEqual(T.sha(self.db), h)
        self.assertEqual(len(T.backups(self.dir)), 1)

    def test_desfazer_segunda_vez_muda_zero_e_nao_cria_backup(self):
        self.classificar()
        self.assertOk(self.rodar('--desfazer'))
        desfeito = T.linhas(self.db)
        for args in (('--desfazer', '--dry-run'), ('--desfazer',)):
            r = self.rodar(*args)
            self.assertOk(r)
            self.assertIn('Nada a desfazer: 0 itens mudados (74 já em "Lista WhatsApp"). Nenhum backup foi criado.',
                          r.stdout)
            self.assertNadaMudou(desfeito)
            self.assertEqual(len(T.backups(self.dir)), 2)
        # Nunca classificado: desfazer também dá 0.
        executar(self.db, 'DELETE FROM items')
        semear(self.db)
        r = self.rodar('--desfazer')
        self.assertOk(r)
        self.assertIn('Nada a desfazer: 0 itens mudados (74 já em', r.stdout)

    def test_desfazer_parcial_so_o_que_falta(self):
        self.classificar()
        executar(self.db, "UPDATE items SET cat=?, busca='WhatsApp' WHERE id IN (9, 10)", ORIGEM)
        r = self.rodar('--desfazer')
        self.assertOk(r)
        self.assertIn('Já desfeitos (ficam como estão): 2', r.stdout)
        self.assertIn('Desfeito: 72 itens voltaram', r.stdout)
        self.assertEqual({d['cat'] for d in T.linhas(self.db).values() if d['id'] in MAPA}, {ORIGEM})

    def test_desfazer_com_item_editado_aborta_sem_gravar(self):
        self.classificar()
        casos = [
            ('busca editada', 'UPDATE items SET busca=? WHERE id=?', ('SSD', 22),
             f'id=22: está em cat="{DESTINO}" busca="SSD", diferente do mapa e de "Lista WhatsApp"/"WhatsApp"'),
            ('movido de aba', 'UPDATE items SET cat=? WHERE id=?', ('Casa e Decoração', 23),
             'id=23: está em cat="Casa e Decoração"'),
            ('item_id diferente', 'UPDATE items SET item_id=? WHERE id=?', ('B0OUTROXXX', 24),
             'id=24: item_id no banco é "B0OUTROXXX"'),
            ('apagado', 'DELETE FROM items WHERE id=?', (25,), 'id=25: não existe no banco'),
        ]
        for nome, sql, params, msg in casos:
            with self.subTest(nome):
                semente = os.path.join(self.dir, 'semente.db')
                shutil.copy(self.db, semente)
                try:
                    executar(self.db, sql, *params)
                    antes = T.linhas(self.db)
                    for args in (('--desfazer', '--dry-run'), ('--desfazer',)):
                        r = self.rodar(*args)
                        self.assertEqual(r.returncode, 1, args)
                        self.assertIn(msg, r.stderr)
                        self.assertIn('Nada foi gravado', r.stderr)
                        self.assertNadaMudou(antes)
                        self.assertEqual(len(T.backups(self.dir)), 1)
                finally:
                    shutil.move(semente, self.db)

    def test_desfazer_com_item_editado_no_meio_aborta_dentro_da_transacao(self):
        """Editado entre o plano (só leitura) e o BEGIN IMMEDIATE: confere de novo e não grava."""
        self.classificar()

        def editar_no_meio(acao, sim):
            self.assertIn('desfazer', acao)
            executar(self.db, "UPDATE items SET busca='Editado' WHERE id=22")

        err = io.StringIO()
        with mock.patch.object(S, 'DB', self.db), mock.patch.object(M, 'confirmar_banco_real', editar_no_meio), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            self.assertEqual(C.main(['--desfazer']), 1)
        self.assertIn('id=22: está em cat="Black Friday | Eletrônicos" busca="Editado"', err.getvalue())
        self.assertEqual({d['cat'] for d in T.linhas(self.db).values() if d['id'] in MAPA}, {DESTINO})
        self.assertEqual(len(T.backups(self.dir)), 1)   # aborta antes do backup

    def test_desfazer_com_rowcount_diferente_desfaz_tudo(self):
        self.classificar()
        classificado = T.linhas(self.db)
        planejar = C.planejar

        def plano_com_fantasma(con, mapa, desfazer=False):
            mudar, *resto = planejar(con, mapa, desfazer)
            return [*mudar, C.Mudanca(999, 'amazon', 'B0FANTASMA', DESTINO, 'SSD', ORIGEM, 'WhatsApp', 'SSD')], *resto

        err = io.StringIO()
        with mock.patch.object(S, 'DB', self.db), mock.patch.object(C, 'planejar', plano_com_fantasma), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            self.assertEqual(C.main(['--desfazer']), 1)
        self.assertIn('o UPDATE mudou 74 itens e o plano previa 75; nada foi gravado', err.getvalue())
        self.assertNadaMudou(classificado)


class TestComServidorNoAr(TS.ServidorTeste):
    """Funciona com o servidor.py no ar (WAL): o GET mostra a classificação sem reiniciar."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        semear(cls.db)

    def test_classifica_com_servidor_no_ar(self):
        itens = {i['id']: i for i in self.itens()}
        self.assertEqual({itens[i]['cat'] for i in MAPA}, {ORIGEM})
        r = rodar(self.db, porta=self.porta)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        itens = {i['id']: i for i in self.itens()}
        for _id, m in MAPA.items():
            self.assertEqual((itens[_id]['cat'], itens[_id]['busca']), (m['cat'], m['busca']), _id)
        self.assertIsNone(self.proc.poll())


class TestGuardaBancoReal(unittest.TestCase):
    """Gravar no banco "real" (achadinhos.db ao lado do script) exige --sim ou "sim" no terminal.

    Prova numa cópia do projeto (servidor.py, os dois scripts, buscas.json e lista_whatsapp.json) com
    um achadinhos.db semeado. ACHADINHOS_DB aponta para esse arquivo: um erro no teste nunca alcança
    o banco real.
    """

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix='achadinhos-guarda-lista-')
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        for f in ('servidor.py', 'migrar_categorias.py', 'classificar_lista.py', 'buscas.json',
                  'lista_whatsapp.json'):
            shutil.copy(os.path.join(TS.RAIZ, f), self.dir)
        self.db = os.path.join(self.dir, 'achadinhos.db')
        semear(self.db)
        self.antes = T.linhas(self.db)
        self.env = TS.ambiente(self.db, TS.porta_livre())
        self.env.pop('PYTHONPATH', None)

    def rodar(self, *args):
        r = rodar(self.db, *args, env=self.env, script=os.path.join(self.dir, 'classificar_lista.py'),
                  cwd=self.dir)
        self.assertIn(f'Banco: {self.db}', r.stdout)   # rodou a cópia, sobre o banco da cópia
        return r

    def test_sem_confirmacao_recusa_e_nao_grava(self):
        r = self.rodar()
        self.assertEqual(r.returncode, 1)
        self.assertIn('exige confirmação', r.stderr)
        self.assertIn('Total a mudar: 74', r.stdout)   # o plano aparece antes da pergunta
        self.assertEqual(T.linhas(self.db), self.antes)
        self.assertEqual(T.backups(self.dir), [])

    def test_dry_run_nao_pede_confirmacao(self):
        r = self.rodar('--dry-run')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(T.linhas(self.db), self.antes)

    def test_sim_grava_e_o_comando_de_reverter_nao_troca_o_banco(self):
        r = self.rodar('--sim')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual({v['id']: (v['cat'], v['busca']) for v in T.linhas(self.db).values() if v['id'] in MAPA},
                         {i: (m['cat'], m['busca']) for i, m in MAPA.items()})
        bk = T.backups(self.dir)[0]
        self.assertNotIn('ACHADINHOS_DB=', r.stdout)
        porta = self.env['ACHADINHOS_PORTA']
        self.assertIn(f'ACHADINHOS_PORTA={porta} python3 {self.dir}/migrar_categorias.py --restaurar {bk}\n',
                      r.stdout)
        self.assertIn(f'Para desfazer só esta classificação: ACHADINHOS_PORTA={porta} python3 '
                      f'{self.dir}/classificar_lista.py --desfazer\n', r.stdout)
        # --desfazer no banco real também exige confirmação.
        classificado = T.linhas(self.db)
        r = self.rodar('--desfazer')
        self.assertEqual(r.returncode, 1)
        self.assertIn('desfazer a classificação da Lista WhatsApp no banco real', r.stderr)
        self.assertIn('exige confirmação', r.stderr)
        self.assertEqual(T.linhas(self.db), classificado)
        self.assertEqual(len(T.backups(self.dir)), 1)
        r = self.rodar('--desfazer', '--sim')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual({v['id']: (v['cat'], v['busca']) for v in T.linhas(self.db).values() if v['id'] in MAPA},
                         {i: (ORIGEM, 'WhatsApp') for i in MAPA})

    def test_prompt_no_terminal(self):
        """No terminal, só "sim" grava; qualquer outra resposta cancela."""
        self.assertNotEqual(os.path.realpath(self.db), TS.DB_REAL)
        terminal = mock.Mock(isatty=mock.Mock(return_value=True))
        with mock.patch.object(S, 'BASE', self.dir), mock.patch.object(S, 'DB', self.db), \
                mock.patch.object(M.sys, 'stdin', terminal), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as err:
            with mock.patch('builtins.input', return_value='não') as perguntou:
                self.assertEqual(C.main([]), 1)
            perguntou.assert_called_once()
            self.assertIn('cancelado', err.getvalue())
            self.assertEqual(T.linhas(self.db), self.antes)
            with mock.patch('builtins.input', return_value='sim'):
                self.assertEqual(C.main([]), 0)
        self.assertEqual({v['id']: v['cat'] for v in T.linhas(self.db).values() if v['id'] in MAPA},
                         {i: DESTINO for i in MAPA})


if __name__ == '__main__':
    unittest.main()
