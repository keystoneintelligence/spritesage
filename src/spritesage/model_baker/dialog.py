from __future__ import annotations

from pathlib import Path

from PySide6 import QtWidgets
from PySide6.QtCore import Qt

from spritesage.config import build_application_stylesheet
from spritesage.utils import style_popup_dialog

from .service import ModelBakeConfig, available_view_sets, inspect_model_animations


class ModelBakeDialog(QtWidgets.QDialog):
    """Collect settings for importing a 3D model into a Sprite Sage project."""

    def __init__(self, project_dir: str | Path, palette: dict, parent=None):
        super().__init__(parent)
        self.project_dir = Path(project_dir)
        self.app_palette = palette
        style_popup_dialog(self, self.app_palette)
        self.setWindowTitle("Import 3D Model")
        self.setModal(True)
        self.resize(560, 520)

        self.model_path_edit = QtWidgets.QLineEdit()
        self.model_path_edit.setPlaceholderText("GLB model path")
        self.model_path_edit.editingFinished.connect(self._model_path_changed)

        self.browse_button = QtWidgets.QPushButton("Browse...")
        self.browse_button.clicked.connect(self._browse_model)

        self.sprite_name_edit = QtWidgets.QLineEdit()
        self.sprite_name_edit.setPlaceholderText("Sprite name")

        self.view_set_combo = QtWidgets.QComboBox()
        self.view_set_combo.addItems(available_view_sets())
        self.view_set_combo.setCurrentText("iso8")

        self.fps_spin = QtWidgets.QDoubleSpinBox()
        self.fps_spin.setRange(0.1, 60.0)
        self.fps_spin.setDecimals(2)
        self.fps_spin.setValue(8.0)

        self.size_spin = QtWidgets.QSpinBox()
        self.size_spin.setRange(16, 2048)
        self.size_spin.setSingleStep(16)
        self.size_spin.setValue(256)

        self.zoom_spin = QtWidgets.QDoubleSpinBox()
        self.zoom_spin.setRange(0.1, 10.0)
        self.zoom_spin.setDecimals(2)
        self.zoom_spin.setSingleStep(0.1)
        self.zoom_spin.setValue(1.0)

        self.style_combo = QtWidgets.QComboBox()
        self.style_combo.addItems(["none", "pixel"])
        self.style_combo.currentTextChanged.connect(self._update_pixel_controls)

        self.pixel_size_spin = QtWidgets.QSpinBox()
        self.pixel_size_spin.setRange(1, 64)
        self.pixel_size_spin.setValue(4)

        self.max_frames_check = QtWidgets.QCheckBox("Limit frames per animation")
        self.max_frames_check.toggled.connect(self._update_max_frame_controls)
        self.max_frames_spin = QtWidgets.QSpinBox()
        self.max_frames_spin.setRange(1, 4096)
        self.max_frames_spin.setValue(24)

        self.copy_source_check = QtWidgets.QCheckBox("Copy source model into project")
        self.copy_source_check.setChecked(True)

        self.overwrite_check = QtWidgets.QCheckBox("Overwrite existing sprite output")

        self.inspect_button = QtWidgets.QPushButton("Inspect Animations")
        self.inspect_button.clicked.connect(self._inspect_animations)
        self.animation_list = QtWidgets.QListWidget()
        self.animation_list.setMinimumHeight(110)

        self.button_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        self.button_box.button(QtWidgets.QDialogButtonBox.StandardButton.Ok).setText("Bake")
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)

        self._build_layout()
        self._apply_styles()
        self._update_pixel_controls(self.style_combo.currentText())
        self._update_max_frame_controls(self.max_frames_check.isChecked())

    def selected_animations(self) -> list[str] | None:
        if self.animation_list.count() == 0:
            return None

        selected: list[str] = []
        all_names: list[str] = []
        for row in range(self.animation_list.count()):
            item = self.animation_list.item(row)
            if not item.flags() & Qt.ItemFlag.ItemIsEnabled:
                continue
            name = item.data(Qt.ItemDataRole.UserRole) or item.text()
            all_names.append(str(name))
            if item.checkState() == Qt.CheckState.Checked:
                selected.append(str(name))

        if selected == all_names:
            return None
        return selected

    def to_config(self) -> ModelBakeConfig:
        max_frames = self.max_frames_spin.value() if self.max_frames_check.isChecked() else None
        return ModelBakeConfig(
            model_path=Path(self.model_path_edit.text().strip()),
            project_dir=self.project_dir,
            sprite_name=self.sprite_name_edit.text().strip(),
            view_set=self.view_set_combo.currentText(),
            fps=float(self.fps_spin.value()),
            frame_size=int(self.size_spin.value()),
            zoom=float(self.zoom_spin.value()),
            style=self.style_combo.currentText(),
            pixel_size=int(self.pixel_size_spin.value()),
            selected_animations=self.selected_animations(),
            max_frames=max_frames,
            copy_source_model=self.copy_source_check.isChecked(),
            overwrite=self.overwrite_check.isChecked(),
        )

    def accept(self):
        model_path = Path(self.model_path_edit.text().strip())
        if not model_path.is_file():
            self._show_validation_error("Select an existing GLB model file.")
            return
        if model_path.suffix.lower() != ".glb":
            self._show_validation_error("Stage 2 currently accepts GLB model files.")
            return
        if not self.sprite_name_edit.text().strip():
            self._show_validation_error("Enter a sprite name.")
            return
        if self._has_selectable_animations() and self._selected_animation_count() == 0:
            self._show_validation_error("Select at least one animation.")
            return
        super().accept()

    def _build_layout(self) -> None:
        root = QtWidgets.QVBoxLayout(self)

        form = QtWidgets.QFormLayout()
        model_row = QtWidgets.QWidget()
        model_layout = QtWidgets.QHBoxLayout(model_row)
        model_layout.setContentsMargins(0, 0, 0, 0)
        model_layout.addWidget(self.model_path_edit, 1)
        model_layout.addWidget(self.browse_button)
        form.addRow("Model:", model_row)
        form.addRow("Sprite Name:", self.sprite_name_edit)
        form.addRow("Camera Views:", self.view_set_combo)
        form.addRow("FPS:", self.fps_spin)
        form.addRow("Frame Size:", self.size_spin)
        form.addRow("Zoom:", self.zoom_spin)
        form.addRow("Style:", self.style_combo)
        form.addRow("Pixel Size:", self.pixel_size_spin)

        max_frame_row = QtWidgets.QWidget()
        max_frame_layout = QtWidgets.QHBoxLayout(max_frame_row)
        max_frame_layout.setContentsMargins(0, 0, 0, 0)
        max_frame_layout.addWidget(self.max_frames_check)
        max_frame_layout.addWidget(self.max_frames_spin)
        max_frame_layout.addStretch(1)
        form.addRow("Frame Limit:", max_frame_row)

        form.addRow("", self.copy_source_check)
        form.addRow("", self.overwrite_check)
        root.addLayout(form)

        animations_header = QtWidgets.QWidget()
        animations_layout = QtWidgets.QHBoxLayout(animations_header)
        animations_layout.setContentsMargins(0, 0, 0, 0)
        animations_label = QtWidgets.QLabel("Animations:")
        animations_layout.addWidget(animations_label)
        animations_layout.addStretch(1)
        animations_layout.addWidget(self.inspect_button)
        root.addWidget(animations_header)
        root.addWidget(self.animation_list)
        root.addWidget(self.button_box)

    def _apply_styles(self) -> None:
        palette = self.app_palette
        style_popup_dialog(self, palette)

    def _browse_model(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select GLB Model",
            str(self.project_dir),
            "GLB Models (*.glb)",
        )
        if path:
            self.model_path_edit.setText(path)
            self._model_path_changed()
            self._inspect_animations()

    def _model_path_changed(self) -> None:
        model_path = Path(self.model_path_edit.text().strip())
        if model_path.suffix.lower() == ".glb" and not self.sprite_name_edit.text().strip():
            self.sprite_name_edit.setText(model_path.stem)

    def _inspect_animations(self) -> None:
        model_path = Path(self.model_path_edit.text().strip())
        if not model_path.is_file():
            self._show_validation_error("Select an existing GLB model file before inspection.")
            return

        try:
            clips = inspect_model_animations(model_path)
        except Exception as exc:
            self._show_validation_error(f"Could not inspect model animations:\n{exc}")
            return

        self.animation_list.clear()
        for clip in clips:
            item = QtWidgets.QListWidgetItem(f"{clip.name} ({clip.duration:.2f}s)")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            item.setData(Qt.ItemDataRole.UserRole, clip.name)
            self.animation_list.addItem(item)

        if not clips:
            item = QtWidgets.QListWidgetItem("No embedded animations found; rest pose will bake")
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self.animation_list.addItem(item)

    def _update_pixel_controls(self, style: str) -> None:
        self.pixel_size_spin.setEnabled(style == "pixel")

    def _update_max_frame_controls(self, enabled: bool) -> None:
        self.max_frames_spin.setEnabled(enabled)

    def _has_selectable_animations(self) -> bool:
        for row in range(self.animation_list.count()):
            item = self.animation_list.item(row)
            if item.flags() & Qt.ItemFlag.ItemIsEnabled:
                return True
        return False

    def _selected_animation_count(self) -> int:
        selected = 0
        for row in range(self.animation_list.count()):
            item = self.animation_list.item(row)
            if (
                item.flags() & Qt.ItemFlag.ItemIsEnabled
                and item.checkState() == Qt.CheckState.Checked
            ):
                selected += 1
        return selected

    def _show_validation_error(self, message: str) -> None:
        box = QtWidgets.QMessageBox(self)
        box.setIcon(QtWidgets.QMessageBox.Icon.Warning)
        box.setWindowTitle("Import 3D Model")
        box.setText(message)
        box.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Ok)
        box.setStyleSheet(build_application_stylesheet(self.app_palette))
        box.exec()
