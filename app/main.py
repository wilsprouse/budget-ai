"""
budget-ai LLM Endpoint
A lightweight FastAPI wrapper around Ollama for self-hosted LLM inference.
"""

import json
import os
import time
import uuid
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import Optional

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "tinyllama")
OLLAMA_TIMEOUT = 120

app = FastAPI(
    title="budget-ai LLM Endpoint",
    description="Self-hosted open-source LLM endpoint powered by Ollama (tinyllama).",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class ChatMessage(BaseModel):
    role: str = Field(..., description="One of 'system', 'user', or 'assistant'")
    content: str = Field(..., description="Message content")


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(..., description="Conversation history")
    model: Optional[str] = Field(None, description="Override the default model")
    stream: bool = Field(False, description="Stream response tokens")


class ChatResponse(BaseModel):
    model: str
    message: ChatMessage
    done: bool


class GenerateRequest(BaseModel):
    prompt: str = Field(..., description="Raw prompt string")
    model: Optional[str] = Field(None, description="Override the default model")
    stream: bool = Field(False, description="Stream response tokens")


class GenerateResponse(BaseModel):
    model: str
    response: str
    done: bool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _model(override: Optional[str]) -> str:
    return override or DEFAULT_MODEL


async def _ollama_post(path: str, payload: dict) -> dict:
    """Send a non-streaming POST request to Ollama and return parsed JSON."""
    url = f"{OLLAMA_BASE_URL}{path}"
    async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT) as client:
        try:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return resp.json()
        except httpx.ConnectError as exc:
            raise HTTPException(
                status_code=503,
                detail=f"Cannot reach Ollama at {OLLAMA_BASE_URL}. Is it running?",
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                status_code=exc.response.status_code,
                detail=exc.response.text,
            ) from exc


async def _stream_ollama(path: str, payload: dict):
    """Yield raw bytes from a streaming Ollama response."""
    url = f"{OLLAMA_BASE_URL}{path}"
    async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT) as client:
        try:
            async with client.stream("POST", url, json=payload) as resp:
                resp.raise_for_status()
                async for chunk in resp.aiter_bytes():
                    yield chunk
        except httpx.ConnectError as exc:
            raise HTTPException(
                status_code=503,
                detail=f"Cannot reach Ollama at {OLLAMA_BASE_URL}. Is it running?",
            ) from exc


async def _stream_ollama_as_sse(path: str, payload: dict):
    """Yield OpenAI-compatible SSE events from a streaming Ollama /api/chat response.

    Each Ollama NDJSON line is converted to a ``data: {...}\\n\\n`` SSE event
    whose JSON contains ``choices[0].delta.content``, matching what the
    budget-ai-ui frontend parser expects.  A final ``data: [DONE]\\n\\n`` event
    is emitted after the stream completes.
    """
    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time())
    model = payload.get("model", DEFAULT_MODEL)

    url = f"{OLLAMA_BASE_URL}{path}"
    async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT) as client:
        try:
            async with client.stream("POST", url, json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    content = chunk.get("message", {}).get("content", "")
                    done = chunk.get("done", False)

                    sse_chunk = {
                        "id": completion_id,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": model,
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"content": content} if content else {},
                                "finish_reason": "stop" if done else None,
                            }
                        ],
                    }
                    yield f"data: {json.dumps(sse_chunk)}\n\n"

                    if done:
                        break
        except httpx.ConnectError as exc:
            raise HTTPException(
                status_code=503,
                detail=f"Cannot reach Ollama at {OLLAMA_BASE_URL}. Is it running?",
            ) from exc

    yield "data: [DONE]\n\n"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/health", tags=["System"])
async def health():
    """Liveness probe — also verifies Ollama is reachable."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
            resp.raise_for_status()
            tags = resp.json()
    except httpx.ConnectError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Cannot reach Ollama at {OLLAMA_BASE_URL}. Is it running?",
        ) from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail="Ollama returned an unexpected error.",
        ) from exc

    return {"status": "ok", "ollama": tags}


@app.post("/chat", response_model=ChatResponse, tags=["Inference"])
async def chat(req: ChatRequest):
    """
    Multi-turn chat completions.

    Pass a list of messages with roles 'system', 'user', or 'assistant'.
    Set `stream=true` to receive a streaming response.
    """
    payload = {
        "model": _model(req.model),
        "messages": [m.model_dump() for m in req.messages],
        "stream": req.stream,
    }

    if req.stream:
        return StreamingResponse(
            _stream_ollama("/api/chat", payload),
            media_type="application/x-ndjson",
        )

    data = await _ollama_post("/api/chat", payload)
    return ChatResponse(
        model=data["model"],
        message=ChatMessage(**data["message"]),
        done=data.get("done", True),
    )


@app.post("/generate", response_model=GenerateResponse, tags=["Inference"])
async def generate(req: GenerateRequest):
    """
    Single-turn text generation from a raw prompt.

    Set `stream=true` to receive a streaming response.
    """
    payload = {
        "model": _model(req.model),
        "prompt": req.prompt,
        "stream": req.stream,
    }

    if req.stream:
        return StreamingResponse(
            _stream_ollama("/api/generate", payload),
            media_type="application/x-ndjson",
        )

    data = await _ollama_post("/api/generate", payload)
    return GenerateResponse(
        model=data["model"],
        response=data["response"],
        done=data.get("done", True),
    )


@app.post("/v1/chat/completions", tags=["OpenAI-Compatible"])
async def openai_chat_completions(req: ChatRequest):
    """
    OpenAI-compatible chat completions endpoint.

    Accepts the same request shape used by the OpenAI API (``model``,
    ``messages``, ``stream``) and transforms Ollama ``/api/chat`` responses
    into OpenAI-compatible format so that ``budget-ai-ui`` — or any other
    OpenAI-compatible client — can target this wrapper directly.

    **Streaming** (``"stream": true``):
    Returns ``text/event-stream`` SSE events with the shape
    ``data: {"choices": [{"delta": {"content": "..."}}]}`` and terminates
    with ``data: [DONE]``.

    **Non-streaming** (``"stream": false``):
    Returns a single JSON object with ``choices[0].message.content`` and a
    ``usage`` field populated from Ollama token counts.
    """
    model = _model(req.model)
    payload = {
        "model": model,
        "messages": [m.model_dump() for m in req.messages],
        "stream": req.stream,
    }

    if req.stream:
        return StreamingResponse(
            _stream_ollama_as_sse("/api/chat", payload),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    data = await _ollama_post("/api/chat", payload)
    prompt_tokens = data.get("prompt_eval_count", 0)
    completion_tokens = data.get("eval_count", 0)
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": data.get("model", model),
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": data["message"]["role"],
                    "content": data["message"]["content"],
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }
