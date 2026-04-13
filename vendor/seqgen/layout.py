from typing import List, Optional, Iterable

import seqast
import drawio

PARTICIPANT_DEFAULT_WIDTH = 160
PARTICIPANT_DEFAULT_SPACING = 40
PARTICIPANT_BOX_HEIGHT = 40

TITLE_FRAME_DEFAULT_BOX_WIDTH = 160
TITLE_FRAME_DEFAULT_BOX_HEIGHT = 30
TITLE_FRAME_PADDING = 20

CONTROL_FRAME_BOX_WIDTH = 60
CONTROL_FRAME_BOX_HEIGHT = 20
CONTROL_FRAME_LABEL_HEIGHT = 35
CONTROL_FRAME_PADDING = 20
CONTROL_FRAME_ACTIVITY_EXTRA_PADDING = 10
CONTROL_FRAME_SPACING_BEFORE = 5
CONTROL_FRAME_SPACING_AFTER = 5

NOTE_DEFAULT_WIDTH = 100
NOTE_DEFAULT_HEIGHT = 40

FOUND_LOST_MESSAGE_DEFAULT_WIDTH = 100

SELF_CALL_MIN_TEXT_WIDTH = 30
SELF_CALL_MESSAGE_DX = 25

FIREFORGET_ACTIVATION_HEIGHT = 20

STATEMENT_OFFSET_Y = 10
MESSAGE_MIN_SPACING = 20
START_POSITION_Y = PARTICIPANT_BOX_HEIGHT + (2 * STATEMENT_OFFSET_Y)

ACTIVATION_STACK_OFFSET_X = drawio.ACTIVATION_WIDTH / 2
MESSAGE_ANCHOR_DY = drawio.MESSAGE_ANCHOR_DY


class PositionMarker:
    def __init__(self):
        self.y = START_POSITION_Y - STATEMENT_OFFSET_Y


class ParticipantInfo:
    def __init__(self, index: int, name: str, lifeline: drawio.Lifeline):
        self.index = index
        self.name = name
        self.lifeline = lifeline
        self.activation_stack: List[drawio.Activation] = []
        self.center_marker: PositionMarker = PositionMarker()
        self.left_marker: PositionMarker = PositionMarker()
        self.right_marker: PositionMarker = PositionMarker()


class FrameDimension:
    def __init__(self):
        self.min_x: Optional[float] = None
        self.max_x: Optional[float] = None


