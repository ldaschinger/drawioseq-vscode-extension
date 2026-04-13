from dataclasses import dataclass
from enum import auto, Enum
from typing import List, Optional, Any
from lark import Lark, Transformer
from pathlib import Path

from drawio import LineStyle, ArrowStyle

SCRIPT_DIR = Path(__file__).resolve().parent


class Parser:
    def __init__(self):
        with open(SCRIPT_DIR / 'syntax.lark', 'r') as f:
            grammar = f.read()

        self.lark = Lark(grammar, start='start', propagate_positions=True)

    def parse(self, text: str) -> List['Statement']:
        text = text.replace('\r', '')
        if not text.endswith('\n'):
            text += '\n'

        parsed = self.lark.parse(text)
        return SeqTransformer().transform(parsed)


class SeqTransformer(Transformer):
    @staticmethod
    def start(items):
        return consume_next(items, 'statement_list')

    @staticmethod
    def statement_list(items):
        statements = []

        for item in items:
            statement = item.children[0]
            statement.line_number = item.meta.line
            statements.append(statement)

        return ParsedValue(statements, 'statement_list')

    @staticmethod
    def title(items):
        width = consume_opt(items, 'title_width')
        height = consume_opt(items, 'title_height')
        text = consume_next(items, 'TEXT')
        return TitleStatement(text, width, height)

    @staticmethod
    def title_width(items):
        value = consume_next(items, 'NUMBER')
        return ParsedValue(value, 'title_width')

    @staticmethod
    def title_height(items):
        value = consume_next(items, 'NUMBER')
        return ParsedValue(value, 'title_height')

    @staticmethod
    def participant(items):
        name = consume_next(items, 'NAME')
        width = consume_opt(items, 'participant_width')
        spacing = consume_opt(items, 'participant_spacing')
        text = consume_opt(items, 'TEXT')
        return ParticipantStatement(name, text or name, width, spacing)

    @staticmethod
    def participant_alias(items):
        value = consume_next(items, 'NAME')
        return ParsedValue(value, 'participant_alias')

    @staticmethod
    def participant_width(items):
        value = consume_next(items, 'NUMBER')
        return ParsedValue(value, 'participant_width')

    @staticmethod
    def participant_spacing(items):
        value = consume_next(items, 'NUMBER')
        return ParsedValue(value, 'participant_spacing')

    @staticmethod
    def activate(items):
        targets = consume_all(items, 'NAME')
        return ActivateStatement(targets)

    @staticmethod
    def deactivate(items):
        targets = consume_all(items, 'NAME')
        return DeactivateStatement(targets)

    @staticmethod
    def found_message(items):
        direction = consume_next(items, 'direction')
        width = consume_next_opt(items, 'NUMBER')
        line, arrow, activation = consume_next(items, 'arrow')
        receiver = consume_next(items, 'NAME')
        text = consume_next_opt(items, 'TEXT', default='')
        return FoundMessageStatement(direction, receiver, text, activation, line, arrow, width)

    @staticmethod
    def lost_message(items):
        sender = consume_next(items, 'NAME')
        line, arrow, activation = consume_next(items, 'arrow')
        direction = consume_next(items, 'direction')
        width = consume_next_opt(items, 'NUMBER')
        text = consume_next_opt(items, 'TEXT', default='')
        return LostMessageStatement(sender, direction, text, activation, line, arrow, width)

    @staticmethod
    def DIRECTION(token):
        direction_map = {
            'left': MessageDirection.LEFT,
            'right': MessageDirection.RIGHT,
        }

        value = direction_map[str(token)]
        return ParsedValue(value, 'direction')

    @staticmethod
    def message(items):
        sender = consume_next(items, 'NAME')
        line, arrow, activation = consume_next(items, 'arrow')
        receiver = consume_next(items, 'NAME')
        text = consume_next_opt(items, 'TEXT', default='')
        return MessageStatement(sender, receiver, text, activation, line, arrow)

    @staticmethod
    def self_call(items):
        target = consume_next(items, 'NAME')
        text = consume_next_opt(items, 'TEXT', default='')
        return MessageStatement(target, target, text, MessageActivation.FIREFORGET, LineStyle.SOLID, ArrowStyle.BLOCK)

    @staticmethod
    def option(items):
        text = consume_next_opt(items, 'TEXT')
        inner = consume_next(items, 'statement_list')
        return FrameStatement('opt', text, inner, [])

    @staticmethod
    def loop(items):
        text = consume_next_opt(items, 'TEXT')
        inner = consume_next(items, 'statement_list')
        return FrameStatement('loop', text, inner, [])

    @staticmethod
    def break_(items):
        text = consume_next_opt(items, 'TEXT')
        inner = consume_next(items, 'statement_list')
        return FrameStatement('break', text, inner, [])

    @staticmethod
    def critical(items):
        text = consume_next_opt(items, 'TEXT')
        inner = consume_next(items, 'statement_list')
        return FrameStatement('critical', text, inner, [])

    @staticmethod
    def alternative(items):
        text = consume_next_opt(items, 'TEXT')
        inner = consume_next(items, 'statement_list')
        sections = consume_all(items, 'alternative_section')
        return FrameStatement('alt', text, inner, sections)

    @staticmethod
    def alternative_section(items):
        text = consume_next_opt(items, 'TEXT', default='else')
        inner = consume_next(items, 'statement_list')
        return ParsedValue(FrameSection(text, inner), 'alternative_section')

    @staticmethod
    def parallel(items):
        text = consume_next_opt(items, 'TEXT')
        inner = consume_next(items, 'statement_list')
        sections = consume_all(items, 'parallel_section')
        return FrameStatement('par', text, inner, sections)

    @staticmethod
    def parallel_section(items):
        text = consume_next_opt(items, 'TEXT')
        inner = consume_next(items, 'statement_list')
        return ParsedValue(FrameSection(text, inner), 'parallel_section')

    @staticmethod
    def group(items):
        title = consume_next(items, 'QUOTED_TEXT')
        text = consume_next_opt(items, 'TEXT')
        inner = consume_next(items, 'statement_list')
        sections = consume_all(items, 'group_section')
        return FrameStatement(title, text, inner, sections)

    @staticmethod
    def group_section(items):
        text = consume_next_opt(items, 'TEXT')
        inner = consume_next(items, 'statement_list')
        return ParsedValue(FrameSection(text, inner), 'group_section')

    @staticmethod
    def note(items):
        target = consume_next(items, 'NAME')
        dx = consume_opt(items, 'note_dx')
        dy = consume_opt(items, 'note_dy')
        width = consume_opt(items, 'note_width')
        height = consume_opt(items, 'note_height')
        text = consume_next(items, 'TEXT')
        return NoteStatement(target, text, dx, dy, width, height)

    @staticmethod
    def note_dx(items):
        value = consume_next(items, 'NUMBER')
        return ParsedValue(value, 'note_dx')

    @staticmethod
    def note_dy(items):
        value = consume_next(items, 'NUMBER')
        return ParsedValue(value, 'note_dy')

    @staticmethod
    def note_width(items):
        value = consume_next(items, 'NUMBER')
        return ParsedValue(value, 'note_width')

    @staticmethod
    def note_height(items):
        value = consume_next(items, 'NUMBER')
        return ParsedValue(value, 'note_height')

    @staticmethod
    def vertical_offset(items):
        offset = consume_next(items, 'NUMBER')
        return VerticalOffsetStatement(offset)

    @staticmethod
    def extend_frame(items):
        extend = consume_next(items, 'NUMBER')
        return ExtendFrameStatement(extend)

    @staticmethod
    def arrow(items):
        line = consume_next(items, 'ARROW_LINE')
        arrow = consume_next(items, 'ARROW_END')
        activation = consume_next_opt(items, 'arrow_activation', MessageActivation.REGULAR)
        return ParsedValue((line, arrow, activation), 'arrow')

    @staticmethod
    def ARROW_LINE(token):
        line_map = {
            '-': LineStyle.SOLID,
            '--': LineStyle.DASHED,
        }

        return ParsedValue(line_map[str(token)], 'ARROW_LINE')

    @staticmethod
    def ARROW_END(token):
        arrow_map = {
            '>': ArrowStyle.BLOCK,
            '>>': ArrowStyle.OPEN,
        }

        return ParsedValue(arrow_map[str(token)], 'ARROW_END')

    @staticmethod
    def ARROW_ACTIVATION(token):
        activation_map = {
            '+': MessageActivation.ACTIVATE,
            '-': MessageActivation.DEACTIVATE,
            '|': MessageActivation.FIREFORGET,
        }

        return ParsedValue(activation_map[str(token)], 'arrow_activation')

    @staticmethod
    def QUOTED_TEXT(token):
        text = str(token)[1:-1]
        text = text.replace(r'\"', '"')
        return ParsedValue(text, 'QUOTED_TEXT')

    @staticmethod
    def TEXT(token):
        return ParsedValue(str(token), 'TEXT')

    @staticmethod
    def NAME(token):
        return ParsedValue(str(token), 'NAME')

    @staticmethod
    def NUMBER(token):
        return ParsedValue(int(token), 'NUMBER')


