import hashlib, importlib.util, io, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('installer',Path(__file__).resolve().parents[1]/'install/setup_windows.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class Response(io.BytesIO):
    status=200
    headers={}
class InstallerTests(unittest.TestCase):
    def row(self,data):return dict(repo='example/repo',file='model.bin',revision='abc',bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
    def test_valid_existing_skips_network(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'model.bin';p.write_bytes(b'abc')
            with patch.object(m.urllib.request,'urlopen',side_effect=AssertionError('network')):m.download(self.row(b'abc'),p)
    def test_hash_failure_does_not_publish(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'model.bin'
            with patch.object(m.urllib.request,'urlopen',return_value=Response(b'bad')):
                with self.assertRaises(RuntimeError):m.download(self.row(b'abc'),p)
            self.assertFalse(p.exists());self.assertTrue(p.with_suffix('.bin.part').exists())
    def test_server_ignoring_resume_restarts(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'model.bin';p.with_suffix('.bin.part').write_bytes(b'a')
            with patch.object(m.urllib.request,'urlopen',return_value=Response(b'abc')):m.download(self.row(b'abc'),p)
            self.assertEqual(p.read_bytes(),b'abc')
    def test_projector_destination_stable(self):
        p=m.model_target(Path('ComfyUI'),dict(repo='unsloth/Qwen2.5-VL-7B-Instruct-GGUF',file='mmproj-BF16.gguf',folder='text_encoders'))
        self.assertEqual(p.name,'Qwen2.5-VL-7B-Instruct-mmproj-BF16.gguf')
if __name__=='__main__':unittest.main()
