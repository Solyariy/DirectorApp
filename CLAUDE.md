# CLAUDE.md

This file provides guidance to agents when working with code in this repository.
Read `@AGENTS.md`.

## Scope discipline
- Implement only the fields and enums I ask for. Propose extra fields (e.g. content_type) as suggestions, and don't add them to code.
- Prefer the simplest design. Avoid caching or singletons unless I ask for them.
- When an instruction is ambiguous (e.g. 'items do leave X'), ask with AskUserQuestion instead of guessing.
