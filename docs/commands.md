Command Protocol

1. Purpose

This document describes the command interface between the Python host dashboard and the Arduino Mega firmware.

The implementation uses newline-delimited ASCII commands and text responses. Telemetry is transmitted separately as binary frames, with frame validation and CRC-16 checking performed by the Python host.


2. Communication

- Baud rate: 115200.
- Command encoding: ASCII, terminated by a newline (`\n`).
- Response format: Newline-delimited text.
- Telemetry format: Binary frames defined in [`protocol.md`](protocol.md).
- Transport architecture: The firmware communicates over USB serial. The Python serial bridge owns the physical serial connection and relays bytes over TCP to the dashboard at `127.0.0.1:8765`.

Command responses and binary telemetry share the same physical serial connection. The host parser distinguishes text responses from binary frames.

3. Implemented Commands

3.1 Set Sampling Rate — `RATE,<milliseconds>`

- Example:

RATE,1000

Configures the normal-mode sampling interval.

- Supported range: 100–5000 milliseconds.
- The configured normal sampling interval is retained when switching between NORMAL and LOW power modes during the same firmware runtime.
- LOW mode uses an effective sampling interval of 5000 milliseconds.

The command changes the runtime configuration.

3.2 Start Streaming — `STREAM,1`

Enables telemetry transmission.

3.3 Stop Streaming — `STREAM,0`

Disables telemetry transmission while keeping command processing active.

3.4 Get Device Status — `STATUS`

Requests the current device status.

- Example response:

STATUS,1000,1,LOW

The response fields are:

| Field | Meaning |
|---|---|
| `STATUS` | Response identifier |
| `1000` | Configured normal sampling interval in milliseconds |
| `1` | Streaming state: `0` stopped, `1` enabled |
| `LOW` | Power mode: `LOW` or `NORMAL` |


3.5 Enable Low-Power Mode — `POWER_MODE,LOW`

Enables the software power-aware mode.

Current behavior:

- Sets the effective sampling interval to 5000 milliseconds.
- Reduces sampling and telemetry transmission frequency.
- Suppresses normal LED toggling.
- Keeps command processing active.

- Expected acknowledgement:

OK,POWER_MODE,LOW

3.6 Enable Normal Mode — `POWER_MODE,NORMAL`

Restores normal-mode sampling behavior using the configured normal sampling interval.

- Expected acknowledgement:

OK,POWER_MODE,NORMAL

3.7 Get Power Status — `POWER_STATUS`

Requests the current power mode.

- Example response:

POWER_STATUS,LOW

3.8 Host Help — `HELP`

Displays the supported command list in the Python dashboard. This is a host-side command and does not require a firmware response.

3.9 Exit Dashboard — `QUIT`

Stops the Python dashboard. It does not intentionally reset or stop the firmware.

If the serial bridge remains running and the USB connection stays active, the dashboard can reconnect without reopening the physical serial port.

4. Power Management

The firmware provides NORMAL and LOW software operating modes.

In LOW mode, the effective sampling interval is 5000 milliseconds. In NORMAL mode, the effective interval follows the configured normal sampling rate.

The dashboard displays:

- Current confirmed power mode.
- Effective sampling interval.
- Last confirmed mode transition.

The displayed power mode is updated from device responses rather than being based solely on the command entered by the user.

5. Error Handling and Reliability

- The host parser handles partial reads, combined reads, malformed input, and corrupted telemetry frames.
- Binary telemetry frames are validated using frame-structure checks and CRC-16 validation.
- Invalid telemetry frames are reported without accepting their data as valid telemetry.
- Text responses and binary telemetry share the same serial connection and are parsed without corrupting frame boundaries.
- The dashboard logs device responses, but the current ASCII command protocol does not implement transaction IDs or full request-response correlation.
- The serial bridge keeps the physical serial port open while the dashboard disconnects and reconnects.
- Dashboard reconnection has been exercised successfully while the bridge and USB connection remain active.

6. RTOS and Resource Considerations

The firmware uses FreeRTOS for task-based operation.

Potential areas for future evaluation include:

- Bounded queues and explicit handling of queue saturation.
- Predictable sampling-period updates.
- Avoiding unnecessary dynamic allocation in steady-state execution paths.
- Keeping command processing independent of telemetry transmission.
- Diagnostic counters for malformed input and dropped telemetry.


7. Future Enhancements

7.1 Framed Command Protocol

Potential enhancements include:

- Message type identifiers.
- Transaction IDs.
- CRC validation for commands and responses.
- Explicit success and error result codes.
- Response timeouts and transaction matching.
- Defined retry and idempotency behavior.

7.2 Hardware Sleep and Power Measurement

Potential enhancements include:

- Implementing an appropriate microcontroller sleep state.
- Designing a wake-up strategy that preserves required sampling and communication behavior.
- Evaluating peripheral power management.
- Measuring current consumption in NORMAL and LOW modes under equivalent conditions.
- Reporting measured average power and energy usage rather than estimating savings from sampling frequency alone.

7.3 Physical USB Reconnection Recovery

Automatic recovery following physical USB disconnection has not been verified as an implemented capability. Future work may include detecting serial-device removal, retrying the connection when the device returns, and handling firmware resets and lost runtime configuration.