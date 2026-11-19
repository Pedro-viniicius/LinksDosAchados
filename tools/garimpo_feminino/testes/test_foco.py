"""Testes do foco.py e do nichos.json (etapa 3 do garimpo feminino). Sem rede.

Rodar: python3 tools/garimpo_feminino/testes/test_foco.py -v
"""
import json
import os
import re
import sys
import unicodedata
import unittest

PASTA = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for v in ('http_proxy', 'https_proxy', 'ftp_proxy'):
    os.environ[v] = 'http://127.0.0.1:9'
os.environ['no_proxy'] = ''
for v in ('ACHADINHOS_SHOPEE_APP_ID', 'ACHADINHOS_SHOPEE_SECRET'):
    os.environ.pop(v, None)
sys.path.insert(0, PASTA)

import foco as F  # noqa: E402

BRIEF_FEMININOS = ['feminino', 'feminina', 'femininos', 'mulher', 'mulheres', 'dama', 'lady', 'gestante',
                   'grávida', 'maternidade', 'sutiã', 'calcinha', 'biquíni', 'saia', 'vestido', 'lingerie']
BRIEF_MASCULINOS = ['masculino', 'masculina', 'masculinos', 'homem', 'homens', 'barba', 'barbear', 'cueca', 'men']
BRIEF_INFANTIS = ['infantil', 'bebê', 'kids', 'menino']


def sem_acento(t):
    return ''.join(c for c in unicodedata.normalize('NFD', t) if not unicodedata.combining(c))


def variantes(termo):
    """O termo como está no brief, sem acento, em maiúsculas e decomposto (NFD)."""
    return {termo, sem_acento(termo), termo.upper(), unicodedata.normalize('NFD', termo)}


def pontos(titulo, classe='mista', nicho=None):
    return F.score(titulo, classe, nicho)[0]


class TermosFemininos(unittest.TestCase):
    def test_cada_termo_do_brief_soma_2_com_e_sem_acento(self):
        for termo in BRIEF_FEMININOS:
            for v in variantes(termo):
                with self.subTest(termo=v):
                    self.assertEqual(pontos('Produto %s novo' % v), 2)

    def test_termo_no_comeco_no_fim_e_sozinho(self):
        for t in ('vestido azul', 'azul vestido', 'vestido', 'VESTIDO.'):
            self.assertEqual(pontos(t), 2, t)

    def test_prefixos_casam_qualquer_terminacao(self):
        for t in ('femininidade', 'femininas', 'mulherzinha', 'mulherada'):
            self.assertEqual(pontos(t), 2, t)

    def test_plural_dos_termos_de_palavra_inteira(self):
        for t in ('vestidos', 'calcinhas', 'saias', 'biquínis', 'sutiãs', 'ladies', 'damas', 'grávidas', 'lingeries'):
            self.assertEqual(pontos(t), 2, t)

    def test_pontua_uma_vez_por_grupo(self):
        self.assertEqual(pontos('Vestido feminino de mulher, lingerie e saia'), 2)

    def test_nao_casa_no_meio_de_outra_palavra(self):
        for t in ('desaia', 'saiado', 'vestidouro', 'ladylike', 'madame', 'gestantes2x', 'semanternidade', 'xlady'):
            self.assertEqual(pontos(t), 0, t)

    def test_separadores_do_titulo(self):
        for t in ('vestido-longo', 'vestido_longo', 'lingerie/pijama', 'Kit(vestido)', "lady's bag"):
            self.assertEqual(pontos(t), 2, t)


