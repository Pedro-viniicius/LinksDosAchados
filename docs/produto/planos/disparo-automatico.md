# Plano técnico: Disparo automático (regras, fila, histórico) e reclassificação da "Lista WhatsApp"
- Brief: não há. O pedido do dono de 2026-11-03, repassado pelo lead, faz esse papel. A referência visual é a tela "Nova regra" do Analytics Lead.
- Spec de tela: `docs/produto/specs/disparo-automatico.md` (designer, em paralelo). Os nomes de campo e os enums estão em "Esquema e contratos".
- Data: 2026-11-03

## Objetivo e critérios de aceite
O app gera mensagens de oferta a partir dos itens do banco, seguindo regras do dono, e as entrega a um grupo "hospedeiro" do WhatsApp. O jeito de enviar (transporte) fica atrás de uma interface trocável. **Esta entrega usa o transporte "manual":** a mensagem entra numa fila na tela, pronta para copiar. O transporte automático entra numa entrega 2, depois que o dono responder à P1.

- CA1: o dono cadastra o número que dispara e o grupo hospedeiro (apelido, telefone, nome do grupo, id do grupo opcional, limite diário). Telefone e id do grupo nunca aparecem em URL, log, `motivo` nem git.
- CA2: o dono cria, edita, ativa, desativa e exclui regras. Cada regra tem nome, número, categorias (as abas que existem hoje e as que forem criadas), lojas, palavras, desconto mínimo, ordem, template, com foto, dias, horários, quantidade por disparo, máximo por dia e prazo para repetir.
- CA3: há sete ordens com definição exata: `relevancia`, `desconto`, `menor_preco`, `maior_preco`, `cupom`, `recentes` e `aleatoria`.
- CA4: só entra item com `tem_dados=1`, título, preço e `url` aprovada por `eh_link_afiliado`. Item do ML sem `meli.la` nunca sai. Se a mensagem montada tiver qualquer URL que não seja de afiliado, ela não é criada.
- CA5: item já `enviado`, `pendente`, `enviando` ou `incerto` para o mesmo número nos últimos `repetir_apos_dias` dias não entra. Com `NULL`, o item nunca se repete. `pulado`, `erro` e `expirado` não bloqueiam.
- CA6: a regra só dispara nos `dias` e `horarios` dela, com até `por_disparo` itens por horário, até `max_por_dia` por regra e até `limite_diario` por número. Horário perdido há mais de 10 min (servidor desligado) é pulado, sem rajada.
- CA7: reiniciar o servidor não reprocessa horário já processado. Envio que estava em `enviando` vira `incerto` e não é reenviado.
- CA8: a mensagem é a mesma do card. `montar_mensagem` (Python) e `buildMsg` (JS) dão o mesmo texto nos mesmos casos. A foto vai junto quando `com_foto=1` e o item tem `imagem`.
- CA9: o transporte é trocável pela interface `enviar(destino, texto, imagem_url)`. Esta entrega traz `manual` (fila com copiar mensagem, copiar imagem, marcar como enviado e pular) e `falso` (só para teste). Trocar de transporte não mexe em regra, seleção nem histórico.
- CA10: há histórico de envios por período e status, e uma prévia dos próximos itens de uma regra sem gravar nada.
- CA11: "Disparar agora" processa a regra na hora e respeita CA4 a CA6.
- CA12: os 74 itens da "Lista WhatsApp" mudam de `cat` e `busca` conforme o mapa da etapa 6. Há backup verificado antes, a execução é idempotente e `migrar_categorias.py --restaurar` reverte.
- CA13: as suítes atuais continuam passando. As rotas novas só aceitam a origem local, nunca as do ML.

