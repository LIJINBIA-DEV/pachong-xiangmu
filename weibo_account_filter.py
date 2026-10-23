"""Exact public UID blocklists and conservative news/media account gates."""

from collections.abc import Mapping
from functools import lru_cache
import hashlib
from pathlib import Path
import re
import unicodedata


NEWS_MEDIA_REASON = "news_media_account"
BLOCKLIST_DIR = Path(__file__).resolve().parent / 'resources/weibo_account_blocklist/pybotfinder'
BLOCKLIST_FILES = {'bot.txt': 'account_blocklist_bot', 'media.txt': 'account_blocklist_media', 'government.txt': 'account_blocklist_government'}


@lru_cache(maxsize=1)
def load_blocklist():
    from tools.user_hash import anonymize_user_id
    uids, hashes, counts = {}, {}, {}
    digest = hashlib.sha256()
    for filename, reason in BLOCKLIST_FILES.items():
        raw = (BLOCKLIST_DIR / filename).read_bytes()
        digest.update(filename.encode() + b'\0' + raw)
        ids = set()
        for line in raw.decode('utf-8-sig').splitlines():
            uid = line.strip()
            if not uid:
                continue
            if not uid.isascii() or not uid.isdigit() or not 5 <= len(uid) <= 20:
                raise ValueError(f'Invalid UID in blocklist {filename}')
            ids.add(uid)
            # Preserve bot/media/government precedence for overlapping lists.
            uids.setdefault(uid, reason)
            hashes.setdefault(anonymize_user_id(uid), reason)
        counts[filename] = len(ids)
    return uids, hashes, {**counts, 'unique_accounts': len(uids)}, digest.hexdigest()


def blocklist_signature():
    registry = Path(__file__).resolve().parent / 'resources/weibo_account_blocklist/organizations.json'
    return hashlib.sha256((load_blocklist()[3] + IDENTITY_RULE).encode() + registry.read_bytes()).hexdigest()


def blocked_uid_reason(uid):
    # Keep IDs as strings. Do not truncate floats or match nickname substrings.
    if not isinstance(uid, (str, int)) or isinstance(uid, bool):
        return None
    value = str(uid).strip()
    reason = load_blocklist()[0].get(value)
    if reason:
        return reason
    # User-added exact UID entries are separate from the pinned public snapshot.
    from tools.user_hash import anonymize_user_id
    known = known_organizations().get(anonymize_user_id(value))
    return known['reason'] if known and known['reason'] in BLOCKLIST_FILES.values() else None


def account_filter_reason(user: Mapping | None) -> str | None:
    if not isinstance(user, Mapping):
        return None
    result = account_identity(user)
    return result['reason'] if result['status'] == 'excluded' else None


def blocklist_record_reason(record: Mapping) -> str | None:
    """Match only the downloaded UID lists, including anonymized exports."""
    reason = record.get('author_filter_reason')
    if reason in BLOCKLIST_FILES.values():
        return reason
    user = record.get('user')
    if isinstance(user, Mapping):
        reason = blocked_uid_reason(user.get('idstr') or user.get('id') or user.get('user_id'))
    else:
        # Flattened post/comment IDs are NOT author UIDs.
        reason = blocked_uid_reason(record.get('user_id') or record.get('creator_id'))
    creator = str(record.get('creator_hash') or '')
    reason = reason or load_blocklist()[1].get(creator)
    if reason:
        return reason
    known = known_organizations().get(creator)
    return known['reason'] if known and known['reason'] in BLOCKLIST_FILES.values() else None


def account_record_reason(record: Mapping) -> str | None:
    result = account_record_identity(record)
    return result['reason'] if result['status'] == 'excluded' else None


