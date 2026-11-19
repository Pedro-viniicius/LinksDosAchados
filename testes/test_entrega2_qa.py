#!/usr/bin/env python3
"""Testes de QA da Entrega 2 de docs/produto/planos/endurecer-entrega2.md (CA10, CA11): bordas que os testes dos
devs (test_hook_prompt.py e test_operacao.py) não cobrem.

Uso:  python3 testes/test_entrega2_qa.py -v

- HookBordas: o hook de prompt (`.claude/hooks/segredo_no_prompt.py`) com segredo colado no meio de uma frase
  (pontuação e delimitadores de markdown), com o ambiente do processo sem UTF-8, prompts de 2 MB em formas que o
  teste do dev não usa, falsos positivos extras e o valor nunca na saída.
- AutomaticoBordas: `operacao/automatico.sh` e `atualizar-ml.sh --sem-chave` chamados com o rastreio do bash
  ligado (o valor do segredo do ambiente nunca vai à tela nem ao log), e a guarda de "código em edição" contra um
  git de verdade, com cada arquivo que a rodada executa.
- InstaladorBordas: o instalador com segredo no próprio ambiente e `--remover` ao lado de arquivos parecidos.

Os segredos falsos são montados em tempo de execução (nenhum literal aqui: o portão de commit varre os testes).
Nenhum teste roda um script de operação de verdade: `python3`, `git`, `notify-send` e `systemctl` são falsos no
PATH, e a pasta de configuração é temporária. Só biblioteca padrão.
"""
import json
import os
import shutil
import string
import subprocess
import sys
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

import test_hook_prompt as TH   # noqa: E402  (Base, gerar, rodar, entrada)
import test_operacao as TO      # noqa: E402  (BaseAutomacao: scripts com comandos falsos)

TIPO_BLOCO = TH.TIPO_BLOCO
LETRAS_DIGITOS = TH.LETRAS_DIGITOS


# ----------------------------------------------------------------------------------------------------- hook
class HookBordas(TH.Base):
    # Q1 (baixa): o bloco solto exige espaço, aspas ou fim de linha dos dois lados. Segredo no meio de uma frase,
    # com ponto final, vírgula ou entre parênteses, passa. O falso positivo do `.png` continua passando
    # (D_FalsosPositivosPassam.test_outros_comuns): o ponto só vale quando depois dele vem espaço ou o fim.
    def test_segredo_solto_com_pontuacao_de_frase_bloqueia(self):
        valor = TH.gerar(32)
        casos = ('o segredo é {v}.', '{v}, e depois outra coisa', 'copiei {v};', 'tenho {v}!', 'qual é {v}?',
                 'veja ({v})', 'veja ({v}).', 'lista [{v}]', 'em **{v}**', 'chave “{v}”', 'chave: {v}')
        for modelo in casos:
            with self.subTest(modelo=modelo):
                self.assertBloqueou(TH.rodar(modelo.format(v=valor)), valor, TIPO_BLOCO)

    def test_segredo_solto_no_fim_de_cada_linha_de_uma_lista(self):
        a, b = TH.gerar(34), TH.gerar(36)
        r = TH.rodar(f'- {a}\n- {b}\n')
        self.assertBloqueou(r, a, TIPO_BLOCO)
        self.assertNaoVazou(r, b)

    def test_ambiente_do_processo_nao_muda_o_bloqueio(self):
        """Sem LANG, em C, sem a coerção para UTF-8 e em latin-1: o texto de bloqueio (com acento) não derruba o
        hook (uma exceção de codificação sairia com 1 e o prompt passaria)."""
        valor = TH.gerar(40)
        dados = json.dumps({'prompt': f'chave {valor} fim, ação'}, ensure_ascii=False).encode()
        ambientes = ({}, {'LC_ALL': 'C'}, {'LANG': 'POSIX'}, {'LC_ALL': 'pt_BR.ISO-8859-1'},
                     {'LC_ALL': 'C', 'PYTHONCOERCECLOCALE': '0', 'PYTHONUTF8': '0'})
        for env in ambientes:
            with self.subTest(env=env):
                self.assertBloqueou(TH.rodar(dados, env=env), valor, TIPO_BLOCO)

    def test_json_com_escapes_unicode_e_o_mesmo_prompt(self):
        """O Claude Code manda o texto em JSON: \\uXXXX e acentos no meio não escondem o bloco solto."""
        valor = TH.gerar(40)
        prompt = f'cá está a chave: {valor}\nobrigação'
        for ascii_only in (True, False):
            with self.subTest(ensure_ascii=ascii_only):
                dados = json.dumps({'prompt': prompt}, ensure_ascii=ascii_only).encode()
                self.assertBloqueou(TH.rodar(dados), valor, TIPO_BLOCO)

    def test_hook_no_repositorio_real_nao_cria_arquivo(self):
        """Rodado contra a raiz de verdade: nada novo em .claude/hooks nem em __pycache__ (o sys.dont_write_bytecode
        vale para o verificar.py importado)."""
        pasta = os.path.join(RAIZ, '.claude', 'hooks')
        cache = os.path.join(RAIZ, '__pycache__')

        def estado():
            e = {}
            for base in (pasta, cache):
                if os.path.isdir(base):
                    for nome in sorted(os.listdir(base)):
                        st = os.lstat(os.path.join(base, nome))
                        e[os.path.join(base, nome)] = (st.st_size, st.st_mtime_ns)
            return e

        antes = estado()
        for prompt in ('oi', TH.gerar(40), 'secret=' + TH.gerar(40)):
            TH.rodar(prompt)
        self.assertEqual(estado(), antes)
        self.assertEqual([n for n in os.listdir(pasta) if n != '__pycache__'], ['segredo_no_prompt.py'])
        # O __pycache__ que já existia antes (deixado por quem importou o hook fora do teste) não conta:
        # o estado() acima já prova que o hook não criou nem mudou nada nesta pasta.


