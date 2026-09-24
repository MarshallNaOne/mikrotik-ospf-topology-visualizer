"""OSPF Topology Visualizer main application window and GUI components."""

from __future__ import annotations

import json
import logging
import sys
from typing import Dict, List, Tuple, Optional
import networkx as nx

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QAction, QIcon, QFont
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QLineEdit,
    QPushButton,
    QLabel,
    QFormLayout,
    QGroupBox,
    QComboBox,
    QSlider,
    QCheckBox,
    QTableWidget,
    QTableWidgetItem,
    QListWidget,
    QListWidgetItem,
    QHeaderView,
    QFileDialog,
    QMessageBox,
    QStatusBar,
    QProgressBar,
    QToolBar,
)

from ospf_viz.models import OSPFRouter, OSPFLink, LinkMatchStatus
from ospf_viz.parser import LSAParser
from ospf_viz.topology import TopologyBuilder
from ospf_viz.layout import TopologyLayoutManager
from ospf_viz.visualization import InteractiveGraphView
from ospf_viz.ssh_client import MikroTikSSHClient

logger = logging.getLogger(__name__)


def show_msg(parent, title: str, text: str, icon: QMessageBox.Icon = QMessageBox.Icon.Information):
    """Shows a safe message dialog using Qt's internal layout instead of macOS native NSAlert."""
    box = QMessageBox(parent)
    box.setOption(QMessageBox.Option.DontUseNativeDialog, True)
    box.setIcon(icon)
    box.setWindowTitle(title)
    box.setText(text)
    box.setStandardButtons(QMessageBox.StandardButton.Ok)
    return box.exec()


class SSHWorker(QThread):
    """Worker thread to fetch LSDB via SSH without blocking the UI."""
    finished = Signal(bool, str, str)  # success, result_data, log_info

    def __init__(self, host: str, port: int, user: str, password: str):
        super().__init__()
        self.host = host
        self.port = port
        self.user = user
        self.password = password

    def run(self):
        try:
            client = MikroTikSSHClient()
            success, output, log_msg = client.fetch_lsa(
                host=self.host,
                port=self.port,
                username=self.user,
                password=self.password
            )
            self.finished.emit(success, output, log_msg or "")
        except Exception as e:
            logger.error("SSHWorker exception: %s", e)
            self.finished.emit(False, f"SSH Error: {e}", "")


