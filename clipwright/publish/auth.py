"""OAuth for the three providers, and the per-brand token files.

secrets/apps.json            your developer apps (one per provider, shared by every brand)
    {"google": {"client_id": "...", "client_secret": "..."},
     "tiktok": {"client_key": "...", "client_secret": "..."},
     "meta":   {"app_id": "...", "app_secret": "...", "graph_version": "v23.0",
                "config_id": "..."}}     # Facebook Login for Business configuration (optional)
secrets/<brand>/<provider>.json   tokens written by `./post connect`, chmod 600

`./post connect <brand> <provider>` opens the consent page and catches the redirect on
http://localhost:8765/callback, which must be registered as a redirect URI in each app.
Endpoints and field names follow each provider's public docs; they have not been exercised
against live accounts from this repo yet, so run one `connect` per provider and check.
"""

import base64
import hashlib
import http.server
import json
import os
import secrets as pysecrets
import time
import urllib.parse
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from .http import Transport, call

PORT = 8765
REDIRECT = f"http://localhost:{PORT}/callback"
# TikTok's Desktop form may only accept the loopback IP; the callback server listens on 127.0.0.1 either way
DEFAULT_REDIRECTS = {"tiktok": f"http://127.0.0.1:{PORT}/callback"}


def redirect_for(provider: str, apps: Dict[str, Any]) -> str:
    """The redirect URI registered in that provider's app: apps.json "redirect_uri", else the default."""
    return (apps.get(provider) or {}).get("redirect_uri") or DEFAULT_REDIRECTS.get(provider, REDIRECT)
PROVIDER_OF = {"youtube": "google", "tiktok": "tiktok", "facebook": "meta", "instagram": "meta"}
GOOGLE_SCOPES = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly"
TIKTOK_SCOPES = "user.info.basic,video.publish"
META_SCOPES = ("pages_show_list,pages_read_engagement,pages_manage_posts,business_management,"
               "instagram_basic,instagram_content_publish")
REFRESH_MARGIN = 300  # refresh access tokens this many seconds before they expire


class AuthError(Exception):
    pass


def graph(apps: Dict[str, Any]) -> str:
    return f"https://graph.facebook.com/{apps.get('meta', {}).get('graph_version', 'v23.0')}"


def load_apps(secrets_dir: Path) -> Dict[str, Any]:
    path = secrets_dir / "apps.json"
    if not path.exists():
        raise AuthError(f"{path} not found: create it with your app credentials (see README, Publishing)")
    return json.loads(path.read_text())


def _write_private(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, path)


class TokenStore:
    """Tokens for one brand. ``access(provider)`` returns a valid access token, refreshing it."""

    def __init__(self, secrets_dir: Path, brand: str, transport: Transport, now: Callable[[], float] = time.time):
        self.dir = secrets_dir / brand
        self.secrets_dir = secrets_dir
        self.brand = brand
        self.transport = transport
        self.now = now

    def path(self, provider: str) -> Path:
        return self.dir / f"{provider}.json"

    def load(self, provider: str) -> Dict[str, Any]:
        path = self.path(provider)
        if not path.exists():
            raise AuthError(f"{self.brand} is not connected to {provider}: run ./post connect {self.brand} {provider}")
        return json.loads(path.read_text())

    def save(self, provider: str, data: Dict[str, Any]) -> None:
        _write_private(self.path(provider), data)

    def access(self, provider: str) -> str:
        tok = self.load(provider)
        if provider == "meta":
            raise AuthError("meta uses page tokens: call page_token()")
        if tok.get("expires_at", 0) - REFRESH_MARGIN > self.now():
            return tok["access_token"]
        apps = load_apps(self.secrets_dir)
        if provider == "google":
            app = apps["google"]
            resp = call(self.transport, "POST", "https://oauth2.googleapis.com/token", form={
                "client_id": app["client_id"], "client_secret": app["client_secret"],
                "refresh_token": tok["refresh_token"], "grant_type": "refresh_token"})
        elif provider == "tiktok":
            app = apps["tiktok"]
            resp = call(self.transport, "POST", "https://open.tiktokapis.com/v2/oauth/token/", form={
                "client_key": app["client_key"], "client_secret": app["client_secret"],
                "refresh_token": tok["refresh_token"], "grant_type": "refresh_token"})
        else:
            raise AuthError(f"unknown provider {provider}")
        if "access_token" not in resp:
            raise AuthError(f"{provider} token refresh failed: {resp}")
        tok.update(access_token=resp["access_token"], expires_at=self.now() + int(resp.get("expires_in", 3600)))
        if resp.get("refresh_token"):
            tok["refresh_token"] = resp["refresh_token"]   # TikTok rotates refresh tokens
        self.save(provider, tok)
        return tok["access_token"]

    def page(self, page_id: str) -> Dict[str, Any]:
        """The stored Facebook Page entry: {name, access_token, ig_user_id}."""
        pages = self.load("meta").get("pages", {})
        if str(page_id) not in pages:
            raise AuthError(f"page {page_id} is not among the Pages {self.brand} granted; "
                            f"re-run ./post connect {self.brand} meta and tick it")
        return pages[str(page_id)]

    def page_for_ig(self, ig_user_id: str) -> Dict[str, Any]:
        for page in self.load("meta").get("pages", {}).values():
            if str(page.get("ig_user_id")) == str(ig_user_id):
                return page
        raise AuthError(f"Instagram account {ig_user_id} is not linked to a Page {self.brand} granted")


