#!/usr/bin/env python3
"""Testes de QA: validade padrão do preço na API v1 (GET /api/v1/ofertas sem preco_max_horas).

Uso:  python3 testes/test_api_ofertas_validade_qa.py -v

Decisão do dono (08/11/2026): quando o pedido não traz preco_max_horas, a API aplica por padrão
config.preco_validade_horas (a mesma trava do disparo: disparo.preco_recente e disparo.validade_horas,
padrão 24, faixa de 1 a 168, valor inválido vale 24). Hoje a API devolve tudo sem o filtro, e o
Achadinho Turbo (que nunca manda preco_max_horas) pode enviar oferta com preço velho aos grupos.

CA1: sem preco_max_horas, não sai oferta com preco_em além da validade, nem com preco_em nulo,
     malformado ou mais de 5 min no futuro; sem a chave na config, ou inválida, a validade é 24 h.
CA2: com preco_max_horas explícito (1 a 168) vale o pedido, mesmo maior que a validade da config;
     fora da faixa continua dando 400.
CA3: paginação (cursor da ordem atualizacao, deslocamento das outras) coerente com o filtro padrão.
CA4: /api/v1/categorias não muda.

Reaproveita o banco temporário e o relógio injetado do test_api_ofertas.py (T.Base) e o servidor de
teste do test_api_ofertas_servidor.py. Nada aqui toca o achadinhos.db real, o api_token.txt do projeto
ou a rede. Só biblioteca padrão.
"""
import json
import os
import shutil
import sys
import unittest
import urllib.parse
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_api_ofertas as T              # noqa: E402
import test_api_ofertas_servidor as TS2   # noqa: E402

A, D = T.A, T.D
AGORA = T.AGORA
hora = T.hora


def tearDownModule():
    shutil.rmtree(TS2.TMP, ignore_errors=True)   # o import do módulo do dev cria esse diretório


class ValidadeBase(T.Base):
    def antes(self, horas=0, segundos=0, agora=AGORA):
        return hora(agora - timedelta(hours=horas, seconds=segundos))

    def configurar(self, texto_json):
        """Grava config.preco_validade_horas como o PUT /api/config grava: o texto JSON do valor."""
        self.con.execute("INSERT OR REPLACE INTO config (chave, valor) VALUES ('preco_validade_horas', ?)",
                         (texto_json,))
        self.con.commit()

    def sem_config(self):
        self.con.execute("DELETE FROM config WHERE chave = 'preco_validade_horas'")
        self.con.commit()


