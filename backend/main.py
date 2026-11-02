"""Local, single-organization reference implementation. No model credentials required."""
import hashlib
import json
import os
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import TypedDict

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import Column, String, Text, create_engine, event, select
from sqlalchemy.orm import Session, declarative_base
from langchain_core.runnables import RunnableLambda
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command
from langgraph.checkpoint.sqlite import SqliteSaver
from .catalog import AGENTS, USE_CASES
from . import projections
from . import models

load_dotenv(Path(__file__).resolve().parent / '.env', override=False)

DATA = Path(os.getenv('DATA_DIR', str(Path(__file__).resolve().parents[1] / 'data')))
DATA.mkdir(parents=True, exist_ok=True)
engine = create_engine(f'sqlite:///{DATA / "platform.db"}', connect_args={'check_same_thread': False})
@event.listens_for(engine, 'connect')
def sqlite_config(connection, _):
    connection.execute('PRAGMA journal_mode=WAL')
    connection.execute('PRAGMA busy_timeout=5000')
Base = declarative_base()
class Record(Base):
    __tablename__ = 'records'
    id = Column(String, primary_key=True)
    kind = Column(String, index=True, nullable=False)
    payload = Column(Text, nullable=False)
Base.metadata.create_all(engine)
lock = threading.RLock()
def now(): return datetime.now(timezone.utc).isoformat()
def save(kind, value):
    with Session(engine) as db:
        db.merge(Record(id=value['id'], kind=kind, payload=json.dumps(value)))
        db.commit()
    return value
def get(id, kind=None):
    with Session(engine) as db:
        row = db.get(Record, id)
        if not row or (kind and row.kind != kind): raise HTTPException(404, 'Record not found')
        return json.loads(row.payload)
def records(kind):
    with Session(engine) as db:
        return [json.loads(r.payload) for r in db.scalars(select(Record).where(Record.kind == kind))]
def audit(action, target): save('audit', dict(id=str(uuid.uuid4()), action=action, target=target, at=now(), actor='local-reviewer'))
def current_config(): return sorted(records('configuration'),key=lambda c:c.get('created_at',''))[-1]

CONFIG = dict(id='config-1', version='1.0', chunking={'max_characters':800,'overlap':80}, hierarchy=['Program','Block','Chapter','DLU','Content Object'], tagging='controlled-vocabulary', mandatory_review=True, retrieval_depth=2, result_limit=30)
if not records('configuration'):
    save('configuration', CONFIG)
    for id, type, label in [('program','Program','Aviation maintenance'),('block','Block','Aircraft electrical systems'),('chapter','Chapter','Electrical fundamentals'),('dlu','DLU','Safe inspection'),('lesson','Content Object','Electrical safety introduction'),('skill','Skill','Electrical safety'),('assessment','Assessment','Safety inspection practical'),('standard','Standard','Sample safety standard v1')]:
        save('node', dict(id=id,node_type=type,label=label,status='APPROVED',scope='LOCAL',sample=True,schema_version='1.0'))
    for i,(s,t,r) in enumerate([('program','block','CONTAINS'),('block','chapter','CONTAINS'),('chapter','dlu','CONTAINS'),('dlu','lesson','CONTAINS'),('lesson','skill','TEACHES'),('assessment','skill','ASSESSES'),('lesson','standard','ALIGNS_TO')]):
        save('edge',dict(id=f'seed-{i}',source=s,target=t,relationship=r,status='APPROVED',evidence={'source':'Illustrative pilot dataset','location':'Seed fixture','method':'sample','reviewer':'seed'},sample=True))

class AuditHTML(HTMLParser):
    def __init__(self): super().__init__(convert_charrefs=True); self.findings=[]
    def handle_starttag(self, tag, attrs):
        a=dict(attrs); line,col=self.getpos()
        if tag=='img' and 'alt' not in a: self.findings.append(dict(line=line,column=col,rule='image-alt',message='Image has no alt attribute. Provide meaningful alt text, or empty alt for a decorative image.'))
        if tag=='html' and not a.get('lang'): self.findings.append(dict(line=line,column=col,rule='document-language',message='Declare the document language.'))
        if tag=='input' and a.get('type') not in ('hidden','submit','button') and not (a.get('id') or a.get('aria-label') or a.get('aria-labelledby')): self.findings.append(dict(line=line,column=col,rule='input-label',message='Provide and verify an associated accessible label.'))

