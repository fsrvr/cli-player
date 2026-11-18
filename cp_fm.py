import curses
from pathlib import Path

AUDIO = {".mp3", ".flac", ".wav", ".ogg", ".m4a", ".opus", ".wma"}
ENTER = (10, 13, curses.KEY_ENTER)
BACK = (curses.KEY_BACKSPACE, 127, 8)


def ls(p):
    try:
        items = [i for i in p.iterdir() if not i.name.startswith(".")
                 and (i.is_dir() or i.suffix.lower() in AUDIO)]
    except OSError:
        return []
    return sorted(items, key=lambda i: (not i.is_dir(), i.name.lower()))


def expand(paths):
    out = []
    for p in paths:
        if p.is_dir():
            out += sorted(f for f in p.rglob("*") if f.is_file() and f.suffix.lower() in AUDIO)
        else:
            out.append(p)
    return out


def read_pl(f):
    try:
        return [l.strip() for l in f.read_text(errors="ignore").splitlines()
                if l.strip() and not l.startswith("#")]
    except OSError:
        return []


def write_pl(f, lines):
    f.write_text("".join(l + "\n" for l in lines))


def add_pl(f, paths):
    have = set(read_pl(f))
    new = [str(p) for p in paths if str(p) not in have]
    if new:
        with f.open("a") as fh:
            fh.write("".join(s + "\n" for s in new))
    return len(new)


