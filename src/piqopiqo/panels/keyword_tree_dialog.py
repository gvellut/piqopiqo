"""Keyword tree dialog for hierarchical keyword selection."""

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from piqopiqo.keyword_tree import KeywordNode, KeywordTreeManager
from piqopiqo.keyword_utils import parse_keywords
from piqopiqo.model import ImageItem

logger = logging.getLogger(__name__)

ADDITIONAL_KEYWORDS_NAME = "Additional keywords"

# User roles for tree items
ROLE_TYPE = Qt.ItemDataRole.UserRole
ROLE_KEYWORD_PATH = Qt.ItemDataRole.UserRole + 1  # Full path in tree for finding node


class KeywordTreeDialog(QDialog):
    """Dialog for hierarchical keyword selection with tri-state checkboxes."""

    keywords_changed = Signal(dict)  # {keyword: added/removed} for modified keywords

    def __init__(
        self,
        items: list[ImageItem],
        tree_manager: KeywordTreeManager,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Keyword Tree")
        self.setMinimumSize(400, 500)

        self._items = items
        self._tree_manager = tree_manager

        # Track which keywords have been modified during this session
        # key: keyword name, value: True (added) or False (removed)
        self._modifications: dict[str, bool] = {}

        # Gather all current keywords from all items
        # Maps item path -> set of keywords for that item
        self._item_keywords: dict[str, set[str]] = {}
        self._all_keywords: set[str] = set()

        for item in items:
            keywords: set[str] = set()
            if item.db_metadata and item.db_metadata.get("keywords"):
                keywords = set(parse_keywords(item.db_metadata["keywords"]))
            self._item_keywords[item.path] = keywords
            self._all_keywords.update(keywords)

        # For inline editing of new keywords
        self._editing_item: QTreeWidgetItem | None = None
        self._editing_parent: QTreeWidgetItem | None = None

        self._setup_ui()
        self._populate_tree()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Import button at top
        import_layout = QHBoxLayout()
        self.import_btn = QPushButton("Import...")
        self.import_btn.setToolTip("Import keywords from Adobe Bridge format (.txt)")
        self.import_btn.clicked.connect(self._on_import)
        import_layout.addWidget(self.import_btn)
        import_layout.addStretch()
        layout.addLayout(import_layout)

        # Tree widget
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        self.tree.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.tree)

        # OK/Cancel buttons
        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def _populate_tree(self):
        """Populate the tree from the keyword tree manager."""
        self.tree.blockSignals(True)
        self.tree.clear()

        # Get predefined keywords
        predefined = self._tree_manager.root.get_all_keywords()

        # Build the tree recursively
        root_item = QTreeWidgetItem(self.tree, ["Keywords"])
        root_item.setFlags(
            root_item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable  # type: ignore[operator]
        )
        root_item.setData(0, ROLE_TYPE, "ROOT")

        self._add_children(root_item, self._tree_manager.root)

        # Add "Additional keywords" section for keywords not in the tree
        additional = self._all_keywords - predefined
        if additional:
            additional_root = QTreeWidgetItem(self.tree, [ADDITIONAL_KEYWORDS_NAME])
            additional_root.setFlags(
                additional_root.flags() & ~Qt.ItemFlag.ItemIsUserCheckable  # type: ignore[operator]
            )
            additional_root.setData(0, ROLE_TYPE, "ADDITIONAL_ROOT")

            for kw in sorted(additional, key=str.lower):
                child = QTreeWidgetItem(additional_root, [kw])
                child.setData(0, ROLE_TYPE, "ADDITIONAL")
                self._set_check_state_for_keyword(child, kw)

            additional_root.setExpanded(True)

        root_item.setExpanded(True)
        self.tree.blockSignals(False)

    def _add_children(self, parent_item: QTreeWidgetItem, node: KeywordNode):
        """Recursively add children to a tree item."""
        for child in node.children:
            item = QTreeWidgetItem(parent_item, [child.name])
            item.setData(0, ROLE_TYPE, "KEYWORD")
            self._set_check_state_for_keyword(item, child.name)
            self._add_children(item, child)

    def _set_check_state_for_keyword(self, item: QTreeWidgetItem, keyword: str):
        """Set checkbox state based on which items have this keyword."""
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)

        count = sum(1 for kws in self._item_keywords.values() if keyword in kws)
        total = len(self._items)

        if count == 0:
            item.setCheckState(0, Qt.CheckState.Unchecked)
        elif count == total:
            item.setCheckState(0, Qt.CheckState.Checked)
        else:
            item.setCheckState(0, Qt.CheckState.PartiallyChecked)

    def _on_item_changed(self, item: QTreeWidgetItem, column: int):
        """Handle checkbox state change."""
        if column != 0:
            return

        role = item.data(0, ROLE_TYPE)
        if role not in ("KEYWORD", "ADDITIONAL"):
            return

        keyword = item.text(0)
        check_state = item.checkState(0)

        # Block signals to avoid recursive updates
        self.tree.blockSignals(True)

        if check_state == Qt.CheckState.Unchecked:
            # Remove from all items
            for kws in self._item_keywords.values():
                kws.discard(keyword)
            self._modifications[keyword] = False  # Mark as removed
        else:
            # Add to all items (both Checked and PartiallyChecked -> Checked)
            for kws in self._item_keywords.values():
                kws.add(keyword)
            item.setCheckState(0, Qt.CheckState.Checked)
            self._modifications[keyword] = True  # Mark as added

        self.tree.blockSignals(False)

    def _show_context_menu(self, position):
        """Show context menu for tree items."""
        item = self.tree.itemAt(position)
        if not item:
            return

        role = item.data(0, ROLE_TYPE)

        # No context menu for Additional keywords section
        if role in ("ADDITIONAL_ROOT", "ADDITIONAL"):
            return

        menu = QMenu(self)

        # Add keyword action (available on KEYWORD and ROOT)
        if role in ("ROOT", "KEYWORD"):
            add_action = menu.addAction("Add keyword")
            add_action.triggered.connect(lambda: self._add_keyword(item))

        # Delete keyword action (available on KEYWORD only)
        if role == "KEYWORD":
            delete_action = menu.addAction("Delete keyword")
            delete_action.triggered.connect(lambda: self._delete_keyword(item))

        if not menu.isEmpty():
            menu.exec(self.tree.viewport().mapToGlobal(position))

    def _add_keyword(self, parent_item: QTreeWidgetItem):
        """Add a new keyword as child of the selected item."""
        # Create a new item with an editable line edit
        self._editing_parent = parent_item

        # Expand parent so the new item is visible
        parent_item.setExpanded(True)

        # Create temporary item
        temp_item = QTreeWidgetItem(parent_item, [""])
        temp_item.setData(0, ROLE_TYPE, "EDITING")
        temp_item.setFlags(
            temp_item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable  # type: ignore[operator]
        )
        self._editing_item = temp_item

        # Scroll to make it visible
        self.tree.scrollToItem(temp_item)

        # Create inline editor
        editor = QLineEdit()
        editor.setPlaceholderText("Enter keyword name...")
        editor.returnPressed.connect(self._finish_add_keyword)
        editor.editingFinished.connect(self._cancel_add_keyword)

        # Install event filter to catch Escape
        editor.installEventFilter(self)

        self.tree.setItemWidget(temp_item, 0, editor)
        editor.setFocus()

    def eventFilter(self, obj, event):
        """Handle escape key in line editor."""
        if isinstance(obj, QLineEdit):
            if event.type() == event.Type.KeyPress:
                if event.key() == Qt.Key.Key_Escape:
                    self._cancel_add_keyword()
                    return True
        return super().eventFilter(obj, event)

    def _finish_add_keyword(self):
        """Finish adding a keyword after Enter is pressed."""
        if not self._editing_item or not self._editing_parent:
            return

        editor = self.tree.itemWidget(self._editing_item, 0)
        if not isinstance(editor, QLineEdit):
            return

        keyword = editor.text().strip()

        # Remove double quotes from keyword
        keyword = keyword.replace('"', "")

        if not keyword:
            self._cancel_add_keyword()
            return

        # Find the corresponding node in the tree manager
        role = self._editing_parent.data(0, ROLE_TYPE)
        if role == "ROOT":
            parent_node = self._tree_manager.root
        else:
            parent_name = self._editing_parent.text(0)
            parent_node = self._tree_manager.root.find_node(parent_name)
            if not parent_node:
                self._cancel_add_keyword()
                return

        # Check if keyword already exists
        for child in parent_node.children:
            if child.name.lower() == keyword.lower():
                QMessageBox.warning(
                    self,
                    "Duplicate Keyword",
                    f'Keyword "{keyword}" already exists under this parent.',
                )
                self._cancel_add_keyword()
                return

        # Add to tree manager
        parent_node.add_child(keyword)
        self._tree_manager.save()

        # Clear editing state before repopulating
        self._editing_item = None
        self._editing_parent = None

        # Refresh the tree
        self._populate_tree()

        # Find and scroll to the new keyword
        self._scroll_to_keyword(keyword)

    def _scroll_to_keyword(self, keyword: str):
        """Find and scroll to a keyword in the tree."""
        iterator = QTreeWidgetItemIterator(self.tree)
        while iterator.value():
            item = iterator.value()
            if item and item.text(0) == keyword:
                self.tree.scrollToItem(item)
                self.tree.setCurrentItem(item)
                break
            iterator += 1

    def _cancel_add_keyword(self):
        """Cancel adding a keyword."""
        if self._editing_item and self._editing_parent:
            idx = self._editing_parent.indexOfChild(self._editing_item)
            if idx >= 0:
                self._editing_parent.takeChild(idx)
        self._editing_item = None
        self._editing_parent = None

    def _delete_keyword(self, item: QTreeWidgetItem):
        """Delete a keyword from the tree."""
        keyword = item.text(0)

        # Confirmation dialog
        reply = QMessageBox.question(
            self,
            "Delete Keyword",
            f'Delete keyword "{keyword}" and all its children?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # Find and remove from tree
        parent_item = item.parent()
        if not parent_item:
            return

        parent_role = parent_item.data(0, ROLE_TYPE)
        if parent_role == "ROOT":
            parent_node = self._tree_manager.root
        else:
            parent_name = parent_item.text(0)
            parent_node = self._tree_manager.root.find_node(parent_name)

        if parent_node:
            parent_node.remove_child(keyword)
            self._tree_manager.save()

        # Refresh the tree (deleted keyword will show in Additional if checked)
        self._populate_tree()

    def _on_import(self):
        """Handle import button click."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Keywords",
            "",
            "Text files (*.txt);;All files (*)",
        )
        if not file_path:
            return

        count = self._tree_manager.import_adobe_bridge(file_path)

        QMessageBox.information(
            self,
            "Import Complete",
            f"Imported {count} new keywords.",
        )

        # Refresh the tree
        self._populate_tree()

    def get_modifications(self) -> dict[str, bool]:
        """Get the keyword modifications made during this session.

        Returns:
            Dictionary mapping keyword names to True (added) or False (removed).
            Only keywords that were actually modified are included.
        """
        return self._modifications.copy()

    def accept(self):
        """Apply modifications and close dialog."""
        # Emit signal with modifications
        if self._modifications:
            self.keywords_changed.emit(self._modifications)
        super().accept()


# Import at the end to avoid issues
from PySide6.QtWidgets import QTreeWidgetItemIterator  # noqa: E402