def _pkce(style: str):
    verifier = pysecrets.token_urlsafe(64)[:96]
    digest = hashlib.sha256(verifier.encode()).digest()
    if style == "hex":       # TikTok's desktop flow documents a hex-encoded SHA-256 challenge
        return verifier, digest.hex()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def authorize_url(provider: str, apps: Dict[str, Any], state: str, challenge: Optional[str]) -> str:
    if provider == "google":
        q = {"client_id": apps["google"]["client_id"], "redirect_uri": redirect_for("google", apps), "response_type": "code",
             "scope": GOOGLE_SCOPES, "access_type": "offline", "prompt": "consent", "state": state,
             "code_challenge": challenge, "code_challenge_method": "S256"}
        return "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(q)
    if provider == "tiktok":
        q = {"client_key": apps["tiktok"]["client_key"], "redirect_uri": redirect_for("tiktok", apps), "response_type": "code",
             "scope": TIKTOK_SCOPES, "state": state, "code_challenge": challenge, "code_challenge_method": "S256"}
        return "https://www.tiktok.com/v2/auth/authorize/?" + urllib.parse.urlencode(q)
    if provider == "meta":
        app = apps["meta"]
        version = app.get("graph_version", "v23.0")
        q = {"client_id": app["app_id"], "redirect_uri": redirect_for("meta", apps), "response_type": "code", "state": state}
        if app.get("config_id"):
            q["config_id"] = app["config_id"]   # Login for Business: the configuration carries the permissions
        else:
            q["scope"] = ",".join([META_SCOPES, *app.get("extra_scopes", [])])
        return f"https://www.facebook.com/{version}/dialog/oauth?" + urllib.parse.urlencode(q)
    raise AuthError(f"unknown provider {provider!r} (use google, tiktok or meta)")


