#!/usr/bin/env python3
"""Testes de QA do buscas.json e do progresso do coletar_amazon.py (CA7 e CA8 do plano
docs/produto/planos/eletronicos-e-coleta-ml.md). Complementa test_coletar_amazon.py.

Uso:  python3 testes/test_coletar_amazon_qa.py -v

Mesmas regras do arquivo do dev: banco e arquivo de progresso temporários, `baixar`, `parse_busca`
e `pausa` falsos, proxy morto. Nenhum teste acessa a Amazon nem toca o coleta_amazon_feitos.txt real.
"""
import json
import os
import subprocess
import sys
import unicodedata
import unittest
import urllib.parse
import zlib
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_coletar_amazon as T  # noqa: E402  (define o ambiente temporário antes de importar o coletor)

C, S = T.C, T.S


def tearDownModule():
    T.tearDownModule()

ELETRONICOS = 'Black Friday | Eletrônicos'
ELETRODOMESTICOS = 'Eletrodomésticos'
CASA = 'Casa e Decoração'
PERFUMES = 'Perfumes e Perfumaria'

# Termos de cada aba como a Decisão 2 do plano.
PLANO_ELETRODOMESTICOS = [
    'Geladeira', 'Máquina de lavar', 'Lava e seca', 'Fogão', 'Cooktop', 'Air fryer', 'Micro-ondas',
    'Ar-condicionado', 'Aspirador de pó', 'Robô aspirador', 'Cafeteira', 'Liquidificador', 'Mixer',
    'Purificador de água', 'Ventilador', 'Sanduicheira grill', 'Lava-louças', 'Ferro de passar',
    'Vaporizador de roupas']
PLANO_CASA = [
    'Jogo de panelas', 'Cama box', 'Colchão', 'Sofá', 'Guarda-roupa', 'Armário de cozinha',
    'Mesa de jantar com cadeiras', 'Aparelho de jantar', 'Jogo de talheres', 'Potes herméticos',
    'Jogo de cama', 'Jogo de toalhas', 'Travesseiro', 'Edredom', 'Cortina', 'Persiana', 'Tapete',
    'Organizador de cozinha', 'Organizador de guarda-roupa']
PLANO_PERFUMES = [
    'Perfume feminino importado', 'Perfume masculino importado', 'Perfume feminino nacional',
    'Perfume masculino nacional', 'Kit perfume com hidratante', 'Kit perfume com desodorante',
    'Perfume árabe feminino', 'Perfume árabe masculino', 'Perfume unissex', 'Body splash feminino',
    'Body splash masculino', 'Colônia feminina', 'Colônia masculina', 'Hidratante corporal perfumado',
    'Óleo corporal perfumado', 'Desodorante corporal perfumado', 'Kit sabonete perfumado',
    'Perfume para cabelo', 'Miniatura de perfume', 'Kit perfume', 'Loção pós-barba',
    'Body splash', 'Desodorante colônia', 'Perfume árabe', 'Perfume infantil',
    'Perfume Natura', 'Natura Kaiak', 'Natura Essencial', 'Perfume O Boticário', 'Malbec O Boticário',
    'Egeo O Boticário', 'Perfume Eudora', 'Carolina Herrera 212 VIP', 'Carolina Herrera Good Girl',
    'Paco Rabanne One Million', 'Paco Rabanne Invictus', 'Dior Sauvage', 'Lancôme La Vie Est Belle',
    'Calvin Klein CK One', 'Jean Paul Gaultier Le Male', 'Azzaro Pour Homme', 'Lattafa']


def buscas_reais():
    with open(os.path.join(T.RAIZ, 'buscas.json'), encoding='utf-8') as f:
        return json.load(f)


