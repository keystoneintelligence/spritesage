"""A small character → motion workflow using the existing Sprite Sage palette."""

from pathlib import Path
import json
import tempfile

from PySide6 import QtCore, QtGui, QtWidgets
from modelmanager import Cancelled, LocalConfig, ModelStore, get_profile
from modelmanager.enhancer import EnhancementError
from modelmanager.qt import ModelManagerDialog, run_task
from modelmanager.runtime import runtime_status

from spritesage.inference import GenerateBaseSpriteImageInput
from spritesage.local_inference import LocalAIClient
from spritesage.model_baker.animations import frame_times, inspect_animations
from spritesage.model_baker.cameras import resolve_view_set
from spritesage.model_baker.timing import animation_from_manifest
from spritesage.model_baker.vtk_baker import BakeConfig, bake
from spritesage.settings import SettingsStore
from spritesage.utils import style_popup_dialog

from .catalog import TemplateLibrary
from .service import (
    TransferRequest,
    read_transfer_request,
    run_transfer,
    safe_name,
    validate_request,
    write_gif,
)


class AnimationTransferDialog(QtWidgets.QDialog):
    def __init__(
        self,
        project_dir,
        palette,
        parent=None,
        *,
        sprite=None,
        project_description="",
        keywords="",
        library=None,
        settings_store=None,
    ):
        super().__init__(parent)
        self.project_dir = Path(project_dir)
        self.app_palette = palette
        self.project_description = project_description
        self.keywords = keywords
        self.library = library or TemplateLibrary()
        self.settings_store = settings_store or SettingsStore()
        self.settings = self.settings_store.load()
        self.local_config = self.settings.get("LOCAL_GENERATION") or {}
        self.result_data = None
        self.reference_path = ""
        self.clips = []
        self.templates = []
        self.existing_sprite = sprite is not None
        self.local_ready = False
        style_popup_dialog(self, palette)
        self.setStyleSheet(self.styleSheet() + f"""
            QScrollArea, QWidget#TransferBody, QWidget#TransferDirections,
            QWidget#TransferAdvanced {{ background: {palette['dialog_bg']}; border: none; }}
            QCheckBox::indicator {{ width: 13px; height: 13px; border: 1px solid {palette['placeholder_border']};
                background: {palette['dialog_input_bg']}; }}
            QCheckBox::indicator:checked {{ background: {palette['tree_item_selected_bg']}; }}
        """)
        self.setWindowTitle("Animate from template")
        self.resize(720, 760)
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        intro = QtWidgets.QLabel(
            "Give your character a motion from a 3D template. Local AI redraws each pose using your character image."
        )
        intro.setWordWrap(True)
        outer.addWidget(intro)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        body = QtWidgets.QWidget()
        body.setObjectName("TransferBody")
        layout = QtWidgets.QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 8, 0)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        character = QtWidgets.QHBoxLayout()
        image_column = QtWidgets.QVBoxLayout()
        self.image_preview = QtWidgets.QLabel("Character image")
        self.image_preview.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.image_preview.setFixedSize(150, 150)
        image_column.addWidget(self.image_preview)
        self.choose_image_button = QtWidgets.QPushButton("Choose image…")
        self.choose_image_button.clicked.connect(self._choose_image)
        image_column.addWidget(self.choose_image_button)
        character.addLayout(image_column)
        character_form = QtWidgets.QFormLayout()
        self.name_edit = QtWidgets.QLineEdit(sprite.name if sprite else "")
        self.name_edit.setPlaceholderText("e.g. Green Orc Warrior")
        self.name_edit.setReadOnly(self.existing_sprite)
        self.description_edit = QtWidgets.QPlainTextEdit(sprite.description if sprite else "")
        self.description_edit.setPlaceholderText("Describe the character, outfit and art style…")
        self.description_edit.setMaximumHeight(100)
        self.generate_reference_button = QtWidgets.QPushButton("Generate character image")
        self.generate_reference_button.clicked.connect(self._generate_reference)
        character_form.addRow("Name", self.name_edit)
        character_form.addRow("Description", self.description_edit)
        character_form.addRow("", self.generate_reference_button)
        character.addLayout(character_form, 1)
        layout.addLayout(character)

        template_row = QtWidgets.QHBoxLayout()
        self.type_combo = QtWidgets.QComboBox()
        self.type_combo.setAccessibleName("Character type")
        self.template_combo = QtWidgets.QComboBox()
        self.template_combo.setAccessibleName("Motion template")
        self.add_template_button = QtWidgets.QPushButton("Add template…")
        self.add_template_button.setToolTip("Register an animated GLB once, from any location")
        self.add_template_button.clicked.connect(self._add_template)
        template_row.addWidget(QtWidgets.QLabel("Type"))
        template_row.addWidget(self.type_combo)
        template_row.addWidget(self.template_combo, 1)
        template_row.addWidget(self.add_template_button)
        layout.addLayout(template_row)
        self.template_note = QtWidgets.QLabel()
        self.template_note.setWordWrap(True)
        layout.addWidget(self.template_note)
        self.animation_list = QtWidgets.QListWidget()
        self.animation_list.setAccessibleName("Animations to transfer")
        self.animation_list.setMinimumHeight(112)
        self.animation_list.setMaximumHeight(156)
        layout.addWidget(self.animation_list)

        camera_row = QtWidgets.QHBoxLayout()
        camera_row.addWidget(QtWidgets.QLabel("Camera"))
        self.view_combo = QtWidgets.QComboBox()
        self.view_combo.addItem("Level", "front3")
        self.view_combo.addItem("Isometric", "iso8")
        self.view_combo.addItem("Top down", "top")
        camera_row.addWidget(self.view_combo)
        camera_row.addStretch()
        self.preview_button = QtWidgets.QPushButton("Preview motion")
        self.preview_button.clicked.connect(self._preview_motion)
        camera_row.addWidget(self.preview_button)
        layout.addLayout(camera_row)
        self.directions_widget = QtWidgets.QWidget()
        self.directions_widget.setObjectName("TransferDirections")
        self.directions_layout = QtWidgets.QGridLayout(self.directions_widget)
        self.directions_layout.setContentsMargins(0, 0, 0, 0)
        self.direction_checks = {}
        layout.addWidget(self.directions_widget)

        self.advanced_toggle = QtWidgets.QCheckBox("Advanced settings")
        layout.addWidget(self.advanced_toggle)
        self.advanced_widget = QtWidgets.QWidget()
        self.advanced_widget.setObjectName("TransferAdvanced")
        advanced = QtWidgets.QFormLayout(self.advanced_widget)
        advanced.setContentsMargins(0, 0, 0, 0)
        self.frames_spin = QtWidgets.QSpinBox()
        self.frames_spin.setRange(2, 120)
        self.frames_spin.setValue(8)
        self.frames_spin.setToolTip(
            "Maximum frames per clip. The whole motion is sampled, never truncated."
        )
        self.size_combo = QtWidgets.QComboBox()
        for size in (64, 128, 256, 512):
            self.size_combo.addItem(f"{size} × {size}", size)
        self.size_combo.setCurrentIndex(1)
        self.resolution_combo = QtWidgets.QComboBox()
        for size in (512, 768, 1024):
            self.resolution_combo.addItem(f"{size} × {size}", size)
        self.fps_spin = QtWidgets.QDoubleSpinBox()
        self.fps_spin.setRange(1, 30)
        self.fps_spin.setValue(8)
        self.zoom_spin = QtWidgets.QDoubleSpinBox()
        self.zoom_spin.setRange(0.25, 2)
        self.zoom_spin.setSingleStep(0.1)
        self.zoom_spin.setValue(1)
        self.cleanup_check = QtWidgets.QCheckBox(
            "Remove white background and align frames to the source poses"
        )
        self.cleanup_check.setChecked(True)
        advanced.addRow("Frames per motion", self.frames_spin)
        advanced.addRow("Sprite size", self.size_combo)
        advanced.addRow("Generation size", self.resolution_combo)
        advanced.addRow("Sample rate", self.fps_spin)
        advanced.addRow("Camera zoom", self.zoom_spin)
        advanced.addRow(self.cleanup_check)
        recipe_note = QtWidgets.QLabel(
            "Pose prompts stay fixed for consistency. Prompt improvement still applies when creating the character image. Raw images are kept alongside the finished frames."
        )
        recipe_note.setWordWrap(True)
        advanced.addRow(recipe_note)
        layout.addWidget(self.advanced_widget)
        self.advanced_widget.hide()
        self.advanced_toggle.toggled.connect(self.advanced_widget.setVisible)
        layout.addStretch()

        model_row = QtWidgets.QHBoxLayout()
        self.model_status = QtWidgets.QLabel()
        self.model_status.setWordWrap(True)
        self.manage_button = QtWidgets.QPushButton("Manage local models…")
        self.manage_button.clicked.connect(self._manage_models)
        model_row.addWidget(self.model_status, 1)
        model_row.addWidget(self.manage_button)
        outer.addLayout(model_row)
        self.estimate_label = QtWidgets.QLabel()
        self.estimate_label.setWordWrap(True)
        outer.addWidget(self.estimate_label)
        buttons = QtWidgets.QHBoxLayout()
        self.resume_button = QtWidgets.QPushButton("Resume saved job…")
        self.resume_button.clicked.connect(self._resume_job)
        buttons.addWidget(self.resume_button)
        buttons.addStretch()
        close = QtWidgets.QPushButton("Cancel")
        close.clicked.connect(self.reject)
        self.generate_button = QtWidgets.QPushButton("Generate animation")
        self.generate_button.clicked.connect(self._generate)
        self.generate_button.setDefault(True)
        buttons.addWidget(close)
        buttons.addWidget(self.generate_button)
        outer.addLayout(buttons)
        self.type_combo.currentIndexChanged.connect(self._filter_templates)
        self.template_combo.currentIndexChanged.connect(self._load_clips)
        self.view_combo.currentIndexChanged.connect(self._build_directions)
        self.animation_list.itemChanged.connect(self._refresh_estimate)
        self.frames_spin.valueChanged.connect(self._refresh_estimate)
        self.fps_spin.valueChanged.connect(self._refresh_estimate)
        self.name_edit.textChanged.connect(self._refresh_estimate)
        self.description_edit.textChanged.connect(self._refresh_estimate)
        self._build_directions()
        self._load_templates()
        self._refresh_model()
        if sprite and sprite.base_image:
            self._set_reference(sprite.base_image)
        self._refresh_saved_jobs()

    def _refresh_saved_jobs(self):
        self.saved_jobs = []
        for path in sorted(
            self.project_dir.glob("sprites/*_transfer_*/request.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        ):
            try:
                request, _ = read_transfer_request(path)
                state = json.loads((path.parent / "progress.json").read_text())
                if state.get("complete") or (
                    self.existing_sprite and request.sprite_name != self.name_edit.text()
                ):
                    continue
                completed = sum(
                    bool(frame.get("sha256")) for frame in state.get("frames", {}).values()
                )
                label = f"{request.sprite_name} · {', '.join(request.animations)} · {completed} frames saved · {path.parent.name[-12:]}"
                self.saved_jobs.append((label, path))
            except (OSError, ValueError, TypeError, KeyError):
                continue
        self.resume_button.setVisible(bool(self.saved_jobs))

    def _resume_job(self):
        if not self.saved_jobs:
            return
        labels = [label for label, path in self.saved_jobs]
        if len(labels) == 1:
            label = labels[0]
        else:
            picker = QtWidgets.QInputDialog(self)
            style_popup_dialog(picker, self.app_palette)
            picker.setWindowTitle("Resume animation transfer")
            picker.setLabelText("Choose a saved job")
            picker.setComboBoxItems(labels)
            picker.setComboBoxEditable(False)
            if picker.exec() != QtWidgets.QDialog.DialogCode.Accepted:
                return
            label = picker.textValue()
        try:
            self.restore_request(self.saved_jobs[labels.index(label)][1])
        except Exception as error:
            self._error("Could not restore job", error)

    def restore_request(self, path):
        request, local = read_transfer_request(Path(path))
        template = next(
            (
                t
                for t in self.templates
                if Path(t.model_path).resolve() == request.model_path.resolve()
            ),
            None,
        )
        if template is None:
            template = self.library.register(request.model_path)
        self._load_templates(template.id)
        self.name_edit.setText(request.sprite_name)
        self.description_edit.setPlainText(request.description)
        self._set_reference(request.reference_image)
        self.view_combo.setCurrentIndex(self.view_combo.findData(request.view_set))
        for name, check in self.direction_checks.items():
            check.setChecked(name in request.directions)
        for index in range(self.animation_list.count()):
            item = self.animation_list.item(index)
            item.setCheckState(
                QtCore.Qt.CheckState.Checked
                if item.data(QtCore.Qt.ItemDataRole.UserRole) in request.animations
                else QtCore.Qt.CheckState.Unchecked
            )
        self.frames_spin.setValue(request.max_frames)
        self.fps_spin.setValue(request.fps)
        self.zoom_spin.setValue(request.zoom)
        self.size_combo.setCurrentIndex(self.size_combo.findData(request.output_size))
        self.resolution_combo.setCurrentIndex(
            self.resolution_combo.findData(request.generation_size)
        )
        self.cleanup_check.setChecked(request.clean_background)
        if local is not None:
            self.local_config = local
        self._refresh_model()

    def _load_templates(self, selected_id=None):
        try:
            self.templates = self.library.load()
        except (OSError, ValueError, TypeError, KeyError) as error:
            self.templates = []
            self._error("Motion templates", error)
        self.type_combo.blockSignals(True)
        self.type_combo.clear()
        self.type_combo.addItems(sorted({t.character_type for t in self.templates} or {"Humanoid"}))
        if selected_id:
            selected = next(t for t in self.templates if t.id == selected_id)
            self.type_combo.setCurrentText(selected.character_type)
        self.type_combo.blockSignals(False)
        self._filter_templates()
        if selected_id:
            self.template_combo.setCurrentIndex(self.template_combo.findData(selected_id))

    def _filter_templates(self):
        self.template_combo.blockSignals(True)
        self.template_combo.clear()
        for template in self.templates:
            if template.character_type == self.type_combo.currentText():
                self.template_combo.addItem(template.name, template.id)
        self.template_combo.blockSignals(False)
        self._load_clips()

    def _template(self):
        return next((t for t in self.templates if t.id == self.template_combo.currentData()), None)

    def _load_clips(self):
        self.animation_list.blockSignals(True)
        self.animation_list.clear()
        self.clips = []
        template = self._template()
        self.template_note.setText("Add an animated GLB to create your reusable motion library.")
        if template:
            try:
                self.clips = inspect_animations(template.model_path)
                self.template_note.setText(
                    "Select motions. Each checked direction creates another animation."
                )
                self.template_combo.setToolTip(template.model_path)
            except Exception as error:
                self.template_note.setText(
                    f"Template unavailable. Use Add template to reconnect it. {error}"
                )
        preferred = next(
            (c.name for c in self.clips if "walk" in c.name.lower()),
            self.clips[0].name if self.clips else "",
        )
        for clip in self.clips:
            item = QtWidgets.QListWidgetItem(f"{clip.name}   ·   {clip.duration:.2f} s")
            item.setData(QtCore.Qt.ItemDataRole.UserRole, clip.name)
            item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                QtCore.Qt.CheckState.Checked
                if clip.name == preferred
                else QtCore.Qt.CheckState.Unchecked
            )
            self.animation_list.addItem(item)
        self.animation_list.blockSignals(False)
        self._refresh_estimate()

    def _add_template(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Add motion template", "", "Animated models (*.glb)"
        )
        if not path:
            return
        try:
            template = self.library.register(path, character_type=self.type_combo.currentText())
            self._load_templates(template.id)
        except Exception as error:
            self._error("Could not add template", error)

    def _build_directions(self):
        while self.directions_layout.count():
            widget = self.directions_layout.takeAt(0).widget()
            if widget:
                widget.deleteLater()
        self.direction_checks.clear()
        for index, view in enumerate(resolve_view_set(self.view_combo.currentData())):
            check = QtWidgets.QCheckBox(view.name.replace("_", " ").title())
            check.setChecked(
                view.name
                == (
                    "front_right"
                    if self.view_combo.currentData() == "iso8"
                    else "top" if self.view_combo.currentData() == "top" else "right"
                )
            )
            check.toggled.connect(self._refresh_estimate)
            self.direction_checks[view.name] = check
            self.directions_layout.addWidget(check, index // 4, index % 4)
        self._refresh_estimate()

    def _selected_animations(self):
        return tuple(
            self.animation_list.item(i).data(QtCore.Qt.ItemDataRole.UserRole)
            for i in range(self.animation_list.count())
            if self.animation_list.item(i).checkState() == QtCore.Qt.CheckState.Checked
        )

    def _directions(self):
        return tuple(name for name, check in self.direction_checks.items() if check.isChecked())

    def _refresh_estimate(self):
        selected = self._selected_animations()
        count = sum(
            len(frame_times(c.duration, self.fps_spin.value(), self.frames_spin.value()))
            for c in self.clips
            if c.name in selected
        ) * len(self._directions())
        self.estimate_label.setText(
            f"{count} local image generations · several minutes per frame on older GPUs. Completed frames are kept; repeat the same choices to resume."
        )
        self.generate_button.setText(f"Generate {count} frames" if count else "Generate animation")
        self.generate_button.setEnabled(
            bool(
                count
                and self.reference_path
                and self.name_edit.text().strip()
                and self.description_edit.toPlainText().strip()
                and self.local_ready
            )
        )
        self.preview_button.setEnabled(bool(count))
        self.generate_reference_button.setEnabled(
            bool(self.description_edit.toPlainText().strip() and self.local_ready)
        )

    def _set_reference(self, path):
        pixmap = QtGui.QPixmap(str(path))
        if pixmap.isNull():
            self._error("Character image", ValueError("Choose a readable PNG, JPEG or WebP image."))
            return
        self.reference_path = str(Path(path).resolve())
        self.image_preview.setPixmap(
            pixmap.scaled(
                150,
                150,
                QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                QtCore.Qt.TransformationMode.SmoothTransformation,
            )
        )
        self.image_preview.setToolTip(self.reference_path)
        self._refresh_estimate()

    def _choose_image(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Choose character image",
            str(self.project_dir),
            "Images (*.png *.jpg *.jpeg *.webp)",
        )
        if path:
            self._set_reference(path)

    def _refresh_model(self):
        self.local_ready = False
        try:
            config = LocalConfig.from_dict(self.local_config)
            profile = get_profile(config.model_id)
            self.local_ready = (
                runtime_status(config) == "Ready"
                and ModelStore(config.model_root, config.state_root).status(profile) == "Ready"
                and "image_edit" in profile.capabilities
                and profile.max_references >= 2
            )
            self.model_status.setText(
                f"Local · {profile.name}"
                if self.local_ready
                else "Install or connect a local image model to begin."
            )
        except Exception:
            self.model_status.setText("Set up local image generation to begin.")
        self._refresh_estimate()

    def _manage_models(self):
        dialog = ModelManagerDialog(self.local_config, self, palette=self.app_palette)
        if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            self.local_config = dialog.selected_config or {}
            try:
                settings = self.settings_store.load()
                settings["LOCAL_GENERATION"] = self.local_config
                self.settings_store.save_preferences(settings)
            except Exception as error:
                self._error("Could not save local setup", error)
            self._refresh_model()

    def _generate_reference(self):
        # Capture Qt fields before entering the worker thread.
        description = self.description_edit.toPlainText().strip()
        input_data = GenerateBaseSpriteImageInput(
            str(self.project_dir / "sprites" / "character_references"),
            description,
            self.project_description,
            self.keywords or "game sprite, clear silhouette",
            [],
            "orthographic full-body view, plain white background",
        )
        local = dict(self.local_config)

        def task(progress, cancel):
            return LocalAIClient(
                {"LOCAL_GENERATION": local}, progress, cancel
            ).generate_base_sprite_image(input_data)

        while True:
            try:
                path = run_task(self, "Creating character image", task, self.app_palette)
                if path:
                    self._set_reference(path)
                return
            except Cancelled:
                return
            except EnhancementError as error:
                box = QtWidgets.QMessageBox(self)
                style_popup_dialog(box, self.app_palette)
                box.setWindowTitle("Prompt improvement failed")
                box.setText(str(error))
                retry = box.addButton("Retry", QtWidgets.QMessageBox.ButtonRole.AcceptRole)
                original = (
                    box.addButton(
                        "Use original prompt", QtWidgets.QMessageBox.ButtonRole.ActionRole
                    )
                    if error.generate_original
                    else None
                )
                box.addButton(QtWidgets.QMessageBox.StandardButton.Cancel)
                box.exec()
                if original and box.clickedButton() is original:
                    assert error.generate_original is not None
                    task = error.generate_original
                elif box.clickedButton() is not retry:
                    return
            except Exception as error:
                self._error("Character generation failed", error)
                return

    def to_request(self):
        template = self._template()
        if template is None:
            raise ValueError("Add a motion template first.")
        return TransferRequest(
            self.project_dir,
            Path(template.model_path),
            Path(self.reference_path),
            self.name_edit.text().strip(),
            self.description_edit.toPlainText().strip(),
            self._selected_animations(),
            self._directions(),
            self.view_combo.currentData(),
            self.fps_spin.value(),
            self.frames_spin.value(),
            self.size_combo.currentData(),
            self.resolution_combo.currentData(),
            self.zoom_spin.value(),
            self.cleanup_check.isChecked(),
        )

    def _generate(self):
        try:
            request = self.to_request()
            validate_request(request)
            if (
                not self.existing_sprite
                and (self.project_dir / f"{safe_name(request.sprite_name)}.sprite").exists()
            ):
                raise ValueError(
                    "A sprite with that filename already exists. Choose another name or animate it from its editor."
                )
            config = LocalConfig.from_dict(self.local_config)
            self.result_data = run_task(
                self,
                "Transferring animation",
                lambda progress, cancel: run_transfer(request, config, progress, cancel),
                self.app_palette,
            )
        except Cancelled:
            self.estimate_label.setText(
                "Paused. Completed frames are saved. Click Generate with the same choices to continue."
            )
            self._refresh_saved_jobs()
            return
        except Exception as error:
            self._refresh_saved_jobs()
            self._error(
                "Animation transfer stopped",
                f"{error}\n\nCompleted frames are saved. Retry with the same choices to resume.",
            )
            return
        self.accept()

    def _preview_motion(self):
        template = self._template()
        if template is None:
            return
        try:
            with tempfile.TemporaryDirectory(prefix="spritesage-motion-") as temporary:
                config = BakeConfig(
                    model_path=Path(template.model_path),
                    output_dir=Path(temporary),
                    view_set=self.view_combo.currentData(),
                    fps=self.fps_spin.value(),
                    size=256,
                    zoom=self.zoom_spin.value(),
                    selected_animations=[self._selected_animations()[0]],
                    selected_views=(self._directions()[0],),
                    max_frames=self.frames_spin.value(),
                    lock_camera=True,
                )
                from modelmanager.types import check_cancel

                result = run_task(
                    self,
                    "Previewing motion",
                    lambda progress, cancel: bake(
                        config, check_cancel=lambda: check_cancel(cancel)
                    ),
                    self.app_palette,
                )
                if result is None:
                    return
                manifest = json.loads(result.manifest_path.read_text())
                record = manifest["animations"][0]
                frames = next(iter(record["views"].values()))
                timing = animation_from_manifest(
                    record, name=record["name"], frames=frames, default_fps=config.fps
                )
                gif = Path(temporary) / "preview.gif"
                write_gif(
                    [Path(p) for p in frames],
                    gif,
                    [timing.frame_seconds(i) for i in range(len(frames))],
                    timing.loop,
                )
                dialog = QtWidgets.QDialog(self)
                style_popup_dialog(dialog, self.app_palette)
                dialog.setWindowTitle(f"{record['name']} · {next(iter(record['views']))}")
                layout = QtWidgets.QVBoxLayout(dialog)
                label = QtWidgets.QLabel()
                movie = QtGui.QMovie(str(gif))
                label.setMovie(movie)
                layout.addWidget(label)
                close = QtWidgets.QPushButton("Close")
                close.clicked.connect(dialog.accept)
                layout.addWidget(close)
                movie.start()
                dialog.exec()
                movie.stop()
                label.clear()
                movie.setFileName("")
        except Cancelled:
            return
        except Exception as error:
            self._error("Motion preview failed", error)

    def _error(self, title, error):
        box = QtWidgets.QMessageBox(
            QtWidgets.QMessageBox.Icon.Warning, title, str(error), parent=self
        )
        style_popup_dialog(box, self.app_palette)
        box.exec()
