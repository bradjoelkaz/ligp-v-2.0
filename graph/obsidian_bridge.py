"""Obsidian vault bridge (Blueprint Section 5).

Exports the knowledge graph (``{nodes, edges}`` in the seed/repo shape) into a
folder of Obsidian-compatible Markdown notes. Each node becomes one ``.md``
file, and every edge is rendered as an Obsidian ``[[wikilink]]`` so the user can
open the folder as a vault and explore the graph visually via Obsidian's
*Graph View*.

The module is deliberately framework-free and pure-Python (stdlib only): the
caller supplies the graph dict (e.g. the admin data layer's DB-or-seed source)
and a target directory. This keeps it unit-testable without a web server,
database, or network.

Node dict shape:  ``{"id", "type", "name", "weight"}``
Edge dict shape:  ``{"from_node", "to_node", "relation_type", "weight"}``
"""

from __future__ import annotations

import os
import re
from typing import Any

from utils.logger import get_logger

_log = get_logger(__name__)

# Characters Obsidian/filesystems dislike in note titles / filenames.
_UNSAFE_CHARS = re.compile(r'[\\/:*?"<>|\[\]#^]+')
_WS = re.compile(r"\s+")

# Node type -> human label (Korean) for the note heading.
NODE_TYPE_LABELS: dict[str, str] = {
    "topic": "토픽",
    "entity": "개체",
    "event": "이벤트",
    "emotion": "감정",
    "audience": "수용층",
    "product": "제품",
    "context": "상황",
    "genre": "장르",
}

# Relation type -> human label (Korean) for grouping outgoing edges.
RELATION_LABELS: dict[str, str] = {
    "related_to": "관련",
    "causes": "유발",
    "similar_to": "유사",
    "leads_to": "유도",
    "monetizes_via": "수익화",
    "triggers_emotion": "감정 유발",
    "belongs_to_event": "이벤트 소속",
    "is_made_by": "제조사",
    "competitor_of": "경쟁",
    "ceo_of": "대표",
    "suitable_for": "적합 대상",
}


def _sanitize_title(name: str) -> str:
    """Turn an arbitrary node name into a safe Obsidian note title/filename."""
    cleaned = _UNSAFE_CHARS.sub(" ", name or "")
    cleaned = _WS.sub(" ", cleaned).strip()
    # Avoid leading dots (hidden files) and empty titles.
    cleaned = cleaned.lstrip(".").strip()
    return cleaned or "untitled"


def build_title_map(nodes: list[dict[str, Any]]) -> dict[str, str]:
    """Map each node id -> a unique, sanitized note title (collisions suffixed)."""
    title_by_id: dict[str, str] = {}
    used: dict[str, int] = {}
    for node in nodes:
        node_id = str(node.get("id", ""))
        base = _sanitize_title(node.get("name") or node_id)
        title = base
        if base in used:
            used[base] += 1
            title = f"{base} ({used[base]})"
        else:
            used[base] = 0
        title_by_id[node_id] = title
    return title_by_id


def _wikilink(target_id: str, title_by_id: dict[str, str]) -> str:
    """Render a ``[[wikilink]]`` for a target node id (falls back to the id)."""
    title = title_by_id.get(target_id) or _sanitize_title(target_id)
    return f"[[{title}]]"


