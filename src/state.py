import json, pathlib

PATH = pathlib.Path("state/history.json")

def load():
    if PATH.exists():
        return json.loads(PATH.read_text())
    return {"videos": []}

def save(state):
    PATH.parent.mkdir(exist_ok=True)
    PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False))

def past_titles(state, n=60):
    return [v["title"] for v in state["videos"][-n:]]
