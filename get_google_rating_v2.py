import argparse
import time
from typing import Any
import urllib.parse
import json
import sys  # <-- Import sys to route prints
from playwright.sync_api import sync_playwright
import difflib
from typing_extensions import TypedDict  # not: from typing import TypedDict
import os

def search_query(name_of_hotel: str):
    encoded_query = urllib.parse.quote(name_of_hotel)
    maps_url = f"https://www.google.com/maps/search/?api=1&query={encoded_query}"
    return maps_url

def get_similarity(search_term: str, actual_name: str) -> float:
    # Normalize the strings to lowercase so "Hotel" matches "hotel"
    search_clean = search_term.lower().strip()
    actual_clean = actual_name.lower().strip()
    
    # Calculate the similarity ratio
    similarity = difflib.SequenceMatcher(None, search_clean, actual_clean).ratio()
    
    # Return the float rounded to 2 decimal places
    return round(similarity, 2)

def Login_and_Save_Google_State(browser: Any) -> bool:
    # Must be headless=False so you can see what you are doing
    context = browser.new_context()
    page = context.new_page()

    # Go to Google login
    page.goto("https://accounts.google.com/")
    
    print("Please log in to your Google account in the browser.", file=sys.stderr)
    print("Once you are fully logged in, come back here and press ENTER.", file=sys.stderr)
    
    # This pauses the script so you have time to log in, do 2FA, etc.
    input("Press ENTER here when done logging in...")

    # Save the cookies and local storage to a file
    context.storage_state(path="google_auth.json")
    print("Login state saved to google_auth.json!", file=sys.stderr)
    
    browser.close()
    return True

