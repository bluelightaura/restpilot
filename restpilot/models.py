"""Pydantic models describing configuration, requests, responses and specs."""

from __future__ import annotations

import json
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class HttpMethod(str, Enum):
    """HTTP methods supported by RestPilot."""

    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"
    HEAD = "HEAD"
    OPTIONS = "OPTIONS"

    @classmethod
    def parse(cls, value: str) -> HttpMethod:
        """Parse a user supplied method name, case-insensitively."""
        try:
            return cls(value.strip().upper())
        except ValueError:
            supported = ", ".join(method.value for method in cls)
            raise ValueError(f"unsupported HTTP method {value!r}. Supported: {supported}") from None


#: Methods that are safe to retry automatically (idempotent, no side effects).
SAFE_METHODS: frozenset[HttpMethod] = frozenset(
    {HttpMethod.GET, HttpMethod.HEAD, HttpMethod.OPTIONS}
)

#: Response statuses that trigger a retry for safe methods.
RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({502, 503, 504})


class ResponseKind(str, Enum):
    """Shape of a documented JSON response body."""

    OBJECT = "object"
    ARRAY = "array"
    UNKNOWN = "unknown"
    NONE = "none"


class EnvironmentConfig(BaseModel):
    """A named target API: base URL plus transport defaults."""

    model_config = ConfigDict(extra="forbid")

    base_url: str
    timeout: float = Field(default=10.0, gt=0, le=600)
    verify_ssl: bool = True
    headers: dict[str, str] = Field(default_factory=dict)

    @field_validator("base_url")
    @classmethod
    def _validate_base_url(cls, value: str) -> str:
        url = value.strip()
        if not url:
            raise ValueError("base_url must not be empty")
        if not url.startswith(("http://", "https://")):
            raise ValueError("base_url must start with http:// or https://")
        return url.rstrip("/")


class ApplicationConfig(BaseModel):
    """The merged RestPilot configuration."""

    model_config = ConfigDict(extra="forbid")

    current_environment: str | None = None
    environments: dict[str, EnvironmentConfig] = Field(default_factory=dict)


class RequestDefinition(BaseModel):
    """Everything needed to perform a single HTTP call."""

    model_config = ConfigDict(extra="forbid")

    method: HttpMethod
    url: str
    headers: dict[str, str] = Field(default_factory=dict)
    query: list[tuple[str, str]] = Field(default_factory=list)
    json_body: Any = None
    content: str | None = None
    timeout: float = Field(default=10.0, gt=0, le=600)
    verify_ssl: bool = True

    @property
    def is_safe(self) -> bool:
        """Whether the request may be retried automatically."""
        return self.method in SAFE_METHODS


class ResponseResult(BaseModel):
    """The outcome of an executed request."""

    model_config = ConfigDict(extra="forbid")

    method: HttpMethod
    url: str
    status_code: int
    reason_phrase: str = ""
    request_headers: dict[str, str] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)
    body: str = ""
    elapsed_ms: float = 0.0
    attempts: int = 1

    @property
    def content_type(self) -> str | None:
        """The response ``Content-Type`` header, if present."""
        for name, value in self.headers.items():
            if name.lower() == "content-type":
                return value
        return None

    @property
    def is_json(self) -> bool:
        """Whether the response advertises a JSON payload."""
        content_type = self.content_type or ""
        return "json" in content_type.lower()

    def json_body(self) -> Any:
        """Return the parsed JSON body, or ``None`` when it is not valid JSON."""
        if not self.body:
            return None
        try:
            return json.loads(self.body)
        except json.JSONDecodeError:
            return None


class OpenAPIEndpoint(BaseModel):
    """A single operation extracted from an OpenAPI document."""

    model_config = ConfigDict(extra="forbid")

    method: HttpMethod
    path: str
    summary: str = ""
    operation_id: str | None = None
    success_status: int = 200
    response_kind: ResponseKind = ResponseKind.UNKNOWN
    request_example: Any = None
    tags: list[str] = Field(default_factory=list)

    @property
    def key(self) -> str:
        """A stable ``METHOD /path`` identifier."""
        return f"{self.method.value} {self.path}"


class OpenAPIDocument(BaseModel):
    """The normalized representation stored after ``restpilot import-api``."""

    model_config = ConfigDict(extra="forbid")

    title: str
    version: str
    source: str = ""
    endpoints: list[OpenAPIEndpoint] = Field(default_factory=list)


class GeneratedTest(BaseModel):
    """A rendered pytest module."""

    model_config = ConfigDict(extra="forbid")

    test_name: str
    file_name: str
    content: str
    endpoint: OpenAPIEndpoint | None = None
