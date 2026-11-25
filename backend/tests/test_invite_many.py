"""Inviting many people at once: a pasted list or a file (CSV, XLSX, PDF) is read without the assistant, shown as
a preview, and only the people the manager sends are invited (docs/plan.md, section 40)."""

import io
import zipfile

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.accounts.models import WRONG_PHONE
from apps.staffing.models import EmployeeProfile, Position
from apps.tenancy import people_list
from apps.tenancy.models import Invitation, InvitationStatus, Location, Membership, Role

pytestmark = pytest.mark.django_db


@pytest.fixture
def a(make_company, subscribe):
    company = make_company("A")
    subscribe(company["company"])
    return company


def make_pdf(lines: list[str]) -> bytes:
    """A one-page PDF with these lines of text (Helvetica, Latin letters only)."""
    content = "BT /F1 11 Tf 50 780 Td 14 TL " + " ".join(f"({line}) Tj T*" for line in lines) + " ET"
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(out.tell())
        out.write(f"{number} 0 obj\n{body}\nendobj\n".encode("latin-1"))
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        out.write(f"{offset:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


def make_xlsx(rows: list[list[object]]) -> bytes:
    """A minimal .xlsx: text in shared strings, numbers as numbers (like a phone typed into Excel)."""
    strings: list[str] = []
    cells_xml = []
    for r, row in enumerate(rows, 1):
        cells = []
        for c, value in enumerate(row):
            ref = f"{chr(65 + c)}{r}"
            if isinstance(value, int | float):
                cells.append(f'<c r="{ref}"><v>{value}</v></c>')
            else:
                strings.append(str(value))
                cells.append(f'<c r="{ref}" t="s"><v>{len(strings) - 1}</v></c>')
        cells_xml.append(f'<row r="{r}">{"".join(cells)}</row>')
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    sheet = (
        f'<?xml version="1.0" encoding="UTF-8"?><worksheet {ns}><sheetData>{"".join(cells_xml)}</sheetData></worksheet>'
    )
    shared = (
        f'<?xml version="1.0" encoding="UTF-8"?><sst {ns}>'
        + "".join(f"<si><t>{s}</t></si>" for s in strings)
        + "</sst>"
    )
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as book:
        book.writestr("[Content_Types].xml", "<Types/>")
        book.writestr("xl/workbook.xml", f"<workbook {ns}/>")
        book.writestr("xl/sharedStrings.xml", shared)
        book.writestr("xl/worksheets/sheet1.xml", sheet)
    return out.getvalue()


def read(api, location, *, text=None, file=None, region=None):
    data = {"text": text} if text is not None else {"file": file}
    if region:
        data["region"] = region
    return api.client.post(f"/api/locations/{location.id}/invitations/read", data)


def invite_many(api, location, people, region=None):
    body = {"people": people, **({"region": region} if region else {})}
    return api.post(f"/api/locations/{location.id}/invitations/many", body)


# --- reading a list -------------------------------------------------------------------------------------


def test_pasted_list_gives_people_with_positions_and_problems(api, a):
    Position.objects.create(location=a["location"], name="Kasa")
    api.login(a["manager"])

    response = read(
        api,
        a["location"],
        text=(
            "Lista na grudzień\n"
            "1. Anna Kowalska 512 345 678 Sprzedawca\n"
            "Jan Nowak, +48 600-100-200, kasa\n"
            f"Pracownik Stały {a['worker'].phone_e164}\n"
            "Ewa Lis 12345\n"
        ),
    )

    assert response.status_code == 200, response.json()
    body = response.json()
    people = body["people"]
    assert [(p["first_name"], p["last_name"]) for p in people] == [
        ("Anna", "Kowalska"),
        ("Jan", "Nowak"),
        ("Pracownik", "Stały"),
    ]
    assert people[0]["phone"] == "+48512345678"
    assert people[0]["position_ids"] == [str(a["position"].id)]
    assert people[0]["problem"] is None
    kasa = Position.objects.get(name="Kasa")
    assert people[1]["position_ids"] == [str(kasa.id)] and people[1]["problem"] is None
    assert people[2]["problem"] == "Ta osoba już pracuje w tym lokalu."
    # The title and the line with a number too short to be a phone are not people.
    assert body["skipped_lines"] == 2
    assert Invitation.objects.count() == 0


def test_numbers_from_other_countries_are_read_with_their_code(api, a):
    api.login(a["manager"])

    response = read(
        api,
        a["location"],
        text="Olena Shevchenko +380 50 123 45 67\nTaras Bondar 00380 67 123 4567\nIryna Koval 050 123 4567\n",
    )

    people = response.json()["people"]
    assert [(p["first_name"], p["phone"]) for p in people] == [
        ("Olena", "+380501234567"),
        ("Taras", "+380671234567"),
        ("Iryna", "050 123 4567"),
    ]
    assert people[0]["problem"] is None and people[1]["problem"] is None
    # Without its code the number is not one: the manager adds +380 in the preview.
    assert people[2]["problem"] == WRONG_PHONE


def test_a_list_from_another_country_reads_numbers_without_a_code_from_there(api, a):
    api.login(a["manager"])
    # Excel drops the leading 0, so 050 123 4567 often arrives as 501234567: Polish-looking, but Ukrainian here.
    text = "Olena Shevchenko 501234567\nTaras Bondar 067 123 4567\nJan Nowak +48 600 100 200\n"

    people = read(api, a["location"], text=text, region="UA").json()["people"]

    assert [(p["first_name"], p["phone"], p["problem"]) for p in people] == [
        ("Olena", "+380501234567", None),
        ("Taras", "+380671234567", None),
        ("Jan", "+48600100200", None),
    ]
    # A number corrected in the preview is read the same way when the list is sent.
    sent = invite_many(api, a["location"], [{"phone": "50 765 4321", "first_name": "Iryna"}], region="UA").json()
    assert [i["phone"] for i in sent["invited"]] == ["+380507654321"]

    assert read(api, a["location"], text=text, region="XX").status_code == 400


def test_csv_with_header_keeps_people_without_a_number(api, a):
    api.login(a["manager"])
    csv = "Nazwisko;Imię;Telefon;Stanowisko\nKowalska;Anna;512345678;Sprzedawca\nNowak;Jan;;Piekarz\n"
    file = SimpleUploadedFile("lista.csv", csv.encode("cp1250"), content_type="text/csv")

    people = read(api, a["location"], file=file).json()["people"]

    assert [(p["first_name"], p["last_name"], p["phone"]) for p in people] == [
        ("Anna", "Kowalska", "+48512345678"),
        ("Jan", "Nowak", ""),
    ]
    assert people[1]["problem"] == "Brak numeru telefonu."
    assert people[1]["unknown_positions"] == ["Piekarz"]


def test_xlsx_and_pdf_files_are_read(api, a):
    api.login(a["manager"])
    sheet = make_xlsx([["Imię i nazwisko", "Telefon"], ["Anna Kowalska", 512345678], ["Jan Nowak", "600 100 200"]])
    people = read(api, a["location"], file=SimpleUploadedFile("lista.xlsx", sheet)).json()["people"]
    assert [(p["first_name"], p["phone"]) for p in people] == [("Anna", "+48512345678"), ("Jan", "+48600100200")]

    pdf = make_pdf(["Pracownicy", "Anna Kowalska 512 345 678 Sprzedawca", "Jan Nowak 600-100-200"])
    people = read(api, a["location"], file=SimpleUploadedFile("lista.pdf", pdf)).json()["people"]
    assert [(p["first_name"], p["last_name"], p["phone"]) for p in people] == [
        ("Anna", "Kowalska", "+48512345678"),
        ("Jan", "Nowak", "+48600100200"),
    ]
    assert people[0]["position_ids"] == [str(a["position"].id)]


def test_unreadable_files_get_a_plain_answer(api, a):
    api.login(a["manager"])
    cases = [
        (SimpleUploadedFile("lista.xls", b"\xd0\xcf\x11\xe0rest"), "stary plik Excela"),
        (SimpleUploadedFile("lista.docx", b"PK\x03\x04garbage"), "Nie umiem przeczytać"),
        (SimpleUploadedFile("lista.csv", b"tylko tytul\nbez numerow\n"), "Nie znalazłem tu nikogo"),
        (SimpleUploadedFile("lista.pdf", b"%PDF-1.4 broken"), "PDF"),
        (SimpleUploadedFile("duzy.csv", b"a" * (people_list.MAX_FILE_BYTES + 1)), "za duży"),
    ]
    for file, words in cases:
        response = read(api, a["location"], file=file)
        assert response.status_code == 400, file.name
        assert words in response.json()["detail"], file.name


def test_xlsx_with_a_dtd_is_refused():
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as book:
        book.writestr("xl/worksheets/sheet1.xml", '<!DOCTYPE x [<!ENTITY a "aaaa">]><worksheet>&a;</worksheet>')
    with pytest.raises(Exception, match="Nie umiem"):
        people_list.file_lines("x.xlsx", out.getvalue())


def test_another_managed_location_named_in_the_row(api, a):
    other = Location.objects.create(company=a["company"], name="Piekarnia Wieliczka")
    api.login(a["manager"])

    people = read(api, a["location"], text="Anna Kowalska 512 345 678 Wieliczka").json()["people"]

    assert people[0]["location_id"] == str(other.id)
    assert (people[0]["first_name"], people[0]["last_name"]) == ("Anna", "Kowalska")


# --- inviting ---------------------------------------------------------------------------------------------


def test_invite_many_invites_the_ready_ones_and_returns_the_rest(api, a):
    api.login(a["manager"])

    response = invite_many(
        api,
        a["location"],
        [
            {
                "phone": "512 345 678",
                "first_name": "Anna",
                "last_name": "Kowalska",
                "position_ids": [str(a["position"].id)],
            },
            {"phone": "600100200", "first_name": "Jan"},
            {"phone": "512345678", "first_name": "Anna again"},
            {"phone": "123", "first_name": "Zły numer"},
            {"phone": a["worker"].phone_e164},
        ],
    )

    assert response.status_code == 200, response.json()
    body = response.json()
    assert [i["phone"] for i in body["invited"]] == ["+48512345678", "+48600100200"]
    assert body["invited"][0]["position_ids"] == [str(a["position"].id)]
    assert [(s["first_name"], s["problem"]) for s in body["skipped"]] == [
        ("Anna again", "Ten numer jest już wyżej na liście."),
        ("Zły numer", WRONG_PHONE),
        ("", "Ta osoba już pracuje w tym lokalu."),
    ]
    assert Invitation.objects.filter(status=InvitationStatus.PENDING).count() == 2

    # Sending the same list again invites nobody twice.
    again = invite_many(api, a["location"], [{"phone": "512 345 678"}]).json()
    assert again["invited"] == []
    assert again["skipped"][0]["problem"] == "Ten numer ma już oczekujące zaproszenie do tego lokalu."


def test_positions_of_the_invitation_are_set_on_acceptance(api, a):
    api.login(a["manager"])
    invite_many(api, a["location"], [{"phone": "512345678", "position_ids": [str(a["position"].id)]}])
    invitation = Invitation.objects.get()

    from apps.accounts.models import User

    person = User.objects.create_user("+48512345678")
    api.login(person)
    assert api.post(f"/api/invitations/{invitation.id}/accept").status_code == 200

    profile = EmployeeProfile.objects.get(membership__user=person)
    assert list(profile.positions.all()) == [a["position"]]


def test_positions_of_another_location_are_dropped(api, a, make_company):
    other_company = make_company("B")
    api.login(a["manager"])

    body = invite_many(
        api, a["location"], [{"phone": "512345678", "position_ids": [str(other_company["position"].id)]}]
    )

    assert body.json()["invited"][0]["position_ids"] == []


def test_only_managed_locations_and_only_managers(api, a, make_company):
    other = Location.objects.create(company=a["company"], name="Drugi lokal")
    stranger = make_company("B")
    manager_user = a["manager"].__class__.objects.create_user("+48602300499")
    membership = Membership.objects.create(company=a["company"], user=manager_user, role=Role.MANAGER)
    membership.locations.add(a["location"])
    api.login(manager_user)

    body = invite_many(
        api,
        a["location"],
        [
            {"phone": "512345678", "location_id": str(other.id)},
            {"phone": "600100200", "location_id": str(stranger["location"].id)},
        ],
    ).json()

    assert body["invited"] == []
    assert {s["problem"] for s in body["skipped"]} == {"Nie zarządzasz tym lokalem."}
    # An employee cannot read or invite; another company's location is not found.
    api.login(a["worker"])
    assert read(api, a["location"], text="Anna 512345678").status_code == 403
    assert invite_many(api, a["location"], [{"phone": "512345678"}]).status_code == 403
    api.login(stranger["manager"])
    assert read(api, a["location"], text="Anna 512345678").status_code == 404
    assert invite_many(api, a["location"], [{"phone": "512345678"}]).status_code == 404


def test_read_only_company_cannot_invite_many(api, make_company):
    company = make_company("Bez dostępu")
    api.login(company["manager"])
    assert invite_many(api, company["location"], [{"phone": "512345678"}]).status_code == 402


# --- hiding numbers from the assistant ------------------------------------------------------------------


def test_phone_mask_hides_numbers_but_not_dates():
    mask = people_list.PhoneMask()
    text = mask.hide("Anna 512 345 678, od 12.11.2026\nJan +48 600-100-200 i znowu 512 345 678")

    assert text == "Anna [TEL1], od 12.11.2026\nJan [TEL2] i znowu [TEL1]"
    assert mask.number("[TEL2]") == "+48 600-100-200"
    assert mask.number("tel 1") == "512 345 678"
    assert mask.number("[TEL9]") is None
    # The same number written another way keeps its mark; a number only in the file is marked as such.
    assert mask.hide("Jan 600100200, Ewa 601 200 300", file=True) == "Jan [TEL2], Ewa [TEL3]"
    assert not mask.only_in_file("[TEL2]") and mask.only_in_file("[TEL3]")
    # The same nine digits after another country's code are another number.
    assert mask.hide("Olena +380 600 100 200") == "Olena [TEL4]"
