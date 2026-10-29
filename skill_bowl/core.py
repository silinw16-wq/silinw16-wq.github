import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

MAX_SKILL_BYTES = 65536
ID = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")

@dataclass(frozen=True)
class Skill:
    id: str
    name: str
    description: str
    instructions: str

@dataclass(frozen=True)
class Settings:
    skills_dir: Path
    api_token: str
    model_url: str = ""
    model_name: str = ""
    model_key: str = ""
    timeout: float = 30

    @classmethod
    def from_env(cls):
        return cls(Path(os.getenv("SKILL_BOWL_SKILLS_DIR", "skills")),
                   os.getenv("SKILL_BOWL_API_TOKEN", ""),
                   os.getenv("MODEL_API_URL", ""), os.getenv("MODEL_NAME", ""),
                   os.getenv("MODEL_API_KEY", ""),
                   float(os.getenv("MODEL_TIMEOUT_SECONDS", "30")))

    def validate(self):
        if len(self.api_token) < 24:
            raise ValueError("SKILL_BOWL_API_TOKEN must contain at least 24 characters")
        if not 0 < self.timeout <= 120:
            raise ValueError("MODEL_TIMEOUT_SECONDS must be between 0 and 120")
        if self.model_url:
            url = urlsplit(self.model_url)
            if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
                raise ValueError("MODEL_API_URL must be an HTTPS endpoint without credentials, query or fragment")

def read_private(path, limit):
    if path.is_symlink() or not path.is_file():
        raise ValueError("Skill files must be regular files, not symlinks")
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Skill file is too large")
    return data.decode("utf-8")

def load_skills(directory):
    directory = directory.resolve(strict=True)
    if not directory.is_dir():
        raise ValueError("Skills directory is not a directory")
    loaded = {}
    for folder in sorted(directory.iterdir()):
        if folder.is_symlink():
            raise ValueError("Symlinks are not allowed in skills directory")
        if not folder.is_dir():
            continue
        manifest = json.loads(read_private(folder / "manifest.json", 8192))
        if not isinstance(manifest, dict) or set(manifest) != {"id", "name", "description", "type", "enabled"}:
            raise ValueError("Invalid manifest fields")
        if not isinstance(manifest["id"], str) or not ID.fullmatch(manifest["id"]):
            raise ValueError("Invalid skill id")
        if manifest["id"] in loaded:
            raise ValueError("Duplicate skill id")
        if manifest["type"] != "markdown" or type(manifest["enabled"]) is not bool:
            raise ValueError("Only markdown skills with boolean enabled are supported")
        for key, limit in (("name", 100), ("description", 500)):
            if not isinstance(manifest[key], str) or not 0 < len(manifest[key]) <= limit:
                raise ValueError("Invalid skill metadata")
        instructions = read_private(folder / "SKILL.md", MAX_SKILL_BYTES)
        if not instructions.strip():
            raise ValueError("Empty SKILL.md")
        # Track disabled IDs too, so duplicates never depend on enable order.
        loaded[manifest["id"]] = (manifest, instructions)
    return {key: Skill(key, m["name"], m["description"], text)
            for key, (m, text) in loaded.items() if m["enabled"]}
