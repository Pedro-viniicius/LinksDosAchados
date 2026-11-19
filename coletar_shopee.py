#!/usr/bin/env python3
"""Coleta produtos da Shopee pela Open API de afiliados (ou de um arquivo do painel) e grava no achadinhos.db.

Uso:  python3 coletar_shopee.py conferir [--por-item]
      python3 coletar_shopee.py buscas --cat "Perfumes e Perfumaria" [--ordens vendidos,relevancia,caros]
      python3 coletar_shopee.py importar ARQUIVO

Planos: docs/produto/planos/perfumaria-tres-lojas.md, etapa E7 (CA7), e
docs/produto/planos/abas-nichadas-e-coleta.md, etapa 7 (CA9: `importar` e piso de 50 vendas), e
docs/produto/planos/atualizar-precos-shopee-por-item.md, etapa 1 (consulta por item e `conferir --por-item`).

Ambiente:
  ACHADINHOS_SHOPEE_APP_ID e ACHADINHOS_SHOPEE_SECRET  credenciais da Open API (obrigatórias em `conferir`
      e `buscas`; o `importar` não as lê). O Secret só é lido do ambiente: nunca vai para arquivo,
      argumento, URL, stdout, log ou mensagem de erro. Antes de lê-lo, `proteger_processo()` fecha o
      /proc/<pid>/environ para os outros processos do usuário (o pop não apaga o Secret dali); se o sistema
      recusar, o comando segue com um AVISO.
      Num terminal só para isso, sem export (o Secret vale só para este comando):
        read -rs S; ACHADINHOS_SHOPEE_SECRET="$S" ACHADINHOS_SHOPEE_APP_ID=<id> python3 coletar_shopee.py ...; unset S
      O script tira o Secret do próprio ambiente assim que o lê.
  ACHADINHOS_FEITOS_SHOPEE  troca o arquivo de progresso (padrão coleta_shopee_feitos.txt, chave <ordem>|<termo>).
  ACHADINHOS_DB  troca o banco, como no servidor.py.
Não há variável que troque a URL da API: o Secret assina toda requisição e só vai para o host fixo.

`conferir` faz uma busca em `vendidos` (ORDEM_PADRAO) e confere, sem gravar nada, que o link gerado é do dono (utm_source=an_<ID>).
`conferir --por-item` (portão G1) faz o mesmo e, depois da conferência do dono, uma segunda chamada:
productOfferV2(shopId, itemId) com os ids do primeiro nó válido da busca. Sai com 0 só se voltar o nó com os
mesmos ids, que passe no no_para_item (link curto de afiliado, título, piso, não usado) e com preço legível, e então
imprime os ids e o preço lido (para o dono conferir no site a ordem de grandeza); com 1 se a lista vier vazia, com
nó de outro id, com o nó que o no_para_item recusaria ou sem preço legível, e se a API recusar o argumento (o código
aparece, como 10010 ou 11001). O filtro desses argumentos é "a confirmar (G1)". Os ids vão nas variáveis Int64
como texto de dígitos: como número JSON a API recusa com 10010 (medições #37/#38 do garimpo e G1 de 09/11/2026).
`buscas` faz a mesma conferência antes de gravar o primeiro termo e aborta sem gravar se ela falhar.
Só entra item com link curto de afiliado da Shopee (servidor.eh_link_shopee), acima do piso de qualidade
(nota >= 4,5 e >= 50 vendas, P1 de 2026-11-04) e cujo título não é de usado (eh_usado).

`importar ARQUIVO` grava os itens capturados no painel de afiliados (affiliate.shopee.com.br), sem credencial:
não chama credenciais() nem lê o ambiente. O arquivo é entrada externa e é conferido inteiro antes de qualquer
gravação. Formato (JSON em UTF-8, até MAX_RESPOSTA bytes, objeto só com estas três chaves):
    {"cat": "<aba do buscas.json>", "busca": "<termo dessa aba no buscas.json>",
     "nos": [<de 1 a MAX_NOS_ARQUIVO nós no formato de um nó do productOfferV2>, ...]}
  Mapeamento mínimo de cada nó (o que o no_para_item lê; os demais campos são ignorados):
    itemId             "Item Id" do CSV do "Obter Link em Massa" (número ou texto só de dígitos)
    shopId             id da loja (na resposta da lista de ofertas do painel, ou no "Product Link" .../i.<shopId>.<itemId>)
    productName        nome do produto (texto)
    offerLink          "Offer Link" do CSV: https://s.shopee.com.br/<código>; qualquer outro link descarta o nó
    ratingStar, sales  nota de 0 a 5 e vendas (número ou texto como "4.8"); abaixo do piso, o nó é descartado
    priceMin           preço em reais (ex.: 49.9), opcional
    priceDiscountRate  desconto em % inteiro (ex.: 20), opcional
    imageUrl           foto em https://down-br.img.susercontent.com/..., opcional (de outro host, fica sem foto)
  A aba e o termo têm de existir no buscas.json (NFC). Antes de gravar, confere o dono de cada link distinto
  que passou no piso (utm_source=an_<ID>; uma requisição ao link curto por link, sem credencial e sem seguir
  redirect, com pausa entre elas); um só que falhe e nada é gravado. Grava pelo servidor.upsert e marca vendidos|<termo> no mesmo arquivo de
  progresso da Open API (a ordem "Mais vendidos" do painel), então os dois caminhos não repetem o termo.
  Nada do conteúdo do arquivo vai para a saída: só contagens e motivos fixos.

Trava por loja (servidor.travar_rodada): `buscas` e `importar` pegam `<banco>.rodada-shopee.lock` (ao lado do
ACHADINHOS_DB) sem esperar, antes do proteger_processo, do Secret, do arquivo, do banco e do progresso; outra rodada
da Shopee no ar (esta coleta ou o atualizar_precos.py shopee) faz sair com 4, sem tocar em nada. O `conferir` não
grava e não trava.

Saída: 0 ok (no `importar`, também quando nenhum nó passa no piso: o termo não é marcado); 1 erro (dono errado,
API recusou, resposta ou arquivo fora do formato, arquivo grande demais); 2 configuração (ID de afiliado,
credenciais, aba ou termo fora do buscas.json, arquivo inexistente ou ilegível, argumento); 3 limite de
requisições da API (o progresso fica salvo, rode de novo depois); 4 outra rodada da Shopee em andamento, ou trava
recusada (só `buscas` e `importar`; espere a outra terminar); 130 interrompido.
"""
import argparse, hashlib, json, math, os, random, re, sys, time, unicodedata, urllib.error, urllib.parse, urllib.request
import servidor as S
import disparo as D

