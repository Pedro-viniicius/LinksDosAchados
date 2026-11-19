#!/usr/bin/env python3
"""Testes do garimpo.py (etapa 4 do garimpo feminino: CA5, CA7, CA8 e CA9). Sem rede.

Rodar: python3 tools/garimpo_feminino/testes/test_cli.py -v

Os dois pontos de rede do coletar_shopee.py são trocados por falsos (`comum.isolado`), o `urlopen` falha, os
proxies apontam para 127.0.0.1:9 e o ACHADINHOS_DB e a pasta de dados vão para uma pasta temporária. Os
subprocessos trocam os openers antes de chamar o `main` (nenhum sai para a rede).
"""
import ast
import contextlib
import fcntl
import inspect
import io
import json
import os
import pty
import re
import shutil
import signal
import sqlite3
import stat
import subprocess
import sys
import termios
import threading
import types
import unittest
from unittest import mock

import comum  # noqa: F401  (isolamento: tem de vir antes dos módulos do garimpo)
from comum import APP_ID, CS, LINK, S, SECRET, URL_FIXA, ApiFalsa, ConferenciaFalsa, erro, http_erro, no, resposta

import banco  # noqa: E402
import cliente as K  # noqa: E402
import garimpo as G  # noqa: E402

PASTA = comum.PASTA
RE_LOG = re.compile(r'(conferir|mapa|exportar)-\d{8}-\d{6}(-\d+)?\.log')
RE_LINHA_LOG = re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2} \S')


def tearDownModule():
    # CA8: nenhum teste criou o achadinhos.db (nem o temporário)
    for sufixo in ('', '-wal', '-shm', '-journal'):
        assert not os.path.exists(S.DB + sufixo), 'o garimpo abriu o achadinhos.db'


def logs_da_pasta(pasta):
    pasta_logs = os.path.join(pasta, 'logs')
    return sorted(os.listdir(pasta_logs)) if os.path.isdir(pasta_logs) else []


class Resultado:
    def __init__(self, codigo, out, err, api, conferencia, esperas, pasta, logs_antes=()):
        self.codigo, self.out, self.err = codigo, out, err
        self.api, self.conferencia, self.esperas, self.pasta = api, conferencia, esperas, pasta
        self.logs_antes = set(logs_antes)

    @property
    def logs(self):
        return logs_da_pasta(self.pasta)

    @property
    def log(self):
        """Texto do log criado nesta rodada (tem de ser um só)."""
        novos = [n for n in self.logs if n not in self.logs_antes]
        assert len(novos) == 1, novos
        with open(os.path.join(self.pasta, 'logs', novos[0]), encoding='utf-8') as f:
            return f.read()

    @property
    def banco(self):
        return os.path.join(self.pasta, 'garimpo.db')

    def linhas(self, sql):
        con = sqlite3.connect(f'file:{self.banco}?mode=ro', uri=True)
        try:
            return con.execute(sql).fetchall()
        finally:
            con.close()


def rodar(argv, *, secret=SECRET, app_id=APP_ID, pasta=None, api=None, conferencia=None, achados=None,
          categorias=None, depois=None):
    """garimpo.main(argv) com credenciais falsas só no ambiente desta chamada, rede falsa e saída capturada.

    `achados`/`categorias` (dict) viram arquivos na pasta; sem eles, os caminhos apontam para arquivos que não
    existem (padrões). `depois()` roda ainda dentro do ambiente da chamada (ex.: conferir o pop do Secret)."""
    pasta = pasta or comum.nova_pasta()
    env = {'ACHADINHOS_GARIMPO_DIR': pasta}
    if app_id is not None:
        env['ACHADINHOS_SHOPEE_APP_ID'] = app_id
    if secret is not None:
        env['ACHADINHOS_SHOPEE_SECRET'] = secret
    arq_achados = os.path.join(pasta, 'achados-teste.json')
    arq_categorias = os.path.join(pasta, 'categorias-teste.json')
    for caminho, dados in ((arq_achados, achados), (arq_categorias, categorias)):
        if dados is not None:
            with open(caminho, 'w', encoding='utf-8') as f:
                json.dump(dados, f)
        elif os.path.exists(caminho):
            os.remove(caminho)
    out, err, antes = io.StringIO(), io.StringIO(), logs_da_pasta(pasta)
    with mock.patch.dict(os.environ, env), \
            mock.patch.object(G, 'ACHADOS', arq_achados), mock.patch.object(G, 'CATEGORIAS', arq_categorias), \
            comum.isolado(api, conferencia) as (api, conf, esperas), \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        codigo = G.main(argv)
        if depois:
            depois()
    return Resultado(codigo, out.getvalue(), err.getvalue(), api, conf, esperas, pasta, antes)


class Base(unittest.TestCase):
    def sem_vazamento(self, r):
        """CA5: nem o Secret nem a assinatura em stdout, stderr, log ou banco."""
        tudo = comum.conteudo_da_pasta(r.pasta)
        for texto in (r.out, r.err):
            self.assertNotIn(SECRET, texto)
            self.assertNotIn('Signature=', texto)
            self.assertNotIn('Traceback', texto)
        self.assertNotIn(SECRET.encode(), tudo)
        self.assertNotIn(b'Signature=', tudo)

    def ultima_linha(self, r):
        return r.log.rstrip('\n').split('\n')[-1]


# ---------- CA5 e CA7: credencial ----------
class TestCredencial(Base):
    def test_secret_ausente_sai_com_2_sem_rede_e_sem_banco(self):
        r = rodar(['conferir'], secret=None)
        self.assertEqual(r.codigo, 2)
        self.assertEqual(r.api.pedidos, [])
        self.assertEqual(r.conferencia.links, [])
        self.assertIn('ACHADINHOS_SHOPEE_SECRET', r.err)
        self.assertFalse(os.path.exists(r.banco), 'sem credencial, nenhum banco é aberto')
        self.assertFalse(os.path.exists(os.path.join(r.pasta, 'garimpo.lock')))
        self.assertEqual(self.ultima_linha(r), 'SAIDA=2')

    def test_secret_vazio_e_app_id_ausente_ou_invalido_saem_com_2(self):
        for secret, app_id in (('', APP_ID), (SECRET, None), (SECRET, 'abc def'), (SECRET, 'x' * 65)):
            with self.subTest(app_id=app_id, secret=bool(secret)):
                r = rodar(['conferir'], secret=secret, app_id=app_id)
                self.assertEqual(r.codigo, 2)
                self.assertEqual(r.api.pedidos, [])
                self.assertFalse(os.path.exists(r.banco))
                self.sem_vazamento(r)

    def test_o_secret_sai_do_ambiente_assim_que_e_lido(self):
        visto = []
        r = rodar(['conferir'], depois=lambda: visto.append('ACHADINHOS_SHOPEE_SECRET' in os.environ))
        self.assertEqual(r.codigo, 0)
        self.assertEqual(visto, [False])

    def test_credenciais_antes_de_qualquer_banco(self):
        ordem, caminhos = [], []
        cred_real, connect_real = CS.credenciais, sqlite3.connect

        def cred():
            ordem.append('credenciais')
            return cred_real()

        def connect(caminho, *a, **k):
            ordem.append('banco')
            caminhos.append(os.path.abspath(caminho))
            return connect_real(caminho, *a, **k)

        with mock.patch.object(CS, 'credenciais', cred), mock.patch.object(sqlite3, 'connect', connect):
            r = rodar(['conferir'])
            self.assertEqual(r.codigo, 0)
            self.assertEqual(ordem[0], 'credenciais')
            self.assertEqual(ordem.count('credenciais'), 1)
            self.assertIn('banco', ordem)
            self.assertEqual(caminhos, [os.path.abspath(r.banco)])
            # sem credencial: nenhum sqlite3.connect
            ordem.clear()
            r = rodar(['conferir'], secret=None)
            self.assertEqual(r.codigo, 2)
            self.assertEqual(ordem, ['credenciais'])

    def test_id_de_afiliado_vazio_sai_com_2(self):
        with mock.patch.object(CS, 'ID_AFILIADO_SHOPEE', ''):
            r = rodar(['conferir'])
        self.assertEqual(r.codigo, 2)
        self.assertEqual(r.api.pedidos, [])
        self.assertFalse(os.path.exists(r.banco))


