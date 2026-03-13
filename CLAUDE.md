# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**AI Skills Platform** - A full-stack application for managing AI skills and workflows. Users can create/manage skills, build workflow orchestrations, and interact with an AI agent that plans skill execution.

## Project Structure

```
product/
├── my-demo/              # Vue 3 Frontend
│   ├── src/
│   │   ├── api/          # API client (fetch wrapper, typed interfaces)
│   │   ├── components/   # Vue components
│   │   │   ├── agent/    # AgentChat.vue - AI chat with skill planning
│   │   │   ├── skills/   # AddSkillModal.vue, SkillCard.vue
│   │   │   └── workflow/ # WorkflowBuilder.vue
│   │   ├── views/        # SkillsView.vue (main page)
│   │   └── stores/       # Pinia stores
│   └── package.json
│
└── product-background/   # FastAPI Backend
    ├── main.py           # App entry, CORS, routers
    ├── config.py         # Settings (DB, Anthropic API)
    ├── database.py       # SQLAlchemy setup
    ├── models/           # SQLAlchemy ORM models
    ├── schemas/          # Pydantic schemas
    ├── services/         # Business logic
    │   └── agent_service.py  # Claude AI integration
    ├── routers/          # API endpoints
    └── schema.sql        # Database DDL
```

## Commands

### Frontend (my-demo)

```bash
cd my-demo

# Install dependencies
npm install

# Development server (Vite)
npm run dev

# Build for production
npm run build

# Type check
npm run type-check

# Lint (oxlint + eslint)
npm run lint

# Format code (Prettier)
npm run format
```

**Note:** Requires Node.js ^20.19.0 or >=22.12.0

### Backend (product-background)

```bash
cd product-background

# Install dependencies
pip install -r requirements.txt

# Development server (with auto-reload)
uvicorn main:app --reload

# Production server
uvicorn main:app --host 0.0.0.0 --port 8000
```

### Database Setup

```bash
# Execute DDL in MySQL
mysql -u root -p product_background < schema.sql
```

## Tech Stack

### Frontend
- **Framework**: Vue 3 (Composition API, `<script setup>`)
- **Build**: Vite 7
- **State**: Pinia
- **Router**: Vue Router 5
- **Language**: TypeScript

### Backend
- **Framework**: FastAPI
- **ORM**: SQLAlchemy 2.0
- **Database**: MySQL 8+ (via PyMySQL)
- **AI**: Anthropic Claude SDK
- **Validation**: Pydantic v2

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET/POST/PUT/DELETE | `/skills` | Skill CRUD |
| GET/POST/PUT/DELETE | `/workflows` | Workflow CRUD |
| POST | `/agent/chat` | AI chat (non-streaming) |
| POST | `/agent/chat/stream` | AI chat (SSE streaming) |
| POST | `/agent/plan` | Plan skills for task |
| POST | `/agent/execute` | Execute skill script |
| GET | `/executions/workflow/{id}/precheck` | Pre-check workflow interactions |
| POST | `/executions/workflow/{id}/start` | Start workflow execution |
| GET | `/executions/{id}` | Get execution status |
| POST | `/executions/{id}/interact` | Submit interaction response |
| POST | `/executions/{id}/cancel` | Cancel execution |

## Key Patterns

### Vue Reactivity
When modifying nested properties in reactive arrays, replace the entire element to trigger updates:
```typescript
// Don't: messages.value[i].skillPlan = plan
// Do: messages.value[i] = { ...messages.value[i], skillPlan: plan }
```

### AI Skill Planning
The AI agent outputs skill plans in a special format at the end of responses:
```
<!--SKILL_PLAN:[{"skill":"skill-name","action":"description","exists":true/false}]-->
```
Frontend parses this to render interactive pipeline UI.

### SSE Streaming
AI responses use Server-Sent Events for real-time streaming. Frontend uses `AsyncGenerator` pattern in `agentApi.chatStream()`.

### Workflow Execution with Interactions
Skills can define `interactions` that require user input during workflow execution:

```typescript
// Skill interaction types
type InteractionType = 'input' | 'select' | 'multiselect' | 'confirm' | 'upload' | 'form'

interface SkillInteraction {
  id: string
  type: InteractionType
  label: string
  timing: 'before' | 'during'  // before=collect upfront, during=pause at runtime
  options?: { value: string; label: string }[]  // for select types
}
```

**Execution Flow:**
1. `precheck` - Get all `timing=before` interactions
2. Collect user inputs in modal form
3. `start` - Begin execution with `pre_inputs`
4. If `timing=during` interaction needed → status becomes `paused`
5. `interact` - Submit user response, resume execution
6. Repeat until `completed` or `failed`

## Environment Variables

Backend (`.env` in product-background):
```env
DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASSWORD=your_password
DB_NAME=product_background

ANTHROPIC_API_KEY=your_key
ANTHROPIC_BASE_URL=       # Optional: Azure proxy URL
CLAUDE_MODEL=claude-opus-4-5
```

Frontend (`.env` in my-demo, optional):
```env
VITE_API_BASE_URL=http://localhost:8000/api  # Default if not set
```

Frontend config is in `src/config.ts`. Use `@/` for imports (alias to `./src`).
