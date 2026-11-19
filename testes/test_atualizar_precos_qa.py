#!/usr/bin/env python3
"""Testes de QA de "preço sempre atualizado" (docs/produto/planos/atualizar-precos.md, CA1 a CA10).

Uso:  python3 testes/test_atualizar_precos_qa.py -v

Complementam os testes do dev (test_atualizar_precos.py, test_disparo*.py, test_servidor.py,
test_api_ofertas*.py) sem repetir os casos deles. Foco:
  - a migração v3 sobre um retrato do banco real (leitura em mode=ro, cópia por sqlite3.backup);
  - o lote com uma fonte falsa sobre linhas reais (nada além do preço, da idade e dos dados muda);
  - a trava do disparo e o filtro da v1 contra um oráculo independente (SQL), nos dados reais;
  - a paridade do front (index.html, rodado no node) com o servidor para `preco_em` e para o prazo;
  - o comando copiável do quadro de preços, rodado por um shell de verdade com nomes hostis;
  - atomicidade por página, propriedades do resumo e concorrência.

Nada aqui toca o achadinhos.db real além do backup em mode=ro, o servidor da 8765, a Amazon, o ML ou a
Shopee (proxy morto, openers falsos). Só biblioteca padrão; precisa do `node` para a paridade com o front.
"""
import http.client
import json
import os
import random
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import unittest
from datetime import datetime, timedelta
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_atualizar_precos as T   # noqa: E402  (define o ambiente, os mocks e o banco temporário)
import test_servidor as TS          # noqa: E402  (ServidorTeste: servidor.py de verdade num subprocesso)

import disparo as D                 # noqa: E402
import api_ofertas as API           # noqa: E402

A, S, C, CAT = T.A, T.S, T.C, T.CAT

RAIZ = T.RAIZ
REAL = os.path.join(RAIZ, 'achadinhos.db')
RX_ISO = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}')
LOJAS = ('amazon', 'ml', 'shopee')
# As classes que copiam o achadinhos.db real só rodam por pedido (verificar.py --dados-reais): o resultado delas
# depende do que o dono coletou no dia, e uma suíte que falha por dado novo vira "falha conhecida".
DADOS_REAIS = unittest.skipUnless(os.environ.get('ACHADINHOS_TESTE_DADOS_REAIS') == '1',
                                  'dados reais: rode verificar.py --dados-reais')


def tearDownModule():
    shutil.rmtree(T.TMP, ignore_errors=True)


def iso(dt):
    return dt.isoformat(timespec='seconds')


def copiar_real(destino):
    """sqlite3.backup com origem em mode=ro (o banco real nunca é gravado). False se não der."""
    if not os.path.exists(REAL):
        return False
    try:
        origem = sqlite3.connect(f'file:{REAL}?mode=ro', uri=True, timeout=30)
    except sqlite3.Error:
        return False
    try:
        copia = sqlite3.connect(destino)
        try:
            origem.backup(copia)
        finally:
            copia.close()
    except sqlite3.Error:
        return False
    finally:
        origem.close()
    return True


def como_v2(caminho):
    """Devolve a cópia ao esquema da v2 (sem items.preco_em), qualquer que seja a versão do real hoje."""
    con = sqlite3.connect(caminho)
    try:
        if con.execute('PRAGMA user_version').fetchone()[0] >= 3:
            con.execute('ALTER TABLE items DROP COLUMN preco_em')
            con.execute('PRAGMA user_version = 2')
            con.commit()
    finally:
        con.close()


def migrar_com_o_servidor(caminho):
    """O mesmo caminho do dono: servidor.criar_banco() num processo novo, sobre a cópia."""
    r = subprocess.run([sys.executable, '-I', '-c',
                        f'import sys; sys.path.insert(0, {RAIZ!r}); import servidor; servidor.criar_banco()'],
                       env=TS.ambiente(caminho), capture_output=True, timeout=300)
    assert r.returncode == 0, r.stderr.decode(errors='replace')[-500:]


def linhas(caminho, tabela='items', ordem='rowid'):
    con = sqlite3.connect(f'file:{caminho}?mode=ro', uri=True)
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute(f'SELECT * FROM {tabela} ORDER BY {ordem}')]
    finally:
        con.close()