@dataclass
class Statement:
    def __init__(self):
        self.line_number = 0


@dataclass
class TitleStatement(Statement):
    text: str
    width: Optional[int] = None
    height: Optional[int] = None


@dataclass
class ParticipantStatement(Statement):
    name: str
    text: str
    width: Optional[int] = None
    spacing: Optional[int] = None


@dataclass
class ActivateStatement(Statement):
    targets: List[str]


@dataclass
class DeactivateStatement(Statement):
    targets: List[str]


class MessageDirection(Enum):
    LEFT = auto()
    RIGHT = auto()


class MessageActivation(Enum):
    REGULAR = auto()
    ACTIVATE = auto()
    DEACTIVATE = auto()
    FIREFORGET = auto()


@dataclass
class MessageStatement(Statement):
    sender: str
    receiver: str
    text: str
    activation: MessageActivation
    line_style: LineStyle
    arrow_style: ArrowStyle


@dataclass
class FoundMessageStatement(Statement):
    from_direction: MessageDirection
    receiver: str
    text: str
    activation: MessageActivation
    line_style: LineStyle
    arrow_style: ArrowStyle
    width: Optional[int]


@dataclass
class LostMessageStatement(Statement):
    sender: str
    to_direction: MessageDirection
    text: str
    activation: MessageActivation
    line_style: LineStyle
    arrow_style: ArrowStyle
    width: Optional[int]


