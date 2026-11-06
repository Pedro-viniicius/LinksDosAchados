"""Único ponto de rede do garimpo feminino: uma requisição GraphQL assinada à Open API de afiliados da Shopee.

Plano: docs/produto/planos/garimpo-feminino-shopee.md, etapa 1 (Decisão 2; CA5, CA7 e CA9).

Reaproveita do coletar_shopee.py, sem mudá-lo: o host fixo (`URL_API`), o opener que não segue redirect
(`OPENER_API`), a assinatura (`assinar`/`autorizacao`), o leitor com teto de 2 MB (`_ler_json`), o código de
erro da resposta e as exceções. A credencial é o par (AppID, Segredo) de `coletar_shopee.credenciais()`, que
tira o Secret do ambiente com `pop`.

- O corpo é JSON canônico só com `query` (a constante da consulta) e `variables` (os valores); a assinatura é
  calculada sobre exatamente esse texto, que vai como corpo.
- Não há variável de ambiente nem parâmetro que troque o host: o Secret só assina pedidos para `CS.URL_API`.
- Ritmo de ~1 req/s: entre o início de um pedido e o do seguinte, `pausa` + U(0; 0,25) s (piso de 0,5 s).
- Limite da API (código 10030 ou HTTP 429): espera `min(900, 30·2^k)·U(0,8; 1,2)` s e tenta de novo, até
  5 vezes; depois, `LimiteAtingido` (saída 3).
- System Error (código 10000, intermitente no R1 real): espera 5, 10 e 20 s e tenta de novo, até 3 vezes; depois,
  `ErroApi(10000)`. Cada tentativa fica no `registrar` e conta no orçamento.
- Orçamento: `max_total` conta os pedidos já gravados no garimpo.db (`ja_feitas`) mais os desta rodada;
  `max_rodada` é o `--max-req`. Os dois levantam `Teto` (saída 3) antes de mandar o pedido.
- `registrar(registro)` recebe um dicionário por pedido mandado (inclusive os do limite e os que falham), só
  com `operacao`, `http`, `codigo`, `ms`, `bytes` e `em`: nem cabeçalho, nem corpo, nem assinatura. Código fora do
  int64 vai como None (o banco recusaria o registro, e o pedido sumiria de `requisicoes`); a exceção mantém o código.
- `erro_permanente(codigo, http)` separa o erro em que a API julgou o pedido (com código ou HTTP 4xx) da falha de
  transporte ou de autenticação; o reconhecer e o motor usam a mesma regra.
"""
import json
import math
import os
import random
import re
import sys
import time
import urllib.error
import urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if RAIZ not in sys.path:
    sys.path.append(RAIZ)   # no fim: os módulos desta pasta não ficam escondidos pelos da raiz

import coletar_shopee as CS  # noqa: E402

MAX_TOTAL_REQUESTS = 20_000              # orçamento padrão do brief (ajuste obrigatório 5)
PAUSA_PADRAO, PAUSA_MINIMA, PAUSA_MAXIMA = 1.0, 0.5, 60.0
JITTER = 0.25                            # segundos somados à pausa, U(0; JITTER)
TENTATIVAS_LIMITE = 5                    # esperas no 10030/429 antes de desistir
BACKOFF_BASE, BACKOFF_TETO = 30, 900     # segundos
BACKOFF_FATOR = (0.8, 1.2)
ERRO_SISTEMA = 10000                     # System Error: intermitente, não é a API recusando o pedido
TENTATIVAS_SISTEMA, ESPERA_SISTEMA = 3, 5  # novas tentativas no 10000; espera da 1ª, em segundos (dobra a cada uma)
MAX_INT64 = 2 ** 63 - 1                  # o que a coluna `codigo` de requisicoes aceita
RE_OPERACAO = re.compile(r'\{\s*([A-Za-z_][A-Za-z0-9_]{0,63})', re.A)

_LIMITE = object()   # sinal interno: a tentativa bateu no limite da API
_SISTEMA = object()  # sinal interno: a tentativa voltou com System Error


class Teto(CS.ErroColeta):
    """Orçamento de requisições esgotado: `qual` é 'total' (MAX_TOTAL_REQUESTS) ou 'rodada' (--max-req)."""
    def __init__(self, qual):
        super().__init__(qual)
        self.qual = qual


