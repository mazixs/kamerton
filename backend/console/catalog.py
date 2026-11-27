"""Speech-recognition model catalog and installed asset layout.

The file lists come from the engine's INT8 layout. The pinned October package
has its own download source and directory to keep the two revisions separate.

`size_mb` is what the files actually weigh on disk after `gigastt download`,
measured rather than copied from upstream's docs: the figures we had inherited
overstated `ml_ctc_large` by 56 MB, which is the one number a user checks before
deciding to wait for it.

Тексты карточек хранятся на двух языках: интерфейс по умолчанию английский,
русский включается переключателем. Идентификаторы голов, названия моделей и
технические термины не переводятся - переводятся только пояснения.

Значки (`badge`) ставятся по нашему собственному замеру, а не по внешним
лидербордам, и на то есть причина. В лидерборде Шмырева GigaAM v3 нет вовсе -
таблица последний раз обновлялась 14.09.2025. Мультиязычный трек HF Open ASR
Leaderboard русского не содержит, поэтому назвать голову "лучшей мультиязычной"
по нему нельзя. Таблица разработчика - заявление производителя. Остается наш
замер, и подпись значка честно называет его своим.
"""

from dataclasses import dataclass
from pathlib import Path
from stat import S_ISREG

from .model_assets import ALTERNATE_ASSETS, GIGAAM_MULTILINGUAL_V2, GIGAAM_V4, GIGAAM_V4_CTC, SILERO, alternate_assets


# Языки интерфейса. Английский первый и он же запасной: если перевода нет,
# показывается английский, а не пустое место.
LANGS = ("en", "ru")
DEFAULT_LANG = "en"
OCTOBER_E2E = "e2e_rnnt_2026_10_09"
OCTOBER_E2E_RELEASE = "https://github.com/ekhodzitsky/gigastt/releases/download/models-v3-2026-10-09"
OCTOBER_E2E_ASSETS = {
    "v3_e2e_rnnt_encoder_int8.onnx": (319665270, "16805903b102d8b27bb0253de044f25e33a8a5bf07fce0c4da4ac1a5a7544091"),
    "v3_e2e_rnnt_decoder.onnx": (4599910, "7b0a16d67fd2cb37061decc93c69e364a9ab27afee3c57495d55b1c974cf7231"),
    "v3_e2e_rnnt_joint.onnx": (2712896, "602ff7017a93311aad34df1437c8d7f49911353c13d6eae7a6ee7b041339465c"),
    "v3_e2e_rnnt_vocab.txt": (13354, "39abae20e692998290c574e606f11a9edef2902a1995463fcff63d1490cf22b7"),
}


def pick(texts: dict[str, str] | None, lang: str) -> str | None:
    """Строка на запрошенном языке, с откатом на английский."""
    if not texts:
        return None
    return texts.get(lang) or texts.get(DEFAULT_LANG)


@dataclass(frozen=True)
class Head:
    id: str
    title: str
    # Пояснения хранятся по языкам: {"en": ..., "ru": ...}.
    subtitle: dict[str, str]
    languages: tuple[str, ...]
    native_punctuation: bool
    size_mb: int
    files: tuple[str, ...]
    # Значок на карточке и подсказка к нему. Умолчания - чтобы не трогать порядок
    # позиционных полей у голов без значка.
    badge: dict[str, str] | None = None
    badge_note: dict[str, str] | None = None
    runtime: str = "gigastt"


