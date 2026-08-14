#!/usr/bin/env python3
"""Validate the public plugin source without third-party dependencies."""

from __future__ import annotations

import ast
import datetime
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / ".codex-plugin" / "plugin.json"
SKILL_PATH = ROOT / "skills" / "manage-code-ontology"
CORE_PATH = SKILL_PATH / "scripts" / "code_ontology_core.py"
COMPANION_PATH = SKILL_PATH / "scripts" / "companion.py"
LOCAL_LLM_PATH = SKILL_PATH / "scripts" / "local_llm.py"
MCP_SERVER_PATH = ROOT / "mcp" / "server.py"
MCP_LAUNCHER_PATH = ROOT / "mcp" / "launcher.mjs"
DOCUMENTATION_VALIDATOR_PATH = ROOT / "scripts" / "validate_documentation.py"
ONTOLOGY_QUALITY_VALIDATOR_PATH = ROOT / "scripts" / "validate_ontology_quality.py"
VISUALIZATION_QUALITY_VALIDATOR_PATH = (
    ROOT / "scripts" / "validate_visualization_quality.py"
)
VERSION = "0.5.2"
VENDOR_HASHES = {
    "skills/manage-code-ontology/assets/vendor/cytoscape-3.34.0.min.js": (
        "9c2a3bf2592e0b14a1f7bec07c03a54f16dedf32af9cd0af155c716aa6c87bc3"
    ),
    "skills/manage-code-ontology/assets/vendor/elkjs-0.12.0.bundled.js": (
        "1222e44f953ce7746af23801e723708f8e6f436b8b377a6a5fc7552f34a307b3"
    ),
}
REQUIRED_FILES = [
    ".mcp.json",
    "LICENSE",
    "CHANGELOG.md",
    "NOTICE",
    "README.md",
    "README.ja.md",
    "README.ko.md",
    "README.ru.md",
    "README.zh-CN.md",
    "PRIVACY.md",
    "TERMS.md",
    "SECURITY.md",
    "THREAT_MODEL.md",
    "SUPPORT.md",
    "CONTRIBUTING.md",
    "SUBMISSION.md",
    "THIRD_PARTY_NOTICES.md",
    "TRADEMARKS.md",
    "SBOM.spdx.json",
    "chatgpt-app-submission.json",
    "evals/cases.json",
    "evals/ontology-quality-cases.json",
    "evals/visualization-quality-cases.json",
    "assets/logo.png",
    "assets/logo-dark.png",
    "assets/composer-icon.png",
    "skills/manage-code-ontology/SKILL.md",
    "skills/manage-code-ontology/agents/openai.yaml",
    "skills/manage-code-ontology/references/data-boundaries.md",
    "skills/manage-code-ontology/references/lineage-model.md",
    "skills/manage-code-ontology/references/local-llm.md",
    "skills/manage-code-ontology/references/local-mcp.md",
    "skills/manage-code-ontology/references/ontology-model.md",
    "skills/manage-code-ontology/references/provenance-schema.ttl",
    "skills/manage-code-ontology/references/schema.ttl",
    "skills/manage-code-ontology/assets/workbench.html",
    "skills/manage-code-ontology/assets/workbench.css",
    "skills/manage-code-ontology/assets/workbench.js",
    "skills/manage-code-ontology/assets/vendor/cytoscape-3.34.0.min.js",
    "skills/manage-code-ontology/assets/vendor/elkjs-0.12.0.bundled.js",
    "skills/manage-code-ontology/assets/vendor/licenses/CYTOSCAPE-MIT.txt",
    "skills/manage-code-ontology/assets/vendor/licenses/ELKJS-EPL-2.0.md",
    "skills/manage-code-ontology/assets/vendor/licenses/WEB-WORKER-APACHE-2.0.txt",
    "skills/manage-code-ontology/scripts/code_ontology_core.py",
    "skills/manage-code-ontology/scripts/companion.py",
    "skills/manage-code-ontology/scripts/local_llm.py",
    "mcp/launcher.mjs",
    "mcp/server.py",
    "scripts/validate_documentation.py",
    "scripts/validate_ontology_quality.py",
    "scripts/validate_visualization_quality.py",
    "scripts/validate_version_bump.py",
]
FORBIDDEN_IMPORT_ROOTS = {
    "requests",
    "httpx",
    "aiohttp",
    "boto3",
    "paramiko",
    "socket",
    "subprocess",
    "http.client",
    "ftplib",
    "urllib.request",
}
REMOVED_PROJECT_PATTERNS = {
    "project-name": re.compile(
        r"(?i)(?<![a-z0-9])" + "aeth" + r"er(?![a-z0-9])"
    ),
    "removed-command": re.compile(r"(?i)runtime(?:[-_ ]+)binding"),
    "removed-schema": re.compile(
        r"(?i)runtime-effective-ontology-" + "binding"
    ),
    "removed-field": re.compile(r"(?i)runtime" + "effective"),
    "removed-policy-path": re.compile(r"(?i)strategy\." + r"exits\."),
    "obsolete-profile-label": re.compile(r"(?i)full" + r"/local"),
}


