# drawioseq

Generate [draw.io](https://www.drawio.com/) sequence diagrams from plain-text `.seq` files — automatically on every save.

## How it works

1. Open or create a `.seq` file in your workspace
2. Write your sequence diagram using the [drawio-seqgen syntax](https://github.com/mjaun/drawio-seqgen)
3. Save the file — a `.drawio` file is generated automatically right next to it
4. Open the `.drawio` file in [Draw.io Integration](https://marketplace.visualstudio.com/items?itemName=hediet.vscode-drawio) to see your diagram live

The extension also provides:

- **Syntax highlighting** — keywords, participant names, arrows, labels, and comments are all coloured
- **Syntax checking** — parse errors are underlined in red; semantic hints (unclosed blocks, activated participants that are never deactivated, unknown participant names) are shown as grey/blue dotted underlines directly in the editor

## Source

The source code for this extension is available at [github.com/ldaschinger/drawioseq-vscode-extension](https://github.com/ldaschinger/drawioseq-vscode-extension).

## Requirements

**Python 3** must be installed and available on your `PATH` as `python3` or `python`. No additional Python packages are needed — `lark` is bundled with the extension.

## Syntax

For the full syntax reference see the [drawio-seqgen repository](https://github.com/mjaun/drawio-seqgen).

This extension is compatible with the drawio-seqgen tool as of version **1.4.26**.

## Commands

| Command | Description |
|---|---|
| `drawioseq: Generate .drawio from current .seq file` | Manually trigger generation |
| `drawioseq: Open Preview to the Side` | Generate and open the diagram beside the editor |
