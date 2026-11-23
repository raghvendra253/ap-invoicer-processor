"""Local JSON persistence layer for AP Invoice Processor."""

import json
from pathlib import Path
from typing import Any, Dict, Optional

try:
    from .seed_data import get_seed_data
except ImportError:
    from seed_data import get_seed_data

DATA_DIR = Path(__file__).resolve().parent
STORE_PATH = DATA_DIR / "store.json"


def init_db(force: bool = False) -> Dict[str, Any]:
    """Creates data/store.json from seed_data.py if it doesn't exist.

    Args:
        force: If True, overwrites store.json even if it exists.

    Returns:
        The initialized database state dictionary.
    """
    if force or not STORE_PATH.exists():
        initial_state = get_seed_data()
        save_state(initial_state)
        return initial_state
    return get_state()


def reset_db() -> Dict[str, Any]:
    """Overwrites data/store.json back to the clean seed state.

    Returns:
        The freshly reset database state dictionary.
    """
    return init_db(force=True)


def get_state() -> Dict[str, Any]:
    """Loads and returns the current database state from data/store.json.

    If store.json does not exist, it will be automatically initialized.
    """
    if not STORE_PATH.exists():
        return init_db()

    with open(STORE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(state: Dict[str, Any]) -> None:
    """Saves the state dictionary into data/store.json with clean formatting."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(STORE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def add_run_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """Appends a new run/invoice record to run_history and persists state.

    Args:
        record: The run record dictionary to store.

    Returns:
        The newly added record.
    """
    state = get_state()
    if "run_history" not in state:
        state["run_history"] = []
    state["run_history"].append(record)
    save_state(state)
    return record


def update_po_billed(po_number: str, amount: float) -> Optional[Dict[str, Any]]:
    """Increments the previously_billed amount for the specified purchase order.

    Args:
        po_number: The purchase order identifier (e.g. 'PO-2026-101').
        amount: The incremental amount to add to previously_billed.

    Returns:
        The updated purchase order dictionary if found, otherwise None.
    """
    state = get_state()
    for po in state.get("purchase_orders", []):
        if po.get("po_number") == po_number:
            current_billed = float(po.get("previously_billed", 0.0))
            po["previously_billed"] = round(current_billed + float(amount), 2)
            save_state(state)
            return po
    return None


if __name__ == "__main__":
    state = init_db()
    print(f"Store initialized at: {STORE_PATH}")
    print(f"Loaded {len(state.get('vendors', []))} vendors, "
          f"{len(state.get('purchase_orders', []))} POs, "
          f"{len(state.get('run_history', []))} run records.")
