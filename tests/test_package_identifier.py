from action_router.package_identifier import PackageMatch, identify_package


def test_identify_package_returns_empty_match_without_orders() -> None:
    result = identify_package("/does/not/matter.mp4", {})

    assert isinstance(result, PackageMatch)
    assert result.to_dict() == {
        "order_id": None,
        "order_title": None,
        "confidence": 0.0,
        "candidates": [],
        "reasoning": "No candidate orders were provided in the event or PACKAGE_ORDERS_PATH.",
    }


def test_identify_package_uses_explicit_event_order_id(mocker) -> None:
    qwen = mocker.patch("action_router.package_identifier._call_qwen_for_package_match")
    event = {
        "package_order_id": "ord_2",
        "orders": [
            {"order_id": "ord_1", "title": "coffee filters"},
            {"order_id": "ord_2", "title": "wireless doorbell"},
        ],
    }

    result = identify_package("/does/not/matter.mp4", event)

    assert result.order_id == "ord_2"
    assert result.order_title == "wireless doorbell"
    assert result.confidence == 1.0
    assert result.candidates[0].to_dict() == {
        "order_id": "ord_2",
        "title": "wireless doorbell",
        "confidence": 1.0,
    }
    qwen.assert_not_called()


def test_identify_package_normalizes_qwen_json(mocker) -> None:
    mocker.patch(
        "action_router.package_identifier._call_qwen_for_package_match",
        return_value="""
        ```json
        {
          "order_id": "ord_1",
          "order_title": "blue running shoes",
          "confidence": 0.82,
          "candidates": [
            {"order_id": "ord_1", "title": "blue running shoes", "confidence": 0.82},
            {"order_id": "ord_2", "title": "phone charger", "confidence": 0.2}
          ],
          "reasoning": "The visible box is shoe-box sized."
        }
        ```
        """,
    )
    event = {
        "orders": [
            {"order_id": "ord_1", "title": "blue running shoes"},
            {"order_id": "ord_2", "title": "phone charger"},
        ],
        "one_line_summary": "person picked up a package",
    }

    result = identify_package("/does/not/matter.mp4", event)

    assert result.to_dict() == {
        "order_id": "ord_1",
        "order_title": "blue running shoes",
        "confidence": 0.82,
        "candidates": [
            {"order_id": "ord_1", "title": "blue running shoes", "confidence": 0.82},
            {"order_id": "ord_2", "title": "phone charger", "confidence": 0.2},
        ],
        "reasoning": "The visible box is shoe-box sized.",
    }


def test_identify_package_falls_back_to_text_overlap_when_qwen_fails(mocker) -> None:
    mocker.patch(
        "action_router.package_identifier._call_qwen_for_package_match",
        side_effect=RuntimeError("model unavailable"),
    )
    event = {
        "orders": [
            {"order_id": "ord_1", "title": "blue running shoes"},
            {"order_id": "ord_2", "title": "phone charger"},
        ],
        "package_description": "small box containing a phone charger",
    }

    result = identify_package("/does/not/matter.mp4", event)

    assert result.order_id == "ord_2"
    assert result.order_title == "phone charger"
    assert result.confidence > 0.5
    assert result.reasoning.startswith("Qwen was unavailable")
