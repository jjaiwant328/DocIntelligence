"""Infer an inputs_map for an ordered list of workflow steps, so the visual
assembler doesn't require the user to hand-wire step I/O.

For each step's declared inputs, resolve to (in priority order):
  1. the nearest PRIOR step whose outputs include a key of the same name  →
     $steps.<prior_id>.<key>
  2. a domain-config field (requirements)                                 →
     $domain.<key>
  3. a workflow input (domain, project, schema_vec, context, approve)     →
     $input.<key>
Unresolved inputs are left out (the engine/skill will surface a clear error),
except we always try to satisfy required inputs first.
"""
from __future__ import annotations

_DOMAIN_KEYS = {"requirements"}
# input name on a skill -> domain-config field it should draw from
_DOMAIN_ALIASES = {"candidate_requirements": "requirements"}
_INPUT_KEYS = {"domain", "project", "schema_vec", "context", "approve",
               "current", "previous"}


def infer_inputs_map(steps: list, registry) -> list:
    """Return steps with an `inputs_map` added to each (existing maps kept).

    `steps` is a list of {id, skill[, inputs_map]}. `registry` resolves contracts.
    """
    resolved: list = []
    prior_outputs: list = []  # [(step_id, set(output_keys))]

    for step in steps:
        sid, skill = step["id"], step["skill"]
        existing = step.get("inputs_map") or {}
        try:
            contract = registry.get(skill)
            input_names = list((contract.inputs or {}).keys())
            output_keys = set((contract.outputs or {}).keys())
        except Exception:
            input_names, output_keys = [], set()

        imap = dict(existing)
        for name in input_names:
            if name in imap:
                continue
            ref = _resolve(name, prior_outputs)
            if ref is not None:
                imap[name] = ref
            elif name in _DOMAIN_ALIASES:
                imap[name] = f"$domain.{_DOMAIN_ALIASES[name]}"
            elif name in _DOMAIN_KEYS:
                imap[name] = f"$domain.{name}"
            elif name in _INPUT_KEYS:
                imap[name] = f"$input.{name}"
            # else: leave unset

        resolved.append({"id": sid, "skill": skill, "inputs_map": imap})
        prior_outputs.append((sid, output_keys))
    return resolved


def _resolve(name: str, prior_outputs: list):
    # nearest prior step that outputs this key
    for sid, keys in reversed(prior_outputs):
        if name in keys:
            return f"$steps.{sid}.{name}"
    return None