## Contexto atual
- O servidor é stdlib, com `ThreadingHTTPServer` iniciado em `servidor.py:480-483` e SQLite em WAL com `timeout=30` (`servidor.py:33-37`). O esquema fica em `criar_banco` (`servidor.py:40-59`), com `CREATE TABLE IF NOT EXISTS`, e `PRAGMA user_version` não é usado em lugar nenhum (`rg` sem resultado).
- A regra de afiliado está em `eh_link_afiliado` (`servidor.py:72-87`). `/api/ml-sem-afiliado` fica em `servidor.py:373-377`. Hoje o banco tem 0 item do ML sem `meli.la` e 0 item da Amazon sem a tag (consulta `mode=ro`).
- `bloquear()` (`servidor.py:284-311`) aceita só a origem local, e as do ML apenas em `ROTAS_ML` (`servidor.py:26`). O log de acesso grava a linha da requisição de `/api/` (`servidor.py:259-262`). Por isso dado pessoal não pode ir em caminho nem em query.
- A tabela `config` é chave → JSON (`servidor.py:383-387` e `455-468`) e **está vazia** no banco real. Os templates usados hoje são os `DEFAULT_TEMPLATES` embutidos no JS (`index.html:195`), e o servidor não os conhece.
- `buildMsg` está em `index.html:224-241`. Ela lê `templates[current]` (`let`, em `index.html:217`), descarta a linha cujo placeholder ficou vazio, junta 3 ou mais `\n` e faz `trim`. As ordens que a tela já tem são desconto e preço (`index.html:380-386`). `copiarImagem(it, card, btn)` está em `index.html:312`.
- Dados (consulta `mode=ro`): 5.329 itens. 6 têm cupom, 4.056 têm desconto e 2.829 têm `vendas`. 55 itens da Amazon estão sem `imagem`, quase todos da Lista WhatsApp (55 dos 74). O banco ainda tem "Black Friday" e "Casa Nova", porque a migração do plano `eletronicos-e-coleta-ml` não rodou no banco real.
- `migrar_categorias.py` já tem as peças que esta feature reaproveita: `confirmar_banco_real` (`:150`), `fazer_backup` (`:189`), `restaurar` (`:314`) e `seguro` (`:47`). O backup vai para `backups/*.db`, que o `*.db` do `.gitignore` já cobre.
- Os testes do front usam `W.eval('…')` para ler `let` globais (`testes/abas.test.html:121`). O runner é `node testes/rodar.mjs <nome>`, com `PORTA`.
- **Ocupados agora:** `servidor.py`, `index.html`, `testes/test_servidor.py`, `coletar_ml.js` e `testes/coletar_ml*.mjs`. As etapas 4 e 5 só começam quando o dev atual liberar esses arquivos.

## Abordagens consideradas

### Transporte (como a mensagem chega ao grupo). Escolha do dono: P1
| Opção | Prós | Contras | Risco ao número | Custo |
|---|---|---|---|---|
| A. Manual (fila na tela, copiar e colar) | Zero dependência, zero risco, reaproveita "Copiar imagem" | O dono precisa colar; não é 100% automático | nenhum | 0 |
| B. Baileys (Node, protocolo do WhatsApp Web), num processo à parte | Envia texto e imagem ao grupo por id, sem navegador, e o Node 22 já está na máquina | Viola os termos do WhatsApp (o próprio README do Baileys desaconselha automação). Traz dependência npm: um fork malicioso, `lotusbail`, ficou 6 meses no npm roubando sessão. A sessão vira credencial a proteger | **alto** (fontes de mercado falam em semanas a meses; números não verificados). Menor com chip dedicado, grupo pequeno e volume baixo | 0 + chip |
| C. Automação do WhatsApp Web no Chrome do dono (script na aba) | Sem dependência; parece uso humano | Frágil a mudanças no DOM. Exige a aba aberta e CORS para `web.whatsapp.com` no servidor. Imagem por evento de colar sintético | médio | 0 |
| D. Serviços de terceiros (Z-API, Evolution API, UltraMsg) | Prontos, com API HTTP simples | Também não são oficiais (Evolution usa o Baileys por baixo). O link e o id do grupo passam por terceiro. A Evolution pede Docker | alto | Z-API cerca de R$ 99/mês (não verificado) |
| E. Cloud API oficial (Groups API da Meta) | Oficial, sem risco de banimento | Exige Official Business Account (selo), número fora do app, grupo **criado pela API** (o hospedeiro atual não serve) e cerca de 8 participantes (fonte terceira). Cobra por mensagem (marketing no BR, cerca de R$ 0,32, fontes divergem) | nenhum | por mensagem + verificação |

**Recomendação.** Entregar agora o núcleo com A, o que já resolve "quando, quanto, o quê, sem repetir". Para a entrega 2, se o dono quiser 100% automático, recomendo B num **chip dedicado** (nunca o número pessoal), com volume baixo e `intervalo_seg` de pelo menos 60. O espelhamento que o dono já usa no Analytics Lead é da mesma classe não oficial. E fica inviável para um afiliado sozinho. C é a alternativa sem dependência, se o dono aceitar a fragilidade.

