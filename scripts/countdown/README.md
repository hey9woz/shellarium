# countdown

ターミナルで使うカウントダウンタイマーです。

時間指定、プリセット、指定時刻までのカウントダウン、繰り返し、休憩、通知、履歴記録に対応しています。

## Usage

```bash
countdown [options] DURATION|PRESET [-- COMMAND...]
countdown [options] until HH:MM [-- COMMAND...]
countdown [options] at HH:MM [-- COMMAND...]
countdown presets
countdown history [-n COUNT]
countdown edit-presets
```

## Examples

```bash
countdown 5m
countdown 1h30m
countdown pomodoro
countdown until 18:00
countdown --repeat 4 --break 5m pomodoro
countdown -t "Tea" -m "Tea is ready" tea
countdown 25m -- notify-send "Pomodoro finished"
```

## Duration Formats

```text
10        10 seconds
10s       10 seconds
2m        2 minutes
1h30m     1 hour 30 minutes
01:30     1 minute 30 seconds
01:02:03  1 hour 2 minutes 3 seconds
```

## Built-In Presets

```text
tea, coffee, pomodoro, break, standup, lunch
```

## Repository Presets

このリポジトリで管理する preset は [config/presets](./config/presets) に置いています。

```text
shortwork=15m|Short Work|Focus block finished
```

## Options

```text
-t, --title TEXT       Title shown above the timer
-m, --message TEXT     Message shown when the timer finishes
-b, --bell COUNT       Ring terminal bell COUNT times on finish (default: 3)
-n, --notify           Send a desktop notification if notify-send is available (default)
-p, --plain            Print one updating line instead of full-screen display
    --no-clear         Do not clear the screen in full-screen display
    --quiet            Disable finish bell, sound, and notification
    --repeat COUNT     Run the main timer COUNT times
    --cycles COUNT     Alias for --repeat
    --break DURATION   Break timer between repeated cycles
    --snooze DURATION  Snooze duration for the finish menu
    --then COMMAND     Run COMMAND through the shell after all timers finish
    --sound            Play a simple terminal/system sound on finish
    --sound-file PATH  Play PATH with paplay, aplay, or afplay on finish
    --log              Append completed timers to history
    --version          Show version
-h, --help             Show help
```

> [!WARNING]
> `--then COMMAND` は `bash -c` で実行されます。信頼できない文字列や外部入力を渡さないでください。
> シェル展開が不要なら `countdown 25m -- command arg...` を使用してください。

## Presets

プリセットは次のファイルで管理します。

```text
scripts/countdown/config/presets
```

形式:

```text
name=duration
name=duration|title|finish message
```

preset は、repo preset、built-in preset の順に解決します。
参照用の例として [config/presets.example](./config/presets.example) も置いています。
`countdown edit-presets` は [config/presets](./config/presets) を開きます。

```bash
countdown presets
countdown edit-presets
```

## History

`--log` を付けると、完了したタイマーを履歴に記録します。

```bash
countdown --log pomodoro
countdown history
countdown history -n 20
```

履歴ファイル:

```text
~/.local/state/countdown/history.tsv
```

## Help

最新のオプションはコマンドの help を確認してください。

```bash
countdown --help
```

## Requirements

- Bash
- GNU coreutils (`date -d` を使用するため、現状は Linux 向けです)
- 任意: `notify-send`、`paplay` / `aplay` / `afplay`
