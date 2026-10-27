"""Resolve one fixed publication window per collection task (Beijing time)."""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import json
import math
import os

BEIJING = timezone(timedelta(hours=8))


def publication_timestamp(value):
    try:
        if value is None or isinstance(value, bool):
            return None
        if isinstance(value, (int, float)) or str(value).replace('.', '', 1).isdigit():
            stamp = float(value)
            return (stamp / 1000 if stamp > 1e11 else stamp) if math.isfinite(stamp) and stamp > 0 else None
        if isinstance(value, datetime):
            parsed = value
        else:
            try:
                parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
            except ValueError:
                parsed = datetime.strptime(str(value), '%a %b %d %H:%M:%S %z %Y')
        return (parsed if parsed.tzinfo else parsed.replace(tzinfo=BEIJING)).timestamp()
    except (ValueError, TypeError, OverflowError):
        return None


@dataclass(frozen=True)
class PublicationWindow:
    mode: str = 'all'
    start: float | None = None
    end: float | None = None

    @classmethod
    def resolve(cls, mode='all', start_date=None, end_date=None, *, now=None):
        if mode == 'all':
            return cls()
        now = now or datetime.now(timezone.utc)
        if mode in {'day', 'week', 'month'}:
            return cls(mode, (now - timedelta(days={'day': 1, 'week': 7, 'month': 30}[mode])).timestamp(), now.timestamp())
        if mode != 'custom' or not start_date or not end_date:
            raise ValueError('请选择有效的发布时间范围，并填写开始和结束日期。')
        begin, finish = date.fromisoformat(str(start_date)), date.fromisoformat(str(end_date))
        if begin > finish or finish == date.max:
            raise ValueError('开始日期不能晚于结束日期，结束日期必须有效。')
        return cls(mode, datetime.combine(begin, time.min, BEIJING).timestamp(),
                   datetime.combine(finish + timedelta(days=1), time.min, BEIJING).timestamp())

    @classmethod
    def from_environment(cls):
        value = json.loads(os.environ.get('MEDIACRAWLER_PUBLICATION_WINDOW', '{}'))
        return cls(**value)

    @property
    def active(self):
        return self.start is not None and self.end is not None

    def as_dict(self):
        return {'mode': self.mode, 'start': self.start, 'end': self.end}

    def exclusion(self, value):
        if not self.active:
            return None
        stamp = publication_timestamp(value)
        if stamp is None:
            return 'unknown_publish_time'
        return None if self.start <= stamp < self.end else 'outside_time_range'

    def older_page(self, values):
        # Search uses latest order. Require every returned post to have a
        # known old timestamp; pinned, mixed or unreadable pages cannot stop it.
        return self.active and bool(values) and all((stamp := publication_timestamp(value)) is not None and stamp < self.start for value in values)
