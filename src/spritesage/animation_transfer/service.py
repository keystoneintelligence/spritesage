"""Resumable pose-by-pose image transfer, independent of the editor UI."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from copy import deepcopy
import hashlib
import json
import math
import re
from pathlib import Path
import uuid
from typing import Any, cast

from filelock import FileLock, Timeout
import numpy as np
from PIL import Image
from modelmanager import LocalConfig, ManagerError, get_profile
from modelmanager.enhancer import EnhancementError, PromptEngine
from modelmanager.generation import generate_image
from modelmanager.installation import enhancement_status
from modelmanager.types import check_cancel, emit

from spritesage.google_images import GoogleImageConfig, generate_google_image
from spritesage.model_baker.animations import frame_times, inspect_animations
from spritesage.model_baker.cameras import resolve_view_set
from spritesage.model_baker.sheet import make_contact_sheet
from spritesage.model_baker.timing import animation_from_manifest
from spritesage.model_baker.vtk_baker import BakeConfig, bake
from spritesage.openai_images import OpenAIImageConfig, generate_openai_image
from spritesage.persistence import atomic_write
from spritesage.sprite_file import SpriteFile

from .pose_guidance import RigPoseGuide

RECIPE_VERSION = 2
TransferConfig = LocalConfig | OpenAIImageConfig | GoogleImageConfig


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
    pose_guided: bool = False


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


def cloud_transfer_prompt(description: str, facts: tuple[str, ...] = (), feedback: str = "") -> str:
    prompt = (
        "Edit the first image. It is the pose and camera guide: keep its facing direction, "
        "head angle, wrists, boots, limb overlaps, foot contact, scale, framing, and white background. "
        "Replace only the character's identity, costume, colors, and drawing style using the "
        "second image. The new character is: "
        f"{description}. Show one complete character in the first image's exact pose. "
        "Do not copy the second image's pose."
    )
    if facts:
        prompt += " Measured pose: " + " ".join(facts)
    if feedback.strip():
        prompt += " Correct this frame: " + feedback.strip()
    return prompt


def pose_guided_prompt(description: str) -> str:
    return (
        "Edit <image1> in place. Replace its character with the character from <image2>. "
        "Keep <image1> as the pose and camera canvas: preserve its on-screen facing, "
        "head angle, wrists, boots, foot contact, limb overlaps, scale and framing. "
        f"The new character is {description}. "
        "Use <image2> only for character identity, clothing, colors and art style. "
        "Output exactly one full-body character on a plain white square canvas."
    )


def _contradicts_boot_height(prompt: str, facts: tuple[str, ...]) -> bool:
    raised = next(
        (
            match.group(1)
            for fact in facts
            if (match := re.search(r"screen-(left|right) boot is higher", fact))
        ),
        None,
    )
    if raised is None:
        return False
    mentions = list(re.finditer(r"\bscreen[- ](left|right) boot\b", prompt.lower()))
    for position, mention in enumerate(mentions):
        end = mentions[position + 1].start() if position + 1 < len(mentions) else len(prompt)
        clause = prompt[mention.end() : min(end, mention.end() + 100)].lower()
        clause = re.split(r"[.;,]|\b(?:while|whereas)\b", clause, maxsplit=1)[0]
        if mention.group(1) == raised:
            if re.search(r"\b(planted|grounded|touching the ground|flat on the ground)\b", clause):
                return True
        elif re.search(r"\b(raised|lifted|airborne|off the ground)\b", clause):
            return True
    return False


def _frame_prompt(request, config, pose_input, identity, facts, progress, cancel, feedback=""):
    base = pose_guided_prompt(request.description)
    if feedback.strip():
        base += f" Correct this frame: {feedback.strip()}"
    constraints = (
        "Describe the visible pose in screen coordinates, including which boot is raised "
        "and where both wrists and boots appear. Do not invent a wider stride or arm reach.",
        "The character identity and outfit come only from <image2>.",
        "Keep exactly one full-body character on the same white square canvas.",
        *facts,
    )
    try:
        rewritten = PromptEngine(config, progress, cancel).rewrite(
            base, [str(pose_input), str(identity)], constraints=constraints
        )
    except EnhancementError as error:
        emit(progress, f"Prompt helper failed; using rig-guided edit instructions: {error}")
        rewritten = base
    if _contradicts_boot_height(rewritten, facts):
        emit(progress, "Prompt helper contradicted the rig's boot height; using measured facts.")
        rewritten = base
    # The vision helper can misread a raised boot. Put measured facts last so
    # ambiguous prose cannot silently override the animated rig's positions.
    return rewritten + "\n" + " ".join(facts), rewritten != base


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value):
    atomic_write(path, json.dumps(value, indent=2).encode("utf-8"))


def read_transfer_request(path: Path):
    """One saved request format for the UI, command line and interrupted jobs."""
    data = json.loads(path.read_text(encoding="utf-8"))
    values = dict(data["request"])
    # Jobs saved before pose guidance keep their original recipe and resume path.
    values.setdefault("pose_guided", False)
    for name in ("project_dir", "model_path", "reference_image"):
        values[name] = Path(values[name])
    for name in ("animations", "directions"):
        if name in values:
            values[name] = tuple(values[name])
    return TransferRequest(**values), data.get("config")


def config_from_saved(data: dict | None, api_key: str | None = None) -> TransferConfig:
    """Restore a draft without ever reading a credential from its JSON file."""
    if isinstance(data, dict) and data.get("provider") == "OPENAI":
        if api_key is None:
            from spritesage.settings import SettingsStore

            api_key = SettingsStore().load().get("OPENAI_API_KEY", "")
        return OpenAIImageConfig.from_dict(data, api_key or "")
    if isinstance(data, dict) and data.get("provider") == "GOOGLEAI":
        if api_key is None:
            from spritesage.settings import SettingsStore

            api_key = SettingsStore().load().get("GOOGLE_AI_STUDIO_API_KEY", "")
        return GoogleImageConfig.from_dict(data, api_key or "")
    return LocalConfig.from_dict(data)


def config_from_settings(settings: dict) -> TransferConfig:
    """Use the same provider and image model selected for the rest of Sprite Sage."""
    provider = settings.get("Selected Inference Provider")
    if provider == "OPENAI":
        return OpenAIImageConfig.from_dict(
            {"model_id": settings.get("OPENAI_IMAGE_MODEL", ""), "quality": "medium"},
            settings.get("OPENAI_API_KEY", ""),
        )
    if provider == "GOOGLEAI":
        return GoogleImageConfig.from_dict(
            {"model_id": settings.get("GOOGLE_IMAGE_MODEL", "")},
            settings.get("GOOGLE_AI_STUDIO_API_KEY", ""),
        )
    if provider == "LOCAL":
        return LocalConfig.from_dict(settings.get("LOCAL_GENERATION"))
    raise ValueError("Select OpenAI, Google, or Local in Preferences to animate from a template.")


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
    request: TransferRequest, config: TransferConfig, progress=None, cancel=None
) -> TransferResult:
    total = validate_request(request)
    cloud = isinstance(config, (OpenAIImageConfig, GoogleImageConfig))
    if cloud:
        config.validate()
        if isinstance(config, OpenAIImageConfig) and request.generation_size != 1024:
            raise ValueError("OpenAI image transfer requires a 1024 × 1024 generation size.")
    else:
        profile = get_profile(config.model_id)
        if "image_edit" not in profile.capabilities or profile.max_references < 2:
            raise ManagerError(
                "Choose a local image model that supports at least two reference images."
            )
        config.validate()
        if request.pose_guided and (
            profile.enhancement is None or enhancement_status(config, profile) != "Ready"
        ):
            raise ManagerError(
                "Pose-guided transfer needs the local prompt tools. Open Manage local models "
                "and install or verify Prompt improvement for this image model."
            )
    check_cancel(cancel)
    recipe = {
        "version": 4 if cloud else (3 if request.pose_guided else RECIPE_VERSION),
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
    }
    if cloud:
        recipe.update(image_provider=config.to_dict()["provider"], image_model=config.model_id)
        if isinstance(config, OpenAIImageConfig):
            recipe["quality"] = config.quality
    else:
        recipe.update(
            image_model=profile.id,
            revision=profile.revision,
            steps=config.steps,
            seed=config.seed,
        )
    if request.pose_guided:
        recipe["pose_guided"] = True
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


def _generate_frame_bytes(config, prompt, references, output_dir, progress, cancel):
    if isinstance(config, OpenAIImageConfig):
        return generate_openai_image(config, prompt, references, progress, cancel)
    if isinstance(config, GoogleImageConfig):
        return generate_google_image(config, prompt, references, progress, cancel)
    output = generate_image(
        config, prompt, [str(path) for path in references], output_dir, progress, cancel
    )
    return Path(output).read_bytes()


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
    guide = None
    if request.pose_guided:
        try:
            guide = RigPoseGuide(
                request.model_path,
                manifest,
                request.view_set,
                request.generation_size,
                request.zoom,
            )
        except (ValueError, KeyError, IndexError, OSError) as error:
            emit(
                progress,
                f"Rig joints unavailable; review the rendered pose carefully: {error}",
            )
    inputs = root / "inputs"
    inputs.mkdir(exist_ok=True)
    identity = inputs / "character.png"
    _white_canvas(request.reference_image, request.generation_size).save(identity)
    cloud = isinstance(config, (OpenAIImageConfig, GoogleImageConfig))
    effective = (
        config
        if cloud
        else replace(
            config,
            width=request.generation_size,
            height=request.generation_size,
            seed=config.seed if config.seed >= 0 else int(fingerprint[:15], 16),
            enhance_prompts=False,
        )
    )
    # Legacy jobs keep fixed prompts. Experimental jobs use visual reasoning
    # constrained by animated rig facts when the template exposes useful joints.
    completed = generated = reused = 0
    previous_manifest = root / "manifest.json"
    rig_guidance_used = (
        bool(json.loads(previous_manifest.read_text()).get("rig_guided"))
        if previous_manifest.is_file()
        else False
    )
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
                            f"{label} — generating with "
                            + (
                                f"{config.to_dict()['provider']} {config.model_id}"
                                if cloud
                                else f"local {get_profile(config.model_id).name}"
                            ),
                            completed,
                            total,
                        )
                        facts = (
                            guide.constraints(record["name"], direction, index)
                            if guide is not None
                            else ()
                        )
                        rig_guidance_used = rig_guidance_used or bool(facts)
                        if cloud:
                            prompt = cloud_transfer_prompt(
                                request.description, facts if request.pose_guided else ()
                            )
                            helper_used = False
                        elif request.pose_guided:
                            prompt, helper_used = _frame_prompt(
                                request,
                                effective,
                                pose_input,
                                identity,
                                facts,
                                report,
                                cancel,
                            )
                        else:
                            prompt = transfer_prompt(
                                request.description, record["name"], direction, index, len(poses)
                            )
                            helper_used = False
                        image_bytes = _generate_frame_bytes(
                            effective,
                            prompt,
                            [pose_input, identity],
                            raw.parent,
                            report,
                            cancel,
                        )
                        atomic_write(raw, image_bytes)
                        saved = {
                            "raw_sha256": _sha(raw),
                            "prompt": prompt,
                            "prompt_helper_used": helper_used,
                        }
                        if not cloud:
                            saved["seed"] = cast(LocalConfig, effective).seed
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
            "recipe_version": recipe["version"],
            "pose_guided": request.pose_guided,
            "rig_guided": rig_guidance_used,
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


def _review_frame(result: TransferResult, animation: str, direction: str, index: int):
    root = result.output_dir.resolve()
    manifest = json.loads((root / "poses" / "manifest.json").read_text(encoding="utf-8"))
    record = next((item for item in manifest["animations"] if item["name"] == animation), None)
    if record is None or direction not in record["views"]:
        raise ValueError("Choose a frame from this animation draft.")
    poses = record["views"][direction]
    if not isinstance(index, int) or not 0 <= index < len(poses):
        raise ValueError("Choose a frame from this animation draft.")
    slug = safe_name(animation)
    key = f"frames/{slug}/{direction}/frame_{index:03d}.png"
    return (
        root,
        key,
        Path(poses[index]),
        root / key,
        root / "raw" / slug / direction / f"frame_{index:03d}.png",
    )


def frame_attempts(result: TransferResult, animation: str, direction: str, index: int):
    root, key, _, _, _ = _review_frame(result, animation, direction, index)
    state = json.loads((root / "progress.json").read_text(encoding="utf-8"))
    frame = state["frames"][key]
    return len(frame.get("attempts", [])) or 1, frame.get("selected_attempt", 0)


def _refresh_review_outputs(result: TransferResult, animation: str, direction: str):
    root = result.output_dir
    output = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    record = next(item for item in output["animations"] if item["name"] == animation)
    slug = safe_name(animation)
    name = f"{slug}_{direction}"
    frames = [root / path for path in record["views"][direction]]
    timing = result.sprite.animations[name]
    write_gif(
        frames,
        root / "gifs" / f"{name}.gif",
        [timing.frame_seconds(i) for i in range(len(frames))],
        timing.loop,
    )
    make_contact_sheet(
        {view: [root / path for path in paths] for view, paths in record["views"].items()},
        root / record["sheet"],
        output["size"],
    )


def retry_transfer_frame(
    result: TransferResult,
    animation: str,
    direction: str,
    index: int,
    feedback: str = "",
    progress=None,
    cancel=None,
) -> int:
    """Create a new candidate, preserving all prior versions and the current draft on failure."""
    root, key, pose, target, raw = _review_frame(result, animation, direction, index)
    if len(feedback) > 2000:
        raise ValueError("Keep retry notes under 2,000 characters.")
    with FileLock(str(root / ".transfer.lock"), timeout=0):
        state_path = root / "progress.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        saved = state["frames"][key]
        if not target.is_file() or _sha(target) != saved.get("sha256"):
            raise ManagerError(
                "This frame changed outside the draft. Reopen the saved job before retrying."
            )
        request, stored_config = read_transfer_request(root / "request.json")
        if isinstance(stored_config, dict) and stored_config.get("provider") in (
            "OPENAI",
            "GOOGLEAI",
        ):
            from spritesage.settings import SettingsStore

            config = config_from_settings(SettingsStore().load())
            if config.to_dict() != stored_config:
                raise ManagerError(
                    "This draft used a different image provider or model. Select its saved "
                    "provider and model in Preferences before retrying a frame."
                )
        else:
            config = config_from_saved(stored_config)
        cloud = isinstance(config, (OpenAIImageConfig, GoogleImageConfig))
        if not cloud:
            profile = get_profile(config.model_id)
            if request.pose_guided and (
                profile.enhancement is None or enhancement_status(config, profile) != "Ready"
            ):
                raise ManagerError(
                    "The local prompt tools are unavailable. Restore them in Manage local models."
                )
        candidate_dir = (
            root / "candidates" / safe_name(animation) / direction / f"frame_{index:03d}"
        )
        candidate_dir.mkdir(parents=True, exist_ok=True)
        attempts = list(saved.get("attempts", []))
        if not attempts:
            previous_raw = candidate_dir / "attempt_000_raw.png"
            previous_frame = candidate_dir / "attempt_000_frame.png"
            atomic_write(previous_raw, raw.read_bytes())
            atomic_write(previous_frame, target.read_bytes())
            attempts.append(
                {
                    "raw": previous_raw.relative_to(root).as_posix(),
                    "frame": previous_frame.relative_to(root).as_posix(),
                    "sha256": _sha(previous_frame),
                    "prompt": saved.get("prompt", ""),
                    "seed": saved.get("seed", None if cloud else config.seed),
                }
            )
        ordinal = len(attempts)
        seed = None if cloud else (int(attempts[0]["seed"]) + ordinal) % (2**63)
        effective = (
            config
            if cloud
            else replace(
                config,
                width=request.generation_size,
                height=request.generation_size,
                seed=seed,
                enhance_prompts=False,
            )
        )
        identity = root / "inputs" / "character.png"
        pose_input = candidate_dir / "pose.png"
        _white_canvas(pose, request.generation_size).save(pose_input)
        pose_manifest = json.loads((root / "poses" / "manifest.json").read_text())
        if cloud:
            try:
                guide = RigPoseGuide(
                    request.model_path,
                    pose_manifest,
                    request.view_set,
                    request.generation_size,
                    request.zoom,
                )
                facts = guide.constraints(animation, direction, index)
            except (ValueError, KeyError, IndexError, OSError):
                facts = ()
            prompt = cloud_transfer_prompt(
                request.description, facts if request.pose_guided else (), feedback
            )
            helper_used = False
        elif feedback.strip() and request.pose_guided:
            try:
                guide = RigPoseGuide(
                    request.model_path,
                    pose_manifest,
                    request.view_set,
                    request.generation_size,
                    request.zoom,
                )
                facts = guide.constraints(animation, direction, index)
            except (ValueError, KeyError, IndexError, OSError):
                facts = ()
            prompt, helper_used = _frame_prompt(
                request, effective, pose_input, identity, facts, progress, cancel, feedback
            )
        else:
            source_record = next(
                item for item in pose_manifest["animations"] if item["name"] == animation
            )
            prompt = saved.get("prompt") or transfer_prompt(
                request.description,
                animation,
                direction,
                index,
                len(source_record["views"][direction]),
            )
            if feedback.strip():
                prompt += f"\nCorrect this frame: {feedback.strip()}"
            helper_used = saved.get("prompt_helper_used", False)
        check_cancel(cancel)
        emit(progress, f"Retrying {animation} · {direction} · frame {index + 1}")
        image_bytes = _generate_frame_bytes(
            effective,
            prompt,
            [pose_input, identity],
            candidate_dir,
            progress,
            cancel,
        )
        candidate_raw = candidate_dir / f"attempt_{ordinal:03d}_raw.png"
        candidate_frame = candidate_dir / f"attempt_{ordinal:03d}_frame.png"
        atomic_write(candidate_raw, image_bytes)
        prepared = prepare_frame(candidate_raw, pose, request)
        prepared.save(candidate_frame)
        if not cloud:
            check_cancel(cancel)
        atomic_write(raw, candidate_raw.read_bytes())
        atomic_write(target, candidate_frame.read_bytes())
        attempts.append(
            {
                "raw": candidate_raw.relative_to(root).as_posix(),
                "frame": candidate_frame.relative_to(root).as_posix(),
                "sha256": _sha(target),
                "prompt": prompt,
                "seed": seed,
                "prompt_helper_used": helper_used,
            }
        )
        saved.update(
            raw_sha256=_sha(raw),
            sha256=_sha(target),
            prompt=prompt,
            prompt_helper_used=helper_used,
            seed=seed,
            attempts=attempts,
            selected_attempt=ordinal,
        )
        _write_json(state_path, state)
        _refresh_review_outputs(result, animation, direction)
        return ordinal


def select_frame_attempt(
    result: TransferResult, animation: str, direction: str, index: int, attempt: int
):
    """Restore any saved candidate without re-running the image model."""
    root, key, _, target, raw = _review_frame(result, animation, direction, index)
    with FileLock(str(root / ".transfer.lock"), timeout=0):
        state_path = root / "progress.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        saved = state["frames"][key]
        attempts = saved.get("attempts", [])
        if not isinstance(attempt, int) or not 0 <= attempt < len(attempts):
            raise ValueError("Choose an available frame version.")
        selected = attempts[attempt]
        candidate = root / selected["frame"]
        if not candidate.is_file() or _sha(candidate) != selected["sha256"]:
            raise ManagerError("This saved frame version is missing or changed.")
        atomic_write(target, candidate.read_bytes())
        atomic_write(raw, (root / selected["raw"]).read_bytes())
        saved.update(
            sha256=_sha(target),
            raw_sha256=_sha(raw),
            prompt=selected["prompt"],
            seed=selected["seed"],
            prompt_helper_used=selected.get("prompt_helper_used", False),
            selected_attempt=attempt,
        )
        _write_json(state_path, state)
        _refresh_review_outputs(result, animation, direction)


def _verify_transfer(result: TransferResult, state):
    if not state.get("complete"):
        raise ManagerError("Finish generating every frame before accepting this animation.")
    for key, saved in state["frames"].items():
        frame = (result.output_dir / key).resolve()
        if not frame.is_relative_to(result.output_dir.resolve()) or (
            not frame.is_file() or _sha(frame) != saved.get("sha256")
        ):
            raise ManagerError("A reviewed frame is missing or changed. Resume the draft first.")


def verify_transfer(result: TransferResult):
    state = json.loads((result.output_dir / "progress.json").read_text(encoding="utf-8"))
    _verify_transfer(result, state)


def accept_transfer(result: TransferResult):
    state_path = result.output_dir / "progress.json"
    with FileLock(str(result.output_dir / ".transfer.lock"), timeout=0):
        state = json.loads(state_path.read_text(encoding="utf-8"))
        _verify_transfer(result, state)
        state["accepted"] = True
        _write_json(state_path, state)
