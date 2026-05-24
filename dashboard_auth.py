# -*- coding: utf-8 -*-
"""
dashboard_auth.py - local login + session + CSRF for the FXJEFE dashboard.

The dashboard exposes destructive controls (restart servers, run pipelines,
kill processes). It binds 127.0.0.1 only, so it is not reachable from the
network - but a malicious web page open in a local browser could still script
requests at it (DNS-rebinding / CSRF). This module closes that gap:

  * password login; hash stored in db/dashboard_auth.json (werkzeug PBKDF2)
  * every route needs a session except /login and /setup-password
  * Host-header allowlist            -> blocks DNS-rebinding
  * SameSite=Strict cookies + an X-CSRF-Token check on state-changing requests

Pure Flask/werkzeug - no OS-specific code; runs identically on Windows/Linux.

Usage from dashboard_hub.py:
    from dashboard_auth import init_auth, reset_password
    init_auth(app, DB_ROOT, port)        # once, before app.run()
"""

import json
import secrets
from datetime import timedelta
from pathlib import Path

from flask import request, session, redirect, jsonify, abort
from werkzeug.security import generate_password_hash, check_password_hash

# Paths reachable without a session. The Host check still applies to these.
_PUBLIC_PATHS = {"/login", "/setup-password"}
_STATE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _load(auth_file: Path) -> dict:
    try:
        return json.loads(auth_file.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(auth_file: Path, data: dict) -> None:
    auth_file.parent.mkdir(parents=True, exist_ok=True)
    auth_file.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _is_configured(auth_file: Path) -> bool:
    return bool(_load(auth_file).get("password_hash"))


def reset_password(db_root) -> bool:
    """Clear the stored password so the next launch shows the setup page.
    Backs the 'python dashboard_hub.py --reset-password' flag."""
    auth_file = Path(db_root) / "dashboard_auth.json"
    data = _load(auth_file)
    data.pop("password_hash", None)
    _save(auth_file, data)
    return True


# -- minimal dark login/setup page (self-contained, no external assets) -----
_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<title>{title}</title><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
 body{{background:#0a0e14;color:#cdd6e4;font-family:Segoe UI,Roboto,sans-serif;
   display:flex;align-items:center;justify-content:center;height:100vh;margin:0}}
 .box{{background:#121823;border:1px solid #1f2a3a;border-radius:10px;
   padding:32px 36px;width:320px;box-shadow:0 8px 40px rgba(0,0,0,.5)}}
 h1{{font-size:1rem;letter-spacing:2px;color:#00ff88;margin:0 0 4px}}
 p{{font-size:.78rem;color:#6b7a90;margin:0 0 18px}}
 input{{width:100%;box-sizing:border-box;background:#0a0e14;border:1px solid #1f2a3a;
   color:#cdd6e4;border-radius:6px;padding:10px 12px;margin:6px 0;font-size:.9rem}}
 button{{width:100%;background:#00ff88;color:#04121a;border:0;border-radius:6px;
   padding:11px;margin-top:12px;font-weight:700;cursor:pointer;letter-spacing:1px}}
 .err{{color:#ff5470;font-size:.78rem;min-height:1em;margin-top:8px}}
</style></head><body><div class="box">
 <h1>FXJEFE COMMAND CENTRAL</h1><p>{subtitle}</p>
 <form method="post">{fields}<button type="submit">{action}</button></form>
 <div class="err">{error}</div>
</div></body></html>"""


def _render(title, subtitle, action, fields, error=""):
    return _PAGE.format(title=title, subtitle=subtitle, action=action,
                        fields=fields, error=error)


def init_auth(app, db_root, port):
    """Wire login, session and CSRF onto the Flask app. Call once after the
    app is created and before app.run()."""
    db_root = Path(db_root)
    db_root.mkdir(parents=True, exist_ok=True)
    auth_file = db_root / "dashboard_auth.json"
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    # Ephemeral secret key -> every dashboard restart invalidates all sessions,
    # so the password prompt re-appears on every boot/restart of the server.
    # Short session lifetime also kicks idle tabs back to the login page.
    app.secret_key = secrets.token_hex(32)

    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=2),
    )

    def _begin_session():
        session["authed"] = True
        session["csrf"] = secrets.token_hex(16)
        session.permanent = True

    @app.before_request
    def _gate():
        # 1. Host-header allowlist - defeats DNS-rebinding. Applies to all.
        if request.host not in allowed_hosts:
            abort(403)

        path = request.path
        if path in _PUBLIC_PATHS:
            return None

        # 2. First run with no password -> force the setup page.
        if not _is_configured(auth_file):
            return None if path == "/setup-password" else redirect("/setup-password")

        # 3. Auth gate.
        if not session.get("authed"):
            if path.startswith("/api/"):
                return jsonify({"error": "auth required"}), 401
            return redirect("/login")

        # 4. CSRF - state-changing requests need the matching header.
        if request.method in _STATE_METHODS:
            token = request.headers.get("X-CSRF-Token", "")
            if not token or token != session.get("csrf"):
                return jsonify({"error": "bad or missing CSRF token"}), 403
        return None

    @app.after_request
    def _csrf_cookie(resp):
        # Expose the session CSRF token to same-site JS (double-submit pattern).
        if session.get("authed") and session.get("csrf"):
            resp.set_cookie("csrf_token", session["csrf"],
                            samesite="Strict", httponly=False, secure=False)
        return resp

    @app.route("/setup-password", methods=["GET", "POST"])
    def setup_password():
        if _is_configured(auth_file):
            return redirect("/login")
        error = ""
        if request.method == "POST":
            pw = request.form.get("password", "")
            pw2 = request.form.get("confirm", "")
            # Min length is intentionally lenient: the dashboard is local-only
            # (127.0.0.1 + Host allowlist + CSRF), so the password just keeps
            # accidental same-machine browser tabs out, not network attackers.
            if len(pw) < 4:
                error = "Password must be at least 4 characters."
            elif pw != pw2:
                error = "Passwords do not match."
            else:
                d = _load(auth_file)
                d["password_hash"] = generate_password_hash(pw)
                _save(auth_file, d)
                _begin_session()
                return redirect("/")
        fields = ('<input type="password" name="password" placeholder="Choose a password" autofocus>'
                  '<input type="password" name="confirm" placeholder="Confirm password">')
        return _render("Set Password", "First run - set your dashboard password.",
                       "SET PASSWORD", fields, error)

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if not _is_configured(auth_file):
            return redirect("/setup-password")
        error = ""
        if request.method == "POST":
            pw = request.form.get("password", "")
            if check_password_hash(_load(auth_file).get("password_hash", ""), pw):
                _begin_session()
                return redirect("/")
            error = "Wrong password."
        fields = '<input type="password" name="password" placeholder="Password" autofocus>'
        return _render("Login", "Enter your dashboard password.",
                       "UNLOCK", fields, error)

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect("/login")
