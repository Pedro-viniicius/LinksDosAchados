# Passagem de sessão: 09/11/2026 (sessão "trabalho_09_nov")

Escrito às 13:55 de 09/11/2026, porque o dono vai trocar de conta do Claude. Uma sessão nova deve ler este arquivo antes de tudo. Cron e tarefas em segundo plano desta sessão **morrem com ela**: veja "Como retomar".

## 1. Estado em 09/11 13:53

### Preços (Etiqueta, `achadinhos.db`, preço válido = `preco_em` nas últimas 48 h)
| Loja | Com preço válido | Situação |
|---|---|---|
| Amazon | 6.612 de 10.880 | Busca renovou 6.314 hoje; mais 55 pelas páginas de produto. Restante: 2.570 abaixo do piso, cerca de 1.400 não alcançados pela busca (as páginas de produto param em captcha), 600 sem preço legível, 14 usados. |
| Shopee | 378 de 540 | Concluída. 155 abaixo do piso, 4 indisponíveis, 3 não vistos. |
| Mercado Livre | 530 de 3.818 | Pela API oficial, aba por aba (rodando em segundo plano às 13:53). Itens fora do catálogo só pelo Chrome. |

Produto sem preço válido fica bloqueado para envio (disparo e API v1 do Turbo; `config.preco_validade_horas` = 48).

### Mercado Livre por aba (API, 09/11)
- Games: 63 (+7 no teste das 09:11); 127 fora do catálogo.
- Celulares e Informática: 246; 474 fora do catálogo.
- Áudio e Acessórios: 109; 146 fora do catálogo.
- Eletroportáteis: 105; 160 fora do catálogo.
- TV, Alexa e Casa Conectada: 0, bateu no limite da API (429). Refazer.
- Eletrodomésticos e Climatização: 0, bateu no limite da API (429). Refazer.
- Casa, Móveis e Ferramentas: rodando às 13:47.
- Faltam: Cozinha, Cama, Mesa e Banho, Beleza e Cuidados, Pets, Bebês e Brinquedos, Suplementos e Fitness, Mercado e Limpeza.
- Registro: `/tmp/claude-1000/-home-ufla-Documentos-saas-etiqueta/4422e68f-2e6b-487b-ad71-912445b9a7f2/scratchpad/atualizar-ml-abas-0911.log` (some quando o /tmp for limpo).

