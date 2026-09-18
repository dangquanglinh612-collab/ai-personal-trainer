# AI Coach OS

Streamlit application for personal trainers to manage members, training sessions,
photos, schedules, and AI-assisted coaching plans.

## Project layout

```text
.
??? fitness.py                 # Stable Streamlit entry point / compatibility facade
??? src/ai_coach_os/
?   ??? application.py         # Application composition and routing
?   ??? auth.py                # Session and coach authentication
?   ??? config.py              # Paths and runtime defaults
?   ??? repositories/          # SQLite persistence boundary
?   ??? services/              # AI orchestration and plan persistence
?   ??? ui/                    # Reusable UI helpers and page handlers
??? tests/                     # Regression tests
??? docs/                      # Product and deployment documentation
??? assets/                    # Versioned visual assets
??? .streamlit/config.toml     # Streamlit presentation settings
??? pyproject.toml             # Dependencies, packaging, and tooling
```

## Local development

```powershell
python -m pip install -e ".[dev]"
streamlit run fitness.py
```

Run the regression suite:

```powershell
python -m unittest discover -s tests -p "test_*.py"
```

## Engineering conventions

- Keep Streamlit pages thin: page handlers coordinate input and rendering only.
- Keep data access in `repositories/`, business/AI workflows in `services/`,
  and application wiring in `application.py`.
- Put production secrets only in `.streamlit/secrets.toml` or the deployment
  platform's secret manager. Never commit them.
- Add a regression test for every bug fix and keep behavior-compatible changes
  behind the root `fitness.py` facade until external callers are migrated.
- TASK 10 is currently at **stage A (offline preparation only)**. Keep SQLite
  active; the Supabase backend is not yet wired into all pages.
  See [deployment steps](docs/DEPLOYMENT.md),
  [audited field mapping](docs/TASK10_AUDIT.md), and
  [backup/restore](docs/BACKUP_AND_RESTORE.md).
  The older `SUPABASE_DEPLOYMENT_GUIDE.md` is historical, not the current SQL plan.