class TermosMasculinos(unittest.TestCase):
    def test_cada_termo_do_brief_tira_5_com_e_sem_acento(self):
        for termo in BRIEF_MASCULINOS:
            for v in variantes(termo):
                with self.subTest(termo=v):
                    self.assertEqual(pontos('Produto %s novo' % v), -5)

    def test_men_nao_pega_women_nem_menina(self):
        for t in ('women', 'Women', 'WOMEN', "women's watch", 'menina', 'Meninas', 'menu', 'mental', 'amen',
                  'menor', 'mentol', 'moment', 'Roupa Women Menina'):
            with self.subTest(t=t):
                self.assertEqual(pontos(t), 0)

    def test_men_como_palavra_inteira(self):
        for t in ('men', 'Men', 'MEN', 'Relogio Men Sport', "men's shirt", 'men-s', 'para men,', 'mens watch'):
            self.assertEqual(pontos(t), -5, t)

    def test_women_e_men_no_mesmo_titulo(self):
        self.assertEqual(pontos('Tênis Men Women'), -5)
        self.assertEqual(pontos('Women Tenis'), 0)

    def test_prefixo_masculin(self):
        for t in ('masculinidade', 'Camisa Masculina', 'MASCULINOS'):
            self.assertEqual(pontos(t), -5, t)

    def test_nao_casa_no_meio_de_outra_palavra(self):
        for t in ('barbante', 'cuecao', 'homemade', 'barbearia'):
            self.assertEqual(pontos(t), 0, t)

    def test_pontua_uma_vez_por_grupo(self):
        self.assertEqual(pontos('Kit homem barba cueca men'), -5)


class TermosInfantis(unittest.TestCase):
    def test_cada_termo_do_brief_tira_3_com_e_sem_acento(self):
        for termo in BRIEF_INFANTIS:
            for v in variantes(termo):
                with self.subTest(termo=v):
                    self.assertEqual(pontos('Produto %s novo' % v), -3)

    def test_menina_nao_e_infantil_pelo_brief(self):
        self.assertEqual(pontos('vestido menina'), 2)

    def test_plural_de_bebe_e_menino(self):
        for t in ('bebês', 'bebes', 'meninos', 'infantis', 'Roupas Infantis'):
            self.assertEqual(pontos(t), -3, t)

    def test_pontua_uma_vez_por_grupo(self):
        self.assertEqual(pontos('Kids infantil bebê menino'), -3)


class SomaDosGrupos(unittest.TestCase):
    def test_classe_feminina_soma_3_mista_e_fora_somam_0(self):
        self.assertEqual(pontos('Produto qualquer', 'feminina'), 3)
        self.assertEqual(pontos('Produto qualquer', 'mista'), 0)
        self.assertEqual(pontos('Produto qualquer', 'fora'), 0)
        self.assertEqual(pontos('Produto qualquer', None), 0)

    def test_combinacoes(self):
        casos = [
            ('vestido feminino', 'feminina', 5),
            ('vestido feminino', 'mista', 2),
            ('camisa masculina', 'feminina', -2),
            ('vestido infantil', 'feminina', 2),
            ('vestido masculino infantil', 'feminina', -3),
            ('cueca men', 'mista', -5),
            ('cueca feminina', 'mista', -3),
            ('vestido feminino', 'fora', 2),
        ]
        for titulo, classe, esperado in casos:
            with self.subTest(titulo=titulo, classe=classe):
                self.assertEqual(pontos(titulo, classe), esperado)

    def test_titulo_vazio_ou_invalido_nao_quebra(self):
        for t in ('', '   ', None, 123, b'vestido'):
            self.assertEqual(F.score(t, 'mista', None), (0, 'neutro'))
        self.assertEqual(F.score(None, 'feminina', None), (3, 'medio'))

    def test_classe_invalida(self):
        for c in ('Feminina', 'masculina', '', 'x', 1):
            with self.assertRaises(ValueError, msg=repr(c)):
                F.score('vestido', c, None)


