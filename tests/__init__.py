"""Tests for the amp_push library.

Self-contained: this directory (and its fixtures/ subfolder) covers only
src/amp_push, uses no fixtures from the rest of tests/, and does not rely on
the top-level tests/conftest.py for anything to pass - so it can run on its
own (`uv run pytest tests/amp_push/`) and move with src/amp_push if that
package is ever extracted into its own repo.
"""
