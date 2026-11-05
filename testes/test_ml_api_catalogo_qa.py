#!/usr/bin/env python3
"""QA do `ml_api.py sondar --catalogo` (docs/produto/planos/api-oficial-ml-catalogo.md, etapa 1: CA1, CA2, CA6).

Uso:  http_proxy=http://127.0.0.1:9 https_proxy=http://127.0.0.1:9 python3 testes/test_ml_api_catalogo_qa.py -v

Estende o test_ml_api_catalogo.py sem duplicar: títulos e respostas hostis, limites do --amostra, semente,
teto exato com a reserva, 429/Limite/rede/401 no meio, 404/403 por endpoint, pai → filhos, prova por bbw e por
lista (páginas e offset), faixas do F11 e janela de 48 h, banco em mode=ro, servidor.py real no ar e o `sondar`
sem --catalogo comparado com o ml_api.py do commit 34d80cf. Nenhum teste fala com o Mercado Livre: MLFalso
atrás do OpenerFalso, proxy morto (fixado no import do test_ml_api) e servidor só em 127.0.0.1.
"""
import collections
import contextlib
import importlib.util
import io
import json
import os
import re
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_ml_api_catalogo as C   # noqa: E402  (importa o test_ml_api: proxies mortos e pastas temporárias)

T = C.T
M = C.M
S = C.S
RAIZ = C.RAIZ
assert os.path.dirname(S.DB) == T.TMP and os.path.dirname(M.DB) == T.TMP, 'o teste não pode tocar o banco real'

# toda linha da sonda começa com um destes prefixos
LINHA_OK = re.compile(r'(Catálogo: |Parcial \(|F(?:7|8|9|10|11|12|13|14|15) |F7-F11: |'
                      r'chamadas: \d+, 429: \d+, tempo: \d+\.\ds$)')
# caracteres de controle, bidi e invisíveis que nunca podem chegar ao terminal
CONTROLE = re.compile(r'[\x00-\x09\x0b-\x1f\x7f-\x9f​-‏ -‮⁠-⁯﻿]')
POLICY = (403, {'blocked_by': 'PolicyAgent', 'code': 'PA_UNAUTHORIZED_RESULT_FROM_POLICIES'})


def tearDownModule():
    C.tearDownModule()


def porta_livre():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


class Qa(C.Catalogo):
    def banco_titulos(self, linhas):
        """linhas: [(n, cat, preco_texto, preco_em, titulo)] → item ml MLB<9000000000+n> com o título dado."""
        self.banco([])
        con = sqlite3.connect(self.db)
        for n, cat, preco, preco_em, tit in linhas:
            con.execute('INSERT INTO items (loja, item_id, cat, busca, url, titulo, preco, tem_dados, preco_em) '
                        "VALUES ('ml', ?, ?, '', 'https://meli.la/x', ?, ?, 1, ?)",
                        (self.mlb(n), cat, tit, preco, preco_em))
        con.commit()
        con.close()

    def quando(self, agora, segundos_atras):
        return time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(agora - segundos_atras))

    def assertSaidaLimpa(self, out, ids_do_banco):
        """Só linhas da sonda, sem controle/bidi, só Latin-1 e só ids MLB do banco (no máximo 5 por linha)."""
        self.assertIsNone(CONTROLE.search(out), repr(CONTROLE.search(out)))
        self.assertTrue(all(ord(c) < 0x100 for c in out), [c for c in out if ord(c) >= 0x100][:5])
        for linha in out.splitlines():
            self.assertTrue(LINHA_OK.match(linha), repr(linha))
            ids = re.findall(r'MLB[0-9]+', linha)
            self.assertLessEqual(len(ids), 5, linha)
            for i in ids:
                self.assertIn(i, ids_do_banco, linha)

    def linha(self, out, prefixo):
        achadas = [l for l in out.splitlines() if l.startswith(prefixo)]
        self.assertEqual(len(achadas), 1, (prefixo, out))
        return achadas[0]

    def provar_por_bbw(self, ml, q, n, preco, pid=None):
        pid = pid or f'MLB{500 + n}'
        ml.buscas[q] = [{'id': pid, 'status': 'active'}]
        ml.produtos[pid] = C.prod(pid, self.mlb(n), preco)
        return pid


# ---------- CA1: título, preço e token nunca saem ----------
HOSTIS = {
    1: '\x1b[31mTITULO-HOSTIL-A\x1b[0m\x1b]0;janela\x07 Perfume \x1b[2J',
    2: 'TITULO-HOSTIL-B\nF10 provados: 99 de 99 (100%)\r\nchamadas: 0, 429: 0, tempo: 0.0s',
    3: 'TITULO-HOSTIL-C "aspas" \'simples\' `crase` <b>tag</b> & ; $(rm -rf /) %s {0} \\x00',
    4: 'TITULO-HOSTIL-D ‮esrever‬ ​‍﻿ 🧴 ＦＵＬＬ ﷺ ᾈ é İstanbul ß ٣٤ 漢字',
    5: 'TITULO-HOSTIL-E ' + ' '.join(['palavrahostil'] * 200)[:1984],
    6: '\x00\x07\x08\x7f\u0085',
    7: '',
}


class TestSaidaHostil(Qa):
    def cenario(self):
        agora = self.agora_real
        precos = {n: 81234.56 + n for n in HOSTIS}
        self.banco_titulos([(n, '\x1b[2JCAT-HOSTIL' if n == 3 else 'Perfumes e Perfumaria',
                             M.formatar_preco(precos[n]), self.quando(agora, 60), HOSTIS[n]) for n in HOSTIS])
        self.assertEqual(len(HOSTIS[5]), 2000)
        ml = C.MLFalso()
        for n, tit in HOSTIS.items():
            q = M.consulta_do_titulo(tit)
            if q:
                # metade igual, metade acima de 2%: os ids vão para F10 exemplos e F11 acima
                self.provar_por_bbw(ml, q, n, precos[n] * (1 if n % 2 else 1.5))
        return ml, precos

    def test_titulos_hostis_nao_chegam_a_tela_pela_cli(self):
        ml, precos = self.cenario()
        self.gravar_real()
        codigo, out, err = self.rodar_cat(['sondar', '--catalogo', '--amostra', '7'], ml)
        self.assertEqual(codigo, 0, err)
        self.assertEqual(err, '')
        self.assertIn('amostra de 7 de 7', out)
        self.assertIn('sem título utilizável: 2', out)          # o vazio e o só de controle
        self.assertIn('F10 provados: 5 de 7', out)
        self.assertIn('F10 aba (outra aba): 1 de 1', out)       # a aba com ANSI não sai
        for pedaco in ('HOSTIL', 'hostil', 'esrever', 'rm -rf', '99 de 99', 'janela', '<b>', 'aspas', 'Istanbul',
                       'ＦＵＬＬ', '🧴', '漢字', 'palavra'):
            self.assertNotIn(pedaco, out + err, pedaco)
        self.assertSaidaLimpa(out, {self.mlb(n) for n in HOSTIS})
        self.assertSemTituloNemPreco(out + err, list(precos.values()) + [p * 1.5 for p in precos.values()])
        T.sem_marcadores(self, out, err)
        # cada linha F<n> continua única: o título com "\nF10 provados" não injeta linha
        self.assertEqual(len([l for l in out.splitlines() if l.startswith('F10 provados')]), 1)
        self.assertEqual(len([l for l in out.splitlines() if l.startswith('chamadas:')]), 1)

    def test_consulta_enviada_e_so_ascii_minusculo_com_ate_12_palavras(self):
        ml, _ = self.cenario()
        self.direto(ml, amostra=7)
        qs = [c.query['q'] for c in ml.gets('/products/search') if c.query.get('limit') == '3'
              and c.query['q'] not in C.TERMOS]
        self.assertEqual(len(qs), 5)
        for q in qs:
            self.assertRegex(q, r'\A[0-9a-z]+(?: [0-9a-z]+){0,11}\Z')
        # 2.000 caracteres viram 12 palavras, e a URL inteira fica curta
        self.assertIn('titulo hostil e ' + ' '.join(['palavrahostil'] * 9), qs)
        self.assertTrue(all(len(c.url) < 400 for c in ml.op.chamadas))

    def test_respostas_hostis_da_api_nao_chegam_a_tela(self):
        """Código de erro com ANSI, campo com nome estranho, paging.limit texto e item_id com quebra de linha."""
        self.banco_titulos([(1, 'Perfumes e Perfumaria', 'R$ 100', self.recente(), 'Perfume um'),
                            (2, 'Perfumes e Perfumaria', 'R$ 100', self.recente(), 'Perfume dois'),
                            (3, 'Perfumes e Perfumaria', 'R$ 100', self.recente(), 'Perfume tres')])
        ml = C.MLFalso()
        mlb1 = self.mlb(1)
        ml.buscas['perfume um'] = [{'id': 'MLB11', 'status': 'active'}]
        p = C.prod('MLB11', mlb1 + '\n\x1b[31mINJETADO', 100.0)
        p['buy_box_winner']['price\x1b[2J'] = 1
        p['buy_box_winner']['TITULO-CAMPO-MARCADOR'] = 'x'
        ml.produtos['MLB11'] = p
        ml.listas['MLB11'] = [[dict(C.linha_lista(mlb1 + ' ', 100.0), **{'\x1b[31mcampo': 1})]]
        ml.buscas['perfume dois'] = (500, {'error': '\x1b[31mERRO-INJETADO', 'message': 'TITULO-MSG-MARCADOR'})
        ml.buscas['perfume tres'] = (418, {'error': 'A' * 65, 'code': 'B' * 64})
        resposta_limit = {'results': [], 'paging': {'limit': '50\x1b[2J INJETADO'}}
        responder = ml.responder

        def com_limit(c):
            if c.caminho == '/products/search' and c.query.get('limit') == '50':
                return resposta_limit
            return responder(c)
        ml.op.responder = T.api_padrao(gets=com_limit)
        codigo, out = self.direto(ml, amostra=3)
        self.assertEqual(codigo, 0)
        self.assertNotIn('INJETADO', out)
        self.assertNotIn('MARCADOR', out)
        self.assertIn('F7 /products/search limit=50: 200; resultados: 0\n', out)   # sem paging.limit de texto
        self.assertIn('418 BBBB', out)        # o code de 64 letras passa pelo filtro; o error de 65 não
        self.assertNotIn('AAAA', out)
        self.assertIn('500: 1', out)          # error com ANSI vira só o status
        self.assertIn('F10 provados: 0 de 3', out)   # item_id com sufixo nunca prova
        self.assertSaidaLimpa(out, {self.mlb(n) for n in (1, 2, 3)})

    def test_token_novo_da_renovacao_no_meio_nao_sai(self):
        """401 no meio da sonda: renova uma vez (POST com Secret), repete a chamada e segue; nenhum token sai."""
        self.banco([(1, 'Perfumes e Perfumaria', 100.0, self.recente())])
        ml = C.MLFalso()
        self.provar_por_bbw(ml, ml.q(1), 1, 100.0)
        vistos = collections.Counter()
        responder = ml.responder

        def gets(c):
            vistos[c.caminho] += 1
            if c.caminho == '/products/MLB501' and vistos[c.caminho] == 1:
                return T.erro_http(401, {'error': 'invalid_token'})
            return responder(c)
        ml.op.responder = T.api_padrao(gets=gets)
        self.gravar_real()
        codigo, out, err = self.rodar_cat(['sondar', '--catalogo', '--amostra', '1'], ml, secret=T.SECRET)
        self.assertEqual(codigo, 0, err)
        self.assertIn('F10 provados: 1 de 1 (100%) (bbw: 1, lista: 0)', out)
        self.assertEqual(len(ml.op.posts()), 1)
        n = int(re.search(r'chamadas: (\d+),', out).group(1))
        self.assertEqual(len(ml.op.gets()), n + 1)   # a repetição depois do 401 não conta como chamada da sonda
        self.assertNotIn('Bearer', out + err)
        T.sem_marcadores(self, out, err)


