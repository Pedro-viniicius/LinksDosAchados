#!/usr/bin/env python3
"""Testes do QA da atualização de preço da Shopee item a item
(docs/produto/planos/atualizar-precos-shopee-por-item.md, etapas 1 a 3: CA1 a CA5).

Uso:  python3 testes/test_shopee_por_item_qa.py -v

Complementa test_coletar_shopee.py e test_atualizar_precos.py (que este arquivo importa para reaproveitar o
banco temporário, os openers que levantam erro e as constantes). Nunca acessa a API, a Shopee, o achadinhos.db real
nem os arquivos de progresso reais: o ambiente é o do test_atualizar_precos (proxies em 127.0.0.1:9, banco e progresso
em pasta temporária) e as credenciais são marcadores.
"""
import contextlib
import inspect
import io
import json
import os
import re
import shutil
import subprocess
import sys
import unittest
import urllib.error
from datetime import datetime, timedelta
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_atualizar_precos as T  # noqa: E402  (fixa o ambiente antes de importar os módulos do projeto)

A, CS, S, C = T.A, T.CS, T.S, T.C

def ids_do_corpo(corpo):
    """(shopId, itemId) das variáveis da consulta por item. Exige texto só de dígitos (Int64: número JSON dá 10010)."""
    v = corpo['variables']
    if not all(isinstance(v.get(k), str) and re.fullmatch(r'[0-9]+', v[k], re.A) for k in ('shopId', 'itemId')):
        return None
    return int(v['shopId']), int(v['itemId'])

RAIZ = T.RAIZ
CAT, SECRET, APP_ID, LINK_A, LINK_B = T.CAT, T.SECRET, T.APP_ID, T.LINK_A, T.LINK_B
ENV = T.ENV_SHOPEE
no = T.no
VOLATEIS = {'preco', 'preco_antigo', 'desconto', 'preco_em', 'atualizado_em'}


def tearDownModule():
    shutil.rmtree(T.TMP, ignore_errors=True)


def resposta(nos):
    return {'data': {'productOfferV2': {'nodes': nos}}}


def sem_volateis(linha):
    return {k: v for k, v in linha.items() if k not in VOLATEIS}


class BaseItem(T.Base):
    """Banco temporário com itens da Shopee e `CS.buscar_item` falso (respostas por id), como no TestShopee do dev."""
    IDS = ('112233.1001', '112233.1002', '112233.1003', '112233.1004', '112233.1005')

    def setUp(self):
        super().setUp()
        self.chamadas, self.efeitos, self.respostas, self.destinos = [], {}, {}, []
        self.destino = T.DESTINO_BOM

        def buscar_item(cred, shop, item):
            iid = f'{shop}.{item}'
            self.chamadas.append(iid)
            self.assertEqual(cred[1].valor(), SECRET)
            if iid in self.efeitos:
                self.efeitos[iid]()
            r = self.respostas.get(iid, [])
            if isinstance(r, BaseException):
                raise r
            return r

        def destino(link):
            self.destinos.append(link)
            if isinstance(self.destino, BaseException):
                raise self.destino
            return self.destino
        for nome, novo in (('buscar_item', buscar_item), ('destino', destino),
                           ('buscar', mock.Mock(side_effect=AssertionError('a busca por termo saiu do atualizar')))):
            p = mock.patch.object(CS, nome, novo)
            p.start()
            self.addCleanup(p.stop)

    def com_itens(self, *ids, **k):
        for iid in ids:
            self.inserir('shopee', iid, 'Perfume Floral', **k)
        for iid in ids:   # a resposta padrão de cada um é o nó dele
            shop, item = iid.split('.')
            self.respostas.setdefault(iid, [no(int(item), shopId=int(shop))])

    def limpar(self):
        con = S.conectar()
        con.execute('DELETE FROM items')
        con.commit()
        con.close()
        for p in (A.FEITOS,):
            if os.path.exists(p):
                os.remove(p)
        self.chamadas.clear()
        self.destinos.clear()

    def shopee(self, *extra, env=ENV):
        return self.rodar(['shopee', '--cat', CAT, *extra], env)


# ---------- ordem: do mais velho ao mais novo (CA3) ----------
class TestOrdem(BaseItem):
    def test_nulo_vazio_malformado_e_hora_24_vem_antes_do_mais_antigo_valido(self):
        idades = {'1.1': '2026-01-01T00:00:00',          # o mais antigo válido
                  '1.2': None, '1.3': '', '1.4': 'ontem', '1.5': '2026-11-08T24:00:00',
                  '1.6': '2026-02-30T00:00:00', '1.7': '2026-03-01T00:00:00+00:00', '1.8': '2026-06-01 10:00:00',
                  '1.9': '2026-03-01T00:00:00'}
        self.com_itens(*idades)
        con = S.conectar()
        con.executemany('UPDATE items SET preco_em=? WHERE item_id=?', [(v, k) for k, v in idades.items()])
        con.commit()
        con.close()
        self.assertEqual(self.shopee()[0], 0)
        invalidos, validos = self.chamadas[:7], self.chamadas[7:]
        self.assertEqual(sorted(invalidos), ['1.2', '1.3', '1.4', '1.5', '1.6', '1.7', '1.8'])
        self.assertEqual(validos, ['1.1', '1.9'])

    def test_ordem_e_deterministica_com_o_mesmo_preco_em(self):
        ids = ('1.10', '1.9', '1.100', '1.2')
        self.com_itens(*ids)
        self.assertEqual(self.shopee()[0], 0)
        primeira = list(self.chamadas)
        self.assertEqual(sorted(primeira), sorted(ids))
        self.limpar()
        self.com_itens(*reversed(ids))   # inserção em outra ordem: a ordem de consulta é a mesma
        self.assertEqual(self.shopee()[0], 0)
        self.assertEqual(self.chamadas, primeira)

    def test_item_do_futuro_alem_da_folga_nao_fura_a_fila_nem_some(self):
        """Documenta o que acontece com preco_em à frente do relógio: o item é selecionado e fica por último."""
        amanha = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%dT10:00:00')
        self.com_itens('1.1', '1.2', '1.3')
        con = S.conectar()
        con.execute('UPDATE items SET preco_em=? WHERE item_id=?', (amanha, '1.1'))
        con.commit()
        con.close()
        self.assertEqual(self.shopee()[0], 0)
        self.assertEqual(sorted(self.chamadas), ['1.1', '1.2', '1.3'])


# ---------- retomada e virada do dia (CA3) ----------
class TestRetomada(BaseItem):
    def rot(self, iid, dia=None):
        return f'shopee|{dia or A.hoje()}|item|{iid}'

    def test_rotulos_de_outra_loja_de_outro_dia_e_de_outro_tipo_nao_pulam_o_item(self):
        self.com_itens(*self.IDS)
        ontem = (datetime.now() - timedelta(days=1)).date().isoformat()
        with open(A.FEITOS, 'w', encoding='utf-8') as f:
            f.write('\n'.join([self.rot(self.IDS[0], ontem),                          # ontem
                               f'ml|{A.hoje()}|item|{self.IDS[1]}',                   # outra loja
                               f'amazon|{A.hoje()}|item|{self.IDS[2]}',
                               f'shopee|{A.hoje()}|produto|{self.IDS[3]}',            # outro tipo de rótulo
                               f'shopee|{A.hoje()}|vendidos|{self.IDS[4]}',
                               f'shopee|{A.hoje()}|item|{self.IDS[4]} ',              # id com espaço no fim
                               '']))
        self.assertEqual(self.shopee()[0], 0)
        self.assertEqual(sorted(self.chamadas), sorted(self.IDS))

    def test_prefixo_de_id_nao_pula_outro_id(self):
        self.com_itens('1.10', '1.100')
        with open(A.FEITOS, 'w', encoding='utf-8') as f:
            f.write(self.rot('1.1') + '\n')
        self.assertEqual(self.shopee()[0], 0)
        self.assertEqual(sorted(self.chamadas), ['1.10', '1.100'])

    def test_retomada_no_mesmo_dia_completa_a_aba_sem_repetir_chamada(self):
        self.com_itens(*self.IDS)
        self.respostas[self.IDS[0]] = [no(1001, ratingStar='4.0')]   # marcado, não gravado
        self.assertEqual(self.shopee('--max-chamadas', '2')[0], 3)
        self.assertEqual(self.shopee('--max-chamadas', '2')[0], 3)
        self.assertEqual(self.shopee('--max-chamadas', '2')[0], 0)
        self.assertEqual(self.chamadas, list(self.IDS), 'cada item é consultado uma vez, 2 + 2 + 1')

    def test_virada_do_dia_consulta_de_novo_ate_os_itens_ja_marcados(self):
        self.com_itens(*self.IDS)
        self.respostas[self.IDS[0]] = [no(1001, ratingStar='4.0')]
        self.assertEqual(self.shopee('--max-chamadas', '2')[0], 3)
        amanha = (datetime.now() + timedelta(days=1)).date().isoformat()
        self.chamadas.clear()
        with mock.patch.object(A, 'hoje', return_value=amanha):
            codigo, out, _ = self.shopee()
        self.assertEqual(codigo, 0)
        # os dois marcados ontem voltam; o que foi gravado no dia 1 também (o "hoje" agora é o dia 2)
        self.assertEqual(sorted(self.chamadas), sorted(self.IDS))
        self.assertIn('(0 já confirmados hoje ficaram de fora)', out)
        with open(A.FEITOS, encoding='utf-8') as f:
            linhas = f.read().splitlines()
        self.assertEqual(sum(1 for l in linhas if l.startswith(f'shopee|{amanha}|item|')), 5)

    def test_rodada_que_atravessa_a_meia_noite_rotula_pelo_dia_do_inicio(self):
        """O dia é fixado no início da rodada: nenhum rótulo sai com o dia seguinte no meio dela."""
        self.com_itens(*self.IDS[:3])
        inicio = A.hoje()
        efeito = {'n': 0}

        def vira():   # depois do 1º item o relógio do projeto passa a dizer "amanhã"
            efeito['n'] += 1
            if efeito['n'] == 2:
                A.hoje = lambda: '2999-01-01'
        self.efeitos[self.IDS[1]] = vira
        efeito['n'] = 1
        original = A.hoje
        try:
            self.assertEqual(self.shopee()[0], 0)
        finally:
            A.hoje = original
        with open(A.FEITOS, encoding='utf-8') as f:
            linhas = f.read().splitlines()
        self.assertEqual(len(linhas), 3)
        self.assertTrue(all(l.startswith(f'shopee|{inicio}|item|') for l in linhas), linhas)


