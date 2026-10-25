"""Browser regressions. Run: python3 -m unittest discover -s tests -v

Requires Python Playwright and Chromium (CHROMIUM_PATH overrides its location).
"""
import base64
import copy
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
from threading import Thread
import unittest

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def project():
    return dict(version=2, projectName='review', width=16, height=16,
                palette=['transparent', '#17191F', '#F4F4F4', '#D95757',
                         '#E58A47', '#DDBB4C', '#55A868', '#4C78A8'],
                frames=[{'layers': [[0] * 256 for _ in range(3)]}],
                activeFrame=0, activeLayer=1, activeColor=1,
                loopStart=None, loopEnd=None, layerVisible=[True] * 3)


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class BrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(ROOT)))
        cls.thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}'
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(
            executable_path=os.environ.get('CHROMIUM_PATH', '/usr/bin/chromium'),
            headless=True, args=['--no-sandbox'])

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        self.context = self.browser.new_context(viewport={'width': 1280, 'height': 900})
        self.page = self.context.new_page()
        self.errors = []
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))
        self.page.goto(self.url)
        self.page.wait_for_function("document.title === 'Pixlet v4.0'")
        self.page.wait_for_function("document.querySelector('#view').width > 0")

    def tearDown(self):
        self.context.close()
        self.assertEqual(self.errors, [])

    def import_project(self, data):
        code = 'Pixlet Project v2\nName: review\nData: ' + base64.b64encode(json.dumps(data).encode()).decode()
        self.page.locator('#menuBtn').click()
        self.page.locator('#saveCodeBtn').click()
        self.page.locator('#codeArea').fill(code)
        self.page.locator('#loadCode').click()

    def saved(self):
        return self.page.evaluate("JSON.parse(localStorage.getItem('pixlet-mobile-v2'))")

    def xy(self, x, y):
        box = self.page.locator('#view').bounding_box()
        zoom = int(min((box['width'] - 20) / 16, (box['height'] - 20) / 16))
        return (box['x'] + int((box['width'] - 16 * zoom) / 2) + (x + .5) * zoom,
                box['y'] + int((box['height'] - 16 * zoom) / 2) + (y + .5) * zoom)

    def test_invalid_import_preserves_current_work(self):
        original = project()
        original['frames'][0]['layers'][1][0] = 4
        self.import_project(original)
        before = self.saved()
        invalid = [dict(frames=[]), dict(width=0), dict(height=65), dict(width=1.5),
                   dict(version=999), dict(palette=['transparent']),
                   dict(frames=[{'layers': [[0] * 256]}])]
        for value in [-1, 8, 1.5, '1']:
            frames = copy.deepcopy(original['frames'])
            frames[0]['layers'][1][0] = value
            invalid.append(dict(frames=frames))
        frames = copy.deepcopy(original['frames'])
        frames[0]['layers'][1].pop()
        invalid.append(dict(frames=frames))
        for change in invalid:
            with self.subTest(change=list(change)):
                self.import_project({**original, **change})
                self.assertEqual(self.page.locator('#toast').inner_text(), 'コードを読み込めません')
                self.assertEqual(self.saved(), before)
                self.page.locator('#codeSheet .closeSheet').click()
        self.page.reload()
        self.assertEqual(self.page.locator('#frameInfo').inner_text(), '1 / 1')
        self.page.mouse.click(*self.xy(1, 1))
        self.assertEqual(self.saved()['frames'][0]['layers'][1][0], 4)

    def test_valid_v2_roundtrip_and_index_recovery(self):
        data = project()
        data.update(activeFrame=-1, activeLayer=20, activeColor=8, loopStart=99, loopEnd=-1)
        data['frames'][0]['layers'][1][136] = 7
        self.import_project(data)
        saved = self.saved()
        self.assertEqual((saved['activeFrame'], saved['activeLayer'], saved['activeColor']), (0, 1, 1))
        self.assertEqual((saved['loopStart'], saved['loopEnd']), (None, None))
        self.assertEqual(saved['frames'], data['frames'])
        self.page.reload()
        self.assertEqual(self.page.locator('#projectTitle').inner_text(), 'review')
        self.page.locator('#menuBtn').click()
        self.page.locator('#saveCodeBtn').click()
        code = self.page.locator('#codeArea').input_value()
        decoded = json.loads(base64.b64decode(code.split('Data: ')[1]))
        self.assertEqual(decoded, saved)

    def test_sparse_pen_events_are_connected_and_one_undo(self):
        for start, end, expected in [((1, 8), (14, 8), [(x, 8) for x in range(1, 15)]),
                                      ((14, 14), (1, 1), [(x, x) for x in range(1, 15)]),
                                      ((8, 14), (8, 1), [(8, y) for y in range(1, 15)])]:
            with self.subTest(start=start, end=end):
                self.import_project(project())
                self.page.mouse.move(*self.xy(*start))
                self.page.mouse.down()
                self.page.mouse.move(*self.xy(*end))
                self.page.mouse.up()
                drawn = self.saved()
                layer = drawn['frames'][0]['layers'][1]
                self.assertEqual({i for i, value in enumerate(layer) if value}, {y * 16 + x for x, y in expected})
                self.page.locator('#undoBtn').click()
                self.assertEqual(self.saved()['frames'], project()['frames'])
                self.page.locator('#redoBtn').click()
                self.assertEqual(self.saved(), drawn)

    def test_picker_and_long_press_ignore_hidden_layers(self):
        data = project()
        data['frames'][0]['layers'][1][136] = 1
        data['frames'][0]['layers'][2][136] = 3
        data['layerVisible'][2] = False
        self.import_project(data)
        self.page.locator('[data-tool="pick"]').click()
        self.page.mouse.click(*self.xy(8, 8))
        self.assertEqual(self.page.locator('.swatch.active span').inner_text(), '1')
        self.page.locator('[data-tool="pen"]').click()
        self.page.locator('.swatch').nth(4).click()
        self.page.mouse.move(*self.xy(8, 8))
        self.page.mouse.down()
        self.page.wait_for_timeout(750)
        self.page.mouse.up()
        self.assertEqual(self.page.locator('.swatch.active span').inner_text(), '1')
        self.assertEqual(self.saved()['frames'], data['frames'])
        data['layerVisible'][2] = True
        self.import_project(data)
        self.page.locator('[data-tool="pick"]').click()
        self.page.mouse.click(*self.xy(8, 8))
        self.assertEqual(self.page.locator('.swatch.active span').inner_text(), '3')
        self.page.mouse.click(*self.xy(0, 0))
        self.assertEqual(self.page.locator('.swatch.active span').inner_text(), '0')


if __name__ == '__main__':
    unittest.main()
