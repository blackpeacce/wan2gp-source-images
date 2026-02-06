"""
Source Images Metadata Plugin

This plugin hooks into the metadata save process to include the file paths
of all input images used during generation. 

The paths are captured from Gradio inputs. For browser uploads, these are 
temp paths but the original filename is preserved. The plugin searches the
configured output folders to find and store the original file path.

This allows for:
- Gallery plugins to access/display source images
- Re-generation with the same inputs
- Chaining outputs through multiple generation steps
"""

import os
import json
import gradio as gr
from shared.utils.plugins import WAN2GPPlugin
from .utils import find_file_by_name

# List of image input keys to track
IMAGE_ATTACHMENT_KEYS = [
    "image_start",      # Starting image for I2V
    "image_end",        # End frame image
    "image_refs",       # Reference images (list)
    "image_guide",      # Control/guidance image (pose, depth, etc.)
    "image_mask",       # Mask image for inpainting
    "custom_guide",     # Custom guidance input
]

# Config key for storing custom search directories
CONFIG_KEY_SEARCH_DIRS = "source_images_search_dirs"

# Global reference to plugin instance for accessing server_config
_plugin_instance = None


def get_configured_output_dirs():
    """Get output directories from server_config and custom dirs if available."""
    global _plugin_instance
    
    search_dirs = []

    plugin_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.dirname(os.path.dirname(plugin_dir))
    
    if _plugin_instance and hasattr(_plugin_instance, 'server_config') and _plugin_instance.server_config:
        config = _plugin_instance.server_config
        
        # Get all configured output paths
        for key in ['save_path', 'image_save_path', 'audio_save_path']:
            path = config.get(key)
            if path and os.path.isdir(path) and path not in search_dirs:
                search_dirs.append(path)
        
        # Get custom search directories configured by user
        custom_dirs = config.get(CONFIG_KEY_SEARCH_DIRS, [])
        if isinstance(custom_dirs, list):
            for path in custom_dirs:
                if path and os.path.isdir(path) and path not in search_dirs:
                    search_dirs.append(path)
    
    # Add default outputs folder
    default_outputs = os.path.join(root_dir, 'outputs')
    if os.path.isdir(default_outputs) and default_outputs not in search_dirs:
        search_dirs.append(default_outputs)
    
    return search_dirs


def resolve_and_build_info(path):
    """
    Build info dict for a path, resolving temp paths to original files.
    
    Args:
        path: File path (may be temp or real)
        
    Returns:
        Dict with path info, including resolved original_path if found
    """
    if not path or not isinstance(path, str):
        return None
    
    filename = os.path.basename(path)
    is_temp = 'gradio' in path.lower() and ('temp' in path.lower() or 'appdata' in path.lower())
    
    info = {
        'filename': filename,
        'is_temp': is_temp,
    }
    
    if is_temp:
        # Get configured output directories
        search_dirs = get_configured_output_dirs()
        
        # Try to find the original file in output folders
        original_path = find_file_by_name(filename, search_dirs=search_dirs)
        if original_path:
            info['original_path'] = original_path
            print(f"[SourceImagesPlugin] Found original: {filename} -> {original_path}")
        else:
            # Store temp path as fallback (valid during session)
            info['temp_path'] = path
            print(f"[SourceImagesPlugin] No original found for {filename}, using temp path")
    else:
        # It's already a real path
        info['original_path'] = path
    
    return info


def process_source_paths(source_paths):
    """
    Process source paths to extract useful info and resolve originals.
    
    Args:
        source_paths: Dict mapping image keys to file paths
        
    Returns:
        Dict with path info for each source image
    """
    if not source_paths:
        return None
    
    result = {}
    
    for key, value in source_paths.items():
        if value is None:
            continue
        
        # Handle list of paths
        if isinstance(value, list):
            info_list = []
            for p in value:
                info = resolve_and_build_info(p)
                if info:
                    info_list.append(info)
            if info_list:
                result[key] = info_list if len(info_list) > 1 else info_list[0]
        # Handle single path
        elif isinstance(value, str):
            info = resolve_and_build_info(value)
            if info:
                result[key] = info
    
    return result if result else None