def exchange(provider: str, apps: Dict[str, Any], code: str, verifier: Optional[str], transport: Transport,
             now: float) -> Dict[str, Any]:
    """Trade the redirect's code for what we store in secrets/<brand>/<provider>.json."""
    if provider == "google":
        app = apps["google"]
        r = call(transport, "POST", "https://oauth2.googleapis.com/token", form={
            "code": code, "client_id": app["client_id"], "client_secret": app["client_secret"],
            "redirect_uri": redirect_for("google", apps), "grant_type": "authorization_code", "code_verifier": verifier})
        if not r.get("refresh_token"):
            raise AuthError("Google returned no refresh token; remove the app's access in your Google account and retry")
        tok = {"access_token": r["access_token"], "refresh_token": r["refresh_token"],
               "expires_at": now + int(r.get("expires_in", 3600))}
        ch = call(transport, "GET", "https://www.googleapis.com/youtube/v3/channels",
                  params={"part": "snippet", "mine": "true"},
                  headers={"Authorization": f"Bearer {tok['access_token']}"})
        items = ch.get("items") or []
        tok["channel"] = {"id": items[0]["id"], "title": items[0]["snippet"]["title"]} if items else None
        return tok
    if provider == "tiktok":
        app = apps["tiktok"]
        r = call(transport, "POST", "https://open.tiktokapis.com/v2/oauth/token/", form={
            "client_key": app["client_key"], "client_secret": app["client_secret"], "code": code,
            "grant_type": "authorization_code", "redirect_uri": redirect_for("tiktok", apps), "code_verifier": verifier})
        if "access_token" not in r:
            raise AuthError(f"TikTok token exchange failed: {r}")
        return {"access_token": r["access_token"], "refresh_token": r["refresh_token"], "open_id": r.get("open_id"),
                "expires_at": now + int(r.get("expires_in", 86400)), "scope": r.get("scope")}
    if provider == "meta":
        app, base = apps["meta"], graph(apps)
        short = call(transport, "GET", f"{base}/oauth/access_token", params={
            "client_id": app["app_id"], "client_secret": app["app_secret"], "redirect_uri": redirect_for("meta", apps), "code": code})
        long = call(transport, "GET", f"{base}/oauth/access_token", params={
            "grant_type": "fb_exchange_token", "client_id": app["app_id"], "client_secret": app["app_secret"],
            "fb_exchange_token": short["access_token"]})
        # Page tokens fetched with a long-lived user token do not expire
        pages = call(transport, "GET", f"{base}/me/accounts", params={
            "fields": "id,name,access_token,instagram_business_account", "access_token": long["access_token"]})
        out = {}
        for p in pages.get("data", []):
            out[p["id"]] = {"name": p["name"], "access_token": p["access_token"],
                            "ig_user_id": (p.get("instagram_business_account") or {}).get("id")}
        if not out:
            raise AuthError("Meta returned no Pages: tick your Page (and its Instagram account) on the consent screen")
        return {"user_token": long["access_token"], "pages": out}
    raise AuthError(f"unknown provider {provider!r}")


def catch_redirect(expected_state: str, timeout: float = 300) -> str:
    """Serve one request on localhost:PORT and return the ``code`` from the OAuth redirect."""
    result: Dict[str, str] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(self.path).query))
            if urllib.parse.urlsplit(self.path).path.rstrip("/") != "/callback":
                self.send_response(404)
                self.end_headers()
                return
            result.update(q)
            ok = q.get("state") == expected_state and "code" in q
            self.send_response(200 if ok else 400)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Connected. You can close this tab." if ok else
                             f"Not connected: {q.get('error_description') or q.get('error') or 'bad state'}".encode())

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", PORT), Handler)
    server.timeout = timeout
    deadline = time.time() + timeout
    while "code" not in result and "error" not in result and time.time() < deadline:
        server.handle_request()
    server.server_close()
    if result.get("state") != expected_state or "code" not in result:
        raise AuthError(f"authorisation did not complete: {result.get('error_description') or result.get('error') or 'timed out or state mismatch'}")
    return result["code"]


def connect(secrets_dir: Path, brand: str, provider: str, transport: Transport, open_url: Callable[[str], Any]) -> Dict[str, Any]:
    apps = load_apps(secrets_dir)
    if provider not in apps:
        raise AuthError(f"secrets/apps.json has no {provider!r} app")
    state = pysecrets.token_urlsafe(24)
    verifier, challenge = _pkce("hex" if provider == "tiktok" else "s256") if provider != "meta" else (None, None)
    url = authorize_url(provider, apps, state, challenge)
    print(f"Opening the {provider} consent page. If it does not open, visit:\n{url}")
    open_url(url)
    code = catch_redirect(state)
    tok = exchange(provider, apps, code, verifier, transport, time.time())
    TokenStore(secrets_dir, brand, transport).save(provider, tok)
    return tok
