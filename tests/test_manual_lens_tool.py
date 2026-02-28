"""Tests for the Set Lens Info tool workflow."""

from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
import pytest

from piqopiqo.cache_paths import set_cache_base_dir
from piqopiqo.metadata.db_fields import DBFields
from piqopiqo.metadata.metadata_db import MetadataDBManager
from piqopiqo.model import ImageItem, ManualLensPreset
from piqopiqo.ssf.settings_state import (
    UserSettingKey,
    init_qsettings_store,
    set_user_setting,
)
from piqopiqo.tools import manual_lens


@pytest.fixture
def qapp(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _item(path: str, source_folder: str) -> ImageItem:
    return ImageItem(
        path=path,
        name=path.split("/")[-1],
        created="2020-01-01 00:00:00",
        source_folder=source_folder,
        db_metadata={
            DBFields.TITLE: "Title",
            DBFields.DESCRIPTION: None,
            DBFields.LATITUDE: None,
            DBFields.LONGITUDE: None,
            DBFields.KEYWORDS: None,
            DBFields.TIME_TAKEN: None,
            DBFields.LABEL: None,
            DBFields.ORIENTATION: 1,
        },
    )


class _ImmediatePool:
    def __init__(self) -> None:
        self.started = 0

    def start(self, worker) -> None:
        self.started += 1
        worker.run()


class _StatusBar:
    def __init__(self) -> None:
        self.messages: list[tuple[str, int]] = []

    def showMessage(self, text: str, timeout_ms: int) -> None:  # noqa: N802
        self.messages.append((text, timeout_ms))


class _WindowStub:
    def __init__(
        self,
        *,
        db_manager: MetadataDBManager,
        selected_items: list[ImageItem],
        visible_items: list[ImageItem],
    ):
        self.db_manager = db_manager
        self.photo_model = SimpleNamespace(
            get_selected_photos=lambda: list(selected_items),
        )
        self.images_data = list(visible_items)
        self.status_bar = _StatusBar()
        self._background_db_save_pool = _ImmediatePool()
        self.synced: list[tuple[set[str], str]] = []

    def sync_model_after_metadata_update(
        self,
        changed_fields: set[str],
        source: str,
        allow_fullscreen_filter: bool = False,
    ) -> None:
        self.synced.append((set(changed_fields), source))


def test_lens_selection_dialog_requires_explicit_choice(qapp):  # noqa: ARG001
    preset = ManualLensPreset(
        lens_make="Samyang",
        lens_model="Samyang 12mm f/2.0 NCS CS",
        focal_length="12",
        focal_length_35mm="18",
    )
    dialog = manual_lens.LensSelectionDialog([preset])

    assert dialog.combo.currentIndex() == 0
    assert dialog.ok_btn.isEnabled() is False
    assert dialog.selected_preset is None
    assert dialog.selected_clear is False

    dialog.combo.setCurrentIndex(1)
    assert dialog.ok_btn.isEnabled() is True
    assert dialog.selected_preset is None
    assert dialog.selected_clear is True

    dialog.combo.setCurrentIndex(2)
    assert dialog.ok_btn.isEnabled() is True
    assert dialog.selected_preset == preset
    assert dialog.selected_clear is False


def test_launch_manual_lens_warns_when_no_presets(tmp_path, monkeypatch):
    set_cache_base_dir(tmp_path / "cache")
    init_qsettings_store(dyn=True)
    set_user_setting(UserSettingKey.MANUAL_LENSES, [])

    dbm = MetadataDBManager()
    folder = tmp_path / "photos"
    folder.mkdir(parents=True)
    item = _item(str(folder / "a.jpg"), str(folder))
    window = _WindowStub(db_manager=dbm, selected_items=[item], visible_items=[item])

    warnings: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda _parent, _title, text: warnings.append(str(text)),
    )

    manual_lens.launch_manual_lens(window)
    assert warnings
    assert "No lens presets found" in warnings[0]