# ---------------------------------------------------------------- CA1
class PadraoDaConfig(ValidadeBase):
    def test_ca1_sem_filtro_vale_a_validade_da_config_e_a_borda_entra(self):
        self.configurar('48')
        dentro = [self.gravar(preco_em=self.antes(h)) for h in (0, 1, 47)] + [self.gravar(preco_em=self.antes(48))]
        for h in (49, 100, 500):
            self.gravar(preco_em=self.antes(h))
        self.gravar(preco_em=self.antes(48, 1))
        r = self.ofertas('limite=200')
        self.assertEqual(sorted(o['id'] for o in r['ofertas']), sorted(dentro))
        self.assertEqual(r['total'], len(dentro))

    def test_ca1_a_config_muda_o_resultado_na_mesma_base(self):
        a = self.gravar(preco_em=self.antes(20))
        b = self.gravar(preco_em=self.antes(50))
        c = self.gravar(preco_em=self.antes(100))
        for valor, esperado in (('24', [a]), ('72', [a, b]), ('168', [a, b, c]), ('1', [])):
            with self.subTest(validade=valor):
                self.configurar(valor)
                self.assertEqual(sorted(self.ids('limite=200')), sorted(esperado))

    def test_ca1_sem_a_chave_na_config_a_validade_e_24h(self):
        self.sem_config()
        dentro = [self.gravar(preco_em=self.antes(h)) for h in (0, 23, 24)]
        for h in (24.5, 30, 48):
            self.gravar(preco_em=hora(AGORA - timedelta(hours=h)))
        self.gravar(preco_em=self.antes(24, 1))
        self.assertEqual(sorted(self.ids('limite=200')), sorted(dentro))

    def test_ca1_config_invalida_vale_24h_como_no_disparo(self):
        invalidos = ('"48"', '48.5', 'true', 'false', '0', '169', '-5', 'null', 'abc', '[48]', '{}', '""',
                     '1e2', '9' * 40)
        for texto in invalidos:
            with self.subTest(config=texto):
                self.configurar(texto)
                self.assertEqual(D.validade_horas(self.con), 24)   # o oráculo: a leitura do disparo
                dentro = self.gravar(preco_em=self.antes(20))
                fora = self.gravar(preco_em=self.antes(30))
                try:
                    self.assertEqual(self.ids('limite=200'), [dentro])
                finally:
                    self.con.execute('DELETE FROM items WHERE id IN (?, ?)', (dentro, fora))
                    self.con.commit()

    def test_ca1_limites_validos_da_config_1_e_168(self):
        a = self.gravar(preco_em=self.antes(0, 30))
        b = self.gravar(preco_em=self.antes(2))
        c = self.gravar(preco_em=self.antes(167))
        d = self.gravar(preco_em=self.antes(169))
        self.configurar('1')
        self.assertEqual(self.ids('limite=200'), [a])
        self.configurar('168')
        self.assertEqual(sorted(self.ids('limite=200')), sorted([a, b, c]))
        self.assertNotIn(d, self.ids('limite=200'))

    def test_ca1_preco_em_nulo_malformado_ou_no_futuro_nao_sai(self):
        self.configurar('48')
        bom = self.gravar(preco_em=self.antes(1))
        futuro_ok = self.gravar(preco_em=hora(AGORA + timedelta(minutes=5)))   # mesma folga do preco_recente
        ruins = {}
        for v in (None, '', '03/11/2026 12:24', '2026-11-03 14:00:00', '2026-11-03T14:00:00.5', '2026-11-03T14:00',
                  ' 2026-11-03T14:00:00', '2026-11-03T14:00:00\n', '2026-11-31T10:00:00', '2026-11-03T25:00:00',
                  '2026-11-02T24:00:00', '2026-11-03T14:60:00', '2026-11-03T14:00:60', 'z',
                  b'2026-11-03T14:00:00', 20261103,
                  hora(AGORA + timedelta(minutes=5, seconds=1)), hora(AGORA + timedelta(hours=1)),
                  '2999-12-31T23:59:59'):
            ruins[self.gravar(preco_em=v)] = v
        r = self.ofertas('limite=200')
        self.assertEqual(sorted(o['id'] for o in r['ofertas']), sorted([bom, futuro_ok]), ruins)
        self.assertEqual(r['total'], 2)

    def test_ca1_igual_ao_disparo_preco_recente_em_qualquer_ordem_e_horario(self):
        self.configurar('36')
        valores = [self.antes(h) for h in (0, 12, 35, 36, 37, 60)] + [None, 'x', hora(AGORA + timedelta(hours=2))]
        ids = {self.gravar(preco_em=v): v for v in valores}
        for agora in (AGORA, AGORA + timedelta(hours=10), AGORA + timedelta(microseconds=500000)):
            esperado = sorted(i for i, v in ids.items() if D.preco_recente(v, agora, 36))
            for ordem in A.ORDENS:
                with self.subTest(agora=agora, ordem=ordem):
                    r = self.ofertas(f'ordem={ordem}&limite=200', agora)
                    self.assertEqual(sorted(o['id'] for o in r['ofertas']), esperado)
                    self.assertEqual(r['total'], len(esperado))

    def test_ca1_o_padrao_combina_com_os_outros_filtros(self):
        self.configurar('48')
        ml_novo = self.gravar('ml', preco_em=self.antes(2), titulo='Perfume árabe novo', desconto='-30%',
                              preco_antigo='R$ 200,00')
        self.gravar('ml', preco_em=self.antes(60), titulo='Perfume árabe velho', desconto='-30%',
                    preco_antigo='R$ 200,00')
        am_novo = self.gravar('amazon', preco_em=self.antes(3), titulo='Perfume árabe amazon')
        self.gravar('amazon', preco_em=self.antes(90), titulo='Perfume árabe amazon antigo')
        self.assertEqual(self.ids('loja=ml'), [ml_novo])
        self.assertEqual(sorted(self.ids('q=arabe')), sorted([ml_novo, am_novo]))
        self.assertEqual(self.ids('desconto_min=20'), [ml_novo])
        self.assertEqual(self.ids('cat=Perfumes e Perfumaria&loja=amazon'), [am_novo])


