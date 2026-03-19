import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

from ics import Calendar, Event
from dateutil import tz
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

URL = "https://selfservice-prod.ml.tcl.fr/SelfService2017/Assignments"
TIMEZONE = "Europe/Paris"

MONTHS_FR = {
    "janvier": 1,
    "février": 2,
    "mars": 3,
    "avril": 4,
    "mai": 5,
    "juin": 6,
    "juillet": 7,
    "août": 8,
    "septembre": 9,
    "octobre": 10,
    "novembre": 11,
    "décembre": 12,
}

ALL_DAY_CODES = {"MA", "RN", "RHE", "LN", "N/D", "RHM", "REMA", "XX_NUIT"}

LOCATION_MAP = {
    "CDM Saint Priest": "Cours du Professeur Jean Bernard, 69800 Saint-Priest",
    "Garage Part Dieu": "42 Rue de la Villette, 69003 Lyon",
    "Meyzieu Z.i": "Rue Antoine Becquerel, 69330 Meyzieu",
    "CDM Meyzieu": "10 Avenue Lionel Terray, 69330 Meyzieu",
    "Grange Blanche": "6 Avenue Rockefeller, 69008 Lyon",
    "Hopitaux Est - Pinel": "22 Rue Chambovet, 69003 Lyon",
    "Debourg": "94 Avenue Debourg, 69007 Lyon",
    "Porte des Alpes": "Cours du Professeur Jean Bernard, 69800 Saint-Priest",
}

INITIAL_CLICK_WAIT_SECONDS = 2.2
DETAIL_MAX_WAIT_SECONDS = 8.0
DETAIL_POLL_INTERVAL_SECONDS = 0.35


def normalize_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def extract_day_and_code_from_cell(text: str):
    txt = normalize_spaces(text)

    day_match = re.search(r"\b(\d{1,2})\b", txt)
    if not day_match:
        return None, None

    day = int(day_match.group(1))

    code_patterns = [
        r"\b(N/D)\b",
        r"\b(REMA|RHM|RHE|RN|LN|MN|MA|XX_NUIT)\b",
        r"\b([A-Z]+\-\d+\*?)\b",
        r"\b([A-Z]\d\-\d+\*?)\b",
        r"\b([A-Z0-9\-/*]{2,})\b",
    ]

    code = None
    for pattern in code_patterns:
        m = re.search(pattern, txt)
        if m:
            value = m.group(1)
            if value not in {"A", "C", "AA"}:
                code = value
                break

    return day, code


def parse_current_month_year(page):
    txt = normalize_spaces(page.locator("#MonthAndYearSelector .k-input").inner_text())
    m = re.search(
        r"^(janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)\s*-\s*(\d{4})$",
        txt,
        re.IGNORECASE,
    )
    if not m:
        raise RuntimeError(f"Impossible de lire le mois courant depuis le sélecteur: {txt!r}")

    month_name = m.group(1).lower()
    year = int(m.group(2))
    return MONTHS_FR[month_name], year


def parse_french_detail_block(text: str):
    text = normalize_spaces(text)

    m_title = re.search(
        r"([A-Z0-9\-/*]+)\s*\((?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)\s+(\d{1,2})\s+([a-zéûîôàèù]+)\s+(\d{4})\)",
        text,
        re.IGNORECASE,
    )
    m_start = re.search(r"Début\s*:\s*(\d{1,2}:\d{2})", text, re.IGNORECASE)
    m_end = re.search(r"Fin\s*:\s*(\d{1,2}:\d{2})", text, re.IGNORECASE)
    m_from = re.search(r"De\s*:\s*(.*?)\s*Début\s*:", text, re.IGNORECASE)

    if not (m_title and m_start and m_end):
        return None

    code = m_title.group(1).strip()
    day = int(m_title.group(2))
    month_name = m_title.group(3).lower()
    year = int(m_title.group(4))

    if month_name not in MONTHS_FR:
        return None

    base_date = datetime(year, MONTHS_FR[month_name], day)

    def build_dt(base: datetime, hhmm: str) -> datetime:
        hh, mm = map(int, hhmm.split(":"))
        extra_day = 0
        if hh >= 24:
            hh -= 24
            extra_day = 1
        return base.replace(hour=hh, minute=mm) + timedelta(days=extra_day)

    start_dt = build_dt(base_date, m_start.group(1))
    end_dt = build_dt(base_date, m_end.group(1))

    if end_dt <= start_dt:
        end_dt += timedelta(days=1)

    start_place = normalize_spaces(m_from.group(1)) if m_from else None

    return {
        "title": code,
        "date": base_date.date(),
        "start": start_dt,
        "end": end_dt,
        "start_place": start_place,
    }


