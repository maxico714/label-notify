# Third-party notices

`label-notify` is MIT-licensed (see [LICENSE](LICENSE)). It has one runtime dependency and several development
dependencies. No third-party source code is vendored into this repository.

## Runtime

| Package | License | Purpose |
|---|---|---|
| [PyYAML](https://pypi.org/project/PyYAML/) | MIT | YAML config parsing |

## Development and CI only

| Package | License | Purpose |
|---|---|---|
| [pytest](https://pypi.org/project/pytest/) | MIT | Test runner |
| [ruff](https://pypi.org/project/ruff/) | MIT | Linter and formatter |
| [mypy](https://pypi.org/project/mypy/) | MIT | Static type checker |
| [types-PyYAML](https://pypi.org/project/types-PyYAML/) | Apache-2.0 | Type stubs for PyYAML |

All licenses are compatible with the MIT license of this project. Versions are constrained in
`pyproject.toml`; no dependency source is included in the distribution.