class ExcecaoGestante(unittest.TestCase):
    def test_infantil_nao_penaliza_no_nicho_gestante(self):
        for nicho in ('gestante', 'Gestante & Maternidade', 'gestantematernidade', 'GESTANTE'):
            with self.subTest(nicho=nicho):
                self.assertEqual(F.score('Kit bebê infantil kids menino', 'feminina', nicho), (3, 'medio'))
                self.assertEqual(F.score('Roupa bebê gestante', 'feminina', nicho), (5, 'alto'))

    def test_outros_nichos_e_sem_nicho_penalizam(self):
        for nicho in (None, '', 'roupasfemininas', 'perfumes', 'gestantes', 'maternidade'):
            with self.subTest(nicho=nicho):
                self.assertEqual(F.score('Kit bebê', 'feminina', nicho), (0, 'neutro'))

    def test_a_excecao_e_so_do_infantil(self):
        self.assertEqual(F.score('Roupa masculina bebê', 'feminina', 'gestante'), (-2, 'descartado'))

    def test_o_slug_do_nichos_json_cobre_a_excecao(self):
        slugs = [n['slug'] for n in carregar()]
        self.assertEqual([s for s in slugs if s in F.NICHOS_SEM_PENALIDADE_INFANTIL], ['gestante'])


class Faixas(unittest.TestCase):
    def test_bordas(self):
        esperado = {-100: 'descartado', -2: 'descartado', -1: 'descartado', 0: 'neutro', 1: 'neutro',
                    2: 'medio', 3: 'medio', 4: 'medio', 5: 'alto', 6: 'alto', 100: 'alto'}
        for p, f in esperado.items():
            with self.subTest(pontos=p):
                self.assertEqual(F.faixa(p), f)
                self.assertEqual(F.faixa(p, 'feminina') if f != 'descartado' else 'descartado', f)

    def test_fora_e_sempre_descartado(self):
        for p in (-5, 0, 2, 5, 50):
            self.assertEqual(F.faixa(p, 'fora'), 'descartado')
        self.assertEqual(F.score('vestido feminino lingerie', 'fora', None), (2, 'descartado'))

    def test_faixa_devolvida_pelo_score_nas_bordas(self):
        casos = [
            ('Produto', 'mista', 0, 'neutro'),            # 0
            ('Produto', 'feminina', 3, 'medio'),          # 3
            ('vestido', 'mista', 2, 'medio'),             # 2: limite inferior do medio
            ('vestido infantil', 'feminina', 2, 'medio'),
            ('vestido', 'feminina', 5, 'alto'),           # 5: limite inferior do alto
            ('vestido kids', 'feminina', 2, 'medio'),
            ('Produto kids', 'feminina', 0, 'neutro'),
            ('Produto men', 'feminina', -2, 'descartado'),
            ('vestido kids', 'mista', -1, 'descartado'),  # -1: limite do descartado
        ]
        for titulo, classe, p, f in casos:
            with self.subTest(titulo=titulo, classe=classe):
                self.assertEqual(F.score(titulo, classe, None), (p, f))

    def test_so_as_quatro_faixas(self):
        for t in ('', 'vestido', 'men', 'kids', 'vestido feminino'):
            for c in F.CLASSES:
                self.assertIn(F.score(t, c, None)[1], ('alto', 'medio', 'neutro', 'descartado'))
        self.assertEqual(F.FAIXAS, ('alto', 'medio', 'neutro', 'descartado'))


class Slug(unittest.TestCase):
    def test_exemplos(self):
        casos = {
            'Roupas Femininas': 'roupasfemininas',
            'Gestante & Maternidade': 'gestantematernidade',
            'Moda Íntima, Lingerie & Pijamas': 'modaintimalingeriepi',
            'Cílios & Sobrancelhas': 'ciliossobrancelhas',
            'plus-size_2': 'plussize2',
            '  ÁÉÍÓÚ çãõ  ': 'aeioucao',
            '': '',
            None: '',
        }
        for entrada, esperado in casos.items():
            with self.subTest(entrada=entrada):
                self.assertEqual(F.slug(entrada), esperado)

    def test_so_a_z_0_9_e_ate_20(self):
        for t in ('Relógios, Óculos & Acessórios', 'a' * 50, 'ação!?#$ 123 ' * 4, '日本語 vestido'):
            s = F.slug(t)
            self.assertRegex(s, r'^[a-z0-9]{0,20}$')
        self.assertEqual(len(F.slug('a' * 50)), 20)
        self.assertEqual(F.slug('日本語 vestido'), 'vestido')

    def test_idempotente(self):
        for t in ('Bolsas & Carteiras', 'Gestante & Maternidade', 'x' * 30):
            self.assertEqual(F.slug(F.slug(t)), F.slug(t))


