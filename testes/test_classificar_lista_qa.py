#!/usr/bin/env python3
"""Testes de QA do classificar_lista.py (disparo-automatico, etapa 6, CA12): bordas além do test_classificar_lista.py.

Uso:  python3 testes/test_classificar_lista_qa.py -v

Cada teste roda numa CÓPIA do projeto (servidor.py, os dois scripts, buscas.json e um lista_whatsapp.json
que o teste escreve) dentro de um diretório temporário, sobre um achadinhos.db semeado ao lado dela, com
--sim. ACHADINHOS_DB aponta para esse arquivo: nada alcança o banco real. Proxy morto, só biblioteca padrão.
"""
import contextlib
import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_classificar_lista as D  # noqa: E402  (semear, MAPA, ORIGEM, DESTINO; define o ambiente temporário)
import test_servidor as TS  # noqa: E402

T, ORIGEM, DESTINO = D.T, D.ORIGEM, D.DESTINO


class ProjetoCopia(unittest.TestCase):
    NOME_DB = 'achadinhos.db'   # com esse nome, o script o trata como o banco real (pede --sim)

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix='achadinhos-classificar-qa-')
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        for f in ('servidor.py', 'migrar_categorias.py', 'classificar_lista.py', 'buscas.json'):
            shutil.copy(os.path.join(TS.RAIZ, f), self.dir)
        self.db = os.path.join(self.dir, self.NOME_DB)
        self.mapa_json = os.path.join(self.dir, 'lista_whatsapp.json')
        self.escrever_mapa({str(k): v for k, v in D.MAPA.items()})
        D.semear(self.db)
        self.antes = T.linhas(self.db)
        self.env = TS.ambiente(self.db, TS.porta_livre())
        self.env.pop('PYTHONPATH', None)

    def escrever_mapa(self, mapa):
        with open(self.mapa_json, 'w', encoding='utf-8') as f:
            f.write(mapa if isinstance(mapa, str) else json.dumps(mapa, ensure_ascii=False))

    def rodar(self, *args, env=None):
        r = subprocess.run([sys.executable, os.path.join(self.dir, 'classificar_lista.py'), *args], cwd=self.dir,
                           env=env or self.env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=90)
        return r

    def mapa_com(self, **mudancas):
        m = {str(k): dict(v) for k, v in D.MAPA.items()}
        for k, v in mudancas.items():
            m[k.lstrip('i')] = v
        return m

    def cats(self):
        con = sqlite3.connect(f'file:{self.db}?mode=ro', uri=True)
        try:
            return {i: (c, b) for i, c, b in con.execute('SELECT id, cat, busca FROM items')}
        finally:
            con.close()


