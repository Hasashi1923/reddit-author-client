#!/usr/bin/env python3
"""reddit_author_client: a minimal Reddit Data API client for one author account.

What it does (and nothing else):
  auth                         one-time OAuth (web app flow): opens Reddit's consent page, you click Allow,
                               the refresh token is saved locally. No password is ever handled.
  rules SUBREDDIT              read a subreddit's rules (read-only) before posting there.
  post SUBREDDIT TITLE FILE    submit ONE text post. Asks for a typed "yes" before submitting.
  comments POST_ID             list comments on one of my own posts.
  reply THING_ID FILE          reply to a comment on my own post. Asks for a typed "yes" first.

What it never does: vote, send private messages or chat, scrape or store other users' data,
post the same text to more than one subreddit, or post without the author's confirmation.
Rate: a few posts per week; the client refuses a second post within 24 hours.

Scopes: identity submit read edit. Config in ~/.config/reddit_author_client/ (chmod 600, never committed):
  app.json   {"client_id": "...", "client_secret": "...", "redirect_uri": "http://localhost:3004/callback",
              "user_agent": "python:reddit_author_client:v0.1 (by /u/YOUR_USERNAME)"}
  token.json written by `auth`.
License: MIT.
"""
import base64, hashlib, http.server, json, os, secrets, sys, time, urllib.parse, urllib.request, webbrowser

CFG = os.path.expanduser("~/.config/reddit_author_client")
APP, TOK, LOG = (os.path.join(CFG, n) for n in ("app.json", "token.json", "posted.json"))
SCOPES = "identity submit read edit"


def _load(p, default=None):
    try:
        with open(p) as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def _save(p, d):
    os.makedirs(CFG, mode=0o700, exist_ok=True)
    os.chmod(CFG, 0o700)
    tmp = p + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)   # created 0600 from the start
    with os.fdopen(fd, "w") as f:
        json.dump(d, f)
    os.replace(tmp, p)


def _clean(s):
    """Strip terminal control characters from text that came from Reddit before printing it."""
    return "".join(ch for ch in str(s) if ch.isprintable() or ch in "\n\t")


def _basic(app):
    return "Basic " + base64.b64encode(f"{app['client_id']}:{app['client_secret']}".encode()).decode()


def _token_call(app, form):
    req = urllib.request.Request("https://www.reddit.com/api/v1/access_token", data=urllib.parse.urlencode(form).encode(),
                                 headers={"Authorization": _basic(app), "User-Agent": app["user_agent"]})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def auth():
    app = _load(APP)
    state = secrets.token_urlsafe(16)
    url = "https://www.reddit.com/api/v1/authorize?" + urllib.parse.urlencode(
        {"client_id": app["client_id"], "response_type": "code", "state": state,
         "redirect_uri": app["redirect_uri"], "duration": "permanent", "scope": SCOPES})
    got = {}

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
            got.update(q)
            self.send_response(200); self.end_headers()
            self.wfile.write(b"Done. You can close this tab.")

        def log_message(self, *a):
            pass

    port = urllib.parse.urlparse(app["redirect_uri"]).port
    srv = http.server.HTTPServer(("127.0.0.1", port), H)
    print("Opening Reddit's consent page. Approve it in your browser.")
    webbrowser.open(url)
    srv.handle_request()
    if got.get("state") != state or "code" not in got:
        sys.exit("Authorisation failed or was declined.")
    t = _token_call(app, {"grant_type": "authorization_code", "code": got["code"], "redirect_uri": app["redirect_uri"]})
    t["obtained"] = time.time()
    _save(TOK, t)
    print("Authorised. Token saved.")


def _access():
    app, t = _load(APP), _load(TOK)
    if time.time() - t.get("obtained", 0) > t.get("expires_in", 3600) - 120:
        n = _token_call(app, {"grant_type": "refresh_token", "refresh_token": t["refresh_token"]})
        t.update(n); t["obtained"] = time.time(); _save(TOK, t)
    return app, t["access_token"]


def api(method, path, form=None):
    app, tok = _access()
    data = urllib.parse.urlencode(form).encode() if form else None
    req = urllib.request.Request("https://oauth.reddit.com" + path, data=data, method=method,
                                 headers={"Authorization": f"bearer {tok}", "User-Agent": app["user_agent"]})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def _confirm(what):
    print(what)
    if input('Type "yes" to submit: ').strip().lower() != "yes":
        sys.exit("Cancelled.")


def rules(sub):
    for r in api("GET", f"/r/{sub}/about/rules").get("rules", []):
        print(f"- {_clean(r['short_name'])}: {_clean(r.get('description', '')[:300])}")


def post(sub, title, path):
    log = _load(LOG, [])
    body = open(path, encoding="utf-8").read().strip()
    digest = hashlib.sha256(body.encode()).hexdigest()
    if log and time.time() - log[-1]["at"] < 24 * 3600:
        sys.exit("Refusing: the last post was less than 24 hours ago.")
    if any(e["digest"] == digest for e in log):
        sys.exit("Refusing: this exact text was already posted somewhere.")
    _confirm(f"Subreddit: r/{sub}\nTitle: {title}\n\n{body}\n")
    r = api("POST", "/api/submit", {"sr": sub, "kind": "self", "title": title, "text": body, "api_type": "json"})
    errs = r.get("json", {}).get("errors")
    if errs:
        sys.exit(f"Reddit refused: {_clean(errs)}")
    log.append({"at": time.time(), "sub": sub, "digest": digest, "url": r["json"]["data"].get("url")})
    _save(LOG, log)
    print("Posted:", _clean(r["json"]["data"].get("url")))


def comments(post_id):
    data = api("GET", f"/comments/{post_id}?limit=200&depth=3")
    def walk(children, d=0):
        for c in children:
            if c.get("kind") != "t1":
                continue
            x = c["data"]
            print("  " * d + f"[{_clean(x['name'])}] {_clean(x['body'][:400])}")
            if x.get("replies"):
                walk(x["replies"]["data"]["children"], d + 1)
    walk(data[1]["data"]["children"])


def reply(thing_id, path):
    body = open(path, encoding="utf-8").read().strip()
    _confirm(f"Reply to {thing_id}:\n\n{body}\n")
    r = api("POST", "/api/comment", {"thing_id": thing_id, "text": body, "api_type": "json"})
    print("Replied." if not r.get("json", {}).get("errors") else f"Reddit refused: {_clean(r['json']['errors'])}")


if __name__ == "__main__":
    a = sys.argv[1:]
    cmds = {"auth": (auth, 0), "rules": (rules, 1), "post": (post, 3), "comments": (comments, 1), "reply": (reply, 2)}
    if not a or a[0] not in cmds or len(a) - 1 != cmds[a[0]][1]:
        sys.exit(__doc__)
    cmds[a[0]][0](*a[1:])
