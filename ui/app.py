# /// script
# requires-python = ">=3.11"
# dependencies = ["fastapi", "uvicorn", "jinja2", "python-multipart"]
# ///
"""Clipwright review UI: find sources, verify them, review clips, edit posts, track status.

Local only (127.0.0.1, no login). Run with ./clip-ui. State lives in tracker/state.json and
jobs/<job>/post_edits.json; anything that needs Docker (searching, packaging) runs ./clip.
static/htmx.min.js is htmx 2.0.4 from unpkg, sha256 e209dda5c8235479f3166defc7750e1dbcd5a5c1808b7792fc2e6733768fb447.
"""

import json
import re
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from clipwright import domains, gate, package, tracker  # noqa: E402

JOB = re.compile(r"^[\w\-]+$")
PART = re.compile(r"^[\w.\-]+$")
MEDIA_TYPES = {".mp4": "video/mp4", ".jpg": "image/jpeg"}
UI_STATUSES = ("found", "approved", "rejected")  # the rest are derived from files on disk
PORT = 8770

Runner = Callable[[List[str]], Dict[str, Any]]


def make_runner(root: Path) -> Runner:
    def run(args: List[str]) -> Dict[str, Any]:
        proc = subprocess.run([str(root / "clip"), *args], capture_output=True, text=True, cwd=root)
        return {"code": proc.returncode, "output": (proc.stdout + proc.stderr).strip()}
    return run


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _hours(seconds: Optional[int]) -> str:
    return "?" if seconds is None else f"{seconds // 3600}:{seconds % 3600 // 60:02d}"


