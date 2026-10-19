from backend.app.config.settings import Settings

def test_settings_default_values():
    s = Settings()
    assert s.APP_NAME == "JobPilot"
    assert s.DEFAULT_LLM_PROVIDER in ("gemini", "openai")
    assert s.CONFIDENCE_THRESHOLD_AUTO == 0.90
    assert s.CONFIDENCE_THRESHOLD_SUGGEST == 0.70
    assert s.DATABASE_URL.startswith("sqlite")
