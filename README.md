# Stock Dashboard — Setup Guide

## What this does
- `update_prices.py` — fetches live NSE prices via yfinance, writes `prices.json`
- GitHub Actions runs this automatically every weekday at 3:30 PM IST
- `stock-dashboard.html` — your dashboard, fetches `prices.json` on load for live CMPs

---

## Step-by-step setup

### 1. Create a GitHub repo
- Go to github.com → click **New repository**
- Name it e.g. `stock-dashboard`
- Set to **Public** (needed for raw URL access)
- Click **Create repository**

### 2. Upload all files
Upload these four files to the repo root:
- `stock-dashboard.html`
- `update_prices.py`
- `.github/workflows/update_prices.yml`
- `README.md`

### 3. Add your tickers to update_prices.py
Open `update_prices.py` and edit the `TICKERS` list:
```python
TICKERS = [
    "RELIANCE",
    "HDFCBANK",
    "INFY",
    # add all your stocks here
]
```
Commit the change.

### 4. Run the workflow manually (first time)
- Go to your repo → **Actions** tab
- Click **Update stock prices**
- Click **Run workflow** → **Run workflow**
- Wait ~30 seconds → `prices.json` appears in the repo

### 5. Get your prices.json URL
- Click on `prices.json` in your repo
- Click **Raw** button
- Copy the URL — it looks like:
  `https://raw.githubusercontent.com/YOUR_USERNAME/stock-dashboard/main/prices.json`

### 6. Update the dashboard HTML
Open `stock-dashboard.html` and find this line near the top of the script:
```javascript
const PRICES_JSON_URL = "YOUR_GITHUB_RAW_URL_HERE";
```
Replace with your actual URL:
```javascript
const PRICES_JSON_URL = "https://raw.githubusercontent.com/YOUR_USERNAME/stock-dashboard/main/prices.json";
```
Commit the change.

### 7. Deploy to Netlify
- Go to https://app.netlify.com/drop
- Drag and drop `stock-dashboard.html`
- Get your live URL instantly

### 8. Done ✓
- Dashboard auto-fetches prices.json on load
- GitHub Actions updates prices every weekday at 3:30 PM IST
- Hit **↻ Refresh prices** in the dashboard sidebar anytime for latest data

---

## Adding more stocks
1. Add the ticker to `TICKERS` in `update_prices.py` and commit
2. Add the stock in your dashboard via **Add stock** button
Both steps needed — one for price data, one for your research view.

---

## Troubleshooting
| Problem | Fix |
|---|---|
| Prices not loading | Check that `prices.json` exists in repo and URL is correct |
| Ticker showing `—` | Add it to `TICKERS` in `update_prices.py` |
| GitHub Action failing | Go to Actions tab → click the failed run → read the error log |
| Dashboard data reset | Data is in localStorage — don't clear browser data |
