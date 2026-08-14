"""UI kit for channel-tui — 1:1 ports of dsh-TUI\'s visual design.

Design-system pieces (Divider, ProgressBar, StatusIcon, Byline), the pixel-
whale renderer (upper/lower half-blocks + 24-bit RGB), big-font glyphs and
the blue-white shimmer sweep. All return Textual markup strings.
"""
from __future__ import annotations

try:  # imported as a plugin submodule (PluginManager sets __package__)
    from .bigfont_data import GLYPHS
    from .whale_data import FRAMES
except ImportError:  # direct import in tests / standalone
    from bigfont_data import GLYPHS
    from whale_data import FRAMES

# ---- palette (whale) ----
_PALETTE = {
    "D": (20, 38, 96),
    "B": (78, 111, 255),
    "L": (190, 225, 255),
    "W": (255, 255, 255),
}

# ---- shimmer ladder (dsh-TUI) ----
BRAND = (77, 107, 254)
ICE = (147, 190, 255)
PALE = (215, 228, 255)
FLASH = (198, 216, 248)


def _hex(rgb) -> str:
    r, g, b = rgb
    return f"#{r:02x}{g:02x}{b:02x}"


def _lerp(a, b, t: float):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


# ---- design system ----
def divider(title: str = "", color: str | None = None, char: str = "-", width: int = 60) -> str:
    """A horizontal divider line, optionally with a centered title."""
    if title and len(title) < width:
        left = char * ((width - len(title)) // 2)
        right = char * (width - len(title) - len(left))
        line = f"{left}{title}{right}"
    else:
        line = char * width
    if color:
        return f"[{color}]{line}[/]"
    return f"[dim]{line}[/]"


_BLOCKS = [" ", "\u258f", "\u258e", "\u258d", "\u258c", "\u258b", "\u258a", "\u2589", "\u2588"]


def progress_bar(ratio: float, width: int = 20, fill: str = "#7c5cff", empty: str = "#161b22") -> str:
    """Block progress bar: full cells + sub-cell ladder + empty remainder."""
    ratio = max(0.0, min(1.0, ratio))
    whole = int(ratio * width)
    cells = [_BLOCKS[-1] * whole]
    if whole < width:
        remainder = ratio * width - whole
        cells.append(_BLOCKS[min(int(remainder * len(_BLOCKS)), len(_BLOCKS) - 1)])
        empty_n = width - whole - 1
        if empty_n > 0:
            cells.append(_BLOCKS[0] * empty_n)
    body = "".join(cells)
    return f"[{fill} on {empty}]{body}[/]"


_STATUS_ICONS = {
    "success": ("+", "#3fb950"),
    "error": ("x", "#f85149"),
    "warning": ("!", "#d29922"),
    "info": ("i", "#58a6ff"),
    "pending": ("o", ""),
    "loading": ("...", ""),
}


def status_icon(status: str, with_space: bool = False) -> str:
    icon, color = _STATUS_ICONS.get(status, ("o", ""))
    s = f"[{color}]{icon}[/]" if color else f"[dim]{icon}[/]"
    return s + (" " if with_space else "")


def byline(*parts) -> str:
    """Inline metadata joined with middot separators."""
    parts = [p for p in parts if p]
    if not parts:
        return ""
    return " " + "[dim]\u00b7[/] ".join(str(p) for p in parts)


# ---- pixel whale ----
def render_whale(frame_name: str = "standard") -> list[str]:
    """Render one whale frame to Textual markup rows (25 sprite rows -> 13).

    Two sprite rows combine into one terminal row: upper cell paints the
    foreground of U+2580, lower cell the background. Consecutive cells
    sharing a style are run-length merged, trailing transparent cells drop.
    """
    frame = next(f for f in FRAMES if f["name"] == frame_name)
    rows = frame["rows"]
    out = []
    for r in range(0, len(rows), 2):
        upper = rows[r]
        lower = rows[r + 1] if r + 1 < len(rows) else ""
        line = ""
        current = None
        for x in range(len(upper)):
            up = _PALETTE.get(upper[x])
            lo = _PALETTE.get(lower[x]) if x < len(lower) else None
            if up is None and lo is None:
                continue  # transparent
            if up is not None and lo is not None:
                ch = "\u2580"  # upper half block: fg=upper, bg=lower
                style = f"[{_hex(up)} on {_hex(lo)}]"
            elif up is not None:
                ch = "\u2580"
                style = f"[{_hex(up)}]"
            else:
                ch = "\u2584"  # lower half block
                style = f"[{_hex(lo)}]"
            if style != current:
                if current is not None:
                    line += "[/]"
                line += style + ch
                current = style
            else:
                line += ch
        if current is not None:
            line += "[/]"
        out.append(line)
    return out


def whale_frames_sequence() -> list[str]:
    """dsh-TUI opening sequence: standard, blink, fins, spouts, tail wag."""
    names = ["standard", "blink", "fin1", "fin2", "spout1", "spout2", "spout3",
             "spout4", "spout5", "spout6", "tail1", "tail2", "tail3", "standard"]
    return ["\n".join(render_whale(n)) for n in names]


# ---- big font ----
def render_big(text: str) -> list[str]:
    """Render text in big glyphs (5 columns per letter, 5 rows)."""
    letters = [GLYPHS.get(ch) for ch in text.upper()]
    letters = [g for g in letters if g]
    if not letters:
        return []
    out = []
    for row in range(5):
        line = " ".join(letter[row] for letter in letters)
        out.append(line)
    return out


def shimmer_line(line: str, step: int, window: int = 10) -> str:
    """Paint `line` with a blue-white highlight window sweeping across it.

    The window advances one column per step (dsh-TUI sweep); inside the
    window the color lerps brand -> ice, outside it fades to pale.
    """
    width = len(line)
    if width == 0:
        return ""
    start = step % (width + window) - window
    out = []
    for i, ch in enumerate(line):
        if ch == " ":
            out.append(" "); continue
        if start <= i < start + window:
            t = (i - start) / max(window - 1, 1)
            color = _hex(_lerp(BRAND, ICE, t))
        else:
            color = _hex(PALE)
        out.append(f"[{color}]{ch}[/]")
    return "".join(out)
