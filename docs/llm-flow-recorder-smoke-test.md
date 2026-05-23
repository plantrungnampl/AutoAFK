# LLM Flow Recorder — Manual Smoke Test

Manual checklist for validating the dev-time LLM Flow Recorder before merging
changes. Run through every item against a real Android emulator session
(Genymotion, Waydroid, Bluestacks, LDPlayer…) at 1080×1920 portrait with a
local Ollama instance reachable. For full context see
[`.kiro/specs/llm-flow-recorder/design.md`](../.kiro/specs/llm-flow-recorder/design.md)
and [`.kiro/specs/llm-flow-recorder/tasks.md`](../.kiro/specs/llm-flow-recorder/tasks.md).
Each item is annotated with the requirement it covers.

## Prerequisites

- `pip install -r requirements-dev.txt`
- Ollama installed and reachable at `http://localhost:11434`
- `ollama pull qwen2.5vl:7b` (the older `qwen2-vl` tag is no longer published)
- `[LLM_TOOLING] enabled=True` in `settings.ini`
- An ADB-connected emulator or device at 1080×1920 portrait, DPI 240
  (Genymotion Pixel 5 image, Waydroid, Bluestacks, LDPlayer, etc.)

## Checklist

1. - [ ] **Launch with no device connected** — Start `python main.py --llm-recorder`
       with ADB reporting no device. Expected: a "device not connected" banner is
       displayed and the **Start** button is disabled. _(Req 3.1)_

2. - [ ] **Launch with device connected** — Start `python main.py --llm-recorder`
       with a connected device. Expected: the live preview pane renders the
       current device screen. _(Req 2.1)_

3. - [ ] **Record 3 steps** — Click Start, then perform three taps in the
       preview. Expected: 3 step entries are listed, each with a non-empty
       before-PNG and after-PNG held in memory. _(Req 2.4)_

4. - [ ] **Delete last step** — From the 3-step recording above, click the
       delete control on the most recent step. Expected: the visible step
       count drops from 3 to 2. _(Req 2.8)_

5. - [ ] **Save session** — With 3 steps recorded, click Save. Expected: a
       directory `debug/llm_recorder/<timestamp>/` is created containing
       `session.json` plus 6 PNG files (before/after for each of the 3 steps).
       _(Req 9.1)_

6. - [ ] **Load saved session in a fresh launch** — Quit the recorder, relaunch
       `python main.py --llm-recorder`, and load the session saved in item 5.
       Expected: all 3 steps are reconstructed in the UI with no errors logged.
       _(Req 9.2)_

7. - [ ] **Analyze with Ollama stopped** — Stop the local Ollama service and
       click Analyze. Expected: an `OLLAMA_UNREACHABLE` modal is shown that
       includes both the configured host and model name. _(Req 5.2)_

8. - [ ] **Analyze with a missing model** — Set `model_name = nope:1b` in
       `settings.ini` (or the recorder UI), restart, and click Analyze.
       Expected: a `MODEL_MISSING` modal is shown displaying the upstream
       error message from Ollama. _(Req 5.3)_

9. - [ ] **Analyze happy path** — With Ollama running and a valid model
       configured, click Analyze on a 3-step recording. Expected: at least one
       `TemplateProposal` is rendered and exactly one `ActivityProposal` is
       displayed. _(Req 6.1, 6.2)_

10. - [ ] **Save a template** — From a `TemplateProposal`, click Save Template.
        Expected: a new PNG file appears under either `img/buttons/` or
        `img/labels/` whose path matches `^(buttons|labels)/[a-z0-9_]+\.png$`.
        _(Req 7.4)_

11. - [ ] **Edit and save the activity** — Edit the `ActivityProposal` source
        text, then click Save Activity. Expected: a new file appears under
        `src/activities/` and the following command exits with status 0:

        ```bash
        python -c "import ast; ast.parse(open('src/activities/<filename>').read())"
        ```

        _(Req 8.5)_

12. - [ ] **Production runtime unaffected** — Run `python main.py --dailies`
        without the recorder flag. Expected: dailies execute normally with no
        recorder-related imports, log messages, or behavior changes. _(Req 1.5)_

13. - [ ] **Recorder excluded from build** — Run `build.bat` to produce a
        Windows `.exe`. Expected: `dist/AutoAFK/AutoAFK.exe` exists and the
        bundled `dist/AutoAFK/_internal/` tree contains no `src/dev_tools`
        files. Verify with the command from `design.md` → Verification:

        ```bash
        # Linux / WSL / Git Bash
        find dist/AutoAFK -path '*src/dev_tools*'   # expected: no output
        ```

        ```powershell
        # Windows PowerShell equivalent
        Get-ChildItem -Path dist\AutoAFK -Recurse -Filter *.* |
            Where-Object { $_.FullName -like '*src\dev_tools*' }
        # expected: no output
        ```

        _(Req 1.3)_