# ---------- teto exato e cota (CA3) ----------
class TestTeto(BaseItem):
    def test_teto_igual_ao_numero_de_itens_termina_sem_bloqueio(self):
        self.com_itens(*self.IDS)
        codigo, out, err = self.shopee('--max-chamadas', '5')
        self.assertEqual((codigo, len(self.chamadas)), (0, 5), err)
        self.assertNotIn('parou no teto', out)

    def test_teto_uma_abaixo_para_com_3_e_deixa_o_ultimo_nao_visto(self):
        self.com_itens(*self.IDS)
        codigo, out, err = self.shopee('--max-chamadas', '4')
        self.assertEqual((codigo, len(self.chamadas)), (3, 4))
        self.assertIn('--max-chamadas', err)
        self.assertIn('1 não vistos', out)

    def test_teto_de_um_com_um_item_nao_bloqueia(self):
        self.com_itens(self.IDS[0])
        self.assertEqual(self.shopee('--max-chamadas', '1')[0], 0)

    def test_itens_ja_marcados_nao_gastam_teto(self):
        self.com_itens(*self.IDS)
        with open(A.FEITOS, 'w', encoding='utf-8') as f:
            f.write(''.join(f'shopee|{A.hoje()}|item|{i}\n' for i in self.IDS[:3]))
        self.assertEqual(self.shopee('--max-chamadas', '2')[0], 0)
        self.assertEqual(sorted(self.chamadas), sorted(self.IDS[3:]), 'só os dois que faltavam são consultados')

    def test_resposta_vazia_e_divergente_gastam_teto_e_o_teto_vence_a_parada_do_filtro(self):
        self.com_itens(*self.IDS)
        for iid in self.IDS:
            self.respostas[iid] = [no(9999)]   # 5 divergentes seriam a parada do filtro
        codigo, _, err = self.shopee('--max-chamadas', '3')
        self.assertEqual((codigo, len(self.chamadas)), (3, 3))
        self.assertIn('teto', err)

    def test_pausa_entre_chamadas_inclusive_apos_item_pulado_e_nunca_antes_da_primeira(self):
        self.com_itens(*self.IDS)
        with open(A.FEITOS, 'w', encoding='utf-8') as f:
            f.write(f'shopee|{A.hoje()}|item|{self.IDS[0]}\n')   # o primeiro da fila já foi feito
        self.assertEqual(self.shopee()[0], 0)
        self.assertEqual(len(self.chamadas), 4)
        self.assertEqual(self.pausas, [('shopee', 1, 3)] * 3)


class TestPausaReal(unittest.TestCase):
    def test_pausa_de_verdade_dorme_um_valor_sorteado_entre_1_e_3_segundos(self):
        with mock.patch('random.uniform', return_value=2.5) as sorteio, mock.patch('time.sleep') as dormir:
            CS.pausa()
        sorteio.assert_called_once_with(1, 3)
        dormir.assert_called_once_with(2.5)


# ---------- divergentes, vazios e casados (CA1) ----------
class TestDivergentes(BaseItem):
    def test_vazios_nao_contam_como_divergentes_mas_o_quinto_divergente_para(self):
        ids = tuple(f'1.{n}' for n in range(1, 11))
        self.com_itens(*ids)
        # mais velho primeiro = ordem de inserção (mesmo preco_em, desempate por id como texto)
        ordem = sorted(ids)
        padrao = ['vazio', 'div', 'vazio', 'div', 'div', 'vazio', 'div', 'div']
        for iid, tipo in zip(ordem, padrao):
            self.respostas[iid] = [] if tipo == 'vazio' else [no(9999)]
        antes = self.todas()
        codigo, out, err = self.shopee()
        self.assertEqual(codigo, 1)
        self.assertIn('a API não filtrou pelo item', err)
        self.assertEqual(self.chamadas, ordem[:8], 'para no 5º divergente, sem gastar o resto da cota')
        self.assertEqual(self.todas(), antes, 'nada gravado')
        # rodada 1 de correção (R1/Q3): vazios e divergentes ficam marcados como "tentado", inclusive o 5º divergente
        self.assertEqual(self.progresso(), [f'shopee|{A.hoje()}|tentado|{i}' for i in ordem[:8]])

    def test_quatro_divergentes_e_vazios_a_vontade_nao_param(self):
        ids = tuple(f'1.{n}' for n in range(1, 9))
        self.com_itens(*ids)
        for i, iid in enumerate(sorted(ids)):
            self.respostas[iid] = [no(9999)] if i < 4 else []
        codigo, out, _ = self.shopee()
        self.assertEqual(codigo, 0)
        self.assertIn('4 indisponíveis', out)
        self.assertIn('4 não vistos', out)

    def test_casado_usado_ou_fora_do_piso_ja_conta_como_filtro_funcionando(self):
        ids = tuple(f'1.{n}' for n in range(1, 9))
        self.com_itens(*ids)
        ordem = sorted(ids)
        self.respostas[ordem[0]] = [no(1, shopId=1, productName='Perfume Usado Floral')]
        for iid in ordem[1:]:
            self.respostas[iid] = [no(9999)]
        codigo, out, err = self.shopee()
        self.assertEqual(codigo, 0, err)
        self.assertEqual(len(self.chamadas), 8)
        self.assertIn('1 usados', out)

    def test_divergente_com_o_mesmo_item_em_outra_loja_nao_grava_nada(self):
        self.com_itens('1.7')
        self.respostas['1.7'] = [no(7, shopId=2), no(7, shopId=3)]
        antes = self.todas()
        self.assertEqual(self.shopee()[0], 0)
        self.assertEqual(self.todas(), antes)

    def test_no_certo_atras_de_varios_errados_e_gravado_uma_vez(self):
        self.com_itens('1.7')
        self.respostas['1.7'] = [no(8, shopId=1, priceMin='1.00'), no(7, shopId=2, priceMin='2.00'),
                                 no(7, shopId=1, priceMin='33.00'), no(7, shopId=1, priceMin='44.00')]
        self.assertEqual(self.shopee()[0], 0)
        self.assertEqual(self.linha('1.7')['preco'], 'R$ 33,00')


# ---------- bordas dos dados do banco e do risco de resposta toda vazia ----------
class TestBordasDoBanco(BaseItem):
    def test_item_com_busca_vazia_nula_ou_gigante_ainda_atualiza_o_preco(self):
        for busca in ('', None, 'x' * 200):
            with self.subTest(busca=busca):
                self.limpar()
                self.com_itens('112233.1001')
                con = S.conectar()
                con.execute("UPDATE items SET busca=? WHERE item_id='112233.1001'", (busca,))
                con.commit()
                con.close()
                antes = self.linha('112233.1001')
                self.assertEqual(self.shopee()[0], 0)
                depois = self.linha('112233.1001')
                self.assertEqual(depois['preco'], 'R$ 1.234,50')
                self.assertEqual(depois['busca'], antes['busca'])

    def test_item_sem_titulo_no_banco_nao_quebra_e_fica_como_estava(self):
        self.com_itens('112233.1001')
        con = S.conectar()
        con.execute("UPDATE items SET titulo='', tem_dados=0 WHERE item_id='112233.1001'")
        con.commit()
        con.close()
        antes = self.linha('112233.1001')
        codigo, out, err = self.shopee()
        self.assertEqual(codigo, 0, err)
        self.assertEqual(self.linha('112233.1001'), antes)

    def test_aba_sem_nenhum_item_da_shopee_sai_com_0_sem_chamar_a_api(self):
        self.inserir('amazon', 'B0AAAAAAA1', 'Perfume Floral')
        codigo, out, _ = self.shopee()
        self.assertEqual((codigo, self.chamadas, self.destinos), (0, [], []))
        self.assertIn('0 selecionados', out)

    def test_todos_ja_confirmados_hoje_nao_chama_a_api(self):
        self.com_itens(*self.IDS, preco_em=datetime.now().strftime('%Y-%m-%dT%H:%M:%S'))
        codigo, out, _ = self.shopee()
        self.assertEqual((codigo, self.chamadas), (0, []))
        self.assertIn('0 selecionados (5 já confirmados hoje', out)

    def test_resposta_toda_vazia_para_no_limite_sem_gastar_a_cota_inteira(self):
        """Q2 (corrigido na rodada 1): sem nenhum nó casado, SEM_PRODUTO_PARA_PARAR respostas vazias param a rodada
        com "não filtrou"; os consultados ficam marcados como tentados e o resto da cota fica."""
        ids = tuple(f'1.{n}' for n in range(1, 31))
        self.com_itens(*ids)
        for iid in ids:
            self.respostas[iid] = []
        antes = self.todas()
        codigo, out, err = self.shopee()
        self.assertEqual((codigo, len(self.chamadas)), (1, A.SEM_PRODUTO_PARA_PARAR))
        self.assertIn('a API não filtrou pelo item', err)
        self.assertEqual(self.todas(), antes)
        self.assertEqual(len(self.progresso()), A.SEM_PRODUTO_PARA_PARAR)
        self.assertTrue(all('|tentado|' in l for l in self.progresso()))


class TestItemQueFazAApiErrar(BaseItem):
    def test_item_que_faz_a_api_errar_nao_trava_a_fila_nas_rodadas_seguintes(self):
        """Q3 (corrigido na rodada 1): o erro geral (ErroApi 11001 ou RespostaInvalida) de UM item ainda para a rodada
        com 1, mas o item é marcado como tentado antes: a rodada seguinte do mesmo dia passa por ele e, em outro dia,
        ele vai para o fim da fila."""
        veneno = self.IDS[0]
        amanha = (datetime.now() + timedelta(days=1)).date().isoformat()
        for erro in (CS.ErroApi(11001, 200), CS.RespostaInvalida()):
            with self.subTest(type(erro).__name__):
                self.limpar()
                self.com_itens(*self.IDS)
                self.respostas[veneno] = erro
                self.assertEqual(self.shopee()[0], 1)
                self.assertEqual(self.chamadas, [veneno])
                self.assertEqual(self.progresso(), [f'shopee|{A.hoje()}|tentado|{veneno}'])
                self.chamadas.clear()
                self.assertEqual(self.shopee()[0], 0)
                self.assertEqual(self.chamadas, list(self.IDS[1:]), 'a rodada passa do item que a API recusa')
                self.chamadas.clear()
                with mock.patch.object(A, 'hoje', return_value=amanha):
                    self.assertEqual(self.shopee()[0], 1)
                self.assertEqual(self.chamadas, list(self.IDS[1:]) + [veneno], 'no outro dia, ele é o último')

    def test_erro_com_cara_de_ser_do_item_marca_e_segue(self):
        for erro in (CS.SemProduto(), CS.ErroApi(10000, 200)):
            with self.subTest(type(erro).__name__):
                self.limpar()
                self.com_itens(*self.IDS)
                self.respostas[self.IDS[0]] = erro
                codigo, out, err = self.shopee()
                self.assertEqual(codigo, 0, err)
                self.assertEqual(self.chamadas, list(self.IDS))
                self.assertIn('4 atualizados', out)


# ---------- rodada 2: tentados (Q2, Q3, R1, S2), G1 com preço, backup do README (Q4, R2) ----------
def minuto(n):
    """preco_em velho e crescente: n=0 é o mais antigo."""
    return f'2026-01-01T{n // 60:02d}:{n % 60:02d}:00'


class BaseR2(BaseItem):
    @contextlib.contextmanager
    def dia(self, d):
        """Relógio coerente de um dia: o dia da rodada (A.hoje) e o carimbo do preco_em (S.agora)."""
        with mock.patch.object(A, 'hoje', return_value=d), mock.patch.object(S, 'agora', return_value=f'{d}T10:00:00'):
            yield

    def add(self, iid, n=None, resp='proprio', **k):
        """Insere o item com preço velho de ordem `n` (None = preco_em nulo) e fixa a resposta do falso."""
        self.inserir('shopee', iid, 'Perfume Floral', preco_em=None if n is None else minuto(n), **k)
        shop, item = iid.split('.')
        if resp == 'proprio':
            self.respostas[iid] = [no(int(item), shopId=int(shop))]
        elif resp == 'outro':
            self.respostas[iid] = [no(9999, shopId=int(shop))]
        else:
            self.respostas[iid] = resp

    def amanha(self, dias=1):
        return (datetime.now() + timedelta(days=dias)).date().isoformat()

    def tentados_no_arquivo(self):
        return [l.split('|')[3] for l in self.progresso() if l.split('|')[2:3] == ['tentado'] and l.count('|') == 3]

    def itens_do_arquivo(self):
        return [l.split('|')[3] for l in self.progresso() if l.split('|')[2:3] == ['item'] and l.count('|') == 3]


