ANALYZE_PAGE_PROMPT = """
You are a web scraper agent. Your task is to analyze the provided clean HTML and identify all interactive elements like links (<a>), buttons (<button>), and form inputs (<input>, <select>, <textarea>).
For each element, provide its text, a unique ID, and a robust CSS selector.
Return a JSON object with two keys:
1. "page_summary": A brief, one-sentence summary of the page's purpose.
2. "interactive_elements": A list of all identified interactive elements. Each element in the list should be a JSON object with the following keys: "id", "tag", "text", and "selector".

Here is the clean HTML:
{html}
"""

DEVISE_STRATEGY_PROMPT = """
You are a master web scraping strategist. Your goal is to create a complete, step-by-step plan to achieve the user's objective.
The plan should be returned as a single JSON object that can be parsed into a `ScrapingPlan` model.

**Objective:**
{objective}

**Page Context:**
This is the context from the starting URL. It includes a page summary and a list of interactive elements with their CSS selectors.
{context}

**Instructions:**
1.  Analyze the objective and the page context.
2.  Identify the repeating element that represents a single item to be scraped (e.g., a faculty member's card in a directory).
3.  Devise a series of steps to be performed on each of these items. This will form a loop.
4.  The steps inside the loop should typically include:
    a. Clicking a link to go to a detail page.
    b. Extracting the required information on the detail page.
    c. Navigating back to the main directory page to process the next item.
5.  If there is pagination, identify the selector for the "next page" button.
6.  Construct a final plan as a JSON object.

**Output Format:**
The output must be a JSON object with a "steps" key, which is a list of plan steps.
**Crucially, the `action` for each step MUST be one of the following literal strings: 'goto', 'click', 'type', 'extract_details', 'loop', 'go_back'. Do not invent new actions.**
Use the 'loop' action for iterating over faculty cards.
Inside the loop, define the steps to get to the detail page, extract data, and go back.

Example of a good plan:
```json
{{
  "steps": [
    {{
      "action": "loop",
      "selector": "div.faculty-card-class",
      "steps": [
        {{
          "action": "click",
          "selector": "a.profile-link-class"
        }},
        {{
          "action": "extract_details",
          "model_definition": {{
            "name": "h1.faculty-name",
            "title": "p.faculty-title",
            "email": "a.faculty-email"
          }}
        }},
        {{
          "action": "go_back"
        }}
      ]
    }}
  ]
}}
```

Now, create the plan for the given objective and context.
"""

GEMINI_ANALYSIS_PROMPT = """
You are a web scraping strategist specialized in university faculty directories.
You understand common CMS patterns used by universities including:
- Workday (used by many large universities)
- PeopleSoft (Oracle-based HR systems)
- Drupal/WordPress with directory plugins
- Custom React/Angular SPAs with JSON APIs
- Simple HTML tables and lists

**Current Objective:** {objective}
**Current URL:** {current_url}

Analyze the HTML and determine the best action. Look for these common patterns:

**Faculty List Patterns:**
- Cards with `.faculty-card`, `.person-card`, `.profile-card`
- Grid layouts with `.faculty-grid`, `.people-grid`
- Tables with faculty data
- Lists with `.faculty-list`, `.directory-list`
- React/Angular components with `data-*` attributes

**Pagination Patterns:**
- "Next" button with `.next`, `.pagination-next`, `[rel="next"]`
- "Load More" button with `.load-more`, `.show-more`
- Numbered pages with `.pagination`, `.pager`
- Infinite scroll (check for scroll triggers)

**Profile Link Patterns:**
- Links in name/title areas
- "View Profile" or "Read More" buttons
- Images that are clickable
- Cards that link to detail pages

Return a JSON object with:
{{
    "action": "NAVIGATE_TO_LIST" | "EXTRACT_LIST" | "EXTRACT_PROFILE" | "CLICK" | "FINISH",
    "args": {{
        "card_selector": "CSS selector for faculty cards/rows (if EXTRACT_LIST/NAVIGATE_TO_LIST)",
        "link_selector": "CSS selector for profile links within cards",
        "name_selector": "CSS selector for name element within cards",
        "title_selector": "CSS selector for title/position element within cards",
        "next_page_selector": "CSS selector for pagination (optional)",
        "load_more_selector": "CSS selector for load more button (optional)",
        "selector": "CSS selector for CLICK action",
        "url": "URL for NAVIGATE action"
    }},
    "reason": "Brief explanation of why this action was chosen",
    "detected_cms": "Detected CMS type if identifiable (Workday/Drupal/Custom/Unknown)",
    "faculty_count_estimate": "Estimated number of faculty visible on page"
}}

**IMPORTANT:**
- For NAVIGATE_TO_LIST or EXTRACT_LIST, you MUST provide: card_selector, link_selector, name_selector, title_selector
- Test selectors mentally - they should match actual elements in the HTML
- If you see JSON data in script tags, note it (might be a SPA)

HTML Content:
{html_content}
"""

GEMINI_CORRECTION_PROMPT = """
You are an expert web crawler agent. Your previous attempt to create an action plan was invalid. You must analyze your mistake and provide a corrected, valid JSON action plan.

**Objective:** {objective}
**Current URL:** {current_url}

**Your Previous Invalid Plan:**
```json
{invalid_plan}
```

**Reason it was Invalid:**
{failure_reason}

**Instructions:**
1.  Review the reason your last plan failed.
2.  Re-analyze the HTML content below.
3.  Provide a new, valid JSON response that corrects the mistake.
4.  The "action" key **MUST** be one of: 'NAVIGATE_TO_LIST', 'EXTRACT_PROFILE', 'CLICK', or 'FINISH'.
5.  All actions **MUST** include all of their required arguments. For example, 'CLICK' requires a 'selector'.

**HTML Content:**
```html
{html_content}
```

**Provide a new, valid JSON object.**
"""

OLLAMA_EXTRACTION_PROMPT = """
You are a data extraction machine. Your ONLY output is valid JSON - no explanations.

**Partial Profile Data (already extracted):**
```json
{partial_data}
```

**Professor's Profile Page Content:**
```text
{page_text_content}
```

**Task:** Complete the profile by extracting missing fields from the page content.

**Fields to extract:**
- name: Full name (First Last, no titles like Dr./Prof.)
- title: Job title/position (e.g., "Associate Professor of Computer Science")
- email: Email address (look for @university.edu patterns)
- research_interests: Array of research areas (split by commas or bullet points)
- publications: Array of recent publication titles (max 5)
- lab: Lab/research group name if mentioned
- description: 1-2 sentence bio if available
- image_url: Profile photo URL (look for img tags with profile/headshot in src)
- phone: Phone number if visible
- office: Office location/building

**Rules:**
1. Keep existing values from partial_data if the page doesn't have better info
2. Return ONLY fields that have actual values - omit null/empty fields
3. For arrays, return empty array [] if no items found
4. Clean up extracted text (remove extra whitespace, fix encoding)

**Return ONLY a JSON object, nothing else:**
"""

