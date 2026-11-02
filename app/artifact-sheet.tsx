import type {ReactNode} from 'react';

type Evidence = {source?:string;location?:string};
type Relationship = {source:string;target:string;relationship:string;evidence?:Evidence};
export type WorkflowOutputs = {
  mode?:string; model_calls?:number; model_cost?:number|null;
  input_tokens?:number;output_tokens?:number;
  generated?:Record<string,{summary:string;recommendations:{title:string;detail:string}[]}>;
  model_usage?:{agent:string;model_id:string;input_tokens:number;output_tokens:number;request_id?:string}[];
  agents?: {
    content?: {status:string;brief:string;blueprint:{title:string;activity:string;assessment:string}[]};
    workforce?: {method:string;required:string[];gaps:string[];current_skills_provided:boolean};
    standards?: {status:string;framework_version:string;warning:string;approved_context:Relationship[]};
    accessibility?: {scope:string;findings:{line:number;column:number;rule:string;message:string}[];manual_checks:string[]};
    intelligence?: {source_hash:string;configuration_version:string;chunks:{index:number;text:string;start:number;end:number}[]};
  };
  context?: {method:string;nodes:{id:string;label:string;node_type:string}[];edges:Relationship[]};
};

function SheetTable({title,columns,rows,empty}:{title:string;columns:string[];rows:ReactNode[][];empty:string}) {
  return <section className="artifact-section"><h4>{title}</h4>{rows.length ? <div className="table-wrap" tabIndex={0} role="region" aria-label={title}><table><caption className="sr-only">{title}</caption><thead><tr>{columns.map(c=><th scope="col" key={c}>{c}</th>)}</tr></thead><tbody>{rows.map((row,i)=><tr key={i}>{row.map((cell,j)=><td key={j}>{cell}</td>)}</tr>)}</tbody></table></div> : <p className="artifact-empty">{empty}</p>}</section>;
}

export default function ArtifactSheet({outputs,status}:{outputs:WorkflowOutputs;status:string}) {
  const {content,workforce,standards,accessibility,intelligence}=outputs.agents || {};
  const context=outputs.context;
  const labels=new Map(context?.nodes.map(n=>[n.id,n.label]) || []);
  const relationships=(edges:Relationship[])=>edges.map(e=>[labels.get(e.source)||e.source,e.relationship.replaceAll('_',' '),labels.get(e.target)||e.target,[e.evidence?.source,e.evidence?.location].filter(Boolean).join(' · ')||'No evidence supplied']);
  return <div className="artifact-sheet">
    <div className="execution-note"><strong>Processing completed · {outputs.model_calls ?? 0} model calls</strong><p>{status==='awaiting_review' ? 'The workflow has produced these drafts. Approval completes the saved workflow and unlocks export; it does not run additional processing.' : status==='approved' ? 'Review approved. The saved workflow is complete and these artifacts are ready to export.' : 'Review rejected. These drafts remain available for inspection. Start a new run to revise them.'}</p><small>{outputs.mode || 'Local reference workflow'} · {outputs.model_cost===null?'Model cost unavailable — see AWS billing':`Model cost $${(outputs.model_cost ?? 0).toFixed(2)}`}{!!outputs.model_calls&&` · ${(outputs.input_tokens ?? 0).toLocaleString()} input / ${(outputs.output_tokens ?? 0).toLocaleString()} output tokens`}</small></div>
    {Object.entries(outputs.generated || {}).map(([agent,artifact])=><section className="artifact-section" key={agent}><h4>{({content:'Content design',workforce:'Workforce skills',standards:'Standards review',accessibility:'Accessibility review',intelligence:'Knowledge extraction',context:'Knowledge answer'} as Record<string,string>)[agent] || agent} · Model draft</h4><p>{artifact.summary}</p><SheetTable title="Recommendations" columns={['Item','Detail / evidence']} rows={artifact.recommendations.map(r=>[r.title,r.detail])} empty="No additional recommendations."/></section>)}
    {!!outputs.model_usage?.length&&<details className="artifact-provenance"><summary>Model execution details</summary><SheetTable title="Completed model calls" columns={['Agent / model','Input / output tokens','AWS request ID']} rows={outputs.model_usage.map(c=>[`${c.agent} · ${c.model_id}`,`${c.input_tokens} / ${c.output_tokens}`,c.request_id || 'Unavailable'])} empty="No completed calls."/></details>}
    {content&&<><div className="artifact-section"><h4>Course brief</h4><p className="source-text">{content.brief}</p><p>{content.status}</p></div><SheetTable title="Course blueprint" columns={['Lesson','Learning activity','Assessment']} rows={content.blueprint.map((b,i)=>[<><span className="lesson-number">{i+1}</span>{b.title}</>,b.activity,b.assessment])} empty="No course blueprint was produced."/></>}
    {workforce&&<><SheetTable title="Skills review" columns={['Required skill','Comparison result']} rows={workforce.required.map(skill=>[skill,!workforce.current_skills_provided?'Current skills not supplied':workforce.gaps.includes(skill)?'Gap — not listed in current skills':'Listed in current skills'])} empty="No skills matched the controlled sample vocabulary. A reviewer must identify requirements."/><p className="artifact-caption">{workforce.method}. {workforce.current_skills_provided?'Comparison uses declared skills only.':'Supply “Current skills:” in the brief to compare skills.'}</p></>}
    {standards&&<><div className="artifact-section"><h4>Standards review</h4><p><strong>{standards.framework_version}</strong> · {standards.status}</p><p>{standards.warning}</p></div><SheetTable title="Retrieved standards context" columns={['From','Relationship','To','Evidence']} rows={relationships(standards.approved_context)} empty="No approved relationships were retrieved. A standards reviewer must supply mapping evidence."/><p className="artifact-caption">These are existing graph relationships, not newly validated mappings for this brief.</p></>}
    {accessibility&&<><SheetTable title="Accessibility findings" columns={['Source location','Check','Recommended action']} rows={accessibility.findings.map(f=>[`Line ${f.line}, column ${f.column}`,f.rule.replaceAll('-',' '),f.message])} empty="No issues detected by the basic source checks. Manual accessibility review is still required."/><p className="artifact-caption">Scope: {accessibility.scope}. Plain-text briefs do not exercise HTML accessibility checks.</p><SheetTable title="Manual accessibility checklist" columns={['Review item','Status']} rows={accessibility.manual_checks.map(check=>[check,'Manual review required'])} empty="No manual checks were supplied."/></>}
    {intelligence&&<><SheetTable title="Source chunks" columns={['Chunk','Character range','Source text']} rows={intelligence.chunks.map(c=>[c.index+1,`${c.start}–${c.end} (end exclusive)`,<span className="source-text">{c.text}</span>])} empty="No source chunks were produced."/><details className="artifact-provenance"><summary>Source provenance</summary><dl><dt>Configuration version</dt><dd>{intelligence.configuration_version}</dd><dt>Source SHA-256</dt><dd className="mono">{intelligence.source_hash}</dd></dl></details></>}
    {context&&<><SheetTable title="Retrieved knowledge" columns={['Entity','Type']} rows={context.nodes.map(n=>[n.label,n.node_type])} empty="No approved knowledge matched this brief."/><SheetTable title="Knowledge evidence" columns={['From','Relationship','To','Evidence']} rows={relationships(context.edges)} empty="No supporting relationships were retrieved."/><p className="artifact-caption">{context.method}</p></>}
    <details className="artifact-provenance"><summary>View technical JSON</summary><pre>{JSON.stringify(outputs,null,2)}</pre></details>
  </div>;
}
