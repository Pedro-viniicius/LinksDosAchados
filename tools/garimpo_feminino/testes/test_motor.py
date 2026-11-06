#!/usr/bin/env python3
"""Testes do motor.py (etapa 7 do garimpo feminino: CA3, CA4 e CA9). Sem rede.

Rodar: python3 tools/garimpo_feminino/testes/test_motor.py -v

Cobrem: (1) `paginar`: retomada (interromper na página 3 e retomar na 4), parada pelos nós (página vazia ou incompleta,
já que a consulta não pede o `pageInfo`), pelo teto de página e por páginas seguidas sem item novo, pedidos que não
geram página, erros; (2) a saturação nas bordas
(1,9% e 2%) e a janela das últimas 5 consultas; (3) as variáveis de cada estratégia e a ordem delas; (4) o
fatiamento por keyword (sementes, bigramas em bola de neve, sem repetir, retomada).
Os proxies apontam para 127.0.0.1:9 e a rede é trocada por falsos (`comum.isolado`).
"""
import json
import os
import unittest
import urllib.error
from unittest import mock

import comum  # noqa: F401  (isolamento: tem de vir antes dos módulos do garimpo)
from comum import CS, SECRET, ApiFalsa, Resp, cred, erro, no, resposta

import banco  # noqa: E402
import cliente as K  # noqa: E402
import consultas as C  # noqa: E402
import motor as M  # noqa: E402

CAT = 100420
BUSCA = {'keyword': 'vestido', 'sortType': 1}
LIM = 2   # limit das páginas dos testes de `paginar`: página com 2 nós é cheia, com 0 ou 1 é a última


class ApiDinamica(ApiFalsa):
    """API falsa que responde pelo conteúdo do pedido: `fn(variaveis, n)` devolve (quantos itens novos, titulo(i)
    ou None). Sem `pageInfo`, como a consulta do garimpo: a página é "cheia" quando `n` for o `limit` do pedido.
    Cada item novo tem um itemId único, e os pedidos ficam em `pedidos`."""

    def __init__(self, fn):
        super().__init__()
        self.fn, self.proximo = fn, 100_000

    def __call__(self, req, timeout=None):
        self.pedidos.append(req)
        self.timeouts.append(timeout)
        variaveis = json.loads(req.data)['variables']
        n, titulo = self.fn(variaveis, len(self.pedidos))
        nos = []
        for i in range(n):
            self.proximo += 1
            nos.append(no(self.proximo, productName=titulo(i) if titulo else f'Produto avulso {self.proximo}'))
        return Resp(json.dumps(resposta(nos)).encode())

    def variaveis(self):
        return [c['variables'] for c in self.corpos()]


class Base(unittest.TestCase):
    def setUp(self):
        self.con = banco.abrir(os.path.join(comum.nova_pasta(), 'garimpo.db'))
        self.addCleanup(self.con.close)
        self.esperas = []

    def cliente(self, **kw):
        return K.Cliente(cred(), dormir=self.esperas.append, aleatorio=lambda a, b: a, **kw)

    def linhas(self, sql, *args):
        return self.con.execute(sql, args).fetchall()

    def reabrir(self):
        """Banco novo e vazio no lugar do atual (para repetir o cenário dentro de um subTest)."""
        self.con.close()
        self.con = banco.abrir(os.path.join(comum.nova_pasta(), 'garimpo.db'))
        self.addCleanup(self.con.close)

    def paginar(self, cli, variaveis=BUSCA, **kw):
        kw = {'teto_pagina': 100, 'limit': LIM, **kw}
        return M.paginar(self.con, cli, C.CONSULTA_PRODUTOS, dict(variaveis), **kw)


def pag(ids):
    """Página sem `pageInfo`, como a da consulta do garimpo."""
    return resposta([no(i) for i in ids])


