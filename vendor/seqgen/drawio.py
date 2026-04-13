import os
import xml.etree.ElementTree as ET

from dataclasses import dataclass
from enum import auto, Enum
from typing import List, Dict, Optional

ACTIVATION_WIDTH = 10
MESSAGE_ANCHOR_DY = 5

StyleAttributes = Dict[str, Optional[str]]


class File:
    def __init__(self):
        self.pages: List[Page] = []

    def xml(self) -> ET.Element:
        root = ET.Element("mxfile", attrib={
            'host': 'seqgen',
            'agent': 'seqgen',
            'version': '26.2.2',
        })

        for page in self.pages:
            page.xml(root)

        return root

    def xml_pretty(self) -> str:
        # manually pretty print output to stay compatible with Python 3.8
        xml_str = ET.tostring(self.xml(), encoding='utf-8', xml_declaration=False).decode('utf-8')
        output = ''
        indent = 0

        for line in xml_str.replace('>', '>\n').split('\n'):
            if not line:
                continue

            if line.startswith('</'):
                indent -= 2

            output += (' ' * indent) + line + '\n'

            if not line.startswith('</') and not line.endswith('/>'):
                indent += 2

        return output


class Page:
    def __init__(self, file: File, name: str):
        self.name = name
        self.id = create_id()
        self.objects: List[Object] = []
        file.pages.append(self)

    def xml(self, xml_parent: ET.Element) -> ET.Element:
        diagram = ET.SubElement(xml_parent, 'diagram', attrib={
            'name': self.name,
            'id': self.id,
        })

        graph_model = ET.SubElement(diagram, 'mxGraphModel', attrib={
            'dx': '0',
            'dy': '0',
            'grid': '1',
            'gridSize': '10',
            'guides': '1',
            'tooltips': '1',
            'connect': '1',
            'arrows': '1',
            'fold': '1',
            'page': '0',
            'pageScale': '1',
            'pageWidth': '851',
            'pageHeight': '1100',
            'background': '#ffffff',
            'math': '0',
            'shadow': '0',
        })

        root = ET.SubElement(graph_model, 'root')

        ET.SubElement(root, 'mxCell', attrib={'id': '0'})
        ET.SubElement(root, 'mxCell', attrib={'id': '1', 'parent': '0'})

        for obj in self.objects:
            obj.xml(root)

        return diagram


class Object:
    def __init__(self, page: Page, parent: Optional['Object'], value: str):
        self.id = create_id()
        self.page = page
        self.parent = parent
        self.value = value
        page.objects.append(self)

    def xml(self, xml_parent: ET.Element) -> ET.Element:
        style = ''

        for key, value in self.style().items():
            if value is not None:
                style += f'{key}={value};'
            else:
                style += f'{key};'

        attr = {
            'id': self.id,
            'value': self.value,
            'parent': self.parent.id if self.parent else '1',
            'style': style,
        }

        attr.update(self.attr())

        cell = ET.SubElement(xml_parent, 'mxCell', attrib=attr)
        return cell

    def style(self) -> StyleAttributes:
        return {}

    def attr(self) -> Dict[str, str]:
        return {}


class ObjectWithAbsoluteGeometry(Object):
    def __init__(self, page: Page, parent: Optional['Object'], value: str):
        super().__init__(page, parent, value)

        self.x: float = 0
        self.y: float = 0
        self.width: float = 0
        self.height: float = 0

    def center_x(self):
        return self.x + (self.width / 2)

    def xml(self, xml_parent: ET.Element) -> ET.Element:
        cell = super().xml(xml_parent)

        ET.SubElement(cell, 'mxGeometry', attrib={
            'x': str(self.x),
            'y': str(self.y),
            'width': str(self.width),
            'height': str(self.height),
            'as': 'geometry'
        })

        return cell


