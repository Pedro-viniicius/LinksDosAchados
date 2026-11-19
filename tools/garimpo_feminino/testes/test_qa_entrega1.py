#!/usr/bin/env python3
"""Testes de QA da entrega 1 do garimpo feminino (etapas 1 a 7: CA3, CA4, CA5, CA7, CA8 e CA9). Sem rede.

Rodar: python3 tools/garimpo_feminino/testes/test_qa_entrega1.py -v
(com os proxies em 127.0.0.1:9; o `comum` já os aponta para lá e troca a pasta de dados por uma temporária)

Foco: as costuras entre os módulos, que cada dev testou isoladamente. Tudo passa pelo `Cliente` real, pelo
`banco` real e pelo `garimpo.main` (ou por subprocesso), com a Open API trocada por falsos. O `socket` fica
proibido no módulo inteiro (CA9). Matriz CA -> teste no relatório do QA.

Como a fase `garimpar` ainda não existe (etapa 14), o teste injeta uma fase `fase_qa_garimpar` com o formato do
contrato (`configurar(parser)` e `rodar(args, ctx)`) que liga `Contexto` -> `motor.parametros` ->
`motor.garimpar_categoria`, e assim prova o encaixe do `achados.json`, do `categorias.json` e do `nichos.json`.
"""
import contextlib
import hashlib
import io
import json
import os
import re
import signal
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import types
import unittest
import zlib
from unittest import mock

import comum  # noqa: F401  (isolamento: tem de vir antes dos módulos do garimpo)
from comum import APP_ID, CS, LINK, S, SECRET, ApiFalsa, Resp, erro, http_erro, no, resposta

import banco  # noqa: E402
import cliente as K  # noqa: E402
import consultas as C  # noqa: E402
import foco  # noqa: E402
import fase_reconhecer as R  # noqa: E402
import garimpo as G  # noqa: E402
import motor as M  # noqa: E402
from test_reconhecer import MEDICOES_PADRAO, ApiRoteada  # noqa: E402

PASTA = comum.PASTA
RAIZ = comum.RAIZ
CAT = 100420
NOME_FASE = 'fase_qa_garimpar'
ARQ_ESTE = os.path.abspath(__file__)

_instantaneo_pasta = None
_patch_rede = []


def _sem_rede(*a, **k):
    raise AssertionError('o teste tentou abrir uma conexão de rede')


def setUpModule():
    """CA9: nenhuma conexão de rede é possível neste módulo (o que sairia seria um bug do teste ou do produto)."""
    global _instantaneo_pasta
    for alvo in ('socket.socket.connect', 'socket.socket.connect_ex', 'socket.create_connection',
                 'socket.getaddrinfo'):
        p = mock.patch(alvo, _sem_rede)
        p.start()
        _patch_rede.append(p)
    _instantaneo_pasta = sorted(os.listdir(PASTA))


def tearDownModule():
    for p in _patch_rede:
        p.stop()
    # CA8: nem o achadinhos.db temporário nem o feitos-shopee foram criados; a pasta real do garimpo ficou igual
    for sufixo in ('', '-wal', '-shm', '-journal'):
        assert not os.path.exists(S.DB + sufixo), 'o garimpo abriu o achadinhos.db'
    assert not os.path.exists(CS.FEITOS), 'o garimpo gravou o progresso da coleta da Shopee'
    sobra = [n for n in sorted(os.listdir(PASTA)) if n != '__pycache__'
             and n not in (_instantaneo_pasta or [])]
    assert not sobra, f'os testes deixaram arquivos na pasta real do garimpo: {sobra}'


# ---------------------------------------------------------------------------------------------------------
# API falsa do catálogo: responde pelas variáveis, de forma determinística (igual em qualquer processo)
# ---------------------------------------------------------------------------------------------------------
def sem_deslocamento(v):
    return 0


class ApiCatalogo:
    """Catálogo de `total` produtos; cada consulta enxerga os ids a partir de `deslocamento(variaveis) + 1`.
    `gancho(n, variaveis)` roda antes de responder (n = número do pedido, 1 a N): devolve None (segue), uma
    exceção (levantada), um dict ou bytes (resposta). Guarda os pedidos como o `comum.ApiFalsa`."""

    def __init__(self, *, total=20, deslocamento=sem_deslocamento, gancho=None):
        self.total, self.deslocamento, self.gancho = total, deslocamento, gancho
        self.pedidos, self.timeouts = [], []

    def __call__(self, req, timeout=None):
        self.pedidos.append(req)
        self.timeouts.append(timeout)
        variaveis = json.loads(req.data)['variables']
        if self.gancho is not None:
            r = self.gancho(len(self.pedidos), variaveis)
            if isinstance(r, BaseException):
                raise r
            if r is not None:
                return Resp(r if isinstance(r, bytes) else json.dumps(r).encode())
        return Resp(json.dumps(self.resposta(variaveis)).encode())

    def resposta(self, v):
        limite, pagina = v['limit'], v['page']
        inicio = (pagina - 1) * limite
        base = self.deslocamento(v)
        nos = [no(base + inicio + i + 1, productName=f'Vestido modelo {base + inicio + i + 1}')
               for i in range(limite) if inicio + i < self.total]
        return resposta(nos, tem_proxima=pagina * limite < self.total, pagina=pagina)

    def corpos(self):
        return [json.loads(p.data) for p in self.pedidos]

    def variaveis(self):
        return [c['variables'] for c in self.corpos()]


def deslocar_por_sort(v):
    """Cada sortType enxerga ids totalmente diferentes (nenhuma consulta satura)."""
    return (v.get('sortType', 1) - 1) * 1000 + (500 if 'isAMSOffer' in v else 0) + (700 if 'isKeySeller' in v else 0)


def deslocar_por_keyword(v):
    """Fatiamento por keyword: ids novos a cada palavra."""
    if 'keyword' in v:
        return 10_000 + (zlib.crc32(v['keyword'].encode()) % 5000) * 100
    return deslocar_por_sort(v)


# ---------------------------------------------------------------------------------------------------------
# a fase injetada (formato do contrato) e a rodada em processo
# ---------------------------------------------------------------------------------------------------------
def _configurar_fase_qa(parser):
    parser.add_argument('--cat', type=int, default=CAT)


