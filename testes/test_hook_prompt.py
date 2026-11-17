#!/usr/bin/env python3
"""Testes do hook de prompt .claude/hooks/segredo_no_prompt.py (docs/produto/planos/endurecer-entrega2.md,
etapa 2, CA10).

Uso:  python3 testes/test_hook_prompt.py -v

O hook roda como o Claude Code o chama: `python3 -I <hook>`, com o JSON no stdin, num subprocesso. Os casos (a)
a (g) da etapa estão marcados no nome das classes.

Os segredos falsos são montados em tempo de execução (secrets), nunca literais neste arquivo: o portão de
commit (`verificar.py --segredos`) varre os testes, e um valor com FALSO ou MARCADOR passaria pela exceção de
falso de teste sem provar nada. Só biblioteca padrão.
"""
import json
import os
import re
import runpy
import secrets
import shutil
import string
import subprocess
import sys
import tempfile
import time
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK_REL = os.path.join('.claude', 'hooks', 'segredo_no_prompt.py')
HOOK = os.path.join(RAIZ, HOOK_REL)
sys.path.insert(0, RAIZ)
import verificar as V  # noqa: E402

MARCADOR = V.MARCADOR
TIPO_BLOCO = 'bloco solto com cara de chave'
LETRAS_DIGITOS = string.ascii_letters + string.digits
URLSAFE = LETRAS_DIGITOS + '-_'
# O que faria o verificar.py tomar o valor por falso de teste (o _NAO_FALSO): o gerador nunca devolve.
PALAVRAS_DE_FALSO = ('falso', 'marcador', 'teste', 'exemplo', '1800012345')
LIMITE_2MB_SEG = 2.0


def gerar(n, alfabeto=LETRAS_DIGITOS, exigir=()):
    """Valor aleatório de n caracteres com letra e dígito, que não é só hexadecimal, sem cara de falso de teste
    e com cada caractere de `exigir`."""
    while True:
        v = ''.join(secrets.choice(alfabeto) for _ in range(n))
        baixo = v.lower()
        if (re.search('[A-Za-z]', v) and re.search('[0-9]', v) and not re.fullmatch('[0-9A-Fa-f]+', v)
                and not any(p in baixo for p in PALAVRAS_DE_FALSO) and all(c in v for c in exigir)):
            return v


def digitos(n):
    while True:
        v = str(secrets.choice('123456789')) + ''.join(secrets.choice(string.digits) for _ in range(n - 1))
        if '1800012345' not in v and '12345' not in v:
            return v


def entrada(prompt):
    return json.dumps({'session_id': 'sessao', 'hook_event_name': 'UserPromptSubmit', 'cwd': RAIZ,
                       'prompt': prompt}).encode()


def rodar(dados, hook=HOOK, cwd=None, env=None, timeout=30):
    if isinstance(dados, str):
        dados = entrada(dados)
    return subprocess.run([sys.executable, '-I', hook], input=dados, capture_output=True, cwd=cwd, env=env,
                          timeout=timeout)


def copiar_raiz(destino):
    """Cópia mínima da árvore (o hook e o verificar.py) numa pasta sem __pycache__. Devolve o hook da cópia."""
    os.makedirs(os.path.join(destino, '.claude', 'hooks'))
    shutil.copy2(HOOK, os.path.join(destino, HOOK_REL))
    shutil.copy2(os.path.join(RAIZ, 'verificar.py'), os.path.join(destino, 'verificar.py'))
    return os.path.join(destino, HOOK_REL)


def arvore(pasta):
    """{caminho relativo: (tamanho, mtime_ns)} de tudo sob a pasta, inclusive pastas."""
    estado = {}
    for base, pastas, arquivos in os.walk(pasta):
        for nome in pastas + arquivos:
            caminho = os.path.join(base, nome)
            st = os.lstat(caminho)
            estado[os.path.relpath(caminho, pasta)] = (st.st_size, st.st_mtime_ns)
    return estado


