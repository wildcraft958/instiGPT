import os
import time
import re
import requests
import pandas as pd
from dotenv import load_dotenv
from bs4 import BeautifulSoup
from groq import Groq
from openai import OpenAI
import cloudscraper

# =============================
# 1. ENV + CONFIG
# =============================

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY not set. Please set it in your .env file.")

client = OpenAI(api_key=OPENAI_API_KEY)

INPUT_EXCEL = "universities_with_faculty_part2.xlsx"
OUTPUT_EXCEL = "Copy-2026-QS-with-types-filled8b_part2.xlsx"
REVIEW_EXCEL = "faculty_type_needs_review_part2.xlsx"

FACULTY_COL = "Uni faculty link"
TYPE_COL = "Type"
NAME_COL = "Name"

# ====================================
# 2. FEATURE EXTRACTION (High Quality)
# ====================================

def fetch_html(url):
    """
    Uses cloudscraper to bypass Cloudflare/WAF protection.
    """
    scraper = cloudscraper.create_scraper()
    try:
        r = scraper.get(url, timeout=15)
        if r.status_code == 200:
            return r.text
        else:
            print(f"    [!] Blocked/Error? Status Code: {r.status_code}")
    except Exception as e:
        print(f"    [!] Connection Error: {e}")
    return None


def extract_features(html, url):
    if not html:
        return None

    soup = BeautifulSoup(html, "html.parser")
    
    # 1. Strip Noise
    for tag in soup(["script", "style", "header", "footer", "nav", "aside", "noscript"]):
        tag.decompose()
    
    # 2. Find Main Content
    main_content = soup.find("main") or soup.find("div", {"id": re.compile(r"content|main", re.I)}) or soup.find("div", {"role": "main"})
    content_root = main_content if main_content else soup.body

    # 3. Text Analysis
    if content_root:
        text_content = content_root.get_text(separator=' ', strip=True)
    else:
        text_content = ""

    text_lower = text_content.lower()
    page_title = soup.title.string.strip() if soup.title else "No Title"

    # 4. Link & Input Analysis
    all_links = soup.find_all("a", href=True)
    
    # "Profile" links (View Profile, Bio, People/xyz)
    profile_links = [a for a in all_links if "profile" in a['href'] or "bio" in a['href'] or "people/" in a['href']]
    
    # "Department" links (School of X, Dept of Y)
    dept_links = [a for a in all_links if "department" in a.text.lower() or "school" in a.text.lower() or "faculty of" in a.text.lower()]
    
    # "Search" inputs
    inputs = soup.find_all("input")
    search_inputs = [i for i in inputs if "search" in str(i).lower() or i.get("type") == "search"]

    # "Next Page" / "Page 1" for pagination
    has_pagination = "next >" in text_lower or "page 1 of" in text_lower or "previous" in text_lower

    # EXTENDED KEYWORD LISTS
    # 1. Academic Roles (Global variations)
    role_terms = [
        "professor", "lecturer", "instructor", "adjunct", "faculty", 
        "reader", "fellow","Chair", "associate", "assistant", 
        "academic staff", "investigator", "scientist"
    ]
    
    # 2. Contact Information
    contact_terms = [
        "email", "@", "phone", "tel:", "contact", 
        "office", "room", "location"
    ]
    
    # 3. Research & Output
    research_terms = [
        "research", "publication", "interest", "expertise", 
        "biography", "bio", "curriculum vitae", 
        "selected works", "project"
    ]
    
    # 4. Blocking / Error Messages (Cloudflare, Incapsula, Akamai, etc.)
    block_terms = [
        "access denied", "security check", "cloudflare", "captcha", 
        "403 forbidden", "incapsula", "imperva", "human verification", 
        "shield", "firewall", "robot", "automated request"
    ]

    features = {
        "page_title": page_title,
        "text_preview": text_content[:5000],
        "text_length": len(text_content),
        "img_count": len(soup.find_all("img")),
        "profile_link_count": len(profile_links),
        "dept_link_count": len(dept_links),
        "link_count": len(all_links),
        "has_search_bar": len(search_inputs) > 0,
        "has_pagination": has_pagination,
        "keywords": {
                "professor": sum(text_lower.count(t) for t in role_terms),
                "email": sum(text_lower.count(t) for t in contact_terms),
                "research": sum(text_lower.count(t) for t in research_terms),
                "blocked": any(t in text_lower or t in page_title.lower() for t in block_terms)
        }
    }

    return features


# =============================
# 3. RULE-BASED CLASSIFIER (Hybrid Logic)
# =============================

