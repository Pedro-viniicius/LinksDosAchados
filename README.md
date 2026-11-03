# Etiqueta

(Repositório `LinksDosAchados`.) Gerador de mensagens de ofertas ("achadinhos") para grupos de WhatsApp: o dono coleta produtos da Amazon e do Mercado Livre, escolhe um template e copia a mensagem pronta, sempre com link de afiliado. Uso local, uma pessoa, no computador.

## Subir o servidor

```
python3 servidor.py        # http://localhost:8765/
```

Variáveis de ambiente (todas opcionais):

- `ACHADINHOS_DB`: caminho do banco SQLite (padrão `achadinhos.db` ao lado do `servidor.py`).
- `ACHADINHOS_PORTA`: porta do servidor (padrão `8765`).
- `ACHADINHOS_FEITOS`: arquivo de progresso do `coletar_amazon.py` (padrão `coleta_amazon_feitos.txt`).

## Testes

Use sempre proxies mortos, para nenhum teste sair para a rede:

```
export http_proxy=http://127.0.0.1:9 https_proxy=http://127.0.0.1:9 ftp_proxy=http://127.0.0.1:9
python3 -m py_compile servidor.py coletar_amazon.py migrar_categorias.py disparo.py classificar_lista.py
python3 testes/test_servidor.py -v
python3 testes/test_migrar_categorias.py -v
python3 testes/test_coletar_amazon.py -v
python3 testes/test_disparo.py -v
python3 testes/test_disparo_servidor.py -v
python3 testes/test_classificar_lista.py -v
node --test testes/coletar_ml.test.mjs
python3 testes/test_servidor_qa.py -v
python3 testes/test_migrar_categorias_qa.py -v
python3 testes/test_coletar_amazon_qa.py -v
python3 testes/test_disparo_qa.py -v
python3 testes/test_classificar_lista_qa.py -v
node --test testes/coletar_ml_qa.test.mjs
```

Os testes que falam com o servidor sobem o `servidor.py` como subprocesso, com banco temporário e porta livre; os outros rodam em memória. Nenhum toca no banco real.

Os testes do front precisam de Node 22+ e do Chrome. Rode-os sobre uma cópia do banco (veja "Backup"), com o servidor de teste na 8766. Para a página das abas, a cópia tem que estar migrada:

```
ACHADINHOS_DB=/caminho/copia.db ACHADINHOS_PORTA=8766 python3 servidor.py
PORTA=8766 node testes/rodar.mjs abas
PORTA=8766 node testes/rodar.mjs copiar-imagem
PORTA=8766 node testes/rodar.mjs abrir-e-adicionar
PORTA=8766 node testes/rodar.mjs mensagens
```

A página `disparo` testa a tela do disparo com um servidor falso dentro dela: só lê os itens do servidor sob teste. Suba esse servidor com o agendador desligado, para nenhuma regra gerar envio durante o teste:

```
ACHADINHOS_DB=/caminho/copia.db ACHADINHOS_PORTA=8766 ACHADINHOS_DISPARO=0 python3 servidor.py
PORTA=8766 node testes/rodar.mjs disparo
```

## Backup

O banco está em modo WAL: não use `cp`. Faça a cópia com a API `backup` do SQLite (lê o banco em modo somente leitura e pode rodar com o servidor no ar). Rode na pasta do projeto, porque os caminhos são relativos:

```
mkdir -p backups
python3 -c "import sqlite3,time;s=sqlite3.connect('file:achadinhos.db?mode=ro',uri=True);d=sqlite3.connect('backups/achadinhos-manual-'+time.strftime('%Y%m%d-%H%M%S')+'.db');s.backup(d);d.close()"
```

O `migrar_categorias.py` guarda os dele na mesma pasta, como `backups/achadinhos-AAAAMMDD-HHMMSS.db`. A pasta `backups/` está fora do git (`*.db` no `.gitignore`). Apague os backups antigos à mão quando não precisar mais deles.

