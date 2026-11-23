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

PREVIOUS_STANDARD_COLORS = [
    '#17191F', '#344A72', '#9B5688', '#3E875F', '#A36450', '#736A71', '#B9BAC6', '#F4F4F4',
    '#D95757', '#E58A47', '#DDBB4C', '#55A868', '#4C78A8', '#8B77AF', '#D878A2', '#E6AA91',
]
GRAYSCALE_COLORS = ['#000000', '#121212', '#242424', '#373737', '#494949', '#5B5B5B',
                    '#6D6D6D', '#808080', '#929292', '#A4A4A4', '#B6B6B6', '#C8C8C8',
                    '#DBDBDB', '#EDEDED', '#FFFFFF', '#FFFFFF']
STANDARD_COLORS = ['#000000', '#1D2B53', '#7E2553', '#008751', '#AB5236', '#5F574F',
                   '#C2C3C7', '#FFF1E8', '#FF004D', '#FFA300', '#FFEC27', '#00E436',
                   '#29ADFF', '#83769C', '#FF77A8', '#FFCCAA']


def project():
    return dict(version=2, projectName='review', width=16, height=16,
                palette=['transparent', *STANDARD_COLORS],
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
        self.page.wait_for_function("document.title === 'Pixlet v5.0'")
        self.page.wait_for_function("document.querySelector('#view').width > 0")

    def tearDown(self):
        self.context.close()
        self.assertEqual(self.errors, [])

    def import_project(self, data):
        code = 'Pixlet Project v2\nName: review\nData: ' + base64.b64encode(json.dumps(data).encode()).decode()
        self.import_code(code)

    def import_code(self, code):
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

    def upload_prep_image(self, color_count, semi=False):
        self.page.goto(self.url + '/prep/')
        image = self.page.evaluate('''({count, semi}) => {
            const canvas = document.createElement('canvas');
            canvas.width = 32; canvas.height = 16;
            const ctx = canvas.getContext('2d');
            for (let x = 0; x < count; x++) {
                ctx.fillStyle = `rgb(${x * 13}, ${255 - x * 11}, 80)`;
                ctx.fillRect(x, 0, 1, 1);
            }
            if (count) ctx.fillRect(31, 15, 1, 1);
            if (semi) {
                ctx.fillStyle = 'rgba(100, 100, 100, 0.5)';
                ctx.fillRect(30, 15, 1, 1);
            }
            return {png: canvas.toDataURL('image/png').split(',')[1],
                    pixels: Array.from(ctx.getImageData(0, 0, 32, 16).data)};
        }''', {'count': color_count, 'semi': semi})
        self.page.locator('#file').set_input_files({
            'name': '素材.png', 'mimeType': 'image/png',
            'buffer': base64.b64decode(image['png'])})
        self.page.wait_for_function("document.querySelector('#assetCount').textContent === '1'")
        return image['pixels']

    def download_prep_code(self):
        with self.page.expect_download() as event:
            self.page.locator('#saveTxt').click()
        return Path(event.value.path()).read_text()

    def test_prep_exports_16_colors_and_transparency_to_v5(self):
        for count in [0, 7, 8, 16]:
            for mode in ['single', 'row']:
                with self.subTest(colors=count, mode=mode):
                    pixels = self.upload_prep_image(count)
                    self.page.locator('#exportName').fill('比較用16色')
                    if mode == 'row':
                        self.page.locator('#codeMode').select_option('row')
                        self.page.locator('#codeW').fill('16')
                        self.page.locator('#codeH').fill('16')
                    self.assertIn('ok', self.page.locator('#compat').get_attribute('class'))
                    self.assertIn('不透明16色以内', self.page.locator('#codeInfo').inner_text())
                    code = self.download_prep_code()
                    data = json.loads(base64.b64decode(code.split('Data: ')[1]))
                    self.assertEqual(data['version'], 2)
                    self.assertEqual(len(data['palette']), 17)
                    self.assertEqual(data['palette'][0], 'transparent')
                    self.assertEqual(data['projectName'], '比較用16色')
                    fw = 16 if mode == 'row' else 32
                    self.assertEqual((data['width'], data['height']), (fw, 16))
                    self.assertEqual(len(data['frames']), 32 // fw)
                    for frame in data['frames']:
                        self.assertEqual(frame['layers'][0], [0] * (fw * 16))
                        self.assertEqual(frame['layers'][2], [0] * (fw * 16))
                    for y in range(16):
                        for x in range(32):
                            frame = data['frames'][x // fw]
                            index = frame['layers'][1][y * fw + x % fw]
                            rgba = ([int(data['palette'][index][i:i + 2], 16)
                                     for i in (1, 3, 5)] + [255]) if index else [0, 0, 0, 0]
                            offset = (y * 32 + x) * 4
                            self.assertEqual(rgba, pixels[offset:offset + 4])
                    self.page.goto(self.url)
                    self.import_code(code)
                    saved = self.saved()
                    self.assertEqual(saved['frames'], data['frames'])
                    self.assertEqual(saved['palette'], [color.upper() if i else color
                                                       for i, color in enumerate(data['palette'])])

    def test_prep_rejects_17_colors_then_reduces_to_16(self):
        self.upload_prep_image(17)
        self.page.locator('#codeMode').select_option('row')
        self.page.locator('#codeW').fill('16')
        self.page.locator('#codeH').fill('16')
        self.assertNotIn('ok', self.page.locator('#compat').get_attribute('class'))
        self.page.locator('#saveTxt').click()
        self.assertIn('16色を超えています', self.page.locator('#toast').inner_text())
        self.page.locator('#reduce').click()
        self.assertEqual(self.page.locator('#colorLimit').input_value(), '16')
        self.assertEqual(self.page.locator('#colorLimit option').all_text_contents(),
                         [str(i) for i in range(2, 17)])
        self.page.locator('#applyOp').click()
        self.assertIn('ok', self.page.locator('#compat').get_attribute('class'))
        code = self.download_prep_code()
        data = json.loads(base64.b64decode(code.split('Data: ')[1]))
        self.assertEqual(len(data['palette']), 17)
        self.assertEqual(len(data['frames']), 2)
        colors = {color for frame in data['frames'] for color in frame['layers'][1]} - {0}
        self.assertEqual(len(colors), 16)
        self.assertEqual(data['frames'][0]['layers'][1][32], 0)
        self.page.goto(self.url)
        self.import_code(code)
        self.assertEqual(self.saved()['frames'], data['frames'])

    def test_prep_still_requires_reducing_semitransparency(self):
        self.upload_prep_image(16, semi=True)
        self.assertIn('半透明', self.page.locator('#compat').inner_text())
        self.page.locator('#saveTxt').click()
        self.assertIn('半透明', self.page.locator('#toast').inner_text())
        self.page.locator('#reduce').click()
        self.page.locator('#applyOp').click()
        self.assertIn('ok', self.page.locator('#compat').get_attribute('class'))
        self.assertTrue(self.download_prep_code().startswith('Pixlet Project v2\n'))

    def test_legacy_palettes_keep_existing_indices_and_colors(self):
        for size in [8, 16, 17]:
            with self.subTest(palette_size=size):
                data = project()
                data['palette'] = ['transparent', *PREVIOUS_STANDARD_COLORS[:size - 1]]
                data['frames'][0]['layers'][1][0] = size - 1
                data['activeColor'] = size - 1
                self.import_project(data)
                saved = self.saved()
                self.assertEqual(len(saved['palette']), 17)
                self.assertEqual(saved['palette'][:size], data['palette'])
                self.assertEqual(saved['frames'], data['frames'])
                self.assertEqual(saved['activeColor'], size - 1)

    def test_studio_imports_and_reorders_editable_sheet_frames(self):
        self.page.set_viewport_size({'width': 390, 'height': 844})
        self.page.goto(self.url + '/sprite-sheet-studio/')
        png = self.page.evaluate('''() => {
            const canvas = document.createElement('canvas');
            canvas.width = 7; canvas.height = 5;
            const ctx = canvas.getContext('2d');
            [[0, 0, '#ff0000'], [4, 0, '#00ff00'], [0, 3, '#0000ff']].forEach(([x, y, color]) => {
                ctx.fillStyle = color;
                ctx.fillRect(x, y, 1, 1);
            });
            return canvas.toDataURL('image/png').split(',')[1];
        }''')
        self.page.locator('#addBlank').click()
        reorder = self.page.locator('#reorderFrames')
        self.assertTrue(reorder.is_disabled())

        def open_sheet():
            with self.page.expect_file_chooser() as event:
                self.page.locator('#loadSheet').click()
            chooser = event.value
            self.assertFalse(chooser.is_multiple())
            chooser.set_files({'name': 'sheet.png', 'mimeType': 'image/png',
                               'buffer': base64.b64decode(png)})
            self.page.locator('#sheetImport').wait_for(state='visible')

        open_sheet()
        self.assertTrue(self.page.locator('#sheetReplaceNotice').is_visible())
        self.page.locator('#sheetFrameWidth').fill('3')
        self.assertTrue(self.page.locator('#importSheet').is_disabled())
        self.page.locator('#cancelSheetImport').click()
        self.assertEqual(self.page.locator('#count').inner_text(), '0枚 / 1コマ')

        open_sheet()
        self.page.locator('#sheetFrameWidth').fill('3')
        self.page.locator('#sheetFrameHeight').fill('2')
        self.page.locator('#sheetGap').fill('1')
        self.assertIn('2列 × 2行', self.page.locator('#sheetGridInfo').inner_text())
        self.page.locator('#importSheet').click()
        self.assertEqual(self.page.locator('#frames .frame span').all_text_contents(),
                         ['1. sheet-1', '2. sheet-2', '3. sheet-3', '4. sheet-4'])
        self.assertEqual(self.page.locator('#cols').input_value(), '2')
        self.page.locator('#right').click()
        self.assertEqual(self.page.locator('#x').input_value(), '1')
        frames = self.page.locator('#frames .frame')
        move_to_end = self.page.locator('#moveFrameToEnd')
        self.assertTrue(move_to_end.is_hidden())
        reorder.click()
        self.assertIn('1番', self.page.locator('#reorderStatus').inner_text())
        reorder.click()
        self.assertEqual(reorder.get_attribute('aria-pressed'), 'false')
        self.assertEqual(frames.first.locator('span').inner_text(), '1. sheet-1')

        reorder.click()
        frames.nth(2).click()
        self.assertEqual(frames.locator('span').all_text_contents(),
                         ['1. sheet-2', '2. sheet-1', '3. sheet-3', '4. sheet-4'])
        self.assertEqual(frames.nth(1).get_attribute('aria-pressed'), 'true')
        self.assertEqual(reorder.get_attribute('aria-pressed'), 'false')
        self.assertEqual(self.page.locator('#x').input_value(), '1')

        frames.nth(3).click()
        reorder.click()
        frames.nth(2).click()
        self.assertEqual(frames.locator('span').all_text_contents(),
                         ['1. sheet-2', '2. sheet-1', '3. sheet-4', '4. sheet-3'])

        frames.nth(1).click()
        reorder.click()
        move_to_end.click()
        self.assertEqual(frames.locator('span').all_text_contents(),
                         ['1. sheet-2', '2. sheet-4', '3. sheet-3', '4. sheet-1'])
        self.assertEqual(frames.last.get_attribute('aria-pressed'), 'true')
        self.assertEqual(self.page.locator('#x').input_value(), '1')

        with self.page.expect_download() as event:
            self.page.locator('#export').click()
        exported = base64.b64encode(Path(event.value.path()).read_bytes()).decode()
        result = self.page.evaluate('''async png => {
            const img = new Image();
            img.src = 'data:image/png;base64,' + png;
            await img.decode();
            const canvas = document.createElement('canvas');
            canvas.width = img.width; canvas.height = img.height;
            const ctx = canvas.getContext('2d');
            ctx.drawImage(img, 0, 0);
            const pixels = [[0,0], [4,0], [0,3], [4,3], [5,3]].map(([x,y]) =>
                Array.from(ctx.getImageData(x,y,1,1).data));
            return [img.width, img.height, pixels];
        }''', exported)
        self.assertEqual(result, [7, 5, [[0, 255, 0, 255], [0, 0, 0, 0],
                                         [0, 0, 255, 255], [0, 0, 0, 0], [255, 0, 0, 255]]])

    def test_viewer_filename_length_does_not_change_image_layout(self):
        names = ['a.png', 'long_filename_' * 12 + '.png', '比較用の長いファイル名' * 12 + '.png']
        for width, height in [(320, 640), (390, 844), (530, 700), (531, 700),
                              (600, 700), (844, 390), (1280, 900)]:
            with self.subTest(viewport=(width, height)):
                self.page.set_viewport_size({'width': width, 'height': height})
                self.page.goto(self.url + '/pixel-viewer/')
                png = self.page.evaluate('''() => {
                    const canvas = document.createElement('canvas');
                    canvas.width = 16; canvas.height = 64;
                    const ctx = canvas.getContext('2d');
                    ctx.fillStyle = '#d95757'; ctx.fillRect(0, 0, 16, 64);
                    return canvas.toDataURL('image/png').split(',')[1];
                }''')
                self.page.locator('#files').set_input_files([
                    {'name': name, 'mimeType': 'image/png', 'buffer': base64.b64decode(png)}
                    for name in names])
                self.page.wait_for_function("document.querySelector('#name').textContent === 'a.png'")

                def layout():
                    self.page.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
                    return self.page.evaluate('''() => ({
                        boxes: ['.toolbar', '#stageArea', '#stage', '#view'].map(selector => {
                            const r = document.querySelector(selector).getBoundingClientRect();
                            return [r.x, r.y, r.width, r.height];
                        }),
                        scale: document.querySelector('#scaleInfo').textContent,
                        pixels: document.querySelector('#view').toDataURL()
                    })''')

                expected = layout()
                self.assertGreater(expected['boxes'][-1][3], 0)
                self.assertGreater(self.page.locator('#name').bounding_box()['width'], 0)
                for index in [1, 2, 0, 2, 1]:
                    self.page.locator('.thumb').nth(index).click()
                    self.assertEqual(self.page.locator('#name').inner_text(), names[index])
                    self.assertEqual(self.page.locator('#name').get_attribute('title'), names[index])
                    self.assertEqual(layout(), expected)
                self.assertFalse(self.page.evaluate(
                    'document.documentElement.scrollWidth > innerWidth'))

    def test_invalid_import_preserves_current_work(self):
        original = project()
        original['frames'][0]['layers'][1][0] = 4
        self.import_project(original)
        before = self.saved()
        invalid = [dict(frames=[]), dict(width=0), dict(height=65), dict(width=1.5),
                   dict(version=999), dict(palette=['transparent']),
                   dict(frames=[{'layers': [[0] * 256]}])]
        for value in [-1, 17, 1.5, '1']:
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
        data.update(activeFrame=-1, activeLayer=20, activeColor=17, loopStart=99, loopEnd=-1)
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

    def test_undo_redo_preserve_zoom_and_pan(self):
        for width, height in [(1280, 900), (390, 844)]:
            with self.subTest(viewport=(width, height)):
                self.page.set_viewport_size({'width': width, 'height': height})
                data = project()
                data['frames'][0]['layers'][0] = [2] * 256
                self.import_project(data)
                view = self.page.locator('#view')
                fitted = view.screenshot()
                box = view.bounding_box()
                x, y = box['x'] + box['width'] / 2, box['y'] + box['height'] / 2
                self.page.mouse.move(x + 30, y + 20)
                for _ in range(3):
                    before = view.evaluate('(canvas) => canvas.toDataURL()')
                    self.page.mouse.wheel(0, -100)
                    self.page.wait_for_function(
                        "before => document.querySelector('#view').toDataURL() !== before", arg=before)
                self.page.mouse.down(button='middle')
                self.page.mouse.move(x + 61, y + 39)
                self.page.mouse.up(button='middle')
                zoomed = view.screenshot()
                self.assertNotEqual(zoomed, fitted)
                self.page.mouse.click(x, y)
                drawn = self.saved()
                self.assertEqual(sum(bool(value) for value in drawn['frames'][0]['layers'][1]), 1)
                painted = view.screenshot()
                self.assertNotEqual(painted, zoomed)
                for _ in range(2):
                    self.page.locator('#undoBtn').click()
                    self.assertEqual(self.saved()['frames'], data['frames'])
                    self.assertEqual(view.screenshot(), zoomed)
                    self.page.locator('#redoBtn').click()
                    self.assertEqual(self.saved(), drawn)
                    self.assertEqual(view.screenshot(), painted)

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
                self.assertEqual(self.page.locator('#shapeModeSheet [data-shape]').all_text_contents(),
                                 ['□', '■', '○', '●'])
                self.page.locator('#shape' + kind + fill).click()
                self.assertEqual(self.page.locator('#shape' + kind + fill).get_attribute('aria-pressed'), 'true')
                self.assertEqual(self.page.locator('#shapeModeSheet [aria-pressed="true"]').count(), 1)
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

    def test_canvas_taps_select_swap_colors_without_editing_artwork(self):
        data = project()
        data.update(activeLayer=0, activeColor=7, layerVisible=[True, True, False])
        data['frames'][0]['layers'][1][68:72] = [1, 2, 3, 4]
        data['frames'][0]['layers'][2][68:70] = [7, 6]
        for touch in [False, True]:
            with self.subTest(touch=touch):
                self.context.close()
                self.context = self.browser.new_context(
                    viewport={'width': 390, 'height': 844}, has_touch=touch)
                self.page = self.context.new_page()
                self.page.on('pageerror', lambda error: self.errors.append(str(error)))
                self.page.goto(self.url)
                self.import_project(data)
                before = self.saved()
                self.page.locator('#menuBtn').click()
                self.page.locator('#paletteManageBtn').click()
                self.page.locator('#openPaletteSwap').click()
                tap = self.page.touchscreen.tap if touch else self.page.mouse.click
                tap(*self.xy(4, 4))
                self.assertEqual(self.page.locator('.paletteSwapSlot.source').inner_text(), '1')
                tap(*self.xy(5, 4))
                self.assertEqual(self.page.locator('.paletteSwapSlot.target').inner_text(), '2')
                self.assertFalse(self.page.locator('#swapPaletteColors').is_disabled())
                tap(*self.xy(4, 4))
                self.assertEqual(self.page.locator('.paletteSwapSlot.source').inner_text(), '2')
                self.assertTrue(self.page.locator('#swapPaletteColors').is_disabled())
                self.page.locator('.paletteSwapSlot').nth(2).click()
                self.assertEqual(self.page.locator('.paletteSwapSlot.target').inner_text(), '3')
                tap(*self.xy(7, 4))
                self.assertEqual(self.page.locator('.paletteSwapSlot.source').inner_text(), '4')
                self.assertEqual(self.page.locator('.paletteSwapSlot.target').count(), 0)
                tap(*self.xy(15, 15))
                canvas = self.page.locator('#view').bounding_box()
                tap(canvas['x'] + 1, canvas['y'] + 1)
                self.page.mouse.move(*self.xy(4, 4))
                self.page.mouse.down()
                self.page.mouse.move(*self.xy(5, 4))
                self.page.mouse.up()
                self.assertEqual(self.page.locator('.paletteSwapSlot.source').inner_text(), '4')
                self.assertEqual(self.saved(), before)
                tap(*self.xy(4, 4))
                self.page.locator('#swapPaletteColors').click()
                swapped = self.saved()
                expected = copy.deepcopy(before['frames'])
                expected[0]['layers'][1][68:72] = [4, 2, 3, 1]
                self.assertEqual(swapped['frames'], expected)
                self.assertEqual(swapped['activeLayer'], before['activeLayer'])
                self.assertEqual(swapped['activeColor'], before['activeColor'])
                self.page.locator('#swapUndo').click()
                self.assertEqual(self.saved(), before)
                self.page.locator('#swapRedo').click()
                self.assertEqual(self.saved(), swapped)

    def test_new_canvas_preset_selection_persists_and_undo_restores_work(self):
        self.page.mouse.click(*self.xy(8, 8))
        self.assertEqual(self.saved()['palette'], ['transparent', *STANDARD_COLORS])
        self.page.locator('#menuBtn').click()
        self.page.locator('#paletteManageBtn').click()
        self.assertEqual(self.page.locator('#palettePresets .paletteEntryName').all_text_contents(),
                         ['標準カラー', 'グレースケール'])
        self.page.locator('#paletteManageSheet .closeSheet').click()
        original = project()
        original['palette'] = ['transparent', *PREVIOUS_STANDARD_COLORS]
        original.update(activeLayer=0, activeColor=6, layerVisible=[True, False, False])
        original['frames'][0]['layers'][0][0] = 5
        palettes = [['transparent', *colors] for colors in
                    [STANDARD_COLORS, GRAYSCALE_COLORS]]
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
        for color_count in [2, 8, 16, 17]:
            with self.subTest(colors=color_count):
                self.import_project(original)
                before = self.saved()
                png = self.page.evaluate('''count => {
                    const canvas = document.createElement('canvas');
                    canvas.width = 32; canvas.height = 16;
                    const ctx = canvas.getContext('2d');
                    for (let x = 0; x < count; x++) {
                        ctx.fillStyle = `rgb(${x * 13}, ${255 - x * 11}, 80)`;
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
                if color_count > 16:
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
                                     min(color_count, 16) if index == 0 else 1)
                    self.assertTrue(all(0 <= value <= 16 for value in frame['layers'][1]))
                self.page.locator('#undoBtn').click()
                self.assertEqual(self.saved(), before)
                self.page.locator('#redoBtn').click()
                # v5 restores normalize HEX spelling while preserving the colors.
                restored = {**imported, 'palette': ['transparent',
                            *[color.upper() for color in imported['palette'][1:]]]}
                self.assertEqual(self.saved(), restored)
                self.page.reload()
                self.assertEqual(self.saved(), restored)
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