# ---------- (1) paginar ----------
class TestPaginar(Base):
    def test_percorre_ate_a_pagina_incompleta_e_encerra_como_esgotada(self):
        api = ApiFalsa(pag([1, 2]), pag([3, 4]), pag([5]))
        with comum.isolado(api):
            r = self.paginar(self.cliente())
        self.assertEqual((r['status'], r['paginas'], r['vistos'], r['novos'], r['ultima_pagina']),
                         ('esgotada', 3, 5, 5, 3))
        self.assertEqual([c['variables']['page'] for c in api.corpos()], [1, 2, 3])
        self.assertEqual([c['variables']['limit'] for c in api.corpos()], [LIM, LIM, LIM])
        self.assertEqual({c['query'] for c in api.corpos()}, {C.CONSULTA_PRODUTOS})
        self.assertEqual(self.linhas('SELECT status, ultima_pagina, vistos, novos, concluida_em IS NOT NULL '
                                     'FROM consultas'), [('esgotada', 3, 5, 5, 1)])
        self.assertEqual(self.linhas('SELECT COUNT(*) FROM products'), [(5,)])
        self.assertEqual(self.linhas('SELECT pagina, n_nos, novos FROM requisicoes ORDER BY pagina'),
                         [(1, 2, 2), (2, 2, 2), (3, 1, 1)])

    def test_pagina_incompleta_encerra_sem_pedido_extra(self):
        """A consulta não tem `pageInfo`: a página com menos itens que o `limit` é a última e nada mais é pedido."""
        for ids in ([], [1], [1, 2, 3]):                    # vazia, incompleta (< limit 4)
            with self.subTest(n=len(ids)):
                self.reabrir()
                api = ApiFalsa(pag(ids))
                with comum.isolado(api):
                    r = self.paginar(self.cliente(), limit=4)
                self.assertEqual((r['status'], r['paginas'], r['vistos'], r['ultima_pagina']),
                                 ('esgotada', 1, len(ids), 1))
                self.assertEqual(len(api.pedidos), 1)
                self.assertEqual(self.linhas('SELECT status, ultima_pagina FROM consultas'), [('esgotada', 1)])

    def test_pagina_cheia_pede_a_seguinte_e_um_pedido_a_mais_e_aceito(self):
        """O último lote vem exatamente cheio: sai 1 pedido a mais, que volta vazio e encerra."""
        api = ApiFalsa(pag([1, 2]), pag([3, 4]), pag([]))
        with comum.isolado(api):
            r = self.paginar(self.cliente())
        self.assertEqual((r['status'], r['paginas'], r['vistos'], r['ultima_pagina']), ('esgotada', 3, 4, 3))
        self.assertEqual(len(api.pedidos), 3)

    def test_o_pageinfo_da_resposta_e_ignorado_o_que_decide_e_o_tamanho_da_pagina(self):
        # hasNextPage mentindo nos dois sentidos: a página cheia continua e a incompleta encerra
        api = ApiFalsa(resposta([no(1), no(2)], tem_proxima=False), resposta([no(3)], tem_proxima=True))
        with comum.isolado(api):
            r = self.paginar(self.cliente())
        self.assertEqual((r['status'], r['paginas'], r['ultima_pagina']), ('esgotada', 2, 2))
        self.assertEqual(len(api.pedidos), 2)

    def test_interromper_na_pagina_3_e_retomar_na_4(self):
        api = ApiFalsa(pag([1, 2]), pag([3, 4]), pag([5, 6]))
        with comum.isolado(api):
            with self.assertRaises(K.Teto):                 # --max-req 3: a 4ª requisição não sai
                self.paginar(self.cliente(max_rodada=3))
        self.assertEqual(len(api.pedidos), 3)
        self.assertEqual(self.linhas('SELECT status, ultima_pagina, vistos, novos FROM consultas'),
                         [('pendente', 3, 6, 6)])
        api2 = ApiFalsa(pag([7, 8]), pag([9]))
        with comum.isolado(api2):
            r = self.paginar(self.cliente())               # outra rodada: cliente novo
        self.assertEqual([c['variables']['page'] for c in api2.corpos()], [4, 5])   # nada das páginas 1 a 3
        self.assertEqual((r['status'], r['paginas'], r['novos'], r['ultima_pagina']), ('esgotada', 2, 3, 5))
        self.assertEqual(self.linhas('SELECT pagina, COUNT(*) FROM requisicoes GROUP BY pagina ORDER BY pagina'),
                         [(p, 1) for p in range(1, 6)])
        self.assertEqual(self.linhas('SELECT COUNT(*) FROM products'), [(9,)])
        self.assertEqual(self.linhas('SELECT status, vistos, novos FROM consultas'), [('esgotada', 9, 9)])

    def test_falha_no_meio_da_pagina_3_refaz_so_a_pagina_3(self):
        api = ApiFalsa(pag([1, 2]), pag([3, 4]), urllib.error.URLError('x'))
        with comum.isolado(api):
            with self.assertRaises(CS.ErroApi):
                self.paginar(self.cliente())
        self.assertEqual(self.linhas('SELECT status, ultima_pagina FROM consultas'), [('erro', 2)])
        api2 = ApiFalsa(pag([5]))
        with comum.isolado(api2):
            r = self.paginar(self.cliente())
        self.assertEqual([c['variables']['page'] for c in api2.corpos()], [3])
        self.assertEqual(r['status'], 'esgotada')
        self.assertEqual(self.linhas('SELECT status, ultima_pagina, novos FROM consultas'), [('esgotada', 3, 5)])
        # a tentativa que falhou ficou registrada, sem novos
        self.assertEqual(self.linhas('SELECT novos, n_nos FROM requisicoes WHERE pagina = 3 ORDER BY id'),
                         [(None, None), (1, 1)])

    def test_ctrl_c_deixa_a_consulta_pendente_e_a_retomada_continua(self):
        api = ApiFalsa(pag([1, 2]), KeyboardInterrupt())
        with comum.isolado(api):
            with self.assertRaises(KeyboardInterrupt):
                self.paginar(self.cliente())
        self.assertEqual(self.linhas('SELECT status, ultima_pagina FROM consultas'), [('pendente', 1)])
        api2 = ApiFalsa(pag([3]))
        with comum.isolado(api2):
            self.assertEqual(self.paginar(self.cliente())['status'], 'esgotada')
        self.assertEqual([c['variables']['page'] for c in api2.corpos()], [2])

    def test_teto_de_pagina_marca_teto(self):
        api = ApiDinamica(lambda v, n: (LIM, None))
        with comum.isolado(api):
            r = self.paginar(self.cliente(), teto_pagina=3)
        self.assertEqual((r['status'], r['paginas'], r['ultima_pagina']), ('teto', 3, 3))
        self.assertEqual(len(api.pedidos), 3)               # não pede a página 4
        self.assertEqual(self.linhas('SELECT status, concluida_em IS NOT NULL FROM consultas'), [('teto', 1)])

    def test_pagina_cheia_na_pagina_40_com_limit_50_marca_teto(self):
        """Os valores do achados.json real (R1): 50 itens por página e teto na 40."""
        api = ApiDinamica(lambda v, n: (50, None))
        with comum.isolado(api):
            r = self.paginar(self.cliente(), limit=50, teto_pagina=40)
        self.assertEqual((r['status'], r['paginas'], r['ultima_pagina'], r['vistos']), ('teto', 40, 40, 2000))
        self.assertEqual(len(api.pedidos), 40)              # não pede a página 41
        self.assertEqual(self.linhas('SELECT status, ultima_pagina FROM consultas'), [('teto', 40)])

    def test_pagina_do_teto_incompleta_e_esgotada_nao_teto(self):
        api = ApiDinamica(lambda v, n: (LIM if v['page'] < 3 else LIM - 1, None))
        with comum.isolado(api):
            r = self.paginar(self.cliente(), teto_pagina=3)
        self.assertEqual(r['status'], 'esgotada')

    def test_teto_de_pagina_na_retomada_nao_pede_mais(self):
        api = ApiDinamica(lambda v, n: (LIM, None))
        with comum.isolado(api):
            with self.assertRaises(K.Teto):
                self.paginar(self.cliente(max_rodada=3), teto_pagina=5, paginas_sem_novo=50)
        # a página 3 está gravada e a consulta aberta (queda antes de fechar, ou teto_pagina menor no achados)
        self.assertEqual(self.linhas('SELECT status, ultima_pagina FROM consultas'), [('pendente', 3)])
        with comum.isolado(api):
            r = self.paginar(self.cliente(), teto_pagina=3, paginas_sem_novo=50)
        self.assertEqual((r['status'], r['paginas']), ('teto', 0))
        self.assertEqual(len(api.pedidos), 3)

    def test_paginas_seguidas_sem_novo_encerram_como_saturada(self):
        # 1ª página nova; depois 3 páginas cheias só com itens já vistos
        api = ApiFalsa(pag([1, 2]), pag([1, 2]), pag([2, 1]), pag([1, 2]), pag([9, 10]))
        with comum.isolado(api):
            r = self.paginar(self.cliente(), paginas_sem_novo=3)
        self.assertEqual((r['status'], r['paginas']), ('saturada', 4))
        self.assertEqual(len(api.pedidos), 4)

    def test_pagina_com_novo_zera_a_contagem(self):
        api = ApiFalsa(pag([1, 2]), pag([1, 2]), pag([1, 3]), pag([1, 2]), pag([2, 3]), pag([1]))
        with comum.isolado(api):
            r = self.paginar(self.cliente(), paginas_sem_novo=3)
        # sem novo: p2 (1), p3 traz o 3 (zera), p4 (1), p5 (2), p6 (3, mas incompleta: esgotada)
        self.assertEqual((r['status'], r['paginas']), ('esgotada', 6))

    def test_retomada_refaz_a_contagem_de_paginas_sem_novo(self):
        api = ApiFalsa(pag([1, 2]), pag([1, 2]), pag([1, 2]))
        with comum.isolado(api):
            with self.assertRaises(K.Teto):
                self.paginar(self.cliente(max_rodada=3), paginas_sem_novo=3)   # p2 e p3 sem novo (2 seguidas)
        api2 = ApiFalsa(pag([1, 2]), pag([3, 4]))
        with comum.isolado(api2):
            r = self.paginar(self.cliente(), paginas_sem_novo=3)
        self.assertEqual((r['status'], r['paginas']), ('saturada', 1))    # a 3ª seguida, só com o pedido novo
        self.assertEqual(len(api2.pedidos), 1)

    def test_consulta_encerrada_nao_pede_nada(self):
        api = ApiFalsa(pag([1]))
        with comum.isolado(api):
            self.paginar(self.cliente())
            r = self.paginar(self.cliente())
        self.assertEqual(len(api.pedidos), 1)
        self.assertEqual((r['status'], r['paginas'], r['vistos'], r['novos'], r['ultima_pagina']),
                         ('esgotada', 0, 0, 0, 1))

    def test_limite_da_api_e_registrado_sem_novos_e_a_pagina_sai_depois(self):
        api = ApiFalsa(erro(CS.ERRO_LIMITE), pag([1]))
        with comum.isolado(api):
            r = self.paginar(self.cliente())
        self.assertEqual(r['status'], 'esgotada')
        self.assertGreaterEqual(max(self.esperas), 24)      # o backoff (30 s x 0,8), além da pausa do ritmo
        self.assertEqual(self.linhas('SELECT pagina, codigo, novos, n_nos FROM requisicoes ORDER BY id'),
                         [(1, CS.ERRO_LIMITE, None, None), (1, None, 1, 1)])

    def test_limite_que_nao_passa_deixa_a_consulta_pendente_com_as_requisicoes_anotadas(self):
        api = ApiFalsa(*[erro(CS.ERRO_LIMITE)] * (K.TENTATIVAS_LIMITE + 1))
        with comum.isolado(api):
            with self.assertRaises(CS.LimiteAtingido):
                self.paginar(self.cliente())
        self.assertEqual(self.linhas('SELECT status, ultima_pagina FROM consultas'), [('pendente', 0)])
        self.assertEqual(self.linhas('SELECT COUNT(*), MIN(pagina), MAX(pagina) FROM requisicoes'),
                         [(K.TENTATIVAS_LIMITE + 1, 1, 1)])

    def test_erro_de_api_fecha_com_erro_e_sobe(self):
        with comum.isolado(ApiFalsa(erro(10020, 'texto da api'))):
            with self.assertRaises(CS.ErroApi):
                self.paginar(self.cliente())
        self.assertEqual(self.linhas('SELECT status, concluida_em IS NULL FROM consultas'), [('erro', 1)])
        self.assertEqual(self.linhas('SELECT pagina, codigo, novos FROM requisicoes'), [(1, 10020, None)])

    def test_resposta_fora_do_formato_fecha_com_erro(self):
        for nome, ruim in (('nodes que não é lista', {'data': {'productOfferV2': {'nodes': 'x'}}}),
                           ('sem nodes', {'data': {'productOfferV2': {}}}),
                           ('nó que não é objeto', {'data': {'productOfferV2': {'nodes': [no(1), 7]}}}),
                           ('sem a operação', {'data': {}})):
            with self.subTest(ruim=nome):
                self.reabrir()
                with comum.isolado(ApiFalsa(ruim)):
                    with self.assertRaises(C.FormatoInvalido):
                        self.paginar(self.cliente())
                self.assertEqual(self.linhas('SELECT status, ultima_pagina FROM consultas'), [('erro', 0)])
                self.assertEqual(self.linhas('SELECT COUNT(*) FROM requisicoes'), [(1,)])
                self.assertEqual(self.linhas('SELECT COUNT(*) FROM products'), [(0,)])

    def test_no_sem_item_id_e_pulado_e_contado(self):
        """R3: o nó ruim fica de fora e a página é gravada; antes ele recusava a página e travava a categoria."""
        ruins = [{'productName': 'sem id'}, {'itemId': 'abc'}]
        with comum.isolado(ApiFalsa(resposta([no(1), ruins[0], no(2), ruins[1]]))):
            r = self.paginar(self.cliente(), limit=5)       # 4 nós < 5: a página é a última
        self.assertEqual((r['status'], r['vistos'], r['novos'], r['pulados']), ('esgotada', 2, 2, 2))
        self.assertEqual(self.linhas('SELECT status, ultima_pagina, vistos FROM consultas'), [('esgotada', 1, 2)])
        self.assertEqual(self.linhas('SELECT COUNT(*) FROM products'), [(2,)])
        self.assertEqual(self.linhas('SELECT n_nos, novos FROM requisicoes'), [(4, 2)])

    def test_no_pulado_conta_para_a_pagina_cheia(self):
        """O que decide é quantos nós a API mandou, não quantos foram gravados."""
        api = ApiFalsa(resposta([no(1), {'itemId': 'abc'}]), resposta([no(2)]))
        with comum.isolado(api):
            r = self.paginar(self.cliente())
        self.assertEqual((r['status'], r['paginas'], r['vistos'], r['pulados']), ('esgotada', 2, 2, 1))

    def test_surrogate_no_titulo_nao_derruba_a_pagina(self):
        with comum.isolado(ApiFalsa(resposta([no(1, productName='Vestido ' + chr(0xD83D))]))):
            r = self.paginar(self.cliente())
        self.assertEqual(r['status'], 'esgotada')
        self.assertEqual(self.linhas('SELECT nome FROM products'), [('Vestido ?',)])

    def test_o_limit_entra_na_chave_do_checkpoint(self):
        api = ApiFalsa(pag([1]), pag([1]))
        with comum.isolado(api):
            self.paginar(self.cliente(), limit=20)
            self.paginar(self.cliente(), limit=50)
        self.assertEqual(len(self.linhas('SELECT id FROM consultas')), 2)
        self.assertEqual([c['variables']['limit'] for c in api.corpos()], [20, 50])

    def test_nao_altera_o_dicionario_do_chamador_e_leva_fase_estrategia_e_categoria(self):
        busca = {'productCatId': CAT, 'sortType': 2}
        with comum.isolado(ApiFalsa(pag([1]))):
            self.paginar(self.cliente(), busca, fase='piloto', estrategia='sort', cat_id=CAT)
        self.assertEqual(busca, {'productCatId': CAT, 'sortType': 2})
        self.assertEqual(self.linhas('SELECT fase, estrategia, cat_id FROM consultas'),
                         [('piloto', 'sort', str(CAT))])

    def test_recusa_argumentos_invalidos_sem_pedir(self):
        api = ApiFalsa()
        casos = [dict(variaveis={'page': 1}), dict(variaveis={'limit': 20}), dict(variaveis=[1]),
                 dict(teto_pagina=0), dict(teto_pagina=True), dict(teto_pagina='3'), dict(limit=0), dict(limit=501),
                 dict(limit=2.5), dict(paginas_sem_novo=0), dict(paginas_sem_novo=None)]
        with comum.isolado(api):
            for caso in casos:
                with self.subTest(caso=caso):
                    kw = dict(caso)
                    variaveis = kw.pop('variaveis', BUSCA)
                    with self.assertRaises(ValueError):
                        M.paginar(self.con, self.cliente(), C.CONSULTA_PRODUTOS, variaveis,
                                  **{'teto_pagina': 100, 'limit': 20, **kw})
            for consulta in (C.CONSULTA_LOJAS, C.INTROSPECCAO, '', None):
                with self.subTest(consulta=consulta):
                    with self.assertRaises(ValueError):
                        M.paginar(self.con, self.cliente(), consulta, BUSCA, teto_pagina=3, limit=20)
        self.assertEqual(api.pedidos, [])
        self.assertEqual(self.linhas('SELECT COUNT(*) FROM consultas'), [(0,)])

    def test_o_segredo_nunca_chega_ao_banco(self):
        with comum.isolado(ApiFalsa(pag([1, 2]), urllib.error.URLError(SECRET), pag([3]))):
            with self.assertRaises(CS.ErroApi):
                self.paginar(self.cliente())
            self.paginar(self.cliente())
        self.con.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        caminho = self.linhas('PRAGMA database_list')[0][2]
        with open(caminho, 'rb') as f:
            self.assertNotIn(SECRET.encode(), f.read())
        self.assertNotIn(b'Signature=', comum.conteudo_da_pasta(os.path.dirname(caminho)))


