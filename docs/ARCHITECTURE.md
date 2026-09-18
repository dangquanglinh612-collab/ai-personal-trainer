# Architecture

## Design goals

- Keep the Streamlit entry point stable while the implementation evolves.
- Separate presentation, application flow, persistence, and AI workflow code.
- Make the SQLite-to-Supabase migration a repository-boundary change rather than
  a UI rewrite.
- Preserve regression coverage during incremental modernization.

## Dependency direction

```text
fitness.py (stable entry point)
        |
        v
application.py  --> ui/pages.py --> ui/views/* --> ui/helpers.py + ui/styles.py
        |                  |
        |                  +--> services/ai.py
        v                         |
auth.py + repositories/ <---------+
```

`fitness.py` is a compatibility facade only. New code must import from
`ai_coach_os` directly; it must not add new behavior to the facade.

## Module contracts

| Layer | Responsibility | Must not own |
| --- | --- | --- |
| `application.py` | configuration, session bootstrapping, route selection | SQL and page markup |
| `ui/` | page state, input validation, rendering, presentation styles | direct database connections |
| `ui/views/` | one business workflow per page module | cross-domain persistence logic |
| `services/` | AI prompts, fallback behavior, multi-step business workflows | Streamlit navigation |
| `repositories/` | database schema, queries, transactions, file metadata | presentation decisions |
| `auth.py` | authenticated coach session lifecycle | member or training business rules |

## Change rules

1. Add a new data access method in `repositories/` first, with a regression test.
2. Keep transaction boundaries inside repositories or a service?not inside a page.
3. A page handler may call a service/repository but may not construct SQL.
4. Store visual tokens and CSS in `ui/styles.py`; keep rendering helpers free of
   persistence concerns.
5. For Supabase, replace the SQLite repository implementation behind the same
   use cases; do not query Supabase from page modules.

## Quality gates

Before merge, run:

```powershell
python -m compileall -q fitness.py src tests
python -m unittest discover -s tests -p "test_*.py"
```

GitHub Actions runs the same gates for pushes to `main` and pull requests.
