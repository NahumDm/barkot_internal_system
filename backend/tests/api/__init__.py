"""Tests for the shared API error envelope (roadmap A2, spec §20.2).

The envelope is the one thing every endpoint in every domain depends on. If a
failure can come back in two shapes, the frontend grows two code paths for
handling a bad request - and the second one is always the buggy one. These
tests pin the shape for each way a request can fail, and pin that genuine bugs
still escape as 500s rather than being dressed up as business outcomes.
"""