BASE = S.BASE
BUSCAS = os.path.join(BASE, 'buscas.json')
FEITOS = os.environ.get('ACHADINHOS_FEITOS_SHOPEE') or os.path.join(BASE, 'coleta_shopee_feitos.txt')

# ID de afiliado da Shopee do dono (Configurações da conta > Informações da conta). Não é segredo: aparece
# como utm_source=an_<ID> em todo link dele. Enquanto estiver vazio, o script não chama a API.
ID_AFILIADO_SHOPEE = '18328801339'

# ---------- formato da Open API: fontes de terceiros, tudo "a confirmar (F5)" no painel do dono ----------
URL_API = 'https://open-api.affiliate.shopee.com.br/graphql'   # a confirmar (F5): endpoint do Brasil
ORDENS = {'relevancia': 1, 'vendidos': 2, 'caros': 3}         # a confirmar (F5): sortType 1, 2 e 3
# Ordem padrão do `buscas` e do `conferir`: em relevância a busca devolve anúncios novos (0 a 3 vendas), todos abaixo do
# piso (medição de 18/11/2026: "perfume" 0 de 30 aproveitáveis em relevância, 25 de 30 em vendidos).
ORDEM_PADRAO = 'vendidos'
ERRO_LIMITE = 10030                                           # a confirmar (F5): código de limite de requisições
POR_BUSCA = 30                                                # a confirmar (F5): limit máximo por página
# a confirmar (F5): nome da consulta, dos argumentos e dos campos. O termo e a ordem vão só em "variables".
CONSULTA = '''query Busca($keyword: String, $sortType: Int, $page: Int, $limit: Int) {
  productOfferV2(keyword: $keyword, sortType: $sortType, page: $page, limit: $limit) {
    nodes { itemId shopId productName priceMin priceDiscountRate ratingStar sales imageUrl offerLink }
  }
}'''
# Consulta por item (plano atualizar-precos-shopee-por-item.md). a confirmar (G1): se a API filtra por shopId e itemId.
# shopId e itemId são Int64 no schema e vão nas variáveis como TEXTO de dígitos: como número JSON a API recusa com
# 10010 (medições #37 e #38 do garimpo, tools/garimpo_feminino/docs/api_interpretacao.md; repetido no G1 de 09/11/2026).
# O texto vem de str(int()) depois da validação do corpo_item; nunca dentro da query.
POR_ITEM = 5                                                  # a confirmar (G1): o filtro deve trazer 1 nó
MAX_ID_API = 2**63 - 1                                        # teto do Int64: id maior não vai à API
CONSULTA_ITEM = '''query PorItem($shopId: Int64, $itemId: Int64, $page: Int, $limit: Int) {
  productOfferV2(shopId: $shopId, itemId: $itemId, page: $page, limit: $limit) {
    nodes { itemId shopId productName priceMin priceDiscountRate ratingStar sales imageUrl offerLink }
  }
}'''

# Piso de qualidade decidido pelo dono (P1 de 2026-11-04, no lugar da P6): nota mínima 4,5 e pelo menos 50 vendas.
NOTA_MINIMA, VENDAS_MINIMAS = 4.5, 50
# Título de produto usado (Decisão 4 do plano abas-nichadas-e-coleta), sem acento e em minúsculas (ver `eh_usado`).
# Cópia do RE_USADO do coletar_amazon.py (e do RX_USADO do coletar_ml.js): mudar a lista exige mexer nos três.
RE_USADO = re.compile(r'\b(?:usad[oa]s?|recondicionad[oa]s?|renovad[oa]s?|seminov[oa]s?|vitrine|open\s+box|refurbished)\b')
MAX_RESPOSTA = 2 * 1024 * 1024   # bytes; resposta da API ou arquivo do `importar` maior é recusado (dado não confiável)
MAX_NOS_ARQUIVO = 100            # o "Obter Link em Massa" do painel gera até 100 links por lote
CHAVES_ARQUIVO = {'cat', 'busca', 'nos'}
ORDEM_IMPORTAR = 'vendidos'      # o painel é percorrido em "Mais vendidos": a chave de progresso é vendidos|<termo>
MAX_URL = 200                    # mesmo teto dos campos de texto do servidor (MAX_CAMPO)
TIMEOUT = 30
TERMO_CONFERENCIA = 'perfume'    # busca usada pelo `conferir`
DOMINIO_LOJA = 'shopee.com.br'   # destino do link curto


