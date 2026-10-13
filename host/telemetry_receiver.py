import csv
import select
import socket
import struct
import sys
import termios
import time
import tty
import math

from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from rich import box
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


try:
    from host.stream_parser import StreamParser
except ModuleNotFoundError:
    from stream_parser import StreamParser

# Constants shared with the firmware telemetry protocol.
# The host expects a fixed 20-byte frame with a 12-byte payload.

FRAME_HEADER = bytes([0xAA, 0x55])
FRAME_SIZE = 20
MESSAGE_TYPE_TELEMETRY = 0x01
PAYLOAD_SIZE = 12
CRC_INITIAL_VALUE = 0xFFFF
CRC_POLYNOMIAL = 0x1021
LOG_FILE = Path(__file__).with_name("telemetry_log.csv")
VISIBLE_TELEMETRY_ROWS = 8
VISIBLE_EVENT_ROWS = 5
console = Console()


def calculate_crc16(data):
    """Calculate CRC-16/CCITT-FALSE over the supplied bytes."""
    crc = CRC_INITIAL_VALUE
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ CRC_POLYNOMIAL) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


def validate_frame(frame):
    """Validate frame structure, CRC, and decoded temperature sanity."""
    if len(frame) != FRAME_SIZE:
        return False, "Incorrect frame size"
    if frame[:2] != FRAME_HEADER:
        return False, "Invalid frame header"
    if frame[2] != MESSAGE_TYPE_TELEMETRY:
        return False, f"Unknown message type: 0x{frame[2]:02X}"
    if frame[3] != PAYLOAD_SIZE:
        return False, f"Unexpected payload size: {frame[3]}"
    # The CRC covers message type through the end of the payload; the
    # synchronization bytes and the CRC field itself are excluded.
    expected_crc = calculate_crc16(frame[2:18])
    received_crc = int.from_bytes(frame[18:20], "little")
    if expected_crc != received_crc:
        return False, (
            f"CRC ERROR: received 0x{received_crc:04X}, "
            f"calculated 0x{expected_crc:04X}"
        )
    temperature_c = struct.unpack("<f", frame[14:18])[0]
    if not math.isfinite(temperature_c):
        return False, "Invalid temperature: value must be finite"
    return True, "CRC OK"


def decode_frame(frame):
    """Decode fields from a frame that has already passed validation."""
    sequence = int.from_bytes(frame[4:6], "little")
    timestamp_ms = int.from_bytes(frame[6:14], "little")
    temperature_c = struct.unpack("<f", frame[14:18])[0]
    return sequence, timestamp_ms, temperature_c


def visible_slice(items, offset, count):
    """Return a page of items, with offset=0 showing the newest items."""
    end = max(0, len(items) - offset)
    start = max(0, end - count)
    return items[start:end]


def update_power_status(state, response):
    """Update dashboard state only from valid device responses."""
    # Preserve the previous mode so the dashboard can record actual changes.
    previous_mode = state["power_mode"]
    parts = response.split(",")
    new_mode = None
    if parts[0] == "STATUS" and len(parts) == 4:
        try:
            sample_rate = int(parts[1])
        except ValueError:
            return
        if not 100 <= sample_rate <= 5000:
            return
        if parts[2] not in ("0", "1"):
            return
        mode = parts[3].strip().upper()
        if mode not in ("LOW", "NORMAL"):
            return
        state["sample_rate"] = sample_rate
        state["streaming_enabled"] = parts[2] == "1"
        new_mode = mode
    elif parts[0] == "POWER_STATUS" and len(parts) == 2:
        mode = parts[1].strip().upper()
        if mode not in ("LOW", "NORMAL"):
            return
        new_mode = mode
    elif (
        len(parts) == 3
        and parts[0] == "OK"
        and parts[1] == "POWER_MODE"
    ):
        mode = parts[2].strip().upper()
        if mode not in ("LOW", "NORMAL"):
            return
        new_mode = mode
    else:
        return
    # LOW mode overrides the configured rate; NORMAL uses the configured rate.
    state["power_mode"] = new_mode
    state["effective_sample_period"] = (
        5000 if new_mode == "LOW" else state["sample_rate"]
    )
    if previous_mode != new_mode:
        now = datetime.now().strftime("%H:%M:%S")
        if previous_mode == "UNKNOWN":
            state["last_power_mode_change"] = (
                f"Initial status confirmed {now}"
            )
        else:
            state["last_power_mode_change"] = (
                f"{previous_mode} → {new_mode} at {now}"
            )
# Keep the CSV schema stable for inspection and downstream analysis.
CSV_HEADER = [
    "host_time_utc",
    "sequence",
    "device_timestamp_ms",
    "temperature_c",
    "crc_status",
]


