"""
Content processing utilities for OpenZIM MCP server.
"""

import logging
import re
from typing import Any, Dict, List, Union, cast
from urllib.parse import urlparse

import html2text
from bs4 import BeautifulSoup, PageElement, Tag

from .constants import DEFAULT_SNIPPET_LENGTH, UNWANTED_HTML_SELECTORS

logger = logging.getLogger(__name__)


class ContentProcessor:
    """Handles HTML to text conversion and content processing."""

    def __init__(self, snippet_length: int = DEFAULT_SNIPPET_LENGTH):
        """
        Initialize content processor.

        Args:
            snippet_length: Maximum length for content snippets
        """
        self.snippet_length = snippet_length
        self._html_converter = self._create_html_converter()
        logger.debug(
            f"ContentProcessor initialized with snippet_length={snippet_length}"
        )

    def _create_html_converter(self) -> html2text.HTML2Text:
        """Create and configure HTML to text converter."""
        converter = html2text.HTML2Text()
        converter.ignore_links = False
        converter.ignore_images = True
        converter.ignore_tables = False
        converter.unicode_snob = True  # Use Unicode instead of ASCII
        converter.body_width = 0  # No line wrapping
        return converter

    def html_to_plain_text(self, html_content: str) -> str:
        """
        Convert HTML to clean plain text.

        Args:
            html_content: HTML content to convert

        Returns:
            Converted plain text
        """
        if not html_content:
            return ""

        try:
            # Parse HTML with BeautifulSoup
            soup = BeautifulSoup(html_content, "html.parser")

            # Remove unwanted elements
            for selector in UNWANTED_HTML_SELECTORS:
                for element in soup.select(selector):
                    element.decompose()

            # Convert to text using html2text
            text = self._html_converter.handle(str(soup))

            # Clean up excess empty lines
            text = re.sub(r"\n{3,}", "\n\n", text)

            return text.strip()

        except Exception as e:
            logger.warning(f"Error converting HTML to text: {e}")
            # Fallback: return raw text content
            soup = BeautifulSoup(html_content, "html.parser")
            return soup.get_text().strip()

    def create_snippet(self, content: str, max_paragraphs: int = 2) -> str:
        """
        Create a snippet from content.

        Args:
            content: Full content text
            max_paragraphs: Maximum number of paragraphs to include

        Returns:
            Content snippet
        """
        if not content:
            return ""

        # Split into paragraphs and take first few
        paragraphs = content.split("\n\n")
        if len(paragraphs) > max_paragraphs:
            snippet_text = " ".join(paragraphs[:max_paragraphs])
        else:
            snippet_text = content

        # Truncate if too long
        if len(snippet_text) > self.snippet_length:
            snippet_text = snippet_text[: self.snippet_length].strip() + "..."

        return snippet_text

    def truncate_content(self, content: str, max_length: int) -> str:
        """
        Truncate content to maximum length with informative message.

        Args:
            content: Content to truncate
            max_length: Maximum allowed length

        Returns:
            Truncated content with metadata
        """
        if not content or len(content) <= max_length:
            return content

        truncated = content[:max_length].strip()
        total_length = len(content)

        return (
            f"{truncated}\n\n"
            f"... [Content truncated, total of {total_length:,} characters, "
            f"only showing first {max_length:,} characters] ..."
        )

    def process_mime_content(self, content_bytes: bytes, mime_type: str) -> str:
        """
        Process content based on MIME type.

        Args:
            content_bytes: Raw content bytes
            mime_type: MIME type of the content

        Returns:
            Processed text content
        """
        try:
            # Decode bytes to string
            raw_content = content_bytes.decode("utf-8", errors="replace")

            if mime_type.startswith("text/html"):
                return self.html_to_plain_text(raw_content)
            elif mime_type.startswith("text/"):
                return raw_content.strip()
            elif mime_type.startswith("image/"):
                return "(Image content - Cannot display directly)"
            else:
                return f"(Unsupported content type: {mime_type})"

        except Exception as e:
            logger.warning(f"Error processing content with MIME type {mime_type}: {e}")
            return f"(Error processing content: {e})"

    def extract_html_structure(self, html_content: str) -> Dict[str, Any]:
        """
        Extract structure from HTML content including headings and sections.

        Args:
            html_content: HTML content to analyze

        Returns:
            Dictionary containing structure information
        """
        structure = {"headings": [], "sections": [], "metadata": {}, "word_count": 0}

        try:
            soup = BeautifulSoup(html_content, "html.parser")

            # Extract metadata from meta tags BEFORE removing unwanted elements
            metadata = {}
            for meta in soup.find_all("meta"):
                if isinstance(meta, Tag):
                    name = (
                        meta.get("name")
                        or meta.get("property")
                        or meta.get("http-equiv")
                    )
                    content = meta.get("content")
                    if name and content:
                        metadata[name] = content

            structure["metadata"] = metadata

            # Remove unwanted elements for analysis
            for selector in UNWANTED_HTML_SELECTORS:
                for element in soup.select(selector):
                    element.decompose()

            # Extract headings (h1-h6)
            headings: List[Dict[str, Any]] = []
            for level in range(1, 7):
                for heading in soup.find_all(f"h{level}"):
                    if isinstance(heading, Tag):
                        text = heading.get_text().strip()
                        if text:
                            headings.append(
                                {
                                    "level": level,
                                    "text": text,
                                    "id": heading.get("id", ""),
                                    "position": len(headings),
                                }
                            )

            structure["headings"] = headings

            # Extract sections based on headings
            sections = []
            current_section: Union[Dict[str, Union[str, int]], None] = None

            elements: List[PageElement] = soup.find_all(
                ["h1", "h2", "h3", "h4", "h5", "h6", "p", "div"]
            )
            for page_element in elements:
                if isinstance(page_element, Tag) and page_element.name:
                    # MyPy type narrowing: page_element is now definitely a Tag
                    element = cast(Tag, page_element)
                    if element.name.startswith("h"):
                        # Start new section
                        if current_section:
                            sections.append(current_section)

                        current_section = {
                            "title": element.get_text().strip(),
                            "level": int(element.name[1]),
                            "content_preview": "",
                            "word_count": 0,
                        }
                    elif current_section and element.name in ["p", "div"]:
                        # Add content to current section
                        text = element.get_text().strip()
                        content_preview = cast(str, current_section["content_preview"])
                        if text and len(content_preview) < 300:
                            if content_preview:
                                current_section["content_preview"] = (
                                    cast(str, current_section["content_preview"]) + " "
                                )
                            current_section["content_preview"] = (
                                cast(str, current_section["content_preview"])
                                + text[: 300 - len(content_preview)]
                            )
                        current_section["word_count"] = cast(
                            int, current_section["word_count"]
                        ) + len(text.split())

            # Add the last section
            if current_section:
                sections.append(current_section)

            structure["sections"] = sections

            # Calculate word count
            text_content = soup.get_text()
            structure["word_count"] = len(text_content.split())

        except Exception as e:
            logger.warning(f"Error extracting HTML structure: {e}")
            structure["error"] = str(e)

        return structure

    def extract_html_links(self, html_content: str) -> Dict[str, Any]:
        """
        Extract links from HTML content.

        Args:
            html_content: HTML content to analyze

        Returns:
            Dictionary containing link information
        """
        links_data: Dict[str, Any] = {
            "internal_links": [],
            "external_links": [],
            "media_links": [],
        }

        try:
            soup = BeautifulSoup(html_content, "html.parser")

            # Extract all links
            for link in soup.find_all("a", href=True):
                if isinstance(link, Tag):
                    href_attr = link.get("href")
                    if href_attr and isinstance(href_attr, str):
                        href = href_attr.strip()
                        text = link.get_text().strip()
                        title_attr = link.get("title", "")
                        title = str(title_attr) if title_attr else ""

                        if not href:
                            continue

                        link_info = {"url": href, "text": text, "title": title}

                        # Categorize links
                        if href.startswith(("http://", "https://", "//")):
                            # External link
                            parsed = urlparse(href)
                            link_info["domain"] = parsed.netloc
                            links_data["external_links"].append(link_info)
                        elif href.startswith("#"):
                            # Internal anchor
                            link_info["type"] = "anchor"
                            links_data["internal_links"].append(link_info)
                        else:
                            # Internal link (relative path)
                            link_info["type"] = "internal"
                            links_data["internal_links"].append(link_info)

            # Extract media links (images, videos, audio)
            media_selectors = [
                ("img", "src", "image"),
                ("video", "src", "video"),
                ("audio", "src", "audio"),
                ("source", "src", "media"),
                ("embed", "src", "embed"),
                ("object", "data", "object"),
            ]

            for tag, attr, media_type in media_selectors:
                for element in soup.find_all(tag):
                    if isinstance(element, Tag):
                        src = element.get(attr)
                        if src and isinstance(src, str):
                            alt_attr = element.get("alt", "")
                            title_attr = element.get("title", "")
                            media_info = {
                                "url": src.strip(),
                                "type": media_type,
                                "alt": str(alt_attr) if alt_attr else "",
                                "title": str(title_attr) if title_attr else "",
                            }
                            links_data["media_links"].append(media_info)

        except Exception as e:
            logger.warning(f"Error extracting HTML links: {e}")
            links_data["error"] = str(e)

        return links_data
