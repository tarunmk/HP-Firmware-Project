# Telemetry Protocol — Version 1

## 1. Frame Layout

| Field                 | Size              | Description |

| Sync marker           | 2 bytes           | `0xAA 0x55` |
| Message type          | 1 byte            | `0x01` for telemetry |
| Payload length        | 1 byte            | Number of payload bytes |
| Sequence number       | 2 bytes           | Unsigned, little-endian |
| Payload               | Variable          | Up to 32 bytes |
| CRC-16                | 2 bytes           | CRC-16/CCITT-FALSE, little-endian |

## 2. Telemetry Payload

| Field                 | Size              | Format |

| Timestamp             | 8 bytes           | Unsigned 64-bit milliseconds since startup |
| Temperature           | 4 bytes           | IEEE 754 binary32, degrees Celsius |

Telemetry payload length: 12 bytes.

Expected telemetry frame size: 20 bytes.

## 3. Encoding Rules

- Multi-byte integers use little-endian byte order.
- Temperature uses IEEE 754 binary32 encoding.
- The sequence number increments for every transmitted frame and wraps at 16 bits.
- The timestamp represents elapsed milliseconds since firmware startup.

## 4. CRC Rules

- Algorithm: CRC-16/CCITT-FALSE.
- Polynomial: `0x1021`.
- Initial value: `0xFFFF`.
- Reflected input/output: false.
- Final XOR: `0x0000`.
- Coverage: message type, payload length, sequence number, and payload.
- Transmission order: low CRC byte first.

## 5. Parser Requirements

- Accept partial and combined serial reads.
- Reject unsupported message types, invalid payload lengths, and CRC failures.
- Recover from corrupted or truncated frames without restarting the host.
- Resume parsing when a valid sync marker is found.
- Never read beyond the fixed receive buffer.

## 6. Command Protocol

Command message types and their payload formats will be specified before implementing the host command interface. All commands and responses will use the same outer frame structure.