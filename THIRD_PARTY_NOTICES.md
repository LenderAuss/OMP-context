# Third-party software

This community installer is independent of OMP, Graphify, Astral, and model providers.
Upstream executables are downloaded separately; they are not included in this source archive.

| Component | Version | License/source |
|---|---|---|
| oh-my-pi | 18.14.0 | [MIT, upstream](https://github.com/can1357/oh-my-pi/blob/v18.14.0/LICENSE) |
| Graphify (`graphifyy`) | 0.9.25 | [Apache-2.0, PyPI metadata](https://pypi.org/project/graphifyy/0.9.25/); its distribution includes additional MIT notices |
| uv bootstrap | 0.13.6 | [MIT OR Apache-2.0, upstream](https://github.com/astral-sh/uv/tree/0.13.6) |
| Managed CPython | 3.12 | [Python license](https://docs.python.org/3/license.html) |

Graphify dependencies are pinned with hashes in requirements.lock. Their installed distributions retain their own licenses. The kit's MIT license does not replace any dependency's license.
