"""Lists of people to invite: reading a file (CSV, XLSX, PDF, plain text), finding people in it without a language
model, and hiding phone numbers from the assistant.

The manager either pastes a list or sends a file ("Zaproś kilka osób" in "Pracownicy"), or gives the file to the
assistant in the chat. This module only reads; `invitations.check_people` / `invite_people` decide who can be invited.
Nothing is stored here: the file is read in memory and dropped.
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
import zipfile
from dataclasses import dataclass, field
from xml.etree import ElementTree

from ninja.errors import HttpError

MAX_FILE_BYTES = 2 * 1024 * 1024
# Characters of text kept from one file or paste, and lines (rows) read from it.
MAX_TEXT = 40_000
MAX_LINES = 400
MAX_PDF_PAGES = 30
# Bytes of one XML part of an .xlsx read after unpacking (a small file can unpack to gigabytes).
MAX_XLSX_PART = 20 * 1024 * 1024

UNREADABLE = "Nie umiem przeczytać tego pliku. Wgraj CSV, XLSX albo PDF albo wklej listę."
TOO_BIG = "Plik jest za duży. Najwyżej 2 MB: podziel listę na mniejsze części."
OLD_EXCEL = "To stary plik Excela (.xls). Zapisz go jako .xlsx albo CSV i wgraj jeszcze raz."
SCANNED_PDF = "W tym PDF-ie nie ma tekstu, pewnie to skan. Wgraj CSV albo XLSX albo wklej listę."
LOCKED_PDF = "Ten PDF jest zabezpieczony hasłem. Zdejmij hasło albo wgraj CSV."

# --------------------------------------------------------------------------------------------- reading a file


def file_lines(name: str, data: bytes) -> list[list[str]]:
    """The file's rows as lists of cells (one cell when the line has no column separator). Raises HttpError(400)."""
    if len(data) > MAX_FILE_BYTES:
        raise HttpError(400, TOO_BIG)
    suffix = name.lower().rsplit(".", 1)[-1] if "." in name else ""
    if data.startswith(b"%PDF") or suffix == "pdf":
        return text_lines(_pdf_text(data))
    if data.startswith(b"PK\x03\x04"):
        if suffix in ("xlsx", "xlsm", "") or not suffix:
            return _xlsx_rows(data)
        raise HttpError(400, UNREADABLE)
    if suffix in ("xls",) or data.startswith(b"\xd0\xcf\x11\xe0"):
        raise HttpError(400, OLD_EXCEL)
    if suffix not in ("csv", "txt", "tsv", ""):
        raise HttpError(400, UNREADABLE)
    if b"\x00" in data[:4096]:
        raise HttpError(400, UNREADABLE)
    return text_lines(decode(data))


def decode(data: bytes) -> str:
    """UTF-8 (with or without BOM), else Windows-1250: Polish Excel saves CSV that way."""
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1250", errors="replace")


SEPARATORS = ("\t", ";", "|", ",")


def text_lines(text: str) -> list[list[str]]:
    """Rows of a pasted list or a text file. Columns are split by the separator most lines share (tab, semicolon,
    vertical bar or comma); a list without one gives one cell per line."""
    lines = [line for line in text[:MAX_TEXT].splitlines() if line.strip()][:MAX_LINES]
    if not lines:
        return []
    sample = lines[:30]
    separator = next((sep for sep in SEPARATORS if sum(sep in line for line in sample) * 2 >= len(sample)), None)
    if separator is None:
        return [[line.strip()] for line in lines]
    rows = []
    for line in lines:
        try:
            cells = next(csv.reader([line], delimiter=separator))
        except csv.Error:
            cells = line.split(separator)
        rows.append([cell.strip() for cell in cells])
    return rows


def _pdf_text(data: bytes) -> str:
    from pypdf import PdfReader
    from pypdf.errors import PyPdfError

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise HttpError(400, LOCKED_PDF)
        parts = []
        for page in reader.pages[:MAX_PDF_PAGES]:
            parts.append(page.extract_text() or "")
            if sum(map(len, parts)) > MAX_TEXT:
                break
    except HttpError:
        raise
    except (PyPdfError, ValueError, KeyError, TypeError, OSError) as exc:
        raise HttpError(400, "Nie udało się przeczytać tego PDF-a. Wgraj CSV albo XLSX albo wklej listę.") from exc
    text = "\n".join(parts)
    if not text.strip():
        raise HttpError(400, SCANNED_PDF)
    return text