class TestBuscasJson(unittest.TestCase):
    """CA7: o mapa termo -> categoria."""

    def test_quatro_chaves_na_ordem_com_60_19_19_42_termos(self):
        b = buscas_reais()
        self.assertEqual(list(b), [ELETRONICOS, ELETRODOMESTICOS, CASA, PERFUMES])
        self.assertEqual([len(v) for v in b.values()], [60, 19, 19, 42])

    def test_nenhum_termo_repete_nenhum_tem_barra_vertical_e_tudo_e_nfc(self):
        b = buscas_reais()
        termos = [t for v in b.values() for t in v]
        self.assertEqual(len(termos), len(set(termos)), 'termo repetido')
        self.assertEqual(len({t.casefold() for t in termos}), len(termos), 'termo repetido só na caixa')
        self.assertEqual([t for t in termos if '|' in t], [])
        for texto in termos + list(b):
            self.assertTrue(unicodedata.is_normalized('NFC', texto), f'{texto!r} não está em NFC')
            self.assertEqual(texto, texto.strip(), f'{texto!r} tem espaço nas pontas')
            self.assertNotIn('  ', texto)
            self.assertTrue(texto)
            self.assertTrue(all(isinstance(t, str) for t in termos))

    def test_termos_de_cada_aba_sao_os_da_decisao_2_do_plano(self):
        b = buscas_reais()
        self.assertEqual(b[ELETRODOMESTICOS], PLANO_ELETRODOMESTICOS)
        self.assertEqual(b[CASA], PLANO_CASA)
        self.assertEqual(b[PERFUMES], PLANO_PERFUMES)
        eletronicos = b[ELETRONICOS]
        self.assertEqual(eletronicos[-1], 'Smart TV', 'os 59 de "Black Friday" na ordem, mais "Smart TV"')
        self.assertEqual(eletronicos[0], 'iPhone 17')
        self.assertNotIn('Caixa inteligente assistente virtual', eletronicos, 'o alias fica fora do buscas.json')
        self.assertIn('Smart speaker Alexa', eletronicos)

    def test_o_alias_do_ml_herda_a_categoria_do_termo_da_amazon(self):
        import migrar_categorias as M
        mapa = M.carregar_mapa()
        self.assertEqual(M.destino_de('Caixa inteligente assistente virtual', mapa), ELETRONICOS)
        self.assertEqual(M.ALIAS, {'Caixa inteligente assistente virtual': 'Smart speaker Alexa'})


class BaseColeta(T.Base):
    def setUp(self):
        super().setUp()
        self.json = os.path.join(T.TMP, 'buscas.json')
        self.baixados = []
        for p in (mock.patch.object(C, 'BASE', T.TMP), mock.patch.object(C, 'baixar', self.baixar),
                  mock.patch.object(C, 'parse_busca', self.parse),
                  mock.patch.object(C, 'pausa', lambda *a, **k: None)):
            p.start()
            self.addCleanup(p.stop)

    def usar(self, buscas):
        with open(self.json, 'w', encoding='utf-8') as f:
            json.dump(buscas, f, ensure_ascii=False)

    def baixar(self, url):
        self.baixados.append(url)
        return url, url

    def parse(self, h):
        k = h.split('k=', 1)[1]
        return [{'asin': f'B{zlib.crc32(k.encode()):010d}{i}', 'data': {'titulo': f'{k} {i}', 'preco': 'R$ 10,00'}}
                for i in range(2)]


class TestProgressoComBuscasReais(BaseColeta):
    """CA8 com o buscas.json de verdade: o progresso antigo cobre os 98 termos e sobram os 42 de perfumaria."""

    def linhas_antigas(self):
        b = buscas_reais()
        eletronicos = [t for t in b[ELETRONICOS] if t != 'Smart TV']
        return ([f'busca|Black Friday|{t}' for t in eletronicos] + ['busca|Casa Nova|Smart TV'] +
                [f'busca|Casa Nova|{t}' for t in b[ELETRODOMESTICOS] + b[CASA]])

    def test_com_o_progresso_antigo_so_os_42_termos_de_perfumaria_sao_coletados(self):
        self.usar(buscas_reais())
        antigas = self.linhas_antigas()
        self.assertEqual(len(antigas), 98)
        T.escrever_feitos(*antigas, *[f'whatsapp|https://amzn.to/{i}' for i in range(3)])
        C.coletar_buscas()
        pedidos = [urllib.parse.unquote_plus(u.split('k=', 1)[1]) for u in self.baixados]
        self.assertEqual(len(pedidos), 42)
        self.assertEqual(set(pedidos), set(PLANO_PERFUMES))
        self.assertEqual({i['cat'] for i in self.itens()}, {PERFUMES})
        self.assertEqual({i['busca'] for i in self.itens()}, set(PLANO_PERFUMES))

    def test_segunda_rodada_nao_baixa_nada(self):
        self.usar(buscas_reais())
        T.escrever_feitos(*self.linhas_antigas())
        C.coletar_buscas()
        n = len(self.baixados)
        C.coletar_buscas()
        self.assertEqual(len(self.baixados), n)
        feitos = T.ler_feitos()
        self.assertEqual(len(feitos), len(set(feitos)), 'a mesma linha foi marcada duas vezes')


