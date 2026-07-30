# SkillForge frontend

React/Vite frontend for SkillForge. The Flask backend in `app.py` serves the production build and exposes the API used by the interface.

## Development

Install dependencies and start Vite:

```bash
pnpm install
pnpm dev
```

In another terminal, start the backend from the repository root:

```bash
python skill-forge/app.py
```

## Checks and production build

```bash
pnpm lint
pnpm build
```

The build is written to `dist/`, which is intentionally not tracked in Git.
