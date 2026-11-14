# Windows 11 setup and migration

## Start here

1. Download or clone this repository into a short writable folder, preferably `C:\src\J-Director`. Avoid protected Program Files folders.
2. Update the NVIDIA driver, plug in the laptop, and select its performance power mode. Reboot after driver installation.
3. Open PowerShell in this folder. To inspect hardware only, run `powershell -ExecutionPolicy Bypass -File .\install\setup-windows.ps1` (Python 3.11 must already be installed for this check).
4. To install image generation and local story planning, run `powershell -ExecutionPolicy Bypass -File .\install\setup-windows.ps1 -Install`.
5. To also install H3 video model files, add `-WithVideo`. Review the displayed download size and type YES to proceed.
6. When setup finishes, double-click **Open J Director.cmd**. Start a small test before running an entire episode.

The wrapper installs Python 3.11, Git and Ollama using Windows Package Manager. Those installers can show Windows prompts. It then creates separate app/ComfyUI environments, installs CUDA-enabled PyTorch, ComfyUI and its GGUF nodes, downloads FFmpeg, downloads selected models, configures local paths, and pulls `qwen2.5:7b` for story planning. Dependencies and model licenses remain their publishers' responsibility; review the repositories before installation.

## Hardware decisions

| Hardware | Initial configuration |
|---|---|
| NVIDIA 6–8 GB dedicated VRAM | Quantized Q4 models, image 576 × 1024, video 480 × 832, conservative memory offloading |
| NVIDIA 12 GB or more | Same conservative initial resolutions; raise only after a successful benchmark |
| No NVIDIA GPU detected | Installation stops before large downloads; this installer targets CUDA |
| Less than 32 GB system RAM | Warning: large models may page heavily or fail |

The installer reads dedicated NVIDIA VRAM, not Intel shared memory. An NPU does not accelerate these CUDA workflows. It does not predict render times from a GPU name. Your RTX 2000 Ada 8 GB is still memory constrained for the large video model. An adequate Windows-managed page file and substantial free SSD space are important, but do not make system memory as fast as VRAM.

## Downloads and storage

`install/models.json` lists image and optional video sources. Before downloading, the installer resolves immutable model revisions, SHA256 checksums and exact byte counts from Hugging Face. It prints the total and checks remaining storage plus a 25 GiB runtime reserve. Keep extra room for projects, page file and outputs. If you add video later, rerun with `-WithVideo`.

Weights land under `tools/ComfyUI/models`; the writer model uses the system Ollama model directory. Downloads keep `.part` files and can resume. Final files are accepted only after size and SHA256 validation. If a checksum fails repeatedly, remove only the named corrupt `.part` file and retry. Download errors stop setup instead of reporting success. No proxy service is used.

The H3 option uses the published Comfy-Org pruned INT8 model and a compatible community GGUF text encoder, rather than a missing/private filename from the original laptop. It updates the H3 workflow filenames. This combination needs a small end-to-end render test on the new computer; it has not been benchmarked there. Model availability and compatibility can change.

## What is and is not installed

Included: J Director application dependencies, ComfyUI, GGUF custom nodes, Qwen text-to-image and image-edit weights, vision encoder/projector, Qwen VAE, Ollama story writer, FFmpeg; optional H3 video/audio model stack.

Not included: private stories/photos, existing project library, trained character LoRAs, third-party service accounts, paid APIs, VoiceStudio voice models, MoneyPrinterTurbo or celebrity voices. This repository is the J Director application snapshot, not a backup of every tool previously installed on the old laptop. Optional camera-angle LoRAs and Omnichar custom nodes require separate installation before using those optional features.

## Verify and troubleshoot

- Open `http://127.0.0.1:8790/api/health` after launching. Ollama should be available; ComfyUI starts when generation needs it.
- Make one simple image, then one reference edit, then a short video if installed. Check faces, audio and playback before committing to a long run.
- ComfyUI missing-node/model errors: inspect `logs/comfyui.err.log` and the reported node name; do not substitute arbitrary model files.
- CUDA unavailable: update NVIDIA driver, confirm `nvidia-smi` works, then consult [PyTorch installation](https://pytorch.org/get-started/locally/).
- Out of memory: close other GPU programs, use conservative resolution, keep one generation at a time. Stop the job before modifying its settings.
- Ollama offline: open Ollama from Start Menu or run `ollama serve`; the new install uses system Ollama rather than the old portable path.
- Some old root-level migration/test helpers are specific to the original laptop. Use the new installer; do not run `activate_comfy_backend.py` or legacy migration scripts on a fresh computer.
- Installation logs/settings stay local. Do not commit `settings.json`, downloaded weights or reference photos.

## Move your own projects

The GitHub repository intentionally excludes them. Stop generation on both machines, privately copy `projects` and `library` from the old installation into the new repository folder, and retain a backup. Review any old absolute paths. Do not overwrite the new machine's settings with the old machine's settings.

## Sources

- [ComfyUI](https://github.com/Comfy-Org/ComfyUI)
- [ComfyUI GGUF nodes](https://github.com/city96/ComfyUI-GGUF)
- [Ollama](https://github.com/ollama/ollama)
- [Model source list](install/models.json)

Installation automation is checked separately from GPU rendering. A successful installation is not a guarantee of character consistency, lip sync or a particular generation speed.
