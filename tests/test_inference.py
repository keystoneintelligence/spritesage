import os
import json
import base64
import tempfile
import pytest
import openai

from unittest.mock import patch, MagicMock

import inference
from io import BytesIO

openai.api_key = "test"

# Ensure module imports
def test_import_inference():
    assert inference is not None

def test_process_image_nonexistent(tmp_path, capsys):
    # Non-existent file returns None and prints warning
    path = tmp_path / 'noimg.png'
    result = inference.OpenAIClient._process_image(str(path))
    captured = capsys.readouterr()
    assert result is None
    assert "Warning: File not found" in captured.out

def test_process_image_unsupported(tmp_path, capsys):
    # Unsupported extension (.txt)
    file = tmp_path / 'file.txt'
    file.write_text('hello')
    result = inference.OpenAIClient._process_image(str(file))
    captured = capsys.readouterr()
    assert result is None
    assert "Unsupported file type" in captured.out

def test_process_image_valid(tmp_path):
    # Create a valid image file
    from PIL import Image
    img = Image.new('RGB', (2,2), color='red')
    file = tmp_path / 'test.png'
    img.save(str(file), format='PNG')
    data_url = inference.OpenAIClient._process_image(str(file))
    assert data_url.startswith('data:image/png;base64,')
    # Decode base64 part and check starts with PNG header bytes
    b64 = data_url.split(',',1)[1]
    raw = base64.b64decode(b64)
    assert raw[:8] == b'\x89PNG\r\n\x1a\n'

def test_build_user_content_no_images():
    prompt = 'hello'
    # Use the updated internal method for building user content
    content = inference.OpenAIClient._build_user_content(prompt, [])
    assert isinstance(content, list)
    # Expect the new input_text type
    assert content == [{'type':'input_text','text':prompt}]

def test_build_user_content_with_images(tmp_path, monkeypatch, capsys):
    # Stub process_image to return a dummy URL for valid, None for invalid
    img1 = tmp_path / 'a.png'
    img1.write_bytes(b'data')
    img2 = tmp_path / 'b.png'
    img2.write_bytes(b'data')
    called = []
    def fake_process(p):
        called.append(p)
        return f'data:image/png;base64,AAA' if 'a.png' in p else None
    monkeypatch.setattr(inference.OpenAIClient, '_process_image', fake_process)
    prompt = 'test'
    # Use the updated internal method for building user content
    content = inference.OpenAIClient._build_user_content(prompt, [str(img1), str(img2)])
    out = capsys.readouterr().out
    # Should print success for a.png only
    assert "Successfully added image 'a.png'" in out
    # content should have input_image first, then only one
    assert content[0]['type'] == 'input_image'
    assert 'image_url' in content[0]
    # Last element is the text prompt with input_text type
    assert content[-1] == {'type':'input_text','text':prompt}

def test_base_ai_client_abstract():
    # Cannot instantiate abstract class
    with pytest.raises(TypeError):
        inference.BaseAIClient()

def test_testing_client_outputs(tmp_path, capsys):
    tc = inference.TestingClient()
    # Description
    desc_input = inference.GenerateDescriptionInput(keywords=None, images=[])
    desc = tc.generate_description(desc_input)
    assert 'placeholder' in desc

    # Keywords
    kws_input = inference.GenerateKeywordsInput(project_description="desc", images=[])
    kws = tc.generate_keywords(kws_input)
    assert 'testing_keyword1' in kws

    # Reference image
    ref_input = inference.GenerateReferenceImageInput(
        output_folder=str(tmp_path),
        project_description="d",
        keywords="k",
        images=[],
        camera=None
    )
    ref = tc.generate_reference_image(ref_input)
    assert ref == 'ImageGeneratedByTESTING'

    # Base sprite image
    base_input = inference.GenerateBaseSpriteImageInput(
        output_folder=str(tmp_path),
        sprite_description="spr",
        project_description="pd",
        keywords="kw",
        images=[],
        camera=None
    )
    base = tc.generate_base_sprite_image(base_input)
    assert 'TEST_sprite_spr_' in base

    # Next sprite image
    next_input = inference.GenerateNextSpriteImageInput(
        output_folder=str(tmp_path),
        animation_name="anim",
        image="img",
        camera=None
    )
    nxt = tc.generate_next_sprite_image(next_input)
    assert 'TEST_next_sprite_anim_' in nxt

    # Between images
    btw_input = inference.GenerateSpriteBetweenImagesInput(
        output_folder=str(tmp_path),
        animation_name="anim",
        images=['i1','i2'],
        camera=None
    )
    btw = tc.generate_sprite_between_images(btw_input)
    assert 'TEST_between_sprite_anim_' in btw

    # Animation suggestion
    sug_input = inference.GenerateSpriteAnimationSuggestion(
        output_folder=str(tmp_path),
        animation_names=['a1'],
        sprite_description="spr",
        project_description=None,
        keywords=None
    )
    sug = tc.generate_sprite_animation_suggestion(sug_input)
    assert sug == 'TEST_sprite_animation_suggestion'