## 2. O que foi feito no código (NÃO commitado; falta o "pode commitar" do dono)
- **Shopee por item (G1).** Em `coletar_shopee.py`, a `CONSULTA_ITEM` continua com `$shopId: Int64, $itemId: Int64`. O `corpo_item` agora manda os ids como **texto de dígitos** (`str(int())`), porque, como número JSON, a API recusa com 10010. Isso já tinha sido medido no garimpo (#37/#38). Os testes usam o helper `ids_do_corpo` em `test_coletar_shopee.py`, `test_shopee_por_item_qa.py` e `test_atualizar_precos.py`. Revisão: revisor APROVADO COM RESSALVAS (R1, R2, R3 e R4 corrigidos), seguranca SEM BLOQUEIOS (S1 corrigido). O plano `docs/produto/planos/atualizar-precos-shopee-por-item.md` e o `CLAUDE.md` foram atualizados.
- **Trabalho de 08/11, também sem commit:** trava de preço velho na API v1 (`api_ofertas.py`), Shopee por item (`atualizar_precos.py`), `proteger_processo()` (`coletar_shopee.py` e `ml_api.py`), testes novos (`test_api_ofertas_validade_qa.py` e `test_shopee_por_item_qa.py`), README, CLAUDE.md e docs.
- **Verificação de 09/11:** `test_coletar_shopee` 122 OK, `test_shopee_por_item_qa` 108 OK, `test_shopee_qa` 65 OK e `test_ordens_qa` 28 OK. Em `test_atualizar_precos` há 3 falhas que já se conhecem e só acontecem antes das 07:00.
- `git status` às 13:53: 28 arquivos modificados e 6 novos (inclusive `docs/produto/specs/black-friday.md` e `tools/garimpo_feminino/testes/test_qa_entrega1.py`, de outras frentes).

## 3. Scripts do dono (fora do repositório, em `~`)
- `~/atualizar-shopee.sh`: faz backup, pede o AppID e o Secret com `read -rs`, roda o G1, depois 10 itens e depois a aba inteira. Rodou com sucesso em 09/11 às 04:2x.
- `~/atualizar-ml.sh`: faz backup, pede a Chave secreta do ML com `read -rs`, roda o teste na aba Games e depois a rodada completa. A rodada completa sem `--cat` bate no 429 logo no início; **use aba por aba**. A chave só é necessária quando o token vence (cerca de 6 h depois da última renovação, que foi às 09:11 de 09/11).
- Aba por aba, sem chave enquanto o token valer, num terminal do dono ou por um agente:
  ```bash
  cd ~/Documentos/saas/etiqueta && for cat in "TV, Alexa e Casa Conectada" "Eletrodomésticos e Climatização" "Cozinha" "Cama, Mesa e Banho" "Beleza e Cuidados" "Pets" "Bebês e Brinquedos" "Suplementos e Fitness" "Mercado e Limpeza" "Casa, Móveis e Ferramentas"; do python3 atualizar_precos.py ml --cat "$cat" --vincular 300 --max-chamadas 1500; r=$?; [ $r -eq 2 ] && break; [ $r -eq 3 ] && sleep 300; done
  ```
  Saída 2 quer dizer que o acesso venceu: o dono roda `bash ~/atualizar-ml.sh`.
- Amazon, sem credencial: `python3 atualizar_precos.py amazon [--produtos 300]`. O captcha sai com 3; espere algumas horas antes de tentar de novo.

## 4. Segurança (ação do dono)
- Em 09/11 o dono **colou o AppID e o Secret da Shopee na conversa** (duas vezes). Eles ficaram no histórico local da sessão. Orientação dada: gerar um Secret novo na Open API. Não se sabe se ele já gerou.
- Nenhum segredo foi gravado em arquivo por agente. Os scripts leem com `read -rs`, sem `export`.

## 5. Campanhas Meta (conta 2009869297060043)
- **Teto: R$ 1.500** desde 09/11 ~07:20 (antes R$ 1.200 e, antes disso, R$ 800). Gasto às 12:47: R$ 794,64. Máximo possível: R$ 1.494,74. Guarda: R$ 1.495.
- **Ativos, até 13/11 23:59, com orçamento total:**
  - `DESEJO | F3 | A pagina longa` (120251338023000783), R$ 320, link `https://desejodemenina.com/?utm_...`;
  - `DESEJO | F3 | B so hero` (120251338023390783), R$ 320, link `https://desejodemenina.com/entrar-no-grupo.html?utm_...`;
  - `ACHADOS | F3 | B so hero` (120251338027690783), R$ 175, link `https://decisoesquedaolucro.com/entrar-no-grupo.html?utm_...`.
  - O sufixo dos links é `utm_source=meta&utm_medium=paid&utm_campaign={{campaign.name}}&utm_term={{adset.name}}&utm_content={{ad.name}}`.
- **Pausados** (não religar sem refazer a conta do teto): DESEJO F1 C1, C2, C3 e C4 (orçamento diário), DESEJO F2 C2+C3, a campanha ACHADOS F2 (sobra R$ 211,15) e a ACHADOS F1.
- **21 anúncios aprovados:**
  - 7 F3: C2 e C3 nas duas páginas da Desejo; C1, C2 e C3 na Eletrônicos;
  - 14 F4, subidos às 07:05: M05, M07, M08 e M11 nas duas páginas da Desejo; E01, E05, E06, E07, E08 e E12 na Eletrônicos.
  - O E01 mostra o Galaxy Fit3 a R$ 189,01, preço de 09/11; às 08h estava R$ 189,00. Se subir, pause esse anúncio.
- **Placar às 12:47:**
  - Desejo A: R$ 43,19, 348 visitas, 4 toques com `c` (1,1%);
  - Desejo B: R$ 42,84, 344 visitas, 5 toques (1,5%);
  - Eletrônicos B: R$ 28,87, 163 visitas, 1 toque (0,6%);
  - Fisher A×B ≈ 0,75 (sem diferença);
  - entradas desde 08/11 01:30: Desejo 8 (8 saídas), Eletrônicos 0.
- O código das páginas manda o `c` certo (conferido só lendo, em 09/11). Os toques sem `c` de 09/11 parecem testes ou visitas fora dos anúncios.
- **Pagamento:** o dono pausou tudo às 06:19 para trocar o cartão por Pix. Recebeu o passo a passo da central de cobrança e mandou religar às 06:30. A conta segue ACTIVE com forma de pagamento.
- **Registros:**
  - linha a linha: `~/Documentos/relatorios-campanhas/2026-11-08/decisoes-variante-b.md`;
  - criativos e decisões de 09/11: `~/Documentos/relatorios-campanhas/2026-11-09/decisoes.md`;
  - criativos preenchidos: `~/Documentos/relatorios-campanhas/2026-11-09/criativos/`.
- **Criativos não preenchidos** (falta material real): E02, E03, E04, E09, E10, E11, M01, M02, M03, M04, M06, M09, M10 e M12.

## 6. Como retomar numa sessão nova
1. **Recriar a conferência das campanhas.** O cron desta sessão (a7aa7717) morre com ela. Use cron `17 */3 8-14 11 *` com este prompt:
   > Conferência da equipe_marketingskills (teto R$ 1.500 desde 09/11 ~07h20, era R$ 1.200; conta Meta 2009869297060043; teste A/B das páginas desde 08/11 01h30, decisões em ~/Documentos/relatorios-campanhas/2026-11-08/decisoes-variante-b.md). Só leitura, a não ser que o teto esteja em risco: 1. Some o amount_spent da conta (date_preset maximum, nível campaign). 2. Liste campanhas e conjuntos ACTIVE com budget_remaining. Esperados: DESEJO | F3 | A pagina longa (120251338023000783, R$ 320), DESEJO | F3 | B so hero (120251338023390783, R$ 320), ACHADOS | F3 | B so hero (120251338027690783, R$ 175), todos até 13/11. Máximo esperado: R$ 1.494,74. 3. Máximo possível = gasto + soma do que ainda pode ser gasto. Se passar de R$ 1.495, ou se aparecer algo ativo com orçamento diário: leia ads_account_get_activity_logs desde a última conferência; se a mudança veio de pessoa da conta, não pause, avise o dono; se não, pause o que estiver sobrando (só pausa) e registre. 4. Veja se algum anúncio desses conjuntos está DISAPPROVED ou WITH_ISSUES (inclui os 14 "F4"): se estiver, não recrie nada, registre e avise o dono. 5. Placar do teste (só leitura): por conjunto, gasto e landing_page_view e toques do contar.php (rótulo c = nome do conjunto; na Desejo também grupo.hero-b para a B), com a chave nunca impressa. Entradas pelo link do dia no disparador.db (mode=ro, só contagem). Guarda: se entradas ÷ toques somados ficar abaixo de 43% em 2 dias seguidos com 5 ou mais toques, avise o dono. 6. Anexe uma linha em ~/Documentos/relatorios-campanhas/2026-11-08/decisoes-variante-b.md. 7. Em 14/11, relatório final do teste com a equipe (Fisher A × B na Desejo; Eletrônicos B contra 4%). Nunca mexa nas landing pages, nunca aumente orçamento e nunca mexa nos limites de gasto das campanhas.
2. **Scripts dos toques e das entradas.** Os scripts usados (`toques.sh` e `ent.py`) estavam no scratchpad desta sessão e se perdem. Refazer pelo contexto da skill `equipe_marketingskills`: o `contar.php?resumo` de cada site, com a chave nunca impressa, e o `disparador.db` em `mode=ro`, só contagens de `group_events` por dia.
3. **Mercado Livre:** rodar as abas que faltam (comando na seção 3). Para os itens fora do catálogo, o dono conecta o `/chrome` (extensão logada no claude.ai com a mesma conta do Claude Code e "Acesso à rede local" liberado). Aí roda-se `ColetaML.atualizar({cat})` em lista.mercadolivre.com.br.
4. **Commit:** só com o "pode commitar" do dono (regra do CLAUDE.md).
5. **14/11:** relatório final do teste A/B.

## 7. Pendências do dono
- Gerar um Secret novo da Shopee.
- Conectar o `/chrome` (Mercado Livre fora do catálogo) e, quando o token vencer, rodar `bash ~/atualizar-ml.sh`.
- Autorizar o commit.
- Fornecer material real para os 14 criativos que faltam (prints do grupo, depoimentos com autorização, fotos de produto, preços de moda).
