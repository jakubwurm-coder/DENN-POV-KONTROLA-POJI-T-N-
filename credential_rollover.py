"""Short-lived, replay-resistant credential provisioning for the office agent."""
import hashlib
import hmac
import os
import secrets
import threading
import time
from flask import jsonify, request

def install(app, expected_agent):
    challenges = {}
    lock = threading.Lock()

    def enabled():
        try:
            return (bool(os.getenv('DENNI_POV_BOOTSTRAP_KEY')) and
                    time.time() < float(os.getenv('DENNI_POV_BOOTSTRAP_UNTIL', '0')))
        except ValueError:
            return False

    @app.get('/api/agent/credential-challenge')
    def credential_challenge():
        if not enabled():
            return jsonify(ok=False), 404
        agent = str(request.args.get('agent') or '').upper()
        if agent != expected_agent():
            return jsonify(ok=False), 403
        with lock:
            now = time.monotonic()
            for key in list(challenges):
                if challenges[key][1] < now:
                    challenges.pop(key)
            if len(challenges) >= 30:
                return jsonify(ok=False), 429
            nonce = secrets.token_hex(32)
            challenges[nonce] = (agent, now + 60)
        return jsonify(nonce=nonce, salt=os.getenv('DENNI_POV_BOOTSTRAP_SALT', ''))

    @app.post('/api/agent/credential-claim')
    def credential_claim():
        if not enabled():
            return jsonify(ok=False), 404
        payload = request.get_json(silent=True) or {}
        nonce = str(payload.get('nonce') or '')
        agent = str(payload.get('agent') or '').upper()
        with lock:
            challenge = challenges.pop(nonce, None)
        if not challenge or challenge[0] != agent or challenge[1] < time.monotonic():
            return jsonify(ok=False), 403
        try:
            key = bytes.fromhex(os.environ['DENNI_POV_BOOTSTRAP_KEY'])
        except (ValueError, KeyError):
            return jsonify(ok=False), 503
        expected = hmac.new(key, (nonce + ':' + agent).encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(str(payload.get('proof') or ''), expected):
            return jsonify(ok=False), 403
        return jsonify(token=os.getenv('SYNC_TOKEN_NEXT') or os.environ['SYNC_TOKEN'])