class MainWindow(QMainWindow):
    """Main application window for OSPF Topology Visualizer."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("MikroTik OSPF Topology Visualizer (RouterOS 7)")
        self.resize(1380, 880)

        # Core State
        self.parser = LSAParser()
        self.builder = TopologyBuilder()
        self.routers: Dict[str, OSPFRouter] = {}
        self.links: List[OSPFLink] = []
        self.graph = nx.MultiGraph()
        self.saved_positions: Dict[str, Tuple[float, float]] = {}
        self.hidden_routers: set[str] = set()

        self._init_ui()
        self._setup_connections()

    def _init_ui(self):
        # Central Splitter (Left Sidebar: Data & Controls | Center: Graph | Right: Inspector & Logs)
        main_widget = QWidget()
        main_layout = QHBoxLayout(main_widget)
        main_layout.setContentsMargins(4, 4, 4, 4)

        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(self.main_splitter)
        self.setCentralWidget(main_widget)

        # 1. Left Panel (Data Source & Controls)
        left_container = QWidget()
        left_layout = QVBoxLayout(left_container)
        left_layout.setContentsMargins(4, 4, 4, 4)

        self.input_tabs = QTabWidget()
        self._init_manual_tab()
        self._init_ssh_tab()
        left_layout.addWidget(self.input_tabs)

        self._init_graph_controls(left_layout)
        self.main_splitter.addWidget(left_container)

        # 2. Center Panel (Interactive Graph View)
        self.graph_view = InteractiveGraphView(self)
        self.main_splitter.addWidget(self.graph_view)

        # 3. Right Panel (Inspector & Warnings)
        right_container = QWidget()
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(4, 4, 4, 4)

        self._init_inspector(right_layout)
        self.main_splitter.addWidget(right_container)

        # Set splitter sizes
        self.main_splitter.setSizes([340, 720, 320])

        # Status Bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumWidth(160)
        self.progress_bar.setVisible(False)
        self.status_bar.addPermanentWidget(self.progress_bar)
        self.status_bar.showMessage("Ready. Paste LSA output or connect via SSH to visualize.")

        # Toolbar
        self._init_toolbar()

    def _init_manual_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        layout.addWidget(QLabel("Paste output of:"))
        cmd_lbl = QLabel("<code>/routing/ospf/lsa/print detail without-paging</code>")
        cmd_lbl.setTextFormat(Qt.TextFormat.RichText)
        cmd_lbl.setStyleSheet("background: #f1f5f9; padding: 4px; border-radius: 3px;")
        layout.addWidget(cmd_lbl)

        self.manual_text_edit = QTextEdit()
        self.manual_text_edit.setPlaceholderText("Paste LSA output here...")
        layout.addWidget(self.manual_text_edit)

        self.btn_parse_manual = QPushButton("Parse & Build Topology")
        self.btn_parse_manual.setStyleSheet("background-color: #2563eb; color: white; font-weight: bold; padding: 7px;")
        layout.addWidget(self.btn_parse_manual)

        self.input_tabs.addTab(widget, "Manual Input")

    def _init_ssh_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        form = QFormLayout()
        self.ssh_host = QLineEdit()
        self.ssh_host.setPlaceholderText("e.g. 192.168.88.1")
        self.ssh_port = QLineEdit("22")
        self.ssh_user = QLineEdit("admin")
        self.ssh_pass = QLineEdit()
        self.ssh_pass.setEchoMode(QLineEdit.EchoMode.Password)

        form.addRow("Host/IP:", self.ssh_host)
        form.addRow("SSH Port:", self.ssh_port)
        form.addRow("Username:", self.ssh_user)
        form.addRow("Password:", self.ssh_pass)
        layout.addLayout(form)

        self.btn_ssh_fetch = QPushButton("Connect & Fetch LSDB")
        self.btn_ssh_fetch.setStyleSheet("background-color: #059669; color: white; font-weight: bold; padding: 7px;")
        layout.addWidget(self.btn_ssh_fetch)

        layout.addStretch()
        self.input_tabs.addTab(widget, "SSH Connect")

    def _init_graph_controls(self, parent_layout: QVBoxLayout):
        box = QGroupBox("Layout & Graph Controls")
        layout = QVBoxLayout(box)

        # Center router selector
        h1 = QHBoxLayout()
        h1.addWidget(QLabel("Center Router:"))
        self.combo_center = QComboBox()
        self.combo_center.addItem("Auto (Highest Degree)")
        h1.addWidget(self.combo_center)
        layout.addLayout(h1)

        # Layout algorithm
        h2 = QHBoxLayout()
        h2.addWidget(QLabel("Layout Mode:"))
        self.combo_layout_mode = QComboBox()
        self.combo_layout_mode.addItems(["Radial", "Force-directed", "Hierarchical", "Circular"])
        h2.addWidget(self.combo_layout_mode)
        layout.addLayout(h2)

        # Spacing slider
        layout.addWidget(QLabel("Node Spacing:"))
        self.slider_spacing = QSlider(Qt.Orientation.Horizontal)
        self.slider_spacing.setRange(80, 500)
        self.slider_spacing.setValue(220)
        layout.addWidget(self.slider_spacing)

        # Edge curvature / spacing slider
        layout.addWidget(QLabel("Parallel Link Curvature:"))
        self.slider_curvature = QSlider(Qt.Orientation.Horizontal)
        self.slider_curvature.setRange(20, 120)
        self.slider_curvature.setValue(55)
        layout.addWidget(self.slider_curvature)

        # Checkbox for stub networks in details
        self.chk_show_stubs = QCheckBox("Show Stub Networks in Details")
        self.chk_show_stubs.setChecked(False)
        layout.addWidget(self.chk_show_stubs)

        # Navigation buttons
        btn_h = QHBoxLayout()
        self.btn_fit = QPushButton("Fit to Screen")
        self.btn_reset_layout = QPushButton("Reset Layout")
        btn_h.addWidget(self.btn_fit)
        btn_h.addWidget(self.btn_reset_layout)
        layout.addLayout(btn_h)

        parent_layout.addWidget(box)

    def _init_inspector(self, parent_layout: QVBoxLayout):
        tabs = QTabWidget()

        # Details Tab
        details_widget = QWidget()
        d_layout = QVBoxLayout(details_widget)
        self.details_label = QLabel("Click on a Router or Link to inspect details.")
        self.details_label.setWordWrap(True)
        self.details_label.setStyleSheet("font-weight: bold; margin-bottom: 6px;")
        d_layout.addWidget(self.details_label)

        self.btn_hide_selected_router = QPushButton("Hide This Router From Graph")
        self.btn_hide_selected_router.setEnabled(False)
        self.btn_hide_selected_router.setStyleSheet("background-color: #fee2e2; color: #b91c1c; font-weight: 500;")
        d_layout.addWidget(self.btn_hide_selected_router)

        self.details_text = QTextEdit()
        self.details_text.setReadOnly(True)
        d_layout.addWidget(self.details_text)
        tabs.addTab(details_widget, "Inspector")

        # Warnings / Diagnostics Tab
        warn_widget = QWidget()
        w_layout = QVBoxLayout(warn_widget)
        self.warn_text = QTextEdit()
        self.warn_text.setReadOnly(True)
        w_layout.addWidget(self.warn_text)
        tabs.addTab(warn_widget, "Diagnostics & Warnings")

        # Router Filter / Visibility Tab
        filter_widget = QWidget()
        f_layout = QVBoxLayout(filter_widget)

        f_info = QLabel("Uncheck a router to hide it and its connected links from the topology:")
        f_info.setWordWrap(True)
        f_layout.addWidget(f_info)

        btn_box = QHBoxLayout()
        self.btn_select_all_routers = QPushButton("Show All")
        self.btn_deselect_all_routers = QPushButton("Hide All")
        btn_box.addWidget(self.btn_select_all_routers)
        btn_box.addWidget(self.btn_deselect_all_routers)
        f_layout.addLayout(btn_box)

        self.router_list_widget = QListWidget()
        f_layout.addWidget(self.router_list_widget)

        tabs.addTab(filter_widget, "Routers Filter")

        parent_layout.addWidget(tabs)

    def _init_toolbar(self):
        toolbar = QToolBar("Actions")
        self.addToolBar(toolbar)

        act_zoom_in = toolbar.addAction("Zoom In")
        act_zoom_in.triggered.connect(self.graph_view.zoom_in)

        act_zoom_out = toolbar.addAction("Zoom Out")
        act_zoom_out.triggered.connect(self.graph_view.zoom_out)

        act_fit = toolbar.addAction("Fit View")
        act_fit.triggered.connect(self.graph_view.fit_to_screen)

        toolbar.addSeparator()

        act_exp_png = toolbar.addAction("Export PNG")
        act_exp_png.triggered.connect(self.export_png)

        act_exp_svg = toolbar.addAction("Export SVG")
        act_exp_svg.triggered.connect(self.export_svg)

        act_exp_json = toolbar.addAction("Export Topology JSON")
        act_exp_json.triggered.connect(self.export_topology_json)

        toolbar.addSeparator()

        act_save_pos = toolbar.addAction("Save Node Layout")
        act_save_pos.triggered.connect(self.save_layout_positions)

        act_load_pos = toolbar.addAction("Load Node Layout")
        act_load_pos.triggered.connect(self.load_layout_positions)

    def _setup_connections(self):
        self.btn_parse_manual.clicked.connect(self.parse_manual_input)
        self.btn_ssh_fetch.clicked.connect(self.start_ssh_fetch)
        self.btn_fit.clicked.connect(self.graph_view.fit_to_screen)
        self.btn_reset_layout.clicked.connect(self.apply_layout)

        self.combo_center.currentIndexChanged.connect(self.apply_layout)
        self.combo_layout_mode.currentIndexChanged.connect(self.apply_layout)
        self.slider_spacing.valueChanged.connect(self.apply_layout)
        self.slider_curvature.valueChanged.connect(self._update_curvature)
        self.chk_show_stubs.stateChanged.connect(self._refresh_inspector_view)

        self.btn_select_all_routers.clicked.connect(self.select_all_routers)
        self.btn_deselect_all_routers.clicked.connect(self.deselect_all_routers)
        self.router_list_widget.itemChanged.connect(self.on_router_filter_changed)
        self.btn_hide_selected_router.clicked.connect(self.hide_selected_router)

        # Graph selection signals
        self.graph_view.listener.node_selected.connect(self.display_router_details)
        self.graph_view.listener.link_selected.connect(self.display_link_details)
        self.graph_view.listener.node_moved.connect(self.on_node_moved)

    def on_node_moved(self, router_id: str, x: float, y: float):
        self.saved_positions[router_id] = (x, y)

    def _update_curvature(self, value: int):
        self.graph_view.curve_spacing = float(value)
        for edge in self.graph_view.edges:
            edge.curve_spacing = float(value)
            edge.update_positions()

    def parse_manual_input(self):
        text = self.manual_text_edit.toPlainText()
        if not text.strip():
            show_msg(self, "Empty Input", "Please paste MikroTik LSA output first.", QMessageBox.Icon.Warning)
            return
        self.process_lsa_data(text)

    def start_ssh_fetch(self):
        host = self.ssh_host.text().strip()
        if not host:
            show_msg(self, "Missing Host", "Please enter a valid Host/IP address.", QMessageBox.Icon.Warning)
            return

        port_str = self.ssh_port.text().strip()
        port = int(port_str) if port_str.isdigit() else 22
        user = self.ssh_user.text().strip()
        password = self.ssh_pass.text()

        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.btn_ssh_fetch.setEnabled(False)
        self.status_bar.showMessage(f"Connecting to {host}:{port}...")

        self.ssh_worker = SSHWorker(host, port, user, password)
        self.ssh_worker.finished.connect(self.on_ssh_finished)
        self.ssh_worker.start()

    def on_ssh_finished(self, success: bool, output: str, log_info: str):
        self.progress_bar.setVisible(False)
        self.btn_ssh_fetch.setEnabled(True)

        if not success:
            self.status_bar.showMessage(f"SSH Failed: {output}")
            show_msg(self, "SSH Connection Error", output, QMessageBox.Icon.Critical)
            return

        self.status_bar.showMessage("SSH data received successfully. Parsing...")
        self.manual_text_edit.setPlainText(output)
        self.process_lsa_data(output)

    def process_lsa_data(self, raw_text: str):
        # Parse
        self.routers = self.parser.parse(raw_text)
        if not self.routers:
            show_msg(
                self,
                "No Routers Found",
                "No valid Router-LSA records were found in the output.\n\n"
                "Check the Diagnostics tab or verify that OSPF is running and LSA database is populated.",
                QMessageBox.Icon.Information
            )
            return

        # Build topology
        self.graph, self.links, warnings = self.builder.build_topology(self.routers)
        all_warnings = self.parser.warnings + warnings

        # Update Diagnostics tab
        if all_warnings:
            self.warn_text.setPlainText("\n".join(f"• {w}" for w in all_warnings))
        else:
            self.warn_text.setPlainText("No anomalies detected. All links matched cleanly.")

        # Update Center Router combo box
        current_center = self.combo_center.currentText()
        self.combo_center.blockSignals(True)
        self.combo_center.clear()
        self.combo_center.addItem("Auto (Highest Degree)")
        for rid in sorted(self.routers.keys()):
            self.combo_center.addItem(rid)
        # Restore selection if exists
        idx = self.combo_center.findText(current_center)
        if idx != -1:
            self.combo_center.setCurrentIndex(idx)
        self.combo_center.blockSignals(False)

        # Populate router filter list
        self.router_list_widget.blockSignals(True)
        self.router_list_widget.clear()
        self.hidden_routers.clear()
        for rid in sorted(self.routers.keys()):
            r = self.routers[rid]
            status_text = f" ({len(r.p2p_endpoints)} links)" if r.has_lsa else " [LSA Missing]"
            item = QListWidgetItem(f"{rid}{status_text}")
            item.setData(Qt.ItemDataRole.UserRole, rid)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            self.router_list_widget.addItem(item)
        self.router_list_widget.blockSignals(False)

        self.apply_layout()
        self.status_bar.showMessage(f"Parsed {len(self.routers)} routers, {len(self.links)} P2P links. Warnings: {len(all_warnings)}")

    def on_router_filter_changed(self, item: QListWidgetItem):
        rid = item.data(Qt.ItemDataRole.UserRole)
        if not rid:
            return
        if item.checkState() == Qt.CheckState.Checked:
            self.hidden_routers.discard(rid)
        else:
            self.hidden_routers.add(rid)
        self.apply_layout()

    def select_all_routers(self):
        self.router_list_widget.blockSignals(True)
        for i in range(self.router_list_widget.count()):
            item = self.router_list_widget.item(i)
            item.setCheckState(Qt.CheckState.Checked)
        self.hidden_routers.clear()
        self.router_list_widget.blockSignals(False)
        self.apply_layout()

    def deselect_all_routers(self):
        self.router_list_widget.blockSignals(True)
        for i in range(self.router_list_widget.count()):
            item = self.router_list_widget.item(i)
            item.setCheckState(Qt.CheckState.Unchecked)
            rid = item.data(Qt.ItemDataRole.UserRole)
            if rid:
                self.hidden_routers.add(rid)
        self.router_list_widget.blockSignals(False)
        self.apply_layout()

    def apply_layout(self):
        if not self.routers:
            return

        mode_name = self.combo_layout_mode.currentText().lower()
        if "radial" in mode_name:
            mode = "radial"
        elif "force" in mode_name:
            mode = "force"
        elif "hierarch" in mode_name:
            mode = "hierarchical"
        elif "circul" in mode_name:
            mode = "circular"
        else:
            mode = "radial"

        center_text = self.combo_center.currentText()
        center_node = None if center_text.startswith("Auto") else center_text

        spacing = float(self.slider_spacing.value())

        # If user clicked Reset Layout, we ignore saved positions for this calculation
        sender = self.sender()
        saved_pos = None if sender == self.btn_reset_layout else self.saved_positions

        positions = TopologyLayoutManager.compute_layout(
            graph=self.graph,
            mode=mode,
            center_node=center_node,
            spacing=spacing,
            saved_positions=saved_pos
        )

        # Update saved_positions
        for k, v in positions.items():
            self.saved_positions[k] = v

        self.graph_view.render_topology(self.routers, self.links, positions, hidden_routers=self.hidden_routers)

    def hide_selected_router(self):
        rid = getattr(self, "selected_router_id", None)
        if not rid:
            return
        self.hidden_routers.add(rid)
        # Update checkbox in router filter list
        self.router_list_widget.blockSignals(True)
        for i in range(self.router_list_widget.count()):
            item = self.router_list_widget.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == rid:
                item.setCheckState(Qt.CheckState.Unchecked)
                break
        self.router_list_widget.blockSignals(False)
        self.btn_hide_selected_router.setEnabled(False)
        self.apply_layout()

    def display_router_details(self, router_id: str):
        if router_id not in self.routers:
            return
        router = self.routers[router_id]
        self.selected_router_id = router_id
        self.selected_link_id = None
        self.btn_hide_selected_router.setEnabled(True)
        self.btn_hide_selected_router.setText(f"Hide Router {router_id} From Graph")

        self.details_label.setText(f"Router Details: {router_id}")
        lines = [
            f"Router ID: {router.router_id}",
            f"LSA Present: {'Yes' if router.has_lsa else 'No (Missing in LSDB)'}",
            f"Areas: {', '.join(router.areas) if router.areas else 'None'}",
            f"Instances: {', '.join(router.instances) if router.instances else 'None'}",
            f"Total P2P Endpoints: {len(router.p2p_endpoints)}",
            "",
            "--- Neighbors & P2P Links ---"
        ]

        # Find all links involving this router
        router_links = [l for l in self.links if l.router_a == router_id or l.router_b == router_id]
        for l in router_links:
            peer = l.router_b if l.router_a == router_id else l.router_a
            local_ip = l.ip_a if l.router_a == router_id else l.ip_b
            peer_ip = l.ip_b if l.router_a == router_id else l.ip_a
            cost_out = l.metric_a_to_b if l.router_a == router_id else l.metric_b_to_a
            cost_in = l.metric_b_to_a if l.router_a == router_id else l.metric_a_to_b

            status_note = f" [{l.status.value}]" if l.status != LinkMatchStatus.MATCHED else ""
            lines.append(
                f"• Link to {peer}{status_note}:\n"
                f"   Subnet: {l.subnet or 'Unknown'}\n"
                f"   Local IP: {local_ip or 'None'} (Cost Out: {cost_out})\n"
                f"   Peer IP:  {peer_ip or 'None'} (Cost In: {cost_in})"
            )

        if self.chk_show_stubs.isChecked():
            lines.append("\n--- Stub Networks ---")
            if router.stubs:
                for s in router.stubs:
                    lines.append(f"• {s.network} / {s.netmask} (Metric: {s.metric})")
            else:
                lines.append("• No stub networks advertised.")

        self.details_text.setPlainText("\n".join(lines))

    def display_link_details(self, link_id: str):
        target_link = next((l for l in self.links if l.id == link_id), None)
        if not target_link:
            return

        self.selected_link_id = link_id
        self.selected_router_id = None
        self.btn_hide_selected_router.setEnabled(False)
        self.btn_hide_selected_router.setText("Hide This Router From Graph")
        self.details_label.setText(f"Link Details: {target_link.id}")

        lines = [
            f"Link ID: {target_link.id}",
            f"Status: {target_link.status.value.upper()}",
            f"Area: {target_link.area}",
            f"Instance: {target_link.instance}",
            f"Subnet: {target_link.subnet or 'Undetermined'}",
            "",
            f"Side A Router: {target_link.router_a}",
            f"Side A Local IP: {target_link.ip_a or 'Unknown'}",
            f"Metric A -> B: {target_link.metric_a_to_b if target_link.metric_a_to_b is not None else 'N/A'}",
            "",
            f"Side B Router: {target_link.router_b}",
            f"Side B Local IP: {target_link.ip_b or 'Unknown'}",
            f"Metric B -> A: {target_link.metric_b_to_a if target_link.metric_b_to_a is not None else 'N/A'}",
        ]

        if target_link.is_asymmetric:
            lines.append("\n⚠️ Warning: Asymmetric metric configured on this link!")

        if target_link.warnings:
            lines.append("\nLink Warnings:")
            for w in target_link.warnings:
                lines.append(f"  • {w}")

        self.details_text.setPlainText("\n".join(lines))

    def _refresh_inspector_view(self):
        if getattr(self, "selected_router_id", None):
            self.display_router_details(self.selected_router_id)

    def export_png(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export PNG", "ospf_topology.png", "PNG Image (*.png)")
        if path:
            if self.graph_view.export_image(path):
                show_msg(self, "Success", f"Topology saved to {path}", QMessageBox.Icon.Information)
            else:
                show_msg(self, "Export Failed", "Could not export image.", QMessageBox.Icon.Critical)

    def export_svg(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export SVG", "ospf_topology.svg", "SVG Vector (*.svg)")
        if path:
            if self.graph_view.export_image(path):
                show_msg(self, "Success", f"Topology saved to {path}", QMessageBox.Icon.Information)
            else:
                show_msg(self, "Export Failed", "Could not export SVG.", QMessageBox.Icon.Critical)

    def export_topology_json(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export Topology JSON", "ospf_topology.json", "JSON (*.json)")
        if not path:
            return

        data = {
            "routers": {
                r_id: {
                    "router_id": r.router_id,
                    "has_lsa": r.has_lsa,
                    "areas": r.areas,
                    "instances": r.instances,
                    "stubs": [{"network": s.network, "netmask": s.netmask, "metric": s.metric} for s in r.stubs]
                }
                for r_id, r in self.routers.items()
            },
            "links": [l.to_dict() for l in self.links],
            "positions": {
                r_id: {"x": pos[0], "y": pos[1]}
                for r_id, pos in self.saved_positions.items()
            }
        }

        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            show_msg(self, "Success", f"Topology JSON exported to {path}", QMessageBox.Icon.Information)
        except Exception as e:
            show_msg(self, "Export Error", f"Failed to save JSON: {e}", QMessageBox.Icon.Critical)

    def save_layout_positions(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save Node Layout", "layout_positions.json", "JSON (*.json)")
        if not path:
            return
        try:
            data = {
                r_id: {"x": pos[0], "y": pos[1]}
                for r_id, pos in self.saved_positions.items()
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            show_msg(self, "Saved", f"Layout positions saved to {path}", QMessageBox.Icon.Information)
        except Exception as e:
            show_msg(self, "Error", f"Failed to save layout: {e}", QMessageBox.Icon.Critical)

    def load_layout_positions(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load Node Layout", "", "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for r_id, coord in data.items():
                if isinstance(coord, dict) and "x" in coord and "y" in coord:
                    self.saved_positions[r_id] = (float(coord["x"]), float(coord["y"]))
            self.apply_layout()
            show_msg(self, "Loaded", f"Layout positions restored from {path}", QMessageBox.Icon.Information)
        except Exception as e:
            show_msg(self, "Error", f"Failed to load layout: {e}", QMessageBox.Icon.Critical)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