def fail(message: str) -> None:
    raise AssertionError(message)


def validate_required_files() -> None:
    missing = [relative for relative in REQUIRED_FILES if not (ROOT / relative).is_file()]
    if missing:
        fail(f"Missing required files: {', '.join(missing)}")


def validate_release_governance() -> None:
    if not re.fullmatch(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)", VERSION):
        fail("Release version must be semantic major.minor.patch")

    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    headings = re.findall(
        r"^## ((?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)) "
        r"- (\d{4}-\d{2}-\d{2})$",
        changelog,
        flags=re.MULTILINE,
    )
    if not headings or headings[0][0] != VERSION:
        fail("Changelog must begin with the current version and an ISO date")
    if len({version for version, _date in headings}) != len(headings):
        fail("Changelog release versions must be unique")
    try:
        release_dates = [datetime.date.fromisoformat(value) for _version, value in headings]
    except ValueError as exc:
        fail(f"Changelog release date is invalid: {exc}")
    versions = [tuple(int(part) for part in version.split(".")) for version, _date in headings]
    if versions != sorted(versions, reverse=True):
        fail("Changelog versions must be in descending semantic-version order")
    if release_dates != sorted(release_dates, reverse=True):
        fail("Changelog dates must be in descending order")
    sbom = json.loads((ROOT / "SBOM.spdx.json").read_text(encoding="utf-8"))
    if sbom.get("creationInfo", {}).get("created") != f"{headings[0][1]}T00:00:00Z":
        fail("SBOM creation date must match the current changelog release date")

    contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    for marker in (
        "Every tracked release change requires a new semantic version",
        "Rebuild and validate both deterministic release profiles twice",
        "Refresh the registered self-ontology from the final committed source state",
        "Never move or replace a published release tag",
    ):
        if marker not in contributing:
            fail(f"Release governance is missing: {marker}")

    current_version_markers = {
        "README.md": f"## Version {VERSION} capabilities",
        "SECURITY.md": f"Version {VERSION}:",
        "SUBMISSION.md": f"- Version: {VERSION}",
        "THIRD_PARTY_NOTICES.md": f"Code Ontology Companion {VERSION} vendors",
        "skills/manage-code-ontology/SKILL.md": (
            f"Version {VERSION} continues to include the optional local Canvas2D 3D constellation first shipped in 0.5.0"
        ),
        "skills/manage-code-ontology/references/local-llm.md": (
            f"Version {VERSION} can use an existing Ollama installation"
        ),
        "README.ko.md": f"## 버전 {VERSION} 지원 기능",
        "README.ja.md": f"## バージョン {VERSION} の対応機能",
        "README.zh-CN.md": f"## 版本 {VERSION} 的支持功能",
        "README.ru.md": f"## Возможности версии {VERSION}",
        "docs/ko/SUBMISSION.md": f"- 버전: {VERSION}",
        "docs/ja/SUBMISSION.md": f"- バージョン: {VERSION}",
        "docs/zh-CN/SUBMISSION.md": f"- 版本：{VERSION}",
        "docs/ko/references/local-llm.md": f"버전 {VERSION}는 기존 Ollama",
        "docs/ja/references/local-llm.md": f"バージョン {VERSION} は、既存の Ollama",
        "docs/zh-CN/references/local-llm.md": f"版本 {VERSION} 可以把现有 Ollama",
    }
    for relative, marker in current_version_markers.items():
        if marker not in (ROOT / relative).read_text(encoding="utf-8"):
            fail(f"Current-version documentation is stale: {relative}")


