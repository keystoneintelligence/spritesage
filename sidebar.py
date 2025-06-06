"""
SPDX-License-Identifier: GPL-3.0-only
Copyright © 2025 Keystone Intelligence LLC
Licensed under GPL v3 (see LICENSE file for details)
"""

import os
from PySide6 import QtCore, QtWidgets, QtGui
from PySide6.QtCore import Qt, Signal, QModelIndex
from PySide6.QtGui import QIcon, QPainter
from PySide6.QtWidgets import ( QTreeView, QFileSystemModel, QStyledItemDelegate,
                                QMenu, QWidget, QVBoxLayout, QPushButton,
                                QLabel, QSpacerItem, QSizePolicy, QStyleOptionViewItem,
                                QStyle, QApplication )

# Import constants from config.py (adjust path if necessary)
from config import FOLDER_ICON_PATH, IMAGE_ICON_PATH, SPRITE_ICON_PATH, SPRITESHEET_ICON_PATH, UNKNOWN_ICON_PATH, MIN_PANEL_WIDTH, SIDEBAR_ICON_SIZE, SIDEBAR_DEPTH_COLORS

IMAGE_EXTENSIONS = {'.png'}

class SidebarItemDelegate(QStyledItemDelegate):
    """
    Custom delegate to draw specific icons based on file type in the sidebar tree.
    Also handles drawing depth-based color indicators (removed in this version
    as the requirement shifted to file-type icons). If you need the depth colors
    *as well*, the paint method needs further modification to combine both.
    """
    def __init__(self, palette, parent=None):
        super().__init__(parent)
        self.palette = palette
        self._load_icons()
        self.image_extensions = IMAGE_EXTENSIONS

    def _load_icons(self):
        """Load icons once for efficiency."""
        self.folder_icon = QIcon(FOLDER_ICON_PATH)
        self.image_icon = QIcon(IMAGE_ICON_PATH)
        self.sprite_icon = QIcon(SPRITE_ICON_PATH)
        self.spritesheet_icon = QIcon(SPRITESHEET_ICON_PATH)
        self.unknown_icon = QIcon(UNKNOWN_ICON_PATH)

        # Optional: Check if icons loaded correctly (useful for debugging paths)
        if self.folder_icon.isNull(): print("Warning: Could not load folder icon.")
        if self.image_icon.isNull(): print("Warning: Could not load image icon.")
        if self.sprite_icon.isNull(): print("Warning: Could not load sprite icon.")
        if self.spritesheet_icon.isNull(): print("Warning: Could not load spritesheet icon.")
        if self.unknown_icon.isNull(): print("Warning: Could not load unknown icon.")

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex):
        # --- 1. Prepare Style Option ---
        custom_option = QStyleOptionViewItem(option)
        self.initStyleOption(custom_option, index)

        # --- 2. Determine File/Folder Info ---
        model = index.model()
        file_icon_to_draw = self.unknown_icon # Default
        is_dir = False
        file_suffix = ""

        if isinstance(model, QFileSystemModel):
            try:
                file_info = model.fileInfo(index)
                if not file_info.fileName(): # Can happen for root index sometimes
                     is_dir = False # Treat invalid/empty info safely
                else:
                    is_dir = file_info.isDir()
                    file_suffix = file_info.suffix().lower()

                # --- 3. Select Appropriate Icon ---
                if is_dir:
                    file_icon_to_draw = self.folder_icon
                elif f".{file_suffix}" in self.image_extensions:
                     file_icon_to_draw = self.image_icon
                elif file_suffix == "sprite":
                    file_icon_to_draw = self.sprite_icon
                elif file_suffix == "spritesheet":
                    file_icon_to_draw = self.spritesheet_icon
                # else: remains self.unknown_icon
            except Exception as e:
                print(f"Error getting file info for index {index}: {e}")
                # Keep default unknown icon

        # --- 4. Draw Background and Text (Standard Way) ---
        original_icon = custom_option.icon
        custom_option.icon = QIcon() # Clear default icon
        widget = option.widget
        style = widget.style() if widget else QApplication.style() # Use application style as fallback
        # Ensure painter state is saved before drawing control and restored after
        painter.save() # Save before drawControl
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, custom_option, painter, widget)
        painter.restore() # Restore after drawControl
        custom_option.icon = original_icon # Restore for potential future use

        # --- 5. Draw Custom Icon ---
        if not file_icon_to_draw.isNull():
            painter.save() # Save before drawing custom icon
            icon_rect = QtCore.QRect(
                custom_option.rect.left() + 2,
                custom_option.rect.center().y() - SIDEBAR_ICON_SIZE // 2,
                SIDEBAR_ICON_SIZE,
                SIDEBAR_ICON_SIZE
            )

            # --- *** CORRECTION HERE *** ---
            # Use QStyle flags directly
            mode = QIcon.Mode.Normal if (custom_option.state & QStyle.StateFlag.State_Enabled) else QIcon.Mode.Disabled
            state = QIcon.State.On if (custom_option.state & QStyle.StateFlag.State_Selected) else QIcon.State.Off
            # --- *** END CORRECTION *** ---

            pixmap = file_icon_to_draw.pixmap(
                SIDEBAR_ICON_SIZE,
                SIDEBAR_ICON_SIZE,
                mode=mode,
                state=state
            )
            painter.drawPixmap(icon_rect.topLeft(), pixmap)
            painter.restore() # Restore after drawing custom icon

    # sizeHint remains the same as before
    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QtCore.QSize:
        size = super().sizeHint(option, index)
        return size