### Onde roda o agendador
| Abordagem | Prós | Contras |
|---|---|---|
| **Thread no `servidor.py`** (escolhida) | Roda sempre que o app está aberto. O bind da porta impede duas instâncias | Precisa iniciar só no `__main__`, porque `coletar_amazon.py` e `migrar_categorias.py` importam o `servidor` |
| Processo `disparar.py` à parte | Isolado | O dono teria dois processos para lembrar e não há trava de instância única |

### Onde a mensagem é montada
Ela é montada no servidor (`montar_mensagem` em Python), porque o agendador roda sem navegador. O risco de divergir do `buildMsg` fica coberto por um teste de paridade com casos compartilhados (CA8). Mover o template para o servidor e apagar o `buildMsg` seria excesso nesta entrega.

## Decisão
- Módulo novo **`disparo.py`**, só stdlib. Ele não importa `servidor`, para evitar import circular com `__main__`: recebe `conectar` e `eh_afiliado` por parâmetro. Nele ficam o esquema, as validações, a seleção, `montar_mensagem`, `processar_slot`, os transportes e o `Agendador`. No `servidor.py` entram só o despacho das rotas `/api/disparo/*`, a chamada de `disparo.migrar` em `criar_banco` e o início do `Agendador` no `__main__`, depois do bind.
- Transportes desta entrega: `TransporteManual`, que deixa o envio `pendente` para a fila da tela, e `TransporteFalso(arquivo_jsonl, falhar=False)`, ligado só por `ACHADINHOS_TRANSPORTE=falso` com `ACHADINHOS_TRANSPORTE_ARQUIVO`. Não há rota para trocar o transporte.
- Os templates continuam em `config.templates`. Quando a tela de Disparo abre com `config/templates` nulo, ela grava os padrões do JS. A regra guarda o **nome** do template. Se o template for apagado depois, o agendador pula a regra e grava `aviso`.
- Telefone e id do grupo ficam na tabela `numeros`, dentro do `achadinhos.db`, que já está fora do git. Trafegam só no corpo JSON.

## Esquema e contratos
Migração versionada e aditiva em `disparo.migrar(con)`: se `PRAGMA user_version < 1`, roda o script abaixo e grava `user_version=1`. Não há migração destrutiva.
```sql
CREATE TABLE IF NOT EXISTS numeros (id INTEGER PRIMARY KEY AUTOINCREMENT,
  nome TEXT NOT NULL, telefone TEXT NOT NULL DEFAULT '', grupo_nome TEXT NOT NULL,
  grupo_id TEXT NOT NULL DEFAULT '', limite_diario INTEGER NOT NULL DEFAULT 40,
  ativo INTEGER NOT NULL DEFAULT 1, criado_em TEXT, atualizado_em TEXT);
CREATE TABLE IF NOT EXISTS regras (id INTEGER PRIMARY KEY AUTOINCREMENT,
  nome TEXT NOT NULL, numero_id INTEGER NOT NULL, ativa INTEGER NOT NULL DEFAULT 1,
  cats TEXT NOT NULL, lojas TEXT NOT NULL DEFAULT '["amazon","ml"]', palavras TEXT NOT NULL DEFAULT '[]',
  desconto_min INTEGER NOT NULL DEFAULT 0, ordem TEXT NOT NULL DEFAULT 'relevancia',
  template TEXT NOT NULL, com_foto INTEGER NOT NULL DEFAULT 1,
  dias TEXT NOT NULL DEFAULT '[0,1,2,3,4,5,6]', horarios TEXT NOT NULL,
  por_disparo INTEGER NOT NULL DEFAULT 1, max_por_dia INTEGER NOT NULL DEFAULT 10,
  repetir_apos_dias INTEGER DEFAULT 7, intervalo_seg INTEGER NOT NULL DEFAULT 60,
  aviso TEXT NOT NULL DEFAULT '', criado_em TEXT, atualizado_em TEXT);
CREATE TABLE IF NOT EXISTS envios (id INTEGER PRIMARY KEY AUTOINCREMENT,
  regra_id INTEGER NOT NULL, numero_id INTEGER NOT NULL, item_pk INTEGER NOT NULL,
  slot TEXT NOT NULL, status TEXT NOT NULL, mensagem TEXT NOT NULL, imagem TEXT NOT NULL DEFAULT '',
  titulo TEXT NOT NULL DEFAULT '', motivo TEXT NOT NULL DEFAULT '', transporte TEXT NOT NULL,
  criado_em TEXT NOT NULL, enviado_em TEXT, UNIQUE(regra_id, slot, item_pk));
CREATE INDEX IF NOT EXISTS ix_envios_rep ON envios(numero_id, item_pk, criado_em);
```
**Validação** (400, mensagem em pt-BR):
- `telefone` só com dígitos, `^\d{10,15}$`, ou vazio. `grupo_id` vazio ou `^\d{5,25}(-\d{5,25})?@g\.us$`.
- `nome` e `grupo_nome` com 1 a 80 caracteres. `limite_diario` de 1 a 200.
- `cats` com 1 a 50 textos. `lojas` dentro de `{amazon, ml}` e não vazio. `palavras` com até 20 textos de até 40 caracteres.
- `desconto_min` de 0 a 95. `ordem` dentro do enum. `template` existente em `config.templates` e contendo `{LINK}`.
- `dias` dentro de 0..6 (0 é segunda, como no `weekday()`) e não vazio. `horarios` com 1 a 48 valores `HH:MM` únicos.
- `por_disparo` de 1 a 10, `max_por_dia` de 1 a 200, `repetir_apos_dias` `null` ou de 1 a 365, `intervalo_seg` de 30 a 3600.
- `numero_id` existente. Inteiro que chega como bool é recusado.

