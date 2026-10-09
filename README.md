Embedded Sensor Telemetry System

Project Overview

This project implements an RTOS-based embedded system that periodically samples a sensor, transmits timestamped readings to a host computer, and accepts commands from the host over a serial connection.

The initial sensor will be synthesized in software. The design will keep sensor acquisition separate from communication logic so a physical sensor can be integrated later.

Target Platform

- Microcontroller: ATmega2560 (ELEGOO Mega 2560)
- RTOS: FreeRTOS
- Host application: Python 3
- Communication: USB serial
- Initial sensor: Synthesized temperature signal

Core Requirements

1. Sample the sensor periodically.
2. Include a timestamp and value with every reading.
3. Frame telemetry messages for reliable decoding over a byte stream.
4. Accept commands to change the sample rate, start or stop streaming, and report status.
5. Continue operating when the host disconnects and resume communication when it reconnects.
6. Display or log readings in the host application.
7. Allow the host to send device commands.
8. Recover from corrupted bytes, truncated frames, and mid-stream connections without restarting the application.
9. Provide reproducible build and run instructions.

Planned Architecture

- `firmware/` — Embedded C firmware and RTOS tasks.
- `host/` — Python receiver, decoder, and command interface.
- `tests/` — Automated firmware logic and protocol tests.
- `docs/` — Architecture and protocol documentation.

Planned Enhancements

- Power-aware operating mode.
- Firmware identity and version reporting.
- Automated testing of malformed telemetry frames.
- Physical sensor integration when hardware becomes available.

Development Status

Current phase: Project setup and design.

The development environment and initial directory structure are ready. Firmware implementation, protocol design, host integration, and validation are pending.