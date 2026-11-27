"""Весовые файлы дополнительных CPU-движков."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Asset:
    base: str
    name: str
    size: int
    sha256: str

    @property
    def url(self) -> str:
        return f"{self.base}/{self.name}"


WHISPER = "https://huggingface.co/ggerganov/whisper.cpp/resolve/5359861c739e955e79d9a303bcbc70fb988958b1"
PARAKEET = "https://huggingface.co/mudler/parakeet-cpp-gguf/resolve/07a08a3a405d20c5434b9a1442f6e6cf571f57ad"
T_ONE = "https://huggingface.co/csukuangfj/sherpa-onnx-streaming-t-one-russian-2025-09-08/resolve/9d63341e0f2d8a8b2edaa825aa1fcfe3c5283b47"
RUPUNCT = "https://huggingface.co/ekhodzitsky/rupunct-small-onnx/resolve/c4a35be7e4a413cdfb08427db75b621b571569c9"
GIGAAM_V4 = "gigaam_v4_rnnt"
GIGAAM_V4_CTC = "gigaam_v4_ctc"
GIGAAM_MULTILINGUAL_V2 = "gigaam_multilingual_v2_rnnt"
GIGAAM_V4_HF = "https://huggingface.co/ai-sage/GigaAM-v4/resolve/180301a192bb45bc2b2ca122e0d4aab24ffe7a96"
GIGAAM_V4_CTC_HF = "https://huggingface.co/ai-sage/GigaAM-v4/resolve/5b81216afa29c8b5a1a3e64c424c8416e18c1e5b"
GIGAAM_MULTILINGUAL_V2_HF = "https://huggingface.co/ai-sage/GigaAM-Multilingual-v2/resolve/c9d7aee4afe99fcc50064ac3ebab35d7db6fbc36"


def _gigaam_v4_common(base: str) -> tuple[Asset, ...]:
    return (
        Asset(base, "vad.safetensors", 5378188, "fd8dfeba717992416d7f76689977c4ae9e9cc99737c1853ed625355b9f2bf692"),
        Asset(base, "vad_config.json", 767, "a2668614c2e0f8385115b6676c10c4cc02eb105bec4b4982582c56838c4b1141"),
        Asset(base, "modeling_gigaam.py", 177771, "dc0b2b56e98c55dddcce2ec6400ea8df3958883a700c153a869577bcf4f52db8"),
    )


GIGAAM_V4_EXTRAS = (
    Asset(GIGAAM_V4_HF, "config.json", 2826, "05bc09964ee47e29c1e926ef01d70978e3d686d102f1ca0324067bead88682ca"),
    Asset(GIGAAM_V4_HF, "e2e_tokenizer.model", 14686, "f547bcb38e071694ef1ddb25d9d40c86b4ab88cd0b16ab9fd52f27dd52c48e39"),
    Asset(GIGAAM_V4_HF, "raw_tokenizer.model", 15374, "dcbe2598d1b374065091832970593a06065d498a43fbb1787de73e180d0556bc"),
    *_gigaam_v4_common(GIGAAM_V4_HF),
)
GIGAAM_V4_CTC_EXTRAS = (
    Asset(GIGAAM_V4_CTC_HF, "config.json", 5517, "e4fb0cf68ebe043cd456409352c311c8e946d3fc3a8dd3d7239925ba36020588"),
    *_gigaam_v4_common(GIGAAM_V4_CTC_HF),
)
GIGAAM_MULTILINGUAL_V2_EXTRAS = (
    Asset(GIGAAM_MULTILINGUAL_V2_HF, "config.json", 3561, "a5d0b02874ba2956558a43a230b74faa71ae4dc491c26b68caf4f6c3cc862dda"),
    Asset(GIGAAM_MULTILINGUAL_V2_HF, "e2e_tokenizer.model", 54214, "3b049685e51a893350452f31613b47f4bd7640857f53facdf32266de82df3c0a"),
    Asset(GIGAAM_MULTILINGUAL_V2_HF, "raw_tokenizer.model", 26877, "c51fe228b747218891e3facdaeda12957065f4238452c377f38f76d3c2d4c423"),
    Asset(GIGAAM_MULTILINGUAL_V2_HF, "vad.safetensors", 5378188, "fd8dfeba717992416d7f76689977c4ae9e9cc99737c1853ed625355b9f2bf692"),
    Asset(GIGAAM_MULTILINGUAL_V2_HF, "vad_config.json", 767, "a2668614c2e0f8385115b6676c10c4cc02eb105bec4b4982582c56838c4b1141"),
    Asset(GIGAAM_MULTILINGUAL_V2_HF, "modeling_gigaam.py", 177679, "8d3f50834b60fe515d02232345314df083f9527910fb6e45fb5c4bd0f089c7a1"),
)

T_ONE_EXTRAS = (
    Asset(T_ONE, "tokens.txt", 202, "27f7b3ba2096c572375fba1a6b29af1f80d86e08a329940612908112695f97e0"),
    Asset(RUPUNCT, "rupunct_small_int8.onnx", 29259673, "b105da023474d98aa13ba18953ae67b04b17bd0595034bc06030c17536893933"),
    Asset(RUPUNCT, "tokenizer.json", 2413439, "7ca617388c2092a3a84272025c52bbf3c6db0aee225c0351186295c0b5d3ddc6"),
    Asset(RUPUNCT, "config.json", 2527, "6924a8cf41ec2bd3a3aa73a387ae0ccd0aed253ec7cac4d2f53c7d27440891eb"),
)

ALTERNATE_ASSETS = {
    GIGAAM_V4: Asset(GIGAAM_V4_HF, "model.safetensors", 486276070,
        "2c38690c38edbd9dfc2190f1a2dacdcfbea2a692078457fc145a6034c031840a"),
    GIGAAM_V4_CTC: Asset(GIGAAM_V4_CTC_HF, "model.safetensors", 472290154,
        "f82cd5d3ef5158ac0318a21c207129da04040a191ca1c49078192826e3c01eed"),
    GIGAAM_MULTILINGUAL_V2: Asset(GIGAAM_MULTILINGUAL_V2_HF, "model.safetensors", 1574765402,
        "1ea6b24faa308791b02e6916450a63b2a2ff401a7d890e08deaf34fc2acfe869"),
    "whisper_tiny": Asset(WHISPER, "ggml-tiny.bin", 77691713,
        "be07e048e1e599ad46341c8d2a135645097a538221678b7acdd1b1919c6e1b21"),
    "whisper_small": Asset(WHISPER, "ggml-small.bin", 487601967,
        "1be3a9b2063867b937e64e2ec7483364a79917e157fa98c5d94b5c1fffea987b"),
    "whisper_large_v3_turbo": Asset(WHISPER, "ggml-large-v3-turbo-q5_0.bin", 574041195,
        "394221709cd5ad1f40c46e6031ca61bce88931e6e088c188294c6d5a55ffa7e2"),
    "whisper_large_v3": Asset(WHISPER, "ggml-large-v3-q5_0.bin", 1081140203,
        "d75795ecff3f83b5faa89d1900604ad8c780abd5739fae406de19f23ecd98ad1"),
    "parakeet_tdt_v3": Asset(PARAKEET, "tdt-0.6b-v3-q8_0.gguf", 940663680,
        "4d69a4a6683f4f2d952bad794c1357ca6eb628027695b4699c5a9ad4cd07d757"),
    "parakeet_ultra": Asset(PARAKEET, "ultra-q8_0.gguf", 941517728,
        "c2fb452a9df468a141012b01c8c168a25ce93f710897c7de6e353c6cc250986a"),
    "nemotron_35_asr": Asset(PARAKEET, "nemotron-3.5-asr-streaming-0.6b-q8_0.gguf", 983696512,
        "ba2f13eccd4a5245be728f77e6149bd6a4fdcdd133ff2e08ac6005bcef7a99f1"),
    "t_one": Asset(T_ONE, "model.onnx", 144193702,
        "5ded080e2a6c86ecc11bcb0902d77524eb3e8b0844cb0c0754347f5aafb4dabc"),
}

_EXTRAS = {
    GIGAAM_V4: GIGAAM_V4_EXTRAS,
    GIGAAM_V4_CTC: GIGAAM_V4_CTC_EXTRAS,
    GIGAAM_MULTILINGUAL_V2: GIGAAM_MULTILINGUAL_V2_EXTRAS,
    "t_one": T_ONE_EXTRAS,
}


def alternate_assets(variant: str) -> tuple[Asset, ...]:
    return (ALTERNATE_ASSETS[variant], *_EXTRAS.get(variant, ()))


SILERO = Asset(PARAKEET, "silero-vad-f16.gguf", 1264928,
    "8160489282352accc0e95925c2f6bf3d76fb8f7bccdce5c7e46808cb15e8443c")
DIARIZATION = Asset(PARAKEET, "nemotron-3-diarization-f16.gguf", 200715584,
    "3dca41a92162af6edf96276c4d2c397b034b55abf9eb2662a58cc7bc8c872683")