class TestMapaRuim(ProjetoCopia):

    def assertAbortou(self, r, trecho):
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn(trecho, r.stderr)
        self.assertNotIn('Traceback', r.stderr)
        self.assertEqual(T.linhas(self.db), self.antes)
        self.assertEqual(T.backups(self.dir), [])

    def test_mapa_com_id_que_nao_existe_aborta_sem_gravar(self):
        m = self.mapa_com()
        m['99999'] = {'item_id': 'B0NAOEXISTE', 'cat': DESTINO, 'busca': 'Monitor'}
        self.escrever_mapa(m)
        for args in (('--dry-run',), ('--sim',)):
            self.assertAbortou(self.rodar(*args), 'id=99999: não existe no banco')

    def test_item_id_trocado_entre_dois_ids_aborta_e_lista_os_dois(self):
        con = sqlite3.connect(self.db)
        i9 = con.execute('SELECT item_id FROM items WHERE id=9').fetchone()[0]
        i10 = con.execute('SELECT item_id FROM items WHERE id=10').fetchone()[0]
        con.execute('UPDATE items SET item_id=? WHERE id=9', ('TMP-TROCA',))
        con.execute('UPDATE items SET item_id=? WHERE id=10', (i9,))
        con.execute('UPDATE items SET item_id=? WHERE id=9', (i10,))
        con.commit()
        con.close()
        self.antes = T.linhas(self.db)
        r = self.rodar('--sim')
        self.assertAbortou(r, 'id=9: item_id no banco é')
        self.assertIn('id=10: item_id no banco é', r.stderr)

    def test_json_malformado_aborta_so_com_o_tipo_do_erro(self):
        for conteudo in ('{"1": {"item_id": "B0G5NZ82TJ", ', '\x00\x01lixo', '', '{"1": }'):
            self.escrever_mapa(conteudo)
            r = self.rodar('--sim')
            self.assertAbortou(r, 'ERRO: não consegui ler')

    def test_mapa_ausente_aborta(self):
        os.remove(self.mapa_json)
        self.assertAbortou(self.rodar('--sim'), 'ERRO: não consegui ler')

    def test_dry_run_e_sim_juntos_nao_gravam_nem_fazem_backup(self):
        r = self.rodar('--dry-run', '--sim')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('--dry-run: nada foi gravado e nenhum backup foi criado.', r.stdout)
        self.assertIn('Total a mudar: 74', r.stdout)
        self.assertEqual(T.linhas(self.db), self.antes)
        self.assertEqual(T.backups(self.dir), [])

    def test_busca_com_aspas_e_sql_no_mapa_e_gravada_como_texto(self):
        busca = "x'); DROP TABLE items; --"
        m = self.mapa_com()
        m['9']['busca'] = busca
        self.escrever_mapa(m)
        r = self.rodar('--sim')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        con = sqlite3.connect(self.db)
        self.assertEqual(con.execute('SELECT busca FROM items WHERE id=9').fetchone()[0], busca)
        self.assertEqual(con.execute('SELECT COUNT(*) FROM items').fetchone()[0], len(self.antes))
        con.close()

    def test_busca_ou_cat_com_caractere_de_controle_no_mapa_nao_chega_crua_ao_terminal(self):
        m = self.mapa_com()
        m['9']['busca'] = 'Console\x1b[2K\x07'
        m['10']['cat'] = 'Aba\x1b]0;x\x07 nova'
        self.escrever_mapa(m)
        for args in (('--dry-run',), ('--sim',)):
            r = self.rodar(*args)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertNotIn('\x1b', r.stdout + r.stderr, args)
            self.assertNotIn('\x07', r.stdout + r.stderr, args)

    def test_mapa_real_esta_em_nfc_sem_espaco_nas_pontas_e_sem_controle(self):
        with open(os.path.join(TS.RAIZ, 'lista_whatsapp.json'), encoding='utf-8') as f:
            bruto = json.load(f)
        self.assertEqual(len(bruto), 74)
        for k, v in bruto.items():
            for campo, texto in v.items():
                self.assertTrue(unicodedata.is_normalized('NFC', texto), (k, campo))
                self.assertEqual(texto, texto.strip(), (k, campo))
                self.assertTrue(texto.isprintable(), (k, campo))
            self.assertEqual(v['cat'], DESTINO)


class TestOutrasBordas(ProjetoCopia):

    def test_item_de_outra_loja_com_o_mesmo_item_id_fora_do_mapa_nao_e_tocado(self):
        iid = D.MAPA[9]['item_id']
        con = sqlite3.connect(self.db)
        con.execute("INSERT INTO items (id,loja,item_id,cat,busca,url,posicao) VALUES "
                    "(950,'ml',?,?,'WhatsApp','https://meli.la/dup',950)", (iid, ORIGEM))
        con.commit()
        con.close()
        antes = T.linhas(self.db)
        r = self.rodar('--sim')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('AVISO: 1 itens de "Lista WhatsApp" não estão no mapa', r.stdout)
        c = self.cats()
        self.assertEqual(c[950], (ORIGEM, 'WhatsApp'))
        self.assertEqual(c[9], (DESTINO, D.MAPA[9]['busca']))
        self.assertEqual(len(antes), len(T.linhas(self.db)))

    def test_duas_execucoes_ao_mesmo_tempo_uma_classifica_e_a_outra_muda_zero(self):
        procs = [subprocess.Popen([sys.executable, os.path.join(self.dir, 'classificar_lista.py'), '--sim'],
                                  cwd=self.dir, env=self.env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True) for _ in range(2)]
        saidas = [p.communicate(timeout=90) for p in procs]
        self.assertEqual([p.returncode for p in procs], [0, 0], saidas)
        textos = ' '.join(o for o, _ in saidas)
        self.assertEqual(textos.count('Classificação concluída: 74 itens mudados.'), 1, textos)
        self.assertEqual(len(T.backups(self.dir)), 1)
        self.assertEqual({c for c, _ in (self.cats()[i] for i in D.MAPA)}, {DESTINO})

    def test_escritor_segurando_o_lock_a_classificacao_espera_e_nao_perde_a_escrita_dele(self):
        escritor = sqlite3.connect(self.db, isolation_level=None)
        escritor.execute('BEGIN IMMEDIATE')
        escritor.execute("INSERT INTO items (id,loja,item_id,cat,busca,url,posicao) VALUES "
                         "(960,'amazon','CONC','Casa Nova','Sofá','https://www.amazon.com.br/dp/CONC',960)")
        res = {}
        t = threading.Thread(target=lambda: res.update(r=self.rodar('--sim')))
        t.start()
        time.sleep(1.5)
        self.assertTrue(t.is_alive(), 'tinha que estar esperando o lock')
        escritor.execute('COMMIT')
        escritor.close()
        t.join(60)
        self.assertEqual(res['r'].returncode, 0, res['r'].stdout + res['r'].stderr)
        c = self.cats()
        self.assertEqual(c[960], ('Casa Nova', 'Sofá'))
        self.assertEqual({c[i][0] for i in D.MAPA}, {DESTINO})
        self.assertEqual(T.linhas(T.backups(self.dir)[0])['CONC']['cat'], 'Casa Nova')


