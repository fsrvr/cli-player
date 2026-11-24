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
        self.msg = "Searching..." if t.startswith("ytsearch") else "Starting..."
        cmd = ["yt-dlp", "-x", "--audio-format", "mp3", "--audio-quality", "0",
               "--embed-thumbnail", "--embed-metadata", "--convert-thumbnails", "jpg",
               "--no-playlist", "--no-simulate", "--no-quiet", "--newline", "--progress",
               "-o", str(self.dest / "%(title)s.%(ext)s"),
               "--print", "after_move:CPDONE\t%(filepath)s\t%(artist,uploader)s\t%(track,title)s\t%(duration)s", t]
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        name, done, err = "", None, ""
        for line in p.stdout:
            line = line.strip()
            if line.startswith("CPDONE\t"):
                done = line.split("\t")[1:]
            elif line.startswith("ERROR"):
                err = line
            elif line.startswith("[download] Destination:"):
                name = Path(line.split(":", 1)[1].strip()).name
                self.msg = f"Downloading {name}"
            elif line.startswith("[download]") and "%" in line:
                m = re.search(r"([\d.]+)%", line)
                if m:
                    self.msg = f"Downloading {name} {m.group(1)}%"
            elif line.startswith("[ExtractAudio]"):
                self.msg = f"Converting to mp3: {name}"
            elif line.startswith(("[EmbedThumbnail]", "[Metadata]", "[ThumbnailsConvertor]")):
                self.msg = f"Adding cover/tags: {name}"
        p.wait()
        if p.returncode != 0 or not done:
            raise RuntimeError(err.replace("ERROR: ", "")[:100] or f"yt-dlp exited with code {p.returncode}")
        fp, artist, title, dur = done
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
