from unittest.mock import Mock

import pytest

from spritesage import inference, local_inference, menu_bar


@pytest.fixture(scope="module")
def qapp():
    from PySide6 import QtWidgets

    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def ready_client(monkeypatch, settings=None):
    monkeypatch.setattr(local_inference, "runtime_status", lambda config: "Ready")
    monkeypatch.setattr(local_inference.ModelStore, "status", lambda *args: "Ready")
    return local_inference.LocalAIClient(settings or {})


def test_local_images_need_no_cloud_api_key(monkeypatch, tmp_path):
    client = ready_client(monkeypatch)
    generate = Mock(return_value=str(tmp_path / "result.png"))
    monkeypatch.setattr(local_inference, "generate_image", generate)
    item = Mock(output_folder=str(tmp_path), images=["first.png", "second.png"])
    item.to_prompt.return_value = "between frames"
    assert client.generate_sprite_between_images(item).endswith("result.png")
    assert generate.call_args.args[1:3] == ("between frames", ["first.png", "second.png"])
    constraints = " ".join(generate.call_args.kwargs["constraints"])
    assert "<image1>" in constraints and "<image2>" in constraints
    assert "plain white background" in constraints


def test_local_text_has_no_silent_cloud_fallback(monkeypatch):
    client = ready_client(monkeypatch, {"OPENAI_API_KEY": "key", "OPENAI_TEXT_MODEL": "model"})
    with pytest.raises(inference.MissingConfigurationException, match="Enter text manually"):
        client.generate_description(Mock())


def test_explicit_cloud_text_needs_no_cloud_image_model(monkeypatch):
    client = ready_client(
        monkeypatch,
        {"LOCAL_TEXT_PROVIDER": "OPENAI", "OPENAI_API_KEY": "key", "OPENAI_TEXT_MODEL": "text"},
    )
    cloud = Mock()
    constructor = Mock(return_value=cloud)
    monkeypatch.setattr(local_inference, "OpenAIClient", constructor)
    item = Mock()
    client.generate_keywords(item)
    constructor.assert_called_once_with(api_key="key", text_model="text")
    cloud.generate_keywords.assert_called_once_with(item)


def test_local_missing_setup_opens_configuration_path(monkeypatch):
    monkeypatch.setattr(local_inference, "runtime_status", lambda config: "Not installed")
    with pytest.raises(inference.MissingConfigurationException, match="Manage local models"):
        local_inference.LocalAIClient({})


def test_local_settings_keep_existing_provider_defaults(qapp):
    dialog = menu_bar.SettingsDialog({})
    assert dialog.inference_radio_buttons[inference.AIModel.TESTING].isChecked()
    assert dialog.local_panel.isHidden()
    dialog.inference_radio_buttons[inference.AIModel.LOCAL].setChecked(True)
    assert not dialog.local_panel.isHidden()
    assert dialog.local_text_provider.currentData() == "NONE"
    captured = []
    dialog.settings_saved.connect(captured.append)
    dialog.save_settings()
    assert captured[0]["Selected Inference Provider"] == "LOCAL"
    assert captured[0]["LOCAL_TEXT_PROVIDER"] == "NONE"


def test_reference_generation_does_not_acquire_sprite_only_constraints(monkeypatch, tmp_path):
    client = ready_client(monkeypatch)
    generate = Mock(return_value="reference.png")
    monkeypatch.setattr(local_inference, "generate_image", generate)
    item = inference.GenerateReferenceImageInput(
        str(tmp_path), "landscape game", "forest", [], "top down"
    )
    client.generate_reference_image(item)
    constraints = " ".join(generate.call_args.kwargs["constraints"])
    assert "top down" in constraints
    assert "plain white" not in constraints


def test_packaged_diagnostic_uses_normal_sprite_adapter(monkeypatch, tmp_path, capsys):
    import json

    client = ready_client(monkeypatch)
    monkeypatch.setattr(local_inference, "LocalAIClient", lambda *a: client)
    generate = Mock(return_value="sprite.png")
    monkeypatch.setattr(client, "generate_base_sprite_image", generate)
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps(
            {
                "operation": "base",
                "config": {},
                "input": {
                    "output_folder": str(tmp_path),
                    "sprite_description": "wizard",
                    "project_description": None,
                    "keywords": None,
                    "images": [],
                    "camera": "side view",
                },
            }
        )
    )
    assert local_inference.test_local_generation(request) == 0
    assert isinstance(generate.call_args.args[0], inference.GenerateBaseSpriteImageInput)
    assert '"output": "sprite.png"' in capsys.readouterr().out
