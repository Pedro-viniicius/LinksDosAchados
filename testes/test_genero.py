#!/usr/bin/env python3
"""Testes do genero.py (docs/produto/planos/genero-nas-categorias.md, etapa 1).

Uso:  python3 testes/test_genero.py -v

Os títulos são reais, tirados do banco em 2026-11-03 (leitura `mode=ro`), com a busca em que cada um
apareceu. Nenhum teste toca o achadinhos.db, o servidor, a rede ou o WhatsApp: o banco dos testes de
`manuais` e `definir_manual` é um sqlite temporário. A exceção é TestBaseReal, que lê o banco real em `mode=ro`
e só roda com ACHADINHOS_TESTE_DADOS_REAIS=1. Só biblioteca padrão.
"""
import atexit
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unicodedata
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix='achadinhos-genero-')
atexit.register(shutil.rmtree, TMP, ignore_errors=True)
sys.path.insert(0, RAIZ)
import genero as G   # noqa: E402

PERF = 'Perfumes e Perfumaria'
BELE = 'Beleza e Cuidados'
MODA = 'Moda e Viagem'
ELET = 'Black Friday | Eletrônicos'
CASA = 'Casa e Decoração'
ELDO = 'Eletrodomésticos'

# Esquema da migração v2 (plano, "Esquema e contratos"): é a tabela que `definir_manual` usa.
ESQUEMA_MANUAIS = '''CREATE TABLE IF NOT EXISTS generos_manuais (item_pk INTEGER PRIMARY KEY,
  genero TEXT NOT NULL CHECK (genero IN ('feminino','masculino','unissex','sem')),
  atualizado_em TEXT NOT NULL)'''

F, M, U, S = 'feminino', 'masculino', 'unissex', 'sem'

# A classe que lê o achadinhos.db real só roda por pedido (verificar.py --dados-reais): o resultado dela depende
# dos dados do dia, e a suíte padrão não abre o banco real (plano endurecer-engenharia-e-operacao, CA3).
DADOS_REAIS = unittest.skipUnless(os.environ.get('ACHADINHOS_TESTE_DADOS_REAIS') == '1',
                                  'dados reais: rode verificar.py --dados-reais')