_MEDIA_NAME = re.compile(
    r"(?:新闻(?:网|中心|频道|客户端|资讯|联播|夜航|直播间|早班车|直播|快报|周刊)?|"
    r"媒体(?:中心|集团|网)?|融媒体中心|传媒|广播(?:电台|电视台)?|"
    r"电视台|报社|日报|晚报|晨报|时报|周报|人民日报社|新华社|中新社|新京报|"
    r"人民网|央视网|央广网|新华网|光明网|中新网|中国新闻网|中国青年报|南方周末|观察者网|中国网|"
    r"澎湃|封面新闻|红星新闻)"
    r"(?:官方(?:微博|账号)?|微博|客户端|发布|在线|新媒体|融媒体|传媒集团|集团)?$"
)
_PERSONAL_NAME = re.compile(
    r"爱看|看新闻|读新闻|新闻迷|媒体人|新闻人|新媒体人|自媒体人|"
    r"学生|同学|专业|学习|学新闻|学媒体|爱好者|读者|粉丝|记者|小编|打工|"
    r"我的|我是|个人|不想|不是|不做|不看|不要"
)
_MEDIA_VERIFICATION = re.compile(
    r"(?:新闻|媒体|传媒|报社|日报|晚报|广播|电视台|通讯社).{0,40}"
    r"(?:官方(?:微博|账号)?|法人|机构|集团|有限(?:公司|责任公司))|"
    r"(?:官方|机构|集团).{0,40}(?:新闻|媒体|传媒|报社|广播|电视台|通讯社)"
)
_PERSONAL_VERIFICATION = re.compile(r"记者|编辑|主持人|董事长|总监|总编|创始人|CEO|顾问|员工|个人|教授|教师|医生|医师|学生|工程师|律师|演员|歌手|博主|摄影师|院长|校长|主任|干部", re.I)


def _normalized(value) -> str:
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", str(value or "")))


def news_media_account_reason(user: Mapping | None) -> str | None:
    """Names/explicit organization verification are signals, not proof of personhood.

    Never treat a blue/yellow badge alone as media, or infer from masked names.
    Personal interest/profession names stay eligible unless the platform explicitly
    identifies their account as an official media organization.
    """
    if not isinstance(user, Mapping):
        return None
    verification = str(user.get("verified_reason") or "")
    if user.get("verified") is True and not _PERSONAL_VERIFICATION.search(verification) and _MEDIA_VERIFICATION.search(verification):
        return NEWS_MEDIA_REASON
    raw_name = str(user.get("screen_name") or user.get("nickname") or "")
    if "*" in raw_name:
        return None
    name = _normalized(raw_name)
    if not name or _PERSONAL_NAME.search(name):
        return None
    return NEWS_MEDIA_REASON if _MEDIA_NAME.search(name) else None


def news_media_record_reason(record: Mapping) -> str | None:
    """Also accepts the non-identifying flag on flattened semantic records."""
    if record.get("author_filter_reason") == NEWS_MEDIA_REASON:
        return NEWS_MEDIA_REASON
    return news_media_account_reason(record.get("user") or record)


IDENTITY_RULE = 'account-identity-v1'
EXCLUSION_REASONS = {NEWS_MEDIA_REASON, 'government_account', 'institution_account', *BLOCKLIST_FILES.values()}
_GOVERNMENT = re.compile(r'人民政府|人民法院|人民检察院|公安(?:局|分局|厅)|司法局|税务局|教育局|财政局|文旅局|文化和旅游局|民政局|交通运输局|市场监督管理局|政务服务中心|(?:国家|省|市|县|区).{0,15}(?:局|厅|委员会)(?:官方(?:微博|账号)?)?$|(?:市委|县委|区委|省委)(?:宣传部|办公室)|(?:政府|政务|交警|消防).{0,15}官方')
_MEDIA_ORG = re.compile(r'融媒体中心|广播电视台|广播电台|电视台|通讯社|报社|新闻(?:中心|传媒|机构)|媒体(?:中心|集团)|传媒(?:集团|有限公司)|日报社|晚报社')
_INSTITUTION = re.compile(r'有限公司|有限责任公司|股份公司|事业单位|行业协会|基金会|(?:公司|集团|协会|大学|学院|医院|博物馆|图书馆|研究院|研究所|学校|小学|中学|幼儿园)(?:官方(?:微博|账号)?)?$|官方.{0,15}(?:大学|学院|医院|博物馆|图书馆|研究院|研究所|学校)|企业官方|机构认证')
_ORG_HINT = re.compile(r'发布$|政务|文旅|官方|融媒|传媒|新闻|媒体|政府|公安|交警|公司|大学|医院|协会|基金会')


def _identity(status, reason=None, evidence=''):
    return {'status': status, 'reason': reason, 'evidence': str(evidence or '')[:240]}


