#!/usr/bin/env python3
"""Real OMP automatic compaction with rejected notes; loopback, no accounts."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import tempfile
import threading
from http.server import ThreadingHTTPServer
import time

from integration_rpc import Fixture, RPC, ROOT


class CompactionFixture(Fixture):
    requests=[]
    chat=0
    summaries=0

    def do_POST(self):
        body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.requests.append(body)
        if len(self.requests)>20:
            self.send_error(429,'Bounded compaction fixture request limit');return
        text=json.dumps(body.get('messages',[]),ensure_ascii=False)
        prompt_tokens=2000
        if not body.get('tools'):
            # Native soft summarization is a separate, tool-free request. The
            # fixture must receive the original constraint, not invent it.
            if 'SYNTHETIC_ORIGINAL_GUARD' not in text:
                self.send_error(400,'Original constraint missing from summary input');return
            type(self).summaries+=1
            delta={'role':'assistant','content':'NATIVE_SUMMARY_OK. SYNTHETIC_ORIGINAL_GUARD: Production deployment is forbidden. Active goal: verify staging migration. Migration is unfinished. Next: read the original guard from history, then report COMPACTION_RECOVERED. No project action has been executed.'}
            finish='stop'
        else:
            type(self).chat+=1
            step=self.chat
            if step==1:
                delta=self.call('bad-alias','context_notes',{'catalogue':'invalid-list','state':{'goal':{'text':'Verify staging','sources':['S1']},'progress':[{'text':'Migration unfinished','status':'in_progress','sources':['S1']}]}})
            elif step==2:
                delta=self.call('bad-source','context_notes',{'catalogue':'aabbccddeeff','state':{'goal':{'text':'Verify staging','sources':['aabbccddeeff']}}})
            elif step==3:
                delta=self.call('pressure','context_probe',{'action':'status'})
                prompt_tokens=130000
            elif step==4:
                if 'NATIVE_SUMMARY_OK' not in text:
                    self.send_error(400,'Automatic summary missing before next work step');return
                delta=self.call('history','grep',{'pattern':'SYNTHETIC_ORIGINAL_GUARD','path':'history://current/full','limit':2})
            else:
                delta={'role':'assistant','content':'COMPACTION_RECOVERED'}
            finish='tool_calls' if 'tool_calls' in delta else 'stop'
        self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Connection','close');self.end_headers()
        for item in [
            {'id':'fixture','object':'chat.completion.chunk','created':int(time.time()),'model':'fixture','choices':[{'index':0,'delta':delta,'finish_reason':None}]},
            {'id':'fixture','object':'chat.completion.chunk','created':int(time.time()),'model':'fixture','choices':[{'index':0,'delta':{},'finish_reason':finish}],'usage':{'prompt_tokens':prompt_tokens,'completion_tokens':100,'total_tokens':prompt_tokens+100}}
        ]:self.wfile.write(('data: '+json.dumps(item)+'\n\n').encode())
        self.wfile.write(b'data: [DONE]\n\n');self.wfile.flush()


async def run(prefix):
    os.umask(0o077)
    work=Path(tempfile.mkdtemp(prefix='omp-kit-compaction-')).resolve()
    manifest=json.loads((prefix/'installation.json').read_text(encoding='utf-8'))
    for f in (ROOT/'runtime').rglob('*'):
        if f.is_file() and '__pycache__' not in f.parts and not f.name.endswith('.local.json'):
            assert f.read_bytes()==(Path(manifest['app'])/f.relative_to(ROOT)).read_bytes(),'Reinstall current runtime before integration testing'
    CompactionFixture.requests=[];CompactionFixture.summaries=0
    server=ThreadingHTTPServer(('127.0.0.1',0),CompactionFixture)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    rpc=RPC(manifest,work,'context-kit-fixture/fixture',f'http://127.0.0.1:{server.server_port}/v1')
    report={'success':False,'workdir':str(work)}
    try:
        await rpc.start()
        original_ids=set()
        for cycle in range(2):
            if cycle:
                session=next((work/'sessions-1').glob('*.jsonl'))
                await rpc.close()
                rpc=RPC(manifest,work,'context-kit-fixture/fixture',f'http://127.0.0.1:{server.server_port}/v1',index=2,resume=session)
                await rpc.start()
            CompactionFixture.chat=0
            padding='\n'.join(f'Synthetic observation {i}: staging test data only, no action authorized.' for i in range(180))
            await rpc.request('prompt',message=f'CYCLE {cycle}. SYNTHETIC_ORIGINAL_GUARD: Production deployment is forbidden. Verify staging migration, which is unfinished.\n{padding}')
            entries=await rpc.entries()
            assert original_ids.issubset({e['id'] for e in entries}),'original journal entries lost'
            original_ids={e['id'] for e in entries}
            assert not any(e.get('customType')=='experimental_context_notes' for e in entries),'invalid note was committed'
            compactions=[e for e in entries if e.get('type')=='compaction']
            assert len(compactions)==cycle+1,[(e.get('method'),e.get('details')) for e in compactions]
            assert all(e.get('details',{}).get('kind')!='experimental-context-rollover' for e in compactions),'unsafe rollover used'
            assert 'NATIVE_SUMMARY_OK' in compactions[-1]['summary']
            assert compactions[-1].get('fromExtension') is not True,'extension replaced the native compactor'
            results=[e['message'] for e in entries if e.get('message',{}).get('role')=='toolResult']
            failed=[m for m in results if m.get('toolName')=='context_notes' and m.get('isError')]
            assert len(failed)==2*(cycle+1),'fixture did not reproduce rejected notes'
            history=next(m for m in reversed(results) if m.get('toolName')=='grep')
            assert not history.get('isError'),history
            assert 'SYNTHETIC_ORIGINAL_GUARD' in json.dumps(history),'full branch history unavailable'
            last=next(e['message'] for e in reversed(entries) if e.get('message',{}).get('role')=='assistant')
            assert 'COMPACTION_RECOVERED' in json.dumps(last),'current task did not automatically continue'
            assert CompactionFixture.chat==5,'unexpected continuation or repair loop'
        report.update(success=True,compactions=len(compactions),rejectedNotes=len(failed),providerRequests=len(CompactionFixture.requests),nativeSummaryRequests=CompactionFixture.summaries,
                      checks=['two threshold crossings across process restart and resume','invalid catalogue and source IDs do not block compaction','native OMP summary committed','original entries preserved','full-history grep after compaction','same task continues automatically','no checkpoint repair loop'])
    finally:
        await rpc.close();server.shutdown();server.server_close()
        (work/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps(report,indent=2),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--prefix',type=Path,required=True)
    asyncio.run(run(parser.parse_args().prefix))
