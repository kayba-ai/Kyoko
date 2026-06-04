import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALID_PROPOSAL = ROOT / "docs/fixtures/learning-proposals/valid-context-proposal.json"


def second_profile_payload() -> dict:
    return {
        "profile": {
            "id": "profile_second",
            "name": "Second Profile",
            "root_path": ".",
            "status": "active",
            "created_at": "2026-05-31T13:00:00Z",
            "updated_at": "2026-05-31T13:00:00Z",
        },
        "sources": [
            {
                "id": "source_second",
                "profile_id": "profile_second",
                "kind": "test",
                "display_name": "Second source",
                "status": "active",
                "adapter_version": "test",
                "config_json": {},
                "capabilities_json": {},
                "last_seen_at": "2026-05-31T13:01:00Z",
            }
        ],
        "agent_identities": [
            {
                "id": "agent_second",
                "profile_id": "profile_second",
                "source_id": "source_second",
                "external_id": "agent-second",
                "name": "agent-second",
                "kind": "agent",
                "role": "writer",
                "model": "test-model",
                "workspace_path": ".",
                "metadata_json": {},
            }
        ],
        "workflow_nodes": [
            {
                "id": "node_second",
                "profile_id": "profile_second",
                "source_id": "source_second",
                "external_id": "node-second",
                "agent_identity_id": "agent_second",
                "kind": "agent",
                "name": "second-node",
                "metadata_json": {},
            }
        ],
        "runs": [
            {
                "id": "run_second",
                "profile_id": "profile_second",
                "source_id": "source_second",
                "external_id": "run-second",
                "root_span_id": "span_second",
                "agent_identity_id": "agent_second",
                "task_attempt_id": None,
                "status": "failed",
                "started_at": "2026-05-31T13:00:00Z",
                "ended_at": "2026-05-31T13:01:00Z",
                "input_ref": "blob_second_input",
                "output_ref": "blob_second_output",
                "summary": "Second profile failed run",
                "metadata_json": {},
            }
        ],
        "spans": [
            {
                "id": "span_second",
                "run_id": "run_second",
                "source_id": "source_second",
                "external_id": "span-second",
                "parent_span_id": None,
                "workflow_node_id": "node_second",
                "agent_identity_id": "agent_second",
                "kind": "agent",
                "name": "second task",
                "status": "failed",
                "started_at": "2026-05-31T13:00:00Z",
                "ended_at": "2026-05-31T13:01:00Z",
                "input_ref": "blob_second_span_input",
                "output_ref": "blob_second_span_output",
                "usage_json": {},
                "attributes_json": {},
                "raw_ref": "blob_second_raw",
            }
        ],
        "timeline_events": [
            {
                "id": "event_second",
                "profile_id": "profile_second",
                "source_id": "source_second",
                "entity_type": "span",
                "entity_id": "span_second",
                "kind": "span_failed",
                "at": "2026-05-31T13:01:00Z",
                "agent_identity_id": "agent_second",
                "payload_ref": "blob_second_event",
                "metadata_json": {},
            }
        ],
    }


def second_profile_proposal() -> dict:
    proposal = json.loads(VALID_PROPOSAL.read_text())
    proposal["id"] = "proposal_second_context"
    proposal["profile_id"] = "profile_second"
    proposal["producer"]["name"] = "second-test"
    proposal["producer"]["session_id"] = "proposal_second_context"
    proposal["title"] = "Add billing context"
    proposal["summary"] = "Second profile needs billing-specific guidance."
    proposal["evidence_refs"] = [
        {
            "entity_type": "span",
            "entity_id": "span_second",
            "role": "failure",
            "note": "Second profile failure.",
        }
    ]
    proposal["problem"] = {
        "issue": "Billing tasks lack profile-specific context.",
        "severity": "medium",
        "root_cause": "The profile has no billing guidance.",
        "target": {
            "entity_type": "agent_identity",
            "entity_id": "agent_second",
        },
    }
    proposal["insight"] = "Use billing-specific context for second profile work."
    proposal["proposed_changes"] = [
        {
            "type": "skillbook_update",
            "operation": "create",
            "section": "context",
            "issue": "Billing tasks lack profile-specific context.",
            "insight": "Use billing-specific context for second profile work.",
            "keywords": ["billing", "second-profile"],
            "occurrence_refs": [
                {
                    "entity_type": "span",
                    "entity_id": "span_second",
                    "role": "failure",
                }
            ],
        }
    ]
    return proposal
