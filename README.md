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

### `codex-apply`

Codexのグローバル `config.toml`・`AGENTS.md`・各プロファイルの `*.config.toml` を取り込み・適用します。
Bash、Git、Python 3.11以降が必要です。毎回差分を表示し、確認後だけ変更します。

```bash
codex-apply --capture  # この端末の設定を取り込み、定型の連番コミットを作成
codex-apply            # 管理元の設定をこの端末へ適用
codex-apply --help
```

認証情報を検証してから差分を表示します。通常適用は `projects` を除いて置き換え、バックアップは配置先ごとに1世代だけ保持します。
端末固有の `projects` はcaptureで除外し、適用先の設定を保持します。
配布元にないプロファイルは、削除差分を確認・承認した後に削除して同期します。
`--capture` はこれらの対象ファイルだけを `chore(codex-apply): capture v0001` の形式でコミットします。pushは行いません。
初回はこの端末の設定からcaptureしてください。設定後のCodex起動は通常の `codex` コマンドです。

詳細: [`scripts/codex-apply/README.md`](./scripts/codex-apply/README.md)

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

Codex設定管理のオフライン検証（使い捨てリポジトリでコミット動作も確認）:

```bash
bash -n bin/codex-apply
shellcheck bin/codex-apply
./bin/codex-apply --help
python3 scripts/codex-apply/test_manage.py
```

既存コマンド変更後の最小チェック:

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
