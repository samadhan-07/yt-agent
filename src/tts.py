import asyncio, re, subprocess, edge_tts


def _humanize_text(text):
    """Add natural contemplative pauses and clean punctuation for reflective narration."""
    t = re.sub(r"\s+", " ", text).strip()
    # Convert ellipses and em/en-dashes into subtle breathing pauses
    t = t.replace("...", "… ").replace("—", ", ").replace("–", ", ").replace(" - ", ", ")
    # Ensure sentence-ending punctuation is followed by a clean space for prosody
    t = re.sub(r"([।?!.;])([^\s])", r"\1 \2", t)
    return t


async def _run(text, voice, out, rate="-6%", pitch="+0Hz"):
    words = []
    clean_text = _humanize_text(text)
    comm = edge_tts.Communicate(clean_text, voice, rate=rate, pitch=pitch, boundary="WordBoundary")
    with open(out, "wb") as f:
        async for ch in comm.stream():
            if ch["type"] == "audio":
                f.write(ch["data"])
            elif ch["type"] == "WordBoundary":
                start = ch["offset"] / 1e7
                words.append((ch["text"], start, start + ch["duration"] / 1e7))
    return words


def synthesize(text, voice, out_path, rate="-6%", pitch="+0Hz"):
    """Returns (word_timings, duration_seconds)."""
    words = asyncio.run(_run(text, voice, out_path, rate, pitch))
    dur = float(
        subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=nw=1:nk=1",
                out_path,
            ]
        )
        .decode()
        .strip()
    )
    return words, dur
