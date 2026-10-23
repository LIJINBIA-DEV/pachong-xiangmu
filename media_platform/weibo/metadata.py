"""Bounded, task-local enrichment of public post metadata."""
import asyncio
from copy import deepcopy

from weibo_metadata import account_id, gender, ip_region, post_location, profile_url, string

from .media import extract_image_urls, ordered_image_pics


def _valid_pics(mblog):
    """Map canonical image URLs to their first original picture objects."""
    pictures = {}
    for pic in ordered_image_pics(mblog):
        urls = extract_image_urls({'pics': [pic]})
        if urls:
            pictures.setdefault(urls[0], pic)
    return pictures


def _images_incomplete(mblog):
    try:
        expected = int(mblog.get('pic_num') or 0)
    except (TypeError, ValueError, OverflowError):
        return False
    return expected > len(extract_image_urls(mblog))


def merge_user(original, incoming):
    result = dict(original) if isinstance(original, dict) else {}
    if not isinstance(incoming, dict):
        return result
    current_id = account_id(result.get('idstr') or result.get('id'))
    incoming_id = account_id(incoming.get('idstr') or incoming.get('id'))
    if current_id and incoming_id and current_id != incoming_id:
        return result
    validators = {'id': account_id, 'idstr': account_id, 'screen_name': string,
                  'gender': gender, 'profile_url': profile_url, 'verified_reason': string,
                  'verified': lambda value: isinstance(value, bool)}
    for key, valid in validators.items():
        if not valid(result.get(key)) and valid(incoming.get(key)):
            result[key] = incoming[key]
    return result


def merge_detail(original, incoming):
    """Fill same-post metadata, longer text and a more complete photo set."""
    result = deepcopy(original)
    if (not original.get('id') or not isinstance(incoming, dict)
            or str(incoming.get('id') or '') != str(original['id'])):
        return result
    result['user'] = merge_user(original.get('user'), incoming.get('user'))
    if not post_location(original) and post_location(incoming):
        for key in ('annotations', 'geo'):
            if key in incoming:
                result[key] = deepcopy(incoming[key])
    if not ip_region(original.get('region_name')) and ip_region(incoming.get('region_name')):
        result['region_name'] = incoming['region_name']
    if len(string(incoming.get('text'))) > len(string(original.get('text'))):
        result['text'] = incoming['text']
        result['isLongText'] = incoming.get('isLongText', False)
    current_pics, incoming_pics = _valid_pics(original), _valid_pics(incoming)
    if len(incoming_pics) > len(current_pics):
        # Existing filenames are position-based: retain their order and objects,
        # then append only genuinely missing, valid photos from the detail page.
        merged_pics = [pic for pic in ordered_image_pics(original)
                       if extract_image_urls({'pics': [pic]})]
        for url, pic in incoming_pics.items():
            if url not in current_pics:
                merged_pics.append(pic)
        result['pics'] = deepcopy(merged_pics)
    return result


class MetadataEnricher:
    def __init__(self, client, interval=0):
        self.client = client
        self.interval = interval
        self.authors = {}
        self.posts = {}
        self.known_posts = {}
        self.known_authors = {}
        self.request_lock = asyncio.Lock()

    async def _request(self, method_name, identity):
        method = getattr(self.client, method_name, None)
        if method is None:
            return {}, 'unavailable'
        async with self.request_lock:
            try:
                response = await asyncio.wait_for(method(identity), timeout=45)
                return (response, 'available') if isinstance(response, dict) and response else ({}, 'unavailable')
            except Exception:
                # Metadata errors are non-fatal. Never log response bodies or cookies.
                return {}, 'failed'
            finally:
                await asyncio.sleep(max(0, self.interval))

    async def _author(self, uid):
        if uid not in self.authors:
            self.authors[uid] = asyncio.create_task(self._request('get_creator_info_by_id', uid))
        response, status = await self.authors[uid]
        data = response.get('data') if isinstance(response.get('data'), dict) else {}
        user = response.get('userInfo') or data.get('userInfo') or {}
        if not isinstance(user, dict) or not user:
            return {}, 'unavailable' if status == 'available' else status
        returned_id = account_id(user.get('idstr') or user.get('id'))
        if returned_id != uid:
            return {}, 'unavailable'
        return user, status

    async def enrich(self, note_item):
        item = deepcopy(note_item)
        mblog = item.get('mblog')
        if not isinstance(mblog, dict) or not mblog.get('id'):
            return item
        status = dict(item.get('_metadata_status') or {})
        nid = str(mblog['id'])
        mblog = merge_detail(mblog, self.known_posts.get(nid, {}))
        self._remember(mblog)
        # A completed full-text/detail lookup already tried this same source.
        if 'detail' not in status and (not post_location(mblog)
                                      or not ip_region(mblog.get('region_name'))
                                      or _images_incomplete(mblog)):
            if nid not in self.posts:
                self.posts[nid] = asyncio.create_task(self._request('get_note_info_by_id', nid))
            response, status['detail'] = await self.posts[nid]
            incoming = response.get('mblog')
            if isinstance(incoming, dict) and str(incoming.get('id') or '') == nid:
                mblog = merge_detail(mblog, incoming)
            elif status['detail'] == 'available':
                status['detail'] = 'unavailable'
        user = mblog.get('user') if isinstance(mblog.get('user'), dict) else {}
        uid = account_id(user.get('idstr') or user.get('id'))
        user = merge_user(user, self.known_authors.get(uid, {}))
        needs_author = (not gender(user.get('gender')) or not profile_url(user.get('profile_url'))
                        or not isinstance(user.get('verified'), bool)
                        or (user.get('verified') is True and not string(user.get('verified_reason'))))
        if uid and needs_author:
            incoming, status['author'] = await self._author(uid)
            user = merge_user(user, incoming)
        mblog['user'] = user
        # Another occurrence may have supplied fields while this one awaited IO.
        mblog = merge_detail(mblog, self.known_posts.get(nid, {}))
        self._remember(mblog)
        item['mblog'] = mblog
        item['_metadata_status'] = status
        return item

    def _remember(self, mblog):
        user = merge_user({}, mblog.get('user'))
        uid = account_id(user.get('idstr') or user.get('id'))
        if uid:
            self.known_authors[uid] = merge_user(user, self.known_authors.get(uid, {}))
        # Retain only public metadata, not full bodies, media or comments.
        self.known_posts[str(mblog['id'])] = {
            'id': mblog['id'], 'user': user,
            **{key: deepcopy(mblog[key]) for key in ('annotations', 'geo', 'region_name') if key in mblog},
        }
