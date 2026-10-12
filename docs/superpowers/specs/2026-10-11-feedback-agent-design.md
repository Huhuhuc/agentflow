# Feedback Agent implementation

The approved goal is to improve AgentFlow for AI Agent developer applications. Implement an additive feedback workspace in the current checkout without overwriting local LLM/SSE changes or merging the separate planner branch wholesale.

## Scope and architecture

- React feedback workspace: submit reports, inspect persisted runs/tool traces, inspect evidence and drafts, explicitly confirm tickets, view an offline evaluation.
- FastAPI authenticated, tenant-scoped endpoints; separate additive SQLAlchemy tables for reports, runs and confirmed tickets so existing workflow tables remain compatible.
- A bounded agent executor selects tools using native OpenAI-compatible function calling in real mode. Mock mode uses a deterministic policy and must be labelled as simulated, not evidence of real model quality.
- Read-only tools search retained demo release notes and same-tenant reports. A draft tool prepares a ticket but cannot persist a confirmed ticket. Arguments are validated, tool names allowlisted, outputs treated as untrusted data.
- Every run freezes input, prompt, tool definitions and runtime limits. Persist per-step tool arguments/results/errors, duration and token usage; cap model steps, tools per response, total tool calls and aggregate tokens. Model requests have timeout and bounded retries. Missing real-mode credentials fail explicitly.
- Final output has a validated category, owner, evidence references and next action. Unsupported evidence references fail validation. Missing evidence returns needs_information. A ticket requires a draft and server-side confirmation; confirmations are idempotent and tenant scoped.
- Offline evaluation compares a rule baseline, single response and agent on retained labelled synthetic cases. Report classification/route accuracy, safe completion, evidence validity, tool coverage, duration and tokens. No synthetic cost or production claims; live mode is an explicit CLI choice.

## Execution plan

1. Add agent-specific models, schemas, fixture knowledge and tools.
2. Add real/mock model adapters and a bounded executor with persistent traces.
3. Add authenticated API routes, background execution and confirmation.
4. Add a React workspace connected to these APIs and remove misleading dashboard constants.
5. Add evaluation fixtures, CLI/report endpoint and failure/tenant/confirmation tests.
6. Run backend tests, frontend build/lint, live local API/UI smoke checks; document honest capabilities and limitations.

## Boundaries

No external ticketing/notification action, automatic production writes, paid live API calls, vector database or multi-agent orchestrator in this iteration. Keyword retrieval is labelled lexical; mock token counters are zero. Docker wiring is documented, not claimed to have been tested without Docker. The separate planner branch remains untouched.
