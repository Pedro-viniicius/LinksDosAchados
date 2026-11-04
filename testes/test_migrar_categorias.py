#!/usr/bin/env python3
"""Testes do migrar_categorias.py (docs/produto/planos/eletronicos-e-coleta-ml.md, etapa 2, e
docs/produto/planos/abas-nichadas-e-coleta.md, etapa 6: CA2, CA3 e CA4).

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
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
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
# As 3 abas antigas (origens) e as abas novas do buscas.json, com o destino de cada termo copiado da
# Decisão 2 do plano abas-nichadas-e-coleta (não lido do buscas.json: o teste confere o arquivo).
ELETRONICOS = 'Black Friday | Eletrônicos'
ELETRODOMESTICOS = 'Eletrodomésticos'
CASA_DECORACAO = 'Casa e Decoração'
CELULARES = 'Celulares e Informática'
AUDIO = 'Áudio e Acessórios'
TV = 'TV, Alexa e Casa Conectada'
GAMES = 'Games'
PORTATEIS = 'Eletroportáteis'
CLIMATIZACAO = 'Eletrodomésticos e Climatização'
COZINHA = 'Cozinha'
CAMA = 'Cama, Mesa e Banho'
CASA = 'Casa, Móveis e Ferramentas'
PERFUMES = 'Perfumes e Perfumaria'
LISTA = 'Lista WhatsApp'   # aba fora das origens e fora do buscas.json: fica como está

# (loja, item_id, cat, busca, cat esperada depois da migração)
SEMENTE = [
    ('amazon', 'W1', LISTA, '', LISTA),            # sem busca, mas fora das origens
    ('amazon', 'W2', LISTA, 'Geladeira', LISTA),   # termo mapeado, mas fora das origens
    ('amazon', 'P1', PERFUMES, 'Perfume feminino importado', PERFUMES),
    ('shopee', 'P2', PERFUMES, 'Perfume masculino nacional', PERFUMES),
    ('amazon', 'B1', ELETRONICOS, 'iPhone 17', CELULARES),
    ('ml', 'MLB1', ELETRONICOS, 'iPhone 17', CELULARES),
    ('ml', 'MLB2', ELETRONICOS, 'Caixa inteligente assistente virtual', TV),   # ALIAS
    ('amazon', 'B2', ELETRONICOS, 'Smart speaker Alexa', TV),
    ('amazon', 'B3', ELETRONICOS, 'Headset gamer', GAMES),
    ('ml', 'MLB3', ELETRONICOS, 'Microfone', AUDIO),
    ('amazon', 'S1', ELETRONICOS, 'Acessórios de informática', CELULARES),   # subtemas da Lista WhatsApp
    ('amazon', 'S2', ELETRONICOS, 'Computador e peças', CELULARES),
    ('amazon', 'S3', ELETRONICOS, 'Capas e acessórios', AUDIO),
    ('amazon', 'S4', ELETRONICOS, 'Câmeras', AUDIO),
    ('ml', 'MLB4', ELETRODOMESTICOS, 'Geladeira', CLIMATIZACAO),
    ('amazon', 'E1', ELETRODOMESTICOS, 'Air fryer', PORTATEIS),
    ('amazon', 'E2', ELETRODOMESTICOS, 'Lavadora de alta pressão', CASA),
    ('amazon', 'C1', CASA_DECORACAO, 'Sofá', CASA),
    ('ml', 'MLB5', CASA_DECORACAO, unicodedata.normalize('NFD', 'Sofá'), CASA),  # acento decomposto no banco
    ('ml', 'MLB6', CASA_DECORACAO, 'Jogo de panelas', COZINHA),
    ('amazon', 'C2', CASA_DECORACAO, 'Jogo de toalhas', CAMA),
    ('ml', 'MLB7', CASA_DECORACAO, '', CASA),     # sem busca, como o id 8524 do banco real
    ('ml', 'MLB8', CASA_DECORACAO, None, CASA),   # busca nula
]
ESPERADO = {s[1]: s[4] for s in SEMENTE}
# Preços de verdade (o resto da semente tem texto ilegível como preço, que é plausível): (preco, antigo, desconto)
PRECOS = {
    'B1': ('R$ 100,00', 'R$ 499,00', '80%'),        # 4,99x: fica
    'MLB1': ('R$ 1.299,90', 'R$ 1.599,90', '19%'),  # desconto normal: fica
    'C1': ('R$ 69,90', 'R$ 349,50', '80%'),         # 5x exato (o caso PHEBO): limpa
    'MLB6': ('R$ 20,00', 'R$ 150,00', '87%'),       # 7,5x, do ML: limpa
    'P1': ('R$ 19,00', 'R$ 19.000,00', '100%'),     # 1000x na perfumaria: limpa e não muda de aba
    'W2': ('R$ 10,00', 'R$ 50,00', '80%'),          # 5x fora das origens: limpa também
}
LIMPOS = {'C1', 'MLB6', 'P1', 'W2'}
ANTIGO = '2026-01-01T00:00:00'


def semear(db):
    """Cria o esquema do servidor.py (se faltar) e grava a SEMENTE num banco temporário."""
    if os.path.realpath(db) == TS.DB_REAL:
        raise RuntimeError('o teste tentou semear o banco real')
    with mock.patch.object(S, 'DB', db):
        S.criar_banco()
    con = sqlite3.connect(db)
    for pos, (loja, iid, cat, busca, _) in enumerate(SEMENTE, 1):
        url = {'amazon': f'https://www.amazon.com.br/dp/{iid}?tag={S.TAG_AMAZON}',
               'shopee': f'https://s.shopee.com.br/{iid}x'}.get(loja, f'https://meli.la/{iid}x')
        dados = {c: f'{c} de {iid}' for c in S.CAMPOS}
        if iid in PRECOS:
            dados['preco'], dados['preco_antigo'], dados['desconto'] = PRECOS[iid]
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


def tabela(saida, titulo):
    """Linhas da tabela aba × loja impressa depois de `titulo`: [(aba, [amazon, ml, shopee, total], fora)]."""
    bloco = saida.split(f'\n{titulo}\n', 1)[1].split('\n')
    assert re.fullmatch(r' {4}aba +amazon +ml +shopee +total', bloco[0]), bloco[0]
    linhas_tab = []
    for linha in bloco[1:]:
        m = re.fullmatch(r' {4}(.+?) +(\d+) +(\d+) +(\d+) +(\d+)(  \(fora do buscas\.json\))?', linha)
        if not m:
            break
        linhas_tab.append((m[1], [int(m[i]) for i in range(2, 6)], bool(m[6])))
    return linhas_tab


def tabela_esperada(contagens, fora=()):
    """As abas do buscas.json na ordem dele (vazias com 0), depois as de fora, e o total."""
    abas = list(dict.fromkeys(M.carregar_mapa().values()))
    linhas_tab = [(a, [*contagens.get(a, (0, 0, 0)), sum(contagens.get(a, (0, 0, 0)))], a in fora)
                  for a in abas + list(fora)]
    total = [sum(c[i] for c in contagens.values()) for i in range(3)]
    return linhas_tab + [('total', [*total, sum(total)], False)]


# Tabela aba × loja (amazon, ml, shopee) depois da migração da SEMENTE.
TABELA_DEPOIS = {
    CELULARES: (3, 1, 0), AUDIO: (2, 1, 0), TV: (1, 1, 0), GAMES: (1, 0, 0), PORTATEIS: (1, 0, 0),
    CLIMATIZACAO: (0, 1, 0), COZINHA: (0, 1, 0), CAMA: (1, 0, 0), CASA: (2, 3, 0), PERFUMES: (1, 0, 1),
    LISTA: (2, 0, 0),
}


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
        """CA2 a CA4: cada item na aba certa, os preços implausíveis sem antigo e sem desconto, e o
        resto igual (inclusive a url): só mudam `cat` dos movidos, `preco_antigo` e `desconto` dos
        limpos e `atualizado_em` de uns e outros."""
        self.assertEqual(set(depois), set(self.antes))   # mesmos itens: total antes = depois
        for iid, antes in self.antes.items():
            d = depois[iid]
            self.assertEqual(d['cat'], ESPERADO[iid], iid)
            movido, limpo = antes['cat'] != ESPERADO[iid], iid in LIMPOS
            for col, valor in antes.items():
                if (col == 'cat' or (col == 'atualizado_em' and (movido or limpo))
                        or (col in ('preco_antigo', 'desconto') and limpo)):
                    continue
                self.assertEqual(d[col], valor, f'{iid}.{col} mudou')
            if limpo:
                self.assertEqual((d['preco_antigo'], d['desconto']), ('', ''), iid)
            if movido or limpo:
                self.assertNotEqual(d['atualizado_em'], ANTIGO, iid)
        self.assertFalse({d['cat'] for d in depois.values()} & set(M.ORIGENS))


class TestMapaDaMigracao(unittest.TestCase):
    """As constantes do script contra o buscas.json vivo e o lista_whatsapp.json (CA2)."""

    def test_origens_saem_e_subtemas_e_sem_busca_apontam_para_abas_do_buscas_json(self):
        mapa = M.carregar_mapa()
        abas = set(mapa.values())
        self.assertEqual(M.ORIGENS, (ELETRONICOS, ELETRODOMESTICOS, CASA_DECORACAO))
        self.assertFalse(abas & set(M.ORIGENS), 'as abas antigas não podem continuar no buscas.json')
        self.assertEqual(M.SUBTEMAS_LISTA, {
            'Acessórios de informática': 'Teclado e mouse',
            'Computador e peças': 'Placa de vídeo',
            'Capas e acessórios': 'Carregador rápido',
            'Câmeras': 'Microfone',
        })
        self.assertEqual(M.DESTINO_SEM_BUSCA, {CASA_DECORACAO: CASA})
        self.assertLessEqual(set(M.DESTINO_SEM_BUSCA), set(M.ORIGENS))
        for subtema in M.SUBTEMAS_LISTA:
            self.assertNotIn(subtema, mapa, 'subtema não é termo de coleta')
            self.assertNotIn(subtema, M.ALIAS)
        for termo, dest in (('Acessórios de informática', CELULARES), ('Computador e peças', CELULARES),
                            ('Capas e acessórios', AUDIO), ('Câmeras', AUDIO),
                            ('Caixa inteligente assistente virtual', TV)):
            self.assertEqual(M.destino_de(termo, mapa, ELETRONICOS), dest, termo)
            self.assertEqual(M.destino_de(termo, mapa), dest, termo)   # a assinatura antiga continua valendo

    def test_toda_busca_do_lista_whatsapp_tem_destino(self):
        """Os 74 itens que o classificar_lista.py pôs em "Black Friday | Eletrônicos" não ficam órfãos."""
        mapa = M.carregar_mapa()
        with open(os.path.join(TS.RAIZ, 'lista_whatsapp.json'), encoding='utf-8') as f:
            buscas = {v['busca'] for v in json.load(f).values()}
        self.assertEqual(buscas - set(mapa), set(M.SUBTEMAS_LISTA))
        for busca in buscas:
            self.assertIsNotNone(M.destino_de(busca, mapa, ELETRONICOS), busca)

    def test_destino_sem_busca_so_na_aba_prevista_e_so_se_for_aba_do_mapa(self):
        mapa = M.carregar_mapa()
        for busca in ('', None):
            self.assertEqual(M.destino_de(busca, mapa, CASA_DECORACAO), CASA, repr(busca))
            self.assertIsNone(M.destino_de(busca, mapa, ELETRONICOS), repr(busca))
            self.assertIsNone(M.destino_de(busca, mapa, ELETRODOMESTICOS), repr(busca))
            self.assertIsNone(M.destino_de(busca, mapa), repr(busca))
        self.assertIsNone(M.destino_de('  ', mapa, CASA_DECORACAO), 'espaço não é "sem busca"')
        self.assertEqual(M.destino_de(unicodedata.normalize('NFD', 'Câmeras'), mapa, ELETRONICOS), AUDIO)
        with mock.patch.dict(M.DESTINO_SEM_BUSCA, {CASA_DECORACAO: 'Aba que não existe'}):
            self.assertIsNone(M.destino_de('', mapa, CASA_DECORACAO))


class TestMigracao(BancoTemporario):

    def test_dry_run_mostra_contagens_e_nao_grava(self):
        h = sha(self.db)
        r = self.rodar('--dry-run')
        self.assertOk(r)
        out = r.stdout
        rotas = [
            (ELETRONICOS, CELULARES, '4 itens (amazon 3, ml 1)'), (ELETRONICOS, TV, '2 itens (amazon 1, ml 1)'),
            (ELETRONICOS, GAMES, '1 itens (amazon 1)'), (ELETRONICOS, AUDIO, '3 itens (amazon 2, ml 1)'),
            (ELETRODOMESTICOS, CLIMATIZACAO, '1 itens (ml 1)'), (ELETRODOMESTICOS, PORTATEIS, '1 itens (amazon 1)'),
            (ELETRODOMESTICOS, CASA, '1 itens (amazon 1)'), (CASA_DECORACAO, CASA, '4 itens (amazon 1, ml 3)'),
            (CASA_DECORACAO, COZINHA, '1 itens (ml 1)'), (CASA_DECORACAO, CAMA, '1 itens (amazon 1)'),
        ]
        for de, para, n in rotas:
            self.assertIn(f'\nDe "{de}" para "{para}": {n}\n', out)
        self.assertEqual(out.count('\nDe "'), len(rotas))
        self.assertIn('    iPhone 17: amazon 1, ml 1\n', out)
        self.assertIn('    Caixa inteligente assistente virtual (alias de "Smart speaker Alexa"): ml 1\n', out)
        for subtema, termo in (('Acessórios de informática', 'Teclado e mouse'),
                               ('Computador e peças', 'Placa de vídeo'),
                               ('Capas e acessórios', 'Carregador rápido'), ('Câmeras', 'Microfone')):
            self.assertIn(f'    {subtema} (subtema da Lista WhatsApp, herda de "{termo}"): amazon 1\n', out)
        self.assertIn('    (sem busca): ml 2\n', out)   # '' e NULL
        self.assertIn(f'    "{CASA}": 5 itens (amazon 2, ml 3)', out)
        self.assertIn('Total a mover: 19', out)
        self.assertIn(f'Não muda: "{LISTA}" (2 itens)', out)
        self.assertIn(f'Não muda: "{PERFUMES}" (2 itens)', out)
        # CA4: quantos preços antigos serão limpos, e quais
        ids = {k: v['id'] for k, v in self.antes.items()}
        self.assertIn('Preços antigos implausíveis (antigo de 5x o preço ou mais) a limpar: 4 itens (amazon 3, ml 1)',
                      out)
        self.assertIn(f'    id={ids["C1"]} loja=amazon preço="R$ 69,90" antigo="R$ 349,50"\n', out)
        self.assertIn(f'    id={ids["MLB6"]} loja=ml preço="R$ 20,00" antigo="R$ 150,00"\n', out)
        self.assertIn(f'    id={ids["P1"]} loja=amazon preço="R$ 19,00" antigo="R$ 19.000,00"\n', out)
        self.assertIn(f'    id={ids["W2"]} loja=amazon preço="R$ 10,00" antigo="R$ 50,00"\n', out)
        self.assertNotIn('antigo="R$ 499,00"', out)   # 4,99x fica
        # CA2: tabela aba × loja projetada, com as abas do buscas.json na ordem dele
        self.assertEqual(tabela(out, 'Abas depois da migração (aba × loja):'),
                         tabela_esperada(TABELA_DEPOIS, fora=(LISTA,)))
        self.assertIn('Itens fora das abas do buscas.json: 2', out)
        self.assertIn('nada foi gravado', out)
        self.assertEqual(linhas(self.db), self.antes)
        self.assertEqual(sha(self.db), h)
        self.assertFalse(os.path.exists(os.path.join(self.dir, 'backups')))

    def test_migra_para_as_abas_novas_limpa_precos_e_mantem_o_resto(self):
        r = self.rodar()
        self.assertOk(r)
        self.assertIn('Migração concluída: 19 itens movidos e 4 preços antigos limpos.', r.stdout)
        depois = linhas(self.db)
        self.assertMigrado(depois)
        self.assertEqual(tabela(r.stdout, 'Abas no banco (aba × loja):'),
                         tabela_esperada(TABELA_DEPOIS, fora=(LISTA,)))
        # "Lista WhatsApp" fica, inclusive o item com termo mapeado; a perfumaria fica com os mesmos ids
        self.assertEqual(depois['W1'], self.antes['W1'])
        self.assertEqual({k for k, v in depois.items() if v['cat'] == PERFUMES}, {'P1', 'P2'})
        self.assertEqual(depois['P2'], self.antes['P2'])
        # CA4: 4,99x fica; 5x ou mais zera antigo e desconto e mantém preço e url
        self.assertEqual((depois['B1']['preco_antigo'], depois['B1']['desconto']), ('R$ 499,00', '80%'))
        self.assertEqual((depois['C1']['preco'], depois['C1']['preco_antigo'], depois['C1']['desconto']),
                         ('R$ 69,90', '', ''))
        self.assertEqual({k: v['url'] for k, v in depois.items()}, {k: v['url'] for k, v in self.antes.items()})

    def test_item_sem_destino_aborta_sem_gravar(self):
        con = sqlite3.connect(self.db)
        ids = [con.execute("INSERT INTO items (loja,item_id,cat,busca,url,posicao) VALUES "
                           "('ml','MLB9',?,'Termo que não existe','https://meli.la/z',99)", (CASA_DECORACAO,)).lastrowid,
               # sem busca numa origem que não está no DESTINO_SEM_BUSCA
               con.execute("INSERT INTO items (loja,item_id,cat,busca,url,posicao) VALUES "
                           "('ml','MLB10',?,'','https://meli.la/y',100)", (ELETRONICOS,)).lastrowid]
        con.commit()
        con.close()
        antes = linhas(self.db)
        for args in ((), ('--dry-run',)):
            r = self.rodar(*args)
            self.assertEqual(r.returncode, 1, args)
            self.assertIn('ERRO: 2 itens das origens têm busca sem destino', r.stderr)
            self.assertIn(f'id={ids[0]} loja=ml cat="{CASA_DECORACAO}" busca="Termo que não existe"', r.stderr)
            self.assertIn(f'id={ids[1]} loja=ml cat="{ELETRONICOS}" busca=""', r.stderr)
            self.assertIn('Nada foi gravado', r.stderr)
            self.assertNotIn('Total a mover', r.stdout)
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
        for args in (('--dry-run',), ()):
            r = self.rodar(*args)
            self.assertOk(r)
            self.assertIn('Nada a migrar: 0 itens movidos e 0 preços antigos a limpar. Nenhum backup foi criado.',
                          r.stdout)
            self.assertEqual(tabela(r.stdout, 'Abas no banco (aba × loja):'),
                             tabela_esperada(TABELA_DEPOIS, fora=(LISTA,)))
            self.assertEqual(len(backups(self.dir)), 1)
            self.assertEqual(linhas(self.db), depois)

    def test_preco_implausivel_gravado_depois_e_limpo_sem_mover_nada(self):
        """Um preço antigo implausível que entrou depois (ex.: edição manual pelo site) é limpo de novo."""
        self.assertOk(self.rodar())
        time.sleep(1.1)   # o nome do backup tem resolução de 1 segundo
        con = sqlite3.connect(self.db)
        con.execute("UPDATE items SET preco='R$ 30,00', preco_antigo='R$ 300,00', desconto='90%' WHERE item_id='E1'")
        con.commit()
        con.close()
        depois = linhas(self.db)
        r = self.rodar('--dry-run')
        self.assertOk(r)
        self.assertIn('Total a mover: 0', r.stdout)
        self.assertIn('a limpar: 1 itens (amazon 1)', r.stdout)
        r = self.rodar()
        self.assertOk(r)
        self.assertIn('Migração concluída: 0 itens movidos e 1 preços antigos limpos.', r.stdout)
        self.assertEqual(len(backups(self.dir)), 2)
        final = linhas(self.db)
        self.assertEqual((final['E1']['preco'], final['E1']['preco_antigo'], final['E1']['desconto']),
                         ('R$ 30,00', '', ''))
        for k, v in depois.items():
            if k != 'E1':
                self.assertEqual(final[k], v, k)

    def test_conferencia_antes_do_commit_desfaz_tudo(self):
        """Se o banco depois dos UPDATEs não bate com o plano (aqui, por um gatilho), nada é gravado."""
        gatilhos = {
            'outro item mudou de aba': ("AFTER UPDATE OF cat ON items WHEN NEW.item_id='B1' "
                                        "BEGIN UPDATE items SET cat='Outra' WHERE item_id='W1'; END",
                                        'não bate com o plano'),
            'um item sumiu': ("AFTER UPDATE OF cat ON items WHEN NEW.item_id='B1' "
                              "BEGIN DELETE FROM items WHERE item_id='W1'; END", 'não bate com o plano'),
            'o preço implausível voltou': ("AFTER UPDATE OF preco_antigo ON items WHEN NEW.item_id='C1' "
                                           "BEGIN UPDATE items SET preco_antigo='R$ 999,00' WHERE item_id='C1'; END",
                                           'ainda há preço antigo implausível'),
        }
        for nome, (gatilho, msg) in gatilhos.items():
            with self.subTest(nome):
                con = sqlite3.connect(self.db)
                con.execute(f'CREATE TRIGGER gatilho_teste {gatilho}')
                con.commit()
                try:
                    r = self.rodar()
                    self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
                    self.assertIn(msg, r.stderr)
                    self.assertIn('nada foi gravado', r.stderr)
                    self.assertNotIn('Migração concluída', r.stdout)
                    self.assertEqual(linhas(self.db), self.antes)
                finally:
                    con.execute('DROP TRIGGER gatilho_teste')
                    con.commit()
                    con.close()

    def rodar_main(self, **mocks):
        err = io.StringIO()
        with mock.patch.object(S, 'DB', self.db), contextlib.ExitStack() as pilha:
            for nome, valor in mocks.items():
                pilha.enter_context(mock.patch.object(M, nome, valor))
            pilha.enter_context(contextlib.redirect_stdout(io.StringIO()))
            pilha.enter_context(contextlib.redirect_stderr(err))
            self.assertEqual(M.main([]), 1)
        return err.getvalue()

    def test_update_confere_o_que_o_plano_leu(self):
        """O WHERE de cada UPDATE (cat e busca; preço e antigo) é a última barreira: plano errado não grava."""
        planejar, planejar_precos = M.planejar, M.planejar_precos

        def mover_com(i, valor):
            def plano(linhas_, mapa):
                movidos, sem = planejar(linhas_, mapa)
                m = list(movidos[0])
                m[i] = valor
                return [tuple(m), *movidos[1:]], sem
            return plano

        def limpar_com(i, valor):
            def plano(linhas_):
                limpar = planejar_precos(linhas_)
                m = list(limpar[0])
                m[i] = valor
                return [tuple(m), *limpar[1:]]
            return plano

        casos = {
            'cat de origem': ({'planejar': mover_com(2, 'Outra')}, 'o UPDATE mudou 18 itens e o plano previa 19'),
            'busca de origem': ({'planejar': mover_com(3, 'Outra')}, 'o UPDATE mudou 18 itens e o plano previa 19'),
            'id fantasma': ({'planejar': mover_com(0, 99999)}, 'o UPDATE mudou 18 itens e o plano previa 19'),
            'preço': ({'planejar_precos': limpar_com(2, 'R$ 1,00')}, 'a limpeza mudou 3 preços e o plano previa 4'),
            'antigo': ({'planejar_precos': limpar_com(3, 'R$ 1,00')}, 'a limpeza mudou 3 preços e o plano previa 4'),
        }
        for nome, (mocks, msg) in casos.items():
            with self.subTest(nome):
                self.assertIn(msg, self.rodar_main(**mocks))
                self.assertEqual(linhas(self.db), self.antes)

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
        self.assertIn(('Aba\\x1b[2K', [0, 1, 0, 1], True), tabela(r.stdout, 'Abas no banco (aba × loja):'))
        self.assertNotIn('\x1b', r.stdout + r.stderr)
        cur = con.execute("INSERT INTO items (loja,item_id,cat,busca,url,posicao) VALUES "
                          "('ml','ESC2',?,'x\x1b[2Ky','https://meli.la/f',99)", (CASA_DECORACAO,))
        con.commit()
        con.close()
        r = self.rodar()
        self.assertEqual(r.returncode, 1)
        self.assertIn(f'id={cur.lastrowid} loja=ml cat="{CASA_DECORACAO}" busca="x\\x1b[2Ky"', r.stderr)
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
        self.assertEqual(set(self.cats().values()), {LISTA, PERFUMES, ELETRONICOS, ELETRODOMESTICOS, CASA_DECORACAO})
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