class Text(ObjectWithAbsoluteGeometry):
    def __init__(self, page: Page, parent: Optional['Object'], value: str):
        super().__init__(page, parent, value)

        self.width: float = 100
        self.height: float = 20
        self.alignment = TextAlignment.MIDDLE_LEFT

    def attr(self) -> Dict[str, str]:
        return {
            'vertex': '1'
        }

    def style(self) -> StyleAttributes:
        style = {
            'text': None,
            'html': '1',
            'rounded': '0',
            'spacing': '0',
            'labelBackgroundColor': 'default',
        }

        style.update(self.alignment.style())

        return style


class Frame(ObjectWithAbsoluteGeometry):
    def __init__(self, page: Page, value: str):
        super().__init__(page, None, value)

        self.box_width: float = 160
        self.box_height: float = 30

    def attr(self) -> Dict[str, str]:
        return {
            'vertex': '1'
        }

    def style(self) -> StyleAttributes:
        return {
            'shape': 'umlFrame',
            'whiteSpace': 'wrap',
            'html': '1',
            'pointerEvents': '0',
            'width': str(self.box_width),
            'height': str(self.box_height),
        }


class Separator(Object):
    def __init__(self, frame: Frame):
        super().__init__(frame.page, None, '')

        self.frame = frame
        self.y: float = 0

    def attr(self) -> Dict[str, str]:
        return {
            'edge': '1',
            'source': self.frame.id,
            'target': self.frame.id,
        }

    def style(self) -> StyleAttributes:
        rel_y = self.y / self.frame.height

        return {
            'html': '1',
            'endArrow': 'none',
            'dashed': '1',
            'rounded': '0',
            'entryX': '1',
            'entryY': f"{rel_y:.3f}",
            'entryDx': '0',
            'entryDy': '0',
            'entryPerimeter': '0',
            'exitX': '0',
            'exitY': f"{rel_y:.3f}",
            'exitDx': '0',
            'exitDy': '0',
            'exitPerimeter': '0',
        }

    def xml(self, xml_parent: ET.Element) -> ET.Element:
        cell = super().xml(xml_parent)

        geometry = ET.SubElement(cell, 'mxGeometry', attrib={
            'relative': '1',
            'as': 'geometry'
        })

        ET.SubElement(geometry, 'mxPoint', attrib={'as': 'targetPoint'})
        ET.SubElement(geometry, 'mxPoint', attrib={'as': 'sourcePoint'})

        return cell


class Lifeline(ObjectWithAbsoluteGeometry):
    def __init__(self, page: Page, value: str):
        super().__init__(page, None, value)

        self.width = 100
        self.height = 300
        self.box_height = 40

    def attr(self) -> Dict[str, str]:
        return {
            'vertex': '1'
        }

    def style(self) -> StyleAttributes:
        return {
            'shape': 'umlLifeline',
            'perimeter': 'lifelinePerimeter',
            'whiteSpace': 'wrap',
            'html': '1',
            'container': '1',
            'dropTarget': '0',
            'collapsible': '0',
            'recursiveResize': '0',
            'outlineConnect': '0',
            'portConstraint': 'eastwest',
            'newEdgeStyle': '{"curved":0,"rounded":0}',
            'size': str(self.box_height),
        }


class Activation(Object):
    def __init__(self, lifeline: Lifeline):
        super().__init__(lifeline.page, lifeline, '')

        self.lifeline = lifeline
        self.dx: float = 0
        self.y: float = 90
        self.height: float = 100

    def attr(self) -> Dict[str, str]:
        return {
            'vertex': '1'
        }

    def style(self) -> StyleAttributes:
        return {
            'html': '1',
            'points': '[[0,0,0,0,5],[0,1,0,0,-5],[1,0,0,0,5],[1,1,0,0,-5]]',
            'perimeter': 'orthogonalPerimeter',
            'outlineConnect': '0',
            'targetShapes': 'umlLifeline',
            'portConstraint': 'eastwest',
            'newEdgeStyle': '{"curved":0,"rounded":0}',
        }

    def xml(self, xml_parent: ET.Element) -> ET.Element:
        cell = super().xml(xml_parent)

        ET.SubElement(cell, 'mxGeometry', attrib={
            'x': str((self.lifeline.width / 2) - (ACTIVATION_WIDTH / 2) + self.dx),
            'y': str(self.y),
            'width': str(ACTIVATION_WIDTH),
            'height': str(self.height),
            'as': 'geometry'
        })

        return cell


