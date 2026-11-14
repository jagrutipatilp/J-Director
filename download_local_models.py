"""Download the model files selected for this local installation; safe to resume."""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time
import zipfile

import requests

ROOT = Path(__file__).resolve().parent
MODELS = Path(r"C:\src\ai drama\tools\ComfyUI\models")
FILES = [
    ("unsloth/LTX-2.3-GGUF", "distilled-1.1/ltx-2.3-22b-distilled-1.1-Q3_K_S.gguf", "unet"),
    ("Kijai/LTX2.3_comfy", "vae/LTX23_audio_vae_bf16.safetensors", "vae"),
    ("Kijai/LTX2.3_comfy", "vae/LTX23_video_vae_bf16.safetensors", "vae"),
    ("Kijai/LTX2.3_comfy", "text_encoders/ltx-2.3_text_projection_bf16.safetensors", "text_encoders"),
    ("Comfy-Org/ltx-2", "split_files/text_encoders/gemma_3_12B_it_fp4_mixed.safetensors", "text_encoders"),
    ("Lightricks/LTX-2.3", "ltx-2.3-spatial-upscaler-x2-1.1.safetensors", "latent_upscale_models"),
    ("unsloth/Z-Image-Turbo-GGUF", "z-image-turbo-Q4_K_M.gguf", "unet"),
    ("Comfy-Org/Z-Image-Turbo", "split_files/text_encoders/qwen_3_4b_fp4_mixed.safetensors", "text_encoders"),
    ("Comfy-Org/Z-Image-Turbo", "split_files/vae/ae.safetensors", "vae"),
]


def download_stream(item):
    url, path, size, digest = item
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size == size:
        if not digest or hashlib.file_digest(path.open("rb"), "sha256").hexdigest() == digest:
            print("Verified existing", path.name, flush=True)
            return
    partial = path.with_suffix(path.suffix + ".part")
    for attempt in range(5):
        try:
            start = partial.stat().st_size if partial.exists() else 0
            headers = {"Range": f"bytes={start}-"} if start else {}
            with requests.get(url, headers=headers, stream=True, timeout=(30, 120)) as response:
                response.raise_for_status()
                mode = "ab" if start and response.status_code == 206 else "wb"
                print("Downloading", path.name, "from", start, "of", size, flush=True)
                with partial.open(mode) as handle:
                    for chunk in response.iter_content(8 * 1024 * 1024):
                        handle.write(chunk)
            if partial.stat().st_size != size:
                raise ValueError("Incomplete file: " + path.name)
            if digest:
                with partial.open("rb") as handle:
                    actual = hashlib.file_digest(handle, "sha256").hexdigest()
                if actual != digest:
                    partial.unlink()
                    raise ValueError("Checksum mismatch: " + path.name)
            partial.replace(path)
            print("Completed", path.name, flush=True)
            return
        except (requests.RequestException, ValueError) as error:
            print("Retry", attempt + 1, path.name, str(error), flush=True)
            if attempt == 4:
                raise
            time.sleep(3)


