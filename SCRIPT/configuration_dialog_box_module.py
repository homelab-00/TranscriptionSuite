"""
Configuration dialog module for speech-to-text application.

Provides a graphical configuration interface with tabbed interface for:
- Long Form tab: Configuration for long-form transcription
- Real-time tab: Configuration for real-time transcription
- Static tab: Configuration for static file transcription
"""

import copy
import json
import os
import tkinter as tk
from tkinter import ttk

# Try to import Rich for pretty printing
try:
    from rich.console import Console

    console = Console()
    HAS_RICH = True
except ImportError:
    HAS_RICH = False


class ThemeConfig:
    """Configuration for UI theme colors."""

    def __init__(self):
        self.bg_color = "#333333"
        self.text_color = "#FFFFFF"
        self.entry_bg = "#555555"
        self.highlight_color = "#007ACC"
        self.button_bg = "#444444"

    def get_colors(self):
        """Get all color values as a dictionary."""
        return {
            "bg_color": self.bg_color,
            "text_color": self.text_color,
            "entry_bg": self.entry_bg,
            "highlight_color": self.highlight_color,
            "button_bg": self.button_bg,
        }

    def set_theme(self, theme_name):
        """Set theme colors based on theme name."""
        if theme_name == "dark":
            self.bg_color = "#333333"
            self.text_color = "#FFFFFF"
            self.entry_bg = "#555555"
            self.highlight_color = "#007ACC"
            self.button_bg = "#444444"
        elif theme_name == "light":
            self.bg_color = "#FFFFFF"
            self.text_color = "#000000"
            self.entry_bg = "#F0F0F0"
            self.highlight_color = "#0078D4"
            self.button_bg = "#E1E1E1"


