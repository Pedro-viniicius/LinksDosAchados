"""Isolamento e falsos comuns aos testes do garimpo feminino (etapa 4 em diante). Sem rede.

Importar este módulo ANTES de qualquer módulo do garimpo (`import comum` no topo do teste):
- os proxies apontam para 127.0.0.1:9 (porta morta) e `no_proxy` fica vazio;
- ACHADINHOS_DB, ACHADINHOS_FEITOS_SHOPEE e ACHADINHOS_GARIMPO_DIR vão para uma pasta temporária, apagada
  no fim do processo (o achadinhos.db e o garimpo.db reais nunca são tocados);
- as credenciais da Shopee saem do ambiente (os testes usam só marcadores falsos).

`isolado(api, conferencia)` troca os dois pontos de rede do coletar_shopee.py (`OPENER_API.open` e
`OPENER_CONFERENCIA.open`) por falsos, faz o `urlopen` falhar e o `time.sleep` só anotar a espera.
"""
import atexit
import contextlib
import email.message
import io
import json
import os
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
from unittest import mock

PASTA = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAIZ = os.path.dirname(os.path.dirname(PASTA))
TMP = tempfile.mkdtemp(prefix='teste-garimpo-')
atexit.register(shutil.rmtree, TMP, True)
for _v in ('http_proxy', 'https_proxy', 'ftp_proxy'):
    os.environ[_v] = 'http://127.0.0.1:9'
os.environ['no_proxy'] = ''
os.environ['ACHADINHOS_DB'] = os.path.join(TMP, 'achadinhos.db')
os.environ['ACHADINHOS_FEITOS_SHOPEE'] = os.path.join(TMP, 'feitos-shopee.txt')
os.environ['ACHADINHOS_GARIMPO_DIR'] = os.path.join(TMP, 'garimpo')
for _v in ('ACHADINHOS_SHOPEE_APP_ID', 'ACHADINHOS_SHOPEE_SECRET'):
    os.environ.pop(_v, None)
if PASTA not in sys.path:
    sys.path.insert(0, PASTA)

import cliente as K  # noqa: E402

CS = K.CS
S = CS.S
assert os.path.dirname(S.DB) == TMP and os.path.dirname(CS.FEITOS) == TMP, 'o teste não pode tocar os dados reais'

SECRET = 'SEGREDO-MARCADOR-9d2b44'   # procurado em toda saída: nunca pode aparecer
APP_ID = '1800012345'
URL_FIXA = 'https://open-api.affiliate.shopee.com.br/graphql'
LINK = 'https://s.shopee.com.br/AbC123'


def cred():
    return (APP_ID, CS.Segredo(SECRET))


def no(item_id=1, **campos):
    """Nó do productOfferV2 como a API devolve."""
    base = {'itemId': item_id, 'shopId': 777, 'productName': f'Vestido longo {item_id}', 'offerLink': LINK,
            'productLink': f'https://shopee.com.br/product/777/{item_id}', 'priceMin': '49.90', 'sales': 1500,
            'ratingStar': '4.8', 'productCatIds': [100017, 100104, 100420]}
    base.update(campos)
    return base


def resposta(nos=None, *, tem_proxima=None, pagina=1):
    """Resposta do productOfferV2. Sem `tem_proxima`, SEM `pageInfo`, como a consulta do garimpo (que não o pede);
    com `tem_proxima` (True ou False), com o `pageInfo` das sondas do reconhecer."""
    nos = [no()] if nos is None else list(nos)
    corpo = {'nodes': nos}
    if tem_proxima is not None:
        corpo['pageInfo'] = {'page': pagina, 'limit': 20, 'hasNextPage': tem_proxima}
    return {'data': {'productOfferV2': corpo}}


def erro(codigo, mensagem='falhou'):
    return {'errors': [{'message': mensagem, 'extensions': {'code': codigo, 'message': mensagem}}]}


def http_erro(codigo, corpo=b'', location=None, motivo='x', url=URL_FIXA):
    h = email.message.Message()
    if location:
        h['Location'] = location
    if isinstance(corpo, dict):
        corpo = json.dumps(corpo).encode()
    return urllib.error.HTTPError(url, codigo, motivo, h, io.BytesIO(corpo))


class Resp(io.BytesIO):
    """Resposta falsa do opener (context manager com read e status)."""
    status = 200


class ApiFalsa:
    """Troca o CS.OPENER_API.open: devolve as respostas da fila (dict vira JSON; bytes vão como estão;
    exceção é levantada) e guarda as requisições e os timeouts. Fila vazia → `resposta()`."""

    def __init__(self, *respostas):
        self.fila, self.pedidos, self.timeouts = list(respostas), [], []

    def __call__(self, req, timeout=None):
        self.pedidos.append(req)
        self.timeouts.append(timeout)
        r = self.fila.pop(0) if self.fila else resposta()
        if isinstance(r, BaseException):
            raise r
        return Resp(r if isinstance(r, bytes) else json.dumps(r).encode())

    def corpos(self):
        return [json.loads(p.data) for p in self.pedidos]


class ConferenciaFalsa:
    """Troca o CS.OPENER_CONFERENCIA.open: o link curto responde 302 com o Location do afiliado `id_afiliado`
    (padrão: o do coletar_shopee.py). Guarda os links conferidos."""

    def __init__(self, id_afiliado=None, location=None):
        self.id_afiliado, self.location, self.links = id_afiliado, location, []

    def __call__(self, req, timeout=None):
        self.links.append(req.full_url)
        destino = self.location or ('https://shopee.com.br/product/777/1?utm_source=an_'
                                    + (self.id_afiliado or CS.ID_AFILIADO_SHOPEE))
        raise http_erro(302, location=destino, url=req.full_url)


def _urlopen_proibido(*a, **k):
    raise AssertionError('urlopen chamado: o teste não pode sair para a rede')


@contextlib.contextmanager
def isolado(api=None, conferencia=None):
    """Os dois pontos de rede trocados por falsos, `urlopen` proibido e `time.sleep` só anotado.

    Devolve (api, conferencia, esperas)."""
    api = api if api is not None else ApiFalsa()
    conferencia = conferencia if conferencia is not None else ConferenciaFalsa()
    esperas = []
    with mock.patch.object(CS.OPENER_API, 'open', api), \
            mock.patch.object(CS.OPENER_CONFERENCIA, 'open', conferencia), \
            mock.patch.object(urllib.request, 'urlopen', _urlopen_proibido), \
            mock.patch.object(K.time, 'sleep', esperas.append):
        yield api, conferencia, esperas


_contador = [0]


def nova_pasta():
    """Pasta de dados nova e vazia dentro do TMP (para ACHADINHOS_GARIMPO_DIR)."""
    _contador[0] += 1
    caminho = os.path.join(TMP, f'garimpo-{_contador[0]}')
    os.makedirs(caminho)
    return caminho


def conteudo_da_pasta(pasta):
    """Bytes de todos os arquivos da pasta (logs, garimpo.db e -wal/-shm, exports), para procurar vazamento."""
    partes = []
    for raiz, _, nomes in os.walk(pasta):
        for nome in nomes:
            caminho = os.path.join(raiz, nome)
            if os.path.isfile(caminho) and not os.path.islink(caminho):
                with open(caminho, 'rb') as f:
                    partes.append(f.read())
    return b'\n'.join(partes)
