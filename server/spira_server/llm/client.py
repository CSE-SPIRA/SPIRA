"""One LLM interface for every stage (spec §6.1) and the call rule (spec §6.2).

    llm = get_llm()
    result = call_with_retry(llm, stage="s3", system=..., user=..., schema=IntentDecision,
                             check=format_check, retry_template=prompts.text("s3_retry.txt"), default=None)

A provider returns parsed JSON; `LLM.structured` turns refusals, empty or unparseable answers and schema failures into
`FormatError`. With `enforce_schema=False` (S4, spec §6.1) the provider does not ask for constrained output: it appends
the JSON schema to the system prompt as text (`schema_block`) and the stage validates the answer as usual.
`call_with_retry` tries twice, appends the stage's retry text listing only the errors, falls back to the stage default,
and writes one `llm_calls` row.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError

from . import calls


class LLMTimeout(Exception):
    pass


class LLMError(Exception):
    pass


class FormatError(Exception):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


@dataclass
class RawReply:
    data: Any = None              # parsed JSON object, or None
    text: str | None = None       # raw text when the provider gave text instead of JSON
    refusal: bool = False
    input_tokens: int | None = None
    output_tokens: int | None = None


class Provider(Protocol):
    name: str
    model: str

    def complete(self, *, stage: str, system: str, user: str, json_schema: dict, schema_name: str,
                 images: Sequence[bytes], timeout_s: int, enforce_schema: bool = True) -> RawReply: ...


SCHEMA_HEADER = ("[답 JSON 스키마]\n"
                 "답은 아래 JSON 스키마를 그대로 따르는 JSON 객체 하나다. "
                 "앞뒤에 다른 글이나 코드 블록 표시(```)를 쓰지 않는다.")


def schema_block(json_schema: dict) -> str:
    """The schema as prompt text, for calls without constrained output (appended to the system prompt)."""
    return SCHEMA_HEADER + "\n" + json.dumps(json_schema, ensure_ascii=False, separators=(",", ":"))


def parse_json_text(text: str) -> Any:
    """JSON from a text answer. Prose or a ```json fence around one object is cut away (first "{" to last "}")."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise
        return json.loads(text[start:end + 1])


def pydantic_errors(e: ValidationError) -> list[str]:
    out = []
    for err in e.errors():
        loc = ".".join(str(p) for p in err.get("loc", ()))
        out.append(f"{loc or '(전체)'}: {err.get('msg', '')}")
    return out


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0


class LLM:
    def __init__(self, provider: Provider, timeout_s: int = 60) -> None:
        self.provider = provider
        self.timeout_s = timeout_s
        self.last_usage = Usage()

    def structured(self, *, stage: str, system: str, user: str, schema: type[BaseModel],
                   images: Sequence[bytes] = (), episode_id: str | None = None, raw: bool = False,
                   enforce_schema: bool = True) -> BaseModel | dict:
        """One provider call. Raises LLMTimeout / LLMError / FormatError."""
        started = time.monotonic()
        reply = self.provider.complete(
            stage=stage, system=system, user=user, json_schema=schema.model_json_schema(),
            schema_name=schema.__name__, images=list(images), timeout_s=self.timeout_s,
            enforce_schema=enforce_schema,
        )
        self.last_usage = Usage(reply.input_tokens or 0, reply.output_tokens or 0,
                                int((time.monotonic() - started) * 1000))
        if reply.refusal:
            raise FormatError(["답하지 않고 거절했다. 스키마에 맞는 JSON으로 답해야 한다."])
        data = reply.data
        if data is None and reply.text:
            try:
                data = parse_json_text(reply.text)
            except json.JSONDecodeError:
                raise FormatError(["JSON이 아니다. 스키마에 맞는 JSON 하나로만 답해야 한다."]) from None
        if not isinstance(data, dict) or not data:
            raise FormatError(["빈 답이다. 스키마에 맞는 JSON으로 답해야 한다."])
        if raw:
            return data
        try:
            return schema.model_validate(data)
        except ValidationError as e:
            raise FormatError(pydantic_errors(e)) from None


@dataclass
class CallResult:
    value: Any
    ok: bool
    attempts: int
    outcome: str                      # ok / format_fail / timeout / error
    errors: list[str] = field(default_factory=list)


def retry_text(template: str, errors: list[str]) -> str:
    return template.replace("{ERRORS}", "\n".join(f"- {e}" for e in errors))


def call_with_retry(llm: LLM, *, stage: str, system: str, user: str, schema: type[BaseModel],
                    retry_template: str, default: Any, images: Sequence[bytes] = (),
                    episode_id: str | None = None, raw: bool = False,
                    check: Callable[[Any], list[str]] | None = None, max_attempts: int = 2,
                    enforce_schema: bool = True) -> CallResult:
    """Spec §6.2: never ask, never block. Writes one llm_calls row."""
    total = Usage()
    outcome, errors = "error", []
    message = user
    attempt = 0
    for attempt in range(1, max_attempts + 1):
        try:
            out = llm.structured(stage=stage, system=system, user=message, schema=schema, images=images,
                                 episode_id=episode_id, raw=raw, enforce_schema=enforce_schema)
            errors = check(out) if check else []
        except LLMTimeout:
            outcome, errors = "timeout", []
            _add(total, llm.last_usage)
            continue
        except LLMError:
            outcome, errors = "error", []
            _add(total, llm.last_usage)
            continue
        except FormatError as e:
            errors = e.errors
        _add(total, llm.last_usage)
        if not errors:
            calls.record(stage=stage, episode_id=episode_id, provider=llm.provider.name, model=llm.provider.model,
                         usage=total, attempts=attempt, outcome="ok")
            return CallResult(out, True, attempt, "ok")
        outcome = "format_fail"
        message = message + "\n\n" + retry_text(retry_template, errors)
    calls.record(stage=stage, episode_id=episode_id, provider=llm.provider.name, model=llm.provider.model,
                 usage=total, attempts=attempt, outcome=outcome)
    return CallResult(default, False, attempt, outcome, errors)


def _add(total: Usage, part: Usage) -> None:
    total.input_tokens += part.input_tokens
    total.output_tokens += part.output_tokens
    total.latency_ms += part.latency_ms
    part.input_tokens = part.output_tokens = part.latency_ms = 0


_llm: LLM | None = None


def get_llm() -> LLM:
    global _llm
    if _llm is None:
        from ..settings import get_settings
        from .providers import make_provider

        s = get_settings()
        _llm = LLM(make_provider(s.llm_provider, s.llm_model, s.llm_api_key), timeout_s=s.llm_timeout_s)
    return _llm


def set_llm(llm: LLM | None) -> None:
    """Tests and dry runs replace the LLM."""
    global _llm
    _llm = llm
