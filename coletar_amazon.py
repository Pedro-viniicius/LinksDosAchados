#!/usr/bin/env python3
"""Coleta produtos da Amazon (buscas.json + lista do WhatsApp) e grava no achadinhos.db.

Uso:  python3 coletar_amazon.py [buscas|whatsapp|tudo]
Retoma de onde parou: termos já coletados ficam em coleta_amazon_feitos.txt.
"""
import json, os, random, re, sys, time, urllib.parse, urllib.request
from bs4 import BeautifulSoup
import servidor as S

BASE = S.BASE
FEITOS = os.path.join(BASE, 'coleta_amazon_feitos.txt')
POR_BUSCA = 30
CHAT = os.path.join(BASE, 'WhatsApp Chat - AmazonLinks', '_chat.txt')


class Bloqueado(Exception):
    pass


def baixar(url):
    req = urllib.request.Request(url, headers={'User-Agent': S.UA, 'Accept-Language': 'pt-BR,pt;q=0.9',
                                               'Accept': 'text/html,application/xhtml+xml'})
    with urllib.request.urlopen(req, timeout=30) as r:
        h = r.read().decode('utf-8', 'ignore'); final = r.geturl()
    if ('captcha' in h.lower() and 's-search-result' not in h and 'productTitle' not in h):
        raise Bloqueado(url)
    return final, h


def link_afiliado(asin):
    return f'https://www.amazon.com.br/dp/{asin}?tag={S.TAG_AMAZON}'


def num(preco):
    try:
        return float(re.sub(r'[^\d,]', '', preco).replace(',', '.'))
    except ValueError:
        return 0


def txt(el):
    return el.get_text(' ', strip=True).replace('\xa0', ' ') if el else ''


def parse_busca(h):
    s = BeautifulSoup(h, 'lxml')
    out = []
    for r in s.select('div[data-component-type="s-search-result"]'):
        asin = r.get('data-asin')
        titulo = txt(r.select_one('h2'))
        if not asin or not titulo:
            continue
        atual = r.select_one('.a-price:not(.a-text-price) .a-offscreen')
        antigo = r.select_one('.a-price.a-text-price[data-a-strike] .a-offscreen') or r.select_one('.a-price.a-text-price .a-offscreen')
        preco, preco_antigo = txt(atual), txt(antigo)
        if num(preco_antigo) <= num(preco):
            preco_antigo = ''
        desconto = f'-{round(100 - num(preco) * 100 / num(preco_antigo))}%' if preco and preco_antigo else ''
        bruto = txt(r)
        vendas = re.search(r'(Mais de [\d.,]+\s*(?:mil)?\s*compras no mês passado)', bruto)
        aval = txt(r.select_one('.a-icon-alt'))
        nav = r.select_one('a[href*="#customerReviews"] span, span.s-underline-text')
        img = r.select_one('img.s-image')
        out.append({'asin': asin, 'data': {
            'titulo': titulo, 'preco': preco, 'preco_antigo': preco_antigo, 'desconto': desconto,
            'avaliacao': aval, 'num_avaliacoes': txt(nav).strip('()'),
            'vendas': vendas.group(1) if vendas else '',
            'frete': 'Frete GRÁTIS' if 'GRÁTIS' in bruto.upper() and 'FRETE' in bruto.upper() else '',
            'cupom': '', 'imagem': img['src'] if img else ''}})
    return out


def gravar(itens):
    con = S.conectar(); c = {'inserido': 0, 'atualizado': 0}
    for it in itens:
        c[S.upsert(con, it)] += 1
    con.commit(); con.close()
    return c


def feitos():
    return set(open(FEITOS, encoding='utf-8').read().splitlines()) if os.path.exists(FEITOS) else set()


def marcar(chave):
    with open(FEITOS, 'a', encoding='utf-8') as f:
        f.write(chave + '\n')


def pausa(a=4, b=8):
    time.sleep(random.uniform(a, b))


def coletar_buscas():
    buscas = json.load(open(os.path.join(BASE, 'buscas.json'), encoding='utf-8'))
    ja = feitos()
    for cat, termos in buscas.items():
        for termo in termos:
            chave = f'busca|{cat}|{termo}'
            if chave in ja:
                continue
            res = []
            for tentativa in range(3):  # às vezes a Amazon devolve uma página sem resultados
                _, h = baixar('https://www.amazon.com.br/s?k=' + urllib.parse.quote_plus(termo))
                res = parse_busca(h)[:POR_BUSCA]
                if res:
                    break
                pausa(8, 15)
            if not res:
                print(f'[{cat}] {termo}: sem resultados, fica para a próxima rodada', flush=True)
                continue
            c = gravar([{'loja': 'amazon', 'item_id': r['asin'], 'cat': cat, 'busca': termo,
                         'url': link_afiliado(r['asin']), 'data': r['data']} for r in res])
            print(f'[{cat}] {termo}: {len(res)} achados, {c["inserido"]} novos', flush=True)
            marcar(chave); pausa()


def coletar_whatsapp():
    links = []
    for u in re.findall(r'https?://\S+', open(CHAT, encoding='utf-8').read()):
        u = u.rstrip('.,);‎')
        if u not in links:
            links.append(u)
    ja = feitos()
    for u in links:
        chave = f'whatsapp|{u}'
        if chave in ja:
            continue
        final, h = baixar(u)
        asin = (re.search(r'/dp/([A-Z0-9]{10})', final) or re.search(r'/dp/([A-Z0-9]{10})', u) or [None, None])[1]
        d = S.extrair_produto_amazon(h)
        # link sempre com a tag de afiliado
        url = link_afiliado(asin) if asin else u
        c = gravar([{'loja': 'amazon', 'item_id': asin or u, 'cat': 'Lista WhatsApp', 'busca': 'WhatsApp',
                     'url': url, 'data': d}])
        print(f'[WhatsApp] {u} -> {asin} {d["titulo"][:50]!r} {c}', flush=True)
        marcar(chave); pausa(3, 6)


if __name__ == '__main__':
    S.criar_banco()
    modo = sys.argv[1] if len(sys.argv) > 1 else 'tudo'
    try:
        if modo in ('whatsapp', 'tudo'):
            coletar_whatsapp()
        if modo in ('buscas', 'tudo'):
            coletar_buscas()
    except Bloqueado as e:
        print('PAROU: a Amazon pediu captcha em', e, '- espere uns minutos e rode de novo.', flush=True)
        sys.exit(2)
    con = S.conectar()
    print('TOTAL no banco:', con.execute('SELECT COUNT(*) FROM items').fetchone()[0])
