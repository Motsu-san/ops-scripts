#!/bin/bash

# 下記リストファイルをロードして自動実行する
# launchctl load Library/LaunchAgents/com.auto_xavc2h264.usbconnect.plist
# 以前はStartOnMountの影響で別のマウント(NAS接続等)でも実行されていたが，
# plist側でStartOnMountを削除し，下記のUSB判定ガードも追加したため再度有効化した

cd $(dirname $0)
current_dir=$(pwd)

# 対象のUSBボリュームが実際にマウントされ，かつUSB接続であることを確認する
# (NAS等のネットワークボリュームはdiskutilが管理しないため，ここで除外される)
target_volume="/Volumes/Untitled"
if [ ! -d "$target_volume" ] || ! diskutil info "$target_volume" 2>/dev/null | grep -q "Protocol:.*USB"; then
    echo "Target USB volume not found or not a USB device. Exiting."
    exit 0
fi

# ロックファイルのパス
lock_file="$(basename "$0").lock"
# ロックファイルが存在すれば終了
if [ -e "$lock_file" ]; then
    echo "Another instance is running. Exiting."
    exit 1
fi
# ロックファイルを作成
touch "$lock_file"

# スクリプト終了時にロックファイルを削除
trap "rm -f $lock_file" EXIT

# ログファイルのパス
log_file="$current_dir/xavc_import.log"
backup_dir="$current_dir/log_backup"  # ログのバックアップディレクトリ
max_size=1048576  # 最大ログサイズ（バイト単位、ここでは1MB）
max_backups=5      # 保存する最大バックアップ数

# バックアップディレクトリを作成（存在しない場合）
mkdir -p "$backup_dir"

# ログファイルのサイズを取得
log_size=$(stat -c %s "$log_file" 2>/dev/null || echo 0)

# ログファイルが最大サイズを超えた場合
if [ "$log_size" -ge "$max_size" ]; then
  echo "Rotating log file: $log_file"

  # 古いバックアップを削除（最大バックアップ数を超える場合）
  if [ -e "$backup_dir/logfile.log.$max_backups" ]; then
    rm -f "$backup_dir/logfile.log.$max_backups"
  fi

  # バックアップを1つずつスライド（例: logfile.log.3 -> logfile.log.4）
  for ((i=max_backups; i>1; i--)); do
    if [ -e "$backup_dir/logfile.log.$((i-1))" ]; then
      mv "$backup_dir/logfile.log.$((i-1))" "$backup_dir/logfile.log.$i"
    fi
  done

  # 現在のログファイルをバックアップディレクトリに移動
  mv "$log_file" "$backup_dir/logfile.log.1"

  # 新しいログファイルを作成
  : > "$log_file"  # 空のファイルを作成
  echo "Log file rotated and new log file created."
fi

echo "============================================= $(date)" >> "$log_file"
echo "No other instance is running. Proceeding with the script."

# 他のスクリプトを実行し、ログに出力をリダイレクト
# bash convert_and_upload.sh 2>&1 | tee -a "$log_file"
caffeinate -i bash convert_and_upload.sh 2>&1 | tee -a "$log_file"

# 実行完了のメッセージをログに記録
echo "Finished convert_and_upload.sh" >> "$log_file"
