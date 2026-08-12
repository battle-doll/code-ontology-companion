#!/usr/bin/env python3
"""Validate the offline workbench's 3D, accessibility, and resource contract."""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = ROOT / "evals" / "visualization-quality-cases.json"
DEFAULT_ASSETS = ROOT / "skills" / "manage-code-ontology" / "assets"
CORE = (
    ROOT
    / "skills"
    / "manage-code-ontology"
    / "scripts"
    / "code_ontology_core.py"
)


class VisualizationGateError(ValueError):
    """Raised when the gate corpus or its configured assets are malformed."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VisualizationGateError(f"Unreadable visualization corpus: {exc}") from exc
    if not isinstance(value, dict):
        raise VisualizationGateError("Visualization corpus root must be an object.")
    return value


def validate_corpus(corpus: dict[str, Any]) -> None:
    if corpus.get("schema_version") != "1.0":
        raise VisualizationGateError("Unsupported visualization corpus schema_version.")
    budgets = corpus.get("budgets")
    if not isinstance(budgets, dict):
        raise VisualizationGateError("Visualization budgets must be an object.")
    required_budgets = {
        "max_3d_nodes_ceiling",
        "max_3d_edges_ceiling",
        "max_frame_budget_ms",
        "minimum_control_target_px",
        "reflow_viewport_px",
    }
    if set(budgets) != required_budgets or any(
        not isinstance(value, int) or isinstance(value, bool) or value <= 0
        for value in budgets.values()
    ):
        raise VisualizationGateError("Visualization budgets are incomplete or invalid.")
    checks = corpus.get("checks")
    if not isinstance(checks, list) or not checks:
        raise VisualizationGateError("Visualization checks must be a non-empty array.")
    identifiers: set[str] = set()
    for check in checks:
        if not isinstance(check, dict) or set(check) != {"id", "description"}:
            raise VisualizationGateError("Every visualization check needs id and description.")
        check_id = check.get("id")
        if (
            not isinstance(check_id, str)
            or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", check_id)
            or check_id in identifiers
            or not isinstance(check.get("description"), str)
            or not check["description"].strip()
        ):
            raise VisualizationGateError(f"Invalid visualization check: {check_id!r}")
        identifiers.add(check_id)
    expected = {
        "offline-safe",
        "progressive-fallback",
        "three-d-controls",
        "keyboard-and-screen-reader",
        "motion-and-visibility",
        "contrast-and-reflow",
        "deterministic-resource-bounds",
        "legacy-snapshot",
    }
    if identifiers != expected:
        raise VisualizationGateError("Visualization corpus check set is incomplete.")
    forbidden = corpus.get("forbidden_application_tokens")
    if (
        not isinstance(forbidden, list)
        or not forbidden
        or any(not isinstance(token, str) or not token for token in forbidden)
    ):
        raise VisualizationGateError("forbidden_application_tokens must be non-empty strings.")


def _contains_all(value: str, markers: tuple[str, ...]) -> list[str]:
    return [marker for marker in markers if marker not in value]


def _constant(source: str, names: tuple[str, ...]) -> int | None:
    alternatives = "|".join(re.escape(name) for name in names)
    match = re.search(
        rf"\b(?:const|let|var)\s+(?:{alternatives})\s*=\s*([0-9]+)\b",
        source,
    )
    return int(match.group(1)) if match else None


def _load_assets(asset_dir: Path) -> tuple[str, str, str]:
    try:
        return tuple(
            (asset_dir / name).read_text(encoding="utf-8")
            for name in ("workbench.html", "workbench.js", "workbench.css")
        )  # type: ignore[return-value]
    except (OSError, UnicodeDecodeError) as exc:
        raise VisualizationGateError(f"Workbench assets are unreadable: {exc}") from exc


def _legacy_render_is_deterministic() -> tuple[bool, str]:
    spec = importlib.util.spec_from_file_location("visualization_gate_core", CORE)
    if spec is None or spec.loader is None:
        return False, "bundled renderer could not be loaded"
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        document = {
            "schema_version": "1.0",
            "generated_at": "2026-01-01T00:00:00+00:00",
            "generator": {"name": "Code Ontology Companion", "version": "legacy"},
            "repository": {"name": "legacy-fixture"},
            "statistics": {"source_files": {"Python": 1}, "skipped": {}},
            "nodes": [
                {
                    "id": "python:module:legacy",
                    "type": "Module",
                    "name": "legacy",
                    "language": "Python",
                    "path": "legacy.py",
                    "qualified_name": "legacy",
                }
            ],
            "edges": [],
            "warnings": [],
            "companion": {"snapshotId": "legacy-snapshot", "evidenceType": "observed"},
        }
        first = module.render_visualization(document, 50)
        second = module.render_visualization(document, 50)
    except Exception as exc:  # pragma: no cover - error text is surfaced by the CLI
        return False, f"legacy render raised {type(exc).__name__}: {exc}"
    required = ('id="view-mode-2d"', 'id="graph"', "legacy_unknown")
    missing = _contains_all(first, required)
    if first != second:
        return False, "identical legacy input produced different HTML bytes"
    if missing:
        return False, "legacy render lacks " + ", ".join(missing)
    return True, "legacy payload renders byte-identically with the 2D fallback"


def evaluate(corpus: dict[str, Any], asset_dir: Path = DEFAULT_ASSETS) -> dict[str, Any]:
    """Return a deterministic machine-readable visualization quality result."""

    validate_corpus(corpus)
    html, js, css = _load_assets(asset_dir)
    budgets = corpus["budgets"]
    results: dict[str, dict[str, str]] = {}

    def record(check_id: str, passed: bool, detail: str) -> None:
        results[check_id] = {"status": "pass" if passed else "fail", "detail": detail}

    csp_missing = _contains_all(
        html,
        (
            "default-src 'none'",
            "connect-src 'none'",
            "worker-src 'none'",
            "frame-src 'none'",
            "object-src 'none'",
        ),
    )
    forbidden_found = [
        token for token in corpus["forbidden_application_tokens"] if token in js
    ]
    remote_refs = re.findall(r"(?:src|href)\s*=\s*[\"'](?:https?:)?//", html, re.I)
    offline_ok = not csp_missing and not forbidden_found and not remote_refs
    record(
        "offline-safe",
        offline_ok,
        "offline CSP and application primitives are bounded"
        if offline_ok
        else f"missing_csp={csp_missing}; forbidden={forbidden_found}; remote={len(remote_refs)}",
    )

    fallback_markers = (
        'id="view-mode-switch"',
        'id="view-mode-2d"',
        'id="view-mode-3d"',
        'id="graph"',
        'aria-pressed="true"',
    )
    fallback_missing = _contains_all(html, fallback_markers)
    mode_listeners = (
        re.search(r"viewMode2d\.addEventListener\s*\(\s*[\"']click[\"']", js)
        is not None
        and re.search(r"viewMode3d\.addEventListener\s*\(\s*[\"']click[\"']", js)
        is not None
    )
    fallback_logic = (
        "threeDAvailable" in js
        and re.search(r"(?:set|activate|switch|apply)[A-Za-z0-9_]*(?:ViewMode|viewMode)\s*\(\s*[\"']2d[\"']", js)
        is not None
        and "aria-pressed" in js
    )
    record(
        "progressive-fallback",
        not fallback_missing and mode_listeners and fallback_logic,
        "2D is the explicit default and capability fallback"
        if not fallback_missing and mode_listeners and fallback_logic
        else f"missing={fallback_missing}; mode_listeners={mode_listeners}; fallback_logic={fallback_logic}",
    )

    controls_missing = _contains_all(
        html,
        (
            'id="graph-3d"',
            'id="graph-3d-canvas"',
            'id="graph-3d-status"',
            'id="graph-3d-instructions"',
            'aria-describedby="graph-3d-instructions',
            'id="zoom-out"',
            'id="zoom-in"',
            'id="fit-graph"',
            'id="reset-view"',
        ),
    )
    canvas_semantics = (
        re.search(r'id="graph-3d-canvas"[^>]*tabindex="0"[^>]*role="(?:application|img|region)"', html)
        is not None
        or re.search(r'id="graph-3d-canvas"[^>]*role="(?:application|img|region)"[^>]*tabindex="0"', html)
        is not None
    )
    canvas_draw_path = (
        re.search(r"getContext\s*\(\s*[\"']2d[\"']", js) is not None
        and ".clearRect(" in js
        and ".lineTo(" in js
        and ".arc(" in js
    )
    pointer_path = (
        all(token in js for token in ("pointerdown", "pointermove", "pointerup", "pointercancel"))
        and re.search(r"graph3dCanvas\.addEventListener", js) is not None
    )
    text_alternative_path = (
        "graphTextNodes" in js
        and "graphTextEdges" in js
        and ("replaceChildren(" in js or "appendChild(" in js)
        and re.search(r"render(?:Graph)?Text(?:Alternative|Summary)?\s*\(\s*graph", js) is not None
    )
    render_invocation = (
        re.search(r"render(?:Graph)?3[Dd]\s*\(\s*graph", js) is not None
        and text_alternative_path
    )
    record(
        "three-d-controls",
        not controls_missing
        and canvas_semantics
        and canvas_draw_path
        and pointer_path
        and render_invocation,
        "3D canvas has bounded visible and textual controls"
        if not controls_missing and canvas_semantics and canvas_draw_path and pointer_path and render_invocation
        else (
            f"missing={controls_missing}; canvas_semantics={canvas_semantics}; "
            f"draw_path={canvas_draw_path}; pointer_path={pointer_path}; "
            f"render_invocation={render_invocation}"
        ),
    )

    keyboard_tokens = ("ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "Enter", "Escape")
    keyboard_missing = _contains_all(js, keyboard_tokens)
    pressed_group = (
        'id="view-mode-switch"' in html
        and 'role="group"' in html
        and re.search(r'id="view-mode-2d"[^>]*aria-pressed=', html) is not None
        and re.search(r'id="view-mode-3d"[^>]*aria-pressed=', html) is not None
    )
    radio_group = (
        'role="radiogroup"' in html
        and len(re.findall(r'role="radio"[^>]*aria-checked=', html)) >= 2
    )
    mode_semantics = pressed_group or radio_group
    a11y_missing = _contains_all(html, ('aria-live="polite"',))
    keyboard_ok = (
        not keyboard_missing
        and not a11y_missing
        and mode_semantics
        and "keydown" in js
        and re.search(r"graph3dCanvas\.addEventListener\s*\(\s*[\"']keydown[\"']", js)
        is not None
        and ("announce(" in js or "liveStatus" in js)
    )
    record(
        "keyboard-and-screen-reader",
        keyboard_ok,
        "keyboard focus, selection, mode, and live announcements are present"
        if keyboard_ok
        else (
            f"missing_keys={keyboard_missing}; missing_html={a11y_missing}; "
            f"mode_semantics={mode_semantics}"
        ),
    )

    motion_control = re.search(r'id="[^"]*(?:motion|animation)[^"]*"[^>]*(?:aria-label|>[^<]+<)', html, re.I)
    motion_ok = (
        motion_control is not None
        and "prefers-reduced-motion" in js
        and "prefers-reduced-motion" in css
        and "visibilitychange" in js
        and "visibilityState" in js
        and "cancelAnimationFrame" in js
        and "dom.graphView.hidden" in js
        and re.search(
            r"if\s*\(\s*!graphMode\s*\)\s*\{[^}]*stop3dFrame\s*\(",
            js,
            re.S,
        ) is not None
    )
    record(
        "motion-and-visibility",
        motion_ok,
        "user preference, reduced motion, and hidden-document pause are enforced"
        if motion_ok
        else "motion control, reduced-motion, visibility pause, or cancellation is missing",
    )

    reflow_queries = [
        int(value)
        for value in re.findall(
            r"@media\s*\([^)]*max-width\s*:\s*([0-9]+)px[^)]*\)", css, re.I
        )
    ]
    reflow_query = any(
        budgets["reflow_viewport_px"] <= value <= 620 for value in reflow_queries
    )
    target = budgets["minimum_control_target_px"]
    target_width = re.search(rf"min-(?:width|inline-size)\s*:\s*(?:{target}|[3-9][0-9])px", css)
    target_height = re.search(rf"min-(?:height|block-size)\s*:\s*(?:{target}|[3-9][0-9])px", css)
    contrast_ok = (
        "forced-colors" in css
        and reflow_query
        and "html, body { min-width: 0" in css
        and "flex-direction: column" in css
        and target_width is not None
        and target_height is not None
        and ("shape" in js.lower() or "legend" in html.lower() or "범례" in html)
    )
    record(
        "contrast-and-reflow",
        contrast_ok,
        "forced colors, non-color encoding, 24px targets, and 320px reflow are present"
        if contrast_ok
        else "forced-colors, narrow reflow, target size, or non-color semantics is missing",
    )

    nodes = _constant(js, ("MAX_3D_VISIBLE_NODES", "MAX_3D_NODES"))
    edges = _constant(js, ("MAX_3D_VISIBLE_EDGES", "MAX_3D_EDGES"))
    frame = _constant(js, ("THREE_D_FRAME_BUDGET_MS", "FRAME_3D_BUDGET_MS"))
    bounds_ok = (
        nodes is not None
        and 0 < nodes <= budgets["max_3d_nodes_ceiling"]
        and edges is not None
        and 0 < edges <= budgets["max_3d_edges_ceiling"]
        and frame is not None
        and 0 < frame <= budgets["max_frame_budget_ms"]
        and (
            js.count("THREE_D_FRAME_BUDGET_MS") >= 2
            or js.count("FRAME_3D_BUDGET_MS") >= 2
        )
        and "threeDLastRenderMs" in js
        and re.search(r"deterministic3dPosition|deterministic3DPosition", js) is not None
        and re.search(r"\.sort\s*\(", js) is not None
        and re.search(r"\.slice\s*\(\s*0\s*,\s*MAX_3D_(?:VISIBLE_)?NODES", js) is not None
        and re.search(r"\.slice\s*\(\s*0\s*,\s*MAX_3D_(?:VISIBLE_)?EDGES", js) is not None
        and re.search(
            r"const\s+graph\s*=\s*bounded3dGraph\s*\(\s*neighborhood", js
        ) is not None
    )
    record(
        "deterministic-resource-bounds",
        bounds_ok,
        "3D input and frame work use deterministic finite caps"
        if bounds_ok
        else f"nodes={nodes}; edges={edges}; frame_ms={frame}; deterministic/sort/slice marker missing",
    )

    legacy_ok, legacy_detail = _legacy_render_is_deterministic()
    record("legacy-snapshot", legacy_ok, legacy_detail)

    ordered_results = {
        check["id"]: results[check["id"]]
        for check in corpus["checks"]
    }
    passed = sum(value["status"] == "pass" for value in ordered_results.values())
    failed = len(ordered_results) - passed
    return {
        "schema_version": "1.0",
        "status": "pass" if failed == 0 else "fail",
        "checks": ordered_results,
        "budgets": {
            "max_3d_nodes": nodes,
            "max_3d_edges": edges,
            "frame_budget_ms": frame,
        },
        "summary": {"passed": passed, "failed": failed, "total": len(ordered_results)},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--assets-dir", type=Path, default=DEFAULT_ASSETS)
    args = parser.parse_args(argv)
    try:
        result = evaluate(_read_json(args.cases), args.assets_dir)
    except VisualizationGateError as exc:
        print(json.dumps({"schema_version": "1.0", "status": "error", "error": str(exc)}, sort_keys=True, separators=(",", ":")))
        return 2
    print(json.dumps(result, ensure_ascii=True, sort_keys=True, separators=(",", ":")))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
