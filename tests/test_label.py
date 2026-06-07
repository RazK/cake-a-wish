from label_printer.label import LabelImage


def test_render_preview():
    img = LabelImage('Test', '29x90').render()
    assert img is not None
