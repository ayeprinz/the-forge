#!/usr/bin/env python3
"""Validate and render one episode, balance voices, and update the RSS feed."""
import os, sys, json, glob, subprocess, datetime, pathlib, urllib.request, urllib.error, email.utils, hashlib, re

KEY = os.environ.get("OPENAI_API_KEY", "")
BASE = os.environ.get("FEED_BASE", "").rstrip("/")
ROOT = pathlib.Path(__file__).parent
DOCS = ROOT / "docs"
AUD = DOCS / "audio"
MODEL = "gpt-4o-mini-tts"

def validate_script(path):
    ep = json.loads(path.read_text())
    if ep.get("date") != path.stem:
        raise ValueError("Script date must match filename")
    datetime.date.fromisoformat(ep["date"])
    for field in ("title", "summary", "instructions"):
        if not isinstance(ep.get(field), str) or not ep[field].strip():
            raise ValueError(f"Missing {field}")
    turns = ep.get("turns")
    if not isinstance(turns, list) or not turns:
        raise ValueError("Missing turns")
    total = 0
    for i, turn in enumerate(turns):
        if turn.get("v") not in ("ash", "sage"):
            raise ValueError(f"Invalid voice at turn {i}")
        for field in ("i", "t"):
            if not isinstance(turn.get(field), str) or not turn[field].strip():
                raise ValueError(f"Missing {field} at turn {i}")
        pause = turn.get("pause_after", 0.35)
        if not isinstance(pause, (int, float)) or not 0 <= pause <= 15:
            raise ValueError("Invalid pause duration")
        text = turn["t"]
        if len(text) > 4000 or any(c.isdigit() or c in "—–" for c in text):
            raise ValueError(f"Invalid spoken text at turn {i}")
        total += len(text)
    if not 50000 <= total <= 57000:
        raise ValueError(f"Spoken length {total} outside 50000–57000")
    return ep


def speak(text, voice, instructions, dest):
    if not KEY:
        raise RuntimeError("OPENAI_API_KEY is missing")
    body = json.dumps({
        "model": MODEL, "voice": voice, "input": text,
        "instructions": instructions, "response_format": "mp3", "speed": 0.95,
    }).encode()
    req = urllib.request.Request(
        "https://api.openai.com/v1/audio/speech", data=body,
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                dest.write_bytes(r.read())
            return
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 3:
                import time; time.sleep(5 * (attempt + 1)); continue
            sys.exit(f"TTS failed with HTTP {e.code}")
    sys.exit("TTS failed after retries")

def render(script_path):
    ep = validate_script(script_path)
    slug = ep["date"]
    out = AUD / f"{slug}.mp3"
    if out.exists():
        print(f"{slug} already rendered"); return ep, out

    fingerprint = hashlib.sha256((MODEL + script_path.read_text()).encode()).hexdigest()[:20]
    tmp = ROOT / "_tmp" / fingerprint; tmp.mkdir(parents=True, exist_ok=True)
    parts = []
    paid_seconds = 0.0
    voice_paths = {"ash": [], "sage": []}
    for i, turn in enumerate(ep["turns"]):
        text = turn["t"].strip()
        if not text:
            continue
        if len(text) > 4000:
            sys.exit(f"turn {i} is {len(text)} chars, over the 4096 limit")
        p = tmp / f"{i:04d}.mp3"
        if paid_seconds > 6600:
            raise RuntimeError("Audio budget guard reached; keeping partial clips")
        if not p.exists() or not p.stat().st_size:
            partial = p.with_suffix(".part")
            speak(text, turn["v"], turn["i"], partial)
            partial.replace(p)
        paid_seconds += seconds(p)
        normal = tmp / f"{i:04d}_norm.wav"
        if not normal.exists() or not normal.stat().st_size:
            normal_pending = tmp / f"{i:04d}_norm.pending.wav"
            subprocess.run(["ffmpeg", "-y", "-i", str(p), "-af",
                            "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", "24000", "-ac", "1",
                            str(normal_pending)], check=True, capture_output=True)
            normal_pending.replace(normal)
        voice_paths[turn["v"]].append(normal)
        parts.append(normal)
        print(f"  turn {i+1}/{len(ep['turns'])} ({turn['v']}, {len(text)} chars)")

    lines = []
    for i, p in enumerate(parts):
        if i:
            pause = ep["turns"][i-1].get("pause_after", 0.35)
            if not isinstance(pause, (int, float)) or not 0 <= pause <= 15:
                raise ValueError("Invalid pause duration")
            gap = tmp / f"gap-{pause}.wav"
            if not gap.exists():
                subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
                                "-t", str(pause), str(gap)], check=True, capture_output=True)
            lines.append(f"file '{gap.name}'")
        lines.append(f"file '{p.name}'")
    (tmp / "list.txt").write_text("\n".join(lines))
    # Real audio measurements, with no speech text or credentials in the report.
    report = {"date": slug, "spoken_characters": sum(len(t["t"]) for t in ep["turns"]),
              "voices": {}, "speech_minutes": round(paid_seconds / 60, 2)}
    for voice, paths in voice_paths.items():
        listing = tmp / f"{voice}.txt"
        listing.write_text("\n".join(f"file '{p.name}'" for p in paths))
        result = subprocess.run(["ffmpeg", "-hide_banner", "-f", "concat", "-safe", "0", "-i", str(listing),
                                 "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
                                capture_output=True, text=True, check=True)
        measurements = json.JSONDecoder().raw_decode(result.stderr[result.stderr.rfind("{"):])[0]
        report["voices"][voice] = {"integrated_lufs": float(measurements["input_i"]), "true_peak": float(measurements["input_tp"])}
    difference = abs(report["voices"]["ash"]["integrated_lufs"] - report["voices"]["sage"]["integrated_lufs"])
    if not difference <= 3:
        raise RuntimeError("Voice balance failed; keeping clips for repair without new speech")

    AUD.mkdir(parents=True, exist_ok=True)
    pending = AUD / f"{slug}.pending.mp3"
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "list.txt",
                    "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", "24000", "-c:a", "libmp3lame", "-b:a", "48k", "-ac", "1", str(pending)],
                   cwd=tmp, check=True, capture_output=True)
    actual_seconds = seconds(pending)
    report["duration_seconds"] = round(actual_seconds, 2)
    report["voice_difference_lu"] = round(difference, 2)
    (DOCS / f"{slug}-audio-check.json").write_text(json.dumps(report, indent=2))
    if not 3300 <= actual_seconds <= 4200:
        raise RuntimeError(f"Duration {actual_seconds/60:.1f} minutes needs review; preserving rendered audio")
    pending.replace(out)
    for p in tmp.glob("*"):
        p.unlink()
    print(f"wrote {out} ({out.stat().st_size // 1024} KB)")
    return ep, out

