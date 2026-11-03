#!/usr/bin/env python3
"""Coleta produtos da Amazon (buscas.json + lista do WhatsApp) e grava no achadinhos.db.

Uso:  python3 coletar_amazon.py [buscas|whatsapp|tudo]
      python3 coletar_amazon.py buscas --cat "<aba>" [--ordens vendidos,avaliados,caros]
Sem opções, as buscas usam só a relevância (padrão da Amazon). Com `--ordens`, coleta só os
termos da aba `--cat`, uma vez por ordem (`&s=<valor>` na URL); `--ordens` sem `--cat` é recusado.
Retoma de onde parou: termos já coletados ficam em coleta_amazon_feitos.txt
(ACHADINHOS_FEITOS troca o caminho desse arquivo).
"""
import argparse, json, os, random, re, sys, time, unicodedata, urllib.parse, urllib.request
from bs4 import BeautifulSoup
import servidor as S

BASE = S.BASE
FEITOS = os.environ.get('ACHADINHOS_FEITOS') or os.path.join(BASE, 'coleta_amazon_feitos.txt')
POR_BUSCA = 30
# ordem -> valor do parâmetro `s` da busca (menu "Classificar por"); relevância não leva `s`
ORDENS = {'relevancia': None, 'vendidos': 'exact-aware-popularity-rank',
          'avaliados': 'review-rank', 'caros': 'price-desc-rank'}
CHAT = os.path.join(BASE, 'WhatsApp Chat - AmazonLinks', '_chat.txt')


class Bloqueado(Exception):
    pass


class ArgInvalido(ValueError):
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


def chave_busca(termo, ordem='relevancia'):
    """Relevância mantém `busca|{termo}` (progresso antigo vale). As outras ordens usam o prefixo
    `ordem|`, que o `feitos()` não reescreve (`busca|…` é lido pelo último segmento)."""
    if ordem not in ORDENS:
        raise ArgInvalido(f'ordem desconhecida: {ordem!r}')
    return f'busca|{termo}' if ordem == 'relevancia' else f'ordem|{ordem}|{termo}'


def url_busca(termo, ordem='relevancia'):
    if ordem not in ORDENS:
        raise ArgInvalido(f'ordem desconhecida: {ordem!r}')
    url = 'https://www.amazon.com.br/s?k=' + urllib.parse.quote_plus(termo)
    return url if ORDENS[ordem] is None else url + '&s=' + ORDENS[ordem]


def ler_ordens(texto):
    """'vendidos,avaliados' -> ['vendidos', 'avaliados'] (sem repetir, na ordem dada)."""
    ordens = []
    for o in (texto or '').split(','):
        o = o.strip()
        if o not in ORDENS:
            raise ArgInvalido(f'ordem desconhecida: {o!r} (valem: {", ".join(ORDENS)})')
        if o not in ordens:
            ordens.append(o)
    return ordens


def feitos():
    """Chaves já coletadas. O progresso é por termo (`busca|{termo}`): as linhas antigas
    `busca|{cat}|{termo}` valem pelo último segmento, então renomear a aba não recoleta nada."""
    if not os.path.exists(FEITOS):
        return set()
    with open(FEITOS, encoding='utf-8') as f:
        linhas = f.read().splitlines()
    return {chave_busca(l.rsplit('|', 1)[1]) if l.startswith('busca|') else l for l in linhas}


def marcar(chave):
    with open(FEITOS, 'a', encoding='utf-8') as f:
        f.write(chave + '\n')


def pausa(a=4, b=8):
    time.sleep(random.uniform(a, b))


def coletar_buscas(cat=None, ordens=('relevancia',)):
    """Sem `cat`, todas as abas, só na relevância. Ordem diferente da relevância exige `cat`."""
    ordens = list(ordens)
    for o in ordens:
        if o not in ORDENS:
            raise ArgInvalido(f'ordem desconhecida: {o!r}')
    if cat is None and ordens != ['relevancia']:
        raise ArgInvalido('--ordens exige --cat')
    buscas = json.load(open(os.path.join(BASE, 'buscas.json'), encoding='utf-8'))
    if cat is not None:
        cat = unicodedata.normalize('NFC', cat)
        if cat not in buscas:
            raise ArgInvalido(f'aba desconhecida: {cat!r} (valem: {", ".join(buscas)})')
        buscas = {cat: buscas[cat]}
    ja = feitos()
    for cat, termos in buscas.items():
        for termo in termos:
            for ordem in ordens:
                chave = chave_busca(termo, ordem)
                if chave in ja:
                    continue
                res = []
                for tentativa in range(3):  # às vezes a Amazon devolve uma página sem resultados
                    _, h = baixar(url_busca(termo, ordem))
                    res = parse_busca(h)[:POR_BUSCA]
                    if res:
                        break
                    pausa(8, 15)
                rotulo = termo if ordem == 'relevancia' else f'{termo} ({ordem})'
                if not res:
                    print(f'[{cat}] {rotulo}: sem resultados, fica para a próxima rodada', flush=True)
                    continue
                c = gravar([{'loja': 'amazon', 'item_id': r['asin'], 'cat': cat, 'busca': termo,
                             'url': link_afiliado(r['asin']), 'data': r['data']} for r in res])
                print(f'[{cat}] {rotulo}: {len(res)} achados, {c["inserido"]} novos', flush=True)
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


def ler_argumentos(argv):
    ap = argparse.ArgumentParser(prog='coletar_amazon.py', description='Coleta produtos da Amazon.')
    ap.add_argument('modo', nargs='?', default='tudo', choices=('buscas', 'whatsapp', 'tudo'))
    ap.add_argument('--cat', help='só os termos desta aba do buscas.json')
    ap.add_argument('--ordens', help='ordens separadas por vírgula: ' + ', '.join(ORDENS) +
                                     ' (padrão: relevancia; exige --cat)')
    a = ap.parse_args(argv)
    if (a.cat is not None or a.ordens is not None) and a.modo != 'buscas':
        ap.error('--cat e --ordens só valem com o modo "buscas"')
    if a.ordens is not None and a.cat is None:
        ap.error('--ordens exige --cat "<aba>"')
    try:
        a.ordens = ler_ordens(a.ordens) if a.ordens is not None else ['relevancia']
    except ArgInvalido as e:
        ap.error(str(e))
    return a


def main(argv=None):
    a = ler_argumentos(sys.argv[1:] if argv is None else argv)
    S.criar_banco()
    try:
        if a.modo in ('whatsapp', 'tudo'):
            coletar_whatsapp()
        if a.modo in ('buscas', 'tudo'):
            coletar_buscas(a.cat, a.ordens)
    except ArgInvalido as e:
        print('ERRO:', e, file=sys.stderr, flush=True)
        sys.exit(2)
    except Bloqueado as e:
        print('PAROU: a Amazon pediu captcha em', e, '- espere uns minutos e rode de novo.', flush=True)
        sys.exit(2)
    con = S.conectar()
    print('TOTAL no banco:', con.execute('SELECT COUNT(*) FROM items').fetchone()[0])


if __name__ == '__main__':
    main()
