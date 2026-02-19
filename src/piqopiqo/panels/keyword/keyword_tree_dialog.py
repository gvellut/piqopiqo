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
    QTreeWidgetItemIterator,
    QVBoxLayout,
)

from piqopiqo.keyword_utils import parse_keywords
from piqopiqo.model import ImageItem

from .keyword_tree import KeywordTreeManager

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
        self._editing_finished: bool = False  # Flag to prevent double handling

        self._setup_ui()
        self._populate_tree()

        # Restore expanded state from tree manager
        self._restore_expanded_state()

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

        # Expand all present button
        expand_layout = QHBoxLayout()
        self.expand_present_btn = QPushButton("Expand all present")
        self.expand_present_btn.setToolTip(
            "Expand tree to show all keywords that are present in selected images"
        )
        self.expand_present_btn.clicked.connect(self._on_expand_all_present)
        expand_layout.addWidget(self.expand_present_btn)
        expand_layout.addStretch()
        layout.addLayout(expand_layout)

        # OK/Cancel buttons
        self.btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.btn_box.accepted.connect(self.accept)
        self.btn_box.rejected.connect(self.reject)
        layout.addWidget(self.btn_box)

    def _get_expanded_keywords(self) -> set[str]:
        """Get the set of expanded keyword names."""
        expanded: set[str] = set()
        iterator = QTreeWidgetItemIterator(self.tree)
        while iterator.value():
            item = iterator.value()
            if item and item.isExpanded():
                expanded.add(item.text(0))
            iterator += 1
        return expanded

    def _restore_expanded_from_set(self, expanded: set[str]):
        """Restore expanded state from a set of keyword names."""
        iterator = QTreeWidgetItemIterator(self.tree)
        while iterator.value():
            item = iterator.value()
            if item and item.text(0) in expanded:
                item.setExpanded(True)
            iterator += 1

    def _save_expanded_state(self):
        """Save expanded state to tree manager for persistence during session."""
        self._tree_manager.expanded_keywords = self._get_expanded_keywords()

    def _restore_expanded_state(self):
        """Restore expanded state from tree manager."""
        if hasattr(self._tree_manager, "expanded_keywords"):
            self._restore_expanded_from_set(self._tree_manager.expanded_keywords)

    def _on_expand_all_present(self):
        """Expand tree to show all keywords that are present in selected images.

        This expands parent items to reveal any keywords that are checked or
        partially checked (present in all or some selected images).
        Already expanded items remain expanded.
        """
        # Collect all items that have a present keyword (checked or partially checked)
        items_to_reveal: list[QTreeWidgetItem] = []
        iterator = QTreeWidgetItemIterator(self.tree)
        while iterator.value():
            item = iterator.value()
            if item:
                role = item.data(0, ROLE_TYPE)
                if role in ("KEYWORD", "ADDITIONAL"):
                    check_state = item.checkState(0)
                    if check_state in (
                        Qt.CheckState.Checked,
                        Qt.CheckState.PartiallyChecked,
                    ):
                        items_to_reveal.append(item)
            iterator += 1

        # Expand all ancestors of items with present keywords
        for item in items_to_reveal:
            parent = item.parent()
            while parent:
                parent.setExpanded(True)
                parent = parent.parent()

    def _populate_tree(self, preserve_state: bool = False):
        """Populate the tree from the keyword tree manager.

        Args:
            preserve_state: If True, save and restore expanded state.
        """
        # Save expanded state if requested
        expanded: set[str] = set()
        scroll_value = 0
        if preserve_state:
            expanded = self._get_expanded_keywords()
            scroll_value = self.tree.verticalScrollBar().value()

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

        # Restore expanded state if requested
        if preserve_state:
            self._restore_expanded_from_set(expanded)
            self.tree.verticalScrollBar().setValue(scroll_value)

    def _add_children(self, parent_item: QTreeWidgetItem, node):
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
            new_state = Qt.CheckState.Unchecked
        else:
            # Add to all items (both Checked and PartiallyChecked -> Checked)
            for kws in self._item_keywords.values():
                kws.add(keyword)
            item.setCheckState(0, Qt.CheckState.Checked)
            self._modifications[keyword] = True  # Mark as added
            new_state = Qt.CheckState.Checked

        # Sync all other items with the same keyword name
        self._sync_keyword_check_state(keyword, new_state, exclude_item=item)

        self.tree.blockSignals(False)

    def _sync_keyword_check_state(
        self,
        keyword: str,
        state: Qt.CheckState,
        exclude_item: QTreeWidgetItem | None = None,
    ):
        """Sync the check state of all tree items with the given keyword name.

        Args:
            keyword: The keyword name to sync.
            state: The new check state to apply.
            exclude_item: Optional item to exclude from syncing (already updated).
        """
        iterator = QTreeWidgetItemIterator(self.tree)
        while iterator.value():
            tree_item = iterator.value()
            if tree_item and tree_item is not exclude_item:
                role = tree_item.data(0, ROLE_TYPE)
                if role in ("KEYWORD", "ADDITIONAL") and tree_item.text(0) == keyword:
                    tree_item.setCheckState(0, state)
            iterator += 1

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
        self._editing_finished = False

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

        # Install event filter to catch Enter and Escape
        editor.installEventFilter(self)

        self.tree.setItemWidget(temp_item, 0, editor)
        editor.setFocus()

    def eventFilter(self, obj, event):
        """Handle key events in line editor."""
        if isinstance(obj, QLineEdit) and self._editing_item:
            if event.type() == event.Type.KeyPress:
                if event.key() == Qt.Key.Key_Escape:
                    self._cancel_add_keyword()
                    return True
                elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    self._finish_add_keyword()
                    return True  # Consume the event to prevent dialog close
            elif event.type() == event.Type.FocusOut:
                # Handle focus out - create keyword if text entered, cancel if empty
                if not self._editing_finished:
                    editor = obj
                    if editor.text().strip():
                        self._finish_add_keyword()
                    else:
                        self._cancel_add_keyword()
                return False
        return super().eventFilter(obj, event)

    def _finish_add_keyword(self):
        """Finish adding a keyword after Enter is pressed or focus out with text."""
        if self._editing_finished:
            return
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

        # Mark as finished to prevent double handling
        self._editing_finished = True

        # Find the corresponding node in the tree manager
        role = self._editing_parent.data(0, ROLE_TYPE)
        if role == "ROOT":
            parent_node = self._tree_manager.root
        else:
            parent_name = self._editing_parent.text(0)
            parent_node = self._tree_manager.root.find_node(parent_name)
            if not parent_node:
                self._clear_editing_state()
                return

        # Check if keyword already exists
        for child in parent_node.children:
            if child.name.lower() == keyword.lower():
                QMessageBox.warning(
                    self,
                    "Duplicate Keyword",
                    f'Keyword "{keyword}" already exists under this parent.',
                )
                self._clear_editing_state()
                return

        # Add to tree manager
        parent_node.add_child(keyword)
        self._tree_manager.save()

        # Clear editing state before repopulating
        self._clear_editing_state()

        # Refresh the tree, preserving state
        self._populate_tree(preserve_state=True)

        # Find and scroll to the new keyword
        self._scroll_to_keyword(keyword)

    def _clear_editing_state(self):
        """Clear the editing state variables."""
        if self._editing_item and self._editing_parent:
            idx = self._editing_parent.indexOfChild(self._editing_item)
            if idx >= 0:
                self._editing_parent.takeChild(idx)
        self._editing_item = None
        self._editing_parent = None

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
        if self._editing_finished:
            return
        self._editing_finished = True
        self._clear_editing_state()

    def _delete_keyword(self, item: QTreeWidgetItem):
        """Delete a keyword from the tree."""
        keyword = item.text(0)

        # Check if this keyword has children
        has_children = item.childCount() > 0

        # Build confirmation message
        if has_children:
            msg = f'Delete keyword "{keyword}" and all its children?'
        else:
            msg = f'Delete keyword "{keyword}"?'

        # Confirmation dialog
        reply = QMessageBox.question(
            self,
            "Delete Keyword",
            msg,
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

        # Refresh the tree, preserving expanded state and scroll position
        self._populate_tree(preserve_state=True)

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

        # Refresh the tree, preserving state
        self._populate_tree(preserve_state=True)

    def get_modifications(self) -> dict[str, bool]:
        """Get the keyword modifications made during this session.

        Returns:
            Dictionary mapping keyword names to True (added) or False (removed).
            Only keywords that were actually modified are included.
        """
        return self._modifications.copy()

    def accept(self):
        """Apply modifications and close dialog."""
        # Save expanded state for next opening
        self._save_expanded_state()

        # Emit signal with modifications
        if self._modifications:
            self.keywords_changed.emit(self._modifications)
        super().accept()

    def reject(self):
        """Cancel dialog."""
        # Save expanded state for next opening
        self._save_expanded_state()
        super().reject()
