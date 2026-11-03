#!/usr/bin/env python3
"""Testes de QA da API v1 (docs/produto/planos/api-achadinho-turbo.md, etapas 1 e 2).

Uso:  python3 testes/test_api_ofertas_qa.py -v

Complementam testes/test_api_ofertas.py e testes/test_api_ofertas_servidor.py (que importamos para
reaproveitar o banco temporário, o relógio injetado e o servidor de teste), sem repetir os casos
deles. Foco: CA4 com modelo aleatório de semente fixa (empates, escrita durante a leitura, item
atualizado depois do cursor, folga de 60 s), CA2 com dados hostis nos campos que saem no corpo, CA3 e
CA5 em paridade com o disparo e entre si, CA6/CA7 pelo HTTP (variações de caminho, limites do token,
simultaneidade) e CA9 com uma cópia do banco real.

Nada aqui toca o servidor em 8765, o api_token.txt do projeto, o Achadinho Turbo ou a rede (proxy
morto). O banco real só é aberto em mode=ro, para copiar com sqlite3.backup; todo servidor sobe sobre
banco temporário ou sobre essa cópia, com o agendador do disparo desligado. O token é gerado aqui e
nunca é impresso. Só biblioteca padrão.
"""
import http.client
import json
import math
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
import unicodedata
import unittest
import urllib.parse
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_api_ofertas as T              # noqa: E402  (Base, relógio injetado, banco temporário)
import test_api_ofertas_servidor as TS2   # noqa: E402  (ServidorApi, gravar_token)

TS = TS2.TS
A, D, S = T.A, T.D, T.S
AFILIADO = T.AFILIADO
AGORA = T.AGORA
DEPOIS = datetime(2030, 1, 1)   # bem depois de qualquer horário gravado: nada fica na folga
TAG = 'desejodemen01-20'
PERFUMES = 'Perfumes e Perfumaria'
CASA = 'Casa e Decoração'


def tearDownModule():
    shutil.rmtree(TS2.TMP, ignore_errors=True)   # o import do módulo do dev cria esse diretório


# ------------------------------------------------------------------ apoio
def varrer(con, extra=(), agora=DEPOIS, limite=200, ordem=None, cursor=None):
    """Segue `proximo` até o fim e devolve a lista de ofertas (sem repetir pedido a mais que o preciso)."""
    base = [('limite', str(limite))] + ([('ordem', ordem)] if ordem else []) + list(extra)
    saida = []
    for _ in range(10000):
        pares = base + ([('cursor', cursor)] if cursor else [])
        r = A.rota(con, 'GET', '/api/v1/ofertas', pares, AFILIADO, agora)
        saida += r['ofertas']
        if not r['ofertas'] or r['proximo'] is None:
            return saida
        cursor = r['proximo']
    raise AssertionError('proximo nunca terminou')


def normalizar(texto):
    """Normalização independente da do disparo: NFKC, pontos parecidos e invisíveis (Cf) fora."""
    t = unicodedata.normalize('NFKC', texto).translate({0x3002: '.', 0xFF61: '.'})
    return ''.join(c for c in t if unicodedata.category(c) != 'Cf')


# Oráculo independente de "parece link": esquema, www. ou rótulo.tld (a detecção do disparo é mais conservadora).
_RE_PARECE_LINK = re.compile(r'(?i)(?:[a-z][a-z0-9+.-]*://|\bwww\.|[a-z0-9-]\.[a-z]{2,})')


def parece_link(texto):
    return bool(_RE_PARECE_LINK.search(normalizar(texto)))


def link_ok_oraculo(loja, url):
    """Regra do dono escrita de novo, sem usar o servidor.py nem o disparo.py."""
    if not isinstance(url, str) or any(c.isspace() or ord(c) < 32 for c in url):
        return False
    try:
        p = urllib.parse.urlsplit(url)
        porta = p.port
    except ValueError:
        return False
    if p.scheme != 'https' or p.username is not None or p.password is not None or porta not in (None, 443):
        return False
    if loja == 'ml':
        return p.hostname == 'meli.la' and len(p.path) > 1
    if loja == 'amazon':
        return p.hostname == 'www.amazon.com.br' and urllib.parse.parse_qs(p.query).get('tag') == [TAG]
    if loja == 'shopee':
        return re.fullmatch(r'https://s\.shopee\.com\.br/[A-Za-z0-9]+', url) is not None
    return False


CDN = {'amazon': 'm.media-amazon.com', 'ml': 'http2.mlstatic.com', 'shopee': 'down-br.img.susercontent.com'}


def imagem_ok_oraculo(loja, url):
    if url is None:
        return True
    p = urllib.parse.urlsplit(url)
    return p.scheme == 'https' and p.hostname == CDN[loja] and p.netloc == CDN[loja]