# ---------- conferir e saídas 0/1/2/3/130 ----------
class TestConferir(Base):
    def test_ok_faz_uma_requisicao_e_confere_o_dono(self):
        api = ApiFalsa(resposta([no(1, offerLink='https://shopee.com.br/x'), no(2), no(3)]))
        r = rodar(['conferir'], api=api)
        self.assertEqual(r.codigo, 0, r.err)
        self.assertEqual(len(api.pedidos), 1)
        pedido = api.pedidos[0]
        self.assertEqual(pedido.full_url, URL_FIXA)
        self.assertIn('Signature=', pedido.get_header('Authorization'))   # o marcador existe no pedido…
        self.assertEqual(api.corpos()[0], {'query': CS.CONSULTA, 'variables': G.VARIAVEIS_CONFERIR})
        self.assertEqual(api.timeouts, [CS.TIMEOUT])
        self.assertEqual(r.conferencia.links, [LINK])   # só o 1º link curto de afiliado
        self.assertIn(f'OK: o link gerado pela API é do afiliado {CS.ID_AFILIADO_SHOPEE}', r.out)
        self.assertEqual(r.linhas('SELECT consulta_id, pagina, operacao, http, codigo, n_nos FROM requisicoes'),
                         [(None, None, 'productOfferV2', 200, None, None)])
        self.assertEqual(r.linhas('SELECT COUNT(*) FROM products'), [(0,)])
        self.assertEqual(self.ultima_linha(r), 'SAIDA=0')
        self.sem_vazamento(r)   # …e não aparece em lugar nenhum

    def test_dono_errado_sai_com_1(self):
        r = rodar(['conferir'], conferencia=ConferenciaFalsa(id_afiliado='99999'))
        self.assertEqual(r.codigo, 1)
        self.assertIn('PAROU', r.err)
        self.assertEqual(self.ultima_linha(r), 'SAIDA=1')
        self.sem_vazamento(r)

    def test_sem_link_curto_sai_com_1_sem_conferir(self):
        for nos in ([], [no(1, offerLink='https://evil.com/x')], [no(1, offerLink=LINK + 'a' * 300)], ['x']):
            with self.subTest(nos=str(nos)[:40]):
                r = rodar(['conferir'], api=ApiFalsa(resposta(nos)))
                self.assertEqual(r.codigo, 1)
                self.assertEqual(r.conferencia.links, [])
                self.assertIn('não trouxe link', r.err)

    def test_resposta_fora_do_formato_sai_com_1(self):
        for corpo in ({'data': {}}, {'data': {'productOfferV2': {'nodes': {}}}}, {'data': {'productOfferV2': []}},
                      {'x': 1}, b'nao json', [1]):
            with self.subTest(corpo=str(corpo)[:40]):
                r = rodar(['conferir'], api=ApiFalsa(corpo))
                self.assertEqual(r.codigo, 1)
                self.assertIn('fora do formato', r.err)
                self.assertEqual(r.conferencia.links, [])

    def test_api_recusa_sai_com_1_sem_texto_da_api(self):
        casos = (erro(10020, 'Invalid Signature ' + SECRET), http_erro(500, {'x': SECRET}, motivo='erro ' + SECRET),
                 http_erro(302, location='https://evil.com/' + SECRET), OSError('rede ' + SECRET))
        for caso in casos:
            with self.subTest(caso=type(caso).__name__):
                r = rodar(['conferir'], api=ApiFalsa(caso))
                self.assertEqual(r.codigo, 1)
                self.assertIn('ERRO: a API da Shopee', r.err)
                self.assertEqual(len(r.linhas('SELECT * FROM requisicoes')), 1)
                self.sem_vazamento(r)
        r = rodar(['conferir'], api=ApiFalsa(http_erro(500)))
        self.assertIn('HTTP 500', r.err)

    def test_limite_da_api_sai_com_3_depois_das_esperas(self):
        api = ApiFalsa(*[erro(CS.ERRO_LIMITE)] * (K.TENTATIVAS_LIMITE + 1))
        r = rodar(['conferir'], api=api)
        self.assertEqual(r.codigo, 3)
        self.assertEqual(len(api.pedidos), K.TENTATIVAS_LIMITE + 1)
        self.assertEqual(sum(1 for s in r.esperas if s >= K.BACKOFF_BASE * K.BACKOFF_FATOR[0]),
                         K.TENTATIVAS_LIMITE)
        self.assertEqual(r.linhas('SELECT COUNT(*), MIN(codigo), MAX(codigo) FROM requisicoes'),
                         [(K.TENTATIVAS_LIMITE + 1, CS.ERRO_LIMITE, CS.ERRO_LIMITE)])
        self.assertIn('PAROU: limite', r.err)
        self.assertEqual(self.ultima_linha(r), 'SAIDA=3')

    def test_teto_total_conta_as_requisicoes_ja_gravadas(self):
        pasta = comum.nova_pasta()
        self.assertEqual(rodar(['conferir'], pasta=pasta).codigo, 0)
        api = ApiFalsa()
        r = rodar(['conferir'], pasta=pasta, api=api, achados={'max_total_requests': 1})
        self.assertEqual(r.codigo, 3)
        self.assertEqual(api.pedidos, [], 'o teto é conferido antes de mandar')
        self.assertIn('teto de requisições total', r.err)
        r = rodar(['conferir'], pasta=pasta, achados={'max_total_requests': 2})
        self.assertEqual(r.codigo, 0)

    def test_ctrl_c_sai_com_130_e_solta_a_trava(self):
        r = rodar(['conferir'], api=ApiFalsa(KeyboardInterrupt()))
        self.assertEqual(r.codigo, 130)
        self.assertIn('Interrompido', r.err)
        self.assertEqual(self.ultima_linha(r), 'SAIDA=130')
        with banco.travar(r.pasta):   # a trava foi solta
            pass
        self.assertEqual(rodar(['conferir'], pasta=r.pasta).codigo, 0)

    def test_outra_rodada_em_andamento_sai_com_2(self):
        pasta = comum.nova_pasta()
        with banco.travar(pasta):
            r = rodar(['conferir'], pasta=pasta)
        self.assertEqual(r.codigo, 2)
        self.assertIn('outra rodada', r.err)
        self.assertEqual(r.api.pedidos, [])
        self.assertFalse(os.path.exists(r.banco))

    def test_banco_que_nao_e_o_garimpo_sai_com_2_sem_mudar(self):
        pasta = comum.nova_pasta()
        caminho = os.path.join(pasta, 'garimpo.db')
        con = sqlite3.connect(caminho)
        con.execute('CREATE TABLE items (id INTEGER)')
        con.commit()
        con.close()
        with open(caminho, 'rb') as f:
            antes = f.read()
        r = rodar(['conferir'], pasta=pasta)
        self.assertEqual(r.codigo, 2)
        self.assertIn('não é um garimpo.db', r.err)
        self.assertEqual(r.api.pedidos, [])
        with open(caminho, 'rb') as f:
            self.assertEqual(f.read(), antes)

    def test_falha_inesperada_sai_com_1_so_com_o_tipo(self):
        with mock.patch.object(G, 'links_da_resposta', side_effect=ValueError('dado ' + SECRET)):
            r = rodar(['conferir'])
        self.assertEqual(r.codigo, 1)
        self.assertIn('ERRO: ValueError', r.err)
        self.sem_vazamento(r)

    def test_argumento_invalido_sai_com_2(self):
        for argv in ([], ['nada'], ['conferir', '--max-req', '5']):
            with self.subTest(argv=argv), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as ctx:
                    G.ler_argumentos(argv)
                self.assertEqual(ctx.exception.code, 2)


