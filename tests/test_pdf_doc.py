import io
import unittest
from unittest.mock import patch

from pdf_doc import MAX_PDF_PAGES, PdfPageLimitError, extract_text_from_pdf_bytes


class PdfLimitTests(unittest.TestCase):
    def test_rejects_pdf_over_page_limit(self):
        pages = [object()] * (MAX_PDF_PAGES + 1)
        reader = type("Reader", (), {"pages": pages})()

        with patch("pdf_doc.PdfReader", return_value=reader):
            with self.assertRaises(PdfPageLimitError):
                extract_text_from_pdf_bytes(b"pdf")

    def test_allows_pdf_at_page_limit(self):
        pages = [type("Page", (), {"extract_text": lambda self: "text"})()
                 for _ in range(MAX_PDF_PAGES)]
        reader = type("Reader", (), {"pages": pages})()

        with patch("pdf_doc.PdfReader", return_value=reader):
            text = extract_text_from_pdf_bytes(b"pdf")

        self.assertEqual(text, "\n\n".join(["text"] * MAX_PDF_PAGES))


if __name__ == "__main__":
    unittest.main()
