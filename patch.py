src = open("cli-player.py").read()

def rep(old, new):
    global src
    assert src.count(old) == 1, "anchor not found:\n" + old[:80]
    src = src.replace(old, new)

rep('AUDIO_EXTS = {".mp3"', 'import cp_dl\nimport cp_fm\n\nAUDIO_EXTS = {".mp3"')
rep('STATE_FILE = Path.home() / ".config" / "cli-player" / "state.json"\n',
    'STATE_FILE = Path.home() / ".config" / "cli-player" / "state.json"\n'
    'PLAYLIST_DIR = Path.home() / ".config" / "cli-player" / "playlists"\n'
    'MUSIC_DIR = Path.home() / "Documents" / "music"\n')
rep('            "theme": ui.theme,\n', '            "theme": ui.theme,\n            "gui": ui.gui,\n')
rep('        playlists.insert(0, Playlist("All (root)", loose, music_dir))\n\n    return playlists\n',
    '        playlists.insert(0, Playlist("All (root)", loose, music_dir))\n\n    playlists += m3u_playlists()\n    return playlists\n')

rep('class Player:\n    def __init__(self, playlists, state=None):', r'''def m3u_playlists():
    out = []
    for f in sorted(PLAYLIST_DIR.glob("*.m3u")):
        songs = [Song(Path(l)) for l in cp_fm.read_pl(f) if Path(l).is_file()]
        if songs:
            out.append(Playlist("♪ " + f.stem, songs, None))
    return out


def refresh_m3u(player):
    cur_name, cur_path = player.playlist.name, str(player.song.path)
    keep = [p for p in player.playlists if p.folder is not None]
    player.playlists = keep + m3u_playlists()
    player.queue = [(a, b) for a, b in player.queue if a < len(keep)]
    for i, p in enumerate(player.playlists):
        if p.name == cur_name:
            player.pl_idx = i
            for j, s in enumerate(p.songs):
                if str(s.path) == cur_path:
                    player.song_idx = j
            break
    else:
        player.pl_idx = player.song_idx = 0
        player._load_current(autoplay=False)
    player.song_idx = min(player.song_idx, len(player.playlist.songs) - 1)


def play_path(player, path):
    p = Path(path)
    order = sorted(range(len(player.playlists)), key=lambda i: player.playlists[i].folder is None)
    for i in order:
        for j, s in enumerate(player.playlists[i].songs):
            if s.path == p:
                player.pl_idx = i
                player.play_song(j)
                return True
    return False


def add_song(player, folder, path):
    cur = player.song
    for pl in player.playlists:
        if pl.folder == folder:
            if all(s.path != path for s in pl.songs):
                pl.songs.append(Song(path))
            pl.songs.sort(key=lambda s: s.path)
            player.song_idx = player.playlist.songs.index(cur)
            return
    player.playlists.insert(0, Playlist("All (root)", [Song(path)], folder))
    player.pl_idx += 1
    player.queue = [(a + 1, b) for a, b in player.queue]


_LEN = {}


def song_len(song):
    p = song.path
    if p not in _LEN:
        t = "--:--"
        if HAVE_MUTAGEN:
            try:
                f = MutagenFile(p)
                if f and f.info:
                    t = fmt_time(int(f.info.length * 1000))
            except Exception:
                pass
        _LEN[p] = t
    return _LEN[p]


class Player:
    def __init__(self, playlists, state=None):''')

rep('        self.rows = {}\n', '''        self.rows = {}
        self.gui = "aud"
        self.btns = []
        self.prompt = None
        self.job = None
        self.job_seen = ""
        self.job_dest = None
''')
rep('    folder = player.playlist.folder\n    cur = player.song\n    done = 0',
    '    folder = player.playlist.folder\n    if folder is None:\n        return 0\n    cur = player.song\n    done = 0')
rep('            draw(stdscr, player, viz, ui, status_msg)\n    except curses.error:',
    '            (draw_aud if ui.gui == "aud" else draw)(stdscr, player, viz, ui, status_msg)\n    except curses.error:')
rep('    ("h", "show this help"),\n',
    '    ("g", "switch GUI: audacious / legacy"),\n    ("f", "file manager / playlists"),\n'
    '    ("d", "download song+lyrics+cover"),\n    ("s", "stop"),\n    ("h", "show this help"),\n')

