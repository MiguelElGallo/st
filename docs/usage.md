# Using tgrep

This Agent Plugin makes [Microsoft tgrep](https://github.com/microsoft/tgrep)
available to agents through three tools:

- `tgrep_index` builds or refreshes a repository's `.tgrep` index.
- `tgrep_search` searches code with a bounded, agent-friendly subset of the
  tgrep and ripgrep flags.
- `tgrep_status` checks whether a tgrep server is running for a repository.

## Recommended workflow

1. Ask the agent to build a tgrep index for the repository.
2. Ask it to search for a symbol or literal string. It can narrow broad
   searches with a file type or glob.
3. Rebuild the index after edits that must appear in a later indexed search, or
   ask for a fresh filesystem search.

For example:

> Build a tgrep index for this repository, then find where `main` is defined.

Every tool call uses an explicit workspace root. Requested paths are
canonicalized and must remain inside that root.

tgrep also supports a long-running `serve` mode. This plugin intentionally does
not create unmanaged background processes; use the standalone tgrep CLI when a
watched, continuously refreshed index is required.

[Back to installation](../README.md)
