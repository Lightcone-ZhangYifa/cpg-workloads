"""Rebuild reference_corpus indexes/readers from the preserved, verified source files.

Rendering requires the bundled Python-Markdown wheel, not an online install.
C++ navigation can be regenerated from an explicitly prepared source tree.
"""
from __future__ import annotations
import argparse
import hashlib
import html
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import urllib.parse
import zipfile


def dump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relpath(path: Path, start: Path) -> str:
    return Path(os.path.relpath(path, start)).as_posix()


CSS = """body{max-width:1000px;margin:2em auto;padding:0 1em;font:17px/1.6 system-ui;color:#17232b}
nav,aside{padding:.8em;background:#eef2f4}a{color:#075f91}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f5f6;padding:1em}
code{font-size:.9em}table{display:block;max-width:100%;overflow:auto;border-collapse:collapse}td,th{border:1px solid #c6d0d7;padding:.35em}img{max-width:100%}
.line{display:block}.ln{display:inline-block;width:5em;text-align:right;color:#637585;padding-right:1em}.metadata{font-size:.85em;color:#40545e}"""


def page(title: str, body: str, notice: str, scripts: str = "") -> str:
    return ("<!doctype html><html lang='en'><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<meta http-equiv='Content-Security-Policy' content=\"default-src 'none'; "
            "img-src 'self' data:; style-src 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
            "connect-src 'none'; font-src 'self'\">"
            f"<title>{html.escape(title)}</title><style>{CSS}</style><body>"
            f"<aside class='metadata'>{notice}</aside>{body}{scripts}</body></html>\n")


def db_build(root: Path, rows: list[dict]) -> None:
    db = root / "search.sqlite"
    db.unlink(missing_ok=True)
    with sqlite3.connect(db) as con:
        con.execute("PRAGMA journal_mode=DELETE")
        con.execute("CREATE VIRTUAL TABLE fts USING fts5(path UNINDEXED, anchor, "
                    "line_start UNINDEXED,line_end UNINDEXED,title,source_url UNINDEXED,"
                    "local_url UNINDEXED,text, tokenize='unicode61')")
        con.executemany("INSERT INTO fts VALUES(?,?,?,?,?,?,?,?)", [
            tuple(row.get(k, "") for k in
                  ("path", "anchor", "line_start", "line_end", "title", "source_url", "local_url", "text"))
            for row in rows])
        con.execute("INSERT INTO fts(fts) VALUES('optimize')")
    dump(root / "index-stats.json", {"sections": len(rows), "sqlite_fts5": True})


def md_sections(text: str):
    lines = text.splitlines(); headings = []
    fence = None; frontmatter = lines and lines[0] == "---"; seen = {}
    for i, line in enumerate(lines, 1):
        if frontmatter:
            if i > 1 and line == "---": frontmatter = False
            continue
        f = re.match(r"^\s*(`{3,}|~{3,})", line)
        if f:
            token = f.group(1)
            if fence is None: fence = token[0]
            elif fence == token[0]: fence = None
            continue
        if fence: continue
        h = re.match(r"^(#{1,6})\s+(.+?)(?:\s+#+)?\s*$", line)
        if h:
            title = h.group(2)
            # The generated source-line anchors are authoritative; slug is for navigation.
            slug = re.sub(r"[^\w\- ]", "", title.lower()).strip().replace(" ", "-")
            count = seen.get(slug, 0); seen[slug] = count + 1
            if count: slug += f"-{count}"
            headings.append((i, title, slug))
    if not headings or headings[0][0] > 1:
        headings.insert(0, (1, "Document preamble", "document-preamble"))
    for pos, (start, title, anchor) in enumerate(headings):
        finish = headings[pos + 1][0] - 1 if pos + 1 < len(headings) else len(lines)
        yield start, finish, title, anchor


def source_page(root: Path, path: Path, title: str, notice: str) -> str:
    relative = path.relative_to(root)
    out = root / "source" / (relative.as_posix() + ".html")
    out.parent.mkdir(parents=True, exist_ok=True)
    raw = path.read_text(encoding="utf-8")
    body = f"<h1>{html.escape(title)}</h1><pre>" + "\n".join(
        f"<span class='line' id='L{i}'><a class='ln' href='#L{i}'>{i}</a>{html.escape(line)}</span>"
        for i, line in enumerate(raw.splitlines(), 1)) + "</pre>"
    out.write_text(page(title, body, notice), encoding="utf-8")
    return out.relative_to(root).as_posix()


