# gitwhy

ファイルと行番号を指定し、そのコードが現在の形になるまでの Git の変更履歴を
読みやすく表示する Bash コマンドです。

> 「このコード、なんでこうなってる？」を 1 コマンドで調べる。

履歴追跡は Git の line log (`git log -L`) に任せ、`gitwhy` は管理対象ファイルの探索、
簡潔な行指定、コミット境界の整形を担当します。リポジトリや作業ファイルは変更しません。

## Usage

```bash
gitwhy [options] FILE:LINE
gitwhy [options] FILE:START-END
gitwhy [options]
```

行番号は正の整数を指定します。範囲では `START` が `END` 以下である必要があります。

```bash
gitwhy src/features/order/OrderService.php:243
gitwhy OrderService.php:243
gitwhy order/OrderService.php:243
gitwhy OrderService.php:230-260
```

## File Resolution

ファイルは `git ls-files` が返す Git 管理対象ファイルから、リポジトリルート基準で
次の順に解決します。

1. パスの完全一致
2. パス末尾の一致（basename だけの指定を含む）

末尾一致が 1 件ならそのファイルを使用します。0 件の場合はエラーになります。
同名ファイルなどが複数件ある場合は勝手に選ばず、安定した順序で候補を表示します。
その場合は、一意になるまで長いパスを指定してください。

```text
gitwhy: multiple files matched "index.ts"

  src/api/index.ts
  src/index.ts
  src/order/index.ts

Specify a longer path.
```

## Interactive Mode

引数なしで TTY から実行すると、管理対象ファイルを選んだ後、行番号または範囲を入力できます。

```bash
gitwhy
```

`fzf` がインストールされていればファイル選択に使用します。`fzf` は optional dependency で、
存在しない場合は Bash の番号付きメニューにフォールバックします。パイプなど TTY でない入力では
対話モードを利用できないため、`FILE:LINE` を明示してください。

## Options

```text
-n, --max-count N  Show at most N commits
    --no-patch     Show commit metadata only
    --reverse      Show oldest changes first
    --version      Show version
-h, --help         Show help
```

`--no-patch` はコミットの hash、日付、author、subject だけを表示します。
色は stdout が TTY の場合だけ使用し、`NO_COLOR` が設定されている場合は無効になります。

## How It Works

解決したファイルと行範囲を `git log -L START,END:FILE` に渡します。patch 自体は独自解析せず、
Git の出力を保ったまま、コミット情報と区切り線だけを見やすく整形します。

## Limitations

`gitwhy` の追跡能力は Git の line log に準じます。特に大規模なリファクタ、ファイル移動、
別ファイルへのコード移動では、期待する履歴まで遡れないことがあります。line log は現在の行範囲を
変更したコミットを追う機能であり、コードの意図や関連コミットすべてを推測するものではありません。

行範囲は現在の `HEAD` にあるファイルを基準にします。Git が扱えない範囲や、履歴が存在しない
ファイルを指定した場合は `git log -L` のエラーになります。

## Requirements

- Bash
- Git
- 任意: `fzf`（対話モードのファイル選択）
