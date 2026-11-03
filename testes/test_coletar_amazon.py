#!/usr/bin/env python3
"""Testes do coletar_amazon.py (docs/produto/planos/eletronicos-e-coleta-ml.md, etapa 3).

Uso:  python3 testes/test_coletar_amazon.py -v

ACHADINHOS_DB e ACHADINHOS_FEITOS apontam para um diretório temporário antes do import (o
coletar_amazon importa o servidor, que lê a variável ao carregar). `baixar`, `parse_busca` e
`pausa` são falsos: nenhum teste acessa a Amazon, o achadinhos.db real ou o
coleta_amazon_feitos.txt real. Qualquer saída acidental para a rede bate num proxy morto.
Só biblioteca padrão (o coletar_amazon exige beautifulsoup4 instalado).
"""
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


if __name__ == '__main__':
    unittest.main()