class DummyChoice:
    def __init__(self, content):
        class Msg: pass
        self.message = Msg()
        self.message.content = content

class DummyResponse:
    def __init__(self, content):
        self.choices = [DummyChoice(content)]
        # Simulate OpenAI response attribute for compatibility
        self.output_text = content

def test_openai_client_generate_description_success(monkeypatch):
    client = inference.OpenAIClient()
    # Stub responses
    data = {'description':'good'}
    monkeypatch.setattr(inference.openai.responses, 'create', lambda **kwargs: DummyResponse(json.dumps(data)))
    input = inference.GenerateDescriptionInput(
        keywords="kw",
        images=[]
    )
    out = client.generate_description(input)
    assert out == 'good'

def test_openai_client_generate_description_error(monkeypatch, capsys):
    client = inference.OpenAIClient()
    def bad(**kwargs): raise RuntimeError('fail')
    monkeypatch.setattr(inference.openai.responses, 'create', bad)
    input_obj = inference.GenerateDescriptionInput(
        keywords=None,
        images=[]
    )
    out = client.generate_description(input_obj)
    assert out is None
    assert 'Error calling OpenAI for description' in capsys.readouterr().out


def test_openai_client_generate_keywords_success(monkeypatch):
    client = inference.OpenAIClient()
    data = {'keywords':'k1,k2'}
    monkeypatch.setattr(inference.openai.responses, 'create', lambda **kwargs: DummyResponse(json.dumps(data)))
    input_obj = inference.GenerateKeywordsInput(
        project_description="desc",
        images=[]
    )
    out = client.generate_keywords(input_obj)
    assert out == 'k1,k2'


def test_openai_client_generate_keywords_error(monkeypatch, capsys):
    client = inference.OpenAIClient()
    monkeypatch.setattr(inference.openai.responses, 'create', lambda **kwargs: (_ for _ in ()).throw(ValueError('oops')))
    input_obj = inference.GenerateKeywordsInput(
        project_description="desc",
        images=[]
    )
    out = client.generate_keywords(input_obj)
    assert out is None
    assert 'Error calling OpenAI for keywords' in capsys.readouterr().out