**Ordens (CA3)** (desempate por `posicao`):
- `relevancia`: `vendas` convertido em número ("Mais de 1 mil compras" vira 1000; "Mais de 1000 produtos vendidos" vira 1000), depois `num_avaliacoes` ("27,6 mil" vira 27600; "(135)" vira 135), depois a nota.
- `desconto`: % decrescente.
- `menor_preco` e `maior_preco`: preço vazio vai para o fim.
- `cupom`: com cupom primeiro, depois desconto.
- `recentes`: `criado_em` decrescente (desempate por `id` decrescente). Não usar `atualizado_em`: a migração e a reclassificação gravam `atualizado_em = agora` em milhares de itens antigos.
- `aleatoria`: `random.Random` injetável.

**Rotas** (todas em `/api/disparo/`, fora de `ROTAS_ML`, sem dado pessoal no caminho):
| Método e caminho | Corpo / resposta |
|---|---|
| `GET numeros` · `POST numeros` · `PUT numeros/<id>` · `DELETE numeros/<id>` | campos de `numeros`. O DELETE dá 409 se alguma regra usa o número |
| `GET regras` · `POST regras` · `PUT regras/<id>` · `DELETE regras/<id>` | campos de `regras`, com listas em JSON nativo. O GET inclui `proximo` (ISO do próximo horário). O DELETE mantém os envios |
| `POST regras/<id>/agora` | `{"criados": n, "envios": [...]}` |
| `POST previa` | corpo = regra (sem gravar) + `n` (até 20) → `[{"item_pk", "titulo", "mensagem", "imagem"}]` |
| `GET fila` | envios `pendente` e `incerto`, do mais antigo para o mais novo |
| `PATCH envios/<id>` | `{"status": "enviado"\|"pulado"}`. Só a partir de `pendente` ou `incerto` (`erro` só vai para `pulado`); fora disso, 409 |
| `GET envios?desde=AAAA-MM-DD&status=` | histórico, com até 500 linhas |
| `GET status` | `{"agendador": "ligado"\|"desligado", "transporte": "manual", "ultimo_tick": iso}` |

**Interface** (`disparo.py`):
- `processar_slot(con, regra, slot, agora, transporte, eh_afiliado) -> list[envio]` é serializada por um `threading.Lock` do módulo e roda em `BEGIN IMMEDIATE`.
- `tick(conectar, agora, transporte, eh_afiliado)` faz duas coisas:
  - processa os slots de hoje com `agora - 10 min <= slot <= agora` que ainda não têm envio;
  - passa a `expirado` os `pendente` de dias anteriores.
- `Agendador(conectar, eh_afiliado, transporte, intervalo=30)` é uma thread daemon. Ao iniciar, troca `enviando` por `incerto`. Depois chama o `tick` em loop e, em caso de erro, loga só `type(e).__name__`.
- O transporte tem `nome`, `automatico: bool` e `enviar(destino: dict, texto: str, imagem_url: str | None)`. `destino` traz `telefone`, `grupo_id` e `grupo_nome`. Se falhar, levanta `ErroEnvio(motivo_curto)`.
- No transporte automático, o envio passa por `enviando`, depois `enviado` ou `erro`. No manual, fica em `pendente`.

