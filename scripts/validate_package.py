#!/usr/bin/env python3
"""Validate the public plugin source without third-party dependencies."""

from __future__ import annotations

import ast
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / ".codex-plugin" / "plugin.json"
SKILL_PATH = ROOT / "skills" / "manage-code-ontology"
APPLY_SKILL_PATH = ROOT / "skills" / "apply-code-ontology"
APPLY_WORKFLOW_PATH = APPLY_SKILL_PATH / "scripts" / "apply_workflow.py"
CORE_PATH = SKILL_PATH / "scripts" / "code_ontology_core.py"
COMPANION_PATH = SKILL_PATH / "scripts" / "companion.py"
LOCAL_LLM_PATH = SKILL_PATH / "scripts" / "local_llm.py"
CODE_REFERENCE_PATH = SKILL_PATH / "scripts" / "code_reference.py"
MCP_SERVER_PATH = ROOT / "mcp" / "server.py"
MCP_LAUNCHER_PATH = ROOT / "mcp" / "launcher.mjs"
DOCUMENTATION_VALIDATOR_PATH = ROOT / "scripts" / "validate_documentation.py"
ONTOLOGY_QUALITY_VALIDATOR_PATH = ROOT / "scripts" / "validate_ontology_quality.py"
VISUALIZATION_QUALITY_VALIDATOR_PATH = (
    ROOT / "scripts" / "validate_visualization_quality.py"
)
VERSION = "0.6.1"
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
    "evals/discovery-cases.json",
    "evals/ontology-quality-cases.json",
    "evals/visualization-quality-cases.json",
    "assets/logo.png",
    "assets/logo-dark.png",
    "assets/composer-icon.png",
    "skills/apply-code-ontology/SKILL.md",
    "skills/apply-code-ontology/agents/openai.yaml",
    "skills/apply-code-ontology/references/companion-handoffs.md",
    "skills/apply-code-ontology/scripts/apply_workflow.py",
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
    "skills/manage-code-ontology/scripts/code_reference.py",
    "skills/manage-code-ontology/references/ai-data-contract.md",
    "skills/manage-code-ontology/references/workspace-setup.md",
    "skills/manage-code-ontology/references/code-reference.md",
    "skills/manage-code-ontology/references/code-reference.schema.json",
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
        "SECURITY.md": f"Version {VERSION}",
        "SUBMISSION.md": f"- Version: {VERSION}",
        "THIRD_PARTY_NOTICES.md": f"Code Ontology Companion {VERSION} vendors",
        "skills/manage-code-ontology/SKILL.md": f"Version {VERSION}",
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
        content = (ROOT / relative).read_text(encoding="utf-8")
        present = (
            re.search(r"\bversion\s+" + re.escape(VERSION) + r"(?![\d.])", content, re.IGNORECASE) is not None
            if relative == "SECURITY.md" else marker in content
        )
        if relative == "THIRD_PARTY_NOTICES.md":
            present = re.search(
                r"\bCode Ontology Companion\s+" + re.escape(VERSION) + r"(?:\s+candidate)?\s+vendors\b",
                content, re.IGNORECASE,
            ) is not None
        if not present:
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
    short_description = manifest["interface"].get("shortDescription")
    if not isinstance(short_description, str) or not 1 <= len(short_description) <= 30:
        fail("Manifest shortDescription must contain 1 to 30 characters")
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

    discovery = json.loads(
        (ROOT / "evals" / "discovery-cases.json").read_text(encoding="utf-8")
    )
    if set(discovery) != {
        "schema_version",
        "plugin_name",
        "skill_name",
        "skill_names",
        "plugin_version",
        "case_groups",
        "apply_case_groups",
    }:
        fail("Discovery eval top-level schema is invalid")
    if (
        discovery["schema_version"] != "1.0"
        or discovery["plugin_name"] != "code-ontology-companion"
        or discovery["skill_name"] != "manage-code-ontology"
        or discovery["skill_names"] != ["manage-code-ontology", "apply-code-ontology"]
        or discovery["plugin_version"] != VERSION
    ):
        fail("Discovery eval identity or version mismatch")
    groups = discovery["case_groups"]
    expected_counts = {"direct": 10, "indirect": 20, "negative": 20}
    if not isinstance(groups, dict) or set(groups) != set(expected_counts):
        fail("Discovery eval groups are invalid")

    case_keys = {
        "id",
        "locale",
        "prompt",
        "should_select_plugin",
        "should_select_skill",
        "expected_route",
        "boundary",
    }
    route = "code-ontology-companion/manage-code-ontology"
    identifiers: list[str] = []
    prompts: list[str] = []
    for group_name, expected_count in expected_counts.items():
        items = groups[group_name]
        if not isinstance(items, list) or len(items) != expected_count:
            fail(
                f"Discovery eval {group_name} count must be {expected_count}"
            )
        expected_locales = (
            {"en": 5, "ko": 5}
            if group_name == "direct"
            else {"en": 10, "ko": 10}
        )
        actual_locales = {
            locale: sum(item.get("locale") == locale for item in items)
            for locale in expected_locales
        }
        if actual_locales != expected_locales:
            fail(f"Discovery eval {group_name} must be bilingual: {actual_locales}")
        should_select = group_name != "negative"
        for item in items:
            if (
                not isinstance(item, dict)
                or set(item) != case_keys
                or not isinstance(item.get("id"), str)
                or not item["id"].startswith(f"{group_name}-")
                or item.get("locale") not in {"en", "ko"}
                or not isinstance(item.get("prompt"), str)
                or not item["prompt"].strip()
                or item.get("should_select_plugin") is not should_select
                or item.get("should_select_skill") is not should_select
                or not isinstance(item.get("expected_route"), str)
                or not item["expected_route"].strip()
                or not isinstance(item.get("boundary"), str)
                or not item["boundary"].strip()
            ):
                fail(f"Discovery eval case is incomplete: {item.get('id', '<missing>')}")
            prompt_folded = item["prompt"].casefold()
            if group_name == "direct" and not (
                "code ontology companion" in prompt_folded
                or "$manage-code-ontology" in prompt_folded
            ):
                fail(f"Direct discovery case does not name the product: {item['id']}")
            if group_name == "indirect" and (
                "code ontology companion" in prompt_folded
                or "manage-code-ontology" in prompt_folded
            ):
                fail(f"Indirect discovery case names the product: {item['id']}")
            if group_name == "negative" and item["expected_route"] == route:
                fail(f"Negative discovery case routes to this plugin: {item['id']}")
            if group_name != "negative" and item["expected_route"] != route:
                fail(f"Positive discovery case routes elsewhere: {item['id']}")
            identifiers.append(item["id"])
            prompts.append(prompt_folded.strip())

    if len(identifiers) != len(set(identifiers)):
        fail("Discovery eval case IDs must be unique")
    if len(prompts) != len(set(prompts)):
        fail("Discovery eval prompts must be unique")
    supported_boundaries = {
        "static-repository-map",
        "spring-di",
        "static-change-impact",
        "rdf-export",
        "snapshot-comparison",
        "registered-ontology-search",
        "provenance-lineage",
        "accessible-visualization",
        "python-pipeline",
        "adapter-coverage",
    }
    for group_name in ("direct", "indirect"):
        if {item["boundary"] for item in groups[group_name]} != supported_boundaries:
            fail(f"Discovery eval {group_name} capability coverage is incomplete")
    negative_boundaries = {item["boundary"] for item in groups["negative"]}
    for required in (
        "runtime-trace",
        "runtime-profiling",
        "adaptive-orchestration",
        "screenshot-action-inbox",
        "code-edit-deploy",
        "current-web-research",
    ):
        if required not in negative_boundaries:
            fail(f"Discovery eval negative boundary is missing: {required}")
    negative_routes = {item["expected_route"] for item in groups["negative"]}
    for required in ("adaptive-codex-orchestrator", "screenshot-action-inbox"):
        if required not in negative_routes:
            fail(f"Discovery eval cross-plugin route is missing: {required}")

    apply_groups = discovery["apply_case_groups"]
    if not isinstance(apply_groups, dict) or set(apply_groups) != set(expected_counts):
        fail("Application discovery eval groups are invalid")
    apply_route = "code-ontology-companion/apply-code-ontology"
    for group_name, items in apply_groups.items():
        if not isinstance(items, list) or len(items) < 2:
            fail(f"Application discovery eval {group_name} needs English and Korean cases")
        if {item.get("locale") for item in items} != {"en", "ko"}:
            fail(f"Application discovery eval {group_name} must be bilingual")
        for item in items:
            if (
                not isinstance(item, dict)
                or set(item) != case_keys
                or not isinstance(item.get("id"), str)
                or not item["id"].startswith(f"apply-{group_name}-")
                or any(not isinstance(item.get(key), str) or not item[key].strip()
                       for key in ("prompt", "expected_route", "boundary"))
                or not isinstance(item.get("should_select_plugin"), bool)
                or not isinstance(item.get("should_select_skill"), bool)
            ):
                fail(f"Application discovery eval is incomplete: {item.get('id', '<missing>')}")
            selects_apply = item["expected_route"] == apply_route
            if group_name != "negative" and not (
                selects_apply and item["should_select_plugin"] and item["should_select_skill"]
            ):
                fail(f"Application discovery positive case must route to apply: {item['id']}")
            if group_name == "negative" and (selects_apply or item["should_select_skill"]):
                fail(f"Application discovery negative case activates apply: {item['id']}")
            identifiers.append(item["id"])
            prompts.append(item["prompt"].casefold().strip())
    if len(identifiers) != len(set(identifiers)) or len(prompts) != len(set(prompts)):
        fail("Both skill discovery suites must have unique IDs and prompts")

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
    for path in (CORE_PATH, COMPANION_PATH, MCP_SERVER_PATH, CODE_REFERENCE_PATH, APPLY_WORKFLOW_PATH):
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
        if not path.is_file() or path.name == ".DS_Store":
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
    skill_names = {path.parent.name for path in (ROOT / "skills").glob("*/SKILL.md")}
    if skill_names != {"manage-code-ontology", "apply-code-ontology"}:
        fail("The release must expose exactly the manage and apply skills")
    for skill_path in (SKILL_PATH, APPLY_SKILL_PATH):
        name = skill_path.name
        skill = (skill_path / "SKILL.md").read_text(encoding="utf-8")
        agent = (skill_path / "agents" / "openai.yaml").read_text(encoding="utf-8")
        if not skill.startswith(f"---\nname: {name}\n"):
            fail(f"Unexpected {name} skill frontmatter")
        frontmatter = skill.split("---", 2)[1]
        if not re.search(r"^description:\s*\S", frontmatter, re.MULTILINE):
            fail(f"{name} must declare a discoverable description")
        if f"${name}" not in agent:
            fail(f"{name} default prompt must invoke its own skill")
        short_description = re.search(r'^\s*short_description:\s*"([^"\n]+)"\s*$', agent, re.MULTILINE)
        if not short_description or not 1 <= len(short_description.group(1)) <= 30:
            fail(f"{name} short_description must contain 1 to 30 characters")
        for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", skill):
            if "://" in target or target.startswith("#"):
                continue
            resolved = (skill_path / target.split("#", 1)[0]).resolve()
            if not resolved.is_relative_to((ROOT / "skills").resolve()) or not resolved.is_file():
                fail(f"{name} links to a missing or unpackaged skill dependency: {target}")
    openai_yaml = (SKILL_PATH / "agents" / "openai.yaml").read_text(encoding="utf-8")
    for marker in (
        "$manage-code-ontology",
        "relationship evidence",
        "adapter coverage",
        "default 3D",
    ):
        if marker not in openai_yaml:
            fail(f"openai.yaml is missing current workflow metadata: {marker}")
    skill_text = (SKILL_PATH / "SKILL.md").read_text(encoding="utf-8")
    description = re.search(r'^\s*short_description:\s*"([^"\n]+)"\s*$', openai_yaml, re.MULTILINE)
    if not description or not 1 <= len(description.group(1)) <= 30:
        fail("Skill short_description must contain 1 to 30 characters")
    if not skill_text.startswith("---\nname: manage-code-ontology\n"):
        fail("Unexpected skill frontmatter")
    # Setup detail can be disclosed progressively through linked references;
    # the safety contract is required across that verified local workflow.
    required_references = ("workspace-setup.md", "local-mcp.md", "local-llm.md", "ai-data-contract.md", "code-reference.md")
    for reference in required_references:
        if f"references/{reference}" not in skill_text:
            fail(f"Skill does not route to required workflow reference: {reference}")
    workflow_text = skill_text + "\n" + "\n".join(
        (SKILL_PATH / "references" / name).read_text(encoding="utf-8") for name in required_references
    )
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
        if marker.casefold() not in workflow_text.casefold():
            fail(f"Skill is missing a required supported-workflow marker: {marker}")
    for label, pattern in (
        ("3D primary with fallback", r"(?s)3D workbench.*2D fallback"),
        ("static evidence limitation", r"(?s)static.*(?:not runtime|runtime causality|runtime proof)"),
        ("current user authorization", r"(?s)approved.*not current user permission"),
        ("snapshot identity", r"(?s)pin.*snapshot ID"),
        ("no implicit upload", r"(?s)never upload.*portable"),
    ):
        if not re.search(pattern, skill_text, re.IGNORECASE):
            fail(f"Skill is missing a required evidence/workflow contract: {label}")


