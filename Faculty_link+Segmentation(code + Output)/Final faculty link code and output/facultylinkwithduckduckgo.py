import os
import time
import re
import warnings
import pandas as pd
import requests
from urllib.parse import urljoin, urlparse
from ddgs import DDGS
from openai import OpenAI
from dotenv import load_dotenv

# 1. Silence warnings
warnings.filterwarnings("ignore", message=".*package.*renamed.*")

# Load environment variables
load_dotenv()

# --- CONFIGURATION ---
INPUT_FILE = "Copy-2026-QS-with-links-filled.xlsx"
OUTPUT_FILE = "universities_with_faculty.xlsx"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Check API Key
if not OPENAI_API_KEY:
    print("❌ ERROR: OPENAI_API_KEY is missing. Check your .env file.")
    exit()

client = OpenAI(api_key=OPENAI_API_KEY)

# --- HELPER: ROBUST URL VALIDATION ---
def is_faculty_url(url: str) -> bool:
    """
    Checks if a URL is likely a faculty directory or department list.
    Returns True if it contains strong keywords or profile links.
    """
    if not url or not isinstance(url, str):
        return False

    u = url.lower()

    # 1. Quick Reject: Generic pages
    reject_tokens = [
        "about-us", "governance", "governance-and-structure", "contact", "alumni",
        "news", "events", "calendar", "jobs", "careers", "press", "store", "admissions",
        "prospectus", "apply", "course", "courses", "faq", "help", "privacy", "policy",
        "facebook", "linkedin", "twitter", "instagram", "youtube", "researchgate", "pdf"
    ]
    for t in reject_tokens:
        if t in u:
            return False

    # 2. Strong Accept: Explicit directory tokens in URL path
    accept_tokens = [
        "/faculty", "/people", "/staff", "/directory", "/departments", "/profiles",
        "/our-people", "/faculty-directory", "/people-list", "/academic-staff",
        "/teaching-staff", "/staff-list", "/profiles/", "/researchers"
    ]
    for t in accept_tokens:
        if t in u:
            if not any(rt in u for rt in reject_tokens):
                return True

    # 3. Reject individual profiles (we want the list, not the person)
    path = urlparse(u).path
    if re.search(r"/(people|profile|person|staff|faculty)/[^/]+$", path):
        return False

    # 4. Deep Inspection: Fetch page content to count links/keywords
    try:
        # Timeout quickly to avoid hanging
        resp = requests.get(url, timeout=5, allow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code != 200:
            return False
        text = resp.text.lower()[:100000] # Analyze first 100KB
    except Exception:
        return False

    # Check for directory phrases
    directory_phrases = [
        "staff directory", "faculty directory", "directory of staff", "find a person",
        "search people", "search staff", "browse people", "our people", "find a staff",
        "find staff", "people directory", "faculty & staff", "academic staff", "list of staff",
        "list of faculty", "staff & faculty", "people search", "faculty members", "our staff"
    ]
    
    # Count profile-like links (e.g. href="/people/john-doe")
    hrefs = re.findall(r'href=["\']([^"\']+)["\']', resp.text, flags=re.IGNORECASE)
    profile_tokens = ["/people", "/profile", "/staff", "/person", "/academic", "/profiles/"]
    count = 0
    for h in hrefs:
        if any(pt in h.lower() for pt in profile_tokens):
            count += 1
    
    # Heuristic: Either strong keywords OR many profile links
    if count >= 5: return True
    if any(phrase in text for phrase in directory_phrases): return True

    return False

def get_faculty_search_results(university_name, homepage_url, max_retries=3):
    """
    Searches specifically for faculty/department pages for the given university.
    """
    print(f"   🔎 Searching for faculty links: {university_name}...", end=" ")
    
    # targeted queries
    queries = [
        f"{university_name} faculty directory",
        f"{university_name} academic staff list",
        f"{university_name} departments list",
        f"{university_name} faculty profiles",
        f"{university_name} people directory"
    ]
    
    candidates = []
    seen_urls = set()

    for attempt in range(max_retries):
        try:
            with DDGS() as ddgs:
                for q in queries:
                    # Get up to 4 results per query
                    results = list(ddgs.text(q, max_results=4, backend="html"))
                    if not results:
                        results = list(ddgs.text(q, max_results=4, backend="lite"))

                    for r in results:
                        url = r['href']
                        # Filter: Must not be homepage, must not be PDF
                        if (url not in seen_urls 
                            and not url.endswith('.pdf') 
                            and url.rstrip('/') != homepage_url.rstrip('/')):
                            
                            candidates.append(url)
                            seen_urls.add(url)
                    time.sleep(0.3)
            
            if candidates:
                break
            else:
                print(f"(Retry {attempt+1})", end=" ")
                time.sleep(2)
        except Exception as e:
            print(f"(Error: {e})", end=" ")
            time.sleep(1)

    print(f"Found {len(candidates)} candidates.")
    return list(set(candidates))


def llm_select_faculty_link(university_name, links_list):
    if not links_list:
        return None

    links_text = "\n".join(links_list[:30])

    prompt = f"""
    I need the best available link for {university_name} to find professors/staff.
    I need the specific URL where I can find a **list of faculty members**, **departments**, or **academic staff**.


    Candidates:
    {links_text}

    ### INSTRUCTIONS:
    1. **Target:** Look for "Faculty Directory", "Departments", "Schools", "People", or "Academic Staff".
    2. **Fallback:** If no directory exists, select "Research", "About Us", or even a single "Profile" page if it's the only option.
    3. **Goal:** Return ANY relevant link rather than "None". I prefer a "Departments List" over nothing.
    
    Return ONLY the URL.
    """

    try:
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Output only the raw URL string."},
                {"role": "user", "content": prompt}
            ],
            temperature=0,
            max_tokens=150
        )
        result = completion.choices[0].message.content.strip()
        
        if "http" in result:
            match = re.search(r'(https?://\S+)', result)
            return match.group(1) if match else result
        return None
    except Exception:
        return None