def open_telemetry_log(log_file=LOG_FILE):
    """Open the CSV log in append mode and initialize its header if needed."""
    log_exists = log_file.exists() and log_file.stat().st_size > 0
    file = log_file.open("a", newline="", encoding="utf-8")
    writer = csv.writer(file)
    if not log_exists:
        writer.writerow(CSV_HEADER)
        file.flush()
    return file, writer


def write_telemetry_row(
    file,
    writer,
    host_time,
    sequence,
    timestamp_ms,
    temperature_c,
    crc_status,
):
    """Append one decoded telemetry record and flush it to disk."""
    # Write one decoded sample per row; flush so recent readings reach disk.
    writer.writerow([
        host_time,
        sequence,
        timestamp_ms,
        f"{temperature_c:.2f}",
        crc_status,
    ])
    file.flush()


def build_dashboard(state, command_text):
    """Build the Rich dashboard from the latest receiver state."""
    layout = Table.grid(expand=True)
    layout.add_column(ratio=1)
    title = Text(
        "HP FIRMWARE MONITOR",
        style="bold cyan",
        justify="center",
    )
    connection_status = (
        "[green]CONNECTED[/green]"
        if state["connected"]
        else "[red]DISCONNECTED[/red]"
    )
    layout.add_row(
        Panel(title, subtitle=connection_status, border_style="cyan")
    )
    # Summary metrics show the latest valid sample and current device settings.
    metrics = Table(box=box.ROUNDED, expand=True)
    metrics.add_column("TEMPERATURE", justify="center")
    metrics.add_column("SAMPLE INTERVAL (ms)", justify="center")
    metrics.add_column("SEQUENCE", justify="center")
    metrics.add_column("CRC", justify="center")
    if state["temperature"] is None:
        temperature_text = "[dim]Waiting...[/dim]"
    else:
        temperature_text = (
            f"[bold green]{state['temperature']:.2f} °C[/bold green]"
        )
    sequence_text = (
        str(state["sequence"])
        if state["sequence"] is not None
        else "--"
    )
    crc_text = (
        "[green]PASS[/green]"
        if state["crc_ok"]
        else "[yellow]WAITING[/yellow]"
    )
    metrics.add_row(
        temperature_text,
        (
            f"[bold cyan]{state['effective_sample_period']} ms[/bold cyan]"
            if state["effective_sample_period"] is not None
            else "[dim]Awaiting device...[/dim]"
        ),
        sequence_text,
        crc_text,
    )
    layout.add_row(metrics)
    # Show the reported mode and the most recent mode transition/confirmation.
    power_table = Table(box=box.ROUNDED, expand=True)
    power_table.add_column("POWER MODE", justify="center")
    power_table.add_column("LAST MODE CHANGE", justify="center")
    mode = state["power_mode"]
    if mode == "LOW":
        mode_text = "[bold green]LOW POWER[/bold green]"
    elif mode == "NORMAL":
        mode_text = "[bold cyan]NORMAL[/bold cyan]"
    else:
        mode_text = "[yellow]UNKNOWN — awaiting device[/yellow]"
    power_table.add_row(
        mode_text,
        state["last_power_mode_change"],
    )
    layout.add_row(
        Panel(power_table, title="POWER MANAGEMENT", border_style="green")
    )
    # History is paginated so older samples can be reviewed while reception continues.
    history = Table(
        title="LIVE TELEMETRY",
        box=box.SIMPLE,
        expand=True,
    )
    history.add_column("UTC TIME", style="dim", width=12)
    history.add_column("SEQ", justify="right", width=7)
    history.add_column("DEVICE TIME", justify="right", width=13)
    history.add_column("TEMPERATURE", justify="right")
    history.add_column("CRC", justify="center", width=8)
    telemetry_rows = visible_slice(
        state["history"],
        state["telemetry_offset"],
        VISIBLE_TELEMETRY_ROWS,
    )
    if telemetry_rows:
        for row in telemetry_rows:
            history.add_row(*row)
    else:
        history.add_row(
            "--", "--", "--", "Waiting for telemetry...", "--"
        )
    if state["telemetry_offset"] > 0:
        history.title = (
            f"LIVE TELEMETRY — "
            f"{state['telemetry_offset']} entries back"
        )
    telemetry_border = (
        "yellow"
        if state["selected_panel"] == "telemetry"
        else "blue"
    )
    layout.add_row(
        Panel(history, border_style=telemetry_border)
    )
    # Device replies, parser errors, and host command activity are shown separately
    # from decoded telemetry records.
    events_table = Table(
        title="DEVICE / COMMAND EVENTS",
        box=box.SIMPLE,
        expand=True,
    )
    events_table.add_column("EVENT", overflow="fold")
    event_rows = visible_slice(
        state["events"],
        state["events_offset"],
        VISIBLE_EVENT_ROWS,
    )
    if event_rows:
        for event in event_rows:
            events_table.add_row(event)
    else:
        events_table.add_row("Waiting for device responses...")
    if state["events_offset"] > 0:
        events_table.title = (
            f"DEVICE / COMMAND EVENTS — "
            f"{state['events_offset']} entries back"
        )
    events_border = (
        "yellow"
        if state["selected_panel"] == "events"
        else "magenta"
    )
    layout.add_row(
        Panel(events_table, border_style=events_border)
    )
    prompt = Text()
    prompt.append("Command> ", style="bold yellow")
    prompt.append(command_text, style="white")
    prompt.append("▌", style="bold cyan")
    layout.add_row(
        Panel(prompt, title="HOST CONTROL", border_style="green")
    )
    layout.add_row(
        Text(
            "Tab: switch panel | Ctrl+P: older | Ctrl+N: newer | "
            "L: live | Enter: send | Backspace: edit | QUIT: exit",
            style="dim",
        )
    )
    return layout


