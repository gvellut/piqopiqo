"""Folder scanning utilities."""

from __future__ import annotations

from datetime import datetime
import os

_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png")


def scan_folder(root_path: str) -> tuple[list[dict], list[str]]:
    """Recursively scan a folder for images.

    Returns:
        Tuple of (images list, unique folders list).
        Each image dict contains: path, name, state, created, source_folder.
        Unique folders list contains paths of all folders with images.
    """
    images: list[dict] = []
    unique_folders: set[str] = set()

    for root, _, files in os.walk(root_path):
        folder_has_images = False
        for file in files:
            if not file.lower().endswith(_IMAGE_EXTENSIONS):
                continue

            path = os.path.join(root, file)
            images.append(
                {
                    "path": path,
                    "name": file,
                    "state": 0,  # not processed
                    "created": datetime.fromtimestamp(os.path.getctime(path)).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    ),
                    "source_folder": root,
                }
            )
            folder_has_images = True

        if folder_has_images:
            unique_folders.add(root)

    sorted_images = sorted(images, key=lambda x: x["name"])
    sorted_folders = sorted(unique_folders)

    return sorted_images, sorted_folders
