import concurrent.futures
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

MODULE=Path(__file__).resolve().parents[1]/"runtime/python/memory.py"
spec=importlib.util.spec_from_file_location("kit_memory",MODULE)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


class MemoryTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix="context-kit-test-")
        self.root=Path(self.tmp.name).resolve();self.project=str(self.root/"sample")
        self.file=self.root/"memory.sqlite3";self.db=m.Memory(self.file)
        self.req={"action":"capture","project":self.project,"session":"s1","entry":"n1","source_file":str(self.root/"session.jsonl"),"ancestor_entries":[],"sources":{
            "u1":{"text":"Prepare staging. Production deployment is forbidden. Three replicas.","role":"user"},
            "u2":{"text":"Change replicas to two. Migration remains unfinished.","role":"user"}},
            "state":{"version":1,"goal":{"text":"Prepare staging","sources":["u1"]},
            "constraints":[{"text":"Production deployment is forbidden","sources":["u1"]}],
            "decisions":[{"id":"d1","text":"3 replicas","status":"superseded","sources":["u1"]},{"id":"d2","text":"2 replicas","status":"active","sources":["u2"]}],
            "progress":[{"text":"Migration is unfinished","status":"pending","sources":["u2"]}],"next":["Test migration"],"questions":[]}}

    def tearDown(self):self.db.close();self.tmp.cleanup()

    def search(self,q,**args):return self.db.search({"project":self.project,"query":q,**args})["items"]

    def remember(self,text="Use staging",key="deploy.target",session="s2",**args):
        return self.db.remember({"project":self.project,"text":text,"key":key,"session":session,"source_ids":["u1"],"sources":self.req["sources"],**args})

    def test_new_process_recalls_constraints_and_pending_work(self):
        self.db.capture(self.req);self.db.close();self.db=m.Memory(self.file)
        self.assertIn("Production deployment is forbidden",[x["text"] for x in self.search("deployment production")])
        self.assertTrue(any(x["state"]=="pending" for x in self.search("migration")))
        self.assertEqual([x["text"] for x in self.search("replicas")],["2 replicas"])

    def test_russian_keywords_match_english_facts(self):
        self.db.capture(self.req)
        self.assertTrue(any("replicas" in x["text"] for x in self.search("сколько реплик")))
        self.assertTrue(any("Migration" in x["text"] for x in self.search("миграцию")))

    def test_capture_idempotence(self):
        first=self.db.capture(self.req);second=self.db.capture(self.req)
        self.assertTrue(first["captured"]);self.assertFalse(second["captured"])
        self.assertEqual(self.db.db.execute("SELECT count(*) FROM facts").fetchone()[0],5)

    def test_ancestor_snapshot_replaced_not_sibling(self):
        self.db.capture(self.req)
        changed=json.loads(json.dumps(self.req));changed["entry"]="n2";changed["ancestor_entries"]=["n1"]
        changed["state"]["progress"][0]["text"]="Migration is done";changed["state"]["progress"][0]["status"]="done"
        self.db.capture(changed)
        self.assertEqual([x["state"] for x in self.search("migration")],["done"])
        fork=json.loads(json.dumps(self.req));fork["entry"]="sibling";fork["ancestor_entries"]=[]
        self.db.capture(fork)
        self.assertEqual(len(self.search("migration")),2)

    def test_missing_evidence_rolls_back_previous_state(self):
        self.db.capture(self.req)
        bad=json.loads(json.dumps(self.req));bad["entry"]="bad";bad["ancestor_entries"]=["n1"]
        bad["state"]["constraints"][0]["sources"]=["invented"]
        with self.assertRaises(ValueError):self.db.capture(bad)
        self.assertTrue(self.search("production"))
        self.assertEqual(self.db.db.execute("SELECT count(*) FROM snapshots").fetchone()[0],1)

    def test_explicit_key_conflict_and_resolution(self):
        first=self.remember();second=self.remember("Use production",session="s3")
        self.assertEqual(second["status"],"conflict")
        self.assertTrue(all(x["status"]=="conflict" for x in self.search("staging production")))
        fixed=self.remember("Use staging",session="s4",supersedes=[first["id"],second["id"]])
        self.assertEqual(fixed["status"],"active")
        self.assertEqual(len(self.search("staging production")),1)

    def test_claim_identity_preserves_negation_small_numbers_and_operators(self):
        self.remember("Делать deploy",key="instruction")
        negative=self.remember("Не делать deploy",key="instruction",session="negative")
        self.assertEqual(negative["status"],"conflict")
        self.assertNotEqual(m.claim_key("replicas=2"),m.claim_key("replicas=3"))
        self.assertNotEqual(m.claim_key("port!=443"),m.claim_key("port=443"))

    def test_cross_project_candidates_are_labelled(self):
        self.db.capture(self.req)
        result=self.db.search({"project":str(self.root/"other"),"query":"production deployment"})
        self.assertTrue(result["cross_project_candidates"])
        self.assertTrue(all(x["project"]==m.project_identity(self.project)[1] for x in result["items"]))
        self.assertFalse(self.db.search({"project":str(self.root/"other"),"query":"hello"})["items"])

    def test_global_preference_requires_user_source(self):
        fact=self.remember("Answer in Russian",key="response.language",scope="user")
        self.assertEqual(fact["status"],"active")
        self.assertTrue(self.db.search({"project":str(self.root/"other"),"query":"Russian"})["items"])
        with self.assertRaises(ValueError):self.remember(scope="user",sources={"u1":{"text":"inferred preference","role":"assistant"}})

    def test_secrets_rejected_and_source_excerpt_redacted(self):
        with self.assertRaises(ValueError):self.remember("Bearer "+"x"*40)
        fact=self.remember(sources={"u1":{"role":"user","text":"A note with Bearer "+"x"*40}})
        evidence=self.db.evidence(fact["id"])
        self.assertIn("[REDACTED]",evidence["evidence"][0]["excerpt"])
        self.assertNotIn("x"*40,json.dumps(evidence))

    def test_recalled_cards_cannot_be_independent_sources(self):
        with self.assertRaises(ValueError):self.remember(sources={"u1":{"role":"user","text":"recalled","recalled":True}})

    def test_old_sources_do_not_appear_new_when_imported_today(self):
        self.req['sources']['u1']['timestamp']='2024-01-01T00:00:00Z'
        self.db.capture(self.req)
        result=self.search('production')[0]
        self.assertIn('2024-01-01T00:00:00Z',result['source_dates'])
        self.assertEqual(result['stored_age_days'],0)
        self.assertFalse(result['source_time_unknown'])

    def test_v1_source_date_migration_preserves_existing_facts(self):
        self.db.capture(self.req)
        self.db.db.execute('ALTER TABLE evidence DROP COLUMN source_time');self.db.db.execute('PRAGMA user_version=1');self.db.db.commit()
        self.db.close();self.db=m.Memory(self.file)
        self.assertTrue(self.search('production')[0]['source_time_unknown'])
        self.assertEqual(self.db.status()['schema'],2)

    def test_forget_removes_recall_and_prevents_automatic_reinsertion(self):
        fact=self.remember();self.db.forget(fact["id"])
        self.assertFalse(self.search("staging"));self.assertFalse(self.db.evidence(fact["id"])["found"])
        self.assertIsNone(self.remember(session="s9")["id"])

    def test_fts_query_injection_and_output_bounds(self):
        self.db.capture(self.req)
        self.db.search({"project":self.project,"query":'" OR * NEAR() -- DROP TABLE facts;'})
        self.assertTrue(self.db.status()["facts"])
        self.assertLess(len(json.dumps(self.db.search({"project":self.project,"query":"production migration replicas"}))),8000)

    def test_shared_graph_is_only_a_derived_projection(self):
        self.db.capture(self.req);info=self.db.graph();data=json.loads(Path(info["graph"]).read_text())
        self.assertTrue(data["graph"]["claims_are_not_verified"])
        self.assertTrue(any(e["relation"]=="cites" for e in data["links"]))
        self.assertFalse(any(n["label"]=="3 replicas" for n in data["nodes"]))

    def test_concurrent_sessions_do_not_lose_records(self):
        def worker(index):
            db=m.Memory(self.file)
            try:
                req=json.loads(json.dumps(self.req));req["session"]=f"parallel{index}";db.capture(req)
            finally:db.close()
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(worker,range(8)))
        self.assertEqual(self.db.db.execute("SELECT count(*) FROM snapshots").fetchone()[0],8)


if __name__=="__main__":unittest.main()
