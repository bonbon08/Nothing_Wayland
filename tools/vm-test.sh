#!/bin/sh
# Test the Nothing desktop in a throwaway Arch Linux VM (QEMU/KVM).
#
#   tools/vm-test.sh create            download the Arch cloud image, create disk + cloud-init seed
#   tools/vm-test.sh start [WxH]       boot the VM headless (default 1920x1080)
#   tools/vm-test.sh provision         install dependencies, this repo and tty1 autologin into the session
#   tools/vm-test.sh deploy            copy the working tree into the VM and reinstall
#   tools/vm-test.sh ssh [CMD]         shell / command in the VM (user "nothing", password "nothing")
#   tools/vm-test.sh key KEY...        send keys through the QEMU monitor, e.g. meta_l-spc  esc  n o t h i n g ret
#   tools/vm-test.sh click X Y [right] click at screen coordinates (usb-tablet)
#   tools/vm-test.sh drag X1 Y1 X2 Y2  press at X1/Y1, move in steps, release at X2/Y2
#   tools/vm-test.sh shot FILE.png     screenshot of the VM display
#   tools/vm-test.sh stop              power off
#
# State lives in $NOTHING_VM_DIR (default ~/.cache/nothing-vm).
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIR="${NOTHING_VM_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/nothing-vm}"
IMAGE_URL="https://fastly.mirror.pkgbuild.com/images/latest/Arch-Linux-x86_64-cloudimg.qcow2"
PORT="${NOTHING_VM_SSH_PORT:-2222}"
PACKAGES="wlroots0.20 xorg-xwayland gtk4 gtk4-layer-shell libadwaita python-gobject python-cairo python-numpy
meson ninja gcc pkgconf wayland-protocols gnome-online-accounts accountsservice polkit-gnome
networkmanager pipewire wireplumber pipewire-pulse xdg-desktop-portal-gtk adwaita-icon-theme
adwaita-fonts noto-fonts mesa librsvg grim wl-clipboard xterm xorg-xeyes foot nautilus gnome-console
gnome-text-editor"
mkdir -p "$DIR"

vm_ssh() {
    ssh -q -i "$DIR/key" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
        -o ConnectTimeout=5 -p "$PORT" nothing@127.0.0.1 "$@"
}

size() { cat "$DIR/size" 2>/dev/null || echo 1920x1080; }

case "$1" in
create)
    [ -f "$DIR/arch.qcow2" ] || curl -fL -o "$DIR/arch.qcow2" "$IMAGE_URL"
    rm -f "$DIR/disk.qcow2"
    qemu-img create -f qcow2 -b "$DIR/arch.qcow2" -F qcow2 "$DIR/disk.qcow2" 20G >/dev/null
    [ -f "$DIR/key" ] || ssh-keygen -q -t ed25519 -N "" -f "$DIR/key"
    cat > "$DIR/user-data" <<EOF
#cloud-config
hostname: nothing-vm
users:
  - name: nothing
    gecos: Nothing Tester
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
    lock_passwd: false
    plain_text_passwd: nothing
    ssh_authorized_keys:
      - $(cat "$DIR/key.pub")
EOF
    printf 'instance-id: nothing-vm\nlocal-hostname: nothing-vm\n' > "$DIR/meta-data"
    genisoimage -quiet -output "$DIR/seed.iso" -volid cidata -joliet -rock "$DIR/user-data" "$DIR/meta-data"
    echo "created in $DIR"
    ;;
start)
    res="${2:-1920x1080}"
    echo "$res" > "$DIR/size"
    qemu-system-x86_64 -enable-kvm -cpu host -smp 4 -m 6144 -machine q35 \
        -drive file="$DIR/disk.qcow2",if=virtio -drive file="$DIR/seed.iso",media=cdrom \
        -device virtio-vga,xres="${res%x*}",yres="${res#*x}" -display none \
        -device qemu-xhci -device usb-tablet -device usb-kbd \
        -nic user,model=virtio-net-pci,hostfwd=tcp:127.0.0.1:"$PORT"-:22 \
        -monitor unix:"$DIR/mon.sock",server,nowait -qmp unix:"$DIR/qmp.sock",server,nowait \
        -serial file:"$DIR/serial.log" -pidfile "$DIR/qemu.pid" -daemonize
    printf 'waiting for ssh'
    until vm_ssh true 2>/dev/null; do printf .; sleep 3; done; echo
    ;;
provision)
    vm_ssh "cloud-init status --wait >/dev/null; sudo pacman -Syu --noconfirm --needed $(echo $PACKAGES)"
    "$0" deploy
    vm_ssh 'sudo mkdir -p /etc/systemd/system/getty@tty1.service.d
printf "[Service]\nExecStart=\nExecStart=-/sbin/agetty --autologin nothing --noclear %%I \$TERM\n" |
    sudo tee /etc/systemd/system/getty@tty1.service.d/autologin.conf >/dev/null