# ---------- log ----------
class TestLog(Base):
    def test_nome_modo_data_e_ultima_linha(self):
        r = rodar(['conferir'])
        self.assertEqual(len(r.logs), 1)
        self.assertRegex(r.logs[0], RE_LOG)
        self.assertTrue(r.logs[0].startswith('conferir-'))
        caminho = os.path.join(r.pasta, 'logs', r.logs[0])
        self.assertEqual(stat.S_IMODE(os.stat(caminho).st_mode), 0o600)
        linhas = r.log.rstrip('\n').split('\n')
        self.assertEqual(linhas[-1], 'SAIDA=0')
        for linha in linhas[:-1]:
            self.assertRegex(linha, RE_LINHA_LOG)
        # tudo o que foi para a tela está no log
        for linha in (r.out + r.err).splitlines():
            self.assertIn(linha, r.log)

    def test_duas_rodadas_no_mesmo_segundo_nao_se_sobrescrevem(self):
        pasta = comum.nova_pasta()
        a = G.Log.abrir(pasta, 'conferir', instante=1_762_400_000)
        b = G.Log.abrir(pasta, 'conferir', instante=1_762_400_000)
        with contextlib.redirect_stdout(io.StringIO()):
            a('um'), b('dois')
        a.fechar(0), b.fechar(1)
        self.assertNotEqual(a.caminho, b.caminho)
        self.assertTrue(b.caminho.endswith('-2.log'))
        with open(b.caminho, encoding='utf-8') as f:
            self.assertEqual(f.read().split('\n')[-2], 'SAIDA=1')

    def test_controle_vira_espaco(self):
        pasta = comum.nova_pasta()
        log = G.Log.abrir(pasta, 'conferir')
        with contextlib.redirect_stdout(io.StringIO()) as out:
            log('a\rb\x1b[31mc\nd\x85e')
        log.fechar(0)
        with open(log.caminho, encoding='utf-8') as f:
            texto = f.read()
        self.assertEqual(texto.count('\n'), 2)
        for c in ('\r', '\x1b', '\x85'):
            self.assertNotIn(c, texto)
            self.assertNotIn(c, out.getvalue())

    def test_pasta_de_logs_impossivel_sai_com_2(self):
        pasta = comum.nova_pasta()
        with open(os.path.join(pasta, 'logs'), 'w'):
            pass
        r = rodar(['conferir'], pasta=pasta)
        self.assertEqual(r.codigo, 2)
        self.assertIn('logs/', r.err)
        self.assertEqual(r.api.pedidos, [])


