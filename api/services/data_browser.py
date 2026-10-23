"""Read saved posts with their own comments and pictures; never re-crawl."""
from collections import Counter
import ast
import csv
from functools import lru_cache
import json
from pathlib import Path
from urllib.parse import quote, urlsplit

from openpyxl import load_workbook
from media_downloader.paths import build_media_dir

DATA_TYPES = {'.xlsx', '.xls', '.json', '.jsonl', '.csv'}
IMAGE_TYPES = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}


def text(value):
    return '' if value is None else str(value)


def post_id(row):
    return text(row.get('note_id') or row.get('aweme_id') or row.get('video_id') or row.get('content_id'))


def web_url(value):
    value = text(value).strip()
    try:
        parsed = urlsplit(value)
    except ValueError:
        return ''
    return value if parsed.scheme in {'http', 'https'} and parsed.netloc else ''


def read_rows(path):
    if path.suffix.lower() == '.csv':
        with path.open(encoding='utf-8-sig', newline='') as source:
            return list(csv.DictReader(source))
    if path.suffix.lower() == '.jsonl':
        with path.open(encoding='utf-8-sig') as source:
            return [json.loads(line) for line in source if line.strip()]
    value = json.loads(path.read_text(encoding='utf-8-sig'))
    if isinstance(value, dict):
        value = value.get('data', [value])
    return value if isinstance(value, list) else []


def paired_comment_files(path):
    candidates = set()
    for marker in ('contents', 'notes'):
        if marker in path.name:
            candidates.add(path.with_name(path.name.replace(marker, 'comments')))
    return sorted(p for p in candidates if p.is_file())


def signature(path):
    stat = path.stat()
    return str(path.resolve()), stat.st_mtime_ns, stat.st_size


def load_dataset(path):
    companions = paired_comment_files(path)
    return _load_dataset(signature(path), tuple(signature(p) for p in companions))


def load_review_dataset(root, path):
    from collection_tasks import find_task, safe_path, task_files
    task = find_task(root, path)
    files = task_files(root, task) if task else [path.relative_to(root).as_posix()]
    notes, comments = {}, {}
    for relative in files:
        source = safe_path(root, relative)
        if not source.is_file():
            raise ValueError('A collection round file is missing; restore it before continuing')
        rows, by_note = load_dataset(source)
        for note in rows:
            key = (post_id(note), text(note.get('source_keyword')))
            notes.setdefault(key, {**note, '_collection_file': relative})
        for nid, items in by_note.items():
            comments.setdefault(nid, []).extend(items)
    return list(notes.values()), comments


@lru_cache(maxsize=8)
def _load_dataset(file_signature, companion_signatures):
    path = Path(file_signature[0])
    notes, comments = [], []
    def append_rows(rows, default_status='unfiltered'):
        for row in rows:
            if not isinstance(row, dict):
                continue
            if isinstance(row.get('note'), dict):
                note = dict(row['note'])
                for name in ('evidence_source', 'evidence_text', 'matched_comment'):
                    note[name] = row.get(name)
                note['semantic_result'] = row.get('status', default_status)
                notes.append(note)
                comments.extend(row.get('comments') or [])
            elif row.get('comment_id'):
                comments.append(row)
            elif post_id(row):
                notes.append({**row, 'semantic_result': row.get('semantic_result') or default_status})
    if path.suffix.lower() == '.xlsx':
        book = load_workbook(path, read_only=True, data_only=True)
        try:
            for sheet in book:
                values = iter(sheet.values)
                headers = next(values, ())
                rows = [dict(zip(headers, row)) for row in values if any(v is not None for v in row)]
                if sheet.title in {'Contents', 'Matched', 'Review', 'Pending', 'Duplicates'}:
                    append_rows(rows, {'Matched': 'matched', 'Review': 'review', 'Pending': 'pending', 'Duplicates': 'duplicate'}.get(sheet.title, 'unfiltered'))
                elif sheet.title in {'Comments', 'ReviewComments', 'MatchedComments'}:
                    for row in rows:
                        comments.append({**row, '_semantic_hit': sheet.title == 'MatchedComments'})
        finally:
            book.close()
    elif path.suffix.lower() == '.xls':
        import pandas as pd
        book = pd.read_excel(path, sheet_name=None, dtype=object)
        for name, frame in book.items():
            rows = frame.where(frame.notna(), None).to_dict(orient='records')
            if 'comment' in name.lower():
                comments.extend(rows)
            else:
                append_rows(rows)
    else:
        append_rows(read_rows(path))
    for companion in companion_signatures:
        comments.extend(read_rows(Path(companion[0])))
    # Checkpoints append multiple states for one post. Keep the latest state.
    unique = {}
    for note in notes:
        nid = post_id(note)
        unique[(nid, text(note.get('source_keyword')))] = note
    by_note = {}
    for comment in comments:
        if isinstance(comment, dict):
            nid = post_id(comment)
            by_note.setdefault(nid, []).append(comment)
    return list(unique.values()), by_note


def image_urls(note):
    value = note.get('image_list') or note.get('images') or []
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
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(url for item in value if (url := web_url(item.get('url') or item.get('url_default') if isinstance(item, dict) else item))))