def _rodar_fase_qa(args, ctx):
    """O que a `fase_garimpar.py` fará: achados -> parâmetros do motor; categorias.json -> nicho -> sementes."""
    nicho = ctx.categorias.get(str(args.cat), {}).get('nicho')
    sementes = M.sementes_do_nicho(nicho) if nicho else []
    parada = M.garimpar_categoria(ctx.con, ctx.cliente, args.cat, ctx.achados['estrategias'], sementes=sementes,
                                  log=ctx.log, **M.parametros(ctx.achados))
    ctx.log(f'categoria {args.cat}: parada {parada}.')
    return 0


def _modulo_fase_qa():
    modulo = types.ModuleType(NOME_FASE)
    modulo.configurar, modulo.rodar = _configurar_fase_qa, _rodar_fase_qa
    return modulo


def logs_de(pasta):
    pasta_logs = os.path.join(pasta, 'logs')
    return sorted(os.listdir(pasta_logs)) if os.path.isdir(pasta_logs) else []


def ler(pasta, relativo):
    with open(os.path.join(pasta, relativo), encoding='utf-8') as f:
        return f.read()


class Rodada:
    def __init__(self, codigo, out, err, api, esperas, pasta, antes):
        self.codigo, self.out, self.err, self.api, self.esperas, self.pasta = codigo, out, err, api, esperas, pasta
        self.antes = set(antes)

    @property
    def banco(self):
        return os.path.join(self.pasta, 'garimpo.db')

    @property
    def log(self):
        novos = [n for n in logs_de(self.pasta) if n not in self.antes]
        assert len(novos) == 1, novos
        return ler(self.pasta, os.path.join('logs', novos[0]))

    def linhas(self, sql, *args):
        con = sqlite3.connect(f'file:{self.banco}?mode=ro', uri=True)
        try:
            return con.execute(sql, args).fetchall()
        finally:
            con.close()


def arquivar(pasta, achados, categorias):
    arq_achados, arq_cat = os.path.join(pasta, 'achados-teste.json'), os.path.join(pasta, 'categorias-teste.json')
    for caminho, dados in ((arq_achados, achados), (arq_cat, categorias)):
        if dados is not None:
            with open(caminho, 'w', encoding='utf-8') as f:
                json.dump(dados, f)
        elif os.path.exists(caminho):
            os.remove(caminho)
    return arq_achados, arq_cat


ACHADOS_PEQUENOS = {'limit': 5, 'teto_pagina': 100, 'pausa': 0.5}


def garimpar(argv=(), *, pasta=None, api=None, achados=None, categorias=None, subcomando='garimpar',
             segredo=SECRET):
    """`garimpo.main([garimpar, ...])` com a fase injetada, credencial falsa só no ambiente da chamada e a rede
    trocada por falsos. Os achados padrão são pequenos (limit 5) para o catálogo de 20 produtos dar 4 páginas."""
    pasta = pasta or comum.nova_pasta()
    achados = dict(ACHADOS_PEQUENOS) if achados is None else achados
    arq_achados, arq_cat = arquivar(pasta, achados, categorias)
    antes = logs_de(pasta)
    api = api if api is not None else ApiCatalogo()
    env = {'ACHADINHOS_GARIMPO_DIR': pasta, 'ACHADINHOS_SHOPEE_APP_ID': APP_ID}
    if segredo is not None:
        env['ACHADINHOS_SHOPEE_SECRET'] = segredo
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.dict(os.environ, env), mock.patch.dict(sys.modules, {NOME_FASE: _modulo_fase_qa()}), \
            mock.patch.dict(G.SUBCOMANDOS, {'garimpar': NOME_FASE}), \
            mock.patch.object(G, 'ACHADOS', arq_achados), mock.patch.object(G, 'CATEGORIAS', arq_cat), \
            comum.isolado(api) as (api, _, esperas), \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        codigo = G.main([subcomando, *argv])
    return Rodada(codigo, out.getvalue(), err.getvalue(), api, esperas, pasta, antes)


def foto(pasta):
    """O que a rodada deixou no banco, sem datas nem ids de requisição: para comparar duas histórias."""
    con = sqlite3.connect(f'file:{os.path.join(pasta, "garimpo.db")}?mode=ro', uri=True)
    try:
        return {
            'produtos': con.execute('SELECT item_id, shop_id, nome, sales FROM products ORDER BY item_id').fetchall(),
            'consultas': con.execute('SELECT chave, fase, estrategia, cat_id, ultima_pagina, status, vistos, novos '
                                     'FROM consultas ORDER BY chave').fetchall(),
            'fontes': con.execute('SELECT s.item_id, c.chave, s.pagina, s.posicao FROM product_sources s '
                                  'JOIN consultas c ON c.id = s.consulta_id ORDER BY 1, 2').fetchall(),
            'categorias': con.execute('SELECT cat_id, saturada, bateu_teto, parada FROM categories '
                                      'ORDER BY cat_id').fetchall(),
            'paginas': con.execute('SELECT c.chave, r.pagina, r.n_nos, r.novos FROM requisicoes r '
                                   'JOIN consultas c ON c.id = r.consulta_id WHERE r.novos IS NOT NULL '
                                   'ORDER BY 1, 2').fetchall(),
        }
    finally:
        con.close()


def contar(pasta, sql, *args):
    con = sqlite3.connect(f'file:{os.path.join(pasta, "garimpo.db")}?mode=ro', uri=True)
    try:
        return con.execute(sql, args).fetchall()
    finally:
        con.close()


class Base(unittest.TestCase):
    def sem_vazamento(self, pasta, *textos):
        """CA5: nem o Secret, nem a assinatura, nem o cabeçalho Authorization em saída, log, banco, wal ou docs."""
        tudo = comum.conteudo_da_pasta(pasta)
        for proibido in (SECRET.encode(), b'Signature=', b'SHA256 Credential', b'Traceback'):
            self.assertNotIn(proibido, tudo)
        for texto in textos:
            for proibido in (SECRET, 'Signature=', 'SHA256 Credential', 'Traceback'):
                self.assertNotIn(proibido, texto)

    def ultima_linha(self, rodada):
        return rodada.log.rstrip('\n').split('\n')[-1]

    def fechou_certo(self, rodada):
        """CA7: a última linha do log é `SAIDA=<código devolvido>`."""
        self.assertEqual(self.ultima_linha(rodada), f'SAIDA={rodada.codigo}')

    def orcamento_bate(self, rodada_ou_pasta, total_pedidos):
        """O que o banco chama de requisição é exatamente o que saiu para a API (o teto e o ja_feitas confiam nisso)."""
        pasta = getattr(rodada_ou_pasta, 'pasta', rodada_ou_pasta)
        self.assertEqual(contar(pasta, 'SELECT COUNT(*) FROM requisicoes')[0][0], total_pedidos)


