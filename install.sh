#!/bin/sh
# Build and install the Nothing desktop.
#   ./install.sh --deps     install the Arch Linux dependencies (uses sudo pacman)
#   ./install.sh            build + install to /usr/local (asks for sudo)
#   PREFIX=/usr ./install.sh
set -e
cd "$(dirname "$0")"
PREFIX="${PREFIX:-/usr/local}"
SUDO="${SUDO-sudo}"

DEPS="wlroots0.20 xorg-xwayland gtk4 gtk4-layer-shell libadwaita python python-gobject python-cairo python-numpy
meson ninja wayland-protocols gnome-online-accounts accountsservice polkit-gnome networkmanager
wireplumber bluez-utils xdg-desktop-portal xdg-desktop-portal-gtk xdg-desktop-portal-wlr
gnome-keyring grim slurp wl-clipboard"

if [ "$1" = "--deps" ]; then
    $SUDO pacman -S --needed $DEPS
    exit 0
fi

meson setup build/compositor compositor --prefix="$PREFIX" --buildtype=release --wipe 2>/dev/null \
    || meson setup build/compositor compositor --prefix="$PREFIX" --buildtype=release
ninja -C build/compositor

$SUDO meson install -C build/compositor
$SUDO install -d "$PREFIX/share/nothing-de/shell/nothing_de" "$PREFIX/share/nothing-de/data/wallpapers"
$SUDO install -m644 shell/nothing_de/*.py "$PREFIX/share/nothing-de/shell/nothing_de/"
$SUDO install -m644 data/wallpapers/* "$PREFIX/share/nothing-de/data/wallpapers/"
for b in bin/*; do $SUDO install -m755 "$b" "$PREFIX/bin/"; done
$SUDO install -Dm644 data/applications/nothing-settings.desktop "$PREFIX/share/applications/nothing-settings.desktop"
# display managers only look in /usr/share/wayland-sessions
$SUDO install -Dm644 data/sessions/nothing.desktop /usr/share/wayland-sessions/nothing.desktop
$SUDO install -Dm644 data/portals/nothing-portals.conf /usr/share/xdg-desktop-portal/nothing-portals.conf
echo "Fertig. Abmelden und im Anmeldebildschirm die Sitzung „Nothing“ wählen."
