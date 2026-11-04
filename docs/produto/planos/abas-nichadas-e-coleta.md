# Plano técnico: 17 abas por nicho e coleta de 2.000 produtos novos
- Brief: não há arquivo em `docs/produto/briefs/` (nem `docs/produto/decisoes.md`). A fonte é o pedido do lead de 2026-11-04, com as decisões do dono que ele transcreveu: mapa de 17 abas, gênero em mais duas abas e nenhuma regra nem número no disparo.
- Spec paralela: `docs/produto/specs/abas-nichadas.md` (designer; ainda não existia quando este plano foi escrito).
- Data: 2026-11-04

## Objetivo e critérios de aceite
O plano tem cerca de 300 linhas, quase todas da lista de termos. Se o lead preferir duas entregas, o corte natural é este:
- **Entrega 1, reorganização:** etapas 0, 1, 2, 3, 6, 8, 9, 10 e 11.
- **Entrega 2, coleta com piso:** etapas 4, 5, 7 e de 12 a 15.

O objetivo tem duas partes. Primeiro, trocar as 4 abas atuais pelas 17 do dono sem deixar nenhum item órfão. Depois, coletar ≥ 2.000 itens novos das três lojas, com piso de qualidade e só com link de afiliado.

- **CA1:** o `buscas.json` tem as 17 abas, com os nomes exatos e na ordem do mapa do dono.
  - Cada termo atual continua com o mesmo texto e vai para a aba nova que lhe cabe. Assim, o progresso da Amazon e do ML continua valendo.
  - Os 161 termos novos estão incluídos.
  - Todo termo está em NFC, sem `|` e sem repetição, e os slugs do ML não se repetem.
  - A cópia dentro do `coletar_ml.js` é idêntica ao `buscas.json` (o teste confere).
- **CA2:** o `migrar_categorias.py --dry-run` mostra a contagem de destino por aba e por loja e aborta se algum item ficar sem destino.
  - Cobre 100% dos itens de "Black Friday | Eletrônicos", "Eletrodomésticos" e "Casa e Decoração".
  - Isso inclui o alias do ML, os 4 subtemas da Lista WhatsApp e o item sem `busca` (id 8524).
- **CA3:** no banco real, a migração só grava com backup verificado e o "sim" do dono.
  - Depois dela, nenhum item fica fora das 17 abas, o total de itens é igual ao de antes e a "Perfumes e Perfumaria" mantém as mesmas contagens e os mesmos ids.
  - O `--restaurar` devolve o estado anterior.
- **CA4:** preço antigo implausível (5× o preço ou mais) não é gravado por nenhuma loja. O item fica sem preço antigo e sem desconto.
  - Os itens que já estão no banco são limpos na migração, e o dry-run diz quantos são.
  - A url nunca muda.
- **CA5:** "Moda e Viagem" e "Beleza e Cuidados" passam a ter público (gênero), no `genero.py` e no `index.html` (o `test_front_constantes.py` confere).
  - As linhas de produto de perfume valem só na perfumaria. A beleza tem a sua própria lista de linhas (barbear e barba).
  - A contagem F/M/U/sem da perfumaria fica igual antes e depois (medida numa cópia).
- **CA6:** o front mostra as 17 abas na ordem do mapa, inclusive em "Mover para".
  - O layout segue a spec e cabe no celular.
  - `abas.test.html` e `genero.test.html` estão atualizados e passam.
- **CA7:** a coleta da Amazon grava só itens que passam no piso (P1).
  - Recusa título de usado, recondicionado, seminovo ou renovado.
  - Lê o preço antigo só do preço riscado.
  - Cada regra tem teste.
- **CA8:** a coleta do ML aplica o mesmo piso e a mesma recusa de usado.
  - Ao fim, `/api/ml-sem-afiliado` dá `[]`.
  - Os inelegíveis do linkbuilder vão para o relatório.
- **CA9:** o `coletar_shopee.py importar ARQUIVO` grava itens capturados no painel de afiliados sem credencial.
  - Aplica o piso, confere o dono do link (`utm_source=an_18328801339`) antes de gravar e registra o progresso.
  - Tem teste.
- **CA10:** entram ≥ 2.000 itens novos (`criado_em` a partir do início da coleta).
  - Por loja: Amazon ≥ 900, ML ≥ 400 e Shopee ≥ 400.
  - Por aba: cada uma das 7 abas que nascem vazias (10, 12 a 17) ganha ≥ 150 itens, e cada uma das abas 1 a 9 ganha ≥ 50.
- **CA11:** 100% dos itens novos têm link de afiliado da própria loja.
  - Amazon com `tag=desejodemen01-20`, ML com `meli.la` e Shopee com `s.shopee.com.br/<código>`.
  - Uma consulta SQL de conferência dá 0 exceções.
- **CA12:** o relatório final traz a tabela aba × loja de itens novos, os totais e a lista do que ficou de fora e por quê.
  - Os motivos possíveis: abaixo do piso, usado, inelegível no ML, já existia, sem resultado, captcha ou bloqueio.
- **CA13:** README, contrato `docs/produto/referencias/api-ofertas.md` e CLAUDE.md citam as abas novas e as 3 abas com público.
- **CA14:** a suíte inteira (comandos do CLAUDE.md) fica verde.

