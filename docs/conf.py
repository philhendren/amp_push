"""Sphinx configuration for amp_push's documentation.

Built from the installed `amp_push` package (see pyproject.toml's `docs`
extra) - autodoc pulls its content straight from the docstrings in
src/amp_push/, so there's one source of truth for the API reference rather
than a hand-maintained copy.
"""

from __future__ import annotations

from importlib.metadata import version as installed_version

project = "amp_push"
copyright = "2026, Phil Hendren"  # noqa: A001
author = "Phil Hendren"
release = installed_version("amp_push")
version = release

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.viewcode",
    "myst_parser",
]

# Autodoc imports amp_push to read its docstrings, so it must be installed
# (it is - see pyproject.toml's `docs` extra / .readthedocs.yaml) rather than
# reached via a sys.path hack.
autodoc_member_order = "bysource"
add_module_names = False

source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}

# Lets `[text](#some-heading)`-style links resolve to auto-generated anchors
# on headings up to this depth, both within a page and across pages.
myst_heading_anchors = 3

exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

html_theme = "sphinx_rtd_theme"
