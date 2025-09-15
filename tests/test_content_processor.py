"""
Tests for content processor module.
"""

from openzim_mcp.content_processor import ContentProcessor


class TestContentProcessor:
    """Test ContentProcessor class."""

    def test_html_to_plain_text(
        self, content_processor: ContentProcessor, sample_html: str
    ):
        """Test HTML to plain text conversion."""
        result = content_processor.html_to_plain_text(sample_html)

        # Should contain main content
        assert "Main Title" in result
        assert "first paragraph" in result
        assert "bold text" in result

        # Should not contain unwanted elements
        assert "alert('test')" not in result
        assert "Edit section" not in result
        assert "Footer content" not in result

    def test_html_to_plain_text_empty(self, content_processor: ContentProcessor):
        """Test HTML to plain text with empty input."""
        result = content_processor.html_to_plain_text("")
        assert result == ""

    def test_html_to_plain_text_invalid_html(self, content_processor: ContentProcessor):
        """Test HTML to plain text with invalid HTML."""
        result = content_processor.html_to_plain_text("<invalid>test</invalid>")
        assert "test" in result

    def test_create_snippet_short_content(self, content_processor: ContentProcessor):
        """Test creating snippet from short content."""
        content = "This is a short piece of content."
        result = content_processor.create_snippet(content)
        assert result == content

    def test_create_snippet_long_content(self, content_processor: ContentProcessor):
        """Test creating snippet from long content."""
        content = "a" * 200  # Longer than snippet_length (100)
        result = content_processor.create_snippet(content)
        assert len(result) <= 103  # 100 + "..."
        assert result.endswith("...")

    def test_create_snippet_multiple_paragraphs(
        self, content_processor: ContentProcessor
    ):
        """Test creating snippet from multiple paragraphs."""
        content = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
        result = content_processor.create_snippet(content, max_paragraphs=2)
        assert "First paragraph" in result
        assert "Second paragraph" in result
        assert "Third paragraph" not in result

    def test_truncate_content_short(self, content_processor: ContentProcessor):
        """Test truncating short content."""
        content = "Short content"
        result = content_processor.truncate_content(content, 100)
        assert result == content

    def test_truncate_content_long(self, content_processor: ContentProcessor):
        """Test truncating long content."""
        content = "a" * 200
        result = content_processor.truncate_content(content, 100)
        assert len(result) > 100  # Includes truncation message
        assert "Content truncated" in result
        assert "200 characters" in result

    def test_process_mime_content_html(self, content_processor: ContentProcessor):
        """Test processing HTML MIME content."""
        html_bytes = b"<html><body><h1>Test</h1></body></html>"
        result = content_processor.process_mime_content(html_bytes, "text/html")
        assert "Test" in result
        assert "<html>" not in result

    def test_process_mime_content_plain_text(self, content_processor: ContentProcessor):
        """Test processing plain text MIME content."""
        text_bytes = b"Plain text content"
        result = content_processor.process_mime_content(text_bytes, "text/plain")
        assert result == "Plain text content"

    def test_process_mime_content_image(self, content_processor: ContentProcessor):
        """Test processing image MIME content."""
        image_bytes = b"fake image data"
        result = content_processor.process_mime_content(image_bytes, "image/png")
        assert "Image content - Cannot display directly" in result

    def test_process_mime_content_unsupported(
        self, content_processor: ContentProcessor
    ):
        """Test processing unsupported MIME content."""
        data_bytes = b"binary data"
        result = content_processor.process_mime_content(
            data_bytes, "application/octet-stream"
        )
        assert "Unsupported content type" in result

    def test_html_to_plain_text_exception_handling(
        self, content_processor: ContentProcessor
    ):
        """Test html_to_plain_text exception handling."""
        # Test with malformed HTML that might cause parsing issues
        malformed_html = "<html><body><div><p>Unclosed tags"

        # This should not raise an exception, but handle it gracefully
        result = content_processor.html_to_plain_text(malformed_html)
        assert "Unclosed tags" in result

    def test_process_mime_content_exception_handling(
        self, content_processor: ContentProcessor
    ):
        """Test process_mime_content exception handling."""
        from unittest.mock import patch

        # Mock the html_to_plain_text method to raise an exception
        with patch.object(
            content_processor, "html_to_plain_text", side_effect=Exception("Test error")
        ):
            result = content_processor.process_mime_content(
                b"<html>test</html>", "text/html"
            )
            assert "Error processing content" in result

    def test_create_snippet_exception_handling(
        self, content_processor: ContentProcessor
    ):
        """Test create_snippet exception handling."""
        from unittest.mock import patch

        # Mock re.sub to raise an exception
        with patch(
            "openzim_mcp.content_processor.re.sub", side_effect=Exception("Test error")
        ):
            result = content_processor.create_snippet("test content")
            # Should return original content when exception occurs (line 92)
            assert result == "test content"

    def test_extract_html_structure_exception_handling(
        self, content_processor: ContentProcessor
    ):
        """Test extract_html_structure exception handling."""
        from unittest.mock import patch

        # Test with content that causes an exception during processing
        with patch(
            "openzim_mcp.content_processor.BeautifulSoup",
            side_effect=Exception("Parse error"),
        ):
            result = content_processor.extract_html_structure(
                "<html><body>test</body></html>"
            )
            # Should return basic structure when exception occurs
            assert "headings" in result
            assert "sections" in result

    def test_extract_html_links_exception_handling(
        self, content_processor: ContentProcessor
    ):
        """Test extract_html_links exception handling."""
        from unittest.mock import patch

        # Test with content that causes an exception during link extraction
        with patch(
            "openzim_mcp.content_processor.BeautifulSoup",
            side_effect=Exception("Parse error"),
        ):
            result = content_processor.extract_html_links(
                "<html><body><a href='test'>link</a></body></html>"
            )
            # Should return empty structure when exception occurs
            assert "internal_links" in result
            assert "external_links" in result

    def test_extract_html_structure(self, content_processor: ContentProcessor):
        """Test HTML structure extraction."""
        html_content = """
        <html>
        <head>
            <title>Test Article</title>
            <meta name="description" content="Test description">
        </head>
        <body>
            <h1 id="intro">Introduction</h1>
            <p>This is the introduction paragraph.</p>
            <h2>Section 1</h2>
            <p>Content of section 1 with multiple words.</p>
            <h3>Subsection 1.1</h3>
            <p>Subsection content here.</p>
            <h2>Section 2</h2>
            <p>Content of section 2.</p>
        </body>
        </html>
        """

        structure = content_processor.extract_html_structure(html_content)

        # Check basic structure
        assert "headings" in structure
        assert "sections" in structure
        assert "metadata" in structure
        assert "word_count" in structure

        # Check headings
        headings = structure["headings"]
        assert len(headings) == 4
        assert headings[0]["level"] == 1
        assert headings[0]["text"] == "Introduction"
        assert headings[0]["id"] == "intro"
        assert headings[1]["level"] == 2
        assert headings[1]["text"] == "Section 1"

        # Check sections
        sections = structure["sections"]
        assert len(sections) > 0
        assert any("Introduction" in section["title"] for section in sections)

        # Check metadata
        metadata = structure["metadata"]
        assert "description" in metadata
        assert metadata["description"] == "Test description"

        # Check word count
        assert structure["word_count"] > 0

    def test_extract_html_structure_empty(self, content_processor: ContentProcessor):
        """Test HTML structure extraction with empty content."""
        structure = content_processor.extract_html_structure("")

        assert "headings" in structure
        assert "sections" in structure
        assert "metadata" in structure
        assert "word_count" in structure
        assert structure["word_count"] == 0

    def test_extract_html_links(self, content_processor: ContentProcessor):
        """Test HTML link extraction."""
        html_content = """
        <html>
        <body>
            <p>Internal link: <a href="C/Other_Article" title="Other Article">
                Link to other article</a></p>
            <p>External link: <a href="https://example.com">Example website</a></p>
            <p>Anchor link: <a href="#section1">Go to section 1</a></p>
            <img src="I/image.jpg" alt="Test image" title="Image title">
            <video src="M/video.mp4">Video content</video>
            <audio src="M/audio.mp3">Audio content</audio>
        </body>
        </html>
        """

        links_data = content_processor.extract_html_links(html_content)

        # Check basic structure
        assert "internal_links" in links_data
        assert "external_links" in links_data
        assert "media_links" in links_data

        # Check internal links
        internal_links = links_data["internal_links"]
        assert (
            len(internal_links) >= 2
        )  # Should have the internal article link and anchor link

        # Find the internal article link
        article_link = next(
            (link for link in internal_links if "Other_Article" in link["url"]), None
        )
        assert article_link is not None
        assert article_link["text"] == "Link to other article"
        assert article_link["title"] == "Other Article"
        assert article_link["type"] == "internal"

        # Find the anchor link
        anchor_link = next(
            (link for link in internal_links if link["url"].startswith("#")), None
        )
        assert anchor_link is not None
        assert anchor_link["type"] == "anchor"

        # Check external links
        external_links = links_data["external_links"]
        assert len(external_links) >= 1
        example_link = next(
            (link for link in external_links if "example.com" in link["url"]), None
        )
        assert example_link is not None
        assert example_link["domain"] == "example.com"

        # Check media links
        media_links = links_data["media_links"]
        assert len(media_links) >= 3  # image, video, audio

        # Check for image
        image_link = next(
            (link for link in media_links if link["type"] == "image"), None
        )
        assert image_link is not None
        assert "image.jpg" in image_link["url"]
        assert image_link["alt"] == "Test image"
        assert image_link["title"] == "Image title"

    def test_extract_html_links_empty(self, content_processor: ContentProcessor):
        """Test HTML link extraction with empty content."""
        links_data = content_processor.extract_html_links("")

        assert "internal_links" in links_data
        assert "external_links" in links_data
        assert "media_links" in links_data
        assert len(links_data["internal_links"]) == 0
        assert len(links_data["external_links"]) == 0
        assert len(links_data["media_links"]) == 0