def render_md(root: Path, source: Path, metadata: dict, markdown) -> dict:
    relative = source.relative_to(root)
    out = root / "rendered" / relative.with_suffix(".html")
    out.parent.mkdir(parents=True, exist_ok=True)
    text = source.read_text(encoding="utf-8")
    text = re.sub(r"\A---\n.*?\n---\n", "", text, count=1, flags=re.S)
    text = re.sub(r"^\* TOC\s*\n\{\:toc\}\s*", "", text, flags=re.M)
    # Upstream uses valid CommonMark fences with up to three leading spaces;
    # Python-Markdown's fence extension expects column zero.
    text = re.sub(r"(?m)^[ \t]{1,3}(`{3,}|~{3,})", r"\1", text)
    # A known upstream ACLE link omits the closing angle bracket. Repair only
    # the rendered view; its original source bytes and line view stay intact.
    text = re.sub(r"\]\(<(https?://[^)\n]+)\)", r"](\1)", text)
    # Preserve rustdoc fence flags in the source; render their first language token.
    text = re.sub(r"^(\s*```)([A-Za-z0-9_+-]+),[^\n]*", r"\1\2", text, flags=re.M)
    include_count = 0
    def include(m):
        nonlocal include_count
        target = (source.parent / m.group(1).strip()).resolve()
        if not target.is_relative_to((root / "upstream").resolve()) or not target.is_file():
            raise ValueError("unresolved or escaping mdbook include: " + m.group(1))
        include_count += 1
        return "```rust\n" + target.read_text() + "\n```"
    text = re.sub(r"\{\{#include ([^}]+)\}\}", include, text)
    text = re.sub(r"\{\s*#([^}]+)\}", r"{#\1}", text)
    md = markdown.Markdown(extensions=["tables", "fenced_code", "toc", "attr_list", "md_in_html"])
    body = md.convert(text)
    # Rewrite only known local files. Other links stay explicit external references.
    def link(m):
        attr, q, value = m.group(1), m.group(2), html.unescape(m.group(3))
        parsed = urllib.parse.urlsplit(value)
        if parsed.scheme or parsed.netloc or not parsed.path:
            return m.group(0)
        decoded = urllib.parse.unquote(parsed.path)
        if decoded.startswith("/"):
            target = (root / "upstream" / ("src" if metadata["resource_id"] == "rustc-dev-guide" else "") / decoded.lstrip("/")).resolve()
        else:
            target = (source.parent / decoded).resolve()
        if not target.is_relative_to(root.resolve()):
            return m.group(0)
        if target.suffix == ".html" and not target.exists() and target.with_suffix(".md").exists():
            target = target.with_suffix(".md")
        if target.is_file():
            if target.suffix.lower() == ".md":
                dest = root / "rendered" / target.relative_to(root).with_suffix(".html")
            else:
                dest = target
            new = relpath(dest, out.parent)
            if parsed.fragment: new += "#" + parsed.fragment
            return f"{attr}={q}{html.escape(new, quote=True)}{q}"
        # A referenced tree outside the explicitly distributed scope remains
        # an explicit pinned upstream link, never a broken local document.
        upstream = (root / "upstream").resolve()
        if target.is_relative_to(upstream):
            upstream_url = metadata["source_base_url"] + target.relative_to(upstream).as_posix()
            if parsed.fragment: upstream_url += "#" + parsed.fragment
            return f"{attr}={q}{html.escape(upstream_url, quote=True)}{q}"
        return m.group(0)
    body = re.sub(r"\b(href|src)=([\"'])(.*?)\2", link, body)
    title = next((t for _, _, t, _ in md_sections(source.read_text()) if t != "Document preamble"), source.name)
    rawlink = relpath(root / "source" / (relative.as_posix() + ".html"), out.parent)
    homelink = relpath(root / "index.html", out.parent)
    notice = (f"CPG offline reader · {html.escape(metadata['version'])} · "
              f"<a href='{html.escape(homelink)}'>Contents</a> · "
              f"<a href='{html.escape(rawlink)}'>Exact source and line numbers</a><br>"
              + html.escape(metadata["license_notice"]))
    scripts = ""
    diagrams = body.count('class="language-mermaid"')
    if diagrams and (root / "upstream/mermaid.min.js").is_file():
        body = re.sub(r'<pre><code class="language-mermaid">(.*?)</code></pre>', r'<pre class="mermaid">\1</pre>', body, flags=re.S)
        js = relpath(root / "upstream/mermaid.min.js", out.parent)
        scripts = (f"<script src='{html.escape(js)}'></script>"
                   "<script>mermaid.initialize({startOnLoad:true,securityLevel:'strict'});</script>")
    out.write_text(page(title, f"<nav>{md.toc}</nav>" + body, notice, scripts), encoding="utf-8")
    return {"source": relative.as_posix(), "html": out.relative_to(root).as_posix(),
            "title": title, "includes": include_count, "mermaid_diagrams": diagrams}


