"""Durable final messages; a network outage never discards a finished check."""
import json
import os
from pathlib import Path

def directory():
    return Path(os.getenv('DENNI_POV_OUTBOX', str(Path(__file__).resolve().parent / '.agent-outbox')))

def pending():
    root = directory()
    return sorted(root.glob('*.json'), key=lambda p: p.stat().st_mtime) if root.exists() else []

def enqueue(snapshot):
    root = directory()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    run_id = str(snapshot.get('run_id') or snapshot.get('check_id') or '')
    import re
    if not re.fullmatch('[a-f0-9]{32}', run_id):
        raise ValueError('Finální zpráva vyžaduje jednoznačný identifikátor běhu.')
    target = root / (run_id + '.json')
    temporary = target.with_suffix('.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        json.dump(snapshot, stream, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(target)
    return target

def flush(send):
    for path in pending():
        snapshot = json.loads(path.read_text(encoding='utf-8'))
        send(snapshot)  # Must raise unless the server durably acknowledged this run.
        path.unlink()
