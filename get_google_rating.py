import json
import re
import sys
from pathlib import Path
from typing import TypedDict

from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


def extract_review_count_from_parentheses(text: str) -> int | None:
    m = re.search(r"\(([\d,]+)\)", text)
    if not m:
        return None
    return int(m.group(1).replace(",", ""))

def get_review_count_with_xpath(page: Page) -> int | None:
    xpath = "/html/body/div[1]/div[2]/div[9]/div[8]/div/div/div[1]/div[2]/div/div[1]/div/div/div[2]/div/div[1]/div[2]/div/div/div[2]/span[2]/span/span"

    try:
        node = page.locator(f"xpath={xpath}").first # type: ignore
        node.wait_for(timeout=12000) # type: ignore
        text = node.inner_text().strip()   # type: ignore # expected like "(2,062)"
        count = extract_review_count_from_parentheses(text) # type: ignore
        if count is not None:
            return count
    except Exception:
        pass

    return None


def get_review_count_from_reviews_badge(page: Page) -> int | None:
    """Read review count from semantic Google Maps badge, e.g. aria-label='3,704 reviews'."""
    try:
        badge = page.locator("span[role='img'][aria-label*='reviews']").first
        if badge.count() == 0:
            return None

        aria_attr = badge.get_attribute("aria-label")
        aria_label: str = aria_attr.strip() if isinstance(aria_attr, str) else ""
        count = parse_review_count_from_text(aria_label)
        if count is not None:
            return count

        visible_text = badge.inner_text().strip()  # often like "(3,704)"
        return parse_review_count_from_text(visible_text)
    except Exception:
        return None

def parse_rating_from_text(text: str) -> float | None:
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*stars", text, re.IGNORECASE)
    if not m:
        return None
    return float(m.group(1).replace(",", "."))


def parse_rating_from_number_text(text: str) -> float | None:
    cleaned = text.strip().replace(",", ".")
    if re.fullmatch(r"\d+(?:\.\d+)?", cleaned):
        return float(cleaned)
    return None


def parse_review_count_from_text(text: str) -> int | None:
    # "12 reviews", "1 review", "(12)"
    m = re.search(r"([\d,]+)\s+reviews?\b", text, re.IGNORECASE)
    if m:
        return int(m.group(1).replace(",", ""))

    m = re.search(r"\(([\d,]+)\)", text)
    if m:
        return int(m.group(1).replace(",", ""))

    return None



def get_google_maps_stats(place_name: str):
    Output_Dict = TypedDict(
        "Output_Dict",
        {
            "hotel_name": str,
            "rating": float | None,
            "review_count": int | None,
            "google_link": str | None,
            "latitude": float | None,
            "longtitude": float | None
        },
        total=False,
    )

    # SUB-FUNCTIONS ----
    def extract_lat_lng_from_google_link(google_link: str) -> tuple[float, float] | None:
        # Example fragment: /@14.4490413,121.0437851,16z
        m = re.search(r"/@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)", google_link)
        if not m:
            return None
        return float(m.group(1)), float(m.group(2))
    # ----


    out: Output_Dict = {
        "hotel_name": place_name,
        "rating": None,
        "review_count": None,
        "google_link": None,
        "latitude": None,
        "longtitude": None,
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_extra_http_headers({"Accept-Language": "en-US,en;q=0.9"})

        try:
            page.goto(
                f"https://www.google.com/maps/search/{place_name.replace(' ', '+')}",
                wait_until="domcontentloaded",
                timeout=45000,
            )

            for selector in [
                "button[aria-label*='Accept']",
                "button:has-text('Accept all')",
                "button:has-text('I agree')",
            ]:
                try:
                    page.click(selector, timeout=1200)
                    break
                except Exception:
                    pass

            page.wait_for_selector("div[role='main']", timeout=20000)

            # Give the rating/review header a moment to render
            try:
                page.wait_for_selector(
                    "div[role='main'] span[role='img'][aria-label*='stars'], "
                    "div[role='main'] span[role='img'][aria-label*='reviews'], "
                    "div[role='main'] button:has-text('reviews')",
                    timeout=12000,
                )
            except PlaywrightTimeoutError:
                pass

            # Parse all semantic aria-label badges first
            rating: float | None = None
            review_count: int | None = None

            # Priority: direct visible rating block
            rating_node = page.locator("div[role='main'] div.fontDisplayLarge").first
            if rating_node.count() > 0:
                rating_text = rating_node.inner_text().strip()
                rating = parse_rating_from_number_text(rating_text)

            # Fallback: semantic aria-label badges
            if rating is None:
                badges = page.locator("div[role='main'] span[role='img'][aria-label]")
                for i in range(badges.count()):
                    label = badges.nth(i).get_attribute("aria-label") or ""
                    parsed = parse_rating_from_text(label)
                    if parsed is not None:
                        rating = parsed
                        break

            # ---------------

            # Priority: semantic review badge like <span role="img" aria-label="3,704 reviews">(3,704)</span>
            badge_count = get_review_count_from_reviews_badge(page)
            if badge_count is not None:
                review_count = badge_count

            # Fallback: exact XPath for "(<int>)" review text
            if review_count is None:
                xpath_count = get_review_count_with_xpath(page)
                if xpath_count is not None:
                    review_count = xpath_count


            # Only do semantic fallback parsing if XPath did not find review count
            if review_count is None:
                # Parse semantic aria-label badges
                badges = page.locator("div[role='main'] span[role='img'][aria-label]")
                for i in range(badges.count()):
                    label = badges.nth(i).get_attribute("aria-label") or ""

                    if rating is None:
                        r = parse_rating_from_text(label)
                        if r is not None:
                            rating = r

                    c = parse_review_count_from_text(label)
                    if c is not None:
                        review_count = c
                        break

                # Fallback from visible button text: "12 reviews"
                if review_count is None:
                    btn = page.locator("div[role='main'] button:has-text('reviews')").first
                    if btn.count() > 0:
                        txt = btn.inner_text().strip()
                        c = parse_review_count_from_text(txt)
                        if c is not None:
                            review_count = c

                # Last fallback from page HTML
                if review_count is None:
                    html = page.content()
                    c = parse_review_count_from_text(html)
                    if c is not None:
                        review_count = c

            # Keep rating extraction independent so you still get rating even if reviews fail
            if rating is None:
                badges = page.locator("div[role='main'] span[role='img'][aria-label]")
                for i in range(badges.count()):
                    label = badges.nth(i).get_attribute("aria-label") or ""
                    r = parse_rating_from_text(label)
                    if r is not None:
                        rating = r
                        break
            
            # I want to get the current link of what the user is seeing
            current_link = page.url

            lat_lng = extract_lat_lng_from_google_link(current_link)
            latitude: float = 0.0
            longtitude: float = 0.0
            if lat_lng:
                latitude, longtitude = lat_lng

            # Take a screenshot and save to the project root
            project_root = Path(__file__).parent
            safe_name = re.sub(r'[\\/*?:"<>|]', "_", place_name)
            # screenshot_path = project_root / f"screenshot_{safe_name}.png"
            # page.screenshot(path=str(screenshot_path), full_page=True)

            if isinstance(review_count, int) and review_count >= 3233361:
                review_count = 0

            out = Output_Dict(
                hotel_name=place_name,
                rating=rating,
                review_count=review_count,
                google_link=current_link,
                latitude=latitude,
                longtitude=longtitude
            )
        except Exception as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
        finally:
            browser.close()

    return out


if __name__ == "__main__":
    query = " ".join(sys.argv[1:])
    print(json.dumps(get_google_maps_stats(query), ensure_ascii=False))