def assinatura_confere(testcase, pedidos):
    """Oráculo independente (não usa CS.assinar): sha256(AppId + ts + corpo + Secret), como diz o brief."""
    for req in pedidos:
        corpo = req.data.decode('ascii')   # ensure_ascii: acento vira \uXXXX, então o corpo é ASCII puro
        m = re.fullmatch(r'SHA256 Credential=(\d+), Timestamp=(\d+), Signature=([0-9a-f]{64})',
                         req.get_header('Authorization'))
        testcase.assertIsNotNone(m, req.get_header('Authorization'))
        esperada = hashlib.sha256((m.group(1) + m.group(2) + corpo + SECRET).encode('utf-8')).hexdigest()
        testcase.assertEqual(m.group(3), esperada)
        testcase.assertEqual(m.group(1), APP_ID)
        testcase.assertEqual(req.full_url, comum.URL_FIXA)
        testcase.assertEqual(req.get_method(), 'POST')


# ---------------------------------------------------------------------------------------------------------
# CA3 e CA7: o motor ligado ao Cliente real, ao banco real e ao garimpo.main
# ---------------------------------------------------------------------------------------------------------
class TestGarimparFimAFim(Base):
    """CA3 (roda até saturar, ou a parada fica documentada por categoria) e CA7 (saídas e log)."""

    def test_satura_documenta_a_parada_e_a_segunda_rodada_nao_pede_nada(self):
        r = garimpar()
        self.assertEqual(r.codigo, 0, r.err)
        # sort 1 traz as 4 páginas; as outras 4 ordens e o AMS (3 páginas cada, 3 sem novo) fecham a janela de 5
        self.assertEqual(len(r.api.pedidos), 4 + 4 * 3 + 3)
        self.orcamento_bate(r, 19)
        self.assertEqual(r.linhas('SELECT cat_id, saturada, bateu_teto, parada FROM categories'),
                         [(str(CAT), 1, 0, M.PARADA['saturada'])])
        self.assertEqual(r.linhas('SELECT COUNT(*) FROM products'), [(20,)])
        self.assertIn('parada saturada', r.out)
        self.fechou_certo(r)
        self.sem_vazamento(r.pasta, r.out, r.err)
        # segunda rodada: tudo encerrado, nenhum pedido, mesma resposta
        antes = foto(r.pasta)
        r2 = garimpar(pasta=r.pasta)
        self.assertEqual(r2.codigo, 0)
        self.assertEqual(r2.api.pedidos, [])
        self.assertEqual(foto(r.pasta), antes)
        self.orcamento_bate(r, 19)

    def test_bate_o_teto_de_pagina_e_documenta(self):
        r = garimpar(achados={**ACHADOS_PEQUENOS, 'teto_pagina': 2, 'estrategias': ['sort']})
        self.assertEqual(r.codigo, 0, r.err)
        self.assertEqual(len(r.api.pedidos), 5 * 2)
        self.assertEqual(r.linhas('SELECT cat_id, saturada, bateu_teto, parada FROM categories'),
                         [(str(CAT), 0, 1, M.PARADA['teto'])])
        self.assertEqual({s for (s,) in r.linhas('SELECT status FROM consultas')}, {'teto'})
        self.fechou_certo(r)

    def test_esgota_sem_saturar_e_documenta(self):
        r = garimpar(api=ApiCatalogo(deslocamento=deslocar_por_sort), achados={**ACHADOS_PEQUENOS,
                                                                               'estrategias': ['sort']})
        self.assertEqual(r.codigo, 0, r.err)
        self.assertEqual(len(r.api.pedidos), 5 * 4)
        self.assertEqual(r.linhas('SELECT cat_id, saturada, bateu_teto, parada FROM categories'),
                         [(str(CAT), 0, 0, M.PARADA['esgotada'])])
        self.assertEqual(r.linhas('SELECT COUNT(*) FROM products'), [(100,)])
        self.fechou_certo(r)

    def test_estrategias_do_achados_chegam_ao_motor_na_ordem_pedida(self):
        r = garimpar(api=ApiCatalogo(deslocamento=deslocar_por_sort),
                     achados={**ACHADOS_PEQUENOS, 'estrategias': ['ams_keyseller', 'listtype', 'sort'],
                              'paginas_sem_novo': 1, 'list_types': [3, 4]})
        self.assertEqual(r.codigo, 0, r.err)
        chaves = [v for v in r.api.variaveis() if v['page'] == 1]
        self.assertEqual([(('isAMSOffer' in v), ('isKeySeller' in v), v.get('listType'), v.get('sortType'))
                          for v in chaves],
                         [(True, False, None, None), (False, True, None, None), (False, False, 4, None),
                          (False, False, 3, None)] + [(False, False, None, s) for s in range(1, 6)])
        self.assertTrue(all(isinstance(v['matchId'], str) for v in chaves if 'matchId' in v), 'Int64: texto')
        self.assertTrue(all(isinstance(v['productCatId'], int) for v in chaves if 'productCatId' in v),
                        'productCatId é Int na tabela de tipos: segue número')

    def test_int64_numero_do_achados_vira_numero_no_corpo(self):
        r = garimpar(achados={**ACHADOS_PEQUENOS, 'int64': 'numero', 'estrategias': ['listtype'], 'list_types': [4]})
        self.assertEqual(r.codigo, 0, r.err)
        v = r.api.variaveis()[0]
        self.assertEqual((v['listType'], v['matchId']), (4, CAT))
        self.assertIsInstance(v['matchId'], int)

    def test_cada_pedido_do_motor_sai_assinado_sobre_o_corpo_exato(self):
        r = garimpar(api=ApiCatalogo(deslocamento=deslocar_por_sort))
        self.assertEqual(r.codigo, 0, r.err)
        assinatura_confere(self, r.api.pedidos)
        self.assertEqual(set(r.api.timeouts), {CS.TIMEOUT})
        for c in r.api.corpos():
            self.assertEqual(set(c), {'query', 'variables'})
            self.assertEqual(c['query'], C.CONSULTA_PRODUTOS)   # a constante, nunca um valor embutido
            self.assertEqual(set(c['variables']) - {'productCatId', 'sortType', 'page', 'limit', 'isAMSOffer',
                                                    'isKeySeller'}, set())

    def test_o_ritmo_do_achados_vale_entre_os_pedidos(self):
        r = garimpar(achados={**ACHADOS_PEQUENOS, 'pausa': 2.0, 'estrategias': ['sort']})
        self.assertEqual(r.codigo, 0, r.err)
        esperas = [e for e in r.esperas if e > 0]
        self.assertTrue(esperas)
        # o relógio é o real e a espera é falsa: cada espera é a pausa mais o jitter menos o tempo já gasto (~0)
        self.assertTrue(all(1.9 <= e <= 2.26 for e in esperas), esperas)
        self.assertEqual(len(esperas), len(r.api.pedidos) - 1)


