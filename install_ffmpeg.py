"""Install the FFmpeg and ffprobe command-line tools used for film assembly."""
from pathlib import Path
import requests
import zipfile
from download_local_models import ROOT, download_stream

response = requests.get('https://api.github.com/repos/BtbN/FFmpeg-Builds/releases/latest', timeout=30)
response.raise_for_status()
asset = next(a for a in response.json()['assets'] if a['name'] == 'ffmpeg-master-latest-win64-gpl.zip')
archive = ROOT / 'tools' / asset['name']
digest = (asset.get('digest') or '').removeprefix('sha256:') or None
download_stream((asset['browser_download_url'], archive, asset['size'], digest))
target = ROOT / 'tools' / 'ffmpeg'
target.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(archive) as zipped:
    for member in zipped.infolist():
        if Path(member.filename).name in ('ffmpeg.exe', 'ffprobe.exe'):
            (target / Path(member.filename).name).write_bytes(zipped.read(member))
archive.unlink()
print('Installed FFmpeg and ffprobe.')