def run(stdscr, root, pl_dir, acc):
    pl_dir.mkdir(parents=True, exist_ok=True)
    stdscr.nodelay(False)
    cwd, pos, sel = root, {}, set()
    mode, msg, last = 0, "", "favs"
    pi, ti, focus, confirm = 0, 0, 0, False

    def put(y, x, s, a=0):
        h, w = stdscr.getmaxyx()
        if 0 <= y < h and 0 <= x < w:
            try:
                stdscr.addstr(y, x, s[:w - x - (1 if y == h - 1 else 0)], a)
            except curses.error:
                pass

    def pane(x, pw, rows, idx, avail):
        off = max(0, min((idx or 0) - avail // 2, len(rows) - avail))
        for r, k in enumerate(range(off, min(len(rows), off + avail))):
            t, b, m = rows[k]
            a = curses.A_BOLD if b else 0
            if k == idx:
                a |= curses.A_REVERSE
            put(1 + r, x, (("● " if m else "  ") + t)[:pw - 1].ljust(pw - 1), a | (acc if m else 0))

    def ask(label, text=""):
        while True:
            h, w = stdscr.getmaxyx()
            stdscr.move(h - 1, 0)
            stdscr.clrtoeol()
            put(h - 1, 1, label + text + "_", acc)
            stdscr.refresh()
            c = stdscr.getch()
            if c == 27:
                return None
            if c in ENTER:
                return text.strip() or None
            if c in BACK:
                text = text[:-1]
            elif 32 <= c <= 126:
                text += chr(c)

    def nm(p):
        return p.name + ("/" if p.is_dir() else "")

    try:
        while True:
            h, w = stdscr.getmaxyx()
            stdscr.erase()
            avail = h - 3
            if mode == 0:
                items = ls(cwd)
                i = min(pos.get(cwd, 0), max(0, len(items) - 1))
                cur = items[i] if items else None
                par = ls(cwd.parent) if cwd != root else []
                w1, w2 = w // 5, w * 2 // 5
                pane(0, w1, [(nm(p), p.is_dir(), False) for p in par],
                     par.index(cwd) if cwd in par else None, avail)
                pane(w1, w2, [(nm(p), p.is_dir(), p in sel) for p in items], i, avail)
                if cur and cur.is_dir():
                    pane(w1 + w2, w - w1 - w2, [(nm(p), p.is_dir(), False) for p in ls(cur)], None, avail)
                elif cur:
                    try:
                        put(1, w1 + w2 + 1, f"{cur.stat().st_size // 1024} KB", curses.A_DIM)
                    except OSError:
                        pass
                put(0, 1, f"FILES {cwd}  [{len(sel)} selected]", acc | curses.A_BOLD)
                hint = "jk move  h/l out/in  space select  a add  n new  enter play  tab lists  q back"
            else:
                pls = sorted(pl_dir.glob("*.m3u"))
                pi = min(pi, max(0, len(pls) - 1))
                trk = read_pl(pls[pi]) if pls else []
                ti = min(ti, max(0, len(trk) - 1))
                w1 = w // 3
                pane(0, w1, [(p.stem, True, k == pi) for k, p in enumerate(pls)],
                     pi if focus == 0 else None, avail)
                pane(w1, w - w1, [(Path(t).name, False, False) for t in trk],
                     ti if focus == 1 else None, avail)
                put(0, 1, f"PLAYLISTS {pl_dir}", acc | curses.A_BOLD)
                hint = "jk move  l/h tracks/lists  x remove track  X delete list  n new  enter play  tab files  q back"
            put(h - 1, 1, msg or hint, acc if msg else curses.A_DIM)
            stdscr.refresh()

            k = stdscr.getch()
            msg = ""
            was, confirm = confirm, False
            if k in (ord('q'), 27):
                return None
            if k == 9:
                mode = 1 - mode
            elif mode == 0:
                if k in (ord('j'), curses.KEY_DOWN) and items:
                    pos[cwd] = min(i + 1, len(items) - 1)
                elif k in (ord('k'), curses.KEY_UP):
                    pos[cwd] = max(i - 1, 0)
                elif k in (ord('h'), curses.KEY_LEFT) and cwd != root:
                    pos[cwd.parent] = par.index(cwd) if cwd in par else 0
                    cwd = cwd.parent
                elif k in (ord('l'), curses.KEY_RIGHT) and cur and cur.is_dir():
                    cwd = cur
                elif k in ENTER and cur:
                    if cur.is_dir():
                        cwd = cur
                    else:
                        return str(cur)
                elif k == ord(' ') and cur:
                    sel ^= {cur}
                    pos[cwd] = min(i + 1, len(items) - 1)
                elif k == ord('a'):
                    tg = expand(sorted(sel) or ([cur] if cur else []))
                    if tg:
                        name = ask("add to playlist: ", last)
                        if name:
                            name = name.replace("/", "_")
                            last = name
                            msg = f"Added {add_pl(pl_dir / f'{name}.m3u', tg)} to {name}"
                            sel.clear()
                elif k == ord('n'):
                    name = ask("new playlist: ")
                    if name:
                        (pl_dir / f"{name.replace('/', '_')}.m3u").touch()
                        msg = f"Created {name}"
            else:
                if k in (ord('j'), curses.KEY_DOWN):
                    if focus == 0 and pls:
                        pi, ti = min(pi + 1, len(pls) - 1), 0
                    elif trk:
                        ti = min(ti + 1, len(trk) - 1)
                elif k in (ord('k'), curses.KEY_UP):
                    if focus == 0:
                        pi, ti = max(pi - 1, 0), 0
                    else:
                        ti = max(ti - 1, 0)
                elif k in (ord('l'), curses.KEY_RIGHT) and trk:
                    focus = 1
                elif k in (ord('h'), curses.KEY_LEFT):
                    focus = 0
                elif k == ord('x') and focus == 1 and trk:
                    trk.pop(ti)
                    write_pl(pls[pi], trk)
                elif k == ord('X') and focus == 0 and pls:
                    if was:
                        pls[pi].unlink()
                        msg = "Deleted"
                    else:
                        confirm, msg = True, "press X again to delete playlist"
                elif k in ENTER and focus == 1 and trk:
                    return trk[ti]
                elif k == ord('n'):
                    name = ask("new playlist: ")
                    if name:
                        (pl_dir / f"{name.replace('/', '_')}.m3u").touch()
    finally:
        stdscr.nodelay(True)
