"""Small, native-dependency-free desktop theme and clock artwork."""

import subprocess
import sys
import tkinter as tk
from tkinter import font, ttk


LIGHT = dict(page="#f3f5f9", card="#ffffff", border="#c5cdd9", secondary_border="#78869a", text="#172438",
             muted="#526176", accent="#245bb5", accent_hover="#194a9a",
             accent_pressed="#133c80", on_accent="#ffffff", accent_text="#245bb5",
             focus="#245bb5", success="#176331", warning="#805000", danger="#b42332",
             stripe="#edf1f7", selected="#e2ecff", indicator_mark="#ffffff")
DARK = dict(page="#111827", card="#1b2535", border="#65748b", secondary_border="#78869a", text="#f3f6fc",
            muted="#b4c1d5", accent="#245bb5", accent_hover="#194a9a",
            accent_pressed="#133c80", on_accent="#ffffff", accent_text="#9ec5ff",
            focus="#9ec5ff", success="#81d9a0", warning="#f7cc77", danger="#ff9da6",
            stripe="#243248", selected="#2b4261", indicator_mark="#1b2535")

# Explicit maps override clam's per-widget disabled defaults, including labels.
DISABLED_SURFACES = dict.fromkeys((
    ".", "TFrame", "Card.TFrame", "Accent.TFrame", "TLabel", "Heading.TLabel",
    "Number.TLabel", "Helper.TLabel", "Footer.TLabel", "Tag.TLabel", "Success.TLabel",
    "Warning.TLabel", "Danger.TLabel", "Pending.Nav.TLabel", "TButton",
    "Secondary.TButton", "Nav.TButton", "Current.Nav.TButton", "Tile.TButton",
    "Primary.TButton", "TEntry", "TCombobox", "TCheckbutton", "TRadiobutton",
    "Treeview", "Treeview.Heading", "Horizontal.TScale", "Vertical.TScale",
    "TProgressbar", "Horizontal.TProgressbar", "Vertical.TProgressbar"), "card")
DISABLED_SURFACES.update(dict.fromkeys(("Page.TFrame", "Title.TLabel", "Subtitle.TLabel",
                                      "Horizontal.TScrollbar", "Vertical.TScrollbar"), "page"))


def system_dark():
    """Use the app appearance preference; unavailable preferences mean light."""
    try:
        if sys.platform == "win32":
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
                return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0
        if sys.platform == "darwin":
            result = subprocess.run(["defaults", "read", "-g", "AppleInterfaceStyle"],
                                    capture_output=True, text=True, timeout=2)
            return result.returncode == 0 and result.stdout.strip().lower() == "dark"
    except (OSError, subprocess.SubprocessError):
        pass
    return False


def font_family(root):
    available = set(font.families(root))
    preferred = {"win32": ("Segoe UI Variable Text", "Segoe UI"),
                 "darwin": ("SF Pro Text", ".AppleSystemUIFont", "Helvetica Neue")}
    return next((name for name in preferred.get(sys.platform, ("Noto Sans", "DejaVu Sans"))
                 if name in available), font.nametofont("TkDefaultFont", root).actual("family"))


def clock_pixels(size, accent=LIGHT["accent"]):
    """RGBA rounded square with a clock face, shared by Tk and packaging."""
    blue = tuple(bytes.fromhex(accent[1:]))
    pixels = bytearray()
    for y in range(size):
        for x in range(size):
            u, v = (x + .5) / size, (y + .5) / size
            dx, dy = max(.20 - u, 0, u - .80), max(.20 - v, 0, v - .80)
            inside = dx * dx + dy * dy <= .16 ** 2
            radius = ((u - .5) ** 2 + (v - .5) ** 2) ** .5
            face = .29 <= radius <= .335
            hands = (.475 <= u <= .525 and .29 <= v <= .525) or (
                .49 <= u <= .69 and .475 <= v <= .525)
            pixels.extend((*((255, 255, 255) if face or hands else blue), 255 if inside else 0))
    return bytes(pixels)


def icon(root, accent):
    size = 64
    pixels = clock_pixels(size, accent)
    result = tk.PhotoImage(master=root, width=size, height=size)
    for y in range(size):
        for x in range(size):
            offset = (y * size + x) * 4
            if pixels[offset + 3]:
                result.put("#" + pixels[offset:offset + 3].hex(), (x, y))
    root.iconphoto(True, result)
    return result