class TestRestaurar(ProjetoCopia):
    NOME_DB = 'teste.db'   # banco comum: o --restaurar só olha a porta do ambiente, não a 8765 real

    def test_restaurar_e_classificar_de_novo_repete_o_resultado(self):
        r = self.rodar('--sim')
        self.assertEqual(r.returncode, 0, r.stderr)
        primeiro = T.linhas(self.db)
        bk = T.backups(self.dir)[0]
        r = subprocess.run([sys.executable, os.path.join(self.dir, 'migrar_categorias.py'), '--restaurar', bk, '--sim'],
                           cwd=self.dir, env=self.env, stdin=subprocess.DEVNULL, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(T.linhas(self.db), self.antes)
        r = self.rodar('--sim')
        self.assertIn('Classificação concluída: 74 itens mudados.', r.stdout)
        depois = T.linhas(self.db)
        for k, v in primeiro.items():   # tudo igual ao primeiro resultado, menos o carimbo de hora
            self.assertEqual({c: x for c, x in depois[k].items() if c != 'atualizado_em'},
                             {c: x for c, x in v.items() if c != 'atualizado_em'}, k)


class TestDesfazerQA(ProjetoCopia):
    """--desfazer (rodada 2): só os ids do mapa, só se ainda estão como o mapa deixou, com o banco "real" protegido."""

    def classificar(self):
        r = self.rodar('--sim')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return self.cats()

    def linhas_por_id(self):
        con = sqlite3.connect(f'file:{self.db}?mode=ro', uri=True)
        con.row_factory = sqlite3.Row
        try:
            return {r['id']: dict(r) for r in con.execute('SELECT * FROM items')}
        finally:
            con.close()

    def sem_hora(self, linhas):
        return {i: {c: v for c, v in r.items() if c != 'atualizado_em'} for i, r in linhas.items()}

    def test_dry_run_e_sim_juntos_no_desfazer_nao_gravam_nem_fazem_backup(self):
        classificado = self.classificar()
        n = len(T.backups(self.dir))
        r = self.rodar('--desfazer', '--dry-run', '--sim')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('--dry-run: nada foi gravado e nenhum backup foi criado.', r.stdout)
        self.assertIn('Total a mudar: 74', r.stdout)
        self.assertEqual(self.cats(), classificado)
        self.assertEqual(len(T.backups(self.dir)), n)

    def test_desfazer_no_banco_real_sem_confirmacao_recusa_e_nao_grava(self):
        classificado = self.classificar()
        r = self.rodar('--desfazer')
        self.assertEqual(r.returncode, 1)
        self.assertIn('exige confirmação', r.stderr)
        self.assertIn('Total a mudar: 74', r.stdout)   # o plano aparece antes da pergunta
        self.assertEqual(self.cats(), classificado)
        self.assertEqual(len(T.backups(self.dir)), 1)

    def test_ciclo_classificar_desfazer_classificar_desfazer_volta_ao_inicio_sem_tocar_nos_outros(self):
        antes = self.linhas_por_id()
        for volta in range(2):
            self.classificar()
            r = self.rodar('--desfazer', '--sim')
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn('Desfeito: 74 itens voltaram para "Lista WhatsApp".', r.stdout)
            depois = self.linhas_por_id()
            self.assertEqual(self.sem_hora(depois), self.sem_hora(antes), f'volta {volta}')
            for i in (1001, 1002, 1003):   # fora do mapa, inclusive os que já estavam no destino, com a mesma busca
                self.assertEqual(depois[i], antes[i], i)
        self.assertEqual(len(T.backups(self.dir)), 4)

    def test_item_que_voltou_a_aba_por_recoleta_do_chat_nao_e_tocado_pelo_desfazer(self):
        self.classificar()
        con = sqlite3.connect(self.db)
        con.execute("INSERT INTO items (id,loja,item_id,cat,busca,url,posicao) VALUES "
                    "(970,'amazon','B0RECOLETA',?,'WhatsApp','https://www.amazon.com.br/dp/B0RECOLETA?tag=t',970)", (ORIGEM,))
        con.commit()
        con.close()
        antes = self.linhas_por_id()
        r = self.rodar('--desfazer', '--sim')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        depois = self.linhas_por_id()
        self.assertEqual(depois[970], antes[970])
        self.assertEqual({depois[i]['cat'] for i in D.MAPA}, {ORIGEM})

    def test_desfazer_com_item_ainda_na_aba_mas_com_busca_editada_aborta(self):
        """Quem mexeu na `busca` de um item da mapa que está na própria aba: o desfazer não adivinha, aborta."""
        classificado = self.classificar()
        con = sqlite3.connect(self.db)
        con.execute("UPDATE items SET cat=?, busca='Minha busca' WHERE id=9", (ORIGEM,))
        con.commit()
        con.close()
        antes = self.linhas_por_id()
        for args in (('--desfazer', '--dry-run'), ('--desfazer', '--sim')):
            r = self.rodar(*args)
            self.assertEqual(r.returncode, 1, args)
            self.assertIn('id=9: está em cat="Lista WhatsApp" busca="Minha busca"', r.stderr)
            self.assertEqual(self.linhas_por_id(), antes)
        self.assertEqual(len(T.backups(self.dir)), 1)
        self.assertNotEqual(self.cats(), classificado)   # só para garantir que a edição valeu

    def test_desfazer_com_item_no_destino_mas_busca_editada_aborta_e_nao_move_nenhum(self):
        classificado = self.classificar()
        con = sqlite3.connect(self.db)
        con.execute('UPDATE items SET busca=? WHERE id=9', ('SSD',))
        con.commit()
        con.close()
        antes = self.linhas_por_id()
        for args in (('--desfazer', '--dry-run'), ('--desfazer', '--sim')):
            r = self.rodar(*args)
            self.assertEqual(r.returncode, 1, args)
            self.assertIn(f'id=9: está em cat="{DESTINO}" busca="SSD"', r.stderr)
            self.assertEqual(self.linhas_por_id(), antes)
        self.assertEqual(sum(1 for i in D.MAPA if self.cats()[i][0] == DESTINO), 74)
        self.assertEqual(len(T.backups(self.dir)), 1)
        self.assertNotEqual(self.cats(), classificado)

    def test_item_da_lista_com_busca_nula_e_classificado_e_depois_volta_com_whatsapp(self):
        con = sqlite3.connect(self.db)
        con.execute('UPDATE items SET busca=NULL WHERE id=9')
        con.commit()
        con.close()
        r = self.rodar('--sim')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.cats()[9], (DESTINO, D.MAPA[9]['busca']))
        r = self.rodar('--desfazer', '--sim')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.cats()[9], (ORIGEM, 'WhatsApp'))

    def test_dois_desfazer_ao_mesmo_tempo_um_desfaz_e_o_outro_muda_zero(self):
        self.classificar()
        procs = [subprocess.Popen([sys.executable, os.path.join(self.dir, 'classificar_lista.py'), '--desfazer', '--sim'],
                                  cwd=self.dir, env=self.env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True) for _ in range(2)]
        saidas = [p.communicate(timeout=90) for p in procs]
        self.assertEqual([p.returncode for p in procs], [0, 0], saidas)
        textos = ' '.join(o for o, _ in saidas)
        self.assertEqual(textos.count('Desfeito: 74 itens voltaram'), 1, textos)
        self.assertEqual(len(T.backups(self.dir)), 2)
        self.assertEqual({c for c, _ in (self.cats()[i] for i in D.MAPA)}, {ORIGEM})

    def test_desfazer_espera_o_escritor_que_segura_o_lock_e_nao_perde_a_escrita_dele(self):
        self.classificar()
        escritor = sqlite3.connect(self.db, isolation_level=None)
        escritor.execute('BEGIN IMMEDIATE')
        escritor.execute("UPDATE items SET preco='R$ 7,77' WHERE id=9")   # item do mapa, outra coluna
        res = {}
        t = threading.Thread(target=lambda: res.update(r=self.rodar('--desfazer', '--sim')))
        t.start()
        time.sleep(1.5)
        self.assertTrue(t.is_alive(), 'tinha que estar esperando o lock')
        escritor.execute('COMMIT')
        escritor.close()
        t.join(60)
        self.assertEqual(res['r'].returncode, 0, res['r'].stdout + res['r'].stderr)
        linhas = self.linhas_por_id()
        self.assertEqual(linhas[9]['preco'], 'R$ 7,77')
        self.assertEqual((linhas[9]['cat'], linhas[9]['busca']), (ORIGEM, 'WhatsApp'))


