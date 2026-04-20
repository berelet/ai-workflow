# AI Workflow

**A multi-agent AI system that develops your product** — from idea to production-ready code.

AI Workflow orchestrates a team of specialized AI agents through a configurable pipeline: a project manager decomposes tasks, a business analyst writes specs, a designer creates mockups, a developer writes code, a tester verifies quality, and a performance reviewer audits for issues. All automated, with built-in quality gates at every stage.

---

## Key Features

- **Speed** — full task cycle (from user story to commit) in minutes, not days
- **Quality** — double-pass review: agent creates artifact, review agent checks it against a set of rules (skills)
- **Audit trail** — all artifacts (specs, wireframes, code, test results) are preserved and accessible
- **Visual pipeline editor** — drag-and-drop pipeline builder with Drawflow, per-project or global templates
- **Provider-agnostic** — works with Kiro CLI (AWS Bedrock) and Claude Code (Anthropic)
- **Multi-user** — role-based access (owner, editor, viewer), team invitations, project memberships
- **Auth & security** — JWT authentication, HTTP-only cookies, setup wizard with superadmin creation
- **Mobile-ready** — responsive dashboard, manage your pipeline from any device
- **i18n** — English and Ukrainian, switchable in the UI
- **Voice I/O** — Web Speech API for dictation and TTS in the dashboard terminal
- **Transcription** — record audio and transcribe with faster-whisper (GPU-accelerated)

## Who Is This For

- Teams looking to automate repetitive development workflows
- Solo developers who need a "virtual team"
- Projects where structured process and audit trail are important

---

## Architecture

```
                    +------------------------------------------+
                    |         Dashboard (FastAPI + HTMX)        |
                    |  Backlog | Pipeline | Agents | Artifacts  |
                    |  Terminal | Recorder | Services | Logs     |
                    +------------------------------------------+
                                      |
                    +------------------------------------------+
                    |           Pipeline Engine                 |
                    |  State machine | Stage transitions        |
                    |  Quality gates | Rollback | Auto-advance  |
                    +------------------------------------------+
                          |                     |
              +-----------+-------+    +--------+---------+
              |   Skills Layer    |    |  Agent Sessions   |
              | Security (OWASP) |    |  tmux + Kiro CLI  |
              | Performance      |    |  tmux + Claude    |
              | API Testing      |    +-------------------+
              +-------------------+
                                      |
              +-----------+-----------+-----------+
              |           |                       |
        PostgreSQL       S3                     Git
        (metadata)    (artifacts)         (branch/task)
```

---

## Development Pipeline

Each task flows through a chain of specialized agents:

```
PM -> PM Review -> BA -> BA Review -> Design -> DEV -> DEV Review -> QA -> QA Review -> PERF -> COMMIT
```

- **Double-pass review** — base agent creates an artifact, review agent checks it using injected skills and improves it
- **Auto-rollback** — if QA finds a bug or PERF finds a critical issue, the task returns to DEV automatically
- **Discovery** — 4-stage process for new projects (interview -> analysis -> decomposition -> confirmation)

### Pipeline Templates (out of the box)

| Template | Stages | Final Status |
|----------|--------|--------------|
| **Full Cycle** | PM -> PM Review -> BA -> BA Review -> Design -> DEV -> DEV Review -> QA -> QA Review -> PERF -> COMMIT | done |
| **BA Analysis** | PM -> PM Review -> BA -> BA Review | todo |
| **Architect** | PM -> PM Review -> BA -> BA Review -> ARCH -> ARCH Review | todo |
| **Code Development** | DEV -> DEV Review -> QA -> QA Review -> PERF -> COMMIT | done |

### Agents

| Agent | Role | Output |
|-------|------|--------|
| **PM** | Task decomposition, user stories | `user-stories.md` |
| **BA** | Specs, acceptance criteria, wireframes | `spec.md`, `wireframe.html` |
| **Designer** | HTML/Tailwind mockups, PNG renders | `*.html`, `*.png`, `design-notes.md` |
| **Developer** | Code implementation | modified files, `changes.md` |
| **Tester (QA)** | Testing against acceptance criteria | `test-result.md` or `bug-report.md` |
| **Performance Reviewer** | N+1 queries, memory leaks, Core Web Vitals | `perf-review.md` |
| **Architect** | System design, tech decisions | architecture docs |
| **Orchestrator** | Pipeline routing and coordination (CLI mode) | `pipeline.md` |

### Skills (injected at review stages)