**Voltar a um backup à mão** (quando o `--restaurar` recusa, por exemplo com o banco corrompido): pare o `servidor.py` e o `coletar_amazon.py` e faça:

```
D=backups/antes-de-voltar-$(date +%Y%m%d-%H%M%S); mkdir -p "$D"
mv achadinhos.db achadinhos.db-wal achadinhos.db-shm "$D"/   # -wal e -shm podem não existir
cp backups/<arquivo>.db achadinhos.db
```


Suba o servidor e confira `curl -s -o /dev/null -w "%{http_code}" localhost:8765/api/items` (200). O que foi gravado depois do backup se perde.

## Reorganizar abas

`migrar_categorias.py` troca a coluna `cat` dos itens das abas antigas ("Black Friday" e "Casa Nova") pela aba do termo de busca, segundo `buscas.json` (mapa termo → aba). Termos usados só no Mercado Livre herdam a aba de outro termo pelo `ALIAS` do script. Item sem destino aborta a migração sem gravar nada.

```
python3 migrar_categorias.py --dry-run     # mostra as contagens; não grava nem faz backup
python3 migrar_categorias.py               # backup verificado + migração numa transação só
```

- No banco real, gravar pede confirmação: digite `sim` quando o script perguntar, ou passe `--sim`.
- Pode rodar com o `servidor.py` no ar (o servidor espera a transação). Recarregue a página depois.
- É idempotente: rodar de novo dá "0 itens movidos" e não cria backup.
- Antes de gravar, o script faz o backup em `backups/` e confere `integrity_check` e a contagem de itens; se falhar, nada é migrado.

**Reverter:** pare o `servidor.py` e o `coletar_amazon.py` e rode (no banco real, o `--restaurar` também pede `sim`, ou passe `--sim`)

```
python3 migrar_categorias.py --restaurar backups/<arquivo>.db
```

Ele recusa se o servidor estiver no ar e, antes de sobrescrever, guarda o estado atual em `backups/` (dá para desfazer o desfazer). O `migrar_categorias.py --restaurar` devolve o banco **inteiro**: números, regras e o histórico de envios criados depois do backup somem, e o "não repetir" recomeça do zero. O estado de antes fica em `backups/`, no backup que o `--restaurar` faz antes de sobrescrever. Para desfazer só a Lista WhatsApp, use `classificar_lista.py --desfazer`. Para um ajuste pontual, use "Mover para" no site.

**Lista WhatsApp.** Os 74 itens da aba "Lista WhatsApp" (vindos do chat) são todos de eletrônicos. `classificar_lista.py` os move para "Black Friday | Eletrônicos" e troca a `busca` pelo subtema de cada um, segundo `lista_whatsapp.json`. Rode **logo depois** do `migrar_categorias.py` (é ele que cria a aba de destino) e **antes de cadastrar qualquer número** no disparo:

```
python3 classificar_lista.py --dry-run     # mostra o que mudaria; não grava nem faz backup
python3 classificar_lista.py               # backup verificado + gravação numa transação só (pede "sim" ou --sim)
```

- Só mudam `cat`, `busca` e `atualizado_em`; o link de afiliado nunca é tocado. Item que não bate com o mapa (id e `item_id`) aborta tudo sem gravar. Rodar de novo imprime "Nada a classificar: 0 itens mudados" e não cria backup. Pode rodar com o servidor no ar.
- **Reverter só estes itens:** `python3 classificar_lista.py --desfazer` (aceita `--dry-run` e `--sim`) devolve os 74 a "Lista WhatsApp". A alternativa, `migrar_categorias.py --restaurar`, devolve o banco **inteiro** ao backup: números, regras e o histórico de envios criados depois dele somem, e o "não repetir" recomeça do zero (o estado de antes fica em `backups/`, no backup que o `--restaurar` faz antes de sobrescrever). Só vale logo depois da migração.
- Os links novos que entrarem pelo chat voltam a cair em "Lista WhatsApp" e podem ser reclassificados depois (com "Mover para" no site).

## Coleta da Amazon

