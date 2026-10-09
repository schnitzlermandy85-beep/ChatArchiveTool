import io
import os
import pathlib
import re
import subprocess
import sys
import time
import unittest
import urllib.request
import json
import threading
from unittest.mock import Mock, patch

sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
import app
import web_app
from test_core import test_directory


class LauncherTests(unittest.TestCase):
    def test_hidden_output_has_a_log_and_missing_files_are_reported(self):
        log=io.StringIO();stream=app.StartupStream(None,log)
        stream.write('visible in log\n');stream.flush()
        self.assertEqual(log.getvalue(),'visible in log\n')
        with test_directory() as root, patch.object(app,'ROOT',pathlib.Path(root)), patch.object(sys,'argv',['app.py','--check']):
            self.assertEqual(app.main(),1)
            text=(pathlib.Path(root)/'logs/startup.log').read_text(encoding='utf-8')
            self.assertIn('Missing web/index.html',text)
            self.assertIn('Extract the entire ZIP',text)

    def test_browser_falls_back_when_known_browser_fails(self):
        with patch('web_app.browser_candidates',return_value=[pathlib.Path('fake-browser.exe')]),patch('web_app.subprocess.Popen',side_effect=OSError('unavailable')),patch('web_app.webbrowser.open',return_value=True) as fallback:
            self.assertTrue(web_app.open_browser_window('http://127.0.0.1:5000/'))
            fallback.assert_called_once()
        with patch('web_app.browser_candidates',return_value=[]),patch('web_app.webbrowser.open',return_value=False):
            self.assertFalse(web_app.open_browser_window('http://127.0.0.1:5000/'))

    def test_browser_immediate_nonzero_exit_uses_fallback(self):
        failed_browser=Mock()
        failed_browser.wait.return_value=1
        with patch('web_app.browser_candidates',return_value=[pathlib.Path('fake-browser.exe')]),patch('web_app.subprocess.Popen',return_value=failed_browser),patch('web_app.webbrowser.open',return_value=True) as fallback:
            self.assertTrue(web_app.open_browser_window('http://127.0.0.1:5000/'))
            fallback.assert_called_once_with('http://127.0.0.1:5000/')

    def test_running_browser_and_successful_handoff_do_not_open_twice(self):
        for result in (0, subprocess.TimeoutExpired('fake-browser',.75)):
            browser=Mock()
            if isinstance(result,Exception):browser.wait.side_effect=result
            else:browser.wait.return_value=result
            with self.subTest(result=result),patch('web_app.browser_candidates',return_value=[pathlib.Path('fake-browser.exe')]),patch('web_app.subprocess.Popen',return_value=browser),patch('web_app.webbrowser.open') as fallback:
                self.assertTrue(web_app.open_browser_window('http://127.0.0.1:5000/'))
                fallback.assert_not_called()

    def test_browser_start_does_not_block_the_local_server(self):
        browser_started=threading.Event();release_browser=threading.Event();browser_finished=threading.Event()
        def blocked_browser(url):
            browser_started.set()
            try:release_browser.wait(3)
            finally:browser_finished.set()
            return True
        server=Mock();server.server_port=5000
        def serve(**kwargs):
            self.assertTrue(browser_started.wait(1))
            self.assertFalse(browser_finished.is_set())
        server.serve_forever.side_effect=serve
        with test_directory() as root,patch.object(web_app,'ROOT',pathlib.Path(root)),patch('web_app.make_server',return_value=server),patch('web_app.open_browser_window',side_effect=blocked_browser):
            try:web_app.run()
            finally:
                release_browser.set()
                self.assertTrue(browser_finished.wait(1))
        server.server_close.assert_called_once()

    def test_native_ready_file_is_fresh_and_removed_on_exit(self):
        with test_directory() as root:
            ready=pathlib.Path(root)/'ready.json'
            ready.write_text('{"url":"http://127.0.0.1:1/","pid":1}')
            server=Mock();server.server_port=5555
            def serve(**kwargs):
                self.assertEqual(json.loads(ready.read_text()),
                                 {'url':'http://127.0.0.1:5555/','pid':os.getpid()})
            server.serve_forever.side_effect=serve
            with patch.dict(os.environ,{'CHATARCHIVE_LAUNCH_READY':str(ready)}),patch.object(web_app,'ROOT',pathlib.Path(root)),patch('web_app.make_server',return_value=server):
                web_app.run(open_browser=False)
            self.assertFalse(ready.exists())
            server.server_close.assert_called_once()

    @unittest.skipUnless(os.name=='nt','Windows batch launcher')
    def test_actual_batch_check_and_running_server(self):
        root=pathlib.Path(__file__).resolve().parents[1]
        result=subprocess.run(['cmd.exe','/d','/c','start.cmd','--check'],cwd=root,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('Startup check passed',result.stdout)
        process=subprocess.Popen([sys.executable,'-u',str(root/'app.py'),'--no-browser'],cwd=root,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace')
        try:
            url=None
            for _ in range(8):
                line=process.stdout.readline()
                if line.startswith('ChatArchive: '):url=line.partition(': ')[2].strip();break
                if not line and process.poll() is not None:break
            self.assertIsNotNone(url)
            with urllib.request.urlopen(url,timeout=3) as response:
                page=response.read().decode('utf-8')
            self.assertIn('关系分析',page)
            self.assertTrue((root/'打开界面.html').is_file())
            self.assertEqual((root/'logs/current-url.txt').read_text(encoding='utf-8').strip(),url)
            token=re.search(r'name="archive-token" content="([^"]+)"',page).group(1)
            request=urllib.request.Request(url+'api/shutdown',data=b'{}',headers={'Content-Type':'application/json','X-Archive-Token':token})
            with urllib.request.urlopen(request,timeout=3) as response:self.assertTrue(json.load(response)['ok'])
            self.assertEqual(process.wait(timeout=5),0)
        finally:
            if process.poll() is None:process.terminate();process.wait(timeout=5)
            if process.stdout:process.stdout.close()


if __name__=='__main__':unittest.main()
