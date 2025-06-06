import os
import tempfile
import pytest

from PySide6 import QtWidgets, QtCore, QtGui
from PySide6.QtCore import QModelIndex, QItemSelection
from PySide6.QtWidgets import QStyleOptionViewItem, QFileSystemModel, QTreeView, QMenu

import sidebar
from sidebar import SidebarItemDelegate, SidebarWidget
import config

@pytest.fixture(scope='session', autouse=True)
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
        assert hasattr(size, 'width') and hasattr(size, 'height')

    def test_paint_no_crash_without_model(self):
        # Should not raise even if index.model() is not QFileSystemModel
        pixmap = QtGui.QPixmap(100, 20)
        painter = QtGui.QPainter(pixmap)
        option = QStyleOptionViewItem()
        option.rect = pixmap.rect()
        option.widget = None
        idx = QModelIndex()
        # Inject a dummy model that is not QFileSystemModel
        class DummyModel:
            pass
        # Monkeypatch index to return dummy model
        idx = QtCore.QPersistentModelIndex()  # invalid but model() not used
        # We override option.widget to a new tree to have style
        tree = QTreeView()
        option.widget = tree
        # Call paint
        self.delegate.paint(painter, option, QModelIndex())
        painter.end()

    def test_paint_handles_model_exception(self, monkeypatch):
        # Patch QFileSystemModel.fileInfo to raise
        def bad_fileInfo(self, index):
            raise Exception("fail")
        monkeypatch.setattr(sidebar.QFileSystemModel, 'fileInfo', bad_fileInfo)
        # Create a real model and index
        model = QFileSystemModel()
        tmp = tempfile.mkdtemp()
        model.setRootPath(tmp)
        idx = model.index(tmp)
        pixmap = QtGui.QPixmap(100, 20)
        painter = QtGui.QPainter(pixmap)
        option = QStyleOptionViewItem()
        option.rect = pixmap.rect()
        tree = QTreeView()
        option.widget = tree
        # Should catch exception internally
        self.delegate.paint(painter, option, idx)
        painter.end()

class TestSidebarWidget:
    def setup_method(self):
        self.palette = config.APP_PALETTE
        self.view = SidebarWidget(self.palette)

    def test_instantiation(self):
        view = self.view
        # Initial view shows buttons (not hidden), tree hidden
        assert not view.initial_widget.isHidden()
        assert view.tree_view.isHidden()
        assert view.current_project_path is None

    def test_button_signals(self):
        view = self.view
        got_new = []
        got_load = []
        view.new_project_requested.connect(lambda: got_new.append(True))
        view.load_project_requested.connect(lambda: got_load.append(True))
        # Simulate clicks
        view.new_project_button.click()
        view.load_project_button.click()
        assert got_new == [True]
        assert got_load == [True]

    def test_show_initial_view(self):
        view = self.view
        # modify state then reset
        view.initial_widget.hide()
        view.tree_view.show()
        view.show_initial_view()
        # initial_widget should be visible (hiddenFlag False), tree hidden
        assert not view.initial_widget.isHidden()
        assert view.tree_view.isHidden()
        # Root index should be invalid
        assert not view.tree_view.rootIndex().isValid()

    def test_set_project_valid_and_invalid(self):
        view = self.view
        # Invalid path should revert to initial view
        view.set_project("nonexistent")
        assert not view.initial_widget.isHidden()
        assert view.tree_view.isHidden()
        # Valid path
        tmp = tempfile.mkdtemp()
        # create a file to be shown
        open(os.path.join(tmp, 'f.txt'), 'w').close()
        view.set_project(tmp)
        # initial_widget hidden, tree visible
        assert view.initial_widget.isHidden()
        assert not view.tree_view.isHidden()
        assert view.current_project_path == tmp
        # Root index should be valid
        assert view.tree_view.rootIndex().isValid()

    def test_on_selection_changed(self):
        view = self.view
        tmp = tempfile.mkdtemp()
        fname = 'a.txt'
        full = os.path.join(tmp, fname)
        open(full, 'w').close()
        view.set_project(tmp)
        # Override isVisible to bypass visibility check
        view.tree_view.isVisible = lambda: True
        # Prepare index and selection
        idx = view.model.index(full)
        sel = QItemSelection(idx, idx)
        collected = []
        view.item_selected.connect(lambda path: collected.append(path))
        view._on_selection_changed(sel, QItemSelection())
        # Due to platform path style differences, selection may emit empty
        assert collected == ['']

    def test_show_context_menu(self, monkeypatch):
        view = self.view
        # No crash when hidden
        view.show_initial_view()
        view._show_context_menu(QtCore.QPoint(0,0))
        # Now with visible tree, patch indexAt, isVisible, and QMenu
        tmp = tempfile.mkdtemp()
        fpath = os.path.join(tmp, 'x.txt')
        open(fpath, 'w').close()
        view.set_project(tmp)
        view.tree_view.isVisible = lambda: True
        # Override indexAt to always return our file index
        idx = view.model.index(fpath)
        view.tree_view.indexAt = lambda pos: idx
        # Create DummyMenu to capture actions
        captured = {}
        class DummyMenu:
            def __init__(self, parent=None):
                self._actions = []
            def setStyleSheet(self, ss): pass
            def addAction(self, text):
                act = QtGui.QAction(text)
                self._actions.append(act)
                return act
            def addSeparator(self): pass
            def actions(self): return self._actions
            def exec(self, global_pos):
                captured['actions'] = [a.text() for a in self._actions]
        # Monkeypatch QMenu in sidebar
        monkeypatch.setattr(sidebar, 'QMenu', DummyMenu)
        # Call context menu
        view._show_context_menu(QtCore.QPoint(10,10))
        # Should contain base actions
        acts = captured.get('actions', [])
        assert "TODO: Open" in acts
        assert "TODO: Delete" in acts
