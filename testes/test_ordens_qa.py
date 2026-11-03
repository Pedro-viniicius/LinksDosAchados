#!/usr/bin/env python3
"""Testes de QA das ordens da coleta da Amazon e dos 42 termos de perfumaria
(docs/produto/planos/perfumaria-tres-lojas.md, E3 e E5: CA4 e CA5).

Uso:  python3 testes/test_ordens_qa.py -v

Complementa test_coletar_amazon.py e test_coletar_amazon_qa.py sem repetir o que eles provam:
  - o buscas.json é conferido de forma independente (lista congelada dos 28 termos antigos, bytes UTF-8,
    NFC, hash das outras abas);
  - a URL e a chave da relevância são comparadas, para os 140 termos reais, com a fórmula do código
    antigo escrita aqui de novo;
  - o progresso antigo (28 termos feitos) é reaproveitado e só os 14 novos são baixados;
  - cada ordem tem a sua chave e a sua URL (`&s=`), uma queda no meio preserva o progresso, e a CLI
    de verdade (subprocesso) recusa as combinações inválidas sem criar banco nem tocar a rede.
`baixar`, `parse_busca` e `pausa` são falsos; banco e arquivo de progresso são temporários; proxies mortos.
Só biblioteca padrão (o coletar_amazon exige beautifulsoup4 instalado).
"""
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import unittest
import urllib.parse
from unittest import mock

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_REAL = os.path.realpath(os.path.join(RAIZ, 'achadinhos.db'))
FEITOS_REAL = os.path.realpath(os.path.join(RAIZ, 'coleta_amazon_feitos.txt'))
TMP = tempfile.mkdtemp(prefix='teste-ordens-qa-')
for v in ('http_proxy', 'https_proxy', 'ftp_proxy'):
    os.environ[v] = 'http://127.0.0.1:9'
os.environ['no_proxy'] = ''
os.environ.setdefault('ACHADINHOS_DB', os.path.join(TMP, 'achadinhos.db'))
os.environ.setdefault('ACHADINHOS_FEITOS', os.path.join(TMP, 'feitos.txt'))
sys.path.insert(0, RAIZ)

import coletar_amazon as C  # noqa: E402
import servidor as S  # noqa: E402

assert os.path.realpath(S.DB) != DB_REAL and os.path.realpath(C.FEITOS) != FEITOS_REAL, \
    'o teste não pode tocar os dados reais'

PERFUMES = 'Perfumes e Perfumaria'
# Os 28 termos de "Perfumes e Perfumaria" antes da E3, congelados aqui (texto idêntico, byte a byte).
ANTIGOS_28 = [
    'Perfume masculino importado', 'Perfume feminino importado', 'Perfume masculino nacional',
    'Perfume feminino nacional', 'Kit perfume', 'Miniatura de perfume', 'Body splash', 'Desodorante colônia',
    'Hidratante corporal perfumado', 'Perfume árabe', 'Perfume infantil', 'Perfume Natura', 'Natura Kaiak',
    'Natura Essencial', 'Perfume O Boticário', 'Malbec O Boticário', 'Egeo O Boticário', 'Perfume Eudora',
    'Carolina Herrera 212 VIP', 'Carolina Herrera Good Girl', 'Paco Rabanne One Million',
    'Paco Rabanne Invictus', 'Dior Sauvage', 'Lancôme La Vie Est Belle', 'Calvin Klein CK One',
    'Jean Paul Gaultier Le Male', 'Azzaro Pour Homme', 'Lattafa']
# Os 14 novos da tabela "Termos" do plano, na posição que ocupam (1 a 21 da lista do dono).
NOVOS_14 = ['Kit perfume com hidratante', 'Kit perfume com desodorante', 'Perfume árabe feminino',
            'Perfume árabe masculino', 'Perfume unissex', 'Body splash feminino', 'Body splash masculino',
            'Colônia feminina', 'Colônia masculina', 'Óleo corporal perfumado', 'Desodorante corporal perfumado',
            'Kit sabonete perfumado', 'Perfume para cabelo', 'Loção pós-barba']