# (cat, busca, titulo, genero, origem)
CASOS = [
    # Palavra de gênero no título (origem 'titulo'), inclusive contra a busca.
    (PERF, 'Perfume feminino importado', '212 Men Nyc Carolina Herrera - Perfume Masculino - Eau de Toilette - 100Ml, Carolina Herrera', M, 'titulo'),
    (PERF, 'Carolina Herrera 212 VIP', '212 MEN VIP BLACK EDP 100ML*@', M, 'titulo'),
    (PERF, 'Paco Rabanne One Million', 'Lady Million Paco Rabanne Feminino Eau De Parfum 30 ml', F, 'titulo'),
    (PERF, 'Natura Kaiak', 'Natura Kaiak Feminino Desodorante Colônia', F, 'titulo'),
    (PERF, 'Natura Kaiak', 'NATURA KAIAK AVENTURA DESODORANTE COLONIA FEMININO 100ml', F, 'titulo'),
    (PERF, 'Kit perfume', 'Kit Perfumes Feminino e Masculino 15ml – 2 Unidades, Alta Fixação, Ideal para Presente | Amakha Paris', U, 'titulo'),
    (PERF, 'Miniatura de perfume', 'Armani Code Masc Edt 75Ml, Giorgio Armani', M, 'titulo'),
    (PERF, 'Perfume feminino importado', 'Perf. Fem. EDP 100ml', F, 'titulo'),
    (PERF, 'Calvin Klein CK One', 'Calvin Klein Perfume Ck One 50Ml Edt Unissex', U, 'titulo'),
    (PERF, 'Perfume árabe', 'French Avenue Liquid Brun Eau de Parfum Unissex 100ml', U, 'titulo'),
    (PERF, 'Perfume masculino importado', 'Azzaro Pour Homme Perfume Masculino Eau de Toilette', M, 'titulo'),
    (PERF, 'Egeo O Boticário', 'Perfume Pour Homme Edt 100Ml, Paco Rabanne', M, 'titulo'),
    (PERF, 'Perfume feminino importado', 'Valentino Valentino Donna Born In Roma EDP Spray Women 3.4 oz', F, 'titulo'),
    (PERF, 'Perfume feminino importado', 'La Rive Donna Feminino Eau de Parfum 90 ml', F, 'titulo'),
    (PERF, 'Perfume árabe feminino', "Perfume em Spray Al Haramain L'aventure Femme, Branco, 100ml", F, 'titulo'),
    (PERF, 'Paco Rabanne One Million', 'PACO RABANNE MILLION GOLD FOR HER EDP 30ML', F, 'titulo'),
    (PERF, 'Perfume masculino importado', 'Carolina Herrera Bad Boy - Perfume Masculino - Eau De Toilette - 100Ml', M, 'titulo'),
    (PERF, 'Body splash masculino', 'Kit Perfume e Body Splash Masculino Cowboy 3500 Day Luan Pereira Amaxxon', M, 'titulo'),
    (PERF, 'Perfume masculino nacional', 'Kit Intimen Body Confidence | Clareador Intimo + Perfume para Homens Confiantes e Irresistíveis', M, 'titulo'),
    # Linha de produto conhecida (origem 'titulo'), só quando não há palavra de gênero.
    (PERF, 'Paco Rabanne One Million', 'Perfume One Million Edt. 100ml - 100% Original/Selado', M, 'titulo'),
    (PERF, 'Paco Rabanne Invictus', 'PACO RABANNE INVICTUS PARFUM 100ML', M, 'titulo'),
    (PERF, 'Perfume masculino importado', 'Sauvage Dior - Perfume Masculino - Eau de Parfum 100ml', M, 'titulo'),
    (PERF, 'Perfume masculino importado', 'Eau de Toilette Calvin Klein Ck One, 200Ml', U, 'titulo'),
    (PERF, 'Perfume feminino importado', 'Lancôme, La Vie est Belle EDP, Perfume Feminino', F, 'titulo'),
    (PERF, 'Perfume feminino importado', 'Lancôme La Vie est Belle Vanille Nude Eau de Parfum, Perfume Floral', F, 'titulo'),
    (PERF, 'Loção pós-barba', 'Loção Pós Barba Ocean 100ml', M, 'titulo'),
    (PERF, 'Natura Kaiak', 'NATURA KAIAK GEL 2 EM 1 PARA BARBEAR E PÓS BARBA 100g', M, 'titulo'),
    (PERF, 'Malbec O Boticário', 'Malbec Signature Eau de Parfum 90ml', M, 'titulo'),
    # A palavra de gênero vence a linha: "For Her" e "Feminino" em linha que o dicionário tem como M ou U.
    (PERF, 'Calvin Klein CK One', 'Perfume CK One Shock for Her Calvin Klein Eau de Toilette Feminino 100ml', F, 'titulo'),
    (PERF, 'Calvin Klein CK One', 'Ckin2U Eau de Toilette for Her 50Ml, Calvin Klein', F, 'titulo'),
    # Só a busca decide (origem 'busca').
    (PERF, 'Perfume feminino importado', 'Perfume Olympea EDP 80ml, Paco Rabanne', F, 'busca'),
    (PERF, 'Perfume feminino importado', 'Granado, Perfume, Vintage, Citrus Brasilis, 75 ml', F, 'busca'),
    (PERF, 'Perfume masculino nacional', 'Eudora Colônia Desodorante Club 6 Voyage 95ml', M, 'busca'),
    (PERF, 'Perfume masculino nacional', 'Homem Essence Parfum Natura 100ml', M, 'titulo'),
    # Sem nada que indique (origem ''): título e busca sem palavra de gênero.
    (PERF, 'Paco Rabanne One Million', 'LANCÔME LA NUIT TRESOR INTENSE EAU DE PARFUM 50ML', S, ''),
    (PERF, 'Hidratante corporal perfumado', 'Hidratante Corporal Hydra Soul Live Roses - Soul Cosmeticos', S, ''),
    (PERF, 'Perfume infantil', 'Colônia Splash Infantil Cia. da Natureza, Magali, 190ml', S, ''),
    (PERF, 'Perfume infantil', 'Disney Disney Princess Belle for Kids 3.4 oz EDT Spray', S, ''),
    # Ruído da coleta: vinho "Malbec" e "Bota Invictus" na aba de perfumaria não viram masculino.
    (PERF, 'Malbec O Boticário', 'Vinho Tinto Malbec Argentino Pampa Del Sebo', S, ''),
    (PERF, 'Malbec O Boticário', 'Don Nicolás Malbec Vinho Tinto Argentino 750ml', S, ''),
    (PERF, 'Paco Rabanne Invictus', 'BOTA INVICTUS INTERCEPTOR TAN Nº 37', S, ''),
    # Beleza e Cuidados: palavra de gênero (título > busca), lista própria de barbear e barba, e o resto é 'sem'.
    (BELE, 'Nivea Milk 400 ml', 'Creme Hidratante Nivea Men Max Hydration 400ml', M, 'titulo'),
    (BELE, 'Kit shampoo e condicionador', 'Kit Shampoo e Condicionador Feminino Lisos 400ml', F, 'titulo'),
    (BELE, 'Aparador de barba', 'Aparador de Barba e Cabelo Recarregável Masculino', M, 'titulo'),
    (BELE, 'Aparador de barba', 'Aparador de Barba Philips Série 3000', M, 'titulo'),
    (BELE, 'Hidratante facial', 'Gel de Barbear Gillette Foamy 200ml', M, 'titulo'),
    (BELE, 'Hidratante facial', 'Loção Pós-Barba Nivea Men Sensitive', M, 'titulo'),
    (BELE, 'Hidratante facial', 'Óleo para Barba Viking 30ml', M, 'titulo'),
    (BELE, 'Hidratante facial', 'Kit Barbearia Cerveja Barba e Bigode', M, 'titulo'),
    (BELE, 'Prancha alisadora', 'Prancha Alisadora Unissex Profissional Bivolt', U, 'titulo'),
    (BELE, 'Kit shampoo e condicionador', 'Kit Shampoo Masculino e Feminino Anticaspa', U, 'titulo'),
    (BELE, 'Barbeador elétrico', 'Barbeador Elétrico Philips Série 3000 Recarregável', S, ''),
    (BELE, 'Base de maquiagem', 'Base de Maquiagem Líquida Alta Cobertura Fps 30', S, ''),
    (BELE, 'Kit shampoo e condicionador', 'Kit Shampoo e Condicionador Elseve Reparação Total 5', S, ''),
    (BELE, 'Secador de cabelo', 'Secador de Cabelo Taiff 2000W', S, ''),
    (BELE, 'Máscara capilar', 'Máscara Capilar Lola Cosmetics Morte Súbita 450g', S, ''),
    (BELE, 'Protetor solar facial', 'Protetor Solar Facial La Roche-Posay Anthelios Fps 70', S, ''),
    # Beleza: depilação e Gillette Venus (lâmina feminina) não viram masculino por citar "barbear".
    (BELE, 'Barbeador elétrico', 'Gillette Venus Aparelho de Barbear Feminino 2 un', F, 'titulo'),
    (BELE, 'Barbeador elétrico', 'Gillette Venus Smooth Aparelho para Barbear', S, ''),
    (BELE, 'Kit shampoo e condicionador', 'Depilador Facial Cera Quente Buço e Barba', S, ''),
    # Beleza: as linhas de perfume não valem ("Invictus", "Sauvage", "Million", "Malbec", "CK One", "La Vie est Belle").
    (BELE, 'Hidratante facial', 'Sabonete Líquido Malbec Hidratante Corporal 250ml', S, ''),
    (BELE, 'Hidratante facial', 'Hidratante Corporal Million Gold 200ml', S, ''),
    (BELE, 'Hidratante facial', 'Desodorante Ck One 150ml', S, ''),
    (BELE, 'Hidratante facial', 'Creme La Vie est Belle 200ml', S, ''),
    # Beleza: só a busca decide (palavra de gênero no termo).
    (BELE, 'Shampoo masculino', 'Shampoo Anticaspa 400ml', M, 'busca'),
    # Moda e Viagem: só palavra de gênero, título > busca; sem linha de produto.
    (MODA, 'Tênis Nike', 'Tênis Nike Revolution 7 Masculino', M, 'titulo'),
    (MODA, 'Bolsa feminina', 'Bolsa Transversal Feminina Couro Sintético', F, 'titulo'),
    (MODA, 'Pijama feminino', 'Pijama Feminino Longo Algodão Inverno', F, 'titulo'),
    (MODA, 'Relógio masculino', 'Relógio Casio Standard Masculino Analógico', M, 'titulo'),
    (MODA, 'Relógio feminino', 'Relógio Technos Elegance Feminino Dourado', F, 'titulo'),
    (MODA, 'Mochila para notebook', 'Mochila Unissex Impermeável Notebook 15.6', U, 'titulo'),
    (MODA, 'Relógio masculino', 'Relógio Casio Vintage A168 Unissex', U, 'titulo'),
    (MODA, 'Relógio masculino', 'Relógio Casio Vintage A168WG-9WDF', M, 'busca'),
    (MODA, 'Pijama feminino', 'Pijama Longo Algodão Inverno', F, 'busca'),
    (MODA, 'Relógio masculino', 'Relógio Feminino Dourado Analógico', F, 'titulo'),
    (MODA, 'Kit camisetas', 'Kit Camisetas Básicas 3 Peças Algodão', S, ''),
    (MODA, 'Tênis de corrida', 'Tênis Asics Gel-Excite 10', S, ''),
    (MODA, 'Mala de bordo', 'Mala de Bordo Rígida 10 kg Cadeado Tsa', S, ''),
    (MODA, 'Óculos de sol', 'Óculos de Sol Ray-Ban Aviador', S, ''),
    (MODA, 'Chinelo Havaianas', 'Chinelo Havaianas Top Branco', S, ''),
    # Moda: as linhas de perfume e de barba não valem (tênis "Sauvage", "Invictus", "barba" em camiseta).
    (MODA, 'Tênis Adidas', 'Tênis Invictus Sauvage Casual', S, ''),
    (MODA, 'Kit camisetas', 'Camiseta Estampa Barba Ruiva Algodão', S, ''),
    (MODA, 'Kit camisetas', 'Camiseta Pós-Barba Club', S, ''),
    # As outras abas são sempre 'sem', mesmo com palavra de gênero no título.
    (ELET, 'Relógio inteligente smartwatch', 'Relógio Inteligente Smartwatch GPS Autônomo NOVANTE Masculino Feminino Chamadas Bluetooth Preto', S, ''),
    (ELET, 'Samsung Galaxy Fit3', 'Relógio Digital Feminino Masculino Smartwatch Inteligente Bluetooth, Full Touch', S, ''),
    (CASA, 'Aparelho de jantar', 'Aparelho De Jantar E Chá Donna Lírios 20 Peças Biona', S, ''),
    (ELDO, 'Geladeira', 'Geladeira Brastemp Frost Free Inverse 500 Litros Black Inox - BRE66AE', S, ''),
]


