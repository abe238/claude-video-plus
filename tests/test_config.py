"""WATCH_DETAIL resolution and frame_cap mapping."""
from __future__ import annotations

import config


def test_default_detail_is_balanced(monkeypatch, tmp_path):
    monkeypatch.delenv("WATCH_DETAIL", raising=False)
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "missing.env")
    assert config.get_config()["detail"] == "balanced"


def test_env_overrides_detail(monkeypatch, tmp_path):
    monkeypatch.setenv("WATCH_DETAIL", "efficient")
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "missing.env")
    assert config.get_config()["detail"] == "efficient"


def test_invalid_detail_falls_back_to_default(monkeypatch, tmp_path):
    monkeypatch.setenv("WATCH_DETAIL", "bogus")
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "missing.env")
    assert config.get_config()["detail"] == "balanced"


def test_get_config_keys(monkeypatch, tmp_path):
    monkeypatch.delenv("WATCH_DETAIL", raising=False)
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "missing.env")
    cfg = config.get_config()
    assert set(cfg) == {"detail", "config_file"}


def test_vad_defaults_on_with_a_detect_only_model_path(monkeypatch, tmp_path):
    """R2a-2: WATCH_VAD defaults on, but activation still requires the model
    file to already exist (detected, never downloaded)."""
    monkeypatch.delenv("WATCH_VAD", raising=False)
    monkeypatch.delenv("WATCH_VAD_MODEL_PATH", raising=False)
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "missing.env")
    cfg = config.get_transcription_config()
    assert cfg["vad"] is True
    assert cfg["vad_model_path"]  # a concrete default location exists


def test_watch_vad_off_disables(monkeypatch, tmp_path):
    monkeypatch.setenv("WATCH_VAD", "off")
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "missing.env")
    assert config.get_transcription_config()["vad"] is False


def test_watch_vad_model_path_override(monkeypatch, tmp_path):
    monkeypatch.setenv("WATCH_VAD_MODEL_PATH", str(tmp_path / "silero.bin"))
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "missing.env")
    assert config.get_transcription_config()["vad_model_path"] == str(tmp_path / "silero.bin")


def test_frame_cap_mapping():
    assert config.frame_cap("efficient") == 50
    assert config.frame_cap("balanced") == 100
    assert config.frame_cap("token-burner") is None
    assert config.frame_cap("transcript") is None
    assert config.frame_cap("anything-else") == 100


def test_read_env_file_quoted_value_with_trailing_comment(tmp_path):
    # fork-watch (jvdurian): quotes must be unwrapped BEFORE the comment strip,
    # else 'balanced' leaks as '"balanced"' and fails WATCH_DETAIL validation.
    p = tmp_path / ".env"
    p.write_text('WATCH_DETAIL="balanced"  # note\nWATCH_X=plain  # c\nK="sk-a#1"\n', encoding="utf-8")
    r = config.read_env_file(p)
    assert r["WATCH_DETAIL"] == "balanced"
    assert r["WATCH_X"] == "plain"
    assert r["K"] == "sk-a#1"           # '#' inside quotes preserved (API keys)


def test_env_parsers_agree_across_config_whisper_setup(tmp_path, monkeypatch):
    # All three .env readers must resolve a quoted+comment value identically now
    # that whisper._from_dotenv and setup._read_env_key delegate to read_env_file.
    import whisper, setup
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    # whisper reads ~/.config/watch/.env; point HOME at tmp so it reads ours.
    home_env = tmp_path / ".config" / "watch" / ".env"
    home_env.parent.mkdir(parents=True)
    home_env.write_text('GROQ_API_KEY="gsk_x"  # my key\n', encoding="utf-8")
    monkeypatch.setattr(whisper.Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(setup, "CONFIG_FILE", home_env)
    assert config.read_env_file(home_env)["GROQ_API_KEY"] == "gsk_x"   # config parser
    assert setup._read_env_key("GROQ_API_KEY") == "gsk_x"              # setup delegates
    assert whisper.load_api_key() == ("groq", "gsk_x")                 # whisper delegates
