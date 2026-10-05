import os
import secrets
from datetime import datetime, timedelta, timezone

from flask import Flask, Response, abort, redirect, render_template, request, url_for
from jinja2 import DictLoader
from sqlalchemy import create_engine, text

MAX_CHARS = 200_000
EXPIRY = {"never": None, "1h": timedelta(hours=1), "1d": timedelta(days=1), "1w": timedelta(weeks=1)}

db_url = os.environ.get("DATABASE_URL", "sqlite:///pastes.db")
if db_url.startswith("postgres://"):  # older Render URLs
    db_url = db_url.replace("postgres://", "postgresql://", 1)
engine = create_engine(db_url, pool_pre_ping=True)

with engine.begin() as c:
    c.execute(text("""
        CREATE TABLE IF NOT EXISTS pastes (
            id VARCHAR(16) PRIMARY KEY,
            title VARCHAR(120) NOT NULL,
            content TEXT NOT NULL,
            created_at VARCHAR(32) NOT NULL,
            expires_at VARCHAR(32),
            burn INTEGER NOT NULL DEFAULT 0
        )"""))

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 1_000_000


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def get_paste(pid):
    with engine.begin() as c:
        row = c.execute(text("SELECT * FROM pastes WHERE id = :id"), {"id": pid}).mappings().first()
        if row and row["expires_at"] and row["expires_at"] <= now():
            c.execute(text("DELETE FROM pastes WHERE id = :id"), {"id": pid})
            return None
    return row


@app.after_request
def headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Content-Security-Policy"] = (
        "default-src 'none'; style-src 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src https://fonts.gstatic.com; script-src 'unsafe-inline'; form-action 'self'; base-uri 'none'"
    )
    return resp


@app.get("/")
def index():
    return render_template("new.html", error=None, max_chars=MAX_CHARS)


@app.post("/new")
def create():
    content = request.form.get("content", "")
    title = request.form.get("title", "").strip()[:120] or "Untitled"
    expiry = request.form.get("expiry", "1d")
    burn = 1 if request.form.get("burn") else 0
    if not content.strip():
        return render_template("new.html", error="Paste some text before saving.", max_chars=MAX_CHARS), 400
    if len(content) > MAX_CHARS:
        return render_template("new.html", error=f"That's over the {MAX_CHARS:,} character limit.", max_chars=MAX_CHARS), 413
    if expiry not in EXPIRY:
        expiry = "1d"
    delta = EXPIRY[expiry]
    expires_at = (datetime.now(timezone.utc) + delta).strftime("%Y-%m-%dT%H:%M:%S") if delta else None
    pid = secrets.token_urlsafe(6)
    with engine.begin() as c:
        c.execute(text("DELETE FROM pastes WHERE expires_at IS NOT NULL AND expires_at <= :n"), {"n": now()})
        c.execute(
            text("INSERT INTO pastes (id, title, content, created_at, expires_at, burn) "
                 "VALUES (:id, :t, :c, :cr, :ex, :b)"),
            {"id": pid, "t": title, "c": content, "cr": now(), "ex": expires_at, "b": burn},
        )
    if burn:  # don't open it ourselves, or we'd burn it
        return render_template("created.html", link=url_for("view", pid=pid, _external=True))
    return redirect(url_for("view", pid=pid))


@app.get("/p/<pid>")
def view(pid):
    paste = get_paste(pid)
    if not paste:
        abort(404)
    if paste["burn"]:
        return render_template("burn.html", paste=paste)
    return render_template("view.html", paste=paste, burned=False)


@app.post("/p/<pid>/reveal")
def reveal(pid):
    paste = get_paste(pid)
    if not paste or not paste["burn"]:
        abort(404)
    with engine.begin() as c:
        c.execute(text("DELETE FROM pastes WHERE id = :id"), {"id": pid})
    return render_template("view.html", paste=paste, burned=True)


@app.get("/raw/<pid>")
def raw(pid):
    paste = get_paste(pid)
    if not paste or paste["burn"]:
        abort(404)
    return Response(paste["content"], mimetype="text/plain; charset=utf-8")


@app.errorhandler(404)
def not_found(_):
    return render_template("missing.html"), 404


