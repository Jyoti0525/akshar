#!/usr/bin/env python3
"""Expand `pyproject.toml` into the Space's `requirements.txt`.

    python deploy/huggingface/gen-requirements.py

`docker/api.Dockerfile` installs `.[api,vision,reports,retrieval]` and never
needs a second list. A Hugging Face Space cannot: it resolves
`requirements.txt` in a build stage that does not carry the repository, so a
local path install has no `pyproject.toml` to read and the build fails before
the source is copied.

So the list is expanded — but generated rather than typed, because the pins in
`pyproject.toml` each have a paragraph of reasoning in AKSHAR.md section 15b
beside them, and a hand-kept copy drifts from that silently. The deployed API
would then be running versions nobody argued for, which is the kind of thing
that is only noticed when it breaks.

`gradio` is deliberately left out: the Space image supplies it at the version
named by `sdk_version` in the Space README, and pinning a second one here is
how a resolver conflict appears on somebody else's build machine.
"""

from __future__ import annotations

import pathlib
import sys
import tomllib

# The extras the API actually needs. `training` is not here on purpose: its
# toolchain is CUDA- and torch-specific and would not install on a Space, and
# nothing the API serves touches it.
EXTRAS = ("api", "vision", "reports", "retrieval")

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
OUT = ROOT / "deploy" / "huggingface" / "gradio" / "requirements.txt"

HEADER = """# Dependencies for a Hugging Face Gradio Space.
#
# GENERATED from `pyproject.toml` by `deploy/huggingface/gen-requirements.py`.
# Regenerate rather than edit: every pin here is argued for in AKSHAR.md
# section 15b, and a hand-kept copy drifts from it silently — the deployed API
# would then be running versions nobody chose.
#
# This was one line once: `.[api,vision,reports,retrieval]`, which is what
# `docker/api.Dockerfile` effectively installs and is far harder to get wrong.
# It does not work here. A Space resolves `requirements.txt` in a separate
# build stage that does not carry the repository, so a local path install has
# no `pyproject.toml` to read and the build fails before the source is ever
# copied. Hence the expansion.
#
# `gradio` is deliberately absent: the Space image provides it at the version
# named by `sdk_version` in README.md, and a second pin here is how you get a
# resolver conflict on somebody else's build machine.
"""


def canonical(requirement: str) -> str:
    """The distribution name alone, for de-duplication.

    Extras and specifiers are stripped because `redis>=5.2,<6` and
    `dramatiq[redis]>=1.17,<2` name two different distributions, while the same
    package appearing in two extras names one.
    """
    for separator in (">", "<", "=", "[", "!", "~", ";"):
        requirement = requirement.split(separator)[0]
    return requirement.strip().lower()


def main() -> int:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = data["project"]

    requirements = list(project.get("dependencies", []))
    optional = project.get("optional-dependencies", {})
    for extra in EXTRAS:
        if extra not in optional:
            print(f"error: pyproject has no [{extra}] extra", file=sys.stderr)
            return 1
        requirements += list(optional[extra])

    seen: set[str] = set()
    ordered: list[str] = []
    for requirement in requirements:
        name = canonical(requirement)
        if name not in seen:
            seen.add(name)
            ordered.append(requirement)

    OUT.write_text(HEADER + "\n".join(ordered) + "\n", encoding="utf-8")
    print(f"{OUT.relative_to(ROOT)}: {len(ordered)} pins from {len(EXTRAS)} extras")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
