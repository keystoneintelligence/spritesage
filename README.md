# 🧙‍♂️ Sprite Sage

**Enter a realm of pixelated magic.**  
Sprite Sage is your generative AI-powered companion for crafting sprite assets and animations. Empowered with multi-provider AI support and a built-in Godot exporter, this open-source tool is forged for indie game developers to bring your ideas to reality.

---

## 🔥 Preview

### Sample Outputs  
![Sample Sprite 1](https://via.placeholder.com/80/8B0000)  
![Sample Sprite 2](https://via.placeholder.com/80/FF8C00)  
![Sample Sprite 3](https://via.placeholder.com/80/FFD700)  
![Sample Sprite 4](https://via.placeholder.com/80/228B22)  
![Sample Sprite 5](https://via.placeholder.com/80/4B0082)

---

## ✨ Key Features

- 🧠 **Multi-Provider AI Support**: Generate sprites using Google Gemini 2.0 or OpenAI Image-1 (bring your own API key).
- 🎮 **Godot Export**: Export directly to `.tscn` and `.tres` files for seamless use in Godot.
- 🌟 **Thematic Control**: Guide AI output with custom references and style descriptions.
- 🧩 **Open Source, Indie-Friendly**: Licensed under GPLv3 — no royalties, no constraints.

---

## 🛠️ Build Instructions

### Requirements

- Python 3.10+
- `pip`, `venv`, `pyinstaller`
- Windows/macOS/Linux

### Build From Source

```bash
# Optional cleanup
rmdir /s /q build dist  # Windows
rm -rf build dist       # macOS/Linux

# Create and activate virtual environment
python -m venv venv
venv\Scripts\activate       # Windows
source venv/bin/activate    # macOS/Linux

# Install dependencies
pip install -r requirements.txt

# Build the app
pyinstaller main.spec

The output executable appears in the dist/ folder.

---

## 🚧 Roadmap

| Feature             | Description                                        |
|---------------------|----------------------------------------------------|
| **Pixel Editor**     | Quick image tweaks inline in the tool             |
| **Animation Templates** | Frame-consistent motion presets              |
| **Type Settings**    | Sprite classification and metadata tagging        |
| **Quality of Life**  | Batch export, sprite cloning, docs, and polish    |

---

## ❓ FAQ

**How do I connect my own AI API key?**  
Go to `Settings → LLM Settings`, paste your key, and it’ll be stored locally on your device.

**Which file formats are supported?**  
Currently: `.png`, `.tscn`, and `.tres` for Godot. More are planned.

**Can I use Sprite Sage for commercial projects?**  
Yes! The GPLv3 license allows full commercial use. You're responsible for your own API key costs.

---

## 🌐 Links

- [🌿 Sprite Sage Website](https://www.keystoneintelligence.ai/spritesage)
- [🕹️ Itch.io Page](https://itch.io)

---

## 📜 License

Sprite Sage is released under the [GNU General Public License v3.0](LICENSE).  
Third-party MIT-licensed components are included and acknowledged in `THIRD_PARTY_LICENSES.md`.

---

## 💡 Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.
