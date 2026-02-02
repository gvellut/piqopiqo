from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QScrollArea, QSizePolicy, QWidget


class ScrollableStrip(QScrollArea):
    """
    Base class for a horizontal filter panel.
    - Autosizes height to fit content exactly.
    - Scrolls horizontally if content is too wide.
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        # 1. ScrollArea Configuration
        self.setWidgetResizable(True)  # Allow inner content to stretch
        self.setFrameShape(QFrame.NoFrame)  # No border
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        # 2. Size Policy: Fixed Height, Preferred Width
        # This tells the parent layout to respect our calculated sizeHint height
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        # 3. Inner Container (The actual panel)
        self._container = QWidget()
        self._layout = QHBoxLayout(self._container)

        # Default styling (Tight fit)
        self._layout.setContentsMargins(4, 4, 4, 4)
        self._layout.setSpacing(8)
        self._layout.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        self.setWidget(self._container)

    def add_widget(self, widget):
        """Use this method to add widgets to the strip."""
        self._layout.addWidget(widget)

    def add_stretch(self):
        """Adds a spacer to push subsequent items to the right."""
        self._layout.addStretch()

    def sizeHint(self):
        """
        Calculates the exact height needed:
        Content Height + Scrollbar Height (if visible).
        """
        # Get the height required by the inner container's content
        content_height = self._container.minimumSizeHint().height()

        # Add scrollbar height if it's currently showing
        scroll_height = 0
        if self.horizontalScrollBar().isVisible():
            scroll_height = self.horizontalScrollBar().height()

        return QSize(super().sizeHint().width(), content_height + scroll_height)

    def resizeEvent(self, event):
        """
        If the width changes, the scrollbar might appear or disappear.
        We must trigger updateGeometry() so sizeHint() is recalled
        and the height adjusts immediately.
        """
        super().resizeEvent(event)
        self.updateGeometry()
