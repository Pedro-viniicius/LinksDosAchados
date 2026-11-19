---
name: rodar_localmente
description: Liga ou reinicia o Etiqueta (site de mensagens de achadinhos, `servidor.py`, porta 8765) no computador do dono, com o código atual, faz backup do banco antes quando o reinício vai migrar o esquema e entrega o endereço; também sobe uma cópia de teste (porta 8766) ou passa o comando para rodar no terminal. Use quando o dono pedir para rodar, ligar, reiniciar, subir ou testar localmente o Etiqueta / site de mensagens, ou depois de uma mudança no código que ele vai querer ver funcionando.
argument-hint: "[servico | teste | terminal]  (padrão: servico)"
---

# Rodar o Etiqueta localmente

Projeto: `~/Documentos/saas/etiqueta` (Python 3.14 só stdlib, `servidor.py`, banco `achadinhos.db` em WAL). Responda sempre em português do Brasil.

Não há serviço do systemd: o servidor roda como processo solto (`setsid nohup`), que continua no ar depois que a sessão do Claude fecha, até o computador desligar ou alguém pará-lo. Mudança em `index.html` só pede recarregar a página (Ctrl+Shift+R); mudança em `.py` pede reiniciar.

Escolha o modo pelo argumento (`$ARGUMENTS`) ou pelo pedido. Sem argumento, use **servico**.

## Modo `servico` (padrão)

Rode tudo na pasta do projeto.

1. **Backup se o reinício for migrar o banco.** Subir o `servidor.py` migra o esquema (`PRAGMA user_version`) quando o código é mais novo que o banco. Compare:
   ```bash
   cd ~/Documentos/saas/etiqueta
   python3 -c "import sqlite3; c=sqlite3.connect('file:achadinhos.db?mode=ro',uri=True); print(c.execute('PRAGMA user_version').fetchone()[0])"
   grep -oP '^VERSAO_ESQUEMA = \K\d+' disparo.py
   ```
   Se o segundo número for maior, faça o backup pelo `backup_banco.py` (nunca `cp`: o banco está em WAL). Ele lê o banco em modo só leitura, confere a cópia (`integrity_check` e itens > 0), grava `backups/auto-reiniciar-AAAAMMDD-HHMMSS.db` em 0600 e guarda os 14 automáticos mais novos:
   ```bash
   python3 backup_banco.py --motivo reiniciar
   ```
   Esperado: saída 0 e a linha `backup: <caminho> ok <n> itens`. Com 1 (backup falhou) ou 2 (uso errado), pare e avise o dono com a mensagem de erro; não reinicie sem backup.
2. **Pare o servidor antigo pelo PID**, se houver (nunca `pkill -f` com padrão amplo: já derrubou o shell):
   ```bash
   PID=$(ss -ltnpH 'sport = :8765' | grep -oP 'pid=\K\d+' | head -1); echo "pid antigo: ${PID:-nenhum}"
   [ -n "$PID" ] && kill "$PID" && while kill -0 "$PID" 2>/dev/null; do sleep 0.2; done
   ```
   Se o processo na 8765 não for `python3` (veja `ss -ltnp 'sport = :8765'`), não mate: avise o dono.
3. **Suba de novo, solto da sessão**, e espere responder:
   ```bash
   setsid nohup python3 servidor.py >> servidor.log 2>&1 < /dev/null &
   curl -s --retry 20 --retry-connrefused --retry-delay 1 -o /dev/null -w '%{http_code}\n' http://localhost:8765/api/items
   ```
   Esperado: `200`. O `servidor.log` está no `.gitignore` (`*.log`).
4. **Confira que o servidor no ar roda o código em disco** (só leitura: um GET em `/api/versao`):
   ```bash
   python3 verificar.py --servidor
   ```
   Esperado: saída 0 e `em dia: ...`. Com 1, a mensagem diz o motivo: `reinicie` (o código mudou de novo, ou o processo na 8765 é anterior a esta versão, sem a rota) ou `fora do ar`. A linha `Código <hash> (último commit <commit>; ...)` do `servidor.log` mostra o código da subida.
5. Se não deu `200` ou o `verificar.py --servidor` não deu 0: mostre ao dono só as últimas linhas do log (`tail -5 servidor.log`) e a mensagem do verificador, diga o que falhou e não tente consertar mexendo em código ou banco sem pedir.
6. Responda curto: está no ar em **http://localhost:8765**, com o código atual (o hash do `verificar.py --servidor`); diga se houve backup (e o caminho) e, se a mudança foi só no `index.html`, lembre do Ctrl+Shift+R.

## Modo `teste` (cópia do banco, sem mexer nos dados reais)

Para ver código novo sem tocar no banco real. Pode rodar junto com o modo `servico`.

```bash
cd ~/Documentos/saas/etiqueta
COPIA=/tmp/claude-1000/etiqueta-teste.db   # ou o scratchpad da sessão
python3 -c "import sqlite3,sys; s=sqlite3.connect('file:achadinhos.db?mode=ro',uri=True); d=sqlite3.connect(sys.argv[1]); s.backup(d); d.close(); s.close()" "$COPIA"
```
Depois suba em segundo plano (Bash com `run_in_background: true`):
```bash
cd ~/Documentos/saas/etiqueta && http_proxy=http://127.0.0.1:9 https_proxy=http://127.0.0.1:9 ftp_proxy=http://127.0.0.1:9 ACHADINHOS_DB="$COPIA" ACHADINHOS_PORTA=8766 ACHADINHOS_API_TOKEN_ARQUIVO=/nao/existe ACHADINHOS_DISPARO=0 python3 servidor.py
```
Confira com `curl -s --retry 20 --retry-connrefused --retry-delay 1 -o /dev/null -w '%{http_code}\n' http://localhost:8766/api/items` (esperado `200`) e entregue **http://localhost:8766**, avisando que é uma cópia (o que mudar ali some). Os proxies bloqueiam o `/api/fetch` ("Atualizar preço") de sair para a Amazon. Ao fim, ou quando o dono pedir, pare pelo PID.

## Modo `terminal` (o dono quer ver a saída no terminal dele)

Não rode isto você mesmo (fica preso em primeiro plano). Passe ao dono, lembrando que a 8765 precisa estar livre (se o modo `servico` estiver no ar, pare antes pelo PID ou dê `kill` no PID que o `ss -ltnp 'sport = :8765'` mostrar):
```bash
cd ~/Documentos/saas/etiqueta && python3 servidor.py
# abra http://localhost:8765 ; Ctrl+C para encerrar
```
E o atalho opcional, para criar uma vez:
```bash
echo "alias etiqueta='cd ~/Documentos/saas/etiqueta && python3 servidor.py'" >> ~/.bashrc && source ~/.bashrc
```
Se o código novo vai migrar o banco (passo 1 do modo `servico`), faça o backup antes de passar o comando.

## Regras

- Nunca leia nem imprima `.env*`, `api_token.txt`, `api_cabecalho.txt` nem o `_chat.txt`; nunca rode `env`, `printenv`, `set` ou `declare -p`.
- Nunca edite o `achadinhos.db` à mão nem rode coletas (`coletar_*.py`, `coletar_ml.js`) a partir desta skill: elas acessam as lojas de verdade.
- Não crie `api_token.txt`: sem ele a API v1 do Achadinho Turbo fica desligada (503), e é o dono quem o cria.
- O Achadinho Turbo (porta 3737) é outro projeto, com a própria skill `rodar_localmente` em `~/Documentos/achadinhoturbo`; não mexa nele daqui.
