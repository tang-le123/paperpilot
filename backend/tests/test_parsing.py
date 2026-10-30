from pathlib import Path

from app.parsing import parse_markdown


def test_markdown_sections_and_references(tmp_path: Path):
    path = tmp_path / "paper.md"
    path.write_text(
        """# Test Paper

## Abstract

This paper studies retrieval.

## 2 Method

We use BM25 and dense retrieval.

## 3 Results

The method works.

## References

[1] A reference that should not be used for QA.
""",
        encoding="utf-8",
    )

    parsed = parse_markdown(1, path)

    assert parsed.title == "Test Paper"
    assert parsed.page_count == 1
    assert any("Method" in chunk["section"] for chunk in parsed.chunks)
    assert any(chunk["is_reference"] for chunk in parsed.chunks)
    assert all(chunk["page"] == 1 for chunk in parsed.chunks)