cat > ~/.bash_profile <<"EOF"
[[ -f ~/.bashrc ]] && . ~/.bashrc
if [ "$(tty)" = /dev/tty1 ] && [ -z "$WAYLAND_DISPLAY" ]; then
    exec nothing-session > /tmp/session.log 2>&1
fi
EOF
sudo systemctl daemon-reload && sudo systemctl restart getty@tty1'
    echo "session running — try: $0 shot desktop.png"
    ;;
deploy)
    (cd "$ROOT" && tar --exclude=./build --exclude=./.git -cf - .) |
        vm_ssh 'rm -rf ~/Nothing_Wayland && mkdir ~/Nothing_Wayland && tar -xf - -C ~/Nothing_Wayland &&
                cd ~/Nothing_Wayland && PREFIX=/usr ./install.sh >/tmp/install.log 2>&1 && tail -1 /tmp/install.log'
    ;;
ssh)
    shift
    vm_ssh "$@"
    ;;
key)
    shift
    python3 - "$DIR/mon.sock" "$@" <<'PY'
import socket, sys, time
s = socket.socket(socket.AF_UNIX); s.connect(sys.argv[1]); time.sleep(.2); s.recv(4096)
for k in sys.argv[2:]:
    s.sendall(f"sendkey {k}\n".encode()); time.sleep(.35)
PY
    ;;
click)
    python3 - "$DIR/qmp.sock" "$(size)" "$2" "$3" "${4:-left}" <<'PY'
import json, socket, sys, time
sock, size, x, y, button = sys.argv[1:]
w, h = map(int, size.split("x"))
s = socket.socket(socket.AF_UNIX); s.connect(sock); f = s.makefile("rw")
f.readline(); f.write(json.dumps({"execute": "qmp_capabilities"}) + "\n"); f.flush(); f.readline()
def ev(events):
    f.write(json.dumps({"execute": "input-send-event", "arguments": {"events": events}}) + "\n")
    f.flush(); f.readline()
ev([{"type": "abs", "data": {"axis": "x", "value": int(x) * 32767 // w}},
    {"type": "abs", "data": {"axis": "y", "value": int(y) * 32767 // h}}])
time.sleep(.3)
ev([{"type": "btn", "data": {"down": True, "button": button}}]); time.sleep(.1)
ev([{"type": "btn", "data": {"down": False, "button": button}}])
PY
    ;;
drag)
    python3 - "$DIR/qmp.sock" "$(size)" "$2" "$3" "$4" "$5" <<'PY'
import json, socket, sys, time
sock, size, x1, y1, x2, y2 = sys.argv[1:]
w, h = map(int, size.split("x"))
x1, y1, x2, y2 = map(int, (x1, y1, x2, y2))
s = socket.socket(socket.AF_UNIX); s.connect(sock); f = s.makefile("rw")
f.readline(); f.write(json.dumps({"execute": "qmp_capabilities"}) + "\n"); f.flush(); f.readline()
def ev(events):
    f.write(json.dumps({"execute": "input-send-event", "arguments": {"events": events}}) + "\n")
    f.flush(); f.readline()
def move(x, y):
    ev([{"type": "abs", "data": {"axis": "x", "value": x * 32767 // w}},
        {"type": "abs", "data": {"axis": "y", "value": y * 32767 // h}}])
move(x1, y1); time.sleep(.3)
ev([{"type": "btn", "data": {"down": True, "button": "left"}}]); time.sleep(.2)
steps = 25
for i in range(1, steps + 1):
    move(x1 + (x2 - x1) * i // steps, y1 + (y2 - y1) * i // steps); time.sleep(.04)
time.sleep(.5)
ev([{"type": "btn", "data": {"down": False, "button": "left"}}])
PY
    ;;
shot)
    out="$(realpath -m "$2")"
    python3 - "$DIR/mon.sock" "$DIR/shot.ppm" "$out" <<'PY'
import os, socket, struct, sys, time, zlib
mon, ppm, out = sys.argv[1:]
if os.path.exists(ppm):
    os.unlink(ppm)
s = socket.socket(socket.AF_UNIX); s.connect(mon); time.sleep(.2); s.recv(4096)
s.sendall(f"screendump {ppm}\n".encode())
for _ in range(50):
    time.sleep(.1)
    if os.path.exists(ppm) and os.path.getsize(ppm) > 1000:
        break
time.sleep(.3)
head, dims, _maxval, px = open(ppm, "rb").read().split(b"\n", 3)
w, h = map(int, dims.split())
raw = b"".join(b"\0" + px[y * w * 3:(y + 1) * w * 3] for y in range(h))
chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
open(out, "wb").write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                      + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))
print(out)
PY
    ;;
stop)
    vm_ssh 'sudo poweroff' 2>/dev/null || true
    ;;
*)
    sed -n '2,15p' "$0"
    exit 1
    ;;
esac