class Segredo:
    """Guarda o Secret sem deixá-lo aparecer em repr, str, f-string ou traceback com variáveis locais."""
    __slots__ = ('_valor',)

    def __init__(self, valor):
        self._valor = valor

    def valor(self):
        return self._valor

    def __repr__(self):
        return 'Segredo(***)'

    __str__ = __repr__

    def __format__(self, spec):
        return repr(self)


class ErroColeta(Exception):
    """Erro que vira mensagem curta, sem texto vindo de fora."""


class LimiteAtingido(ErroColeta):
    pass


class DonoErrado(ErroColeta):
    pass


class RespostaInvalida(ErroColeta):
    pass


class ArquivoInvalido(ErroColeta):
    """Arquivo do `importar` fora do formato. O motivo é texto fixo, nunca conteúdo do arquivo."""
    def __init__(self, motivo):
        super().__init__(motivo)
        self.motivo = motivo


class ArquivoAusente(ErroColeta):
    """Arquivo do `importar` inexistente, que não é arquivo comum ou que não pôde ser lido."""


class ForaDoBuscas(ErroColeta):
    """Aba ou termo do arquivo do `importar` que não está no buscas.json."""


class SemProduto(RespostaInvalida):
    """data.productOfferV2 veio null, sem "errors": na consulta por item, é o produto pedido que a API não tem."""


class ErroApi(ErroColeta):
    def __init__(self, codigo=None, http=None):
        super().__init__(codigo, http)
        self.codigo, self.http = codigo, http


# Códigos que recusam a requisição inteira, não um produto (fontes de terceiros, a confirmar F5): parse (10010),
# autenticação (10020), acesso, ID de afiliado e conta (10031 a 10035), parâmetro (11001) e conta vinculada (11002).
ERROS_GERAIS = frozenset({10010, 10020, 10031, 10032, 10033, 10034, 10035, 11001, 11002})


def erro_do_item(e):
    """True se o erro da consulta por item parece ser do produto pedido, não da requisição: productOfferV2 null
    (SemProduto) ou ErroApi com HTTP 200 (ou sem HTTP) e código numérico fora de ERROS_GERAIS e do limite (inclusive o
    10000, System Error intermitente). Qualquer outro status, código geral ou erro sem código é geral."""
    if isinstance(e, SemProduto):
        return True
    return (isinstance(e, ErroApi) and e.http in (None, 200) and isinstance(e.codigo, int)
            and not isinstance(e.codigo, bool) and e.codigo not in ERROS_GERAIS and e.codigo not in (0, ERRO_LIMITE))


# ---------- funções puras ----------
def assinar(app_id, ts, corpo, secret):
    """Assinatura da Open API: sha256(AppID + Timestamp + corpo + Secret) em hexadecimal. a confirmar (F5)."""
    return hashlib.sha256(f'{app_id}{ts}{corpo}{secret}'.encode('utf-8')).hexdigest()


def autorizacao(app_id, ts, assinatura):
    """Cabeçalho Authorization (a confirmar, F5). Leva só a assinatura, nunca o Secret."""
    return f'SHA256 Credential={app_id}, Timestamp={ts}, Signature={assinatura}'


def corpo_consulta(termo, sort_type):
    """Corpo JSON da busca. O termo e a ordem vão como variáveis GraphQL, nunca dentro da query."""
    return json.dumps({'query': CONSULTA,
                       'variables': {'keyword': termo, 'sortType': sort_type, 'page': 1, 'limit': POR_BUSCA}},
                      separators=(',', ':'))


def corpo_item(shop, item):
    """Corpo JSON da consulta por item. Os ids vão nas variáveis GraphQL como texto de dígitos (Int64 do schema:
    número JSON dá 10010), nunca dentro da query.

    Aceita os ids como no banco (texto só de dígitos) ou como int. Id inválido ou acima do Int64 levanta
    ValueError com texto fixo, antes de qualquer rede. O texto vem de str(int()): zero à esquerda some ('007' → '7').
    """
    ids = [_inteiro(shop), _inteiro(item)]
    if not all(ids) or any(int(i) > MAX_ID_API for i in ids):
        raise ValueError('id da Shopee inválido para a consulta por item')
    return json.dumps({'query': CONSULTA_ITEM,
                       'variables': {'shopId': str(int(ids[0])), 'itemId': str(int(ids[1])), 'page': 1,
                                     'limit': POR_ITEM}},
                      separators=(',', ':'))


def _numero(v):
    """int, float ou texto numérico ("4.8", "12") → float finito; o resto → None."""
    if isinstance(v, bool):
        return None
    if isinstance(v, str) and re.fullmatch(r'\d{1,12}(\.\d{1,6})?', v.strip(), re.A):
        v = float(v)
    if isinstance(v, int) and abs(v) < 10**15 or isinstance(v, float) and math.isfinite(v):
        return float(v)
    return None


