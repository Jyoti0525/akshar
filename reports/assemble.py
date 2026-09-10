"""Stored rows to a `ProductReport`. AKSHAR.md sections 13 and 14.

The route and the render worker both come through here, so a report downloaded
now and the same report re-rendered in eighteen months are built by one function
from one set of columns.

**Everything is read back out of the database, nothing is carried over from the
scan that produced it.** That is the whole reason section 10 stores the
declaration set, the model versions and the rulepack version as columns rather
than leaving them in a log line: *"a finding you cannot reproduce is a finding
you cannot defend."* A report assembled partly from live objects would render
beautifully today and be unreproducible the moment the process restarted.

**The check type comes from the rulepack, not from the verdict.** A verdict
carries its rule id and citation but not the kind of check that produced it, and
the remediation sentence in `reports/model.py` is keyed on the check. Looking it
up here means a rule whose check changes gets the right remedy automatically,
and a rule that has been *removed* from the pack still renders — with a generic
remedy — rather than raising while somebody prints an old case file.
"""

from __future__ import annotations

from typing import Any

from reports.model import Exhibit, Package, ProductReport, build

# The declaration fields Form A Part A names, in the order it names them.
_PARTICULARS: dict[str, str] = {
    "manufacturer": "manufacturer",
    "net_quantity": "net_quantity",
    "mrp": "mrp",
}


def check_types(pack: Any) -> dict[str, str]:
    """`rule_id -> check`, for the remediation lookup."""
    return {rule.id: rule.check for rule in pack.all_rules()}


def package_from(scan: dict[str, Any], sku: Any | None = None) -> Package:
    """Part A's particulars: the SKU where we matched one, the label otherwise.

    The declarations are read from the *stored* `declaration_set`, so Part A
    quotes what was actually printed on the package rather than what the SKU
    record says today. Those can differ — a manufacturer reprints, a SKU row is
    corrected — and the package in front of the officer is the one that matters.
    """
    declarations = (scan.get("declaration_set") or {}).get("declarations") or []
    text: dict[str, str] = {}
    for declaration in declarations:
        field = declaration.get("field")
        if field in _PARTICULARS and field not in text:
            text[field] = (declaration.get("text") or "").strip()

    return Package(
        brand=getattr(sku, "brand", None),
        variant=getattr(sku, "variant", None),
        pack_size=getattr(sku, "pack_size", None),
        category=scan.get("category") or getattr(sku, "category", None),
        barcode=getattr(sku, "barcode", None),
        manufacturer=text.get("manufacturer"),
        net_quantity=text.get("net_quantity"),
        mrp=text.get("mrp"),
    )


NO_EXHIBIT_STORED = (
    "No annotated image is held for this scan. The photograph, the declarations "
    "and the verdicts are unaffected."
)


def exhibit_for(scan: dict[str, Any], objects: Any | None) -> tuple[Exhibit | None, str]:
    """Fetch the annotated label from the derived bucket, if it is there.

    The key is *derived* from the scan id and its capture date rather than
    stored in a column, which is deliberate: the annotation is written by a
    worker after the scan row has been chain-sealed, so a column for it could
    only ever be filled by an UPDATE to a row that must not be updated. A
    convention that both sides compute independently needs no write at all.

    Absence is normal and is not an error. A repeat SKU stores no image by
    design, a privacy stop suppresses one, and a queued upload has simply not
    landed yet — so this returns a sentence rather than raising, and the report
    prints it in place of the picture.
    """
    if objects is None:
        return None, NO_EXHIBIT_STORED

    from evidence import storage

    key = storage.annotation_key(str(scan["id"]), captured_at=scan["captured_at"])
    payload = storage.get_derived(objects, key)
    if not payload:
        return None, NO_EXHIBIT_STORED
    return Exhibit(jpeg=payload), ""


def from_scan(
    *,
    scan: dict[str, Any],
    verdicts: list[dict[str, Any]],
    pack: Any,
    sku: Any | None = None,
    officer_name: str | None = None,
    objects: Any | None = None,
) -> ProductReport:
    exhibit, note = exhibit_for(scan, objects)
    return build(
        scan=scan,
        verdicts=verdicts,
        package=package_from(scan, sku),
        officer_name=officer_name,
        checks=check_types(pack),
        exhibit=exhibit,
        exhibit_note=note,
    )


__all__ = ["NO_EXHIBIT_STORED", "check_types", "exhibit_for", "from_scan", "package_from"]
