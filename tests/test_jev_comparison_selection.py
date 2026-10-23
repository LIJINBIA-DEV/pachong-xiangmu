from copy import deepcopy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from select_jev_passed_compare import passed


def records():
    return ({'note': {'jev_original_choice': 'keep'}, 'status': 'matched',
             'matched': True, 'uncertain': False, 'confidence': .9,
             'verification_confidence': .95, 'object_type': 'scene_animal',
             'target_relation': 'scene_component', 'evidence_text': '可爱的猫',
             'target_evidence_text': '公园的猫'},
            {'semantic_result': 'matched', 'jev_original_choice': 'keep'})


def test_explicit_verified_keep_passes():
    assert passed(*records())


@pytest.mark.parametrize('choice', ['review','reject',None,''])
def test_matched_does_not_override_original_jev_choice(choice):
    state, row = records()
    state['note']['jev_original_choice'] = row['jev_original_choice'] = choice
    assert not passed(state, row)


@pytest.mark.parametrize('field,value', [
    ('quality_reason','jev_screening_candidate'), ('quality_reason','low_or_missing_confidence'),
    ('status','review'), ('uncertain',True), ('confidence',None),
    ('verification_confidence',.69), ('verification_confidence',True),
    ('object_type','pet'), ('object_type','unrelated_item'), ('object_type',None),
    ('target_relation','unrelated'), ('target_evidence_text',''), ('duplicate_of','other')])
def test_pending_rejected_or_incomplete_proof_is_excluded(field, value):
    state, row = records()
    state[field] = value
    assert not passed(state, row)


def test_workbook_checkpoint_conflict_is_not_admitted():
    state, row = records()
    row['jev_original_choice'] = 'reject'
    assert not passed(state, row)
    state, row = records()
    row['original_semantic_source'] = 'model_review'
    assert not passed(state, row)