class TestClassificar(unittest.TestCase):
    def test_titulos_reais(self):
        self.assertGreaterEqual(len(CASOS), 40)
        for cat, busca, titulo, genero, origem in CASOS:
            with self.subTest(titulo=titulo[:60]):
                self.assertEqual(G.classificar(cat, busca, titulo), (genero, origem))

    def test_os_quatro_valores_aparecem(self):
        self.assertEqual({c[3] for c in CASOS}, set(G.GENEROS))

    def test_prioridade_titulo_linha_busca(self):
        # título (palavra) > linha > busca
        self.assertEqual(G.classificar(PERF, 'Perfume masculino importado', 'Lady Million Feminino'), (F, 'titulo'))
        self.assertEqual(G.classificar(PERF, 'Perfume masculino importado', 'La Vie est Belle EDP'), (F, 'titulo'))
        # linha > busca: a linha manda mesmo contra a busca de outro gênero
        self.assertEqual(G.classificar(PERF, 'Perfume feminino importado', 'Sauvage EDT 100ml'), (M, 'titulo'))
        # palavra no título > linha: "Lady Million" sai F por "lady"
        self.assertEqual(G.classificar(PERF, '', 'Lady Million EDP'), (F, 'titulo'))
        # só a busca
        self.assertEqual(G.classificar(PERF, 'Perfume feminino importado', 'Olympea EDP'), (F, 'busca'))
        # busca sem palavra de gênero e título sem nada
        self.assertEqual(G.classificar(PERF, 'Natura Kaiak', 'Desodorante Colônia 100ml'), (S, ''))

    def test_masculino_e_feminino_juntos_dao_unissex(self):
        self.assertEqual(G.classificar(PERF, '', 'Kit Masculino e Feminino 2 un'), (U, 'titulo'))
        # também na busca
        self.assertEqual(G.classificar(PERF, 'Perfume masculino e feminino', 'Kit 2 un'), (U, 'busca'))

    def test_unissex_declarado_vence_masculino_e_feminino(self):
        self.assertEqual(G.classificar(PERF, '', 'Perfume Unissex Masculino Feminino'), (U, 'titulo'))
        self.assertEqual(G.classificar(PERF, '', 'Perfume para ambos os sexos'), (U, 'titulo'))
        self.assertEqual(G.classificar(PERF, '', 'Perfume Unisex 100ml'), (U, 'titulo'))

    def test_acentos_caixa_e_normalizacao(self):
        self.assertEqual(G.classificar(PERF, '', 'PERFUME FEMÍNINO 100ML')[0], F)
        self.assertEqual(G.classificar(PERF, '', 'Perfume Femínino 100ml')[0], F)
        self.assertEqual(G.classificar(PERF, '', 'Perfume Unissêx')[0], U)
        # decomposto (NFD): o acento vem como caractere separado
        self.assertEqual(G.classificar(PERF, '', unicodedata.normalize('NFD', 'Perfume Femínino'))[0], F)
        self.assertEqual(G.classificar(PERF, '', unicodedata.normalize('NFD', 'Colônia Homem Ação')), (M, 'titulo'))
        # compatibilidade (NFKD): letras de largura total
        self.assertEqual(G.classificar(PERF, '', 'Perfume ＭＡＳＣＵＬＩＮＯ')[0], M)
        # acento na busca
        self.assertEqual(G.classificar(PERF, 'Perfúme Fêminino', 'Desodorante')[0], F)
        self.assertEqual(G.classificar(PERF, 'Perfume Femínino', 'Desodorante')[0], F)

    def test_palavras_inteiras(self):
        # "men" e "man" não casam dentro de outras palavras; "women" não vira "men".
        for titulo in ('Colônia Mandarina 100ml', 'Perfume Menta Fresca', 'Perfume Roman Holiday',
                       'Colônia Cowboy 3500', 'Perfume Hombresito Club', 'Colônia Mujeriego 100ml'):
            with self.subTest(titulo=titulo):
                self.assertEqual(G.classificar(PERF, '', titulo)[0], S)
        self.assertEqual(G.classificar(PERF, '', 'Lattafa Fakhar Extrait Women Eau de Parfum 100ml')[0], F)
        self.assertEqual(G.classificar(PERF, '', "Dior Sauvage Men's EDT")[0], M)
        self.assertEqual(G.classificar(PERF, '', 'Perf. Masc. EDT 100ml')[0], M)
        # espanhol, singular e plural
        for titulo, genero in (('Perfume para Hombres 100ml', M), ('Perfume para Hombre 100ml', M),
                               ('Perfume para Mujeres 100ml', F), ('Perfume para Mujer 100ml', F)):
            with self.subTest(titulo=titulo):
                self.assertEqual(G.classificar(PERF, '', titulo), (genero, 'titulo'))
        # "fem" e "masc" só valem como palavra inteira
        self.assertEqual(G.classificar(PERF, '', 'Fembot Spray')[0], S)
        self.assertEqual(G.classificar(PERF, '', 'Mascara Facial')[0], S)

    def test_entradas_estranhas(self):
        for titulo, busca in ((None, None), ('', ''), (123, ['x']), (b'masculino', None)):
            with self.subTest(titulo=repr(titulo)):
                self.assertEqual(G.classificar(PERF, busca, titulo), (S, ''))
        self.assertEqual(G.classificar(None, '', 'Perfume Masculino'), (S, ''))
        self.assertEqual(G.classificar('', '', 'Perfume Masculino'), (S, ''))

    def test_aba_com_nome_parecido_nao_vale(self):
        # a comparação é pelo nome exato da aba
        self.assertEqual(G.classificar('perfumes e perfumaria', '', 'Perfume Masculino'), (S, ''))
        self.assertEqual(G.classificar('beleza e cuidados', '', 'Creme Masculino'), (S, ''))
        self.assertEqual(G.classificar(MODA + ' ', '', 'Relógio Masculino'), (S, ''))
        self.assertEqual(G.classificar(PERF + ' ', '', 'Perfume Masculino'), (S, ''))

    def test_linha_de_produto_e_por_aba(self):
        # o mesmo título muda de resultado conforme a aba: cada aba tem a sua lista de linhas
        for titulo in ('Gel de Barbear 200ml', 'Loção Pós Barba'):
            with self.subTest(titulo=titulo):
                self.assertEqual(G.classificar(PERF, '', titulo), (M, 'titulo'))
                self.assertEqual(G.classificar(BELE, '', titulo), (M, 'titulo'))
                self.assertEqual(G.classificar(MODA, '', titulo), (S, ''))
        # "barba" solta é só da beleza (a lista de perfume ficou como era)
        self.assertEqual(G.classificar(PERF, '', 'Óleo para Barba 30ml'), (S, ''))
        self.assertEqual(G.classificar(BELE, '', 'Óleo para Barba 30ml'), (M, 'titulo'))
        # linha de perfume só na perfumaria
        for titulo in ('Invictus 100ml', 'Sauvage 100ml', 'One Million 100ml', 'Malbec 100ml',
                       'Ck One 100ml', 'La Vie est Belle 50ml'):
            with self.subTest(titulo=titulo):
                self.assertNotEqual(G.classificar(PERF, '', titulo)[0], S)
                self.assertEqual(G.classificar(BELE, '', titulo), (S, ''))
                self.assertEqual(G.classificar(MODA, '', titulo), (S, ''))
        # "barbear" tem prefixo (barbearia); "barba" é palavra inteira (barbante, barbaridade não casam)
        self.assertEqual(G.classificar(BELE, '', 'Kit Barbearia Completo'), (M, 'titulo'))
        for titulo in ('Barbante de Algodão', 'Esmalte Barbaridade 8ml', 'Barbie Maquiagem Infantil'):
            with self.subTest(titulo=titulo):
                self.assertEqual(G.classificar(BELE, '', titulo), (S, ''))
        # a palavra de gênero continua vencendo a linha e a guarda
        self.assertEqual(G.classificar(BELE, '', 'Gillette Venus Barbear Feminino'), (F, 'titulo'))
        self.assertEqual(G.classificar(BELE, '', 'Cera Depilatória Masculina'), (M, 'titulo'))
        # beleza e moda: a guarda de ruído da perfumaria não vale (nem existe: palavra de gênero é o que conta)
        self.assertEqual(G.classificar(MODA, '', 'Bota Masculina Couro'), (M, 'titulo'))
        self.assertEqual(G.classificar(BELE, '', 'Vinho Tinto Pós Barba'), (M, 'titulo'))

    def test_guarda_de_ruido_nao_atinge_perfume(self):
        # a guarda só desliga a linha de produto; palavra de gênero continua valendo
        self.assertEqual(G.classificar(PERF, '', 'Bota Invictus Masculina')[0], M)
        # "tinto"/"vinho" soltos num kit de sabonete não mudam o que já era 'sem'
        self.assertEqual(G.classificar(PERF, 'Kit sabonete perfumado', 'Phebo Caixa de Sabonetes, Vinho, 90g')[0], S)
        # perfumes de linha conhecida sem as palavras da guarda continuam masculinos
        self.assertEqual(G.classificar(PERF, '', 'Malbec Magnetic Desodorante Colônia 100ml')[0], M)
        self.assertEqual(G.classificar(PERF, '', 'Invictus Victory Elixir EDP 100ml')[0], M)


