"""
SPDX-License-Identifier: GPL-3.0-only
Copyright © 2025 Keystone Intelligence LLC
Licensed under GPL v3 (see LICENSE file for details)
"""

from abc import ABC, abstractmethod
from enum import Enum
import os
import json
import base64
import mimetypes
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field
from dataclasses import dataclass
import openai
from PIL import Image
from io import BytesIO
import google.genai as genai

from config import SETTINGS_FILE_NAME

DEFAULT_OPENAI_TEXT_MODEL = "gpt-4o-mini"
DEFAULT_OPENAI_IMAGE_MODEL = "gpt-image-1"
DEFAULT_GOOGLE_TEXT_MODEL = "gemini-2.0-flash"
DEFAULT_GOOGLE_IMAGE_MODEL = "gemini-2.0-flash-preview-image-generation"


# ---------------------------
# Domain-specific Data Models
# ---------------------------
class GameDescriptionOutput(BaseModel):
    """Structure for the generated game description."""
    description: str

class GameKeywordsOutput(BaseModel):
    """Structure for the extracted game keywords."""
    keywords: str = Field(
        description="A list of 5-10 relevant keywords summarizing a video game description, useful for searching or tagging game assets. Keywords cover themes, genre, art style, key elements, and mood."
    )

# ---------------------------
# Constant Templates & Context
# ---------------------------
GAME_ASSET_CONTEXT = """
You are an AI assistant specialized in helping game developers conceptualize video games and generate ideas for sprites and 2D game assets. Your responses should be concise and focused on visual descriptions, mood, style, and elements relevant to 2D game art creation. Emphasize sprite design, pixel art, and other aspects unique to 2D games.
"""

GENERATE_DESCRIPTION_PROMPT_TEMPLATE = """
{context}

Generate a compelling but short maximum 3 sentence description for a video game concept.
{input_guidance}

The description should be detailed enough to inspire visual ideas for the game assets such as sprite animations, pixel art characters, 2D environments, props, and effects.
Output the description according to the required structured format.
"""

GENERATE_KEYWORDS_PROMPT_TEMPLATE = """
{context}

Analyze the following video game description and extract a list of the most relevant keywords (around 5-10).

Video Game Description:
"{project_description}"

Identify keywords covering the core themes, genre, art style, key visual elements (including sprite design, pixel art details, 2D backgrounds, and overall mood), and setting.
These keywords should be concise and useful for searching, tagging, or generating sprites and other 2D game assets.
Output the keywords as a list according to the required structured format.
"""

GENERATE_REFERENCE_IMAGE_PROMPT_TEMPLATE = """
{context}

Using the provided context about a video game concept, generate a new reference or style image. The generated image should align with the established style, themes, mood, and visual universe, yet capture a new conceptual perspective.
{project_description}
{keywords}
{camera}
"""

GENERATE_BASE_SPRITE_IMAGE_PROMPT_TEMPLATE = """
{context}

Project Description:
{project_description}

Keywords:
{keywords}

Based on the style of the provided context, generate a detailed base sprite image of '{sprite_description}' on a plain white background.
{camera}
"""

# New Prompt Templates for Sprite Sequence Generation
GENERATE_NEXT_SPRITE_IMAGE_PROMPT_TEMPLATE = """
{context}

Animation: {animation_name}

Based on the provided sprite image, generate the next sprite image for the animation sequence. Ensure continuity in visual style, movement, and thematic elements, including the plain white background.
{camera}
"""


GENERATE_SPRITE_BETWEEN_IMAGES_PROMPT_TEMPLATE = """
{context}

Given the two provided sprite images showing different frames of a {animation_name} animation 
generate a new intermediate frame that represents the midway pose between them.
Blend the characters motion smoothly, adjust the body orientation appropriately, 
and preserve the consistent 2D pixel art style, character proportions, and details such as the plain white background.
The goal is to create a visually correct "in-between" frame that fits naturally between these two sprites in an animation sequence.
{camera}
"""

