# Command Protocol — Version 1

## 1. Purpose

This document defines the commands exchanged between the Python host and the FreeRTOS-based MCU.

All commands and responses use the common binary frame format defined in `protocol.md`.

## 2. Frame and Transaction Rules

- Each command includes a unique 16-bit transaction ID in its payload.
- Transaction IDs are allocated by the host and increment for each new command, wrapping at 65535 to 0.
- A response echoes the transaction ID of the command it acknowledges.
- Transaction IDs are independent of the outer frame sequence number.
- The host permits only one outstanding command at a time in Version 1.
- The device processes a command only after validating its complete frame and CRC.
- Responses use message type `0x80`.
- The outer frame sequence number increments independently for every transmitted frame.

### Command Payload Layout

Every command payload starts with a 2-byte unsigned transaction ID in little-endian order, followed by command-specific data.

## 3. Command Definitions

### Set Sample Rate — `0x10`

- Payload length: 6 bytes.
- Bytes 0–1: transaction ID (`uint16`, little-endian).
- Bytes 2–5: requested sample rate (`uint32`, little-endian).
- Valid rate: 1–100 samples per second.
- Success: atomically apply the new rate and acknowledge success.
- Failure: reject the request without changing the active rate.

### Start Streaming — `0x11`

- Payload length: 2 bytes.
- Bytes 0–1: transaction ID.
- Action: enable telemetry transmission.
- Repeated requests are idempotent: the device remains in the streaming state without creating duplicate tasks.

### Stop Streaming — `0x12`

- Payload length: 2 bytes.
- Bytes 0–1: transaction ID.
- Action: stop telemetry transmission while keeping command processing active.
- Repeated requests are idempotent.

### Get Status — `0x13`

- Payload length: 2 bytes.
- Bytes 0–1: transaction ID.
- Action: request current device status.

## 4. Command Response — `0x80`

### Common Response Payload

| Field | Size | Description |
|---|---:|---|
| Transaction ID | 2 bytes | Echoes the request transaction ID |
| Result code | 1 byte | Outcome of the command |
| Original command type | 1 byte | Identifies the acknowledged command |
| Response data | Variable | Command-specific information |

Transaction ID and multi-byte response fields use little-endian encoding.

### Result Codes

- `0x00`: success.
- `0x01`: unsupported command.
- `0x02`: invalid payload length.
- `0x03`: invalid parameter.
- `0x04`: internal error.

### Status Response Data

For a successful Get Status command, the response data contains:

| Field | Size | Description |
|---|---:|---|
| Streaming state | 1 byte | `0x00` stopped; `0x01` streaming |
| Sample rate | 4 bytes | Active rate in Hz, unsigned little-endian |
| Firmware major version | 1 byte | Major version |
| Firmware minor version | 1 byte | Minor version |
| Firmware patch version | 1 byte | Patch version |

The complete successful status response payload is 12 bytes: 4 bytes of common response fields and 8 bytes of status data.

For other successful commands, response data is empty unless explicitly defined later.

For unsuccessful commands, response data is empty in Version 1.

## 5. Validation and State Safety

The device must validate, in order:

1. Sync marker and complete frame availability.
2. Payload length and maximum permitted frame size.
3. CRC integrity.
4. Supported message type.
5. Exact payload length for that command.
6. Transaction ID and command parameters.

The device must not modify configuration or streaming state until validation succeeds.

Malformed frames that cannot be reliably associated with a complete command are discarded without changing state. If a complete, validly framed command has a recognized transaction ID but invalid parameters, return an error response.

## 6. Reliability and Recovery

- The device must continue operating when the host disconnects.
- Reconnection must not require a device restart.
- The host must handle partial reads, combined frames, corrupted bytes, and truncated frames.
- Invalid frames must not crash the parser or cause out-of-bounds memory access.
- The host must match responses using transaction IDs, not arrival order alone.
- The host must use a finite response timeout and report timeout failures.
- The host must not assume a timed-out command failed to execute; it may have executed before the response was lost.
- Start and Stop commands are idempotent to make safe retries easier.

## 7. RTOS Concurrency

- One control task owns mutable configuration and streaming state.
- The serial receive path validates frames before submitting commands to the control task.
- Inter-task communication uses bounded queues or notifications where appropriate.
- Queue saturation is handled explicitly and counted; it must not silently corrupt state.
- No command may create duplicate RTOS tasks.
- Sampling timing changes must take effect predictably without busy-waiting.

## 8. Resource Constraints

- Use fixed-size buffers and bounded payload lengths.
- Avoid dynamic memory allocation in the steady-state command and telemetry paths.
- Keep command processing independent of telemetry streaming.
- Use diagnostic counters for malformed frames, CRC failures, dropped telemetry, and command timeouts where applicable.