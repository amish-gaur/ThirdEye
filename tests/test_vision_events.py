from scripts._fixtures import sample_event
from vision_pipeline.events import build_event, parse_classifier_output


def test_parse_classifier_output_accepts_json() -> None:
    raw = (
        '{"tier": 3, "behavior_pattern": "taking_item", "confidence": 0.82, '
        '"scene": "front porch", '
        '"suspect_description": "young man in red hoodie and dark jeans", '
        '"one_line_summary": "took a package from the porch", '
        '"time_elapsed": "ignored"}'
    )
    parsed = parse_classifier_output(raw, 1.25)
    assert parsed == {
        "tier": 3,
        "behavior_pattern": "taking_item",
        "confidence": 0.82,
        "scene": "the front porch",
        "suspect_description": "young man in red hoodie and dark jeans",
        "one_line_summary": "took a package from the porch",
        "time_elapsed": "1.25s",
    }


def test_parse_classifier_output_accepts_single_quoted_literal() -> None:
    raw = (
        "{'tier': 4, 'behavior_pattern': 'collapsed', 'confidence': 0.91, "
        "'scene': 'driveway', "
        "'suspect_description': 'older man in blue jacket on driveway', "
        "'one_line_summary': 'resident has fallen', 'time_elapsed': 'ignored'}"
    )
    parsed = parse_classifier_output(raw, 2.5)
    assert parsed == {
        "tier": 4,
        "behavior_pattern": "collapsed",
        "confidence": 0.91,
        "scene": "the driveway",
        "suspect_description": "older man in blue jacket on driveway",
        "one_line_summary": "resident has fallen",
        "time_elapsed": "2.50s",
    }


def test_build_event_matches_action_router_shape() -> None:
    baseline = sample_event()
    event = build_event(
        classification={
            "tier": 3,
            "behavior_pattern": "taking_item",
            "confidence": 0.82,
            "scene": "the library aisle",
            "suspect_description": "young man in red hoodie",
            "one_line_summary": "took a package from the porch",
            "time_elapsed": "0.75s",
        },
        node_id="node_local",
        frame_seq=4321,
        yolo_classes=["person"],
        raw_classifier="{}",
        timestamp=1715301234.567,
    )
    assert set(event.keys()) == set(baseline.keys())
    assert event["tier_name"] == "ALERT"
    assert event["yolo_classes"] == ["person"]
    assert event["behavior_pattern"] == "taking_item"
    assert event["scene"] == "the library aisle"