class Base(unittest.TestCase):
    def assertPassou(self, r, msg=None):
        self.assertEqual(r.returncode, 0, msg)
        self.assertEqual(r.stdout, b'', msg)
        self.assertEqual(r.stderr, b'', msg)

    def assertBloqueou(self, r, valor, tipo, msg=None):
        """Saída 2, JSON de bloqueio válido no stdout, o mesmo texto no stderr com o tipo e nada do valor."""
        self.assertEqual(r.returncode, 2, msg)
        saida = json.loads(r.stdout)   # um objeto JSON só, nada mais na saída
        self.assertEqual(set(saida), {'decision', 'reason', 'hookSpecificOutput'}, msg)
        self.assertEqual(saida['decision'], 'block', msg)
        self.assertEqual(saida['hookSpecificOutput'],
                         {'hookEventName': 'UserPromptSubmit', 'suppressOriginalPrompt': True}, msg)
        erro = r.stderr.decode()
        self.assertEqual(erro.strip(), saida['reason'], msg)
        self.assertIn(tipo, erro, msg)
        self.assertTrue(erro.startswith('Bloqueado: o prompt parece ter um segredo ('), msg)
        self.assertIn('Ele não foi enviado ao Claude', erro, msg)
        self.assertIn(f'`{MARCADOR}`', erro, msg)
        self.assertNaoVazou(r, valor, msg)

    def assertNaoVazou(self, r, valor, msg=None):
        """(c) nem o valor, nem um pedaço de 8 caracteres dele, aparece no stdout ou no stderr."""
        tudo = r.stdout.decode('utf-8', 'replace') + r.stderr.decode('utf-8', 'replace')
        self.assertNotIn(valor, tudo, msg)
        for i in range(0, len(valor) - 7, 4):
            self.assertNotIn(valor[i:i + 8], tudo, msg)


class A_EntradaQuePassa(Base):
    """(a) prompt limpo e entrada fora do esperado saem com 0 e sem saída."""

    def test_prompt_limpo(self):
        for prompt in ('oi', '', 'Implemente a etapa 2 do plano docs/produto/planos/endurecer-entrega2.md.',
                       'linha 1\nlinha 2\r\nlinha 3', 'Preço R$ 1.299,90 com 15% de desconto'):
            with self.subTest(prompt=prompt):
                self.assertPassou(rodar(prompt))

    def test_entrada_invalida(self):
        casos = (b'', b'{', b'nao e json', b'[]', b'"texto"', b'42', b'null', b'{}', b'{"prompt": null}',
                 b'{"prompt": 7}', b'{"prompt": ["a"]}', b'{"prompt": {"a": 1}}', b'\xff\xfe\x00',
                 b'{"prompt": "\xff"}', b'[' * 100000)
        for dados in casos:
            with self.subTest(dados=dados[:20]):
                self.assertPassou(rodar(dados))

    def test_json_invalido_com_segredo_passa_sem_eco(self):
        valor = gerar(40)
        r = rodar(('{"prompt": "' + valor).encode())
        self.assertPassou(r)


class B_SegredoBloqueia(Base):
    """(b) e (c): cada forma de segredo sai com 2, JSON com suppressOriginalPrompt e o tipo no stderr, sem o valor."""

    def test_secret_solto(self):
        for n in (32, 40, 64):
            for alfabeto in (LETRAS_DIGITOS, string.ascii_uppercase + string.digits,
                             string.ascii_lowercase + string.digits):
                valor = gerar(n, alfabeto)
                for prompt in (valor, f'a chave é {valor} e pronto', f'"{valor}"', f"'{valor}'", f'`{valor}`',
                               f'primeira linha\n{valor}\nterceira', f'{valor}\r\n', f'\t{valor}\t'):
                    with self.subTest(n=n, prompt=prompt.replace(valor, '<valor>')):
                        self.assertBloqueou(rodar(prompt), valor, TIPO_BLOCO)

    def test_atribuicao(self):
        valor = gerar(43, URLSAFE)   # o formato do secrets.token_urlsafe(32)
        for prompt in (f'ACHADINHOS_SHOPEE_SECRET={valor} python3 coletar_shopee.py conferir', f'secret = {valor}',
                       f'"client_secret": "{valor}"', f'senha: {valor}'):
            with self.subTest(prompt=prompt.replace(valor, '<valor>')):
                self.assertBloqueou(rodar(prompt), valor, 'atribuição de segredo')

    def test_bearer(self):
        valor = gerar(48, LETRAS_DIGITOS + '._-')
        r = rodar('curl -H "Authorization: Bearer ' + valor + '" http://localhost:8765/api/v1/ofertas')
        self.assertBloqueou(r, valor, 'Bearer com valor longo')

    def test_access_token_do_ml(self):
        valor = '-'.join((digitos(16), digitos(6), secrets.token_hex(16), digitos(9)))
        r = rodar('o token é APP_USR-' + valor)   # o prefixo está no nome do tipo: confere o resto
        self.assertBloqueou(r, valor, 'access token do Mercado Livre (APP_USR-)')

    def test_app_id(self):
        valor = digitos(11)
        r = rodar('ACHADINHOS_SHOPEE_APP_ID=' + valor + ' python3 coletar_shopee.py conferir')
        self.assertBloqueou(r, valor, 'AppID numérico')

    def test_varios_tipos_sem_repetir(self):
        solto, bearer = gerar(36), gerar(40)
        prompt = f'{solto}\nBearer {bearer}\nBearer {bearer}\n{solto}'
        r = rodar(prompt)
        self.assertBloqueou(r, solto, TIPO_BLOCO)
        self.assertNaoVazou(r, bearer)
        erro = r.stderr.decode()
        self.assertEqual(erro.count('Bearer com valor longo'), 1)
        self.assertEqual(erro.count(TIPO_BLOCO), 1)

    def test_texto_do_bloqueio_e_fixo(self):
        """O texto só muda pelos tipos: dois segredos diferentes dão a mesma mensagem."""
        r1, r2 = rodar(gerar(40)), rodar('outro texto ' + gerar(50) + ' aqui')
        self.assertEqual(r1.stdout, r2.stdout)
        self.assertEqual(r1.stderr, r2.stderr)


