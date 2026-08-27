"""CustomTkinter GUI for the dev-time-only LLM Flow Recorder.

This module is excluded from the PyInstaller build and is reachable only
through ``main.py --llm-recorder``. It implements the state machine and
sequence diagrams from ``design.md`` ("High-level state machine",
"Per-click sequence", "View-to-device coordinate translation",
"Tap watchdog", and the Logging table).

The class is intentionally self-contained; helper methods are kept short
so the file stays readable and so the manual smoke test in task 11.2 can
exercise each control independently. The acceptance check for the
implementation task is import-only — see task 9.1 — and the behavior is
validated by the smoke-test checklist.

Python 3.8-compatible.
"""

from __future__ import annotations

import concurrent.futures
import threading
import time
import tkinter
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import List, Optional, Tuple, Union

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageTk

from src.dev_tools.llm_recorder import session_store as _session_store
from src.dev_tools.llm_recorder.code_generator import CodeGenerator
from src.dev_tools.llm_recorder.llm_client import LLMClient
from src.dev_tools.llm_recorder.models import (
    ActivityProposal,
    LLMError,
    RecordedStep,
    RecordingSession,
    TemplateProposal,
)
from src.dev_tools.llm_recorder.template_saver import TemplateSaver
from src.utils.logger import Logger

logger = Logger.get_logger(__name__)


# State constants from the design's "High-level state machine" diagram.
STATE_DEVICE_MISSING = "DeviceMissing"
STATE_PREVIEW_READY = "PreviewReady"
STATE_RECORDING = "Recording"
STATE_REVIEWING = "Reviewing"
STATE_ANALYSIS_RUNNING = "AnalysisRunning"
STATE_PROPOSALS_READY = "ProposalsReady"

# Watchdog timeout for any single ADB call, per design Req 3.2.
ADB_WATCHDOG_S = 10

# Preview canvas size (the screenshot is letterboxed inside this rect).
_CANVAS_W = 360
_CANVAS_H = 640

# Tooltip text from the design's "Effect of `enabled=False`" section.
ANALYZE_DISABLED_TOOLTIP = (
    "Set [LLM_TOOLING] enabled = True in settings.ini to use the local "
    "Ollama analysis."
)


def _device_to_resolution(device_manager) -> Tuple[int, int]:
    """Best-effort extraction of device resolution.

    Defaults to ``(1080, 1920)`` per design Open Issue 5. Reading the
    actual ``wm size`` output is not reliable across emulators, so we
    fall back to the project-wide standard.

    Args:
        device_manager: The connected ``DeviceManager`` (unused; kept
            for future extension).

    Returns:
        A ``(width, height)`` tuple.
    """
    return (1080, 1920)


class _Tooltip:
    """Lightweight hover tooltip for ttk/ctk widgets.

    Used to surface the "Analyze with LLM disabled" reason without adding
    a third-party dependency.
    """

    def __init__(self, widget, text: str) -> None:
        self.widget = widget
        self.text = text
        self._tip: Optional[tkinter.Toplevel] = None
        widget.bind("<Enter>", self._show)
        widget.bind("<Leave>", self._hide)

    def _show(self, _event=None) -> None:
        if self._tip is not None or not self.text:
            return
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        tip = tkinter.Toplevel(self.widget)
        tip.wm_overrideredirect(True)
        tip.wm_geometry("+{}+{}".format(x, y))
        label = tkinter.Label(
            tip,
            text=self.text,
            background="#222",
            foreground="#eee",
            relief="solid",
            borderwidth=1,
            wraplength=320,
            justify="left",
            padx=6,
            pady=4,
        )
        label.pack()
        self._tip = tip

    def _hide(self, _event=None) -> None:
        if self._tip is not None:
            self._tip.destroy()
            self._tip = None


