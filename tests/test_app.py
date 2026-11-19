from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "app" / "streamlit_app.py")


def test_demo_reviews_a_sample_without_an_llm_key(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    at = AppTest.from_file(APP, default_timeout=90).run()
    assert not at.exception
    assert at.metric[0].label == "Comments posted"


def test_demo_reviews_pasted_code(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    at = AppTest.from_file(APP, default_timeout=90).run()
    at.radio[0].set_value("My own code").run()
    at.button[0].click().run()
    assert not at.exception and int(at.metric[0].value) >= 1  # the coupon call has no timeout