class SidebarWidget(QtWidgets.QWidget):
    """
    Widget representing the sidebar area.
    Displays initial project buttons OR a file tree view of the current project.
    """
    item_selected = Signal(str)
    new_project_requested = Signal()
    load_project_requested = Signal()

    def __init__(self, palette, parent=None):
        super().__init__(parent)
        self.palette = palette
        self.setMinimumWidth(MIN_PANEL_WIDTH)
        self.current_project_path = None
        self.tree_view = None
        self.model = None
        self.delegate = None
        self.initial_widget = None
        self.new_project_button = None
        self.load_project_button = None
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(5, 5, 5, 5)
        self.main_layout.setSpacing(10)

        self._setup_ui()
        self._apply_styles()
        self.show_initial_view()

    def _setup_ui(self):
        # --- 1. Initial View Widget (Buttons) ---
        self.initial_widget = QWidget(self)
        initial_layout = QVBoxLayout(self.initial_widget)
        initial_layout.setContentsMargins(10, 20, 10, 20)
        initial_layout.setSpacing(15)
        initial_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title_label = QLabel("Project", self.initial_widget)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = title_label.font()
        font.setPointSize(font.pointSize() + 2)
        font.setBold(True)
        title_label.setFont(font)

        self.new_project_button = QPushButton(" New Project", self.initial_widget)
        self.new_project_button.clicked.connect(self.new_project_requested)

        self.load_project_button = QPushButton(" Load Project", self.initial_widget)
        self.load_project_button.clicked.connect(self.load_project_requested)

        initial_layout.addWidget(title_label)
        initial_layout.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding))
        initial_layout.addWidget(self.new_project_button)
        initial_layout.addWidget(self.load_project_button)
        initial_layout.addSpacerItem(QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding))

        self.main_layout.addWidget(self.initial_widget)

        # --- 2. Tree View (Initially Hidden) ---
        self.tree_view = QTreeView(self)
        self.tree_view.setHeaderHidden(True)
        self.tree_view.setIndentation(15)
        self.tree_view.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.tree_view.setDragEnabled(False)
        self.tree_view.setAcceptDrops(False)
        self.tree_view.setDropIndicatorShown(False)
        self.tree_view.setVisible(False)

        self.model = QFileSystemModel(self)
        self.model.setFilter(QtCore.QDir.Filter.AllDirs | QtCore.QDir.Filter.Files | QtCore.QDir.Filter.NoDotAndDotDot)
        self.tree_view.setModel(self.model)

        for i in range(1, self.model.columnCount()):
            self.tree_view.hideColumn(i)

        self.delegate = SidebarItemDelegate(self.palette, self)
        self.tree_view.setItemDelegate(self.delegate)
        self.main_layout.addWidget(self.tree_view)
        self.tree_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree_view.customContextMenuRequested.connect(self._show_context_menu)
        self.tree_view.selectionModel().selectionChanged.connect(self._on_selection_changed)

    def show_initial_view(self):
        self.tree_view.setVisible(False)
        self.initial_widget.setVisible(True)
        self.current_project_path = None
        if self.model:
            self.model.setRootPath("")
        if self.tree_view:
            self.tree_view.setRootIndex(QModelIndex())

    def set_project(self, project_path):
        if project_path and os.path.isdir(project_path):
            self.current_project_path = project_path
            print(f"Sidebar: Loading project {self.current_project_path}")
            root_index = self.model.setRootPath(self.current_project_path)
            self.tree_view.setRootIndex(root_index)
            self.tree_view.scrollToTop()
            self._apply_styles()
            self.initial_widget.setVisible(False)
            self.tree_view.setVisible(True)
        else:
            if project_path:
                print(f"Sidebar Error: Invalid project path provided: {project_path}")
            self.show_initial_view()

    def _apply_styles(self):
        self.setStyleSheet(f"QWidget {{ background-color: {self.palette['widget_bg']}; border: none; color: {self.palette['text_color']}; }}")
        button_style = f"""
            QPushButton {{
                background-color: {self.palette['button_bg']};
                color: {self.palette['button_text']};
                border: 1px solid {self.palette['placeholder_border']};
                padding: 5px 15px;
                min-height: 25px;
                border-radius: 3px;
            }}
            QPushButton:hover {{
                background-color: {QtGui.QColor(self.palette['button_bg']).lighter(115).name()};
            }}
            QPushButton:pressed {{
                background-color: {QtGui.QColor(self.palette['button_bg']).darker(110).name()};
            }}
        """
        if self.new_project_button:
            self.new_project_button.setStyleSheet(button_style)
        if self.load_project_button:
            self.load_project_button.setStyleSheet(button_style)

        if self.tree_view:
            self.tree_view.setStyleSheet(f"""
                QTreeView {{
                    background-color: {self.palette['tree_bg']};
                    color: {self.palette['text_color']};
                    border: none;
                    outline: 0;
                }}
                QTreeView::item {{
                    padding: 3px 0px;
                    color: {self.palette['text_color']};
                    background-color: transparent;
                }}
                QTreeView::item:selected {{
                    background-color: {self.palette['tree_item_selected_bg']};
                    color: {self.palette['tree_item_selected_text']};
                }}
                QTreeView::item:hover {{
                    background-color: {QtGui.QColor(self.palette.get('tree_item_selected_bg', '#A0C8F0')).lighter(115).name()};
                }}
                QTreeView::branch {{
                    background: transparent;
                }}
            """)
            if self.delegate:
                self.tree_view.viewport().update()

    def _show_context_menu(self, pos: QtCore.QPoint):
        if not self.tree_view or not self.tree_view.isVisible(): return
        index = self.tree_view.indexAt(pos)
        if not index.isValid(): return
        file_path = self.model.filePath(index)
        is_dir = self.model.isDir(index)
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background-color: {self.palette['menu_bg']};
                color: {self.palette['menu_text']};
                border: 1px solid {self.palette['placeholder_border']};
            }}
            QMenu::item:selected {{
                background-color: {self.palette['tree_item_selected_bg']};
                color: {self.palette['tree_item_selected_text']};
            }}
        """)
        menu.addAction("TODO: Open")
        menu.addAction("TODO: Show in Explorer/Finder")
        menu.addSeparator()
        menu.addAction("TODO: Rename")
        menu.addAction("TODO: Delete")
        menu.addSeparator()
        if is_dir:
            menu.addAction("TODO: New File")
            menu.addAction("TODO: New Folder")
        global_pos = self.tree_view.viewport().mapToGlobal(pos)
        menu.exec(global_pos)

    def _on_selection_changed(self, selected: QtCore.QItemSelection, deselected: QtCore.QItemSelection):
        if not self.tree_view or not self.tree_view.isVisible(): return
        indexes = selected.indexes()
        if indexes:
            index = indexes[0]
            if index.isValid() and self.model and self.current_project_path:
                file_path = self.model.filePath(index)
                if file_path.startswith(self.current_project_path):
                    self.item_selected.emit(file_path)
                else:
                    self.item_selected.emit("")
            else:
                self.item_selected.emit("")
        else:
            self.item_selected.emit("")