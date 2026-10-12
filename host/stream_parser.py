"""Bounded, testable parser for mixed text and binary telemetry streams."""

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class StreamEvent:
    """An event emitted by the stream parser."""

    kind: str
    data: bytes | str


class StreamParser:
    """Parse newline-delimited text and fixed-size binary frames."""

    INPUT_CHUNK_SIZE = 64

    def __init__(
        self,
        frame_header: bytes,
        frame_size: int,
        validator: Callable[[bytes], tuple[bool, str]],
        max_text_line: int = 128,
    ):
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
        self._buffer = bytearray()
        self._discarding_oversized_line = False
        self._discard_scan_tail = b""

    @property
    def buffered_bytes(self) -> int:
        """Number of bytes currently retained for an incomplete message."""
        return len(self._buffer)

    @property
    def max_buffer_size(self) -> int:
        """Maximum retained/transient parser buffer size."""
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

        incoming = bytes(data)
        events = []
        offset = 0

        while offset < len(incoming):
            if self._discarding_oversized_line:
                # Retain a possible split sync marker while discarding an
                # oversized line. Search all remaining input so a newline
                # or frame header later in this same feed is not missed.
                scan = self._discard_scan_tail + incoming[offset:]
                newline_index = scan.find(b"\n")
                header_index = scan.find(self._header)

                if header_index >= 0 and (
                    newline_index < 0 or header_index < newline_index
                ):
                    incoming = scan[header_index:]
                    offset = 0
                    self._discard_scan_tail = b""
                    self._discarding_oversized_line = False
                    continue

                if newline_index >= 0:
                    incoming = scan[newline_index + 1:]
                    offset = 0
                    self._discard_scan_tail = b""
                    self._discarding_oversized_line = False
                    continue

                keep = max(0, len(self._header) - 1)
                self._discard_scan_tail = scan[-keep:] if keep else b""
                return events

            chunk_end = min(offset + self.INPUT_CHUNK_SIZE, len(incoming))
            chunk = incoming[offset:chunk_end]
            self._buffer.extend(chunk)
            offset = chunk_end
            self._drain(events)

        return events

    def _drain(self, events: list[StreamEvent]) -> None:
        while self._buffer:
            header_index = self._buffer.find(self._header)
            newline_index = self._buffer.find(b"\n")

            # Reject an oversized complete text line before decoding it.
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

            # A complete newline-delimited text line takes priority only
            # when it ends before the next binary frame header.
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

            # A candidate binary frame begins at the buffer boundary.
            if header_index == 0:
                if len(self._buffer) < self._frame_size:
                    return

                candidate = bytes(self._buffer[:self._frame_size])
                valid, message = self._validator(candidate)

                if valid:
                    del self._buffer[:self._frame_size]
                    events.append(StreamEvent("frame", candidate))
                else:
                    # Advance one byte so an overlapping or subsequent
                    # valid sync marker can still be discovered.
                    del self._buffer[0]
                    events.append(StreamEvent("error", message))

                continue

            # Discard bytes before a candidate frame header. Do not interpret
            # arbitrary binary noise as a text response.
            if header_index > 0:
                del self._buffer[:header_index]
                events.append(
                    StreamEvent(
                        "error",
                        f"Discarded {header_index} bytes before frame header",
                    )
                )
                continue

            # Bound memory and remember to discard the rest of an oversized
            # unterminated text line instead of later accepting its tail.
            if len(self._buffer) > self._max_text_line:
                self._buffer.clear()
                self._discarding_oversized_line = True
                events.append(
                    StreamEvent(
                        "error",
                        "Discarded oversized unterminated input",
                    )
                )
                return

            # Preserve a partial line or frame header for the next read.
            return

    def _process_text_line(
        self,
        line: bytes,
        events: list[StreamEvent],
    ) -> None:
        line = line.rstrip(b"\r\n")

        if not line:
            return

        if len(line) > self._max_text_line:
            events.append(
                StreamEvent("error", "Text response exceeds maximum length")
            )
            return

        if any(byte < 0x20 or byte > 0x7E for byte in line):
            events.append(
                StreamEvent("error", "Non-printable byte in text response")
            )
            return

        events.append(StreamEvent("text", line.decode("ascii")))