class TestOrcamento(Base):
    """CA7: o Teto total (achados.json) e o --max-req saem com 3, sem perder nem repetir página."""

    def controle(self):
        r = garimpar()
        self.assertEqual(r.codigo, 0, r.err)
        return foto(r.pasta)

    def pedidos_repetidos(self, *apis):
        """Variáveis (com a página) pedidas mais de uma vez em todas as rodadas."""
        todas = [json.dumps(v, sort_keys=True) for api in apis for v in api.variaveis()]
        return sorted({x for x in todas if todas.count(x) > 1})

    def test_teto_total_do_achados_para_com_3_e_a_retomada_termina_igual_sem_repetir_pedido(self):
        esperado = self.controle()
        r1 = garimpar(achados={**ACHADOS_PEQUENOS, 'max_total_requests': 10})
        self.assertEqual(r1.codigo, 3)
        self.assertEqual(len(r1.api.pedidos), 10)
        self.orcamento_bate(r1, 10)
        self.assertIn('teto de requisições total (max_total_requests do achados.json)', r1.err)
        self.assertEqual(r1.linhas('SELECT COUNT(*) FROM categories'), [(0,)], 'categoria interrompida não é marcada')
        self.fechou_certo(r1)
        r2 = garimpar(pasta=r1.pasta)   # sem o teto: usa o padrão de 20.000
        self.assertEqual(r2.codigo, 0, r2.err)
        self.assertEqual(foto(r1.pasta), esperado)
        self.orcamento_bate(r1.pasta, 19)
        self.assertEqual(self.pedidos_repetidos(r1.api, r2.api), [], 'o teto é checado antes do pedido: nada em voo')
        self.assertIn('10 requisições já feitas de 20000', r2.out)

    def test_teto_total_conta_o_historico_do_banco_entre_rodadas(self):
        r1 = garimpar(achados={**ACHADOS_PEQUENOS, 'max_total_requests': 12})
        self.assertEqual((r1.codigo, len(r1.api.pedidos)), (3, 12))
        r2 = garimpar(pasta=r1.pasta, achados={**ACHADOS_PEQUENOS, 'max_total_requests': 15})
        self.assertEqual((r2.codigo, len(r2.api.pedidos)), (3, 3))
        r3 = garimpar(pasta=r1.pasta, achados={**ACHADOS_PEQUENOS, 'max_total_requests': 15})
        self.assertEqual((r3.codigo, len(r3.api.pedidos)), (3, 0), 'orçamento esgotado: nenhum pedido')
        self.orcamento_bate(r1.pasta, 15)

    def test_max_req_em_rodadas_ate_terminar(self):
        esperado = self.controle()
        pasta, codigos, apis = comum.nova_pasta(), [], []
        for _ in range(6):
            r = garimpar(['--max-req', '7'], pasta=pasta)
            codigos.append(r.codigo)
            apis.append(r.api)
            self.assertLessEqual(len(r.api.pedidos), 7)
            self.fechou_certo(r)
            if r.codigo == 0:
                break
        self.assertEqual(codigos, [3, 3, 0])
        self.assertEqual([len(a.pedidos) for a in apis], [7, 7, 5])
        self.assertEqual(foto(pasta), esperado)
        self.assertEqual(self.pedidos_repetidos(*apis), [])
        self.orcamento_bate(pasta, 19)

    def test_mensagem_do_teto_diz_qual_foi(self):
        r = garimpar(['--max-req', '3'])
        self.assertEqual(r.codigo, 3)
        self.assertIn('desta rodada (--max-req)', r.err)
        r = garimpar(['--max-req', '3'], pasta=r.pasta, achados={**ACHADOS_PEQUENOS, 'max_total_requests': 4})
        self.assertEqual((r.codigo, len(r.api.pedidos)), (3, 1))
        self.assertIn('total (max_total_requests do achados.json)', r.err)