class ConfigurationDialog:
    """Dialog for configuring speech-to-text application settings."""

    def __init__(self, config_file_path, callback=None):
        self.config_path = config_file_path
        self.callback = callback
        self.apply_clicked = False
        self.theme = ThemeConfig()
        # Combine related data to reduce instance attributes
        self.data = {
            "config": self._load_config(),
            "updated_config": {},
            "variables": {},
            "language_data": self._initialize_language_data(),
        }

    def _initialize_language_data(self):
        """Initialize all language-related data."""
        priority = {
            "en": "🇬🇧 English (en)",
            "el": "🇬🇷 Greek (el)",
            "ru": "🇷🇺 Russian (ru)",
            "zh": "🇨🇳 Chinese (zh)",
            "de": "🇩🇪 German (de)",
            "fr": "🇫🇷 French (fr)",
        }

        all_languages = {
            "en": "english",
            "zh": "chinese",
            "de": "german",
            "es": "spanish",
            "ru": "russian",
            "ko": "korean",
            "fr": "french",
            "ja": "japanese",
            "pt": "portuguese",
            "tr": "turkish",
            "pl": "polish",
            "ca": "catalan",
            "nl": "dutch",
            "ar": "arabic",
            "sv": "swedish",
            "it": "italian",
            "id": "indonesian",
            "hi": "hindi",
            "fi": "finnish",
            "vi": "vietnamese",
            "he": "hebrew",
            "uk": "ukrainian",
            "el": "greek",
            "ms": "malay",
            "cs": "czech",
            "ro": "romanian",
            "da": "danish",
            "hu": "hungarian",
            "ta": "tamil",
            "no": "norwegian",
            "th": "thai",
            "ur": "urdu",
            "hr": "croatian",
            "bg": "bulgarian",
            "lt": "lithuanian",
            "la": "latin",
            "mi": "maori",
            "ml": "malayalam",
            "cy": "welsh",
            "sk": "slovak",
            "te": "telugu",
            "fa": "persian",
            "lv": "latvian",
            "bn": "bengali",
            "sr": "serbian",
            "az": "azerbaijani",
            "sl": "slovenian",
            "kn": "kannada",
            "et": "estonian",
            "mk": "macedonian",
            "br": "breton",
            "eu": "basque",
            "is": "icelandic",
            "hy": "armenian",
            "ne": "nepali",
            "mn": "mongolian",
            "bs": "bosnian",
            "kk": "kazakh",
            "sq": "albanian",
            "sw": "swahili",
            "gl": "galician",
            "mr": "marathi",
            "pa": "punjabi",
            "si": "sinhala",
            "km": "khmer",
            "sn": "shona",
            "yo": "yoruba",
            "so": "somali",
            "af": "afrikaans",
            "oc": "occitan",
            "ka": "georgian",
            "be": "belarusian",
            "tg": "tajik",
            "sd": "sindhi",
            "gu": "gujarati",
            "am": "amharic",
            "yi": "yiddish",
            "lo": "lao",
            "uz": "uzbek",
            "fo": "faroese",
            "ht": "haitian creole",
            "ps": "pashto",
            "tk": "turkmen",
            "nn": "nynorsk",
            "mt": "maltese",
            "sa": "sanskrit",
            "lb": "luxembourgish",
            "my": "myanmar",
            "bo": "tibetan",
            "tl": "tagalog",
            "mg": "malagasy",
            "as": "assamese",
            "tt": "tatar",
            "haw": "hawaiian",
            "ln": "lingala",
            "ha": "hausa",
            "ba": "bashkir",
            "jw": "javanese",
            "su": "sundanese",
            "yue": "cantonese",
        }

        display = {}
        for code, name in all_languages.items():
            if code not in priority:
                display[code] = f"{name.title()} ({code})"

        return {"priority": priority, "all": all_languages, "display": display}

    def _load_config(self):
        """Load configuration from file."""
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            self._print_error(f"Error loading configuration: {e}")
            return {}

    def _print(self, message):
        """Print with Rich if available, otherwise use regular print."""
        if HAS_RICH:
            console.print(message)
        else:
            print(message)

    def _print_error(self, message):
        """Print error message."""
        if HAS_RICH:
            console.print(f"[bold red]{message}[/bold red]")
        else:
            print(f"ERROR: {message}")

    def _get_available_models(self):
        """Get a list of available Whisper models from the HuggingFace cache."""
        models = []
        cache_dir = os.path.join(
            os.path.expanduser("~"), ".cache", "huggingface", "hub"
        )

        def normalize_model_name(name):
            """Normalize model names for comparison."""
            if name.startswith("models--"):
                parts = name.split("--")
                if len(parts) >= 3:
                    return f"{parts[1]}/{parts[2]}"
            return name

        normalized_models = set()

        if os.path.exists(cache_dir):
            model_dirs = [
                d
                for d in os.listdir(cache_dir)
                if os.path.isdir(os.path.join(cache_dir, d))
            ]
            for model_dir in model_dirs:
                if "whisper" in model_dir.lower():
                    norm_name = normalize_model_name(model_dir)
                    if norm_name not in normalized_models:
                        normalized_models.add(norm_name)
                        models.append(norm_name)

        default_models = [
            "deepdml/faster-whisper-large-v3-turbo-ct2",
            "Systran/faster-whisper-medium",
            "Systran/faster-whisper-large-v3",
        ]

        for model in default_models:
            norm_name = normalize_model_name(model)
            if norm_name not in normalized_models:
                if model not in models:
                    models.append(model)
                    normalized_models.add(norm_name)

        return sorted(models)

    def _update_language_label(self, section):
        """Update the label showing the currently selected language."""
        language_listbox = self.data["variables"].get(
            f"{section}_language_listbox"
        )
        language_label = self.data["variables"].get(f"{section}_language_label")

        if (
            language_listbox
            and language_label
            and language_listbox.curselection()
        ):
            selection_idx = language_listbox.curselection()[0]
            display_name = language_listbox.get(selection_idx)
            language_code = self._get_code_from_display(display_name)
            if language_code:
                language_label.config(
                    text=f"Currently selected: {language_code}"
                )

    def show_dialog(self):
        """Show the configuration dialog."""
        root = self._create_main_window()
        main_frame = self._create_main_frame(root)
        notebook = self._create_notebook(main_frame)
        self._create_tabs(notebook)
        self._create_buttons(root)
        self._bind_events(root)
        root.mainloop()
        return self.apply_clicked

    def _create_main_window(self):
        """Create and configure the main dialog window."""
        root = tk.Tk()
        root.title("Configuration Settings")
        root.geometry("700x600")
        root.configure(bg=self.theme.bg_color)
        root.attributes("-topmost", True)

        # Center the window
        screen_width = root.winfo_screenwidth()
        screen_height = root.winfo_screenheight()
        x = (screen_width - 700) // 2
        y = (screen_height - 600) // 2
        root.geometry(f"700x600+{x}+{y}")

        return root

    def _create_main_frame(self, root):
        """Create the main frame container."""
        main_frame = tk.Frame(root, bg=self.theme.bg_color)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)
        return main_frame

    def _create_notebook(self, main_frame):
        """Create and style the notebook widget."""
        notebook = ttk.Notebook(main_frame)
        notebook.pack(fill="both", expand=True)

        style = ttk.Style()
        style.configure(
            "TNotebook", background=self.theme.bg_color, borderwidth=0
        )
        style.configure(
            "TNotebook.Tab",
            background=self.theme.button_bg,
            foreground="#000000",
            padding=[10, 5],
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", self.theme.highlight_color)],
            foreground=[("selected", "#000000")],
        )

        return notebook

    def _create_tabs(self, notebook):
        """Create all tabs and their content."""
        sections = ["longform", "realtime", "static"]
        tab_names = ["Long Form", "Real-time", "Static"]

        for section, tab_name in zip(sections, tab_names):
            tab = self._create_scrollable_tab(notebook)
            notebook.add(tab, text=tab_name)
            self._create_tab_content(tab.scrollable_frame, section)

    def _create_buttons(self, root):
        """Create Apply and Cancel buttons."""
        button_frame = tk.Frame(root, bg=self.theme.bg_color)
        button_frame.pack(pady=15, padx=20, fill="x")

        apply_button = tk.Button(
            button_frame,
            text="Apply",
            command=lambda: self._save_and_exit(root),
            bg="#4CAF50",
            fg=self.theme.text_color,
            font=("Arial", 12),
            width=10,
            activebackground="#3e8e41",
            activeforeground=self.theme.text_color,
        )
        apply_button.pack(side="right", padx=5)

        cancel_button = tk.Button(
            button_frame,
            text="Cancel",
            command=root.destroy,
            bg="#f44336",
            fg=self.theme.text_color,
            font=("Arial", 12),
            width=10,
            activebackground="#d32f2f",
            activeforeground=self.theme.text_color,
        )
        cancel_button.pack(side="right", padx=5)

    def _bind_events(self, root):
        """Bind keyboard events."""
        root.protocol("WM_DELETE_WINDOW", root.destroy)
        root.bind("<Escape>", lambda e: root.destroy())
        root.bind("<Return>", lambda e: self._save_and_exit(root))

    class ScrollableFrame(tk.Frame):
        """A frame with a scrollbar."""

        def __init__(self, container, *args, bg_color="#333333", **kwargs):
            super().__init__(container, *args, **kwargs)

            self.canvas = tk.Canvas(self, bg=bg_color, highlightthickness=0)
            self.scrollbar = ttk.Scrollbar(
                self, orient="vertical", command=self.canvas.yview
            )
            self.scrollable_frame = tk.Frame(self.canvas, bg=bg_color)

            self.scrollable_frame.bind(
                "<Configure>",
                lambda e: self.canvas.configure(
                    scrollregion=self.canvas.bbox("all")
                ),
            )

            self.canvas_window = self.canvas.create_window(
                (0, 0), window=self.scrollable_frame, anchor="nw"
            )
            self.canvas.configure(yscrollcommand=self.scrollbar.set)

            self.canvas.bind("<Configure>", self._adjust_window_width)
            self.canvas.pack(side="left", fill="both", expand=True)
            self.scrollbar.pack(side="right", fill="y")
            self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

        def _adjust_window_width(self, event):
            """Adjust the width of the canvas window when resized."""
            self.canvas.itemconfig(self.canvas_window, width=event.width)

        def _on_mousewheel(self, event):
            """Handle mousewheel scrolling."""
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _create_scrollable_tab(self, notebook):
        """Create a tab with a scrollable frame."""
        tab = self.ScrollableFrame(notebook, bg_color=self.theme.bg_color)
        return tab

    def _create_tab_content(self, tab, section):
        """Create content for a tab."""
        self._create_title(tab, section)
        self._ensure_section_exists(section)
        self._create_model_selection(tab, section)
        self._create_language_selection(tab, section)
        self._create_audio_selection(tab, section)
        self._create_advanced_params(tab, section)

        if section == "longform":
            self._create_keyboard_options(tab)

    def _create_title(self, tab, section):
        """Create title for the tab."""
        title_frame = tk.Frame(tab, bg=self.theme.bg_color, pady=10)
        title_frame.pack(fill="x")

        title_label = tk.Label(
            title_frame,
            text=f"{section.capitalize()} Configuration",
            bg=self.theme.bg_color,
            fg=self.theme.text_color,
            font=("Arial", 14, "bold"),
        )
        title_label.pack()

    def _ensure_section_exists(self, section):
        """Ensure section exists in config."""
        if section not in self.data["config"]:
            self.data["config"][section] = {}

    def _create_model_selection(self, tab, section):
        """Create model selection dropdown."""
        model_frame = self._create_section(tab, "Model")
        model_frame.pack(fill="x", pady=5)

        models = self._get_available_models()
        current_model = self.data["config"][section].get(
            "model", "Systran/faster-whisper-large-v3"
        )

        model_var = tk.StringVar(value=current_model)
        model_dropdown = ttk.Combobox(
            model_frame,
            textvariable=model_var,
            values=models,
            state="readonly",
            width=40,
        )
        model_dropdown.pack(side="right")
        self.data["variables"][f"{section}_model"] = model_var

    def _create_language_selection(self, tab, section):
        """Create language selection listbox."""
        language_frame = self._create_section(tab, "Language")
        language_frame.pack(fill="x", pady=5)

        languages_listbox_frame = tk.Frame(tab, bg=self.theme.bg_color)
        languages_listbox_frame.pack(fill="x", padx=20, pady=5)

        current_language = self.data["config"][section].get("language", "en")

        languages_label = tk.Label(
            languages_listbox_frame,
            text="Select Language:",
            bg=self.theme.bg_color,
            fg=self.theme.text_color,
            font=("Arial", 10),
            anchor="w",
        )
        languages_label.pack(anchor="w")

        language_listbox = self._create_language_listbox(
            languages_listbox_frame, current_language
        )

        current_language_label = tk.Label(
            languages_listbox_frame,
            text=f"Currently selected: {current_language}",
            bg=self.theme.bg_color,
            fg=self.theme.text_color,
            font=("Arial", 10, "italic"),
            anchor="w",
        )
        current_language_label.pack(anchor="w", pady=(5, 0))

        self.data["variables"][
            f"{section}_language_label"
        ] = current_language_label
        language_listbox.bind(
            "<<ListboxSelect>>",
            lambda e, s=section: self._update_language_label(s),
        )
        self.data["variables"][f"{section}_language_listbox"] = language_listbox

    def _create_language_listbox(self, parent, current_language):
        """Create and populate the language listbox."""
        listbox_container = tk.Frame(parent, bg=self.theme.bg_color)
        listbox_container.pack(fill="x", pady=5)

        listbox_scrollbar = tk.Scrollbar(
            listbox_container,
            bg=self.theme.button_bg,
            troughcolor=self.theme.bg_color,
        )
        listbox_scrollbar.pack(side="right", fill="y")

        language_listbox = tk.Listbox(
            listbox_container,
            yscrollcommand=listbox_scrollbar.set,
            font=("Segoe UI Emoji", 11),
            selectmode="single",
            height=7,
            bg=self.theme.entry_bg,
            fg=self.theme.text_color,
            selectbackground=self.theme.highlight_color,
            selectforeground=self.theme.text_color,
        )
        language_listbox.pack(side="left", fill="x", expand=True)
        listbox_scrollbar.config(command=language_listbox.yview)

        # Populate listbox
        for display_name in self.data["language_data"]["priority"].values():
            language_listbox.insert(tk.END, display_name)

        language_listbox.insert(tk.END, "───────────────────")

        sorted_display = sorted(self.data["language_data"]["display"].values())
        for display_name in sorted_display:
            language_listbox.insert(tk.END, display_name)

        # Select current language
        for i in range(language_listbox.size()):
            item = language_listbox.get(i)
            if current_language in item and f"({current_language})" in item:
                language_listbox.selection_set(i)
                language_listbox.see(i)
                break

        return language_listbox

    def _create_audio_selection(self, tab, section):
        """Create audio source selection."""
        audio_frame = self._create_section(tab, "Audio Source (Placeholder)")
        audio_frame.pack(fill="x", pady=5)

        audio_var = tk.StringVar(value="Microphone")
        audio_dropdown = ttk.Combobox(
            audio_frame,
            textvariable=audio_var,
            values=["Microphone", "System Audio"],
            state="readonly",
            width=40,
        )
        audio_dropdown.pack(side="right")
        self.data["variables"][f"{section}_audio"] = audio_var

    def _create_advanced_params(self, tab, section):
        """Create advanced parameters section."""
        params_frame = tk.Frame(tab, bg=self.theme.bg_color, pady=10)
        params_frame.pack(fill="x")

        params_label = tk.Label(
            params_frame,
            text="Advanced Parameters:",
            bg=self.theme.bg_color,
            fg=self.theme.text_color,
            font=("Arial", 12, "bold"),
        )
        params_label.pack(anchor="w", padx=10)

        for param, value in self.data["config"][section].items():
            if param in ["model", "language"]:
                continue

            param_frame = self._create_section(tab, param)
            param_frame.pack(fill="x", pady=5)

            widget, var = self._create_parameter_widget(param_frame, value)
            widget.pack(side="right")
            self.data["variables"][f"{section}_{param}"] = var

    def _create_parameter_widget(self, parent, value):
        """Create appropriate widget for parameter based on type."""
        if isinstance(value, bool):
            var = tk.BooleanVar(value=value)
            widget = tk.Checkbutton(
                parent,
                variable=var,
                bg=self.theme.bg_color,
                activebackground=self.theme.bg_color,
                selectcolor=self.theme.entry_bg,
                bd=0,
                highlightthickness=0,
            )
        elif isinstance(value, (int, float)):
            var = tk.StringVar(value=str(value))
            widget = tk.Entry(
                parent,
                textvariable=var,
                bg=self.theme.entry_bg,
                fg=self.theme.text_color,
                width=40,
                insertbackground=self.theme.text_color,
            )
        elif value is None:
            var = tk.StringVar(value="")
            widget = tk.Entry(
                parent,
                textvariable=var,
                bg=self.theme.entry_bg,
                fg=self.theme.text_color,
                width=40,
                insertbackground=self.theme.text_color,
            )
        else:
            var = tk.StringVar(value=str(value))
            widget = tk.Entry(
                parent,
                textvariable=var,
                bg=self.theme.entry_bg,
                fg=self.theme.text_color,
                width=40,
                insertbackground=self.theme.text_color,
            )
        return widget, var

    def _create_keyboard_options(self, tab):
        """Create keyboard options for longform tab."""
        enter_frame = tk.Frame(tab, bg=self.theme.bg_color, pady=10)
        enter_frame.pack(fill="x")

        enter_label = tk.Label(
            enter_frame,
            text="Keyboard Options:",
            bg=self.theme.bg_color,
            fg=self.theme.text_color,
            font=("Arial", 12, "bold"),
        )
        enter_label.pack(anchor="w", padx=10)

        send_enter_frame = self._create_section(
            tab, "Send Enter After Typing (Placeholder)"
        )
        send_enter_frame.pack(fill="x", pady=5)

        enter_var = tk.BooleanVar(value=False)
        enter_checkbox = tk.Checkbutton(
            send_enter_frame,
            variable=enter_var,
            bg=self.theme.bg_color,
            activebackground=self.theme.bg_color,
            selectcolor=self.theme.entry_bg,
            bd=0,
            highlightthickness=0,
        )
        enter_checkbox.pack(side="right")
        self.data["variables"]["send_enter"] = enter_var

    def _create_section(self, parent, title):
        """Create a section with a label."""
        frame = tk.Frame(parent, bg=self.theme.bg_color, padx=20, pady=5)

        label = tk.Label(
            frame,
            text=title,
            bg=self.theme.bg_color,
            fg=self.theme.text_color,
            font=("Arial", 10),
            anchor="w",
            width=30,
        )
        label.pack(side="left")

        return frame

    def _get_code_from_display(self, display_name):
        """Extract language code from display name."""
        for code, priority_name in self.data["language_data"][
            "priority"
        ].items():
            if display_name == priority_name:
                return code

        if "───" in display_name:
            return None

        try:
            return display_name.split("(")[1].split(")")[0]
        except IndexError:
            return None

    def _save_and_exit(self, root):
        """Save the configuration and exit."""
        self.apply_clicked = True
        self.data["updated_config"] = copy.deepcopy(self.data["config"])

        self._update_config_from_variables()
        self._save_config_to_file()

        if self.callback:
            self.callback(self.data["updated_config"])

        root.destroy()

    def _update_config_from_variables(self):
        """Update configuration from UI variables."""
        for section in ["longform", "realtime", "static"]:
            self._update_section_config(section)

    def _update_section_config(self, section):
        """Update configuration for a specific section."""
        # Update model
        model_var = self.data["variables"].get(f"{section}_model")
        if model_var:
            self.data["updated_config"][section]["model"] = model_var.get()

        # Update language
        self._update_language_config(section)

        # Update other parameters
        self._update_other_params(section)

    def _update_language_config(self, section):
        """Update language configuration from listbox."""
        language_listbox = self.data["variables"].get(
            f"{section}_language_listbox"
        )
        if language_listbox and language_listbox.curselection():
            selection_idx = language_listbox.curselection()[0]
            display_name = language_listbox.get(selection_idx)
            language_code = self._get_code_from_display(display_name)
            if language_code:
                self.data["updated_config"][section]["language"] = language_code

    def _update_other_params(self, section):
        """Update other parameters for a section."""
        for param in self.data["config"][section]:
            if param in ["model", "language"]:
                continue

            var = self.data["variables"].get(f"{section}_{param}")
            if var:
                value = var.get()
                value = self._convert_param_value(
                    value, self.data["config"][section][param]
                )
                self.data["updated_config"][section][param] = value

    def _convert_param_value(self, value, original_value):
        """Convert parameter value to appropriate type."""
        if isinstance(original_value, bool):
            return bool(value)
        if isinstance(original_value, int):
            try:
                return int(value)
            except ValueError:
                return original_value
        if isinstance(original_value, float):
            try:
                return float(value)
            except ValueError:
                return original_value
        return value

    def _save_config_to_file(self):
        """Save configuration to file."""
        try:
            fixed_config = self._fix_none_values(self.data["updated_config"])
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(fixed_config, f, indent=4)
            self._print("Configuration saved successfully")
        except (IOError, OSError) as e:
            self._print_error(f"Error saving configuration: {e}")

    def _fix_none_values(self, obj):
        """Fix None values in configuration object."""
        if isinstance(obj, dict):
            return {k: self._fix_none_values(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self._fix_none_values(i) for i in obj]
        if obj == "":
            return None
        return obj

    def get_current_config(self):
        """Get the current configuration."""
        return self.data["config"].copy()


# Constants for testing
CONFIG_PATH_DEFAULT = "config.json"

if __name__ == "__main__":
    # Get the directory of this script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    test_config_path = os.path.join(script_dir, CONFIG_PATH_DEFAULT)

    # Create and show the dialog
    dialog = ConfigurationDialog(test_config_path)
    RESULT = dialog.show_dialog()

    print(f"Dialog closed with Apply: {RESULT}")
