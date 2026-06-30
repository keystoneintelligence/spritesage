"""
SPDX-License-Identifier: GPL-3.0-only
Copyright © 2025 Keystone Intelligence LLC
Licensed under GPL v3 (see LICENSE file for details)
"""

import os
import json
import uuid
import shutil
from copy import deepcopy
from typing import Optional
from PySide6 import QtWidgets, QtCore
from PySide6.QtWidgets import (
    QStyle,
    QMessageBox,
    QTableWidgetItem,
    QApplication,
    QTableWidget,
    QAbstractItemView,
)
from PySide6.QtCore import Qt

from .inference import (
    AIModelManager,
    GenerateReferenceImageInput,
    GenerateDescriptionInput,
    GenerateKeywordsInput,
)
from .exporter import GodotProjectExporter, GodotSpriteExporter
from .image_loader import ImageLoaderWidget, ActionIconButton
from .art_import_dialog import ArtImportDialog, ArtImportDialogRequest
from .art_importer import (
    ArtImportResult,
    import_aseprite_json,
    import_folder,
    import_image_sequence,
    import_sprite_sheet,
)
from .model_baker import ModelBakeResult, bake_model_to_sprite_project
from .model_baker.dialog import ModelBakeDialog
from .sprite_file import SpriteFile
from .config import EMPTY_SPRITE_TEMPLATE, build_application_stylesheet
from .utils import (
    TextInputDialog,
    UndoRedoManager,
    call_with_busy,
    call_with_progress,
    ensure_llm_configured,
)
from .sage_file import SageFile