def seconds(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=nw=1:nk=1", str(path)], capture_output=True, text=True, check=True)
    value = float(r.stdout.strip() or 0)
    if value <= 0:
        raise ValueError("Audio has no duration")
    return value

def duration(path):
    secs = int(seconds(path))
    return f"{secs//3600:02d}:{secs%3600//60:02d}:{secs%60:02d}"


def esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

def build_feed():
    items = []
    for f in sorted(AUD.glob("*.mp3"), reverse=True):
        if f.stem.endswith(".pending"):
            continue
        meta = ROOT / "scripts" / f"{f.stem}.json"
        ep = json.loads(meta.read_text()) if meta.exists() else {}
        title = ep.get("title", f.stem)
        summary = ep.get("summary", "")
        pub_dt = datetime.datetime.fromisoformat(f.stem + "T05:00:00+00:00")
        now = datetime.datetime.now(datetime.timezone.utc)
        if pub_dt > now:
            pub_dt = now  # never publish into the future; players hide those
        pub = email.utils.format_datetime(pub_dt)
        items.append(f"""    <item>
      <title>{esc(title)}</title>
      <description>{esc(summary)}</description>
      <pubDate>{pub}</pubDate>
      <guid isPermaLink="false">{f.stem}</guid>
      <enclosure url="{BASE}/audio/{f.name}" length="{f.stat().st_size}" type="audio/mpeg"/>
      <itunes:duration>{duration(f)}</itunes:duration>
      <itunes:explicit>true</itunes:explicit>
    </item>""")

    feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
  <channel>
    <title>The Forge</title>
    <link>{BASE}/</link>
    <language>en-gb</language>
    <description>A daily hour. Private curriculum, built for one listener.</description>
    <itunes:author>Prinz</itunes:author>
    <itunes:explicit>true</itunes:explicit>
    <itunes:image href="{BASE}/cover.png"/>
{chr(10).join(items)}
  </channel>
</rss>
"""
    DOCS.mkdir(parents=True, exist_ok=True)
    pending_feed = DOCS / "feed.xml.tmp"
    pending_feed.write_text(feed)
    pending_feed.replace(DOCS / "feed.xml")
    print(f"feed rebuilt with {len(items)} episodes")

if __name__ == "__main__":
    today = os.environ.get("EPISODE_DATE") or datetime.date.today().isoformat()
    path = ROOT / "scripts" / f"{today}.json"
    if not path.exists():
        sys.exit(f"MISSING SCRIPT: {today}; feed unchanged")
    render(path)
    # Retain existing episodes; deletion requires a separate retention decision.
    build_feed()
