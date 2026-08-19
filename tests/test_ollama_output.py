from core.ollama_output import OllamaOutputProcessor


def messages(processor: OllamaOutputProcessor, chunks: list[str]) -> str:
    output: list[str] = []
    for index, chunk in enumerate(chunks, start=1):
        event = processor.feed(chunk, now=float(index))
        if event:
            output.append(event.message)
    final = processor.flush(now=100)
    if final:
        output.append(final.message)
    return "".join(output)


def test_partial_ansi_sequences_and_ollama_prompt_are_removed():
    processor = OllamaOutputProcessor()
    processor.feed("\x1b[?", now=1)
    processor.feed("25l\x1b[2K", now=2)
    processor.note_input("hello\n")

    result = messages(
        processor,
        [
            "\x1b[Khell\r\n... o\r\n",
            "\x1b[1G\x1b[2KHello! How can I help you?\r\n\r\n",
            ">>> Send a message (/? for help)",
        ],
    )

    assert result.strip() == "Hello! How can I help you?"
    assert "\x1b" not in result
    assert ">>>" not in result
    assert "Send a message" not in result


def test_startup_prompt_race_does_not_leak_input_echo():
    processor = OllamaOutputProcessor()
    processor.note_input("hello\n")

    result = messages(
        processor,
        [
            "\x1b[2K\x1b[1G>>> Send a message (/? for help)",
            "\x1b[Khell\r\n... o\r\n\x1b[2K\x1b[1GHello!\r\n",
        ],
    )

    assert result.strip() == "Hello!"
    assert "... o" not in result


def test_explicit_thinking_tags_are_filtered_without_removing_markdown():
    processor = OllamaOutputProcessor()
    processor.note_input("What is Docker?\n")

    result = messages(
        processor,
        [
            "\x1b[2K\x1b[1G<think>private reasoning",
            "</think>\n## Docker\n\n- Portable\n- Reproducible\n",
        ],
    )

    assert "private reasoning" not in result
    assert "## Docker" in result
    assert "- Portable" in result
    assert "- Reproducible" in result


def test_partial_model_words_are_coalesced_without_corruption():
    processor = OllamaOutputProcessor()
    processor.feed("prompt\n", now=10)
    processor.note_input("hello\n")

    first = processor.feed("\x1b[2K\x1b[1GHello", now=10.01)
    second = processor.feed(", how can I help?", now=10.02)
    final = processor.flush(now=11)

    assert first is None or first.message == ""
    assert second is None or second.message == ""
    assert final is not None
    assert final.message == "Hello, how can I help?"