# ---------- R2: erro permanente não trava a categoria ----------
class ApiSeletiva(ApiDinamica):
    """Como a ApiDinamica, mas `falha(variaveis, n)` pode devolver uma resposta ou uma exceção para o pedido."""

    def __init__(self, falha, fn=lambda v, n: (2, None)):
        super().__init__(fn)
        self.falha = falha

    def __call__(self, req, timeout=None):
        n = len(self.pedidos) + 1
        r = self.falha(json.loads(req.data)['variables'], n)
        if r is None:
            return super().__call__(req, timeout)
        self.pedidos.append(req)
        if isinstance(r, BaseException):
            raise r
        return Resp(json.dumps(r).encode())


class TestErroPermanente(Base):
    def garimpar(self, api, estrategias=('sort',), **kw):
        kw = {'limit': 20, 'teto_pagina': 5, **kw}
        cli = kw.pop('cli', None) or self.cliente()
        with comum.isolado(api):
            return M.garimpar_categoria(self.con, cli, CAT, list(estrategias), **kw)

    def so_o_sort(self, tipo, resposta_falha):
        return lambda v, n: resposta_falha if v.get('sortType') == tipo else None

    def status_por_sort(self):
        return [r[0] for r in self.linhas('SELECT status FROM consultas ORDER BY id')]

    def test_com_codigo_a_consulta_fica_em_erro_e_o_motor_segue(self):
        api = ApiSeletiva(self.so_o_sort(2, erro(10010, 'ECO-DA-API')))
        mensagens = []
        self.assertEqual(self.garimpar(api, log=mensagens.append), 'esgotada')
        self.assertEqual([v['sortType'] for v in api.variaveis()], [1, 2, 3, 4, 5])
        self.assertEqual(self.status_por_sort(), ['esgotada', 'erro', 'esgotada', 'esgotada', 'esgotada'])
        self.assertEqual(self.linhas('SELECT parada FROM categories'),
                         [(M.PARADA['esgotada'] + '; ' + M.PARADA['recusadas'].format(n=1),)])
        self.assertIn('10010', ' '.join(mensagens))
        self.assertFalse(any('ECO-DA-API' in m for m in mensagens))

    def test_http_4xx_sem_codigo_e_permanente(self):
        for http in (400, 404, 422):
            with self.subTest(http=http):
                self.reabrir()
                api = ApiSeletiva(lambda v, n, http=http: comum.http_erro(http) if v.get('sortType') == 3 else None)
                self.assertEqual(self.garimpar(api), 'esgotada')
                self.assertEqual(len(api.pedidos), 5)
                self.assertEqual(self.status_por_sort().count('erro'), 1)

    def test_a_parada_cita_a_contagem_de_recusadas(self):
        api = ApiSeletiva(lambda v, n: erro(10010) if v.get('sortType') in (1, 3, 5) else None)
        self.garimpar(api)
        self.assertEqual(self.linhas('SELECT parada FROM categories'),
                         [(M.PARADA['esgotada'] + '; ' + M.PARADA['recusadas'].format(n=3),)])
        self.assertIn('3', self.linhas('SELECT parada FROM categories')[0][0])

    def test_nova_rodada_nao_repete_a_consulta_permanente(self):
        api = ApiSeletiva(self.so_o_sort(2, erro(10010)))
        self.garimpar(api)
        n = len(api.pedidos)
        self.assertEqual(self.garimpar(api), 'esgotada')
        self.assertEqual(len(api.pedidos), n, 'a consulta recusada e as encerradas não pedem de novo')
        self.assertEqual(self.linhas('SELECT parada FROM categories'),
                         [(M.PARADA['esgotada'] + '; ' + M.PARADA['recusadas'].format(n=1),)])

    def test_paginar_de_novo_devolve_erro_sem_pedir(self):
        api = ApiSeletiva(lambda v, n: erro(10010))
        with comum.isolado(api), self.assertRaises(CS.ErroApi):
            self.paginar(self.cliente())
        with comum.isolado(api):
            r = self.paginar(self.cliente())
        self.assertEqual((r['status'], r['paginas']), ('erro', 0))
        self.assertEqual(len(api.pedidos), 1)

    def test_recusa_na_pagina_3_guarda_as_anteriores_e_nao_repete(self):
        api = ApiSeletiva(lambda v, n: erro(10010) if v['page'] == 3 else None, lambda v, n: (LIM, None))
        self.assertEqual(self.garimpar(api, ['ams_keyseller'], teto_pagina=9, limit=LIM), 'esgotada')
        self.assertEqual(self.linhas('SELECT status, ultima_pagina FROM consultas ORDER BY id'),
                         [('erro', 2), ('erro', 2)])
        n = len(api.pedidos)
        self.garimpar(api, ['ams_keyseller'], teto_pagina=9, limit=LIM)
        self.assertEqual(len(api.pedidos), n)

    def test_transitorio_sobe_e_a_retomada_refaz(self):
        casos = (('rede', urllib.error.URLError('x')), ('http_500', comum.http_erro(500)),
                 ('http_503_com_codigo', comum.http_erro(503, corpo=erro(10010))), ('http_401', comum.http_erro(401)),
                 ('http_403_com_codigo', comum.http_erro(403, corpo=erro(10020))), ('http_302', comum.http_erro(302)))
        for nome, falha in casos:
            with self.subTest(caso=nome):
                self.reabrir()
                api = ApiSeletiva(self.so_o_sort(2, falha))
                with self.assertRaises(CS.ErroApi):
                    self.garimpar(api)
                self.assertEqual(self.linhas('SELECT COUNT(*) FROM categories'), [(0,)])
                self.assertEqual(self.status_por_sort(), ['esgotada', 'erro'])
                api2 = ApiSeletiva(lambda v, n: None)
                self.assertEqual(self.garimpar(api2), 'esgotada')
                self.assertEqual([v['sortType'] for v in api2.variaveis()], [2, 3, 4, 5])   # refaz a que caiu
                self.assertEqual(self.linhas('SELECT parada FROM categories'), [(M.PARADA['esgotada'],)])

    def test_system_error_repete_sobe_e_nao_marca_a_consulta_de_vez(self):
        # motor sobre o Cliente real: 10000 em todas as tentativas da sort 2
        api = ApiSeletiva(self.so_o_sort(2, erro(K.ERRO_SISTEMA)))
        with self.assertRaises(CS.ErroApi):
            self.garimpar(api)
        self.assertEqual([v['sortType'] for v in api.variaveis()], [1] + [2] * (K.TENTATIVAS_SISTEMA + 1))
        self.assertEqual(self.linhas('SELECT COUNT(*) FROM categories'), [(0,)])
        self.assertEqual(M._recusadas(self.con, CAT), 0)
        api2 = ApiSeletiva(lambda v, n: None)
        self.assertEqual(self.garimpar(api2), 'esgotada')
        self.assertEqual([v['sortType'] for v in api2.variaveis()], [2, 3, 4, 5])   # a próxima rodada refaz
        self.assertEqual(self.linhas('SELECT parada FROM categories'), [(M.PARADA['esgotada'],)])

    def test_system_error_que_passa_na_tentativa_nao_aparece(self):
        vistas = []

        def uma_vez(v, n):
            if v.get('sortType') == 3 and not vistas:
                vistas.append(n)
                return erro(K.ERRO_SISTEMA)
            return None
        self.assertEqual(self.garimpar(ApiSeletiva(uma_vez)), 'esgotada')
        self.assertEqual(self.status_por_sort(), ['esgotada'] * 5)

    def test_limite_na_retomada_nao_vira_erro_permanente(self):
        # a consulta está em erro (rede); na retomada, a API só responde 10030 até desistir: o último registro
        # tem código, mas é limite. A próxima rodada tem de pedir de novo.
        with self.assertRaises(CS.ErroApi):
            self.garimpar(ApiSeletiva(self.so_o_sort(1, urllib.error.URLError('x'))))
        with self.assertRaises(CS.LimiteAtingido):
            self.garimpar(ApiSeletiva(lambda v, n: erro(CS.ERRO_LIMITE)))
        self.assertEqual(self.status_por_sort(), ['erro'])
        api = ApiSeletiva(lambda v, n: None)
        self.assertEqual(self.garimpar(api), 'esgotada')
        self.assertEqual(len(api.pedidos), 5)

    def test_resposta_fora_do_formato_continua_subindo(self):
        ruim = {'data': {'productOfferV2': {'nodes': 'x'}}}
        api = ApiSeletiva(self.so_o_sort(1, ruim))
        with self.assertRaises(C.FormatoInvalido):
            self.garimpar(api)
        self.assertEqual(self.linhas('SELECT COUNT(*) FROM categories'), [(0,)])
        api2 = ApiSeletiva(lambda v, n: None)
        self.assertEqual(self.garimpar(api2), 'esgotada')
        self.assertEqual(len(api2.pedidos), 5)                       # a de formato ruim é refeita

    def test_recusada_nao_entra_na_janela_da_saturacao(self):
        # 5 consultas sem novo saturam; a recusada no meio não conta nem atrapalha
        cid = banco.obter_consulta(self.con, 'productOfferV2', {'x': 1}, fase='semente')['id']
        banco.gravar_pagina(self.con, cid, 1, [no(1)], {'operacao': 'productOfferV2'})
        api = ApiSeletiva(lambda v, n: (erro(10010) if v.get('sortType') == 1 else pag([1])))
        self.assertEqual(self.garimpar(api, ['sort', 'ams_keyseller']), 'saturada')
        self.assertEqual(self.linhas('SELECT saturada, parada FROM categories'),
                         [(1, M.PARADA['saturada'] + '; ' + M.PARADA['recusadas'].format(n=1))])
        self.assertEqual(len(api.pedidos), 6)

    def test_so_conta_a_recusa_de_vez_nas_estrategias_do_motor(self):
        def consulta(i, *, estrategia='sort', status='erro', **req):
            cid = banco.obter_consulta(self.con, 'productOfferV2', {'c': i}, fase='garimpar', estrategia=estrategia,
                                       cat_id=CAT)['id']
            banco.registrar_requisicao(self.con, cid, 1, {'operacao': 'productOfferV2', **req})
            banco.fechar_consulta(self.con, cid, status)

        consulta(1, codigo=10010)                     # recusada
        consulta(2, http=400)                         # recusada
        consulta(3)                                   # em erro por falha de rede
        consulta(4, http=503, codigo=10010)           # em erro por 5xx
        consulta(5, codigo=10010, status='esgotada')  # encerrada
        consulta(6, codigo=10010, estrategia='mapa')  # não é do motor
        self.assertEqual(M._recusadas(self.con, CAT), 2)
        self.assertEqual(M._recusadas(self.con, CAT + 1), 0)

    def test_consulta_em_erro_sem_nenhum_pedido_registrado_e_refeita(self):
        cid = banco.obter_consulta(self.con, 'productOfferV2', {**BUSCA, 'limit': 20}, fase='garimpar')['id']
        banco.fechar_consulta(self.con, cid, 'erro')
        api = ApiFalsa(pag([1]))
        with comum.isolado(api):
            self.assertEqual(self.paginar(self.cliente())['status'], 'esgotada')
        self.assertEqual(len(api.pedidos), 1)

    def test_com_os_fatos_do_r1_os_ids_vao_como_o_schema_pede(self):
        # productCatId é Int (número); matchId, itemId e shopId são Int64 (texto: número dá 10010, #37 e #38)
        api = ApiSeletiva(lambda v, n: None)
        self.garimpar(api, ['sort', 'listtype'], list_types=[4])
        vs = api.variaveis()
        self.assertTrue(all(type(v['productCatId']) is int for v in vs if 'productCatId' in v))
        self.assertEqual([v['matchId'] for v in vs if 'matchId' in v], [str(CAT)])
        self.assertEqual(C.TIPOS['productCatId'], 'Int')
        for nome in ('matchId', 'itemId', 'shopId'):
            self.assertEqual(C.TIPOS[nome], 'Int64')

    def test_produto_so_com_os_campos_de_producao_e_gravado(self):
        # a parte B pode tirar campos da CONSULTA_PRODUTOS: nem o motor nem o banco exigem o que faltar
        no_minimo = {'itemId': 1, 'shopId': 777, 'productName': 'Vestido', 'priceMin': '9.9', 'priceDiscountRate': 0,
                     'ratingStar': '4.8', 'sales': 1, 'imageUrl': 'https://x/y', 'offerLink': comum.LINK}
        with comum.isolado(ApiFalsa(resposta([no_minimo]))):
            r = self.paginar(self.cliente())
        self.assertEqual((r['status'], r['novos']), ('esgotada', 1))
        self.assertEqual(self.linhas('SELECT cat_l1, commission, product_link FROM products'), [(None, None, None)])

    def test_pageinfo_estranho_na_resposta_nao_derruba_porque_o_motor_nao_o_le(self):
        # a consulta não pede o pageInfo; se ele vier mesmo assim (nulo, incompleto, tipo errado), é ignorado
        for info in ({'page': None, 'limit': 20, 'hasNextPage': False}, {'page': 1}, 'x', None, [], {'limit': 'a'}):
            with self.subTest(info=info):
                self.reabrir()
                ruim = {'data': {'productOfferV2': {'nodes': [no(1)], 'pageInfo': info}}}
                with comum.isolado(ApiFalsa(ruim)):
                    self.assertEqual(self.paginar(self.cliente())['status'], 'esgotada')

    def test_o_log_conta_os_nos_pulados(self):
        mensagens = []
        api = ApiFalsa(*[resposta([no(i), {'itemId': 'x'}]) for i in range(1, 6)])
        self.garimpar(api, log=mensagens.append)
        self.assertTrue(all('1 nós sem id' in m for m in mensagens), mensagens)


