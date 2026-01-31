from bs4 import BeautifulSoup, Tag
from typing import List, Optional, Dict
from collections import Counter
import logging

logger = logging.getLogger(__name__)

class VisualSelectorGenerator:
    """
    Reverse-engineers CSS selectors using visual anchors (names) extracted by Vision LLM.
    
    Algorithm:
    1. Find elements containing the sample names in the HTML.
    2. Analyze the DOM path of these elements.
    3. Calculate the usage frequency of classes/tags.
    4. Generate a 'Least Common Ancestor' style selector pattern.
    """
    
    def generate_from_names(self, html: str, sample_names: List[str]) -> Optional['SelectorStrategy']:
        """
        Generate a SelectorStrategy from sample names.
        
        Args:
            html: Page HTML
            sample_names: List of names seen in the screenshot
            
        Returns:
            SelectorStrategy object if successful, else None
        """
        from insti_scraper.core.selector_strategies import SelectorStrategy
        
        soup = BeautifulSoup(html, 'html.parser')
        
        # 1. Locate elements for each name
        hits = []
        for name in sample_names:
            el = self._find_best_match_element(soup, name)
            if el:
                hits.append(el)
        
        if len(hits) < 2:
            logger.warning(f"   [SelectorGen] Too few visual anchors found in DOM ({len(hits)}/{len(sample_names)})")
            return None
            
        # 2. Analyze common pattern from hits
        try:
            container_sel, name_sel = self._derive_pattern(hits)
            
            if not container_sel or not name_sel:
                return None
                
            # 3. Create Strategy
            strategy = SelectorStrategy(
                name="visual_heuristic",
                container=container_sel,
                name_selector=name_sel,
                title_selector=".title, .position, .role, p", # Generic fallbacks
                email_selector="a[href^='mailto:']",
                link_selector="a", # Contextual from container
                priority=0 # High priority as it's custom generated
            )
            
            logger.info(f"   [SelectorGen] Generated: '{container_sel}' -> '{name_sel}'")
            return strategy
            
        except Exception as e:
            logger.error(f"   [SelectorGen] Failed to derive pattern: {e}")
            return None

    def _find_best_match_element(self, soup: BeautifulSoup, text: str) -> Optional[Tag]:
        """Find the deepest element containing the exact text."""
        # Clean text
        text = text.strip()
        if not text: return None
        
        # Try exact text match first
        # We search for elements that contain the text
        elements = soup.find_all(string=lambda t: t and text.lower() in t.lower())
        
        best_el = None
        max_depth = -1
        
        for text_node in elements:
            parent = text_node.parent
            # We want the element that creates the "box" for the name, usually an <a>, <h3>, <span>, <div>
            # Heuristic: Go up until we find a block-level or significant inline element
            curr = parent
            depth = 0
            while curr and curr.name not in ['body', 'html']:
                # Prefer headers or links as "Name" containers
                if curr.name in ['h1','h2','h3','h4','a','strong','b']:
                    if depth > max_depth:
                        max_depth = depth
                        best_el = curr
                    break
                curr = curr.parent
                depth += 1
                
            # If we didn't find a specific header/link, just take the direct parent
            if not best_el:
                best_el = parent
                
        return best_el

    def _derive_pattern(self, elements: List[Tag]) -> tuple[str, str]:
        """
        Derive common container and name selector from a list of elements.
        
        Returns:
            (container_selector, name_selector_relative_to_container)
        """
        # A. Find Common Ancestor (Container)
        # We need to find a 'card' or 'row'.
        # Look at parents of all hits.
        
        parent_counts = Counter()
        
        # Store paths for each element
        paths = []
        
        for el in elements:
            # Get path: html > body > div.foo > ul > li.card > h3
            path = []
            curr = el
            while curr and curr.name != 'body':
                classes = ".".join(curr.get('class', []))
                tag = curr.name
                signature = f"{tag}.{classes}" if classes else tag
                path.append(signature)
                curr = curr.parent
            paths.append(list(reversed(path)))
            
        # B. Identify the Repeating Unit
        # We look for the level where the path diverges.
        # e.g.
        # P1: ... > ul > li:nth-child(1) > h3
        # P2: ... > ul > li:nth-child(2) > h3
        # Divergence is at 'li'. So 'li' is the container.
        
        # Simple algorithm: Scan down from root until paths differ
        min_len = min(len(p) for p in paths)
        divergence_index = 0
        
        for i in range(min_len):
            segments = [p[i] for p in paths]
            # Check if all segments are mostly same (allow some variance like odd/even rows)
            # Actually, standard DOM paths won't contain :nth-child info in this string rep
            # So if they look identical like 'tr.odd' and 'tr.even', we manually Normalize them
            
            # For robustness, let's just use the IMMEDIATE PARENT that is common to all
            # But "immediate common parent" is the List container (ul), not the Item container (li)
            # We want the Item container.
            
            if len(set(segments)) > 1:
                divergence_index = i
                break
            divergence_index = i
            
        # The item container is usually the child at the divergence point (or the last common one??)
        # Actually, for a list of items:
        # P1: [div.list, div.card_1, h3]
        # P2: [div.list, div.card_2, h3]
        # Divergence is at index 1. So index 1 is the Item Container.
        
        # We'll use the tag + class of the element at divergence_index
        # But wait, looking at 'paths' list above, distinct elements will likely have same 'tag.class' signature
        # unless classes differ.
        
        # Better approach:
        # Go UP from each element until we hit a parent that is NOT common to all other elements (but its parent IS common).
        # OR: Just take the parent of the name element, or grandparent, and see which one repeats most frequently across the page but covers our hits.
        
        # Simplest Heuristic for V1:
        # Use the name element's direct class as the name selector.
        # Use the name element's standard textual tag (h3, h4, a) pattern.
        
        # 1. Determine Name Selector (e.g., "h3.name" or ".profile-link")
        # Check if all hits share a class
        common_classes = set(elements[0].get('class', []))
        for el in elements[1:]:
            common_classes &= set(el.get('class', []))
            
        name_tag = elements[0].name
        name_sel = name_tag
        if common_classes:
            # Pick the most specific-looking class (longest?)
            best_cls = max(common_classes, key=len)
            name_sel = f"{name_tag}.{best_cls}"
            
        # 2. Determine Container
        # Go up 1-3 levels and find the "repeating item" wrapper
        # The container should be an element that contains the name, 
        # AND there are many such elements on the page (siblings).
        
        container_sel = None
        
        sample_el = elements[0]
        curr = sample_el.parent
        depth = 0
        while curr and depth < 4:
            # Check siblings of curr
            # If curr has many siblings with same tag/class, it is likely the container
            siblings = curr.find_next_siblings(curr.name) + curr.find_previous_siblings(curr.name)
            
            # Check if these siblings look similar (share classes)
            sim_siblings = 0
            my_classes = set(curr.get('class', []))
            
            for sib in siblings:
                sib_classes = set(sib.get('class', []))
                # Logic: if my_classes is subset of sib_classes or vice versa, or exact match
                if not my_classes:
                     if not sib_classes: sim_siblings += 1
                elif my_classes & sib_classes:
                    sim_siblings += 1
            
            if sim_siblings >= 2: # At least 2 similar siblings -> This is likely the Row/Card
                # Construct selector
                # If it has a class, use it
                if my_classes:
                    # Filter out helper classes
                    valid_cls = [c for c in my_classes if c not in ['even','odd','first','last','active']]
                    if valid_cls:
                        # Use the most descriptive class
                        best_cont_cls = max(valid_cls, key=len)
                        container_sel = f"{curr.name}.{best_cont_cls}"
                    else:
                        container_sel = curr.name # Fallback to just tag (e.g. 'tr')
                else:
                    container_sel = curr.name
                    
                # If we found a container, we break
                # BUT, check specificity. 'div' is too generic.
                if container_sel == 'div' or container_sel == 'span':
                    # Try to include parent context?? 
                    # For V1, accept risk or go up one more level?
                    # Let's verify if 'div' container works by counting matches?
                    pass 
                
                break
                
            curr = curr.parent
            depth += 1
            
        if not container_sel:
            # Fallback: Just use body as container (bad practice but works for name_sel global search)
            # Better: use a generic "list-item" heuristic
            return None, None
            
        # Refine relative name selector
        # If container is ".card" and name is ".card h3", relative is "h3"
        # Since we are using BeautifulSoup select(), we need the relative path from container.
        
        # However, our selector logic is usually `container.select_one(name_sel)`
        # So `name_sel` should be `h3` or `.name` (descendant).
        # We already calculated `name_sel` as `h3.someclass`. This works as a descendant selector.
        
        return container_sel, name_sel

# Global instance
visual_selector_generator = VisualSelectorGenerator()