GENERATE_SPRITE_ANIMATION_SUGGESTION_PROMPT_TEMPLATE = """
{context}

Project Description:
{project_description}

Keywords:
{keywords}

Given the sprite description: '{sprite_description}', and current animation names: {current_animation_names}.

Suggest an additional animation name that makes sense for this sprite and does not overlap any of its current animations.
Provide the output as a single animation name with no other text. Make any spaces underscores.
"""

class BaseInferenceInput(ABC):

    @property
    @abstractmethod
    def to_prompt(self) -> str:
        """Generate a prompt from this input object"""
        pass


@dataclass
class GenerateDescriptionInput(BaseInferenceInput):
    keywords: Optional[str]
    images: List[str]

    @property
    def to_prompt(self) -> str:
        input_guidance = (f"Base the description on the following keywords: '{self.keywords}'."
                          if self.keywords and self.keywords.strip()
                          else "Generate a description for an interesting video game concept (e.g., fantasy RPG, sci-fi exploration, cute puzzle game).")
        return GENERATE_DESCRIPTION_PROMPT_TEMPLATE.format(
            context=GAME_ASSET_CONTEXT,
            input_guidance=input_guidance
        )


@dataclass
class GenerateKeywordsInput(BaseInferenceInput):
    project_description: str
    images: List[str]

    @property
    def to_prompt(self) -> str:
        return GENERATE_KEYWORDS_PROMPT_TEMPLATE.format(
            context=GAME_ASSET_CONTEXT,
            project_description=self.project_description
        )


@dataclass
class GenerateReferenceImageInput(BaseInferenceInput):
    output_folder: str
    project_description: str
    keywords: str
    images: List[str]
    camera: Optional[str]

    @property
    def to_prompt(self) -> str:
        return GENERATE_REFERENCE_IMAGE_PROMPT_TEMPLATE.format(
            context=GAME_ASSET_CONTEXT,
            project_description=f"\nProject Description:\n{self.project_description}" if self.project_description else "",
            keywords=f"\nKeywords: {self.keywords}" if self.keywords else "",
            camera=f"\nCamera Perspective/Viewing Angle: {self.camera}" if self.camera and self.camera.strip().lower() not in {"none", "null"} else "",
        )


@dataclass
class GenerateBaseSpriteImageInput(BaseInferenceInput):
    output_folder: str
    sprite_description: str
    project_description: Optional[str]
    keywords: Optional[str]
    images: Optional[List[str]]
    camera: Optional[str]

    @property
    def to_prompt(self) -> str:
        return GENERATE_BASE_SPRITE_IMAGE_PROMPT_TEMPLATE.format(
            context=GAME_ASSET_CONTEXT,
            project_description=f"\nProject Description:\n{self.project_description}" if self.project_description else "",
            keywords=f"\nKeywords: {self.keywords}" if self.keywords else "",
            sprite_description=self.sprite_description,
            camera=f"\nCamera Perspective/Viewing Angle: {self.camera}" if self.camera and self.camera.strip().lower() not in {"none", "null"} else "",
        )


@dataclass
class GenerateNextSpriteImageInput(BaseInferenceInput):
    output_folder: str
    animation_name: str
    image: str
    camera: str

    @property
    def to_prompt(self) -> str:
        return GENERATE_NEXT_SPRITE_IMAGE_PROMPT_TEMPLATE.format(
            context=GAME_ASSET_CONTEXT,
            animation_name=self.animation_name,
            camera=f"\nCamera Perspective/Viewing Angle: {self.camera}" if self.camera and self.camera.strip().lower() not in {"none", "null"} else "",
        )


@dataclass
class GenerateSpriteBetweenImagesInput(BaseInferenceInput):
    output_folder: str
    animation_name: str
    images: List[str]
    camera: str

    @property
    def to_prompt(self) -> str:
        return GENERATE_SPRITE_BETWEEN_IMAGES_PROMPT_TEMPLATE.format(
            context=GAME_ASSET_CONTEXT,
            animation_name=self.animation_name,
            camera=f"\nCamera Perspective/Viewing Angle: {self.camera}" if self.camera and self.camera.strip().lower() not in {"none", "null"} else "",
        )


