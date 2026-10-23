"""Regression at the text-to-vision boundary, using captured trial responses."""
import copy
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import compare_cute_models as compare


def captured(model, note):
    fixture = Path(__file__).parent / 'fixtures/cute_text_evidence.json'
    record = json.loads(fixture.read_text(encoding='utf-8'))[model + '/' + note]
    return record['parsed'], record['content']


def test_captured_cat_ellipsis_survives_into_visual_input():
    raw, content = captured('q36', '5351650459913190')
    original = copy.deepcopy(raw)
    value = compare.validate_text(raw, content)
    assert value['status'] == '明确'
    assert value['targets'][0]['kind'] == '动物造型实体'
    assert value['targets'][0]['citation']['status'] == 'repaired'
    assert value['targets'][0]['evidence'] in content
    assert compare.vision_targets(value) == [{'id': 't1', 'name': '猫咪', 'kind': '动物造型实体'}]
    assert raw == original


def test_captured_spacing_can_map_back_to_exact_source():
    raw, content = captured('q35', '5350259213735383')
    value = compare.validate_text(raw, content)
    assert value['status'] == '明确'
    assert value['targets'][0]['evidence'] in content
    assert value['targets'][0]['citation']['method'] == 'whitespace'


def target(evidence):
    return {'status': '明确', 'targets': [{'name': '猫', 'kind': '真实动物', 'evidence': evidence,
            'ownership': '未见宠物证据', 'place_relation': '明确相关'}], 'reason': '模型判断'}


def test_unverified_target_is_visible_but_not_used_to_release_images():
    value = compare.validate_text(target('小猫非常可爱'), '公园的猫很可爱')
    assert value['targets'][0]['name'] == '猫'
    assert value['targets'][0]['citation']['status'] == 'unverified'
    assert value['semantic_status'] == '明确'
    assert value['status'] == '不确定'
    assert compare.vision_targets(value) == []
    result = compare.decision(value, {'label': '二者都不是', 'reason': '猫', 'image_type': '实景照片',
                                      'type_reason': '照片', 'target_matches': []})
    assert result['outcome'] == '待核对'


def test_ellipsis_cannot_reorder_invent_or_pick_ambiguous_fragments():
    for quote, body in [('可爱...猫', '猫真可爱'), ('猫...可爱...花坛', '猫可爱'),
                        ('猫...可爱', '猫可爱。猫可爱'), ('猫...可爱', '猫不可爱')]:
        value = compare.validate_text(target(quote), body)
        assert value['targets'][0]['citation']['status'] == 'unverified'
        assert compare.vision_targets(value) == []


def test_long_fragments_still_require_order_uniqueness_and_no_hidden_negation():
    for quote, body in [('非常可爱...公园猫咪', '公园猫咪非常可爱'),
                        ('公园猫咪...非常可爱', '公园猫咪不是非常可爱'),
                        ('公园猫咪...非常可爱', '公园猫咪非常可爱，公园猫咪非常可爱'),
                        ('公园猫咪...非常可爱', '公园猫咪非常漂亮')]:
        assert compare.validate_text(target(quote), body)['status'] == '不确定'
    assert compare.validate_text(target('a a a a'), 'aaaaa')['status'] == '不确定'


def test_source_verification_does_not_rewrite_semantic_errors():
    raw, content = captured('q36', '5351650459913190')
    raw['targets'][0]['ownership'] = '明确本人宠物'
    value = compare.validate_text(raw, content)
    assert value['targets'][0]['ownership'] == '明确本人宠物'
    assert value['targets'][0]['citation']['status'] == 'repaired'


def test_invalid_historical_pet_stays_pending_without_erasing_valid_dog():
    raw, content = captured('q35', '5351179883643641')
    value = compare.validate_text(raw, content)
    assert len(value['targets']) == 2
    assert value['targets'][1]['citation']['status'] == 'unverified'
    assert compare.vision_targets(value) == [{'id': 't1', 'name': '小狗', 'kind': '真实动物'}]
    assert value['status'] == '不确定'


def test_invalid_enums_do_not_become_visual_targets():
    raw = target('猫可爱')
    raw['targets'][0]['ownership'] = '随意猜测'
    value = compare.validate_text(raw, '猫可爱')
    assert value['targets'][0]['name'] == '猫'
    assert compare.vision_targets(value) == []
    assert value['status'] == '不确定'
