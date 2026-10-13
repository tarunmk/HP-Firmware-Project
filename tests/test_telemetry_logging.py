import csv

from host.telemetry_receiver import (
    CSV_HEADER,
    open_telemetry_log,
    write_telemetry_row,
)


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as file:
        return list(csv.reader(file))


# Tests that a new telemetry log is created with the correct CSV header.
def test_new_log_creates_correct_header(tmp_path):
    path = tmp_path / "telemetry_log.csv"

    file, writer = open_telemetry_log(path)
    file.close()

    assert read_csv(path) == [CSV_HEADER]


# Tests that reopening an existing log appends rows without duplicating the header.
def test_existing_log_does_not_duplicate_header(tmp_path):
    path = tmp_path / "telemetry_log.csv"

    file, writer = open_telemetry_log(path)
    write_telemetry_row(
        file, writer, "2026-10-12T12:00:00+00:00",
        1, 100, 23.456, "CRC OK",
    )
    file.close()

    file, writer = open_telemetry_log(path)
    write_telemetry_row(
        file, writer, "2026-10-12T12:00:01+00:00",
        2, 200, 24.0, "CRC OK",
    )
    file.close()

    rows = read_csv(path)

    assert rows[0] == CSV_HEADER
    assert len(rows) == 3
    assert rows[1][1:] == ["1", "100", "23.46", "CRC OK"]
    assert rows[2][1:] == ["2", "200", "24.00", "CRC OK"]


# Tests that an existing empty log file receives the correct CSV header.
def test_empty_log_gets_header(tmp_path):
    path = tmp_path / "telemetry_log.csv"
    path.touch()

    file, writer = open_telemetry_log(path)
    file.close()

    assert read_csv(path) == [CSV_HEADER]


# Tests that telemetry data is flushed to disk and readable before the file is closed.
def test_write_telemetry_row_flushes_data(tmp_path):
    path = tmp_path / "telemetry_log.csv"

    file, writer = open_telemetry_log(path)
    write_telemetry_row(
        file, writer, "2026-10-12T12:00:00+00:00",
        42, 1234, 21.678, "CRC OK",
    )

    # Read the file while the writer is still open.
    rows = read_csv(path)
    file.close()

    assert len(rows) == 2
    assert rows[1] == [
        "2026-10-12T12:00:00+00:00",
        "42",
        "1234",
        "21.68",
        "CRC OK",
    ]