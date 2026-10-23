"""Public post metadata and its shared browsing/delivery presentation."""
from datetime import datetime, timezone
import math
import ipaddress
import re
import json
from urllib.parse import urlsplit, urlunsplit
from pathlib import Path


def string(value):
    return value.strip() if isinstance(value, str) else ''


def account_id(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return ''
    result = str(value).strip()
    return result if result.isascii() and result.isdecimal() else ''


def profile_url(value):
    url = string(value)
    try:
        parsed = urlsplit(url)
        if (parsed.scheme not in ('http', 'https') or parsed.username or parsed.password
                or parsed.hostname not in ('weibo.com', 'www.weibo.com', 'm.weibo.cn', 'weibo.cn')
                or parsed.port not in (None, 80, 443)):
            return ''
        # Public profile URLs can include visitor-specific tracking tokens.
        return urlunsplit(('https', parsed.hostname, parsed.path, '', ''))
    except ValueError:
        return ''


def gender(value):
    return {'m': '男', 'f': '女', 'n': '未知', '男': '男', '女': '女', '未知': '未知'}.get(string(value).lower(), '')


def post_location(mblog):
    annotations = mblog.get('annotations')
    for annotation in annotations if isinstance(annotations, list) else []:
        place = annotation.get('place') if isinstance(annotation, dict) else None
        if isinstance(place, dict):
            for name in ('title', 'name', 'address'):
                if string(place.get(name)):
                    return string(place[name])
    geo = mblog.get('geo')
    # Weibo's status geo representation orders these as latitude, longitude;
    # do not treat arbitrary objects or GeoJSON from other APIs as this shape.
    coords = geo.get('coordinates') if isinstance(geo, dict) and geo.get('type') == 'Point' else None
    if isinstance(coords, (tuple, list)) and len(coords) == 2:
        lat, lon = coords
        if (all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in coords)
                and -90 <= lat <= 90 and -180 <= lon <= 180):
            return f'经度 {lon:g}，纬度 {lat:g}'
    return ''


def ip_region(value):
    value = re.sub(r'^(?:IP\s*属地\s*[:：]?|发布于)\s*', '', string(value), flags=re.I).strip()
    if not value or value in ('未知', '未获取', '不详', '--') or any(c in value for c in '<>\r\n'):
        return ''
    try:
        ipaddress.ip_address(value)
        return ''
    except ValueError:
        return value


def stored_metadata(mblog, status=None):
    user = mblog.get('user') if isinstance(mblog.get('user'), dict) else {}
    return {
        'account_id': account_id(user.get('idstr') or user.get('id')),
        'profile_url': profile_url(user.get('profile_url')),
        'gender': gender(user.get('gender')),
        'account_verification': string(user.get('verified_reason')),
        'account_verified': user.get('verified') if isinstance(user.get('verified'), bool) else None,
        'publish_location': post_location(mblog),
        'post_ip_region': ip_region(mblog.get('region_name')),
        'metadata_version': 1,
        'metadata_collected_at': datetime.now(timezone.utc).isoformat(),
        'metadata_detail_status': (status or {}).get('detail', 'not_requested'),
        'metadata_author_status': (status or {}).get('author', 'not_requested'),
        'metadata_field_sources': json.dumps({
            'account': 'author_profile_or_post_user' if (status or {}).get('author') == 'available' else 'post_user',
            'publish_location': 'mblog.annotations.place_or_geo' if post_location(mblog) else '',
            'post_ip_region': 'mblog.region_name' if ip_region(mblog.get('region_name')) else '',
        }, ensure_ascii=False),
    }


def refresh_metadata(saved, incoming):
    """Refresh newly collected metadata without repeating cached model decisions."""
    if not incoming.get('metadata_version'):
        return False
    changed = False
    for key in ('nickname', 'account_id', 'profile_url', 'gender', 'account_verification', 'account_verified',
                'publish_location', 'post_ip_region',
                'metadata_version', 'metadata_collected_at', 'metadata_detail_status',
                'metadata_author_status', 'metadata_field_sources'):
        value = incoming.get(key)
        if value not in (None, '') and value != saved.get(key):
            saved[key] = value
            changed = True
    return changed


def reconcile_metadata(incoming, previous):
    """Share acquired evidence across search rows of this same newly collected post."""
    if not incoming.get('metadata_version'):
        return []
    merged = dict(incoming)
    for saved in previous:
        fallback = dict(saved)
        refresh_metadata(fallback, merged)
        refresh_metadata(merged, fallback)
    refresh_metadata(incoming, merged)
    return [saved for saved in previous if refresh_metadata(saved, merged)]


def posting_location(note):
    # These are saved post fields, never nested author/profile locations.
    for key in ('publish_location', 'location', 'location_name', 'geo_location'):
        value = note.get(key)
        if isinstance(value, dict):
            value = value.get('name') or value.get('address')
        if string(value):
            return string(value)
    return ''


def metadata_platform(note, path):
    explicit = string(note.get('platform')).lower()
    if explicit:
        return explicit
    source = Path(note.get('_collection_file') or path)
    if any(part.lower() in ('weibo', 'wb') for part in source.parts) or source.name.startswith('weibo_'):
        return 'weibo'
    if profile_url(note.get('note_url')):
        return 'weibo'
    return ''


def metadata_view(note, platform='weibo'):
    location = posting_location(note)
    is_weibo = platform in ('weibo', 'wb', '微博')
    region = ip_region(note.get('post_ip_region')) if is_weibo else ''
    verification = string(note.get('account_verification')) or string(note.get('author_verification'))
    if not verification:
        verified = note.get('account_verified')
        if verified is None:
            verified = note.get('author_verified')
        verification = '无认证说明' if verified in (False, 'False', 'false') else '未获取'
    return {
        'account_id': account_id(note.get('account_id')),
        'profile_url': profile_url(note.get('profile_url')),
        'gender': gender(note.get('gender')) or '未获取',
        'verification': verification,
        'publish_location': location,
        'post_ip_region': region,
        'display_location': location or region or '未获取',
        'location_source': ('微博定位' if is_weibo else '帖子定位') if location else 'IP 属地' if region else '未获取',
    }