@DADOS_REAIS   # as subclasses herdam o skip
class CopiaMigrada(unittest.TestCase):
    """Base: uma cópia do banco real, devolvida à v2 e migrada pelo caminho do dono. Dá SkipTest sem o real."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix='achadinhos-qa-precos-')
        cls.addClassCleanup(shutil.rmtree, cls.dir, ignore_errors=True)
        cls.caminho = os.path.join(cls.dir, 'copia.db')
        if not copiar_real(cls.caminho):
            raise unittest.SkipTest('sem achadinhos.db legível neste checkout')
        como_v2(cls.caminho)
        cls.v2 = {t: linhas(cls.caminho, t) for t in ('items', 'numeros', 'regras', 'envios', 'config', 'generos_manuais')}
        migrar_com_o_servidor(cls.caminho)
        cls.v3 = {t: linhas(cls.caminho, t) for t in cls.v2}


# ------------------------------------------------------------------ CA1: migração v3 no retrato real
class MigracaoV3NoRetratoReal(CopiaMigrada):
    def test_vai_para_a_v3_sem_perder_nem_mudar_nenhuma_linha(self):
        con = sqlite3.connect(self.caminho)
        try:
            self.assertEqual(con.execute('PRAGMA user_version').fetchone()[0], 3)
            self.assertEqual(con.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            colunas = [r[1] for r in con.execute('PRAGMA table_info(items)')]
        finally:
            con.close()
        self.assertEqual(colunas[-1], 'preco_em', 'a coluna entra no fim de items')
        self.assertGreater(len(self.v2['items']), 5000)
        self.assertEqual(len(self.v3['items']), len(self.v2['items']))
        for antes, depois in zip(self.v2['items'], self.v3['items']):
            depois = dict(depois)
            depois.pop('preco_em')
            self.assertEqual(depois, antes, f'item {antes["id"]}: só preco_em pode ser novo (url e atualizado_em ficam)')
        for t in ('numeros', 'regras', 'envios', 'config', 'generos_manuais'):
            self.assertEqual(self.v3[t], self.v2[t], t)

    def test_preenchimento_e_criado_em_para_quem_tem_preco_e_null_para_o_resto(self):
        com = sem = 0
        for r in self.v3['items']:
            ok = r['tem_dados'] == 1 and r['preco'] != '' and RX_ISO.fullmatch(r['criado_em'] or '')
            if ok:
                com += 1
                self.assertEqual(r['preco_em'], r['criado_em'], r['id'])
            else:
                sem += 1
                self.assertIsNone(r['preco_em'], r['id'])
        self.assertGreater(com, 5000)
        self.assertGreater(sem, 0, 'o banco real tem item sem preço (a regra do NULL precisa ser exercitada)')

    def test_nenhum_preco_em_vem_do_futuro_de_atualizado_em(self):
        # o backfill é um limite inferior: nunca depois do momento em que a linha foi escrita pela última vez
        for r in self.v3['items']:
            if r['preco_em']:
                self.assertLessEqual(r['preco_em'], r['atualizado_em'], r['id'])

    def test_segunda_migracao_nao_muda_nada(self):
        migrar_com_o_servidor(self.caminho)
        self.assertEqual(linhas(self.caminho), self.v3['items'])


# ------------------------------------------------------------------ CA1: a migração com a coleta gravando e o código antigo depois
@DADOS_REAIS
class MigracaoComColetaEscrevendo(unittest.TestCase):
    """O banco real está sendo gravado por uma coleta (código da v2) quando o dono reinicia o servidor novo."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix='achadinhos-qa-precos-conc-')
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.caminho = os.path.join(self.dir, 'copia.db')
        if not copiar_real(self.caminho):
            self.skipTest('sem achadinhos.db legível neste checkout')
        como_v2(self.caminho)

    def test_escritas_do_codigo_antigo_durante_a_migracao_nao_se_perdem_e_ficam_como_velhas(self):
        antes = len(linhas(self.caminho))
        parar, erros, gravados = threading.Event(), [], []

        def coleta_antiga():
            # o INSERT e o UPDATE da v2, com a lista de colunas dela (sem preco_em)
            con = sqlite3.connect(self.caminho, timeout=60)
            try:
                n = 0
                while not parar.is_set():
                    n += 1
                    try:
                        cur = con.execute("INSERT INTO items (loja,item_id,cat,busca,url,titulo,preco,tem_dados,posicao,criado_em,atualizado_em) "
                                          "VALUES ('amazon',?,?,?,?,?,?,1,0,?,?)",
                                          (f'B0CONC{n:05d}', 'Cozinha', 'Panela', f'https://www.amazon.com.br/dp/B0CONC{n:05d}?tag=desejodemen01-20',
                                           'Panela', 'R$ 10,00', iso(datetime.now()), iso(datetime.now())))
                        con.execute("UPDATE items SET preco='R$ 11,00' WHERE id=?", (cur.lastrowid,))
                        con.commit()
                        gravados.append(f'B0CONC{n:05d}')
                    except sqlite3.Error as e:
                        erros.append(type(e).__name__ + ': ' + str(e))
                        con.rollback()
                    time.sleep(0.002)
            finally:
                con.close()

        fio = threading.Thread(target=coleta_antiga)
        fio.start()
        time.sleep(0.4)
        try:
            migrar_com_o_servidor(self.caminho)
            time.sleep(0.4)
        finally:
            parar.set()
            fio.join(30)
        self.assertEqual(erros, [], 'a coleta antiga tomou erro por causa da migração')
        self.assertGreater(len(gravados), 20)
        final = linhas(self.caminho)
        self.assertEqual(len(final), antes + len(gravados), 'linha perdida ou duplicada')
        con = sqlite3.connect(self.caminho)
        try:
            self.assertEqual(con.execute('PRAGMA user_version').fetchone()[0], 3)
            self.assertEqual(con.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        finally:
            con.close()
        por_id = {r['item_id']: r for r in final}
        depois = [por_id[i] for i in gravados if por_id[i]['preco_em'] is not None]
        for r in depois:   # quem foi preenchido pela migração só pode ter o criado_em
            self.assertEqual(r['preco_em'], r['criado_em'])
        sem = [i for i in gravados if por_id[i]['preco_em'] is None]
        self.assertTrue(sem, 'o teste não pegou escrita depois da migração (nenhum item da coleta ficou sem preco_em)')


@DADOS_REAIS
class CodigoAntigoSobreOBancoV3(unittest.TestCase):
    """Reverter é voltar o código: o servidor do commit anterior roda sobre o banco já migrado."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix='achadinhos-qa-precos-antigo-')
        cls.addClassCleanup(shutil.rmtree, cls.dir, ignore_errors=True)
        cls.caminho = os.path.join(cls.dir, 'copia.db')
        if not copiar_real(cls.caminho):
            raise unittest.SkipTest('sem achadinhos.db legível neste checkout')
        como_v2(cls.caminho)
        migrar_com_o_servidor(cls.caminho)
        cls.v3 = linhas(cls.caminho)
        try:
            nomes = subprocess.run(['git', '-C', RAIZ, 'ls-tree', '--name-only', 'HEAD'], check=True, capture_output=True,
                                   text=True).stdout.split('\n')
            tar = subprocess.run(['git', '-C', RAIZ, 'archive', '--format=tar', 'HEAD',
                                  *[n for n in nomes if n.endswith('.py') or n == 'buscas.json']],
                                 check=True, capture_output=True).stdout
        except (OSError, subprocess.CalledProcessError):
            raise unittest.SkipTest('sem git neste checkout')
        cls.codigo = os.path.join(cls.dir, 'antigo')
        os.makedirs(cls.codigo)
        import io
        import tarfile
        with tarfile.open(fileobj=io.BytesIO(tar)) as t:
            t.extractall(cls.codigo, filter='data')
        with open(os.path.join(cls.codigo, 'servidor.py'), encoding='utf-8') as f:
            tem_feature = 'preco_em' in f.read()
        if tem_feature:
            raise unittest.SkipTest('o HEAD já tem a feature: não há "código antigo" para comparar')
        cls.porta = TS.porta_livre()
        cls.log = open(os.path.join(cls.dir, 'antigo.log'), 'wb')
        cls.addClassCleanup(cls.log.close)
        cls.proc = subprocess.Popen([sys.executable, '-u', 'servidor.py'], cwd=cls.codigo, env=TS.ambiente(cls.caminho, cls.porta),
                                    stdout=subprocess.PIPE, stderr=cls.log)
        cls.addClassCleanup(cls.parar)
        cls.proc.stdout.readline()
        for _ in range(100):
            try:
                import socket
                socket.create_connection(('127.0.0.1', cls.porta), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.05)

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

    def pedir(self, metodo, caminho, corpo=None):
        con = http.client.HTTPConnection('127.0.0.1', self.porta, timeout=30)
        h = {'Host': f'localhost:{self.porta}', 'Origin': f'http://localhost:{self.porta}', 'Sec-Fetch-Site': 'same-origin'}
        if corpo is not None:
            corpo = json.dumps(corpo)
            h['Content-Type'] = 'application/json'
        try:
            con.request(metodo, caminho, body=corpo, headers=h)
            r = con.getresponse()
            return r.status, r.read()
        finally:
            con.close()

    def test_o_servidor_antigo_serve_todos_os_itens_e_nao_mexe_na_versao(self):
        st, dados = self.pedir('GET', '/api/items')
        self.assertEqual(st, 200)
        self.assertEqual(len(json.loads(dados)), len(linhas(self.caminho)))
        con = sqlite3.connect(self.caminho)
        try:
            self.assertEqual(con.execute('PRAGMA user_version').fetchone()[0], 3)
        finally:
            con.close()

    def test_item_gravado_pelo_codigo_antigo_fica_sem_data_de_preco_e_o_novo_o_trata_como_velho(self):
        item = {'loja': 'ml', 'item_id': 'MLBANTIGO1', 'cat': 'Cozinha', 'url': 'https://meli.la/MLBANTIGO1',
                'data': {'titulo': 'Panela', 'preco': 'R$ 80,00'}}
        st, dados = self.pedir('POST', '/api/items', {'items': [item]})
        self.assertEqual(st, 200, dados)
        r = next(r for r in linhas(self.caminho) if r['item_id'] == 'MLBANTIGO1')
        self.assertIsNone(r['preco_em'], 'o código antigo não conhece a coluna: item novo sem data = velho (lado seguro)')
        self.assertFalse(D.preco_recente(r['preco_em'], datetime.now(), 168))


# ------------------------------------------------------------------ CA1 e CA10: o lote sobre linhas reais
class LoteSobreLinhasReais(CopiaMigrada):
    def setUp(self):
        if os.path.exists(A.FEITOS):
            os.remove(A.FEITOS)
        self.addCleanup(lambda: os.path.exists(A.FEITOS) and os.remove(A.FEITOS))
        # cada teste grava na sua cópia: o lote muda linhas, e o próximo teste parte do retrato migrado
        self.trabalho = os.path.join(self.dir, f'trabalho-{self.id().rsplit(".", 1)[-1]}.db')
        origem = sqlite3.connect(self.caminho)
        destino = sqlite3.connect(self.trabalho)
        origem.backup(destino)
        origem.close()
        destino.close()

    def rodar_fonte(self, fonte, loja='amazon', abas=None):
        abas = abas or A.abas_escolhidas(None)
        with mock.patch.object(S, 'DB', self.trabalho), mock.patch.dict(A.FONTES, {loja: fonte}):
            with mock.patch('builtins.print'):
                return A.atualizar(loja, abas, {})

    def test_todo_item_real_de_amazon_e_shopee_tem_id_no_formato_que_a_selecao_conhece(self):
        # um id fora do formato nunca seria atualizado: o item ficaria velho para sempre sem aviso
        for loja in ('amazon', 'shopee'):
            ids = [r['item_id'] for r in self.v3['items'] if r['loja'] == loja]
            ruins = [i for i in ids if not A.ID_DA_LOJA[loja].fullmatch(i)]
            self.assertGreater(len(ids), 100, loja)
            self.assertEqual(ruins[:5], [], loja)

    def test_so_o_preco_a_idade_e_os_dados_do_lote_mudam_nas_linhas_reais(self):
        abas = A.abas_escolhidas(None)
        con = sqlite3.connect(f'file:{self.caminho}?mode=ro', uri=True)
        con.row_factory = sqlite3.Row
        try:
            escolhidos, _ = A.selecionar(con, 'amazon', list(abas), A.hoje())
        finally:
            con.close()
        self.assertGreater(len(escolhidos), 1000)
        ids = sorted(escolhidos)
        rng = random.Random(7)
        ok = set(rng.sample(ids, 300))
        outros = [i for i in ids if i not in ok]
        usado, piso, sumiu = set(outros[:20]), set(outros[20:40]), set(outros[40:60])

        def fonte(itens, opcoes):
            obs = []
            for iid in sorted(ok):
                l = itens[iid]
                it = {'loja': 'amazon', 'item_id': iid, 'cat': 'Cat que a fonte inventou', 'busca': 'busca inventada',
                      'url': 'https://www.amazon.com.br/dp/' + iid, 'data': {'titulo': 'Título novo ' + iid, 'preco': 'R$ 12,34'}}
                obs.append(T.A.Observacao(iid, 'ok', it))
            obs += [T.A.Observacao(i, 'usado', None) for i in usado]
            obs += [T.A.Observacao(i, 'fora_do_piso', None) for i in piso]
            obs += [T.A.Observacao(i, 'sumiu', None) for i in sumiu]
            obs.append(T.A.Observacao('B0NAOESTA0', 'ok', {'loja': 'amazon', 'item_id': 'B0NAOESTA0', 'cat': 'x', 'busca': 'x',
                                                          'url': 'https://www.amazon.com.br/dp/B0NAOESTA0',
                                                          'data': {'titulo': 't', 'preco': 'R$ 1,00'}}))
            yield 'relevancia|termo qualquer', obs

        t0 = datetime.now().replace(microsecond=0)
        resumo = self.rodar_fonte(fonte)
        t1 = datetime.now()
        depois = linhas(self.trabalho)
        self.assertEqual(len(depois), len(self.v3['items']), 'o lote nunca insere')
        antes = {r['id']: r for r in self.v3['items']}
        mudou = 0
        for r in depois:
            a = antes[r['id']]
            if r['loja'] == 'amazon' and r['item_id'] in ok:
                mudou += 1
                self.assertEqual((r['preco'], r['titulo']), ('R$ 12,34', 'Título novo ' + r['item_id']))
                self.assertRegex(r['preco_em'], RX_ISO)
                self.assertTrue(iso(t0) <= r['preco_em'] <= iso(t1), (r['preco_em'], t0, t1))
                self.assertEqual(r['atualizado_em'], r['preco_em'])
                # url (o CASE do afiliado), cat, busca, ids e posição nunca mudam; nem a data de criação
                for col in ('url', 'cat', 'busca', 'loja', 'item_id', 'criado_em', 'posicao', 'id'):
                    self.assertEqual(r[col], a[col], f'{r["item_id"]}.{col}')
            else:
                self.assertEqual(r, a, f'{r["loja"]}:{r["item_id"]} não era do lote e mudou')
        self.assertEqual(mudou, 300)
        self.assertEqual((resumo['atualizado'], resumo['usado'], resumo['fora_do_piso'], resumo['sumiu']),
                         (300, 20, 20, 20))
        self.assertEqual(resumo['atualizado'] + resumo['usado'] + resumo['fora_do_piso'] + resumo['sumiu']
                         + resumo['nao_vistos'], resumo['selecionados'])
        self.assertFalse(resumo['parou'])

    def test_retomada_no_mesmo_dia_deixa_de_fora_o_que_o_lote_acabou_de_confirmar(self):
        def fonte(itens, opcoes):
            ids = sorted(itens)[:50]
            yield 'relevancia|t', [T.A.Observacao(i, 'ok', {'loja': 'amazon', 'item_id': i, 'cat': 'x', 'busca': 'x',
                                                           'url': 'https://www.amazon.com.br/dp/' + i,
                                                           'data': {'titulo': 'novo', 'preco': 'R$ 5,55'}}) for i in ids]
        primeiro = self.rodar_fonte(fonte)
        segundo = self.rodar_fonte(lambda itens, opcoes: iter(()))
        self.assertEqual(primeiro['atualizado'], 50)
        self.assertEqual(segundo['ja_hoje'], primeiro['ja_hoje'] + 50)
        self.assertEqual(segundo['selecionados'], primeiro['selecionados'] - 50)


# ------------------------------------------------------------------ CA6 e CA7: a trava contra um oráculo (SQL), nos dados reais
class TravaNosDadosReais(CopiaMigrada):
    def setUp(self):
        self.con = sqlite3.connect(f'file:{self.caminho}?mode=ro', uri=True)
        self.con.row_factory = sqlite3.Row
        self.addCleanup(self.con.close)
        self.cats = sorted({r['cat'] for r in self.con.execute('SELECT cat FROM items')})
        self.regra = {'numero_id': 0, 'cats': self.cats, 'lojas': list(LOJAS), 'palavras': [], 'desconto_min': 0,
                      'repetir_apos_dias': None, 'generos': []}
        self.validade = D.validade_horas(self.con)
        self.datas = {r['id']: r['preco_em'] for r in self.con.execute('SELECT id, preco_em FROM items')}
        self.minimo = min(v for v in self.datas.values() if v)
        self.maximo = max(v for v in self.datas.values() if v)

    def eleitos(self, agora):
        info = {}
        itens = D.elegiveis(self.con, self.regra, agora, S.eh_link_afiliado, info)
        return {i['id'] for i in itens}, info

    def test_a_trava_particiona_o_universo_exatamente_pela_data_do_preco(self):
        # prazo de 168 h (patch) para o universo caber na janela; o oráculo é o de SQL/texto:
        # recente <=> agora - prazo <= preco_em <= agora + 5 min (a folga da S2 para relógio adiantado)
        with mock.patch.object(D, 'validade_horas', return_value=168):
            universo, info0 = self.eleitos(datetime.fromisoformat(self.maximo))   # nada é velho nem do futuro
            self.assertGreater(len(universo), 5000)
            self.assertEqual(info0['velhos'], 0, 'o retrato real passa de 7 dias: o teste precisa de outro universo')
            datas = sorted(v for i, v in self.datas.items() if i in universo)
            instantes = [datetime.fromisoformat(v) for v in (datas[0], datas[len(datas) // 4], datas[len(datas) // 2],
                                                             datas[-1])]
            instantes += [instantes[-1] + timedelta(seconds=1), instantes[0] - timedelta(minutes=5),
                          instantes[0] - timedelta(minutes=5, seconds=1), instantes[1] + timedelta(hours=100)]
            for agora in instantes:
                with self.subTest(agora=iso(agora)):
                    piso, teto = iso(agora - timedelta(hours=168)), iso(agora + timedelta(minutes=5))
                    esperado = {i for i in universo if piso <= self.datas[i] <= teto}
                    obtido, info = self.eleitos(agora)
                    self.assertEqual(obtido, esperado)
                    self.assertEqual(info['casam'], len(esperado))
                    self.assertEqual(info['casam'] + info['velhos'], len(universo))

    def test_com_tudo_velho_o_aviso_e_o_de_preco_e_traz_a_validade(self):
        agora = datetime.fromisoformat(self.minimo) + timedelta(days=60)
        eleitos, info = self.eleitos(agora)
        self.assertEqual(eleitos, set())
        self.assertEqual(info['casam'], 0)
        self.assertGreater(info['velhos'], 5000)
        self.assertEqual(D._aviso_sem_mensagem({**info, 'elegiveis': 0}), D.AVISO_PRECO_VELHO.format(h=self.validade))

    def test_relogio_atras_dos_dados_deixa_tudo_velho_em_vez_de_recente(self):
        # S2: preço mais de 5 min à frente do relógio é suspeito (relógio errado), não "recém-confirmado"
        agora = datetime.fromisoformat(self.minimo) - timedelta(days=1)
        eleitos, info = self.eleitos(agora)
        self.assertEqual((eleitos, info['casam']), (set(), 0))
        self.assertGreater(info['velhos'], 5000)

    def test_itens_sem_preco_legivel_nunca_sao_eleitos_em_nenhum_relogio(self):
        sem = {r['id'] for r in self.con.execute("SELECT id FROM items WHERE preco_em IS NULL")}
        self.assertTrue(sem)
        for agora in (datetime.fromisoformat(self.minimo), datetime(2030, 1, 1)):
            eleitos, _ = self.eleitos(agora)
            self.assertFalse(eleitos & sem)


# ------------------------------------------------------------------ CA8: o filtro da v1 contra um oráculo, nos dados reais
class V1PrecoMaxHorasNosDadosReais(CopiaMigrada):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # idades escalonadas e conhecidas: 0 a 199 h antes de AGORA, por id (a cópia é descartável)
        cls.agora = datetime(2026, 11, 4, 12, 0, 0)
        con = sqlite3.connect(cls.caminho)
        try:
            con.execute('UPDATE items SET preco_em = strftime(\'%Y-%m-%dT%H:%M:%S\', ?, \'-\' || (id % 200) || \' hours\')',
                        (iso(cls.agora),))
            # a ordem padrão da v1 ("atualizacao") esconde o que foi gravado nos últimos 60 s antes do relógio
            # (agora, fixo em 04/11): sem isto o total dependeria de quando o dono atualizou itens do banco real
            con.execute('UPDATE items SET atualizado_em = ?', (iso(cls.agora - timedelta(days=1)),))
            # validade padrão fixa na cópia: o assertLess do teste de "sem filtro" não pode depender da config real
            con.execute("INSERT OR REPLACE INTO config (chave, valor) VALUES ('preco_validade_horas', '48')")
            con.commit()
        finally:
            con.close()
        cls.con = sqlite3.connect(f'file:{cls.caminho}?mode=ro', uri=True)
        cls.con.row_factory = sqlite3.Row
        cls.con.execute('PRAGMA query_only = 1')
        cls.addClassCleanup(cls.con.close)
        manuais = API.G.manuais(cls.con)
        cls.ofertas = {r['id']: API.oferta(r, S.eh_link_afiliado, manuais) for r in cls.con.execute('SELECT * FROM items')}
        cls.ofertas = {i: o for i, o in cls.ofertas.items() if o}

    def pedir(self, qs):
        pares = [tuple(p.split('=')) for p in qs.split('&') if p]
        return API.rota(self.con, 'GET', '/api/v1/ofertas', pares, S.eh_link_afiliado, self.agora)

    def test_total_do_filtro_e_o_numero_de_ofertas_com_preco_dentro_do_prazo(self):
        self.assertGreater(len(self.ofertas), 5000)
        for horas in (1, 2, 24, 25, 100, 168):
            with self.subTest(horas=horas):
                esperado = sum(1 for i in self.ofertas if i % 200 <= horas)
                r = self.pedir(f'preco_max_horas={horas}&limite=1')
                self.assertEqual(r['total'], esperado)

    def test_a_primeira_pagina_so_traz_oferta_dentro_do_prazo_e_todas_vem_com_a_data(self):
        r = self.pedir('preco_max_horas=10&limite=200&ordem=relevancia')
        self.assertTrue(r['ofertas'])
        corte = iso(self.agora - timedelta(hours=10))
        for o in r['ofertas']:
            self.assertGreaterEqual(o['preco_em'], corte, o['chave'])
        # sem o filtro vale o padrão: config.preco_validade_horas (Q1 da API v1, decisão do dono de 08/11/2026)
        sem_filtro = self.pedir('limite=1')
        validade = D.validade_horas(self.con)
        self.assertEqual(sem_filtro['total'], self.pedir(f'preco_max_horas={validade}&limite=1')['total'])
        self.assertLess(sem_filtro['total'], self.pedir('preco_max_horas=168&limite=1')['total'])


# ------------------------------------------------------------------ paridade do front (node) com o servidor
INDEX = os.path.join(RAIZ, 'index.html')


def trecho_do_front(inicio, fim):
    """Texto de index.html do marcador `inicio` até o fim da linha que começa com `fim` (inclusive)."""
    with open(INDEX, encoding='utf-8') as f:
        html = f.read()
    i = html.index(inicio)
    j = html.index(fim, i)
    return html[i:html.index('\n', j)]


def rodar_node(codigo, entrada):
    node = shutil.which('node')
    if not node:
        raise unittest.SkipTest('sem node neste ambiente')
    env = {'PATH': os.environ.get('PATH', ''), 'TZ': 'America/Sao_Paulo'}
    r = subprocess.run([node, '-e', codigo], input=json.dumps(entrada), env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-800:]
    return json.loads(r.stdout)


class ParidadeDoFront(unittest.TestCase):
    AGORA = datetime(2026, 11, 4, 8, 0, 0)

    @classmethod
    def setUpClass(cls):
        cls.fonte = trecho_do_front('const PRECO_VALIDADE', 'const validadeValida')
        # validadeDoTexto vem logo depois (função de várias linhas): do começo dela até a chave que a fecha
        with open(INDEX, encoding='utf-8') as f:
            html = f.read()
        i = html.index('function validadeDoTexto')
        cls.fonte += '\n' + html[i:html.index('\n}\n', i) + 2]

    def velho_no_front(self, casos):
        """casos: [(preco_em, horas)] -> [bool] do precoVelho() do index.html, com `agora` fixo."""
        a = self.AGORA
        codigo = (self.fonte + f"""
const agora = new Date({a.year}, {a.month - 1}, {a.day}, {a.hour}, {a.minute}, {a.second});
const entrada = JSON.parse(require('fs').readFileSync(0, 'utf8'));
console.log(JSON.stringify(entrada.map(([pe, h]) => precoVelho(pe, h, agora))));""")
        return rodar_node(codigo, casos)

    def casos(self):
        a = self.AGORA
        bons = []
        for h in (1, 24, 168):
            for delta in (-5, -1, 0, 1, 5):   # segundos em volta do limite
                bons.append((iso(a - timedelta(hours=h) + timedelta(seconds=delta)), h))
            bons.append((iso(a), h))
            bons.append((iso(a + timedelta(days=3650)), h))   # relógio no futuro: o servidor e o front aceitam igual
        estranhos = [None, '', ' ' + iso(a), iso(a) + ' ', iso(a).replace('T', ' '), iso(a) + 'Z', iso(a) + '.123',
                     iso(a)[:16], '2026-02-30T10:00:00', '2026-11-04T23:59:60',
                     '2026-13-01T00:00:00', '2026-11-31T00:00:00', '２０２６-11-04T07:00:00', iso(a) + '\n',
                     '0000-01-01T00:00:00', '0099-01-01T00:00:00', '9999-12-31T23:59:59', '1999-12-31T23:59:59',
                     20261104070000, True, False, [], {}, 'ontem', '04/11/2026', '2026-11-04']
        return bons + [(v, 24) for v in estranhos]

    def test_precoVelho_do_front_e_o_oposto_de_disparo_preco_recente_em_toda_a_grade(self):
        casos = self.casos()
        no_front = self.velho_no_front(casos)
        self.assertEqual(len(no_front), len(casos))
        for (pe, h), velho in zip(casos, no_front):
            self.assertEqual(velho, not D.preco_recente(pe, self.AGORA, h), f'preco_em={pe!r} horas={h}')

    def test_q2_preco_em_com_hora_24_e_velho_no_front_e_no_servidor(self):
        # datetime.fromisoformat aceita "T24:00:00" (meia-noite do dia seguinte) e o regex do servidor também:
        # o disparo e a v1 tratam esse texto como preço recente (no futuro); o front o trata como inválido (velho)
        casos = [('2026-11-04T24:00:00', 24), ('2026-11-03T24:00:00', 24), ('2026-11-04T24:00:01', 24)]
        no_front = self.velho_no_front(casos)
        for (pe, h), velho in zip(casos, no_front):
            self.assertEqual(velho, not D.preco_recente(pe, self.AGORA, h), f'preco_em={pe!r} horas={h}')

    def test_validade_do_front_e_do_servidor_dao_o_mesmo_prazo_para_valores_inteiros(self):
        textos = ['24', '1', '168', '0', '169', '-5', '48', '"24"', '"48"', 'true', 'false', 'null', '[]', '{}', '[48]',
                  '24.5', '"abc"', '', '9' * 400, '-0', '100']
        self.comparar(textos)

    def test_q1_front_e_servidor_discordam_do_prazo_em_json_inteiro_escrito_como_decimal(self):
        # json.loads('48.0') é float no servidor (vale 24); JSON.parse('48.0') é 48 no front (Number.isInteger)
        self.comparar(['48.0', '1e2', '2.5e1', '1E+1', '72.00'])

    def comparar(self, textos):
        codigo = (self.fonte + """
const entrada = JSON.parse(require('fs').readFileSync(0, 'utf8'));
// o front lê o prazo do texto cru da config (validadeDoTexto), como o json.loads do servidor
console.log(JSON.stringify(entrada.map((t) => { const v = validadeDoTexto(t);
  return validadeValida(v) ? v : PRECO_VALIDADE.padrao; })));""")
        no_front = rodar_node(codigo, textos)
        con = sqlite3.connect(':memory:')
        con.execute('CREATE TABLE config (chave TEXT PRIMARY KEY, valor TEXT)')
        for t, f in zip(textos, no_front):
            con.execute("DELETE FROM config")
            con.execute("INSERT INTO config VALUES ('preco_validade_horas', ?)", (t,))
            self.assertEqual(D.validade_horas(con), f, f'config={t[:30]!r}: servidor e front discordam')


# ------------------------------------------------------------------ o comando copiável do quadro, num shell de verdade
class ComandoCopiavel(unittest.TestCase):
    NOMES = ['Perfumes e Perfumaria', 'Casa, Móveis e Ferramentas', 'TV, Alexa e Casa Conectada', 'a"b', '$(touch PWNED)',
             '`touch PWNED`', 'x; touch PWNED', 'a\\b', "it's", "'; touch PWNED; '", '!!', '-x', 'a b\nc', '', 'é' * 40,
             '${HOME}', 'a|b&c>d', '  ', 'x' * 300,
             'a\rb', '\x1b[31mvermelho', 'a\u202eb', 'a\u200bb', 'a\ufeffb', 'a\tb', 'a\x00b', 'a\x7fb']

    @staticmethod
    def tem_controle(nome):
        # S1: caractere de controle (Cc) ou de formatação (Cf) não entra em comando copiável
        return any(unicodedata.category(c) in ('Cc', 'Cf') for c in nome)

    @classmethod
    def setUpClass(cls):
        cls.fonte = trecho_do_front('function aspasShell', '  return bloco.cmd.replace') + '\n}'

    def comandos(self, nomes, loja, cmd):
        codigo = (self.fonte + f"""
const entrada = JSON.parse(require('fs').readFileSync(0, 'utf8'));
console.log(JSON.stringify(entrada.map((c) => comandoPrecos({json.dumps(loja)}, {{cmd: {json.dumps(cmd)}}}, c))));""")
        return rodar_node(codigo, nomes)

    def test_o_argumento_chega_inteiro_ao_programa_e_nada_e_executado(self):
        comandos = self.comandos(self.NOMES, 'amazon', 'python3 atualizar_precos.py amazon{ARG}')
        with tempfile.TemporaryDirectory() as pasta:
            for nome, cmd in zip(self.NOMES, comandos):
                with self.subTest(nome=nome[:40]):
                    if not nome:
                        self.assertEqual(cmd, 'python3 atualizar_precos.py amazon')
                        continue
                    if self.tem_controle(nome):
                        self.assertEqual(cmd, '', 'nome com caractere de controle não pode gerar comando')
                        continue
                    resto = cmd[len('python3 atualizar_precos.py '):]
                    r = subprocess.run(['bash', '-c', "printf '%s\\0' " + resto], cwd=pasta, capture_output=True, timeout=20)
                    self.assertEqual(r.returncode, 0, r.stderr)
                    self.assertEqual(r.stdout.decode().split('\0')[:-1], ['amazon', '--cat', nome])
            self.assertEqual(os.listdir(pasta), [], 'um nome de categoria executou comando no terminal')

    def test_o_comando_do_ml_e_um_objeto_javascript_com_o_nome_exato(self):
        comandos = self.comandos(self.NOMES, 'ml', 'ColetaML.atualizar({ARG})')
        for nome, cmd in zip(self.NOMES, comandos):
            with self.subTest(nome=nome[:40]):
                if self.tem_controle(nome):
                    self.assertEqual(cmd, '', 'nome com caractere de controle não pode gerar comando')
                    continue
                self.assertTrue(cmd.startswith('ColetaML.atualizar(') and cmd.endswith(')'))
                arg = cmd[len('ColetaML.atualizar('):-1]
                esperado = {'cat': nome} if nome else {}
                lido = rodar_node('const v = eval("(" + JSON.parse(require("fs").readFileSync(0, "utf8")) + ")");'
                                  'console.log(JSON.stringify(v));', arg)
                self.assertEqual(lido, esperado)


# ------------------------------------------------------------------ CA2/CA10: o orquestrador em propriedades e atomicidade
class OrquestradorEmPropriedades(T.Base):
    def setUp(self):
        super().setUp()
        self.ids = [f'B0QA{n:06d}' for n in range(40)]
        for i in self.ids:
            self.inserir('amazon', i, 'Perfume Floral')

    def it(self, iid, preco='R$ 9,99', titulo='Novo'):
        return {'loja': 'amazon', 'item_id': iid, 'cat': CAT, 'busca': 'Perfume Floral', 'url': C.link_afiliado(iid),
                'data': {'titulo': titulo, 'preco': preco}}

    def rodar_fonte(self, fonte):
        with mock.patch.dict(A.FONTES, {'amazon': fonte}), mock.patch('builtins.print'):
            return A.atualizar('amazon', {CAT: ['Perfume Floral']}, {})

    def test_resumo_fecha_a_conta_e_so_o_ok_de_selecionado_grava_em_qualquer_mistura(self):
        for semente in range(25):
            with self.subTest(semente=semente):
                for i in self.ids:   # volta ao estado inicial
                    con = S.conectar()
                    con.execute('UPDATE items SET preco=?, preco_em=?, titulo=? WHERE item_id=?',
                                ('R$ 50,00', T.ANTIGO, 'Item antigo', i))
                    con.commit()
                    con.close()
                if os.path.exists(A.FEITOS):
                    os.remove(A.FEITOS)
                rng = random.Random(semente)
                antes = self.todas()
                paginas = []
                for _ in range(rng.randint(1, 4)):
                    obs = []
                    for _ in range(rng.randint(0, 30)):
                        iid = rng.choice(self.ids + ['B0FORADOLOTE', 'B0FORADOLOT2'])
                        sit = rng.choice(A.SITUACOES)
                        preco = rng.choice(['R$ 9,99', 'R$ 9,99', '', 'Indisponível', 'R$ 0,00'])
                        it = self.it(iid, preco, rng.choice(['Novo', 'Novo', ''])) if sit == 'ok' else None
                        obs.append(A.Observacao(iid, sit, it))
                    paginas.append(obs)
                resumo = self.rodar_fonte(lambda itens, op: (('relevancia|t%d' % n, o) for n, o in enumerate(paginas)))
                depois = self.todas()
                self.assertEqual(set(depois), set(antes), 'nunca insere')
                gravados = {i for i in self.ids if depois[i] != antes[i]}
                self.assertEqual(len(gravados), resumo['atualizado'])
                soma = sum(resumo[k] for k in ('atualizado', 'sem_preco', 'fora_do_piso', 'usado', 'indisponivel', 'sumiu',
                                               'nao_vistos'))
                self.assertEqual(soma, resumo['selecionados'])
                for i in gravados:
                    self.assertEqual((depois[i]['preco'], depois[i]['titulo']), ('R$ 9,99', 'Novo'))
                    self.assertRegex(depois[i]['preco_em'], RX_ISO)
                    self.assertEqual(depois[i]['url'], antes[i]['url'])
                    self.assertTrue(any(o.item_id == i and o.situacao == 'ok' for p in paginas for o in p))
                # quem não foi gravado ficou byte a byte igual, com a data de preço antiga
                for i in set(self.ids) - gravados:
                    self.assertEqual(depois[i], antes[i])

    def test_erro_no_meio_da_pagina_desfaz_a_pagina_inteira_e_nao_marca_o_progresso(self):
        antes = self.todas()

        def fonte(itens, op):
            yield 'relevancia|certo', [A.Observacao(self.ids[0], 'ok', self.it(self.ids[0]))]
            ruim = self.it(self.ids[3])
            ruim['item_id'] = self.ids[4]   # a fonte devolve o item de outro id: o orquestrador recusa
            yield 'relevancia|quebra', [A.Observacao(self.ids[1], 'ok', self.it(self.ids[1])),
                                         A.Observacao(self.ids[2], 'ok', self.it(self.ids[2])),
                                         A.Observacao(self.ids[3], 'ok', ruim)]
        with self.assertRaises(ValueError):
            self.rodar_fonte(fonte)
        depois = self.todas()
        self.assertEqual(depois[self.ids[0]]['preco'], 'R$ 9,99')       # a página anterior foi commitada
        for i in self.ids[1:]:
            self.assertEqual(depois[i], antes[i], 'uma página com erro gravou pela metade')
        self.assertEqual(self.progresso(), [f'amazon|{A.hoje()}|relevancia|certo'])

    def test_lote_espera_o_servidor_soltar_a_escrita_em_vez_de_falhar_com_banco_travado(self):
        # o servidor do dono grava (agendador, POSTs) enquanto o lote roda: o busy timeout tem que cobrir
        trava = sqlite3.connect(S.DB, timeout=30, check_same_thread=False)   # o Timer solta a trava de outra thread
        trava.execute('BEGIN IMMEDIATE')
        soltou = threading.Timer(1.5, trava.commit)
        soltou.start()
        self.addCleanup(soltou.cancel)
        t0 = time.monotonic()
        resumo = self.rodar_fonte(lambda itens, op: iter([('relevancia|t', [A.Observacao(self.ids[0], 'ok', self.it(self.ids[0]))])]))
        soltou.join()
        trava.close()
        self.assertEqual(resumo['atualizado'], 1)
        self.assertGreaterEqual(time.monotonic() - t0, 1.0, 'o teste não exercitou a espera')

    def test_q3_item_com_preco_em_malformado_no_dia_de_hoje_e_selecionado(self):
        # "confirmado hoje" tem que usar o mesmo critério da trava: preco_em malformado é velho, qualquer que seja o prefixo
        prefixo = A.hoje()
        for iid, valor in ((self.ids[0], prefixo + 'Tlixo'), (self.ids[1], prefixo + 'T99:99:99'), (self.ids[2], prefixo + 'T07:00:00Z')):
            con = S.conectar()
            con.execute('UPDATE items SET preco_em=? WHERE item_id=?', (valor, iid))
            con.commit()
            con.close()
        con = S.conectar()
        try:
            itens, ja = A.selecionar(con, 'amazon', [CAT], A.hoje())
        finally:
            con.close()
        self.assertEqual(ja, 0)
        self.assertIn(self.ids[0], itens)
        self.assertIn(self.ids[1], itens)
        self.assertIn(self.ids[2], itens)


# ------------------------------------------------------------------ CA1: o servidor de verdade, em concorrência e com preços hostis
class EscritasNoServidor(TS.ServidorTeste):
    def banco(self):
        con = sqlite3.connect(self.db, timeout=30)
        con.row_factory = sqlite3.Row
        self.addCleanup(con.close)
        return con

    def item(self, item_id, preco='R$ 69,90', **extra):
        return {'loja': 'ml', 'item_id': item_id, 'cat': 'Cozinha', 'url': f'https://meli.la/{item_id}',
                'data': {'titulo': 'Produto', 'preco': preco}, **extra}

    def preco_em(self, item_id):
        r = self.banco().execute('SELECT preco_em FROM items WHERE item_id=?', (item_id,)).fetchone()
        return r[0] if r else 'SEM-LINHA'

    def test_preco_legivel_grava_a_data_e_o_resto_deixa_null(self):
        casos = {'R$ 1.299,90': True, 'R$ 4.285': True, 'R$ 69,90': True, '69,90': True, 'R$ 0,00': False, '0': False,
                 '': False, 'Consulte': False, 'R$ 10 - R$ 20': False, 'R$ ' + '9' * 400: True, '   ': False}
        postado = {}
        for n, (preco, legivel) in enumerate(casos.items()):
            iid = f'MLBPRECO{n}'
            st, _, dados = self.postar([self.item(iid, preco)])
            if st == 200:
                postado[iid] = legivel
        self.assertGreaterEqual(len(postado), 8, 'poucos preços aceitos para o teste valer')
        for iid, legivel in postado.items():
            valor = self.preco_em(iid)
            if legivel:
                self.assertRegex(valor, RX_ISO, iid)
            else:
                self.assertIsNone(valor, iid)

    def test_so_existentes_so_aceita_booleano_e_recusa_antes_de_gravar(self):
        self.postar([self.item('MLBBOOL0')])
        total = len(self.itens())
        for ruim in (None, 0, 1, 'true', 'false', 'sim', [], {}, [True], 1.0):
            with self.subTest(valor=ruim):
                st, _, dados = self.pedir('POST', '/api/items', {'so_existentes': ruim, 'items': [self.item('MLBBOOL1')]},
                                          self.local())
                self.assertEqual(st, 400, dados)
                self.assertEqual(len(self.itens()), total)
        self.assertEqual(self.preco_em('MLBBOOL1'), 'SEM-LINHA')

    def test_patch_de_data_num_item_que_nao_existe_nao_cria_linha(self):
        st, _, dados = self.pedir('PATCH', '/api/items/999999', {'data': {'titulo': 'x', 'preco': 'R$ 1,00'}}, self.local())
        self.assertIn(st, (200, 404), dados)
        self.assertEqual(self.banco().execute('SELECT COUNT(*) FROM items WHERE id=999999').fetchone()[0], 0)

    def test_put_do_prazo_como_o_front_manda_vale_no_disparo_e_valor_estranho_cai_para_24(self):
        # o quadro faz PUT /api/config/preco_validade_horas com o número cru no corpo (JSON.stringify(48))
        def validade():
            con = self.banco()
            return D.validade_horas(con)
        st, _, dados = self.pedir('PUT', '/api/config/preco_validade_horas', 48, self.local())
        self.assertEqual(st, 200, dados)
        self.assertEqual(validade(), 48)
        st, _, dados = self.pedir('GET', '/api/config/preco_validade_horas')
        self.assertEqual(self.json_de(dados), 48)
        for estranho in (169, 0, -3, 1.5, '48', True, None, [], {'h': 48}, 10 ** 30):
            with self.subTest(valor=estranho):
                st, _, dados = self.pedir('PUT', '/api/config/preco_validade_horas', json.dumps(estranho), self.local())
                if st == 200:   # a API de config grava qualquer JSON; quem lê é que não pode confiar
                    self.assertEqual(validade(), 24)
        st, _, dados = self.pedir('PUT', '/api/config/preco_validade_horas', 168, self.local())
        self.assertEqual((st, validade()), (200, 168))

    def test_escritas_ao_mesmo_tempo_nunca_inserem_nem_deixam_preco_em_invalido(self):
        ids = [f'MLBCONC{n}' for n in range(30)]
        self.postar([self.item(i) for i in ids])
        con = self.banco()
        with con:
            con.execute("UPDATE items SET preco_em='2026-01-01T00:00:00' WHERE item_id LIKE 'MLBCONC%'")
        ids_pk = {r['item_id']: r['id'] for r in con.execute("SELECT id, item_id FROM items WHERE item_id LIKE 'MLBCONC%'")}
        total = len(self.itens())
        erros, inicio = [], iso(datetime.now().replace(microsecond=0))

        def lote(n):
            try:
                for rodada in range(6):
                    extra = [self.item(f'MLBINTRUSO{n}-{rodada}')]   # item que NÃO existe: so_existentes não pode inserir
                    corpo = {'so_existentes': True, 'items': [self.item(i, f'R$ {10 + n + rodada},00') for i in ids] + extra}
                    st, _, dados = self.pedir('POST', '/api/items', corpo, self.local())
                    if st != 200:
                        erros.append(('lote', st, dados[:80]))
            except Exception as e:   # noqa: BLE001
                erros.append(('lote', type(e).__name__))

        def patch(n):
            try:
                for rodada in range(6):
                    pk = ids_pk[ids[(n * 7 + rodada) % len(ids)]]
                    st, _, dados = self.pedir('PATCH', f'/api/items/{pk}', {'data': {'titulo': 'P', 'preco': f'R$ {50 + rodada},00'}},
                                              self.local())
                    if st != 200:
                        erros.append(('patch', st, dados[:80]))
            except Exception as e:   # noqa: BLE001
                erros.append(('patch', type(e).__name__))

        def leitor():
            try:
                for _ in range(8):
                    st, _, dados = self.pedir('GET', '/api/items')
                    if st != 200:
                        erros.append(('get', st))
            except Exception as e:   # noqa: BLE001
                erros.append(('get', type(e).__name__))

        fios = [threading.Thread(target=lote, args=(n,)) for n in range(4)] \
            + [threading.Thread(target=patch, args=(n,)) for n in range(3)] + [threading.Thread(target=leitor) for _ in range(2)]
        for f in fios:
            f.start()
        for f in fios:
            f.join(120)
        self.assertEqual(erros, [])
        self.assertEqual(len(self.itens()), total, 'so_existentes inseriu item durante a concorrência')
        for r in self.banco().execute("SELECT item_id, preco_em FROM items WHERE item_id LIKE 'MLBCONC%'"):
            self.assertRegex(r['preco_em'], RX_ISO)
            self.assertGreaterEqual(r['preco_em'], inicio, r['item_id'])


if __name__ == '__main__':
    unittest.main()
