---
title: AKSHAR API
emoji: 📏
colorFrom: red
colorTo: yellow
sdk: gradio
sdk_version: 6.28.0
app_file: app.py
pinned: false
license: apache-2.0
short_description: Legal Metrology label compliance, measured from a photograph
---

# AKSHAR — API

The backend for [AKSHAR](https://github.com/Jyoti0525/akshar): Legal Metrology
(Packaged Commodities) Rules, 2011 compliance, measured from a photograph of a
package rather than read out of an artwork file before printing.

This Space runs the FastAPI service. The officer-facing web app is deployed
separately and talks to it server-side; a browser never calls it directly.

## Why a Gradio Space and not a Docker one

A real scan peaks at **1.8 GB** resident and stays there, because ONNX keeps the
weights loaded — which is what makes a second scan 10 seconds instead of 25.
That rules out the 512 MB free tiers. A free CPU Space has the headroom, and
Docker Spaces are a paid feature on some accounts, so the same image is served
through the Gradio SDK instead: `packages.txt` installs the system libraries the
Dockerfile installed with `apt-get`, and `requirements.txt` installs the project
itself so the pinned versions stay the ones `pyproject.toml` argues for.

`app.py` imports `api.main:app` unchanged and mounts a Gradio landing page at
`/ui`. The root belongs to FastAPI.

## Endpoints

| | |
|---|---|
| `/healthz` | tier, rulepack version, how many weights are present |
| `/docs` | the full OpenAPI schema, browsable |
| `/ui` | this landing page |
| `POST /api/v1/auth/login` | session |
| `POST /api/v1/scans` | a photograph in, a verdict out |

## Configuration

Set these as **Space secrets**, never as public variables:

| Secret | Required | Notes |
|---|---|---|
| `AKSHAR_JWT_SECRET` | **yes** | the API refuses to start without it |
| `AKSHAR_DATABASE_URL` | yes | Postgres 17+ with pgvector |
| `AKSHAR_REDIS_URL` | no | omit and the spool degrades cleanly |
| `AKSHAR_MINIO_ENDPOINT` | no | omit and evidence images are not stored |

Both optional services return `None` when unset rather than raising, so the API
starts and reports what it can do instead of failing.

## First request

A free Space sleeps when idle and takes about a minute to wake. After that it is
warm.

## Licence

Apache-2.0. The rulepack and the legal corpus are public documents of the
Government of India.
