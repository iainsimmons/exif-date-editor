#!/usr/bin/env python3
from __future__ import annotations

import os
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from config import Config
from exif_utils import (
    apply_offset,
    read_metadata,
    set_alldates,
    set_date_keep_time,
    set_metadata,
)
from file_model import (
    IMAGE_EXTENSIONS,
    display_date,
    group_date,
    make_groups,
    natural_key,
    normalize_path,
    sort_groups,
)
from image_utils import load_preview_image
from thumbnails import ThumbnailCache

SORT_LABELS = {"File name": "name", "Date": "date"}
SORT_FIELD_LABELS = {value: label for label, value in SORT_LABELS.items()}
META_LABELS = {
    "OwnerName": "Owner",
    "Artist": "Artist",
    "Copyright": "Copyright",
    "ImageDescription": "Description",
}
THUMB_SIZES = (120, 160, 220)
GRID_PADDING = 8
GRID_CAPTION_HEIGHT = 28
GRID_MEMORY_LIMIT = 400


def configure_fonts(root) -> dict:
    families = set(tkfont.families(root))
    default = tkfont.nametofont("TkDefaultFont")
    family = default.actual("family")
    if family.lower() in {"fixed", "monospace"} or family not in families:
        family = ""
        for candidate in ("Inter", "Cantarell", "Noto Sans", "DejaVu Sans", "Liberation Sans", "Ubuntu"):
            if candidate in families:
                family = candidate
                break
        if not family:
            family = default.actual("family")
    font_sizes = {
        "TkDefaultFont": 12,
        "TkTextFont": 12,
        "TkMenuFont": 12,
        "TkHeadingFont": 13,
        "TkTooltipFont": 11,
        "TkCaptionFont": 12,
        "TkSmallCaptionFont": 11,
        "TkIconFont": 12,
    }
    for name, size in font_sizes.items():
        try:
            font = tkfont.nametofont(name)
        except tk.TclError:
            continue
        weight = "bold" if name == "TkHeadingFont" else "normal"
        font.configure(family=family, size=size, weight=weight)
    return {
        "family": family,
        "base": tkfont.nametofont("TkDefaultFont"),
        "list": tkfont.Font(root=root, family=family, size=11),
        "heading": tkfont.Font(root=root, family=family, size=13, weight="bold"),
        "caption": tkfont.Font(root=root, family=family, size=10),
    }


