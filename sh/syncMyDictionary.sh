#!/bin/sh
cloud_storage_dir=$(find "$HOME/Library/CloudStorage" -maxdepth 1 -type d -name 'GoogleDrive-*' -print -quit 2>/dev/null)
sync_target="$cloud_storage_dir/My Drive/dictionary/JapaneseInput/user_dictionary.db"
local_target="$HOME/Library/Application Support/Google/JapaneseInput/user_dictionary.db"

if [ -n "$cloud_storage_dir" ] && [ -e "$sync_target" ]; then
    rsync -u "$sync_target" "$local_target"
    rsync -u "$local_target" "$sync_target"
fi
