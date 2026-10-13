import math
import struct

from host.telemetry_receiver import (
    FRAME_HEADER,
    FRAME_SIZE,
    MESSAGE_TYPE_TELEMETRY,
    PAYLOAD_SIZE,
    calculate_crc16,
    decode_frame,
    validate_frame,
)


def make_frame(sequence=1, timestamp_ms=123456, temperature_c=25.5):
    frame = bytearray(FRAME_SIZE)
    frame[0:2] = FRAME_HEADER
    frame[2] = MESSAGE_TYPE_TELEMETRY
    frame[3] = PAYLOAD_SIZE
    frame[4:6] = sequence.to_bytes(2, "little")
    frame[6:14] = timestamp_ms.to_bytes(8, "little")
    frame[14:18] = struct.pack("<f", temperature_c)
    crc = calculate_crc16(frame[2:18])
    frame[18:20] = crc.to_bytes(2, "little")
    return bytes(frame)


# Tests that CRC-16 produces the expected result for a standard known test vector.
def test_crc16_known_vector():
    assert calculate_crc16(b"123456789") == 0x29B1


# Tests that a correctly formatted frame with a valid CRC is accepted.
def test_valid_frame_is_accepted():
    valid, message = validate_frame(make_frame())
    assert valid is True
    assert message == "CRC OK"


# Tests that telemetry frames use the expected 20-byte format.
def test_frame_size_is_20_bytes():
    assert len(make_frame()) == 20
    assert FRAME_SIZE == 20


# Tests that the sequence number, timestamp, and temperature are decoded correctly.
def test_decode_frame_fields():
    frame = make_frame(513, 987654, 26.5)
    sequence, timestamp_ms, temperature_c = decode_frame(frame)
    assert sequence == 513
    assert timestamp_ms == 987654
    assert math.isclose(temperature_c, 26.5, abs_tol=0.001)


# Tests that a frame with an invalid synchronization header is rejected.
def test_invalid_header_is_rejected():
    frame = bytearray(make_frame())
    frame[0] = 0x00
    valid, message = validate_frame(bytes(frame))
    assert valid is False
    assert message == "Invalid frame header"


# Tests that a frame with an unsupported message type is rejected.
def test_wrong_message_type_is_rejected():
    frame = bytearray(make_frame())
    frame[2] = 0x02
    valid, message = validate_frame(bytes(frame))
    assert valid is False
    assert "Unknown message type" in message


# Tests that a frame with an unexpected payload length is rejected.
def test_wrong_payload_length_is_rejected():
    frame = bytearray(make_frame())
    frame[3] = 11
    valid, message = validate_frame(bytes(frame))
    assert valid is False
    assert "Unexpected payload size" in message


# Tests that modifying the payload without updating the CRC causes validation to fail.
def test_corrupted_payload_fails_crc():
    frame = bytearray(make_frame())
    frame[14] ^= 0x01
    valid, message = validate_frame(bytes(frame))
    assert valid is False
    assert "CRC ERROR" in message


# Tests that a frame with a corrupted CRC value is rejected.
def test_corrupted_crc_is_rejected():
    frame = bytearray(make_frame())
    frame[18] ^= 0x01
    valid, message = validate_frame(bytes(frame))
    assert valid is False
    assert "CRC ERROR" in message


# Tests that NaN temperatures are rejected even when the frame CRC is valid.
def test_nan_temperature_is_rejected_even_with_valid_crc():
    frame = bytearray(make_frame(temperature_c=25.0))
    frame[14:18] = struct.pack("<f", float("nan"))
    crc = calculate_crc16(frame[2:18])
    frame[18:20] = crc.to_bytes(2, "little")

    valid, message = validate_frame(bytes(frame))

    assert valid is False
    assert "temperature" in message.lower()
    assert "finite" in message.lower()


# Tests that infinite temperatures are rejected even when the frame CRC is valid.
def test_infinite_temperature_is_rejected_even_with_valid_crc():
    frame = bytearray(make_frame(temperature_c=25.0))
    frame[14:18] = struct.pack("<f", float("inf"))
    crc = calculate_crc16(frame[2:18])
    frame[18:20] = crc.to_bytes(2, "little")

    valid, message = validate_frame(bytes(frame))

    assert valid is False
    assert "temperature" in message.lower()
    assert "finite" in message.lower()


# Tests that a frame with an incorrect number of bytes is rejected.
def test_incomplete_frame_is_rejected():
    valid, message = validate_frame(make_frame()[:-1])
    assert valid is False
    assert message == "Incorrect frame size"


# Tests that the minimum, typical, and maximum sequence numbers decode correctly.
def test_sequence_number_boundaries():
    for sequence in (0, 1, 65535):
        assert decode_frame(make_frame(sequence=sequence))[0] == sequence


# Tests that changing the sequence number without recalculating the CRC is detected.
def test_crc_detects_changes_in_sequence_number():
    frame = bytearray(make_frame(sequence=10))
    frame[4] ^= 0x01

    valid, message = validate_frame(bytes(frame))

    assert valid is False
    assert "CRC ERROR" in message


# Tests that two concatenated telemetry frames can be separated and validated individually.
def test_concatenated_frames_can_be_validated_individually():
    frames = [
        make_frame(sequence=1, temperature_c=20.0),
        make_frame(sequence=2, temperature_c=21.0),
    ]
    combined = b"".join(frames)

    assert len(combined) == 2 * FRAME_SIZE

    first = combined[:FRAME_SIZE]
    second = combined[FRAME_SIZE:]

    assert validate_frame(first)[0] is True
    assert validate_frame(second)[0] is True
    assert decode_frame(first)[0] == 1
    assert decode_frame(second)[0] == 2