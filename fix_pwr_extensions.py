#!/usr/bin/env python3
"""
Helper script to fix PWR tab files that have incorrect extensions.

This script scans for files matching the pattern *_PWR_*.* (with any extension except .ptb) 
and renames them to .ptb extension. It also updates any corresponding JSON files to reflect 
the new file paths.
"""

import os
import re
import json
import argparse
import hashlib
from pathlib import Path


def find_pwr_files_wrong_extension(directory):
    """
    Find all files that match the pattern *_PWR_*.* but don't have .ptb extension
    
    Args:
        directory (str): Directory to search in
    
    Returns:
        list: List of file paths that match the PWR pattern with non-.ptb extensions
    """
    pwr_files = []
    
    # Pattern to match: <name>_PWR_<id>.<any_extension_except_ptb>
    pwr_pattern = re.compile(r'^(.+)_PWR_(\d+)\.(?!ptb$)[^.]+$', re.IGNORECASE)
    
    for root, dirs, files in os.walk(directory):
        for filename in files:
            if pwr_pattern.match(filename):
                filepath = os.path.join(root, filename)
                pwr_files.append(filepath)
    
    return pwr_files


def calculate_md5(filepath):
    """
    Calculate MD5 hash of a file
    
    Args:
        filepath (str): Path to the file
    
    Returns:
        str: MD5 hash of the file, or None if error
    """
    try:
        hash_md5 = hashlib.md5()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
    except Exception as e:
        print(f"  Error calculating MD5 for {filepath}: {e}")
        return None


def rename_pwr_file(old_filepath, destructive=False):
    """
    Rename a PWR file from any extension to .ptb extension
    
    Args:
        old_filepath (str): Original file path with non-.ptb extension
        destructive (bool): Enable destructive operations (delete files when needed)
    
    Returns:
        tuple: (new_filepath, action_taken) where action_taken is one of:
               'renamed', 'removed_duplicate', 'deleted_both', 'exists_skip', 'error'
    """
    try:
        # Change extension to .ptb (replace whatever extension it currently has)
        base_path = os.path.splitext(old_filepath)[0]
        new_filepath = base_path + '.ptb'
        
        # Check if target file already exists
        if os.path.exists(new_filepath):
            if not destructive:
                print(f"  Warning: Target file already exists: {os.path.basename(new_filepath)}")
                print(f"  Use --destructive flag to enable MD5 comparison and handling")
                return None, 'exists_skip'
            
            # Calculate MD5 of both files
            print(f"  Target file exists: {os.path.basename(new_filepath)}")
            print(f"  Calculating MD5 checksums...")
            
            old_md5 = calculate_md5(old_filepath)
            new_md5 = calculate_md5(new_filepath)
            
            if old_md5 is None or new_md5 is None:
                print(f"  Error: Could not calculate MD5 checksums")
                return None, 'error'
            
            print(f"  Old file MD5: {old_md5}")
            print(f"  Target file MD5: {new_md5}")
            
            if old_md5 == new_md5:
                # Files are identical - remove the bad extension file
                print(f"  Files are identical - removing duplicate with bad extension")
                os.remove(old_filepath)
                print(f"  Removed: {os.path.basename(old_filepath)}")
                return new_filepath, 'removed_duplicate'
            else:
                # Files differ - delete both so they can be redownloaded
                print(f"  Files differ - deleting both to allow redownload")
                os.remove(old_filepath)
                os.remove(new_filepath)
                print(f"  Deleted: {os.path.basename(old_filepath)}")
                print(f"  Deleted: {os.path.basename(new_filepath)}")
                return None, 'deleted_both'
        
        # Target doesn't exist - simple rename
        os.rename(old_filepath, new_filepath)
        print(f"  Renamed: {os.path.basename(old_filepath)} -> {os.path.basename(new_filepath)}")
        
        return new_filepath, 'renamed'
        
    except Exception as e:
        print(f"  Error processing {old_filepath}: {e}")
        return None, 'error'


