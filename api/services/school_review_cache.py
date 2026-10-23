"""Share only public collected material; every cache hit gets a new owner-scoped job."""
import hashlib
import json
from pathlib import Path
import time
import unicodedata
from collection_tasks import atomic_json
from api.services.school_review_profile import VERSION

PUBLIC_FIELDS = ('school', 'topic', 'platform', 'posts', 'profile', 'fetched_count',
                 'excluded_count', 'screening_status', 'created_at', 'finished_at')


class SchoolReviewCache:
    def __init__(self, root, days):
        self.directory = Path(root) / 'data/.ragent-review-cache'
        self.ttl = days * 86400

    def key(self, school, topic, platform):
        values = [unicodedata.normalize('NFKC', s).strip() for s in (school, topic, platform)]
        return hashlib.sha256(json.dumps([VERSION, *values], ensure_ascii=False).encode()).hexdigest()

    def get(self, school, topic, platform, now=None):
        now = time.time() if now is None else now
        try:
            entry = json.loads((self.directory / (self.key(school, topic, platform) + '.json')).read_text())
            age = now - entry['collected_epoch']
            if (entry['analysis_version'] != VERSION or not 0 <= age < self.ttl
                    or not isinstance(entry.get('data'), dict)
                    or self.key(entry['data']['school'], entry['data']['topic'], entry['data']['platform']) != self.key(school, topic, platform)
                    or not isinstance(entry['data'].get('posts'), list) or not entry['data']['posts']
                    or entry['data'].get('screening_status') != 'COMPLETED'
                    or not isinstance(entry['data'].get('profile'), dict)
                    or entry['data']['profile'].get('version') != VERSION
                    or entry['data']['profile'].get('status') not in {'COMPLETED', 'INSUFFICIENT'}):
                return None
            return entry
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def put(self, job):
        if (job.get('status') != 'COMPLETED' or not job.get('posts')
                or job.get('screening_status') != 'COMPLETED'
                or not isinstance(job.get('profile'), dict)
                or job['profile'].get('status') not in {'COMPLETED', 'INSUFFICIENT'}):
            return
        entry = {'analysis_version': VERSION, 'collected_epoch': job['created_epoch'],
                 'data': {k: job[k] for k in PUBLIC_FIELDS if k in job}}
        atomic_json(self.directory / (self.key(job['school'], job['topic'], job['platform']) + '.json'), entry)
