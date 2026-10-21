"""Neural TTS (edge-tts) per scene chunk with word-level timestamps for kinetic captions."""
import asyncio, subprocess
from pathlib import Path
import edge_tts
import config

# MALE voices only. The configured voice goes first; if Microsoft rejects it, the next male voice is tried.
MALE_VOICES = ("en-US-ChristopherNeural", "en-GB-RyanNeural", "en-US-GuyNeural", "en-US-EricNeural")
VOICES = [config.VOICE] + [v for v in MALE_VOICES if v != config.VOICE]
_good = [None]   # once a voice works it is kept for the whole video, so every chunk sounds identical


def probe(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                       capture_output=True, text=True)
    return float(r.stdout.strip() or 0)


async def _synth(text, mp3):
    order = [_good[0]] if _good[0] else VOICES
    for voice in order:
        for attempt in range(3):
            try:
                try:
                    comm = edge_tts.Communicate(text, voice, rate=config.RATE, pitch=config.PITCH, boundary="WordBoundary")
                except TypeError:  # older edge-tts emits word boundaries by default
                    comm = edge_tts.Communicate(text, voice, rate=config.RATE, pitch=config.PITCH)
                marks = []
                with open(mp3, "wb") as f:
                    async for ch in comm.stream():
                        if ch["type"] == "audio":
                            f.write(ch["data"])
                        elif ch["type"] == "WordBoundary":
                            marks.append(ch["offset"] / 1e7)
                if mp3.stat().st_size > 800:
                    if _good[0] != voice:
                        print(f"[tts] using voice: {voice}", flush=True)
                    _good[0] = voice
                    return marks
            except Exception as e:
                print(f"[tts] {voice} retry {attempt + 1}: {str(e)[:80]}", flush=True)
                await asyncio.sleep(3 * (attempt + 1))
    raise RuntimeError("TTS failed: " + text[:60])


def align(words, marks, dur):
    """Return a start time for every display word. Use TTS marks if counts match, else proportional by length."""
    if len(marks) == len(words):
        return marks
    total = sum(len(w) + 1 for w in words)
    t, out = 0.0, []
    for w in words:
        out.append(t)
        t += dur * (len(w) + 1) / total
    return out


def _run(cmd):
    subprocess.run(cmd, check=True, capture_output=True)


async def _one(sc, wd, sem):
    async with sem:
        wav = wd / f"a_{sc['id']:04d}.wav"
        if sc["kind"] == "chapter":
            _run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", str(sc["pause"]), str(wav)])
            sc.update(audio=str(wav), dur=sc["pause"], words=[])
            return
        mp3 = wd / f"a_{sc['id']:04d}.mp3"
        text = sc["narration"].replace("\u2014", ", ").replace("\u2013", "-")
        if not wav.exists():
            marks = await _synth(text, mp3)
            await asyncio.to_thread(_run, ["ffmpeg", "-y", "-i", str(mp3), "-ar", "44100", "-ac", "1",
                                           "-af", f"apad=pad_dur={sc['pause']}", str(wav)])
            sc["_marks"] = marks
        else:
            sc["_marks"] = []
        dur = probe(wav)
        words = sc["narration"].split()
        marks = align(words, sc.pop("_marks"), dur - sc["pause"])
        sc.update(audio=str(wav), dur=dur, words=[dict(w=w, t=t) for w, t in zip(words, marks)])


async def _pick_voice(wd):
    await _synth("This is a short voice test.", wd / "voice_test.mp3")


def synthesize(scenes, wd: Path, workers=4):
    wd.mkdir(parents=True, exist_ok=True)
    if any(s["kind"] != "chapter" for s in scenes):
        asyncio.run(_pick_voice(wd))   # decide the voice once, before the parallel workers start

    async def go():
        sem = asyncio.Semaphore(workers)
        await asyncio.gather(*[_one(s, wd, sem) for s in scenes])
    asyncio.run(go())
    t = 0.0
    for s in scenes:
        s["start"] = t
        t += s["dur"]
    return t
