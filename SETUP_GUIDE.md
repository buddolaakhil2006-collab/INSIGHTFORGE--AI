# InsightForge AI — setup guide (Windows)

This is a local, full-stack project. The browser talks to a Flask/Python server. The server calls Gemini; the API key is never sent to the browser.

## 1. Install the tools

Install Python 3.11 or newer from https://www.python.org/downloads/ and Visual Studio Code from https://code.visualstudio.com/.

## 2. Get your Gemini API key

1. Open https://aistudio.google.com/app/apikey
2. Sign in with your Google account.
3. Create an API key and copy it.
4. Keep the key private. Do not paste it into `app.py`, `static/app.js`, screenshots, GitHub, or a public document.

Gemini API access, quotas and any charges are controlled by Google and your account. Check the AI Studio usage page before large-scale use.

## 3. Prepare the project

1. Extract the ZIP file.
2. Open the extracted `insightforge_ai_website` folder in VS Code (`File > Open Folder`).
3. In VS Code, choose `Terminal > New Terminal`.
4. Run these commands one at a time:

```powershell
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

5. Copy `.env.example` and rename the copy to `.env`.
6. Open `.env` and replace the sample value with your actual key:

```text
GEMINI_API_KEY=your_real_key_here
GEMINI_MODEL=gemini-3.8-flash
```

Do not add quotation marks around the key. Do not share the `.env` file.

## 4. Start InsightForge AI

Run:

```powershell
python app.py
```

Open http://127.0.0.1:5000 in Chrome or Edge. Keep the terminal window open while using the website. To stop the server, press `Ctrl+C` in the terminal.

You can also double-click `start_windows.bat` after completing steps 1–3.

## 5. Try the included dataset

Use `data/sales.csv` and try:
- What is the total revenue?
- Which region has the highest revenue?
- Show average quantity by region.
- Which product sold the most units?
- How many rows are in this dataset?

The natural-language question is interpreted by Gemini. The server validates the proposed operation and columns, computes values from CSV rows, records evidence, and runs verification checks. Gemini writes a short explanation from the verified result. It is not permitted to execute AI-generated code.

## 6. What is implemented, and what is not

Implemented in this starter:
- CSV upload, preview, column profiling, missing-cell checks and duplicate-ID checks.
- Gemini-powered Intent, Planner and Insight roles using the Google GenAI SDK.
- Server-side deterministic aggregate/group calculations for the supported operation set.
- Evidence record and independent recomputation checks.
- Eight workflow stages, with data quality, analytics, evidence, verification and report preparation handled by deterministic Python services.
- Downloadable JSON evidence for each completed question.

Not included yet:
- User accounts, Firebase database, cloud deployment, multi-user isolation, saved history, PDF report export, or production security review.
- The eight roles are modular workflow stages, not eight independently hosted autonomous agents. Intent, Planner and Insight call Gemini; the other stages are controlled Python services.
- This is a student project development build, not a production-certified analytics platform.

## Troubleshooting

- `python` is not recognized: reinstall Python and select **Add Python to PATH**, then reopen VS Code.
- `No module named google`: activate `.venv` and run `pip install -r requirements.txt`.
- `Gemini API key is not configured`: check that `.env` is in the same folder as `app.py`, its name is exactly `.env`, and it contains `GEMINI_API_KEY=...`; restart the server.
- `API key invalid` or quota errors: create/check the key in Google AI Studio and check the account's API usage and limits.
- Port 5000 is busy: close the other local Flask app first, or ask for help changing the port.
