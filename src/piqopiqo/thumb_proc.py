import os
import subprocess

from PIL import Image

from piqopiqo.config import Config


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