def test_openai_client_image_methods(monkeypatch, capsys):
    # Set a dummy API key to prevent OpenAI client init error during monkeypatch setup
    monkeypatch.setenv("OPENAI_API_KEY", "test_key_xyz")
    # Now instantiate the client *after* the env var is set
    client = inference.OpenAIClient(api_key="test_key_xyz")

    # Mock the specific API call to raise an exception
    def raise_error(*args, **kwargs):
        # Simulate file opening if needed by the signature, although it won't be used
        if 'image' in kwargs and isinstance(kwargs['image'], list):
             for f in kwargs['image']:
                 # Check if it looks like a file object (BytesIO) and close it
                 if hasattr(f, 'read') and hasattr(f, 'close'):
                     f.close()
        raise Exception("Simulated API Error")

    # Patch Images.edit before invoking any method
    with patch('openai.resources.images.Images.edit', side_effect=raise_error) as mock_edit:

        method_names = [
            'generate_reference_image',
            'generate_base_sprite_image',
            'generate_next_sprite_image',
            'generate_sprite_between_images'
        ]

        for method_name in method_names:
            func = getattr(client, method_name)

            # Create two temporary PNG files to simulate inputs
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_img1, \
                 tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_img2:

                img_path1 = tmp_img1.name
                img_path2 = tmp_img2.name

                if method_name == 'generate_reference_image':
                    input_obj = inference.GenerateReferenceImageInput(
                        output_folder="out",
                        project_description="pd",
                        keywords="kw",
                        images=[img_path1],
                        camera=None
                    )
                elif method_name == 'generate_base_sprite_image':
                    input_obj = inference.GenerateBaseSpriteImageInput(
                        output_folder="out",
                        sprite_description="spr",
                        project_description="pd",
                        keywords="kw",
                        images=[img_path1],
                        camera=None
                    )
                elif method_name == 'generate_next_sprite_image':
                    input_obj = inference.GenerateNextSpriteImageInput(
                        output_folder="out",
                        animation_name="anim",
                        image=img_path1,
                        camera=None
                    )
                elif method_name == 'generate_sprite_between_images':
                    input_obj = inference.GenerateSpriteBetweenImagesInput(
                        output_folder="out",
                        animation_name="anim",
                        images=[img_path1, img_path2],
                        camera=None
                    )
                else:
                    continue  # should not happen

                ret = func(input_obj)
                assert ret is None, f"Method {method_name} did not return None"
                out = capsys.readouterr().out
                assert "Error generating" in out and "Simulated API Error" in out, \
                       f"Expected error message not found for {method_name}. Output: {out}"

            # Clean up temp files
            os.remove(img_path1)
            if method_name == 'generate_sprite_between_images':
                os.remove(img_path2)

        # Assert the mock was called
        assert mock_edit.call_count >= len(method_names)


def test_openai_client_animation_suggestion(monkeypatch):
    client = inference.OpenAIClient()
    # Success case
    monkeypatch.setattr(inference.openai.responses, 'create', lambda **kwargs: DummyResponse(' suggest '))
    input_obj = inference.GenerateSpriteAnimationSuggestion(
        output_folder="out",
        animation_names=['a'],
        sprite_description="spr",
        project_description=None,
        keywords=None
    )
    out = client.generate_sprite_animation_suggestion(input_obj)
    assert out == 'suggest'
    # Error case
    monkeypatch.setattr(inference.openai.responses, 'create', lambda **kwargs: (_ for _ in ()).throw(Exception('err')))
    input_obj2 = inference.GenerateSpriteAnimationSuggestion(
        output_folder="out",
        animation_names=[],
        sprite_description="spr",
        project_description=None,
        keywords=None
    )
    assert client.generate_sprite_animation_suggestion(input_obj2) is None


