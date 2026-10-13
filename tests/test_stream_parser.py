from host.stream_parser import StreamParser
from host.telemetry_receiver import (
    FRAME_HEADER,
    FRAME_SIZE,
    calculate_crc16,
    validate_frame,
)
from test_telemetry_protocol import make_frame


def make_parser(max_text_line=128):
    return StreamParser(
        frame_header=FRAME_HEADER,
        frame_size=FRAME_SIZE,
        validator=validate_frame,
        max_text_line=max_text_line,
    )


# Tests that a complete valid telemetry frame is parsed successfully.
def test_single_frame():
    parser = make_parser()
    events = parser.feed(make_frame(sequence=7))

    frames = [event.data for event in events if event.kind == "frame"]
    assert len(frames) == 1
    assert validate_frame(frames[0])[0]


# Tests that a frame split across multiple reads is reconstructed correctly.
def test_frame_split_across_reads():
    parser = make_parser()
    frame = make_frame(sequence=8)

    assert parser.feed(frame[:5]) == []
    assert parser.feed(frame[5:13]) == []

    events = parser.feed(frame[13:])
    frames = [event.data for event in events if event.kind == "frame"]

    assert frames == [frame]


# Tests that multiple telemetry frames received together are parsed in order.
def test_multiple_frames_in_one_read():
    parser = make_parser()
    first = make_frame(sequence=1)
    second = make_frame(sequence=2)

    events = parser.feed(first + second)
    frames = [event.data for event in events if event.kind == "frame"]

    assert frames == [first, second]


# Tests that a newline-terminated text response is parsed correctly.
def test_text_response():
    parser = make_parser()

    events = parser.feed(b"STATUS,1000,1,NORMAL\r\n")

    assert [(event.kind, event.data) for event in events] == [
        ("text", "STATUS,1000,1,NORMAL")
    ]


# Tests that the parser reports and recovers from garbage before a valid frame.
def test_garbage_before_valid_frame_recovers():
    parser = make_parser()
    frame = make_frame(sequence=11)

    events = parser.feed(b"\x01\x02\x03" + frame)
    frames = [event.data for event in events if event.kind == "frame"]

    assert frames == [frame]
    assert any(event.kind == "error" for event in events)


# Tests that a corrupted frame is discarded and the following valid frame is recovered.
def test_corrupt_frame_followed_by_valid_frame_recovers():
    parser = make_parser()
    corrupt = bytearray(make_frame(sequence=10))
    corrupt[14] ^= 0x80
    good = make_frame(sequence=12)

    events = parser.feed(bytes(corrupt) + good)
    frames = [event.data for event in events if event.kind == "frame"]

    assert frames == [good]


# Tests that oversized unterminated input does not cause unbounded buffering.
def test_oversized_unterminated_input_is_bounded():
    parser = make_parser(max_text_line=32)

    events = parser.feed(b"x" * 4096)

    assert parser.buffered_bytes <= parser.max_buffer_size
    assert any(event.kind == "error" for event in events)


# Tests that resetting the parser discards an incomplete frame.
def test_reset_discards_partial_frame():
    parser = make_parser()
    frame = make_frame(sequence=14)

    assert parser.feed(frame[:10]) == []
    parser.reset()

    events = parser.feed(frame[10:])
    assert not any(event.kind == "frame" for event in events)


# Tests that a frame with an invalid CRC is rejected.
def test_invalid_crc_is_never_emitted_as_frame():
    parser = make_parser()
    frame = bytearray(make_frame(sequence=15))
    frame[-1] ^= 0x01

    events = parser.feed(frame)

    assert not any(event.kind == "frame" for event in events)
    assert any(event.kind == "error" for event in events)


# Tests that a frame is reconstructed correctly at every possible split boundary.
def test_frame_at_every_possible_split_boundary():
    frame = make_frame(sequence=21)

    for split in range(len(frame) + 1):
        parser = make_parser()
        events = parser.feed(frame[:split])
        events.extend(parser.feed(frame[split:]))

        frames = [
            event.data for event in events if event.kind == "frame"
        ]
        assert frames == [frame], f"Frame failed at split boundary {split}"


# Tests that a frame received one byte at a time is reconstructed correctly.
def test_frame_received_one_byte_at_a_time():
    parser = make_parser()
    frame = make_frame(sequence=22)
    events = []

    for byte in frame:
        events.extend(parser.feed(bytes([byte])))

    frames = [event.data for event in events if event.kind == "frame"]
    assert frames == [frame]


# Tests that a text response split across reads is reconstructed correctly.
def test_text_response_split_across_reads():
    parser = make_parser()

    assert parser.feed(b"STATUS,1000,") == []
    events = parser.feed(b"1,NORMAL\r\n")

    assert [(event.kind, event.data) for event in events] == [
        ("text", "STATUS,1000,1,NORMAL")
    ]


# Tests that a text response followed by a binary frame is parsed in order.
def test_text_and_binary_frame_back_to_back():
    parser = make_parser()
    response = b"STATUS,1000,1,NORMAL\r\n"
    frame = make_frame(sequence=23)

    events = parser.feed(response + frame)

    assert [(event.kind, event.data) for event in events] == [
        ("text", "STATUS,1000,1,NORMAL"),
        ("frame", frame),
    ]


# Tests that a false synchronization marker does not prevent recovery of a valid frame.
def test_false_sync_marker_before_valid_frame_recovers():
    parser = make_parser()
    false_candidate = b"\xAA\x55" + b"\x00" * 18
    valid_frame = make_frame(sequence=24)

    events = parser.feed(false_candidate + valid_frame)

    frames = [event.data for event in events if event.kind == "frame"]
    assert frames == [valid_frame]


# Tests that repeated malformed input does not cause the parser buffer to grow without limit.
def test_repeated_malformed_input_keeps_buffer_bounded():
    parser = make_parser(max_text_line=32)

    for _ in range(100):
        parser.feed(b"x" * 256)

        assert parser.buffered_bytes <= parser.max_buffer_size


# Tests that an oversized newline-terminated text response is rejected.
def test_oversized_terminated_text_is_rejected():
    parser = make_parser(max_text_line=32)

    events = parser.feed(b"A" * 200 + b"\n")

    assert not any(event.kind == "text" for event in events)
    assert any(event.kind == "error" for event in events)
    assert parser.buffered_bytes <= parser.max_buffer_size


# Tests that the parser recovers when a corrupted frame contains a false header.
def test_corrupt_frame_with_embedded_header_recovers():
    parser = make_parser()

    corrupt = bytearray(make_frame(sequence=30))
    corrupt[8:10] = FRAME_HEADER
    good = make_frame(sequence=31)

    events = parser.feed(bytes(corrupt) + good)

    frames = [event.data for event in events if event.kind == "frame"]
    assert frames == [good]


# Tests that the parser recovers when an oversized text line is followed by a split frame header.
def test_recovers_after_oversized_line_with_split_frame_header():
    parser = make_parser(max_text_line=32)
    frame = make_frame(sequence=32)

    events = parser.feed(b"A" * 100)
    assert any(event.kind == "error" for event in events)

    parser.feed(b"\n")
    assert parser.feed(frame[:1]) == []

    events = parser.feed(frame[1:])
    frames = [event.data for event in events if event.kind == "frame"]

    assert frames == [frame]