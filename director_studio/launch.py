"""Launch J Director in a dedicated desktop window, keeping render services alive."""
from pathlib import Path
import ctypes,json,os,subprocess,time
import requests
ROOT=Path(__file__).resolve().parents[1]
URL='http://127.0.0.1:8790'

def ready():
 try:
  response=requests.get(URL+'/api/projects',timeout=2)
  return response.ok and isinstance(response.json(),list)
 except (requests.RequestException,ValueError):return False

def desktop_browser():
 paths=[Path(os.environ.get('PROGRAMFILES(X86)','C:/Program Files (x86)'))/'Microsoft/Edge/Application/msedge.exe',Path(os.environ.get('PROGRAMFILES','C:/Program Files'))/'Microsoft/Edge/Application/msedge.exe',Path(os.environ.get('PROGRAMFILES','C:/Program Files'))/'Google/Chrome/Application/chrome.exe',Path(os.environ.get('LOCALAPPDATA',''))/'Google/Chrome/Application/chrome.exe']
 return next((p for p in paths if p.is_file()),None)

def window_command(browser):
 return [str(browser),'--app='+URL,'--user-data-dir='+str(ROOT/'.desktop-profile'),'--no-first-run','--no-default-browser-check','--window-size=1440,960']

def main():
 if not ready():
  logs=ROOT/'logs';logs.mkdir(exist_ok=True)
  with (logs/'director-launch.out.log').open('a') as out,(logs/'director-launch.err.log').open('a') as err:
   subprocess.Popen([str(ROOT/'.venv/Scripts/python.exe'),'-m','uvicorn','director_studio.app:app','--host','127.0.0.1','--port','8790'],cwd=ROOT,stdout=out,stderr=err,creationflags=subprocess.CREATE_NO_WINDOW)
  for _ in range(60):
   if ready():break
   time.sleep(.3)
 if not ready():raise RuntimeError('J Director could not start. Check logs/director-launch.err.log.')
 browser=desktop_browser()
 if not browser:raise RuntimeError('Microsoft Edge or Google Chrome is needed for the desktop window.')
 process=subprocess.Popen(window_command(browser),cwd=ROOT)
 (ROOT/'logs').mkdir(exist_ok=True)
 (ROOT/'logs/desktop-window.json').write_text(json.dumps({'pid':process.pid,'browser':str(browser),'url':URL,'mode':'app','profile':str(ROOT/'.desktop-profile')}),encoding='utf-8')

if __name__=='__main__':
 try:main()
 except Exception as error:ctypes.windll.user32.MessageBoxW(0,str(error),'J Director',0)