def test_ai_model_manager_and_missing_input(tmp_path, monkeypatch):
    # Create a fake settings file
    settings = {'OPENAI_API_KEY':'k1','GOOGLE_AI_STUDIO_API_KEY':'k2','Selected Inference Provider':'TESTING'}
    sfile = tmp_path / 'settings.json'
    sfile.write_text(json.dumps(settings))
    # Monkeypatch SETTINGS_FILE_NAME in inference module
    monkeypatch.setattr(inference, 'SETTINGS_FILE_NAME', str(sfile))
    mgr = inference.AIModelManager()
    # Active vendor
    assert inference.AIModelManager.get_active_vendor().name == 'TESTING'
    # get_client
    client = mgr.get_client()
    assert isinstance(client, inference.TestingClient)

    # generate_project_description delegates
    pd_input = inference.GenerateDescriptionInput(keywords="kw", images=[])
    pd = mgr.generate_project_description(pd_input)
    assert 'placeholder' in pd

    # MissingInputException for reference image
    ref_input_missing = inference.GenerateReferenceImageInput(
        output_folder="out",
        project_description="",
        keywords="",
        images=[],
        camera=None
    )
    with pytest.raises(inference.MissingInputException):
        mgr.generate_reference_image(ref_input_missing)

    # MissingInputException for base sprite image
    base_input_missing = inference.GenerateBaseSpriteImageInput(
        output_folder="out",
        sprite_description="spr",
        project_description=None,
        keywords=None,
        images=None,
        camera=None
    )
    with pytest.raises(inference.MissingInputException):
        mgr.generate_base_sprite_image(base_input_missing)

    # Next sprite should work (no missing‐input check)
    next_input = inference.GenerateNextSpriteImageInput(
        output_folder="out",
        animation_name="anim",
        image="img",
        camera=None
    )
    nxt = mgr.generate_next_sprite_image(next_input)
    assert 'TEST_next_sprite_anim_' in nxt

    # Between sprite
    between_input = inference.GenerateSpriteBetweenImagesInput(
        output_folder="out",
        animation_name="anim",
        images=['i1','i2'],
        camera=None
    )
    btw = mgr.generate_sprite_between_images(between_input)
    assert 'TEST_between_sprite_anim_' in btw

    # Animation suggestion
    suggestion_input = inference.GenerateSpriteAnimationSuggestion(
        output_folder="out",
        animation_names=['a1'],
        sprite_description="spr",
        project_description=None,
        keywords=None
    )
    sug = mgr.generate_sprite_animation_suggestion(suggestion_input)
    assert sug == 'TEST_sprite_animation_suggestion'
    
class DummyParsedDesc:
    def __init__(self, description=None, keywords=None):
        self.description = description
        self.keywords = keywords

class DummyGResponseText:
    def __init__(self, parsed):
        self.parsed = parsed

class DummyGClient:
    def __init__(self, parsed_response=None, parts=None, text_parts=None, fail_generate=False, fail_message="Simulated API error"):
        # parsed_response: DummyParsedDesc
        # parts: list of InlineData parts for image
        # text_parts: list of text parts for suggestion
        # fail_generate: flag to force generate_content to fail
        # fail_message: message for the exception when fail_generate is True
        self.models = self
        self._parsed = parsed_response
        self._parts = parts
        self._text_parts = text_parts
        self._fail_generate = fail_generate
        self._fail_message = fail_message

    def generate_content(self, **kwargs):
        if self._fail_generate:
            raise Exception(self._fail_message)

        if self._parsed is not None:
            return DummyGResponseText(self._parsed)

        # Simulate image generation or text response
        class InlineData:
            def __init__(self, data, mime_type):
                self.data = data
                self.mime_type = mime_type
        class Part:
            def __init__(self, inline_data=None, text=None):
                self.inline_data = inline_data
                self.text = text
        class Content:
            def __init__(self, parts):
                self.parts = parts
        class Candidate:
            def __init__(self, content):
                self.content = content
        class Resp:
            def __init__(self, candidates):
                self.candidates = candidates

        # Build parts
        response_parts = []
        if self._parts:
            for data, mt in self._parts:
                response_parts.append(Part(inline_data=InlineData(data, mt)))
        if self._text_parts:
            for txt in self._text_parts:
                response_parts.append(Part(inline_data=None, text=txt))

        # Handle case where no parts were provided (e.g., simulating generation failure downstream)
        if not response_parts:
             # Return a response with no usable parts if neither image nor text parts were defined
             return Resp([Candidate(Content([]))])

        return Resp([Candidate(Content(response_parts))])

@pytest.fixture(autouse=True)
def stub_genai_client(monkeypatch):
    # Provide a default stub client; tests will monkeypatch as needed
    monkeypatch.setattr(inference.genai, 'Client', lambda api_key=None: DummyGClient())

def make_png_bytes():
    from PIL import Image
    buf = BytesIO()
    img = Image.new('RGB', (2,2), color='blue')
    img.save(buf, format='PNG')
    return buf.getvalue()

