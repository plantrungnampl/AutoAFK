"""CustomTkinter GUI for the dev-time-only LLM Agent.

Hosts an :class:`AgentLoop` on a background thread and exposes Approve /
Skip / Stop / Trust-mode controls. Marshals every UI mutation back to the
Tk main loop via ``self.root.after(0, ...)`` (same pattern as the
recorder).
"""

from __future__ import annotations

import queue
import threading
import tkinter
from typing import Optional, Tuple, Union

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageTk

from src.dev_tools.llm_agent.agent_client import AgentClient
from src.dev_tools.llm_agent.agent_loop import (
    AgentLoop, AgentLoopCallbacks, AgentResult,
)
from src.dev_tools.llm_agent.models import (
    AgentAction, AgentError, AgentSession, AgentStep,
)
from src.utils.logger import Logger

logger = Logger.get_logger(__name__)


_CANVAS_W = 360
_CANVAS_H = 640
_AGENT_DISABLED_TOOLTIP = (
    "Set [LLM_AGENT] enabled = True in settings.ini to use the agent."
)


class _Tooltip:
    """Tiny hover tooltip — copied from recorder for self-containment."""

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
        tkinter.Label(
            tip, text=self.text, background="#222", foreground="#eee",
            relief="solid", borderwidth=1, wraplength=320, justify="left",
            padx=6, pady=4,
        ).pack()
        self._tip = tip

    def _hide(self, _event=None) -> None:
        if self._tip is not None:
            self._tip.destroy()
            self._tip = None


