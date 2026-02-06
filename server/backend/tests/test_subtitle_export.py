"""Tests for subtitle export cue building and rendering."""

from server.core.subtitle_export import (
    MAX_CUE_DURATION,
    SubtitleCue,
    build_subtitle_cues,
    normalize_speaker_labels,
    render_ass,
    render_srt,
)


def test_word_only_cues_split_for_readability() -> None:
    segments = [
        {
            "id": 1,
            "segment_index": 0,
            "speaker": None,
            "start_time": 0.0,
            "end_time": 6.0,
            "text": "",
        }
    ]
    words = [
        {"segment_id": 1, "word": "This", "start_time": 0.0, "end_time": 0.2},
        {"segment_id": 1, "word": "is", "start_time": 0.2, "end_time": 0.4},
        {"segment_id": 1, "word": "a", "start_time": 0.4, "end_time": 0.6},
        {"segment_id": 1, "word": "subtitle", "start_time": 0.6, "end_time": 0.9},
        {"segment_id": 1, "word": "readability", "start_time": 0.9, "end_time": 1.2},
        {"segment_id": 1, "word": "check.", "start_time": 1.2, "end_time": 1.6},
        {"segment_id": 1, "word": "Second", "start_time": 2.8, "end_time": 3.1},
        {"segment_id": 1, "word": "cue", "start_time": 3.1, "end_time": 3.3},
        {"segment_id": 1, "word": "starts", "start_time": 3.3, "end_time": 3.6},
        {"segment_id": 1, "word": "here.", "start_time": 3.6, "end_time": 3.9},
    ]

    cues = build_subtitle_cues(segments, words, has_diarization=False)

    assert len(cues) >= 2
    assert all("Speaker " not in cue.text for cue in cues)
    assert all((cue.end - cue.start) <= MAX_CUE_DURATION for cue in cues)


def test_diarization_labels_normalize_by_first_appearance() -> None:
    labels = ["SPEAKER_11", "SPEAKER_03", "SPEAKER_11", "SPEAKER_08"]
    mapping = normalize_speaker_labels(labels)
    assert mapping == {
        "SPEAKER_11": "Speaker 1",
        "SPEAKER_03": "Speaker 2",
        "SPEAKER_08": "Speaker 3",
    }

    segments = [
        {
            "id": 10,
            "segment_index": 0,
            "speaker": "SPEAKER_11",
            "start_time": 0.0,
            "end_time": 1.0,
            "text": "hello",
        },
        {
            "id": 20,
            "segment_index": 1,
            "speaker": "SPEAKER_03",
            "start_time": 1.0,
            "end_time": 2.0,
            "text": "world",
        },
    ]
    words = [
        {"segment_id": 10, "word": "Hello", "start_time": 0.0, "end_time": 0.6},
        {"segment_id": 20, "word": "world", "start_time": 1.1, "end_time": 1.6},
    ]

    cues = build_subtitle_cues(segments, words, has_diarization=True)

    assert cues[0].speaker == "Speaker 1"
    assert cues[0].text.startswith("Speaker 1:")
    assert cues[1].speaker == "Speaker 2"
    assert cues[1].text.startswith("Speaker 2:")


def test_render_srt_timestamp_formatting() -> None:
    cues = [SubtitleCue(start=1.234, end=62.5, text="Hello", speaker=None)]
    output = render_srt(cues)

    assert "00:00:01,234 --> 00:01:02,500" in output
    assert output.startswith("1\n")


def test_render_ass_contains_required_sections_and_dialogues() -> None:
    cues = [
        SubtitleCue(
            start=0.0,
            end=1.5,
            text="Speaker 1: line one\n{line two}\\final",
            speaker="Speaker 1",
        )
    ]
    output = render_ass(cues, title="Test Export")

    assert "[Script Info]" in output
    assert "[V4+ Styles]" in output
    assert "[Events]" in output
    assert "Dialogue: 0,0:00:00.00,0:00:01.50,Default" in output
    assert r"\N" in output
    assert r"\{" in output
    assert r"\\final" in output


def test_cue_split_on_punctuation() -> None:
    segments = [{"id": 1, "segment_index": 0, "speaker": None}]
    words = [
        {"segment_id": 1, "word": "Hello", "start_time": 0.0, "end_time": 0.4},
        {"segment_id": 1, "word": "there.", "start_time": 0.4, "end_time": 1.3},
        {"segment_id": 1, "word": "Next", "start_time": 1.31, "end_time": 1.6},
    ]

    cues = build_subtitle_cues(segments, words, has_diarization=False)

    assert len(cues) == 2
    assert cues[0].text.endswith("there.")
    assert cues[1].text == "Next"


def test_cue_split_on_long_gap() -> None:
    segments = [{"id": 1, "segment_index": 0, "speaker": None}]
    words = [
        {"segment_id": 1, "word": "Alpha", "start_time": 0.0, "end_time": 0.4},
        {"segment_id": 1, "word": "beta", "start_time": 0.4, "end_time": 0.9},
        {"segment_id": 1, "word": "gamma", "start_time": 2.1, "end_time": 2.4},
    ]

    cues = build_subtitle_cues(segments, words, has_diarization=False)

    assert len(cues) == 2
    assert cues[0].text == "Alpha beta"
    assert cues[1].text == "gamma"


def test_cue_split_on_max_duration() -> None:
    segments = [{"id": 1, "segment_index": 0, "speaker": None}]
    words = []
    for i in range(12):
        start = i * 0.55
        words.append(
            {
                "segment_id": 1,
                "word": f"w{i}",
                "start_time": start,
                "end_time": start + 0.3,
            }
        )

    cues = build_subtitle_cues(segments, words, has_diarization=False)

    assert len(cues) >= 2
    assert max(cue.end - cue.start for cue in cues) <= MAX_CUE_DURATION


def test_cue_split_on_max_chars() -> None:
    segments = [{"id": 1, "segment_index": 0, "speaker": None}]
    words = [
        {
            "segment_id": 1,
            "word": f"token{i}_abcdefghij",
            "start_time": i * 0.2,
            "end_time": i * 0.2 + 0.18,
        }
        for i in range(12)
    ]

    cues = build_subtitle_cues(segments, words, has_diarization=False)

    assert len(cues) >= 2


def test_degenerate_timestamps_are_normalized() -> None:
    segments = [
        {
            "id": 1,
            "segment_index": 0,
            "speaker": None,
            "start_time": -3.0,
            "end_time": -3.0,
            "text": "fallback",
        }
    ]
    words = [
        {"segment_id": 1, "word": "Bad", "start_time": -2.0, "end_time": -3.0},
        {"segment_id": 1, "word": "times", "start_time": -1.5, "end_time": -1.5},
    ]

    cues = build_subtitle_cues(segments, words, has_diarization=False)

    assert cues
    assert all(cue.start >= 0.0 for cue in cues)
    assert all(cue.end > cue.start for cue in cues)
