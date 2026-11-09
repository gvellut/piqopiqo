from unittest.mock import Mock

import Cocoa

from piqopiqo.external_apps import reveal_in_file_manager_macos
from piqopiqo.model import ImageItem


def test_reveal_photos_sends_one_finder_selection_per_folder(monkeypatch, tmp_path):
    workspace_class = Mock()
    monkeypatch.setattr(Cocoa, "NSWorkspace", workspace_class)
    workspace = workspace_class.sharedWorkspace.return_value
    reveal = workspace.activateFileViewerSelectingURLs_
    first_folder = tmp_path.resolve() / "One"
    second_folder = tmp_path.resolve() / "Two"
    first = first_folder / "first photo.jpg"
    second = first_folder / "second photo.jpg"
    third = second_folder / "first photo.jpg"
    fourth = second_folder / "second photo.jpg"
    photos = [
        ImageItem(path=str(path), name=path.name, created="")
        for path in (first, third, second, fourth)
    ]

    reveal_in_file_manager_macos(photos)

    assert [[url.path() for url in call.args[0]] for call in reveal.call_args_list] == [
        [str(first), str(second)],
        [str(third), str(fourth)],
    ]
