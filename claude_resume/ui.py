"""Textual TUI for the session picker.

Thin wrapper around claude-session-commons SessionPickerPanel.
All session picker logic lives in the shared package.
"""

from textual.app import App, ComposeResult
from textual.widgets import Header, Footer

from claude_session_commons.tui import SessionOps, SessionPickerPanel


class SessionPickerApp(App):
    """Full-screen session picker with search and preview."""

    CSS = """
    Screen { layout: vertical; }
    """

    BINDINGS = []

    def __init__(self, sessions: list, summaries: list, ops: SessionOps, **kwargs):
        super().__init__(**kwargs)
        self.sessions = sessions
        self.summaries = summaries
        self._ops = ops
        self.result_data = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield SessionPickerPanel(
            self.sessions, self.summaries, self._ops,
            title="claude-resume",
            id="picker",
        )
        yield Footer()

    def on_mount(self) -> None:
        self.title = "claude-resume"
        self.sub_title = "Claude Code Session Recovery"

    def on_session_picker_panel_session_selected(
        self, message: SessionPickerPanel.SessionSelected
    ) -> None:
        if message.action == "multi_resume":
            self.result_data = ("multi_resume", message.idx, message.cmds)
        else:
            self.result_data = (message.action, message.idx, message.cmd)
        self.exit()

    def on_key(self, event) -> None:
        # Panel handles session-specific keys via its own on_key (event bubbling).
        # We only handle keys the panel doesn't consume.
        if event.key == "escape":
            self.exit()
            event.prevent_default()
            event.stop()
        elif event.character == "q":
            self.exit()
            event.prevent_default()
            event.stop()
