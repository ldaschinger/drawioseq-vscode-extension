import sys
import os
import json
import re

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))

from seqast import Parser


def main():
    text = sys.stdin.read()
    errors = []
    try:
        Parser().parse(text)
    except Exception as e:
        errors.append(extract_error(e))
    print(json.dumps(errors))


def extract_error(e):
    # Lark exceptions expose .line and .column directly
    line = getattr(e, 'line', None)
    col = getattr(e, 'column', None)

    if line is None:
        m = re.search(r'line (\d+).*?col(?:umn)?\s*(\d+)', str(e), re.IGNORECASE | re.DOTALL)
        if m:
            line, col = int(m.group(1)), int(m.group(2))
        else:
            line, col = 1, 1

    # Build a clean one-line message
    raw = str(e).split('\n')
    msg = next((l.strip() for l in reversed(raw)
                if l.strip() and not l.strip().startswith('Expected')
                and not l.strip().startswith('File ')), raw[0].strip())
    msg = re.sub(r'\s+', ' ', msg)

    return {'line': int(line or 1), 'col': int(col or 1), 'message': f'Syntax error: {msg}'}


if __name__ == '__main__':
    main()