def pictures(root, path, note):
    nid = post_id(note)
    aliases = ('wb', 'weibo') if path.parent.name in {'wb', 'weibo'} or 'weibo' in path.name else (path.parent.name,)
    local = []
    for platform in aliases:
        folder = build_media_dir(root, platform, nid)
        if folder.is_dir():
            for file in sorted(folder.iterdir()):
                if file.is_file() and file.suffix.lower() in IMAGE_TYPES and file.stat().st_size:
                    try:
                        relative = file.resolve().relative_to(root.resolve()).as_posix()
                    except ValueError:
                        continue
                    local.append({'url': '/api/data/media/' + quote(relative, safe='/'), 'name': file.name, 'local': True})
    # Downloaded pictures work offline. If none exist, use saved image URLs.
    return local or [{'url': url, 'name': f'image-{i}', 'local': False} for i, url in enumerate(image_urls(note), 1)]


def image_download_info(note, images):
    """Source image metadata and local downloads are separate, including old files."""
    names = note.get('image_names') or []
    if isinstance(names, str):
        names = names.split(',')
    if not isinstance(names, list):
        names = []
    names = {str(name).strip() for name in names if Path(str(name).strip()).suffix.lower() in IMAGE_TYPES}
    expected = max(len(names), len(image_urls(note)))
    downloaded = len({item['name'] for item in images if item['local']})
    count = max(expected, downloaded)
    if downloaded:
        status = 'partial' if downloaded < count else 'downloaded'
    elif expected:
        status = 'not_downloaded'
    else:
        status = 'no_images' if any(key in note for key in ('image_names', 'image_list', 'images')) else 'unknown'
    return {
        'image_count': None if status == 'unknown' else count,
        'downloaded_image_count': downloaded, 'image_download_status': status,
    }


def comment_hits(note, rows):
    query = text(note.get('source_keyword'))
    pair = query.split(maxsplit=1)
    source = text(note.get('evidence_source'))
    selected_id = source.removeprefix('comment:') if source.startswith('comment:') else ''
    selected = note.get('matched_comment')
    if isinstance(selected, dict):
        rows = [*rows, {**selected, '_semantic_hit': True}]
    seen, hits, all_comments = set(), [], []
    for row in rows:
        if row.get('source_keyword') and text(row['source_keyword']) != query:
            continue
        cid, content = text(row.get('comment_id')), text(row.get('content'))
        if not content.strip() or (cid, content) in seen:
            continue
        seen.add((cid, content))
        item = {'id': cid, 'content': content, 'nickname': text(row.get('nickname'))}
        all_comments.append(item)
        if note.get('semantic_result') == 'matched' and note.get('selection_origin') not in {'review_policy','user_confirmed'} and note.get('quality_reason') != 'jev_screening_candidate' and ((selected_id and cid == selected_id) or row.get('_semantic_hit')):
            hits.append({**item, 'kind': 'semantic'})
        elif len(pair) == 2 and all(keyword in content for keyword in pair):
            hits.append({**item, 'kind': 'keyword'})
    return hits, all_comments


def browse_posts(root, path, offset=0, limit=20, search='', status='all'):
    from weibo_metadata import metadata_platform, metadata_view
    notes, by_note = load_review_dataset(root, path)
    counts = Counter(text(n.get('semantic_result')) for n in notes)
    filtered = []
    needle = search.strip().casefold()
    for note in notes:
        if status != 'all' and note.get('semantic_result') != status:
            continue
        nid = post_id(note)
        comments = by_note.get(nid, [])
        content = text(note.get('content') or note.get('desc'))
        haystack = '\n'.join([nid, text(note.get('title')), content, text(note.get('source_keyword')), *(text(c.get('content')) for c in comments)])
        if not needle or needle in haystack.casefold():
            filtered.append((note, nid, comments, content))
    records = []
    for index, (note, nid, comments, content) in enumerate(filtered[offset:offset + limit], offset):
        hits, all_comments = comment_hits(note, comments)
        images = pictures(root, path, note)
        records.append({
            'key': f'{nid}:{text(note.get("source_keyword"))}', 'id': nid, 'index': index + 1,
            'title': text(note.get('title')), 'content': content,
            'url': web_url(note.get('note_url') or note.get('url')),
            'source_keyword': text(note.get('source_keyword')), 'status': note.get('semantic_result'),
            'nickname': text(note.get('nickname')), 'published_at': text(note.get('create_date_time') or note.get('time')),
            **metadata_view(note, metadata_platform(note, path)),
            'evidence': text(note.get('semantic_evidence') or note.get('evidence_text')),
            'evidence_source': text(note.get('evidence_source')),
            'selection_origin': text(note.get('selection_origin')),
            'manual_review_required': note.get('manual_review_required') in (True, 1, 'true', 'True'),
            'jev_original_choice': text(note.get('jev_original_choice')),
            'hit_comments': hits, 'comments': all_comments, 'images': images,
            **image_download_info(note, images),
        })
    return {'posts': records, 'total': len(filtered), 'file_total': len(notes), 'offset': offset, 'limit': limit, 'counts': dict(counts)}
