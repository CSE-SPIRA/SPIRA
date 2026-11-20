"""Provider adapters (spec §6.1). Each one asks for JSON that follows the stage's Pydantic schema with the provider's
own structured-output feature, attaches images, and reports token usage. Temperature is not set.

These adapters are exercised for real only in dry runs; mock tests never reach them.

`enforce_schema=False` (S4, spec §6.1): no constrained output; the schema goes into the system prompt as text
(`schema_block`) and the stage validates the answer itself.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Sequence

from .client import LLMError, LLMTimeout, RawReply, parse_json_text, schema_block


def image_media_type(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    raise ValueError("only png and jpeg images are supported")


def anthropic_output_schema(json_schema: dict) -> dict:
    """The stage's Pydantic JSON schema in the form Anthropic JSON outputs accept (`output_config.format`):
    every object gets `additionalProperties: false`, `oneOf` becomes `anyOf`, and constraints the API does not take
    (minimum, maximum, minLength …) move into the description. The stage still validates them itself."""
    from anthropic import transform_schema

    return transform_schema(json_schema)


class AnthropicProvider:
    """JSON outputs (`output_config.format` json_schema). Forced tool use (`tool_choice` tool/any) is refused by
    current models, and a large schema can exceed the compiled grammar size (dry run A, 11-21; S4 sends the schema as
    text instead)."""

    name = "anthropic"

    def __init__(self, model: str, api_key: str) -> None:
        import anthropic

        self._sdk = anthropic
        self.model = model
        self.client = anthropic.Anthropic(api_key=api_key, max_retries=0)

    def complete(self, *, stage: str, system: str, user: str, json_schema: dict, schema_name: str,
                 images: Sequence[bytes], timeout_s: int, enforce_schema: bool = True) -> RawReply:
        content: list[dict] = [
            {"type": "image", "source": {"type": "base64", "media_type": image_media_type(img),
                                         "data": base64.b64encode(img).decode()}}
            for img in images
        ]
        content.append({"type": "text", "text": user})
        extra: dict = {}
        if enforce_schema:
            extra["output_config"] = {"format": {"type": "json_schema", "schema": anthropic_output_schema(json_schema)}}
        else:
            system = system + "\n\n" + schema_block(json_schema)
        try:
            msg = self.client.messages.create(
                model=self.model,
                max_tokens=8192,
                system=system,
                messages=[{"role": "user", "content": content}],
                timeout=timeout_s,
                **extra,
            )
        except self._sdk.APITimeoutError as e:
            raise LLMTimeout(str(e)) from e
        except self._sdk.APIError as e:
            raise LLMError(str(e)) from e
        usage = getattr(msg, "usage", None)
        text = "".join(getattr(b, "text", "") for b in msg.content if getattr(b, "type", "") == "text") or None
        data = None
        if text and msg.stop_reason != "max_tokens":
            try:
                data = parse_json_text(text)
            except json.JSONDecodeError:
                data = None
        return RawReply(
            data=data,
            text=None if data is not None else text,
            refusal=msg.stop_reason == "refusal" or text is None,
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
        )


class OpenAIProvider:
    name = "openai"

    def __init__(self, model: str, api_key: str) -> None:
        import openai

        self._sdk = openai
        self.model = model
        self.client = openai.OpenAI(api_key=api_key, max_retries=0)

    def complete(self, *, stage: str, system: str, user: str, json_schema: dict, schema_name: str,
                 images: Sequence[bytes], timeout_s: int, enforce_schema: bool = True) -> RawReply:
        content: list[dict] = [{"type": "text", "text": user}]
        for img in images:
            url = f"data:{image_media_type(img)};base64,{base64.b64encode(img).decode()}"
            content.append({"type": "image_url", "image_url": {"url": url}})
        if enforce_schema:
            response_format = {"type": "json_schema",
                               "json_schema": {"name": schema_name, "schema": json_schema, "strict": False}}
        else:
            system = system + "\n\n" + schema_block(json_schema)
            response_format = {"type": "json_object"}
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": content}],
                response_format=response_format,
                timeout=timeout_s,
            )
        except self._sdk.APITimeoutError as e:
            raise LLMTimeout(str(e)) from e
        except self._sdk.APIError as e:
            raise LLMError(str(e)) from e
        choice = resp.choices[0].message
        usage = resp.usage
        return RawReply(
            text=choice.content, refusal=bool(getattr(choice, "refusal", None)),
            input_tokens=getattr(usage, "prompt_tokens", None), output_tokens=getattr(usage, "completion_tokens", None),
        )


class GeminiProvider:
    name = "gemini"

    def __init__(self, model: str, api_key: str) -> None:
        from google import genai

        self._genai = genai
        self.model = model
        self.client = genai.Client(api_key=api_key)

    def complete(self, *, stage: str, system: str, user: str, json_schema: dict, schema_name: str,
                 images: Sequence[bytes], timeout_s: int, enforce_schema: bool = True) -> RawReply:
        from google.genai import errors, types

        parts = [types.Part.from_bytes(data=img, mime_type=image_media_type(img)) for img in images]
        parts.append(types.Part.from_text(text=user))
        try:
            resp = self.client.models.generate_content(
                model=self.model,
                contents=[types.Content(role="user", parts=parts)],
                config=types.GenerateContentConfig(
                    system_instruction=system if enforce_schema else system + "\n\n" + schema_block(json_schema),
                    response_mime_type="application/json",
                    response_json_schema=json_schema if enforce_schema else None,
                    http_options=types.HttpOptions(timeout=timeout_s * 1000),
                ),
            )
        except errors.APIError as e:
            if getattr(e, "code", None) in (408, 504):
                raise LLMTimeout(str(e)) from e
            raise LLMError(str(e)) from e
        except TimeoutError as e:
            raise LLMTimeout(str(e)) from e
        usage = getattr(resp, "usage_metadata", None)
        text = resp.text
        data = None
        if text:
            try:
                data = parse_json_text(text)
            except json.JSONDecodeError:
                data = None
        return RawReply(
            data=data, text=None if data is not None else text, refusal=not text,
            input_tokens=getattr(usage, "prompt_token_count", None),
            output_tokens=getattr(usage, "candidates_token_count", None),
        )


def make_provider(provider: str, model: str, api_key: str):
    if provider == "mock":
        from .mock import MockProvider

        return MockProvider(model=model or "mock")
    if provider == "anthropic":
        return AnthropicProvider(model, api_key)
    if provider == "openai":
        return OpenAIProvider(model, api_key)
    if provider == "gemini":
        return GeminiProvider(model, api_key)
    raise ValueError(f"unknown LLM_PROVIDER {provider}")