# ---------------------------------------------------------------- CA2
class FiltroExplicito(ValidadeBase):
    def test_ca2_pedido_maior_que_a_config_vale_o_pedido(self):
        self.configurar('24')
        novo = self.gravar(preco_em=self.antes(2))
        meio = self.gravar(preco_em=self.antes(50))
        velho = self.gravar(preco_em=self.antes(100))
        mais = self.gravar(preco_em=self.antes(169))
        self.assertEqual(self.ids('limite=200'), [novo])   # sem o pedido: a validade da config
        self.assertEqual(sorted(self.ids('preco_max_horas=72&limite=200')), sorted([novo, meio]))
        self.assertEqual(sorted(self.ids('preco_max_horas=168&limite=200')), sorted([novo, meio, velho]))
        self.assertNotIn(mais, self.ids('preco_max_horas=168&limite=200'))

    def test_ca2_pedido_menor_que_a_config_tambem_vale_o_pedido(self):
        self.configurar('168')
        novo = self.gravar(preco_em=self.antes(0, 30))
        meio = self.gravar(preco_em=self.antes(5))
        self.assertEqual(sorted(self.ids('limite=200')), sorted([novo, meio]))
        self.assertEqual(self.ids('preco_max_horas=1'), [novo])

    def test_ca2_pedido_maior_vale_tambem_com_config_ausente_ou_invalida(self):
        a = self.gravar(preco_em=self.antes(30))
        for texto in (None, 'abc', '0'):
            with self.subTest(config=texto):
                self.sem_config() if texto is None else self.configurar(texto)
                self.assertEqual(self.ids('preco_max_horas=48&limite=200'), [a])
                self.assertEqual(self.ids('limite=200'), [])

    def test_ca2_fora_da_faixa_continua_400_mesmo_com_config_valida(self):
        self.configurar('48')
        self.gravar(preco_em=self.antes(1))
        for qs in ('preco_max_horas=0', 'preco_max_horas=169', 'preco_max_horas=-1', 'preco_max_horas=',
                   'preco_max_horas=24h', 'preco_max_horas=1.5'):
            with self.subTest(qs=qs):
                self.assertEqual(self.erro(qs), 'preco_max_horas deve ser um número inteiro de 1 a 168')