class TestFalhasDaApi(Base):
    """CA7: limite da API (3), erro e resposta fora do formato (1), configuração (2); a retomada continua."""

    def controle(self):
        r = garimpar()
        return foto(r.pasta)

    def test_limite_10030_persistente_sai_com_3_anota_as_esperas_e_a_retomada_termina_igual(self):
        esperado = self.controle()
        api = ApiCatalogo(gancho=lambda n, v: erro(CS.ERRO_LIMITE, 'limit') if 6 <= n <= 11 else None)
        r1 = garimpar(api=api)
        self.assertEqual(r1.codigo, 3)
        self.assertIn('limite de requisições da API', r1.err)
        self.assertEqual(len(api.pedidos), 11)
        self.orcamento_bate(r1, 11)
        # as 6 tentativas do limite estão na tabela, na página que ficou pendente, sem produto novo
        self.assertEqual(r1.linhas('SELECT pagina, codigo, novos FROM requisicoes WHERE codigo = ?', CS.ERRO_LIMITE),
                         [(2, CS.ERRO_LIMITE, None)] * 6)
        longas = sorted(e for e in r1.esperas if e > 20)
        self.assertEqual(len(longas), 5)
        for esperada, real in zip((30, 60, 120, 240, 480), longas):
            self.assertTrue(0.8 * esperada <= real <= 1.2 * esperada, (esperada, real))
        self.assertEqual(r1.linhas('SELECT ultima_pagina, status FROM consultas ORDER BY id'),
                         [(4, 'esgotada'), (1, 'pendente')])
        self.fechou_certo(r1)
        r2 = garimpar(pasta=r1.pasta)
        self.assertEqual(r2.codigo, 0, r2.err)
        self.assertEqual(foto(r1.pasta), esperado)
        self.orcamento_bate(r1.pasta, 11 + len(r2.api.pedidos))
        self.sem_vazamento(r1.pasta, r1.out, r1.err, r2.out, r2.err)

    def test_http_429_conta_como_limite_do_mesmo_jeito(self):
        api = ApiCatalogo(gancho=lambda n, v: http_erro(429, b'') if 6 <= n <= 11 else None)
        r = garimpar(api=api)
        self.assertEqual(r.codigo, 3)
        self.assertEqual(r.linhas('SELECT COUNT(*) FROM requisicoes WHERE http = 429 AND novos IS NULL'), [(6,)])

    def test_limite_que_passa_na_terceira_tentativa_segue_sem_sair(self):
        esperado = self.controle()
        api = ApiCatalogo(gancho=lambda n, v: erro(CS.ERRO_LIMITE) if n in (6, 7) else None)
        r = garimpar(api=api)
        self.assertEqual(r.codigo, 0, r.err)
        self.assertEqual(foto(r.pasta), esperado)
        self.orcamento_bate(r, 19 + 2)
        self.assertEqual(len([e for e in r.esperas if e > 20]), 2)

    def test_erro_da_api_sai_com_1_marca_a_consulta_e_a_retomada_continua(self):
        esperado = self.controle()
        r1 = garimpar(api=ApiCatalogo(gancho=lambda n, v: erro(10020, 'texto da api') if n == 6 else None))
        self.assertEqual(r1.codigo, 1)
        self.assertIn('código 10020', r1.err)
        self.assertNotIn('texto da api', r1.err + r1.log, 'o texto da API não vai para a saída nem para o log')
        self.assertEqual(r1.linhas('SELECT status, ultima_pagina FROM consultas ORDER BY id'),
                         [('esgotada', 4), ('erro', 1)])
        self.assertEqual(r1.linhas('SELECT codigo, novos FROM requisicoes WHERE codigo = 10020'), [(10020, None)])
        self.fechou_certo(r1)
        r2 = garimpar(pasta=r1.pasta)
        self.assertEqual(r2.codigo, 0, r2.err)
        self.assertEqual(foto(r1.pasta), esperado)

    def test_resposta_fora_do_formato_sai_com_1_sem_gravar_a_pagina(self):
        def estraga(n, v):
            if n == 6:
                return {'data': {'productOfferV2': {'nodes': [no(9999)], 'pageInfo': {'page': 2, 'limit': 5}}}}
        r = garimpar(api=ApiCatalogo(gancho=estraga))
        self.assertEqual(r.codigo, 1)
        self.assertIn('fora do formato', r.err)
        self.assertEqual(r.linhas('SELECT COUNT(*) FROM products WHERE item_id = ?', '9999'), [(0,)])
        self.assertEqual(r.linhas('SELECT status, ultima_pagina FROM consultas ORDER BY id'),
                         [('esgotada', 4), ('erro', 1)])
        self.fechou_certo(r)

    def test_item_sem_item_id_derruba_a_pagina_inteira_com_1(self):
        def estraga(n, v):
            if n == 2:
                return resposta([no(1), {'productName': 'sem id'}], tem_proxima=True, pagina=2)
        r = garimpar(api=ApiCatalogo(gancho=estraga))
        self.assertEqual(r.codigo, 1)
        self.assertEqual(r.linhas('SELECT COUNT(*) FROM products'), [(5,)], 'só a página 1 ficou')
        self.assertEqual(r.linhas('SELECT status, ultima_pagina FROM consultas'), [('erro', 1)])

    def test_estrategia_desconhecida_no_achados_passa_a_validacao_e_sai_com_2_antes_de_pedir(self):
        achados = {**ACHADOS_PEQUENOS, 'estrategias': ['sortt']}
        self.assertEqual(G.ler_achados.__name__, 'ler_achados')
        arq = os.path.join(comum.nova_pasta(), 'a.json')
        with open(arq, 'w') as f:
            json.dump(achados, f)
        self.assertEqual(G.ler_achados(arq)['estrategias'], ['sortt'], 'a leitura do achados aceita o nome')
        r = garimpar(achados=achados)
        self.assertEqual(r.codigo, 2)
        self.assertEqual(r.api.pedidos, [])
        self.assertEqual(r.linhas('SELECT COUNT(*) FROM consultas'), [(0,)])
        self.assertIn('estrategias:', r.err)
        self.fechou_certo(r)

    def test_achados_invalido_sai_com_2_sem_banco_e_sem_pedido(self):
        r = garimpar(achados={**ACHADOS_PEQUENOS, 'limit': 501})
        self.assertEqual(r.codigo, 2)
        self.assertEqual(r.api.pedidos, [])
        self.assertFalse(os.path.exists(r.banco))
        self.assertIn('limit', r.err)

    def test_sem_secret_sai_com_2_sem_pedido_nem_banco(self):
        r = garimpar(segredo=None)
        self.assertEqual(r.codigo, 2)
        self.assertEqual(r.api.pedidos, [])
        self.assertFalse(os.path.exists(r.banco))
        self.fechou_certo(r)


# ---------------------------------------------------------------------------------------------------------
# CA4: Ctrl+C em qualquer ponto do motor nunca deixa página pela metade; só a página em curso se repete
# ---------------------------------------------------------------------------------------------------------
class ConAlvo:
    """Conexão que levanta KeyboardInterrupt no k-ésimo `execute` (antes de rodá-lo ou logo depois dele)."""

    def __init__(self, con, k, depois):
        self._con, self.k, self.depois, self.n, self.sqls = con, k, depois, 0, []

    @property
    def in_transaction(self):
        return self._con.in_transaction

    def execute(self, sql, *args):
        self.n += 1
        self.sqls.append(sql)
        if self.n == self.k and not self.depois:
            raise KeyboardInterrupt()
        resultado = self._con.execute(sql, *args)
        if self.n == self.k and self.depois:
            raise KeyboardInterrupt()
        return resultado


BUSCA_PAGINAR = {'productCatId': CAT, 'sortType': 1}


def paginar_com(con, api, **kw):
    """`motor.paginar` com o Cliente real (ja_feitas lido do banco, como o garimpo.py faz) e a API trocada."""
    ja = con.execute('SELECT COUNT(*) FROM requisicoes').fetchone()[0] if not isinstance(con, ConAlvo) else 0
    with comum.isolado(api):
        cli = K.Cliente(comum.cred(), ja_feitas=ja, dormir=lambda s: None, aleatorio=lambda a, b: a)
        return M.paginar(con, cli, C.CONSULTA_PRODUTOS, dict(BUSCA_PAGINAR), teto_pagina=100, limit=5, **kw)


