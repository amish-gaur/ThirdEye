from action_router.router import execute_action
from scripts._fixtures import sample_event


def test_tier1_logs_only(dry_config) -> None:
    result = execute_action(sample_event(tier=1), config=dry_config)
    assert result.tier == 1
    assert result.tier_label == "AMBIENT"
    assert result.actions == ["log_only"]
    assert not result.calls
    assert not result.messages
    assert not result.errors


def test_tier2_sends_sms(dry_config) -> None:
    result = execute_action(sample_event(tier=2), config=dry_config)
    assert result.tier == 2
    assert "sms_homeowner" in result.actions
    assert len(result.messages) == 1
    msg = result.messages[0]
    assert msg.dry_run is True
    assert msg.to == dry_config.homeowner_phone
    assert "ThirdEye" in msg.body


def test_tier3_calls_homeowner(dry_config) -> None:
    result = execute_action(sample_event(tier=3), config=dry_config)
    assert result.tier == 3
    assert "call_homeowner" in result.actions
    assert len(result.calls) == 1
    call = result.calls[0]
    assert call.dry_run is True
    assert call.to == dry_config.homeowner_phone
    assert "<Say" in call.twiml  # ElevenLabs disabled -> Say path
    assert "<Gather" not in call.twiml
    assert "ThirdEye is watching." in call.twiml


def test_loitering_cannot_trigger_a_call_even_if_posted_as_tier3(dry_config) -> None:
    event = sample_event(tier=3, behavior_pattern="loitering")
    result = execute_action(event, config=dry_config)

    assert result.tier == 2
    assert "call_homeowner" not in result.actions
    assert "sms_homeowner" in result.actions


def test_collapsed_can_still_escalate_to_emergency(dry_config) -> None:
    result = execute_action(sample_event(tier=4), config=dry_config)
    assert result.tier == 4
    targets = {c.to for c in result.calls}
    assert targets == {
        dry_config.homeowner_phone,
        dry_config.emergency_dispatch_phone,
        dry_config.family_phone,
    }
    assert {"call_homeowner", "call_dispatch", "call_family"} <= set(result.actions)


def test_emergency_fans_out_to_neighbors_with_dedup(dry_config) -> None:
    cfg = dry_config
    object.__setattr__(
        cfg,
        "neighbor_phones",
        (
            cfg.emergency_dispatch_phone,  # duplicate of dispatch — must dedupe
            "+15555550199",                # genuine 4th contact
        ),
    )
    result = execute_action(sample_event(tier=4), config=cfg)
    assert result.tier == 4
    targets = {c.to for c in result.calls}
    assert targets == {
        cfg.homeowner_phone,
        cfg.emergency_dispatch_phone,
        cfg.family_phone,
        "+15555550199",
    }
    assert any(a.startswith("call_neighbor") for a in result.actions)


def test_emergency_fans_out_sms_with_keyframe_attachment(dry_config, mocker) -> None:
    """Tier 4 fires four SMS in parallel with the four calls, and each SMS
    carries the moment-of-theft keyframe as MMS media so every contact gets
    the photo even if they don't pick up the call."""
    import action_router.router as router_mod

    cfg = dry_config
    object.__setattr__(cfg, "neighbor_phones", ("+15555550199",))

    # Drop a real keyframe under MEDIA_DIR mirroring the layout the vision
    # pipeline writes (`media/frames/<incident>_<ts>.jpg`).
    frame = cfg.media_dir / "frames" / "inc_demo_1700000000.jpg"
    frame.parent.mkdir(parents=True, exist_ok=True)
    frame.write_bytes(b"\xff\xd8\xff\xe0fake-jpeg")

    spy = mocker.spy(router_mod, "send_sms")
    event = sample_event(tier=4)
    event["clip_path"] = str(frame)

    result = execute_action(event, config=cfg)
    assert result.tier == 4

    sms_targets = {m.to for m in result.messages if m.sid == "DRYRUN"}
    assert sms_targets == {
        cfg.homeowner_phone,
        cfg.emergency_dispatch_phone,
        cfg.family_phone,
        "+15555550199",
    }
    expected_sms_actions = {
        "sms_homeowner", "sms_dispatch", "sms_family", "sms_neighbor1",
    }
    assert expected_sms_actions <= set(result.actions)

    expected_url = f"{cfg.public_base_url}/media/frames/{frame.name}"
    media_args_per_call = [c.kwargs.get("media_urls") for c in spy.call_args_list]
    # Every SMS to the four emergency contacts must include the keyframe URL.
    matching = [m for m in media_args_per_call if m == [expected_url]]
    assert len(matching) == 4, (
        f"expected 4 SMS with frame attached, got {len(matching)}; "
        f"all media args: {media_args_per_call}"
    )