def validate_manifest() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if manifest["name"] != "code-ontology-companion":
        fail("Unexpected manifest name")
    if manifest["version"] != VERSION:
        fail("Manifest version mismatch")
    if manifest["license"] != "Apache-2.0":
        fail("Unexpected license identifier")
    if manifest.get("mcpServers") != "./.mcp.json":
        fail("Manifest must reference the bundled MCP configuration")
    if set(manifest).intersection({"hooks", "apps"}):
        fail(f"Version {VERSION} must not bundle hooks or apps")
    prompts = manifest["interface"]["defaultPrompt"]
    if not 1 <= len(prompts) <= 3 or any(len(prompt) > 128 for prompt in prompts):
        fail("Default prompt count or length is invalid")
    for field in ("websiteURL", "privacyPolicyURL", "termsOfServiceURL"):
        if not manifest["interface"][field].startswith("https://"):
            fail(f"{field} must use HTTPS")
    for field in ("composerIcon", "logo", "logoDark"):
        asset = (ROOT / manifest["interface"][field]).resolve()
        if not asset.is_file() or ROOT not in asset.parents:
            fail(f"Invalid manifest asset: {field}")
    mcp_config = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))
    expected = {
        "cwd": ".",
        "command": "node",
        "args": ["./mcp/launcher.mjs"],
    }
    if mcp_config.get("mcpServers", {}).get("code-ontology-companion") != expected:
        fail("Unexpected bundled MCP launch configuration")
    sbom = json.loads((ROOT / "SBOM.spdx.json").read_text(encoding="utf-8"))
    packages = sbom.get("packages")
    if (
        sbom.get("spdxVersion") != "SPDX-2.3"
        or sbom.get("dataLicense") != "CC0-1.0"
        or sbom.get("SPDXID") != "SPDXRef-DOCUMENT"
        or sbom.get("name") != f"code-ontology-companion-{VERSION}"
        or not isinstance(packages, list)
        or len(packages) != 4
    ):
        fail("SBOM document metadata is invalid")
    package_versions = {
        package.get("name"): package.get("versionInfo")
        for package in packages or []
        if isinstance(package, dict)
    }
    if package_versions != {
        "code-ontology-companion": VERSION,
        "cytoscape": "3.34.0",
        "elkjs": "0.12.0",
        "web-worker": "1.4.1",
    } or not str(sbom.get("documentNamespace", "")).endswith(f"/{VERSION}"):
        fail("SBOM version mismatch")
    package_ids = [package.get("SPDXID") for package in packages]
    if len(set(package_ids)) != len(package_ids) or any(not item for item in package_ids):
        fail("SBOM package SPDX identifiers must be present and unique")
    expected_licenses = {
        "code-ontology-companion": ("Apache-2.0", "Apache-2.0"),
        "cytoscape": ("MIT", "MIT"),
        "elkjs": ("EPL-2.0", "EPL-2.0 OR GPL-3.0-or-later"),
        "web-worker": ("Apache-2.0", "Apache-2.0"),
    }
    for package in packages:
        name = package.get("name")
        if (
            name not in expected_licenses
            or package.get("filesAnalyzed") is not False
            or (
                package.get("licenseConcluded"), package.get("licenseDeclared")
            )
            != expected_licenses[name]
        ):
            fail(f"SBOM package metadata is invalid: {name}")
        references = package.get("externalRefs")
        if not isinstance(references, list) or not any(
            item.get("referenceCategory") == "PACKAGE-MANAGER"
            and item.get("referenceType") == "purl"
            and isinstance(item.get("referenceLocator"), str)
            for item in references
            if isinstance(item, dict)
        ):
            fail(f"SBOM package purl is missing: {name}")
    package_by_name = {package["name"]: package for package in packages}
    if not any(
        item.get("referenceLocator")
        == f"pkg:github/battle-doll/code-ontology-companion@{VERSION}"
        for item in package_by_name["code-ontology-companion"]["externalRefs"]
    ):
        fail("Primary package purl version mismatch")
    for name, relative in (
        ("cytoscape", "skills/manage-code-ontology/assets/vendor/cytoscape-3.34.0.min.js"),
        ("elkjs", "skills/manage-code-ontology/assets/vendor/elkjs-0.12.0.bundled.js"),
    ):
        if VENDOR_HASHES[relative] not in str(package_by_name[name].get("comment", "")):
            fail(f"SBOM vendored hash comment mismatch: {name}")
    relationships = {
        (
            item.get("spdxElementId"),
            item.get("relationshipType"),
            item.get("relatedSpdxElement"),
        )
        for item in sbom.get("relationships", [])
        if isinstance(item, dict)
    }
    expected_relationships = {
        ("SPDXRef-Package-CodeOntologyCompanion", "DEPENDS_ON", "SPDXRef-Package-Cytoscape"),
        ("SPDXRef-Package-CodeOntologyCompanion", "DEPENDS_ON", "SPDXRef-Package-Elkjs"),
        ("SPDXRef-Package-Elkjs", "CONTAINS", "SPDXRef-Package-WebWorker"),
    }
    if not expected_relationships.issubset(relationships):
        fail("SBOM dependency relationships are incomplete")
    submission = (ROOT / "SUBMISSION.md").read_text(encoding="utf-8")
    if f"- Version: {VERSION}" not in submission:
        fail("Submission version mismatch")
    application_submission = json.loads(
        (ROOT / "chatgpt-app-submission.json").read_text(encoding="utf-8")
    )
    expected_tools = {
        "ontology_list_workspaces",
        "ontology_status",
        "ontology_search",
        "ontology_neighbors",
        "ontology_history",
        "ontology_changes",
        "ontology_lineage",
    }
    if set(application_submission.get("tools", {})) != expected_tools:
        fail("App submission tool declarations are incomplete")
    expected_annotations = {
        "readOnlyHint": True,
        "openWorldHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
    }
    for tool_name, declaration in application_submission["tools"].items():
        if declaration.get("annotations") != expected_annotations:
            fail(f"App submission annotations are inaccurate: {tool_name}")


