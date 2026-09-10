"""HTML, then PDF. AKSHAR.md sections 13 and 8c.

    "One HTML template renders both formats."          -- section 15b, on
                                                          rejecting ReportLab

**The PDF is not a separate document.** WeasyPrint lays out the same HTML a
browser would, so the officer's on-screen report and the filed PDF cannot say
different things — which is the same argument `api/analytics.py` makes about the
dashboard and `reports/model.py` makes about the two formats.

**WeasyPrint may not be able to render, and that is a first-class state.** It
needs Pango, cairo and their font machinery, which are present in the Linux
image `docker/api.Dockerfile` builds and absent from a plain Windows or macOS
`pip install`. So `to_pdf` raises `RendererUnavailableError` with an instruction
rather than an ImportError with a stack trace, `available()` answers the
question directly, and `/healthz` can report it. This is deliberately the same
shape as `vision.runtime.ModelUnavailableError`: a missing native dependency
degrades a feature and says so, it does not take the process down.

The HTML and DOCX paths have no native dependencies at all, so a deployment that
cannot produce a PDF can still produce the editable format the problem statement
actually asks for.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

TEMPLATE_DIR = Path(__file__).parent / "templates"


class RendererUnavailableError(RuntimeError):
    """A renderer's native libraries are missing. Caught, reported, never fatal."""


@lru_cache(maxsize=1)
def _environment() -> Any:
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    return Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        # Autoescape on, and it matters more here than in a web page: every
        # string in this document is OCR output from a photograph of a package.
        # A pack whose ingredient list contains "<" would otherwise silently
        # swallow the rest of the report.
        autoescape=select_autoescape(["html", "xml"], default_for_string=True),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def to_html(report: Any, *, template: str = "product.html") -> str:
    """Render the report model to a standalone HTML document."""
    return _environment().get_template(template).render(report=report)


@lru_cache(maxsize=1)
def pdf_available() -> tuple[bool, str]:
    """Can this process produce a PDF? Returns (yes, reason-if-not).

    Cached: a host does not grow Pango while the process runs, and `/healthz`
    calls this. Uncached it also re-emits WeasyPrint's own multi-line import
    banner to stderr on every health check, which would bury the log.

    Import *and* a one-line render, and **both are wrapped in bare `except`**,
    which is usually a smell and is right here:

    - The import raises `OSError`, not `ImportError`, when the native libraries
      are absent — `cannot load library 'gobject-2.0-0'`, from `cffi.dlopen`
      deep inside `weasyprint.text.ffi`. Catching `ImportError` alone lets that
      escape, which is exactly what this function exists to prevent and exactly
      what it did on the first run.
    - The render can fail for host reasons an exception type does not enumerate:
      a fontconfig cache that cannot be written, a cairo version mismatch.

    A one-line render as well as the import, because on some hosts the import
    succeeds and only layout fails. A health check that only imported would
    report ready and then fail on the first officer's report.
    """
    try:
        import weasyprint
    except Exception as exc:  # see the docstring: OSError is the common case here
        return False, _install_hint(f"weasyprint could not be imported: {exc}")
    try:
        weasyprint.HTML(string="<p>.</p>").write_pdf()
    except Exception as exc:  # pragma: no cover - depends on the host
        return False, _install_hint(f"weasyprint is installed but cannot render: {exc}")
    return True, ""


def _install_hint(problem: str) -> str:
    return (
        f"{problem}. It needs Pango, cairo and harfbuzz — on Debian "
        f"libpango-1.0-0, libpangoft2-1.0-0, libcairo2 and libharfbuzz0b, which "
        f"docker/api.Dockerfile installs. DOCX and HTML are unaffected."
    )


def to_pdf(report: Any, *, template: str = "product.html", allow_fallback: bool = True) -> bytes:
    """Render to PDF. WeasyPrint where it runs, a pure-Python writer where it does not.

    `base_url` is deliberately **not** set. The template references no external
    resource, and leaving the base URL unset means WeasyPrint cannot resolve one
    even if a future edit adds it by accident — a report whose appearance depends
    on whether a district office had connectivity when it was filed is not
    evidence.

    ---------------------------------------------------------------------------
    WHY THERE IS A SECOND RENDERER AT ALL
    ---------------------------------------------------------------------------
    WeasyPrint needs Pango, cairo and harfbuzz. `docker/api.Dockerfile` installs
    them and the deployed system never reaches the fallback. A Windows or macOS
    machine without the GTK runtime cannot import it at all, and until
    2026-09-09 the PDF route answered such a host with a JSON error body — which
    the browser, following the `download` attribute on the link, saved as
    `akshar-<id>.pdf`. The officer got a file that would not open.

    A plainer PDF is a worse report. A file that will not open is not a report.

    `allow_fallback=False` is for the test that asserts WeasyPrint itself still
    works where it is installed; without it that test would pass on a host with
    no GTK and prove nothing.
    """
    ok, reason = pdf_available()
    if ok:
        import weasyprint

        return weasyprint.HTML(string=to_html(report, template=template)).write_pdf()

    if not allow_fallback:
        raise RendererUnavailableError(reason)

    from reports import pdf_fallback

    if template == "summary.html":
        return pdf_fallback.summary_to_pdf(report)
    return pdf_fallback.to_pdf(report)


__all__ = ["TEMPLATE_DIR", "RendererUnavailableError", "pdf_available", "to_html", "to_pdf"]