def test_googleai_client_generate_description(monkeypatch):
    # Success
    parsed = DummyParsedDesc(description='gdesc')
    monkeypatch.setattr(inference.genai, 'Client', lambda api_key=None: DummyGClient(parsed_response=parsed))
    client = inference.GoogleAIClient(api_key='key')
    input = inference.GenerateDescriptionInput(
        keywords="kw",
        images=[]
    )
    out = client.generate_description(input)
    assert out == 'gdesc'
    # Error path
    def bad_client(api_key=None): raise RuntimeError('fail')
    monkeypatch.setattr(inference.genai, 'Client', bad_client)
    client = inference.GoogleAIClient(api_key='key')
    input = inference.GenerateDescriptionInput(
        keywords=None,
        images=[]
    )
    out2 = client.generate_description(input)
    assert out2 is None

def test_googleai_client_generate_keywords(monkeypatch):
    parsed = DummyParsedDesc(keywords='k1,k2')
    monkeypatch.setattr(inference.genai, 'Client', lambda api_key=None: DummyGClient(parsed_response=parsed))
    client = inference.GoogleAIClient(api_key='key')
    input_obj = inference.GenerateKeywordsInput(
        project_description="desc",
        images=[]
    )
    out = client.generate_keywords(input_obj)
    assert out == 'k1,k2'

    # Error path
    monkeypatch.setattr(inference.genai, 'Client', lambda api_key=None: (_ for _ in ()).throw(Exception('oops')))
    assert inference.GoogleAIClient(api_key='key').generate_keywords(
        inference.GenerateKeywordsInput(project_description="desc", images=[])
    ) is None


def test_googleai_client_image_generation_methods(tmp_path, monkeypatch):
    # Prepare dummy PNG data
    data = make_png_bytes()
    parts = [(data, 'image/png')]
    monkeypatch.setattr(inference.genai, 'Client', lambda api_key=None: DummyGClient(parts=parts))
    client = inference.GoogleAIClient(api_key='key')

    # Reference image
    ref_input = inference.GenerateReferenceImageInput(
        output_folder=str(tmp_path),
        project_description="pd",
        keywords="kw",
        images=[],
        camera=None
    )
    out_ref = client.generate_reference_image(ref_input)
    assert out_ref and os.path.exists(out_ref)

    # Base sprite image
    base_input = inference.GenerateBaseSpriteImageInput(
        output_folder=str(tmp_path),
        sprite_description="sprd",
        project_description="pd",
        keywords="kw",
        images=[],
        camera=None
    )
    out_base = client.generate_base_sprite_image(base_input)
    assert out_base and os.path.exists(out_base)

    # Next sprite image
    # First create a small valid PNG to pass as "input" in next‐sprite
    img_path = tmp_path / "input.png"
    img_path.write_bytes(make_png_bytes())
    next_input = inference.GenerateNextSpriteImageInput(
        output_folder=str(tmp_path),
        animation_name="anim",
        image=str(img_path),
        camera=None
    )
    out_next = client.generate_next_sprite_image(next_input)
    assert out_next and os.path.exists(out_next)

    # Between images
    img1 = tmp_path / "i1.png"
    img2 = tmp_path / "i2.png"
    img1.write_bytes(make_png_bytes())
    img2.write_bytes(make_png_bytes())
    between_input = inference.GenerateSpriteBetweenImagesInput(
        output_folder=str(tmp_path),
        animation_name="anim",
        images=[str(img1), str(img2)],
        camera=None
    )
    out_between = client.generate_sprite_between_images(between_input)
    assert out_between and os.path.exists(out_between)


