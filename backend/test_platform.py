import os
import json
import tempfile
import unittest
from unittest.mock import Mock, patch
import httpx
from botocore.exceptions import ClientError

_temporary=tempfile.TemporaryDirectory()
os.environ['DATA_DIR']=_temporary.name
os.environ['MODEL_PROVIDER']='deterministic'
from backend.main import app, graph, records, checkpoint_connection, engine
from backend.catalog import USE_CASES
from backend import models

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

if __name__=='__main__': unittest.main()
