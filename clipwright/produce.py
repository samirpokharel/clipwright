"""Turn the next idea in each brand's ideas.md into reviewed-ready clips with a headless
Claude Code run (`claude -p`), then tick or flag the idea.

Claude Code does the judgement (source choice, cut points, layout, copy) following the
"Produce from an idea" section of skill/SKILL.md, and writes a small result file that this
module reads. Its tools are limited to the commands this pipeline needs (ALLOWED_TOOLS).
"""

import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from . import brands, postspec

ALLOWED_TOOLS = [
    "Read", "Glob", "Grep",
    "Write(jobs/**)", "Edit(jobs/**)", "Write(out/**)", "Edit(out/**)",
    "Bash(./clip fetch:*)", "Bash(./clip frames:*)", "Bash(./clip render:*)", "Bash(./clip schema:*)",
    "Bash(./clip profiles:*)",
    "Bash(./post discover:*)", "Bash(./post words:*)", "Bash(./post strip-music:*)", "Bash(./post validate:*)",
    "Bash(yt-dlp --skip-download:*)", "Bash(ffprobe:*)", "Bash(ffmpeg -loglevel error -y -ss:*)",
]
TIMEOUT = 3 * 3600

PROMPT = """You are running unattended as the Clipwright producer for the brand "{brand}".
Idea: "{idea}"

Follow the "Produce from an idea" section of skill/SKILL.md exactly. Brand files:
brands/{brand}/brand.json (look) and brands/{brand}/accounts.json (platforms, hashtags {hashtags}).
Make at most {max_clips} clip(s). Render with --brand {brand}. Write one
out/{brand}/<job>/<clip>.post.json per clip and check each with ./post validate.

Finish by writing {result} as JSON:
  {{"status": "done", "posts": ["out/{brand}/<job>/<clip>.post.json", ...], "note": "<one line>"}}
or, if no source is good enough or a step fails,
  {{"status": "failed", "posts": [], "note": "<why, one line>"}}
Do not post or upload anything. A human reviews every clip before it is published.
"""


def build_prompt(brand: str, idea: str, accounts: Dict[str, Any], result: str, max_clips: int = 1) -> str:
    return PROMPT.format(brand=brand, idea=idea, result=result, max_clips=max_clips,
                         hashtags=" ".join(accounts.get("hashtags", [])) or "(none)")


def claude_command(prompt: str) -> List[str]:
    return ["claude", "-p", prompt, "--output-format", "json", "--allowedTools", *ALLOWED_TOOLS]


def read_result(work: Path, result: Path) -> Dict[str, Any]:
    """The producer's result, with every listed post.json validated. Missing or bad -> failed."""
    if not result.exists():
        return {"status": "failed", "posts": [], "note": "producer wrote no result file"}
    try:
        data = json.loads(result.read_text())
    except json.JSONDecodeError as exc:
        return {"status": "failed", "posts": [], "note": f"result file is not JSON: {exc}"}
    if data.get("status") != "done":
        return {"status": "failed", "posts": [], "note": str(data.get("note") or "producer reported failure")}
    good, problems = [], []
    for rel in data.get("posts") or []:
        try:
            postspec.load(work / rel)
            good.append(rel)
        except (OSError, postspec.PostError) as exc:
            problems.append(str(exc).splitlines()[0])
    if not good:
        return {"status": "failed", "posts": [], "note": "; ".join(problems) or "no posts listed"}
    return {"status": "done", "posts": good, "note": str(data.get("note") or "")}


def produce_brand(work: Path, brand: str, runner: Callable = subprocess.run, log: Callable = print,
                  max_clips: int = 1) -> Optional[Dict[str, Any]]:
    ideas = work / "brands" / brand / "ideas.md"
    idea = brands.next_idea(ideas)
    if not idea:
        log(f"{brand}: no waiting ideas")
        return None
    accounts = brands.load_accounts(work / "brands" / brand / "accounts.json")
    run_dir = work / "jobs" / "_produce"
    run_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    result = run_dir / f"{brand}-{stamp}.json"
    log_file = run_dir / f"{brand}-{stamp}.log"
    log(f"{brand}: producing {idea!r} (log {log_file.relative_to(work)})")
    if shutil.which("claude") is None and runner is subprocess.run:
        raise RuntimeError("the claude CLI is not on PATH")
    prompt = build_prompt(brand, idea, accounts, str(result.relative_to(work)), max_clips)
    try:
        proc = runner(claude_command(prompt), cwd=str(work), capture_output=True, text=True, timeout=TIMEOUT)
        log_file.write_text(f"exit {proc.returncode}\n--- stdout\n{proc.stdout}\n--- stderr\n{proc.stderr}\n")
    except subprocess.TimeoutExpired:
        log_file.write_text("timed out\n")
    outcome = read_result(work, result)
    if outcome["status"] == "done":
        jobs = sorted({Path(p).parent.name for p in outcome["posts"]})
        brands.mark_idea(ideas, idea, True, ", ".join(jobs))
    else:
        brands.mark_idea(ideas, idea, False, outcome["note"])
    log(f"{brand}: {outcome['status']}: {outcome['note'] or ', '.join(outcome['posts'])}")
    return dict(outcome, brand=brand, idea=idea)