**Variáveis de ambiente novas:**
- `ACHADINHOS_DISPARO=0` desliga o agendador.
- `ACHADINHOS_TICK_SEG` define o intervalo do tick (padrão 30).
- `ACHADINHOS_TRANSPORTE=falso` e `ACHADINHOS_TRANSPORTE_ARQUIVO` ligam o transporte falso.

## Etapas
| # | Etapa | Arquivos | Verificação | Responsável | Grupo | Sensível | CAs |
|---|---|---|---|---|---|---|---|
| 1 | `disparo.py`: `migrar` (com `user_version`, idempotente) e `validar_numero`/`validar_regra` com todos os limites acima. CRUD (`listar_*`, `criar_*`, `atualizar_*`, `excluir_*`) com as listas em JSON. Testes em banco temporário: migração em banco antigo e em banco novo, migração repetida sem efeito, cada limite recusado, telefone ausente do texto de toda exceção | `disparo.py`, `testes/test_disparo.py` | `python3 -m py_compile disparo.py && python3 testes/test_disparo.py -v` | dev (opus) | A | sim | CA1, CA2 |
| 6 | Classificar a Lista WhatsApp. Gerar `lista_whatsapp.json` (`{"<id>": {"item_id", "cat", "busca"}}`) a partir do mapa abaixo, com o `item_id` lido do banco em `mode=ro`. Escrever `classificar_lista.py`, que importa de `migrar_categorias` e oferece `--dry-run` e `--sim`. Ele confere `id`↔`item_id` e `cat='Lista WhatsApp'` (aborta se divergir), faz backup verificado e grava numa transação só (`cat`, `busca`, `atualizado_em`). Rodar de novo resulta em 0 mudanças. Testes em banco semeado | `lista_whatsapp.json`, `classificar_lista.py`, `testes/test_classificar_lista.py` | `python3 -m py_compile classificar_lista.py && python3 testes/test_classificar_lista.py -v` | dev (opus) | A | sim | CA12 |
| 2 | `disparo.py`: `montar_mensagem(item, template)` como porte fiel do `buildMsg`. `.replace('-', '', 1)` no desconto; o `trim` usa o mesmo conjunto do JS, que remove `﻿` (o `strip()` do Python não remove) e mantém `​`. Também `elegiveis`, `ordenar`, `previa` e a conferência de toda URL da mensagem com `eh_afiliado`. A paridade usa `testes/mensagens.test.html`, com os casos num `<script type="application/json" id="casos">`: o teste Python lê esse bloco do arquivo, e a página roda `buildMsg` via `W.eval` com `templates` e `current` trocados. Casos: os 4 templates padrão, campo vazio, `​` no título, desconto sem `-` e `NUMERO_VENDAS` caindo no fallback | `disparo.py`, `testes/test_disparo.py`, `testes/mensagens.test.html` | `python3 testes/test_disparo.py -v` e, com servidor de teste: `PORTA=<p> node testes/rodar.mjs mensagens` | dev (opus) | B | sim | CA3, CA4, CA5, CA8, CA10 |
| 3 | `disparo.py`: `processar_slot` (lock + `BEGIN IMMEDIATE` + `UNIQUE`), `tick` com `agora` injetado, `TransporteManual`, `TransporteFalso`, `ErroEnvio` e `Agendador`. Testes com relógio falso cobrindo: dia/horário fora, tolerância de 10 min, `por_disparo`, `max_por_dia`, `limite_diario`, não repetir com N e com `null`, `pulado` sem bloqueio, `enviando` virando `incerto` no início, falha do transporte gravando `erro` sem dado pessoal, duas threads no mesmo slot sem envio duplicado, template apagado gravando `aviso` | `disparo.py`, `testes/test_disparo.py` | `python3 testes/test_disparo.py -v` | dev (opus) | C | sim | CA5, CA6, CA7, CA9, CA11 |
| 4 | `servidor.py`: em `criar_banco`, chamar `disparo.migrar`. Despachar `/api/disparo/*` para `disparo.rota(con, metodo, caminho, query, corpo, eh_link_afiliado)` e reaproveitar `corpo()`/`ErroCliente`. No `__main__`, criar o servidor (bind), iniciar o `Agendador` (salvo `ACHADINHOS_DISPARO=0`) e depois chamar `serve_forever`. O log do agendador traz só contagens. Os testes sobem um subprocesso com o transporte falso e `TICK_SEG=1`: rotas, 403 com Origin do ML, regra com horário no minuto atual gerando envio no JSONL, e reinício sem novo envio. Telefone ausente da saída do servidor | `servidor.py`, `testes/test_disparo_servidor.py` | `python3 -m py_compile servidor.py disparo.py && python3 testes/test_disparo_servidor.py -v && python3 testes/test_servidor.py` | dev (opus) | D | sim | CA1, CA2, CA7, CA9, CA10, CA11, CA13 |
| 5 | `index.html`: tela "Disparo", seguindo a spec do designer (regras, números, fila, histórico). A lista de categorias vem de `cats()`. Ao abrir, grava `config/templates` se estiver nulo. A fila é atualizada a cada 30 s e tem "Copiar mensagem", "Copiar imagem" (reaproveita `copiarImagem` com o item de `items`), "Enviado" e "Pular". Há "Disparar agora" e prévia. Todo texto vindo da API passa por `esc`. Teste com GETs e itens falsos, sem POST no banco real | `index.html`, `testes/disparo.test.html` | `PORTA=<p> node testes/rodar.mjs disparo` e, sem regressão, `node testes/rodar.mjs copiar-imagem` e `abas` | dev | E | não | CA2, CA9, CA10, CA11 |
| 7 | Docs: seção "Disparo" no `README.md` (como cadastrar, a fila manual, variáveis de ambiente e como reverter) | `README.md` | leitura pelo revisor | dev | E | não | CA9 |

