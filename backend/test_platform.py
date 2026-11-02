import os
import json
import tempfile
import unittest
import copy
import io
import zipfile
from unittest.mock import Mock, patch
import httpx
from botocore.exceptions import ClientError

_temporary=tempfile.TemporaryDirectory()
os.environ['DATA_DIR']=_temporary.name
os.environ['MODEL_PROVIDER']='deterministic'
from backend.main import app, graph, records, checkpoint_connection, engine
from backend.catalog import USE_CASES
from backend import models
from backend import courses

def tearDownModule():
    checkpoint_connection.close()
    engine.dispose()
    _temporary.cleanup()

class PlatformTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client=httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test')
    async def asyncTearDown(self): await self.client.aclose()
    async def test_all_use_cases_checkpoint_review_and_export(self):
        for case in USE_CASES:
            with self.subTest(case=case['id']):
                response=await self.client.post('/api/v1/runs',json={'use_case_id':case['id'],'source':case['sample']})
                self.assertEqual(response.status_code,200,response.text)
                run=response.json(); id=run['id']
                self.assertEqual(run['status'],'awaiting_review')
                snapshot=graph.get_state({'configurable':{'thread_id':id}})
                self.assertEqual(snapshot.next,('review',))
                self.assertEqual((await self.client.get(f'/api/v1/runs/{id}/export')).status_code,409)
                approved=await self.client.post(f'/api/v1/runs/{id}/review',json={'decision':'approve'})
                self.assertEqual(approved.json()['status'],'approved')
                self.assertEqual((await self.client.get(f'/api/v1/runs/{id}/export')).status_code,200)
                self.assertEqual((await self.client.post(f'/api/v1/runs/{id}/review',json={'decision':'reject'})).status_code,409)
                self.assertEqual(graph.get_state({'configurable':{'thread_id':id}}).next,())
    async def test_candidate_governance_and_duplicate_guard(self):
        proposal={'source':'lesson','target':'assessment','relationship':'SUPPORTS','evidence':'Pilot manual, page 10: activity supports the assessment.'}
        candidate=(await self.client.post('/api/v1/kg/candidates',json=proposal)).json()
        self.assertEqual(candidate['status'],'PENDING')
        self.assertFalse(any(e['id']=='edge-'+candidate['id'] for e in records('edge')))
        self.assertEqual((await self.client.post('/api/v1/kg/candidates',json=proposal)).status_code,409)
        approved=await self.client.post(f"/api/v1/kg/candidates/{candidate['id']}/review",json={'decision':'approve'})
        self.assertEqual(approved.json()['status'],'APPROVED')
        self.assertTrue(any(e['id']=='edge-'+candidate['id'] for e in records('edge')))
        self.assertEqual((await self.client.post('/api/v1/kg/candidates',json={**proposal,'source':'missing'})).status_code,404)
        self.assertEqual((await self.client.get('/api/v1/kg/nodes/lesson/neighbors?depth=100')).status_code,422)
    async def test_config_is_versioned_and_applied(self):
        text='Electrical safety. '*100
        first=(await self.client.post('/api/v1/runs',json={'use_case_id':'ingest','source':text})).json()
        config=await self.client.post('/api/v1/configurations',json={'max_characters':100,'overlap':10})
        self.assertEqual(config.status_code,200)
        second=(await self.client.post('/api/v1/runs',json={'use_case_id':'ingest','source':text})).json()
        self.assertNotEqual(first['configuration']['version'],second['configuration']['version'])
        self.assertGreater(len(second['outputs']['agents']['intelligence']['chunks']),len(first['outputs']['agents']['intelligence']['chunks']))
        self.assertEqual((await self.client.post('/api/v1/configurations',json={'max_characters':100,'overlap':100})).status_code,422)
    async def test_rejection_and_html_findings(self):
        run=(await self.client.post('/api/v1/runs',json={'use_case_id':'accessibility','source':'<html><img src="x"><input></html>'})).json()
        self.assertEqual(len(run['outputs']['agents']['accessibility']['findings']),3)
        await self.client.post(f"/api/v1/runs/{run['id']}/review",json={'decision':'reject'})
        self.assertEqual((await self.client.get(f"/api/v1/runs/{run['id']}/export")).status_code,409)

    async def test_bedrock_execution_and_approval_do_not_repeat_model_calls(self):
        artifact=dict(summary='Generated draft',recommendations=[dict(title='Safety',detail='Isolate power before inspection.')],
            blueprint=[dict(title='Electrical isolation',activity='Practice safe isolation with an instructor.',assessment='Demonstrate the isolation checklist.')],
            required_skills=['electrical safety'],skill_gaps=[])
        runtime=Mock()
        runtime.converse.return_value=dict(stopReason='tool_use',output={'message':{'content':[
            {'toolUse':{'name':'submit_artifact','input':artifact}}]}},
            usage={'inputTokens':100,'outputTokens':50},ResponseMetadata={'RequestId':'test-bedrock-request'})
        with patch.dict(os.environ,MODEL_PROVIDER='bedrock',AWS_REGION='us-east-1'), patch.object(models,'client',return_value=runtime):
            for case in USE_CASES:
                runtime.reset_mock()
                response=await self.client.post('/api/v1/runs',json={'use_case_id':case['id'],'source':case['sample']})
                self.assertEqual(response.status_code,200,response.text)
                run=response.json()
                expected=len([a for a in case['agents'] if a in models.TASKS and a!='context']) or 1
                self.assertEqual(runtime.converse.call_count,expected)
                self.assertEqual(run['outputs']['model_calls'],expected)
                self.assertEqual(run['outputs']['input_tokens'],100*expected)
                self.assertIsNone(run['outputs']['model_cost'])
                self.assertEqual(run['outputs']['model_usage'][0]['request_id'],'test-bedrock-request')
                if 'content' in case['agents']:
                    self.assertEqual(run['outputs']['agents']['content']['blueprint'],artifact['blueprint'])
                reviewed=await self.client.post(f"/api/v1/runs/{run['id']}/review",json={'decision':'approve'})
                self.assertEqual(reviewed.status_code,200)
                self.assertEqual(reviewed.json()['outputs'],run['outputs'])
                self.assertEqual(runtime.converse.call_count,expected)
                request=runtime.converse.call_args.kwargs
                self.assertEqual(request['toolConfig']['toolChoice'],{'tool':{'name':'submit_artifact'}})
                self.assertEqual(case['sample'],json.loads(request['messages'][0]['content'][0]['text'])['source'])

    async def test_bedrock_failure_never_returns_a_template_success(self):
        case=USE_CASES[0]
        runtime=Mock()
        failures=[ClientError({'Error':{'Code':'AccessDeniedException','Message':'private provider detail'}},'Converse'),
            {'stopReason':'max_tokens','output':{'message':{'content':[]}}},
            {'stopReason':'tool_use','output':{'message':{'content':[{'toolUse':{'name':'submit_artifact','input':{'summary':'Missing fields'}}}]}}}]
        with patch.dict(os.environ,MODEL_PROVIDER='bedrock',AWS_REGION='us-east-1'), patch.object(models,'client',return_value=runtime):
            for failure in failures:
                runtime.converse.side_effect=failure if isinstance(failure,Exception) else None
                runtime.converse.return_value=failure
                count=len(records('run'))
                response=await self.client.post('/api/v1/runs',json={'use_case_id':case['id'],'source':case['sample']})
                self.assertEqual(response.status_code,502,response.text)
                self.assertNotIn('private provider detail',response.text)
                self.assertEqual(len(records('run')),count)

    async def test_course_generation_review_package_and_reference_validation(self):
        objectives=[dict(id=f'O{i}',text=f'Objective {i}: demonstrate safe circuit inspection.') for i in range(1,4)]
        rubric=[dict(criterion='Safety isolation',not_yet='Fails to verify isolation',meets='Verifies isolation correctly',exceeds='Explains the verification',safety_critical=True),
            dict(criterion='Measurement',not_yet='Incorrect tool setup',meets='Correct setup',exceeds='Explains tool limitations',safety_critical=False),
            dict(criterion='Evidence',not_yet='No recorded result',meets='Records accurate result',exceeds='Explains the implication',safety_critical=False)]
        question=dict(question='Explain when continuity can safely be measured.',model_answer='Only on an isolated de-energized circuit after checking the applicable instructions.')
        plan=dict(title='<script>Generated course</script>',audience='New technicians',overview='A course about safe inspection of electrical circuits. '*3,
            prerequisites=['Basic arithmetic'],equipment=['De-energized training rig'],safety_notes=['Qualified instructor required','Follow applicable maintenance instructions'],
            objectives=objectives,lessons=[dict(id=f'L{i}',title=f'Lesson {i}',duration_minutes=60,objective_ids=[f'O{i}']) for i in range(1,4)],
            assessments=[dict(id=f'A{i}',title=f'Assessment {i}',instructions='Demonstrate circuit inspection on a de-energized training rig under instructor supervision. '*2,
                objective_ids=[o['id'] for o in objectives],questions=[question],rubric=rubric,pass_rule='Every criterion must meet level 1, including all safety-critical criteria; remediate before retry.') for i in range(1,3)],
            alignment=[dict(standard_code='AM.I.A.S1',objective_ids=[f'O{i}'],lesson_ids=[f'L{i}'],assessment_ids=['A1','A2'],rationale='Supervised continuity practice and observed assessment provide evidence for this element.') for i in range(1,4)],out_of_scope=['Full A&P certification'])
        sources=dict(manifest=[dict(id='faa-acs',title='FAA ACS',version='2021',url='https://www.faa.gov/example.pdf',sha256='test-hash',downloaded_at='2026-11-02')],
            pages=[dict(id='faa-acs:7',pdf_page=7,printed_page='2',text='Official test source')],
            standards=[dict(code='AM.I.A.S1',text='Perform circuit continuity test.',source_page_id='faa-acs:7',pdf_page=7,url='https://www.faa.gov/example.pdf#page=7')])
        lesson=dict(sections=[dict(heading=f'Section {i}',content=('Explain safe inspection and record the measured result. '*100),source_page_ids=['faa-acs:7']) for i in range(4)],
            worked_example='An instructor provides an isolated training circuit for an inspection. '*7,
            practice_steps=['Check instructions','Verify isolation','Inspect the rig','Record findings'],knowledge_check=[question,question],instructor_notes='An instructor must verify the setup and supervise all practical work. '*3)
        courses.CoursePlan.model_validate(plan);courses.LessonContent.model_validate(lesson);courses.validate_plan(plan,sources)
        invalid=copy.deepcopy(plan);invalid['alignment'][0]['standard_code']='AM.INVENTED.K99'
        with self.assertRaises(ValueError): courses.validate_plan(invalid,sources)
        invalid=copy.deepcopy(plan);invalid['alignment'][0]['lesson_ids']=['MISSING']
        with self.assertRaises(ValueError): courses.validate_plan(invalid,sources)
        case=USE_CASES[0]
        run=(await self.client.post('/api/v1/runs',json={'use_case_id':case['id'],'source':case['sample']})).json()
        self.assertEqual((await self.client.post(f"/api/v1/runs/{run['id']}/course")).status_code,409)
        await self.client.post(f"/api/v1/runs/{run['id']}/review",json={'decision':'approve'})
        usage=dict(input_tokens=100,output_tokens=200,request_id='course-test',agent='test')
        with patch.dict(os.environ,MODEL_PROVIDER='bedrock'),patch.object(courses,'load_sources',return_value=sources),patch.object(models,'client',return_value=Mock()),patch.object(models,'structured',side_effect=[(copy.deepcopy(plan),usage)]+[(lesson,usage)]*3) as generate:
            response=await self.client.post(f"/api/v1/runs/{run['id']}/course")
            self.assertEqual(response.status_code,200,response.text)
            course=response.json();id=course['id']
            self.assertEqual(course['status'],'awaiting_review');self.assertEqual(generate.call_count,4)
            self.assertEqual(course['content']['model_calls'],4)
        self.assertEqual((await self.client.get(f"/api/v1/runs/{run['id']}/course")).json()['id'],id)
        self.assertEqual((await self.client.get(f'/api/v1/courses/{id}/export')).status_code,409)
        preview=await self.client.get(f'/api/v1/courses/{id}/preview')
        self.assertEqual(preview.status_code,200)
        self.assertNotIn('<script>',preview.text);self.assertIn('&lt;script&gt;',preview.text)
        self.assertIn(question['model_answer'],preview.text)
        self.assertEqual((await self.client.post(f'/api/v1/courses/{id}/review',json={'decision':'approve'})).status_code,200)
        self.assertEqual((await self.client.post(f'/api/v1/courses/{id}/review',json={'decision':'reject'})).status_code,409)
        exported=await self.client.get(f'/api/v1/courses/{id}/export')
        self.assertEqual(exported.status_code,200)
        with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
            self.assertIsNone(archive.testzip())
            self.assertIn('alignment-matrix.csv',archive.namelist());self.assertIn('assessment-rubrics.csv',archive.namelist())
            student=archive.read('index.html').decode()
            self.assertNotIn(question['model_answer'],student)
            self.assertIn(question['model_answer'],archive.read('instructor.html').decode())
            self.assertIn('AM.I.A.S1',archive.read('alignment-matrix.csv').decode())
            self.assertEqual(json.loads(archive.read('workflow.json'))['id'],run['id'])

    async def test_structured_repair_is_bounded_and_counts_both_requests(self):
        runtime=Mock()
        def response(value,request_id):
            return dict(stopReason='tool_use',output={'message':{'content':[{'toolUse':{'name':'submit_artifact','input':value}}]}},
                usage={'inputTokens':100,'outputTokens':50},ResponseMetadata={'RequestId':request_id})
        complete=dict(summary='Valid generated draft',recommendations=[],blueprint=[],required_skills=[],skill_gaps=[])
        runtime.converse.side_effect=[response({'summary':'Incomplete'},'invalid-1'),response(complete,'valid-2')]
        with patch.dict(os.environ,MODEL_PROVIDER='bedrock',AWS_REGION='us-east-1'):
            artifact,usage=models.structured(runtime,'course-test','Generate an artifact',{'brief':'Test'},models.Artifact,repair_attempts=1)
            self.assertEqual(artifact,complete)
            self.assertEqual(usage['attempts'],2);self.assertEqual(usage['input_tokens'],200);self.assertEqual(usage['output_tokens'],100)
            self.assertEqual([r['status'] for r in usage['requests']],['invalid_output','completed'])
            self.assertNotIn('$ref',json.dumps(runtime.converse.call_args.kwargs['toolConfig']))
            runtime.reset_mock();runtime.converse.side_effect=[response({'summary':'Incomplete'},'invalid-3')]*2
            from fastapi import HTTPException
            with self.assertRaises(HTTPException):
                models.structured(runtime,'course-test','Generate an artifact',{},models.Artifact,repair_attempts=1)
            self.assertEqual(runtime.converse.call_count,2)

if __name__=='__main__': unittest.main()
