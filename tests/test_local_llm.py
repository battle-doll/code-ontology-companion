from __future__ import annotations

import hashlib
import http.server
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "skills" / "manage-code-ontology" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import companion  # noqa: E402
import local_llm  # noqa: E402


FIXTURE = ROOT / "tests" / "fixtures" / "sample-app"


class LocalLLMTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.repo = self.base / "repo"
        shutil.copytree(FIXTURE, self.repo)
        self.workspace = self.base / "workspace"
        self.data_home = self.base / "data"
        self.environment = mock.patch.dict(
            os.environ,
            {"CODE_ONTOLOGY_HOME": str(self.data_home)},
            clear=False,
        )
        self.environment.start()
        companion.initialize(
            str(self.repo),
            str(self.workspace),
            True,
            label="local-llm-test",
        )

    def tearDown(self) -> None:
        self.environment.stop()
        self.temporary.cleanup()

    @staticmethod
    def model(name: str = "qwen3:8b", digest_char: str = "a") -> dict:
        return {
            "name": name,
            "digest": "sha256:" + digest_char * 64,
            "size": 4_000_000_000,
            "format": "gguf",
        }

    def configure(self) -> dict:
        model = self.model()
        with (
            mock.patch.object(
                local_llm,
                "detect",
                return_value={"supportedProviderDetected": True},
            ),
            mock.patch.object(local_llm, "_tag_models", return_value=([model], 0)),
            mock.patch.object(
                local_llm,
                "_verify_model",
                return_value={**model, "capabilities": ["completion"]},
            ),
        ):
            return local_llm.configure(str(self.workspace), model["name"], True)

    def test_system_prompt_and_output_schema_use_the_canonical_role_set(self) -> None:
        prompt_roles = {
            role.strip()
            for role in local_llm.PIPELINE_ROLE_PROMPT_LIST.split(",")
            if role.strip()
        }
        suggestion_schema = local_llm.OUTPUT_SCHEMA["properties"]["suggestions"][
            "items"
        ]
        schema_roles = set(suggestion_schema["properties"]["pipeline_role"]["enum"])

        self.assertEqual(local_llm.ALLOWED_PIPELINE_ROLES, prompt_roles)
        self.assertEqual(local_llm.ALLOWED_PIPELINE_ROLES, schema_roles)
        self.assertIn("Validate", local_llm.SYSTEM_PROMPT)
        self.assertNotIn("Sink", local_llm.SYSTEM_PROMPT)

    def test_detect_is_read_only_and_does_not_connect_or_execute(self) -> None:
        with (
            mock.patch.object(
                local_llm.shutil,
                "which",
                side_effect=lambda name: "/opt/bin/ollama" if name == "ollama" else None,
            ),
            mock.patch.object(local_llm, "_request_json") as request,
        ):
            result = local_llm.detect()

        self.assertTrue(result["supportedProviderDetected"])
        self.assertFalse(result["networkAccess"])
        self.assertFalse(result["processExecuted"])
        self.assertFalse(result["filesWritten"])
        request.assert_not_called()

    def test_absent_runtime_does_not_recommend_configuration(self) -> None:
        with mock.patch.object(local_llm.shutil, "which", return_value=None):
            result = local_llm.detect()
        self.assertFalse(result["supportedProviderDetected"])
        self.assertEqual(
            "Do not ask to configure local LLM enrichment.", result["nextStep"]
        )

    def test_authorization_is_required_before_connection_or_write(self) -> None:
        config = self.workspace / local_llm.CONFIG_NAME
        with mock.patch.object(local_llm, "_request_json") as request:
            with self.assertRaises(local_llm.LocalLLMError):
                local_llm.probe(False)
            with self.assertRaises(local_llm.LocalLLMError):
                local_llm.configure(str(self.workspace), None, False)
            with self.assertRaises(local_llm.LocalLLMError):
                local_llm.enrich(str(self.workspace), False)

        request.assert_not_called()
        self.assertFalse(config.exists())

    def test_transport_connects_only_to_literal_loopback(self) -> None:
        response_body = json.dumps({"models": []}).encode("utf-8")

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                self.server.request_path = self.path
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(response_body)))
                self.end_headers()
                self.wfile.write(response_body)

            def log_message(self, *_args) -> None:
                return

        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with mock.patch.object(local_llm, "PORT", server.server_address[1]):
                result = local_llm._request_json("GET", "/api/tags")
            self.assertEqual({"models": []}, result)
            self.assertEqual("/api/tags", server.request_path)
            self.assertEqual("127.0.0.1", server.server_address[0])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_configure_writes_bounded_workspace_only_config(self) -> None:
        result = self.configure()
        config_path = self.workspace / local_llm.CONFIG_NAME
        config = json.loads(config_path.read_text(encoding="utf-8"))

        self.assertEqual("configured", result["status"])
        self.assertEqual("0.4.0", local_llm.VERSION)
        self.assertEqual(local_llm.VERSION, config["pluginVersion"])
        self.assertEqual({"host": "127.0.0.1", "port": 11434}, config["endpoint"])
        self.assertEqual("on-demand", config["mode"])
        self.assertEqual("portable-ontology-metadata/v1", config["dataScope"])
        self.assertTrue(config["model"]["localMetadataVerified"])
        self.assertNotIn("localArtifactVerified", config["model"])
        self.assertNotIn(str(self.repo), json.dumps(config))
        self.assertNotIn("apiKey", json.dumps(config))
        if os.name == "posix":
            self.assertEqual(0o600, config_path.stat().st_mode & 0o777)
        with mock.patch.object(local_llm, "_request_json") as request:
            status = local_llm.status(str(self.workspace))
        self.assertTrue(status["enabled"])
        self.assertFalse(status["networkAccess"])
        request.assert_not_called()

    def test_previous_compatible_plugin_version_remains_enabled_and_disableable(self) -> None:
        self.configure()
        path = self.workspace / local_llm.CONFIG_NAME
        baseline = json.loads(path.read_text(encoding="utf-8"))
        for plugin_version in ("0.3.1", "0.3.4", "0.3.5"):
            with self.subTest(plugin_version=plugin_version):
                value = dict(baseline)
                value["pluginVersion"] = plugin_version
                value["enabled"] = True
                value.pop("disabledAt", None)
                path.write_text(json.dumps(value), encoding="utf-8")

                with mock.patch.object(local_llm, "_request_json") as request:
                    status = local_llm.status(str(self.workspace))
                    disabled = local_llm.disable(str(self.workspace), True)
                self.assertTrue(status["enabled"])
                self.assertEqual("disabled", disabled["status"])
                self.assertFalse(local_llm.status(str(self.workspace))["enabled"])
                preserved = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(plugin_version, preserved["pluginVersion"])
                request.assert_not_called()

    def test_future_old_or_malformed_plugin_versions_fail_closed(self) -> None:
        self.configure()
        path = self.workspace / local_llm.CONFIG_NAME
        baseline = json.loads(path.read_text(encoding="utf-8"))
        for plugin_version in (
            "0.4.1",
            "1.0.0",
            "0.3.0",
            "0.3",
            "v0.3.1",
            "00.3.1",
            True,
            None,
        ):
            with self.subTest(plugin_version=plugin_version):
                value = dict(baseline)
                value["pluginVersion"] = plugin_version
                path.write_text(json.dumps(value), encoding="utf-8")
                with self.assertRaisesRegex(
                    local_llm.LocalLLMError, "configuration is invalid"
                ):
                    local_llm.status(str(self.workspace))

    def test_configuration_links_are_rejected(self) -> None:
        if not hasattr(os, "symlink"):
            self.skipTest("symbolic links are unavailable")
        outside = self.base / "outside.json"
        outside.write_text("{}\n", encoding="utf-8")
        os.symlink(outside, self.workspace / local_llm.CONFIG_NAME)
        with self.assertRaises(local_llm.LocalLLMError):
            local_llm.status(str(self.workspace))

    def test_tampered_configuration_is_rejected(self) -> None:
        self.configure()
        path = self.workspace / local_llm.CONFIG_NAME
        value = json.loads(path.read_text(encoding="utf-8"))
        value["endpoint"] = {"host": "192.168.1.8", "port": 11434}
        value["unexpected"] = "ignored-by-nobody"
        path.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(local_llm.LocalLLMError, "configuration is invalid"):
            local_llm.status(str(self.workspace))

    @unittest.skipUnless(os.name == "posix", "owner-only mode check requires POSIX")
    def test_permissive_configuration_mode_is_rejected(self) -> None:
        self.configure()
        path = self.workspace / local_llm.CONFIG_NAME
        path.chmod(0o644)
        with self.assertRaisesRegex(local_llm.LocalLLMError, "owner-only mode 0600"):
            local_llm.status(str(self.workspace))

    def test_duplicate_and_nonfinite_model_json_is_rejected(self) -> None:
        with self.assertRaisesRegex(local_llm.LocalLLMError, "duplicate"):
            local_llm._parse_json('{"suggestions":[],"suggestions":[]}', "completion")
        with self.assertRaisesRegex(local_llm.LocalLLMError, "non-finite"):
            local_llm._parse_json('{"confidence":NaN}', "completion")
        with self.assertRaisesRegex(local_llm.LocalLLMError, "top-level"):
            local_llm._validated_suggestions(
                {"suggestions": [], "explanation": "unrequested"}, set()
            )

    def test_unsupported_role_is_discarded_but_unknown_node_still_fails(self) -> None:
        suggestions, discarded_roles, discarded_duplicates, discarded_conflicts = (
            local_llm._validated_suggestions(
                {
                    "suggestions": [
                        {
                            "node_id": "node-1",
                            "pipeline_role": "Transform",
                            "confidence": 0.8,
                        },
                        {
                            "node_id": "node-2",
                            "pipeline_role": "Test",
                            "confidence": 0.9,
                        },
                    ]
                },
                {"node-1", "node-2"},
            )
        )
        self.assertEqual(1, discarded_roles)
        self.assertEqual(0, discarded_duplicates)
        self.assertEqual(0, discarded_conflicts)
        self.assertEqual(["node-1"], [item["nodeId"] for item in suggestions])
        with self.assertRaisesRegex(local_llm.LocalLLMError, "unknown node"):
            local_llm._validated_suggestions(
                {
                    "suggestions": [
                        {
                            "node_id": "unknown",
                            "pipeline_role": "Test",
                            "confidence": 0.9,
                        }
                    ]
                },
                {"node-1"},
            )

    def test_matching_duplicate_uses_lower_confidence_and_conflict_is_quarantined(self) -> None:
        suggestions, discarded_roles, discarded_duplicates, discarded_conflicts = (
            local_llm._validated_suggestions(
                {
                    "suggestions": [
                        {
                            "node_id": "node-1",
                            "pipeline_role": "Transform",
                            "confidence": 0.9,
                        },
                        {
                            "node_id": "node-1",
                            "pipeline_role": "Transform",
                            "confidence": 0.7,
                        },
                    ]
                },
                {"node-1"},
            )
        )
        self.assertEqual(0, discarded_roles)
        self.assertEqual(1, discarded_duplicates)
        self.assertEqual(0, discarded_conflicts)
        self.assertEqual(0.7, suggestions[0]["confidence"])
        suggestions, discarded_roles, discarded_duplicates, discarded_conflicts = (
            local_llm._validated_suggestions(
                {
                    "suggestions": [
                        {
                            "node_id": "node-1",
                            "pipeline_role": "Transform",
                            "confidence": 0.8,
                        },
                        {
                            "node_id": "node-1",
                            "pipeline_role": "Load",
                            "confidence": 0.8,
                        },
                    ]
                },
                {"node-1"},
            )
        )
        self.assertEqual([], suggestions)
        self.assertEqual(0, discarded_roles)
        self.assertEqual(0, discarded_duplicates)
        self.assertEqual(2, discarded_conflicts)

    def test_recursive_model_json_is_rejected_as_a_local_error(self) -> None:
        with mock.patch.object(local_llm.json, "loads", side_effect=RecursionError):
            with self.assertRaisesRegex(local_llm.LocalLLMError, "not valid JSON"):
                local_llm._parse_json('{"suggestions":[]}', "completion")

    def test_portable_candidates_reject_private_or_control_text(self) -> None:
        document = {
            "nodes": [
                {
                    "id": "safe-id",
                    "type": "Function",
                    "name": "safe",
                    "qualified_name": "pkg.safe",
                    "path": "/Users/alice/private.py",
                },
                {
                    "id": "bad\u202eid",
                    "type": "Function",
                    "name": "bad",
                    "qualified_name": "pkg.bad",
                    "path": "pkg/bad.py",
                },
                {
                    "id": "too-long-" + "x" * 1_000,
                    "type": "Function",
                    "name": "long",
                    "qualified_name": "pkg.long",
                    "path": "pkg/long.py",
                },
            ],
            "edges": [],
        }
        candidates = local_llm._portable_candidates(document)
        self.assertEqual(1, len(candidates))
        self.assertEqual("safe-id", candidates[0]["node_id"])
        self.assertEqual("", candidates[0]["repository_relative_path"])

    def test_portable_relation_collection_stays_deterministically_bounded(self) -> None:
        nodes = [
            {
                "id": "candidate",
                "type": "Function",
                "name": "candidate",
                "qualified_name": "pkg.candidate",
                "path": "pkg/candidate.py",
            }
        ]
        edges = []
        for index in reversed(range(100)):
            target_id = f"target-{index:03d}"
            nodes.append(
                {
                    "id": target_id,
                    "type": "ExternalCallable",
                    "name": f"target_{index:03d}",
                    "qualified_name": f"pkg.target_{index:03d}",
                }
            )
            edges.append(
                {"source": "candidate", "target": target_id, "type": "CALLS"}
            )

        candidates = local_llm._portable_candidates({"nodes": nodes, "edges": edges})

        self.assertEqual(1, len(candidates))
        relations = candidates[0]["relations"]
        self.assertEqual(local_llm.MAX_RELATIONS_PER_CANDIDATE, len(relations))
        self.assertEqual(
            [f"pkg.target_{index:03d}" for index in range(12)],
            [relation["target_qualified_name"] for relation in relations],
        )

    def test_portable_candidate_cap_is_80_and_deterministic(self) -> None:
        nodes = [
            {
                "id": f"node-{index:03d}",
                "type": "Function",
                "name": f"function_{index:03d}",
                "qualified_name": f"pkg.function_{index:03d}",
                "path": f"pkg/function_{index:03d}.py",
            }
            for index in reversed(range(100))
        ]

        candidates = local_llm._portable_candidates({"nodes": nodes, "edges": []})

        self.assertEqual(local_llm.MAX_CANDIDATES, len(candidates))
        self.assertEqual(
            [f"node-{index:03d}" for index in range(local_llm.MAX_CANDIDATES)],
            [candidate["node_id"] for candidate in candidates],
        )

    def test_transport_timeout_is_distinct_from_unavailable(self) -> None:
        timeout_connection = mock.Mock()
        timeout_connection.getresponse.side_effect = TimeoutError()
        with mock.patch.object(
            local_llm.http.client,
            "HTTPConnection",
            return_value=timeout_connection,
        ):
            with self.assertRaisesRegex(
                local_llm.LocalLLMError,
                "timed out after 17 seconds",
            ):
                local_llm._request_json(
                    "GET",
                    "/api/tags",
                    timeout_seconds=17,
                )
        timeout_connection.close.assert_called_once()

        unavailable_connection = mock.Mock()
        unavailable_connection.request.side_effect = ConnectionRefusedError()
        with mock.patch.object(
            local_llm.http.client,
            "HTTPConnection",
            return_value=unavailable_connection,
        ):
            with self.assertRaisesRegex(
                local_llm.LocalLLMError,
                "unavailable on 127.0.0.1",
            ):
                local_llm._request_json("GET", "/api/tags")
        unavailable_connection.close.assert_called_once()

    def test_single_json_fence_is_the_only_completion_wrapper_accepted(self) -> None:
        expected = {"suggestions": []}
        for opening in ("```json", "```JSON", "```"):
            with self.subTest(opening=opening):
                self.assertEqual(
                    expected,
                    local_llm._parse_completion_json(
                        f"{opening}\n{{\"suggestions\": []}}\n```"
                    ),
                )
        for invalid in (
            "before\n```json\n{\"suggestions\": []}\n```",
            "```json\n{\"suggestions\": []}\n```\nafter",
            "```json {\"suggestions\": []}\n```",
            "```json\n```\n```",
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(local_llm.LocalLLMError):
                    local_llm._parse_completion_json(invalid)

    def test_enrich_parser_uses_bounded_production_timeout(self) -> None:
        parsed = local_llm.build_parser().parse_args(
            ["enrich", "--workspace", str(self.workspace), "--authorized"]
        )
        self.assertEqual(local_llm.DEFAULT_TIMEOUT_SECONDS, parsed.timeout_seconds)
        self.assertEqual(180, parsed.timeout_seconds)

    def test_cloud_and_unverifiable_models_are_rejected(self) -> None:
        response = {
            "models": [
                {
                    "name": "remote:cloud",
                    "digest": "sha256:" + "a" * 64,
                    "size": 1,
                    "details": {"format": "remote"},
                },
                {
                    "name": "gpt-oss:120b-cloud",
                    "digest": "c" * 64,
                    "size": 1,
                    "details": {"format": "gguf"},
                },
                {
                    "name": "missing-digest",
                    "size": 1,
                    "details": {"format": "gguf"},
                },
                {
                    "name": "/Users/alice/private-model",
                    "digest": "sha256:" + "b" * 64,
                    "size": 1,
                    "details": {"format": "gguf"},
                },
            ]
        }
        with mock.patch.object(local_llm, "_request_json", return_value=response):
            models, rejected = local_llm._tag_models()
        self.assertEqual([], models)
        self.assertEqual(4, rejected)
        with mock.patch.object(
            local_llm,
            "_request_json",
            return_value={"remote_host": "example.invalid", "models": [self.model()]},
        ):
            with self.assertRaisesRegex(local_llm.LocalLLMError, "remote or cloud"):
                local_llm._tag_models()

    def test_bare_ollama_digest_is_canonicalized(self) -> None:
        response = {
            "models": [
                {
                    "name": "qwen3:8b",
                    "digest": "a" * 64,
                    "size": 4_000_000_000,
                    "details": {"format": "gguf"},
                }
            ]
        }
        with mock.patch.object(local_llm, "_request_json", return_value=response):
            models, rejected = local_llm._tag_models()
        self.assertEqual(0, rejected)
        self.assertEqual("sha256:" + "a" * 64, models[0]["digest"])

    def test_enrichment_is_inferred_sidecar_and_does_not_change_observed_graph(self) -> None:
        self.configure()
        snapshot_id = companion.status(str(self.workspace))["snapshotId"]
        ontology_path = self.workspace / "snapshots" / snapshot_id / "ontology.json"
        before = hashlib.sha256(ontology_path.read_bytes()).hexdigest()
        captured: dict = {}

        def chat(method, path, payload=None, **kwargs):
            self.assertEqual("POST", method)
            self.assertEqual("/api/chat", path)
            captured.update(payload)
            user_content = payload["messages"][1]["content"]
            input_document = json.loads(user_content)
            node_id = input_document["candidates"][0]["node_id"]
            return {
                "done": True,
                "done_reason": "stop",
                "message": {
                    "content": json.dumps(
                        {
                            "suggestions": [
                                {
                                    "node_id": node_id,
                                    "pipeline_role": "Orchestrate",
                                    "confidence": 0.81,
                                }
                            ]
                        }
                    )
                }
            }

        model = self.model()
        with (
            mock.patch.object(local_llm, "_tag_models", return_value=([model], 0)),
            mock.patch.object(
                local_llm,
                "_verify_model",
                return_value={**model, "capabilities": ["completion"]},
            ),
            mock.patch.object(local_llm, "_request_json", side_effect=chat),
        ):
            result = local_llm.enrich(str(self.workspace), True)

        self.assertEqual("created", result["status"])
        self.assertEqual("inferred", result["evidenceType"])
        self.assertFalse(result["observedOntologyChanged"])
        self.assertEqual(before, hashlib.sha256(ontology_path.read_bytes()).hexdigest())
        user_payload = captured["messages"][1]["content"]
        self.assertEqual(0, captured["keep_alive"])
        self.assertIs(False, captured["think"])
        self.assertEqual(
            local_llm.REQUEST_MAX_OUTPUT_TOKENS,
            captured["options"]["num_predict"],
        )
        self.assertEqual(
            local_llm.REQUEST_CONTEXT_TOKENS,
            captured["options"]["num_ctx"],
        )
        self.assertNotIn(str(self.repo), user_payload)
        self.assertNotIn("sourceFingerprint", user_payload)
        self.assertNotIn(snapshot_id, user_payload)
        self.assertNotIn("this file must never be read", user_payload)
        sidecar_path = self.workspace / result["filesWritten"][0]
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        self.assertEqual("inferred", sidecar["evidenceType"])
        self.assertFalse(sidecar["authority"]["changesObservedOntology"])
        self.assertNotIn("messages", sidecar)
        self.assertNotIn("rawResponse", sidecar)

    def test_large_enrichment_is_batched_and_writes_one_sidecar(self) -> None:
        self.configure()
        candidates = [
            {
                "node_id": f"python:function:pkg.function_{index:03d}",
                "type": "Function",
                "name": f"function_{index:03d}",
                "qualified_name": f"pkg.function_{index:03d}",
                "repository_relative_path": f"pkg/function_{index:03d}.py",
                "relations": [
                    {
                        "type": "CALLS",
                        "target_type": "ExternalCallable",
                        "target_name": "dependency",
                        "target_qualified_name": "pkg.dependency",
                    }
                ],
            }
            for index in range(local_llm.MAX_CANDIDATES)
        ]
        requests: list[dict] = []

        def chat(method, path, payload=None, **kwargs):
            self.assertEqual("POST", method)
            self.assertEqual("/api/chat", path)
            requests.append(payload)
            input_document = json.loads(payload["messages"][1]["content"])
            return {
                "done": True,
                "done_reason": "stop",
                "message": {
                    "content": json.dumps(
                        {
                            "suggestions": [
                                {
                                    "node_id": candidate["node_id"],
                                    "pipeline_role": "Transform",
                                    "confidence": 0.75,
                                }
                                for candidate in input_document["candidates"]
                            ]
                        }
                    )
                },
            }

        model = self.model()
        with (
            mock.patch.object(local_llm, "_portable_candidates", return_value=candidates),
            mock.patch.object(local_llm, "_tag_models", return_value=([model], 0)),
            mock.patch.object(
                local_llm,
                "_verify_model",
                return_value={**model, "capabilities": ["completion"]},
            ),
            mock.patch.object(local_llm, "_request_json", side_effect=chat),
        ):
            result = local_llm.enrich(str(self.workspace), True)

        self.assertGreater(len(requests), 1)
        self.assertEqual(len(requests), result["requestCount"])
        delivered = []
        for request in requests:
            input_document = json.loads(request["messages"][1]["content"])
            delivered.extend(item["node_id"] for item in input_document["candidates"])
            self.assertLessEqual(
                len(input_document["candidates"]),
                local_llm.MAX_CANDIDATES_PER_REQUEST,
            )
            self.assertLessEqual(
                len(local_llm._json_bytes(input_document)),
                local_llm.MAX_REQUEST_INPUT_BYTES,
            )
            self.assertIs(False, request["think"])
            self.assertEqual(0, request["keep_alive"])
            self.assertEqual(
                local_llm.REQUEST_MAX_OUTPUT_TOKENS,
                request["options"]["num_predict"],
            )
            self.assertEqual(
                local_llm.REQUEST_CONTEXT_TOKENS,
                request["options"]["num_ctx"],
            )
        self.assertEqual(
            [candidate["node_id"] for candidate in candidates],
            delivered,
        )
        sidecar_path = self.workspace / result["filesWritten"][0]
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        self.assertEqual(len(requests), sidecar["input"]["requestCount"])
        self.assertEqual(len(candidates), sidecar["input"]["candidateCount"])
        self.assertEqual(
            local_llm.REQUEST_CONTEXT_TOKENS,
            sidecar["input"]["contextTokens"],
        )
        self.assertEqual(len(candidates), len(sidecar["suggestions"]))
        self.assertEqual(0, sidecar["validation"]["discardedUnsupportedRoleSuggestions"])
        self.assertEqual(0, sidecar["validation"]["discardedDuplicateSuggestions"])
        self.assertEqual(0, sidecar["validation"]["discardedConflictingRoleSuggestions"])
        self.assertNotIn("messages", json.dumps(sidecar))
        if os.name == "posix":
            self.assertEqual(0o600, sidecar_path.stat().st_mode & 0o777)

    def test_later_batch_timeout_is_atomic(self) -> None:
        self.configure()
        candidates = [
            {
                "node_id": f"python:function:pkg.function_{index:03d}",
                "type": "Function",
                "name": f"function_{index:03d}",
                "qualified_name": f"pkg.function_{index:03d}",
                "repository_relative_path": f"pkg/function_{index:03d}.py",
                "relations": [],
            }
            for index in range(local_llm.MAX_CANDIDATES_PER_REQUEST + 1)
        ]
        calls = 0

        def chat(_method, _path, payload=None, **_kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise local_llm.LocalLLMError(
                    "Local Ollama request timed out after 180 seconds."
                )
            input_document = json.loads(payload["messages"][1]["content"])
            return {
                "done": True,
                "done_reason": "stop",
                "message": {"content": json.dumps({"suggestions": []})},
            }

        model = self.model()
        with (
            mock.patch.object(local_llm, "_portable_candidates", return_value=candidates),
            mock.patch.object(local_llm, "_tag_models", return_value=([model], 0)),
            mock.patch.object(
                local_llm,
                "_verify_model",
                return_value={**model, "capabilities": ["completion"]},
            ),
            mock.patch.object(local_llm, "_request_json", side_effect=chat),
        ):
            with self.assertRaisesRegex(
                local_llm.LocalLLMError,
                r"batch 2/2 failed \(inputBytes=\d+\): .*timed out",
            ):
                local_llm.enrich(str(self.workspace), True)

        self.assertEqual(2, calls)
        self.assertFalse((self.workspace / "enrichments").exists())

    def test_output_token_limit_is_rejected_without_sidecar(self) -> None:
        self.configure()
        model = self.model()
        response = {
            "done": True,
            "done_reason": "length",
            "message": {"content": json.dumps({"suggestions": []})},
        }
        with (
            mock.patch.object(local_llm, "_tag_models", return_value=([model], 0)),
            mock.patch.object(
                local_llm,
                "_verify_model",
                return_value={**model, "capabilities": ["completion"]},
            ),
            mock.patch.object(local_llm, "_request_json", return_value=response),
        ):
            with self.assertRaisesRegex(local_llm.LocalLLMError, "output token limit"):
                local_llm.enrich(str(self.workspace), True)
        self.assertFalse((self.workspace / "enrichments").exists())

    def test_unknown_or_malformed_suggestion_fails_without_sidecar(self) -> None:
        self.configure()
        model = self.model()
        response = {
            "message": {
                "content": json.dumps(
                    {
                        "suggestions": [
                            {
                                "node_id": "unknown-node",
                                "pipeline_role": "Load",
                                "confidence": 1.0,
                            }
                        ]
                    }
                )
            }
        }
        with (
            mock.patch.object(local_llm, "_tag_models", return_value=([model], 0)),
            mock.patch.object(
                local_llm,
                "_verify_model",
                return_value={**model, "capabilities": ["completion"]},
            ),
            mock.patch.object(local_llm, "_request_json", return_value=response),
        ):
            with self.assertRaises(local_llm.LocalLLMError):
                local_llm.enrich(str(self.workspace), True)
        self.assertFalse((self.workspace / "enrichments").exists())

    def test_chat_remote_marker_fails_without_sidecar(self) -> None:
        self.configure()
        model = self.model()
        response = {
            "remote_model": "provider/model",
            "message": {"content": json.dumps({"suggestions": []})},
        }
        with (
            mock.patch.object(local_llm, "_tag_models", return_value=([model], 0)),
            mock.patch.object(
                local_llm,
                "_verify_model",
                return_value={**model, "capabilities": ["completion"]},
            ),
            mock.patch.object(local_llm, "_request_json", return_value=response),
        ):
            with self.assertRaisesRegex(local_llm.LocalLLMError, "remote or cloud"):
                local_llm.enrich(str(self.workspace), True)
        self.assertFalse((self.workspace / "enrichments").exists())

    def test_model_digest_change_fails_before_inference(self) -> None:
        self.configure()
        changed = self.model(digest_char="b")
        with (
            mock.patch.object(local_llm, "_tag_models", return_value=([changed], 0)),
            mock.patch.object(local_llm, "_request_json") as request,
        ):
            with self.assertRaisesRegex(local_llm.LocalLLMError, "digest changed"):
                local_llm.enrich(str(self.workspace), True)
        request.assert_not_called()
        self.assertFalse((self.workspace / "enrichments").exists())

    def test_disable_preserves_existing_sidecars_and_makes_no_connection(self) -> None:
        self.configure()
        enrichment = self.workspace / "enrichments" / "existing"
        enrichment.mkdir(parents=True)
        preserved = enrichment / "finding.json"
        preserved.write_text("{}\n", encoding="utf-8")
        with mock.patch.object(local_llm, "_request_json") as request:
            result = local_llm.disable(str(self.workspace), True)
        self.assertEqual("disabled", result["status"])
        self.assertTrue(preserved.is_file())
        self.assertFalse(local_llm.status(str(self.workspace))["enabled"])
        request.assert_not_called()

    def test_unconfigured_mutations_return_bounded_json_errors(self) -> None:
        for command in ("enrich", "disable"):
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                result = local_llm.main(
                    [
                        command,
                        "--workspace",
                        str(self.workspace),
                        "--authorized",
                    ]
                )
            self.assertEqual(1, result)
            error = json.loads(stderr.getvalue())
            self.assertEqual("error", error["status"])
            self.assertIn("not configured", error["message"])
        self.assertFalse((self.workspace / local_llm.CONFIG_NAME).exists())
        self.assertFalse((self.workspace / "enrichments").exists())

    def test_core_sync_never_calls_local_llm(self) -> None:
        self.configure()
        source = self.repo / "extra.py"
        source.write_text("def added():\n    return 1\n", encoding="utf-8")
        with mock.patch.object(local_llm, "_request_json") as request:
            result = companion.sync(str(self.workspace), trigger="test-no-llm")
        self.assertEqual("promoted", result["status"])
        request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
