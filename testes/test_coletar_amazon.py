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
        return [{'asin': f'B{k}{i}', 'data': {'titulo': f'{k} {i}', 'preco': 'R$ 10,00'}} for i in range(2)]

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