# ---------- achados.json e categorias.json ----------
class TestAchados(Base):
    def escrever(self, conteudo):
        caminho = os.path.join(comum.nova_pasta(), 'achados.json')
        with open(caminho, 'wb') as f:
            f.write(conteudo if isinstance(conteudo, bytes) else json.dumps(conteudo).encode())
        return caminho

    def test_ausente_da_os_padroes_sem_alterar_o_padrao(self):
        a = G.ler_achados(os.path.join(comum.TMP, 'nao-existe.json'))
        self.assertEqual(a, G.PADROES_ACHADOS)
        a['list_types'].append(1)
        self.assertEqual(G.PADROES_ACHADOS['list_types'], [])
        self.assertEqual(G.PADROES_ACHADOS['max_total_requests'], 20_000)
        self.assertEqual(G.ler_achados(self.escrever({})), G.PADROES_ACHADOS)

    def test_valores_validos_e_bordas(self):
        validos = {'limit': 500, 'teto_pagina': 1, 'int64': 'numero', 'list_types': [0, 3, 4, 5],
                   'separador_subids': '_', 'estrategias': ['sort', 'listtype', 'fatiar_keyword'],
                   'orcamento_aprovado': 35_000, 'max_total_requests': 1_000_000, 'pausa': 0.5,
                   'paginas_sem_novo': 100}
        a = G.ler_achados(self.escrever(validos))
        self.assertEqual(a, validos)
        for chave, valor in (('limit', 1), ('pausa', 60), ('pausa', 1.7), ('orcamento_aprovado', None),
                             ('separador_subids', '-'), ('estrategias', None), ('list_types', [])):
            with self.subTest(chave=chave, valor=valor):
                self.assertEqual(G.ler_achados(self.escrever({chave: valor}))[chave], valor)
        self.assertIsInstance(G.ler_achados(self.escrever({'pausa': 2}))['pausa'], float)

    def test_invalidos_saem_com_erro_de_config(self):
        casos = [[], 'x', None, {'chave_nova': 1}, {'limit': 0}, {'limit': 501}, {'limit': True}, {'limit': '20'},
                 {'limit': 20.0}, {'teto_pagina': 0}, {'teto_pagina': 10_001}, {'int64': 'num'}, {'int64': 1},
                 {'list_types': [6]}, {'list_types': [1, 1]}, {'list_types': [True]}, {'list_types': 1},
                 {'separador_subids': 'a'}, {'separador_subids': '--'}, {'separador_subids': ' '},
                 {'separador_subids': ''}, {'estrategias': []}, {'estrategias': ['Sort']}, {'estrategias': ['a', 'a']},
                 {'estrategias': [1]}, {'estrategias': 'sort'}, {'orcamento_aprovado': 0},
                 {'orcamento_aprovado': 1_000_001}, {'max_total_requests': 0}, {'max_total_requests': None},
                 {'pausa': 0.49}, {'pausa': 60.01}, {'pausa': True}, {'pausa': '1'}, {'paginas_sem_novo': 0},
                 {'paginas_sem_novo': 101}]
        for caso in casos:
            with self.subTest(caso=caso):
                with self.assertRaises(banco.ErroConfig):
                    G.ler_achados(self.escrever(caso))
        for bruto in (b'{"limit": 20, "limit": 30}', b'{"pausa": NaN}', b'{"pausa": Infinity}', b'\xff\xfe{}',
                      b'{', b'[' * 100_000 + b']' * 100_000, b' ' * (G.MAX_CONFIG + 1)):
            with self.subTest(bruto=bruto[:30]):
                with self.assertRaises(banco.ErroConfig):
                    G.ler_achados(self.escrever(bruto))

    def test_no_teto_de_bytes_entra(self):
        corpo = b'{"limit": 30}'
        self.assertEqual(G.ler_achados(self.escrever(corpo + b' ' * (G.MAX_CONFIG - len(corpo))))['limit'], 30)

    def test_symlink_pasta_e_fifo_sao_recusados(self):
        pasta = comum.nova_pasta()
        alvo = self.escrever({'limit': 30})
        link = os.path.join(pasta, 'link.json')
        os.symlink(alvo, link)
        fifo = os.path.join(pasta, 'fifo.json')
        os.mkfifo(fifo)
        for caminho in (link, pasta, fifo):
            with self.subTest(caminho=os.path.basename(caminho)):
                with self.assertRaises(banco.ErroConfig):
                    G.ler_achados(caminho)

    def test_mensagem_nao_ecoa_o_conteudo(self):
        try:
            G.ler_achados(self.escrever({'SEGREDO-NA-CHAVE': 'VALOR-ESTRANHO'}))
        except banco.ErroConfig as e:
            self.assertNotIn('SEGREDO-NA-CHAVE', str(e))
            self.assertNotIn('VALOR-ESTRANHO', str(e))
        else:
            self.fail('aceitou chave fora da lista')

    def test_achados_invalido_sai_com_2_sem_rede_e_sem_banco(self):
        r = rodar(['conferir'], achados={'limit': 'muito'})
        self.assertEqual(r.codigo, 2)
        self.assertIn('achados.json', r.err)
        self.assertEqual(r.api.pedidos, [])
        self.assertFalse(os.path.exists(r.banco))

    def test_pausa_e_teto_do_achados_chegam_ao_cliente(self):
        vistos = []
        real = K.Cliente

        def espiao(*a, **k):
            c = real(*a, **k)
            vistos.append(c)
            return c

        with mock.patch.object(K, 'Cliente', espiao):
            r = rodar(['conferir'], achados={'pausa': 2.5, 'max_total_requests': 777})
        self.assertEqual(r.codigo, 0)
        self.assertEqual((vistos[0].pausa, vistos[0].max_total, vistos[0].max_rodada, vistos[0].ja_feitas),
                         (2.5, 777, None, 0))

    def test_os_arquivos_reais_da_pasta_sao_validos(self):
        """Etapas 8 e 13: o achados.json e o categorias.json versionados passam na leitura estrita."""
        self.assertEqual(set(G.ler_achados()), set(G.PADROES_ACHADOS))
        self.assertIsInstance(G.ler_categorias(), dict)
        self.assertEqual(len(G.ler_nichos()), 18)

    def test_o_achados_json_real_existe_e_traz_os_valores_medidos_no_r1(self):
        """Etapa 8, parte B: o arquivo versionado (não o padrão do código) com o que o R1 mediu. Lê o arquivo
        REAL da pasta, sem `rodar` (que o troca por um de teste)."""
        self.assertEqual(G.ACHADOS, os.path.join(comum.PASTA, 'achados.json'))
        self.assertTrue(os.path.isfile(G.ACHADOS) and not os.path.islink(G.ACHADOS))
        bruto = G.ler_json_estrito(G.ACHADOS, 'achados.json')
        self.assertIsInstance(bruto, dict)
        self.assertEqual(set(bruto), set(G.PADROES_ACHADOS), 'todas as chaves escritas, nenhuma só por padrão')
        self.assertEqual(G.ler_achados(), bruto)                       # passa na validação estrita, nada a completar
        # medicoes #5 e #77 (limit 50 e página 40 cheia), #81 (teto de 2.000 itens por consulta)
        self.assertEqual((bruto['limit'], bruto['teto_pagina']), (50, 40))
        self.assertEqual(bruto['limit'] * bruto['teto_pagina'], 2000)
        # medicoes #37 e #38: Int64 como número dá 10010, como texto passa
        self.assertEqual(bruto['int64'], 'texto')
        # medicoes #32 e #33: o listType 4 devolve o mesmo que o productCatId e os outros nada que sirva
        self.assertEqual(bruto['list_types'], [])
        # o resto fica nos padrões do código
        for chave in ('estrategias', 'max_total_requests', 'pausa', 'paginas_sem_novo'):
            self.assertEqual(bruto[chave], G.PADROES_ACHADOS[chave], chave)
        # quem aprova o orçamento é o dono, no R3; o separador dos subIds só aparece depois de cliques
        self.assertIsNone(bruto['orcamento_aprovado'])
        self.assertIsNone(bruto['separador_subids'])
        # ints são ints e a pausa vira float na leitura
        for chave in ('limit', 'teto_pagina', 'max_total_requests', 'paginas_sem_novo'):
            self.assertIs(type(bruto[chave]), int, chave)
        self.assertIsInstance(G.ler_achados()['pausa'], float)

    def test_o_achados_json_real_nao_leva_texto_de_produto_nem_link_nem_segredo(self):
        with open(G.ACHADOS, 'rb') as f:
            bruto = f.read()
        self.assertTrue(bruto.isascii())
        for proibido in (b'http', b'shopee', b'Secret', b'Signature', b'utm_'):
            self.assertNotIn(proibido.lower(), bruto.lower())


class TestCategorias(Base):
    NICHOS = frozenset({'maquiagem', 'gestante'})

    def escrever(self, conteudo):
        caminho = os.path.join(comum.nova_pasta(), 'categorias.json')
        with open(caminho, 'wb') as f:
            f.write(conteudo if isinstance(conteudo, bytes) else json.dumps(conteudo).encode())
        return caminho

    def test_ausente_e_vazio(self):
        self.assertEqual(G.ler_categorias(os.path.join(comum.TMP, 'nao-existe.json'), self.NICHOS), {})
        self.assertEqual(G.ler_categorias(self.escrever({}), self.NICHOS), {})

    def test_valido(self):
        dados = {'100017': {'classe': 'feminina', 'nicho': 'maquiagem', 'nome': 'Batom'},
                 '100104': {'classe': 'mista', 'nicho': None}, '9223372036854775807': {'classe': 'fora'}}
        self.assertEqual(G.ler_categorias(self.escrever(dados), self.NICHOS), {
            '100017': {'classe': 'feminina', 'nicho': 'maquiagem', 'nome': 'Batom'},
            '100104': {'classe': 'mista', 'nicho': None, 'nome': None},
            '9223372036854775807': {'classe': 'fora', 'nicho': None, 'nome': None}})

    def test_invalidos(self):
        bom = {'classe': 'feminina', 'nicho': 'maquiagem'}
        casos = [[], {'0': bom}, {'01': bom}, {'abc': bom}, {'9223372036854775808': bom}, {'1 ': bom},
                 {'1': {'nicho': 'maquiagem'}}, {'1': {'classe': 'outra'}}, {'1': {'classe': 1}},
                 {'1': {'classe': 'feminina', 'nicho': 'roupas'}}, {'1': {'classe': 'feminina', 'nicho': 5}},
                 {'1': {'classe': 'feminina', 'extra': 1}}, {'1': {'classe': 'feminina', 'nome': ''}},
                 {'1': {'classe': 'feminina', 'nome': 'a\nb'}}, {'1': {'classe': 'feminina', 'nome': 'a' * 201}},
                 {'1': 'feminina'}, {'1': None}]
        for caso in casos:
            with self.subTest(caso=str(caso)[:60]):
                with self.assertRaises(banco.ErroConfig):
                    G.ler_categorias(self.escrever(caso), self.NICHOS)

    def test_nicho_vem_do_nichos_json_real(self):
        caminho = self.escrever({'1': {'classe': 'feminina', 'nicho': 'gestante'}})
        self.assertEqual(G.ler_categorias(caminho)['1']['nicho'], 'gestante')
        with self.assertRaises(banco.ErroConfig):
            G.ler_categorias(self.escrever({'1': {'classe': 'feminina', 'nicho': 'Gestante'}}))

    def test_categorias_invalido_sai_com_2(self):
        r = rodar(['conferir'], categorias={'1': {'classe': 'talvez'}})
        self.assertEqual(r.codigo, 2)
        self.assertIn('categorias.json', r.err)
        self.assertEqual(r.api.pedidos, [])
        self.assertFalse(os.path.exists(r.banco))


