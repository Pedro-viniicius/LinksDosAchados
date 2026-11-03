---
name: decisao-disparo-automatico
description: Plano do disparo automático (2026-11-03), com transporte atrás de interface e manual primeiro, disparo.py sem importar servidor, user_version, fatos da pesquisa sobre WhatsApp e mapa da Lista WhatsApp
metadata:
  type: project
---
Plano em `docs/produto/planos/disparo-automatico.md` (2026-11-03), aguardando a aprovação do dono e a resposta à P1 (transporte).

**Decisões e por quê:**
- O núcleo fica em `disparo.py`, que **não importa `servidor`**. Ele recebe `conectar` e `eh_afiliado` por parâmetro. Motivo: o `servidor.py` roda como `__main__`, então importá-lo daria import circular ou um módulo duplicado.
- O transporte é a interface `enviar(destino, texto, imagem_url)`. A entrega 1 usa o manual (fila na tela, copiar e colar) e o falso (só por variável de ambiente). O automático vem na entrega 2.
- O agendador é uma thread iniciada no `__main__` depois do bind. O bind funciona como trava de instância única.
- Esquema versionado por `PRAGMA user_version`, a primeira vez no projeto (a versão 1 cria `numeros`, `regras` e `envios`).
- A tabela `config` estava **vazia** no banco real. Os templates em uso são os `DEFAULT_TEMPLATES` do JS, e o servidor não os conhece. A tela grava os padrões quando `config/templates` está nulo.

**Fatos da pesquisa (2026-11):**
- A Meta tem a Groups API na Cloud API. Ela exige Official Business Account, grupo criado pela API (cerca de 8 participantes, segundo fonte terceira) e cobra por mensagem. É inviável para afiliado sozinho.
- O Baileys viola os termos. O fork malicioso `lotusbail` ficou no npm por 6 meses roubando sessões (dez/2025).
- A Lista WhatsApp tem 74 itens, todos eletrônicos ou informática, e 55 deles sem foto. Eles vão para "Black Friday | Eletrônicos" com `busca` por subtema.

**Why:** essas escolhas e esses fatos não aparecem no código.
**How to apply:** se o dono escolher o transporte na P1, escreva só a entrega 2 (uma classe `Transporte` e um sidecar). Não reabra o núcleo. Veja [[decisao-eletronicos-coleta-ml]] e [[decisao-blindar-servidor]].
