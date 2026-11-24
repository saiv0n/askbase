from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

TEXT_EXT = {".md", ".markdown", ".txt", ".rst"}
HTML_EXT = {".html", ".htm"}


@dataclass
class Doc:
    source: str  # file path or url, shown to users as the citation link
    title: str
    text: str


@dataclass
class Chunk:
    source: str
    title: str
    heading: str
    text: str


def _html_to_text(html: str) -> tuple[str, str]:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "form", "svg"]):
        tag.decompose()
    title = soup.title.get_text(strip=True) if soup.title else ""
    root = soup.find("main") or soup.find("article") or soup.body or soup
    # keep headings as markdown so the chunker can split on them
    for h in root.find_all(re.compile(r"^h[1-6]$")):
        h.replace_with(f"\n\n{'#' * int(h.name[1])} {h.get_text(' ', strip=True)}\n\n")
    for li in reversed(root.find_all("li")):
        li.replace_with(f"\n- {li.get_text(' ', strip=True)}\n")
    text = root.get_text("\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    return title, text


def _pdf_to_text(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(path)
    pages = []
    for i, page in enumerate(reader.pages, 1):
        t = (page.extract_text() or "").strip()
        if t:
            pages.append(f"## Page {i}\n\n{t}")
    return "\n\n".join(pages)


def _first_heading(text: str) -> str | None:
    m = re.search(r"^#\s+(.+)$", text, re.M)
    return m.group(1).strip() if m else None


def load_path(path: str | Path) -> list[Doc]:
    path = Path(path)
    files = sorted(p for p in path.rglob("*") if p.is_file()) if path.is_dir() else [path]
    docs = []
    for f in files:
        ext = f.suffix.lower()
        if ext in TEXT_EXT:
            text = f.read_text(encoding="utf-8", errors="replace")
            docs.append(Doc(str(f), _first_heading(text) or f.stem.replace("-", " ").title(), text))
        elif ext in HTML_EXT:
            title, text = _html_to_text(f.read_text(encoding="utf-8", errors="replace"))
            docs.append(Doc(str(f), title or f.stem, text))
        elif ext == ".pdf":
            docs.append(Doc(str(f), f.stem.replace("-", " ").title(), _pdf_to_text(f)))
        else:
            log.debug("skipping %s", f)
    return [d for d in docs if d.text.strip()]


def load_urls(urls: list[str], max_pages: int = 200, client: httpx.Client | None = None) -> list[Doc]:
    """Fetch pages, following same-site links from each start url (breadth first)."""
    client = client or httpx.Client(timeout=20, follow_redirects=True,
                                    headers={"User-Agent": "askbase/0.1"})
    docs: list[Doc] = []
    seen: set[str] = set()
    queue = list(urls)
    allowed = {urlsplit(u).netloc for u in urls}
    while queue and len(seen) < max_pages:
        url = queue.pop(0).split("#")[0]
        if url in seen:
            continue
        seen.add(url)
        try:
            r = client.get(url)
            r.raise_for_status()
        except httpx.HTTPError as e:
            log.warning("skip %s: %s", url, e)
            continue
        if "html" not in r.headers.get("content-type", "html"):
            continue
        title, text = _html_to_text(r.text)
        if text:
            docs.append(Doc(url, title or url, text))
        for a in BeautifulSoup(r.text, "lxml").select("a[href]"):
            nxt = urljoin(url, a["href"]).split("#")[0]
            parts = urlsplit(nxt)
            if parts.scheme in ("http", "https") and parts.netloc in allowed and nxt not in seen \
                    and not re.search(r"\.(png|jpe?g|gif|svg|zip|pdf|mp4|css|js)$", parts.path, re.I):
                queue.append(nxt)
    return docs


def chunk(doc: Doc, size: int = 1200, overlap: int = 150) -> list[Chunk]:
    """Split on headings first, then on paragraphs, so a chunk rarely cuts a thought in half."""
    sections: list[tuple[str, str]] = []
    heading, buf = doc.title, []
    for line in doc.text.splitlines():
        m = re.match(r"^#{1,6}\s+(.+)$", line)
        if m:
            if "".join(buf).strip():
                sections.append((heading, "\n".join(buf).strip()))
            heading, buf = m.group(1).strip(), []
        else:
            buf.append(line)
    if "".join(buf).strip():
        sections.append((heading, "\n".join(buf).strip()))

    out: list[Chunk] = []
    for heading, body in sections:
        paras = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
        cur = ""
        for p in paras:
            while len(p) > size:
                # a single giant paragraph: hard split at a sentence end if possible
                cut = p.rfind(". ", 0, size)
                cut = cut + 1 if cut > size // 2 else size
                if cur:
                    out.append(Chunk(doc.source, doc.title, heading, cur))
                    cur = ""
                out.append(Chunk(doc.source, doc.title, heading, p[:cut].strip()))
                p = p[max(cut - overlap, 1):].strip()
            if cur and len(cur) + len(p) + 2 > size:
                out.append(Chunk(doc.source, doc.title, heading, cur))
                cur = cur[-overlap:].split(" ", 1)[-1] + "\n\n" + p if overlap else p
            else:
                cur = f"{cur}\n\n{p}" if cur else p
        if cur:
            out.append(Chunk(doc.source, doc.title, heading, cur))
    return out
