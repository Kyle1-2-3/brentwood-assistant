"""Shared-password access gate, enforced before any page or API handler."""
import hashlib
import hmac
import sqlite3
import time
import secrets

from flask import jsonify, redirect, render_template, request, g
from itsdangerous import BadSignature, URLSafeTimedSerializer
from werkzeug.security import check_password_hash

COOKIE = "brentwood_access"
ENTRY_COOKIE = "brentwood_entry"
MAX_AGE = 7 * 86400
# "Remember this browser": a persistent cookie that opens the page without a
# single-use entry ticket. Still bound to the current password hash.
REMEMBER_AGE = 30 * 86400
REMEMBER_SUFFIX = ":remember"


def install_access_gate(app, store, client_ip):
    def signer():
        return URLSafeTimedSerializer(store.signing_key(), salt=COOKIE)

    def fingerprint():
        return hashlib.sha256(app.config["SITE_PASSWORD_HASH"].encode()).hexdigest()

    def access_token():
        """(valid, remembered) for the access cookie; raises BadSignature when invalid."""
        cookie = request.cookies.get(COOKIE, "")
        token = signer().loads(cookie, max_age=REMEMBER_AGE)
        if not isinstance(token, str):
            raise BadSignature("Invalid access token")
        remembered = token.endswith(REMEMBER_SUFFIX)
        if not remembered:
            signer().loads(cookie, max_age=MAX_AGE)  # session cookies expire sooner
        return hmac.compare_digest(token.removesuffix(REMEMBER_SUFFIX), fingerprint()), remembered

    @app.before_request
    def require_access():
        if not app.config["ACCESS_GATE_ENABLED"]:
            return None
        if not app.config["SITE_PASSWORD_HASH"]:
            return "Access is temporarily unavailable.", 503
        if request.endpoint == "access_login":
            return None
        try:
            valid, remembered = access_token()
            if valid:
                if request.path in ("/", "/index.html") and not remembered:
                    # A password grants exactly one document load. Existing API
                    # cookies cannot unlock a new tab, revisit, or refresh.
                    g.consume_entry = True
                    entry = URLSafeTimedSerializer(store.signing_key(), salt=ENTRY_COOKIE).loads(
                        request.cookies.get(ENTRY_COOKIE, ""), max_age=60)
                    if not isinstance(entry, str):
                        raise BadSignature("Invalid entry")
                    now = int(time.time())
                    if store.reserve([(f"entry:{entry}", 1, now + 120)], now):
                        raise BadSignature("Entry already used")
                return None
        except BadSignature:
            pass
        except (OSError, sqlite3.Error):
            return "Access is temporarily unavailable.", 503
        if request.path == "/chat" or request.path.startswith("/api/"):
            return jsonify(error="authentication_required", reply="Please sign in to use Brentwood Assistant."), 401
        return redirect("/login", code=303)

    @app.after_request
    def private_response(response):
        if app.config["ACCESS_GATE_ENABLED"]:
            response.headers["Cache-Control"] = "private, no-store"
            response.vary.add("Cookie")
        if getattr(g, "consume_entry", False):
            response.delete_cookie(ENTRY_COOKIE)
        return response

    @app.route("/login", methods=["GET", "POST"])
    def access_login():
        error = None
        status = 200
        if request.method == "POST":
            origin = request.headers.get("Origin")
            if origin and origin.rstrip("/") != request.host_url.rstrip("/") and origin.rstrip("/") != "https://" + request.host:
                return "Invalid request origin.", 403
            try:
                now = int(time.time())
                ip_key = hmac.new(store.signing_key().encode(), client_ip().encode(), hashlib.sha256).hexdigest()
                retry = store.reserve([(f"login:{ip_key}", 10, now + 900)], now)
                if retry:
                    return render_template("login.html", error="Too many attempts. Please try again in 15 minutes."), 429, {"Retry-After": str(retry)}
                password = request.form.get("password", "")
                if len(password) <= 256 and check_password_hash(app.config["SITE_PASSWORD_HASH"], password):
                    response = redirect("/", code=303)
                    secure = request.is_secure or request.headers.get("X-Forwarded-Proto") == "https"
                    if request.form.get("remember"):
                        response.set_cookie(COOKIE, signer().dumps(fingerprint() + REMEMBER_SUFFIX),
                                            max_age=REMEMBER_AGE, httponly=True, samesite="Lax", secure=secure)
                        return response
                    response.set_cookie(COOKIE, signer().dumps(fingerprint()),
                                        httponly=True, samesite="Lax", secure=secure)
                    response.set_cookie(ENTRY_COOKIE,
                                        URLSafeTimedSerializer(store.signing_key(), salt=ENTRY_COOKIE).dumps(secrets.token_hex(24)),
                                        httponly=True, samesite="Lax", secure=secure)
                    return response
            except (OSError, sqlite3.Error):
                return render_template("login.html", error="Sign-in is temporarily unavailable. Please try again shortly."), 503
            error = "Incorrect password. Please try again."
            status = 401
        return render_template("login.html", error=error), status

    @app.post("/logout")
    def access_logout():
        response = redirect("/login", code=303)
        response.delete_cookie(COOKIE)
        response.delete_cookie(ENTRY_COOKIE)
        return response
