#!/usr/bin/env python3
"""
Helper script to fix PWR tab files that were incorrectly saved with .txt extension.

This script scans for files matching the pattern *_PWR_*.txt and renames them to .ptb extension.
It also updates any corresponding JSON files to reflect the new file paths.
"""

import os
import re
import json
import argparse
from pathlib import Path


def find_pwr_txt_files(directory):
    """
    Find all files that match the pattern *_PWR_*.txt
    
    Args:
        directory (str): Directory to search in
    
    Returns:
        list: List of file paths that match the PWR pattern with .txt extension
    """
    pwr_files = []
    
    # Pattern to match: <name>_PWR_<id>.txt
    pwr_pattern = re.compile(r'^(.+)_PWR_(\d+)\.txt$', re.IGNORECASE)
    
    for root, dirs, files in os.walk(directory):
        for filename in files:
            if pwr_pattern.match(filename):
                filepath = os.path.join(root, filename)
                pwr_files.append(filepath)
    
    return pwr_files


def rename_pwr_file(old_filepath):
    """
    Rename a PWR file from .txt to .ptb extension
    
    Args:
        old_filepath (str): Original file path with .txt extension
    
    Returns:
        str: New file path with .ptb extension, or None if rename failed
    """
    try:
        # Change extension from .txt to .ptb
        new_filepath = old_filepath.rsplit('.txt', 1)[0] + '.ptb'
        
        # Check if target file already exists
        if os.path.exists(new_filepath):
            print(f"  Warning: Target file already exists: {os.path.basename(new_filepath)}")
            return None
        
        # Rename the file
        os.rename(old_filepath, new_filepath)
        print(f"  Renamed: {os.path.basename(old_filepath)} -> {os.path.basename(new_filepath)}")
        
        return new_filepath
        
    except Exception as e:
        print(f"  Error renaming {old_filepath}: {e}")
        return None


def update_json_file_paths(directory, old_filepath, new_filepath):
    """
    Update any JSON files that reference the old file path
    
    Args:
        directory (str): Directory to search for JSON files
        old_filepath (str): Old file path to replace
        new_filepath (str): New file path to use
    """
    json_files_updated = 0
    
    # Extract band ID from the directory name containing the tab file
    tab_dir = os.path.dirname(old_filepath)
    band_dir_name = os.path.basename(tab_dir)
    
    # Pattern: <band_name>_<band_id>
    band_id_match = re.search(r'_(\d+)$', band_dir_name)
    if not band_id_match:
        print(f"    Warning: Could not extract band ID from directory name: {band_dir_name}")
        return 0
    
    band_id = band_id_match.group(1)
    
    # Look for the specific band JSON file
    json_filename = f"band_{band_id}.json"
    json_filepath = os.path.join(directory, json_filename)
    
    if not os.path.exists(json_filepath):
        print(f"    Warning: Band JSON file not found: {json_filename}")
        return 0
    
    try:
        # Read JSON file
        with open(json_filepath, 'r', encoding='utf-8') as f:
            band_data = json.load(f)
        
        # Extract tab ID from the old filepath filename
        tab_filename = os.path.basename(old_filepath)
        # Pattern: <name>_PWR_<id>.txt
        id_match = re.search(r'_PWR_(\d+)\.txt$', tab_filename, re.IGNORECASE)
        if not id_match:
            print(f"    Warning: Could not extract tab ID from filename: {tab_filename}")
            return 0
        
        tab_id = id_match.group(1)
        
        # Check if this specific tab references the old file path
        updated = False
        if 'tabs' in band_data and tab_id in band_data['tabs']:
            tab_data = band_data['tabs'][tab_id]
            if 'file_path' in tab_data:
                stored_path = tab_data['file_path']
                stored_basename = os.path.basename(stored_path)
                old_basename = os.path.basename(old_filepath)
                
                # Check if the basename matches (handles both absolute and relative paths)
                if stored_basename == old_basename:
                    # Update just the basename, keeping the directory structure
                    new_basename = os.path.basename(new_filepath)
                    updated_path = os.path.join(os.path.dirname(stored_path), new_basename)
                    tab_data['file_path'] = updated_path
                    
                    updated = True
                    print(f"    Updated JSON reference in {json_filename}")
                    print(f"      Old path: {stored_path}")
                    print(f"      New path: {updated_path}")
        
        # Write back if updated
        if updated:
            with open(json_filepath, 'w', encoding='utf-8') as f:
                json.dump(band_data, f, indent=2, ensure_ascii=False)
            json_files_updated = 1
            
    except Exception as e:
        print(f"    Warning: Error updating JSON file {json_filename}: {e}")
    
    return json_files_updated


def main():
    parser = argparse.ArgumentParser(description='Fix PWR tab files that were incorrectly saved with .txt extension')
    parser.add_argument('directory', help='Directory to search for PWR files (searches recursively)')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be renamed without actually renaming files')
    parser.add_argument('--update-json', action='store_true', default=True, help='Update JSON files that reference the old file paths (default: True)')
    parser.add_argument('--no-update-json', dest='update_json', action='store_false', help='Skip updating JSON files')
    
    args = parser.parse_args()
    
    if not os.path.exists(args.directory):
        print(f"Error: Directory does not exist: {args.directory}")
        return 1
    
    print(f"Searching for PWR files with .txt extension in: {args.directory}")
    
    # Find all PWR files with .txt extension
    pwr_files = find_pwr_txt_files(args.directory)
    
    if not pwr_files:
        print("No PWR files with .txt extension found.")
        return 0
    
    print(f"Found {len(pwr_files)} PWR files with .txt extension:")
    
    renamed_files = 0
    json_files_updated = 0
    
    for old_filepath in pwr_files:
        rel_path = os.path.relpath(old_filepath, args.directory)
        print(f"\nProcessing: {rel_path}")
        
        if args.dry_run:
            new_filepath = old_filepath.rsplit('.txt', 1)[0] + '.ptb'
            new_rel_path = os.path.relpath(new_filepath, args.directory)
            print(f"  Would rename to: {new_rel_path}")
        else:
            # Actually rename the file
            new_filepath = rename_pwr_file(old_filepath)
            
            if new_filepath:
                renamed_files += 1
                
                # Update JSON files if requested
                if args.update_json:
                    json_updated = update_json_file_paths(args.directory, old_filepath, new_filepath)
                    json_files_updated += json_updated
    
    print(f"\nSummary:")
    if args.dry_run:
        print(f"  Would rename {len(pwr_files)} PWR files from .txt to .ptb")
    else:
        print(f"  Successfully renamed {renamed_files} out of {len(pwr_files)} PWR files")
        if args.update_json:
            print(f"  Updated {json_files_updated} JSON files with new file paths")
    
    return 0


if __name__ == '__main__':
    exit(main())