# ---------- despacho sob demanda ----------
def fase_falsa(nome, *, usa_api=True, codigo=0, erro_rodar=None):
    m = types.ModuleType(nome)
    m.chamadas = []

    def configurar(parser):
        parser.add_argument('--cor', default='azul')

    def rodar_fase(args, ctx):
        m.chamadas.append((args, ctx))
        if erro_rodar:
            raise erro_rodar
        if ctx.cliente is not None:
            ctx.cliente.pedir(CS.CONSULTA, {'keyword': 'x'}, registrar=ctx.registrar)
        return codigo

    m.configurar, m.rodar = configurar, rodar_fase
    if not usa_api:
        m.USA_API = False
    return m


class TestDespacho(Base):
    def com_fase(self, modulo):
        return mock.patch.dict(sys.modules, {modulo.__name__: modulo})

    def test_conferir_nao_importa_nenhuma_fase(self):
        importados = []
        real = G.importlib.import_module
        with mock.patch.object(G.importlib, 'import_module',
                               side_effect=lambda n, *a: importados.append(n) or real(n, *a)):
            self.assertEqual(rodar(['conferir']).codigo, 0)
        self.assertEqual(importados, [])

    def test_so_a_fase_pedida_e_importada(self):
        m = fase_falsa('fase_teste_mapa')
        importados = []
        real = G.importlib.import_module
        with self.com_fase(m), mock.patch.dict(G.SUBCOMANDOS, {'mapa': 'fase_teste_mapa'}), \
                mock.patch.object(G.importlib, 'import_module',
                                  side_effect=lambda n, *a: importados.append(n) or real(n, *a)):
            r = rodar(['mapa', '--cor', 'rosa', '--max-req', '7'])
        self.assertEqual(r.codigo, 0, r.err)
        self.assertEqual(importados, ['fase_teste_mapa'])
        args, ctx = m.chamadas[0]
        self.assertEqual((args.sub, args.cor, args.max_req), ('mapa', 'rosa', 7))
        self.assertEqual(ctx.cliente.max_rodada, 7)
        self.assertEqual(ctx.achados, G.PADROES_ACHADOS)
        self.assertEqual(ctx.pasta, r.pasta)
        self.assertEqual(r.linhas('SELECT COUNT(*) FROM requisicoes'), [(1,)])
        self.assertNotIn('Segredo', repr(ctx))
        self.assertFalse(hasattr(ctx, 'cred'))
        self.sem_vazamento(r)

    def test_max_req_estoura_e_sai_com_3(self):
        m = fase_falsa('fase_teste_mapa')

        def duas(args, ctx):
            for _ in range(2):
                ctx.cliente.pedir(CS.CONSULTA, {'keyword': 'x'}, registrar=ctx.registrar)
            return 0

        m.rodar = duas
        with self.com_fase(m), mock.patch.dict(G.SUBCOMANDOS, {'mapa': 'fase_teste_mapa'}):
            r = rodar(['mapa', '--max-req', '1'])
        self.assertEqual(r.codigo, 3)
        self.assertEqual(len(r.api.pedidos), 1)
        self.assertIn('--max-req', r.err)

    def test_max_req_invalido_e_erro_de_argumento(self):
        m = fase_falsa('fase_teste_mapa')
        for valor in ('0', '-1', 'x', '1000001'):
            with self.subTest(valor=valor), self.com_fase(m), \
                    mock.patch.dict(G.SUBCOMANDOS, {'mapa': 'fase_teste_mapa'}), \
                    contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as ctx:
                    G.ler_argumentos(['mapa', '--max-req', valor])
                self.assertEqual(ctx.exception.code, 2)

    def test_fase_sem_api_nao_le_credencial(self):
        m = fase_falsa('fase_teste_exportar', usa_api=False)
        with self.com_fase(m), mock.patch.dict(G.SUBCOMANDOS, {'exportar': 'fase_teste_exportar'}), \
                mock.patch.object(CS, 'credenciais', side_effect=AssertionError('leu a credencial')):
            r = rodar(['exportar'], secret=None, app_id=None)
        self.assertEqual(r.codigo, 0, r.err)
        self.assertIsNone(m.chamadas[0][1].cliente)
        self.assertEqual(r.api.pedidos, [])
        with self.com_fase(m), mock.patch.dict(G.SUBCOMANDOS, {'exportar': 'fase_teste_exportar'}), \
                contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                G.ler_argumentos(['exportar', '--max-req', '3'])   # sem API, sem --max-req

    def test_fase_ainda_nao_implementada_sai_com_2(self):
        with mock.patch.dict(G.SUBCOMANDOS, {'mapa': 'fase_que_nao_existe_ainda'}):
            r = rodar(['mapa'])
        self.assertEqual(r.codigo, 2)
        self.assertIn('ainda não foi implementado', r.err)
        self.assertEqual(r.api.pedidos, [])
        self.assertFalse(os.path.exists(r.banco))

    def test_import_quebrado_dentro_da_fase_nao_vira_nao_implementada(self):
        with mock.patch.object(G.importlib, 'import_module',
                               side_effect=ModuleNotFoundError('x', name='dependencia_qualquer')), \
                mock.patch.dict(G.SUBCOMANDOS, {'mapa': 'fase_teste_mapa'}):
            with self.assertRaises(ModuleNotFoundError):
                G.ler_argumentos(['mapa'])

    def test_fase_sem_configurar_ou_rodar_e_recusada(self):
        m = types.ModuleType('fase_teste_mapa')
        m.configurar = lambda p: None
        with self.com_fase(m), mock.patch.dict(G.SUBCOMANDOS, {'mapa': 'fase_teste_mapa'}):
            with self.assertRaises(TypeError):
                G.ler_argumentos(['mapa'])

    def test_codigo_da_fase_e_repassado_e_o_invalido_vira_1(self):
        for codigo, esperado in ((0, 0), (1, 1), (2, 2), (3, 3), (130, 130), (5, 1), (None, 1), (True, 1),
                                 ('0', 1)):
            with self.subTest(codigo=codigo):
                m = fase_falsa('fase_teste_mapa', codigo=codigo)
                with self.com_fase(m), mock.patch.dict(G.SUBCOMANDOS, {'mapa': 'fase_teste_mapa'}):
                    r = rodar(['mapa'])
                self.assertEqual(r.codigo, esperado)
                self.assertEqual(self.ultima_linha(r), f'SAIDA={esperado}')

    def test_excecoes_da_fase_viram_as_saidas(self):
        casos = ((K.Teto('total'), 3), (CS.LimiteAtingido(), 3), (CS.DonoErrado(), 1), (CS.ErroApi(10020), 1),
                 (CS.RespostaInvalida(), 1), (banco.ErroConfig('texto fixo'), 2), (KeyboardInterrupt(), 130),
                 (RuntimeError('mensagem ' + SECRET), 1))
        for exc, esperado in casos:
            with self.subTest(exc=type(exc).__name__):
                m = fase_falsa('fase_teste_mapa', erro_rodar=exc)
                with self.com_fase(m), mock.patch.dict(G.SUBCOMANDOS, {'mapa': 'fase_teste_mapa'}):
                    r = rodar(['mapa'])
                self.assertEqual(r.codigo, esperado)
                self.assertEqual(self.ultima_linha(r), f'SAIDA={esperado}')
                self.sem_vazamento(r)
                with banco.travar(r.pasta):   # trava solta em toda saída
                    pass

    def test_ajuda_lista_os_subcomandos_sem_importar_fase(self):
        with contextlib.redirect_stdout(io.StringIO()) as out, \
                mock.patch.object(G.importlib, 'import_module', side_effect=AssertionError('importou')):
            with self.assertRaises(SystemExit) as ctx:
                G.ler_argumentos(['-h'])
        self.assertEqual(ctx.exception.code, 0)
        for nome in G.SUBCOMANDOS:
            self.assertIn(nome, out.getvalue())