def retrieve(query):
    nodes=records('node'); tokens=set(re.findall(r'\w+',query.lower()))
    scored=sorted(nodes,key=lambda n:len(tokens & set(re.findall(r'\w+',n['label'].lower()))),reverse=True)
    hits=[n for n in scored if tokens & set(re.findall(r'\w+',n['label'].lower()))][:6]
    ids={n['id'] for n in hits}
    edges=[e for e in records('edge') if e['status']=='APPROVED' and (e['source'] in ids or e['target'] in ids)][:12]
    return dict(nodes=hits,edges=edges,method='Approved graph lexical retrieval',citations=[e['evidence'] for e in edges])
retriever=RunnableLambda(retrieve)

class State(TypedDict, total=False):
    source: str
    case_id: str
    context: dict
    outputs: dict
    decision: str
    configuration: dict
def context_step(state): return {'context':retriever.invoke(state['source'])}
def execute(state):
    case=next(c for c in USE_CASES if c['id']==state['case_id']); text=state['source']; results={}
    for id in case['agents']:
        if id=='intelligence':
            config=state['configuration']; size=config['chunking']['max_characters']; overlap=config['chunking']['overlap']
            chunks=[dict(index=i,text=text[start:start+size],start=start,end=min(start+size,len(text))) for i,start in enumerate(range(0,len(text),size-overlap))]
            results[id]=dict(source_hash=hashlib.sha256(text.encode()).hexdigest(),chunks=chunks,configuration_version=config['version'])
        elif id=='content': results[id]=dict(status='Template draft — author review required',brief=text,blueprint=[dict(title='Understand the foundations',activity='Read the source and identify key concepts',assessment='Explain the core concepts in your own words'),dict(title='Apply the procedure',activity='Practice the task described in the brief under supervision',assessment='Demonstrate the procedure using a reviewer-defined checklist'),dict(title='Reflect and validate',activity='Compare the practical result with approved source requirements',assessment='Document findings and receive instructor feedback')],context_ids=[n['id'] for n in state['context']['nodes']])
        elif id=='workforce':
            parts=re.split(r'current skills:',text,flags=re.I); required=re.findall(r'electrical safety|circuit inspection|fault diagnosis',parts[0],re.I); current=parts[1].lower() if len(parts)>1 else ''
            results[id]=dict(method='Controlled sample skill vocabulary; no inferred equivalence',required=sorted(set(s.lower() for s in required)),gaps=sorted(set(s.lower() for s in required if s.lower() not in current)),current_skills_provided=len(parts)>1,review_required=True)
        elif id=='standards': results[id]=dict(status='Reviewer mapping required',framework_version='Sample safety standard v1',approved_context=state['context']['edges'],warning='No new alignment or crosswalk is established automatically.')
        elif id=='accessibility':
            parser=AuditHTML(); parser.feed(text)
            results[id]=dict(findings=parser.findings,scope='Basic source HTML checks only',manual_checks=['Keyboard navigation and focus order','Screen reader reading order','Color contrast and visual meaning','Instructional and alternative-text quality'])
    config=models.settings()
    calls=[]
    generated={}
    if config['provider']=='bedrock':
        runtime=models.client()
        specialists=[id for id in case['agents'] if id in models.TASKS and id!='context'] or ['context']
        for id in specialists:
            artifact,usage=models.generate(runtime,id,case,text,state['context'],generated)
            generated[id]=artifact
            calls.append(usage)
            if id=='content':
                results[id].update(status='Bedrock-generated draft — author review required',blueprint=artifact['blueprint'])
            elif id=='workforce':
                results[id].update(method='Bedrock skill analysis — reviewer validation required',required=artifact['required_skills'],gaps=artifact['skill_gaps'])
    return {'outputs':dict(agents=results,context=state['context'],generated=generated,
        mode='Amazon Bedrock specialist workflow' if calls else 'Deterministic local reference workflow',
        model_calls=len(calls),model_cost=None if calls else 0,model_usage=calls,
        input_tokens=sum(c['input_tokens'] for c in calls),output_tokens=sum(c['output_tokens'] for c in calls))}
