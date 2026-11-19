#!/usr/bin/env python3
"""Testes do QA do `conferir` do coletar_shopee.py buscar o termo de conferência na ordem `vendidos`.

Contexto (medido em 18/11/2026 com as credenciais do dono, só leitura): na relevância (sortType 1) a busca
"perfume" devolveu só anúncios novos, todos abaixo do piso, e o `conferir` saiu com 1; em `vendidos`
(sortType 2) a mesma busca devolveu nós aproveitáveis.

Uso:  python3 testes/test_shopee_conferir_qa.py -v

Reaproveita o ambiente, os dublês de rede e o Base do test_coletar_shopee.py: nada fala com a Shopee.
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_coletar_shopee as T  # noqa: E402  (fixa o ambiente antes de importar os módulos do projeto)

C, S = T.C, T.S
ID, LINK, no, resposta = T.ID, T.LINK, T.no, T.resposta

SORT_RELEVANCIA, SORT_VENDIDOS = 1, 2
LINK_VENDIDOS = 'https://s.shopee.com.br/Vend0001'


def tearDownModule():
    T.tearDownModule()


class ApiPorOrdem(T.ApiFalsa):
    """API falsa que responde conforme o sortType do corpo: o que a Shopee faz de verdade."""
    def __init__(self, por_sort, fila_item=()):
        super().__init__()
        self.por_sort, self.fila_item = por_sort, list(fila_item)

    def __call__(self, req, timeout=None):
        corpo = json.loads(req.data)
        v = corpo['variables']
        if 'sortType' in v:
            self.fila = [self.por_sort.get(v['sortType'], resposta([]))]
        else:   # consulta por item
            self.fila = [self.fila_item.pop(0) if self.fila_item else resposta([])]
        return super().__call__(req, timeout)


def anuncios_novos():
    """O que a relevância devolveu em 18/11: nota 5/0 e 0 a 3 vendas (abaixo do piso)."""
    return resposta([no(itemId=i, ratingStar='5' if i % 2 else '0', sales=i % 4, offerLink=f'https://s.shopee.com.br/Novo{i}')
                     for i in range(1, 31)])


def produtos_vendidos():
    return resposta([no(itemId=100 + i, ratingStar='4.6', sales=3000 + i, offerLink=LINK_VENDIDOS) for i in range(5)])


class TestConferirOrdemVendidos(T.Base):
    def test_ca1_busca_do_termo_de_conferencia_vai_com_sorttype_2(self):
        api = ApiPorOrdem({SORT_VENDIDOS: produtos_vendidos()})
        self.rodar(['conferir'], api=api)
        buscas = [v for v in api.variaveis() if v.get('keyword') == C.TERMO_CONFERENCIA]
        self.assertEqual(len(buscas), 1)
        self.assertEqual(buscas[0]['sortType'], SORT_VENDIDOS)

    def test_ca1_com_por_item_a_busca_tambem_vai_com_sorttype_2(self):
        api = ApiPorOrdem({SORT_VENDIDOS: produtos_vendidos()}, [resposta([no(itemId=100, sales=3000)])])
        self.rodar(['conferir', '--por-item'], api=api)
        buscas = [v for v in api.variaveis() if v.get('keyword') == C.TERMO_CONFERENCIA]
        self.assertEqual([b['sortType'] for b in buscas], [SORT_VENDIDOS])

    def test_ca2_relevancia_so_com_anuncios_novos_nao_impede_a_conferencia(self):
        api = ApiPorOrdem({SORT_RELEVANCIA: anuncios_novos(), SORT_VENDIDOS: produtos_vendidos()})
        codigo, out, err = self.rodar(['conferir'], api=api)
        self.assertEqual(codigo, 0, err)
        self.assertIn(f'afiliado {ID}', out)
        self.assertEqual(self.conf.links, [LINK_VENDIDOS], 'o link conferido é o do produto mais vendido')

    def test_ca2_com_por_item_tambem_sai_com_0(self):
        api = ApiPorOrdem({SORT_RELEVANCIA: anuncios_novos(), SORT_VENDIDOS: produtos_vendidos()},
                          [resposta([no(itemId=100, shopId=112233, sales=3000)])])
        codigo, out, err = self.rodar(['conferir', '--por-item'], api=api)
        self.assertEqual(codigo, 0, err)
        self.assertEqual(len(api.pedidos), 2, 'busca e consulta por item')
        v_item = api.variaveis()[1]
        self.assertEqual((v_item['shopId'], v_item['itemId']), ('112233', '100'), 'consulta o 1º nó válido de vendidos')

    def test_ca3_sem_por_item_continua_com_uma_chamada_e_nao_grava(self):
        api = ApiPorOrdem({SORT_VENDIDOS: produtos_vendidos()})
        self.rodar(['conferir'], api=api)
        self.assertEqual(len(api.pedidos), 1)
        self.assertFalse(os.path.exists(S.DB))
        self.assertFalse(os.path.exists(C.FEITOS))

    def test_ca3_vendidos_tambem_vazio_continua_saindo_com_1(self):
        api = ApiPorOrdem({SORT_VENDIDOS: anuncios_novos()})
        codigo, out, _ = self.rodar(['conferir'], api=api)
        self.assertEqual(codigo, 1)
        self.assertIn('não trouxe link para conferir', out)
        self.assertEqual(self.conf.links, [])

    def test_ca3_conferencia_do_dono_continua_valendo_em_vendidos(self):
        api = ApiPorOrdem({SORT_VENDIDOS: produtos_vendidos()})
        codigo, _, err = self.rodar(['conferir'], api=api, conf=T.ConferenciaFalsa(T.DESTINO_RUIM))
        self.assertEqual(codigo, 1)
        self.assertIn('PAROU', err)


class TestBuscasOrdemPadraoVendidos(T.Base):
    """CA4: `buscas --cat ABA` sem --ordens coleta só na ordem `vendidos` (sortType 2)."""
    def termos_da_aba(self):
        return ['Perfume feminino importado', 'Body splash', 'Kit perfume']

    def test_ca4_ler_argumentos_sem_ordens_da_so_vendidos(self):
        self.assertEqual(C.ler_argumentos(['buscas', '--cat', T.CAT]).ordens, ['vendidos'])

    def test_ca4_ordens_explicitas_continuam_aceitas_na_ordem_dada(self):
        args = C.ler_argumentos(['buscas', '--cat', T.CAT, '--ordens', 'relevancia,caros'])
        self.assertEqual(args.ordens, ['relevancia', 'caros'])
        self.assertEqual(C.ler_argumentos(['buscas', '--cat', T.CAT, '--ordens', 'relevancia']).ordens, ['relevancia'])

    def test_ca4_coleta_sem_ordens_so_pede_sorttype_2_para_cada_termo(self):
        api = T.ApiFalsa(*[resposta([no(itemId=i, offerLink=f'https://s.shopee.com.br/Z{i}')]) for i in range(1, 4)])
        codigo, _, err = self.rodar(['buscas', '--cat', T.CAT], api=api)
        self.assertEqual(codigo, 0, err)
        self.assertEqual([(v['keyword'], v['sortType']) for v in api.variaveis()],
                         [(t, SORT_VENDIDOS) for t in self.termos_da_aba()])

    def test_ca4_progresso_continua_com_a_ordem_na_chave(self):
        api = T.ApiFalsa(*[resposta([no(itemId=i, offerLink=f'https://s.shopee.com.br/Z{i}')]) for i in range(1, 4)])
        self.rodar(['buscas', '--cat', T.CAT], api=api)
        self.assertEqual(self.feitos(), [f'vendidos|{t}' for t in self.termos_da_aba()])

    def test_ca4_progresso_de_relevancia_de_rodadas_antigas_nao_pula_o_termo_em_vendidos(self):
        with open(C.FEITOS, 'w', encoding='utf-8') as f:
            f.write('relevancia|Perfume feminino importado\n')
        api = T.ApiFalsa(*[resposta([no(itemId=i, offerLink=f'https://s.shopee.com.br/Z{i}')]) for i in range(1, 4)])
        self.rodar(['buscas', '--cat', T.CAT], api=api)
        self.assertEqual([v['keyword'] for v in api.variaveis()], self.termos_da_aba())

    def test_ca4_ordens_explicita_relevancia_ainda_pede_sorttype_1(self):
        api = T.ApiFalsa(*[resposta([no(itemId=i, offerLink=f'https://s.shopee.com.br/Z{i}')]) for i in range(1, 4)])
        codigo, _, err = self.rodar(['buscas', '--cat', T.CAT, '--ordens', 'relevancia'], api=api)
        self.assertEqual(codigo, 0, err)
        self.assertEqual({v['sortType'] for v in api.variaveis()}, {SORT_RELEVANCIA})
        self.assertEqual(self.feitos(), [f'relevancia|{t}' for t in self.termos_da_aba()])


if __name__ == '__main__':
    unittest.main()
