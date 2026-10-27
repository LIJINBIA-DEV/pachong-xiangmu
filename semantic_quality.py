"""Evidence provenance and conservative safeguards, independent of model output."""

from dataclasses import dataclass
from difflib import SequenceMatcher
import html
import math
import re
import unicodedata



def explicit_jev_rejection(choice=None, object_type=None, *, original_choice=None,
                           original_object_type=None, verification_choice=None, reason=None):
    """A definite negative cannot be upgraded by candidate/review policy."""
    if choice == 'reject' or original_choice == 'reject':
        return 'semantic_reject'
    if verification_choice == 'contradicted':
        return 'evidence_contradicted'
    if reason in {'semantic_reject', 'evidence_contradicted'}:
        return reason
    return None


def saved_jev_rejection(note):
    """Apply the same gate to old candidate exports without rewriting them."""
    if note.get('semantic_rule') not in {'evaluation', 'topic'}:
        return None  # Legacy spatial/image rejections stay in history, without blocking human review.
    return explicit_jev_rejection(
        object_type=note.get('semantic_object_type'),
        original_choice=note.get('jev_original_choice'),
        original_object_type=note.get('jev_original_object_type'),
        reason=note.get('quality_reason') or note.get('semantic_rejection_reason'),
        verification_choice=note.get('verification_choice'),
    )


def is_general_evaluation(note):
    return note.get('semantic_rule') == 'evaluation'


def evaluation_problem(decision, records, threshold):
    score = decision.confidence
    if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) or not threshold <= score <= 1:
        return 'low_or_missing_confidence'
    by_key = {record.key: record for record in records}
    evaluation, target = by_key.get(decision.evidence_id), by_key.get(decision.target_evidence_id)
    if not evaluation or not target or not evaluation.text.strip() or not target.text.strip():
        return 'missing_evidence'
    return None


def keyword_pair_present(note, comments=(), pair=None):
    """Use actual saved text, never the search label or synthesized evidence."""
    if is_general_evaluation(note):
        fields = [str(note.get(name) or '') for name in ('title', 'desc', 'content')]
        fields.extend(str(comment.get('content') or '') for comment in comments)
        evidence = (note.get('evaluation_evidence'), note.get('evaluation_target_evidence'))
        return all(isinstance(value, str) and bool(value.strip()) and any(value in field for field in fields) for value in evidence)
    if note.get('semantic_rule') == 'topic':
        evidence = note.get('topic_evidence')
        fields = [str(note.get(name) or '') for name in ('title', 'desc', 'content')]
        fields.extend(str(comment.get('content') or '') for comment in comments)
        return isinstance(evidence, str) and bool(evidence.strip()) and any(evidence in value for value in fields)
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
    if note.get('semantic_rule') not in {'evaluation', 'topic'} or note.get('semantic_result') not in {'matched', 'review', 'pending', 'excluded', 'duplicate'}:
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
        if context_pair:
            for paragraph in re.finditer(r'[^\n]+', value):
                text = paragraph.group()
                if len(text) > max_fragment or not all(word in text for word in context_pair):
                    continue
                if any(item.source == source and item.start == paragraph.start() and item.end == paragraph.end() for item in records):
                    continue
                records.append(Evidence(f"context{len(records) + 1}", source, text, paragraph.start(), paragraph.end()))
    return records


def scene_animal_ambiguity(text: str) -> bool:
    return False  # Compatibility for old offline tools; no object-category policy remains.


def scene_wildlife_ambiguity(text: str, target: str) -> bool:
    return False


def image_requirement_problem(note: dict) -> str | None:
    return None  # Optional media can never exclude a post.


def keep_problem(pair, decision, records: list[Evidence], threshold: float) -> str | None:
    return evaluation_problem(decision, records, threshold)


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