def validate_application_routing() -> None:
    """Check actual helper dispatch without treating a plan as activation."""

    with tempfile.TemporaryDirectory(prefix="code-ontology-route-validation-") as raw:
        temporary = Path(raw)
        environment = dict(os.environ)
        for name in ("PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP"):
            environment.pop(name, None)
        environment.update({
            "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1",
            "CODE_ONTOLOGY_HOME": str(temporary / "registry"),
        })
        cases = (
            ({}, []),
            ({"code": {"installed": True}}, []),
            ({"code": {"installed": True, "skill_exposed": True,
                       "mcp_exposed": False, "verified_cli": True}}, ["code"]),
        )
        for capabilities, selected in cases:
            process = subprocess.run(
                [sys.executable, str(APPLY_WORKFLOW_PATH), "plan",
                 "--capabilities", json.dumps(capabilities)],
                cwd=temporary, env=environment, text=True,
                capture_output=True, timeout=30, check=False,
            )
            if process.returncode:
                fail(f"Application routing helper failed: {process.stderr.strip()}")
            payload = json.loads(process.stdout)
            if (
                payload.get("selectedProducts") != selected
                or payload.get("availableCount") != len(selected)
                or payload.get("executionPerformed") is not False
                or payload.get("activationStatus") != "NOT_EXECUTED"
                or any(temporary.rglob("*"))
            ):
                fail("Application routing fabricated capability, activation, or state")


def main() -> int:
    validate_required_files()
    validate_release_governance()
    validate_manifest()
    validate_evals()
    validate_runtime_boundaries()
    validate_visualization_assets()
    validate_text_hygiene()
    validate_skill_metadata()
    validate_application_routing()
    run([sys.executable, str(DOCUMENTATION_VALIDATOR_PATH)])
    run(
        [
            sys.executable,
            "-m",
            "py_compile",
            str(CORE_PATH),
            str(COMPANION_PATH),
            str(LOCAL_LLM_PATH),
            str(CODE_REFERENCE_PATH),
            str(APPLY_WORKFLOW_PATH),
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