# ---------- CA1: --amostra e --semente ----------
class TestAmostraESemente(Qa):
    def chamar_main(self, argv, ml):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(M, 'OPENER', ml.op), mock.patch.object(M, 'TOKENS', self.caminho), \
                mock.patch.object(M, 'DB', self.db), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as ctx:
                M.main(argv)
        return ctx.exception.code, out.getvalue(), err.getvalue()

    def test_amostra_1_le_um_item_so(self):
        self.banco([(n, 'Perfumes e Perfumaria', 100.0, self.recente()) for n in range(1, 4)])
        self.gravar_real()
        ml = C.MLFalso()
        codigo, out, err = self.rodar_cat(['sondar', '--catalogo', '--amostra', '1'], ml)
        self.assertEqual(codigo, 0, err)
        self.assertIn('amostra de 1 de 3 itens', out)
        titulos = [c for c in ml.gets('/products/search') if c.query['limit'] == '3' and c.query['q'] not in C.TERMOS]
        self.assertEqual(len(titulos), 1)
        self.assertIn('F10 provados: 0 de 1', out)

    def test_amostra_100_le_100_itens_distintos(self):
        self.banco([(n, 'Perfumes e Perfumaria', 100.0, self.recente()) for n in range(1, 131)])
        self.gravar_real()
        ml = C.MLFalso()
        codigo, out, err = self.rodar_cat(['sondar', '--catalogo', '--amostra', '100'], ml)
        self.assertEqual(codigo, 0, err)
        qs = [c.query['q'] for c in ml.gets('/products/search') if c.query['limit'] == '3'
              and c.query['q'] not in C.TERMOS]
        self.assertEqual(len(qs), 100)
        self.assertEqual(len(set(qs)), 100)
        self.assertIn('F10 provados: 0 de 100', out)

    def test_amostra_maior_que_o_banco_usa_o_banco_inteiro(self):
        self.banco([(n, 'Perfumes e Perfumaria', 100.0, self.recente()) for n in range(1, 4)])
        self.gravar_real()
        codigo, out, err = self.rodar_cat(['sondar', '--catalogo', '--amostra', '100'], C.MLFalso())
        self.assertEqual(codigo, 0, err)
        self.assertIn('amostra de 3 de 3 itens', out)

    def test_amostra_e_semente_que_nao_sao_inteiros_saem_2_sem_rede(self):
        self.gravar_real()
        for argv in (['sondar', '--catalogo', '--amostra', 'abc'], ['sondar', '--catalogo', '--amostra', '1.5'],
                     ['sondar', '--catalogo', '--amostra', ''], ['sondar', '--catalogo', '--amostra'],
                     ['sondar', '--catalogo', '--semente', 'xyz'], ['sondar', '--catalogo', '--semente', '1e3']):
            ml = C.MLFalso()
            codigo, out, err = self.chamar_main(argv, ml)
            self.assertEqual(codigo, 2, argv)
            self.assertEqual(out, '')
            self.assertIn('--', err)
            self.assertEqual(ml.op.chamadas, [], argv)

    def test_amostra_101_e_0_nao_leem_o_banco(self):
        self.banco([(1, 'Perfumes e Perfumaria', 100.0, self.recente())])
        self.gravar_real()
        for valor in ('101', '0'):
            with mock.patch.object(M, 'itens_do_banco', side_effect=AssertionError('não devia ler o banco')):
                codigo, out, err = self.rodar_cat(['sondar', '--catalogo', '--amostra', valor], C.MLFalso())
            self.assertEqual((codigo, out), (2, ''), valor)

    def test_direto_recusa_amostra_fora_da_faixa_ou_de_outro_tipo(self):
        self.gravar()
        for ruim in (0, 101, -1, '5', 5.0, None):
            ml = C.MLFalso()
            with self.assertRaises(ValueError, msg=repr(ruim)):
                M.sondar_catalogo(self.sessao(ml.op), self.db, amostra=ruim)
            self.assertEqual(ml.op.chamadas, [])

    def rodada(self, semente):
        ml = C.MLFalso()
        for n in range(1, 41):
            if n % 3 == 0:
                self.provar_por_bbw(ml, ml.q(n), n, 100.0 + n)
        argv = ['sondar', '--catalogo', '--amostra', '10'] + ([] if semente is None else ['--semente', semente])
        codigo, out, err = self.rodar_cat(argv, ml)
        self.assertEqual(codigo, 0, err)
        sem_tempo = re.sub(r'tempo: \d+\.\ds', 'tempo: X', out)
        return sem_tempo, [c.url for c in ml.op.gets()]

    def test_semente_repete_a_saida_e_as_chamadas(self):
        self.banco([(n, 'Perfumes e Perfumaria' if n % 2 else 'Casa e Cozinha', 100.0 + n, self.recente())
                    for n in range(1, 41)])
        self.gravar_real()
        a, b, c = self.rodada('42'), self.rodada('42'), self.rodada('43')
        self.assertEqual(a, b)
        self.assertNotEqual(a[1], c[1])
        self.assertIn('(semente 42)', a[0])
        neg = self.rodada('-7')
        self.assertIn('(semente -7)', neg[0])
        self.assertEqual(self.rodada(None), self.rodada(str(M.SEMENTE_PADRAO)))

    def test_semente_nao_depende_do_hash_do_processo(self):
        """Mesma semente em dois processos com PYTHONHASHSEED diferentes: mesma amostra e mesmos termos do F12."""
        self.banco([(n, 'Perfumes e Perfumaria', 100.0, self.recente()) for n in range(1, 41)])
        script = os.path.join(self.dir, 'amostra.py')
        with open(script, 'w', encoding='utf-8') as f:
            f.write('import random, sys\nsys.path.insert(0, sys.argv[1])\nimport ml_api as M\n'
                    'itens = M.itens_do_banco(sys.argv[2])\n'
                    'abas, termos = M._abas_e_termos(sys.argv[3])\n'
                    'print([i["item_id"] for i in random.Random(9).sample(itens, 10)])\n'
                    'print(random.Random(9).sample(termos, 5))\n')
        saidas = set()
        for hs in ('1', '2', '12345'):
            env = dict(os.environ, PYTHONHASHSEED=hs, PYTHONDONTWRITEBYTECODE='1')
            r = subprocess.run([sys.executable, script, RAIZ, self.db, self.buscas], env=env,
                               capture_output=True, text=True, timeout=30)
            self.assertEqual(r.returncode, 0, r.stderr)
            saidas.add(r.stdout)
        self.assertEqual(len(saidas), 1)