def review_step(state): return {'decision':interrupt({'message':'Review draft artifacts before export','outputs':state['outputs']})}
builder=StateGraph(State)
builder.add_node('retrieve',context_step); builder.add_node('execute',execute); builder.add_node('review',review_step)
builder.add_edge(START,'retrieve'); builder.add_edge('retrieve','execute'); builder.add_edge('execute','review'); builder.add_edge('review',END)
checkpoint_connection=sqlite3.connect(str(DATA/'checkpoints.db'),check_same_thread=False)
graph=builder.compile(checkpointer=SqliteSaver(checkpoint_connection))

app=FastAPI(title='Academian Multi-Agent Platform',version='0.1.0',description='Local single-organization workbench. APIs are unauthenticated; bind to loopback only.')
class RunInput(BaseModel):
    use_case_id: str
    source: str = Field(min_length=10,max_length=50000)
class Decision(BaseModel):
    decision: str
class CandidateInput(BaseModel):
    source: str
    target: str
    relationship: str
    evidence: str = Field(min_length=5,max_length=2000)
class ConfigurationInput(BaseModel):
    max_characters: int = Field(ge=100,le=4000)
    overlap: int = Field(ge=0,le=500)
RELATIONS={'CONTAINS','PART_OF','COVERS','TEACHES','SUPPORTS','ALIGNS_TO','MAPS_TO','ASSESSES','MEASURES','REQUIRES','REFERENCES','DERIVED_FROM','REUSES','VERSION_OF','SUCCEEDS','PUBLISHED_IN','MEMBER_OF','RELATED_TO','CROSSWALKS_TO','EQUIVALENT_TO'}
@app.get('/api/v1/health')
def health(): return dict(status='ok',mode='local-development',authentication=False,model=models.settings()['provider'],model_configuration=models.settings(),database='SQLite WAL',optional_services={'ChromaDB':'not configured','OpenSearch':'not configured','Redis/Celery':'not configured','Entra ID':'not configured'})
@app.get('/api/v1/catalog')
def catalog(): return dict(agents=AGENTS,use_cases=USE_CASES)
@app.get('/api/v1/configurations')
def configurations(): return records('configuration')
@app.post('/api/v1/configurations')
def create_configuration(body:ConfigurationInput):
    if body.overlap>=body.max_characters: raise HTTPException(422,'Overlap must be smaller than chunk size')
    with lock:
        config={**CONFIG,'id':str(uuid.uuid4()),'version':str(len(records('configuration'))+1)+'.0','created_at':now(),'chunking':body.model_dump()}
        audit('configuration.created',config['id']); return save('configuration',config)
@app.get('/api/v1/runs')
def runs(): return sorted(records('run'),key=lambda r:r['created_at'],reverse=True)
@app.post('/api/v1/runs')
def start_run(body:RunInput):
    if body.use_case_id not in {c['id'] for c in USE_CASES}: raise HTTPException(422,'Unknown use case')
    with lock:
        id=str(uuid.uuid4()); config={'configurable':{'thread_id':id}}
        applied=current_config()
        result=graph.invoke({'source':body.source,'case_id':body.use_case_id,'configuration':applied},config)
        run=save('run',dict(id=id,use_case_id=body.use_case_id,created_at=now(),status='awaiting_review',outputs=result['outputs'],configuration=applied,source_hash=hashlib.sha256(body.source.encode()).hexdigest()))
        audit('run.created',id)
        return run