BASE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>{% block title %}scrapbin{% endblock %}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root{--bg:#e9edf1;--panel:#fff;--ink:#17212b;--muted:#566472;--line:#c6d0da;--accent:#0e7c66;--accent-ink:#fff;--warn:#9a3412;--warn-bg:#fff1e6}
@media (prefers-color-scheme:dark){:root{--bg:#10161c;--panel:#18212a;--ink:#e6ecf1;--muted:#93a1ae;--line:#2c3945;--accent:#3ec9a7;--accent-ink:#06231c;--warn:#fdba74;--warn-bg:#2a1c10}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 "Instrument Sans",system-ui,sans-serif}
header{max-width:60rem;margin:0 auto;padding:1.25rem 1rem;display:flex;justify-content:space-between;align-items:baseline}
header a{color:var(--ink);text-decoration:none}
.logo{font:600 1.35rem "JetBrains Mono",monospace;letter-spacing:-.02em}
main{max-width:60rem;margin:0 auto;padding:0 1rem 3rem}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:6px}
textarea,input[type=text],select{font:inherit;color:inherit;background:transparent;border:0;width:100%}
textarea{font:400 .9rem/1.55 "JetBrains Mono",monospace;min-height:55vh;padding:1rem;resize:vertical;tab-size:4}
textarea:focus,input:focus,select:focus{outline:2px solid var(--accent);outline-offset:-2px}
.bar{display:flex;flex-wrap:wrap;gap:.75rem 1.25rem;align-items:center;padding:.75rem 1rem;border-top:1px solid var(--line)}
.bar .title{flex:1 1 14rem;border:1px solid var(--line);border-radius:4px;padding:.45rem .6rem}
.bar select{width:auto;border:1px solid var(--line);border-radius:4px;padding:.45rem .6rem;background:var(--panel)}
label{display:flex;gap:.45rem;align-items:center;color:var(--muted);font-size:.92rem}
button,.btn{font:600 .95rem "Instrument Sans",sans-serif;background:var(--accent);color:var(--accent-ink);border:0;border-radius:4px;padding:.55rem 1.1rem;cursor:pointer;text-decoration:none;display:inline-block}
button.quiet,.btn.quiet{background:transparent;color:var(--ink);border:1px solid var(--line)}
button:focus-visible,.btn:focus-visible{outline:2px solid var(--ink);outline-offset:2px}
.error{background:var(--warn-bg);color:var(--warn);padding:.7rem 1rem;border-radius:4px;margin-bottom:1rem}
.meta{display:flex;flex-wrap:wrap;gap:.5rem 1rem;justify-content:space-between;align-items:center;margin-bottom:1rem}
h1{font-size:1.4rem;margin:0}
.sub{color:var(--muted);font-size:.9rem}
.actions{display:flex;gap:.5rem}
pre{margin:0;padding:1rem;overflow:auto;font:400 .9rem/1.55 "JetBrains Mono",monospace;tab-size:4}
.center{max-width:34rem;margin:3rem auto;padding:1.5rem}
.link{font:500 .9rem "JetBrains Mono",monospace;word-break:break-all;padding:.7rem;border:1px dashed var(--line);border-radius:4px;margin:1rem 0}
@media (prefers-reduced-motion:no-preference){button,.btn{transition:filter .12s}button:hover,.btn:hover{filter:brightness(1.1)}}
</style></head><body>
<header><a class="logo" href="/">scrapbin</a><span class="sub">Text in, link out.</span></header>
<main>{% block body %}{% endblock %}</main>
</body></html>"""

NEW = """{% extends "base.html" %}{% block body %}
{% if error %}<div class="error" role="alert">{{ error }}</div>{% endif %}
<form method="post" action="/new" class="panel">
<textarea name="content" placeholder="Paste text or code here" maxlength="{{ max_chars }}" required autofocus aria-label="Paste content"></textarea>
<div class="bar">
<input class="title" type="text" name="title" maxlength="120" placeholder="Title (optional)" aria-label="Title">
<select name="expiry" aria-label="Expires">
<option value="1h">Expires in 1 hour</option><option value="1d" selected>Expires in 1 day</option>
<option value="1w">Expires in 1 week</option><option value="never">Never expires</option></select>
<label><input type="checkbox" name="burn"> Delete after first view</label>
<button type="submit">Create paste</button>
</div></form>{% endblock %}"""

VIEW = """{% extends "base.html" %}{% block title %}{{ paste.title }} · scrapbin{% endblock %}{% block body %}
<div class="meta"><div><h1>{{ paste.title }}</h1>
<div class="sub">Created {{ paste.created_at.replace('T',' ') }} UTC ·
{% if burned %}Deleted now: this link no longer works{% elif paste.expires_at %}Expires {{ paste.expires_at.replace('T',' ') }} UTC{% else %}Never expires{% endif %}</div></div>
<div class="actions"><button class="quiet" id="copy" type="button">Copy text</button>
{% if not burned %}<a class="btn quiet" href="/raw/{{ paste.id }}">Raw</a>{% endif %}
<a class="btn" href="/">New paste</a></div></div>
<div class="panel"><pre id="body">{{ paste.content }}</pre></div>
<script>
document.getElementById('copy').onclick=async function(){
  try{await navigator.clipboard.writeText(document.getElementById('body').textContent);this.textContent='Copied'}
  catch(e){this.textContent='Copy failed'}
  setTimeout(()=>this.textContent='Copy text',1500)}
</script>{% endblock %}"""

BURN = """{% extends "base.html" %}{% block body %}
<div class="panel center"><h1>This paste deletes itself</h1>
<p class="sub">It will be removed as soon as you open it, and can't be viewed again.</p>
<form method="post" action="/p/{{ paste.id }}/reveal"><button type="submit">Open and delete</button></form></div>{% endblock %}"""

CREATED = """{% extends "base.html" %}{% block body %}
<div class="panel center"><h1>Paste created</h1>
<p class="sub">Share this link. It works once; opening it deletes the paste.</p>
<div class="link" id="l">{{ link }}</div>
<button id="c" type="button">Copy link</button> <a class="btn quiet" href="/">New paste</a></div>
<script>document.getElementById('c').onclick=async function(){
try{await navigator.clipboard.writeText(document.getElementById('l').textContent);this.textContent='Copied'}catch(e){this.textContent='Copy failed'}}</script>{% endblock %}"""

MISSING = """{% extends "base.html" %}{% block body %}
<div class="panel center"><h1>Paste not found</h1>
<p class="sub">It may have expired, been deleted after viewing, or the link is mistyped.</p>
<a class="btn" href="/">Create a new paste</a></div>{% endblock %}"""

app.jinja_loader = DictLoader({
    "base.html": BASE, "new.html": NEW, "view.html": VIEW,
    "burn.html": BURN, "created.html": CREATED, "missing.html": MISSING,
})

if __name__ == "__main__":
    app.run(debug=True)
