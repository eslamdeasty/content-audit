import re
import pandas as pd
import streamlit as st
import requests
from bs4 import BeautifulSoup

# Optional Playwright import
try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except Exception:
    PLAYWRIGHT_AVAILABLE = False


st.set_page_config(
    page_title="Keyword / Entity Coverage Analyzer",
    layout="wide"
)

# ---------------------------
# Arabic Normalization
# ---------------------------

arabic_diacritics = re.compile(r"""
    ّ    | # Tashdid
    َ    | # Fatha
    ً    | # Tanwin Fath
    ُ    | # Damma
    ٌ    | # Tanwin Damm
    ِ    | # Kasra
    ٍ    | # Tanwin Kasr
    ْ    | # Sukun
    ـ      # Tatwil/Kashida
""", re.VERBOSE)


def normalize_arabic(text):
    if not isinstance(text, str):
        text = str(text)

    text = re.sub(arabic_diacritics, "", text)
    text = re.sub("[إأآاٱ]", "ا", text)
    text = text.replace("ى", "ي")
    text = text.replace("ـ", "")
    text = re.sub("[،؛؟…]", " ", text)
    text = re.sub(r"[^\w\s]", " ", text)
    text = text.lower()
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ---------------------------
# Content Extraction
# ---------------------------

def extract_text_from_html(html):
    soup = BeautifulSoup(html, "lxml")

    for tag in soup(["script", "style", "noscript", "iframe", "svg"]):
        tag.decompose()

    # Prefer semantic content containers if available
    preferred_selectors = [
        "article",
        "main",
        "[role='main']",
        ".article-body",
        ".post-content",
        ".entry-content",
        ".content",
        ".article-content"
    ]

    for selector in preferred_selectors:
        node = soup.select_one(selector)
        if node:
            text = node.get_text(separator=" ", strip=True)
            text = re.sub(r"\s+", " ", text).strip()
            if len(text) > 200:
                return text

    # Fallback to whole page text
    text = soup.get_text(separator=" ", strip=True)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def fetch_with_requests(url):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/133.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9,ar;q=0.8"
    }

    response = requests.get(url, headers=headers, timeout=25, allow_redirects=True)
    response.raise_for_status()

    html = response.text
    text = extract_text_from_html(html)

    soup = BeautifulSoup(html, "lxml")
    title = soup.title.get_text(strip=True) if soup.title else ""

    return {
        "method": "requests",
        "url": response.url,
        "title": title,
        "content": text,
        "status_code": response.status_code
    }