# ---------- (2) saturação ----------
def fechar(con, cat, vistos, novos, *, estrategia='sort', status='esgotada', i=[0]):
    """Cria uma consulta já encerrada da categoria, direto no banco."""
    i[0] += 1
    cid = banco.obter_consulta(con, 'productOfferV2', {'k': i[0]}, fase='garimpar', estrategia=estrategia,
                               cat_id=cat)['id']
    con.execute('UPDATE consultas SET vistos = ?, novos = ?, status = ?, concluida_em = ? WHERE id = ?',
                (vistos, novos, status, '2026-11-06T10:00:00', cid))
    return cid


class TestSaturacao(Base):
    def cinco(self, vistos, novos, ultima=None):
        for _ in range(4):
            fechar(self.con, CAT, 1000, 0)
        fechar(self.con, CAT, *(ultima or (vistos, novos)))

    def test_bordas_de_2_por_cento(self):
        for vistos, novos, esperado in [(1000, 19, True), (1000, 20, False), (1000, 21, False), (100, 1, True),
                                        (100, 2, False), (50, 1, False), (51, 1, True), (500, 9, True),
                                        (500, 10, False), (0, 0, True), (10, 0, True), (1, 1, False)]:
            with self.subTest(vistos=vistos, novos=novos):
                con = banco.abrir(os.path.join(comum.nova_pasta(), 'garimpo.db'))
                self.addCleanup(con.close)
                for _ in range(4):
                    fechar(con, CAT, 1000, 0)
                fechar(con, CAT, vistos, novos)
                self.assertIs(M.saturada(con, CAT), esperado)

    def test_cada_uma_das_cinco_tem_de_ficar_abaixo(self):
        for posicao in range(5):
            with self.subTest(posicao=posicao):
                con = banco.abrir(os.path.join(comum.nova_pasta(), 'garimpo.db'))
                self.addCleanup(con.close)
                for i in range(5):
                    fechar(con, CAT, 1000, 20 if i == posicao else 19)
                self.assertFalse(M.saturada(con, CAT))
                # média abaixo de 2%, mas uma consulta em 2% ou mais: não satura
        con = banco.abrir(os.path.join(comum.nova_pasta(), 'garimpo.db'))
        self.addCleanup(con.close)
        for _ in range(5):
            fechar(con, CAT, 1000, 19)
        self.assertTrue(M.saturada(con, CAT))

    def test_com_menos_de_cinco_consultas_nao_satura(self):
        for _ in range(4):
            fechar(self.con, CAT, 1000, 0)
        self.assertFalse(M.saturada(self.con, CAT))
        fechar(self.con, CAT, 1000, 0)
        self.assertTrue(M.saturada(self.con, CAT))

    def test_so_as_ultimas_cinco_contam(self):
        fechar(self.con, CAT, 100, 100)     # a mais antiga trouxe tudo novo
        for _ in range(5):
            fechar(self.con, CAT, 100, 1)
        self.assertTrue(M.saturada(self.con, CAT))
        fechar(self.con, CAT, 100, 50)      # uma nova e rica empurra para fora da janela só a mais antiga
        self.assertFalse(M.saturada(self.con, CAT))

    def test_ignora_outra_categoria_consulta_aberta_com_erro_e_de_outra_fase_sem_estrategia(self):
        for _ in range(4):
            fechar(self.con, CAT, 1000, 0)
        fechar(self.con, CAT + 1, 1000, 0)                       # outra categoria
        fechar(self.con, CAT, 1000, 0, status='erro')            # não encerrada com sucesso
        fechar(self.con, CAT, 1000, 0, status='pendente')
        fechar(self.con, CAT, 1000, 0, estrategia='mapa')        # não é do motor
        fechar(self.con, CAT, 1000, 0, estrategia=None)
        self.assertFalse(M.saturada(self.con, CAT))
        fechar(self.con, CAT, 1000, 0, estrategia='fatiamento', status='teto')
        self.assertTrue(M.saturada(self.con, CAT))

    def test_cat_id_invalido(self):
        for ruim in (0, -1, True, 'a', '', 1.5, None, 2 ** 63):
            with self.subTest(ruim=ruim):
                with self.assertRaises(ValueError):
                    M.saturada(self.con, ruim)
        self.assertFalse(M.saturada(self.con, str(CAT)))