def validate_evals() -> None:
    cases = json.loads((ROOT / "evals" / "cases.json").read_text(encoding="utf-8"))
    if cases["plugin_version"] != VERSION:
        fail("Eval version mismatch")
    if len(cases["positive_cases"]) < 5:
        fail("At least five positive evaluation cases are required")
    if len(cases["negative_cases"]) < 3:
        fail("At least three negative evaluation cases are required")
    identifiers = [
        item["id"] for group in ("positive_cases", "negative_cases") for item in cases[group]
    ]
    if len(identifiers) != len(set(identifiers)):
        fail("Evaluation case IDs must be unique")
    for group in ("positive_cases", "negative_cases"):
        for item in cases[group]:
            if (
                set(item) != {"id", "prompt", "expected"}
                or not isinstance(item["prompt"], str)
                or not item["prompt"].strip()
                or not isinstance(item["expected"], list)
                or len(item["expected"]) < 2
                or any(not isinstance(value, str) or not value.strip() for value in item["expected"])
            ):
                fail(f"Evaluation case is incomplete: {item.get('id', '<missing>')}")

    run([sys.executable, str(ONTOLOGY_QUALITY_VALIDATOR_PATH)])
    run([sys.executable, str(VISUALIZATION_QUALITY_VALIDATOR_PATH)])


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def validate_runtime_boundaries() -> None:
    for path in (CORE_PATH, COMPANION_PATH, MCP_SERVER_PATH):
        imports = imported_modules(path)
        forbidden = {
            module
            for module in imports
            if module in FORBIDDEN_IMPORT_ROOTS
            or module.split(".", 1)[0] in FORBIDDEN_IMPORT_ROOTS
        }
        if forbidden:
            fail(f"Network or process imports are not allowed in {path.name}: {sorted(forbidden)}")
        source = path.read_text(encoding="utf-8")
        for token in ("eval(", "exec(", "os.system(", "Popen(", "shell=True"):
            if token in source:
                fail(f"Target execution primitive found in {path.name}: {token}")
    source = CORE_PATH.read_text(encoding="utf-8")
    if f'PLUGIN_VERSION = "{VERSION}"' not in source:
        fail("Analyzer version mismatch")
    companion_source = COMPANION_PATH.read_text(encoding="utf-8")
    if f'COMPANION_VERSION = "{VERSION}"' not in companion_source:
        fail("Companion version mismatch")
    local_llm_source = LOCAL_LLM_PATH.read_text(encoding="utf-8")
    local_llm_imports = imported_modules(LOCAL_LLM_PATH)
    local_llm_forbidden = {
        module
        for module in local_llm_imports
        if module.split(".", 1)[0]
        in {"aiohttp", "httpx", "requests", "socket", "subprocess", "urllib"}
    }
    if local_llm_forbidden:
        fail(f"Unsupported local LLM transport imports: {sorted(local_llm_forbidden)}")
    required_local_llm_markers = (
        f'VERSION = "{VERSION}"',
        'HOST = "127.0.0.1"',
        "PORT = 11434",
        "http.client.HTTPConnection(HOST, PORT",
        "_require_authorized(authorized)",
        '"evidenceType": "inferred"',
        '"changesObservedOntology": False',
        '"runtimeProof": False',
    )
    for marker in required_local_llm_markers:
        if marker not in local_llm_source:
            fail(f"Local LLM fail-closed boundary is missing: {marker}")
    for token in (
        "os.system(",
        "Popen(",
        "subprocess.",
        "shell=True",
        "http://",
        "https://",
        "0.0.0.0",
        "localhost",
    ):
        if token in local_llm_source:
            fail(f"Local LLM helper contains an unsupported execution or endpoint token: {token}")
    server_source = MCP_SERVER_PATH.read_text(encoding="utf-8")
    if f'SERVER_VERSION = "{VERSION}"' not in server_source:
        fail("MCP server version mismatch")
    launcher = MCP_LAUNCHER_PATH.read_text(encoding="utf-8")
    for forbidden in ('from "node:http"', 'from "node:https"', 'from "node:net"', "fetch(", "exec("):
        if forbidden in launcher:
            fail(f"Network or shell primitive found in launcher: {forbidden}")
    if "shell: false" not in launcher or 'path.join(launcherDir, "server.py")' not in launcher:
        fail("Launcher must use a fixed bundled server path without a shell")