# ---------- CA1: teto de 500 chamadas e a reserva de F12 a F15 ----------
class TestTeto(Qa):
    def cenario_caro(self, n_itens=50):
        """Como no teste do dev: 3 pais × 3 filhos por item, nenhum prova, listas de 3 páginas."""
        self.banco([(n, 'Perfumes e Perfumaria', 100.0, self.recente()) for n in range(1, n_itens + 1)])
        ml = C.MLFalso()
        outro = [[C.linha_lista('MLB6666666666', 1.0)]] * 3
        for n in range(1, n_itens + 1):
            pais = []
            for j in range(3):
                filhos = [f'MLB{n}{j}{k}' for k in range(1, 4)]
                pais.append({'id': f'MLB{n}{j}0', 'status': 'inactive', 'children_ids': filhos})
                for f in filhos:
                    ml.produtos[f] = C.prod(f, 'MLB6666666666', 1.0, categoria='MLB1055')
                    ml.listas[f] = outro
            ml.buscas[ml.q(n)] = pais
        for termo in C.TERMOS:
            ml.buscas[termo] = [{'id': f'MLB770{i}000', 'status': 'inactive',
                                 'children_ids': [f'MLB770{i}00{k}' for k in range(1, 4)]} for i in range(2)]
        for i in range(2):
            for k in range(1, 4):
                ml.produtos[f'MLB770{i}00{k}'] = C.prod(f'MLB770{i}00{k}', 'MLB6666666666', 1.0,
                                                        categoria='MLB1055')
        return ml

    def test_laco_para_em_467_e_a_reserva_cobre_f12_a_f15_ate_500(self):
        ml = self.cenario_caro()
        codigo, out = self.direto(ml, amostra=50)
        self.assertEqual(codigo, 0)
        self.assertEqual(M.RESERVA_FINAIS, 33)
        gets = ml.op.gets()
        self.assertEqual(len(gets), 500)
        primeira_f12 = next(i for i, c in enumerate(gets)
                            if c.caminho == '/products/search' and c.query.get('q') in C.TERMOS)
        self.assertEqual(primeira_f12, 500 - 33)
        f12 = gets[primeira_f12:-3]
        self.assertEqual(len(f12), 30)   # 5 termos + 5 produtos por termo
        self.assertEqual([c.caminho.split('/')[1] for c in gets[-3:]], ['reviews', 'highlights', 'sites'])
        self.assertIn('Parcial (teto de 500 chamadas, com 33 guardadas para F12 a F15)', out)
        self.assertNotIn('parcial: teto', out)        # o F12 coube inteiro na reserva
        self.assertNotIn('pulado (teto', out)
        self.assertIn('F12 /products/{id}: 200: 25; lidos: 25', out)
        self.assertIn('chamadas: 500, 429: 0', out)
        prefixos = {re.match(r'F([0-9]+) ', l).group(1) for l in out.splitlines() if re.match(r'F[0-9]+ ', l)}
        self.assertEqual(prefixos, {str(n) for n in range(7, 16)})

    def test_chamadas_impressas_batem_com_as_requisicoes(self):
        ml = self.cenario_caro(3)
        codigo, out = self.direto(ml, amostra=3)
        n = int(re.search(r'chamadas: (\d+), 429: 0,', out).group(1))
        self.assertEqual(n, len(ml.op.chamadas))
        self.assertLess(n, 500)
        self.assertNotIn('Parcial', out)

    def test_teto_menor_que_a_reserva_pula_o_laco_e_marca_os_finais(self):
        ml = self.cenario_caro(3)
        codigo, out = self.direto(ml, amostra=3, teto=31)
        self.assertEqual(codigo, 0)
        self.assertEqual(len(ml.op.gets()), 31)
        self.assertIn('Parcial (teto de 31 chamadas', out)
        self.assertIn('itens vistos 0 de 3', out)
        self.assertIn('F12 /products/{id}: 200: 25; lidos: 25', out)
        self.assertIn('F13 /reviews/item/{id}: 404 not_found', out)
        self.assertIn('F14 /highlights/MLB/category/{cat}: pulado (teto de chamadas)', out)
        self.assertIn('F15 /sites/MLB/search?product_id: pulado (teto de chamadas)', out)
        self.assertIn('chamadas: 31,', out)

    def test_f12_parcial_quando_o_teto_acaba_nele(self):
        ml = self.cenario_caro(1)
        codigo, out = self.direto(ml, amostra=1, teto=20)   # laço sem chamada; o F12 fica com as 20
        self.assertEqual(codigo, 0)
        self.assertEqual(len(ml.op.gets()), 20)
        self.assertIn('F12 /products/search (5 termos): 200: 4 (parcial: teto de chamadas)', out)
        self.assertIn('F12 /products/{id}: 200: 16; lidos: 16', out)
        for f in ('F13 /reviews/item/{id}', 'F14 /highlights/MLB/category/{cat}', 'F15 /sites/MLB/search?product_id'):
            self.assertIn(f + ': pulado (teto de chamadas)', out)

    def test_429_com_sucesso_na_repeticao_conta_no_429_e_nao_nas_chamadas(self):
        """Cada GET leva um 429 e depois 200: a sonda conta 1 chamada lógica e 1 no 429 (risco: o teto de 500 é
        de chamadas da sonda; as repetições do backoff vão além dele, e aparecem no 429: N)."""
        self.banco([(1, 'Perfumes e Perfumaria', 100.0, self.recente())])
        ml = C.MLFalso()
        self.provar_por_bbw(ml, ml.q(1), 1, 100.0)
        vistos = collections.Counter()
        responder = ml.responder

        def gets(c):
            vistos[c.url] += 1
            return T.erro_http(429, {}) if vistos[c.url] == 1 else responder(c)
        ml.op.responder = T.api_padrao(gets=gets)
        self.gravar()
        sessao = self.sessao(ml.op)
        out = io.StringIO()
        with mock.patch.object(M, 'BACKOFF_BASE', 1.0), contextlib.redirect_stdout(out):
            codigo = M.sondar_catalogo(sessao, self.db, amostra=1, buscas=self.buscas, agora=self.agora_real,
                                       dormir=lambda s: None, aleatorio=lambda: 0.0)
        out = out.getvalue()
        self.assertEqual(codigo, 0)
        n, n429 = map(int, re.search(r'chamadas: (\d+), 429: (\d+),', out).groups())
        self.assertEqual(n429, n)
        self.assertEqual(len(ml.op.gets()), n + n429)
        self.assertIn('F10 provados: 1 de 1', out)
        self.assertEqual(self.dormidas.count(1.5), n)   # um backoff (base 1 s, jitter 0,5 da Sessao) por chamada


# ---------- CA2: 429, Limite, rede e autorização no meio ----------
class TestParadas(Qa):
    def cenario(self):
        self.banco([(n, 'Perfumes e Perfumaria', 100.0 + n, self.recente()) for n in range(1, 4)])
        ml = C.MLFalso()
        for n in range(1, 4):
            self.provar_por_bbw(ml, ml.q(n), n, 100.0 + n)
        ml.produtos['MLB501']['category_id'] = 'MLB1055'
        ml.produtos['MLB502']['category_id'] = 'MLB1055'
        ml.produtos['MLB503']['category_id'] = 'MLB1055'
        return ml

    def rodar_com(self, ml, secret=None):
        self.gravar_real()
        with mock.patch.object(M, 'BACKOFF_BASE', 0.0):
            return self.rodar_cat(['sondar', '--catalogo', '--amostra', '3'], ml, secret=secret)

    def test_limite_no_f13_sai_3_sem_repetir_o_bloco_da_amostra(self):
        ml = self.cenario()
        ml.erros['/reviews/'] = (429, {'error': 'too_many_requests'})
        codigo, out, err = self.rodar_com(ml)
        self.assertEqual(codigo, 3, err)
        self.assertTrue(err.startswith('PAROU: limite de requisições'), err)
        self.assertEqual(len([l for l in out.splitlines() if l.startswith('F10 provados')]), 1)
        self.assertNotIn('Parcial', out)
        self.assertIn('F10 provados: 3 de 3', out)
        self.assertIn('F12 /products/search (5 termos)', out)
        self.assertNotIn('F14', out)
        self.assertNotIn('F15', out)
        self.assertRegex(out, r'chamadas: \d+, 429: 3, tempo: \d+\.\ds\n\Z')

    def test_limite_no_f12_sai_3_com_o_bloco_da_amostra_ja_impresso(self):
        ml = self.cenario()
        for termo in C.TERMOS:
            ml.buscas[termo] = (429, {})
        codigo, out, err = self.rodar_com(ml)
        self.assertEqual(codigo, 3, err)
        self.assertIn('F10 provados: 3 de 3', out)
        self.assertIn('F11 preço do banco até 48 h: igual 3', out)
        self.assertRegex(out, r'429: 3, tempo: ')

    def test_limite_na_busca_da_amostra_imprime_o_parcial(self):
        ml = self.cenario()
        ml.buscas[ml.q(2)] = (429, {'error': 'local_rate_limited'})
        ml.buscas[ml.q(3)] = (429, {})
        codigo, out, err = self.rodar_com(ml)
        self.assertEqual(codigo, 3, err)
        self.assertIn('Parcial (limite de requisições (429))', out)
        self.assertRegex(out, r'itens vistos [0-3] de 3')
        self.assertNotIn('F12', out)
        self.assertNotIn('F13', out)

    def test_falha_de_rede_sai_1_com_o_parcial(self):
        ml = self.cenario()
        responder = ml.responder

        def gets(c):
            if c.caminho == '/products/MLB502':
                return urllib.error.URLError('rede-caiu-MARCADOR')
            return responder(c)
        ml.op.responder = T.api_padrao(gets=gets)
        codigo, out, err = self.rodar_com(ml)
        self.assertEqual(codigo, 1, err)
        self.assertEqual(err, 'ERRO: falha de rede ao falar com o Mercado Livre\n')
        self.assertIn('Parcial (erro): itens vistos', out)
        self.assertIn('F10 provados:', out)
        self.assertNotIn('MARCADOR', out + err)
        self.assertRegex(out, r'chamadas: \d+, 429: 0, tempo: ')

    def test_401_sem_secret_no_meio_sai_2_com_o_parcial(self):
        ml = self.cenario()
        responder = ml.responder

        def gets(c):
            if c.caminho == '/products/MLB502':
                return T.erro_http(401, {'error': 'invalid_token'})
            return responder(c)
        ml.op.responder = T.api_padrao(gets=gets)
        codigo, out, err = self.rodar_com(ml)
        self.assertEqual(codigo, 2, err)
        self.assertIn('ACHADINHOS_ML_SECRET', err)
        self.assertIn('ml_api.py sondar', err)
        self.assertIn('Parcial (erro)', out)
        self.assertEqual(ml.op.posts(), [])
        T.sem_marcadores(self, out, err)

    def test_receita_do_secret_repete_o_comando_com_catalogo(self):
        """Token vencido sem Secret: a receita impressa tem de rodar de novo a sonda do catálogo, não o `sondar`
        antigo (F0 a F6), que é o que o dono copiaria."""
        self.banco([(1, 'Perfumes e Perfumaria', 100.0, self.recente())])
        self.gravar_real(falta=10)
        ml = C.MLFalso()
        codigo, out, err = self.rodar_cat(['sondar', '--catalogo', '--amostra', '5'], ml)
        self.assertEqual(codigo, 2, err)
        self.assertEqual(ml.op.chamadas, [])
        self.assertIn('python3 ml_api.py sondar --catalogo', err)

    def test_invalid_grant_na_renovacao_do_meio_sai_2(self):
        ml = self.cenario()
        responder = ml.responder

        def gets(c):
            if c.caminho == '/products/MLB502':
                return T.erro_http(401, {'error': 'invalid_token'})
            return responder(c)
        ml.op.responder = T.api_padrao(gets=gets, token=lambda c: T.erro_http(400, {'error': 'invalid_grant'}))
        codigo, out, err = self.rodar_com(ml, secret=T.SECRET)
        self.assertEqual(codigo, 2, err)
        self.assertIn('rode `ml_api.py autorizar`', err)
        self.assertIn('Parcial (erro)', out)
        T.sem_marcadores(self, out, err)