# ------------------------------------------------------------------ CA4: modelo aleatório do cursor
class ModeloDoCursor(T.Base):
    """Um consumidor que guarda o último `proximo` e volta a perguntar, enquanto a coleta grava."""

    def rodar_modelo(self, semente, passos=80):
        rng = random.Random(semente)
        relogio = datetime(2026, 11, 3, 10, 0, 0)
        ids = []
        vistas = []                # (id, atualizado_em) entregues, na ordem
        estado = {'cursor': None}

        def sondar():
            limite = rng.randint(1, 7)
            na_varredura = []
            for _ in range(500):
                qs = [('limite', str(limite))] + ([('cursor', estado['cursor'])] if estado['cursor'] else [])
                r = A.rota(self.con, 'GET', '/api/v1/ofertas', qs, AFILIADO, relogio)
                for o in r['ofertas']:
                    # folga: nada gravado há menos de 60 s sai
                    self.assertLessEqual(o['atualizado_em'], T.hora(relogio - timedelta(seconds=60)), f'semente {semente}')
                    vistas.append((o['id'], o['atualizado_em']))
                    na_varredura.append(o['id'])
                if not r['ofertas']:
                    break
                self.assertIsNotNone(r['proximo'], f'página com ofertas sem proximo, semente {semente}')
                estado['cursor'] = r['proximo']
            else:
                self.fail(f'varredura sem fim, semente {semente}')
            self.assertEqual(len(na_varredura), len(set(na_varredura)), f'id repetido numa varredura, semente {semente}')

        for _ in range(passos):
            op = rng.choices(['novo', 'atualiza', 'invalida', 'revalida', 'tick', 'sonda'], [4, 3, 1, 1, 4, 2])[0]
            agora_txt = T.hora(relogio)
            if op == 'novo':
                ids.append(self.gravar(atualizado_em=agora_txt, criado_em=agora_txt))
            elif op == 'atualiza' and ids:
                self.con.execute("UPDATE items SET preco='R$ 77,00', atualizado_em=? WHERE id=?",
                                 (agora_txt, rng.choice(ids)))
            elif op == 'invalida' and ids:
                self.con.execute("UPDATE items SET preco='', atualizado_em=? WHERE id=?",
                                 (agora_txt, rng.choice(ids)))
            elif op == 'revalida' and ids:
                self.con.execute("UPDATE items SET preco='R$ 55,00', atualizado_em=? WHERE id=?",
                                 (agora_txt, rng.choice(ids)))
            elif op == 'tick':
                relogio += timedelta(seconds=rng.choice((0, 0, 1, 3, 7, 13, 19, 30, 45)))
            elif op == 'sonda':
                sondar()
            self.con.commit()
        relogio += timedelta(seconds=120)
        sondar()
        self.assertEqual(len(vistas), len(set(vistas)), f'versão entregue duas vezes, semente {semente}')
        atuais = {(r['id'], r['atualizado_em']) for r in self.con.execute(
            "SELECT id, atualizado_em FROM items WHERE preco!=''")}
        faltou = atuais - set(vistas)
        self.assertFalse(faltou, f'versão atual nunca entregue, semente {semente}: {sorted(faltou)[:5]}')

    def test_ca4_modelo_aleatorio_cada_versao_chega_uma_vez_so(self):
        for semente in range(40):
            with self.subTest(semente=semente):
                self.con.execute('DELETE FROM items')
                self.con.commit()
                self.rodar_modelo(semente)

    def test_ca4_item_gravado_durante_a_leitura_so_vem_na_leitura_seguinte(self):
        ids = [self.gravar(atualizado_em=T.hora(AGORA - timedelta(minutes=10))) for _ in range(5)]
        r = self.ofertas('limite=3')
        self.assertEqual([o['id'] for o in r['ofertas']], ids[:3])
        # a coleta grava dois itens (um deles com o mesmo segundo do cursor) enquanto o consumidor lê
        durante = [self.gravar(atualizado_em=T.hora(AGORA - timedelta(seconds=5))),
                   self.gravar(atualizado_em=r['ofertas'][-1]['atualizado_em'])]
        resto = self.ofertas('limite=10&cursor=' + urllib.parse.quote(r['proximo']))
        # o segundo tem o horário do cursor mas id maior: pelo desempate (atualizado_em, id), vem agora e só agora
        self.assertEqual([o['id'] for o in resto['ofertas']], ids[3:] + [durante[1]])
        cursor = resto['proximo']
        depois = self.ofertas('limite=10&cursor=' + urllib.parse.quote(cursor), agora=AGORA + timedelta(seconds=56))
        self.assertEqual([o['id'] for o in depois['ofertas']], [durante[0]])
        outra = self.ofertas('limite=10&cursor=' + urllib.parse.quote(depois['proximo']), agora=AGORA + timedelta(hours=1))
        self.assertEqual(outra['ofertas'], [])

    def test_ca4_tamanhos_das_paginas_com_muitos_empates(self):
        total = 120
        ids = [self.gravar(atualizado_em=T.ANTIGO) for _ in range(total)]
        for limite in (1, 7, 60, 119, 120, 121, 200):
            with self.subTest(limite=limite):
                paginas, cursor = [], None
                for _ in range(total + 2):
                    qs = f'limite={limite}' + (('&cursor=' + urllib.parse.quote(cursor)) if cursor else '')
                    r = self.ofertas(qs)
                    if not r['ofertas']:
                        break
                    paginas.append([o['id'] for o in r['ofertas']])
                    self.assertIsNotNone(r['proximo'], 'página com ofertas sem proximo')
                    cursor = r['proximo']
                else:
                    self.fail('proximo nunca levou a uma página vazia')
                self.assertEqual([i for p in paginas for i in p], ids)
                self.assertTrue(all(len(p) == limite for p in paginas[:-1]), 'página cheia no meio da varredura')
                self.assertEqual(len(paginas), math.ceil(total / limite))

    def test_ca4_ids_fora_de_ordem_em_relacao_ao_horario(self):
        # ids altos com horário antigo e ids baixos com horário novo: a ordem é por (horário, id), não por id
        a = self.gravar(atualizado_em='2026-11-03T12:00:03')
        b = self.gravar(atualizado_em='2026-11-03T12:00:01')
        c = self.gravar(atualizado_em='2026-11-03T12:00:03')
        d = self.gravar(atualizado_em='2026-11-03T12:00:02')
        for limite in (1, 2, 3, 4):
            with self.subTest(limite=limite):
                vistos, _, _ = self.percorrer(f'limite={limite}')
                self.assertEqual(vistos, [b, d, a, c])

    def test_ca4_escrita_concorrente_com_relogio_real_nao_perde_nem_repete(self):
        velho = T.hora(datetime.now() - timedelta(hours=2))
        antigos = [self.gravar(atualizado_em=velho) for _ in range(40)]
        parar = threading.Event()
        erros = []

        def escritor():
            con = T.abrir(self.caminho)
            try:
                n = 0
                while not parar.is_set():
                    n += 1
                    agora = T.hora(datetime.now())
                    con.execute("INSERT INTO items (loja,item_id,cat,busca,url,titulo,preco,tem_dados,posicao,"
                                "criado_em,atualizado_em) VALUES ('amazon',?,?,?,?,?,?,1,?,?,?)",
                                (f'B0CONC{n:05d}', PERFUMES, 'perfume',
                                 f'https://www.amazon.com.br/dp/B0CONC{n:05d}?tag={TAG}', f'Perfume concorrente {n}',
                                 'R$ 10,00', n, agora, agora))
                    con.commit()
                    time.sleep(0.001)
            except Exception as e:   # noqa: BLE001
                erros.append(repr(e))
            finally:
                con.close()

        th = threading.Thread(target=escritor)
        th.start()
        try:
            leitor = T.abrir(self.caminho, so_leitura=True)
            vistos, totais, cursor = [], set(), None
            for _ in range(60):
                qs = [('limite', '3')] + ([('cursor', cursor)] if cursor else [])
                r = A.rota(leitor, 'GET', '/api/v1/ofertas', qs, AFILIADO, datetime.now())
                vistos += [o['id'] for o in r['ofertas']]
                totais.add(r['total'])
                if not r['ofertas']:
                    break
                cursor = r['proximo']
                time.sleep(0.01)   # dá tempo ao escritor de gravar entre uma página e outra
            leitor.close()
        finally:
            parar.set()
            th.join(10)
        self.assertEqual(erros, [])
        self.assertEqual(vistos, antigos)       # nenhum dos itens novos (na folga) aparece; nenhum antigo se perde
        self.assertEqual(totais, {40})
        escritos = self.con.execute('SELECT COUNT(*) FROM items').fetchone()[0]
        self.assertGreater(escritos, 45, 'o escritor não rodou durante a leitura')