class TestTentadosTresRodadas(BaseR2):
    def test_divergentes_na_frente_da_fila_a_1a_rodada_para_a_2a_do_dia_segue_e_a_3a_poe_no_fim(self):
        """Pior caso do R1: os 5 divergentes têm o preço mais velho (vêm antes dos 2 bons). Rodada 1 para com "não
        filtrou" (sem gravar nada); a 2ª, no mesmo dia, pula os 5 marcados e atualiza os bons; a 3ª, no dia seguinte,
        consulta os bons antes dos 5 e não para. O arquivo de progresso nunca é apagado."""
        ruins = [f'7.{n}' for n in range(2001, 2006)]
        bons = ['7.1001', '7.1002']
        for i, iid in enumerate(ruins):
            self.add(iid, i, 'outro')
        for i, iid in enumerate(bons):
            self.add(iid, 10 + i)
        antes = self.todas()
        codigo, out, err = self.shopee()
        self.assertEqual(codigo, 1)
        self.assertIn('5 respostas seguidas só com outros produtos', err)
        self.assertEqual(self.chamadas, ruins)
        self.assertEqual(self.todas(), antes, 'nada gravado na rodada que parou')
        self.assertEqual(self.tentados_no_arquivo(), ruins)
        self.chamadas.clear()
        codigo, out, err = self.shopee()   # mesmo dia
        self.assertEqual((codigo, self.chamadas), (0, bons), err)
        self.assertIn('2 atualizados', out)
        self.assertEqual(self.linha(bons[0])['preco'], 'R$ 1.234,50')
        self.assertEqual(self.linha(ruins[0]), antes[ruins[0]])
        self.chamadas.clear()
        with mock.patch.object(A, 'hoje', return_value=self.amanha()):   # dia seguinte
            codigo, out, err = self.shopee()
        self.assertEqual(codigo, 0, err)
        self.assertEqual(self.chamadas, bons + ruins, 'os bons (preço de ontem) primeiro, os tentados no fim')
        self.assertNotIn('não filtrou', err)
        # o arquivo só cresceu: as linhas dos dias anteriores continuam lá
        self.assertEqual(self.tentados_no_arquivo(), ruins + ruins)

    def test_erro_de_item_persistente_em_tres_rodadas_nunca_trava_e_vai_para_o_fim(self):
        veneno, outros = '7.1001', ['7.1002', '7.1003', '7.1004', '7.1005']
        self.add(veneno, 0, CS.ErroApi(10000, 200))
        for i, iid in enumerate(outros):
            self.add(iid, 1 + i)
        codigo, out, err = self.shopee()
        self.assertEqual(codigo, 0, err)
        self.assertEqual(self.chamadas, [veneno] + outros)
        self.assertIn('4 atualizados', out)
        self.assertIn('1 itens: a API recusou a consulta só daquele item', out)
        self.assertEqual(self.tentados_no_arquivo(), [veneno])
        self.chamadas.clear()
        self.assertEqual(self.shopee()[0], 0)
        self.assertEqual(self.chamadas, [], 'mesmo dia: nada a fazer')
        with mock.patch.object(A, 'hoje', return_value=self.amanha()):
            codigo, out, err = self.shopee()
        self.assertEqual(codigo, 0, err)
        self.assertEqual(self.chamadas[-1], veneno)
        self.assertEqual(sorted(self.chamadas[:-1]), sorted(outros))
        self.assertEqual(self.tentados_no_arquivo(), [veneno, veneno])

    def test_erro_geral_persistente_num_item_para_com_1_em_cada_dia_depois_de_atualizar_os_outros(self):
        veneno, outros = '7.1001', ['7.1002', '7.1003', '7.1004']
        self.add(veneno, 0, CS.ErroApi(10010, 200))
        for i, iid in enumerate(outros):
            self.add(iid, 1 + i)
        self.assertEqual(self.shopee()[0], 1)           # dia 1: para no veneno
        self.assertEqual(self.chamadas, [veneno])
        self.chamadas.clear()
        self.assertEqual(self.shopee()[0], 0)           # mesmo dia: passa por ele e atualiza os outros
        self.assertEqual(self.chamadas, outros)
        self.chamadas.clear()
        with mock.patch.object(A, 'hoje', return_value=self.amanha()):
            codigo, _, err = self.shopee()               # dia 2: ele é o último; ainda sai 1, mas depois dos outros
        self.assertEqual(codigo, 1)
        self.assertEqual(self.chamadas, outros + [veneno])
        self.assertIn('recusou', err)
        self.assertNotIn(SECRET, err)

    def test_queda_geral_da_api_100_por_cento_de_erro_de_item_para_a_cada_20_e_a_cota_do_dia_nao_queima(self):
        """10000 em todos os itens (queda da API): cada rodada gasta no máximo 20 chamadas e sai com 1; rodar de novo no
        mesmo dia segue pelos próximos 20 (os 20 marcados não repetem)."""
        ids = [f'7.{n}' for n in range(1001, 1046)]
        for i, iid in enumerate(ids):
            self.add(iid, i, CS.ErroApi(10000, 200))
        vistos = []
        for esperado in (20, 20, 5):
            self.chamadas.clear()
            codigo, out, err = self.shopee()
            self.assertEqual(len(self.chamadas), esperado)
            self.assertEqual(codigo, 1 if esperado == 20 else 0)
            if esperado == 20:
                self.assertIn('20 respostas seguidas sem o produto pedido', err)
            vistos += self.chamadas
        self.assertEqual(vistos, ids, 'cada item foi consultado uma vez no dia, em ordem')
        self.assertEqual(self.tentados_no_arquivo(), ids)


class TestParadaDoFiltro(BaseR2):
    def fila_de(self, n, resp):
        ids = [f'7.{3000 + i}' for i in range(n)]
        for i, iid in enumerate(ids):
            self.add(iid, i, resp(i) if callable(resp) else resp)
        return ids

    def test_so_vazios_19_nao_param_e_20_param(self):
        self.fila_de(19, [])
        codigo, out, err = self.shopee()
        self.assertEqual((codigo, len(self.chamadas)), (0, 19), err)
        self.assertIn('19 indisponíveis', out)
        self.limpar()
        self.fila_de(20, [])
        codigo, out, err = self.shopee()
        self.assertEqual((codigo, len(self.chamadas)), (1, 20))
        self.assertIn('(20 respostas seguidas sem o produto pedido (vazias, com outros produtos ou com erro do item).)', err)
        self.assertEqual(len(self.tentados_no_arquivo()), 20)

    def test_4_de_outros_e_16_vazios_dao_o_motivo_nenhum_e_5_de_outros_o_motivo_outros(self):
        self.fila_de(30, lambda i: [no(9999)] if i in (0, 1, 2, 3) else [])
        codigo, _, err = self.shopee()
        self.assertEqual((codigo, len(self.chamadas)), (1, 20))
        self.assertIn('20 respostas seguidas sem o produto pedido', err)
        self.assertNotIn('5 respostas seguidas só com outros', err)
        self.limpar()
        self.fila_de(30, lambda i: [no(9999)] if i in (0, 1, 2, 3, 4) else [])
        codigo, _, err = self.shopee()
        self.assertEqual((codigo, len(self.chamadas)), (1, 5))
        self.assertIn('5 respostas seguidas só com outros produtos', err)

    def test_um_casado_em_qualquer_ponto_antes_desliga_a_parada_ate_o_fim_da_rodada(self):
        self.fila_de(41, lambda i: 'proprio' if i == 18 else [])
        for iid in self.respostas:   # os 'proprio' viram o nó certo
            if self.respostas[iid] == 'proprio':
                shop, item = iid.split('.')
                self.respostas[iid] = [no(int(item), shopId=int(shop))]
        codigo, out, err = self.shopee()
        self.assertEqual((codigo, len(self.chamadas)), (0, 41), err)
        self.assertIn('1 atualizados', out)
        self.assertIn('40 indisponíveis', out)

    def test_usado_e_fora_do_piso_contam_como_casados_para_a_parada(self):
        for nome, extra in (('usado', {'productName': 'Perfume Usado Floral'}), ('fora do piso', {'ratingStar': '3.9'})):
            with self.subTest(nome):
                self.limpar()
                self.fila_de(25, lambda i: [no(3000, shopId=7, **extra)] if i == 0 else [])
                codigo, out, err = self.shopee()
                self.assertEqual((codigo, len(self.chamadas)), (0, 25), err)

    def test_erro_do_item_conta_como_resposta_sem_produto_mas_nao_o_erro_geral_que_ja_sai_com_1(self):
        self.fila_de(25, lambda i: CS.ErroApi(10000, 200))
        codigo, _, err = self.shopee()
        self.assertEqual((codigo, len(self.chamadas)), (1, 20))
        self.assertIn('20 respostas seguidas sem o produto pedido', err)

    def test_so_o_motivo_e_o_texto_fixo_sem_id_titulo_link_nem_secret(self):
        self.fila_de(6, [no(9999, productName='TITULO-SECRETO-XYZ', offerLink='https://s.shopee.com.br/LINKXYZ')])
        codigo, out, err = self.shopee()
        self.assertEqual(codigo, 1)
        for proibido in ('TITULO-SECRETO-XYZ', 'LINKXYZ', SECRET, 'Traceback'):
            self.assertNotIn(proibido, out + err)


