import os
import time
import streamlit as st
import pandas as pd
import duckdb
import google.generativeai as genai
from google.api_core.exceptions import ResourceExhausted

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


@st.cache_resource
def get_model():
    api_key = os.environ.get("GEMINI_API_KEY") or st.secrets.get("GEMINI_API_KEY", None)
    if not api_key:
        return None
    genai.configure(api_key=api_key)
    return genai.GenerativeModel("gemini-3.6-flash")


def clean_sql(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("sql"):
            text = text[3:]
    return text.strip()


def call_gemini(prompt, retries=3, wait=15):
    """
    Wrapper around generate_content that retries on rate-limit errors
    instead of just crashing. Free tier quota runs out fast if you spam it,
    so this waits a bit and tries again a couple of times before giving up.
    """
    model = get_model()
    last_err = None
    for attempt in range(retries):
        try:
            return model.generate_content(prompt)
        except ResourceExhausted as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(wait)
        except Exception as e:
            last_err = e
            break
    raise last_err


def ask_agent(question: str) -> str:
    model = get_model()
    if model is None:
        return ("⚠️ GEMINI_API_KEY is not set. Get a free key from "
                "https://aistudio.google.com/apikey, then add it to your "
                "environment variable or Streamlit secrets.")

    # cache repeated questions in this session so we don't burn quota
    # asking Gemini the same thing twice
    cache = st.session_state.setdefault("answer_cache", {})
    if question in cache:
        return cache[question]

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
    try:
        router_response = call_gemini(router_prompt)
    except ResourceExhausted:
        return ("⚠️ The free Gemini quota is temporarily maxed out. "
                "Wait a minute and try again, or check your usage at "
                "https://aistudio.google.com/apikey.")
    except Exception as e:
        return f"⚠️ Could not reach the AI model right now. Error: {e}"

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
        try:
            explain_response = call_gemini(explain_prompt)
            explanation = explain_response.text.strip()
        except ResourceExhausted:
            explanation = ("⚠️ Got the data, but the free Gemini quota ran out before "
                            "I could explain it in words. The numbers are below anyway.")
        except Exception as e:
            explanation = f"⚠️ Got the data but couldn't generate an explanation. Error: {e}"

        answer = explanation + f"\n\n<details><summary>SQL used</summary>\n\n```sql\n{sql_query}\n```\n\n</details>"
        cache[question] = answer
        return answer

    elif raw.upper().startswith("ANSWER:"):
        answer = raw.split(":", 1)[1].strip()
        cache[question] = answer
        return answer

    else:
        return raw


st.title("🧸 Toy Store AI Analytics")

left, right = st.columns([1.4, 1])

with left:
    st.subheader("📊 Power BI Dashboard")
    st.iframe(POWER_BI_EMBED_URL, height=700)

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