rep('HELP = [\n', r'''def draw_pending(stdscr, player, ui, h, w):
    bw = min(w - 4, max(24, len(player.playlist.name) + 14))
    inner = bw - 2
    y0 = max(0, (h - 5) // 2)
    x0 = max(0, (w - bw) // 2)

    def put(y, text, attr=curses.A_NORMAL):
        try:
            stdscr.addstr(y, x0, text, attr)
        except curses.error:
            pass

    t = f" add to {player.playlist.name} "[:inner]
    put(y0, "┌" + t.center(inner, "─") + "┐", ACC)
    for k, label in enumerate(("copy", "move")):
        s = (curses.A_REVERSE | ACC) if ui.pick == k else curses.A_NORMAL
        put(y0 + 1 + k * 2, "│" + label.center(inner) + "│", s)
    put(y0 + 2, "│" + "─" * inner + "│")
    put(y0 + 4, "└" + "─" * inner + "┘", ACC)


def draw_aud(stdscr, player, viz, ui, status_msg):
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    iw = w - 4
    length = max(0, player.mp.get_length() or 0)
    cur = max(0, player.mp.get_time() or 0)
    playing = player.mp.get_state() == vlc.State.Playing
    ui.btns, ui.rows = [], {}

    def put(y, x, s, a=0):
        try:
            stdscr.addstr(y, x, s[:max(0, w - x)], a)
        except curses.error:
            pass

    for y in range(1, h - 2):
        put(y, 0, "│")
        put(y, w - 1, "│")
    put(0, 0, "┌" + " cli-player ".center(w - 2, "─") + "┐", ACC)
    put(h - 2, 0, "└" + "─" * (w - 2) + "┘", ACC)
    if ui.job and not ui.job.done:
        put(0, 2, " downloading ", ACC | curses.A_BOLD)

    head = f"{'▶' if playing else '❚❚'} {fmt_time(cur)}"
    put(1, 2, head, ACC | curses.A_BOLD)
    x = 2 + len(head) + 2
    if viz.available:
        n = len(viz.values)
        vz = "".join(BLOCKS[max(0, min(8, int(viz.values[c * n // 16] / 100 * 9)))] for c in range(16))
        put(1, x, vz, VIZ)
        x += 18
    t = player.song.title
    tw = max(1, w - 2 - x)
    if len(t) > tw:
        s = t + "   ***   "
        o = int(time.time() * 4) % len(s)
        t = (s + s)[o:o + tw]
    put(1, x, t, ACC | curses.A_BOLD)

    vb = 10
    f = player.volume * vb // 100
    put(2, 2, (f"vol {'█' * f}{'░' * (vb - f)} {player.volume:>3}%   speed {player.rate:.1f}x   "
               f"loop:{player.loop_mode}   shuffle:{'on' if player.shuffle else 'off'}")[:iw])

    bw = max(10, iw - 12)
    put(3, 2, draw_bar(bw, cur / length if length else 0), ACC)
    put(3, 3 + bw, f"{fmt_time(cur)}/{fmt_time(length)}")
    ui.bar = (3, 2, bw)

    x = 2
    for label, key, on in (("[|<]", ord('p'), 0), ("[>||]", ord(' '), 0), ("[■]", ord('s'), 0),
                           ("[>|]", ord('n'), 0), (None, 0, 0),
                           ("[shuf]", ord('r'), player.shuffle),
                           ("[loop]", ord('l'), player.loop_mode != "off"), (None, 0, 0),
                           ("[files]", ord('f'), 0), ("[dl]", ord('d'), 0), ("[legacy]", ord('g'), 0)):
        if label is None:
            x += 2
            continue
        put(4, x, label, (ACC | curses.A_REVERSE) if on else 0)
        ui.btns.append((4, x, x + len(label), key))
        x += len(label) + 1

    lyr = current_lyric(player.song, cur)
    if lyr:
        put(5, 2, lyr[:iw], ACC)
    elif player.queue:
        qpl, qsi = player.queue[0]
        put(5, 2, f"Next up: {player.playlists[qpl].songs[qsi].title}"[:iw], curses.A_DIM)

    put(6, 0, "├" + f" {player.playlist.name} ({player.pl_idx + 1}/{len(player.playlists)}) ".center(w - 2, "─") + "┤", ACC)
    songs = player.playlist.songs
    vis = visible_songs(player, ui)
    ui.sel = max(0, min(ui.sel, len(vis) - 1)) if vis else 0
    row, avail = 7, h - 9
    if avail > 0:
        if not vis:
            put(row, 4, "no matches", curses.A_DIM)
        else:
            off = max(0, min(ui.sel - avail // 2, len(vis) - avail))
            for k in range(off, min(len(vis), off + avail)):
                i = vis[k]
                is_cur = i == player.song_idx
                qn = [n for n, (pi, si) in enumerate(player.queue, 1)
                      if pi == player.pl_idx and si == i]
                d = song_len(songs[i])
                left = f"{'▶' if is_cur else ' '} {i + 1:>3}. {'[q%d] ' % qn[0] if qn else ''}{songs[i].title}"
                text = left[:max(0, iw - len(d) - 1)].ljust(max(0, iw - len(d))) + d
                attr = (ACC | curses.A_BOLD) if is_cur else curses.A_NORMAL
                if k == ui.sel:
                    attr |= curses.A_REVERSE
                ui.rows[row] = k
                put(row, 2, text, attr)
                row += 1
    put(h - 2, 2, f" {len(vis)} songs ", ACC)

    if ui.pending:
        foot, a = "↑/↓:select  enter:confirm  esc:cancel", ACC
    elif ui.search_mode:
        foot, a = f"/{ui.query}_", ACC
    elif status_msg:
        foot, a = status_msg, ACC
    else:
        foot, a = "h:help  g:legacy  f:files  d:download  /:search  t:theme", curses.A_DIM
    put(h - 1, 2, foot[:w - 4], a)
    if ui.pending:
        draw_pending(stdscr, player, ui, h, w)
    stdscr.refresh()


HELP = [
''')