class TestAbas(unittest.TestCase):
    def test_constantes(self):
        self.assertEqual(G.GENEROS, ('feminino', 'masculino', 'unissex', 'sem'))
        self.assertEqual(G.ABAS_COM_GENERO, (PERF, BELE, MODA))

    def test_abas_com_genero_existem_no_buscas_json(self):
        with open(os.path.join(RAIZ, 'buscas.json'), encoding='utf-8') as f:
            abas = set(json.load(f))
        for aba in G.ABAS_COM_GENERO:
            self.assertIn(aba, abas)
        # as demais abas do buscas.json continuam sem público
        for aba in abas - set(G.ABAS_COM_GENERO):
            self.assertEqual(G.classificar(aba, 'Perfume masculino', 'Perfume Masculino'), (S, ''))
            self.assertEqual(G.classificar(aba, 'Barba masculino', 'Gel de Barbear Masculino'), (S, ''))


def _banco(com_tabela=True):
    caminho = os.path.join(TMP, 'g%d.db' % len(os.listdir(TMP)))
    con = sqlite3.connect(caminho)
    if com_tabela:
        con.execute(ESQUEMA_MANUAIS)
        con.commit()
    return con


class TestManuais(unittest.TestCase):
    def setUp(self):
        self.con = _banco()
        self.addCleanup(self.con.close)

    def test_tabela_ausente_da_vazio(self):
        con = _banco(com_tabela=False)
        self.addCleanup(con.close)
        self.assertEqual(G.manuais(con), {})

    def test_tabela_vazia(self):
        self.assertEqual(G.manuais(self.con), {})

    def test_le_as_correcoes(self):
        self.con.executemany('INSERT INTO generos_manuais VALUES (?,?,?)',
                             [(1, F, 'x'), (2, M, 'x'), (3, U, 'x'), (4, S, 'x')])
        self.assertEqual(G.manuais(self.con), {1: F, 2: M, 3: U, 4: S})

    def test_definir_grava_e_apaga(self):
        G.definir_manual(self.con, 7, M, '2026-11-03T10:00:00')
        self.assertEqual(G.manuais(self.con), {7: M})
        self.assertEqual(self.con.execute('SELECT atualizado_em FROM generos_manuais').fetchone()[0],
                         '2026-11-03T10:00:00')
        G.definir_manual(self.con, 7, None, '2026-11-03T11:00:00')
        self.assertEqual(G.manuais(self.con), {})
        # apagar o que não existe não é erro
        G.definir_manual(self.con, 7, None, '2026-11-03T11:00:00')

    def test_definir_de_novo_troca_o_valor_e_a_data(self):
        G.definir_manual(self.con, 7, M, 'a')
        G.definir_manual(self.con, 7, F, 'b')
        self.assertEqual(self.con.execute('SELECT item_pk, genero, atualizado_em FROM generos_manuais').fetchall(),
                         [(7, F, 'b')])

    def test_definir_o_mesmo_valor_nao_conta_como_mudanca(self):
        G.definir_manual(self.con, 7, F, 'a')
        antes = self.con.total_changes
        G.definir_manual(self.con, 7, F, 'b')
        self.assertEqual(self.con.total_changes, antes)
        # a data também não anda
        self.assertEqual(self.con.execute('SELECT atualizado_em FROM generos_manuais').fetchone()[0], 'a')
        G.definir_manual(self.con, 7, M, 'c')
        self.assertEqual(self.con.total_changes, antes + 1)
        self.assertEqual(self.con.execute('SELECT genero, atualizado_em FROM generos_manuais').fetchall(), [(M, 'c')])
        # apagar o que não existe também não muda nada
        G.definir_manual(self.con, 8, None, 'd')
        self.assertEqual(self.con.total_changes, antes + 1)

    def test_definir_nao_faz_commit(self):
        G.definir_manual(self.con, 7, M, 'a')
        self.assertTrue(self.con.in_transaction)
        outra = sqlite3.connect(self.con.execute('PRAGMA database_list').fetchone()[2])
        self.addCleanup(outra.close)
        self.assertEqual(G.manuais(outra), {})
        self.con.commit()
        self.assertEqual(G.manuais(outra), {7: M})
        # e o rollback desfaz
        G.definir_manual(self.con, 8, F, 'a')
        self.con.rollback()
        self.assertEqual(G.manuais(self.con), {7: M})

    def test_definir_valor_invalido_nao_grava_nem_ecoa(self):
        for valor in ('Feminino', 'infantil', '', 'x\'; DROP TABLE generos_manuais;--', 1, [F]):
            with self.subTest(valor=repr(valor)):
                with self.assertRaises(ValueError) as cm:
                    G.definir_manual(self.con, 7, valor, 'a')
                self.assertNotIn('DROP', str(cm.exception))
                self.assertNotIn('infantil', str(cm.exception))
        self.assertEqual(G.manuais(self.con), {})

    def test_definir_na_tabela_ausente_levanta(self):
        con = _banco(com_tabela=False)
        self.addCleanup(con.close)
        with self.assertRaises(sqlite3.OperationalError):
            G.definir_manual(con, 1, M, 'a')

    def test_migracao_real_cria_a_tabela(self):
        # Quando o disparo.migrar já cria a versão 2, a tabela dele serve a este módulo.
        import disparo as D
        if D.VERSAO_ESQUEMA < 2:
            self.skipTest('migração v2 ainda não existe')
        con = sqlite3.connect(os.path.join(TMP, 'migrado.db'))
        self.addCleanup(con.close)
        D.migrar(con)
        self.assertEqual(G.manuais(con), {})
        G.definir_manual(con, 3, U, 'a')
        con.commit()
        self.assertEqual(G.manuais(con), {3: U})
        G.definir_manual(con, 3, None, 'a')
        con.commit()
        self.assertEqual(G.manuais(con), {})


