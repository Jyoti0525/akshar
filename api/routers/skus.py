"""`/api/v1/skus` — the cache check and offline warming. AKSHAR.md sections 4, 5, 12.

This is exit zero, expressed as HTTP. Section 4: *"Computing a perceptual hash
costs about 12 ms. We do it before touching a model. If this SKU has been seen
before, we replay the stored verdict and finish in roughly 60 ms."*

**Barcode is tried before pHash, deliberately.** Section 12: *"if the pack has a
readable EAN-13 then identifying the SKU is a single indexed lookup — faster and
more reliable than image matching. It costs almost nothing and it's the fastest
path to a cache hit we have."*

And the caveat that keeps it honest, from section 8b: *"A barcode match means
probably the same SKU. It does not mean the same printing, the same MRP, or the
same batch."* So this route returns an identity, never a verdict.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from api.deps import CurrentUserDep, SkuStoreDep
from api.repository import SkuRecord
from api.schemas import SkuCacheResponse, SkuLookupResponse, SkuSummary

router = APIRouter(prefix="/api/v1/skus", tags=["skus"])

MAX_HAMMING = 8
"""Section 15b: pHash (DCT-based), 64-bit, Hamming <= 8.

"dHash and aHash are faster but break under the lighting variation of shop
photography, which is exactly our condition."
"""


def _summary(sku: SkuRecord) -> SkuSummary:
    return SkuSummary(
        id=sku.id,
        brand=sku.brand,
        brand_group=sku.brand_group,
        variant=sku.variant,
        pack_size=sku.pack_size,
        category=sku.category,
        barcode=sku.barcode,
        phash=sku.phash,
        scan_count=sku.scan_count,
        label_w_mm=sku.label_w_mm,
        label_h_mm=sku.label_h_mm,
        label_mm_observations=sku.label_mm_observations,
        label_w_mm_stddev=sku.label_w_mm_stddev,
    )


@router.get("/lookup", response_model=SkuLookupResponse)
async def lookup(
    user: CurrentUserDep,
    skus: SkuStoreDep,
    barcode: str | None = Query(default=None),
    phash: str | None = Query(default=None, description="64-bit perceptual hash, hex."),
) -> SkuLookupResponse:
    """Have we seen this pack before? Cache check *before* any model runs.

    Returns an identity and nothing else. A cached *verdict* is fetched
    separately, because reusing a verdict is a decision about evidence and this
    route is about recognition.
    """
    if barcode:
        found = skus.by_barcode(barcode)
        if found is not None:
            return SkuLookupResponse(hit=True, matched_on="barcode", sku=_summary(found))

    if phash:
        found = skus.by_phash(phash, max_hamming=MAX_HAMMING)
        if found is not None:
            return SkuLookupResponse(hit=True, matched_on="phash", sku=_summary(found))

    return SkuLookupResponse(hit=False, matched_on="none", sku=None)


@router.get("/cache", response_model=SkuCacheResponse)
async def cache(
    user: CurrentUserDep,
    skus: SkuStoreDep,
    district: str | None = Query(default=None),
    n: int = Query(default=5000, ge=1, le=20_000),
) -> SkuCacheResponse:
    """Warm an officer's offline cache. Section 5.

    *"On wifi, pull the 5,000 most-scanned SKUs for the officer's district.
    Retail is heavily long-tailed, so a few megabytes covers close to 90% of
    what's actually on those shelves."*

    Ordered by scan count, because the long tail is the whole reason a few
    megabytes is enough — the head of the distribution is most of the shelf.
    """
    target = district or user.district
    found = skus.cache_for_district(target, n)
    return SkuCacheResponse(
        district=target, count=len(found), skus=[_summary(sku) for sku in found]
    )
