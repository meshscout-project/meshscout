# AGENTS

<!-- stigmerig:begin sha256=5ab2b5da11af1288 -->
## Autonomous Operation Invariants

1. **Local-First Stigmergy**: Agents coordinate indirectly through `.stigmerig` task state and filesystem artifacts.
2. **Worktree Isolation**: Implementers isolate execution branches in dedicated git worktrees.
3. **Anti-Self-Approval**: Verification must be performed by an independent verifier before completing tasks.
4. **Append-Only WORM Audit**: All state transitions and completion records are hash-chained in the audit ledger.
5. **Deterministic Trap Ratchet**: Run `stigmerig traps scan` across polyglot source files and bind verification outputs via `--evidence`.

## Workflow

1. Query available tasks via `stigmerig task list --status todo`.
2. Claim a task with lease TTL via `stigmerig task claim --id <id> --agent <agent>`.
3. Scan traps via `stigmerig traps scan` and complete verification via `stigmerig task done --id <id> --agent <agent> --verifier <verifier> --evidence <path>` (pass `--model <model>` or `STIGMERIG_MODEL` for lineage).
<!-- stigmerig:end -->
