from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6 import QtWidgets

from .config import build_application_stylesheet
from .utils import style_popup_dialog


@dataclass(frozen=True)
class ArtImportDialogRequest:
    mode: str
    options: dict


class ArtImportDialog(QtWidgets.QDialog):
    def __init__(self, project_dir: str | Path, palette: dict, parent=None):
        super().__init__(parent)
        self.project_dir = Path(project_dir)
        self.app_palette = palette
        self.sequence_files: list[Path] = []

        style_popup_dialog(self, self.app_palette)
        self.setWindowTitle("Import Existing Art")
        self.setModal(True)
        self.resize(600, 440)

        self.sprite_name_edit = QtWidgets.QLineEdit()
        self.sprite_name_edit.setPlaceholderText("Sprite name")

        self.tabs = QtWidgets.QTabWidget()
        self._build_sequence_tab()
        self._build_folder_tab()
        self._build_sheet_tab()
        self._build_aseprite_tab()

        self.button_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        self.button_box.button(QtWidgets.QDialogButtonBox.StandardButton.Ok).setText("Import")
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)

        root = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        form.addRow("Sprite Name:", self.sprite_name_edit)
        root.addLayout(form)
        root.addWidget(self.tabs, 1)
        root.addWidget(self.button_box)

    def to_request(self) -> ArtImportDialogRequest:
        mode = self.tabs.tabText(self.tabs.currentIndex()).lower()
        sprite_name = self.sprite_name_edit.text().strip()
        if mode.startswith("sequence"):
            return ArtImportDialogRequest(
                mode="sequence",
                options={
                    "project_dir": self.project_dir,
                    "sprite_name": sprite_name,
                    "animation_name": self.sequence_animation_edit.text().strip(),
                    "image_paths": tuple(self.sequence_files),
                },
            )
        if mode.startswith("folder"):
            return ArtImportDialogRequest(
                mode="folder",
                options={
                    "project_dir": self.project_dir,
                    "sprite_name": sprite_name,
                    "folder_path": Path(self.folder_path_edit.text().strip()),
                    "default_animation_name": self.folder_animation_edit.text().strip(),
                },
            )
        if mode.startswith("sheet"):
            return ArtImportDialogRequest(
                mode="sheet",
                options={
                    "project_dir": self.project_dir,
                    "sprite_name": sprite_name,
                    "sheet_path": Path(self.sheet_path_edit.text().strip()),
                    "frame_width": self.sheet_width_spin.value(),
                    "frame_height": self.sheet_height_spin.value(),
                    "margin": self.sheet_margin_spin.value(),
                    "spacing": self.sheet_spacing_spin.value(),
                    "animation_name": self.sheet_animation_edit.text().strip(),
                    "ignore_empty": self.sheet_ignore_empty_check.isChecked(),
                },
            )
        return ArtImportDialogRequest(
            mode="aseprite",
            options={
                "project_dir": self.project_dir,
                "sprite_name": sprite_name,
                "json_path": Path(self.aseprite_json_edit.text().strip()),
                "sheet_path": (
                    Path(self.aseprite_sheet_edit.text().strip())
                    if self.aseprite_sheet_edit.text().strip()
                    else None
                ),
            },
        )

    def accept(self) -> None:
        sprite_name = self.sprite_name_edit.text().strip()
        if not sprite_name:
            self._show_validation_error("Enter a sprite name.")
            return

        request = self.to_request()
        if request.mode == "sequence":
            if not self.sequence_files:
                self._show_validation_error("Select one or more image files.")
                return
            if not request.options["animation_name"]:
                self._show_validation_error("Enter an animation name.")
                return
        elif request.mode == "folder":
            if not Path(request.options["folder_path"]).is_dir():
                self._show_validation_error("Select an existing folder.")
                return
            if not request.options["default_animation_name"]:
                self._show_validation_error("Enter an animation name.")
                return
        elif request.mode == "sheet":
            if not Path(request.options["sheet_path"]).is_file():
                self._show_validation_error("Select an existing sprite sheet image.")
                return
            if not request.options["animation_name"]:
                self._show_validation_error("Enter an animation name.")
                return
        elif request.mode == "aseprite" and not Path(request.options["json_path"]).is_file():
            self._show_validation_error("Select an existing Aseprite JSON file.")
            return

        super().accept()

    def _build_sequence_tab(self) -> None:
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QFormLayout(tab)

        self.sequence_files_edit = QtWidgets.QLineEdit()
        self.sequence_files_edit.setReadOnly(True)
        browse = QtWidgets.QPushButton("Browse...")
        browse.clicked.connect(self._browse_sequence_files)
        files_row = self._path_row(self.sequence_files_edit, browse)

        self.sequence_animation_edit = QtWidgets.QLineEdit("idle")
        layout.addRow("Images:", files_row)
        layout.addRow("Animation:", self.sequence_animation_edit)
        self.tabs.addTab(tab, "Sequence")

    def _build_folder_tab(self) -> None:
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QFormLayout(tab)

        self.folder_path_edit = QtWidgets.QLineEdit()
        browse = QtWidgets.QPushButton("Browse...")
        browse.clicked.connect(self._browse_folder)
        self.folder_animation_edit = QtWidgets.QLineEdit("idle")

        layout.addRow("Folder:", self._path_row(self.folder_path_edit, browse))
        layout.addRow("Direct Images Animation:", self.folder_animation_edit)
        self.tabs.addTab(tab, "Folder")

    def _build_sheet_tab(self) -> None:
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QFormLayout(tab)

        self.sheet_path_edit = QtWidgets.QLineEdit()
        browse = QtWidgets.QPushButton("Browse...")
        browse.clicked.connect(self._browse_sheet)

        self.sheet_width_spin = self._dimension_spin()
        self.sheet_height_spin = self._dimension_spin()
        self.sheet_margin_spin = self._offset_spin()
        self.sheet_spacing_spin = self._offset_spin()
        self.sheet_animation_edit = QtWidgets.QLineEdit("idle")
        self.sheet_ignore_empty_check = QtWidgets.QCheckBox("Ignore empty transparent frames")
        self.sheet_ignore_empty_check.setChecked(True)

        layout.addRow("Sheet:", self._path_row(self.sheet_path_edit, browse))
        layout.addRow("Frame Width:", self.sheet_width_spin)
        layout.addRow("Frame Height:", self.sheet_height_spin)
        layout.addRow("Margin:", self.sheet_margin_spin)
        layout.addRow("Spacing:", self.sheet_spacing_spin)
        layout.addRow("Animation:", self.sheet_animation_edit)
        layout.addRow("", self.sheet_ignore_empty_check)
        self.tabs.addTab(tab, "Sheet")

    def _build_aseprite_tab(self) -> None:
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QFormLayout(tab)

        self.aseprite_json_edit = QtWidgets.QLineEdit()
        json_browse = QtWidgets.QPushButton("Browse...")
        json_browse.clicked.connect(self._browse_aseprite_json)

        self.aseprite_sheet_edit = QtWidgets.QLineEdit()
        sheet_browse = QtWidgets.QPushButton("Browse...")
        sheet_browse.clicked.connect(self._browse_aseprite_sheet)

        layout.addRow("JSON:", self._path_row(self.aseprite_json_edit, json_browse))
        layout.addRow("Sheet:", self._path_row(self.aseprite_sheet_edit, sheet_browse))
        self.tabs.addTab(tab, "Aseprite")

    def _path_row(self, edit: QtWidgets.QLineEdit, button: QtWidgets.QPushButton):
        row = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(edit, 1)
        layout.addWidget(button)
        return row

    def _dimension_spin(self) -> QtWidgets.QSpinBox:
        spin = QtWidgets.QSpinBox()
        spin.setRange(1, 4096)
        spin.setValue(64)
        return spin

    def _offset_spin(self) -> QtWidgets.QSpinBox:
        spin = QtWidgets.QSpinBox()
        spin.setRange(0, 4096)
        spin.setValue(0)
        return spin

    def _browse_sequence_files(self) -> None:
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self,
            "Select Image Sequence",
            str(self.project_dir),
            "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp)",
        )
        if not paths:
            return
        self.sequence_files = [Path(path) for path in paths]
        self.sequence_files_edit.setText(f"{len(self.sequence_files)} file(s) selected")
        self._set_default_sprite_name(self.sequence_files[0].stem)

    def _browse_folder(self) -> None:
        path = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            "Select Art Folder",
            str(self.project_dir),
        )
        if path:
            self.folder_path_edit.setText(path)
            self._set_default_sprite_name(Path(path).name)

    def _browse_sheet(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select Sprite Sheet",
            str(self.project_dir),
            "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp)",
        )
        if path:
            self.sheet_path_edit.setText(path)
            self._set_default_sprite_name(Path(path).stem)

    def _browse_aseprite_json(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select Aseprite JSON",
            str(self.project_dir),
            "JSON (*.json)",
        )
        if path:
            self.aseprite_json_edit.setText(path)
            self._set_default_sprite_name(Path(path).stem)

    def _browse_aseprite_sheet(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select Aseprite Sheet",
            str(self.project_dir),
            "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp)",
        )
        if path:
            self.aseprite_sheet_edit.setText(path)

    def _set_default_sprite_name(self, value: str) -> None:
        if not self.sprite_name_edit.text().strip():
            self.sprite_name_edit.setText(value)

    def _show_validation_error(self, message: str) -> None:
        box = QtWidgets.QMessageBox(self)
        box.setIcon(QtWidgets.QMessageBox.Icon.Warning)
        box.setWindowTitle("Import Existing Art")
        box.setText(message)
        box.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Ok)
        box.setStyleSheet(build_application_stylesheet(self.app_palette))
        box.exec()