def indicator_image(root, colors, size, radio, selected):
    """Explicit filled indicators, independent of platform theme drawing."""
    image = tk.PhotoImage(master=root, width=size, height=size)
    for y in range(size):
        for x in range(size):
            distance = (((x + .5 - size / 2) ** 2 + (y + .5 - size / 2) ** 2) ** .5
                        if radio else max(abs(x + .5 - size / 2), abs(y + .5 - size / 2)))
            if distance > size / 2 - 1:
                continue
            ring = distance >= size / 2 - 3
            color = colors["accent_text"] if ring or selected else colors["card"]
            if selected and not radio:
                u, v = x / size, y / size
                if (.23 <= u <= .47 and abs(v - (u + .18)) < .07 or
                        .43 <= u <= .79 and abs(v - (1.1 - u)) < .07):
                    color = colors["indicator_mark"]
            image.put(color, (x, y))
    return image


def apply(root, dark=None):
    colors = dict(DARK if (system_dark() if dark is None else dark) else LIGHT)
    family = font_family(root)
    heading = next((name for name in ("Segoe UI Semibold", "SF Pro Text Semibold")
                    if name in font.families(root)), family)
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
        font.nametofont(name, root).configure(family=family, size=11)
    style = ttk.Style(root)
    style.theme_use("clam")
    root.configure(background=colors["page"])
    root.option_add("*TCombobox*Listbox.background", colors["card"])
    root.option_add("*TCombobox*Listbox.foreground", colors["text"])
    root.option_add("*TCombobox*Listbox.selectBackground", colors["accent"])
    root.option_add("*TCombobox*Listbox.selectForeground", colors["on_accent"])
    root.option_add("*TCombobox*Listbox.font", (family, 11))
    style.configure(".", background=colors["card"], foreground=colors["text"],
                    font=(family, 11), bordercolor=colors["border"],
                    lightcolor=colors["border"], darkcolor=colors["border"],
                    focuscolor=colors["focus"], troughcolor=colors["stripe"])
    style.configure("Page.TFrame", background=colors["page"])
    style.configure("Card.TFrame", relief="solid", borderwidth=1)
    style.configure("Accent.TFrame", background=colors["accent_text"])
    style.configure("TLabel", padding=(0, 2))
    style.configure("Title.TLabel", font=(heading, 20, "bold"), background=colors["page"])
    style.configure("Subtitle.TLabel", font=(family, 10), foreground=colors["muted"], background=colors["page"])
    style.configure("Heading.TLabel", font=(heading, 13, "bold"))
    style.configure("Number.TLabel", font=(family, 20, "bold"))
    style.configure("Helper.TLabel", font=(family, 10), foreground=colors["muted"])
    style.configure("Footer.TLabel", font=(family, 10), foreground=colors["muted"], background=colors["card"])
    style.configure("Tag.TLabel", font=(family, 10), background=colors["selected"], padding=(6, 3))
    for state in ("success", "warning", "danger"):
        style.configure(f"{state.title()}.TLabel", foreground=colors[state], padding=(8, 8))
    for name in ("TButton", "Secondary.TButton", "Nav.TButton", "Current.Nav.TButton", "Tile.TButton", "Primary.TButton"):
        primary = name == "Primary.TButton"
        style.configure(name, padding=(14, 9), borderwidth=1, relief="flat" if primary else "solid", focusthickness=2,
                        focuscolor=colors["on_accent" if primary else "focus"],
                        background=colors["accent" if primary else "stripe"],
                        foreground=colors["on_accent" if primary else "text"])
        style.map(name, background=[("disabled", colors["stripe"]),
                                   ("pressed", colors["accent_pressed" if primary else "selected"]),
                                   ("active", colors["accent_hover" if primary else "card"])],
                  foreground=[("disabled", colors["muted"])],
                  bordercolor=[("focus", colors["focus"])])
        if not primary:
            for option in ("bordercolor", "lightcolor", "darkcolor"):
                style.configure(name, **{option: colors["secondary_border"]})
                style.map(name, **{option: [("focus", colors["focus"]), ("!focus", colors["secondary_border"])]})
        else:
            # Do not inherit the secondary edges from the base TButton style.
            style.configure(name, bordercolor=colors["border"])
            for option in ("lightcolor", "darkcolor"):
                style.map(name, **{option: [("focus", colors["border"]), ("!focus", colors["border"])]})
    style.configure("Nav.TButton", anchor="w", padding=(10, 10))
    style.configure("Pending.Nav.TLabel", padding=(10, 10), foreground=colors["muted"],
                    borderwidth=0, relief="flat")
    style.configure("Current.Nav.TButton", font=(family, 11, "bold"), background=colors["selected"])
    style.configure("Tile.TButton", anchor="w", padding=(18, 22), font=(family, 13, "bold"))
    for name in ("TEntry", "TCombobox"):
        style.configure(name, padding=8, fieldbackground=colors["card"], insertcolor=colors["text"],
                        selectbackground=colors["accent"], selectforeground=colors["on_accent"])
        style.map(name, fieldbackground=[("disabled", colors["stripe"]), ("readonly", colors["card"])],
                  foreground=[("disabled", colors["muted"]), ("readonly", colors["text"])],
                  bordercolor=[("focus", colors["focus"])],
                  lightcolor=[("focus", colors["focus"])], darkcolor=[("focus", colors["focus"])],
                  arrowcolor=[("disabled", colors["muted"]), ("!disabled", colors["text"])])
    root._indicator_images = []
    for name in ("TCheckbutton", "TRadiobutton"):
        size = max(18, font.nametofont("TkDefaultFont", root).metrics("linespace"))
        images = [indicator_image(root, colors, size, name == "TRadiobutton", selected)
                  for selected in (False, True)]
        root._indicator_images.extend(images)
        element = f"Autohours{images[0]}.{name}.indicator"
        style.element_create(element, "image", images[0], ("selected", images[1]),
                             sticky="w", padding=(0, 0, 8, 0))
        # Preserve native focus and label elements and replace only the indicator.
        def replace_indicator(layout):
            return [(element if part.endswith(".indicator") else part,
                     {key: replace_indicator(value) if key == "children" else value
                      for key, value in options.items()}) for part, options in layout]
        style.layout(name, replace_indicator(style.layout(name)))
        style.configure(name, padding=(6, 8), focusthickness=2, indicatorbackground=colors["card"],
                        indicatorforeground=colors["indicator_mark"],
                        indicatorsize=max(16, font.nametofont("TkDefaultFont", root).metrics("linespace") - 4),
                        indicatormargin=(0, 0, 8, 0))
        style.map(name, background=[("active", colors["stripe"])],
                  foreground=[("disabled", colors["muted"])],
                  indicatorbackground=[("selected", colors["accent_text"])])
    # A character row grows with the font at high DPI instead of clipping text.
    scale = max(1, float(root.tk.call("tk", "scaling")) / (96 / 72))
    rowheight = max(round(32 * scale), font.nametofont("TkDefaultFont", root).metrics("linespace") + 12)
    style.configure("Treeview", rowheight=rowheight, background=colors["card"],
                    fieldbackground=colors["card"], borderwidth=2)
    style.configure("Treeview.Heading", font=(family, 11, "bold"), padding=(8, 8), relief="flat")
    style.map("Treeview", background=[("selected", colors["selected"])],
              foreground=[("selected", colors["text"])], bordercolor=[("focus", colors["focus"])])
    for direction in ("Vertical", "Horizontal"):
        style.configure(f"{direction}.TScrollbar", arrowsize=12, borderwidth=0,
                        background=colors["border"], troughcolor=colors["page"])
    style.configure("TProgressbar", background=colors["accent_text"], borderwidth=0, thickness=6)
    for name, surface in DISABLED_SURFACES.items():
        for option, token in (("background", surface), ("fieldbackground", surface),
                              ("foreground", "muted"), ("arrowcolor", "muted"),
                              ("lightcolor", surface), ("darkcolor", surface),
                              ("bordercolor", "border"), ("troughcolor", surface)):
            existing = style.map(name, option)
            style.map(name, **{option: [("disabled", colors[token]),
                                       *(row for row in existing if "disabled" not in row[:-1])]})
    return colors


def stripe(table, colors):
    table.tag_configure("even", background=colors["card"])
    table.tag_configure("odd", background=colors["stripe"])


def text_options(colors):
    return dict(background=colors["card"], foreground=colors["text"],
                insertbackground=colors["text"], selectbackground=colors["accent"],
                selectforeground=colors["on_accent"], highlightbackground=colors["border"],
                highlightcolor=colors["focus"], highlightthickness=2, relief="flat")
