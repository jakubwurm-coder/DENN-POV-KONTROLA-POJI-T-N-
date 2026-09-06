from __future__ import annotations

import subprocess
from dataclasses import dataclass, field

import requests
from bs4 import BeautifulSoup

from models import UniqaVehicle
from normalize import normalize_spz, normalize_vin


BASE_URL = "https://aiv.uniqa.cz"

LOGIN_URL = f"{BASE_URL}/vb/frmLoginMain.aspx"
START_URL = f"{BASE_URL}/vb/frmStart.aspx"
LIST_URL = f"{BASE_URL}/vb/frmPovDenSeznam.aspx"

USER_SERVICE = "UNIQA_CHECKER_UNIQA_USER"
PASS_SERVICE = "UNIQA_CHECKER_UNIQA_PASS"


@dataclass
class UniqaLoadResult:
    vehicles: list[UniqaVehicle]
    available: bool
    error: str = ""

    # Skupiny stejného VIN, který se v aktivním seznamu
    # UNIQA vyskytuje více než jednou.
    duplicates: list[list[UniqaVehicle]] = field(
        default_factory=list
    )

    raw_count: int = 0


def keychain_read(service: str) -> str:
    result = subprocess.run(
        [
            "/usr/bin/security",
            "find-generic-password",
            "-a",
            "login",
            "-s",
            service,
            "-w",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"Chybí položka macOS Klíčenky: {service}"
        )

    value = result.stdout.strip()

    if not value:
        raise RuntimeError(
            f"Položka macOS Klíčenky je prázdná: {service}"
        )

    return value


def make_session() -> requests.Session:
    session = requests.Session()

    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/152.0.0.0 Safari/537.36"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;"
                "q=0.9,image/avif,image/webp,*/*;q=0.8"
            ),
            "Accept-Language": "cs-CZ,cs;q=0.9,en;q=0.8",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }
    )

    return session


def parse_html(
    response: requests.Response,
) -> BeautifulSoup:
    return BeautifulSoup(
        response.content,
        "html.parser",
    )


def hidden_fields(
    soup: BeautifulSoup,
) -> dict[str, str]:

    payload: dict[str, str] = {}

    for inp in soup.find_all("input"):

        name = (
            inp.get("name")
            or ""
        ).strip()

        if not name:
            continue

        typ = (
            inp.get("type")
            or ""
        ).lower()

        if typ == "hidden":
            payload[name] = inp.get(
                "value",
                "",
            )

    return payload


def is_login_page(
    response: requests.Response,
) -> bool:

    if "frmloginmain.aspx" in response.url.lower():
        return True

    soup = parse_html(
        response
    )

    if soup.find(
        id="nf2Username"
    ):
        return True

    if soup.find(
        id="nf2Password"
    ):
        return True

    return False


def login(
    session: requests.Session,
) -> None:

    username = keychain_read(
        USER_SERVICE
    )

    password = keychain_read(
        PASS_SERVICE
    )

    print()
    print("UNIQA - přihlašování...")

    response = session.get(
        LOGIN_URL,
        timeout=30,
    )

    response.raise_for_status()

    soup = parse_html(
        response
    )

    form = soup.find(
        "form",
        id="f1",
    )

    if form is None:
        raise RuntimeError(
            "UNIQA login formulář f1 nebyl nalezen."
        )

    payload = hidden_fields(
        soup
    )

    payload["username"] = username
    payload["password"] = password

    payload["nf2Username"] = username
    payload["nf2Password"] = password

    payload["password2"] = ""
    payload["screenwidth"] = ""

    payload[
        "ctl00$body$LoginReturnURL"
    ] = "frmStart.aspx"

    login_response = session.post(
        LOGIN_URL,
        data=payload,
        headers={
            "Referer": LOGIN_URL,
            "Origin": BASE_URL,
        },
        timeout=30,
        allow_redirects=True,
    )

    login_response.raise_for_status()

    if is_login_page(
        login_response
    ):
        raise RuntimeError(
            "UNIQA přihlášení nebylo přijato."
        )

    print("UNIQA login: OK")


