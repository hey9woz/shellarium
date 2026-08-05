# bitsh

入力テキストを 8 bit の二進数へ変換し、端末上でハッカー風に表示する Bash コマンドです。
ステージ済みの Git の変更を、変換後の二進数をコミットメッセージとしてコミットできます。

## Usage

```bash
bitsh [options] [TEXT...]
printf '%s' TEXT | bitsh [options]
```

## Examples

```bash
bitsh "Happy National AI Day"
bitsh --plain hello
printf 'hello' | bitsh --plain
```

通常は TTY 上で色と短い演出を付けて表示します。パイプやリダイレクトで使う場合、または
`--plain` を指定した場合は、二進数だけを 1 行で出力します。

```text
01001000 01100001 01110000 01110000 01111001
```

変換単位は文字ではなく UTF-8 の各バイトです。そのため、ASCII は 1 文字につき 1 個、
日本語などは 1 文字につき複数の 8 bit 値として表示されます。

## Git Commit

変更を先にステージし、コミットに使うテキストを渡します。

```bash
git add path/to/file
bitsh --commit "ship it"
```

`bitsh` はステージ済みの変更一覧を表示し、確認後、次のような二進数をコミットメッセージにして
`git commit` を実行します。

```text
01110011 01101000 01101001 01110000 00100000 01101001 01110100
```

安全のため `git add` は実行せず、未ステージの変更や未追跡ファイルを自動追加しません。
実行内容の確認だけを行う場合は `--dry-run` を使用します。非対話環境で確認を省略する場合は
明示的に `--yes` を指定します。

```bash
bitsh --commit --dry-run "ship it"
bitsh --commit --yes "ship it"
```

## Options

```text
-p, --plain    Print only the binary value without terminal effects
-c, --commit   Commit staged Git changes using the binary value as the message
-n, --dry-run  Preview the commit without creating it
-y, --yes      Skip the confirmation prompt used by --commit
    --version  Show version
-h, --help     Show help
```

色だけを無効にして演出を残す場合は `NO_COLOR=1 bitsh TEXT` を使用できます。

## Requirements

- Bash
- GNU coreutils (`od`)
- Git (`--commit` を使う場合のみ)