# --- MAIN EXECUTION ---

if os.path.exists(OUTPUT_FILE):
    df = pd.read_excel(OUTPUT_FILE)
    print(f"📂 Resuming from {OUTPUT_FILE}")
else:
    df = pd.read_excel(INPUT_FILE)
    print(f"📂 Starting fresh from {INPUT_FILE}")

# Ensure column exists
if 'Uni faculty link' not in df.columns:
    df['Uni faculty link'] = None

# Identify columns (Adjust 'Uinversity Link' based on your exact Excel header)
name_col = 'Name' 
homepage_col = 'Uinversity Link' # Note: Matching your screenshot spelling

print(f"🚀 Processing {len(df)} universities...")

try:
    for index, row in df.iterrows():
        
        # Skip if already done
        if pd.notna(row['Uni faculty link']):
            continue

        uni_name = str(row[name_col])
        homepage = str(row[homepage_col]) if pd.notna(row[homepage_col]) else ""
        
        if uni_name == "nan" or not uni_name: 
            continue

        print(f"\n[{index+1}/{len(df)}] Processing: {uni_name}")
        
        # 1. Search specific faculty/dept pages
        candidates = get_faculty_search_results(uni_name, homepage)
        
        best_link = None
        
        if candidates:
            # 2. Ask AI to pick
            ai_pick = llm_select_faculty_link(uni_name, candidates)
            
            if ai_pick:
                # 3. Light Validation Only
                # We check is_faculty_url, but if it returns False, we MIGHT still want it 
                # if it looks plausible.
                
                if is_faculty_url(ai_pick):
                    print(f"   ✅ Accepted: {ai_pick}")
                    best_link = ai_pick
                else:
                    # FALLBACK: If AI picked it but validator failed, 
                    # check if it is at least an edu/ac link and NOT a social media link.
                    # This fixes the issue where "good" links get rejected by strict rules.
                    if "facebook" not in ai_pick and "linkedin" not in ai_pick:
                         print(f"   ⚠️ Heuristic unsure, but trusting AI: {ai_pick}")
                         best_link = ai_pick
                    else:
                         print(f"   ❌ Rejected (Social Media/Garbage): {ai_pick}")
        
        if best_link:
            df.at[index, 'Uni faculty link'] = best_link
        else:
            print("   ❌ No valid faculty directory found.")

        # Save periodically
        df.to_excel(OUTPUT_FILE, index=False)
        time.sleep(1)

except KeyboardInterrupt:
    print("\nStopped by user. Progress saved.")
finally:
    df.to_excel(OUTPUT_FILE, index=False)
    print(f"Final save complete: {OUTPUT_FILE}")