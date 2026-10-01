#!/usr/bin/env python3
"""Heading-Aware Passage Chunker and Evidence Extraction Module for SearXNG.

Extracts structured metadata (canonical URL, author, dates, language),
splits article text into heading-anchored passages with overlap,
ranks passages via BM25, and flags prompt injection risks.
"""

from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, ClassVar

from lexical_rerank import MultilingualTokenizer

try:
    import lxml.html

    _HAS_LXML = True
except ImportError:
    _HAS_LXML = False

try:
    import trafilatura

    _HAS_TRAFILATURA = True
except ImportError:
    _HAS_TRAFILATURA = False


@dataclass(frozen=True)
class ChunkerConfig:
    """Configurable boundaries and budgets for passage chunking."""

    min_chunk_chars: int = 15
    target_chunk_chars: int = 800
    max_chunk_chars: int = 1200
    overlap_chars: int = 150
    max_passages_per_page: int = 3
    default_heading: str = "General"

    def __init__(
        self,
        min_chunk_chars: int = 15,
        target_chunk_chars: int = 800,
        max_chunk_chars: int = 1200,
        overlap_chars: int = 150,
        max_passages_per_page: int = 3,
        default_heading: str = "General",
        target_passage_chars: int | None = None,
        max_passage_chars: int | None = None,
    ) -> None:
        object.__setattr__(self, "min_chunk_chars", min_chunk_chars)
        object.__setattr__(
            self,
            "target_chunk_chars",
            target_passage_chars if target_passage_chars is not None else target_chunk_chars,
        )
        object.__setattr__(
            self,
            "max_chunk_chars",
            max_passage_chars if max_passage_chars is not None else max_chunk_chars,
        )
        object.__setattr__(self, "overlap_chars", overlap_chars)
        object.__setattr__(self, "max_passages_per_page", max_passages_per_page)
        object.__setattr__(self, "default_heading", default_heading)