def corpo_json(consulta, variaveis):
    """Corpo canônico do pedido: a consulta como está e os valores só em `variables`, com as chaves ordenadas.

    `ensure_ascii` deixa o texto igual aos bytes enviados (a assinatura é sobre esse texto).
    """
    if not isinstance(consulta, str) or not consulta.strip():
        raise TypeError('a consulta tem de ser uma constante GraphQL em texto')
    if not isinstance(variaveis, dict) or not all(isinstance(k, str) for k in variaveis):
        raise TypeError('as variáveis têm de ser um dicionário com chaves de texto')
    return json.dumps({'query': consulta, 'variables': variaveis}, separators=(',', ':'), sort_keys=True,
                      ensure_ascii=True, allow_nan=False)


def operacao_de(consulta):
    """Nome do primeiro campo da consulta (ex.: productOfferV2), para a tabela requisicoes. Vem da constante,
    nunca da API."""
    m = RE_OPERACAO.search(consulta)
    return m.group(1) if m else '?'


def erro_permanente(codigo, http):
    """True se a API julgou o pedido: respondeu com código de erro ou HTTP 4xx, e repetir daria o mesmo.

    False para o resto, que não diz nada sobre o pedido: sem resposta (rede, timeout), HTTP 5xx, 3xx sem código,
    autenticação (401/403, com ou sem código), limite (10030/429, que tem espera e retomada próprias) e System
    Error (10000, intermitente).
    Recebe os campos, não a exceção: também classifica o que já está gravado em `medicoes` e `requisicoes`.
    """
    if codigo in (CS.ERRO_LIMITE, ERRO_SISTEMA) or http in (401, 403, 429) or http is not None and http >= 500:
        return False
    return codigo is not None or http is not None and 400 <= http < 500


def espera_backoff(k, aleatorio):
    """Espera, em segundos, depois do k-ésimo limite seguido (k a partir de 0)."""
    return min(BACKOFF_TETO, BACKOFF_BASE * 2 ** k) * aleatorio(*BACKOFF_FATOR)


def _inteiro(v, minimo, nome):
    if isinstance(v, bool) or not isinstance(v, int) or v < minimo:
        raise ValueError(f'{nome} tem de ser um inteiro >= {minimo}')
    return v


class _Medidor:
    """Conta os bytes lidos da resposta (para a coluna `bytes`), sem guardar o conteúdo."""
    def __init__(self):
        self.lidos, self._r = 0, None

    def de(self, r):
        self._r = r
        return self

    def read(self, n=-1):
        bruto = self._r.read(n)
        self.lidos += len(bruto)
        return bruto


