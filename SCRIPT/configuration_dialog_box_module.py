# configuration_dialog.py
# 
# Provides a graphical configuration interface for the speech-to-text application
#
# This module creates and manages a Tkinter-based configuration dialog that allows:
# - Setting model, language, and audio source preferences for each mode (Long Form, Real-time, Static)
# - Configuring advanced parameters for each mode
# - Setting the "send Enter key" option for Long Form mode
#
# The dialog presents a tabbed interface with:
# - Long Form tab: Configuration for long-form transcription
# - Real-time tab: Configuration for real-time transcription 
# - Static tab: Configuration for static file transcription

import os
import sys
import tkinter as tk
from tkinter import ttk
import json
import logging

# Try to import Rich for pretty printing
try:
    from rich.console import Console
    console = Console()
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

class ConfigurationDialog:
    def __init__(self, config_path, callback=None):
        self.config_path = config_path
        self.callback = callback
        self.apply_clicked = False
        
        # Load configuration
        try:
            with open(config_path, 'r') as f:
                self.config = json.load(f)
        except Exception as e:
            self._print_error(f"Error loading configuration: {e}")
            self.config = {}
        
        # Languages to display first with flag icons
        self.priority_languages = {
            "en": "🇬🇧 English (en)",
            "el": "🇬🇷 Greek (el)",
            "ru": "🇷🇺 Russian (ru)",
            "zh": "🇨🇳 Chinese (zh)",
            "de": "🇩🇪 German (de)",
            "fr": "🇫🇷 French (fr)"
        }
        
        # All supported languages from Whisper
        self.languages = {
            "en": "english", "zh": "chinese", "de": "german", "es": "spanish",
            "ru": "russian", "ko": "korean", "fr": "french", "ja": "japanese",
            "pt": "portuguese", "tr": "turkish", "pl": "polish", "ca": "catalan",
            "nl": "dutch", "ar": "arabic", "sv": "swedish", "it": "italian",
            "id": "indonesian", "hi": "hindi", "fi": "finnish", "vi": "vietnamese",
            "he": "hebrew", "uk": "ukrainian", "el": "greek", "ms": "malay",
            "cs": "czech", "ro": "romanian", "da": "danish", "hu": "hungarian",
            "ta": "tamil", "no": "norwegian", "th": "thai", "ur": "urdu",
            "hr": "croatian", "bg": "bulgarian", "lt": "lithuanian", "la": "latin",
            "mi": "maori", "ml": "malayalam", "cy": "welsh", "sk": "slovak",
            "te": "telugu", "fa": "persian", "lv": "latvian", "bn": "bengali",
            "sr": "serbian", "az": "azerbaijani", "sl": "slovenian", "kn": "kannada",
            "et": "estonian", "mk": "macedonian", "br": "breton", "eu": "basque",
            "is": "icelandic", "hy": "armenian", "ne": "nepali", "mn": "mongolian",
            "bs": "bosnian", "kk": "kazakh", "sq": "albanian", "sw": "swahili",
            "gl": "galician", "mr": "marathi", "pa": "punjabi", "si": "sinhala",
            "km": "khmer", "sn": "shona", "yo": "yoruba", "so": "somali",
            "af": "afrikaans", "oc": "occitan", "ka": "georgian", "be": "belarusian",
            "tg": "tajik", "sd": "sindhi", "gu": "gujarati", "am": "amharic",
            "yi": "yiddish", "lo": "lao", "uz": "uzbek", "fo": "faroese",
            "ht": "haitian creole", "ps": "pashto", "tk": "turkmen", "nn": "nynorsk",
            "mt": "maltese", "sa": "sanskrit", "lb": "luxembourgish", "my": "myanmar",
            "bo": "tibetan", "tl": "tagalog", "mg": "malagasy", "as": "assamese",
            "tt": "tatar", "haw": "hawaiian", "ln": "lingala", "ha": "hausa",
            "ba": "bashkir", "jw": "javanese", "su": "sundanese", "yue": "cantonese"
        }
        
        # Build display names for non-priority languages
        self.language_display = {}
        for code, name in self.languages.items():
            if code not in self.priority_languages:
                self.language_display[code] = f"{name.title()} ({code})"
        
        # Variables for storing updated values
        self.updated_config = {}
        
        # Store variables for different parameters
        self.variables = {}
    
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
        import os
        import glob
        
        models = []
        cache_dir = os.path.join(os.path.expanduser("~"), ".cache", "huggingface", "hub")

        # Helper function to normalize model names for comparison
        def normalize_model_name(name):
            # Remove 'models--' prefix and replace '--' with '/'
            if name.startswith("models--"):
                parts = name.split("--")
                if len(parts) >= 3:
                    return f"{parts[1]}/{parts[2]}"
            return name
        
        # Track normalized names to avoid duplicates
        normalized_models = set()
        
        if os.path.exists(cache_dir):
            # Look for model directories directly in the hub folder
            model_dirs = [d for d in os.listdir(cache_dir) if os.path.isdir(os.path.join(cache_dir, d))]
            for model_dir in model_dirs:
                # Only add model directories that have "whisper" in the name
                if "whisper" in model_dir.lower():
                    norm_name = normalize_model_name(model_dir)
                    if norm_name not in normalized_models:
                        normalized_models.add(norm_name)
                        models.append(norm_name)  # Use normalized name instead of directory name
        
        # Add default models if not found
        default_models = [
            "deepdml/faster-whisper-large-v3-turbo-ct2",
            "Systran/faster-whisper-medium",
            "Systran/faster-whisper-large-v3"
        ]
        
        for model in default_models:
            # Check if this model (or a variant) is already in the list
            norm_name = normalize_model_name(model)
            if norm_name not in normalized_models:
                if model not in models:
                    models.append(model)
                    normalized_models.add(norm_name)
        
        return sorted(models)

    def _update_language_label(self, section):
        """Update the label showing the currently selected language."""
        language_listbox = self.variables.get(f"{section}_language_listbox")
        language_label = self.variables.get(f"{section}_language_label")
        
        if language_listbox and language_label and language_listbox.curselection():
            selection_idx = language_listbox.curselection()[0]
            display_name = language_listbox.get(selection_idx)
            language_code = self._get_code_from_display(display_name)
            if language_code:
                language_label.config(text=f"Currently selected: {language_code}")

    def show_dialog(self):
        """Show the configuration dialog."""
        # Create the main dialog window
        root = tk.Tk()
        root.title("Configuration Settings")

        # Dark theme colors
        bg_color = "#333333"        # Dark grey background
        text_color = "#FFFFFF"      # White text
        entry_bg = "#555555"        # Slightly lighter grey for input fields
        button_bg = "#444444"       # Medium grey for buttons
        highlight_color = "#007ACC" # Blue highlight color

        # Size and position
        root.geometry("700x600")
        root.configure(bg=bg_color)

        # Make dialog appear on top
        root.attributes('-topmost', True)

        # Center the window
        screen_width = root.winfo_screenwidth()
        screen_height = root.winfo_screenheight()
        x = (screen_width - 700) // 2
        y = (screen_height - 600) // 2
        root.geometry(f"700x600+{x}+{y}")

        # Create container with scrollbar
        main_frame = tk.Frame(root, bg=bg_color)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # Notebook for tabs
        notebook = ttk.Notebook(main_frame)
        notebook.pack(fill="both", expand=True)
        
        # Style for the notebook
        style = ttk.Style()
        style.configure("TNotebook", background=bg_color, borderwidth=0)
        style.configure("TNotebook.Tab", background=button_bg, foreground="#000000", padding=[10, 5])
        style.map("TNotebook.Tab", background=[("selected", highlight_color)], foreground=[("selected", "#000000")])
        
        # Create tabs with scrollbars
        longform_tab = self._create_scrollable_tab(notebook, bg_color, button_bg)
        realtime_tab = self._create_scrollable_tab(notebook, bg_color, button_bg)
        static_tab = self._create_scrollable_tab(notebook, bg_color, button_bg)
        
        notebook.add(longform_tab, text="Long Form")
        notebook.add(realtime_tab, text="Real-time")
        notebook.add(static_tab, text="Static")
        
        # Create contents for each tab
        longform_frame = longform_tab.scrollable_frame
        realtime_frame = realtime_tab.scrollable_frame
        static_frame = static_tab.scrollable_frame
        
        self._create_tab_content(longform_frame, "longform", bg_color, text_color, entry_bg, highlight_color, button_bg)
        self._create_tab_content(realtime_frame, "realtime", bg_color, text_color, entry_bg, highlight_color, button_bg)
        self._create_tab_content(static_frame, "static", bg_color, text_color, entry_bg, highlight_color, button_bg)
        
        # Add buttons
        button_frame = tk.Frame(root, bg=bg_color)
        button_frame.pack(pady=15, padx=20, fill="x")

        apply_button = tk.Button(
            button_frame, 
            text="Apply", 
            command=lambda: self._save_and_exit(root),
            bg="#4CAF50",
            fg=text_color,
            font=("Arial", 12),
            width=10,
            activebackground="#3e8e41",
            activeforeground=text_color
        )
        apply_button.pack(side="right", padx=5)

        cancel_button = tk.Button(
            button_frame, 
            text="Cancel", 
            command=root.destroy,
            bg="#f44336",
            fg=text_color,
            font=("Arial", 12),
            width=10,
            activebackground="#d32f2f",
            activeforeground=text_color
        )
        cancel_button.pack(side="right", padx=5)
        
        # Handle window close event (X button) as cancellation
        root.protocol("WM_DELETE_WINDOW", root.destroy)
        
        # Bind Escape key to cancel
        root.bind("<Escape>", lambda e: root.destroy())
        
        # Bind Enter key to apply
        root.bind("<Return>", lambda e: self._save_and_exit(root))
        
        # Run the dialog
        root.mainloop()
        
        # Return True if Apply was clicked, False otherwise
        return self.apply_clicked
    
    class ScrollableFrame(tk.Frame):
        """A frame with a scrollbar."""
        def __init__(self, container, bg_color, button_bg=None, *args, **kwargs):
            super().__init__(container, *args, **kwargs)
            
            if button_bg is None:
                button_bg = "#444444"  # Default medium grey for buttons
            
            # Create a canvas and scrollbar
            self.canvas = tk.Canvas(self, bg=bg_color, highlightthickness=0)
            self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
            self.scrollable_frame = tk.Frame(self.canvas, bg=bg_color)
            
            # Configure the scrollable frame
            self.scrollable_frame.bind(
                "<Configure>",
                lambda e: self.canvas.configure(
                    scrollregion=self.canvas.bbox("all")
                )
            )
            
            # Create window in canvas and configure
            self.canvas_window = self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
            self.canvas.configure(yscrollcommand=self.scrollbar.set)
            
            # Bind canvas resize to adjust window width
            self.canvas.bind("<Configure>", self._adjust_window_width)
            
            # Pack the canvas and scrollbar
            self.canvas.pack(side="left", fill="both", expand=True)
            self.scrollbar.pack(side="right", fill="y")
            
            # Bind mousewheel to scroll
            self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
            
        def _adjust_window_width(self, event):
            """Adjust the width of the canvas window when the canvas is resized."""
            self.canvas.itemconfig(self.canvas_window, width=event.width)
            
        def _on_mousewheel(self, event):
            """Handle mousewheel scrolling."""
            self.canvas.yview_scroll(int(-1*(event.delta/120)), "units")
    
    def _create_scrollable_tab(self, notebook, bg_color, button_bg=None):
        """Create a tab with a scrollable frame."""
        if button_bg is None:
            button_bg = "#444444"  # Default medium grey for buttons
        tab = self.ScrollableFrame(notebook, bg_color, button_bg, bg=bg_color)
        return tab
    
    def _create_tab_content(self, tab, section, bg_color, text_color, entry_bg, highlight_color, button_bg=None):
        """Create content for a tab."""
        # Default button background if not provided
        if button_bg is None:
            button_bg = "#444444"  # Medium grey for buttons
            
        # Create a title frame
        title_frame = tk.Frame(tab, bg=bg_color, pady=10)
        title_frame.pack(fill="x")
        
        title_label = tk.Label(
            title_frame,
            text=f"{section.capitalize()} Configuration",
            bg=bg_color,
            fg=text_color,
            font=("Arial", 14, "bold")
        )
        title_label.pack()
        
        # Ensure this section exists in config
        if section not in self.config:
            self.config[section] = {}
            
        # Create model selection
        model_frame = self._create_section(
            tab, "Model", 
            bg_color, text_color, entry_bg, highlight_color
        )
        model_frame.pack(fill="x", pady=5)
        
        models = self._get_available_models()
        current_model = self.config[section].get("model", "Systran/faster-whisper-large-v3")
        
        model_var = tk.StringVar(value=current_model)
        model_dropdown = ttk.Combobox(
            model_frame, 
            textvariable=model_var,
            values=models,
            state="readonly",
            width=40
        )
        model_dropdown.pack(side="right")
        
        # Store the variable for later use
        self.variables[f"{section}_model"] = model_var
        
        # Create language selection
        language_frame = self._create_section(
            tab, "Language", 
            bg_color, text_color, entry_bg, highlight_color
        )
        language_frame.pack(fill="x", pady=5)

        languages_listbox_frame = tk.Frame(tab, bg=bg_color)
        languages_listbox_frame.pack(fill="x", padx=20, pady=5)

        # Get the current language FIRST
        current_language = self.config[section].get("language", "en")

        languages_label = tk.Label(
            languages_listbox_frame,
            text="Select Language:",
            bg=bg_color,
            fg=text_color,
            font=("Arial", 10),
            anchor="w"
        )
        languages_label.pack(anchor="w")
        
        # Create a frame for the listbox and scrollbar
        listbox_container = tk.Frame(languages_listbox_frame, bg=bg_color)
        listbox_container.pack(fill="x", pady=5)
        
        listbox_scrollbar = tk.Scrollbar(listbox_container, bg=button_bg, troughcolor=bg_color)
        listbox_scrollbar.pack(side="right", fill="y")
        
        language_listbox = tk.Listbox(
            listbox_container,
            yscrollcommand=listbox_scrollbar.set,
            font=("Segoe UI Emoji", 11),
            selectmode="single",
            height=7,  # Show 7-8 languages at a time
            bg=entry_bg,
            fg=text_color,
            selectbackground=highlight_color,
            selectforeground=text_color
        )
        language_listbox.pack(side="left", fill="x", expand=True)
        listbox_scrollbar.config(command=language_listbox.yview)
        
        # Populate the listbox with priority languages first
        for code, display_name in self.priority_languages.items():
            language_listbox.insert(tk.END, display_name)
            
        # Add a separator
        language_listbox.insert(tk.END, "───────────────────")
        
        # Add other languages in alphabetical order
        sorted_display = sorted(self.language_display.values())
        for display_name in sorted_display:
            language_listbox.insert(tk.END, display_name)

        # Add a label to show the currently selected language
        current_language_label = tk.Label(
            languages_listbox_frame,
            text=f"Currently selected: {current_language}",
            bg=bg_color,
            fg=text_color,
            font=("Arial", 10, "italic"),
            anchor="w"
        )
        current_language_label.pack(anchor="w", pady=(5, 0))

        # Store the label for later use
        self.variables[f"{section}_language_label"] = current_language_label

        # Bind the listbox selection event to update the label
        language_listbox.bind("<<ListboxSelect>>", lambda e, s=section: self._update_language_label(s))
        
        # Select the current language
        for i in range(language_listbox.size()):
            item = language_listbox.get(i)
            if current_language in item and f"({current_language})" in item:
                language_listbox.selection_set(i)
                language_listbox.see(i)
                break
        
        # Store the listbox for later use
        self.variables[f"{section}_language_listbox"] = language_listbox
        
        # Create audio source selection (placeholder)
        audio_frame = self._create_section(
            tab, "Audio Source (Placeholder)", 
            bg_color, text_color, entry_bg, highlight_color
        )
        audio_frame.pack(fill="x", pady=5)
        
        audio_var = tk.StringVar(value="Microphone")
        audio_dropdown = ttk.Combobox(
            audio_frame, 
            textvariable=audio_var,
            values=["Microphone", "System Audio"],
            state="readonly",
            width=40
        )
        audio_dropdown.pack(side="right")
        
        # Store the variable for later use
        self.variables[f"{section}_audio"] = audio_var
        
        # Add other parameters
        params_frame = tk.Frame(tab, bg=bg_color, pady=10)
        params_frame.pack(fill="x")
        
        params_label = tk.Label(
            params_frame,
            text="Advanced Parameters:",
            bg=bg_color,
            fg=text_color,
            font=("Arial", 12, "bold")
        )
        params_label.pack(anchor="w", padx=10)
        
        for param, value in self.config[section].items():
            # Skip parameters that are handled separately
            if param in ["model", "language"]:
                continue
                
            # Create a frame for this parameter
            param_frame = self._create_section(
                tab, param, 
                bg_color, text_color, entry_bg, highlight_color
            )
            param_frame.pack(fill="x", pady=5)
            
            # Create an appropriate widget based on the parameter type
            if isinstance(value, bool):
                var = tk.BooleanVar(value=value)
                widget = tk.Checkbutton(
                    param_frame,
                    variable=var,
                    bg=bg_color,
                    activebackground=bg_color,
                    selectcolor=entry_bg,
                    bd=0,
                    highlightthickness=0
                )
            elif isinstance(value, int) or isinstance(value, float):
                var = tk.StringVar(value=str(value))
                widget = tk.Entry(
                    param_frame,
                    textvariable=var,
                    bg=entry_bg,
                    fg=text_color,
                    width=40,
                    insertbackground=text_color
                )
            elif value is None:
                var = tk.StringVar(value="")
                widget = tk.Entry(
                    param_frame,
                    textvariable=var,
                    bg=entry_bg,
                    fg=text_color,
                    width=40,
                    insertbackground=text_color
                )
            else:
                var = tk.StringVar(value=str(value))
                widget = tk.Entry(
                    param_frame,
                    textvariable=var,
                    bg=entry_bg,
                    fg=text_color,
                    width=40,
                    insertbackground=text_color
                )
            
            widget.pack(side="right")
            
            # Store the variable for later use
            self.variables[f"{section}_{param}"] = var
        
        # Add "Send Enter" option only for Long Form tab
        if section == "longform":
            enter_frame = tk.Frame(tab, bg=bg_color, pady=10)
            enter_frame.pack(fill="x")
            
            enter_label = tk.Label(
                enter_frame,
                text="Keyboard Options:",
                bg=bg_color,
                fg=text_color,
                font=("Arial", 12, "bold")
            )
            enter_label.pack(anchor="w", padx=10)
            
            send_enter_frame = self._create_section(
                tab, "Send Enter After Typing (Placeholder)", 
                bg_color, text_color, entry_bg, highlight_color
            )
            send_enter_frame.pack(fill="x", pady=5)
            
            enter_var = tk.BooleanVar(value=False)  # Placeholder
            enter_checkbox = tk.Checkbutton(
                send_enter_frame,
                variable=enter_var,
                bg=bg_color,
                activebackground=bg_color,
                selectcolor=entry_bg,
                bd=0,
                highlightthickness=0
            )
            enter_checkbox.pack(side="right")
            
            # Store the variable for later use
            self.variables["send_enter"] = enter_var
    
    def _create_section(self, parent, title, bg_color, text_color, entry_bg, highlight_color):
        """Create a section with a label."""
        frame = tk.Frame(parent, bg=bg_color, padx=20, pady=5)
        
        label = tk.Label(
            frame,
            text=title,
            bg=bg_color,
            fg=text_color,
            font=("Arial", 10),
            anchor="w",
            width=30
        )
        label.pack(side="left")
        
        return frame
    
    def _get_code_from_display(self, display_name):
        """Extract language code from display name."""
        # Check if it's a priority language with flag
        for code, priority_name in self.priority_languages.items():
            if display_name == priority_name:
                return code
            
        # Check if it's a separator
        if "───" in display_name:
            return None
                
        # Extract from regular language format
        try:
            return display_name.split("(")[1].split(")")[0]
        except (IndexError, Exception):
            return None
    
    def _save_and_exit(self, root):
        """Save the configuration and exit."""
        self.apply_clicked = True
        
        # Make a deep copy of the current config
        import copy
        self.updated_config = copy.deepcopy(self.config)
        
        # Update the configuration from the variables
        for section in ["longform", "realtime", "static"]:
            # Update model
            model_var = self.variables.get(f"{section}_model")
            if model_var:
                self.updated_config[section]["model"] = model_var.get()
                
            # Update language from listbox
            language_listbox = self.variables.get(f"{section}_language_listbox")
            if language_listbox and language_listbox.curselection():
                selection_idx = language_listbox.curselection()[0]
                display_name = language_listbox.get(selection_idx)
                language_code = self._get_code_from_display(display_name)
                if language_code:
                    self.updated_config[section]["language"] = language_code
                
            # Update other parameters
            for param in self.config[section]:
                # Skip parameters that are handled separately
                if param in ["model", "language"]:
                    continue
                    
                var = self.variables.get(f"{section}_{param}")
                if var:
                    value = var.get()
                    
                    # Convert to appropriate type
                    if isinstance(self.config[section][param], bool):
                        value = bool(value)
                    elif isinstance(self.config[section][param], int):
                        try:
                            value = int(value)
                        except ValueError:
                            pass
                    elif isinstance(self.config[section][param], float):
                        try:
                            value = float(value)
                        except ValueError:
                            pass
                    
                    self.updated_config[section][param] = value
        
        # Save the send_enter option if it exists
        send_enter_var = self.variables.get("send_enter")
        if send_enter_var:
            # This is a placeholder - we'll implement it later
            pass
        
        # Save the configuration to file
        try:
            # Define a function to fix None values
            def fix_none_values(obj):
                if isinstance(obj, dict):
                    return {k: fix_none_values(v) for k, v in obj.items()}
                elif isinstance(obj, list):
                    return [fix_none_values(i) for i in obj]
                elif obj == "":
                    return None  # Convert empty strings back to None
                else:
                    return obj
            
            # Apply the fix to the config object
            fixed_config = fix_none_values(self.updated_config)
            
            with open(self.config_path, 'w') as f:
                json.dump(fixed_config, f, indent=4)
            self._print("Configuration saved successfully")
        except Exception as e:
            self._print_error(f"Error saving configuration: {e}")
        
        # Call the callback if provided
        if self.callback:
            self.callback(self.updated_config)
        
        # Close the dialog
        root.destroy()


# For standalone testing
if __name__ == "__main__":
    # Get the directory of this script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, "config.json")
    
    # Create and show the dialog
    dialog = ConfigurationDialog(config_path)
    result = dialog.show_dialog()
    
    print(f"Dialog closed with Apply: {result}")