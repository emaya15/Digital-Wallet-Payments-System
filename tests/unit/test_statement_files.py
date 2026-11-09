import csv
from datetime import date

from app.utils.statement_files import statement_password, write_statement_csv, write_statement_pdf

HEADER = {
    "Wallet Number": "WLT123456789012",
    "Account Holder": "Asha Raman",
    "Statement Period": "2026-10",
}
ROWS = [
    {
        "date": "2026-10-02 10:00",
        "reference": "TXNAAAA1111BBBB22",
        "type": "Add Money",
        "description": "Wallet top up",
        "credit": "1000.00",
        "debit": "",
        "balance": "1000.00",
    },
    {
        "date": "2026-10-03 11:30",
        "reference": "TXNCCCC3333DDDD44",
        "type": "P2P Transfer",
        "description": "Rent share",
        "credit": "",
        "debit": "250.00",
        "balance": "750.00",
    },
]
SUMMARY = {
    "Opening Balance": "0.00",
    "Total Credits": "1000.00",
    "Total Debits": "250.00",
    "Closing Balance": "750.00",
}


def test_statement_password_uses_first_four_letters_and_birth_year():
    assert statement_password("Asha Raman", date(1998, 5, 17)) == "asha1998"
    assert statement_password("Jo", date(2001, 1, 1)) == "jo2001"
    assert statement_password("  A.B. Kumar", date(1990, 1, 1)) == "abku1990"


def test_csv_statement_contents(tmp_path):
    path = tmp_path / "s.csv"
    write_statement_csv(str(path), HEADER, ROWS, SUMMARY)
    with open(path, newline="", encoding="utf-8") as handle:
        content = list(csv.reader(handle))
    flat = [cell for row in content for cell in row]
    assert ["Wallet Number", "WLT123456789012"] in content
    assert ["Account Holder", "Asha Raman"] in content
    assert ["Date", "Reference", "Type", "Description", "Credit", "Debit", "Balance"] in content
    assert "TXNAAAA1111BBBB22" in flat and "TXNCCCC3333DDDD44" in flat
    assert ["Opening Balance", "0.00"] in content
    assert ["Closing Balance", "750.00"] in content


def test_pdf_statement_is_encrypted_and_not_readable_in_plain_text(tmp_path):
    path = tmp_path / "s.pdf"
    write_statement_pdf(str(path), "asha1998", HEADER, ROWS, SUMMARY)
    data = path.read_bytes()
    assert data.startswith(b"%PDF")
    assert b"/Encrypt" in data
    # Content streams are encrypted, so the plain wallet number must not appear.
    assert b"WLT123456789012" not in data


def test_pdf_statement_with_no_rows(tmp_path):
    path = tmp_path / "empty.pdf"
    write_statement_pdf(str(path), "asha1998", HEADER, [], SUMMARY)
    assert path.stat().st_size > 500
