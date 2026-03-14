import re
import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="Keyword / Entity Coverage Analyzer",
    layout="wide"
)

st.title("📊 Keyword / Entity Coverage Analyzer")
st.write("Analyze Arabic keyword and entity coverage inside Arabic content after normalization.")

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
    coverage_percent = round(
        (found_count / total_keywords) * 100, 2) if total_keywords > 0 else 0.0

    missing_keywords = df_results[df_results["found"]
                                  == False]["keyword"].tolist()
    weak_keywords = df_results[
        (df_results["found"] == True) & (df_results["frequency"] == 1)
    ]["keyword"].tolist()

    return df_results, total_keywords, found_count, missing_count, coverage_percent, missing_keywords, weak_keywords


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

if st.button("Analyze Coverage"):
    if not content_input.strip():
        st.warning("Please add content in the Content box.")
    elif not keywords_input.strip():
        st.warning(
            "Please add target keywords in the Keywords box, one per line.")
    else:
        df_results, total_keywords, found_count, missing_count, coverage_percent, missing_keywords, weak_keywords = analyze_coverage(
            content_input, keywords_input
        )

        st.subheader("Summary")

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total Keywords", total_keywords)
        col2.metric("Found", found_count)
        col3.metric("Missing", missing_count)
        col4.metric("Coverage %", f"{coverage_percent}%")

        st.markdown("---")

        col_a, col_b = st.columns(2)

        with col_a:
            st.write("**Missing Keywords**")
            if missing_keywords:
                st.write(missing_keywords)
            else:
                st.success("None")

        with col_b:
            st.write("**Weak Keywords (appear only once)**")
            if weak_keywords:
                st.write(weak_keywords)
            else:
                st.success("None")

        st.markdown("---")
        st.subheader("Detailed Results")
        st.dataframe(df_results, use_container_width=True)

        csv_data = df_results.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            label="Download Results as CSV",
            data=csv_data,
            file_name="keyword_entity_coverage_report.csv",
            mime="text/csv"
        )
