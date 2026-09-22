# AKSHAR — API and worker image. AKSHAR.md sections 12, 15b, 20.
#
# One image for both services. `docker-compose.yml` runs it twice with different
# commands: `uvicorn` for the API, `dramatiq` for the worker. They share every
# dependency, and a separate worker image would be a second thing to keep in
# step with the first for no benefit.
#
# Section 20's submission checklist requires `docker compose up` to work from a
# clean clone, which is why the native libraries below are pinned into the image
# rather than left to a README instruction.

FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# --- native libraries, and why each one is here ------------------------------
#
# WeasyPrint renders the PDF through Pango, cairo and harfbuzz. Without them
# `import weasyprint` raises OSError from cffi — not ImportError — and
# `reports.render.pdf_available()` reports the feature as unavailable. That
# degradation is deliberate and tested, but a deployment should never be in it:
# the PDF is what an officer files.
#
# fonts-dejavu covers Devanagari, so a brand name in Hindi renders as text
# rather than as tofu boxes. It is a labelling tool for Indian packages; the
# font is not optional.
#
# libglib2.0-0 and libzbar0 are opencv-python-headless and pyzbar respectively.
# `libgl1` is deliberately NOT installed — the headless OpenCV wheel exists
# precisely so a server does not need an OpenGL stack.
RUN apt-get update && apt-get install --no-install-recommends -y \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libcairo2 \
        libharfbuzz0b \
        libffi8 \
        fonts-dejavu-core \
        libglib2.0-0 \
        libzbar0 \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependency metadata first, so a source edit does not invalidate the pip layer.
COPY pyproject.toml README.md ./
COPY contracts/__init__.py contracts/__init__.py

# `[tool.setuptools] packages` names nine packages by hand, and setuptools
# refuses to build the wheel while any one of them is missing from the tree. At
# this point in the build every one of them is missing except `contracts`, so
# the install below died on `package directory 'rules' does not exist` — taking
# the whole image with it, and with it section 20's "`docker compose up` from a
# clean clone". Empty stubs satisfy the check so the dependency layer can still
# be built and cached before any source arrives.
#
# They are placeholders for exactly one layer. `COPY . .` puts the real modules
# at /app, and the `--no-deps` reinstall below replaces the stub copies in
# site-packages with the real code — so nothing can import an empty package by
# resolving the installed distribution instead of the working directory.
RUN mkdir -p rules/checks vision evidence retrieval api workers reports \
    && touch rules/__init__.py rules/checks/__init__.py vision/__init__.py \
             evidence/__init__.py retrieval/__init__.py api/__init__.py \
             workers/__init__.py reports/__init__.py
# `setuptools` explicitly: the source-only reinstall after `COPY . .` runs with
# `--no-build-isolation`, which means the build backend named in
# `[build-system]` has to already be importable here rather than fetched into a
# throwaway environment. python:3.12-slim ships pip without it.
RUN pip install --upgrade pip setuptools \
    && pip install ".[api,vision,reports,retrieval]"

COPY . .

# Source only. Every dependency was resolved in the cached layer above, so this
# is a file copy rather than a second resolve.
RUN pip install --no-deps --no-build-isolation "."

# Fail the build if the PDF renderer cannot actually render. The whole point of
# installing those libraries is defeated if a version bump silently breaks them,
# and finding out here costs a build where finding out in production costs an
# officer their document.
RUN python -c "from reports.render import pdf_available; ok, why = pdf_available(); \
import sys; sys.exit(0) if ok else sys.exit('PDF rendering is broken in this image: ' + why)"

# Never root. The container writes nothing except to the volumes compose mounts.
RUN useradd --create-home --uid 10001 akshar && chown -R akshar:akshar /app
USER akshar

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/healthz || exit 1

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
