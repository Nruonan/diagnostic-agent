from collections import defaultdict
from contextvars import ContextVar
from dataclasses import dataclass
from threading import RLock


LabelSet = tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class LLMMetricLabels:
    provider: str
    model: str
    response_model: str

    def as_tuple(self) -> LabelSet:
        return (
            ("provider", self.provider),
            ("model", self.model),
            ("response_model", self.response_model),
        )


@dataclass(frozen=True)
class LLMUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None


_current_usage: ContextVar[LLMUsage | None] = ContextVar("llm_current_usage", default=None)


def set_current_llm_usage(input_tokens: int | None, output_tokens: int | None) -> None:
    _current_usage.set(LLMUsage(input_tokens=input_tokens, output_tokens=output_tokens))


def clear_current_llm_usage() -> None:
    _current_usage.set(None)


def get_current_llm_usage() -> LLMUsage | None:
    return _current_usage.get()


class LLMMetricsRegistry:
    def __init__(self) -> None:
        self._lock = RLock()
        self._calls_total: dict[LabelSet, int] = defaultdict(int)
        self._failures_total: dict[LabelSet, int] = defaultdict(int)
        self._latency_sum_ms: dict[LabelSet, float] = defaultdict(float)
        self._latency_count: dict[LabelSet, int] = defaultdict(int)
        self._input_tokens_total: dict[LabelSet, int] = defaultdict(int)
        self._output_tokens_total: dict[LabelSet, int] = defaultdict(int)
        self._retries_total: dict[LabelSet, int] = defaultdict(int)
        self._fallbacks_total: dict[tuple[tuple[str, str], ...], int] = defaultdict(int)

    def record_call(
        self,
        labels: LLMMetricLabels,
        latency_ms: float,
        input_tokens: int,
        output_tokens: int,
        success: bool,
    ) -> None:
        label_set = labels.as_tuple()
        with self._lock:
            self._calls_total[label_set] += 1
            self._latency_sum_ms[label_set] += latency_ms
            self._latency_count[label_set] += 1
            self._input_tokens_total[label_set] += input_tokens
            self._output_tokens_total[label_set] += output_tokens
            if not success:
                self._failures_total[label_set] += 1

    def record_retry(self, labels: LLMMetricLabels) -> None:
        with self._lock:
            self._retries_total[labels.as_tuple()] += 1

    def record_fallback(self, from_provider: str, to_provider: str) -> None:
        label_set = (("from_provider", from_provider), ("to_provider", to_provider))
        with self._lock:
            self._fallbacks_total[label_set] += 1

    def to_prometheus(self) -> str:
        with self._lock:
            lines = [
                "# HELP llm_calls_total Total LLM call attempts.",
                "# TYPE llm_calls_total counter",
                *self._counter_lines("llm_calls_total", self._calls_total),
                "# HELP llm_failures_total Failed LLM call attempts.",
                "# TYPE llm_failures_total counter",
                *self._counter_lines("llm_failures_total", self._failures_total),
                "# HELP llm_latency_ms_total Total LLM latency in milliseconds.",
                "# TYPE llm_latency_ms_total counter",
                *self._counter_lines("llm_latency_ms_total", self._latency_sum_ms),
                "# HELP llm_latency_ms_count LLM latency observation count.",
                "# TYPE llm_latency_ms_count counter",
                *self._counter_lines("llm_latency_ms_count", self._latency_count),
                "# HELP llm_input_tokens_total Input tokens sent to LLMs, estimated when provider usage is absent.",
                "# TYPE llm_input_tokens_total counter",
                *self._counter_lines("llm_input_tokens_total", self._input_tokens_total),
                "# HELP llm_output_tokens_total Output tokens returned by LLMs, estimated when provider usage is absent.",
                "# TYPE llm_output_tokens_total counter",
                *self._counter_lines("llm_output_tokens_total", self._output_tokens_total),
                "# HELP llm_retries_total LLM retry attempts.",
                "# TYPE llm_retries_total counter",
                *self._counter_lines("llm_retries_total", self._retries_total),
                "# HELP llm_fallbacks_total LLM provider fallback switches.",
                "# TYPE llm_fallbacks_total counter",
                *self._counter_lines("llm_fallbacks_total", self._fallbacks_total),
            ]
        return "\n".join(lines) + "\n"

    def _counter_lines(self, metric_name: str, values: dict[LabelSet, int | float]) -> list[str]:
        if not values:
            return [f"{metric_name} 0"]
        return [f"{metric_name}{self._format_labels(labels)} {value}" for labels, value in sorted(values.items())]

    def _format_labels(self, labels: LabelSet) -> str:
        escaped = [f'{key}="{self._escape_label(value)}"' for key, value in labels]
        return "{" + ",".join(escaped) + "}"

    def _escape_label(self, value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')


llm_metrics_registry = LLMMetricsRegistry()