@dataclass
class GenerateSpriteAnimationSuggestion(BaseInferenceInput):
    output_folder: str
    animation_names: List[str]
    sprite_description: str
    project_description: Optional[str]
    keywords: Optional[str]

    @property
    def to_prompt(self) -> str:
        return GENERATE_SPRITE_ANIMATION_SUGGESTION_PROMPT_TEMPLATE.format(
            context=GAME_ASSET_CONTEXT,
            project_description=f"\nProject Description:\n{self.project_description}" if self.project_description else "",
            keywords=f"\nKeywords: {self.keywords}" if self.keywords else "",
            sprite_description=self.sprite_description,
            current_animation_names=json.dumps(self.animation_names)
        )


# ---------------------------
# Base AI Client Abstraction
# ---------------------------
class BaseAIClient(ABC):
    def __init__(self, text_model: str, image_model: str, api_key: Optional[str] = None):
        self.text_model = text_model
        self.image_model = image_model
        self.api_key = api_key

    @abstractmethod
    def generate_description(self, input: GenerateDescriptionInput) -> Optional[str]:
        """Generate a project description based on keywords and/or images."""
        pass

    @abstractmethod
    def generate_keywords(self, input: GenerateKeywordsInput) -> Optional[str]:
        """Generate keywords based on a project description and/or images."""
        pass

    @abstractmethod
    def generate_reference_image(self, input: GenerateReferenceImageInput) -> Optional[str]:
        """Generate a reference image based on project description and keywords."""
        pass

    @abstractmethod
    def generate_base_sprite_image(self, input: GenerateBaseSpriteImageInput) -> Optional[str]:
        """Generate a base sprite image based on provided project context and sprite description."""
        pass

    @abstractmethod
    def generate_next_sprite_image(self, input: GenerateNextSpriteImageInput) -> Optional[str]:
        """Generate the next sprite image based on a single provided sprite and an animation description."""
        pass

    @abstractmethod
    def generate_sprite_between_images(self, input: GenerateSpriteBetweenImagesInput) -> Optional[str]:
        """Generate the sprite image between two provided sprite images and an animation description."""
        pass

    @abstractmethod
    def generate_sprite_animation_suggestion(self, input: GenerateSpriteAnimationSuggestion) -> Optional[str]:
        """Generate a suggested animation name for this sprite."""
        pass

