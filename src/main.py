import os, pathlib, shutil, sys, yaml
from . import script_gen, tts, imagegen, render, upload, state

def make_one(cfg, st, dry_run):
    data = script_gen.generate(cfg, state.past_titles(st))
    scenes = data["scenes"]
    print(f"Title: {data['title']}")

    work = pathlib.Path("work")
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir()

    narration = " ".join(s["text"].strip() for s in scenes)
    audio = work / "voice.mp3"
    words, dur = tts.synthesize(narration, cfg["voice"], str(audio))
    print(f"Narration: {dur:.1f}s")
    if dur > 59:
        raise RuntimeError(f"Narration too long for a Short ({dur:.1f}s)")

    seed = int.from_bytes(os.urandom(3), "big")
    images = []
    for i, s in enumerate(scenes):
        print(f"Generating image {i + 1}/{len(scenes)}")
        images.append(imagegen.generate(
            s["image_prompt"], data["visual_style"], str(work / f"img{i}.jpg"),
            seed=seed + i, model=cfg.get("image_model", "flux"),
            delay=cfg.get("image_delay_seconds", 16)))

    final = render.render(scenes, images, audio, words, dur, work)

    tags = data.get("hashtags", []) + cfg.get("extra_tags", [])
    desc = data["description"] + "\n\n" + " ".join("#" + t.replace(" ", "") for t in tags[:5]) + " #Shorts"
    title = data["title"] if "#shorts" in data["title"].lower() else data["title"] + " #Shorts"

    if dry_run:
        out = pathlib.Path("out"); out.mkdir(exist_ok=True)
        shutil.copy(final, out / "preview.mp4")
        print("DRY RUN: saved out/preview.mp4, skipping upload.")
        return
    vid = upload.upload(final, title, desc, tags, cfg.get("privacy", "private"), cfg.get("category_id", "27"))
    print(f"Uploaded: https://youtube.com/shorts/{vid}")
    st["videos"].append({"title": data["title"], "id": vid})
    state.save(st)

def main():
    cfg = yaml.safe_load(open("config.yaml"))
    dry = os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes")
    st = state.load()
    failures = 0
    for _ in range(int(cfg.get("videos_per_run", 1))):
        try:
            make_one(cfg, st, dry)
        except Exception as e:
            failures += 1
            print(f"ERROR: {e}", file=sys.stderr)
    sys.exit(1 if failures else 0)

if __name__ == "__main__":
    main()
