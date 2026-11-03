#!/usr/bin/env python3
"""Testes de QA do disparo (docs/produto/planos/disparo-automatico.md, etapas 1 a 4): bordas e adversariais.

Uso:  python3 testes/test_disparo_qa.py -v

Estende test_disparo.py e test_disparo_servidor.py (importa os dois como módulos, sem duplicar o que eles
já provam). Banco sempre temporário, relógio injetado, transportes locais, proxy morto; nenhum teste toca
o achadinhos.db real, o servidor em 8765, a rede ou o WhatsApp. A paridade com o buildMsg roda o código
do index.html no node (vm), sem navegador. Só biblioteca padrão.
"""
import json
import os
import random
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_disparo as T            # noqa: E402  (Base, D, S, AFILIADO, SEGUNDA, Gravador...)
import test_disparo_servidor as TD  # noqa: E402  (ServidorDisparo, esperar, TS)

D, TS = T.D, TD.TS
TELEFONE, GRUPO_ID = T.TELEFONE, T.GRUPO_ID


def hora(dia, h, m=0, s=0):
    return dia.replace(hour=h, minute=m, second=s)


def instantaneo(con):
    """Cópia de todas as tabelas de dados (para provar que algo não gravou nada)."""
    return {t: [tuple(r) for r in con.execute(f'SELECT * FROM {t} ORDER BY 1')]
            for t in ('items', 'numeros', 'regras', 'envios', 'config')}


# ================================================================ CA8: paridade com o buildMsg real (node)
JS_PARIDADE = r'''
const fs = require('fs'), vm = require('vm');
const [html, entrada] = process.argv.slice(1);
const src = fs.readFileSync(html, 'utf8');
const loja = src.match(/^const LOJA = \{.*\};$/m)[0];
const ini = src.indexOf('function buildMsg(it){'), fim = src.indexOf('async function fetchItem');
if (ini < 0 || fim < ini) throw new Error('buildMsg não encontrado no index.html');
const ctx = vm.createContext({ templates: {}, current: 'x' });
vm.runInContext(loja + '\n' + src.slice(ini, fim) + '\nthis.buildMsg = buildMsg;', ctx);
const casos = JSON.parse(fs.readFileSync(entrada, 'utf8'));
const saida = casos.map(c => { ctx.templates = { x: c.template }; ctx.current = 'x'; return ctx.buildMsg(c.item); });
process.stdout.write(JSON.stringify(saida));
'''

URL_AMZ = 'https://www.amazon.com.br/dp/B0TESTE001?tag=desejodemen01-20'
DADOS_BASE = {'titulo': 'Fone', 'preco': 'R$ 10,00', 'preco_antigo': 'R$ 20,00', 'desconto': '-50%',
              'avaliacao': '4,7 de 5 estrelas', 'num_avaliacoes': '(135)', 'vendas': 'Mais de 1 mil compras',
              'frete': 'Frete GRÁTIS', 'cupom': 'CUPOM10', 'imagem': ''}


def caso(nome, template, url=URL_AMZ, loja='amazon', **dados):
    return {'nome': nome, 'template': template, 'item': {'loja': loja, 'url': url, 'data': {**DADOS_BASE, **dados}}}


ADVERSARIAIS = [
    caso('U+FEFF no meio e nas pontas do título e do cupom', '{TITULO_PRODUTO}\n{CUPOM}\n{LINK}',
         titulo='\ufeff\ufeffA\ufeffB\ufeff', cupom='\ufeff'),
    caso('U+200B sozinho no campo: é verdadeiro, a linha fica e o trim não tira', '*{TITULO_PRODUTO}*\n{FRETE}\n{LINK}',
         titulo='\u200b', frete='\u200b'),
    caso('desconto sem hífen, com hífen no meio e só o hífen', '{DESCONTO_PRODUTO} {PRECO_PRODUTO}\n{LINK}',
         desconto='12% -3'),
    caso('desconto só com hífen: a linha some', 'Desc: {DESCONTO_PRODUTO}\n{LINK}', desconto='-'),
    caso('todos os campos vazios', '{TITULO_PRODUTO}\n{PRECO_PRODUTO}\n{PRECO_ANTIGO}\n{DESCONTO_PRODUTO}\n'
         '{NUMERO_VENDAS}\n{FRETE}\n{CUPOM}\n\n\n\n{LINK}',
         titulo='', preco='', preco_antigo='', desconto='', avaliacao='', num_avaliacoes='', vendas='',
         frete='', cupom=''),
    caso('NUMERO_VENDAS só com "0" como texto (verdadeiro no JS)', '{NUMERO_VENDAS}|{LINK}', vendas='0'),
    caso('NUMERO_VENDAS cai em num_avaliacoes "0"', '{NUMERO_VENDAS}|{LINK}', vendas='', num_avaliacoes='0'),
    caso('placeholder repetido na mesma linha e na linha sumida', '{CUPOM} e {CUPOM}\n{FRETE} {FRETE}\n{LINK}',
         cupom='X', frete=''),
    caso('espaços Unicode e NBSP nas pontas', '\u00a0\u3000{TITULO_PRODUTO}\u2003\n{LINK}\u00a0', titulo='T'),
    caso('template com CRLF', '{TITULO_PRODUTO}\r\n{LINK}\r\n', titulo='T'),
    caso('$ de substituição em todos os campos', '{TITULO_PRODUTO} {PRECO_PRODUTO} {LINK}',
         titulo="$$ $& $` $' $1 $<x>", preco='$&$&'),
    caso('loja desconhecida e link vazio', '{LOJA}|{LINK}|{TITULO_PRODUTO}', loja='shopee', url=''),
]

_POOL = ['', ' ', '0', '-', '--5%', '-43%', '43%', '\ufeff', '\u200b', 'a\u0085', '\u00a0x\u00a0', '\u2028', '\u3000',
         '$&', "$'", '$`', '$$', '$1', '{CUPOM}', '{LINK}', '{TITULO_PRODUTO}', 'x\n\n\ny', '\t', 'ç😀', 'R$ 1.899,00',
         'Mais de 1 mil', '4,7', '\u180e', '\x1c', '\x85']
_PLACEHOLDERS = ['{LINK}', '{LOJA}', '{TITULO_PRODUTO}', '{PRECO_PRODUTO}', '{PRECO_ANTIGO}', '{DESCONTO_PRODUTO}',
                 '{NUMERO_VENDAS}', '{FRETE}', '{CUPOM}']


def casos_fuzz(n, semente=20261103):
    rng = random.Random(semente)
    saida = []
    for i in range(n):
        linhas = []
        for _ in range(rng.randint(1, 8)):
            partes = [rng.choice(_PLACEHOLDERS + ['texto', '', ' ', '🔥', '*', '\u200b']) for _ in range(rng.randint(0, 3))]
            linhas.append(' '.join(partes))
        dados = {c: rng.choice(_POOL) for c in DADOS_BASE if c != 'imagem'}
        dados['imagem'] = ''
        data = rng.choice([dados, dados, dados, None, {}])
        url = rng.choice([URL_AMZ, 'https://meli.la/AbC', '', '$&x'])
        saida.append({'nome': f'fuzz {i}', 'template': '\n'.join(linhas),
                      'item': {'loja': rng.choice(['amazon', 'ml', 'outra']), 'url': url, 'data': data}})
    return saida


