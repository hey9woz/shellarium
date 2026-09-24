# 🐚 shellarium

> `~/bin` に潜む、小さくて実用的な CLI ツール群。

```text
  $ export PATH="$PWD/bin:$PATH"
  $ countdown pomodoro
  Countdown: Focus: 25:00 | [----------------] 0%
```

`shellarium` は、日常のターミナル作業を少しだけ自動化する個人用 Bash スクリプト集です。
各コマンドは `bin/` から直接実行でき、ドキュメントと設定例は `scripts/` にまとめています。

## ⚡ Boot Sequence

### Requirements

- Bash
- GNU coreutils (`countdown` は `date -d`、`bitsh` は `od` を使用します)
- Git (`gitwhy` では必須、`bitsh` では `--commit` 使用時のみ)
- 任意: tmux (`layout` で使用します)
- 任意: `fzf` (`gitwhy` の対話的なファイル選択で使用します)
- 任意: `notify-send`、`canberra-gtk-play`、`paplay` / `aplay` / `afplay`

### PATH を通す

リポジトリを clone し、`bin/` を PATH に追加します。

```bash
git clone <repository-url> shellarium
cd shellarium
export PATH="$PWD/bin:$PATH"
```

シェル起動時から使う場合は、実際の配置先を指定して設定ファイルへ追記します。

```bash
# bash
echo 'export PATH="/path/to/shellarium/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc

# zsh
echo 'export PATH="/path/to/shellarium/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

## 🖥️ Commands

### `countdown`

時間指定、プリセット、指定時刻、繰り返し、休憩、デスクトップ通知、履歴記録に対応したターミナルタイマーです。

```bash
countdown 5m
countdown pomodoro
countdown until 18:00
countdown --repeat 4 --break 5m pomodoro
```

詳細: [`scripts/countdown/README.md`](./scripts/countdown/README.md)

### `bitsh`

入力テキストを 8 bit の二進数へ変換して端末に表示します。ステージ済みの Git の変更を、
二進数をコミットメッセージとしてコミットすることもできます。

```bash
bitsh "Happy National AI Day"
bitsh --plain hello
bitsh --commit --dry-run "ship it"
```

詳細: [`scripts/bitsh/README.md`](./scripts/bitsh/README.md)

### `gitwhy`

ファイルと行番号を指定し、そのコードが現在の形になるまでの Git の変更履歴を読みやすく表示します。
basename や一意なパス末尾でも管理対象ファイルを指定できます。

```bash
gitwhy src/app.ts:42
gitwhy app.ts:42
gitwhy src/app.ts:40-60
gitwhy --max-count 5 app.ts:42
```

詳細: [`scripts/gitwhy/README.md`](./scripts/gitwhy/README.md)

### `layout`

現在の tmux pane から、既定・対話指定・ランダムの pane layout を作ります。

```bash
layout
layout default
layout custom
layout --dry-run random
```

詳細: [`scripts/layout/README.md`](./scripts/layout/README.md)

## 🧬 Repository Map

```text
shellarium/
├── bin/                 # PATH から呼び出す実行ファイル
├── scripts/<command>/   # コマンド別のドキュメントと補助ファイル
│   └── config/          # 設定ファイルとサンプル
├── AGENTS.md            # コーディングエージェント向け作業ルール
└── README.md
```

## 🔐 Trust Boundary

- `countdown --then COMMAND` は `bash -c` でコマンドを実行します。信頼できない文字列や外部入力を渡さないでください。
- `countdown -- COMMAND...` はシェルを介さず、指定した引数をそのまま実行します。可能ならこちらを使用してください。
- `countdown edit-presets` はリポジトリ内の `scripts/countdown/config/presets` を直接編集します。
- `bitsh --commit` はステージ済みの変更だけをコミットし、`git add` は実行しません。
- `gitwhy` は `git log -L` と `git ls-files` を使う読み取り専用コマンドです。
- `layout` は現在の tmux pane を分割します。`--dry-run` では変更せず、実行予定のコマンドだけを表示します。
- 履歴は `--log` を指定した場合だけ `${XDG_STATE_HOME:-~/.local/state}/countdown/history.tsv` に保存されます。
- トークン、秘密鍵、個人用認証情報はリポジトリへ追加しないでください。

## 🧪 Diagnostics

変更後の最小チェック:

```bash
bash -n bin/countdown
shellcheck bin/countdown
./bin/countdown --help
./bin/countdown --plain --quiet 1s
bash -n bin/bitsh
shellcheck bin/bitsh
./bin/bitsh --help
./bin/bitsh --plain hello
bash -n bin/gitwhy
shellcheck bin/gitwhy
./bin/gitwhy --help
./bin/gitwhy --version
bash -n bin/layout
shellcheck bin/layout
./bin/layout --help
./bin/layout --dry-run default
```

## 🛠️ Adding A Command

1. 実行ファイルを `bin/<command>` に追加し、実行権限を付けます。
2. `scripts/<command>/README.md` に使い方と依存コマンドを書きます。
3. この README の Commands に追加します。
4. `bash -n`、help、代表的な正常系・異常系を確認します。

実装・編集時の詳細ルールは [`AGENTS.md`](./AGENTS.md) を参照してください。

## 📜 License

[MIT License](./LICENSE) © 2026 hey9woz
