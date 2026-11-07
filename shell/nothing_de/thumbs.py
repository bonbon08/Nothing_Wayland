"""Bilder verkleinert laden, ohne die Oberfläche anzuhalten.

GdkPixbuf dekodiert in einem Hintergrund-Thread (es kennt mehr Formate als Gtk.Picture allein,
etwa JPEG XL und WebP); das Ergebnis kommt im Haupt-Thread als Gdk.Texture an. Vorschaubilder
landen zusätzlich als PNG in ~/.cache/nothing-de/thumbs, das nächste Mal geht es sofort.
"""
import hashlib
import os
import queue
import threading

from gi.repository import Gdk, GdkPixbuf, GLib

CACHE = os.path.join(GLib.get_user_cache_dir(), "nothing-de", "thumbs")
_jobs = queue.Queue()
_worker = None


def _cache_path(path, w, h):
    try:
        st = os.stat(path)
    except OSError:
        return None
    key = f"{path}:{st.st_mtime_ns}:{st.st_size}:{w}x{h}".encode()
    return os.path.join(CACHE, hashlib.sha1(key).hexdigest() + ".png")


def _load(path, w, h, cache):
    cached = _cache_path(path, w, h) if cache else None
    if cached and os.path.exists(cached):
        try:
            return GdkPixbuf.Pixbuf.new_from_file(cached)
        except GLib.Error:
            pass
    pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, w, h, True)
    if cached:
        try:
            os.makedirs(CACHE, exist_ok=True)
            pb.savev(cached + ".tmp", "png", [], [])
            os.replace(cached + ".tmp", cached)
        except (GLib.Error, OSError):
            pass
    return pb


def _run():
    while True:
        path, w, h, cache, callback = _jobs.get()
        try:
            pb = _load(path, w, h, cache)
        except GLib.Error:
            pb = None
        GLib.idle_add(lambda pb=pb, cb=callback: (cb(Gdk.Texture.new_for_pixbuf(pb)
                                                      if pb else None), False)[1])


def load_async(path, width, height, callback, cache=True):
    """callback(Gdk.Texture or None) in the main thread; one worker, jobs in order."""
    global _worker
    if _worker is None:
        _worker = threading.Thread(target=_run, daemon=True, name="thumbs")
        _worker.start()
    _jobs.put((path, width, height, cache, callback))
