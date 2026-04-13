# AI Email & Calendar Assistant

An AI agent that monitors a Gmail inbox, classifies incoming emails using GPT, and executes actions
through a LangGraph state machine with persistent checkpoints and human approval interrupts.

## Architecture

```
FastAPI API  →  WorkflowManager  →  LangGraph Workflow  →  Provider Ports  →  Google Services
                                    │
                    ┌───────────────┼────────────────────────────┐
                    ▼               ▼                            ▼
                Ingest  →  Classify (structured output)  →  Action dispatch
                                │
                       interrupt() on approval
                                │
                          invoke(Command(resume=...))
```

### Workflow nodes

| Node       | Responsibility                                      |
|------------|-----------------------------------------------------|
| `ingest`   | Fetch raw email from Gmail API                      |
| `classify` | LLM classification → label + action + urgency       |
| `approval` | Send approval request email to manager               |
| `wait_approval` | Interrupt workflow and wait for APPROVE/REJECT |
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
```powershell
git clone <repo-url>
cd AiEmailAgent
python -m venv env
env\Scripts\activate
pip install -r requirements.txt
```

### 2. Google credentials
1. Create a Google Cloud project and enable Gmail + Calendar APIs.
2. Create OAuth 2.0 credentials (Desktop app).
3. Download `credentials.json` to `credentials/`.
4. Run the auth flow once locally to generate `credentials/token.json`.

### 3. Environment variables
```powershell
cp .env.example .env
# Edit .env with your values
```

| Variable         | Required | Description                            |
|------------------|----------|----------------------------------------|
| `OPENAI_API_KEY` | Yes      | OpenAI API key                         |
| `MANAGER_EMAIL`  | Yes      | Email for approval requests            |
| `MODEL_NAME`     | No       | LLM model (default: `gpt-4o`)         |
| `APP_HOST`       | No       | Server host (default: `0.0.0.0`)      |
| `APP_PORT`       | No       | Server port (default: `9000`)          |
| `POLL_INTERVAL_SECONDS` | No | Inbox poll interval (default: `30`)    |
| `CREDENTIALS_DIR` | No      | OAuth directory (default: `./credentials`) |
| `TOKEN_PATH`     | No       | OAuth token file (default: `./credentials/token.json`) |
| `CHECKPOINT_DB_PATH` | No   | LangGraph checkpoint DB (default: `./data/checkpoints.db`) |

### 4. Run
```powershell
python main.py
```

## API Endpoints

| Method | Path                       | Description                          |
|--------|----------------------------|--------------------------------------|
| GET    | `/api/v1/test-connection`  | Test Gmail + Calendar connectivity   |
| POST   | `/api/v1/process-emails`   | Process unread emails                |
| POST   | `/api/v1/approve`          | Resume interrupted workflow (APPROVE/REJECT) |

### How it works
1. New unread emails are submitted to `WorkflowManager`.
2. LangGraph executes `ingest -> classify -> action` and interrupts on approval-required paths.
3. Approval request is sent to `MANAGER_EMAIL`, then graph waits in checkpointed state.
4. Manager replies `APPROVE`/`REJECT` to the approval email; poller resumes the checkpointed workflow.
5. Approved path continues from checkpoint to calendar/reply without reclassification.

API endpoints are also available for manual triggers and debugging.

## Project Structure

```
app/
├── workflows/
│   ├── email_graph.py   # LangGraph factory + routing
│   ├── prompts.py       # LLM prompt templates for workflow nodes
│   ├── state.py         # Unified EmailAgentState
│   └── nodes/           # Small single-purpose workflow nodes
├── api/
│   └── endpoints.py
├── schemas/
│   ├── api.py             # API payload models
│   └── classification.py  # Enums + EmailClassification schema
├── services/
│   ├── workflow_manager.py # WorkflowManager (event delivery only)
│   ├── ports.py           # Email/Calendar provider protocols
│   ├── base.py            # Google API base class
│   ├── gmail_service.py   # Gmail service implementation
│   └── calendar_service.py # Calendar service implementation
├── utils/
│   ├── email_utils.py     # Email parsing helpers
│   ├── logging_config.py  # Logging setup
│   └── time_utils.py      # Time helpers
├── auth.py           # Google OAuth2
├── dependencies.py   # FastAPI DI factories
└── settings.py       # Pydantic Settings
```

## Non-Functional Requirements

- **Audit trail**: Every node appends structured entries in `EmailAgentState.audit_log`.
- **Error handling**: Node failures stay localized and are surfaced in workflow output.
- **Idempotency**: Workflow state is checkpointed per thread/workflow id and resumed without re-running prior steps.
- **Human-in-the-loop**: Approval uses LangGraph `interrupt()` and explicit resume command.

## Smoke Test (local, no Google/OpenAI calls)

```powershell
python scripts/smoke_workflow.py
```