## Contexto atual
- **Banco em 2026-11-04, lido em modo ro:** 8.888 itens, e não 8.381. A coleta da lista de presentes acrescentou 507 itens às 01:26: 364 em Casa e 143 em Eletrodomésticos.
  - Por aba: Eletrônicos 3.110 (amazon 1.513, ml 1.597), Casa 1.481, Eletrodomésticos 1.246 e Perfumaria 3.051 (amazon 2.511, shopee 540).
  - `user_version` 2. `numeros`, `regras`, `envios` e `generos_manuais` estão vazias.
  - A Amazon tem 0 itens sem tag e o ML tem 0 itens sem `meli.la`.
- **Mudanças sem commit:** `buscas.json`, `coletar_ml.js` e 3 testes acrescentaram 18 termos da lista de presentes (`git diff --stat`). Este plano parte dessa árvore (premissa PR1).
- **`migrar_categorias.py`:** o desenho já foi pensado para a próxima reorganização ("basta trocar esta tupla", `migrar_categorias.py:30-31`).
  - O destino sai de `buscas.json` + `ALIAS` (`:77-80`). Item sem destino aborta (`:249-255`).
  - Tem backup verificado (`:189-219`), "sim" no banco real (`:150-161`) e `--restaurar` (`:314-357`).
  - Hoje faltaria destino para 31 itens:
    - `Acessórios de informática` (15), `Capas e acessórios` (5), `Computador e peças` (3) e `Câmeras` (3) são subtemas do `lista_whatsapp.json` e ficam fora do `buscas.json` de propósito (`testes/test_classificar_lista.py:63,165`);
    - `Caixa inteligente assistente virtual` (21, ML) já está no `ALIAS`;
    - o id 8524 é um item do ML sem `busca`, sem título e sem dados, só com o `meli.la`.
- **`upsert`:** mantém a `cat` de item que já existe (`servidor.py:276,300-306`), então coletar de novo não muda a aba. A chave única é `loja+item_id` (`servidor.py:92`), e é ela que garante "sem duplicar".
- **`coletar_amazon.py`** não tem piso de nota nem de vendas e não descarta usado (`:139-174`).
  - O preço antigo cai num seletor genérico quando falta o riscado (`:66`).
  - No banco, há 5 itens com o antigo 1000× maior e vários com 5× ou 10× exatos (PHEBO, 69,90 contra 349,50). Isso combina com o seletor pegando o preço por litro ou por unidade (**hipótese, não verificado**).
  - Há 19 títulos "Seminovo" ou de recondicionados (iPhone, Dell Latitude).
  - O progresso é por termo (`:93-98,120-127`).
- **`coletar_ml.js`:** a coleta não tem piso nem recusa de usado (`polycardParaItem`, `:361-412`; `extrairItens`, `:415-428`).
  - As ordens são só relevância e caros (`:50`). A pausa é de 2,5 a 5 s (`:51`). O `afiliar()` lista os inelegíveis para o dono excluir.
- **`coletar_shopee.py`:** o piso é nota ≥ 4,5 e ≥ 1 venda, decisão P6 do dono (`:50-51,152-153`). `no_para_item` (`:163-199`), `conferir_dono` (`:361-363`) e `gravar` (`:367-375`) podem ser reaproveitados.
  - O `main` sempre exige credenciais (`:434-439`).
  - Em 2026-11-03, os 540 itens entraram pelo painel, só pelos botões. Os dados vieram de captura passiva e passaram por `no_para_item` num script avulso (memória do projeto).
- **`genero.py`:** `ABAS_COM_GENERO = ('Perfumes e Perfumaria',)` (`:16`). As linhas de perfume e a guarda de ruído (`:29-37`) valem para qualquer aba com gênero (`:73-79`).
  - Testes que amarram a constante: `test_genero.py:184`, `test_front_constantes.py:119-135` e `genero.test.html:192`.
- **Front:** `cats()` segue a ordem de aparição dos itens (`index.html:432`), usada na barra (`:709`), em "Mover para" (`:601`) e no disparo (`:1468`).
  - O CSS das abas está em `index.html:77-82,168-169`. O texto `publicoAjuda` cita só a perfumaria (`:916`).
- **API v1:** aceita até 20 `cat` (`api_ofertas.py:26`), então 17 cabem. O contrato cita "Casa e Decoração" num exemplo (`api-ofertas.md:154`).
- **`classificar_lista.py`:** já rodou no banco real (não sobra "Lista WhatsApp"). Ele usa `M.ORIGENS` só para um aviso (`classificar_lista.py:150-158`). Se rodar de novo, aborta por divergência sem gravar (docstring `:17`).
- **Testes que leem o `buscas.json` real ou as abas antigas:**
  - `coletar_ml.test.mjs`, `coletar_ml_qa.test.mjs`, `test_coletar_amazon_qa.py` e `test_ordens_qa.py`, que congelam contagens, hash e ordem;
  - `test_migrar_categorias*.py` (semente com as origens antigas);
  - `test_classificar_lista*.py` (copiam o `buscas.json` real);
  - `abas.test.html` (exige as 4 abas antigas).
  - Os outros testes usam nomes como fixture e não mudam.
- **Fontes de termos:** os mais vendidos da Amazon e do ML deram 503 e 403 no WebFetch. O Promobit Black Friday trouxe:
  - Games: GTA VI, Switch 2, PS5 Digital e controle Xbox.
  - Celulares: Galaxy S26 e Poco X8.
  - Informática: RAM DDR5 e Lenovo LOQ.
  - Áudio: AirPods 4 e PartyBox.
  - Casa e escritório: cadeira de escritório e parafusadeira Bosch.
  - Brinquedos: LEGO Speed Champions.