@dataclass
class FrameSection:
    text: Optional[str]
    inner: List[Statement]


@dataclass
class FrameStatement(Statement):
    title: str
    text: Optional[str]
    inner: List[Statement]
    sections: List[FrameSection]


@dataclass
class NoteStatement(Statement):
    target: str
    text: str
    dx: Optional[int] = None
    dy: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None


@dataclass
class VerticalOffsetStatement(Statement):
    offset: int


@dataclass
class ExtendFrameStatement(Statement):
    extend: int


@dataclass
class ParsedValue:
    value: Any
    type: str


def consume_next(items, expected_type):
    assert len(items) > 0, "missing item"
    assert isinstance(items[0], ParsedValue), f"unparsed value: {items[0]}"
    assert items[0].type == expected_type, f"expected '{expected_type}' found '{items[0].type}'"
    return items.pop(0).value


def consume_next_opt(items, expected_type, default=None):
    if len(items) == 0:
        return default

    assert isinstance(items[0], ParsedValue), f"unparsed value: {items[0]}"
    return items.pop(0).value if items[0].type == expected_type else default


def consume_opt(items, expected_type, default=None):
    for item in items:
        assert isinstance(item, ParsedValue), f"unparsed value: {items[0]}"

        if item.type == expected_type:
            items.remove(item)
            return item.value

    return default


def consume_all(items, expected_type):
    found = []
    for item in items:
        assert isinstance(item, ParsedValue), f"unparsed value: {items[0]}"

        if item.type == expected_type:
            found.append(item)

    items[:] = [item for item in items if item not in found]
    return [item.value for item in found]
