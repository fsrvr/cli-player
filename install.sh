#!/bin/sh
set -e
cd "$(dirname "$0")"
echo "cli-player installer"

def=""
[ -r /etc/os-release ] && def=$(. /etc/os-release; echo "$ID")
[ "$(uname -s)" = Darwin ] && def=macos
[ "$(uname -s)" = FreeBSD ] && def=freebsd

if [ -n "$1" ]; then
  os="$1"
else
  echo "Supported: arch debian ubuntu mint fedora opensuse void alpine macos freebsd windows"
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
    echo "Windows: run these in PowerShell:"
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
    $S dnf install -y vlc python3 python3-pip || { echo "VLC needs RPM Fusion: https://rpmfusion.org/Configuration"; exit 1; }
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

APP="$HOME/.local/share/cli-player"
BIN="$HOME/.local/bin"
mkdir -p "$APP" "$BIN"
cp cli-player.py cp_dl.py cp_fm.py "$APP/"
python3 -m venv "$APP/venv"
"$APP/venv/bin/pip" install -q --upgrade python-vlc mutagen yt-dlp

cat > "$BIN/cli-player" << 'LAUNCH'
#!/bin/sh
export PATH="$HOME/.local/share/cli-player/venv/bin:$PATH"
exec "$HOME/.local/share/cli-player/venv/bin/python" "$HOME/.local/share/cli-player/cli-player.py" "$@"
LAUNCH
chmod +x "$BIN/cli-player"

case ":$PATH:" in
  *":$BIN:"*) ;;
  *) echo "Add to your shell rc: export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
esac
echo "Done. Run: cli-player [MUSIC_DIR]   (default ~/Documents/music)"
echo "Update later: git pull && ./install.sh"
