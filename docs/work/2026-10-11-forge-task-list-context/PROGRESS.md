# PROGRESS — forge-task-list-context

- [x] Find why the chat list stopped at 2 of 8 (2000-char tool-result cap)
- [x] Find the "Sveglia." opener (presence line)
- [x] Find why task 910395 stopped (Ollama /v1 ignores num_ctx, prompt over the window)
- [x] Hephaestus `/forge/tasks/brief` + `forge_tasks` tool on it
- [x] Oracle: truncation marker, presence line, style rule
- [x] Oracle gateway: local profile via Ollama `/api/chat` with num_ctx, `context_window` in profiles
- [x] Forge engine: budget from window, trim/clip, precise stop reason
- [x] Tests, swagger, module docs
- [ ] User: real run (ask the task list again; reject 910395; consider num_ctx ≥ 32768 for local Forge)
