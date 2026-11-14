# J Director

Local short-drama planning, character/background reference management, image generation and video production workspace.

## Features

- Story and episode breakdown using a local Ollama model.
- Reusable character and background libraries with uploaded references.
- Scene/keyframe editing, Qwen image and H3 video workflows through ComfyUI.
- Serialized production queue, progress logs, review and export.
- Desktop-style browser workspace and a limited-motion editing pilot tool.

Character consistency, motion and lip sync depend on the selected models and references; they are not guaranteed. Large models can render slowly on laptop GPUs.

## Windows setup

1. Install Python, Git, Ollama, ComfyUI and FFmpeg as needed.
2. Create a Python environment: `python -m venv .venv`.
3. Install dependencies: `.venv\Scripts\python.exe -m pip install -r requirements-director.txt`.
4. Review `director_studio/settings.example.json`, copy it to `director_studio/settings.json`, and set paths for your machine.
5. Install the required ComfyUI custom nodes and model files for the workflows you intend to use. See the model manifests and workflow builders in this repository. Model weights are separate downloads with their own licenses.
6. Run `Open J Director.cmd`. The local workspace uses http://127.0.0.1:8790/.

This is a development snapshot of an existing local installation. Some helper scripts and model paths still assume `C:/src/J-Director` and `C:/src/ai drama`; review them before running on another computer. Automated setup helpers can download large model files; inspect them first.

## Private data

Projects, reference photos, generated media, models, browser profiles, queue state, local settings and API keys are intentionally excluded. A fresh clone does not contain your existing characters or stories.

## Validation

Run `.venv\Scripts\python.exe -m unittest discover -s tests` for the included unit checks. GPU generation requires the external model/runtime installation.

## License and attribution

Derived from [Matticusnicholas/KupkaProd-Cinema-Pipeline](https://github.com/Matticusnicholas/KupkaProd-Cinema-Pipeline). The original non-commercial license and copyright notice are retained in LICENSE. This derivative remains subject to that license; commercial use requires the permissions described there. The original project documentation is preserved in UPSTREAM_README.md.