class TestSaturacaoNoFluxo(Base):
    """A mesma borda, mas pelo caminho inteiro: pedidos, consultas gravadas e retorno de garimpar_categoria."""

    def preparar(self):
        # 1000 itens já conhecidos (consulta fora do motor)
        cid = banco.obter_consulta(self.con, 'productOfferV2', {'x': 1}, fase='semente')['id']
        banco.gravar_pagina(self.con, cid, 1, [no(i) for i in range(1, 1001)], {'operacao': 'productOfferV2'})

    def api(self, novos_por_consulta):
        """Cada consulta lê 999 itens em 2 páginas (500 cheia + 499 incompleta, limit 500): `novos_por_consulta(k)`
        são inéditos (todos na 1ª página) e o resto, já conhecidos. 20 inéditos de 999 passam de 2%, 19 não."""
        estado = {'proximo': 50_000}

        class Api(ApiFalsa):
            def __call__(inner, req, timeout=None):
                inner.pedidos.append(req)
                k, pagina = divmod(len(inner.pedidos) - 1, 2)
                novos = novos_por_consulta(k + 1) if pagina == 0 else 0
                ids = list(range(1, 501 - novos)) if pagina == 0 else list(range(501, 1000))
                for _ in range(novos):
                    estado['proximo'] += 1
                    ids.append(estado['proximo'])
                return Resp(json.dumps(resposta([no(i) for i in ids])).encode())
        return Api()

    def garimpar(self, api, **kw):
        kw = {'limit': 500, 'teto_pagina': 100, **kw}
        with comum.isolado(api):
            return M.garimpar_categoria(self.con, self.cliente(), CAT, kw.pop('estrategias', ['sort']), **kw)

    def test_1_9_por_cento_nas_cinco_satura_e_para_nos_cinco_pedidos(self):
        self.preparar()
        api = self.api(lambda n: 19)
        self.assertEqual(self.garimpar(api, estrategias=None, list_types=[3, 4]), 'saturada')
        self.assertEqual(len(api.pedidos), 5 * 2)           # nem listtype, nem ams, nem fatiamento (2 páginas cada)
        self.assertEqual(self.linhas('SELECT saturada, bateu_teto, parada FROM categories'),
                         [(1, 0, M.PARADA['saturada'])])

    def test_2_por_cento_nao_satura_e_as_estrategias_seguem_ate_o_fim(self):
        self.preparar()
        api = self.api(lambda n: 20)
        self.assertEqual(self.garimpar(api, estrategias=None, list_types=[3, 4]), 'esgotada')
        self.assertEqual(len(api.pedidos), (5 + 2 + 2) * 2)
        self.assertEqual(self.linhas('SELECT saturada, bateu_teto, parada FROM categories'),
                         [(0, 0, M.PARADA['esgotada'])])

    def test_a_janela_desliza_uma_rica_no_comeco_nao_impede(self):
        self.preparar()
        api = self.api(lambda n: 500 if n == 1 else 0)
        self.assertEqual(self.garimpar(api, estrategias=['sort', 'ams_keyseller']), 'saturada')
        self.assertEqual(len(api.pedidos), 6 * 2)           # sort 2..5 + ams: as 5 últimas

    def test_categoria_ja_saturada_nao_pede_nada(self):
        self.preparar()
        api = self.api(lambda n: 0)
        self.assertEqual(self.garimpar(api), 'saturada')
        n = len(api.pedidos)
        self.assertEqual(self.garimpar(api, estrategias=['ams_keyseller']), 'saturada')   # nem a consulta nova
        self.assertEqual(self.garimpar(api, estrategias=None), 'saturada')
        self.assertEqual(len(api.pedidos), n)

    def test_o_log_so_traz_id_estrategia_e_contagens(self):
        self.preparar()
        mensagens = []
        self.garimpar(self.api(lambda n: 0), log=mensagens.append)
        self.assertTrue(mensagens)
        self.assertTrue(all(str(CAT) in m for m in mensagens))
        self.assertTrue(any('sort' in m for m in mensagens))


