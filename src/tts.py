import asyncio, subprocess, edge_tts

async def _run(text, voice, out):
    words = []
    comm = edge_tts.Communicate(text, voice, boundary="WordBoundary")
    with open(out, "wb") as f:
        async for ch in comm.stream():
            if ch["type"] == "audio":
                f.write(ch["data"])
            elif ch["type"] == "WordBoundary":
                start = ch["offset"] / 1e7
                words.append((ch["text"], start, start + ch["duration"] / 1e7))
    return words

def synthesize(text, voice, out_path):
    """Returns (word_timings, duration_seconds)."""
    words = asyncio.run(_run(text, voice, out_path))
    dur = float(subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", out_path]).decode().strip())
    return words, dur
