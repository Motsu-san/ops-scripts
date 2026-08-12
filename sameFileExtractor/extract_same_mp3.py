#!/usr/bin/env python3
"""
extract_same_mp3.py
指定フォルダ内の .mp3 / .m4a ファイルを再帰的に検索し，
同じ曲名（title タグ）とアルバム名（album タグ）のファイルを抽出して
最も新しいファイル以外を指定フォルダにフォルダ構造を保って移動する

依存: ffprobe (ffmpeg に同梱)
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from collections import defaultdict
from datetime import datetime

# ANSI カラー
RED    = '\033[0;31m'
GREEN  = '\033[0;32m'
YELLOW = '\033[1;33m'
BLUE   = '\033[0;34m'
CYAN   = '\033[0;36m'
NC     = '\033[0m'


def cprint(color, msg):
    print(f"{color}{msg}{NC}")


def check_ffprobe():
    result = subprocess.run(['which', 'ffprobe'], capture_output=True)
    if result.returncode != 0:
        cprint(RED, "Error: ffprobe が見つかりません。ffmpeg をインストールしてください。")
        cprint(RED, "  brew install ffmpeg")
        sys.exit(1)


def get_audio_tags(filepath):
    """ffprobe で title / album タグを取得。失敗時は (None, None) を返す"""
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', filepath],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0:
            return None, None
        data = json.loads(result.stdout)
        tags = data.get('format', {}).get('tags', {})
        title = ''
        album = ''
        for k, v in tags.items():
            if k.lower() == 'title':
                title = v.strip()
            elif k.lower() == 'album':
                album = v.strip()
        return title, album
    except Exception:
        return None, None


AUDIO_EXTENSIONS = ('.mp3', '.m4a')

def find_audio_files(folders):
    """指定フォルダ以下の .mp3 / .m4a ファイルを再帰的に収集"""
    files = []
    for folder in folders:
        folder = os.path.abspath(folder)
        for root, dirs, filenames in os.walk(folder):
            dirs.sort()
            for filename in sorted(filenames):
                if filename.lower().endswith(AUDIO_EXTENSIONS):
                    files.append(os.path.join(root, filename))
    return files


def make_dest_path(filepath, search_folders, output_dir):
    """移動先パスを生成（検索フォルダ名を保持したフォルダ構造）"""
    abs_path = os.path.abspath(filepath)
    for folder in search_folders:
        folder_abs = os.path.abspath(folder)
        if abs_path.startswith(folder_abs + os.sep) or abs_path == folder_abs:
            folder_name = os.path.basename(folder_abs)
            rel = os.path.relpath(abs_path, folder_abs)
            return os.path.join(output_dir, folder_name, rel)
    # フォルダ配下にない場合はファイル名のみ
    return os.path.join(output_dir, os.path.basename(abs_path))


def main():
    parser = argparse.ArgumentParser(
        description='同じ曲名・アルバム名の .mp3 / .m4a ファイルを抽出し，古いファイルを移動する',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
例:
  %(prog)s ./musicA ./musicB
  %(prog)s -o ./duplicates ./musicA ./musicB
  %(prog)s -d ./musicA ./musicB
  %(prog)s --skip-no-tags ./musicA ./musicB
        """
    )
    parser.add_argument('folders', nargs='+', help='検索対象フォルダ（複数指定可）')
    parser.add_argument('-o', '--output',
                        help='移動先フォルダ (デフォルト: 最初のフォルダの親/duplicates_YYYYMMDD_HHMMSS)')
    parser.add_argument('-d', '--dry-run', action='store_true',
                        help='ドライラン: 実際には移動しない')
    parser.add_argument('--skip-no-tags', action='store_true',
                        help='title または album タグが空のファイルを重複判定から除外')

    args = parser.parse_args()

    check_ffprobe()

    # フォルダのバリデーション
    for folder in args.folders:
        if not os.path.isdir(folder):
            cprint(RED, f"Error: '{folder}' はディレクトリではありません")
            sys.exit(1)

    # 移動先フォルダを決定
    if args.output:
        output_dir = os.path.abspath(args.output)
    else:
        parent = os.path.dirname(os.path.abspath(args.folders[0]))
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_dir = os.path.join(parent, f'duplicates_{timestamp}')

    # ヘッダー表示
    print()
    cprint(BLUE, '=' * 54)
    cprint(BLUE, '   同名音楽ファイル抽出・移動スクリプト (MP3 / M4A)')
    cprint(BLUE, '=' * 54)
    print()
    print('検索フォルダ:')
    for f in args.folders:
        print(f'  {CYAN}{os.path.abspath(f)}{NC}')
    print(f'移動先フォルダ: {CYAN}{output_dir}{NC}')
    if args.dry_run:
        print()
        cprint(YELLOW, '[ドライラン] 実際の移動は行いません')
    print()

    # ---- 音楽ファイル収集 ----
    print('音楽ファイルを検索中... (.mp3 / .m4a)')
    audio_files = find_audio_files(args.folders)
    print(f'  {len(audio_files)} ファイルが見つかりました')
    print()

    if not audio_files:
        cprint(YELLOW, '対象ファイルがありません。終了します。')
        return

    # ---- タグ読み取りとグルーピング ----
    print('タグを読み取り中...')
    groups   = defaultdict(list)  # (title_lower, album_lower) -> [(path, title, album, mtime)]
    no_tag   = []
    err_files = []

    for i, filepath in enumerate(audio_files):
        print(f'\r  {i + 1}/{len(audio_files)} 処理中... ', end='', flush=True)
        title, album = get_audio_tags(filepath)

        if title is None:
            err_files.append(filepath)
            continue

        if args.skip_no_tags and (not title or not album):
            no_tag.append(filepath)
            continue

        mtime = os.path.getmtime(filepath)
        key = (title.lower(), album.lower())
        groups[key].append((filepath, title, album, mtime))

    print(f'\r  タグ読み取り完了 ({len(audio_files)} ファイル)      ')

    if err_files:
        print()
        cprint(YELLOW, f'  警告: タグ読み取り失敗 {len(err_files)} ファイル')
        for f in err_files:
            print(f'    {f}')

    if no_tag and args.skip_no_tags:
        print()
        cprint(YELLOW, f'  スキップ (タグ未設定): {len(no_tag)} ファイル')

    print()

    # ---- 重複グループを抽出 ----
    duplicate_groups = {k: v for k, v in groups.items() if len(v) > 1}

    if not duplicate_groups:
        cprint(GREEN, '重複するファイルは見つかりませんでした。')
        return

    cprint(YELLOW, f'{len(duplicate_groups)} グループの重複が見つかりました')
    print()

    total_move = 0

    for _key, files in sorted(duplicate_groups.items(),
                              key=lambda x: (x[0][0], x[0][1])):
        # 代表タグ（最初のファイルから取得）
        _, title_disp, album_disp, _ = files[0]

        cprint(YELLOW, f'[重複]  曲名: "{title_disp}"  /  アルバム: "{album_disp}"')

        # 更新日時で降順ソート（先頭が最新）
        files_sorted = sorted(files, key=lambda x: x[3], reverse=True)

        for i, (filepath, title, album, mtime) in enumerate(files_sorted):
            dt = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')
            if i == 0:
                print(f'  {GREEN}[保持]{NC} ({dt})  {filepath}')
            else:
                dest = make_dest_path(filepath, args.folders, output_dir)
                print(f'  {RED}[移動]{NC} ({dt})  {filepath}')
                print(f'         -> {dest}')

                if not args.dry_run:
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    shutil.move(filepath, dest)

                total_move += 1
        print()

    # ---- サマリー ----
    cprint(BLUE, '=' * 54)
    cprint(GREEN, '処理完了')
    print(f'重複グループ数 : {len(duplicate_groups)}')
    print(f'移動ファイル数 : {total_move}')

    if total_move > 0 and not args.dry_run:
        print()
        print(f'移動先: {CYAN}{output_dir}{NC}')

    if args.dry_run:
        print()
        cprint(YELLOW, '[ドライラン] 実際の移動は行われていません')


if __name__ == '__main__':
    main()
