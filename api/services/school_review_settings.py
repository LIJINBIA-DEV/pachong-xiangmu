"""Opt-in school-review features. Local configuration changes require a restart."""
from dataclasses import dataclass, field, asdict
import json
from pathlib import Path


@dataclass
class SchoolReviewSettings:
    progress_enabled: bool = False
    cache_enabled: bool = False
    prewarm_enabled: bool = False
    cache_days: int = 7
    prewarm_hour: int = 3
    prewarm_targets: list = field(default_factory=list)

    def __post_init__(self):
        for name in ('progress_enabled', 'cache_enabled', 'prewarm_enabled'):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f'{name} must be a boolean')
        if type(self.cache_days) is not int or not 1 <= self.cache_days <= 15:
            raise ValueError('cache_days must be 1..15')
        if type(self.prewarm_hour) is not int or not 0 <= self.prewarm_hour <= 23:
            raise ValueError('prewarm_hour must be 0..23')
        if self.prewarm_enabled and not self.cache_enabled:
            raise ValueError('prewarm requires cache_enabled')
        if not isinstance(self.prewarm_targets, list) or len(self.prewarm_targets) > 20:
            raise ValueError('prewarm_targets must contain at most 20 queries')
        for target in self.prewarm_targets:
            if not isinstance(target, dict) or set(target) != {'school', 'topic', 'platform'}:
                raise ValueError('each prewarm target requires school, topic, platform')
            for key, minimum, maximum in [('school', 2, 60), ('topic', 1, 40)]:
                value = target[key]
                if (not isinstance(value, str) or value != value.strip() or not minimum <= len(value) <= maximum
                        or any(c in value for c in ',，\n\r\x00')):
                    raise ValueError('invalid prewarm keywords')
            if target['platform'] not in {'xhs', 'wb', 'zhihu', 'bili'}:
                raise ValueError('invalid prewarm platform')

    @classmethod
    def load(cls, root):
        path = Path(root) / '.runtime/school-reviews.json'
        return cls(**json.loads(path.read_text())) if path.exists() else cls()

    def public(self):
        return {**asdict(self), 'timezone': 'Asia/Shanghai'}
