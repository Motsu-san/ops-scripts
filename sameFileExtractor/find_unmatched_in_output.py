#!/usr/bin/env python3
"""
find_unmatched_in_output.py
extract_aiff_matches.py で移動した先のフォルダ（移動先）を対象に、
AIFF フォルダのタグと再照合し、どの AIFF タグとも一致しない
mp3 / m4a ファイルを検出する（＝不明な経緯で移動された疑いのあるファイル）。
判定条件: 曲名・アルバムは部分一致、artist または album_artist のどちらかが完全一致、
track・disc はそれぞれ完全一致
（AIFF側にタグが無い項目は判定不能としてスキップする）。

デフォルトでは移動は行わず、一覧表示とログ出力のみ。
--move-to を指定すると、不一致ファイルを指定フォルダへ退避できる。

依存: ffprobe (ffmpeg に同梱)
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import unicodedata
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


def get_tags(filepath):
    """ffprobe で title / album / artist / album_artist / track / disc タグを取得。
    失敗時は (None, None, None, None, None, None) を返す"""
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', filepath],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0:
            return None, None, None, None, None, None
        data = json.loads(result.stdout)
        tags = data.get('format', {}).get('tags', {})
        title = ''
        album = ''
        artist = ''
        album_artist = ''
        track = ''
        disc = ''
        for k, v in tags.items():
            kl = k.lower()
            if kl == 'title':
                title = v.strip()
            elif kl == 'album':
                album = v.strip()
            elif kl == 'artist':
                artist = v.strip()
            elif kl == 'album_artist':
                album_artist = v.strip()
            elif kl == 'track':
                track = v.strip()
            elif kl == 'disc':
                disc = v.strip()
        return title, album, artist, album_artist, track, disc
    except Exception:
        return None, None, None, None, None, None


CACHE_FILENAME = '.tags_cache.json'


def load_tag_cache(folder):
    """指定フォルダ内のタグキャッシュ(.tags_cache.json)を読み込む。無ければ空dict"""
    try:
        with open(os.path.join(folder, CACHE_FILENAME), encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def save_tag_cache(folder, cache):
    """指定フォルダ内にタグキャッシュを保存する。書き込みに失敗しても処理は継続する"""
    try:
        with open(os.path.join(folder, CACHE_FILENAME), 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False)
    except Exception:
        pass


def file_fingerprint(filepath):
    """mtime + サイズ からファイル変更検知用のフィンガープリントを作る。
    処理中にファイルが削除されるなどして stat に失敗した場合は None を返す
    （呼び出し側はキャッシュ不一致 → get_tags 失敗 のパスで通常のタグ読み取りエラーとして扱う）"""
    try:
        st = os.stat(filepath)
    except OSError:
        return None
    return f'{st.st_mtime_ns}:{st.st_size}'


def find_files(folder, extensions):
    """指定フォルダ以下の対象拡張子ファイルを再帰的に収集（AppleDouble の ._ ファイルは除外）"""
    files = []
    folder = os.path.abspath(folder)
    for root, dirs, filenames in os.walk(folder):
        dirs.sort()
        for filename in sorted(filenames):
            if filename.startswith('._'):
                continue
            if filename.lower().endswith(extensions):
                files.append(os.path.join(root, filename))
    return files


MIN_MATCH_LEN   = 3     # 部分一致に使う文字列の最小文字数
MIN_MATCH_RATIO = 0.4   # 部分一致とみなす最小の長さ比率（短い方 / 長い方）

BRACKETS_RE = re.compile(r'[()\[\]{}<>「」『』【】〔〕｛｝〈〉]')


def normalize(s):
    """比較用に正規化:
    - NFKC正規化で全角/半角の違いを吸収（例: "Ｅ．Ｐ．" -> "E.P."）
    - 大文字小文字を無視
    - 括弧の種類（()・[]・【】など）の違いを無視するため括弧文字自体を除去
    - 空白（全角含む）を除去
    例: "Love & DISCO E. P." と "Love&DISCO E.P." / "山崎 まさよし" と "山崎まさよし" /
        "(Remastered)" と "[Remastered]" を同一視する"""
    s = unicodedata.normalize('NFKC', s).lower().strip()
    s = BRACKETS_RE.sub('', s)
    return re.sub(r'\s+', '', s)


def partial_match(a, b):
    """どちらかが他方に含まれれば一致（大文字小文字・空白・括弧種別の違いを無視）。
    どちらかが空、または正規化後 MIN_MATCH_LEN 未満の場合は完全一致のみ。
    部分一致の場合も、短い方が長い方の MIN_MATCH_RATIO 未満しか占めない場合は
    "you" のようなありふれた単語による誤マッチとみなし不一致とする"""
    a, b = normalize(a), normalize(b)
    if not a or not b:
        return False
    if len(a) < MIN_MATCH_LEN or len(b) < MIN_MATCH_LEN:
        return a == b
    if a not in b and b not in a:
        return False
    shorter_len, longer_len = sorted((len(a), len(b)))
    return shorter_len / longer_len >= MIN_MATCH_RATIO


def artist_match(artist, album_artist, aiff_artist, aiff_album_artist):
    """artist または album_artist のどちらかが完全一致すれば一致（大文字小文字・空白の違いを無視）。
    AIFF 側に artist・album_artist が両方とも無い場合は判定不能として一致扱い（title/albumのみで判定）"""
    aiff_artist = normalize(aiff_artist)
    aiff_album_artist = normalize(aiff_album_artist)
    if not aiff_artist and not aiff_album_artist:
        return True
    if aiff_artist and normalize(artist) == aiff_artist:
        return True
    if aiff_album_artist and normalize(album_artist) == aiff_album_artist:
        return True
    return False


def parse_num(s):
    """"8" や "1/19" のようなタグ値から先頭の数値部分だけを取り出す（先頭ゼロは無視）"""
    m = re.match(r'\s*0*(\d+)', s)
    return m.group(1) if m else ''


def num_match(value, aiff_value):
    """track / disc 用: AIFF側に値が無ければ判定不能として一致扱い。
    あれば数値部分を完全一致で比較する"""
    aiff_value = parse_num(aiff_value)
    if not aiff_value:
        return True
    return parse_num(value) == aiff_value


def parse_disc_total(s):
    """"1/1" のようなタグ値から総枚数部分（分母）だけを取り出す。無ければ None"""
    m = re.match(r'\s*\d+\s*/\s*0*(\d+)', s)
    return m.group(1) if m else None


def normalize_disc(s):
    """discタグを比較用に正規化する。
    値が空、総数1枚（"1/1"など。ほとんどのCDは1枚組のため）、
    または位置が0（disc番号は1始まりのため、0は古いツールが書き込む「未設定」の意味と考えられる）
    の場合は「意味のある情報なし」とみなして空文字列を返す。それ以外は先頭の数値（disc位置）を返す"""
    if not s or parse_disc_total(s) == '1':
        return ''
    pos = parse_num(s)
    return '' if pos == '0' else pos


def disc_match(value, aiff_value):
    """disc用: "1/1"（総数1枚）や値が空の場合はどちらも「意味のある情報なし」として
    同一視する。それ以外は disc位置が完全一致する場合のみ一致とする
    （どちらか一方だけが意味のある情報を持つ場合は不一致とする）"""
    return normalize_disc(value) == normalize_disc(aiff_value)


def classify_mismatch(title, album, artist, album_artist, track, disc, aiff_keys):
    """不一致の理由を段階的に判定する。
    戻り値は (matched: bool, reason: str)。matched が True の場合 reason は空文字。
    どの段階で弾かれたか（候補なし／artist不一致／track・disc不一致）を具体的に示す"""
    title_album_candidates = [
        k for k in aiff_keys
        if partial_match(title, k[0]) and partial_match(album, k[1])
    ]
    if not title_album_candidates:
        return False, 'タイトル/アルバムが一致するAIFFが見つかりません'

    artist_ok_candidates = [
        k for k in title_album_candidates
        if artist_match(artist, album_artist, k[2], k[3])
    ]
    if not artist_ok_candidates:
        aiff_variants = sorted({f'artist="{k[2]}" album_artist="{k[3]}"' for k in title_album_candidates})
        return False, (f'アーティスト不一致: mp3側 artist="{artist}" album_artist="{album_artist}" '
                        f'/ AIFF候補: {" | ".join(aiff_variants)}')

    track_disc_ok_candidates = [
        k for k in artist_ok_candidates
        if num_match(track, k[4]) and disc_match(disc, k[5])
    ]
    if not track_disc_ok_candidates:
        aiff_variants = sorted({f'track="{k[4]}" disc="{k[5]}"' for k in artist_ok_candidates})
        return False, (f'track/disc不一致: mp3側 track="{track}" disc="{disc}" '
                        f'/ AIFF候補: {" | ".join(aiff_variants)}')

    return True, ''


def make_dest_path(filepath, base_folder, output_dir):
    """移動先パスを生成（直上2階層のフォルダ構造を維持）"""
    abs_path   = os.path.abspath(filepath)
    folder_abs = os.path.abspath(base_folder)
    filename   = os.path.basename(abs_path)
    parent     = os.path.dirname(abs_path)
    grandparent = os.path.dirname(parent)

    if parent == folder_abs:
        return os.path.join(output_dir, filename)
    elif grandparent == folder_abs:
        return os.path.join(output_dir, os.path.basename(parent), filename)
    else:
        return os.path.join(output_dir, os.path.basename(grandparent),
                            os.path.basename(parent), filename)


def main():
    parser = argparse.ArgumentParser(
        description='移動先フォルダを AIFF タグと再照合し、どの AIFF タグとも一致しないファイルを検出する',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
例:
  %(prog)s ./aiff_folder ./output
  %(prog)s ./aiff_folder ./output --move-to ./unmatched
  %(prog)s -d ./aiff_folder ./output --move-to ./unmatched
        """
    )
    parser.add_argument('aiff_folder',   help='AIFF ファイルが入ったフォルダ（参照元）')
    parser.add_argument('target_folder', help='調査対象フォルダ（extract_aiff_matches.py の移動先）')
    parser.add_argument('-m', '--move-to', metavar='DIR',
                        help='不一致ファイルの退避先フォルダ（指定しない場合は一覧表示・ログ出力のみ）')
    parser.add_argument('-d', '--dry-run', action='store_true',
                        help='ドライラン: --move-to 指定時も実際には移動しない')
    parser.add_argument('--skip-no-tags', action='store_true',
                        help='title または album タグが空のファイルを対象から除外する（デフォルトでは不一致として報告）')

    args = parser.parse_args()

    check_ffprobe()

    for folder in [args.aiff_folder, args.target_folder]:
        if not os.path.isdir(folder):
            cprint(RED, f"Error: '{folder}' はディレクトリではありません")
            sys.exit(1)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    log_base_dir = os.path.abspath(args.move_to) if args.move_to else os.path.abspath(args.target_folder)
    unmatched_log = os.path.join(log_base_dir, f'unmatched_{timestamp}.txt')
    tag_err_log   = os.path.join(log_base_dir, f'tag_errors_{timestamp}.txt')

    print()
    cprint(BLUE, '=' * 56)
    cprint(BLUE, '   移動先ファイル 不一致検出スクリプト')
    cprint(BLUE, '=' * 56)
    print()
    print(f'AIFF フォルダ   : {CYAN}{os.path.abspath(args.aiff_folder)}{NC}')
    print(f'調査対象フォルダ: {CYAN}{os.path.abspath(args.target_folder)}{NC}')
    if args.move_to:
        print(f'退避先フォルダ  : {CYAN}{os.path.abspath(args.move_to)}{NC}')
    if args.dry_run:
        print()
        cprint(YELLOW, '[ドライラン] 実際の移動は行いません')
    print()

    # ---- AIFF タグを収集 ----
    print('AIFF ファイルのタグを読み取り中...')
    aiff_files = find_files(args.aiff_folder, ('.aiff', '.aif'))
    print(f'  {len(aiff_files)} ファイルが見つかりました')

    tag_cache     = load_tag_cache(args.aiff_folder)
    new_tag_cache = {}
    cache_hits    = 0

    aiff_keys = []
    for i, filepath in enumerate(aiff_files):
        print(f'\r  {i + 1}/{len(aiff_files)} 処理中... ', end='', flush=True)
        fp = file_fingerprint(filepath)
        cached = tag_cache.get(filepath)
        if cached and cached.get('fp') == fp:
            title, album, artist, album_artist, track, disc = cached['tags']
            cache_hits += 1
        else:
            title, album, artist, album_artist, track, disc = get_tags(filepath)
        if title is None:
            continue
        new_tag_cache[filepath] = {'fp': fp, 'tags': [title, album, artist, album_artist, track, disc]}
        aiff_keys.append((title.lower(), album.lower(), artist.lower(), album_artist.lower(), track, disc))

    save_tag_cache(args.aiff_folder, new_tag_cache)
    print(f'\r  タグ読み取り完了 ({len(aiff_files)} ファイル、キャッシュ利用 {cache_hits} 件)      ')
    print(f'  有効なタグセット: {len(aiff_keys)} 件')
    print()

    if not aiff_keys:
        cprint(YELLOW, 'AIFF からタグが取得できませんでした。終了します。')
        return

    # ---- 調査対象フォルダを検査 ----
    print('調査対象フォルダの mp3 / m4a を検索中...')
    target_files = find_files(args.target_folder, ('.mp3', '.m4a'))
    print(f'  {len(target_files)} ファイルが見つかりました')
    print()
    print('AIFF タグと再照合中...')

    unmatched = []   # (filepath, title, album, artist, album_artist, track, disc, reason)
    tag_err   = []

    target_tag_cache     = load_tag_cache(args.target_folder)
    new_target_tag_cache = {}
    target_cache_hits    = 0

    for i, filepath in enumerate(target_files):
        print(f'\r  {i + 1}/{len(target_files)} 処理中... ', end='', flush=True)
        fp = file_fingerprint(filepath)
        cached = target_tag_cache.get(filepath)
        if cached and cached.get('fp') == fp:
            title, album, artist, album_artist, track, disc = cached['tags']
            target_cache_hits += 1
        else:
            title, album, artist, album_artist, track, disc = get_tags(filepath)

        if title is None:
            tag_err.append(filepath)
            continue
        new_target_tag_cache[filepath] = {'fp': fp, 'tags': [title, album, artist, album_artist, track, disc]}
        if args.skip_no_tags and (not title or not album):
            continue

        matched, reason = classify_mismatch(title, album, artist, album_artist, track, disc, aiff_keys)
        if not matched:
            unmatched.append((filepath, title, album, artist, album_artist, track, disc, reason))

    save_tag_cache(args.target_folder, new_target_tag_cache)
    print(f'\r  照合完了 ({len(target_files)} ファイル、キャッシュ利用 {target_cache_hits} 件)      ')
    print()

    # ---- 結果表示 ----
    if unmatched:
        cprint(YELLOW, f'[不一致] {len(unmatched)} 件 (どの AIFF タグとも一致しません)')
        for filepath, title, album, artist, album_artist, track, disc, reason in unmatched:
            print(f'  {RED}[不一致]{NC} {filepath}')
            print(f'           曲名: "{title}"  /  アルバム: "{album}"  /  '
                  f'アーティスト: "{artist}"  /  アルバムアーティスト: "{album_artist}"  /  '
                  f'track: "{track}"  /  disc: "{disc}"')
            print(f'           {CYAN}理由: {reason}{NC}')
        print()
    else:
        cprint(GREEN, '不一致ファイルはありませんでした。')
        print()

    move_count = 0
    if unmatched:
        os.makedirs(log_base_dir, exist_ok=True)
        with open(unmatched_log, 'w', encoding='utf-8') as log:
            log.write('# AIFF タグと一致しなかったファイル\n')
            for filepath, title, album, artist, album_artist, track, disc, reason in unmatched:
                log.write(f'{filepath}\t曲名: "{title}"\tアルバム: "{album}"\t'
                          f'アーティスト: "{artist}"\tアルバムアーティスト: "{album_artist}"\t'
                          f'track: "{track}"\tdisc: "{disc}"\t理由: {reason}\n')

        if args.move_to:
            for filepath, title, album, artist, album_artist, track, disc, reason in unmatched:
                dest = make_dest_path(filepath, args.target_folder, os.path.abspath(args.move_to))
                print(f'  {RED}[退避]{NC} {filepath}')
                print(f'         -> {dest}')
                if not args.dry_run:
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    try:
                        shutil.move(filepath, dest)
                        move_count += 1
                    except Exception as e:
                        cprint(RED, f'  [エラー] {e}')
                else:
                    move_count += 1

    if tag_err:
        print()
        cprint(YELLOW, f'  警告: タグ読み取り失敗 {len(tag_err)} ファイル')
        for f in tag_err:
            print(f'    {f}')
        os.makedirs(log_base_dir, exist_ok=True)
        with open(tag_err_log, 'a', encoding='utf-8') as log:
            log.write('# タグ読み取り失敗\n')
            for f in tag_err:
                log.write(f + '\n')

    # ---- サマリー ----
    print()
    cprint(BLUE, '=' * 56)
    cprint(GREEN, '処理完了')
    print(f'AIFF タグセット数    : {len(aiff_keys)}')
    print(f'調査対象ファイル数   : {len(target_files)}')
    print(f'不一致ファイル数     : {len(unmatched)}')
    if args.move_to:
        print(f'退避ファイル数       : {move_count}')

    if unmatched:
        print(f'不一致ログ: {CYAN}{unmatched_log}{NC}')
    if tag_err:
        print(f'タグエラーログ: {CYAN}{tag_err_log}{NC}')

    if args.dry_run and args.move_to:
        print()
        cprint(YELLOW, '[ドライラン] 実際の移動は行われていません')


if __name__ == '__main__':
    main()