```
python3 coletar_amazon.py buscas     # só os termos de buscas.json, sem passar pelo WhatsApp
```

Cada termo é gravado e marcado em `coleta_amazon_feitos.txt` quando termina; Ctrl+C e rodar de novo retoma de onde parou. A chave do progresso é o termo, então depois da migração só faltam os 28 termos de "Perfumes e Perfumaria". Esta coleta acessa a Amazon de verdade: nunca rode em teste.

## Coleta do Mercado Livre

Roda no Chrome (por causa do captcha), com o `coletar_ml.js`. Passo a passo:

1. Suba o `servidor.py`.
2. **Cole só o `coletar_ml.js` deste projeto.** Colar no console de uma conta logada código de outra fonte é perigoso. Copie o arquivo inteiro, cole no Console do DevTools (F12) e aperte Enter: isso só define `ColetaML`, nada roda sozinho.
3. Coleta: numa aba de `https://lista.mercadolivre.com.br`.
4. Links de afiliado: numa aba de `https://www.mercadolivre.com.br/afiliados/linkbuilder` (cole o arquivo de novo nela).

```
await ColetaML.coletar({termos: ColetaML.BUSCAS['Perfumes e Perfumaria']})
await ColetaML.afiliar({servidor: 'http://localhost:8765'})
```

API (`ColetaML`):

- `coletar({termos, servidor, enviar, pausa})`: busca cada termo, monta os itens e faz um POST em `<servidor>/api/items` com `cat` = aba do termo. `servidor` padrão `http://localhost:8765`; `enviar:false` só monta os itens em `ColetaML.estado.itens`, sem gravar; `pausa` é `[min, max]` em ms entre termos. O progresso fica no `localStorage` da aba, por servidor: termo já enviado não é coletado de novo.
- `afiliar({servidor, enviar, itens})`: troca a `url` dos itens do ML sem afiliado pelo link `https://meli.la/...` gerado no linkbuilder (PATCH). Com `enviar:false`, passe `itens: ['https://produto.mercadolivre.com.br/MLB-...']` para só ver o que trocaria.
- `parar()`: para depois do termo (ou lote) atual. `estado`: o resultado da última execução. `BUSCAS` e `ALIAS`: cópias de `buscas.json` e do `ALIAS` do `migrar_categorias.py`. `zerar(servidor)`: esquece o progresso guardado.

Cuidados:

- **Passe sempre `termos`.** Sem eles, a coleta busca todos os termos de `buscas.json`.
- Antes de `afiliar()`, confira na página do linkbuilder que a etiqueta é **`achadosmenicas`** e que **"Links curtos"** está ligado. O script recusa outra etiqueta e, se um lote inteiro vier sem `meli.la`, para: só aquele lote não é gravado (os anteriores ficam). Num lote misto, o item que volta sem `meli.la` é tentado de novo na mesma execução (repescagem em lote de até 10, no máximo 2 tentativas) e, se ainda assim não vier, fica "sem resposta" para a próxima execução; os que vieram certos são gravados.
- **Itens inelegíveis** (o ML não gera link de afiliado) aparecem no console no fim do `afiliar()`. O script nunca apaga nada: exclua-os pelo site. Enquanto `GET /api/ml-sem-afiliado` não for `[]`, há itens com link comum: rode `afiliar()` de novo.
- Depois de `afiliar()`, olhe `ColetaML.estado.divergencias` (link já `meli.la` no banco que não bate com o gerado agora) e `ColetaML.estado.naoMeliLa` (link que veio sem ser `meli.la`; sintoma de "Links curtos" desligado). O que aparecer aí é para conferir à mão.
- `zerar()` precisa rodar **nas duas abas**: o progresso da coleta fica na aba `lista.` e o dos inelegíveis na aba `www.`.
- Captcha ou "sem polycard": a coleta para sem gravar o termo. Resolva na aba e rode de novo.
- Contrato com o servidor: só JSON, só as origens `https://lista.mercadolivre.com.br` e `https://www.mercadolivre.com.br`, e nenhum DELETE.

## Primeira coleta de perfumaria

