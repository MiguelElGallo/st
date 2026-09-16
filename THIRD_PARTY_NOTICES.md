# Third-party notices

## Microsoft tgrep

This project integrates with the `tgrep` command-line tool:

- Source: <https://github.com/microsoft/tgrep>
- Upstream version used by this plugin: 1.0.8
- Upstream copyright: Copyright (c) Microsoft Corporation
- Upstream license: MIT

The plugin downloads an official Microsoft tgrep release archive on first use,
verifies the archive against a pinned SHA-256 digest published by GitHub for
that release asset, extracts only the `tgrep` executable, and copies the
upstream MIT license beside the cached executable.

The complete upstream license text is retained at:

- `plugins/tgrep/third_party/tgrep-LICENSE.txt`

This repository does not claim authorship of tgrep and is not affiliated with
or endorsed by Microsoft.
