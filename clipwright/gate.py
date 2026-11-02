"""The verification gate: does each segment carry the checks its domain requires?

Claude Code writes a ``verification`` object per segment. The gate checks that every field the
domain pack asks for is present and well formed, and that the checkable ones hold (the clip
length, and that the framing moment lies inside the clip). It cannot judge whether a claim is
true: the record shows what Claude says it checked, for the user to audit. Pure, stdlib only.
"""

from typing import Any, Dict, List, Optional, Sequence, Tuple

from .layout import parse_time

COMMENTARY_MAX = 140


def _time(segment: Dict[str, Any], key: str, prefix: str, problems: List[str]) -> Optional[float]:
    try:
        return parse_time(segment[key])
    except KeyError:
        problems.append(f"{prefix} {key} is missing")
    except ValueError as exc:
        problems.append(f"{prefix} {key} is not a time ({exc})")
    return None


def _check_commentary(segment: Dict[str, Any], prefix: str) -> List[str]:
    if "commentary" not in segment:
        return []
    value = segment["commentary"]
    if not isinstance(value, str):
        return [f"{prefix} commentary must be text"]
    if len(value.strip()) > COMMENTARY_MAX:
        return [f"{prefix} commentary is {len(value.strip())} characters; the limit is {COMMENTARY_MAX}"]
    return []


def check_segment(pack: Optional[Dict[str, Any]], segment: Dict[str, Any], number: int) -> List[str]:
    """Problems that block this segment, each starting ``segment N:``. Empty means it passes.

    With no pack (a job that has no domain) only the commentary is checked.
    """
    prefix = f"segment {number}:"
    problems = _check_commentary(segment, prefix)
    if pack is None:
        return problems

    domain = pack["name"]
    start = _time(segment, "start_time", prefix, problems)
    end = _time(segment, "end_time", prefix, problems)
    if start is not None and end is not None:
        low, high = pack["clip_seconds"]["min"], pack["clip_seconds"]["max"]
        length = end - start
        if not low <= length <= high:
            problems.append(f"{prefix} the clip is {length:g}s; {domain} clips must be {low}-{high}s")

    ver = segment.get("verification")
    if not isinstance(ver, dict):
        problems.append(f"{prefix} no verification record: the {domain} gate needs a verification object")
        return problems
    rules = pack["verification"]

    for key in rules["text"]:
        value = ver.get(key)
        if not isinstance(value, str) or not value.strip():
            problems.append(f"{prefix} verification.{key} must be filled in (non-empty text)")
    for key in rules["true"]:
        if ver.get(key) is not True:
            problems.append(f"{prefix} verification.{key} must be true, and only after doing that check")
    for key in rules["time_inside"]:
        if key not in ver:
            problems.append(f"{prefix} verification.{key} is missing")
            continue
        try:
            moment = parse_time(ver[key])
        except ValueError:
            problems.append(f"{prefix} verification.{key} {ver[key]!r} is not a time")
            continue
        if start is not None and end is not None and not start <= moment < end:
            problems.append(
                f"{prefix} {key} {ver[key]} is not inside the clip ({segment['start_time']} to "
                f"{segment['end_time']}); include the question or setup that frames the answer")
    for key in rules["flags"]:
        value = ver.get(key)
        if value is not None and not (isinstance(value, list) and all(isinstance(v, str) for v in value)):
            problems.append(f"{prefix} verification.{key} must be a list of text flags")
    return problems


def check_all(pack: Optional[Dict[str, Any]], segments: Sequence[Dict[str, Any]]) -> Dict[int, List[str]]:
    """Problems for every segment (1-based), only those that have some."""
    out: Dict[int, List[str]] = {}
    for number, segment in enumerate(segments, 1):
        problems = check_segment(pack, segment, number)
        if problems:
            out[number] = problems
    return out


def partition(pack: Optional[Dict[str, Any]], segments: Sequence[Dict[str, Any]],
              indexes: Sequence[int]) -> Tuple[List[int], Dict[int, List[str]]]:
    """Split the selected segment numbers into those that may render and those that are blocked."""
    allowed: List[int] = []
    blocked: Dict[int, List[str]] = {}
    for i in indexes:
        problems = check_segment(pack, segments[i - 1], i)
        if problems:
            blocked[i] = problems
        else:
            allowed.append(i)
    return allowed, blocked


def overlays_for(pack: Optional[Dict[str, Any]], segment: Dict[str, Any]) -> Dict[str, str]:
    """The on-screen lines for a segment: speaker, commentary and disclaimer, only those that apply."""
    out: Dict[str, str] = {}
    ver = segment.get("verification") if isinstance(segment.get("verification"), dict) else {}
    if pack and pack["overlays"]["speaker"]:
        name, credential = ver.get("speaker"), ver.get("credential")
        if isinstance(name, str) and name.strip() and isinstance(credential, str) and credential.strip():
            out["speaker"] = f"{name.strip()}, {credential.strip()}"
    commentary = segment.get("commentary")
    if isinstance(commentary, str) and commentary.strip():
        out["commentary"] = commentary.strip()
    if pack and pack["overlays"]["disclaimer"]:
        out["disclaimer"] = pack["overlays"]["disclaimer"]
    return out


def report_markdown(pack: Dict[str, Any], segments: Sequence[Dict[str, Any]],
                    blocked: Dict[int, List[str]]) -> str:
    """verification.md: every clip with its verdict, the record Claude wrote and any problems."""
    lines = [f"# Verification report ({pack['name']})", "",
             f"{pack['description']}", ""]
    for number, segment in enumerate(segments, 1):
        verdict = "BLOCKED" if number in blocked else "OK"
        title = (segment.get("hook_title") or "").strip() or "(no title)"
        lines += [f"## Clip {number}: {title} ({segment.get('start_time')} to {segment.get('end_time')}): {verdict}", ""]
        for problem in blocked.get(number, []):
            lines.append(f"- PROBLEM: {problem}")
        ver = segment.get("verification")
        if isinstance(ver, dict):
            for key, value in ver.items():
                shown = ", ".join(map(str, value)) if isinstance(value, list) else value
                lines.append(f"- {key}: {shown if shown not in ('', []) else '(none)'}")
        if segment.get("commentary"):
            lines.append(f"- commentary: {segment['commentary']}")
        lines.append("")
    return "\n".join(lines)