HEADS: dict[str, Head] = {
    "rnnt": Head(
        id="rnnt",
        title="GigaAM v3 RNN-T",
        subtitle={
            "en": "Russian speech, lowercase Cyrillic. By default a separate pass adds punctuation "
            "and converts number words to digits.",
            "ru": "Русская речь, строчная кириллица. По умолчанию отдельная обработка расставляет "
            "знаки препинания и записывает числа цифрами.",
        },
        languages=("ru",),
        native_punctuation=False,
        size_mb=219,
        files=(
            "v3_rnnt_encoder_int8.onnx",
            "v3_rnnt_decoder.onnx",
            "v3_rnnt_joint.onnx",
            "v3_vocab.txt",
        ),
    ),
    "e2e_rnnt": Head(
        id="e2e_rnnt",
        title="GigaAM v3 RNN-T end-to-end (2026-06-22)",
        subtitle={
            "en": "Writes Russian with punctuation, capitals and digits without a separate pass. "
            "Its vocabulary also includes Latin letters and hyphens for names and terms.",
            "ru": "Записывает русскую речь со знаками препинания, заглавными буквами и цифрами "
            "без отдельной обработки. Для имён и терминов в словаре есть латиница и дефис.",
        },
        languages=("ru",),
        native_punctuation=True,
        size_mb=222,
        files=tuple(OCTOBER_E2E_ASSETS),
        badge={"en": "low error on FLEURS ru", "ru": "низкая ошибка на FLEURS ru"},
        badge_note={
            "en": "Our own measurement, 11.08.2026: WER 4.32% on FLEURS ru against 6.56% "
            "for rnnt and 6.25% for ml_ctc_large; on live dictation without fillers, "
            "4.09% against Soniox. Details in docs/research/head-choice-and-wer.md",
            "ru": "Это наш замер 11.08.2026: WER 4.32% на FLEURS ru против 6.56% у rnnt "
            "и 6.25% у ml_ctc_large; на живой диктовке без междометий 4.09% против Soniox. "
            "Подробности - docs/research/head-choice-and-wer.md",
        },
    ),
    OCTOBER_E2E: Head(
        id=OCTOBER_E2E,
        title="GigaAM v3 RNN-T end-to-end (2026-10-09)",
        subtitle={
            "en": "Russian speech with punctuation, capitals and digits. Uses the October INT8 encoder, "
            "which requires more disk space and memory than the June edition.",
            "ru": "Русская речь со знаками препинания, заглавными буквами и цифрами. "
            "Октябрьский INT8-энкодер занимает больше места на диске и требует больше памяти, чем июньский.",
        },
        languages=("ru",),
        native_punctuation=True,
        size_mb=312,
        files=tuple(OCTOBER_E2E_ASSETS),
    ),
    "ml_ctc": Head(
        id="ml_ctc",
        title="GigaAM Multilingual CTC",
        subtitle={
            "en": "First-generation Multilingual, five languages. Outputs lowercase letters; "
            "separate punctuation and number formatting are off in Auto mode.",
            "ru": "Первое поколение Multilingual, пять языков. Пишет строчными буквами. "
            "В режиме «Авто» отдельное оформление пунктуации и чисел выключено.",
        },
        languages=("ru", "en", "kk", "ky", "uz"),
        native_punctuation=False,
        size_mb=214,
        files=("multilingual_ctc.int8.onnx", "multilingual_vocab.txt"),
    ),
    "ml_ctc_large": Head(
        id="ml_ctc_large",
        title="GigaAM Multilingual CTC Large",
        subtitle={
            "en": "The larger first-generation Multilingual model (600M parameters, five languages). "
            "Like the smaller variant, it outputs lowercase letters by default.",
            "ru": "Увеличенная модель первого поколения Multilingual, 600 млн параметров и пять языков. "
            "Как и младшая версия, по умолчанию пишет строчными буквами.",
        },
        languages=("ru", "en", "kk", "ky", "uz"),
        native_punctuation=False,
        size_mb=564,
        files=("multilingual_large_ctc.int8.onnx", "multilingual_vocab.txt"),
        badge={"en": "larger memory footprint", "ru": "требует больше памяти"},
        badge_note={
            "en": "Our own measurement on first startup: 2,538 MiB peak for ml_ctc_large, "
            "1,078 MiB for e2e_rnnt. These are peak values, not steady-state usage.",
            "ru": "Это наш замер пика памяти при первом запуске: 2 538 МиБ у ml_ctc_large "
            "и 1 078 МиБ у e2e_rnnt. После загрузки расход памяти ниже.",
        },
    ),
}