# ---------------------------
# OpenAI Client Implementation
# ---------------------------
class OpenAIClient(BaseAIClient):
    def __init__(self, text_model=DEFAULT_OPENAI_TEXT_MODEL, image_model=DEFAULT_OPENAI_IMAGE_MODEL, api_key = None):
        super().__init__(text_model, image_model, api_key)

    @staticmethod
    def _process_image(image_path: str) -> Optional[str]:
        """Helper to verify image file, deduce its MIME type and return a Base64-encoded data URL."""
        if not os.path.exists(image_path):
            print(f"Warning: File not found at '{image_path}'. Skipping.")
            return None
        mime_type, _ = mimetypes.guess_type(image_path)
        if not mime_type or not mime_type.startswith("image/"):
            print(f"Warning: Skipping '{os.path.basename(image_path)}'. Unsupported file type: {mime_type or 'unknown'}")
            return None
        try:
            with open(image_path, "rb") as img_file:
                base64_image = base64.b64encode(img_file.read()).decode("utf-8")
            return f"data:{mime_type};base64,{base64_image}"
        except Exception as e:
            print(f"Error processing image '{os.path.basename(image_path)}': {e}. Skipping.")
            return None

    @staticmethod
    def _build_user_content(prompt: str, images: List[str]) -> List[dict]:
        """Compose the user_content list by prepending image data if available."""
        user_content = [{"type": "input_text", "text": prompt}]
        for image_path in images:
            data_url = OpenAIClient._process_image(image_path)
            if data_url:
                user_content.insert(0, {
                    "type": "input_image",
                    "image_url": data_url
                })
                print(f"Successfully added image '{os.path.basename(image_path)}' to the request.")
        return user_content

    def generate_description(self, input: GenerateDescriptionInput) -> Optional[str]:
        # Prepare prompt with optional guidance.
        prompt = input.to_prompt + "\n{\"description\": RESPONSE_STR}"
        user_content = self._build_user_content(prompt, input.images)
        try:
            response = openai.responses.create(
                model=self.text_model,
                input=[{"role": "user", "content": user_content}],
            )
            parsed = GameDescriptionOutput.model_validate_json(response.output_text)
            return parsed.description
        except Exception as e:
            print(f"Error calling OpenAI for description: {e}")
            return None

    def generate_keywords(self, input: GenerateKeywordsInput) -> Optional[str]:
        prompt = input.to_prompt + "\n{\"keywords\": RESPONSE_STR_NOT_A_LIST}"
        user_content = self._build_user_content(prompt, input.images)
        try:
            response = openai.responses.create(
                model=self.text_model,
                input=[{"role": "user", "content": user_content}],
            )
            parsed = GameKeywordsOutput.model_validate_json(response.output_text)
            return parsed.keywords
        except Exception as e:
            print(f"Error calling OpenAI for keywords: {e}")
            return None

    def generate_reference_image(self, input: GenerateReferenceImageInput) -> Optional[str]:
        prompt = input.to_prompt
        # Ensure output folder exists
        os.makedirs(input.output_folder, exist_ok=True)

        try:
            # Call the new image‐generation endpoint
            result = openai.images.edit(
                model=self.image_model,
                prompt=prompt,
                image=[open(x, "rb") for x in input.images],
                n=1,
                size="1024x1024",
            )
            image_base64 = result.data[0].b64_json
            image_bytes = base64.b64decode(image_base64)

            timestamp = datetime.now().strftime('%Y_%m_%d_%H_%M_%S')
            img_fpath = os.path.join(input.output_folder, f'reference_{timestamp}.png')
            with open(img_fpath, "wb") as f:
                f.write(image_bytes)

            return img_fpath

        except Exception as e:
            print(f"Error generating reference image: {e}")
            return None

    def generate_base_sprite_image(self, input: GenerateBaseSpriteImageInput) -> Optional[str]:
        prompt = input.to_prompt
        os.makedirs(input.output_folder, exist_ok=True)

        try:
            result = openai.images.edit(
                model=self.image_model,
                prompt=prompt,
                image=[open(x, "rb") for x in input.images],
                n=1,
                size="1024x1024",
            )
            image_base64 = result.data[0].b64_json
            image_bytes = base64.b64decode(image_base64)

            timestamp = datetime.now().strftime('%Y_%m_%d_%H_%M_%S')
            img_fpath = os.path.join(input.output_folder, f'base_sprite_{timestamp}.png')
            with open(img_fpath, "wb") as f:
                f.write(image_bytes)

            return img_fpath

        except Exception as e:
            print(f"Error generating base sprite image: {e}")
            return None

    def generate_next_sprite_image(self, input: GenerateNextSpriteImageInput) -> Optional[str]:
        prompt = input.to_prompt
        os.makedirs(input.output_folder, exist_ok=True)

        try:
            # Read the source sprite
            result = openai.images.edit(
                model=self.image_model,
                image=[open(input.image, "rb")],
                prompt=prompt,
                n=1,
                size="1024x1024",
            )

            image_base64 = result.data[0].b64_json
            image_bytes = base64.b64decode(image_base64)

            timestamp = datetime.now().strftime('%Y_%m_%d_%H_%M_%S')
            safe_anim = "".join(c if c.isalnum() else "_" for c in input.animation_name[:20])
            img_fpath = os.path.join(input.output_folder, f'next_sprite_{safe_anim}_{timestamp}.png')
            with open(img_fpath, "wb") as out:
                out.write(image_bytes)

            return img_fpath

        except Exception as e:
            print(f"Error generating next sprite image: {e}")
            return None

    def generate_sprite_between_images(self, input: GenerateSpriteBetweenImagesInput) -> Optional[str]:
        prompt = input.to_prompt
        os.makedirs(input.output_folder, exist_ok=True)

        try:
            # Read binary files for editing
            result = openai.images.edit(
                model=self.image_model,
                image=[open(path, "rb") for path in input.images],
                prompt=prompt,
                n=1,
                size="1024x1024",
            )

            image_base64 = result.data[0].b64_json
            image_bytes = base64.b64decode(image_base64)

            timestamp = datetime.now().strftime('%Y_%m_%d_%H_%M_%S')
            safe_anim = "".join(c if c.isalnum() else "_" for c in input.animation_name[:20])
            img_fpath = os.path.join(input.output_folder, f'between_{safe_anim}_{timestamp}.png')
            with open(img_fpath, "wb") as f:
                f.write(image_bytes)

            return img_fpath

        except Exception as e:
            print(f"Error generating sprite between images: {e}")
            return None
    
    def generate_sprite_animation_suggestion(self, input: GenerateSpriteAnimationSuggestion) -> Optional[str]:
        prompt = input.to_prompt
        user_content = self._build_user_content(prompt, [])
        try:
            response = openai.responses.create(
                model=self.text_model,
                input=[{"role": "user", "content": user_content}],
            )
            suggestion = response.output_text.strip()
            return suggestion
        except Exception as e:
            print(f"Error calling OpenAI for sprite animation suggestion: {e}")
            return None

