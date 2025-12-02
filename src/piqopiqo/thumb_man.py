from datetime import datetime
import multiprocessing
import os
import subprocess

from PIL import Image
from PySide6.QtCore import QObject, Signal

from piqopiqo.config import Config


def worker_task(file_path):
    filename = os.path.basename(file_path)
    cache_path_embedded = os.path.join(
        Config.CACHE_DIR, f"{os.path.splitext(filename)[0]}_embedded.jpg"
    )
    cache_path_hq = os.path.join(
        Config.CACHE_DIR, f"{os.path.splitext(filename)[0]}_hq.jpg"
    )

    # Embedded
    if generate_embedded(file_path, cache_path_embedded):
        return ("embedded", file_path, cache_path_embedded)

    # HQ
    if generate_hq(file_path, cache_path_hq, Config.THUMB_MAX_DIM):
        return ("hq", file_path, cache_path_hq)

    return (None, None, None)


def hq_worker_task(file_path):
    filename = os.path.basename(file_path)
    cache_path_hq = os.path.join(
        Config.CACHE_DIR, f"{os.path.splitext(filename)[0]}_hq.jpg"
    )
    if generate_hq(file_path, cache_path_hq, Config.THUMB_MAX_DIM):
        # since process : just the path is sent (must be reread from main workers)
        return ("hq", file_path, cache_path_hq)
    return (None, None, None)


class ThumbnailManager(QObject):
    thumb_ready = Signal(str, str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pool = multiprocessing.Pool(Config.MAX_WORKERS)
        self.pending = set()

    def queue_image(self, file_path):
        if file_path in self.pending:
            return

        self.pending.add(file_path)

        filename = os.path.basename(file_path)
        cache_path_hq = os.path.join(
            Config.CACHE_DIR, f"{os.path.splitext(filename)[0]}_hq.jpg"
        )

        if os.path.exists(cache_path_hq):
            self.thumb_ready.emit(file_path, "hq", cache_path_hq)
            self.pending.remove(file_path)
            return

        self.pool.apply_async(worker_task, (file_path,), callback=self.on_task_done)

    def on_task_done(self, result):
        thumb_type, file_path, cache_path = result
        if file_path and file_path in self.pending:
            self.pending.remove(file_path)

        if thumb_type:
            self.thumb_ready.emit(file_path, thumb_type, cache_path)

            if thumb_type == "embedded":
                self.queue_hq(file_path)

    def queue_hq(self, file_path):
        if file_path in self.pending:
            return

        self.pending.add(file_path)
        self.pool.apply_async(
            hq_worker_task, (file_path,), callback=self.on_hq_task_done
        )

    def on_hq_task_done(self, result):
        thumb_type, file_path, cache_path = result
        if file_path and file_path in self.pending:
            self.pending.remove(file_path)
        if thumb_type:
            self.thumb_ready.emit(file_path, thumb_type, cache_path)

    def stop(self):
        self.pool.close()
        self.pool.join()


def scan_folder(root_path):
    """
    Recursively scans a folder for images.
    """
    images = []
    for root, _, files in os.walk(root_path):
        for file in files:
            if file.lower().endswith((".jpg", ".jpeg", ".png")):
                path = os.path.join(root, file)
                images.append(
                    {
                        "path": path,
                        "name": file,
                        "state": 0,  # not processed
                        "created": datetime.fromtimestamp(
                            os.path.getctime(path)
                        ).strftime("%Y-%m-%d %H:%M:%S"),
                    }
                )
    return sorted(images, key=lambda x: x["name"])


def generate_embedded(source, dest_path):
    """
    Extracts embedded thumbnail from an image using exiftool.
    """
    try:
        cmd = [Config.EXIFTOOL_PATH, "-b", "-ThumbnailImage", source]
        with open(dest_path, "wb") as f:
            subprocess.run(cmd, stdout=f, stderr=subprocess.DEVNULL)
        return os.path.getsize(dest_path) > 0
    except Exception:
        return False


def generate_hq(source, dest_path, max_dim):
    """
    Generates a high-quality thumbnail from an image.
    """
    try:
        img = Image.open(source)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        img.thumbnail((max_dim, max_dim))
        img.save(dest_path, "JPEG", quality=80)
        return True
    except Exception:
        return False