def _xml(book: zipfile.ZipFile, part: str) -> ElementTree.Element | None:
    try:
        with book.open(part) as stream:
            raw = stream.read(MAX_XLSX_PART + 1)
    except KeyError:
        return None
    if len(raw) > MAX_XLSX_PART:
        raise HttpError(400, TOO_BIG)
    # Spreadsheet parts never declare a DTD; refusing one rules out entity tricks in a crafted file.
    if b"<!DOCTYPE" in raw or b"<!ENTITY" in raw:
        raise HttpError(400, UNREADABLE)
    return ElementTree.fromstring(raw)  # noqa: S314  # no DTD (checked above), so no entity expansion


def _column(ref: str) -> int:
    """ "C7" → 2."""
    number = 0
    for char in ref:
        if not char.isalpha():
            break
        number = number * 26 + (ord(char.upper()) - 64)
    return max(number - 1, 0)


def _xlsx_rows(data: bytes) -> list[list[str]]:
    """The first sheet of an .xlsx file, read with the standard library (cells as text, no formulas)."""
    try:
        book = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise HttpError(400, UNREADABLE) from exc
    with book:
        names = book.namelist()
        sheets = sorted(
            (n for n in names if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n)),
            key=lambda n: int(re.sub(r"\D", "", n.rsplit("/", 1)[-1]) or 0),
        )
        if not sheets:
            raise HttpError(400, UNREADABLE)
        shared: list[str] = []
        strings = _xml(book, "xl/sharedStrings.xml")
        if strings is not None:
            shared = ["".join(t.text or "" for t in item.iterfind(".//{*}t")) for item in strings.iterfind(".//{*}si")]
        sheet = _xml(book, sheets[0])
    if sheet is None:
        raise HttpError(400, UNREADABLE)
    rows: list[list[str]] = []
    for row in sheet.iterfind(".//{*}row"):
        cells: dict[int, str] = {}
        for position, cell in enumerate(row.iterfind("{*}c")):
            kind = cell.get("t", "n")
            if kind == "inlineStr":
                value = "".join(t.text or "" for t in cell.iterfind(".//{*}t"))
            else:
                found = cell.find("{*}v")
                value = found.text or "" if found is not None else ""
                if kind == "s" and value.isdigit():
                    index = int(value)
                    value = shared[index] if index < len(shared) else ""
                elif kind == "n" and re.fullmatch(r"\d+\.0+", value):
                    value = value.split(".")[0]  # 512345678.0 → 512345678
            column = _column(cell.get("r", "")) if cell.get("r") else position
            if value.strip() and column < 50:
                cells[column] = value.strip()
        if cells:
            rows.append([cells.get(i, "") for i in range(max(cells) + 1)])
        if len(rows) >= MAX_LINES:
            break
    return rows


def as_text(rows: list[list[str]]) -> str:
    """Rows as plain lines for the assistant: cells joined with " | "."""
    return "\n".join(" | ".join(cell for cell in row) for row in rows)[:MAX_TEXT]


# ------------------------------------------------------------------------------------------- phone numbers

# 7 to 15 digits, optionally with +, 00, spaces (also non-breaking), dashes, dots or brackets between them, on one line.
PHONE_LIKE = re.compile(r"(?<![\w+])(?:\+|00)?\(?\d(?:[ \t\u00a0\-./()]{0,2}\d){6,14}(?![\w])")
DATE_LIKE = re.compile(r"\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|\d{4}[./-]\d{1,2}[./-]\d{1,2}")


def phone_spans(text: str) -> list[re.Match]:
    return [m for m in PHONE_LIKE.finditer(text) if not DATE_LIKE.fullmatch(m.group().strip())]


def is_phone(raw: str) -> bool:
    from django.core.exceptions import ValidationError

    from apps.accounts.models import normalize_phone

    try:
        normalize_phone(raw)
    except ValidationError:
        return False
    return True


