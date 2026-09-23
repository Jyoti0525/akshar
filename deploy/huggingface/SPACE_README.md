---
title: AKSHAR API
emoji: 📏
colorFrom: red
colorTo: yellow
sdk: docker
app_port: 7860
pinned: false
license: apache-2.0
short_description: Legal Metrology label compliance, measured from a photograph
---

# AKSHAR — API

The backend for [AKSHAR](https://github.com/Jyoti0525/akshar): Legal Metrology
(Packaged Commodities) Rules, 2011 compliance, measured from a photograph of a
package rather than read out of an artwork file before printing.

This Space runs the FastAPI service only. The officer-facing web app is deployed
separately and talks to this Space server-side; a browser never calls it
directly.

## What it is

Given a photograph and the height of the face being photographed, it recovers a
millimetre scale from a printed ChArUco marker, measures the printed characters,
and evaluates a versioned YAML rulepack against what it read.

**Rules decide, models never.** The neural networks extract text and geometry;
the verdict comes from the rulepack, and every verdict carries the gazette
clause that produced it. That is deliberate — a paraphrase of a statute is not
something an enforcement notice can rest on.

## Endpoints

| | |
|---|---|
| `GET /healthz` | Tier, rulepack version, how many models are present |
| `GET /docs` | The full OpenAPI schema, browsable |
| `POST /api/v1/auth/login` | Session |
| `POST /api/v1/scans` | A photograph in, a verdict out |

## Configuration

Set these as **Space secrets**, not as public variables:

| Secret | Required | Notes |
|---|---|---|
| `AKSHAR_JWT_SECRET` | **yes** | The API refuses to start without it |
| `AKSHAR_DATABASE_URL` | yes | Postgres 17 with pgvector |
| `AKSHAR_REDIS_URL` | no | Omit and the spool degrades cleanly |
| `AKSHAR_MINIO_ENDPOINT` | no | Omit and evidence images are not stored |

Both optional services return `None` when unset rather than raising, so the API
starts and reports what it can do rather than failing.

## A note on the first request

A free Space sleeps when idle. The first request after a sleep wakes the
container and takes about a minute; after that it is warm. Inside the container
a cold scan is roughly 25 seconds while ONNX loads the weights, and about 10
seconds once they are resident.

## Licence

Apache-2.0. The rulepack and the legal corpus are public documents of the
Government of India.
