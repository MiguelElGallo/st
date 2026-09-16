---
name: tgrep-search
description: Search and index large local repositories with Microsoft tgrep. Use for symbol, text, regex, filename, and reference searches when fast repeated repository exploration is useful.
---

# Search repositories with tgrep

Use the `tgrep_search`, `tgrep_index`, and `tgrep_status` tools when available.
The plugin manages a pinned, checksum-verified tgrep binary. The first tool call
may download it from the official Microsoft GitHub release.

## Workflow

1. Resolve the active repository root to an absolute path and pass it as
   `workspace_root` on every tool call. Tool paths must remain inside it. Never
   select an unrelated directory merely to bypass the containment check.
2. For repeated searches in a medium or large repository, call `tgrep_index`
   once. Do not commit the generated `.tgrep/` directory.
3. Call `tgrep_search` with the smallest useful scope:
   - Prefer `fixed_strings: true` for exact symbols or user-provided text.
   - Use `file_type` or `glob` before limiting matches.
   - Use `files_with_matches: true` to find candidate files, then search those
     paths with context.
   - Use `context` only when surrounding lines help answer the question.
4. Treat exit code `1` as “no match,” not a tool failure. Exit code `2` is an
   actual error, such as an invalid regex or unreadable path.
5. Rebuild the index after edits that must appear in later indexed searches, or
   pass `fresh: true` for a slower direct filesystem scan.
6. Open the relevant files before making code claims. Search output identifies
   candidates; it is not a substitute for reading the implementation.

## Choosing index freshness

- Indexed searches are fastest, but an on-disk index reflects the last
  successful `tgrep_index` call.
- `fresh: true` bypasses the index and reads current files. Use it for checks
  immediately after edits or when correctness depends on the latest bytes.
- `tgrep_status` reports a separately started tgrep server. This plugin does not
  start background servers automatically.

## Failure handling

- If the managed download fails, report the exact error. Do not bypass digest
  verification. The user can provide a trusted executable through `TGREP_BIN`.
- If Python or the MCP server is unavailable, use an installed `tgrep` CLI with
  equivalent flags. If tgrep is unavailable too, fall back to `rg` and state
  that the indexed path was not used.
- Never forward arbitrary shell fragments. The MCP tools use an allowlisted
  argument set and execute tgrep without a shell.

Example literal search:

```json
{
  "pattern": "parse_config",
  "workspace_root": "/absolute/path/to/repository",
  "path": ".",
  "fixed_strings": true,
  "file_type": ["rust"],
  "context": 2
}
```