## Abordagens consideradas
| Abordagem | Prós | Contras | Risco |
|---|---|---|---|
| A. Reaproveitar o `migrar_categorias.py`: trocar `ORIGENS` e acrescentar subtemas e um destino para "sem busca" | Mecanismo já testado (dry-run, backup, "sim", restaurar); muda ~30 linhas | Testes do script precisam de semente nova | Baixo |
| B. Script novo de reorganização a partir de um JSON `de → para` | Mapa explícito, separado do `buscas.json` | Duplica backup, confirmação e restauração; dois mapas para manter | Médio |
| C. UPDATE à mão no sqlite | Rápido | Sem dry-run, backup nem teste; o CLAUDE.md proíbe | Alto |

Para o piso de qualidade, cada coleta filtra no seu próprio formato: Python na Amazon, JS no ML e o que já existe na Shopee. Filtrar no `upsert` recusaria também os itens que o dono acrescenta pelo site.

## Decisão
1. **Migração pela abordagem A.** As mudanças no `migrar_categorias.py`:
   - `ORIGENS = ('Black Friday | Eletrônicos', 'Eletrodomésticos', 'Casa e Decoração')`.
   - Um novo `SUBTEMAS_LISTA`, separado do `ALIAS` para não mexer no espelho do `coletar_ml.js`, aponta cada subtema para o termo de onde ele herda a aba:
     - `Acessórios de informática` → `Teclado e mouse`;
     - `Computador e peças` → `Placa de vídeo`;
     - `Capas e acessórios` → `Carregador rápido`;
     - `Câmeras` → `Microfone`.
   - `DESTINO_SEM_BUSCA = {'Casa e Decoração': 'Casa, Móveis e Ferramentas'}`.
   - A limpeza de preço antigo implausível entra na mesma transação e no mesmo backup.
   - `classificar_lista.py` passa a ter a sua própria tupla `ORIGENS_ANTIGAS = ('Black Friday', 'Casa Nova')` para o aviso. O script fica histórico.
2. **`buscas.json` = mapa único.** Os termos atuais mudam de aba sem mudar o texto (projeção medida em modo ro, total de 8.888, 0 órfãos):
   - **1 Celulares e Informática (1.426):**
     - iPhone 17 e iPhone 16;
     - Samsung Galaxy A17 e A57, e Celular smartphone;
     - Notebook Dell, Acer e ASUS, Notebook, Notebook gamer e Computador gamer;
     - Tablet Samsung, iPad Apple e Tablet;
     - Monitor Samsung, Monitor AOC e Monitor;
     - Impressora Epson EcoTank L3250 e Impressora multifuncional;
     - Mouse Logitech M170, Teclado e mouse e Webcam;
     - SSD, HD externo e Placa de vídeo;
     - Filtro de linha iCLAMPER Energia 5, Filtro de linha e Nobreak.
   - **2 Áudio e Acessórios (512):**
     - Samsung Galaxy Fit3 e Relógio inteligente smartwatch;
     - Fone Bluetooth JBL e Fone de ouvido Bluetooth;
     - Caixa de som Bluetooth JBL e Caixa de som Bluetooth;
     - Carregador portátil power bank e Carregador rápido;
     - Microfone.
   - **3 TV, Alexa e Casa Conectada (767):**
     - Echo Dot Alexa e Smart speaker Alexa;
     - Smart TV 4K Samsung 50, Smart TV 4K LG 55, Smart TV 4K e Smart TV;
     - Fire TV Stick HD e Aparelho de streaming para TV;
     - Kindle, Kindle Paperwhite e Leitor de livros digitais;
     - Soundbar, Soundbar Samsung HW-B400F e Home theater;
     - Roteador Wi-Fi mesh e Câmera de segurança Wi-Fi.
   - **4 Games (405):**
     - PlayStation 5 Slim, Nintendo Switch OLED e Console de videogame;
     - Controle PS5 DualSense e Controle acessório videogame;
     - Mouse gamer Redragon Predator M612 e Headset gamer.
   - **5 Eletroportáteis (584):**
     - Air fryer e Sanduicheira grill;
     - Aspirador de pó e Robô aspirador;
     - Cafeteira, Liquidificador, Mixer e Batedeira planetária;
     - Ferro de passar e Vaporizador de roupas;
     - Torradeira elétrica.
   - **6 Eletrodomésticos e Climatização (632):**
     - Geladeira, Fogão, Cooktop e Micro-ondas;
     - Máquina de lavar, Lava e seca e Lava-louças;
     - Ar-condicionado, Ventilador, Umidificador de ar e Climatizador de ar;
     - Purificador de água.
   - **7 Cozinha (604):**
     - Jogo de panelas, Frigideira antiaderente e Panela de pressão 4,5 litros;
     - Aparelho de jantar, Jogo de talheres e Conjunto de bowls de cerâmica;
     - Jogo de taças de vinho, Taças de sobremesa e Jogo de xícaras de café com pires;
     - Assadeira antiaderente, Forma de bolo antiaderente e Boleira com tampa;
     - Potes herméticos, Organizador de cozinha e Balança de cozinha digital;
     - Aparelho de fondue.
   - **8 Cama, Mesa e Banho (266):**
     - Jogo de cama, Edredom e Travesseiro;
     - Jogo de toalhas;
     - Manta para sofá.
   - **9 Casa, Móveis e Ferramentas (641):**
     - Cama box e Colchão;
     - Sofá, Guarda-roupa, Armário de cozinha e Mesa de jantar com cadeiras;
     - Cortina, Persiana, Tapete e Abajur de chão;
     - Organizador de guarda-roupa;
     - Lavadora de alta pressão;
     - mais o item 8524.
   - **11 Perfumes e Perfumaria (3.051):** os 42 termos ficam iguais, sem termo novo (P4).
   - O ML leva ao destino os seus aliases: "Caixa inteligente assistente virtual" vai para a aba 3.
