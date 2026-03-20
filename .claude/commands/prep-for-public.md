# prep-for-public

Audit this repo for public release readiness. Run every check below, report findings as READY / CONCERN / BLOCKER.

## Security Checks (BLOCKERS if found)

- **Hardcoded secrets**: Scan all non-.gitignore files for patterns: API keys (`sk-`, `ghp_`, `evk_`, `pypi-`, `AKIA`), passwords, tokens, private URLs, connection strings with credentials
- **Private SSH deps**: Check `pyproject.toml`, `package.json`, `requirements*.txt` for `git+ssh://` or `git+https://github.com/` private repo refs
- **Internal hostnames**: Search for `.internal`, `localhost` hardcoded as production URLs, private IP ranges (10.x, 192.168.x, 172.16-31.x)
- **Sensitive env files**: Verify `.env`, `.env.local`, `*.pem`, `*.key`, `credentials.json` are in `.gitignore` and not committed
- **Git history secrets**: Run `git log --all --oneline` and flag if any commit messages mention secrets, passwords, or tokens

## Identity & Attribution

- **Author info**: Does `pyproject.toml` / `package.json` have correct author name + email?
- **License**: Does a `LICENSE` file exist in root? Does it match the declared license in pyproject?
- **Copyright headers**: Are any source files missing attribution that require it?

## Install & Dependency Checks

- **All deps on public registries**: No `git+ssh://`, no private PyPI indexes, no internal npm registries
- **Version pinned appropriately**: No `*` or missing version constraints on critical deps
- **Install actually works**: `pip install -e .` or `npm install` completes without errors
- **Entry points work**: Run the installed CLI commands and verify they start without crashing

## Documentation

- **README exists and has**: Title, one-line description, install instructions, basic usage example, license badge or mention
- **Install instructions are current**: `pip install <name>` uses the actual published package name
- **No internal references in docs**: No mentions of internal systems, private repos, or internal URLs
- **Examples work**: Any code examples in README are runnable

## Code Quality

- **No TODO/FIXME/HACK that indicate broken or missing features**: Scan for these and flag any that affect core functionality
- **No commented-out credential blocks**: Patterns like `# API_KEY = "..."` or `# password = ...`
- **No debug print statements left in**: `print("DEBUG")`, `console.log("testing")`, etc.
- **No dev-only code paths that could expose internals**: Hardcoded `if DEBUG:` blocks that expose stack traces or internal data

## Repo Hygiene

- **`.gitignore` covers**: `*.pyc`, `__pycache__/`, `.env*`, `dist/`, `*.egg-info/`, `node_modules/`, `.DS_Store`
- **No large binaries committed**: Files > 5MB that aren't intentional assets (models, images for docs are OK)
- **No build artifacts committed**: `dist/`, `build/`, `*.egg-info/` should not be tracked
- **Branch is clean**: No uncommitted changes that should be part of the release

## Package-Specific (Python)

- **Package name available on PyPI**: `pip index versions <name>` — warn if taken by someone else
- **Version not already published**: Can't overwrite an existing PyPI version
- **`packages.find` scoped**: `[tool.setuptools.packages.find] include = ["<package>*"]` to avoid shipping marketing/docs folders

## Package-Specific (npm/Node)

- **`files` field in package.json**: Whitelist what gets published — don't ship test folders, internal docs
- **`npm pack --dry-run`**: Review what would actually be published

## Final Checklist

After running all checks, output:

```
BLOCKERS (must fix before going public):
- [ ] ...

CONCERNS (should fix, won't break install):
- [ ] ...

READY:
- [x] ...

VERDICT: SHIP / NOT READY
```

If BLOCKERS exist, stop and list them. Do not proceed with publishing.
If only CONCERNS, ask the user if they want to fix them first or ship anyway.
If all clear, confirm: "No blockers found. Ready to publish."
