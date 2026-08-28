# Toy Store AI Analytics — Setup Guide

Ye app ek hi page pe do cheezein dikhata hai:
- **Left**: tumhara Power BI dashboard (embedded)
- **Right**: AI agent jo CSV data (orders, products, sessions, etc.) pe sawaalon
  ka jawab deta hai

## Folder structure
```
toy_store_app/
├── app.py
├── requirements.txt
├── README.md
└── data/
    ├── orders.csv
    ├── order_items.csv
    ├── order_item_refunds.csv
    ├── products.csv
    ├── website_sessions.csv
    └── website_pageviews.csv
```

## Step 1 — Local pe test karo

```bash
pip install -r requirements.txt
```

Apni **FREE** Gemini API key lo: [aistudio.google.com/apikey](https://aistudio.google.com/apikey)
→ Google account se sign in → "Create API key" → copy karo (koi card/payment nahi chahiye).

```bash
# Mac/Linux
export GEMINI_API_KEY="AIza...."

# Windows (cmd)
set GEMINI_API_KEY=AIza....
```

App chalao:

```bash
streamlit run app.py
```

Browser mein `http://localhost:8501` khulega — dono panel dikhenge.

## Step 2 — Ek single public link banao (free)

1. Is poore `toy_store_app` folder ko GitHub pe ek repo mein push karo.
2. [share.streamlit.io](https://share.streamlit.io) pe jao, GitHub se login karo.
3. **"New app"** → apna repo, branch, aur `app.py` select karo.
4. App settings mein **"Secrets"** section khol ke ye add karo:
   ```
   GEMINI_API_KEY = "AIza...."
   ```
5. **Deploy** dabao. Kuch minute mein ek public URL milega
   (jaise `https://toy-store-ai.streamlit.app`) — yehi tumhara **ONE LINK** hai
   jo sabko doge.

## Notes

- Power BI link abhi "Publish to web" wala hai, isliye publicly accessible
  rahega — demo/portfolio ke liye theek hai, sensitive data ho toh mat use karo.
- Agar CSV data update ho, bas `data/` folder ke files replace kar do aur
  app restart kar do.
- AI agent Claude API se SQL query generate karta hai aur DuckDB mein turant
  chala ke jawab deta hai — koi extra database setup nahi chahiye.
