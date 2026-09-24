"""Resumable pose-by-pose local image transfer, independent of the editor UI."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import uuid
from typing import Any, cast

from filelock import FileLock, Timeout
import numpy as np
from PIL import Image
from modelmanager import LocalConfig, ManagerError, get_profile
from modelmanager.generation import generate_image
from modelmanager.types import check_cancel, emit

from spritesage.model_baker.animations import frame_times, inspect_animations
from spritesage.model_baker.cameras import resolve_view_set
from spritesage.model_baker.sheet import make_contact_sheet
from spritesage.model_baker.timing import animation_from_manifest
from spritesage.model_baker.vtk_baker import BakeConfig, bake
from spritesage.persistence import atomic_write
from spritesage.sprite_file import SpriteFile

RECIPE_VERSION = 2


@dataclass(frozen=True)
class TransferRequest:
    project_dir: Path
    model_path: Path
    reference_image: Path
    sprite_name: str
    description: str
    animations: tuple[str, ...]
    directions: tuple[str, ...] = ("right",)
    view_set: str = "front3"
    fps: float = 8.0
    max_frames: int = 8
    output_size: int = 128
    generation_size: int = 512
    zoom: float = 1.0
    clean_background: bool = True


@dataclass(frozen=True)
class TransferResult:
    sprite: SpriteFile
    output_dir: Path
    manifest_path: Path
    sheet_paths: tuple[Path, ...]
    gif_paths: tuple[Path, ...]
    generated_frames: int
    reused_frames: int


def safe_name(value: str) -> str:
    return "".join(c if c.isalnum() or c in "_-" else "_" for c in value).strip("_") or "sprite"


def validate_request(request: TransferRequest) -> int:
    if not request.sprite_name.strip() or not request.description.strip():
        raise ValueError("Give the character a name and description.")
    if not request.project_dir.is_dir():
        raise ValueError("Save the project before generating an animation.")
    if not request.model_path.is_file() or request.model_path.suffix.lower() != ".glb":
        raise ValueError("Choose an available animated GLB template.")
    with Image.open(request.reference_image) as image:
        image.verify()
    if not math.isfinite(request.fps) or not 1 <= request.fps <= 30:
        raise ValueError("Sampling rate must be between 1 and 30 FPS.")
    if not 2 <= request.max_frames <= 120:
        raise ValueError("Choose between 2 and 120 frames per animation.")
    if not 32 <= request.output_size <= 1024 or request.generation_size not in (512, 768, 1024):
        raise ValueError("Choose a supported frame size.")
    if not math.isfinite(request.zoom) or not 0.25 <= request.zoom <= 2:
        raise ValueError("Camera zoom must be between 0.25 and 2.")
    views = {view.name for view in resolve_view_set(request.view_set)}
    if not request.directions or not set(request.directions).issubset(views):
        raise ValueError("Choose at least one available direction.")
    clips = {clip.name: clip for clip in inspect_animations(request.model_path)}
    if not request.animations or not set(request.animations).issubset(clips):
        raise ValueError("Choose at least one animation from this template.")
    if len(set(request.animations)) != len(request.animations) or len(
        set(request.directions)
    ) != len(request.directions):
        raise ValueError("Animations and directions must not repeat.")
    slugs = [safe_name(name) for name in request.animations]
    if len(set(slugs)) != len(slugs):
        raise ValueError(
            "These animation names produce duplicate filenames; rename them in the source model."
        )
    return sum(
        len(frame_times(clips[name].duration, request.fps, request.max_frames))
        for name in request.animations
    ) * len(request.directions)


def transfer_prompt(
    description: str, animation: str, direction: str, index: int, count: int
) -> str:
    return (
        "Replace the source character in <image1> with the character from <image2>. "
        "<image1> is the canvas: preserve its exact facing direction, body pose, limb positions, "
        "stride, arm swing, framing and white background. "
        "<image2> supplies ONLY the new character's identity, face, skin, hair, body proportions, "
        "outfit, equipment, colors and drawing style. "
        f"The new character is {description}. "
        "The output is the character from <image2> in the exact pose of <image1>. "
        "Match the arms, hands, legs and feet of <image1>, including which limbs overlap. "
        "Preserve <image1>'s character height, position and ground contact. "
        "One character, full body, on pure white. No shadow, no text, no other people."
    )


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value):
    atomic_write(path, json.dumps(value, indent=2).encode("utf-8"))


def read_transfer_request(path: Path):
    """One saved request format for the UI, command line and interrupted jobs."""
    data = json.loads(path.read_text(encoding="utf-8"))
    values = dict(data["request"])
    for name in ("project_dir", "model_path", "reference_image"):
        values[name] = Path(values[name])
    for name in ("animations", "directions"):
        if name in values:
            values[name] = tuple(values[name])
    return TransferRequest(**values), data.get("config")


def _white_canvas(path: Path, size: int) -> Image.Image:
    with Image.open(path) as source:
        image = source.convert("RGBA")
    image.thumbnail((size, size), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (size, size), cast(Any, "white"))
    canvas.alpha_composite(image, ((size - image.width) // 2, (size - image.height) // 2))
    return canvas.convert("RGB")


def remove_white_background(image: Image.Image) -> Image.Image:
    """Remove border-connected neutral white; keep enclosed eyes, tusks and highlights."""
    import cv2

    rgba = np.array(image.convert("RGBA"))
    rgb = rgba[:, :, :3].astype(np.int16)
    white = ((rgb.min(axis=2) >= 232) & (rgb.max(axis=2) - rgb.min(axis=2) <= 18)) | (
        rgba[:, :, 3] == 0
    )
    _, labels = cv2.connectedComponents(white.astype(np.uint8), connectivity=4)
    border = np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))
    border = border[border != 0]
    rgba[np.isin(labels, border), 3] = 0
    return Image.fromarray(rgba, "RGBA")


def prepare_frame(raw: Path, pose: Path, request: TransferRequest) -> Image.Image:
    with Image.open(raw) as image:
        frame = image.convert("RGBA").resize(
            (request.generation_size,) * 2, Image.Resampling.LANCZOS
        )
    if request.clean_background:
        frame = remove_white_background(frame)
        bounds = frame.getchannel("A").getbbox()
        with Image.open(pose) as source:
            target = source.convert("RGBA").getchannel("A").getbbox()
        if bounds is None or target is None:
            raise ManagerError("A generated frame was empty. Retry this animation.")
        # Normalize overall height and feet to the source pose without warping limb proportions.
        cropped = frame.crop(bounds)
        height = target[3] - target[1]
        width = max(1, round(cropped.width * height / cropped.height))
        cropped = cropped.resize((width, height), Image.Resampling.LANCZOS)
        frame = Image.new("RGBA", frame.size)
        x = round((target[0] + target[2] - width) / 2)
        if x < 0 or x + width > frame.width:
            raise ManagerError(
                "A generated frame extends beyond the canvas. Reduce camera zoom and retry."
            )
        frame.alpha_composite(cropped, (x, target[1]))
    return frame.resize((request.output_size,) * 2, Image.Resampling.NEAREST)


def write_gif(paths: list[Path], destination: Path, durations: list[float], loop: bool):
    """Shared palette and cumulative rounding preserve colors and GIF's 10 ms timing."""
    images = []
    for path in paths:
        with Image.open(path) as image:
            canvas = Image.new("RGBA", image.size, cast(Any, "white"))
            canvas.alpha_composite(image.convert("RGBA"))
            scale = max(1, 512 // image.width)
            images.append(
                canvas.convert("RGB").resize(
                    (image.width * scale, image.height * scale), Image.Resampling.NEAREST
                )
            )
    swatch = Image.new("RGB", (images[0].width * len(images), images[0].height))
    for i, image in enumerate(images):
        swatch.paste(image, (i * image.width, 0))
    palette = swatch.quantize(colors=255)
    quantized = [image.quantize(palette=palette, dither=Image.Dither.NONE) for image in images]
    elapsed = 0.0
    previous = 0
    delays = []
    for duration in durations:
        elapsed += duration * 100
        rounded = max(previous + 1, round(elapsed))
        delays.append((rounded - previous) * 10)
        previous = rounded
    options = {"loop": 0} if loop else {}
    destination.parent.mkdir(parents=True, exist_ok=True)
    quantized[0].save(
        destination,
        save_all=True,
        append_images=quantized[1:],
        duration=delays,
        disposal=2,
        optimize=False,
        **options,
    )


def run_transfer(
    request: TransferRequest, config: LocalConfig, progress=None, cancel=None
) -> TransferResult:
    total = validate_request(request)
    profile = get_profile(config.model_id)
    if "image_edit" not in profile.capabilities or profile.max_references < 2:
        raise ManagerError(
            "Choose a local image model that supports at least two reference images."
        )
    config.validate()
    check_cancel(cancel)
    recipe = {
        "version": RECIPE_VERSION,
        "model_sha256": _sha(request.model_path),
        "reference_sha256": _sha(request.reference_image),
        "name": request.sprite_name,
        "description": request.description,
        "animations": request.animations,
        "directions": request.directions,
        "view_set": request.view_set,
        "fps": request.fps,
        "max_frames": request.max_frames,
        "output_size": request.output_size,
        "generation_size": request.generation_size,
        "zoom": request.zoom,
        "clean_background": request.clean_background,
        "image_model": profile.id,
        "revision": profile.revision,
        "steps": config.steps,
        "seed": config.seed,
    }
    fingerprint = hashlib.sha256(json.dumps(recipe, sort_keys=True).encode()).hexdigest()
    root = (
        request.project_dir.resolve()
        / "sprites"
        / f"{safe_name(request.sprite_name)}_transfer_{fingerprint[:12]}"
    )
    if not root.resolve().is_relative_to(request.project_dir.resolve()):
        raise ValueError("Transfer output must stay inside the project.")
    root.mkdir(parents=True, exist_ok=True)
    try:
        with FileLock(str(root / ".transfer.lock"), timeout=0):
            return _run(request, config, root, recipe, fingerprint, total, progress, cancel)
    except Timeout as error:
        raise ManagerError("This animation job is already running.") from error


def merge_animations(sprite: SpriteFile, result: TransferResult):
    """Add without overwriting animations; preserve the destination canvas and settings."""
    from PIL import ImageOps

    additions = {}
    for name, original in result.sprite.animations.items():
        candidate, suffix = name, 2
        while candidate in sprite.animations or candidate in additions:
            candidate = f"{name}_{suffix}"
            suffix += 1
        animation = deepcopy(original)
        animation.name = candidate
        if (sprite.width, sprite.height) != (result.sprite.width, result.sprite.height):
            resized = []
            for index, frame in enumerate(animation.frames):
                with Image.open(frame) as source:
                    image = ImageOps.contain(
                        source.convert("RGBA"),
                        (sprite.width, sprite.height),
                        Image.Resampling.NEAREST,
                    )
                canvas = Image.new("RGBA", (sprite.width, sprite.height))
                canvas.alpha_composite(
                    image, ((sprite.width - image.width) // 2, (sprite.height - image.height) // 2)
                )
                path = (
                    result.output_dir
                    / "resized"
                    / f"{sprite.width}x{sprite.height}"
                    / name
                    / f"{index:03d}.png"
                )
                path.parent.mkdir(parents=True, exist_ok=True)
                canvas.save(path)
                resized.append(str(path))
            animation.frames = resized
        additions[candidate] = animation
    sprite.animations.update(additions)


def _run(request, config, root, recipe, fingerprint, total, progress, cancel):
    state_path = root / "progress.json"
    state = (
        json.loads(state_path.read_text())
        if state_path.exists()
        else {"fingerprint": fingerprint, "frames": {}}
    )
    if state.get("fingerprint") != fingerprint:
        raise ManagerError(
            "The saved job does not match this request. Choose a different sprite name."
        )
    _write_json(root / "recipe.json", recipe)
    values = asdict(request)
    for name in ("project_dir", "model_path", "reference_image"):
        values[name] = str(values[name].resolve())
    _write_json(root / "request.json", {"request": values, "config": config.to_dict()})
    state["complete"] = False
    _write_json(state_path, state)
    poses_dir = root / "poses"
    pose_manifest = poses_dir / "manifest.json"
    # Re-render cheap deterministic pose guides on resume; expensive verified AI frames are reused.
    emit(progress, "Rendering motion template…", 0, total)
    bake(
        BakeConfig(
            model_path=request.model_path.resolve(),
            output_dir=poses_dir,
            sprite_name=request.sprite_name,
            view_set=request.view_set,
            fps=request.fps,
            size=request.generation_size,
            zoom=request.zoom,
            selected_animations=list(request.animations),
            selected_views=request.directions,
            max_frames=request.max_frames,
            lock_camera=True,
        ),
        check_cancel=lambda: check_cancel(cancel),
    )
    manifest = json.loads(pose_manifest.read_text())
    inputs = root / "inputs"
    inputs.mkdir(exist_ok=True)
    identity = inputs / "character.png"
    _white_canvas(request.reference_image, request.generation_size).save(identity)
    effective = replace(
        config,
        width=request.generation_size,
        height=request.generation_size,
        seed=config.seed if config.seed >= 0 else int(fingerprint[:15], 16),
        enhance_prompts=False,
    )
    # Pose instructions are deliberately fixed, not rewritten independently per frame.
    completed = generated = reused = 0
    animations = {}
    sheets, gifs, records = [], [], []
    for record in manifest["animations"]:
        views = {}
        slug = safe_name(record["name"])
        for direction, poses in record["views"].items():
            frames = []
            for index, pose_value in enumerate(poses):
                check_cancel(cancel)
                pose = Path(pose_value)
                key = f"frames/{slug}/{direction}/frame_{index:03d}.png"
                target = root / key
                raw = root / "raw" / slug / direction / f"frame_{index:03d}.png"
                target.parent.mkdir(parents=True, exist_ok=True)
                raw.parent.mkdir(parents=True, exist_ok=True)
                label = f"{record['name']} · {direction.replace('_', ' ')} · frame {index + 1}/{len(poses)}"
                saved = state["frames"].get(key, {})
                if target.is_file() and _sha(target) == saved.get("sha256"):
                    reused += 1
                else:
                    if not raw.is_file() or _sha(raw) != saved.get("raw_sha256"):
                        pose_input = inputs / "pose.png"
                        _white_canvas(pose, request.generation_size).save(pose_input)

                        def report(update, label=label, completed=completed):
                            emit(progress, f"{label} — {update.message}", completed, total)

                        emit(
                            progress,
                            f"{label} — generating with local {get_profile(config.model_id).name}",
                            completed,
                            total,
                        )
                        output = generate_image(
                            effective,
                            transfer_prompt(
                                request.description, record["name"], direction, index, len(poses)
                            ),
                            [str(pose_input), str(identity)],
                            raw.parent,
                            report,
                            cancel,
                        )
                        atomic_write(raw, Path(output).read_bytes())
                        saved = {"raw_sha256": _sha(raw)}
                        state["frames"][key] = saved
                        _write_json(state_path, state)
                        generated += 1
                    check_cancel(cancel)
                    prepared = prepare_frame(raw, pose, request)
                    prepared.save(target)
                    saved["sha256"] = _sha(target)
                    state["frames"][key] = saved
                    _write_json(state_path, state)
                frames.append(target)
                completed += 1
                emit(progress, f"{label} — saved · {completed}/{total} frames", completed, total)
            name = f"{slug}_{direction}"
            animation = animation_from_manifest(
                record, name=name, frames=[str(p) for p in frames], default_fps=request.fps
            )
            animations[name] = animation
            gif = root / "gifs" / f"{name}.gif"
            write_gif(
                frames,
                gif,
                [animation.frame_seconds(i) for i in range(len(frames))],
                animation.loop,
            )
            gifs.append(gif)
            views[direction] = frames
        sheet = root / "sheets" / f"{slug}.png"
        make_contact_sheet(views, sheet, request.output_size)
        sheets.append(sheet)
        records.append(
            {
                **record,
                "views": {
                    v: [p.relative_to(root).as_posix() for p in ps] for v, ps in views.items()
                },
                "sheet": sheet.relative_to(root).as_posix(),
            }
        )
    check_cancel(cancel)
    base = root / "character.png"
    with Image.open(identity) as image:
        base_image = (
            remove_white_background(image) if request.clean_background else image.convert("RGBA")
        )
        base_image.resize((request.output_size,) * 2, Image.Resampling.NEAREST).save(base)
    output_manifest = root / "manifest.json"
    _write_json(
        output_manifest,
        {
            "recipe_version": RECIPE_VERSION,
            "size": request.output_size,
            "fps": request.fps,
            "base_image": "character.png",
            "animations": records,
            "gifs": [p.relative_to(root).as_posix() for p in gifs],
        },
    )
    state["complete"] = True
    _write_json(state_path, state)
    sprite = SpriteFile(
        str(uuid.uuid4()),
        request.sprite_name,
        request.description,
        request.output_size,
        request.output_size,
        str(base),
        animations,
        include_base_image_in_animations=False,
    )
    emit(progress, "Animation ready", total, total)
    return TransferResult(
        sprite, root, output_manifest, tuple(sheets), tuple(gifs), generated, reused
    )
