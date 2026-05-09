from action_router.twiml import play_response, play_with_gather, say_response


def test_say_response_escapes_xml() -> None:
    xml = say_response("hello & <world>")
    assert xml.startswith('<?xml version="1.0"')
    assert "<Response>" in xml and "</Response>" in xml
    assert "hello &amp; &lt;world&gt;" in xml
    assert 'voice="alice"' in xml


def test_play_response_includes_url_and_optional_fallback() -> None:
    xml = play_response("https://example.com/a.mp3")
    assert "<Play>https://example.com/a.mp3</Play>" in xml
    assert "<Say" not in xml

    xml2 = play_response("https://example.com/a.mp3", fallback_text="hi there")
    assert "<Play>https://example.com/a.mp3</Play>" in xml2
    assert "<Say" in xml2 and "hi there" in xml2


def test_play_with_gather_collects_one_digit() -> None:
    xml = play_with_gather("https://example.com/a.mp3", "https://example.com/cb")
    assert 'numDigits="1"' in xml
    assert 'action="https://example.com/cb"' in xml
    assert "<Hangup/>" in xml