def test_launch_manual_lens_falls_back_to_visible_when_no_selection(
    tmp_path, monkeypatch
):
    set_cache_base_dir(tmp_path / "cache")
    init_qsettings_store(dyn=True)
    preset = ManualLensPreset(
        lens_make="Samyang",
        lens_model="Samyang 12mm f/2.0 NCS CS",
        focal_length="12",
        focal_length_35mm="18",
    )
    set_user_setting(UserSettingKey.MANUAL_LENSES, [preset])

    folder = tmp_path / "photos"
    folder.mkdir(parents=True)
    item_a = _item(str(folder / "a.jpg"), str(folder))
    item_b = _item(str(folder / "b.jpg"), str(folder))

    dbm = MetadataDBManager()
    window = _WindowStub(
        db_manager=dbm,
        selected_items=[],
        visible_items=[item_a, item_b],
    )

    class _PickerStub:
        def __init__(self, _presets, parent=None):
            self.selected_preset = preset

        def exec(self):
            return QDialog.DialogCode.Accepted

    monkeypatch.setattr(manual_lens, "LensSelectionDialog", _PickerStub)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Ok,
    )

    manual_lens.launch_manual_lens(window)

    assert item_a.db_metadata[DBFields.MANUAL_LENS_MODEL] == preset.lens_model
    assert item_b.db_metadata[DBFields.MANUAL_LENS_MODEL] == preset.lens_model
    assert window.synced == [(set(DBFields.MANUAL_LENS_FIELDS), "manual_lens")]


def test_launch_manual_lens_prioritizes_selected_items(tmp_path, monkeypatch):
    set_cache_base_dir(tmp_path / "cache")
    init_qsettings_store(dyn=True)
    preset = ManualLensPreset(
        lens_make="Sigma",
        lens_model="Sigma 18-35mm F1.8",
        focal_length="24.5",
        focal_length_35mm="36",
    )
    set_user_setting(UserSettingKey.MANUAL_LENSES, [preset])

    folder = tmp_path / "photos"
    folder.mkdir(parents=True)
    selected = _item(str(folder / "selected.jpg"), str(folder))
    not_selected = _item(str(folder / "not-selected.jpg"), str(folder))

    dbm = MetadataDBManager()
    window = _WindowStub(
        db_manager=dbm,
        selected_items=[selected],
        visible_items=[selected, not_selected],
    )

    class _PickerStub:
        def __init__(self, _presets, parent=None):
            self.selected_preset = preset

        def exec(self):
            return QDialog.DialogCode.Accepted

    monkeypatch.setattr(manual_lens, "LensSelectionDialog", _PickerStub)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Ok,
    )

    manual_lens.launch_manual_lens(window)

    assert selected.db_metadata[DBFields.MANUAL_LENS_MODEL] == preset.lens_model
    assert not_selected.db_metadata.get(DBFields.MANUAL_LENS_MODEL) is None


def test_launch_manual_lens_clear_option_clears_all_manual_lens_fields(
    tmp_path, monkeypatch
):
    set_cache_base_dir(tmp_path / "cache")
    init_qsettings_store(dyn=True)
    preset = ManualLensPreset(
        lens_make="Samyang",
        lens_model="Samyang 12mm f/2.0 NCS CS",
        focal_length="12",
        focal_length_35mm="18",
    )
    set_user_setting(UserSettingKey.MANUAL_LENSES, [preset])

    folder = tmp_path / "photos"
    folder.mkdir(parents=True)
    item = _item(str(folder / "selected.jpg"), str(folder))
    item.db_metadata[DBFields.MANUAL_LENS_MAKE] = "Old Make"
    item.db_metadata[DBFields.MANUAL_LENS_MODEL] = "Old Model"
    item.db_metadata[DBFields.MANUAL_FOCAL_LENGTH] = "33"
    item.db_metadata[DBFields.MANUAL_FOCAL_LENGTH_35MM] = "50"

    dbm = MetadataDBManager()
    window = _WindowStub(
        db_manager=dbm,
        selected_items=[item],
        visible_items=[item],
    )

    class _PickerStub:
        def __init__(self, _presets, parent=None):
            self.selected_preset = None
            self.selected_clear = True

        def exec(self):
            return QDialog.DialogCode.Accepted

    confirm_texts: list[str] = []

    def _question_stub(_parent, _title, text, *_args, **_kwargs):
        confirm_texts.append(str(text))
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(manual_lens, "LensSelectionDialog", _PickerStub)
    monkeypatch.setattr(QMessageBox, "question", _question_stub)

    manual_lens.launch_manual_lens(window)

    assert "The lens information will be cleared" in confirm_texts[0]
    assert item.db_metadata[DBFields.MANUAL_LENS_MAKE] is None
    assert item.db_metadata[DBFields.MANUAL_LENS_MODEL] is None
    assert item.db_metadata[DBFields.MANUAL_FOCAL_LENGTH] is None
    assert item.db_metadata[DBFields.MANUAL_FOCAL_LENGTH_35MM] is None
