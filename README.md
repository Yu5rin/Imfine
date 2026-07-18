# I'm fine

モニターのスリープと Microsoft Teams の「退席中」表示を防ぐ Windows 用常駐ツールです。

## 主な機能

- ワンクリックの ON/OFF トグルスイッチ（アニメーション付き）
- ON の間はモニタースリープを抑止し、一定間隔でアクティブ状態を維持
- 停止時刻を指定して自動 OFF（動作中の変更も即反映）
- タスクトレイ常駐
  - 左クリック: ON/OFF 切り替え（トースト通知で状態表示）
  - 左ダブルクリック: メイン画面を表示
  - 右クリック: メニュー（復元 / 終了）
- ライト / ダークテーマ切り替え
- 起動時に自動で ON にするオプション
- Windows 起動時の自動起動オプション
- ウィンドウ位置と設定の自動保存

## インストール

Releases ページから最新の ImFine.exe をダウンロードして実行するだけです。
インストール不要のポータブル形式です。

https://github.com/Yu5rin/Imfine/releases

## 使い方

1. ImFine.exe を起動する
2. 中央のトグルスイッチをクリックして ON にする
3. 最小化するとタスクトレイに格納される（設定で変更可能）

### 停止時刻

「有効」にチェックを入れて時刻を設定すると、その時刻に自動で OFF になります。
指定時刻が現在より前の場合は翌日のその時刻に停止します。

## 開発

Python 3.11 + tkinter 製。ビルドには PyInstaller を使用します。

```
pip install -r requirements.txt
python icon_gen.py
pyinstaller ImFine.spec
```

GitHub Actions の Build and Release ワークフローを手動実行すると、
ui.py のバージョンを読み取って自動でタグ付け・リリースされます。

## 設定ファイル

%APPDATA%\ImFine\settings.json に保存されます。
旧バージョン（Mouser）の設定は初回起動時に自動で引き継がれます。