def without_numbers(text: str) -> str:
    """Text with every phone-like number replaced by "[numer]" (earlier messages the assistant reads again)."""
    return PHONE_LIKE.sub(lambda m: m.group() if DATE_LIKE.fullmatch(m.group().strip()) else "[numer]", text)


class PhoneMask:
    """Replaces every phone-like number with a mark ([TEL1], [TEL2]…) before text goes to the assistant: the model
    never sees a number, and the numbers in its answer can only be ones from the manager's own text."""

    def __init__(self) -> None:
        self.numbers: dict[str, str] = {}

    def hide(self, text: str) -> str:
        def mark(match: re.Match) -> str:
            raw = match.group()
            if DATE_LIKE.fullmatch(raw.strip()):
                return raw
            token = next((t for t, number in self.numbers.items() if number == raw), None)
            if token is None:
                token = f"TEL{len(self.numbers) + 1}"
                self.numbers[token] = raw
            return f"[{token}]"

        return PHONE_LIKE.sub(mark, text)

    def number(self, mark: str) -> str | None:
        """The number behind "[TEL3]" (also "TEL3", "tel 3"); None for anything else."""
        token = re.sub(r"[\s\[\]]", "", mark or "").upper()
        return self.numbers.get(token)


# ------------------------------------------------------------------------------- finding people without a model


@dataclass
class Listed:
    """One person found in a list. Ids are of the given positions and locations; `phone` is as written."""

    first_name: str = ""
    last_name: str = ""
    phone: str = ""
    position_ids: list = field(default_factory=list)
    location_id: object = None
    # Positions named in the list that the location does not have.
    unknown_positions: list[str] = field(default_factory=list)


def fold(text: str) -> str:
    """Lower case without Polish letters, for comparing names ("Kasa" = "kasa", "Wieliczka" = "wieliczka")."""
    text = text.replace("ł", "l").replace("Ł", "L")
    return "".join(c for c in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(c)).strip()


HEADERS = {
    "full": ("imie i nazwisko", "nazwisko i imie", "pracownik", "osoba", "imiona i nazwisko", "name", "full name"),
    "first": ("imie", "imiona", "first name"),
    "last": ("nazwisko", "last name", "surname"),
    "phone": ("telefon", "tel", "tel.", "nr tel", "nr tel.", "nr telefonu", "numer", "numer telefonu", "komorka",
              "phone", "mobile", "kontakt"),
    "positions": ("stanowisko", "stanowiska", "funkcja", "position", "stanowisko pracy"),
    "location": ("lokal", "sklep", "punkt", "placowka", "oddzial", "location", "lokalizacja", "piekarnia"),
}  # fmt: skip


def _header(row: list[str]) -> dict[str, int] | None:
    """Column numbers by meaning, when the row is a header ("Imię;Nazwisko;Telefon…")."""
    if phone_spans(" ".join(row)):
        return None
    columns: dict[str, int] = {}
    for index, cell in enumerate(row):
        name = fold(cell).rstrip(":")
        for meaning, words in HEADERS.items():
            if name in words and meaning not in columns:
                columns[meaning] = index
                if meaning == "full" and name.startswith("nazwisko"):
                    columns["last_first"] = index
                break
    return columns if len(columns) >= 2 or "phone" in columns else None


def _find_names(text: str, known: dict[str, object]) -> tuple[list[object], str]:
    """Known names (positions or locations) in `text`, longest first, and the text without them."""
    found = []
    for name in sorted(known, key=len, reverse=True):
        pattern = re.compile(rf"(?<!\w){re.escape(name)}(?!\w)", re.IGNORECASE)
        if pattern.search(text):
            found.append(known[name])
            text = pattern.sub(" ", text)
    return found, text


def _with_short_names(known: dict[str, object]) -> dict[str, object]:
    """Names plus the words that only one of them has ("Piekarnia Wieliczka" is also "Wieliczka" when no other
    location has that word), so a row may name a location the way people say it."""
    words: dict[str, set] = {}
    for name, value in known.items():
        for word in NAME_WORD.findall(name):
            if len(word) >= 4:
                words.setdefault(word, set()).add(value)
    short = {word: values.pop() for word, values in words.items() if len(values) == 1}
    return {**short, **known}


