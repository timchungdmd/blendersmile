import re

# Collections
COL_SCANS   = "Scans"
COL_TEETH   = "Teeth"
COL_LM      = "SmileLandmarks"
COL_ARCH    = "SmileArch"
COL_PREVIEW = "SmilePreview"
COL_WAXUP   = "Waxup"
COL_VENEER  = "Veneers"
COL_RIG     = "SmileRig"
COL_MARGINS = "VeneerMargins"

# Domains
DOMAIN_FACE = "FACE"
DOMAIN_MAX  = "MAX"
DOMAIN_MAN  = "MAN"
DOMAINS = (DOMAIN_FACE, DOMAIN_MAX, DOMAIN_MAN)
DOMAIN_SHAPE = {DOMAIN_FACE: "SPHERE", DOMAIN_MAX: "CUBE", DOMAIN_MAN: "CONE"}

# Colors
NEON = [
    (1.00, 0.05, 0.55, 1.0), (0.10, 1.00, 0.10, 1.0),
    (0.10, 0.65, 1.00, 1.0), (1.00, 1.00, 0.10, 1.0),
    (1.00, 0.45, 0.05, 1.0), (0.10, 1.00, 0.95, 1.0),
    (0.75, 0.10, 1.00, 1.0), (1.00, 1.00, 1.00, 1.0),
]

# Keys
KEY_ARCH_MAX_PTS = "SMILE_ARCH_MAX_PTS"
KEY_ARCH_MAN_PTS = "SMILE_ARCH_MAN_PTS"
KEY_MARGIN_PREFIX = "SMILE_MARGIN_PTS_"

# Regex
FDI_REGEX = re.compile(r"#\s*(\d{2})")
SUPPORTED_EXTS = {
    ".obj", ".stl", ".ply", ".fbx", ".gltf", ".glb",
    ".usd", ".usda", ".usdc", ".usdz", ".abc", ".dae"
}