def _inteiro(v):
    """Identificador numérico (int ou dígitos) → texto só de dígitos; o resto → None."""
    if isinstance(v, bool):
        return None
    if isinstance(v, int) and 0 <= v < 10**20:
        return str(v)
    if isinstance(v, str) and re.fullmatch(r'\d{1,20}', v, re.A):
        return v
    return None


def _texto(v, teto):
    """Só texto: caracteres de controle viram espaço, os espaços se juntam e o texto é cortado no teto."""
    if not isinstance(v, str):
        return ''
    v = ''.join(' ' if ord(c) < 32 or 0x7f <= ord(c) <= 0x9f else c for c in v)
    return ' '.join(v.split())[:teto]


def _milhar(n, casas=0):
    return f'{n:,.{casas}f}'.replace(',', '_').replace('.', ',').replace('_', '.')


def sem_acento(texto):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(texto or '')) if not unicodedata.combining(c)).lower()


def eh_usado(titulo):
    """Título de usado, recondicionado, seminovo, renovado, de vitrine ou open box, sem acento e com `\\b`."""
    return bool(RE_USADO.search(sem_acento(titulo)))


def passa_piso(nota, vendas):
    return nota is not None and vendas is not None and nota >= NOTA_MINIMA and vendas >= VENDAS_MINIMAS


def imagem_da_shopee(url):
    """Foto só do CDN da Shopee (disparo.HOST_FOTO_SHOPEE), pela mesma regra do disparo."""
    if not isinstance(url, str) or len(url) > MAX_URL or not D.imagem_permitida(url, 'shopee'):
        return ''
    return url if urllib.parse.urlsplit(url).hostname == D.HOST_FOTO_SHOPEE else ''


def no_para_item(no, termo, cat):
    """Um nó de productOfferV2 → item do upsert, ou None se não puder entrar.

    Descarta: link que não é o curto de afiliado da Shopee, ids inválidos, sem título, título de usado
    (eh_usado) e abaixo do piso.
    """
    if not isinstance(no, dict):
        return None
    link = no.get('offerLink')
    if not isinstance(link, str) or len(link) > MAX_URL or not S.eh_link_shopee(link):
        return None
    shop, item = _inteiro(no.get('shopId')), _inteiro(no.get('itemId'))
    titulo = _texto(no.get('productName'), S.MAX_TITULO)
    if not shop or not item or not titulo or eh_usado(titulo):
        return None
    nota, vendas = _numero(no.get('ratingStar')), _numero(no.get('sales'))
    if not passa_piso(nota, vendas):
        return None
    preco = _numero(no.get('priceMin'))
    taxa = _numero(no.get('priceDiscountRate'))
    vendas = int(vendas)
    data = {
        'titulo': titulo,
        'preco': f'R$ {_milhar(preco, 2)}' if preco and 0 < preco < 10**9 else '',
        'preco_antigo': '',   # a API não dá o preço cheio: nada de preço inventado
        'desconto': f'-{int(taxa)}%' if taxa and 1 <= taxa < 100 else '',
        'avaliacao': f'{min(nota, 5.0):.1f} de 5 estrelas',
        'num_avaliacoes': '',
        'vendas': f'{_milhar(vendas)} vendido' + ('' if vendas == 1 else 's'),
        'frete': '', 'cupom': '',
        'imagem': imagem_da_shopee(no.get('imageUrl')),
    }
    it = {'loja': 'shopee', 'item_id': f'{shop}.{item}', 'cat': cat, 'busca': termo, 'url': link, 'data': data}
    try:
        S.conferir_tipos(it, ('url', 'item_id', 'cat', 'busca'))
    except S.ErroCliente:
        return None
    return it


def no_do_item(nos, shop, item):
    """O nó de `nos` cujo shopId e itemId são os pedidos, ou None (CA1: nó de outro id não vale).

    Compara pelo `_inteiro`, a mesma regra do item_id que o no_para_item monta: int ou texto só de dígitos;
    bool, float, texto com sinal, espaço ou outro caractere não casam.
    """
    alvo = (_inteiro(shop), _inteiro(item))
    if not all(alvo) or not isinstance(nos, list):
        return None
    for no in nos:
        if isinstance(no, dict) and (_inteiro(no.get('shopId')), _inteiro(no.get('itemId'))) == alvo:
            return no
    return None


def preco_legivel(no):
    """O priceMin do nó vira preço gravável, pela mesma regra do no_para_item."""
    preco = _numero(no.get('priceMin')) if isinstance(no, dict) else None
    return bool(preco and 0 < preco < 10**9)


def dono_ok(location):
    """Destino do link curto é da Shopee e traz utm_source=an_<ID_AFILIADO_SHOPEE> (forma oficial de conferir)."""
    if not id_afiliado_ok() or not isinstance(location, str) or any(c.isspace() for c in location):
        return False
    try:
        p = urllib.parse.urlsplit(location)
        porta = p.port
    except ValueError:
        return False
    host = p.hostname or ''
    if (p.scheme != 'https' or p.username is not None or p.password is not None or porta not in (None, 443)
            or not (host == DOMINIO_LOJA or host.endswith('.' + DOMINIO_LOJA))):
        return False
    return urllib.parse.parse_qs(p.query).get('utm_source') == [f'an_{ID_AFILIADO_SHOPEE}']


