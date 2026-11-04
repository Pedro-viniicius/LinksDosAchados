#!/usr/bin/env python3
"""Testes do coletar_amazon.py (docs/produto/planos/eletronicos-e-coleta-ml.md, etapa 3).

Uso:  python3 testes/test_coletar_amazon.py -v

ACHADINHOS_DB e ACHADINHOS_FEITOS apontam para um diretório temporário antes do import (o
coletar_amazon importa o servidor, que lê a variável ao carregar). `baixar`, `parse_busca` e
`pausa` são falsos: nenhum teste acessa a Amazon, o achadinhos.db real ou o
coleta_amazon_feitos.txt real. Qualquer saída acidental para a rede bate num proxy morto.
Só biblioteca padrão (o coletar_amazon exige beautifulsoup4 instalado).
"""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix='teste-coletar-amazon-')
for v in ('http_proxy', 'https_proxy', 'ftp_proxy'):
    os.environ[v] = 'http://127.0.0.1:9'
os.environ['ACHADINHOS_DB'] = os.path.join(TMP, 'achadinhos.db')
os.environ['ACHADINHOS_FEITOS'] = os.path.join(TMP, 'feitos.txt')
sys.path.insert(0, RAIZ)

import coletar_amazon as C  # noqa: E402
import servidor as S  # noqa: E402

assert os.path.dirname(S.DB) == TMP and os.path.dirname(C.FEITOS) == TMP, 'o teste não pode tocar os dados reais'


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


# Campos que fazem um achado passar no piso (nota >= 4,5 e >= 100 avaliações); os parses falsos os usam
NO_PISO = {'avaliacao': '4,6 de 5 estrelas', 'num_avaliacoes': '1.234', 'vendas': ''}


def escrever_feitos(*linhas):
    with open(C.FEITOS, 'w', encoding='utf-8') as f:
        f.write(''.join(l + '\n' for l in linhas))


def ler_feitos():
    return open(C.FEITOS, encoding='utf-8').read().splitlines()


class Base(unittest.TestCase):
    def setUp(self):
        for p in (S.DB, S.DB + '-wal', S.DB + '-shm', C.FEITOS):
            if os.path.exists(p):
                os.remove(p)
        S.criar_banco()

    def itens(self):
        con = S.conectar()
        try:
            return [dict(r) for r in con.execute('SELECT * FROM items ORDER BY id')]
        finally:
            con.close()


class TestFeitos(Base):
    def test_sem_arquivo_nao_ha_feitos(self):
        self.assertEqual(C.feitos(), set())

    def test_linha_antiga_com_cat_conta_pelo_termo(self):
        escrever_feitos('busca|Black Friday|iPhone 17', 'busca|Casa Nova|Air fryer')
        f = C.feitos()
        self.assertIn(C.chave_busca('iPhone 17'), f)
        self.assertIn(C.chave_busca('Air fryer'), f)

    def test_linha_com_barra_vertical_na_cat_conta(self):
        escrever_feitos('busca|Black Friday | Eletrônicos|Smart TV')
        self.assertIn(C.chave_busca('Smart TV'), C.feitos())

    def test_linha_nova_por_termo_conta(self):
        escrever_feitos('busca|Geladeira')
        self.assertIn(C.chave_busca('Geladeira'), C.feitos())

    def test_linha_de_outra_cat_nao_vale_para_outro_termo(self):
        escrever_feitos('busca|Black Friday|iPhone 17')
        self.assertNotIn(C.chave_busca('iPhone 16'), C.feitos())

    def test_whatsapp_fica_como_esta(self):
        escrever_feitos('whatsapp|https://link.amazon/B08oG5uBs')
        self.assertEqual(C.feitos(), {'whatsapp|https://link.amazon/B08oG5uBs'})

    def test_chave_nova_e_por_termo(self):
        self.assertEqual(C.chave_busca('Smart TV'), 'busca|Smart TV')

    def test_chave_da_relevancia_e_a_de_sempre(self):
        self.assertEqual(C.chave_busca('Smart TV', 'relevancia'), 'busca|Smart TV')

    def test_chave_das_outras_ordens_tem_prefixo_proprio(self):
        self.assertEqual(C.chave_busca('Smart TV', 'vendidos'), 'ordem|vendidos|Smart TV')
        self.assertEqual(C.chave_busca('Smart TV', 'caros'), 'ordem|caros|Smart TV')

    def test_chave_ordem_sobrevive_ao_feitos_sem_virar_outro_termo(self):
        # a armadilha: `busca|<termo>|<ordem>` seria lida como o termo "<ordem>"
        escrever_feitos('ordem|vendidos|Smart TV', 'busca|Geladeira')
        self.assertEqual(C.feitos(), {'ordem|vendidos|Smart TV', 'busca|Geladeira'})
        self.assertNotIn(C.chave_busca('Smart TV'), C.feitos())

    def test_ordem_desconhecida_na_chave_e_recusada(self):
        with self.assertRaises(C.ArgInvalido):
            C.chave_busca('Smart TV', 'baratos')


