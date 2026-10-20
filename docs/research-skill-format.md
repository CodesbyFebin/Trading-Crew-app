# Research skill manifest format (`research_skills/<name>/SKILL.md`)

Idea adapted from the SKILL.md layout used by HKUDS/Vibe-Trading and spyderweb47/Vibe-Trade (idea only, no code).
Each research skill gets a folder with a `SKILL.md` whose YAML-style front matter must contain:
`name`, `callable`, `category: research`, `research_only: true`, `inputs`, `output`, `lookahead`, `data_status`,
`wired_into_execution: false`, `attribution`. `tests/test_research_extracts.py` checks every manifest: the callable
exists in `crew.skills.REGISTRY`, is flagged research-only, and its name does not appear in engine/risk/order code.
Manifests are documentation and metadata; nothing loads or executes code from them.
