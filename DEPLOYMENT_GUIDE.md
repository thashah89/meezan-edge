# 🕌 Complete Deployment Guide
## GitHub (Private) + Streamlit Cloud + Zerodha Registration

---

## 🏷️ APP NAME SUGGESTIONS

| Name | Tagline |
|------|---------|
| **Meezan Edge** | *Shariah-smart swing trading* |
| **Halal Alpha** | *Clean signals. Pure profits.* |
| **ZakatTrade** | *Trade with purpose* |
| **NoorTrader** | *Illuminating Halal opportunities* |
| **MizanStock** | *Balanced. Compliant. Profitable.* |
| **SaafSignals** | *Clear, clean, compliant trades* |
| **HalalEdge** | *Your Shariah trading advantage* |

> **Top pick → `Meezan Edge`** — Meezan means "balance/scale" in Arabic,
> perfectly representing the 2:1 R:R system. Professional, memorable, unique.

Your Streamlit URL would be:
`https://meezanedge.streamlit.app`

---

## PART 1 — GITHUB SETUP (Private Repo)

### Step 1 — Create a GitHub Account
1. Go to **https://github.com**
2. Click **Sign up**
3. Enter your email, create a username and password
4. Verify your email

---

### Step 2 — Create a NEW Private Repository
1. Click the **+** icon (top right) → **New repository**
2. Fill in:
   - **Repository name:** `meezan-edge`  *(or your chosen name)*
   - **Description:** `Halal Stock Trading System — Private`
   - **Visibility:** ✅ Select **Private**  ← IMPORTANT
   - **Initialize:** ✅ Check **Add a README file**
3. Click **Create repository**

> Your repo is now private. Only you can see it.

---

### Step 3 — Install Git on your PC

**Windows:**
Download from https://git-scm.com/download/win
Run the installer, click Next through everything.

**Mac:**
```bash
# Open Terminal and run:
xcode-select --install
```

Verify it worked:
```bash
git --version
# Should show: git version 2.x.x
```

---

### Step 4 — Set Up Your Folder

Create a folder called `meezan-edge` on your PC and put ALL these files inside it:

```
meezan-edge/
├── app.py
├── config.py
├── scraper.py
├── market_data.py
├── trend_filter.py
├── pattern_engine.py
├── backtester.py
├── live_engine.py
├── zerodha_auth.py
├── requirements.txt
├── .gitignore
└── .streamlit/
    ├── config.toml
    └── secrets.toml        ← LOCAL ONLY, never pushed to GitHub
```

---

### Step 5 — Push Code to GitHub

Open **Command Prompt** (Windows) or **Terminal** (Mac) inside your `meezan-edge` folder:

```bash
# 1. Tell Git who you are (one-time setup)
git config --global user.email "you@email.com"
git config --global user.name "Your Name"

# 2. Initialize git in your folder
git init

# 3. Connect to your GitHub repo
#    Replace YOUR_USERNAME with your actual GitHub username
git remote add origin https://github.com/YOUR_USERNAME/meezan-edge.git

# 4. Stage all files
git add .

# 5. Check what will be committed — secrets.toml should NOT appear
git status
# You should NOT see .streamlit/secrets.toml in the list
# If you do, stop and check your .gitignore file

# 6. Commit
git commit -m "Initial commit — Meezan Edge trading system"

# 7. Push to GitHub
git branch -M main
git push -u origin main
```

GitHub will ask for your username and password.
For the password, use a **Personal Access Token** (not your GitHub password):
- Go to GitHub → Settings → Developer Settings → Personal Access Tokens → Tokens (classic)
- Click **Generate new token**
- Check: `repo` scope
- Copy the token and paste it as your password

---

### Step 6 — Verify .gitignore is Working

Go to your GitHub repo in the browser.
Open the file list and confirm these files are **NOT** there:
- ❌ `.streamlit/secrets.toml`
- ❌ `zerodha_token.json`
- ❌ `halal_stocks_cache.json`

These should be there:
- ✅ `.streamlit/config.toml`
- ✅ `.gitignore`
- ✅ All `.py` files
- ✅ `requirements.txt`

---

## PART 2 — STREAMLIT CLOUD DEPLOYMENT

### Step 7 — Create a Streamlit Account
1. Go to **https://share.streamlit.io**
2. Click **Sign up**
3. Click **Continue with GitHub** — use the same GitHub account
4. Authorize Streamlit to access your GitHub

---

### Step 8 — Deploy Your App
1. Click **New app** (top right)
2. Fill in:
   - **Repository:** `YOUR_USERNAME/meezan-edge`
   - **Branch:** `main`
   - **Main file path:** `app.py`
   - **App URL:** type `meezanedge` → your URL becomes `meezanedge.streamlit.app`
3. Click **Advanced settings** → we'll add secrets here (Step 9)
4. Click **Deploy!**

Streamlit will install dependencies from `requirements.txt` and launch the app.
This takes 2–4 minutes the first time.

---