# ---------------------------
# GoogleAI Client Implementation
# ---------------------------
class GoogleAIClient(BaseAIClient):
    def __init__(self, api_key, text_model=DEFAULT_GOOGLE_TEXT_MODEL, image_model=DEFAULT_GOOGLE_IMAGE_MODEL):
        super().__init__(text_model, image_model, api_key)

    def generate_description(self, input: GenerateDescriptionInput) -> Optional[str]:
        prompt = input.to_prompt
        try:
            client = genai.Client(api_key=self.api_key)
            image_context = [Image.open(img) for img in input.images if os.path.exists(img)]
            response = client.models.generate_content(
                model=self.text_model,
                contents=image_context + [prompt],
                config={
                    'response_mime_type': 'application/json',
                    'response_schema': GameDescriptionOutput,
                },
            )
            return response.parsed.description
        except Exception as e:
            print(f"Error calling GoogleAI for description: {e}")
            return None

    def generate_keywords(self, input: GenerateKeywordsInput) -> Optional[str]:
        prompt = input.to_prompt
        try:
            client = genai.Client(api_key=self.api_key)
            image_context = [Image.open(img) for img in input.images if os.path.exists(img)]
            response = client.models.generate_content(
                model=self.text_model,
                contents=image_context + [prompt],
                config={
                    'response_mime_type': 'application/json',
                    'response_schema': GameKeywordsOutput,
                },
            )
            return response.parsed.keywords
        except Exception as e:
            print(f"Error calling GoogleAI for keywords: {e}")
            return None

    def generate_reference_image(self, input: GenerateReferenceImageInput) -> Optional[str]:
        prompt = input.to_prompt
        try:
            client = genai.Client(api_key=self.api_key)
            image_context = [Image.open(img) for img in input.images if os.path.exists(img)]
            response = client.models.generate_content(
                model=self.image_model,
                contents=image_context + [prompt],
                config=genai.types.GenerateContentConfig(response_modalities=['Text', 'Image'])
            )
            img_fpath = None
            for part in response.candidates[0].content.parts:
                if part.inline_data is not None:
                    timestamp = datetime.now().strftime('%Y_%m_%d_%H_%M_%S')
                    img_fpath = os.path.join(input.output_folder, f'image_{timestamp}.png')
                    image_obj = Image.open(BytesIO(part.inline_data.data))
                    image_obj.save(img_fpath)
            if not img_fpath:
                print("Image generation failed")
            return img_fpath
        except Exception as e:
            print(f"Error calling GoogleAI for reference image: {e}")
            return None

    def generate_base_sprite_image(self, input: GenerateBaseSpriteImageInput) -> Optional[str]:
        prompt = input.to_prompt
        try:
            client = genai.Client(api_key=self.api_key)
            image_context = []
            if input.images:
                for img in input.images:
                    if os.path.exists(img):
                        try:
                            image_context.append(Image.open(img))
                        except Exception as e:
                            print(f"Error opening reference image '{img}': {e}. Skipping.")
            print("Constructed Prompt for Google AI Base Sprite Image Generation:")
            print(prompt)
            response = client.models.generate_content(
                model=self.image_model,
                contents=image_context + [prompt],
                config=genai.types.GenerateContentConfig(response_modalities=['Text', 'Image'])
            )
            img_fpath = None
            for part in response.candidates[0].content.parts:
                if part.inline_data is not None and part.inline_data.mime_type.startswith('image/'):
                    timestamp = datetime.now().strftime('%Y_%m_%d_%H_%M_%S')
                    safe_desc = "".join(c if c.isalnum() else "_" for c in input.sprite_description[:20])
                    img_fpath = os.path.join(input.output_folder, f'sprite_{safe_desc}_{timestamp}.png')
                    os.makedirs(input.output_folder, exist_ok=True)
                    image_obj = Image.open(BytesIO(part.inline_data.data))
                    image_obj.save(img_fpath)
                    print(f"Base sprite image saved to: {img_fpath}")
                    break
            if not img_fpath:
                print("Google AI image generation failed or no image data received.")
            return img_fpath
        except Exception as e:
            print(f"Error calling GoogleAI for base sprite image generation: {e}")
            return None

    def generate_next_sprite_image(self, input: GenerateNextSpriteImageInput) -> Optional[str]:
        prompt = input.to_prompt
        try:
            client = genai.Client(api_key=self.api_key)
            image_context = []
            if os.path.exists(input.image):
                try:
                    image_context.append(Image.open(input.image))
                except Exception as e:
                    print(f"Error opening sprite image '{input.image}': {e}. Skipping.")
            response = client.models.generate_content(
                model=self.image_model,
                contents=image_context + [prompt],
                config=genai.types.GenerateContentConfig(response_modalities=['Text', 'Image'])
            )
            img_fpath = None
            for part in response.candidates[0].content.parts:
                if part.inline_data is not None and part.inline_data.mime_type.startswith('image/'):
                    timestamp = datetime.now().strftime('%Y_%m_%d_%H_%M_%S')
                    safe_anim = "".join(c if c.isalnum() else "_" for c in input.animation_name[:20])
                    img_fpath = os.path.join(input.output_folder, f'next_sprite_{safe_anim}_{timestamp}.png')
                    os.makedirs(input.output_folder, exist_ok=True)
                    image_obj = Image.open(BytesIO(part.inline_data.data))
                    image_obj.save(img_fpath)
                    print(f"Next sprite image saved to: {img_fpath}")
                    break
            if not img_fpath:
                print("Google AI image generation failed or no image data received for next sprite image.")
            return img_fpath
        except Exception as e:
            print(f"Error calling GoogleAI for next sprite image generation: {e}")
            return None

    def generate_sprite_between_images(self, input: GenerateSpriteBetweenImagesInput) -> Optional[str]:
        prompt = input.to_prompt
        try:
            client = genai.Client(api_key=self.api_key)
            image_context = []
            for img in input.images:
                if os.path.exists(img):
                    try:
                        image_context.append(Image.open(img))
                    except Exception as e:
                        print(f"Error opening sprite image '{img}': {e}. Skipping.")
            response = client.models.generate_content(
                model=self.image_model,
                contents=image_context + [prompt],
                config=genai.types.GenerateContentConfig(response_modalities=['Text', 'Image'])
            )
            img_fpath = None
            for part in response.candidates[0].content.parts:
                if part.inline_data is not None and part.inline_data.mime_type.startswith('image/'):
                    timestamp = datetime.now().strftime('%Y_%m_%d_%H_%M_%S')
                    safe_anim = "".join(c if c.isalnum() else "_" for c in input.animation_name[:20])
                    img_fpath = os.path.join(input.output_folder, f'between_sprite_{safe_anim}_{timestamp}.png')
                    os.makedirs(input.output_folder, exist_ok=True)
                    image_obj = Image.open(BytesIO(part.inline_data.data))
                    image_obj.save(img_fpath)
                    print(f"Sprite between images saved to: {img_fpath}")
                    break
            if not img_fpath:
                print("Google AI image generation failed or no image data received for sprite between images.")
            return img_fpath
        except Exception as e:
            print(f"Error calling GoogleAI for sprite between images generation: {e}")
            return None
    
    def generate_sprite_animation_suggestion(self, input: GenerateSpriteAnimationSuggestion) -> Optional[str]:
        prompt = input.to_prompt
        try:
            client = genai.Client(api_key=self.api_key)
            response = client.models.generate_content(
                model=self.text_model,
                contents=[prompt],
                config=genai.types.GenerateContentConfig(response_modalities=['Text'])
            )
            suggestion = None
            for part in response.candidates[0].content.parts:
                if getattr(part, 'text', None):
                    suggestion = part.text.strip()
                    break
            if not suggestion:
                print("Google AI sprite animation suggestion failed or no text received.")
            return suggestion
        except Exception as e:
            print(f"Error calling GoogleAI for sprite animation suggestion: {e}")
            return None