3. **161 termos novos**, acrescentados no fim de cada aba, a partir da lista do dono e do Promobit. O `dev` copia exatamente:
   - **1 Celulares e Informática:** Galaxy S26 · Smartphone 256 GB · Xiaomi Poco · Notebook 16 GB RAM · Notebook Lenovo IdeaPad · Monitor 27 polegadas · SSD 1 TB · Memória RAM DDR5
   - **2 Áudio e Acessórios:** Fone com cancelamento de ruído · AirPods · Caixa de som JBL PartyBox · Carregador USB-C · Power bank 20000 mAh · Cabo USB-C · Galaxy Watch · Suporte de celular veicular
   - **3 TV, Alexa e Casa Conectada:** Echo Show · Echo Pop · Fire TV Stick 4K · Smart TV 55 polegadas · Smart TV 65 polegadas · Câmera Wi-Fi externa · Tomada inteligente · Lâmpada inteligente · Fechadura digital
   - **4 Games:** Nintendo Switch 2 · PS5 Digital · Jogo de PS5 · Controle Xbox sem fio · Cadeira gamer · Teclado mecânico gamer · Volante gamer
   - **5 Eletroportáteis:** Air fryer 5 litros · Air fryer forno 12 litros · Cafeteira de cápsulas · Cafeteira espresso · Panela elétrica de arroz · Chaleira elétrica · Aspirador vertical · Processador de alimentos
   - **6 Eletrodomésticos e Climatização:** Geladeira frost free · Micro-ondas 30 litros · Ar-condicionado inverter · Ventilador de coluna · Freezer vertical
   - **7 Cozinha:** Jogo de panelas Tramontina · Garrafa térmica · Copo térmico · Jogo de facas · Tábua de corte · Potes de vidro com tampa · Escorredor de louça
   - **8 Cama, Mesa e Banho:** Jogo de lençol casal · Lençol queen algodão · Kit toalhas de banho · Kit travesseiros · Cobertor casal · Protetor de colchão · Toalha de mesa · Tapete de banheiro
   - **9 Casa, Móveis e Ferramentas:** Torneira de cozinha · Cortina blackout · Tapete de sala · Papel de parede · Penteadeira · Cadeira de escritório · Organizador de gaveta · Rack para TV · Parafusadeira · Furadeira de impacto · Jogo de ferramentas · Escada doméstica
   - **10 Beleza e Cuidados:** Elseve Óleo Extraordinário · Lola Morte Súbita · Nivea Milk 400 ml · Cicaplast · Protetor solar facial · Sérum vitamina C · Hidratante facial · Máscara capilar · Kit shampoo e condicionador · Secador de cabelo · Prancha alisadora · Escova secadora · Barbeador elétrico · Aparador de barba · Base de maquiagem · Kit de esmaltes
   - **12 Mercado e Limpeza:** OMO líquido 5 litros · Amaciante Downy 3 litros · Tabletes para lava-louças · Papel higiênico folha dupla · Sabão em pó · Detergente líquido · Desinfetante · Papel toalha · Café em pacote · Café em cápsulas · Azeite extravirgem · Caixa de bombom · Leite em pó
   - **13 Pets:** Ração para cães 15 kg · Ração para gatos 10 kg · Areia para gatos · Sachê para gatos · Petisco para cães · Tapete higiênico para cães · Arranhador para gatos · Cama para cachorro · Peitoral para cachorro · Fonte de água para gatos
   - **14 Bebês e Brinquedos:** Fralda pants · Fralda Pampers · Fralda Huggies · Kit lenços umedecidos · Sabonete infantil refil · Kit mamadeiras · Carrinho de bebê · Cadeirinha para carro · Babá eletrônica · LEGO · Jogos de tabuleiro · Boneca · Carrinho Hot Wheels · Quebra-cabeça
   - **15 Suplementos e Fitness:** Creatina 300 g · Whey protein 900 g · Kit barras de proteína · Bebida proteica · Pré-treino · Multivitamínico · Colágeno · Ômega 3 · Bicicleta ergométrica · Kit halteres · Tapete de yoga · Elástico de treino · Esteira elétrica
   - **16 Moda e Viagem:** Tênis de corrida · Tênis Nike · Tênis Adidas · Kit camisetas · Mala de bordo · Conjunto de malas · Mochila para notebook · Relógio masculino · Relógio feminino · Bolsa feminina · Óculos de sol · Chinelo Havaianas · Pijama feminino
   - **17 Natal e Papelaria:** Pisca-pisca · Árvore de Natal · Enfeites de Natal · Panetone · Livro para colorir · Kit material escolar · Caderno universitário · Marca-texto · Agenda 2027 · Mochila escolar
