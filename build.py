#!/usr/bin/env python3
"""Render the day's episode to MP3, rebuild the RSS feed, prune old audio."""
import os, sys, json, glob, subprocess, datetime, pathlib, urllib.request, urllib.error, email.utils

KEY = os.environ["OPENAI_API_KEY"]
BASE = os.environ.get("FEED_BASE", "").rstrip("/")
ROOT = pathlib.Path(__file__).parent
DOCS = ROOT / "docs"
AUD = DOCS / "audio"
KEEP_DAYS = 35
MODEL = "gpt-4o-mini-tts"

def speak(text, voice, instructions, dest):
    body = json.dumps({
        "model": MODEL, "voice": voice, "input": text,
        "instructions": instructions, "response_format": "mp3",
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
            if e.code in (429, 500, 502, 503) and attempt < 3:
                import time; time.sleep(5 * (attempt + 1)); continue
            sys.exit(f"TTS failed {e.code}: {e.read()[:300]}")
    sys.exit("TTS failed after retries")

def render(script_path):
    ep = json.loads(script_path.read_text())
    slug = ep["date"]
    out = AUD / f"{slug}.mp3"
    if out.exists():
        print(f"{slug} already rendered"); return ep, out

    tmp = ROOT / "_tmp"; tmp.mkdir(exist_ok=True)
    parts = []
    for i, turn in enumerate(ep["turns"]):
        text = turn["t"].strip()
        if not text:
            continue
        if len(text) > 4000:
            sys.exit(f"turn {i} is {len(text)} chars, over the 4096 limit")
        p = tmp / f"{i:04d}.mp3"
        speak(text, turn["v"], turn.get("i", ep.get("instructions", "")), p)
        parts.append(p)
        print(f"  turn {i+1}/{len(ep['turns'])} ({turn['v']}, {len(text)} chars)")

    gap = tmp / "gap.mp3"
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
                    "-t", "0.35", "-q:a", "9", str(gap)], check=True, capture_output=True)

    listing = tmp / "list.txt"
    lines = []
    for p in parts:
        lines.append(f"file '{p.name}'")
        lines.append(f"file '{gap.name}'")
    listing.write_text("\n".join(lines))

    AUD.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "list.txt",
                    "-c:a", "libmp3lame", "-b:a", "48k", "-ac", "1", str(out)],
                   cwd=tmp, check=True, capture_output=True)
    for p in tmp.glob("*"):
        p.unlink()
    print(f"wrote {out} ({out.stat().st_size // 1024} KB)")
    return ep, out

def duration(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=nw=1:nk=1", str(path)], capture_output=True, text=True)
    secs = int(float(r.stdout.strip() or 0))
    return f"{secs//3600:02d}:{secs%3600//60:02d}:{secs%60:02d}"

def prune():
    cutoff = datetime.date.today() - datetime.timedelta(days=KEEP_DAYS)
    for f in AUD.glob("*.mp3"):
        try:
            d = datetime.date.fromisoformat(f.stem)
        except ValueError:
            continue
        if d < cutoff:
            f.unlink(); print(f"pruned {f.name}")

def esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

def build_feed():
    items = []
    for f in sorted(AUD.glob("*.mp3"), reverse=True):
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
    (DOCS / "feed.xml").write_text(feed)
    print(f"feed rebuilt with {len(items)} episodes")

if __name__ == "__main__":
    today = os.environ.get("EPISODE_DATE") or datetime.date.today().isoformat()
    path = ROOT / "scripts" / f"{today}.json"
    if not path.exists():
        print(f"no script for {today}, nothing to render")
        build_feed(); sys.exit(0)
    render(path)
    prune()
    build_feed()