class TestDoItem(unittest.TestCase):
    def test_sem_correcao_usa_o_classificador(self):
        self.assertEqual(G.do_item(1, PERF, '', 'Perfume Masculino', {}), (M, 'titulo'))
        self.assertEqual(G.do_item(1, PERF, 'Perfume feminino importado', 'Olympea', {}), (F, 'busca'))
        self.assertEqual(G.do_item(1, PERF, '', 'Hidratante', {}), (S, ''))
        self.assertEqual(G.do_item(1, PERF, '', 'Perfume Masculino', None), (M, 'titulo'))

    def test_correcao_vence_o_titulo(self):
        self.assertEqual(G.do_item(1, PERF, '', 'Perfume Masculino', {1: F}), (F, 'manual'))
        self.assertEqual(G.do_item(1, PERF, '', 'Perfume Masculino', {1: S}), (S, 'manual'))
        self.assertEqual(G.do_item(1, PERF, '', 'Hidratante', {1: U}), (U, 'manual'))

    def test_correcao_e_por_item(self):
        self.assertEqual(G.do_item(2, PERF, '', 'Perfume Masculino', {1: F}), (M, 'titulo'))

    def test_fora_da_aba_e_sempre_sem_e_a_correcao_fica_guardada(self):
        m = {1: F}
        self.assertEqual(G.do_item(1, CASA, '', 'Sofá Lady', m), (S, ''))
        # nas abas novas com público a correção manual vale
        self.assertEqual(G.do_item(1, BELE, '', 'Shampoo 400ml', {1: M}), (M, 'manual'))
        self.assertEqual(G.do_item(1, MODA, '', 'Tênis Masculino', {1: F}), (F, 'manual'))
        self.assertEqual(G.do_item(2, MODA, '', 'Tênis Masculino', {1: F}), (M, 'titulo'))
        self.assertEqual(G.do_item(1, ELET, '', 'Smartwatch Masculino', m), (S, ''))
        self.assertEqual(m, {1: F})
        # voltando para a aba, a correção vale de novo
        self.assertEqual(G.do_item(1, PERF, '', 'Perfume Masculino', m), (F, 'manual'))

    def test_correcao_com_valor_fora_da_lista_e_ignorada(self):
        self.assertEqual(G.do_item(1, PERF, '', 'Perfume Masculino', {1: 'infantil'}), (M, 'titulo'))

    def test_com_banco(self):
        con = _banco()
        self.addCleanup(con.close)
        G.definir_manual(con, 5, F, 'a')
        m = G.manuais(con)
        self.assertEqual(G.do_item(5, PERF, '', 'Perfume Masculino', m), (F, 'manual'))
        G.definir_manual(con, 5, None, 'b')
        self.assertEqual(G.do_item(5, PERF, '', 'Perfume Masculino', G.manuais(con)), (M, 'titulo'))