def update_json_file_paths(directory, old_filepath, new_filepath, action_taken):
    """
    Update any JSON files that reference the old file path
    
    Args:
        directory (str): Directory to search for JSON files
        old_filepath (str): Old file path to replace
        new_filepath (str): New file path to use (can be None if both files were deleted)
        action_taken (str): Action that was taken ('renamed', 'removed_duplicate', 'deleted_both', etc.)
    
    Returns:
        int: Number of JSON files updated
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
        # Pattern: <name>_PWR_<id>.<any_extension>
        id_match = re.search(r'_PWR_(\d+)\.[^.]+$', tab_filename, re.IGNORECASE)
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
                    if action_taken == 'deleted_both':
                        # Both files were deleted - remove the file_path reference
                        del tab_data['file_path']
                        updated = True
                        print(f"    Removed JSON file reference in {json_filename} (both files deleted)")
                        print(f"      Removed path: {stored_path}")
                    elif action_taken in ['renamed', 'removed_duplicate'] and new_filepath:
                        # File was renamed or duplicate removed - update the path
                        new_basename = os.path.basename(new_filepath)
                        updated_path = os.path.join(os.path.dirname(stored_path), new_basename)
                        tab_data['file_path'] = updated_path
                        
                        updated = True
                        action_desc = "Updated" if action_taken == 'renamed' else "Kept existing"
                        print(f"    {action_desc} JSON reference in {json_filename}")
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
    parser = argparse.ArgumentParser(description='Fix PWR tab files that have incorrect extensions (any extension except .ptb)')
    parser.add_argument('directory', help='Directory to search for PWR files (searches recursively)')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be renamed without actually renaming files')
    parser.add_argument('--update-json', action='store_true', default=True, help='Update JSON files that reference the old file paths (default: True)')
    parser.add_argument('--no-update-json', dest='update_json', action='store_false', help='Skip updating JSON files')
    parser.add_argument('--destructive', action='store_true', help='Enable destructive operations: compare MD5 when target exists, delete files if they differ')
    
    args = parser.parse_args()
    
    if not os.path.exists(args.directory):
        print(f"Error: Directory does not exist: {args.directory}")
        return 1
    
    print(f"Searching for PWR files with non-.ptb extensions in: {args.directory}")
    
    # Find all PWR files with non-.ptb extensions
    pwr_files = find_pwr_files_wrong_extension(args.directory)
    
    if not pwr_files:
        print("No PWR files with incorrect extensions found.")
        return 0
    
    print(f"Found {len(pwr_files)} PWR files with non-.ptb extensions:")
    
    # Initialize counters for different actions
    renamed_files = 0
    removed_duplicates = 0
    deleted_both_count = 0
    skipped_existing = 0
    errors = 0
    json_files_updated = 0
    
    for old_filepath in pwr_files:
        rel_path = os.path.relpath(old_filepath, args.directory)
        print(f"\nProcessing: {rel_path}")
        
        if args.dry_run:
            base_path = os.path.splitext(old_filepath)[0]
            new_filepath = base_path + '.ptb'
            
            if os.path.exists(new_filepath):
                if args.destructive:
                    old_md5 = calculate_md5(old_filepath)
                    new_md5 = calculate_md5(new_filepath)
                    if old_md5 and new_md5:
                        if old_md5 == new_md5:
                            print(f"  Would remove duplicate (identical MD5): {os.path.basename(old_filepath)}")
                        else:
                            print(f"  Would delete both files (different MD5) to allow redownload")
                    else:
                        print(f"  Would skip (could not calculate MD5)")
                else:
                    print(f"  Would skip (target exists, use --destructive for MD5 comparison)")
            else:
                new_rel_path = os.path.relpath(new_filepath, args.directory)
                print(f"  Would rename to: {new_rel_path}")
        else:
            # Actually process the file
            new_filepath, action_taken = rename_pwr_file(old_filepath, args.destructive)
            
            # Update counters based on action taken
            if action_taken == 'renamed':
                renamed_files += 1
            elif action_taken == 'removed_duplicate':
                removed_duplicates += 1
            elif action_taken == 'deleted_both':
                deleted_both_count += 1
            elif action_taken == 'exists_skip':
                skipped_existing += 1
            elif action_taken == 'error':
                errors += 1
            
            # Update JSON files if requested and applicable
            if args.update_json and action_taken in ['renamed', 'removed_duplicate', 'deleted_both']:
                json_updated = update_json_file_paths(args.directory, old_filepath, new_filepath, action_taken)
                json_files_updated += json_updated
    
    print(f"\nSummary:")
    if args.dry_run:
        print(f"  Would process {len(pwr_files)} PWR files")
        if args.destructive:
            print(f"  (MD5 comparison enabled for duplicate handling)")
    else:
        print(f"  Files renamed: {renamed_files}")
        print(f"  Duplicates removed: {removed_duplicates}")
        print(f"  Both files deleted: {deleted_both_count}")
        print(f"  Skipped (target exists): {skipped_existing}")
        print(f"  Errors: {errors}")
        if args.update_json:
            print(f"  JSON files updated: {json_files_updated}")
        
        total_processed = renamed_files + removed_duplicates + deleted_both_count + skipped_existing
        print(f"  Total processed: {total_processed} out of {len(pwr_files)} files")
    
    return 0


if __name__ == '__main__':
    exit(main())
