import asyncio
import contextlib
import logging
from typing import Callable
from typing import Dict
from typing import List

from aiohttp.web import Request

from .checks import Check
from .trace import Span


log = logging.getLogger(__name__)


class CheckTraceCountHeader(Check):
    name = "trace_count_header"
    description = """
The number of traces included in a payload must be included as the
X-Datadog-Trace-Count http header with each payload. The value of the
header must match the number of traces included in the payload.
""".strip()
    default_enabled = True

    def check(self, headers: Dict[str, str], num_traces: int) -> None:  # type: ignore
        if "X-Datadog-Trace-Count" not in headers:
            self.fail("X-Datadog-Trace-Count header not found in headers")
            return
        try:
            count = int(headers["X-Datadog-Trace-Count"])
        except ValueError:
            self.fail("X-Datadog-Trace-Count header is not a valid integer")
            return
        else:
            if num_traces != count:
                self.fail(
                    f"X-Datadog-Trace-Count value ({count}) does not match actual number of traces ({num_traces})"
                )


class CheckMetaTracerVersionHeader(Check):
    name = "meta_tracer_version_header"
    description = (
        """v0.4 payloads must include the Datadog-Meta-Tracer-Version header."""
    )
    default_enabled = True

    def check(self, headers: Dict[str, str]) -> None:  # type: ignore
        if "Datadog-Meta-Tracer-Version" not in headers:
            self.fail("Datadog-Meta-Tracer-Version not found in headers")


class CheckTraceContentLength(Check):
    name = "trace_content_length"
    description = """
The max content size of a trace payload is 50MB.
""".strip()
    default_enabled = True

    def check(self, headers: Dict[str, str]) -> None:  # type: ignore
        if "Content-Length" not in headers:
            self.fail(
                f"content length header 'Content-Length' not in http headers {headers}"
            )
            return
        content_length = int(headers["Content-Length"])
        if content_length > 5e7:
            self.fail(f"content length {content_length} too large.")


class CheckTraceStallAsync(Check):
    name = "trace_stall"
    description = """
Stall the trace (mimicking an overwhelmed or throttled agent) for the given duration in seconds.

Enable the check by submitting the X-Datadog-Test-Stall-Seconds http header (unit is seconds)
with the request.

Note that only the request for this trace is stalled, subsequent requests will not be
affected.
""".strip()
    default_enabled = True

    async def check(self, headers: Dict[str, str], request: Request) -> None:  # type: ignore
        if "X-Datadog-Test-Stall-Seconds" in headers:
            duration = float(headers["X-Datadog-Test-Stall-Seconds"])
        else:
            duration = request.app["trace_request_delay"]
        if duration > 0:
            log.info("Stalling for %r seconds.", duration)
            await asyncio.sleep(duration)


class CheckHttpSpanStructure(Check):
    name = "span_spec_http_client"
    description = """
The structure of HTTP client spans must match our expectations.
""".strip()
    default_enabled = True

    @contextlib.contextmanager
    def using_span(self, span):
        try:
            self.span = span
            yield self
        finally:
            self.span = None

    def property_matches(self, property_name: str, expected_value: str):
        actual_value = self.span[property_name]
        if self.span[property_name] != expected_value:
            self.fail(f"Property '{property_name}' has value '{actual_value}', expected '{expected_value}'.")

    def tag_is_present(self, tagname: str):
        if tagname not in self.span["meta"]:
            self.fail(f"Tag '{tagname}' is not present.")

    def tag_matches(self, tagname: str, expected_value: str):
        actual_value = self.span["meta"][tagname]
        if self.span["meta"][tagname] != expected_value:
            self.fail(f"Tag '{tagname}' has value '{actual_value}', expected '{expected_value}'.")

    def run_check(self, spec):
        spec(self)

    def check(self, traces: List[List[Span]]) -> None:  # type: ignore
        for trace in traces:
            for span in trace:
                with self.using_span(span) as assertion:
                    if span["type"] == "http" and span["meta"]["span.kind"] == "client":
                        assertion.run_check(SpanSpec.http_client)

class SpanSpec(object):
    @staticmethod
    def http_client(check: CheckHttpSpanStructure) -> None:
        check.tag_is_present("http.method") 
        check.tag_is_present("http.status_code")
        check.tag_is_present("http.url")
        check.tag_matches("span.kind", "client")
        check.property_matches("type", "http")