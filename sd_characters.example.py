"""
sd_characters.py — Character preset definitions
Copy this file to sd_characters.py and fill in your own characters.

Usage:
  cp sd_characters.example.py sd_characters.py
"""

# Core BASE prompt shared by all characters
BASE = (
    "1girl, masterpiece, 8k, photorealistic, cinematic soft lighting, "
    "# ... add your base prompt here ..."
)

CHARACTERS: dict[str, dict] = {
    "character1": {
        "name": "Character One",
        "emoji": "🌸",
        "description": "Short vibe description",
        "base": "hair color, personality tags, style tags",
        "scenes": {
            "S1": {
                "name": "Scene Name",
                "prompt": "scene description, background, pose, lighting",
            },
            "S2": {
                "name": "Scene Name 2",
                "prompt": "scene description, background, pose, lighting",
            },
            "S3": {
                "name": "Scene Name 3",
                "prompt": "scene description, background, pose, lighting",
            },
        },
    },
    # Add more characters...
}


def build_prompt(character_id: str, scene_id: str | None = None, extra: str = "") -> str:
    """Assemble full prompt from BASE + character base + scene."""
    char = CHARACTERS[character_id]
    scene_id = scene_id or "S1"
    scene = char["scenes"][scene_id]
    parts = [BASE, char["base"], scene["prompt"]]
    if extra:
        parts.append(extra)
    return ", ".join(p.strip(", ") for p in parts if p)


def list_characters() -> list[dict]:
    return [
        {
            "id": cid,
            "name": c["name"],
            "emoji": c["emoji"],
            "description": c["description"],
            "scenes": {sid: s["name"] for sid, s in c["scenes"].items()},
        }
        for cid, c in CHARACTERS.items()
    ]