class TestInterrupcao(BaseColeta):
    BUSCAS = {ELETRONICOS: ['iPhone 17', 'Smart TV'], PERFUMES: ['Dior Sauvage', 'Lattafa']}

    def test_captcha_no_meio_mantem_os_termos_feitos_e_o_resto_fica_para_depois(self):
        self.usar(self.BUSCAS)
        chamadas = []

        def baixar(url):
            chamadas.append(url)
            if len(chamadas) == 3:
                raise C.Bloqueado(url)
            return url, url

        with mock.patch.object(C, 'baixar', baixar):
            with self.assertRaises(C.Bloqueado):
                C.coletar_buscas()
        self.assertEqual(T.ler_feitos(), ['busca|iPhone 17', 'busca|Smart TV'])
        self.assertEqual({i['busca'] for i in self.itens()}, {'iPhone 17', 'Smart TV'})
        # nova rodada (sem o captcha) coleta só o que faltou
        self.baixados.clear()
        C.coletar_buscas()
        self.assertEqual(len(self.baixados), 2)
        self.assertEqual(T.ler_feitos()[-2:], ['busca|Dior Sauvage', 'busca|Lattafa'])

    def test_falha_ao_gravar_nao_marca_o_termo_como_feito(self):
        self.usar(self.BUSCAS)
        with mock.patch.object(C, 'gravar', side_effect=RuntimeError('disco cheio')):
            with self.assertRaises(RuntimeError):
                C.coletar_buscas()
        self.assertFalse(os.path.exists(C.FEITOS) and T.ler_feitos(), 'termo marcado sem ter gravado')

    def test_linhas_com_fim_de_linha_do_windows_e_vazias_nao_atrapalham(self):
        with open(C.FEITOS, 'w', encoding='utf-8', newline='') as f:
            f.write('busca|Black Friday|iPhone 17\r\n\r\nbusca|Casa Nova|Smart TV\r\n')
        feitos = C.feitos()
        self.assertIn(C.chave_busca('iPhone 17'), feitos)
        self.assertIn(C.chave_busca('Smart TV'), feitos)

    def test_linha_whatsapp_com_barra_vertical_na_url_fica_intacta(self):
        linha = 'whatsapp|https://exemplo.com/p?a=1|2|busca|x'
        T.escrever_feitos(linha, 'busca|Casa Nova|Sofá')
        self.assertEqual(C.feitos(), {linha, 'busca|Sofá'})


class TestVariavelDeAmbiente(unittest.TestCase):
    """CA8: ACHADINHOS_FEITOS troca o arquivo de progresso; sem ela, vale o do projeto."""

    def caminho(self, **env):
        base = {k: v for k, v in os.environ.items() if k != 'ACHADINHOS_FEITOS'}
        base.update(env, ACHADINHOS_DB=os.path.join(T.TMP, 'outro.db'), PYTHONDONTWRITEBYTECODE='1')
        r = subprocess.run([sys.executable, '-I', '-c',
                            'import sys; sys.path.insert(0, %r); import coletar_amazon as C; print(C.FEITOS)' % T.RAIZ],
                           env=base, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()

    def test_sem_variavel_usa_o_arquivo_do_projeto(self):
        self.assertEqual(self.caminho(), os.path.join(T.RAIZ, 'coleta_amazon_feitos.txt'))

    def test_com_variavel_usa_o_caminho_dela(self):
        alvo = os.path.join(T.TMP, 'meu-progresso.txt')
        self.assertEqual(self.caminho(ACHADINHOS_FEITOS=alvo), alvo)

    def test_variavel_vazia_cai_no_arquivo_do_projeto(self):
        self.assertEqual(self.caminho(ACHADINHOS_FEITOS=''), os.path.join(T.RAIZ, 'coleta_amazon_feitos.txt'))


if __name__ == '__main__':
    unittest.main()
