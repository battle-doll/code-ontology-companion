#!/usr/bin/env python3
"""Build a public self-ontology from this repository, keeping private state outside it."""
from __future__ import annotations

import argparse
import hashlib
import html
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_REPOSITORY = "https://github.com/battle-doll/code-ontology-companion"
PUBLIC_ARTIFACT_NAMES = {"index.html", "ontology.json", "ontology.ttl", "snapshot.json", ".nojekyll"}


def command(args: list[str], *, cwd: Path = ROOT, env=None) -> str:
    return subprocess.run(args, cwd=cwd, env=env, check=True, text=True,
                          capture_output=True).stdout.strip()


def load_demo_privacy_guard(tool: Path):
    """Use the same shipped guard as runtime HTML generation; no identity values."""
    location = tool / "scripts" / "privacy_guard.py"
    if not location.is_file():
        raise ValueError("The public demo requires the shipped privacy guard.")
    spec = importlib.util.spec_from_file_location("self_demo_privacy_guard", location)
    if spec is None or spec.loader is None:
        raise ValueError("The public demo privacy guard could not be loaded.")
    guard = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = guard
    spec.loader.exec_module(guard)
    return guard


def publish_validated_artifacts(output: Path, artifacts: dict[str, bytes], guard,
                                *, context_roots=(), forbidden=()) -> None:
    """Check every staged artifact before making any portable file visible."""
    for name, payload in artifacts.items():
        if name not in PUBLIC_ARTIFACT_NAMES or PurePosixPath(name).name != name or "\\" in name:
            raise ValueError("Public demo artifact names must be fixed basenames.")
        # The runtime guard canonicalizes JSON/HTML/URL encodings and consults
        # an optional private HMAC profile. That profile never enters artifacts.
        guard.ensure_public_safe(payload.decode("utf-8"), context_roots=context_roots)
        for token in forbidden:
            if token and str(token).encode("utf-8") in payload:
                raise ValueError("Private metadata found in a public demo artifact.")
    for name, payload in artifacts.items():
        (output / name).write_bytes(payload)


def committed_source(revision: str, destination: Path, *, repo: Path = ROOT) -> None:
    """Materialize only one Git tree, excluding ignored files and working-tree races."""
    archive = destination.parent / "committed-source.tar"
    command(["git", "archive", "--format=tar", "--output", str(archive), revision], cwd=repo)
    destination.mkdir()
    with tarfile.open(archive) as bundle:
        members = bundle.getmembers()
        for member in members:
            name = PurePosixPath(member.name)
            if name.is_absolute() or ".." in name.parts or "\\" in member.name:
                raise ValueError("Unsafe path in committed source archive.")
            if not member.isdir() and not member.isfile():
                raise ValueError("Public source archive must contain regular files and directories only.")
        bundle.extractall(destination, members=members)


def build(output: Path, allow_dirty: bool = False) -> dict:
    origin = command(["git", "remote", "get-url", "origin"])
    if origin.removesuffix(".git") != PUBLIC_REPOSITORY:
        raise ValueError("The public demo builder only accepts this public project origin.")
    dirty = bool(command(["git", "status", "--porcelain", "--untracked-files=normal"]))
    if dirty and not allow_dirty:
        raise ValueError("Public release demos require a clean committed source tree.")
    revision = command(["git", "rev-parse", "HEAD"])
    output = output.resolve()
    if output == ROOT or ROOT in output.parents or output in ROOT.parents:
        raise ValueError("Demo output must be outside the source repository.")
    if output.exists() and any(output.iterdir()):
        raise ValueError("Demo output must be new or empty.")
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="companion-self-demo-") as raw:
        private = Path(raw)
        source = ROOT
        if not allow_dirty:
            source = private / "code-ontology-companion"
            committed_source(revision, source)
        tool = private / "tool"
        shutil.copytree(source / "skills" / "manage-code-ontology", tool,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        guard = load_demo_privacy_guard(tool)
        env = dict(os.environ, CODE_ONTOLOGY_HOME=str(private / "registry"),
                   PYTHONDONTWRITEBYTECODE="1")
        cli = [sys.executable, str(tool / "scripts" / "companion.py")]
        command(cli + ["doctor", "--repo", str(source)], env=env)
        scope = ["--source-root", "skills", "--source-root", "mcp", "--source-root", "scripts"]
        command(cli + ["preflight", "--repo", str(source)] + scope, env=env)
        result = json.loads(command(cli + ["init", "--repo", str(source), "--workspace",
                            str(private / "workspace"), "--label", "Code Ontology Companion",
                            "--authorized"] + scope, env=env))
        snapshot = Path(result["visualization"]).parent
        document = json.loads((snapshot / "ontology.json").read_text())
        # Full fingerprints and local registration IDs stay in the private snapshot.
        document["companion"] = {key: value for key, value in document.get("companion", {}).items()
                                 if key in {"snapshotId", "evidenceType"}}
        portable = private / "portable"
        portable.mkdir()
        (portable / "ontology.json").write_text(json.dumps(document, ensure_ascii=False,
                                                           indent=2) + "\n", encoding="utf-8")
        command([sys.executable, str(tool / "scripts" / "code_ontology_core.py"),
                 "visualize", "--index", str(portable / "ontology.json"),
                 "--output", str(portable / "index.html")], env=env)
        markup = (portable / "index.html").read_text(encoding="utf-8")
        source_url = PUBLIC_REPOSITORY + "/tree/" + revision
        meta = (f'<meta name="source-revision" content="{revision}">\n'
                f'<meta name="source-url" content="{html.escape(source_url, quote=True)}">\n'
                f'<meta name="source-state" content="{"dirty-preview" if allow_dirty else "committed"}">\n')
        markup = markup.replace("</head>", meta + "</head>", 1)
        (portable / "index.html").write_text(markup, encoding="utf-8")
        shutil.copyfile(snapshot / "ontology.ttl", portable / "ontology.ttl")
        manifest = {
            "repository": PUBLIC_REPOSITORY, "sourceRevision": revision,
            "sourceState": "dirty-preview" if allow_dirty else "committed",
            "snapshotId": result["snapshotId"],
            "pluginVersion": json.loads((source / ".codex-plugin/plugin.json").read_text())["version"],
            "counts": result["counts"], "evidenceType": "observed",
            "scope": "Supported Java/Python static source in skills, mcp and scripts; excludes tests and fixtures; not all languages or runtime behavior",
            "sourceRoots": ["mcp", "scripts", "skills"],
            "files": {},
        }
        artifacts = {}
        for name in ("index.html", "ontology.json", "ontology.ttl"):
            payload = (portable / name).read_bytes()
            manifest["files"][name] = {"sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)}
            artifacts[name] = payload
        artifacts["snapshot.json"] = (json.dumps(manifest, indent=2) + "\n").encode("utf-8")
        artifacts[".nojekyll"] = b""
        publish_validated_artifacts(output, artifacts, guard,
            context_roots=(ROOT, source, private, output),
            forbidden=(ROOT, private, Path.home(), "sourceFingerprint", "workspaceId"))
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--allow-dirty", action="store_true", help="Local preview only; marks provenance dirty.")
    args = parser.parse_args()
    try:
        result = build(args.output, args.allow_dirty)
    except Exception:
        # Native exceptions and subprocess argv can contain private local paths.
        print(json.dumps({"status": "error", "message": "Public demo build failed; no raw diagnostic data is displayed."}), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