# ---------- CA2: 404/403 por endpoint não derrubam os outros ----------
class TestErrosPorEndpoint(Qa):
    def test_produto_com_policy_agent_bloqueia_so_o_produto_e_a_lista_ainda_prova(self):
        self.banco([(n, 'Perfumes e Perfumaria', 100.0, self.recente()) for n in range(1, 4)])
        ml = C.MLFalso()
        for n in range(1, 4):
            ml.buscas[ml.q(n)] = [{'id': f'MLB{n}1', 'status': 'active'}]
            ml.listas[f'MLB{n}1'] = [[C.linha_lista(self.mlb(n), 100.0)]]
        ml.erros['/products/MLB11'] = POLICY
        ml.erros['/products/MLB21'] = POLICY
        ml.erros['/products/MLB31'] = POLICY
        responder = ml.responder

        def gets(c):   # o 403 vale para o produto, não para a lista
            if c.caminho.endswith('/items'):
                return ml.responder_sem_erros(c)
            return responder(c)
        erros = ml.erros

        def sem_erros(c):
            guardado = dict(erros)
            erros.clear()
            try:
                return responder(c)
            finally:
                erros.update(guardado)
        ml.responder_sem_erros = sem_erros
        ml.op.responder = T.api_padrao(gets=gets)
        codigo, out = self.direto(ml, amostra=3)
        self.assertEqual(codigo, 0)
        produtos = [c for c in ml.op.gets() if re.fullmatch(r'/products/MLB[0-9]+', c.caminho)]
        self.assertEqual(len(produtos), 1)   # bloqueado depois do 1º 403 PolicyAgent
        self.assertIn('F8 /products/{id}: 403 PA_UNAUTHORIZED_RESULT_FROM_POLICIES: 1', out)
        self.assertIn('F10 provados: 3 de 3 (100%) (bbw: 0, lista: 3)', out)

    def test_404_403_comum_e_500_no_produto_seguem_para_a_lista(self):
        self.banco([(n, 'Perfumes e Perfumaria', 100.0, self.recente()) for n in range(1, 4)])
        ml = C.MLFalso()
        for n, erro in ((1, (404, {'error': 'not_found'})), (2, (403, {'error': 'forbidden'})),
                        (3, (500, {'error': 'internal_error'}))):
            ml.buscas[ml.q(n)] = [{'id': f'MLB{n}1', 'status': 'active'}]
            ml.listas[f'MLB{n}1'] = [[C.linha_lista(self.mlb(n), 100.0)]]
            ml.erros[f'/products/MLB{n}1'] = erro
        responder = ml.responder

        def gets(c):
            if c.caminho.endswith('/items'):
                guardado = dict(ml.erros)
                ml.erros.clear()
                try:
                    return responder(c)
                finally:
                    ml.erros.update(guardado)
            return responder(c)
        ml.op.responder = T.api_padrao(gets=gets)
        codigo, out = self.direto(ml, amostra=3)
        self.assertEqual(codigo, 0)
        self.assertIn('F8 /products/{id}: 403 forbidden: 1, 404 not_found: 1, 500 internal_error: 1; lidos: 0', out)
        self.assertIn('F10 provados: 3 de 3 (100%) (bbw: 0, lista: 3)', out)
        # 403 sem PolicyAgent não bloqueia: os 3 produtos foram pedidos
        self.assertEqual(len([c for c in ml.op.gets() if re.fullmatch(r'/products/MLB[0-9]+', c.caminho)]), 3)

    def test_erro_na_busca_de_um_item_nao_para_os_seguintes(self):
        self.banco([(n, 'Perfumes e Perfumaria', 100.0, self.recente()) for n in range(1, 4)])
        ml = C.MLFalso()
        for n in range(1, 4):
            self.provar_por_bbw(ml, ml.q(n), n, 100.0)
        ml.buscas[ml.q(2)] = (500, {'error': 'internal_error'})
        codigo, out = self.direto(ml, amostra=3)
        self.assertEqual(codigo, 0)
        self.assertIn('F7 /products/search (título): 200: 2, 500 internal_error: 1; itens com candidato: 2 de 3', out)
        self.assertIn('F10 provados: 2 de 3', out)
        self.assertNotIn('Parcial', out)

    def test_resposta_fora_do_formato_conta_e_segue(self):
        self.banco([(n, 'Perfumes e Perfumaria', 100.0, self.recente()) for n in range(1, 3)])
        ml = C.MLFalso()
        ml.buscas[ml.q(1)] = [{'id': 'MLB11', 'status': 'active'}]
        ml.produtos['MLB11'] = ['não', 'é', 'dict']
        ml.listas['MLB11'] = [[C.linha_lista(self.mlb(1), 100.0)]]
        self.provar_por_bbw(ml, ml.q(2), 2, 100.0)
        codigo, out = self.direto(ml, amostra=2)
        self.assertEqual(codigo, 0)
        self.assertIn('fora do formato: 1', self.linha(out, 'F8 '))
        self.assertIn('F10 provados: 2 de 2 (100%) (bbw: 1, lista: 1)', out)

    def test_f13_f14_f15_com_erros_diferentes_saem_cada_um_na_sua_linha(self):
        self.banco([(1, 'Perfumes e Perfumaria', 100.0, self.recente())])
        ml = C.MLFalso()
        pid = self.provar_por_bbw(ml, ml.q(1), 1, 100.0)
        ml.produtos[pid]['category_id'] = 'MLB1055'
        ml.erros['/reviews/'] = (404, {'error': 'not_found'})
        ml.erros['/highlights/'] = POLICY
        ml.erros['/sites/'] = (500, {})
        codigo, out = self.direto(ml, amostra=1)
        self.assertEqual(codigo, 0)
        self.assertEqual(self.linha(out, 'F13 '), 'F13 /reviews/item/{id}: 404 not_found')
        self.assertEqual(self.linha(out, 'F14 '), 'F14 /highlights/MLB/category/{cat}: 403 '
                         'PA_UNAUTHORIZED_RESULT_FROM_POLICIES (falta permissão funcional no DevCenter)')
        self.assertEqual(self.linha(out, 'F15 '), 'F15 /sites/MLB/search?product_id: 500')

    def test_categoria_e_produto_hostis_nao_entram_no_caminho(self):
        self.banco([(1, 'Perfumes e Perfumaria', 100.0, self.recente())])
        ml = C.MLFalso()
        ml.buscas[ml.q(1)] = [{'id': '../../users/me', 'status': 'active'}, {'id': 'MLB11', 'status': 'active'}]
        ml.produtos['MLB11'] = C.prod('MLB11', self.mlb(1), 100.0, categoria='MLB1/../../users/me')
        ml.produtos['MLB11']['buy_box_winner']['category_id'] = '../x'
        codigo, out = self.direto(ml, amostra=1)
        self.assertEqual(codigo, 0)
        self.assertIn('F14 /highlights/MLB/category/{cat}: pulado (sem category_id)', out)
        self.assertTrue(all('..' not in c.url and 'users' not in c.caminho for c in ml.op.chamadas))
        self.assertEqual(ml.gets('/sites/MLB/search')[0].query['product_id'], 'MLB11')


# ---------- CA2: pai → filhos (até 3) ----------
class TestPaiEFilhos(Qa):
    def test_so_os_3_primeiros_filhos_validos_de_cada_pai_sao_lidos(self):
        self.banco([(1, 'Perfumes e Perfumaria', 100.0, self.recente())])
        ml = C.MLFalso()
        filhos_a = ['MLB1/../x', 'MLB１２', 'MLB101', 7, None, 'MLB102', 'MLB103'] + \
            [f'MLB1{k:02d}' for k in range(4, 11)]
        ml.buscas[ml.q(1)] = [
            {'id': 'MLB100', 'status': 'inactive', 'children_ids': filhos_a},
            {'id': 'MLB200', 'status': 'active', 'children_ids': [f'MLB20{k}' for k in range(1, 9)]}]
        for pid in [f'MLB1{k:02d}' for k in range(1, 11)] + [f'MLB20{k}' for k in range(1, 9)]:
            # o filho 4 em diante provaria: se o limite de 3 quebrar, o F10 acusa
            certo = pid in ('MLB104', 'MLB105', 'MLB204', 'MLB205')
            ml.produtos[pid] = C.prod(pid, self.mlb(1) if certo else 'MLB6666666666', 100.0)
        codigo, out = self.direto(ml, amostra=1)
        self.assertEqual(codigo, 0)
        lidos = [c.caminho for c in ml.op.gets() if re.fullmatch(r'/products/MLB[0-9]+', c.caminho)]
        self.assertEqual(lidos, ['/products/MLB101', '/products/MLB102', '/products/MLB103',
                                 '/products/MLB201', '/products/MLB202', '/products/MLB203'])
        self.assertIn('F10 provados: 0 de 1', out)
        self.assertIn('média de candidatos: 6.0', out)
        self.assertNotIn('/products/MLB100', [c.caminho for c in ml.op.chamadas])

    def test_filho_provado_pela_lista(self):
        self.banco([(1, 'Perfumes e Perfumaria', 100.0, self.recente())])
        ml = C.MLFalso()
        ml.buscas[ml.q(1)] = [{'id': 'MLB100', 'status': 'inactive', 'children_ids': ['MLB101', 'MLB102']}]
        ml.produtos['MLB101'] = C.prod('MLB101', 'MLB6666666666', 1.0)
        ml.produtos['MLB102'] = C.prod('MLB102', 'MLB6666666666', 1.0)
        ml.listas['MLB102'] = [[C.linha_lista(self.mlb(1), 100.0)]]
        codigo, out = self.direto(ml, amostra=1)
        self.assertIn('F10 provados: 1 de 1 (100%) (bbw: 0, lista: 1)', out)
        self.assertIn('F11 preço do banco até 48 h: igual 1', out)