# ---------- (3) estratégias ----------
class TestEstrategias(Base):
    def api(self, mais=False):
        """`mais`: toda página vem cheia (com `limit` itens), então a consulta só para no teto; sem ele, vem
        incompleta (2 itens) e a consulta se esgota na página 1."""
        return ApiDinamica(lambda v, n: (v['limit'] if mais else 2, None))

    def garimpar(self, api, estrategias=None, **kw):
        kw = {'limit': 20, 'teto_pagina': 5, **kw}
        with comum.isolado(api):
            return M.garimpar_categoria(self.con, self.cliente(), kw.pop('cat', CAT), estrategias, **kw)

    def esperado_sort(self, cat=str(CAT)):
        return [{'productCatId': int(cat), 'sortType': s, 'limit': 20, 'page': 1} for s in (1, 2, 3, 4, 5)]

    def test_ordem_padrao_e_variaveis_de_cada_estrategia(self):
        api = self.api()
        self.assertEqual(self.garimpar(api, list_types=[3, 4]), 'esgotada')
        self.assertEqual(api.variaveis(), self.esperado_sort() + [
            {'listType': 4, 'matchId': str(CAT), 'limit': 20, 'page': 1},
            {'listType': 3, 'matchId': str(CAT), 'limit': 20, 'page': 1},
            {'productCatId': CAT, 'isAMSOffer': True, 'limit': 20, 'page': 1},
            {'productCatId': CAT, 'isKeySeller': True, 'limit': 20, 'page': 1}])
        self.assertEqual({c['query'] for c in api.corpos()}, {C.CONSULTA_PRODUTOS})
        self.assertEqual([r[0] for r in self.linhas('SELECT estrategia FROM consultas ORDER BY id')],
                         ['sort'] * 5 + ['listtype'] * 2 + ['ams_keyseller'] * 2)
        self.assertEqual({r[0] for r in self.linhas('SELECT cat_id FROM consultas')}, {str(CAT)})
        self.assertEqual({r[0] for r in self.linhas('SELECT fase FROM consultas')}, {'garimpar'})

    def test_sort_cobre_exatamente_1_a_5(self):
        api = self.api()
        self.garimpar(api, ['sort'])
        self.assertEqual([v['sortType'] for v in api.variaveis()], [1, 2, 3, 4, 5])

    def test_listtype_so_os_liberados_pelo_achados_e_na_ordem_do_brief(self):
        casos = [([], []), ([4], [4]), ([3], [3]), ([3, 4], [4, 3]), ([4, 3], [4, 3]), ([0, 1, 2, 5], []),
                 ([5, 3, 0], [3]), ((4,), [4])]
        for liberados, esperado in casos:
            with self.subTest(liberados=liberados):
                self.reabrir()
                api = self.api()
                self.garimpar(api, ['listtype'], list_types=liberados)
                self.assertEqual([v['listType'] for v in api.variaveis()], esperado)
                self.assertTrue(all(v['matchId'] == str(CAT) for v in api.variaveis()))

    def test_ams_e_keyseller_sao_duas_consultas_com_o_booleano_verdadeiro(self):
        api = self.api()
        self.garimpar(api, ['ams_keyseller'])
        vs = api.variaveis()
        self.assertEqual(len(vs), 2)
        self.assertIs(vs[0]['isAMSOffer'], True)
        self.assertNotIn('isKeySeller', vs[0])
        self.assertIs(vs[1]['isKeySeller'], True)
        self.assertNotIn('isAMSOffer', vs[1])
        self.assertTrue(all(v['productCatId'] == CAT for v in vs))
        self.assertIn(b'"isAMSOffer":true', api.pedidos[0].data)       # booleano JSON, não texto
        self.assertIn(b'"isKeySeller":true', api.pedidos[1].data)

    def test_a_ordem_do_achados_troca_a_ordem_e_tira_estrategias(self):
        api = self.api()
        self.garimpar(api, ['ams_keyseller', 'sort'])
        vs = api.variaveis()
        self.assertEqual(['isAMSOffer' in v or 'isKeySeller' in v for v in vs], [True, True] + [False] * 5)
        self.assertEqual([r[0] for r in self.linhas('SELECT estrategia FROM consultas ORDER BY id')],
                         ['ams_keyseller'] * 2 + ['sort'] * 5)

    def test_estrategia_desconhecida_ou_lista_ruim_e_erro_de_configuracao_sem_pedir(self):
        for ruim in (['sort', 'nada'], [], 'sort', ['sort', 'sort'], [1], ['SORT'], 5):
            with self.subTest(ruim=ruim):
                api = self.api()
                with self.assertRaises(banco.ErroConfig):
                    self.garimpar(api, ruim)
                self.assertEqual(api.pedidos, [])

    def test_int64_texto_ou_numero_so_nos_campos_int64_da_tabela(self):
        api = self.api()
        self.garimpar(api, ['listtype'], list_types=[4], int64='numero')
        self.assertEqual(api.variaveis()[0]['matchId'], CAT)
        # se o reconhecer medir que o productCatId também é Int64, ele acompanha o achados
        with mock.patch.dict(C.TIPOS, {'productCatId': 'Int64'}):
            for int64, esperado in (('texto', str(CAT)), ('numero', CAT)):
                with self.subTest(int64=int64):
                    self.reabrir()
                    api = self.api()
                    self.garimpar(api, ['ams_keyseller'], int64=int64)
                    self.assertEqual(api.variaveis()[0]['productCatId'], esperado)

    def test_cat_como_texto_de_digitos_e_aceito_e_invalido_nao_pede(self):
        api = self.api()
        self.garimpar(api, ['sort'], cat=str(CAT))
        self.assertEqual(api.variaveis(), self.esperado_sort())
        for ruim in (0, -5, 'abc', None, True, 1.5):
            with self.subTest(ruim=ruim):
                with self.assertRaises(ValueError):
                    self.garimpar(self.api(), ['sort'], cat=ruim)

    def test_parametros_invalidos(self):
        for kw in (dict(int64='hex'), dict(int64=None), dict(list_types='4'), dict(list_types=[True]),
                   dict(list_types=[4.0]), dict(limit=0), dict(teto_pagina=0)):
            with self.subTest(kw=kw):
                api = self.api()
                with self.assertRaises(ValueError):
                    self.garimpar(api, ['sort'], **kw)
                self.assertEqual(api.pedidos, [])

    def test_parametros_do_achados(self):
        achados = {'limit': 50, 'teto_pagina': 7, 'int64': 'numero', 'list_types': [4], 'paginas_sem_novo': 2,
                   'estrategias': None, 'pausa': 1.0}
        self.assertEqual(M.parametros(achados), {'limit': 50, 'teto_pagina': 7, 'int64': 'numero',
                                                 'list_types': [4], 'paginas_sem_novo': 2})
        api = self.api()
        self.garimpar(api, achados['estrategias'], **M.parametros(achados))
        self.assertEqual(len(api.pedidos), 5 + 1 + 2)
        self.assertEqual(api.variaveis()[5], {'listType': 4, 'matchId': CAT, 'limit': 50, 'page': 1})

    def test_com_o_achados_real_a_ordem_padrao_pula_o_listtype_porque_list_types_e_vazio(self):
        """Etapa 8: o achados.json versionado deixa `estrategias` nulo (ordem do brief, que inclui `listtype`) e
        `list_types` vazio (o listType 4 só repete o productCatId, medicoes #33): a estratégia é pulada, sem pedido."""
        import garimpo as G
        achados = G.ler_achados()
        self.assertEqual((achados['estrategias'], achados['list_types'], achados['limit'], achados['teto_pagina']),
                         (None, [], 50, 40))
        self.assertIn('listtype', M.ORDEM_PADRAO)
        api = self.api()
        self.assertEqual(self.garimpar(api, achados['estrategias'], **M.parametros(achados)), 'esgotada')
        vs = api.variaveis()
        self.assertFalse([v for v in vs if 'listType' in v or 'matchId' in v])
        self.assertEqual(len(vs), 5 + 2)                              # 5 sortType + isAMSOffer e isKeySeller
        self.assertEqual({v['limit'] for v in vs}, {50})
        self.assertEqual([r[0] for r in self.linhas('SELECT estrategia FROM consultas ORDER BY id')],
                         ['sort'] * 5 + ['ams_keyseller'] * 2)
        # e o productCatId vai como número, que é o tipo Int do schema (medicoes #2)
        self.assertTrue(all(type(v['productCatId']) is int for v in vs))

    def test_estrategias_do_achados_validas_batem_com_o_regex_do_garimpo(self):
        import re
        for nome in M.ESTRATEGIAS:
            self.assertRegex(nome, r'[a-z][a-z0-9_]{0,39}')
        self.assertEqual(M.ORDEM_PADRAO, ('sort', 'listtype', 'ams_keyseller', 'fatiamento'))

    def test_teto_marca_bateu_teto_na_categoria_e_na_consulta(self):
        api = self.api(mais=True)
        self.assertEqual(self.garimpar(api, ['sort'], teto_pagina=2), 'teto')
        self.assertEqual({r[0] for r in self.linhas('SELECT status FROM consultas')}, {'teto'})
        self.assertEqual(self.linhas('SELECT cat_id, saturada, bateu_teto, parada FROM categories'),
                         [(str(CAT), 0, 1, M.PARADA['teto'])])
        self.assertEqual(len(api.pedidos), 5 * 2)

    def test_atualiza_a_linha_da_categoria_sem_apagar_o_que_o_mapa_gravou(self):
        self.con.execute("INSERT INTO categories (cat_id, nivel, nome, classe, nicho, frequencia) "
                         "VALUES (?, 3, 'Vestidos', 'feminina', 'roupasfemininas', 40)", (str(CAT),))
        self.garimpar(self.api(), ['sort'])
        self.assertEqual(self.linhas('SELECT nome, classe, nicho, frequencia, bateu_teto, parada FROM categories'),
                         [('Vestidos', 'feminina', 'roupasfemininas', 40, 0, M.PARADA['esgotada'])])

    def test_linha_existente_tambem_recebe_o_bateu_teto(self):
        self.con.execute('INSERT INTO categories (cat_id, nome) VALUES (?, ?)', (str(CAT), 'Vestidos'))
        self.garimpar(self.api(mais=True), ['sort'], teto_pagina=1)
        self.assertEqual(self.linhas('SELECT nome, bateu_teto, saturada FROM categories'), [('Vestidos', 1, 0)])

    def test_teto_de_requisicoes_sobe_e_a_categoria_nao_e_marcada(self):
        api = self.api()
        with comum.isolado(api):
            with self.assertRaises(K.Teto):
                M.garimpar_categoria(self.con, self.cliente(max_rodada=2), CAT, ['sort'], limit=20, teto_pagina=5)
        self.assertEqual(len(api.pedidos), 2)
        self.assertEqual(self.linhas('SELECT COUNT(*) FROM categories'), [(0,)])


