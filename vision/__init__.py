"""Extraction — AKSHAR.md sections 4, 8, 14 and 17.

Everything here turns pixels into facts. Nothing here decides compliance; that
is `rules/`, and the wall between them is section 3's first principle.

Submodules are imported lazily rather than eagerly, because `vision.identify`
is the only one the cache path needs and pulling in onnxruntime to compute a
12 ms perceptual hash would defeat the exit that makes the system fast.
"""
