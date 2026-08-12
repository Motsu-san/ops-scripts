#!/bin/sh
sync_target="/Users/motsu/Library/CloudStorage/GoogleDrive-j4507620@gmail.com/My Drive/dictionary/JapaneseInput/user_dictionary.db"
local_target="/Users/motsu/Library/Application Support/Google/JapaneseInput/user_dictionary.db"

if [ -e "$sync_target" ]; then
    rsync -u "$sync_target" "$local_target"
    rsync -u "$local_target" "$sync_target"
fi
