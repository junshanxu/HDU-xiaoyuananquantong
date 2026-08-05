---
name: hdu-safety-answer
description: Run, verify, and operate the local HDU safety-education tool. Use when a user wants their own agent to start the repository's localhost service, check a copied platform link, follow progress, or save a generated certificate. Keep credentials local and obtain explicit confirmation before any action that submits course or exam answers.
---

# HDU Safety Education Local Tool

Operate the repository only on the user's computer. This Skill is portable: clients that understand `SKILL.md` can use it; `agents/openai.yaml` is optional UI metadata for Codex-compatible clients.

## Preconditions

- Locate a clone containing `server.py`, `xy_auto.py`, and `xy_bank.json`. Do not download or use a public proxy for this workflow.
- Keep the service bound to `127.0.0.1`. Do not set `HOST` to a non-local address.
- Treat a copied platform link and its `ah` value as credentials. Do not print, repeat, save, commit, upload, or include either in logs.

## Start and check

1. Enter the repository and run `python3 -m py_compile server.py xy_auto.py`.
2. Start the service with `python3 server.py`; confirm it listens at `http://127.0.0.1:8090`.
3. Open `http://127.0.0.1:8090` in the user's browser.
4. Have the user paste their own link. Pasting must not submit anything by itself.

## Confirmation boundary

Before starting the workflow, state that it may complete course work and submit answers to the external platform. Ask for an explicit confirmation such as “开始答题”.

- Do not call the start endpoint, invoke `xy_auto.py` directly, or click the start button before that confirmation.
- For a status-only request, check only whether the local service is running and whether the link can be pasted; do not submit answers or create an exam.

## Completion and privacy

- Follow the local progress panel and report platform errors without exposing credential values.
- When a certificate dialog appears, ask the user to save the image promptly. The in-memory task, logs, and certificate image are automatically removed after 10 minutes.
- Explain precisely: the tool does not persist the token or use a developer server, but the user's computer sends the token directly to the education platform during the current run.

## Failure handling

- For an expired link, ask the user to obtain a fresh link from the platform.
- For an exhausted exam attempt, report whether the local tool found an existing certificate; do not retry automatically.
- For platform errors, preserve the safe error message only and suggest trying again later.
