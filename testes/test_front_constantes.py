"""Constantes do index.html que espelham o servidor (R1 da rodada 1 da E4, plano perfumaria-tres-lojas).

O front guarda à mão os hosts dos links por loja (HOSTS_LINK, SUFIXO_ML), o CDN da foto (HOST_FOTO_SHOPEE,
HOSTS_FOTO) e as lojas com seus nomes (LOJA). O servidor.py e o disparo.py têm os mesmos dados. Estes testes leem as
linhas do index.html (cada constante fica numa linha só, no começo da linha) e conferem com os módulos Python,
para uma troca de host feita num lado só reprovar aqui.

Decisão sobre o Mercado Livre: o servidor aceita meli.la e qualquer SUBDOMÍNIO de mercadolivre.com.br
(host.endswith('.mercadolivre.com.br')); o domínio nu mercadolivre.com.br é recusado. O front guarda o sufixo em
SUFIXO_ML e usa endsWith, igual ao servidor; por isso o teste compara o sufixo e o comportamento de lojaDoLink
com o servidor numa lista de URLs, inclusive a do domínio nu.

Rodar: python3 testes/test_front_constantes.py -v   (precisa de node no PATH só para o teste de comportamento)
"""
import atexit
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix='achadinhos-front-const-')
atexit.register(shutil.rmtree, TMP, ignore_errors=True)
# Antes do import: o servidor lê ACHADINHOS_DB ao carregar; nada aqui sai para a rede.
os.environ['ACHADINHOS_DB'] = os.path.join(TMP, 'import.db')
for _v in ('http_proxy', 'https_proxy', 'ftp_proxy'):
    os.environ[_v] = 'http://127.0.0.1:9'
os.environ['no_proxy'] = ''
sys.path.insert(0, RAIZ)
import servidor as S   # noqa: E402
import disparo as D    # noqa: E402
import genero as G      # noqa: E402

with open(os.path.join(RAIZ, 'index.html'), encoding='utf-8') as _f:
    HTML = _f.read()


def linha(nome):
    """A linha `const <nome> = ...;` do index.html (no começo da linha), sem o comentário do fim."""
    m = re.search(r'^(const ' + re.escape(nome) + r' = .*?;)(?:\s*//.*)?$', HTML, re.M)
    assert m, f'index.html sem uma linha "const {nome} = ...;" no começo da linha'
    return m.group(1)


