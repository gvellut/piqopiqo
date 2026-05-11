"""Tests for Qt runnable ownership helpers."""

from __future__ import annotations

import ast
import os
from pathlib import Path
import subprocess
import sys


SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / "piqopiqo"
PROJECT_ROOT = SRC_ROOT.parents[1]

EXPECTED_PYTHON_OWNED_RUNNABLES = (
    ("main_window.py", "_WorkspaceCleanupWorker"),
    ("metadata/save_workers.py", "MetadataSaveWorker"),
    ("tools/archive.py", "ArchiveMoveWorker"),
    ("tools/copy_sd.py", "CopySdWorker"),
    ("tools/copy_sd.py", "_ResolveDatesWorker"),
    ("tools/flickr_upload/workers.py", "FlickrLoginWorker"),
    ("tools/flickr_upload/workers.py", "FlickrTokenValidationWorker"),
    ("tools/flickr_upload/workers.py", "FlickrAlbumCheckWorker"),
    ("tools/flickr_upload/workers.py", "FlickrMetadataPrecheckWorker"),
    ("tools/gpx2exif/workers.py", "ExtractGpsTimeShiftWorker"),
    ("tools/gpx2exif/workers.py", "ApplyGpxWorker"),
    ("tools/gpx2exif/workers.py", "ClearGpsWorker"),
)


def test_python_owned_runnable_disables_qt_auto_delete() -> None:
    code = """
from piqopiqo.qt_workers import PythonOwnedRunnable


class _Runnable(PythonOwnedRunnable):
    def run(self) -> None:
        return None


worker = _Runnable()
raise SystemExit(0 if worker.autoDelete() is False else 1)
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT / "src")

    subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(PROJECT_ROOT),
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


def test_production_runnables_use_python_owned_base() -> None:
    for relative_path, class_name in EXPECTED_PYTHON_OWNED_RUNNABLES:
        bases = _class_base_names(SRC_ROOT / relative_path, class_name)

        assert "PythonOwnedRunnable" in bases


def test_no_production_worker_directly_subclasses_qrunnable() -> None:
    direct_subclasses: list[str] = []
    for path in SRC_ROOT.rglob("*.py"):
        if path.name == "qt_workers.py":
            continue
        for class_node in _class_nodes(path):
            if "QRunnable" in _base_names(class_node):
                direct_subclasses.append(
                    f"{path.relative_to(SRC_ROOT)}::{class_node.name}"
                )

    assert direct_subclasses == []


def _class_base_names(path: Path, class_name: str) -> set[str]:
    for class_node in _class_nodes(path):
        if class_node.name == class_name:
            return _base_names(class_node)
    raise AssertionError(f"{class_name} not found in {path}")


def _class_nodes(path: Path) -> list[ast.ClassDef]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]


def _base_names(class_node: ast.ClassDef) -> set[str]:
    return {_base_name(base) for base in class_node.bases}


def _base_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""
