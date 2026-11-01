import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('health',Path(__file__).resolve().parents[1]/'runtime/python/health.py')
h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)


class HealthTest(unittest.TestCase):
    def entries(self):
        return [
            {'id':'a','type':'message','message':{'role':'assistant','provider':'test','model':'fixture','content':[{'type':'text','text':'PRIVATE TEST CONTENT'},{'type':'toolCall','name':'context_notes','arguments':{'state':{}}}], 'usage':{'input':100,'output':20,'cacheRead':900,'cacheWrite':0,'totalTokens':1020}}},
            {'id':'b','type':'message','message':{'role':'toolResult','toolName':'context_notes','isError':True}},
            {'id':'c','type':'custom','customType':'experimental_context_notes','data':{'text':'PRIVATE TEST CONTENT'}},
            {'id':'d','type':'custom_message','customType':'omp-context-kit.recall','content':'память'},
            {'id':'e','type':'compaction','tokensBefore':1000,'details':{'kind':'experimental-context-rollover'}},
            {'id':'f','type':'message','message':{'role':'assistant','provider':'test','model':'fixture','usage':{'input':50,'output':10,'cacheRead':50,'totalTokens':110}}}
        ]

    def test_usage_cache_checkpoint_and_recall_are_separate(self):
        value=h.summarize(self.entries())
        self.assertEqual(value['reported_input_total'],1100)
        self.assertEqual(value['reported_tokens']['output'],30)
        self.assertEqual(value['model_requests'],2)
        self.assertEqual(value['checkpoint_write_requests'],1)
        self.assertEqual(value['checkpoint_saves'],1)
        self.assertEqual(value['context_notes_errors'],1)
        self.assertEqual(value['recall_utf8_bytes'],len('память'.encode()))
        self.assertEqual(value['latest_rollover']['next_request_input'],100)
        self.assertNotIn('PRIVATE TEST CONTENT',json.dumps(value))

    def test_active_branch_filter_and_incomplete_tail(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'session.jsonl';p.write_text('\n'.join(json.dumps(e) for e in self.entries())+'\n{"unfinished"',encoding='utf-8')
            before=p.read_bytes();value=h.report({'file':str(p),'entry_ids':['f']})
            self.assertEqual(value['model_requests'],1);self.assertEqual(value['reported_input_total'],100)
            self.assertEqual(value['malformed_or_incomplete_lines'],1)
            self.assertFalse(value['partial']);self.assertEqual(p.read_bytes(),before)

    def test_native_summary_is_counted_even_with_no_successful_checkpoint(self):
        entries=[{'type':'compaction','method':'soft','tokensBefore':130000,'tokensAfter':8000},self.entries()[-1]]
        value=h.summarize(entries)
        self.assertEqual(value['compactions'],1);self.assertEqual(value['summary_compactions'],1)
        self.assertEqual(value['rollovers'],0);self.assertEqual(value['checkpoint_saves'],0)
        self.assertEqual(value['latest_compaction']['next_request_input'],100)
        self.assertEqual(value['latest_compaction']['method'],'soft')
        self.assertIn('summarizer',value['limitations'])

    def test_missing_usage_and_non_session_files_are_explicit(self):
        self.assertEqual(h.summarize([{'message':{'role':'assistant'}}])['usage_missing'],1)
        self.assertIsNone(h.summarize([])['cache_read_share_percent'])
        with self.assertRaises(ValueError):h.report({})


if __name__=='__main__':unittest.main()
