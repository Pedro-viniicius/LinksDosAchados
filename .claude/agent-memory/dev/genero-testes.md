---
name: genero-testes
description: Armadilhas do genero.py, do test_genero.py e da rota PUT de gênero no servidor (regex do plano, guarda de ruído, medição, mutantes, scratchpad compartilhado)
metadata:
  type: project
---

Vistas na etapa 1 do plano genero-nas-categorias (2026-11-03):

- O regex M do plano tinha `homens?`, que casa "homem"? Não: casa "homen"/"homens". Singular "homem" ("Homem Essence") ficava sem gênero; o código usa `homem|homens`. Efeito na base: M 966 -> 972, sem 1.211 -> 1.205 (junto com a guarda abaixo).
- Guarda de ruído na linha de produto: título com `vinho|tinto|bota|botina|coturno|sapato|tenis|sandalia` não usa a linha (Malbec vinho x3 e "Bota Invictus" viram `sem`). Só 5 itens da aba batem nela; só a palavra de gênero (passo 2) continua valendo.
- Medida em `mode=ro` (8.381 itens, aba com 3.051): F 696, M 972, U 178, sem 1.205; origem título 1.593, busca 253, sem 1.205. Tempo da classificação completa: ~25 ms.
- O teste da base real compara proporção (±5 pontos), não contagem, porque a base cresce; pula se não há `achadinhos.db` ou há menos de 1.000 itens na aba.
- `test_migracao_real_cria_a_tabela` usa `disparo.migrar` e pula se `VERSAO_ESQUEMA < 2`.
- Mutantes numa cópia (genero.py + testes/ + buscas.json no scratchpad, `python3 -I`): os 15 testados morrem; nenhum equivalente conhecido.
- `Fêminino` (com acento errado) normaliza para "feminino" e casa: não use como exemplo de "não palavra".

**How to apply:** ao ajustar o dicionário do `genero.py` ou ao ligar o módulo no servidor, disparo e API. Relacionado: [[disparo-testes]], [[api-ofertas-testes]].

Vistas na etapa 3 (servidor, 2026-11-03):

- **Scratchpad compartilhado com o `dev` em paralelo:** o outro `dev` usava `scratchpad/mut` e `scratchpad/mutar.py`, os mesmos nomes que eu escolhi. Ele sobrescreveu meu script, meu `sed` mexeu no dele e um mutante meu ficou no `mut/servidor.py` dele (resultado falso "VIVO"). Use sempre subpasta com o nome da etapa (`scratchpad/dev-e3-genero/`) e nunca rode `sed -i` em arquivo do scratchpad sem `grep` antes.
- Rota nova no `servidor.py`: regex com `\A` no começo (`r'\A/api/items/...'`) não entra na lista de literais do `test_ca6_antigo_rotas_do_fonte...`; com `'/api/...'` direto entra e quebra o teste.
- Mutantes equivalentes conhecidos na rota PUT de gênero: tirar o `isinstance(valor, str)` (tupla `in` usa `==`; True/1/lista nunca igualam texto) e trocar `[0-9]` por `\d` (o caminho é cru em latin-1; nenhum dígito Unicode Nd cabe nele).
- `GET /api/items` na cópia de 8.381 itens: ~63 ms antes, ~92 ms com gênero. Para medir o código antigo numa cópia, ponha o `genero.py` ao lado: o `api_ofertas.py` novo importa ele.

Vistas na etapa 3 do plano abas-nichadas-e-coleta (2026-11-04):

- Linhas de produto agora são por aba (`_LINHAS` em `genero.py`): perfume só na perfumaria, `barbear|barba|pos-barba|aparador de barba` só na beleza (com guarda `venus|depil`), moda sem linha. Perfumaria medida em cópia `backup` de `mode=ro` (8.888 itens): F 696, M 972, U 178, sem 1.205, igual antes e depois. Os 65 títulos reais da base que a lista da beleza pega são todos de barba (pós-barba, balm, Barber Shop), sem falso positivo na base atual.
- Falsos positivos conhecidos e documentados: "Spider-Man"/"Iron Man" em camiseta (palavra `man`) sai masculino na moda; `barber` solto (Barber Shop) não está na lista da beleza.
- Mutante equivalente: tirar `|aparador de barba\b` do regex da beleza (a alternativa `barba\b` já cobre).
- Mutantes numa cópia exigem `disparo.py`, `servidor.py` e `api_ofertas.py` ao lado (o `test_genero.py` importa `disparo` na migração); com `env -i` o teste falha por import, não pelo mutante.
- Não há `sqlite3` CLI na máquina: cópia do banco com `sqlite3.connect('file:achadinhos.db?mode=ro', uri=True).backup(outro)` em Python.
- Nunca `pkill`/`kill` por nome `servidor.py`: há servidores do lead (pid 2102217 e outras portas). Mate só o PID de `ss -ltnp | grep <minha porta>`.
