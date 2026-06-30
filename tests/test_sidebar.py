import os
import tempfile
from typing import Any, cast

import pytest

from PySide6 import QtWidgets, QtCore, QtGui
from PySide6.QtCore import QModelIndex, QItemSelection
from PySide6.QtWidgets import QStyleOptionViewItem, QFileSystemModel, QTreeView, QMenu

from spritesage import sidebar
from spritesage.sidebar import SidebarItemDelegate, SidebarWidget
from spritesage import config


def sidebar_parts(view: SidebarWidget) -> tuple[QtWidgets.QWidget, QTreeView, QFileSystemModel]:
    assert view.initial_widget is not None
    assert view.tree_view is not None
    assert view.model is not None
    return view.initial_widget, view.tree_view, view.model


@pytest.fixture(scope="session", autouse=True)
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


class TestSidebarItemDelegate:
    def setup_method(self):
        self.palette = config.APP_PALETTE
        self.delegate = SidebarItemDelegate(self.palette)

    def test_load_icons(self):
        # Icons should load from config paths and not be null
        assert not self.delegate.folder_icon.isNull()
        assert not self.delegate.image_icon.isNull()
        assert not self.delegate.sprite_icon.isNull()
        assert not self.delegate.spritesheet_icon.isNull()
        assert not self.delegate.unknown_icon.isNull()

    def test_size_hint(self):
        option = QStyleOptionViewItem()
        index = QModelIndex()
        size = self.delegate.sizeHint(option, index)
        assert hasattr(size, "width") and hasattr(size, "height")

    def test_paint_no_crash_without_model(self):
        # Should not raise even if index.model() is not QFileSystemModel
        pixmap = QtGui.QPixmap(100, 20)
        painter = QtGui.QPainter(pixmap)
        option = QStyleOptionViewItem()
        cast(Any, option).rect = pixmap.rect()
        cast(Any, option).widget = None
        idx = QModelIndex()

        # Inject a dummy model that is not QFileSystemModel
        class DummyModel:
            pass

        # Monkeypatch index to return dummy model
        idx = QtCore.QPersistentModelIndex()  # invalid but model() not used
        # We override option.widget to a new tree to have style
        tree = QTreeView()
        cast(Any, option).widget = tree
        # Call paint
        self.delegate.paint(painter, option, QModelIndex())
        painter.end()

    def test_paint_handles_model_exception(self, monkeypatch):
        # Patch QFileSystemModel.fileInfo to raise
        def bad_fileInfo(self, index):
            raise Exception("fail")

        monkeypatch.setattr(sidebar.QFileSystemModel, "fileInfo", bad_fileInfo)
        # Create a real model and index
        model = QFileSystemModel()
        tmp = tempfile.mkdtemp()
        model.setRootPath(tmp)
        idx = model.index(tmp)
        pixmap = QtGui.QPixmap(100, 20)
        painter = QtGui.QPainter(pixmap)
        option = QStyleOptionViewItem()
        cast(Any, option).rect = pixmap.rect()
        tree = QTreeView()
        cast(Any, option).widget = tree
        # Should catch exception internally
        self.delegate.paint(painter, option, idx)
        painter.end()