class C_BordasDaFrase(Base):
    """Rodada 1 (R3 = S1 = Q1): o Secret colado no meio de uma frase, com pontuação ou entre delimitadores de
    markdown, bloqueia; o token preso a um nome de arquivo, URL, atribuição ou id com "-"/"_" continua passando."""

    def test_pontuacao_e_delimitadores_bloqueiam(self):
        valor = gerar(40)
        modelos = ('o segredo é {v}.', 'é {v}...', '{v}, e depois', 'copiei {v};', 'termina em {v}:', 'tenho {v}!',
                   'qual é {v}?', 'veja ({v})', 'veja ({v}).', '({v}),', 'lista [{v}]', 'objeto {{{v}}}',
                   'tag <{v}>', 'em **{v}**', 'em *{v}*', 'chave “{v}”', 'chave ‘{v}’', 'chave "{v}".',
                   'Chave:{v}', 'chave:{v} e mais', 'a) {v}?!', '`{v}`.')
        for modelo in modelos:
            prompt = modelo.format(v=valor)
            with self.subTest(modelo=modelo):
                self.assertBloqueou(rodar(prompt), valor, TIPO_BLOCO)

    def test_preso_a_outra_coisa_passa(self):
        valor = gerar(40)
        modelos = ('{v}.png', 'arquivo {v}.png', 'veja {v}.png.', 'https://x.com/{v}', 'https://x.com/{v}.',
                   'x={v}', 'x={v}.', '{v}-abc', 'abc-{v}', '{v}_x', 'x_{v}', '({v}/a)', '{v}.)x', 'a.{v}',
                   '@{v}', '#{v}', '{v}@x')
        for modelo in modelos:
            prompt = modelo.format(v=valor)
            with self.subTest(modelo=modelo):
                self.assertPassou(rodar(prompt))

    def test_hexadecimal_e_tamanhos_fora_continuam_passando_com_pontuacao(self):
        for valor in (secrets.token_hex(20), secrets.token_hex(32), gerar(31), gerar(65), 'a' * 40, digitos(40)):
            for modelo in ('commit {v}.', '({v})', '**{v}**', 'Chave:{v}', '“{v}”,'):
                prompt = modelo.format(v=valor)
                with self.subTest(prompt=prompt[:30]):
                    self.assertPassou(rodar(prompt))