def search_maps_url(name_of_hotel: str) -> dict[str, float | int]:
    with sync_playwright() as p:
        # Use your anti-bot settings here too, just to be extra safe!
        browser = p.chromium.launch(
            headless=False,
            channel="chrome",
            args=["--disable-blink-features=AutomationControlled"]
        )
        
        chosen_rating: float = 0.0  
        num_of_reviews: int = 0  
        
        try: 
            print("Setting up browser context...", file=sys.stderr)
            
            context: Any = None
            print("📥 Loading the saved cookies...", file=sys.stderr)
            if os.path.exists("google_auth.json"):
                context = browser.new_context(
                    storage_state="google_auth.json",
                    # Add this line to hide the HeadlessChrome flag!
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                )
                print("Loaded saved login state.", file=sys.stderr)
            else:
                print("No google_auth.json found! Running logged out.", file=sys.stderr)
                context = browser.new_context()

            # ALWAYS use context.new_page() when working with saved states
            if context is None:
                print("Error: Browser context was not created successfully.", file=sys.stderr)
                raise Exception("Failed to create browser context.")
            page = context.new_page()

            # --- 2. DOUBLE-CHECK IF COOKIES ARE EXPIRED ---
            print("🔎 Verifying Google session health...", file=sys.stderr)
            page.goto("https://www.google.com/", wait_until="domcontentloaded")
            
            # If Google asks us to sign in, our cookies are dead.
            sign_in_button = page.locator('a:has-text("Sign in")').first
            if sign_in_button.is_visible():
                print("❌ WARNING: Session expired! Google does not recognize your cookies.", file=sys.stderr)
                print("Triggering manual login prompt...", file=sys.stderr)
                
                # Trigger the Login Script
                responesLogin = Login_and_Save_Google_State(browser)
                
                if responesLogin:
                    print("✅ Login successful. Reloading context...", file=sys.stderr)
                    # Close the old, expired context
                    context.close()
                    time.sleep(1)
                    
                    # Create the NEW context with fresh cookies
                    context = browser.new_context(
                        storage_state="google_auth.json",
                        # Add this line to hide the HeadlessChrome flag!
                        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                    )
                    
                    # --- THE FIX: Create a NEW page from the NEW context ---
                    page = context.new_page() 
                    
                elif not responesLogin:
                    raise Exception("Failed to login and save state.")
            else:
                print("✅ Session is valid and active! Proceeding to scrape...", file=sys.stderr)

            
            print("Starting the Scraping Process", file=sys.stderr)
            maps_url: str = search_query(name_of_hotel)
            print(f"🏃 Navigating directly to: {maps_url}", file=sys.stderr)
            try:
                page.goto(maps_url, wait_until="networkidle", timeout=1000)
            except Exception:
                print("🧍 Network idle timeout reached, but page is likely loaded.", file=sys.stderr)
            # wait until 
            # there's this button with an arial-label="Photo of...." which only appears once the page is fully loaded.
            # <button class="aoRNLd kn2E5e NMjTrf lvtCsd " aria-label="Photo of The Bellevue Resort" jslog="15130; track:click; mutable:true;metadata:WyIwYWhVS0V3ancxLU9hODZDVEF4WGt6VGdHSFdRSEoyTVF6Q2NJVkNnVyJd" jsaction="pane.wfvdle32.heroHeaderImage"><img decoding="async" src="https://lh3.googleusercontent.com/gps-proxy/ALd4DhHY7PbcW_7tRYgTu5oqjJpCW2hzkyRbWpUVEVcqJ7vXCk2-Tbm9HHH3813u3U1yT_yoPPIyvdTdRhtXXTCWe_smovBeJFy0nUqK-jBrtgVD7dNn_Mti9laPDfPwxYRLfWM7tIV-1A8OzaZA9XLUf7JpffjLpLat9CT-TikPMNpLkBS_aGatPYwerQ=w408-h271-k-no" style="position: absolute; top: 50%; left: 50%; width: 408px; height: 272px; transform: translateY(-50%) translateX(-50%);"></button>
            # The ^= means the string MUST start with "Photo of "
            # Is there a way to check if the visible images are actually loaded?
            # Wait for the first 3 <img> tags on the page to finish downloading
            
            isResultsPageVisible: bool = False
            try: 
                print("🔎 checking if Results Heading is Visible", file=sys.stderr)
                resultsHeading = page.get_by_role("heading", name="Results", exact=True)
                resultsHeading.first.wait_for(state="visible", timeout=3000)
                isResultsPageVisible = resultsHeading.is_visible()
            except Exception:
                print("❌ Results Heading not found. Assuming we're on the direct map page.", file=sys.stderr)

                try: 
                    print("🔎 checking if You're at the end of the list", file=sys.stderr)

                    # find for this <span class="HlvSq">You've reached the end of the list.</span>
                    endOfListSpan = page.get_by_text("You've reached the end of the list.", exact=True)
                    endOfListSpan.wait_for(state="visible", timeout=3000)
                    isResultsPageVisible = endOfListSpan.is_visible()
                except Exception:
                    print("❌ End of list message not found. Still assuming we're on the direct map page.", file=sys.stderr)
                    isResultsPageVisible = False

            def direct_google_map_page_scrape(page: Any, chosen_rating: float = 0.0, num_of_reviews: int = 0) -> dict[str, float | int]:
                try:
                    page.locator('button[aria-label^="Photo of "]').first.wait_for(state="visible", timeout=10000)
                except Exception:
                    page.wait_for_timeout(1000)
                print("Hero image loaded! Safe to scrape data.", file=sys.stderr)
                print("Page fully loaded! Scraping span elements...", file=sys.stderr)

                max_attempts = 5
                attempt = 0
                while chosen_rating == 0.0 and attempt < max_attempts:
                    # Hierarchy: div with tabindex="-1" -> div with class fontBodyMedium -> span with aria-hidden="true"
                    all_ratings = page.locator('div[tabindex="-1"] div.fontBodyMedium span[aria-hidden="true"]').all_inner_texts()
                    
                    # 1. Clean the texts but KEEP the original top-to-bottom order
                    span_texts = [text.strip() for text in all_ratings if text.isascii() and text.strip()]
                    print(f'Cleaned span_texts (Ordered): {span_texts}', file=sys.stderr)
                    
                    chosen_rating = 0.0 # Fallback just in case
                    
                    # 2. Iterate through the list and grab the VERY FIRST valid float
                    for text in span_texts:
                        try:
                            chosen_rating = float(text)
                            # We found our main rating! Break out of the loop immediately.
                            break 
                        except ValueError:
                            pass
                    
                    print(f"🔎 Rating found: {chosen_rating}", file=sys.stderr)
                    attempt += 1
                    page.wait_for_timeout(100)
                print("finished rating loop", file=sys.stderr)
                page.wait_for_timeout(1000)

                if chosen_rating == 0.0:
                    raise Exception("❌ No rating found in the first 5 attempts. Conclusion: Place has 0 reviews, Google changed their layout again, or Name is Unrecognizable.")
                else:
                    print(f"✅ Ratings Found! {chosen_rating} Moving on to reviews...", file=sys.stderr)
                    
                    page.wait_for_timeout(1000)

                    # Find an element like this <span role="img" aria-label="32 reviews">(32)</span>
                    # --- 100% CLEAN REVIEWS EXTRACTOR ---
                    print("Searching for review count...", file=sys.stderr)
                    
                    # We use 'review' to catch both singular and plural, inside the main side panel
                    reviews_locator = page.locator('div[tabindex="-1"] span[aria-label*="review"]').first
                    
                    try:
                        # Give the headless browser up to 5 seconds to render the text
                        reviews_locator.wait_for(state="attached", timeout=5000)
                        
                        aria_label = reviews_locator.get_attribute("aria-label")
                        if aria_label:
                            num_of_reviews_str = ''.join(filter(str.isdigit, aria_label))
                            if num_of_reviews_str:
                                num_of_reviews = int(num_of_reviews_str)
                                print(f"✅ Number of reviews found: {num_of_reviews}", file=sys.stderr)
                            else:
                                print("No digits found in aria-label.", file=sys.stderr)
                        else:
                            print("No aria-label attribute found.", file=sys.stderr)
                    except Exception:
                        print("❌ No reviews element found (Timeout).", file=sys.stderr)
                page.wait_for_timeout(1000)
                return {
                    "rating": chosen_rating,
                    "num_of_reviews": num_of_reviews,
                }

            if isResultsPageVisible:
                print("📍 You're in the results page", file=sys.stderr)
                print("not the direct map page!", file=sys.stderr)

                # 1. Target only <a> tags that actually have an aria-label attribute
                links = page.locator("a[aria-label]")

                class HotelResult(TypedDict, closed=True):
                    hotel_name: str
                    similarity_score: float
                    rating: float  # <-- ADDED: We need to store the rating for the tie-breaker
                    href_link: str

                listThing: list[HotelResult] = []

                # 2. Extract name, href, AND peek inside the element to find its rating
                print("🔎 extracting all hotel names, ratings, and links from the results page...", file=sys.stderr)
                js_code = """
                elements => elements.map(e => {
                    let rating = 0.0;
                    // Look for the star rating span inside this specific search result
                    const ratingSpan = e.querySelector('span[aria-label*="stars"], span[aria-label*="star"]');
                    if (ratingSpan) {
                        const aria = ratingSpan.getAttribute('aria-label');
                        // Extract just the float number from "4.5 stars"
                        const match = aria.match(/[\\d\\.]+/);
                        if (match) {
                            rating = parseFloat(match[0]);
                        }
                    }
                    return {
                        name: e.getAttribute('aria-label'),
                        rating: rating,
                        href: e.getAttribute('href') || '' 
                    };
                })
                """
                print("🏃 executing JavaScript code...", file=sys.stderr)
                all_hotel_data = links.evaluate_all(js_code)
                for data in all_hotel_data:
                    hotel_name = data['name']
                    href_link = data['href']
                    extracted_rating = data['rating'] 
                    
                    # Calculate similarity using the extracted name
                    similarity = get_similarity(name_of_hotel, hotel_name)
                    
                    # Add everything to your array
                    listThing.append(HotelResult(
                        hotel_name=hotel_name, 
                        similarity_score=similarity, 
                        rating=extracted_rating,  # <-- Save the rating here
                        href_link=href_link
                    ))
                print(f"✅ Found {len(all_hotel_data)} hotels on the page.", file=sys.stderr)
                print("🏃 sort the list by similarity score (and rating as a tie-breaker) in descending order", file=sys.stderr)
                listThing.sort(key=lambda x: (x['similarity_score'], x['rating']), reverse=True)
                
                # Print the highest scoring result if the list isn't empty
                if listThing:
                    print(f"✅ Best Match: {listThing[0]}", file=sys.stderr)
                    print("🏃 Taking user to the main page", file=sys.stderr)
                    page.goto(f"{listThing[0]['href_link']}")
                page.wait_for_timeout(3000)

                print("🔎 checking if Hero Image is Visible (using same technique in direct page)", file=sys.stderr)
                responseDirectGoogeleMapScrape = direct_google_map_page_scrape(page)
                chosen_rating = responseDirectGoogeleMapScrape["rating"]
                num_of_reviews = int(responseDirectGoogeleMapScrape["num_of_reviews"])
            else:
                print("📍 You're in the direct Google Map Page", file=sys.stderr)
                responseDirectGoogeleMapScrape = direct_google_map_page_scrape(page)
                chosen_rating = responseDirectGoogeleMapScrape["rating"]
                num_of_reviews = int(responseDirectGoogeleMapScrape["num_of_reviews"])
                
        except Exception as e:
            print(f"Error during scraping: {e}", file=sys.stderr)
        finally:
            browser.close()
        return {
            "rating": chosen_rating,
            "num_of_reviews": num_of_reviews,
        }

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape Google Maps rating for a location.")
    parser.add_argument("location", type=str, nargs="?", default="The Soul Center")
    args = parser.parse_args()
    
    print(f"--- Starting scrape for: {args.location} ---", file=sys.stderr)
    
    # Run the scrape
    result = search_maps_url(args.location)
    
    # --- THE ONLY THING PRINTING TO STDOUT ---
    # Because this is the only print without file=sys.stderr, 
    # it is the only thing that goes into result.stdout!
    print(json.dumps(result))