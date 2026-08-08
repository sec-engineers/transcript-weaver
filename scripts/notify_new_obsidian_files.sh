#!/usr/bin/env bash

# Directory to check (files in subdirectories are not counted).
WATCH_DIRECTORY="$HOME/path/to/your/obsidian/files"

# Address that will receive the notification.
EMAIL_TO="fmerrow@gmail.com"

# Store regular files directly inside WATCH_DIRECTORY, including hidden files.
mapfile -d '' files < <(
    find "$WATCH_DIRECTORY" -mindepth 1 -maxdepth 1 -type f -print0
)

file_count=${#files[@]}

# No files means there is nothing to report.
if (( file_count == 0 )); then
    exit 0
fi

subject=$(printf 'You have %s New Obsidian files to process' "$file_count")

{
    printf 'To: %s\n' "$EMAIL_TO"
    printf 'Subject: %s\n' "$subject"
    printf '\n'
    printf '%s\n\n' "$subject"
    printf 'Files:\n'

    for file in "${files[@]}"; do
        printf '%s\n' "$(basename "$file")"
    done
} | msmtp "$EMAIL_TO"
