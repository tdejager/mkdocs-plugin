import re
from collections.abc import Iterable, Callable
from functools import partial, reduce
from pathlib import Path
from textwrap import indent
from itertools import chain

from mkdocs.config.defaults import MkDocsConfig
from mkdocs.structure.pages import Page
from mkdocs.structure.files import Files, File

from entangled.model import ReferenceMap, Content, PlainText, ReferenceId, CodeBlock, content_to_text
from entangled.model.properties import get_attribute, get_id, get_classes, Id, Attribute, Class
from entangled.config import ConfigUpdate, read_config
from entangled.interface import Context, read_markdown
from repl_session import read_session


type ContentFilter = Callable[[ReferenceMap, Content], Iterable[Content]]
type CodeBlockFilter = Callable[[ReferenceMap, ReferenceId], Iterable[Content]]


def codeblock_filter(f: CodeBlockFilter) -> ContentFilter:
    def _foo(rm: ReferenceMap, c: Content) -> Iterable[Content]:
        match c:
            case PlainText():
                return [c]
            case ReferenceId():
                return f(rm, c)
    return _foo


def document_to_text(refs: ReferenceMap, content: Iterable[Content]) -> str:
    return "".join(map(lambda c: content_to_text(refs, c)[0], content))


def iter_bind[T, U](lst: Iterable[T], f: Callable[[T], Iterable[U]]) -> Iterable[U]:
    return chain(*map(f, lst))


def compose_filter(a: ContentFilter, b: ContentFilter) -> ContentFilter:
    def _joined(rm: ReferenceMap, c: Content) -> Iterable[Content]:
        return iter_bind(partial(a, rm)(c), partial(b, rm))
    return _joined


def compose_filters(*args: ContentFilter) -> ContentFilter:
    return reduce(compose_filter, args, lambda _, c: [c])


def read_single_markdown(ctx: Context, text: str) -> tuple[ReferenceMap, list[Content]]:
    refs = ReferenceMap()
    content, _ = read_markdown(ctx, refs, text)
    return refs, content


def file_slug(filename: str) -> str:
    """Generate an HTML anchor slug from a file= attribute value."""
    return "file-" + re.sub(r'[^\w]+', '-', filename).strip('-')


def make_add_title(global_ref_counts: dict[str, int] | None = None) -> ContentFilter:
    """Create the add_title filter, optionally with ref count info for indexed titles."""
    ref_counts = global_ref_counts or {}

    @codeblock_filter
    def add_title(reference_map: ReferenceMap, r: ReferenceId) -> list[Content]:
        """
        Changes the `open_line` member of a `CodeBlock` to reflect accepted
        MkDocs syntax, adding a `title` attribute.
        """
        codeblock: CodeBlock = reference_map[r]

        block_id = get_id(codeblock.properties)
        classes = list(get_classes(codeblock.properties))
        filename = get_attribute(codeblock.properties, "file")

        title = None
        if block_id and filename:
            title = f"#{block_id} / file: {filename}"
        elif block_id:
            title = f"#{block_id}"
        elif filename:
            title = f"file: {filename}"

        # Add [N] index to title when block has multiple parts
        if title and block_id:
            count = ref_counts.get(block_id, 1)
            if count > 1:
                title += f" [{r.ref_count + 1}]"

        open_line = "```"
        if classes:
            open_line += classes[0]

        if block_id or classes or title:
            open_line += " {"

            if block_id:
                open_line += str(Id(block_id))

            for c in classes[1:]:
                open_line += " " + str(Class(c))

            if title:
                open_line += " " + str(Attribute("title", title))

            open_line += "}\n"

        codeblock.open_line = open_line

        # Insert an anchor target before code blocks with an id or file, so that
        # <<refname>> and "used by" links can jump to them.
        if block_id:
            anchor_id = block_id if r.ref_count == 0 else f"{block_id}-{r.ref_count}"
            return [PlainText(f'\n<a id="{anchor_id}"></a>\n'), r]
        elif filename:
            slug = file_slug(filename)
            return [PlainText(f'\n<a id="{slug}"></a>\n'), r]
        return [r]

    return add_title


@codeblock_filter
def include_repl_output(reference_map: ReferenceMap, r: ReferenceId) -> list[Content]:
    """
    Takes any codeblock that has the `repl` class and append its pre-computed output.
    """
    codeblock: CodeBlock = reference_map[r]
    if Class("repl") not in codeblock.properties:
        return [r]

    ref = next(iter(reference_map.select_by_name(r.name)))
    first: CodeBlock = reference_map[ref]
    session_filename = get_attribute(first.properties, "session")
    assert session_filename is not None
    session_path: Path = Path(session_filename)
    assert session_path.exists()
    session_output_path: Path = session_path.with_suffix(".out.json")
    assert session_output_path.exists()

    session = read_session(session_output_path.open("r"))
    command = session.commands[r.ref_count]

    if not command.output:
        return [r]

    output: str
    if command.output_type == "text/plain":
        output = indent(f"\n``` {{.text .output}}\n{command.output}\n```", codeblock.indent)
    else:
        output = indent(f"\n**unknown MIME type: {command.output_type}**", codeblock.indent)

    return [r, PlainText(output)]


def make_used_by_filter(
    global_used_by: dict[str, list],
    global_refs: dict[str, File],
    page: Page,
) -> ContentFilter:
    """Create a ContentFilter that adds 'Used by' annotations after named code blocks."""

    @codeblock_filter
    def used_by(reference_map: ReferenceMap, r: ReferenceId) -> list[Content]:
        codeblock: CodeBlock = reference_map[r]
        block_id = get_id(codeblock.properties)
        filename = get_attribute(codeblock.properties, "file")

        # Only annotate blocks that have a visible name
        if not block_id and not filename:
            return [r]

        ref_key = str(r.name)
        entries = global_used_by.get(ref_key)
        if not entries:
            return [r]

        links: list[str] = []
        for entry in entries:
            if entry.file.src_path == page.file.src_path:
                # Same page link
                if entry.block_id:
                    links.append(f'<a href="#{entry.block_id}" class="entangled-link">{entry.label}</a>')
                else:
                    links.append(entry.label)
            else:
                # Cross-page link
                rel_url = entry.file.url_relative_to(page.file)
                anchor = f"#{entry.block_id}" if entry.block_id else ""
                links.append(f'<a href="{rel_url}{anchor}" class="entangled-link">{entry.label}</a>')

        annotation = f'\n<div class="used-by">Used by: {", ".join(links)}</div>\n'
        return [r, PlainText(annotation)]

    return used_by


def on_page_markdown(
    context: Context, markdown: str, *, page: Page, config: MkDocsConfig, files: Files,
    global_ref_counts: dict[str, int] | None = None,
    global_used_by: dict[str, list] | None = None,
    global_refs: dict[str, File] | None = None,
) -> tuple[str, ReferenceMap]:
    reference_map, content = read_single_markdown(context, markdown)

    add_title = make_add_title(global_ref_counts)
    filters: list[ContentFilter] = [add_title, include_repl_output]
    if global_used_by is not None:
        filters.append(make_used_by_filter(global_used_by, global_refs or {}, page))

    filtered_content = iter_bind(content, partial(compose_filters(*filters), reference_map))
    return document_to_text(reference_map, filtered_content), reference_map
