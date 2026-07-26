"""Retry/exit dialog for exhausted cache or copy destinations."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from piqopiqo.storage import StorageWriteFault


class StorageFullDialog(QDialog):
    """Modal full-storage dialog with explicit Exit and Retry actions."""

    def __init__(
        self,
        fault: StorageWriteFault,
        *,
        title: str,
        headline: str,
        retry_description: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(560)

        root = QVBoxLayout(self)

        self.headline_label = QLabel(headline, self)
        self.headline_label.setWordWrap(True)
        root.addWidget(self.headline_label)

        self.path_label = QLabel(self)
        self.path_label.setWordWrap(True)
        self.path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        root.addWidget(self.path_label)

        self.error_label = QLabel(self)
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #b00020;")
        self.error_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        root.addWidget(self.error_label)

        retry_label = QLabel(retry_description, self)
        retry_label.setWordWrap(True)
        root.addWidget(retry_label)

        button_row = QHBoxLayout()
        self.exit_button = QPushButton("Exit PiqoPiqo", self)
        self.retry_button = QPushButton("Retry", self)
        self.retry_button.setDefault(True)
        button_row.addWidget(self.exit_button)
        button_row.addStretch(1)
        button_row.addWidget(self.retry_button)
        root.addLayout(button_row)

        self.exit_button.clicked.connect(self.reject)
        self.retry_button.clicked.connect(self.accept)
        self.set_fault(fault)
        self.adjustSize()

    def set_fault(self, fault: StorageWriteFault) -> None:
        self.path_label.setText(f"Storage location:\n{fault.target_path}")
        self.error_label.setText(f"Write error: {fault.error_message}")
        self.adjustSize()


def wait_for_storage_retry(
    *,
    parent: QWidget | None,
    fault: StorageWriteFault,
    retry: Callable[[], StorageWriteFault | None],
    title: str,
    headline: str,
    retry_description: str,
) -> bool:
    """Wait until Retry succeeds or the user chooses Exit PiqoPiqo."""
    dialog = StorageFullDialog(
        fault,
        title=title,
        headline=headline,
        retry_description=retry_description,
        parent=parent,
    )
    current_fault = fault
    while True:
        dialog.set_fault(current_fault)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        try:
            retry_fault = retry()
        except OSError as exc:
            retry_fault = StorageWriteFault(
                target_path=current_fault.target_path,
                operation=current_fault.operation,
                error_message=str(exc) or exc.__class__.__name__,
            )
        if retry_fault is None:
            return True
        current_fault = retry_fault