class TestUrlEOrdens(unittest.TestCase):
    def test_relevancia_mantem_a_url_de_hoje(self):
        self.assertEqual(C.url_busca('Perfume Importado'), 'https://www.amazon.com.br/s?k=Perfume+Importado')
        self.assertEqual(C.url_busca('Perfume Importado', 'relevancia'),
                         'https://www.amazon.com.br/s?k=Perfume+Importado')

    def test_outras_ordens_acrescentam_s(self):
        base = 'https://www.amazon.com.br/s?k=Smart+TV&s='
        self.assertEqual(C.url_busca('Smart TV', 'vendidos'), base + 'exact-aware-popularity-rank')
        self.assertEqual(C.url_busca('Smart TV', 'avaliados'), base + 'review-rank')
        self.assertEqual(C.url_busca('Smart TV', 'caros'), base + 'price-desc-rank')

    def test_termo_com_acento_e_codificado(self):
        self.assertEqual(C.url_busca('Água de Colônia', 'caros'),
                         'https://www.amazon.com.br/s?k=%C3%81gua+de+Col%C3%B4nia&s=price-desc-rank')

    def test_ler_ordens(self):
        self.assertEqual(C.ler_ordens('vendidos,avaliados,caros'), ['vendidos', 'avaliados', 'caros'])
        self.assertEqual(C.ler_ordens(' caros , caros,relevancia'), ['caros', 'relevancia'])

    def test_ler_ordens_desconhecida_ou_vazia_e_recusada(self):
        for ruim in ('baratos', 'vendidos,', '', 'vendidos,,caros', 'Vendidos'):
            with self.subTest(ruim=ruim), self.assertRaises(C.ArgInvalido):
                C.ler_ordens(ruim)