def validate_visualization_assets() -> None:
    for relative, expected in VENDOR_HASHES.items():
        actual = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        if actual != expected:
            fail(f"Vendored visualization asset hash mismatch: {relative}")

    template = (SKILL_PATH / "assets" / "workbench.html").read_text(encoding="utf-8")
    required_markers = {
        "__CODE_ONTOLOGY_TITLE__",
        "__CODE_ONTOLOGY_CSS__",
        "__CODE_ONTOLOGY_CYTOSCAPE__",
        "__CODE_ONTOLOGY_ELK__",
        "__CODE_ONTOLOGY_DATA__",
        "__CODE_ONTOLOGY_APP__",
    }
    if not all(marker in template for marker in required_markers):
        fail("Workbench template placeholders are incomplete")
    for required_csp in ("default-src 'none'", "connect-src 'none'", "worker-src 'none'"):
        if required_csp not in template:
            fail(f"Workbench CSP is missing: {required_csp}")
    if re.search(r"<(?:script|link)\b[^>]+(?:src|href)\s*=", template, re.IGNORECASE):
        fail("Workbench template references an external script or stylesheet")

    application = (SKILL_PATH / "assets" / "workbench.js").read_text(encoding="utf-8")
    for forbidden in (
        "innerHTML",
        "outerHTML",
        "document.write",
        "fetch(",
        "XMLHttpRequest",
        "WebSocket",
        "EventSource",
        "new Worker",
    ):
        if forbidden in application:
            fail(f"Unsafe or network-capable workbench primitive found: {forbidden}")