def before_metadata_save_hook(configs, plugin_data=None, model_type=None, **kwargs):
    """
    Hook called before metadata is saved to output files.
    
    Adds 'source_images' key containing info about all input images used,
    with resolved original paths when possible.
    """
    if configs is None:
        return configs
    
    # Get source image paths from plugin_data (captured before validate_settings)
    source_paths = plugin_data.get('source_image_paths', {}) if plugin_data else {}
    
    # Process paths and resolve originals
    source_info = process_source_paths(source_paths)
    
    if source_info:
        configs['source_images'] = source_info
        print(f"[SourceImagesPlugin] Added source image info: {list(source_info.keys())}")
    
    return configs


class SourceImagesPlugin(WAN2GPPlugin):
    def __init__(self):
        super().__init__()
        self.name = "Source Images Metadata"
        self.version = "1.6.0"
        self.description = "Saves input image file paths in output metadata"
        
        # Request access to server_config and filename for saving
        self.request_global("server_config")
        self.request_global("server_config_filename")
        
        # Store instance for global access
        global _plugin_instance
        _plugin_instance = self

    def setup_ui(self):
        # Register the hook to intercept metadata before saving
        self.register_data_hook('before_metadata_save', before_metadata_save_hook)
        
        # Add configuration tab
        self.add_tab(
            tab_id="source_images_config",
            label="Source Images",
            component_constructor=self.create_config_ui,
            position=99  # Put near the end
        )
    
    def create_config_ui(self):
        """Create the configuration UI for managing search directories."""
        css = """
            .search-dirs-list {
                font-family: monospace;
                font-size: 13px;
                line-height: 1.8;
                padding: 10px;
                background-color: var(--background-fill-secondary);
                border-radius: 8px;
                max-height: 300px;
                overflow-y: auto;
            }
            .search-dirs-list .dir-item {
                padding: 5px 10px;
                margin: 2px 0;
                background-color: var(--background-fill-primary);
                border-radius: 4px;
                display: flex;
                justify-content: space-between;
                align-items: center;
            }
            .search-dirs-list .dir-item.auto {
                opacity: 0.7;
                font-style: italic;
            }
            .search-dirs-list .dir-path {
                word-break: break-all;
            }
            .search-dirs-list .dir-tag {
                font-size: 11px;
                padding: 2px 6px;
                border-radius: 3px;
                margin-left: 10px;
                white-space: nowrap;
            }
            .search-dirs-list .dir-tag.auto {
                background-color: var(--secondary-500);
                color: white;
            }
            .search-dirs-list .dir-tag.custom {
                background-color: var(--primary-500);
                color: white;
            }
        """
        
        with gr.Blocks() as config_blocks:
            gr.HTML(value=f"<style>{css}</style>")
            
            gr.Markdown("""
            ### Source Images Search Directories
            
            When you load images from the gallery, this plugin searches for the original files 
            in the directories listed below. Add custom directories if your source images are 
            stored elsewhere (e.g., external drives, network shares, or custom folders).
            """)
            
            with gr.Row():
                with gr.Column(scale=2):
                    self.dirs_display = gr.HTML(
                        value=self._render_dirs_list(),
                        elem_classes=["search-dirs-list"]
                    )
                
                with gr.Column(scale=1):
                    gr.Markdown("#### Add Custom Directory")
                    self.new_dir_input = gr.Textbox(
                        label="Directory Path",
                        placeholder="C:\\Path\\To\\Images or /path/to/images",
                        lines=1
                    )
                    self.add_dir_btn = gr.Button("Add Directory", variant="primary")
                    
                    gr.Markdown("#### Remove Custom Directory")
                    self.remove_dir_dropdown = gr.Dropdown(
                        label="Select directory to remove",
                        choices=self._get_custom_dirs_choices(),
                        interactive=True
                    )
                    self.remove_dir_btn = gr.Button("Remove Selected", variant="stop")
            
            # Event handlers
            self.add_dir_btn.click(
                fn=self._add_directory,
                inputs=[self.new_dir_input],
                outputs=[self.dirs_display, self.new_dir_input, self.remove_dir_dropdown]
            )
            
            self.remove_dir_btn.click(
                fn=self._remove_directory,
                inputs=[self.remove_dir_dropdown],
                outputs=[self.dirs_display, self.remove_dir_dropdown]
            )
        
        return config_blocks
    
    def _get_custom_dirs(self):
        """Get list of custom search directories from config."""
        if self.server_config:
            dirs = self.server_config.get(CONFIG_KEY_SEARCH_DIRS, [])
            return dirs if isinstance(dirs, list) else []
        return []
    
    def _get_custom_dirs_choices(self):
        """Get custom dirs as dropdown choices."""
        return self._get_custom_dirs()
    
    def _save_custom_dirs(self, dirs):
        """Save custom directories to server_config."""
        if self.server_config and self.server_config_filename:
            self.server_config[CONFIG_KEY_SEARCH_DIRS] = dirs
            try:
                with open(self.server_config_filename, "w", encoding="utf-8") as writer:
                    writer.write(json.dumps(self.server_config, indent=4))
            except Exception as e:
                print(f"[SourceImagesPlugin] Error saving config: {e}")
    
    def _render_dirs_list(self):
        """Render HTML for the directories list."""
        html = '<div class="search-dirs-list">'
        
        # Auto-detected directories
        auto_dirs = []
        if self.server_config:
            for key in ['save_path', 'image_save_path', 'audio_save_path']:
                path = self.server_config.get(key)
                if path and os.path.isdir(path) and path not in auto_dirs:
                    auto_dirs.append((path, key))
        
        # Default outputs
        plugin_dir = os.path.dirname(os.path.abspath(__file__))
        root_dir = os.path.dirname(os.path.dirname(plugin_dir))
        default_outputs = os.path.join(root_dir, 'outputs')
        if os.path.isdir(default_outputs):
            already_listed = any(d[0] == default_outputs for d in auto_dirs)
            if not already_listed:
                auto_dirs.append((default_outputs, 'default'))
        
        if auto_dirs:
            html += '<div style="margin-bottom: 10px; font-weight: bold; color: var(--body-text-color-subdued);">Auto-detected directories:</div>'
            for path, source in auto_dirs:
                html += f'''
                <div class="dir-item auto">
                    <span class="dir-path">{path}</span>
                    <span class="dir-tag auto">{source}</span>
                </div>
                '''
        
        # Custom directories
        custom_dirs = self._get_custom_dirs()
        if custom_dirs:
            html += '<div style="margin: 15px 0 10px 0; font-weight: bold; color: var(--body-text-color-subdued);">Custom directories:</div>'
            for path in custom_dirs:
                exists = os.path.isdir(path)
                status = "✓" if exists else "⚠️ Not found"
                html += f'''
                <div class="dir-item">
                    <span class="dir-path">{path} {'' if exists else '<span style="color: orange;">(' + status + ')</span>'}</span>
                    <span class="dir-tag custom">custom</span>
                </div>
                '''
        
        if not auto_dirs and not custom_dirs:
            html += '<div style="color: var(--body-text-color-subdued); text-align: center; padding: 20px;">No directories configured</div>'
        
        html += '</div>'
        return html
    
    def _add_directory(self, new_dir):
        """Add a new custom directory."""
        new_dir = new_dir.strip() if new_dir else ""
        
        if not new_dir:
            gr.Warning("Please enter a directory path.")
            return self._render_dirs_list(), "", self._get_custom_dirs_choices()
        
        # Normalize path
        new_dir = os.path.abspath(new_dir)
        
        if not os.path.isdir(new_dir):
            gr.Warning(f"Directory does not exist: {new_dir}")
            return self._render_dirs_list(), new_dir, self._get_custom_dirs_choices()
        
        custom_dirs = self._get_custom_dirs()
        
        if new_dir in custom_dirs:
            gr.Info("Directory already in the list.")
            return self._render_dirs_list(), "", self._get_custom_dirs_choices()
        
        custom_dirs.append(new_dir)
        self._save_custom_dirs(custom_dirs)
        
        gr.Info(f"Added directory: {new_dir}")
        return self._render_dirs_list(), "", self._get_custom_dirs_choices()
    
    def _remove_directory(self, dir_to_remove):
        """Remove a custom directory."""
        if not dir_to_remove:
            gr.Warning("Please select a directory to remove.")
            return self._render_dirs_list(), self._get_custom_dirs_choices()
        
        custom_dirs = self._get_custom_dirs()
        
        if dir_to_remove in custom_dirs:
            custom_dirs.remove(dir_to_remove)
            self._save_custom_dirs(custom_dirs)
            gr.Info(f"Removed directory: {dir_to_remove}")
        
        return self._render_dirs_list(), gr.Dropdown(choices=self._get_custom_dirs_choices(), value=None)

    def get_allowed_paths(self):
        """Return custom search directories to add to Gradio's allowed_paths.
        
        This enables Gradio to serve files from user-configured directories,
        allowing images from custom locations to be loaded into the UI.
        """
        return self._get_custom_dirs()
