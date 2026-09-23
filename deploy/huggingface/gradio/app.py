"""Entry point for a Hugging Face **Gradio** Space.

Docker Spaces are a paid feature on some accounts, and this project needs the
memory a free CPU Space provides — a real scan peaks at 1.8 GB and stays there,
because ONNX keeps the weights resident. So the API is served from a Gradio
Space instead of a Docker one, which costs nothing and reaches the same place.

**Nothing about the application changes.** `api.main:app` is imported and served
exactly as `docker/api.Dockerfile` serves it; this file adds a landing page and
a `uvicorn` call and no behaviour of its own. The system libraries the Docker
image installs with `apt-get` come from `packages.txt` here, and the Python
dependencies from `requirements.txt`.

Two details that are easy to get wrong:

- **Port 7860.** A Space routes to it and nothing else.
- **A Gradio Space expects a Gradio app**, so one is mounted — but at `/ui`, not
  at `/`. The root belongs to FastAPI, because the web app talks to `/api/v1/*`
  and a redirect there would break it. `gr.mount_gradio_app` attaches Gradio to
  an existing FastAPI application rather than the other way round, which is what
  keeps the API's own routes, its OpenAPI schema and `/docs` untouched.
"""

from __future__ import annotations

import os

import gradio as gr

from api.main import app as api

PORT = int(os.environ.get("PORT", "7860"))

_LANDING = """
# AKSHAR — API

Legal Metrology (Packaged Commodities) Rules, 2011 compliance, **measured from a
photograph** rather than read out of an artwork file before printing.

This Space runs the backend only. The officer-facing web app is deployed
separately and calls it server-side; a browser never talks to it directly.

| | |
|---|---|
| [`/healthz`](/healthz) | tier, rulepack version, how many weights are present |
| [`/docs`](/docs) | the full OpenAPI schema, browsable |
| `POST /api/v1/auth/login` | session |
| `POST /api/v1/scans` | a photograph in, a verdict out |

**Rules decide, models never.** The neural networks extract text and geometry;
the verdict comes from a versioned YAML rulepack, and every verdict carries the
gazette clause that produced it.

*A free Space sleeps when idle — the first request after a sleep takes about a
minute to wake the container. A cold scan is roughly 25 seconds while ONNX loads
the weights, and about 10 seconds once they are resident.*
"""

with gr.Blocks(title="AKSHAR API", analytics_enabled=False) as landing:
    gr.Markdown(_LANDING)

# Gradio is mounted ONTO the API, not in front of it.
app = gr.mount_gradio_app(api, landing, path="/ui")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT)