def open_serial_without_reset(port):
    """Attempt to set serial control lines before opening the specified port."""
    connection = serial.Serial(
        port=None,
        baudrate=115200,
        timeout=0,
        dsrdtr=False,
    )
    # Set control-line states before opening the port. This cannot guarantee that
    # every USB-to-serial interface will avoid resetting the board.
    connection.dtr = False
    connection.rts = False
    connection.port = port
    connection.open()
    return connection


def main():
    """Run the dashboard client and process telemetry, commands, and input."""
    # The serial bridge owns the physical Mega connection.
    # The receiver connects to the bridge over TCP.
    parser = StreamParser(
        frame_header=FRAME_HEADER,
        frame_size=FRAME_SIZE,
        validator=validate_frame,
    )
    # Keep editable command text separate from the device event history.
    command_text = ""
    # Centralized UI state is updated by device responses and validated frames.
    state = {
        "connected": False,
        "temperature": None,
        "sample_rate": 1000,
        "sequence": None,
        "crc_ok": False,
        "history": [],
        "events": [],
        "selected_panel": "telemetry",
        "telemetry_offset": 0,
        "events_offset": 0,
        "power_mode": "UNKNOWN",
        "effective_sample_period": None,
        "streaming_enabled": None,
        "last_power_mode_change": "Not yet confirmed",
    }
    old_terminal_settings = None
    try:
        # Connect to the bridge rather than reopening the physical serial port.
        with socket.create_connection(
            ("127.0.0.1", 8765),
            timeout=3,
        ) as connection:
            connection.settimeout(0.1)
            state["connected"] = True
            file, writer = open_telemetry_log()
            with file:
                console.print(
                    "[green]Connected to serial bridge at 127.0.0.1:8765[/green]"
                )
                console.print(f"Logging telemetry to: {LOG_FILE}")
                console.print("Click the terminal, then type commands.")
                # Save terminal settings and use character-at-a-time input so the
                # dashboard can refresh while the user types.
                terminal_fd = sys.stdin.fileno()
                old_terminal_settings = termios.tcgetattr(terminal_fd)
                tty.setcbreak(terminal_fd)
                with Live(
                    build_dashboard(state, command_text),
                    console=console,
                    refresh_per_second=10,
                    screen=False,
                    transient=False,
                ) as live:
                    last_refresh = 0.0
                    running = True
                    # Query current device configuration when the dashboard starts.
                    connection.sendall(b"STATUS\n")
                    connection.sendall(b"POWER_STATUS\n")
                    while running:
                        try:
                            data = connection.recv(128)
                        except socket.timeout:
                            data = None
                        except OSError as error:
                            state["connected"] = False
                            state["events"].append(f"Connection lost: {error}")
                            break
                        if data == b"":
                            state["connected"] = False
                            state["events"].append("Connection lost: serial bridge disconnected")
                            break
                        if data:
                            # TCP reads may split or combine messages arbitrarily;
                            # StreamParser reconstructs complete lines and binary frames.
                            for event in parser.feed(data):
                                if event.kind == "text":
                                    response = str(event.data).strip()
                                    if response:
                                        state["events"].append(response)
                                        update_power_status(state, response)
                                        if response == "OK,RATE":
                                            try:
                                                connection.sendall(b"STATUS\n")
                                            except OSError as error:
                                                state["events"].append(
                                                    f"Status refresh failed: {error}"
                                                )
                                elif event.kind == "error":
                                    state["events"].append(
                                        f"INVALID: {event.data}"
                                    )
                                elif event.kind == "frame":
                                    # Decode and log frames only after the stream parser
                                    # has identified a complete candidate frame.
                                    frame = bytes(event.data)
                                    valid, message = validate_frame(frame)
                                    if not valid:
                                        state["events"].append(
                                            f"INVALID: {message}"
                                        )
                                        continue
                                    sequence, timestamp_ms, temperature_c = (
                                        decode_frame(frame)
                                    )
                                    host_time = datetime.now(
                                        timezone.utc
                                    ).isoformat(timespec="milliseconds")
                                    write_telemetry_row(
                                        file,
                                        writer,
                                        host_time,
                                        sequence,
                                        timestamp_ms,
                                        temperature_c,
                                        message,
                                    )
                                    # Update displayed metrics only after validation,
                                    # decoding, and logging have succeeded.
                                    state["temperature"] = temperature_c
                                    state["sequence"] = sequence
                                    state["crc_ok"] = True
                                    state["history"].append(
                                        (
                                            datetime.now(timezone.utc).strftime("%H:%M:%S"),
                                            str(sequence),
                                            f"{timestamp_ms} ms",
                                            f"{temperature_c:.2f} °C",
                                            "OK",
                                        )
                                    )
                        # Poll keyboard input without blocking socket reception.
                        readable, _, _ = select.select(
                            [sys.stdin], [], [], 0
                        )
                        if readable:
                            key = sys.stdin.read(1)
                            if key == "\t":
                                if state["selected_panel"] == "telemetry":
                                    state["selected_panel"] = "events"
                                else:
                                    state["selected_panel"] = "telemetry"
                            # Navigation changes the visible history offset, not the log.
                            elif key == "\x10":  # Ctrl+P: older entries
                                if state["selected_panel"] == "telemetry":
                                    state["telemetry_offset"] = min(
                                        max(
                                            0,
                                            len(state["history"])
                                            - VISIBLE_TELEMETRY_ROWS,
                                        ),
                                        state["telemetry_offset"] + 1,
                                    )
                                else:
                                    state["events_offset"] = min(
                                        max(
                                            0,
                                            len(state["events"])
                                            - VISIBLE_EVENT_ROWS,
                                        ),
                                        state["events_offset"] + 1,
                                    )
                            elif key == "\x0e":  # Ctrl+N: newer entries
                                if state["selected_panel"] == "telemetry":
                                    state["telemetry_offset"] = max(
                                        0,
                                        state["telemetry_offset"] - 1,
                                    )
                                else:
                                    state["events_offset"] = max(
                                        0,
                                        state["events_offset"] - 1,
                                    )
                            elif key == "\x0c":  # Ctrl+L: return to latest entries
                                if state["selected_panel"] == "telemetry":
                                    state["telemetry_offset"] = 0
                                else:
                                    state["events_offset"] = 0
                            # Submit the completed command when Enter is pressed.
                            elif key in ("\r", "\n"):
                                command = command_text.strip()
                                command_text = ""
                                if command.upper() == "QUIT":
                                    running = False
                                elif command.upper() == "HELP":
                                    state["events"].append(
                                        "Commands: RATE,100-5000 | STREAM,0 | STREAM,1 | "
                                        "STATUS | POWER_MODE,LOW | POWER_MODE,NORMAL | "
                                        "POWER_STATUS | QUIT | Ctrl+L: latest entries"
                                    )
                                elif command:
                                    try:
                                        connection.sendall(
                                            (command + "\n").encode("ascii")
                                        )
                                        state["events"].append(f"> {command}")
                                    except (OSError, UnicodeEncodeError) as error:
                                        state["events"].append(
                                            f"Send error: {error}"
                                        )
                            elif key in ("\x7f", "\b"):
                                command_text = command_text[:-1]
                            elif key == "\x03":
                                running = False
                            elif key.isprintable():
                                command_text += key
                        # Refresh at a bounded cadence instead of rebuilding the UI
                        # for every received byte or keyboard event.
                        now = time.monotonic()
                        if now - last_refresh >= 0.1:
                            live.update(
                                build_dashboard(state, command_text)
                            )
                            last_refresh = now
    except OSError as error:
        console.print(
            f"[red]Connection error: {error}[/red]"
        )
    except KeyboardInterrupt:
        pass
    finally:
        # Restore terminal settings even if the receiver exits after an error.
        if old_terminal_settings is not None:
            termios.tcsetattr(
                sys.stdin.fileno(),
                termios.TCSADRAIN,
                old_terminal_settings,
            )
        console.print("\n[dim]Host receiver stopped.[/dim]")


if __name__ == "__main__":
    main()
