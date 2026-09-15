from performance_ai.activity_tracker import ProcessActivity


def activity(**overrides):
    values = dict(
        pid=10,
        name="steam.exe",
        rss_mb=500.0,
        cpu_percent=0.0,
        io_kbps=0.0,
        observation_seconds=600.0,
        seconds_since_foreground=1800.0,
        has_baseline=True,
        foreground=False,
    )
    values.update(overrides)
    return ProcessActivity(**values)


def reason(sample: ProcessActivity):
    return sample.protection_reason(
        cpu_threshold=1.0,
        io_threshold_kbps=256.0,
        recent_foreground_seconds=900,
        min_observation_seconds=60,
    )


def test_first_sample_is_protected_until_tracker_has_baseline():
    assert reason(activity(has_baseline=False)) == "warming_up"


def test_recent_foreground_app_is_protected():
    assert reason(activity(seconds_since_foreground=120.0)) == "recently_used"


def test_cpu_active_background_app_is_protected():
    assert reason(activity(cpu_percent=3.0)) == "cpu_active"


def test_io_active_background_app_is_protected():
    assert reason(activity(io_kbps=2048.0)) == "io_active"


def test_long_idle_inactive_app_is_eligible():
    assert reason(activity()) is None
