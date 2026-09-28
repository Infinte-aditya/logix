def test_spike_mode_produces_higher_error_ratio_than_normal(
    generator, read_lines, error_ratio
):
    for _ in range(500):
        generator.run_once()
    normal_lines = read_lines(generator.path)
    assert len(normal_lines) == 500
    generator.start_spike()
    for _ in range(500):
        generator.run_once()
    spike_lines = read_lines(generator.path)[500:]
    assert len(spike_lines) == 500
    normal_ratio = error_ratio(normal_lines)
    spike_ratio = error_ratio(spike_lines)
    assert spike_ratio > normal_ratio
    assert 0.10 <= spike_ratio <= 0.65