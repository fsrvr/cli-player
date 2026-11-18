import json, re, shutil, subprocess, threading, urllib.parse, urllib.request
from pathlib import Path


def available():
    return bool(shutil.which("yt-dlp") and shutil.which("ffmpeg"))


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "cli-player"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def fetch_lrc(artist, title, dur):
    q = urllib.parse.urlencode
    try:
        d = _get("https://lrclib.net/api/get?" + q(
            {"artist_name": artist, "track_name": title, "duration": int(float(dur))}))
        if d.get("syncedLyrics"):
            return d["syncedLyrics"]
    except Exception:
        pass
    try:
        for d in _get("https://lrclib.net/api/search?" + q({"q": f"{artist} {title}".strip()})):
            if d.get("syncedLyrics"):
                return d["syncedLyrics"]
    except Exception:
        pass
    return None


class Job:
    def __init__(self, target, dest):
        self.target, self.dest = target, Path(dest)
        self.msg, self.result, self.done = "Downloading...", None, False
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            self.result = self._work()
        except Exception as e:
            self.msg = f"Download failed: {e}"
        self.done = True

    def _work(self):
        t = self.target
        if not re.match(r"https?://", t):
            t = f"ytsearch1:{t}"
        cmd = ["yt-dlp", "-x", "--audio-format", "mp3", "--audio-quality", "0",
               "--embed-thumbnail", "--embed-metadata", "--convert-thumbnails", "jpg",
               "--no-playlist", "--no-simulate",
               "-o", str(self.dest / "%(title)s.%(ext)s"),
               "--print", "after_move:%(filepath)s\t%(artist,uploader)s\t%(track,title)s\t%(duration)s", t]
        r = subprocess.run(cmd, capture_output=True, text=True)
        out = r.stdout.strip().splitlines()
        if r.returncode != 0 or not out:
            err = r.stderr.strip().splitlines()
            raise RuntimeError((err[-1] if err else "yt-dlp error")[:80])
        fp, artist, title, dur = out[-1].split("\t")
        artist = "" if artist == "NA" else re.sub(r"\s*-\s*Topic$", "", artist)
        title = re.sub(r"\s*[\(\[].*?[\)\]]", "", title).strip()
        if " - " in title:
            artist, title = title.split(" - ", 1)
        self.msg = "Fetching lyrics..."
        lrc = fetch_lrc(artist, title, dur)
        p = Path(fp)
        if lrc:
            p.with_suffix(".lrc").write_text(lrc, encoding="utf-8")
        self.msg = f"Saved: {p.stem} ({'+lyrics' if lrc else 'no lyrics found'})"
        return p