def resolve_location(start_place):
    if not start_place:
        return None

    exact = LOCATION_MAP.get(start_place)
    if exact:
        return exact

    start_place_lower = start_place.lower()
    for key, value in LOCATION_MAP.items():
        key_lower = key.lower()
        if key_lower in start_place_lower or start_place_lower in key_lower:
            return value

    return start_place


def get_detail_block_text(page):
    blocks = page.locator("div, section, td")
    count = min(blocks.count(), 700)

    for i in range(count):
        try:
            txt = normalize_spaces(blocks.nth(i).inner_text(timeout=500))
            if "Jour de travail" in txt and "Début" in txt and "Fin" in txt:
                return txt
        except Exception:
            pass

    return None


def wait_for_fresh_detail(page, previous_detail_text, timeout_seconds: float):
    deadline = time.time() + timeout_seconds
    last_seen = None

    while time.time() < deadline:
        detail_text = get_detail_block_text(page)

        if detail_text:
            if previous_detail_text is None:
                return detail_text

            if normalize_spaces(detail_text) != normalize_spaces(previous_detail_text):
                return detail_text

            last_seen = detail_text

        time.sleep(DETAIL_POLL_INTERVAL_SECONDS)

    return last_seen if previous_detail_text is None else None


def add_timed_event(cal: Calendar, paris_tz, title: str, start_dt: datetime, end_dt: datetime, location=None):
    e = Event()
    e.name = title
    e.begin = start_dt.replace(tzinfo=paris_tz)
    e.end = end_dt.replace(tzinfo=paris_tz)
    e.description = ""
    if location:
        e.location = location
    cal.events.add(e)


def add_all_day_event(cal: Calendar, title: str, date_value):
    e = Event()
    e.name = title
    e.begin = date_value
    e.make_all_day()
    e.description = ""
    cal.events.add(e)


def login_if_needed(page, username: str, password: str):
    if not username or not password:
        raise RuntimeError("Identifiants planning manquants.")

    page.goto(URL, wait_until="domcontentloaded")
    time.sleep(2)

    try:
        if page.locator("#MonthAndYearSelector").count() > 0:
            return
    except Exception:
        pass

    user_selectors = [
        "input[type='text']",
        "input[name*='user' i]",
        "input[id*='user' i]",
        "input[name*='login' i]",
        "input[id*='login' i]",
        "input[name*='ident' i]",
        "input[id*='ident' i]",
    ]

    password_selectors = [
        "input[type='password']",
        "input[name*='pass' i]",
        "input[id*='pass' i]",
        "input[name*='pwd' i]",
        "input[id*='pwd' i]",
    ]

    user_locator = None
    for sel in user_selectors:
        try:
            locator = page.locator(sel).first
            locator.wait_for(timeout=2000)
            locator.fill(username, timeout=2000)
            user_locator = locator
            break
        except Exception:
            pass

    if user_locator is None:
        raise RuntimeError("Impossible de trouver le champ identifiant.")

    password_locator = None
    for sel in password_selectors:
        try:
            locator = page.locator(sel).first
            locator.wait_for(timeout=2000)
            locator.fill(password, timeout=2000)
            password_locator = locator
            break
        except Exception:
            pass

    if password_locator is None:
        raise RuntimeError("Impossible de trouver le champ mot de passe.")

    submitted = False
    submit_selectors = [
        "input[type='submit'][value*='Valider' i]",
        "button[type='submit']",
        "input[type='submit']",
        "button:has-text('Valider')",
        "button:has-text('Connexion')",
        "button:has-text('Se connecter')",
    ]

    for sel in submit_selectors:
        try:
            btn = page.locator(sel).first
            btn.wait_for(timeout=1500)
            btn.click(timeout=2000)
            submitted = True
            break
        except Exception:
            pass

    if not submitted:
        try:
            password_locator.press("Enter")
            submitted = True
        except Exception:
            pass

    if not submitted:
        raise RuntimeError("Impossible de soumettre le formulaire de connexion.")

    try:
        page.wait_for_selector("#MonthAndYearSelector", timeout=20000)
    except Exception:
        page.goto(URL, wait_until="domcontentloaded")
        page.wait_for_selector("#MonthAndYearSelector", timeout=20000)

    time.sleep(2)

    if page.locator("#MonthAndYearSelector").count() == 0:
        raise RuntimeError("Connexion effectuée, mais le planning n'a pas été détecté.")


