"""
SPDX-License-Identifier: GPL-3.0-only
Copyright © 2025 Keystone Intelligence LLC
Licensed under GPL v3 (see LICENSE file for details)
"""

import os
import shutil
import sys
from typing import Any, cast

from PySide6 import QtCore, QtWidgets, QtGui
from PySide6.QtCore import Qt, Signal, QModelIndex
from PySide6.QtGui import QIcon, QPainter
from PySide6.QtWidgets import (
    QTreeView,
    QFileSystemModel,
    QStyledItemDelegate,
    QMenu,
    QWidget,
    QVBoxLayout,
    QPushButton,
    QLabel,
    QSpacerItem,
    QSizePolicy,
    QStyleOptionViewItem,
    QStyle,
    QApplication,
    QListWidget,
    QListWidgetItem,
)

# Import constants from config.py (adjust path if necessary)
from .config import (
    FOLDER_ICON_PATH,
    IMAGE_ICON_PATH,
    SPRITE_ICON_PATH,
    SPRITESHEET_ICON_PATH,
    UNKNOWN_ICON_PATH,
    MIN_PANEL_WIDTH,
    SIDEBAR_ICON_SIZE,
    SIDEBAR_DEPTH_COLORS,
)
from .recent_projects import RecentProject, recent_project_label

IMAGE_EXTENSIONS = {".png"}