def id_afiliado_ok():
    return isinstance(ID_AFILIADO_SHOPEE, str) and re.fullmatch(r'[0-9]{1,20}', ID_AFILIADO_SHOPEE, re.A) is not None


def codigo_de_erro(resposta):
    """Código da Shopee no primeiro item de "errors" (extensions.code, a confirmar F5).

    Aceita inteiro ou texto só com dígitos ("10030"). None quando não há erro; 0 quando há erro sem
    código numérico.
    """
    erros = resposta.get('errors') if isinstance(resposta, dict) else None
    if not isinstance(erros, list) or not erros:
        return None
    ext = erros[0].get('extensions') if isinstance(erros[0], dict) else None
    codigo = ext.get('code') if isinstance(ext, dict) else None
    if isinstance(codigo, str) and re.fullmatch(r'[0-9]{1,9}', codigo, re.A):
        return int(codigo)
    return codigo if isinstance(codigo, int) and not isinstance(codigo, bool) else 0


def nos_da_resposta(resposta):
    """Lista de nós de data.productOfferV2.nodes (a confirmar, F5). Levanta LimiteAtingido/ErroApi/RespostaInvalida."""
    if not isinstance(resposta, dict):
        raise RespostaInvalida()
    codigo = codigo_de_erro(resposta)
    if codigo == ERRO_LIMITE:
        raise LimiteAtingido()
    if codigo is not None:
        raise ErroApi(codigo)
    try:
        oferta = resposta['data']['productOfferV2']
    except (KeyError, TypeError):
        raise RespostaInvalida() from None
    if oferta is None:
        raise SemProduto()
    try:
        nos = oferta['nodes']
    except (KeyError, TypeError):
        raise RespostaInvalida() from None
    if not isinstance(nos, list):
        raise RespostaInvalida()
    return nos[:POR_BUSCA]


# ---------- ambiente ----------
AVISO_PROCESSO = ('AVISO: o sistema não deixou fechar o /proc/<pid>/environ deste processo; outro processo do seu '
                  'usuário pode ler o ambiente (com o Secret) enquanto o comando durar.')


def proteger_processo():
    """PR_SET_DUMPABLE = 0 (o mesmo do tools/garimpo_feminino/garimpo.py): outro processo do mesmo usuário não lê o
    /proc/<pid>/environ, onde o Secret fica até o fim do comando (o pop só tira do os.environ). Chame antes de ler a
    credencial. True se o sistema aceitou; False em qualquer falha (fora do Linux, por exemplo), sem levantar."""
    try:
        import ctypes
        return ctypes.CDLL(None, use_errno=True).prctl(4, 0, 0, 0, 0) == 0
    except (ImportError, OSError, AttributeError):
        return False


def credenciais():
    """(AppID, Segredo) do ambiente, ou None se faltar algum ou o AppID tiver formato estranho.

    O Secret sai do os.environ do processo (pop): não fica para subprocesso nem para quem ler o ambiente.
    """
    app_id = os.environ.get('ACHADINHOS_SHOPEE_APP_ID') or ''
    secret = os.environ.pop('ACHADINHOS_SHOPEE_SECRET', '') or ''
    if not secret or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', app_id, re.A):
        return None
    return app_id, Segredo(secret)


def termos_da_aba(cat):
    """Termos da aba do buscas.json (gravado em NFC). A aba chega normalizada pelo ler_argumentos."""
    cat = unicodedata.normalize('NFC', cat)
    with open(BUSCAS, encoding='utf-8') as f:
        buscas = json.load(f)
    termos = buscas.get(cat) if isinstance(buscas, dict) else None
    return [t for t in termos if isinstance(t, str) and t] if isinstance(termos, list) else None


def feitos():
    if not os.path.exists(FEITOS):
        return set()
    with open(FEITOS, encoding='utf-8') as f:
        return set(f.read().splitlines())


def marcar(chave):
    with open(FEITOS, 'a', encoding='utf-8') as f:
        f.write(chave + '\n')


def chave(ordem, termo):
    return f'{ordem}|{termo}'


def pausa(a=1, b=3):
    time.sleep(random.uniform(a, b))


# ---------- rede ----------
def _ler_json(r):
    bruto = r.read(MAX_RESPOSTA + 1)
    if len(bruto) > MAX_RESPOSTA:
        raise RespostaInvalida()
    try:
        return json.loads(bruto)
    except (ValueError, RecursionError):
        raise RespostaInvalida() from None


