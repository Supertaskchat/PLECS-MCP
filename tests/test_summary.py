import math

from plecs_mcp.summary import summarize_frequency, summarize_result, summarize_time_series


def test_time_series_stats_for_two_signals():
    summary = summarize_time_series({"Time": [0, 1, 2], "Values": [[1, 2, 3], [4, 5, 6]]})
    assert summary["time"] == {"points": 3, "start": 0, "stop": 2}
    first, second = summary["signals"]
    assert first["mean"] == 2 and first["rms"] == math.sqrt(14 / 3)
    assert first["p2p"] == 2 and second["min"] == 4


def test_time_series_accepts_time_major_values():
    # 3 time points x 2 signals must be transposed to 2 channels of 3 samples
    summary = summarize_time_series({"Time": [0, 1, 2], "Values": [[1, 10], [2, 20], [3, 30]]})
    assert len(summary["signals"]) == 2
    assert summary["signals"][0]["last"] == 3
    assert summary["signals"][1]["last"] == 30


def test_empty_result_is_reported_not_crashing():
    summary = summarize_time_series({"Time": [], "Values": []})
    assert summary["time"]["points"] == 0
    assert summary["signals"] == []


def test_frequency_summary_finds_crossover_and_margin():
    # |H| = 5, 1, 0.707 ; phase at 100 Hz = -90 deg -> PM = 90 deg
    summary = summarize_frequency(
        {"F": [10, 100, 1000], "Gr": [[5, 0, -0.5]], "Gi": [[0, -1, -0.5]]}
    )
    response = summary["responses"][0]
    assert response["gain_crossover_hz"] == 100
    assert response["phase_margin_deg"] == 90
    assert response["stable"] is True


def test_frequency_summary_handles_flat_arrays_and_non_finite():
    summary = summarize_frequency({"F": [1, 10], "Gr": [0, 0], "Gi": [0, 0]})
    assert summary["responses"][0]["magnitude_db"]["min"] is None
    assert "gain_crossover_hz" not in summary["responses"][0]


def test_summarize_result_dispatch():
    assert summarize_result({"F": [1], "Gr": [1], "Gi": [0]})["kind"] == "frequency-domain"
    assert summarize_result({"Time": [0], "Values": [[1]]})["kind"] == "time-series"
    assert summarize_result({"other": 1}) == {"other": 1}