class RecorderGUI:
    """CustomTkinter GUI for the dev-time-only LLM Flow Recorder.

    Drives the full Recorder → Reviewer → Analysis → Proposals workflow.
    All ADB interaction is wrapped in a 10-second watchdog and all LLM
    work runs on a background thread; results are marshalled back into
    the Tk main loop with ``self.root.after(0, ...)`` (see design Open
    Issue 6).

    Attributes:
        config: AutoAFK ``Config`` instance.
        device_manager: AutoAFK ``DeviceManager`` instance.
        session: The in-memory ``RecordingSession`` being built or
            reviewed.
        state: Current state from the design's "High-level state machine"
            diagram.
    """

    def __init__(self, config, device_manager) -> None:
        """Initialize the GUI.

        Args:
            config: AutoAFK ``Config`` instance.
            device_manager: AutoAFK ``DeviceManager`` instance.
        """
        self.config = config
        self.device_manager = device_manager

        self.session: RecordingSession = RecordingSession(
            device_resolution=_device_to_resolution(device_manager),
            started_at=time.time(),
        )
        self.state: str = STATE_PREVIEW_READY

        self.template_saver = TemplateSaver()
        self.code_generator = CodeGenerator()
        self.llm_client = LLMClient()
        self.session_store = _session_store.SessionStore()

        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        self._latest_screenshot: Optional[Image.Image] = None
        self._preview_imagetk: Optional[ImageTk.PhotoImage] = None
        # Cached image rect inside the canvas for click-to-device math.
        self._image_rect: Tuple[int, int, int, int] = (0, 0, _CANVAS_W, _CANVAS_H)

        self._templates: List[TemplateProposal] = []
        self._activity: Optional[ActivityProposal] = None

        self._build_ui()
        self._refresh_initial_preview()
        self._refresh_controls()

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def mainloop(self) -> None:
        """Run the Tk main loop until the window closes."""
        try:
            self.root.mainloop()
        finally:
            self._executor.shutdown(wait=False)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        """Construct the root window and its three panels."""
        self.root = ctk.CTk()
        self.root.title("AutoAFK — LLM Flow Recorder (dev only)")
        self.root.geometry("1280x800")

        # Left: live preview + controls.
        left = ctk.CTkFrame(self.root, width=400)
        left.pack(side="left", fill="y", padx=8, pady=8)

        self.banner = ctk.CTkLabel(
            left,
            text="",
            text_color="#ff8a8a",
            wraplength=380,
            justify="left",
        )
        self.banner.pack(fill="x", padx=8, pady=(8, 4))

        self.canvas = tkinter.Canvas(
            left,
            width=_CANVAS_W,
            height=_CANVAS_H,
            bg="#1a1a1a",
            highlightthickness=0,
        )
        self.canvas.pack(padx=8, pady=4)
        self.canvas.bind("<Button-1>", self._on_canvas_click)

        controls = ctk.CTkFrame(left)
        controls.pack(fill="x", padx=8, pady=(4, 8))

        self.btn_start = ctk.CTkButton(
            controls, text="Start Recording", command=self._on_start_recording
        )
        self.btn_start.grid(row=0, column=0, padx=4, pady=4, sticky="ew")
        self.btn_end = ctk.CTkButton(
            controls, text="End Recording", command=self._on_end_recording
        )
        self.btn_end.grid(row=0, column=1, padx=4, pady=4, sticky="ew")
        self.btn_reconnect = ctk.CTkButton(
            controls, text="Reconnect", command=self._on_reconnect
        )
        self.btn_reconnect.grid(row=1, column=0, padx=4, pady=4, sticky="ew")
        self.btn_delete = ctk.CTkButton(
            controls, text="Delete last step", command=self._on_delete_last
        )
        self.btn_delete.grid(row=1, column=1, padx=4, pady=4, sticky="ew")
        self.btn_save = ctk.CTkButton(
            controls, text="Save session", command=self._on_save_session
        )
        self.btn_save.grid(row=2, column=0, padx=4, pady=4, sticky="ew")
        self.btn_load = ctk.CTkButton(
            controls, text="Load session", command=self._on_load_session
        )
        self.btn_load.grid(row=2, column=1, padx=4, pady=4, sticky="ew")
        self.btn_analyze = ctk.CTkButton(
            controls, text="Analyze with LLM", command=self._on_analyze
        )
        self.btn_analyze.grid(
            row=3, column=0, columnspan=2, padx=4, pady=4, sticky="ew"
        )
        controls.grid_columnconfigure(0, weight=1)
        controls.grid_columnconfigure(1, weight=1)

        if not self.config.getboolean("LLM_TOOLING", "enabled", fallback=False):
            _Tooltip(self.btn_analyze, ANALYZE_DISABLED_TOOLTIP)

        self.status = ctk.CTkLabel(
            left, text="state: PreviewReady | steps: 0", anchor="w"
        )
        self.status.pack(fill="x", padx=8, pady=(0, 8))

        # Right: scrollable proposals + activity panels.
        right = ctk.CTkScrollableFrame(self.root)
        right.pack(side="right", fill="both", expand=True, padx=8, pady=8)
        self.right_panel = right

        self.templates_section = ctk.CTkFrame(right)
        self.templates_section.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(
            self.templates_section,
            text="Templates",
            font=("Arial", 14, "bold"),
        ).pack(anchor="w", padx=8, pady=(8, 0))

        self.activity_section = ctk.CTkFrame(right)
        self.activity_section.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(
            self.activity_section,
            text="Activity",
            font=("Arial", 14, "bold"),
        ).pack(anchor="w", padx=8, pady=(8, 0))

    # ------------------------------------------------------------------
    # Initial preview
    # ------------------------------------------------------------------

    def _refresh_initial_preview(self) -> None:
        """Try to fetch a preview screenshot, transition to DeviceMissing on failure."""
        if not getattr(self.device_manager, "connected", False):
            self._enter_device_missing("recorder_device_not_connected")
            return
        try:
            img = self._call_with_watchdog(self.device_manager.get_screenshot)
        except Exception as err:
            self._enter_device_missing(
                "recorder_screenshot_before_failed: {}".format(err)
            )
            return
        if img is None:
            self._enter_device_missing("recorder_device_not_connected")
            return
        self._latest_screenshot = img
        self._draw_preview(img)
        self.state = STATE_PREVIEW_READY

    def _enter_device_missing(self, log_msg: str) -> None:
        """Show the disconnected banner and disable Start (design Req 3.1)."""
        logger.error(log_msg)
        self.state = STATE_DEVICE_MISSING
        self.banner.configure(
            text="Device not connected. Connect ADB and click Reconnect.",
        )

    # ------------------------------------------------------------------
    # Watchdog
    # ------------------------------------------------------------------

    def _call_with_watchdog(self, fn, *args, **kwargs):
        """Run ``fn`` on a worker thread and bound it to ``ADB_WATCHDOG_S``.

        On timeout or exception, the caller is responsible for discarding
        whatever in-progress work this call was part of (per design
        Req 3.2). We do not attempt to cancel the underlying ADB call —
        ``ppadb`` does not support cancellation — but we let it drain in
        the executor while returning control to the GUI thread.

        Args:
            fn: Callable to invoke on the worker thread.
            *args: Positional arguments forwarded to ``fn``.
            **kwargs: Keyword arguments forwarded to ``fn``.

        Returns:
            Whatever ``fn`` returned.

        Raises:
            concurrent.futures.TimeoutError: If ``fn`` did not finish
                within ``ADB_WATCHDOG_S`` seconds.
            Exception: Whatever ``fn`` raised, re-raised in the caller.
        """
        future = self._executor.submit(fn, *args, **kwargs)
        return future.result(timeout=ADB_WATCHDOG_S)

    # ------------------------------------------------------------------
    # Preview rendering & click translation
    # ------------------------------------------------------------------

    def _draw_preview(self, screenshot: Image.Image) -> None:
        """Render ``screenshot`` letterboxed into the canvas."""
        device_w, device_h = screenshot.size
        scale = min(_CANVAS_W / device_w, _CANVAS_H / device_h)
        view_w = max(1, int(device_w * scale))
        view_h = max(1, int(device_h * scale))
        offset_x = (_CANVAS_W - view_w) // 2
        offset_y = (_CANVAS_H - view_h) // 2
        self._image_rect = (offset_x, offset_y, view_w, view_h)

        thumb = screenshot.resize((view_w, view_h), Image.Resampling.LANCZOS)
        self._preview_imagetk = ImageTk.PhotoImage(thumb)
        self.canvas.delete("all")
        self.canvas.create_image(
            offset_x, offset_y, anchor="nw", image=self._preview_imagetk
        )

    def _view_to_device(
        self, view_x: int, view_y: int
    ) -> Optional[Tuple[int, int]]:
        """Translate a canvas click to device-pixel coordinates.

        Returns ``None`` when the click falls outside the displayed
        image rect (per the design's "View-to-device coordinate
        translation" section: clicks outside the image are silently
        ignored — no tap, no step, no log).

        Args:
            view_x: Canvas X coordinate of the click.
            view_y: Canvas Y coordinate of the click.

        Returns:
            ``(device_x, device_y)`` if the click is inside the image
            rect, else ``None``.
        """
        offset_x, offset_y, view_w, view_h = self._image_rect
        if not (offset_x <= view_x < offset_x + view_w):
            return None
        if not (offset_y <= view_y < offset_y + view_h):
            return None
        device_w, device_h = self.session.device_resolution
        device_x = round((view_x - offset_x) * (device_w / view_w))
        device_y = round((view_y - offset_y) * (device_h / view_h))
        # Clamp to valid device range as a final safety net.
        device_x = max(0, min(device_w - 1, device_x))
        device_y = max(0, min(device_h - 1, device_y))
        return device_x, device_y

    # ------------------------------------------------------------------
    # Click handling: per-click sequence from the design
    # ------------------------------------------------------------------

    def _on_canvas_click(self, event) -> None:
        """Handle a click on the preview canvas.

        Implements the per-click sequence from the design's sequence
        diagram: ``screenshot_before`` → ``tap`` →
        ``sleep(tap_settle_ms/1000)`` → ``screenshot_after`` → append
        step → refresh preview. Any failure or watchdog timeout
        discards the in-progress step and leaves prior steps intact
        (Req 3.2).
        """
        if self.state != STATE_RECORDING:
            return
        coords = self._view_to_device(event.x, event.y)
        if coords is None:
            # Click outside the displayed image — silently ignored.
            return
        device_x, device_y = coords

        # screenshot_before
        try:
            before = self._call_with_watchdog(self.device_manager.get_screenshot)
        except concurrent.futures.TimeoutError:
            logger.error("recorder_screenshot_before_timeout: 10s exceeded")
            return
        except Exception as err:
            logger.error("recorder_screenshot_before_failed: {}".format(err))
            return
        if before is None:
            logger.error("recorder_screenshot_before_failed: returned None")
            return

        # tap
        try:
            self._call_with_watchdog(
                self.device_manager.tap, device_x, device_y
            )
        except concurrent.futures.TimeoutError:
            logger.error("recorder_tap_timeout: 10s exceeded")
            return
        except Exception as err:
            logger.error("recorder_tap_failed: {}".format(err))
            return

        # settle delay
        tap_settle_ms = self.config.getint(
            "LLM_TOOLING", "tap_settle_ms", fallback=1000
        )
        time.sleep(max(0, tap_settle_ms) / 1000.0)

        # screenshot_after
        try:
            after = self._call_with_watchdog(self.device_manager.get_screenshot)
        except concurrent.futures.TimeoutError:
            logger.error("recorder_screenshot_after_timeout: 10s exceeded")
            return
        except Exception as err:
            logger.error("recorder_screenshot_after_failed: {}".format(err))
            return
        if after is None:
            logger.error("recorder_screenshot_after_failed: returned None")
            return

        index = len(self.session.steps)
        step = RecordedStep(
            index=index,
            screenshot_before=before,
            screenshot_after=after,
            tap_coords=(device_x, device_y),
            label=None,
        )
        self.session.steps.append(step)
        logger.info("Step {}: tap ({},{})".format(index, device_x, device_y))
        self._latest_screenshot = after
        self._draw_preview(after)
        self._refresh_status()

    # ------------------------------------------------------------------
    # Control handlers
    # ------------------------------------------------------------------

    def _on_start_recording(self) -> None:
        if self.state == STATE_DEVICE_MISSING:
            return
        if not self.session.steps:
            self.session.started_at = time.time()
        self.state = STATE_RECORDING
        logger.blue("Recording session started")
        self._refresh_controls()
        self._refresh_status()

    def _on_end_recording(self) -> None:
        if self.state != STATE_RECORDING:
            return
        self.state = STATE_REVIEWING
        self._refresh_controls()
        self._refresh_status()

    def _on_reconnect(self) -> None:
        try:
            self.device_manager.disconnect()
        except Exception as err:
            logger.error("recorder_disconnect_failed: {}".format(err))
        try:
            ok = bool(self.device_manager.connect())
        except Exception as err:
            logger.error("recorder_reconnect_failed: {}".format(err))
            ok = False
        if not ok:
            self._enter_device_missing("recorder_device_not_connected")
            self._refresh_controls()
            return
        self.banner.configure(text="")
        self._refresh_initial_preview()
        # If we already had steps, keep them (Req 3.3).
        if self.state == STATE_PREVIEW_READY and self.session.steps:
            self.state = STATE_REVIEWING
        self._refresh_controls()
        self._refresh_status()

    def _on_delete_last(self) -> None:
        if not self.session.steps:
            return
        self.session.steps.pop()
        # Re-index so indices remain contiguous (Session_Persistence requires this).
        for i, step in enumerate(self.session.steps):
            step.index = i
        if self.session.steps:
            self._latest_screenshot = self.session.steps[-1].screenshot_after
            self._draw_preview(self._latest_screenshot)
        self._refresh_status()

    def _on_save_session(self) -> None:
        if not self.session.steps:
            messagebox.showinfo(
                "Save session", "Session is empty; nothing to save."
            )
            return
        try:
            target = self.session_store.save(self.session)
        except OSError as err:
            logger.error("session_save_io: {}".format(err))
            messagebox.showerror("Save session failed", str(err))
            return
        logger.green("Saved session {}/".format(target))

    def _on_load_session(self) -> None:
        path = filedialog.askopenfilename(
            title="Load session.json",
            initialdir=str(Path("debug/llm_recorder")),
            filetypes=[("Session JSON", "session.json"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            session = self.session_store.load(Path(path))
        except FileNotFoundError as err:
            logger.error("session_load_missing_file {}".format(err))
            messagebox.showerror("Load session failed", str(err))
            return
        except _session_store.SessionLoadError as err:
            logger.error("session_load_version_mismatch: {}".format(err))
            messagebox.showerror("Load session failed", str(err))
            return
        except Exception as err:
            logger.error("session_load_failed: {}".format(err))
            messagebox.showerror("Load session failed", str(err))
            return
        self.session = session
        if self.session.steps:
            self._latest_screenshot = self.session.steps[-1].screenshot_after
            self._draw_preview(self._latest_screenshot)
        self.state = STATE_REVIEWING
        self._refresh_controls()
        self._refresh_status()

    def _on_analyze(self) -> None:
        enabled = self.config.getboolean(
            "LLM_TOOLING", "enabled", fallback=False
        )
        if not enabled:
            return
        if not self.session.steps:
            messagebox.showinfo(
                "Analyze", "Cannot analyze: recording session has no steps."
            )
            return
        host = self.config.get(
            "LLM_TOOLING", "ollama_host", fallback="http://localhost:11434"
        )
        model = self.config.get(
            "LLM_TOOLING", "model_name", fallback="qwen2.5vl:7b"
        )
        logger.blue(
            "Analyzing {} steps via {} on {}".format(
                len(self.session.steps), model, host
            )
        )
        self.state = STATE_ANALYSIS_RUNNING
        self._refresh_controls()
        self._refresh_status()
        thread = threading.Thread(
            target=self._analyze_worker, name="llm-analyze", daemon=True
        )
        thread.start()

    def _analyze_worker(self) -> None:
        """Run ``LLMClient.analyze`` off the Tk main loop.

        Per design Open Issue 6, the result is marshalled back via
        ``self.root.after(0, ...)`` so all UI mutations happen on the
        main thread.
        """
        try:
            result = self.llm_client.analyze(self.session, self.config)
        except Exception as err:  # pragma: no cover — defensive
            logger.error("llm_analyze_unexpected_error: {}".format(err))
            result = LLMError(
                category="OLLAMA_UNREACHABLE",
                message=str(err),
                raw_excerpt="",
                ollama_host="",
                model_name="",
            )
        self.root.after(0, lambda: self._on_analyze_done(result))

    def _on_analyze_done(
        self,
        result: Union[
            Tuple[List[TemplateProposal], ActivityProposal], LLMError
        ],
    ) -> None:
        if isinstance(result, LLMError):
            messagebox.showerror(
                "LLM Error: {}".format(result.category),
                "{}\n\nHost: {}\nModel: {}\n\n{}".format(
                    result.message,
                    result.ollama_host,
                    result.model_name,
                    result.raw_excerpt,
                ),
            )
            self.state = STATE_REVIEWING
            self._refresh_controls()
            self._refresh_status()
            return

        templates, activity = result
        self._templates = list(templates)
        self._activity = activity
        self.state = STATE_PROPOSALS_READY
        self._render_proposals()
        self._refresh_controls()
        self._refresh_status()

    # ------------------------------------------------------------------
    # Proposals rendering
    # ------------------------------------------------------------------

    def _render_proposals(self) -> None:
        """Re-render templates + activity sections from current state."""
        for child in list(self.templates_section.winfo_children())[1:]:
            child.destroy()
        for child in list(self.activity_section.winfo_children())[1:]:
            child.destroy()

        for tpl in self._templates:
            self._render_template_card(tpl)

        if self._activity is not None:
            self._render_activity_card(self._activity)

    def _render_template_card(self, tpl: TemplateProposal) -> None:
        """Render one ``TemplateProposal`` row with editable fields."""
        card = ctk.CTkFrame(self.templates_section)
        card.pack(fill="x", padx=8, pady=4)

        # Source screenshot with bbox overlay.
        if 0 <= tpl.source_step_index < len(self.session.steps):
            source = self.session.steps[tpl.source_step_index].screenshot_before
            overlay = source.copy()
            draw = ImageDraw.Draw(overlay)
            x, y, w, h = tpl.bbox
            draw.rectangle((x, y, x + w, y + h), outline="red", width=4)
            overlay.thumbnail((180, 320), Image.Resampling.LANCZOS)
            tk_img = ImageTk.PhotoImage(overlay)
            preview = tkinter.Label(card, image=tk_img, bg="#1a1a1a")
            preview.image = tk_img  # type: ignore[attr-defined]  # keep ref
            preview.pack(side="left", padx=4, pady=4)

        right = ctk.CTkFrame(card)
        right.pack(side="left", fill="both", expand=True, padx=4, pady=4)

        ctk.CTkLabel(right, text="filename:").grid(row=0, column=0, sticky="w")
        filename_var = ctk.StringVar(value=tpl.filename)
        ctk.CTkEntry(right, textvariable=filename_var, width=260).grid(
            row=0, column=1, columnspan=4, sticky="ew", padx=4, pady=2
        )

        bbox_vars = {}
        for col, key in enumerate(("x", "y", "w", "h")):
            ctk.CTkLabel(right, text=key).grid(row=1, column=col, sticky="e")
            v = ctk.StringVar(value=str(tpl.bbox[col]))
            bbox_vars[key] = v
            ctk.CTkEntry(right, textvariable=v, width=70).grid(
                row=2, column=col, sticky="ew", padx=2, pady=2
            )

        ctk.CTkLabel(right, text="rationale:").grid(row=3, column=0, sticky="w")
        rationale_var = ctk.StringVar(value=tpl.rationale)
        ctk.CTkEntry(right, textvariable=rationale_var, width=260).grid(
            row=3, column=1, columnspan=4, sticky="ew", padx=4, pady=2
        )

        def on_save() -> None:
            try:
                tpl.filename = filename_var.get().strip()
                tpl.bbox = (
                    int(bbox_vars["x"].get()),
                    int(bbox_vars["y"].get()),
                    int(bbox_vars["w"].get()),
                    int(bbox_vars["h"].get()),
                )
                tpl.rationale = rationale_var.get()
            except ValueError as err:
                logger.error("template_save_invalid_input: {}".format(err))
                messagebox.showerror("Invalid input", str(err))
                return
            self._save_template(tpl)

        def on_skip() -> None:
            card.destroy()
            if tpl in self._templates:
                self._templates.remove(tpl)

        ctk.CTkButton(right, text="Save", command=on_save, width=80).grid(
            row=4, column=0, padx=2, pady=4
        )
        ctk.CTkButton(right, text="Skip", command=on_skip, width=80).grid(
            row=4, column=1, padx=2, pady=4
        )

    def _save_template(self, tpl: TemplateProposal) -> None:
        """Save ``tpl`` via ``TemplateSaver`` with overwrite confirmation."""
        try:
            target = self.template_saver.save(tpl, self.session, force=False)
        except FileExistsError as exc:
            existing = str(exc)
            if not messagebox.askyesno(
                "Overwrite existing template?",
                "A template already exists at:\n\n{}\n\nOverwrite it?".format(
                    existing
                ),
            ):
                return
            try:
                target = self.template_saver.save(
                    tpl, self.session, force=True
                )
            except (ValueError, OSError) as err:
                logger.error(
                    "template_save_failed {}: {}".format(existing, err)
                )
                messagebox.showerror("Save template failed", str(err))
                return
        except ValueError as err:
            messagebox.showerror("Save template failed", str(err))
            return
        except OSError as err:
            logger.error("template_save_failed: {}".format(err))
            messagebox.showerror("Save template failed", str(err))
            return
        tpl.accepted = True
        logger.green("Saved template {}".format(target))

    def _render_activity_card(self, activity: ActivityProposal) -> None:
        """Render the editable activity panel and its three copy buttons."""
        card = ctk.CTkFrame(self.activity_section)
        card.pack(fill="x", padx=8, pady=4)

        header = ctk.CTkFrame(card)
        header.pack(fill="x", padx=4, pady=2)
        ctk.CTkLabel(header, text="module:").grid(row=0, column=0, sticky="w")
        module_var = ctk.StringVar(value=activity.module_filename)
        ctk.CTkEntry(header, textvariable=module_var, width=260).grid(
            row=0, column=1, sticky="ew", padx=4
        )
        ctk.CTkLabel(header, text="class:").grid(row=0, column=2, sticky="w")
        class_var = ctk.StringVar(value=activity.class_name)
        ctk.CTkEntry(header, textvariable=class_var, width=200).grid(
            row=0, column=3, sticky="ew", padx=4
        )

        ctk.CTkLabel(card, text="source_text (editable):").pack(
            anchor="w", padx=4
        )
        source_box = ctk.CTkTextbox(card, height=240, font=("Courier", 11))
        source_box.pack(fill="both", expand=True, padx=4, pady=2)
        source_box.insert("1.0", activity.source_text)

        snippets = ctk.CTkFrame(card)
        snippets.pack(fill="x", padx=4, pady=4)

        registration = activity.registration_snippet
        call_site = activity.call_site_snippet
        config_toggle = "[{section}]\n{key} = False".format(
            section=activity.config_section, key=activity.config_key
        )

        def make_copy(text: str):
            def copy() -> None:
                self.root.clipboard_clear()
                self.root.clipboard_append(text)
            return copy

        ctk.CTkButton(
            snippets,
            text="Copy registration snippet",
            command=make_copy(registration),
        ).grid(row=0, column=0, padx=2, pady=2, sticky="ew")
        ctk.CTkButton(
            snippets,
            text="Copy call-site snippet",
            command=make_copy(call_site),
        ).grid(row=0, column=1, padx=2, pady=2, sticky="ew")
        ctk.CTkButton(
            snippets,
            text="Copy settings.ini toggle",
            command=make_copy(config_toggle),
        ).grid(row=0, column=2, padx=2, pady=2, sticky="ew")

        def on_save_activity() -> None:
            activity.module_filename = module_var.get().strip()
            activity.class_name = class_var.get().strip()
            activity.source_text = source_box.get("1.0", "end-1c")
            self._save_activity(activity)

        ctk.CTkButton(
            card, text="Save Activity", command=on_save_activity
        ).pack(anchor="e", padx=4, pady=4)

    def _save_activity(self, activity: ActivityProposal) -> None:
        """Save ``activity`` via ``CodeGenerator`` with overwrite confirmation."""
        try:
            target = self.code_generator.save(activity, force=False)
        except FileExistsError as exc:
            existing = str(exc.args[0]) if exc.args else ""
            if not messagebox.askyesno(
                "Overwrite existing activity?",
                "An activity already exists at:\n\n{}\n\nOverwrite it?".format(
                    existing
                ),
            ):
                return
            try:
                target = self.code_generator.save(activity, force=True)
            except SyntaxError as err:
                logger.error(
                    "activity_save_syntax_error: line {}: {}".format(
                        err.lineno, err.msg
                    )
                )
                messagebox.showerror("Save activity failed", str(err))
                return
            except (ValueError, OSError) as err:
                logger.error("activity_save_failed: {}".format(err))
                messagebox.showerror("Save activity failed", str(err))
                return
        except SyntaxError as err:
            logger.error(
                "activity_save_syntax_error: line {}: {}".format(
                    err.lineno, err.msg
                )
            )
            messagebox.showerror("Save activity failed", str(err))
            return
        except ValueError as err:
            messagebox.showerror("Save activity failed", str(err))
            return
        except OSError as err:
            logger.error("activity_save_failed: {}".format(err))
            messagebox.showerror("Save activity failed", str(err))
            return
        activity.accepted = True
        logger.green("Wrote {}".format(target))

    # ------------------------------------------------------------------
    # Status / control state
    # ------------------------------------------------------------------

    def _refresh_status(self) -> None:
        self.status.configure(
            text="state: {} | steps: {}".format(
                self.state, len(self.session.steps)
            )
        )

    def _refresh_controls(self) -> None:
        """Enable/disable buttons based on ``self.state`` and config."""

        def _set(btn, enabled: bool) -> None:
            btn.configure(state="normal" if enabled else "disabled")

        is_recording = self.state == STATE_RECORDING
        device_ok = self.state != STATE_DEVICE_MISSING
        analysis_running = self.state == STATE_ANALYSIS_RUNNING

        _set(self.btn_start, device_ok and not is_recording and not analysis_running)
        _set(self.btn_end, is_recording)
        _set(self.btn_reconnect, not analysis_running)
        _set(
            self.btn_delete,
            bool(self.session.steps) and not analysis_running,
        )
        _set(
            self.btn_save,
            bool(self.session.steps) and not analysis_running,
        )
        _set(self.btn_load, not is_recording and not analysis_running)

        llm_enabled = self.config.getboolean(
            "LLM_TOOLING", "enabled", fallback=False
        )
        _set(
            self.btn_analyze,
            llm_enabled
            and not is_recording
            and not analysis_running
            and bool(self.session.steps),
        )