class TestColetarBuscas(Base):
    BUSCAS = {
        'Black Friday | Eletrônicos': ['iPhone 17', 'Smart TV'],
        'Eletrodomésticos': ['Geladeira'],
        'Perfumes e Perfumaria': ['Perfume Importado Masculino'],
    }

    def setUp(self):
        super().setUp()
        self.json = os.path.join(TMP, 'buscas.json')
        with open(self.json, 'w', encoding='utf-8') as f:
            json.dump(self.BUSCAS, f, ensure_ascii=False)
        self.baixados = []
        # os patches substituem o BASE só para achar o buscas.json do teste
        for p in (mock.patch.object(C, 'BASE', TMP),
                  mock.patch.object(C, 'baixar', self.baixar),
                  mock.patch.object(C, 'parse_busca', self.parse),
                  mock.patch.object(C, 'pausa', lambda *a, **k: None)):
            p.start()
            self.addCleanup(p.stop)

    def baixar(self, url):
        self.baixados.append(url)
        return url, url  # o "html" é a própria url; o parse falso deriva os itens dela

    def parse(self, h):
        k = h.split('k=', 1)[1].replace('+', '_')
        return [{'asin': f'B{k}{i}', 'data': {'titulo': f'{k} {i}', 'preco': 'R$ 10,00', **NO_PISO}} for i in range(2)]

    def test_grava_cada_termo_com_a_cat_exata_do_json(self):
        C.coletar_buscas()
        pares = {(i['busca'], i['cat']) for i in self.itens()}
        self.assertEqual(pares, {
            ('iPhone 17', 'Black Friday | Eletrônicos'),
            ('Smart TV', 'Black Friday | Eletrônicos'),
            ('Geladeira', 'Eletrodomésticos'),
            ('Perfume Importado Masculino', 'Perfumes e Perfumaria'),
        })
        self.assertEqual(len(self.itens()), 8)
        self.assertTrue(all('tag=' + S.TAG_AMAZON in i['url'] for i in self.itens()))
        self.assertEqual(ler_feitos(), ['busca|iPhone 17', 'busca|Smart TV', 'busca|Geladeira',
                                        'busca|Perfume Importado Masculino'])

    def test_so_coleta_os_termos_que_faltam(self):
        escrever_feitos('busca|Black Friday|iPhone 17',        # linha antiga, cat antiga
                        'busca|Casa Nova|Geladeira',            # outra cat antiga
                        'busca|Black Friday | Eletrônicos|Smart TV')  # '|' dentro da cat
        C.coletar_buscas()
        self.assertEqual(len(self.baixados), 1)
        self.assertIn('Perfume', self.baixados[0])
        self.assertEqual({i['busca'] for i in self.itens()}, {'Perfume Importado Masculino'})
        self.assertEqual(ler_feitos()[-1], 'busca|Perfume Importado Masculino')

    def test_renomear_a_chave_nao_recoleta(self):
        C.coletar_buscas()
        n = len(self.baixados)
        renomeado = {'Aba Nova': [t for ts in self.BUSCAS.values() for t in ts]}
        with open(self.json, 'w', encoding='utf-8') as f:
            json.dump(renomeado, f, ensure_ascii=False)
        C.coletar_buscas()
        self.assertEqual(len(self.baixados), n)

    def test_termo_sem_resultado_nao_e_marcado(self):
        with mock.patch.object(C, 'parse_busca', lambda h: []):
            C.coletar_buscas()
        self.assertEqual(self.itens(), [])
        self.assertFalse(os.path.exists(C.FEITOS) and ler_feitos())

    def test_item_existente_mantem_cat_e_url(self):
        asin = 'BiPhone_170'
        con = S.conectar()
        S.upsert(con, {'loja': 'amazon', 'item_id': asin, 'cat': 'Aba Antiga', 'busca': 'antigo',
                       'url': 'https://www.amazon.com.br/dp/%s?tag=%s' % (asin, S.TAG_AMAZON),
                       'data': {'titulo': 'velho', 'preco': 'R$ 99,00'}})
        con.commit(); con.close()
        antes = [i for i in self.itens() if i['item_id'] == asin][0]
        C.coletar_buscas()
        depois = [i for i in self.itens() if i['item_id'] == asin]
        self.assertEqual(len(depois), 1)
        self.assertEqual(depois[0]['cat'], 'Aba Antiga')
        self.assertEqual(depois[0]['url'], antes['url'])
        self.assertEqual(depois[0]['titulo'], 'iPhone_17 0')  # preço/título atualizam

    # --- ordens (perfumaria-tres-lojas, etapa E5) ---

    def test_padrao_e_so_relevancia_com_url_e_chave_de_hoje(self):
        C.coletar_buscas()
        self.assertEqual(self.baixados, [
            'https://www.amazon.com.br/s?k=iPhone+17', 'https://www.amazon.com.br/s?k=Smart+TV',
            'https://www.amazon.com.br/s?k=Geladeira', 'https://www.amazon.com.br/s?k=Perfume+Importado+Masculino'])
        self.assertTrue(all(l.startswith('busca|') for l in ler_feitos()))

    def test_cat_com_ordens_coleta_so_os_termos_da_aba(self):
        C.coletar_buscas('Black Friday | Eletrônicos', ['vendidos', 'avaliados', 'caros'])
        s = 'https://www.amazon.com.br/s?k=%s&s=%s'
        self.assertEqual(self.baixados, [
            s % ('iPhone+17', 'exact-aware-popularity-rank'), s % ('iPhone+17', 'review-rank'),
            s % ('iPhone+17', 'price-desc-rank'), s % ('Smart+TV', 'exact-aware-popularity-rank'),
            s % ('Smart+TV', 'review-rank'), s % ('Smart+TV', 'price-desc-rank')])
        self.assertEqual(ler_feitos(), [
            'ordem|vendidos|iPhone 17', 'ordem|avaliados|iPhone 17', 'ordem|caros|iPhone 17',
            'ordem|vendidos|Smart TV', 'ordem|avaliados|Smart TV', 'ordem|caros|Smart TV'])
        self.assertEqual({i['cat'] for i in self.itens()}, {'Black Friday | Eletrônicos'})

    def test_busca_continua_sendo_o_termo_e_a_url_e_de_afiliado(self):
        C.coletar_buscas('Eletrodomésticos', ['caros'])
        itens = self.itens()
        self.assertEqual({i['busca'] for i in itens}, {'Geladeira'})
        self.assertTrue(itens and all(i['url'].startswith('https://www.amazon.com.br/dp/')
                                      and i['url'].endswith('?tag=' + S.TAG_AMAZON) for i in itens))

    def test_progresso_antigo_da_relevancia_nao_recoleta(self):
        escrever_feitos('busca|Black Friday|iPhone 17', 'busca|Casa Nova|Smart TV')
        C.coletar_buscas('Black Friday | Eletrônicos', ['relevancia'])
        self.assertEqual(self.baixados, [])
        C.coletar_buscas('Black Friday | Eletrônicos', ['relevancia', 'vendidos'])
        self.assertEqual([u for u in self.baixados if '&s=' not in u], [])  # só a ordem nova foi baixada
        self.assertEqual(len(self.baixados), 2)

    def test_chave_de_ordem_feita_nao_recoleta_e_a_relevancia_continua_separada(self):
        escrever_feitos('ordem|vendidos|Geladeira')
        C.coletar_buscas('Eletrodomésticos', ['vendidos'])
        self.assertEqual(self.baixados, [])
        C.coletar_buscas('Eletrodomésticos', ['vendidos', 'relevancia'])
        self.assertEqual(self.baixados, ['https://www.amazon.com.br/s?k=Geladeira'])

    def test_ordens_sem_cat_e_recusado_sem_baixar_nada(self):
        with self.assertRaises(C.ArgInvalido):
            C.coletar_buscas(None, ['vendidos'])
        self.assertEqual(self.baixados, [])

    def test_ordem_desconhecida_e_aba_desconhecida_sao_recusadas_sem_baixar_nada(self):
        with self.assertRaises(C.ArgInvalido):
            C.coletar_buscas('Eletrodomésticos', ['baratos'])
        with self.assertRaises(C.ArgInvalido):
            C.coletar_buscas('Aba que não existe', ['vendidos'])
        self.assertEqual(self.baixados, [])

    def test_cat_aceita_a_aba_em_nfd(self):
        import unicodedata
        C.coletar_buscas(unicodedata.normalize('NFD', 'Eletrodomésticos'))
        self.assertEqual(len(self.baixados), 1)

    def test_item_existente_mantem_cat_e_url_em_outra_ordem(self):
        asin = 'BGeladeira0'
        con = S.conectar()
        S.upsert(con, {'loja': 'amazon', 'item_id': asin, 'cat': 'Aba Antiga', 'busca': 'antigo',
                       'url': 'https://www.amazon.com.br/dp/%s?tag=%s' % (asin, S.TAG_AMAZON),
                       'data': {'titulo': 'velho', 'preco': 'R$ 99,00'}})
        con.commit(); con.close()
        antes = [i for i in self.itens() if i['item_id'] == asin][0]
        C.coletar_buscas('Eletrodomésticos', ['vendidos'])
        depois = [i for i in self.itens() if i['item_id'] == asin]
        self.assertEqual(len(depois), 1)
        self.assertEqual((depois[0]['cat'], depois[0]['url']), ('Aba Antiga', antes['url']))