Ordem: as etapas 1 e 6 rodam em paralelo (A), depois vêm 2 (B), 3 (C), 4 (D) e, por fim, 5 e 7 juntas (E). A etapa 4 espera o dev atual liberar `servidor.py` e `testes/test_servidor.py`; a 5 espera `index.html` e a spec. A etapa 6 roda no banco real **depois** do `migrar_categorias.py` do plano `eletronicos-e-coleta-ml`. Ao final, o lead atualiza o `CLAUDE.md` com as rotas, os arquivos e as variáveis novas.

### Mapa da Lista WhatsApp (etapa 6). Destino de todos: "Black Friday | Eletrônicos"
Nenhum dos 74 títulos pede aba nova: todos são eletrônicos ou informática. A `busca` (o filtro "buscas" dentro da aba) recebe um termo do `buscas.json` quando ele existe. Os termos marcados com * são subtemas novos que **não** entram no `buscas.json`, para a Amazon não passar a coletá-los.

| busca | ids |
|---|---|
| Console de videogame | 9 |
| Controle acessório videogame | 10, 11, 12, 17, 23, 42 |
| Fone de ouvido Bluetooth | 2, 4 |
| Headset gamer | 16 |
| Teclado e mouse | 13, 15, 37, 38, 39, 40, 41, 44, 48 |
| Monitor | 22, 36 |
| Smart TV | 24 |
| Smart TV 4K | 25, 26, 27 |
| Notebook | 28, 29, 30, 33 |
| Computador gamer | 34 |
| Tablet | 31 |
| Celular smartphone | 18 |
| SSD | 54, 57, 58 |
| HD externo | 53, 62, 63 |
| Roteador Wi-Fi mesh | 52, 65, 66, 67, 68, 129, 130, 131, 133 |
| Carregador portátil power bank | 20 (auxiliar de partida com power bank) |
| Acessórios de informática* | 8, 43, 45, 46, 47, 49, 50, 51, 55, 56, 59, 60, 61, 64, 132 |
| Capas e acessórios* | 5, 6, 7, 14, 19 |
| Câmeras* | 1, 3, 21 |
| Computador e peças* | 32, 35, 134 |

São 74 ids, sem repetição, conferidos contra o banco em `mode=ro`. Com isso a aba "Lista WhatsApp" some, porque as abas saem de `cats()`.