def test_googleai_client_image_generation_failure(monkeypatch, capsys):
    # Client returns no parts
    monkeypatch.setattr(inference.genai, 'Client', lambda api_key=None: DummyGClient(parts=None))
    client = inference.GoogleAIClient(api_key='key')

    method_names = [
        'generate_reference_image',
        'generate_base_sprite_image',
        'generate_next_sprite_image',
        'generate_sprite_between_images'
    ]

    for method_name in method_names:
        func = getattr(client, method_name)
        if method_name == 'generate_reference_image':
            input_obj = inference.GenerateReferenceImageInput(
                output_folder=str(tempfile.mkdtemp()),
                project_description="pd",
                keywords="kw",
                images=[],
                camera=None
            )
        elif method_name == 'generate_base_sprite_image':
            input_obj = inference.GenerateBaseSpriteImageInput(
                output_folder=str(tempfile.mkdtemp()),
                sprite_description="spr",
                project_description="pd",
                keywords="kw",
                images=[],
                camera=None
            )
        elif method_name == 'generate_next_sprite_image':
            # Create a tiny valid PNG for next‐sprite
            tmpdir = str(tempfile.mkdtemp())
            img = os.path.join(tmpdir, "img.png")
            with open(img, "wb") as f:
                f.write(make_png_bytes())
            input_obj = inference.GenerateNextSpriteImageInput(
                output_folder=tmpdir,
                animation_name="anim",
                image=img,
                camera=None
            )
        else:  # generate_sprite_between_images
            tmpdir = str(tempfile.mkdtemp())
            img1 = os.path.join(tmpdir, "i1.png")
            img2 = os.path.join(tmpdir, "i2.png")
            with open(img1, "wb") as f:
                f.write(make_png_bytes())
            with open(img2, "wb") as f:
                f.write(make_png_bytes())
            input_obj = inference.GenerateSpriteBetweenImagesInput(
                output_folder=tmpdir,
                animation_name="anim",
                images=[img1, img2],
                camera=None
            )

        ret = func(input_obj)
        assert ret is None
        captured = capsys.readouterr().out
        assert 'failed' in captured.lower()

def test_googleai_client_animation_suggestion(monkeypatch):
    # Provide text part
    monkeypatch.setattr(inference.genai, 'Client', lambda api_key=None: DummyGClient(parts=None, text_parts=['suggested_anim']))
    client = inference.GoogleAIClient(api_key='key')
    input_obj = inference.GenerateSpriteAnimationSuggestion(
        output_folder=str(tempfile.mkdtemp()),
        animation_names=['a1'],
        sprite_description="spr",
        project_description=None,
        keywords=None
    )
    out = client.generate_sprite_animation_suggestion(input_obj)
    assert out == 'suggested_anim'

    # Error case: client initialization fails
    monkeypatch.setattr(inference.genai, 'Client', lambda api_key=None: (_ for _ in ()).throw(Exception('err')))
    input_obj2 = inference.GenerateSpriteAnimationSuggestion(
        output_folder="o",
        animation_names=["a"],
        sprite_description="spr",
        project_description=None,
        keywords=None
    )
    assert inference.GoogleAIClient(api_key='key').generate_sprite_animation_suggestion(input_obj2) is None

def test_process_image_exception_branch(tmp_path, monkeypatch, capsys):
    # Simulate an exception during file read to hit the except branch in process_image (lines 129-131)
    png = tmp_path / 'img.png'
    # create a dummy file so exists() is True and mime type is image/png
    png.write_bytes(b'data')
    # Monkeypatch open to raise an exception
    def bad_open(*args, **kwargs):
        raise RuntimeError("read error")
    monkeypatch.setattr('builtins.open', bad_open)
    # Process image should catch the exception, print error, and return None
    result = inference.OpenAIClient._process_image(str(png))
    captured = capsys.readouterr().out
    assert result is None
    assert f"Error processing image '{png.name}':" in captured


