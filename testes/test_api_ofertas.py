#!/usr/bin/env python3
"""Testes do api_ofertas.py (docs/produto/planos/api-achadinho-turbo.md, etapa 1).

Uso:  python3 testes/test_api_ofertas.py -v

Cada teste usa um banco novo num diretório temporário, com o esquema do servidor.criar_banco.
Nenhum teste toca o achadinhos.db real, o servidor em 8765 ou a rede: o relógio é injetado e
os proxies apontam para uma porta morta. Só biblioteca padrão.
"""
import ast
import atexit
import json
import os
import random
import shutil
import sqlite3
import sys
import tempfile
import unittest
import urllib.parse
from datetime import datetime, timedelta
from unittest import mock

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_REAL = os.path.realpath(os.path.join(RAIZ, 'achadinhos.db'))
TMP = tempfile.mkdtemp(prefix='achadinhos-api-')
atexit.register(shutil.rmtree, TMP, ignore_errors=True)

# Antes do import: o servidor lê ACHADINHOS_DB ao carregar, e qualquer saída para a rede bate num proxy morto.
os.environ['ACHADINHOS_DB'] = os.path.join(TMP, 'import.db')
for _v in ('http_proxy', 'https_proxy', 'ftp_proxy'):
    os.environ[_v] = 'http://127.0.0.1:9'
os.environ['no_proxy'] = ''
sys.path.insert(0, RAIZ)
import servidor as S     # noqa: E402
import disparo as D      # noqa: E402
import api_ofertas as A  # noqa: E402
import genero as G       # noqa: E402

AFILIADO = S.eh_link_afiliado
AGORA = datetime(2026, 11, 3, 15, 0, 0)
ANTIGO = '2026-11-03T12:24:23'
FOTO = {'amazon': 'https://m.media-amazon.com/images/I/71teste.jpg',
        'ml': 'https://http2.mlstatic.com/D_teste.jpg',
        'shopee': 'https://down-br.img.susercontent.com/file/teste'}
CAMPOS_OFERTA = ['id', 'chave', 'loja', 'item_id', 'categoria', 'busca', 'titulo', 'link', 'imagem', 'preco',
                 'preco_antigo', 'desconto_pct', 'vendas', 'avaliacao', 'num_avaliacoes', 'frete_gratis',
                 'cupom', 'criado_em', 'atualizado_em', 'genero', 'preco_em']
SEGREDO = 'XYZVALORDOCLIENTE'   # nunca pode voltar na mensagem de erro


def abrir(caminho, so_leitura=False):
    """Igual ao conectar() do servidor, mas com caminho explícito e guarda contra o banco real."""
    if os.path.realpath(caminho) == DB_REAL:
        raise RuntimeError('o teste tentou usar o banco real')
    if so_leitura:
        con = sqlite3.connect(f'file:{caminho}?mode=ro', uri=True, timeout=30)
    else:
        con = sqlite3.connect(caminho, timeout=30)
        con.execute('PRAGMA journal_mode=WAL')
    con.row_factory = sqlite3.Row
    return con


def hora(dt):
    return dt.isoformat(timespec='seconds')


def pares(qs):
    return urllib.parse.parse_qsl(qs, keep_blank_values=True)


