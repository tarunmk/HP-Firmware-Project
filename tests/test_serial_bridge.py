import sys

import pytest
import serial

from host import serial_bridge


def test_serial_open_failure_exits_cleanly(monkeypatch, capsys):
    def fail_to_open_serial(*args, **kwargs):
        raise serial.SerialException("Simulated serial port failure")

    monkeypatch.setattr(
        serial_bridge.serial,
        "Serial",
        fail_to_open_serial,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["serial_bridge.py", "--port", "/dev/fake-port"],
    )

    with pytest.raises(SystemExit) as exc:
        serial_bridge.main()

    assert exc.value.code == 1

    output = capsys.readouterr().out
    assert "Simulated serial port failure" in output
    assert "Serial bridge stopped." in output


def test_missing_port_argument_is_rejected(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["serial_bridge.py"],
    )

    with pytest.raises(SystemExit) as exc:
        serial_bridge.main()

    assert exc.value.code == 2