def build_markdown(root: Path, metadata: dict, markdown) -> None:
    files = []
    for path in sorted((root / "upstream").rglob("*")):
        if path.is_symlink(): raise ValueError("source symlink not permitted")
        if not path.is_file(): continue
        relative = path.relative_to(root).as_posix()
        repo_rel = path.relative_to(root / "upstream").as_posix()
        files.append({"path": relative, "bytes": path.stat().st_size, "sha256": digest(path),
                      "url": metadata["raw_base_url"] + repo_rel, "distributed": True})
    dump(root / "source-lock.json", {"resource_id": metadata["resource_id"], "files": files})
    rows = []; anchors = []; pages = []; examples = []; intrinsics = []; rustpaths = []
    for source in sorted((root / "upstream").rglob("*.md")):
        text = source.read_text(); relative = source.relative_to(root).as_posix()
        url = metadata["source_base_url"] + source.relative_to(root / "upstream").as_posix()
        local = source_page(root, source, relative, html.escape(metadata["license_notice"]))
        lines = text.splitlines()
        for start, finish, title, anchor in md_sections(text):
            anchors.append({"anchor": anchor, "path": relative, "line_start": start,
                            "line_end": finish, "title": title, "source_url": url + f"#L{start}",
                            "local_url": local + f"#L{start}"})
            for chunk in range(start, finish + 1, 60):
                end = min(finish, chunk + 59)
                rows.append({"anchor": anchor, "path": relative, "line_start": chunk,
                             "line_end": end, "title": title, "source_url": url + f"#L{chunk}",
                             "local_url": local + f"#L{chunk}", "text": "\n".join(lines[chunk-1:end])})
        pages.append(render_md(root, source, metadata, markdown))
        if metadata["resource_id"] == "arm-acle":
            for i, line in enumerate(lines, 1):
                if line.lstrip().startswith("|"):
                    first_cell = line.split("|", 2)[1]
                    plain = html.unescape(re.sub(r"<[^>]+>", " ", first_cell))
                    plain = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", plain).replace("`", "")
                    signature = re.sub(r"\s+", " ", plain).strip()
                    for symbol in sorted(set(re.findall(r"\b((?:v|sv)[A-Za-z0-9_]+)\s*\(", signature))):
                        intrinsics.append({"name": symbol, "path": relative, "line": i,
                                           "signature": signature, "source_url": url + f"#L{i}",
                                           "local_url": local + f"#L{i}"})
            opening = None
            for i, line in enumerate(lines, 1):
                mark = re.match(r"^[ \t]*(`{3,}|~{3,})([^\n]*)$", line)
                if opening is None and mark:
                    opening = (i, mark.group(1), mark.group(2).strip())
                elif opening and mark and not mark.group(2).strip() and mark.group(1)[0] == opening[1][0]:
                    start, fence, language = opening
                    if language in ("", "c", "cpp", "c++"):
                        examples.append({"id": f"{relative}:{start}", "path": relative,
                                         "line": start, "language": language or "unspecified",
                                         "code": "\n".join(lines[start:i-1]),
                                         "source_url": url + f"#L{start}"})
                    opening = None
        else:
            for i, line in enumerate(lines, 1):
                for value in re.findall(r"(?:compiler|library|src|tests)/[A-Za-z0-9_./-]+", line):
                    rustpaths.append({"compiler_path_reference": value.rstrip("./"),
                                      "document_path": relative, "document_line": i,
                                      "document_commit": metadata["commit"],
                                      "code_checkout_verified": False})
    dump(root / "anchors.json", anchors); dump(root / "render-manifest.json", pages)
    db_build(root, rows)
    if metadata["resource_id"] == "arm-acle":
        (root / "intrinsics.jsonl").write_text("".join(json.dumps(x) + "\n" for x in intrinsics))
        (root / "examples.jsonl").write_text("".join(json.dumps(x) + "\n" for x in examples))
    else:
        dump(root / "compiler-path-references.json", rustpaths)
    body = "<h1>" + html.escape(metadata["title"]) + "</h1><p>" + html.escape(metadata["scope"]) + "</p><ul>"
    body += "".join(f"<li><a href='{html.escape(p['html'])}'>{html.escape(p['source'])}</a></li>" for p in pages)
    body += "</ul><p>Use reader.py search for the offline full-text index. Exact source bytes and line anchors remain available on every page.</p>"
    (root / "index.html").write_text(page(metadata["title"], body, html.escape(metadata["license_notice"])))
    dump(root / "build-statistics.json", {"source_files": len(files), "markdown_pages": len(pages),
         "sections": len(anchors), "search_chunks": len(rows), "examples": len(examples),
         "intrinsic_occurrences": len(intrinsics), "compiler_path_references": len(rustpaths),
         "resolved_includes": sum(p["includes"] for p in pages),
         "mermaid_diagrams": sum(p["mermaid_diagrams"] for p in pages)})


