#!/usr/bin/env python3
"""Exercise actual OMP hooks across fresh processes. Default uses only loopback.

--live MODEL is explicit and uses an existing default OMP account, synthetic
messages and a 0.5 USD estimated session cap. It never copies credentials.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import time

ROOT=Path(__file__).resolve().parents[1]


class Fixture(BaseHTTPRequestHandler):
    requests=[]
    def log_message(self,*args):pass
    def do_POST(self):
        body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.requests.append(body)
        if len(self.requests)>12:
            self.send_error(429,"Test request limit");return
        messages=body.get('messages',[])
        last_user=next((m.get('content','') for m in reversed(messages) if m.get('role')=='user'),'')
        all_text=json.dumps(messages,ensure_ascii=False)
        last_tool=next((m for m in reversed(messages) if m.get('role')=='tool'),None)
        if 'FIXTURE_RECALL' in all_text:
            answer={'database':'PostgreSQL' if 'PostgreSQL' in all_text else None,'port':5433 if '5433' in all_text else None,'production_allowed':False if 'Production deployment is forbidden' in all_text else None,'migration_done':False if 'Migration is unfinished' in all_text else None}
            delta={'role':'assistant','content':json.dumps(answer)};finish='stop'
        elif not last_tool:
            delta=self.call('probe','context_probe',{'action':'sources'});finish='tool_calls'
        elif last_tool.get('tool_call_id')=='probe':
            raw=last_tool.get('content','')
            if isinstance(raw,list):raw=''.join(b.get('text','') for b in raw)
            sources=json.loads(raw)
            entry=next(x['id'] for x in sources['sources'] if x['role']=='user')
            state={'version':1,'goal':{'text':'Bluebird PostgreSQL 5433 staging preparation','sources':[entry]},
                   'constraints':[{'text':'Production deployment is forbidden','sources':[entry]}],
                   'decisions':[{'id':'db','text':'PostgreSQL on port 5433','status':'active','sources':[entry]}],
                   'progress':[{'text':'Migration is unfinished','status':'pending','sources':[entry]}],
                   'next':['Test migration'],'questions':[]}
            delta=self.call('save','context_notes',{'text':json.dumps(state)});finish='tool_calls'
        else:
            delta={'role':'assistant','content':'SAVED'};finish='stop'
        self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Connection','close');self.end_headers()
        for payload in [
            {'id':'fixture','object':'chat.completion.chunk','created':int(time.time()),'model':'fixture','choices':[{'index':0,'delta':delta,'finish_reason':None}]},
            {'id':'fixture','object':'chat.completion.chunk','created':int(time.time()),'model':'fixture','choices':[{'index':0,'delta':{},'finish_reason':finish}],'usage':{'prompt_tokens':2000,'completion_tokens':100,'total_tokens':2100}},
        ]:self.wfile.write(('data: '+json.dumps(payload)+'\n\n').encode())
        self.wfile.write(b'data: [DONE]\n\n');self.wfile.flush()
    @staticmethod
    def call(cid,name,args):return {'role':'assistant','tool_calls':[{'index':0,'id':cid,'type':'function','function':{'name':name,'arguments':json.dumps(args)}}]}


class RPC:
    def __init__(self,manifest,work,model,fixture_url=None,index=1):
        self.manifest,self.work,self.model,self.fixture_url,self.index=manifest,work,model,fixture_url,index
        self.events=[];self.queue=asyncio.Queue();self.serial=0
    async def start(self):
        config=self.work/'test.yml'
        config.write_text((ROOT/'config/config.yml').read_text(encoding='utf-8')+"\nsession:\n  maxCost: 0.5\n",encoding='utf-8')
        env={**os.environ,'OMP_KIT_MEMORY_DB':str(self.work/'memory.sqlite3'),'OMP_KIT_PYTHON':self.manifest['python'],'OMP_KIT_GRAPHIFY':self.manifest['graphify']}
        args=[self.manifest['omp'],'--cwd',str(self.work),'--mode','rpc','--no-ui','--no-lsp','--no-skills','--no-rules','--no-title','--no-pty','--no-extensions','--extension',str(Path(self.manifest['app'])/'runtime/extension.js'),'--config',str(config),'--tools','read,grep,context_notes,new_context,context_probe,project_graph,shared_memory','--model',self.model,'--thinking','low','--session-dir',str(self.work/f'sessions-{self.index}')]
        if self.fixture_url:
            env['PI_CODING_AGENT_DIR']=str(self.work/'empty-agent')
            env['OMP_KIT_FIXTURE_URL']=self.fixture_url
            args+=['--extension',str(ROOT/'tests/fixture-provider.js')]
        self.err=open(self.work/f'stderr-{self.index}.log','w',encoding='utf-8')
        self.proc=await asyncio.create_subprocess_exec(*args,stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=self.err,env=env,limit=4*1024*1024)
        async def read():
            async for line in self.proc.stdout:
                try:event=json.loads(line)
                except ValueError:continue
                self.events.append(event);await self.queue.put(event)
            await self.queue.put({'type':'closed'})
        self.reader=asyncio.create_task(read())
        await self.wait(lambda e:e.get('type')=='ready',45)
        state=await self.request('get_state')
        names={t['name'] for t in state['dumpTools']}
        assert {'context_notes','shared_memory','project_graph'}.issubset(names),names
        assert not {'bash','write','task','edit'}.intersection(names),names
    async def wait(self,predicate,timeout=90):
        async def loop():
            while True:
                e=await self.queue.get()
                if e.get('type')=='closed':raise RuntimeError('OMP closed; inspect synthetic stderr log')
                if predicate(e):return e
        return await asyncio.wait_for(loop(),timeout)
    async def request(self,command,**values):
        self.serial+=1;rid=str(self.serial)
        self.proc.stdin.write((json.dumps({'type':command,'id':rid,**values})+'\n').encode());await self.proc.stdin.drain()
        r=await self.wait(lambda e:e.get('type')=='response' and e.get('id')==rid)
        assert r.get('success'),str(r)[:400]
        if command=='prompt' and r.get('data',{}).get('agentInvoked') is not False:
            result=await self.wait(lambda e:e.get('type')=='prompt_result' and e.get('id')==rid,240)
            assert result.get('status')=='completed',str(result)[:500]
            if not result.get('sessionSettled'):await self.wait(lambda e:e.get('type')=='session_settled')
        return r.get('data')
    async def entries(self):
        data=await self.request('get_entries');return data['entries'] if isinstance(data,dict) else data
    async def close(self):
        if hasattr(self,'proc'):
            if self.proc.returncode is None:
                self.proc.stdin.close()
                try:await asyncio.wait_for(self.proc.wait(),15)
                except asyncio.TimeoutError:self.proc.terminate();await self.proc.wait()
            await self.reader;self.err.close()
            (self.work/f'rpc-{self.index}.json').write_text(json.dumps(self.events,ensure_ascii=False),encoding='utf-8')


async def run(prefix,live):
    os.umask(0o077)
    work=Path(tempfile.mkdtemp(prefix='omp-kit-integration-')).resolve()
    manifest=json.loads((prefix/'installation.json').read_text(encoding='utf-8'))
    for file in (ROOT/'runtime').rglob('*'):
        if file.is_file() and '__pycache__' not in file.parts and not file.name.endswith('.local.json'):
            assert file.read_bytes()==(Path(manifest['app'])/file.relative_to(ROOT)).read_bytes(),'Reinstall current runtime before integration testing'
    server=None;url=None;report={'workdir':str(work),'live':bool(live),'success':False}
    if not live:
        Fixture.requests=[]
        server=ThreadingHTTPServer(('127.0.0.1',0),Fixture)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        url=f'http://127.0.0.1:{server.server_port}/v1'
    model=live or 'context-kit-fixture/fixture'
    one=RPC(manifest,work,model,url,1);two=RPC(manifest,work,model,url,2)
    try:
        await one.start()
        await one.request('prompt',message='FIXTURE_SAVE. Synthetic memory test. Bluebird uses PostgreSQL on port 5433. Production deployment is forbidden. Migration is unfinished. Get exact source IDs using context_probe, save these facts in a valid context_notes checkpoint, then answer SAVED. Do not perform project work.')
        first=await one.entries()
        assert any(e.get('customType')=='experimental_context_notes' for e in first),'no checkpoint'
        await one.close()
        await two.start()
        empty=await two.entries()
        assert not any(e.get('type')=='message' for e in empty),'second process is not a new conversation'
        await two.request('prompt',message='FIXTURE_RECALL. Bluebird PostgreSQL production migration: recall our prior choices. Do not change anything. Output only JSON with database, port, production_allowed, migration_done. If unknown, use null; do not guess.')
        second=await two.entries()
        recalled=[e for e in second if e.get('customType')=='omp-context-kit.recall']
        assert recalled,'no automatic cross-session recall card'
        last=next(e['message'] for e in reversed(second) if e.get('message',{}).get('role')=='assistant')
        body=''.join(b.get('text','') for b in last.get('content',[]) if b.get('type')=='text')
        answer=json.loads(body[body.find('{'):body.rfind('}')+1])
        if isinstance(answer.get('database'),str):answer['database']=answer['database'].casefold()
        assert answer=={'database':'postgresql','port':5433,'production_allowed':False,'migration_done':False},answer
        report.update(success=True,answer=answer,recallCards=len(recalled),fixtureRequests=len(Fixture.requests) if not live else None,
                      checks=['real OMP extension loads','checkpoint auto-exported','new independent conversation','automatic sourced memory injection','facts and pending work recalled'])
    finally:
        await one.close();await two.close()
        if server:server.shutdown();server.server_close()
        (work/'report.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
        print(json.dumps(report,indent=2,ensure_ascii=False),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    default=(Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'AppData/Local')))/'OmpContextKit') if os.name=='nt' else Path.home()/'.local/share/omp-context-kit'
    parser.add_argument('--prefix',type=Path,default=default)
    parser.add_argument('--live',metavar='PROVIDER/MODEL',help='Explicit real inference using existing default OMP login; consumes quota')
    args=parser.parse_args();asyncio.run(run(args.prefix,args.live))
