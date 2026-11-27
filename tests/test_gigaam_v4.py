from pathlib import Path
from types import SimpleNamespace

import pytest

from console import downloader, engine, gigaam_v4_worker
from console.catalog import HEADS, head_directory, is_downloaded
from console.errors import ApiError
from console.model_assets import GIGAAM_MULTILINGUAL_V2, GIGAAM_V4, GIGAAM_V4_CTC, alternate_assets
from console.settings import Settings
from console.state import EngineConfig
from conftest import wav_bytes


@pytest.mark.parametrize(("variant", "repo", "revision"), [
    (GIGAAM_V4, "GigaAM-v4", "180301a"),
    (GIGAAM_V4_CTC, "GigaAM-v4", "5b81216"),
    (GIGAAM_MULTILINGUAL_V2, "GigaAM-Multilingual-v2", "c9d7aee"),
])
async def test_gigaam_downloads_pinned_assets_in_its_own_directory(monkeypatch, tmp_path, variant, repo, revision):
    captured = []

    async def capture(targets, on_event):
        captured.extend(targets)

    settings = Settings(_env_file=None, model_dir=tmp_path)
    monkeypatch.setattr(downloader, "download_assets", capture)
    await downloader.download(settings, variant, lambda event: None)

    directory = head_directory(variant, tmp_path)
    assert directory == tmp_path / variant
    directory.mkdir()
    assert tuple(asset.name for _, asset in captured) == HEADS[variant].files
    if variant == GIGAAM_V4_CTC:
        assert set(HEADS[variant].files) == {
            "model.safetensors", "config.json", "modeling_gigaam.py", "vad.safetensors", "vad_config.json",
        }
    for parent, asset in captured:
        assert parent == directory
        assert asset.url.startswith(f"https://huggingface.co/ai-sage/{repo}/resolve/{revision}")
        (directory / asset.name).touch()
    assert not is_downloaded(variant, tmp_path)
    monkeypatch.setattr("console.catalog.has_weight", lambda path, size=None: path.is_file())
    assert is_downloaded(variant, tmp_path)
    (directory / "vad.safetensors").unlink()
    assert not is_downloaded(variant, tmp_path)


@pytest.mark.parametrize("variant", [GIGAAM_V4, GIGAAM_V4_CTC, GIGAAM_MULTILINGUAL_V2])
def test_gigaam_v4_uses_its_cpu_worker(monkeypatch, tmp_path, variant):
    monkeypatch.setattr(engine.shutil, "which", lambda name: name)
    monkeypatch.setattr(engine, "find_spec", lambda name: object())
    settings = Settings(_env_file=None, model_dir=tmp_path, max_upload_mb=96, gigaam_v4_python="/opt/gigaam-v4/bin/python")
    config = EngineConfig(variant=variant, alternate_threads=6)
    command = engine.build_argv(settings, config, alternate_port=9901)
    assert command == [
        settings.gigaam_v4_python, "-m", "console.gigaam_v4_worker", "9901",
        str(tmp_path / variant), "6", "96", variant,
    ]


@pytest.mark.parametrize(("seconds", "expected"), [(0, None), (30, "short"), (31, "long")])
def test_gigaam_v4_splits_only_long_audio(monkeypatch, tmp_path: Path, seconds, expected):
    calls = []

    def recognize(name, path, **kwargs):
        calls.append((name, path, kwargs))
        word = SimpleNamespace(text="Камертон", start=0.2, end=0.7)
        return {"e2e": SimpleNamespace(text="Камертон.", words=[word])}

    model = SimpleNamespace(
        transcribe=lambda path, **kw: recognize("short", path, **kw),
        transcribe_longform=lambda path, **kw: recognize("long", path, **kw),
    )
    monkeypatch.setattr(gigaam_v4_worker, "load_model", lambda path, threads, variant: (model, 480000))
    worker = gigaam_v4_worker.GigaAM(tmp_path, 3, GIGAAM_V4)
    audio = tmp_path / "audio.wav"
    audio.write_bytes(wav_bytes(seconds))

    result = worker.recognize(audio, "ru")
    if expected is None:
        assert result == {"text": "", "words": []}
        assert calls == []
    else:
        arguments = {"word_timestamps": True}
        if expected == "long":
            arguments.update(fr_batch_size=1, vad_batch_size=1)
        assert calls == [(expected, str(audio), arguments)]
        assert result == {"text": "Камертон.", "words": [{"word": "Камертон", "start": 0.2, "end": 0.7}]}


@pytest.mark.parametrize(("language", "seconds"), [("kk", 5), ("auto", 31)])
def test_multilingual_passes_language_to_short_and_long_inference(monkeypatch, tmp_path, language, seconds):
    calls = []

    def recognize(path, **options):
        calls.append(options["language"])
        return {"e2e": SimpleNamespace(text="Сәлем.", words=[])}

    model = SimpleNamespace(transcribe=recognize, transcribe_longform=recognize)
    monkeypatch.setattr(gigaam_v4_worker, "load_model", lambda path, threads, variant: (model, 480000))
    worker = gigaam_v4_worker.GigaAM(tmp_path, 3, GIGAAM_MULTILINGUAL_V2)
    audio = tmp_path / "audio.wav"
    audio.write_bytes(wav_bytes(seconds))

    assert worker.recognize(audio, language)["text"] == "Сәлем."
    assert calls == [language]
    with pytest.raises(ApiError, match="не поддерживает"):
        worker.recognize(audio, "ja")
