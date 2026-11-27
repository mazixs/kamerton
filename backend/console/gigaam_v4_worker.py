"""Изолированный CPU-процесс для GigaAM v4 и Multilingual v2 с весами safetensors."""

import hashlib
import sys
import wave
from pathlib import Path
from types import ModuleType

import uvicorn

from .catalog import HEADS
from .downloader import matches_asset
from .errors import ApiError
from .model_assets import GIGAAM_MULTILINGUAL_V2, GIGAAM_V4, alternate_assets
from .parakeet_worker import create_worker
from .settings import Settings


def load_model(directory: Path, threads: int, variant: str):
    assets = alternate_assets(variant)
    code = next(asset for asset in assets if asset.name == "modeling_gigaam.py")
    for asset in assets:
        if not matches_asset(directory / asset.name, asset.size, asset.sha256):
            raise RuntimeError(f"Поврежден файл модели: {asset.name}")

    path = directory / code.name
    source = path.read_bytes()
    if hashlib.sha256(source).hexdigest() != code.sha256:
        raise RuntimeError("Поврежден код модели GigaAM.")
    module = ModuleType("_kamerton_gigaam")
    module.__file__ = str(path)
    sys.modules[module.__name__] = module
    exec(compile(source, str(path), "exec"), module.__dict__)

    module.torch.set_num_threads(threads)
    module.torch.set_num_interop_threads(1)
    model = module.GigaAMModel.from_pretrained(
        str(directory), device="cpu", local_files_only=True, use_safetensors=True,
    )
    return model.eval(), module.LONGFORM_THRESHOLD


class GigaAM:
    default_language = "auto"

    def __init__(self, directory: Path, threads: int, variant: str) -> None:
        self.directory = directory
        self.languages = HEADS[variant].languages
        self.condition_language = variant == GIGAAM_MULTILINGUAL_V2
        self.model, self.short_limit = load_model(directory, threads, variant)

    def recognize(self, wav: Path, language: str) -> dict:
        if language != self.default_language and language not in self.languages:
            raise ApiError(400, "Выбранная модель GigaAM не поддерживает этот язык.", "unsupported_language")
        with wave.open(str(wav), "rb") as audio:
            frames = audio.getnframes()
        if frames < 320:
            return {"text": "", "words": []}
        options = {"language": language} if self.condition_language else {}
        if frames <= self.short_limit:
            result = self.model.transcribe(str(wav), word_timestamps=True, **options)["e2e"]
        else:
            result = self.model.transcribe_longform(
                str(wav), word_timestamps=True, fr_batch_size=1, vad_batch_size=1, **options,
            )["e2e"]
        return {
            "text": result.text,
            "words": [
                {"word": word.text, "start": word.start, "end": word.end}
                for word in result.words or ()
            ],
        }


def main() -> None:
    port, directory, threads, max_upload_mb, *variant_args = sys.argv[1:]
    variant, = variant_args or [GIGAAM_V4]
    settings = Settings(_env_file=None, max_upload_mb=int(max_upload_mb))
    worker = create_worker(GigaAM(Path(directory), int(threads), variant), settings)
    uvicorn.run(worker, host="127.0.0.1", port=int(port), access_log=False, timeout_graceful_shutdown=2)


if __name__ == "__main__":
    main()
