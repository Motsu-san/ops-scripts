# xavc_import

SONY α6000 で撮影した XAVC (C####.MP4) を、SD カード接続時に自動で H.264 に変換し、NAS（またはローカル）にアップロードするスクリプト群。

## 構成

- `run.sh` — エントリポイント。USB接続チェック、多重起動防止（ロックファイル）、ログのローテーション（1MB超で最大5世代バックアップ）を行い、`convert_and_upload.sh` を実行してログを記録する。
- `convert_and_upload.sh` — 実際の変換・アップロード処理。
- `launchd/com.auto_xavc2h264.usbconnect.plist` — `/Volumes/Untitled` のマウントを監視し、SDカード接続時に `run.sh` を自動起動する launchd 設定。

## 処理の流れ (`convert_and_upload.sh`)

1. `/Volumes/Untitled/private/M4ROOT/CLIP` から `C*.MP4` を作業フォルダ `<日時>_xavc/` にコピー
   - マウントされていない場合、過去の `*_xavc/`（未変換）・`*_mp4/`（未アップロード）に残っているファイルを今回の作業フォルダに回収
2. `/Volumes/Untitled/DCIM/100MSDCF` の RAW 画像 (`*.ARW`) をアップロード先にコピー
3. 連番ファイルごとに `exiftool` で撮影日時 (`LastUpdate`) を取得し、`ffmpeg` で H.264 に変換して `<日時>_mp4/` に出力（メタデータ・音声は維持）
   - 変換が成功した元ファイルは削除、失敗したものは `<日時>_xavc/` に残す
4. 変換後ファイルを1件ずつ `<日時>_alpha6000/` としてアップロード先（`/Volumes/photo` または `$HOME/Photo`）にコピー
   - アップロードが成功したファイルは削除、失敗したものは `<日時>_mp4/` に残す
5. 各ループの終了後、空になった作業フォルダを削除。失敗があれば exit 1 で終了し、残ったファイルは次回の実行で再処理される

## セットアップ

plist は `~/Library/LaunchAgents/` にコピーせず、リポジトリ内の実体へのシンボリックリンクとして配置する（リポジトリの更新がそのまま反映されるため）。

```bash
ln -s $HOME/repos/ops-scripts/xavc_import/launchd/com.auto_xavc2h264.usbconnect.plist \
  ~/Library/LaunchAgents/com.auto_xavc2h264.usbconnect.plist
launchctl load ~/Library/LaunchAgents/com.auto_xavc2h264.usbconnect.plist
```

## 注意

- SDカード側の元ファイルは削除しない（α6000側でエラーが発生するため）。
- ログは `xavc_import.log`、バックアップは `log_backup/` に保存される。
