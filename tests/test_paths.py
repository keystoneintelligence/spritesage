import json
import ntpath
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image
from PySide6 import QtWidgets

from spritesage import config, paths, sage_editor, main_window
from spritesage.animation_service import plan_frame_copy
from spritesage.art_import_dialog import ArtImportDialog
from spritesage.exporter import GodotSpriteExporter
from spritesage.export_ui import GodotExportUiMixin
from spritesage.project_paths import remap_project_references
from spritesage.sage_file import SageFile
from spritesage.sprite_file import Animation, SpriteFile


@pytest.fixture(scope="session", autouse=True)
def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def sprite_data():
    return {
        "uuid": "hero",
        "name": "Hero",
        "description": "Do not rewrite art/idle.png here",
        "width": 8,
        "height": 8,
        "base_image": "art/idle.png",
        "animations": {"idle": ["art/idle.png"]},
    }


def test_source_resources_do_not_depend_on_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = Path(config.__file__).resolve().parents[2]
    assert config.base_dir() == str(root)
    assert (Path(config.base_dir()) / "graphics" / "logo_large.png").is_file()
    monkeypatch.setattr(config.sys, "_MEIPASS", str(tmp_path / "bundle"), raising=False)
    assert config.base_dir() == str(tmp_path / "bundle")


