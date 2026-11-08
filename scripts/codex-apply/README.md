# codex-apply

この端末のCodexグローバル設定をGitで管理し、他のUbuntu環境へ適用します。
起動ラッパーや秘密情報の配布は行いません。設定後は通常の `codex` コマンドで起動します。

```bash
codex-apply --capture  # この端末 → リポジトリ、確認後に連番コミット
codex-apply            # リポジトリ → この端末、確認後に全体を置き換え
codex-apply --help
```

## 必要なもの

- Bash、Git、Python 3.11以降（標準 `tomllib`）。Ubuntu/Linux向けです。
- 確認に応答できる対話端末。非対話実行では変更せず終了します。
- capture時はGitのユーザー名・メールアドレスが設定済みであること。

このリポジトリの `bin/` をPATHに追加してください。コマンドはどの作業ディレクトリからでも実行できます。
依存コマンドの自動インストールやsudo、ネットワーク接続は行いません。

## 初回の取り込み

初回は配布する設定ファイルを同梱していません。この端末で用意した設定から取り込みます。
対象は `${CODEX_HOME:-$HOME/.codex}/config.toml` と同ディレクトリの `AGENTS.md` の2ファイルです。
どちらかがない場合は、内容を自分で用意してから実行してください。存在しないファイルを勝手に空ファイルへ置き換えることはありません。

```bash
codex-apply --capture
```

1. 2ファイルを検証します。秘密情報が疑われる場合は、値を表示せず停止します。
2. 取り込み先・差分・次のバージョン・コミットメッセージを表示します。
3. `取り込み・コミットを実行しますか？ [y/N]` に `y` / `yes` と答えた場合だけ取り込みます。
4. `scripts/codex-apply/config/{config.toml,AGENTS.md}` だけをコミットします。

確認前に秘密情報の検証を行い、確認中にファイルやGit HEADが変わった場合は停止します。
コミットメッセージは次の形式です。

```text
chore(codex-apply): capture v0001
chore(codex-apply): capture v0002
```

現在のブランチ履歴にある同形式の最大番号に1を加えます。コミット成功時だけ番号が確定します。
差分なしの場合はコミット・採番をしません。GitのコミットIDも表示します。
複数ブランチでそれぞれcaptureすると番号が重複し得るため、連番管理は1つのブランチで行ってください。

無関係な作業ツリー・ステージ済み変更はコミットに含めません。管理対象2ファイルが既にステージされている場合、または別の未コミット編集がある場合は停止します。
pre-commit / prepare-commit-msg / commit-msg を別インデックスで実行し、その後に対象・内容・定型メッセージが変わっていないことを検証します。hookによる自動修正や追加ステージは停止対象です。commit.gpgsignによる署名にも対応します。信頼できるhooks/filterだけを使ってください。
検証済みツリーからコミットを作成し、HEADが変わっていない場合だけブランチを更新します。post-commitの失敗は警告として表示し、作成済みコミットは残します。
マージ・rebase・cherry-pick等の進行中、または未解決のインデックスがある場合はcaptureを拒否します。
Gitのclean filterが検証済みの内容を変更する場合はコミットせず停止します。
**pushは実行しません。** 他の端末へ配布するためのGitの送受信は別途行ってください。

## 別の端末への適用・設定の更新

配布先でリポジトリを更新してから実行します。

```bash
codex-apply
```

配置先・変更ファイル・差分を表示し、確認後に適用します。
`--dry-run` はありません。Enterだけ、または `y` / `yes` 以外ならキャンセルします。
**ファイル単位で管理元の内容に置き換えます。** 端末側だけの設定・プロファイルが消える場合もあるため、差分を確認してください。
管理元と配置済みファイルの両方を検証するので、配置済みファイルに認証情報・未対応設定がある場合も、差分を表示せず停止します。

設定を更新する場合は、端末の設定を編集して再度 `--capture` します。
Git管理の2ファイルを直接編集した場合は、別途レビュー・コミットしてから適用してください。
適用そのものではコミットしません。差分なし・キャンセル時は設定とバックアップを変更しません。

`CODEX_HOME` を使う場合は絶対パスを指定します。

```bash
CODEX_HOME="$HOME/codex-settings" codex-apply
```

シンボリックリンクを経由するパス、配置先がディレクトリの場合、リポジトリ内への設定・状態ファイルの生成は拒否します。
`auth.json`、履歴・ログ、別のプロファイルファイルなどは読み取り・コピー対象ではありません。

## バリデーション