def test_base_ai_client_pass_methods():
    # Exercise BaseAIClient abstract methods (pass statements)
    class SubClient(inference.BaseAIClient):
        def __init__(self):
            super().__init__(inference.DEFAULT_OPENAI_TEXT_MODEL, inference.DEFAULT_OPENAI_IMAGE_MODEL)
        def generate_description(self, input: inference.GenerateDescriptionInput) -> None:
            return super().generate_description(input)
        def generate_keywords(self, input: inference.GenerateKeywordsInput) -> None:
            return super().generate_keywords(input)
        def generate_reference_image(self, input: inference.GenerateReferenceImageInput) -> None:
            return super().generate_reference_image(input)
        def generate_base_sprite_image(self, input: inference.GenerateBaseSpriteImageInput) -> None:
            return super().generate_base_sprite_image(input)
        def generate_next_sprite_image(self, input: inference.GenerateNextSpriteImageInput) -> None:
            return super().generate_next_sprite_image(input)
        def generate_sprite_between_images(self, input: inference.GenerateSpriteBetweenImagesInput) -> None:
            return super().generate_sprite_between_images(input)
        def generate_sprite_animation_suggestion(self, input: inference.GenerateSpriteAnimationSuggestion) -> None:
            return super().generate_sprite_animation_suggestion(input)

    client = SubClient()
    # All super() calls should return None (implicit) for the pass methods
    assert client.generate_description(inference.GenerateDescriptionInput(keywords=None, images=[])) is None
    assert client.generate_keywords(inference.GenerateKeywordsInput(project_description="desc", images=[])) is None
    assert client.generate_reference_image(
        inference.GenerateReferenceImageInput(output_folder="out", project_description="pd", keywords="kw", images=[], camera=None)
    ) is None
    assert client.generate_base_sprite_image(
        inference.GenerateBaseSpriteImageInput(output_folder="out", sprite_description="spr", project_description="pd", keywords="kw", images=[], camera=None)
    ) is None
    assert client.generate_next_sprite_image(
        inference.GenerateNextSpriteImageInput(output_folder="out", animation_name="anim", image="img", camera=None)
    ) is None
    assert client.generate_sprite_between_images(
        inference.GenerateSpriteBetweenImagesInput(output_folder="out", animation_name="anim", images=['i1','i2'], camera=None)
    ) is None
    assert client.generate_sprite_animation_suggestion(
        inference.GenerateSpriteAnimationSuggestion(output_folder="out", animation_names=['a1'], sprite_description="spr", project_description="pd", keywords="kw")
    ) is None


def test_googleai_client_generate_reference_image_error(monkeypatch, capsys):
    # Simulate failure in genai.Client constructor or generate_content
    monkeypatch.setattr(
        inference.genai, 'Client',
        lambda api_key=None: (_ for _ in ()).throw(Exception("ref_fail"))
    )
    client = inference.GoogleAIClient(api_key='key')
    input_obj = inference.GenerateReferenceImageInput(
        output_folder="out",
        project_description="pd",
        keywords="kw",
        images=[],
        camera=None
    )
    result = client.generate_reference_image(input_obj)
    captured = capsys.readouterr().out

    assert result is None
    assert "Error calling GoogleAI for reference image: ref_fail" in captured


def test_googleai_client_generate_base_sprite_image_open_error(tmp_path, capsys):
    # Provide a file that exists but is not a valid image
    bad_file = tmp_path / 'bad.png'
    bad_file.write_bytes(b'not_an_image')
    client = inference.GoogleAIClient(api_key='key')

    input_obj = inference.GenerateBaseSpriteImageInput(
        output_folder=str(tmp_path),
        sprite_description="spr",
        project_description="pd",
        keywords="kw",
        images=[str(bad_file)],
        camera=None
    )
    result = client.generate_base_sprite_image(input_obj)
    captured = capsys.readouterr().out

    # Should catch the PIL open error and skip the file
    assert result is None
    assert "Error opening reference image" in captured
    assert bad_file.name in captured
    # And still hit the final generation‐failure message
    assert "Google AI image generation failed or no image data received." in captured


def test_googleai_client_generate_base_sprite_image_exception(monkeypatch, capsys):
    # Simulate failure in genai.Client constructor
    monkeypatch.setattr(
        inference.genai, 'Client',
        lambda api_key=None: (_ for _ in ()).throw(Exception("base_fail"))
    )
    client = inference.GoogleAIClient(api_key='key')

    input_obj = inference.GenerateBaseSpriteImageInput(
        output_folder="out",
        sprite_description="spr",
        project_description="pd",
        keywords="kw",
        images=None,
        camera=None
    )
    result = client.generate_base_sprite_image(input_obj)
    captured = capsys.readouterr().out

    assert result is None
    assert "Error calling GoogleAI for base sprite image generation: base_fail" in captured


