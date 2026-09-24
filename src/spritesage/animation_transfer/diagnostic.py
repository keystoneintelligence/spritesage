"""Exercise the production transfer pipeline from source or a packaged application."""

import json
from pathlib import Path

from modelmanager import LocalConfig

from spritesage.settings import SettingsStore
from .service import read_transfer_request, run_transfer


def test_animation_transfer(request_path):
    try:
        request, stored_config = read_transfer_request(Path(request_path))
        config = LocalConfig.from_dict(
            stored_config
            if stored_config is not None
            else SettingsStore().load().get("LOCAL_GENERATION")
        )
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
