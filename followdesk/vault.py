"""Authenticated encryption via platform libraries; no custom primitives.

Local use delegates AES-256-GCM to Node's standard crypto library.
Hosted use requires cryptography/Fernet and a configured vault key.
"""
import json
from pathlib import Path
import shutil
import subprocess
from flask import current_app


def _local(mode,value):
    node=shutil.which("node")
    if not node:
        raise RuntimeError("Local encrypted storage requires Node.js. No token was stored.")
    process=subprocess.run([node,str(Path(__file__).with_name("vault.mjs")),mode],input=json.dumps(dict(key=current_app.config["LOCAL_VAULT_KEY"],value=value)),capture_output=True,text=True,timeout=5)
    if process.returncode:
        raise RuntimeError("Encrypted connection storage is unavailable. Reconnect after correcting vault configuration.")
    return process.stdout.strip()


def seal(value):
    key=current_app.config.get("VAULT_KEY")
    if key:
        from cryptography.fernet import Fernet
        return "fernet:"+Fernet(key).encrypt(value.encode()).decode()
    if not current_app.config["PRODUCTION"]:
        return "aesgcm:"+_local("seal",value)
    raise RuntimeError("Configure FOLLOWDESK_VAULT_KEY and cryptography before connecting.")


def open_token(value):
    if value.startswith("fernet:"):
        from cryptography.fernet import Fernet
        return Fernet(current_app.config["VAULT_KEY"]).decrypt(value[7:].encode()).decode()
    if value.startswith("aesgcm:") and not current_app.config["PRODUCTION"]:
        return _local("open",value[7:])
    raise RuntimeError("Cannot decrypt this connection in the current environment. Reconnect locally.")