@DADOS_REAIS
class TestBaseReal(unittest.TestCase):
    """CA1: a distribuição na base de 2026-11-03. Só roda com ACHADINHOS_TESTE_DADOS_REAIS=1 (verificar.py
    --dados-reais) e se o achadinhos.db existir; abre em `mode=ro`."""

    @classmethod
    def setUpClass(cls):
        caminho = os.path.join(RAIZ, 'achadinhos.db')
        if not os.path.exists(caminho):
            raise unittest.SkipTest('sem achadinhos.db')
        con = sqlite3.connect('file:%s?mode=ro' % caminho, uri=True)
        try:
            cls.linhas = con.execute('SELECT cat, busca, titulo FROM items').fetchall()
        finally:
            con.close()

    def test_distribuicao_da_perfumaria(self):
        # Base de 2026-11-03 (3.051 itens): F 696, M 966, U 178, sem 1.211 (+-3% foi medido na entrega).
        # A base cresce, então aqui vale a proporção, com folga de 5 pontos percentuais.
        perf = [l for l in self.linhas if l[0] == PERF]
        if len(perf) < 1000:
            self.skipTest('base muito diferente da de 2026-11-03')
        cont = {g: 0 for g in G.GENEROS}
        for cat, busca, titulo in perf:
            cont[G.classificar(cat, busca, titulo)[0]] += 1
        esperado = {F: 696, M: 966, U: 178, S: 1211}
        for g, n in esperado.items():
            with self.subTest(genero=g):
                self.assertAlmostEqual(cont[g] / len(perf), n / 3051, delta=0.05, msg=str(cont))

    def test_outras_abas_sao_sem(self):
        for cat, busca, titulo in self.linhas:
            if cat not in G.ABAS_COM_GENERO:
                self.assertEqual(G.classificar(cat, busca, titulo), (S, ''))


if __name__ == '__main__':
    unittest.main()