class Message(Object):
    def __init__(self, source: Object, target: Object, value: str):
        super().__init__(source.page, None, value)
        self.source = source
        self.target = target

        self.source_anchor = SourceAnchor.NONE
        self.target_anchor = TargetAnchor.NONE
        self.line_style = LineStyle.SOLID
        self.arrow_style = ArrowStyle.BLOCK
        self.text_alignment = TextAlignment.BOTTOM_CENTER
        self.points: List[Point] = []

    def attr(self) -> Dict[str, str]:
        return {
            'edge': '1',
            'source': self.source.id,
            'target': self.target.id,
        }

    def style(self) -> StyleAttributes:
        style = {
            'html': '1',
            'curved': '0',
            'rounded': '0',
        }

        if self.text_alignment in (TextAlignment.MIDDLE_LEFT, TextAlignment.TOP_LEFT):
            style['spacingLeft'] = '2'
        if self.text_alignment == TextAlignment.MIDDLE_RIGHT:
            style['spacingRight'] = '2'

        style.update(self.text_alignment.style())
        style.update(self.arrow_style.style())
        style.update(self.line_style.style())
        style.update(self.source_anchor.style())
        style.update(self.target_anchor.style())

        return style

    def xml(self, xml_parent: ET.Element) -> ET.Element:
        cell = super().xml(xml_parent)

        geometry = ET.SubElement(cell, 'mxGeometry', attrib={
            'relative': '1',
            'as': 'geometry'
        })

        ET.SubElement(geometry, 'mxPoint', attrib={'as': 'sourcePoint'})
        ET.SubElement(geometry, 'mxPoint', attrib={'as': 'targetPoint'})

        if self.points:
            array = ET.SubElement(geometry, 'Array', attrib={'as': 'points'})

            for point in self.points:
                ET.SubElement(array, 'mxPoint', attrib={'x': str(point.x), 'y': str(point.y)})

        return cell


class LostFoundDot(ObjectWithAbsoluteGeometry):
    def __init__(self, page: Page):
        super().__init__(page, None, '')

        self.width = 8
        self.height = 8

    def set_position(self, center_x: float, center_y: float):
        self.x = center_x - (self.width / 2)
        self.y = center_y - (self.height / 2)

    def attr(self) -> Dict[str, str]:
        return {
            'vertex': '1',
        }

    def style(self) -> StyleAttributes:
        return {
            'ellipse': None,
            'html': '1',
            'aspect': 'fixed',
            'fillColor': '#000000',
        }


class Note(ObjectWithAbsoluteGeometry):
    def __init__(self, page: Page, value: str):
        super().__init__(page, None, value)

        self.width: float = 120
        self.height: float = 60

    def attr(self) -> Dict[str, str]:
        return {
            'vertex': '1'
        }

    def style(self) -> StyleAttributes:
        return {
            'shape': 'note',
            'whiteSpace': 'wrap',
            'html': '1',
            'backgroundOutline': '1',
            'size': '10',
            'align': 'left',
            'spacing': '8',
        }


@dataclass
class Point:
    x: float
    y: float