class ExifDateGUI:
    def __init__(self, root):
        self.root = root
        self.config = Config()
        self.fonts = configure_fonts(root)

        self.root.title("EXIF Date Editor")
        self.root.minsize(860, 640)
        geometry = str(self.config.get("window_geometry", "") or "")
        if geometry:
            try:
                self.root.geometry(geometry)
            except tk.TclError:
                pass

        self.paths: list[str] = []
        self.groups = []
        self.metadata: dict[str, dict[str, str]] = {}
        self.selected_keys: set[str] = set()
        self._syncing = False
        self._grid_anchor: int | None = None
        self._grid_generation = 0
        self._grid_cols = 1
        self._grid_cell_w = 1
        self._grid_cell_h = 1
        self._grid_rects: dict[str, int] = {}
        self._grid_placeholders: dict[str, int] = {}
        self._grid_positions: dict[str, tuple[int, int]] = {}
        self._grid_thumb_boxes: dict[str, tuple[int, int, int, int]] = {}
        self._grid_photos: OrderedDict[str, ImageTk.PhotoImage] = OrderedDict()
        self._grid_image_items: OrderedDict[str, int] = OrderedDict()
        self._grid_requested: set[str] = set()
        self._layout_job = None
        self._thumb_job = None
        self.preview_photo = None

        self.sort_field = str(self.config.get("sort_field", "name"))
        if self.sort_field not in {"name", "date"}:
            self.sort_field = "name"
        self.sort_reverse = bool(self.config.get("sort_reverse", False))
        self.group_var = tk.BooleanVar(value=bool(self.config.get("group_raw_jpg", True)))
        self.view_var = tk.StringVar(value=str(self.config.get("view_mode", "grid")))
        if self.view_var.get() not in {"list", "grid"}:
            self.view_var.set("grid")
        try:
            thumb_size = int(self.config.get("thumbnail_size", 160))
        except (TypeError, ValueError):
            thumb_size = 160
        if thumb_size not in THUMB_SIZES:
            thumb_size = 160
        self.thumb_var = tk.StringVar(value=str(thumb_size))

        style = ttk.Style(root)
        self.canvas_bg = style.lookup("TFrame", "background") or "#f0f0f0"
        self.text_fg = style.lookup("TLabel", "foreground") or "#000000"
        self.select_bg = style.lookup("Treeview", "selectbackground") or "#4a90d9"
        self.placeholder_bg = "#d9d9d9"
        self.placeholder_border = "#bdbdbd"

        self.thumbnail_cache = ThumbnailCache(root, size=thumb_size)

        self._build_menu()
        self._build_toolbar()
        self._build_main_area()
        self._build_edit_panel()
        self._build_status_bar()

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._show_active_view()
        self._refresh_views()
        self._update_selection_display()

    def _build_menu(self) -> None:
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Open Directory...", command=self.choose_open_directory)
        file_menu.add_command(label="Add Directory...", command=self.choose_add_directory)
        file_menu.add_command(label="Add Files...", command=self.choose_add_files)
        file_menu.add_separator()
        self.recent_menu = tk.Menu(file_menu, tearoff=0)
        file_menu.add_cascade(label="Open Recent", menu=self.recent_menu)
        file_menu.add_command(label="Clear Recent", command=self.clear_recent)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.on_close)
        self._rebuild_recent_menu()

    def _build_toolbar(self) -> None:
        toolbar = ttk.Frame(self.root, padding=(6, 4))
        toolbar.pack(fill=tk.X)
        ttk.Label(toolbar, text="View:").pack(side=tk.LEFT)
        ttk.Radiobutton(
            toolbar, text="List", value="list", variable=self.view_var, command=self.on_view_change
        ).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Radiobutton(
            toolbar, text="Grid", value="grid", variable=self.view_var, command=self.on_view_change
        ).pack(side=tk.LEFT)
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)
        ttk.Label(toolbar, text="Sort:").pack(side=tk.LEFT)
        self.sort_combo = ttk.Combobox(
            toolbar, width=10, state="readonly", values=list(SORT_LABELS)
        )
        self.sort_combo.set(SORT_FIELD_LABELS.get(self.sort_field, "File name"))
        self.sort_combo.pack(side=tk.LEFT, padx=4)
        self.sort_combo.bind("<<ComboboxSelected>>", self.on_sort_field_change)
        self.sort_order_button = ttk.Button(
            toolbar, width=5, text=self._order_label(), command=self.toggle_sort_order
        )
        self.sort_order_button.pack(side=tk.LEFT)
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)
        ttk.Checkbutton(
            toolbar,
            text="Pair JPG+ORF",
            variable=self.group_var,
            command=self.on_group_toggle,
        ).pack(side=tk.LEFT)
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)
        ttk.Label(toolbar, text="Thumbnails:").pack(side=tk.LEFT)
        self.thumb_combo = ttk.Combobox(
            toolbar,
            width=5,
            state="readonly",
            values=[str(size) for size in THUMB_SIZES],
            textvariable=self.thumb_var,
        )
        self.thumb_combo.pack(side=tk.LEFT, padx=4)
        self.thumb_combo.bind("<<ComboboxSelected>>", self.on_thumb_size_change)

    def _build_main_area(self) -> None:
        main_paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_paned.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 4))

        left_frame = ttk.Frame(main_paned)
        main_paned.add(left_frame, weight=1)

        button_frame = ttk.Frame(left_frame)
        button_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(4, 0))
        ttk.Button(button_frame, text="Select All", command=self.select_all).pack(side=tk.LEFT)
        ttk.Button(button_frame, text="Clear", command=self.clear_selection).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(button_frame, text="Remove", command=self.remove_selected).pack(side=tk.LEFT)

        self.list_frame = ttk.Frame(left_frame)
        list_scrollbar = ttk.Scrollbar(self.list_frame)
        list_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.file_listbox = tk.Listbox(
            self.list_frame,
            selectmode=tk.EXTENDED,
            exportselection=False,
            activestyle="none",
            font=self.fonts["list"],
            selectbackground=self.select_bg,
        )
        self.file_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        list_scrollbar.config(command=self.file_listbox.yview)
        self.file_listbox.config(yscrollcommand=list_scrollbar.set)
        self.file_listbox.bind("<<ListboxSelect>>", self.on_listbox_select)

        self.grid_frame = ttk.Frame(left_frame)
        grid_scrollbar = ttk.Scrollbar(self.grid_frame)
        grid_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.grid_canvas = tk.Canvas(
            self.grid_frame,
            background=self.canvas_bg,
            highlightthickness=0,
            takefocus=True,
        )
        self.grid_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        grid_scrollbar.config(command=self.grid_canvas.yview)
        self.grid_canvas.config(yscrollcommand=grid_scrollbar.set)
        self.grid_canvas.bind("<Configure>", self.on_grid_configure)
        self.grid_canvas.bind("<Button-1>", self.on_grid_click)
        self.grid_canvas.bind("<MouseWheel>", self.on_grid_mousewheel)
        self.grid_canvas.bind("<Button-4>", self.on_grid_wheel_up)
        self.grid_canvas.bind("<Button-5>", self.on_grid_wheel_down)

        right_frame = ttk.Frame(main_paned)
        main_paned.add(right_frame, weight=2)
        ttk.Label(right_frame, text="Preview", font=self.fonts["heading"]).pack(anchor=tk.W)
        self.preview_label = ttk.Label(right_frame, text="No image selected", anchor=tk.CENTER)
        self.preview_label.pack(fill=tk.BOTH, expand=True, pady=4)
        self.info_label = ttk.Label(
            right_frame,
            text="",
            anchor=tk.W,
            justify=tk.LEFT,
            wraplength=560,
        )
        self.info_label.pack(fill=tk.X, anchor=tk.W)

    def _build_edit_panel(self) -> None:
        edit_frame = ttk.LabelFrame(self.root, text="Edit", padding=(8, 4))
        edit_frame.pack(fill=tk.X, padx=6, pady=(0, 4))
        self.notebook = ttk.Notebook(edit_frame)
        self.notebook.pack(fill=tk.X)

        date_tab = ttk.Frame(self.notebook, padding=6)
        self.notebook.add(date_tab, text="Set Date (Keep Time)")
        ttk.Label(date_tab, text="New date (YYYY-MM-DD):").pack(side=tk.LEFT, padx=(0, 6))
        self.date_keep_entry = ttk.Entry(date_tab, width=16)
        self.date_keep_entry.pack(side=tk.LEFT)
        ttk.Button(date_tab, text="Apply to Selected", command=self.apply_date_keep_time).pack(
            side=tk.LEFT, padx=8
        )

        offset_tab = ttk.Frame(self.notebook, padding=6)
        self.notebook.add(offset_tab, text="Apply Offset")
        ttk.Label(offset_tab, text="Offset (e.g. -1d, +10h, -30m, +2d3h):").pack(
            side=tk.LEFT, padx=(0, 6)
        )
        self.offset_entry = ttk.Entry(offset_tab, width=24)
        self.offset_entry.pack(side=tk.LEFT)
        ttk.Button(offset_tab, text="Apply to Selected", command=self.apply_offset).pack(
            side=tk.LEFT, padx=8
        )

        datetime_tab = ttk.Frame(self.notebook, padding=6)
        self.notebook.add(datetime_tab, text="Set Full DateTime")
        ttk.Label(datetime_tab, text="DateTime (YYYY-MM-DD HH:MM:SS):").pack(
            side=tk.LEFT, padx=(0, 6)
        )
        self.full_dt_entry = ttk.Entry(datetime_tab, width=24)
        self.full_dt_entry.pack(side=tk.LEFT)
        ttk.Button(
            datetime_tab, text="Apply to Selected", command=self.apply_full_datetime
        ).pack(side=tk.LEFT, padx=8)

        metadata_tab = ttk.Frame(self.notebook, padding=6)
        self.notebook.add(metadata_tab, text="Metadata")
        fields_frame = ttk.Frame(metadata_tab)
        fields_frame.pack(side=tk.LEFT, anchor=tk.W)
        self.meta_vars: dict[str, tk.StringVar] = {}
        self.meta_clear: dict[str, tk.BooleanVar] = {}
        for row, tag in enumerate(META_LABELS):
            ttk.Label(fields_frame, text=f"{META_LABELS[tag]}:").grid(
                row=row, column=0, sticky=tk.W, padx=(0, 6), pady=1
            )
            value_var = tk.StringVar()
            clear_var = tk.BooleanVar(value=False)
            self.meta_vars[tag] = value_var
            self.meta_clear[tag] = clear_var
            ttk.Entry(fields_frame, textvariable=value_var, width=34).grid(
                row=row, column=1, sticky=tk.W, pady=1
            )
            ttk.Checkbutton(fields_frame, text="Clear", variable=clear_var).grid(
                row=row, column=2, sticky=tk.W, padx=(6, 0)
            )
        metadata_buttons = ttk.Frame(metadata_tab)
        metadata_buttons.pack(side=tk.LEFT, anchor=tk.N, padx=(16, 0))
        ttk.Button(
            metadata_buttons, text="Apply to Selected", command=self.apply_metadata
        ).pack(anchor=tk.W)
        ttk.Button(
            metadata_buttons, text="Reload", command=self.reload_metadata_fields
        ).pack(anchor=tk.W, pady=(4, 0))
        ttk.Label(
            metadata_buttons,
            text="Blank = unchanged.\nTick Clear to remove a tag.",
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(8, 0))

    def _build_status_bar(self) -> None:
        self.status_var = tk.StringVar(value="Ready")
        status_bar = ttk.Label(
            self.root, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W, padding=(6, 2)
        )
        status_bar.pack(fill=tk.X, side=tk.BOTTOM)

    def _order_label(self) -> str:
        return "Desc" if self.sort_reverse else "Asc"

    def _rebuild_recent_menu(self) -> None:
        self.recent_menu.delete(0, tk.END)
        recents = self.config.recent_dirs()
        if not recents:
            self.recent_menu.add_command(label="(empty)", state=tk.DISABLED)
            return
        for path in recents:
            self.recent_menu.add_command(
                label=self._display_path(path),
                command=lambda selected=path: self.open_directory(selected),
            )
        self.recent_menu.add_separator()
        self.recent_menu.add_command(label="Clear Recent", command=self.clear_recent)

    def _display_path(self, path: str) -> str:
        home = str(Path.home())
        if path == home:
            return "~"
        if path.startswith(home + os.sep):
            return "~" + path[len(home):]
        return path

    def clear_recent(self) -> None:
        self.config.clear_recent_dirs()
        self._rebuild_recent_menu()

    def _scan_directory(self, directory: str) -> list[str]:
        try:
            with os.scandir(directory) as entries:
                files = [
                    entry.path
                    for entry in entries
                    if entry.is_file()
                    and Path(entry.name).suffix.lower() in IMAGE_EXTENSIONS
                ]
        except OSError as error:
            messagebox.showerror("Directory Error", f"Cannot read directory:\n{error}")
            return []
        return sorted(files, key=lambda path: natural_key(os.path.basename(path)))

    def choose_open_directory(self) -> None:
        directory = filedialog.askdirectory(
            title="Open Directory", initialdir=self.config.picker_dir()
        )
        if directory:
            self.open_directory(directory)

    def choose_add_directory(self) -> None:
        directory = filedialog.askdirectory(
            title="Add Directory", initialdir=self.config.picker_dir()
        )
        if directory:
            self.add_directory(directory)

    def choose_add_files(self) -> None:
        filenames = filedialog.askopenfilenames(
            title="Add Images",
            initialdir=self.config.picker_dir(),
            filetypes=[
                ("Images", "*.jpg *.JPG *.jpeg *.JPEG *.orf *.ORF"),
                ("All Files", "*.*"),
            ],
        )
        if not filenames:
            return
        self.config.remember_picker_dir(os.path.dirname(filenames[0]))
        self._add_paths(list(filenames), replace=False)

    def open_directory(self, directory: str) -> None:
        if not os.path.isdir(directory):
            messagebox.showerror("Directory Error", f"Directory not found:\n{directory}")
            return
        paths = self._scan_directory(directory)
        self.config.add_recent_dir(directory)
        self._rebuild_recent_menu()
        if not paths:
            self.status_var.set(f"No JPG/ORF files found in {directory}")
            return
        self._add_paths(paths, replace=True)

    def add_directory(self, directory: str) -> None:
        paths = self._scan_directory(directory)
        self.config.add_recent_dir(directory)
        self._rebuild_recent_menu()
        if not paths:
            self.status_var.set(f"No JPG/ORF files found in {directory}")
            return
        self._add_paths(paths, replace=False)

    def _add_paths(self, paths, replace: bool) -> None:
        if replace:
            self.paths = []
            self.selected_keys.clear()
            self._grid_anchor = None
        existing = set(self.paths)
        for raw_path in paths:
            normalized = normalize_path(raw_path)
            if Path(normalized).suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            if normalized in existing:
                continue
            existing.add(normalized)
            self.paths.append(normalized)
        self._rebuild()

    def _rebuild(self) -> None:
        self.status_var.set("Reading metadata...")
        self.root.update_idletasks()
        self.metadata = read_metadata(self.paths) if self.paths else {}
        self.groups = make_groups(self.paths, self.group_var.get())
        self.groups = sort_groups(
            self.groups, self.sort_field, self.sort_reverse, self.metadata
        )
        valid_keys = {group.key for group in self.groups}
        self.selected_keys &= valid_keys
        if self._grid_anchor is not None and self._grid_anchor >= len(self.groups):
            self._grid_anchor = None
        self._refresh_views()
        self._update_selection_display()
        self.status_var.set(f"{len(self.groups)} groups, {len(self.paths)} files")

    def _refresh_views(self) -> None:
        self._refresh_listbox()
        if self.view_var.get() == "grid":
            self._layout_grid()
        else:
            self._grid_requested.clear()

    def _refresh_listbox(self) -> None:
        self._syncing = True
        self.file_listbox.delete(0, tk.END)
        for group in self.groups:
            date_text = display_date(group_date(group, self.metadata))
            label = group.label if not date_text else f"{group.label}    {date_text}"
            self.file_listbox.insert(tk.END, label)
        for index, group in enumerate(self.groups):
            if group.key in self.selected_keys:
                self.file_listbox.selection_set(index)
        self._syncing = False

    def _show_active_view(self) -> None:
        if self.view_var.get() == "grid":
            self.list_frame.pack_forget()
            self.grid_frame.pack(fill=tk.BOTH, expand=True)
            self.root.after_idle(self._layout_grid)
        else:
            self.grid_frame.pack_forget()
            self.list_frame.pack(fill=tk.BOTH, expand=True)

    def on_view_change(self) -> None:
        self.config.set("view_mode", self.view_var.get())
        self._show_active_view()
        self._sync_listbox_selection()
        self._update_grid_selection()

    def _layout_grid(self) -> None:
        canvas = self.grid_canvas
        self._grid_generation += 1
        self._grid_requested.clear()
        self._grid_photos.clear()
        self._grid_image_items.clear()
        self._grid_rects.clear()
        self._grid_placeholders.clear()
        self._grid_positions.clear()
        self._grid_thumb_boxes.clear()
        canvas.delete("all")

        if not self.groups:
            width = max(canvas.winfo_width(), 200)
            canvas.create_text(
                width // 2,
                48,
                text="No files. Use File > Open Directory...",
                fill=self.text_fg,
                font=self.fonts["base"],
            )
            canvas.configure(scrollregion=(0, 0, width, 120))
            return

        width = max(canvas.winfo_width(), 1)
        thumb = int(self.thumb_var.get())
        cell_w = thumb + 2 * GRID_PADDING
        cell_h = thumb + GRID_CAPTION_HEIGHT + 2 * GRID_PADDING
        cols = max(1, (width - GRID_PADDING) // cell_w)
        self._grid_cols = cols
        self._grid_cell_w = cell_w
        self._grid_cell_h = cell_h

        for index, group in enumerate(self.groups):
            row, col = divmod(index, cols)
            x = GRID_PADDING + col * cell_w
            y = GRID_PADDING + row * cell_h
            cell_rect = canvas.create_rectangle(
                x,
                y,
                x + cell_w - GRID_PADDING,
                y + cell_h - GRID_PADDING,
                fill=self.canvas_bg,
                outline="",
            )
            thumb_box = (
                x + GRID_PADDING,
                y + GRID_PADDING,
                x + GRID_PADDING + thumb,
                y + GRID_PADDING + thumb,
            )
            placeholder = canvas.create_rectangle(
                *thumb_box, fill=self.placeholder_bg, outline=self.placeholder_border
            )
            canvas.create_text(
                x + GRID_PADDING + thumb // 2,
                y + GRID_PADDING + thumb + GRID_CAPTION_HEIGHT // 2,
                text=group.label,
                width=thumb + 2 * GRID_PADDING,
                font=self.fonts["caption"],
                fill=self.text_fg,
                anchor=tk.CENTER,
            )
            self._grid_rects[group.key] = cell_rect
            self._grid_placeholders[group.key] = placeholder
            self._grid_positions[group.key] = (
                x + GRID_PADDING + thumb // 2,
                y + GRID_PADDING + thumb // 2,
            )
            self._grid_thumb_boxes[group.key] = thumb_box

        rows = (len(self.groups) + cols - 1) // cols
        canvas.configure(
            scrollregion=(0, 0, width, GRID_PADDING + rows * cell_h)
        )
        self._update_grid_selection()
        self._schedule_thumb_request(0)

    def _draw_placeholder(self, key: str) -> None:
        box = self._grid_thumb_boxes.get(key)
        if box is None:
            return
        self._grid_placeholders[key] = self.grid_canvas.create_rectangle(
            *box, fill=self.placeholder_bg, outline=self.placeholder_border
        )

    def _set_grid_thumbnail(self, key: str, image, generation: int) -> None:
        if generation != self._grid_generation:
            return
        self._grid_requested.discard(key)
        if image is None or key not in self._grid_positions or key in self._grid_photos:
            return
        photo = ImageTk.PhotoImage(image)
        center = self._grid_positions[key]
        item = self.grid_canvas.create_image(
            center[0], center[1], image=photo, anchor=tk.CENTER
        )
        self._grid_photos[key] = photo
        self._grid_image_items[key] = item
        placeholder = self._grid_placeholders.pop(key, None)
        if placeholder is not None:
            self.grid_canvas.delete(placeholder)
        while len(self._grid_photos) > GRID_MEMORY_LIMIT:
            old_key, _ = self._grid_photos.popitem(last=False)
            old_item = self._grid_image_items.pop(old_key, None)
            if old_item is not None:
                self.grid_canvas.delete(old_item)
            self._grid_requested.discard(old_key)
            self._draw_placeholder(old_key)

    def _schedule_thumb_request(self, delay: int = 50) -> None:
        if self._thumb_job is not None:
            try:
                self.root.after_cancel(self._thumb_job)
            except tk.TclError:
                pass
        self._thumb_job = self.root.after(delay, self._request_visible_thumbnails)

    def _request_visible_thumbnails(self) -> None:
        self._thumb_job = None
        if self.view_var.get() != "grid" or not self.groups:
            return
        canvas = self.grid_canvas
        height = canvas.winfo_height()
        if height <= 1:
            return
        top = canvas.canvasy(0)
        bottom = top + height
        cell_h = max(self._grid_cell_h, 1)
        cols = max(self._grid_cols, 1)
        first_row = max(0, int((top - GRID_PADDING) // cell_h))
        last_row = int((bottom - GRID_PADDING) // cell_h) + 1
        for row in range(first_row, last_row + 1):
            for col in range(cols):
                index = row * cols + col
                if index >= len(self.groups):
                    break
                group = self.groups[index]
                key = group.key
                if key in self._grid_photos or key in self._grid_requested:
                    continue
                self._grid_requested.add(key)
                generation = self._grid_generation
                self.thumbnail_cache.get(
                    group.primary,
                    lambda image, k=key, g=generation: self._set_grid_thumbnail(k, image, g),
                )

    def _update_grid_selection(self) -> None:
        for key, rect in self._grid_rects.items():
            selected = key in self.selected_keys
            self.grid_canvas.itemconfigure(
                rect,
                fill=self.select_bg if selected else self.canvas_bg,
                outline=self.select_bg if selected else "",
                width=2 if selected else 0,
            )

    def _sync_listbox_selection(self) -> None:
        self._syncing = True
        self.file_listbox.selection_clear(0, tk.END)
        for index, group in enumerate(self.groups):
            if group.key in self.selected_keys:
                self.file_listbox.selection_set(index)
        self._syncing = False

    def _grid_index_at(self, x: int, y: int) -> int | None:
        if not self.groups:
            return None
        canvas_y = self.grid_canvas.canvasy(y)
        row = int((canvas_y - GRID_PADDING) // max(self._grid_cell_h, 1))
        col = int((x - GRID_PADDING) // max(self._grid_cell_w, 1))
        if row < 0 or col < 0 or col >= self._grid_cols:
            return None
        index = row * self._grid_cols + col
        if 0 <= index < len(self.groups):
            return index
        return None

    def on_grid_click(self, event) -> None:
        self.grid_canvas.focus_set()
        index = self._grid_index_at(event.x, event.y)
        if index is None:
            return
        key = self.groups[index].key
        control = bool(event.state & 0x0004)
        shift = bool(event.state & 0x0001)
        if control:
            if key in self.selected_keys:
                self.selected_keys.remove(key)
            else:
                self.selected_keys.add(key)
            self._grid_anchor = index
        elif shift and self._grid_anchor is not None:
            start = min(self._grid_anchor, index)
            end = max(self._grid_anchor, index)
            self.selected_keys = {group.key for group in self.groups[start : end + 1]}
        else:
            self.selected_keys = {key}
            self._grid_anchor = index
        self._sync_listbox_selection()
        self._update_grid_selection()
        self._update_selection_display()

    def on_listbox_select(self, event=None) -> None:
        if self._syncing:
            return
        indexes = self.file_listbox.curselection()
        self.selected_keys = {
            self.groups[index].key for index in indexes if 0 <= index < len(self.groups)
        }
        self._grid_anchor = indexes[0] if indexes else None
        self._update_grid_selection()
        self._update_selection_display()

    def on_grid_configure(self, event=None) -> None:
        if self._layout_job is not None:
            try:
                self.root.after_cancel(self._layout_job)
            except tk.TclError:
                pass
        self._layout_job = self.root.after(150, self._on_grid_resize)

    def _on_grid_resize(self) -> None:
        self._layout_job = None
        if self.view_var.get() == "grid":
            self._layout_grid()

    def _scroll_grid(self, units: int) -> None:
        self.grid_canvas.yview_scroll(units, "units")
        self._schedule_thumb_request()

    def on_grid_mousewheel(self, event) -> str:
        units = -1 if event.delta > 0 else 1
        self._scroll_grid(units)
        return "break"

    def on_grid_wheel_up(self, event) -> str:
        self._scroll_grid(-1)
        return "break"

    def on_grid_wheel_down(self, event) -> str:
        self._scroll_grid(1)
        return "break"

    def _selected_groups(self):
        return [group for group in self.groups if group.key in self.selected_keys]

    def _selected_paths(self) -> tuple[list, list[str]]:
        groups = self._selected_groups()
        paths = [member for group in groups for member in group.members]
        return groups, paths

    def select_all(self) -> None:
        self.selected_keys = {group.key for group in self.groups}
        self._grid_anchor = 0 if self.groups else None
        self._sync_listbox_selection()
        self._update_grid_selection()
        self._update_selection_display()

    def clear_selection(self) -> None:
        self.selected_keys.clear()
        self._grid_anchor = None
        self._sync_listbox_selection()
        self._update_grid_selection()
        self._update_selection_display()

    def remove_selected(self) -> None:
        if not self.selected_keys:
            messagebox.showwarning("No Selection", "Please select files to remove")
            return
        removed = {
            member
            for group in self.groups
            if group.key in self.selected_keys
            for member in group.members
        }
        self.paths = [path for path in self.paths if path not in removed]
        self.selected_keys.clear()
        self._grid_anchor = None
        self._rebuild()

    def _update_selection_display(self) -> None:
        groups = self._selected_groups()
        if not groups:
            self._clear_selection_display()
            return
        group = groups[0]
        self._show_group_preview(group)
        self.info_label.config(text=self._info_text(group))
        self._prefill_metadata(group)

    def _clear_selection_display(self) -> None:
        self.preview_label.config(image="", text="No image selected")
        self.preview_photo = None
        self.info_label.config(text="")
        for tag, value_var in self.meta_vars.items():
            value_var.set("")
            self.meta_clear[tag].set(False)

    def _show_group_preview(self, group) -> None:
        try:
            image = load_preview_image(group.primary)
            if image is None:
                raise ValueError("no preview")
            max_width = max(320, self.root.winfo_width() - 480)
            max_height = max(240, self.root.winfo_height() - 470)
            image.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
            self.preview_photo = ImageTk.PhotoImage(image)
            self.preview_label.config(image=self.preview_photo, text="")
        except Exception:
            self.preview_label.config(image="", text="Cannot preview")
            self.preview_photo = None

    def _info_text(self, group) -> str:
        meta = self.metadata.get(group.primary, {})
        lines = [group.label, f"Folder: {group.directory}"]
        date_value = group_date(group, self.metadata)
        lines.append(f"Date: {display_date(date_value) or 'unknown'}")
        for tag in META_LABELS:
            value = meta.get(tag)
            if value:
                lines.append(f"{META_LABELS[tag]}: {value}")
        if group.is_pair:
            lines.append("Files: " + ", ".join(Path(member).name for member in group.members))
            member_dates = {
                self.metadata.get(member, {}).get(tag)
                for member in group.members
                for tag in ("DateTimeOriginal", "CreateDate")
                if self.metadata.get(member, {}).get(tag)
            }
            if len(member_dates) > 1:
                lines.append("Warning: member dates differ")
        return "\n".join(lines)

    def _prefill_metadata(self, group) -> None:
        meta = self.metadata.get(group.primary, {})
        for tag, value_var in self.meta_vars.items():
            value_var.set(meta.get(tag, ""))
            self.meta_clear[tag].set(False)

    def on_sort_field_change(self, event=None) -> None:
        field = SORT_LABELS.get(self.sort_combo.get(), "name")
        if field == self.sort_field:
            return
        self.sort_field = field
        self.config.set("sort_field", field)
        self._resort()

    def toggle_sort_order(self) -> None:
        self.sort_reverse = not self.sort_reverse
        self.config.set("sort_reverse", self.sort_reverse)
        self.sort_order_button.config(text=self._order_label())
        self._resort()

    def _resort(self) -> None:
        self.groups = sort_groups(
            self.groups, self.sort_field, self.sort_reverse, self.metadata
        )
        self._refresh_views()
        self._update_selection_display()

    def on_group_toggle(self) -> None:
        self.config.set("group_raw_jpg", bool(self.group_var.get()))
        self.selected_keys.clear()
        self._grid_anchor = None
        self._rebuild()

    def on_thumb_size_change(self, event=None) -> None:
        try:
            size = int(self.thumb_var.get())
        except ValueError:
            return
        self.config.set("thumbnail_size", size)
        self.thumbnail_cache.set_size(size)
        if self.view_var.get() == "grid":
            self._layout_grid()

    def _set_busy(self) -> None:
        self.status_var.set("Updating...")
        self.root.update_idletasks()

    def _finish_write(self, paths: list[str], ok: bool, message: str) -> None:
        self.status_var.set(message)
        if not ok:
            messagebox.showerror("Error", message)
            return
        if paths:
            updated = read_metadata(paths)
            for path in paths:
                key = normalize_path(path)
                self.metadata[key] = updated.get(key, {})
        self.groups = sort_groups(
            self.groups, self.sort_field, self.sort_reverse, self.metadata
        )
        self._refresh_views()
        self._update_selection_display()
        messagebox.showinfo("Success", message)

    def apply_date_keep_time(self) -> None:
        groups, paths = self._selected_paths()
        if not groups:
            messagebox.showwarning("No Selection", "Please select files")
            return
        value = self.date_keep_entry.get().strip()
        if not value:
            messagebox.showwarning("No Date", "Please enter a date")
            return
        self._set_busy()
        ok, message = set_date_keep_time(paths, value, metadata=self.metadata)
        self._finish_write(paths, ok, message)

    def apply_offset(self) -> None:
        groups, paths = self._selected_paths()
        if not groups:
            messagebox.showwarning("No Selection", "Please select files")
            return
        value = self.offset_entry.get().strip()
        if not value:
            messagebox.showwarning("No Offset", "Please enter an offset")
            return
        self._set_busy()
        ok, message = apply_offset(paths, value, metadata=self.metadata)
        self._finish_write(paths, ok, message)

    def apply_full_datetime(self) -> None:
        groups, paths = self._selected_paths()
        if not groups:
            messagebox.showwarning("No Selection", "Please select files")
            return
        text = self.full_dt_entry.get().strip()
        if not text:
            messagebox.showwarning("No DateTime", "Please enter a datetime")
            return
        parsed = None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        if parsed is None:
            messagebox.showwarning("Invalid DateTime", "Use YYYY-MM-DD HH:MM:SS")
            return
        value = parsed.strftime("%Y:%m:%d %H:%M:%S")
        self._set_busy()
        ok, message = set_alldates(paths, value)
        self._finish_write(paths, ok, message)

    def apply_metadata(self) -> None:
        groups, paths = self._selected_paths()
        if not groups:
            messagebox.showwarning("No Selection", "Please select files")
            return
        fields: dict[str, str | None] = {}
        for tag, value_var in self.meta_vars.items():
            if self.meta_clear[tag].get():
                fields[tag] = None
            else:
                value = value_var.get().strip()
                if value:
                    fields[tag] = value
        if not fields:
            messagebox.showwarning(
                "No Metadata", "Enter a value or tick Clear for at least one field"
            )
            return
        self._set_busy()
        ok, message = set_metadata(paths, fields)
        self._finish_write(paths, ok, message)

    def reload_metadata_fields(self) -> None:
        groups = self._selected_groups()
        if groups:
            self._prefill_metadata(groups[0])

    def on_close(self) -> None:
        self.config.data["window_geometry"] = self.root.geometry()
        self.config.save()
        self.thumbnail_cache.shutdown()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    ExifDateGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