def fetch_with_playwright(url):
    if not PLAYWRIGHT_AVAILABLE:
        raise RuntimeError("Playwright is not installed or not available in this environment.")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-dev-shm-usage"])
        page = browser.new_page()
        page.goto(url, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(2000)

        html = page.content()
        final_url = page.url
        title = page.title()

        browser.close()

    text = extract_text_from_html(html)

    return {
        "method": "playwright",
        "url": final_url,
        "title": title,
        "content": text,
        "status_code": None
    }


def fetch_page_content(url, allow_playwright_fallback=True):
    """
    Strategy:
    1) Try requests first
    2) If content looks too thin and Playwright is allowed, fallback to Playwright
    """
    requests_error = None

    try:
        result = fetch_with_requests(url)

        # If content is enough, keep it
        if len(result["content"]) >= 300:
            return result

        # If content is too thin, maybe JS page
        if allow_playwright_fallback and PLAYWRIGHT_AVAILABLE:
            try:
                pw_result = fetch_with_playwright(url)
                if len(pw_result["content"]) > len(result["content"]):
                    return pw_result
            except Exception:
                pass

        return result

    except Exception as e:
        requests_error = e

    # If requests failed, try Playwright fallback
    if allow_playwright_fallback and PLAYWRIGHT_AVAILABLE:
        try:
            return fetch_with_playwright(url)
        except Exception as pw_error:
            raise RuntimeError(
                f"Requests failed: {requests_error} | Playwright fallback failed: {pw_error}"
            )

    raise RuntimeError(f"Requests failed and no Playwright fallback available: {requests_error}")


# ---------------------------
# Keyword Analysis
# ---------------------------

def analyze_coverage(raw_content, raw_keywords):
    content_clean = normalize_arabic(raw_content)

    target_keywords = [
        normalize_arabic(line)
        for line in raw_keywords.split("\n")
        if line.strip()
    ]

    results = []

    for keyword in target_keywords:
        freq = content_clean.count(keyword)
        first_pos = content_clean.find(keyword)
        found = freq > 0

        results.append({
            "keyword": keyword,
            "found": found,
            "frequency": freq,
            "first_position": first_pos if found else None
        })

    df_results = pd.DataFrame(results)

    total_keywords = len(df_results)
    found_count = int(df_results["found"].sum()) if total_keywords > 0 else 0
    missing_count = total_keywords - found_count
    coverage_percent = round((found_count / total_keywords) * 100, 2) if total_keywords > 0 else 0.0

    missing_keywords = df_results[df_results["found"] == False]["keyword"].tolist()
    weak_keywords = df_results[
        (df_results["found"] == True) & (df_results["frequency"] == 1)
    ]["keyword"].tolist()

    return {
        "df_results": df_results,
        "total_keywords": total_keywords,
        "found_count": found_count,
        "missing_count": missing_count,
        "coverage_percent": coverage_percent,
        "missing_keywords": missing_keywords,
        "weak_keywords": weak_keywords,
        "normalized_content": content_clean
    }


# ---------------------------
# Streamlit UI
# ---------------------------

st.title("📊 Keyword / Entity Coverage Analyzer")
st.write("Analyze keyword and entity coverage from pasted content or a live page URL.")

fetch_mode = st.radio(
    "Input Mode",
    ["Paste Content", "Fetch From URL"],
    horizontal=True
)

url_input = ""
content_input = ""

if fetch_mode == "Fetch From URL":
    url_input = st.text_input(
        "Page URL",
        placeholder="https://example.com/article"
    )

    st.caption(
        "The app tries requests + BeautifulSoup first, then uses Playwright only as a fallback if available."
    )
else:
    content_input = st.text_area(
        "Content",
        placeholder="Paste your content here (article, script, caption, etc.)",
        height=300
    )

keywords_input = st.text_area(
    "Keywords",
    placeholder="Enter your target keywords or entities here, one per line",
    height=220
)

show_normalized = st.checkbox("Show normalized content used for analysis", value=False)

analyze_button = st.button("Analyze Coverage", type="primary")

if analyze_button:
    if not keywords_input.strip():
        st.warning("Please add target keywords in the Keywords box, one per line.")
        st.stop()

    raw_content_to_analyze = ""
    page_meta = None

    if fetch_mode == "Fetch From URL":
        if not url_input.strip():
            st.warning("Please enter a valid page URL.")
            st.stop()

        try:
            with st.spinner("Fetching and extracting page content..."):
                page_meta = fetch_page_content(url_input.strip(), allow_playwright_fallback=True)
                raw_content_to_analyze = page_meta["content"]

            st.success(f"Page fetched successfully using {page_meta['method']}.")

            with st.expander("Fetched Page Details"):
                st.write(f"**Method used:** {page_meta['method']}")
                st.write(f"**Final URL:** {page_meta['url']}")
                st.write(f"**Title:** {page_meta['title'] or 'N/A'}")
                st.write(f"**Extracted characters:** {len(raw_content_to_analyze)}")
                if page_meta["status_code"] is not None:
                    st.write(f"**HTTP status:** {page_meta['status_code']}")

        except Exception as e:
            st.error(f"Failed to fetch page content: {e}")
            st.stop()

    else:
        raw_content_to_analyze = content_input

    if not raw_content_to_analyze.strip():
        st.warning("No content available for analysis.")
        st.stop()

    result = analyze_coverage(raw_content_to_analyze, keywords_input)

    st.subheader("Summary")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Keywords", result["total_keywords"])
    col2.metric("Found", result["found_count"])
    col3.metric("Missing", result["missing_count"])
    col4.metric("Coverage %", f"{result['coverage_percent']}%")

    st.markdown("---")

    col_a, col_b = st.columns(2)

    with col_a:
        st.write("**Missing Keywords**")
        if result["missing_keywords"]:
            st.write(result["missing_keywords"])
        else:
            st.success("None")

    with col_b:
        st.write("**Weak Keywords (appear only once)**")
        if result["weak_keywords"]:
            st.write(result["weak_keywords"])
        else:
            st.success("None")

    st.markdown("---")
    st.subheader("Detailed Results")
    st.dataframe(result["df_results"], use_container_width=True)

    if show_normalized:
        with st.expander("Normalized Content Used for Analysis"):
            st.text_area(
                "Normalized Content Preview",
                value=result["normalized_content"],
                height=300
            )

    csv_data = result["df_results"].to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        label="⬇ Download Results as CSV",
        data=csv_data,
        file_name="keyword_entity_coverage_report.csv",
        mime="text/csv"
    )