def rule_based_classify(features):
    """
    Returns (Predicted_Type, Confidence_Score)
    Confidence > 0.8 means we trust the rule and skip LLM.
    Confidence < 0.7 means we ask LLM.
    """
    if not features:
        return "Z", 0.0

    # --- RULE 1: Blocked/Junk Detection (Z) ---
    if features["keywords"]["blocked"]:
        return "Z", 0.95  # High confidence it's junk/blocked
    
    if features["text_length"] < 200:
        return "Z", 0.6   # Too short, probably junk, but let LLM confirm

    # --- RULE 2: Department Gateway (C) ---
    # Many links to "School of..." or "Dept of..." and few actual profiles
    if features["dept_link_count"] > 8 and features["profile_link_count"] < 5:
        return "C", 0.9

    # --- RULE 3: Search/Interactive (E) ---
    # Search bar exists, very few links, low text content
    if features["has_search_bar"] and features["link_count"] < 15 and features["keywords"]["professor"] < 3:
        return "E", 0.85

    # --- RULE 4: Segmented Directory (D) ---
    # Explicit pagination keywords found
    if features["has_pagination"]:
        return "D", 0.85

    # --- RULE 5: Profile Directory (A/B) ---
    # Lots of "Profile" links or lots of "Professor" keywords
    if features["profile_link_count"] > 10:
        return "A", 0.8  # Likely a list of profiles (Type A)
    
    if features["keywords"]["professor"] > 5 and features["keywords"]["email"] > 5:
        return "B", 0.75 # Lots of data on page (Type B), but let LLM verify context

    # --- DEFAULT: Low Confidence ---
    return "Z", 0.3


# =============================
# 4. LLM VALIDATOR (Fallback)
# =============================

def llm_validate(university, url, features):
    prompt = f"""
You are a scraping architect. Classify this university webpage based on the text preview.

Target: {university}
Title: {features['page_title']}
Text Preview: "{features['text_preview']}..."

**RULES FOR CLASSIFICATION:**
1. **Type C (Department List)**: List of "Departments", "Schools", "Faculties".
2. **Type E (Search/Filters)**: Search bar, "Filter by", empty list needing interaction.
3. **Type D (A-Z/Directory)**: "A-Z Listing", "Page 1 of...", pagination.
4. **Type F (Lab/Personal Site)**: "Welcome to [Name] Lab", "Principal Investigator", "Our Team".
5. **Type A (Profile Links)**: List of names where you MUST click "View Profile" to see details.
6. **Type B (Full Info)**: Emails and Research Interests are visible RIGHT HERE on this page.
7. **Type Z (Junk)**: Login, 404, Access Denied, News, General Home.

**DECISION:**
Return ONLY the single letter (A, B, C, D, E, F, or Z).
"""
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini", # "meta-llama/llama-4-scout-17b-16e-instruct" ("llama-3.3-70b-versatile"# Using smart model)
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_completion_tokens=5
        )
        return response.choices[0].message.content.strip().upper()
    except Exception as e:
        # print(f"  > LLM Error: {e}")
        return "Z"


# =============================
# 5. MAIN PIPELINE
# =============================

def main():
    print(f"Reading {INPUT_EXCEL}...")
    df = pd.read_excel(INPUT_EXCEL)

    if TYPE_COL not in df.columns:
        df[TYPE_COL] = ""

    processed_count = 0
    review_rows = []

    # print("Starting Hybrid Classification...")

    try:
        for idx, row in df.iterrows():
            try:
                faculty_url = str(row.get(FACULTY_COL, "")).strip()
                university = str(row.get(NAME_COL, "")).strip()

                if not faculty_url.lower().startswith("http"):
                    continue

                print(f"[{idx+1}/{len(df)}] {university}")

                # 1. Fetch & Extract
                html = fetch_html(faculty_url)
                if not html:
                    print("  > Fetch failed (Type Z)")
                    df.at[idx, TYPE_COL] = "Z"
                    continue

                features = extract_features(html, faculty_url)

                # 2. Rule-Based Classification
                rule_type, confidence = rule_based_classify(features)
                final_type = rule_type
                used_llm = False

                # 3. Hybrid Logic: Use LLM if confidence is low
                # We also force LLM if Rule says "Z" but we aren't 100% sure, to double check
                if confidence < 0.75 and features is not None:
                    try:
                        llm_type = llm_validate(university, faculty_url, features)
                        
                        # Sanity check LLM output
                        if llm_type in ["A", "B", "C", "D", "E", "F", "Z"]:
                            final_type = llm_type
                            used_llm = True
                    except Exception:
                        final_type = rule_type

                # print(f"  > Result: {final_type} (Rule: {rule_type} @ {confidence})")
                
                df.at[idx, TYPE_COL] = final_type

                # Log tricky rows for manual review
                if used_llm and confidence < 0.5:
                    review_rows.append({
                        "Name": university,
                        "URL": faculty_url,
                        "Rule": rule_type,
                        "Final": final_type,
                        "Conf": confidence
                    })

                processed_count += 1

                # Checkpoint Save
                if processed_count % 50 == 0:
                    print(f"  >> Saving checkpoint at row {idx+1}...")
                    df.to_excel(OUTPUT_EXCEL, index=False)

                time.sleep(0.5)

            except Exception as row_error:
                print(f"  !!! CRITICAL ERROR on row {idx}: {row_error}")
                continue

    except KeyboardInterrupt:
        print("\n\nUser interrupted!")

    # Final Save
    print("\nFinalizing...")
    df.to_excel(OUTPUT_EXCEL, index=False)
    
    if review_rows:
        pd.DataFrame(review_rows).to_excel(REVIEW_EXCEL, index=False)
        print(f"Saved review file: {REVIEW_EXCEL}")

    print(f"Saved main file: {OUTPUT_EXCEL}")
    print("Done.")

if __name__ == "__main__":
    main()