"""Remote preview and account information must not manufacture rejection labels."""
import hashlib
import json
from pathlib import Path

from PIL import Image
import pytest

from api.services.manual_review import annotations, review_images, storage_path, update_annotation, write_state


@pytest.fixture
def online(tmp_path):
    path=tmp_path/'xhs/posts.json';path.parent.mkdir()
    note={'note_id':'1','source_keyword':'服务 体验','content':'服务体验记录','semantic_result':'unfiltered',
          'image_names':'cover.jpg,detail.jpg','image_list':['https://cdn.example.com/cover.webp','https://cdn.example.com/detail.webp']}
    path.write_text(json.dumps([note]))
    return tmp_path,path,note


def test_saved_urls_are_previewable_without_local_downloads(online):
    root,path,note=online
    images=review_images(root,path,note)
    assert [i['key'] for i in images]==['cover.jpg','detail.jpg']
    assert all(not i['local'] and i['url']==i['remote_url'] for i in images)
    entry=annotations(root,path)['entries']['1:服务 体验']
    assert entry['images']=={} and entry['decision'] is None
    assert entry['decision_reason']=='text_review_pending'
    before=hashlib.sha256(path.read_bytes()).hexdigest()
    result=update_annotation(root,path,'1:服务 体验','image','qualified','cover.jpg')
    assert result['entries']['1:服务 体验']['decision'] is None  # Image marks cannot approve a post.
    assert hashlib.sha256(path.read_bytes()).hexdigest()==before


def test_local_preview_keeps_online_fallback_and_stable_manual_keys(online):
    root,path,note=online
    folder=root/'xhs/media/1';folder.mkdir(parents=True)
    Image.new('RGB',(20,20)).save(folder/'cover.jpg')
    images=review_images(root,path,note)
    assert images[0]['local'] and images[0]['url'].startswith('/api/data/media/')
    assert images[0]['remote_url']=='https://cdn.example.com/cover.webp'
    assert not images[1]['local'] and images[1]['key']=='detail.jpg'
    update_annotation(root,path,'1:服务 体验','image','unqualified','detail.jpg')
    (folder/'cover.jpg').write_bytes(b'broken-image')
    entry=annotations(root,path)['entries']['1:服务 体验']
    assert entry['review_images'][0]['download_problem'] is None  # Image contents are not inspected.
    assert entry['review_images'][0]['remote_url'].endswith('cover.webp')
    assert entry['images']=={'detail.jpg':'unqualified'}


def test_legacy_download_negatives_are_ignored_without_erasing_history(online):
    root,path,_=online
    state={'version':1,'posts':{'1:服务 体验':{'images':{'cover.jpg':'unqualified','detail.jpg':'qualified'},
            'image_sources':{'cover.jpg':'download','detail.jpg':'manual'}}},'accounts':{}}
    write_state(root,path,state)
    before=storage_path(root,path).read_bytes()
    entry=annotations(root,path)['entries']['1:服务 体验']
    assert entry['images']=={'detail.jpg':'qualified'}
    assert entry['review_images'][0]['decision_source'] is None
    assert entry['decision'] is None
    assert storage_path(root,path).read_bytes()==before
