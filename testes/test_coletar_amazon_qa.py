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

# Abas de 04/11/2026 (antes das 17 abas por nicho). Valem só para o histórico: o progresso antigo, gravado como
# `busca|<aba>|<termo>`, e a fixture testes/fixtures/buscas-2026-11-04.json, cópia do buscas.json daquele dia.
ELETRONICOS = 'Black Friday | Eletrônicos'
ELETRODOMESTICOS = 'Eletrodomésticos'
CASA = 'Casa e Decoração'
PERFUMES = 'Perfumes e Perfumaria'

# As 17 abas do mapa do dono, na ordem do buscas.json vivo.
ABAS_17 = [
    'Celulares e Informática', 'Áudio e Acessórios', 'TV, Alexa e Casa Conectada', 'Games', 'Eletroportáteis',
    'Eletrodomésticos e Climatização', 'Cozinha', 'Cama, Mesa e Banho', 'Casa, Móveis e Ferramentas',
    'Beleza e Cuidados', 'Perfumes e Perfumaria', 'Mercado e Limpeza', 'Pets', 'Bebês e Brinquedos',
    'Suplementos e Fitness', 'Moda e Viagem', 'Natal e Papelaria']
NOVOS_POR_ABA = [8, 8, 9, 7, 8, 5, 7, 8, 12, 16, 0, 13, 10, 14, 13, 13, 10]   # os 161 termos novos (Decisão 3)
TV_ALEXA = 'TV, Alexa e Casa Conectada'

# Termos da lista de presentes do casamento (pedido do dono em 04/11/2026), acrescentados no FIM das abas.
PRESENTES_ELETRODOMESTICOS = ['Torradeira elétrica', 'Batedeira planetária', 'Umidificador de ar', 'Lavadora de alta pressão',
                              'Climatizador de ar']
PRESENTES_CASA = ['Balança de cozinha digital', 'Manta para sofá', 'Assadeira antiaderente', 'Jogo de taças de vinho',
                  'Forma de bolo antiaderente', 'Aparelho de fondue', 'Taças de sobremesa', 'Boleira com tampa',
                  'Frigideira antiaderente', 'Conjunto de bowls de cerâmica', 'Jogo de xícaras de café com pires',
                  'Panela de pressão 4,5 litros', 'Abajur de chão']
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


# Decisão 2 do plano abas-nichadas-e-coleta: onde cada termo atual passou a morar (mesmo texto, outra aba).
ABA_DOS_TERMOS_ATUAIS = {
    'Celulares e Informática': [
        'iPhone 17', 'iPhone 16', 'Samsung Galaxy A17', 'Samsung Galaxy A57', 'Celular smartphone', 'Notebook Dell',
        'Notebook Acer', 'Notebook ASUS', 'Notebook', 'Notebook gamer', 'Computador gamer', 'Tablet Samsung',
        'iPad Apple', 'Tablet', 'Monitor Samsung', 'Monitor AOC', 'Monitor', 'Impressora Epson EcoTank L3250',
        'Impressora multifuncional', 'Mouse Logitech M170', 'Teclado e mouse', 'Webcam', 'SSD', 'HD externo',
        'Placa de vídeo', 'Filtro de linha iCLAMPER Energia 5', 'Filtro de linha', 'Nobreak'],
    'Áudio e Acessórios': [
        'Samsung Galaxy Fit3', 'Relógio inteligente smartwatch', 'Fone Bluetooth JBL', 'Fone de ouvido Bluetooth',
        'Caixa de som Bluetooth JBL', 'Caixa de som Bluetooth', 'Carregador portátil power bank', 'Carregador rápido',
        'Microfone'],
    'TV, Alexa e Casa Conectada': [
        'Echo Dot Alexa', 'Smart speaker Alexa', 'Smart TV 4K Samsung 50', 'Smart TV 4K LG 55', 'Smart TV 4K', 'Smart TV',
        'Fire TV Stick HD', 'Aparelho de streaming para TV', 'Kindle', 'Kindle Paperwhite', 'Leitor de livros digitais',
        'Soundbar', 'Soundbar Samsung HW-B400F', 'Home theater', 'Roteador Wi-Fi mesh', 'Câmera de segurança Wi-Fi'],
    'Games': [
        'PlayStation 5 Slim', 'Nintendo Switch OLED', 'Console de videogame', 'Controle PS5 DualSense',
        'Controle acessório videogame', 'Mouse gamer Redragon Predator M612', 'Headset gamer'],
    'Eletroportáteis': [
        'Air fryer', 'Sanduicheira grill', 'Aspirador de pó', 'Robô aspirador', 'Cafeteira', 'Liquidificador', 'Mixer',
        'Batedeira planetária', 'Ferro de passar', 'Vaporizador de roupas', 'Torradeira elétrica'],
    'Eletrodomésticos e Climatização': [
        'Geladeira', 'Fogão', 'Cooktop', 'Micro-ondas', 'Máquina de lavar', 'Lava e seca', 'Lava-louças',
        'Ar-condicionado', 'Ventilador', 'Umidificador de ar', 'Climatizador de ar', 'Purificador de água'],
    'Cozinha': [
        'Jogo de panelas', 'Frigideira antiaderente', 'Panela de pressão 4,5 litros', 'Aparelho de jantar',
        'Jogo de talheres', 'Conjunto de bowls de cerâmica', 'Jogo de taças de vinho', 'Taças de sobremesa',
        'Jogo de xícaras de café com pires', 'Assadeira antiaderente', 'Forma de bolo antiaderente', 'Boleira com tampa',
        'Potes herméticos', 'Organizador de cozinha', 'Balança de cozinha digital', 'Aparelho de fondue'],
    'Cama, Mesa e Banho': ['Jogo de cama', 'Edredom', 'Travesseiro', 'Jogo de toalhas', 'Manta para sofá'],
    'Casa, Móveis e Ferramentas': [
        'Cama box', 'Colchão', 'Sofá', 'Guarda-roupa', 'Armário de cozinha', 'Mesa de jantar com cadeiras', 'Cortina',
        'Persiana', 'Tapete', 'Abajur de chão', 'Organizador de guarda-roupa', 'Lavadora de alta pressão'],
}