class TestTentadosENaFila(BaseR2):
    def test_teto_vale_com_tentados_no_fim_eles_so_sao_consultados_depois_dos_outros(self):
        ontem = self.amanha(-1)
        tentados = [f'7.{n}' for n in range(1, 5)]
        bons = [f'7.{n}' for n in range(101, 104)]
        for i, iid in enumerate(tentados):    # os mais velhos, mas tentados ontem: vão para o fim
            self.add(iid, i, [])
        for i, iid in enumerate(bons):
            self.add(iid, 10 + i)
        with open(A.FEITOS, 'w', encoding='utf-8') as f:
            f.write(''.join(f'shopee|{ontem}|tentado|{i}\n' for i in tentados))
        codigo, out, err = self.shopee('--max-chamadas', '3')
        self.assertEqual((codigo, self.chamadas), (3, bons), err)
        self.assertIn('--max-chamadas', err)
        self.assertIn('3 atualizados', out)
        self.chamadas.clear()
        codigo, out, err = self.shopee('--max-chamadas', '2')
        self.assertEqual((codigo, self.chamadas), (3, tentados[:2]))
        self.chamadas.clear()
        codigo, out, err = self.shopee('--max-chamadas', '2')
        self.assertEqual((codigo, self.chamadas), (0, tentados[2:]), err)
        self.chamadas.clear()
        self.assertEqual(self.shopee()[0], 0)
        self.assertEqual(self.chamadas, [], 'tudo marcado hoje')

    def test_tentados_antigos_nao_contam_para_a_parada_mesmo_passando_de_20_sem_nenhum_casado(self):
        ontem = self.amanha(-1)
        ids = [f'7.{n}' for n in range(1, 31)]
        for i, iid in enumerate(ids):
            self.add(iid, i, [])
        with open(A.FEITOS, 'w', encoding='utf-8') as f:
            f.write(''.join(f'shopee|{ontem}|tentado|{i}\n' for i in ids))
        codigo, out, err = self.shopee()
        self.assertEqual((codigo, len(self.chamadas)), (0, 30), err)
        self.assertIn('30 indisponíveis', out)
        # e um item novo vazio no meio deles conta 1, não 20
        self.limpar()
        for i, iid in enumerate(ids):
            self.add(iid, i, [])
        with open(A.FEITOS, 'w', encoding='utf-8') as f:
            f.write(''.join(f'shopee|{ontem}|tentado|{i}\n' for i in ids[1:]))
        self.assertEqual(self.shopee()[0], 0)
        self.assertEqual(self.chamadas[0], ids[0], 'o único sem tentativa vem primeiro')
        self.assertEqual(len(self.chamadas), 30)

    def test_os_ids_de_um_tentado_nao_se_misturam_com_prefixo_nem_com_outra_loja(self):
        self.add('7.10', 0)
        self.add('7.1', 1)
        with open(A.FEITOS, 'w', encoding='utf-8') as f:
            f.write(f'ml|{self.amanha(-1)}|tentado|7.1\nshopee|{self.amanha(-1)}|tentado|7.100\n'
                    f'amazon|{self.amanha(-1)}|tentado|7.10\n')
        self.assertEqual(self.shopee()[0], 0)
        self.assertEqual(self.chamadas, ['7.10', '7.1'], 'nenhum dos dois é tentado: ordem do preco_em')

    def test_tentado_so_do_dia_do_preco_ou_depois_conta_e_o_de_antes_do_preco_nao(self):
        a, b = '7.1', '7.2'
        self.add(a, 5)      # preco_em 2026-01-01
        self.add(b, 6)
        self.add('7.3', 7)
        for iid in (a, b, '7.3'):
            self.respostas[iid] = []
        with open(A.FEITOS, 'w', encoding='utf-8') as f:   # a: tentado ANTES do preço; b: no mesmo dia do preço
            f.write(f'shopee|2025-12-31|tentado|{a}\nshopee|2026-01-01|tentado|{b}\n')
        self.assertEqual(self.shopee()[0], 0)
        self.assertEqual(self.chamadas, [a, '7.3', b], 'b (tentado desde o preço) vai para o fim; a volta à fila normal')

    def test_virada_do_dia_com_tentados_antigos_e_preco_em_nulo_com_linhas_lixo_no_arquivo(self):
        dia1, dia2 = '2031-03-10', '2031-03-12'
        n1, n2, n3 = '5.10', '5.20', '5.30'
        self.add(n1, None, [])    # com tentado antigo: vai para o fim
        self.add(n2, None)
        self.add(n3, None)        # só linhas lixo: continua na fila normal
        lixo = ['', 'shopee', 'tentado|5.30', 'shopee|2031-03-09|tentado', 'shopee|2031-03-09|tentado|5.30|x',
                'shopee|٢٠٣١-٠٣-٠٩|tentado|5.30', 'shopee|2031-03-09|TENTADO|5.30', 'shopee|2031-3-9|tentado|5.30',
                f'shopee|{dia1}|tentado| 5.30', 'shopee|2031-03-09|tentado|' + '9' * 5000]
        with open(A.FEITOS, 'w', encoding='utf-8') as f:
            f.write('\n'.join(['shopee|2031-03-05|tentado|5.10', 'shopee|2031-03-09|tentado|5.10', *lixo]) + '\n')
        with mock.patch.object(A, 'hoje', return_value=dia1):
            codigo, out, err = self.shopee()
        self.assertEqual(codigo, 0, err)
        self.assertEqual(self.chamadas, [n2, n3, n1])
        self.assertEqual(self.tentados_no_arquivo()[-1], n1)
        self.chamadas.clear()
        with mock.patch.object(A, 'hoje', return_value=dia1):   # mesmo dia: tudo marcado
            self.assertEqual(self.shopee()[0], 0)
        self.assertEqual(self.chamadas, [])
        with mock.patch.object(A, 'hoje', return_value=dia2):   # 2 dias depois: n1 continua no fim, n2 e n3 na frente
            codigo, out, err = self.shopee()
        self.assertEqual(codigo, 0, err)
        self.assertEqual(self.chamadas, [n2, n3, n1])

    def test_vale_o_ultimo_dia_tentado_mesmo_com_linhas_fora_de_ordem_no_arquivo(self):
        """O arquivo é só de acréscimo, mas se alguém o editar à mão: vale o dia mais recente de cada item, não a última
        linha. Tentado em 03-09 e (depois, no arquivo) em 03-05, com preco_em de 03-07: o 03-09 manda, no fim da fila."""
        self.inserir('shopee', '5.10', 'Perfume Floral', preco_em='2031-03-07T08:00:00')
        self.inserir('shopee', '5.20', 'Perfume Floral', preco_em='2031-03-08T08:00:00')
        self.respostas['5.10'], self.respostas['5.20'] = [], [no(20, shopId=5)]
        with open(A.FEITOS, 'w', encoding='utf-8') as f:
            f.write('shopee|2031-03-09|tentado|5.10\nshopee|2031-03-05|tentado|5.10\n')
        with mock.patch.object(A, 'hoje', return_value='2031-03-12'):
            self.assertEqual(self.shopee()[0], 0)
        self.assertEqual(self.chamadas, ['5.20', '5.10'])

    def test_item_com_sucesso_depois_do_tentado_sai_do_fim_da_fila(self):
        """Relógio coerente (A.hoje e S.agora). D1: 7.1 vazio, vira tentado. D2: ainda tentado desde o último preço, no
        fim; desta vez a API o devolve, e o preco_em dele passa a ser de D2. D3: o tentado de D1 é anterior ao preço, e o
        item volta à ordem normal (o primeiro, pelo preco_em mais velho)."""
        d1, d2, d3 = '2031-04-01', '2031-04-02', '2031-04-03'
        self.add('7.1', 0, [])
        self.inserir('shopee', '7.2', 'Perfume Floral', preco_em='2031-04-02T11:00:00')
        self.inserir('shopee', '7.3', 'Perfume Floral', preco_em='2031-04-02T11:00:00')
        self.respostas['7.2'], self.respostas['7.3'] = [no(2, shopId=7)], [no(3, shopId=7)]
        with self.dia(d1):
            self.assertEqual(self.shopee()[0], 0)
        self.assertEqual(self.chamadas, ['7.1', '7.2', '7.3'])
        self.respostas['7.1'] = [no(1, shopId=7)]
        self.chamadas.clear()
        with self.dia(d2):
            self.assertEqual(self.shopee()[0], 0)
        self.assertEqual(self.chamadas, ['7.2', '7.3', '7.1'], 'D2: tentado desde o último preço, no fim')
        self.assertEqual(self.linha('7.1')['preco_em'], f'{d2}T10:00:00')
        self.chamadas.clear()
        with self.dia(d3):
            self.assertEqual(self.shopee()[0], 0)
        self.assertEqual(self.chamadas[0], '7.1', 'D3: o tentado é de antes do preço, fila normal')


class TestErrosDaApiPelaRequisicaoDeVerdade(BaseR2):
    """Pelo CS.buscar_item e o _pedir de verdade (só o opener é falso): o que marca e segue, o que marca e para."""

    def com_opener(self, respostas_por_item):
        self.pedidos = []

        def open_(req, timeout=None):
            shop, item = ids_do_corpo(json.loads(req.data))
            iid = f'{shop}.{item}'
            self.pedidos.append(iid)
            r = respostas_por_item.get(iid)
            if r is None:
                r = {'data': {'productOfferV2': {'nodes': [no(item, shopId=shop)]}}}
            if isinstance(r, BaseException):
                raise r
            return io.BytesIO(json.dumps(r).encode())
        return open_

    def rodar_real(self, mapa, *extra):
        with mock.patch.object(CS, 'buscar_item', T.BUSCAR_ITEM), \
                mock.patch.object(CS.OPENER_API, 'open', self.com_opener(mapa)):
            return self.shopee(*extra)

    def erro(self, codigo):
        return {'errors': [{'message': 'x', 'extensions': {'code': codigo}}]}

    def http(self, status, corpo=b'{}'):
        return urllib.error.HTTPError(CS.URL_API, status, 'x', {}, io.BytesIO(corpo))

    def test_marcam_e_seguem_produto_null_e_codigo_desconhecido_com_http_200(self):
        casos = {'productOfferV2 null': {'data': {'productOfferV2': None}},
                 'codigo 10000': self.erro(10000), 'codigo 12345': self.erro(12345), 'codigo texto "12345"': self.erro('12345')}
        for nome, resp in casos.items():
            with self.subTest(nome):
                self.limpar()
                for i, iid in enumerate(self.IDS):
                    self.add(iid, i)
                codigo, out, err = self.rodar_real({self.IDS[0]: resp})
                self.assertEqual(codigo, 0, err)
                self.assertEqual(self.pedidos, list(self.IDS))
                self.assertEqual(self.tentados_no_arquivo(), [self.IDS[0]])
                self.assertIn('4 atualizados', out)

    def test_marcam_e_param_com_1_codigo_geral_sem_codigo_http_de_erro_e_resposta_fora_do_formato(self):
        casos = {'10020': self.erro(10020), '10010': self.erro(10010), '11001': self.erro(11001), '10033': self.erro(10033),
                 'sem codigo': {'errors': [{'message': 'oops'}]}, 'codigo bool': self.erro(True),
                 'codigo zero': self.erro(0), 'codigo texto livre': self.erro('abc'),
                 'http 500 com codigo comum': self.http(500, json.dumps(self.erro(12345)).encode()),
                 'http 400': self.http(400), 'http 401': self.http(401), 'http 302': self.http(302),
                 'nodes nao e lista': {'data': {'productOfferV2': {'nodes': 'x'}}}, 'sem data': {'x': 1},
                 'lista': []}
        for nome, resp in casos.items():
            with self.subTest(nome):
                self.limpar()
                for i, iid in enumerate(self.IDS):
                    self.add(iid, i)
                codigo, out, err = self.rodar_real({self.IDS[0]: resp})
                self.assertEqual(codigo, 1, (nome, err))
                self.assertEqual(self.pedidos, [self.IDS[0]], 'para no primeiro')
                self.assertEqual(self.tentados_no_arquivo(), [self.IDS[0]], 'marcado antes de parar')
                self.assertNotIn('Traceback', err)
                self.assertNotIn(SECRET, out + err)

    def test_limite_nao_marca_e_nunca_vira_tentado(self):
        for nome, resp in (('10030 no corpo', self.erro(10030)), ('http 429', self.http(429)),
                           ('http 500 com 10030', self.http(500, json.dumps(self.erro(10030)).encode()))):
            with self.subTest(nome):
                self.limpar()
                for i, iid in enumerate(self.IDS):
                    self.add(iid, i)
                codigo, out, err = self.rodar_real({self.IDS[1]: resp})
                self.assertEqual(codigo, 3)
                self.assertEqual(self.pedidos, list(self.IDS[:2]))
                self.assertEqual(self.tentados_no_arquivo(), [])
                self.assertEqual(self.itens_do_arquivo(), [self.IDS[0]])

    def test_erro_de_item_gasta_teto(self):
        for i, iid in enumerate(self.IDS):
            self.add(iid, i, [])
        mapa = {iid: self.erro(10000) for iid in self.IDS[:3]}
        codigo, out, err = self.rodar_real(mapa, '--max-chamadas', '3')
        self.assertEqual((codigo, len(self.pedidos)), (3, 3))
        self.assertEqual(self.tentados_no_arquivo(), list(self.IDS[:3]))