def validate_text_hygiene() -> None:
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in {".git", "dist", "__pycache__"} for part in path.parts):
            continue
        if "vendor" in path.parts:
            continue
        if path.suffix.lower() not in {
            ".md", ".json", ".yaml", ".yml", ".py", ".ttl", ".svg", ".html", ".css", ".js", ""
        }:
            continue
        text = path.read_text(encoding="utf-8", errors="strict")
        placeholder = "TO" + "DO"
        if re.search(rf"\[{placeholder}(?::|\])|{placeholder}:", text, flags=re.IGNORECASE):
            fail(f"Unresolved placeholder found: {path.relative_to(ROOT)}")
        local_user = Path.home().name
        local_posix = f"/Users/{local_user}/"
        local_windows = f"\\Users\\{local_user}\\"
        if local_posix in text or local_windows in text:
            fail(f"Local absolute path leaked: {path.relative_to(ROOT)}")
        for label, pattern in REMOVED_PROJECT_PATTERNS.items():
            if pattern.search(text):
                fail(
                    f"Removed project-specific scope remains ({label}): "
                    f"{path.relative_to(ROOT)}"
                )


def run(command: list[str]) -> None:
    process = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    if process.returncode:
        sys.stderr.write(process.stdout)
        sys.stderr.write(process.stderr)
        fail(f"Command failed: {' '.join(command)}")


def validate_skill_metadata() -> None:
    openai_yaml = (SKILL_PATH / "agents" / "openai.yaml").read_text(encoding="utf-8")
    for marker in (
        "$manage-code-ontology",
        "relationship evidence",
        "adapter coverage",
        "default 2D",
        "optional 3D",
    ):
        if marker not in openai_yaml:
            fail(f"openai.yaml is missing current workflow metadata: {marker}")
    skill_text = (SKILL_PATH / "SKILL.md").read_text(encoding="utf-8")
    if not skill_text.startswith("---\nname: manage-code-ontology\n"):
        fail("Unexpected skill frontmatter")
    for marker in (
        "optionalRuntimesDetected.ollama",
        "Do not connect or write before an",
        "127.0.0.1:11434",
        "Never call it implicitly from `init`,",
        "reverse-engineer an existing authorized codebase",
        "[local-mcp.md](references/local-mcp.md)",
        "On Windows",
        "[local-llm.md](references/local-llm.md)",
    ):
        if marker not in skill_text:
            fail(f"Skill is missing a required supported-workflow marker: {marker}")


def main() -> int:
    validate_required_files()
    validate_release_governance()
    validate_manifest()
    validate_evals()
    validate_runtime_boundaries()
    validate_visualization_assets()
    validate_text_hygiene()
    validate_skill_metadata()
    run([sys.executable, str(DOCUMENTATION_VALIDATOR_PATH)])
    run(
        [
            sys.executable,
            "-m",
            "py_compile",
            str(CORE_PATH),
            str(COMPANION_PATH),
            str(LOCAL_LLM_PATH),
            str(MCP_SERVER_PATH),
        ]
    )
    run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"])
    print("PASS: source package, safety boundaries, metadata, evals, and tests")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, KeyError, json.JSONDecodeError, SyntaxError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
