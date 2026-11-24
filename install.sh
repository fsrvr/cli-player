#!/bin/sh
# cli-player installer: asks for your OS, installs VLC + ffmpeg, adds a `cli-player` command.
set -e
APP="$HOME/.local/share/cli-player"
BIN="$HOME/.local/bin"
HERE="$(cd "$(dirname "$0")" && pwd)"

for f in cli-player.py cp_dl.py cp_fm.py; do
  [ -f "$HERE/$f" ] || { echo "Missing $f. Run this script from the cli-player folder."; exit 1; }
done

echo "cli-player installer"
echo "Supported: arch debian ubuntu mint fedora opensuse void alpine macos freebsd windows"
def=""
[ -r /etc/os-release ] && def=$(. /etc/os-release; echo "$ID")
case "$(uname -s)" in Darwin) def=macos ;; FreeBSD) def=freebsd ;; esac
os="$1"
if [ -z "$os" ]; then
  printf "Type your OS/distro [%s]: " "$def"
  read os
  [ -z "$os" ] && os="$def"
fi
os=$(echo "$os" | tr 'A-Z' 'a-z')

case "$os" in
  arch|manjaro|endeavouros|cachyos|garuda|artix) fam=arch ;;
  debian|ubuntu|mint|linuxmint|pop|popos|zorin|elementary|kali|raspbian|neon) fam=debian ;;
  fedora|rhel|centos|nobara|rocky|almalinux) fam=fedora ;;
  opensuse*|suse|sles) fam=suse ;;
  void) fam=void ;;
  alpine) fam=alpine ;;
  macos|mac|osx|darwin) fam=macos ;;
  freebsd) fam=freebsd ;;
  windows|win|win10|win11) fam=windows ;;
  *) echo "Unknown OS: $os"; exit 1 ;;
esac

S=""
if [ "$(id -u)" != 0 ]; then
  command -v sudo >/dev/null 2>&1 && S=sudo || S=doas
fi

case "$fam" in
  windows)
    echo "Windows: run these in PowerShell, inside this folder:"
    echo "  winget install VideoLAN.VLC Gyan.FFmpeg Python.Python.3.12"
    echo "  pip install -r requirements.txt"
    echo "  python cli-player.py"
    exit 0 ;;
  arch)
    $S pacman -S --needed --noconfirm vlc python python-pip ffmpeg cava ;;
  debian)
    $S apt update
    $S apt install -y vlc python3 python3-venv python3-pip ffmpeg
    $S apt install -y cava || true ;;
  fedora)
    $S dnf install -y vlc python3 python3-pip || { echo "VLC needs RPM Fusion enabled first: https://rpmfusion.org/Configuration"; exit 1; }
    $S dnf install -y ffmpeg || $S dnf install -y ffmpeg-free || echo "warning: install ffmpeg (RPM Fusion) for downloads" ;;
  suse)
    $S zypper install -y vlc python3 python3-pip ffmpeg ;;
  void)
    $S xbps-install -Sy vlc python3 ffmpeg ;;
  alpine)
    $S apk add vlc python3 py3-pip ffmpeg ;;
  macos)
    command -v brew >/dev/null 2>&1 || { echo "Install Homebrew first: https://brew.sh"; exit 1; }
    brew install --cask vlc
    brew install ffmpeg python ;;
  freebsd)
    $S pkg install -y vlc python3 ffmpeg ;;
esac

mkdir -p "$APP" "$BIN"
cp "$HERE/cli-player.py" "$HERE/cp_dl.py" "$HERE/cp_fm.py" "$APP/"
python3 -m venv "$APP/venv"
"$APP/venv/bin/pip" install -q --upgrade python-vlc mutagen yt-dlp

cat > "$BIN/cli-player" << 'LAUNCH'
#!/bin/sh
export PATH="$HOME/.local/share/cli-player/venv/bin:$PATH"
exec "$HOME/.local/share/cli-player/venv/bin/python" "$HOME/.local/share/cli-player/cli-player.py" "$@"
LAUNCH
chmod +x "$BIN/cli-player"

echo "Done. Run: cli-player [MUSIC_DIR]"
case ":$PATH:" in
  *":$BIN:"*) ;;
  *) echo "If 'cli-player' is not found, add this to your shell rc: export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
esac
