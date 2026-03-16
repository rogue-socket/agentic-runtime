"""Agent packaging — export and import agent archives."""

from __future__ import annotations

import os
import shutil
import tarfile
import tempfile
from typing import List

from ..errors import AgentValidationError
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


def import_agent(archive_path: str, project_root: str = ".") -> AgentManifest:
    """Import an agent archive into the project.

    Extracts the archive, copies files into the project tree, and places
    the manifest in ``agents/``.

    Returns the loaded :class:`AgentManifest` from the imported files.
    """
    if not os.path.isfile(archive_path):
        raise AgentValidationError(f"Archive not found: {archive_path}")

    with tempfile.TemporaryDirectory() as tmp_dir:
        # Extract to temp
        with tarfile.open(archive_path, "r:gz") as tar:
            # Security: reject paths that escape the extraction directory
            for member in tar.getmembers():
                member_path = os.path.normpath(member.name)
                if member_path.startswith("..") or os.path.isabs(member_path):
                    raise AgentValidationError(
                        f"Unsafe path in archive: {member.name}"
                    )
            tar.extractall(tmp_dir)

        # Load manifest from extracted files
        manifest_path = os.path.join(tmp_dir, "agent.yaml")
        if not os.path.isfile(manifest_path):
            raise AgentValidationError("Archive does not contain agent.yaml")

        manifest = load_agent_manifest(manifest_path)

        # Copy workflow
        src_wf = os.path.join(tmp_dir, manifest.workflow)
        dst_wf = os.path.join(project_root, manifest.workflow)
        if os.path.isfile(src_wf):
            os.makedirs(os.path.dirname(dst_wf) or ".", exist_ok=True)
            shutil.copy2(src_wf, dst_wf)

        # Copy handlers
        for h in manifest.handlers:
            src = os.path.join(tmp_dir, h)
            dst = os.path.join(project_root, h)
            if os.path.isfile(src):
                os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
                shutil.copy2(src, dst)

        # Copy tools
        for t in manifest.tools:
            src = os.path.join(tmp_dir, t)
            dst = os.path.join(project_root, t)
            if os.path.isfile(src):
                os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
                shutil.copy2(src, dst)

        # Place manifest in agents/ directory
        agents_dir = os.path.join(project_root, "agents")
        os.makedirs(agents_dir, exist_ok=True)
        dst_manifest = os.path.join(
            agents_dir, f"{manifest.agent_id}.yaml"
        )
        shutil.copy2(manifest_path, dst_manifest)

        # Reload from final location
        return load_agent_manifest(dst_manifest)