class SemRedirecionar(urllib.request.HTTPRedirectHandler):
    """Nenhum redirect é seguido: a API não reenvia o Authorization para outro host e a conferência
    lê só o Location do link curto. O 3xx vira HTTPError."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


OPENER_API = urllib.request.build_opener(SemRedirecionar)


def _pedir(cred, corpo):
    """POST assinado do corpo para a URL fixa da API e lista de nós da resposta. Único ponto que fala com a API.

    Não recebe URL: o Secret assina toda requisição e só vai para URL_API. Levanta LimiteAtingido (10030 ou
    HTTP 429), ErroApi (só código e status) ou RespostaInvalida.
    """
    app_id, segredo = cred
    ts = int(time.time())
    req = urllib.request.Request(URL_API, data=corpo.encode('utf-8'), method='POST', headers={
        'Content-Type': 'application/json', 'User-Agent': S.UA,
        'Authorization': autorizacao(app_id, ts, assinar(app_id, ts, corpo, segredo.valor()))})
    try:
        with OPENER_API.open(req, timeout=TIMEOUT) as r:
            resposta = _ler_json(r)
    except urllib.error.HTTPError as e:
        try:
            codigo = codigo_de_erro(_ler_json(e))
        except Exception:
            codigo = None
        finally:
            e.close()
        if codigo == ERRO_LIMITE or e.code == 429:
            raise LimiteAtingido() from None
        raise ErroApi(codigo, e.code) from None   # inclusive 3xx: o redirect não é seguido
    return nos_da_resposta(resposta)


def buscar(cred, termo, ordem):
    """Uma página de productOfferV2 para o termo na ordem."""
    return _pedir(cred, corpo_consulta(termo, ORDENS[ordem]))


def buscar_item(cred, shop, item):
    """Nós de productOfferV2(shopId, itemId). A API pode ignorar o filtro: use no_do_item para achar o pedido."""
    return _pedir(cred, corpo_item(shop, item))


OPENER_CONFERENCIA = urllib.request.build_opener(SemRedirecionar)


def destino(link):
    """Location do 3xx do link curto, ou None se ele não redirecionar."""
    if not S.eh_link_shopee(link):
        return None
    req = urllib.request.Request(link, headers={'User-Agent': S.UA})
    try:
        with OPENER_CONFERENCIA.open(req, timeout=TIMEOUT):
            return None
    except urllib.error.HTTPError as e:   # 3xx não seguido vira HTTPError; 4xx/5xx também não confere
        try:
            return e.headers.get('Location') if e.code in (301, 302, 303, 307, 308) else None
        finally:
            e.close()


def conferir_dono(link):
    if not dono_ok(destino(link)):
        raise DonoErrado()


# ---------- comandos ----------
def gravar(itens):
    con = S.conectar(); c = {'inserido': 0, 'atualizado': 0}
    try:
        for it in itens:
            c[S.upsert(con, it)] += 1
        con.commit()
    finally:
        con.close()
    return c


def conferir(cred, por_item=False):
    """Uma busca e a conferência do dono. Com por_item (portão G1), depois dela consulta por item o primeiro
    nó válido da busca: 0 só se voltar o mesmo produto com preço legível."""
    itens = [i for i in (no_para_item(n, TERMO_CONFERENCIA, '') for n in buscar(cred, TERMO_CONFERENCIA, ORDEM_PADRAO)) if i]
    if not itens:
        print(f'A busca "{TERMO_CONFERENCIA}" não trouxe link para conferir. Tente de novo mais tarde.', flush=True)
        return 1
    conferir_dono(itens[0]['url'])
    print(f'OK: o link gerado pela API é do afiliado {ID_AFILIADO_SHOPEE}.', flush=True)
    if not por_item:
        return 0
    shop, item = itens[0]['item_id'].split('.')
    pausa()
    no = no_do_item(buscar_item(cred, shop, item), shop, item)
    if no is None:
        print('PAROU: a consulta por item não devolveu o produto pedido (shopId e itemId). '
              'Não rode o atualizar_precos.py shopee; leve esta saída ao lead.', file=sys.stderr, flush=True)
        return 1
    it = no_para_item(no, TERMO_CONFERENCIA, '')   # o mesmo filtro da rodada: sem ele, todo item seria indisponível
    if it is None:
        print('PAROU: a consulta por item devolveu o produto pedido, mas a rodada o recusaria (sem link curto de '
              'afiliado, sem título, abaixo do piso ou de usado). '
              'Não rode o atualizar_precos.py shopee; leve esta saída ao lead.', file=sys.stderr, flush=True)
        return 1
    if not preco_legivel(no):
        print('PAROU: a consulta por item devolveu o produto pedido, mas sem preço legível (priceMin). '
              'Não rode o atualizar_precos.py shopee; leve esta saída ao lead.', file=sys.stderr, flush=True)
        return 1
    print('OK: a consulta por item (shopId e itemId) devolveu o produto pedido, com preço.', flush=True)
    # só ids e preço (nada de título nem link): o dono confere no site que a ordem de grandeza bate
    print(f'Produto {it["item_id"]}: preço lido {it["data"]["preco"]}. Abra esse produto no site da Shopee e confira '
          'que o preço tem a mesma ordem de grandeza (não 100 vezes maior nem menor).', flush=True)
    return 0


def coletar_buscas(cred, cat, termos, ordens):
    ja, conferido = feitos(), False
    for termo in termos:
        for ordem in ordens:
            k = chave(ordem, termo)
            if k in ja:
                continue
            nos = buscar(cred, termo, ordem)
            itens = [i for i in (no_para_item(n, termo, cat) for n in nos) if i]
            if not itens:
                print(f'[{cat}] {termo} ({ordem}): {len(nos)} achados, nenhum no piso; fica para a próxima rodada', flush=True)
                pausa()
                continue
            if not conferido:   # antes de gravar o primeiro termo: o link tem que ser do dono
                conferir_dono(itens[0]['url'])
                conferido = True
            c = gravar(itens)
            print(f'[{cat}] {termo} ({ordem}): {len(nos)} achados, {len(itens)} no piso, {c["inserido"]} novos', flush=True)
            marcar(k); pausa()


def ler_arquivo(caminho):
    """(cat, busca, nos) do arquivo do `importar`, com cat e busca em NFC. Confere teto de bytes e tipos.

    Levanta ArquivoAusente (saída 2) ou ArquivoInvalido (saída 1). Nada do conteúdo vai para a exceção.
    """
    if not isinstance(caminho, str) or not os.path.isfile(caminho):
        raise ArquivoAusente()
    try:
        with open(caminho, 'rb') as f:
            bruto = f.read(MAX_RESPOSTA + 1)
    except OSError:
        raise ArquivoAusente() from None
    if len(bruto) > MAX_RESPOSTA:
        raise ArquivoInvalido(f'maior que {MAX_RESPOSTA} bytes')
    try:
        dados = json.loads(bruto)
    except (ValueError, RecursionError):
        raise ArquivoInvalido('não é JSON em UTF-8') from None
    if not isinstance(dados, dict) or set(dados) != CHAVES_ARQUIVO:
        raise ArquivoInvalido('o arquivo tem de ser um objeto só com cat, busca e nos')
    cat, busca, nos = dados['cat'], dados['busca'], dados['nos']
    if not all(isinstance(v, str) and 0 < len(v) <= S.MAX_CAMPO for v in (cat, busca)):
        raise ArquivoInvalido(f'cat e busca têm de ser texto de 1 a {S.MAX_CAMPO} caracteres')
    if (not isinstance(nos, list) or not 1 <= len(nos) <= MAX_NOS_ARQUIVO
            or not all(isinstance(n, dict) for n in nos)):
        raise ArquivoInvalido(f'nos tem de ser uma lista de 1 a {MAX_NOS_ARQUIVO} objetos')
    return unicodedata.normalize('NFC', cat), unicodedata.normalize('NFC', busca), nos


def importar(caminho):
    """Grava os nós de um arquivo capturado no painel de afiliados. Não usa credencial nem lê o ambiente.

    Ordem: arquivo inteiro conferido → aba e termo no buscas.json → piso (no_para_item) → dono de cada link
    distinto que passou no piso, com pausa entre um e outro → criar_banco e gravar → marcar vendidos|<termo>.
    Um link de outro afiliado (ou que não confere) para tudo antes de gravar. A saída traz só contagens.
    """
    cat, busca, nos = ler_arquivo(caminho)
    termos = termos_da_aba(cat)
    if not termos or busca not in termos or '|' in busca or any(ord(c) < 32 for c in busca):
        raise ForaDoBuscas()
    itens = [i for i in (no_para_item(n, busca, cat) for n in nos) if i]
    if not itens:
        print(f'importar: {len(nos)} no arquivo, nenhum no piso; o termo fica para a próxima rodada.', flush=True)
        return 0
    # antes de gravar: todo link tem que ser do dono (o arquivo vem de fora, cada nó pode ter vindo de outra conta)
    for n, link in enumerate(dict.fromkeys(i['url'] for i in itens)):
        if n:
            pausa()
        conferir_dono(link)
    S.criar_banco()
    c = gravar(itens)
    k = chave(ORDEM_IMPORTAR, busca)
    if k not in feitos():
        marcar(k)
    print(f'importar: {len(nos)} no arquivo, {len(itens)} no piso, {c["inserido"]} novos, '
          f'{c["atualizado"]} atualizados.', flush=True)
    con = S.conectar()
    try:
        print('TOTAL da Shopee no banco:', con.execute("SELECT COUNT(*) FROM items WHERE loja='shopee'").fetchone()[0])
    finally:
        con.close()
    return 0


def ler_argumentos(argv):
    p = argparse.ArgumentParser(prog='coletar_shopee.py',
                                description='Coleta da Shopee pela Open API de afiliados ou por arquivo do painel.')
    sub = p.add_subparsers(dest='modo', required=True)
    c = sub.add_parser('conferir', help='confere que o link gerado pela API é do dono; não grava nada')
    c.add_argument('--por-item', action='store_true',
                   help='depois, consulta por shopId e itemId o primeiro item da busca (portão G1)')
    b = sub.add_parser('buscas', help='coleta os termos de uma aba do buscas.json')
    b.add_argument('--cat', required=True, help='aba do buscas.json')
    b.add_argument('--ordens', default=ORDEM_PADRAO, help='lista separada por vírgula: ' + ','.join(ORDENS))
    i = sub.add_parser('importar', help='grava os itens de um arquivo capturado no painel de afiliados; sem credencial')
    i.add_argument('arquivo', help='JSON {cat, busca, nos} (formato no topo do coletar_shopee.py)')
    args = p.parse_args(argv)
    if args.modo == 'buscas':
        ordens = [o.strip() for o in args.ordens.split(',') if o.strip()]
        ruins = [o for o in ordens if o not in ORDENS]
        if not ordens or ruins or len(set(ordens)) != len(ordens):
            p.error('--ordens aceita ' + ', '.join(ORDENS) + ', sem repetir')
        args.ordens = ordens
        # o terminal pode mandar a aba em NFD; o buscas.json e a coluna cat estão em NFC (como no coletar_amazon)
        args.cat = unicodedata.normalize('NFC', args.cat)
    return args


def _rodar_importar(caminho):
    """importar() com as saídas 0/1/2. As mensagens são fixas: nada do arquivo nem da exceção vai para a tela."""
    try:
        return importar(caminho)
    except ArquivoAusente:
        print('ERRO: o arquivo do importar não existe ou não pôde ser lido.', file=sys.stderr, flush=True)
        return 2
    except ForaDoBuscas:
        print('ERRO: a aba ou o termo do arquivo não está no buscas.json. Nada foi gravado.', file=sys.stderr, flush=True)
        return 2
    except ArquivoInvalido as e:
        print(f'ERRO: arquivo do importar fora do formato ({e.motivo}). Nada foi gravado.', file=sys.stderr, flush=True)
        return 1
    except DonoErrado:
        print(f'PAROU: um link do arquivo não leva a utm_source=an_{ID_AFILIADO_SHOPEE}. Nada foi gravado. '
              'Confira a conta logada no painel e o ID_AFILIADO_SHOPEE.', file=sys.stderr, flush=True)
        return 1
    except KeyboardInterrupt:
        print('Interrompido.', file=sys.stderr, flush=True)
        return 130
    except Exception as e:   # só o tipo: a mensagem pode trazer o link ou outro dado do arquivo
        print(f'ERRO: {type(e).__name__}', file=sys.stderr, flush=True)
        return 1


def main(argv=None):
    args = ler_argumentos(argv)
    if not id_afiliado_ok():
        print('ERRO: preencha ID_AFILIADO_SHOPEE no coletar_shopee.py (só números, o <ID> de utm_source=an_<ID>).',
              file=sys.stderr, flush=True)
        return 2
    if args.modo == 'conferir':   # não grava nada: não trava (roda mesmo com outra rodada da Shopee no ar)
        return _rodar_api(args)
    try:
        # buscas e importar gravam: a trava vem antes do proteger_processo, do Secret, do arquivo, do banco e do
        # progresso. Pega ou não pega na hora (sem espera).
        with S.travar_rodada('shopee'):
            if args.modo == 'importar':   # sem credencial: não chama credenciais() nem lê o ambiente
                return _rodar_importar(args.arquivo)
            return _rodar_api(args)
    except S.RodadaEmAndamento as e:   # só a entrada da trava levanta isto
        print(f'PAROU: {e}', file=sys.stderr, flush=True)
        return 4


def _rodar_api(args):
    """conferir e buscas: proteger_processo, credenciais e a Open API, com as saídas 0/1/2/3/130."""
    if not proteger_processo():   # antes de ler o Secret
        print(AVISO_PROCESSO, file=sys.stderr, flush=True)
    cred = credenciais()
    if cred is None:
        print('ERRO: defina ACHADINHOS_SHOPEE_APP_ID e ACHADINHOS_SHOPEE_SECRET só para este comando, sem export, '
              'num terminal só para isso: read -rs S; ACHADINHOS_SHOPEE_SECRET="$S" '
              'ACHADINHOS_SHOPEE_APP_ID=<id> python3 coletar_shopee.py ...; unset S', file=sys.stderr, flush=True)
        return 2
    try:
        if args.modo == 'conferir':
            return conferir(cred, args.por_item)
        termos = termos_da_aba(args.cat)
        if not termos:
            print('ERRO: aba sem termos no buscas.json.', file=sys.stderr, flush=True)
            return 2
        S.criar_banco()
        coletar_buscas(cred, args.cat, termos, args.ordens)
        con = S.conectar()
        try:
            print('TOTAL da Shopee no banco:', con.execute("SELECT COUNT(*) FROM items WHERE loja='shopee'").fetchone()[0])
        finally:
            con.close()
        return 0
    except LimiteAtingido:
        print(f'PAROU: limite de requisições da API da Shopee (código {ERRO_LIMITE}). O progresso foi salvo; '
              'espere e rode de novo.', file=sys.stderr, flush=True)
        return 3
    except DonoErrado:
        print(f'PAROU: o link gerado não leva a utm_source=an_{ID_AFILIADO_SHOPEE}. Nada foi gravado. '
              'Confira as credenciais e o ID_AFILIADO_SHOPEE.', file=sys.stderr, flush=True)
        return 1
    except ErroApi as e:
        detalhe = ', '.join(x for x in (f'código {e.codigo}' if e.codigo is not None else '',
                                        f'HTTP {e.http}' if e.http is not None else '') if x)
        print(f'ERRO: a API da Shopee recusou ({detalhe or "sem código"}).', file=sys.stderr, flush=True)
        return 1
    except RespostaInvalida:
        print('ERRO: resposta da API da Shopee fora do formato esperado.', file=sys.stderr, flush=True)
        return 1
    except KeyboardInterrupt:
        print('Interrompido. O progresso dos termos já gravados foi salvo.', file=sys.stderr, flush=True)
        return 130
    except Exception as e:   # só o tipo: a mensagem de biblioteca pode trazer dados da requisição
        print(f'ERRO: {type(e).__name__}', file=sys.stderr, flush=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())
