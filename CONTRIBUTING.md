# Contributing to MikroTik OSPF Topology Visualizer

Thank you for your interest in contributing! This project is an open-source tool for network engineers and operators visualizing MikroTik RouterOS 7 OSPF link-state databases.

---

## Development Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/<your-username>/mikrotik-ospf-topology-visualizer.git
   cd mikrotik-ospf-topology-visualizer
   ```

2. **Create and activate a virtual environment:**
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install development dependencies:**
   ```bash
   pip install -r requirements-dev.txt
   ```

---

## Running and Testing

- **Run CLI smoke test:**
  ```bash
  python run.py --version
  ```

- **Run unit tests:**
  ```bash
  python -m unittest discover -s tests -p "test_*.py" -v
  ```

- **Run GUI application locally:**
  ```bash
  python run.py
  ```

---

## Code Guidelines

- Keep the architecture modular:
  - `ospf_viz/parser.py`: LSA text tokenization and extraction. Must be resilient against RouterOS CLI noise and arbitrary LSA ordering.
  - `ospf_viz/topology.py`: MultiGraph matching and endpoint reconciliation. Never collapse parallel links into a single edge.
  - `ospf_viz/layout.py`: Graph layout algorithms.
  - `ospf_viz/visualization.py`: Qt Graphics View canvas, Bezier curves, and visual interactions.
  - `ospf_viz/ssh_client.py`: Secure Paramiko client. Never print or persist credentials.
  - `ospf_viz/gui.py`: Main window, inspector sidebar, worker threads, and import/export.
- Follow PEP 8 standards with type hints where applicable.
- Add unit test coverage for new parser features or topology edge-cases in `tests/test_parser_and_topology.py`.

---

## Submitting Pull Requests

1. Fork the repo and create your feature branch:
   ```bash
   git checkout -b feature/my-new-feature
   ```
2. Ensure all unit tests pass:
   ```bash
   python -m unittest discover -s tests -p "test_*.py" -v
   ```
3. Commit your changes with clear, descriptive commit messages.
4. Push to your branch and open a Pull Request.