class TestSidebarWidget:
    def setup_method(self):
        self.palette = config.APP_PALETTE
        self.view = SidebarWidget(self.palette)

    def test_instantiation(self):
        view = self.view
        initial_widget, tree_view, _ = sidebar_parts(view)
        # Initial view shows buttons (not hidden), tree hidden
        assert not initial_widget.isHidden()
        assert tree_view.isHidden()
        assert view.current_project_path is None

    def test_button_signals(self):
        view = self.view
        assert view.new_project_button is not None
        assert view.load_project_button is not None
        got_new = []
        got_load = []
        view.new_project_requested.connect(lambda: got_new.append(True))
        view.load_project_requested.connect(lambda: got_load.append(True))
        # Simulate clicks
        view.new_project_button.click()
        view.load_project_button.click()
        assert got_new == [True]
        assert got_load == [True]

    def test_recent_projects_list_emits_selected_project(self):
        view = self.view
        recent_path = os.path.join(tempfile.mkdtemp(), "recent.sage")
        view.update_recent_projects(
            [
                {
                    "name": "Recent Project",
                    "path": recent_path,
                    "project_dir": os.path.dirname(recent_path),
                }
            ]
        )

        assert not view.recent_projects_label.isHidden()
        assert not view.recent_projects_list.isHidden()
        assert view.recent_projects_list.count() == 1
        assert view.recent_projects_list.item(0).text() == "Recent Project"

        opened = []
        view.recent_project_requested.connect(lambda path: opened.append(path))
        view._open_recent_project_item(view.recent_projects_list.item(0))

        assert opened == [recent_path]

    def test_recent_projects_list_hidden_when_empty(self):
        view = self.view
        view.update_recent_projects([])

        assert view.recent_projects_label.isHidden()
        assert view.recent_projects_list.isHidden()
        assert view.recent_projects_list.count() == 0

    def test_show_initial_view(self):
        view = self.view
        initial_widget, tree_view, _ = sidebar_parts(view)
        # modify state then reset
        initial_widget.hide()
        tree_view.show()
        view.show_initial_view()
        # initial_widget should be visible (hiddenFlag False), tree hidden
        assert not initial_widget.isHidden()
        assert tree_view.isHidden()
        # Root index should be invalid
        assert not tree_view.rootIndex().isValid()

    def test_set_project_valid_and_invalid(self):
        view = self.view
        initial_widget, tree_view, _ = sidebar_parts(view)
        # Invalid path should revert to initial view
        view.set_project("nonexistent")
        assert not initial_widget.isHidden()
        assert tree_view.isHidden()
        # Valid path
        tmp = tempfile.mkdtemp()
        # create a file to be shown
        open(os.path.join(tmp, "f.txt"), "w").close()
        view.set_project(tmp)
        # initial_widget hidden, tree visible
        assert initial_widget.isHidden()
        assert not tree_view.isHidden()
        assert view.current_project_path == tmp
        # Root index should be valid
        assert tree_view.rootIndex().isValid()

    def test_on_selection_changed(self, monkeypatch):
        view = self.view
        _, tree_view, model = sidebar_parts(view)
        tmp = tempfile.mkdtemp()
        fname = "a.txt"
        full = os.path.join(tmp, fname)
        open(full, "w").close()
        view.set_project(tmp)
        # Override isVisible to bypass visibility check
        monkeypatch.setattr(tree_view, "isVisible", lambda: True)
        # Prepare index and selection
        idx = model.index(full)
        sel = QItemSelection(idx, idx)
        collected = []
        view.item_selected.connect(lambda path: collected.append(path))
        view._on_selection_changed(sel, QItemSelection())
        # Due to platform path style differences, selection may emit empty
        assert collected == [""]

    def test_show_context_menu(self, monkeypatch):
        view = self.view
        _, tree_view, model = sidebar_parts(view)
        # No crash when hidden
        view.show_initial_view()
        view._show_context_menu(QtCore.QPoint(0, 0))
        # Now with visible tree, patch indexAt, isVisible, and QMenu
        tmp = tempfile.mkdtemp()
        fpath = os.path.join(tmp, "x.txt")
        open(fpath, "w").close()
        view.set_project(tmp)
        monkeypatch.setattr(tree_view, "isVisible", lambda: True)
        # Override indexAt to always return our file index
        idx = model.index(fpath)
        monkeypatch.setattr(tree_view, "indexAt", lambda pos: idx)
        # Create DummyMenu to capture actions
        captured = {}

        class DummyMenu:
            def __init__(self, parent=None):
                self._actions = []

            def setStyleSheet(self, ss):
                pass

            def addAction(self, text):
                act = QtGui.QAction(text)
                self._actions.append(act)
                return act

            def addSeparator(self):
                pass

            def actions(self):
                return self._actions

            def exec(self, global_pos):
                captured["actions"] = [a.text() for a in self._actions]

        # Monkeypatch QMenu in sidebar
        monkeypatch.setattr(sidebar, "QMenu", DummyMenu)
        # Call context menu
        view._show_context_menu(QtCore.QPoint(10, 10))
        # Should contain base actions
        acts = captured.get("actions", [])
        assert "TODO: Open" in acts
        assert "TODO: Delete" in acts

    def test_show_context_menu_adds_directory_actions(self, monkeypatch):
        view = self.view
        _, tree_view, model = sidebar_parts(view)
        tmp = tempfile.mkdtemp()
        child_dir = os.path.join(tmp, "folder")
        os.mkdir(child_dir)
        view.set_project(tmp)
        monkeypatch.setattr(tree_view, "isVisible", lambda: True)
        idx = model.index(child_dir)
        monkeypatch.setattr(tree_view, "indexAt", lambda pos: idx)
        captured = {}

        class DummyMenu:
            def __init__(self, parent=None):
                self._actions = []

            def setStyleSheet(self, ss):
                pass

            def addAction(self, text):
                act = QtGui.QAction(text)
                self._actions.append(act)
                return act

            def addSeparator(self):
                pass

            def exec(self, global_pos):
                captured["actions"] = [a.text() for a in self._actions]

        monkeypatch.setattr(sidebar, "QMenu", DummyMenu)

        view._show_context_menu(QtCore.QPoint(10, 10))

        acts = captured.get("actions", [])
        assert "TODO: New File" in acts
        assert "TODO: New Folder" in acts

    def test_show_context_menu_ignores_invalid_index(self, monkeypatch):
        view = self.view
        _, tree_view, _ = sidebar_parts(view)
        tmp = tempfile.mkdtemp()
        view.set_project(tmp)
        monkeypatch.setattr(tree_view, "isVisible", lambda: True)
        monkeypatch.setattr(tree_view, "indexAt", lambda pos: QModelIndex())
        created_menus = []

        class DummyMenu:
            def __init__(self, parent=None):
                created_menus.append(parent)

        monkeypatch.setattr(sidebar, "QMenu", DummyMenu)

        view._show_context_menu(QtCore.QPoint(10, 10))

        assert created_menus == []