def test_emergency_sms_falls_back_to_text_only_when_frame_missing(dry_config, mocker) -> None:
    """If the keyframe path isn't usable (missing file, localhost base URL,
    or no clip_path on the event), the SMS fan-out still goes out — just
    without the MMS attachment. The voice calls and SMS body must still
    fire so the alert isn't silently dropped."""
    import action_router.router as router_mod

    cfg = dry_config
    spy = mocker.spy(router_mod, "send_sms")

    event = sample_event(tier=4)
    event.pop("clip_path", None)
    result = execute_action(event, config=cfg)

    assert result.tier == 4
    assert len(result.calls) == 3  # dispatch + homeowner + family
    sms = [m for m in result.messages if m.sid == "DRYRUN"]
    assert len(sms) == 3
    for call in spy.call_args_list:
        assert call.kwargs.get("media_urls") is None


def test_emergency_skips_mms_when_public_base_url_is_localhost(dry_config, mocker, tmp_path) -> None:
    """Twilio can't fetch from 127.0.0.1 — the resolver must refuse to
    advertise a localhost frame URL even if clip_path is otherwise valid."""
    import action_router.router as router_mod

    cfg = dry_config
    object.__setattr__(cfg, "public_base_url", "http://127.0.0.1:8001")
    frame = cfg.media_dir / "frames" / "inc_local.jpg"
    frame.parent.mkdir(parents=True, exist_ok=True)
    frame.write_bytes(b"\xff\xd8\xff\xe0fake-jpeg")

    spy = mocker.spy(router_mod, "send_sms")
    event = sample_event(tier=4)
    event["clip_path"] = str(frame)

    result = execute_action(event, config=cfg)
    assert result.tier == 4
    for call in spy.call_args_list:
        assert call.kwargs.get("media_urls") is None


def test_tier3_call_path_does_not_depend_on_public_base_url(dry_config) -> None:
    cfg = dry_config
    object.__setattr__(cfg, "public_base_url", "http://127.0.0.1:8001")

    result = execute_action(sample_event(tier=3), config=cfg)

    assert len(result.calls) == 1
    assert "<Gather" not in result.calls[0].twiml
    assert "<Say" in result.calls[0].twiml


def test_unknown_tier_clamped_to_one(dry_config) -> None:
    event = sample_event(tier=1)
    event["tier"] = 99
    result = execute_action(event, config=dry_config)
    assert result.tier == 1


def test_missing_tier_defaults_to_one(dry_config) -> None:
    event = sample_event(tier=1)
    event.pop("tier")
    result = execute_action(event, config=dry_config)
    assert result.tier == 1


def test_tier3_with_elevenlabs_uses_play(dry_config, mocker, tmp_path) -> None:
    """When ElevenLabs succeeds, the call should use <Play> (with <Say> fallback)."""
    import action_router.router as router_mod

    cfg = dry_config
    object.__setattr__(cfg, "use_elevenlabs", True)
    object.__setattr__(cfg, "elevenlabs_api_key", "test-el-key")

    fake_mp3 = tmp_path / "media" / "alert_x.mp3"
    fake_mp3.parent.mkdir(parents=True, exist_ok=True)
    fake_mp3.write_bytes(b"\x00")
    mocker.patch.object(router_mod, "synthesize_mp3", return_value=fake_mp3)

    result = execute_action(sample_event(tier=3), config=cfg)
    assert result.media_url and result.media_url.endswith("alert_x.mp3")
    assert len(result.calls) == 1
    twiml = result.calls[0].twiml
    assert "<Gather" not in twiml
    assert "<Play>" in twiml
    assert "alert_x.mp3" in twiml


def test_tts_failure_falls_back_to_say(dry_config, mocker) -> None:
    import action_router.router as router_mod

    cfg = dry_config
    object.__setattr__(cfg, "use_elevenlabs", True)
    object.__setattr__(cfg, "elevenlabs_api_key", "test-el-key")

    mocker.patch.object(
        router_mod, "synthesize_mp3", side_effect=RuntimeError("boom")
    )

    result = execute_action(sample_event(tier=3), config=cfg)
    assert result.media_url is None
    assert any("tts:" in e for e in result.errors)
    assert "<Say" in result.calls[0].twiml
    assert "<Play>" not in result.calls[0].twiml
