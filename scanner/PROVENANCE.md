# Portable Trip Bot source

Upstream: https://github.com/baka9881/trip-bot

Pinned commit: `baf9dfee219f396b83b6face4b085ee995d15530`.

Export allowlist: tracked `package.json`, `package-lock.json`, `tsconfig.json`, and `src/` from that commit. No checkout history, environment files, live state, browser sessions, or original Windows launchers are included. This is a modified snapshot, not an unchanged upstream checkout.

Portability changes:

- `src/telegram.ts`: remove all account/environment/configuration reads and all HTTP delivery; retain formatting helpers and the caller-compatible function, which writes segment text once to stdout. Native Hermes owns delivery. Photos and Telegram buttons are not sent by this local boundary.
- `src/cli.ts`: reject `--telegram` before dispatch and remove the misleading Telegram-success path. Tick, background jobs and alert callbacks use the same local boundary.
- `src/local-delivery.test.ts`: assert local text output and zero HTTP calls.
- `../scripts/scan-trip.py`: explicit Node/tsx/CLI paths, isolated DB override, one-root ownership marker and OS process lock. The wrapper does not print a second copy of scanner output. It never imports the live Hermes configuration.

Each installation needs its own scanner checkout because upstream JSON caches/settings are source-relative. On first wrapper use, an empty `data/` is bound to its Hermes root using `data/workflow-owner.json`. A different root or unowned nonempty data directory is refused. Retain the marker with private backups, never commit it. Native jobs should invoke the wrapper, not the TypeScript entry point directly. The lock persists as a file and is released by the OS; no cleanup deletion is necessary.

Install dependencies using `npm ci --ignore-scripts` in this directory. Requires Node >=24. Existing upstream tests use synthetic temporary SQLite and retain their files. Run `npm test` and `npm run typecheck`. Browser-backed live searches additionally require the matching Playwright browser installed explicitly (`npx playwright install chromium`); fixture tests and local preference/region commands do not require a browser. No real scan or external delivery is part of package verification.

The wrapper deliberately does not impose a timeout that could orphan Node's own long-running verification children. Schedule executions must not overlap: the wrapper holds an OS lock for the full child lifetime and reports a skipped overlap. Do not terminate a running gateway job merely to clean up its data.