Faça antes um backup (seção "Backup") e a migração (seção "Reorganizar abas"). Resumo do protocolo do plano (`docs/produto/planos/eletronicos-e-coleta-ml.md`):

1. **Amazon numa cópia.** Copie o banco e suba o servidor de teste na 8766 (seção "Testes"). Copie também o progresso real, `cp coleta_amazon_feitos.txt /caminho/feitos-teste.txt`: com um arquivo vazio a coleta começaria pelos termos de eletrônicos, e assim só faltam os 28 de perfumaria (o arquivo real fica intocado). Rode `ACHADINHOS_DB=/caminho/copia.db ACHADINHOS_FEITOS=/caminho/feitos-teste.txt python3 coletar_amazon.py buscas` e interrompa com Ctrl+C depois de 2 ou 3 termos. Confira a aba em `localhost:8766`.
2. **Amazon no banco real.** `python3 coletar_amazon.py buscas`; pare depois dos primeiros termos, confira e rode de novo para continuar.
3. **ML, em etapas.**
   1. Na aba da lista: `await ColetaML.coletar({termos: ['Perfume Natura', 'Body splash'], enviar: false})`. Compare 3 itens de `ColetaML.estado.itens` com a página (título, preço e foto).
   2. Repita com `servidor: 'http://localhost:8766'` (em vez de `enviar:false`).
   3. Na aba do linkbuilder: `await ColetaML.afiliar({servidor: 'http://localhost:8766'})`; abra 2 links `meli.la` e confira o MLB.
   4. Só então use o servidor real (8765): primeiro esses 2 termos, depois `ColetaML.BUSCAS['Perfumes e Perfumaria']`, e termine com `afiliar()`.
4. **Conferência.** A aba "Perfumes e Perfumaria" tem itens da Amazon e do ML e `curl -s localhost:8765/api/ml-sem-afiliado` devolve `[]`. Item ruim (contratipo, réplica, "inspirado em"): exclua pelo site ou volte ao backup.

Gerar links de verdade também os adiciona a "Minhas recomendações" da conta do ML; isso é aceitável.

## Disparo automático

Regras do dono que montam uma **fila de ofertas** nos horários combinados. Nesta entrega o transporte é **manual**: o servidor cria as mensagens e você as copia da fila (mensagem e imagem) para o WhatsApp e clica em "Marcar como enviado" ou "Pular". O envio automático para o grupo fica para uma entrega 2. Plano: `docs/produto/planos/disparo-automatico.md`.

**Primeira vez:** faça um backup (seção "Backup") e reinicie o `servidor.py`. Ele cria as tabelas `numeros`, `regras` e `envios` e grava `PRAGMA user_version = 1`; a migração só acrescenta, não mexe em nada existente. O botão "Disparo automático" fica no topo da página principal.

1. **Número e grupo** (`#numeros`, "Números de WhatsApp"): rótulo, telefone com DDI e DDD, só números (ex.: 55 + DDD + número; opcional no envio manual), grupo de destino, código do grupo (opcional) e limite por dia (1 a 200, somando todas as regras do número). O telefone e o código do grupo ficam só no banco local, vão só no corpo JSON (nunca em URL nem em log) e aparecem mascarados na tela.
2. **Regra** (`#disparo/nova`; editar: `#disparo/regra/<id>`): nome, número, categorias (as abas que existem), loja (Amazon, Mercado Livre ou ambas), ordem, filtros opcionais (palavras no título, desconto mínimo em %), dias e horários, mensagens por horário (1 a 10), máximo por dia, prazo para não repetir (N dias ou nunca), template (os de "Editar templates"; precisa ter `{LINK}`) e foto (item sem imagem sai só com texto). **A regra nasce pausada:** confira a prévia (a lista de mensagens que ela mandaria agora, sem gravar nada, no fim do formulário) e use "Ativar" quando quiser começar.
3. **Fila** (seção "Para enviar", em `#disparo`): "Copiar mensagem", "Copiar imagem", "Marcar como enviado" e "Pular". O botão "Disparar agora" da regra processa um horário na hora, com as mesmas regras de seleção e limites.
4. **Histórico** (`#historico`): envios por período e status (na fila, enviado, pulado, incerto, falhou, expirado).

