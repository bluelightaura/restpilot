"""A thin, predictable HTTP client on top of HTTPX."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from restpilot.exceptions import RequestExecutionError
from restpilot.models import RETRYABLE_STATUS_CODES, RequestDefinition, ResponseResult

#: Hard upper bound on retries, whatever the caller asks for.
MAX_RETRIES = 2


@dataclass(frozen=True)
class RetryPolicy:
    """How often and how fast a safe request may be retried.

    Retries only ever apply to GET, HEAD and OPTIONS: replaying POST, PATCH or
    DELETE could duplicate side effects.
    """

    max_retries: int = MAX_RETRIES
    backoff_seconds: float = 0.25

    def attempts_for(self, request: RequestDefinition) -> int:
        """Return the total number of attempts allowed for ``request``."""
        if not request.is_safe:
            return 1
        return 1 + max(0, min(self.max_retries, MAX_RETRIES))


class ApiClient:
    """Execute :class:`RequestDefinition` objects and report the outcome."""

    def __init__(
        self,
        *,
        retry_policy: RetryPolicy | None = None,
        sleep: Callable[[float], None] = time.sleep,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        """Configure the retry policy, the sleep function and the transport."""
        self.retry_policy = retry_policy or RetryPolicy()
        self._sleep = sleep
        self._transport = transport

    def execute(self, request: RequestDefinition) -> ResponseResult:
        """Perform ``request`` and return its result.

        Args:
            request: The fully built request definition.

        Returns:
            The response, including timing and the number of attempts made.

        Raises:
            RequestExecutionError: On timeouts, connection failures or other
                transport level errors.
        """
        max_attempts = self.retry_policy.attempts_for(request)
        attempt = 0
        params: list[tuple[str, str | int | float | bool | None]] = list(request.query)
        with httpx.Client(
            timeout=request.timeout,
            verify=request.verify_ssl,
            follow_redirects=True,
            transport=self._transport,
        ) as client:
            while True:
                attempt += 1
                started = time.perf_counter()
                try:
                    response = client.request(
                        request.method.value,
                        request.url,
                        headers=request.headers or None,
                        params=params or None,
                        json=request.json_body,
                        content=request.content,
                    )
                except httpx.TimeoutException as error:
                    if attempt < max_attempts:
                        self._backoff(attempt)
                        continue
                    raise RequestExecutionError(
                        f"request to {request.url} timed out after {request.timeout}s.",
                        hint="Increase the limit with --timeout or check that the API is up.",
                    ) from error
                except httpx.TransportError as error:
                    if attempt < max_attempts:
                        self._backoff(attempt)
                        continue
                    raise RequestExecutionError(
                        f"cannot reach {request.url}: {error}.",
                        hint="Check the base URL of the current environment and your network.",
                    ) from error

                elapsed_ms = (time.perf_counter() - started) * 1000
                if response.status_code in RETRYABLE_STATUS_CODES and attempt < max_attempts:
                    self._backoff(attempt)
                    continue
                return self._to_result(request, response, elapsed_ms, attempt)

    def _backoff(self, attempt: int) -> None:
        delay = self.retry_policy.backoff_seconds * attempt
        if delay > 0:
            self._sleep(delay)

    @staticmethod
    def _to_result(
        request: RequestDefinition,
        response: httpx.Response,
        elapsed_ms: float,
        attempts: int,
    ) -> ResponseResult:
        return ResponseResult(
            method=request.method,
            url=str(response.request.url),
            status_code=response.status_code,
            reason_phrase=response.reason_phrase or "",
            request_headers=dict(response.request.headers),
            headers=dict(response.headers),
            body=response.text,
            elapsed_ms=round(elapsed_ms, 2),
            attempts=attempts,
        )