# --- piso de qualidade e recusa de usado (abas-nichadas-e-coleta, etapa 4, CA7) ---

def card(asin, titulo, preco='R$ 99,90', riscado=None, por_unidade=None, nota='4,6 de 5 estrelas',
         avaliacoes='1.234', compras=None):
    """Um resultado da busca da Amazon, no formato que o parse_busca lê. `por_unidade` é o preço por
    litro/unidade: a Amazon o escreve como `.a-price.a-text-price` SEM `data-a-strike`."""
    return f"""<div data-component-type="s-search-result" data-asin="{asin}">
      <h2><span>{titulo}</span></h2>
      <img class="s-image" src="https://m.media-amazon.com/images/I/{asin}.jpg">
      <div data-cy="reviews-block">
        {f'<span class="a-icon-alt">{nota}</span>' if nota else ''}
        {f'<a href="/dp/{asin}#customerReviews"><span class="a-size-base s-underline-text">{avaliacoes}</span></a>' if avaliacoes else ''}
      </div>
      {f'<span class="a-size-base a-color-secondary">{compras}</span>' if compras else ''}
      <span class="a-price" data-a-size="xl"><span class="a-offscreen">{preco}</span></span>
      {f'<span class="a-price a-text-price" data-a-size="b" data-a-strike="true"><span class="a-offscreen">{riscado}</span></span>' if riscado else ''}
      {f'<span class="a-price a-text-price" data-a-size="b" data-a-color="secondary"><span class="a-offscreen">{por_unidade}</span></span><span>/litro</span>' if por_unidade else ''}
    </div>"""