# As 21 primeiras posições da tabela (a ordem importa: é a prioridade da lista do dono).
PRIMEIROS_21 = [
    'Perfume feminino importado', 'Perfume masculino importado', 'Perfume feminino nacional',
    'Perfume masculino nacional', 'Kit perfume com hidratante', 'Kit perfume com desodorante',
    'Perfume árabe feminino', 'Perfume árabe masculino', 'Perfume unissex', 'Body splash feminino',
    'Body splash masculino', 'Colônia feminina', 'Colônia masculina', 'Hidratante corporal perfumado',
    'Óleo corporal perfumado', 'Desodorante corporal perfumado', 'Kit sabonete perfumado',
    'Perfume para cabelo', 'Miniatura de perfume', 'Kit perfume', 'Loção pós-barba']
# Hash (json compacto, UTF-8) das outras três abas em HEAD antes da E3: não podem mudar.
HASH_OUTRAS_ABAS = {
    'Black Friday | Eletrônicos': '4ba0c9f013b6643bb51026517b1fc3907e39b0e5f4af4a06f1afe809f428165e',
    'Eletrodomésticos': 'c738485e8052d4f2d5ee0e3bf9138cfe6a2ce7a84f2a70373d7bcd9d9bcd48c1',
    'Casa e Decoração': 'c8b7d72fa91c595b73972c5a4ce5fc21f750c8c4adf9d52ad11fec07722942f7'}
VALORES_S = {'vendidos': 'exact-aware-popularity-rank', 'avaliados': 'review-rank', 'caros': 'price-desc-rank'}


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


def buscas_reais():
    with open(os.path.join(RAIZ, 'buscas.json'), 'rb') as f:
        bruto = f.read()
    return bruto, json.loads(bruto.decode('utf-8'))


def url_antiga(termo):
    """A URL de relevância do código antes da E5 (coletar_amazon.py de HEAD), escrita de novo."""
    return 'https://www.amazon.com.br/s?k=' + urllib.parse.quote_plus(termo)


