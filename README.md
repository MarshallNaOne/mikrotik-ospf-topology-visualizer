# MikroTik RouterOS 7 OSPF Topology Visualizer

[![Test and Build](https://github.com/MarshallNaOne/mikrotik-ospf-topology-visualizer/actions/workflows/build.yml/badge.svg)](https://github.com/MarshallNaOne/mikrotik-ospf-topology-visualizer/actions/workflows/build.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

A standalone, professional desktop application built with Python and PySide6 (Qt) to parse **MikroTik RouterOS 7** OSPFv2 Link-State Database (LSDB) records and render high-performance, interactive network topology graphs.

---

## Key Features

- **Live SSH or Offline Manual Input**:
  - Connect directly to any MikroTik RouterOS 7 device over SSH to fetch the LSDB on-demand.
  - Or paste the output of `/routing/ospf/lsa/print detail without-paging` manually.
- **Robust OSPF LSDB Parser**:
  - Full support for RouterOS 7 LSA syntax including flags (`SD`, `D`, `S`), multi-line record layouts, and banner noise.
  - Filters out external (`type="external"`), summary (`type="summary"`), and opaque records while strictly reconstructing physical/logical Point-to-Point (`type=p2p`) and stub (`type=stub`) links.
- **Accurate Parallel Link Representation**:
  - True MultiGraph data structure — parallel connections between the same pair of routers are **never collapsed**.
  - Distinct quadratic Bézier curves separate parallel links with dynamic offset arcs.
  - Intelligent two-way link matching correlates interfaces by matching subnet masks derived from stub LSA records.
  - Detection and visual warnings for asymmetric metrics (`Metric A != Metric B`) and one-way (unidirectional/unmatched) links.
- **Interactive Qt Graphics View Canvas**:
  - Smooth pan (`ScrollHandDrag`), zoom centered at the cursor (`wheelEvent`), and node dragging with real-time edge recalculation.
  - Router search and dynamic visibility toggling (hide/show specific routers and connected links from the topology).
  - Multiple layout algorithms: **Force-Directed (Fruchterman-Reingold)**, **Radial BFS**, **Hierarchical**, and **Circular**.
  - Save and restore node coordinate positions (`JSON`).
- **Comprehensive Inspector & Diagnostics**:
  - Click any router node or link curve to inspect Router IDs, interface IPs, subnet masks, directional costs, and link matching states.
  - Dedicated Diagnostics tab displaying raw parsed records, matched link tables, and LSA warning logs.
- **Vector & Raster Export**:
  - Export the rendered topology to high-resolution PNG or lossless vector SVG.
- **Zero-Storage Security**:
  - Passwords and SSH private credentials are never written to disk or logged.

---

## Architecture Overview

```
mikrotik-ospf-topology-visualizer/
├── ospf_viz/
│   ├── __init__.py           # Package definition and __version__
│   ├── models.py             # Dataclasses: OSPFRouter, OSPFLink, P2PEndpoint, StubNetwork, LinkMatchStatus
│   ├── parser.py             # Robust tokenizer and parser for RouterOS 7 LSA output
│   ├── topology.py           # MultiGraph topology builder & bidirectional endpoint correlation
│   ├── ssh_client.py         # Threaded Paramiko SSH client with safe credential handling
│   ├── layout.py             # Layout engines (Fruchterman-Reingold, Radial BFS, Hierarchical, Circular)
│   ├── visualization.py      # Qt Graphics View canvas, Bezier curves, and interactive graph items
│   └── gui.py                # Main window (PySide6), Inspector sidebar, toolbar, and worker threads
├── tests/
│   └── test_parser_and_topology.py # Comprehensive unit test suite
├── .github/workflows/
│   ├── build.yml             # Automated CI matrix tests and multiplatform binary compilation
│   └── release.yml           # Automated release artifact packaging and SHA256 checksum generation
├── requirements.txt          # Production runtime dependencies
├── requirements-dev.txt      # Development and packaging dependencies
├── ospf_viz.spec             # PyInstaller multiplatform build specification
├── run.py                    # Application entry point with CLI smoke-test support
└── README.md
```

### Why Qt Graphics View?
Unlike web-based canvas wrappers or Matplotlib, the **Qt Graphics View Framework (`QGraphicsScene` / `QGraphicsView`)** provides hardware-accelerated 2D rendering, native desktop event dispatching, pixel-perfect Bézier curve drawing for multi-link bundles, and lossless SVG serialization.

---

## RouterOS Command

To collect the LSDB manually from RouterOS 7 terminal or WinBox:

```routeros
/routing/ospf/lsa/print detail without-paging
```

Then switch to the **Manual Input** tab in the application, paste the text, and click **Parse & Build Topology**.

---

## Installation & Running from Source

### Prerequisites
- Python 3.10, 3.11, or 3.12
- `pip`

### Steps

1. **Clone the repository:**
   ```bash
   git clone https://github.com/MarshallNaOne/mikrotik-ospf-topology-visualizer.git
   cd mikrotik-ospf-topology-visualizer
   ```

2. **Create a virtual environment:**
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Launch the application:**
   ```bash
   python run.py
   ```

---

## Building Standalone Executables

Standalone executables for Windows, Linux, and macOS can be built using [PyInstaller](https://pyinstaller.org/):

```bash
pip install -r requirements-dev.txt
pyinstaller --noconfirm ospf_viz.spec
```

The resulting binaries will be located in the `dist/` directory:
- **Windows**: `dist/ospf-viz.exe`
- **Linux**: `dist/ospf-viz`
- **macOS**: `dist/OSPF-Viz.app` and `dist/ospf-viz`

---

## Continuous Integration & Automated Builds

GitHub Actions workflows are configured out-of-the-box:

1. **CI Build (`build.yml`)**:
   - Triggers on every push and pull request to `main`/`master`.
   - Runs unit tests and CLI smoke tests on Windows, Linux, and macOS across Python 3.11 and 3.12.
   - Builds native standalone binaries on:
     - Windows x64 (`windows-latest`)
     - Linux x64 (`ubuntu-22.04`)
     - macOS Apple Silicon ARM64 (`macos-15`)
     - macOS Intel x64 (`macos-15-intel`)
   - Packages and uploads downloadable artifacts.

2. **Automated Release (`release.yml`)**:
   - Triggers when a version tag (e.g. `v1.0.0`) is pushed.
   - Builds all 4 platform binaries.
   - Generates a `SHA256SUMS.txt` cryptographic manifest.
   - Publishes a formal GitHub Release with binary attachments.

---

## Platform Notes & OS Security

- **macOS (Gatekeeper)**: Binaries built in open CI are not notarized with an Apple Developer certificate. If macOS blocks opening the application, right-click `OSPF-Viz.app` and select **Open**, or run:
  ```bash
  xattr -cr /path/to/OSPF-Viz.app
  ```
- **Linux**: The standalone executable is compiled on Ubuntu 22.04 LTS (glibc 2.35) and requires standard X11/Wayland display libraries (`libegl1`, `libxkbcommon-x11-0`).

---

## Running Unit Tests

Run the test suite using standard Python `unittest`:

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

---

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
