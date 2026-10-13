import pytest

from host.telemetry_receiver import update_power_status


def make_state():
    return {
        "power_mode": "UNKNOWN",
        "sample_rate": 1000,
        "streaming_enabled": None,
        "effective_sample_period": None,
        "last_power_mode_change": "Not yet confirmed",
    }


# Tests that NORMAL mode reports the configured sampling interval correctly.
def test_status_normal_sets_confirmed_sample_interval():
    state = make_state()

    update_power_status(state, "STATUS,1000,1,NORMAL")

    assert state["power_mode"] == "NORMAL"
    assert state["sample_rate"] == 1000
    assert state["streaming_enabled"] is True
    assert state["effective_sample_period"] == 1000
    assert state["last_power_mode_change"] != "Not yet confirmed"


# Tests that LOW mode uses a 5000 ms effective sampling interval.
def test_status_low_uses_5000_ms_effective_interval():
    state = make_state()

    update_power_status(state, "STATUS,500,1,LOW")

    assert state["power_mode"] == "LOW"
    assert state["sample_rate"] == 500
    assert state["streaming_enabled"] is True
    assert state["effective_sample_period"] == 5000


# Tests that switching to LOW mode preserves the configured sample rate.
def test_power_status_low_preserves_configured_sample_rate():
    state = make_state()
    state["power_mode"] = "NORMAL"
    state["sample_rate"] = 750
    state["effective_sample_period"] = 750

    update_power_status(state, "POWER_STATUS,LOW")

    assert state["power_mode"] == "LOW"
    assert state["sample_rate"] == 750
    assert state["effective_sample_period"] == 5000


# Tests that switching back to NORMAL restores the configured interval.
def test_switching_back_to_normal_restores_configured_interval():
    state = make_state()
    state["power_mode"] = "LOW"
    state["sample_rate"] = 750
    state["effective_sample_period"] = 5000

    update_power_status(state, "POWER_STATUS,NORMAL")

    assert state["power_mode"] == "NORMAL"
    assert state["effective_sample_period"] == 750


# Tests that power-mode acknowledgments update the effective sampling interval.
def test_power_mode_acknowledgment_updates_effective_interval():
    state = make_state()
    state["sample_rate"] = 1200

    update_power_status(state, "OK,POWER_MODE,LOW")

    assert state["power_mode"] == "LOW"
    assert state["effective_sample_period"] == 5000

    update_power_status(state, "OK,POWER_MODE,NORMAL")

    assert state["power_mode"] == "NORMAL"
    assert state["effective_sample_period"] == 1200


# Tests that invalid or unsupported responses leave the state unchanged.
@pytest.mark.parametrize(
    "response",
    [
        "STATUS,abc,1,NORMAL",
        "STATUS,99,1,NORMAL",
        "STATUS,5001,1,NORMAL",
        "STATUS,1000,2,NORMAL",
        "STATUS,1000,1,UNKNOWN",
        "STATUS,1000,1,NORMAL,EXTRA",
        "POWER_STATUS,UNKNOWN",
        "OK,POWER_MODE,UNKNOWN",
        "ERR,RATE",
        "",
    ],
)
def test_invalid_responses_do_not_change_state(response):
    state = make_state()
    before = state.copy()

    update_power_status(state, response)

    assert state == before


# Tests that the minimum and maximum supported sample rates are accepted.
@pytest.mark.parametrize("sample_rate", [100, 5000])
def test_status_accepts_sample_rate_boundaries(sample_rate):
    state = make_state()

    update_power_status(
        state, f"STATUS,{sample_rate},1,NORMAL"
    )

    assert state["sample_rate"] == sample_rate
    assert state["effective_sample_period"] == sample_rate


# Tests that streaming can be disabled without changing the sample interval.
def test_status_records_streaming_disabled():
    state = make_state()

    update_power_status(state, "STATUS,1000,0,NORMAL")

    assert state["streaming_enabled"] is False
    assert state["effective_sample_period"] == 1000