## Pontos para o seguranca
- **Dado pessoal.** Telefone e `grupo_id` não podem aparecer no caminho, na query, no log de acesso (`servidor.py:259-262`), no log do agendador, em `envios.motivo`, em mensagem de exceção nem no git. O DELETE e o PUT usam só o `id`.
- **Entrada.** As rotas novas passam por `bloquear()` e ficam fora de `ROTAS_ML`. Os limites de tipo e tamanho estão em "Validação". Os campos JSON dentro de TEXT são validados antes de gravar. Rejeitar bool como int.
- **Regra de afiliado.** Toda URL da mensagem final passa por `eh_link_afiliado`, inclusive as escritas à mão no template.
- **Concorrência.** A thread e a rota "agora" disputam o mesmo slot (lock + `BEGIN IMMEDIATE` + `UNIQUE`). O WAL é compartilhado com `coletar_amazon.py` e `migrar_categorias.py`. Expirar e marcar `incerto` não pode apagar histórico.
- **Transporte falso** só por variável de ambiente, nunca por rota. Ele grava apenas no arquivo indicado.
- **Migração.** É só aditiva (`user_version` 1). O script da etapa 6 escreve no banco real, com backup e confirmação.
- **Entrega 2 (para registro).** Sessão de transporte automático = credencial completa da conta. Vai para uma pasta no `.gitignore` com permissão 600. A dependência npm fica fixada com lockfile e só o pacote oficial do Baileys (o caso `lotusbail` mostra o risco). O sidecar fica preso a `127.0.0.1` e exige um token.

## Riscos e como reverter
- **Migração do esquema:** é aditiva. Para reverter, basta o `git revert` do código: as tabelas novas ficam ociosas e o código antigo as ignora. Não há DROP.
- **Reclassificação (etapa 6):** `python3 migrar_categorias.py --restaurar backups/<arquivo>.db`, com o servidor parado.
- **Agendador com defeito:** `ACHADINHOS_DISPARO=0` o desliga sem mexer em nada. Desativar as regras também resolve.
- **Mensagem com preço desatualizado:** os dados são da coleta e o disparo não recoleta nada. A mitigação é usar o Template 4, que tem o aviso de preço (ver P4).
- **Divergência entre `buildMsg` e `montar_mensagem`:** o teste de paridade da etapa 2 cobre. Quem mudar um dos dois precisa mudar o caso no `mensagens.test.html`.
- **Excesso de engenharia vigiado:** nada de cron externo, de tabela de templates ou de similaridade de títulos (o "pulada por ser parecida" do concorrente). `intervalo_seg` existe só para a entrega 2.

## Perguntas em aberto e premissas adotadas
- **P1 (dono):** qual transporte automático usar na entrega 2? Opções B (Baileys num chip dedicado, recomendado se quiser 100% automático), C (aba do WhatsApp Web), D (serviço pago) ou ficar só no manual. Premissa desta entrega: só manual.
- **P2 (dono):** o mapa da Lista WhatsApp pode trocar a `busca` "WhatsApp" pelos subtemas? A alternativa é mudar só a `cat` e manter `busca='WhatsApp'`. Premissa: trocar.
- **P3 (dono):** "não repetir" conta por número/grupo, juntando todas as regras. É o que está no plano, porque o grupo vê a repetição seja qual for a regra. Valor padrão: 7 dias.
- **P4 (dono):** antes de enviar, atualizar o preço dos itens da Amazon? Isso usaria `/api/fetch`, com risco de captcha e de mais acesso à Amazon. Premissa: não.
- **Premissas.** Horário local da máquina. Fila manual com Notification API opcional (decisão do designer). 55 itens sem foto saem só com texto. Só 6 itens têm cupom hoje, então a ordem `cupom` cai quase toda no desconto.

## ADR 1: transporte atrás de interface, com manual primeiro
- **Contexto:** enviar para um grupo do WhatsApp por programa só é oficial pela Groups API, que exige selo e grupo criado pela API, e isso é inviável aqui. Os caminhos viáveis violam os termos e arriscam o número.
- **Decisão:** o núcleo (regras, seleção, fila e histórico) não depende do transporte. Entra primeiro o transporte manual, sem risco. O automático fica para a entrega 2, depois da P1, e é implementado como mais uma classe `Transporte`.
- **Consequências:** o valor chega sem risco e sem dependência nova. A troca de transporte não mexe no banco. O custo é `montar_mensagem` em Python, com paridade testada.

## ADR 2: esquema versionado por `PRAGMA user_version`
Primeira migração com versão no projeto. Ela é aditiva e idempotente e fica em `disparo.migrar`. As próximas mudanças de esquema sobem o número.
