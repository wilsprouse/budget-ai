# budget-ai

A lightweight, self-hosted LLM endpoint designed to run on cheap/minimal hardware.
Powered by [Ollama](https://ollama.com/) and exposed via a simple FastAPI REST API.

---

## Model choice — `tinyllama`

[TinyLlama](https://huggingface.co/TinyLlama/TinyLlama-1.1B-Chat-v1.0) (1.1 B parameters, ~638 MB on disk) is the default model because it:

* runs on **CPU-only** machines with as little as **2 GB RAM**
* loads in seconds and responds within 1–5 s on modest hardware
* still produces coherent, helpful text for most assistant-style tasks

You can swap to any Ollama-compatible model by setting the `DEFAULT_MODEL` environment variable (see Configuration).

---

## Prerequisites

| Tool | Minimum version |
|------|----------------|
| Podman | 4.0+ |
| podman-compose | 1.0+ |

No GPU required for `tinyllama`.

> **Tip:** Run `./start.sh --install-deps` to automatically install Podman and
> podman-compose for your OS (Ubuntu/Debian, Fedora/RHEL, or macOS via Homebrew).

---

## Quick start

```bash
# 1. Clone the repo
git clone https://github.com/wilsprouse/budget-ai.git
cd budget-ai

# 2. (Optional) Install podman and podman-compose automatically
./start.sh --install-deps

# 3. Start the stack (builds the API image, starts Ollama, pulls the model)
./start.sh

# Or start detached:
./start.sh -d
```

The first run downloads the TinyLlama model (~638 MB) — subsequent starts are instant.

---

## Endpoints

Once running, the API is available at **http://localhost:8000**.

Interactive docs (Swagger UI): **http://localhost:8000/docs**

### `GET /health`

Liveness probe. Also verifies Ollama is reachable.

```bash
curl http://localhost:8000/health
```

### `POST /v1/chat/completions` _(OpenAI-compatible — use this with budget-ai-ui)_

OpenAI-compatible chat completions endpoint. Accepts the same payload shape as
the OpenAI API and transforms Ollama responses so that **budget-ai-ui** (or any
other OpenAI-compatible client) can target this wrapper directly.

```bash
curl -s http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "tinyllama",
    "messages": [
      {"role": "system", "content": "You are a helpful budgeting assistant."},
      {"role": "user",   "content": "How do I create a simple monthly budget?"}
    ]
  }' | jq .
```

Streaming (SSE, OpenAI-compatible `data: {...}` events):

```bash
curl -s http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"role": "system", "content": "You are a helpful budgeting assistant."},
      {"role": "user",   "content": "Give me 3 tips for reducing monthly expenses."}
    ],
    "stream": true
  }'
```

### `POST /chat`

Multi-turn chat completions (Ollama-native NDJSON response).

```bash
curl -s http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"role": "system", "content": "You are a helpful budgeting assistant."},
      {"role": "user",   "content": "How do I create a simple monthly budget?"}
    ]
  }' | jq .
```

### `POST /generate`

Single-turn text generation from a raw prompt.

```bash
curl -s http://localhost:8000/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt": "List 3 tips for saving money on groceries."}' | jq .
```

### Streaming

Both `/chat` and `/generate` accept `"stream": true` to receive newline-delimited
JSON tokens as they are generated:

```bash
curl -s http://localhost:8000/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Tell me a short story.", "stream": true}'
```

```bash
curl -s http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"role": "system", "content": "You are a helpful budgeting assistant."},
      {"role": "user",   "content": "Give me 3 tips for reducing monthly expenses."}
    ],
    "stream": true
  }'
```

---

## Connecting budget-ai-ui

[budget-ai-ui](https://github.com/wilsprouse/budget-ai-ui) is built for
OpenAI-compatible endpoints. Point it at this wrapper's `/v1/chat/completions`
route in `config.js`:

```javascript
const CONFIG = {
  LLM_BASE_URL: 'http://localhost:8000',   // budget-ai wrapper
  LLM_API_PATH: '/v1/chat/completions',    // OpenAI-compatible route
  MODEL: 'tinyllama',
  API_KEY: '',
  SYSTEM_PROMPT: 'You are a helpful and friendly AI assistant.',
  APP_NAME: 'Budget AI',
};
```

The wrapper will accept the UI's `{ model, messages, stream }` payload,
forward it to Ollama's `/api/chat`, and convert the response into the
SSE `data: {"choices":[{"delta":{"content":"..."}}]}` format the UI parser
expects, terminating with `data: [DONE]`.

---

## Configuration

Copy `.env.example` to `.env` and edit as needed (the `start.sh` script does this automatically):

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_BASE_URL` | `http://ollama:11434` | Internal Ollama URL |
| `DEFAULT_MODEL` | `tinyllama` | Ollama model to use |
| `API_PORT` | `8000` | Host port for the FastAPI service |
| `WEB_CONCURRENCY` | `4` | Number of uvicorn worker processes for the FastAPI service |
| `OLLAMA_NUM_PARALLEL` | `4` | Number of requests Ollama processes simultaneously |

### Concurrent requests

The stack is configured out of the box to handle multiple simultaneous users:

* **`WEB_CONCURRENCY`** — controls how many uvicorn worker processes the FastAPI service runs. Each worker process runs independently and can handle multiple concurrent async requests. Increase this on machines with more CPU cores.
* **`OLLAMA_NUM_PARALLEL`** — controls how many inference requests Ollama will run at the same time. Each additional parallel slot consumes more RAM/VRAM. Start at `4` and tune to your hardware.

```bash
# Example: higher-concurrency deployment on a beefy server
WEB_CONCURRENCY=8 OLLAMA_NUM_PARALLEL=8 ./start.sh
```

### Using a different model

```bash
# Start with a slightly larger but still small model
DEFAULT_MODEL=phi3:mini ./start.sh

# Or via the flag
./start.sh --model gemma:2b
```

---

## Project structure

```
budget-ai/
├── app/
│   └── main.py            # FastAPI application
├── docker-compose.yml     # Orchestrates Ollama + API
├── Dockerfile             # API service image
├── requirements.txt       # Python dependencies
├── start.sh               # Convenience startup script
└── .env.example           # Environment variable template
```

---

## Architecture

```
  budget-ai-ui  (or any OpenAI-compatible client)
      │
      │  HTTP POST /v1/chat/completions  (OpenAI-compatible SSE)
      ▼
┌─────────────┐
│  budget-ai  │  FastAPI wrapper
│     API     │  • /v1/chat/completions  ← UI target
│             │  • /chat
│             │  • /generate
└──────┬──────┘
       │  HTTP POST /api/chat  (Ollama NDJSON)
       ▼
┌─────────────┐
│   Ollama    │  LLM runtime
│  tinyllama  │
└─────────────┘
```

---

## License

MIT — see [LICENSE](LICENSE)