@patch('inference.Image.open')
def test_googleai_next_sprite_image_open_error(mock_image_open, tmp_path, capsys, monkeypatch):
    """Test coverage for lines 460-463: Error opening the input image."""
    # Setup: Mock Image.open to fail
    error_message = "PIL cannot open this specific file"
    mock_image_open.side_effect = Exception(error_message)

    # Mock genai client to avoid real API call
    monkeypatch.setattr(inference.genai, 'Client', lambda api_key=None: DummyGClient(parts=None, text_parts=None))

    client = inference.GoogleAIClient(api_key='dummy_key')
    img_path = tmp_path / "bad_image.png"
    img_path.touch()  # Make file exist for os.path.exists check

    input_obj = inference.GenerateNextSpriteImageInput(
        output_folder=str(tmp_path),
        animation_name="test_anim",
        image=str(img_path),
        camera=None
    )
    result = client.generate_next_sprite_image(input_obj)

    # Assertions
    captured = capsys.readouterr()
    expected_error_log = f"Error opening sprite image '{str(img_path)}': {error_message}. Skipping."
    assert expected_error_log in captured.out
    assert result is None
    mock_image_open.assert_called_once_with(str(img_path))


def test_googleai_next_sprite_api_error(tmp_path, capsys, monkeypatch):
    """Test coverage for lines 483-485: Error during the Google AI API call."""
    error_message = "Simulated API error from generate_content"
    monkeypatch.setattr(inference.genai, 'Client', lambda api_key=None: DummyGClient(fail_generate=True, fail_message=error_message))

    # Create a valid-looking image
    img_path = tmp_path / "input.png"
    img_path.write_bytes(make_png_bytes())

    client = inference.GoogleAIClient(api_key='dummy_key')
    input_obj = inference.GenerateNextSpriteImageInput(
        output_folder=str(tmp_path),
        animation_name="test_anim",
        image=str(img_path),
        camera=None
    )
    result = client.generate_next_sprite_image(input_obj)

    captured = capsys.readouterr()
    assert f"Error calling GoogleAI for next sprite image generation: {error_message}" in captured.out
    assert result is None


@patch('inference.Image.open')
def test_googleai_between_images_open_error(mock_image_open, tmp_path, capsys, monkeypatch):
    """Test coverage for lines 497-500: Error opening one of the input images in the list."""
    img1_path = tmp_path / "img1.png"
    img2_path = tmp_path / "img2_bad.png"
    img3_path = tmp_path / "img3.png"

    # Create dummy files so os.path.exists passes
    img1_path.write_bytes(make_png_bytes())
    img2_path.touch()  # Will fail
    img3_path.write_bytes(make_png_bytes())

    open_error_message = "PIL failed specifically on img2"
    successful_mock_image = MagicMock(name="SuccessfulPILImage")

    def image_open_side_effect(path):
        if path == str(img2_path):
            raise Exception(open_error_message)
        elif path in [str(img1_path), str(img3_path)]:
            return successful_mock_image
        else:
            pytest.fail(f"Unexpected call to Image.open with path: {path}")

    mock_image_open.side_effect = image_open_side_effect

    monkeypatch.setattr(inference.genai, 'Client', lambda api_key=None: DummyGClient(parts=None))

    client = inference.GoogleAIClient(api_key='dummy_key')
    input_obj = inference.GenerateSpriteBetweenImagesInput(
        output_folder=str(tmp_path),
        animation_name="test_anim",
        images=[str(img1_path), str(img2_path), str(img3_path)],
        camera=None
    )
    result = client.generate_sprite_between_images(input_obj)

    captured = capsys.readouterr()
    expected_error_log = f"Error opening sprite image '{str(img2_path)}': {open_error_message}. Skipping."
    assert expected_error_log in captured.out

    assert mock_image_open.call_count == 3
    mock_image_open.assert_any_call(str(img1_path))
    mock_image_open.assert_any_call(str(img2_path))
    mock_image_open.assert_any_call(str(img3_path))

    assert result is None
    assert "Google AI image generation failed or no image data received for sprite between images." in captured.out
