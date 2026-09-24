"""Interactive Qt Graphics View visualization engine for OSPF topology.

Features:
- Native smooth zooming (mouse wheel + buttons) and panning.
- Draggable router nodes with live curved parallel edge updates.
- Parallel edges rendered with distinct curvature offsets so lines never overlap.
- Rich edge labels displaying:
  - Local IP (side A) and Remote IP (side B)
  - Cost metrics (A -> B and B -> A)
  - Subnet prefix (e.g. 10.0.0.12/30)
- Visual styling for:
  - Normal bidirectional links (green/slate)
  - Asymmetric cost links (orange/amber)
  - Incomplete/unmatched links (dashed red)
  - Missing Router-LSA nodes (dashed border, warning icon/badge)
- Click & Hover selection signals to trigger Inspector details.
- High quality PNG and SVG vector export.
"""

from __future__ import annotations

import math
from typing import Dict, List, Tuple, Optional, Callable
from PySide6.QtCore import Qt, QPointF, QRectF, Signal, QObject
from PySide6.QtGui import (
    QPainter,
    QPen,
    QBrush,
    QColor,
    QFont,
    QPainterPath,
    QWheelEvent,
    QMouseEvent,
    QTransform,
)
from PySide6.QtWidgets import (
    QGraphicsView,
    QGraphicsScene,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsTextItem,
    QGraphicsDropShadowEffect,
)
from PySide6.QtSvg import QSvgGenerator

from ospf_viz.models import OSPFRouter, OSPFLink, LinkMatchStatus


class GraphSelectionListener(QObject):
    """Bridge for Qt signals from graphics items to GUI inspector."""
    node_selected = Signal(str)           # router_id
    link_selected = Signal(str)           # link_id
    node_hovered = Signal(str)
    link_hovered = Signal(str)
    node_moved = Signal(str, float, float) # router_id, x, y