# ---------------------------------------------------------------- CA3
class PaginacaoComPadrao(ValidadeBase):
    def popular(self):
        """30 ofertas, metade velha e metade recente, atualizado_em misturado entre elas."""
        self.configurar('48')
        recentes, velhas = [], []
        for n in range(30):
            loja = D.LOJAS[n % 3]
            atualizado = hora(datetime(2026, 11, 2, 10, 0, 0) + timedelta(minutes=n % 7))
            if n % 2:
                recentes.append(self.gravar(loja, preco_em=self.antes(n % 40), atualizado_em=atualizado,
                                            vendas=f'+{n} vendidos'))
            else:
                velhas.append(self.gravar(loja, preco_em=self.antes(60 + n), atualizado_em=atualizado,
                                          vendas=f'+{n} vendidos'))
        return recentes, velhas

    def test_ca3_cursor_da_atualizacao_nunca_traz_oferta_velha_em_pagina_nenhuma(self):
        recentes, velhas = self.popular()
        linha = {r['id']: r['atualizado_em'] for r in self.con.execute('SELECT id, atualizado_em FROM items')}
        for limite in (1, 4, 7):
            with self.subTest(limite=limite):
                vistos, _, totais = self.percorrer(f'limite={limite}')
                self.assertEqual(vistos, sorted(recentes, key=lambda i: (linha[i], i)))
                self.assertEqual(totais, {len(recentes)})
                self.assertFalse(set(vistos) & set(velhas))

    def test_ca3_ordens_por_deslocamento_nao_trazem_oferta_velha_nem_repetem(self):
        recentes, velhas = self.popular()
        for ordem in A.ORDENS:
            if ordem == 'atualizacao':
                continue
            with self.subTest(ordem=ordem):
                vistos, _, totais = self.percorrer(f'ordem={ordem}&limite=4')
                self.assertEqual(sorted(vistos), sorted(recentes))
                self.assertEqual(len(vistos), len(set(vistos)))
                self.assertEqual(totais, {len(recentes)})

    def test_ca3_oferta_velha_no_meio_nao_faz_o_cursor_pular_recentes(self):
        self.configurar('48')
        a = self.gravar(preco_em=self.antes(1), atualizado_em='2026-11-02T10:00:00')
        self.gravar(preco_em=self.antes(70), atualizado_em='2026-11-02T10:00:01')
        b = self.gravar(preco_em=self.antes(2), atualizado_em='2026-11-02T10:00:02')
        r1 = self.ofertas('limite=1')
        self.assertEqual([o['id'] for o in r1['ofertas']], [a])
        r2 = self.ofertas('limite=1&cursor=' + urllib.parse.quote(r1['proximo']))
        self.assertEqual([o['id'] for o in r2['ofertas']], [b])

    def test_ca3_quem_guarda_o_ultimo_proximo_recebe_so_novidades_recentes(self):
        self.configurar('48')
        a = self.gravar(preco_em=self.antes(1), atualizado_em='2026-11-02T10:00:00')
        vistos, ultimo, _ = self.percorrer('limite=10')
        self.assertEqual(vistos, [a])
        self.gravar(preco_em=self.antes(80), atualizado_em='2026-11-02T11:00:00')
        novo = self.gravar(preco_em=self.antes(1), atualizado_em='2026-11-02T11:00:01')
        vistos, _, _ = self.percorrer('limite=10', cursor=ultimo)
        self.assertEqual(vistos, [novo])

    def test_ca3_pagina_depois_do_fim_dos_recentes_vem_vazia(self):
        self.configurar('48')
        self.gravar(preco_em=self.antes(70), atualizado_em='2026-11-02T10:00:00')
        r = self.ofertas('limite=5')
        self.assertEqual((r['ofertas'], r['total'], r['proximo']), ([], 0, None))
        for ordem in A.ORDENS:
            with self.subTest(ordem=ordem):
                r = self.ofertas(f'ordem={ordem}')
                self.assertEqual((r['ofertas'], r['total'], r['proximo']), ([], 0, None))