def go_to_next_month(page):
    previous_label = normalize_spaces(page.locator("#MonthAndYearSelector .k-input").inner_text())

    page.locator("#NextMonth").click(timeout=3000)

    deadline = time.time() + 12
    while time.time() < deadline:
        try:
            current_label = normalize_spaces(page.locator("#MonthAndYearSelector .k-input").inner_text())
            if current_label != previous_label:
                time.sleep(1.2)
                return
        except Exception:
            pass
        time.sleep(0.3)

    raise RuntimeError("Le mois suivant n'a pas chargé correctement.")


def is_outside_current_month(item) -> bool:
    class_name = (item.get_attribute("class") or "").lower()

    outside_markers = [
        "anothermonth",
        "fromanothermonth",
        "foranothermonth",
    ]

    return any(marker in class_name for marker in outside_markers)


def collect_clickable_days(page):
    selectors = [
        "[class*='CalendarDayContentWrapper']",
        "[class*='CalendarDayContent']",
        "[class*='CalendarDay']",
        "td",
        "div",
    ]

    for sel in selectors:
        loc = page.locator(sel)
        out = []
        count = min(loc.count(), 700)

        for i in range(count):
            try:
                item = loc.nth(i)
                txt = normalize_spaces(item.inner_text(timeout=300))
                day, code = extract_day_and_code_from_cell(txt)

                if not (day and code):
                    continue

                if is_outside_current_month(item):
                    continue

                out.append(item)
            except Exception:
                pass

        if len(out) >= 7:
            return out

    return []


def process_current_month(page, cal, paris, seen_timed, seen_all_day):
    current_month, current_year = parse_current_month_year(page)
    print(f"Mois détecté : {current_month:02d}/{current_year}")

    days = collect_clickable_days(page)
    print(f"{len(days)} cases plausibles détectées pour {current_month:02d}/{current_year}")

    if not days:
        return

    previous_detail_text = get_detail_block_text(page)

    for idx in range(len(days)):
        try:
            days = collect_clickable_days(page)
            if idx >= len(days):
                break

            cell = days[idx]
            preview = normalize_spaces(cell.inner_text(timeout=500))
            day_num, cell_code = extract_day_and_code_from_cell(preview)

            if not day_num or not cell_code:
                continue

            cell.click(timeout=3000)
            time.sleep(INITIAL_CLICK_WAIT_SECONDS)

            detail_text = wait_for_fresh_detail(
                page,
                previous_detail_text=previous_detail_text,
                timeout_seconds=DETAIL_MAX_WAIT_SECONDS,
            )

            if detail_text:
                detail = parse_french_detail_block(detail_text)
                if detail:
                    key = (detail["title"], detail["start"], detail["end"])
                    if key not in seen_timed:
                        seen_timed.add(key)
                        location = resolve_location(detail["start_place"])
                        add_timed_event(
                            cal,
                            paris,
                            detail["title"],
                            detail["start"],
                            detail["end"],
                            location=location,
                        )
                    previous_detail_text = detail_text
                    continue

            if cell_code in ALL_DAY_CODES:
                event_date = datetime(current_year, current_month, day_num).date()
                key = (cell_code, event_date)

                if key not in seen_all_day:
                    seen_all_day.add(key)
                    add_all_day_event(cal, cell_code, event_date)

        except PlaywrightTimeoutError:
            pass
        except Exception:
            pass


def generate_tcl_ics_for_user(user):
    os.makedirs("data/ics", exist_ok=True)
    output_path = f"data/ics/user_{user.id}.ics"

    cal = Calendar()
    paris = tz.gettz(TIMEZONE)

    seen_timed = set()
    seen_all_day = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(locale="fr-FR", timezone_id=TIMEZONE)
        page = context.new_page()

        login_if_needed(page, user.planning_login, user.planning_password)

        months_to_process = 3

        for i in range(months_to_process):
            process_current_month(page, cal, paris, seen_timed, seen_all_day)

            if i < months_to_process - 1:
                go_to_next_month(page)

        browser.close()

    with open(output_path, "w", encoding="utf-8") as f:
        f.writelines(cal)

    return output_path