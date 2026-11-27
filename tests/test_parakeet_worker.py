from console.parakeet_worker import ctc_words, speaker_utterances


def test_diarization_reads_native_words_and_groups_adjacent_turns():
    words = [
        {"w": "Один", "start": 0.1, "end": 0.4},
        {"w": "два.", "start": 0.5, "end": 0.7},
        {"w": "Три.", "start": 0.95, "end": 1.2},
        {"word": "Дальше.", "start": 2.0, "end": 2.2},
    ]
    timeline = [
        {"speaker": 0, "start": 0.0, "end": 1.0},
        {"speaker": 1, "start": 0.9, "end": 1.5},
    ]
    segments = speaker_utterances(words, timeline)
    assert [(segment["speaker"], segment["text"]) for segment in segments] == [
        ("speaker_1", "Один два."),
        ("speaker_2", "Три."),
        ("unknown", "Дальше."),
    ]
    assert segments[0]["end"] == 0.7


def test_t_one_groups_timed_letters_and_clips_padding():
    words = ctc_words(["д", "а", " ", "н", "е", "т"], [0.1, 0.2, 0.3, 0.5, 0.6, 0.7], 0.75)
    assert [(word["word"], word["start"]) for word in words] == [("да", 0.1), ("нет", 0.5)]
    assert words[-1]["end"] == 0.75
