# Python Monorepo Experiment
---

> [!NOTE]
> Inspired (read: hijacked) from https://gafni.dev/blog/cracking-the-python-monorepo/


This experiment is an exercise in exploring an option for managing a python monorepo. Nothing this repo accomplishes is extraordinary in comparison to what can be accomplished with other routes using a tool like Bazel. However, Bazel is a pretty heavy lift that can be hard to win over other engineers with. The primary advantage of this experiment is to look at the quantity of effort it takes to monorepo with these tools in hopes that less push-back is given. Pants may be a valid alternative but the apparent lack of first class support for debugging and import suggestions and autocomplete in visual studio code makes it less appealing.

### The general goals of this repo:
- Small and low overhead solution or toolchain. Ideally workable for a small (single digit) sized team with only a subset actively touching any apps.
- Small shippables. Serverless is the intended target, the environment it is to enter spends near 50% of its time idle.
- Reduce duplication and copy/paste drift. Without a monorepo, the overhead of shipping individual packages and dealing with packaging is more than the small team is ready to take on. As a side effect, duplicated code and drift on them.
- Avoid steep learning curve tools. Not everyone is at the same level of exposure to some of the tooling options, and still need to be able to pick them up.
- Facilitate a conglomerate of small shippable artifacts to keep build and iteration times low, reduce blast radius of changes and hide domain complexity. (The domain is harder than the engineering complexity of more things...)
- Rapidly cloneable github workflows. Onboarding a new shippable artifact raises eyebrows if it takes a significant portion of time, so the intent is to make it short enough that it isn't noticed.
- Type-ahead and import suggestions and ability to attach a debugger are non-negotiable. Any set up that loses those three aspects is immediately not worth it.
- Few to none of the unexpected gotchyas (the pip workflow with editable or non-updating dependencies comes to mind)

### Getting set up:

#### Necessary to install:
- [uv](https://docs.astral.sh/uv/): for managing the dependencies. Using `uv` enables support for local editable installs.
- [docker (or docker compatible tool)](https://www.docker.com/): the runtime for containers that are used to execute CI tasks for this project and the containers it will ship.
- [dagger](https://docs.dagger.io/): a tool to manage and build containers in utilizing python

#### Optional to install:
- [act](https://nektosact.com/usage/index.html): some level of validation before pushing a workflow file

### Adding more things:
- Adding a new library:
    ```sh
    uv init --package --lib libs/lib3
    ```

- Adding a new service:
    ```sh
    uv init --package projects/app
    ```

- Adding a new dependency:
    ```sh
    uv add --package app lib1
    ```

### Executing things:

- Running a FastAPI container locally, see `.dagger/src/monorepo_dagger/main.py`
    ```sh
    dagger -v call fastapi-distroless-run --project app up
    ```

- Running tests:
    ```sh
    dagger call pytest --project app
    ```

- Publishing FastAPI container, see `.dagger/src/monorepo_daggger/main.py`
    ```sh
    dagger -v call fastapi-distroless-publish --project app --registry ttl.sh --image python-monorepo --tag 20m
    ```

- Testing workflow for github:

    ```sh
    act pull_request --container-architecture linux/amd64
    ```

### Getting configured for work

- Debugging a project from inside vscode (launch.json):
    ```json
    {
        "version": "0.2.0",
        "configurations": [
            {
                "name": "Debug Project",
                "type": "debugpy",
                "request": "launch",
                "module": "uvicorn",
                "args": [
                    "src.${input:project-name}:app",
                    "--reload"
                ],
                "jinja": true,
                "cwd": "${workspaceFolder}/projects/${input:project-name}"
            }
        ],
        "inputs": [
            {
                "id": "project-name",
                "type": "pickString",
                "options": [
                    "app"
                ],
                "description": "The project inside the `projects` folder to attach the debugger.",
                "default": "app"
            }
        ]
    }

    ```

- Getting auto complete and auto imports in vscode (settings.json):
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

- Wiring up unit testing for attaching debuggers (settings.json):
    ```json
    {
        "python.testing.unittestEnabled": false,
        "python.testing.pytestEnabled": true,
        "python.testing.pytestArgs": [
            // need a new entry for each package that is going to have tests
            "projects/app"
        ]
    }
    ```