class D_FalsosPositivosPassam(Base):
    """(d) o que parece chave, mas não é, passa sem saída."""

    def test_hashes(self):
        for valor in (secrets.token_hex(20), secrets.token_hex(32), secrets.token_hex(16),
                      secrets.token_hex(20).upper()):
            for prompt in (valor, f'commit {valor}', f'git show {valor[:7]} e {valor}'):
                with self.subTest(prompt=prompt):
                    self.assertPassou(rodar(prompt))

    def test_ids_de_loja(self):
        asin = 'B0' + gerar(8, string.ascii_uppercase + string.digits)
        mlb = 'MLB' + digitos(10)
        shopee = 'https://s.shopee.com.br/' + gerar(10)
        for prompt in (asin, f'o ASIN {asin} sumiu', mlb, f'id {mlb} e MLBU{digitos(10)}', shopee,
                       f'link {shopee} ok'):
            with self.subTest(prompt=prompt):
                self.assertPassou(rodar(prompt))

    def test_url_longa_da_amazon(self):
        url = ('https://www.amazon.com.br/Fone-Ouvido-Bluetooth-Cancelamento-Ru%C3%ADdo/dp/B0'
               + gerar(8, string.ascii_uppercase + string.digits)
               + '/ref=sr_1_3?crid=' + gerar(13, string.ascii_uppercase + string.digits)
               + '&dib=' + gerar(120, URLSAFE) + '.' + gerar(43, URLSAFE)
               + '&dib_tag=se&keywords=fone+bluetooth&qid=1731800000&sprefix=fone%2Caps%2C200&sr=8-3'
               + '&tag=desejodemen01-20')
        self.assertGreaterEqual(len(url), 300)
        for prompt in (url, f'olha {url} aqui', f'"{url}"'):
            with self.subTest(prompt=prompt[:40]):
                self.assertPassou(rodar(prompt))

    def test_comandos_com_read_rs(self):
        for prompt in (
                'read -rs S; ACHADINHOS_SHOPEE_SECRET="$S" ACHADINHOS_SHOPEE_APP_ID="$A" '
                'python3 coletar_shopee.py conferir; unset S',
                'read -rs S; ACHADINHOS_ML_SECRET="$S" python3 ml_api.py autorizar; unset S',
                'read -rsp "Chave: " S; ACHADINHOS_SHOPEE_SECRET="$S" python3 atualizar_precos.py shopee '
                '--cat "Perfumes e Perfumaria"; unset S'):
            with self.subTest(prompt=prompt[:30]):
                self.assertPassou(rodar(prompt))

    def test_file_id_do_telegram(self):
        """Ids com '-'/'_', mesmo com trechos de 32+ letras e dígitos entre eles, não são blocos soltos."""
        for file_id in ('AgACAgEAAxkBAAI' + gerar(65, URLSAFE, exigir='-_'),
                        gerar(40) + '-' + gerar(20) + '_' + gerar(33),
                        'BQACAgEAAxkBAAI' + gerar(30) + '_' + gerar(36)):
            for prompt in (file_id, f'attachment_file_id="{file_id}"', f'arquivo {file_id}'):
                with self.subTest(prompt=prompt.replace(file_id, '<id>')):
                    self.assertPassou(rodar(prompt))

    def test_outros_comuns(self):
        uuid = '-'.join((secrets.token_hex(4), secrets.token_hex(2), secrets.token_hex(2), secrets.token_hex(2),
                         secrets.token_hex(6)))
        for prompt in (uuid, 'a' * 40, digitos(40), 'Anticonstitucionalissimamente' * 2, gerar(31), gerar(65),
                       '/home/dono/' + gerar(40) + '/arquivo.py', 'x=' + gerar(40), gerar(40) + '.png',
                       'sha256:' + secrets.token_hex(32)):
            with self.subTest(prompt=prompt[:30]):
                self.assertPassou(rodar(prompt))


class E_Marcador(Base):
    """(e) a linha com o marcador passa; as outras linhas continuam conferidas."""

    def test_linha_com_marcador_passa(self):
        solto, valor = gerar(40), gerar(43, URLSAFE)
        for prompt in (f'{solto} {MARCADOR}', f'{MARCADOR} secret={valor}',
                       f'oi\n{solto}  {MARCADOR}\nBearer {valor} {MARCADOR}'):
            with self.subTest(prompt=prompt.replace(solto, '<s>').replace(valor, '<v>')):
                self.assertPassou(rodar(prompt))

    def test_marcador_so_vale_na_propria_linha(self):
        solto, outro = gerar(40), gerar(40)
        r = rodar(f'{solto} {MARCADOR}\n{outro}')
        self.assertBloqueou(r, outro, TIPO_BLOCO)
        self.assertNaoVazou(r, solto)


