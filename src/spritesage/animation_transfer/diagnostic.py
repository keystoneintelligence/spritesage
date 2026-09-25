"""Exercise the production transfer pipeline from source or a packaged application."""

import json
from pathlib import Path

from spritesage.settings import SettingsStore
from .service import config_from_saved, config_from_settings, read_transfer_request, run_transfer


def test_animation_transfer(request_path):
    try:
        request, stored_config = read_transfer_request(Path(request_path))
        settings = SettingsStore().load()
        if stored_config is None:
            config = config_from_settings(settings)
        elif stored_config.get("provider") in ("OPENAI", "GOOGLEAI"):
            config = config_from_settings(settings)
            if config.to_dict() != stored_config:
                raise ValueError("Select the saved image provider and model in Preferences first.")
        else:
            config = config_from_saved(stored_config)
        result = run_transfer(request, config, lambda update: print(update.message, flush=True))
        print(
            json.dumps(
                {
                    "manifest": str(result.manifest_path),
                    "gifs": [str(path) for path in result.gif_paths],
                    "generated_frames": result.generated_frames,
                    "reused_frames": result.reused_frames,
                }
            ),
            flush=True,
        )
        return 0
    except Exception as error:
        print(f"Animation transfer failed: {error}", flush=True)
        return 1
