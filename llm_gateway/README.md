# LLM Gateway

A lightweight multi-model LLM gateway with native tool-use, prompt caching, reasoning budgets, structured output, and capability-aware routing.

Runs on port **8100**. Reads keys from `../.env`.

**Supported providers:** Gemini · NVIDIA 

---

## Quick Start

```bash
cd llm_gateway
./run.sh          # creates .venv, starts on port 8100
```

---

## Endpoints

| Endpoint | Description |
|---|---|
| `POST /v1/chat` | Main chat endpoint |
| `GET /v1/providers` | List active providers |
| `GET /v1/capabilities` | Per-provider capability matrix |
| `GET /v1/status` | Rate-limit status + today's call counts |
| `GET /v1/calls` | Recent call log |
| `GET /` | Dashboard UI |

---

## Request

```jsonc
{
  "messages": [{"role": "user", "content": "..."}],
  "provider": "g",          // optional: "g"/"gemini", "n"/"nvidia"
  "model": "...",            // optional model override
  "max_tokens": 2048,
  "temperature": 0.7,
  "system": "...",           // or [{\"text\": \"...\", \"cache\": true}]
  "cache_system": true,      // cache the whole system block
  "tools": [...],            // tool definitions
  "tool_choice": "auto",
  "reasoning": "high",       // "off" | "low" | "medium" | "high"
  "response_format": {"type": "json_schema", "schema": {...}}
}
```

Tool result turn:
```jsonc
{"role": "tool", "tool_call_id": "<id>", "tool_name": "add", "content": "{\"result\": 12}"}
```

---

## Response

```jsonc
{
  "provider": "gemini",
  "model": "gemini-3.1-flash-lite",
  "text": "...",
  "tool_calls": [{"id": "call_abc", "name": "add", "arguments": {"a": 7, "b": 5}}],
  "stop_reason": "tool_use",
  "input_tokens": 66,
  "output_tokens": 16,
  "cache_creation_input_tokens": 0,
  "cache_read_input_tokens": 0,
  "latency_ms": 412,
  "reasoning_applied": false,
  "parsed": null,      // populated when response_format validation passes
  "attempted": []      // skipped providers + reasons
}
```

---

## Python Client

```python
from client import LLM
llm = LLM()  # defaults to http://localhost:8100

# Basic
result = llm.chat("Hello!", provider="g")
print(result["text"])

# Tool use
result = llm.chat(
    messages=[{"role": "user", "content": "What is 7+5? Use the add tool."}],
    provider="gr",
    tools=[{"name": "add", "description": "a+b",
            "input_schema": {"type": "object", "properties": {"a": {"type": "number"}, "b": {"type": "number"}}, "required": ["a", "b"]}}],
    tool_choice="auto",
)
tc = result["tool_calls"][0]  # {"id": ..., "name": "add", "arguments": {"a": 7, "b": 5}}

# Structured output + reasoning
out = llm.chat(
    prompt="Capital of France as JSON {city, country}.",
    provider="g",
    response_format={"type": "json_schema", "schema": {...}, "name": "loc"},
    reasoning="low",
)
print(out["parsed"])  # validated dict
```

---

## Providers

| Provider | Shortcut | Tools | Reasoning | Notes |
|---|---|---|---|---|
| Gemini | `g` / `gem` | ✅ | ✅ (2.5+ models) | Explicit prompt cache; `thoughtSignature` echoed automatically |
| NVIDIA | `n` / `nv` | ✅ | ✅ (DeepSeek-R) | Implicit prefix cache |

---

## Files

| File | Purpose |
|---|---|
| `main.py` | FastAPI app + routing logic |
| `providers.py` | Gemini, NVIDIA |
| `router.py` | Rate limiting + capability-aware failover |
| `schemas.py` | Pydantic v2 request/response models |
| `cache.py` | Gemini SHA-256-keyed cache (5 min TTL) |
| `db.py` | SQLite call log |
| `client.py` | Python SDK |
| `tests/test_all_providers.py` | Provider matrix test |