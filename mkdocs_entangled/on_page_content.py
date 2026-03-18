import logging
import re
from pathlib import Path

from mkdocs.config.defaults import MkDocsConfig
from mkdocs.structure.pages import Page
from mkdocs.structure.files import Files, File

from entangled.model import ReferenceMap
from entangled.model.properties import get_id
from entangled.interface import Context

from .on_page_markdown import read_single_markdown

log = logging.getLogger("mkdocs.plugins.entangled")


# Regex to match <<refname>> in Pygments-highlighted HTML.
# Pygments splits tokens across <span> elements, e.g.:
#   <span class="o">&lt;&lt;</span><span class="n">hello</span><span class="o">-</span><span class="n">world</span><span class="o">&gt;&gt;</span>
# or in unhighlighted blocks:
#   &lt;&lt;hello-world&gt;&gt;
NOWEB_PATTERN = re.compile(
    r'(?:<span[^>]*>)?'                       # optional span around <<
    r'&lt;&lt;'                                # the << (HTML-escaped)
    r'(?:</span>)?'                            # optional closing span
    r'((?:(?:<span[^>]*>)?[\w:-]+(?:</span>)?)+)'  # reference name (may span multiple <span>s)
    r'(?:<span[^>]*>)?'                        # optional span around >>
    r'&gt;&gt;'                                # the >> (HTML-escaped)
    r'(?:</span>)?'                            # optional closing span
)

STRIP_TAGS = re.compile(r'<[^>]+>')


def _collect_ids(reference_map: ReferenceMap) -> set[str]:
    """Extract all Id values from code blocks in a reference map."""
    ids: set[str] = set()
    for code_block in reference_map.values():
        if block_id := get_id(code_block.properties):
            ids.add(block_id)
    return ids


def build_global_refs(context: Context, files: Files, config: MkDocsConfig) -> dict[str, File]:
    """Pre-scan all markdown files to build a global refname -> File map."""
    global_refs: dict[str, File] = {}
    docs_dir = Path(config['docs_dir'])

    for file in files.documentation_pages():
        src_path = docs_dir / file.src_path
        if not src_path.exists():
            continue

        text = src_path.read_text()
        try:
            refs, _ = read_single_markdown(context, text)
        except Exception:
            log.warning("Failed to parse %s for cross-page references", file.src_path, exc_info=True)
            continue

        for block_id in _collect_ids(refs):
            global_refs[block_id] = file

    return global_refs


def on_page_content(
    html: str,
    reference_map: ReferenceMap,
    global_refs: dict[str, File],
    *,
    page: Page,
) -> str:
    """Post-process rendered HTML to make <<refname>> noweb references clickable."""
    local_anchors = _collect_ids(reference_map)

    def replace_noweb(m: re.Match) -> str:
        full_match = m.group(0)
        raw_name = STRIP_TAGS.sub('', m.group(1))

        if raw_name in local_anchors:
            return f'<a href="#{raw_name}" class="noweb-ref">{full_match}</a>'

        if raw_name in global_refs:
            target_file = global_refs[raw_name]
            rel_url = target_file.url_relative_to(page.file)
            return f'<a href="{rel_url}#{raw_name}" class="noweb-ref">{full_match}</a>'

        return full_match

    return NOWEB_PATTERN.sub(replace_noweb, html)