# ------------------------------------------------------------------ CA3/CA4: paridade com o disparo
class ParidadeComODisparo(T.Base):
    TITULOS = ['Perfume Ácido Café 100ml', 'CAFÉ solúvel', 'cafe moido', 'Ração ÇÃO premium', 'Maçã verde',
               'STRASSE importada', 'Fone de ouvido bluetooth', 'Perfume masculino 100ml', 'Ônibus de brinquedo',
               'Conjunto Faqueiro 24 peças']

    def test_ca3_q_equivale_a_regra_palavras_do_disparo(self):
        for t in self.TITULOS:
            self.gravar(titulo=t)
        for q in ('cafe', 'CAFÉ', 'maca', 'maçã,fone', 'perfume , ração', 'onibus', 'straße', 'ç', 'verde,nada',
                  'PERFUME,perfume', ' cafe ', 'a'):
            with self.subTest(q=q):
                regra = {'cats': [PERFUMES], 'lojas': list(D.LOJAS), 'numero_id': -1, 'repetir_apos_dias': 7,
                         'desconto_min': 0, 'palavras': [p.strip() for p in q.split(',')]}
                esperado = sorted(it['id'] for it in D.elegiveis(self.con, regra, AGORA, AFILIADO))
                obtido = sorted(self.ids('limite=200&ordem=relevancia&q=' + urllib.parse.quote(q)))
                self.assertEqual(obtido, esperado)

    def test_ca4_todas_as_ordens_paginadas_com_limites_variados(self):
        rng = random.Random(11)
        for _ in range(60):
            self.gravar(rng.choice(D.LOJAS), preco=rng.choice(('R$ 10,00', 'R$ 99,90', 'R$ 1.899', 'R$ 99,90')),
                        desconto=rng.choice(('', '-5%', '-30%', '-30%')),
                        vendas=rng.choice(('', 'Mais de 1 mil compras', '+50 vendidos')),
                        cupom=rng.choice(('', 'Cupom 10%')), posicao=rng.randint(1, 8),
                        criado_em=rng.choice((T.ANTIGO, '2026-11-01T08:00:00')))
        regra = {'cats': [PERFUMES], 'lojas': list(D.LOJAS), 'numero_id': -1, 'repetir_apos_dias': 7,
                 'desconto_min': 0, 'palavras': []}
        base = sorted(D.elegiveis(self.con, regra, AGORA, AFILIADO), key=lambda it: it['id'])
        self.assertEqual(len(base), 60)
        for ordem in ('relevancia', 'desconto', 'menor_preco', 'maior_preco', 'cupom', 'recentes'):
            esperado = [it['id'] for it in D.ordenar(base, ordem)]
            for limite in (1, 7, 13, 59, 60, 61, 200):
                with self.subTest(ordem=ordem, limite=limite):
                    vistos, _, totais = self.percorrer(f'ordem={ordem}&limite={limite}')
                    self.assertEqual(vistos, esperado)
                    self.assertEqual(totais, {60})

    def test_ca3_desconto_min_so_deixa_quem_mostra_o_desconto(self):
        rng = random.Random(4)
        for _ in range(40):
            self.gravar(desconto=rng.choice(('', '-10%', '-50%', '-99%')), preco_antigo=rng.choice(('', 'R$ 200,00')),
                        preco='R$ 100,00')
        todos = varrer(self.con)
        for minimo in (0, 1, 10, 11, 49, 50, 51, 99):
            with self.subTest(minimo=minimo):
                obtidas = varrer(self.con, [('desconto_min', str(minimo))])
                self.assertEqual([o['id'] for o in obtidas], [o['id'] for o in todos if o['desconto_pct'] >= minimo])


# ------------------------------------------------------------------ CA5: categorias x ofertas
class CategoriasBatemComAsOfertas(T.Base):
    def test_ca5_soma_igual_a_seguir_o_cursor_e_cada_aba_igual_ao_filtro(self):
        rng = random.Random(8)
        cats = [PERFUMES, CASA, 'Black Friday | Eletrônicos', 'Eletrodomésticos']
        for _ in range(150):
            loja = rng.choice(D.LOJAS)
            campos = {'cat': rng.choice(cats), 'atualizado_em': rng.choice((T.ANTIGO, '2026-11-02T09:00:00'))}
            if rng.random() < 0.15:
                campos['titulo'] = 'Capinha i.Phone 15'
            if rng.random() < 0.1:
                campos['preco'] = rng.choice(('', 'Consulte', 'R$ 0,00'))
            if rng.random() < 0.1 and loja == 'ml':
                campos['url'] = 'https://produto.mercadolivre.com.br/MLB-1'
            self.gravar(loja, **campos)
        resp = self.cats()
        todas = varrer(self.con)
        self.assertEqual(resp['total'], len(todas))
        self.assertEqual(resp['total'], sum(c['total'] for c in resp['categorias']))
        self.assertEqual(resp['total'], self.ofertas('limite=1', agora=DEPOIS)['total'])
        self.assertEqual(len({o['id'] for o in todas}), len(todas))
        for c in resp['categorias']:
            with self.subTest(aba=c['nome']):
                da_aba = varrer(self.con, [('cat', c['nome'])])
                self.assertEqual(len(da_aba), c['total'])
                self.assertEqual(c['total'], sum(c['lojas'].values()))
                for loja, n in c['lojas'].items():
                    self.assertEqual(len(varrer(self.con, [('cat', c['nome']), ('loja', loja)])), n)
        # a ordem não muda o conjunto
        self.assertEqual({o['id'] for o in varrer(self.con, ordem='relevancia')}, {o['id'] for o in todas})


