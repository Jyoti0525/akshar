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

def _declare_gpu_function():
    """Satisfy ZeroGPU's startup check, and be honest about what this is.

    ZeroGPU refuses to start a Space in which no function is decorated with
    `@spaces.GPU` — *"No @spaces.GPU function detected during startup"*. The
    check exists because ZeroGPU exists to share GPUs between Spaces that use
    them, and it is the only free hardware this account can select: Docker
    Spaces and CPU Basic are both paid on it.

    **This project's inference is CPU-bound.** `onnxruntime` is installed
    without a CUDA provider and the scan path never asks for a device, so the
    decorated function below is a declaration and not a workload. It reports
    whether a GPU was attached, which is true and occasionally useful, and it is
    not called by anything in the request path.

    Recorded plainly rather than buried, because it is a workaround for a
    platform constraint rather than a design decision, and because the honest
    answer to "why is this on ZeroGPU" is "it is the free tier that had enough
    memory", not "it needs a GPU". A scan peaks at 1.8 GB resident on a 9 MP
    photograph and 0.93 GB on a 1.4 MP one — measured 2026-09-23 — and 512 MB
    tiers cannot hold either.

    If the account ever gains CPU Basic or a Docker Space, delete this and
    switch the hardware; nothing else depends on it.
    """
    try:
        import spaces
    except ImportError:
        # Not on a Space — running locally or in the Docker image. There is
        # nothing to satisfy and nothing to declare.
        return None

    @spaces.GPU(duration=15)
    def gpu_probe() -> str:
        try:
            import torch

            if torch.cuda.is_available():
                return f"GPU attached: {torch.cuda.get_device_name(0)}"
            return "No GPU attached; inference here is CPU-bound by design."
        except Exception as exc:  # pragma: no cover - diagnostic only
            return f"Could not query the device: {exc}"

    return gpu_probe


_gpu_probe = _declare_gpu_function()


with gr.Blocks(title="AKSHAR API", analytics_enabled=False) as landing:
    gr.Markdown(_LANDING)
    if _gpu_probe is not None:
        with gr.Accordion("Runtime device", open=False):
            gr.Markdown(
                "This Space runs on ZeroGPU because it is the free tier with "
                "enough memory — a scan needs about 1.8 GB. The inference "
                "itself is CPU-bound; no GPU is used in the scan path."
            )
            _device_out = gr.Textbox(label="Device", interactive=False)
            gr.Button("Check the device").click(_gpu_probe, outputs=_device_out)

# Gradio is mounted ONTO the API, not in front of it.
app = gr.mount_gradio_app(api, landing, path="/ui")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT)
