"""The local review page: watch each produced clip, edit its copy per platform, approve or reject.

Approving books the next free slots (postqueue.enqueue). Nothing reaches a platform without
this click. The server binds 127.0.0.1 only, checks the Host header (DNS rebinding) and needs
a per-run token on every POST, so other web pages cannot approve clips through the browser.
"""

import json
import mimetypes
import re
import secrets
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import unquote, urlsplit

from . import brands, postqueue as pq, postspec

POST_GLOB = "*/*.post.json"         # out/<brand>/<job>/<clip>.post.json


def awaiting(work: Path, db) -> List[Dict[str, Any]]:
    """Produced clips with no review decision yet and nothing queued."""
    queued = pq.queued_post_jsons(db)
    items = []
    for brand in brands.list_brands(work):
        for path in sorted((work / "out" / brand).glob(POST_GLOB)):
            rel = str(path.relative_to(work))
            try:
                post = json.loads(path.read_text())
            except json.JSONDecodeError as exc:
                items.append({"post_json": rel, "brand": brand, "error": f"invalid JSON: {exc}"})
                continue
            if rel in queued or (post.get("review") or {}).get("status") in ("approved", "rejected"):
                continue
            try:
                accounts = brands.load_accounts(work / "brands" / brand / "accounts.json")
                enabled = [p for p in brands.PLATFORMS if p in accounts["platforms"]]
                audited = {p: bool(accounts["platforms"][p].get("audited")) for p in enabled}
            except brands.BrandError as exc:
                enabled, audited = [], {}
                post["error"] = str(exc)
            items.append({"post_json": rel, "brand": brand, "post": post, "platforms": enabled, "audited": audited})
    return items


def approve(work: Path, db, rel: str, platforms: List[str], copy: Dict[str, Any]) -> Dict[str, str]:
    path = _post_path(work, rel)
    post = json.loads(path.read_text())
    accounts = brands.load_accounts(work / "brands" / post["brand"] / "accounts.json")
    unknown = [p for p in platforms if p not in accounts["platforms"]]
    if unknown:
        raise ValueError(f"{post['brand']} has no account on {', '.join(unknown)}")
    for p, fields in copy.items():
        if p in post["platforms"]:
            post["platforms"][p].update({k: v for k, v in fields.items() if k in ("title", "description", "tags", "caption")})
    missing = [p for p in platforms if p not in post["platforms"]]
    if missing:
        raise ValueError(f"no copy written for {', '.join(missing)}")
    postspec.validate(post, rel)
    slots = pq.enqueue(db, post["brand"], rel, accounts, platforms)
    post["review"] = {"status": "approved", "at": pq.iso(pq.now_utc()), "platforms": platforms}
    path.write_text(json.dumps(post, indent=2, ensure_ascii=False) + "\n")
    return slots


def reject(work: Path, rel: str, reason: str) -> None:
    path = _post_path(work, rel)
    post = json.loads(path.read_text())
    post["review"] = {"status": "rejected", "at": pq.iso(pq.now_utc()), "reason": reason[:500]}
    path.write_text(json.dumps(post, indent=2, ensure_ascii=False) + "\n")


def _post_path(work: Path, rel: str) -> Path:
    path = (work / rel).resolve()
    if not (path.name.endswith(".post.json") and path.is_relative_to((work / "out").resolve()) and path.is_file()):
        raise ValueError(f"not a post.json under out/: {rel}")
    return path