def pagina(*cards):
    return '<html><body><div class="s-main-slot">' + ''.join(cards) + '</div></body></html>'


def parse_um(**kw):
    (r,) = C.parse_busca(pagina(card('B0TESTE0001', 'Produto de teste', **kw)))
    return r['data']


class TestParseBusca(unittest.TestCase):
    def test_preco_por_litro_sem_riscado_nao_vira_preco_antigo(self):
        d = parse_um(preco='R$ 69,90', por_unidade='R$ 349,50')
        self.assertEqual((d['preco'], d['preco_antigo'], d['desconto']), ('R$ 69,90', '', ''))

    def test_preco_por_unidade_menor_tambem_nao_vira_antigo(self):
        d = parse_um(preco='R$ 59,90', por_unidade='R$ 5,99')
        self.assertEqual((d['preco_antigo'], d['desconto']), ('', ''))

    def test_riscado_e_lido_mesmo_com_preco_por_litro_na_mesma_oferta(self):
        d = parse_um(preco='R$ 80,00', riscado='R$ 100,00', por_unidade='R$ 400,00')
        self.assertEqual((d['preco'], d['preco_antigo'], d['desconto']), ('R$ 80,00', 'R$ 100,00', '-20%'))

    def test_riscado_menor_ou_igual_ao_preco_e_descartado(self):
        d = parse_um(preco='R$ 80,00', riscado='R$ 80,00')
        self.assertEqual((d['preco_antigo'], d['desconto']), ('', ''))

    def test_le_nota_avaliacoes_e_compras_no_mes(self):
        d = parse_um(nota='4,7 de 5 estrelas', avaliacoes='(2,3 mil)', compras='Mais de 1 mil compras no mês passado')
        self.assertEqual((d['avaliacao'], d['num_avaliacoes'], d['vendas']),
                         ('4,7 de 5 estrelas', '2,3 mil', 'Mais de 1 mil compras no mês passado'))

    def test_sem_nota_nem_volume_os_campos_ficam_vazios(self):
        d = parse_um(nota=None, avaliacoes=None)
        self.assertEqual((d['avaliacao'], d['num_avaliacoes'], d['vendas']), ('', '', ''))


