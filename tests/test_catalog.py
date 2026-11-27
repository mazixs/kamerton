from console.catalog import HEADS, LANGS, OCTOBER_E2E, is_downloaded, openai_model_id, pick


def test_catalog_lists_model_revisions_in_ui_order():
    assert list(HEADS) == [
        "rnnt", "e2e_rnnt", OCTOBER_E2E, "ml_ctc", "ml_ctc_large",
        "gigaam_v4_rnnt", "gigaam_v4_ctc", "gigaam_multilingual_v2_rnnt",
        "whisper_tiny", "whisper_small", "whisper_large_v3_turbo", "whisper_large_v3",
        "parakeet_tdt_v3", "parakeet_ultra", "nemotron_35_asr", "t_one",
    ]
    assert HEADS["e2e_rnnt"].native_punctuation is True
    assert HEADS[OCTOBER_E2E].native_punctuation is True
    assert HEADS["rnnt"].native_punctuation is False
    assert "ru" in HEADS["rnnt"].languages
    assert "kk" in HEADS["ml_ctc"].languages


def test_every_head_has_russian_copy_and_size():
    for head in HEADS.values():
        assert head.title and head.subtitle
        assert head.size_mb > 0
        assert head.files


def test_is_downloaded_requires_every_file(tmp_path):
    assert is_downloaded("rnnt", tmp_path) is False
    for name in HEADS["rnnt"].files:
        (tmp_path / name).write_bytes(b"x")
    assert is_downloaded("rnnt", tmp_path) is True


def test_is_downloaded_ignores_empty_files(tmp_path):
    for name in HEADS["rnnt"].files:
        (tmp_path / name).write_bytes(b"")
    assert is_downloaded("rnnt", tmp_path) is False


def test_is_downloaded_unknown_head_is_false(tmp_path):
    assert is_downloaded("whisper-large", tmp_path) is False


def test_openai_model_ids():
    assert openai_model_id("rnnt") == "gigaam-v3-rnnt"
    assert openai_model_id("ml_ctc_large") == "gigaam-multilingual-large-ctc"
    assert openai_model_id("gigaam_v4_rnnt") == "gigaam-v4-rnnt"
    assert openai_model_id("gigaam_v4_ctc") == "gigaam-v4-ctc"
    assert openai_model_id("gigaam_multilingual_v2_rnnt") == "gigaam-multilingual-v2-rnnt"
    assert len(HEADS["gigaam_multilingual_v2_rnnt"].languages) == 21


def test_badges_name_our_own_measurement_not_someone_elses_table():
    e2e, large = HEADS["e2e_rnnt"].badge, HEADS["ml_ctc_large"].badge
    assert e2e and e2e["ru"] == "низкая ошибка на FLEURS ru"
    assert large and large["ru"] == "требует больше памяти"
    assert HEADS["rnnt"].badge is None and HEADS["ml_ctc"].badge is None
    for head in HEADS.values():
        if head.badge:
            assert head.badge_note is not None
            assert "наш замер" in head.badge_note["ru"]
            assert "our own measurement" in head.badge_note["en"].lower()


def test_every_head_text_exists_in_both_languages():
    """Пропущенный перевод показал бы пустую карточку, а не фразу не на том языке."""
    for head in HEADS.values():
        for field in (head.subtitle, head.badge, head.badge_note):
            if field is None:
                continue
            assert set(field) == set(LANGS), head.id
            assert all(value.strip() for value in field.values()), head.id


def test_unknown_language_falls_back_to_english():
    assert pick({"en": "a", "ru": "б"}, "xx") == "a"
    assert pick({"en": "a"}, "ru") == "a"
    assert pick(None, "en") is None