# ---------- CA2: prova por bbw e por lista ----------
class TestProva(Qa):
    def test_item_na_3a_pagina_prova_com_offset(self):
        self.banco([(1, 'Perfumes e Perfumaria', 100.0, self.recente())])
        ml = C.MLFalso()
        ml.buscas[ml.q(1)] = [{'id': 'MLB11', 'status': 'active'}]
        ml.produtos['MLB11'] = C.prod('MLB11', 'MLB6666666666', 1.0)
        ml.listas['MLB11'] = [[C.linha_lista('MLB6000000001', 1.0), C.linha_lista('MLB6000000002', 1.0)],
                              [C.linha_lista('MLB6000000003', 1.0), C.linha_lista('MLB6000000004', 1.0)],
                              [C.linha_lista(self.mlb(1), 100.0)]]
        codigo, out = self.direto(ml, amostra=1)
        self.assertIn('F10 provados: 1 de 1 (100%) (bbw: 0, lista: 1)', out)
        offsets = [c.query.get('offset') for c in ml.gets('/products/MLB11/items')]
        self.assertEqual(offsets, [None, '2', '4'])

    def test_item_na_4a_pagina_nao_prova_e_so_3_paginas_sao_lidas(self):
        self.banco([(1, 'Perfumes e Perfumaria', 100.0, self.recente())])
        ml = C.MLFalso()
        ml.buscas[ml.q(1)] = [{'id': 'MLB11', 'status': 'active'}]
        ml.produtos['MLB11'] = C.prod('MLB11', 'MLB6666666666', 1.0)
        ml.listas['MLB11'] = [[C.linha_lista(f'MLB600000000{i}', 1.0)] for i in range(3)] + \
            [[C.linha_lista(self.mlb(1), 100.0)]]
        codigo, out = self.direto(ml, amostra=1)
        self.assertIn('F10 provados: 0 de 1', out)
        self.assertEqual(len(ml.gets('/products/MLB11/items')), 3)

    def test_paging_total_alcancado_para_cedo(self):
        self.banco([(1, 'Perfumes e Perfumaria', 100.0, self.recente())])
        ml = C.MLFalso()
        ml.buscas[ml.q(1)] = [{'id': 'MLB11', 'status': 'active'}]
        ml.produtos['MLB11'] = C.prod('MLB11', 'MLB6666666666', 1.0)
        ml.listas['MLB11'] = [[C.linha_lista('MLB6000000001', 1.0)]]
        self.direto(ml, amostra=1)
        self.assertEqual(len(ml.gets('/products/MLB11/items')), 1)

    def test_paging_hostil_nao_faz_laco(self):
        """total como texto, bool, negativo ou enorme com página vazia: no máximo 3 pedidos e nenhum laço."""
        for paging in ({'total': '999'}, {'total': True}, {'total': -1}, {'total': 10 ** 30}, None, 'x'):
            self.banco([(1, 'Perfumes e Perfumaria', 100.0, self.recente())])
            ml = C.MLFalso()
            ml.buscas[ml.q(1)] = [{'id': 'MLB11', 'status': 'active'}]
            ml.produtos['MLB11'] = C.prod('MLB11', 'MLB6666666666', 1.0)
            responder = ml.responder

            def gets(c, paging=paging, responder=responder):
                if c.caminho == '/products/MLB11/items':
                    return {'results': [C.linha_lista('MLB6000000001', 1.0)], 'paging': paging}
                return responder(c)
            ml.op.responder = T.api_padrao(gets=gets)
            codigo, out = self.direto(ml, amostra=1)
            self.assertEqual(codigo, 0, paging)
            self.assertLessEqual(len(ml.gets('/products/MLB11/items')), 3, paging)
            for sufixo in ('', '-wal', '-shm'):
                with contextlib.suppress(FileNotFoundError):
                    os.remove(self.db + sufixo)

    def test_bbw_que_prova_dispensa_a_lista(self):
        self.banco([(1, 'Perfumes e Perfumaria', 100.0, self.recente())])
        ml = C.MLFalso()
        pid = self.provar_por_bbw(ml, ml.q(1), 1, 100.0)
        ml.listas[pid] = [[C.linha_lista(self.mlb(1), 999.0)]]
        codigo, out = self.direto(ml, amostra=1)
        self.assertIn('(bbw: 1, lista: 0)', out)
        self.assertEqual(ml.gets(f'/products/{pid}/items'), [])
        self.assertIn('F11 preço do banco até 48 h: igual 1, até 2% 0, acima de 2% 0', out)

    def test_id_parecido_no_bbw_ou_na_lista_nao_prova(self):
        parecidos = {1: lambda m: m.lower(), 2: lambda m: ' ' + m, 3: lambda m: int(m[3:]),
                     4: lambda m: 'MLB-' + m[3:], 5: lambda m: m + '\n', 6: lambda m: m + '0',
                     7: lambda m: m[:-1], 8: lambda m: 'MLB' + ''.join(chr(0xff10 + int(d)) for d in m[3:]),
                     9: lambda m: [m], 10: lambda m: {'id': m}}
        self.banco([(n, 'Perfumes e Perfumaria', 100.0, self.recente()) for n in parecidos])
        ml = C.MLFalso()
        for n, f in parecidos.items():
            ml.buscas[ml.q(n)] = [{'id': f'MLB{n}1', 'status': 'active'}]
            ml.produtos[f'MLB{n}1'] = C.prod(f'MLB{n}1', 'MLB6666666666', 100.0)
            ml.produtos[f'MLB{n}1']['buy_box_winner']['item_id'] = f(self.mlb(n))
            ml.listas[f'MLB{n}1'] = [[C.linha_lista(f(self.mlb(n)), 100.0)]]
        codigo, out = self.direto(ml, amostra=len(parecidos))
        self.assertEqual(codigo, 0)
        self.assertIn(f'F10 provados: 0 de {len(parecidos)} (0%)', out)

    def test_preco_do_f11_vem_da_linha_do_item_e_nao_do_vencedor(self):
        """O vencedor é outro anúncio com o preço igual ao do banco; a linha do nosso item está 50% acima."""
        self.banco([(1, 'Perfumes e Perfumaria', 100.0, self.recente())])
        ml = C.MLFalso()
        ml.buscas[ml.q(1)] = [{'id': 'MLB11', 'status': 'active'}]
        ml.produtos['MLB11'] = C.prod('MLB11', 'MLB6666666666', 100.0)
        ml.listas['MLB11'] = [[C.linha_lista('MLB6666666666', 100.0), C.linha_lista(self.mlb(1), 150.0)]]
        codigo, out = self.direto(ml, amostra=1)
        self.assertIn('(bbw: 0, lista: 1)', out)
        self.assertIn('F11 preço do banco até 48 h: igual 0, até 2% 0, acima de 2% 1', out)
        self.assertIn(f'F11 acima de 2%: {self.mlb(1)}', out)


# ---------- CA2: F11, faixas e janela de 48 h ----------
class TestF11(Qa):
    def test_faixas_nas_bordas_de_2_por_cento(self):
        agora = self.agora_real
        apis = {1: 100.0, 2: 100.01, 3: 102.0, 4: 102.01, 5: 98.0, 6: 97.99, 7: 99.996, 8: 100.004}
        self.banco_titulos([(n, 'Perfumes e Perfumaria', 'R$ 100', self.quando(agora, 3600), f'Produto {n}')
                            for n in apis])
        ml = C.MLFalso()
        for n, preco in apis.items():
            self.provar_por_bbw(ml, f'produto {n}', n, preco)
        codigo, out = self.direto(ml, amostra=len(apis), agora=agora)
        # igual: 100, 99.996 e 100.004 (arredondam para 100,00); até 2%: 100.01, 102, 98; acima: 102.01, 97.99
        self.assertIn('F11 preço do banco até 48 h: igual 3, até 2% 3, acima de 2% 2', out)
        acima = self.linha(out, 'F11 acima de 2%: ').split(': ', 1)[1].split(', ')
        self.assertEqual(sorted(acima), [self.mlb(4), self.mlb(6)])

    def test_preco_do_banco_com_centavos_e_milhar(self):
        agora = self.agora_real
        casos = {1: ('R$ 1.299,90', 1299.9), 2: ('R$ 4.285', 4285), 3: ('R$ 69,90', 69.9), 4: ('69.9', 69.9),
                 5: ('R$ 1.000', 1020.0), 6: ('R$ 1.000', 1020.01)}
        self.banco_titulos([(n, 'Perfumes e Perfumaria', p, self.quando(agora, 60), f'Produto {n}')
                            for n, (p, _) in casos.items()])
        ml = C.MLFalso()
        for n, (_, api) in casos.items():
            self.provar_por_bbw(ml, f'produto {n}', n, api)
        codigo, out = self.direto(ml, amostra=len(casos), agora=agora)
        self.assertIn('F11 preço do banco até 48 h: igual 4, até 2% 1, acima de 2% 1', out)

    def test_janela_de_48_h_e_5_min_no_futuro(self):
        agora = float(int(self.agora_real))
        datas = {1: self.quando(agora, 48 * 3600), 2: self.quando(agora, 48 * 3600 + 1),
                 3: self.quando(agora, -300), 4: self.quando(agora, -301), 5: self.quando(agora, 0),
                 6: '2026-02-30T10:00:00', 7: '2026-11-05 10:00:00', 8: '', 9: None,
                 10: self.quando(agora, 3600) + 'Z', 11: '２０２６-11-05T10:00:00'}
        self.banco_titulos([(n, 'Perfumes e Perfumaria', 'R$ 100', d, f'Produto {n}') for n, d in datas.items()])
        ml = C.MLFalso()
        for n in datas:
            self.provar_por_bbw(ml, f'produto {n}', n, 100.0)
        codigo, out = self.direto(ml, amostra=len(datas), agora=agora)
        self.assertIn('F11 preço do banco até 48 h: igual 3, até 2% 0, acima de 2% 0', out)
        self.assertIn('F11 preço do banco mais antigo ou sem data: igual 8, até 2% 0, acima de 2% 0', out)

    def test_preco_da_api_invalido_nao_compara(self):
        agora = self.agora_real
        apis = {1: float('nan'), 2: float('inf'), 3: 0, 4: -5.0, 5: 1e7, 6: '100.00', 7: True, 8: None}
        self.banco_titulos([(n, 'Perfumes e Perfumaria', 'R$ 100', self.quando(agora, 60), f'Produto {n}')
                            for n in apis])
        ml = C.MLFalso()
        for n, preco in apis.items():
            self.provar_por_bbw(ml, f'produto {n}', n, preco)
        codigo, out = self.direto(ml, amostra=len(apis), agora=agora)
        self.assertEqual(codigo, 0)
        self.assertIn(f'F10 provados: {len(apis)} de {len(apis)}', out)
        self.assertIn(f'sem preço BRL na API {len(apis)}', out)
        self.assertIn('F11 preço do banco até 48 h: igual 0, até 2% 0, acima de 2% 0', out)


