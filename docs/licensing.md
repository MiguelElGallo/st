# Licensing and Microsoft tgrep attribution

This Agent Plugin is distributed under the repository's
[MIT License](../LICENSE).

It integrates with **tgrep**, originally developed by Microsoft Corporation:

- Source: [github.com/microsoft/tgrep](https://github.com/microsoft/tgrep)
- Upstream license: [MIT](https://github.com/microsoft/tgrep/blob/main/LICENSE)
- Bundled license copy:
  [portable package](../plugins/tgrep/third_party/tgrep-LICENSE.txt)
- Additional attribution: [Third-party notices](../THIRD_PARTY_NOTICES.md)

The official tgrep binary is downloaded at runtime instead of being committed
to this repository. The plugin verifies its recorded SHA-256 digest and copies
Microsoft's license text beside the cached executable.

This project is community-maintained and is not affiliated with or endorsed by
Microsoft.

[Back to installation](../README.md)