class Layouter:
    def __init__(self, page: drawio.Page):
        self.page = page
        self.participants: List[ParticipantInfo] = []
        self.frame_dimension_stack: List[FrameDimension] = [FrameDimension()]
        self.title_frame: Optional[drawio.Frame] = None
        self.current_position_y = START_POSITION_Y
        self.executed = False

    def layout(self, statements: List[seqast.Statement]):
        assert not self.executed, "layouter instance can only be used once"
        self.executed = True

        self.process_statements(statements)

        self.finalize_participants()
        self.finalize_title_frame()

    def finalize_participants(self):
        self.current_position_y += STATEMENT_OFFSET_Y

        for participant in self.participants:
            assert not participant.activation_stack, f"participants must be inactive at end: {participant.name}"
            participant.lifeline.height = self.current_position_y

    def finalize_title_frame(self):
        assert len(self.frame_dimension_stack) == 1
        dimensions = self.frame_dimension_stack.pop()

        if not self.title_frame:
            return

        self.title_frame.x = dimensions.min_x - TITLE_FRAME_PADDING
        self.title_frame.y = -TITLE_FRAME_PADDING - self.title_frame.box_height
        self.title_frame.width = dimensions.max_x + TITLE_FRAME_PADDING - self.title_frame.x
        self.title_frame.height = (self.current_position_y - self.title_frame.y) + TITLE_FRAME_PADDING

    def process_statements(self, statements: List[seqast.Statement]):
        handlers = {
            seqast.TitleStatement: self.handle_title,
            seqast.ParticipantStatement: self.handle_participant,
            seqast.ActivateStatement: self.handle_activate,
            seqast.DeactivateStatement: self.handle_deactivate,
            seqast.FoundMessageStatement: self.handle_found_message,
            seqast.LostMessageStatement: self.handle_lost_message,
            seqast.MessageStatement: self.handle_message,
            seqast.FrameStatement: self.handle_frame,
            seqast.NoteStatement: self.handle_note,
            seqast.VerticalOffsetStatement: self.handle_vertical_offset,
            seqast.ExtendFrameStatement: self.handle_extend_frame,
        }

        for statement in statements:
            try:
                # noinspection PyTypeChecker, PyArgumentList
                handlers[type(statement)](statement)
            except:
                raise RuntimeError(f'error processing statement on line {statement.line_number}')

    def handle_title(self, statement: seqast.TitleStatement):
        assert not self.title_frame, "title may occur only once"
        self.title_frame = drawio.Frame(self.page, statement.text)
        self.title_frame.box_width = statement.width or TITLE_FRAME_DEFAULT_BOX_WIDTH
        self.title_frame.box_height = statement.height or TITLE_FRAME_DEFAULT_BOX_HEIGHT

    def handle_participant(self, statement: seqast.ParticipantStatement):
        assert not self.participant_by_name(statement.name), "participant already exists"

        first_participant = len(self.participants) == 0
        index = len(self.participants)

        lifeline = drawio.Lifeline(self.page, statement.text)
        lifeline.width = statement.width or PARTICIPANT_DEFAULT_WIDTH
        lifeline.box_height = PARTICIPANT_BOX_HEIGHT

        if not first_participant:
            prev_lifeline = self.participants[-1].lifeline
            lifeline.x = prev_lifeline.x + prev_lifeline.width + (statement.spacing or PARTICIPANT_DEFAULT_SPACING)

        participant = ParticipantInfo(index, statement.name, lifeline)

        if not first_participant:
            participant.left_marker = self.participants[-1].right_marker

        self.participants.append(participant)
        self.frame_dimension(lifeline.x, lifeline.x + lifeline.width)

    def handle_activate(self, statement: seqast.ActivateStatement):
        for name in statement.targets:
            participant = self.participant_by_name(name)
            self.participant_activate(participant)
            self.frame_dimension(participant.lifeline.center_x(), extra_padding=True)

        self.current_position_y += STATEMENT_OFFSET_Y

    def handle_deactivate(self, statement: seqast.DeactivateStatement):
        for name in statement.targets:
            participant = self.participant_by_name(name)
            assert participant.activation_stack, "participant not activated"
            self.participant_deactivate(participant)
            self.position_marker_update(participant.center_marker)
            self.frame_dimension(participant.lifeline.center_x(), extra_padding=True)

        self.current_position_y += STATEMENT_OFFSET_Y

    def handle_found_message(self, statement: seqast.FoundMessageStatement):
        assert statement.activation in (seqast.MessageActivation.REGULAR, seqast.MessageActivation.ACTIVATE), \
            f"{statement.activation} not supported for found message"

        receiver = self.participant_by_name(statement.receiver)
        width = statement.width or FOUND_LOST_MESSAGE_DEFAULT_WIDTH

        if statement.from_direction == seqast.MessageDirection.LEFT:
            source_x = receiver.lifeline.center_x() - width
            marker = receiver.left_marker
            target_anchor = drawio.TargetAnchor.ACTIVATION_TOP_LEFT
            source_anchor = drawio.SourceAnchor.FOUND_DOT_RIGHT
        elif statement.from_direction == seqast.MessageDirection.RIGHT:
            source_x = receiver.lifeline.center_x() + width
            marker = receiver.right_marker
            target_anchor = drawio.TargetAnchor.ACTIVATION_TOP_RIGHT
            source_anchor = drawio.SourceAnchor.FOUND_DOT_LEFT
        else:
            raise NotImplementedError()

        # activation before message
        if statement.activation == seqast.MessageActivation.ACTIVATE:
            self.position_marker_ensure_spacing(marker, MESSAGE_MIN_SPACING - MESSAGE_ANCHOR_DY)
            self.participant_activate(receiver, source_x)
            self.current_position_y += MESSAGE_ANCHOR_DY
        else:
            self.position_marker_ensure_spacing(marker, MESSAGE_MIN_SPACING)

        # actual message
        bullet = drawio.LostFoundDot(self.page)
        bullet.set_position(source_x, self.current_position_y)
        target = receiver.activation_stack[-1] if receiver.activation_stack else receiver.lifeline
        message = drawio.Message(bullet, target, statement.text)
        message.points.append(drawio.Point((source_x + receiver.lifeline.center_x()) / 2, self.current_position_y))
        message.line_style = statement.line_style
        message.arrow_style = statement.arrow_style
        message.source_anchor = source_anchor

        if statement.activation == seqast.MessageActivation.ACTIVATE:
            message.target_anchor = target_anchor

        self.position_marker_update(marker)

        # layout
        self.current_position_y += STATEMENT_OFFSET_Y
        self.frame_dimension(source_x, receiver.lifeline.center_x(), extra_padding=True)

    def handle_lost_message(self, statement: seqast.LostMessageStatement):
        assert statement.activation in (seqast.MessageActivation.REGULAR, seqast.MessageActivation.DEACTIVATE), \
            f"{statement.activation} not supported for found message"

        sender = self.participant_by_name(statement.sender)
        width = statement.width or FOUND_LOST_MESSAGE_DEFAULT_WIDTH

        if statement.to_direction == seqast.MessageDirection.LEFT:
            source_x = sender.lifeline.center_x() - width
            marker = sender.left_marker
            source_anchor = drawio.SourceAnchor.ACTIVATION_BOTTOM_LEFT
            target_anchor = drawio.TargetAnchor.LOST_DOT_RIGHT
        elif statement.to_direction == seqast.MessageDirection.RIGHT:
            source_x = sender.lifeline.center_x() + width
            marker = sender.right_marker
            source_anchor = drawio.SourceAnchor.ACTIVATION_BOTTOM_RIGHT
            target_anchor = drawio.TargetAnchor.LOST_DOT_LEFT
        else:
            raise NotImplementedError()

        self.position_marker_ensure_spacing(marker, MESSAGE_MIN_SPACING)

        # actual message
        bullet = drawio.LostFoundDot(self.page)
        bullet.set_position(source_x, self.current_position_y)
        source = sender.activation_stack[-1] if sender.activation_stack else sender.lifeline
        message = drawio.Message(source, bullet, statement.text)
        message.line_style = statement.line_style
        message.arrow_style = statement.arrow_style
        message.target_anchor = target_anchor

        if statement.activation == seqast.MessageActivation.DEACTIVATE:
            message.source_anchor = source_anchor

        self.position_marker_update(marker)

        # deactivation after message
        if statement.activation == seqast.MessageActivation.DEACTIVATE:
            assert sender.activation_stack, "sender not activated"
            self.current_position_y += MESSAGE_ANCHOR_DY
            self.participant_deactivate(sender)
            self.position_marker_update(sender.center_marker)

        # layout
        self.current_position_y += STATEMENT_OFFSET_Y
        self.frame_dimension(source_x, sender.lifeline.center_x(), extra_padding=True)

    def handle_message(self, statement: seqast.MessageStatement):
        if statement.sender == statement.receiver:
            self.handle_self_call(statement)
            return

        sender = self.participant_by_name(statement.sender)
        receiver = self.participant_by_name(statement.receiver)
        min_spacing = MESSAGE_MIN_SPACING

        # activation before message
        if statement.activation == seqast.MessageActivation.ACTIVATE:
            min_spacing -= MESSAGE_ANCHOR_DY
        if statement.activation == seqast.MessageActivation.FIREFORGET:
            min_spacing -= FIREFORGET_ACTIVATION_HEIGHT / 2

        self.position_marker_ensure_spacing_between(sender, receiver, min_spacing)

        if statement.activation == seqast.MessageActivation.ACTIVATE:
            self.participant_activate(receiver, sender.lifeline.center_x())
            self.current_position_y += MESSAGE_ANCHOR_DY
        if statement.activation == seqast.MessageActivation.FIREFORGET:
            self.participant_activate(receiver, sender.lifeline.center_x())
            self.current_position_y += FIREFORGET_ACTIVATION_HEIGHT / 2

        # actual message
        source = sender.activation_stack[-1] if sender.activation_stack else sender.lifeline
        target = receiver.activation_stack[-1] if receiver.activation_stack else receiver.lifeline

        message = drawio.Message(source, target, statement.text)
        message.line_style = statement.line_style
        message.arrow_style = statement.arrow_style

        if statement.activation == seqast.MessageActivation.ACTIVATE:
            message.target_anchor = drawio.TargetAnchor.ACTIVATION_TOP_LEFT if sender.index < receiver.index else drawio.TargetAnchor.ACTIVATION_TOP_RIGHT
        elif statement.activation == seqast.MessageActivation.DEACTIVATE:
            message.source_anchor = drawio.SourceAnchor.ACTIVATION_BOTTOM_RIGHT if sender.index < receiver.index else drawio.SourceAnchor.ACTIVATION_BOTTOM_LEFT
        else:
            message.points.append(drawio.Point(
                x=(sender.lifeline.center_x() + receiver.lifeline.center_x()) / 2,
                y=self.current_position_y
            ))

        self.position_marker_update_between(sender, receiver)

        # deactivation after message
        if statement.activation == seqast.MessageActivation.DEACTIVATE:
            assert sender.activation_stack, "sender not activated"
            self.current_position_y += MESSAGE_ANCHOR_DY
            self.participant_deactivate(sender)
            self.position_marker_update(sender.center_marker)
        if statement.activation == seqast.MessageActivation.FIREFORGET:
            self.current_position_y += FIREFORGET_ACTIVATION_HEIGHT / 2
            self.participant_deactivate(receiver)
            self.position_marker_update(receiver.center_marker)

        # layout
        self.current_position_y += STATEMENT_OFFSET_Y
        self.frame_dimension(sender.lifeline.center_x(), receiver.lifeline.center_x(), extra_padding=True)

    def handle_self_call(self, statement: seqast.MessageStatement):
        assert statement.sender == statement.receiver
        assert statement.activation in (seqast.MessageActivation.REGULAR, seqast.MessageActivation.ACTIVATE,
                                        seqast.MessageActivation.FIREFORGET), \
            f"{statement.activation} not supported for self call"

        participant = self.participant_by_name(statement.sender)

        if participant.activation_stack:
            from_activation = participant.activation_stack[-1]
        else:
            from_activation = participant.lifeline

        self.current_position_y += STATEMENT_OFFSET_Y

        # activation for self call
        if statement.activation in (seqast.MessageActivation.ACTIVATE, seqast.MessageActivation.FIREFORGET):
            self.participant_activate(participant)
            to_activation = participant.activation_stack[-1]
        else:
            to_activation = from_activation

        if isinstance(to_activation, drawio.Activation):
            to_activation_dx = to_activation.dx
        else:
            to_activation_dx = 0

        # create self call message
        message = drawio.Message(from_activation, to_activation, statement.text)
        message.line_style = statement.line_style
        message.arrow_style = statement.arrow_style

        activation_x = participant.lifeline.center_x() + to_activation_dx

        if to_activation_dx >= 0:
            self_call_x = activation_x + SELF_CALL_MESSAGE_DX
            frame_x = self_call_x + SELF_CALL_MIN_TEXT_WIDTH
            message.text_alignment = drawio.TextAlignment.MIDDLE_LEFT
        else:
            self_call_x = activation_x - SELF_CALL_MESSAGE_DX
            frame_x = self_call_x - SELF_CALL_MIN_TEXT_WIDTH
            message.text_alignment = drawio.TextAlignment.MIDDLE_RIGHT

        message.points.append(drawio.Point(
            x=self_call_x,
            y=self.current_position_y - STATEMENT_OFFSET_Y,
        ))

        message.points.append(drawio.Point(
            x=self_call_x,
            y=self.current_position_y + STATEMENT_OFFSET_Y
        ))

        self.current_position_y += 2 * STATEMENT_OFFSET_Y

        # deactivate after self call
        if statement.activation == seqast.MessageActivation.FIREFORGET:
            self.participant_deactivate(participant)
            self.current_position_y += STATEMENT_OFFSET_Y

        self.frame_dimension(participant.lifeline.center_x(), frame_x, extra_padding=True)

    def handle_frame(self, statement: seqast.FrameStatement):
        frame = self.frame_open(statement.title, statement.text)
        self.process_statements(statement.inner)

        for section in statement.sections:
            self.frame_section(frame, section.text)
            self.process_statements(section.inner)

        self.frame_close(frame)

    def handle_note(self, statement: seqast.NoteStatement):
        participant = self.participant_by_name(statement.target)

        note = drawio.Note(self.page, statement.text)
        note.x = participant.lifeline.center_x() + (statement.dx or 0)
        note.y = self.current_position_y + (statement.dy or 0)
        note.width = statement.width or NOTE_DEFAULT_WIDTH
        note.height = statement.height or NOTE_DEFAULT_HEIGHT

    def handle_vertical_offset(self, statement: seqast.VerticalOffsetStatement):
        self.current_position_y += statement.offset

        for marker in self.position_marker_all():
            marker.y += statement.offset

    def handle_extend_frame(self, statement: seqast.ExtendFrameStatement):
        dimensions = self.frame_dimension_stack[-1]
        assert dimensions.min_x is not None and dimensions.max_x is not None, "cannot extend empty frame"

        if statement.extend >= 0:
            dimensions.max_x += statement.extend
        else:
            dimensions.min_x += statement.extend

    def frame_open(self, title: str, text: Optional[str] = None) -> drawio.Frame:
        # create frame
        self.current_position_y += CONTROL_FRAME_SPACING_BEFORE

        frame = drawio.Frame(self.page, title)
        frame.y = self.current_position_y
        frame.box_width = CONTROL_FRAME_BOX_WIDTH
        frame.box_height = CONTROL_FRAME_BOX_HEIGHT

        # push frame stack
        dimension = FrameDimension()
        self.frame_dimension_stack.append(dimension)

        # handle text
        if text:
            text = drawio.Text(self.page, frame, f'[{text}]')
            text.alignment = drawio.TextAlignment.TOP_LEFT
            text.x = 10
            text.y = CONTROL_FRAME_BOX_HEIGHT + 5

            self.current_position_y += CONTROL_FRAME_BOX_HEIGHT + CONTROL_FRAME_LABEL_HEIGHT
        else:
            self.current_position_y += CONTROL_FRAME_BOX_HEIGHT + STATEMENT_OFFSET_Y

        self.position_marker_update_all(-STATEMENT_OFFSET_Y)

        return frame

    def frame_close(self, frame: drawio.Frame):
        # set frame height
        frame.height = self.current_position_y - frame.y

        # positioning on frame end
        self.current_position_y += STATEMENT_OFFSET_Y
        self.position_marker_update_all()
        self.current_position_y += CONTROL_FRAME_SPACING_AFTER

        # pop frame stack
        dimension = self.frame_dimension_stack.pop()

        # set frame width
        assert dimension.min_x is not None and dimension.max_x is not None, "unknown frame dimension"
        frame.x = dimension.min_x - CONTROL_FRAME_PADDING
        frame.width = dimension.max_x + CONTROL_FRAME_PADDING - frame.x

        # update dimension for parent frame
        self.frame_dimension(frame.x, frame.x + frame.width)

    def frame_section(self, frame: drawio.Frame, text: Optional[str] = None):
        # create separator
        separator = drawio.Separator(frame)
        separator.y = self.current_position_y - frame.y

        # handle text
        if text:
            text = drawio.Text(self.page, frame, f'[{text}]')
            text.alignment = drawio.TextAlignment.TOP_LEFT
            text.x = 10
            text.y = separator.y + 5

            self.current_position_y += CONTROL_FRAME_LABEL_HEIGHT
        else:
            self.current_position_y += STATEMENT_OFFSET_Y

        self.position_marker_update_all(-STATEMENT_OFFSET_Y)

    def frame_dimension(self, *x: float, extra_padding: bool = False):
        dimension = self.frame_dimension_stack[-1]
        extra_padding_val = CONTROL_FRAME_ACTIVITY_EXTRA_PADDING if extra_padding else 0

        if dimension.min_x is None:
            dimension.min_x = min(x) - extra_padding_val
        else:
            dimension.min_x = min(dimension.min_x, min(x) - extra_padding_val)

        if dimension.max_x is None:
            dimension.max_x = max(x) + extra_padding_val
        else:
            dimension.max_x = max(dimension.max_x, max(x) + extra_padding_val)

    def participant_activate(self, participant: ParticipantInfo, activator_x: Optional[float] = None):
        activation = drawio.Activation(participant.lifeline)
        activation.y = self.current_position_y

        if not participant.activation_stack:
            # if participant is not active we always start in the middle
            activation.dx = 0

        elif len(participant.activation_stack) == 1:
            # if participant is activated once, we consider the location of the activator
            if activator_x is None or activator_x > participant.lifeline.center_x():
                next_dx = ACTIVATION_STACK_OFFSET_X
            else:
                next_dx = -ACTIVATION_STACK_OFFSET_X

            activation.dx = next_dx

        else:
            # if participant is activated multiple times, we keep stacking into the same direction
            if participant.activation_stack[-1].dx > participant.activation_stack[-2].dx:
                next_dx = ACTIVATION_STACK_OFFSET_X
            else:
                next_dx = -ACTIVATION_STACK_OFFSET_X

            activation.dx = participant.activation_stack[-1].dx + next_dx

        participant.activation_stack.append(activation)

    def participant_deactivate(self, participant: ParticipantInfo):
        activation = participant.activation_stack.pop()
        activation.height = self.current_position_y - activation.y

    def participant_by_name(self, name: str) -> ParticipantInfo:
        return next((p for p in self.participants if p.name == name), None)

    def position_marker_ensure_spacing_between(self, first: ParticipantInfo, second: ParticipantInfo,
                                               required_spacing: float):
        for marker in self.position_marker_between(first, second):
            self.position_marker_ensure_spacing(marker, required_spacing)

    def position_marker_ensure_spacing(self, marker: PositionMarker, required_spacing: float):
        current_spacing = (self.current_position_y - marker.y)

        if current_spacing < required_spacing:
            self.current_position_y += required_spacing - current_spacing

    def position_marker_update_between(self, first: ParticipantInfo, second: ParticipantInfo):
        for marker in self.position_marker_between(first, second):
            self.position_marker_update(marker)

    def position_marker_update_all(self, dy: float = 0):
        for marker in self.position_marker_all():
            self.position_marker_update(marker, dy)

    def position_marker_update(self, marker: PositionMarker, dy: float = 0):
        marker.y = self.current_position_y + dy

    def position_marker_between(self, first: ParticipantInfo, second: ParticipantInfo) \
            -> Iterable[PositionMarker]:
        start_index = min(first.index, second.index)
        end_index = max(first.index, second.index)

        for participant in self.participants[start_index:end_index + 1]:
            if participant.index != start_index and participant.index != end_index:
                yield participant.center_marker

            if participant.index != end_index:
                yield participant.right_marker

    def position_marker_all(self) -> Iterable[PositionMarker]:
        if self.participants:
            yield self.participants[0].left_marker

        for participant in self.participants:
            yield participant.center_marker
            yield participant.right_marker
