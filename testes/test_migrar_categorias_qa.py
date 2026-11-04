#!/usr/bin/env python3
"""Testes de QA do migrar_categorias.py (bordas que a suíte do dev não cobre).

Uso:  python3 testes/test_migrar_categorias_qa.py -v

Reaproveita o ambiente de test_migrar_categorias.py (banco temporário semeado, subprocesso, sem
rede, guarda contra o banco real). Planos: docs/produto/planos/eletronicos-e-coleta-ml.md, CA2 a CA6, e
docs/produto/planos/abas-nichadas-e-coleta.md, etapa 6 (as origens agora são as 3 abas de 2026-11-03).
"""
import os
import sqlite3
import subprocess
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_migrar_categorias as T  # noqa: E402
import test_servidor as TS  # noqa: E402


def inserir(db, item_id, cat, busca, loja='ml'):
    con = sqlite3.connect(db)
    cur = con.execute('INSERT INTO items (loja,item_id,cat,busca,url,posicao) VALUES (?,?,?,?,?,?)',
                      (loja, item_id, cat, busca, f'https://meli.la/{item_id}', 900))
    con.commit()
    con.close()
    return cur.lastrowid


class TestBordas(T.BancoTemporario):

    def test_busca_com_aspas_e_sql_nao_vira_comando_e_aborta(self):
        malicioso = "x'); DROP TABLE items; --"
        nid = inserir(self.db, 'MLB666', T.CASA_DECORACAO, malicioso)
        antes = T.linhas(self.db)
        r = self.rodar()
        self.assertEqual(r.returncode, 1)
        self.assertIn(f'id={nid}', r.stderr)
        self.assertEqual(T.linhas(self.db), antes)   # a tabela segue lá e nada mudou
        self.assertEqual(T.backups(self.dir), [])

    def test_busca_nula_ou_vazia_numa_origem_sem_destino_sem_busca_aborta_e_lista(self):
        """Só "Casa e Decoração" tem DESTINO_SEM_BUSCA; nas outras origens, item sem busca é órfão."""
        con = sqlite3.connect(self.db)
        con.execute("INSERT INTO items (loja,item_id,cat,busca,url,posicao) VALUES "
                    "('ml','NULO',?,NULL,'https://meli.la/n',90)", (T.ELETRONICOS,))
        con.execute("INSERT INTO items (loja,item_id,cat,busca,url,posicao) VALUES "
                    "('ml','VAZIO',?,'','https://meli.la/v',91)", (T.ELETRODOMESTICOS,))
        con.commit()
        con.close()
        antes = T.linhas(self.db)
        r = self.rodar()
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stderr.count('loja=ml cat='), 2, r.stderr)
        self.assertEqual(T.linhas(self.db), antes)

    def test_termo_com_espaco_sobrando_no_banco_nao_casa_e_aborta(self):
        """Termo "Sofá " (espaço no fim) não é o termo do mapa: aborta em vez de chutar a aba."""
        nid = inserir(self.db, 'MLB777', T.CASA_DECORACAO, 'Sofá ')
        r = self.rodar()
        self.assertEqual(r.returncode, 1)
        self.assertIn(f'id={nid}', r.stderr)
        self.assertEqual({v['cat'] for v in T.linhas(self.db).values()} & set(T.M.ORIGENS), set(T.M.ORIGENS))

    def test_item_novo_depois_da_migracao_move_so_ele_e_faz_novo_backup(self):
        self.assertOk(self.rodar())
        depois = T.linhas(self.db)
        time.sleep(1.1)   # o nome do backup tem resolução de 1 segundo (e há sufixo -N se colidir)
        inserir(self.db, 'MLB888', T.ELETRODOMESTICOS, 'Geladeira')
        r = self.rodar()
        self.assertOk(r)
        self.assertIn('Migração concluída: 1 itens movidos e 0 preços antigos limpos.', r.stdout)
        final = T.linhas(self.db)
        self.assertEqual(final['MLB888']['cat'], T.CLIMATIZACAO)
        for k, v in depois.items():
            self.assertEqual(final[k], v, k)   # os já migrados não mudam, nem o atualizado_em
        self.assertEqual(len(T.backups(self.dir)), 2)

    def test_restaurar_junto_com_dry_run_e_pedido_invalido(self):
        antes = T.linhas(self.db)
        r = self.rodar('--dry-run', '--restaurar', self.db)
        self.assertEqual(r.returncode, 2)
        self.assertEqual(T.linhas(self.db), antes)

    def test_restaurar_arquivo_sqlite_sem_tabela_items_e_recusado(self):
        self.assertOk(self.rodar())
        depois = T.linhas(self.db)
        outro = os.path.join(self.dir, 'outro.db')
        con = sqlite3.connect(outro)
        con.execute('CREATE TABLE coisa (x)')
        con.commit()
        con.close()
        r = self.rodar('--restaurar', outro)
        self.assertEqual(r.returncode, 1)
        self.assertIn('ERRO', r.stderr)
        self.assertNotIn('Traceback', r.stderr)
        self.assertEqual(T.linhas(self.db), depois)

    def test_escritor_concorrente_segurando_o_lock_a_migracao_espera_e_conclui(self):
        """Quem grava (como o servidor) e solta o lock logo: a migração espera e não perde a escrita dele."""
        escritor = sqlite3.connect(self.db, isolation_level=None)
        escritor.execute('BEGIN IMMEDIATE')
        escritor.execute("INSERT INTO items (loja,item_id,cat,busca,url,posicao) VALUES "
                         "('amazon','CONC',?,'Sofá','https://www.amazon.com.br/dp/CONC',901)", (T.CASA_DECORACAO,))
        resultado = {}

        def migrar():
            resultado['r'] = self.rodar()

        t = threading.Thread(target=migrar)
        t.start()
        time.sleep(1.5)
        self.assertTrue(t.is_alive(), 'a migração tinha que estar esperando o lock do escritor')
        escritor.execute('COMMIT')
        escritor.close()
        t.join(30)
        self.assertOk(resultado['r'])
        final = T.linhas(self.db)
        self.assertEqual(final['CONC']['cat'], T.CASA, 'o item gravado pelo escritor entra na migração')
        self.assertEqual(len(final), len(self.antes) + 1)


