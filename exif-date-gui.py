#!/usr/bin/env python3
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk
import os
from pathlib import Path
from datetime import datetime
import tempfile

from exif_utils import read_alldates, set_alldates, apply_offset, set_date_keep_time
from image_utils import get_preview_image

class ExifDateGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("EXIF Date Editor")
        self.root.geometry("1000x700")
        
        self.files = []
        self.current_image = None
        self.photo = None
        
        # Menu
        menubar = tk.Menu(root)
        root.config(menu=menubar)
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Add Files...", command=self.add_files)
        file_menu.add_command(label="Add Directory...", command=self.add_directory)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=root.quit)
        
        # Main layout
        main_paned = ttk.PanedWindow(root, orient=tk.HORIZONTAL)
        main_paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Left panel - file list
        left_frame = ttk.Frame(main_paned)
        main_paned.add(left_frame, weight=1)
        
        ttk.Label(left_frame, text="Files (JPG/ORF)").pack(anchor=tk.W)
        
        list_frame = ttk.Frame(left_frame)
        list_frame.pack(fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.file_listbox = tk.Listbox(list_frame, selectmode=tk.EXTENDED, yscrollcommand=scrollbar.set)
        self.file_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.file_listbox.yview)
        self.file_listbox.bind('<<ListboxSelect>>', self.on_file_select)
        
        btn_frame = ttk.Frame(left_frame)
        btn_frame.pack(fill=tk.X)
        ttk.Button(btn_frame, text="Select All", command=self.select_all).pack(side=tk.LEFT)
        ttk.Button(btn_frame, text="Clear Selection", command=self.clear_selection).pack(side=tk.LEFT)
        ttk.Button(btn_frame, text="Remove", command=self.remove_selected).pack(side=tk.LEFT)
        
        # Right panel
        right_frame = ttk.Frame(main_paned)
        main_paned.add(right_frame, weight=2)
        
        ttk.Label(right_frame, text="Preview").pack(anchor=tk.W)
        
        self.preview_label = ttk.Label(right_frame, text="No image selected")
        self.preview_label.pack(fill=tk.BOTH, expand=True)
        
        self.date_label = ttk.Label(right_frame, text="Current Date: -")
        self.date_label.pack(anchor=tk.W)
        
        # Edit panel
        edit_frame = ttk.LabelFrame(root, text="Edit Dates", padding=10)
        edit_frame.pack(fill=tk.X, padx=5, pady=5)
        
        # Notebook for different edit modes
        self.notebook = ttk.Notebook(edit_frame)
        self.notebook.pack(fill=tk.X)
        
        # Tab 1: Set date keep time
        tab1 = ttk.Frame(self.notebook)
        self.notebook.add(tab1, text="Set Date (Keep Time)")
        ttk.Label(tab1, text="New Date (YYYY-MM-DD):").pack(side=tk.LEFT, padx=5)
        self.date_keep_entry = ttk.Entry(tab1)
        self.date_keep_entry.pack(side=tk.LEFT, padx=5)
        ttk.Button(tab1, text="Apply to Selected", command=self.apply_date_keep_time).pack(side=tk.LEFT, padx=5)
        
        # Tab 2: Apply offset
        tab2 = ttk.Frame(self.notebook)
        self.notebook.add(tab2, text="Apply Offset")
        ttk.Label(tab2, text="Offset (e.g., -1d, +10h, -30m, +2d3h):").pack(side=tk.LEFT, padx=5)
        self.offset_entry = ttk.Entry(tab2)
        self.offset_entry.pack(side=tk.LEFT, padx=5)
        ttk.Button(tab2, text="Apply to Selected", command=self.apply_offset).pack(side=tk.LEFT, padx=5)
        
        # Tab 3: Set full datetime
        tab3 = ttk.Frame(self.notebook)
        self.notebook.add(tab3, text="Set Full DateTime")
        ttk.Label(tab3, text="DateTime (YYYY-MM-DD HH:MM:SS):").pack(side=tk.LEFT, padx=5)
        self.full_dt_entry = ttk.Entry(tab3)
        self.full_dt_entry.pack(side=tk.LEFT, padx=5)
        ttk.Button(tab3, text="Apply to Selected", command=self.apply_full_datetime).pack(side=tk.LEFT, padx=5)
        
        # Status bar
        self.status_var = tk.StringVar(value="Ready")
        status_bar = ttk.Label(root, textvariable=self.status_var, relief=tk.SUNKEN)
        status_bar.pack(fill=tk.X, side=tk.BOTTOM)
        
        self.refresh_file_list()
    
    def add_files(self):
        filenames = filedialog.askopenfilenames(
            title="Select Images",
            filetypes=[("Images", "*.jpg *.JPG *.jpeg *.JPEG *.orf *.ORF"), ("All Files", "*.*")]
        )
        for f in filenames:
            if f not in self.files:
                self.files.append(f)
        self.refresh_file_list()
    
    def add_directory(self):
        dirname = filedialog.askdirectory(title="Select Directory")
        if dirname:
            for ext in ['*.jpg', '*.JPG', '*.jpeg', '*.JPEG', '*.orf', '*.ORF']:
                import glob
                for f in glob.glob(os.path.join(dirname, ext)):
                    if f not in self.files:
                        self.files.append(f)
            self.refresh_file_list()
    
    def refresh_file_list(self):
        self.file_listbox.delete(0, tk.END)
        for f in self.files:
            self.file_listbox.insert(tk.END, os.path.basename(f))
    
    def get_selected_files(self):
        selected = self.file_listbox.curselection()
        return [self.files[i] for i in selected]
    
    def select_all(self):
        self.file_listbox.select_set(0, tk.END)
        if self.files:
            self.on_file_select(None)
    
    def clear_selection(self):
        self.file_listbox.select_clear(0, tk.END)
        self.date_label.config(text="Current Date: -")
        self.preview_label.config(image='', text="No image selected")
        self.photo = None
    
    def remove_selected(self):
        selected = sorted(self.file_listbox.curselection(), reverse=True)
        for i in selected:
            del self.files[i]
        self.refresh_file_list()
        self.clear_selection()
    
    def on_file_select(self, event):
        selected = self.get_selected_files()
        if not selected:
            return
        # Show preview for first selected
        f = selected[0]
        self.show_preview(f)
        # Show date
        dates = read_alldates(selected)
        if f in dates:
            self.date_label.config(text=f"Current Date: {dates[f]}")
        elif os.path.basename(f) in dates:
            self.date_label.config(text=f"Current Date: {dates[os.path.basename(f)]}")
        else:
            self.date_label.config(text="Current Date: Not found")
    
    def show_preview(self, file_path):
        try:
            preview_path = get_preview_image(file_path)
            if not preview_path:
                self.preview_label.config(image='', text="Cannot preview")
                self.photo = None
                return
            img = Image.open(preview_path)
            # Resize to fit
            img.thumbnail((600, 400), Image.Resampling.LANCZOS)
            self.photo = ImageTk.PhotoImage(img)
            self.preview_label.config(image=self.photo, text='')
        except Exception as e:
            self.preview_label.config(image='', text=f"Error: {e}")
            self.photo = None
    
    def apply_date_keep_time(self):
        selected = self.get_selected_files()
        if not selected:
            messagebox.showwarning("No Selection", "Please select files")
            return
        new_date = self.date_keep_entry.get().strip()
        if not new_date:
            messagebox.showwarning("No Date", "Please enter a date")
            return
        self.status_var.set("Updating...")
        self.root.update()
        ok, msg = set_date_keep_time(selected, new_date)
        self.status_var.set(msg)
        if ok:
            messagebox.showinfo("Success", msg)
            self.on_file_select(None)
        else:
            messagebox.showerror("Error", msg)
    
    def apply_offset(self):
        selected = self.get_selected_files()
        if not selected:
            messagebox.showwarning("No Selection", "Please select files")
            return
        offset = self.offset_entry.get().strip()
        if not offset:
            messagebox.showwarning("No Offset", "Please enter an offset")
            return
        self.status_var.set("Updating...")
        self.root.update()
        ok, msg = apply_offset(selected, offset)
        self.status_var.set(msg)
        if ok:
            messagebox.showinfo("Success", msg)
            self.on_file_select(None)
        else:
            messagebox.showerror("Error", msg)
    
    def apply_full_datetime(self):
        selected = self.get_selected_files()
        if not selected:
            messagebox.showwarning("No Selection", "Please select files")
            return
        dt = self.full_dt_entry.get().strip()
        if not dt:
            messagebox.showwarning("No DateTime", "Please enter a datetime")
            return
        # Convert from YYYY-MM-DD HH:MM:SS to YYYY:MM:DD HH:MM:SS
        dt = dt.replace('-', ':')
        self.status_var.set("Updating...")
        self.root.update()
        ok, msg = set_alldates(selected, dt)
        self.status_var.set(msg)
        if ok:
            messagebox.showinfo("Success", msg)
            self.on_file_select(None)
        else:
            messagebox.showerror("Error", msg)

def main():
    root = tk.Tk()
    app = ExifDateGUI(root)
    root.mainloop()

if __name__ == '__main__':
    main()
