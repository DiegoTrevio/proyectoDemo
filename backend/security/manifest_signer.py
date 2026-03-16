"""Manifest Signing — Ed25519 signatures for system prompts and agent configs.

Ensures that system prompts and agent configurations have not been tampered with.
If a signature doesn't match, the agent refuses to start.
"""

import hashlib
import json
import logging
import os
from dataclasses import dataclass

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from config.settings import settings

logger = logging.getLogger("agentos.security.manifest")


@dataclass
class ManifestEntry:
    """A signed manifest entry."""
    path: str
    content_hash: str
    signature: str  # hex-encoded Ed25519 signature


class ManifestSigner:
    """Signs and verifies agent manifests using Ed25519."""

    def __init__(self):
        self._private_key: Ed25519PrivateKey | None = None
        self._public_key: Ed25519PublicKey | None = None
        self._manifests: dict[str, ManifestEntry] = {}
        self._initialized = False

    def initialize(self, signing_key: str = "") -> bool:
        """Initialize signing keys.

        Args:
            signing_key: Hex-encoded Ed25519 private key seed (32 bytes).
                         If empty, generates a new keypair.

        Returns:
            True if initialized successfully.
        """
        try:
            key_hex = signing_key or os.environ.get("MANIFEST_SIGNING_KEY", "")

            if key_hex and len(key_hex) >= 64:
                # Load from seed
                seed = bytes.fromhex(key_hex[:64])
                self._private_key = Ed25519PrivateKey.from_private_bytes(seed)
            else:
                # Generate new keypair
                self._private_key = Ed25519PrivateKey.generate()
                seed = self._private_key.private_bytes(
                    serialization.Encoding.Raw,
                    serialization.PrivateFormat.Raw,
                    serialization.NoEncryption(),
                )
                logger.info(
                    "Generated new manifest signing key. "
                    "Set MANIFEST_SIGNING_KEY=%s in .env to persist.",
                    seed.hex(),
                )

            self._public_key = self._private_key.public_key()
            self._initialized = True
            logger.info("Manifest signer initialized")
            return True

        except Exception as e:
            logger.error("Failed to initialize manifest signer: %s", e)
            return False

    @property
    def available(self) -> bool:
        return self._initialized and self._private_key is not None

    def sign_manifest(self, content: str) -> str:
        """Sign content and return hex-encoded signature."""
        if not self.available:
            self.initialize()
        if not self._private_key:
            raise RuntimeError("Manifest signer not initialized")

        content_hash = self._hash(content)
        signature = self._private_key.sign(content_hash.encode())
        return signature.hex()

    def verify_manifest(self, content: str, signature: str) -> bool:
        """Verify that content matches its signature."""
        if not self.available:
            self.initialize()
        if not self._public_key:
            return False

        try:
            content_hash = self._hash(content)
            sig_bytes = bytes.fromhex(signature)
            self._public_key.verify(sig_bytes, content_hash.encode())
            return True
        except Exception:
            return False

    def sign_agent_prompt(self, agent_name: str, system_prompt: str) -> ManifestEntry:
        """Sign an agent's system prompt and register it."""
        signature = self.sign_manifest(system_prompt)
        entry = ManifestEntry(
            path=f"agents/{agent_name}/system_prompt",
            content_hash=self._hash(system_prompt),
            signature=signature,
        )
        self._manifests[entry.path] = entry
        logger.debug("Signed manifest for %s", entry.path)
        return entry

    def verify_agent_prompt(self, agent_name: str, system_prompt: str) -> bool:
        """Verify an agent's system prompt against its signed manifest.

        Returns True if the prompt is valid (matches signature or no manifest exists).
        """
        path = f"agents/{agent_name}/system_prompt"
        entry = self._manifests.get(path)

        if entry is None:
            # No manifest registered — first run, sign it
            self.sign_agent_prompt(agent_name, system_prompt)
            return True

        current_hash = self._hash(system_prompt)
        if current_hash != entry.content_hash:
            logger.critical(
                "MANIFEST VIOLATION: Agent '%s' system prompt has been modified! "
                "Expected hash %s, got %s",
                agent_name, entry.content_hash[:12], current_hash[:12],
            )
            return False

        if not self.verify_manifest(system_prompt, entry.signature):
            logger.critical(
                "MANIFEST VIOLATION: Agent '%s' signature verification failed!",
                agent_name,
            )
            return False

        return True

    def export_manifests(self) -> dict:
        """Export all signed manifests as JSON-serializable dict."""
        return {
            path: {
                "path": entry.path,
                "content_hash": entry.content_hash,
                "signature": entry.signature,
            }
            for path, entry in self._manifests.items()
        }

    def load_manifests(self, data: dict) -> int:
        """Load manifests from exported data. Returns count loaded."""
        count = 0
        for path, entry_data in data.items():
            self._manifests[path] = ManifestEntry(**entry_data)
            count += 1
        return count

    @staticmethod
    def _hash(content: str) -> str:
        return hashlib.sha256(content.encode()).hexdigest()


# Singleton
manifest_signer = ManifestSigner()


# ── CLI ──────────────────────────────────────────────────────────────────

def _cli():
    """CLI for signing agent manifests: python -m security.manifest_signer sign agents/"""
    import sys

    if len(sys.argv) < 3:
        print("Usage: python -m security.manifest_signer sign <directory>")
        print("       python -m security.manifest_signer verify <directory>")
        sys.exit(1)

    command = sys.argv[1]
    directory = sys.argv[2]

    manifest_signer.initialize()

    if command == "sign":
        import glob
        files = glob.glob(os.path.join(directory, "*.py"))
        manifests = {}
        for filepath in files:
            with open(filepath) as f:
                content = f.read()
            entry = ManifestEntry(
                path=filepath,
                content_hash=ManifestSigner._hash(content),
                signature=manifest_signer.sign_manifest(content),
            )
            manifests[filepath] = {
                "path": entry.path,
                "content_hash": entry.content_hash,
                "signature": entry.signature,
            }
            print(f"  Signed: {filepath}")

        output = os.path.join(directory, "manifests.json")
        with open(output, "w") as f:
            json.dump(manifests, f, indent=2)
        print(f"\nManifests written to {output}")

    elif command == "verify":
        manifest_file = os.path.join(directory, "manifests.json")
        if not os.path.exists(manifest_file):
            print(f"No manifests.json found in {directory}")
            sys.exit(1)

        with open(manifest_file) as f:
            manifests = json.load(f)

        all_valid = True
        for filepath, entry_data in manifests.items():
            if not os.path.exists(filepath):
                print(f"  MISSING: {filepath}")
                all_valid = False
                continue

            with open(filepath) as f:
                content = f.read()

            current_hash = ManifestSigner._hash(content)
            if current_hash != entry_data["content_hash"]:
                print(f"  MODIFIED: {filepath}")
                all_valid = False
            else:
                print(f"  OK: {filepath}")

        sys.exit(0 if all_valid else 1)


if __name__ == "__main__":
    _cli()
