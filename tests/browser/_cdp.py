"""A tiny Chrome DevTools driver: navigate, evaluate JS, screenshot."""
import base64
import itertools
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.request

CHROME_CANDIDATES = (
    os.environ.get('CHROME_BIN', ''),
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    shutil.which('google-chrome') or '',
    shutil.which('chromium') or '',
)


def chrome_path():
    return next((p for p in CHROME_CANDIDATES if p and os.path.exists(p)), None)


class Browser:
    def __init__(self, port, width=1300, height=1000):
        import websocket
        self.proc = subprocess.Popen(
            [chrome_path(), '--headless=new', '--disable-gpu', '--hide-scrollbars',
             f'--remote-debugging-port={port}', '--remote-allow-origins=*',
             f'--window-size={width},{height}', f'--user-data-dir={tempfile.mkdtemp()}',
             'about:blank'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        page = None
        for _ in range(150):
            try:
                targets = json.load(urllib.request.urlopen(f'http://127.0.0.1:{port}/json'))
                page = [t for t in targets if t['type'] == 'page'][0]
                break
            except Exception:
                time.sleep(0.1)
        if page is None:
            self.proc.kill()
            raise RuntimeError('Chrome did not start')
        self.ws = websocket.create_connection(page['webSocketDebuggerUrl'], timeout=30,
                                              suppress_origin=True)
        self.ids = itertools.count(1)
        self.cmd('Page.enable')
        self.cmd('Runtime.enable')
        self.cmd('Emulation.setDeviceMetricsOverride', width=width, height=height,
                 deviceScaleFactor=1, mobile=False)

    def cmd(self, method, **params):
        i = next(self.ids)
        self.ws.send(json.dumps({'id': i, 'method': method, 'params': params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get('id') == i:
                if 'error' in msg:
                    raise RuntimeError(msg['error'])
                return msg.get('result', {})

    def goto(self, url, settle=0.6):
        self.cmd('Page.navigate', url=url)
        deadline = time.time() + 20
        while time.time() < deadline:
            if self.js('document.readyState') == 'complete':
                break
            time.sleep(0.1)
        time.sleep(settle)

    def js(self, expr):
        r = self.cmd('Runtime.evaluate', expression=expr, returnByValue=True, awaitPromise=True)
        if 'exceptionDetails' in r:
            raise RuntimeError(r['exceptionDetails'].get('exception', {}).get('description')
                               or r['exceptionDetails'])
        return r.get('result', {}).get('value')

    def shot(self, path):
        data = self.cmd('Page.captureScreenshot', format='png')['data']
        with open(path, 'wb') as f:
            f.write(base64.b64decode(data))

    def close(self):
        try:
            self.ws.close()
        finally:
            self.proc.kill()
