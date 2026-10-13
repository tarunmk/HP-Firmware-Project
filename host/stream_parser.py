
"""Bounded, testable parser for mixed text and binary telemetry streams."""

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class StreamEvent:
    """A parsed text response, validated binary frame, or parser error."""

    kind: str
    data: bytes | str


class StreamParser:
    """Parse newline-delimited text and fixed-size binary frames."""

    # Process input in small chunks so a single large read does not
    # unnecessarily expand the parser's internal buffer all at once.
    INPUT_CHUNK_SIZE = 64

    def __init__(
        self,
        frame_header: bytes,
        frame_size: int,
        validator: Callable[[bytes], tuple[bool, str]],
        max_text_line: int = 128,
    ):
        # Validate the parser configuration before accepting any input.
        if not frame_header:
            raise ValueError("frame_header must not be empty")
        if frame_size <= len(frame_header):
            raise ValueError("frame_size must exceed header length")
        if max_text_line <= 0:
            raise ValueError("max_text_line must be positive")

        self._header = bytes(frame_header)
        self._frame_size = frame_size
        self._validator = validator
        self._max_text_line = max_text_line

        # Retains incomplete messages between feed() calls.
        self._buffer = bytearray()

        # Tracks recovery from an oversized text line. The scan tail
        # preserves enough bytes to detect a frame header split across
        # separate input chunks.
        self._discarding_oversized_line = False
        self._discard_scan_tail = b""

    @property
    def buffered_bytes(self) -> int:
        """Number of bytes currently retained for an incomplete message."""
        return len(self._buffer)

    @property
    def max_buffer_size(self) -> int:
        """Maximum retained/transient parser buffer size."""
        # This is a bound derived from configured message sizes and the
        # input chunk size, not a limit on the total input passed to feed().
        return max(self._max_text_line, self._frame_size) + self.INPUT_CHUNK_SIZE

    def reset(self) -> None:
        """Discard partial input and parser recovery state."""
        self._buffer.clear()
        self._discarding_oversized_line = False
        self._discard_scan_tail = b""

    def feed(self, data: bytes | bytearray | memoryview) -> list[StreamEvent]:
        """Consume arbitrary input chunks and return all complete events."""
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError("data must be bytes-like")

        # Normalize input so parsing works consistently with all supported
        # bytes-like types. A message may span multiple calls to feed().
        incoming = bytes(data)
        events = []
        offset = 0

        while offset < len(incoming):
            if self._discarding_oversized_line:
                # Ignore the remainder of an oversized text line, while
                # searching for a newline or a new binary frame header.
                # The header may occur before the next newline if the text
                # was malformed or a frame followed the oversized input.
                scan = self._discard_scan_tail + incoming[offset:]
                newline_index = scan.find(b"\n")
                header_index = scan.find(self._header)

                if header_index >= 0 and (
                    newline_index < 0 or header_index < newline_index
                ):
                    # Resume parsing at the frame header rather than
                    # discarding a valid binary frame with the bad text.
                    incoming = scan[header_index:]
                    offset = 0
                    self._discard_scan_tail = b""
                    self._discarding_oversized_line = False
                    continue

                if newline_index >= 0:
                    # The oversized line ended. Resume after its newline.
                    incoming = scan[newline_index + 1:]
                    offset = 0
                    self._discard_scan_tail = b""
                    self._discarding_oversized_line = False
                    continue

                # Keep only enough trailing bytes to detect a header that
                # may be split across the next input chunk.
                keep = max(0, len(self._header) - 1)
                self._discard_scan_tail = scan[-keep:] if keep else b""
                return events

            # Append input in bounded chunks and parse after each addition.
            chunk_end = min(offset + self.INPUT_CHUNK_SIZE, len(incoming))
            chunk = incoming[offset:chunk_end]
            self._buffer.extend(chunk)
            offset = chunk_end
            self._drain(events)

        return events

    def _drain(self, events: list[StreamEvent]) -> None:
        """Extract complete messages until the buffer holds only partial input."""
        while self._buffer:
            # Locate the next candidate binary frame and text line ending.
            header_index = self._buffer.find(self._header)
            newline_index = self._buffer.find(b"\n")

            # Reject an overlong completed text response before processing it.
            if (
                newline_index >= 0
                and (header_index < 0 or newline_index < header_index)
                and newline_index > self._max_text_line
            ):
                del self._buffer[:newline_index + 1]
                events.append(
                    StreamEvent("error", "Text response exceeds maximum length")
                )
                continue

            # Process text only when its newline occurs before the next
            # candidate binary header. This allows text and frames to share
            # the same serial stream.
            if (
                newline_index >= 0
                and (
                    header_index < 0
                    or newline_index < header_index
                )
            ):
                line = bytes(self._buffer[:newline_index + 1])
                del self._buffer[:newline_index + 1]
                self._process_text_line(line, events)
                continue

            if header_index == 0:
                # A header is present, but the complete fixed-size frame
                # may not have arrived yet. Retain it for the next feed().
                if len(self._buffer) < self._frame_size:
                    return

                candidate = bytes(self._buffer[:self._frame_size])
                valid, message = self._validator(candidate)

                if valid:
                    # Emit only validated frames and remove their bytes.
                    del self._buffer[:self._frame_size]
                    events.append(StreamEvent("frame", candidate))
                else:
                    # Advance by one byte after a failed candidate so a
                    # later valid header inside the buffered data can be found.
                    del self._buffer[0]
                    events.append(StreamEvent("error", message))

                continue

            if header_index > 0:
                # Discard unrelated bytes before the next candidate header.
                # Reporting the discarded count helps diagnose stream corruption.
                del self._buffer[:header_index]
                events.append(
                    StreamEvent(
                        "error",
                        f"Discarded {header_index} bytes before frame header",
                    )
                )
                continue

            if len(self._buffer) > self._max_text_line:
                # No header or newline was found within the permitted length.
                # Clear buffered input and enter recovery mode until a newline
                # or a recognizable frame header is found.
                self._buffer.clear()
                self._discarding_oversized_line = True
                events.append(
                    StreamEvent(
                        "error",
                        "Discarded oversized unterminated input",
                    )
                )
                return

            # No complete message is available yet. Keep the partial bytes.
            return

    def _process_text_line(
        self,
        line: bytes,
        events: list[StreamEvent],
    ) -> None:
        """Validate and emit one newline-terminated ASCII response."""
        # Accept both LF and CRLF line endings.
        line = line.rstrip(b"\r\n")

        # Ignore blank lines rather than emitting empty text events.
        if not line:
            return

        if len(line) > self._max_text_line:
            events.append(
                StreamEvent("error", "Text response exceeds maximum length")
            )
            return

        # Protocol responses are expected to be printable ASCII. Reject
        # control characters and non-ASCII bytes rather than decoding
        # potentially corrupted input as a command response.
        if any(byte < 0x20 or byte > 0x7E for byte in line):
            events.append(
                StreamEvent("error", "Non-printable byte in text response")
            )
            return

        events.append(StreamEvent("text", line.decode("ascii")))