[TOMLはPython標準のパーサー](https://docs.python.org/3/library/tomllib.html)で解析します。
秘密情報の実値をエラーメッセージに含めず、ファイル・項目の種類を表示します。未対応の項目名自体が秘密情報である可能性もあるため、その場合は `<unsupported>` と表示します。

### config.tomlの配布可能項目

安全側に絞った許可リストを `validate.py` で管理します。Codex全体の設定スキーマを網羅するものではありません。
主な対応範囲は以下です。

- モデル・推論・verbosity・approval・sandbox・personality・web searchなどの基本設定
- `[profiles.<name>]` 内の同じ設定項目
- `[features]` のbool値、history、sandbox_workspace_writeの一部
- `[model_providers.<name>]` の基本項目と `env_key` による環境変数名指定
- 次に示すMCP設定

未対応設定、端末固有のプロジェクトパス、絶対パス・ホーム依存のMCPコマンドやcwdは停止します。
必要な項目は、公式仕様と秘密情報の扱いを確認してから許可リストへ追加してください。
別ファイルのプロファイルは今回の配布対象に含めません。
[Codex設定リファレンス](https://developers.openai.com/codex/config-reference/)

### MCPは環境変数参照を使う

認証不要のMCP、および正式な環境変数参照形式を許可します。

```toml
[mcp_servers.example_stdio]
command = "example-mcp-server"
env_vars = ["EXAMPLE_API_KEY"]

[mcp_servers.example_http]
url = "https://example.invalid/mcp"
bearer_token_env_var = "EXAMPLE_TOKEN"
env_http_headers = { "X-API-Key" = "EXAMPLE_API_KEY" }
```

- `env_vars` は文字列と `{ name = "NAME", source = "local" }` / `source = "remote"` に対応します。
- 参照先には変数名だけを指定します。`${NAME}` のような補間文字列は受け付けません。
- 固定値を指定する `env`・`http_headers`、OAuthの `client_secret` などは拒否します。
- URL欄と引数内のURLのユーザー情報・クエリ・フラグメント、`--key` / `--auth` / `--credential` などの認証引数、シェルラッパーや `-c` / `--eval` のような実行文字列も拒否します。
- `command` と `args` に必要な実行ファイル・依存関係は、各端末で別途用意してください。

環境変数の存在・実値・MCPとの接続は検証しません。環境変数の配布・設定も行いません。
[公式MCP仕様](https://developers.openai.com/codex/mcp/)

### 秘密情報の検出と限界

両ファイルの既知のトークン形式、秘密鍵、認証情報らしい代入、ランダムな認証文字列らしい値、端末制御文字を検査します。
TOMLは文字列のエスケープを解いた内容も検査し、コメントも検査対象です。
`AGENTS.md` の自由文や短い任意の文字列から、秘密情報を完全に判別することはできません。誤検知・見逃しの可能性があります。
保存前の差分確認とコミット前のレビューも行ってください。検出時に自動削除・自動マスクして取り込む処理はしません。

## バックアップ・失敗時の復元

通常適用のバックアップは次の場所へ、**配置先ごとに直前の1世代だけ**保存します。

```text
${XDG_STATE_HOME:-$HOME/.local/state}/codex-apply/<配置先のハッシュ>/backup.json
```

成功後にバックアップを入れ替えるため、日時付きファイルが増え続けることはありません。
内容には変更前の両ファイル、権限、元ファイルが存在しなかったこと、配置先が記録されます。
バックアップと新規設定ファイルは `0600`、新規ディレクトリは `0700` で作成します。

適用途中の通常エラーでは、両ファイルを変更前の状態へ戻し、前世代のバックアップを保持します。
強制終了や復元の失敗で `pending.json` が残った場合、次回は停止して復元情報の場所を表示します。
同時実行はロックで防ぎます。外部のエディターやGit操作と同時に更新しないでください。

手動復元はCodexを終了し、表示された `backup.json`（未完了操作なら `pending.json`）の `target` と内容を確認して行います。
次は確認後に明示的な1つの復元情報を指定する例です。元の対象2ファイルを上書きし、元々存在しなかったファイルは削除します。

```bash
python3 - /exact/path/to/backup.json <<'PY'
import base64, json, os, pathlib, sys
record = json.loads(pathlib.Path(sys.argv[1]).read_text())
target = pathlib.Path(record["target"])
print("Restore target:", target)
with open("/dev/tty", "r") as reader, open("/dev/tty", "w") as writer:
    writer.write("Restore both files? [y/N] ")
    writer.flush()
    if reader.readline().strip().lower() != "y":
        raise SystemExit(0)
for name in ("config.toml", "AGENTS.md"):
    path = target / name
    if path.is_symlink():
        raise SystemExit("Refusing a symbolic link")
    item = record["files"][name]
    if item is None:
        path.unlink(missing_ok=True)
    else:
        path.write_bytes(base64.b64decode(item["content"]))
        os.chmod(path, item["mode"])
PY
```

復元確認後、未完了操作の `pending.json` がある場合は、その1ファイルだけを取り除いてから再実行してください。
バックアップはBase64形式であり、暗号化ではありません。公開・Git登録しないでください。

captureではGit履歴が設定のバージョンになります。
コミットが失敗した場合は取り込み済みのファイルを残し、バージョンを確定しません。
Gitのユーザー情報・署名・hooks等を修正して `codex-apply --capture` を再実行すると、差分を再確認してコミットを再試行できます。
独立した未コミット編集がある場合は、先にその編集を整理してください。

## 開発時の検証

```bash
bash -n bin/codex-apply
shellcheck bin/codex-apply
./bin/codex-apply --help
python3 scripts/codex-apply/test_manage.py
```

テストは一時HOME、一時Gitリポジトリ、疑似端末を使用し、実際の認証情報・ネットワーク・Codexログインは不要です。
Gitのコミット作成も使い捨てリポジトリ内でのみ検証します。実際のホーム設定への適用は自動テストしません。
