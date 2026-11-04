---
name: decisao-genero-categorias
description: Plano genero-nas-categorias (2026-11-03), com gênero derivado na leitura em genero.py, generos_manuais em user_version 2, só a Perfumaria, e as medições do banco por aba
metadata:
  type: project
---
O plano está em `docs/produto/planos/genero-nas-categorias.md` (2026-11-03). Ele aguarda as respostas do dono às perguntas P1 a P5. A spec paralela é `docs/produto/specs/genero-e-ux.md`, com a Parte A (gênero) e a Parte B (M1 a M8).

**Decisões e por quê:**
- **O gênero é derivado na leitura, num `genero.py` puro.** Só a correção manual fica gravada, na tabela `generos_manuais` (`user_version` 2, dentro de `disparo.migrar`). Motivo: são 6 caminhos de escrita, e um `ALTER` em `items` quebraria testes que comparam linhas inteiras.
- **Só "Perfumes e Perfumaria" separa por gênero** (`ABAS_COM_GENERO`). Em 2026-11-04, o dono pediu também "Moda e Viagem" e "Beleza e Cuidados". As linhas de perfume passam a valer só na perfumaria (veja [[decisao-abas-nichadas]]). A medição em modo ro mostrou:
  - Eletrônicos tem só ~25 smartwatches, quase todos "M e F";
  - em Casa, os 7 casos são falsos positivos ("Donna" é louça, "Lady" é sofá);
  - Eletrodomésticos tem 0.
- **O termo de busca sozinho não serve.** Termos de marca são mistos: Natura Essencial tem 28 M e 23 F, e 212 VIP tem 19 M e 17 F. A ordem é título, depois linha conhecida no título (million, invictus, sauvage, malbec, barba...), depois busca.
- **Os números na Perfumaria são F 696, M 966, U 178 e sem 1.211.** Uma passada completa leva cerca de 66 ms.
- **O disparo filtra `generos` só nos itens de abas com gênero.** A API v1 tem filtro exato.
- **A correção usa a rota `PUT /api/items/<id>/genero`.** Ela fica fora de `ROTAS_ML`, então recebe 403 das origens do ML sem código novo.

**Why:** as medições e as armadilhas não aparecem no código.

**How to apply:** se o dono pedir outra aba, meça de novo em modo ro antes. Ruído conhecido na aba: vinho Malbec e "Bota Invictus". Veja [[decisao-disparo-automatico]] e [[decisao-api-achadinho-turbo]].
