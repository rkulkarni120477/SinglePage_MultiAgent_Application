'use client';

import {useEffect,useState} from 'react';
import {BookOpen,Check,Download,ExternalLink,LoaderCircle} from 'lucide-react';

type Course={id:string;status:string;content:{notice:string;model_id?:string;model_calls:number;input_tokens:number;output_tokens:number;
  lessons:{id:string;title:string;duration_minutes:number}[];
  plan:{title:string;overview:string;assessments:{id:string;title:string;rubric:unknown[]}[];
    alignment:{standard_code:string;standard:{text:string;url:string};objective_ids:string[];lesson_ids:string[];assessment_ids:string[];rationale:string}[]};
  uncovered_standard_codes:string[];
  sources:{manifest:{id:string;title:string;url:string;version:string}[]}}};

async function request(path:string,method='GET',body?:unknown){
  const response=await fetch('/api/v1'+path,{method,...(body?{headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{})});
  if(!response.ok){let detail;try{detail=(await response.json()).detail}catch{}throw new Error(detail||`Request failed (${response.status})`)}
  return response.json();
}

export default function CourseBuilder({runId,runStatus}:{runId:string;runStatus:string}){
  const [course,setCourse]=useState<Course|null>(null),[busy,setBusy]=useState(false),[loading,setLoading]=useState(true),[error,setError]=useState('');
  useEffect(()=>{let live=true;setLoading(true);setCourse(null);setError('');request(`/runs/${runId}/course`).then(value=>{if(live)setCourse(value)}).catch(e=>{if(live)setError(e.message)}).finally(()=>{if(live)setLoading(false)});return()=>{live=false}},[runId]);
  async function act(fn:()=>Promise<void>){setBusy(true);setError('');try{await fn()}catch(e){setError(e instanceof Error?e.message:'Course operation failed')}finally{setBusy(false)}}
  async function build(){await act(async()=>{setCourse(await request(`/runs/${runId}/course`,'POST',{}))})}
  async function review(decision:string){if(!course)return;await act(async()=>{setCourse(await request(`/courses/${course.id}/review`,'POST',{decision}))})}
  async function download(){if(!course)return;await act(async()=>{const response=await fetch(`/api/v1/courses/${course.id}/export`);if(!response.ok){let detail;try{detail=(await response.json()).detail}catch{}throw new Error(detail||'Course download failed')}const url=URL.createObjectURL(await response.blob());const link=document.createElement('a');link.href=url;link.download=`faa-course-${course.id.slice(0,8)}.zip`;link.click();URL.revokeObjectURL(url)})}
  return <section className="course-builder" aria-label="Deliverable FAA course"><div className="section-title"><h3><BookOpen size={18}/> Deliverable course</h3><span className="sample-badge">FAA AVIATION MECHANIC ACS</span></div>
    <p>Build full lessons, written and practical assessments, instructor answers, scoring rubrics, and an explicit alignment matrix from this workflow. Official FAA references are downloaded and cited. Course authoring uses Amazon Nova Pro by default and is billed to your AWS account.</p>
    {error&&<div className="error" role="alert">{error}</div>}
    {runStatus!=='approved'?<p>Approve the workflow artifacts above to generate the course.</p>:<button className="primary" disabled={busy||loading} onClick={build}>{busy?<LoaderCircle className="spin" size={16}/>:<BookOpen size={16}/>} {course?'Generate another FAA course draft':'Generate FAA course'}</button>}
    {busy&&<p role="status">Working on the course. Source download and lesson generation can take several minutes. Keep this page open.</p>}
    {loading&&<p role="status">Checking saved course drafts…</p>}
    {course&&<div className="course-preview"><div className="section-title"><h4>{course.content.plan.title}</h4><span className={'status '+course.status}>{course.status.replaceAll('_',' ')}</span></div><p>{course.content.plan.overview}</p><small>{course.content.lessons.length} lessons · {course.content.lessons.reduce((total,l)=>total+l.duration_minutes,0)} minutes · {course.content.plan.assessments.length} assessments · {course.content.model_calls} additional model calls</small>
      <small>Model: {course.content.model_id || 'See model usage in course JSON'}</small><div className="table-wrap"><table><caption>Lesson sequence</caption><thead><tr><th scope="col">Lesson</th><th scope="col">Duration</th></tr></thead><tbody>{course.content.lessons.map(l=><tr key={l.id}><td>{l.id} · {l.title}</td><td>{l.duration_minutes} minutes</td></tr>)}</tbody></table></div>
      <div className="table-wrap"><table><caption>Proposed alignment matrix</caption><thead><tr><th scope="col">ACS requirement</th><th scope="col">Objectives / lessons / assessments</th><th scope="col">Rationale</th></tr></thead><tbody>{course.content.plan.alignment.map((r,i)=><tr key={i}><td><a href={r.standard.url} target="_blank" rel="noreferrer">{r.standard_code} <ExternalLink size={11}/></a><p>{r.standard.text}</p></td><td>{r.objective_ids.join(', ')}<br/>{r.lesson_ids.join(', ')}<br/>{r.assessment_ids.join(', ')}</td><td>{r.rationale}</td></tr>)}</tbody></table></div>
      {!!course.content.uncovered_standard_codes.length&&<p>Selected elements without a mapping: {course.content.uncovered_standard_codes.join(', ')}</p>}
      <details><summary>Official references</summary>{course.content.sources.manifest.map(s=><p key={s.id}><a href={s.url} target="_blank" rel="noreferrer">{s.title} · {s.version} <ExternalLink size={12}/></a></p>)}</details>
      <p className="artifact-caption">{course.content.notice}</p><a className="secondary course-preview-link" href={`/api/v1/courses/${course.id}/preview`} target="_blank" rel="noreferrer">Review full lessons, answers & rubrics <ExternalLink size={14}/></a>
      {course.status==='awaiting_review'?<><p>Review the full lesson content, rubric criteria and each alignment before approving this new course draft.</p><div className="review-actions"><button className="secondary" disabled={busy} onClick={()=>review('reject')}>Reject course</button><button className="primary" disabled={busy} onClick={()=>review('approve')}><Check size={16}/>Approve course</button></div></>:course.status==='approved'?<div className="review-actions"><button className="primary" disabled={busy} onClick={download}><Download size={16}/>Download course ZIP</button></div>:<p>Course rejected. Generate another draft to revise it.</p>}
      <p className="artifact-caption">The ZIP contains learner and instructor HTML, editable alignment and rubric CSVs, source excerpts and the workflow JSON. It includes instructor answers; distribute learner materials separately.</p>
    </div>}
  </section>;
}
