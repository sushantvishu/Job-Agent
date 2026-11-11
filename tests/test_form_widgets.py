from app.forms.widgets import CheckboxWidget, NumberInputWidget, SelectWidget, TextInputWidget
from app.utils import FillResult


def test_widget_can_handle():
    num_widget = NumberInputWidget()
    assert num_widget.can_handle({"type": "number"})
    assert not num_widget.can_handle({"type": "text"})

    text_widget = TextInputWidget()
    assert text_widget.can_handle({"type": "text", "tag": "input"})
    assert text_widget.can_handle({"tag": "textarea"})
    assert not text_widget.can_handle({"type": "checkbox", "tag": "input"})

    chk_widget = CheckboxWidget()
    assert chk_widget.can_handle({"type": "checkbox"})
    assert not chk_widget.can_handle({"type": "radio"})

    sel_widget = SelectWidget()
    assert sel_widget.can_handle({"tag": "select"})
    assert not sel_widget.can_handle({"tag": "input"})


def test_number_widget_extraction():
    assert NumberInputWidget._extract_numeric("Immediate") == "0"
    assert NumberInputWidget._extract_numeric("0 LPA (Fresher)") == "0"
    assert NumberInputWidget._extract_numeric("4.5") == "4.5"
    assert NumberInputWidget._extract_numeric("30 days") == "30"
    assert NumberInputWidget._extract_numeric("12") == "12"
