# Meterless H-MEM reference (vendored)

Unmodified copy of `engines/hmem/reference/src` from https://github.com/Meterless/Meterless
(commit 1742dec56a66e58eef9dda2d2b865823758ca8cd), Apache-2.0 (see LICENSE).
Pre-existing open-source component, declared in the hackathon submission. **Not written by the ClinAssist team.**

The reference is deterministic and dependency-free: its embedder is a hash mock (the H-MEM authors say to swap
in a real embedding provider for production), so retrieval ranking here is driven mostly by keywords, tags,
entities and recency.