class HookDesempenhoEFalsosPositivos(TH.Base):
    def medir(self, prompt):
        self.assertGreaterEqual(len(prompt.encode()), 2 * 1024 * 1024)
        import time
        inicio = time.monotonic()
        r = TH.rodar(prompt)
        tempo = time.monotonic() - inicio
        self.assertLess(tempo, TH.LIMITE_2MB_SEG, f'{tempo:.2f}s')
        return r

    def test_formas_extras_de_2mb_passam_em_menos_de_2s(self):
        def ate_2mb(unidade):
            return unidade * (2 * 1024 * 1024 // len(unidade.encode()) + 1)

        casos = {
            'muitas linhas curtas': ate_2mb('ab\n'),
            'CR puro': ate_2mb('x\r'),
            'TG- com hexadecimal longo': ate_2mb('TG-' + 'a' * 1000 + ' '),
            'APP_USR- quase certo': ate_2mb('APP_USR-1' + 'a' * 18 + ' '),
            'token com espaços depois': ate_2mb('token' + ' ' * 2000),
            'app_id com espaços depois': ate_2mb('app_id' + ' ' * 2000),
            'Bearer com espaços depois': ate_2mb('Bearer' + ' ' * 500),
            'secret= e valor de 23': ate_2mb('secret=' + 'a' * 23 + '-'),
            'só aspas': ate_2mb('"'),
            'acentos': ate_2mb('ção '),
        }
        for nome, prompt in casos.items():
            with self.subTest(nome):
                self.assertPassou(self.medir(prompt))

    def test_segredo_no_meio_de_2mb_de_linhas_curtas(self):
        valor = TH.gerar(40)
        linhas = ['ab'] * 300000
        linhas.insert(150000, valor)
        r = self.medir('\n'.join(linhas) + '\n' + 'x' * 1200000)
        self.assertBloqueou(r, valor, TIPO_BLOCO)

    def test_ids_de_32_a_64_hexadecimais_e_formatos_de_dado_passam(self):
        import secrets
        uuid_sem_hifen = secrets.token_hex(16)
        asins = ','.join('B0' + TH.gerar(8, string.ascii_uppercase + string.digits) for _ in range(6))
        base64_com_sinais = TH.gerar(20) + '+' + TH.gerar(12) + '/' + TH.gerar(8) + '=='
        for prompt in (uuid_sem_hifen, f'id {uuid_sem_hifen}.', asins, base64_com_sinais,
                       'docker image sha256:' + secrets.token_hex(32), '2026-11-17T09:06:00-03:00',
                       'MLB' + TH.digitos(10) + ' e MLB' + TH.digitos(10)):
            with self.subTest(prompt=prompt[:30]):
                self.assertPassou(TH.rodar(prompt))

    def test_segredo_depois_de_um_link_de_afiliado_na_mesma_linha_bloqueia(self):
        valor = TH.gerar(40)
        link = 'https://s.shopee.com.br/' + TH.gerar(10)
        self.assertBloqueou(TH.rodar(f'{link} {valor}'), valor, TIPO_BLOCO)

    def test_marcador_numa_linha_nao_libera_a_outra_nem_o_tipo_atribuicao(self):
        valor = TH.gerar(43, TH.URLSAFE)
        solto = TH.gerar(40)
        r = TH.rodar(f'{TH.MARCADOR}\nsecret = {valor}\n{solto}')
        self.assertEqual(r.returncode, 2)
        erro = r.stderr.decode()
        self.assertIn('atribuição de segredo', erro)
        self.assertIn(TIPO_BLOCO, erro)
        self.assertNaoVazou(r, valor)
        self.assertNaoVazou(r, solto)


# ------------------------------------------------------------------------------------ rodada automática
GIT_ENV = {'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_CONFIG_NOSYSTEM': '1'}


class AutomaticoBordas(TO.BaseAutomacao):
    MARCAS = {'ACHADINHOS_ML_SECRET': 'marca-qa-ml-8c1d', 'ACHADINHOS_SHOPEE_APP_ID': 'marca-qa-app-52e7',
              'ACHADINHOS_SHOPEE_SECRET': 'marca-qa-shopee-d094'}

    def assert_marcas_fora(self, p, marcas):
        textos = [p.stdout, p.stderr, json.dumps(self.chamadas() + self.chamadas(True))]
        logs = os.path.join(self.raiz, 'logs')
        if os.path.isdir(logs):
            for nome in os.listdir(logs):
                with open(os.path.join(logs, nome), encoding='utf-8') as f:
                    textos.append(f.read())
        for m in marcas:
            for t in textos:
                self.assertNotIn(m, t)

    def test_rastreio_do_bash_nao_leva_o_segredo_do_ambiente_a_tela(self):
        """A guarda só diz o NOME da variável: `bash -x` e SHELLOPTS=xtrace não mostram o valor."""
        modos = (('bash -x', ('bash', '-x'), None), ('SHELLOPTS', (), {'SHELLOPTS': 'xtrace'}))
        for modo, antes, extra in modos:
            for tarefa in ('backup', 'amazon', 'ml'):
                with self.subTest(modo=modo, tarefa=tarefa):
                    self.limpar()
                    p = self.rodar('automatico.sh', tarefa, antes=antes, saidas=['0', '0'],
                                   env_extra={**self.MARCAS, **(extra or {})})
                    self.assertEqual(p.returncode, 2, self.saida)
                    self.assertIn('PAROU: variável de segredo no ambiente', p.stdout)
                    self.assert_marcas_fora(p, self.MARCAS.values())

    def test_sem_chave_com_rastreio_nao_leva_a_chave_nem_do_ambiente_nem_da_entrada(self):
        chave_da_entrada = 'marca-qa-entrada-3fa9'
        modos = (('bash -x', ('bash', '-x'), None), ('SHELLOPTS', (), {'SHELLOPTS': 'xtrace'}))
        for modo, antes, extra in modos:
            with self.subTest(modo=modo):
                self.limpar()
                p = self.rodar('atualizar-ml.sh', '--sem-chave', antes=antes, entrada=chave_da_entrada + '\n',
                               saidas=['0'] * 6, env_extra={'ACHADINHOS_ML_SECRET': self.MARCAS['ACHADINHOS_ML_SECRET'],
                                                            'FALSO_LER_STDIN': '1', **(extra or {})})
                self.assertEqual(p.returncode, 0, self.saida)
                self.assertRegex(p.stderr, r'(?m)^\+ source .*/operacao/comum\.sh$')   # o rastreio estava ligado
                self.assert_marcas_fora(p, (self.MARCAS['ACHADINHOS_ML_SECRET'], chave_da_entrada))
                for c in self.chamadas():
                    self.assertEqual(c['env'], {}, c['argv'])
                    self.assertEqual(c.get('stdin'), '', c['argv'])

    # ---- a guarda de código em edição contra um git de verdade
    def git_real(self):
        """Repositório de verdade em self.raiz, com os arquivos que cada rodada executa e um commit."""
        if shutil.which('git') is None:
            self.skipTest('git não instalado')
        os.remove(os.path.join(self.bin, 'git'))
        self.git_env = {**GIT_ENV, 'GIT_CEILING_DIRECTORIES': self.tmp}
        for nome in ('servidor.py', 'disparo.py', 'genero.py', 'api_ofertas.py', 'atualizar_precos.py',
                     'backup_banco.py', 'ml_api.py', 'coletar_amazon.py', 'coletar_shopee.py', 'index.html'):
            with open(os.path.join(self.raiz, nome), 'w', encoding='utf-8') as f:
                f.write('# falso\n')
        self.git('init', '-q')
        self.git('add', '-A')
        self.git('commit', '-q', '-m', 'base')

    def git(self, *args):
        subprocess.run(['git', '-c', 'user.name=Teste', '-c', 'user.email=teste@exemplo.invalid',
                        '-c', 'commit.gpgsign=false', *args], cwd=self.raiz, check=True, capture_output=True,
                       env={'PATH': '/usr/bin:/bin', 'HOME': self.tmp, **self.git_env})

    def edita(self, nome):
        with open(os.path.join(self.raiz, nome), 'a', encoding='utf-8') as f:
            f.write('# mudança\n')

    def test_base_limpa_roda_as_tres_tarefas_com_o_git_de_verdade(self):
        """Controle dos testes abaixo: sem mudança, a guarda deixa passar (senão o 1 abaixo seria da guarda errada)."""
        self.git_real()
        for tarefa, saidas in (('backup', ['0']), ('amazon', ['0', '0']), ('ml', ['0'] * 5)):
            with self.subTest(tarefa=tarefa):
                self.limpar()
                p = self.rodar('automatico.sh', tarefa, saidas=saidas, env_extra=self.git_env)
                self.assertEqual(p.returncode, 0, self.saida)
                self.assertNotEqual(self.argvs(), [])

    def test_cada_arquivo_que_a_rodada_da_amazon_executa_trava_a_guarda(self):
        """Q2 (baixa): `atualizar_precos.py amazon` importa o coletar_amazon.py (fonte_amazon_busca), mas a guarda
        não o conhece: uma edição sem commit nele roda no timer da Amazon. Os outros arquivos da lista já travam."""
        self.git_real()
        for nome in ('atualizar_precos.py', 'servidor.py', 'disparo.py', 'genero.py', 'backup_banco.py',
                     'coletar_amazon.py'):
            with self.subTest(arquivo=nome):
                self.limpar()
                self.git('checkout', '-q', '--', '.')
                self.edita(nome)
                p = self.rodar('automatico.sh', 'amazon', saidas=['0', '0'], env_extra=self.git_env)
                self.assertEqual(p.returncode, 1, self.saida)
                self.assertEqual(self.argvs(), [])   # nem backup, nem rodada

    def test_cada_arquivo_que_a_rodada_do_ml_executa_trava_a_guarda(self):
        self.git_real()
        for nome in ('atualizar_precos.py', 'ml_api.py', 'servidor.py', 'backup_banco.py', 'operacao/comum.sh',
                     'operacao/atualizar-ml.sh', 'operacao/automatico.sh'):
            with self.subTest(arquivo=nome):
                self.limpar()
                self.git('checkout', '-q', '--', '.')
                self.edita(nome)
                p = self.rodar('automatico.sh', 'ml', saidas=['0'] * 5, env_extra=self.git_env)
                self.assertEqual(p.returncode, 1, self.saida)
                self.assertEqual(self.argvs(), [])

    def test_guarda_larga_trava_todo_py_da_raiz_e_nao_trava_index_nem_testes(self):
        """Adaptado na rodada 1 (decisão do lead para R1 = S4 = Q2, guarda larga): a guarda cobre todo .py da raiz,
        rastreado ou não, então o coletar_shopee.py (que nenhuma rodada automática executa) agora trava, como um
        módulo novo ainda sem commit. O index.html e o testes/ continuam fora."""
        self.git_real()
        for nome, esperado in (('index.html', 0), ('coletar_shopee.py', 1), ('modulo_novo.py', 1),
                               ('testes/test_novo.py', 0)):
            with self.subTest(arquivo=nome):
                self.limpar()
                self.git('checkout', '-q', '--', '.')
                self.git('clean', '-qfd', '--', '*.py', 'testes/')   # o arquivo novo do caso anterior
                os.makedirs(os.path.join(self.raiz, 'testes'), exist_ok=True)
                self.edita(nome)   # em arquivo que não existe, cria (não rastreado)
                p = self.rodar('automatico.sh', 'backup', saidas=['0'], env_extra=self.git_env)
                self.assertEqual(p.returncode, esperado, self.saida)
                self.assertEqual(self.argvs(), [['backup_banco.py', '--motivo', 'diario']] if esperado == 0 else [])


# ------------------------------------------------------------------------------------------- instalador
class InstaladorBordas(TO.BaseAutomacao):
    def setUp(self):
        super().setUp()
        self.config = os.path.join(self.tmp, 'config')
        self.destino = os.path.join(self.config, 'systemd', 'user')

    def instalar(self, *args, env_extra=None):
        env = {'XDG_CONFIG_HOME': self.config, **(env_extra or {})}
        return self.rodar('instalar-timers.sh', *args, env_extra=env)

    def test_segredo_no_ambiente_do_instalador_nao_chega_a_nenhuma_unidade(self):
        marcas = {'ACHADINHOS_ML_SECRET': 'marca-inst-ml-77ab', 'ACHADINHOS_SHOPEE_APP_ID': 'marca-inst-app-0c3e',
                  'ACHADINHOS_SHOPEE_SECRET': 'marca-inst-shopee-e1f5'}
        p = self.instalar(env_extra=marcas)
        self.assertEqual(p.returncode, 0, self.saida)
        textos = [p.stdout, p.stderr]
        for base, _, nomes in os.walk(self.tmp):
            if os.path.basename(base) in ('bin', 'falso'):   # os falsos registram o ambiente de propósito
                continue
            for nome in nomes:
                with open(os.path.join(base, nome), encoding='utf-8', errors='replace') as f:
                    textos.append(f.read())
        for m in marcas.values():
            for t in textos:
                self.assertNotIn(m, t)
        self.assertEqual(len(os.listdir(self.destino)), 6)

    def test_remover_nao_toca_em_nome_parecido_nem_nas_pastas_de_override(self):
        """`systemctl --user edit` cria etiqueta-<t>.service.d/ (override do dono): não é do instalador."""
        self.assertEqual(self.instalar('ml').returncode, 0, self.saida)
        vizinhos = {'etiqueta-ml.timer.bak': '[Timer]\n', 'etiqueta-mlx.timer': '[Timer]\n',
                    'etiqueta-ml.service.d/override.conf': '[Service]\nNice=5\n', 'etiqueta.timer': '[Timer]\n'}
        for nome, texto in vizinhos.items():
            caminho = os.path.join(self.destino, nome)
            os.makedirs(os.path.dirname(caminho), exist_ok=True)
            with open(caminho, 'w', encoding='utf-8') as f:
                f.write(texto)
        self.limpar()
        p = self.instalar('--remover', 'ml')
        self.assertEqual(p.returncode, 0, self.saida)
        for nome, texto in vizinhos.items():
            with open(os.path.join(self.destino, nome), encoding='utf-8') as f:
                self.assertEqual(f.read(), texto, nome)
        self.assertFalse(os.path.exists(os.path.join(self.destino, 'etiqueta-ml.timer')))
        self.assertFalse(os.path.exists(os.path.join(self.destino, 'etiqueta-ml.service')))

    def test_instalar_com_service_alheio_nao_grava_nem_o_timer_da_mesma_tarefa(self):
        os.makedirs(self.destino)
        with open(os.path.join(self.destino, 'etiqueta-amazon.service'), 'w', encoding='utf-8') as f:
            f.write('[Service]\nExecStart=/bin/true\n')
        p = self.instalar('backup', 'amazon')
        self.assertEqual(p.returncode, 1, self.saida)
        self.assertEqual(sorted(os.listdir(self.destino)), ['etiqueta-amazon.service'])   # nem o do backup
        self.assertEqual(self.argvs('systemctl'), [])

    def test_pasta_de_destino_que_e_link_simbolico_funciona_e_nao_sobra_temporario(self):
        """Dotfiles costumam ligar ~/.config/systemd/user a outra pasta."""
        real = os.path.join(self.tmp, 'dotfiles-systemd-user')
        os.makedirs(real)
        os.makedirs(os.path.join(self.config, 'systemd'))
        os.symlink(real, self.destino)
        p = self.instalar('backup')
        self.assertEqual(p.returncode, 0, self.saida)
        self.assertEqual(sorted(os.listdir(real)), ['etiqueta-backup.service', 'etiqueta-backup.timer'])


if __name__ == '__main__':
    unittest.main()
