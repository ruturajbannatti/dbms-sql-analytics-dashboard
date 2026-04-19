# DBMS SQL Analytics Dashboard

A Streamlit-based DBMS project that demonstrates SQL-style data operations, transaction handling, and normalization analysis on CSV-backed datasets using an in-memory SQLite engine.

## Features
- Load multiple CSV files as SQL tables
- Perform record display, filtering, grouping, and aggregation
- Run set operations
- Simulate transactions with logs and savepoints
- Compute candidate keys and analyze 2NF/3NF
- Visualize and inspect dependency behavior

## Tech Stack
- Python 3.10+
- Streamlit
- Pandas
- SQLite (in-memory)
- Matplotlib

## Project Structure
- `DBMSProject.py`: Main Streamlit application
- `LO30_L019_L005_DBMSProject.pdf`: Project report/documentation
- `requirements.txt`: Python dependencies

## Quick Start
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run DBMSProject.py
```

## Notes
- The app expects CSV files when using the “Load Data” workflow.
- SQLite is initialized in memory for each session.
