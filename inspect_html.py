from bs4 import BeautifulSoup

with open("page.html", "r", encoding="utf-8") as f:
    html = f.read()

soup = BeautifulSoup(html, "html.parser")

# Find the Lori Setton element
name_el = soup.find("h3", string="Lori Setton")
if name_el:
    print(f"Name Tag: {name_el.name}, Class: {name_el.get('class')}")
    parent = name_el.find_parent()
    print(f"Parent Tag: {parent.name}, Class: {parent.get('class')}")
    grandparent = parent.find_parent()
    print(f"Grandparent Tag: {grandparent.name}, Class: {grandparent.get('class')}")
    
    # Check for link
    link = parent.find("a")
    if link:
        print(f"Link found: {link['href']}")
    else:
        print("No link in parent")
        
    # Check for title
    # Title is usually near the name
    print(parent.prettify())

else:
    print("Lori Setton not found via BS4")