def build_cplusplus(root: Path, metadata: dict, source_root: Path) -> None:
    files = []; anchors = []
    for source in sorted((source_root / "source").glob("*.tex")):
        relative = "upstream/source/" + source.name
        url = metadata["raw_base_url"] + "source/" + source.name
        text = source.read_text(); lines = text.splitlines()
        files.append({"path": relative, "bytes": source.stat().st_size, "sha256": digest(source),
                      "url": url, "distributed": False})
        matches = list(re.finditer(r"(?m)^\\rSec([0-9]+)\[([^\]]+)\]", text))
        for i, match in enumerate(matches):
            start = text[:match.start()].count("\n") + 1
            end = text[:matches[i+1].start()].count("\n") if i+1<len(matches) else len(lines)
            anchors.append({"anchor": match.group(2), "level": int(match.group(1)),
                            "path": relative, "line_start": start, "line_end": end,
                            "title": "[" + match.group(2) + "]", "draft": metadata["version"],
                            "source_url": metadata["source_base_url"] + "source/" + source.name + f"#L{start}",
                            "local_url": "index.html#" + match.group(2)})
    if not anchors or len({a["anchor"] for a in anchors}) != len(anchors):
        raise ValueError("empty or duplicate C++ section anchors")
    dump(root / "source-lock.json", {"resource_id": metadata["resource_id"], "files": files})
    dump(root / "anchors.json", anchors)
    db_build(root, [{**a, "text": a["anchor"] + " " + a["path"]} for a in anchors])
    body = "<h1>C++ " + html.escape(metadata["version"]) + " chapter navigation</h1><p>" + html.escape(metadata["scope"]) + "</p><ul>"
    body += "".join(f"<li id='{html.escape(a['anchor'])}'><a href='{html.escape(a['source_url'])}'>[{html.escape(a['anchor'])}]</a> — {html.escape(a['path'])}:{a['line_start']}–{a['line_end']}</li>" for a in anchors)
    body += "</ul>"
    (root / "index.html").write_text(page(metadata["title"], body, html.escape(metadata["license_notice"])))
    dump(root / "build-statistics.json", {"pinned_tex_files": len(files), "section_anchors": len(anchors),
                                         "distributed_source_bodies": 0, "search_scope": "section labels and source paths"})


def finalize(root: Path, recipe: Path) -> None:
    for name in ("reader.py", "prepare_external.py", "verify.py"):
        shutil.copy2(recipe / name, root / name)
    inventory = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.relative_to(root).as_posix() != "payload-manifest.json":
            inventory.append({"path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size,
                              "sha256": digest(path)})
    dump(root / "payload-manifest.json", {"schema_version": 1, "files": inventory})


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--markdown-wheel", type=Path)
    ap.add_argument("--cpp-source-root", type=Path)
    args = ap.parse_args(); root = args.root.resolve()
    metadata = json.loads((root / "metadata.json").read_text())
    if metadata["resource_id"] in ("arm-acle", "rustc-dev-guide"):
        if not args.markdown_wheel: raise ValueError("provide the pinned local --markdown-wheel")
        sys.path.insert(0, str(args.markdown_wheel.resolve()))
        import markdown
        if markdown.__version__ != "3.10.2": raise ValueError("expected Markdown 3.10.2")
        build_markdown(root, metadata, markdown)
    elif metadata["resource_id"] == "cplusplus-draft":
        if args.cpp_source_root is None: raise ValueError("provide prepared --cpp-source-root")
        build_cplusplus(root, metadata, args.cpp_source_root.resolve())
    else:
        raise ValueError("use curated metadata generation for WG14")
    finalize(root, Path(__file__).resolve().parent)
    print(json.dumps(json.loads((root / "build-statistics.json").read_text()), indent=2))


if __name__ == "__main__":
    main()
