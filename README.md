Inspired (read: hijacked) from https://gafni.dev/blog/cracking-the-python-monorepo/

Necessary to install:
- [uv](https://docs.astral.sh/uv/): for managing the dependencies. Using `uv` enables support for local editable installs.
- [docker (or docker compatible tool)](https://www.docker.com/): the runtime for containers that are used to execute CI tasks for this project and the containers it will ship.
- [dagger](https://docs.dagger.io/): a tool to manage and build containers in utilizing python

Optional to install:
- [act](https://nektosact.com/usage/index.html): some level of validation before pushing a workflow file

Adding a new library:
```sh
uv init --package --lib libs/lib3
```

Adding a new service:
```sh
uv init --package projects/app
```

Adding a new dependency:
```sh
uv add --package app lib1
```

Running fastapi container locally, see `.dagger/src/monorepo_dagger/main.py`

```sh
dagger call fastapi-run --port 8081 --root-dir . --project app up
```

Publishing fastapi container, see `.dagger/src/monorepo_daggger/main.py`

```sh
dagger call fastapi-publish --root-dir . --project app --dev
```

Debugging a project from inside vscode (launch.json):
```json
{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "Debug: App", // TODO: smarter way of finding which project to run?
            "type": "debugpy",
            "request": "launch",
            "module": "uvicorn",
            "args": [
                "app:app",
                "--reload"
            ],
            "jinja": true,
            "cwd": "${workspaceFolder}/app"
        }
    ]
}
```

Getting auto complete and auto imports in vscode (settings.json):
```json
{
    "python.autoComplete.extraPaths": [
        "./libs/lib1/src",
        "./libs/lib2/src"
    ],
    "python.analysis.extraPaths": [
        "./libs/lib1/src",
        "./libs/lib2/src"
    ]
}
```

Running tests:
```sh
dagger call pytest --project app
```

Testing workflow for github:

```sh
act pull_request --container-architecture linux/amd64
```
