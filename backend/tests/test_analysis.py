from app.routers.analysis import (
    _fallback_content,
    _prompt,
    _sanitize_analysis_content,
)


def _strain_context() -> dict:
    return {
        "day": "2026-05-25",
        "biometrics": {
            "date": "2026-05-25",
            "strain_score": 16,
            "recovery_score": 79,
            "sleep_score": 82,
            "hrv_rmssd": 63,
            "resting_hr": 46,
        },
        "pmc": {
            "date": "2026-05-25",
            "ctl": 50.12,
            "atl": 56.04,
            "tsb": -5.92,
            "daily_tss": 0,
        },
    }


def test_strain_prompt_includes_metric_scale_rules():
    prompt = _prompt("strain", _strain_context())

    assert "0-33 = light/recovery" in prompt
    assert "If strain_score is below 34" in prompt
    assert "-10 to +25 = productive/fresh/good form" in prompt


def test_strain_fallback_labels_low_strain_as_light():
    content = _fallback_content("strain", _strain_context())

    assert "strain is light" in content
    assert "recovery 79/100" in content
    assert "TSB -5.92" in content
    assert "significant" not in content.lower()
    assert "overload" not in content.lower()


def test_strain_sanitizer_replaces_bad_low_strain_model_text():
    bad_model_text = (
        "Your strain score of 16 indicates a significant training load, but a recovery score "
        "of 79 confirms you are well-positioned to sustain this intensity. The negative TSB "
        "of -5.92 suggests you are currently in a productive overload phase."
    )

    content = _sanitize_analysis_content("strain", _strain_context(), bad_model_text)

    assert "strain is light" in content
    assert "significant training load" not in content.lower()
    assert "productive overload" not in content.lower()