def serve(work: Path, db_path: Path, port: int = 8790, open_browser: bool = True) -> None:
    token = secrets.token_urlsafe(24)
    out_root = (work / "out").resolve()
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, body: bytes, ctype: str = "application/json", extra=None):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, status: int, data: Any):
            self._send(status, json.dumps(data, ensure_ascii=False).encode())

        def _host_ok(self) -> bool:
            if self.headers.get("Host") not in allowed_hosts:
                self._send(403, b"bad host", "text/plain")
                return False
            return True

        def do_GET(self):  # noqa: N802
            if not self._host_ok():
                return
            path = urlsplit(self.path).path
            db = pq.connect(db_path)
            if path == "/":
                self._send(200, PAGE.replace("__TOKEN__", token).encode(), "text/html; charset=utf-8")
            elif path == "/api/state":
                self._json(200, {"awaiting": awaiting(work, db), "queue": pq.rows(db)})
            elif path.startswith("/media/"):
                self._media(unquote(path[len("/media/"):]))
            else:
                self._send(404, b"not found", "text/plain")

        do_HEAD = do_GET

        def _media(self, rel: str):
            file = (work / rel).resolve()
            if not (file.is_relative_to(out_root) and file.is_file() and file.suffix == ".mp4"):
                self._send(404, b"not found", "text/plain")
                return
            size = file.stat().st_size
            m = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
            ctype = mimetypes.guess_type(file.name)[0] or "video/mp4"
            if not m:
                self._send(200, file.read_bytes(), ctype, {"Accept-Ranges": "bytes"})
                return
            start = int(m.group(1) or 0)
            end = min(int(m.group(2)) if m.group(2) else size - 1, size - 1)
            with file.open("rb") as fh:
                fh.seek(start)
                chunk = fh.read(end - start + 1)
            self._send(206, chunk, ctype, {"Accept-Ranges": "bytes", "Content-Range": f"bytes {start}-{end}/{size}"})

        def do_POST(self):  # noqa: N802
            if not self._host_ok():
                return
            if not secrets.compare_digest(self.headers.get("X-Clipwright-Token", ""), token):
                self._json(403, {"error": "bad token: reload the page"})
                return
            try:
                data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                db = pq.connect(db_path)
                path = urlsplit(self.path).path
                if path == "/api/approve":
                    self._json(200, {"slots": approve(work, db, data["post_json"], data["platforms"], data.get("copy", {}))})
                elif path == "/api/reject":
                    reject(work, data["post_json"], data.get("reason", ""))
                    self._json(200, {"ok": True})
                elif path == "/api/retry":
                    pq.retry(db, int(data["id"]))
                    self._json(200, {"ok": True})
                elif path == "/api/cancel":
                    pq.cancel(db, int(data["id"]))
                    self._json(200, {"ok": True})
                else:
                    self._json(404, {"error": "unknown action"})
            except (ValueError, KeyError, pq.QueueError, postspec.PostError, brands.BrandError) as exc:
                self._json(400, {"error": str(exc)})

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"Review page: {url}  (Ctrl+C to stop)")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Clipwright Review</title>
<style>
:root{--bg:#f6f5f2;--card:#fff;--ink:#1a1a1a;--mute:#666;--line:#e3e1dc;--accent:#c79a00;--ok:#1e7d3a;--bad:#b3261e}
@media (prefers-color-scheme:dark){:root{--bg:#141414;--card:#1e1e1e;--ink:#eee;--mute:#999;--line:#333;--accent:#ffd400;--ok:#5ccf7d;--bad:#ff7b72}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 system-ui,sans-serif}
main{max-width:1100px;margin:0 auto;padding:16px}h1{font-size:20px;margin:8px 0 16px}h2{font-size:16px;margin:28px 0 10px}
.clip{display:grid;grid-template-columns:240px 1fr;gap:16px;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px;margin-bottom:16px}
@media (max-width:700px){.clip{grid-template-columns:1fr}}
video{width:100%;border-radius:8px;background:#000;aspect-ratio:9/16}
.meta{color:var(--mute);font-size:13px;margin-bottom:8px;word-break:break-all}
fieldset{border:1px solid var(--line);border-radius:8px;margin:0 0 10px;padding:8px 10px}legend{font-weight:600;font-size:13px}
label.pf{font-weight:600;display:flex;gap:6px;align-items:center}
input[type=text],textarea{width:100%;font:inherit;font-size:14px;padding:6px 8px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--ink)}
textarea{min-height:84px;resize:vertical}.count{font-size:12px;color:var(--mute);text-align:right}.count.over{color:var(--bad)}
.note{font-size:12px;color:var(--accent)}button{font:inherit;padding:7px 14px;border-radius:6px;border:1px solid var(--line);background:var(--card);color:var(--ink);cursor:pointer}
button.go{background:var(--ok);color:#fff;border-color:var(--ok)}button.no{color:var(--bad)}
.actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:6px}.err{color:var(--bad);white-space:pre-wrap;font-size:13px}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:10px;font-size:13px}
th,td{padding:6px 8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}.s-failed{color:var(--bad)}.s-posted,.s-scheduled{color:var(--ok)}
.scroll{overflow-x:auto}.empty{color:var(--mute)}
</style></head><body><main>
<h1>Clipwright review</h1>
<div id="awaiting"></div>
<h2>Queue</h2><div class="scroll"><table id="queue"></table></div>
</main><script>
const TOKEN="__TOKEN__";
const LIMITS={youtube:{title:100,description:5000},tiktok:{caption:2200},facebook:{caption:63206},instagram:{caption:2200}};
const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const fmt=iso=>iso?new Date(iso).toLocaleString([], {weekday:"short",month:"short",day:"numeric",hour:"2-digit",minute:"2-digit"}):"";
async function post(path,body){const r=await fetch(path,{method:"POST",headers:{"Content-Type":"application/json","X-Clipwright-Token":TOKEN},body:JSON.stringify(body)});const j=await r.json();if(!r.ok)throw new Error(j.error||r.status);return j}
function field(pf,name,value,multi){const lim=(LIMITS[pf]||{})[name];const id=`${pf}-${name}-${Math.random().toString(36).slice(2)}`;
 const input=multi?`<textarea data-pf="${pf}" data-k="${name}" id="${id}">${esc(value)}</textarea>`:`<input type="text" data-pf="${pf}" data-k="${name}" id="${id}" value="${esc(value)}">`;
 return `<div>${input}${lim?`<div class="count" data-for="${id}" data-lim="${lim}"></div>`:""}</div>`}
function card(item){
 if(item.error) return `<div class="clip"><div></div><div><div class="meta">${esc(item.post_json)}</div><div class="err">${esc(item.error)}</div></div></div>`;
 const p=item.post;let sets="";
 for(const pf of item.platforms){const c=p.platforms[pf];const has=!!c;const cc=c||{};
  const note=(pf==="youtube"||pf==="tiktok")&&!item.audited[pf]?`<div class="note">private until the ${pf==="youtube"?"YouTube API audit":"TikTok app audit"} passes</div>`:"";
  let inner=pf==="youtube"?field(pf,"title",cc.title,false)+field(pf,"description",cc.description,true)+field(pf,"tags",(cc.tags||[]).join(", "),false):field(pf,"caption",cc.caption,true);
  sets+=`<fieldset><legend><label class="pf"><input type="checkbox" data-plat="${pf}" ${has?"checked":"disabled"}> ${pf}${has?"":" (no copy written)"}</label></legend>${has?inner:""}${note}</fieldset>`}
 return `<div class="clip" data-post="${esc(item.post_json)}"><video src="/media/${encodeURI(p.file)}#t=0.5" controls preload="metadata" playsinline></video>
 <div><div class="meta"><b>${esc(item.brand)}</b> · ${esc(p.duration)}s · <a href="${esc(p.source_url)}" target="_blank" rel="noopener">source</a><br>${esc(p.credit)}</div>${sets}
 <div class="actions"><button class="go" data-act="approve">Approve and schedule</button><button class="no" data-act="reject">Reject</button></div><div class="err"></div></div></div>`}
function counts(){document.querySelectorAll(".count").forEach(el=>{const v=document.getElementById(el.dataset.for).value.length;el.textContent=`${v} / ${el.dataset.lim}`;el.classList.toggle("over",v>+el.dataset.lim)})}
async function load(){const s=await (await fetch("/api/state")).json();
 document.getElementById("awaiting").innerHTML=s.awaiting.length?s.awaiting.map(card).join(""):`<p class="empty">Nothing waiting for review.</p>`;
 const q=s.queue;document.getElementById("queue").innerHTML=q.length?`<tr><th>#</th><th>Brand</th><th>Platform</th><th>Clip</th><th>Slot</th><th>Status</th><th></th></tr>`+q.map(r=>`<tr><td>${r.id}</td><td>${esc(r.brand)}</td><td>${esc(r.platform)}</td><td>${esc(r.post_json.split("/").slice(-2).join("/"))}</td><td>${fmt(r.slot_at)}</td><td class="s-${r.status}">${esc(r.status)}${r.url?` · <a href="${esc(r.url)}" target="_blank" rel="noopener">open</a>`:""}${r.last_error?`<div class="err">${esc(r.last_error)}</div>`:""}</td><td>${r.status==="failed"?`<button data-retry="${r.id}">Retry</button> `:""}${["pending","failed"].includes(r.status)?`<button data-cancel="${r.id}">Cancel</button>`:""}</td></tr>`).join(""):`<tr><td class="empty">Queue is empty.</td></tr>`;
 counts()}
document.addEventListener("input",counts);
document.addEventListener("click",async e=>{const b=e.target.closest("button");if(!b)return;
 try{if(b.dataset.retry){await post("/api/retry",{id:b.dataset.retry});return load()}
  if(b.dataset.cancel){if(!confirm("Remove this post from the queue?"))return;await post("/api/cancel",{id:b.dataset.cancel});return load()}
  const box=b.closest(".clip");const rel=box.dataset.post;const err=box.querySelector(".err");err.textContent="";
  if(b.dataset.act==="reject"){const reason=prompt("Why reject? (kept in post.json)","")??null;if(reason===null)return;await post("/api/reject",{post_json:rel,reason});return load()}
  const platforms=[...box.querySelectorAll("input[data-plat]:checked")].map(i=>i.dataset.plat);const copy={};
  box.querySelectorAll("[data-pf]").forEach(el=>{const pf=el.dataset.pf;copy[pf]=copy[pf]||{};copy[pf][el.dataset.k]=el.dataset.k==="tags"?el.value.split(",").map(t=>t.trim()).filter(Boolean):el.value});
  b.disabled=true;const r=await post("/api/approve",{post_json:rel,platforms,copy});
  alert("Scheduled:\n"+Object.entries(r.slots).map(([p,t])=>`${p}: ${fmt(t)}`).join("\n"));load()}
 catch(x){(b.closest(".clip")?.querySelector(".err")||{}).textContent=x.message;b.disabled=false}});
load();
</script></body></html>
"""
