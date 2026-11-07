"""Credential rollover without publishing a token or trusting the exposed old token.

The short-lived server challenge requires proof of the SQL password already held
by the office agent. Neither password nor derived key is transmitted to the server.
Windows persists the returned token with user-bound DPAPI.
"""
import base64
import ctypes
import hashlib
import hmac
import json
import os
from pathlib import Path

def token_path():
    return Path(os.getenv('DENNI_POV_TOKEN_FILE', str(Path(__file__).resolve().parent / '.agent-sync-token')))

def _protect(data, decrypt=False):
    if os.name != 'nt':
        return data
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_char))]
    buf = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    target = Blob()
    fn = ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise OSError('Nelze použít chráněné úložiště přihlašovacích údajů.')
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        ctypes.windll.kernel32.LocalFree(target.data)

def load_token():
    path = token_path()
    if path.is_file():
        return _protect(base64.b64decode(path.read_bytes()), decrypt=True).decode()
    return os.getenv('DENNI_POV_SYNC_TOKEN', '').strip()

def save_token(token):
    path = token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(base64.b64encode(_protect(token.encode())))
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(temp, 0o600)
    temp.replace(path)

def bootstrap(base_url, agent_id):
    import requests
    # Already-provisioned protected credentials survive normal updates/restarts.
    if token_path().is_file():
        return True
    response = requests.get(base_url + '/api/agent/credential-challenge',
        params={'agent': agent_id}, timeout=20)
    if response.status_code == 404:
        return bool(load_token())
    response.raise_for_status()
    challenge = response.json()
    password = os.getenv('TIRBAZAR_PASSWORD', '')
    if not password:
        from tirbazar import get_password
        password = get_password()
    key = hashlib.pbkdf2_hmac('sha256', password.encode(),
        bytes.fromhex(challenge['salt']), 200000)
    proof = hmac.new(key, (challenge['nonce'] + ':' + agent_id).encode(), hashlib.sha256).hexdigest()
    password = ''; key = b''
    response = requests.post(base_url + '/api/agent/credential-claim',
        json={'agent': agent_id, 'nonce': challenge['nonce'], 'proof': proof}, timeout=20)
    response.raise_for_status()
    save_token(response.json()['token'])
    return True