_ADDITIONAL_HEADS = {
    GIGAAM_V4: (
        "GigaAM v4 RNN-T", "gigaam_v4", "Russian and English with built-in formatting.",
        "Русский и английский, со встроенной пунктуацией и нормализацией чисел.",
    ),
    GIGAAM_V4_CTC: (
        "GigaAM v4 CTC", "gigaam_v4", "Character-level CTC. Russian and English with built-in formatting.",
        "Посимвольная CTC. Русский и английский, со встроенной пунктуацией и нормализацией чисел.",
    ),
    GIGAAM_MULTILINGUAL_V2: (
        "GigaAM Multilingual v2 RNN-T", "gigaam_v4",
        "21 languages with language detection and built-in text formatting.",
        "21 язык с автоопределением и встроенным форматированием текста.",
    ),
    "whisper_tiny": ("Whisper Tiny", "whisper", "Multilingual, 39M parameters.", "Многоязычная модель, 39 млн параметров."),
    "whisper_small": ("Whisper Small", "whisper", "Multilingual, 244M parameters.", "Многоязычная модель, 244 млн параметров."),
    "whisper_large_v3_turbo": (
        "Whisper Large V3 Turbo (Q5_0)", "whisper", "Faster multilingual decoder.",
        "Многоязычная модель с ускоренным декодером.",
    ),
    "whisper_large_v3": (
        "Whisper Large V3 (Q5_0)", "whisper", "Multilingual, highest-capacity Whisper in this catalog.",
        "Многоязычная модель Whisper, 1,55 млрд параметров.",
    ),
    "parakeet_tdt_v3": (
        "Parakeet TDT 0.6B V3 (Q8_0)", "parakeet", "25 languages, including Russian and English.",
        "25 языков, включая русский и английский.",
    ),
    "parakeet_ultra": (
        "Moondream Parakeet Ultra (Q8_0)", "parakeet", "Moondream's fine-tuned Parakeet TDT V3.",
        "Вариант Parakeet TDT V3 с дополнительным обучением от Moondream.",
    ),
    "nemotron_35_asr": (
        "Nemotron 3.5 ASR Streaming 0.6B (Q8_0)", "parakeet", "Cache-aware processing for speech in Russian and English.",
        "Потоковый движок с поддержкой русского и английского.",
    ),
    "t_one": (
        "T-one Russian", "sherpa", "Russian CTC model for telephony with separate punctuation.",
        "Русская CTC-модель для телефонной речи с отдельной пунктуацией.",
    ),
}

_ADDITIONAL_LANGUAGES = {
    GIGAAM_MULTILINGUAL_V2: (
        "ru", "en", "kk", "ky", "uz", "be", "fr", "es", "ba", "ka", "hy",
        "ro", "tk", "az", "tg", "de", "it", "nl", "pl", "pt", "tt",
    ),
    "t_one": ("ru",),
}

for variant, (title, runtime, en, ru) in _ADDITIONAL_HEADS.items():
    files = alternate_assets(variant)
    HEADS[variant] = Head(
        variant, title, {"en": en, "ru": ru}, _ADDITIONAL_LANGUAGES.get(variant, ("ru", "en")),
        variant != "t_one", round(sum(file.size for file in files) / 2**20),
        tuple(file.name for file in files), runtime=runtime,
    )

_OPENAI_IDS = {
    GIGAAM_V4: "gigaam-v4-rnnt",
    GIGAAM_V4_CTC: "gigaam-v4-ctc",
    GIGAAM_MULTILINGUAL_V2: "gigaam-multilingual-v2-rnnt",
    "rnnt": "gigaam-v3-rnnt",
    "e2e_rnnt": "gigaam-v3-e2e-rnnt",
    "ml_ctc": "gigaam-multilingual-ctc",
    "ml_ctc_large": "gigaam-multilingual-large-ctc",
}


PUBLIC_MODEL_ID = "kamerton"


def openai_model_id(head_id: str) -> str:
    """Историческое клиентское имя головы (до появления `kamerton`)."""
    return _OPENAI_IDS.get(head_id, head_id)


def engine_head_id(head_id: str) -> str:
    return "e2e_rnnt" if head_id == OCTOBER_E2E else head_id


def head_directory(head_id: str, model_dir: Path) -> Path:
    return model_dir / head_id if head_id == OCTOBER_E2E or head_id in ALTERNATE_ASSETS else model_dir


def has_weight(path: Path, expected: int | None = None) -> bool:
    try:
        info = path.stat()
    except OSError:
        return False
    return S_ISREG(info.st_mode) and (info.st_size == expected if expected is not None else info.st_size > 0)


def is_downloaded(head_id: str, model_dir: Path) -> bool:
    head = HEADS.get(head_id)
    if head is None:
        return False
    if head_id in ALTERNATE_ASSETS:
        directory = head_directory(head_id, model_dir)
        if not all(has_weight(directory / asset.name, asset.size) for asset in alternate_assets(head_id)):
            return False
        if head.runtime == "parakeet" and head_id != "nemotron_35_asr":
            return has_weight(model_dir / SILERO.name, SILERO.size)
        return True
    if head_id == OCTOBER_E2E:
        return all(
            has_weight(head_directory(head_id, model_dir) / name, size)
            for name, (size, _) in OCTOBER_E2E_ASSETS.items()
        )
    return all(
        has_weight(model_dir / name)
        for name in head.files
    )
