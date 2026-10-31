# Browser regression tests

Run from the repository root:

```sh
python3 -m unittest discover -s tests -v
```

Requires Python 3, the `playwright` Python package, and Chromium. The prepared
cloud environment includes these tools. Elsewhere, install Playwright with
`python3 -m pip install playwright` and install Chromium through your OS package
manager. Set `CHROMIUM_PATH` if the browser is not at `/usr/bin/chromium`.

The tests start their own local HTTP server on an available port and use isolated
browser contexts. They cover invalid project rejection without overwriting work,
v2 project roundtrips, index recovery, continuous pen strokes with undo/redo, and
color picking with hidden layers, new-canvas palette selection, and PNG import
into a visible MAIN layer (including automatic color reduction). They do not
change browser user profiles.
