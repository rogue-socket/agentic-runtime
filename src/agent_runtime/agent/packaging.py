"""Agent packaging — export and import agent archives."""

from __future__ import annotations

import os
import shutil
import tarfile
import tempfile
from typing import List, Union

from ..errors import AgentValidationError
from .definition import AgentDefinition, load_agent_definition
from .manifest import AgentManifest, load_agent_manifest


def export_agent(manifest: AgentManifest, output_path: str, project_root: str = ".") -> str:
    """Bundle an agent manifest and its files into a ``.tar.gz`` archive.

    The archive contains:
    - ``agent.yaml`` (the manifest)
    - All handler files listed in the manifest
    - All tool files listed in the manifest
    - The workflow file

    Returns the absolute path of the created archive.
    """
    if not manifest.manifest_path:
        raise AgentValidationError("Manifest has no source path; cannot export.")

    # Collect all files to include
    files_to_pack: List[tuple] = []  # (source_abs, archive_relative)

    # Manifest itself
    files_to_pack.append((manifest.manifest_path, "agent.yaml"))

    # Workflow
    wf_abs = os.path.join(project_root, manifest.workflow)
    if not os.path.isfile(wf_abs):
        raise AgentValidationError(f"Workflow file not found: {wf_abs}")
    files_to_pack.append((os.path.abspath(wf_abs), manifest.workflow))

    # Handlers
    for h in manifest.handlers:
        h_abs = os.path.join(project_root, h)
        if not os.path.isfile(h_abs):
            raise AgentValidationError(f"Handler file not found: {h_abs}")
        files_to_pack.append((os.path.abspath(h_abs), h))

    # Tools
    for t in manifest.tools:
        t_abs = os.path.join(project_root, t)
        if not os.path.isfile(t_abs):
            raise AgentValidationError(f"Tool file not found: {t_abs}")
        files_to_pack.append((os.path.abspath(t_abs), t))

    # Build the archive
    os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)
    with tarfile.open(output_path, "w:gz") as tar:
        for source_path, arcname in files_to_pack:
            tar.add(source_path, arcname=arcname)

    return os.path.abspath(output_path)


def import_agent(archive_path: str, project_root: str = ".") -> Union[AgentManifest, AgentDefinition]:
    """Import an agent archive into the project.

    Extracts the archive, copies files into the project tree, and places
    the agent YAML in ``agents/``.

    Supports both definition-format and manifest-format archives.

    Returns the loaded agent (``AgentDefinition`` or ``AgentManifest``).
    """
    if not os.path.isfile(archive_path):
        raise AgentValidationError(f"Archive not found: {archive_path}")

    abs_project_root = os.path.abspath(project_root)

    with tempfile.TemporaryDirectory() as tmp_dir:
        # Extract to temp
        with tarfile.open(archive_path, "r:gz") as tar:
            for member in tar.getmembers():
                member_path = os.path.normpath(member.name)
                if member_path.startswith("..") or os.path.isabs(member_path):
                    raise AgentValidationError(
                        f"Unsafe path in archive: {member.name}"
                    )
                if member.issym() or member.islnk():
                    raise AgentValidationError(
                        f"Symlink or hard link not allowed in archive: {member.name}"
                    )
            tar.extractall(tmp_dir)

        # Load agent from extracted files
        agent_yaml_path = os.path.join(tmp_dir, "agent.yaml")
        if not os.path.isfile(agent_yaml_path):
            raise AgentValidationError("Archive does not contain agent.yaml")

        # Try definition format first (canonical), fall back to manifest
        agent_def = None
        try:
            agent_def = load_agent_definition(agent_yaml_path)
        except Exception:
            pass

        if agent_def is not None:
            # Definition-format: self-contained, just copy to agents/
            agents_dir = os.path.join(project_root, "agents")
            os.makedirs(agents_dir, exist_ok=True)
            dst = os.path.join(agents_dir, f"{agent_def.agent_id}.yaml")
            shutil.copy2(agent_yaml_path, dst)
            return load_agent_definition(dst)

        # Legacy manifest format
        manifest = load_agent_manifest(agent_yaml_path)

        def _safe_copy(rel_path: str, label: str) -> None:
            """Copy a file from tmp extraction into project_root, rejecting traversal."""
            resolved = os.path.normpath(os.path.join(abs_project_root, rel_path))
            if resolved != abs_project_root and not resolved.startswith(abs_project_root + os.sep):
                raise AgentValidationError(
                    f"{label} path escapes project root: {rel_path}"
                )
            src = os.path.join(tmp_dir, rel_path)
            if os.path.isfile(src):
                os.makedirs(os.path.dirname(resolved) or ".", exist_ok=True)
                shutil.copy2(src, resolved)

        # Copy workflow
        _safe_copy(manifest.workflow, "Workflow")

        # Copy handlers
        for h in manifest.handlers:
            _safe_copy(h, "Handler")

        # Copy tools
        for t in manifest.tools:
            _safe_copy(t, "Tool")

        # Place manifest in agents/ directory
        agents_dir = os.path.join(project_root, "agents")
        os.makedirs(agents_dir, exist_ok=True)
        dst_manifest = os.path.join(
            agents_dir, f"{manifest.agent_id}.yaml"
        )
        shutil.copy2(agent_yaml_path, dst_manifest)

        # Reload from final location
        return load_agent_manifest(dst_manifest)
