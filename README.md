# AI Email & Calendar Assistant

An AI agent that **automatically monitors** a Gmail inbox, classifies incoming emails using GPT-4o,
and takes autonomous actions — including calendar coordination and human-in-the-loop approval.

The agent runs a **background polling loop** (default: every 60s) that processes new emails
and checks for manager approval replies. No manual API calls required — just start the server.

## Architecture

```
FastAPI API  →  AgentRunner  →  LangGraph Workflow  →  Gmail / Calendar APIs
                                    │
                    ┌───────────────┼───────────────────┐
                    ▼               ▼                   ▼
                Ingest  →  Classify (LLM)  →  Action dispatch
                                │                │    │    │
                            Approval?       Archive  Spam  Flag+Notify
                                │                         │
                          Manager email            Calendar → Reply
```

### Workflow nodes

| Node       | Responsibility                                      |
|------------|-----------------------------------------------------|
| `ingest`   | Fetch raw email from Gmail API                      |
| `classify` | LLM classification → label + action + urgency       |
| `approval` | Send approval request email to manager               |
| `action`   | Dispatch: archive / spam / flag+notify based on action |
| `calendar` | Check availability + create Google Calendar event    |
| `reply`    | Send auto-reply within the original thread           |

### Email classification matrix

| Label            | Action         | Approval     | Details                              |
|------------------|----------------|--------------|--------------------------------------|
| MARKETING        | archive        | No — auto    | Optional acknowledgement reply       |
| MEETING_REQUEST  | create_event   | Yes — email  | Parse times, check calendar conflicts|
| SALES_OUTREACH   | send_reply     | No — auto    | Polite decline + archive             |
| TASK             | flag_notify    | If urgent    | STARRED + manager notification       |
| INFO_ONLY        | archive        | No — auto    | Auto-labeled with Finance label      |
| SPAM             | log_spam       | No — auto    | Moved to Gmail system Spam folder    |

**URGENT** modifier can be added to any label except SPAM.

## Setup

### Prerequisites
- Python 3.10+
- Gmail account with API access enabled
- Google Calendar API enabled
- OpenAI API key

### 1. Clone and install
```bash
git clone <repo-url>
cd AiEmailAgent
python -m venv env
source env/bin/activate  # or env\Scripts\activate on Windows
pip install -r requirements.txt
```

### 2. Google credentials
1. Create a Google Cloud project and enable Gmail + Calendar APIs.
2. Create OAuth 2.0 credentials (Desktop app).
3. Download `credentials.json` to `credentials/`.
4. Run the auth flow once locally to generate `credentials/token.json`.

### 3. Environment variables
```bash
cp .env.example .env
# Edit .env with your values
```

| Variable         | Required | Description                            |
|------------------|----------|----------------------------------------|
| `OPENAI_API_KEY` | Yes      | OpenAI API key                         |
| `GMAIL_USER`     | Yes      | Gmail address being monitored          |
| `MANAGER_EMAIL`  | Yes      | Email for approval requests            |
| `MODEL_NAME`     | No       | LLM model (default: `gpt-4o`)         |
| `APP_HOST`       | No       | Server host (default: `0.0.0.0`)      |
| `APP_PORT`       | No       | Server port (default: `9000`)          |
| `POLL_INTERVAL_SECONDS` | No | Inbox poll interval (default: `60`)    |
| `PROXY_HOST`     | No       | HTTP proxy host                        |
| `PROXY_PORT`     | No       | HTTP proxy port                        |
| `DB_PATH`        | No       | SQLite DB path (default: `data/agent.db`) |

### 4. Run
```bash
python main.py
```

## API Endpoints

| Method | Path                       | Description                          |
|--------|----------------------------|--------------------------------------|
| GET    | `/api/v1/test-connection`  | Test Gmail + Calendar connectivity   |
| POST   | `/api/v1/process-emails`   | Process unread emails + approved retries |
| POST   | `/api/v1/check-approvals`  | Check manager replies on pending approvals |

### How it works
1. On startup, the agent begins polling Gmail every `POLL_INTERVAL_SECONDS` (default: 60s).
2. New unread emails are fetched, classified by LLM, and actions are executed automatically.
3. Emails requiring approval (calendar events, urgent tasks) trigger an email to `MANAGER_EMAIL`.
4. Manager replies APPROVE or REJECT — the next poll cycle picks up the decision.
5. Approved actions (calendar events, replies) are executed on the following poll cycle.

API endpoints are also available for manual triggers and debugging.

## Project Structure

```
app/
├── agent/          # LangGraph workflow
│   ├── actions.py  # Atomic Gmail/Calendar actions
│   ├── graph.py    # Graph construction + routing
│   ├── nodes.py    # Workflow node functions
│   ├── prompts.py  # LLM prompt templates
│   └── state.py    # AgentState TypedDict
├── api/
│   └── endpoints.py
├── schemas/
│   └── classification.py  # Pydantic models (EmailRecord, EmailClassification)
├── services/
│   ├── agent_runner.py    # Orchestrator (idempotency, retry logic)
│   ├── approval.py        # Approval polling service
│   ├── base.py            # Google API base class
│   └── google.py          # Gmail + Calendar service classes
├── utils/
│   ├── email_utils.py     # Email parsing helpers
│   ├── logging_config.py  # Logging setup
│   └── time_utils.py      # Time helpers
├── auth.py         # Google OAuth2
├── database.py     # SQLite persistence
├── dependencies.py # FastAPI DI factories
└── settings.py     # Pydantic Settings
```

## Non-Functional Requirements

- **Audit trail**: Every processed email produces structured log entries stored in DB (`audit_trail` field on `EmailRecord`).
- **Error handling**: `safe_execute` wrapper catches exceptions per node, logs them, persists state, and short-circuits the remaining workflow.
- **Idempotency**: Emails already processed (with classification) are skipped. Incomplete records (failed mid-workflow) are automatically retried.
- **Human-in-the-loop**: Calendar events and manager-facing replies require email confirmation (APPROVE/REJECT) before execution.