# ---------- (4) fatiamento ----------
def titulos_de_vestido(v, i):
    """Títulos que dão os bigramas 'vestido longo' e 'longo floral'; a fatia 'vestido longo' ainda traz
    'cropped canelado' e 'canelado preto' (bola de neve)."""
    if v.get('keyword') == 'vestido longo':
        return lambda j: f'Cropped Canelado Preto {j}'
    return lambda j: f'Vestido Longo Floral {j}'


LIM_FATIA = 3   # limit do fatiamento nos testes: 3 títulos por fatia bastam para o bigrama (frequência mínima 3)


class TestFatiamento(Base):
    def api(self, mais=True, por=LIM_FATIA):
        """`mais`: toda página vem cheia (`por` itens = o limit do teste); sem ele, vem uma a menos, incompleta."""
        return ApiDinamica(lambda v, n: (por if mais else por - 1, titulos_de_vestido(v, n)))

    def garimpar(self, api, cli=None, **kw):
        kw = {'limit': LIM_FATIA, 'teto_pagina': 1, 'sementes': ['Vestido  Longo', 'saia midi'], **kw}
        with comum.isolado(api):
            return M.garimpar_categoria(self.con, cli or self.cliente(), CAT,
                                        kw.pop('estrategias', ['sort', 'fatiamento']), **kw)

    def palavras(self, api):
        return [v['keyword'] for v in api.variaveis() if 'keyword' in v]

    ESPERADAS = ['vestido longo', 'saia midi', 'longo floral', 'canelado preto', 'cropped canelado']

    def test_sementes_primeiro_depois_bigramas_em_bola_de_neve_sem_repetir(self):
        api = self.api()
        self.assertEqual(self.garimpar(api), 'teto')
        self.assertEqual(self.palavras(api), self.ESPERADAS)
        self.assertEqual(len(set(self.palavras(api))), len(self.palavras(api)))
        fatias = [v for v in api.variaveis() if 'keyword' in v]
        self.assertEqual(fatias[0], {'keyword': 'vestido longo', 'productCatId': CAT, 'sortType': 1,
                                    'limit': LIM_FATIA, 'page': 1})
        self.assertEqual(len(api.pedidos), 5 + len(self.ESPERADAS))
        self.assertEqual([r[0] for r in self.linhas('SELECT estrategia FROM consultas ORDER BY id')],
                         ['sort'] * 5 + ['fatiamento'] * 5)

    def test_a_bola_de_neve_so_aparece_depois_que_a_fatia_trouxe_os_titulos(self):
        api = self.api()
        self.garimpar(api)
        # 'cropped canelado' nasceu da fatia 'vestido longo' (a 1ª); antes dela nenhum título o tinha
        self.assertEqual(self.linhas("SELECT COUNT(*) FROM products WHERE nome LIKE 'Cropped%'"), [(3,)])
        self.assertNotIn('cropped canelado', self.palavras(api)[:2])

    def test_retomar_depois_de_terminar_nao_repete_nem_pede_nada(self):
        api = self.api()
        self.garimpar(api)
        n = len(api.pedidos)
        self.assertEqual(self.garimpar(api), 'teto')
        self.assertEqual(len(api.pedidos), n)
        self.assertEqual(self.linhas("SELECT COUNT(*) FROM consultas WHERE estrategia = 'fatiamento'"), [(5,)])

    def test_interromper_no_meio_e_retomar_nao_repete_o_mesmo_fatiamento(self):
        api = self.api()
        with self.assertRaises(K.Teto):
            self.garimpar(api, self.cliente(max_rodada=5 + 3))
        feitas = self.palavras(api)
        self.assertEqual(feitas, self.ESPERADAS[:3])
        self.assertEqual(self.garimpar(api), 'teto')
        todas = self.palavras(api)
        self.assertEqual(todas, self.ESPERADAS)             # as outras duas, sem repetir as 3 primeiras
        self.assertEqual(len(api.pedidos), 5 + 5)

    def test_fatiamento_so_quando_alguma_consulta_bateu_o_teto(self):
        api = self.api(mais=False)                           # tudo cabe numa página: nada de teto
        self.assertEqual(self.garimpar(api), 'esgotada')
        self.assertEqual(self.palavras(api), [])
        self.assertEqual(len(api.pedidos), 5)

    def test_sem_fatiamento_na_lista_do_achados_nao_fatia_mesmo_com_teto(self):
        api = self.api()
        self.assertEqual(self.garimpar(api, estrategias=['sort']), 'teto')
        self.assertEqual(self.palavras(api), [])

    def test_o_fatiamento_vem_depois_das_outras_na_ordem_padrao(self):
        api = self.api()
        self.garimpar(api, estrategias=None, list_types=[4])
        vs = api.variaveis()
        self.assertEqual([('sortType' in v and 'keyword' not in v, 'listType' in v, 'isAMSOffer' in v,
                           'isKeySeller' in v, 'keyword' in v) for v in vs][:9],
                         [(True, False, False, False, False)] * 5 + [(False, True, False, False, False),
                                                                      (False, False, True, False, False),
                                                                      (False, False, False, True, False),
                                                                      (False, False, False, False, True)])

    def test_a_saturacao_interrompe_o_fatiamento(self):
        # as 5 consultas de sort trazem só itens conhecidos: satura antes de fatiar
        cid = banco.obter_consulta(self.con, 'productOfferV2', {'x': 1}, fase='semente')['id']
        banco.gravar_pagina(self.con, cid, 1, [no(i, productName='Vestido Longo Floral') for i in range(1, 51)],
                            {'operacao': 'productOfferV2'})
        api = ApiFalsa(*[resposta([no(i, productName='Vestido Longo Floral') for i in range(1, 51)])
                         for _ in range(30)])
        self.assertEqual(self.garimpar(api), 'saturada')
        self.assertEqual(len(api.pedidos), 5)

    def test_limite_de_fatias_por_categoria(self):
        api = self.api()
        with mock.patch.object(M, 'MAX_FATIAS', 3):
            self.assertEqual(self.garimpar(api), 'teto')
        self.assertEqual(self.palavras(api), self.ESPERADAS[:3])
        with mock.patch.object(M, 'MAX_FATIAS', 3):          # o limite vale pelo total, também na retomada
            self.garimpar(api)
        self.assertEqual(self.palavras(api), self.ESPERADAS[:3])

    def test_na_retomada_as_fatias_ja_feitas_contam_no_limite_mas_so_elas(self):
        api = self.api()
        with mock.patch.object(M, 'MAX_FATIAS', 4):
            with self.assertRaises(K.Teto):
                self.garimpar(api, self.cliente(max_rodada=5 + 3))
            self.garimpar(api)
        self.assertEqual(self.palavras(api), self.ESPERADAS[:4])    # 3 da 1ª rodada + 1 da 2ª, nenhuma repetida

    def test_bigrama_exige_a_frequencia_minima_e_ignora_preposicao_numero_e_palavra_repetida(self):
        titulos = (['Vestido de Festa 2024'] * 3            # "de" e o número quebram a vizinhança
                   + ['Vestido Festa Rosa', 'Kit Vestido Festa', 'Vestido Festa Azul']   # "kit" é palavra vazia
                   + ['Saia Rosa Rosa'] * 3                  # 'rosa rosa' nunca; 'saia rosa' sim
                   + ['Camisa Polo Lisa'] * 2                # só 2 títulos: abaixo do mínimo
                   + ['Bolsa Tote Bolsa Tote', 'Bolsa Tote']  # 'bolsa tote' em 2 títulos (não 3 vezes)
                   + [None])
        for i, t in enumerate(titulos, 1):
            self.con.execute('INSERT INTO products (item_id, nome, cat_l3, raw_json, first_seen, last_seen) '
                             "VALUES (?, ?, ?, '{}', 'x', 'x')", (str(i), t, str(CAT)))
        self.con.execute("INSERT INTO products (item_id, nome, cat_l3, raw_json, first_seen, last_seen) "
                         "VALUES ('99', 'Vestido Festa Outra Categoria', '1', '{}', 'x', 'x')")
        self.assertEqual(M.bigramas_da_categoria(self.con, CAT), ['saia rosa', 'vestido festa'])

    def test_bigramas_olham_a_categoria_em_qualquer_nivel(self):
        for i in range(3):
            self.con.execute('INSERT INTO products (item_id, nome, cat_l1, cat_l2, cat_l3, raw_json, first_seen, '
                             "last_seen) VALUES (?, 'Bolsa Tote Grande', '7', ?, ?, '{}', 'x', 'x')",
                             (str(i + 1), str(CAT), '55'))
        self.assertEqual(M.bigramas_da_categoria(self.con, CAT), ['bolsa tote', 'tote grande'])
        self.assertEqual(M.bigramas_da_categoria(self.con, 7), ['bolsa tote', 'tote grande'])
        self.assertEqual(M.bigramas_da_categoria(self.con, 8), [])

    def test_sementes_repetidas_ou_vazias_viram_uma_so_fatia(self):
        api = self.api()
        self.garimpar(api, sementes=['Saia Midi', 'saia  midi', 'SAIA MIDI', '', '   ', None, 5, 'x' * 500])
        self.assertEqual(self.palavras(api)[0], 'saia midi')
        self.assertEqual(self.palavras(api).count('saia midi'), 1)
        self.assertNotIn('', self.palavras(api))

    def test_o_log_nao_traz_palavra_de_busca(self):
        api, mensagens = self.api(), []
        self.garimpar(api, log=mensagens.append)
        self.assertTrue(any('fatiamento' in m for m in mensagens))
        for m in mensagens:
            for palavra in self.ESPERADAS:
                self.assertNotIn(palavra, m)


