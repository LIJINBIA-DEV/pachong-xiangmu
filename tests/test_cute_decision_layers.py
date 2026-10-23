"""Image matching and post eligibility must remain separate, without bypassing pet rules."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from compare_cute_models import decision


def sample(ownership='不确定', relation='明确相关', match='包含', image_type='实景照片'):
    # Captured Qwen3.6 rescue-kitten case, post 5351423082236349 / 002.jpg.
    text = {'status': '明确', 'targets': [{'id': 't1', 'name': '猫', 'kind': '真实动物',
            'ownership': ownership, 'place_relation': relation, 'usable_for_matching': True}]}
    visual = {'label': '二者都不是', 'reason': '图片主体是一只小猫，属于动物',
              'image_type': image_type, 'type_reason': '图片实际类型',
              'target_matches': [{'id': 't1', 'status': match, 'visible_evidence': '可见小猫'}]}
    return text, visual


def test_rescued_cat_image_passes_while_post_ownership_stays_pending():
    result = decision(*sample())
    assert result['image_outcome'] == '不排除'
    assert result['post_outcome'] == '待核对'
    assert '宠物' in result['post_decision_reason']
    assert result['outcome'] == '待核对'  # The overall gate remains intact.


@pytest.mark.parametrize('owner', ['明确本人宠物', '明确他人宠物'])
def test_visible_pet_does_not_bypass_post_exclusion(owner):
    result = decision(*sample(ownership=owner))
    assert result['image_outcome'] == '不排除'
    assert result['post_outcome'] == '排除'
    assert result['outcome'] == '排除'


def test_confirmed_nonpet_matches_all_layers():
    result = decision(*sample(ownership='未见宠物证据'))
    assert result['image_outcome'] == result['post_outcome'] == result['outcome'] == '不排除'


@pytest.mark.parametrize('extra', [{'match': '不包含'}, {'image_type': '宣传海报'}])
def test_visual_rejection_is_preserved(extra):
    result = decision(*sample(ownership='未见宠物证据', **extra))
    assert result['image_outcome'] == result['outcome'] == '排除'
    assert result['post_outcome'] == '不排除'


def test_unverified_text_cannot_become_an_image_pass():
    text, visual = sample()
    text.update(status='不确定')
    assert decision(text, visual)['image_outcome'] == '待核对'


def test_place_relation_uncertainty_belongs_to_post():
    result = decision(*sample(ownership='未见宠物证据', relation='不确定'))
    assert result['image_outcome'] == '不排除'
    assert result['post_outcome'] == result['outcome'] == '待核对'
