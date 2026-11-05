---
name: decisao-painel-hostinger
description: Painel de métricas /painel no repositório Pagina_desejoMenina (PHP na Hostinger) e o limite do hook ao planejar em outro repositório
metadata:
  type: project
---

Em 2026-11-04 planejei o painel de métricas da campanha em `/home/ufla/Documentos/Pagina_desejoMenina` (docs lá ficam em `docs/equipe/`, não em `docs/produto/`; ADRs numeradas em `docs/equipe/adr/`, a 0011 é a deste painel).

- Desenho: PHP sem JS, `index.php` único em `site/hostinger/painel/` → `public_html/painel/`; dados, cache, sessões e `config.php` (segredos) em `domains/desejodemenina.com/painel-dados/`; contadores dos dois sites lidos pelo `contar.php?resumo` via HTTPS (funciona com contas Hostinger iguais ou diferentes); Meta pela Graph v26.0 insights com token de usuário do sistema `ads_read`.
- **Why:** o `public_html` tem subdomínios (`casamento`, `amigosdonoivo`; na decisoesquedaolucro.com, `financas`), então a publicação é arquivo a arquivo e tudo que dura fica fora dele (padrão do `contar.php`, ADR 0010). Login próprio contraria a ADR 0006, mas foi escolha do PO; o painel não muda destino de botão.
- **How to apply:** o hook do arquiteto só deixa gravar em caminhos com `/docs/produto/planos/` e na memória. Pedido para gravar em `docs/equipe/...` de outro repositório é bloqueado: não contornar; entregar o texto do plano e da ADR ao lead no relatório final para ele gravar.
- Teste de PHP ali: Docker `php:8.3-apache` (já na máquina; não há `php` no host), `--network none` para os testes de unidade.