@dataclass
class EvidencePassage:
    """A single coherent, cited evidence passage with stable ID and metadata."""

    id: str  # e.g., 'src_01_p01'
    heading: str = "General"
    text: str = ""
    source_id: str = "src_01"
    score: float = 0.0
    start_char: int = 0
    end_char: int = 0
    extraction_method: str = "trafilatura_heading"
    content_type: str = "text/plain"
    security_flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize passage according to GenAI Structured Response schema."""
        data: dict[str, Any] = {
            "id": self.id,
            "heading": self.heading,
            "text": self.text,
            "score": round(self.score, 4),
        }
        if self.security_flags:
            data["security_flags"] = self.security_flags
        return data


class SecurityScanner:
    """Scans untrusted web text for adversarial prompt injection patterns."""

    INJECTION_PATTERNS: ClassVar[tuple[re.Pattern, ...]] = (
        re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+(instructions|directives|rules)", re.IGNORECASE),
        re.compile(r"disregard\s+(all\s+)?(previous|prior|above)\s+(instructions|directives)", re.IGNORECASE),
        re.compile(r"(system\s+prompt|initial\s+prompt|developer\s+mode)", re.IGNORECASE),
        re.compile(r"(reveal|leak|print|show)\s+(your\s+)?(secret|token|api_key|system\s+prompt)", re.IGNORECASE),
        re.compile(r"(前の指示を(すべて|全部)?(無視|取り消|忘れて))", re.IGNORECASE),
        re.compile(r"((システムプロンプト|機密情報|環境変数)を(開示|送信|表示|出力))", re.IGNORECASE),
        re.compile(r"(You are now in developer mode|DAN mode)", re.IGNORECASE),
        re.compile(r"(exfiltrate\s+to|curl\s+-X\s+POST\s+http)", re.IGNORECASE),
    )

    @classmethod
    def scan_for_injection(cls, text: str) -> list[str]:
        """Scan text and return security warning flags if adversarial injection detected."""
        if not text:
            return []
        flags: list[str] = []
        for pat in cls.INJECTION_PATTERNS:
            if pat.search(text):
                flags.append("possible_prompt_injection")
                break
        return flags


class HTMLMetadataExtractor:
    """Extracts high-fidelity metadata (canonical URL, author, dates, language) from raw HTML."""

    @classmethod
    def extract_metadata(cls, raw_html: str, fallback_url: str = "") -> dict[str, Any]:
        """Extract metadata from HTML using lxml and trafilatura."""
        out: dict[str, Any] = {
            "canonical_url": "",
            "language": "",
            "title": "",
            "author": "",
            "published_at": None,
            "updated_at": None,
            "date_source": None,
            "date_confidence": None,
        }

        if not raw_html:
            return out

        # 1. Trafilatura metadata extraction
        if _HAS_TRAFILATURA:
            try:
                t_meta = trafilatura.extract_metadata(raw_html)
                if t_meta:
                    if t_meta.url:
                        out["canonical_url"] = t_meta.url.strip()
                    if t_meta.title:
                        out["title"] = t_meta.title.strip()
                    if t_meta.author:
                        out["author"] = t_meta.author.strip()
                    if t_meta.date:
                        out["published_at"] = t_meta.date.strip()
                        out["date_source"] = "trafilatura"
                        out["date_confidence"] = "medium"
                    if getattr(t_meta, "language", None):
                        out["language"] = t_meta.language.strip()
            except (AttributeError, KeyError, TypeError, ValueError, IndexError):
                pass

        # 2. Precise lxml parsing for meta tags, canonical, and dates
        if _HAS_LXML:
            try:
                tree = lxml.html.fromstring(raw_html[:500000])

                # Language
                if not out["language"]:
                    html_lang = (
                        tree.get("lang")
                        or tree.xpath("//html/@lang")
                        or tree.xpath("//meta[@http-equiv='content-language']/@content")
                    )
                    if html_lang:
                        lang_val = html_lang[0] if isinstance(html_lang, list) else str(html_lang)
                        out["language"] = lang_val.split("-")[0].strip().lower()

                # Canonical URL
                if not out["canonical_url"]:
                    canonical_href = tree.xpath("//link[@rel='canonical']/@href") or tree.xpath(
                        "//meta[@property='og:url']/@content"
                    )
                    if canonical_href:
                        out["canonical_url"] = str(canonical_href[0]).strip()

                # Author
                if not out["author"]:
                    auth_meta = (
                        tree.xpath("//meta[@name='author']/@content")
                        or tree.xpath("//meta[@property='article:author']/@content")
                        or tree.xpath("//meta[@name='twitter:creator']/@content")
                    )
                    if auth_meta:
                        out["author"] = str(auth_meta[0]).strip()

                # Published date
                pub_meta = (
                    tree.xpath("//meta[@property='article:published_time']/@content")
                    or tree.xpath("//meta[@property='og:published_time']/@content")
                    or tree.xpath("//meta[@name='publication_date']/@content")
                    or tree.xpath("//meta[@name='pubdate']/@content")
                    or tree.xpath("//meta[@name='date']/@content")
                    or tree.xpath("//time[@pubdate]/@datetime")
                    or tree.xpath("//time/@datetime")
                )
                if pub_meta:
                    out["published_at"] = str(pub_meta[0]).strip()
                    out["date_source"] = "meta_article_published"
                    out["date_confidence"] = "high"

                # Updated date
                mod_meta = (
                    tree.xpath("//meta[@property='article:modified_time']/@content")
                    or tree.xpath("//meta[@property='og:updated_time']/@content")
                    or tree.xpath("//meta[@name='last-modified']/@content")
                )
                if mod_meta:
                    out["updated_at"] = str(mod_meta[0]).strip()
                    if not out["date_source"]:
                        out["date_source"] = "meta_article_modified"
                        out["date_confidence"] = "high"

                # Title fallback
                if not out["title"]:
                    t_el = tree.xpath("//title/text()") or tree.xpath("//meta[@property='og:title']/@content")
                    if t_el:
                        out["title"] = str(t_el[0]).strip()
            except (AttributeError, KeyError, TypeError, ValueError, IndexError):
                pass

        if out["canonical_url"] and fallback_url:
            out["canonical_url"] = urllib.parse.urljoin(fallback_url, out["canonical_url"])
        elif not out["canonical_url"] and fallback_url:
            out["canonical_url"] = fallback_url

        return out


class HeadingPassageChunker:
    """Splits full web page content into heading-delimited, sized passages."""

    HEADING_LINE_PAT = re.compile(r"^(#{1,6}\s+.*|<h[1-6][^>]*>.*?</h[1-6]>)$", re.IGNORECASE | re.MULTILINE)

    def __init__(self, config: ChunkerConfig | None = None) -> None:
        self.config = config or ChunkerConfig()
        self.tokenizer = MultilingualTokenizer()

    def _clean_heading(self, raw_heading: str) -> str:
        """Strip markdown `#` or HTML `<hX>` tags from heading text."""
        h = raw_heading.strip()
        h = re.sub(r"^#{1,6}\s+", "", h)
        h = re.sub(r"<[^>]+>", "", h)
        return h.strip() or self.config.default_heading

    def split_into_sections(self, content: str) -> list[tuple[str, str]]:
        """Delineate content by headings into (heading, text_body) tuples."""
        if not content:
            return []

        clean_text = content.replace("\r\n", "\n")
        lines = clean_text.split("\n")

        sections: list[tuple[str, list[str]]] = []
        current_heading = self.config.default_heading
        current_lines: list[str] = []

        for line in lines:
            line_str = line.strip()
            # Detect heading lines
            if line_str.startswith(("# ", "## ", "### ", "#### ", "##### ", "###### ")) or re.match(
                r"^<h[1-6][^>]*>.*?</h[1-6]>$", line_str, re.IGNORECASE
            ):
                if current_lines:
                    sections.append((current_heading, current_lines))
                    current_lines = []
                current_heading = self._clean_heading(line_str)
            else:
                current_lines.append(line)

        if current_lines:
            sections.append((current_heading, current_lines))

        result: list[tuple[str, str]] = []
        for h, l_list in sections:
            body = "\n".join(l_list).strip()
            if body:
                result.append((h, body))

        return result or [(self.config.default_heading, content.strip())]

    def _chunk_section_body(
        self,
        heading: str,
        body: str,
        source_id: str,
        base_char_offset: int,
    ) -> list[EvidencePassage]:
        """Split a single section body into overlapping passages respecting length bounds."""
        passages: list[EvidencePassage] = []
        if len(body) <= self.config.max_chunk_chars:
            if len(body) >= self.config.min_chunk_chars:
                flags = SecurityScanner.scan_for_injection(body)
                passages.append(
                    EvidencePassage(
                        id="",  # assigned later
                        source_id=source_id,
                        heading=heading,
                        text=body,
                        start_char=base_char_offset,
                        end_char=base_char_offset + len(body),
                        security_flags=flags,
                    )
                )
            return passages

        # Split longer section into paragraphs or sentences
        paragraphs = re.split(r"(\n\n+)", body)
        buffer = ""
        buf_start = base_char_offset

        for p in paragraphs:
            p_clean = p.strip()
            if not p_clean:
                continue

            if len(buffer) + len(p_clean) + 1 <= self.config.target_chunk_chars:
                buffer = f"{buffer}\n\n{p_clean}" if buffer else p_clean
            else:
                if len(buffer) >= self.config.min_chunk_chars:
                    flags = SecurityScanner.scan_for_injection(buffer)
                    passages.append(
                        EvidencePassage(
                            id="",
                            source_id=source_id,
                            heading=heading,
                            text=buffer,
                            start_char=buf_start,
                            end_char=buf_start + len(buffer),
                            security_flags=flags,
                        )
                    )
                    # Prepare overlap from end of buffer
                    overlap = buffer[-self.config.overlap_chars :] if len(buffer) > self.config.overlap_chars else ""
                    buf_start = buf_start + len(buffer) - len(overlap)
                    buffer = f"{overlap}\n{p_clean}" if overlap else p_clean
                else:
                    buffer = f"{buffer}\n\n{p_clean}" if buffer else p_clean

        if len(buffer.strip()) >= self.config.min_chunk_chars:
            flags = SecurityScanner.scan_for_injection(buffer)
            passages.append(
                EvidencePassage(
                    id="",
                    source_id=source_id,
                    heading=heading,
                    text=buffer.strip(),
                    start_char=buf_start,
                    end_char=buf_start + len(buffer),
                    security_flags=flags,
                )
            )

        return passages

    def extract_evidence(
        self,
        content: str,
        query: str,
        source_id: str,
        max_passages: int | None = None,
    ) -> list[EvidencePassage]:
        """Extract, chunk, and rank evidence passages for a specific query."""
        if not content:
            return []

        max_p = max_passages or self.config.max_passages_per_page
        sections = self.split_into_sections(content)

        all_candidates: list[EvidencePassage] = []
        char_offset = 0

        for h, body in sections:
            sec_passages = self._chunk_section_body(
                heading=h,
                body=body,
                source_id=source_id,
                base_char_offset=char_offset,
            )
            all_candidates.extend(sec_passages)
            char_offset += len(body) + 2

        if not all_candidates:
            # Fallback for short texts: use the first meaningful section heading
            first_heading = (
                sections[0][0]
                if (sections and sections[0][0] != self.config.default_heading)
                else self.config.default_heading
            )
            text_clean = content.strip()[: self.config.max_chunk_chars]
            if text_clean:
                flags = SecurityScanner.scan_for_injection(text_clean)
                all_candidates.append(
                    EvidencePassage(
                        id=f"{source_id}_p01",
                        source_id=source_id,
                        heading=first_heading,
                        text=text_clean,
                        start_char=0,
                        end_char=len(text_clean),
                        security_flags=flags,
                    )
                )

        # Score passages against query tokens using BM25
        q_tokens = set(self.tokenizer.tokenize(query))
        q_lower = query.strip().lower()

        for p in all_candidates:
            p_tokens = self.tokenizer.tokenize(f"{p.heading} {p.text}")
            tf_map: dict[str, int] = {}
            for t in p_tokens:
                tf_map[t] = tf_map.get(t, 0) + 1

            p_score = 0.0
            for qt in q_tokens:
                if qt in tf_map:
                    p_score += tf_map[qt] * 1.5

            # Phrase bonus
            if q_lower and q_lower in p.text.lower():
                p_score += 4.0
            if q_lower and q_lower in p.heading.lower():
                p_score += 3.0

            p.score = p_score

        # Sort candidate passages by relevance score descending
        all_candidates.sort(key=lambda x: x.score, reverse=True)
        chosen = all_candidates[:max_p]

        # Assign stable passage IDs: src_01_p01, src_01_p02, ...
        for idx, pass_item in enumerate(chosen, start=1):
            pass_item.id = f"{source_id}_p{idx:02d}"

        return chosen

    def split_into_passages(self, content: str, source_id: str = "src_01") -> list[EvidencePassage]:
        """Split content into heading passages without score filtering, keeping all passages."""
        sections = self.split_into_sections(content)
        all_candidates: list[EvidencePassage] = []
        char_offset = 0
        for h, body in sections:
            sec_passages = self._chunk_section_body(
                heading=h,
                body=body,
                source_id=source_id,
                base_char_offset=char_offset,
            )
            all_candidates.extend(sec_passages)
            char_offset += len(body) + 2

        if not all_candidates:
            first_heading = (
                sections[0][0]
                if (sections and sections[0][0] != self.config.default_heading)
                else self.config.default_heading
            )
            text_clean = content.strip()[: self.config.max_chunk_chars]
            if text_clean:
                flags = SecurityScanner.scan_for_injection(text_clean)
                all_candidates.append(
                    EvidencePassage(
                        id=f"{source_id}_p01",
                        source_id=source_id,
                        heading=first_heading,
                        text=text_clean,
                        start_char=0,
                        end_char=len(text_clean),
                        security_flags=flags,
                    )
                )

        for idx, pass_item in enumerate(all_candidates, start=1):
            pass_item.id = f"{source_id}_p{idx:02d}"

        return all_candidates

    def score_passages(self, passages: list[EvidencePassage], query: str) -> list[EvidencePassage]:
        """Score and sort given passages against a search query."""
        q_tokens = set(self.tokenizer.tokenize(query))
        q_lower = query.strip().lower()

        for p in passages:
            p_tokens = self.tokenizer.tokenize(f"{p.heading} {p.text}")
            tf_map: dict[str, int] = {}
            for t in p_tokens:
                tf_map[t] = tf_map.get(t, 0) + 1

            p_score = 0.0
            for qt in q_tokens:
                if qt in tf_map:
                    p_score += tf_map[qt] * 1.5

            if q_lower and q_lower in p.text.lower():
                p_score += 4.0
            if q_lower and q_lower in p.heading.lower():
                p_score += 3.0

            p.score = p_score

        return sorted(passages, key=lambda x: x.score, reverse=True)


HeadingPassageSplitter = HeadingPassageChunker
PassageChunkerConfig = ChunkerConfig
PassageChunk = EvidencePassage
MetadataExtractor = HTMLMetadataExtractor


def extract_metadata_and_headings(url: str, html_content: str) -> dict[str, Any]:
    """Helper to extract metadata and headings from HTML."""
    return HTMLMetadataExtractor.extract_metadata(raw_html=html_content, fallback_url=url)
