#!/usr/bin/env python3
"""syncMyDictionary.sh のPython版。

Google DriveでマウントされたクラウドストレージとローカルのIME(Google日本語入力/Mozc)の
ユーザー辞書(user_dictionary.db)を、更新日時が新しい方に合わせて同期する。
macOS/Windows11/Ubuntu 22.04で動作する想定。

注意: user_dictionary.dbは独自バイナリ形式であり、Google日本語入力(Win/Mac)と
Mozc(Linux)間でのファイル互換性はGoogleの公式保証ではない。実運用前に
辞書のエクスポート機能で定期バックアップを取ることを推奨する。

クラウド側のGoogle Driveルート(「My Drive」フォルダの親)の場所はOS/環境依存のため、
自動検出できない場合は環境変数 SYNC_MY_DICTIONARY_CLOUD_ROOT で明示する:
  - macOS: 通常は自動検出される(~/Library/CloudStorage/GoogleDrive-*)
  - Windows: Google Drive for desktopのドライブレター(例: G:\\)
  - Ubuntu: rcloneのマウント先(例: ~/GoogleDrive)

ローカル側の辞書パスも SYNC_MY_DICTIONARY_LOCAL_TARGET で上書きできる
(Mozcのプロファイルディレクトリをカスタマイズしている場合など)。
"""
import argparse
import glob
import os
import platform
import shutil
import string
import sys

CLOUD_RELATIVE_PATH = os.path.join("My Drive", "dictionary", "JapaneseInput", "user_dictionary.db")


def find_cloud_root_macos():
    home = os.path.expanduser("~")
    pattern = os.path.join(home, "Library", "CloudStorage", "GoogleDrive-*")
    for path in sorted(glob.glob(pattern)):
        if os.path.isdir(path):
            return path
    return None


def find_cloud_root_windows():
    candidates = ["G"] + [c for c in string.ascii_uppercase if c != "G"]
    for letter in candidates:
        root = f"{letter}:\\"
        if os.path.isdir(os.path.join(root, "My Drive")):
            return root
    return None


def find_cloud_root_linux():
    home = os.path.expanduser("~")
    for name in ("GoogleDrive", "google-drive", "gdrive", "Google Drive"):
        root = os.path.join(home, name)
        if os.path.isdir(os.path.join(root, "My Drive")):
            return root
    return None


def get_cloud_root(override=None):
    if override:
        return override
    env_value = os.environ.get("SYNC_MY_DICTIONARY_CLOUD_ROOT")
    if env_value:
        return env_value

    system = platform.system()
    if system == "Darwin":
        return find_cloud_root_macos()
    if system == "Windows":
        return find_cloud_root_windows()
    if system == "Linux":
        return find_cloud_root_linux()
    return None


def get_local_target(override=None):
    if override:
        return override
    env_value = os.environ.get("SYNC_MY_DICTIONARY_LOCAL_TARGET")
    if env_value:
        return env_value

    system = platform.system()
    if system == "Darwin":
        return os.path.expanduser(
            "~/Library/Application Support/Google/JapaneseInput/user_dictionary.db"
        )
    if system == "Windows":
        local_low = os.path.expandvars(r"%USERPROFILE%\AppData\LocalLow")
        return os.path.join(local_low, "Google", "Google Japanese Input", "user_dictionary.db")
    if system == "Linux":
        return os.path.expanduser("~/.mozc/user_dictionary.db")
    return None


def sync_files(cloud_target, local_target, dry_run=False):
    if not os.path.exists(cloud_target):
        return

    if not os.path.exists(local_target) or os.path.getmtime(cloud_target) > os.path.getmtime(local_target):
        src, dst = cloud_target, local_target
    elif os.path.getmtime(local_target) > os.path.getmtime(cloud_target):
        src, dst = local_target, cloud_target
    else:
        return

    if dry_run:
        print(f"[dry-run] Would sync: {src} -> {dst}")
        return

    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)
    print(f"Synced: {src} -> {dst}")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Google日本語入力/Mozcのユーザー辞書をGoogle Drive経由で同期する",
    )
    parser.add_argument(
        "--cloud-root",
        help="Google Driveルートのパス(未指定時は環境変数SYNC_MY_DICTIONARY_CLOUD_ROOT、"
        "次いでOS別の自動検出を使用)",
    )
    parser.add_argument(
        "--local-target",
        help="ローカルのuser_dictionary.dbのパス(未指定時は環境変数"
        "SYNC_MY_DICTIONARY_LOCAL_TARGET、次いでOS別の既定パスを使用)",
    )
    parser.add_argument(
        "-d", "--dry-run",
        action="store_true",
        help="実際にはコピーせず、解決されたパスと同期方向のみ表示する",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    cloud_root = get_cloud_root(args.cloud_root)
    local_target = get_local_target(args.local_target)

    if not cloud_root:
        print(
            "Error: Google Driveのルートを検出できませんでした。"
            "環境変数 SYNC_MY_DICTIONARY_CLOUD_ROOT で明示してください。",
            file=sys.stderr,
        )
        sys.exit(1)
    if not local_target:
        print(
            "Error: 未対応のOSです。環境変数 SYNC_MY_DICTIONARY_LOCAL_TARGET で明示してください。",
            file=sys.stderr,
        )
        sys.exit(1)

    cloud_target = os.path.join(cloud_root, CLOUD_RELATIVE_PATH)

    try:
        sync_files(cloud_target, local_target, dry_run=args.dry_run)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