def _split_list(cell: str) -> list[str]:
    return [part.strip() for part in re.split(r"[,/;+&\n]| i | oraz ", cell) if part.strip()]


EMAIL = re.compile(r"\S+@\S+")
ROW_NUMBER = re.compile(r"^\s*\d{1,3}\s*[.)]?\s+")
NAME_WORD = re.compile(r"[^\W\d_][^\W\d_'’\-.]*(?:[-'’][^\W\d_]+)*")


def _name_parts(text: str, last_first: bool = False) -> tuple[str, str]:
    words = NAME_WORD.findall(EMAIL.sub(" ", ROW_NUMBER.sub(" ", text)))
    if not words:
        return "", ""
    if last_first and len(words) > 1:
        return words[-1][:80], " ".join(words[:-1])[:120]
    return words[0][:80], " ".join(words[1:])[:120]


def _match(cell: str, known: dict[str, object]) -> object | None:
    """A known name equal to the cell, or the only one containing it ("Wieliczka" → "Piekarnia Wieliczka")."""
    key = fold(cell)
    if not key:
        return None
    exact = [value for name, value in known.items() if fold(name) == key]
    if exact:
        return exact[0]
    partial = {value for name, value in known.items() if key in fold(name) or fold(name) in key}
    return partial.pop() if len(partial) == 1 else None


def find_people(
    rows: list[list[str]], positions: dict[str, object], locations: dict[str, object] | None = None
) -> tuple[list[Listed], int]:
    """People in the rows, and how many non-empty rows were not a person (titles, headers, notes).

    `positions` and `locations` map names to ids. With a header row, its columns say what is where, and a person
    without a number is kept (the manager types it in). Without one, a row is a person only when it has a phone
    number: the rest of the row gives positions, the location and the name (first word = first name).
    """
    locations = locations or {}
    people: list[Listed] = []
    skipped = 0
    header: dict[str, int] | None = None
    for row in rows:
        if not any(cell.strip() for cell in row):
            continue
        if header is None and not people:
            found = _header(row)
            if found is not None:
                header = found
                continue
        person = _from_columns(row, header, positions, locations) if header else _from_text(row, positions, locations)
        if person is None:
            skipped += 1
        else:
            people.append(person)
    return people, skipped


def _cell(row: list[str], header: dict[str, int], meaning: str) -> str:
    index = header.get(meaning)
    return row[index].strip() if index is not None and index < len(row) else ""


def _from_columns(row, header, positions, locations) -> Listed | None:
    person = Listed()
    phone = _cell(row, header, "phone")
    spans = phone_spans(phone)
    person.phone = spans[0].group().strip() if spans else phone
    if "full" in header:
        person.first_name, person.last_name = _name_parts(_cell(row, header, "full"), "last_first" in header)
    else:
        person.first_name = " ".join(NAME_WORD.findall(_cell(row, header, "first")))[:80]
        person.last_name = " ".join(NAME_WORD.findall(_cell(row, header, "last")))[:120]
    for name in _split_list(_cell(row, header, "positions")):
        found = _match(name, positions)
        if found is None:
            person.unknown_positions.append(name[:100])
        elif found not in person.position_ids:
            person.position_ids.append(found)
    place = _cell(row, header, "location")
    if place:
        person.location_id = _match(place, locations)
    if not (person.phone or person.first_name or person.last_name):
        return None
    return person


def _from_text(row, positions, locations) -> Listed | None:
    text = " | ".join(cell for cell in row if cell.strip())
    spans = phone_spans(text)
    if not spans:
        return None
    # Another long number (PESEL, an account) may come first: take the first one that is a phone number.
    person = Listed(phone=next((m.group().strip() for m in spans if is_phone(m.group())), spans[0].group().strip()))
    for match in reversed(spans):
        text = text[: match.start()] + " " + text[match.end() :]
    found, text = _find_names(text, _with_short_names(locations))
    person.location_id = found[0] if found else None
    person.position_ids, text = _find_names(text, positions)
    person.first_name, person.last_name = _name_parts(text)
    return person