class Cliente:
    """Guarda a credencial, o ritmo e o orçamento de uma rodada. Um objeto por rodada, sem threads."""

    def __init__(self, cred, *, ja_feitas=0, max_total=MAX_TOTAL_REQUESTS, max_rodada=None, pausa=PAUSA_PADRAO,
                 parede=None, monotonico=None, dormir=None, aleatorio=None):
        if (not isinstance(cred, tuple) or len(cred) != 2 or not isinstance(cred[0], str)
                or not isinstance(cred[1], CS.Segredo)):
            raise TypeError('a credencial tem de vir de coletar_shopee.credenciais()')
        if isinstance(pausa, bool) or not isinstance(pausa, (int, float)) or not math.isfinite(pausa) \
                or not PAUSA_MINIMA <= pausa <= PAUSA_MAXIMA:
            raise ValueError(f'a pausa tem de ficar entre {PAUSA_MINIMA} e {PAUSA_MAXIMA} s')
        self._cred = cred
        self.ja_feitas = _inteiro(ja_feitas, 0, 'ja_feitas')
        self.max_total = _inteiro(max_total, 1, 'max_total')
        self.max_rodada = None if max_rodada is None else _inteiro(max_rodada, 1, 'max_rodada')
        self.pausa = float(pausa)
        # relógios, espera e sorteio injetáveis (testes); o padrão é lido aqui, não na definição
        self._parede = parede or time.time
        self._mono = monotonico or time.monotonic
        self._dormir = dormir or time.sleep
        self._aleatorio = aleatorio or random.uniform
        self.feitas = 0          # pedidos mandados nesta rodada, inclusive os que bateram no limite
        self._ultimo = None      # instante (monotônico) do início do último pedido
        self._http_sistema = None   # HTTP do último 10000 (None quando veio com 200)

    def __repr__(self):
        return (f'Cliente(feitas={self.feitas}, ja_feitas={self.ja_feitas}, max_total={self.max_total}, '
                f'max_rodada={self.max_rodada})')

    def pedir(self, consulta, variaveis, *, registrar):
        """Manda a consulta e devolve o "data" da resposta.

        Levanta CS.LimiteAtingido (limite depois das 5 esperas), CS.ErroApi (código da API, inclusive o 10000
        depois das 3 tentativas, HTTP fora do 2xx, 3xx não seguido ou falha de rede), CS.RespostaInvalida (acima de
        2 MB, JSON inválido ou sem "data")
        ou Teto (orçamento). Nenhuma delas leva texto vindo da API nem da credencial.
        """
        if not callable(registrar):
            raise TypeError('registrar tem de ser uma função')
        corpo = corpo_json(consulta, variaveis)
        operacao = operacao_de(consulta)
        limites = sistemas = 0
        while True:
            dados = self._tentar(corpo, operacao, registrar)
            if dados is _LIMITE:
                if limites == TENTATIVAS_LIMITE:
                    raise CS.LimiteAtingido()
                espera = espera_backoff(limites, self._aleatorio)
                limites += 1
            elif dados is _SISTEMA:
                if sistemas == TENTATIVAS_SISTEMA:
                    raise CS.ErroApi(ERRO_SISTEMA, self._http_sistema)
                espera = ESPERA_SISTEMA * 2 ** sistemas
                sistemas += 1
            else:
                return dados
            self._conferir_teto()   # sem orçamento para tentar de novo: não espera à toa
            self._dormir(espera)

    def _conferir_teto(self):
        if self.ja_feitas + self.feitas >= self.max_total:
            raise Teto('total')
        if self.max_rodada is not None and self.feitas >= self.max_rodada:
            raise Teto('rodada')

    def _esperar_ritmo(self):
        if self._ultimo is None:
            return
        falta = self.pausa + self._aleatorio(0, JITTER) - (self._mono() - self._ultimo)
        if falta > 0:
            self._dormir(falta)

    def _tentar(self, corpo, operacao, registrar):
        """Um pedido. Devolve o "data", ou _LIMITE/_SISTEMA para tentar de novo; registra o pedido sempre."""
        self._conferir_teto()
        self._esperar_ritmo()
        app_id, segredo = self._cred
        ts = int(self._parede())
        req = urllib.request.Request(CS.URL_API, data=corpo.encode('utf-8'), method='POST', headers={
            'Content-Type': 'application/json', 'User-Agent': CS.S.UA,
            'Authorization': CS.autorizacao(app_id, ts, CS.assinar(app_id, ts, corpo, segredo.valor()))})
        medidor, info = _Medidor(), {'http': None, 'codigo': None}
        inicio = self._ultimo = self._mono()
        self.feitas += 1
        try:
            try:
                with CS.OPENER_API.open(req, timeout=CS.TIMEOUT) as r:
                    status = getattr(r, 'status', None)
                    info['http'] = status if isinstance(status, int) else 200
                    resposta = CS._ler_json(medidor.de(r))
            except urllib.error.HTTPError as e:   # inclusive o 3xx, que o OPENER_API não segue
                info['http'] = e.code
                try:
                    info['codigo'] = CS.codigo_de_erro(CS._ler_json(medidor.de(e)))
                except Exception:
                    pass
                finally:
                    e.close()
                if info['codigo'] == CS.ERRO_LIMITE or e.code == 429:
                    return _LIMITE
                if info['codigo'] == ERRO_SISTEMA:
                    self._http_sistema = e.code
                    return _SISTEMA
                raise CS.ErroApi(info['codigo'], e.code) from None
            except OSError:   # rede, timeout, proxy: só o tipo importa; a mensagem não sai daqui
                raise CS.ErroApi() from None
            if not isinstance(resposta, dict):
                raise CS.RespostaInvalida()
            info['codigo'] = CS.codigo_de_erro(resposta)
            if info['codigo'] == CS.ERRO_LIMITE:
                return _LIMITE
            if info['codigo'] == ERRO_SISTEMA:
                self._http_sistema = None
                return _SISTEMA
            if info['codigo'] is not None:
                raise CS.ErroApi(info['codigo'])
            dados = resposta.get('data')
            if not isinstance(dados, dict):
                raise CS.RespostaInvalida()
            return dados
        finally:
            codigo = info['codigo']
            registrar({'operacao': operacao, 'http': info['http'],
                       'codigo': codigo if codigo is None or abs(codigo) <= MAX_INT64 else None,
                       'ms': max(0, round((self._mono() - inicio) * 1000)), 'bytes': medidor.lidos,
                       'em': time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(ts))})