# ---------- CA5 e CA8 como script, em subprocesso ----------
SCRIPT = r'''
import json, os, sys, urllib.error, urllib.request, email.message, io
sys.path.insert(0, sys.argv[1])
import garimpo as G
segredo = os.environ.get('ACHADINHOS_SHOPEE_SECRET', '')   # só para montar as falhas com o marcador
modo = sys.argv[2]
class Resp(io.BytesIO):
    status = 200
def api(req, timeout=None):
    if modo == 'rede':
        raise OSError('rede caiu ' + segredo + ' ' + req.get_header('Authorization'))
    corpo = {'data': {'productOfferV2': {'nodes': [{'itemId': 1, 'offerLink': 'https://s.shopee.com.br/AbC123'}]}}}
    return Resp(json.dumps(corpo).encode())
def conferencia(req, timeout=None):
    h = email.message.Message()
    h['Location'] = 'https://shopee.com.br/p?utm_source=an_' + G.CS.ID_AFILIADO_SHOPEE
    raise urllib.error.HTTPError(req.full_url, 302, 'Found', h, io.BytesIO(b''))
def proibido(*a, **k):
    raise OSError('urlopen ' + segredo)
G.CS.OPENER_API.open = api
G.CS.OPENER_CONFERENCIA.open = conferencia
urllib.request.urlopen = proibido
sys.exit(G.main(['conferir']))
'''


class TestComoScript(Base):
    def ambiente(self, pasta, secret=True):
        env = dict(os.environ)   # já isolado pelo comum (proxies mortos, ACHADINHOS_DB temporário)
        env.update({'ACHADINHOS_GARIMPO_DIR': pasta, 'ACHADINHOS_SHOPEE_APP_ID': APP_ID,
                    'PYTHONDONTWRITEBYTECODE': '1'})
        if secret:
            env['ACHADINHOS_SHOPEE_SECRET'] = SECRET
        return env

    def rodar_sub(self, cmd, pasta, secret=True):
        antes = logs_da_pasta(pasta)
        p = subprocess.run(cmd, env=self.ambiente(pasta, secret), capture_output=True, text=True, timeout=60,
                           cwd=comum.RAIZ)
        r = Resultado(p.returncode, p.stdout, p.stderr, None, None, None, pasta, antes)
        self.sem_vazamento(r)
        self.assertEqual(self.ultima_linha(r), f'SAIDA={p.returncode}')
        for sufixo in ('', '-wal', '-shm'):
            self.assertFalse(os.path.exists(S.DB + sufixo), 'o achadinhos.db temporário foi criado')
        return r

    def test_script_sem_secret_sai_com_2(self):
        pasta = comum.nova_pasta()
        r = self.rodar_sub([sys.executable, os.path.join(PASTA, 'garimpo.py'), 'conferir'], pasta, secret=False)
        self.assertEqual(r.codigo, 2)
        self.assertIn('read -rs S', r.err)
        self.assertFalse(os.path.exists(r.banco))

    def test_script_ok_e_falha_de_rede_sem_vazar(self):
        pasta = comum.nova_pasta()
        r = self.rodar_sub([sys.executable, '-c', SCRIPT, PASTA, 'ok'], pasta)
        self.assertEqual(r.codigo, 0, r.err)
        self.assertIn('OK:', r.out)
        r = self.rodar_sub([sys.executable, '-c', SCRIPT, PASTA, 'rede'], pasta)
        self.assertEqual(r.codigo, 1)
        self.assertEqual(len(r.logs), 2)
        self.assertEqual(r.linhas('SELECT COUNT(*) FROM requisicoes'), [(2,)])


# ---------- R4 e S1: sinais reais e proteção do ambiente, em subprocesso ----------
# Sem rede: a API falsa avisa "PRONTO" e fica parada até chegar um sinal. O marcador do Secret é falso (comum.SECRET).
SCRIPT_PARADO = r'''
import signal, sys
sys.path.insert(0, sys.argv[1])
import garimpo as G
def api(req, timeout=None):
    print('PRONTO', flush=True)
    signal.pause()
    raise OSError('voltou da pausa')
G.CS.OPENER_API.open = api
sys.exit(G.main(['conferir']))
'''
SCRIPT_CONTROLE = "import signal\nprint('PRONTO', flush=True)\nsignal.pause()\n"
FOLGA = 30   # segundos até o relógio de guarda matar o subprocesso


def ler_environ(pid):
    """Só em subprocesso deste teste, com marcador falso."""
    with open(f'/proc/{pid}/environ', 'rb') as f:
        return f.read()


class Parado:
    """Sobe o script parado na API; `with` garante que nada sobra, mesmo com o teste falhando."""

    def __init__(self, script=SCRIPT_PARADO, *, ignorar_sighup=False, **popen):
        self.pasta = comum.nova_pasta()
        env = dict(os.environ, ACHADINHOS_GARIMPO_DIR=self.pasta, ACHADINHOS_SHOPEE_APP_ID=APP_ID,
                   ACHADINHOS_SHOPEE_SECRET=SECRET, PYTHONDONTWRITEBYTECODE='1')
        if ignorar_sighup:   # o que o nohup faz antes do exec
            popen['preexec_fn'] = lambda: signal.signal(signal.SIGHUP, signal.SIG_IGN)
        popen.setdefault('stdout', subprocess.PIPE)
        popen.setdefault('stderr', subprocess.PIPE)
        self.p = subprocess.Popen([sys.executable, '-c', script, PASTA], env=env, cwd=comum.RAIZ, **popen)
        self.guarda = threading.Timer(FOLGA, self.p.kill)
        self.guarda.start()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.guarda.cancel()
        if self.p.poll() is None:
            self.p.kill()
        self.p.wait()
        for f in (self.p.stdout, self.p.stderr):
            if f:
                f.close()

    def esperar_pronto(self):
        for linha in self.p.stdout:
            if b'PRONTO' in linha:
                return
        raise AssertionError('o subprocesso terminou antes de chegar à API')

    @property
    def log(self):
        pasta_logs = os.path.join(self.pasta, 'logs')
        nome = sorted(os.listdir(pasta_logs))[0]
        return os.path.join(pasta_logs, nome)

    def ler_log(self):
        with open(self.log, encoding='utf-8') as f:
            return f.read()