| Scope | Skills |
|-------|--------|
| Global | Software Security (OWASP), Systematic Debugging |
| PM Review | Product Manager Toolkit (RICE, prioritization) |
| BA Review | Requirements Clarity (YAGNI, KISS) |
| DEV Review | FastAPI, React, Software Security, API Testing |
| QA Review | Webapp Testing (Playwright) |
| PERF | Web Performance Audit, App Performance Optimization, Performance Profiling |

---

## Deployment

### Prerequisites

| Component | Version | Purpose |
|-----------|---------|---------|
| Python | 3.12+ | Dashboard backend, CLI |
| PostgreSQL | 14+ | Database (users, projects, pipelines, artifacts) |
| Node.js | 18+ | Design rendering (Puppeteer), dependencies |
| tmux | any | Multi-project CLI sessions |
| Git | 2.x | Version control |

At least one AI provider:

| Provider | Installation | Description |
|----------|-------------|-------------|
| [Kiro CLI](https://kiro.dev) | `npm i -g kiro-cli` | AWS Bedrock models (default) |
| [Claude Code](https://claude.ai/claude-code) | `npm i -g @anthropic-ai/claude-code` | Anthropic Claude |


### Step 1. Clone

```bash
git clone git@github.com:berelet/ai-workflow.git
cd ai-workflow
```

### Step 2. Python environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r dashboard/requirements.txt
```

### Step 3. Node.js dependencies

```bash
npm install
```

Installs `puppeteer-core` and `jsdom` (needed for design rendering to PNG).

### Step 4. PostgreSQL

Create a database and user:

```sql
CREATE USER aiworkflow_app WITH PASSWORD 'your_password';
CREATE DATABASE aiworkflow OWNER aiworkflow_app;
```

### Step 5. Configuration

```bash
cp config/.env.example .env
```

Edit `.env` with your database credentials and preferences:

```env
# Database
PGSQL_AIWORKFLOW_HOST=localhost
PGSQL_AIWORKFLOW_PORT=5432
PGSQL_AIWORKFLOW_DB=aiworkflow
PGSQL_AIWORKFLOW_USER=aiworkflow_app
PGSQL_AIWORKFLOW_PASSWORD=your_password

# AI provider
DEFAULT_CLI=kiro-cli
DEFAULT_MODEL=auto
```

### Step 6. Run database migrations

```bash
alembic upgrade head
```

This creates all required tables (users, projects, pipelines, backlog, artifacts, etc.).

### Step 7. Install skills (optional)

```bash
npm i -g tessl
tessl install
```

Skills are quality rules used by review agents. They're loaded from `.tessl/tiles/`.

### Step 8. Start the dashboard

```bash
# Direct
uvicorn dashboard.server:app --host 0.0.0.0 --port 9000

# Or via the service manager
mkdir -p runtime
cp config/projects.example.json runtime/projects.json
./run.sh start ai-workflow-dashboard
```

### Step 9. Setup Wizard

Open **http://localhost:9000/** in your browser. The setup wizard will guide you through:

1. **Create Superadmin** — email, password, display name
2. **Seed Defaults** — automatically creates:
   - 12 agent configurations (PM, BA, Designer, Developer, QA, Performance Reviewer, Architect, Orchestrator, 4 Discovery agents)
   - 13 skills (Security, PM Toolkit, Requirements Clarity, FastAPI, React, API Testing, Webapp Testing, Performance, etc.)
   - 4 pipeline templates (Full Cycle, BA Analysis, Architect, Code Development)

After setup, the dashboard is ready to use.

### Verification

```bash
# Service status
./run.sh status

# Dashboard logs
./run.sh logs ai-workflow-dashboard

# CLI (interactive menu)
python3 cli.py
```

---

## Project Structure

```
ai-workflow/
├── orchestrator/              # Orchestrator — brain of the system, task routing
├── project-manager/           # PM agent: task decomposition -> user stories
├── business-analyst/          # BA agent: specs + wireframes
├── designer/                  # Designer: HTML/Tailwind mockups -> PNG
├── developer/                 # DEV agent: code implementation
├── tester/                    # QA agent: testing against acceptance criteria
├── performance-reviewer/      # PERF agent: performance audit
├── architect/                 # ARCH agent: system design
├── discovery-*/               # Discovery agents (4 stages)
├── dashboard/                 # Web dashboard
│   ├── routers/               #   API endpoints
│   ├── services/              #   Pipeline engine, git, terminal, prompts
│   ├── db/                    #   SQLAlchemy models, migrations, seeds
│   ├── templates/             #   Jinja2 templates (HTMX + Alpine.js)
│   ├── static/                #   CSS, JS, i18n
│   ├── setup/                 #   Setup wizard
│   └── auth/                  #   JWT authentication
├── config/                    # Configuration (.env.example, tessl.json)
├── shared/templates/          # Artifact templates (user-story, spec, bug-report)
├── .tessl/tiles/              # Skills library for review stages
├── cli.py                     # CLI for running projects in tmux
└── run.sh                     # Service manager (start/stop/status)
```

### Task artifacts

Each task produces artifacts stored in the database (and optionally S3):

```
.ai-workflow/artifacts/task-{id}/
├── user-stories.md            # PM output
├── user-stories-reviewed.md   # PM Review output
├── pm-review.md               # PM Review report
├── spec.md                    # BA output
├── spec-reviewed.md           # BA Review output
├── ba-review.md               # BA Review report
├── wireframe.html             # BA wireframe
├── design-notes.md            # Designer notes
├── changes.md                 # Developer changelog
├── dev-review.md              # Dev Review report
├── test-result.md             # QA result (PASS/FAIL)
├── bug-report.md              # QA bug report (if FAIL)
├── qa-review.md               # QA Review report
└── perf-review.md             # Performance review
```

---

## Dashboard

The web dashboard (http://localhost:9000/) provides:

| Tab | Description |
|-----|-------------|
| **Backlog** | Kanban board (Todo / In Progress / Done). Priority filters, image uploads |
| **Pipeline** | Visual pipeline editor (Drawflow). Create/edit pipelines, configure nodes and skills |
| **Agents** | Agent configurations. Edit global and per-project instructions |
| **Artifacts** | Browse all task artifacts: specs, wireframes, code changes, test results |
| **Terminal** | Embedded terminal for AI agents. Multi-session, Kiro/Claude provider selector |
| **Members** | Team management: invite members, assign roles (owner/editor/viewer) |
| **Recorder** | Audio transcription: record microphone, transcribe with faster-whisper |
| **Services** | Service management: start, stop, health check |
| **Logs** | Pipeline telemetry: structured logs with color-coded events |

---

## CLI

```bash
# Interactive menu
python3 cli.py

# Start a project
python3 cli.py my-project

# With a specific task
python3 cli.py my-project --task "Add user authentication"

# With a specific provider and model
python3 cli.py my-project --provider kiro --model auto
python3 cli.py my-project --provider claude --model sonnet

# Start from a specific stage
python3 cli.py my-project --stage DEV
```

### Providers and Models

| Provider | Models |
|----------|--------|
| `kiro` | Auto (default), Claude Sonnet 4.6, Claude 3.7 Sonnet, Claude 3.5 Sonnet v2 |
| `claude` | Sonnet 4.6 (default), Opus 4.6, Haiku 4.5 |


---

## Customization

### Per-project agent instructions

Create a file at `<project_dir>/.ai-workflow/agents/<agent>.md` — it overrides the global instructions for that agent within the project. You can also edit agent instructions directly in the dashboard (Agents tab).

### Per-project pipelines

Use the visual Pipeline Editor in the dashboard to create custom pipelines per project, or modify one of the global templates.

### Git rules

Create `<project_dir>/.ai-workflow/git-rules.md` — the COMMIT agent will follow these rules when creating commits (message format, branch naming, merge strategy).

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `tmux: command not found` | `sudo apt install tmux` (Ubuntu) or `brew install tmux` (macOS) |
| Port in use | `lsof -i :<port>` -> `kill <PID>`, or change port in config |
| Puppeteer can't render PNG | `npx puppeteer browsers install chrome` |
| faster-whisper: CUDA not found | Will use CPU. For GPU: install CUDA 12 + cuDNN 9 |
| Database connection error | Check `.env` credentials, ensure PostgreSQL is running |
| Alembic migration fails | Ensure database exists and user has CREATE privileges |
| Skills not found | Run `tessl install` in the project root |

---

## Tech Stack

- **Backend**: Python 3.12+, FastAPI, SQLAlchemy 2.0 (async), Alembic, asyncpg
- **Frontend**: Jinja2, HTMX, Alpine.js, Drawflow.js
- **Database**: PostgreSQL
- **Storage**: S3 (binary artifacts), local filesystem (optional)
- **AI Providers**: Kiro CLI (AWS Bedrock), Claude Code (Anthropic)
- **Skills**: tessl framework for quality rules

---

## License

MIT
