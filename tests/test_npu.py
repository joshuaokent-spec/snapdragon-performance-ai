from performance_ai.npu import _looks_like_npu_counter


def test_text_input_host_is_not_an_npu_counter():
    assert not _looks_like_npu_counter(r"\Process(TextInputHost)\% Processor Time")


def test_real_npu_engine_counter_is_detected():
    assert _looks_like_npu_counter(r"\NPU Engine(*)\Utilization Percentage")


def test_numbered_npu_counter_is_detected():
    assert _looks_like_npu_counter(r"\NPU0\Usage")