# ---------- dono do link (CA4) ----------
class TestDono(BaseItem):
    def test_dono_errado_no_meio_depois_de_usado_e_fora_do_piso_nada_e_gravado(self):
        self.com_itens(*self.IDS)
        ordem = list(self.IDS)
        self.respostas[ordem[0]] = [no(1001, productName='Perfume Reembalado Usado')]
        self.respostas[ordem[1]] = [no(1002, ratingStar='3.0')]
        self.destino = T.DESTINO_RUIM
        antes = self.todas()
        codigo, out, err = self.shopee()
        self.assertEqual(codigo, 1)
        self.assertIn('Nada foi gravado', err)
        self.assertEqual(self.chamadas, ordem[:3], 'para no primeiro ok, que é o terceiro')
        self.assertEqual(self.todas(), antes)
        self.assertEqual(len(self.destinos), 1)
        self.assertNotIn(LINK_B, out + err)

    def test_conferencia_so_acontece_uma_vez_e_depois_dela_o_link_novo_nao_e_regravado(self):
        self.com_itens(*self.IDS)
        antes = self.todas()
        self.assertEqual(self.shopee()[0], 0)
        self.assertEqual(self.destinos, [LINK_B])
        for iid in self.IDS:
            self.assertEqual(self.linha(iid)['url'], antes[iid]['url'], 'o link de afiliado do banco nunca troca')

    def test_destino_que_nao_redireciona_ou_falha_na_rede_nao_grava(self):
        for destino, codigo_esperado in ((None, 1), (OSError(f'rede caiu {SECRET}'), 1),
                                         (urllib.error.URLError(SECRET), 1)):
            with self.subTest(repr(destino)[:30]):
                self.limpar()
                self.com_itens(*self.IDS[:2])
                self.destino = destino
                antes = self.todas()
                codigo, out, err = self.shopee()
                self.assertEqual(codigo, codigo_esperado)
                self.assertEqual(self.todas(), antes)
                self.assertNotIn(SECRET, out + err)
                self.assertNotIn('Traceback', err)

    def test_dono_de_outro_afiliado_em_destino_com_utm_parecido(self):
        for destino in (f'https://shopee.com.br/x?utm_source=an_{T.ID}9', f'https://shopee.com.br/x?utm_source=an_{T.ID[:-1]}',
                        f'https://shopee.com.br/x?utm_source=an_{T.ID}&utm_source=an_999',
                        f'http://shopee.com.br/x?utm_source=an_{T.ID}', f'https://evil.com/x?utm_source=an_{T.ID}',
                        f'https://shopee.com.br.evil.com/x?utm_source=an_{T.ID}'):
            with self.subTest(destino):
                self.limpar()
                self.com_itens(self.IDS[0])
                self.destino = destino
                antes = self.todas()
                self.assertEqual(self.shopee()[0], 1)
                self.assertEqual(self.todas(), antes)


# ---------- gravação só do preço (CA2) ----------
class TestRelerSoPreco(BaseItem):
    def preparar(self):
        self.com_itens('112233.1001')
        con = S.conectar()
        valores = {c: f'banco-{c}' for c in S.CAMPOS}
        valores.update(preco='R$ 50,00', preco_antigo='R$ 60,00', desconto='-17%', imagem=T.FOTO + '-banco',
                       num_avaliacoes='321', frete='Frete grátis', cupom='CUPOM10')
        con.execute('UPDATE items SET ' + ', '.join(f'{c}=?' for c in valores) + " WHERE item_id='112233.1001'",
                    list(valores.values()))
        con.commit()
        con.close()

    def test_so_preco_antigo_e_desconto_mudam_e_todo_o_resto_da_linha_fica(self):
        self.preparar()
        self.respostas['112233.1001'] = [no(1001, productName='Outro título da API', ratingStar='4.9', sales=7777,
                                            imageUrl=T.FOTO + '-api', priceMin='19.9', priceDiscountRate=33)]
        antes = self.linha('112233.1001')
        self.assertEqual(self.shopee()[0], 0)
        depois = self.linha('112233.1001')
        self.assertEqual(sem_volateis(depois), sem_volateis(antes))
        self.assertEqual((depois['preco'], depois['preco_antigo'], depois['desconto']), ('R$ 19,90', '', '-33%'))
        self.assertTrue(depois['preco_em'].startswith(T.hoje()))
        self.assertGreater(depois['preco_em'], antes['preco_em'])

    def test_edicao_no_meio_da_rodada_de_qualquer_campo_sobrevive(self):
        self.preparar()
        novo = {'titulo': 'Editado no site', 'avaliacao': '5,0 de 5 estrelas', 'num_avaliacoes': '9',
                'vendas': '1 vendido', 'frete': 'Editado', 'cupom': 'NOVO', 'imagem': T.FOTO + '-site',
                'cat': 'Cozinha', 'busca': 'Panela', 'url': 'https://s.shopee.com.br/Editado9'}

        def site_muda():
            con = S.conectar()
            con.execute('UPDATE items SET ' + ', '.join(f'{c}=?' for c in novo) + " WHERE item_id='112233.1001'",
                        list(novo.values()))
            con.commit()
            con.close()
        self.efeitos['112233.1001'] = site_muda
        self.assertEqual(self.shopee()[0], 0)
        depois = self.linha('112233.1001')
        for campo, valor in novo.items():
            self.assertEqual(depois[campo], valor, campo)
        self.assertEqual(depois['preco'], 'R$ 1.234,50')

    def test_preco_digitado_no_site_no_meio_da_rodada_e_trocado_pelo_da_api(self):
        self.preparar()

        def site_muda():
            con = S.conectar()
            con.execute("UPDATE items SET preco='R$ 1,00', preco_antigo='R$ 2,00' WHERE item_id='112233.1001'")
            con.commit()
            con.close()
        self.efeitos['112233.1001'] = site_muda
        self.assertEqual(self.shopee()[0], 0)
        a = self.linha('112233.1001')
        self.assertEqual((a['preco'], a['preco_antigo']), ('R$ 1.234,50', ''))

    def test_item_excluido_antes_da_vez_dele_nao_e_reinserido(self):
        self.com_itens(*self.IDS[:3])
        self.efeitos[self.IDS[0]] = lambda: self._apagar(self.IDS[2])
        codigo, out, _ = self.shopee()
        self.assertEqual(codigo, 0)
        self.assertIsNone(self.linha(self.IDS[2]))
        self.assertEqual(len(self.todas()), 2)
        self.assertIn('1 sumidos', out)

    def _apagar(self, iid):
        con = S.conectar()
        con.execute('DELETE FROM items WHERE item_id=?', (iid,))
        con.commit()
        con.close()

    def test_item_excluido_e_recriado_com_outro_link_mantem_o_link_novo(self):
        self.com_itens('112233.1001')

        def troca():
            con = S.conectar()
            con.execute("UPDATE items SET url='https://s.shopee.com.br/Recriado1', cupom='X' WHERE item_id='112233.1001'")
            con.commit()
            con.close()
        self.efeitos['112233.1001'] = troca
        self.assertEqual(self.shopee()[0], 0)
        a = self.linha('112233.1001')
        self.assertEqual((a['url'], a['cupom']), ('https://s.shopee.com.br/Recriado1', 'X'))

    def test_preco_em_so_muda_com_preco_legivel(self):
        ilegiveis = (None, '', 0, '0', '0.0', '0.001', 0.004, -5, '-5', 'abc', True, False, [], {}, 'NaN', 'nan', 'inf',
                     float('nan'), float('inf'), 10**9, '1000000000', '1e9', '12,50', 'R$ 12', '1.2.3', '١٢',
                     '1' * 13)
        for valor in ilegiveis:
            with self.subTest(priceMin=valor):
                self.limpar()
                self.com_itens('112233.1001')
                self.respostas['112233.1001'] = [no(1001, priceMin=valor)]
                antes = self.linha('112233.1001')
                codigo, out, err = self.shopee()
                self.assertEqual(codigo, 0, err)
                depois = self.linha('112233.1001')
                if depois != antes:   # só admito mudança se o preço gravado for legível e o preco_em de agora
                    self.assertIsNotNone(S.ler_preco(depois['preco']), depois)
                    self.fail(f'priceMin={valor!r} gravou {depois["preco"]!r}')
                self.assertIn('0 atualizados', out)

    def test_preco_legivel_grava_e_carimba_preco_em(self):
        for valor, esperado in (('0.01', 'R$ 0,01'), (1, 'R$ 1,00'), ('1234.5', 'R$ 1.234,50'), (999999.99, 'R$ 999.999,99'),
                                (' 12.5 ', 'R$ 12,50'), (19.904, 'R$ 19,90')):
            with self.subTest(priceMin=valor):
                self.limpar()
                self.com_itens('112233.1001')
                self.respostas['112233.1001'] = [no(1001, priceMin=valor)]
                self.assertEqual(self.shopee()[0], 0)
                a = self.linha('112233.1001')
                self.assertEqual(a['preco'], esperado)
                self.assertTrue(a['preco_em'].startswith(T.hoje()))

    def test_desconto_invalido_da_api_vira_vazio_sem_estragar_o_preco(self):
        for taxa, esperado in ((150, ''), (0, ''), (-5, ''), ('x', ''), (None, ''), (True, ''), (99, '-99%'),
                               ('25', '-25%'), (12.7, '-12%')):
            with self.subTest(taxa=taxa):
                self.limpar()
                self.com_itens('112233.1001')
                self.respostas['112233.1001'] = [no(1001, priceDiscountRate=taxa)]
                self.assertEqual(self.shopee()[0], 0)
                a = self.linha('112233.1001')
                self.assertEqual((a['preco'], a['desconto']), ('R$ 1.234,50', esperado))

    def test_usado_fora_do_piso_titulo_vazio_e_link_ruim_nao_gravam_nada(self):
        casos = {'usado': no(1001, productName='Perfume USADO 100ml'), 'recondicionado': no(1001, productName='Recondicionado'),
                 'nota_baixa': no(1001, ratingStar='4.49'), 'nota_nula': no(1001, ratingStar=None),
                 'vendas_49': no(1001, sales=49), 'vendas_nulas': no(1001, sales=None),
                 'sem_titulo': no(1001, productName=''), 'titulo_so_espacos': no(1001, productName='   '),
                 'link_comum': no(1001, offerLink='https://shopee.com.br/produto-i.1.2'),
                 'link_http': no(1001, offerLink='http://s.shopee.com.br/AbC123'),
                 'link_de_outra_loja': no(1001, offerLink='https://meli.la/abc'), 'sem_link': no(1001, offerLink=None)}
        for nome, nodo in casos.items():
            with self.subTest(nome):
                self.limpar()
                self.com_itens('112233.1001')
                self.respostas['112233.1001'] = [nodo]
                antes = self.linha('112233.1001')
                codigo, out, err = self.shopee()
                self.assertEqual(codigo, 0, err)
                self.assertEqual(self.linha('112233.1001'), antes)
                self.assertEqual(self.destinos, [], 'sem ok, sem conferência de dono')

    def test_piso_no_limite_exato_passa(self):
        self.com_itens('112233.1001')
        self.respostas['112233.1001'] = [no(1001, ratingStar='4.5', sales=50)]
        self.assertEqual(self.shopee()[0], 0)
        self.assertEqual(self.linha('112233.1001')['preco'], 'R$ 1.234,50')

    def test_nunca_insere_nem_apaga_item_de_outras_abas_e_lojas(self):
        self.com_itens(*self.IDS[:2])
        self.inserir('shopee', '5.5', 'Panela', cat='Cozinha')
        self.inserir('amazon', 'B0AAAAAAA1', 'Perfume Floral')
        self.inserir('ml', 'MLB1234567', 'Perfume Floral', url='https://meli.la/x')
        antes = self.todas()
        self.respostas['112233.1001'] = [no(1001), no(5, shopId=5), no(77, shopId=88)]
        self.assertEqual(self.shopee()[0], 0)
        depois = self.todas()
        self.assertEqual(set(depois), set(antes), 'nenhum item novo, nenhum apagado')
        for iid in ('5.5', 'B0AAAAAAA1', 'MLB1234567'):
            self.assertEqual(depois[iid], antes[iid])
        self.assertNotIn('5.5', self.chamadas)

    def test_item_de_id_fora_do_formato_da_loja_nao_e_consultado(self):
        self.com_itens('112233.1001')
        for ruim in ('abc', '112233', '112233.', '.1001', '1.2.3', '1 2.3', '112233.1001\n', '٣.٤', '1' * 21 + '.1'):
            self.inserir('shopee', ruim, 'Perfume Floral')
        self.assertEqual(self.shopee()[0], 0)
        self.assertEqual(self.chamadas, ['112233.1001'])