class SidebarItemDelegate(QStyledItemDelegate):
    """
    Custom delegate to draw specific icons based on file type in the sidebar tree.
    Also handles drawing depth-based color indicators (removed in this version
    as the requirement shifted to file-type icons). If you need the depth colors
    *as well*, the paint method needs further modification to combine both.
    """

    def __init__(self, palette, parent=None):
        super().__init__(parent)
        self.app_palette = palette
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
        if self.folder_icon.isNull():
            print("Warning: Could not load folder icon.")
        if self.image_icon.isNull():
            print("Warning: Could not load image icon.")
        if self.sprite_icon.isNull():
            print("Warning: Could not load sprite icon.")
        if self.spritesheet_icon.isNull():
            print("Warning: Could not load spritesheet icon.")
        if self.unknown_icon.isNull():
            print("Warning: Could not load unknown icon.")

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex):
        # --- 1. Prepare Style Option ---
        custom_option = cast(Any, QStyleOptionViewItem(option))
        option_any = cast(Any, option)
        self.initStyleOption(custom_option, index)

        # --- 2. Determine File/Folder Info ---
        model = index.model()
        file_icon_to_draw = self.unknown_icon  # Default
        is_dir = False
        file_suffix = ""

        if isinstance(model, QFileSystemModel):
            try:
                file_info = model.fileInfo(index)
                if not file_info.fileName():  # Can happen for root index sometimes
                    is_dir = False  # Treat invalid/empty info safely
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
        custom_option.icon = QIcon()  # Clear default icon
        widget = option_any.widget
        style = (
            widget.style() if widget else QApplication.style()
        )  # Use application style as fallback
        # Ensure painter state is saved before drawing control and restored after
        painter.save()  # Save before drawControl
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, custom_option, painter, widget)
        painter.restore()  # Restore after drawControl
        custom_option.icon = original_icon  # Restore for potential future use

        # --- 5. Draw Custom Icon ---
        if not file_icon_to_draw.isNull():
            painter.save()  # Save before drawing custom icon
            icon_rect = QtCore.QRect(
                custom_option.rect.left() + 2,
                custom_option.rect.center().y() - SIDEBAR_ICON_SIZE // 2,
                SIDEBAR_ICON_SIZE,
                SIDEBAR_ICON_SIZE,
            )

            # --- *** CORRECTION HERE *** ---
            # Use QStyle flags directly
            mode = (
                QIcon.Mode.Normal
                if (custom_option.state & QStyle.StateFlag.State_Enabled)
                else QIcon.Mode.Disabled
            )
            state = (
                QIcon.State.On
                if (custom_option.state & QStyle.StateFlag.State_Selected)
                else QIcon.State.Off
            )
            # --- *** END CORRECTION *** ---

            pixmap = file_icon_to_draw.pixmap(
                SIDEBAR_ICON_SIZE, SIDEBAR_ICON_SIZE, mode=mode, state=state
            )
            painter.drawPixmap(icon_rect.topLeft(), pixmap)
            painter.restore()  # Restore after drawing custom icon

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
    file_renamed = Signal(str, str)
    file_deleted = Signal(str)
    new_project_requested = Signal()
    load_project_requested = Signal()
    recent_project_requested = Signal(str)

    def __init__(self, palette, parent=None):
        super().__init__(parent)
        self.app_palette = palette
        self.setMinimumWidth(MIN_PANEL_WIDTH)
        self.current_project_path: str | None = None
        self.tree_view: QTreeView
        self.model: QFileSystemModel
        self.delegate: SidebarItemDelegate
        self.initial_widget: QWidget
        self.new_project_button: QPushButton
        self.load_project_button: QPushButton
        self.recent_projects_label: QLabel
        self.recent_projects_list: QListWidget
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

        self.recent_projects_label = QLabel("Recent Projects", self.initial_widget)
        self.recent_projects_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        recent_font = self.recent_projects_label.font()
        recent_font.setBold(True)
        self.recent_projects_label.setFont(recent_font)

        self.recent_projects_list = QListWidget(self.initial_widget)
        self.recent_projects_list.setObjectName("RecentProjectsList")
        self.recent_projects_list.setMinimumHeight(120)
        self.recent_projects_list.setVisible(False)
        self.recent_projects_label.setVisible(False)
        self.recent_projects_list.itemActivated.connect(self._open_recent_project_item)

        initial_layout.addWidget(title_label)
        initial_layout.addSpacerItem(
            QSpacerItem(20, 20, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
        )
        initial_layout.addWidget(self.new_project_button)
        initial_layout.addWidget(self.load_project_button)
        initial_layout.addSpacing(10)
        initial_layout.addWidget(self.recent_projects_label)
        initial_layout.addWidget(self.recent_projects_list)
        initial_layout.addSpacerItem(
            QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
        )

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
        self.model.setFilter(
            QtCore.QDir.Filter.AllDirs
            | QtCore.QDir.Filter.Files
            | QtCore.QDir.Filter.NoDotAndDotDot
        )
        self.tree_view.setModel(self.model)

        for i in range(1, self.model.columnCount()):
            self.tree_view.hideColumn(i)

        self.delegate = SidebarItemDelegate(self.app_palette, self)
        self.tree_view.setItemDelegate(self.delegate)
        self.main_layout.addWidget(self.tree_view)
        self.tree_view.viewport().installEventFilter(self)
        self.tree_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree_view.customContextMenuRequested.connect(self._show_context_menu)
        self.tree_view.selectionModel().selectionChanged.connect(self._on_selection_changed)

    def eventFilter(self, watched, event):
        if (
            watched is self.tree_view.viewport()
            and event.type() == QtCore.QEvent.Type.MouseButtonPress
            and isinstance(event, QtGui.QMouseEvent)
            and event.button() == Qt.MouseButton.RightButton
        ):
            return True
        return super().eventFilter(watched, event)

    def show_initial_view(self):
        self.tree_view.setVisible(False)
        self.initial_widget.setVisible(True)
        self.current_project_path = None
        self.model.setRootPath("")
        self.tree_view.setRootIndex(QModelIndex())

    def update_recent_projects(self, recent_projects: list[RecentProject]):
        self.recent_projects_list.clear()
        for project in recent_projects:
            item = QListWidgetItem(recent_project_label(project))
            item.setToolTip(project["path"])
            item.setData(Qt.ItemDataRole.UserRole, project["path"])
            self.recent_projects_list.addItem(item)

        has_recents = bool(recent_projects)
        self.recent_projects_label.setVisible(has_recents)
        self.recent_projects_list.setVisible(has_recents)

    def _open_recent_project_item(self, item: QListWidgetItem):
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            self.recent_project_requested.emit(str(path))

    def set_project(self, project_path: str | None):
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
        self.setStyleSheet(
            f"QWidget {{ background-color: {self.app_palette['widget_bg']}; border: none; color: {self.app_palette['text_color']}; }}"
        )
        button_style = f"""
            QPushButton {{
                background-color: {self.app_palette['button_bg']};
                color: {self.app_palette['button_text']};
                border: 1px solid {self.app_palette['placeholder_border']};
                padding: 5px 15px;
                min-height: 25px;
                border-radius: 3px;
            }}
            QPushButton:hover {{
                background-color: {QtGui.QColor(self.app_palette['button_bg']).lighter(115).name()};
            }}
            QPushButton:pressed {{
                background-color: {QtGui.QColor(self.app_palette['button_bg']).darker(110).name()};
            }}
        """
        if self.new_project_button:
            self.new_project_button.setStyleSheet(button_style)
        if self.load_project_button:
            self.load_project_button.setStyleSheet(button_style)
        if self.recent_projects_list:
            self.recent_projects_list.setStyleSheet(f"""
                QListWidget#RecentProjectsList {{
                    background-color: {self.app_palette['tree_bg']};
                    color: {self.app_palette['text_color']};
                    border: 1px solid {self.app_palette['placeholder_border']};
                    outline: 0;
                }}
                QListWidget#RecentProjectsList::item {{
                    padding: 5px 6px;
                }}
                QListWidget#RecentProjectsList::item:selected {{
                    background-color: {self.app_palette['tree_item_selected_bg']};
                    color: {self.app_palette['tree_item_selected_text']};
                }}
                QListWidget#RecentProjectsList::item:hover {{
                    background-color: {QtGui.QColor(self.app_palette.get('tree_item_selected_bg', '#A0C8F0')).lighter(115).name()};
                }}
            """)

        if self.tree_view:
            self.tree_view.setStyleSheet(f"""
                QTreeView {{
                    background-color: {self.app_palette['tree_bg']};
                    color: {self.app_palette['text_color']};
                    border: none;
                    outline: 0;
                }}
                QTreeView::item {{
                    padding: 3px 0px;
                    color: {self.app_palette['text_color']};
                    background-color: transparent;
                }}
                QTreeView::item:selected {{
                    background-color: {self.app_palette['tree_item_selected_bg']};
                    color: {self.app_palette['tree_item_selected_text']};
                }}
                QTreeView::item:hover {{
                    background-color: {QtGui.QColor(self.app_palette.get('tree_item_selected_bg', '#A0C8F0')).lighter(115).name()};
                }}
                QTreeView::branch {{
                    background: transparent;
                }}
            """)
            if self.delegate:
                self.tree_view.viewport().update()

    def _show_context_menu(self, pos: QtCore.QPoint):
        if not self.tree_view or not self.tree_view.isVisible():
            return
        index = self.tree_view.indexAt(pos)
        if not index.isValid():
            return
        file_path = self.model.filePath(index)
        is_dir = self.model.isDir(index)
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background-color: {self.app_palette['menu_bg']};
                color: {self.app_palette['menu_text']};
                border: 1px solid {self.app_palette['placeholder_border']};
            }}
            QMenu::item:selected {{
                background-color: {self.app_palette['tree_item_selected_bg']};
                color: {self.app_palette['tree_item_selected_text']};
            }}
        """)
        open_action = menu.addAction("Open")
        reveal_action = menu.addAction(self._reveal_action_text())
        menu.addSeparator()
        rename_action = menu.addAction("Rename")
        delete_action = menu.addAction("Delete")
        menu.addSeparator()
        if is_dir:
            new_file_action = menu.addAction("New File")
            new_folder_action = menu.addAction("New Folder")
        else:
            new_file_action = None
            new_folder_action = None
        open_action.triggered.connect(lambda: self.open_path(file_path))
        reveal_action.triggered.connect(lambda: self.reveal_path(file_path))
        rename_action.triggered.connect(lambda: self.rename_path(file_path))
        delete_action.triggered.connect(lambda: self.delete_path(file_path))
        if new_file_action is not None:
            new_file_action.triggered.connect(lambda: self.create_file(file_path))
        if new_folder_action is not None:
            new_folder_action.triggered.connect(lambda: self.create_folder(file_path))
        global_pos = self.tree_view.viewport().mapToGlobal(pos)
        menu.exec(global_pos)

    def _reveal_action_text(self) -> str:
        if sys.platform == "darwin":
            return "Show in Finder"
        if sys.platform.startswith("win"):
            return "Show in File Explorer"
        return "Show in File Manager"

    def _path_is_inside_project(self, path: str) -> bool:
        if not self.current_project_path:
            return False
        try:
            project_path = os.path.abspath(self.current_project_path)
            candidate_path = os.path.abspath(path)
            return os.path.commonpath([project_path, candidate_path]) == project_path
        except (OSError, ValueError):
            return False

    def _show_file_action_error(self, title: str, message: str):
        QtWidgets.QMessageBox.warning(self, title, message)

    def open_path(self, file_path: str):
        if not self._path_is_inside_project(file_path):
            self.item_selected.emit("")
            return

        if os.path.isdir(file_path):
            index = self.model.index(file_path)
            if index.isValid():
                self.tree_view.setExpanded(index, not self.tree_view.isExpanded(index))
            return

        if os.path.isfile(file_path):
            self.item_selected.emit(file_path)
        else:
            self.item_selected.emit("")

    def reveal_path(self, file_path: str):
        if not self._path_is_inside_project(file_path) or not os.path.exists(file_path):
            self._show_file_action_error(
                "Show in File Manager",
                f"Cannot find this item:\n{file_path}",
            )
            return

        native_path = os.path.normpath(file_path)
        if sys.platform.startswith("win"):
            args = [f"/select,{native_path}"] if os.path.isfile(file_path) else [native_path]
            if QtCore.QProcess.startDetached("explorer.exe", args):
                return
        elif sys.platform == "darwin":
            if QtCore.QProcess.startDetached("open", ["-R", native_path]):
                return
        else:
            target_dir = file_path if os.path.isdir(file_path) else os.path.dirname(file_path)
            if QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(target_dir)):
                return

        self._show_file_action_error(
            "Show in File Manager",
            f"Could not open a file manager for:\n{file_path}",
        )

    def rename_path(self, file_path: str):
        if not self._path_is_inside_project(file_path) or not os.path.exists(file_path):
            self._show_file_action_error("Rename", f"Cannot find this item:\n{file_path}")
            return

        old_name = os.path.basename(file_path)
        new_name, accepted = QtWidgets.QInputDialog.getText(
            self,
            "Rename",
            "New name:",
            QtWidgets.QLineEdit.EchoMode.Normal,
            old_name,
        )
        if not accepted:
            return

        new_name = self._normalize_new_name_for_path(file_path, new_name.strip())
        if not new_name or new_name == old_name:
            return
        if os.path.basename(new_name) != new_name or any(sep in new_name for sep in ("/", "\\")):
            self._show_file_action_error("Rename", "Enter a file or folder name, not a path.")
            return

        target_path = os.path.join(os.path.dirname(file_path), new_name)
        if os.path.exists(target_path):
            self._show_file_action_error(
                "Rename",
                f"An item named '{new_name}' already exists.",
            )
            return

        try:
            os.rename(file_path, target_path)
        except OSError as e:
            self._show_file_action_error("Rename", f"Could not rename this item:\n{e}")
            return

        self.file_renamed.emit(file_path, target_path)
        QtCore.QTimer.singleShot(0, lambda: self._select_path_if_visible(target_path))

    def delete_path(self, file_path: str):
        if not self._path_is_inside_project(file_path) or not os.path.exists(file_path):
            self._show_file_action_error("Delete", f"Cannot find this item:\n{file_path}")
            return
        if self.current_project_path and os.path.abspath(file_path) == os.path.abspath(
            self.current_project_path
        ):
            self._show_file_action_error("Delete", "The project root cannot be deleted here.")
            return

        name = os.path.basename(file_path)
        if file_path.lower().endswith(".sprite") and os.path.isfile(file_path):
            reply = QtWidgets.QMessageBox.question(
                self,
                "Remove Sprite",
                (
                    f"Remove this sprite from the project?\n\n{name}\n\n"
                    "The .sprite file and image files will remain on disk."
                ),
                QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
                QtWidgets.QMessageBox.StandardButton.No,
            )
            if reply == QtWidgets.QMessageBox.StandardButton.Yes:
                self.file_deleted.emit(file_path)
            return

        item_type = "folder" if os.path.isdir(file_path) else "file"
        reply = QtWidgets.QMessageBox.question(
            self,
            "Delete",
            f"Delete this {item_type}?\n\n{name}",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No,
        )
        if reply != QtWidgets.QMessageBox.StandardButton.Yes:
            return

        try:
            if os.path.isdir(file_path):
                shutil.rmtree(file_path)
            else:
                os.remove(file_path)
        except OSError as e:
            self._show_file_action_error("Delete", f"Could not delete this item:\n{e}")
            return

        self.file_deleted.emit(file_path)

    @staticmethod
    def _normalize_new_name_for_path(original_path: str, new_name: str) -> str:
        if not original_path.lower().endswith(".sprite") or not os.path.isfile(original_path):
            return new_name
        if new_name.lower().endswith(".sprite"):
            new_name = new_name[:-7]
        else:
            new_name = os.path.splitext(new_name)[0]
        return f"{new_name}.sprite" if new_name else ""

    def create_file(self, directory_path: str):
        self._create_child_path(directory_path, is_directory=False)

    def create_folder(self, directory_path: str):
        self._create_child_path(directory_path, is_directory=True)

    def _create_child_path(self, directory_path: str, is_directory: bool):
        if not self._path_is_inside_project(directory_path) or not os.path.isdir(directory_path):
            self._show_file_action_error(
                "New Folder" if is_directory else "New File",
                f"Cannot create an item inside:\n{directory_path}",
            )
            return

        title = "New Folder" if is_directory else "New File"
        label = "Folder name:" if is_directory else "File name:"
        name, accepted = QtWidgets.QInputDialog.getText(
            self,
            title,
            label,
            QtWidgets.QLineEdit.EchoMode.Normal,
            "",
        )
        if not accepted:
            return

        name = name.strip()
        if not name:
            return
        if os.path.basename(name) != name or any(sep in name for sep in ("/", "\\")):
            self._show_file_action_error(title, "Enter a file or folder name, not a path.")
            return

        new_path = os.path.join(directory_path, name)
        if os.path.exists(new_path):
            self._show_file_action_error(title, f"An item named '{name}' already exists.")
            return

        try:
            if is_directory:
                os.mkdir(new_path)
            else:
                with open(new_path, "x", encoding="utf-8"):
                    pass
        except OSError as e:
            self._show_file_action_error(title, f"Could not create this item:\n{e}")
            return

        QtCore.QTimer.singleShot(0, lambda: self._select_path_if_visible(new_path))
        if not is_directory:
            self.item_selected.emit(new_path)

    def _select_path_if_visible(self, file_path: str):
        index = self.model.index(file_path)
        if index.isValid():
            self.tree_view.setCurrentIndex(index)
            self.tree_view.scrollTo(index)

    def _on_selection_changed(
        self, selected: QtCore.QItemSelection, deselected: QtCore.QItemSelection
    ):
        if not self.tree_view or not self.tree_view.isVisible():
            return
        indexes = selected.indexes()
        if indexes:
            index = indexes[0]
            if index.isValid() and self.model and self.current_project_path:
                file_path = self.model.filePath(index)
                if self._path_is_inside_project(file_path) and os.path.isfile(file_path):
                    self.item_selected.emit(file_path)
                elif not self._path_is_inside_project(file_path):
                    self.item_selected.emit("")
            else:
                self.item_selected.emit("")
        else:
            self.item_selected.emit("")