# ================================================================ CA4: os 42 termos
class TestTermos42(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bruto, cls.buscas = buscas_reais()
        cls.perfumes = cls.buscas[PERFUMES]

    def test_ca4_sao_42_na_ordem_da_tabela(self):
        self.assertEqual(len(self.perfumes), 42)
        self.assertEqual(self.perfumes[:21], PRIMEIROS_21)
        self.assertEqual(self.perfumes[21:25], ['Body splash', 'Desodorante colônia', 'Perfume árabe', 'Perfume infantil'])
        self.assertEqual(self.perfumes[25:], ANTIGOS_28[11:])   # os 17 de marca, na ordem de hoje

    def test_ca4_os_28_antigos_estao_la_byte_a_byte(self):
        em_bytes = {t.encode('utf-8') for t in self.perfumes}
        for antigo in ANTIGOS_28:
            with self.subTest(antigo):
                self.assertIn(antigo.encode('utf-8'), em_bytes)
        self.assertEqual([t for t in self.perfumes if t in ANTIGOS_28 or t in NOVOS_14],
                         [t for t in self.perfumes], 'só há antigos e os 14 novos, nada a mais')
        self.assertEqual(len(set(ANTIGOS_28) | set(NOVOS_14)), 42)
        self.assertEqual({t for t in self.perfumes if t not in ANTIGOS_28}, set(NOVOS_14))

    def test_ca4_nfc_sem_barra_vertical_sem_repeticao_e_sem_espaco_sobrando(self):
        for t in self.perfumes:
            with self.subTest(t):
                self.assertTrue(unicodedata.is_normalized('NFC', t))
                self.assertNotIn('|', t)
                self.assertEqual(t, ' '.join(t.split()), 'sem espaço nas pontas, duplo ou invisível')
                self.assertTrue(t.isprintable())
                self.assertNotIn('﻿', t)
        sem_acento = [''.join(c for c in unicodedata.normalize('NFD', t.casefold()) if not unicodedata.combining(c))
                      for t in self.perfumes]
        self.assertEqual(len(set(sem_acento)), 42, 'dois termos só diferem por caixa ou acento')
        urls = {url_antiga(t) for t in self.perfumes}
        self.assertEqual(len(urls), 42, 'dois termos dariam a mesma busca na Amazon')

    def test_ca4_o_arquivo_cru_esta_em_nfc_e_sem_bom(self):
        self.assertFalse(self.bruto.startswith(b'\xef\xbb\xbf'))
        texto = self.bruto.decode('utf-8')
        self.assertTrue(unicodedata.is_normalized('NFC', texto), 'o arquivo todo tem que estar em NFC')
        self.assertNotIn('\\u', texto, 'termos com acento ficam como UTF-8, não como escape')

    def test_ca4_as_outras_tres_abas_nao_mudaram(self):
        for aba, esperado in HASH_OUTRAS_ABAS.items():
            with self.subTest(aba):
                h = hashlib.sha256(json.dumps(self.buscas[aba], ensure_ascii=False).encode('utf-8')).hexdigest()
                self.assertEqual(h, esperado)
        self.assertEqual(list(self.buscas), list(HASH_OUTRAS_ABAS) + [PERFUMES], 'as quatro abas, na ordem de sempre')

    def test_ca4_termos_novos_nao_colidem_com_termo_de_outra_aba(self):
        outros = {t for aba, ts in self.buscas.items() if aba != PERFUMES for t in ts}
        self.assertEqual(outros & set(self.perfumes), set())

    def test_ca4_o_bloco_do_ml_tem_os_mesmos_42_termos(self):
        """Leitura independente do bloco BUSCAS do coletar_ml.js (entre os marcadores), sem rodar o script."""
        with open(os.path.join(RAIZ, 'coletar_ml.js'), encoding='utf-8') as f:
            js = f.read()
        ini = js.index('const BUSCAS = ')
        corpo = js[js.index('{', ini):js.index('\n  };', ini) + 4]
        self.assertEqual(json.loads(corpo)[PERFUMES], self.perfumes)


# ================================================================ CA5: URL e chave
class TestUrlEChave(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.termos = [t for ts in buscas_reais()[1].values() for t in ts]

    def test_ca5_relevancia_dos_140_termos_reais_tem_a_url_e_a_chave_de_hoje(self):
        self.assertEqual(len(self.termos), 140)
        for t in self.termos:
            self.assertEqual(C.url_busca(t), url_antiga(t), t)
            self.assertEqual(C.url_busca(t, 'relevancia'), url_antiga(t), t)
            self.assertEqual(C.chave_busca(t), f'busca|{t}', t)
            self.assertNotIn('&s=', C.url_busca(t))

    def test_ca5_outras_ordens_so_acrescentam_um_s_e_mantem_o_k(self):
        for t in self.termos:
            for ordem, valor in VALORES_S.items():
                with self.subTest(t=t, ordem=ordem):
                    url = C.url_busca(t, ordem)
                    self.assertEqual(url, url_antiga(t) + '&s=' + valor)
                    q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
                    self.assertEqual(q, {'k': [t], 's': [valor]})
                    self.assertEqual(C.chave_busca(t, ordem), f'ordem|{ordem}|{t}')

    def test_ca5_chaves_de_ordens_diferentes_nunca_se_confundem_nem_pelo_feitos(self):
        # o feitos() reescreve `busca|a|b` como `busca|b`: a chave `ordem|…` não pode ser tocada por isso
        chaves = {C.chave_busca(t, o) for t in self.termos for o in C.ORDENS}
        self.assertEqual(len(chaves), 140 * 4)
        caminho = os.path.join(TMP, 'feitos-chaves.txt')
        with open(caminho, 'w', encoding='utf-8') as f:
            f.write(''.join(c + '\n' for c in chaves))
        with mock.patch.object(C, 'FEITOS', caminho):
            self.assertEqual(C.feitos(), chaves)

    def test_ca5_termo_chamado_como_uma_ordem_nao_vira_chave_de_ordem(self):
        self.assertEqual(C.chave_busca('vendidos'), 'busca|vendidos')
        self.assertEqual(C.chave_busca('vendidos', 'vendidos'), 'ordem|vendidos|vendidos')
        caminho = os.path.join(TMP, 'feitos-ambiguo.txt')
        with open(caminho, 'w', encoding='utf-8') as f:
            f.write('busca|vendidos\n')
        with mock.patch.object(C, 'FEITOS', caminho):
            self.assertEqual(C.feitos(), {'busca|vendidos'})
            self.assertNotIn(C.chave_busca('vendidos', 'vendidos'), C.feitos())

    def test_ca5_ler_ordens_bordas(self):
        self.assertEqual(C.ler_ordens(' vendidos , caros '), ['vendidos', 'caros'])
        self.assertEqual(C.ler_ordens('caros,caros,vendidos,caros'), ['caros', 'vendidos'])
        self.assertEqual(C.ler_ordens('relevancia'), ['relevancia'])
        for ruim in ('', ',', 'vendidos,', ',vendidos', 'Vendidos', 'mais_vendidos', 'vendidos;caros', 'vendidos caros',
                     'constructor', '__proto__', None, 'caros,price-desc-rank'):
            with self.subTest(ruim=ruim), self.assertRaises(C.ArgInvalido):
                C.ler_ordens(ruim)


# ================================================================ CA5: coleta com progresso
class TestColetaComOrdens(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(dir=TMP)
        self.feitos = os.path.join(self.dir, 'feitos.txt')
        self.db = os.path.join(self.dir, 'banco.db')
        bruto, _ = buscas_reais()
        with open(os.path.join(self.dir, 'buscas.json'), 'wb') as f:
            f.write(bruto)
        self.baixados, self.falhar_na = [], None
        for p in (mock.patch.object(C, 'BASE', self.dir), mock.patch.object(C, 'FEITOS', self.feitos),
                  mock.patch.object(S, 'DB', self.db),
                  mock.patch.object(C, 'baixar', self.baixar), mock.patch.object(C, 'parse_busca', self.parse),
                  mock.patch.object(C, 'pausa', lambda *a, **k: None)):
            p.start()
            self.addCleanup(p.stop)
        S.criar_banco()
        p = mock.patch('sys.stdout', io.StringIO()); p.start(); self.addCleanup(p.stop)

    def baixar(self, url):
        self.baixados.append(url)
        if self.falhar_na is not None and len(self.baixados) == self.falhar_na:
            raise C.Bloqueado(url)
        return url, url

    def parse(self, h):
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(h).query)
        k = q['k'][0].replace(' ', '_')
        s = q.get('s', ['rel'])[0]
        return [{'asin': 'B' + hashlib.sha1(f'{k}|{s}|{i}'.encode()).hexdigest()[:9].upper(),
                 'data': {'titulo': f'{k} {s} {i}', 'preco': 'R$ 1,00'}} for i in range(2)]

    def linhas_feitos(self):
        if not os.path.exists(self.feitos):
            return []
        with open(self.feitos, encoding='utf-8') as f:
            return f.read().splitlines()

    def itens(self):
        con = S.conectar()
        try:
            return [dict(r) for r in con.execute('SELECT * FROM items ORDER BY id')]
        finally:
            con.close()

    def test_ca5_progresso_antigo_dos_28_so_baixa_os_14_novos(self):
        # 28 termos feitos como o código antigo marcava: `busca|<termo>` e a forma ainda mais antiga `busca|<aba>|<termo>`
        with open(self.feitos, 'w', encoding='utf-8') as f:
            for i, t in enumerate(ANTIGOS_28):
                f.write((f'busca|{t}' if i % 2 else f'busca|{PERFUMES}|{t}') + '\n')
        C.coletar_buscas(PERFUMES, ['relevancia'])
        pedidos = {urllib.parse.parse_qs(urllib.parse.urlsplit(u).query)['k'][0] for u in self.baixados}
        self.assertEqual(pedidos, set(NOVOS_14))
        self.assertEqual(len(self.baixados), 14)
        self.assertTrue(all('&s=' not in u for u in self.baixados))
        self.assertEqual({i['busca'] for i in self.itens()}, set(NOVOS_14))
        self.assertEqual({i['cat'] for i in self.itens()}, {PERFUMES})
        # o arquivo só ganha as 14 chaves novas, no formato de sempre
        novas = [l for l in self.linhas_feitos() if l.startswith('busca|') and l.count('|') == 1 and l[6:] in NOVOS_14]
        self.assertEqual(sorted(novas), sorted(f'busca|{t}' for t in NOVOS_14))

    def test_ca5_o_progresso_da_relevancia_nao_vale_para_as_outras_ordens(self):
        with open(self.feitos, 'w', encoding='utf-8') as f:
            f.write(''.join(f'busca|{t}\n' for t in buscas_reais()[1][PERFUMES]))
        C.coletar_buscas(PERFUMES, ['vendidos'])
        self.assertEqual(len(self.baixados), 42)
        self.assertTrue(all(u.endswith('&s=exact-aware-popularity-rank') for u in self.baixados))

    def test_ca5_tres_ordens_coletam_42_vezes_cada_com_a_url_certa_e_depois_nao_repetem(self):
        C.coletar_buscas(PERFUMES, ['vendidos', 'avaliados', 'caros'])
        self.assertEqual(len(self.baixados), 126)
        for ordem, valor in VALORES_S.items():
            self.assertEqual(sum(u.endswith('&s=' + valor) for u in self.baixados), 42, ordem)
        linhas = self.linhas_feitos()
        self.assertEqual(len(linhas), 126)
        self.assertEqual(set(linhas), {f'ordem|{o}|{t}' for o in VALORES_S for t in buscas_reais()[1][PERFUMES]})
        self.assertFalse([l for l in linhas if l.startswith('busca|')], 'só a relevância usa o prefixo busca|')
        n = len(self.baixados)
        C.coletar_buscas(PERFUMES, ['vendidos', 'avaliados', 'caros'])
        self.assertEqual(len(self.baixados), n, 'segunda rodada não pode baixar nada')

    def test_ca5_so_coleta_a_aba_pedida_e_grava_cat_e_busca_certas(self):
        C.coletar_buscas(PERFUMES, ['caros'])
        its = self.itens()
        self.assertTrue(its)
        self.assertEqual({i['cat'] for i in its}, {PERFUMES})
        self.assertEqual({i['busca'] for i in its}, set(buscas_reais()[1][PERFUMES]))
        self.assertEqual({i['loja'] for i in its}, {'amazon'})
        for i in its:
            self.assertTrue(S.eh_link_afiliado(i['url']), i['url'])

    def test_ca5_queda_no_meio_preserva_o_progresso_e_a_proxima_rodada_continua_dali(self):
        self.falhar_na = 5
        with self.assertRaises(C.Bloqueado):
            C.coletar_buscas(PERFUMES, ['avaliados', 'caros'])
        esperado = [f'ordem|{o}|{t}' for t in PRIMEIROS_21[:2] for o in ('avaliados', 'caros')]   # 4 feitos, o 5º caiu
        self.assertEqual(self.linhas_feitos(), esperado)
        self.baixados.clear(); self.falhar_na = None
        C.coletar_buscas(PERFUMES, ['avaliados', 'caros'])
        self.assertEqual(len(self.baixados), 84 - 4)
        self.assertEqual(len(self.linhas_feitos()), 84)
        self.assertEqual(len(set(self.linhas_feitos())), 84, 'nenhuma chave duplicada')

    def test_ca5_sem_resultado_numa_ordem_nao_marca_so_aquela_ordem(self):
        original = self.parse
        self.parse = lambda h: [] if 's=review-rank' in h else original(h)
        with mock.patch.object(C, 'parse_busca', self.parse):
            C.coletar_buscas(PERFUMES, ['vendidos', 'avaliados'])
        linhas = self.linhas_feitos()
        self.assertEqual(len([l for l in linhas if l.startswith('ordem|vendidos|')]), 42)
        self.assertEqual([l for l in linhas if l.startswith('ordem|avaliados|')], [])

    def test_ca5_ordem_ou_aba_invalida_nao_baixa_nada_nem_cria_progresso(self):
        for cat, ordens in ((PERFUMES, ['barato']), (PERFUMES, ['vendidos', 'barato']), ('Aba que não existe', ['vendidos']),
                            (None, ['vendidos']), (None, ['relevancia', 'caros']), (PERFUMES.upper(), ['caros'])):
            with self.subTest(cat=cat, ordens=ordens), self.assertRaises(C.ArgInvalido):
                C.coletar_buscas(cat, ordens)
        self.assertEqual(self.baixados, [])
        self.assertEqual(self.linhas_feitos(), [])
        self.assertEqual(self.itens(), [])

    def test_ca5_sem_cat_a_relevancia_continua_coletando_as_quatro_abas(self):
        C.coletar_buscas()
        self.assertEqual(len(self.baixados), 140)
        self.assertEqual(self.baixados, [url_antiga(t) for ts in buscas_reais()[1].values() for t in ts])
        self.assertEqual(len(self.linhas_feitos()), 140)
        self.assertTrue(all(l.startswith('busca|') for l in self.linhas_feitos()))

    def test_ca5_item_ja_coletado_por_relevancia_nao_vira_duplicado_em_outra_ordem(self):
        C.coletar_buscas(PERFUMES, ['relevancia'])
        antes = self.itens()
        C.coletar_buscas(PERFUMES, ['vendidos'])   # o parse falso devolve outros ASIN por ordem: não repete
        # um ASIN que a relevância já trouxe e a ordem traz de novo mantém linha, cat e url
        with mock.patch.object(C, 'parse_busca', lambda h: [{'asin': 'B0REPETIDO', 'data': {'titulo': 'Repetido', 'preco': 'R$ 5,00'}}]):
            self.feitos_antes = self.linhas_feitos()
            C.coletar_buscas(PERFUMES, ['caros'])
        repetidos = [i for i in self.itens() if i['item_id'] == 'B0REPETIDO']
        self.assertEqual(len(repetidos), 1)
        self.assertEqual(repetidos[0]['cat'], PERFUMES)
        self.assertGreater(len(self.itens()), len(antes))


# ================================================================ CA5: a CLI de verdade
class TestCliSubprocesso(unittest.TestCase):
    """Roda `python3 coletar_amazon.py ...` de verdade. Só combinações que saem antes de qualquer download."""

    def rodar(self, *args):
        d = tempfile.mkdtemp(dir=TMP)
        env = dict(os.environ, ACHADINHOS_DB=os.path.join(d, 'b.db'), ACHADINHOS_FEITOS=os.path.join(d, 'f.txt'),
                   http_proxy='http://127.0.0.1:9', https_proxy='http://127.0.0.1:9', ftp_proxy='http://127.0.0.1:9',
                   no_proxy='', PYTHONDONTWRITEBYTECODE='1')
        r = subprocess.run([sys.executable, os.path.join(RAIZ, 'coletar_amazon.py'), *args], cwd=d, env=env,
                           capture_output=True, text=True, timeout=60, encoding='utf-8')
        self.assertFalse(os.path.exists(os.path.join(d, 'f.txt')), 'a recusa não pode criar progresso')
        self.assertNotIn('Traceback', r.stderr)
        return r, d

    def test_ca5_ordens_sem_cat_e_recusado_com_codigo_2_e_sem_criar_banco(self):
        r, d = self.rodar('buscas', '--ordens', 'vendidos,avaliados,caros')
        self.assertEqual(r.returncode, 2)
        self.assertIn('--cat', r.stderr)
        self.assertFalse(os.path.exists(os.path.join(d, 'b.db')), 'recusa antes de abrir o banco')
        self.assertEqual(r.stdout, '')

    def test_ca5_ordem_desconhecida_e_recusada(self):
        r, d = self.rodar('buscas', '--cat', PERFUMES, '--ordens', 'vendidos,baratos')
        self.assertEqual(r.returncode, 2)
        self.assertIn('baratos', r.stderr)
        self.assertFalse(os.path.exists(os.path.join(d, 'b.db')))

    def test_ca5_cat_ou_ordens_fora_do_modo_buscas_e_recusado(self):
        for args in (('--cat', PERFUMES), ('--ordens', 'caros'), ('whatsapp', '--cat', PERFUMES),
                     ('tudo', '--cat', PERFUMES, '--ordens', 'caros')):
            with self.subTest(args=args):
                r, d = self.rodar(*args)
                self.assertEqual(r.returncode, 2)
                self.assertFalse(os.path.exists(os.path.join(d, 'b.db')))

    def test_ca5_aba_desconhecida_sai_com_2_e_lista_as_abas_validas(self):
        r, d = self.rodar('buscas', '--cat', 'Perfumes', '--ordens', 'caros')
        self.assertEqual(r.returncode, 2)
        self.assertIn(PERFUMES, r.stderr)

    def test_ca5_cat_vazio_e_recusado(self):
        r, _ = self.rodar('buscas', '--cat', '')
        self.assertEqual(r.returncode, 2)

    def test_ca5_ajuda_lista_as_ordens(self):
        r, _ = self.rodar('--help')
        self.assertEqual(r.returncode, 0)
        for o in C.ORDENS:
            self.assertIn(o, r.stdout)


if __name__ == '__main__':
    unittest.main()