class Base(unittest.TestCase):
    """Banco temporário com o esquema do servidor.py (inclui a migração do disparo)."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(dir=TMP)
        self.caminho = os.path.join(self.dir, 'teste.db')
        with mock.patch.object(S, 'DB', self.caminho):
            S.criar_banco()
        self.con = abrir(self.caminho)
        self.addCleanup(self.con.close)
        self.seq = 0

    def gravar(self, loja='amazon', **campos):
        """Grava um item válido (CA2) da loja; `campos` troca qualquer coluna. Devolve o id."""
        self.seq += 1
        n = self.seq
        item_id, url = {'amazon': (f'B0TESTE{n:04d}', f'https://www.amazon.com.br/dp/B0TESTE{n:04d}?tag=desejodemen01-20'),
                        'ml': (f'MLB{n:08d}', f'https://meli.la/T{n}x'),
                        'shopee': (f'{n}', f'https://s.shopee.com.br/T{n}x')}.get(loja, (f'X{n}', 'https://exemplo.invalido/'))
        linha = {'loja': loja, 'item_id': item_id, 'cat': 'Perfumes e Perfumaria', 'busca': 'perfume importado',
                 'url': url, 'titulo': f'Perfume número {n}', 'preco': 'R$ 100,00', 'preco_antigo': '',
                 'desconto': '', 'avaliacao': '', 'num_avaliacoes': '', 'vendas': '', 'frete': '', 'cupom': '',
                 'imagem': FOTO.get(loja, ''), 'tem_dados': 1, 'posicao': n,
                 'criado_em': ANTIGO, 'atualizado_em': ANTIGO}
        linha.update(campos)
        cols = list(linha)
        cur = self.con.execute(f'INSERT INTO items ({",".join(cols)}) VALUES ({",".join("?" * len(cols))})',
                               [linha[c] for c in cols])
        self.con.commit()
        return cur.lastrowid

    def ofertas(self, qs='', agora=AGORA, con=None):
        return A.rota(con or self.con, 'GET', '/api/v1/ofertas', pares(qs), AFILIADO, agora)

    def ids(self, qs='', agora=AGORA):
        return [o['id'] for o in self.ofertas(qs, agora)['ofertas']]

    def cats(self, con=None):
        return A.rota(con or self.con, 'GET', '/api/v1/categorias', [], AFILIADO)

    def erro(self, qs, codigo=400):
        with self.assertRaises(A.ErroApi) as ctx:
            self.ofertas(qs)
        self.assertEqual(ctx.exception.codigo, codigo, qs)
        self.assertTrue(ctx.exception.msg.strip(), qs)
        self.assertNotIn(SEGREDO, ctx.exception.msg, qs)
        return ctx.exception.msg

    def percorrer(self, qs, agora=AGORA, cursor=None, maximo=1000):
        """Segue `proximo` até null. Devolve (ids na ordem, último proximo não nulo, totais vistos)."""
        vistos, ultimo, totais = [], cursor, set()
        for _ in range(maximo):
            extra = '&cursor=' + urllib.parse.quote(cursor) if cursor else ''
            r = self.ofertas(qs + extra, agora)
            vistos += [o['id'] for o in r['ofertas']]
            totais.add(r['total'])
            if r['proximo'] is None:
                return vistos, ultimo, totais
            ultimo = cursor = r['proximo']
        self.fail('proximo nunca chegou a null')


# ---------------------------------------------------------------- CA1: formato
class Formato(Base):
    def test_ca1_resposta_tem_versao_ofertas_proximo_e_total(self):
        self.gravar()
        r = self.ofertas()
        self.assertEqual(list(r), ['versao', 'ofertas', 'proximo', 'total'])
        self.assertEqual(r['versao'], 1)
        self.assertEqual(r['total'], 1)
        self.assertEqual(len(r['ofertas']), 1)

    def test_ca1_oferta_igual_ao_exemplo_do_plano(self):
        i = self.gravar(item_id='B0G5NZ82TJ', url='https://www.amazon.com.br/dp/B0G5NZ82TJ?tag=desejodemen01-20',
                        titulo='Perfume Importado Masculino 100ml', preco='R$ 523,99', preco_antigo='R$ 929,00',
                        desconto='-44%', vendas='Mais de 50 compras no mês passado', avaliacao='4,5 de 5 estrelas',
                        num_avaliacoes='7.000', frete='', cupom='', preco_em=ANTIGO)
        o = self.ofertas()['ofertas'][0]
        self.assertEqual(list(o), CAMPOS_OFERTA)
        self.assertEqual(o, {
            'id': i, 'chave': 'amazon:B0G5NZ82TJ', 'loja': 'amazon', 'item_id': 'B0G5NZ82TJ',
            'categoria': 'Perfumes e Perfumaria', 'busca': 'perfume importado',
            'titulo': 'Perfume Importado Masculino 100ml',
            'link': 'https://www.amazon.com.br/dp/B0G5NZ82TJ?tag=desejodemen01-20',
            'imagem': FOTO['amazon'], 'preco': 523.99, 'preco_antigo': 929.0, 'desconto_pct': 44,
            'vendas': 50, 'avaliacao': 4.5, 'num_avaliacoes': 7000, 'frete_gratis': False, 'cupom': '',
            'criado_em': ANTIGO, 'atualizado_em': ANTIGO, 'genero': 'masculino', 'preco_em': ANTIGO})

    def test_ca1_tipos_de_cada_campo(self):
        self.gravar()                                   # quase tudo vazio
        self.gravar('ml', preco='R$ 1.899', preco_antigo='R$ 2.000', desconto='5% OFF', vendas='+1 mil vendidos',
                    avaliacao='4.8', num_avaliacoes='(135)', frete='Frete grátis', cupom='Cupom 10% OFF')
        self.gravar('shopee', imagem='')
        tipos = {'id': (int,), 'chave': (str,), 'loja': (str,), 'item_id': (str,), 'categoria': (str,),
                 'busca': (str,), 'titulo': (str,), 'link': (str,), 'imagem': (str, type(None)),
                 'preco': (float,), 'preco_antigo': (float, type(None)), 'desconto_pct': (int,), 'vendas': (int,),
                 'avaliacao': (float, type(None)), 'num_avaliacoes': (int,), 'frete_gratis': (bool,),
                 'cupom': (str,), 'criado_em': (str,), 'atualizado_em': (str,), 'genero': (str,),
                 'preco_em': (str, type(None))}
        ofertas = self.ofertas()['ofertas']
        self.assertEqual(len(ofertas), 3)
        for o in ofertas:
            self.assertEqual(list(o), CAMPOS_OFERTA)
            for campo, aceitos in tipos.items():
                self.assertIn(type(o[campo]), aceitos, campo)
            if o['loja'] == 'ml':
                self.assertEqual((o['preco'], o['preco_antigo'], o['desconto_pct'], o['vendas'], o['avaliacao'],
                                  o['num_avaliacoes'], o['frete_gratis'], o['cupom']),
                                 (1899.0, 2000.0, 5, 1000, 4.8, 135, True, 'Cupom 10% OFF'))
            if o['loja'] == 'shopee':
                self.assertIsNone(o['imagem'])

    def test_ca1_preco_antigo_null_quando_vazio_ou_nao_maior(self):
        a = self.gravar(preco_antigo='')
        b = self.gravar(preco='R$ 100,00', preco_antigo='R$ 100,00')
        c = self.gravar(preco='R$ 100,00', preco_antigo='R$ 90,00')
        d = self.gravar(preco='R$ 100,00', preco_antigo='R$ 125,00')
        por_id = {o['id']: o for o in self.ofertas()['ofertas']}
        self.assertIsNone(por_id[a]['preco_antigo'])
        self.assertIsNone(por_id[b]['preco_antigo'])
        self.assertIsNone(por_id[c]['preco_antigo'])
        self.assertEqual(por_id[d]['preco_antigo'], 125.0)

    def test_ca1_desconto_pct_vem_do_texto_ou_do_preco_antigo(self):
        texto = self.gravar(desconto='-10%', preco='R$ 75,00', preco_antigo='R$ 100,00')
        calculado = self.gravar(desconto='', preco='R$ 75,00', preco_antigo='R$ 100,00')
        sem_nada = self.gravar(desconto='', preco_antigo='')
        antigo_menor = self.gravar(desconto='', preco='R$ 100,00', preco_antigo='R$ 50,00')
        por_id = {o['id']: o for o in self.ofertas()['ofertas']}
        self.assertEqual(por_id[texto]['desconto_pct'], 10)        # pct(desconto) vence
        self.assertEqual(por_id[calculado]['desconto_pct'], 25)    # round((1 - 75/100) * 100)
        self.assertEqual(por_id[sem_nada]['desconto_pct'], 0)
        self.assertEqual(por_id[antigo_menor]['desconto_pct'], 0)

    def test_ca1_frete_gratis_sem_caixa_nem_acento(self):
        casos = {'Frete grátis': True, 'Frete GRÁTIS': True, 'FRETE GRATIS': True, 'frete gratis no app': True,
                 '': False, 'Frete R$ 10,00': False, 'Chega amanhã': False}
        ids = {self.gravar(frete=f): esperado for f, esperado in casos.items()}
        for o in self.ofertas()['ofertas']:
            self.assertIs(o['frete_gratis'], ids[o['id']], o['id'])

    def test_ca1_avaliacao_null_quando_vazia_ou_zero(self):
        vazia = self.gravar(avaliacao='')
        zero = self.gravar(avaliacao='0 de 5')
        boa = self.gravar(avaliacao='4,7 de 5 estrelas')
        por_id = {o['id']: o for o in self.ofertas()['ofertas']}
        self.assertIsNone(por_id[vazia]['avaliacao'])
        self.assertIsNone(por_id[zero]['avaliacao'])
        self.assertEqual(por_id[boa]['avaliacao'], 4.7)

    def test_ca1_numero_gigante_nao_vira_infinity_no_json(self):
        gigante = '9' * 400                     # float('9'*400) == inf: JSON inválido
        fora = self.gravar(preco=gigante)
        dentro = self.gravar(preco_antigo=gigante, avaliacao=gigante)
        r = self.ofertas()
        json.dumps(r, allow_nan=False)
        self.assertEqual([o['id'] for o in r['ofertas']], [dentro])
        self.assertNotIn(fora, [o['id'] for o in r['ofertas']])
        o = r['ofertas'][0]
        self.assertIsNone(o['preco_antigo'])
        self.assertIsNone(o['avaliacao'])

    def test_r1_linha_que_quebra_a_conversao_fica_fora_e_as_rotas_seguem(self):
        # R1: o coletar_amazon.py não aplica o teto de 200 caracteres. Sem a captura, uma linha só
        # levantava OverflowError (float inf * 1000) ou ValueError (int com mais de ~4.300 dígitos)
        # e derrubava toda a v1, porque as rotas varrem a tabela.
        bons = [self.gravar(vendas='Mais de 1 mil compras', desconto='-10%'), self.gravar('ml'), self.gravar('shopee')]
        ruins = [self.gravar(vendas='9' * 400 + ' mil'),
                 self.gravar(vendas='9' * 5000),
                 self.gravar(num_avaliacoes='9' * 5000),
                 self.gravar(desconto='-' + '9' * 5000 + '%'),
                 self.gravar('ml', num_avaliacoes='(' + '9' * 400 + ' mil)')]
        for ordem in A.ORDENS:
            with self.subTest(ordem=ordem):
                r = self.ofertas(f'ordem={ordem}&limite=200')
                json.dumps(r, allow_nan=False)
                self.assertEqual(sorted(o['id'] for o in r['ofertas']), bons)
                self.assertEqual(r['total'], 3)
        self.assertEqual(self.ofertas('desconto_min=5&q=perfume')['total'], 1)
        self.assertEqual(self.cats()['total'], 3)
        for i in ruins:
            linha = self.con.execute('SELECT * FROM items WHERE id=?', (i,)).fetchone()
            self.assertIsNone(A.oferta(linha, AFILIADO), i)


# ---------------------------------------------------------------- CA2: só o que pode sair
class SoAfiliado(Base):
    def test_ca2_condicoes_basicas(self):
        bom = self.gravar()
        fora = [self.gravar(tem_dados=0), self.gravar(titulo=''), self.gravar(titulo='   '),
                self.gravar(preco=''), self.gravar(preco='R$ 0,00'), self.gravar(preco='consulte')]
        r = self.ofertas()
        self.assertEqual([o['id'] for o in r['ofertas']], [bom])
        self.assertEqual(r['total'], 1)
        self.assertTrue(set(fora).isdisjoint(o['id'] for o in r['ofertas']))

    def test_ca2_titulo_tipo_iphone_fica_fora(self):
        bom = self.gravar()
        self.gravar(titulo='Apple i.Phone 15 128 GB')
        self.gravar(titulo='Smart TV 55UN85CBPSA.BWZ 4K')
        self.gravar(titulo='Perfume em golpe.com barato')
        self.gravar(titulo='Veja https://exemplo.com.br/x')
        self.gravar(cupom='Use em www.golpe.com')
        self.gravar('ml', cupom='Cupom em https://meli.la/outro')
        self.assertEqual(self.ids(), [bom])
        self.assertEqual(self.cats()['total'], 1)

    def test_ca2_ml_com_url_comum_fica_fora(self):
        bom = self.gravar('ml')
        self.gravar('ml', url='https://produto.mercadolivre.com.br/MLB-123456789-perfume-_JM')
        self.gravar('ml', url='https://www.mercadolivre.com.br/perfume/p/MLB123')
        self.gravar('ml', url='http://meli.la/abc')
        self.gravar('ml', url='https://www.amazon.com.br/dp/B0X?tag=desejodemen01-20')   # afiliado de outra loja
        self.assertEqual(self.ids(), [bom])

    def test_ca2_amazon_com_tag_de_terceiro_fica_fora(self):
        bom = self.gravar()
        self.gravar(url='https://www.amazon.com.br/dp/B0X?tag=outrapessoa-20')
        self.gravar(url='https://www.amazon.com.br/dp/B0X')
        self.gravar(url='https://www.amazon.com.br/dp/B0X?tag=desejodemen01-20&tag=outrapessoa-20')
        self.gravar(url='https://amzn.to/3abc')
        self.gravar(url='https://meli.la/abc')                                            # afiliado do ML
        self.assertEqual(self.ids(), [bom])

    def test_ca2_shopee_so_com_link_curto_de_afiliado(self):
        bom = self.gravar('shopee')
        self.gravar('shopee', url='https://shopee.com.br/produto-i.1.2')
        self.gravar('shopee', url='https://meli.la/abc')
        self.gravar('outraloja')
        self.assertEqual(self.ids(), [bom])

    def test_ca2_imagem_fora_do_cdn_da_loja_vira_null(self):
        casos = {'https://m.media-amazon.com/images/I/a.jpg': 'https://m.media-amazon.com/images/I/a.jpg',
                 'https://golpe.com/a.jpg': None,
                 'http://m.media-amazon.com/images/I/a.jpg': None,
                 'https://http2.mlstatic.com/D_a.jpg': None,          # CDN de outra loja
                 'https://user@m.media-amazon.com/a.jpg': None,
                 'https://m.media-amazon.com:8443/a.jpg': None,
                 '': None}
        ids = {self.gravar(imagem=img): esperado for img, esperado in casos.items()}
        ofertas = self.ofertas()['ofertas']
        self.assertEqual(len(ofertas), len(casos))
        for o in ofertas:
            self.assertEqual(o['imagem'], ids[o['id']])

    def test_ca2_oferta_direto_na_linha(self):
        i = self.gravar()
        linha = dict(self.con.execute('SELECT * FROM items WHERE id=?', (i,)).fetchone())
        self.assertEqual(A.oferta(linha, AFILIADO)['id'], i)
        self.assertIsNone(A.oferta({**linha, 'tem_dados': 0}, AFILIADO))
        self.assertIsNone(A.oferta({**linha, 'tem_dados': None}, AFILIADO))
        self.assertIsNone(A.oferta(linha, lambda u: False))     # o eh_afiliado do chamador é consultado
        self.assertIsNone(A.oferta({**linha, 'titulo': 'i.Phone'}, AFILIADO))

    def test_ca2_loja_fora_de_lojas_nunca_sai(self):
        # mesmo que um dia o disparo aceite o host de outra loja, a oferta e a contagem não saem
        self.gravar()
        self.gravar('magalu', url='https://www.magazineluiza.com.br/p/1')
        with mock.patch.dict(D.HOSTS_LINK_LOJA, {'magalu': ('www.magazineluiza.com.br',)}):
            self.assertEqual(self.ofertas()['total'], 1)
            self.assertEqual(self.cats()['categorias'][0]['lojas'], {'amazon': 1, 'ml': 0, 'shopee': 0})
            linha = self.con.execute("SELECT * FROM items WHERE loja='magalu'").fetchone()
            self.assertIsNone(A.oferta(linha, lambda u: True))

    def test_ca2_cat_busca_e_item_id_sem_link(self):
        bom = self.gravar()
        mesmo_link = self.gravar('ml', item_id='https://meli.la/proprio', url='https://meli.la/proprio')
        self.gravar(cat='Ofertas em golpe.com')
        self.gravar(busca='veja www.golpe.com')
        self.gravar(item_id='https://golpe.com/B0X')
        self.assertEqual(sorted(self.ids()), [bom, mesmo_link])

    def test_ca2_tipos_estranhos_no_banco_ficam_fora_sem_quebrar(self):
        bom = self.gravar()
        # na coluna TEXT o sqlite converte número em texto; só BLOB continua com outro tipo
        numero = self.gravar(titulo=12345, preco=100)
        self.gravar(titulo=b'Perfume')
        self.gravar(preco=b'100')
        self.gravar(cupom=b'https://golpe.com')
        self.gravar(atualizado_em='03/11/2026 12:24')           # fora do formato do servidor
        self.gravar(criado_em=None)
        self.assertEqual(self.ids(), [bom, numero])
        self.assertEqual(self.ofertas()['ofertas'][1]['titulo'], '12345')
        self.assertEqual(self.cats()['total'], 2)

    def test_ca2_nenhum_outro_url_no_corpo(self):
        for loja in ('amazon', 'ml', 'shopee'):
            for _ in range(3):
                self.gravar(loja, cupom='Cupom 5% OFF', frete='Frete grátis', vendas='+100 vendidos')
        self.gravar(titulo='Apple i.Phone 15')
        self.gravar(imagem='https://golpe.com/x.jpg')
        r = self.ofertas()
        json.dumps(r, allow_nan=False)
        self.assertEqual(len(r['ofertas']), 10)
        for o in r['ofertas']:
            self.assertTrue(D.link_da_loja_ok(o['loja'], o['link'], AFILIADO))
            self.assertTrue(o['imagem'] is None or D.imagem_permitida(o['imagem'], o['loja']))
            for campo, valor in o.items():
                if campo not in ('link', 'imagem') and isinstance(valor, str):
                    self.assertEqual(D.urls_da_mensagem(valor), [], campo)


# ---------------------------------------------------------------- foto grande (o Turbo baixa o campo `imagem` e manda ao grupo)
class FotoGrande(Base):
    """CA2: `imagem` da oferta é disparo.foto_grande(imagem gravada, loja). CA5: o banco guarda a miniatura."""
    AMZ = 'https://m.media-amazon.com/images/I/'
    ML = 'https://http2.mlstatic.com/'
    SHP = 'https://down-br.img.susercontent.com/file/'
    CASOS = {   # loja: (gravada, esperada na API)
        'amazon': (AMZ + '41p2HTchUrL._AC_UL320_.jpg', AMZ + '41p2HTchUrL._AC_SL1000_.jpg'),
        'ml': (ML + 'D_Q_NP_2X_840992-MLB95728482450_102025-E.webp', ML + 'D_Q_NP_2X_840992-MLB95728482450_102025-F.jpg'),
        'shopee': (SHP + 'br-11134207-7r98o-m1abc_tn', SHP + 'br-11134207-7r98o-m1abc'),
    }

    def imagem_por_loja(self):
        return {o['loja']: o['imagem'] for o in self.ofertas()['ofertas']}

    def test_imagem_sai_em_tamanho_grande_nas_tres_lojas(self):
        for loja, (gravada, _) in self.CASOS.items():
            self.gravar(loja, imagem=gravada)
        self.assertEqual(self.imagem_por_loja(), {l: g for l, (_, g) in self.CASOS.items()})

    def test_imagem_e_a_mesma_do_foto_grande_do_disparo(self):
        self.assertTrue(hasattr(D, 'foto_grande'), 'disparo.foto_grande não existe')
        for loja, (gravada, _) in self.CASOS.items():
            self.gravar(loja, imagem=gravada)
        for o in self.ofertas()['ofertas']:
            self.assertEqual(o['imagem'], D.foto_grande(self.CASOS[o['loja']][0], o['loja']))

    def test_imagem_ja_grande_ou_sem_miniatura_nao_muda(self):
        casos = {'amazon': self.AMZ + 'abc.jpg', 'ml': self.ML + 'D_NQ_NP_840992-MLB1_102025-F.jpg',
                 'shopee': self.SHP + 'br-11134207-7r98o-m1abc'}
        for loja, foto in casos.items():
            self.gravar(loja, imagem=foto)
        self.assertEqual(self.imagem_por_loja(), casos)

    def test_foto_fora_do_cdn_da_loja_continua_null_mesmo_parecendo_miniatura(self):
        self.gravar('amazon', imagem='https://golpe.com/images/I/a._AC_UL320_.jpg')
        self.gravar('amazon', imagem='http://m.media-amazon.com/images/I/a._AC_UL320_.jpg')
        self.gravar('amazon', imagem=self.ML + 'D_a-E.webp')      # CDN de outra loja
        self.gravar('ml', imagem=self.AMZ + 'a._AC_UL320_.jpg')   # CDN de outra loja
        self.gravar('shopee', imagem='https://evil.example/file/a_tn')
        self.gravar('shopee', imagem='')
        ofertas = self.ofertas()['ofertas']
        self.assertEqual(len(ofertas), 6)
        self.assertEqual([o['imagem'] for o in ofertas], [None] * 6)

    def test_url_com_query_ou_fragmento_nao_e_mexida(self):
        mini = self.AMZ + 'a._AC_UL320_.jpg'
        self.gravar(imagem=mini + '?x=1')
        self.gravar(imagem=mini + '#f')
        self.assertEqual([o['imagem'] for o in self.ofertas()['ofertas']], [mini + '?x=1', mini + '#f'])

    def test_a_oferta_direto_na_linha_traz_a_foto_grande(self):
        gravada, grande = self.CASOS['ml']
        i = self.gravar('ml', imagem=gravada)
        linha = dict(self.con.execute('SELECT * FROM items WHERE id=?', (i,)).fetchone())
        self.assertEqual(A.oferta(linha, AFILIADO)['imagem'], grande)

    def test_o_banco_continua_com_a_miniatura(self):
        for loja, (gravada, _) in self.CASOS.items():
            self.gravar(loja, imagem=gravada)
        antes = [tuple(r) for r in self.con.execute('SELECT * FROM items ORDER BY id')]
        self.ofertas()
        self.ofertas('ordem=desconto&limite=2')
        self.cats()
        self.assertEqual([tuple(r) for r in self.con.execute('SELECT * FROM items ORDER BY id')], antes)
        self.assertEqual({r['loja']: r['imagem'] for r in self.con.execute('SELECT loja, imagem FROM items')},
                         {l: g for l, (g, _) in self.CASOS.items()})

    def test_imagem_da_oferta_sempre_passa_em_imagem_permitida(self):
        for loja, (gravada, _) in self.CASOS.items():
            self.gravar(loja, imagem=gravada)
        for o in self.ofertas()['ofertas']:
            self.assertTrue(D.imagem_permitida(o['imagem'], o['loja']))


# ---------------------------------------------------------------- CA3: filtros e validação
class Filtros(Base):
    def test_ca3_cat_e_loja_repetiveis(self):
        a = self.gravar(cat='Casa e Decoração')
        b = self.gravar('ml', cat='Eletrodomésticos')
        c = self.gravar('shopee')
        self.assertEqual(sorted(self.ids('cat=Casa+e+Decora%C3%A7%C3%A3o&cat=Eletrodom%C3%A9sticos')), [a, b])
        self.assertEqual(sorted(self.ids('loja=ml&loja=shopee')), [b, c])
        self.assertEqual(self.ids('cat=Eletrodom%C3%A9sticos&loja=amazon'), [])
        self.assertEqual(self.ofertas('cat=N%C3%A3o+existe')['total'], 0)

    def test_ca3_q_sem_caixa_nem_acento_e_qualquer_termo(self):
        cafe = self.gravar(titulo='Café Pilão Tradicional')
        perfume = self.gravar(titulo='PERFUME Malbec')
        self.gravar(titulo='Fritadeira elétrica')
        self.assertEqual(self.ids('q=cafe'), [cafe])
        self.assertEqual(self.ids('q=CAF%C3%89'), [cafe])
        self.assertEqual(sorted(self.ids('q=perfume,+caf%C3%A9')), [cafe, perfume])
        self.assertEqual(self.ofertas('q=perfume,cafe')['total'], 2)
        self.assertEqual(self.ids('q=geladeira'), [])

    def test_ca3_desconto_min_usa_o_desconto_pct_da_oferta(self):
        self.gravar(desconto='-10%')
        trinta = self.gravar(desconto='-30%')
        calculado = self.gravar(desconto='', preco='R$ 60,00', preco_antigo='R$ 100,00')   # 40%
        self.assertEqual(sorted(self.ids('desconto_min=30')), [trinta, calculado])
        self.assertEqual(self.ids('desconto_min=41'), [])
        self.assertEqual(len(self.ids('desconto_min=0')), 3)
        self.assertEqual(self.ofertas('desconto_min=99')['total'], 0)

    def test_ca3_limite_padrao_50_e_maximo_200(self):
        for _ in range(210):
            self.gravar()
        r = self.ofertas()
        self.assertEqual((len(r['ofertas']), r['total']), (50, 210))
        self.assertEqual(len(self.ids('limite=200')), 200)
        self.assertEqual(len(self.ids('limite=1')), 1)
        self.erro('limite=201')

    def test_ca3_valores_invalidos_dao_400(self):
        invalidos = ['limite=0', 'limite=-1', 'limite=1.5', 'limite=', 'limite=+5', 'limite=%205', 'limite=5%20',
                     'limite=%D9%A3', 'limite=1e2', 'limite=0x10', 'limite=9999',
                     'desconto_min=100', 'desconto_min=-1', 'desconto_min=', 'desconto_min=dez',
                     'cat=', 'cat=' + 'a' * 201, 'cat=a&cat=a', '&'.join(f'cat=c{i}' for i in range(21)),
                     'loja=', 'loja=ML', 'loja=magalu', 'loja=ml&loja=ml', 'loja=' + SEGREDO,
                     'q=', 'q=%20', 'q=a,,b', 'q=a,', 'q=' + 'a' * 201, 'q=' + ','.join('t' * 11),
                     'ordem=', 'ordem=preco', 'ordem=ATUALIZACAO', 'ordem=' + SEGREDO]
        for qs in invalidos:
            with self.subTest(qs=qs[:60]):
                self.erro(qs)

    def test_ca3_limites_aceitos(self):
        self.gravar()
        for qs in ('cat=' + 'a' * 200, '&'.join(f'cat=c{i}' for i in range(20)), 'q=' + 'a' * 200,
                   'q=' + ','.join('t' * 10), 'desconto_min=0', 'desconto_min=99', 'limite=050'):
            with self.subTest(qs=qs[:60]):
                self.assertEqual(self.ofertas(qs)['versao'], 1)

    def test_ca3_parametro_desconhecido_da_400_sem_ecoar(self):
        for qs in ('foo=1', 'token=' + SEGREDO, SEGREDO + '=1', 'Cat=x', 'cat[]=x', 'categoria=x', 'pagina=2'):
            with self.subTest(qs=qs):
                self.assertIn('desconhecido', self.erro(qs))

    def test_ca3_repetido_onde_nao_pode_da_400(self):
        for nome, valor in (('q', 'a'), ('desconto_min', '1'), ('ordem', 'desconto'), ('limite', '5'),
                            ('cursor', '5')):
            with self.subTest(nome=nome):
                msg = self.erro(f'ordem=desconto&{nome}={valor}&{nome}={valor}' if nome != 'ordem'
                                else f'{nome}={valor}&{nome}={valor}')
                self.assertIn(nome, msg)

    def test_ca3_pares_demais_ou_malformados_dao_400(self):
        # teto de custo: nem chega a conferir repetição
        self.assertIn('demais', self.erro('&'.join(['loja=ml'] * 100)))
        self.assertIn('demais', self.erro('&'.join(f'cat=c{i}' for i in range(A.MAX_PARES + 1))))
        for ruim in ([('cat',)], [('cat', 1)], [['cat', 'x']], [(b'cat', 'x')]):
            with self.subTest(ruim=ruim), self.assertRaises(A.ErroApi) as ctx:
                A.rota(self.con, 'GET', '/api/v1/ofertas', ruim, AFILIADO, AGORA)
            self.assertEqual(ctx.exception.codigo, 400)

    def test_ca3_filtros_devolve_valores_normalizados(self):
        f = A.filtros(pares('cat=A&cat=B&loja=ml&q=Caf%C3%A9,+%C3%93leo&desconto_min=07&ordem=cupom&limite=10&cursor=20'))
        self.assertEqual(f, {'cats': ['A', 'B'], 'lojas': ['ml'], 'generos': [], 'termos': ['cafe', 'oleo'], 'desconto_min': 7,
                             'ordem': 'cupom', 'limite': 10, 'cursor': 20, 'preco_max_horas': None})
        self.assertEqual(A.filtros([]), {'cats': [], 'lojas': [], 'generos': [], 'termos': [], 'desconto_min': 0,
                                         'ordem': 'atualizacao', 'limite': 50, 'cursor': None, 'preco_max_horas': None})
        self.assertEqual(A.filtros(pares('preco_max_horas=024'))['preco_max_horas'], 24)
        self.assertEqual(A.filtros(None)['ordem'], 'atualizacao')


# ---------------------------------------------------------------- CA4: paginação e ordens
class PaginacaoAtualizacao(Base):
    def test_ca4_empates_de_atualizado_em_sem_pular_nem_repetir(self):
        rng = random.Random(7)
        horas = [ANTIGO, ANTIGO, '2026-11-01T08:00:00', '2026-11-03T12:24:24']
        for _ in range(37):
            self.gravar(rng.choice(('amazon', 'ml', 'shopee')), atualizado_em=rng.choice(horas))
        self.gravar(titulo='Apple i.Phone')          # fora da lista e da contagem
        esperado = [r['id'] for r in self.con.execute(
            "SELECT id FROM items WHERE titulo NOT LIKE '%i.Phone%' ORDER BY atualizado_em, id")]
        for limite in (1, 2, 5, 36, 37, 50):
            with self.subTest(limite=limite):
                vistos, _, totais = self.percorrer(f'limite={limite}')
                self.assertEqual(vistos, esperado)
                self.assertEqual(totais, {37})

    def test_ca4_proximo_e_o_cursor_da_ultima_oferta_e_null_na_pagina_vazia(self):
        a = self.gravar(atualizado_em='2026-11-01T08:00:00')
        b = self.gravar()
        r = self.ofertas('limite=1')
        self.assertEqual(r['proximo'], f'2026-11-01T08:00:00~{a}')
        r = self.ofertas('limite=5&cursor=' + r['proximo'])
        self.assertEqual([o['id'] for o in r['ofertas']], [b])
        self.assertEqual(r['proximo'], f'{ANTIGO}~{b}')     # guardado, serve para buscar só as novidades
        r = self.ofertas('limite=5&cursor=' + r['proximo'])
        self.assertEqual((r['ofertas'], r['proximo'], r['total']), ([], None, 2))
        self.assertEqual(self.ofertas('cat=Nada')['proximo'], None)

    def test_ca4_folga_de_60_segundos(self):
        velho = self.gravar()
        no_limite = self.gravar(atualizado_em=hora(AGORA - timedelta(seconds=60)))
        recente = self.gravar(atualizado_em=hora(AGORA - timedelta(seconds=59)))
        futuro = self.gravar(atualizado_em=hora(AGORA + timedelta(minutes=5)))
        vistos, ultimo, totais = self.percorrer('limite=1')
        self.assertEqual(vistos, [velho, no_limite])
        self.assertEqual(totais, {2})
        depois, _, _ = self.percorrer('limite=1', agora=AGORA + timedelta(seconds=1), cursor=ultimo)
        self.assertEqual(depois, [recente])
        depois, _, _ = self.percorrer('limite=1', agora=AGORA + timedelta(minutes=6), cursor=ultimo)
        self.assertEqual(depois, [recente, futuro])
        # a folga vale só para a ordem atualizacao
        self.assertEqual(len(self.ids('ordem=relevancia')), 4)

    def test_ca4_folga_com_agora_fracionado(self):
        i = self.gravar(atualizado_em='2026-11-03T14:59:00')
        self.assertEqual(self.ids(agora=datetime(2026, 11, 3, 15, 0, 0, 999999)), [i])
        self.assertEqual(self.ids(agora=datetime(2026, 11, 3, 14, 59, 59, 999999)), [])

    def test_ca4_item_atualizado_volta_depois_do_cursor(self):
        ids = [self.gravar() for _ in range(6)]
        vistos, ultimo, _ = self.percorrer('limite=4')
        self.assertEqual(vistos, ids)
        # a coleta regrava o item 3 (atualizado_em novo)
        self.con.execute('UPDATE items SET preco=?, atualizado_em=? WHERE id=?',
                         ('R$ 80,00', hora(AGORA - timedelta(minutes=5)), ids[2]))
        self.con.commit()
        r = self.ofertas('limite=4&cursor=' + ultimo)
        self.assertEqual([o['id'] for o in r['ofertas']], [ids[2]])
        self.assertEqual(r['ofertas'][0]['preco'], 80.0)
        # numa leitura do zero ele aparece uma vez só, no fim
        tudo, _, _ = self.percorrer('limite=4')
        self.assertEqual(tudo, ids[:2] + ids[3:] + [ids[2]])

    def test_ca4_cursor_com_filtros(self):
        for loja in ('amazon', 'ml', 'shopee') * 4:
            self.gravar(loja, atualizado_em=random.Random(self.seq).choice((ANTIGO, '2026-11-02T10:00:00')))
        esperado = [r['id'] for r in self.con.execute(
            "SELECT id FROM items WHERE loja IN ('ml','shopee') ORDER BY atualizado_em, id")]
        vistos, _, totais = self.percorrer('loja=ml&loja=shopee&limite=3')
        self.assertEqual(vistos, esperado)
        self.assertEqual(totais, {8})

    def test_ca4_cursor_adulterado_da_400(self):
        self.gravar()
        ruins = ['x', '', '12', f'{ANTIGO}~', f'{ANTIGO}~0', f'{ANTIGO}~01', f'{ANTIGO}~abc', f'{ANTIGO}~1~2',
                 f'{ANTIGO}~1 ', f' {ANTIGO}~1', f'{ANTIGO}~1\n', '2026-11-03 12:24:23~1', '2026-11-03T12:24~1',
                 f'{ANTIGO}.123~1', f'{ANTIGO}~' + '9' * 19, '٢٠٢٦-11-03T12:24:23~1', f'{ANTIGO}~1;DROP', SEGREDO]
        for c in ruins:
            with self.subTest(cursor=c):
                self.erro('cursor=' + urllib.parse.quote(c))

    def test_ca4_cursor_de_outra_ordem_da_400(self):
        self.gravar()
        self.erro('cursor=5')                                        # deslocamento na ordem atualizacao
        self.erro('ordem=desconto&cursor=' + urllib.parse.quote(f'{ANTIGO}~1'))
        self.erro('ordem=atualizacao&cursor=5')

    def test_ca4_cursor_bem_formado_de_item_que_nao_existe_funciona(self):
        a = self.gravar()
        self.assertEqual(self.ids('cursor=' + urllib.parse.quote('2000-01-01T00:00:00~999')), [a])
        self.assertEqual(self.ids('cursor=' + urllib.parse.quote('2999-01-01T00:00:00~1')), [])


class OrdensDoDisparo(Base):
    def gravar(self, loja='amazon', **campos):
        """Preço confirmado agora: o disparo.elegiveis, oráculo destes testes, tira o preço velho
        (CA6 de docs/produto/planos/atualizar-precos.md); a v1 sem preco_max_horas não tira."""
        campos.setdefault('preco_em', hora(AGORA))
        return super().gravar(loja, **campos)

    def popular(self, rng):
        """Itens com empates de propósito (vendas, preço, desconto, posição, criado_em)."""
        for _ in range(45):
            self.gravar(rng.choice(('amazon', 'ml', 'shopee')),
                        cat=rng.choice(('Perfumes e Perfumaria', 'Casa e Decoração')),
                        preco=rng.choice(('R$ 10,00', 'R$ 99,90', 'R$ 1.899', 'R$ 99,90')),
                        desconto=rng.choice(('', '-5%', '-30%', '30% OFF')),
                        vendas=rng.choice(('', 'Mais de 1 mil compras', '+50 vendidos', '27,6 mil')),
                        num_avaliacoes=rng.choice(('', '(135)', '1.234')),
                        avaliacao=rng.choice(('', '4,5 de 5', '4.8')),
                        cupom=rng.choice(('', '', 'Cupom 10% OFF')),
                        posicao=rng.randint(1, 15),
                        criado_em=rng.choice((ANTIGO, '2026-11-01T08:00:00', '2026-10-30T23:59:59')))
        self.gravar(titulo='Apple i.Phone 15', vendas='Mais de 10 mil compras')
        self.gravar('ml', url='https://produto.mercadolivre.com.br/MLB-1', vendas='Mais de 10 mil compras')

    def esperado(self, ordem, cats=('Perfumes e Perfumaria', 'Casa e Decoração'), lojas=D.LOJAS):
        regra = {'cats': list(cats), 'lojas': list(lojas), 'numero_id': 1, 'repetir_apos_dias': 7,
                 'desconto_min': 0, 'palavras': []}
        # Mesma entrada da API (por id): o SELECT do elegiveis não tem ORDER BY e o sqlite lê pelo
        # ix_items_cat, então lá os empates de posicao saem na ordem da categoria.
        itens = sorted((it for it in D.elegiveis(self.con, regra, AGORA, AFILIADO)
                        if not D.urls_da_mensagem(it['data']['titulo']) and not D.urls_da_mensagem(it['data']['cupom'])),
                       key=lambda it: it['id'])
        return [it['id'] for it in D.ordenar(itens, ordem)]

    def test_ca4_paridade_com_disparo_ordenar(self):
        self.popular(random.Random(42))
        for ordem in ('relevancia', 'desconto', 'menor_preco', 'maior_preco', 'cupom', 'recentes'):
            with self.subTest(ordem=ordem):
                esperado = self.esperado(ordem)
                self.assertEqual(len(esperado), 45)
                self.assertEqual(self.ids(f'ordem={ordem}&limite=200'), esperado)
                vistos, _, totais = self.percorrer(f'ordem={ordem}&limite=7')
                self.assertEqual(vistos, esperado)
                self.assertEqual(totais, {45})

    def test_ca4_paridade_com_duas_categorias_lidas_pelo_indice(self):
        # com cat no WHERE o sqlite lê pelo ix_items_cat (por categoria); a entrada do ordenar
        # tem de continuar por id, senão os empates de posicao mudam de lugar
        rng = random.Random(5)
        for _ in range(30):
            self.gravar(cat=rng.choice(('Zeta', 'Alfa')), posicao=1, desconto=rng.choice(('', '-10%')))
        for ordem in ('desconto', 'cupom', 'menor_preco'):
            with self.subTest(ordem=ordem):
                self.assertEqual(self.ids(f'ordem={ordem}&cat=Zeta&cat=Alfa&limite=200'),
                                 self.esperado(ordem, cats=('Zeta', 'Alfa')))

    def test_ca4_paridade_com_filtro_de_loja_e_cat(self):
        self.popular(random.Random(3))
        esperado = self.esperado('relevancia', cats=('Casa e Decoração',), lojas=('ml', 'shopee'))
        self.assertTrue(esperado)
        vistos, _, _ = self.percorrer('ordem=relevancia&limite=4&cat=Casa+e+Decora%C3%A7%C3%A3o&loja=ml&loja=shopee')
        self.assertEqual(vistos, esperado)

    def test_ca4_deslocamento(self):
        for _ in range(5):
            self.gravar()
        r = self.ofertas('ordem=desconto&limite=2')
        self.assertEqual(r['proximo'], '2')
        r = self.ofertas('ordem=desconto&limite=2&cursor=4')
        self.assertEqual((len(r['ofertas']), r['proximo'], r['total']), (1, None, 5))
        r = self.ofertas('ordem=desconto&limite=5')
        self.assertIsNone(r['proximo'])                      # coube tudo: não há próxima página
        r = self.ofertas('ordem=desconto&cursor=999')
        self.assertEqual((r['ofertas'], r['proximo'], r['total']), ([], None, 5))
        self.erro('ordem=desconto&cursor=0')
        self.erro('ordem=desconto&cursor=-1')
        self.erro('ordem=desconto&cursor=1234567890')

    def test_ca4_aleatoria_da_400(self):
        self.gravar()
        self.assertIn('aleatoria', self.erro('ordem=aleatoria'))


# ---------------------------------------------------------------- CA5: categorias
class Categorias(Base):
    def test_ca5_formato_ordem_alfabetica_e_contagem(self):
        self.gravar(cat='Zebra')
        self.gravar('ml', cat='Ética')
        self.gravar('shopee', cat='Ética')
        self.gravar(cat='eletro')
        self.gravar(cat='Casa')
        self.gravar('ml', cat='Casa')
        self.gravar(cat='Casa', titulo='Apple i.Phone')                   # fora (CA2)
        self.gravar('ml', cat='Casa', url='https://produto.mercadolivre.com.br/MLB-1')
        self.gravar(cat='Só inválidos', preco='')
        r = self.cats()
        self.assertEqual(list(r), ['versao', 'categorias', 'total'])
        self.assertEqual(r['versao'], 1)
        self.assertEqual(r['total'], 6)
        sem = lambda n: {'feminino': 0, 'masculino': 0, 'unissex': 0, 'sem': n}   # abas sem público
        self.assertEqual(r['categorias'], [
            {'nome': 'Casa', 'total': 2, 'lojas': {'amazon': 1, 'ml': 1, 'shopee': 0}, 'generos': sem(2)},
            {'nome': 'eletro', 'total': 1, 'lojas': {'amazon': 1, 'ml': 0, 'shopee': 0}, 'generos': sem(1)},
            {'nome': 'Ética', 'total': 2, 'lojas': {'amazon': 0, 'ml': 1, 'shopee': 1}, 'generos': sem(2)},
            {'nome': 'Zebra', 'total': 1, 'lojas': {'amazon': 1, 'ml': 0, 'shopee': 0}, 'generos': sem(1)}])

    def test_ca5_bate_com_a_contagem_das_ofertas(self):
        OrdensDoDisparo.popular(self, random.Random(9))
        r = self.cats()
        for c in r['categorias']:
            self.assertEqual(self.ofertas('cat=' + urllib.parse.quote(c['nome']))['total'], c['total'])
            for loja, n in c['lojas'].items():
                self.assertEqual(self.ofertas(f"cat={urllib.parse.quote(c['nome'])}&loja={loja}")['total'], n)
        self.assertEqual(self.ofertas()['total'], r['total'])

    def test_ca5_banco_vazio(self):
        self.assertEqual(self.cats(), {'versao': 1, 'categorias': [], 'total': 0})

    def test_ca5_nao_aceita_parametros(self):
        with self.assertRaises(A.ErroApi) as ctx:
            A.rota(self.con, 'GET', '/api/v1/categorias', [('cat', 'x')], AFILIADO)
        self.assertEqual(ctx.exception.codigo, 400)


# ---------------------------------------------------------------- CA6 (genero-nas-categorias): público
PERFUMES, CASA = 'Perfumes e Perfumaria', 'Casa e Decoração'
MSG_GENERO = 'genero deve ser feminino, masculino, unissex, sem, sem repetir'


class Genero(Base):
    """docs/produto/planos/genero-nas-categorias.md, etapa 5: `genero` na oferta, no filtro e nas categorias."""

    def popular_generos(self):
        """Um item de cada público na perfumaria e um da Casa com palavra de gênero (que é `sem`)."""
        return {'feminino': self.gravar(titulo='Lady Million Paco Rabanne Feminino'),
                'masculino': self.gravar('ml', titulo='212 Men NYC'),
                'unissex': self.gravar('shopee', titulo='Kit Perfumes Feminino e Masculino'),
                'sem': self.gravar(titulo='Hidratante Corporal Pele Seca', busca='hidratante corporal'),
                'casa': self.gravar(cat=CASA, titulo='Jogo de Toalhas Masculino', busca='perfume masculino')}

    def corrigir(self, item_pk, valor):
        G.definir_manual(self.con, item_pk, valor, ANTIGO)
        self.con.commit()

    def test_ca6_oferta_com_os_4_valores(self):
        ids = self.popular_generos()
        busca = self.gravar(titulo='Olympea EDP', busca='Perfume feminino importado')   # só a busca diz
        por_id = {o['id']: o for o in self.ofertas('limite=200')['ofertas']}
        self.assertEqual({nome: por_id[i]['genero'] for nome, i in ids.items()},
                         {'feminino': 'feminino', 'masculino': 'masculino', 'unissex': 'unissex', 'sem': 'sem',
                          'casa': 'sem'})
        self.assertEqual(por_id[busca]['genero'], 'feminino')
        self.assertEqual({o['genero'] for o in por_id.values()}, set(G.GENEROS))
        for o in por_id.values():
            # campos novos no fim (genero e depois preco_em); os antigos na mesma ordem
            self.assertEqual(list(o)[-2:], ['genero', 'preco_em'])
            self.assertNotIn('genero_origem', o)            # a origem fica só no /api/items

    def test_ca6_correcao_manual_vale_so_em_aba_com_genero(self):
        ids = self.popular_generos()
        self.corrigir(ids['feminino'], 'unissex')
        self.corrigir(ids['sem'], 'masculino')
        self.corrigir(ids['casa'], 'feminino')               # guardada, mas a Casa não separa por público
        por_id = {o['id']: o['genero'] for o in self.ofertas('limite=200')['ofertas']}
        self.assertEqual((por_id[ids['feminino']], por_id[ids['sem']], por_id[ids['casa']]),
                         ('unissex', 'masculino', 'sem'))
        self.assertEqual(sorted(self.ids('genero=masculino')), sorted([ids['masculino'], ids['sem']]))
        por_nome = {c['nome']: c['generos'] for c in self.cats()['categorias']}
        self.assertEqual(por_nome, {PERFUMES: {'feminino': 0, 'masculino': 2, 'unissex': 2, 'sem': 0},
                                    CASA: {'feminino': 0, 'masculino': 0, 'unissex': 0, 'sem': 1}})
        self.corrigir(ids['feminino'], None)                 # volta ao automático
        self.assertEqual(self.ids('genero=feminino'), [ids['feminino']])

    def test_ca6_oferta_direto_com_2_ou_3_argumentos(self):
        i = self.gravar(titulo='Perfume Feminino Floral')
        self.corrigir(i, 'masculino')
        linha = self.con.execute('SELECT * FROM items WHERE id=?', (i,)).fetchone()
        self.assertEqual(A.oferta(linha, AFILIADO)['genero'], 'feminino')        # compatível: sem correções
        self.assertEqual(A.oferta(linha, AFILIADO, None)['genero'], 'feminino')
        self.assertEqual(A.oferta(linha, AFILIADO, G.manuais(self.con))['genero'], 'masculino')

    def test_ca6_genero_repetivel_filtro_exato_e_total_filtrado(self):
        ids = self.popular_generos()
        for _ in range(3):
            self.gravar(titulo='Perfume Masculino Amadeirado')
        self.assertEqual(self.ids('genero=feminino'), [ids['feminino']])
        self.assertEqual(sorted(self.ids('genero=feminino&genero=unissex')), sorted([ids['feminino'], ids['unissex']]))
        self.assertEqual(sorted(self.ids('genero=sem')), sorted([ids['sem'], ids['casa']]))   # exato: a Casa é `sem`
        self.assertEqual(self.ofertas('genero=masculino')['total'], 4)
        self.assertEqual(self.ofertas('genero=masculino&limite=1')['total'], 4)
        todos = '&'.join(f'genero={g}' for g in reversed(G.GENEROS))
        self.assertEqual(self.ofertas(todos)['total'], self.ofertas()['total'])
        self.assertEqual(self.ids(f'genero=feminino&cat={urllib.parse.quote(CASA)}'), [])
        self.assertEqual(self.ids('genero=masculino&loja=ml'), [ids['masculino']])
        self.assertEqual(self.ids('genero=masculino&q=nyc'), [ids['masculino']])
        self.assertEqual(A.filtros(pares('genero=unissex&genero=feminino'))['generos'], ['unissex', 'feminino'])

    def test_ca6_genero_com_paginacao_nas_duas_familias_de_ordem(self):
        OrdensDoDisparo.popular(self, random.Random(11))
        for g in G.GENEROS:
            for ordem in ('atualizacao', 'relevancia', 'menor_preco'):
                with self.subTest(genero=g, ordem=ordem):
                    todos = [o for o in self.ofertas(f'ordem={ordem}&limite=200')['ofertas']]
                    esperado = [o['id'] for o in todos if o['genero'] == g]
                    vistos, _, totais = self.percorrer(f'ordem={ordem}&limite=3&genero={g}')
                    self.assertEqual(vistos, esperado)
                    self.assertEqual(totais, {len(esperado)})

    def test_ca6_genero_invalido_da_400_sem_eco(self):
        self.gravar()
        for qs in ('genero=', 'genero=Feminino', 'genero=FEMININO', 'genero=feminina', 'genero=fem', 'genero=f',
                   'genero=todos', 'genero=feminino%20', 'genero=%20sem', 'genero=feminino,masculino',
                   'genero=infantil', 'genero=' + SEGREDO, 'genero=sem&genero=' + SEGREDO,
                   'genero=f%C3%AAminino', 'genero=%EF%BD%93%EF%BD%85%EF%BD%8D'):    # acento e largura total
            with self.subTest(qs=qs):
                self.assertEqual(self.erro(qs), MSG_GENERO)

    def test_ca6_genero_repetido_da_400(self):
        for g in G.GENEROS:
            with self.subTest(genero=g):
                self.assertEqual(self.erro(f'genero={g}&genero={g}'), MSG_GENERO)
        self.assertEqual(self.erro('genero=sem&genero=feminino&genero=sem'), MSG_GENERO)
        with self.assertRaises(A.ErroApi) as ctx:
            A.filtros([('genero', 'feminino'), ('genero', 'feminino')])
        self.assertEqual((ctx.exception.codigo, ctx.exception.msg), (400, MSG_GENERO))

    def test_ca6_parametro_desconhecido_lista_genero(self):
        self.assertEqual(self.erro('generos=feminino'),
                         'parâmetro desconhecido (use cat, loja, q, desconto_min, ordem, limite, cursor, genero, '
                         'preco_max_horas)')
        for qs in ('Genero=feminino', 'publico=feminino', 'g%C3%AAnero=feminino'):
            with self.subTest(qs=qs):
                self.assertIn('desconhecido', self.erro(qs))

    def test_ca6_max_pares_soma_os_4_generos(self):
        self.assertEqual(A.MAX_PARES, 33)   # 32 com genero; preco_max_horas (atualizar-precos) soma 1
        self.assertEqual(A.MAX_PARES, A.MAX_CATS + len(D.LOJAS) + len(G.GENEROS) + 6)
        self.gravar()
        maior = ([f'cat=c{i}' for i in range(A.MAX_CATS)] + [f'loja={l}' for l in D.LOJAS]
                 + [f'genero={g}' for g in G.GENEROS]
                 + ['q=perfume', 'desconto_min=0', 'ordem=relevancia', 'limite=10', 'cursor=10', 'preco_max_horas=168'])
        self.assertEqual(len(maior), A.MAX_PARES)
        r = self.ofertas('&'.join(maior))                  # o maior pedido válido passa
        self.assertEqual((r['versao'], r['total']), (1, 0))
        self.assertEqual(self.erro('&'.join(maior + ['cat=c99'])), 'parâmetros demais')
        self.assertEqual(self.erro('&'.join(['genero=sem'] * (A.MAX_PARES + 1))), 'parâmetros demais')

    def test_ca6_genero_nao_traz_oferta_sem_link_de_afiliado(self):
        bom = self.gravar(titulo='Perfume Feminino Floral')
        fora = [self.gravar('ml', titulo='Perfume Feminino Floral', url='https://produto.mercadolivre.com.br/MLB-1'),
                self.gravar(titulo='Perfume Feminino Floral', url='https://www.amazon.com.br/dp/B0X?tag=outro-20'),
                self.gravar(titulo='Perfume Feminino i.Phone'),
                self.gravar(titulo='Perfume Feminino Floral', preco='consulte'),
                self.gravar(titulo='Perfume Feminino Floral', tem_dados=0)]
        for i in fora:
            self.corrigir(i, 'feminino')
        for qs in ('genero=feminino', 'genero=feminino&ordem=relevancia', 'genero=feminino&genero=sem'):
            with self.subTest(qs=qs):
                self.assertEqual(self.ids(qs), [bom])
                self.assertEqual(self.ofertas(qs)['total'], 1)
        manuais = G.manuais(self.con)
        for i in fora:
            linha = self.con.execute('SELECT * FROM items WHERE id=?', (i,)).fetchone()
            self.assertIsNone(A.oferta(linha, AFILIADO, manuais), i)
        self.assertEqual(self.cats()['categorias'][0]['generos'], {'feminino': 1, 'masculino': 0, 'unissex': 0,
                                                                   'sem': 0})

    def test_ca6_categorias_com_as_4_chaves_e_contagem_igual_ao_filtro(self):
        self.popular_generos()
        OrdensDoDisparo.popular(self, random.Random(7))
        self.gravar(cat='Zebra', titulo='Relógio Masculino')
        r = self.cats()
        self.assertEqual([list(c) for c in r['categorias']], [['nome', 'total', 'lojas', 'generos']] * 3)
        for c in r['categorias']:
            with self.subTest(cat=c['nome']):
                self.assertEqual(list(c['generos']), list(G.GENEROS))
                self.assertEqual(sum(c['generos'].values()), c['total'])
                for g, n in c['generos'].items():
                    self.assertEqual(self.ofertas(f"cat={urllib.parse.quote(c['nome'])}&genero={g}")['total'], n)
                if c['nome'] not in G.ABAS_COM_GENERO:
                    self.assertEqual(c['generos']['sem'], c['total'])
        perfumes = next(c for c in r['categorias'] if c['nome'] == PERFUMES)
        self.assertTrue(all(perfumes['generos'][g] >= 1 for g in G.GENEROS), perfumes)

    def test_ca6_banco_sem_a_tabela_de_correcoes_e_tudo_automatico(self):
        # banco migrado por código antigo (v1): a v1 não pode cair por falta da tabela
        ids = self.popular_generos()
        self.con.execute('DROP TABLE IF EXISTS generos_manuais')
        self.con.commit()
        por_id = {o['id']: o['genero'] for o in self.ofertas('limite=200')['ofertas']}
        self.assertEqual(por_id[ids['feminino']], 'feminino')
        self.assertEqual(self.ids('genero=unissex'), [ids['unissex']])
        self.assertEqual(sum(self.cats()['categorias'][-1]['generos'].values()), 4)

    def test_ca6_query_only_com_correcoes_nao_grava(self):
        # como o servidor.py abre a conexão da v1 (PRAGMA query_only)
        ids = self.popular_generos()
        self.corrigir(ids['sem'], 'unissex')
        ro = abrir(self.caminho)
        self.addCleanup(ro.close)
        ro.execute('PRAGMA query_only=1')
        antes = [tuple(r) for r in self.con.execute('SELECT * FROM generos_manuais ORDER BY item_pk')]
        self.assertEqual(sorted(self.ids('genero=unissex&ordem=desconto')),
                         sorted([ids['unissex'], ids['sem']]))
        r = A.rota(ro, 'GET', '/api/v1/ofertas', pares('genero=unissex'), AFILIADO, AGORA)
        self.assertEqual(r['total'], 2)
        A.rota(ro, 'GET', '/api/v1/categorias', [], AFILIADO)
        self.assertEqual(ro.total_changes, 0)
        self.assertEqual([tuple(r) for r in self.con.execute('SELECT * FROM generos_manuais ORDER BY item_pk')], antes)

    def test_ca6_versao_continua_1_e_json_valido(self):
        self.popular_generos()
        for r in (self.ofertas('genero=feminino'), self.cats()):
            self.assertEqual(r['versao'], 1)
            json.dumps(r, allow_nan=False)


# ---------------------------------------------------------------- idade do preço (atualizar-precos, CA8)
class PrecoEm(Base):
    """docs/produto/planos/atualizar-precos.md, etapa 3: `preco_em` no fim da oferta e o filtro opcional
    preco_max_horas, que só vale quando pedido (decisão P2 do dono: sem ele, nada sai da resposta)."""

    # (valor gravado em items.preco_em, o que a oferta traz): fora do formato do servidor vira null
    ESTRANHOS = ((None, None), ('', None), ('03/11/2026 12:24', None), ('2026-11-03 12:24:23', None),
                 ('2026-11-03T12:24:23.5', None), ('2026-11-03T12:24', None), (' 2026-11-03T12:24:23', None),
                 ('2026-11-03T12:24:23\n', None), ('2026-11-31T10:00:00', None), ('2026-11-03T25:00:00', None),
                 ('٢٠٢٦-11-03T12:24:23', None), ('z', None),
                 (b'2026-11-03T12:24:23', None), (20261103, None),
                 # Q2: o fromisoformat do Python 3.14 aceita a hora 24; a regra única (disparo.ler_preco_em) não
                 ('2026-11-02T24:00:00', None), ('2026-11-03T14:60:00', None), ('2026-11-03T14:00:60', None))

    def antes(self, horas=0, segundos=0, agora=AGORA):
        return hora(agora - timedelta(hours=horas, seconds=segundos))

    def test_ca8_preco_em_sai_como_texto_ou_null_e_nunca_tira_a_oferta(self):
        validos = {self.gravar(preco_em=ANTIGO): ANTIGO, self.gravar('ml', preco_em=hora(AGORA)): hora(AGORA),
                   self.gravar('shopee', preco_em='2020-02-29T00:00:00'): '2020-02-29T00:00:00',
                   # no futuro: o campo mostra a data como está; quem a trata como velha é o filtro (S2)
                   self.gravar(preco_em='2999-12-31T23:59:59'): '2999-12-31T23:59:59'}
        estranhos = {self.gravar(preco_em=v): esperado for v, esperado in self.ESTRANHOS}
        r = self.ofertas('limite=200')
        json.dumps(r, allow_nan=False)
        self.assertEqual(r['total'], len(validos) + len(estranhos))
        self.assertEqual({o['id']: o['preco_em'] for o in r['ofertas']}, {**validos, **estranhos})
        for o in r['ofertas']:
            self.assertEqual(list(o), CAMPOS_OFERTA)
        self.assertEqual(self.cats()['total'], len(validos) + len(estranhos))

    def test_ca8_sem_o_filtro_preco_em_nao_muda_nada_na_resposta(self):
        for n in range(12):
            loja = D.LOJAS[n % 3]
            v = (ANTIGO, None, hora(AGORA), '03/11/2026', b'x', '2001-01-01T00:00:00')[n % 6]
            self.gravar(loja, preco_em=v, preco=f'R$ {10 + n},00', vendas=f'+{n} vendidos', desconto=f'-{n}%')

        def sem_campo(qs):
            r = self.ofertas(qs)
            return {**r, 'ofertas': [{k: v for k, v in o.items() if k != 'preco_em'} for o in r['ofertas']]}

        consultas = [f'ordem={o}&limite=5' for o in A.ORDENS] + ['loja=ml', 'q=perfume', 'desconto_min=3']
        com_datas = {qs: sem_campo(qs) for qs in consultas}
        self.assertEqual(com_datas['ordem=atualizacao&limite=5']['total'], 12)
        self.con.execute('UPDATE items SET preco_em = NULL')
        self.con.commit()
        for qs in consultas:
            with self.subTest(qs=qs):
                self.assertEqual(com_datas[qs], sem_campo(qs))

    def test_ca8_filtro_na_borda_e_igual_ao_disparo_preco_recente(self):
        gravados = {}
        # no futuro (S2): até 5 min à frente do agora ainda vale; 5 min e 1 s ou 1 h à frente já é velho
        mais_5min, mais_5min_1s = hora(AGORA + timedelta(minutes=5)), hora(AGORA + timedelta(minutes=5, seconds=1))
        for v in (self.antes(0), self.antes(23), self.antes(24), self.antes(24, 1), self.antes(25),
                  self.antes(167), self.antes(168), self.antes(168, 1), hora(AGORA + timedelta(hours=1)),
                  mais_5min, mais_5min_1s, ANTIGO) + tuple(v for v, _ in self.ESTRANHOS):
            gravados[self.gravar(preco_em=v)] = v
        ida = {v: i for i, v in gravados.items() if isinstance(v, str)}
        recentes_24 = sorted(ida[v] for v in (self.antes(0), self.antes(23), self.antes(24), ANTIGO, mais_5min))
        self.assertEqual(sorted(self.ids('preco_max_horas=24&limite=200')), recentes_24)
        for futuro in (mais_5min_1s, hora(AGORA + timedelta(hours=1))):
            self.assertNotIn(ida[futuro], self.ids('preco_max_horas=168&limite=200'), futuro)
        # 2026-02-30 e companhia passam na comparação de texto do SQL; o BLOB também (BLOB > TEXT)
        for agora in (AGORA, AGORA + timedelta(microseconds=500000), AGORA + timedelta(hours=30)):
            for horas in (1, 23, 24, 25, 167, 168):
                with self.subTest(agora=agora, horas=horas):
                    esperado = sorted(i for i, v in gravados.items() if D.preco_recente(v, agora, horas))
                    r = self.ofertas(f'preco_max_horas={horas}&limite=200&ordem=relevancia', agora)
                    self.assertEqual(sorted(o['id'] for o in r['ofertas']), esperado)
                    self.assertEqual(r['total'], len(esperado))
        # agora fracionado: o limite exato de 24 h (contado do segundo cheio) já ficou velho
        self.assertNotIn(ida[self.antes(24)],
                         self.ids('preco_max_horas=24&limite=200', AGORA + timedelta(microseconds=500000)))

    def test_ca8_filtro_com_paginacao_total_e_os_outros_filtros(self):
        recentes, velhos = [], []
        for n in range(30):
            loja = D.LOJAS[n % 3]
            atualizado = hora(datetime(2026, 11, 2, 10, 0, 0) + timedelta(minutes=n % 7))
            if n % 2:
                recentes.append(self.gravar(loja, preco_em=self.antes(n % 20), atualizado_em=atualizado,
                                            vendas=f'+{n} vendidos'))
            else:
                velhos.append(self.gravar(loja, preco_em=self.antes(30 + n), atualizado_em=atualizado,
                                          vendas=f'+{n} vendidos'))
        linha = {r['id']: r['atualizado_em'] for r in self.con.execute('SELECT id, atualizado_em FROM items')}
        vistos, _, totais = self.percorrer('preco_max_horas=24&limite=4')
        self.assertEqual(vistos, sorted(recentes, key=lambda i: (linha[i], i)))
        self.assertEqual(totais, {len(recentes)})
        vistos, _, totais = self.percorrer('preco_max_horas=24&limite=4&ordem=relevancia')
        self.assertEqual(sorted(vistos), sorted(recentes))
        self.assertEqual(len(vistos), len(set(vistos)))
        self.assertEqual(totais, {len(recentes)})
        ml = [i for n, i in enumerate(recentes) if D.LOJAS[(2 * n + 1) % 3] == 'ml']
        self.assertEqual(sorted(self.ids('preco_max_horas=24&loja=ml&limite=200')), sorted(ml))
        self.assertEqual(self.ids('preco_max_horas=24&q=nada-assim'), [])
        self.assertEqual(sorted(self.ids('preco_max_horas=168&limite=200')), sorted(recentes + velhos))

    def test_ca8_preco_max_horas_invalido_da_400_sem_ecoar(self):
        for qs in ('preco_max_horas=0', 'preco_max_horas=169', 'preco_max_horas=-1', 'preco_max_horas=',
                   'preco_max_horas=1.5', 'preco_max_horas=24h', 'preco_max_horas=+5', 'preco_max_horas=%2024',
                   'preco_max_horas=%D9%A3', 'preco_max_horas=1e2', 'preco_max_horas=0x10',
                   'preco_max_horas=9999', 'preco_max_horas=' + SEGREDO):
            with self.subTest(qs=qs):
                self.assertEqual(self.erro(qs), 'preco_max_horas deve ser um número inteiro de 1 a 168')
        self.assertIn('preco_max_horas', self.erro('preco_max_horas=24&preco_max_horas=24'))
        for qs in ('Preco_max_horas=24', 'preco_max=24', 'preco_max_horas[]=24'):
            with self.subTest(qs=qs):
                self.assertIn('desconhecido', self.erro(qs))
        with self.assertRaises(A.ErroApi) as ctx:
            A.rota(self.con, 'GET', '/api/v1/categorias', pares('preco_max_horas=24'), AFILIADO, AGORA)
        self.assertEqual(ctx.exception.codigo, 400)

    def test_ca8_limites_aceitos(self):
        i = self.gravar(preco_em=self.antes(1))
        for qs in ('preco_max_horas=1', 'preco_max_horas=01', 'preco_max_horas=168', 'preco_max_horas=024'):
            with self.subTest(qs=qs):
                self.assertEqual(self.ids(qs), [i])
        self.assertEqual(self.ids('preco_max_horas=1', AGORA + timedelta(seconds=1)), [])

    def test_ca8_o_sql_estreita_a_leitura(self):
        recentes = [self.gravar(preco_em=self.antes(h)) for h in (0, 5)]
        for h in (30, 40, 50, 60):
            self.gravar(preco_em=self.antes(h))
        self.gravar(preco_em=None)
        with mock.patch.object(A, 'oferta', wraps=A.oferta) as espiao:
            self.assertEqual(self.ids('preco_max_horas=24'), recentes)
        self.assertEqual(espiao.call_count, 2)   # as 5 velhas nem saem do sqlite

    def test_ca8_banco_de_antes_da_v3_da_null_e_o_filtro_nao_traz_nada(self):
        # o servidor migra na subida; um retrato antigo lido direto (como o do test_api_ofertas_qa) não
        a, b = self.gravar(preco_em=self.antes(1)), self.gravar('ml', preco_em=None)
        self.con.execute('ALTER TABLE items DROP COLUMN preco_em')
        self.con.commit()
        ro = abrir(self.caminho, so_leitura=True)
        self.addCleanup(ro.close)
        r = self.ofertas('limite=200', con=ro)
        self.assertEqual(({o['id']: o['preco_em'] for o in r['ofertas']}, r['total']), ({a: None, b: None}, 2))
        self.assertEqual([list(o) for o in r['ofertas']], [CAMPOS_OFERTA] * 2)
        for ordem in A.ORDENS:
            with self.subTest(ordem=ordem):
                r = self.ofertas(f'ordem={ordem}&preco_max_horas=168', con=ro)
                self.assertEqual((r['ofertas'], r['total'], r['proximo']), ([], 0, None))
        self.assertEqual(self.cats(con=ro)['total'], 2)
        self.assertEqual(ro.total_changes, 0)

    def test_ca8_conexao_so_leitura_com_o_filtro(self):
        self.gravar(preco_em=self.antes(1))
        self.gravar('ml', preco_em=b'x')
        ro = abrir(self.caminho, so_leitura=True)
        self.addCleanup(ro.close)
        for ordem in A.ORDENS:
            self.assertEqual(self.ofertas(f'ordem={ordem}&preco_max_horas=24', con=ro)['total'], 1)
        self.assertEqual(ro.total_changes, 0)
        self.assertFalse(ro.in_transaction)


# ---------------------------------------------------------------- rota e CA9
class Rota(Base):
    def test_rota_desconhecida_da_404(self):
        for caminho in ('/api/v1/', '/api/v1', '/api/v1/ofertas/', '/api/v1/ofertas/1', '/api/v1/Ofertas',
                        '/api/v1/categorias/x', '/api/items', '/api/v2/ofertas', None, 12):
            with self.subTest(caminho=caminho), self.assertRaises(A.ErroApi) as ctx:
                A.rota(self.con, 'GET', caminho, [], AFILIADO, AGORA)
            self.assertEqual(ctx.exception.codigo, 404)

    def test_metodo_diferente_de_get_da_405(self):
        for caminho in ('/api/v1/ofertas', '/api/v1/categorias'):
            for metodo in ('POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS', 'get'):
                with self.subTest(caminho=caminho, metodo=metodo), self.assertRaises(A.ErroApi) as ctx:
                    A.rota(self.con, metodo, caminho, [], AFILIADO, AGORA)
                self.assertEqual(ctx.exception.codigo, 405)

    def test_agora_padrao_e_o_relogio(self):
        a = self.gravar()
        self.gravar(atualizado_em=hora(datetime.now() + timedelta(hours=1)))
        r = A.rota(self.con, 'GET', '/api/v1/ofertas', [], AFILIADO)
        self.assertEqual([o['id'] for o in r['ofertas']], [a])

    def test_erro_api_tem_codigo_e_msg(self):
        e = A.ErroApi(400, 'frase')
        self.assertEqual((e.codigo, e.msg, str(e)), (400, 'frase', 'frase'))


class SoLeitura(Base):
    def test_ca9_funciona_numa_conexao_so_leitura_e_nao_grava(self):
        self.gravar()
        self.gravar('ml', titulo='Apple i.Phone')
        self.gravar('shopee', atualizado_em=hora(AGORA))
        esquema = self.con.execute('SELECT type, name, sql FROM sqlite_master ORDER BY name').fetchall()
        versao = self.con.execute('PRAGMA user_version').fetchone()[0]
        dados = [tuple(r) for r in self.con.execute('SELECT * FROM items ORDER BY id')]
        ro = abrir(self.caminho, so_leitura=True)
        self.addCleanup(ro.close)
        for ordem in A.ORDENS:
            self.ofertas(f'ordem={ordem}&q=perfume', con=ro)
        self.ofertas('cursor=' + urllib.parse.quote(f'{ANTIGO}~1'), con=ro)
        self.cats(con=ro)
        self.assertEqual(ro.total_changes, 0)
        self.assertFalse(ro.in_transaction)
        self.assertEqual([tuple(r) for r in self.con.execute('SELECT type, name, sql FROM sqlite_master ORDER BY name')],
                         [tuple(r) for r in esquema])
        self.assertEqual(self.con.execute('PRAGMA user_version').fetchone()[0], versao)
        self.assertEqual([tuple(r) for r in self.con.execute('SELECT * FROM items ORDER BY id')], dados)

    def test_ca9_modulo_nao_importa_servidor(self):
        with open(os.path.join(RAIZ, 'api_ofertas.py'), encoding='utf-8') as f:
            arvore = ast.parse(f.read())
        importados = set()
        for no in ast.walk(arvore):
            if isinstance(no, ast.Import):
                importados |= {a.name.split('.')[0] for a in no.names}
            elif isinstance(no, ast.ImportFrom):
                importados.add((no.module or '').split('.')[0])
        self.assertNotIn('servidor', importados)
        self.assertLessEqual(importados, {'math', 're', 'datetime', 'disparo', 'genero'})


if __name__ == '__main__':
    unittest.main()