# ------------------------------------------------------------------ CA2: dados hostis
class SoSaiOQueDeveFuzz(T.Base):
    TITULOS_OK = ['Perfume Importado 100ml', 'Smart TV 55" 4K UHD', 'Fone Bluetooth Wi-Fi 6 Pro',
                  'Cafeteira Elétrica 15 Xícaras 4.8 de 5', 'Dr. Pepper Zero 350ml', 'Kit 3 un. Toalha de Banho',
                  'Notebook 15,6" Core i5 8GB, R$ 1.249,90']
    TITULOS_RUINS = ['Capinha i.Phone 15', 'Veja em golpe.com', 'acesse WWW.golpe.com.br agora',
                     'https://evil.example/x', 'http://evil.example', 'compre em golpe⒈com', 'exemplo。com.br',
                     'x​.com.br', 'GOLPE.COM/promo', 'ftp://evil.example/a', 'x@golpe.com', 'promoção.com',
                     'Carregador 50W.Original']
    CUPONS_OK = ['', '', 'Aplicar Cupom de 10%   Ver itens']
    CUPONS_RUINS = ['https://evil.example', 'use golpe.com', 'www.golpe.com.br']
    CATS_OK = [PERFUMES, CASA, 'Black Friday | Eletrônicos']
    CATS_RUINS = ['www.golpe.com', 'Perfumes.promo']
    BUSCAS_OK = ['perfume importado', 'tv 55 4k']
    BUSCAS_RUINS = ['golpe.com/promo', 'https://evil.example']
    IDS_RUINS = ['https://evil.example/x', 'evil.example']   # o montar() acrescenta /<n> para ficar único
    PRECOS_OK = ['R$ 10,00', 'R$ 1.899', 'R$99,99']
    PRECOS_RUINS = ['', 'Consulte', 'R$ 0,00', '0', 'R$ ' + '9' * 400]
    LINKS_RUINS = [
        'https://www.amazon.com.br/dp/B0X?tag=outro-20', 'https://www.amazon.com.br/dp/B0X',
        f'https://www.amazon.com.br/dp/B0X?tag={TAG}&tag=outro-20', f'http://www.amazon.com.br/dp/B0X?tag={TAG}',
        f'https://www.amazon.com.br.evil.example/dp/B0X?tag={TAG}', 'https://evil.example/?u=https://meli.la/abc',
        'https://meli.la.evil.example/abc', 'https://meli.la/', 'https://user@meli.la/abc',
        'https://meli.la:8443/abc', 'https://meli.la/ab c', 'https://meli.la/abc\n',
        'https://produto.mercadolivre.com.br/MLB-1', 'https://s.shopee.com.br/abc?x=1',
        'https://shopee.com.br/produto-i.1.2', 'https://s.shopee.com.br/', '', 'javascript:alert(1)', 'meli.la/abc',
        f'https://user:senha@www.amazon.com.br/dp/B0X?tag={TAG}']
    IMAGENS_RUINS = [
        'http://m.media-amazon.com/a.jpg', 'https://m.media-amazon.com.evil.example/a.jpg',
        'https://evil.example/m.media-amazon.com/a.jpg', 'https://user@m.media-amazon.com/a.jpg',
        'https://m.media-amazon.com:444/a.jpg', '//m.media-amazon.com/a.jpg', 'javascript:alert(1)',
        'data:image/png;base64,AAAA', '', 'https://http2.mlstatic.com/D_1.jpg',
        'https://down-br.img.susercontent.com/file/x', 'https://evil.example/a.jpg']

    def test_o_oraculo_nao_e_cego(self):
        for t in self.TITULOS_RUINS + self.CUPONS_RUINS[:] + self.CATS_RUINS + self.BUSCAS_RUINS + self.IDS_RUINS:
            self.assertTrue(parece_link(t), t)
        for t in self.TITULOS_OK + ['', 'Aplicar Cupom de 10%   Ver itens', PERFUMES, CASA, 'tv 55 4k']:
            self.assertFalse(parece_link(t), t)
        for loja in D.LOJAS:
            for u in self.LINKS_RUINS:
                self.assertFalse(link_ok_oraculo(loja, u), (loja, u))

    def montar(self, rng, n):
        """Grava n itens misturando componentes bons e hostis. Devolve {id: bom_por_construcao}."""
        bons = {}
        for k in range(n):
            loja = rng.choice(D.LOJAS)
            bom_link = rng.random() < 0.6
            link_bom = {'amazon': f'https://www.amazon.com.br/dp/B0F{k:06d}?tag={TAG}',
                        'ml': f'https://meli.la/F{k}x', 'shopee': f'https://s.shopee.com.br/F{k}x'}[loja]
            outro_bom = {'amazon': 'https://meli.la/Zzz', 'ml': f'https://www.amazon.com.br/dp/B0X?tag={TAG}',
                         'shopee': 'https://meli.la/Zzz'}[loja]   # afiliado, mas de outra loja
            url = link_bom if bom_link else rng.choice(self.LINKS_RUINS + [outro_bom, outro_bom])
            titulo_bom, cupom_bom, cat_bom = rng.random() < .75, rng.random() < .8, rng.random() < .9
            busca_bom, id_bom, preco_bom = rng.random() < .9, rng.random() < .9, rng.random() < .85
            imagem_boa = rng.random() < .6
            campos = {
                'url': url, 'item_id': f'F{k:06d}' if id_bom else f'{rng.choice(self.IDS_RUINS)}/{k}',
                'titulo': rng.choice(self.TITULOS_OK) if titulo_bom else rng.choice(self.TITULOS_RUINS),
                'cupom': rng.choice(self.CUPONS_OK) if cupom_bom else rng.choice(self.CUPONS_RUINS),
                'cat': rng.choice(self.CATS_OK) if cat_bom else rng.choice(self.CATS_RUINS),
                'busca': rng.choice(self.BUSCAS_OK) if busca_bom else rng.choice(self.BUSCAS_RUINS),
                'preco': rng.choice(self.PRECOS_OK) if preco_bom else rng.choice(self.PRECOS_RUINS),
                'imagem': ('https://' + CDN[loja] + f'/img/{k}.jpg') if imagem_boa else rng.choice(self.IMAGENS_RUINS),
            }
            i = self.gravar(loja, **campos)
            bons[i] = bom_link and titulo_bom and cupom_bom and cat_bom and busca_bom and id_bom and preco_bom
        return bons

    def test_ca2_so_sai_oferta_que_passa_no_oraculo_e_toda_oferta_boa_sai(self):
        for semente in (1, 2, 3):
            with self.subTest(semente=semente):
                self.con.execute('DELETE FROM items')
                self.con.commit()
                bons = self.montar(random.Random(semente), 160)
                self.assertGreater(sum(bons.values()), 10)
                self.assertLess(sum(bons.values()), 160)
                linhas = {r['id']: r for r in self.con.execute('SELECT * FROM items')}
                saidas = varrer(self.con)
                ids_saida = {o['id'] for o in saidas}
                self.assertEqual(len(ids_saida), len(saidas))
                self.assertFalse({i for i, bom in bons.items() if bom} - ids_saida, 'oferta boa ficou de fora')
                for o in saidas:
                    r = linhas[o['id']]
                    self.assertTrue(link_ok_oraculo(o['loja'], o['link']), o['link'])
                    self.assertTrue(imagem_ok_oraculo(o['loja'], o['imagem']), o['imagem'])
                    self.assertGreater(o['preco'], 0)
                    for campo in ('titulo', 'cupom', 'categoria', 'busca'):
                        self.assertFalse(parece_link(o[campo]), (campo, o[campo]))
                    self.assertFalse(o['item_id'] != o['link'] and parece_link(o['item_id']), o['item_id'])
                    self.assertEqual(o['chave'], f"{o['loja']}:{o['item_id']}")
                    # a foto boa da própria loja sai como veio; qualquer outra vira null
                    boa = bool(r['imagem']) and imagem_ok_oraculo(o['loja'], r['imagem'])
                    self.assertEqual(o['imagem'], r['imagem'] if boa else None)
                # nenhum texto estranho no corpo: tirados link e imagem, não sobra URL nenhum
                for o in saidas:
                    resto = {k: v for k, v in o.items() if k not in ('link', 'imagem', 'item_id', 'chave')}
                    for v in resto.values():
                        if isinstance(v, str):
                            self.assertFalse(parece_link(v), v)
                for c in self.cats()['categorias']:
                    self.assertFalse(parece_link(c['nome']), c['nome'])

    def test_ca2_titulos_legitimos_nao_sao_barrados_a_toa(self):
        for t in self.TITULOS_OK:
            self.gravar(titulo=t)
        self.assertEqual({o['titulo'] for o in varrer(self.con)}, set(self.TITULOS_OK))