class TestComServidorEBackup(TS.ServidorTeste):
    """Servidor.py de verdade no ar: o backup tem que trazer o que ainda está só no WAL."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        T.semear(cls.db)

    def novo(self, item_id, cat, busca):
        st, _, _ = self.postar([{'loja': 'ml', 'item_id': item_id, 'cat': cat, 'busca': busca,
                                 'url': f'https://meli.la/{item_id}', 'data': {'titulo': busca}}])
        self.assertEqual(st, 200)

    def test_1_dry_run_com_servidor_no_ar_nao_muda_dados_nem_cria_backup(self):
        self.novo('MLBDRY', T.CASA_DECORACAO, 'Sofá')
        antes = {i['item_id']: i['cat'] for i in self.itens()}
        r = T.rodar(self.db, '--dry-run', porta=self.porta)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('Total a mover: 20', r.stdout)   # 19 da semente + o item novo
        self.assertEqual({i['item_id']: i['cat'] for i in self.itens()}, antes)
        self.assertEqual(T.backups(self.dir), [])

    def test_2_backup_inclui_item_gravado_pelo_servidor_instantes_antes(self):
        self.novo('MLBNOVO', T.ELETRONICOS, 'Kindle')
        r = T.rodar(self.db, porta=self.porta)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        no_backup = T.linhas(T.backups(self.dir)[0])
        self.assertIn('MLBNOVO', no_backup)
        self.assertIn('MLBDRY', no_backup)
        self.assertEqual(no_backup['MLBNOVO']['cat'], T.ELETRONICOS, 'o backup é o estado de antes da migração')
        cats = {i['item_id']: i['cat'] for i in self.itens()}   # GET logo depois, sem reiniciar
        self.assertEqual(cats['MLBNOVO'], T.TV)
        self.assertEqual(cats['MLBDRY'], T.CASA)
        self.assertIsNone(self.proc.poll())


if __name__ == '__main__':
    unittest.main()