def build_note_markdown(
    node: dict[str, Any],
    outgoing: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
    title_by_id: dict[str, str],
) -> str:
    """Render a single node into Obsidian Markdown with YAML frontmatter."""
    node_id = str(node.get("id", ""))
    name = node.get("name") or node_id
    node_type = node.get("type", "topic")
    type_label = NODE_TYPE_LABELS.get(node_type, node_type)
    weight = float(node.get("weight", 0.0) or 0.0)

    lines: list[str] = []

    # YAML frontmatter (Obsidian uses this for properties / filtering).
    lines.append("---")
    lines.append(f'id: "{node_id}"')
    lines.append(f"type: {node_type}")
    lines.append(f"weight: {weight}")
    lines.append(f"tags: [{node_type}]")
    lines.append("---")
    lines.append("")

    # Heading.
    lines.append(f"# {name} ({type_label})")
    lines.append("")

    # Properties.
    lines.append("## 속성 (Properties)")
    lines.append(f"- **ID**: `{node_id}`")
    lines.append(f"- **유형(Type)**: {type_label} (`{node_type}`)")
    lines.append(f"- **가중치(Weight)**: {weight}")
    lines.append("")

    # Outgoing relations grouped by relation type.
    lines.append("## 연결된 지식 그래프 (Relations)")
    if outgoing:
        grouped: dict[str, list[str]] = {}
        for edge in outgoing:
            rel = edge.get("relation_type", "related_to")
            grouped.setdefault(rel, []).append(_wikilink(str(edge.get("to_node", "")), title_by_id))
        for rel, links in grouped.items():
            label = RELATION_LABELS.get(rel, rel)
            lines.append(f"- {label} ({rel}): {', '.join(links)}")
    else:
        lines.append("- (연결된 노드가 없습니다)")
    lines.append("")

    # Incoming relations (backlinks).
    if incoming:
        lines.append("## 역방향 연결 (Backlinks)")
        for edge in incoming:
            rel = edge.get("relation_type", "related_to")
            label = RELATION_LABELS.get(rel, rel)
            src = _wikilink(str(edge.get("from_node", "")), title_by_id)
            lines.append(f"- {src} → {label} ({rel})")
        lines.append("")

    return "\n".join(lines)


def build_index_markdown(nodes: list[dict[str, Any]], title_by_id: dict[str, str]) -> str:
    """Render an index (Map of Content) grouping node links by type."""
    by_type: dict[str, list[str]] = {}
    for node in nodes:
        node_type = node.get("type", "topic")
        by_type.setdefault(node_type, []).append(_wikilink(str(node.get("id", "")), title_by_id))

    lines: list[str] = ["# IIGP 지식 그래프 인덱스 (Knowledge Graph Index)", ""]
    lines.append(f"- 총 노드: {len(nodes)}개")
    lines.append("")
    for node_type in sorted(by_type):
        label = NODE_TYPE_LABELS.get(node_type, node_type)
        lines.append(f"## {label} ({node_type})")
        for link in sorted(by_type[node_type]):
            lines.append(f"- {link}")
        lines.append("")
    return "\n".join(lines)


def export_to_vault(graph: dict[str, list[dict[str, Any]]], vault_dir: str) -> dict[str, Any]:
    """Write the graph to ``vault_dir`` as Obsidian Markdown notes + an index.

    Returns a summary dict: ``{vault_dir, node_files, nodes, edges, index}``.
    Never raises on individual file errors — they are logged and skipped.
    """
    nodes = list(graph.get("nodes", []))
    edges = list(graph.get("edges", []))

    os.makedirs(vault_dir, exist_ok=True)
    title_by_id = build_title_map(nodes)

    # Pre-index edges by their endpoints for O(nodes + edges) assembly.
    outgoing_by_id: dict[str, list[dict[str, Any]]] = {}
    incoming_by_id: dict[str, list[dict[str, Any]]] = {}
    for edge in edges:
        outgoing_by_id.setdefault(str(edge.get("from_node", "")), []).append(edge)
        incoming_by_id.setdefault(str(edge.get("to_node", "")), []).append(edge)

    written = 0
    for node in nodes:
        node_id = str(node.get("id", ""))
        title = title_by_id.get(node_id, _sanitize_title(node_id))
        markdown = build_note_markdown(
            node,
            outgoing_by_id.get(node_id, []),
            incoming_by_id.get(node_id, []),
            title_by_id,
        )
        path = os.path.join(vault_dir, f"{title}.md")
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(markdown)
            written += 1
        except OSError as exc:
            _log.error("obsidian_note_write_failed", extra={"node_id": node_id, "error": str(exc)})

    # Index / Map of Content.
    index_written = False
    try:
        with open(os.path.join(vault_dir, "_index.md"), "w", encoding="utf-8") as fh:
            fh.write(build_index_markdown(nodes, title_by_id))
        index_written = True
    except OSError as exc:
        _log.error("obsidian_index_write_failed", extra={"error": str(exc)})

    summary = {
        "vault_dir": vault_dir,
        "node_files": written,
        "nodes": len(nodes),
        "edges": len(edges),
        "index": index_written,
    }
    _log.info("obsidian_export_complete", extra=summary)
    return summary