class F_PromptGrande(Base):
    """(f) prompt de 2 MB termina em menos de 2 s, inclusive nas formas que forçariam retrocesso."""

    def medir(self, prompt):
        self.assertGreaterEqual(len(prompt), 2 * 1024 * 1024)
        inicio = time.monotonic()
        r = rodar(prompt)
        tempo = time.monotonic() - inicio
        self.assertLess(tempo, LIMITE_2MB_SEG, f'{tempo:.2f}s')
        return r

    def test_texto_comum(self):
        bloco = 'Implemente a etapa do plano com testes. O preço caiu 15% e o link é https://s.shopee.com.br/x1.\n'
        self.assertPassou(self.medir(bloco * (2 * 1024 * 1024 // len(bloco) + 1)))

    def test_formas_de_retrocesso(self):
        n = 2 * 1024 * 1024
        casos = {
            'atribuição sem dígito': 'token=' + 'a' * n,
            'chave sem atribuição': 'token ' * (n // 6 + 1),
            'atribuições curtas': 'secret=abc ' * (n // 11 + 1),
            'Bearer curto': 'Bearer abc ' * (n // 11 + 1),
            'espaços sem fim': 'token' + ' ' * n,
            'tokens longos demais': (gerar(70) + ' ') * (n // 71 + 1),
            'tokens só de letras': ('a' * 40 + ' ') * (n // 41 + 1),
            'uma linha sem espaço': 'a1' * (n // 2 + 1),
            # a pontuação depois do token (R3): só o tamanho que fecha a sequência a percorre, uma vez
            'token e pontuação longa': ('(' + gerar(40) + '.' * 1000 + 'x ') * (n // 1043 + 1),
            'token e pontuação sem fim': ' ' + gerar(40) + '.' * n + 'x',
            'delimitadores sem fim': '(*:“' * (n // 4 + 1),
            'delimitador e token longo': ('(' + 'a1' * 35) * (n // 71 + 1),
        }
        for nome, prompt in casos.items():
            with self.subTest(nome):
                self.assertPassou(self.medir(prompt))

    def test_segredo_no_fim_de_2mb(self):
        valor = gerar(40)
        r = self.medir('texto comum ' * (2 * 1024 * 1024 // 12 + 1) + '\n' + valor)
        self.assertBloqueou(r, valor, TIPO_BLOCO)


# Roda o hook com um gancho de auditoria (sys.addaudithook) e grava em argv[1] os eventos de escrita, rede e
# processo que ele disparar. O arquivo de saída é aberto antes de ligar o gancho.
AUDITORIA = r'''
import json, os, runpy, sys
saida, hook = sys.argv[1], sys.argv[2]
eventos = []
ESCRITA = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC
PREFIXOS = ('socket.', 'subprocess.', 'os.system', 'os.exec', 'os.posix_spawn', 'os.spawn', 'os.fork',
            'os.remove', 'os.rename', 'os.mkdir', 'os.rmdir', 'os.truncate', 'os.chmod', 'os.chown',
            'os.symlink', 'os.link', 'os.utime', 'shutil.', 'urllib.', 'http.', 'ftplib.', 'smtplib.',
            'sqlite3.connect', 'tempfile.', 'ctypes.')
def auditar(evento, args):
    if evento == 'open':
        _caminho, modo, flags = args
        if (isinstance(modo, str) and any(c in modo for c in 'wax+')) or (isinstance(flags, int) and flags & ESCRITA):
            eventos.append('open para escrita')
    elif evento.startswith(PREFIXOS):
        eventos.append(evento)
f = open(saida, 'w', encoding='utf-8')
sys.argv = [hook]
sys.addaudithook(auditar)
codigo = None
try:
    runpy.run_path(hook, run_name='__main__')
except SystemExit as e:
    codigo = e.code
f.write(json.dumps({'codigo': codigo, 'eventos': eventos}))
f.close()
'''


class G_NaoGravaNemUsaRede(Base):
    """(g) o hook não grava nada: HOME e diretório atual vazios continuam vazios, a raiz (sem __pycache__)
    não muda, e um gancho de auditoria não vê escrita, rede nem processo."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='hook-prompt-')
        self.addCleanup(shutil.rmtree, self.tmp)
        self.home = os.path.join(self.tmp, 'home')
        self.cwd = os.path.join(self.tmp, 'cwd')
        os.mkdir(self.home)
        os.mkdir(self.cwd)
        self.hook = copiar_raiz(os.path.join(self.tmp, 'raiz'))
        self.env = {'HOME': self.home, 'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'LANG': 'C.UTF-8',
                    'http_proxy': V.PROXY_MORTO, 'https_proxy': V.PROXY_MORTO}

    def prompts(self):
        return (('limpo', 'oi, tudo bem?'), ('bloco solto', gerar(40)), ('atribuição', 'secret=' + gerar(40)),
                ('inválido', b'{'))

    def test_home_cwd_e_raiz_nao_mudam(self):
        antes = arvore(os.path.join(self.tmp, 'raiz'))
        for nome, prompt in self.prompts():
            with self.subTest(nome):
                r = rodar(prompt, hook=self.hook, cwd=self.cwd, env=self.env)
                self.assertIn(r.returncode, (0, 2))
                self.assertEqual(os.listdir(self.home), [])
                self.assertEqual(os.listdir(self.cwd), [])
                self.assertEqual(arvore(os.path.join(self.tmp, 'raiz')), antes)

    def test_auditoria_sem_escrita_rede_nem_processo(self):
        for nome, prompt in self.prompts():
            with self.subTest(nome):
                saida = os.path.join(self.tmp, 'auditoria.json')
                dados = prompt if isinstance(prompt, bytes) else entrada(prompt)
                r = subprocess.run([sys.executable, '-I', '-c', AUDITORIA, saida, self.hook], input=dados,
                                   capture_output=True, cwd=self.cwd, env=self.env, timeout=30)
                self.assertEqual(r.returncode, 0, r.stderr[-500:])
                with open(saida, encoding='utf-8') as f:
                    resultado = json.load(f)
                self.assertEqual(resultado['eventos'], [])
                self.assertEqual(resultado['codigo'], 2 if nome in ('bloco solto', 'atribuição') else 0)

    def test_auditoria_pega_escrita(self):
        """Controle: o gancho de auditoria acusa um script que grava (senão o teste acima não prova nada)."""
        script = os.path.join(self.tmp, 'grava.py')
        with open(script, 'w', encoding='utf-8') as f:
            f.write('import sys\nopen(sys.argv[0] + ".saida", "w").close()\n')
        saida = os.path.join(self.tmp, 'auditoria.json')
        subprocess.run([sys.executable, '-I', '-c', AUDITORIA, saida, script], input=entrada('oi'), check=True,
                       cwd=self.cwd, env=self.env, timeout=30)
        with open(saida, encoding='utf-8') as f:
            self.assertIn('open para escrita', json.load(f)['eventos'])

    def test_codigo_sem_escrita_nem_rede(self):
        """Estático: nenhum open, rede, processo ou log no código do hook (cobre os ramos que o teste não roda)."""
        with open(HOOK, encoding='utf-8') as f:
            codigo = f.read()
        self.assertNotRegex(codigo, r'\bopen\(')
        self.assertNotRegex(codigo, r'\bimport\s+(socket|urllib|http|subprocess|logging|tempfile|shutil)\b')
        self.assertNotRegex(codigo, r'\bprint\(')
        self.assertNotRegex(codigo, r'write\([^)]*prompt')


ERRO_PADROES = ('hook segredo_no_prompt: não carregou os padrões do verificar.py; '
                'o prompt seguiu conferido só pelo bloco solto.\n')


class H_FalhaAberta(Base):
    """Falha aberta (P4): sem o verificar.py, o bloco solto ainda bloqueia (S3) e o resto sai com 1 e mensagem
    fixa; o verificar.py vem só da raiz do hook, sem pôr a raiz no sys.path (S2)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='hook-prompt-')
        self.addCleanup(shutil.rmtree, self.tmp)
        self.raiz = os.path.join(self.tmp, 'raiz')
        self.hook = copiar_raiz(self.raiz)

    def quebrar_verificar(self, codigo):
        with open(os.path.join(self.raiz, 'verificar.py'), 'w', encoding='utf-8') as f:
            f.write(codigo)

    def test_verificar_quebrado_ainda_bloqueia_o_bloco_solto(self):
        """S3: com o verificar.py quebrado (exceção, sintaxe ou ausente), o Secret solto ainda dá 2."""
        valor = gerar(40)
        for nome, codigo in (('exceção', 'raise RuntimeError("quebrado")\n'), ('sintaxe', 'def (\n'),
                             ('ausente', None)):
            with self.subTest(nome):
                if codigo is None:
                    os.remove(os.path.join(self.raiz, 'verificar.py'))
                else:
                    self.quebrar_verificar(codigo)
                for prompt in (valor, f'o segredo é {valor}.', f'oi\nChave:{valor}'):
                    self.assertBloqueou(rodar(prompt, hook=self.hook, cwd=self.tmp), valor, TIPO_BLOCO)

    def test_verificar_quebrado_sem_bloco_solto_sai_com_1_sem_eco(self):
        """Sem achado do bloco solto, falha aberta: 1 e a mensagem fixa. Os padrões do verificar.py não valem
        (a atribuição passa com 1) e a linha com o marcador local é liberada."""
        self.quebrar_verificar('raise RuntimeError("quebrado")\n')
        solto, valor = gerar(40), gerar(43, URLSAFE)
        for nome, prompt, segredo in (('limpo', 'oi, tudo bem?', None), ('atribuição', f'secret={valor}', valor),
                                      ('marcador', f'{solto} {MARCADOR}', solto)):
            with self.subTest(nome):
                r = rodar(prompt, hook=self.hook, cwd=self.tmp)
                self.assertEqual(r.returncode, 1)
                self.assertEqual(r.stdout, b'')
                self.assertEqual(r.stderr.decode(), ERRO_PADROES)
                if segredo:
                    self.assertNaoVazou(r, segredo)

    def test_varredura_quebrada_sai_com_1_sem_eco(self):
        """Uma exceção cuja mensagem cita o texto não chega à saída: só a mensagem fixa."""
        with open(os.path.join(self.raiz, 'verificar.py'), 'a', encoding='utf-8') as f:
            f.write('\ndef varrer_linhas(arquivo, linhas):\n    raise ValueError(repr(list(linhas)))\n')
        valor = gerar(40)
        r = rodar(valor, hook=self.hook, cwd=self.tmp)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout, b'')
        self.assertEqual(r.stderr.decode(), 'hook segredo_no_prompt: a conferência de segredo falhou; '
                                            'o prompt seguiu sem ela.\n')
        self.assertNaoVazou(r, valor)

    def test_modulo_falso_na_raiz_nao_e_carregado(self):
        """S2: um socket.py na raiz (o verificar.py importa socket) não entra no lugar do da biblioteca padrão."""
        with open(os.path.join(self.raiz, 'socket.py'), 'w', encoding='utf-8') as f:
            f.write('import sys\nsys.stderr.write("socket falso carregado\\n")\nraise SystemExit(97)\n')
        self.assertPassou(rodar('oi', hook=self.hook, cwd=self.raiz))
        valor = gerar(43, URLSAFE)   # a atribuição só sai dos padrões do verificar.py: ele carregou inteiro
        self.assertBloqueou(rodar(f'secret={valor}', hook=self.hook, cwd=self.raiz), valor, 'atribuição de segredo')

    def test_marcador_local_igual_ao_do_verificar(self):
        """O marcador do bloco solto sem o verificar.py é o mesmo do portão de commit."""
        antes = sys.dont_write_bytecode
        try:
            modulo = runpy.run_path(HOOK, run_name='hook_sem_main')   # sem __main__: não lê o stdin
        finally:
            sys.dont_write_bytecode = antes
        self.assertEqual(modulo['MARCADOR'], V.MARCADOR)
        with open(HOOK, encoding='utf-8') as f:
            self.assertNotIn(V.MARCADOR, f.read())   # montado em duas partes

    def test_verificar_do_diretorio_atual_nao_e_usado(self):
        cwd = os.path.join(self.tmp, 'cwd')
        os.mkdir(cwd)
        with open(os.path.join(cwd, 'verificar.py'), 'w', encoding='utf-8') as f:
            f.write('raise RuntimeError("não devia ser importado")\n')
        env = dict(os.environ, PYTHONPATH=cwd)
        self.assertPassou(rodar('oi', hook=self.hook, cwd=cwd, env=env))
        valor = gerar(40)
        self.assertBloqueou(rodar(valor, hook=self.hook, cwd=cwd, env=env), valor, TIPO_BLOCO)


if __name__ == '__main__':
    unittest.main()
