# Quality Scan Script Opportunities — Reference Guide

**Reference: `references/script-standards.md` for script creation guidelines.**

This document identifies deterministic operations that should be offloaded from the LLM into scripts for quality validation of BMad agents.

---

## Core Principle

Scripts validate structure and syntax (deterministic). Prompts evaluate semantics and meaning (judgment). Create scripts for checks that have clear pass/fail criteria.

---

## How to Spot Script Opportunities

During build, walk through every capability/operation and apply these tests:

### The Determinism Test
For each operation the agent performs, ask:
- Given identical input, will this ALWAYS produce identical output? → Script
- Does this require interpreting meaning, tone, context, or ambiguity? → Prompt
- Could you write a unit test with expected output for every input? → Script

### The Judgment Boundary
Scripts handle: fetch, transform, validate, count, parse, compare, extract, format, check structure
Prompts handle: interpret, classify with ambiguity, create, decide with incomplete info, evaluate quality, synthesize meaning

### Pattern Recognition Checklist
Table of signal verbs/patterns mapping to script types:
| Signal Verb/Pattern | Script Type |
|---------------------|-------------|
| "validate", "check", "verify" | Validation script |
| "count", "tally", "aggregate", "sum" | Metric/counting script |
| "extract", "parse", "pull from" | Data extraction script |
| "convert", "transform", "format" | Transformation script |
| "compare", "diff", "match against" | Comparison script |
| "scan for", "find all", "list all" | Pattern scanning script |
| "check structure", "verify exists" | File structure checker |
| "against schema", "conforms to" | Schema validation script |
| "graph", "map dependencies" | Dependency analysis script |

### The Outside-the-Box Test
Beyond obvious validation, consider:
- Could any data gathering step be a script that returns structured JSON for the LLM to interpret?
- Could pre-processing reduce what the LLM needs to read?
- Could post-processing validate what the LLM produced?
- Could metric collection feed into LLM decision-making without the LLM doing the counting?

### Your Toolbox
Scripts have access to full capabilities — think broadly:
- **Bash**: Full shell — `jq`, `grep`, `awk`, `sed`, `find`, `diff`, `wc`, `sort`, `uniq`, `curl`, plus piping and composition
- **Python**: Standard library (`json`, `yaml`, `pathlib`, `re`, `argparse`, `collections`, `difflib`, `ast`, `csv`, `xml`, etc.) plus PEP 723 inline-declared dependencies (`tiktoken`, `jsonschema`, `pyyaml`, etc.)
- **System tools**: `git` commands for history/diff/blame, filesystem operations, process execution

If you can express the logic as deterministic code, it's a script candidate.

### The --help Pattern
All scripts use PEP 723 and `--help`. When a skill's prompt needs to invoke a script, it can say "Run `scripts/foo.py --help` to understand inputs/outputs, then invoke appropriately" instead of inlining the script's interface. This saves tokens in prompts and keeps a single source of truth for the script's API.

---

## Priority 1: High-Value Validation Scripts

### 1. Frontmatter Validator

**What:** Validate SKILL.md frontmatter structure and content

**Why:** Frontmatter is the #1 factor in skill triggering. Catch errors early.

**Checks:**
```python
# checks:
- name exists and is kebab-case
- description exists and follows pattern "Use when..."
- No forbidden fields (XML, reserved prefixes)
- Optional fields have valid values if present
```

**Output:** JSON with pass/fail per field, line numbers for errors

**Implementation:** Python with argparse, no external deps needed

---

### 2. Template Artifact Scanner

**What:** Scan for orphaned template substitution artifacts

**Why:** Build process may leave `{if-autonomous}`, `{displayName}`, etc.

**Output:** JSON with file path, line number, artifact type

**Implementation:** Bash script with JSON output via jq

---

### 3. Access Boundaries Extractor

**What:** Extract and validate access boundaries from memory-system.md

**Why:** Security critical — must be defined before file operations

**Checks:**
```python
# Parse memory-system.md for:
- ## Read Access section exists
- ## Write Access section exists
- ## Deny Zones section exists (can be empty)
- Paths use placeholders correctly ({project-root} for _bmad paths, relative for skill-internal)
```

**Output:** Structured JSON of read/write/deny zones

**Implementation:** Python with markdown parsing

---

---

## Priority 2: Analysis Scripts

### 4. Token Counter

**What:** Count tokens in each file of an agent

**Why:** Identify verbose files that need optimization

**Checks:**
```python
# For each .md file:
- Total tokens (approximate: chars / 4)
- Code block tokens
- Token density (tokens / meaningful content)
```

**Output:** JSON with file path, token count, density score

**Implementation:** Python with tiktoken for accurate counting, or char approximation

---