def download(item):
    url, path, size, digest = item
    if path.exists() and path.stat().st_size == size:
        with path.open('rb') as handle:
            if not digest or hashlib.file_digest(handle, 'sha256').hexdigest() == digest:
                print('Verified existing', path.name, flush=True)
                return
    if ('huggingface.co/' not in url and 'registry.ollama.ai/' not in url) or size < 16 * 1024 * 1024:
        return download_stream(item)
    parts = path.parent / (path.name + '.parts')
    parts.mkdir(parents=True, exist_ok=True)
    block = 16 * 1024 * 1024
    count = (size + block - 1) // block

    def chunk(index):
        start, end = index * block, min((index + 1) * block, size) - 1
        part = parts / str(index)
        if part.exists() and part.stat().st_size == end - start + 1:
            return end - start + 1
        temporary = part.with_suffix('.partial')
        headers = part.with_suffix('.headers')
        # Retain accumulated partials across restarts; verify the final file by SHA256.
        fragment = part.with_suffix('.fragment')
        offset = temporary.stat().st_size if temporary.exists() else 0
        if fragment.exists() and headers.exists():
            expected_range = f'content-range: bytes {start + offset}-{end}/{size}'
            if expected_range in headers.read_text().lower() and fragment.stat().st_size <= end - start + 1 - offset:
                with temporary.open('ab') as handle, fragment.open('rb') as source:
                    shutil.copyfileobj(source, handle)
                fragment.unlink()
        for attempt in range(8):
            try:
                offset = temporary.stat().st_size if temporary.exists() else 0
                if offset == end - start + 1:
                    temporary.replace(part)
                    if headers.exists():
                        headers.unlink()
                    return offset
                if offset > end - start + 1:
                    temporary.unlink()
                    offset = 0
                first = start + offset
                query = f'?download=true&segment={index}&attempt={attempt}&t={time.time_ns()}'
                fragment = part.with_suffix('.fragment')
                result = subprocess.run([
                    'curl.exe', '--ipv4', '--silent', '--show-error', '--fail', '--location',
                    '--range', f'{first}-{end}', '--connect-timeout', '30', '--max-time', '180',
                    '--dump-header', str(headers), '--output', str(fragment), url + query,
                ], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
                valid_range = headers.exists() and f'content-range: bytes {first}-{end}/{size}' in headers.read_text().lower()
                if valid_range and fragment.exists() and fragment.stat().st_size <= end - first + 1:
                    with temporary.open('ab') as handle, fragment.open('rb') as source:
                        shutil.copyfileobj(source, handle)
                    fragment.unlink()
                    # The accumulated partial now always starts at the original range.
                    headers.write_text(f'content-range: bytes {start}-{end}/{size}')
                if result.returncode:
                    raise ValueError(result.stderr.decode(errors='replace')[-300:])
                if not valid_range:
                    raise ValueError('Server returned an incorrect byte range')
                if temporary.stat().st_size != end - start + 1:
                    raise ValueError('Incomplete chunk')
                temporary.replace(part)
                headers.unlink()
                return end - start + 1
            except (requests.RequestException, ValueError) as error:
                if attempt == 7:
                    raise
                print('Retrying', path.name, 'chunk', index, str(error), flush=True)
                time.sleep(min(60, 2 ** (attempt + 1)))

    completed = 0
    failures = []
    started = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        for result in concurrent.futures.as_completed([pool.submit(chunk, i) for i in range(count)]):
            try:
                completed += result.result()
            except Exception as error:
                failures.append(str(error))
                print('Chunk failed; saved transfers remain available:', str(error), flush=True)
            if completed == size or time.monotonic() - started > 20:
                print(f'{path.name}: {completed / size:.1%}', flush=True)
                started = time.monotonic()
    if failures:
        raise RuntimeError('Some chunks could not be downloaded; rerun to resume: ' + '; '.join(failures[:3]))
    partial = path.with_suffix(path.suffix + '.part')
    actual = hashlib.sha256()
    with partial.open('wb') as handle:
        for index in range(count):
            data = (parts / str(index)).read_bytes()
            handle.write(data)
            actual.update(data)
            (parts / str(index)).unlink()
    if digest and actual.hexdigest() != digest:
        raise ValueError('Checksum mismatch: ' + path.name)
    partial.replace(path)
    for index in range(count):
        if (parts / str(index)).exists():
            (parts / str(index)).unlink()
    for extra in parts.iterdir():
        if extra.suffix in {'.headers', '.fragment', '.partial'}:
            extra.unlink()
    parts.rmdir()
    print('Verified and installed', path.name, flush=True)


def cached_bytes(path, size):
    if path.exists() and path.stat().st_size == size:
        return size
    parts = path.parent / (path.name + '.parts')
    if not parts.exists():
        return 0
    saved = sum(part.stat().st_size for part in parts.iterdir()
                if part.is_file() and part.suffix in {'', '.partial', '.fragment'})
    return min(size, saved)


def main():
    metadata = {}
    manifest = []
    for repo, filename, folder in FILES:
        if repo not in metadata:
            response = requests.get(f"https://huggingface.co/api/models/{repo}?blobs=true", timeout=30)
            response.raise_for_status()
            metadata[repo] = response.json()
        info = metadata[repo]
        file = next(f for f in info["siblings"] if f["rfilename"] == filename)
        digest = file.get("lfs", {}).get("sha256")
        manifest.append((f"https://huggingface.co/{repo}/resolve/{info['sha']}/{filename}",
                         MODELS / folder / Path(filename).name, file["size"], digest))
    response = requests.get("https://api.github.com/repos/ollama/ollama/releases/latest", timeout=30)
    response.raise_for_status()
    release = response.json()
    asset = next(a for a in release["assets"] if a["name"] == "ollama-windows-amd64.zip")
    archive = ROOT / "tools" / asset["name"]
    manifest.append((asset["browser_download_url"], archive, asset["size"],
                     (asset.get("digest") or "").removeprefix("sha256:") or None))
    remaining = sum(max(0, size - cached_bytes(path, size))
                    for _, path, size, _ in manifest)
    planner_remaining = 6_600_000_000
    planner_manifest = ROOT / 'planning-model-manifest.json'
    if planner_manifest.exists():
        planner = json.loads(planner_manifest.read_text())
        planner_remaining = sum(max(0, layer['size'] - cached_bytes(
            ROOT / 'local-models' / 'ollama' / 'blobs' / layer['digest'].replace(':', '-'), layer['size']))
            for layer in [planner['config'], *planner['layers']])
    reserve = planner_remaining + 2_300_000_000 + 2_000_000_000
    free = shutil.disk_usage(ROOT).free
    print(f"Model/archive downloads: {remaining / 1e9:.1f} GB; free: {free / 1e9:.1f} GB", flush=True)
    if remaining and free < remaining + reserve:
        raise RuntimeError("Insufficient disk space for downloads, Ollama extraction and its planning model")
    (ROOT / "local-model-manifest.json").write_text(json.dumps([
        {"url": url, "path": str(path), "bytes": size, "sha256": digest}
        for url, path, size, digest in manifest], indent=2))
    # Install smaller supporting files first so they can be validated early.
    for item in sorted(manifest, key=lambda item: item[2]):
        download(item)
    target = ROOT / "tools" / "ollama"
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zipped:
        for member in zipped.infolist():
            if not (target / member.filename).resolve().is_relative_to(target.resolve()):
                raise ValueError("Unsafe archive member")
        zipped.extractall(target)
    print("Models and portable Ollama installed.", flush=True)


if __name__ == "__main__":
    main()