def carregar():
    with open(os.path.join(PASTA, 'nichos.json'), encoding='utf-8') as f:
        return json.load(f)


class NichosJson(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.nichos = carregar()

    def test_formato(self):
        self.assertIsInstance(self.nichos, list)
        for n in self.nichos:
            self.assertEqual(sorted(n), ['nome', 'sementes', 'slug'])
            self.assertIsInstance(n['nome'], str)
            self.assertTrue(n['nome'].strip())
            self.assertIsInstance(n['sementes'], list)
            self.assertTrue(n['sementes'])

    def test_sao_18_nichos_e_196_sementes(self):
        self.assertEqual(len(self.nichos), 18)
        self.assertEqual(sum(len(n['sementes']) for n in self.nichos), 196)

    def test_slugs_unicos_e_validos(self):
        slugs = [n['slug'] for n in self.nichos]
        self.assertEqual(len(set(slugs)), 18)
        for s in slugs:
            self.assertRegex(s, r'^[a-z0-9]{1,20}$', s)
            self.assertEqual(F.slug(s), s)

    def test_nomes_unicos_e_na_ordem_do_brief(self):
        nomes = [n['nome'] for n in self.nichos]
        self.assertEqual(len(set(nomes)), 18)
        self.assertEqual(nomes[0], 'Roupas Femininas')
        self.assertEqual(nomes[1], 'Moda Íntima, Lingerie & Pijamas')
        self.assertEqual(nomes[-1], 'Gestante & Maternidade')

    def test_sementes_em_nfc_sem_pipe_e_limpas(self):
        for n in self.nichos:
            for s in n['sementes']:
                with self.subTest(nicho=n['slug'], semente=s):
                    self.assertIsInstance(s, str)
                    self.assertEqual(unicodedata.normalize('NFC', s), s)
                    self.assertNotIn('|', s)
                    self.assertEqual(s, s.strip())
                    self.assertTrue(s)
                    self.assertNotIn('  ', s)

    def test_sementes_sem_repeticao(self):
        todas = [s for n in self.nichos for s in n['sementes']]
        self.assertEqual(len(todas), len(set(todas)))

    def test_o_arquivo_inteiro_e_nfc(self):
        with open(os.path.join(PASTA, 'nichos.json'), encoding='utf-8') as f:
            bruto = f.read()
        self.assertEqual(unicodedata.normalize('NFC', bruto), bruto)

    def test_sementes_de_pontas_do_brief(self):
        por_slug = {n['slug']: n['sementes'] for n in self.nichos}
        self.assertIn('calça wide leg', por_slug['roupasfemininas'])
        self.assertIn('kimono', por_slug['roupasfemininas'])
        self.assertIn('meia-calça', por_slug['modaintima'])
        self.assertIn('prata 925', por_slug['bijuterias'])
        self.assertIn('vitamina C', por_slug['skincare'])
        self.assertIn('travesseiro gestante', por_slug['gestante'])


class SemRede(unittest.TestCase):
    def test_foco_so_importa_biblioteca_padrao_de_texto(self):
        with open(os.path.join(PASTA, 'foco.py'), encoding='utf-8') as f:
            fonte = f.read()
        importados = set(re.findall(r'^\s*(?:import|from)\s+([\w.]+)', fonte, re.M))
        self.assertEqual(importados, {'re', 'unicodedata'})


if __name__ == '__main__':
    unittest.main()
