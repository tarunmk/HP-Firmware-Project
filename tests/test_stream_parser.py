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


def test_single_frame():
    parser = make_parser()
    events = parser.feed(make_frame(sequence=7))

    frames = [event.data for event in events if event.kind == "frame"]
    assert len(frames) == 1
    assert validate_frame(frames[0])[0]


def test_frame_split_across_reads():
    parser = make_parser()
    frame = make_frame(sequence=8)

    assert parser.feed(frame[:5]) == []
    assert parser.feed(frame[5:13]) == []

    events = parser.feed(frame[13:])
    frames = [event.data for event in events if event.kind == "frame"]

    assert frames == [frame]


def test_multiple_frames_in_one_read():
    parser = make_parser()
    first = make_frame(sequence=1)
    second = make_frame(sequence=2)

    events = parser.feed(first + second)
    frames = [event.data for event in events if event.kind == "frame"]

    assert frames == [first, second]


def test_text_response():
    parser = make_parser()

    events = parser.feed(b"STATUS,1000,1,NORMAL\r\n")

    assert [(event.kind, event.data) for event in events] == [
        ("text", "STATUS,1000,1,NORMAL")
    ]


def test_garbage_before_valid_frame_recovers():
    parser = make_parser()
    frame = make_frame(sequence=11)

    events = parser.feed(b"\x01\x02\x03" + frame)
    frames = [event.data for event in events if event.kind == "frame"]

    assert frames == [frame]
    assert any(event.kind == "error" for event in events)


def test_corrupt_frame_followed_by_valid_frame_recovers():
    parser = make_parser()
    corrupt = bytearray(make_frame(sequence=10))
    corrupt[14] ^= 0x80
    good = make_frame(sequence=12)

    events = parser.feed(bytes(corrupt) + good)
    frames = [event.data for event in events if event.kind == "frame"]

    assert frames == [good]


def test_oversized_unterminated_input_is_bounded():
    parser = make_parser(max_text_line=32)

    events = parser.feed(b"x" * 4096)

    assert parser.buffered_bytes <= parser.max_buffer_size
    assert any(event.kind == "error" for event in events)


def test_reset_discards_partial_frame():
    parser = make_parser()
    frame = make_frame(sequence=14)

    assert parser.feed(frame[:10]) == []
    parser.reset()

    events = parser.feed(frame[10:])
    assert not any(event.kind == "frame" for event in events)


def test_invalid_crc_is_never_emitted_as_frame():
    parser = make_parser()
    frame = bytearray(make_frame(sequence=15))
    frame[-1] ^= 0x01

    events = parser.feed(frame)

    assert not any(event.kind == "frame" for event in events)
    assert any(event.kind == "error" for event in events)


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


def test_frame_received_one_byte_at_a_time():
    parser = make_parser()
    frame = make_frame(sequence=22)
    events = []

    for byte in frame:
        events.extend(parser.feed(bytes([byte])))

    frames = [event.data for event in events if event.kind == "frame"]
    assert frames == [frame]


def test_text_response_split_across_reads():
    parser = make_parser()

    assert parser.feed(b"STATUS,1000,") == []
    events = parser.feed(b"1,NORMAL\r\n")

    assert [(event.kind, event.data) for event in events] == [
        ("text", "STATUS,1000,1,NORMAL")
    ]


def test_text_and_binary_frame_back_to_back():
    parser = make_parser()
    response = b"STATUS,1000,1,NORMAL\r\n"
    frame = make_frame(sequence=23)

    events = parser.feed(response + frame)

    assert [(event.kind, event.data) for event in events] == [
        ("text", "STATUS,1000,1,NORMAL"),
        ("frame", frame),
    ]


def test_false_sync_marker_before_valid_frame_recovers():
    parser = make_parser()
    false_candidate = b"\xAA\x55" + b"\x00" * 18
    valid_frame = make_frame(sequence=24)

    events = parser.feed(false_candidate + valid_frame)

    frames = [event.data for event in events if event.kind == "frame"]
    assert frames == [valid_frame]


def test_repeated_malformed_input_keeps_buffer_bounded():
    parser = make_parser(max_text_line=32)

    for _ in range(100):
        parser.feed(b"x" * 256)

        assert parser.buffered_bytes <= parser.max_buffer_size


def test_oversized_terminated_text_is_rejected():
    parser = make_parser(max_text_line=32)

    events = parser.feed(b"A" * 200 + b"\n")

    assert not any(event.kind == "text" for event in events)
    assert any(event.kind == "error" for event in events)
    assert parser.buffered_bytes <= parser.max_buffer_size


def test_corrupt_frame_with_embedded_header_recovers():
    parser = make_parser()

    corrupt = bytearray(make_frame(sequence=30))
    corrupt[8:10] = FRAME_HEADER
    good = make_frame(sequence=31)

    # The altered payload invalidates the first frame's CRC.
    events = parser.feed(bytes(corrupt) + good)

    frames = [event.data for event in events if event.kind == "frame"]
    assert frames == [good]

def test_recovers_after_oversized_line_with_split_frame_header():
    parser = make_parser(max_text_line=32)
    frame = make_frame(sequence=32)

    # Trigger oversized-line discard mode.
    events = parser.feed(b"A" * 100)
    assert any(event.kind == "error" for event in events)

    # End the discarded line, then deliver the frame header in two reads.
    parser.feed(b"\n")
    assert parser.feed(frame[:1]) == []

    events = parser.feed(frame[1:])
    frames = [event.data for event in events if event.kind == "frame"]

    assert frames == [frame]