4. **Piso de qualidade, com os valores da premissa P1:** nota ≥ 4,5 e volume.
   - Amazon: ≥ 100 avaliações ou "Mais de N compras no mês passado".
   - ML: "Mais de 50 produtos vendidos" ou mais.
   - Shopee: ≥ 50 vendas. Isso sobe a P6 antiga, que era 1.
   - Recusa de usado por título: `usad[oa]s?|recondicionad[oa]s?|renovad[oa]s?|seminov[oa]s?|vitrine|open box|refurbished`, sem acento e com `\b`.
5. **Preço antigo em duas camadas.**
   - `servidor.preco_antigo_plausivel(preco, antigo)`: se o antigo for 5× o preço ou mais, zera `preco_antigo` e `desconto`. O `upsert` aplica a função às três lojas.
   - O `parse_busca` passa a ler só o preço riscado `[data-a-strike]` e larga o seletor genérico.
6. **Ordem das abas no front:** uma constante numa linha só, `ORDEM_ABAS`, igual às chaves do `buscas.json`. `cats()` ordena por ela e põe as abas desconhecidas no fim, na ordem de aparição. O resto do layout fica com a spec.
7. **Shopee pelo painel, com o subcomando `importar`.**
   - O plugin só clica nos botões do painel e captura as respostas passivamente. Converte os nós para o formato do `productOfferV2` e grava `{cat, busca, nos:[…]}` num arquivo no scratchpad.
   - O `importar` valida a aba e o termo contra o `buscas.json`, passa cada nó por `no_para_item`, confere o dono no 1º link, grava e marca `vendidos|<termo>`.
   - O progresso é o mesmo da Open API, então os dois caminhos não repetem trabalho.

## Esquema e contratos
- Banco: nenhuma mudança de esquema. `user_version` continua 2, porque `cat` e `busca` são TEXT.
- Funções e constantes novas:
  - `servidor.preco_antigo_plausivel(preco: str, antigo: str) -> bool` e `servidor.LIMITE_PRECO_ANTIGO = 5`;
  - `coletar_amazon.passa_piso(data) -> bool` e `coletar_amazon.eh_usado(titulo) -> bool`;
  - no `coletar_ml.js`, as funções internas `passaPiso(data)` e `ehUsado(titulo)` e o campo `estado.foraDoPiso`;
  - `coletar_shopee.py importar ARQUIVO` (sai com 0, 1 ou 2), com JSON de até `MAX_RESPOSTA` bytes;
  - `genero.ABAS_COM_GENERO` com 3 abas e as linhas de produto por aba.
- API v1: nenhum campo novo. Mudam os nomes de `categoria` e as 3 abas com `generos`. A `versao` continua 1.

