"""
Utility functions for working with source images metadata.

These helpers can be used by other plugins to locate and load source images
from the metadata stored by the Source Images plugin.

Key insight: When files are uploaded via browser, the original filesystem path
is NOT sent (browser security). Only the filename + content are sent. Gradio 
saves to temp preserving the filename. So we use the filename to find the 
original in the outputs folder.
"""

import os
import glob
from typing import Optional, Dict, Any, List, Union


def find_file_by_name(filename: str, search_dirs: List[str] = None, recursive: bool = True) -> Optional[str]:
    """
    Search for a file by name in output directories.
    
    WanGP outputs have unique filenames (timestamp + seed + prompt), so 
    searching by filename reliably finds the original.
    
    Args:
        filename: The filename to search for (basename only)
        search_dirs: List of directories to search. 
                     If None, falls back to default 'outputs' folder.
        recursive: Whether to search subdirectories
    
    Returns:
        Full path to the file if found, None otherwise
    """
    if not filename:
        return None
    
    # Get the root directory (where wgp.py is)
    plugin_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.dirname(os.path.dirname(plugin_dir))
    
    # Use provided search_dirs or fall back to default
    if not search_dirs:
        search_dirs = [os.path.join(root_dir, 'outputs')]
    
    # Search each directory
    for search_dir in search_dirs:
        if not os.path.isdir(search_dir):
            continue
        
        # Direct match in directory
        direct_path = os.path.join(search_dir, filename)
        if os.path.isfile(direct_path):
            return direct_path
        
        if recursive:
            # Recursive glob search
            pattern = os.path.join(search_dir, '**', filename)
            matches = glob.glob(pattern, recursive=True)
            if matches:
                # Return the most recently modified if multiple matches
                return max(matches, key=os.path.getmtime)
    
    return None


def resolve_source_image(source_info: Union[str, Dict[str, Any]], search_dirs: List[str] = None) -> Optional[str]:
    """
    Resolve a source image info to an actual file path.
    
    Handles both:
    - String paths (legacy format or direct paths)
    - Dict with 'path', 'filename', 'is_temp' keys (new format)
    
    For temp paths (browser uploads), searches outputs folder by filename.
    
    Args:
        source_info: Either a path string or a dict with path info
        search_dirs: Optional directories to search for the file
    
    Returns:
        Resolved file path if found, None otherwise
    """
    if not source_info:
        return None
    
    # Handle string (path directly)
    if isinstance(source_info, str):
        # Check if it's a temp path
        is_temp = 'gradio' in source_info.lower() and 'temp' in source_info.lower()
        
        if not is_temp and os.path.isfile(source_info):
            return source_info
        
        # Search by filename
        filename = os.path.basename(source_info)
        found = find_file_by_name(filename, search_dirs)
        if found:
            return found
        
        # If still not found but temp file exists, return temp path
        if os.path.isfile(source_info):
            return source_info
        
        return None
    
    # Handle dict format
    if isinstance(source_info, dict):
        path = source_info.get('path')
        filename = source_info.get('filename')
        is_temp = source_info.get('is_temp', False)
        
        # If not temp and path exists, use it directly
        if not is_temp and path and os.path.isfile(path):
            return path
        
        # Search by filename (works for temp files since filename is preserved)
        if filename:
            found = find_file_by_name(filename, search_dirs)
            if found:
                return found
        
        # Last resort: return the original path if it exists (temp still valid)
        if path and os.path.isfile(path):
            return path
    
    return None


def get_source_images_from_metadata(metadata: Dict[str, Any], search_dirs: List[str] = None) -> Dict[str, Union[str, List[str]]]:
    """
    Extract and resolve source images from output metadata.
    
    Args:
        metadata: The metadata dict from a WanGP output file
        search_dirs: Optional directories to search for files
    
    Returns:
        Dict mapping image keys to resolved file paths
    """
    source_images = metadata.get('source_images', {})
    if not source_images:
        return {}
    
    result = {}
    
    for key, value in source_images.items():
        if value is None:
            continue
        
        # Handle list of images
        if isinstance(value, list):
            resolved_list = []
            for item in value:
                resolved = resolve_source_image(item, search_dirs)
                if resolved:
                    resolved_list.append(resolved)
            if resolved_list:
                result[key] = resolved_list if len(resolved_list) > 1 else resolved_list[0]
        else:
            # Handle single image
            resolved = resolve_source_image(value, search_dirs)
            if resolved:
                result[key] = resolved
    
    return result


def load_source_image(source_info: Union[str, Dict[str, Any]], search_dirs: List[str] = None):
    """
    Load a source image as a PIL Image.
    
    Args:
        source_info: Either a path string or a dict with path info
        search_dirs: Optional directories to search for the file
    
    Returns:
        PIL Image if found and loaded, None otherwise
    """
    from PIL import Image
    
    path = resolve_source_image(source_info, search_dirs)
    if path and os.path.isfile(path):
        try:
            return Image.open(path)
        except Exception as e:
            print(f"[SourceImagesUtils] Error loading image {path}: {e}")
    
    return None