class TestCtrlCNoMotor(Base):
    def setUp(self):
        self.api_controle = ApiCatalogo(total=15)
        pasta = comum.nova_pasta()
        self.con = banco.abrir(os.path.join(pasta, 'garimpo.db'))
        paginar_com(self.con, self.api_controle)
        self.con.close()
        self.esperado = foto(pasta)
        self.pedidos_controle = len(self.api_controle.pedidos)
        # quantos `execute` o motor faz numa rodada completa (para varrer cada ponto de interrupção)
        pasta = comum.nova_pasta()
        alvo = ConAlvo(banco.abrir(os.path.join(pasta, 'garimpo.db')), 0, False)
        paginar_com(alvo, ApiCatalogo(total=15))
        self.total_execute, self.sqls = alvo.n, alvo.sqls
        alvo._con.close()

    def rodada_interrompida(self, k, depois):
        pasta = comum.nova_pasta()
        real = banco.abrir(os.path.join(pasta, 'garimpo.db'))
        api1 = ApiCatalogo(total=15)
        try:
            with self.assertRaises(KeyboardInterrupt):
                paginar_com(ConAlvo(real, k, depois), api1)
        finally:
            real.close()
        con = banco.abrir(os.path.join(pasta, 'garimpo.db'))
        try:
            meio = con.execute('SELECT COUNT(*) FROM products').fetchone()[0]
            paginas = con.execute('SELECT COALESCE(MAX(ultima_pagina), 0) FROM consultas').fetchone()[0]
            self.assertEqual(con.in_transaction, False)
            self.assertEqual(con.execute('PRAGMA integrity_check').fetchone(), ('ok',))
            # nada de página pela metade: os produtos gravados são exatamente os das páginas do checkpoint
            self.assertEqual(meio, min(paginas * 5, 15))
            self.assertEqual(con.execute('SELECT COUNT(*) FROM product_sources').fetchone()[0], meio)
            api2 = ApiCatalogo(total=15)
            res = paginar_com(con, api2)
        finally:
            con.close()
        return pasta, api1, api2, res

    @staticmethod
    def sem_pagina_extra(f):
        """A queda depois da última página e antes de fechar a consulta gasta, por desenho (docstring do motor),
        um pedido a mais, que volta vazio: tira essa página extra para comparar com o controle."""
        f = dict(f)
        f['consultas'] = [c[:4] + (min(c[4], 3),) + c[5:] for c in f['consultas']]
        f['paginas'] = [p for p in f['paginas'] if p[2] != 0]
        return f

    def confere_varredura(self, depois, exato):
        for k in range(1, self.total_execute + 1):
            with self.subTest(execute=k, depois=depois):
                pasta, api1, api2, res = self.rodada_interrompida(k, depois)
                self.assertEqual(self.sem_pagina_extra(foto(pasta)), self.sem_pagina_extra(self.esperado))
                self.assertEqual(res['status'], 'esgotada')
                chamadas = len(api1.pedidos) + len(api2.pedidos)
                # o que saiu para a API nas duas rodadas é o controle mais, no máximo, a página em curso
                self.assertLessEqual(chamadas, self.pedidos_controle + 1)
                linhas = contar(pasta, 'SELECT COUNT(*) FROM requisicoes')[0][0]
                if exato:
                    self.assertEqual(linhas, chamadas)
                else:   # ver TestBugsAbertos: a fronteira do COMMIT e a do BEGIN erram a conta em 1
                    self.assertLessEqual(abs(linhas - chamadas), 1)

    def test_ctrl_c_antes_de_cada_execute_nao_deixa_pagina_pela_metade_e_a_retomada_fecha_igual(self):
        self.confere_varredura(depois=False, exato=True)

    def test_ctrl_c_logo_depois_de_cada_execute_tambem(self):
        self.confere_varredura(depois=True, exato=False)

    def test_queda_depois_da_ultima_pagina_gasta_um_pedido_vazio_e_fecha(self):
        """Desenho documentado no motor: o `hasNextPage` não é guardado, então a retomada pede a página seguinte."""
        pasta = comum.nova_pasta()
        con = banco.abrir(os.path.join(pasta, 'garimpo.db'))
        cid = banco.obter_consulta(con, 'productOfferV2', {**BUSCA_PAGINAR, 'limit': 5}, fase='garimpar')['id']
        api0 = ApiCatalogo(total=15)
        for pagina in (1, 2, 3):
            v = {**BUSCA_PAGINAR, 'limit': 5, 'page': pagina}
            nos = api0.resposta(v)['data']['productOfferV2']['nodes']
            banco.gravar_pagina(con, cid, pagina, nos, {'operacao': 'productOfferV2', 'http': 200})
        api = ApiCatalogo(total=15)
        res = paginar_com(con, api)
        con.close()
        self.assertEqual([v['page'] for v in api.variaveis()], [4])
        self.assertEqual((res['status'], res['novos'], res['ultima_pagina']), ('esgotada', 0, 4))

    def test_ctrl_c_durante_o_pedido_repete_so_aquela_pagina(self):
        for n in range(1, self.pedidos_controle + 1):
            with self.subTest(pedido=n):
                pasta = comum.nova_pasta()
                con = banco.abrir(os.path.join(pasta, 'garimpo.db'))
                api1 = ApiCatalogo(total=15, gancho=lambda i, v, n=n: KeyboardInterrupt() if i == n else None)
                with self.assertRaises(KeyboardInterrupt):
                    paginar_com(con, api1)
                api2 = ApiCatalogo(total=15)
                paginar_com(con, api2)
                con.close()
                self.assertEqual(foto(pasta), self.esperado)
                paginas = [(v['page']) for v in api1.variaveis() + api2.variaveis()]
                self.assertEqual(sorted(set(paginas)), [1, 2, 3])
                self.assertEqual({p: paginas.count(p) for p in (1, 2, 3)}, {1: 1 + (n == 1), 2: 1 + (n == 2),
                                                                               3: 1 + (n == 3)})
                self.orcamento_bate(pasta, len(paginas))


# ---------------------------------------------------------------------------------------------------------
# subprocessos: sinais de verdade (Ctrl+C, kill, kill -9) e duas rodadas ao mesmo tempo
# ---------------------------------------------------------------------------------------------------------
RUNNER = ("import json, sys\nsys.path.insert(0, sys.argv[1])\nimport test_qa_entrega1 as Q\n"
          "Q.executar_filho(json.loads(sys.argv[2]))\n")


class ApiRoteadaComGancho(ApiRoteada):
    """O falso da fase reconhecer com um gancho(n) antes de cada resposta (n = número do pedido, de 1 a N)."""

    def __init__(self, gancho):
        super().__init__()
        self.gancho, self.chamadas = gancho, 0

    def __call__(self, req, timeout=None):
        self.chamadas += 1
        r = self.gancho(self.chamadas, None)
        if isinstance(r, BaseException):
            raise r
        return super().__call__(req, timeout)


