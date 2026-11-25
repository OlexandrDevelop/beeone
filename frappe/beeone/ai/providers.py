# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Model providers of the AI assistant: one call of the model with the tools.

A provider gets the neutral conversation and returns a `Reply`:
	messages: [{"role": "user"|"model"|"tool", "text": str, "calls": [Call], "results": [(Call, dict)], "raw": ...}]
	tools:    [{"name", "description", "parameters"}]  (JSON Schema of the arguments)
The raw turn of the model is kept, because Gemini wants its own parts (with the thought signatures) back.
"""

import json
from dataclasses import dataclass, field

import requests

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
TIMEOUT = 60


class ProviderError(Exception):
	"""The model could not answer: `kind` is quota, key, unavailable or bad_request."""

	def __init__(self, kind, message):
		super().__init__(message)
		self.kind = kind


@dataclass
class Call:
	name: str
	args: dict
	id: str = ""


@dataclass
class Reply:
	text: str = ""
	calls: list = field(default_factory=list)
	raw: object = None
	tokens_in: int = 0
	tokens_out: int = 0


def get_provider(settings):
	if settings.provider == "OpenAI compatible":
		return OpenAICompatible(settings)
	return Gemini(settings)


def _error_of(response):
	try:
		body = response.json()
		err = body.get("error") if isinstance(body, dict) else None
		message = (err or {}).get("message") if isinstance(err, dict) else None
	except ValueError:
		message = None
	message = message or response.text[:300] or str(response.status_code)
	if response.status_code == 429:
		return ProviderError("quota", message)
	if response.status_code in (401, 403) or "API key" in message:
		return ProviderError("key", message)
	if response.status_code >= 500:
		return ProviderError("unavailable", message)
	return ProviderError("bad_request", message)


def _post(url, payload, headers):
	try:
		response = requests.post(url, data=json.dumps(payload), headers=headers, timeout=TIMEOUT)
	except requests.RequestException as e:
		raise ProviderError("unavailable", str(e)) from e
	if response.status_code != 200:
		raise _error_of(response)
	return response.json()


class Gemini:
	def __init__(self, settings):
		self.model = settings.model or "gemini-flash-latest"
		self.key = settings.key
		self.max_tokens = settings.max_answer_tokens or 2048

	def contents(self, messages):
		out = []
		for m in messages:
			if m["role"] == "user":
				out.append({"role": "user", "parts": [{"text": m["text"]}]})
			elif m["role"] == "model":
				if m.get("raw"):
					out.append(m["raw"])
				else:
					parts = [{"text": m["text"]}] if m.get("text") else []
					parts += [{"functionCall": {"name": c.name, "args": c.args}} for c in m.get("calls") or []]
					out.append({"role": "model", "parts": parts})
			elif m["role"] == "tool":
				out.append(
					{
						"role": "user",
						"parts": [{"functionResponse": {"name": c.name, "response": result}} for c, result in m["results"]],
					}
				)
		return out

	def complete(self, system, messages, tools):
		payload = {
			"systemInstruction": {"parts": [{"text": system}]},
			"contents": self.contents(messages),
			"generationConfig": {"temperature": 0.2, "maxOutputTokens": self.max_tokens},
		}
		if tools:
			payload["tools"] = [{"functionDeclarations": [_gemini_tool(t) for t in tools]}]
		body = _post(
			GEMINI_URL.format(model=self.model),
			payload,
			{"Content-Type": "application/json", "x-goog-api-key": self.key},
		)
		candidates = body.get("candidates") or []
		if not candidates:
			reason = (body.get("promptFeedback") or {}).get("blockReason") or "empty answer"
			raise ProviderError("bad_request", reason)
		content = candidates[0].get("content") or {"role": "model", "parts": []}
		content.setdefault("role", "model")
		reply = Reply(raw=content)
		texts = []
		for part in content.get("parts") or []:
			if part.get("thought"):
				continue
			if "functionCall" in part:
				fc = part["functionCall"]
				reply.calls.append(Call(fc.get("name") or "", fc.get("args") or {}, fc.get("id") or ""))
			elif part.get("text"):
				texts.append(part["text"])
		reply.text = "".join(texts).strip()
		usage = body.get("usageMetadata") or {}
		reply.tokens_in = usage.get("promptTokenCount") or 0
		reply.tokens_out = (usage.get("candidatesTokenCount") or 0) + (usage.get("thoughtsTokenCount") or 0)
		return reply


def _gemini_tool(tool):
	declaration = {"name": tool["name"], "description": tool["description"]}
	if tool.get("parameters", {}).get("properties"):
		declaration["parameters"] = _gemini_schema(tool["parameters"])
	return declaration


def _gemini_schema(schema):
	"""Gemini takes no object without properties: such an argument goes as a JSON string (the tools parse it)."""
	if schema.get("type") == "object" and not schema.get("properties"):
		return {"type": "string", "description": (schema.get("description", "") + " Pass it as a JSON object string.").strip()}
	out = dict(schema)
	if "properties" in out:
		out["properties"] = {k: _gemini_schema(v) for k, v in out["properties"].items()}
	if "items" in out:
		out["items"] = _gemini_schema(out["items"])
	return out


class OpenAICompatible:
	"""/chat/completions with tools: a local server (Ollama, vLLM, LM Studio) or a gateway (OpenRouter)."""

	def __init__(self, settings):
		self.model = settings.model
		self.key = settings.key
		self.url = (settings.base_url or "").rstrip("/") + "/chat/completions"
		self.max_tokens = settings.max_answer_tokens or 2048

	def chat(self, system, messages):
		out = [{"role": "system", "content": system}]
		for m in messages:
			if m["role"] == "user":
				out.append({"role": "user", "content": m["text"]})
			elif m["role"] == "model":
				item = {"role": "assistant", "content": m.get("text") or None}
				if m.get("calls"):
					item["tool_calls"] = [
						{"id": c.id or f"call_{i}", "type": "function", "function": {"name": c.name, "arguments": json.dumps(c.args, ensure_ascii=False)}}
						for i, c in enumerate(m["calls"])
					]
				out.append(item)
			elif m["role"] == "tool":
				for i, (c, result) in enumerate(m["results"]):
					out.append({"role": "tool", "tool_call_id": c.id or f"call_{i}", "content": json.dumps(result, ensure_ascii=False, default=str)})
		return out

	def complete(self, system, messages, tools):
		payload = {"model": self.model, "messages": self.chat(system, messages), "temperature": 0.2, "max_tokens": self.max_tokens}
		if tools:
			payload["tools"] = [{"type": "function", "function": t} for t in tools]
		headers = {"Content-Type": "application/json"}
		if self.key:
			headers["Authorization"] = f"Bearer {self.key}"
		body = _post(self.url, payload, headers)
		choice = (body.get("choices") or [{}])[0].get("message") or {}
		reply = Reply(text=(choice.get("content") or "").strip())
		for tc in choice.get("tool_calls") or []:
			fn = tc.get("function") or {}
			try:
				args = json.loads(fn.get("arguments") or "{}")
			except ValueError:
				args = {}
			reply.calls.append(Call(fn.get("name") or "", args if isinstance(args, dict) else {}, tc.get("id") or ""))
		usage = body.get("usage") or {}
		reply.tokens_in = usage.get("prompt_tokens") or 0
		reply.tokens_out = usage.get("completion_tokens") or 0
		return reply