class SageEditorView(QtWidgets.QWidget):
    """A custom widget to display and edit .sage (JSON) files with custom controls."""

    REFERENCE_IMAGES_KEY = "Reference Images"
    HIDDEN_KEYS = {"createdAt", "lastSaved", "version", "Hidden Sprites"}
    LOCKED_KEYS = {"Project Name"}
    ICON_BUTTON_KEYS = {"Project Description", "Keywords"}
    SPRITE_BUTTONS_KEY = "_SpriteButtons"
    SPRITE_TABLE_KEY = "_SpriteTable"
    EXPORTS_DIRNAME = "exports"
    sprite_row_action = QtCore.Signal(str)

    def __init__(self, palette, parent=None):
        super().__init__(parent)
        self.app_palette = palette
        self._widgets = {}
        self._undo_redo_manager = UndoRedoManager[SageFile]()
        self.sage_file: Optional[SageFile] = None

        self.scroll_area = QtWidgets.QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet(
            f"background-color: {self.app_palette['widget_bg']}; border: none;"
        )

        self.content_widget = QtWidgets.QWidget()
        self.content_widget.setStyleSheet(f"background-color: {self.app_palette['widget_bg']};")
        self.form_layout = QtWidgets.QFormLayout(self.content_widget)
        self.form_layout.setContentsMargins(10, 10, 10, 10)
        self.form_layout.setSpacing(10)
        self.form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        self.form_layout.setRowWrapPolicy(QtWidgets.QFormLayout.RowWrapPolicy.WrapLongRows)

        self.scroll_area.setWidget(self.content_widget)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.scroll_area)

    def _require_sage_file(self) -> SageFile:
        if self.sage_file is None:
            raise RuntimeError("No .sage file is loaded.")
        return self.sage_file

    # MODIFIED load_data: Connect to action_clicked signal
    def load_data(self, sage_file: SageFile):
        """Loads data from a dictionary and populates the editor fields."""
        print(
            f"SageEditor: Clearing layout for new data (Sage File: {sage_file.filepath})"
        )  # Debug print

        if self.sage_file and self.sage_file.filepath != sage_file.filepath:
            self._undo_redo_manager.clear()

        self.sage_file = deepcopy(sage_file)
        # Do NOT clear self._widgets here yet. We need it to track old widgets if the layout clear fails.

        # --- Robust Layout Clearing ---
        layout = self.form_layout
        while layout.count() > 0:
            item = layout.takeAt(0)
            if item is None:
                print("Warning: layout.takeAt(0) returned None unexpectedly.")
                continue

            widget = item.widget()
            if widget:
                widget.setParent(None)
                widget.deleteLater()
            else:
                sub_layout = item.layout()
                if sub_layout:
                    print(f"  Removing sub-layout: {sub_layout}")
                    while sub_layout.count() > 0:
                        sub_item = sub_layout.takeAt(0)
                        if sub_item:
                            sub_widget = sub_item.widget()
                            if sub_widget:
                                sub_widget.setParent(None)
                                sub_widget.deleteLater()

        print("SageEditor: Layout cleared, resetting _widgets dictionary.")
        self._widgets = {}

        print("SageEditor: Finished populating layout.")  # Debug print

        # Populate standard fields from data
        for key, value in self.sage_file.to_dict().items():
            if key in self.HIDDEN_KEYS:
                continue

            key_label = QtWidgets.QLabel(f"{key}:")
            self._apply_label_styles(key_label)
            key_label.setWordWrap(True)

            is_locked = key in self.LOCKED_KEYS

            if key == self.REFERENCE_IMAGES_KEY:
                if not isinstance(value, list):
                    print(f"Warning: Value for '{key}' is not a list. Using empty list.")
                    value = []

                image_paths = (value + ["", "", "", ""])[:4]
                row_container = QtWidgets.QWidget()
                row_layout = QtWidgets.QHBoxLayout(row_container)
                row_layout.setSpacing(5)
                row_layout.setContentsMargins(0, 0, 0, 0)
                row_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)

                image_loaders = []
                for i in range(4):
                    loader = ImageLoaderWidget(
                        self.sage_file.directory, self.app_palette, i, parent=row_container
                    )
                    initial_path = image_paths[i]
                    if isinstance(initial_path, str) and initial_path:
                        loader.load_image(initial_path)
                    else:
                        pass

                    # Connect signals
                    loader.image_updated.connect(
                        lambda path, k=key, index=i: self._on_image_updated(k, index, path)
                    )
                    # *** NEW CONNECTION ***
                    loader.action_clicked.connect(self._handle_image_action_clicked)

                    row_layout.addWidget(loader)
                    image_loaders.append(loader)

                self.form_layout.addRow(key_label, row_container)
                self._widgets[key] = image_loaders  # Store the list of loader widgets

            elif key in self.ICON_BUTTON_KEYS:
                widget_container = QtWidgets.QWidget()
                hbox = QtWidgets.QHBoxLayout(widget_container)
                hbox.setContentsMargins(0, 0, 0, 0)
                hbox.setSpacing(5)

                button = ActionIconButton(
                    palette=self.app_palette,
                    action_string=f"TEXT_FIELD_ACTION_{key.replace(' ', '_')}",
                    tooltip=f"Generate {key} with AI",
                    parent=widget_container,
                )
                button.clicked_with_action.connect(self._common_icon_button_clicked_for_sage)

                value_widget = QtWidgets.QLineEdit()
                value_str = json.dumps(value) if isinstance(value, (dict, list)) else str(value)
                value_widget.setText(value_str)
                value_widget.setReadOnly(is_locked)
                # Use functools.partial for cleaner lambda alternative if preferred
                value_widget.textChanged.connect(
                    lambda text, k=key: self._on_text_field_changed(k, text)
                )
                self._apply_widget_styles(value_widget, is_locked)

                hbox.addWidget(button, 0, Qt.AlignmentFlag.AlignTop)
                hbox.addWidget(value_widget, 1)

                self.form_layout.addRow(key_label, widget_container)
                self._widgets[key] = value_widget  # Store the QLineEdit

            elif key == "Camera":
                # Dropdown for camera views
                combo = QtWidgets.QComboBox()
                for opt in ["None", "Side View", "Top Down", "Isometric"]:
                    combo.addItem(opt)
                # select current camera setting
                idx = combo.findText(value)
                combo.setCurrentIndex(idx if idx >= 0 else 0)
                combo.currentTextChanged.connect(
                    lambda text, k=key: self._on_text_field_changed(k, text)
                )
                # update our model immediately
                combo.currentTextChanged.connect(
                    lambda text: setattr(self.sage_file, "camera", text)
                )
                # lighten dropdown background and selection list
                combo.setStyleSheet(f"""
                    QComboBox {{
                        background-color: {self.app_palette.get('editable_value_bg', '#3A3A3A')};
                        color: {self.app_palette.get('text_color', '#D0D0D0')};
                        min-height: 24px;
                        padding: 4px;
                    }}
                    QComboBox QAbstractItemView {{
                        background-color: {self.app_palette.get('editable_value_bg', '#3A3A3A')};
                        selection-background-color: {self.app_palette.get('selection_bg', '#BBBBBB')};
                        color: {self.app_palette.get('text_color', '#D0D0D0')};
                        padding: 4px;
                    }}
                """)
                # measure longest item and set width to a quarter of its text width (with minimum)
                fm = combo.fontMetrics()
                items = [combo.itemText(i) for i in range(combo.count())]
                max_w = max((fm.horizontalAdvance(txt) for txt in items), default=0)
                # ensure it's not too small
                combo.setFixedWidth(max(max_w // 4, 120))
                combo.setSizePolicy(
                    QtWidgets.QSizePolicy.Policy.Fixed,
                    QtWidgets.QSizePolicy.Policy.Fixed,
                )
                self.form_layout.addRow(key_label, combo)
                self._widgets[key] = combo
            else:  # Standard QLineEdit
                value_widget = QtWidgets.QLineEdit()
                value_str = json.dumps(value) if isinstance(value, (dict, list)) else str(value)
                value_widget.setText(value_str)
                value_widget.setReadOnly(is_locked)
                self._apply_widget_styles(value_widget, is_locked)
                # Use functools.partial for cleaner lambda alternative if preferred
                value_widget.textChanged.connect(
                    lambda text, k=key: self._on_text_field_changed(k, text)
                )
                self.form_layout.addRow(key_label, value_widget)
                self._widgets[key] = value_widget  # Store the QLineEdit

        # --- Project actions and sprite table ---
        sprite_buttons_label = QtWidgets.QLabel("Project Actions:")
        self._apply_label_styles(sprite_buttons_label)
        sprite_buttons_container = self._create_sprite_buttons()
        self.form_layout.addRow(sprite_buttons_label, sprite_buttons_container)
        self._widgets[self.SPRITE_BUTTONS_KEY] = sprite_buttons_container

        sprite_table_label = QtWidgets.QLabel("Loaded Sprites:")
        self._apply_label_styles(sprite_table_label)
        sprite_table = self._create_sprite_table()
        self.form_layout.addRow(sprite_table_label, sprite_table)
        self._widgets[self.SPRITE_TABLE_KEY] = sprite_table
        self._populate_sprite_table(sprite_table)
        # --- End Sprite Section ---

        self.form_layout.setFieldGrowthPolicy(
            QtWidgets.QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow
        )
        # Ensure initial layout is correct
        self.content_widget.adjustSize()

    # --- Helper methods for creating sprite UI elements ---
    def _create_sprite_buttons(self):
        container = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        # then a regular 'New Sprite' button
        new_sprite_button = QtWidgets.QPushButton("New Sprite")
        new_sprite_button.setStyleSheet(f"""
            QPushButton {{ background-color: {self.app_palette.get('button_bg', '#555555')}; color: {self.app_palette.get('button_fg', '#D3D3D3')}; border: 1px solid {self.app_palette.get('placeholder_border', '#555555')}; padding: 5px; min-height: 18px; }}
            QPushButton:hover {{ background-color: #6A6A6A; border: 1px solid #777777; }}
            QPushButton:pressed {{ background-color: #4E4E4E; }}
        """)
        new_sprite_button.clicked.connect(self._new_sprite_button_clicked)
        layout.addWidget(new_sprite_button)

        import_art_button = QtWidgets.QPushButton("Import Existing Art...")
        import_art_button.setStyleSheet(new_sprite_button.styleSheet())
        import_art_button.clicked.connect(self._import_art_button_clicked)
        layout.addWidget(import_art_button)

        import_model_button = QtWidgets.QPushButton("Import 3D Model...")
        import_model_button.setStyleSheet(new_sprite_button.styleSheet())
        import_model_button.clicked.connect(self._import_model_button_clicked)
        layout.addWidget(import_model_button)

        export_project_button = QtWidgets.QPushButton("Export Project")
        export_project_button.setStyleSheet(new_sprite_button.styleSheet())
        export_project_button.clicked.connect(self._export_project_to_godot)
        layout.addWidget(export_project_button)

        layout.addStretch(1)
        container.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        return container

    def _new_sprite_button_clicked(self):
        """Called when the 'New Sprite' button is clicked."""
        dialog = TextInputDialog(
            self,
            title="New Sprite",
            label_text="Enter sprite filename:",
            palette=self.app_palette,
        )
        ok = dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted
        filename = dialog.textValue()
        if ok and filename.strip():
            name = filename.strip()
            # Strip existing extension if provided
            if name.lower().endswith(".sprite"):
                name = name[:-7]
            sprite_file = f"{name}.sprite"
            # Ensure project directory is valid
            if self.sage_file and os.path.isdir(self.sage_file.directory):
                full_path = os.path.join(self.sage_file.directory, sprite_file)
                try:
                    sprite_content = EMPTY_SPRITE_TEMPLATE.copy()
                    sprite_content["uuid"] = str(uuid.uuid4())
                    # Create an empty sprite file
                    with open(full_path, "w") as f:
                        json.dump(sprite_content, f)
                except Exception as e:
                    QMessageBox.critical(self, "File Error", f"Could not create sprite file:\n{e}")
                    return
                # Invoke the same handler as selecting an existing sprite
                self._on_sprite_row_action(sprite_file)

    def _import_art_button_clicked(self):
        if not self.sage_file or not os.path.isdir(self.sage_file.directory):
            QMessageBox.warning(self, "Import Existing Art", "Project directory is not valid.")
            return

        dialog = ArtImportDialog(
            project_dir=self.sage_file.directory,
            palette=self.app_palette,
            parent=self,
        )
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return

        request = dialog.to_request()
        try:
            self._log_message(f"Importing existing art sprite: {request.options['sprite_name']}")
            result = call_with_busy(
                self,
                lambda: self._run_art_import(request),
                message=f"Importing {request.options['sprite_name']}",
                palette=self.app_palette,
            )
        except Exception as e:
            self._show_art_import_failed(e)
            self._log_message(f"Existing art import failed: {e}")
            return

        if result is None:
            self._show_art_import_failed(RuntimeError("The art import returned no result."))
            return

        self._refresh_sprite_table()
        self._show_art_import_complete(result)
        self._log_message(f"Existing art import complete: {result.sprite_path}")
        self.sprite_row_action.emit(str(result.sprite_path))

    def _run_art_import(self, request: ArtImportDialogRequest) -> ArtImportResult:
        if request.mode == "sequence":
            return import_image_sequence(**request.options)
        if request.mode == "folder":
            return import_folder(**request.options)
        if request.mode == "sheet":
            return import_sprite_sheet(**request.options)
        if request.mode == "aseprite":
            return import_aseprite_json(**request.options)
        raise ValueError(f"Unknown import mode: {request.mode}")

    def _import_model_button_clicked(self):
        if not self.sage_file or not os.path.isdir(self.sage_file.directory):
            QMessageBox.warning(self, "Import 3D Model", "Project directory is not valid.")
            return

        dialog = ModelBakeDialog(
            project_dir=self.sage_file.directory,
            palette=self.app_palette,
            parent=self,
        )
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return

        config = dialog.to_config()
        try:
            self._log_message(f"Baking 3D model sprite: {config.model_path}")
            result = call_with_busy(
                self,
                lambda: bake_model_to_sprite_project(config),
                message=f"Baking {config.sprite_name or config.model_path.stem} from 3D model",
                palette=self.app_palette,
            )
        except Exception as e:
            self._show_model_bake_failed(e)
            self._log_message(f"3D model import failed: {e}")
            return

        if result is None:
            self._show_model_bake_failed(RuntimeError("The model bake returned no result."))
            return

        self._refresh_sprite_table()
        self._show_model_bake_complete(result)
        self._log_message(f"3D model import complete: {result.sprite_path}")
        self.sprite_row_action.emit(str(result.sprite_path))

    def _create_sprite_table(self):
        table = QTableWidget()
        table.setColumnCount(3)
        table.setHorizontalHeaderLabels(["Sprite File", "Go To", "Remove"])
        table.setRowCount(0)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        table.verticalHeader().setVisible(False)
        table.setShowGrid(True)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setMinimumHeight(100)
        table.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.MinimumExpanding,
        )
        self._apply_table_styles(table)
        return table

    def _populate_sprite_table(self, sprite_table: QTableWidget):
        sage_file = self.sage_file
        if sage_file and os.path.isdir(sage_file.directory):
            sprite_files = []
            hidden_sprites = {
                path.replace("\\", "/") for path in getattr(sage_file, "hidden_sprites", [])
            }
            print(f"Searching for *.sprite files in: {sage_file.directory}")
            for root, _, files in os.walk(sage_file.directory):
                for filename in files:
                    if filename.lower().endswith(".sprite"):
                        full_path = os.path.join(root, filename)
                        try:
                            relative_path = os.path.relpath(full_path, sage_file.directory).replace(
                                "\\", "/"
                            )
                            if relative_path not in hidden_sprites:
                                sprite_files.append(relative_path)
                        except ValueError as e:
                            print(f"Warning: Could not get relative path for {full_path}: {e}")
            print(f"Found {len(sprite_files)} sprite files: {sprite_files}")
            sprite_table.setRowCount(len(sprite_files))
            for row_index, sprite_path in enumerate(sorted(sprite_files)):
                # file path column
                item = QTableWidgetItem(sprite_path)
                sprite_table.setItem(row_index, 0, item)
                # action button column (arrow)
                btn = QtWidgets.QPushButton()
                btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowRight))
                btn.setToolTip(f"Open {sprite_path}")
                btn.clicked.connect(lambda _, p=sprite_path: self._on_sprite_row_action(p))
                sprite_table.setCellWidget(row_index, 1, btn)
                remove_btn = QtWidgets.QPushButton()
                remove_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon))
                remove_btn.setToolTip(f"Remove {sprite_path} from this project")
                remove_btn.clicked.connect(
                    lambda _, p=sprite_path: self._remove_sprite_from_project(p)
                )
                sprite_table.setCellWidget(row_index, 2, remove_btn)
        else:
            print(
                "Warning: Cannot search for sprites, sage_file.directory is not valid: "
                f"{sage_file.directory if sage_file else None}"
            )

    def _refresh_sprite_table(self):
        sprite_table = self._widgets.get(self.SPRITE_TABLE_KEY)
        if isinstance(sprite_table, QTableWidget):
            sprite_table.setRowCount(0)
            self._populate_sprite_table(sprite_table)

    def _remove_sprite_from_project(self, sprite_path: str):
        sage_file = self._require_sage_file()
        normalized_path = sprite_path.replace("\\", "/")
        reply = QMessageBox.question(
            self,
            "Remove Sprite",
            (
                f"Remove '{normalized_path}' from this project?\n\n"
                "The .sprite file and image files will remain on disk."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        hidden_sprites = {
            path.replace("\\", "/") for path in getattr(sage_file, "hidden_sprites", [])
        }
        hidden_sprites.add(normalized_path)
        sage_file.hidden_sprites = sorted(hidden_sprites)
        sage_file.save()
        self.sage_file = sage_file
        self._refresh_sprite_table()
        self._log_message(f"Removed sprite from project: {normalized_path}")

    def _export_sprite_to_godot(self, sprite_path: str):
        sage_file = self._require_sage_file()
        # build default folder name from sprite base name
        base = os.path.splitext(os.path.basename(sprite_path))[0]
        default_name = f"{base}_godot_export"
        # ask user for folder name
        folder_name, ok = self._prompt_for_export_folder_name(default_name)
        if not ok or not folder_name.strip():
            return
        output_dir = self._resolve_godot_export_dir(folder_name.strip())
        try:
            sprite_file = SpriteFile.from_json(
                fpath=os.path.join(sage_file.directory, sprite_path),
                sage_directory=sage_file.directory,
            )

            def run_export(progress_callback=None):
                exporter = GodotSpriteExporter(
                    sprite_file=sprite_file,
                    output_dir=output_dir,
                    progress_callback=progress_callback,
                )
                exporter.export()

            call_with_progress(
                self,
                run_export,
                message="Preparing Godot export",
                progress_label="Exporting Godot sprite",
                palette=self.app_palette,
            )
            self._show_export_complete(sprite_path, output_dir)
        except Exception as e:
            self._show_export_failed(e)

    def _export_project_to_godot(self):
        sage_file = self._require_sage_file()
        project_name = os.path.splitext(os.path.basename(sage_file.filepath))[0] or "project"
        default_name = f"{project_name}_godot_export"
        folder_name, ok = self._prompt_for_export_folder_name(default_name)
        if not ok or not folder_name.strip():
            return

        output_dir = self._resolve_godot_export_dir(folder_name.strip())
        try:

            def run_export(progress_callback=None):
                exporter = GodotProjectExporter(
                    project_dir=sage_file.directory,
                    output_dir=output_dir,
                    progress_callback=progress_callback,
                    hidden_sprites=sage_file.hidden_sprites,
                )
                return exporter.export()

            exported_dirs = call_with_progress(
                self,
                run_export,
                message="Preparing Godot project export",
                progress_label="Exporting Godot project",
                progress_unit="sprites",
                palette=self.app_palette,
            )
            self._show_project_export_complete(output_dir, len(exported_dirs or []))
        except Exception as e:
            self._show_project_export_failed(e)

    def _resolve_godot_export_dir(self, folder_name: str) -> str:
        sage_file = self._require_sage_file()
        return os.path.join(sage_file.directory, self.EXPORTS_DIRNAME, folder_name)

    def _create_export_folder_dialog(self, default_name: str) -> TextInputDialog:
        return TextInputDialog(
            self,
            title="Godot Export Folder",
            label_text="Folder name:",
            default_text=default_name,
            palette=self.app_palette,
        )

    def _prompt_for_export_folder_name(self, default_name: str):
        dialog = self._create_export_folder_dialog(default_name)
        result = dialog.exec()
        accepted = result == QtWidgets.QDialog.DialogCode.Accepted
        return dialog.textValue(), accepted

    def _show_export_message(self, icon, title: str, text: str):
        box = QMessageBox(self)
        box.setIcon(icon)
        box.setWindowTitle(title)
        box.setText(text)
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.setStyleSheet(build_application_stylesheet(self.app_palette))
        box.exec()

    def _show_export_complete(self, sprite_path: str, output_dir: str):
        self._show_export_message(
            QMessageBox.Icon.Information,
            "Export Complete",
            f"Exported '{sprite_path}' to:\n{output_dir}",
        )

    def _show_export_failed(self, error: Exception):
        self._show_export_message(
            QMessageBox.Icon.Critical,
            "Export Failed",
            f"Could not export sprite:\n{error}",
        )

    def _show_project_export_complete(self, output_dir: str, sprite_count: int):
        self._show_export_message(
            QMessageBox.Icon.Information,
            "Export Complete",
            f"Exported {sprite_count} sprite(s) to:\n{output_dir}",
        )

    def _show_project_export_failed(self, error: Exception):
        self._show_export_message(
            QMessageBox.Icon.Critical,
            "Export Failed",
            f"Could not export project:\n{error}",
        )

    def _show_model_bake_complete(self, result: ModelBakeResult):
        animation_preview = ", ".join(result.animation_names[:6])
        if len(result.animation_names) > 6:
            animation_preview += f", +{len(result.animation_names) - 6} more"
        self._show_export_message(
            QMessageBox.Icon.Information,
            "Import Complete",
            (
                f"Created sprite:\n{result.sprite_path}\n\n"
                f"Frames: {result.frame_count}\n"
                f"Animations: {animation_preview}"
            ),
        )

    def _show_model_bake_failed(self, error: Exception):
        self._show_export_message(
            QMessageBox.Icon.Critical,
            "Import Failed",
            f"Could not import 3D model:\n{error}",
        )

    def _show_art_import_complete(self, result: ArtImportResult):
        animation_preview = ", ".join(result.animation_names[:6])
        if len(result.animation_names) > 6:
            animation_preview += f", +{len(result.animation_names) - 6} more"
        self._show_export_message(
            QMessageBox.Icon.Information,
            "Import Complete",
            (
                f"Created sprite:\n{result.sprite_path}\n\n"
                f"Frames: {result.frame_count}\n"
                f"Animations: {animation_preview}"
            ),
        )

    def _show_art_import_failed(self, error: Exception):
        self._show_export_message(
            QMessageBox.Icon.Critical,
            "Import Failed",
            f"Could not import existing art:\n{error}",
        )

    def _on_sprite_row_action(self, sprite_path: str):
        """Handle per-sprite action button click."""
        sage_file = self._require_sage_file()
        # build absolute path and emit for parent to load
        full_path = os.path.join(sage_file.directory, sprite_path)
        self.sprite_row_action.emit(full_path)

    def _log_message(self, message):
        parent_widget = self.parent()
        while parent_widget:
            console_widget = getattr(parent_widget, "console_widget", None)
            log_message = getattr(console_widget, "log_message", None)
            if callable(log_message):
                log_message(message)
                return
            parent_widget = parent_widget.parent()
        print(f"LOG (SageEditor): {message}")

    def _on_text_field_changed(self, key, text):
        """Handle text changes in any QLineEdit to emit content_changed."""
        # Optional: Could add logic here to validate text based on key if needed
        print(f"Content changed in field '{key}'")
        self.save()

    # Slot connected to ImageLoaderWidget's image_updated signal.
    def _on_image_updated(self, key, index, path):
        """Handles updates from ImageLoaderWidgets when an image is selected or cleared."""
        print(f"Image updated for key '{key}', index {index}, new path: '{path}'")
        self.save()

    # *** NEW SLOT *** to handle the action button click from ImageLoaderWidget
    def _handle_image_action_clicked(self, index: int):
        """Handles the action_clicked signal from an ImageLoaderWidget."""
        print(f"Action requested for image index: {index}")

        # 1. Get context needed for AI (desc, keywords, etc.)
        project_desc_widget = self._widgets.get("Project Description")
        keywords_widget = self._widgets.get("Keywords")
        camera_widget = self._widgets.get("Camera")
        image_loaders = self._widgets.get(self.REFERENCE_IMAGES_KEY)  # Get the list of loaders

        if (
            not isinstance(project_desc_widget, QtWidgets.QLineEdit)
            or not isinstance(keywords_widget, QtWidgets.QLineEdit)
            or not isinstance(camera_widget, QtWidgets.QComboBox)
            or not isinstance(image_loaders, list)
            or index >= len(image_loaders)
            or not isinstance(image_loaders[index], ImageLoaderWidget)
        ):
            QMessageBox.warning(
                self,
                "Error",
                "Cannot perform image action: Required editor fields or image widget are missing or invalid.",
            )
            return

        sage_file = self.sage_file
        if not sage_file or not os.path.isdir(sage_file.directory):
            QMessageBox.warning(
                self, "Error", "Cannot perform image action: Project directory is not valid."
            )
            return

        desc_text = project_desc_widget.text()
        keywords_text = keywords_widget.text()
        camera_value = camera_widget.currentText()
        current_image_widget = image_loaders[index]

        # 2. Call AI Model Manager (similar logic as before, but now inside SageEditorView)
        img_fpath = None
        mm = AIModelManager()
        if not ensure_llm_configured(self, mm):
            return
        try:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            # Pass absolute paths of *other* images as context if needed
            context_image_paths = sage_file.reference_image_abs_paths(exclude_index=index)
            print(
                f"Calling AI image generation with context: Desc='{desc_text}', Keywords='{keywords_text}', Other Images={context_image_paths}"
            )

            img_fpath = call_with_busy(
                self,
                lambda: mm.generate_reference_image(
                    input=GenerateReferenceImageInput(
                        output_folder=sage_file.directory,
                        project_description=desc_text,
                        keywords=keywords_text,
                        images=context_image_paths,
                        camera=camera_value,
                    )
                ),
                message=f"Generating reference image with {mm.get_active_vendor().value}",
                palette=self.app_palette,
            )

        except Exception as e:
            print(f"Error during AI image generation: {e}")
            QMessageBox.critical(self, "AI Error", f"Failed to generate image:\n\n{e}")
            img_fpath = None
        finally:
            if QApplication.overrideCursor() is not None:
                QApplication.restoreOverrideCursor()

        # 3. Process the generated image path (copy, make relative, update widget & data)
        if img_fpath and os.path.isfile(img_fpath):
            print(f"AI generated image successfully: {img_fpath}")
            target_dir = os.path.join(sage_file.directory, "reference_images")
            os.makedirs(target_dir, exist_ok=True)
            base_filename = os.path.basename(img_fpath)
            target_fpath = os.path.join(target_dir, base_filename)

            # Handle potential filename conflicts
            counter = 1
            name, ext = os.path.splitext(base_filename)
            while os.path.exists(target_fpath):
                target_fpath = os.path.join(target_dir, f"{name}_{counter}{ext}")
                counter += 1

            try:
                print(f"Copying generated image to: {target_fpath}")
                shutil.copy2(img_fpath, target_fpath)

                # Calculate the relative path for the widget and data
                relative_path = os.path.relpath(target_fpath, sage_file.directory).replace(
                    "\\", "/"
                )
                print(f"Calculated relative path: {relative_path}")

                # Update the specific ImageLoaderWidget
                current_image_widget.load_image(relative_path)

                # Update internal data structure (self.sage_file) - IMPORTANT for saving
                sage_file.reference_images[index] = relative_path

            except ValueError as ve:
                print(f"Error calculating relative path: {ve}")
                QMessageBox.critical(
                    self, "Path Error", f"Could not determine relative path for the image:\n{ve}"
                )
            except Exception as e:
                print(f"Error copying or processing generated image: {e}")
                QMessageBox.critical(
                    self, "File Error", f"Could not copy or process the generated image:\n{e}"
                )

        elif img_fpath:  # Path returned but not a valid file
            print(f"AI generation returned an invalid path or file: {img_fpath}")
            QMessageBox.warning(
                self, "AI Result Error", f"AI generated an invalid image file path:\n{img_fpath}"
            )
        # else: img_fpath is None (handled by try/except)
        self.save()

    # _common_icon_button_clicked_for_sage remains the same (handles Description/Keyword AI)
    def _common_icon_button_clicked_for_sage(self, action_string: str):
        """Handles clicks from ActionIconButtons next to text fields."""
        print(f"SageEditorView received action: {action_string}")
        project_desc_widget = self._widgets.get("Project Description")
        keywords_widget = self._widgets.get("Keywords")

        if not isinstance(project_desc_widget, QtWidgets.QLineEdit) or not isinstance(
            keywords_widget, QtWidgets.QLineEdit
        ):
            QMessageBox.warning(self, "Error", "Project Description or Keywords field is missing.")
            return

        current_desc = project_desc_widget.text()
        current_keywords = keywords_widget.text()
        sage_file = self._require_sage_file()
        context_image_paths = sage_file.reference_image_abs_paths()

        updated_desc = None
        updated_keywords = None
        mm = AIModelManager()
        if not ensure_llm_configured(self, mm):
            return

        try:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            print(f"Calling AI text generation with context: Images={context_image_paths}")

            if action_string.endswith("Project_Description"):
                updated_desc = call_with_busy(
                    self,
                    lambda: mm.generate_project_description(
                        input=GenerateDescriptionInput(
                            keywords=current_keywords,
                            images=context_image_paths,
                        )
                    ),
                    message=f"Generating project description with {mm.get_active_vendor().value}",
                    palette=self.app_palette,
                )
                if updated_desc:
                    project_desc_widget.setText(updated_desc)
                    print(f"  Generated Description: {updated_desc}")
                else:
                    QMessageBox.information(
                        self, "AI Result", "Could not generate a new project description."
                    )

            elif action_string.endswith("Keywords"):
                updated_keywords = call_with_busy(
                    self,
                    lambda: mm.generate_keywords(
                        GenerateKeywordsInput(
                            project_description=current_desc,
                            images=context_image_paths,
                        )
                    ),
                    message=f"Generating keywords with {mm.get_active_vendor().value}",
                    palette=self.app_palette,
                )
                if updated_keywords:
                    keywords_widget.setText(updated_keywords)
                    print(f"  Generated Keywords: {updated_keywords}")
                else:
                    QMessageBox.information(self, "AI Result", "Could not generate new keywords.")
            else:
                print(f"Warning: Unhandled action string in SageEditorView: {action_string}")

        except Exception as e:
            print(f"Error during AI generation: {e}")
            QMessageBox.critical(
                self, "AI Error", f"An error occurred during AI processing:\n\n{e}"
            )
        finally:
            if QApplication.overrideCursor() is not None:
                QApplication.restoreOverrideCursor()

    # _apply_label_styles, _apply_widget_styles, _apply_table_styles remain the same
    def _apply_label_styles(self, label_widget):
        label_widget.setStyleSheet(f"""
             QLabel {{
                 color: {self.app_palette.get('label_color', self.app_palette['text_color'])};
                 padding-right: 5px;
                 padding-top: 5px; /* Align with top of widget */
                 margin-top: 2px; /* Add slight margin for better alignment with LineEdit */
             }}
         """)
        label_widget.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)

    def _apply_widget_styles(self, value_widget, is_locked):
        bg_color = (
            self.app_palette["locked_value_bg"]
            if is_locked
            else self.app_palette["editable_value_bg"]
        )
        text_color = self.app_palette["text_color"]
        border_color = self.app_palette["placeholder_border"]
        font_style = "italic" if is_locked else "normal"
        value_widget.setStyleSheet(f"""
            QLineEdit {{
                background-color: {bg_color};
                color: {text_color};
                border: 1px solid {border_color};
                padding: 4px;
                font-style: {font_style};
                min-height: 18px;
            }}
            QLineEdit:read-only {{
                 background-color: {self.app_palette['locked_value_bg']};
                 font-style: italic;
            }}
            QLineEdit:focus {{
                border: 1px solid #BBBBBB;
                background-color: {self.app_palette.get('editable_value_focus_bg', bg_color)};
            }}
        """)

    @staticmethod
    def _debug_widget_text(widget) -> str:
        if isinstance(widget, QtWidgets.QLineEdit):
            return widget.text()
        if isinstance(widget, QtWidgets.QComboBox):
            return widget.currentText()
        return "N/A"

    def _apply_table_styles(self, table_widget: QTableWidget):
        text_color = self.app_palette.get("text_color", "#D0D0D0")
        header_bg = self.app_palette.get("table_header_bg", "#4A4A4A")
        header_fg = self.app_palette.get("table_header_fg", "#E0E0E0")
        grid_color = self.app_palette.get("table_grid_color", "#555555")
        bg_color = self.app_palette.get("editable_value_bg", "#3A3A3A")
        alt_bg_color = self.app_palette.get("table_alt_row_bg", "#404040")
        selection_bg = self.app_palette.get("selection_bg", "#5C5C5C")
        selection_fg = self.app_palette.get("selection_fg", "#FFFFFF")
        table_widget.setStyleSheet(f"""
            QTableWidget {{
                background-color: {bg_color};
                color: {text_color};
                gridline-color: {grid_color};
                border: 1px solid {self.app_palette.get('placeholder_border', '#555555')};
                alternate-background-color: {alt_bg_color};
                outline: 0;
            }}
            QTableWidget::item {{
                padding: 4px;
                border-bottom: 1px solid {grid_color};
                border-right: 1px solid {grid_color};
            }}
             QTableWidget::item:selected {{
                background-color: {selection_bg};
                color: {selection_fg};
            }}
            QHeaderView::section {{
                background-color: {header_bg};
                color: {header_fg};
                padding: 4px;
                border: 1px solid {grid_color};
                font-weight: bold;
            }}
            QTableCornerButton::section {{
                background-color: {header_bg};
                border: 1px solid {grid_color};
            }}
        """)

    # MODIFIED get_edited_data: Reads paths from ImageLoaderWidgets
    def get_modified_sage_file(self) -> SageFile:
        """Retrieves the current data from the editor widgets."""
        sage_file = self._require_sage_file()
        data = sage_file.to_dict().copy()
        edited_data = sage_file.to_dict().copy()  # Start with original data

        for key, widget_or_list in self._widgets.items():
            if (
                key in [self.SPRITE_BUTTONS_KEY, self.SPRITE_TABLE_KEY]
                or key in self.LOCKED_KEYS
                or key in self.HIDDEN_KEYS
            ):
                continue

            original_value = data.get(key)

            try:
                if key == self.REFERENCE_IMAGES_KEY and isinstance(widget_or_list, list):
                    image_paths = []
                    for i in range(4):  # Ensure exactly 4 entries
                        if i < len(widget_or_list) and isinstance(
                            widget_or_list[i], ImageLoaderWidget
                        ):
                            # Use get_relative_path() which stores the intended path
                            rel_path = widget_or_list[i].get_relative_path(
                                sage_dir=sage_file.directory
                            )
                            image_paths.append(
                                rel_path if rel_path is not None else ""
                            )  # Ensure "" for None
                        else:
                            image_paths.append("")  # Placeholder if widget is missing or wrong type
                    print(f"DEBUG {image_paths}")
                    edited_data[key] = image_paths  # Should already be length 4
                elif isinstance(widget_or_list, QtWidgets.QComboBox):
                    # persist camera selection
                    edited_data[key] = widget_or_list.currentText()

                elif isinstance(widget_or_list, QtWidgets.QLineEdit):
                    # --- QLineEdit handling (same as before) ---
                    current_text = widget_or_list.text()
                    if isinstance(original_value, bool):
                        edited_data[key] = current_text.lower() in ["true", "1", "yes"]
                    elif isinstance(original_value, int):
                        edited_data[key] = int(current_text) if current_text.strip() else 0
                    elif isinstance(original_value, float):
                        edited_data[key] = float(current_text) if current_text.strip() else 0.0
                    elif isinstance(original_value, list) or isinstance(original_value, dict):
                        trimmed_text = current_text.strip()
                        if (trimmed_text.startswith("{") and trimmed_text.endswith("}")) or (
                            trimmed_text.startswith("[") and trimmed_text.endswith("]")
                        ):
                            try:
                                edited_data[key] = json.loads(trimmed_text)
                            except json.JSONDecodeError:
                                print(f"Warning: Invalid JSON in field '{key}'. Saving as string.")
                                edited_data[key] = current_text
                        else:
                            if (
                                original_value is not None
                                and current_text != json.dumps(original_value)
                                and current_text != str(original_value)
                            ):
                                print(
                                    f"Warning: Field '{key}' originally complex type, now saving as string: '{current_text}'"
                                )
                            edited_data[key] = current_text
                    else:
                        edited_data[key] = current_text
                # Add other widget types here if needed

            except (ValueError, TypeError) as ve:  # Catch conversion errors
                current_val_text = self._debug_widget_text(widget_or_list)
                print(
                    f"Warning: Invalid value '{current_val_text}' for key '{key}'. Type mismatch ({ve}). Keeping original value."
                )
                edited_data[key] = original_value  # Revert
            except Exception as e:
                print(f"Error processing value for key '{key}': {e}. Keeping original value.")
                edited_data[key] = original_value  # Revert

        # Ensure required hidden keys are preserved
        for hidden_key in self.HIDDEN_KEYS:
            if hidden_key in data:
                edited_data[hidden_key] = data[hidden_key]
            elif hidden_key in edited_data:
                del edited_data[hidden_key]  # Remove if added erroneously

        return SageFile.from_dict(data=edited_data, filepath=sage_file.filepath)

    def save(self):
        self._undo_redo_manager.save_undo_state(self._require_sage_file())
        sage_file_to_save = self.get_modified_sage_file()
        sage_file_to_save.save()
        self.sage_file = sage_file_to_save

    def undo(self):
        undo_sage_file = self._undo_redo_manager.perform_undo(
            current_state=self.get_modified_sage_file()
        )
        if undo_sage_file:
            print(f"current: {self.get_modified_sage_file()}")
            print(f"undo state: {undo_sage_file}")
            undo_sage_file.save()
            self.load_data(sage_file=undo_sage_file)

    def redo(self):
        redo_sage_file = self._undo_redo_manager.perform_redo()
        if redo_sage_file:
            redo_sage_file.save()
            self.load_data(sage_file=redo_sage_file)