class TestSinais(unittest.TestCase):
    def conferir_saida_130(self, parado):
        self.assertEqual(parado.ler_log().rstrip('\n').split('\n')[-1], 'SAIDA=130')
        self.assertIn('Interrompido', parado.ler_log())
        self.assertNotIn(SECRET, parado.ler_log())
        with banco.travar(parado.pasta):   # trava solta
            pass
        con = sqlite3.connect(os.path.join(parado.pasta, 'garimpo.db'))
        try:
            self.assertEqual(con.execute('PRAGMA integrity_check').fetchone(), ('ok',))
            self.assertEqual(con.execute('SELECT COUNT(*) FROM requisicoes').fetchone(), (1,))   # o pedido interrompido
        finally:
            con.close()

    def test_sigterm_sighup_e_sigint_saem_com_130(self):
        for sinal in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
            with self.subTest(sinal=sinal.name), Parado() as parado:
                parado.esperar_pronto()
                parado.p.send_signal(sinal)
                self.assertEqual(parado.p.wait(timeout=FOLGA), 130)
                self.assertNotIn(b'Traceback', parado.p.stderr.read())
                self.conferir_saida_130(parado)

    def test_o_nohup_continua_valendo(self):
        """SIGHUP ignorado (nohup, o jeito de mandar a rodada longa para o fundo): fechar o terminal não a derruba."""
        with Parado(ignorar_sighup=True) as parado:
            parado.esperar_pronto()
            parado.p.send_signal(signal.SIGHUP)
            with self.assertRaises(subprocess.TimeoutExpired):
                parado.p.wait(timeout=0.5)
            parado.p.send_signal(signal.SIGTERM)   # o kill continua parando
            self.assertEqual(parado.p.wait(timeout=FOLGA), 130)
            self.conferir_saida_130(parado)

    def test_terminal_fechado_de_verdade_grava_saida_130(self):
        """Terminal fechado: vem o SIGHUP e a tela já não aceita escrita (EIO). O log tem de fechar com 130."""
        mestre, escravo = pty.openpty()
        try:
            with Parado(stdin=escravo, stdout=escravo, stderr=escravo, start_new_session=True,
                        preexec_fn=lambda: fcntl.ioctl(0, termios.TIOCSCTTY, 0)) as parado:
                os.close(escravo)
                escravo = None
                visto = b''
                while b'PRONTO' not in visto:
                    visto += os.read(mestre, 4096)
                os.close(mestre)
                mestre = None
                parado.p.wait(timeout=FOLGA)
                self.conferir_saida_130(parado)
        finally:
            for fd in (mestre, escravo):
                if fd is not None:
                    os.close(fd)

    def test_interrupcao_fora_do_executar_tambem_grava_130(self):
        pasta = comum.nova_pasta()
        with mock.patch.object(G, 'executar', side_effect=KeyboardInterrupt), \
                mock.patch.dict(os.environ, {'ACHADINHOS_GARIMPO_DIR': pasta}), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(G.main(['conferir']), 130)
        with open(os.path.join(pasta, 'logs', logs_da_pasta(pasta)[0]), encoding='utf-8') as f:
            self.assertEqual(f.read().rstrip('\n').split('\n')[-1], 'SAIDA=130')

    def test_tela_que_nao_aceita_escrita_nao_derruba_o_log(self):
        pasta = comum.nova_pasta()
        log = G.Log.abrir(pasta, 'conferir')
        with mock.patch('builtins.print', side_effect=OSError(5, 'EIO')):
            log('continua no arquivo')
        log.fechar(0)
        with open(log.caminho, encoding='utf-8') as f:
            self.assertIn('continua no arquivo', f.read())


@unittest.skipUnless(sys.platform == 'linux' and os.path.isdir('/proc/self'), 'só no Linux')
@unittest.skipIf(os.geteuid() == 0, 'root lê /proc/<pid>/environ de qualquer jeito')
class TestProcessoProtegido(Base):
    def test_controle_sem_protecao_o_environ_e_legivel(self):
        """Sem isto, o teste seguinte passaria até com o /proc fechado por outro motivo."""
        with Parado(SCRIPT_CONTROLE) as parado:
            parado.esperar_pronto()
            self.assertIn(SECRET.encode(), ler_environ(parado.p.pid))

    def test_outro_processo_nao_le_o_ambiente_da_rodada(self):
        with Parado() as parado:
            parado.esperar_pronto()
            with self.assertRaises(PermissionError):
                ler_environ(parado.p.pid)

    @unittest.skipUnless(shutil.which('tail') and shutil.which('kill'), 'sem tail ou kill')
    def test_tail_do_log_e_kill_continuam_funcionando(self):
        with Parado() as parado:
            parado.esperar_pronto()
            tail = subprocess.Popen(['tail', '-n', '+1', '-f', parado.log], stdout=subprocess.PIPE, text=True,
                                    encoding='utf-8')
            guarda = threading.Timer(FOLGA, tail.kill)
            guarda.start()
            try:
                self.assertIn('início', tail.stdout.readline())
                subprocess.run(['kill', '-TERM', str(parado.p.pid)], check=True, timeout=FOLGA)
                self.assertEqual(parado.p.wait(timeout=FOLGA), 130)
                for linha in tail.stdout:   # o tail -f vê a última linha, escrita depois do sinal
                    if linha.strip() == 'SAIDA=130':
                        break
                else:
                    self.fail('o tail -f não viu a última linha')
            finally:
                guarda.cancel()
                tail.kill()
                tail.wait()
                tail.stdout.close()

    def test_protege_antes_de_importar_o_coletar_shopee_e_de_ler_a_credencial(self):
        with open(os.path.join(PASTA, 'garimpo.py'), encoding='utf-8') as f:
            corpo = ast.parse(f.read()).body
        protege = next(i for i, n in enumerate(corpo) if isinstance(n, ast.Assign)
                       and getattr(n.targets[0], 'id', '') == 'PROCESSO_PROTEGIDO')
        self.assertIsInstance(corpo[protege].value, ast.Call)
        self.assertEqual(corpo[protege].value.func.id, 'proteger_processo')
        do_garimpo = [i for i, n in enumerate(corpo) if isinstance(n, ast.Import)
                      and n.names[0].name in ('banco', 'cliente', 'foco')]
        self.assertEqual(len(do_garimpo), 3)
        self.assertLess(protege, min(do_garimpo))


class TestProtegerProcesso(Base):
    def test_chama_o_prctl_certo(self):
        chamadas = []

        class Libc:
            def prctl(self, *a):
                chamadas.append(a)
                return 0
        with mock.patch('ctypes.CDLL', return_value=Libc()) as cdll:
            self.assertIs(G.proteger_processo(), True)
        cdll.assert_called_once_with(None, use_errno=True)
        self.assertEqual(chamadas, [(4, 0, 0, 0, 0)])   # PR_SET_DUMPABLE = 0

    def test_falha_devolve_falso_sem_levantar(self):
        class Recusa:
            def prctl(self, *a):
                return -1
        for efeito in ({'side_effect': OSError('sem libc')}, {'side_effect': AttributeError('prctl')},
                       {'return_value': Recusa()}, {'return_value': object()}):
            with self.subTest(efeito=str(efeito)), mock.patch('ctypes.CDLL', **efeito):
                self.assertIs(G.proteger_processo(), False)

    def test_sem_protecao_a_rodada_segue_com_aviso_sem_dado_sensivel(self):
        with mock.patch.object(G, 'PROCESSO_PROTEGIDO', False):
            r = rodar(['conferir'])
        self.assertEqual(r.codigo, 0)
        self.assertIn('AVISO', r.err)
        self.assertIn('AVISO', r.log)
        self.sem_vazamento(r)

    def test_com_protecao_nao_ha_aviso(self):
        with mock.patch.object(G, 'PROCESSO_PROTEGIDO', True):
            r = rodar(['conferir'])
        self.assertNotIn('AVISO', r.log)


