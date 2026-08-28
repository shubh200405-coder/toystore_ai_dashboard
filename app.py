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

DASHBOARD_CONTEXT = """
The Power BI dashboard has 5 pages:

1. Executive Overview: Gross Revenue, Net Revenue, Total Products, Total Customers,
   Total Items Purchased KPIs; Net Revenue Trend chart; Gross Revenue vs COGS Trend chart;
   Gross Revenue vs Net Revenue by year; Orders vs Average Order Value by year.

2. Marketing Performance: Total Sessions, Total Page Views, Page Per Sessions,
   Engaged Session Rate, Revenue Per Session KPIs; Revenue by Marketing Source;
   Sessions by Device Type; Revenue by Marketing Campaign; Marketing Source
   Performance table; Total Orders by Device Type.

3. Website Funnel & Conversion: Total Sessions, Product Sessions, Cart Sessions,
   Total Orders, Conversion Rate KPIs; Website Conversion Funnel (Sessions ->
   Product -> Cart -> Shipping -> Billing -> Orders); Conversion Rate by
   Marketing Source; Device Conversion Performance.

4. Product & Profitability: Total Revenue, Total Profit, Profit Margin %,
   Avg Order Value, Total Orders KPIs; Profit by Product; Revenue vs Profit
   by Product; Annual Profit Trend by Product; Profit Margin by Product.

5. Customer & Refund Intelligence: Unique Customers, Repeat Customer Rate,
   Average Order Value, Refund Rate, Refund Amount KPIs; Monthly Refund Trend;
   Refund Amount by Product; Average Order Value by Customer Type; Customers
   by Customer Type; Refund Rate by Product.
"""

# ---------------------------------------------------------------------------
# AI AGENT — question -> SQL -> run -> plain-language answer
# ---------------------------------------------------------------------------
@st.cache_resource
def get_model():
    api_key = os.environ.get("GEMINI_API_KEY") or st.secrets.get("GEMINI_API_KEY", None)
    if not api_key:
        return None
    genai.configure(api_key=api_key)

    # Try a few model names in case one isn't available on this API key/project
    for name in ["gemini-2.5-flash", "gemini-flash-latest", "gemini-2.0-flash", "gemini-1.5-flash"]:
        try:
            model = genai.GenerativeModel(name)
            model.generate_content("ping")  # quick check that this model works
            return model
        except Exception:
            continue
    return None


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
        return ("⚠️ GEMINI_API_KEY is not set. Get a free key from "
                "https://aistudio.google.com/apikey, then add it to your "
                "environment variable or Streamlit secrets.")

    # Step 1: let the model decide — does this need a data query, or is it a
    # general question about the dashboard (like summarizing a page)?
    router_prompt = f"""You are an analytics assistant for a toy store's Power BI dashboard.

{DASHBOARD_CONTEXT}

{SCHEMA_DESCRIPTION}

The user asked: "{question}"

Decide how to respond:
- If the question needs actual numbers from the data (totals, trends, comparisons,
  rates, etc.), respond with exactly:
  SQL: <one DuckDB SQL query, no markdown fences, no explanation>
- If the question is about summarizing or explaining a dashboard page, a KPI's
  meaning, or anything that doesn't need a fresh number, respond with exactly:
  ANSWER: <your answer in 3-6 short sentences, plain language>

Only output one of these two formats, nothing else.
"""
    router_response = model.generate_content(router_prompt)
    raw = router_response.text.strip()

    if raw.upper().startswith("SQL:"):
        sql_query = clean_sql(raw.split(":", 1)[1])

        try:
            result_df = con.execute(sql_query).fetchdf()
        except Exception as e:
            return f"There was an error running the query: {e}\n\nGenerated SQL:\n```sql\n{sql_query}\n```"

        explain_prompt = f"""Question: "{question}"
SQL used: {sql_query}
Result (as a table): {result_df.to_string(index=False)}

Answer the question in 2-4 short sentences, in simple plain language,
citing the actual numbers from the result. Do not repeat the SQL.
"""
        explain_response = model.generate_content(explain_prompt)
        explanation = explain_response.text.strip()
        return explanation + f"\n\n<details><summary>SQL used</summary>\n\n```sql\n{sql_query}\n```\n\n</details>"

    elif raw.upper().startswith("ANSWER:"):
        return raw.split(":", 1)[1].strip()

    else:
        # Fallback: just return whatever the model said
        return raw


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
    st.caption("Ask anything about your data — like 'refund rate by product' or 'summarize the executive overview page'")

    if "history" not in st.session_state:
        st.session_state.history = []

    for role, msg in st.session_state.history:
        with st.chat_message(role):
            st.markdown(msg)

    user_q = st.chat_input("Type your question...")
    if user_q:
        st.session_state.history.append(("user", user_q))
        with st.chat_message("user"):
            st.markdown(user_q)

        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                answer = ask_agent(user_q)
            st.markdown(answer)
        st.session_state.history.append(("assistant", answer))