class AgentGUI:
    """Top-level CustomTkinter window for the agent.

    Attributes:
        config: AutoAFK ``Config`` instance.
        device_manager: AutoAFK ``DeviceManager`` instance.
    """

    def __init__(self, config, device_manager) -> None:
        self.config = config
        self.device_manager = device_manager
        self.client = AgentClient()
        self._confirm_request_q: "queue.Queue[AgentAction]" = queue.Queue()
        self._confirm_response_q: "queue.Queue[Union[bool, str]]" = queue.Queue()
        self._loop_thread: Optional[threading.Thread] = None
        self._session: Optional[AgentSession] = None
        self._latest_screenshot: Optional[Image.Image] = None
        self._preview_imagetk: Optional[ImageTk.PhotoImage] = None
        self._image_rect: Tuple[int, int, int, int] = (0, 0, _CANVAS_W, _CANVAS_H)
        self._build_ui()
        self._refresh_initial_preview()

    def mainloop(self) -> None:
        """Run the Tk main loop until the window closes."""
        self.root.mainloop()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.root = ctk.CTk()
        self.root.title("AutoAFK — LLM Agent (dev only)")
        self.root.geometry("1280x800")

        left = ctk.CTkFrame(self.root, width=400)
        left.pack(side="left", fill="y", padx=8, pady=8)

        self.banner = ctk.CTkLabel(
            left, text="", text_color="#ff8a8a",
            wraplength=380, justify="left",
        )
        self.banner.pack(fill="x", padx=8, pady=(8, 4))

        self.canvas = tkinter.Canvas(
            left, width=_CANVAS_W, height=_CANVAS_H,
            bg="#1a1a1a", highlightthickness=0,
        )
        self.canvas.pack(padx=8, pady=4)

        self.status = ctk.CTkLabel(
            left, text="state: idle | steps: 0/0", anchor="w",
        )
        self.status.pack(fill="x", padx=8, pady=(0, 8))

        right = ctk.CTkFrame(self.root)
        right.pack(side="right", fill="both", expand=True, padx=8, pady=8)

        ctk.CTkLabel(right, text="Goal:").pack(anchor="w", padx=8, pady=(8, 2))
        self.goal_entry = ctk.CTkEntry(
            right, placeholder_text="e.g. collect daily login reward",
        )
        self.goal_entry.pack(fill="x", padx=8, pady=(0, 8))

        controls = ctk.CTkFrame(right)
        controls.pack(fill="x", padx=8, pady=(0, 8))
        self.btn_start = ctk.CTkButton(
            controls, text="Start", command=self._on_start
        )
        self.btn_start.grid(row=0, column=0, padx=4, pady=4, sticky="ew")
        self.btn_stop = ctk.CTkButton(
            controls, text="Stop", command=self._on_stop, state="disabled"
        )
        self.btn_stop.grid(row=0, column=1, padx=4, pady=4, sticky="ew")
        self.trust_var = tkinter.BooleanVar(value=False)
        self.trust_checkbox = ctk.CTkCheckBox(
            controls, text="Trust mode", variable=self.trust_var,
            command=self._on_trust_toggle,
        )
        self.trust_checkbox.grid(row=0, column=2, padx=4, pady=4, sticky="ew")
        controls.grid_columnconfigure(0, weight=1)
        controls.grid_columnconfigure(1, weight=1)
        controls.grid_columnconfigure(2, weight=1)

        if not self.config.getboolean("LLM_AGENT", "enabled", fallback=False):
            self.btn_start.configure(state="disabled")
            _Tooltip(self.btn_start, _AGENT_DISABLED_TOOLTIP)

        self.history_panel = ctk.CTkScrollableFrame(right)
        self.history_panel.pack(fill="both", expand=True, padx=8, pady=8)

        # Confirmation panel sits inside history_panel, populated dynamically.
        self._pending_card: Optional[ctk.CTkFrame] = None

    # ------------------------------------------------------------------
    # Initial preview
    # ------------------------------------------------------------------

    def _refresh_initial_preview(self) -> None:
        if not getattr(self.device_manager, "connected", False):
            self.banner.configure(
                text="Device not connected. Connect ADB first."
            )
            return
        try:
            img = self.device_manager.get_screenshot()
        except Exception as err:
            logger.error("agent_initial_screenshot_failed: %s", err)
            self.banner.configure(text="Screenshot failed: {}".format(err))
            return
        if img is None:
            self.banner.configure(text="Device not connected.")
            return
        self._latest_screenshot = img
        self._draw_preview(img)

    # ------------------------------------------------------------------
    # Preview rendering
    # ------------------------------------------------------------------

    def _draw_preview(
        self, screenshot: Image.Image, overlay_action: Optional[AgentAction] = None,
    ) -> None:
        device_w, device_h = screenshot.size
        scale = min(_CANVAS_W / device_w, _CANVAS_H / device_h)
        view_w = max(1, int(device_w * scale))
        view_h = max(1, int(device_h * scale))
        offset_x = (_CANVAS_W - view_w) // 2
        offset_y = (_CANVAS_H - view_h) // 2
        self._image_rect = (offset_x, offset_y, view_w, view_h)
        thumb = screenshot.resize((view_w, view_h), Image.LANCZOS)
        if overlay_action is not None:
            draw = ImageDraw.Draw(thumb)
            if overlay_action.kind == "tap":
                cx = int(overlay_action.x * scale)
                cy = int(overlay_action.y * scale)
                draw.ellipse((cx - 12, cy - 12, cx + 12, cy + 12),
                             outline="red", width=3)
            elif overlay_action.kind == "swipe":
                draw.line(
                    (
                        int(overlay_action.x1 * scale),
                        int(overlay_action.y1 * scale),
                        int(overlay_action.x2 * scale),
                        int(overlay_action.y2 * scale),
                    ),
                    fill="red", width=3,
                )
        self._preview_imagetk = ImageTk.PhotoImage(thumb)
        self.canvas.delete("all")
        self.canvas.create_image(
            offset_x, offset_y, anchor="nw", image=self._preview_imagetk
        )

    # ------------------------------------------------------------------
    # Control handlers
    # ------------------------------------------------------------------

    def _on_start(self) -> None:
        goal = self.goal_entry.get().strip()
        if not goal:
            self.banner.configure(text="Enter a goal first.")
            return
        if self._loop_thread and self._loop_thread.is_alive():
            return
        self.banner.configure(text="")
        self._session = AgentSession(
            goal=goal,
            max_steps=self.config.getint("LLM_AGENT", "max_steps", fallback=20),
            history_window=self.config.getint(
                "LLM_AGENT", "history_window", fallback=3
            ),
            trust_mode=self.trust_var.get(),
        )
        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.goal_entry.configure(state="disabled")
        for child in self.history_panel.winfo_children():
            child.destroy()
        logger.blue("Agent loop started: goal={}".format(goal))
        self._loop_thread = threading.Thread(
            target=self._loop_worker, name="agent-loop", daemon=True
        )
        self._loop_thread.start()

    def _on_stop(self) -> None:
        if self._pending_card is not None:
            self._confirm_response_q.put("stop")
        # Otherwise the loop will drain on its next confirm point.
        self.btn_stop.configure(state="disabled")

    def _on_trust_toggle(self) -> None:
        if self._session is not None:
            self._session.trust_mode = self.trust_var.get()

    # ------------------------------------------------------------------
    # Loop worker (background thread)
    # ------------------------------------------------------------------

    def _loop_worker(self) -> None:
        cbs = AgentLoopCallbacks(
            request_confirm=self._request_confirm_blocking,
            render_step=lambda s: self.root.after(0, self._render_step, s),
            render_error=lambda e: self.root.after(0, self._render_error, e),
        )
        loop = AgentLoop(self.client, self.device_manager, cbs, self.config)
        try:
            result = loop.run(self._session)
        except Exception as exc:  # pragma: no cover — defensive
            logger.error("agent_loop_unexpected: %s", exc)
            result = AgentResult(error=AgentError(
                category="ADB_FAILURE", message=str(exc)
            ))
        self.root.after(0, self._on_loop_finished, result)

    def _request_confirm_blocking(
        self, action: AgentAction
    ) -> Union[bool, str]:
        """Called on loop thread; blocks until GUI replies."""
        self.root.after(0, self._show_confirm_card, action)
        return self._confirm_response_q.get()

    # ------------------------------------------------------------------
    # GUI side: render confirm card and step rows
    # ------------------------------------------------------------------

    def _show_confirm_card(self, action: AgentAction) -> None:
        if self._latest_screenshot is not None:
            self._draw_preview(self._latest_screenshot, overlay_action=action)
        card = ctk.CTkFrame(self.history_panel, border_width=2)
        card.pack(fill="x", padx=4, pady=4)
        ctk.CTkLabel(card, text=self._action_summary(action),
                     font=("Arial", 14, "bold")).pack(anchor="w", padx=6, pady=(6, 0))
        ctk.CTkLabel(card, text=action.rationale or "(no rationale)",
                     wraplength=520, justify="left").pack(anchor="w", padx=6, pady=2)
        btns = ctk.CTkFrame(card)
        btns.pack(fill="x", padx=6, pady=4)
        ctk.CTkButton(
            btns, text="Approve",
            command=lambda: self._respond_confirm(True, card),
        ).pack(side="left", padx=4)
        ctk.CTkButton(
            btns, text="Skip",
            command=lambda: self._respond_confirm(False, card),
        ).pack(side="left", padx=4)
        ctk.CTkButton(
            btns, text="Stop",
            command=lambda: self._respond_confirm("stop", card),
        ).pack(side="left", padx=4)
        self._pending_card = card

    def _respond_confirm(
        self, response: Union[bool, str], card: ctk.CTkFrame
    ) -> None:
        if self._pending_card is card:
            self._pending_card = None
        for child in card.winfo_children():
            child.destroy()
        ctk.CTkLabel(
            card, text=("approved" if response is True else
                        "skipped" if response is False else "stop"),
            text_color="#4caf50" if response else "#aaa",
        ).pack(anchor="w", padx=6, pady=4)
        self._confirm_response_q.put(response)

    def _render_step(self, step: AgentStep) -> None:
        self._latest_screenshot = step.screenshot
        self._draw_preview(step.screenshot)
        if self._session is None:
            return
        self.status.configure(
            text="state: running | steps: {}/{}".format(
                len(self._session.steps), self._session.max_steps
            )
        )
        if step.proposed.kind == "done":
            row = ctk.CTkFrame(self.history_panel)
            row.pack(fill="x", padx=4, pady=2)
            ctk.CTkLabel(
                row,
                text="Step {}: DONE — {}".format(step.index, step.proposed.done_reason),
                text_color="#4caf50",
            ).pack(anchor="w", padx=6, pady=4)

    def _render_error(self, error: AgentError) -> None:
        from tkinter import messagebox

        messagebox.showerror(
            "Agent error: {}".format(error.category),
            "{}\n\nHost: {}\nModel: {}\n\n{}".format(
                error.message, error.ollama_host, error.model_name,
                error.raw_excerpt,
            ),
        )

    def _on_loop_finished(self, result: AgentResult) -> None:
        if self._session is None:
            return
        if result.done:
            logger.green("Agent done: {}".format(result.done_reason))
            self.banner.configure(text="Done: {}".format(result.done_reason),
                                  text_color="#4caf50")
        elif result.stopped:
            logger.purple("Agent stopped by user")
            self.banner.configure(text="Stopped by user", text_color="#ffd54f")
        elif result.error is not None:
            self.banner.configure(
                text="Error: {}".format(result.error.category),
                text_color="#ff8a8a",
            )
        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        self.goal_entry.configure(state="normal")

    @staticmethod
    def _action_summary(action: AgentAction) -> str:
        if action.kind == "tap":
            return "Step proposal: tap ({}, {})".format(action.x, action.y)
        if action.kind == "swipe":
            return "Step proposal: swipe ({},{}) → ({},{})".format(
                action.x1, action.y1, action.x2, action.y2
            )
        if action.kind == "wait":
            return "Step proposal: wait {:.1f}s".format(action.seconds)
        return "Step proposal: {}".format(action.kind)