def buscas_reais():
    with open(os.path.join(T.RAIZ, 'buscas.json'), encoding='utf-8') as f:
        return json.load(f)


def buscas_antigas():
    """O buscas.json de 04/11/2026 (4 abas, 158 termos), congelado na fixture."""
    with open(os.path.join(T.RAIZ, 'testes', 'fixtures', 'buscas-2026-11-04.json'), encoding='utf-8') as f:
        return json.load(f)


def aba_de(termo):
    """Aba do termo no buscas.json vivo."""
    return next(aba for aba, ts in buscas_reais().items() if termo in ts)


class TestBuscasJson(unittest.TestCase):
    """CA7 (histórico, na fixture de 04/11) e CA1 do plano abas-nichadas (arquivo vivo)."""

    def test_fixture_tem_quatro_chaves_na_ordem_com_60_24_32_42_termos(self):
        b = buscas_antigas()
        self.assertEqual(list(b), [ELETRONICOS, ELETRODOMESTICOS, CASA, PERFUMES])
        self.assertEqual([len(v) for v in b.values()], [60, 24, 32, 42])

    def test_fixture_tem_os_termos_da_decisao_2_do_plano_antigo(self):
        b = buscas_antigas()
        self.assertEqual(b[ELETRODOMESTICOS], PLANO_ELETRODOMESTICOS + PRESENTES_ELETRODOMESTICOS)
        self.assertEqual(b[CASA], PLANO_CASA + PRESENTES_CASA)
        self.assertEqual(b[PERFUMES], PLANO_PERFUMES)
        eletronicos = b[ELETRONICOS]
        self.assertEqual(eletronicos[-1], 'Smart TV', 'os 59 de "Black Friday" na ordem, mais "Smart TV"')
        self.assertEqual(eletronicos[0], 'iPhone 17')
        self.assertNotIn('Caixa inteligente assistente virtual', eletronicos, 'o alias fica fora do buscas.json')
        self.assertIn('Smart speaker Alexa', eletronicos)

    def test_17_abas_com_os_nomes_do_mapa_do_dono_e_na_ordem(self):
        b = buscas_reais()
        self.assertEqual(list(b), ABAS_17)
        self.assertEqual(len(b), 17)
        self.assertEqual(sum(len(v) for v in b.values()), 319)

    def test_nenhum_termo_repete_nenhum_tem_barra_vertical_e_tudo_e_nfc(self):
        b = buscas_reais()
        termos = [t for v in b.values() for t in v]
        self.assertEqual(len(termos), len(set(termos)), 'termo repetido')
        self.assertEqual(len({t.casefold() for t in termos}), len(termos), 'termo repetido só na caixa')
        self.assertEqual([t for t in termos if '|' in t], [])
        self.assertEqual([a for a in b if '|' in a], [])
        for texto in termos + list(b):
            self.assertTrue(unicodedata.is_normalized('NFC', texto), f'{texto!r} não está em NFC')
            self.assertEqual(texto, texto.strip(), f'{texto!r} tem espaço nas pontas')
            self.assertNotIn('  ', texto)
            self.assertTrue(texto)
        self.assertTrue(all(isinstance(t, str) for t in termos))

    def test_cada_termo_antigo_segue_com_o_mesmo_texto_e_os_161_novos_entram_no_fim_de_cada_aba(self):
        vivo, antigo = buscas_reais(), buscas_antigas()
        antigos = [t for v in antigo.values() for t in v]
        todos = {t for v in vivo.values() for t in v}
        self.assertEqual(len(antigos), 158)
        self.assertEqual([t for t in antigos if t not in todos], [], 'termo antigo sumiu ou mudou de texto')
        self.assertEqual(len(todos) - len(antigos), 161)
        # os termos antigos formam o começo de cada aba; os novos vêm depois, na ordem do plano
        for (aba, termos), novos in zip(vivo.items(), NOVOS_POR_ABA):
            n_antigos = len(termos) - novos
            self.assertTrue(all(t in antigos for t in termos[:n_antigos]), aba)
            self.assertTrue(all(t not in antigos for t in termos[n_antigos:]), aba)
        self.assertEqual(sum(NOVOS_POR_ABA), 161)

    def test_perfumaria_fica_exatamente_igual(self):
        self.assertEqual(buscas_reais()[PERFUMES], buscas_antigas()[PERFUMES])
        self.assertEqual(buscas_reais()[PERFUMES], PLANO_PERFUMES)

    def test_termos_atuais_foram_para_as_abas_da_decisao_2(self):
        b = buscas_reais()
        for aba, esperado in ABA_DOS_TERMOS_ATUAIS.items():
            self.assertEqual(b[aba][:len(esperado)], esperado, aba)
        atuais = [t for v in ABA_DOS_TERMOS_ATUAIS.values() for t in v] + PLANO_PERFUMES
        self.assertEqual(sorted(atuais), sorted(t for v in buscas_antigas().values() for t in v))

    def test_o_alias_do_ml_herda_a_categoria_do_termo_da_amazon(self):
        import migrar_categorias as M
        mapa = M.carregar_mapa()
        self.assertEqual(M.destino_de('Caixa inteligente assistente virtual', mapa), TV_ALEXA)
        self.assertEqual(M.ALIAS, {'Caixa inteligente assistente virtual': 'Smart speaker Alexa'})
        self.assertNotIn('Caixa inteligente assistente virtual', [t for v in buscas_reais().values() for t in v],
                         'o alias fica fora do buscas.json')


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
        return [{'asin': f'B{zlib.crc32(k.encode()):010d}{i}', 'data': {'titulo': f'{k} {i}', 'preco': 'R$ 10,00', **T.NO_PISO}}
                for i in range(2)]


