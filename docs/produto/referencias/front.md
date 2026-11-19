# Referência: front (`index.html` e testes do front)

Contrato da interface, movido do `CLAUDE.md` em 17/11/2026 (plano `docs/produto/planos/endurecer-entrega2.md`, etapa 5). O `CLAUDE.md` guarda o mapa, as armadilhas que cruzam áreas e as regras de segredo, de LGPD e de afiliado, que valem aqui também. Decisões de UI em `docs/produto/specs/ux-ui-identidade.md`.

## `index.html`

- A interface inteira (estilos, marcação e JS que chama a API).
- O `designer` mexe só em estilo, marcação e textos; chamadas de API e lógica de dados ficam com o `dev`.
- Constantes lidas por regex nos testes Python ficam numa linha só (`LOJA`, `HOSTS_LINK`, `HOST_FOTO_SHOPEE`, `HOSTS_FOTO`, `ABAS_COM_GENERO`, `GENEROS`, `NOME_GENERO`, `OPCOES_PUBLICO`).

### Disparo e público

- Inclui a tela "Disparo automático" (`#telaDisparo`, textos em `TXT_DISPARO`, rotas por hash `#disparo`, `#disparo/nova`, `#disparo/regra/<id>`, `#historico`, `#numeros`; telefone e código do grupo mascarados, inteiros só no campo de edição; Template e "Editar templates" ficam dentro de cada regra, não no cabeçalho do disparo), e o controle "Público" (gênero) nas abas com gênero, com correção à mão em "Mais ações".
- A fila e as prévias do disparo mostram no `<img>` a foto grande gravada em `envios.imagem`, e o "Copiar imagem" da fila não tem a miniatura como reserva (`itemDaFila` usa `e.imagem`).

### Categoria e lista

- A categoria é desmarcável: clicar de novo na pílula marcada (ou escolher "Todas as categorias", a primeira opção do `#selCat`) deixa `activeCat === ''` e a lista traz os produtos de todas as categorias (o "Público" some, a faixa e o quadro de preços falam de "Todas as categorias", o filtro de buscas agrupa por categoria); é também o padrão da primeira visita, sem nada guardado no `localStorage` (a escolha de nenhuma é lembrada; `localStorage` indisponível não quebra); o "Adicionar" sem categoria marcada pede para escolher (não adivinha "Geral").
- A lista tem estados de carregando, erro ("Tentar de novo") e sem resultado ("Limpar filtros") em `#estadoLista` (`carregarOfertas`, `carregarJson`, `htmlEstadoLista`), e o `render()` devolve o foco ao botão equivalente (`guardarFoco`/`devolverFoco`).

### Fotos

- O "Copiar imagem" baixa a versão grande da foto com as mesmas regras do `disparo.foto_grande` (`urlFotoParaCopiar`; tabela de casos igual nos dois lados, conferida por `test_disparo.py`), e cai na URL gravada só se a grande estiver indisponível.
- URL com mais de 2048 caracteres volta como veio nos dois lados (a regex da Amazon é quadrática).

### Idade do preço

- Linha `.idade-preco` e selo "Desatualizado" no cartão ("Atualizar preço" da Amazon não grava se a página vier sem preço ou com outro ASIN), faixa `#faixaPrecos` e quadro `#quadroPrecos` "Como atualizar os preços" (comandos só para abas de `ORDEM_ABAS`; o site nunca pede credencial), filtro `#fPreco`, ordem "Preço mais antigo primeiro", atalho `#precos`, prazo `config/preco_validade_horas` no quadro e no cabeçalho do disparo.
- Textos em `TXT_PRECOS`, testes em `testes/precos.test.html` e `precos-qa.test.html`.

## Testes do front

- Front: com o servidor no ar (`curl -s -o /dev/null -w "%{http_code}" localhost:8765/api/items` dá 200), `node testes/rodar.mjs copiar-imagem` deve imprimir `RESULTADO: OK` (exit 0).
- Requer Node 22+ (`WebSocket` nativo) e Chrome em `/usr/bin/google-chrome`; o runner abre o Chrome headless via CDP em tempo real (não use `--virtual-time-budget --dump-dom`, que sai antes do fim).
- Cada página fica em `testes/<nome>.test.html`, só faz GET na API real, usa itens falsos montados com `renderCard` e lê duas fotos reais dos CDNs (sem internet, esses 2 testes falham).
- Funções do front que precisam de teste ficam declaradas com `function`, para o iframe alcançar.
- Páginas: `copiar-imagem`, `abrir-e-adicionar`, `mensagens` (contra o 8765), `precos`, `precos-qa`, `genero`, `genero-qa`, `abas`, `abas-qa` e `desmarcar-aba` (estas três sobre uma cópia já migrada, em servidor próprio: `PORTA=8766 node testes/rodar.mjs abas`; `desmarcar-aba` só faz GET na API e usa itens falsos só na memória, veja o comentário no topo da página), `disparo` e `disparo-qa` (só sobre servidor próprio com `ACHADINHOS_DISPARO=0`) e `disparo-integracao` (grava de verdade: só sobre banco temporário novo, migrado e sem número nem regra; recusa a 8765).
- `testes/disparo.test.html` está perto do limite de navegações por hash do Chrome no runner: evite acrescentar navegações.
- Para rodar o front contra código novo sem tocar no servidor real (o `verificar.py --front` já faz isto): copie o banco com `sqlite3 backup` (não `cp`, o banco está em WAL), suba `ACHADINHOS_DB=<cópia> ACHADINHOS_PORTA=8766 ACHADINHOS_API_TOKEN_ARQUIVO=/nao/existe python3 servidor.py` (a variável mantém a API v1 desligada mesmo com `api_token.txt` real no projeto) e rode `PORTA=8766 node testes/rodar.mjs copiar-imagem`.

## Histórico

- 08/11/2026: decisão do lead de não ter a miniatura como reserva no "Copiar imagem" da fila, com 100% das fotos grandes existentes na medição.