class TestEhUsado(unittest.TestCase):
    def test_titulos_de_usado_sao_recusados(self):
        for t in ('iPhone 13 128GB Seminovo', 'Dell Latitude 5420 Recondicionado', 'Celular Usado Galaxy S21',
                  'Galaxy S21 Renovado Excelente', 'Fritadeira Vitrine', 'Fone Open Box', 'Echo Dot REFURBISHED',
                  'Câmeras usadas', 'Kit SEMINOVA', 'iPhone Recondicionada', 'Notebook (Seminovo)', 'Smart TV usado, sem caixa',
                  'Seminovo'.upper(), 'Recondicionado'.upper(), 'Usado', 'open  box', 'Notebook recondicionados'):
            with self.subTest(t=t):
                self.assertTrue(C.eh_usado(t))

    def test_acento_e_forma_decomposta_nao_importam(self):
        import unicodedata
        self.assertTrue(C.eh_usado(unicodedata.normalize('NFD', 'Aparelho Seminovo')))

    def test_titulos_normais_passam(self):
        for t in ('Smart TV 50" 4K Samsung', 'Kit Renovador de Couro', 'Fone abusado resistente', 'Casadinho 2 em 1',
                  'Desusado', 'Panela Usadora', 'Perfume Vitrines', 'Notebook Dell Inspiron 15', 'Lava e seca 11 kg', '', None):
            with self.subTest(t=t):
                self.assertFalse(C.eh_usado(t))


class TestPassaPiso(unittest.TestCase):
    def d(self, nota='4,6 de 5 estrelas', aval='1.234', vendas=''):
        return {'avaliacao': nota, 'num_avaliacoes': aval, 'vendas': vendas}

    def test_nota_44_nao_passa_mesmo_com_muito_volume(self):
        self.assertFalse(C.passa_piso(self.d(nota='4,4 de 5 estrelas', aval='5.000', vendas='Mais de 10 mil compras no mês passado')))

    def test_nota_45_com_100_avaliacoes_passa(self):
        self.assertTrue(C.passa_piso(self.d(nota='4,5 de 5 estrelas', aval='100')))

    def test_nota_45_com_99_avaliacoes_e_sem_compras_nao_passa(self):
        self.assertFalse(C.passa_piso(self.d(nota='4,5 de 5 estrelas', aval='99')))

    def test_nota_46_com_poucas_avaliacoes_mas_mais_de_mil_compras_passa(self):
        self.assertTrue(C.passa_piso(self.d(aval='12', vendas='Mais de 1 mil compras no mês passado')))
        self.assertTrue(C.passa_piso(self.d(aval='', vendas='Mais de 50 compras no mês passado')))

    def test_avaliacoes_em_mil_e_milhar_com_ponto(self):
        self.assertTrue(C.passa_piso(self.d(aval='1,2 mil')))
        self.assertTrue(C.passa_piso(self.d(aval='(12 mil)')))
        self.assertTrue(C.passa_piso(self.d(aval='1.234')))
        self.assertFalse(C.passa_piso(self.d(aval='99')))

    def test_nota_com_ponto_e_nota_5(self):
        self.assertTrue(C.passa_piso(self.d(nota='4.5 de 5 estrelas')))
        self.assertTrue(C.passa_piso(self.d(nota='5,0 de 5 estrelas')))

    def test_sem_nota_ou_nota_ilegivel_nao_passa(self):
        for nota in ('', None, 'sem avaliações', '45 de 5 estrelas', '9,9 de 5 estrelas'):
            with self.subTest(nota=nota):
                self.assertFalse(C.passa_piso(self.d(nota=nota)))

    def test_nota_boa_sem_nenhum_volume_nao_passa(self):
        self.assertFalse(C.passa_piso(self.d(aval='', vendas='')))
        self.assertFalse(C.passa_piso(self.d(aval='sem avaliações', vendas='')))

    def test_dado_vazio_ou_nulo_nao_passa_e_nao_quebra(self):
        for d in (None, {}, {'avaliacao': None, 'num_avaliacoes': None, 'vendas': None}):
            with self.subTest(d=d):
                self.assertFalse(C.passa_piso(d))