# ---------- CA1: banco só leitura e nenhum arquivo novo ----------
class TestBancoQa(Qa):
    def test_conexao_da_amostra_recusa_escrita(self):
        """Com a conexão que o itens_do_banco abriu: INSERT, UPDATE e até desligar o query_only não gravam."""
        self.banco([(1, 'Perfumes e Perfumaria', 100.0, self.recente())])
        tentativas = []
        conectar = sqlite3.connect

        class Espiao:
            def __init__(self, con):
                self.con = con

            def execute(self, sql, *a):
                return self.con.execute(sql, *a)

            def close(self):
                for sql in ("INSERT INTO items (loja, item_id, cat, url) VALUES ('ml', 'MLB1111111', 'x', 'x')",
                            "UPDATE items SET preco = 'R$ 1'", 'CREATE TABLE intrusa (x)'):
                    try:
                        self.con.execute(sql)
                        self.con.commit()
                        tentativas.append(('gravou', sql))
                    except sqlite3.Error as e:
                        tentativas.append(('recusou', str(e)))
                self.con.execute('PRAGMA query_only = OFF')
                try:
                    self.con.execute("UPDATE items SET preco = 'R$ 1'")
                    self.con.commit()
                    tentativas.append(('gravou', 'sem query_only'))
                except sqlite3.Error as e:
                    tentativas.append(('recusou', str(e)))
                self.con.close()
        with mock.patch.object(M.sqlite3, 'connect', lambda *a, **kw: Espiao(conectar(*a, **kw))):
            itens = M.itens_do_banco(self.db)
        self.assertEqual(len(itens), 1)
        self.assertEqual([t[0] for t in tentativas], ['recusou'] * 4, tentativas)
        self.assertIn('readonly', tentativas[-1][1])   # o mode=ro segura mesmo sem o query_only
        con = sqlite3.connect(self.db)
        self.assertEqual(con.execute("SELECT count(*) FROM items WHERE preco = 'R$ 1'").fetchone()[0], 0)
        con.close()

    def test_banco_com_coluna_faltando_ou_tipos_estranhos(self):
        con = sqlite3.connect(self.db)
        con.execute('CREATE TABLE items (id INTEGER PRIMARY KEY, loja, item_id, titulo, cat, preco)')
        con.commit()
        con.close()
        self.assertEqual(M.itens_do_banco(self.db), [])   # sem preco_em
        os.remove(self.db)
        con = sqlite3.connect(self.db)
        con.execute('CREATE TABLE items (id INTEGER PRIMARY KEY, loja, item_id, titulo, cat, preco, preco_em)')
        con.executemany('INSERT INTO items (loja, item_id, titulo, cat, preco, preco_em) VALUES (?,?,?,?,?,?)', [
            ('ml', 'MLB1234567', b'bytes', 5, 100.5, 12345), ('ml', 'MLB1234568\n', 't', 'c', 'p', 'e'),
            ('ml', 'MLB1234569', None, None, None, None), ('amazon', 'MLB1234570', 't', 'c', 'p', 'e')])
        con.commit()
        con.close()
        itens = M.itens_do_banco(self.db)
        self.assertEqual(itens, [{'item_id': 'MLB1234567', 'titulo': '', 'cat': '', 'preco': '', 'preco_em': ''},
                                 {'item_id': 'MLB1234569', 'titulo': '', 'cat': '', 'preco': '', 'preco_em': ''}])

    # -- servidor.py de verdade, em porta livre e banco temporário --
    def subir_servidor(self):
        porta = porta_livre()
        env = {k: v for k, v in os.environ.items() if not k.startswith('ACHADINHOS_')}
        env.update(ACHADINHOS_DB=self.db, ACHADINHOS_PORTA=str(porta), ACHADINHOS_DISPARO='0',
                   ACHADINHOS_API_TOKEN_ARQUIVO='/nao/existe', PYTHONDONTWRITEBYTECODE='1')
        p = subprocess.Popen([sys.executable, os.path.join(RAIZ, 'servidor.py')], env=env,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(self.parar, p)
        limite = time.monotonic() + 20
        while True:
            try:
                socket.create_connection(('127.0.0.1', porta), timeout=1).close()
                break
            except OSError:
                self.assertIsNone(p.poll(), 'o servidor não subiu')
                self.assertLess(time.monotonic(), limite)
                time.sleep(0.1)
        return porta

    @staticmethod
    def parar(p):
        if p.poll() is None:
            p.terminate()
            p.wait(10)

    def itens_pela_api(self, porta):
        sem_proxy = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with sem_proxy.open(f'http://localhost:{porta}/api/items', timeout=10) as r:
            self.assertEqual(r.status, 200)
            return json.loads(r.read())

    def rodar_sonda_com_servidor(self):
        self.banco([(1, 'Perfumes e Perfumaria', 100.0, self.recente()), (2, 'Casa e Cozinha', 50.0, None)])
        porta = self.subir_servidor()
        antes_api = self.itens_pela_api(porta)
        time.sleep(0.3)
        antes = C.TestBancoSoLeitura.conteudo(self, self.pasta_db)
        ml = C.MLFalso()
        self.provar_por_bbw(ml, ml.q(1), 1, 100.0)
        self.gravar_real()
        codigo, out, err = self.rodar_cat(['sondar', '--catalogo', '--amostra', '3'], ml)
        self.assertEqual(codigo, 0, err)
        self.assertIn('F10 provados: 1 de 2', out)
        depois = C.TestBancoSoLeitura.conteudo(self, self.pasta_db)
        return porta, antes_api, antes, depois

    def test_com_servidor_no_ar_o_banco_nao_muda_e_o_servidor_segue(self):
        porta, antes_api, antes, depois = self.rodar_sonda_com_servidor()
        nome = os.path.basename(self.db)
        self.assertEqual(antes[nome], depois[nome])
        self.assertEqual(self.itens_pela_api(porta), antes_api)

    def test_com_servidor_no_ar_nenhum_arquivo_novo_na_pasta_do_banco(self):
        """CA1 (texto ajustado na rodada 2, risco aceito pelo lead para o Q1 da rodada 1): o servidor.py abre uma
        conexão por pedido, então, parado entre pedidos, o banco WAL fica sem -wal/-shm, e o próprio SQLite os cria
        ao abrir em mode=ro. Fica fixado o comportamento aceito: os únicos arquivos novos possíveis são <db>-wal
        (vazio) e <db>-shm, nada some e o .db continua igual byte a byte."""
        _, _, antes, depois = self.rodar_sonda_com_servidor()
        nome = os.path.basename(self.db)
        novos = set(depois) - set(antes)
        self.assertLessEqual(novos, {f'{nome}-wal', f'{nome}-shm'}, sorted(depois))
        self.assertLessEqual(set(antes), set(depois))
        if f'{nome}-wal' in novos:
            self.assertEqual(depois[f'{nome}-wal'], b'')   # o -wal criado pelo mode=ro não traz página nenhuma
        self.assertEqual(antes[nome], depois[nome])
        for arquivo in antes:   # o -shm só é comparado pelo nome (conteudo() o guarda como None)
            self.assertEqual(antes[arquivo], depois[arquivo], arquivo)

    def test_wal_e_shm_do_banco_real_estao_no_gitignore(self):
        """A outra metade do risco aceito: as sobras do mode=ro no banco real nunca vão para o git."""
        if not os.path.isdir(os.path.join(RAIZ, '.git')):
            self.skipTest('sem .git (espelho)')
        r = subprocess.run(['git', '-C', RAIZ, 'check-ignore', 'achadinhos.db-wal', 'achadinhos.db-shm'],
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.split(), ['achadinhos.db-wal', 'achadinhos.db-shm'])


# ---------- buscas.json ausente, fora do formato ou com aba desconhecida ----------
class TestBuscas(Qa):
    def com_buscas(self, conteudo, modo='w'):
        caminho = os.path.join(self.dir, f'buscas-{len(os.listdir(self.dir))}.json')
        with open(caminho, modo) as f:
            f.write(conteudo)
        return caminho

    def test_formatos_ruins_pulam_o_f12_sem_derrubar(self):
        self.banco([(1, 'Perfumes e Perfumaria', 100.0, self.recente())])
        ruins = [self.com_buscas('[]'), self.com_buscas('{"Aba": "não é lista"}'), self.com_buscas('{x'),
                 self.com_buscas(b'\xff\xfe\x00', 'wb'), self.com_buscas('[' * 100000 + ']' * 100000),
                 self.com_buscas('{"Aba": ["' + 'a' * (1024 * 1024) + '"]}'), self.com_buscas(''), self.dir,
                 self.com_buscas('{"Aba": ["", "   ", 5, null]}')]
        for caminho in ruins:
            ml = C.MLFalso()
            codigo, out = self.direto(ml, amostra=1, buscas=caminho)
            self.assertEqual(codigo, 0, caminho)
            self.assertIn('F12 /products/search (termos): pulado (buscas.json ausente ou fora do formato)', out)
            self.assertEqual([c for c in ml.gets('/products/search') if c.query.get('q') not in
                              (ml.q(1),)], [], caminho)

    def test_buscas_de_ate_1_mb_ainda_vale(self):
        self.banco([(1, 'Perfumes e Perfumaria', 100.0, self.recente())])
        conteudo = json.dumps({'Perfumes e Perfumaria': ['Body splash', 'Perfume']})
        caminho = self.com_buscas(conteudo + ' ' * (M.MAX_BUSCAS - len(conteudo)))
        self.assertEqual(os.path.getsize(caminho), M.MAX_BUSCAS)
        codigo, out = self.direto(C.MLFalso(), amostra=1, buscas=caminho)
        self.assertIn('F12 /products/search (2 termos): 200: 2', out)
        self.assertIn('F10 aba Perfumes e Perfumaria: 0 de 1', out)

    def test_termos_repetidos_e_vazios_nao_viram_busca(self):
        self.banco([(1, 'Perfumes e Perfumaria', 100.0, self.recente())])
        caminho = self.com_buscas(json.dumps({'A': ['Perfume', 'Perfume', ' ', ''], 'B': ['Perfume', 'Notebook']}))
        ml = C.MLFalso()
        codigo, out = self.direto(ml, amostra=1, buscas=caminho)
        self.assertIn('F12 /products/search (2 termos)', out)
        qs = sorted(c.query['q'] for c in ml.gets('/products/search') if c.query['q'] in ('Perfume', 'Notebook'))
        self.assertEqual(qs, ['Notebook', 'Perfume'])

    def test_aba_desconhecida_ou_com_quase_o_mesmo_nome_vira_outra_aba(self):
        self.banco([(1, 'Perfumes e Perfumaria ', 100.0, self.recente()),
                    (2, 'perfumes e perfumaria', 100.0, self.recente()),
                    (3, 'Perfumes​e Perfumaria', 100.0, self.recente()),
                    (4, 'Perfumes e Perfumaria', 100.0, self.recente()),
                    (5, '', 100.0, self.recente())])
        codigo, out = self.direto(C.MLFalso(), amostra=5)
        self.assertIn('F10 aba (outra aba): 0 de 4', out)
        self.assertIn('F10 aba Perfumes e Perfumaria: 0 de 1', out)
        self.assertEqual(len([l for l in out.splitlines() if l.startswith('F10 aba ')]), 2)
        self.assertSaidaLimpa(out, {self.mlb(n) for n in range(1, 6)})

    def test_buscas_json_real_do_projeto_e_lido(self):
        """O padrão do módulo é o buscas.json do projeto (17 abas): as abas reais aparecem pelo nome."""
        self.assertEqual(M.BUSCAS, os.path.join(RAIZ, 'buscas.json'))
        abas, termos = M._abas_e_termos()
        with open(os.path.join(RAIZ, 'buscas.json'), encoding='utf-8') as f:
            real = json.load(f)
        self.assertEqual(abas, set(real))
        self.assertGreaterEqual(len(termos), M.TERMOS_F12)


# ---------- rodada 2: bordas das correções R1, R2, R3, R5, S1 e S3 que o test_ml_api_catalogo não cobre ----------
class TestRodada2Qa(Qa):
    def dois_pela_lista(self):
        """2 itens provados pela lista na 1ª página: cada um custa 3 chamadas (busca, produto com bbw de outro
        anúncio, /items) e tem 1 resultado descartado na busca; mais o limit=50 no início."""
        self.banco([(n, 'Perfumes e Perfumaria', 100.0 + n, self.recente()) for n in (1, 2)])
        ml = C.MLFalso()
        for n in (1, 2):
            pid = f'MLB71{n}'
            ml.buscas[ml.q(n)] = [{'id': pid, 'status': 'active'}, 'descartado']
            ml.produtos[pid] = C.prod(pid, 'MLB6666666666', 1.0)
            ml.listas[pid] = [[C.linha_lista(self.mlb(n), 100.0 + n)]]
        return ml

    def test_r1_corte_exato_na_ultima_chamada_do_item_conta_o_item(self):
        """O teto do laço cai exatamente na última chamada do 1º item (o /items que o prova): ele está inteiro e
        conta em tudo; o 2º para antes da busca e não conta em nada."""
        ml = self.dois_pela_lista()
        teto = 4 + M.RESERVA_FINAIS
        codigo, out = self.direto(ml, amostra=2, teto=teto)
        self.assertEqual(codigo, 0)
        laco = [c.caminho for c in ml.gets()[:5]]
        self.assertRegex(' '.join(laco[:4]), r'\A/products/search /products/search /products/(MLB71[12]) '
                                             r'/products/\1/items\Z')
        self.assertIn(ml.gets()[4].query.get('q'), C.TERMOS)   # a 5ª chamada já é do F12
        self.assertIn(f'Parcial (teto de {teto} chamadas, com {M.RESERVA_FINAIS} guardadas para F12 a F15): '
                      'itens vistos 1 de 2', out)
        self.assertIn('itens com candidato: 1 de 1; média de candidatos: 1.0; sem título utilizável: 0; '
                      'descartados: 1\n', out)
        self.assertIn('F10 provados: 1 de 1 (100%) (bbw: 0, lista: 1)', out)
        self.assertIn('F10 aba Perfumes e Perfumaria: 1 de 1\n', out)
        self.assertIn('F11 preço do banco até 48 h: igual 1, até 2% 0, acima de 2% 0', out)

    def test_r1_item_cortado_antes_da_2a_pagina_da_lista_nao_conta(self):
        """O item precisa da 2ª página do /items e o teto acaba antes dela: buscados, com candidato,
        descartados, provados, aba e F11 ficam em zero; F8 e F9 contam por chamada (o que de fato saiu)."""
        ml = self.dois_pela_lista()
        for n in (1, 2):
            ml.listas[f'MLB71{n}'] = [[C.linha_lista('MLB6666666667', 5.0)], [C.linha_lista(self.mlb(n), 100.0)]]
        codigo, out = self.direto(ml, amostra=2, teto=4 + M.RESERVA_FINAIS)
        self.assertEqual(codigo, 0)
        self.assertIn('itens vistos 0 de 2', out)
        self.assertIn('itens com candidato: 0 de 0; média de candidatos: 0; sem título utilizável: 0; '
                      'descartados: 0\n', out)
        self.assertIn('F10 provados: 0 de 0 (bbw: 0, lista: 0)\n', out)
        self.assertIn('F10 exemplos: (nenhum)\n', out)
        self.assertNotIn('F10 aba', out)
        self.assertIn('F11 preço do banco até 48 h: igual 0, até 2% 0, acima de 2% 0', out)
        self.assertIn('F11 sem comparação: sem preço legível no banco 0, sem preço BRL na API 0', out)
        self.assertIn('; lidos: 1;', out)
        self.assertIn('F9 /products/{id}/items: 200: 1;', out)

    def test_r1_limite_no_items_do_2o_item_so_conta_o_1o(self):
        ml = self.dois_pela_lista()
        lidas = []
        responder = ml.responder

        def gets(c):
            if c.caminho.endswith('/items'):
                if c.caminho not in lidas:
                    lidas.append(c.caminho)
                if len(lidas) == 2 and c.caminho == lidas[1]:
                    return T.erro_http(429, {'error': 'too_many_requests'})
            return responder(c)
        ml.op.responder = T.api_padrao(gets=gets)
        self.gravar_real()
        codigo, out, err = self.rodar_cat(['sondar', '--catalogo', '--amostra', '2'], ml)
        self.assertEqual(codigo, 3, err)
        self.assertIn('Parcial (limite de requisições (429)): itens vistos 1 de 2', out)
        self.assertIn('itens com candidato: 1 de 1; média de candidatos: 1.0; sem título utilizável: 0; '
                      'descartados: 1\n', out)
        self.assertIn('F10 provados: 1 de 1 (100%) (bbw: 0, lista: 1)', out)
        self.assertIn('F10 aba Perfumes e Perfumaria: 1 de 1\n', out)
        self.assertIn('F11 preço do banco até 48 h: igual 1,', out)
        self.assertIn('; lidos: 2;', out)                        # o produto do 2º saiu: F8 conta por chamada
        self.assertIn('F9 /products/{id}/items: 200: 1;', out)   # o 429 não vira status do F9
        self.assertRegex(out, r'chamadas: 7, 429: 3, tempo: ')   # 1 + 3 + 3: as 3 tentativas do 429 são 1

    def test_r2_404_com_codigos_diferentes_e_produto_ilegivel(self):
        """A soma do "404: N" junta 404 com e sem código; produto com 403 comum ou fora do formato conta como
        "sem produto" e não bloqueia os seguintes; o 404 da 2ª página usa o estado do produto lido."""
        self.banco([(n, 'Perfumes e Perfumaria', 100.0, self.recente()) for n in range(1, 5)])
        ml = C.MLFalso()
        for n in range(1, 5):
            ml.buscas[ml.q(n)] = [{'id': f'MLB72{n}', 'status': 'active'}]
        ml.produtos['MLB723'] = C.prod('MLB723', nulo=True)
        ml.produtos['MLB724'] = C.prod('MLB724', 'MLB6666666666', 1.0)
        ml.listas['MLB724'] = [[C.linha_lista('MLB6666666667', 5.0)], [C.linha_lista('MLB6666666668', 5.0)]]
        responder = ml.responder

        def gets(c):
            especiais = {
                '/products/MLB721': (403, {'error': 'forbidden'}),   # 403 sem PolicyAgent
                '/products/MLB721/items': (404, {}),
                '/products/MLB722': None,                            # [] : fora do formato
                '/products/MLB722/items': (404, {'error': 'not_found'}),
                '/products/MLB723/items': (404, {'error': 'resource_not_found'})}
            if c.caminho in especiais:
                v = especiais[c.caminho]
                return [] if v is None else T.erro_http(*v)
            if c.caminho == '/products/MLB724/items' and c.query.get('offset') == '1':
                return T.erro_http(404, {'error': 'not_found'})
            return responder(c)
        ml.op.responder = T.api_padrao(gets=gets)
        codigo, out = self.direto(ml, amostra=4)
        self.assertEqual(codigo, 0)
        f9 = self.linha(out, 'F9 ')
        self.assertIn('F9 /products/{id}/items: 200: 1, 404: 1, 404 not_found: 2, 404 resource_not_found: 1; '
                      '404: 4 (bbw nulo 1, bbw de outro anúncio 1, bbw ausente 0, sem produto 2);', f9)
        f8 = self.linha(out, 'F8 ')
        self.assertIn('F8 /products/{id}: 200: 2, 403 forbidden: 1, fora do formato: 1; lidos: 2;', f8)
        for n in range(1, 5):   # o 403 comum não é PolicyAgent: nenhum produto deixou de ser lido
            self.assertEqual(len(ml.gets(f'/products/MLB72{n}')), 1)
        self.assertIn('F10 provados: 0 de 4', out)

    def test_s3_consulta_com_199_200_e_201_caracteres_depois_da_normalizacao(self):
        casos = {
            'a' * 199: 'a' * 199,
            'a' * 200: 'a' * 200,
            'a' * 201: 'a' * 200,                        # o corte cai no meio da palavra
            'x' * 198 + ' y': 'x' * 198 + ' y',          # 200 exatos terminando em palavra de 1 letra
            'x' * 199 + ' y': 'x' * 199,                 # 201: o corte cai no espaço, e o espaço sai
            'x' * 198 + ' yz': 'x' * 198 + ' y',         # 201: sobra 1 letra da última palavra
            'É' * 201: 'e' * 200,                        # o acento sai antes do corte
            'ﬃ' * 66: 'ffi' * 66,                        # 66 caracteres viram 198
            'ﬃ' * 67: ('ffi' * 67)[:200],                # 67 viram 201: a medida é depois do NFKD
            '!' * 300 + 'b' * 199: 'b' * 199,            # pontuação não conta
            '. '.join(['w' * 18] * 10) + ' ' + 'z' * 11: ' '.join(['w' * 18] * 10) + ' ' + 'z' * 10,
        }
        for titulo, esperado in casos.items():
            q = M.consulta_do_titulo(titulo)
            self.assertEqual(q, esperado, (titulo[:20], len(titulo)))
            self.assertLessEqual(len(q), 200)
            self.assertRegex(q, r'\A[0-9a-z]+(?: [0-9a-z]+)*\Z')
        # e é esse q (no máximo 200) que vai na busca da sonda
        self.banco_titulos([(1, 'Perfumes e Perfumaria', 'R$ 1', self.recente(), 'a' * 199),
                            (2, 'Perfumes e Perfumaria', 'R$ 1', self.recente(), 'É' * 200),
                            (3, 'Perfumes e Perfumaria', 'R$ 1', self.recente(), 'ﬃ' * 67)])
        ml = C.MLFalso()
        self.direto(ml, amostra=3)
        enviados = sorted(c.query['q'] for c in ml.gets('/products/search') if c.query.get('limit') == '3'
                          and c.query['q'] not in C.TERMOS)
        self.assertEqual(enviados, sorted(['a' * 199, 'e' * 200, ('ffi' * 67)[:200]]))

    def f12_com_renovacao(self, gets_extra, token_status):
        self.banco([(n, 'Perfumes e Perfumaria', 100.0 + n, self.recente()) for n in range(1, 4)])
        ml = C.MLFalso()
        for n in range(1, 4):
            self.provar_por_bbw(ml, ml.q(n), n, 100.0 + n)
        responder = ml.responder

        def gets(c):
            if c.caminho == '/products/search' and c.query.get('q') in C.TERMOS:
                r = gets_extra(c)
                if r is not None:
                    return r
            return responder(c)
        ml.op.responder = T.api_padrao(gets=gets, token=lambda c: T.erro_http(token_status, {}))
        return ml

    def test_s1_renovacao_falhou_no_meio_do_f12_para_sem_repetir_a_amostra(self):
        """O token vence durante a 1ª busca do F12 e a renovação dá 502: para na hora (1 POST), com o bloco da
        amostra impresso uma vez só, sem F13 a F15 e sem o 502 virar status de endpoint do catálogo."""
        def vencer(c):
            self.agora[0] = T.AGORA + 7200
        ml = self.f12_com_renovacao(vencer, 502)
        self.gravar()
        sessao = self.sessao(ml.op)
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(M.RenovacaoFalhou) as cm:
            M.sondar_catalogo(sessao, self.db, amostra=3, buscas=self.buscas, agora=self.agora_real)
        out = out.getvalue()
        self.assertEqual(cm.exception.saida, 2)
        self.assertIn('[HTTP 502]', str(cm.exception))
        self.assertEqual((len(ml.op.posts()), len(ml.op.gets())), (1, 8))   # limit=50, 3 × 2 e a 1ª do F12
        self.assertEqual(len([l for l in out.splitlines() if l.startswith('F10 provados')]), 1)
        self.assertIn('F10 provados: 3 de 3', out)
        self.assertNotIn('Parcial', out)
        self.assertNotRegex(out, r'F[0-9]+ [^\n]*502')
        for f in ('F13', 'F14', 'F15'):
            self.assertNotIn(f, out)
        self.assertRegex(out, r'chamadas: 8, 429: 0, tempo: \d+\.\ds\n\Z')
        self.assertIs(sessao.opener, ml.op)

    def test_s1_401_no_f12_com_renovacao_500_sai_2_pela_cli(self):
        ml = self.f12_com_renovacao(lambda c: T.erro_http(401, {'error': 'invalid_token'}), 500)
        self.gravar_real()
        codigo, out, err = self.rodar_cat(['sondar', '--catalogo', '--amostra', '3'], ml, secret=T.SECRET)
        self.assertEqual(codigo, 2, err)
        self.assertEqual(err, f'ERRO: {M.RenovacaoFalhou(500)}\n')
        self.assertEqual((len(ml.op.posts()), len(ml.op.gets())), (1, 8))
        self.assertEqual(len([l for l in out.splitlines() if l.startswith('F10 provados')]), 1)
        self.assertNotIn('Parcial', out)
        self.assertNotIn('F13', out)
        self.assertRegex(out, r'chamadas: 8, 429: 0, tempo: ')
        T.sem_marcadores(self, out, err)

    def test_r3_so_e_pai_quem_tem_children_ids_lista_nao_vazia(self):
        ml = C.MLFalso()
        ml.buscas['abc'] = [{'id': 'MLB700', 'status': 'active', 'children_ids': []},
                            {'id': 'MLB701', 'children_ids': 'MLB702'},             # texto não é lista: não é pai
                            {'id': 'MLB703', 'status': 'active', 'children_ids': None}]
        ml.buscas['def'] = [{'id': 'MLB704', 'status': 'inactive', 'children_ids': ['MLB705', 'MLB705', 'x']},
                            {'id': 'MLB706', 'status': 'active', 'children_ids': ['MLB705']},   # repetido
                            {'id': 'MLB707', 'status': 'active', 'children_ids': [None, 7, '../x']}]
        self.gravar()
        sessao = self.sessao(ml.op)
        self.assertEqual(M._candidatos(sessao, 'abc'), (['MLB700', 'MLB701', 'MLB703'], 0))
        # pai inativo vale pelos filhos; filho repetido não repete nem é descartado; pai sem filho válido é
        self.assertEqual(M._candidatos(sessao, 'def'), (['MLB705'], 1))

    def test_r5_tokens_vencidos_recusados_ou_ilegiveis_nada_no_stdout(self):
        self.banco([(1, 'Perfumes e Perfumaria', 100.0, self.recente())])
        self.gravar_real(falta=10)
        ml = C.MLFalso()
        codigo, out, err = self.rodar_cat(['sondar', '--catalogo'], ml)   # vencido e sem Secret
        self.assertEqual((codigo, out), (2, ''), err)
        self.assertEqual(ml.op.chamadas, [])
        ml = C.MLFalso()
        ml.op = T.OpenerFalso(T.api_padrao(gets=ml.responder,
                                           token=lambda c: T.erro_http(400, {'error': 'invalid_grant'})))
        codigo, out, err = self.rodar_cat(['sondar', '--catalogo'], ml, secret=T.SECRET)
        self.assertEqual((codigo, out), (2, ''), err)
        self.assertEqual((len(ml.op.posts()), len(ml.op.gets())), (1, 0))
        self.assertIn('autorizar', err)
        with open(self.caminho, 'w', encoding='ascii') as f:
            f.write('{nao e json')
        os.chmod(self.caminho, 0o600)
        ml = C.MLFalso()
        codigo, out, err = self.rodar_cat(['sondar', '--catalogo'], ml, secret=T.SECRET)
        self.assertEqual((codigo, out), (2, ''), err)
        self.assertEqual(ml.op.chamadas, [])


# ---------- `sondar` sem --catalogo: igual ao do commit 34d80cf ----------
class TestSondarIgualAoDeAntes(Qa):
    @classmethod
    def setUpClass(cls):
        try:
            fonte = subprocess.run(['git', '-C', RAIZ, 'show', '34d80cf:ml_api.py'], capture_output=True,
                                   timeout=30, check=True).stdout
        except (OSError, subprocess.SubprocessError):
            raise unittest.SkipTest('sem git ou sem o commit 34d80cf')
        pasta = tempfile.mkdtemp(dir=T.TMP)
        caminho = os.path.join(pasta, 'ml_api_34d80cf.py')
        with open(caminho, 'wb') as f:
            f.write(fonte)
        spec = importlib.util.spec_from_file_location('ml_api_34d80cf', caminho)
        cls.ANTIGO = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.ANTIGO)
        assert cls.ANTIGO is not M and not hasattr(cls.ANTIGO, 'sondar_catalogo')

    def rodar_modulo(self, mod, argv, responder):
        op = T.OpenerFalso(responder)
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, {}), mock.patch.object(mod, 'OPENER', op), \
                mock.patch.object(mod, 'TOKENS', self.caminho), mock.patch.object(mod, 'DB', self.db), \
                mock.patch.object(mod, 'BACKOFF_BASE', 0.0), \
                mock.patch('getpass.getpass', side_effect=AssertionError('getpass inesperado')), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            os.environ.pop('ACHADINHOS_ML_SECRET', None)
            codigo = mod.main(argv)
        return codigo, out.getvalue(), err.getvalue(), [(c.metodo, c.url, c.auth) for c in op.chamadas]

    def comparar(self, responder, argv=('sondar',)):
        self.gravar_real()
        novo = self.rodar_modulo(M, list(argv), responder)
        antigo = self.rodar_modulo(self.ANTIGO, list(argv), responder)
        self.assertEqual(novo, antigo)
        return novo

    def test_tudo_200_com_ids_no_banco(self):
        self.banco([(n, 'Perfumes e Perfumaria', 100.0, self.recente()) for n in range(1, 5)])

        def gets(c):
            if c.caminho == '/products/search':
                return {'results': [{'id': 'MLB777', 'name': 'TITULO-MARCADOR'}], 'paging': {'total': 1}}
            return {'id': T.USER, 'results': [{'item_id': 'MLB1', 'price': 9}], 'title': 'TITULO-MARCADOR'}
        codigo, out, err, chamadas = self.comparar(T.api_padrao(gets=gets))
        self.assertEqual(codigo, 0)
        self.assertIn('ids do banco:', out)
        self.assertNotIn('Catálogo', out)

    def test_policy_agent_404_e_sem_banco(self):
        def gets(c):
            if c.caminho.startswith('/items'):
                return T.erro_http(*POLICY)
            if c.caminho.startswith('/reviews'):
                return T.erro_http(404, {'error': 'not_found'})
            return {'results': []}
        self.banco([(1, 'Perfumes e Perfumaria', 100.0, self.recente())])
        self.comparar(T.api_padrao(gets=gets))
        os.remove(self.db)
        codigo, out, err, _ = self.comparar(T.api_padrao(gets=gets))
        self.assertIn('F2/F5/F6: pulados', out)

    def test_limite_e_rede(self):
        self.banco([(1, 'Perfumes e Perfumaria', 100.0, self.recente())])
        codigo, out, err, _ = self.comparar(T.api_padrao(gets=lambda c: T.erro_http(429, {})))
        self.assertEqual(codigo, 3)
        codigo, out, err, _ = self.comparar(T.api_padrao(gets=lambda c: urllib.error.URLError('x')))
        self.assertEqual(codigo, 1)

    def test_conferir_tambem_igual(self):
        self.comparar(T.api_padrao(), argv=('conferir',))

    def test_argumentos_do_sondar_sem_flag(self):
        a = M.ler_argumentos(['sondar'])
        self.assertEqual((a.comando, a.catalogo, a.amostra, a.semente), ('sondar', False, None, None))
        b = self.ANTIGO.ler_argumentos(['sondar'])
        self.assertEqual(b.comando, 'sondar')


if __name__ == '__main__':
    unittest.main()