## Etapas
| # | Etapa | Arquivos | Verificação | Responsável | Grupo | Sensível | CAs |
|---|---|---|---|---|---|---|---|
| 0 | Linha de base, backup do banco real (API `backup` do sqlite) e cópia de `coleta_amazon_feitos.txt`. O commit das mudanças pendentes dos 18 termos só sai com aprovação do dono | `backups/antes-abas-nichadas-<data>.db` | `PRAGMA integrity_check` = ok e 8.888 itens na cópia; suíte do CLAUDE.md | lead | 0 | sim | CA3 |
| 1 | `buscas.json` com as 17 abas (Decisão 2 e 3); bloco entre marcadores do `coletar_ml.js`; fixture `testes/fixtures/buscas-2026-11-04.json` (cópia exata do `buscas.json` antes da mudança) para os testes que congelam o histórico; contagens e hashes passam a apontar para a fixture, e os testes que valem para o arquivo vivo (NFC, sem `|`, sem repetição, slugs, cópia igual) continuam no real | `buscas.json`, `coletar_ml.js` (só o bloco BUSCAS), `testes/fixtures/buscas-2026-11-04.json`, `testes/coletar_ml.test.mjs`, `testes/coletar_ml_qa.test.mjs`, `testes/test_coletar_amazon_qa.py`, `testes/test_ordens_qa.py` | `node --test testes/coletar_ml.test.mjs testes/coletar_ml_qa.test.mjs && python3 testes/test_coletar_amazon_qa.py && python3 testes/test_ordens_qa.py` | dev | A | não | CA1 |
| 2 | `preco_antigo_plausivel` e aplicação no `upsert` (insert e update); testes de 4,99×, de 5× (exato, o caso PHEBO) e de antigo vazio; a url fica intocada | `servidor.py`, `testes/test_servidor.py` | `python3 testes/test_servidor.py -v && python3 testes/test_servidor_qa.py` | dev | A | não | CA4 |
| 3 | Gênero: `ABAS_COM_GENERO` com as 3 abas no `genero.py` e no `index.html` (só a linha 374); as linhas de perfume e a guarda de ruído só na perfumaria; na beleza, `barbear\|barba\|pos[- ]?barba\|aparador de barba` → masculino; na moda, só palavras de gênero (título > busca); casos de teste das duas abas; medir F/M/U/sem da perfumaria numa cópia antes e depois (iguais) | `genero.py`, `index.html`, `testes/test_genero.py`, `testes/genero.test.html` | `python3 testes/test_genero.py && python3 testes/test_genero_qa.py && python3 testes/test_front_constantes.py`; página `genero` sobre a cópia (8766) | dev | B | não | CA5 |
| 4 | Amazon: `passa_piso` e `eh_usado` antes de `gravar`; o log por termo diz "N achados, X no piso, Y novos"; preço antigo só do riscado (teste com HTML que traga preço por litro sem riscado); ajustar os testes antigos que esperam gravar itens sem nota | `coletar_amazon.py`, `testes/test_coletar_amazon.py`, `testes/test_coletar_amazon_qa.py`, `testes/test_ordens_qa.py` | `python3 testes/test_coletar_amazon.py && python3 testes/test_coletar_amazon_qa.py && python3 testes/test_ordens_qa.py` | dev | B | não | CA7 |
| 5 | ML: `passaPiso` e `ehUsado` em `extrairItens`, contando o que fica de fora em `estado.foraDoPiso`; testes com polycards abaixo do piso, de usado e sem nota | `coletar_ml.js`, `testes/coletar_ml.test.mjs`, `testes/coletar_ml_qa.test.mjs` | `node --test testes/coletar_ml.test.mjs testes/coletar_ml_qa.test.mjs` | dev | B | não | CA8 |
| 6 | Migração: `ORIGENS` nova, `SUBTEMAS_LISTA`, `DESTINO_SEM_BUSCA`, limpeza de preço antigo pelo id (com parâmetros) na mesma transação e conferência de total antes = depois; no dry-run, tabela aba × loja projetada e quantidade de preços a limpar; `classificar_lista.py` com `ORIGENS_ANTIGAS`; semente nova nos testes de migração; os testes do classificar passam a usar a fixture da etapa 1 | `migrar_categorias.py`, `classificar_lista.py`, `testes/test_migrar_categorias.py`, `testes/test_migrar_categorias_qa.py`, `testes/test_classificar_lista.py`, `testes/test_classificar_lista_qa.py` | os 4 testes + `ACHADINHOS_DB=<cópia sqlite3 backup> python3 migrar_categorias.py --dry-run` com 0 órfãos e os números da Decisão 2 | dev (opus) | B | sim | CA2, CA3, CA4 |
| 7 | Shopee: subcomando `importar` sem chamar `credenciais()` (o gate dos outros modos fica igual); valida o formato, o teto de bytes, a aba e o termo; `no_para_item` sobe `VENDAS_MINIMAS` para 50 (P1); `conferir_dono` antes do 1º `gravar`; progresso `vendidos\|<termo>`; não imprime o conteúdo do arquivo | `coletar_shopee.py`, `testes/test_coletar_shopee.py`, `testes/test_shopee_qa.py` | `python3 testes/test_coletar_shopee.py && python3 testes/test_shopee_qa.py` | dev (opus) | B | sim | CA9 |
| 8 | Front, lógica: `ORDEM_ABAS` numa linha; `cats()` ordenado por ela; o JS que a spec pedir para a barra das 17 abas (ex.: rolagem ou seletor no celular); `test_front_constantes` confere que `ORDEM_ABAS` é igual à lista do `buscas.json`; `abas.test.html` com as 17 abas na ordem | `index.html`, `testes/test_front_constantes.py`, `testes/abas.test.html` | `python3 testes/test_front_constantes.py`; numa cópia migrada (8766): `abas`, `copiar-imagem`, `abrir-e-adicionar`, `mensagens`, `disparo` | dev | C | não | CA6 |
| 9 | Docs: README (abas, piso, `importar`, plano B do ML) e contrato da API (exemplo, abas com público, nota de renomeação) | `README.md`, `docs/produto/referencias/api-ofertas.md` | `rg -n "Black Friday \| Eletrônicos\|Casa e Decoração" README.md docs/produto/referencias/api-ofertas.md` mostra só a nota histórica | dev | C | não | CA13 |
| 10 | Front, visual: estilo, marcação e textos da spec `abas-nichadas.md` (barra de 17 abas no celular, texto `publicoAjuda`) | `index.html` | páginas da etapa 8 + revisão do designer em 360 px e 1280 px | designer | D | não | CA6 |
| 11 | Migração no banco real: o dono para o servidor; `--dry-run`; o dono confere a tabela; roda com "sim"; o servidor sobe de novo com o código novo | banco real (via script) | contagem por aba = dry-run; 0 itens fora das 17; perfumaria igual; `curl` em `/api/items` = 200 | lead + dono | E | sim | CA2, CA3, CA4 |
| 12 | Coleta Amazon (detalhe abaixo) | banco real, `coleta_amazon_feitos.txt` | log por termo; SQL de novos por aba | lead | F | não | CA7, CA10, CA11 |
| 13 | Coleta Shopee pelo painel + `importar` | banco real, `coleta_shopee_feitos.txt`, scratchpad | saída do `importar`; SQL | lead | F | sim | CA9, CA10, CA11 |
| 14 | Coleta ML (`coletar` + `afiliar` com 2ª passada) | banco real, localStorage do ML | `/api/ml-sem-afiliado` = `[]`; 0 `url` repetida | lead | F (depois da 13: o mesmo Chrome) | não | CA8, CA10, CA11 |
| 15 | Relatório aba × loja, conferência de afiliado, fora do piso, inelegíveis, usados já existentes e F/M/U/sem das 3 abas com público; CLAUDE.md atualizado | consultas ro; `CLAUDE.md` | SQL do CA11 com 0 exceções | lead | G | não | CA10, CA11, CA12, CA13 |

