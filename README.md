# AI Email & Calendar Assistant

AI agent monitoring Gmail inbox, classifying emails via GPT, and executing actions autonomously — with human-in-the-loop approval for sensitive operations.

## Architecture

```
FastAPI + poll loop → WorkflowManager → LangGraph → Gmail / Calendar APIs
```

**Workflow:** `ingest → classify → analyze → tools → (ask_approval?) → cleanup`

| Node | Responsibility |
|------|---------------|
| `ingest` | Fetch raw email from Gmail |
| `classify` | LLM structured output → `EmailLabel` + urgency flag |
| `analyze` | LLM tool-call planning (MAX_ANALYZE_PASSES guard) |
| `tools` | Execute tool calls |
| `ask_approval` | Email manager, interrupt & checkpoint workflow |
| `cleanup` | Write JSON audit record |

| Label | Auto action | Approval |
|-------|------------|---------|
| `MEETING_REQUEST` | Check availability → create event | Yes |
| `TASK` | Notify manager → archive | Yes (if urgent) |
| `INFO_ONLY` | Archive (Finance label for invoices) | No |
| `SALES_OUTREACH` | Polite decline + archive | Configurable |
| `MARKETING` | Archive | No |
| `SPAM` | Move to Spam | No |

## Setup

### Prerequisites
- Python 3.10+, Gmail + Calendar APIs enabled, OpenAI API key

### Install
```powershell
git clone <repo-url>
cd AI-Email-Assistant
python -m venv env
env\Scripts\activate
pip install -r requirements.txt
```

### Google credentials
1. Create a GCP project, enable Gmail + Calendar APIs.
2. Create OAuth 2.0 credentials (Desktop app).
3. Place `credentials.json` in `credentials/`.
4. Run OAuth flow once → generates `credentials/token.json`.

### Environment
```powershell
cp .env.example .env   # fill in values
```

| Variable | Required | Default                 | Description |
|----------|----------|-------------------------|-------------|
| `OPENAI_API_KEY` | Yes | —                       | OpenAI key |
| `MANAGER_EMAIL` | Yes | —                       | Approval request recipient |
| `MODEL_NAME` | No | `gpt-4o`                | LLM model |
| `POLL_INTERVAL_SECONDS` | No | `30`                    | Inbox poll interval |
| `MAX_ANALYZE_PASSES` | No | `6`                     | Max LLM cycles per email |
| `SALES_REPLY_REQUIRES_APPROVAL` | No | `true`                     | Gate sales auto-replies |
| `APP_HOST` / `APP_PORT` | No | `0.0.0.0` / `9000`      | Server bind |
| `CHECKPOINT_DB_PATH` | No | `./data/checkpoints.db` | LangGraph state DB |

### Run
```powershell
python main.py
```

## API

| Method | Path | Description                          |
|--------|------|--------------------------------------|
| GET | `/api/v1/health` | Health check                         |
| GET | `/api/v1/test-connection` | Verify Gmail + Calendar connectivity |
| POST | `/api/v1/process-emails` | Manually trigger inbox processing    |
| POST | `/api/v1/approve` | Approve / reject workflow via API    |

Primary flow is fully automated. `/process-emails` and `/approve` are manual fallbacks — approval normally happens via email reply (`APPROVE` / `REJECT`).

## How approval works

1. Poll loop fetches unread emails every `POLL_INTERVAL_SECONDS`.
2. Each email runs `ingest → classify → analyze → tools`.
3. Sensitive tools (`send_reply`, `create_calendar_event`, `notify_manager`) trigger `ask_approval` — graph interrupts, manager gets an email.
4. Manager replies `APPROVE` or `REJECT`; next poll detects the reply and resumes the checkpointed workflow.
5. Approved actions execute from exact checkpoint; rejected emails are archived.

## Project structure

```
app/
├── api/endpoints.py          # FastAPI router
├── schemas/
│   ├── api.py                # ApprovalDecision, WorkflowStatus
│   └── classification.py     # EmailLabel, GmailSystemLabel enums
├── services/
│   ├── ports.py              # EmailProvider / CalendarProvider protocols
│   ├── gmail_service.py      # Gmail implementation
│   ├── calendar_service.py   # Calendar implementation
│   └── workflow_manager.py   # Polling, approval resume, orchestration
├── workflows/
│   ├── graph.py              # LangGraph factory + routing_logic
│   ├── nodes.py              # Workflow nodes
│   ├── tools.py              # LangChain tools
│   ├── policies.py           # ApprovalPolicy (pluggable)
│   ├── prompts.py            # LLM system prompt
│   ├── state.py              # EmailAgentState TypedDict + reducers
│   └── utils.py              # Message sanitization, runtime config
└── utils/                    # Email parsing, logging, time helpers
```