def js_json(expr, *linhas):
    """Roda as linhas `const` do index.html num node e devolve o valor da expressão como JSON."""
    node = shutil.which('node')
    assert node, 'node não está no PATH'
    codigo = '\n'.join(linhas) + f'\nprocess.stdout.write(JSON.stringify({expr}));'
    r = subprocess.run([node, '-e', codigo], capture_output=True, text=True, encoding='utf-8', timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def funcao(nome):
    m = re.search(r'^const ' + re.escape(nome) + r' = u=>\{.*?^\};', HTML, re.M | re.S)
    assert m, f'index.html sem a função {nome}'
    return m.group(0)


class ConstantesDoFront(unittest.TestCase):
    def test_hosts_da_shopee_iguais_ao_servidor(self):
        hosts = js_json('HOSTS_LINK', linha('HOSTS_LINK'))
        self.assertEqual(set(hosts['shopee']), set(S.HOSTS_AFILIADO_SHOPEE))

    def test_hosts_da_amazon_e_do_ml_iguais_ao_servidor(self):
        hosts = js_json('HOSTS_LINK', linha('HOSTS_LINK'))
        self.assertEqual(set(hosts['ml']), {'meli.la'})
        self.assertEqual(set(hosts['amazon']), set(S.HOSTS_LOJAS) - {'meli.la'})
        self.assertEqual(set(hosts['amazon']) | set(hosts['ml']), set(S.HOSTS_LOJAS))
        self.assertEqual(set(hosts), set(S.LOJAS), 'o front tem hosts para as mesmas lojas do servidor')

    def test_sufixo_do_ml_igual_ao_do_servidor(self):
        sufixo = js_json('SUFIXO_ML', linha('SUFIXO_ML'))
        self.assertEqual(sufixo, '.mercadolivre.com.br')
        self.assertTrue(S.eh_url_de_loja('https://www' + sufixo + '/x'))
        self.assertFalse(S.eh_url_de_loja('https://' + sufixo[1:] + '/x'), 'o domínio nu o servidor recusa')

    def test_loja_do_link_concorda_com_o_servidor(self):
        """lojaDoLink devolve uma loja exatamente quando o servidor aceita a url (eh_url_de_loja) e
        quando o servidor recusa devolve null; a loja bate com o validador de cada loja do servidor."""
        urls = [
            'https://s.shopee.com.br/7AbCdEf12', 'https://meli.la/1AbCdEf', 'https://lista.mercadolivre.com.br/x',
            'https://www.mercadolivre.com.br/afiliados/x', 'https://mercadolivre.com.br/x',
            'https://www.amazon.com.br/dp/B0TESTE001?tag=desejodemen01-20', 'https://amazon.com.br/dp/B0', 'https://amzn.to/3abc',
            'https://www.amazon.com/dp/B0', 'https://shopee.com.br/Perfume-i.1.2', 'https://shope.ee/AAA',
            'https://amazon.com.br.golpe.com/x', 'https://golpe.com/s.shopee.com.br/AAA', 'https://exemplo.com/produto',
            'https://s.shopee.com/AAA', 'https://xs.shopee.com.br/AAA', 'https://meli.la.golpe.com/x',
            'https://golpe-mercadolivre.com.br/x', 'https://evil.com/.mercadolivre.com.br', 'isto nao e url',
        ]
        codigo = '\n'.join([linha('HOSTS_LINK'), linha('SUFIXO_ML'), funcao('lojaDoLink')])
        lojas = js_json('URLS.map(lojaDoLink)', 'const URLS = ' + json.dumps(urls) + ';', codigo)
        for u, loja in zip(urls, lojas):
            with self.subTest(u):
                self.assertEqual(loja is not None, S.eh_url_de_loja(u))
                if loja is not None:
                    self.assertTrue(S.URL_DA_LOJA[loja][0](u), 'a loja do front é a que o servidor valida')

    def test_cdn_da_foto_igual_ao_disparo(self):
        self.assertEqual(js_json('HOST_FOTO_SHOPEE', linha('HOST_FOTO_SHOPEE')), D.HOST_FOTO_SHOPEE)

    def test_hosts_foto_iguais_ao_disparo(self):
        hosts = js_json('HOSTS_FOTO', linha('HOST_FOTO_SHOPEE'), linha('HOSTS_FOTO'))
        self.assertEqual(hosts, list(D.HOSTS_FOTO))

    def test_lojas_e_nomes_iguais_ao_disparo(self):
        loja = js_json('LOJA', linha('LOJA'))
        self.assertEqual(list(loja), list(D.LOJAS), 'mesmas lojas, na mesma ordem')
        self.assertEqual(loja, D.NOMES_LOJA)
        self.assertEqual(set(loja), set(S.LOJAS))

    def test_abas_com_genero_e_valores_iguais_ao_genero_py(self):
        """Etapa 6 do plano genero-nas-categorias: o front guarda a lista de abas com público e os valores
        de item.genero; o servidor (genero.py) tem os mesmos. Troca num lado só reprova aqui."""
        self.assertEqual(tuple(js_json('ABAS_COM_GENERO', linha('ABAS_COM_GENERO'))), G.ABAS_COM_GENERO)
        self.assertEqual(tuple(js_json('GENEROS', linha('GENEROS'))), G.GENEROS)
        nomes = js_json('NOME_GENERO', linha('NOME_GENERO'))
        self.assertEqual(list(nomes), list(G.GENEROS), 'um nome para cada valor, na ordem do servidor')
        opcoes = js_json('OPCOES_PUBLICO', linha('OPCOES_PUBLICO'))
        self.assertEqual([k for k, _ in opcoes], ['todos', *G.GENEROS])
        self.assertEqual({k: t for k, t in opcoes if k != 'todos'}, nomes)
        # abaTemGenero concorda com a constante do servidor para cada aba do buscas.json
        with open(os.path.join(RAIZ, 'buscas.json'), encoding='utf-8') as f:
            abas = list(json.load(f))
        for a in G.ABAS_COM_GENERO:
            self.assertIn(a, abas, 'a aba com público existe no buscas.json')
        m = re.search(r'^function abaTemGenero\(cat\)\{.*\}$', HTML, re.M)   # numa linha só, declarada com function
        self.assertTrue(m, 'index.html sem a função abaTemGenero numa linha só')
        codigo = '\n'.join([linha('ABAS_COM_GENERO'), m.group(0)])
        respostas = js_json('ABAS.map(abaTemGenero)', 'const ABAS = ' + json.dumps(abas + ['', 'perfumes e perfumaria']) + ';', codigo)
        self.assertEqual(respostas, [a in G.ABAS_COM_GENERO for a in abas] + [False, False])

    def test_ordem_das_abas_igual_as_chaves_do_buscas_json(self):
        """Etapa 8 do plano abas-nichadas-e-coleta (CA6): a ordem das 17 abas do front é a do buscas.json,
        nome por nome. Aba renomeada ou reordenada num lado só reprova aqui (o servidor não serve o buscas.json)."""
        with open(os.path.join(RAIZ, 'buscas.json'), encoding='utf-8') as f:
            chaves = list(json.load(f))
        ordem = js_json('ORDEM_ABAS', linha('ORDEM_ABAS'))
        self.assertEqual(len(chaves), 17)
        self.assertEqual(ordem, chaves)
        self.assertEqual(len(set(ordem)), len(ordem), 'sem aba repetida')

    def test_grupos_das_abas_cobrem_as_17_em_faixas_contiguas(self):
        """GRUPOS_ABAS diz quantas abas tem cada grupo, na ordem de TXT_ABAS.grupos (4 faixas da spec: 4, 5, 4 e 4)."""
        tamanhos = js_json('GRUPOS_ABAS', linha('GRUPOS_ABAS'))
        ordem = js_json('ORDEM_ABAS', linha('ORDEM_ABAS'))
        self.assertEqual(tamanhos, [4, 5, 4, 4])
        self.assertEqual(sum(tamanhos), len(ordem), 'toda aba está em algum grupo')
        m = re.search(r"^  grupos:\[(.*?)\], outras:'(.*?)',", HTML, re.M)
        self.assertTrue(m, 'index.html sem a linha "grupos:[...], outras:..." em TXT_ABAS')
        rotulos = js_json('G', 'const G = [' + m.group(1) + '];')
        self.assertEqual(len(rotulos), len(tamanhos), 'um rótulo para cada grupo')
        self.assertEqual(rotulos, ['Tecnologia', 'Casa', 'Beleza e consumo', 'Família e estilo'])
        self.assertEqual(m.group(2), 'Outras')
        for a in G.ABAS_COM_GENERO:
            self.assertIn(a, ordem, 'a aba com público está entre as 17')


if __name__ == '__main__':
    unittest.main()