def test_relative_sprite_assets_use_project_directory_not_working_directory(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(tmp_path)
    sprite = SpriteFile(
        "id", "Hero", "", 8, 8, "art/base.png", {"idle": Animation("idle", [r"art\frame.png"])}
    )
    data = sprite.to_dict(str(project))
    assert data["base_image"] == "art/base.png"
    assert data["animations"]["idle"]["frames"][0]["path"] == "art/frame.png"
    loaded = SpriteFile.from_dict(data, str(project))
    assert loaded.base_image == str(project / "art" / "base.png")
    assert loaded.animations["idle"].frames == [str(project / "art" / "frame.png")]


def test_sage_paths_are_portable_and_relative_project_file_is_anchored(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    project = SageFile.from_dict({"Reference Images": [r"art\ref.png", ""]}, "project.sage")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert project.filepath == str(tmp_path / "project.sage")
    assert project.to_dict()["Reference Images"] == ["art/ref.png", ""]


@pytest.mark.parametrize("value", ["", ".", "./", "folder"])
def test_empty_or_directory_animation_frame_is_rejected(tmp_path, value):
    (tmp_path / "folder").mkdir()
    data = sprite_data()
    data["animations"] = {"idle": [value]}
    with pytest.raises(ValueError, match="image file"):
        SpriteFile.from_dict(data, str(tmp_path))
    sprite = SpriteFile("id", "Hero", "", 8, 8, "", {"idle": Animation("idle", [value])})
    with pytest.raises(ValueError, match="image file"):
        sprite.to_dict(str(tmp_path))


def test_cross_drive_assets_survive_save_and_reload(monkeypatch):
    monkeypatch.setattr(paths, "os", SimpleNamespace(path=ntpath))
    sprite = SpriteFile(
        "id", "Hero", "", 8, 8, "D:/art/base.png", {"idle": Animation("idle", ["D:/art/frame.png"])}
    )
    data = sprite.to_dict("C:/project")
    assert data["base_image"] == "D:/art/base.png"
    assert data["animations"]["idle"]["frames"][0]["path"] == "D:/art/frame.png"
    loaded = SpriteFile.from_dict(data, "C:/project")
    assert ntpath.normcase(loaded.base_image) == ntpath.normcase("D:/art/base.png")


def test_windows_containment_handles_case_and_component_boundaries(monkeypatch):
    monkeypatch.setattr(paths, "os", SimpleNamespace(path=ntpath))
    assert paths.path_is_within("c:/PROJECT/art/a.png", "C:/Project")
    assert not paths.path_is_within("C:/Project-copy/a.png", "C:/Project")
    assert not paths.path_is_within("D:/Project/a.png", "C:/Project")
    assert ntpath.normcase(
        paths.remap_path("c:/PROJECT/art/a.png", "C:/Project/art", "C:/Project/images")
    ) == ntpath.normcase("C:/Project/images/a.png")


def test_frame_copy_accepts_relative_project_directory_without_copying(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    frame = project / "frame.png"
    frame.touch()
    monkeypatch.chdir(tmp_path)
    plan = plan_frame_copy(str(frame), "project")
    assert not plan.requires_copy
    assert plan.stored_path == str(frame)


@pytest.mark.parametrize(
    "name",
    [
        "../outside",
        r"..\outside",
        "/absolute",
        "C:outside",
        "CON",
        "nul.png",
        "LPT1",
        "COM¹",
        "foo.",
        "bad?name",
        ".",
        "..",
    ],
)
def test_export_folder_rejects_path_expressions_and_windows_invalid_names(tmp_path, name):
    widget = SimpleNamespace(_godot_export_project_directory=lambda: str(tmp_path))
    with pytest.raises(ValueError):
        GodotExportUiMixin._resolve_godot_export_dir(widget, name)


@pytest.mark.parametrize("name", ["../outside", r"..\outside", "C:outside", "CON", "Hero/Attack"])
def test_exported_asset_names_remain_in_chosen_directory(tmp_path, name):
    frame = tmp_path / "frame.png"
    Image.new("RGBA", (8, 8)).save(frame)
    sprite = SpriteFile("id", name, "", 8, 8, "", {"idle": Animation("idle", [str(frame)])})
    output = tmp_path / "export"
    exporter = GodotSpriteExporter(sprite, str(output))
    exporter.export()
    safe = paths.safe_asset_name(name)
    assert (output / f"{safe}.tscn").is_file()
    tres = (output / f"{safe}_frames.tres").read_text()
    assert f'path="{safe}_sheet.png"' in tres
    assert len([path for path in output.iterdir() if not path.name.startswith(".spritesage-")]) == 3
    assert not (tmp_path / "outside.tscn").exists()


def test_blank_import_folder_is_not_the_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    dialog = ArtImportDialog(tmp_path, config.APP_PALETTE)
    dialog.sprite_name_edit.setText("Hero")
    dialog.tabs.setCurrentIndex(1)
    errors = []
    monkeypatch.setattr(dialog, "_show_validation_error", errors.append)
    dialog.accept()
    assert errors == ["Select an existing folder."]
    assert dialog.result() == QtWidgets.QDialog.DialogCode.Rejected


@pytest.mark.parametrize("name", ["hero", "../outside", "CON", "C:outside"])
def test_new_sprite_cannot_overwrite_or_escape_project(tmp_path, monkeypatch, name):
    existing = tmp_path / "hero.sprite"
    existing.write_text(json.dumps(sprite_data()))
    original = existing.read_bytes()
    view = sage_editor.SageEditorView(config.APP_PALETTE)
    view.sage_file = SageFile.from_dict({}, str(tmp_path / "project.sage"))
    dialog = SimpleNamespace(
        exec=lambda: QtWidgets.QDialog.DialogCode.Accepted, textValue=lambda: name
    )
    monkeypatch.setattr(sage_editor, "TextInputDialog", lambda *args, **kwargs: dialog)
    messages = []
    monkeypatch.setattr(sage_editor.QMessageBox, "warning", lambda *args: messages.append(args[2]))
    view._new_sprite_button_clicked()
    assert messages
    assert existing.read_bytes() == original
    assert list(tmp_path.glob("*.sprite")) == [existing]
    assert not (tmp_path.parent / "outside.sprite").exists()


def test_folder_rename_updates_legacy_and_current_sprite_paths_and_project(tmp_path):
    art = tmp_path / "art"
    art.mkdir()
    (art / "idle.png").touch()
    project = tmp_path / "project.sage"
    project.write_text(
        json.dumps(
            {"Reference Images": ["art/idle.png", ""], "Hidden Sprites": ["art/hidden.sprite"]}
        )
    )
    legacy = tmp_path / "legacy.sprite"
    legacy.write_text(json.dumps(sprite_data()))
    modern_data = SpriteFile.from_dict(sprite_data(), str(tmp_path)).to_dict(str(tmp_path))
    modern_data["animations"]["idle"]["frames"][0]["duration"] = 2
    modern = art / "hidden.sprite"
    modern.write_text(json.dumps(modern_data))
    new = tmp_path / "images"
    art.rename(new)
    changed = remap_project_references(
        str(project), str(art), str(new), original_project_dir=str(tmp_path)
    )
    assert changed == {str(project), str(legacy), str(new / "hidden.sprite")}
    saved = json.loads(project.read_text())
    assert saved["Reference Images"] == ["images/idle.png", ""]
    assert saved["Hidden Sprites"] == ["images/hidden.sprite"]
    for path in (legacy, new / "hidden.sprite"):
        saved = json.loads(path.read_text())
        assert saved["description"] == "Do not rewrite art/idle.png here"
        sprite = SpriteFile.from_json(str(path), str(tmp_path))
        assert sprite.base_image == str(new / "idle.png")
        assert sprite.animations["idle"].frames == [str(new / "idle.png")]
    assert (
        json.loads((new / "hidden.sprite").read_text())["animations"]["idle"]["frames"][0][
            "duration"
        ]
        == 2
    )


def test_project_root_rename_preserves_relative_references(tmp_path):
    old = tmp_path / "old"
    old.mkdir()
    project = old / "project.sage"
    project.write_text(json.dumps({"Reference Images": ["art/idle.png"]}))
    sprite = old / "hero.sprite"
    sprite.write_text(json.dumps(sprite_data()))
    new = tmp_path / "new"
    old.rename(new)
    remap_project_references(
        str(new / project.name), str(old), str(new), original_project_dir=str(old)
    )
    assert json.loads((new / project.name).read_text())["Reference Images"] == ["art/idle.png"]
    assert json.loads((new / sprite.name).read_text())["base_image"] == "art/idle.png"


def test_live_sprite_and_project_context_follow_renamed_reference(tmp_path, monkeypatch):
    monkeypatch.setattr(main_window, "refresh_model_cache_for_settings", lambda settings: {})
    project = tmp_path / "project.sage"
    project.write_text(json.dumps({"Reference Images": ["old.png"]}))
    image = tmp_path / "old.png"
    Image.new("RGBA", (8, 8)).save(image)
    data = sprite_data()
    data["base_image"] = "old.png"
    data["animations"] = {"idle": ["old.png"]}
    sprite = tmp_path / "hero.sprite"
    sprite.write_text(json.dumps(data))
    window = main_window.MainWindow(logo_path=None)
    window._load_project(str(tmp_path), str(project))
    window.editor_widget.load_file(str(sprite))
    renamed = tmp_path / "new.png"
    image.rename(renamed)
    window._on_sidebar_file_renamed(str(image), str(renamed))
    editor = window.editor_widget.sprite_editor
    assert editor.sprite_data.base_image == str(renamed)
    assert editor.sage_file.reference_images == [str(renamed)]
    assert window.editor_widget.sage_editor.sage_file.reference_images == [str(renamed)]
    editor.save()
    assert json.loads(sprite.read_text())["base_image"] == "new.png"
    window.close()


@pytest.mark.parametrize("default_name", ["idle", "IDLE"])
def test_import_folder_preserves_colliding_animation_folder_names(tmp_path, default_name):
    from spritesage.art_importer import import_folder

    project = tmp_path / "project"
    project.mkdir()
    source = tmp_path / "source"
    for folder, color in [(source, "red"), (source / "idle", "blue")]:
        folder.mkdir(parents=True, exist_ok=True)
        Image.new("RGBA", (8, 8), color).save(folder / "frame.png")
    result = import_folder(
        project_dir=project,
        sprite_name="CON",
        folder_path=source,
        default_animation_name=default_name,
    )
    assert result.sprite_path.name == "CON_.sprite"
    sprite = SpriteFile.from_json(str(result.sprite_path), str(project))
    assert set(sprite.animations) == {default_name, "idle_2"}
    colors = {
        Image.open(animation.frames[0]).getpixel((0, 0)) for animation in sprite.animations.values()
    }
    assert colors == {(255, 0, 0, 255), (0, 0, 255, 255)}


def test_saved_job_paths_resolve_from_request_file(tmp_path, monkeypatch):
    from spritesage.animation_transfer.service import read_transfer_request

    folder = tmp_path / "job"
    folder.mkdir()
    request = folder / "request.json"
    request.write_text(
        json.dumps(
            {
                "request": {
                    "project_dir": "../project",
                    "model_path": "models/model.glb",
                    "reference_image": r"images\hero.png",
                    "sprite_name": "Hero",
                    "description": "Hero",
                    "animations": ["walk"],
                }
            }
        )
    )
    monkeypatch.chdir(tmp_path)
    loaded, _ = read_transfer_request(request)
    assert loaded.project_dir == tmp_path / "project"
    assert loaded.model_path == folder / "models" / "model.glb"
    assert loaded.reference_image == folder / "images" / "hero.png"


def test_imported_manifest_and_aseprite_windows_separators_are_portable(tmp_path):
    from spritesage.art_importer import _resolve_aseprite_sheet_path
    from spritesage.model_baker.sprite_writer import _resolve_manifest_path

    folder = tmp_path / "art"
    folder.mkdir()
    image = folder / "sheet.png"
    image.touch()
    assert _resolve_manifest_path(r"art\sheet.png", tmp_path) == image
    data = {"meta": {"image": r"art\sheet.png"}}
    assert _resolve_aseprite_sheet_path(data, tmp_path / "sprite.json", None) == image


def test_model_export_can_reference_sheet_more_than_one_folder_away(tmp_path):
    from spritesage.model_baker.godot_exporter import _godot_rel_path

    image = tmp_path / "art" / "sheet.png"
    output = tmp_path / "exports" / "hero" / "godot"
    assert _godot_rel_path(image, output) == "../../../art/sheet.png"


def test_google_creates_output_directory_before_request(tmp_path, monkeypatch):
    from spritesage import inference

    destination = tmp_path / "output" / "new"

    def generate(**kwargs):
        assert destination.is_dir()
        return SimpleNamespace(candidates=[])

    monkeypatch.setattr(
        inference.genai,
        "Client",
        lambda **kwargs: SimpleNamespace(models=SimpleNamespace(generate_content=generate)),
    )
    client = inference.GoogleAIClient(api_key="offline")
    client.generate_reference_image(
        inference.GenerateReferenceImageInput(str(destination), "description", "", [], "")
    )


def test_legacy_null_optional_images_load_as_empty_slots(tmp_path):
    data = sprite_data()
    data["base_image"] = None
    sprite = SpriteFile.from_dict(data, str(tmp_path))
    assert sprite.base_image == ""
    assert sprite.to_dict(str(tmp_path))["base_image"] == ""
    project = SageFile.from_dict({"Reference Images": [None, ""]}, str(tmp_path / "project.sage"))
    assert project.reference_images == ["", ""]
    assert project.to_dict()["Reference Images"] == ["", ""]


def test_relative_model_bake_paths_and_colliding_clip_names(tmp_path, monkeypatch):
    from spritesage.model_baker import vtk_baker
    from spritesage.model_baker.animations import AnimationClip
    from spritesage.model_baker.sprite_writer import write_sprite_file_from_manifest

    monkeypatch.chdir(tmp_path)
    Path("hero.glb").touch()
    clips = [AnimationClip(0, "Walk Run", 0.0), AnimationClip(1, "Walk_Run", 0.0)]
    model = SimpleNamespace(
        deformed_points=lambda *args: None,
        to_polydata=lambda *args: SimpleNamespace(GetBounds=lambda: (0, 1, 0, 1, 0, 1)),
    )
    monkeypatch.setattr(vtk_baker, "inspect_animations", lambda *args: clips)
    monkeypatch.setattr(vtk_baker, "_load_model", lambda *args: model)
    monkeypatch.setattr(
        vtk_baker, "resolve_view_set", lambda *args: [SimpleNamespace(name="front")]
    )
    monkeypatch.setattr(vtk_baker, "extract_texture_from_gltf_or_glb", lambda *args: None)
    monkeypatch.setattr(
        vtk_baker, "_create_renderer", lambda *args: (SimpleNamespace(Finalize=lambda: None), None)
    )
    monkeypatch.setattr(
        vtk_baker,
        "_render_frame",
        lambda **kwargs: Image.new("RGBA", (8, 8)).save(kwargs["output_path"]),
    )
    result = vtk_baker.bake(
        vtk_baker.BakeConfig(
            model_path=Path("hero.glb"), output_dir=Path("output"), size=8, max_frames=1
        )
    )
    manifest = json.loads(result.manifest_path.read_text())
    frame_paths = [Path(record["views"]["front"][0]) for record in manifest["animations"]]
    assert frame_paths[0] != frame_paths[1]
    assert all(path.is_absolute() and path.is_file() for path in frame_paths)
    assert frame_paths[0].parent.parent.name == "Walk_Run"
    assert frame_paths[1].parent.parent.name == "Walk_Run_2"
    written = write_sprite_file_from_manifest(
        result.manifest_path, sprite_path=tmp_path / "hero.sprite", project_dir=tmp_path
    )
    assert written.frame_count == 2


def test_live_project_root_rename_updates_editor_sidebar_and_recents(tmp_path, monkeypatch):
    monkeypatch.setattr(main_window, "refresh_model_cache_for_settings", lambda settings: {})
    old = tmp_path / "old"
    old.mkdir()
    project = old / "project.sage"
    project.write_text(json.dumps({"Reference Images": []}))
    sprite = old / "hero.sprite"
    data = sprite_data()
    data["base_image"] = ""
    data["animations"] = {}
    sprite.write_text(json.dumps(data))
    window = main_window.MainWindow(logo_path=None)
    window._load_project(str(old), str(project))
    window.editor_widget.load_file(str(sprite))
    new = tmp_path / "new"
    old.rename(new)
    window._on_sidebar_file_renamed(str(old), str(new))
    assert window.current_project_path == str(new)
    assert window.current_project_file == str(new / project.name)
    assert window.editor_widget.current_file_path == str(new / sprite.name)
    assert window.sidebar_widget.current_project_path == str(new)
    assert window.editor_widget.sprite_editor.sage_file.directory == str(new)
    assert [entry["path"] for entry in window.recent_projects] == [str(new / project.name)]
    window.close()
