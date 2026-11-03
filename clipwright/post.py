"""`./post`: the autopilot commands that run on the host (not in the render container).

  produce [--brand B]           next idea per brand -> clips + post.json (headless Claude Code)
  review [--port N]             local page: watch, edit copy, approve or reject
  publish-due [--dry-run]       upload whatever is due (the 15-minute timer runs this)
  queue [--brand B]             list queued posts
  retry ID | cancel ID          after checking a failed post on the platform
  connect BRAND PROVIDER        OAuth for google | tiktok | meta, tokens into secrets/BRAND/
  discover QUERY...             ranked YouTube sources for an idea, as JSON
  words VIDEO_ID --from S --to S    word timings from the transcript cache, for exact cuts
  strip-music VIDEO_ID          Demucs: keep the voice, drop the source's music (Content ID)
  validate POST_JSON...         check post.json files
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path

from . import brands, discover, postqueue as pq, postspec, produce, review

WORK = Path(__file__).resolve().parent.parent
DB = WORK / "queue.db"
IMAGE = "clipwright-runtime:latest"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="post", description="Clipwright autopilot: produce, review, publish")
    sub = p.add_subparsers(dest="cmd", required=True)
    pr = sub.add_parser("produce", help="turn the next idea per brand into clips (headless Claude Code)")
    pr.add_argument("--brand", action="append", help="only this brand (repeatable); default every brand")
    pr.add_argument("--max-clips", type=int, default=1)
    rv = sub.add_parser("review", help="open the local review page")
    rv.add_argument("--port", type=int, default=8790)
    rv.add_argument("--no-browser", action="store_true")
    pd = sub.add_parser("publish-due", help="upload posts that are due")
    pd.add_argument("--dry-run", action="store_true", help="print what would upload; change nothing")
    q = sub.add_parser("queue", help="list queued posts")
    q.add_argument("--brand")
    for name in ("retry", "cancel"):
        sub.add_parser(name, help=f"{name} a queued post by id").add_argument("id", type=int)
    c = sub.add_parser("connect", help="authorise a brand's account (google = YouTube, meta = Facebook + Instagram)")
    c.add_argument("brand")
    c.add_argument("provider", choices=["google", "tiktok", "meta"])
    d = sub.add_parser("discover", help="ranked YouTube sources for an idea")
    d.add_argument("queries", nargs="+")
    d.add_argument("-n", type=int, default=10, help="results per query")
    d.add_argument("--top", type=int, default=8)
    w = sub.add_parser("words", help="word timings (seconds) from a fetched video's transcript")
    w.add_argument("video_id")
    w.add_argument("--from", dest="start", type=float, required=True)
    w.add_argument("--to", dest="end", type=float, required=True)
    sm = sub.add_parser("strip-music", help="replace a fetched source's audio with its Demucs vocal stem")
    sm.add_argument("video_id")
    v = sub.add_parser("validate", help="check post.json files")
    v.add_argument("paths", nargs="+")
    return p


def _cache_dir(video_id: str) -> Path:
    safe = "".join(ch for ch in video_id if ch.isalnum() or ch in "_-")
    d = WORK / "tmp" / "youtube-cache" / safe
    if not (d / "full-1080.mp4").exists():
        raise SystemExit(f"{video_id} is not fetched yet: run ./clip fetch first")
    return d


def words(args) -> None:
    data = json.loads((_cache_dir(args.video_id) / "full-1080.transcript_cache.json").read_text())
    picked = [w for w in data["words"] if args.start * 1000 <= w["start"] <= args.end * 1000]
    print(" ".join(f"{w['text'].strip()}@{w['start'] / 1000:.2f}-{w['end'] / 1000:.2f}" for w in picked))


def strip_music(args) -> None:
    """Keep the voice only. The cache is written by the container as root, so the swap runs there too."""
    d = _cache_dir(args.video_id)
    vid = d.name
    source = d / "full-1080.orig.mp4" if (d / "full-1080.orig.mp4").exists() else d / "full-1080.mp4"
    demucs = os.environ.get("DEMUCS", str(WORK / "tmp/demucs-env/.venv/bin/demucs"))
    if not Path(demucs).exists():
        raise SystemExit(f"demucs not found at {demucs}: set DEMUCS or install it into tmp/demucs-env (README)")
    sep = WORK / "tmp" / "sep"
    sep.mkdir(parents=True, exist_ok=True)
    wav = sep / f"{vid}.wav"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(source), "-vn", "-ac", "2", "-ar", "44100", str(wav)],
                   check=True)
    subprocess.run([demucs, "--two-stems", "vocals", "-o", str(sep / "out"), str(wav)], check=True,
                   stdout=subprocess.DEVNULL)
    rel = f"tmp/youtube-cache/{vid}"
    script = (f"set -e; cd /work; [ -f {rel}/full-1080.orig.mp4 ] || mv {rel}/full-1080.mp4 {rel}/full-1080.orig.mp4; "
              f"ffmpeg -loglevel error -y -i {rel}/full-1080.orig.mp4 -i tmp/sep/out/htdemucs/{vid}/vocals.wav "
              f"-map 0:v -map 1:a -c:v copy -c:a aac -b:a 192k -shortest {rel}/full-1080.mp4; "
              f"rm -rf jobs/{vid}/pass1")
    subprocess.run(["docker", "run", "--rm", "--entrypoint", "bash", "-v", f"{WORK}:/work", IMAGE, "-c", script],
                   check=True)
    wav.unlink(missing_ok=True)
    print(f"{vid}: music removed (original kept as {rel}/full-1080.orig.mp4). Render with --no-music.")


def notify(title: str, body: str) -> None:
    if shutil.which("notify-send"):
        subprocess.run(["notify-send", "-a", "Clipwright", title, body], check=False)


def main(argv=None) -> None:
    args = build_parser().parse_args(argv)
    try:
        if args.cmd == "produce":
            names = args.brand or brands.list_brands(WORK)
            if not names:
                raise SystemExit("no brands: create brands/<name>/ with brand.json, accounts.json and ideas.md")
            made = 0
            for name in names:
                out = produce.produce_brand(WORK, name, max_clips=args.max_clips)
                made += len(out["posts"]) if out else 0
                if out and out["status"] != "done":
                    notify(f"{name}: idea failed", out["note"])
            if made:
                notify("Clips ready for review", f"{made} new clip(s): run ./post review")
        elif args.cmd == "review":
            review.serve(WORK, DB, args.port, not args.no_browser)
        elif args.cmd == "publish-due":
            from .publish import run_due
            report = run_due(WORK, pq.connect(DB), dry_run=args.dry_run)
            failed = [r for r in report if r["outcome"] == "failed"]
            if failed:
                notify(f"{len(failed)} post(s) failed",
                       "\n".join(f"{r['brand']}/{r['platform']}: {r.get('error', '')[:120]}" for r in failed))
        elif args.cmd == "queue":
            where, params = ("brand = ?", (args.brand,)) if args.brand else ("1", ())
            for r in pq.rows(pq.connect(DB), where, params):
                print(f"#{r['id']:<4} {r['brand']:<14} {r['platform']:<10} {r['slot_at']}  {r['status']:<10} "
                      f"{r['url'] or ''} {r['last_error'] or ''}".rstrip())
        elif args.cmd == "retry":
            pq.retry(pq.connect(DB), args.id)
        elif args.cmd == "cancel":
            pq.cancel(pq.connect(DB), args.id)
        elif args.cmd == "connect":
            from .publish import auth
            from .publish.http import urllib_transport
            tok = auth.connect(WORK / "secrets", args.brand, args.provider, urllib_transport, webbrowser.open)
            label = {"google": lambda t: f"YouTube channel {(t.get('channel') or {}).get('title')}",
                     "tiktok": lambda t: f"TikTok account {t.get('open_id')}",
                     "meta": lambda t: "Pages " + ", ".join(f"{p['name']} ({i}, IG {p['ig_user_id']})"
                                                             for i, p in t["pages"].items())}[args.provider](tok)
            print(f"{args.brand}: connected {label}")
        elif args.cmd == "discover":
            print(json.dumps(discover.discover(args.queries, args.n, args.top), indent=2, ensure_ascii=False))
        elif args.cmd == "words":
            words(args)
        elif args.cmd == "strip-music":
            strip_music(args)
        elif args.cmd == "validate":
            for path in args.paths:
                postspec.load(Path(path))
                print(f"ok  {path}")
    except (brands.BrandError, postspec.PostError, pq.QueueError) as exc:
        sys.exit(str(exc))
    except Exception as exc:
        if exc.__class__.__name__ == "AuthError":
            sys.exit(str(exc))
        raise


if __name__ == "__main__":
    main()