class TestColetaComPiso(Base):
    """A coleta com `parse_busca` de verdade sobre um HTML de busca (só `baixar` e `pausa` são falsos)."""
    PAGINA = pagina(
        card('B0BOM00001', 'Shampoo bom', nota='4,6 de 5 estrelas', avaliacoes='1.234'),
        card('B0NOTA4400', 'Shampoo nota baixa', nota='4,4 de 5 estrelas', avaliacoes='5.000'),
        card('B0POUCA9900', 'Shampoo poucas avaliações', nota='4,5 de 5 estrelas', avaliacoes='99'),
        card('B0COMPRAS00', 'Shampoo vendido', nota='4,6 de 5 estrelas', avaliacoes='12',
             compras='Mais de 1 mil compras no mês passado'),
        card('B0USADO0000', 'Celular Seminovo', nota='4,8 de 5 estrelas', avaliacoes='9.000'),
        card('B0SEMNOTA00', 'Sabonete líquido 5 L', nota=None, avaliacoes=None))

    def setUp(self):
        super().setUp()
        with open(os.path.join(TMP, 'buscas.json'), 'w', encoding='utf-8') as f:
            json.dump({'Beleza e Cuidados': ['Shampoo']}, f, ensure_ascii=False)
        self.html = self.PAGINA
        self.baixados = []
        for p in (mock.patch.object(C, 'BASE', TMP), mock.patch.object(C, 'baixar', self.baixar),
                  mock.patch.object(C, 'pausa', lambda *a, **k: None)):
            p.start()
            self.addCleanup(p.stop)

    def baixar(self, url):
        self.baixados.append(url)
        return url, self.html

    def coletar(self, *args):
        with mock.patch('sys.stdout', io.StringIO()) as out:
            C.coletar_buscas(*args)
        return out.getvalue()

    def test_grava_so_o_que_passa_no_piso_e_nao_e_usado(self):
        log = self.coletar()
        # a página tem 6 resultados: bom, nota 4,4, 99 avaliações, compras, usado e sem nota
        self.assertEqual({i['item_id'] for i in self.itens()}, {'B0BOM00001', 'B0COMPRAS00'})
        self.assertIn('[Beleza e Cuidados] Shampoo: 6 achados, 2 no piso, 2 novos', log)
        self.assertEqual(ler_feitos(), ['busca|Shampoo'])

    def test_segunda_rodada_mostra_zero_novos_quando_o_item_ja_existe(self):
        self.coletar()
        os.remove(C.FEITOS)
        log = self.coletar()
        self.assertIn('6 achados, 2 no piso, 0 novos', log)
        self.assertEqual(len(self.itens()), 2)

    def test_item_usado_com_nota_e_volume_otimos_nao_e_gravado(self):
        self.html = pagina(card('B0USADO0000', 'iPhone 13 Recondicionado', nota='4,9 de 5 estrelas', avaliacoes='9.000'),
                           card('B0BOM00001', 'Shampoo bom'))
        log = self.coletar()
        self.assertEqual([i['item_id'] for i in self.itens()], ['B0BOM00001'])
        self.assertIn('2 achados, 1 no piso, 1 novos', log)

    def test_preco_por_litro_nao_vira_preco_antigo_no_banco(self):
        # passa no piso (nota e avaliações padrão) e traz o preço por litro sem riscado
        self.html = pagina(card('B0LITRO0000', 'Sabonete 5 L', preco='R$ 69,90', por_unidade='R$ 349,50'))
        self.coletar()
        (i,) = self.itens()
        self.assertEqual((i['preco'], i['preco_antigo'], i['desconto']), ('R$ 69,90', '', ''))

    def test_termo_todo_abaixo_do_piso_nao_grava_nem_marca_como_feito(self):
        self.html = pagina(card('B0NOTA4400', 'Shampoo nota baixa', nota='4,4 de 5 estrelas'),
                           card('B0USADO0000', 'Celular Seminovo'))
        log = self.coletar()
        self.assertEqual(self.itens(), [])
        self.assertFalse(os.path.exists(C.FEITOS) and ler_feitos())
        self.assertIn('2 achados, 0 no piso, 0 novos', log)
        self.assertIn('próxima rodada', log)
        # a próxima rodada tenta o termo de novo (sem loop: uma tentativa por rodada)
        self.coletar()
        self.assertEqual(len(self.baixados), 2)

    def test_termo_todo_abaixo_do_piso_nao_repete_a_busca_dentro_da_rodada(self):
        # só a página sem nenhum resultado é repetida (3 tentativas); a que tem resultado ruim é lida uma vez
        self.html = pagina(card('B0NOTA4400', 'Shampoo nota baixa', nota='4,4 de 5 estrelas'))
        self.coletar()
        self.assertEqual(len(self.baixados), 1)

    def test_ordem_diferente_tambem_aplica_o_piso_e_marca_pela_chave_da_ordem(self):
        log = self.coletar('Beleza e Cuidados', ['vendidos'])
        self.assertEqual({i['item_id'] for i in self.itens()}, {'B0BOM00001', 'B0COMPRAS00'})
        self.assertIn('Shampoo (vendidos): 6 achados, 2 no piso, 2 novos', log)
        self.assertEqual(ler_feitos(), ['ordem|vendidos|Shampoo'])