def _gancho_filho(cfg):
    def gancho(n, v):
        if cfg.get('preso') and n == 1:
            open(cfg['preso'], 'w').close()
            parada, fim = threading.Event(), time.monotonic() + 40
            while not os.path.exists(cfg['liberar']) and time.monotonic() < fim:
                parada.wait(0.05)
        if cfg.get('sinal') and n == cfg['no_pedido']:
            os.kill(os.getpid(), getattr(signal, cfg['sinal']))
            threading.Event().wait(5)   # SIGINT vira KeyboardInterrupt aqui; os outros matam o processo
        return None
    return gancho


def executar_filho(cfg):
    """Corpo do subprocesso: a mesma rodada do `garimpar()`, mas num processo à parte (sinal de verdade)."""
    os.environ.update({'ACHADINHOS_GARIMPO_DIR': cfg['pasta'], 'ACHADINHOS_SHOPEE_APP_ID': APP_ID,
                       'ACHADINHOS_SHOPEE_SECRET': SECRET})
    setUpModule()
    arq_achados, arq_cat = arquivar(cfg['pasta'], cfg.get('achados', ACHADOS_PEQUENOS), None)
    gancho = _gancho_filho(cfg)
    api = ApiRoteadaComGancho(gancho) if cfg['argv'][0] == 'reconhecer' else ApiCatalogo(gancho=gancho)
    with mock.patch.dict(sys.modules, {NOME_FASE: _modulo_fase_qa()}), \
            mock.patch.dict(G.SUBCOMANDOS, {'garimpar': NOME_FASE}), \
            mock.patch.object(G, 'ACHADOS', arq_achados), mock.patch.object(G, 'CATEGORIAS', arq_cat), \
            comum.isolado(api):
        codigo = G.main(cfg['argv'])
    sys.exit(codigo)


