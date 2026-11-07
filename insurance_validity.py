"""Deterministic policy intervals shared by the provider comparison."""
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

PRAGUE = ZoneInfo('Europe/Prague')

def _bound(value, end=False):
    text = str(value or '').strip()
    if text in {'', '-', '—'}:
        return None
    try:
        if len(text) == 10:
            day = next((datetime.strptime(text, fmt).date() for fmt in
                        ('%Y-%m-%d', '%d.%m.%Y', '%d/%m/%Y') if _matches(text, fmt)), None)
            if day is None:
                raise ValueError('Unknown date')
            return datetime.combine(day, time.max if end else time.min, PRAGUE)
        try:
            parsed = datetime.fromisoformat(text.replace('Z', '+00:00'))
        except ValueError:
            parsed = datetime.strptime(text, '%d.%m.%Y %H:%M:%S')
        return parsed.replace(tzinfo=PRAGUE) if parsed.tzinfo is None else parsed
    except (ValueError, TypeError):
        raise ValueError('Neplatné období pojištění') from None

def _matches(value, fmt):
    try:
        datetime.strptime(value, fmt)
        return True
    except ValueError:
        return False

def policy_state(policy, as_of=None):
    now = as_of or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=PRAGUE)
    try:
        start = _bound(getattr(policy, 'poj_od', ''))
        end = _bound(getattr(policy, 'poj_do', ''), end=True)
        if start and end and end < start:
            return 'unknown'
        if start and now < start:
            return 'future'
        if end and now > end:
            return 'ended'
        return 'active'
    except ValueError:
        return 'unknown'

def policy_sort_key(policy):
    # Stable even when the provider changes row order. Conflicts are reported separately.
    return tuple(str(getattr(policy, key, '') or '') for key in
                 ('poj_od', 'poj_do', 'cps', 'pojistka', 'spz', 'vin'))
