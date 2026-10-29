# Local package: makepkg -si
pkgname=nothing-de
pkgver=0.1.0
pkgrel=1
pkgdesc="Nothing OS styled Wayland desktop (compositor, shell, settings)"
arch=(x86_64)
license=(MIT)
depends=(wlroots0.20 xorg-xwayland gtk4 gtk4-layer-shell libadwaita python python-gobject python-cairo python-numpy
         gnome-online-accounts accountsservice polkit-gnome xdg-desktop-portal-gtk xdg-desktop-portal-wlr)
optdepends=('networkmanager: network status and Wi-Fi toggle'
            'wireplumber: volume control'
            'bluez-utils: Bluetooth toggle'
            'grim: screenshots' 'slurp: area screenshots' 'wl-clipboard: copy screenshots'
            'gnome-control-center: adding online accounts (Google, Microsoft, …)'
            'gnome-keyring: storing online account secrets')
makedepends=(meson ninja wayland-protocols)

build() {
  meson setup build "$startdir/compositor" --prefix=/usr --buildtype=release
  ninja -C build
}

package() {
  meson install -C build --destdir "$pkgdir"
  cd "$startdir"
  install -d "$pkgdir/usr/share/nothing-de/shell/nothing_de" "$pkgdir/usr/share/nothing-de/data/wallpapers"
  install -m644 shell/nothing_de/*.py "$pkgdir/usr/share/nothing-de/shell/nothing_de/"
  install -m644 data/wallpapers/* "$pkgdir/usr/share/nothing-de/data/wallpapers/"
  for b in bin/*; do install -Dm755 "$b" "$pkgdir/usr/bin/$(basename "$b")"; done
  install -Dm644 data/applications/nothing-settings.desktop "$pkgdir/usr/share/applications/nothing-settings.desktop"
  install -Dm644 data/sessions/nothing.desktop "$pkgdir/usr/share/wayland-sessions/nothing.desktop"
  install -Dm644 data/portals/nothing-portals.conf "$pkgdir/usr/share/xdg-desktop-portal/nothing-portals.conf"
}