- **Paralelismo:**
  - No grupo A, as etapas 1 e 2 não compartilham arquivos.
  - No grupo B, as etapas 3 a 7 têm conjuntos disjuntos: a 3 é a única que mexe no `index.html`, a 4 é a única nos testes da Amazon, a 5 é a única no `coletar_ml.js` e a 6 é a única nos testes de migração e do classificar.
  - O grupo B depende do A: a 6 usa a função da etapa 2 e o `buscas.json` da etapa 1. Entre A e B, os testes de migração e do classificar ficam vermelhos de propósito; vale o fim do grupo B.
  - No grupo C, as etapas 8 e 9 também não compartilham arquivos. A etapa 10 vem depois da 8 porque as duas mexem no `index.html`.
  - No grupo F, a etapa 12 (terminal) roda junto com a 13 e a 14 (Chrome). A 13 e a 14 vão uma depois da outra.
- **Coleta, com a premissa P8 para as metas:**
  - **Amazon (12):** `python3 coletar_amazon.py buscas --cat "<aba>" --ordens <…>` por aba. Uma página leva uns 10 s com a pausa. São cerca de 430 páginas, perto de 1h15, e a estimativa é de ~1.400 itens novos depois do piso.
    - Nas abas 10, 12 a 17: `relevancia,vendidos,avaliados`.
    - Nas abas 1, 3, 4 e 6: `relevancia,vendidos,caros`.
    - Nas abas 2, 5, 7, 8 e 9: `relevancia,vendidos`.
    - Os termos já coletados não se repetem na relevância.
  - **Shopee (13):** no painel `affiliate.shopee.com.br/offer/product_offer`, o fluxo é buscar o termo → "Mais vendidos" → "Selecione todos" → "Obter Link em Massa" (até 100 por lote).
    - Prioridade de termos: abas 10, 13, 14, 16, 17, 7 e 8.
    - Meta de cerca de 500 itens novos, em 6 a 8 lotes e cerca de 1h30. O Chrome bloqueia downloads seguidos, então os lotes levam pausa.
    - A alternativa é o dono rodar `coletar_shopee.py buscas --cat … --ordens vendidos,relevancia` com a Open API no terminal dele.
  - **ML (14):** `ColetaML.coletar({termos: ColetaML.BUSCAS['<aba>']})` nas abas 10, 12 a 17 e nos termos novos das abas 2, 5, 7, 8 e 9. Depois, `ordem:'caros'` nas abas 1, 3 e 6.
    - Em seguida, `afiliar()` com uma 2ª passada até dar 0 correções.
    - Cerca de 40 min de coleta e 1 h de afiliação, com meta de ~500 itens.
    - Se o Chrome continuar bloqueando o `localhost`, vale o plano B (P6).
  - **Captcha, "verificação de conta" ou o código 90309999 da Shopee:** parar, guardar o progresso e avisar o dono. Nunca chamar a API interna do painel por script.

## Pontos para o seguranca
- **Etapa 6:** os UPDATEs só com parâmetros; dry-run em `mode=ro`; backup verificado antes do COMMIT; "sim" no banco real; o `--restaurar` fica como está; a limpeza de preço nunca toca `url`; a mensagem de erro do sqlite nunca é impressa.
- **Etapa 7:**
  - O `importar` não lê o ambiente nem chama `credenciais()`, e os modos `conferir` e `buscas` continuam exigindo credenciais como hoje.
  - O arquivo é entrada externa, porque vem do painel. Conferir o teto de bytes, o tipo de cada campo e `eh_link_shopee`.
  - `conferir_dono` roda antes do primeiro `gravar`. Nada do arquivo vai para log.
- **Etapa 13:** o plugin nunca abre nem age na página do painel que mostra o Secret da Open API. Só botões e captura passiva, nunca chamada por script à `/api/v3/...` (dispara o antirrobô). O arquivo de importação fica no scratchpad e é apagado depois.
- **Etapa 14:** liberar "Acesso à rede local" só para `lista.mercadolivre.com.br` e `www.mercadolivre.com.br`. Conferir a etiqueta `achadosmenicas` no pedido do createLink (o script já confere, `coletar_ml.js:864-869`).
- **Etapa 2:** a mudança no `upsert` é só de normalização de dados. Confirmar que nenhum caminho passa a gravar url diferente.

## Riscos e como reverter
- **Mapeamento errado de algum termo**, visto no dry-run: corrigir o `buscas.json` (etapa 1) e rodar o dry-run de novo antes de gravar.
  - Depois da migração e **antes da coleta**: `python3 migrar_categorias.py --restaurar <backup>` com o servidor parado.
  - **Depois da coleta, não restaure** (perderia os itens novos e o progresso ficaria marcado como feito). Corrija com nova edição do `buscas.json` e nova migração, ou com "Mover para" no site.