# ---------------------------------------------------------------- CA4
class CategoriasNaoMudam(ValidadeBase):
    def test_ca4_categorias_continuam_contando_tambem_as_ofertas_de_preco_velho(self):
        self.configurar('24')
        self.gravar(preco_em=self.antes(1))
        self.gravar(preco_em=self.antes(100))
        self.gravar('ml', preco_em=None, cat='Casa e Decoração', busca='luminária')
        self.gravar('shopee', preco_em='2020-01-01T00:00:00', cat='Casa e Decoração', busca='luminária')
        cats = self.cats()
        self.assertEqual(cats['total'], 4)
        por_nome = {c['nome']: c for c in cats['categorias']}
        self.assertEqual(por_nome['Perfumes e Perfumaria']['total'], 2)
        self.assertEqual(por_nome['Casa e Decoração']['total'], 2)
        self.assertEqual(por_nome['Casa e Decoração']['lojas'], {'amazon': 0, 'ml': 1, 'shopee': 1})

    def test_ca4_categorias_ignoram_a_config_e_seguem_recusando_preco_max_horas(self):
        self.gravar(preco_em=self.antes(1))
        self.gravar(preco_em=self.antes(100))
        resultados = []
        for texto in ('1', '24', '168', 'abc'):
            self.configurar(texto)
            resultados.append(self.cats())
        self.assertEqual(resultados, [resultados[0]] * 4)
        self.assertEqual(resultados[0]['total'], 2)
        with self.assertRaises(A.ErroApi) as ctx:
            A.rota(self.con, 'GET', '/api/v1/categorias', T.pares('preco_max_horas=24'), T.AFILIADO, AGORA)
        self.assertEqual(ctx.exception.codigo, 400)


# ---------------------------------------------------------------- pelo HTTP (servidor de verdade, relógio real)
class PeloHttp(TS2.ServidorApi):
    """O servidor.py chama a rota sem `agora`: vale o relógio da máquina, então os preco_em são
    relativos a datetime.now() com folga de 1 h em torno das bordas de 48 h."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import sqlite3
        agora = datetime.now()

        def antes(h):
            return (agora - timedelta(hours=h)).isoformat(timespec='seconds')

        con = sqlite3.connect(cls.db)
        con.execute("INSERT OR REPLACE INTO config (chave, valor) VALUES ('preco_validade_horas', '48')")
        cls.ids_extra = {}
        for n, h in enumerate((47, 49, 100), start=10):
            TS2.inserir(con, item_id=f'B0VALID{n:03d}', posicao=n, preco_em=antes(h),
                        url=f'https://www.amazon.com.br/dp/B0VALID{n:03d}?tag=desejodemen01-20')
            cls.ids_extra[h] = f'amazon:B0VALID{n:03d}'
        TS2.inserir(con, item_id='B0VALID020', posicao=20, preco_em=None,
                    url='https://www.amazon.com.br/dp/B0VALID020?tag=desejodemen01-20')
        con.commit()
        con.close()

    def chaves(self, query=''):
        st, _, j = self.v1('/api/v1/ofertas' + query, self.auth())
        self.assertEqual(st, 200, j)
        return {o['chave'] for o in j['ofertas']}, j

    def test_ca1_sem_filtro_o_http_aplica_a_validade_da_config(self):
        chaves, j = self.chaves()
        # B0TESTE001 foi gravado agora e B0VALID010 há 47 h; ML de 2020, 49 h, 100 h e preco_em nulo ficam fora
        self.assertEqual(chaves, {'amazon:B0TESTE001', self.ids_extra[47]})
        self.assertEqual(j['total'], 2)

    def test_ca2_com_preco_max_horas_o_http_usa_o_pedido(self):
        chaves, _ = self.chaves('?preco_max_horas=168')
        self.assertEqual(chaves, {'amazon:B0TESTE001', self.ids_extra[47], self.ids_extra[49], self.ids_extra[100]})
        chaves, _ = self.chaves('?preco_max_horas=1')
        self.assertEqual(chaves, {'amazon:B0TESTE001'})

    def test_ca2_http_fora_da_faixa_da_400(self):
        for qs in ('preco_max_horas=0', 'preco_max_horas=169'):
            st, _, j = self.v1('/api/v1/ofertas?' + qs, self.auth())
            self.assertEqual(st, 400, qs)
            self.assertIn('preco_max_horas', j['error'])

    def test_ca4_http_categorias_contam_todas_as_ofertas(self):
        st, _, j = self.v1('/api/v1/categorias', self.auth())
        self.assertEqual(st, 200)
        # B0TESTE001, ML 2020, 3 extras de preço datado e 1 de preço nulo: todas com preço legível e link
        self.assertEqual(j['total'], 6)
        json.dumps(j)


if __name__ == '__main__':
    unittest.main()