def create_app(root: Path = ROOT, runner: Optional[Runner] = None) -> FastAPI:
    root = Path(root)
    run = runner or make_runner(root)
    tracker_path = root / "tracker" / "state.json"
    lock = threading.RLock()
    search = {"running": False, "domain": None, "result": None, "notified": True}

    app = FastAPI(title="Clipwright review")
    app.state.search_thread = None
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    templates = Jinja2Templates(directory=str(HERE / "templates"))
    templates.env.filters["hours"] = _hours
    templates.env.filters["number"] = lambda v: "?" if v is None else f"{v:,}"

    def render(request: Request, name: str, status_code: int = 200, **context: Any) -> HTMLResponse:
        return templates.TemplateResponse(request, name, context, status_code=status_code)

    # -- helpers ---------------------------------------------------------
    def domain_names() -> List[str]:
        return domains.list_packs(root / "domains")

    def need_domain(name: str) -> str:
        if name not in domain_names():
            raise HTTPException(404, f"unknown domain {name!r}")
        return name

    def need_job(job: str) -> str:
        if not JOB.match(job) or not (root / "out" / job / "manifest.json").exists():
            raise HTTPException(404, f"no rendered clips for {job!r}")
        return job

    def read_json(path: Path, default: Any) -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return default

    def segments_of(job: str) -> List[Dict[str, Any]]:
        raw = read_json(root / "jobs" / job / "segments.json", [])
        if isinstance(raw, dict):
            raw = raw.get("most_relevant_segments") or raw.get("segments") or []
        return raw

    def manifest_of(job: str) -> List[Dict[str, Any]]:
        return read_json(root / "out" / job / "manifest.json", [])

    def clip_number(entry: Dict[str, Any]) -> int:
        return int(Path(entry["file"]).name[:2])

    def load_state() -> Dict[str, Any]:
        return tracker.load(tracker_path)

    def sync(state: Dict[str, Any]) -> None:
        facts: Dict[str, Dict[str, Any]] = {}
        for video_id in state["sources"]:
            clips = manifest_of(video_id) if JOB.match(video_id) else []
            marks = [state["clips"].get(f"{video_id}/{clip_number(c):02d}", {}).get("mark") for c in clips]
            facts[video_id] = {"fetched": (root / "jobs" / video_id / "state.json").exists(), "clips": len(clips),
                               "verified": bool(clips) and all(m == "ok" for m in marks)}
        tracker.sync_statuses(state, facts)

    def source_rows(domain: str) -> List[Dict[str, Any]]:
        cands = read_json(root / "sources" / f"{domain}.json", [])
        with lock:
            state = load_state()
            for c in cands:
                tracker.upsert_source(state, c, domain, _now())
            sync(state)
            tracker.save(tracker_path, state)
        return [state["sources"][c["id"]] for c in cands]

    def clip_view(job: str, entry: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
        n = clip_number(entry)
        segments = segments_of(job)
        segment = segments[n - 1] if 1 <= n <= len(segments) else {}
        job_state = read_json(root / "jobs" / job / "state.json", {})
        pack = domains.load_pack(job_state["domain"], root / "domains") if job_state.get("domain") in domain_names() else None
        edits = read_json(root / "jobs" / job / "post_edits.json", {}).get(str(n))
        merged = package.merge_edits(segment, edits)
        covers = {}
        for folder in sorted((root / "out" / job / "upload").glob(f"{n:02d}_*")):
            for letter in package.COVER_LETTERS:
                if (folder / f"cover_{letter}.jpg").exists():
                    covers[letter] = f"/media/{job}/upload/{folder.name}/cover_{letter}.jpg"
        return {
            "job": job, "n": n, "file": Path(entry["file"]).name, "hook_title": entry.get("hook_title"),
            "domain": job_state.get("domain"), "verification": segment.get("verification"),
            "commentary": segment.get("commentary"), "gate_problems": gate.check_segment(pack, segment, n),
            "post": {"title": merged.get("title", ""), "description": merged.get("description", ""),
                     "hashtags": " ".join(merged["hashtags"]) if isinstance(merged.get("hashtags"), list) else "",
                     "cover": merged.get("cover", "a")},
            "post_problems": package.check_post(merged, n), "covers": covers,
            "mark": state["clips"].get(f"{job}/{n:02d}", {}).get("mark"),
            "note": state["clips"].get(f"{job}/{n:02d}", {}).get("note", ""),
        }

    def clip_response(request: Request, job: str, n: int, status_code: int = 200) -> HTMLResponse:
        entry = next((e for e in manifest_of(job) if clip_number(e) == n), None)
        if entry is None:
            raise HTTPException(404, f"no clip {n} in {job}")
        return render(request, "_clip.html", status_code, c=clip_view(job, entry, load_state()))

    # -- pages -----------------------------------------------------------
    @app.get("/")
    def home() -> RedirectResponse:
        return RedirectResponse("/sources")

    @app.get("/sources", response_class=HTMLResponse)
    def sources_page(request: Request, domain: str = "tech") -> HTMLResponse:
        need_domain(domain)
        return render(request, "sources.html", domain=domain, domains=domain_names(), rows=source_rows(domain),
                      statuses=UI_STATUSES, permissions=tracker.PERMISSIONS, search=dict(search))

    @app.post("/sources/search", response_class=HTMLResponse)
    def start_search(request: Request, domain: str = Form(...)) -> HTMLResponse:
        need_domain(domain)
        with lock:
            if search["running"]:
                return render(request, "_search_status.html", 409, search=dict(search), busy=True)
            search.update(running=True, domain=domain, result=None, notified=False)

        def work() -> None:
            try:
                result = run(["sources", domain])
            except Exception as exc:  # the thread must always finish the search
                result = {"code": 1, "output": f"could not run clip sources: {exc}"}
            with lock:
                search.update(running=False, result=result)

        thread = threading.Thread(target=work, daemon=True)
        app.state.search_thread = thread
        thread.start()
        return render(request, "_search_status.html", search=dict(search), busy=False)

    @app.get("/sources/search/status", response_class=HTMLResponse)
    def search_status(request: Request) -> HTMLResponse:
        with lock:
            snapshot = dict(search)
            first_done = not search["running"] and not search["notified"]
            if first_done:
                search["notified"] = True
        response = render(request, "_search_status.html", search=snapshot, busy=False)
        if first_done:
            response.headers["HX-Refresh"] = "true"  # the list on the page is now out of date
        return response

    @app.post("/sources/{video_id}", response_class=HTMLResponse)
    def update_source(request: Request, video_id: str, status: str = Form(""), permission: str = Form(""),
                      note: Optional[str] = Form(None)) -> HTMLResponse:
        if status and status not in UI_STATUSES:
            raise HTTPException(400, f"status must be one of {', '.join(UI_STATUSES)} (the others follow from your files)")
        with lock:
            state = load_state()
            if video_id not in state["sources"]:
                raise HTTPException(404, f"unknown source {video_id!r}")
            try:
                row = tracker.set_source(state, video_id, status=status or None, permission=permission or None,
                                         note=note, now=_now())
            except tracker.TrackerError as exc:
                raise HTTPException(400, str(exc)) from None
            tracker.save(tracker_path, state)
        return render(request, "_row.html", r=row, statuses=UI_STATUSES, permissions=tracker.PERMISSIONS)

    @app.get("/sources/{domain}/commands", response_class=HTMLResponse)
    def fetch_commands(request: Request, domain: str) -> HTMLResponse:
        need_domain(domain)
        state = load_state()
        lines = [f"./clip fetch --domain {domain} {r['url']}" for r in state["sources"].values()
                 if r.get("domain") == domain and r.get("status") == "approved"]
        return render(request, "_commands.html", lines=lines)

    @app.get("/clips", response_class=HTMLResponse)
    def clips_page(request: Request) -> HTMLResponse:
        with lock:
            state = load_state()
            sync(state)
            tracker.save(tracker_path, state)
        jobs = []
        for manifest in sorted((root / "out").glob("*/manifest.json")):
            job = manifest.parent.name
            if JOB.match(job):
                jobs.append({"job": job, "clips": [clip_view(job, e, state) for e in manifest_of(job)]})
        return render(request, "clips.html", jobs=jobs)

    @app.post("/clips/{job}/{n}/mark", response_class=HTMLResponse)
    def mark_clip(request: Request, job: str, n: int, mark: str = Form(...), note: str = Form("")) -> HTMLResponse:
        need_job(job)
        if not any(clip_number(e) == n for e in manifest_of(job)):
            raise HTTPException(404, f"no clip {n} in {job}")
        with lock:
            state = load_state()
            try:
                tracker.set_clip(state, job, n, mark=mark, note=note, now=_now())
            except tracker.TrackerError as exc:
                raise HTTPException(400, str(exc)) from None
            sync(state)
            tracker.save(tracker_path, state)
        return clip_response(request, job, n)

    @app.post("/clips/{job}/{n}/post", response_class=HTMLResponse)
    def edit_post(request: Request, job: str, n: int, title: str = Form(""), description: str = Form(""),
                  hashtags: str = Form(""), cover: str = Form("a")) -> HTMLResponse:
        need_job(job)
        if not any(clip_number(e) == n for e in manifest_of(job)):
            raise HTTPException(404, f"no clip {n} in {job}")
        path = root / "jobs" / job / "post_edits.json"
        with lock:
            edits = read_json(path, {})
            edits[str(n)] = {"title": title, "description": description,
                             "hashtags": [t for t in re.split(r"[,\s]+", hashtags.strip()) if t],
                             "cover": cover if cover in package.COVER_LETTERS else "a"}
            tracker.save(path, edits)  # atomic JSON write, nothing tracker-specific about it
        return clip_response(request, job, n)

    @app.post("/clips/{job}/package", response_class=HTMLResponse)
    def build_package(request: Request, job: str) -> HTMLResponse:
        need_job(job)
        state = load_state()
        unmarked = [clip_number(e) for e in manifest_of(job)
                    if state["clips"].get(f"{job}/{clip_number(e):02d}", {}).get("mark") != "ok"]
        if unmarked:
            return render(request, "_package_result.html", 409, unmarked=unmarked, result=None)
        return render(request, "_package_result.html", unmarked=[], result=run(["package", job]))

    @app.get("/media/{path:path}")
    def media(path: str) -> Response:
        parts = path.split("/")
        suffix = Path(parts[-1]).suffix.lower()
        if suffix not in MEDIA_TYPES or not all(PART.match(p) and not p.startswith(".") for p in parts):
            raise HTTPException(404)
        base = (root / "out").resolve()
        target = (base / path).resolve()
        if base not in target.parents or not target.is_file():
            raise HTTPException(404)
        return FileResponse(target, media_type=MEDIA_TYPES[suffix])

    return app


if __name__ == "__main__":
    import uvicorn

    print(f"Clipwright review UI: http://127.0.0.1:{PORT}/")
    uvicorn.run(create_app(ROOT), host="127.0.0.1", port=PORT, log_level="warning")