@app.get('/api/v1/runs/{id}')
def run(id:str): return get(id,'run')
@app.post('/api/v1/runs/{id}/review')
def review_run(id:str,body:Decision):
    if body.decision not in ('approve','reject'): raise HTTPException(422,'Expected approve or reject')
    with lock:
        run=get(id,'run')
        if run['status']!='awaiting_review': raise HTTPException(409,'Run already reviewed')
        graph.invoke(Command(resume=body.decision),{'configurable':{'thread_id':id}})
        run.update(status='approved' if body.decision=='approve' else 'rejected',reviewed_at=now(),reviewer='local-reviewer')
        audit(f'run.{body.decision}',id)
        return save('run',run)
@app.get('/api/v1/runs/{id}/export')
def export_run(id:str):
    run=get(id,'run')
    if run['status']!='approved': raise HTTPException(409,'Approve the run before exporting')
    return run
@app.get('/api/v1/runs/{id}/events')
def events(id:str):
    value=get(id,'run')
    return StreamingResponse(iter([f'event: snapshot\ndata: {json.dumps(value)}\n\n']),media_type='text/event-stream')
@app.get('/api/v1/kg')
def kg(): return dict(nodes=records('node'),edges=records('edge'),candidates=records('candidate'))
@app.get('/api/v1/kg/search')
def search(q:str=''): return retriever.invoke(q[:2000])
@app.post('/api/v1/projections/rebuild')
def rebuild_projection():
    try: return projections.rebuild(records('node'))
    except Exception as exc: raise HTTPException(503,'Chroma projection unavailable; verify CHROMA_HOST and service health') from exc
@app.get('/api/v1/projections/search')
def search_projection(q:str):
    try: return projections.search(q[:2000])
    except Exception as exc: raise HTTPException(503,'Chroma projection unavailable; configure and rebuild the index first') from exc
@app.get('/api/v1/kg/nodes/{id}/neighbors')
def neighbors(id:str,depth:int=2,limit:int=30):
    get(id,'node')
    if not 1<=depth<=3 or not 1<=limit<=100: raise HTTPException(422,'Depth 1–3 and limit 1–100 required')
    seen={id}; selected=[]; edges=records('edge')
    for _ in range(depth):
        frontier=set()
        for e in edges:
            if e['status']=='APPROVED' and (e['source'] in seen or e['target'] in seen) and e not in selected:
                selected.append(e); frontier.update([e['source'],e['target']])
                if len(selected)>=limit: break
        seen.update(frontier)
        if len(selected)>=limit: break
    return dict(nodes=[n for n in records('node') if n['id'] in seen],edges=selected)
@app.post('/api/v1/kg/candidates')
def propose(body:CandidateInput):
    get(body.source,'node'); get(body.target,'node')
    if body.relationship not in RELATIONS: raise HTTPException(422,'Unknown relationship type')
    with lock:
        if any(e['source']==body.source and e['target']==body.target and e['relationship']==body.relationship and e['status'] not in ('REJECTED',) for e in records('edge')+records('candidate')): raise HTTPException(409,'This relationship already exists or is pending')
        candidate=save('candidate',dict(id=str(uuid.uuid4()),source=body.source,target=body.target,relationship=body.relationship,status='PENDING',evidence={'source':'Reviewer supplied evidence','location':body.evidence,'method':'manual-proposal','configuration_version':'1.0'},created_at=now()))
        audit('candidate.created',candidate['id']); return candidate
@app.post('/api/v1/kg/candidates/{id}/review')
def review_candidate(id:str,body:Decision):
    if body.decision not in ('approve','reject'): raise HTTPException(422,'Expected approve or reject')
    with lock:
        candidate=get(id,'candidate')
        if candidate['status']!='PENDING': raise HTTPException(409,'Candidate already reviewed')
        candidate.update(status='APPROVED' if body.decision=='approve' else 'REJECTED',reviewer='local-reviewer',reviewed_at=now())
        if body.decision=='approve':
            candidate['evidence']['reviewer']='local-reviewer'
            save('edge',{**candidate,'id':'edge-'+id})
        save('candidate',candidate); audit('candidate.'+body.decision,id); return candidate
