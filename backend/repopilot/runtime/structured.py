"""Schema-validated model calls: small open models get a second (and third) chance to return valid JSON."""

from __future__ import annotations

from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from repopilot.runtime.client import Message, Runtime
from repopilot.runtime.roles import Role

T = TypeVar("T", bound=BaseModel)


class ModelOutputError(RuntimeError):
    def __init__(self, last_output: str, error: str):
        super().__init__(f"Model output did not match the schema: {error}")
        self.last_output = last_output
        self.error = error


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()


async def structured_call[T: BaseModel](
    runtime: Runtime,
    role: Role,
    schema: type[T],
    messages: list[Message],
    *,
    retries: int = 2,
    max_tokens: int = 2048,
) -> T:
    convo = list(messages)
    json_schema = schema.model_json_schema()
    last_output, last_error = "", ""
    for _ in range(retries + 1):
        try:
            last_output = await runtime.chat(role, convo, json_schema=json_schema, max_tokens=max_tokens)
        except httpx.HTTPStatusError as exc:
            # Ollama aborts a generation stuck repeating itself; that is a bad answer, so retry.
            if "repeat" not in exc.response.text:
                raise
            last_output, last_error = "", "generation aborted: the model kept repeating itself"
            convo = [
                *convo,
                {
                    "role": "user",
                    "content": "Your previous answer was cut off because it kept repeating itself. "
                    "Answer again, briefly, as JSON matching the schema.",
                },
            ]
            continue
        try:
            return schema.model_validate_json(_strip_fences(last_output))
        except ValidationError as exc:
            last_error = str(exc.errors(include_url=False)[:3])
            convo = [
                *convo,
                {"role": "assistant", "content": last_output},
                {
                    "role": "user",
                    "content": f"Your previous output was invalid: {last_error}. Return only JSON matching the schema, and keep every text field short.",
                },
            ]
    raise ModelOutputError(last_output, last_error)
