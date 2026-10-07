# Contributing

Thanks for looking. Reports from mirrors other than the tested Alasta 2M09 are the most useful
thing anyone can send: the integration talks to a protocol reverse-engineered from the WiseMirror
app, and other brands and models may behave differently.

## Reporting a mirror, or a problem

The [community thread](https://community.home-assistant.io/t/wisemirror-local-control-of-smart-bathroom-mirrors-alasta-byecold-gs-mirror/1027643)
is the easiest place for questions, and for "it works on my mirror" or "it behaves oddly". Bugs
are better as an [issue](https://github.com/jorgediez/ha-wisemirror/issues/new/choose), where there
is a form for telling us whether the integration works with your mirror, one for bugs, and one for
ideas.

What makes a report actionable:

- The integration's diagnostics (*Settings → Devices & services → WiseMirror → ⋮ → Download
  diagnostics*). The IP and MAC addresses and the location are redacted. It includes the model and
  firmware, which is what tells mirrors apart.
- A debug log covering the moment it went wrong, with `custom_components.wisemirror: debug` in your
  `logger` settings. See [Troubleshooting](README.md#troubleshooting).
- For a mirror that isn't discovered or behaves oddly, the output of
  [`scripts/wisemirror.py`](scripts/wisemirror.py), which talks to a mirror directly, without Home
  Assistant: `python scripts/wisemirror.py discover`.

## What belongs here

This integration controls the weather-station display of mirrors managed with the WiseMirror app,
locally, over UDP.

Changes that fit:

- More of what the mirror reports or accepts over its protocol. Record what you learn in
  [docs/PROTOCOL.md](docs/PROTOCOL.md).
- Making an existing feature work on another brand or model.
- Fixing how the integration reacts to what a mirror sends.
- Documentation and translations.

Changes that belong elsewhere:

- The mirror's first Wi-Fi setup: that is done once with the WiseMirror app.
- Anything that needs a cloud account.

**If a change is more than a small fix, open an issue first.** A short description of what you
want and how you'd do it takes minutes and can save you days.

## Working on the code

```bash
pip install -r requirements_test.txt
ruff check . && ruff format --check .
pytest --cov
```

The Home Assistant test harness only runs on Linux and macOS. With Docker you can run the suite on
any OS, Windows included, against both the oldest supported and the latest Home Assistant, the
same matrix as CI:

```bash
scripts/test-docker.sh                 # both versions
scripts/test-docker.sh min -k options  # one version ("min" or "latest"), extra pytest args
scripts/test-docker.sh --cov           # with a coverage report
REBUILD=1 scripts/test-docker.sh       # rebuild the images anyway; a new pin rebuilds by itself
```

A pull request is expected to:

- Pass `ruff check`, `ruff format --check` and the test suite on both Home Assistant versions. CI
  runs these, plus HACS and `hassfest`, and needs a maintainer to approve the first run on a fork.
- Come with tests. Integration tests run inside Home Assistant against a mocked mirror (the
  `mock_device` fixture in `tests/conftest.py`); protocol tests feed in what a mirror really sends.
- Translate any text a user sees into **English and Spanish**. A test fails if the two files differ
  in strings or placeholders.
- Update the docs it affects: the README for what users see, docs/PROTOCOL.md for what was learned
  about the protocol.
- Explain, in the commit message, why the change is the way it is — particularly anything that
  works around how a mirror behaves.

Keep a pull request to one subject. Two unrelated improvements are two pull requests, and they'll
both move faster.

## Style

Follow [Home Assistant's own conventions](https://developers.home-assistant.io/docs/development_guidelines)
and the code already here: entity names and errors translated, no blocking calls in the event loop
(the protocol client is blocking, so it runs in the executor), comments that say why rather than
what. Ruff, at line length 88, settles formatting.

## Releasing

1. Bump `version` in `custom_components/wisemirror/manifest.json` and in `pyproject.toml`. A test
   checks they match.
2. Publish a GitHub release tagged `vX.Y.Z`, with notes for users. HACS installs from that tag.
3. The **Release** workflow checks the tag matches both files, then runs the tests and the HACS and
   hassfest validation against the tagged code.

## License

Contributions are under the [MIT License](LICENSE), like the rest of the project.
