import tempfile,unittest
from pathlib import Path
from unittest.mock import patch,Mock
import requests
from director_studio import engines,store
class WriterTests(unittest.TestCase):
 def test_available_writer_is_not_started_twice(self):
  with patch.object(engines.requests,'get',return_value=Mock()),patch.object(engines.subprocess,'Popen') as start:
   engines.ensure_writer();start.assert_not_called()
 def test_custom_offline_server_is_not_replaced(self):
  with patch.object(engines,'settings',return_value={'ollama_url':'http://localhost:9999'}),patch.object(engines.requests,'get',side_effect=requests.ConnectionError):
   with self.assertRaisesRegex(RuntimeError,'offline'):engines.ensure_writer()
 def test_installed_local_writer_starts_with_local_models(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);exe=root/'tools/ollama-bootstrap/ollama.exe';exe.parent.mkdir(parents=True);exe.touch()
   with patch.object(store,'ROOT',root),patch.object(engines.requests,'get',side_effect=[requests.ConnectionError(),requests.ConnectionError(),Mock()]),patch.object(engines.subprocess,'Popen') as start:
    engines.ensure_writer();args=start.call_args
    self.assertEqual(args.args[0],[str(exe),'serve']);self.assertEqual(args.kwargs['env']['OLLAMA_MODELS'],str(root/'local-models/ollama'));self.assertEqual(args.kwargs['env']['OLLAMA_NO_CLOUD'],'true')