class TestSementesDoNicho(unittest.TestCase):
    def test_le_as_sementes_do_nichos_json_real(self):
        s = M.sementes_do_nicho('roupasfemininas')
        self.assertEqual(s[:3], ['vestido', 'vestido longo', 'blusa feminina'])
        self.assertEqual(len(s), 22)

    def test_slug_desconhecido_ou_vazio_nao_tem_sementes(self):
        for slug in ('nao_existe', None, '', 5):
            self.assertEqual(M.sementes_do_nicho(slug), [])

    def test_arquivo_ruim_e_erro_de_configuracao(self):
        pasta = comum.nova_pasta()
        for i, texto in enumerate(['', 'não é json', '{}', '[1]', '[{"slug": "a", "sementes": "x"}]',
                                   '[{"slug": "a", "sementes": [1]}]']):
            with self.subTest(texto=texto):
                caminho = os.path.join(pasta, f'n{i}.json')
                with open(caminho, 'w', encoding='utf-8') as f:
                    f.write(texto)
                with self.assertRaises(banco.ErroConfig):
                    M.sementes_do_nicho('a', caminho)
        with self.assertRaises(banco.ErroConfig):
            M.sementes_do_nicho('a', os.path.join(pasta, 'nao-existe.json'))


if __name__ == '__main__':
    unittest.main()
