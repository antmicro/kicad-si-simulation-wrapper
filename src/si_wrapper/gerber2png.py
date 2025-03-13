"""Script that creates bitmaps from gerbers."""

import logging
import os
import subprocess
import sys

import typer

logger = logging.getLogger(__name__)
app = typer.Typer()


def process_gbrs_to_pngs() -> None:
    """Process all gerber files to PNG's.

    Finds edge cuts gerber as well as copper gerbers in `fab` directory.
    Processes copper gerbers into PNG's using edge_cuts for framing.
    """
    img_dir = "."

    if not os.path.exists(img_dir):
        os.makedirs(img_dir)

    files = os.listdir(os.path.join(os.getcwd(), "fab"))
    edge = next(filter(lambda name: "Edge_Cuts.gbr" in name, files), None)
    if edge is None:
        logger.error("No edge_cuts gerber found")
        sys.exit(1)

    layers = [
        list(filter(lambda name: "F_Cu.gbr" in name, files))[0],
        list(filter(lambda name: "B_Cu.gbr" in name, files))[0],
    ]
    layers_in = list(filter(lambda name: "-In" in name, files))

    if len(layers) == 0:
        logger.warning("No copper gerbers found")

    # Split top and bootom into two images
    for name in layers:
        output = name.split("-")[-1].split(".")[0] + ".png"
        fb_gbr2png(
            os.path.join(os.getcwd(), "fab", name),
            os.path.join(os.getcwd(), "fab", edge),
            os.path.join(os.getcwd(), img_dir, output),
        )

    # Reduce inner layers to one image
    output = "In_Cu.png"
    in_gbr2png(
        [os.path.join(os.getcwd(), "fab", name) for name in layers_in],
        os.path.join(os.getcwd(), "fab", edge),
        os.path.join(os.getcwd(), img_dir, output),
    )


def in_gbr2png(gerber_filenames: list[str], edge_filename: str, output_filename: str) -> None:
    """Generate PNG from gerber file.

    Generates PNG of a gerber using gerbv.
    Edge cuts gerber is used to crop the image correctly.
    """
    dpi = 1000

    foreground_array = [" --foreground=#ffffff"] * len(gerber_filenames)
    foreground_array.append(" --foreground=#000000")

    gerbv_command = f'gerbv {" ".join(gerber_filenames)} {edge_filename}'
    gerbv_command += f' {" ".join(foreground_array)}'
    gerbv_command += f" -o {output_filename}"
    gerbv_command += f" --dpi={dpi} --export=png -a  --border=0"
    subprocess.call(gerbv_command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=True)


def fb_gbr2png(gerber_filename: str, edge_filename: str, output_filename: str) -> None:
    """Generate PNG from gerber file.

    Generates PNG of a gerber using gerbv.
    Edge cuts gerber is used to crop the image correctly.
    """
    dpi = 1000

    logger.debug("Generating PNG for %s", gerber_filename)

    gerbv_command = f"gerbv {gerber_filename} {edge_filename}"
    gerbv_command += " --background=#000000 --foreground=#ffffffff --foreground=#000000"
    gerbv_command += f" -o {output_filename}"
    gerbv_command += f" --dpi={dpi} --export=png -a --border=0"
    subprocess.call(gerbv_command, shell=True)


@app.command("gerber2png")
def main():
    """Process gerbers to png."""
    process_gbrs_to_pngs()


if __name__ == "__main__":
    app()