class SourceAnchor(Enum):
    NONE = auto()
    ACTIVATION_BOTTOM_LEFT = auto()
    ACTIVATION_BOTTOM_RIGHT = auto()
    FOUND_DOT_LEFT = auto()
    FOUND_DOT_RIGHT = auto()

    def style(self) -> StyleAttributes:
        style_map = {
            SourceAnchor.NONE: {},
            SourceAnchor.ACTIVATION_BOTTOM_LEFT: {
                'exitX': '0',
                'exitY': '1',
                'exitDx': '0',
                'exitDy': str(-MESSAGE_ANCHOR_DY),
            },
            SourceAnchor.ACTIVATION_BOTTOM_RIGHT: {
                'exitX': '1',
                'exitY': '1',
                'exitDx': '0',
                'exitDy': str(-MESSAGE_ANCHOR_DY),
            },
            SourceAnchor.FOUND_DOT_LEFT: {
                'exitX': '0',
                'exitY': '0.5',
                'exitDx': '0',
                'exitDy': '0',
            },
            SourceAnchor.FOUND_DOT_RIGHT: {
                'exitX': '1',
                'exitY': '0.5',
                'exitDx': '0',
                'exitDy': '0',
            },
        }

        return style_map[self]


class TargetAnchor(Enum):
    NONE = auto()
    ACTIVATION_TOP_LEFT = auto()
    ACTIVATION_TOP_RIGHT = auto()
    LOST_DOT_LEFT = auto()
    LOST_DOT_RIGHT = auto()

    def style(self) -> StyleAttributes:
        style_map = {
            TargetAnchor.NONE: {},
            TargetAnchor.ACTIVATION_TOP_LEFT: {
                'entryX': '0',
                'entryY': '0',
                'entryDx': '0',
                'entryDy': str(MESSAGE_ANCHOR_DY),
            },
            TargetAnchor.ACTIVATION_TOP_RIGHT: {
                'entryX': '1',
                'entryY': '0',
                'entryDx': '0',
                'entryDy': str(MESSAGE_ANCHOR_DY),
            },
            TargetAnchor.LOST_DOT_LEFT: {
                'entryX': '0',
                'entryY': '0.5',
                'entryDx': '0',
                'entryDy': '0',
            },
            TargetAnchor.LOST_DOT_RIGHT: {
                'entryX': '1',
                'entryY': '0.5',
                'entryDx': '0',
                'entryDy': '0',
            },
        }

        return style_map[self]


class LineStyle(Enum):
    SOLID = auto()
    DASHED = auto()

    def style(self) -> StyleAttributes:
        style_map = {
            LineStyle.SOLID: {
                'dashed': '0',
            },
            LineStyle.DASHED: {
                'dashed': '1',
            },
        }

        return style_map[self]


class ArrowStyle(Enum):
    BLOCK = auto()
    OPEN = auto()

    def style(self) -> StyleAttributes:
        style_map = {
            ArrowStyle.BLOCK: {
                'endArrow': 'block',
            },
            ArrowStyle.OPEN: {
                'endArrow': 'open',
            },
        }

        return style_map[self]


class TextAlignment(Enum):
    BOTTOM_CENTER = auto()
    MIDDLE_LEFT = auto()
    MIDDLE_RIGHT = auto()
    TOP_LEFT = auto()

    def style(self) -> StyleAttributes:
        style_map = {
            TextAlignment.BOTTOM_CENTER: {
                'align': 'center',
                'verticalAlign': 'bottom',
            },
            TextAlignment.MIDDLE_LEFT: {
                'align': 'left',
                'verticalAlign': 'middle',
            },
            TextAlignment.MIDDLE_RIGHT: {
                'align': 'right',
                'verticalAlign': 'middle',
            },
            TextAlignment.TOP_LEFT: {
                'align': 'left',
                'verticalAlign': 'top',
            },
        }

        return style_map[self]


# Live reloading in draw.io does not work well if an object ID is suddenly used for another type of object.
# On the other side, the integration test require a predictable output.
# Using deterministic IDs with a random prefix which can be overridden for testing seems like a good trade-off.
next_id = 1
id_prefix = os.getenv('SEQGEN_ID_PREFIX', os.urandom(4).hex() + '-')


def create_id() -> str:
    global next_id
    result = next_id
    next_id += 1
    return id_prefix + str(result)
