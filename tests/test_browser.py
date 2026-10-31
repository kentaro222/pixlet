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

    def test_new_canvas_preset_selection_persists_and_undo_restores_work(self):
        original = project()
        original.update(activeLayer=0, activeColor=6, layerVisible=[True, False, False])
        original['frames'][0]['layers'][0][0] = 5
        palettes = [original['palette'], ['transparent', '#000000', '#2B2B2B', '#555555',
                                        '#808080', '#AAAAAA', '#D4D4D4', '#FFFFFF']]
        for index, palette in enumerate(palettes):
            with self.subTest(preset=index):
                self.import_project(original)
                before = self.saved()
                self.page.locator('#menuBtn').click()
                self.page.locator('#newCanvasBtn').click()
                self.assertEqual(self.page.locator('#newCanvasPalette option').all_text_contents(),
                                 ['標準カラー', 'グレースケール'])
                self.page.locator('#newCanvasPalette').select_option(str(index))
                self.page.locator('#wInput').fill('8')
                self.page.locator('#newCanvasHeight').fill('12')
                self.page.locator('#resizeBtn').click()
                created = self.saved()
                self.assertEqual(created['palette'], palette)
                self.assertEqual((created['width'], created['height']), (8, 12))
                self.assertEqual(created['frames'], [{'layers': [[0] * 96 for _ in range(3)]}])
                self.assertEqual(created['activeLayer'], 1)
                self.assertEqual(created['layerVisible'], [True] * 3)
                self.page.locator('#undoBtn').click()
                self.assertEqual(self.saved(), before)
                self.page.locator('#redoBtn').click()
                self.assertEqual(self.saved(), created)
                self.page.reload()
                self.assertEqual(self.saved(), created)
        self.page.locator('#menuBtn').click()
        self.page.locator('#newCanvasBtn').click()
        self.assertEqual(self.page.locator('#newCanvasPalette').input_value(), '0')
        self.page.locator('#newCanvasPalette').select_option('1')
        self.page.locator('#newCanvasSheet .closeSheet').click()
        self.assertEqual(self.saved(), created)

    def test_png_import_targets_visible_main_including_color_reduction(self):
        original = project()
        original.update(activeLayer=0, layerVisible=[True, False, True])
        original['frames'][0]['layers'][0][0] = 5
        for color_count in [2, 8]:
            with self.subTest(colors=color_count):
                self.import_project(original)
                before = self.saved()
                png = self.page.evaluate('''count => {
                    const canvas = document.createElement('canvas');
                    canvas.width = 32; canvas.height = 16;
                    const ctx = canvas.getContext('2d');
                    for (let x = 0; x < count; x++) {
                        ctx.fillStyle = `rgb(${x * 30}, ${255 - x * 30}, 80)`;
                        ctx.fillRect(x, 0, 1, 1);
                    }
                    ctx.fillRect(16, 0, 1, 1);
                    return canvas.toDataURL('image/png').split(',')[1];
                }''', color_count)
                self.page.locator('#menuBtn').click()
                self.page.locator('#importPngBtn').click()
                self.page.locator('#pngFile').set_input_files({
                    'name': 'sprite.png', 'mimeType': 'image/png',
                    'buffer': base64.b64decode(png)})
                self.page.wait_for_function("document.querySelector('#pngInfo').textContent.includes('推定:')")
                self.page.locator('#pngImportDo').click()
                if color_count > 7:
                    self.page.locator('#pngReduceDo').click()
                imported = self.saved()
                self.assertEqual((imported['width'], imported['height']), (16, 16))
                self.assertEqual(len(imported['frames']), 2)
                self.assertEqual(imported['activeLayer'], 1)
                self.assertTrue(imported['layerVisible'][1])
                self.assertEqual(self.page.locator('.layer.active').get_attribute('data-layer'), '1')
                for index, frame in enumerate(imported['frames']):
                    self.assertEqual(frame['layers'][0], [0] * 256)
                    self.assertEqual(frame['layers'][2], [0] * 256)
                    self.assertEqual(sum(value != 0 for value in frame['layers'][1]),
                                     color_count if index == 0 else 1)
                    self.assertTrue(all(0 <= value <= 7 for value in frame['layers'][1]))
                self.page.locator('#undoBtn').click()
                self.assertEqual(self.saved(), before)
                self.page.locator('#redoBtn').click()
                self.assertEqual(self.saved(), imported)
                self.page.reload()
                self.assertEqual(self.saved(), imported)
                self.assertEqual(self.page.locator('.layer.active').get_attribute('data-layer'), '1')

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