class NodeItem(QGraphicsItem):
    """Interactive Draggable Router Node in QGraphicsScene."""

    def __init__(
        self,
        router: OSPFRouter,
        listener: GraphSelectionListener,
        radius: float = 38.0,
        font_size: int = 11,
    ):
        super().__init__()
        self.router = router
        self.listener = listener
        self.radius = radius
        self.font_size = font_size

        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setAcceptHoverEvents(True)

        self.connected_edges: List[EdgeItem] = []

    def boundingRect(self) -> QRectF:
        pad = 8.0
        r = self.radius
        return QRectF(-r - pad, -r - pad, (r + pad) * 2, (r + pad) * 2)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.radius

        # Colors based on node status
        if not self.router.has_lsa:
            # LSA Missing node
            bg_color = QColor("#fee2e2")      # Light red
            border_color = QColor("#ef4444")  # Red
            border_pen = QPen(border_color, 2.5, Qt.PenStyle.DashLine)
        elif self.isSelected():
            bg_color = QColor("#dbeafe")      # Light blue highlight
            border_color = QColor("#2563eb")  # Blue
            border_pen = QPen(border_color, 3.0)
        else:
            bg_color = QColor("#f0fdf4")      # Subtle green tint / clean white
            border_color = QColor("#059669")  # Emerald/slate border
            border_pen = QPen(border_color, 2.2)

        painter.setPen(border_pen)
        painter.setBrush(QBrush(bg_color))
        painter.drawEllipse(-r, -r, r * 2, r * 2)

        # Draw Router ID text
        font = QFont("Helvetica Neue", self.font_size, QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(QPen(QColor("#1e293b")))

        text_rect = QRectF(-r, -r + 10, r * 2, 22)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, self.router.router_id)

        # Status badge or Subtitle
        sub_font = QFont("Helvetica Neue", max(7, self.font_size - 3))
        painter.setFont(sub_font)

        if not self.router.has_lsa:
            painter.setPen(QPen(QColor("#dc2626")))
            sub_rect = QRectF(-r, 8, r * 2, 16)
            painter.drawText(sub_rect, Qt.AlignmentFlag.AlignCenter, "[LSA Missing]")
        else:
            painter.setPen(QPen(QColor("#64748b")))
            area_str = self.router.areas[0] if self.router.areas else "area0"
            sub_rect = QRectF(-r, 10, r * 2, 16)
            painter.drawText(sub_rect, Qt.AlignmentFlag.AlignCenter, area_str)

    def itemChange(self, change: QGraphicsItem.GraphicsItemChange, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            for edge in self.connected_edges:
                edge.update_positions()
            self.listener.node_moved.emit(self.router.router_id, self.pos().x(), self.pos().y())
        return super().itemChange(change, value)

    def mousePressEvent(self, event: QMouseEvent):
        self.listener.node_selected.emit(self.router.router_id)
        super().mousePressEvent(event)

    def hoverEnterEvent(self, event):
        self.listener.node_hovered.emit(self.router.router_id)
        super().hoverEnterEvent(event)


class EdgeItem(QGraphicsPathItem):
    """
    Curved edge between two router nodes representing an OSPF Link.
    Renders with curvature offset to display parallel links distinctly without overlapping.
    """

    def __init__(
        self,
        link: OSPFLink,
        node_a: NodeItem,
        node_b: NodeItem,
        curve_index: int,
        curve_total: int,
        listener: GraphSelectionListener,
        font_size: int = 9,
        curve_spacing: float = 50.0
    ):
        super().__init__()
        self.link = link
        self.node_a = node_a
        self.node_b = node_b
        self.curve_index = curve_index
        self.curve_total = curve_total
        self.listener = listener
        self.font_size = font_size
        self.curve_spacing = curve_spacing

        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setAcceptHoverEvents(True)
        self.setZValue(-1)  # Place edges under nodes

        self.node_a.connected_edges.append(self)
        self.node_b.connected_edges.append(self)

        self.update_positions()

    def update_positions(self) -> None:
        """Calculates curved Bézier path and triggers repaint."""
        p1 = self.node_a.pos()
        p2 = self.node_b.pos()

        dx = p2.x() - p1.x()
        dy = p2.y() - p1.y()
        dist = math.hypot(dx, dy)

        if dist < 1e-4:
            self.setPath(QPainterPath())
            return

        # Unit normal vector perpendicular to link vector
        nx = -dy / dist
        ny = dx / dist

        # Calculate curvature offset
        # For curve_total = 1 -> offset = 0
        # For curve_total = 2 -> offsets: -spacing/2, +spacing/2
        # For curve_total = 3 -> offsets: -spacing, 0, +spacing
        if self.curve_total <= 1:
            offset = 0.0
        else:
            midpoint_shift = (self.curve_total - 1) / 2.0
            offset = (self.curve_index - midpoint_shift) * self.curve_spacing

        # Quadratic Bézier control point
        cx = (p1.x() + p2.x()) / 2.0 + nx * offset
        cy = (p1.y() + p2.y()) / 2.0 + ny * offset

        path = QPainterPath()
        path.moveTo(p1)
        path.quadTo(QPointF(cx, cy), p2)
        self.setPath(path)
        self.ctrl_point = QPointF(cx, cy)
        self.update()

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Style based on link condition
        if self.isSelected():
            color = QColor("#2563eb")  # Blue selection
            width = 3.2
            pen_style = Qt.PenStyle.SolidLine
        elif self.link.status == LinkMatchStatus.ONE_WAY:
            color = QColor("#dc2626")  # Red dashed for one-way
            width = 2.0
            pen_style = Qt.PenStyle.DashLine
        elif self.link.is_asymmetric:
            color = QColor("#d97706")  # Amber/orange for asymmetric
            width = 2.4
            pen_style = Qt.PenStyle.SolidLine
        else:
            color = QColor("#475569")  # Slate gray/dark for normal
            width = 2.0
            pen_style = Qt.PenStyle.SolidLine

        pen = QPen(color, width, pen_style, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(self.path())

        # Render labels along the link
        self._paint_labels(painter)

    def _paint_labels(self, painter: QPainter) -> None:
        """Paints IPs and Metrics along the link."""
        p1 = self.node_a.pos()
        p2 = self.node_b.pos()
        c = getattr(self, "ctrl_point", QPointF((p1.x() + p2.x()) / 2, (p1.y() + p2.y()) / 2))

        # Position along curve:
        # t = 0.25 (near A) -> IP A, metric A->B
        # t = 0.50 (mid)    -> Subnet
        # t = 0.75 (near B) -> IP B, metric B->A
        font = QFont("Helvetica Neue", self.font_size)
        painter.setFont(font)

        def eval_bezier(t: float) -> QPointF:
            x = (1 - t)**2 * p1.x() + 2 * (1 - t) * t * c.x() + t**2 * p2.x()
            y = (1 - t)**2 * p1.y() + 2 * (1 - t) * t * c.y() + t**2 * p2.y()
            return QPointF(x, y)

        # Center label: Subnet
        if self.link.subnet:
            mid_pt = eval_bezier(0.5)
            self._draw_pill_label(painter, mid_pt, self.link.subnet, QColor("#f1f5f9"), QColor("#334155"))

        # Side A label
        pt_a = eval_bezier(0.25)
        text_a_parts = []
        if self.link.ip_a:
            text_a_parts.append(self.link.ip_a)
        if self.link.metric_a_to_b is not None:
            text_a_parts.append(f"cost:{self.link.metric_a_to_b}")
        if text_a_parts:
            self._draw_pill_label(painter, pt_a, " | ".join(text_a_parts), QColor("#ffffff"), QColor("#0f172a"))

        # Side B label
        pt_b = eval_bezier(0.75)
        text_b_parts = []
        if self.link.ip_b:
            text_b_parts.append(self.link.ip_b)
        if self.link.metric_b_to_a is not None:
            text_b_parts.append(f"cost:{self.link.metric_b_to_a}")
        elif self.link.status == LinkMatchStatus.ONE_WAY:
            text_b_parts.append("[no return]")
        if text_b_parts:
            self._draw_pill_label(painter, pt_b, " | ".join(text_b_parts), QColor("#ffffff"), QColor("#0f172a"))

    def _draw_pill_label(self, painter: QPainter, center: QPointF, text: str, bg_color: QColor, text_color: QColor) -> None:
        metrics = painter.fontMetrics()
        text_width = metrics.horizontalAdvance(text)
        text_height = metrics.height()

        padding_x = 5.0
        padding_y = 2.0
        rect = QRectF(
            center.x() - text_width / 2.0 - padding_x,
            center.y() - text_height / 2.0 - padding_y,
            text_width + padding_x * 2.0,
            text_height + padding_y * 2.0
        )

        painter.setPen(QPen(QColor("#cbd5e1"), 0.8))
        painter.setBrush(QBrush(bg_color))
        painter.drawRoundedRect(rect, 3.5, 3.5)

        painter.setPen(QPen(text_color))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    def mousePressEvent(self, event: QMouseEvent):
        self.listener.link_selected.emit(self.link.id)
        super().mousePressEvent(event)

    def hoverEnterEvent(self, event):
        self.listener.link_hovered.emit(self.link.id)
        super().hoverEnterEvent(event)


class InteractiveGraphView(QGraphicsView):
    """
    QGraphicsView with smooth navigation, mouse-wheel zoom, pan,
    and topology visualization controls.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)

        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        self.listener = GraphSelectionListener()

        self.nodes: Dict[str, NodeItem] = {}
        self.edges: List[EdgeItem] = []

        # Configurable display parameters
        self.node_radius = 40.0
        self.node_font_size = 11
        self.edge_font_size = 9
        self.curve_spacing = 55.0

        # Background grid styling
        self.setBackgroundBrush(QBrush(QColor("#f8fafc")))

    def wheelEvent(self, event: QWheelEvent):
        """Zoom in/out towards mouse cursor position."""
        zoom_factor = 1.15
        if event.angleDelta().y() > 0:
            self.scale(zoom_factor, zoom_factor)
        else:
            self.scale(1.0 / zoom_factor, 1.0 / zoom_factor)

    def zoom_in(self) -> None:
        self.scale(1.2, 1.2)

    def zoom_out(self) -> None:
        self.scale(1.0 / 1.2, 1.0 / 1.2)

    def fit_to_screen(self) -> None:
        rect = self.scene.itemsBoundingRect()
        if not rect.isEmpty():
            self.fitInView(rect.adjusted(-50, -50, 50, 50), Qt.AspectRatioMode.KeepAspectRatio)

    def center_on_node(self, router_id: str) -> None:
        if router_id in self.nodes:
            self.centerOn(self.nodes[router_id])

    def render_topology(
        self,
        routers: Dict[str, OSPFRouter],
        links: List[OSPFLink],
        positions: Dict[str, Tuple[float, float]],
        hidden_routers: Optional[set] = None
    ) -> None:
        """Populates the scene with nodes and parallel curved edges, filtering out hidden routers."""
        self.scene.clear()
        self.nodes.clear()
        self.edges.clear()

        hidden = hidden_routers or set()

        # Step 1: Create all visible nodes
        for r_id, router in routers.items():
            if r_id in hidden:
                continue
            node = NodeItem(
                router=router,
                listener=self.listener,
                radius=self.node_radius,
                font_size=self.node_font_size,
            )
            pos = positions.get(r_id, (0.0, 0.0))
            node.setPos(pos[0], pos[1])
            self.scene.addItem(node)
            self.nodes[r_id] = node

        # Step 2: Group links by pair of endpoints to compute curvature offsets
        pair_links: Dict[Tuple[str, str], List[OSPFLink]] = {}
        for link in links:
            if link.router_a in hidden or link.router_b in hidden:
                continue
            pair_key = (min(link.router_a, link.router_b), max(link.router_a, link.router_b))
            if pair_key not in pair_links:
                pair_links[pair_key] = []
            pair_links[pair_key].append(link)

        # Step 3: Create edges with offsets
        for (r1, r2), l_list in pair_links.items():
            if r1 not in self.nodes or r2 not in self.nodes:
                continue
            node1 = self.nodes[r1]
            node2 = self.nodes[r2]
            total_edges = len(l_list)

            for idx, link in enumerate(l_list):
                edge = EdgeItem(
                    link=link,
                    node_a=node1,
                    node_b=node2,
                    curve_index=idx,
                    curve_total=total_edges,
                    listener=self.listener,
                    font_size=self.edge_font_size,
                    curve_spacing=self.curve_spacing
                )
                self.scene.addItem(edge)
                self.edges.append(edge)

        self.fit_to_screen()

    def export_image(self, file_path: str) -> bool:
        """Exports the graph to PNG or SVG."""
        rect = self.scene.itemsBoundingRect().adjusted(-40, -40, 40, 40)
        if rect.isEmpty():
            return False

        if file_path.lower().endswith(".svg"):
            generator = QSvgGenerator()
            generator.setFileName(file_path)
            generator.setSize(rect.size().toSize())
            generator.setViewBox(rect)
            generator.setTitle("OSPF Topology")

            painter = QPainter(generator)
            self.scene.render(painter, QRectF(0, 0, rect.width(), rect.height()), rect)
            painter.end()
            return True
        else:
            from PySide6.QtGui import QImage
            image = QImage(rect.size().toSize(), QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(QColor("#f8fafc"))
            painter = QPainter(image)
            self.scene.render(painter, QRectF(0, 0, rect.width(), rect.height()), rect)
            painter.end()
            return image.save(file_path)
