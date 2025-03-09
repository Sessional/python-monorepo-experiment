from typing import (
    Annotated,
    TypeAlias,
)

import dagger
import tomli
from dagger import (
    BuildArg,
    Container,
    DefaultPath,
    File,
    Ignore,
    dag,
    function,
    object_type,
)

IGNORE = Ignore(
    [
        ".env",
        ".git",
        "**/.venv",
        "**__pycache__**",
        ".dagger/sdk",
        "**/.pytest_cache",
        "**/.ruff_cache",
    ]
)

# this represents the repo root
RootDir: TypeAlias = Annotated[
    dagger.Directory,
    DefaultPath("."),
    IGNORE,
]

# this represents the source directory of a specific project in the monorepo
SourceDir: TypeAlias = Annotated[
    dagger.Directory,
    IGNORE,
]


@object_type
class MonorepoDagger:
    @function
    async def build_project(
        self,
        root_dir: RootDir,
        project: str,
        debug_sleep: float = 0.0,
    ) -> Container:
        """Build a container containing only the source code for a given project and it's dependencies."""
        # we start by creating a container including only third-party dependencies
        # with no source code (except pyproject.toml and uv.lock from the repo root)
        container = self.container_with_third_party_dependencies(
            pyproject_toml=root_dir.file("pyproject.toml"),
            uv_lock=root_dir.file("uv.lock"),
            dockerfile=root_dir.file("Dockerfile"),  # this could be a parameter
            project=project,
        )

        # find the source code locations for the dependencies of a given project
        project_sources_map = await self.get_project_sources_map(
            root_dir.file("uv.lock"), project
        )

        container = self.copy_source_code(container, root_dir, project_sources_map)

        container = container.with_exec(["sleep", str(debug_sleep)])

        # we run `uv sync` to create editable installs of the local dependencies
        # pointing (for now) to the dummy directories we created in the previous step
        container = self.install_local_dependencies(container, project)

        # change the working directory to the project's source directory
        # so that commands in CI are automatically run in the context of this project
        container = container.with_workdir(f"/src/{project_sources_map[project]}")

        return container

    def container_with_third_party_dependencies(
        self,
        pyproject_toml: File,
        uv_lock: File,
        dockerfile: File,
        project: str,
    ) -> Container:
        # create an empty directory to make sure only the pyproject.toml
        # and uv.lock files are copied to the build context (to affect caching)
        build_context = (
            dag.directory()
            .with_file(
                "pyproject.toml",
                pyproject_toml,
            )
            .with_file(
                "uv.lock",
                uv_lock,
            )
            .with_file(
                "/Dockerfile",
                dockerfile,
            )
            .with_new_file("README.md", "Dummy README.md")
        )

        return build_context.docker_build(
            target="deps-dev",
            dockerfile="/Dockerfile",
            build_args=[BuildArg(name="PACKAGE", value=project)],
        )

    async def get_project_sources_map(
        self,
        uv_lock: File,
        project: str,
    ) -> dict[str, str]:
        """Returns a dictionary of the local dependencies' (of a given project) source directories."""
        uv_lock_dict = tomli.loads(await uv_lock.contents())

        members = set(uv_lock_dict["manifest"]["members"])

        local_projects = {project}

        def find_deps_for_package(package_name: str):
            for package in uv_lock_dict["package"]:
                if package["name"] == package_name:
                    dependencies = package.get("dependencies", [])
                    for dep in dependencies:
                        if isinstance(dep, dict) and dep.get("name") in members:
                            local_projects.add(dep["name"])
                            find_deps_for_package(dep["name"])

        find_deps_for_package(project)
        # now, gather all the directories with the dependency sources

        project_sources_map = {}

        for package in uv_lock_dict["package"]:
            if package["name"] in local_projects:
                project_sources_map[package["name"]] = package["source"]["editable"]

        return project_sources_map

    def copy_source_code(
        self,
        container: Container,
        root_dir: RootDir,
        project_sources_map: dict[str, str],
    ) -> Container:
        for project, project_source_path in project_sources_map.items():
            container = container.with_directory(
                f"/src/{project_source_path}",
                root_dir.directory(project_source_path),
            )

        return container

    def install_local_dependencies(
        self, container: Container, project: str
    ) -> Container:
        # the following uv command installs the project
        # and its dependencies in editable mode
        container = container.with_exec(
            [
                "uv",
                "sync",
                "--inexact",
                "--package",
                project,
            ]
        )

        return container

    @function
    async def uv_run(
        self,
        root_dir: RootDir,
        project: str,
    ) -> str:
        container: Container = await self.build_project(root_dir=root_dir, project=project, debug_sleep=0)
        container = container.with_exec(["uv", "run", project])
        return await (
            container
            .stdout()
        )
    
    @function
    async def fastapi_build(
        self,
        root_dir: RootDir,
        project: str,
        port: str | None,
        host: str | None,
    ) -> Container:
        """
        Build a fastapi container for a project running with the fastapi command line

        Usage: dagger call fastapi-build --root-dir . --project app up
        """
        port_to_use = "8080"
        if port is not None:
            port_to_use = port
        host_to_use = "0.0.0.0"
        if host is not None:
            host_to_use = host
        container: Container = await self.build_project(root_dir=root_dir, project=project, debug_sleep=0)
        # TODO: uvicorn with workers here might be ideal.
        return container.with_entrypoint(["fastapi", "run", f"src/{project}", "--port", port_to_use, "--host", host_to_use])

    @function
    async def fastapi_publish(
        self,
        root_dir: RootDir,
        project: str,
        dev: bool | None,
        port: str | None,
        host: str | None,
        tag: str | None,
    ) -> str:
        """
        Build a fastapi container and publish it to a registry
        Usage:
          dagger call fastapi-publish --root-dir . --project app --repository ghcr.io/sessional/app:latest [--tag $COMMIT_SHA]
        """

        is_dev = True if dev is True else False
        tag_to_use = tag if tag is not None else "latest"
        
        container: Container = await self.fastapi_build(root_dir=root_dir, project=project, port=port, host=host)
        if is_dev:
            repository = "ttl.sh/dagger-monorepo:20m"
        else:
            # TODO: get a real repository here
            repository = f"localhost:5000/dagger-monorepo:{tag_to_use}"
        return await container.publish(repository)

    @function
    async def fastapi_run(
        self,
        root_dir: RootDir,
        project: str,
        port: str | None,
        host: str | None,
    ) -> dagger.Service:
        """
        Build a fastapi container and run it locally
        Usage:
          dagger call fastapi-run --port 8081 --root-dir . --project app up
        """
        port_to_use = "8080"
        if port is not None:
            port_to_use = port

        container: Container = await self.fastapi_build(root_dir=root_dir, project=project, port=port_to_use, host=host)
        return (
            container
            .with_exposed_port(int(port_to_use))
            .as_service()
        )

    @function
    async def pytest(self, root_dir: RootDir, project: str) -> str:
        """Run pytest for a given project."""
        container = await self.build_project(root_dir, project)
        return await container.with_exec(["pytest"]).stdout()

    @function
    async def pyright(self, root_dir: RootDir, project: str) -> str:
        """Run pyright for a given project."""
        container = await self.build_project(root_dir, project)
        return await container.with_exec(["pyright"]).stdout()

    @function
    async def ruff(self, root_dir: RootDir, project: str) -> str:
        """Run ruff for a given project."""
        container = await self.build_project(root_dir, project)
        return await container.with_exec(["ruff", "check"]).stdout()