# ---------------------------
# Testing Client Implementation
# ---------------------------
class TestingClient(BaseAIClient):
    def __init__(self, api_key=None, text_model="", image_model=""):
        super().__init__(text_model, image_model, api_key)

    def generate_description(self, input: GenerateDescriptionInput) -> Optional[str]:
        return "Project description from TESTING (placeholder)"

    def generate_keywords(self, input: GenerateKeywordsInput) -> Optional[str]:
        return "testing_keyword1,testing_keyword2,testing_keyword3"

    def generate_reference_image(self, input: GenerateReferenceImageInput) -> Optional[str]:
        return "ImageGeneratedByTESTING"

    def generate_base_sprite_image(self, input: GenerateBaseSpriteImageInput) -> Optional[str]:
        print(f"Generating fake base sprite for: {input.sprite_description}")
        timestamp = datetime.now().strftime('%Y_%m_%d_%H_%M_%S')
        safe_desc = "".join(c if c.isalnum() else "_" for c in input.sprite_description[:20])
        dummy_path = os.path.join(input.output_folder, f'TEST_sprite_{safe_desc}_{timestamp}.png')
        print(f"Returning dummy path: {dummy_path}")
        return dummy_path

    def generate_next_sprite_image(self, input: GenerateNextSpriteImageInput) -> Optional[str]:
        print(f"Generating fake next sprite image for animation: {input.animation_name}")
        timestamp = datetime.now().strftime('%Y_%m_%d_%H_%M_%S')
        safe_anim = "".join(c if c.isalnum() else "_" for c in input.animation_name[:20])
        dummy_path = os.path.join(input.output_folder, f'TEST_next_sprite_{safe_anim}_{timestamp}.png')
        print(f"Returning dummy path: {dummy_path}")
        return dummy_path

    def generate_sprite_between_images(self, input: GenerateSpriteBetweenImagesInput) -> Optional[str]:
        print(f"Generating fake sprite between images for animation: {input.animation_name} with images {input.images}")
        timestamp = datetime.now().strftime('%Y_%m_%d_%H_%M_%S')
        safe_anim = "".join(c if c.isalnum() else "_" for c in input.animation_name[:20])
        dummy_path = os.path.join(input.output_folder, f'TEST_between_sprite_{safe_anim}_{timestamp}.png')
        print(f"Returning dummy path: {dummy_path}")
        return dummy_path
    
    def generate_sprite_animation_suggestion(self, input: GenerateSpriteAnimationSuggestion) -> Optional[str]:
        print(f"Generating fake sprite animation suggestion for sprite: {input.sprite_description} with existing animations: {input.animation_names}")
        # Return a dummy suggestion
        return "TEST_sprite_animation_suggestion"

