import json, pathlib

PATH = pathlib.Path("state/history.json")
METRICS = pathlib.Path("state/metrics.json")


def load():
    if PATH.exists():
        return json.loads(PATH.read_text(encoding="utf-8"))
    return {"videos": []}


def save(state):
    PATH.parent.mkdir(exist_ok=True)
    PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def past_titles(state, n=60):
    return [v["title"] for v in state["videos"][-n:]]


def top_titles(n=5):
    """Best-performing titles from state/metrics.json (written by analytics.py). [] if none yet."""
    if not METRICS.exists():
        return []
    try:
        vids = json.loads(METRICS.read_text(encoding="utf-8"))["videos"]
    except Exception:
        return []
    vids = [v for v in vids if (v.get("views") or 0) > 0]
    vids.sort(key=lambda v: v["views"], reverse=True)
    return [v["title"] for v in vids[:n]]