class TestCorridaDentroDaTransacao(D.BancoTemporario):
    """Outra execução termina entre o plano (só leitura) e o BEGIN IMMEDIATE: a conferência de dentro da
    transação vê 0 pendentes e não grava nem faz backup (determinístico, sem depender de tempo)."""

    def rodar_main(self, args, antes_da_transacao):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(D.S, 'DB', self.db), mock.patch.object(D.M, 'confirmar_banco_real', antes_da_transacao), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = D.C.main(args)
        return rc, out.getvalue(), err.getvalue()

    def test_classificar_que_ja_foi_feito_por_outra_execucao_muda_zero_e_nao_faz_backup(self):
        def outra_execucao(acao, sim):
            for _id, m in D.MAPA.items():
                D.executar(self.db, 'UPDATE items SET cat=?, busca=? WHERE id=?', m['cat'], m['busca'], _id)
        rc, out, err = self.rodar_main([], outra_execucao)
        self.assertEqual(rc, 0, out + err)
        self.assertIn('Nada a classificar: 0 itens mudados', out)
        self.assertNotIn('Backup verificado', out)
        self.assertEqual(T.backups(self.dir), [])

    def test_desfazer_que_ja_foi_feito_por_outra_execucao_muda_zero_e_nao_faz_backup(self):
        self.assertEqual(D.rodar(self.db).returncode, 0)   # classifica (backup 1)

        def outra_execucao(acao, sim):
            D.executar(self.db, "UPDATE items SET cat=?, busca='WhatsApp' WHERE cat=? AND id <= 134", ORIGEM, DESTINO)
        rc, out, err = self.rodar_main(['--desfazer'], outra_execucao)
        self.assertEqual(rc, 0, out + err)
        self.assertIn('Nada a desfazer: 0 itens mudados', out)
        self.assertNotIn('Backup verificado', out)
        self.assertEqual(len(T.backups(self.dir)), 1)


