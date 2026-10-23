"""Evidence provenance and conservative safeguards, independent of model output."""

from dataclasses import dataclass
from difflib import SequenceMatcher
import html
import ast
import json
import math
from pathlib import PurePath
import re
import unicodedata
from urllib.parse import urlsplit

from semantic_rules import OBJECT_TYPES, target_scope


def explicit_jev_rejection(choice=None, object_type=None, *, original_choice=None,
                           original_object_type=None, verification_choice=None, reason=None):
    """A definite negative cannot be upgraded by candidate/review policy."""
    if object_type in {'pet', OBJECT_TYPES['pet']} or original_object_type in {'pet', OBJECT_TYPES['pet']} or reason == 'pet_not_allowed':
        return 'pet_not_allowed'
    if choice == 'reject' or original_choice == 'reject':
        return 'semantic_reject'
    if verification_choice == 'contradicted':
        return 'evidence_contradicted'
    if reason in {'semantic_reject', 'evidence_contradicted'}:
        return reason
    return None


def saved_jev_rejection(note):
    """Apply the same gate to old candidate exports without rewriting them."""
    return explicit_jev_rejection(
        object_type=note.get('semantic_object_type'),
        original_choice=note.get('jev_original_choice'),
        original_object_type=note.get('jev_original_object_type'),
        reason=note.get('quality_reason') or note.get('semantic_rejection_reason'),
        verification_choice=note.get('verification_choice'),
    )


def keyword_pair_present(note, comments=(), pair=None):
    """Use actual saved text, never the search label or synthesized evidence."""
    if pair is None:
        words = str(note.get('source_keyword') or '').strip().split(maxsplit=1)
        pair = tuple(words) if len(words) == 2 else None
    if not pair or len(pair) != 2 or not all(pair):
        return False
    fields = [str(note.get(name) or '') for name in ('title', 'desc', 'content')]
    fields.extend(str(comment.get('content') or '') for comment in comments)
    return any(pair[0] in value and pair[1] in value for value in fields)


def saved_collection_rejection(note, comments=()):
    """Enforce collection eligibility independently of human image/account marks."""
    if note.get('semantic_result') not in {'matched', 'review', 'pending', 'excluded', 'duplicate'}:
        return None
    if not keyword_pair_present(note, comments):
        return 'keyword_miss'
    if ('comments_fetch_failed' in {note.get('semantic_comment_stop_reason'), note.get('comments_collection_stop_reason')}
            or note.get('semantic_source') == 'comments_unavailable'):
        return 'comments_fetch_failed'
    return None


@dataclass(frozen=True)
class Evidence:
    key: str
    source: str
    text: str
    start: int
    end: int


def evidence_records(fields: list[tuple[str, str]], max_fragment: int = 900, *, context_pair: tuple[str, str] | None = None) -> list[Evidence]:
    """Original source slices; repeated context anchors never become evidence."""
    records = []
    for source, value in fields:
        for match in re.finditer(r"[^。！？!?；;\n]+[。！？!?；;\n]*", value):
            for start in range(match.start(), match.end(), max_fragment):
                end = min(start + max_fragment, match.end())
                if value[start:end].strip():
                    records.append(Evidence(f"e{len(records) + 1}", source, value[start:end], start, end))
        # Offer contiguous paragraph evidence alongside sentence evidence. It
        # carries the location-to-object bridge without synthesizing any text
        # or joining comments, titles, bodies, or different paragraphs.
        if context_pair and target_scope(context_pair[1]) in {'place', 'contextual_place'}:
            for paragraph in re.finditer(r'[^\n]+', value):
                text = paragraph.group()
                if len(text) > max_fragment or not all(word in text for word in context_pair):
                    continue
                if any(item.source == source and item.start == paragraph.start() and item.end == paragraph.end() for item in records):
                    continue
                records.append(Evidence(f"context{len(records) + 1}", source, text, paragraph.start(), paragraph.end()))
    return records


def scene_animal_ambiguity(text: str) -> bool:
    """A rescue-to-review signal, never a rule that automatically admits a post."""
    animals = r"猫|兔|鸭|熊|狗|鹿|🐱|🐈|🐰|🐇|🦆|🐻|🐶|🐕|🦌"
    scene = r"雕塑|雕像|草雕|绿雕|花坛|装置|墙绘|涂鸦|玩偶|造型|布景"
    return bool(
        re.search(rf"(?:{animals})[\s\S]{{0,80}}(?:{scene})|(?:{scene})[\s\S]{{0,80}}(?:{animals})", text)
        or re.search(rf"(?:{animals}).{{0,12}}(?:留在|亮相).{{0,20}}(?:公园|广场|街区)", text)
    )


def scene_wildlife_ambiguity(text: str, target: str) -> bool:
    return target_scope(target) in {'place', 'contextual_place'} and target in text and bool(
        re.search(r'野生|野鸟|水鸟|候鸟|松鼠|园区饲养|动物区|动物园|动物乐园|池塘.{0,12}(?:鸭|天鹅)', text)
    )