# ---------- ids de 11 a 20 dígitos e Int64 (CA1) ----------
class TestIds(BaseItem):
    def test_ids_longos_vao_como_inteiros_exatos_e_o_no_certo_e_achado(self):
        casos = ('112233.12345678901', '1234567890.12345678901234', '112233.9007199254740993',
                 '112233.9223372036854775807', '9223372036854775807.1', '112233.9223372036854775808',
                 '112233.12345678901234567890', '12345678901234567890.1')
        for iid in casos:
            shop, item = iid.split('.')
            ok = int(item) <= 2**63 - 1 and int(shop) <= 2**63 - 1
            with self.subTest(iid):
                self.limpar()
                self.inserir('shopee', iid, 'Perfume Floral')
                self.respostas[iid] = [no(int(item), shopId=int(shop))]
                codigo, out, err = self.shopee()
                self.assertEqual(codigo, 0, err)
                self.assertEqual(self.chamadas, [iid] if ok else [])
                self.assertEqual(self.linha(iid)['preco'], 'R$ 1.234,50' if ok else 'R$ 50,00')

    def test_corpo_da_requisicao_tem_os_digitos_exatos_sem_notacao_cientifica(self):
        for item in ('9007199254740993', '9223372036854775807', '12345678901'):
            corpo = CS.corpo_item('112233', item)
            self.assertIn(f'"itemId":"{item}",', corpo)
            self.assertNotIn('e+', corpo)
            self.assertNotIn('.0,', corpo)
            self.assertEqual(ids_do_corpo(json.loads(corpo)), (112233, int(item)))

    def test_ids_de_20_digitos_e_acima_do_int64_nao_chegam_a_rede(self):
        for shop, item in (('1', '9223372036854775808'), ('99999999999999999999', '1'), ('1', '99999999999999999999'),
                           ('9223372036854775808', '9223372036854775808')):
            with self.subTest(item=(shop, item)):
                with self.assertRaises(ValueError):
                    CS.corpo_item(shop, item)
                self.assertEqual(A._ids_consultaveis(CS, f'{shop}.{item}'), None)

    def test_resposta_com_id_como_texto_ou_inteiro_casa_e_com_float_nao(self):
        self.com_itens('112233.9007199254740993')
        iid = '112233.9007199254740993'
        for itemId, casa in ((9007199254740993, True), ('9007199254740993', True), (9007199254740992, False),
                             (9007199254740993.0, False), (9.007199254740993e15, False), ('9.007199254740993e15', False)):
            with self.subTest(itemId=itemId):
                self.limpar()
                self.inserir('shopee', iid, 'Perfume Floral')
                self.respostas[iid] = [no(itemId)]
                self.assertEqual(self.shopee()[0], 0)
                self.assertEqual(self.linha(iid)['preco'], 'R$ 1.234,50' if casa else 'R$ 50,00', itemId)

    def test_ids_zero_e_com_zero_a_esquerda_documentam_o_comportamento(self):
        """Id '0' passa no corpo_item (a API recusaria?) e id com zero à esquerda nunca casa com o nó da API."""
        corpo = json.loads(CS.corpo_item('0', '0'))
        self.assertEqual(ids_do_corpo(corpo), (0, 0))
        self.com_itens('0112233.1001')
        self.respostas['0112233.1001'] = [no(1001, shopId=112233)]
        self.assertEqual(self.shopee()[0], 0)
        self.assertEqual(self.linha('0112233.1001')['preco'], 'R$ 50,00', 'sem casar, não grava (não visto)')


# ---------- segredo, rede e ambiente (CA4) ----------
class TestSegredoERede(BaseItem):
    def test_o_secret_nao_aparece_em_nenhuma_saida_nem_no_banco_nem_no_progresso(self):
        excecoes = (CS.ErroApi(10010, 400), CS.RespostaInvalida(), CS.LimiteAtingido(), RuntimeError(SECRET),
                    OSError(f'x {SECRET}'), ValueError(SECRET), KeyError(SECRET), urllib.error.URLError(SECRET),
                    UnicodeDecodeError('utf-8', b'x', 0, 1, SECRET),
                    urllib.error.HTTPError(CS.URL_API, 500, SECRET, {}, io.BytesIO(SECRET.encode())))
        for exc in excecoes:
            with self.subTest(type(exc).__name__):
                self.limpar()
                self.com_itens(*self.IDS[:2])
                self.respostas[self.IDS[0]] = exc
                codigo, out, err = self.shopee()
                self.assertNotIn(SECRET, out + err)
                self.assertNotIn('Traceback', out + err)
                self.assertNotIn(APP_ID + SECRET, out + err)
                for caminho in (S.DB, S.DB + '-wal', A.FEITOS):
                    if os.path.exists(caminho):
                        with open(caminho, 'rb') as f:
                            self.assertNotIn(SECRET.encode(), f.read(), caminho)

    def test_excecao_na_requisicao_de_verdade_nao_vaza_nem_pelo_opener(self):
        """Com o buscar_item de verdade, o erro sobe pelo _pedir; só o tipo aparece."""
        for exc in (OSError(SECRET), urllib.error.URLError(SECRET), TimeoutError(SECRET), ConnectionResetError(SECRET),
                    urllib.error.HTTPError(CS.URL_API, 502, SECRET, {}, io.BytesIO(f'{{"x":"{SECRET}"}}'.encode()))):
            with self.subTest(type(exc).__name__):
                self.limpar()
                self.com_itens(self.IDS[0])
                with mock.patch.object(CS, 'buscar_item', T.BUSCAR_ITEM), \
                        mock.patch.object(CS.OPENER_API, 'open', side_effect=exc):
                    codigo, out, err = self.shopee()
                self.assertEqual(codigo, 1)
                self.assertNotIn(SECRET, out + err)
                self.assertNotIn('Traceback', err)

    def test_http_com_corpo_de_erro_gigante_ou_lixo_nao_derruba_com_traceback(self):
        for corpo in (b'', b'\xff\xfe', b'[' * 5000, b'{"errors":"x"}', b'{"errors":[1]}',
                      b'{"errors":[{"extensions":{"code":"10030"}}]}'):
            with self.subTest(corpo[:12]):
                self.limpar()
                self.com_itens(self.IDS[0])
                erro = urllib.error.HTTPError(CS.URL_API, 400, 'x', {}, io.BytesIO(corpo))
                with mock.patch.object(CS, 'buscar_item', T.BUSCAR_ITEM), \
                        mock.patch.object(CS.OPENER_API, 'open', side_effect=erro):
                    codigo, out, err = self.shopee()
                self.assertIn(codigo, (1, 3))
                self.assertNotIn('Traceback', err)

    def test_limite_da_api_no_meio_sai_com_3_com_resumo_e_o_ja_gravado_fica(self):
        self.com_itens(*self.IDS)
        self.respostas[self.IDS[2]] = CS.LimiteAtingido()
        codigo, out, err = self.shopee()
        self.assertEqual(codigo, 3)
        self.assertIn('RESUMO shopee', out)
        self.assertIn('PAROU', err)
        self.assertEqual(self.chamadas, list(self.IDS[:3]))
        self.assertEqual(self.linha(self.IDS[0])['preco'], 'R$ 1.234,50')
        self.assertEqual(self.linha(self.IDS[3])['preco'], 'R$ 50,00')
        self.assertEqual(self.progresso(), [f'shopee|{A.hoje()}|item|{i}' for i in self.IDS[:2]], 'o item do limite não é marcado')

    def test_ctrl_c_no_meio_sai_com_130_e_sem_traceback(self):
        self.com_itens(*self.IDS[:3])
        self.respostas[self.IDS[1]] = KeyboardInterrupt()
        codigo, out, err = self.shopee()
        self.assertEqual(codigo, 130)
        self.assertNotIn('Traceback', err)
        self.assertEqual(self.linha(self.IDS[0])['preco'], 'R$ 1.234,50', 'o já gravado fica')
        self.assertEqual(self.progresso(), [f'shopee|{A.hoje()}|item|{self.IDS[0]}'])

    def test_secret_sai_do_ambiente_mesmo_quando_falta_o_app_id_ou_o_id_do_afiliado(self):
        casos = ({'ACHADINHOS_SHOPEE_SECRET': SECRET}, {'ACHADINHOS_SHOPEE_SECRET': SECRET, 'ACHADINHOS_SHOPEE_APP_ID': 'a b'})
        for env in casos:
            with self.subTest(sorted(env)):
                self.assertEqual(self.shopee(env=env)[0], 2)
                self.assertIsNone(self.secret_no_ambiente)
        self.com_itens(self.IDS[0])
        self.assertEqual(self.chamadas, [])

    def test_nenhum_subprocesso_e_aberto_e_o_ambiente_filho_nao_tem_o_secret(self):
        self.com_itens(*self.IDS[:2])
        with mock.patch.object(subprocess, 'Popen', side_effect=AssertionError('subprocesso')), \
                mock.patch.object(os, 'system', side_effect=AssertionError('os.system')):
            self.assertEqual(self.shopee()[0], 0)

    def test_um_unico_ponto_de_rede_da_api_e_o_pedir_sem_url_por_parametro(self):
        with open(os.path.join(RAIZ, 'coletar_shopee.py'), encoding='utf-8') as f:
            fonte = f.read()
        self.assertEqual(fonte.count('OPENER_API.open('), 1)
        self.assertEqual(list(inspect.signature(CS._pedir).parameters), ['cred', 'corpo'])
        self.assertEqual(list(inspect.signature(CS.buscar_item).parameters), ['cred', 'shop', 'item'])
        self.assertEqual(len(re.findall(r'urlopen\(', fonte)), 0)
        self.assertEqual(len(re.findall(r'\bsocket\b|http\.client|requests', fonte)), 0)
        for nome in ('fonte_shopee_item', '_mais_velho_primeiro', '_ids_consultaveis', '_observacao_shopee', '_rodar_shopee'):
            trecho = inspect.getsource(getattr(A, nome))
            for proibido in ('urlopen', 'OPENER', '.open(', 'socket', 'http.client', 'subprocess', 'os.system'):
                self.assertNotIn(proibido, trecho, f'{nome} não fala com a rede por conta própria')

    def test_o_secret_so_e_lido_do_ambiente_com_pop(self):
        for arquivo in ('coletar_shopee.py', 'atualizar_precos.py'):
            with open(os.path.join(RAIZ, arquivo), encoding='utf-8') as f:
                for n, linha in enumerate(f, 1):
                    codigo = linha.split('#')[0]
                    if 'SHOPEE_SECRET' in codigo and 'os.environ' in codigo:
                        self.assertIn('pop(', codigo, f'{arquivo}:{n}')
                    self.assertNotRegex(codigo, r'environ\[.ACHADINHOS_SHOPEE_SECRET.\]', f'{arquivo}:{n}')

    def test_cabecalhos_e_corpo_da_requisicao_de_item_nao_levam_o_secret_e_a_assinatura_confere(self):
        pedidos = []

        def open_(req, timeout=None):
            pedidos.append(req)
            return io.BytesIO(json.dumps(resposta([no(1001)])).encode())
        self.com_itens(self.IDS[0])
        with mock.patch.object(CS, 'buscar_item', T.BUSCAR_ITEM), mock.patch.object(CS.OPENER_API, 'open', open_), \
                mock.patch('time.time', return_value=1_700_000_000):
            self.assertEqual(self.shopee()[0], 0)
        req = pedidos[0]
        corpo = req.data.decode()
        self.assertNotIn(SECRET, corpo + repr(req.header_items()))
        import hashlib
        esperado = hashlib.sha256(f'{APP_ID}1700000000{corpo}{SECRET}'.encode()).hexdigest()
        self.assertEqual(req.get_header('Authorization'),
                         f'SHA256 Credential={APP_ID}, Timestamp=1700000000, Signature={esperado}')
        self.assertEqual(req.get_method(), 'POST')
        self.assertEqual(req.full_url, 'https://open-api.affiliate.shopee.com.br/graphql')


