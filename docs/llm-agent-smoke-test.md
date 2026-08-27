# LLM Agent — Manual Smoke Test

Manual checklist for the dev-time-only LLM Agent. Runs against a real
ADB device + local Ollama.

## Prerequisites

- `pip install -r requirements-dev.txt`
- Ollama reachable at `http://localhost:11434`
- `ollama pull qwen2.5vl:3b`
- `[LLM_AGENT] enabled=True` in `settings.ini`
- ADB device at 1080×1920 portrait, DPI 240

## Checklist

1. - [ ] **Launch with no device** — `adb kill-server`, then
       `python main.py --llm-agent`. Expected: banner reads
       "Device not connected", **Start** is disabled.

2. - [ ] **Launch with `enabled=False`** — set the flag, relaunch.
       Expected: GUI opens but **Start** disabled with tooltip
       "Set [LLM_AGENT] enabled = True in settings.ini to use the agent."

3. - [ ] **Start with Ollama stopped** — connect a device,
       `systemctl --user stop ollama`, type a goal, click **Start**.
       Expected: `OLLAMA_UNREACHABLE` modal showing host + model name.

4. - [ ] **Start with missing model** — set
       `model_name=nonexistent:0.1b`, restart, type goal, **Start**.
       Expected: `MODEL_MISSING` modal with the upstream message
       containing "model not found".

5. - [ ] **Approve a tap** — Ollama running, real model. Goal:
       "tap the home icon at the bottom of the screen". After ~30–60 s a
       card appears. Approve. Preview refreshes; the device received the
       tap; the step is logged with ✓ approved & executed.

6. - [ ] **Skip a tap** — same goal as above. Click Skip on the next
       proposal. Expected: step is logged but `executed=False`; the
       device received no tap; loop continues.

7. - [ ] **Stop mid-run** — wait for any pending action card, click
       **Stop**. Expected: banner shows "Stopped by user"; no further
       actions execute; controls re-enable.

8. - [ ] **Reach `done`** — give a tight goal like "tap the very center
       of the screen". The model should return a tap, then on the next
       iteration return `kind="done"`. Expected: banner turns green with
       "Done: ..."; controls re-enable.
