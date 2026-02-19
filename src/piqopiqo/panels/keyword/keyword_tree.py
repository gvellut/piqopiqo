"""Keyword tree data model and persistence.

Manages hierarchical keyword structure with JSON persistence.
"""

import json
import logging
from pathlib import Path

from attrs import define, field

from piqopiqo.settings_state import (
    RuntimeSettingKey,
    get_runtime_setting,
    get_support_dir,
)

logger = logging.getLogger(__name__)

KEYWORD_TREE_FILE = "keyword-tree.json"


@define
class KeywordNode:
    """A node in the keyword tree."""

    name: str
    children: list["KeywordNode"] = field(factory=list)

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        return {
            "name": self.name,
            "children": [c.to_dict() for c in self.children],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "KeywordNode":
        """Create from JSON dict."""
        return cls(
            name=data["name"],
            children=[cls.from_dict(c) for c in data.get("children", [])],
        )

    def get_all_keywords(self) -> set[str]:
        """Get all keyword names in this subtree (excluding this node).

        Returns:
            Set of all keyword names from children recursively.
        """
        keywords: set[str] = set()
        for child in self.children:
            keywords.add(child.name)
            keywords.update(child.get_all_keywords())
        return keywords

    def find_node(self, name: str) -> "KeywordNode | None":
        """Find a node by name in this subtree.

        Args:
            name: The keyword name to find.

        Returns:
            The node if found, None otherwise.
        """
        for child in self.children:
            if child.name == name:
                return child
            found = child.find_node(name)
            if found:
                return found
        return None

    def find_parent_of(self, name: str) -> "KeywordNode | None":
        """Find the parent node of a keyword by name.

        Args:
            name: The keyword name to find the parent of.

        Returns:
            The parent node if found, None otherwise.
        """
        for child in self.children:
            if child.name == name:
                return self
            found = child.find_parent_of(name)
            if found:
                return found
        return None

    def add_child(self, name: str) -> "KeywordNode":
        """Add a child node, maintaining alphabetical order.

        Args:
            name: The keyword name to add.

        Returns:
            The newly created node.
        """
        new_node = KeywordNode(name=name)
        self.children.append(new_node)
        self.children.sort(key=lambda n: n.name.lower())
        return new_node

    def remove_child(self, name: str) -> bool:
        """Remove a child by name.

        Args:
            name: The keyword name to remove.

        Returns:
            True if found and removed, False otherwise.
        """
        for i, child in enumerate(self.children):
            if child.name == name:
                del self.children[i]
                return True
        return False

    def sort_children_recursive(self) -> None:
        """Sort children alphabetically at all levels."""
        self.children.sort(key=lambda n: n.name.lower())
        for child in self.children:
            child.sort_children_recursive()


class KeywordTreeManager:
    """Manages the keyword tree persistence and operations."""

    def __init__(self):
        self._root: KeywordNode = KeywordNode(name="Keywords")
        self._loaded = False
        # Track expanded state between dialog openings (not persisted to JSON)
        self.expanded_keywords: set[str] = {"Keywords"}

    @property
    def root(self) -> KeywordNode:
        """Get the root node, loading from file if needed."""
        if not self._loaded and not get_runtime_setting(
            RuntimeSettingKey.DETACHED_KEYWORD_TREE
        ):
            self.load()
        return self._root

    def get_tree_path(self) -> Path:
        """Get the path to the keyword tree JSON file."""
        return get_support_dir() / KEYWORD_TREE_FILE

    def load(self) -> bool:
        """Load the keyword tree from file.

        Returns:
            True if loaded successfully, False otherwise.
        """
        if get_runtime_setting(RuntimeSettingKey.DETACHED_KEYWORD_TREE):
            self._loaded = True
            return False

        path = self.get_tree_path()
        if not path.exists():
            self._loaded = True
            return False

        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)

            if "tree" in data:
                self._root = KeywordNode.from_dict(data["tree"])

            self._loaded = True
            logger.debug(f"Loaded keyword tree from {path}")
            return True
        except (OSError, json.JSONDecodeError) as e:
            logger.error(f"Failed to load keyword tree: {e}")
            self._loaded = True
            return False

    def save(self) -> bool:
        """Save the keyword tree to file.

        Returns:
            True if saved successfully, False otherwise.
        """
        if get_runtime_setting(RuntimeSettingKey.DETACHED_KEYWORD_TREE):
            return False

        path = self.get_tree_path()

        try:
            data = {
                "version": 1,
                "tree": self._root.to_dict(),
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            logger.debug(f"Saved keyword tree to {path}")
            return True
        except OSError as e:
            logger.error(f"Failed to save keyword tree: {e}")
            return False

    def import_adobe_bridge(self, file_path: str) -> int:
        """Import keywords from Adobe Bridge tab-indented format.

        The file format uses tabs for indentation levels:
        ```
        Camera
            7artisans
                ufo lens
        Event
            christmas
        ```

        Args:
            file_path: Path to the Adobe Bridge keyword file.

        Returns:
            Number of new keywords imported.
        """
        count = 0
        try:
            with open(file_path, encoding="utf-8") as f:
                lines = f.readlines()

            # Stack: list of (indent_level, node)
            stack: list[tuple[int, KeywordNode]] = [(-1, self._root)]

            for line in lines:
                if not line.strip():
                    continue

                # Count leading tabs
                indent = 0
                for char in line:
                    if char == "\t":
                        indent += 1
                    else:
                        break

                keyword = line.strip()
                if not keyword:
                    continue

                # Remove double quotes from keyword if present
                keyword = keyword.replace('"', "")

                # Pop stack to find parent at correct level
                while stack and stack[-1][0] >= indent:
                    stack.pop()

                parent = stack[-1][1] if stack else self._root

                # Check if keyword already exists under this parent
                existing = None
                for child in parent.children:
                    if child.name.lower() == keyword.lower():
                        existing = child
                        break

                if existing:
                    node = existing
                else:
                    node = parent.add_child(keyword)
                    count += 1

                stack.append((indent, node))

            # Save after import
            self.save()

        except OSError as e:
            logger.error(f"Failed to import keyword file: {e}")

        return count

    def reset(self) -> None:
        """Reset the tree to empty state."""
        self._root = KeywordNode(name="Keywords")
        self._loaded = True