def iniciar_filho(**cfg):
    env = dict(os.environ)
    env.update({'TMPDIR': comum.TMP, 'PYTHONDONTWRITEBYTECODE': '1'})
    return subprocess.Popen([sys.executable, '-c', RUNNER, os.path.dirname(ARQ_ESTE), json.dumps(cfg)], env=env, cwd=RAIZ,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def rodar_filho(timeout=60, **cfg):
    p = iniciar_filho(**cfg)
    try:
        out, err = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        p.kill()
        out, err = p.communicate()
        raise AssertionError(f'subprocesso preso: {cfg}\n{out}\n{err}')
    return types.SimpleNamespace(codigo=p.returncode, out=out, err=err)


def ultima_linha_do_log(pasta):
    """Última linha do log mais recente (pela data de modificação: `-2.log` ordena antes de `.log`)."""
    nomes = logs_de(pasta)
    if not nomes:
        return None
    recente = max(nomes, key=lambda n: os.stat(os.path.join(pasta, 'logs', n)).st_mtime_ns)
    return ler(pasta, os.path.join('logs', recente)).rstrip('\n').split('\n')[-1]


def trava_livre(pasta):
    """A trava da rodada está solta: dá para pegá-la agora, sem esperar."""
    with banco.travar(pasta):
        return True


class TestSinaisReais(Base):
    """CA4 e CA7 com sinal de verdade num subprocesso: Ctrl+C sai com 130, `kill` e `kill -9` deixam o banco íntegro."""

    @classmethod
    def setUpClass(cls):
        r = garimpar()
        cls.esperado = foto(r.pasta)
        cls.pedidos_controle = len(r.api.pedidos)

    def conferir_banco(self, pasta):
        con = sqlite3.connect(f'file:{os.path.join(pasta, "garimpo.db")}?mode=ro', uri=True)
        try:
            self.assertEqual(con.execute('PRAGMA integrity_check').fetchone(), ('ok',))
            # nenhum produto fora de uma página gravada
            self.assertEqual(con.execute('SELECT COUNT(*) FROM products WHERE item_id NOT IN '
                                         '(SELECT item_id FROM product_sources)').fetchone(), (0,))
        finally:
            con.close()

    def test_ctrl_c_de_verdade_sai_com_130_solta_a_trava_e_a_retomada_repete_so_a_pagina_em_curso(self):
        for pedido in (3, 7, 12):   # sort1 p3 (com itens novos), sort2 p3 e sort3 p4/p3
            with self.subTest(pedido=pedido):
                pasta = comum.nova_pasta()
                a = rodar_filho(pasta=pasta, argv=['garimpar'], sinal='SIGINT', no_pedido=pedido)
                self.assertEqual(a.codigo, 130, a.err)
                self.assertEqual(ultima_linha_do_log(pasta), 'SAIDA=130')
                self.assertIn('Interrompido', a.err)
                self.assertNotIn('Traceback', a.err + a.out)
                self.assertTrue(trava_livre(pasta))
                self.conferir_banco(pasta)
                self.sem_vazamento(pasta, a.out, a.err)
                # a requisição que ia pela rede ficou anotada uma vez, sem página nem produto novo
                self.assertEqual(contar(pasta, 'SELECT COUNT(*) FROM requisicoes WHERE novos IS NULL '
                                               'AND http IS NULL'), [(1,)])
                b = rodar_filho(pasta=pasta, argv=['garimpar'])
                self.assertEqual(b.codigo, 0, b.err)
                self.assertEqual(foto(pasta), self.esperado)
                # as duas rodadas pediram o controle mais UMA repetição (a página em curso)
                self.assertEqual(contar(pasta, 'SELECT COUNT(*) FROM requisicoes')[0][0], self.pedidos_controle + 1)
                self.assertEqual(contar(pasta, 'SELECT COUNT(*) FROM requisicoes WHERE novos IS NOT NULL')[0][0],
                                 self.pedidos_controle)
                self.assertEqual(ultima_linha_do_log(pasta), 'SAIDA=0')
                self.sem_vazamento(pasta, b.out, b.err)

    def test_kill_9_no_meio_deixa_banco_integro_trava_livre_e_a_retomada_termina_igual(self):
        pasta = comum.nova_pasta()
        a = rodar_filho(pasta=pasta, argv=['garimpar'], sinal='SIGKILL', no_pedido=3)
        self.assertEqual(a.codigo, -signal.SIGKILL)
        self.assertTrue(trava_livre(pasta), 'a trava some com o processo: kill -9 não deixa trava velha')
        self.conferir_banco(pasta)
        b = rodar_filho(pasta=pasta, argv=['garimpar'])
        self.assertEqual(b.codigo, 0, b.err)
        self.assertEqual(foto(pasta), self.esperado)
        self.conferir_banco(pasta)

    def test_kill_comum_sigterm_deixa_banco_integro_e_a_retomada_termina_igual(self):
        pasta = comum.nova_pasta()
        a = rodar_filho(pasta=pasta, argv=['garimpar'], sinal='SIGTERM', no_pedido=3)
        self.assertEqual(a.codigo, -signal.SIGTERM)
        self.assertTrue(trava_livre(pasta))
        self.conferir_banco(pasta)
        b = rodar_filho(pasta=pasta, argv=['garimpar'])
        self.assertEqual(b.codigo, 0, b.err)
        self.assertEqual(foto(pasta), self.esperado)


class TestRodadaSimultanea(Base):
    """CA7: a 2ª rodada ao mesmo tempo sai com 2, sem pedir nada nem tocar o banco, e a 1ª termina normal."""

    def test_segunda_rodada_sai_com_2_sem_pedido_e_a_primeira_termina_com_0(self):
        for segunda in (['conferir'], ['garimpar'], ['reconhecer']):
            with self.subTest(segunda=segunda):
                pasta = comum.nova_pasta()
                preso, liberar = os.path.join(pasta, 'preso.flag'), os.path.join(pasta, 'liberar.flag')
                primeira = iniciar_filho(pasta=pasta, argv=['conferir'], preso=preso, liberar=liberar)
                try:
                    fim = time.monotonic() + 40
                    while not os.path.exists(preso) and time.monotonic() < fim:
                        time.sleep(0.05)
                    self.assertTrue(os.path.exists(preso), 'a 1ª rodada não chegou ao pedido')
                    b = rodar_filho(pasta=pasta, argv=segunda)
                    self.assertEqual(b.codigo, 2, b.err)
                    self.assertIn('outra rodada do garimpo está em andamento', b.err)
                    self.assertNotIn('Traceback', b.err + b.out)
                    # a 2ª não pediu nada à API nem gravou requisição; a 1ª ainda está no pedido
                    self.assertEqual(contar(pasta, 'SELECT COUNT(*) FROM requisicoes'), [(0,)])
                    self.assertEqual(len(logs_de(pasta)), 2, 'cada rodada tem o seu log')
                    open(liberar, 'w').close()
                    out, err = primeira.communicate(timeout=60)
                finally:
                    if primeira.poll() is None:
                        primeira.kill()
                        primeira.communicate()
                self.assertEqual(primeira.returncode, 0, err)
                finais = sorted(ler(pasta, os.path.join('logs', n)).rstrip('\n').split('\n')[-1]
                                for n in logs_de(pasta))
                self.assertEqual(finais, ['SAIDA=0', 'SAIDA=2'])
                self.assertEqual(contar(pasta, 'SELECT COUNT(*) FROM requisicoes'), [(1,)])
                self.sem_vazamento(pasta, out, err, b.out, b.err)
                # solta: uma terceira rodada passa
                c = rodar_filho(pasta=pasta, argv=['conferir'])
                self.assertEqual(c.codigo, 0, c.err)

    def test_primeira_morta_com_kill_9_nao_deixa_a_segunda_presa(self):
        pasta = comum.nova_pasta()
        preso, liberar = os.path.join(pasta, 'preso.flag'), os.path.join(pasta, 'liberar.flag')
        primeira = iniciar_filho(pasta=pasta, argv=['conferir'], preso=preso, liberar=liberar)
        try:
            fim = time.monotonic() + 40
            while not os.path.exists(preso) and time.monotonic() < fim:
                time.sleep(0.05)
            self.assertTrue(os.path.exists(preso))
            self.assertEqual(rodar_filho(pasta=pasta, argv=['conferir']).codigo, 2)
            primeira.kill()
            primeira.communicate()
        finally:
            if primeira.poll() is None:
                primeira.kill()
                primeira.communicate()
        segunda = rodar_filho(pasta=pasta, argv=['conferir'])
        self.assertEqual(segunda.codigo, 0, segunda.err)


class TestBugsAbertos(Base):
    """Achados do QA que o dev ainda não corrigiu: cada teste abaixo FALHA hoje (severidade baixa nos dois)."""

    def sqls_do_controle(self):
        pasta = comum.nova_pasta()
        alvo = ConAlvo(banco.abrir(os.path.join(pasta, 'garimpo.db')), 0, False)
        paginar_com(alvo, ApiCatalogo(total=15))
        alvo._con.close()
        return alvo.sqls

    def interrompe_na_pagina_1(self, k):
        pasta = comum.nova_pasta()
        real = banco.abrir(os.path.join(pasta, 'garimpo.db'))
        api1 = ApiCatalogo(total=15)
        try:
            with self.assertRaises(KeyboardInterrupt):
                paginar_com(ConAlvo(real, k, True), api1)
        finally:
            real.close()
        con = banco.abrir(os.path.join(pasta, 'garimpo.db'))
        api2 = ApiCatalogo(total=15)
        paginar_com(con, api2)
        con.close()
        return pasta, len(api1.pedidos) + len(api2.pedidos)

    def test_q1_ctrl_c_logo_depois_do_commit_da_pagina_nao_duplica_a_linha_da_requisicao(self):
        sqls = self.sqls_do_controle()
        k_update = next(i for i, q in enumerate(sqls, 1) if q.startswith('UPDATE consultas SET ultima_pagina'))
        self.assertEqual(sqls[k_update], 'COMMIT')
        pasta, chamadas = self.interrompe_na_pagina_1(k_update + 1)
        self.assertEqual(contar(pasta, 'SELECT COUNT(*) FROM requisicoes WHERE pagina = 1'), [(1,)],
                         'a página 1 foi gravada uma vez e pedida uma vez: uma linha só')
        self.orcamento_bate(pasta, chamadas)

    def test_q2_ctrl_c_logo_depois_do_begin_da_pagina_nao_perde_a_requisicao_em_voo(self):
        sqls = self.sqls_do_controle()
        k_select = next(i for i, q in enumerate(sqls, 1) if q.startswith('SELECT ultima_pagina, status'))
        self.assertEqual(sqls[k_select - 2], 'BEGIN IMMEDIATE')
        pasta, chamadas = self.interrompe_na_pagina_1(k_select - 1)
        self.orcamento_bate(pasta, chamadas)