def get_control_value(
    soup: BeautifulSoup,
    name: str,
    default: str = "",
) -> str:

    control = soup.find(
        attrs={
            "name": name
        }
    )

    if control is None:
        return default

    if control.name == "select":

        selected = (
            control.find(
                "option",
                selected=True,
            )
            or control.find(
                "option"
            )
        )

        if selected:
            return selected.get(
                "value",
                "",
            )

        return default

    return control.get(
        "value",
        default,
    )


def load_active_list(
    session: requests.Session,
) -> requests.Response:

    print(
        "UNIQA - otevírám Denní POV..."
    )

    response = session.get(
        LIST_URL,
        headers={
            "Referer": START_URL,
        },
        timeout=30,
        allow_redirects=True,
    )

    response.raise_for_status()

    if is_login_page(
        response
    ):
        raise RuntimeError(
            "UNIQA session vypršela před otevřením Denní POV."
        )

    soup = parse_html(
        response
    )

    payload = hidden_fields(
        soup
    )

    payload[
        "ctl00$body$txtAkce"
    ] = "1"

    payload[
        "ctl00$body$txtMaxStrana"
    ] = ""

    payload[
        "ctl00$body$txtStrana"
    ] = ""

    payload[
        "ctl00$body$txtOrder"
    ] = (
        get_control_value(
            soup,
            "ctl00$body$txtOrder",
            "pojisteniod",
        )
        or "pojisteniod"
    )

    payload[
        "ctl00$body$txtNabidka"
    ] = ""

    payload[
        "ctl00$body$txtZaruka"
    ] = ""

    payload[
        "ctl00$body$txtCislo"
    ] = get_control_value(
        soup,
        "ctl00$body$txtCislo",
        "",
    )

    # 1 = Aktivní
    payload[
        "ctl00$body$comboVyber"
    ] = "1"

    payload[
        "ctl00$body$txtOd$txt_date"
    ] = ""

    payload[
        "ctl00$body$txtDo$txt_date"
    ] = ""

    payload[
        "ctl00$body$txtVIN"
    ] = ""

    payload[
        "ctl00$body$txtRZ"
    ] = ""

    print(
        "UNIQA - klikám Zobraz "
        "(Aktivní vozidla)..."
    )

    result = session.post(
        LIST_URL,
        data=payload,
        headers={
            "Referer": LIST_URL,
            "Origin": BASE_URL,
        },
        timeout=45,
        allow_redirects=True,
    )

    result.raise_for_status()

    if is_login_page(
        result
    ):
        raise RuntimeError(
            "UNIQA session vypršela při načítání seznamu."
        )

    return result


def parse_vehicle_table(
    response: requests.Response,
) -> list[UniqaVehicle]:

    soup = parse_html(
        response
    )

    target_table = None

    for table in soup.find_all(
        "table"
    ):

        rows = table.find_all(
            "tr"
        )

        if not rows:
            continue

        headers = [
            cell.get_text(
                " ",
                strip=True,
            )
            for cell in rows[0].find_all(
                ["td", "th"]
            )
        ]

        normalized_headers = [
            h.strip().upper()
            for h in headers
        ]

        required = {
            "ČPS",
            "POJ. OD",
            "POJ. DO",
            "VIN",
            "RZ (SPZ)",
        }

        if required.issubset(
            set(
                normalized_headers
            )
        ):
            target_table = table
            break

    if target_table is None:
        raise RuntimeError(
            "UNIQA tabulka Denní POV nebyla nalezena."
        )

    rows = target_table.find_all(
        "tr"
    )

    headers = [
        cell.get_text(
            " ",
            strip=True,
        ).strip()
        for cell in rows[0].find_all(
            ["td", "th"]
        )
    ]

    index = {
        name.strip().upper(): i
        for i, name in enumerate(
            headers
        )
    }

    vehicles: list[UniqaVehicle] = []

    for row in rows[1:]:

        cells = [
            cell.get_text(
                " ",
                strip=True,
            )
            for cell in row.find_all(
                ["td", "th"]
            )
        ]

        if len(cells) < len(headers):
            continue

        vin = normalize_vin(
            cells[
                index["VIN"]
            ]
        )

        if not vin:
            continue

        spz = normalize_spz(
            cells[
                index["RZ (SPZ)"]
            ]
        )

        vehicles.append(
            UniqaVehicle(
                vin=vin,
                spz=spz,
                cps=cells[
                    index["ČPS"]
                ],
                poj_od=cells[
                    index["POJ. OD"]
                ],
                poj_do=cells[
                    index["POJ. DO"]
                ],
            )
        )

    return vehicles


