import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))

import drawio

import xml.etree.ElementTree as ET

from seqast import Parser
from layout import Layouter


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-o', '--output', type=str, help='Output file')
    parser.add_argument('input', type=str, help='Input file')
    args = parser.parse_args()

    input_path = args.input
    output_path = args.output or change_ext(input_path, '.drawio')

    with open(input_path, 'r') as f:
        source = f.read()

    file = drawio.File()
    page = drawio.Page(file, 'Diagram')

    statement_list = Parser().parse(source)
    Layouter(page).layout(statement_list)

    with open(output_path, 'w') as f:
        f.write(file.xml_pretty())


def change_ext(path, new_ext):
    return os.path.splitext(path)[0] + new_ext


if __name__ == '__main__':
    main()