**Ordens** (nome na tela, entre parênteses). Em empate vale a ordem da coleta, salvo em `recentes` e `aleatoria`:

| Ordem | O que faz |
|---|---|
| `relevancia` ("Mais relevantes") | mais vendas ("Mais de 1 mil compras" vale 1000), depois mais avaliações, depois a nota |
| `desconto` ("Maiores descontos") | maior desconto em % primeiro |
| `menor_preco` ("Mais baratos") / `maior_preco` ("Mais caros") | preço crescente / decrescente; item sem preço vai para o fim |
| `cupom` ("Com cupom primeiro") | itens com cupom primeiro, depois o maior desconto |
| `recentes` ("Mais recentes") | coletados há menos tempo primeiro (empate pelo `id`, o maior primeiro) |
| `aleatoria` ("Aleatória") | sorteio a cada horário (sem desempate) |

**O que o dono precisa saber:**

- Só sai item com título, preço e **link de afiliado**. Item do ML sem `meli.la` nunca sai, e a mensagem que tiver qualquer outro link não é criada (vale também para links escritos à mão no template).
- "Não repetir" conta **por número**, juntando todas as regras dele, em **dias de calendário**: com 7 dias, o item enviado na segunda volta a valer na segunda seguinte; com "nunca", não se repete jamais. Item pulado, que falhou ou expirou não bloqueia.
- O que ficou "na fila" de um dia anterior vira **expirado** (sem apagar o histórico). Itens "incertos" (o servidor caiu no meio de um envio) pedem que você confira no grupo antes de marcar.
- Horário perdido por **mais de 10 minutos** (computador desligado) é pulado, sem rajada. Reiniciar o servidor **não repete** horário já processado.
- Valem ao mesmo tempo "mensagens por horário", "máximo por dia" (por regra) e o "limite por dia" do número. O horário é o do computador.
- Os preços são os da última coleta; o disparo não recoleta nada. O template com aviso de preço ajuda.
- Quando um horário não gera nenhuma mensagem, a regra mostra um aviso com o motivo: nenhum item casa com os filtros (acontece quando uma aba é renomeada), todos os elegíveis já foram enviados no prazo de repetição, ou o template tem um link que não é o do item. O aviso some no próximo horário que mandar.
- Título com algo parecido com um endereço de site (ex.: `i.Phone`, `55UN85CBPSA.BWZ`) é recusado por segurança e esse item nunca sai; são poucos (14 no banco de hoje) e ficam só no log do servidor.

Variáveis de ambiente (todas opcionais):

- `ACHADINHOS_DISPARO`: `0` desliga o agendador (a tela e a fila continuam funcionando; só nada novo é gerado sozinho). Desativar as regras também serve.
- `ACHADINHOS_TICK_SEG`: segundos entre as checagens do agendador (padrão `30`).
- `ACHADINHOS_TRANSPORTE`: `manual` (padrão) ou `falso`. O `falso` é só para teste e exige `ACHADINHOS_TRANSPORTE_ARQUIVO`.
- `ACHADINHOS_TRANSPORTE_ARQUIVO`: arquivo JSONL onde o transporte falso grava cada envio. Nunca aponte para um arquivo que importa.

**Reverter:** `ACHADINHOS_DISPARO=0` para o agendador sem mexer em nada. As tabelas novas ficam ociosas e o código antigo as ignora, então voltar a versão do código é seguro; para devolver também os dados, use um backup (seção "Backup"). O `migrar_categorias.py --restaurar` devolve o banco **inteiro**: números, regras e o histórico de envios criados depois do backup somem, e o "não repetir" recomeça do zero. O estado de antes fica em `backups/`, no backup que o `--restaurar` faz antes de sobrescrever. Para desfazer só a Lista WhatsApp, use `classificar_lista.py --desfazer`.
