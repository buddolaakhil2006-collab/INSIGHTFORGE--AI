# InsightForge AI

**An Evidence-Grounded Multi-Agent System for Reliable and Explainable Data Analytics**

InsightForge AI is a student-project development build for uploading CSV datasets, asking natural-language analytics questions, and receiving answers supported by deterministic calculations, evidence records, and verification checks.

## Features

- CSV upload, preview, column profiling, missing-value and duplicate checks
- Gemini-assisted intent classification, analytics planning, and explanation
- Server-side deterministic aggregation for supported operations
- Evidence records and independent recomputation checks
- Workflow trace for the eight project roles
- Downloadable JSON evidence output
- Included sample datasets in `data/`

## Technology

- Python and Flask backend
- HTML, CSS, and JavaScript frontend
- Google GenAI SDK (Gemini)
- Deterministic Python analytics and verification

## Run locally (Windows)

1. Install Python 3.11+ and VS Code.
2. Copy `.env.example` to `.env` and add your Gemini API key.
3. In a terminal opened in this folder, run:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

4. Open `http://127.0.0.1:5000`.

Never commit `.env` or expose your Gemini API key in browser-side code.

## Deploy a live website

This repository includes `render.yaml` for deployment on Render.

1. Push this repository to GitHub.
2. In Render, choose **New + → Blueprint** and connect this repository.
3. Set the `GEMINI_API_KEY` secret in the Render service environment.
4. Deploy. Render will provide a public HTTPS URL for the running Flask app.

GitHub hosts the source code; it does not run this Flask backend as a GitHub Pages site. Use a Python-capable host such as Render for the live application.

## Agent/workflow scope

The eight displayed roles are modular workflow stages. Intent, Planner, and Insight use Gemini. Data Quality, Analytics, Evidence, Verification, and Report are controlled Python services. They are not eight independently hosted autonomous agents.

## Current limitations

This is a development starter, not a production-certified application. Authentication, persistent multi-user storage, saved analysis history, production security review, and deployment configuration are not included as finished features. Gemini usage, availability, quotas, and billing depend on the configured Google AI account.
