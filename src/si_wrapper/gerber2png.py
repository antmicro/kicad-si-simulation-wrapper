"""Script that creates bitmaps from gerbers."""

import logging
import subprocess
import sys
from typing import Annotated
from pathlib import Path
from si_wrapper.generate_slices import setup_logging
import typer
from typing import List, Optional

logger = logging.getLogger(__name__)
app = typer.Typer()


def process_gbrs(img_dir: Optional[Path] = None, no_png: bool = False) -> None:
    """Process all gerber files to images.

    Finds edge cuts gerber as well as copper gerbers in `fab` directory.
    Processes copper gerbers into PNG/SVG's using edge_cuts for framing.
    """
    cwd = Path.cwd()
    if img_dir is None:
        img_dir = Path.cwd()
    fab_dir = cwd / "fab"

    img_dir.mkdir(exist_ok=True, parents=True)

    edge = next(fab_dir.glob("*Edge_Cuts.gbr"), None)
    if edge is None:
        logger.error("No edge_cuts gerber found")
        sys.exit(1)

    layers = {
        "F_Cu": list(fab_dir.glob("*F_Cu.gbr"))[0:1],
        "B_Cu": list(fab_dir.glob("*B_Cu.gbr"))[0:1],
        "In_Cu": list(fab_dir.glob("*-In*")),
    }
    # Split top and bootom into two images
    # Reduce inner layers to one image
    for name, in_file in layers.items():
        gerbv_call(in_file, fab_dir / edge, img_dir / name, no_png)


def gerbv_call(gerber_filenames: List[Path], edge_filename: Path, output_filename: Path, no_png: bool) -> None:
    """Generate PNG/SVG from gerber file.

    Generates PNG/SVG of a gerber using gerbv.
    Edge cuts gerber is used to crop the image correctly.
    """
    color_array = ["--background=#FFFFFF"]
    color_array.extend("--foreground=#000000FF" for _ in gerber_filenames)
    color_array.append("--foreground=#FFFFFF")
    dpi = 2000
    cmd = ["gerbv"] + gerber_filenames + [edge_filename, "-a", f"--dpi={dpi}"] + color_array

    if not no_png:
        cmd_png = cmd + ["-o", output_filename.with_suffix(".png"), "--export=png", "--border=0"]
        logger.debug(f"Generating PNG, CMD: {cmd_png}")
        subprocess.call(cmd_png, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    cmd_svg = cmd + ["-o", output_filename.with_suffix(".svg"), "--export=svg", "--border=5"]
    logger.debug(f"Generating SVG, CMD: {cmd_svg}")
    subprocess.call(cmd_svg, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


@app.command("gerber2png")
def main(
    debug: Annotated[bool, typer.Option("--debug", help="Increase logs verbosity")] = False,
    no_png: Annotated[bool, typer.Option("--no-png", help="Skip export to png")] = False,
) -> None:
    """Process gerbers to png/svg."""
    setup_logging(debug)
    process_gbrs(Path.cwd(), no_png)


if __name__ == "__main__":
    app()
