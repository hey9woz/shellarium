# layout

現在の tmux pane を起点に、よく使う pane layout を作る Bash コマンドです。
引数なしでは対話メニューを表示し、mode 名を渡すと直接実行できます。

## Usage

```bash
layout [options] [default|custom|random]
```

## Modes

- `default`: 現在の pane を上下 70% / 30% に分割します。
- `custom`: pane 数、各分割方向、新しい pane の割合を対話形式で指定します。
- `random`: 2-4 panes をランダムな方向と 20-80% の割合で作ります。

引数なしで起動すると、従来どおり mode を番号で選べます。

```text
🌐 Choose your tmux layout mode:
1: Default  (Vertical split: 70% / 30%)
2: Custom   (Interactive split)
3: Random   (Random directions and ratios)
```

`custom` と `random` では、分割で新しく作られた pane が次の分割対象になります。

## Examples

```bash
layout
layout default
layout custom
layout random
layout --dry-run default
```

`--dry-run` は実行予定の `tmux` コマンドを stdout に表示し、pane を変更しません。
tmux の外でも layout の確認に使えます。

```text
$ layout --dry-run default
tmux split-window -v -l 30%
```

## Options

```text
-n, --dry-run  Show tmux commands without changing the current layout
    --version  Show version
-h, --help     Show help
```

## Requirements

- Bash
- tmux

通常実行は、既存の tmux session 内から行ってください。