class ParidadeComOBuildMsg(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which('node')
        cls.dir = tempfile.mkdtemp(prefix='achadinhos-paridade-')
        cls.addClassCleanup(shutil.rmtree, cls.dir, ignore_errors=True)

    def no_js(self, casos):
        assert self.node, 'node não está no PATH (a paridade com o buildMsg precisa dele)'
        ent = os.path.join(self.dir, 'casos.json')
        with open(ent, 'w', encoding='utf-8') as f:
            json.dump([{'template': c['template'], 'item': c['item']} for c in casos], f)
        r = subprocess.run([self.node, '-e', JS_PARIDADE, os.path.join(T.RAIZ, 'index.html'), ent],
                           capture_output=True, text=True, timeout=60, encoding='utf-8')
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def confere(self, casos):
        js = self.no_js(casos)
        self.assertEqual(len(js), len(casos))
        for c, esperado in zip(casos, js):
            with self.subTest(c['nome']):
                self.assertEqual(D.montar_mensagem(c['item'], c['template']), esperado)

    def test_ca8_casos_adversariais_batem_com_o_buildmsg_do_index_html(self):
        self.confere(ADVERSARIAIS)

    def test_ca8_adversariais_tem_o_resultado_esperado_nos_pontos_delicados(self):
        """Fixa o resultado literal (e não só 'os dois batem') nos casos em que o trim e o replace diferem."""
        def msg(i):
            return D.montar_mensagem(ADVERSARIAIS[i]['item'], ADVERSARIAIS[i]['template'])
        self.assertEqual(msg(0), 'A\ufeffB\ufeff\n\ufeff\n' + URL_AMZ)   # trim só nas pontas
        self.assertEqual(msg(1), '*\u200b*\n\u200b\n' + URL_AMZ)             # U+200B mantido
        self.assertEqual(msg(2), '12% 3 R$ 10,00\n' + URL_AMZ)               # só o 1º hífen sai
        self.assertEqual(msg(3), URL_AMZ)                                    # desconto "-": linha some

    def test_ca8_fuzz_com_semente_fixa_bate_com_o_buildmsg(self):
        self.confere(casos_fuzz(600))

    def test_ca8_mutante_do_trim_seria_pego(self):
        """O teste tem força: com strip() do Python no lugar do trim do JS, algum caso adversarial diverge."""
        js = self.no_js(ADVERSARIAIS)
        with mock.patch.object(D, '_ESPACOS_JS', None):   # strip(None) = o strip() padrão do Python
            divergiu = [c['nome'] for c, esperado in zip(ADVERSARIAIS, js)
                        if D.montar_mensagem(c['item'], c['template']) != esperado]
        self.assertTrue(divergiu, 'nenhum caso distingue o strip() do trim() do JS')


# ================================================================ CA6: calendário (dia, mês, ano)
class Calendario(T.Base):
    def setUp(self):
        super().setUp()
        self.n = self.numero(limite_diario=40)

    def test_ca6_limite_diario_zera_na_virada_do_dia(self):
        r = self.regra(self.n['id'], horarios=['23:59', '00:01'], dias=[0, 1, 2, 3, 4, 5, 6])
        self.n = D.atualizar_numero(self.con, self.n['id'], {'limite_diario': 1})
        for _ in range(4):
            self.item()
        g = T.Gravador()   # automático: o envio fica "enviado" e continua bloqueando o item na virada
        self.assertEqual(self.tick(hora(T.SEGUNDA, 23, 59), g)['criados'], 1)
        self.assertEqual(self.tick(hora(T.SEGUNDA, 23, 59, 40), g)['criados'], 0, 'mesmo slot')
        terca = T.SEGUNDA + timedelta(days=1)
        self.assertEqual(self.tick(hora(terca, 0, 1), g)['criados'], 1, 'dia novo, contagem nova')
        self.assertEqual(self.tick(hora(terca, 0, 2), g)['criados'], 0)
        self.assertEqual(len({e['item_pk'] for e in self.envios()}), 2, 'e não repete o item de ontem')

    def test_ca6_max_por_dia_zera_na_virada_do_mes(self):
        self.regra(self.n['id'], horarios=['23:58', '00:03'], dias=[0, 1, 2, 3, 4, 5, 6], max_por_dia=1)
        for _ in range(3):
            self.item()
        dia = datetime(2026, 11, 30)   # segunda
        self.assertEqual(self.tick(hora(dia, 23, 58))['criados'], 1)
        self.assertEqual(self.tick(hora(dia, 23, 59, 30))['criados'], 0)
        self.assertEqual(self.tick(datetime(2026, 12, 1, 0, 3, 5))['criados'], 1, '1º de dezembro é outro dia')
        self.assertEqual([e['slot'] for e in self.envios()], ['2026-11-30T23:58', '2026-12-01T00:03'])

    def test_ca5_prazo_de_7_dias_cruza_o_mes_pelo_calendario(self):
        r = self.regra(self.n['id'], horarios=['09:00'], dias=[0, 1, 2, 3, 4, 5, 6], repetir_apos_dias=7)
        pk = self.item()
        self.envio_antigo(r, pk, 'enviado', datetime(2026, 11, 30, 12, 0))
        self.assertEqual(self.tick(datetime(2026, 12, 6, 9, 0))['criados'], 0, '6 dias depois: ainda bloqueado')
        self.assertEqual(self.tick(datetime(2026, 12, 7, 9, 0))['criados'], 1, 'a segunda seguinte volta a valer')

    def test_ca5_prazo_cruza_o_ano(self):
        r = self.regra(self.n['id'], horarios=['09:00'], dias=[0, 1, 2, 3, 4, 5, 6], repetir_apos_dias=3)
        pk = self.item()
        self.envio_antigo(r, pk, 'enviado', datetime(2026, 12, 30, 23, 59))
        self.assertEqual(self.tick(datetime(2027, 1, 1, 9, 0))['criados'], 0)
        self.assertEqual(self.tick(datetime(2027, 1, 2, 9, 0))['criados'], 1)

    def test_ca6_dia_da_semana_domingo_e_sabado(self):
        self.regra(self.n['id'], horarios=['08:00'], dias=[6])
        for _ in range(3):
            self.item()
        self.assertEqual(self.tick(datetime(2026, 11, 7, 8, 0))['criados'], 0, 'sábado não é domingo')
        self.assertEqual(self.tick(datetime(2026, 11, 8, 8, 0))['criados'], 1, 'domingo = 6')

    def test_ca6_slot_perdido_na_virada_do_dia_e_pulado(self):
        """Fixa o plano ('slots de hoje'): 23:55 visto às 00:03 do dia seguinte não é recuperado."""
        self.regra(self.n['id'], horarios=['23:55'], dias=[0, 1, 2, 3, 4, 5, 6])
        self.item()
        self.assertEqual(self.tick(hora(T.SEGUNDA + timedelta(days=1), 0, 3))['criados'], 0)

    def test_ca6_horario_00_00_e_23_59_dentro_da_janela(self):
        self.regra(self.n['id'], horarios=['00:00', '23:59'], dias=[0, 1, 2, 3, 4, 5, 6])
        for _ in range(3):
            self.item()
        self.assertEqual(self.tick(hora(T.SEGUNDA, 0, 0, 0))['criados'], 1)
        self.assertEqual(self.tick(hora(T.SEGUNDA, 23, 59, 59))['criados'], 1)

    def test_proximo_horario_na_virada_do_ano_e_em_ano_bissexto(self):
        base = {'ativa': 1, 'dias': [4], 'horarios': ['09:00']}
        self.assertEqual(D.proximo_horario(base, datetime(2026, 12, 31, 10, 0)), '2027-01-01T09:00')
        todos = {'ativa': 1, 'dias': [0, 1, 2, 3, 4, 5, 6], 'horarios': ['09:00']}
        self.assertEqual(D.proximo_horario(todos, datetime(2028, 2, 28, 23, 0)), '2028-02-29T09:00')
        self.assertEqual(D.proximo_horario(todos, datetime(2028, 2, 29, 23, 0)), '2028-03-01T09:00')
        self.assertEqual(D.proximo_horario({**todos, 'ativa': 0}, datetime(2026, 11, 3)), None)

    def test_proximo_horario_exato_conta_como_proximo_e_semana_seguinte(self):
        r = {'ativa': 1, 'dias': [0], 'horarios': ['09:00', '18:00']}
        self.assertEqual(D.proximo_horario(r, datetime(2026, 11, 2, 9, 0)), '2026-11-02T09:00')
        self.assertEqual(D.proximo_horario(r, datetime(2026, 11, 2, 9, 0, 1)), '2026-11-02T18:00')
        self.assertEqual(D.proximo_horario(r, datetime(2026, 11, 2, 18, 0, 1)), '2026-11-09T09:00')


# ================================================================ CA4, CA5, CA6: seleção e limites
class Selecao(T.Base):
    def setUp(self):
        super().setUp()
        self.n = self.numero(limite_diario=40)

    def slot(self, extra=None, dia=None):
        return hora(dia or T.SEGUNDA, 9, 0)

    def test_ca6_por_disparo_maior_que_elegiveis_cria_so_os_elegiveis_e_o_slot_nao_completa(self):
        self.regra(self.n['id'], por_disparo=5)
        for _ in range(2):
            self.item()
        self.assertEqual(self.tick(self.slot())['criados'], 2)
        for _ in range(3):
            self.item()   # chegaram depois
        self.assertEqual(self.tick(hora(T.SEGUNDA, 9, 5))['criados'], 0, 'horário já processado (CA7)')
        self.assertEqual(len(self.envios()), 2)

    def test_ca6_slot_sem_elegiveis_nao_quebra_e_pega_item_que_chega_dentro_da_janela(self):
        self.regra(self.n['id'])
        self.assertEqual(self.tick(self.slot())['criados'], 0)
        self.item()
        self.assertEqual(self.tick(hora(T.SEGUNDA, 9, 4))['criados'], 1)

    def test_ca6_limite_diario_e_compartilhado_entre_regras_do_mesmo_numero(self):
        D.atualizar_numero(self.con, self.n['id'], {'limite_diario': 3})
        a = self.regra(self.n['id'], nome='A', por_disparo=2, horarios=['09:00'])
        b = self.regra(self.n['id'], nome='B', por_disparo=2, horarios=['09:00'])
        for _ in range(10):
            self.item()
        self.assertEqual(self.tick(self.slot())['criados'], 3)
        self.assertEqual(sorted(len(self.envios(regra_id=r['id'])) for r in (a, b)), [1, 2])
        self.assertEqual(len(D.disparar_agora(self.con, a['id'], hora(T.SEGUNDA, 9, 1), D.TransporteManual(), T.AFILIADO)), 0)
        self.assertEqual(len({e['item_pk'] for e in self.envios()}), 3, 'as duas regras nunca mandam o mesmo item')

    def test_ca6_limite_diario_e_por_numero_e_o_mesmo_item_pode_ir_a_outro_numero(self):
        n2 = self.numero(nome='Loja 2', limite_diario=1)
        D.atualizar_numero(self.con, self.n['id'], {'limite_diario': 1})
        a = self.regra(self.n['id'], horarios=['09:00'], ordem='desconto')
        b = self.regra(n2['id'], horarios=['09:00'], ordem='desconto')
        for _ in range(3):
            self.item()
        self.assertEqual(self.tick(self.slot())['criados'], 2)
        self.assertEqual(self.envios(regra_id=a['id'])[0]['item_pk'], self.envios(regra_id=b['id'])[0]['item_pk'],
                         'o bloqueio de repetição é por número (P3)')

    def test_ca6_max_por_dia_corta_o_por_disparo_no_meio_do_slot(self):
        self.regra(self.n['id'], por_disparo=3, max_por_dia=4, horarios=['09:00', '12:00', '15:00'])
        for _ in range(10):
            self.item()
        total = [self.tick(hora(T.SEGUNDA, h))['criados'] for h in (9, 12, 15)]
        self.assertEqual(total, [3, 1, 0])

    def test_ca5_nulo_bloqueia_item_enviado_ha_400_dias_e_prazo_curto_nao(self):
        r = self.regra(self.n['id'], repetir_apos_dias=None, horarios=['09:00'])
        pk = self.item()
        self.envio_antigo(r, pk, 'enviado', T.SEGUNDA - timedelta(days=400))
        self.assertEqual(self.tick(self.slot())['criados'], 0)
        D.atualizar_regra(self.con, r['id'], {'repetir_apos_dias': 365})
        self.assertEqual(self.tick(hora(T.SEGUNDA, 9, 1))['criados'], 1, 'com prazo de 365 dias, 400 já passou')

    def test_ca5_expirado_erro_e_pulado_nao_bloqueiam_mas_incerto_e_enviando_sim(self):
        r = self.regra(self.n['id'], por_disparo=10, horarios=['09:00'])
        pks = {s: self.item() for s in ('expirado', 'erro', 'pulado', 'incerto', 'enviando', 'enviado', 'pendente')}
        for s, pk in pks.items():
            self.envio_antigo(r, pk, s, T.SEGUNDA.replace(hour=5))   # hoje: pendente de ontem expiraria
        self.assertEqual(self.tick(self.slot())['criados'], 3)
        novos = {e['item_pk'] for e in self.envios() if e['slot'] == '2026-11-02T09:00'}
        self.assertEqual(novos, {pks['expirado'], pks['erro'], pks['pulado']})

    def test_ca4_ml_sem_meli_la_e_amazon_sem_a_tag_nunca_saem(self):
        ruins_ml = ['https://www.mercadolivre.com.br/p/MLB123', 'https://produto.mercadolivre.com.br/MLB-1',
                    'http://meli.la/abc', 'https://meli.la/', 'https://meli.la', 'https://meli.la.evil.com/x',
                    'https://evil.com/meli.la/x', 'https://meli.la@evil.com/x', 'meli.la/abc', ' https://meli.la/abc',
                    'https://meli.la:444/abc', T.url_amz(900)]
        ruins_amz = ['https://www.amazon.com.br/dp/B0X', 'https://www.amazon.com.br/dp/B0X?tag=outra-20',
                     'https://www.amazon.com.br/dp/B0X?tag=desejodemen01-20&tag=outra-20',
                     'https://amazon.com.br/dp/B0X?tag=desejodemen01-20', 'https://amzn.to/abc',
                     'http://www.amazon.com.br/dp/B0X?tag=desejodemen01-20', 'https://meli.la/abc',
                     'https://www.amazon.com.br.evil.com/dp/B0X?tag=desejodemen01-20', '']
        for u in ruins_ml:
            self.item(loja='ml', url=u)
        for u in ruins_amz:
            self.item(loja='amazon', url=u)
        bom_ml, bom_amz = self.item(loja='ml', url='https://meli.la/BOM'), self.item(loja='amazon')
        self.regra(self.n['id'], por_disparo=10, max_por_dia=200, horarios=['09:00'])
        self.assertEqual(self.tick(self.slot())['criados'], 2)
        self.assertEqual({e['item_pk'] for e in self.envios()}, {bom_ml, bom_amz})
        for e in self.envios():
            self.assertTrue(all(T.AFILIADO(u) for u in D.urls_da_mensagem(e['mensagem'])), e['mensagem'])

    def test_ca4_mesma_regra_na_previa_e_no_disparar_agora(self):
        self.item(loja='ml', url='https://www.mercadolivre.com.br/p/MLB123', titulo='Sem afiliado')
        self.item(loja='ml', url='https://meli.la/OK', titulo='Com afiliado')
        r = self.regra(self.n['id'], por_disparo=10)
        pre = D.previa(self.con, {**self.dados_regra(self.n['id']), 'nome': 'p'}, 10, T.SEGUNDA, T.AFILIADO)
        agora = D.disparar_agora(self.con, r['id'], T.SEGUNDA, D.TransporteManual(), T.AFILIADO)
        self.assertEqual([p['titulo'] for p in pre], ['Com afiliado'])
        self.assertEqual([e['titulo'] for e in agora], ['Com afiliado'])

    def test_ca4_item_incompleto_nunca_sai(self):
        for campos in ({'titulo': ''}, {'preco': ''}, {'tem_dados': 0}):
            self.item(**campos)
        bom = self.item()
        self.regra(self.n['id'], por_disparo=10)
        self.tick(self.slot())
        self.assertEqual([e['item_pk'] for e in self.envios()], [bom])

    def test_ca8_foto_so_com_imagem_valida_e_com_foto_ligado(self):
        imagens = {'vazia': '', 'http': 'http://m.media-amazon.com/images/I/a.jpg',
                   'outro host': 'https://evil.com/a.jpg', 'subdominio falso': 'https://m.media-amazon.com.evil.com/a.jpg',
                   'porta': 'https://m.media-amazon.com:444/a.jpg', 'usuario': 'https://x@m.media-amazon.com/a.jpg',
                   'javascript': 'javascript:alert(1)', 'boa': 'https://m.media-amazon.com/images/I/b.jpg',
                   'boa ml': 'https://http2.mlstatic.com/D_NQ_NP_1-F.jpg'}
        for nome, img in imagens.items():
            self.item(titulo=nome, imagem=img)
        r = self.regra(self.n['id'], por_disparo=10, max_por_dia=200, horarios=['09:00'], com_foto=1)
        g = T.Gravador()
        self.tick(self.slot(), transporte=g)
        self.assertEqual(len(g.chamadas), len(imagens))
        for e in self.envios():
            esperado = imagens[e['titulo']] if e['titulo'] in ('boa', 'boa ml') else ''
            self.assertEqual(e['imagem'], esperado, e['titulo'])
        self.assertEqual(sorted(c[2] for c in g.chamadas if c[2]), sorted(imagens[k] for k in ('boa', 'boa ml')))
        self.assertEqual(sum(1 for c in g.chamadas if c[2] is None), len(imagens) - 2, 'sem foto vai None, nunca ""')

    def test_ca8_com_foto_zero_nunca_manda_foto(self):
        self.item()
        self.regra(self.n['id'], com_foto=0)
        g = T.Gravador()
        self.tick(self.slot(), transporte=g)
        self.assertEqual([c[2] for c in g.chamadas], [None])
        self.assertEqual(self.envios()[0]['imagem'], '')

    def test_ca2_template_apagado_da_aviso_nao_envia_e_nao_trava_as_outras_regras(self):
        a = self.regra(self.n['id'], nome='A', template='Template 3', horarios=['09:00'])
        b = self.regra(self.n['id'], nome='B', template='Template 2', horarios=['09:00'])
        for _ in range(3):
            self.item()
        tpl = {k: v for k, v in T.DEFAULT_TEMPLATES.items() if k != 'Template 3'}
        self.gravar_templates(tpl)
        res = self.tick(self.slot())
        self.assertEqual((res['criados'], res['erros']), (1, []))
        self.assertEqual(self.envios()[0]['regra_id'], b['id'])
        aviso = D.obter_regra(self.con, a['id'])['aviso']
        self.assertIn('Template 3', aviso)
        self.assertEqual(D.obter_regra(self.con, b['id'])['aviso'], '')
        self.gravar_templates(T.DEFAULT_TEMPLATES)   # o dono recria o template dentro da janela de 10 min
        self.assertEqual(self.tick(hora(T.SEGUNDA, 9, 1))['criados'], 1, 'a regra A volta no mesmo slot')
        self.assertEqual(D.obter_regra(self.con, a['id'])['aviso'], '')

    def test_ca2_aviso_some_quando_a_regra_volta_a_funcionar(self):
        a = self.regra(self.n['id'], template='Template 3', horarios=['09:00', '10:00'])
        self.item()
        self.gravar_templates({k: v for k, v in T.DEFAULT_TEMPLATES.items() if k != 'Template 3'})
        self.tick(self.slot())
        self.assertNotEqual(D.obter_regra(self.con, a['id'])['aviso'], '')
        self.gravar_templates(T.DEFAULT_TEMPLATES)
        self.assertEqual(self.tick(hora(T.SEGUNDA, 10, 0))['criados'], 1)
        self.assertEqual(D.obter_regra(self.con, a['id'])['aviso'], '')

    def test_ca4_template_editado_depois_para_ter_url_comum_nao_envia_nada(self):
        a = self.regra(self.n['id'], template='Template 2')
        self.item()
        t = dict(T.DEFAULT_TEMPLATES)
        t['Template 2'] = t['Template 2'] + '\nFale comigo: https://evil.com/zap'
        self.gravar_templates(t)
        self.assertEqual(self.tick(self.slot())['criados'], 0)
        self.assertEqual(self.envios(), [])
        t['Template 2'] = T.DEFAULT_TEMPLATES['Template 2'] + '\nwww.evil.com'
        self.gravar_templates(t)
        self.assertEqual(self.tick(hora(T.SEGUNDA, 9, 2))['criados'], 0)

    def test_duas_regras_no_mesmo_slot_e_numero_mandam_itens_diferentes(self):
        a = self.regra(self.n['id'], nome='A', por_disparo=2, horarios=['09:00'])
        b = self.regra(self.n['id'], nome='B', por_disparo=2, horarios=['09:00'])
        for _ in range(6):
            self.item()
        self.assertEqual(self.tick(self.slot())['criados'], 4)
        self.assertEqual(len({e['item_pk'] for e in self.envios()}), 4)
        self.assertEqual([len(self.envios(regra_id=r['id'])) for r in (a, b)], [2, 2])

    def test_tick_repetido_no_mesmo_minuto_nao_duplica(self):
        self.regra(self.n['id'], por_disparo=2)
        for _ in range(5):
            self.item()
        for s in range(0, 60, 3):
            self.tick(hora(T.SEGUNDA, 9, 0, s))
        self.assertEqual(len(self.envios()), 2)

    def test_ca11_disparar_agora_com_numero_desativado_avisa_e_nao_cria(self):
        r = self.regra(self.n['id'])
        self.item()
        D.atualizar_numero(self.con, self.n['id'], {'ativo': 0})
        self.assertEqual(D.rota(self.con, 'POST', f'/api/disparo/regras/{r["id"]}/agora', {}, {}, T.AFILIADO,
                                D.TransporteManual(), agora=T.SEGUNDA), {'criados': 0, 'envios': []})
        self.assertIn('desativado', D.obter_regra(self.con, r['id'])['aviso'])
        self.assertEqual(self.envios(), [])
        D.atualizar_numero(self.con, self.n['id'], {'ativo': 1})
        self.assertEqual(len(D.disparar_agora(self.con, r['id'], T.SEGUNDA + timedelta(seconds=2),
                                              D.TransporteManual(), T.AFILIADO)), 1)
        self.assertEqual(D.obter_regra(self.con, r['id'])['aviso'], '')

    def test_ca11_disparar_agora_fora_do_dia_e_horario_mas_com_regra_pausada_tambem(self):
        r = self.regra(self.n['id'], dias=[6], ativa=0)
        self.item()
        self.assertEqual(len(D.disparar_agora(self.con, r['id'], T.SEGUNDA, D.TransporteManual(), T.AFILIADO)), 1)

    def test_ca11_clique_duplo_no_mesmo_segundo_nao_duplica_e_em_segundos_diferentes_so_manda_itens_novos(self):
        r = self.regra(self.n['id'], por_disparo=2)
        for _ in range(6):
            self.item()
        agora = hora(T.SEGUNDA, 14, 30, 5)
        m, f = D.TransporteManual(), T.AFILIADO
        self.assertEqual(len(D.disparar_agora(self.con, r['id'], agora, m, f)), 2)
        self.assertEqual(len(D.disparar_agora(self.con, r['id'], agora, m, f)), 0)
        self.assertEqual(len(D.disparar_agora(self.con, r['id'], agora + timedelta(seconds=1), m, f)), 2)
        self.assertEqual(len({e['item_pk'] for e in self.envios()}), 4)

    def test_ca11_disparar_agora_respeita_max_por_dia_e_limite_diario(self):
        D.atualizar_numero(self.con, self.n['id'], {'limite_diario': 3})
        r = self.regra(self.n['id'], por_disparo=2, max_por_dia=10)
        for _ in range(8):
            self.item()
        m, f = D.TransporteManual(), T.AFILIADO
        agora = hora(T.SEGUNDA, 14, 0, 0)
        feitos = [len(D.disparar_agora(self.con, r['id'], agora + timedelta(seconds=i), m, f)) for i in range(4)]
        self.assertEqual(feitos, [2, 1, 0, 0])


# ================================================================ CA9, CA10: fila, histórico, prévia
class FilaHistoricoPrevia(T.Base):
    def setUp(self):
        super().setUp()
        self.n = self.numero()
        self.r = self.regra(self.n['id'])

    def novo_envio(self, status, criado_em='2026-11-02T10:00:00', pk=None):
        pk = pk or self.item()
        with self.con:
            cur = self.con.execute(
                'INSERT INTO envios (regra_id, numero_id, item_pk, slot, status, mensagem, transporte, criado_em) '
                'VALUES (?,?,?,?,?,?,?,?)', (self.r['id'], self.n['id'], pk, f's{pk}{status}', status, 'm', 'manual', criado_em))
        return cur.lastrowid

    def test_ca9_status_invalido_em_marcar_envio_da_400_e_nao_muda_nada(self):
        e = self.novo_envio('pendente')
        for st in (None, '', 'enviando', 'expirado', 'erro', 'pendente', 'incerto', 'ENVIADO', 'enviado ', 1, True,
                   ['enviado'], {'a': 1}, 'enviado\n'):
            with self.subTest(status=st):
                with self.assertRaises(D.ErroDisparo) as c:
                    D.marcar_envio(self.con, e, st)
                self.assertEqual(c.exception.codigo, 400)
                self.assertEqual(D.obter_envio(self.con, e)['status'], 'pendente')

    def test_ca9_transicoes_por_status_de_origem(self):
        esperado = {'pendente': (True, True), 'incerto': (True, True), 'erro': (False, True), 'enviado': (False, False),
                    'pulado': (False, False), 'expirado': (False, False), 'enviando': (False, False)}
        for origem, (pode_enviado, pode_pulado) in esperado.items():
            for destino, pode in (('enviado', pode_enviado), ('pulado', pode_pulado)):
                with self.subTest(origem=origem, destino=destino):
                    e = self.novo_envio(origem)
                    if pode:
                        r = D.marcar_envio(self.con, e, destino, T.SEGUNDA)
                        self.assertEqual(r['status'], destino)
                        self.assertEqual(bool(r['enviado_em']), destino == 'enviado')
                    else:
                        with self.assertRaises(D.ErroDisparo) as c:
                            D.marcar_envio(self.con, e, destino)
                        self.assertEqual(c.exception.codigo, 409)
                        self.assertEqual(D.obter_envio(self.con, e)['status'], origem)

    def test_ca9_marcar_enviado_duas_vezes_da_409_e_nao_muda_enviado_em(self):
        e = self.novo_envio('pendente')
        antes = D.marcar_envio(self.con, e, 'enviado', datetime(2026, 11, 2, 10, 5))['enviado_em']
        with self.assertRaises(D.ErroDisparo) as c:
            D.marcar_envio(self.con, e, 'enviado', datetime(2026, 11, 2, 11, 0))
        self.assertEqual(c.exception.codigo, 409)
        self.assertEqual(D.obter_envio(self.con, e)['enviado_em'], antes)

    def test_ca9_id_inexistente_da_404_e_corpo_sem_status_da_400(self):
        with self.assertRaises(D.ErroDisparo) as c:
            D.marcar_envio(self.con, 999, 'enviado')
        self.assertEqual(c.exception.codigo, 404)
        for corpo in ({}, [], 'x', None, {'status': None}):
            with self.subTest(corpo=corpo):
                with self.assertRaises(D.ErroDisparo) as c:
                    D.rota(self.con, 'PATCH', '/api/disparo/envios/1', {}, corpo, T.AFILIADO, D.TransporteManual())
                self.assertEqual(c.exception.codigo, 400)

    def test_ca10_desde_invalido_da_400_nunca_estoura(self):
        for desde in ('2026-13-01', '2026-02-30', '2026-1-1', '26-11-03', '2026-11-03T10:00', '2026/11/03',
                      ' 2026-11-03', '2026-11-03 ', '2026-11-03\n', 'abc', "2026-11-03' OR '1'='1", '٢٠٢٦-١١-٠٣',
                      '0000-00-00', '9999-99-99', '20261103', '2026-11-03;--', 123, ['2026-11-03']):
            with self.subTest(desde=desde):
                with self.assertRaises(D.ErroDisparo) as c:
                    D.listar_envios(self.con, desde)
                self.assertEqual(c.exception.codigo, 400)

    def test_ca10_desde_e_status_validos_e_limites(self):
        self.novo_envio('enviado', '2026-11-02T23:59:59')
        self.novo_envio('enviado', '2026-11-03T00:00:00')
        self.novo_envio('pulado', '2026-11-03T08:00:00')
        self.assertEqual(len(D.listar_envios(self.con, '2026-11-03')), 2, 'o dia inteiro conta')
        self.assertEqual(len(D.listar_envios(self.con, '2026-11-02')), 3)
        self.assertEqual(len(D.listar_envios(self.con, '2026-11-03', 'pulado')), 1)
        self.assertEqual(len(D.listar_envios(self.con, '0001-01-01')), 3)
        self.assertEqual(D.listar_envios(self.con, '9999-12-31'), [])
        self.assertEqual(len(D.listar_envios(self.con, '', '')), 3)
        for status in ('x', 'ENVIADO', 'enviado,pulado', "enviado' OR 1=1", 'enviado ', 5):
            with self.subTest(status=status):
                with self.assertRaises(D.ErroDisparo) as c:
                    D.listar_envios(self.con, None, status)
                self.assertEqual(c.exception.codigo, 400)

    def test_ca10_historico_limitado_a_500_do_mais_novo_ao_mais_antigo(self):
        base = datetime(2026, 11, 1)
        pks = [self.item() for _ in range(520)]
        with self.con:
            self.con.executemany(
                'INSERT INTO envios (regra_id, numero_id, item_pk, slot, status, mensagem, transporte, criado_em) '
                "VALUES (?,?,?,?,'enviado','m','manual',?)",
                [(self.r['id'], self.n['id'], pk, f's{pk}', (base + timedelta(minutes=i)).isoformat(timespec='seconds'))
                 for i, pk in enumerate(pks)])
        h = D.listar_envios(self.con)
        self.assertEqual(len(h), 500)
        self.assertEqual(h[0]['item_pk'], pks[-1])
        self.assertEqual(h[-1]['item_pk'], pks[20])

    def test_ca10_previa_nao_grava_nada_em_nenhuma_tabela(self):
        for _ in range(6):
            self.item()
        antes = instantaneo(self.con)
        for ordem in D.ORDENS:
            for n in (1, 5, 20):
                D.previa(self.con, {**self.dados_regra(self.n['id']), 'nome': 'p', 'ordem': ordem}, n, T.SEGUNDA,
                         T.AFILIADO, random.Random(1))
        D.rota(self.con, 'POST', '/api/disparo/previa', {}, {**self.dados_regra(self.n['id']), 'nome': 'p', 'n': 3},
               T.AFILIADO, D.TransporteManual(), agora=T.SEGUNDA)
        self.assertEqual(instantaneo(self.con), antes)
        self.assertFalse(self.con.in_transaction)

    def test_ca10_previa_invalida_nao_grava_e_nao_vaza_o_template_apagado(self):
        self.item()
        antes = instantaneo(self.con)
        dados = {**self.dados_regra(self.n['id']), 'nome': 'p'}
        for ruim in ({'template': 'Fantasma'}, {'numero_id': 9999}, {'cats': []}, {'ordem': 'x'}, {'horarios': ['9:00']},
                     {'por_disparo': True}):
            with self.subTest(ruim=ruim):
                with self.assertRaises(D.ErroDisparo) as c:
                    D.previa(self.con, {**dados, **ruim}, 3, T.SEGUNDA, T.AFILIADO)
                self.assertEqual(c.exception.codigo, 400)
        for n in (0, 21, -1, True, 1.0, '5', None):
            with self.subTest(n=n):
                with self.assertRaises(D.ErroDisparo) as c:
                    D.previa(self.con, dados, n, T.SEGUNDA, T.AFILIADO)
                self.assertEqual(c.exception.codigo, 400)
        self.assertEqual(instantaneo(self.con), antes)

    def test_ca10_previa_respeita_repeticao_filtros_e_traz_so_afiliado(self):
        feitos = self.item(titulo='Já mandado')
        outro = self.item(titulo='Fone Gamer Bom', desconto='-40%')
        self.item(titulo='Cadeira', desconto='-5%')
        self.envio_antigo(self.r, feitos, 'pendente', T.SEGUNDA)
        base = {**self.dados_regra(self.n['id']), 'nome': 'p'}
        p = D.previa(self.con, {**base, 'palavras': ['FONE'], 'desconto_min': 30}, 10, T.SEGUNDA, T.AFILIADO)
        self.assertEqual([x['item_pk'] for x in p], [outro])
        todas = D.previa(self.con, base, 10, T.SEGUNDA, T.AFILIADO)
        self.assertNotIn(feitos, [x['item_pk'] for x in todas])
        for x in todas:
            self.assertTrue(all(T.AFILIADO(u) for u in D.urls_da_mensagem(x['mensagem'])))

    def test_ca10_previa_so_pelo_corpo_nao_cria_numero_ou_regra_nem_usa_ids_do_corpo(self):
        self.item()
        antes = instantaneo(self.con)
        D.previa(self.con, {**self.dados_regra(self.n['id']), 'nome': 'p', 'id': 77, 'aviso': 'x', 'proximo': 'y'}, 3,
                 T.SEGUNDA, T.AFILIADO)
        self.assertEqual(instantaneo(self.con), antes)


# ================================================================ CA7: enviando vira incerto
class IncertoNoInicio(T.Base):
    def setUp(self):
        super().setUp()
        self.n = self.numero(limite_diario=40)
        self.r = self.regra(self.n['id'], horarios=['09:00'], por_disparo=3)

    def test_ca7_so_enviando_vira_incerto_e_nada_e_reenviado(self):
        pks = {s: self.item() for s in ('enviando', 'enviado', 'pendente', 'erro', 'pulado', 'expirado', 'incerto')}
        for s, pk in pks.items():
            self.envio_antigo(self.r, pk, s, T.SEGUNDA - timedelta(hours=1))
        g = T.Gravador()
        ag = D.Agendador(self.conectar, T.AFILIADO, g, intervalo=3600, relogio=lambda: T.SEGUNDA.replace(hour=20))
        ag.start()
        TD.esperar(lambda: ag.ticks >= 1, 10, 'o primeiro tick')
        ag.parar()
        ag.join(5)
        status = {e['item_pk']: e['status'] for e in self.envios()}
        self.assertEqual(status[pks['enviando']], 'incerto')
        for s in ('enviado', 'pendente', 'erro', 'pulado', 'expirado', 'incerto'):
            if s != 'pendente':
                self.assertEqual(status[pks[s]], s, s)
        self.assertEqual(g.chamadas, [], 'nada foi reenviado ao transporte')

    def test_ca7_incerto_continua_bloqueando_a_repeticao_e_fica_na_fila_ate_o_dono_decidir(self):
        pk = self.item()
        self.envio_antigo(self.r, pk, 'enviando', T.SEGUNDA - timedelta(days=2))
        self.assertEqual(D.marcar_incertos(self.con), 1)
        self.assertEqual(self.tick(T.SEGUNDA.replace(hour=9))['criados'], 0, 'incerto bloqueia o item')
        self.assertEqual([e['status'] for e in D.listar_fila(self.con)], ['incerto'])
        self.tick(T.SEGUNDA + timedelta(days=3))
        self.assertEqual([e['status'] for e in D.listar_fila(self.con)], ['incerto'], 'incerto não expira sozinho')
        D.marcar_envio(self.con, D.listar_fila(self.con)[0]['id'], 'pulado')
        self.assertEqual(self.tick(hora(T.SEGUNDA + timedelta(days=3), 9))['criados'], 1, 'pulado libera o item')

    def test_ca7_marcar_incertos_e_idempotente(self):
        self.envio_antigo(self.r, self.item(), 'enviando', T.SEGUNDA)
        self.assertEqual(D.marcar_incertos(self.con), 1)
        self.assertEqual(D.marcar_incertos(self.con), 0)

    def test_ca7_falha_do_transporte_nao_deixa_enviando_e_so_o_tipo_vai_para_o_motivo(self):
        for _ in range(3):
            self.item()
        formatos = ['+55 (00) 00000-0001', '5500000000001', '55 00 00000 0001', '(00) 00000-0001', '00.00000.0001',
                    'tel:5500000000001', GRUPO_ID, '120363012345678901', '0 0 0 0 0 0 0 0 0 0 1']
        for f in formatos:
            with self.subTest(formato=f):
                g = T.Gravador(erro=D.ErroEnvio(f'falhou para {f}!'))
                with self.con:
                    self.con.execute('DELETE FROM envios')
                self.tick(T.SEGUNDA.replace(hour=9), transporte=g)
                e = self.envios()[0]
                self.assertEqual(e['status'], 'erro')
                self.assertSemDadoPessoal(e['motivo'])
                self.assertNotRegex(e['motivo'], r'\d{8}')
        g = T.Gravador(erro=RuntimeError(f'boom {TELEFONE} {GRUPO_ID}'))
        with self.con:
            self.con.execute('DELETE FROM envios')
        self.tick(T.SEGUNDA.replace(hour=9), transporte=g)
        self.assertEqual([e['motivo'] for e in self.envios()], ['RuntimeError'] * 3)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM envios WHERE status='enviando'").fetchone()[0], 0)

    def test_ca9_falha_do_transporte_nao_conta_no_limite_e_nao_bloqueia_a_repeticao(self):
        D.atualizar_numero(self.con, self.n['id'], {'limite_diario': 1})
        self.item()
        self.tick(T.SEGUNDA.replace(hour=9), transporte=T.Gravador(erro=D.ErroEnvio('x')))
        self.assertEqual(self.envios()[0]['status'], 'erro')
        D.atualizar_regra(self.con, self.r['id'], {'horarios': ['09:00', '10:00']})
        self.assertEqual(self.tick(T.SEGUNDA.replace(hour=10))['criados'], 1)


# ================================================================ rodada 2 do dev: links, tamanho e tetos
class LinksTamanhoETetos(T.Base):
    def setUp(self):
        super().setUp()
        self.n = self.numero(limite_diario=200)
        self.r = self.regra(self.n['id'], por_disparo=10, max_por_dia=200, horarios=['09:00'])

    def rodar(self):
        return self.tick(hora(T.SEGUNDA, 9, 0))['criados']

    def test_ca4_titulo_com_link_ou_dominio_alheio_nunca_sai(self):
        golpes = ['Compre em exemplo.com agora', 'Fale: wa.me/5500000000001', 'veja bit.ly/abc', 'EXEMPLO.COM.BR/oferta',
                  'https://evil.com/x', 'ftp://evil.com', 'evil\u3002com/x', '\uff45\uff56\uff49\uff4c\uff0e\uff43\uff4f\uff4d',
                  'evil\u200b.com', 'https://meli.la/abc\u200b.evil.com', 'http://1.2.3.4/x', '10.0.0.1/x',
                  'www.evil.com', 'aqui:https://evil.com/x', 'outro https://meli.la/OUTROPRODUTO',
                  'https://www.amazon.com.br/dp/B0X?tag=desejodemen01-20']
        for g in golpes:
            self.item(titulo=g)
        bom = self.item(titulo='Fone sem golpe nenhum')
        self.assertEqual(self.rodar(), 1)
        self.assertEqual([e['item_pk'] for e in self.envios()], [bom])

    def test_ca4_falso_positivo_do_titulo_so_tira_o_item_da_fila_e_nao_quebra_os_outros(self):
        """Código de produto com ponto (ex.: "Nx.kzwal.003") parece domínio: o item é pulado, por segurança."""
        self.item(titulo='Acer Nx.kzwal.003')
        bom = self.item(titulo='Notebook sem ponto')
        self.assertEqual(self.rodar(), 1)
        self.assertEqual(self.envios()[0]['item_pk'], bom)

    def test_ca4_link_de_afiliado_de_outro_item_no_titulo_nao_passa(self):
        self.item(titulo='Veja também https://meli.la/OUTRO', loja='ml', url='https://meli.la/MEU')
        self.assertEqual(self.rodar(), 0)

    def test_ca4_mensagem_acima_de_4000_caracteres_e_pulada_e_no_limite_passa(self):
        pk = self.item(titulo='T', loja='ml', url='https://meli.la/X')
        for tamanho, saem in ((4000, 1), (4001, 0)):
            with self.subTest(tamanho=tamanho):
                with self.con:
                    self.con.execute('DELETE FROM envios')
                corpo = '{LINK}'
                cabeca = 'a' * (tamanho - len('https://meli.la/X') - 1)
                tpl = {**T.DEFAULT_TEMPLATES, 'Gigante': cabeca + '\n' + corpo}
                self.gravar_templates(tpl)
                D.atualizar_regra(self.con, self.r['id'], {'template': 'Gigante'})
                msgs = D.previa(self.con, {**self.dados_regra(self.n['id']), 'nome': 'p', 'template': 'Gigante'}, 3,
                                hora(T.SEGUNDA, 9, 0), T.AFILIADO)
                self.assertEqual(len(msgs), saem)
                if saem:
                    self.assertEqual(len(msgs[0]['mensagem']), 4000)

    def test_ca4_campos_cheios_de_cifrao_no_teto_nao_viram_mensagem_gigante(self):
        self.item(titulo='$&' * 250, cupom='$`' * 100, vendas='$$' * 100, frete='$\'' * 100)
        self.rodar()
        for e in self.envios():
            self.assertLessEqual(len(e['mensagem']), 4000)

    def test_ca2_put_parcial_com_template_apagado_funciona_mas_trocar_para_template_inexistente_da_400(self):
        t = {k: v for k, v in T.DEFAULT_TEMPLATES.items() if k != 'Template 2'}
        self.gravar_templates(t)
        self.assertEqual(D.atualizar_regra(self.con, self.r['id'], {'ativa': 0})['ativa'], 0)
        with self.assertRaises(D.ErroDisparo) as c:
            D.atualizar_regra(self.con, self.r['id'], {'template': 'Template 2'})
        self.assertEqual(c.exception.codigo, 400)
        with self.assertRaises(D.ErroDisparo) as c:
            D.criar_regra(self.con, self.dados_regra(self.n['id'], template='Template 2'))
        self.assertEqual(c.exception.codigo, 400)

    def test_ca2_proximo_nulo_com_numero_desativado_e_volta_ao_reativar(self):
        agora = hora(T.SEGUNDA, 8, 0)
        rodar = lambda: D.rota(self.con, 'GET', '/api/disparo/regras', {}, None, T.AFILIADO, D.TransporteManual(),
                               agora=agora)[0]['proximo']
        self.assertEqual(rodar(), '2026-11-02T09:00')
        D.atualizar_numero(self.con, self.n['id'], {'ativo': 0})
        self.assertIsNone(rodar())
        D.atualizar_numero(self.con, self.n['id'], {'ativo': 1})
        self.assertEqual(rodar(), '2026-11-02T09:00')

    def test_ca1_ca2_surrogate_solto_da_400_e_nao_grava(self):
        for dados in ({'nome': 'a\ud800', 'grupo_nome': 'g'}, {'nome': 'a', 'grupo_nome': '\udc00'}):
            with self.subTest(dados=dados):
                with self.assertRaises(D.ErroDisparo) as c:
                    D.criar_numero(self.con, dados)
                self.assertEqual(c.exception.codigo, 400)
        with self.assertRaises(D.ErroDisparo) as c:
            D.criar_regra(self.con, self.dados_regra(self.n['id'], nome='\ud800'))
        self.assertEqual(c.exception.codigo, 400)
        with self.assertRaises(D.ErroDisparo) as c:
            D.criar_regra(self.con, self.dados_regra(self.n['id'], palavras=['\ud800']))
        self.assertEqual(c.exception.codigo, 400)
        self.assertEqual(len(D.listar_numeros(self.con)), 1)

    def test_ca4_tick_com_numero_desativado_nao_grava_aviso_nem_envio(self):
        self.item()
        D.atualizar_numero(self.con, self.n['id'], {'ativo': 0})
        self.assertEqual(self.rodar(), 0)
        self.assertEqual(D.obter_regra(self.con, self.r['id'])['aviso'], '')

    def test_ca9_fila_do_mais_antigo_ao_mais_novo(self):
        pks = [self.item() for _ in range(3)]
        for i, pk in enumerate(reversed(pks)):
            self.envio_antigo(self.r, pk, 'pendente', T.SEGUNDA.replace(hour=1 + i))
        self.assertEqual([e['item_pk'] for e in D.listar_fila(self.con)], list(reversed(pks)))


# ================================================================ servidor: rotas, CA13 e dado pessoal
class QaRotas(TD.ServidorDisparo):
    DISPARO = '0'

    def assertSemDadoPessoal(self, texto):
        """Como o da base, mas sem despejar o log inteiro na falha: mostra só a linha que vazou."""
        for v in (TELEFONE, GRUPO_ID, TELEFONE[-8:], GRUPO_ID.split('@')[0]):
            achadas = [l[:200] for l in str(texto).splitlines() if v in l]
            self.assertEqual(achadas, [], f'{v!r} apareceu na saída')

    def api_bruto(self, metodo, resto, texto_json):
        """Corpo JSON que não é objeto (lista, texto, número), com o Content-Type certo."""
        h = {**self.local(), 'Content-Type': 'application/json'}
        st, _, dados = self.pedir(metodo, '/api/disparo/' + resto, texto_json.encode(), h)
        return st, json.loads(dados)

    def setUp(self):
        with sqlite3.connect(self.db) as con:
            con.executescript('DELETE FROM envios; DELETE FROM regras; DELETE FROM numeros; DELETE FROM items;')
        con.close()
        if os.path.exists(self.jsonl):
            os.remove(self.jsonl)
        self.preparar()

    # --- CA13
    def test_ca13_preflight_do_ml_em_toda_rota_nova_e_metodo_da_403_sem_cors(self):
        n = self.numero()
        rotas = ['numeros', f'numeros/{n["id"]}', 'regras', 'regras/1', 'regras/1/agora', 'previa', 'fila', 'envios',
                 'envios/1', 'status', 'nao-existe']
        for origem in TD.ML:
            for rota in rotas:
                for metodo in ('GET', 'POST', 'PUT', 'PATCH', 'DELETE'):
                    with self.subTest(origem=origem, rota=rota, metodo=metodo):
                        st, h, _ = self.pedir('OPTIONS', '/api/disparo/' + rota, None, {
                            'Origin': origem, 'Access-Control-Request-Method': metodo,
                            'Access-Control-Request-Private-Network': 'true'})
                        self.assertEqual(st, 403)
                        for cab in ('Access-Control-Allow-Origin', 'Access-Control-Allow-Methods',
                                    'Access-Control-Allow-Private-Network'):
                            self.assertIsNone(h.get(cab), cab)

    def test_ca13_origem_do_ml_nao_escreve_nem_le_e_nao_ha_atalho_pelo_caminho(self):
        n = self.numero()
        for origem in TD.ML:
            cab = {'Origin': origem}
            for metodo, caminho, corpo in (
                    ('POST', '/api/disparo/numeros', {'nome': 'x', 'grupo_nome': 'g'}),
                    ('PATCH', '/api/disparo/envios/1', {'status': 'pulado'}),
                    ('PUT', f'/api/disparo/numeros/{n["id"]}', {'nome': 'hack'}),
                    ('DELETE', f'/api/disparo/numeros/{n["id"]}', None),
                    ('GET', '/api/disparo/numeros', None),
                    ('GET', '/api/disparo/numeros?x=/api/items', None),
                    ('GET', '/api/items/../disparo/numeros', None),
                    ('POST', '/api/disparo/regras/1/agora', {}),
                    ('POST', '/api/disparo/previa', {})):
                with self.subTest(origem=origem, metodo=metodo, caminho=caminho):
                    st, h, d = self.pedir(metodo, caminho, corpo, cab)
                    self.assertIn(st, (403, 404))   # 404 só no atalho que nem chega ao disparo
                    self.assertIsNone(h.get('Access-Control-Allow-Origin'))
                    self.assertNotIn(b'Loja 1', d)
        self.assertEqual([x['nome'] for x in self.ok('GET', 'numeros')], ['Loja 1'])
        st, h, _ = self.pedir('OPTIONS', '/api/disparo/numeros', None, {'Origin': self.local()['Origin']})
        self.assertEqual(st, 204)
        self.assertIsNone(h.get('Access-Control-Allow-Origin'), 'a origem local não precisa de CORS')

    def test_ca13_rotas_do_ml_continuam_funcionando_com_o_disparo_no_ar(self):
        for origem in TD.ML:
            st, h, d = self.pedir('GET', '/api/items', None, {'Origin': origem})
            self.assertEqual(st, 200)
            self.assertEqual(h.get('Access-Control-Allow-Origin'), origem)
            st, h, _ = self.pedir('OPTIONS', '/api/items', None, {'Origin': origem, 'Access-Control-Request-Method': 'POST'})
            self.assertEqual(st, 204)

    def test_ca13_host_estranho_da_403_nas_rotas_novas(self):
        for host in ('evil.com', f'evil.com:{self.porta}', f'localhost:{self.porta + 1}'):
            st, _, _ = self.pedir('GET', '/api/disparo/numeros', None, {'Host': host})
            self.assertEqual(st, 403, host)

    # --- validação pela rede: 400 em pt-BR, sem eco do valor, sem gravar
    def test_ca1_ca2_400_nao_ecoa_o_valor_enviado_e_nao_grava(self):
        segredo = '99887766554433'
        for corpo in ({'nome': 'a', 'grupo_nome': 'g', 'telefone': segredo + 'x'},
                      {'nome': 'a', 'grupo_nome': 'g', 'telefone': '1' * 16},
                      {'nome': 'a', 'grupo_nome': 'g', 'grupo_id': segredo + '@g.us.evil'},
                      {'nome': 'a', 'grupo_nome': 'g', 'telefone': int(segredo)},
                      {'nome': 'a', 'grupo_nome': 'g', 'limite_diario': True},
                      {'nome': 'a', 'grupo_nome': 'g', 'limite_diario': 201},
                      {'nome': 'x' * 81, 'grupo_nome': 'g'}, {'grupo_nome': 'g'}):
            with self.subTest(corpo=str(corpo)[:60]):
                st, j = self.api('POST', 'numeros', corpo)
                self.assertEqual(st, 400, j)
                self.assertNotIn(segredo, json.dumps(j))
                self.assertTrue(j['error'])
        for bruto in ('[]', '"texto"', '5', 'null', '[{"nome":"a","grupo_nome":"g"}]'):
            with self.subTest(bruto=bruto):
                st, j = self.api_bruto('POST', 'numeros', bruto)
                self.assertEqual(st, 400, j)
        self.assertEqual(self.ok('GET', 'numeros'), [])

    def test_ca2_regra_invalida_da_400_e_nao_grava(self):
        n = self.numero()
        base = {'nome': 'R', 'numero_id': n['id'], 'cats': ['Eletrônicos'], 'template': 'Template 2', 'horarios': ['09:00']}
        ruins = [{'horarios': ['09:00', '09:00']}, {'horarios': []}, {'horarios': ['24:00']}, {'horarios': ['9:00']},
                 {'horarios': ['09:60']}, {'horarios': [900]}, {'dias': []}, {'dias': [7]}, {'dias': [-1]}, {'dias': [0, 0]},
                 {'dias': [True]}, {'dias': ['1']}, {'por_disparo': 0}, {'por_disparo': 11}, {'por_disparo': True},
                 {'max_por_dia': 0}, {'max_por_dia': 201}, {'repetir_apos_dias': 0}, {'repetir_apos_dias': 366},
                 {'repetir_apos_dias': '7'}, {'intervalo_seg': 29}, {'intervalo_seg': 3601}, {'desconto_min': 96},
                 {'desconto_min': -1}, {'ordem': 'aleatória'}, {'ordem': None}, {'lojas': []}, {'lojas': ['shopee']},
                 {'lojas': ['ml', 'ml']}, {'palavras': ['x'] * 21}, {'palavras': ['y' * 41]}, {'palavras': ['  ']},
                 {'cats': []}, {'cats': ['a'] * 51}, {'cats': [1]}, {'template': 'Fantasma'}, {'template': None},
                 {'numero_id': 9999}, {'numero_id': True}, {'numero_id': '1'}, {'ativa': True}, {'com_foto': 2},
                 {'nome': ''}, {'nome': 'n' * 81}]
        for ruim in ruins:
            with self.subTest(ruim=ruim):
                st, j = self.api('POST', 'regras', {**base, **ruim})
                self.assertEqual(st, 400, j)
        self.assertEqual(self.ok('GET', 'regras'), [])
        self.assertEqual(self.api('POST', 'regras', base)[0], 200)

    def test_put_parcial_ativa_e_repetir_nulo_e_delete_mantem_envios(self):
        n = self.numero()
        r = self.regra(n['id'])
        j = self.ok('PUT', f'regras/{r["id"]}', {'repetir_apos_dias': None})
        self.assertIsNone(j['repetir_apos_dias'])
        self.assertEqual(j['cats'], ['Eletrônicos'], 'o resto fica como estava')
        self.ok('POST', f'regras/{r["id"]}/agora', {})
        self.assertEqual(self.ok('DELETE', f'regras/{r["id"]}'), {'ok': True})
        self.assertEqual(len(self.ok('GET', 'envios')), 1, 'excluir a regra mantém o histórico')
        self.assertEqual(self.api('DELETE', f'regras/{r["id"]}')[0], 404)

    def test_ca10_desde_invalido_pela_rede_da_400_nunca_500(self):
        for q in ('desde=2026-13-01', 'desde=2026-02-30', 'desde=%27%20OR%201%3D1', 'desde=%00', 'desde=2026-11-03%0A',
                  'desde=' + 'x' * 5000, 'status=%00', 'status=enviado%27', 'status=' + 'y' * 3000):
            with self.subTest(q=q[:40]):
                st, j = self.api('GET', 'envios?' + q)
                self.assertEqual(st, 400, j)
        self.assertEqual(self.api('GET', 'envios?desde=&status=')[0], 200)
        self.assertEqual(self.api('GET', 'envios?outro=1')[0], 200)

    def test_ca9_patch_status_invalido_pela_rede(self):
        n = self.numero()
        r = self.regra(n['id'])
        e = self.ok('POST', f'regras/{r["id"]}/agora', {})['envios'][0]
        for corpo in ({'status': 'enviando'}, {'status': ['enviado']}, {'status': None}, {}):
            with self.subTest(corpo=corpo):
                self.assertEqual(self.api('PATCH', f'envios/{e["id"]}', corpo)[0], 400)
        for bruto in ('[]', '"x"', 'null', '7'):
            with self.subTest(bruto=bruto):
                self.assertEqual(self.api_bruto('PATCH', f'envios/{e["id"]}', bruto)[0], 400)
        self.assertEqual(self.api('PATCH', f'envios/{e["id"]}', {'status': 'pulado'})[0], 409, 'já enviado pelo falso')

    def test_ca8_foto_segue_so_com_com_foto_e_imagem(self):
        n = self.numero()
        st, _, _ = self.postar([{'loja': 'amazon', 'item_id': 'B0SEMFOTO1', 'cat': 'Eletrônicos',
                                 'url': 'https://www.amazon.com.br/dp/B0SEMFOTO1?tag=desejodemen01-20',
                                 'data': {'titulo': 'Sem foto', 'preco': 'R$ 5,00', 'desconto': '-99%'}}], self.local())
        self.assertEqual(st, 200)
        r = self.regra(n['id'], por_disparo=10, ordem='desconto')
        self.ok('POST', f'regras/{r["id"]}/agora', {})
        linhas = {l['texto'].split('\n')[2]: l['imagem_url'] for l in self.linhas_jsonl()}
        self.assertEqual(len(linhas), 4)
        self.assertIsNone(linhas['*Sem foto*'])
        self.assertTrue(all(v and v.startswith('https://m.media-amazon.com/') for k, v in linhas.items() if k != '*Sem foto*'))
        self.ok('PUT', f'regras/{r["id"]}', {'com_foto': 0})
        os.remove(self.jsonl)
        time.sleep(1.1)   # outro segundo para o slot "agora"
        self.assertEqual(self.ok('POST', f'regras/{r["id"]}/agora', {})['criados'], 0, 'os 4 itens já foram')

    def test_ca4_teto_dos_campos_do_item_na_gravacao_titulo_500_e_demais_200(self):
        """O teto impede que o disparo monte mensagem enorme: a API recusa o item (400) e não grava nada do lote."""
        def item(i, **dados):
            return {'loja': 'amazon', 'item_id': f'B0TETO{i:05d}', 'cat': 'Eletrônicos',
                    'url': f'https://www.amazon.com.br/dp/B0TETO{i:05d}?tag=desejodemen01-20',
                    'data': {'titulo': 'T', 'preco': 'R$ 1,00', **dados}}
        antes = len(self.itens())
        for i, (campo, lim) in enumerate((('titulo', 500), ('preco', 200), ('frete', 200), ('cupom', 200),
                                          ('vendas', 200), ('preco_antigo', 200), ('imagem', 200))):
            with self.subTest(campo=campo):
                st, _, _ = self.postar([item(i * 2, **{campo: 'x' * lim})], self.local())
                self.assertEqual(st, 200, 'no teto passa')
                st, _, d = self.postar([item(i * 2 + 1, **{campo: 'x' * (lim + 1)}), item(900 + i)], self.local())
                self.assertEqual(st, 400, d)
                self.assertNotIn(b'B0TETO00900', json.dumps([x['item_id'] for x in self.itens()]).encode())
        self.assertEqual(len(self.itens()), antes + 7)

    # --- concorrência pela rede
    def test_ca11_cliques_simultaneos_em_disparar_agora_nao_duplicam_item_nem_estouram_o_limite(self):
        n = self.numero()
        self.ok('PUT', f'numeros/{n["id"]}', {'limite_diario': 2})
        r = self.regra(n['id'], por_disparo=1)
        with sqlite3.connect(self.db) as con:
            con.executescript("INSERT OR IGNORE INTO config VALUES ('x','1')")
        con.close()
        resultados, barreira = [], threading.Barrier(4)

        def clicar():
            barreira.wait()
            resultados.append(self.api('POST', f'regras/{r["id"]}/agora', {}))
        ts = [threading.Thread(target=clicar) for _ in range(4)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(30)
        self.assertEqual([st for st, _ in resultados], [200] * 4, resultados)
        envios = self.ok('GET', 'envios')
        self.assertLessEqual(len(envios), 2, 'limite_diario = 2')
        self.assertEqual(len({e['item_pk'] for e in envios}), len(envios), 'item repetido')
        self.assertEqual(len(self.linhas_jsonl()), len(envios))

    # --- dado pessoal
    def test_ca1_telefone_e_grupo_nunca_na_saida_nem_em_resposta_de_envios(self):
        n = self.numero()
        r = self.regra(n['id'])
        self.ok('POST', f'regras/{r["id"]}/agora', {})
        st, j = self.api('PUT', f'numeros/{n["id"]}', {'telefone': 'abc' + TELEFONE})
        self.assertEqual(st, 400)
        self.assertSemDadoPessoal(json.dumps(j))
        st, j = self.api('POST', 'numeros', {'nome': 'z', 'grupo_nome': 'g', 'grupo_id': GRUPO_ID + 'x'})
        self.assertEqual(st, 400)
        self.assertSemDadoPessoal(json.dumps(j))
        for rota in ('regras', 'fila', 'envios', 'status', 'previa'):
            st, j = self.api('POST' if rota == 'previa' else 'GET', rota, {} if rota == 'previa' else None)
            self.assertSemDadoPessoal(json.dumps(j))
        self.assertSemDadoPessoal(self.saida())
        with open(self.jsonl, encoding='utf-8') as f:
            self.assertSemDadoPessoal(f.read())


# ================================================================ servidor: partida, variáveis e reinício
class Partida(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix='achadinhos-disparo-qa-')
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.db = os.path.join(self.dir, 'x.db')
        self.porta = TS.porta_livre()
        self.procs = []
        self.addCleanup(self.matar)

    def env(self, **extra):
        env = TS.ambiente(self.db, self.porta)
        for k in TD.VARS_DISPARO:
            env.pop(k, None)
        env['ACHADINHOS_TRANSPORTE'] = 'falso'
        env['ACHADINHOS_TRANSPORTE_ARQUIVO'] = os.path.join(self.dir, 'e.jsonl')
        env.update(extra)
        return env

    def subir(self, **extra):
        p = subprocess.Popen([sys.executable, '-u', 'servidor.py'], cwd=TS.RAIZ, env=self.env(**extra),
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.procs.append(p)
        return p

    def matar(self):
        for p in self.procs:
            if p.poll() is None:
                p.kill()
            p.wait()
            p.stdout.close()
            p.stderr.close()

    def esperar_porta(self, p, segundos=10):
        fim = time.monotonic() + segundos
        while time.monotonic() < fim:
            try:
                socket.create_connection(('127.0.0.1', self.porta), timeout=0.2).close()
                return True
            except OSError:
                if p.poll() is not None:
                    return False
                time.sleep(0.05)
        return False

    def test_tick_seg_fora_da_faixa_derruba_a_partida_e_libera_a_porta(self):
        for valor in ('0', '0.05', '0.099', '3600.5', '3601', '-1', 'nan', 'inf', '-inf', 'abc', '1e400', '1,5', '30s'):
            with self.subTest(valor=valor):
                self.porta = TS.porta_livre()
                p = self.subir(ACHADINHOS_TICK_SEG=valor)
                try:
                    saida, erro = p.communicate(timeout=20)
                except subprocess.TimeoutExpired:
                    self.fail(f'ACHADINHOS_TICK_SEG={valor} não derrubou o servidor')
                self.assertNotEqual(p.returncode, 0)
                self.assertIn('ACHADINHOS_TICK_SEG', erro)
                with socket.socket() as s:   # a porta não ficou presa pelo processo que morreu
                    s.bind(('127.0.0.1', self.porta))

    def test_tick_seg_nos_limites_sobe_e_o_status_fica_ligado(self):
        for valor in ('0.1', '3600', '30', ' 5 '):
            with self.subTest(valor=valor):
                self.porta = TS.porta_livre()
                p = self.subir(ACHADINHOS_TICK_SEG=valor)
                self.assertTrue(self.esperar_porta(p), f'não subiu com {valor!r}')
                p.kill()
                p.wait()

    def test_segunda_instancia_na_mesma_porta_nao_mexe_nos_envios_da_primeira(self):
        """O bind vem antes do agendador (plano): a instância que perde a porta não marca 'enviando' como 'incerto'."""
        a = self.subir(ACHADINHOS_DISPARO='0')
        self.assertTrue(self.esperar_porta(a))
        with sqlite3.connect(self.db) as con:
            con.execute("INSERT INTO envios (regra_id, numero_id, item_pk, slot, status, mensagem, transporte, criado_em)"
                        " VALUES (1,1,1,'s','enviando','m','falso','2026-11-03T10:00:00')")
        con.close()
        b = self.subir(ACHADINHOS_DISPARO='1', ACHADINHOS_TICK_SEG='1')
        b.communicate(timeout=20)
        self.assertNotEqual(b.returncode, 0, 'a porta está ocupada')
        with sqlite3.connect(self.db) as con:
            st = con.execute('SELECT status FROM envios').fetchone()[0]
        con.close()
        self.assertEqual(st, 'enviando')

    def test_disparo_0_e_valores_estranhos_da_variavel(self):
        for valor, ligado in (('0', False), (' 0 ', False), ('1', True), ('', True), ('sim', True)):
            with self.subTest(valor=valor):
                self.porta = TS.porta_livre()
                p = self.subir(ACHADINHOS_DISPARO=valor, ACHADINHOS_TICK_SEG='1')
                self.assertTrue(self.esperar_porta(p))
                st, _, d = self.chamar('/api/disparo/status')
                self.assertEqual(json.loads(d)['agendador'], 'ligado' if ligado else 'desligado')
                p.kill()
                p.wait()

    def chamar(self, caminho):
        import http.client
        con = http.client.HTTPConnection('127.0.0.1', self.porta, timeout=10)
        try:
            con.request('GET', caminho, headers={'Host': f'localhost:{self.porta}'})
            r = con.getresponse()
            return r.status, r.headers, r.read()
        finally:
            con.close()


class ReinicioComRegraNoMinuto(TD.ServidorDisparo):
    """TICK_SEG=1 e transporte falso: o agendador cria o envio no minuto da regra e o reinício não repete."""

    def test_ca7_ca9_reinicio_varias_vezes_nao_reenvia_e_a_fila_manual_nao_e_afetada(self):
        agora = datetime.now()
        if (agora.hour, agora.minute) == (23, 59) and agora.second > 40:
            time.sleep(25)
            agora = datetime.now()
        self.preparar()
        n = self.numero()
        r = self.regra(n['id'], horarios=[agora.strftime('%H:%M')], por_disparo=2)
        linhas = TD.esperar(lambda: len(self.linhas_jsonl()) == 2 and self.linhas_jsonl(), desc='2 envios no JSONL')
        self.assertEqual(len(linhas), 2)
        for _ in range(2):
            self.parar_servidor()
            self.subir()
            primeiro = TD.esperar(lambda: self.ok('GET', 'status')['ultimo_tick'], desc='tick depois do reinício')
            TD.esperar(lambda: self.ok('GET', 'status')['ultimo_tick'] != primeiro or None, desc='outro tick')
        self.assertEqual(len(self.linhas_jsonl()), 2, 'três partidas, dois envios')
        self.assertEqual(len(self.ok('GET', 'envios')), 2)
        saida = self.saida()
        self.assertSemDadoPessoal(saida)
        self.assertNotIn(TELEFONE[-6:], saida)


if __name__ == '__main__':
    unittest.main()
