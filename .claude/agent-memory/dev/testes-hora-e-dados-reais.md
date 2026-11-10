---
name: testes-hora-e-dados-reais
description: Como provar teste sem dependência da hora (TZ POSIX) e como ficaram os skips de dados reais (ACHADINHOS_TESTE_DADOS_REAIS=1); oráculo _RE_PARECE_LINK com fronteira
metadata:
  type: project
---

Etapas 1 e 2 do plano endurecer-engenharia-e-operacao (2026-11-09):

- **Hora do dia:** `preco_em` gravado como `A.hoje()+'T07:00:00'` é futuro antes das 07h e conta como velho (folga de 5 min). Use `T00:00:00`. Prova: `TZ='XXX+N'` dá local = UTC - N (N = (UTC - 3 + 24) % 24 para cair às 03h; `date` com esse TZ confirma). Rode a versão antiga do arquivo copiada para `testes/_x.py` (apague depois) e a nova com o mesmo TZ: antes 3 falhas, depois OK. Não use `git stash` com outros devs editando em paralelo.
- **Skip de dados reais:** decorador `DADOS_REAIS = unittest.skipUnless(os.environ.get('ACHADINHOS_TESTE_DADOS_REAIS') == '1', 'dados reais: rode verificar.py --dados-reais')` nas classes; subclasse herda o skip da base (`CopiaMigrada`). Sem a variável, `test_api_ofertas_qa` roda em ~4 s (era ~200 s); com ela, 41 testes OK em ~190 s.
- `CodigoAntigoSobreOBancoV3` pula sempre com a variável (o HEAD já tem a feature): skip anterior à etapa, com motivo.
- **Oráculo `_RE_PARECE_LINK`:** o TLD precisa de `\b` depois (`l.eb2gam1` de um modelo de ar-condicionado LG não é link). O positivo está em `test_o_oraculo_com_fronteira_ainda_pega_link_de_verdade`; sem o `\b` ele e o caso sintético do título real falham (provado com cópia do arquivo).