- **Código das etapas 1 a 10:** `git revert` do commit. Sem mudança de esquema, o banco não precisa voltar.
- **O piso corta demais e uma aba não chega à meta:** o relatório mostra quantos itens ficaram de fora por termo. O dono decide afrouxar a P1 ou trocar termos. Os termos que caem no piso não são marcados como feitos, então rodam de novo.
- **Gênero errado na moda ou na beleza:** o dono corrige à mão (a correção manual vence). Reverter o `genero.py` volta essas abas para "sem", e as correções ficam guardadas.
- **Captcha ou bloqueio:** parar. O progresso é por termo e por ordem nas três lojas.
- **O servidor de pé roda código antigo** (pid 2102217, desde 2026-11-03): reiniciar na etapa 11, antes de qualquer coleta. O ML grava pelo `upsert` do servidor.
- **API v1 e Turbo:** os nomes das abas mudam e a migração regrava o `atualizado_em`, então os itens reaparecem na ordem `atualizacao`. O contrato já prevê isso (`api-ofertas.md:218`), e o Turbo ainda não tem catálogo.

## Perguntas em aberto e premissas adotadas
- **PR1:** as mudanças sem commit dos 18 termos de presentes entram como base. O lead faz o commit com aprovação do dono antes da etapa 1.
- **P1 (piso), premissa:** nota ≥ 4,5 e, além disso:
  - Amazon com ≥ 100 avaliações ou "compras no mês passado";
  - ML com "Mais de 50 vendidos";
  - Shopee com ≥ 50 vendas. Isso muda a P6 de 2026-11-03, que era 1. O fato novo é o pedido de "volume real".
- **P2:** preço antigo de 5× o preço ou mais (desconto de 80% ou mais) é descartado. No banco atual, isso limpa 33 itens da Amazon e 0 do ML (medido em modo ro). Os ML legítimos chegam a 77%. Os 9 casos de 5× exato, como o PHEBO, parecem preço por litro.
- **P3:** o dono confirma no dry-run os termos ambíguos:
  - Soundbar e Home theater → TV;
  - smartwatch e Galaxy Fit3 → Áudio;
  - Robô aspirador → Eletroportáteis;
  - Cama box e Colchão → Casa, Móveis;
  - Mouse gamer e Headset gamer → Games;
  - Kindle → TV;
  - Lavadora de alta pressão → Casa, Móveis e Ferramentas;
  - Manta para sofá → Cama, Mesa e Banho;
  - Câmeras (instax e GoPro) → Áudio e Acessórios.
- **P4:** a perfumaria fica igual, sem termo novo. "Lily O Boticário" e "Armani Code" ficam como sugestão para outra rodada.
- **P5:** há 19 itens "Seminovo" ou recondicionados já no banco. Eles vão para o relatório, e o dono decide se exclui pelo site. O plano não exclui nada.
- **P6, plano B do ML:** se o "Acesso à rede local" continuar bloqueado, o ML fica para depois. A Amazon e a Shopee cobrem os 2.000, e a meta do ML no CA10 vira risco aceito pelo dono.
  - Uma ponte manual (o plugin lê o estado e o lead faz o `curl` local) é possível, mas não é recomendada: ela também precisaria do mesmo caminho no `afiliar()`.
- **P7:** a Shopee vai pelo painel com o plugin, como o lead pediu. A Open API no terminal do dono é a alternativa equivalente.
- **P8, metas:** as do CA10 (por loja e por aba) são proposta do arquiteto. O dono pode trocar.
- O `classificar_lista.py` e o `lista_whatsapp.json` ficam como histórico: o `--desfazer` só valia antes desta migração. Para voltar, use o backup.

## ADR
**ADR: o piso de qualidade fica em cada coleta e o preço antigo é saneado no `upsert`** (2026-11-04)

- **Contexto:** o dono quer só itens com nota ≥ 4,5 e volume real, sem usado e sem desconto falso. As três coletas são independentes e usam formatos diferentes.
- **Decisão:** o piso e a recusa de usado ficam em cada coleta. Na Amazon ficam em Python, no ML em JS dentro do `coletar_ml.js` e na Shopee no `no_para_item`. Os limites são os mesmos e cada lado tem o seu teste. A plausibilidade do preço antigo fica numa função só do `servidor.py`, chamada pelo `upsert`.
- **Alternativa rejeitada:** filtrar tudo no `upsert`. Recusaria os itens que o dono acrescenta pelo site e os que não têm dados.
- **Consequência:** os mesmos limites aparecem em três lugares. Mudar a P1 exige mexer nos três e nos testes.
- **Ordem das abas:** fica em `ORDEM_ABAS` no `index.html`, amarrada ao `buscas.json` por teste. O servidor não serve o `buscas.json`, e não vale abrir mais uma rota estática só para isso.

## Decisões do dono (2026-11-04)
- Plano aprovado inteiro, incluindo a coleta.
- **PR1:** os 18 termos de presentes e os 507 itens das 01:16–01:26 são do dono; entram como base.
- **P1:** piso da premissa: nota ≥ 4,5, e Amazon ≥ 100 avaliações (ou "compras no mês passado"), ML "+50 vendidos", Shopee ≥ 50 vendas.
- **P2, P3, P4, P5, P6, P8:** valem as premissas do plano (5×; termos ambíguos conferidos no dry-run; perfumaria sem termo novo; seminovos só no relatório; ML como risco aceito se o Chrome bloquear; metas do CA10).
- **Spec:** "Ir para a página" e "Sem público" ficam fora desta entrega. Os rótulos dos 4 grupos da barra (Tecnologia, Casa, Beleza e consumo, Família e estilo) ficam como o designer propôs.
- Backup da etapa 0: `backups/antes-abas-nichadas-20261104-014404.db` (integrity ok, 8.888 itens) e `backups/coleta_amazon_feitos-20261104-014404.txt`.
