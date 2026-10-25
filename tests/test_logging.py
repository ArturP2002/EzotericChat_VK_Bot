from app.logging_setup import imya_knopki, kratko, nastroit_zhurnal


def test_kratko_rezhet_dlinnyy_tekst():
    text = "слово " * 100
    short = kratko(text, limit=40)
    assert len(short) <= 40
    assert short.endswith("…")


def test_imya_knopki():
    assert imya_knopki("clarify") == "Уточнить"
    assert imya_knopki("new_question") == "Новый вопрос"


def test_nastroit_zhurnal(tmp_path, monkeypatch):
    monkeypatch.setenv("LOG_DIR", str(tmp_path))
    monkeypatch.setenv("LOG_TO_FILE", "true")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    from app.config import get_settings

    get_settings.cache_clear()
    # Повторная настройка не должна падать, даже если журнал уже включён.
    nastroit_zhurnal()
    nastroit_zhurnal()
    get_settings.cache_clear()
