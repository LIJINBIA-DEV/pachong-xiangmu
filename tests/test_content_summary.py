import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.services import content_summary as summary
from api.services.manual_review import update_annotation
from api.routers import data as data_router


@pytest.fixture
def saved_task(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, 'SAVE_DATA_PATH', '')
    monkeypatch.setattr(data_router, 'DATA_DIR', tmp_path)
    monkeypatch.delenv('DEEPSEEK_API_KEY', raising=False)
    folder = tmp_path/'xhs'
    folder.mkdir()
    path = folder/'posts.json'
    notes = [
        {'note_id':'1','source_keyword':'可靠 服务','title':'使用感受','content':'这项服务很可靠。', 'semantic_rule':'evaluation', 'semantic_result':'matched',
         'evaluation_evidence':'这项服务很可靠。','evaluation_target_evidence':'这项服务很可靠。', 'note_url':'https://www.xiaohongshu.com/explore/1?xsec_token=PRIVATE_PLATFORM_TOKEN','nickname':'PRIVATE_NICKNAME'},
        {'note_id':'2','source_keyword':'可靠 服务','content':'这项服务反复出错。','semantic_result':'review'},
        {'note_id':'3','source_keyword':'可靠 服务','content':'已排除的广告','semantic_result':'excluded'},
        {'note_id':'4','source_keyword':'产品讨论','content':'功能与使用体验。','semantic_result':'unfiltered'},
    ]
    path.write_text(json.dumps(notes,ensure_ascii=False))
    return tmp_path,path


def model_response(payload, *, bad_quote=False, bad_ref=False):
    data=json.loads(payload['messages'][1]['content'])
    if 'sources' in data['posts'][0]:
        rows=[]
        for post in data['posts']:
            source=next(s for s in post['sources'] if s['id']=='body')
            rows.append({'ref':post['ref'],'summary':'讨论服务的实际使用感受。','stance':'positive','topics':['使用体验'],
                         'evidence':[{'source':'body','quote':'伪造证据' if bad_quote else source['text'][:100]}]})
        return {'posts':rows}
    return {'overview':'所选帖子主要讨论实际使用感受。','themes':[{'title':'使用体验','summary':'从已采集材料归纳使用感受。','refs':['P999' if bad_ref else data['posts'][0]['ref']]}]}