# ---------- conferir --por-item (G1) ----------
class TestConferirPorItem(unittest.TestCase):
    """CS.main(['conferir', ...]) com a API e o destino falsos, sem passar pelo atualizar."""
    def setUp(self):
        for alvo, nome, novo in ((CS, 'ID_AFILIADO_SHOPEE', T.ID), (CS.OPENER_API, 'open', None),
                                 (CS, 'destino', None), (CS, 'pausa', None)):
            pass
        self.eventos, self.pedidos = [], []
        self.fila = []
        self.destino = T.DESTINO_BOM
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(CS, 'ID_AFILIADO_SHOPEE', T.ID).start()
        mock.patch.object(CS, 'pausa', lambda a=1, b=3: self.eventos.append('pausa')).start()
        mock.patch.object(CS, 'destino', self.falso_destino).start()
        mock.patch.object(CS.OPENER_API, 'open', self.falso_open).start()

    def falso_destino(self, link):
        self.eventos.append('dono')
        return self.destino

    def falso_open(self, req, timeout=None):
        self.eventos.append('api')
        self.pedidos.append(json.loads(req.data))
        r = self.fila.pop(0)
        if isinstance(r, BaseException):
            raise r
        return io.BytesIO(json.dumps(r).encode())

    def conferir(self, *flags):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, ENV), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            codigo = CS.main(['conferir', *flags])
        self.assertNotIn(SECRET, out.getvalue() + err.getvalue())
        self.assertNotIn(LINK_B, out.getvalue() + err.getvalue())
        return codigo, out.getvalue(), err.getvalue()

    def test_sem_a_flag_e_uma_chamada_so_e_nada_de_consulta_por_item(self):
        self.fila = [resposta([no(1)])]
        codigo, out, _ = self.conferir()
        self.assertEqual((codigo, self.eventos), (0, ['api', 'dono']))
        self.assertNotIn('por item', out)
        self.assertNotIn('productOfferV2(shopId', json.dumps(self.pedidos))

    def test_com_a_flag_sao_duas_chamadas_com_dono_e_pausa_entre_elas(self):
        self.fila = [resposta([no(1)]), resposta([no(1)])]
        codigo, out, _ = self.conferir('--por-item')
        self.assertEqual(codigo, 0)
        self.assertEqual(self.eventos, ['api', 'dono', 'pausa', 'api'])
        self.assertIn('consulta por item', out)

    def test_consulta_os_ids_do_primeiro_no_valido_e_nao_do_primeiro_no(self):
        invalido = no(111, shopId=222, productName='Perfume Usado', offerLink=LINK_B)
        valido = no(333, shopId=444)
        self.fila = [resposta([invalido, valido, no(555, shopId=666)]), resposta([valido])]
        self.assertEqual(self.conferir('--por-item')[0], 0)
        self.assertEqual(ids_do_corpo(self.pedidos[1]), (444, 333))
        self.assertEqual(self.pedidos[1]['query'], CS.CONSULTA_ITEM)

    def test_nos_de_outros_ids_ou_so_a_loja_igual_dao_1(self):
        base = no(333, shopId=444)
        for nos in ([], [no(333, shopId=1)], [no(1, shopId=444)], [no(444, shopId=333)], [{'x': 1}], ['a']):
            with self.subTest(nos=nos):
                self.eventos.clear()
                self.fila = [resposta([base]), resposta(nos)]
                codigo, out, err = self.conferir('--por-item')
                self.assertEqual(codigo, 1)
                self.assertIn('a consulta por item não devolveu o produto pedido', err)

    def test_no_certo_no_fim_da_lista_vale(self):
        base = no(333, shopId=444)
        self.fila = [resposta([base]), resposta([no(1), no(2), no(3), no(4), base])]
        self.assertEqual(self.conferir('--por-item')[0], 0)

    def test_codigos_de_recusa_aparecem_e_a_sequencia_para(self):
        for codigo_api in (10010, 11001):
            with self.subTest(codigo_api):
                self.eventos.clear()
                self.fila = [resposta([no(1)]), {'errors': [{'message': 'x', 'extensions': {'code': codigo_api}}]}]
                codigo, out, err = self.conferir('--por-item')
                self.assertEqual(codigo, 1)
                self.assertIn(f'código {codigo_api}', err)

    def test_no_certo_sem_preco_legivel_da_1(self):
        base = no(333, shopId=444)
        for preco in (None, '', 0, '0', '-1', 'abc', True, 10**9):
            with self.subTest(preco=preco):
                self.fila = [resposta([base]), resposta([no(333, shopId=444, priceMin=preco)])]
                codigo, _, err = self.conferir('--por-item')
                self.assertEqual(codigo, 1)
                self.assertIn('sem preço legível', err)

    def test_limite_na_segunda_chamada_sai_com_3(self):
        self.fila = [resposta([no(1)]), {'errors': [{'extensions': {'code': 10030}}]}]
        codigo, _, err = self.conferir('--por-item')
        self.assertEqual(codigo, 3)
        self.assertIn('10030', err)

    def test_dono_errado_para_antes_da_consulta_por_item(self):
        self.destino = T.DESTINO_RUIM
        self.fila = [resposta([no(1)])]
        codigo, _, err = self.conferir('--por-item')
        self.assertEqual(codigo, 1)
        self.assertEqual(self.eventos, ['api', 'dono'], 'sem a 2ª chamada, sem gastar cota')

    def test_primeiro_no_valido_com_id_acima_do_int64_sai_com_1_sem_segunda_chamada_e_sem_traceback(self):
        self.fila = [resposta([no(99999999999999999999, shopId=1)]), resposta([])]
        codigo, out, err = self.conferir('--por-item')
        self.assertEqual(codigo, 1)
        self.assertNotIn('Traceback', err)
        self.assertEqual(self.eventos.count('api'), 1)

    def test_saida_0_mostra_so_ids_e_o_preco_formatado_sem_titulo_link_nem_secret(self):
        for bruto, esperado in (('49.9', 'R$ 49,90'), ('4990.5', 'R$ 4.990,50'), (12, 'R$ 12,00'), ('0.99', 'R$ 0,99')):
            with self.subTest(bruto=bruto):
                base = no(333, shopId=444)
                self.fila = [resposta([base]), resposta([no(333, shopId=444, priceMin=bruto, productName='TITULO-SECRETO-GG')])]
                codigo, out, err = self.conferir('--por-item')
                self.assertEqual(codigo, 0, err)
                self.assertIn(f'Produto 444.333: preço lido {esperado}.', out)
                self.assertNotIn('TITULO-SECRETO-GG', out + err)
                self.assertNotIn('Perfume', out + err)

    def test_a_linha_do_preco_so_aparece_na_saida_0_e_nunca_nas_falhas(self):
        base = no(333, shopId=444)
        casos = ([resposta([base]), resposta([])], [resposta([base]), resposta([no(333, shopId=444, priceMin=None)])],
                 [resposta([base]), resposta([no(333, shopId=444, ratingStar='3.0')])],
                 [resposta([base]), {'errors': [{'extensions': {'code': 11001}}]}])
        for fila in casos:
            with self.subTest(fila=str(fila)[:60]):
                self.fila = list(fila)
                codigo, out, err = self.conferir('--por-item')
                self.assertNotEqual(codigo, 0)
                self.assertNotIn('preço lido', out + err)

    def test_sem_a_flag_nao_imprime_o_preco(self):
        self.fila = [resposta([no(1)])]
        codigo, out, _ = self.conferir()
        self.assertEqual(codigo, 0)
        self.assertNotIn('preço lido', out)

    def test_o_preco_impresso_e_o_mesmo_que_a_rodada_gravaria(self):
        for bruto in ('0.5', '49.9', '1234.5', '99999.99'):
            with self.subTest(bruto=bruto):
                base = no(333, shopId=444)
                self.fila = [resposta([base]), resposta([no(333, shopId=444, priceMin=bruto)])]
                _, out, _ = self.conferir('--por-item')
                gravaria = CS.no_para_item(no(333, shopId=444, priceMin=bruto), 't', '')['data']['preco']
                self.assertIn(f'preço lido {gravaria}.', out)

    def test_flag_invalida_em_outros_subcomandos_sai_com_2(self):
        for argv in (['buscas', '--cat', CAT, '--por-item'], ['importar', 'x', '--por-item'], ['conferir', '--por-item=1'],
                     ['conferir', '--por_item']):
            with self.subTest(argv), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as e:
                    CS.main(argv)
                self.assertEqual(e.exception.code, 2)


