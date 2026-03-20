from pathlib import Path
from typing import override

from mkdocs.plugins import BasePlugin
from mkdocs.config.defaults import MkDocsConfig
from mkdocs.structure.pages import Page
from mkdocs.structure.files import Files, File

from entangled.model import ReferenceMap
from entangled.config import read_config
from entangled.interface import Context

from .on_page_markdown import on_page_markdown
from .on_page_content import on_page_content, build_global_refs
from .config import EntangledConfig

CSS_DIR = Path(__file__).parent / "css"


class EntangledPlugin(BasePlugin[EntangledConfig]):

    def __init__(self) -> None:
        super().__init__()
        self._context: Context | None = None
        self._reference_map: ReferenceMap | None = None
        self._global_refs: dict[str, File] = {}
        self._global_ref_counts: dict[str, int] = {}

    @override
    def on_files(self, files: Files, *, config: MkDocsConfig):
        ctx = Context()
        self._context = ctx | read_config(ctx.fs)
        self._global_refs, self._global_ref_counts = build_global_refs(self._context, files, config)

        # Inject bundled CSS into the build
        css_path = "css/entangled.css"
        css_file = File.generated(config, css_path, content=self._read_css())
        files.append(css_file)
        config["extra_css"].append(css_path)

        return files

    @staticmethod
    def _read_css() -> str:
        return (CSS_DIR / "entangled.css").read_text()

    @override
    def on_page_markdown(self, markdown: str, *, page: Page, config: MkDocsConfig, files: Files):
        assert self._context is not None
        self._reference_map = None
        result, self._reference_map = on_page_markdown(
            self._context, markdown, page=page, config=config, files=files,
            global_ref_counts=self._global_ref_counts,
        )
        return result

    @override
    def on_page_content(self, html: str, *, page: Page, config: MkDocsConfig, files: Files):
        if self._reference_map is not None:
            return on_page_content(html, self._reference_map, self._global_refs, self._global_ref_counts, page=page)
        return html