def mocked_jobs(*, bad_quote=False, bad_ref=False, status=200):
    requests=[]
    def respond(request):
        payload=json.loads(request.content)
        requests.append(payload)
        assert request.url == summary.API_URL
        assert request.headers['Authorization']=='Bearer test-summary-key'
        assert payload['response_format']=={'type':'json_object'}
        assert payload['thinking']=={'type':'disabled'}
        assert all(secret not in request.content.decode() for secret in ('test-summary-key','PRIVATE_PLATFORM_TOKEN','PRIVATE_NICKNAME'))
        if status!=200:
            return httpx.Response(status,json={'error':{'message':'PRIVATE_ERROR_DETAIL'}})
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(model_response(payload,bad_quote=bad_quote,bad_ref=bad_ref),ensure_ascii=False)}}]})
    jobs=summary.SummaryJobs(client_factory=lambda:httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    return jobs,requests


async def complete(jobs,root,path,**options):
    request=summary.SummaryRequest(file=path.relative_to(root).as_posix(),api_key='test-summary-key',**options)
    job=await jobs.start(root,path,request)
    await asyncio.gather(*list(jobs.tasks.values()))
    return job


def test_snapshot_scope_comments_and_limits(saved_task):
    root,path=saved_task
    selected=summary.snapshot(root,path,summary.SummaryOptions())
    assert selected['mode']=='topic'  # Mixed legacy markers do not invent an evaluation rule.
    assert selected['stats']['records']==selected['stats']['eligible']==1
    selected=summary.snapshot(root,path,summary.SummaryOptions(mode='evaluation',scope='available',max_posts=2))
    assert selected['mode']=='evaluation'
    assert selected['stats']['eligible']==3 and selected['stats']['omitted']==1
    assert selected['stats']['review']==1
    assert selected['stats']['comments']==0
    assert {p['post_id'] for p in selected['posts']}=={'1','2'}


@pytest.mark.asyncio
async def test_summary_saved_separately_grounded_and_survives_restart(saved_task):
    root,path=saved_task
    before=hashlib.sha256(path.read_bytes()).hexdigest()
    jobs,requests=mocked_jobs()
    job=await complete(jobs,root,path,mode='evaluation')
    assert job['status']=='ready' and job['processed']==job['total']==1 and len(requests)==2
    assert job['result']['stance_counts']=={'positive':1}
    report=summary.SummaryJobs().info(root,path)
    assert report['report']['id']==job['id'] and not report['stale']
    assert report['report']['result']['posts'][0]['url'].endswith('PRIVATE_PLATFORM_TOKEN')
    markdown=summary.markdown(job)
    assert 'PRIVATE_PLATFORM_TOKEN' in markdown and '打开原帖' in markdown
    assert 'test-summary-key' not in markdown
    assert hashlib.sha256(path.read_bytes()).hexdigest()==before
    for saved in (root/'.content-summaries').rglob('*.json'):
        assert 'test-summary-key' not in saved.read_text() and 'api_key' not in saved.read_text()
    # Review decisions affect later summaries and flag old snapshots without rewriting them.
    update_annotation(root,path,'1:可靠 服务','post','unqualified')
    assert summary.SummaryJobs().info(root,path)['stale']


@pytest.mark.asyncio
@pytest.mark.parametrize(('bad_quote','bad_ref','status','reason'),[
    (True,False,200,'summary_invalid_evidence'),
    (False,True,200,'summary_invalid_references'),
    (False,False,401,'summary_auth_failed'),
    (False,False,429,'summary_quota'),
])
async def test_invalid_model_output_and_errors_are_safe(saved_task,bad_quote,bad_ref,status,reason):
    root,path=saved_task
    jobs,_=mocked_jobs(bad_quote=bad_quote,bad_ref=bad_ref,status=status)
    job=await complete(jobs,root,path,mode='evaluation')
    assert job['status']=='failed' and job['error']==reason and job['result'] is None
    assert 'PRIVATE_ERROR_DETAIL' not in json.dumps(job)


@pytest.mark.asyncio
async def test_all_selected_posts_are_batched_and_not_only_first_page(saved_task):
    root,path=saved_task
    notes=json.loads(path.read_text())
    notes=[{**notes[0],'note_id':str(index),'content':f'第{index}条使用感受。'} for index in range(1,15)]
    path.write_text(json.dumps(notes,ensure_ascii=False))
    jobs,requests=mocked_jobs()
    job=await complete(jobs,root,path,mode='topic')
    assert job['status']=='ready'
    assert job['stats']['records']==14
    assert len(job['result']['posts'])==14 and len(requests)==4
    assert job['result']['stance_counts']=={}
    covered=[post['ref'] for request in requests[:-1] for post in json.loads(request['messages'][1]['content'])['posts']]
    assert len(set(covered))==14


@pytest.mark.asyncio
async def test_failure_does_not_replace_last_successful_report(saved_task):
    root,path=saved_task
    jobs,_=mocked_jobs()
    first=await complete(jobs,root,path)
    jobs,_=mocked_jobs(bad_ref=True)
    failed=await complete(jobs,root,path)
    data=jobs.info(root,path)
    assert data['report']['id']==first['id'] and data['job']['id']==failed['id']


def test_comment_only_evidence_cannot_become_author_positive_stance():
    post={'ref':'P1','sources':[{'id':'body','text':'记录使用过程。'},{'id':'comment:1','text':'真的很好'}]}
    value={'posts':[{'ref':'P1','summary':'使用记录','stance':'positive','topics':['使用'],'evidence':[{'source':'comment:1','quote':'真的很好'}]}]}
    with pytest.raises(ValueError,match='summary_invalid_evidence'):
        summary.parse_posts(value,[post],'evaluation')
    value['posts'][0]['stance']='unclear'
    assert summary.parse_posts(value,[post],'evaluation')[0]['stance']=='unclear'


@pytest.mark.asyncio
async def test_missing_key_and_duplicate_generation_do_not_send_requests(saved_task):
    root,path=saved_task
    jobs,requests=mocked_jobs()
    with pytest.raises(ValueError,match='summary_missing_key'):
        await jobs.start(root,path,summary.SummaryRequest(file='xhs/posts.json'))
    first=await jobs.start(root,path,summary.SummaryRequest(file='xhs/posts.json',api_key='test-summary-key'))
    with pytest.raises(ValueError,match='summary_busy'):
        await jobs.start(root,path,summary.SummaryRequest(file='xhs/posts.json',api_key='test-summary-key'))
    await asyncio.gather(*list(jobs.tasks.values()))
    assert first['status']=='ready' and len(requests)==2


def test_endpoint_validation_never_returns_raw_key_and_blocks_private_files(saved_task,monkeypatch):
    root,path=saved_task
    jobs,_=mocked_jobs()
    monkeypatch.setattr(data_router,'summary_jobs',jobs)
    app=FastAPI(); app.include_router(data_router.router,prefix='/api')
    client=TestClient(app)
    response=client.post('/api/data/content-summary',json={'file':'xhs/posts.json','api_key':['DO_NOT_ECHO_SECRET']})
    assert response.status_code==422 and 'DO_NOT_ECHO_SECRET' not in response.text
    assert client.get('/api/data/content-summary',params={'file':'../secret.json'}).status_code==403
    response=client.post('/api/data/content-summary',json={'file':'xhs/posts.json'})
    assert response.status_code==409 and response.json()['detail']=='summary_missing_key'
    assert client.get('/api/data/content-summary',params={'file':'xhs/posts.json'}).json()['key_configured'] is False
    assert client.get('/api/data/content-summary/'+'f'*32+'/download',params={'file':'xhs/posts.json'}).status_code==404


def test_comments_truncation_is_reported_and_duplicate_rows_are_not_recounted(saved_task,monkeypatch):
    root,path=saved_task
    note=json.loads(path.read_text())[0]
    note['content']='正文'*5000
    comments={'1':[{'content':f'评论{i}'+ '字'*450} for i in range(15)]}
    monkeypatch.setattr(summary,'dataset',lambda *_:([note,deepcopy(note)],comments,None))
    selected=summary.snapshot(root,path,summary.SummaryOptions(include_comments=True))
    assert selected['stats']['records']==selected['stats']['truncated']==1
    assert selected['stats']['comments']==10 and selected['stats']['comments_omitted']==5
    assert len(next(s['text'] for s in selected['posts'][0]['sources'] if s['id']=='body'))==8000


@pytest.mark.asyncio
async def test_http_generation_status_and_download_share_task_access_checks(saved_task,monkeypatch):
    root,path=saved_task
    jobs,requests=mocked_jobs()
    monkeypatch.setattr(data_router,'summary_jobs',jobs)
    from api.services import crawler_manager
    monkeypatch.setattr(crawler_manager,'status','idle')
    app=FastAPI();app.include_router(data_router.router,prefix='/api')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://local') as client:
        response=await client.post('/api/data/content-summary',json={'file':'xhs/posts.json','mode':'evaluation','api_key':'test-summary-key'})
        assert response.status_code==200
        identity=response.json()['id']
        await asyncio.gather(*list(jobs.tasks.values()))
        info=(await client.get('/api/data/content-summary',params={'file':'xhs/posts.json'})).json()
        assert info['report']['status']=='ready' and info['report']['stats']['records']==1
        downloaded=await client.get(f'/api/data/content-summary/{identity}/download',params={'file':'xhs/posts.json'})
        assert downloaded.status_code==200 and '使用感受' in downloaded.text
        assert 'test-summary-key' not in downloaded.text
        assert 'attachment' in downloaded.headers['content-disposition']
        foreign=root/'xhs/other.json';foreign.write_text(path.read_text())
        assert (await client.get(f'/api/data/content-summary/{identity}/download',params={'file':'xhs/other.json'})).status_code==404