rep("    keyq = deque()\n\n    while True:", r'''    keyq = deque()

    def start_dl(text):
        if ui.job and not ui.job.done:
            return "Download already running"
        if not cp_dl.available():
            return "need: sudo pacman -S yt-dlp ffmpeg"
        ui.job_dest = player.playlist.folder or MUSIC_DIR
        ui.job = cp_dl.Job(text, ui.job_dest)
        return "Downloading..."

    while True:''')

rep("(ui.search_mode or ui.pending) else []", "(ui.search_mode or ui.pending or ui.prompt) else []")

rep("            if ui.pending:\n                if ch in (curses.KEY_UP, curses.KEY_DOWN, ord('j'), ord('k')):\n                    ui.pick = 1 - ui.pick",
    r'''            if ui.prompt:
                p = ui.prompt
                if ch == 27:
                    ui.prompt = None
                elif is_enter(ch):
                    ui.prompt = None
                    if p["text"].strip():
                        status_msg = p["cb"](p["text"].strip()) or ""
                elif ch in (curses.KEY_BACKSPACE, 127, 8):
                    p["text"] = p["text"][:-1]
                elif 32 <= ch <= 126:
                    p["text"] += chr(ch)
            elif ui.pending:
                if ch in (curses.KEY_UP, curses.KEY_DOWN, ord('j'), ord('k')):
                    ui.pick = 1 - ui.pick''')

rep("                    b = ui.bar\n                    if b and my == b[0] and b[1] <= mx < b[1] + b[2]:",
    "                    b = ui.bar\n"
    "                    hit = [k for (by, x0, x1, k) in ui.btns if my == by and x0 <= mx < x1]\n"
    "                    if hit:\n                        keyq.append(hit[0])\n"
    "                    elif b and my == b[0] and b[1] <= mx < b[1] + b[2]:")

rep("            elif ch in (ord('t'), ord('T')):\n                ui.theme = (ui.theme + 1) % len(THEMES)",
    r'''            elif ch == ord('g'):
                ui.gui = "legacy" if ui.gui == "aud" else "aud"
                status_msg = f"GUI: {ui.gui}"
            elif ch == ord('s'):
                player.mp.stop()
                player.paused = True
            elif ch == ord('d'):
                ui.prompt = {"label": "download (url or search): ", "text": "", "cb": start_dl}
            elif ch == ord('f'):
                r = cp_fm.run(stdscr, MUSIC_DIR, PLAYLIST_DIR, ACC)
                refresh_m3u(player)
                if r:
                    play_path(player, r)
                ui.last_key = None
                last_pl = player.pl_idx
            elif ch in (ord('t'), ord('T')):
                ui.theme = (ui.theme + 1) % len(THEMES)''')

rep("        now = time.time()\n        if status_msg != msg_seen:", r'''        if ui.job:
            job = ui.job
            done = job.done
            if job.msg != ui.job_seen:
                ui.job_seen = status_msg = job.msg
            if done:
                if job.result:
                    add_song(player, ui.job_dest, job.result)
                ui.job = None

        now = time.time()
        if status_msg != msg_seen:''')

rep("        draw_safe(stdscr, player, viz, ui, status_msg)\n        time.sleep(0.03)",
    "        shown = f\"{ui.prompt['label']}{ui.prompt['text']}_\" if ui.prompt else status_msg\n"
    "        draw_safe(stdscr, player, viz, ui, shown)\n        time.sleep(0.03)")

rep('    if not music_dir.is_dir():\n        print(f"Music directory not found: {music_dir}")',
    '    music_dir = music_dir.resolve()\n    MUSIC_DIR = music_dir\n    if not music_dir.is_dir():\n        print(f"Music directory not found: {music_dir}")')
rep("    ui = UI(theme)\n",
    '    ui = UI(theme)\n    ui.gui = state.get("gui") if state.get("gui") in ("aud", "legacy") else "aud"\n')

open("cli-player.py", "w").write(src)
print("patched")
