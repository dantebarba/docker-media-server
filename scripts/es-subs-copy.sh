#!/bin/sh

if [ -z "$1" ]; then
  echo "Error: directory parameter is required."
  exit 1  # Exit with a non-zero status to indicate failure
fi

# Base directory containing movie directories
TARGET_DIR=$1

# Iterate through each movie directory
for movie in "$TARGET_DIR"/*; do
    if [ -d "$movie" ]; then
        for sub in "$movie"/*.es-MX.srt; do
            # Change this line to ensure correct matching
            es_srt="${sub%.es-MX.srt}.es.srt"  # Use .es-MX.srt to match the original file
            if cp --no-clobber "$sub" "$es_srt"; then
                echo "Copied: $sub -> $es_srt"
            else
                echo "Skipped: $es_srt already exists"
            fi
        done
    fi
done
