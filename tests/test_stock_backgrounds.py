import io,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,Mock
from PIL import Image
from director_studio import stock_backgrounds as stock,store,library

class StockBackgroundTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  for obj,key,value in [(store,'ROOT',self.root),(store,'PROJECTS',self.root/'projects'),(library,'ROOT',self.root/'library')]:
   p=patch.object(obj,key,value);p.start();self.addCleanup(p.stop)
  p=patch.object(stock.engines,'settings',return_value={'existing_runtime':str(self.root),'background_source':'stock_first'});p.start();self.addCleanup(p.stop)
  keys=self.root/'studio/stock-settings.json';keys.parent.mkdir();keys.write_text(json.dumps({'pixabay_key':'secret-test-key'}))
  self.s=store.create('Stock','Story');self.a=store.add_node(self.s,'location','Villa corridor','Corridor outside the bedroom');self.r=store.add_node(self.s,'reference','Master',parent=self.a['id'],prompt='An empty corridor',category='Angles');self.a['primary_reference']=self.r['id'];store.persist(self.s)
 def jpg(self):
  b=io.BytesIO();Image.new('RGB',(32,32),'red').save(b,'JPEG');return b.getvalue()
 def test_room_title_wins_over_mentions_of_adjacent_rooms(self):
  self.assertEqual(stock.query_for(self.a),'hotel corridor')
 def test_search_filters_people_and_renders_and_caches_without_credentials(self):
  response=Mock(status_code=200);response.json.return_value={'hits':[{'id':1,'type':'photo','tags':'bedroom, 3d'},{'id':2,'type':'photo','tags':'woman, bedroom'},{'id':3,'type':'photo','tags':'corridor, hallway','pageURL':'https://pixabay.com/photos/3','largeImageURL':'https://cdn.pixabay.com/photo/3.jpg'}]}
  with patch.object(stock.requests,'get',return_value=response) as get:
   first=stock.search('hotel corridor');second=stock.search('hotel corridor')
  self.assertEqual([h['id'] for h in first],[3]);self.assertEqual(first,second);self.assertEqual(get.call_count,1)
  self.assertNotIn('secret-test-key',next((self.root/'.stock-cache').glob('*.json')).read_text())
 def test_import_saves_local_jpg_and_source_and_reuses_existing_master(self):
  hit={'id':7,'tags':'corridor','pageURL':'https://pixabay.com/photos/7','user':'Author'}
  with patch.object(stock,'search',return_value=[hit]),patch.object(stock,'download',return_value=self.jpg()):result=stock.fetch(self.s['id'],self.a['id'])
  ref=result['project']['nodes'][result['reference']];self.assertTrue(store.contained(self.s['id'],ref['output']).is_file());self.assertEqual(ref['source_provenance']['provider'],'Pixabay')
  with patch.object(stock,'search') as search:stock.fetch(self.s['id'],self.a['id'])
  search.assert_not_called();self.assertEqual(len(library.load()['assets']),1)
 def test_untrusted_download_host_is_rejected(self):
  with patch.object(stock.requests,'get') as get:
   with self.assertRaises(ValueError):stock.download({'largeImageURL':'http://127.0.0.1/private'})
  get.assert_not_called()