# ---------- S9 e S8 (parciais) ----------
class TestMaxReqPadrao(Base):
    def test_250_so_no_reconhecer(self):
        self.assertEqual(G.ler_argumentos(['reconhecer'])[0].max_req, 250)
        self.assertEqual(G.ler_argumentos(['reconhecer', '--max-req', '7'])[0].max_req, 7)
        m = fase_falsa('fase_teste_mapa')
        for sub in ('mapa', 'piloto', 'garimpar', 'links', 'conversoes'):
            with self.subTest(sub=sub), self.com_fase(m), mock.patch.dict(G.SUBCOMANDOS, {sub: 'fase_teste_mapa'}):
                self.assertIsNone(G.ler_argumentos([sub])[0].max_req)

    def com_fase(self, modulo):
        return mock.patch.dict(sys.modules, {modulo.__name__: modulo})


class TestGitignore(unittest.TestCase):
    @unittest.skipUnless(shutil.which('git') and os.path.exists(os.path.join(comum.RAIZ, '.git')), 'sem git')
    def test_sobra_da_escrita_atomica_dos_docs_fica_fora_do_git(self):
        for caminho, ignorado in (('tools/garimpo_feminino/docs/.api_findings.md.a1b2c3.tmp', True),
                                  ('tools/garimpo_feminino/docs/.schema.json.x.tmp', True),
                                  ('tools/garimpo_feminino/docs/api_findings.md', False),
                                  ('tools/garimpo_feminino/docs/schema.json', False)):
            with self.subTest(caminho=caminho):
                p = subprocess.run(['git', 'check-ignore', '-q', caminho], cwd=comum.RAIZ, timeout=30)
                self.assertEqual(p.returncode == 0, ignorado)


# ---------- teste estático e contrato com o coletar_shopee.py ----------
def fontes():
    nomes = sorted(n for n in os.listdir(PASTA) if n.endswith('.py'))
    saida = {}
    for n in nomes:
        with open(os.path.join(PASTA, n), encoding='utf-8') as f:
            saida[n] = f.read()
    return saida


class TestEstatico(unittest.TestCase):
    def test_um_so_ponto_de_rede_no_cliente(self):
        f = fontes()
        self.assertIn('garimpo.py', f)
        self.assertIn('cliente.py', f)
        contagem = {n: len(re.findall(r'OPENER_API\.open\(', t)) for n, t in f.items()}
        self.assertEqual(sum(contagem.values()), 1, contagem)
        self.assertEqual(contagem['cliente.py'], 1)

    def test_nada_de_rede_crua_nem_do_banco_do_etiqueta(self):
        proibidos = (r'urlopen\(', r'build_opener\(', r'http\.client', r'socket', r'conectar\(', r'criar_banco',
                     r'upsert\(')
        for nome, texto in fontes().items():
            for padrao in proibidos:
                with self.subTest(arquivo=nome, padrao=padrao):
                    self.assertIsNone(re.search(padrao, texto))


# Nomes do coletar_shopee.py (CS) e do servidor.py (CS.S) que o garimpo usa: se o plano pendente
# atualizar-precos-shopee-por-item (ou outro) renomear algum, este teste falha antes do dono rodar.
NOMES_CS = {
    # cliente.py
    'URL_API': str, 'OPENER_API': object, 'assinar': 'funcao', 'autorizacao': 'funcao', '_ler_json': 'funcao',
    'codigo_de_erro': 'funcao', 'ERRO_LIMITE': int, 'TIMEOUT': (int, float), 'Segredo': type,
    'ErroColeta': 'excecao', 'ErroApi': 'excecao', 'LimiteAtingido': 'excecao', 'RespostaInvalida': 'excecao',
    # garimpo.py
    'credenciais': 'funcao', 'conferir_dono': 'funcao', 'DonoErrado': 'excecao', 'id_afiliado_ok': 'funcao',
    'ID_AFILIADO_SHOPEE': str, 'CONSULTA': str, 'TERMO_CONFERENCIA': str, 'POR_BUSCA': int, 'MAX_URL': int,
    'OPENER_CONFERENCIA': object,
    # fase_reconhecer.py
    '_texto': 'funcao', 'MAX_RESPOSTA': int, 'destino': 'funcao', 'dono_ok': 'funcao',
}
NOMES_S = {'UA': str, 'eh_link_shopee': 'funcao'}
ARIDADE = {'assinar': 4, 'autorizacao': 3, 'credenciais': 0, 'conferir_dono': 1, '_ler_json': 1,
           'codigo_de_erro': 1, 'id_afiliado_ok': 0, '_texto': 2, 'destino': 1, 'dono_ok': 1}


class TestContrato(unittest.TestCase):
    def conferir_tipo(self, alvo, nome, tipo):
        self.assertTrue(hasattr(alvo, nome), f'{nome} sumiu')
        v = getattr(alvo, nome)
        if tipo == 'funcao':
            self.assertTrue(callable(v), nome)
        elif tipo == 'excecao':
            self.assertTrue(isinstance(v, type) and issubclass(v, CS.ErroColeta), nome)
        elif tipo is type:
            self.assertIsInstance(v, type, nome)
        elif tipo is not object:
            self.assertIsInstance(v, tipo, nome)

    def test_os_nomes_listados_existem_com_o_tipo_esperado(self):
        for nome, tipo in NOMES_CS.items():
            with self.subTest(nome=nome):
                self.conferir_tipo(CS, nome, tipo)
        for nome, tipo in NOMES_S.items():
            with self.subTest(nome='S.' + nome):
                self.conferir_tipo(S, nome, tipo)
        for nome, n in ARIDADE.items():
            with self.subTest(nome=nome):
                self.assertEqual(len(inspect.signature(getattr(CS, nome)).parameters), n)

    def test_todo_nome_usado_no_fonte_esta_na_lista_e_existe(self):
        usados, usados_s = set(), set()
        for texto in fontes().values():
            usados |= {m for m in re.findall(r'\bCS\.([A-Za-z_]\w*)', texto) if m != 'S'}
            usados_s |= set(re.findall(r'\bCS\.S\.([A-Za-z_]\w*)', texto))
        self.assertTrue({'URL_API', 'OPENER_API', 'assinar', 'credenciais', 'conferir_dono'} <= usados, usados)
        self.assertEqual(usados - set(NOMES_CS), set(), 'nome novo do CS: acrescente em NOMES_CS')
        self.assertEqual(usados_s - set(NOMES_S), set(), 'nome novo do CS.S: acrescente em NOMES_S')
        for nome in usados:
            self.assertTrue(hasattr(CS, nome), nome)
        for nome in usados_s:
            self.assertTrue(hasattr(S, nome), nome)

    def test_host_fixo_e_openers_sem_redirect(self):
        self.assertEqual(CS.URL_API, URL_FIXA)
        for opener in (CS.OPENER_API, CS.OPENER_CONFERENCIA):
            self.assertTrue(any(isinstance(h, CS.SemRedirecionar) for h in opener.handlers))
        self.assertIsNot(CS.OPENER_API, CS.OPENER_CONFERENCIA)

    def test_credenciais_tira_o_secret_do_ambiente(self):
        with mock.patch.dict(os.environ, {'ACHADINHOS_SHOPEE_APP_ID': APP_ID, 'ACHADINHOS_SHOPEE_SECRET': SECRET}):
            app_id, segredo = CS.credenciais()
            self.assertNotIn('ACHADINHOS_SHOPEE_SECRET', os.environ)
        self.assertEqual(app_id, APP_ID)
        self.assertNotIn(SECRET, repr(segredo) + str(segredo) + f'{segredo}')


if __name__ == '__main__':
    unittest.main()