# ---------------------------
# AI Model Enum and Exception
# ---------------------------
class AIModel(Enum):
    OPENAI = "OPENAI"
    GOOGLEAI = "GOOGLEAI"
    TESTING = "TESTING"

class MissingInputException(Exception):
    """Custom exception for missing required input."""
    pass


# ---------------------------
# Manager: Chooses the Correct Client
# ---------------------------
class AIModelManager:
    def __init__(self):
        with open(SETTINGS_FILE_NAME) as f:
            data = json.load(f)
        # Warn if keys are missing.
        if not data.get("OPENAI_API_KEY"):
            print("Warning: OPENAI_API_KEY not set in settings")
        if not data.get("GOOGLE_AI_STUDIO_API_KEY"):
            print("Warning: GOOGLE_AI_STUDIO_API_KEY not set in settings")
        openai.api_key = data.get("OPENAI_API_KEY")
        self.google_api_key = data.get("GOOGLE_AI_STUDIO_API_KEY")
        self.config_data = data

    @staticmethod
    def get_active_vendor() -> AIModel:
        with open(SETTINGS_FILE_NAME) as f:
            data = json.load(f)
        requested = data.get("Selected Inference Provider")
        for model in AIModel:
            if model.value == requested:
                return model
        raise ValueError(f"AI Model {requested} not supported")

    def get_client(self) -> BaseAIClient:
        vendor = self.get_active_vendor()
        if vendor == AIModel.OPENAI:
            return OpenAIClient()
        elif vendor == AIModel.GOOGLEAI:
            return GoogleAIClient(api_key=self.google_api_key)
        elif vendor == AIModel.TESTING:
            return TestingClient()
        else:
            raise ValueError("Unrecognized AI model.")

    def generate_project_description(self, input: GenerateDescriptionInput) -> Optional[str]:
        client = self.get_client()
        return client.generate_description(input=input)

    def generate_keywords(self, input: GenerateKeywordsInput) -> Optional[str]:
        client = self.get_client()
        return client.generate_keywords(input=input)

    def generate_reference_image(self, input: GenerateReferenceImageInput) -> Optional[str]:
        if not input.project_description and not input.keywords:
            raise MissingInputException("Provide at least a project description or keywords.")
        client = self.get_client()
        return client.generate_reference_image(input=input)

    def generate_base_sprite_image(self, input: GenerateBaseSpriteImageInput) -> Optional[str]:
        if not input.project_description and not input.keywords:
            raise MissingInputException("Provide at least a project description or keywords.")
        client = self.get_client()
        return client.generate_base_sprite_image(input=input)

    def generate_next_sprite_image(self, input: GenerateNextSpriteImageInput) -> Optional[str]:
        client = self.get_client()
        return client.generate_next_sprite_image(input=input)

    def generate_sprite_between_images(self, input: GenerateSpriteBetweenImagesInput) -> Optional[str]:
        client = self.get_client()
        return client.generate_sprite_between_images(input=input)

    def generate_sprite_animation_suggestion(self, input: GenerateSpriteAnimationSuggestion) -> Optional[str]:
        client = self.get_client()
        return client.generate_sprite_animation_suggestion(input=input)
