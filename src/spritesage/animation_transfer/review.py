"""Review generated animation frames against their rendered motion poses."""

from __future__ import annotations

import json

from PySide6 import QtCore, QtGui, QtWidgets
from modelmanager import Cancelled
from modelmanager.qt import run_task

from spritesage.utils import style_popup_dialog

from .service import (
    frame_attempts,
    retry_transfer_frame,
    safe_name,
    select_frame_attempt,
    verify_transfer,
)


class FrameReviewDialog(QtWidgets.QDialog):
    def __init__(self, result, palette, parent=None):
        super().__init__(parent)
        self.transfer_result = result
        self.app_palette = palette
        self.entries = []
        output = json.loads(result.manifest_path.read_text())
        state = json.loads((result.output_dir / "progress.json").read_text())
        source = json.loads((result.output_dir / "poses" / "manifest.json").read_text())
        for record in source["animations"]:
            for direction, poses in record["views"].items():
                for index, pose in enumerate(poses):
                    name = f"{record['name']} · {direction.replace('_', ' ')} · {index + 1}/{len(poses)}"
                    key = f"{safe_name(record['name'])}_{direction}"
                    frame = result.sprite.animations[key].frames[index]
                    self.entries.append((record["name"], direction, index, name, pose, frame))
        style_popup_dialog(self, palette)
        self.setWindowTitle("Review animation frames")
        self.resize(870, 620)
        outer = QtWidgets.QVBoxLayout(self)
        guidance_note = (
            " This template has no recognized pose joints, so inspect foot placement carefully."
            if output.get("pose_guided") and not output.get("rig_guided")
            else ""
        )
        fallback_count = sum(
            not frame.get("prompt_helper_used", False) for frame in state.get("frames", {}).values()
        )
        if output.get("pose_guided") and fallback_count:
            guidance_note += (
                f" {fallback_count} frame(s) used the direct edit prompt after local prompt guidance "
                "was unavailable or disagreed with the rig."
            )
        note = QtWidgets.QLabel(
            "Experimental pose transfer · Compare each source pose with the generated sprite. "
            "Retry any frame before adding this animation to your project. Closing keeps the draft."
            + guidance_note
        )
        note.setWordWrap(True)
        outer.addWidget(note)

        middle = QtWidgets.QHBoxLayout()
        self.frame_list = QtWidgets.QListWidget()
        self.frame_list.setAccessibleName("Generated frames to review")
        self.frame_list.setMinimumWidth(225)
        for _, _, _, label, _, _ in self.entries:
            self.frame_list.addItem(label)
        self.frame_list.currentRowChanged.connect(self._show_frame)
        middle.addWidget(self.frame_list)
        previews = QtWidgets.QVBoxLayout()
        compare = QtWidgets.QHBoxLayout()
        self.expected_label = self._image_column(compare, "Expected pose")
        self.output_label = self._image_column(compare, "Generated sprite")
        previews.addLayout(compare)
        version_row = QtWidgets.QHBoxLayout()
        version_row.addWidget(QtWidgets.QLabel("Frame version"))
        self.version_combo = QtWidgets.QComboBox()
        self.version_combo.setAccessibleName("Saved versions of this frame")
        self.version_combo.currentIndexChanged.connect(self._select_version)
        version_row.addWidget(self.version_combo, 1)
        previews.addLayout(version_row)
        previews.addWidget(QtWidgets.QLabel("Retry note (optional)"))
        self.feedback_edit = QtWidgets.QLineEdit()
        self.feedback_edit.setPlaceholderText("e.g. Keep the rear boot raised like the source pose")
        self.feedback_edit.setMaxLength(2000)
        previews.addWidget(self.feedback_edit)
        self.retry_button = QtWidgets.QPushButton("Retry this frame")
        self.retry_button.clicked.connect(self._retry)
        previews.addWidget(self.retry_button)
        previews.addStretch()
        middle.addLayout(previews, 1)
        outer.addLayout(middle, 1)

        bottom = QtWidgets.QHBoxLayout()
        self.previous_button = QtWidgets.QPushButton("Previous frame")
        self.previous_button.clicked.connect(
            lambda: self.frame_list.setCurrentRow(self.frame_list.currentRow() - 1)
        )
        self.next_button = QtWidgets.QPushButton("Next frame")
        self.next_button.clicked.connect(
            lambda: self.frame_list.setCurrentRow(self.frame_list.currentRow() + 1)
        )
        bottom.addWidget(self.previous_button)
        bottom.addWidget(self.next_button)
        bottom.addStretch()
        keep_button = QtWidgets.QPushButton("Close · keep draft")
        keep_button.clicked.connect(self.reject)
        accept_button = QtWidgets.QPushButton("Accept animation")
        accept_button.clicked.connect(self._accept)
        bottom.addWidget(keep_button)
        bottom.addWidget(accept_button)
        outer.addLayout(bottom)
        if self.entries:
            self.frame_list.setCurrentRow(0)

    def _image_column(self, layout, title):
        column = QtWidgets.QVBoxLayout()
        heading = QtWidgets.QLabel(title)
        heading.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        column.addWidget(heading)
        image = QtWidgets.QLabel()
        image.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        image.setFixedSize(270, 270)
        image.setStyleSheet(
            f"background: {self.app_palette['dialog_input_bg']}; "
            f"border: 1px solid {self.app_palette['placeholder_border']};"
        )
        column.addWidget(image)
        layout.addLayout(column, 1)
        return image

    def _show_frame(self, row):
        if not 0 <= row < len(self.entries):
            return
        animation, direction, index, _, pose, frame = self.entries[row]
        for label, path in ((self.expected_label, pose), (self.output_label, frame)):
            # Load fresh bytes after a retry; Qt may cache QPixmap(file path).
            image = QtGui.QImage(str(path))
            label.setPixmap(
                QtGui.QPixmap.fromImage(image).scaled(
                    250,
                    250,
                    QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                    QtCore.Qt.TransformationMode.FastTransformation,
                )
            )
        count, selected = frame_attempts(self.transfer_result, animation, direction, index)
        self.version_combo.blockSignals(True)
        self.version_combo.clear()
        self.version_combo.addItem("Original")
        for attempt in range(1, count):
            self.version_combo.addItem(f"Retry {attempt}")
        self.version_combo.setCurrentIndex(selected)
        self.version_combo.blockSignals(False)
        self.previous_button.setEnabled(row > 0)
        self.next_button.setEnabled(row < len(self.entries) - 1)

    def _select_version(self, selected):
        row = self.frame_list.currentRow()
        if row < 0 or selected < 0:
            return
        animation, direction, index, _, _, _ = self.entries[row]
        _, current = frame_attempts(self.transfer_result, animation, direction, index)
        if selected == current:
            return
        try:
            select_frame_attempt(self.transfer_result, animation, direction, index, selected)
            self._show_frame(row)
        except Exception as error:
            self._error("Could not restore frame version", error)
            self._show_frame(row)

    def _retry(self):
        row = self.frame_list.currentRow()
        if row < 0:
            return
        animation, direction, index, _, _, _ = self.entries[row]
        feedback = self.feedback_edit.text().strip()
        try:
            run_task(
                self,
                "Retrying frame",
                lambda progress, cancel: retry_transfer_frame(
                    self.transfer_result, animation, direction, index, feedback, progress, cancel
                ),
                self.app_palette,
            )
        except Cancelled:
            return
        except Exception as error:
            self._error("Frame retry stopped", error)
            return
        self.feedback_edit.clear()
        self._show_frame(row)

    def _accept(self):
        try:
            verify_transfer(self.transfer_result)
        except Exception as error:
            self._error("Could not accept animation", error)
            return
        self.accept()

    def _error(self, title, error):
        box = QtWidgets.QMessageBox(
            QtWidgets.QMessageBox.Icon.Warning, title, str(error), parent=self
        )
        style_popup_dialog(box, self.app_palette)
        box.exec()
