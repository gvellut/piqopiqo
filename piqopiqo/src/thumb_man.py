from PySide6.QtCore import QObject, Signal
import multiprocessing
import os
from src.config import Config
from src.thumb_proc import generate_embedded, generate_hq

def worker_task(file_path):
    filename = os.path.basename(file_path)
    cache_path_embedded = os.path.join(Config.CACHE_DIR, f"{os.path.splitext(filename)[0]}_embedded.jpg")
    cache_path_hq = os.path.join(Config.CACHE_DIR, f"{os.path.splitext(filename)[0]}_hq.jpg")

    # Embedded
    if generate_embedded(file_path, cache_path_embedded):
        return ("embedded", file_path, cache_path_embedded)

    # HQ
    if generate_hq(file_path, cache_path_hq, Config.THUMB_MAX_DIM):
        return ("hq", file_path, cache_path_hq)

    return (None, None, None)

def hq_worker_task(file_path):
    filename = os.path.basename(file_path)
    cache_path_hq = os.path.join(Config.CACHE_DIR, f"{os.path.splitext(filename)[0]}_hq.jpg")
    if generate_hq(file_path, cache_path_hq, Config.THUMB_MAX_DIM):
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
        cache_path_hq = os.path.join(Config.CACHE_DIR, f"{os.path.splitext(filename)[0]}_hq.jpg")

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
        self.pool.apply_async(hq_worker_task, (file_path,), callback=self.on_hq_task_done)

    def on_hq_task_done(self, result):
        thumb_type, file_path, cache_path = result
        if file_path and file_path in self.pending:
            self.pending.remove(file_path)
        if thumb_type:
            self.thumb_ready.emit(file_path, thumb_type, cache_path)

    def stop(self):
        self.pool.close()
        self.pool.join()