@lru_cache(maxsize=1)
def known_organizations():
    from tools.user_hash import anonymize_user_id
    path = Path(__file__).resolve().parent / 'resources/weibo_account_blocklist/organizations.json'
    import json
    rows = json.loads(path.read_text(encoding='utf-8'))
    return {anonymize_user_id(row['uid']): row for row in rows}


def account_identity(user: Mapping | None) -> dict:
    """A missing blacklist match is not evidence of personal authorship."""
    if not isinstance(user, Mapping):
        return _identity('review', 'account_identity_uncertain', '未取得账号身份信息')
    from tools.user_hash import anonymize_user_id
    uid = user.get('idstr') or user.get('id') or user.get('user_id')
    reason = blocked_uid_reason(uid)
    if reason:
        return _identity('excluded', reason, '公开账号 ID 排除名单')
    known = known_organizations().get(anonymize_user_id(uid))
    if known:
        return _identity('excluded', known['reason'], known['verification'])
    verification = str(user.get('verified_reason') or '').strip()
    name = str(user.get('screen_name') or user.get('nickname') or '').strip()
    personal = bool(_PERSONAL_VERIFICATION.search(verification))
    # A profession at an institution describes an individual, not its employer.
    if user.get('verified') is True and verification and not personal:
        for pattern, reason in ((_GOVERNMENT, 'government_account'), (_MEDIA_ORG, NEWS_MEDIA_REASON), (_INSTITUTION, 'institution_account')):
            if pattern.search(verification):
                return _identity('excluded', reason, verification)
        if _MEDIA_VERIFICATION.search(verification):
            return _identity('excluded', NEWS_MEDIA_REASON, verification)
    if user.get('verified') is True and personal:
        return _identity('personal', evidence=verification)
    if '*' not in name and not _PERSONAL_NAME.search(name):
        # Preserve the existing explicit media-name gate; "某某发布" alone is uncertain.
        if _MEDIA_NAME.search(_normalized(name)):
            return _identity('excluded', NEWS_MEDIA_REASON, '账号名称：' + name)
        if _GOVERNMENT.search(name) or re.search(r'(?:有限公司|有限责任公司|股份公司)$', name):
            return _identity('review', 'account_identity_uncertain', '机构名称线索，认证主体待确认：' + name)
        if _ORG_HINT.search(name) or _ORG_HINT.search(verification):
            return _identity('review', 'account_identity_uncertain', verification or '机构名称线索：' + name)
    if user.get('verified') is False and name and '*' not in name:
        return _identity('personal', evidence='未认证普通账号，无机构线索')
    return _identity('review', 'account_identity_uncertain', verification or '认证信息缺失，需人工确认是否个人账号')


def account_record_identity(record: Mapping) -> dict:
    reason = blocklist_record_reason(record)
    if reason:
        return _identity('excluded', reason, '公开账号 ID 排除名单')
    known = known_organizations().get(str(record.get('creator_hash') or ''))
    if known:
        return _identity('excluded', known['reason'], known['verification'])
    if record.get('author_filter_reason') in EXCLUSION_REASONS:
        return _identity('excluded', record['author_filter_reason'], record.get('account_identity_evidence') or record.get('author_verification'))
    if isinstance(record.get('user'), Mapping):
        return account_identity(record['user'])
    user = {**record, 'id': record.get('creator_id') or record.get('user_id'),
            'verified': record.get('author_verified', record.get('verified')),
            'verified_reason': record.get('author_verification') or record.get('verified_reason'),
            'screen_name': record.get('nickname') or record.get('screen_name')}
    return account_identity(user)


def identity_fields(user):
    result = account_identity(user)
    return {'author_verified': user.get('verified') if isinstance(user.get('verified'), bool) else None,
            'author_verification': str(user.get('verified_reason') or '')[:240],
            'account_identity_status': result['status'], 'account_identity_reason': result['reason'],
            'account_identity_evidence': result['evidence'], 'account_identity_rule': IDENTITY_RULE}


def log_account_exclusion(user, note_id, keyword='', **kwargs):
    from account_audit import record_event
    result = account_identity(user)
    if result['status'] != 'excluded':
        return
    from tools import utils
    utils.logger.info(f"[AccountFilter] post {note_id}: excluded ({result['reason']}); {result['evidence']}")
    record_event({**user, 'note_id': note_id, 'source_keyword': keyword}, result, **kwargs)