class TestCLI(Base):
    def setUp(self):
        super().setUp()
        self.chamadas = []
        for p in (mock.patch.object(C, 'coletar_buscas', lambda *a, **k: self.chamadas.append(('buscas', a, k))),
                  mock.patch.object(C, 'coletar_whatsapp', lambda: self.chamadas.append(('whatsapp',)))):
            p.start()
            self.addCleanup(p.stop)

    def recusa(self, *argv):
        with mock.patch('sys.stderr', io.StringIO()) as err, self.assertRaises(SystemExit) as r:
            C.main(list(argv))
        self.assertEqual(r.exception.code, 2)
        self.assertEqual(self.chamadas, [])
        return err.getvalue()

    def roda(self, *argv):
        with mock.patch('sys.stdout', io.StringIO()):
            C.main(list(argv))

    def test_buscas_sem_opcoes_e_so_relevancia_em_todas_as_abas(self):
        self.roda('buscas')
        self.assertEqual(self.chamadas, [('buscas', (None, ['relevancia']), {})])

    def test_buscas_com_cat_e_ordens(self):
        self.roda('buscas', '--cat', 'Perfumes e Perfumaria', '--ordens', 'vendidos,avaliados,caros')
        self.assertEqual(self.chamadas, [('buscas', ('Perfumes e Perfumaria', ['vendidos', 'avaliados', 'caros']), {})])

    def test_ordens_sem_cat_e_recusado(self):
        self.assertIn('--cat', self.recusa('buscas', '--ordens', 'vendidos'))

    def test_ordem_desconhecida_e_recusada(self):
        self.assertIn('baratos', self.recusa('buscas', '--cat', 'Eletrodomésticos', '--ordens', 'baratos'))

    def test_cat_ou_ordens_fora_do_modo_buscas_e_recusado(self):
        self.recusa('whatsapp', '--cat', 'Eletrodomésticos')
        self.recusa('tudo', '--cat', 'Eletrodomésticos', '--ordens', 'caros')

    def test_modo_desconhecido_e_recusado(self):
        self.recusa('buscar')

    def test_whatsapp_e_tudo_seguem_funcionando(self):
        self.roda('whatsapp')
        self.assertEqual(self.chamadas, [('whatsapp',)])
        self.chamadas.clear()
        self.roda()  # sem argumentos = tudo
        self.assertEqual(self.chamadas, [('whatsapp',), ('buscas', (None, ['relevancia']), {})])

    def test_aba_desconhecida_sai_com_erro_2(self):
        with mock.patch.object(C, 'coletar_buscas', side_effect=C.ArgInvalido('aba desconhecida')), \
                mock.patch('sys.stderr', io.StringIO()), self.assertRaises(SystemExit) as r:
            C.main(['buscas', '--cat', 'X', '--ordens', 'caros'])
        self.assertEqual(r.exception.code, 2)


if __name__ == '__main__':
    unittest.main()
