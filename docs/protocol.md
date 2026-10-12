Telemetry Protocol — Version 1

1. Overview

This document defines the binary telemetry frame exchanged between the Arduino Mega firmware and the Python host receiver.
The current implementation uses binary frames for telemetry and newline-delimited ASCII for commands and device responses.

2. Frame Layout

Each telemetry frame is exactly 20 bytes.

| Field             | Size       | Description |

| Sync marker       | 2 bytes    | `0xAA 0x55` |
| Message type      | 1 byte     | `0x01` for telemetry |
| Payload length    | 1 byte     | `12` bytes |
| Sequence number   | 2 bytes    | Unsigned 16-bit integer, little-endian |
| Payload           | 12 bytes   | Timestamp followed by temperature |
| CRC-16            | 2 bytes    | CRC-16/CCITT-FALSE, little-endian |

3. Telemetry Payload

| Field             | Size         | Format |

| Timestamp         | 8 bytes      | Unsigned 64-bit milliseconds since startup |
| Temperature       | 4 bytes      | IEEE 754 binary32, degrees Celsius |

Telemetry payload length: 12 bytes.

Expected telemetry frame size: 20 bytes.

4. Encoding Rules

- Multi-byte integers use little-endian byte order.
- Temperature uses IEEE 754 binary32 encoding.
- The sequence number increments for every transmitted telemetry frame and wraps at 16 bits.
- The timestamp represents elapsed milliseconds since firmware startup.

5. CRC Rules

- Algorithm: CRC-16/CCITT-FALSE.
- Polynomial: `0x1021`.
- Initial value: `0xFFFF`.
- Reflected input/output: false.
- Final XOR: `0x0000`.
- Coverage: message type, payload length, sequence number, and payload.
- Transmission order: low CRC byte first.

The host validates the CRC before accepting a telemetry frame.

6. Parser Requirements

- Accept partial and combined serial reads.
- Reject unsupported message types, invalid payload lengths, and CRC failures.
- Recover from corrupted or truncated frames without restarting the host.
- Resume parsing when a valid sync marker is found.
- Avoid reading beyond available frame data.
- Keep text command responses separate from validated binary telemetry frames.
- Reject telemetry frames containing non-finite temperature values, including `NaN` and positive or negative infinity.

7. Command Interface

The current host and firmware use newline-delimited ASCII commands and text responses over the same serial connection.

Examples include:

- `STATUS`
- `RATE,1000`
- `STREAM,0`
- `STREAM,1`
- `POWER_MODE,LOW`
- `POWER_MODE,NORMAL`
- `POWER_STATUS`

These commands do not currently use the binary telemetry frame format or transaction IDs.

See `commands.md` for the implemented commands and planned protocol enhancements.

8. Future Enhancements

Potential improvements include:

- A unified binary framing format for commands and responses.
- Transaction IDs and explicit command acknowledgement codes.
- Additional telemetry fields and sensor measurements.
- Diagnostic counters for invalid frames and dropped telemetry.
- Hardware sleep modes and measured power-consumption comparisons, documented separately from the current telemetry protocol.