def image_requirement_problem(note: dict) -> str | None:
    """Check saved picture metadata, not visual quality or download success."""
    known = False
    for key in ('image_names', 'image_list', 'images'):
        if key not in note:
            continue
        known = True
        value = note[key]
        if isinstance(value, str):
            if value.lstrip().startswith('['):
                try:
                    value = json.loads(value)
                except ValueError:
                    try:
                        value = ast.literal_eval(value)
                    except (ValueError, SyntaxError):
                        value = []
            else:
                value = value.split(',')
        if not isinstance(value, (list, tuple)):
            continue
        for item in value:
            if isinstance(item, dict):
                item = item.get('url') or item.get('url_default') or ''
            if not isinstance(item, str) or not item.strip():
                continue
            item = item.strip()
            if key == 'image_names':
                if PurePath(item).suffix.lower() in {'.jpg', '.jpeg', '.png', '.gif', '.webp'}:
                    return None
            else:
                try:
                    url = urlsplit(item)
                except ValueError:
                    continue
                if url.scheme in {'http', 'https'} and url.netloc and PurePath(url.path).suffix.lower() not in {'.mp4', '.mov', '.flv', '.m4s', '.mp3'}:
                    return None
    return 'no_images' if known else 'image_information_unavailable'


def keep_problem(pair, decision, records: list[Evidence], threshold: float) -> str | None:
    confidence = decision.confidence
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not math.isfinite(confidence) or not threshold <= confidence <= 1:
        return "low_or_missing_confidence"
    if decision.object_type not in {"place", "building", "facility", "landscape", "decoration", "wild_animal", "park_animal", "scene_animal"}:
        return "object_not_allowed"
    if decision.object_type in {'wild_animal', 'park_animal', 'scene_animal'} and target_scope(pair[1]) not in {'place', 'contextual_place'}:
        return 'animal_outside_place_scope'
    allowed = {"target_itself", "scene_component"} if target_scope(pair[1]) in {"place", "contextual_place"} else {"target_itself", "element_component"}
    if decision.target_relation not in allowed:
        return "target_relation_conflict"
    by_key = {record.key: record for record in records}
    evaluation = by_key.get(decision.evidence_id)
    location = by_key.get(decision.target_evidence_id)
    if not evaluation or not location:
        return "missing_evidence"
    if pair[0] not in evaluation.text:
        return "evaluation_without_keyword"
    if pair[1] not in location.text:
        return "location_without_keyword"
    if re.search(rf'(?:并不|一点也不|完全不|毫不|不怎么|不太|不可|不).{{0,3}}{re.escape(pair[0])}', evaluation.text):
        return 'negative_evaluation'
    if decision.object_type == 'scene_animal':
        if re.search(r'我家|自家|自己养|宠物|遛猫|牵.{0,8}猫|带.{0,8}(?:小猫|猫咪)', evaluation.text + '\n' + location.text):
            return 'pet_not_allowed'
    if decision.object_type in {'wild_animal', 'park_animal'}:
        identity_text = evaluation.text + '\n' + location.text
        if re.search(r'流浪(?:猫|狗|犬|动物)', evaluation.text):
            return 'animal_identity_unconfirmed'
        if re.search(r'(?:我家|自家|自己养|宠物|遛狗|牵.{0,8}(?:狗|犬)|带.{0,8}(?:小狗|狗狗|宠物))', evaluation.text):
            return 'pet_not_allowed'
        if re.search(r'猫|狗|犬', evaluation.text) and not re.search(r'野生|园区.{0,12}(?:饲养|管理)|动物区|保护区', identity_text):
            return 'animal_identity_unconfirmed'
    # This invalidates the selected evidence, not an entire post that might
    # contain another independent and valid scene evaluation.
    if re.search(rf"(?:名字|名称|英文名|店名|地名).{{0,20}}{re.escape(pair[0])}|{re.escape(pair[0])}.{{0,5}}(?:的)?(?:名字|名称|英文名|店名|地名)", evaluation.text):
        return "name_only_evidence"
    return None


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", html.unescape(value or "")).casefold()
    return "".join(char for char in value if char.isalnum())


def duplicate_kind(note, source, evidence_text, previous) -> tuple[str, str] | None:
    """Exact long copies are duplicates; near copies are flagged, never erased.

    Repeated short captions and independent comments do not establish duplication.
    The caller supplies only earlier qualified posts for the same keyword pair.
    """
    body = normalize_text(str(note.get("content") or note.get("desc") or ""))
    if len(body) < 60:
        return None
    for other in previous:
        old = normalize_text(str(other.note.get("content") or other.note.get("desc") or ""))
        if source == "comment" or other.source == "comment":
            if normalize_text(evidence_text or "") != normalize_text(other.evidence_text or ""):
                continue
        note_id = str(other.note["note_id"])
        if body == old:
            return "exact_text", note_id
        if min(len(body), len(old)) >= 120:
            short, long = sorted((body, old), key=len)
            overlap = sum(block.size for block in SequenceMatcher(None, short, long, autojunk=False).get_matching_blocks())
            if overlap / len(short) >= 0.97:
                return "near_text", note_id
    return None
