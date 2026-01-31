# 🚀 Insti-Scraper: The "Simple Step" User Guide

Welcome! If you want to collect data about professors from universities but don't want to deal with complex coding, you've come to the right place. 

Follow these steps exactly, and you'll have your data in no time!

---

## 🏁 Step 0: What you need first
Before you start, make sure you have:
1.  **An OpenAI API Key**: This is the "brain" of the scraper. You get it from [OpenAI](https://platform.openai.com/).
2.  **Python**: If you don't have it, download it from [python.org](https://www.python.org/).

---

## 🛠️ Step 1: Getting Ready (Setup)

1.  **Open your Terminal** (or Command Prompt).
2.  **Download the project code** (if you haven't):
    ```bash
    git clone https://github.com/your-repo/instigpt.git
    cd insti-scraper
    ```
3.  **Install the magic tool (uv)**:
    ```bash
    curl -LsSf https://astral.sh/uv/install.sh | sh
    ```
    *(Wait for it to finish and restart your terminal if needed)*
4.  **Install everything**:
    ```bash
    make install
    ```

---

## 🔑 Step 2: Adding your API Key

The scraper needs your OpenAI key to work.
1.  Find the file named `.env.example` in the folder.
2.  Rename it to just `.env`.
3.  Open it in Notepad and change the line `OPENAI_API_KEY=...` to your real key.
    ```ini
    OPENAI_API_KEY=sk-proj-your-actual-key-here
    ```
4.  **Save the file.**

---

## 🏃‍♂️ Step 3: Running the Scraper

This is the fun part! Just tell it which university to scrape.

### A. The "I'm Feeling Lucky" Mode (Auto-Discover)
If you only know the university homepage, run this:
```bash
make run URL="https://www.stanford.edu"
```
*The scraper will automatically find the faculty list for you!* 🕵️‍♂️

### B. The "I Know Exactly Where It Is" Mode
If you have the exact link to a department's faculty list:
```bash
make direct URL="https://cs.stanford.edu/people/faculty"
```

### C. The "Link Hunter" Mode (Discovery Only)
If you want to see all the links the scraper found without actually scraping them yet:
```bash
make discover URL="https://www.mit.edu"
```

---

## 📊 Step 4: Seeing Your Results

Once it finishses, you probably want to see the data.

1.  **To see it in your terminal**:
    ```bash
    make list
    ```
2.  **To get a nice Excel/CSV file**:
    ```bash
    make csv FILE=my_data.csv
    ```
    *Now open `my_data.csv` in Excel!* 📈

---

## ❓ FAQ (Troubleshooting)

-   **"Command not found"**: Try putting `uv run` before your commands, or make sure you followed Step 1.
-   **"Quota Exceeded"**: Your OpenAI account ran out of credits. Add money to your OpenAI usage balance.
-   **"No faculty found"**: Sometimes university websites are like mazes. Try using the **Direct Mode** (Step 3B) with the exact link.

---

### 💡 Pro Tip
If it asks you to update something called "Playwright", just run:
```bash
uv run playwright install
```
