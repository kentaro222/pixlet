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

    def test_shape_modes_preview_geometry_and_undo_redo(self):
        square = {(x, y) for y in range(4, 9) for x in range(4, 9)}
        square_outline = {(x, y) for x, y in square if x in (4, 8) or y in (4, 8)}
        circle = square - {(4, 4), (8, 4), (4, 8), (8, 8)}
        circle_outline = ({(x, y) for x in (5, 6, 7) for y in (4, 8)} |
                          {(x, y) for x in (4, 8) for y in (5, 6, 7)})
        cases = [('Rect', 'Outline', (4, 4), (8, 8), square_outline, '□'),
                 ('Rect', 'Filled', (8, 8), (4, 4), square, '■'),
                 ('Ellipse', 'Outline', (8, 8), (4, 4), circle_outline, '○'),
                 ('Ellipse', 'Filled', (4, 4), (8, 8), circle, '●'),
                 ('Ellipse', 'Outline', (4, 4), (4, 8), {(4, y) for y in range(4, 9)}, '○'),
                 ('Ellipse', 'Filled', (4, 4), (4, 4), {(4, 4)}, '●')]
        for kind, fill, start, end, expected, icon in cases:
            with self.subTest(kind=kind, fill=fill, start=start, end=end):
                self.import_project(project())
                self.page.locator('#shapeTool').click()
                self.page.locator('#shape' + kind).click()
                self.page.locator('#shape' + fill).click()
                self.assertEqual(self.page.locator('#shape' + kind).get_attribute('aria-pressed'), 'true')
                self.assertEqual(self.page.locator('#shape' + fill).get_attribute('aria-pressed'), 'true')
                self.page.locator('#shapeModeSheet .closeSheet').click()
                self.assertEqual(self.page.locator('#shapeIcon').inner_text(), icon)
                self.page.mouse.move(*self.xy(*start))
                self.page.mouse.down()
                self.page.mouse.move(*self.xy(*end))
                self.assertEqual(self.saved()['frames'], project()['frames'])
                self.page.mouse.up()
                drawn = self.saved()
                layer = drawn['frames'][0]['layers'][1]
                self.assertEqual({(i % 16, i // 16) for i, value in enumerate(layer) if value}, expected)
                self.page.locator('#undoBtn').click()
                self.assertEqual(self.saved()['frames'], project()['frames'])
                self.page.locator('#redoBtn').click()
                self.assertEqual(self.saved(), drawn)

    def test_selection_dimensions_follow_drag_move_copy_and_clear(self):
        self.import_project(project())
        self.page.locator('[data-tool="select"]').click()
        size = self.page.locator('#selectionSize')
        self.assertTrue(size.is_hidden())
        for start, end, label in [((3, 4), (7, 6), '選択: 5 × 3 px'),
                                  ((10, 12), (7, 8), '選択: 4 × 5 px')]:
            self.page.mouse.move(*self.xy(*start))
            self.page.mouse.down()
            self.page.mouse.move(*self.xy(*end))
            self.assertEqual(size.inner_text(), label)
            self.page.mouse.up()
            self.assertTrue(size.is_visible())
            self.assertEqual(size.inner_text(), label)
            self.page.locator('#moveSelRight').click()
            self.assertEqual(size.inner_text(), label)
            self.page.locator('#copySel').click()
            self.page.locator('#pasteSel').click()
            self.assertEqual(size.inner_text(), label)
            self.page.locator('#clearSel').click()
            self.assertTrue(size.is_hidden())
        self.page.mouse.click(*self.xy(5, 5))
        self.assertEqual(size.inner_text(), '選択: 1 × 1 px')
        self.page.locator('#addFrame').click()
        self.assertTrue(size.is_hidden())

    def test_showing_layer_selects_it_and_last_visible_layer_stays_visible(self):
        data = project()
        data.update(activeLayer=0, layerVisible=[True, False, False])
        self.import_project(data)
        main = self.page.locator('.layer[data-layer="1"]')
        main.dblclick(delay=80)
        self.assertTrue(self.saved()['layerVisible'][1])
        self.assertEqual(self.saved()['activeLayer'], 1)
        self.assertEqual(self.page.locator('.layer.active').get_attribute('data-layer'), '1')
        self.page.reload()
        self.assertEqual(self.page.locator('.layer.active').get_attribute('data-layer'), '1')
        main.dblclick(delay=80)
        self.assertFalse(self.saved()['layerVisible'][1])
        self.assertEqual(self.saved()['activeLayer'], 0)
        self.page.locator('.layer[data-layer="0"]').dblclick(delay=80)
        self.assertEqual(self.saved()['layerVisible'], [True, False, False])
        self.assertEqual(self.saved()['activeLayer'], 0)

    def test_color_swap_keeps_canvas_visible_and_supports_undo_redo(self):
        data = project()
        data['frames'].append(copy.deepcopy(data['frames'][0]))
        for frame in data['frames']:
            for layer in frame['layers']:
                layer[0:3] = [1, 2, 3]
        expected = copy.deepcopy(data['frames'])
        for frame in expected:
            for layer in frame['layers']:
                layer[0:3] = [2, 1, 3]
        for viewport in [{'width': 1280, 'height': 900}, {'width': 390, 'height': 844},
                         {'width': 320, 'height': 568}]:
            with self.subTest(viewport=viewport):
                self.page.set_viewport_size(viewport)
                self.import_project(data)
                before = self.saved()
                canvas_before = self.page.locator('#view').bounding_box()
                self.page.locator('#menuBtn').click()
                self.page.locator('#paletteManageBtn').click()
                self.page.locator('#openPaletteSwap').click()
                self.assertEqual(self.page.locator('.sheet.open').count(), 0)
                canvas = self.page.locator('#view').bounding_box()
                panel = self.page.locator('#paletteSwapControls').bounding_box()
                self.assertEqual(canvas, canvas_before)
                self.assertGreater(canvas['height'], 0)
                self.assertGreaterEqual(panel['y'], canvas['y'] + canvas['height'])
                close = self.page.locator('#closePaletteSwap').bounding_box()
                self.assertLessEqual(close['y'] + close['height'], viewport['height'])
                # Viewing the artwork must not accidentally paint while choosing colors.
                self.page.mouse.click(canvas['x'] + canvas['width']/2,
                                      canvas['y'] + canvas['height']/2)
                self.assertEqual(self.saved(), before)
                self.assertTrue(self.page.locator('#swapPaletteColors').is_disabled())
                self.page.locator('.paletteSwapSlot').nth(0).click()
                self.assertTrue(self.page.locator('#swapPaletteColors').is_disabled())
                self.page.locator('.paletteSwapSlot').nth(1).click()
                self.page.locator('#swapPaletteColors').click()
                swapped = self.saved()
                self.assertEqual(swapped['frames'], expected)
                self.assertEqual(swapped['palette'], before['palette'])
                self.assertTrue(self.page.locator('#paletteSwapControls').is_visible())
                self.page.locator('#swapUndo').click()
                self.assertEqual(self.saved(), before)
                self.page.locator('#swapRedo').click()
                self.assertEqual(self.saved(), swapped)
                self.page.locator('#closePaletteSwap').click()
                self.assertTrue(self.page.locator('#normalControls').is_visible())
                self.page.reload()
                self.assertEqual(self.saved(), swapped)

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