# ---------- README e CLAUDE.md batem com o código (CA5) ----------
class TestDocumentacao(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(RAIZ, 'README.md'), encoding='utf-8') as f:
            readme = f.read()
        i = readme.index('\n### Shopee\n', readme.index('## Atualizar os preços'))
        cls.secao = readme[i:readme.index('\n### O que acontece', i)]
        cls.reverter = readme[readme.index('\n### Reverter'):readme.index('\n## Plugin do Chrome')]
        with open(os.path.join(RAIZ, 'CLAUDE.md'), encoding='utf-8') as f:
            cls.claude = f.read()
        with open(os.path.join(RAIZ, 'atualizar_precos.py'), encoding='utf-8') as f:
            cls.atualizar = f.read()
        with open(os.path.join(RAIZ, 'coletar_shopee.py'), encoding='utf-8') as f:
            cls.coletar = f.read()

    def comandos(self, script):
        achados = []
        for bloco in re.findall(r'```\n(.*?)```', self.secao, re.S):
            for linha in bloco.splitlines():
                if f'python3 {script}' in linha:
                    achados.append(linha.split(f'python3 {script}', 1)[1].split(';')[0].strip())
        return achados

    def test_comandos_do_readme_sao_aceitos_pelos_scripts(self):
        mut = self.comandos('atualizar_precos.py')
        self.assertTrue(mut, 'o README traz o comando do atualizar_precos.py shopee')
        import shlex
        for c in mut:
            with self.subTest(c):
                args = A.ler_argumentos(shlex.split(c))
                self.assertEqual(args.loja, 'shopee')
                self.assertIn(CAT, args.abas)
        conf = self.comandos('coletar_shopee.py')
        self.assertIn('conferir --por-item', conf)
        for c in conf:
            if c.startswith('conferir'):
                with self.subTest(c):
                    self.assertTrue(CS.ler_argumentos(shlex.split(c)).modo == 'conferir')

    def test_exemplo_com_max_chamadas_mostra_o_valor_dentro_do_intervalo(self):
        valores = [int(v) for v in re.findall(r'--max-chamadas (\d+)', self.secao)]
        self.assertTrue(valores)
        for v in valores:
            self.assertTrue(1 <= v <= A.MAX_CHAMADAS_SHOPEE)
        self.assertIn(f'1 a {A.MAX_CHAMADAS_SHOPEE}', self.secao)
        self.assertIn(f'padrão {A.CHAMADAS_SHOPEE_PADRAO}', self.secao)

    def test_textos_citados_no_readme_existem_no_codigo(self):
        frase_filtro = 'a API não filtrou pelo item; rode coletar_shopee.py conferir --por-item'
        self.assertIn(frase_filtro, self.secao)
        self.assertIn(frase_filtro, self.atualizar)
        self.assertIn('a consulta por item não devolveu o produto pedido', self.secao)
        self.assertIn('a consulta por item não devolveu o produto pedido', self.coletar)
        for codigo in ('10010', '11001'):
            self.assertIn(codigo, self.secao)
        self.assertIn('10030', self.secao)
        self.assertIn(str(CS.ERRO_LIMITE), '10030')
        self.assertIn('espere de 15 a 30 min', self.secao)
        self.assertIn('espere de 15 a 30 minutos', self.atualizar)

    def test_formato_do_progresso_e_do_resumo_do_readme_e_o_que_o_codigo_grava(self):
        self.assertIn('shopee|<AAAA-MM-DD>|item|<shopId>.<itemId>', self.secao)
        self.assertIn("rotulo = f'item|{iid}'", self.atualizar)
        self.assertEqual(A.MAX_IDS_RESUMO, 20)
        self.assertIn('até 20 ids', self.secao)
        for rotulo in ('atualizados', 'indisponíveis', 'não vistos', 'fora do piso', 'usados', 'sem preço legível'):
            self.assertIn(f'`{rotulo}`', self.secao, rotulo)
        resumo = A.texto_resumo({'loja': 'shopee', 'selecionados': 1, 'ja_hoje': 0, 'atualizado': 0, 'sem_preco': 0,
                                 'fora_do_piso': 0, 'usado': 0, 'indisponivel': 0, 'sumiu': 0, 'nao_vistos': 0,
                                 'ids_nao_vistos': []})
        for palavra in ('atualizados', 'indisponíveis', 'não vistos', 'fora do piso', 'usados', 'sem preço legível'):
            self.assertIn(palavra, resumo)

    def test_readme_nao_diz_mais_que_falta_credencial_e_cita_o_portao(self):
        for texto in (self.secao, self.claude):
            self.assertNotIn('ainda não tem a credencial', texto)
        self.assertIn('conferir --por-item', self.secao)
        self.assertIn('conferir --por-item', self.claude)
        self.assertIn('shopee --cat ABA [--max-chamadas N]', self.claude)
        self.assertIn('shopee|<dia>|item|<shopId>.<itemId>', self.claude)
        self.assertIn('fonte_shopee_item', self.claude)
        self.assertNotIn('fonte_shopee_api', self.claude + self.secao + self.atualizar)

    def test_readme_cita_o_backup_e_o_arquivo_que_a_reversao_usa(self):
        self.assertIn('backups/auto-', self.secao)
        self.assertIn('backups/auto-', self.reverter)
        self.assertNotIn('antes-shopee-item.db', self.secao + self.reverter, 'o nome fixo saiu: vale o backup datado')
        self.assertIn('migrar_categorias.py --restaurar', self.reverter)
        self.assertTrue(os.path.exists(os.path.join(RAIZ, 'migrar_categorias.py')))

    def test_saidas_citadas_no_readme(self):
        self.assertIn('**3 limite da API (10030 ou HTTP 429) ou teto do `--max-chamadas`**', self.secao)
        self.assertIn('0 ok; 1 erro', self.secao)
        self.assertIn('2 configuração', self.secao)

    def blocos(self):
        return re.findall(r'```\n(.*?)```', self.secao, re.S)

    def blocos(self):
        return re.findall(r'```\n(.*?)```', self.secao, re.S)

    def test_dois_blocos_de_rodada_cada_um_com_um_comando_so_o_primeiro_com_o_teto_de_200(self):
        rodadas = [b for b in self.blocos() if 'atualizar_precos.py shopee' in b]
        self.assertEqual(len(rodadas), 2)
        for b in rodadas:
            self.assertEqual(b.count('python3 atualizar_precos.py'), 1)
            self.assertTrue(b.strip().startswith('read -rs S;'))
            self.assertTrue(b.strip().endswith('unset S'))
            self.assertIn('--cat "Perfumes e Perfumaria"', b)
        self.assertIn('--max-chamadas 200', rodadas[0])
        self.assertNotIn('--max-chamadas', rodadas[1])
        i = self.secao.index(rodadas[0])
        j = self.secao.index(rodadas[1])
        self.assertLess(i, j)
        self.assertIn('**Primeira vez:**', self.secao[:i][-400:])
        self.assertIn('**Depois, a aba inteira:**', self.secao[:j][-400:])

    def test_nenhum_bloco_tem_credencial_real(self):
        for b in self.blocos():
            self.assertNotRegex(b, r'APP_ID=\d')
            self.assertNotRegex(b, r'SECRET=["\']?[A-Za-z0-9]{8,}(?<!\$S)')
        self.assertNotIn(SECRET, self.secao)

    def bloco_de_backup(self):
        bloco = next(b for b in self.blocos() if 'backup_banco.py --motivo shopee' in b)
        self.assertEqual(bloco.strip(), 'python3 backup_banco.py --motivo shopee')
        return bloco

    def rodar_backup_do_readme(self, bloco, banco, **extra):
        """Roda o bloco do README na raiz do projeto (é onde o backup_banco.py está) com o banco apontado para a
        pasta temporária. O ACHADINHOS_DB vai sempre, para o comando nunca chegar ao achadinhos.db real; os
        backups caem em <pasta do banco>/backups."""
        env = {**os.environ, 'ACHADINHOS_DB': banco, 'http_proxy': 'http://127.0.0.1:9',
               'https_proxy': 'http://127.0.0.1:9', 'PYTHONDONTWRITEBYTECODE': '1', **extra}
        self.assertNotEqual(os.path.abspath(banco), os.path.join(RAIZ, 'achadinhos.db'))
        return subprocess.run(['bash', '-c', bloco], cwd=RAIZ, capture_output=True, text=True, timeout=60, env=env)

    def test_o_comando_de_backup_do_readme_faz_copia_integra_de_banco_em_wal_sem_alterar_o_original(self):
        import glob
        import sqlite3
        import tempfile
        bloco = self.bloco_de_backup()
        pasta = tempfile.mkdtemp(dir=T.TMP)
        banco = os.path.join(pasta, 'achadinhos.db')
        con = sqlite3.connect(banco)
        con.execute('PRAGMA journal_mode=WAL')
        con.execute('PRAGMA wal_autocheckpoint=0')   # o servidor no ar: dados ainda só no -wal
        con.execute('CREATE TABLE items (id INTEGER PRIMARY KEY, preco TEXT)')
        con.executemany('INSERT INTO items (preco) VALUES (?)', [(f'R$ {i},00',) for i in range(50)])
        con.commit()
        self.assertGreater(os.path.getsize(banco + '-wal'), 0)
        try:
            for vez in (1, 2):   # repetir é seguro: cada vez grava um arquivo novo, sem sobrescrever
                r = self.rodar_backup_do_readme(bloco, banco)
                self.assertEqual(r.returncode, 0, (vez, r.stderr))
            copias = sorted(glob.glob(os.path.join(pasta, 'backups', 'auto-shopee-*.db')))
            self.assertEqual(len(copias), 2, copias)
            self.assertFalse(glob.glob(os.path.join(pasta, 'backups', '*-wal')) + glob.glob(os.path.join(pasta, 'backups', '*-shm')))
            copia = sqlite3.connect(copias[0])
            self.assertEqual(copia.execute('SELECT COUNT(*) FROM items').fetchone()[0], 50, 'inclui o que só estava no WAL')
            self.assertEqual(copia.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            copia.close()
            con.execute('INSERT INTO items (preco) VALUES (?)', ('depois',))   # o original continua gravável
            con.commit()
            self.assertEqual(con.execute('SELECT COUNT(*) FROM items').fetchone()[0], 51)
        finally:
            con.close()

    def test_backup_do_readme_nao_cria_o_banco_se_ele_nao_existe(self):
        import tempfile
        bloco = self.bloco_de_backup()
        pasta = tempfile.mkdtemp(dir=T.TMP)
        r = self.rodar_backup_do_readme(bloco, os.path.join(pasta, 'achadinhos.db'))
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(os.listdir(pasta), [], 'sem banco, o backup não cria banco nem pasta backups/')

    def test_backup_do_readme_restaura_com_o_migrar_categorias_de_ponta_a_ponta(self):
        import socket
        import tempfile
        import glob
        bloco = self.bloco_de_backup()
        pasta = tempfile.mkdtemp(dir=T.TMP)
        banco = os.path.join(pasta, 'achadinhos.db')
        with socket.socket() as s:
            s.bind(('127.0.0.1', 0))
            porta = s.getsockname()[1]
        env = {**os.environ, 'ACHADINHOS_DB': banco, 'ACHADINHOS_PORTA': str(porta), 'http_proxy': 'http://127.0.0.1:9',
               'https_proxy': 'http://127.0.0.1:9', 'PYTHONDONTWRITEBYTECODE': '1'}
        prep = ("import sys; sys.path.insert(0, %r); import servidor as S; S.criar_banco(); con = S.conectar();"
                "con.execute(\"INSERT INTO items (loja,item_id,cat,busca,url,titulo,preco,tem_dados,posicao,criado_em,"
                "atualizado_em,preco_em) VALUES ('shopee','1.2','C','b','https://s.shopee.com.br/Abc','T','R$ 10,00',"
                "1,0,'2026-01-01T00:00:00','2026-01-01T00:00:00','2026-01-01T00:00:00')\"); con.commit(); con.close()") % RAIZ
        r = subprocess.run([sys.executable, '-c', prep], cwd=pasta, env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self.rodar_backup_do_readme(bloco, banco)
        self.assertEqual(r.returncode, 0, r.stderr)
        backups = glob.glob(os.path.join(pasta, 'backups', 'auto-shopee-*.db'))
        self.assertEqual(len(backups), 1, backups)
        mexer = ("import sys; sys.path.insert(0, %r); import servidor as S; con = S.conectar();"
                 "con.execute(\"UPDATE items SET preco='R$ 999,00'\"); con.commit(); con.close()") % RAIZ
        subprocess.run([sys.executable, '-c', mexer], cwd=pasta, env=env, check=True, timeout=60)
        r = subprocess.run([sys.executable, os.path.join(RAIZ, 'migrar_categorias.py'), '--restaurar',
                            os.path.relpath(backups[0], pasta)], cwd=pasta, env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        import sqlite3
        con = sqlite3.connect(banco)
        self.assertEqual(con.execute('SELECT preco FROM items').fetchone()[0], 'R$ 10,00')
        con.close()

    def test_docs_e_codigo_concordam_nos_limites_da_parada_e_no_rotulo_tentado(self):
        self.assertEqual((A.DIVERGENTES_PARA_PARAR, A.SEM_PRODUTO_PARA_PARAR, A.TENTADO), (5, 20, 'tentado'))
        topo = ' '.join(self.atualizar[:self.atualizar.index('"""', self.atualizar.index('"""') + 3)].split())
        self.assertIn('SEM_PRODUTO_PARA_PARAR respostas', topo)
        self.assertIn('`tentado|<iid>`', topo)
        self.assertRegex(self.secao, rf'{A.DIVERGENTES_PARA_PARAR} respostas[^.]*que só trouxeram outros produtos')
        self.assertRegex(self.secao, rf'{A.SEM_PRODUTO_PARA_PARAR} respostas[^.]*sem o produto pedido')
        self.assertIn(f'{A.SEM_PRODUTO_PARA_PARAR} sem o produto pedido', self.claude)
        self.assertIn('shopee|<AAAA-MM-DD>|tentado|<shopId>.<itemId>', self.secao)
        self.assertIn('shopee|<dia>|tentado|<shopId>.<itemId>', self.claude)
        for texto in (self.secao, self.claude):
            self.assertNotIn(SECRET, texto)

    def test_docstring_do_atualizar_descreve_o_teto_e_o_padrao_reais(self):
        topo = self.atualizar[:self.atualizar.index('"""', self.atualizar.index('"""') + 3)]
        topo = ' '.join(topo.split())
        self.assertIn('padrão 1000, máximo 5000', topo)
        self.assertEqual((A.CHAMADAS_SHOPEE_PADRAO, A.MAX_CHAMADAS_SHOPEE), (1000, 5000))
        self.assertIn('DIVERGENTES_PARA_PARAR', topo)
        self.assertEqual(A.DIVERGENTES_PARA_PARAR, 5)
        self.assertIn('5 respostas', self.secao)


if __name__ == '__main__':
    unittest.main()
