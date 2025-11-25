from datetime import datetime
import os


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
                        "created": datetime.fromtimestamp(
                            os.path.getctime(path)
                        ).strftime("%Y-%m-%d %H:%M:%S"),
                    }
                )
    return sorted(images, key=lambda x: x["name"])
