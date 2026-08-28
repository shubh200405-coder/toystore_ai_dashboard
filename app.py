"""
Toy Store AI Analytics — single-page app
Left  : Power BI dashboard (embedded via iframe)
Right : AI Agent that answers questions using the raw CSV data
        (turns your question into SQL, runs it with DuckDB, then
         explains the result in plain language using Gemini — FREE tier)

HOW TO RUN LOCALLY
------------------
1. pip install -r requirements.txt
2. Get a FREE Gemini API key from https://aistudio.google.com/apikey
   (sign in with Google account -> "Create API key" -> copy it, no card needed)
3. Set your Gemini API key:
   - Mac/Linux:  export GEMINI_API_KEY="AIza...."
   - Windows:    set GEMINI_API_KEY=AIza....
4. streamlit run app.py
5. Browser mein khulega http://localhost:8501 — yahi tumhara "ONE LINK" hai
   jab tum ise Streamlit Community Cloud pe deploy karoge.

DEPLOY (free, gives you one public link)
-----------------------------------------
1. Is poore folder (app.py, requirements.txt, data/) ko GitHub repo mein daalo.
2. https://share.streamlit.io par jao -> "New app" -> apna repo select karo.
3. "Secrets" mein GEMINI_API_KEY add karo (Settings -> Secrets).
4. Deploy karo -> ek single public URL milega. Yehi link sabko doge.
"""

import os
import streamlit as st
import pandas as pd
import duckdb
import streamlit.components.v1 as components
import google.generativeai as genai

# ---------------------------------------------------------------------------
# CONFIG — apna Power BI "Publish to web" link yahan daalo
# ---------------------------------------------------------------------------
POWER_BI_EMBED_URL = "https://app.powerbi.com/view?r=eyJrIjoiMGI1ZjE5ODEtYTdmMy00YmMzLWE0YjUtMmU4MDMzMGE2MDJkIiwidCI6ImM2ZTU0OWIzLTVmNDUtNDAzMi1hYWU5LWQ0MjQ0ZGM1YjJjNCJ9"

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

TABLE_FILES = {
    "orders": "orders.csv",
    "order_items": "order_items.csv",
    "order_item_refunds": "order_item_refunds.csv",
    "products": "products.csv",
    "website_sessions": "website_sessions.csv.gz",
    "website_pageviews": "website_pageviews.csv.gz",
}

st.set_page_config(page_title="Toy Store AI Analytics", layout="wide")

# ---------------------------------------------------------------------------
# LOAD DATA into an in-memory DuckDB database (fast, SQL-queryable)
# ---------------------------------------------------------------------------
@st.cache_resource
def get_db():
    con = duckdb.connect(database=":memory:")
    for table_name, filename in TABLE_FILES.items():
        path = os.path.join(DATA_DIR, filename)
        df = pd.read_csv(path)
        con.register(table_name, df)
        con.execute(f"CREATE TABLE {table_name} AS SELECT * FROM df")
    return con

con = get_db()

SCHEMA_DESCRIPTION = """
Tables available (all in a DuckDB database):

orders(order_id, created_at, website_session_id, user_id, primary_product_id,
       items_purchased, price_usd, cogs_usd)

order_items(order_item_id, created_at, order_id, product_id, is_primary_item,
            price_usd, cogs_usd)

order_item_refunds(order_item_refund_id, created_at, order_item_id, order_id,
                    refund_amount_usd)

products(product_id, created_at, product_name)

website_sessions(website_session_id, created_at, user_id, is_repeat_session,
                  utm_source, utm_campaign, utm_content, device_type, http_referer)

website_pageviews(website_pageview_id, created_at, website_session_id, pageview_url)
"""

# ---------------------------------------------------------------------------
# AI AGENT — question -> SQL -> run -> plain-language answer
# ---------------------------------------------------------------------------
def get_model():
    api_key = os.environ.get("GEMINI_API_KEY") or st.secrets.get("GEMINI_API_KEY", None)
    if not api_key:
        return None
    genai.configure(api_key=api_key)
    return genai.GenerativeModel("gemini-2.0-flash")


def clean_sql(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("sql"):
            text = text[3:]
    return text.strip()


def ask_agent(question: str) -> str:
    model = get_model()
    if model is None:
        return ("⚠️ GEMINI_API_KEY set nahi hai. https://aistudio.google.com/apikey "
                "se free key lo, phir environment variable ya Streamlit secrets mein daalo.")

    # Step 1: ask Gemini to write a DuckDB SQL query for the question
    sql_prompt = f"""You are a SQL analyst for an e-commerce toy store database.
{SCHEMA_DESCRIPTION}

Write ONE DuckDB SQL query that answers this question:
"{question}"

Rules:
- Return ONLY the SQL query, no explanation, no markdown fences.
- Use table/column names exactly as given above.
- created_at columns are timestamps; cast/extract as needed for date grouping.
"""
    sql_response = model.generate_content(sql_prompt)
    sql_query = clean_sql(sql_response.text)

    # Step 2: run the SQL
    try:
        result_df = con.execute(sql_query).fetchdf()
    except Exception as e:
        return f"Query chalane mein error aaya: {e}\n\nGenerated SQL tha:\n```sql\n{sql_query}\n```"

    # Step 3: ask Gemini to explain the result in plain language
    explain_prompt = f"""Question: "{question}"
SQL used: {sql_query}
Result (as a table): {result_df.to_string(index=False)}

Answer the question in 2-4 short sentences, in simple plain language (Hinglish is fine),
citing the actual numbers from the result. Do not repeat the SQL.
"""
    explain_response = model.generate_content(explain_prompt)
    explanation = explain_response.text.strip()

    return explanation + f"\n\n<details><summary>SQL used</summary>\n\n```sql\n{sql_query}\n```\n\n</details>"


# ---------------------------------------------------------------------------
# LAYOUT
# ---------------------------------------------------------------------------
st.title("🧸 Toy Store AI Analytics")

left, right = st.columns([1.4, 1])

with left:
    st.subheader("📊 Power BI Dashboard")
    components.iframe(POWER_BI_EMBED_URL, height=700, scrolling=True)

with right:
    st.subheader("🤖 AI Agent")
    st.caption("Apne data ke baare mein kuch bhi poocho — jaise 'refund rate by product' ya '2014 mein total revenue kitna tha'")

    if "history" not in st.session_state:
        st.session_state.history = []

    for role, msg in st.session_state.history:
        with st.chat_message(role):
            st.markdown(msg)

    user_q = st.chat_input("Apna sawaal likho...")
    if user_q:
        st.session_state.history.append(("user", user_q))
        with st.chat_message("user"):
            st.markdown(user_q)

        with st.chat_message("assistant"):
            with st.spinner("Soch raha hoon..."):
                answer = ask_agent(user_q)
            st.markdown(answer)
        st.session_state.history.append(("assistant", answer))