class TestComServidorNoArEBackup(TS.ServidorTeste):
    """Servidor.py no ar: o backup traz o que só estava no WAL e o GET logo depois mostra a classificação."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        D.semear(cls.db)

    def test_backup_inclui_item_gravado_pelo_servidor_antes_e_o_item_fora_do_mapa_fica(self):
        st, _, _ = self.postar([{'loja': 'amazon', 'item_id': 'B0NOVOWAL1', 'cat': ORIGEM, 'busca': 'WhatsApp',
                                 'url': f'https://www.amazon.com.br/dp/B0NOVOWAL1?tag={D.S.TAG_AMAZON}',
                                 'data': {'titulo': 'novo'}}])
        self.assertEqual(st, 200)
        r = D.rodar(self.db, porta=self.porta)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('AVISO: 1 itens de "Lista WhatsApp" não estão no mapa', r.stdout)
        bk = T.linhas(T.backups(os.path.dirname(self.db))[0])
        self.assertEqual(bk['B0NOVOWAL1']['cat'], ORIGEM)
        self.assertEqual(len(bk), 74 + len(D.OUTROS) + 1)
        itens = {i['item_id']: i for i in self.itens()}
        self.assertEqual(itens['B0NOVOWAL1']['cat'], ORIGEM)
        self.assertEqual({itens[m['item_id']]['cat'] for m in D.MAPA.values()}, {DESTINO})
        self.assertIsNone(self.proc.poll())


    def test_desfazer_com_servidor_no_ar_preserva_o_que_o_servidor_gravou_depois(self):
        r = D.rodar(self.db, porta=self.porta)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        # depois da classificação, o servidor atualiza os dados de um item do mapa (como "Atualizar preço")
        alvo = next(i for i in self.itens() if i['id'] == 9)
        self.assertEqual(alvo['cat'], DESTINO)
        st, _, _ = self.pedir('PATCH', '/api/items/9', {'data': {'titulo': 'Título novo', 'preco': 'R$ 3,21'}},
                              headers=self.local())
        self.assertEqual(st, 200)
        r = D.rodar(self.db, '--desfazer', porta=self.porta)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('Desfeito: 74 itens voltaram', r.stdout)
        itens = {i['id']: i for i in self.itens()}   # GET logo depois, sem reiniciar
        self.assertEqual({itens[i]['cat'] for i in D.MAPA}, {ORIGEM})
        self.assertEqual({itens[i]['busca'] for i in D.MAPA}, {'WhatsApp'})
        self.assertEqual(itens[9]['data']['titulo'], 'Título novo')
        self.assertEqual(itens[9]['data']['preco'], 'R$ 3,21')
        self.assertIsNone(self.proc.poll())


if __name__ == '__main__':
    unittest.main()
