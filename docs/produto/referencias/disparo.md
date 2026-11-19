# Referência: disparo e público (`disparo.py` e `genero.py`)

Contrato dos módulos, movido do `CLAUDE.md` em 17/11/2026 (plano `docs/produto/planos/endurecer-entrega2.md`, etapa 5). O `CLAUDE.md` guarda o mapa, as armadilhas que cruzam áreas e as regras de segredo, de LGPD e de afiliado, que valem aqui também.

## `disparo.py`

**Regra de negócio.** Disparo automático (plano `docs/produto/planos/disparo-automatico.md`, spec `docs/produto/specs/disparo-automatico.md`).

- Tabelas `numeros` (telefone e id de grupo: dado pessoal, só no banco local, mascarado na tela, nunca em log/URL/git), `regras` e `envios`.
- Migração por `PRAGMA user_version`, só aditiva, feita em `criar_banco`; hoje v3: v2 trouxe a tabela `generos_manuais` e a coluna `regras.generos`, v3 a coluna `items.preco_em`, preenchida com `criado_em` na migração; migra ao reiniciar o servidor ou rodar uma coleta, então faça backup antes.
- A regra tem filtro de público `generos` (lista; vazia = todos; vale só para as abas de `genero.ABAS_COM_GENERO`, as outras passam inteiras).
- `montar_mensagem` é porte fiel do `buildMsg` (paridade em `testes/mensagens.test.html`).
- Só sai link de afiliado (ML sem `meli.la` nunca sai; mensagem com qualquer outra URL não é criada).
- Agendador em thread no `servidor.py` (`ACHADINHOS_DISPARO=0` desliga; `ACHADINHOS_TICK_SEG`, padrão 30).
- Transporte `manual` (fila: o dono copia e cola) ou `falso` (`ACHADINHOS_TRANSPORTE`, `ACHADINHOS_TRANSPORTE_ARQUIVO`, só teste).
- Rotas `/api/disparo/*` só da origem local.
- Detecção de links na mensagem é conservadora, token a token (NFKC, pontos parecidos, invisíveis, IP): títulos como `i.Phone` ou `55UN85CBPSA.BWZ` são recusados de propósito (14 itens reais).
- A montagem para em `LIMITE_MONTAGEM` (8.000 caracteres) e a mensagem acima de `MAX_MENSAGEM` (4.000) é pulada.
- Horário sem nenhuma mensagem grava `aviso` na regra (filtros, repetição ou link recusado); `recusados` (só em memória) sai no `GET regras` e na prévia com `"com_info": true`, que traz também `preco_velho`.
- Trava de preço velho: o `elegiveis` só escolhe item com `preco_em` dentro de `config.preco_validade_horas` (`validade_horas`, padrão 24, de 1 a 168; inválido vale 24); `preco_recente`/`ler_preco_em` aceitam só `AAAA-MM-DDTHH:MM:SS` válido, e mais de 5 min no futuro conta como velho; horário sem mensagem só por isso grava `AVISO_PRECO_VELHO`.
- A mesma regra vale no front (`precoVelho`) e no filtro `preco_max_horas` da v1.
- A foto do envio (`com_foto`) sai na versão grande do CDN da loja (`foto_grande(url, loja)`, função pura: Amazon `._AC_SL1000_`, ML `-F.jpg`, Shopee sem `_tn`; o banco guarda a miniatura).
- Um host novo da Shopee entra também no `HOSTS_AFILIADO_SHOPEE` daqui (veja o `CLAUDE.md`, armadilhas).

## `genero.py`

**Regra de negócio.** Plano `docs/produto/planos/genero-nas-categorias.md`, spec `docs/produto/specs/genero-e-ux.md`.

- Público (gênero) do produto, calculado na leitura (`classificar`, `do_item`, `manuais`, `definir_manual`): correção manual (tabela `generos_manuais`) > título > linha de produto conhecida > termo `busca`; valores `feminino`, `masculino`, `unissex`, `sem`; só as abas de `ABAS_COM_GENERO` (hoje "Perfumes e Perfumaria", "Beleza e Cuidados" e "Moda e Viagem") têm gênero.
- Correção pelo site em `PUT /api/items/<id>/genero` (corpo só `{"genero": valor|null}`, só origem local, fora de `ROTAS_ML`; mexe em `atualizado_em`).
- Os itens do `GET /api/items` trazem `genero`, `genero_origem` e `genero_auto`.
- Aba nova com gênero: mudar `ABAS_COM_GENERO` em `genero.py` e no `index.html` (`test_front_constantes.py` confere).

## Histórico

- Envio automático pelo WhatsApp fica para uma entrega 2 (o dono escolheu ficar no manual).
