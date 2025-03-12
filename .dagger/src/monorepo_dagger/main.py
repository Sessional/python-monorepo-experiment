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
        ".envrc",
    ]
)

SHIPPING_IGNORES = Ignore(
    IGNORE.patterns + [
        "**/tests"
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

        container = await self.copy_source_code(container, root_dir, IGNORE, project_sources_map)

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

        project_sources_map = {}

        for package in uv_lock_dict["package"]:
            if package["name"] in local_projects:
                project_sources_map[package["name"]] = package["source"]["editable"]

        return project_sources_map

    async def copy_source_code(
        self,
        container: Container,
        root_dir: RootDir,
        ignores: Ignore,
        project_sources_map: dict[str, str],
        target_dir: str = "src",
    ) -> Container:
        for project, project_source_path in project_sources_map.items():
            container = container.with_directory(
                f"/{target_dir}/{project_source_path}",
                root_dir.directory(project_source_path),
                exclude=ignores.patterns
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
    async def verify(self, root_dir: RootDir, project: str) -> str:
        container = await self.build_project(root_dir, project)

        pytest_output = await container.with_exec(["pytest"]).stdout()
        pyright_output = await container.with_exec(["pyright"]).stdout()
        ruff_output = await container.with_exec(["ruff", "check"]).stdout()

        return f"""
Pytest:
{pytest_output}

Pyright:
{pyright_output}

Ruff:
{ruff_output}
"""

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

    def build_container_destination(
            self,
            registry: str,
            namespace: str | None,
            repository: str,
            tag: str,
    ):
        return f"{'/'.join(item for item in [registry, namespace, repository] if item is not None)}:{tag}".lower()

    def attach_registry_auth(
            self,
            container: Container,
            registry: str,
            username: str | None,
            password: dagger.Secret | None
    ) -> Container:
        if registry == "ghcr.io":
            return container.with_registry_auth(
                    address=registry,
                    username=username,
                    secret=password,
            )
        return container

    @function
    async def fastapi_slim_build(
        self,
        root_dir: RootDir,
        project: str,
        port: str | None = "8080",
        host: str | None = "0.0.0.0",
        path_to_code: str | None = "code"
        ) -> Container:
        uv_container = (
            dag.container()
            .from_("ghcr.io/astral-sh/uv:latest")
        )
        uv_lock = root_dir.file("uv.lock")

        code_directory = (dag.directory()
            .with_file("uv.lock", uv_lock)
            .with_file("pyproject.toml", root_dir.file("pyproject.toml"))
        )

        sources = await self.get_project_sources_map(uv_lock=uv_lock, project=project)
        
        uv = "/uv"

        builder = (
            dag.container()
            # set to 3.11 because that is what distroless supports
            .from_("python:3.11-slim")
            .with_file("uv", uv_container.file(uv))
            .with_env_variable("UV_PROJECT_ENVIRONMENT", "/usr/local/")
            .with_env_variable("UV_PYTHON", "/usr/local/bin/python")
            .with_env_variable("UV_COMPILE_BYTECODE", "1")
            .with_env_variable("UV_LINK_MODE", "copy")
            .with_env_variable("UV_FROZEN", "1")
            .with_mounted_cache("/root/.cache/uv", dag.cache_volume("python-311"))
            .with_directory(f"{path_to_code}", code_directory)
            .with_workdir(f"{path_to_code}")
            .with_exec([uv, "sync", "--no-install-workspace", "--package", project])
        )
        
        builder = await self.copy_source_code(container=builder, root_dir=root_dir, project_sources_map=sources, target_dir=path_to_code, ignores=SHIPPING_IGNORES)
        builder = builder.with_exec([uv, "sync", "--inexact", "--no-editable", "--package", project])

        builder = (
            builder
            .with_workdir(f"/{path_to_code}/projects/{project}")
            .with_entrypoint(["python", "-m", "fastapi", "run", f"src/{project}", "--port", port, "--host", host])
            .with_exposed_port(int(port))
        )

        return builder

    @function
    async def fastapi_slim_publish(
        self,
        root_dir: RootDir,
        project: str,
        registry: str,
        git_repository: str,
        username: str | None,
        password: dagger.Secret | None,
        tag: str,
        port: str | None = "8080",
        host: str | None = "0.0.0.0",
        ) -> str:
        container = await self.fastapi_slim_build(root_dir=root_dir, project=project, port=port, host=host)

        #return await container.publish(f"ttl.sh/python-monorepo-slim:20m")

        container = self.attach_registry_auth(container=container, registry=registry, username=username, password=password)

        namespace, repository = git_repository.split("/")
        repository = self.build_container_destination(registry=registry, namespace=namespace, repository=repository, tag=tag)

        return await container.publish(repository)
    
    @function
    async def fastapi_slim_run(
        self,
        root_dir: RootDir,
        project: str,
        port: str | None = "8080",
        host: str | None = "0.0.0.0",
        ) -> dagger.Service:
        container = await self.fastapi_slim_build(root_dir=root_dir, project=project, port=port, host=host)

        return container.as_service()

    @function
    async def fastapi_distroless_build(
        self,
        root_dir: RootDir,
        project: str,
        port: str | None = "8080",
        host: str | None = "0.0.0.0",
        ) -> Container:
        path_to_code = "code"
        path_to_site_packages = "/usr/local/lib/python3.11/site-packages"

        builder = await self.fastapi_slim_build(root_dir=root_dir, project=project, path_to_code=path_to_code, port=port, host=host)

        new_code_directory = builder.directory(f"/{path_to_code}")
        new_site_packages = builder.directory(path_to_site_packages)

        runtime_container = (
            dag.container()
            .from_("gcr.io/distroless/python3-debian12")
            .with_directory(f"/{path_to_code}", new_code_directory)
            .with_directory(path_to_site_packages, new_site_packages)
        )

        runtime_container = (
            runtime_container
            .with_env_variable("PYTHONPATH", path_to_site_packages)
            .with_workdir(f"/{path_to_code}/projects/{project}")
            .with_entrypoint(["python", "-m", "fastapi", "run", f"src/{project}", "--port", port, "--host", host])
            .with_exposed_port(int(port))
        )

        return runtime_container
    
    @function
    async def fastapi_distroless_run(
        self,
        root_dir: RootDir,
        project: str,
        port: str | None = "8080",
        host: str | None = "0.0.0.0",
        ) -> dagger.Service:
        container = await self.fastapi_distroless_build(root_dir=root_dir, project=project, port=port, host=host)

        return container.as_service()
    
    @function
    async def fastapi_distroless_publish(
        self,
        root_dir: RootDir,
        project: str,
        registry: str,
        image: str | None,
        git_repository: str | None,
        username: str | None,
        password: dagger.Secret | None,
        tag: str,
        port: str | None = "8080",
        host: str | None = "0.0.0.0",
        ) -> str:
        """
        :param git_repository: typically ${{ github.repository }}, or `sessional/python-monorepo-experiment`
        :param image: used when passing to somewhere that does not have a namespace tier (ttl.sh)
        :param username: for authenticating to a registry (GHCR)
        :param password: for authenticating to a registry (GHCR)
        """
        container = await self.fastapi_distroless_build(root_dir=root_dir, project=project, port=port, host=host)

        if username is not None and password is not None:
            container = self.attach_registry_auth(container=container, registry=registry, username=username, password=password)

        if git_repository is not None:
            namespace, repository = git_repository.split("/")
        else:
            namespace = None
            repository = image
        repository = self.build_container_destination(registry=registry, namespace=namespace, repository=repository, tag=tag)

        return await container.publish(repository)