### 5. Dependency Graph Generator

**What:** Map skill → external skill dependencies

**Why:** Understand agent's dependency surface

**Checks:**
```python
# Parse SKILL.md for skill invocation patterns
# Parse prompt files for external skill references
# Build dependency graph
```

**Output:** DOT format (GraphViz) or JSON adjacency list

**Implementation:** Python, JSON parsing only

---

### 6. Activation Flow Analyzer

**What:** Parse SKILL.md On Activation section for sequence

**Why:** Validate activation order matches best practices

**Checks:**

Validate that the activation sequence is logically ordered (e.g., config loads before config is used, memory loads before memory is referenced).

**Output:** JSON with detected steps, missing steps, out-of-order warnings

**Implementation:** Python with regex pattern matching

---

### 7. Memory Structure Validator

**What:** Validate memory-system.md structure

**Why:** Memory files have specific requirements

**Checks:**
```python
# Required sections:
- ## Core Principle
- ## File Structure
- ## Write Discipline
- ## Memory Maintenance
```

**Output:** JSON with missing sections, validation errors

**Implementation:** Python with markdown parsing

---

### 8. Subagent Pattern Detector

**What:** Detect if agent uses BMAD Advanced Context Pattern

**Why:** Agents processing 5+ sources MUST use subagents

**Checks:**
```python
# Pattern detection in SKILL.md:
- "DO NOT read sources yourself"
- "delegate to sub-agents"
- "/tmp/analysis-" temp file pattern
- Sub-agent output template (50-100 token summary)
```

**Output:** JSON with pattern found/missing, recommendations

**Implementation:** Python with keyword search and context extraction

---

## Priority 3: Composite Scripts

### 9. Agent Health Check

**What:** Run all validation scripts and aggregate results

**Why:** One-stop shop for agent quality assessment

**Composition:** Runs Priority 1 scripts, aggregates JSON outputs

**Output:** Structured health report with severity levels

**Implementation:** Bash script orchestrating Python scripts, jq for aggregation

---

### 10. Comparison Validator

**What:** Compare two versions of an agent for differences

**Why:** Validate changes during iteration

**Checks:**
```bash
# Git diff with structure awareness:
- Frontmatter changes
- Capability additions/removals
- New prompt files
- Token count changes
```

**Output:** JSON with categorized changes

**Implementation:** Bash with git, jq, python for analysis

---

## Script Output Standard

All scripts MUST output structured JSON for agent consumption:

```json
{
  "script": "script-name",
  "version": "1.0.0",
  "agent_path": "/path/to/agent",
  "timestamp": "2025-03-08T10:30:00Z",
  "status": "pass|fail|warning",
  "findings": [
    {
      "severity": "critical|high|medium|low|info",
      "category": "structure|security|performance|consistency",
      "location": {"file": "SKILL.md", "line": 42},
      "issue": "Clear description",
      "fix": "Specific action to resolve"
    }
  ],
  "summary": {
    "total": 10,
    "critical": 1,
    "high": 2,
    "medium": 3,
    "low": 4
  }
}
```

---

## Implementation Checklist

When creating validation scripts:

- [ ] Uses `--help` for documentation
- [ ] Accepts `--agent-path` for target agent
- [ ] Outputs JSON to stdout
- [ ] Writes diagnostics to stderr
- [ ] Returns meaningful exit codes (0=pass, 1=fail, 2=error)
- [ ] Includes `--verbose` flag for debugging
- [ ] Has tests in `scripts/tests/` subfolder
- [ ] Self-contained (PEP 723 for Python)
- [ ] No interactive prompts

---

## Integration with Quality Analysis

The Quality Analysis skill should:

1. **First**: Run available scripts for fast, deterministic checks
2. **Then**: Use sub-agents for semantic analysis (requires judgment)
3. **Finally**: Synthesize both sources into report

**Example flow:**
```bash
# Run all validation scripts
python scripts/validate-frontmatter.py --agent-path {path}
bash scripts/scan-template-artifacts.sh --agent-path {path}

# Collect JSON outputs
# Spawn sub-agents only for semantic checks
# Synthesize complete report
```

---

## Script Creation Priorities

**Phase 1 (Immediate value):**
1. Template Artifact Scanner (Bash + jq)
2. Access Boundaries Extractor (Python)

**Phase 2 (Enhanced validation):**
4. Token Counter (Python)
5. Subagent Pattern Detector (Python)
6. Activation Flow Analyzer (Python)

**Phase 3 (Advanced features):**
7. Dependency Graph Generator (Python)
8. Memory Structure Validator (Python)
9. Agent Health Check orchestrator (Bash)

**Phase 4 (Comparison tools):**
10. Comparison Validator (Bash + Python)
