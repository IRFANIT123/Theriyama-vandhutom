from pathlib import Path

from reportlab.graphics import renderPM
from svglib.svglib import svg2rlg


source = Path(r"C:\2nd year fall\campus _ nav e block\f0\E Block - Ground Floor.svg")
target = Path(r"C:\2nd year fall\campus _ nav e block\.impeccable\mocks\decision\ground-floor-reference.png")
target.parent.mkdir(parents=True, exist_ok=True)
drawing = svg2rlg(str(source))
renderPM.drawToFile(drawing, str(target), fmt="PNG", dpi=180)
