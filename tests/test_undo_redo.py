from dataclasses import dataclass

from spritesage.undo_redo import UndoRedoManager


@dataclass
class Document:
    value: str


def test_record_undo_redo_and_undo_after_redo():
    manager = UndoRedoManager[Document]()
    first = Document("first")
    second = Document("second")

    manager.reset(first)
    assert manager.record_change(first, second, label="Rename")

    assert manager.state().can_undo
    assert manager.undo_text == "Rename"
    assert manager.undo(current_state=second) == first
    assert manager.state().can_redo
    assert manager.redo_text == "Rename"
    assert manager.redo() == second

    assert manager.undo(current_state=second) == first


def test_record_change_clears_redo_stack():
    manager = UndoRedoManager[Document]()
    first = Document("first")
    second = Document("second")
    third = Document("third")

    manager.reset(first)
    manager.record_change(first, second, label="Second")
    assert manager.undo(current_state=second) == first
    assert manager.can_redo

    manager.record_change(first, third, label="Third")

    assert manager.can_undo
    assert not manager.can_redo
    assert manager.redo() is None
    assert manager.undo(current_state=third) == first


def test_merge_key_coalesces_continuous_edits():
    manager = UndoRedoManager[Document](merge_window_seconds=60)
    first = Document("a")
    second = Document("ab")
    third = Document("abc")

    manager.reset(first)
    manager.record_change(first, second, label="Edit name", merge_key="name")
    manager.record_change(second, third, label="Edit name", merge_key="name")

    state = manager.state()
    assert state.undo_count == 1
    assert manager.undo(current_state=third) == first
    assert manager.redo() == third


def test_max_depth_discards_oldest_command():
    manager = UndoRedoManager[Document](max_depth=2)
    one = Document("one")
    two = Document("two")
    three = Document("three")
    four = Document("four")

    manager.reset(one)
    manager.record_change(one, two, label="Two")
    manager.record_change(two, three, label="Three")
    manager.record_change(three, four, label="Four")

    assert manager.state().undo_count == 2
    assert manager.undo(current_state=four) == three
    assert manager.undo(current_state=three) == two
    assert manager.undo(current_state=two) is None