### Step 9 — Add Secrets (API Keys) on Streamlit Cloud

**Never put real keys in config.py or GitHub.**
Add them here instead:

1. After deploying, click ⋮ (three dots) next to your app → **Settings**
2. Click **Secrets** tab
3. Paste this block and fill in your values:

```toml
ZERODHA_API_KEY      = "your_actual_api_key_here"
ZERODHA_API_SECRET   = "your_actual_api_secret_here"
ZERODHA_REDIRECT_URL = "https://meezanedge.streamlit.app"
ZERODHA_POSTBACK_URL = "https://meezanedge.streamlit.app/postback"
```

4. Click **Save**
5. App restarts automatically and picks up the secrets

---

### Step 10 — Get Your Live App URL

After deployment your app is live at:
```
https://meezanedge.streamlit.app
```

**Copy this URL — you need it for the Zerodha developer portal.**

---

## PART 3 — ZERODHA KITE API REGISTRATION

### Step 11 — Apply for Kite Connect API
1. Go to **https://developers.kite.trade**
2. Click **Sign up** (or log in with your Zerodha trading account)
3. Click **Create new app**

Fill in the form:

| Field | What to Enter |
|-------|--------------|
| **App name** | `Meezan Edge` |
| **App type** | `Personal` |
| **Redirect URL** | `https://meezanedge.streamlit.app` |
| **Postback URL** | `https://meezanedge.streamlit.app/postback` |
| **Description** | `Personal halal stock screening and swing trading system for NSE stocks` |

4. Click **Create**
5. You'll receive your **API Key** and **API Secret** immediately

---

### Step 12 — Add Keys to Streamlit Secrets

Go back to Streamlit Cloud:
1. ⋮ → **Settings** → **Secrets**
2. Replace the placeholder values with your real keys:

```toml
ZERODHA_API_KEY      = "abc123xyz456"        ← your real key
ZERODHA_API_SECRET   = "aBcDeFgHiJkLmN"     ← your real secret
ZERODHA_REDIRECT_URL = "https://meezanedge.streamlit.app"
ZERODHA_POSTBACK_URL = "https://meezanedge.streamlit.app/postback"
```

3. Save → app restarts

---

## PART 4 — ACCESS CONTROL (Private App)

### Step 13 — Restrict Who Can View the App

By default, even private GitHub repos produce a publicly accessible Streamlit URL.
Here's how to lock it down:

#### Option A — Streamlit Cloud Viewer Authentication (Easiest)
1. In Streamlit Cloud → **Settings** → **Sharing**
2. Change from **Public** to **Private**
3. Under **Who can view this app**, click **Invite viewers**
4. Enter the email addresses of people you want to allow
5. They will need a Streamlit account (free) to log in

**Result:** Only you and your invited users can open the app URL.
Anyone else sees a login page.

#### Option B — Share by Streamlit Account Email (Most Controlled)
Same as Option A but you add emails one by one.
Useful for sharing with a broker, CA, or family member.

---

## PART 5 — UPDATING THE APP AFTER CHANGES

Every time you update code on your PC:

```bash
# In your meezan-edge folder:
git add .
git commit -m "describe what you changed"
git push
```

Streamlit Cloud automatically detects the GitHub push and redeploys within 60 seconds.
No manual steps needed.

---

## QUICK REFERENCE — URLS TO USE EVERYWHERE

| Where | URL |
|-------|-----|
| **Open your app** | `https://meezanedge.streamlit.app` |
| **Zerodha portal — Redirect URL** | `https://meezanedge.streamlit.app` |
| **Zerodha portal — Postback URL** | `https://meezanedge.streamlit.app/postback` |
| **Streamlit secrets ZERODHA_REDIRECT_URL** | `https://meezanedge.streamlit.app` |
| **config.py ZERODHA_REDIRECT_URL (local)** | `http://127.0.0.1:8501` |

---

## SECURITY CHECKLIST

Before going live, confirm all of these:

- [ ] GitHub repository is set to **Private**
- [ ] `.streamlit/secrets.toml` is in `.gitignore` and NOT on GitHub
- [ ] API keys are ONLY in Streamlit Cloud Secrets (not in any `.py` file)
- [ ] Streamlit app Sharing is set to **Private**
- [ ] Only your email (+ approved emails) are in the viewer list
- [ ] `zerodha_token.json` is in `.gitignore`

---

## TROUBLESHOOTING

| Problem | Fix |
|---------|-----|
| App shows "Module not found" | Check `requirements.txt` has all packages, push again |
| Secrets not working | Ensure key names in Secrets match exactly what `config.py` reads |
| Zerodha redirect fails | Confirm redirect URL in portal matches Streamlit URL exactly (no trailing slash) |
| App keeps reloading | Normal — free tier sleeps after 7 days of inactivity, wakes on first visit |
| Push rejected | Use Personal Access Token as password, not your GitHub password |
| Can't see .streamlit folder | Hidden folders — press Ctrl+H (Windows) or Cmd+Shift+. (Mac) to show |