class TestProgressoComBuscasReais(BaseColeta):
    """CA8 com o buscas.json de verdade: o progresso antigo cobre os 98 termos que já existiam antes da lista de
    presentes; sobram os 42 de perfumaria, os 18 de presentes e os 161 das 17 abas (a aba nova não recoleta nada)."""

    def linhas_antigas(self):
        b = buscas_antigas()
        eletronicos = [t for t in b[ELETRONICOS] if t != 'Smart TV']
        return ([f'busca|Black Friday|{t}' for t in eletronicos] + ['busca|Casa Nova|Smart TV'] +
                [f'busca|Casa Nova|{t}' for t in PLANO_ELETRODOMESTICOS + PLANO_CASA])

    def test_com_o_progresso_antigo_so_os_termos_novos_sao_coletados(self):
        self.usar(buscas_reais())
        antigas = self.linhas_antigas()
        self.assertEqual(len(antigas), 98)
        T.escrever_feitos(*antigas, *[f'whatsapp|https://amzn.to/{i}' for i in range(3)])
        C.coletar_buscas()
        pedidos = [urllib.parse.unquote_plus(u.split('k=', 1)[1]) for u in self.baixados]
        ja_feitos = {l.rsplit('|', 1)[1] for l in antigas}
        faltam = [t for v in buscas_reais().values() for t in v if t not in ja_feitos]
        self.assertEqual(len(pedidos), 42 + 18 + 161)
        self.assertEqual(pedidos, faltam, 'na ordem do arquivo, só o que ainda não foi feito')
        self.assertEqual({i['cat'] for i in self.itens()}, set(ABAS_17))
        self.assertEqual({i['busca'] for i in self.itens()}, set(faltam))
        for i in self.itens():
            self.assertEqual(i['cat'], aba_de(i['busca']), i['busca'])

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