# ------------------------------------------------------------------ dados reais (cópia do banco real)
def copiar_banco_real(destino):
    """sqlite3.backup com origem em mode=ro: o banco real nunca é gravado. Devolve False se não der."""
    if not os.path.exists(TS.DB_REAL):
        return False
    try:
        origem = sqlite3.connect(f'file:{TS.DB_REAL}?mode=ro', uri=True, timeout=30)
    except sqlite3.Error:
        return False
    try:
        copia = sqlite3.connect(destino)
        try:
            origem.backup(copia)
        finally:
            copia.close()
    except sqlite3.Error:
        return False
    finally:
        origem.close()
    return True


class DadosReais(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix='achadinhos-api-real-')
        cls.addClassCleanup(shutil.rmtree, cls.dir, ignore_errors=True)
        cls.caminho = os.path.join(cls.dir, 'copia.db')
        if not copiar_banco_real(cls.caminho):
            raise unittest.SkipTest('sem achadinhos.db legível neste checkout: os testes de dados reais precisam dele')
        cls.con = T.abrir(cls.caminho, so_leitura=True)
        cls.addClassCleanup(cls.con.close)
        cls.linhas = cls.con.execute('SELECT COUNT(*) FROM items').fetchone()[0]
        cls.todas = varrer(cls.con)

    def test_a_copia_tem_dados_de_verdade(self):
        self.assertGreater(self.linhas, 1000)
        self.assertGreater(len(self.todas), 1000)

    def test_ca2_toda_oferta_real_passa_no_link_da_loja_e_no_oraculo(self):
        for o in self.todas:
            self.assertTrue(D.link_da_loja_ok(o['loja'], o['link'], AFILIADO), o['chave'])
            self.assertTrue(link_ok_oraculo(o['loja'], o['link']), o['chave'])
            self.assertTrue(imagem_ok_oraculo(o['loja'], o['imagem']), o['chave'])
            self.assertTrue(D.imagem_permitida(o['imagem'], o['loja']) or o['imagem'] is None, o['chave'])
            self.assertGreater(o['preco'], 0, o['chave'])
            for campo in ('titulo', 'cupom', 'categoria', 'busca'):
                self.assertEqual(D.urls_da_mensagem(o[campo]), [], (o['chave'], campo))
                self.assertFalse(parece_link(o[campo]), (o['chave'], campo))

    def test_ca2_o_que_fica_de_fora_tem_motivo(self):
        sairam = {o['id'] for o in self.todas}
        fora = [r for r in self.con.execute('SELECT * FROM items') if r['id'] not in sairam]
        for r in fora:
            motivos = []
            if r['tem_dados'] != 1:
                motivos.append('sem dados')
            if D.preco_num(r['preco']) <= 0:
                motivos.append('preço')
            if not D.link_da_loja_ok(r['loja'], r['url'], AFILIADO):
                motivos.append('link')
            if any(D.urls_da_mensagem(r[c] or '') for c in ('titulo', 'cupom', 'cat', 'busca')):
                motivos.append('texto com cara de link')
            self.assertTrue(motivos, f'item {r["id"]} ficou de fora sem motivo')
        # e o que sai tem preço e link bons: nenhum item sem preço escapou
        sem_preco = {r['id'] for r in self.con.execute('SELECT * FROM items') if D.preco_num(r['preco']) <= 0}
        self.assertFalse(sem_preco & sairam)

    def test_ca1_numeros_reais_batem_com_o_texto_cru_lido_por_um_segundo_parser(self):
        """Preço, desconto, vendas, nota e nº de avaliações lidos de novo, sem usar o disparo.py."""
        def reais(t):
            m = re.fullmatch(r'R\$ ?(\d{1,3}(?:\.\d{3})*)(?:,(\d{2}))?', t)
            return float(m.group(1).replace('.', '') + '.' + (m.group(2) or '0')) if m else None

        def contagem(t):
            m = re.search(r'(\d[\d.,]*)( mil)?', t)
            if not m:
                return 0
            n = m.group(1).rstrip('.,')
            return round(float(n.replace(',', '.')) * 1000) if m.group(2) else int(n.replace('.', '').replace(',', ''))

        linhas = {r['id']: r for r in self.con.execute('SELECT * FROM items')}
        for o in self.todas:
            r = linhas[o['id']]
            ctx = o['chave']
            self.assertEqual(o['preco'], reais(r['preco']), ctx)
            antigo = reais(r['preco_antigo']) if r['preco_antigo'] else None
            self.assertEqual(o['preco_antigo'], antigo if antigo and antigo > o['preco'] else None, ctx)
            m = re.fullmatch(r'-(\d{1,3})%', r['desconto']) if r['desconto'] else None
            if m and int(m.group(1)) > 0:
                self.assertEqual(o['desconto_pct'], int(m.group(1)), ctx)
            elif o['preco_antigo']:
                self.assertEqual(o['desconto_pct'], round((1 - o['preco'] / o['preco_antigo']) * 100), ctx)
            else:
                self.assertEqual(o['desconto_pct'], 0, ctx)
            self.assertEqual(o['vendas'], contagem(r['vendas']), (ctx, r['vendas']))
            self.assertEqual(o['num_avaliacoes'], contagem(r['num_avaliacoes'].strip('()')), (ctx, r['num_avaliacoes']))
            nota = re.match(r'(\d+(?:[.,]\d+)?)', r['avaliacao'])
            self.assertEqual(o['avaliacao'], float(nota.group(1).replace(',', '.')) if nota else None, ctx)
            self.assertEqual(o['frete_gratis'], 'gr\u00e1tis' in r['frete'].lower(), ctx)
            self.assertEqual((o['titulo'], o['link'], o['cupom'], o['categoria'], o['busca'], o['item_id']),
                             (r['titulo'], r['url'], r['cupom'], r['cat'], r['busca'], r['item_id']), ctx)

    def test_ca5_soma_das_categorias_bate_com_seguir_o_cursor_ate_o_fim(self):
        resp = A.rota(self.con, 'GET', '/api/v1/categorias', [], AFILIADO)
        self.assertEqual(resp['total'], len(self.todas))
        self.assertEqual(sum(c['total'] for c in resp['categorias']), len(self.todas))
        por_aba = {}
        for o in self.todas:
            por_aba.setdefault(o['categoria'], dict.fromkeys(D.LOJAS, 0))[o['loja']] += 1
        self.assertEqual({c['nome']: c['lojas'] for c in resp['categorias']}, por_aba)
        self.assertEqual(len({o['id'] for o in self.todas}), len(self.todas))
        nomes = [c['nome'] for c in resp['categorias']]
        self.assertEqual(nomes, sorted(nomes, key=lambda n: (D._sem_acento(n), n)))

    def test_ca4_ordem_atualizacao_e_total_do_filtro_na_primeira_pagina(self):
        r = A.rota(self.con, 'GET', '/api/v1/ofertas', [('limite', '1')], AFILIADO, DEPOIS)
        self.assertEqual(r['total'], len(self.todas))
        chaves = [(o['atualizado_em'], o['id']) for o in self.todas]
        self.assertEqual(chaves, sorted(chaves))

    def test_ca4_ordens_por_deslocamento_batem_com_o_disparo_nos_dados_reais(self):
        cats = sorted({o['categoria'] for o in self.todas})
        regra = {'cats': cats, 'lojas': list(D.LOJAS), 'numero_id': -1, 'repetir_apos_dias': 7,
                 'desconto_min': 0, 'palavras': []}
        sairam = {o['id'] for o in self.todas}
        base = sorted((it for it in D.elegiveis(self.con, regra, AGORA, AFILIADO) if it['id'] in sairam),
                      key=lambda it: it['id'])
        self.assertEqual(len(base), len(self.todas))
        n = len(base)
        # primeira, do meio e última página (um pedido recalcula a lista inteira: varrer tudo levaria minutos)
        for ordem in ('relevancia', 'desconto', 'menor_preco', 'maior_preco', 'cupom', 'recentes'):
            esperado = [it['id'] for it in D.ordenar(base, ordem)]
            for inicio in (0, (n // 2) // 200 * 200, (n - 1) // 200 * 200):
                with self.subTest(ordem=ordem, inicio=inicio):
                    pares = [('limite', '200'), ('ordem', ordem)] + ([('cursor', str(inicio))] if inicio else [])
                    r = A.rota(self.con, 'GET', '/api/v1/ofertas', pares, AFILIADO, DEPOIS)
                    self.assertEqual([o['id'] for o in r['ofertas']], esperado[inicio:inicio + 200])
                    self.assertEqual(r['total'], n)
                    self.assertEqual(r['proximo'], str(inicio + 200) if inicio + 200 < n else None)

    def test_ca4_filtros_na_cadeia_real(self):
        loja_cat = self.todas[0]
        parcial = varrer(self.con, [('cat', loja_cat['categoria']), ('loja', loja_cat['loja'])])
        self.assertEqual({o['id'] for o in parcial},
                         {o['id'] for o in self.todas if o['categoria'] == loja_cat['categoria'] and o['loja'] == loja_cat['loja']})
        grandes = varrer(self.con, [('desconto_min', '50')])
        self.assertEqual({o['id'] for o in grandes}, {o['id'] for o in self.todas if o['desconto_pct'] >= 50})

    def test_ca9_a_leitura_nao_gravou_nada_na_copia(self):
        escrita = sqlite3.connect(self.caminho)
        try:
            self.assertEqual(escrita.execute('PRAGMA user_version').fetchone()[0],
                             self.con.execute('PRAGMA user_version').fetchone()[0])
        finally:
            escrita.close()

    def test_o_tempo_de_um_pedido_fica_longe_de_estourar(self):
        # medição do plano (item do seguranca): ~0,5 s no banco real de 8 mil itens; o teto é folgado de propósito
        for ordem in (None, 'relevancia'):
            t0 = time.monotonic()
            A.rota(self.con, 'GET', '/api/v1/ofertas', [('limite', '200')] + ([('ordem', ordem)] if ordem else []),
                   AFILIADO, DEPOIS)
            self.assertLess(time.monotonic() - t0, 5.0, ordem)
        t0 = time.monotonic()
        A.rota(self.con, 'GET', '/api/v1/categorias', [], AFILIADO)
        self.assertLess(time.monotonic() - t0, 5.0)


# ------------------------------------------------------------------ HTTP
class ServidorQa(TS2.ServidorApi):
    """Como o ServidorApi do dev, mas com ganchos para preparar o banco antes e depois da subida."""

    @classmethod
    def antes_de_subir(cls):
        """Banco já existente na hora em que o servidor sobe (padrão: nenhum)."""

    @classmethod
    def depois_de_subir(cls):
        con = sqlite3.connect(cls.db)
        TS2.inserir(con)
        TS2.inserir(con, loja='ml', item_id='MLB4100000001', cat=CASA, url=TS2.LINK_ML, titulo='Luminária de mesa',
                    preco='R$ 59,90', imagem='https://http2.mlstatic.com/D_teste.jpg', posicao=2)
        con.commit()
        con.close()

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix='achadinhos-api-qa-')
        cls.addClassCleanup(shutil.rmtree, cls.dir, ignore_errors=True)
        cls.db = os.path.join(cls.dir, 'teste.db')
        cls.arquivo_token = os.path.join(cls.dir, 'api_token.txt')
        cls.token = cls.TOKEN() if hasattr(cls, 'TOKEN') else __import__('secrets').token_urlsafe(32)
        conteudo = cls.CONTEUDO(cls.token)
        if conteudo is not None:
            TS2.gravar_token(cls.arquivo_token, conteudo, cls.MODO)
        cls.antes_de_subir()
        cls.porta = TS.porta_livre()
        cls.log_err = open(os.path.join(cls.dir, 'stderr.log'), 'wb')
        cls.addClassCleanup(cls.log_err.close)
        env = TS.ambiente(cls.db, cls.porta)
        env.update({TS2.VAR_TOKEN: cls.arquivo_token, 'ACHADINHOS_DISPARO': '0'})
        cls.proc = subprocess.Popen([sys.executable, '-u', 'servidor.py'], cwd=TS.RAIZ, env=env,
                                    stdout=subprocess.PIPE, stderr=cls.log_err)
        cls.addClassCleanup(cls.parar_servidor)
        cls.primeira_linha = cls.proc.stdout.readline().decode()
        for _ in range(100):
            try:
                socket.create_connection(('127.0.0.1', cls.porta), timeout=0.2).close()
                break
            except OSError:
                if cls.proc.poll() is not None:
                    break
                time.sleep(0.05)
        if cls.proc.poll() is not None:
            raise RuntimeError('o servidor de teste saiu: ' + cls.primeira_linha)
        cls.depois_de_subir()


class TestHttpComVariacoesDeCaminho(ServidorQa):
    ROTAS_OK = ('/api/v1/ofertas', '/api/v1/categorias')

    def test_ca6_variacoes_de_caminho_sem_token_nunca_dao_200_nem_vazam(self):
        variacoes = ['/api/v1/ofertas', '/api/v1/ofertas/', '/api/v1/ofertas?', '/api/v1/ofertas?limite=1',
                     '//api/v1/ofertas', '/api/v1/ofertas;x', '/api/v1/ofertas%00', '/api/v1/%6ffertas',
                     '/api/v1/ofertas%2F', '/api/v1%2Fofertas', '/api/%76%31/ofertas', '/api/v1/../v1/ofertas',
                     '/api/v1/./ofertas', '/api//v1/ofertas', '/API/V1/ofertas', '/api/v1/OFERTAS',
                     '/api/v1/categorias', '/api/v1/categorias/', '/api/v1', '/api/v1/',
                     f'http://localhost:{self.porta}/api/v1/ofertas']
        for caminho in variacoes:
            with self.subTest(caminho=caminho):
                r = self.cru(f'GET {caminho} HTTP/1.1\r\nHost: localhost:{self.porta}\r\n\r\n'.encode())
                linha = r.split(b'\r\n', 1)[0]
                self.assertNotIn(b' 200 ', linha)
                self.assertNotIn(b'"ofertas"', r)
                self.assertNotIn(b'"categorias"', r)
                self.assertNotIn(b'B0TESTE001', r)

    def test_ca6_com_token_so_as_duas_rotas_certas_respondem_200(self):
        for caminho in ('/api/v1/ofertas', '/api/v1/categorias', '/api/v1/ofertas?', '//api/v1/ofertas'):
            with self.subTest(caminho=caminho):
                r = self.cru(f'GET {caminho} HTTP/1.1\r\nHost: localhost:{self.porta}\r\n'
                             f'Authorization: Bearer {self.token}\r\n\r\n'.encode())
                self.assertTrue(r.startswith(b'HTTP/1.0 200'), r[:30])
        for caminho in ('/api/v1/ofertas/', '/api/v1/OFERTAS', '/api/v1/%6ffertas', '/api/v1/ofertas%2F', '/api/v1',
                        '/api/v1/ofertas;x', '/api/v1/../v1/ofertas', '/api/v1/./ofertas'):
            with self.subTest(caminho=caminho):
                r = self.cru(f'GET {caminho} HTTP/1.1\r\nHost: localhost:{self.porta}\r\n'
                             f'Authorization: Bearer {self.token}\r\n\r\n'.encode())
                self.assertTrue(r.startswith(b'HTTP/1.0 404'), (caminho, r[:30]))

    def test_ca7_pedido_de_navegador_com_token_certo_nunca_recebe_dado(self):
        for cab in ('Origin: http://localhost:%d', 'Origin: https://lista.mercadolivre.com.br', 'Origin: null',
                    'Sec-Fetch-Site: same-origin', 'Sec-Fetch-Site: cross-site', 'Sec-Fetch-Site: none',
                    'Sec-Fetch-Mode: navigate\r\nSec-Fetch-Site: same-site'):
            for caminho in self.ROTAS_OK:
                with self.subTest(cabecalho=cab, caminho=caminho):
                    r = self.cru((f'GET {caminho} HTTP/1.1\r\nHost: localhost:{self.porta}\r\n'
                                  f'Authorization: Bearer {self.token}\r\n' + (cab % self.porta if '%d' in cab else cab)
                                  + '\r\n\r\n').encode())
                    self.assertTrue(r.startswith(b'HTTP/1.0 403'), r[:30])
                    self.assertNotIn(b'"ofertas"', r)
                    self.assertNotIn(b'ccess-Control-', r)

    def test_ca7_sec_fetch_mode_do_fetch_do_node_sozinho_nao_barra(self):
        # o undici manda Sec-Fetch-Mode: cors sem Sec-Fetch-Site nem Origin: tem que passar (é o cliente real)
        st, _, j = self.v1('/api/v1/categorias', self.auth(**{'Sec-Fetch-Mode': 'cors'}))
        self.assertEqual(st, 200, j)

    def test_ca7_nenhuma_resposta_v1_leva_cors_nem_vary_origin_em_nenhum_status(self):
        casos = [('GET', '/api/v1/ofertas', self.auth()), ('GET', '/api/v1/ofertas?limite=0', self.auth()),
                 ('GET', '/api/v1/ofertas', {}), ('GET', '/api/v1/ofertas', self.auth(Origin='https://lista.mercadolivre.com.br')),
                 ('GET', '/api/v1/nada', self.auth()), ('POST', '/api/v1/ofertas', self.auth()),
                 ('OPTIONS', '/api/v1/ofertas', self.auth()), ('HEAD', '/api/v1/ofertas', self.auth())]
        vistos = set()
        for metodo, caminho, cab in casos:
            st, hd, _ = self.pedir(metodo, caminho, headers=cab)
            vistos.add(st)
            self.assertFalse([k for k in hd if k.lower().startswith('access-control-')], (metodo, caminho, st))
            self.assertIsNone(hd.get('Vary'), (metodo, caminho, st))
        self.assertEqual(vistos, {200, 400, 401, 403, 404, 405})

    def test_ca6_resposta_v1_nao_vai_para_cache(self):
        _, hd, _ = self.v1('/api/v1/categorias', self.auth())
        self.assertEqual(hd.get('Cache-Control'), 'no-store')

    def test_ca7_post_com_corpo_grande_recebe_405_e_o_servidor_segue_de_pe(self):
        # 100 KB cabem no buffer do socket: o cliente chega a ler o 405 (ver o relatório sobre corpos de MBs)
        corpo = b'x' * 100_000
        r = self.cru((f'POST /api/v1/ofertas HTTP/1.1\r\nHost: localhost:{self.porta}\r\n'
                      f'Authorization: Bearer {self.token}\r\nContent-Type: application/json\r\n'
                      f'Content-Length: {len(corpo)}\r\n\r\n').encode() + corpo)
        self.assertTrue(r.startswith(b'HTTP/1.0 405'), r[:30])
        st, _, _ = self.v1('/api/v1/categorias', self.auth())
        self.assertEqual(st, 200)

    def test_ca6_cabecalho_authorization_enorme_nao_derruba_nem_vai_para_o_log(self):
        r = self.cru((f'GET /api/v1/ofertas HTTP/1.1\r\nHost: localhost:{self.porta}\r\n'
                      f'Authorization: Bearer {"A" * 70000}\r\n\r\n').encode())
        self.assertRegex(r.split(b'\r\n', 1)[0], rb'^HTTP/1\.[01] (4\d\d)')
        st, _, _ = self.v1('/api/v1/categorias', self.auth())
        self.assertEqual(st, 200)
        self.assertNotIn('AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA', self.saida())

    def test_ca6_a_v1_so_responde_json_com_utf8(self):
        for caminho in ('/api/v1/ofertas', '/api/v1/categorias'):
            st, hd, corpo = self.v1(caminho, self.auth())
            self.assertEqual(st, 200)
            self.assertEqual(hd.get('Content-Type'), 'application/json; charset=utf-8')
            self.assertEqual(hd.get('X-Frame-Options'), 'SAMEORIGIN')


class TestHttpSimultaneo(ServidorQa):
    def test_leitores_e_gravador_ao_mesmo_tempo_sem_erro_e_sem_perder_item(self):
        # 3 leitores + 1 gravador (o backlog do ThreadingHTTPServer é 5: mais que isso dá ConnectionReset)
        antes = self.v1('/api/v1/ofertas?limite=200', self.auth())[2]
        self.assertEqual(antes['total'], 2)
        resultados, erros = [], []
        gravados = 12

        def leitor(n):
            try:
                for i in range(15):
                    caminho = ('/api/v1/ofertas?limite=2' if i % 3 else '/api/v1/categorias') if n else '/api/v1/ofertas?ordem=relevancia'
                    st, _, j = self.v1(caminho, self.auth())
                    resultados.append((caminho, st, j))
            except Exception as e:   # noqa: BLE001
                erros.append(repr(e))

        def gravador():
            try:
                for i in range(gravados):
                    item = {'loja': 'amazon', 'item_id': f'B0SIM{i:05d}', 'cat': PERFUMES, 'busca': 'perfume',
                            'url': f'https://www.amazon.com.br/dp/B0SIM{i:05d}?tag={TS2.LINK_AMAZON.split("=")[-1]}',
                            'data': {'titulo': f'Perfume simultâneo {i}', 'preco': 'R$ 10,00'}}
                    st, _, corpo = self.pedir('POST', '/api/items', corpo={'items': [item]}, headers=self.local())
                    if st != 200:
                        erros.append(('POST', st, corpo[:100]))
            except Exception as e:   # noqa: BLE001
                erros.append(repr(e))

        threads = [threading.Thread(target=leitor, args=(n,)) for n in range(3)] + [threading.Thread(target=gravador)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(60)
        self.assertEqual(erros, [])
        self.assertEqual(len(resultados), 45)
        for caminho, st, j in resultados:
            self.assertEqual(st, 200, (caminho, j))
            self.assertEqual(j['versao'], 1)
        # na ordem atualizacao os gravados agora ficam na folga; na relevancia o total só cresce
        self.assertEqual(self.v1('/api/v1/ofertas?limite=200', self.auth())[2]['total'], 2)
        depois = self.v1('/api/v1/ofertas?ordem=relevancia&limite=200', self.auth())[2]
        self.assertEqual(depois['total'], 2 + gravados)
        self.assertNotIn('falhou', self.saida())
        self.assertNotIn('Traceback', self.saida())


class TokenDe32Caracteres(ServidorQa):
    TOKEN = staticmethod(lambda: 'a1_-' * 8)   # exatamente 32

    def test_ca6_token_de_32_caracteres_liga_a_api(self):
        self.assertEqual(len(self.token), 32)
        st, _, j = self.v1('/api/v1/categorias', self.auth())
        self.assertEqual(st, 200, j)


class TokenDe31Caracteres(ServidorQa):
    TOKEN = staticmethod(lambda: 'a1_-' * 7 + 'abc')   # 31

    def test_ca6_token_de_31_caracteres_deixa_a_api_desligada_e_o_servidor_no_ar(self):
        self.assertEqual(len(self.token), 31)
        st, _, j = self.v1('/api/v1/categorias', self.auth())
        self.assertEqual(st, 503, j)
        st, _, _ = self.pedir('GET', '/api/items', headers=self.local())
        self.assertEqual(st, 200)
        self.assertIn('API v1 desligada', self.saida())


class TokenComFimDeLinhaWindows(ServidorQa):
    @staticmethod
    def CONTEUDO(token):
        return b'\r\n  ' + token.encode() + b'  \r\n\r\n'

    def test_ca6_espacos_e_crlf_nas_pontas_do_arquivo_sao_tirados(self):
        st, _, j = self.v1('/api/v1/categorias', self.auth())
        self.assertEqual(st, 200, j)


class TokenComBom(ServidorQa):
    @staticmethod
    def CONTEUDO(token):
        return b'\xef\xbb\xbf' + token.encode() + b'\n'

    def test_ca6_arquivo_com_bom_deixa_a_api_desligada_sem_vazar_o_conteudo(self):
        st, _, j = self.v1('/api/v1/categorias', self.auth())
        self.assertEqual(st, 503, j)
        self.assertFalse(self.token in self.saida(), 'o token apareceu no log')


class TokenComEspacoNoMeio(ServidorQa):
    @staticmethod
    def CONTEUDO(token):
        return (token[:20] + ' ' + token[20:]).encode() + b'\n'

    def test_ca6_token_com_espaco_no_meio_desliga(self):
        st, _, j = self.v1('/api/v1/categorias', self.auth())
        self.assertEqual(st, 503, j)


class TokenLidoUmaVezSo(ServidorQa):
    def test_ca6_trocar_o_arquivo_sem_reiniciar_nao_muda_o_token_em_uso(self):
        novo = ('A' if self.token[0] != 'A' else 'B') + self.token[1:]
        TS2.gravar_token(self.arquivo_token, novo.encode() + b'\n')
        st, _, _ = self.v1('/api/v1/categorias', self.auth())
        self.assertEqual(st, 200)
        st, _, _ = self.v1('/api/v1/categorias', self.auth(token=novo))
        self.assertEqual(st, 401)
        os.remove(self.arquivo_token)
        st, _, _ = self.v1('/api/v1/categorias', self.auth())
        self.assertEqual(st, 200)


class ServidorDadosReais(ServidorQa):
    """O servidor de verdade sobre a cópia do banco real: segue o cursor até o fim pelo HTTP."""

    @classmethod
    def antes_de_subir(cls):
        if not copiar_banco_real(cls.db):
            raise unittest.SkipTest('sem achadinhos.db legível neste checkout')

    @classmethod
    def depois_de_subir(cls):
        pass

    def estado(self):
        con = sqlite3.connect(f'file:{self.db}?mode=ro', uri=True)
        try:
            return (con.execute('SELECT COUNT(*), MAX(atualizado_em), MAX(id) FROM items').fetchone(),
                    con.execute('PRAGMA user_version').fetchone()[0],
                    [con.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in ('numeros', 'regras', 'envios', 'config')])
        finally:
            con.close()

    def test_ca1_ca4_ca5_ca9_seguir_o_proximo_pelo_http_percorre_tudo_uma_vez_e_nao_grava(self):
        antes = self.estado()
        _, _, cats = self.v1('/api/v1/categorias', self.auth())
        ofertas, cursor, paginas = [], None, 0
        while True:
            caminho = '/api/v1/ofertas?limite=200' + (('&cursor=' + urllib.parse.quote(cursor)) if cursor else '')
            st, _, j = self.v1(caminho, self.auth())
            self.assertEqual(st, 200, j)
            paginas += 1
            if not j['ofertas']:
                self.assertIsNone(j['proximo'])
                break
            ofertas += j['ofertas']
            cursor = j['proximo']
            self.assertLess(paginas, 200)
        ids = [o['id'] for o in ofertas]
        self.assertEqual(len(ids), len(set(ids)), 'oferta repetida')
        self.assertEqual(len(ofertas), cats['total'])
        self.assertEqual(sum(c['total'] for c in cats['categorias']), cats['total'])
        self.assertEqual(paginas, math.ceil(len(ofertas) / 200) + 1)
        for o in ofertas:
            self.assertTrue(D.link_da_loja_ok(o['loja'], o['link'], AFILIADO), o['chave'])
            self.assertTrue(imagem_ok_oraculo(o['loja'], o['imagem']), o['chave'])
        self.assertEqual(self.estado(), antes)
        self.assertNotIn('falhou', self.saida())


if __name__ == '__main__':
    unittest.main()
