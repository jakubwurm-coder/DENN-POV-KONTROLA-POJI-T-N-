from __future__ import annotations

import subprocess
import sys
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://aiv.uniqa.cz"
LOGIN_URL = f"{BASE_URL}/vb/frmLoginMain.aspx"
LIST_URL = f"{BASE_URL}/vb/frmPovDenSeznam.aspx"

USER_SERVICE = "UNIQA_CHECKER_UNIQA_USER"
PASS_SERVICE = "UNIQA_CHECKER_UNIQA_PASS"


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
            f"Položka {service} nebyla nalezena v macOS Klíčence."
        )

    value = result.stdout.strip()

    if not value:
        raise RuntimeError(
            f"Položka {service} je prázdná."
        )

    return value


def clean(value: str | None) -> str:
    return (value or "").strip()


def find_login_fields(soup: BeautifulSoup):
    inputs = soup.find_all("input")

    password_input = None

    for inp in inputs:
        if clean(inp.get("type")).lower() == "password":
            password_input = inp
            break

    if password_input is None:
        raise RuntimeError(
            "Na přihlašovací stránce nebylo nalezeno pole typu password."
        )

    password_name = clean(password_input.get("name"))

    if not password_name:
        raise RuntimeError(
            "Pole hesla nemá HTML atribut name."
        )

    username_input = None

    candidates = []

    for inp in inputs:
        name = clean(inp.get("name"))
        input_type = clean(inp.get("type")).lower()

        if not name:
            continue

        if input_type in ("text", "email", ""):
            candidates.append(inp)

    keywords = (
        "user",
        "login",
        "jmeno",
        "jméno",
        "username",
        "uziv",
        "uživ",
    )

    for inp in candidates:
        haystack = " ".join(
            [
                clean(inp.get("name")),
                clean(inp.get("id")),
                clean(inp.get("placeholder")),
            ]
        ).lower()

        if any(word in haystack for word in keywords):
            username_input = inp
            break

    if username_input is None and candidates:
        password_index = inputs.index(password_input)

        before_password = [
            inp
            for inp in candidates
            if inputs.index(inp) < password_index
        ]

        if before_password:
            username_input = before_password[-1]
        else:
            username_input = candidates[0]

    if username_input is None:
        raise RuntimeError(
            "Nepodařilo se automaticky určit pole uživatelského jména."
        )

    username_name = clean(username_input.get("name"))

    if not username_name:
        raise RuntimeError(
            "Pole uživatelského jména nemá HTML atribut name."
        )

    return username_name, password_name


def build_form_payload(
    soup: BeautifulSoup,
    username_name: str,
    password_name: str,
    username: str,
    password: str,
):
    payload = {}

    for inp in soup.find_all("input"):
        name = clean(inp.get("name"))

        if not name:
            continue

        input_type = clean(inp.get("type")).lower()

        if input_type == "hidden":
            payload[name] = inp.get("value", "")

    payload[username_name] = username
    payload[password_name] = password

    # Klasické submit tlačítko.
    submit = soup.find(
        "input",
        attrs={"type": lambda value: value and value.lower() == "submit"},
    )

    if submit:
        submit_name = clean(submit.get("name"))

        if submit_name:
            payload[submit_name] = submit.get("value", "")

    else:
        # ASP.NET někdy používá ImageButton.
        image = soup.find(
            "input",
            attrs={"type": lambda value: value and value.lower() == "image"},
        )

        if image:
            image_name = clean(image.get("name"))

            if image_name:
                payload[f"{image_name}.x"] = "10"
                payload[f"{image_name}.y"] = "10"

    return payload


def looks_like_login_page(html: str, url: str) -> bool:
    text = html.lower()
    url_lower = url.lower()

    if "frmloginmain.aspx" in url_lower:
        return True

    if "vítejte v auto i volnost" in text and 'type="password"' in text:
        return True

    return False


def main():
    print()
    print("UNIQA AIV - TEST PŘIHLÁŠENÍ")
    print()

    username = keychain_read(USER_SERVICE)
    password = keychain_read(PASS_SERVICE)

    session = requests.Session()

    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/152.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "cs-CZ,cs;q=0.9,en;q=0.8",
        }
    )

    print("1. Otevírám přihlašovací stránku...")

    login_get = session.get(
        LOGIN_URL,
        timeout=30,
    )

    print("   HTTP:", login_get.status_code)

    login_get.raise_for_status()

    soup = BeautifulSoup(
        login_get.text,
        "html.parser",
    )

    form = soup.find("form")

    if form is None:
        raise RuntimeError(
            "Na frmLoginMain.aspx nebyl nalezen formulář."
        )

    username_name, password_name = find_login_fields(soup)

    print("2. Přihlašovací formulář nalezen.")
    print("   ASP.NET hidden tokeny budou převzaty automaticky.")

    payload = build_form_payload(
        soup=soup,
        username_name=username_name,
        password_name=password_name,
        username=username,
        password=password,
    )

    action = clean(form.get("action"))

    if action:
        post_url = urljoin(login_get.url, action)
    else:
        post_url = login_get.url

    print("3. Odesílám přihlášení...")

    login_post = session.post(
        post_url,
        data=payload,
        headers={
            "Referer": login_get.url,
            "Origin": BASE_URL,
        },
        timeout=30,
        allow_redirects=True,
    )

    print("   HTTP:", login_post.status_code)
    print("   Výsledná stránka:", login_post.url)

    login_post.raise_for_status()

    print("4. Otevírám seznam pojištěných vozidel...")

    list_response = session.get(
        LIST_URL,
        headers={
            "Referer": login_post.url,
        },
        timeout=30,
        allow_redirects=True,
    )

    print("   HTTP:", list_response.status_code)
    print("   Výsledná stránka:", list_response.url)

    list_response.raise_for_status()

    if looks_like_login_page(
        list_response.text,
        list_response.url,
    ):
        print()
        print("VÝSLEDEK: PŘIHLÁŠENÍ SE NEPODAŘILO")
        print()
        print(
            "Session byla vrácena zpět na přihlašovací stránku."
        )

        sys.exit(2)

    text = BeautifulSoup(
        list_response.text,
        "html.parser",
    ).get_text(
        " ",
        strip=True,
    )

    indicators = [
        "VIN",
        "RZ (SPZ)",
        "ČPS",
        "Pojištění od",
        "Pojištění do",
    ]

    found = [
        item
        for item in indicators
        if item.lower() in text.lower()
    ]

    print()
    print("VÝSLEDEK")
    print()

    print("UNIQA login: OK")
    print("Session vytvořena: ANO")
    print("Seznam pojištění dostupný: ANO")
    print(
        "Rozpoznané prvky seznamu:",
        ", ".join(found) if found else "stránka dostupná, tabulka zatím nenačtena",
    )

    print()
    print("Cookie session: ANO" if session.cookies else "Cookie session: NE")
    print()
    print(
        "Přihlašovací údaje nebyly vypsány ani uloženy do souboru."
    )


if __name__ == "__main__":
    try:
        main()

    except requests.exceptions.ConnectionError as exc:
        print()
        print("CHYBA SÍTĚ:")
        print(str(exc))
        sys.exit(3)

    except requests.exceptions.Timeout:
        print()
        print("CHYBA: UNIQA neodpověděla v časovém limitu.")
        sys.exit(4)

    except Exception as exc:
        print()
        print("CHYBA:")
        print(str(exc))
        sys.exit(1)