def split_duplicates(
    vehicles: list[UniqaVehicle],
) -> tuple[
    list[UniqaVehicle],
    list[list[UniqaVehicle]],
]:

    groups: dict[
        str,
        list[UniqaVehicle],
    ] = {}

    for vehicle in vehicles:

        groups.setdefault(
            vehicle.vin,
            [],
        ).append(
            vehicle
        )

    unique: list[UniqaVehicle] = []

    duplicates: list[
        list[UniqaVehicle]
    ] = []

    for vin, group in groups.items():

        # ====================================================
        # DUPLICITA
        # ====================================================

        if len(group) > 1:

            duplicate_group = sorted(
                group,
                key=lambda v: (
                    v.poj_od,
                    v.cps,
                ),
            )

            duplicates.append(
                duplicate_group
            )

        # ====================================================
        # PRO HLAVNÍ POROVNÁNÍ BEREME JEDEN ZÁZNAM
        # ====================================================

        preferred = sorted(
            group,
            key=lambda v: (
                1 if not v.poj_do else 0,
                v.poj_od,
            ),
            reverse=True,
        )[0]

        unique.append(
            preferred
        )

    unique.sort(
        key=lambda v: v.vin
    )

    duplicates.sort(
        key=lambda group: group[0].vin
    )

    return unique, duplicates


def print_duplicates(
    duplicates: list[list[UniqaVehicle]],
) -> None:

    print()
    print("=" * 70)
    print("UNIQA - DUPLICITNÍ VIN")
    print("=" * 70)

    if not duplicates:

        print()
        print(
            "Žádný VIN není v aktivní UNIQA veden vícekrát."
        )
        print()

        return

    print()
    print(
        "Počet duplicitních VIN skupin:",
        len(duplicates),
    )
    print()

    for number, group in enumerate(
        duplicates,
        start=1,
    ):

        vin = group[0].vin

        print("-" * 70)

        print(
            f"{number}. VIN: {vin}"
        )

        print(
            "Počet aktivních záznamů:",
            len(group),
        )

        for index, vehicle in enumerate(
            group,
            start=1,
        ):

            print()
            print(
                f"   Záznam {index}"
            )

            print(
                f"   ČPS: {vehicle.cps or '-'}"
            )

            print(
                f"   SPZ: {vehicle.spz or '-'}"
            )

            print(
                f"   Pojištění od: {vehicle.poj_od or '-'}"
            )

            print(
                f"   Pojištění do: {vehicle.poj_do or '-'}"
            )

        print()

    print("-" * 70)
    print()


def load_uniqa_vehicles() -> UniqaLoadResult:

    try:

        session = make_session()

        login(
            session
        )

        response = load_active_list(
            session
        )

        raw = parse_vehicle_table(
            response
        )

        vehicles, duplicates = split_duplicates(
            raw
        )

        without_spz = sum(
            1
            for v in vehicles
            if not v.spz
        )

        extra_duplicate_rows = (
            len(raw)
            - len(vehicles)
        )

        print()
        print("UNIQA LIVE:")

        print(
            "Načtených řádků:",
            len(raw),
        )

        print(
            "Unikátních VIN:",
            len(vehicles),
        )

        print(
            "Bez SPZ:",
            without_spz,
        )

        print(
            "Duplicitních VIN skupin:",
            len(duplicates),
        )

        print(
            "Duplicitních řádků navíc:",
            extra_duplicate_rows,
        )

        print_duplicates(
            duplicates
        )

        if not vehicles:
            raise RuntimeError(
                "UNIQA vrátila prázdný seznam. "
                "Prázdný seznam nebude považován "
                "za důkaz, že vozidla nejsou pojištěná."
            )

        return UniqaLoadResult(
            vehicles=vehicles,
            available=True,
            error="",
            duplicates=duplicates,
            raw_count=len(raw),
        )

    except Exception as exc:

        print()
        print(
            "UNIQA LIVE NELZE OVĚŘIT:"
        )

        print(
            str(exc)
        )

        print()

        return UniqaLoadResult(
            vehicles=[],
            available=False,
            error=str(exc),
            duplicates=[],
            raw_count=0,
        )
